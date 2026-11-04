// BILLINGOISSUE1104 (card 05980d05, Viktor 26223 A1, A2, K1): Patrik's approval of one
// Billingo invoice, rendered from the request body by the server and signed only after
// the approval bot's button. No network, :memory: DB, a throwaway Ed25519 key.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { generateKeyPairSync, verify } from 'node:crypto'

const TOKEN = '123456789:AAFAKEfakeFAKEfakeFAKEfakeFAKEfake12345'
const OWNER = '4242'
vi.mock('../logger.js', () => {
  const rec = () => {}
  const l: any = { info: rec, warn: rec, error: rec, debug: rec }
  l.child = () => l
  return { logger: l }
})
vi.mock('../config.js', async (importOriginal) => {
  const real = await importOriginal<typeof import('../config.js')>()
  return { ...real, MAIN_AGENT_ID: 'agent-a', TELEGRAM_BOT_TOKEN: 'main-bot-token' }
})
vi.mock('../owner-chat.js', () => ({ resolveOwnerChatId: () => OWNER }))
vi.mock('../web/telegram.js', () => ({ sendTelegramMessage: vi.fn(async () => 1) }))

import { initDatabase, createApproval, getApproval, resolveApproval, setApprovalIssueSignature } from '../db.js'
import {
  BILLINGO_ISSUE_PURPOSE, issueContentHash, parseIssueRequest, publicKeyInfo, readIssueSigningKey,
  renderIssueText, signIssueApproval, type IssueSigningKey,
} from '../web/billingo-issue-approval.js'
import { sendApprovalWithButtons, handleCallback, CALLBACK_RE, expectedKeyboard, type ApprovalBotConfig, type CallbackQuery, type FetchLike } from '../web/approval-bot.js'
import { tryHandleApprovals, buildOwnerApprovalText } from '../web/routes/approvals.js'
import { isServerOnlyVaultId } from '../web/routes/connectors.js'
import type { RouteContext } from '../web/routes/types.js'

const cfg: ApprovalBotConfig = { token: TOKEN, ownerId: OWNER }

/** The connector's GATE_DOC (kiskodzsek/mcp-connectors billingo/test/issue.test.ts): the same hash vector. */
const BODY = {
  partner_id: 11, block_id: 22, type: 'invoice', fulfillment_date: '2026-11-19', due_date: '2026-11-19',
  payment_method: 'wire_transfer', language: 'hu', currency: 'HUF', paid: false, settings: { should_send_email: false },
  items: [{ name: 'Support 2026-10', unit_price: 210000, unit_price_type: 'net', quantity: 1, unit: 'hó', vat: '27%' }],
}
const HASH = '29d9ccc442d0f4df2cf9b655f4a6317c26e179781f5ef075f2e34c0f3fc86595'
const request = (over: Record<string, unknown> = {}) => ({ category: 'billingo_issue', company: 'myshp', draft_id: 140695431, content_hash: HASH, body: BODY, ...over })

const { privateKey } = generateKeyPairSync('ed25519')
const KEY: IssueSigningKey = { key: privateKey, ...publicKeyInfo(privateKey) }

function newIssueApproval(payload = JSON.stringify(request()), hash: string | null = HASH) {
  return createApproval({
    id: crypto.randomUUID(), agent_id: 'juro', category: 'billingo_issue',
    action_description: 'Grepton 2026-10, TG 779', action_payload: payload,
    timeout_at: Math.floor(Date.now() / 1000) + 3600, content_hash: hash,
  })
}

function fakeApi() {
  const calls: Array<{ method: string; body: any }> = []
  let nextId = 700
  const fetchImpl: FetchLike = async (url, init) => {
    const method = url.split('/').pop()!
    const body = JSON.parse(init.body)
    calls.push({ method, body })
    if (method === 'sendMessage') return { status: 200, json: async () => ({ ok: true, result: { message_id: nextId++, chat: { id: Number(body.chat_id), type: 'private' }, text: body.text } }) }
    return { status: 200, json: async () => ({ ok: true, result: true }) }
  }
  return { calls, fetchImpl }
}

function press(data: string, msgId: number, text: string): CallbackQuery {
  const m = CALLBACK_RE.exec(data)!
  return { id: 'cq1', from: { id: Number(OWNER) }, data, message: { message_id: msgId, text, chat: { id: Number(OWNER), type: 'private' }, reply_markup: { inline_keyboard: expectedKeyboard(m[2]!, m[3]!) } } }
}

