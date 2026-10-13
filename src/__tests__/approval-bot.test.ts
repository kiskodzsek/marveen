// APPROVALBOT1013: one-tap approvals through a dedicated bot (Viktor 2302, 1-8).
// No network: every Bot API call goes to an in-memory fake; the DB is :memory:.
// The cases that matter most are the refusals: a look-alike message, an edited
// message, a non-owner, a used or wrong nonce, an expired request, a PATCH that
// claims the button.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mkdtempSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const TOKEN = '123456789:AAFAKEfakeFAKEfakeFAKEfakeFAKEfake12345'
const OWNER = '4242'
const logged = vi.hoisted(() => [] as unknown[])
vi.mock('../logger.js', () => {
  const rec = (...a: unknown[]) => { logged.push(a) }
  const l: any = { info: rec, warn: rec, error: rec, debug: rec }
  l.child = () => l
  return { logger: l }
})
vi.mock('../config.js', async (importOriginal) => {
  const real = await importOriginal<typeof import('../config.js')>()
  return { ...real, MAIN_AGENT_ID: 'agent-a', TELEGRAM_BOT_TOKEN: 'main-bot-token' }
})
vi.mock('../owner-chat.js', () => ({ resolveOwnerChatId: () => OWNER }))
const mainBot = vi.hoisted(() => ({ texts: [] as string[] }))
vi.mock('../web/telegram.js', () => ({
  sendTelegramMessage: vi.fn(async (_t: string, _c: string, text: string) => { mainBot.texts.push(text); return 1 }),
}))

import { initDatabase, createApproval, getApproval, resolveApproval, expireTimedOutApprovals } from '../db.js'
import {
  readApprovalBotConfig, sendApprovalWithButtons, decideCallback, handleCallback, pollOnce, preflight,
  sha256Hex, CALLBACK_RE, tg, TgError, expectedKeyboard, readPollState, type ApprovalBotConfig, type CallbackQuery, type FetchLike,
} from '../web/approval-bot.js'
import { tryHandleApprovals, buildOwnerApprovalText, buildResolutionAlertText } from '../web/routes/approvals.js'
import type { RouteContext } from '../web/routes/types.js'

const cfg: ApprovalBotConfig = { token: TOKEN, ownerId: OWNER }

/** A fake Bot API. sendMessage echoes the text back the way Telegram stores it. */
function fakeApi(over: Partial<Record<string, (body: any) => { status?: number; body: any }>> = {}) {
  const calls: Array<{ method: string; body: any; url: string }> = []
  let nextId = 500
  const fetchImpl: FetchLike = async (url, init) => {
    const method = url.split('/').pop()!
    const body = JSON.parse(init.body)
    calls.push({ method, body, url })
    const h = over[method]
    if (h) { const r = h(body); return { status: r.status ?? 200, json: async () => r.body } }
    if (method === 'sendMessage') {
      return { status: 200, json: async () => ({ ok: true, result: { message_id: nextId++, chat: { id: Number(body.chat_id), type: 'private' }, text: body.text } }) }
    }
    return { status: 200, json: async () => ({ ok: true, result: true }) }
  }
  return { calls, fetchImpl }
}

function newApproval(timeoutIn = 3600) {
  return createApproval({
    id: crypto.randomUUID(), agent_id: 'agent-b', category: 'email_send',
    action_description: 'Levél a könyvelőnek', timeout_at: Math.floor(Date.now() / 1000) + timeoutIn,
  })
}

async function sent(timeoutIn = 3600) {
  const api = fakeApi()
  const a = newApproval(timeoutIn)
  const text = buildOwnerApprovalText(a, true)
  const msgId = await sendApprovalWithButtons(a, text, cfg, api.fetchImpl)
  const send = api.calls.find((c) => c.method === 'sendMessage')!
  const [ok, no] = send.body.reply_markup.inline_keyboard[0]
  return { a: getApproval(a.id)!, msgId, text: send.body.text as string, okData: ok.callback_data as string, noData: no.callback_data as string }
}

