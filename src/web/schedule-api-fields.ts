// Which scheduled-task fields the HTTP API may write (RESERVEDSENDER1013, Viktor M2).
//
// PUT /api/schedules/:name used to hand the parsed body straight to
// writeScheduledTask, which persists every field it knows. With the shared
// dashboard token that meant:
//   - `agent: "system"` -> the heartbeat direct digest is sent with task.agent as
//     its sender, i.e. a from=system row to the main agent;
//   - `type: "command"` + `command`, or `preCheck` -> bash in the dashboard
//     process, outside Claude Code, its PreToolUse hooks (egress gate,
//     destructive gate) and its deny list. The 2026-10-12 machine audit found
//     the file-write route to the same capability; this was the API route.
//
// The API therefore writes only what the dashboard's own task form sends
// (web/app.js saveSchedule) plus `enabled` (docs/scheduled-tasks.md). Command
// tasks, digest routing and chat ids stay with the installer's seeders, which
// call writeScheduledTask in-process. A preCheck is the one narrow exception
// (card 248e8f7c, Klodel 47998): see SCHEDULE_API_PRECHECK_RX.
import { lstatSync, realpathSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { isReservedSender } from '../reserved-sender.js'

export const SCHEDULE_API_STRING_FIELDS = ['description', 'prompt', 'schedule', 'agent', 'type', 'targetSession'] as const
export const SCHEDULE_API_BOOLEAN_FIELDS = ['enabled', 'skipIfBusy', 'forceSend'] as const

/** Task types the API may set. `command` is deliberately absent. */
export const SCHEDULE_API_TYPES: readonly string[] = ['task', 'heartbeat']

/**
 * preCheck over the API (card 248e8f7c, Klodel 47998, 2026-11-19): ONLY a script shipped
 * in the install's scripts/prechecks/, written in the {{PROJECT_ROOT}} form, one path
 * segment, `.sh`, an existing regular file (not a symlink) whose directory resolves to
 * <root>/scripts/prechecks. A preCheck is bash in the dashboard process, so this write
 * never approves anything: the changed definition loses its approval (recordWriteTrust ->
 * clearScheduleTrust; an owner save does not approve it either, the field is not in the
 * editor) and the preCheck runs only after the owner's one-click approve, which hashes the
 * script chain (PRECHECKTRUST1114). Removing or changing a preCheck to anything else stays
 * with the installer.
 */
export const SCHEDULE_API_PRECHECK_PREFIX = '{{PROJECT_ROOT}}/scripts/prechecks/'
export const SCHEDULE_API_PRECHECK_RX = /^\{\{PROJECT_ROOT\}\}\/scripts\/prechecks\/[a-z0-9][a-z0-9_-]{0,63}\.sh$/
export const SCHEDULE_API_PRECHECK_REFUSAL =
  'preCheck must be {{PROJECT_ROOT}}/scripts/prechecks/<name>.sh, an existing regular file of the install'

/** Why `preCheck` cannot be stored over the API, or null when it can. `root` = the install root. */
export function preCheckApiRefusal(preCheck: unknown, root: string | undefined): string | null {
  if (typeof preCheck !== 'string' || !SCHEDULE_API_PRECHECK_RX.test(preCheck) || !root) return SCHEDULE_API_PRECHECK_REFUSAL
  const file = join(root, 'scripts', 'prechecks', preCheck.slice(SCHEDULE_API_PRECHECK_PREFIX.length))
  try {
    if (!lstatSync(file).isFile()) return SCHEDULE_API_PRECHECK_REFUSAL      // lstat: a symlink is not a file
    if (realpathSync(dirname(file)) !== join(realpathSync(root), 'scripts', 'prechecks')) return SCHEDULE_API_PRECHECK_REFUSAL
  } catch {
    return SCHEDULE_API_PRECHECK_REFUSAL
  }
  return null
}

export interface ScheduleApiUpdate {
  description?: string
  prompt?: string
  schedule?: string
  agent?: string
  type?: string
  targetSession?: string
  enabled?: boolean
  skipIfBusy?: boolean
  forceSend?: boolean
  preCheck?: string
}

export type ScheduleApiVerdict =
  | { ok: true; update: ScheduleApiUpdate }
  | { ok: false; error: string }

/** The `agent` a task may run as: a known fleet agent or the main agent. */
export function scheduleAgentRefusal(agent: string, knownAgents: ReadonlySet<string>): string | null {
  if (isReservedSender(agent)) return `agent '${agent}' is reserved for in-process system messages`
  if (!knownAgents.has(agent)) return `unknown agent '${agent}' -- must be one of GET /api/schedules/agents`
  return null
}

/**
 * A command task (bash in the dashboard process, seeded by the installer) can
 * only be switched OFF over HTTP. Viktor L2 (2026-10-13): with `enabled` and
 * `schedule` writable, the shared token could start a disabled seeder command
 * or run it more often -- harmless for today's two (auto-update, usage-collect),
 * but the next seeder command would inherit the same door. Switching one back
 * on is the installer's or the owner's job, not the API's.
 */
export const COMMAND_TASK_API_REFUSAL =
  'command tasks can only be disabled via the API ({"enabled": false}); enabling or editing them is done by the installer'

/**
 * Validate a PUT body against the API allowlist. `existingType` is the stored
 * task's type: nothing can become a command task over HTTP, and an existing
 * command task accepts only `{enabled: false}` (see COMMAND_TASK_API_REFUSAL).
 * `root` (the install root) is needed only for `preCheck`; without it a preCheck
 * is refused.
 */
export function validateScheduleUpdate(
  body: unknown,
  existingType: string | undefined,
  knownAgents: ReadonlySet<string>,
  root?: string,
): ScheduleApiVerdict {
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    return { ok: false, error: 'Body must be a JSON object' }
  }
  const data = body as Record<string, unknown>
  if (existingType === 'command') {
    const keys = Object.keys(data)
    if (keys.length !== 1 || keys[0] !== 'enabled' || data.enabled !== false) {
      return { ok: false, error: COMMAND_TASK_API_REFUSAL }
    }
    return { ok: true, update: { enabled: false } }
  }
  const allowed = new Set<string>([...SCHEDULE_API_STRING_FIELDS, ...SCHEDULE_API_BOOLEAN_FIELDS, 'preCheck'])
  const refused = Object.keys(data).filter(k => !allowed.has(k))
  if (refused.length > 0) {
    return { ok: false, error: `Field(s) not editable via the API: ${refused.join(', ')}` }
  }

  const update: ScheduleApiUpdate = {}
  for (const key of SCHEDULE_API_STRING_FIELDS) {
    if (data[key] === undefined) continue
    if (typeof data[key] !== 'string') return { ok: false, error: `${key} must be a string` }
    update[key] = data[key] as string
  }
  for (const key of SCHEDULE_API_BOOLEAN_FIELDS) {
    if (data[key] === undefined) continue
    if (typeof data[key] !== 'boolean') return { ok: false, error: `${key} must be a boolean` }
    update[key] = data[key] as boolean
  }

  if (data.preCheck !== undefined) {
    const refusal = preCheckApiRefusal(data.preCheck, root)
    if (refusal) return { ok: false, error: refusal }
    update.preCheck = data.preCheck as string
  }
  if (update.agent !== undefined) {
    const refusal = scheduleAgentRefusal(update.agent, knownAgents)
    if (refusal) return { ok: false, error: refusal }
  }
  if (update.type !== undefined) {
    if (!SCHEDULE_API_TYPES.includes(update.type)) {
      return { ok: false, error: `type '${update.type}' cannot be set via the API (allowed: ${SCHEDULE_API_TYPES.join(', ')})` }
    }
  }
  return { ok: true, update }
}

/** POST-time check of the two fields that pick who and what runs. */
export function scheduleCreateRefusal(
  agent: unknown,
  type: unknown,
  knownAgents: ReadonlySet<string>,
): string | null {
  if (agent !== undefined && agent !== '') {
    if (typeof agent !== 'string') return 'agent must be a string'
    const refusal = scheduleAgentRefusal(agent, knownAgents)
    if (refusal) return refusal
  }
  if (type !== undefined && type !== '') {
    if (typeof type !== 'string' || !SCHEDULE_API_TYPES.includes(type)) {
      return `type '${String(type)}' cannot be set via the API (allowed: ${SCHEDULE_API_TYPES.join(', ')})`
    }
  }
  return null
}
