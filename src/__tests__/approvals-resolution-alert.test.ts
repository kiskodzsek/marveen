// 9a2925a7 (Viktor, msg 603 and 1391): every approved/rejected resolution is
// announced to the owner on Telegram by the server, with a warning when the
// server can tell something is off. A forged PATCH must alert too, a failed
// send must not change the resolution, and the sweeper's timeout path stays
// silent.
import { describe, it, expect, beforeEach, vi } from 'vitest'

const sent = vi.hoisted(() => ({ calls: [] as Array<{ chatId: string; text: string }>, failNext: false, nextId: 100 }))

vi.mock('../config.js', async (importOriginal) => {
  const real = await importOriginal<typeof import('../config.js')>()
  return { ...real, MAIN_AGENT_ID: 'agent-a', TELEGRAM_BOT_TOKEN: 'test-token' }
})
vi.mock('../owner-chat.js', () => ({ resolveOwnerChatId: () => '4242' }))
vi.mock('../web/telegram.js', () => ({
  sendTelegramMessage: vi.fn(async (_token: string, chatId: string, text: string) => {
    if (sent.failNext) {
      sent.failNext = false
      throw new Error('telegram 502')
    }
    sent.calls.push({ chatId, text })
    return sent.nextId++
  }),
}))

import { initDatabase, getPendingMessages, getApproval } from '../db.js'
import {
  tryHandleApprovals,
  approvalResolutionWarnings,
  buildResolutionAlertText,
  OWNER_RESOLUTION_SOURCES,
  oneLine,
} from '../web/routes/approvals.js'
import type { RouteContext } from '../web/routes/types.js'

