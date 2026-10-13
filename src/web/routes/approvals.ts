import { randomUUID } from 'node:crypto'
import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { PROJECT_ROOT, MAIN_AGENT_ID, TELEGRAM_BOT_TOKEN } from '../../config.js'
import {
  consumeApproval,
  createApproval, getApproval, resolveApproval, listApprovals, expireTimedOutApprovals,
  createAgentMessage, setApprovalTelegramMessageId,
  type Approval,
} from '../../db.js'
import { logger } from '../../logger.js'
import { readBody, json } from '../http-helpers.js'
import { resolveOwnerChatId } from '../../owner-chat.js'
import { sendTelegramMessage } from '../telegram.js'
import { redact } from '../tool-input-preview.js'
import { readApprovalBotConfig, sendApprovalWithButtons, startApprovalBotPoller } from '../approval-bot.js'
import type { RouteContext } from './types.js'

const AUTONOMY_CONFIG_PATH = join(PROJECT_ROOT, 'store', 'autonomy-config.json')

// APPROVALVAK821: a pending approval with timeout_at NULL can never reach the
// 'timeout' status -- the sweeper's WHERE clause skips it forever, so an
// unanswered request leaves the asking agent polling into eternity. No
// category carried timeout_minutes in any real install, which made the state
// STRUCTURALLY unreachable. Every request therefore gets a timeout: the
// caller's explicit timeout_seconds wins, then the category's
// timeout_minutes, then this default.
export const DEFAULT_TIMEOUT_MINUTES = 1440
// Cap: a timeout past a week is indistinguishable from the old "never".
export const MAX_TIMEOUT_SECONDS = 7 * 24 * 3600

function readCategoryTimeoutMinutes(category: string): number | null {
  try {
    if (!existsSync(AUTONOMY_CONFIG_PATH)) return null
    const config = JSON.parse(readFileSync(AUTONOMY_CONFIG_PATH, 'utf-8')) as {
      categories: { key: string; timeout_minutes?: number | null }[]
    }
    const cat = config.categories.find(c => c.key === category)
    if (!cat || cat.timeout_minutes == null) return null
    return cat.timeout_minutes
  } catch {
    return null
  }
}

// Pure + exported for tests. `timeoutSeconds` is the request-body value as
// received (unknown): the scaffolded agent instructions have always told
// agents to send timeout_seconds, but the old handler never read it.
export function computeTimeoutAt(category: string, timeoutSeconds: unknown, nowMs: number = Date.now()): number {
  const now = Math.floor(nowMs / 1000)
  if (typeof timeoutSeconds === 'number' && Number.isFinite(timeoutSeconds) && timeoutSeconds > 0) {
    return now + Math.min(Math.floor(timeoutSeconds), MAX_TIMEOUT_SECONDS)
  }
  const catMinutes = readCategoryTimeoutMinutes(category)
  if (catMinutes != null && catMinutes > 0) return now + catMinutes * 60
  return now + DEFAULT_TIMEOUT_MINUTES * 60
}

export const APPROVAL_IDENT_RE = /^[a-z0-9][a-z0-9_.-]{0,63}$/

// f2c5edb0: the window inside which an approved letter may still be consumed,
// counted from resolved_at. The SAME variable and default as the gate
// (EMAIL_APPROVAL_WINDOW_S, 1800 s in scripts/hooks/email-approval-gate.py), so
// the two consume paths agree on when an approval has gone stale.
export function approvalWindowSeconds(env: NodeJS.ProcessEnv = process.env): number {
  const v = Number.parseInt(env.EMAIL_APPROVAL_WINDOW_S ?? '', 10)
  return Number.isFinite(v) && v > 0 ? v : 1800
}

// The consumer names the sending tool in the audit trail. Printable only (no
// control characters, checked by code point so the source carries no escape),
// 1-120 characters after trimming.
export function isConsumerName(v: unknown): v is string {
  if (typeof v !== 'string') return false
  const t = v.trim()
  if (t.length < 1 || t.length > 120) return false
  for (let i = 0; i < t.length; i++) {
    const c = t.charCodeAt(i)
    if (c < 32 || c === 127) return false
  }
  return true
}