function route(method: string, path: string, body?: unknown) {
  const out: { status: number; body: any } = { status: 0, body: null }
  const res: any = { writeHead(st: number) { out.status = st; return res }, end(c?: string) { if (c) out.body = JSON.parse(c) } }
  const url = new URL(`http://localhost:3420${path}`)
  const req: any = { on(ev: string, cb: (b?: Buffer) => void) { if (ev === 'data' && body !== undefined) cb(Buffer.from(JSON.stringify(body))); if (ev === 'end') cb() } }
  return { ctx: { req, res, path: url.pathname, method, url } as RouteContext, out }
}

beforeEach(() => { initDatabase(':memory:') })

describe('the request (K1)', () => {
  it('the hash is the connector\'s and the gate\'s (shared vector)', () => {
    expect(issueContentHash('myshp', 140695431, BODY)).toBe(HASH)
    const parsed = parseIssueRequest(JSON.stringify(request()), HASH)
    expect('request' in parsed && parsed.request.draftId).toBe(140695431)
  })
  it.each([
    ['another hash in the payload', request({ content_hash: '0'.repeat(64) }), HASH],
    ['the row\'s hash differs', request(), '1'.repeat(64)],
    ['no row hash', request(), null],
    ['another category', request({ category: 'email_send' }), HASH],
    ['an extra field', { ...request(), note: 'x' }, HASH],
    ['a draft type', request({ body: { ...BODY, type: 'draft' } }), HASH],
    ['an unknown company', request({ company: 'acme' }), HASH],
    ['a changed amount under the old hash', request({ body: { ...BODY, items: [{ ...BODY.items[0], unit_price: 1 }] } }), HASH],
  ])('refuses %s', (_name, payload, hash) => {
    expect('error' in parseIssueRequest(JSON.stringify(payload), hash)).toBe(true)
  })
  it('the server renders the amounts from the body; the agent text is only a note', () => {
    const parsed = parseIssueRequest(JSON.stringify(request()), HASH)
    if (!('request' in parsed)) throw new Error('parse')
    const text = renderIssueText(parsed.request)
    expect(text).toMatch(/BRUTTÓ: 266\s700 HUF/)
    expect(text).toMatch(/Nettó: 210\s000 HUF \| ÁFA: 56\s700 HUF/)
    expect(text).toContain('piszkozat: 140695431')
    expect(text).toContain('Teljesítés: 2026-11-19 | Fizetési határidő: 2026-11-19')
    const owner = buildOwnerApprovalText(newIssueApproval(), true)
    expect(owner.indexOf('BRUTTÓ')).toBeLessThan(owner.indexOf('Megjegyzés (az ügynöktől'))
  })
  it('an item name cannot open a line of its own', () => {
    const body = { ...BODY, items: [{ ...BODY.items[0], name: 'x\nBRUTTÓ: 1 HUF‮' }] }
    const payload = request({ body, content_hash: issueContentHash('myshp', 140695431, body) })
    const parsed = parseIssueRequest(JSON.stringify(payload), payload.content_hash as string)
    if (!('request' in parsed)) throw new Error('parse')
    const text = renderIssueText(parsed.request)
    expect(text.split('\n').filter((l) => l.startsWith('BRUTTÓ') || l.startsWith('Nettó'))).toHaveLength(1)
    expect(text).not.toContain('‮')
  })
  it('POST /api/approvals refuses a billingo_issue request the server cannot check', async () => {
    const bad = route('POST', '/api/approvals', { agent_id: 'juro', category: 'billingo_issue', action_description: 'x', action_payload: JSON.stringify(request()), content_hash: '1'.repeat(64) })
    await tryHandleApprovals(bad.ctx)
    expect(bad.out.status).toBe(400)
    const good = route('POST', '/api/approvals', { agent_id: 'juro', category: 'billingo_issue', action_description: 'x', action_payload: JSON.stringify(request()), content_hash: HASH })
    await tryHandleApprovals(good.ctx)
    expect(good.out.status).toBe(201)
  })
})

