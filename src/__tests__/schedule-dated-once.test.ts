import { afterAll, describe, expect, it } from 'vitest'
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  DATED_ONCE_MAX_MARGIN_MS,
  datedCronDayEndMs,
  disableExpiredDatedTasks,
  disableScheduledTaskOnDisk,
  isExpiredDatedTask,
} from '../web/schedule-dated-once.js'

// DATEDONCE1115 (card cb2c20bc): a cron naming one calendar day is switched
// off once its day (plus catch-up margin) is over. Local time, like the cron.
const sec = (y: number, m: number, d: number, h = 0, mi = 0) => Math.floor(new Date(y, m - 1, d, h, mi).getTime() / 1000)
const ms = (y: number, m: number, d: number, h = 0, mi = 0) => new Date(y, m - 1, d, h, mi).getTime()
const HOUR = 60 * 60 * 1000

describe('datedCronDayEndMs', () => {
  it('a dated cron ends at the local midnight after its day, in the year it was made', () => {
    expect(datedCronDayEndMs({ schedule: '55 10 9 11 *', createdAt: sec(2026, 11, 8, 12) })).toBe(ms(2026, 11, 10))
  })

  it('a list of hours on the day is still one day', () => {
    expect(datedCronDayEndMs({ schedule: '0 1,3,5 20 10 *', createdAt: sec(2026, 10, 19) })).toBe(ms(2026, 10, 21))
  })

  it('made in December for 5 January: next year', () => {
    expect(datedCronDayEndMs({ schedule: '0 9 5 1 *', createdAt: sec(2026, 12, 20) })).toBe(ms(2027, 1, 6))
  })

  it('made on the day itself, after the hour: still that day (it is over at midnight)', () => {
    expect(datedCronDayEndMs({ schedule: '0 9 14 11 *', createdAt: sec(2026, 11, 14, 22) })).toBe(ms(2026, 11, 15))
  })

  it('createdAt in milliseconds is read as such', () => {
    expect(datedCronDayEndMs({ schedule: '55 10 9 11 *', createdAt: ms(2026, 11, 8, 12) })).toBe(ms(2026, 11, 10))
  })

  it.each([
    '0 9 * * *',
    '0 9 15 * *',
    '0 9 * * 1',
    '0 9 1-3 11 *',
    '0 9 1,2 11 *',
    '0 9 */2 11 *',
    '0 9 0x9 11 *',
    '0 9 9 11 1',
    '0 9 9 11',
    '',
  ])('not a single-day cron: null (%s)', (schedule) => {
    expect(datedCronDayEndMs({ schedule, createdAt: sec(2026, 11, 1) })).toBeNull()
  })

  it('no createdAt: null (the day cannot be placed)', () => {
    expect(datedCronDayEndMs({ schedule: '55 10 9 11 *', createdAt: 0 })).toBeNull()
  })

  it('a day that does not exist (31 April): null', () => {
    expect(datedCronDayEndMs({ schedule: '0 9 31 4 *', createdAt: sec(2026, 1, 1) })).toBeNull()
  })
})

describe('isExpiredDatedTask', () => {
  const t = { schedule: '55 10 9 11 *', createdAt: sec(2026, 11, 8, 12), enabled: true as boolean, runAt: undefined as number | undefined }
  const end = ms(2026, 11, 10)

  it('not before its day end plus the margin; yes from then on', () => {
    expect(isExpiredDatedTask(t, end + 3 * HOUR - 1, 3 * HOUR)).toBe(false)
    expect(isExpiredDatedTask(t, end + 3 * HOUR, 3 * HOUR)).toBe(true)
  })

  it('a disabled task or a runAt one-shot is never touched', () => {
    expect(isExpiredDatedTask({ ...t, enabled: false }, end + 100 * HOUR, 0)).toBe(false)
    expect(isExpiredDatedTask({ ...t, runAt: ms(2026, 11, 9, 10) }, end + 100 * HOUR, 0)).toBe(false)
  })

  it('an "always catch up" margin (Infinity) is capped at 7 days', () => {
    expect(DATED_ONCE_MAX_MARGIN_MS).toBe(7 * 24 * HOUR)
    expect(isExpiredDatedTask(t, end + DATED_ONCE_MAX_MARGIN_MS - 1, Infinity)).toBe(false)
    expect(isExpiredDatedTask(t, end + DATED_ONCE_MAX_MARGIN_MS, Infinity)).toBe(true)
  })
})

