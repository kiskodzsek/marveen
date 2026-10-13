// APPROVALBOT1013 (Patrik, Telegram 1623/1653; plan reviewed by Viktor, msg 2302):
// one-tap approvals from the phone, without the main agent in the loop.
//
// A DEDICATED Telegram bot, polled by the dashboard alone, sends every approval
// request to the owner with two buttons. A press is resolved by THIS process,
// never through the fleet-token PATCH route. The main bot cannot be used: its
// updates belong to the native channel plugin (the sole poller; a second
// getUpdates there is a 409), and the plugin drops every callback but perm:.
//
// What a press must prove before anything is resolved (Viktor 2302, 1-8):
//   - it came from the explicitly configured owner (APPROVAL_OWNER_TELEGRAM_ID),
//     in a private chat with that owner. No fallback to "the first paired id";
//   - it sits on the very message the server sent (bot_message_id/bot_chat_id
//     on the row) and that message's text is unchanged (bot_text_hash). Both
//     columns are server-only, so a token holder who sends a look-alike message,
//     or edits ours into something harmless, cannot get a real press counted;
//   - it carries the 128-bit one-time nonce, compared by hash in constant time,
//     cleared on first use, on any resolution and on timeout;
//   - the request is still pending and not expired.
// Anything else is refused. A non-owner press and a binding mismatch alert the
// owner; a 409 or a set webhook (someone else consuming the updates) alerts too.
//
// What this does NOT stop, stated so nobody reads more into it: an agent that
// can write the dashboard code, the Vault or .env on the same UID. That needs
// the isolated, TOTP-backed approval of 9a2925a7 step 2.
//
// Off unless configured: the Vault entry (APPROVAL_BOT_VAULT_ID, default
// telegram-approval-bot) and APPROVAL_OWNER_TELEGRAM_ID in .env. Without them
// approvals keep going out through the main bot, exactly as before.

import { createHash, randomBytes, timingSafeEqual } from 'node:crypto'
import { closeSync, constants, openSync, readFileSync, renameSync, writeSync } from 'node:fs'
import { join } from 'node:path'
import { STORE_DIR } from '../config.js'
import { readEnvFile } from '../env.js'
import { logger } from '../logger.js'
import { getApproval, resolveApprovalByBot, setApprovalBotMessage, type Approval } from '../db.js'
import { getSecret } from './vault.js'
import { markIfTestRun } from '../test-run-marker.js'