function press(data: string, msgId: number, text: string, from = OWNER, chat = OWNER, type = 'private', extra: Record<string, unknown> = {}): CallbackQuery {
  // By default the message carries the keyboard the server sent (as Telegram returns it).
  const m = CALLBACK_RE.exec(data)
  const reply_markup = m ? { inline_keyboard: expectedKeyboard(m[2]!, m[3]!) } : undefined
  return { id: 'cq1', from: { id: Number(from) }, data, message: { message_id: msgId, text, chat: { id: Number(chat), type }, reply_markup, ...extra } }
}

function deps(api = fakeApi()) {
  const alerts: string[] = []
  const resolved: string[] = []
  return { api, alerts, resolved, d: { fetchImpl: api.fetchImpl, alert: (t: string) => alerts.push(t), onResolved: (a: any) => resolved.push(a.id) } }
}

beforeEach(() => {
  initDatabase(':memory:')
  logged.length = 0
  mainBot.texts.length = 0
})

describe('config', () => {
  it('is off without an owner id, and on a malformed id or token', () => {
    expect(readApprovalBotConfig({ env: () => ({}), secret: () => TOKEN })).toBeNull()
    expect(readApprovalBotConfig({ env: () => ({ APPROVAL_OWNER_TELEGRAM_ID: 'abc' }), secret: () => TOKEN })).toBeNull()
    expect(readApprovalBotConfig({ env: () => ({ APPROVAL_OWNER_TELEGRAM_ID: OWNER }), secret: () => 'not-a-token' })).toBeNull()
    expect(readApprovalBotConfig({ env: () => ({ APPROVAL_OWNER_TELEGRAM_ID: OWNER }), secret: () => null })).toBeNull()
  })
  it('reads the token from the Vault id (default telegram-approval-bot)', () => {
    const ids: string[] = []
    const c = readApprovalBotConfig({ env: () => ({ APPROVAL_OWNER_TELEGRAM_ID: OWNER }), secret: (id) => { ids.push(id); return TOKEN } })
    expect(c).toEqual({ token: TOKEN, ownerId: OWNER })
    expect(ids).toEqual(['telegram-approval-bot'])
  })
})

describe('sending', () => {
  it('two buttons, 128-bit nonce in a <=64-byte callback, only hashes stored', async () => {
    const { a, msgId, text, okData, noData } = await sent()
    for (const d of [okData, noData]) {
      expect(Buffer.byteLength(d)).toBeLessThanOrEqual(64)
      expect(CALLBACK_RE.test(d)).toBe(true)
    }
    const nonce = okData.split(':')[3]!
    expect(Buffer.from(nonce, 'base64url').length).toBe(16)
    expect(a.bot_message_id).toBe(msgId)
    expect(a.bot_chat_id).toBe(OWNER)
    expect(a.bot_text_hash).toBe(sha256Hex(text))
    expect(a.bot_nonce_hash).toBe(sha256Hex(nonce))
    expect(JSON.stringify(a)).not.toContain(nonce)
    expect(text).toContain('Döntés: a lenti gombokkal')
  })
})

