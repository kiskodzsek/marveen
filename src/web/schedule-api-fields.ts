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
// tasks, pre-checks, digest routing and chat ids stay with the installer's
// seeders, which call writeScheduledTask in-process.
import { isReservedSender } from '../reserved-sender.js'

export const SCHEDULE_API_STRING_FIELDS = ['description', 'prompt', 'schedule', 'agent', 'type', 'targetSession'] as const
export const SCHEDULE_API_BOOLEAN_FIELDS = ['enabled', 'skipIfBusy', 'forceSend'] as const

/** Task types the API may set. `command` is deliberately absent. */
export const SCHEDULE_API_TYPES: readonly string[] = ['task', 'heartbeat']

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
 * Validate a PUT body against the API allowlist. `existingType` is the stored
 * task's type: a command task may keep its own type in an edit, but nothing can
 * become a command task over HTTP.
 */
export function validateScheduleUpdate(
  body: unknown,
  existingType: string | undefined,
  knownAgents: ReadonlySet<string>,
): ScheduleApiVerdict {
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    return { ok: false, error: 'Body must be a JSON object' }
  }
  const data = body as Record<string, unknown>
  const allowed = new Set<string>([...SCHEDULE_API_STRING_FIELDS, ...SCHEDULE_API_BOOLEAN_FIELDS])
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

  if (update.agent !== undefined) {
    const refusal = scheduleAgentRefusal(update.agent, knownAgents)
    if (refusal) return { ok: false, error: refusal }
  }
  if (update.type !== undefined) {
    const keepsOwnType = existingType !== undefined && update.type === existingType
    if (!keepsOwnType && !SCHEDULE_API_TYPES.includes(update.type)) {
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
