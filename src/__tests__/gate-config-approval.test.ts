// GATECONFIG1113 (Klodel 40642, Viktor 40668 C5/C6, negative tests 11-13 and 20): a gate config change approved
// with the owner's button. The server renders the full diff, refuses what it cannot render, and signs only a
// button approval; the signed envelope lands in the gate's inbox. No network, :memory: DB, a throwaway key,
// the gate's installed config and inbox in a temporary directory.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createHash, generateKeyPairSync, verify } from 'node:crypto'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, readdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

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

import { initDatabase, createApproval, getApproval, resolveApproval, setApprovalGateConfigSignature } from '../db.js'
import { canonicalJson, publicKeyInfo } from '../web/billingo-issue-approval.js'
import {
  GATES, GATE_CONFIG_PURPOSE, MAX_DIFF_CHARS, configDiff, gateConfigContentHash, parseGateConfigRequest,
  readGateConfigSigningKey, renderGateConfigText, signGateConfigApproval, writeGateConfigEnvelope, type GateConfigSigningKey,
} from '../web/gate-config-approval.js'
import { sendApprovalWithButtons, handleCallback, CALLBACK_RE, expectedKeyboard, type ApprovalBotConfig, type CallbackQuery, type FetchLike } from '../web/approval-bot.js'
import { tryHandleApprovals, buildOwnerApprovalText } from '../web/routes/approvals.js'
import { isServerOnlyVaultId } from '../web/server-only-secrets.js'
import type { RouteContext } from '../web/routes/types.js'

const cfg: ApprovalBotConfig = { token: TOKEN, ownerId: OWNER }
const sha256 = (b: string | Buffer) => createHash('sha256').update(b).digest('hex')
const { privateKey, publicKey } = generateKeyPairSync('ed25519')
const KEY: GateConfigSigningKey = { key: privateKey, ...publicKeyInfo(privateKey) }

const INSTALLED = {
  daily_cap: 400, ledger: '/usr/local/var/higgsfield/ledger.jsonl', upload_dir: ['/x/hf-input'],
  tools: { mcp__higgsfield__generate_video: { credits: 60, params: { prompt: { type: 'string', max_len: 4000 } }, urls: false } },
}
const NEW = { ...INSTALLED, daily_cap: null, tools: { mcp__higgsfield__generate_video: { ...INSTALLED.tools.mcp__higgsfield__generate_video, credits: 80 } } }

let dir = ''
const saved = { ...GATES.higgsfield! }
let prevSha = ''
beforeEach(() => {
  initDatabase(':memory:')
  dir = mkdtempSync(join(tmpdir(), 'gcfg-ts-'))
  mkdirSync(join(dir, 'inbox'))
  const bytes = canonicalJson(INSTALLED)
  writeFileSync(join(dir, 'config.json'), bytes)
  prevSha = sha256(bytes)
  GATES.higgsfield!.installed = join(dir, 'config.json')
  GATES.higgsfield!.inbox = join(dir, 'inbox')
})
afterEach(() => {
  Object.assign(GATES.higgsfield!, saved)
  rmSync(dir, { recursive: true, force: true })
})

const payload = (config: unknown = NEW, prev = prevSha) => JSON.stringify({ gate: 'higgsfield', prev_sha: prev, config })
const hashOf = (config: unknown = NEW, prev = prevSha) => gateConfigContentHash('higgsfield', prev, config)

function newGateApproval(config: unknown = NEW) {
  return createApproval({
    id: crypto.randomUUID(), agent_id: 'kernel', category: 'gate_config',
    action_description: 'AGENT NOTE: please approve, nothing important', action_payload: payload(config),
    timeout_at: Math.floor(Date.now() / 1000) + 3600, content_hash: hashOf(config),
  })
}

