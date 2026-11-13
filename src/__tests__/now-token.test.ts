import { describe, it, expect, beforeAll } from 'vitest'
import { EventEmitter } from 'node:events'
import { initDatabase, createAgentMessage, getAgentMessage, getDailyLog, getDailyLogDates, getPendingMessages } from '../db.js'
import { tryHandleMessages } from '../web/routes/messages.js'
import { tryHandleDailyLog } from '../web/routes/daily-log.js'
import { fillNowToken, NOW_TOKEN } from '../web/now-token.js'
import { APP_TZ, MAIN_AGENT_ID } from '../config.js'
import type { RouteContext } from '../web/routes/types.js'

// Retro 2026-11-13 R1 (card 028205dd): {{NOW}} in a message, a close result or a daily-log entry is the
// server's clock at the write, so the author never types a "measured" time that has not come yet.

const hhmm = (d: Date) =>
  new Intl.DateTimeFormat('sv-SE', { timeZone: APP_TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(d)
const CLOCK = /^\d{2}:\d{2}$/

beforeAll(() => { initDatabase(':memory:') })

describe('fillNowToken', () => {
  const NOW = new Date('2026-11-13T18:05:09Z')

  it('replaces every {{NOW}} with HH:MM in the install zone', () => {
    const out = fillNowToken('## {{NOW}} -- Téma\nmérve {{NOW}} date', NOW)
    expect(out).toBe(`## ${hhmm(NOW)} -- Téma\nmérve ${hhmm(NOW)} date`)
    expect(hhmm(NOW)).toMatch(CLOCK)
  })

  it('uses the 24-hour clock past midnight (00, not 24)', () => {
    const late = new Date('2026-11-13T23:30:00Z')
    expect(fillNowToken(NOW_TOKEN, late)).toMatch(CLOCK)
    expect(fillNowToken(NOW_TOKEN, late)?.startsWith('24')).toBe(false)
  })

  it('leaves other spellings and texts without the token untouched', () => {
    for (const t of ['{{ NOW }}', '{NOW}', '{{now}}', 'nincs benne token', '']) expect(fillNowToken(t, NOW)).toBe(t)
    expect(fillNowToken(undefined, NOW)).toBeUndefined()
    expect(fillNowToken(null, NOW)).toBeNull()
  })
})

function fakeReq(body: unknown): RouteContext['req'] {
  const req = new EventEmitter() as unknown as RouteContext['req']
  ;(req as unknown as { headers: Record<string, string> }).headers = {}
  process.nextTick(() => {
    ;(req as unknown as EventEmitter).emit('data', Buffer.from(JSON.stringify(body)))
    ;(req as unknown as EventEmitter).emit('end')
  })
  return req
}

function fakeRes(state: { statusCode: number; body: string }): RouteContext['res'] {
  const res = {
    writeHead(code: number) { state.statusCode = code; return res },
    end(data?: unknown) { state.body = String(data ?? '') },
    setHeader() {},
  } as unknown as RouteContext['res']
  return res
}

async function call(handler: (ctx: RouteContext) => Promise<boolean>, method: string, path: string, body: unknown) {
  const state = { statusCode: 0, body: '' }
  const handled = await handler({
    req: fakeReq(body), res: fakeRes(state), path, method, url: new URL(`http://localhost${path}`), fedPeer: null,
  } as RouteContext)
  expect(handled).toBe(true)
  return { statusCode: state.statusCode || 200, json: state.body ? JSON.parse(state.body) : null }
}

// The minute may roll over between the call and the check: accept the clock before and after.
function stampedNow(text: string, before: Date, after: Date): boolean {
  return [hhmm(before), hhmm(after)].some((c) => text.includes(c))
}

describe('the write paths fill {{NOW}} at the server', () => {
  it('PUT /api/messages/:id result', async () => {
    const msg = createAgentMessage(MAIN_AGENT_ID, 'dex', 'Delegated task')
    const before = new Date()
    const r = await call(tryHandleMessages, 'PUT', `/api/messages/${msg.id}`, { status: 'done', result: 'kész, mérve {{NOW}}' })
    const after = new Date()
    expect(r.statusCode).toBe(200)
    const stored = getAgentMessage(msg.id)!.result ?? ''
    expect(stored).not.toContain(NOW_TOKEN)
    expect(stampedNow(stored, before, after)).toBe(true)
  })

  it('PUT with notify: the ack carries the filled result too', async () => {
    const msg = createAgentMessage(MAIN_AGENT_ID, 'dex', 'Delegated task 2')
    await call(tryHandleMessages, 'PUT', `/api/messages/${msg.id}`, { status: 'done', result: 'ack {{NOW}}', notify: true })
    const ack = getPendingMessages(MAIN_AGENT_ID).find((m) => m.content.includes(`msg_id:${msg.id}`))
    expect(ack).toBeDefined()
    expect(ack!.content).not.toContain(NOW_TOKEN)
  })

  it('POST /api/daily-log content (the "## {{NOW}} -- Téma" heading)', async () => {
    const before = new Date()
    const r = await call(tryHandleDailyLog, 'POST', '/api/daily-log', { agent_id: 'dex', content: '## {{NOW}} -- R1 próba' })
    const after = new Date()
    expect(r.statusCode).toBe(200)
    const log = JSON.stringify(getDailyLogDates('dex').flatMap((d) => getDailyLog('dex', d)))
    expect(log).not.toContain(NOW_TOKEN)
    expect(log).toContain('R1 próba')
    expect(stampedNow(log, before, after)).toBe(true)
  })

  it('POST /api/messages content', async () => {
    const before = new Date()
    const r = await call(tryHandleMessages, 'POST', '/api/messages', { from: MAIN_AGENT_ID, to: MAIN_AGENT_ID, content: 'mérve {{NOW}}: R1' })
    const after = new Date()
    expect(r.statusCode).toBe(200)
    const row = getAgentMessage(r.json.id)!
    expect(row.content).not.toContain(NOW_TOKEN)
    expect(stampedNow(row.content, before, after)).toBe(true)
  })
})