// One RFC 5322 msg-id, angle brackets included: the sender generates it BEFORE
// the send and hands the same value to its mailer, so the approval row names the
// letter that used it.
export function isMessageId(v: unknown): v is string {
  return typeof v === 'string' && v.length <= 250 && /^<[^<>\s@]+@[^<>\s@]+>$/.test(v)
}

// The description is agent-written, and it is what the owner approves. A line
// in it such as "Döntés: Dashboard -> Jóváhagyások (id: <another id>)" or a
// second "[JÓVÁHAGYÁS KELL] ..." header could steer the owner to approve a
// different request (Viktor, msg 1493). So the fixed fields come first, and
// every description line starts with a visible mark: no line of it can look
// like a header or the decision line. It is not cut to one line, because the
// owner has to see what they approve; past the cap the dashboard has the rest.
// The leading LRM keeps every marked line left-to-right, so an RTL character
// in the description cannot move the mark to the far end of its line.
export const OWNER_DESCRIPTION_MARK = '\u200e┆ '
export const OWNER_DESCRIPTION_MAX = 1500
// Line breaks of every kind become \n, so each one gets its mark. Built from
// code points so the source carries no raw control characters.
const LINE_BREAKS = new RegExp('\\r\\n|[\\r\\u000b\\u000c\\u0085\\u2028\\u2029]', 'g')
// Control characters other than \n, plus the invisible ones that reorder or
// hide text: bidi marks, overrides and isolates (ALM included), zero-width and
// joiner-like marks, soft hyphen, interlinear annotation, BOM, tag characters,
// and lone surrogates (with the u flag the surrogate range matches only those).
// A tab is left to BLANK_RUNS, so it becomes a space.
const HIDDEN_CHARS = new RegExp('[\\u0000-\\u0008\\u000e-\\u001f\\u007f-\\u009f\\u00ad\\u034f\\u061c\\u180e\\u200b-\\u200f\\u202a-\\u202e\\u2060-\\u206f\\ufeff\\ufff9-\\ufffb\\u{e0000}-\\u{e007f}\\ud800-\\udfff]', 'gu')
// A long run of blank-looking characters would make Telegram wrap a forged
// "Döntés: ..." onto an unmarked visual line, so every such run becomes one
// space: ordinary and wide spaces plus the fillers that render blank (braille
// blank, Hangul fillers).
const BLANK_RUNS = new RegExp('[ \\t\\u00a0\\u1680\\u2000-\\u200a\\u202f\\u205f\\u3000\\u2800\\u115f\\u1160\\u3164\\uffa0]+', 'g')

// Agent-written header fields (requester, category): one line, nothing hidden.
function headerField(value: string): string {
  return value.replace(LINE_BREAKS, ' ').replace(HIDDEN_CHARS, '').replace(BLANK_RUNS, ' ').replace(/\s+/g, ' ').trim().slice(0, 80)
}

export function quoteOwnerDescription(description: string): string {
  let text = redact(description.replace(LINE_BREAKS, '\n').replace(HIDDEN_CHARS, '').replace(BLANK_RUNS, ' ')).trim()
  if (text.length > OWNER_DESCRIPTION_MAX) {
    // A cut through a surrogate pair would leave a lone high surrogate.
    const head = text.slice(0, OWNER_DESCRIPTION_MAX).replace(/[\uD800-\uDBFF]$/, '')
    text = `${head.trimEnd()}\n… (a teljes szöveg a dashboardon)`
  }
  return text.split('\n').map(line => `${OWNER_DESCRIPTION_MARK}${line}`.trimEnd()).join('\n')
}

