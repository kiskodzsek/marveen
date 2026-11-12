import { existsSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import {
  listPendingTaskRetries, deletePendingTaskRetryById, listTaskRunHistory, getAgentMessage, createSystemMessage,
} from '../../db.js'
import { MAIN_AGENT_ID, currentBotName, PROJECT_ROOT, WEB_PORT, DASHBOARD_PUBLIC_URL, AGENT_API_ORIGIN } from '../../config.js'
import { runAgent } from '../../agent.js'
import { logger } from '../../logger.js'
import { toPendingRetryView } from '../../pending-retries.js'
import { atomicWriteFileSync } from '../atomic-write.js'
import { isValidCronShape, effectiveCronTz } from '../cron.js'
import { readBody, json, RequestBodyTooLargeError } from '../http-helpers.js'
import { sanitizeScheduleName, safeJoin } from '../sanitize.js'
import { listAgentNames } from '../agent-config.js'
import { readFileOr, readJsonObjectForWrite } from '../agent-config.js'
import {
  SCHEDULED_TASKS_DIR, MAX_SCHEDULED_TASK_PROMPT_LEN,
  listScheduledTasks, writeScheduledTask, markDefaultTaskRemoved, readScheduledTask,
} from '../scheduled-tasks-io.js'
import { validateScheduleUpdate, scheduleCreateRefusal, COMMAND_TASK_API_REFUSAL } from '../schedule-api-fields.js'
import { runScheduledTaskNow } from '../schedule-runner.js'
import { createOnceTask, readOnceAnchors, recordOnceAnchor, shouldAlertCap, isOnceTask, ONCE_EDIT_REFUSAL, type OnceRequestBody } from '../once-schedule.js'
import { resolveDashboardOrigin } from '../agent-scaffold.js'
import type { RouteContext } from './types.js'

// The `agent` values the API accepts: exactly what GET /api/schedules/agents offers.
function scheduleAgentIds(): Set<string> {
  return new Set([MAIN_AGENT_ID, ...listAgentNames()])
}

// Resolve a URL-supplied schedule name to an on-disk dir, blocking path
// traversal. sanitizeScheduleName strips everything outside [a-z0-9-] (so no
// "." or "/" survives), the empty check rejects a name that sanitized away
// (which would otherwise resolve to the tasks root and delete/overwrite it),
// and safeJoin is a belt-and-suspenders guard against escaping the base.
function resolveScheduleDir(rawName: string): { name: string; dir: string } | null {
  let decoded: string
  try { decoded = decodeURIComponent(rawName) } catch { return null }
  const name = sanitizeScheduleName(decoded)
  if (!name) return null
  try {
    return { name, dir: safeJoin(SCHEDULED_TASKS_DIR, name) }
  } catch { return null }
}

// HBSCHEDSZAM903: the hourly heartbeat digest's "enabled schedules" figure was
// the ONE number the agent computed itself (counting enabled:true in the raw
// /api/schedules array), and it drifted to a 13x error (376 reported vs 29
// real). Serve the counts pre-computed so the digest copies a number instead
// of deriving one. Pure and exported so the counting rule is unit-testable.
export function summarizeScheduledTasks(tasks: Array<{ enabled?: boolean }>): { total: number; enabled: number; disabled: number } {
  // The same rule the toggle route uses: a task is enabled unless enabled is
  // explicitly false (absent field = enabled).
  const enabled = tasks.filter(t => t.enabled !== false).length
  return { total: tasks.length, enabled, disabled: tasks.length - enabled }
}

export async function tryHandleSchedules(ctx: RouteContext): Promise<boolean> {
  const { req, res, path, method } = ctx

  if (path === '/api/schedules/agents' && method === 'GET') {
    const agentNames = listAgentNames()
    const agents = [
      { name: MAIN_AGENT_ID, label: currentBotName(), avatar: '/api/marveen/avatar' },
      ...agentNames.map(n => ({ name: n, label: n, avatar: `/api/agents/${encodeURIComponent(n)}/avatar` }))
    ]
    json(res, agents)
    return true
  }

  if (path === '/api/schedules/expand-questions' && method === 'POST') {
    const body = await readBody(req)
    const { prompt, agent } = JSON.parse(body.toString()) as { prompt: string; agent?: string }
    if (!prompt?.trim()) { json(res, { error: 'Prompt is required' }, 400); return true }

    const aiPrompt = `A felhasznalo egy utemezett feladatot akar letrehozni egy AI agensnek. A rovid leirasa:
"${prompt.trim()}"
${agent ? `Az agens neve: ${agent}` : ''}

Generalj 3-4 feleletvalasztos kerdest, amivel pontositani lehet a feladatot. Minden kerdeshez adj 2-4 valaszlehetoseget.

Valaszolj KIZAROLAG JSON formatumban, semmi mas:
[
  {"question": "Kerdes szovege?", "options": ["Opcio 1", "Opcio 2", "Opcio 3"]},
  {"question": "Masik kerdes?", "options": ["A", "B"]}
]`

    try {
      const { text } = await runAgent(aiPrompt)
      if (!text) throw new Error('No response')
      const jsonMatch = text.match(/\[[\s\S]*\]/)
      if (!jsonMatch) throw new Error('Invalid response format')
      const questions = JSON.parse(jsonMatch[0])
      json(res, questions)
    } catch (err) {
      logger.error({ err }, 'Failed to generate expand questions')
      json(res, { error: 'Failed to generate questions' }, 500)
    }
    return true
  }

  if (path === '/api/schedules/expand-prompt' && method === 'POST') {
    const body = await readBody(req)
    const { prompt, answers } = JSON.parse(body.toString()) as { prompt: string; answers: { question: string; answer: string }[] }
    if (!prompt?.trim()) { json(res, { error: 'Prompt is required' }, 400); return true }

    const answersText = answers.map((a: { question: string; answer: string }) => `Kerdes: ${a.question}\nValasz: ${a.answer}`).join('\n\n')

    const aiPrompt = `Bovitsd ki ezt a rovid feladat-leirast egy reszletes, egyertelmu promptta amit egy AI asszisztens vegre tud hajtani.
A prompt legyen magyar nyelvu, konkret utasitasokkal.

Rovid leiras: "${prompt.trim()}"

A felhasznalo valaszai a pontosito kerdesekre:
${answersText}

Az eredmeny CSAK a kibovitett prompt szovege legyen, semmi mas. Ne hasznalj code fence-t.`

    try {
      const { text } = await runAgent(aiPrompt)
      if (!text) throw new Error('No response')
      let expanded = text.trim()
      if (expanded.startsWith('```')) expanded = expanded.replace(/^```\w*\n?/, '').replace(/\n?```$/, '')
      json(res, { prompt: expanded })
    } catch (err) {
      logger.error({ err }, 'Failed to expand prompt')
      json(res, { error: 'Failed to expand prompt' }, 500)
    }
    return true
  }

  if (path === '/api/schedules' && method === 'GET') {
    json(res, listScheduledTasks())
    return true
  }

  if (path === '/api/schedules/summary' && method === 'GET') {
    json(res, summarizeScheduledTasks(listScheduledTasks()))
    return true
  }

  // ONCE (card fd941954): the ONE schedule write a sub-agent may make (the
  // self-pace gate lets exactly this path through). All rules are in
  // once-schedule.ts; this handler only does the I/O around them.
  if (path === '/api/schedules/once' && method === 'POST') {
    let body: Buffer
    try {
      body = await readBody(req, { maxBytes: 16 * 1024 })
    } catch (err) {
      if (err instanceof RequestBodyTooLargeError) {
        json(res, { error: `Request body too large (max ${err.limit} bytes)` }, 413)
        return true
      }
      throw err
    }
    let data: OnceRequestBody
    try {
      const parsed: unknown = JSON.parse(body.toString())
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('not an object')
      data = parsed as OnceRequestBody
    } catch {
      json(res, { error: 'Body must be a JSON object' }, 400)
      return true
    }
    // ATOMIC (Viktor 38878 #5): from here to the response there is no await, so
    // the deps read below and the ledger append inside createOnceTask are one
    // uninterruptible stretch on the single-threaded dashboard.
    const now = Date.now()
    // Viktor 38943 #5: a damaged ledger fails closed -- no once-task until a
    // human has looked, and the main agent hears about it (once a day).
    const ledger = readOnceAnchors()
    if (ledger.malformed > 0) {
      if (shouldAlertCap('ledger', 'agent-day', now)) {
        try {
          createSystemMessage(MAIN_AGENT_ID, `[ONCE-LEDGER] store/once-schedule-anchors.jsonl: ${ledger.malformed} sor nem értelmezhető. Egyszeri ébresztés addig nem kérhető; a fájlt ember nézze meg (append-only, a sérült sort ne töröld vakon).`)
        } catch (err) {
          logger.warn({ err }, 'once-schedule: ledger alert could not be queued')
        }
      }
      json(res, { error: 'once-schedule ledger is damaged; the main agent has been told' }, 503)
      return true
    }
    const verdict = createOnceTask(data, {
      now,
      knownAgents: scheduleAgentIds(),
      getMessage: (id) => getAgentMessage(id),
      anchors: ledger.anchors,
      pendingOnceCount: (agent) => listScheduledTasks().filter(t => t.runAt != null && t.agent === agent).length,
      tz: effectiveCronTz().tz,
      dashboardOrigin: resolveDashboardOrigin(DASHBOARD_PUBLIC_URL, WEB_PORT, AGENT_API_ORIGIN),
      tokenPath: join(PROJECT_ROOT, 'store', '.dashboard-token'),
    }, {
      taskExists: (name) => existsSync(join(SCHEDULED_TASKS_DIR, name)),
      recordAnchor: (rec) => recordOnceAnchor(rec),
      writeTask: (plan) => writeScheduledTask(plan.name, {
        description: plan.description,
        prompt: plan.prompt,
        schedule: plan.schedule,
        agent: plan.agent,
        enabled: true,
        type: 'task',
        // A self-reminder: the result goes nowhere by itself (the woken turn
        // reports on its own channel, as for its anchor message).
        telegramChatId: 'none',
        runAt: plan.runAt,
        originMsgId: plan.originMsgId,
      }),
      // CAPS (Viktor 38878 #1): a cap hit is a loop suspicion, not just a 429.
      alertCap: (agent, cap, error) => {
        if (!shouldAlertCap(agent, cap, now)) return
        try {
          createSystemMessage(MAIN_AGENT_ID, `[ONCE-PLAFON] ${agent}: egyszeri ébresztés elutasítva (${cap}). ${error}. Hurok-gyanú: nézd meg, mi kéri ilyen sűrűn (store/once-schedule-anchors.jsonl).`)
        } catch (err) {
          logger.warn({ err, agent, cap }, 'once-schedule: cap alert could not be queued')
        }
      },
    })
    if (!verdict.ok) { json(res, { error: verdict.error }, verdict.status); return true }
    const plan = verdict.plan
    logger.info(
      { name: plan.name, agent: plan.agent, runAt: new Date(plan.runAt).toISOString(), originMsgId: plan.originMsgId, claimedBy: ctx.auth?.agent },
      'One-shot task created',
    )
    json(res, { ok: true, name: plan.name, runAt: new Date(plan.runAt).toISOString(), schedule: plan.schedule })
    return true
  }

  if (path === '/api/schedules' && method === 'POST') {
    let body: Buffer
    try {
      body = await readBody(req, { maxBytes: 256 * 1024 })
    } catch (err) {
      if (err instanceof RequestBodyTooLargeError) {
        json(res, { error: `Request body too large (max ${err.limit} bytes)` }, 413)
        return true
      }
      throw err
    }
    const data = JSON.parse(body.toString()) as {
      name: string; description: string; prompt: string; schedule: string; agent?: string; type?: string; skipIfBusy?: boolean; forceSend?: boolean; targetSession?: string
    }
    const name = sanitizeScheduleName(data.name || '')
    if (!name) { json(res, { error: 'Name is required' }, 400); return true }
    if (!data.prompt?.trim()) { json(res, { error: 'Prompt is required' }, 400); return true }
    if (data.prompt.length > MAX_SCHEDULED_TASK_PROMPT_LEN) {
      json(res, {
        error: `Prompt too large (${data.prompt.length} chars, max ${MAX_SCHEDULED_TASK_PROMPT_LEN})`,
      }, 413)
      return true
    }
    if (!data.schedule?.trim()) { json(res, { error: 'Schedule is required' }, 400); return true }
    if (!isValidCronShape(data.schedule)) { json(res, { error: 'Invalid cron expression' }, 400); return true }
    // RESERVEDSENDER1013: who runs it and as what -- see schedule-api-fields.ts.
    const createRefusal = scheduleCreateRefusal(data.agent, data.type, scheduleAgentIds())
    if (createRefusal) { json(res, { error: createRefusal }, 400); return true }

    const dir = join(SCHEDULED_TASKS_DIR, name)
    if (existsSync(dir)) { json(res, { error: 'Schedule already exists' }, 409); return true }

    writeScheduledTask(name, {
      description: data.description || '',
      prompt: data.prompt.trim(),
      schedule: data.schedule.trim(),
      agent: data.agent || MAIN_AGENT_ID,
      enabled: true,
      type: data.type || 'task',
      skipIfBusy: data.skipIfBusy === true,
      forceSend: data.forceSend === true,
      targetSession: data.targetSession || undefined,
    })
    logger.info({ name, schedule: data.schedule }, 'Scheduled task created')
    json(res, { ok: true, name })
    return true
  }

  const scheduleUpdateMatch = path.match(/^\/api\/schedules\/([^/]+)$/)
  if (scheduleUpdateMatch && method === 'PUT') {
    const resolved = resolveScheduleDir(scheduleUpdateMatch[1])
    if (!resolved) { json(res, { error: 'Schedule not found' }, 404); return true }
    const { name, dir } = resolved
    if (!existsSync(dir)) { json(res, { error: 'Schedule not found' }, 404); return true }
    // ONCE (Viktor 38943 #2): a once-task carries a fixed prompt (the TEXT rule);
    // an edit afterwards would put free text into it after all. It can be
    // cancelled (DELETE) or switched off (toggle), never rewritten.
    if (isOnceTask(readScheduledTask(name))) { json(res, { error: ONCE_EDIT_REFUSAL }, 409); return true }

    let body: Buffer
    try {
      body = await readBody(req, { maxBytes: 256 * 1024 })
    } catch (err) {
      if (err instanceof RequestBodyTooLargeError) {
        json(res, { error: `Request body too large (max ${err.limit} bytes)` }, 413)
        return true
      }
      throw err
    }
    // RESERVEDSENDER1013 (Viktor M2): only the allowlisted fields reach
    // writeScheduledTask -- see schedule-api-fields.ts for what stays out and why.
    const verdict = validateScheduleUpdate(
      JSON.parse(body.toString()),
      readScheduledTask(name)?.type,
      scheduleAgentIds(),
    )
    if (!verdict.ok) { json(res, { error: verdict.error }, 400); return true }
    const data = verdict.update
    if (data.prompt !== undefined && data.prompt.length > MAX_SCHEDULED_TASK_PROMPT_LEN) {
      json(res, {
        error: `Prompt too large (${data.prompt.length} chars, max ${MAX_SCHEDULED_TASK_PROMPT_LEN})`,
      }, 413)
      return true
    }
    if (data.schedule !== undefined && !isValidCronShape(data.schedule)) {
      json(res, { error: 'Invalid cron expression' }, 400)
      return true
    }
    writeScheduledTask(name, data)
    logger.info({ name }, 'Scheduled task updated')
    json(res, { ok: true })
    return true
  }

  if (scheduleUpdateMatch && method === 'DELETE') {
    const resolved = resolveScheduleDir(scheduleUpdateMatch[1])
    if (!resolved) { json(res, { error: 'Schedule not found' }, 404); return true }
    const { name, dir } = resolved
    if (!existsSync(dir)) { json(res, { error: 'Schedule not found' }, 404); return true }
    rmSync(dir, { recursive: true, force: true })
    // #796: remember the removal so a shipped default is not re-seeded on the
    // next restart/update. Harmless for a user-authored task (the seeders only
    // ever revisit shipped names); a later re-create with this name clears it.
    markDefaultTaskRemoved(name)
    logger.info({ name }, 'Scheduled task deleted')
    json(res, { ok: true })
    return true
  }

  const scheduleToggleMatch = path.match(/^\/api\/schedules\/([^/]+)\/toggle$/)
  if (scheduleToggleMatch && method === 'POST') {
    const resolved = resolveScheduleDir(scheduleToggleMatch[1])
    if (!resolved) { json(res, { error: 'Schedule not found' }, 404); return true }
    const { name, dir } = resolved
    if (!existsSync(dir)) { json(res, { error: 'Schedule not found' }, 404); return true }

    const configPath = join(dir, 'task-config.json')
    let config: Record<string, unknown> = {}
    // JSONCLOBBER926: a corrupt task-config.json is refused, not reset to {enabled}.
    config = readJsonObjectForWrite(configPath)
    const newEnabled = !(config.enabled !== false)
    // Viktor L2: the toggle is the other way to flip `enabled`, so the same
    // rule as the PUT -- a command task can be switched off here, never on.
    if (config.type === 'command' && newEnabled) {
      json(res, { error: COMMAND_TASK_API_REFUSAL }, 400)
      return true
    }
    config.enabled = newEnabled
    atomicWriteFileSync(configPath, JSON.stringify(config, null, 2))
    logger.info({ name, enabled: newEnabled }, 'Scheduled task toggled')
    json(res, { ok: true, enabled: newEnabled })
    return true
  }

  const scheduleRunMatch = path.match(/^\/api\/schedules\/([^/]+)\/run$/)
  if (scheduleRunMatch && method === 'POST') {
    const resolved = resolveScheduleDir(scheduleRunMatch[1])
    if (!resolved) { json(res, { error: 'Schedule not found' }, 404); return true }
    const { name, dir } = resolved
    if (!existsSync(dir)) { json(res, { error: 'Schedule not found' }, 404); return true }
    const result = await runScheduledTaskNow(name)
    if (!result.ok) { json(res, { error: result.error }, 400); return true }
    logger.info({ name, result: result.result }, 'Scheduled task run-now fired')
    json(res, { ok: true, result: result.result })
    return true
  }

  if (path === '/api/schedules/pending' && method === 'GET') {
    const now = Date.now()
    const rows = listPendingTaskRetries().map(r => toPendingRetryView(r, now))
    json(res, rows)
    return true
  }

  const scheduleRunsMatch = path.match(/^\/api\/schedules\/([^/]+)\/runs$/)
  if (scheduleRunsMatch && method === 'GET') {
    const resolved = resolveScheduleDir(scheduleRunsMatch[1])
    if (!resolved) { json(res, { error: 'Schedule not found' }, 404); return true }
    const { name, dir } = resolved
    if (!existsSync(dir)) { json(res, { error: 'Schedule not found' }, 404); return true }
    const runs = listTaskRunHistory(name, 10)
    json(res, runs)
    return true
  }

  const pendingCancelMatch = path.match(/^\/api\/schedules\/pending\/(\d+)$/)
  if (pendingCancelMatch && method === 'DELETE') {
    const id = parseInt(pendingCancelMatch[1], 10)
    if (!Number.isFinite(id)) { json(res, { error: 'Invalid id' }, 400); return true }
    const removed = deletePendingTaskRetryById(id)
    if (!removed) { json(res, { error: 'Pending retry not found' }, 404); return true }
    logger.info({ id }, 'Pending scheduled-task retry cancelled via API')
    json(res, { ok: true })
    return true
  }

  return false
}
