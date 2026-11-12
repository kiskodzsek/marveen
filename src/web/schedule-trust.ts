// SCHEDTRUST1112 (card 6544de50; Viktor 38943 #4 and 38996; Klodel 39006):
// which scheduled tasks reach their agent with the OWNER framing.
//
// The problem: every agent holds the one shared dashboard token, and the
// runner handed EVERY task to its agent under SCHEDULED_TASK_PREAMBLE
// ("authored by the operator ... EXPECTED TO CARRY OUT"). So a prompt-injected
// agent could schedule an owner-grade instruction for any agent, the main one
// included, through POST/PUT /api/schedules -- or by editing a SKILL.md.
//
// The rule:
//   - A task runs with the owner framing ONLY while it has a trust row
//     (db.ts schedule_trust) whose hash equals the hash of its CURRENT stored
//     definition. Everything else -- no row, an unreadable row, a mismatch, a
//     lookup error -- runs with AGENT_SCHEDULED_TASK_PREAMBLE (fail-closed).
//   - Rows are written by the server only: the owner's browser session
//     (create/edit/approve in the dashboard), the install's own code (seeded
//     defaults, the rotation heartbeat), and the one-time legacy baseline. No
//     request body field reaches this table, and X-Agent-Id is a label only.
//   - A token-authenticated create or edit drops the row (expected path, no
//     alarm). A row whose hash no longer matches means the definition changed
//     behind the API (a file edit): agent framing PLUS an alert to the main
//     agent, once per changed definition.
//   - The runner executes no bash for an untrusted task: a command task is not
//     run, a preCheck is not run (its stdout would land in the task body).
//
// The legacy baseline runs once (db.ts schedule_trust_baseline). Deleting a
// trust ROW only lowers trust; deleting the BASELINE row and restarting would
// re-baseline every task at its current hash -- the same capability as writing
// the table directly, i.e. the residual below, not a new door (Viktor 39032 #5).
//
// Residual, stated (Klodel 39006: "ismert maradék kockázat, zárja: bubek 2e"):
// an agent runs under the same Unix user as the dashboard, so it can rewrite a
// task AND its trust row together (the hash is not a secret; an HMAC key would
// be just as readable). The hash stops the realistic case -- an agent that
// edits the task files without knowing about this table -- not a determined
// one. Only a separate OS user for the dashboard closes that. The preCheck
// SCRIPT body is not hashed either (only its path): all of today's preCheck
// scripts live in the repo / ops tree under the controlled PR path.

import { createHash } from 'node:crypto'
import {
  getScheduleTrust, setScheduleTrust, deleteScheduleTrust, baselineScheduleTrust, createSystemMessage,
  type ScheduleTrustRow,
} from '../db.js'
import { MAIN_AGENT_ID } from '../config.js'
import { logger } from '../logger.js'
import type { ScheduledTask } from './scheduled-tasks-io.js'

/** approved/legacy run with the owner framing; agent/mismatch do not. */
export type ScheduleTrustStatus = 'approved' | 'legacy' | 'agent' | 'mismatch'

/**
 * The hash is DENY-LIST based (Viktor 39032 #1): EVERY field of the stored
 * definition counts -- prompt (the SKILL.md body), type, command, preCheck,
 * agent, targetSession, telegramChatId, channelProvider, injectMetrics,
 * sendDigestDirect, requires, ... and any field added later -- EXCEPT the ones
 * below, which only say WHEN or WHETHER a task runs, or how it is labelled.
 * They are exactly what a token PUT may change while keeping the approval
 * (schedule-api-fields.ts), plus the store's own bookkeeping.
 */
export const SCHEDULE_TRUST_UNHASHED_FIELDS: ReadonlySet<string> = new Set([
  'name', 'description', 'schedule', 'enabled', 'createdAt', 'skipIfBusy', 'forceSend',
  'catchUpMaxAgeMinutes', 'stuckAfterMinutes', 'runAt',
])

export type ScheduleTrustFields = Pick<ScheduledTask, 'prompt' | 'agent'> & Partial<Omit<ScheduledTask, 'prompt' | 'agent'>>

const HASH_RX = /^[0-9a-f]{64}$/

// Key-sorted, undefined-free JSON, so the hash does not depend on the order
// the fields were written in, nor on an absent-vs-undefined difference.
function canonical(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(canonical)
  if (v && typeof v === 'object') {
    const out: Record<string, unknown> = {}
    for (const k of Object.keys(v as Record<string, unknown>).sort()) {
      const x = (v as Record<string, unknown>)[k]
      if (x !== undefined) out[k] = canonical(x)
    }
    return out
  }
  return v
}

export function scheduleTrustHash(task: ScheduleTrustFields): string {
  const kept: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(task)) {
    if (!SCHEDULE_TRUST_UNHASHED_FIELDS.has(k)) kept[k] = v
  }
  // The defaults readScheduledTask applies, so a task built in code and the
  // same task read back from disk hash alike.
  kept.prompt = String(task.prompt ?? '')
  kept.agent = String(task.agent ?? '')
  kept.type = task.type ?? 'task'
  return createHash('sha256').update(JSON.stringify(['v2', canonical(kept)]), 'utf8').digest('hex')
}

/** The first 16 hex of the hash: what the dashboard shows and the approve call echoes. */
export function scheduleTrustShortHash(task: ScheduleTrustFields): string {
  return scheduleTrustHash(task).slice(0, 16)
}