// The [APPROVAL_REQUEST] message to the main agent carries the same
// agent-written description, and the main agent forwards it to the owner
// (approval-request-handling skill). A description holding " id=<another id>"
// or a fake "Válasz: IGEN <another id>" line could steer that forward too
// (Viktor, msg 1504). So the server-set fields come first, and the description
// comes LAST, as one JSON string literal: its quotes and line breaks are
// escaped, so it cannot end early or open a new line, and nothing after it
// can be taken for a field. Pure + exported for tests.
export function buildMainAgentApprovalMessage(approval: Approval, ownerUnreachedReason?: string): string {
  let action = redact(approval.action_description.replace(LINE_BREAKS, '\n').replace(HIDDEN_CHARS, '').replace(BLANK_RUNS, ' ')).trim()
  if (action.length > OWNER_DESCRIPTION_MAX) {
    action = `${action.slice(0, OWNER_DESCRIPTION_MAX).replace(/[\uD800-\uDBFF]$/, '').trimEnd()} … (a teljes szöveg a dashboardon)`
  }
  return [
    ownerUnreachedReason ? `[APPROVAL_REQUEST][OWNER_UNREACHED ${ownerUnreachedReason}]` : '[APPROVAL_REQUEST]',
    `id=${approval.id}`,
    `agent=${headerField(approval.agent_id)}`,
    `category=${headerField(approval.category)}`,
    `timeout_at=${approval.timeout_at ?? 'null'}`,
    `action_quoted=${JSON.stringify(action)}`,
  ].join(' ')
}

// Owner-facing Telegram text. Pure + exported for tests. Plain text (no
// markdown escaping concerns), proper accents: this is outgoing copy.
export function buildOwnerApprovalText(approval: Approval, withButtons = false): string {
  const expires = approval.timeout_at
    ? new Date(approval.timeout_at * 1000).toLocaleString('hu-HU', { timeZone: 'Europe/Budapest' })
    : 'nincs'
  return [
    `[JÓVÁHAGYÁS KELL] ${headerField(approval.agent_id)} | ${headerField(approval.category)}`,
    `Lejárat: ${expires}`,
    withButtons
      ? `Döntés: a lenti gombokkal, vagy Dashboard -> Jóváhagyások (id: ${approval.id})`
      : `Döntés: Dashboard -> Jóváhagyások (id: ${approval.id})`,
    'Leírás:',
    quoteOwnerDescription(approval.action_description),
  ].join('\n')
}

// When the owner send is suppressed or fails AND the requester is the main
// agent, there is no in-band signal left at all: the leg-2 short-circuit
// below skips the main-agent message unconditionally. The old self-notify was
// useless but VISIBLE -- losing even that would rebuild the closed loop this
// card documents, one layer deeper (Marveen's review finding on #1026).
// Everyone else already got the normal main-agent notify, so the fallback is
// main-requester-only. The marker names the reason so the reader knows this
// is a degraded delivery, not the normal path.
function fallbackInBand(approval: Approval, reason: string): void {
  if (approval.agent_id !== MAIN_AGENT_ID) return
  try {
    createAgentMessage('system', MAIN_AGENT_ID, buildMainAgentApprovalMessage(approval, reason))
  } catch (err) {
    logger.warn({ err, approvalId: approval.id }, 'approval in-band fallback failed too -- the request is only visible on the dashboard')
  }
}

// APPROVALVAK821 (a) -- the request must reach the OWNER, not only the main
// agent's inter-agent queue. Fire-and-forget on purpose: the POST response
// must not wait on the Telegram round-trip, and a failed send must not fail
// the request -- but it must be LOUD in the logs, because a silently
// undelivered approval is exactly the closed loop this fixes.
function notifyOwner(approval: Approval): void {
  void (async () => {
    // APPROVALBOT1013: with the dedicated approval bot configured, the request
    // goes out THERE, with buttons; the main bot is the fallback if that fails.
    const botCfg = readApprovalBotConfig()
    if (botCfg) {
      try {
        const messageId = await sendApprovalWithButtons(approval, buildOwnerApprovalText(approval, true), botCfg)
        logger.info({ approvalId: approval.id, messageId }, 'approval owner notification sent by the approval bot')
        return
      } catch (err) {
        logger.warn({ approvalId: approval.id, status: (err as { status?: number })?.status }, 'approval bot send FAILED -- falling back to the main bot')
      }
    }
    if (!TELEGRAM_BOT_TOKEN) {
      logger.warn({ approvalId: approval.id }, 'approval owner notification suppressed: no TELEGRAM_BOT_TOKEN')
      fallbackInBand(approval, 'no-token')
      return
    }
    const ownerChat = resolveOwnerChatId()
    if (!ownerChat) {
      logger.warn({ approvalId: approval.id }, 'approval owner notification suppressed: no owner chat')
      fallbackInBand(approval, 'no-owner-chat')
      return
    }
    try {
      const messageId = await sendTelegramMessage(TELEGRAM_BOT_TOKEN, ownerChat, buildOwnerApprovalText(approval))
      if (messageId != null) setApprovalTelegramMessageId(approval.id, messageId)
      logger.info({ approvalId: approval.id, messageId }, 'approval owner notification sent')
    } catch (err) {
      logger.warn({ err, approvalId: approval.id }, 'approval owner notification FAILED -- the request is only visible on the dashboard')
      fallbackInBand(approval, 'send-failed')
    }
  })()
}

