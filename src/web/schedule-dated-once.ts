// DATEDONCE1115 (card cb2c20bc, Klodel 42602): a schedule whose cron names ONE
// calendar day (`m h DOM MONTH *`, DOM and MONTH plain numbers) is a one-off the
// agents write with a date in it (e.g. szigma-meta-24h-1109: `55 10 9 11 *`).
// Cron has no year, so after that day such a task stays enabled and runs again
// on the same day next year. The runner switches it OFF (never deletes it) once
// its day is over and its catch-up window has passed.
//
// `enabled` is not in the schedule-trust hash (SCHEDULE_TRUST_UNHASHED_FIELDS),
// so the switch-off keeps the task's trust row, like the dashboard toggle.
// A one-shot made through /api/schedules/once (runAt) is not touched here: the
// runner removes that one itself after its single occurrence.
// Known trade-off: a task meant to repeat every year on a fixed day must not
// use this form (it is switched off after its first day); a weekday cron
// (`... * * 1`) or a month-day cron (`... 15 * *`) is never touched.
import { existsSync } from 'node:fs'
import { basename, join } from 'node:path'
import { readJsonObjectForWrite } from './agent-config.js'
import { atomicWriteFileSync } from './atomic-write.js'
import { SCHEDULED_TASKS_DIR, type ScheduledTask } from './scheduled-tasks-io.js'

const DAY_MS = 24 * 60 * 60 * 1000
/** A configured "always catch up" (Infinity) must not keep a dated task alive for ever. */
export const DATED_ONCE_MAX_MARGIN_MS = 7 * DAY_MS

/**
 * The local midnight right after the day a dated cron means, in ms; null when
 * the cron is not a single-day one or the day cannot be placed. The day is the
 * first such date on or after the task's createdAt (seconds; a task made in
 * December for 5 January means next year).
 */
export function datedCronDayEndMs(task: Pick<ScheduledTask, 'schedule' | 'createdAt'>): number | null {
  const f = String(task.schedule || '').trim().split(/\s+/)
  if (f.length !== 5 || !/^\d{1,2}$/.test(f[2]) || !/^\d{1,2}$/.test(f[3]) || f[4] !== '*') return null
  if (!Number.isFinite(task.createdAt) || task.createdAt <= 0) return null
  const createdMs = task.createdAt > 1e11 ? task.createdAt : task.createdAt * 1000
  const dom = Number(f[2])
  const mon = Number(f[3])
  const createdYear = new Date(createdMs).getFullYear()
  for (const year of [createdYear, createdYear + 1]) {
    const day = new Date(year, mon - 1, dom)
    if (day.getMonth() !== mon - 1 || day.getDate() !== dom) return null // 31 April, 29 February off a leap year
    const end = new Date(year, mon - 1, dom + 1).getTime()
    if (end > createdMs) return end
  }
  return null
}

/** Pure: is this task a dated one-off whose day (plus its catch-up margin) is over? */
export function isExpiredDatedTask(
  task: Pick<ScheduledTask, 'schedule' | 'createdAt' | 'enabled' | 'runAt'>,
  nowMs: number,
  marginMs: number,
): boolean {
  if (task.enabled === false || task.runAt != null) return false
  const end = datedCronDayEndMs(task)
  if (end === null) return false
  return nowMs >= end + Math.min(Math.max(marginMs, 0), DATED_ONCE_MAX_MARGIN_MS)
}

/** Switch one task off on disk. Re-reads the config: a task already off, or gone, is left as it is. */
export function disableScheduledTaskOnDisk(
  name: string,
  dir: string = SCHEDULED_TASKS_DIR,
  expect?: { schedule?: string; createdAt?: number },
): boolean {
  // task.name can come from the SKILL.md frontmatter, not from the directory: only a plain directory name is written to
  if (!name || basename(name) !== name || name.startsWith('.')) return false
  const configPath = join(dir, name, 'task-config.json')
  // a task removed meanwhile is not re-created as a bare {enabled:false}
  if (!existsSync(configPath)) return false
  let config: Record<string, unknown>
  try {
    config = readJsonObjectForWrite(configPath)
  } catch {
    return false
  }
  if (config.enabled === false) return false
  // the config that is on disk must be the one the expiry was decided on (a frontmatter name can point at another task)
  if (expect && (config.schedule !== expect.schedule || config.createdAt !== expect.createdAt)) return false
  config.enabled = false
  atomicWriteFileSync(configPath, JSON.stringify(config, null, 2))
  return true
}

/**
 * Switch off every expired dated one-off of the list. `pending` names a task
 * whose occurrence still waits in the retry queue: it is left for a later tick.
 * Returns the names switched off.
 */
export function disableExpiredDatedTasks(
  tasks: ReadonlyArray<Pick<ScheduledTask, 'name' | 'schedule' | 'createdAt' | 'enabled' | 'runAt' | 'type' | 'catchUpMaxAgeMinutes'>>,
  nowMs: number,
  marginMs: (task: Pick<ScheduledTask, 'type' | 'catchUpMaxAgeMinutes'>) => number,
  pending: (name: string) => boolean = () => false,
  disable: (name: string, expect?: { schedule?: string; createdAt?: number }) => boolean =
    (name, expect) => disableScheduledTaskOnDisk(name, SCHEDULED_TASKS_DIR, expect),
): string[] {
  const off: string[] = []
  for (const task of tasks) {
    if (!isExpiredDatedTask(task, nowMs, marginMs(task)) || pending(task.name)) continue
    if (disable(task.name, { schedule: task.schedule, createdAt: task.createdAt })) off.push(task.name)
  }
  return off
}