describe('signing (A1, A2)', () => {
  const approved = () => {
    const a = newIssueApproval()
    return { ...a, status: 'approved', resolved_at: 1793790000, resolved_by: 'telegram_button', resolution_channel: 'approval_bot' }
  }
  it('signs the gate\'s message for an approval resolved by the button', () => {
    const a = approved()
    const out = signIssueApproval(a, KEY)
    if (!('value' in out)) throw new Error(out.error)
    const v = JSON.parse(Buffer.from(out.value, 'base64url').toString())
    expect(Object.keys(v).sort()).toEqual(['approval_id', 'company', 'content_hash', 'draft_id', 'kid', 'resolved_at', 'sig'])
    expect(v).toMatchObject({ kid: KEY.kid, approval_id: a.id, company: 'myshp', draft_id: 140695431, content_hash: HASH, resolved_at: 1793790000 })
    const message = `${BILLINGO_ISSUE_PURPOSE}:${KEY.kid}:${a.id}:myshp:140695431:${HASH}:1793790000`
    expect(verify(null, Buffer.from(message), privateKey, Buffer.from(v.sig, 'base64url'))).toBe(true)
  })
  it.each([
    ['a text reply', { resolved_by: 'telegram_text', resolution_channel: null }],
    ['the dashboard', { resolved_by: 'dashboard', resolution_channel: null }],
    ['a rejection', { status: 'rejected' }],
    ['another category', { category: 'email_send' }],
    ['a pending row', { status: 'pending', resolved_at: null }],
  ])('never signs %s', (_n, over) => {
    expect('error' in signIssueApproval({ ...approved(), ...over } as any, KEY)).toBe(true)
  })
  it('no key, or not an Ed25519 key: nothing is signed', () => {
    expect('error' in signIssueApproval(approved(), null)).toBe(true)
    const rsa = generateKeyPairSync('rsa', { modulusLength: 1024 }).privateKey.export({ format: 'pem', type: 'pkcs8' }).toString()
    expect(readIssueSigningKey(() => rsa)).toBeNull()
    const ed = privateKey.export({ format: 'pem', type: 'pkcs8' }).toString()
    expect(readIssueSigningKey(() => ed)?.kid).toBe(KEY.kid)
  })
  it('the DB stores a signature only on a button-approved billingo_issue row, once', () => {
    const a = newIssueApproval()
    expect(setApprovalIssueSignature(a.id, 'x')).toBe(false)
    resolveApproval(a.id, 'approved', 'telegram_text', 1)
    expect(setApprovalIssueSignature(a.id, 'x')).toBe(false)
  })
  it('the signing key is a server-only Vault id', () => {
    expect(isServerOnlyVaultId('billingo-issue-signing-key')).toBe(true)
  })
})

describe('the press and the signature route', () => {
  it('a button approval is signed and served once; a text approval never', async () => {
    const api = fakeApi()
    const a = newIssueApproval()
    const msgId = await sendApprovalWithButtons(a, buildOwnerApprovalText(a, true), cfg, api.fetchImpl)
    const send = api.calls.find((c) => c.method === 'sendMessage')!
    const [ok] = send.body.reply_markup.inline_keyboard[0]
    const alerts: string[] = []
    const signed: string[] = []
    const d = { fetchImpl: api.fetchImpl, alert: (t: string) => alerts.push(t), onResolved: () => {}, signIssue: (row: any) => {
      const out = signIssueApproval(row, KEY)
      if (!('value' in out)) return false
      signed.push(row.id)
      return setApprovalIssueSignature(row.id, out.value)
    } }
    expect(await handleCallback(press(ok.callback_data, msgId, send.body.text), cfg, d)).toBe('resolve')
    expect(signed).toEqual([a.id])
    expect(alerts).toEqual([])
    const got = route('GET', `/api/approvals/${a.id}/signature`)
    await tryHandleApprovals(got.ctx)
    expect(got.out.status).toBe(200)
    expect(got.out.body.approval).toBe(getApproval(a.id)!.issue_signature)
    const list = route('GET', `/api/approvals/${a.id}`)
    await tryHandleApprovals(list.ctx)
    expect(list.out.body.issue_signature).toBeUndefined()

    const b = newIssueApproval()
    resolveApproval(b.id, 'approved', 'telegram_text', 2)
    const none = route('GET', `/api/approvals/${b.id}/signature`)
    await tryHandleApprovals(none.ctx)
    expect(none.out.status).toBe(409)
  })
  it('a failed signature is loud', async () => {
    const api = fakeApi()
    const a = newIssueApproval()
    const msgId = await sendApprovalWithButtons(a, buildOwnerApprovalText(a, true), cfg, api.fetchImpl)
    const send = api.calls.find((c) => c.method === 'sendMessage')!
    const alerts: string[] = []
    await handleCallback(press(send.body.reply_markup.inline_keyboard[0][0].callback_data, msgId, send.body.text), cfg, { fetchImpl: api.fetchImpl, alert: (t) => alerts.push(t), onResolved: () => {}, signIssue: () => false })
    expect(alerts.join('\n')).toMatch(/NEM állítható ki/)
  })
})