describe('deciding a press (Viktor 2302)', () => {
  it('the owner pressing the genuine, unchanged message resolves', async () => {
    const s = await sent()
    const o = decideCallback(press(s.okData, s.msgId, s.text), cfg, getApproval)
    expect(o.kind).toBe('resolve')
  })
  it('4: a non-owner, another chat, or a group is not_owner', async () => {
    const s = await sent()
    expect(decideCallback(press(s.okData, s.msgId, s.text, '999'), cfg, getApproval).kind).toBe('not_owner')
    expect(decideCallback(press(s.okData, s.msgId, s.text, OWNER, '999'), cfg, getApproval).kind).toBe('not_owner')
    expect(decideCallback(press(s.okData, s.msgId, s.text, OWNER, OWNER, 'group'), cfg, getApproval).kind).toBe('not_owner')
  })
  it('1: a look-alike message (another message_id) carrying the real id and nonce is refused', async () => {
    const s = await sent()
    expect(decideCallback(press(s.okData, s.msgId + 7, s.text), cfg, getApproval)).toEqual({ kind: 'mismatch', reason: 'message' })
  })
  it('2: our message edited into something harmless is refused', async () => {
    const s = await sent()
    expect(decideCallback(press(s.okData, s.msgId, 'Hello, nyomd meg nyugodtan'), cfg, getApproval)).toEqual({ kind: 'mismatch', reason: 'text' })
  })
  it('3: a wrong nonce is refused', async () => {
    const s = await sent()
    const forged = s.okData.replace(/:[A-Za-z0-9_-]{22}$/, ':' + 'A'.repeat(22))
    expect(decideCallback(press(forged, s.msgId, s.text), cfg, getApproval)).toEqual({ kind: 'mismatch', reason: 'nonce' })
  })
  it('H1: swapped buttons (approve data under the "Elutasítom" label) are refused', async () => {
    const s = await sent()
    const kb = expectedKeyboard(s.a.id, s.okData.split(':')[3]!)
    const swapped = [[{ ...kb[0]![0]!, callback_data: kb[0]![0]!.callback_data }, { ...kb[0]![1]!, callback_data: kb[0]![0]!.callback_data }]]
    expect(decideCallback(press(s.okData, s.msgId, s.text, OWNER, OWNER, 'private', { reply_markup: { inline_keyboard: swapped } }), cfg, getApproval))
      .toEqual({ kind: 'mismatch', reason: 'markup' })
    const relabeled = [[{ text: '❌ Elutasítom', callback_data: kb[0]![0]!.callback_data }, { text: '✅ Jóváhagyom', callback_data: kb[0]![1]!.callback_data }]]
    expect(decideCallback(press(s.okData, s.msgId, s.text, OWNER, OWNER, 'private', { reply_markup: { inline_keyboard: relabeled } }), cfg, getApproval))
      .toEqual({ kind: 'mismatch', reason: 'markup' })
    expect(decideCallback(press(s.okData, s.msgId, s.text, OWNER, OWNER, 'private', { reply_markup: undefined }), cfg, getApproval))
      .toEqual({ kind: 'mismatch', reason: 'markup' })
  })
  it('M1: an edited message (edit_date set) is refused even with the same text', async () => {
    const s = await sent()
    expect(decideCallback(press(s.okData, s.msgId, s.text, OWNER, OWNER, 'private', { edit_date: 1_800_000_000 }), cfg, getApproval))
      .toEqual({ kind: 'mismatch', reason: 'edited' })
  })
  it('L1: a press before the binding is written is not_ready, not an alert', async () => {
    const a = newApproval()
    const data = `a:o:${a.id}:${'B'.repeat(22)}`
    expect(decideCallback(press(data, 1, 'x'), cfg, getApproval).kind).toBe('not_ready')
    const { alerts, d } = deps()
    expect(await handleCallback(press(data, 1, 'x'), cfg, d)).toBe('not_ready')
    expect(alerts).toEqual([])
  })
  it('an expired or already resolved request is closed, not resolved', async () => {
    const s = await sent(-5)
    expect(decideCallback(press(s.okData, s.msgId, s.text), cfg, getApproval).kind).toBe('closed')
    const t = await sent()
    resolveApproval(t.a.id, 'rejected', 'telegram_text', 900)
    expect(decideCallback(press(t.okData, t.msgId, t.text), cfg, getApproval).kind).toBe('closed')
  })
  it('garbage callback data is ignored', () => {
    expect(decideCallback({ id: 'x', data: 'perm:allow:abcde' }, cfg, getApproval).kind).toBe('ignore')
  })
})