export const APPROVAL_BOT_DEFAULT_VAULT_ID = 'telegram-approval-bot'
const OWNER_ID_RE = /^[1-9]\d{2,19}$/
const VAULT_ID_RE = /^[a-z0-9][a-z0-9_.-]{0,63}$/
const BOT_TOKEN_RE = /^\d{5,15}:[A-Za-z0-9_-]{30,64}$/
// a:<o|n>:<approval uuid>:<22-char base64url nonce> -> 63 bytes, under Telegram's 64.
export const CALLBACK_RE = /^a:([on]):([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):([A-Za-z0-9_-]{22})$/
const API = 'https://api.telegram.org'
const SEND_TIMEOUT_MS = 10_000
const POLL_TIMEOUT_S = 25
const STATE_FILE = 'approval-bot-state.json'

export interface ApprovalBotConfig {
  token: string
  ownerId: string
}

export interface ConfigDeps {
  env?: (keys: string[]) => Record<string, string>
  secret?: (id: string) => string | null
}

/** null when the feature is off or misconfigured (logged, never the token). */
export function readApprovalBotConfig(deps: ConfigDeps = {}): ApprovalBotConfig | null {
  const env = (deps.env ?? readEnvFile)(['APPROVAL_BOT_VAULT_ID', 'APPROVAL_OWNER_TELEGRAM_ID'])
  const ownerId = (env['APPROVAL_OWNER_TELEGRAM_ID'] ?? '').trim()
  const vaultId = (env['APPROVAL_BOT_VAULT_ID'] ?? '').trim() || APPROVAL_BOT_DEFAULT_VAULT_ID
  if (!ownerId) return null
  if (!OWNER_ID_RE.test(ownerId) || !VAULT_ID_RE.test(vaultId)) {
    logger.warn('approval bot: APPROVAL_OWNER_TELEGRAM_ID or APPROVAL_BOT_VAULT_ID malformed, the bot stays off')
    return null
  }
  let token: string | null = null
  try { token = (deps.secret ?? getSecret)(vaultId) } catch { token = null }
  token = (token ?? '').trim()
  if (!BOT_TOKEN_RE.test(token)) {
    if (token) logger.warn({ vaultId }, 'approval bot: the Vault entry does not look like a bot token, the bot stays off')
    return null
  }
  return { token, ownerId }
}

export function sha256Hex(text: string): string {
  return createHash('sha256').update(text, 'utf8').digest('hex')
}

function hashEqual(aHex: string, bHex: string): boolean {
  const a = Buffer.from(aHex, 'hex')
  const b = Buffer.from(bHex, 'hex')
  return a.length === 32 && b.length === 32 && timingSafeEqual(a, b)
}

// ---------------------------------------------------------------- Telegram client

export type FetchLike = (url: string, init: { method: string; headers: Record<string, string>; body: string; signal: AbortSignal }) => Promise<{ status: number; json: () => Promise<unknown> }>

/** A Bot API failure. Carries the HTTP status and Telegram's error_code ONLY:
 *  the request URL holds the token, so neither it nor a raw body is kept. */
export class TgError extends Error {
  constructor(readonly status: number, readonly code: number | null, readonly kind: 'http' | 'network') {
    super(`telegram ${kind} ${status}${code != null ? `/${code}` : ''}`)
  }
}

export async function tg<T>(token: string, method: string, body: Record<string, unknown>, timeoutMs: number, fetchImpl: FetchLike = fetch as unknown as FetchLike): Promise<T> {
  let resp: { status: number; json: () => Promise<unknown> }
  try {
    resp = await fetchImpl(`${API}/bot${token}/${method}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(timeoutMs),
    })
  } catch {
    throw new TgError(0, null, 'network')            // never the error text: it may echo the URL
  }
  type ApiBody = { ok?: boolean; error_code?: number; result?: unknown }
  let data: ApiBody | null
  try { data = await resp.json() as ApiBody } catch { data = null }
  if (resp.status !== 200 || !data || data.ok !== true) {
    throw new TgError(resp.status, typeof data?.error_code === 'number' ? data.error_code : null, 'http')
  }
  return data.result as T
}

// ---------------------------------------------------------------- sending

interface SentMessage { message_id: number; chat: { id: number }; text?: string }

/** Send the request with two buttons; stamp the binding onto the row. Returns
 *  the message id, or throws (the caller falls back to the main bot). */
export async function sendApprovalWithButtons(approval: Approval, text: string, cfg: ApprovalBotConfig, fetchImpl?: FetchLike): Promise<number> {
  const nonce = randomBytes(16).toString('base64url')
  const data = (k: 'o' | 'n') => `a:${k}:${approval.id}:${nonce}`
  const msg = await tg<SentMessage>(cfg.token, 'sendMessage', {
    chat_id: cfg.ownerId,
    text: markIfTestRun(text),
    reply_markup: { inline_keyboard: [[
      { text: '✅ Jóváhagyom', callback_data: data('o') },
      { text: '❌ Elutasítom', callback_data: data('n') },
    ]] },
  }, SEND_TIMEOUT_MS, fetchImpl)
  if (typeof msg?.message_id !== 'number' || typeof msg.text !== 'string') throw new TgError(200, null, 'http')
  // The hash is over the text AS TELEGRAM STORED IT: that is what a callback
  // carries back, whatever normalisation Telegram applied on the way in.
  if (!setApprovalBotMessage(approval.id, msg.message_id, String(msg.chat?.id ?? ''), sha256Hex(msg.text), sha256Hex(nonce))) {
    throw new TgError(200, null, 'http')             // the row resolved meanwhile: the buttons must not stand
  }
  return msg.message_id
}

// ---------------------------------------------------------------- deciding a press

export interface CallbackQuery {
  id: string
  from?: { id?: number }
  data?: string
  message?: { message_id?: number; text?: string; chat?: { id?: number; type?: string } }
}

export type CallbackOutcome =
  | { kind: 'ignore' }
  | { kind: 'not_owner' }
  | { kind: 'mismatch'; reason: 'unknown_request' | 'message' | 'text' | 'nonce' }
  | { kind: 'closed'; approval: Approval }
  | { kind: 'resolve'; approval: Approval; status: 'approved' | 'rejected'; nonceHash: string }

/** Pure: everything a press must prove, in order. */
export function decideCallback(cq: CallbackQuery, cfg: ApprovalBotConfig, lookup: (id: string) => Approval | undefined, now: number = Math.floor(Date.now() / 1000)): CallbackOutcome {
  const m = CALLBACK_RE.exec(String(cq.data ?? ''))
  if (!m) return { kind: 'ignore' }
  const chat = cq.message?.chat
  if (String(cq.from?.id ?? '') !== cfg.ownerId || String(chat?.id ?? '') !== cfg.ownerId || chat?.type !== 'private') {
    return { kind: 'not_owner' }
  }
  const [, verb, id, nonce] = m
  const approval = lookup(id!)
  if (!approval || approval.bot_message_id == null) return { kind: 'mismatch', reason: 'unknown_request' }
  if (cq.message?.message_id !== approval.bot_message_id || String(chat?.id) !== String(approval.bot_chat_id ?? '')) {
    return { kind: 'mismatch', reason: 'message' }
  }
  if (typeof cq.message?.text !== 'string' || !approval.bot_text_hash || !hashEqual(sha256Hex(cq.message.text), approval.bot_text_hash)) {
    return { kind: 'mismatch', reason: 'text' }
  }
  if (approval.status !== 'pending' || (approval.timeout_at != null && approval.timeout_at <= now)) {
    return { kind: 'closed', approval }
  }
  const nonceHash = sha256Hex(nonce!)
  if (!approval.bot_nonce_hash || !hashEqual(nonceHash, approval.bot_nonce_hash)) return { kind: 'mismatch', reason: 'nonce' }
  return { kind: 'resolve', approval, status: verb === 'o' ? 'approved' : 'rejected', nonceHash }
}

// ---------------------------------------------------------------- acting on a press

export interface HandlerDeps {
  fetchImpl?: FetchLike
  /** owner alert through the MAIN bot (the 9a2925a7 path) */
  alert: (text: string) => void
  /** called after a verified bot resolution (owner resolution alert, channel=approval_bot) */
  onResolved: (approval: Approval) => void
  lookup?: (id: string) => Approval | undefined
  resolve?: typeof resolveApprovalByBot
  now?: () => number
}

const notOwnerCount = { n: 0, windowStart: 0 }

function fmtTime(sec: number): string {
  return new Date(sec * 1000).toLocaleTimeString('hu-HU', { timeZone: 'Europe/Budapest', hour: '2-digit', minute: '2-digit' })
}

export async function handleCallback(cq: CallbackQuery, cfg: ApprovalBotConfig, deps: HandlerDeps): Promise<CallbackOutcome['kind']> {
  const now = (deps.now ?? (() => Math.floor(Date.now() / 1000)))()
  const outcome = decideCallback(cq, cfg, deps.lookup ?? getApproval, now)
  const answer = (text?: string) => tg(cfg.token, 'answerCallbackQuery', text ? { callback_query_id: cq.id, text } : { callback_query_id: cq.id }, SEND_TIMEOUT_MS, deps.fetchImpl).catch(() => {})
  const closeButtons = (approval: Approval, suffix: string) => tg(cfg.token, 'editMessageText', {
    chat_id: approval.bot_chat_id, message_id: approval.bot_message_id,
    text: `${cq.message?.text ?? ''}\n\n${suffix}`, reply_markup: { inline_keyboard: [] },
  }, SEND_TIMEOUT_MS, deps.fetchImpl).catch(() => {})

  switch (outcome.kind) {
    case 'ignore':
      await answer()
      break
    case 'not_owner': {
      await answer('Nem jogosult.')
      // Counted, so a flood does not become a flood of alerts: the 1st, then every 10th per hour.
      if (now - notOwnerCount.windowStart > 3600) { notOwnerCount.windowStart = now; notOwnerCount.n = 0 }
      notOwnerCount.n++
      if (notOwnerCount.n === 1 || notOwnerCount.n % 10 === 0) {
        deps.alert(`⚠️ Jóváhagyó bot: nem a tulajdonos nyomott gombot (${notOwnerCount.n}. az elmúlt órában). Elutasítva.`)
      }
      logger.warn({ count: notOwnerCount.n }, 'approval bot: press from a non-owner refused')
      break
    }
    case 'mismatch': {
      await answer('Elutasítva: ez a gomb nem érvényes.')
      const what = { unknown_request: 'ismeretlen kérés', message: 'nem a szerver által küldött üzenet', text: 'az üzenet szövege megváltozott', nonce: 'érvénytelen vagy elhasznált gomb' }[outcome.reason]
      deps.alert(`⚠️ Jóváhagyó bot: gyanús gombnyomás elutasítva (${what}). Ha nem te voltál, vagy a szöveg nem az, amit küldtünk, szólj.`)
      logger.warn({ reason: outcome.reason }, 'approval bot: press refused, binding mismatch')
      break
    }
    case 'closed':
      await answer('Ez a kérés már le van zárva.')
      await closeButtons(outcome.approval, `Lezárva: ${outcome.approval.status}`)
      break
    case 'resolve': {
      const ok = (deps.resolve ?? resolveApprovalByBot)(outcome.approval.id, outcome.status, outcome.nonceHash, now)
      if (!ok) {
        await answer('Ez a kérés már le van zárva.')
        break
      }
      const label = outcome.status === 'approved' ? `✅ Jóváhagyva ${fmtTime(now)}` : `❌ Elutasítva ${fmtTime(now)}`
      await answer(label)
      await closeButtons(outcome.approval, label)
      const fresh = (deps.lookup ?? getApproval)(outcome.approval.id)
      if (fresh) deps.onResolved(fresh)
      logger.info({ approvalId: outcome.approval.id, status: outcome.status }, 'approval resolved by the approval bot')
      break
    }
  }
  return outcome.kind
}

// ---------------------------------------------------------------- polling

interface PollState { offset: number; owner_hash: string | null }

function statePath(): string { return join(STORE_DIR, STATE_FILE) }

export function readPollState(path: string = statePath()): PollState {
  try {
    const d = JSON.parse(readFileSync(path, 'utf8')) as Partial<PollState>
    return { offset: Number.isInteger(d.offset) ? d.offset! : 0, owner_hash: typeof d.owner_hash === 'string' ? d.owner_hash : null }
  } catch {
    return { offset: 0, owner_hash: null }
  }
}

export function writePollState(state: PollState, path: string = statePath()): void {
  const tmp = `${path}.${process.pid}.tmp`
  const fd = openSync(tmp, constants.O_WRONLY | constants.O_CREAT | constants.O_TRUNC | constants.O_NOFOLLOW, 0o600)
  try { writeSync(fd, JSON.stringify(state)) } finally { closeSync(fd) }
  renameSync(tmp, path)
}

interface Update { update_id: number; callback_query?: CallbackQuery }

export interface PollDeps extends HandlerDeps {
  statePath?: string
  sleep?: (ms: number) => Promise<void>
}

const lastAlert: Record<string, number> = {}
function alertOnce(deps: PollDeps, key: string, text: string, everySec = 3600): void {
  const now = Math.floor(Date.now() / 1000)
  if ((lastAlert[key] ?? 0) + everySec > now) return
  lastAlert[key] = now
  deps.alert(text)
}

/** Startup checks: owner-id change, a webhook somebody set. */
export async function preflight(cfg: ApprovalBotConfig, deps: PollDeps): Promise<void> {
  const state = readPollState(deps.statePath)
  const ownerHash = sha256Hex(cfg.ownerId)
  if (state.owner_hash && state.owner_hash !== ownerHash) {
    deps.alert('⚠️ Jóváhagyó bot: a tulajdonos Telegram-azonosítója (APPROVAL_OWNER_TELEGRAM_ID) megváltozott. Ha nem te állítottad át, szólj azonnal.')
  }
  if (state.owner_hash !== ownerHash) writePollState({ ...state, owner_hash: ownerHash }, deps.statePath)
  try {
    const info = await tg<{ url?: string }>(cfg.token, 'getWebhookInfo', {}, SEND_TIMEOUT_MS, deps.fetchImpl)
    if (info?.url) alertOnce(deps, 'webhook', '⚠️ Jóváhagyó bot: webhook van beállítva, a gombnyomások máshová mehetnek. A dashboard nem kapja meg őket.')
  } catch (err) {
    logger.warn({ status: (err as TgError).status, code: (err as TgError).code }, 'approval bot: getWebhookInfo failed')
  }
}

/** One long-poll round. Returns the ms to wait before the next one. */
export async function pollOnce(cfg: ApprovalBotConfig, deps: PollDeps): Promise<number> {
  const state = readPollState(deps.statePath)
  let updates: Update[]
  try {
    updates = await tg<Update[]>(cfg.token, 'getUpdates', {
      offset: state.offset, timeout: POLL_TIMEOUT_S, allowed_updates: ['callback_query'],
    }, (POLL_TIMEOUT_S + 10) * 1000, deps.fetchImpl)
  } catch (err) {
    const e = err as TgError
    if (e.status === 409 || e.code === 409) {
      alertOnce(deps, 'conflict', '⚠️ Jóváhagyó bot: valaki más is lekéri a bot frissítéseit (409). A gombok így nem érnek ide; ha nem tudsz róla, szólj.')
      return 30_000
    }
    if (e.status === 401 || e.code === 401) {
      alertOnce(deps, 'unauthorized', '⚠️ Jóváhagyó bot: a token érvénytelen (401). A jóváhagyások a régi úton mennek tovább.')
      return 300_000
    }
    logger.warn({ status: e.status, code: e.code, kind: e.kind }, 'approval bot: getUpdates failed')
    return 5_000
  }
  for (const u of Array.isArray(updates) ? updates : []) {
    if (!Number.isInteger(u?.update_id)) continue
    writePollState({ ...readPollState(deps.statePath), offset: u.update_id + 1 }, deps.statePath)
    if (u.callback_query) {
      try { await handleCallback(u.callback_query, cfg, deps) } catch (err) {
        logger.warn({ name: (err as Error)?.name }, 'approval bot: callback handling failed')
      }
    }
  }
  return 0
}

/** The background loop. Re-reads the config each round, so setting or removing
 *  the Vault entry / owner id takes effect without a restart. */
export function startApprovalBotPoller(deps: PollDeps): { stop: () => void } {
  let stopped = false
  const sleep = deps.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms).unref?.()))
  void (async () => {
    let checkedFor: string | null = null
    while (!stopped) {
      const cfg = readApprovalBotConfig()
      if (!cfg) { checkedFor = null; await sleep(60_000); continue }
      const key = sha256Hex(`${cfg.ownerId}\u0000${cfg.token}`)   // never the token itself
      if (checkedFor !== key) {
        await preflight(cfg, deps)
        checkedFor = key
      }
      const wait = await pollOnce(cfg, deps)
      if (wait > 0) await sleep(wait)
    }
  })()
  return { stop: () => { stopped = true } }
}
