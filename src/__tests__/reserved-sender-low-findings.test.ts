// RESERVEDSENDER1013 follow-up -- Viktor's two LOW findings on dca6d31a.
//
// L1: the look-alike map in reserved-sender.ts is a denylist, so Latin small
//     capitals ('ꜱʏꜱᴛᴇᴍ') and Cherokee ('Ꮪystem') slipped past it. A sender taken
//     from the request is now also held to a positive rule: only the router's
//     id alphabet ([A-Za-z0-9_-]) may reach from_agent. The owner's exact
//     configured name is the one exception (it may carry accents).
// L2: a seeded command task could be enabled or rescheduled through the API.
//     Now the PUT accepts only {enabled:false} for it, and /toggle only
//     switches it off.
//
// The route tests run the real handlers. os.homedir() reads $HOME, and
// SCHEDULED_TASKS_DIR is computed at import, so HOME points at a temp dir
// BEFORE the modules load (same pattern as scheduled-task-deletion-tombstone).

import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { EventEmitter } from 'node:events'
import type { RouteContext } from '../web/routes/types.js'

const tmpHome = mkdtempSync(join(tmpdir(), 'reservedsender-low-'))
const realHome = process.env.HOME
process.env.HOME = tmpHome
process.env.MAIN_AGENT_ID = process.env.MAIN_AGENT_ID || 'marveen'

let rs: typeof import('../reserved-sender.js')
let lock: typeof import('../web/routes/desktop-lock.js')
let messages: typeof import('../web/routes/messages.js')
let schedules: typeof import('../web/routes/schedules.js')
let fields: typeof import('../web/schedule-api-fields.js')
let io: typeof import('../web/scheduled-tasks-io.js')
let config: typeof import('../config.js')

beforeAll(async () => {
  process.env.NODE_ENV = 'test'
  rs = await import('../reserved-sender.js')
  lock = await import('../web/routes/desktop-lock.js')
  messages = await import('../web/routes/messages.js')
  schedules = await import('../web/routes/schedules.js')
  fields = await import('../web/schedule-api-fields.js')
  io = await import('../web/scheduled-tasks-io.js')
  config = await import('../config.js')
  const db = await import('../db.js')
  db.initDatabase(':memory:')
})

afterAll(() => {
  process.env.HOME = realHome
  rmSync(tmpHome, { recursive: true, force: true })
})

// The two spellings Viktor measured as passing isReservedSender, plus the
// zero-width case the sanitized-compare in POST /api/messages let through.
const LOOKALIKES = ['ꜱʏꜱᴛᴇᴍ', 'Ꮪystem']
const ZWSP = '​'

function fakeCtx(path: string, method: string, body?: unknown) {
  const req = new EventEmitter() as unknown as RouteContext['req'] & { destroy(): void }
  ;(req as unknown as { headers: Record<string, string> }).headers = {}
  ;(req as { destroy(): void }).destroy = () => { /* readBody over-limit hook */ }
  const state = { statusCode: 0, body: '' }
  const res = {
    writeHead(code: number) { state.statusCode = code; return res },
    end(data?: unknown) { state.body = String(data ?? '') },
    setHeader() { /* not used by json() */ },
  } as unknown as RouteContext['res']
  process.nextTick(() => {
    if (body !== undefined) (req as unknown as EventEmitter).emit('data', Buffer.from(JSON.stringify(body)))
    ;(req as unknown as EventEmitter).emit('end')
  })
  const ctx = { req, res, path, method, url: new URL(`http://localhost${path}`), fedPeer: null, auth: { kind: 'token' } }
  return { ctx: ctx as unknown as RouteContext, res: state }
}

describe('isPlainSenderId (Viktor L1)', () => {
  it('refuses everything outside the router id alphabet', () => {
    for (const bad of [...LOOKALIKES, `kernel${ZWSP}`, 'kernel x', 'kérnel', 'a.b', 'peer/agent', '', '   ']) {
      expect(rs.isPlainSenderId(bad), JSON.stringify(bad)).toBe(false)
    }
  })

  it('NEGATIVE CONTROL: plain ids pass, surrounding whitespace is trimmed', () => {
    for (const ok of ['kernel', 'desktop-lock', 'video_review', 'Agent7', ' kernel ']) {
      expect(rs.isPlainSenderId(ok), JSON.stringify(ok)).toBe(true)
    }
  })

  it('the look-alikes really do pass the denylist alone (why L1 is needed)', () => {
    for (const s of LOOKALIKES) expect(rs.isReservedSender(s), s).toBe(false)
  })
})

