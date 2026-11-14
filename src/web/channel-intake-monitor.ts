/**
 * Channel intake monitor: measures whether a channel's inbound side is still
 * being consumed, using a signal that EXISTS while the channel is deaf.
 *
 * Why this is not covered by what we already run:
 *   - channel-health-monitor greps the pane for `✘ failed`. A plugin whose
 *     poll loop stopped while the process stayed alive renders nothing.
 *   - channel-poller-reap and channel-conflict-probe answer "is someone else
 *     holding the getUpdates slot", and only once the monitor already believes
 *     the channel is down.
 *   - inbound-probe is the gold standard, but it covers the MAIN channels
 *     session only (one transcript dir, one telethon prober account), and it
 *     is gated on an operator allowlisting that prober.
 * Finy sat deaf for five days in July 2026 with all of the above green. The
 * absence of inbound is not an event, so nothing fired.
 *
 * The positive signal used here is getWebhookInfo.pending_update_count: the
 * number of updates Telegram is holding that NOBODY has fetched. A live poller
 * keeps it at zero; a dead poll loop lets it grow the moment anyone writes to
 * the bot. It costs one HTTP call, contends with nothing, and -- unlike a
 * getUpdates probe -- cannot itself cause the deafness it is looking for
 * (grammy gives up permanently after 8 consecutive 409s, and a healthy poller
 * answered 409 to 2 of 5 hand-run getUpdates probes on 2026-09-06).
 *
 * Inbound silence is carried alongside as context only. An agent with nothing
 * to do is legitimately silent for days, so silence never alerts on its own.
 */

import { existsSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { encodeClaudeProjectDir } from '../claude-project-dir.js'
import { join } from 'node:path'
import { homedir } from 'node:os'
import { logger } from '../logger.js'
import { MAIN_AGENT_ID, STORE_DIR } from '../config.js'
import { agentDir, listAgentNames } from './agent-config.js'
import { isAgentRunning } from './agent-process.js'
import { readLastIngestionTimestamp, readLastIngestionTimestampAcross, mainTranscriptDirs } from './inbound-probe.js'
import { sendRoutineAlert } from './routine-alert.js'

const MINUTE_MS = 60 * 1000
const DAY_MS = 24 * 60 * 60 * 1000

// Silence long enough that a working agent would normally have heard something,
// short enough to still be actionable. Only ever downgrades an alert to a log
// line -- see decideIntakeVerdict.
export const INTAKE_SILENCE_THRESHOLD_MS = 2 * DAY_MS

// Two readings taken this close together describe one moment, not a trend.
export const BACKLOG_CONFIRM_MIN_GAP_MS = 3 * MINUTE_MS

// The channel is either deaf or it is not; repeating hourly buries the first
// message (see routine-alert). Matches the fleet's 3h re-alert cadence.
export const INTAKE_ALERT_COOLDOWN_MS = 3 * 60 * MINUTE_MS

// An unreachable stretch this long is worth one line to the owner once it ends:
// while our side cannot reach api.telegram.org the plugin's getUpdates cannot
// succeed either, so whatever was written to the bot arrives in one burst
// afterwards. Measured 2026-11-13 (card 6a9c1cc0): the main bot's backlog came
// in at once at 10:38 after the network outage, and nobody had been told that
// the bot was deaf. Shorter blips are routine and stay in the state file only.
export const UNREACHABLE_RECOVERY_NOTICE_MS = 30 * MINUTE_MS

// Written every tick so the monitor's work is MEASURABLE. The monitor is silent
// on success by design, which on 2026-11-13 left no way to tell a working probe
// of the main bot from one that never ran (Pulzus 11:10, card 6a9c1cc0).
export const INTAKE_STATE_FILE = join(STORE_DIR, 'channel-intake-state.json')

const CHECK_INTERVAL_MS = 5 * MINUTE_MS
const INITIAL_DELAY_MS = 100 * 1000
const PROBE_TIMEOUT_MS = 8_000

export interface IntakeProbe {
  /**
   * false when no usable Telegram answer came back: our side failed (network,
   * timeout), or something answered that is not a Telegram verdict on the token
   * (5xx, 429, a proxy's HTML, a 200 without a usable body).
   */
  reachable: boolean
  /** false when Telegram answered but rejected the token. */
  tokenOk: boolean
  /** Updates queued upstream that nobody has fetched; null when unknown. */
  pendingUpdates: number | null
  webhookUrl: string | null
  /** Telegram's own error text, clipped to ERROR_TEXT_MAX characters; null when absent. */
  lastErrorMessage: string | null
  /** Status of the HTTP answer that came back; null when the call never completed (network, timeout). */
  httpStatus: number | null
}

// Telegram's description (or a TLS-intercepting proxy's) goes into an alert
// sent through Telegram itself; an unbounded one would break the message
// (Viktor 42131 INFO 2).
export const ERROR_TEXT_MAX = 200

function clipErrorText(v: unknown): string | null {
  if (typeof v !== 'string') return null
  return v.length > ERROR_TEXT_MAX ? v.slice(0, ERROR_TEXT_MAX) + '…' : v
}

export interface IntakeObservation {
  at: number
  pendingUpdates: number
}

export type IntakeVerdict =
  | 'ok'
  | 'quiet'
  | 'unknown-inbound'
  | 'draining'
  | 'backlog-suspected'
  | 'deaf-backlog'
  | 'token-invalid'
  | 'unreachable'

export interface IntakeDecision {
  verdict: IntakeVerdict
  alert: boolean
}

interface TelegramWebhookInfoBody {
  ok?: boolean
  description?: string
  result?: {
    url?: string
    pending_update_count?: number
    last_error_message?: string
  }
}

/**
 * Turn one getWebhookInfo response into a probe reading.
 *
 * `status === 0` is the caller's marker for "the HTTP call never completed",
 * which must NOT be read as a bad token: our own network being down would
 * otherwise page the owner about every agent at once.
 *
 * Only Telegram's own refusal is a token verdict: a 401 or 404 carrying
 * Telegram's JSON (ok:false). A proxy's 401/404 page is not (Viktor 42131
 * INFO 1). Everything else that is not a healthy answer --
 * 5xx, 429, a proxy's HTML page, a 200 without a usable body -- used to be read
 * as token-invalid as well, which during a Telegram-side outage would page the
 * owner about a "rejected token" and cut the outage stretch short (Viktor 42107
 * INFO 3, card fe7f332b). It is now read like unreachable: no alert, and the
 * stretch goes on.
 */
export function isTokenRejection(status: number, body: unknown): boolean {
  if (status !== 401 && status !== 404) return false
  return body !== null && typeof body === 'object' && (body as TelegramWebhookInfoBody).ok === false
}

export function parseIntakeProbe(status: number, body: unknown): IntakeProbe {
  const httpStatus = status === 0 ? null : status
  const unusable: IntakeProbe = { reachable: false, tokenOk: true, pendingUpdates: null, webhookUrl: null, lastErrorMessage: null, httpStatus }
  if (status === 0) return unusable
  const parsed = (body ?? {}) as TelegramWebhookInfoBody
  if (isTokenRejection(status, body)) {
    return {
      reachable: true,
      tokenOk: false,
      pendingUpdates: null,
      webhookUrl: null,
      lastErrorMessage: clipErrorText(parsed.description),
      httpStatus,
    }
  }
  if (status !== 200 || parsed.ok !== true || !parsed.result) return unusable
  const pending = parsed.result.pending_update_count
  return {
    reachable: true,
    tokenOk: true,
    pendingUpdates: typeof pending === 'number' ? pending : null,
    webhookUrl: parsed.result.url ?? null,
    lastErrorMessage: clipErrorText(parsed.result.last_error_message),
    httpStatus,
  }
}

/**
 * Pure verdict for one agent's channel intake.
 *
 * Alerting cases (both are positive evidence):
 *   - `token-invalid`: Telegram answered and refused the token.
 *   - `deaf-backlog`: updates were queued upstream at two readings far enough
 *     apart to be a trend, and the queue did not shrink between them. A live
 *     poller drains in milliseconds, so a queue that survives minutes means
 *     nobody is fetching.
 *
 * Everything else is logged only. `quiet` in particular is a suspicion, not a
 * finding: silence is also what a correctly working idle agent looks like.
 */
export function decideIntakeVerdict(opts: {
  probe: IntakeProbe
  prev: IntakeObservation | null
  lastInboundAt: number | null
  now: number
  silenceThresholdMs: number
}): IntakeDecision {
  const { probe, prev, lastInboundAt, now, silenceThresholdMs } = opts

  if (!probe.reachable) return { verdict: 'unreachable', alert: false }
  if (!probe.tokenOk) return { verdict: 'token-invalid', alert: true }

  const pending = probe.pendingUpdates ?? 0
  if (pending > 0) {
    const confirmed =
      prev != null &&
      prev.pendingUpdates > 0 &&
      now - prev.at >= BACKLOG_CONFIRM_MIN_GAP_MS
    if (!confirmed) return { verdict: 'backlog-suspected', alert: false }
    if (pending < prev.pendingUpdates) return { verdict: 'draining', alert: false }
    return { verdict: 'deaf-backlog', alert: true }
  }

  // No ingestion timestamp is missing evidence, not evidence of silence: the
  // transcript scan reads the newest JSONL's tail, and an agent whose newest
  // session is a worker or a scheduled run shows no channel line at all. Saying
  // "silent forever" there would be an unmeasured claim on every tick.
  if (lastInboundAt == null) return { verdict: 'unknown-inbound', alert: false }
  if (now - lastInboundAt >= silenceThresholdMs) return { verdict: 'quiet', alert: false }
  return { verdict: 'ok', alert: false }
}

export function formatIntakeAlert(agentName: string, decision: IntakeDecision, probe: IntakeProbe, silentForMs: number | null): string {
  const silence =
    silentForMs == null ? 'nem érkezett bejövő üzenet, amióta figyeljük'
    : `${Math.floor(silentForMs / DAY_MS)} napja nem érkezett bejövő üzenet`
  if (decision.verdict === 'token-invalid') {
    return `🔇 ${agentName}: a Telegram elutasította a bot tokent (${probe.lastErrorMessage ?? 'nincs indoklás'}). A csatorna nem tud fogadni. ${silence}.`
  }
  return `🔇 ${agentName}: ${probe.pendingUpdates} bejövő üzenet áll a Telegram sorában, és senki nem veszi le. A plugin fut, de a poll-ciklusa halott. ${silence}.`
}

/** What the state file records for one agent: no token, no webhook URL, no Telegram error text. */
export interface IntakeStateEntry {
  /** ms epoch of the reading. */
  at: number
  /** 'no-token': the agent's channel .env (or its token line) was not found, so it was NOT probed. */
  verdict: IntakeVerdict | 'no-token'
  reachable: boolean | null
  tokenOk: boolean | null
  pending: number | null
  /** ms epoch of the first unreachable reading of the current stretch; null when reachable. */
  unreachableSince: number | null
}

/** Pure: the state entry for one probe. Only booleans, counts and timestamps leave this function. */
export function intakeStateEntry(
  probe: IntakeProbe,
  verdict: IntakeVerdict,
  now: number,
  prev: IntakeStateEntry | null,
): IntakeStateEntry {
  const unreachableSince = probe.reachable ? null : (prev?.unreachableSince ?? now)
  return {
    at: now,
    verdict,
    reachable: probe.reachable,
    tokenOk: probe.tokenOk,
    pending: probe.pendingUpdates,
    unreachableSince,
  }
}

/**
 * Pure: the row for an agent whose token was not found -- main agent only. A
 * sub-agent without a channel is normal; the main agent without a token is the
 * 11-13 blind spot made visible.
 */
export function noTokenStateEntryFor(agentName: string, now: number): IntakeStateEntry | null {
  if (agentName !== MAIN_AGENT_ID) return null
  return { at: now, verdict: 'no-token', reachable: null, tokenOk: null, pending: null, unreachableSince: null }
}

/**
 * Pure: the length of an unreachable stretch that THIS reading ends, when it is
 * long enough to report; null otherwise (still unreachable, never was, or a blip).
 */
export function unreachableRecoveredAfter(
  prev: IntakeStateEntry | null,
  probe: IntakeProbe,
  now: number,
  minMs: number = UNREACHABLE_RECOVERY_NOTICE_MS,
): number | null {
  if (!probe.reachable) return null
  const since = prev?.unreachableSince
  if (since == null) return null
  const lengthMs = now - since
  return lengthMs >= minMs ? lengthMs : null
}

export function formatUnreachableRecovered(agentName: string, lengthMs: number, since: number): string {
  const from = new Date(since).toLocaleTimeString('hu-HU', { timeZone: 'Europe/Budapest', hour: '2-digit', minute: '2-digit' })
  // The probe is the dashboard's own call, not the plugin's getUpdates: that the
  // bot was deaf too is an inference, so the sentence says so (Viktor 42107 LOW 2).
  // "kb.": the stretch is measured in 5-minute ticks, and after a restart it also
  // counts the dashboard's own downtime, which no probe saw (Viktor 42111 INFO 2).
  return `📶 ${agentName}: a gép kb. ${Math.round(lengthMs / MINUTE_MS)} percig nem kapott használható választ a Telegramtól (${from} óta). Ez alatt a bot valószínűleg befelé süket volt; ami közben jött, feltehetően most egyben érkezik.`
}

export interface RecoveryNotice {
  key: string
  text: string
  cooldownMs: number
}

/**
 * Pure: the one notice a long outage's end earns, or null. Main agent only: a
 * network outage hits every bot at once and would otherwise send one line per
 * bot (Viktor 42107 LOW 3, W01). The cooldown travels with it (W02).
 */
export function recoveryNoticeFor(
  agentName: string,
  prev: IntakeStateEntry | null,
  probe: IntakeProbe,
  now: number,
): RecoveryNotice | null {
  if (agentName !== MAIN_AGENT_ID) return null
  const lengthMs = unreachableRecoveredAfter(prev, probe, now)
  const since = prev?.unreachableSince
  if (lengthMs == null || since == null) return null
  return {
    key: `channel-intake:${agentName}:unreachable-recovered`,
    text: formatUnreachableRecovered(agentName, lengthMs, since),
    cooldownMs: INTAKE_ALERT_COOLDOWN_MS,
  }
}

// Telegram answering, but not usefully (5xx, 429, a proxy page), for this long
// is worth a line WHILE it lasts: unlike a network outage, an alert can still go
// out, and without it nothing would speak until the stretch ends (Viktor 42131
// INFO 3). Repeats follow the 3 h alert cooldown.
export const ONGOING_OUTAGE_NOTICE_MS = 2 * 60 * MINUTE_MS

export function formatOngoingOutage(agentName: string, lengthMs: number, since: number, httpStatus: number): string {
  const from = new Date(since).toLocaleTimeString('hu-HU', { timeZone: 'Europe/Budapest', hour: '2-digit', minute: '2-digit' })
  return `⚠️ ${agentName}: a gép kb. ${Math.round(lengthMs / MINUTE_MS)} perce nem kap használható választ a Telegramtól (${from} óta, utolsó HTTP-kód: ${httpStatus}). Ez alatt a bot valószínűleg befelé süket.`
}

/**
 * Pure: the mid-outage line, or null. Main agent only; only when the latest
 * reading was an HTTP answer (a network outage could not deliver the alert);
 * `entry` is the row AFTER this reading.
 */
export function ongoingOutageNoticeFor(
  agentName: string,
  entry: IntakeStateEntry,
  probe: IntakeProbe,
  now: number,
): RecoveryNotice | null {
  if (agentName !== MAIN_AGENT_ID) return null
  if (probe.reachable || probe.httpStatus == null) return null
  const since = entry.unreachableSince
  if (since == null || now - since < ONGOING_OUTAGE_NOTICE_MS) return null
  return {
    key: `channel-intake:${agentName}:outage-ongoing`,
    text: formatOngoingOutage(agentName, now - since, since, probe.httpStatus),
    cooldownMs: INTAKE_ALERT_COOLDOWN_MS,
  }
}

// A restart in the middle of an outage (power cut, reboot: exactly when the bot
// is deaf) would otherwise lose the stretch's start (Viktor 42107 LOW 1). A row
// older than this describes another moment and is not carried over.
export const STATE_SEED_MAX_AGE_MS = 15 * MINUTE_MS

// A carried-over stretch older than this is not an outage we measured: a
// hand-edited or corrupt file (epoch 0 gave "29910720 percig", Viktor 42111
// INFO 1) is dropped instead of reported.
export const SEED_MAX_STRETCH_MS = 7 * DAY_MS

/** Pure: the main agent's row from a previous run's state file, if it is fresh and well-formed; else null. */
export function seedMainStateFrom(raw: string | null, now: number): IntakeStateEntry | null {
  if (raw == null) return null
  let body: unknown
  try { body = JSON.parse(raw) } catch { return null }
  const row = (body as { agents?: Record<string, unknown> } | null)?.agents?.[MAIN_AGENT_ID] as Partial<IntakeStateEntry> | undefined
  if (!row || typeof row !== 'object') return null
  const numOrNull = (v: unknown) => v === null || (typeof v === 'number' && Number.isFinite(v))
  const boolOrNull = (v: unknown) => v === null || typeof v === 'boolean'
  if (typeof row.at !== 'number' || !Number.isFinite(row.at)) return null
  if (row.at > now || now - row.at > STATE_SEED_MAX_AGE_MS) return null
  if (typeof row.verdict !== 'string' || !numOrNull(row.pending) || !numOrNull(row.unreachableSince)) return null
  if (!boolOrNull(row.reachable) || !boolOrNull(row.tokenOk)) return null
  if (row.unreachableSince != null && row.unreachableSince > row.at) return null
  if (row.unreachableSince != null && row.unreachableSince < row.at - SEED_MAX_STRETCH_MS) return null
  return {
    at: row.at,
    verdict: row.verdict as IntakeStateEntry['verdict'],
    reachable: row.reachable ?? null,
    tokenOk: row.tokenOk ?? null,
    pending: row.pending ?? null,
    unreachableSince: row.unreachableSince ?? null,
  }
}

/** Atomic write of the per-agent state (tmp + rename), so a reader never sees half a file. */
export function writeIntakeState(path: string, entries: ReadonlyMap<string, IntakeStateEntry>, now: number): void {
  const body = { writtenAt: now, agents: Object.fromEntries(entries) }
  const tmp = `${path}.tmp-${process.pid}`
  writeFileSync(tmp, JSON.stringify(body, null, 2) + '\n', { mode: 0o600 })
  renameSync(tmp, path)
}

// ---------------------------------------------------------------------------
// Runtime
// ---------------------------------------------------------------------------

const lastObservation = new Map<string, IntakeObservation>()
const lastQuietLogAt = new Map<string, number>()
const lastState = new Map<string, IntakeStateEntry>()

/** Test seam: a copy of the per-agent state the next write would record. */
export function intakeStateSnapshot(): Map<string, IntakeStateEntry> {
  return new Map(lastState)
}

/**
 * Carry the main agent's row over a restart (see seedMainStateFrom). Returns
 * whether a row was carried. Exported so the call in startChannelIntakeMonitor
 * is testable end to end (Viktor 42111 LOW, W07).
 */
export function seedIntakeStateFromFile(path: string, now: number): boolean {
  try {
    const seeded = seedMainStateFrom(existsSync(path) ? readFileSync(path, 'utf-8') : null, now)
    if (!seeded) return false
    lastState.set(MAIN_AGENT_ID, seeded)
    return true
  } catch (err) {
    logger.debug({ err }, 'channel-intake-monitor: state seed read error')
    return false
  }
}

// A quiet channel is a standing condition, not an event; repeating it every
// tick would bury the lines that matter in dashboard.log.
const QUIET_LOG_INTERVAL_MS = 6 * 60 * MINUTE_MS

/** Test seam: reset the per-agent backlog history. */
export function resetIntakeObservations(): void {
  lastObservation.clear()
  lastQuietLogAt.clear()
  lastState.clear()
}

/**
 * Where an agent's Telegram channel .env can live, most likely first.
 *
 * The main agent's channel is $INSTALL_DIR/.claude/channels/telegram -- that is
 * the TELEGRAM_STATE_DIR scripts/channels.sh exports for the main session
 * (MAIN_CHAN_DIR, channels.sh:1167). This monitor used to look ONLY under
 * homedir()/.claude/channels/telegram; on an install whose main channel lives in
 * the install dir that file does not exist, readTelegramToken returned null and
 * the main agent was silently never probed. Measured 2026-11-13 (card 6a9c1cc0,
 * Klodel kanban 20225): the main bot was deaf 07:20-10:38 and this monitor said
 * nothing. The home path stays as the fallback for older installs. Every
 * sub-agent has its own copy under its agent dir (mirrors telegram.ts).
 */
export function channelEnvPathCandidates(agentName: string, projectRoot: string): string[] {
  if (agentName !== MAIN_AGENT_ID) return [join(agentDir(agentName), '.claude', 'channels', 'telegram', '.env')]
  return [...new Set([
    join(projectRoot, '.claude', 'channels', 'telegram', '.env'),
    join(homedir(), '.claude', 'channels', 'telegram', '.env'),
  ])]
}

/** The first existing candidate, or the most likely one when none exists. */
export function channelEnvPathFor(agentName: string, projectRoot: string, exists: (p: string) => boolean = existsSync): string {
  const candidates = channelEnvPathCandidates(agentName, projectRoot)
  return candidates.find(exists) ?? candidates[0]
}

// The main agent ALWAYS has a channel: a missing token there is a monitor blind
// spot, not "this agent has no channel". Said once per process, not per tick.
let mainTokenMissingLogged = false

function readTelegramToken(agentName: string, projectRoot: string): string | null {
  const envPath = channelEnvPathFor(agentName, projectRoot)
  if (!existsSync(envPath)) {
    if (agentName === MAIN_AGENT_ID && !mainTokenMissingLogged) {
      mainTokenMissingLogged = true
      logger.warn({ candidates: channelEnvPathCandidates(agentName, projectRoot) },
        'channel-intake-monitor: no Telegram .env found for the MAIN agent -- its intake is NOT monitored')
    }
    return null
  }
  try {
    const match = readFileSync(envPath, 'utf-8').match(/^\s*TELEGRAM_BOT_TOKEN=(.+)$/m)
    return match?.[1]?.trim() || null
  } catch {
    return null
  }
}

/** Transcript dir Claude Code uses for a cwd under the shared root (encoder: src/claude-project-dir.ts). */
export function transcriptDirFor(agentName: string, projectRoot: string): string {
  const cwd = agentName === MAIN_AGENT_ID ? projectRoot : agentDir(agentName)
  return join(process.env['HOME'] ?? homedir(), '.claude', 'projects', encodeClaudeProjectDir(cwd))
}

// Same CONFIG-DIR BLIND SPOT the keepalive watchdog hit (see mainTranscriptDirs
// in inbound-probe.ts): an agent running with an isolated CLAUDE_CONFIG_DIR
// writes its transcript under THAT root, not the shared ~/.claude, so reading
// only the shared path reports "no inbound ever" for a perfectly busy agent.
// Both the main agent (<PROJECT_ROOT>/.channels-config) and every sub-agent
// (<agentDir>/.claude-config) can be isolated, so probe each candidate root and
// let the newest ingestion win.
export function transcriptDirsFor(agentName: string, projectRoot: string): string[] {
  if (agentName === MAIN_AGENT_ID) return mainTranscriptDirs()
  const cwd = agentDir(agentName)
  const encoded = encodeClaudeProjectDir(cwd)
  const roots = [
    join(process.env['HOME'] ?? homedir(), '.claude'),
    join(cwd, '.claude-config'),
  ]
  return [...new Set(roots.map(r => join(r, 'projects', encoded)))]
}

async function probeIntake(token: string): Promise<IntakeProbe> {
  try {
    const res = await fetch(`https://api.telegram.org/bot${token}/getWebhookInfo`, {
      signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
    })
    let body: unknown = null
    try {
      body = await res.json()
    } catch {
      // Telegram always answers JSON; a proxy in between might not.
    }
    return parseIntakeProbe(res.status, body)
  } catch {
    return parseIntakeProbe(0, null)
  }
}

async function checkAgentIntake(agentName: string, projectRoot: string): Promise<void> {
  const token = readTelegramToken(agentName, projectRoot)
  if (!token) {
    const entry = noTokenStateEntryFor(agentName, Date.now())
    if (entry) lastState.set(agentName, entry)
    return
  }

  const probe = await probeIntake(token)
  const now = Date.now()
  const lastInboundAt = readLastIngestionTimestampAcross(transcriptDirsFor(agentName, projectRoot))
  applyIntakeProbe(agentName, probe, lastInboundAt, now)
}

export type IntakeAlertSender = (key: string, text: string, opts: { cooldownMs: number }) => void

/**
 * Everything after the HTTP call: verdict, backlog history, state row, the
 * outage-end notice and the deafness alert. Exported with an injectable sender
 * so the call sites of both alerts are tested, not just the pure decisions
 * (Viktor 42111 LOW, W14/W15).
 */
export function applyIntakeProbe(
  agentName: string,
  probe: IntakeProbe,
  lastInboundAt: number | null,
  now: number,
  send: IntakeAlertSender = sendRoutineAlert,
): IntakeDecision {
  const decision = decideIntakeVerdict({
    probe,
    prev: lastObservation.get(agentName) ?? null,
    lastInboundAt,
    now,
    silenceThresholdMs: INTAKE_SILENCE_THRESHOLD_MS,
  })

  if (probe.pendingUpdates != null) {
    lastObservation.set(agentName, { at: now, pendingUpdates: probe.pendingUpdates })
  }

  const prevState = lastState.get(agentName) ?? null
  const entry = intakeStateEntry(probe, decision.verdict, now, prevState)
  lastState.set(agentName, entry)
  const notice = recoveryNoticeFor(agentName, prevState, probe, now)
  if (notice) {
    logger.warn({ agent: agentName, unreachableSince: prevState?.unreachableSince }, 'channel-intake-monitor: Telegram reachable again after a long outage')
    send(notice.key, notice.text, { cooldownMs: notice.cooldownMs })
  }
  const ongoing = ongoingOutageNoticeFor(agentName, entry, probe, now)
  if (ongoing) {
    logger.warn({ agent: agentName, unreachableSince: entry.unreachableSince, httpStatus: probe.httpStatus }, 'channel-intake-monitor: Telegram answering but unusable for a long while')
    send(ongoing.key, ongoing.text, { cooldownMs: ongoing.cooldownMs })
  }

  const silentForMs = lastInboundAt == null ? null : now - lastInboundAt
  // Never log message bodies -- only counts and timestamps (see inbound-probe).
  logger.debug(
    { agent: agentName, verdict: decision.verdict, pending: probe.pendingUpdates, silentForMs },
    'channel-intake-monitor: probe',
  )

  if (decision.verdict === 'quiet') {
    const loggedAt = lastQuietLogAt.get(agentName) ?? 0
    if (now - loggedAt >= QUIET_LOG_INTERVAL_MS) {
      lastQuietLogAt.set(agentName, now)
      logger.info(
        { agent: agentName, silentForMs },
        'channel-intake-monitor: no inbound for a long while, but the intake is clean (not an alert on its own)',
      )
    }
    return decision
  }
  if (!decision.alert) return decision

  logger.warn(
    { agent: agentName, verdict: decision.verdict, pending: probe.pendingUpdates, silentForMs },
    'channel-intake-monitor: channel intake is dead',
  )
  send(
    `channel-intake:${agentName}:${decision.verdict}`,
    formatIntakeAlert(agentName, decision, probe, silentForMs),
    { cooldownMs: INTAKE_ALERT_COOLDOWN_MS },
  )
  return decision
}

export function startChannelIntakeMonitor(projectRoot: string, opts: { stateFile?: string } = {}): NodeJS.Timeout {
  const stateFile = opts.stateFile ?? INTAKE_STATE_FILE
  let stateWriteWarned = false
  async function check(): Promise<void> {
    const names = [MAIN_AGENT_ID, ...listAgentNames().filter(n => n !== MAIN_AGENT_ID)]
    for (const name of names) {
      // A stopped agent has no poller by design; that is not deafness.
      if (name !== MAIN_AGENT_ID && !isAgentRunning(name)) {
        lastObservation.delete(name)
        lastState.delete(name)
        continue
      }
      try {
        await checkAgentIntake(name, projectRoot)
      } catch (err) {
        logger.debug({ err, agent: name }, 'channel-intake-monitor: check error')
      }
    }
    try {
      writeIntakeState(stateFile, lastState, Date.now())
      stateWriteWarned = false
    } catch (err) {
      // A lasting failure (full disk) would otherwise leave a stale file in silence (Viktor 42107 INFO 2).
      if (!stateWriteWarned) logger.warn({ err }, 'channel-intake-monitor: state file write failed -- readers see a stale file')
      stateWriteWarned = true
    }
  }

  seedIntakeStateFromFile(stateFile, Date.now())

  // Offset past channel-monitor (30s) and channel-health-monitor (45s) so the
  // three do not share a tick.
  setTimeout(() => void check(), INITIAL_DELAY_MS)
  return setInterval(() => void check(), CHECK_INTERVAL_MS)
}