function notifyMainAgent(approval: Approval): void {
  // APPROVALVAK821 (b): when the requester IS the main agent, this used to
  // deliver the notification back to the requester itself -- which counted as
  // "notified" while no human ever saw it. The owner Telegram above is the
  // real notification; a self-addressed message is noise that hides the gap.
  if (approval.agent_id === MAIN_AGENT_ID) {
    logger.info({ approvalId: approval.id }, 'approval main-agent notify skipped: requester is the main agent (owner is notified on Telegram)')
    return
  }
  try {
    createAgentMessage('system', MAIN_AGENT_ID, buildMainAgentApprovalMessage(approval))
  } catch (err) {
    // Non-fatal: the approval is created regardless; main-agent notification is best-effort
    logger.warn({ err, approvalId: approval.id }, 'Failed to notify main agent of approval request')
  }
}

// 9a2925a7 (Viktor, msg 603 and 1391; Patrik, D20261013-0800 6.): every fleet
// agent shares the dashboard token, so PATCH /api/approvals/:id can be called
// by any agent, and resolved_by / telegram_message_id are self-declared. Step 1
// is visibility: every approved/rejected resolution is announced to the owner
// on Telegram by the SERVER, so a closure the owner did not make is noticed.
// All of them, not only the suspicious ones: a forger fills in exactly the
// expected fields. The warning marks what the server can tell is off. The
// sweeper's timeout path is not announced. Step 2 (TOTP, an approval channel
// isolated from agents) comes later.
// APPROVALBOT1013 (Viktor 2302/2): 'telegram_button' is no longer a value a
// PATCH may claim -- only the server's approval bot writes it, together with
// resolution_channel='approval_bot', which no API route can set.
export const OWNER_RESOLUTION_SOURCES: readonly string[] = ['telegram_text']
export const SERVER_ONLY_RESOLVED_BY = 'telegram_button'

// Agent-written fields (resolved_by, category, agent_id, description) go into
// the owner's message on one line: control characters and line breaks are
// replaced, then the value is cut. A "telegram_text\nJóváhagyás lezárva: ..."
// resolved_by can then not draw a second, clean-looking line (Viktor, msg 1451).
const CONTROL_CHARS = new RegExp('[\\u0000-\\u001f\\u007f\\u2028\\u2029]+', 'g')
export function oneLine(value: string, max: number): string {
  return value.replace(CONTROL_CHARS, ' ').replace(/\s+/g, ' ').trim().slice(0, max)
}

// Pure + exported for tests. requestMessageId is the owner request's message
// (setApprovalTelegramMessageId), read BEFORE the resolution overwrites it.
export function approvalResolutionWarnings(input: {
  resolvedBy: string
  resolverMessageId: number | null
  requestMessageId: number | null
}): string[] {
  const warnings: string[] = []
  if (!OWNER_RESOLUTION_SOURCES.includes(input.resolvedBy)) {
    warnings.push(`nem Telegram-forrás: ${oneLine(input.resolvedBy, 60)}`)
  }
  if (input.resolverMessageId == null) {
    warnings.push('nincs tg-msg')
  } else if (input.requestMessageId == null) {
    warnings.push('a kérés tg-msg-je ismeretlen, nem összevethető')
  } else if (input.resolverMessageId <= input.requestMessageId) {
    warnings.push(`a tg-msg (${input.resolverMessageId}) nem újabb a kérésénél (${input.requestMessageId})`)
  }
  return warnings
}