describe('disableExpiredDatedTasks', () => {
  const base = { type: 'task' as const, catchUpMaxAgeMinutes: undefined, enabled: true, runAt: undefined }
  const tasks = [
    { ...base, name: 'over', schedule: '55 10 9 11 *', createdAt: sec(2026, 11, 8) },
    { ...base, name: 'over-pending', schedule: '0 12 9 11 *', createdAt: sec(2026, 11, 8) },
    { ...base, name: 'ahead', schedule: '0 8 19 11 *', createdAt: sec(2026, 11, 8) },
    { ...base, name: 'daily', schedule: '0 8 * * *', createdAt: sec(2026, 11, 8) },
  ]

  it('switches off only the expired dated ones without a pending retry', () => {
    const called: string[] = []
    const off = disableExpiredDatedTasks(tasks, ms(2026, 11, 15), () => 3 * HOUR, n => n === 'over-pending', n => { called.push(n); return true })
    expect(called).toEqual(['over'])
    expect(off).toEqual(['over'])
  })

  it('a write that changed nothing is not reported', () => {
    expect(disableExpiredDatedTasks(tasks, ms(2026, 11, 15), () => 0, () => false, () => false)).toEqual([])
  })

  it('hands the listed schedule and createdAt to the write, so the config on disk must match them', () => {
    const seen: unknown[] = []
    disableExpiredDatedTasks(tasks, ms(2026, 11, 15), () => 3 * HOUR, () => false, (n, e) => { seen.push([n, e]); return true })
    expect(seen).toEqual([
      ['over', { schedule: '55 10 9 11 *', createdAt: sec(2026, 11, 8) }],
      ['over-pending', { schedule: '0 12 9 11 *', createdAt: sec(2026, 11, 8) }],
    ])
  })
})

describe('disableScheduledTaskOnDisk', () => {
  const dir = mkdtempSync(join(tmpdir(), 'dated-once-'))
  afterAll(() => rmSync(dir, { recursive: true, force: true }))
  const put = (name: string, cfg: Record<string, unknown>) => {
    mkdirSync(join(dir, name), { recursive: true })
    writeFileSync(join(dir, name, 'task-config.json'), JSON.stringify(cfg))
  }
  const read = (name: string) => JSON.parse(readFileSync(join(dir, name, 'task-config.json'), 'utf8'))

  it('sets enabled:false and keeps every other field', () => {
    const cfg = { schedule: '55 10 9 11 *', agent: 'szigma', enabled: true, createdAt: 1794165626, type: 'task', preCheck: '/x.sh' }
    put('a', cfg)
    expect(disableScheduledTaskOnDisk('a', dir)).toBe(true)
    expect(read('a')).toEqual({ ...cfg, enabled: false })
  })

  it('a task with no enabled field (= enabled) is switched off too', () => {
    put('b', { schedule: '0 9 1 1 *', agent: 'x' })
    expect(disableScheduledTaskOnDisk('b', dir)).toBe(true)
    expect(read('b').enabled).toBe(false)
  })

  it('already off: unchanged, false; missing: false', () => {
    put('c', { schedule: '0 9 1 1 *', enabled: false })
    expect(disableScheduledTaskOnDisk('c', dir)).toBe(false)
    expect(disableScheduledTaskOnDisk('no-such-task', dir)).toBe(false)
  })

  // Viktor 42609 LOW: task.name may come from the SKILL.md frontmatter, not from the directory.
  it.each(['../outside/x', '../outside', 'outside/x', '..', '.', '.hidden', ''])(
    'a name that is not a plain directory name (%j) writes nothing, even where a config exists', name => {
      const root = mkdtempSync(join(tmpdir(), 'dated-once-trav-'))
      const tasks = join(root, 'tasks')
      try {
        for (const d of [join(tasks, 'outside', 'x'), join(root, 'outside', 'x'), join(root, 'outside'), join(tasks, '.hidden')]) {
          mkdirSync(d, { recursive: true })
          writeFileSync(join(d, 'task-config.json'), JSON.stringify({ schedule: '0 9 1 1 *', enabled: true, keep: 1 }))
        }
        writeFileSync(join(tasks, 'task-config.json'), JSON.stringify({ schedule: '0 9 1 1 *', enabled: true, keep: 1 }))
        expect(disableScheduledTaskOnDisk(name, tasks)).toBe(false)
        for (const f of [join(tasks, 'outside', 'x'), join(root, 'outside', 'x'), join(root, 'outside'), join(tasks, '.hidden'), tasks]) {
          expect(JSON.parse(readFileSync(join(f, 'task-config.json'), 'utf8'))).toEqual({ schedule: '0 9 1 1 *', enabled: true, keep: 1 })
        }
      } finally {
        rmSync(root, { recursive: true, force: true })
      }
    })

  it('a frontmatter name pointing at another task: that task is left on (its schedule differs)', () => {
    put('victim', { schedule: '*/5 * * * *', agent: 'kernel', enabled: true, createdAt: 1794000000 })
    expect(disableScheduledTaskOnDisk('victim', dir, { schedule: '55 10 9 11 *', createdAt: 1794165626 })).toBe(false)
    expect(read('victim').enabled).toBe(true)
  })

  it('same schedule but another createdAt: left on; both equal: switched off', () => {
    put('twin', { schedule: '55 10 9 11 *', enabled: true, createdAt: 1794000000 })
    expect(disableScheduledTaskOnDisk('twin', dir, { schedule: '55 10 9 11 *', createdAt: 1794165626 })).toBe(false)
    expect(read('twin').enabled).toBe(true)
    expect(disableScheduledTaskOnDisk('twin', dir, { schedule: '55 10 9 11 *', createdAt: 1794000000 })).toBe(true)
    expect(read('twin').enabled).toBe(false)
  })
})