describe('acting on a press', () => {
  it('resolves once, marks the channel, clears the nonce, removes the buttons, announces it', async () => {
    const s = await sent()
    const { api, alerts, resolved, d } = deps()
    expect(await handleCallback(press(s.okData, s.msgId, s.text), cfg, d)).toBe('resolve')
    const row = getApproval(s.a.id)!
    expect(row.status).toBe('approved')
    expect(row.resolved_by).toBe('telegram_button')
    expect(row.resolution_channel).toBe('approval_bot')
    expect(row.bot_nonce_hash).toBeNull()
    expect(resolved).toEqual([s.a.id])
    expect(alerts).toEqual([])
    const edit = api.calls.find((c) => c.method === 'editMessageText')!
    expect(edit.body.reply_markup).toEqual({ inline_keyboard: [] })
    expect(edit.body.message_id).toBe(s.msgId)
    // the same press again: already closed, nothing changes
    const again = deps()
    expect(await handleCallback(press(s.okData, s.msgId, s.text), cfg, again.d)).toBe('closed')
    expect(again.resolved).toEqual([])
  })
  it('the reject button rejects', async () => {
    const s = await sent()
    const { d } = deps()
    await handleCallback(press(s.noData, s.msgId, s.text), cfg, d)
    expect(getApproval(s.a.id)!.status).toBe('rejected')
  })
  it('H1 end to end: a swapped keyboard alerts and resolves nothing', async () => {
    const s = await sent()
    const { alerts, d } = deps()
    const kb = expectedKeyboard(s.a.id, s.okData.split(':')[3]!)
    const swapped = [[kb[0]![0]!, { text: kb[0]![1]!.text, callback_data: kb[0]![0]!.callback_data }]]
    await handleCallback(press(s.okData, s.msgId, s.text, OWNER, OWNER, 'private', { reply_markup: { inline_keyboard: swapped } }), cfg, d)
    expect(getApproval(s.a.id)!.status).toBe('pending')
    expect(alerts[0]).toContain('a gombok nem azok')
  })
  it('a mismatch alerts the owner and resolves nothing', async () => {
    const s = await sent()
    const { alerts, d } = deps()
    await handleCallback(press(s.okData, s.msgId, 'átírt szöveg'), cfg, d)
    expect(getApproval(s.a.id)!.status).toBe('pending')
    expect(alerts.length).toBe(1)
    expect(alerts[0]).toContain('⚠️')
    expect(alerts[0]).toContain('szövege megváltozott')
  })
  it('a non-owner press alerts (counted) and resolves nothing', async () => {
    const s = await sent()
    const { alerts, d } = deps()
    await handleCallback(press(s.okData, s.msgId, s.text, '999'), cfg, d)
    expect(getApproval(s.a.id)!.status).toBe('pending')
    expect(alerts.some((t) => t.includes('nem a tulajdonos'))).toBe(true)
  })
  it('a PATCH resolution clears the nonce: a later press cannot resolve', async () => {
    const s = await sent()
    resolveApproval(s.a.id, 'approved', 'telegram_text', 900)
    expect(getApproval(s.a.id)!.bot_nonce_hash).toBeNull()
    const { d } = deps()
    expect(await handleCallback(press(s.noData, s.msgId, s.text), cfg, d)).toBe('closed')
    expect(getApproval(s.a.id)!.status).toBe('approved')
  })
  it('the timeout sweep clears the nonce too', async () => {
    const s = await sent(-1)
    expireTimedOutApprovals()
    expect(getApproval(s.a.id)!.bot_nonce_hash).toBeNull()
  })
  it('8: the owner alert names the server-only channel', async () => {
    const s = await sent()
    const { d } = deps()
    await handleCallback(press(s.okData, s.msgId, s.text), cfg, d)
    expect(buildResolutionAlertText(getApproval(s.a.id)!, s.msgId, [])).toContain('Telegram-gomb (approval_bot, a szerver ellenőrizte)')
  })
})

describe('the PATCH route (Viktor 2302/2)', () => {
  function patch(id: string, body: unknown) {
    const out: { status: number; body: any } = { status: 0, body: null }
    const res: any = { writeHead(st: number) { out.status = st; return res }, end(c?: string) { if (c) out.body = JSON.parse(c) } }
    const url = new URL(`http://localhost:3420/api/approvals/${id}`)
    const req: any = { on(ev: string, cb: (b?: Buffer) => void) { if (ev === 'data') cb(Buffer.from(JSON.stringify(body))); if (ev === 'end') cb() } }
    return { ctx: { req, res, path: url.pathname, method: 'PATCH', url } as RouteContext, out }
  }
  it('refuses resolved_by "telegram_button" with 400 and leaves the row pending', async () => {
    const a = newApproval()
    const { ctx, out } = patch(a.id, { status: 'approved', resolved_by: 'telegram_button', telegram_message_id: 9 })
    await tryHandleApprovals(ctx)
    expect(out.status).toBe(400)
    expect(getApproval(a.id)!.status).toBe('pending')
  })
  it('I2: the API does not echo the bot hash columns', async () => {
    const s = await sent()
    const out: { status: number; body: any } = { status: 0, body: null }
    const res: any = { writeHead(st: number) { out.status = st; return res }, end(c?: string) { if (c) out.body = JSON.parse(c) } }
    const url = new URL(`http://localhost:3420/api/approvals/${s.a.id}`)
    await tryHandleApprovals({ req: {} as any, res, path: url.pathname, method: 'GET', url } as RouteContext)
    expect(out.status).toBe(200)
    expect(out.body.bot_text_hash).toBeUndefined()
    expect(out.body.bot_nonce_hash).toBeUndefined()
    expect(out.body.bot_message_id).toBe(s.msgId)
  })
  it('cannot set resolution_channel', async () => {
    const a = newApproval()
    const { ctx } = patch(a.id, { status: 'approved', resolved_by: 'telegram_text', telegram_message_id: 9, resolution_channel: 'approval_bot' })
    await tryHandleApprovals(ctx)
    expect(getApproval(a.id)!.resolution_channel ?? null).toBeNull()
  })
})