// Owner-facing, plain text. The description is redacted and cut: it is
// agent-written and may carry a secret.
export function buildResolutionAlertText(approval: Approval, resolverMessageId: number | null, warnings: string[]): string {
  const description = oneLine(redact(approval.action_description.slice(0, 400)), 200)
  const line = [
    `Jóváhagyás lezárva: ${approval.status}`,
    oneLine(approval.category, 60),
    `kérte: ${oneLine(approval.agent_id, 60)}`,
    approval.resolution_channel === 'approval_bot'
      ? 'lezárta: Telegram-gomb (approval_bot, a szerver ellenőrizte)'
      : `lezárta: ${oneLine(approval.resolved_by ?? '?', 60)}`,
    `tg-msg: ${resolverMessageId ?? 'HIÁNYZIK'}`,
    description,
  ].join(' | ')
  return warnings.length > 0 ? `⚠️ ${line}\nGyanús: ${warnings.join('; ')}` : line
}

function resolutionAlertFailed(approvalId: string, reason: string, err?: unknown): void {
  logger.warn({ err, approvalId, reason }, 'approval resolution alert NOT sent')
  try {
    createAgentMessage('system', MAIN_AGENT_ID, `approval-riasztás nem ment ki: ${approvalId} (${reason})`)
  } catch (msgErr) {
    logger.warn({ err: msgErr, approvalId }, 'approval resolution alert fallback message failed too')
  }
}

// Fire-and-forget: the PATCH response never waits on, or changes with, the send.
function notifyOwnerOfResolution(approval: Approval, resolverMessageId: number | null, requestMessageId: number | null): void {
  void (async () => {
    const warnings = approvalResolutionWarnings({
      resolvedBy: approval.resolved_by ?? '',
      resolverMessageId,
      requestMessageId,
    })
    if (!TELEGRAM_BOT_TOKEN) return resolutionAlertFailed(approval.id, 'no-token')
    const ownerChat = resolveOwnerChatId()
    if (!ownerChat) return resolutionAlertFailed(approval.id, 'no-owner-chat')
    try {
      await sendTelegramMessage(TELEGRAM_BOT_TOKEN, ownerChat, buildResolutionAlertText(approval, resolverMessageId, warnings))
      logger.info({ approvalId: approval.id, warnings: warnings.length }, 'approval resolution alert sent')
    } catch (err) {
      resolutionAlertFailed(approval.id, 'send-failed', err)
    }
  })()
}

// The main bot to the owner: the approval bot's anomaly alerts go here, the
// channel the owner already reads for 9a2925a7 resolution alerts.
function alertOwnerMainBot(text: string): void {
  void (async () => {
    const ownerChat = resolveOwnerChatId()
    if (!TELEGRAM_BOT_TOKEN || !ownerChat) return resolutionAlertFailed('approval-bot', 'no-token-or-chat')
    try {
      await sendTelegramMessage(TELEGRAM_BOT_TOKEN, ownerChat, text)
    } catch (err) {
      resolutionAlertFailed('approval-bot', 'send-failed', err)
    }
  })()
}

// APPROVALBOT1013: a verified button resolution is announced like any other
// (9a2925a7), marked with its server-only channel and without the PATCH-path
// warnings, which do not apply.
export function notifyOwnerOfBotResolution(approval: Approval): void {
  alertOwnerMainBot(buildResolutionAlertText(approval, approval.bot_message_id ?? null, []))
}

export function startApprovalBot(): { stop: () => void } {
  return startApprovalBotPoller({ alert: alertOwnerMainBot, onResolved: notifyOwnerOfBotResolution })
}

export function startApprovalTimeoutSweeper(): NodeJS.Timeout {
  return setInterval(() => {
    try {
      const expired = expireTimedOutApprovals()
      if (expired > 0) logger.info({ expired }, 'Approval timeout sweep: expired pending approvals')
    } catch (err) {
      logger.warn({ err }, 'Approval timeout sweep failed')
    }
  }, 60_000)
}