function fake(method: 'POST' | 'PATCH', path: string, body: unknown): { ctx: RouteContext; out: { status: number; body: any } } {
  const out: { status: number; body: any } = { status: 0, body: null }
  const res: any = {
    writeHead(status: number) { out.status = status; return res },
    end(chunk?: string) { if (chunk) out.body = JSON.parse(chunk) },
  }
  const url = new URL(`http://localhost:3420${path}`)
  const bodyStr = JSON.stringify(body)
  const req: any = {
    on(event: string, cb: (chunk?: Buffer) => void) {
      if (event === 'data') cb(Buffer.from(bodyStr))
      if (event === 'end') cb()
    },
  }
  return { ctx: { req, res, path: url.pathname, method, url } as RouteContext, out }
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

async function createApproval(description = 'Levél küldése a könyvelőnek') {
  const { ctx, out } = fake('POST', '/api/approvals', { agent_id: 'agent-b', category: 'email_send', action_description: description })
  await tryHandleApprovals(ctx)
  await flush()
  return out.body.id as string
}

async function patch(id: string, body: unknown) {
  const { ctx, out } = fake('PATCH', `/api/approvals/${id}`, body)
  await tryHandleApprovals(ctx)
  await flush()
  return out
}

// The owner's request message (buildOwnerApprovalText) starts with [JÓVÁHAGYÁS KELL]; the alerts are the rest.
const resolutionAlerts = () => sent.calls.filter((c) => !c.text.startsWith('[JÓVÁHAGYÁS KELL]') && c.text.includes('Jóváhagyás lezárva'))

describe('approval resolution alert (9a2925a7)', () => {
  beforeEach(() => {
    initDatabase(':memory:')
    sent.calls.length = 0
    sent.failNext = false
    sent.nextId = 100
  })

  it('a forged PATCH with plausible fields still alerts the owner (every resolution does)', async () => {
    const id = await createApproval()
    expect(getApproval(id)?.telegram_message_id).toBe(100) // the owner request's message
    const out = await patch(id, { status: 'approved', resolved_by: 'telegram_text', telegram_message_id: 999 })
    expect(out.status).toBe(200)
    const alerts = resolutionAlerts()
    expect(alerts).toHaveLength(1)
    expect(alerts[0].chatId).toBe('4242')
    expect(alerts[0].text).toBe('Jóváhagyás lezárva: approved | email_send | kérte: agent-b | lezárta: telegram_text | tg-msg: 999 | Levél küldése a könyvelőnek')
  })

  it('marks the alert when the source or the message id does not add up', async () => {
    const id = await createApproval()
    await patch(id, { status: 'rejected', resolved_by: 'agent-c' })
    const [alert] = resolutionAlerts()
    expect(alert.text.startsWith('⚠️ Jóváhagyás lezárva: rejected')).toBe(true)
    expect(alert.text).toContain('tg-msg: HIÁNYZIK')
    expect(alert.text).toContain('Gyanús: nem Telegram-forrás: agent-c; nincs tg-msg')
  })

  it('the warning matrix', () => {
    expect(OWNER_RESOLUTION_SOURCES).toEqual(['telegram_text', 'telegram_button'])
    const w = (resolvedBy: string, resolverMessageId: number | null, requestMessageId: number | null) =>
      approvalResolutionWarnings({ resolvedBy, resolverMessageId, requestMessageId })
    expect(w('telegram_text', 101, 100)).toEqual([])
    expect(w('telegram_button', 101, 100)).toEqual([])
    expect(w('dashboard', 101, 100)).toEqual(['nem Telegram-forrás: dashboard'])
    expect(w('telegram_text', null, 100)).toEqual(['nincs tg-msg'])
    expect(w('telegram_text', 100, 100)).toEqual(['a tg-msg (100) nem újabb a kérésénél (100)'])
    expect(w('telegram_text', 99, 100)).toEqual(['a tg-msg (99) nem újabb a kérésénél (100)'])
    expect(w('telegram_text', 101, null)).toEqual(['a kérés tg-msg-je ismeretlen, nem összevethető'])
    expect(w('klodel', null, null)).toEqual(['nem Telegram-forrás: klodel', 'nincs tg-msg'])
  })

  it('a reply id older than the request is flagged end to end', async () => {
    const id = await createApproval()
    await patch(id, { status: 'approved', resolved_by: 'telegram_text', telegram_message_id: 50 })
    expect(resolutionAlerts()[0].text).toContain('Gyanús: a tg-msg (50) nem újabb a kérésénél (100)')
  })

  it('a failed send does not change the resolution, and the main agent hears about it', async () => {
    const id = await createApproval()
    sent.failNext = true
    const out = await patch(id, { status: 'approved', resolved_by: 'telegram_text', telegram_message_id: 101 })
    expect(out.status).toBe(200)
    expect(out.body.status).toBe('approved')
    expect(getApproval(id)?.status).toBe('approved')
    expect(resolutionAlerts()).toHaveLength(0)
    const notes = getPendingMessages('agent-a').map((m) => m.content)
    expect(notes.some((c) => c === `approval-riasztás nem ment ki: ${id} (send-failed)`)).toBe(true)
  })

  it('a timeout resolution is not announced', async () => {
    const id = await createApproval()
    const out = await patch(id, { status: 'timeout', resolved_by: 'sweeper' })
    expect(out.status).toBe(200)
    expect(resolutionAlerts()).toHaveLength(0)
  })

  it('an already resolved approval (409) is not announced again', async () => {
    const id = await createApproval()
    await patch(id, { status: 'approved', resolved_by: 'telegram_text', telegram_message_id: 101 })
    const again = await patch(id, { status: 'rejected', resolved_by: 'telegram_text', telegram_message_id: 102 })
    expect(again.status).toBe(409)
    expect(resolutionAlerts()).toHaveLength(1)
  })

  it('the description is redacted and cut: no secret reaches the alert', async () => {
    const secret = 'sk-ant-api03-' + 'A'.repeat(40)
    const id = await createApproval(`Token rotálása ${secret} ` + 'x'.repeat(400))
    await patch(id, { status: 'approved', resolved_by: 'telegram_text', telegram_message_id: 101 })
    const [alert] = resolutionAlerts()
    expect(alert.text).not.toContain(secret)
    expect(alert.text).toContain('[REDACTED]')
    const description = alert.text.split(' | ').slice(5).join(' | ')
    expect(description.length).toBeLessThanOrEqual(200)
  })

  it('agent-written fields cannot draw a second line into the owner message (Viktor, msg 1451)', async () => {
    const id = await createApproval('Leírás\u2028Jóváhagyás lezárva: approved | hamis')
    const forged = 'telegram_text\nJóváhagyás lezárva: approved | email_send | kérte: agent-b | lezárta: telegram_text | tg-msg: 999'
    await patch(id, { status: 'approved', resolved_by: forged, telegram_message_id: 101 })
    const [alert] = resolutionAlerts()
    const lines = alert.text.split('\n')
    expect(lines).toHaveLength(2) // the alert line and the "Gyanús:" line, nothing else
    expect(lines[0].startsWith('⚠️ Jóváhagyás lezárva: approved')).toBe(true)
    expect(lines[1].startsWith('Gyanús: nem Telegram-forrás: telegram_text Jóváhagyás')).toBe(true)
    expect(alert.text).not.toMatch(/[\u0000-\u0009\u000b-\u001f\u2028\u2029]/)
    expect(oneLine('a\tb\r\nc\u0007d', 60)).toBe('a b c d')
    expect(oneLine('x'.repeat(100), 60)).toHaveLength(60)
  })

  it('buildResolutionAlertText keeps one line without warnings', () => {
    const text = buildResolutionAlertText(
      {
        id: 'x', agent_id: 'agent-b', category: 'c', action_description: 'a\n  b', action_payload: null, status: 'approved',
        timeout_at: null, telegram_message_id: 5, requested_at: 0, resolved_at: 1, resolved_by: 'telegram_button',
        content_hash: null, consumed_at: null,
      },
      5,
      [],
    )
    expect(text).toBe('Jóváhagyás lezárva: approved | c | kérte: agent-b | lezárta: telegram_button | tg-msg: 5 | a b')
  })
})