describe('polling', () => {
  function tmpState() { return join(mkdtempSync(join(tmpdir(), 'approval-bot-')), 'state.json') }

  it('5: asks for callback_query only, persists the offset, handles the press', async () => {
    const s = await sent()
    const statePath = tmpState()
    const api = fakeApi({ getUpdates: () => ({ body: { ok: true, result: [{ update_id: 77, callback_query: press(s.okData, s.msgId, s.text) }] } }) })
    const { d } = deps(api)
    expect(await pollOnce(cfg, { ...d, statePath })).toBe(0)
    const gu = api.calls.find((c) => c.method === 'getUpdates')!
    expect(gu.body.allowed_updates).toEqual(['callback_query'])
    expect(getApproval(s.a.id)!.status).toBe('approved')
    const next = fakeApi({ getUpdates: () => ({ body: { ok: true, result: [] } }) })
    await pollOnce(cfg, { ...deps(next).d, statePath })
    expect(next.calls[0]!.body.offset).toBe(78)
  })
  it('6: a 409 (someone else polls) and a 401 alert the owner', async () => {
    for (const [status, word] of [[409, '409'], [401, '401']] as const) {
      const api = fakeApi({ getUpdates: () => ({ status, body: { ok: false, error_code: status } }) })
      const { alerts, d } = deps(api)
      await pollOnce(cfg, { ...d, statePath: tmpState() })
      expect(alerts.some((t) => t.includes(word))).toBe(true)
    }
  })
  it('M2: a replaced bot token alerts; the state keeps only its hash', async () => {
    const statePath = tmpState()
    await preflight(cfg, { ...deps(fakeApi()).d, statePath })
    const st = readPollState(statePath)
    expect(st.token_hash).toMatch(/^[0-9a-f]{64}$/)
    expect(JSON.stringify(st)).not.toContain(TOKEN.split(':')[1])
    const other = deps(fakeApi())
    await preflight({ ...cfg, token: '987654321:BBotherOTHERotherOTHERotherOTHER1234567' }, { ...other.d, statePath })
    expect(other.alerts.some((t) => t.includes('tokenje') && t.includes('megváltozott'))).toBe(true)
  })
  it('6: a webhook somebody set alerts; 4: an owner-id change alerts', async () => {
    const statePath = tmpState()
    const api = fakeApi({ getWebhookInfo: () => ({ body: { ok: true, result: { url: 'https://evil.example/hook' } } }) })
    const { alerts, d } = deps(api)
    await preflight(cfg, { ...d, statePath })
    expect(alerts.some((t) => t.includes('webhook'))).toBe(true)
    const a2 = deps(fakeApi())
    await preflight({ ...cfg, ownerId: '5555' }, { ...a2.d, statePath })
    expect(a2.alerts.some((t) => t.includes('megváltozott'))).toBe(true)
  })
  it('7: the token never reaches a log line or an error message', async () => {
    const boom: FetchLike = async () => { throw new Error(`connect ECONNREFUSED https://api.telegram.org/bot${TOKEN}/getUpdates`) }
    const { d } = deps()
    await pollOnce(cfg, { ...d, fetchImpl: boom, statePath: tmpState() })
    let err: unknown
    try { await tg(TOKEN, 'getMe', {}, 1000, boom) } catch (e) { err = e }
    expect(err).toBeInstanceOf(TgError)
    expect(String((err as Error).message)).not.toContain(TOKEN)
    expect(JSON.stringify(logged)).not.toContain(TOKEN)
    expect(JSON.stringify(logged)).not.toContain(TOKEN.split(':')[1])
  })
})