export async function tryHandleApprovals(ctx: RouteContext): Promise<boolean> {
  const { req, res, path, method, url } = ctx

  // POST /api/approvals -- create new approval request
  if (path === '/api/approvals' && method === 'POST') {
    let body: { agent_id?: unknown; category?: unknown; action_description?: unknown; action_payload?: unknown; timeout_seconds?: unknown; content_hash?: unknown }
    try {
      body = JSON.parse((await readBody(req)).toString())
    } catch {
      json(res, { error: 'Invalid JSON' }, 400)
      return true
    }

    const { agent_id, category, action_description, action_payload, timeout_seconds, content_hash } = body
    if (typeof agent_id !== 'string' || !agent_id.trim()) {
      json(res, { error: 'agent_id is required' }, 400)
      return true
    }
    if (typeof category !== 'string' || !category.trim()) {
      json(res, { error: 'category is required' }, 400)
      return true
    }
    // Both end up in the owner's header and in the main agent's message, next
    // to the server-set fields. A free string could carry a quote, "id=" or a
    // forged action_quoted= (Viktor, msg 1526), so only plain identifiers pass.
    // Agent names are [a-z0-9-] (sanitizeAgentName); category keys are snake_case.
    if (!APPROVAL_IDENT_RE.test(agent_id)) {
      json(res, { error: 'agent_id must match ^[a-z0-9][a-z0-9_.-]{0,63}$' }, 400)
      return true
    }
    if (!APPROVAL_IDENT_RE.test(category)) {
      json(res, { error: 'category must match ^[a-z0-9][a-z0-9_.-]{0,63}$' }, 400)
      return true
    }
    if (typeof action_description !== 'string' || !action_description.trim()) {
      json(res, { error: 'action_description is required' }, 400)
      return true
    }
    if (action_payload !== undefined && typeof action_payload !== 'string') {
      json(res, { error: 'action_payload must be a string (JSON) if provided' }, 400)
      return true
    }
    // EMAILKAPU901 PR2: the email-approval-gate hook hands the requesting
    // agent this exact sha256 anchor (to+cc+subject+body); a malformed value
    // could never match the gate's recomputation, so reject it loudly here
    // instead of storing a row that silently authorizes nothing.
    if (content_hash !== undefined && (typeof content_hash !== 'string' || !/^[0-9a-f]{64}$/.test(content_hash))) {
      json(res, { error: 'content_hash must be a 64-char lowercase sha256 hex string if provided' }, 400)
      return true
    }

    const id = randomUUID()
    const timeout_at = computeTimeoutAt(category, timeout_seconds)
    const approval = createApproval({
      id,
      agent_id: agent_id.trim(),
      category: category.trim(),
      action_description: action_description.trim(),
      action_payload: typeof action_payload === 'string' ? action_payload : null,
      timeout_at,
      content_hash: typeof content_hash === 'string' ? content_hash : null,
    })

    notifyOwner(approval)
    notifyMainAgent(approval)
    logger.info({ id, agent_id, category }, 'Approval request created')
    json(res, approval, 201)
    return true
  }

  // GET /api/approvals -- list with filters
  if (path === '/api/approvals' && method === 'GET') {
    const agent_id = url.searchParams.get('agent') ?? undefined
    const category = url.searchParams.get('category') ?? undefined
    const status = url.searchParams.get('status') ?? undefined
    const limitRaw = url.searchParams.get('limit')
    const limit = limitRaw ? Math.min(parseInt(limitRaw, 10) || 100, 500) : 100

    const items = listApprovals({ agent_id, category, status, limit })
    json(res, items)
    return true
  }

  // POST /api/approvals/:id/consume -- f2c5edb0: one-shot consumption on the
  // SEND path. A sender the gate cannot see (a script that mails from another
  // host) calls this right BEFORE the letter goes out and sends only on 200.
  // 409 means do NOT send: the approval is used, unapproved, for another letter,
  // or stale -- and a second attempt on a used approval is the double send this
  // exists to stop.
  const consumeMatch = path.match(/^\/api\/approvals\/([^/]+)\/consume$/)
  if (consumeMatch && method === 'POST') {
    let body: { content_hash?: unknown; consumer?: unknown; message_id?: unknown }
    try {
      body = JSON.parse((await readBody(req)).toString())
    } catch {
      json(res, { error: 'Invalid JSON' }, 400)
      return true
    }
    const { content_hash, consumer, message_id } = body
    if (typeof content_hash !== 'string' || !/^[0-9a-f]{64}$/.test(content_hash)) {
      json(res, { error: 'content_hash must be the 64-char lowercase sha256 hex anchor of the letter being sent' }, 400)
      return true
    }
    if (!isConsumerName(consumer)) {
      json(res, { error: 'consumer is required: 1-120 printable characters naming the sending tool' }, 400)
      return true
    }
    if (message_id !== undefined && message_id !== null && !isMessageId(message_id)) {
      json(res, { error: 'message_id, if given, must be one RFC 5322 id like <local@domain> (max 250 chars)' }, 400)
      return true
    }
    const result = consumeApproval({
      id: consumeMatch[1],
      contentHash: content_hash,
      consumer: consumer.trim(),
      messageId: typeof message_id === 'string' ? message_id : null,
      windowSeconds: approvalWindowSeconds(),
    })
    if (result.ok) {
      logger.info({ id: consumeMatch[1], consumer: consumer.trim(), ref: message_id ?? null }, 'Approval consumed by the send path')
      json(res, { ok: true, approval: result.approval })
      return true
    }
    if (result.reason === 'not_found') {
      json(res, { ok: false, reason: 'not_found' }, 404)
      return true
    }
    const a = result.approval
    logger.warn({ id: consumeMatch[1], consumer: consumer.trim(), reason: result.reason }, 'Approval consume refused')
    json(res, {
      ok: false,
      reason: result.reason,
      approval: a ? { id: a.id, status: a.status, consumed_at: a.consumed_at, consumed_by: a.consumed_by, consumed_ref: a.consumed_ref } : null,
    }, 409)
    return true
  }

  // GET /api/approvals/:id -- status poll
  const idMatch = path.match(/^\/api\/approvals\/([^/]+)$/)
  if (idMatch && method === 'GET') {
    const approval = getApproval(idMatch[1])
    if (!approval) {
      json(res, { error: 'Not found' }, 404)
      return true
    }
    json(res, approval)
    return true
  }

  // PATCH /api/approvals/:id -- resolve (approve/reject/timeout)
  if (idMatch && method === 'PATCH') {
    let body: { status?: unknown; resolved_by?: unknown; telegram_message_id?: unknown }
    try {
      body = JSON.parse((await readBody(req)).toString())
    } catch {
      json(res, { error: 'Invalid JSON' }, 400)
      return true
    }

    const { status, resolved_by, telegram_message_id } = body
    if (status !== 'approved' && status !== 'rejected' && status !== 'timeout') {
      json(res, { error: 'status must be approved, rejected, or timeout' }, 400)
      return true
    }
    if (typeof resolved_by !== 'string' || !resolved_by.trim()) {
      json(res, { error: 'resolved_by is required' }, 400)
      return true
    }
    if (resolved_by.trim() === SERVER_ONLY_RESOLVED_BY) {
      json(res, { error: 'resolved_by "telegram_button" is set only by the server\'s approval bot, never through this route' }, 400)
      return true
    }
    const msgId = typeof telegram_message_id === 'number' ? telegram_message_id : null

    // Self-approval guard: the requesting agent cannot approve its own request.
    // This is a best-effort check on the self-declared resolved_by value (all fleet
    // agents share the same bearer token, so server-side identity is not enforceable).
    // It catches naive/accidental self-approvals; the real control lives on the
    // main-agent side (approval-request-handling skill).
    const target = getApproval(idMatch[1])
    if (target && resolved_by.trim() === target.agent_id) {
      json(res, { error: 'The requesting agent cannot approve its own request' }, 403)
      return true
    }

    const updated = resolveApproval(idMatch[1], status, resolved_by.trim(), msgId)
    if (!updated) {
      // Either not found or already resolved
      const existing = getApproval(idMatch[1])
      if (!existing) {
        json(res, { error: 'Not found' }, 404)
      } else {
        json(res, { error: `Already resolved as ${existing.status}` }, 409)
      }
      return true
    }

    const approval = getApproval(idMatch[1])
    logger.info({ id: idMatch[1], status, resolved_by }, 'Approval resolved')
    if (approval && (status === 'approved' || status === 'rejected')) {
      notifyOwnerOfResolution(approval, msgId, target?.telegram_message_id ?? null)
    }
    json(res, approval)
    return true
  }

  return false
}