/** Pure verdict for one task against its stored row. */
export function evaluateScheduleTrust(task: ScheduleTrustFields, row: Pick<ScheduleTrustRow, 'status' | 'hash'> | null | undefined): ScheduleTrustStatus {
  if (!row) return 'agent'
  if (row.status !== 'approved' && row.status !== 'legacy') return 'agent'
  if (typeof row.hash !== 'string' || !HASH_RX.test(row.hash)) return 'mismatch'
  return row.hash === scheduleTrustHash(task) ? row.status : 'mismatch'
}

export function isOwnerTrusted(status: ScheduleTrustStatus): boolean {
  return status === 'approved' || status === 'legacy'
}

/** The verdict for a task as stored now. Any error is 'agent' (fail-closed). */
export function scheduleTrustOf(task: ScheduledTask): ScheduleTrustStatus {
  try {
    return evaluateScheduleTrust(task, getScheduleTrust(task.name))
  } catch (err) {
    logger.warn({ err, task: task.name }, 'schedule-trust: lookup failed, treating the task as agent-authored')
    return 'agent'
  }
}

/** Owner (or install code) approval of the task AS STORED NOW. */
export function approveScheduledTask(task: ScheduledTask, setBy: string, now = Date.now()): string {
  const hash = scheduleTrustHash(task)
  setScheduleTrust(task.name, 'approved', hash, setBy, Math.floor(now / 1000))
  return hash
}

/** A token-side create/edit/delete: the task is agent-authored from here on. */
export function clearScheduleTrust(taskName: string): void {
  try {
    deleteScheduleTrust(taskName)
  } catch (err) {
    // The row survives, but its hash no longer matches the edited task, so the
    // fire still gets the agent framing (and an alert) -- fail-closed anyway.
    logger.warn({ err, task: taskName }, 'schedule-trust: could not drop the trust row')
  }
}

/**
 * One-time legacy import of the tasks that existed when SCHEDTRUST1112
 * shipped (Klodel 39006: they keep today's framing). Does nothing once the
 * baseline row exists. Returns the number of rows written, or null.
 */
export function ensureScheduleTrustBaseline(listTasks: () => ScheduledTask[], now = Date.now()): number | null {
  try {
    const entries = listTasks().map(t => ({ name: t.name, agent: t.agent, hash: scheduleTrustHash(t) }))
    const n = baselineScheduleTrust(entries, Math.floor(now / 1000))
    // Viktor 39032 #7: the baselined set, once, so a later review can compare
    // what was trusted unreviewed. Names and agents are filtered like the alert.
    if (n !== null) {
      logger.warn({
        tasks: n,
        baseline: entries.map(e => ({ name: alertSafeId(e.name), agent: alertSafeId(e.agent), hash: e.hash.slice(0, 16) })),
      }, 'schedule-trust: legacy baseline written (one-time)')
    }
    return n
  } catch (err) {
    logger.error({ err }, 'schedule-trust: legacy baseline failed; every task runs agent-framed until it is approved')
    return null
  }
}

// One alert per task per stored definition (keyed by the CURRENT hash), so a
// task firing every 10 minutes does not repeat it; a further edit alerts again.
const mismatchAlerted = new Map<string, string>()

// Viktor 39032 #2: the alert goes out as a from=system message to the main
// agent, so nothing read from the task files may reach it raw -- the directory
// name and the agent field are free text on disk (newlines, a fake directive,
// kilobytes). Only an id-shaped value is shown; the rest is a fixed template.
const ALERT_ID_RX = /^[A-Za-z0-9._-]{1,64}$/
export function alertSafeId(v: unknown): string {
  return typeof v === 'string' && ALERT_ID_RX.test(v) ? v : '(érvénytelen név)'
}

export function alertScheduleTrust(task: ScheduledTask, status: ScheduleTrustStatus, where: string): void {
  if (isOwnerTrusted(status)) return
  const hash = scheduleTrustHash(task)
  if (mismatchAlerted.get(task.name) === hash) return
  mismatchAlerted.set(task.name, hash)
  const name = alertSafeId(task.name)
  const agent = alertSafeId(task.agent)
  logger.warn({ task: name, agent, status, where }, 'schedule-trust: task is not approved as stored')
  const what = status === 'mismatch'
    ? 'tárolt definíciója eltér a jóváhagyottól (prompt / type / command / preCheck / agent / targetSession): valaki az API-n kívül, a fájlban írta át'
    : 'nincs jóváhagyva, mégis olyat kér, amit az API nem tud beállítani (command / preCheck): fájlból került a tárba'
  try {
    createSystemMessage(
      MAIN_AGENT_ID,
      `[UTEMEZES-BIZALOM] A(z) "${name}" ütemezett feladat (agent: ${agent}) ${what}. ` +
      `Ügynöki keretezéssel fut, bash (command, preCheck) nélkül (${where}). ` +
      `Nézd meg a ~/.claude/scheduled-tasks/${name}/ tartalmát; ha rendben van, a tulajdonos a dashboardon jóváhagyhatja. Ha nem a tulajdonos írta, szólj Viktornak.`,
    )
  } catch (err) {
    logger.warn({ err, task: name }, 'schedule-trust: alert could not be queued')
  }
}

/** Test seam. */
export function _resetScheduleTrustAlertsForTest(): void { mismatchAlerted.clear() }