function route(method: string, path: string, body?: unknown) {
  const out: { status: number; body: any } = { status: 0, body: null }
  const res: any = { writeHead(st: number) { out.status = st; return res }, end(c?: string) { if (c) out.body = JSON.parse(c) } }
  const url = new URL(`http://localhost:3420${path}`)
  const req: any = { on(ev: string, cb: (b?: Buffer) => void) { if (ev === 'data' && body !== undefined) cb(Buffer.from(JSON.stringify(body))); if (ev === 'end') cb() } }
  return { ctx: { req, res, path: url.pathname, method, url } as RouteContext, out }
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

function press(data: string, msgId: number, text: string, from = OWNER): CallbackQuery {
  const m = CALLBACK_RE.exec(data)!
  return { id: 'cq1', from: { id: Number(from) }, data, message: { message_id: msgId, text, chat: { id: Number(OWNER), type: 'private' }, reply_markup: { inline_keyboard: expectedKeyboard(m[2]!, m[3]!) } } }
}

describe('request and diff (C6)', () => {
  it('the diff names every changed leaf', () => {
    expect(configDiff(INSTALLED, NEW)).toEqual([
      '~ daily_cap: 400 -> null',
      '~ tools.mcp__higgsfield__generate_video.credits: 60 -> 80',
    ])
    expect(configDiff({ a: { b: 1 } }, { a: { c: 2 } })).toEqual(['- a.b (volt: 1)', '+ a.c = 2'])
  })
  it('13 the button text is the server diff; the agent note is not in it', () => {
    const a = newGateApproval()
    const text = buildOwnerApprovalText(a, true)
    expect(text).toContain('~ tools.mcp__higgsfield__generate_video.credits: 60 -> 80')
    expect(text).toContain('~ daily_cap: 400 -> null')
    expect(text).not.toContain('AGENT NOTE')
  })
  it('POST stores a renderable request', async () => {
    const r = route('POST', '/api/approvals', { agent_id: 'kernel', category: 'gate_config', action_description: 'x', action_payload: payload(), content_hash: hashOf() })
    await tryHandleApprovals(r.ctx)
    expect(r.out.status).toBe(201)
  })
  it.each([
    ['a wrong content_hash', () => ({ action_payload: payload(), content_hash: '1'.repeat(64) })],
    ['a stale prev_sha (installed config changed)', () => ({ action_payload: payload(NEW, 'a'.repeat(64)), content_hash: hashOf(NEW, 'a'.repeat(64)) })],
    ['an unknown gate', () => {
      const p = JSON.stringify({ gate: 'billingo', prev_sha: prevSha, config: NEW })
      return { action_payload: p, content_hash: gateConfigContentHash('billingo', prevSha, NEW) }
    }],
    ['no change', () => ({ action_payload: payload(INSTALLED), content_hash: hashOf(INSTALLED) })],
    ['20 a diff too long for the button message', () => {
      const big = { ...NEW, upload_dir: Array.from({ length: 200 }, (_, i) => `/x/${'d'.repeat(20)}${i}/hf-input`) }
      return { action_payload: payload(big), content_hash: hashOf(big) }
    }],
  ])('POST refuses %s and stores nothing', async (_n, body) => {
    const r = route('POST', '/api/approvals', { agent_id: 'kernel', category: 'gate_config', action_description: 'x', ...body() })
    await tryHandleApprovals(r.ctx)
    expect(r.out.status).toBe(400)
    const list = route('GET', '/api/approvals?category=gate_config')
    await tryHandleApprovals(list.ctx)
    expect(list.out.body).toEqual([])
  })
  it('the length limit leaves room in a Telegram message', () => {
    expect(MAX_DIFF_CHARS).toBeLessThan(4096 - 200)
    const r = parseGateConfigRequest(payload(), hashOf())
    if (!('request' in r)) throw new Error(r.error)
    const t = renderGateConfigText(r.request)
    expect('text' in t && t.text.length <= MAX_DIFF_CHARS).toBe(true)
  })
})

describe('signing (C5): only the owner\'s button', () => {
  const approved = () => ({ ...newGateApproval(), status: 'approved', resolved_at: 1794590000, resolved_by: 'telegram_button', resolution_channel: 'approval_bot' })
  it('signs the daemon\'s message and builds a canonical envelope', () => {
    const a = approved()
    const out = signGateConfigApproval(a, KEY)
    if (!('envelope' in out)) throw new Error(out.error)
    const e = JSON.parse(out.envelope)
    expect(canonicalJson(e)).toBe(out.envelope)
    expect(Object.keys(e).sort()).toEqual(['approval_id', 'config', 'gate', 'kid', 'prev_sha', 'resolved_at', 'sig', 'v'])
    const msg = [GATE_CONFIG_PURPOSE, KEY.kid, a.id, 'higgsfield', prevSha, sha256(canonicalJson(NEW)), 1794590000].join(':')
    expect(verify(null, Buffer.from(msg), publicKey, Buffer.from(e.sig, 'base64url'))).toBe(true)
  })
  it.each([
    ['12 a text reply', { resolved_by: 'telegram_text', resolution_channel: null }],
    ['12 the dashboard', { resolved_by: 'dashboard', resolution_channel: null }],
    ['a rejection', { status: 'rejected' }],
    ['another category', { category: 'billingo_issue' }],
    ['a pending row', { status: 'pending', resolved_at: null }],
  ])('never signs %s', (_n, over) => {
    expect('error' in signGateConfigApproval({ ...approved(), ...over } as any, KEY)).toBe(true)
  })
  it('no key, or not an Ed25519 key: nothing is signed', () => {
    expect('error' in signGateConfigApproval(approved(), null)).toBe(true)
    const rsa = generateKeyPairSync('rsa', { modulusLength: 1024 }).privateKey.export({ format: 'pem', type: 'pkcs8' }).toString()
    expect(readGateConfigSigningKey(() => rsa)).toBeNull()
  })
  it('the DB stores the envelope only on a button-approved gate_config row, once', () => {
    const a = newGateApproval()
    expect(setApprovalGateConfigSignature(a.id, 'x')).toBe(false)
    resolveApproval(a.id, 'approved', 'telegram_text', 1)
    expect(setApprovalGateConfigSignature(a.id, 'x')).toBe(false)
  })
  it('the signing key is a server-only Vault id', () => {
    expect(isServerOnlyVaultId('gate-config-signing-key')).toBe(true)
  })
})

describe('the press', () => {
  async function sent() {
    const api = fakeApi()
    const a = newGateApproval()
    const msgId = await sendApprovalWithButtons(a, buildOwnerApprovalText(a, true), cfg, api.fetchImpl)
    const send = api.calls.find((c) => c.method === 'sendMessage')!
    return { api, a, msgId, send, ok: send.body.reply_markup.inline_keyboard[0][0] }
  }
  it('the owner\'s press signs, stores and writes the envelope into the inbox', async () => {
    const { api, a, msgId, send, ok } = await sent()
    const alerts: string[] = []
    const d = { fetchImpl: api.fetchImpl, alert: (t: string) => alerts.push(t), onResolved: () => {}, signGateConfig: (row: any) => {
      const out = signGateConfigApproval(row, KEY)
      if (!('envelope' in out)) return false
      if (!setApprovalGateConfigSignature(row.id, out.envelope)) return false
      writeGateConfigEnvelope(out.gate, row.id, out.envelope)
      return true
    } }
    expect(await handleCallback(press(ok.callback_data, msgId, send.body.text), cfg, d)).toBe('resolve')
    expect(alerts).toEqual([])
    expect(readdirSync(join(dir, 'inbox'))).toEqual([`${a.id}.json`])
    expect(readFileSync(join(dir, 'inbox', `${a.id}.json`), 'utf8')).toBe(getApproval(a.id)!.issue_signature)
  })
  it('11 a non-owner press resolves nothing and signs nothing', async () => {
    const { api, a, msgId, send, ok } = await sent()
    let called = 0
    const d = { fetchImpl: api.fetchImpl, alert: () => {}, onResolved: () => {}, signGateConfig: () => { called++; return true } }
    expect(await handleCallback(press(ok.callback_data, msgId, send.body.text, '9999'), cfg, d)).not.toBe('resolve')
    expect(called).toBe(0)
    expect(getApproval(a.id)!.status).toBe('pending')
    expect(readdirSync(join(dir, 'inbox'))).toEqual([])
  })
  it('a failed signature or handover is loud', async () => {
    const { api, msgId, send, ok } = await sent()
    const alerts: string[] = []
    await handleCallback(press(ok.callback_data, msgId, send.body.text), cfg, { fetchImpl: api.fetchImpl, alert: (t) => alerts.push(t), onResolved: () => {}, signGateConfig: () => false })
    expect(alerts.join('\n')).toMatch(/NEM változik/)
  })
  it('the inbox write never overwrites an envelope', () => {
    writeGateConfigEnvelope('higgsfield', 'abcdefgh-1', '{"a":1}')
    expect(() => writeGateConfigEnvelope('higgsfield', 'abcdefgh-1', '{"a":2}')).toThrow()
    expect(readFileSync(join(dir, 'inbox', 'abcdefgh-1.json'), 'utf8')).toBe('{"a":1}')
    expect(readdirSync(join(dir, 'inbox')).filter((n) => n.startsWith('.'))).toEqual([])
  })
})