describe('desktop-lock owner, positive rule (Viktor L1)', () => {
  it('refuses look-alikes and hidden characters', () => {
    for (const bad of [...LOOKALIKES, `kernel${ZWSP}`, 'kernel x']) {
      expect(lock.lockOwnerRefusal(bad), JSON.stringify(bad)).toMatch(/plain id/)
    }
  })

  it('NEGATIVE CONTROL: agents and the configured owner name keep the screen', () => {
    // The registry is injected: this suite runs without an agents/ directory.
    const fleet = new Set(['kernel', 'janna'])
    for (const ok of [...fleet, config.OWNER_NAME]) {
      expect(lock.lockOwnerRefusal(ok, (id) => fleet.has(id)), ok).toBeNull()
    }
  })
})

describe('POST /api/messages, positive rule (Viktor L1)', () => {
  async function post(from: string) {
    const { ctx, res } = fakeCtx('/api/messages', 'POST', { from, to: config.MAIN_AGENT_ID, content: 'probe' })
    expect(await messages.tryHandleMessages(ctx)).toBe(true)
    return { status: res.statusCode, json: JSON.parse(res.body) as Record<string, unknown> }
  }

  it('refuses a look-alike sender', async () => {
    for (const from of LOOKALIKES) {
      const r = await post(from)
      expect(r.status, from).toBe(403)
    }
  })

  it('refuses a registered id with a zero-width character (it used to be stored as written)', async () => {
    const r = await post(`${config.MAIN_AGENT_ID}${ZWSP}`)
    expect(r.status).toBe(403)
    expect(String(r.json.error)).toMatch(/plain id/)
  })

  it('NEGATIVE CONTROL: the plain id is accepted and stored as sent', async () => {
    const r = await post(config.MAIN_AGENT_ID)
    expect(r.status).toBe(200)
    expect(r.json.from_agent).toBe(config.MAIN_AGENT_ID)
  })
})

describe('command tasks are disable-only over HTTP (Viktor L2)', () => {
  const agents = new Set(['marveen', 'kernel'])

  it('PUT: only {enabled:false} is accepted for a command task', () => {
    expect(fields.validateScheduleUpdate({ enabled: false }, 'command', agents))
      .toEqual({ ok: true, update: { enabled: false } })
    for (const body of [
      { enabled: true },
      { schedule: '* * * * *' },
      { enabled: false, schedule: '* * * * *' },
      { type: 'command' },
      { type: 'task' },
      { prompt: 'x' },
      {},
    ]) {
      const v = fields.validateScheduleUpdate(body, 'command', agents)
      expect(v.ok, JSON.stringify(body)).toBe(false)
      if (!v.ok) expect(v.error).toBe(fields.COMMAND_TASK_API_REFUSAL)
    }
  })

  it('NEGATIVE CONTROL: a task/heartbeat task is still fully editable', () => {
    expect(fields.validateScheduleUpdate({ enabled: true, schedule: '0 9 * * *' }, 'task', agents).ok).toBe(true)
    expect(fields.validateScheduleUpdate({ type: 'heartbeat' }, 'task', agents).ok).toBe(true)
  })

  function seed(name: string, cfg: Record<string, unknown>): string {
    const dir = join(io.SCHEDULED_TASKS_DIR, name)
    mkdirSync(dir, { recursive: true })
    const path = join(dir, 'task-config.json')
    writeFileSync(path, JSON.stringify(cfg, null, 2))
    return path
  }

  async function toggle(name: string) {
    const path = `/api/schedules/${name}/toggle`
    const { ctx, res } = fakeCtx(path, 'POST')
    expect(await schedules.tryHandleSchedules(ctx)).toBe(true)
    return { status: res.statusCode, json: JSON.parse(res.body) as Record<string, unknown> }
  }

  it('toggle refuses to switch a disabled command task on, and writes nothing', async () => {
    const path = seed('cmd-off', { type: 'command', command: 'true', schedule: '0 4 * * 3', enabled: false })
    const before = readFileSync(path, 'utf-8')
    const r = await toggle('cmd-off')
    expect(r.status).toBe(400)
    expect(r.json.error).toBe(fields.COMMAND_TASK_API_REFUSAL)
    expect(readFileSync(path, 'utf-8')).toBe(before)
  })

  it('toggle still switches an enabled command task off', async () => {
    const path = seed('cmd-on', { type: 'command', command: 'true', schedule: '*/15 * * * *', enabled: true })
    const r = await toggle('cmd-on')
    expect(r.status).toBe(200)
    expect(r.json.enabled).toBe(false)
    expect(JSON.parse(readFileSync(path, 'utf-8')).enabled).toBe(false)
  })

  it('NEGATIVE CONTROL: toggle switches a disabled ordinary task on', async () => {
    const path = seed('plain-off', { type: 'task', prompt: 'p', schedule: '0 8 * * *', enabled: false })
    const r = await toggle('plain-off')
    expect(r.status).toBe(200)
    expect(JSON.parse(readFileSync(path, 'utf-8')).enabled).toBe(true)
  })
})
