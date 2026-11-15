import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { removeScheduledTaskDir, resolveTaskDirInside } from '../web/scheduled-tasks-io.js'
import { disableScheduledTaskOnDisk } from '../web/schedule-dated-once.js'

// Card c453361b (Viktor 42609 LOW 2, 42613 INFO 1): a listed task.name comes
// from the SKILL.md frontmatter, not from the directory. The runner's recursive
// remove of a one-shot and the dated-once switch-off must only ever touch a
// plain task directory that really sits in the tasks dir, and only the task
// that was listed (its config still carries the listed runAt / createdAt).

const RUN_AT = 1_794_700_000_000
const CREATED = 1_794_600_000
const ONCE = { schedule: '0 9 * * *', agent: 'kernel', enabled: true, createdAt: CREATED, runAt: RUN_AT }
const LIVE = { schedule: '*/5 * * * *', agent: 'kernel', enabled: true, createdAt: CREATED - 86_400 }

let root: string
let tasks: string
const put = (dir: string, cfg: Record<string, unknown>) => {
  mkdirSync(dir, { recursive: true })
  writeFileSync(join(dir, 'task-config.json'), JSON.stringify(cfg))
}
const cfgOf = (dir: string) => JSON.parse(readFileSync(join(dir, 'task-config.json'), 'utf8'))

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), 'task-dir-guard-'))
  tasks = join(root, 'tasks')
  put(join(tasks, 'once'), ONCE)
  put(join(tasks, 'live-guard'), LIVE)
  put(join(tasks, 'outside', 'x'), ONCE) // a nested dir inside tasks: not a task dir
  put(join(root, 'outside'), ONCE)
  put(join(root, 'outside', 'x'), ONCE)
  put(join(tasks, '.hidden'), ONCE)
  writeFileSync(join(tasks, 'task-config.json'), JSON.stringify(ONCE))
  symlinkSync(join(root, 'outside'), join(tasks, 'lnk-out'))
  symlinkSync(join(tasks, 'once'), join(tasks, 'lnk-in'))
})
afterEach(() => rmSync(root, { recursive: true, force: true }))

const BAD_NAMES = ['../outside', '../outside/x', 'outside/x', '..', '.', '.hidden', '', 'once/', 'once/.', 'once/../..', 'x\0y', '/']

describe('resolveTaskDirInside', () => {
  it('a plain task directory: its path', () => {
    expect(resolveTaskDirInside('once', tasks)).toBe(join(tasks, 'once'))
  })

  it.each(BAD_NAMES)('not a plain directory name (%j): null', name => {
    expect(resolveTaskDirInside(name, tasks)).toBeNull()
  })

  it('a name that is not a string (a hand-edited frontmatter read as data): null, no throw', () => {
    expect(resolveTaskDirInside(undefined as unknown as string, tasks)).toBeNull()
    expect(resolveTaskDirInside(7 as unknown as string, tasks)).toBeNull()
  })

  it('a missing directory: null', () => {
    expect(resolveTaskDirInside('no-such-task', tasks)).toBeNull()
  })

  it('a task dir that is a symlink to outside the tasks dir: null; one to a sibling task: allowed', () => {
    expect(resolveTaskDirInside('lnk-out', tasks)).toBeNull()
    expect(resolveTaskDirInside('lnk-in', tasks)).toBe(join(tasks, 'lnk-in'))
  })

  it('the tasks dir itself reached through a symlink (e.g. ~/.claude linked): still fine', () => {
    symlinkSync(tasks, join(root, 'tasks-link'))
    expect(resolveTaskDirInside('once', join(root, 'tasks-link'))).toBe(join(root, 'tasks-link', 'once'))
  })
})

describe('removeScheduledTaskDir', () => {
  it('removes the one-shot whose config carries the listed runAt and createdAt', () => {
    expect(removeScheduledTaskDir('once', { runAt: RUN_AT, createdAt: CREATED }, tasks)).toBe(true)
    expect(existsSync(join(tasks, 'once'))).toBe(false)
  })

  it.each(BAD_NAMES)('a name that is not a plain task directory (%j) removes nothing', name => {
    expect(removeScheduledTaskDir(name, { runAt: RUN_AT, createdAt: CREATED }, tasks)).toBe(false)
    for (const d of [join(tasks, 'once'), join(tasks, 'outside', 'x'), join(root, 'outside'), join(root, 'outside', 'x'), join(tasks, '.hidden'), tasks]) {
      expect(cfgOf(d)).toEqual(ONCE)
    }
  })

  it('a symlinked task dir pointing outside: nothing removed, the target intact', () => {
    expect(removeScheduledTaskDir('lnk-out', { runAt: RUN_AT, createdAt: CREATED }, tasks)).toBe(false)
    expect(cfgOf(join(root, 'outside'))).toEqual(ONCE)
    expect(cfgOf(join(root, 'outside', 'x'))).toEqual(ONCE)
  })

  it('a frontmatter name pointing at a live cron task (no runAt): that task stays', () => {
    expect(removeScheduledTaskDir('live-guard', { runAt: RUN_AT, createdAt: CREATED }, tasks)).toBe(false)
    expect(cfgOf(join(tasks, 'live-guard'))).toEqual(LIVE)
  })

  it('another runAt or another createdAt: stays; no runAt expected: stays', () => {
    expect(removeScheduledTaskDir('once', { runAt: RUN_AT + 1, createdAt: CREATED }, tasks)).toBe(false)
    expect(removeScheduledTaskDir('once', { runAt: RUN_AT, createdAt: CREATED + 1 }, tasks)).toBe(false)
    expect(removeScheduledTaskDir('once', { createdAt: CREATED }, tasks)).toBe(false)
    expect(cfgOf(join(tasks, 'once'))).toEqual(ONCE)
  })

  it('a cron task (no runAt) with nothing expected for runAt: stays (only a one-shot is ever removed)', () => {
    expect(removeScheduledTaskDir('live-guard', { createdAt: LIVE.createdAt }, tasks)).toBe(false)
    expect(cfgOf(join(tasks, 'live-guard'))).toEqual(LIVE)
  })

  it('a task dir with no or broken config: stays', () => {
    mkdirSync(join(tasks, 'bare'))
    put(join(tasks, 'broken'), {})
    writeFileSync(join(tasks, 'broken', 'task-config.json'), '{not json')
    expect(removeScheduledTaskDir('bare', { runAt: RUN_AT, createdAt: CREATED }, tasks)).toBe(false)
    expect(removeScheduledTaskDir('broken', { runAt: RUN_AT, createdAt: CREATED }, tasks)).toBe(false)
    expect(existsSync(join(tasks, 'bare'))).toBe(true)
    expect(existsSync(join(tasks, 'broken'))).toBe(true)
  })

  it('a config without createdAt matches a listed createdAt of 0 (readScheduledTask reads it so)', () => {
    put(join(tasks, 'no-created'), { schedule: '0 9 * * *', runAt: RUN_AT })
    expect(removeScheduledTaskDir('no-created', { runAt: RUN_AT, createdAt: 0 }, tasks)).toBe(true)
  })
})

describe('disableScheduledTaskOnDisk through the same guard', () => {
  it('a symlinked task dir pointing outside is not written (Viktor 42613 INFO 1)', () => {
    const dated = { schedule: '55 10 9 11 *', enabled: true, createdAt: CREATED }
    put(join(root, 'outside'), dated)
    expect(disableScheduledTaskOnDisk('lnk-out', tasks, { schedule: dated.schedule, createdAt: CREATED })).toBe(false)
    expect(cfgOf(join(root, 'outside'))).toEqual(dated)
  })
})
