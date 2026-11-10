// Klodel 35737 (Patrik group TG 4465 "mehet"): agent_messages.priority.
// Pinned here: the column exists with a 'normal' default, createAgentMessage stores what it is given and reads
// back through getPendingMessages (the router's input), and parseMessagePriority only ever yields 'urgent' for
// the exact string.

import { describe, it, expect, beforeAll } from 'vitest'
import { EventEmitter } from 'node:events'
import { initDatabase, createAgentMessage, getPendingMessages, getAgentMessage, parseMessagePriority } from '../db.js'
import { MAIN_AGENT_ID } from '../config.js'
import { tryHandleMessages } from '../web/routes/messages.js'
import type { RouteContext } from '../web/routes/types.js'

beforeAll(() => {
  process.env.NODE_ENV = 'test'
  initDatabase(':memory:')
})

// The real route handler, same harness as messages-post-queue-field.test.ts.
async function post(body: unknown): Promise<{ statusCode: number; json: Record<string, unknown> }> {
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
    ;(req as unknown as EventEmitter).emit('data', Buffer.from(JSON.stringify(body)))
    ;(req as unknown as EventEmitter).emit('end')
  })
  const path = '/api/messages'
  const handled = await tryHandleMessages({ req, res, path, method: 'POST', url: new URL(`http://localhost${path}`), fedPeer: null } as RouteContext)
  expect(handled).toBe(true)
  return { statusCode: state.statusCode, json: JSON.parse(state.body) }
}

describe('agent_messages.priority', () => {
  it('a message created without a priority is normal, an urgent one reads back urgent', () => {
    const to = 'urgent-db-' + Date.now()
    const plain = createAgentMessage('subA', to, 'plain')
    const urgent = createAgentMessage('subB', to, 'urgent', null, null, 'urgent')
    expect(plain.priority).toBe('normal')
    expect(urgent.priority).toBe('urgent')
    const rows = getPendingMessages(to)
    expect(rows.map((m) => [m.content, m.priority])).toEqual([['plain', 'normal'], ['urgent', 'urgent']])
  })
})

describe('parseMessagePriority', () => {
  it('only the exact string "urgent" is urgent', () => {
    expect(parseMessagePriority('urgent')).toBe('urgent')
    for (const v of [undefined, null, '', 'normal', 'URGENT', ' urgent', 'urgnet', 1, true, {}]) {
      expect(parseMessagePriority(v)).toBe('normal')
    }
  })
})

describe('POST /api/messages priority', () => {
  it('"priority":"urgent" is stored, no priority stays normal', async () => {
    const u = await post({ from: MAIN_AGENT_ID, to: MAIN_AGENT_ID, content: 'urgent one', priority: 'urgent' })
    const n = await post({ from: MAIN_AGENT_ID, to: MAIN_AGENT_ID, content: 'plain one' })
    expect(u.statusCode).toBe(200)
    expect(n.statusCode).toBe(200)
    expect(getAgentMessage(u.json.id as number)?.priority).toBe('urgent')
    expect(getAgentMessage(n.json.id as number)?.priority).toBe('normal')
  })
  it('an unknown priority is refused with 400, not silently downgraded', async () => {
    for (const priority of ['urgnet', 'URGENT', 1, true]) {
      const r = await post({ from: MAIN_AGENT_ID, to: MAIN_AGENT_ID, content: 'typo', priority })
      expect(r.statusCode).toBe(400)
      expect(String(r.json.error)).toMatch(/priority/)
    }
  })
})
