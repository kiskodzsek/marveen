import { statSync, readFileSync, writeFileSync, renameSync } from 'node:fs'
import { join } from 'node:path'
import { logger } from '../logger.js'
import { MAIN_AGENT_ID, PROJECT_ROOT } from '../config.js'
import { hardRestartMarveenChannels, lastMainRespawnAt, MARVEEN_POST_RESPAWN_GRACE_MS, markAgentRestartPending } from './channel-monitor.js'
import { shouldDeferForRecentRespawn } from './stuck-tool-call-watcher.js'
import { listAgentNames, listAllAgentNames, agentDir, readAgentModel, readAgentRemoteHost } from './agent-config.js'
import { configDirFor } from './main-transcript-root.js'
import {
  agentRunState,
  agentSessionName,
  restartAgentProcess,
  capturePane,
  isSessionReadyForPrompt,
  noteSaturationBannerUntrusted,
  clearSaturationBannerOverride,
} from './agent-process.js'
import { sendSystemDirective } from './system-directive.js'
import { urgentEmitRefusal, setDeliveryHoldCheck, type DeliveryHold } from './message-router.js'
import { notifyChannel } from '../notify.js'
import { MAIN_CHANNELS_SESSION } from './main-agent.js'
import { backgroundAgentCount, detectPaneState, paneShowsContextSaturation, paneShowsContextSaturationHardError, type PaneState } from '../pane-state.js'
import { readContextTokensFromProjectDir, readActiveModelFromProjectDir, readTranscriptMtimeFromProjectDir } from './active-model.js'
import { readContextGuardConfig } from './context-guard-store.js'
import { localMidnightMs } from '../auto-restart.js'
import { recordRescueFailure, clearRescueFailures } from './rescue-failure-tracker.js'
import { createAgentMessage } from '../db.js'
import {
  decideGuard,
  contextLimitForModel,
  calibrateLimit,
  handoffStaleMinutes,
  applyDailyHandoffSweep,
  DAILY_HANDOFF_REASON_PREFIX,
  IDLE_FLUSH_REASON_PREFIX,
  INITIAL_GUARD_STATE,
  STALE_REFRESH_REASON_PREFIX,
  HANDOFF_RESEND_REASON_PREFIX,
  READY_TIMEOUT_MS,
  SATURATION_CREDIBLE_MIN_PCT,
  saturationBannerCredible,
  type GuardState,
  type HandoffStaleness,
  type GuardInputs,
  type ContextGuardConfig,
} from '../context-guard.js'

// Fleet context guard (kanban #81): acts BEFORE a session drowns in its own
// context. Sweep every agent (main included) every five minutes; at actPct ask the
// agent to write HANDOFF.md, then fresh-restart it and inject a resume prompt
// pointing at the handoff. The always-on saturation net additionally rescues a
// pane already showing "100% context used" -- unreachable by prompt dispatch,
// so nothing else can recover it (samu stall, 2026-07-18). See
// src/context-guard.ts for the why and the pure state machine; this module is
// only the I/O, mirroring auto-restart-runner.
//
// Remote-host agents are skipped: their transcripts live on the remote machine,
// so the context size cannot be measured here (v1 limitation, logged once).

const INITIAL_DELAY_MS = 270_000
export const INTERVAL_MS = 300_000

// C106C3FF (measured 2026-10-14, Mira 22:44-22:59): while an agent is in
// await-handoff the router holds its messages (GUARDHOLD1013), and the hold
// ends only when the phase does. With the full sweep every 5 minutes, a
// handoff written right after a sweep kept 13 messages pending for up to one
// whole interval more. The fast round re-runs ONLY the await-handoff -> restart
// step, every FAST_INTERVAL_MS, with the same decideGuard (Viktor 2659):
// it types nothing (request-handoff and resend decisions stay on the full
// sweep), and it restarts only after FAST_IDLE_CONFIRM consecutive idle
// readings, so one idle-looking frame between two tool calls cannot cut a turn.
//
// CGRESUME1021 (measured 2026-10-21, Dave 13:45:52 and Kernel 13:50:32): the
// fast round restarts, but the resume prompt was left to the full sweep, so the
// fresh session sat at an empty prompt for 0-5 minutes (a supervisor typed the
// resume by hand after 1.5 minutes, and the sweep's ready-timeout then sent a
// second one). The fast round therefore also runs the await-ready step, and
// acts ONLY on 'inject-resume' with a ready session (isSessionReadyForPrompt:
// two idle captures). The ready-timeout injection into a busy pane stays on the
// full sweep. The resume goes through the same anchored directive and emit
// guard as on the sweep.
export const FAST_INTERVAL_MS = 20_000
export const FAST_IDLE_CONFIRM = 2

// The router's fail-open cap for a guard hold, per agent and derived from the
// same config the guard runs on (Viktor 2659): the designed path is "handoff
// timeout, then the restart on the next full sweep"; the slack covers one slow
// sweep (a restart in flight) on top. Above this, a held row is delivered.
export const GUARD_HOLD_SLACK_MS = 2 * 60_000
export function guardHoldCapMs(cfg: Pick<ContextGuardConfig, 'handoffTimeoutMinutes'>): number {
  return cfg.handoffTimeoutMinutes * 60_000 + INTERVAL_MS + GUARD_HOLD_SLACK_MS
}

// CGHOLDREADY1021 (measured 2026-10-21, dashboard.log, Dave's restarts at 14:05,
// 14:32, 15:04 and 15:18): the hold ended with await-handoff, so the rows it had
// kept back were delivered 4-6 s after the fresh session started -- before the
// fast round's resume. The session worked its inbox instead of reading as ready,
// and got the resume from the ready-timeout path 5-8 minutes later (78 s at
// 14:32, a short turn). Restarts with no held row resumed in ~18 s (Pulzus,
// Viktor, Kernel). So the hold lasts through await-ready too: the resume goes in
// first, the rows after it. The cap grows by the await-ready window (the ready
// timeout plus the full sweep that injects on it), so a row held since
// await-handoff is not released in the middle of the designed path.
export function guardReadyHoldCapMs(cfg: Pick<ContextGuardConfig, 'handoffTimeoutMinutes'>): number {
  return guardHoldCapMs(cfg) + READY_TIMEOUT_MS + INTERVAL_MS
}

/** Which hold a guard phase puts on the router, with its cap. Pure, for the test. */
export function deliveryHoldForPhase(
  phase: string, cfg: Pick<ContextGuardConfig, 'handoffTimeoutMinutes'>,
): DeliveryHold | null {
  if (phase === 'await-handoff') return { reason: 'context-guard await-handoff', maxMs: guardHoldCapMs(cfg) }
  if (phase === 'await-ready') return { reason: 'context-guard await-ready', maxMs: guardReadyHoldCapMs(cfg) }
  return null
}

/** The router's hold check: a hold (with its cap) while the agent is in
 *  await-handoff, and on through await-ready until the resume is in. */
export function guardDeliveryHold(name: string): DeliveryHold | null {
  const phase = getHardGuardPhase(name)
  if (phase !== 'await-handoff' && phase !== 'await-ready') return null
  return deliveryHoldForPhase(phase, readContextGuardConfig(name))
}

// How long the dispatch gate honours one sweep's "this banner is not
// credible" verdict. Expressed in SWEEPS, not minutes, so it cannot silently
// drift under the refresh rate if INTERVAL_MS ever changes: the entry has to
// outlive one missed or slow sweep, AND it has to lapse on its own if this
// runner stops (webOnly mode, guard disabled, crash) so the gate falls back to
// today's "refuse and wait for the rescue" rather than staying open.
const SATURATION_OVERRIDE_TTL_MS = 3 * INTERVAL_MS

// agent name -> guard state. In-memory: a dashboard restart re-arms every
// agent at 'idle', which is safe -- the worst case is a repeated handoff
// request, and cooldown prevents restart loops within a run. The one
// exception is await-ready after a restart that ran: see PENDING_RESUME_PATH.
const guardStates = new Map<string, GuardState>()
// CGGAPS1013 / Viktor 2453 L2: early cooldown exits in the current chain, per
// agent (reset when a cooldown runs out normally). In memory, like guardStates.
const earlyCooldownExits = new Map<string, number>()
const earlyBlockLogged = new Set<string>()
// C106C3FF: consecutive fast-round readings of an idle pane, per agent in
// await-handoff. Cleared whenever the agent is seen in any other phase.
const fastIdleStreak = new Map<string, number>()
// Agents whose "background agents running, restarts defer" line is already
// logged; cleared when the panel is gone, so each stretch is logged once.
const bgAgentDeferLogged = new Set<string>()

// agent name -> when the daily-handoff tier last fired (ms). Seeded on first
// sight WITHOUT firing, so a slot that already passed before the dashboard
// started does not trigger a handoff cycle at boot -- the same seed rule, for
// the same reason, as the nightly auto-restart's lastRestart map. In-memory
// like that one: a dashboard restart re-seeds and at worst skips one slot,
// which is the safe direction (a missed daily handoff costs one day of
// context; a spurious one ends a live conversation).
const lastDailyHandoff = new Map<string, number>()
const remoteSkipLogged = new Set<string>()
// Agents currently in the banner-vs-measurement mismatch state. The
// condition holds on EVERY sweep while a mis-tagged agent keeps running, so
// the WARN below is emitted on the state CHANGE only -- per-sweep it would be
// ~1150 lines a day into a log nobody then reads. Same idiom as
// remoteSkipLogged above.
const bannerMismatchLogged = new Set<string>()

// Per-agent observed-context high-water mark, persisted across dashboard
// restarts. calibrateLimit alone is memoryless: the moment the guard
// restarts an agent, the fresh session's observation shrinks back below the
// tier step-up point, the denominator falls back to the base guess, and a
// miscalibrated agent gets restarted at the same false "over-full" reading
// every cycle -- the evidence that would have corrected the limit is
// destroyed by the very restart it triggered. Persisting the per-(agent,
// model) maximum breaks that loop: once a session has proven the window is
// bigger, the proof survives restarts. Keyed by model so a real model
// downgrade (e.g. fable-5 -> haiku) does not inherit a 1M denominator.
const HIGHWATER_PATH = join(PROJECT_ROOT, 'store', 'context-guard-highwater.json')
type HighwaterMap = Record<string, { model: string; tokens: number }>

function readHighwater(): HighwaterMap {
  try {
    const parsed = JSON.parse(readFileSync(HIGHWATER_PATH, 'utf-8'))
    return (parsed && typeof parsed === 'object') ? parsed as HighwaterMap : {}
  } catch { return {} }
}

let highwater: HighwaterMap | null = null

function observedHighwater(name: string, model: string, observedNow: number): number {
  if (highwater === null) highwater = readHighwater()
  const entry = highwater[name]
  const prior = entry && entry.model === model ? entry.tokens : 0
  if (observedNow > prior) {
    highwater[name] = { model, tokens: observedNow }
    try { writeFileSync(HIGHWATER_PATH, JSON.stringify(highwater, null, 2)) }
    catch (err) { logger.warn({ err }, 'context-guard: highwater persist failed') }
  }
  return Math.max(observedNow, prior)
}

// CGRESUME1021 (measured 2026-10-21): Dave was restarted at 13:17:53 and the
// dashboard itself restarted at 13:18:29 (a release). The await-ready state
// lived only in guardStates, so the new dashboard re-armed Dave at 'idle' and
// the resume prompt was never sent; the fresh session sat at an empty prompt
// until a supervisor typed it by hand at 13:31. So the one state whose loss
// strands a session -- await-ready after a restart that RAN -- is persisted,
// and restored at runner start if it is still recent. Every other phase stays
// in memory (losing it is safe, see guardStates).
const PENDING_RESUME_PATH = join(PROJECT_ROOT, 'store', 'context-guard-pending-resume.json')
// An entry older than this is dropped at restore instead of resumed: by then
// the ready timeout and one full sweep have passed, and the session has been
// working (or been resumed by hand) long enough that a "continue from your
// handoff" prompt would land in the middle of something else.
export const PENDING_RESUME_MAX_AGE_MS = READY_TIMEOUT_MS + INTERVAL_MS
export interface PendingResume {
  restartedAtMs: number
  deadlineMs: number
  handoffStaleMinutes: HandoffStaleness
}
type PendingResumeMap = Record<string, PendingResume>

function readPendingResumes(): PendingResumeMap {
  try {
    const parsed = JSON.parse(readFileSync(PENDING_RESUME_PATH, 'utf-8'))
    return (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) ? parsed as PendingResumeMap : {}
  } catch { return {} }
}

function writePendingResumes(map: PendingResumeMap): void {
  try {
    const tmp = `${PENDING_RESUME_PATH}.tmp`
    writeFileSync(tmp, JSON.stringify(map, null, 2))
    renameSync(tmp, PENDING_RESUME_PATH)
  } catch (err) {
    logger.warn({ err }, 'context-guard: pending-resume persist failed')
  }
}

/** Record a restart that ran: the fresh session still needs its resume. */
function recordPendingResume(name: string, state: GuardState, nowMs: number): void {
  const map = readPendingResumes()
  map[name] = { restartedAtMs: nowMs, deadlineMs: state.deadlineMs, handoffStaleMinutes: state.handoffStaleMinutes }
  writePendingResumes(map)
}

/** Forget the entry once the agent is in any phase but await-ready. */
function clearPendingResume(name: string): void {
  const map = readPendingResumes()
  if (!(name in map)) return
  delete map[name]
  writePendingResumes(map)
}

/** Every guardStates write goes through here, so the persisted entry can
 *  never outlive the await-ready phase it describes. */
function setGuardState(name: string, state: GuardState): void {
  guardStates.set(name, state)
  if (state.phase !== 'await-ready') clearPendingResume(name)
}

/**
 * Which persisted entries a starting runner restores, as await-ready states.
 * Pure, for the test: an entry is restored only while it is younger than
 * PENDING_RESUME_MAX_AGE_MS and not from the future (a clock step or a
 * hand-edited file must not pin an agent in await-ready).
 */
export function pendingResumesToRestore(map: PendingResumeMap, nowMs: number): Array<[string, GuardState]> {
  const out: Array<[string, GuardState]> = []
  for (const [name, e] of Object.entries(map)) {
    if (!e || typeof e.restartedAtMs !== 'number' || typeof e.deadlineMs !== 'number') continue
    const age = nowMs - e.restartedAtMs
    if (age < 0 || age > PENDING_RESUME_MAX_AGE_MS) continue
    const stale = e.handoffStaleMinutes
    out.push([name, {
      ...INITIAL_GUARD_STATE,
      phase: 'await-ready',
      deadlineMs: e.deadlineMs,
      handoffStaleMinutes: typeof stale === 'number' || stale === 'unknown' ? stale : null,
    }])
  }
  return out
}

function restorePendingResumes(nowMs: number): void {
  const map = readPendingResumes()
  const restore = pendingResumesToRestore(map, nowMs)
  for (const [name, state] of restore) guardStates.set(name, state)
  const kept = new Set(restore.map(([n]) => n))
  const dropped = Object.keys(map).filter((n) => !kept.has(n))
  if (dropped.length > 0) {
    for (const n of dropped) delete map[n]
    writePendingResumes(map)
  }
  if (restore.length > 0 || dropped.length > 0) {
    logger.info({ restored: [...kept], dropped }, 'context-guard: pending resumes restored after a dashboard restart')
  }
}

function sessionFor(name: string): string {
  return name === MAIN_AGENT_ID ? MAIN_CHANNELS_SESSION : agentSessionName(name)
}

function workingDirFor(name: string): string {
  return name === MAIN_AGENT_ID ? PROJECT_ROOT : agentDir(name)
}

function handoffPathFor(name: string): string {
  return join(workingDirFor(name), 'HANDOFF.md')
}

function handoffMtime(name: string): number | null {
  try { return statSync(handoffPathFor(name)).mtimeMs } catch { return null }
}

export function handoffPrompt(pctRound: number, handoffPath: string): string {
  return (
    `[CONTEXT-GUARD] A munkakontextusod ~${pctRound}%-on van -- kritikus. ` +
    `NE folytasd a feladatot. EGYETLEN dolgod ebben a körben: írj HANDOFF.md-t a /handoff skill struktúrája szerint ide: ${handoffPath} ` +
    `(purpose: a folyamatban lévő feladat folytatása friss kontextusban; Goal / Current Progress / What Worked / What Didn't Work / Next Steps szekciók, ` +
    `konkrét fájl-útvonalakkal és kanban kártya-azonosítókkal). Ha nincs aktív feladatod, írd bele hogy nincs. ` +
    `Utána ÁLLJ MEG -- a rendszer friss kontextussal újraindít és a HANDOFF.md-ből folytatod.`
  )
}

/**
 * Handoff request for the idle-flush tier.
 *
 * Separate wording from handoffPrompt on purpose. That one tells an agent its
 * context is critical and to drop what it is doing, which is true at 90% of the
 * window and false here: this tier only ever fires on a session that has been
 * quiet for the configured idle period, so there is nothing in flight to drop.
 * Reusing the alarming text would push an idle agent into treating a routine
 * housekeeping restart as an emergency.
 */
export function idleFlushHandoffPrompt(tokens: number, idleMinutes: number, handoffPath: string): string {
  return (
    `[CONTEXT-GUARD] Rutin karbantartás, nem vészhelyzet. A sessionöd kontextusa ~${Math.round(tokens / 1000)}k token, ` +
    `és ${idleMinutes} perce nincs benne aktivitás, ezért friss kontextussal indítalak újra -- így olcsóbb és gyorsabb lesz a következő kör. ` +
    `EGYETLEN dolgod: írj HANDOFF.md-t a /handoff skill struktúrája szerint ide: ${handoffPath} ` +
    `(Goal / Current Progress / What Worked / What Didn't Work / Next Steps, konkrét fájl-útvonalakkal és kanban kártya-azonosítókkal). ` +
    `Ha nincs félbehagyott feladatod, írd bele hogy nincs -- az is teljes értékű válasz. ` +
    `Utána ÁLLJ MEG; a rendszer újraindít és a HANDOFF.md-ből folytatod.`
  )
}

/**
 * Handoff request for the daily tier.
 *
 * A fourth wording, for the same reason the idle tier needed a third: this
 * agent's context is not critical (the act tier would have fired) and not
 * expensive (the idle tier would have), so both of those texts would state
 * something untrue about its session. What IS true is the only thing this
 * prompt claims: the scheduled restart is about to happen, and whatever is
 * not written down will not survive it.
 */
export function dailyHandoffPrompt(atTime: string, handoffPath: string): string {
  return (
    `[CONTEXT-GUARD] Ütemezett napi újraindítás (${atTime}), nem vészhelyzet és nem hiba. ` +
    `A sessionöd hamarosan friss kontextussal indul újra, és ami nincs leírva, az nem éli túl. ` +
    `EGYETLEN dolgod ebben a körben: írj HANDOFF.md-t a /handoff skill struktúrája szerint ide: ${handoffPath} ` +
    `(Goal / Current Progress / What Worked / What Didn't Work / Next Steps, konkrét fájl-útvonalakkal és kanban kártya-azonosítókkal). ` +
    `Ha nincs félbehagyott feladatod, írd bele hogy nincs -- az is teljes értékű válasz. ` +
    `Utána ÁLLJ MEG; a rendszer újraindít és a HANDOFF.md-ből folytatod.`
  )
}

/**
 * A handoff refresh request: the agent DID write a handoff, then kept working,
 * so the artifact no longer covers the session. Distinct wording from both
 * other requests -- "write a handoff" would read as a bug ("I already did"),
 * and the critical-context alarm may be false here.
 */
export function staleRefreshHandoffPrompt(staleMinutes: number, handoffPath: string): string {
  return (
    `[CONTEXT-GUARD] A HANDOFF.md-d megvan, de az írása óta ~${staleMinutes} perc érdemi munka történt, ` +
    `tehát a mostani állapotot MÁR NEM fedi (döntések, verdiktek, üzenetváltások hiányoznak belőle). ` +
    `EGYETLEN dolgod ebben a körben: frissítsd a HANDOFF.md-t itt: ${handoffPath} úgy, hogy a legutóbbi munkát is tartalmazza ` +
    `(mi dőlt el, mi került leadásra, mi a következő lépés). Utána ÁLLJ MEG -- a rendszer friss kontextussal újraindít és ebből folytatod.`
  )
}

export function resumePrompt(
  name: string,
  handoffPath: string,
  hadHandoff: boolean,
  staleMinutes: HandoffStaleness = null,
): string {
  const base =
    // Wording covers both tiers that lead here: "grew too large" is true at the
    // act threshold and true of an idle-flush, where the context was heavy but
    // the window was nowhere near full. "megtelt" would be false in that case.
    `[CONTEXT-GUARD] Friss kontextussal indultál, mert az előző session kontextusa túl nagyra nőtt (auto-handoff). `
  const source = !hadHandoff
    ? `HANDOFF.md nem készült el időben, ezért az élő forrásokból dolgozz. `
    : staleMinutes === 'unknown'
      // A missing measurement must not impersonate a fresh one: say that the
      // freshness was unverifiable, so the agent cross-checks instead of
      // trusting the artifact blindly.
      ? `Első lépés: olvasd be ${handoffPath} -- ez az előző session átadója, de a FRISSESSÉGÉT NEM TUDTAM MEGMÉRNI. ` +
        `Kezeld óvatosan: vesd össze a kanban-kommentekkel és az inter-agent üzenetekkel, mielőtt a Next Steps-e szerint cselekednél. `
      : typeof staleMinutes === 'number' 
      // A stale handoff presented as current re-opens already-decided
      // questions; say the gap out loud and route the agent to the live
      // sources FIRST for the uncovered window.
      ? `Első lépés: olvasd be ${handoffPath} -- ez az előző session átadója, DE ELAVULT: az utolsó ~${staleMinutes} perc munkája NINCS benne. ` +
        `A hiányzó szakaszt az élő forrásokból pótold (kanban-kommentek, inter-agent üzenetek, hot memóriák), MIELŐTT a handoff Next Steps-e szerint cselekednél. `
      : `Első lépés: olvasd be ${handoffPath} -- ez az előző session átadója. `
  return (
    base + source +
    `Utána ellenőrizd a kanban tábládat (in_progress kártyák, assignee=${name}) és a hot memóriáidat, ` +
    `és FOLYTASD a megkezdett munkát magadtól. Ne kezdd elölről ami a handoff szerint már kész. ` +
    `Ha repo-munkád volt folyamatban, a worktree-ben nézd meg a git status-t (külön recovery-brief ezen az úton nem jön). ` +
    // ORSICTX912: msg 23670 was delivered SEVEN SECONDS after the guard kill
    // started, into the dying session -- the queue marked it delivered, the
    // fresh session had no reason to look, so the loss is invisible from the
    // queue. The re-read must ride in the resume prompt (the fresh session's
    // only context), and it needs an OBSERVABLE trace. The trace is the close
    // of the row (PUT sets completed_at and keeps the result), NOT an ack
    // message: every ack wakes the sender for a turn, and on 2026-10-21 the
    // acks were 312 of 2926 queue rows in 20 hours (10.7%), many of them acks
    // of acks (Klodel 12739).
    `RESTART-ABLAK: az előző session utolsó ~15 percében kézbesített inter-agent üzenet elveszhetett. ` +
    `Olvasd vissza a saját sorodat erre az ablakra (GET /api/messages?agent=${name}, created_at szerint szűrve), ` +
    `és minden ott talált, még el nem intézett kérést kezelj újként. MEGFIGYELHETŐ NYOM: minden visszaolvasott, ` +
    `még nem lezárt tételt zárj le (PUT /api/messages/<id>, status done, a result mezőben "[RESTART-ABLAK] felvéve ` +
    `a friss sessionben" és hogy mi lett vele) -- a lezárás (completed_at + result) a sorban látható nyom. ` +
    `Külön nyugta-üzenetet a feladónak NE küldj: minden nyugta felébreszti a címzettet. notify:true csak akkor, ` +
    `ha a feladó az eredményre vár; ami már lezárt, abból nincs teendő. ` +
    // RESPAWNZAJ822/PRODFAAG822: a fresh session acting on a resume goal is
    // exactly the actor that branch-switched and committed on the live prod
    // tree (2026-08-22 10:10, PR #1036 duplicate). The constraint must ride in
    // the resume prompt itself -- it is the ONLY context the fresh session has.
    `KORLÁT: a futó prod fán (a repo fő checkoutján) NE válts ágat, NE commitolj és NE nyiss belőle PR-t ` +
    `-- ha repo-munka kell, használj worktree-t (git worktree add). ` +
    // The main agent's channel is the OWNER's channel (Telegram), and session
    // meta must never go there (standing owner preference; a 3am status
    // notice measured on 2026-08-05, review msg 14197). Sub-agents' channel
    // is the inter-agent queue, where the notice belongs. This prompt is the
    // fresh session's ONLY rule set, so the split must live here.
    (name === MAIN_AGENT_ID
      ? `Zárásul egyetlen transzkript-sorban rögzítsd, hogy friss kontextussal folytatod -- a csatornádra (a gazda Telegramjára) session-meta NEM mehet ki.`
      : `Röviden jelezz a csatornádon, hogy friss kontextussal folytatod.`)
  )
}

/** Raw observed context size (tokens) for the idle-flush tier's absolute threshold. */
export function measureContextTokens(name: string): number | null {
  const tokens = readContextTokensFromProjectDir(workingDirFor(name), configDirFor(name))
  return tokens !== null && tokens > 0 ? tokens : null
}

/**
 * How long the session's transcript has been untouched (ms), or null when
 * unmeasurable. A negative reading (transcript mtime in the future, e.g. after
 * a clock change) is treated as "just now" rather than as a large idle time --
 * a wrong clock must not be able to trigger a flush.
 */
export function measureIdleMs(name: string, nowMs: number): number | null {
  const mtime = readTranscriptMtimeFromProjectDir(workingDirFor(name), configDirFor(name))
  if (mtime === null) return null
  return Math.max(0, nowMs - mtime)
}

export function measurePct(name: string, cfgLimit: number | null): number | null {
  const workingDir = workingDirFor(name)
  const configDir = configDirFor(name)
  const tokens = readContextTokensFromProjectDir(workingDir, configDir)
  if (tokens === null || tokens <= 0) return null
  let limit: number
  if (cfgLimit) {
    limit = cfgLimit
  } else {
    const model = (name === MAIN_AGENT_ID
      // Same root as the token read above: the model decides the context LIMIT,
      // so a model read from a stale root produces a wrong pct from a right
      // token count -- and pct is what the handoff threshold compares.
      ? readActiveModelFromProjectDir(PROJECT_ROOT, undefined, configDirFor(name))
      : readAgentModel(name)) ?? ''
    // Calibrate against the persisted per-(agent, model) maximum, not just
    // the live reading: a fresh post-restart session must not un-learn a
    // window the previous session already proved (see HighwaterMap above).
    limit = calibrateLimit(observedHighwater(name, model, tokens), contextLimitForModel(model))
  }
  return tokens / limit
}

async function performRestart(name: string): Promise<void> {
  if (name === MAIN_AGENT_ID) {
    // Platform-correct main-session restart. This was a hardcoded
    // `/bin/launchctl kickstart`, which exists only on macOS: on Linux every
    // rescue died instantly with `spawnSync /bin/launchctl ENOENT`, caught by
    // checkAgent's catch and buried in a single WARN. Measured on 2026-07-26:
    // the main agent sat at 100% context from 09:47, the saturation net -- the
    // only mechanism that can rescue a pane prompt dispatch refuses -- fired
    // four times and failed every time, and main was unreachable for ~2h until
    // a hand restart.
    //
    // hardRestartMarveenChannels() is the existing helper the channel-monitor
    // down-cascade already uses: it keeps the launchd path for macOS installs
    // (and warns + falls back to a pane respawn if the plist is absent), uses
    // respawn-pane-FRESH on Linux -- fresh is exactly what the guard wants --
    // and writes the shared respawn stamp so the other respawners defer to us.
    const res = hardRestartMarveenChannels()
    if (!res.ok) throw new Error(res.error ?? 'main channels hard restart failed')
  } else {
    // DANICTXHUROK906: claim the reconcile grace window BEFORE the stop, so
    // reconcileDesiredAgents() does not see the agent "down" mid-restart and
    // re-launch it non-fresh (--continue), which would defeat the whole point
    // of a context-guard restart -- dropping the saturated context.
    markAgentRestartPending(name)
    // The result was discarded here until 2026-09-01. startAgentProcess has an
    // early "Agent is already running" return, and a supervisor that started
    // the agent inside our stop window (restart-lock.ts) trips it -- so the
    // rescue reported success while the pane still held the saturated session
    // it was supposed to drop. Measured twice on levente, 2026-08-31 19:10 and
    // 19:41; the second restart WAS the first one's unnoticed failure.
    // brief: false -- the inject-resume below is this door's recovery prompt;
    // the generic recovery-brief on top of it doubled the first turn.
    const res = await restartAgentProcess(name, { fresh: true, brief: false })
    if (!res.ok) throw new Error(res.error ?? 'agent restart failed')
  }
}

/**
 * 'sweep' = the full five-minute decision. 'fast' = C106C3FF's fast round: the
 * same measurement and the same decideGuard, but only for an agent already in
 * await-handoff, and only a 'restart' decision confirmed by FAST_IDLE_CONFIRM
 * consecutive idle readings is acted on; anything else is dropped (state
 * untouched), so the full sweep keeps every other transition.
 */
type CheckMode = 'sweep' | 'fast'

async function checkAgent(name: string, nowMs: number, mode: CheckMode = 'sweep'): Promise<void> {
  const cfg = readContextGuardConfig(name)
  const state = guardStates.get(name) ?? INITIAL_GUARD_STATE
  if (state.phase !== 'await-handoff') fastIdleStreak.delete(name)
  if (mode === 'fast' && !FAST_ROUND_PHASES.has(state.phase)) return

  // Fully disarmed only when EVERY tier and the always-on saturation net are
  // off; the net alone keeps the sweep alive so a 100%-context pane (which
  // dispatch refuses to prompt) still gets rescued.
  //
  // Every tier that can act has to appear in this list. This is the THIRD
  // copy of the same condition (decideGuard's short-circuit and its
  // await-handoff stand-down are the other two), and the daily tier was
  // missing from exactly this one: an operator who turned the saturation net
  // off and the daily tier on would have been skipped here, before
  // decideGuard ever saw the agent, with no log line to say so.
  if (!cfg.enabled && !cfg.saturationRestart && !cfg.idleFlushEnabled && !cfg.dailyHandoffEnabled) {
    guardStates.delete(name)
    clearPendingResume(name)
    return
  }

  // v1: local agents only -- a remote host's transcripts are unreadable here.
  if (name !== MAIN_AGENT_ID && readAgentRemoteHost(name)) {
    if (!remoteSkipLogged.has(name)) {
      remoteSkipLogged.add(name)
      logger.info({ name }, 'context-guard: remote-host agent, skipping (transcripts not local)')
    }
    return
  }

  const session = sessionFor(name)
  const running = name === MAIN_AGENT_ID
    ? capturePane(session) !== null
    : agentRunState(name) === 'running'

  // Only pay for the tmux/transcript probes a decision can actually use.
  // 'cooldown' too (CGGAPS1013): a fresh session can cross the act band
  // inside the cooldown, and decideGuard needs pct + idleMs to see it.
  const needPct = state.phase === 'idle' || state.phase === 'await-handoff' || state.phase === 'cooldown'
  const pane = running && needPct ? capturePane(session) : null
  const sessionReady = running && state.phase === 'await-ready'
    ? await isSessionReadyForPrompt(session)
    : false
  // One classification, two distinct signals: 'idle' (safe to restart) and
  // 'busy' (positively mid-turn -- restarts defer). A pane that is neither
  // (error banner, modal, unknown surface) is treated as NOT busy, so a
  // wedged pane still gets the restart that is its only way out.
  const { paneState, guardPaneState, bgAgents } = guardPaneSignals(pane)
  if (bgAgents > 0 && paneState !== 'busy' && !bgAgentDeferLogged.has(name)) {
    bgAgentDeferLogged.add(name)
    logger.info({ name, bgAgents, paneState }, 'context-guard: background agents running -- the pane counts as busy, restarts defer until they finish')
  } else if (bgAgents === 0) {
    bgAgentDeferLogged.delete(name)
  }

  // The pane banner and the calibrated measurement are TWO signals about one
  // fact, and this sweep is the only place that holds both. Reconciling them
  // HERE leaves decideGuard's contract intact ("paneSaturated means the pane
  // really is saturated") and lets all three consumers of the signal -- the net
  // below, agent-process.ts's dispatch gate and schedule-runner.ts's forceSend
  // deferral -- act on ONE verdict.
  const paneSaturatedRaw = pane !== null ? paneShowsContextSaturation(pane) : false
  // Only a PERCENTAGE claim can be contradicted by a measurement; an
  // error-shaped banner is painted after a turn actually failed at the real
  // limit and is final (see saturationBannerCredible). So the error case needs
  // no probe at all -- which also keeps the promise above this function: the
  // transcript probe is paid for only where a decision can use it. That matters
  // beyond CPU here, because measurePct persists a per-agent high-water mark to
  // store/context-guard-highwater.json; with cfg.enabled false and no banner up
  // we write exactly as little as before this change.
  const bannerIsHardError = pane !== null && paneShowsContextSaturationHardError(pane)
  const needCredibilityProbe = paneSaturatedRaw && !bannerIsHardError
  const measuredPct = running && needPct && (cfg.enabled || needCredibilityProbe)
    ? measurePct(name, cfg.limitTokens)
    : null
  const paneSaturatedTrusted = saturationBannerCredible(paneSaturatedRaw, bannerIsHardError, measuredPct)
  if (paneSaturatedRaw && !paneSaturatedTrusted) {
    noteSaturationBannerUntrusted(session, nowMs + SATURATION_OVERRIDE_TTL_MS)
    if (!bannerMismatchLogged.has(name)) {
      bannerMismatchLogged.add(name)
      logger.warn(
        {
          name,
          session,
          pct: measuredPct !== null ? Math.round(measuredPct * 100) : null,
          thresholdPct: Math.round(SATURATION_CREDIBLE_MIN_PCT * 100),
          limitTokens: cfg.limitTokens,
          // The actionable field: this is what says WHAT to fix. Same branch as
          // measurePct's, and it only runs on this rare state change.
          model: (name === MAIN_AGENT_ID
            ? readActiveModelFromProjectDir(PROJECT_ROOT, undefined, configDirFor(name))
            : readAgentModel(name)) ?? null,
        },
        // Fleet-side checks should match on the fields above (name, model, pct,
        // thresholdPct), never on this wording: the message is prose and may be
        // reworded, the fields are the contract.
        'context-guard: pane claims context saturation but the measured context contradicts it -- NOT restarting, and dispatch may keep prompting. Usual cause: the agent model id reaches the CLI without the `[1m]` marker, so the CLI sizes its status line to 200k.',
      )
    }
  } else if (pane !== null) {
    // Only a sweep that actually LOOKED at the pane may revoke the override.
    // paneSaturatedRaw is also false when we never captured (the await-ready and
    // cooldown phases leave pane === null), and "we did not look" is not
    // evidence that the banner is gone. The TTL still expires it fail-closed.
    clearSaturationBannerOverride(session)
    if (bannerMismatchLogged.delete(name)) {
      logger.info({ name, session }, 'context-guard: banner and measurement agree again -- the saturation net is live for this agent')
    }
  }

  const inputs: GuardInputs = {
    nowMs,
    running,
    // The proactive tiers own this field, and it stays gated on cfg.enabled
    // exactly as before: the await-handoff `pct >= hardPct` arm and the
    // stale-refresh condition are NOT behind cfg.enabled, so populating it for
    // an unconfigured agent would arm tiers that are quiet there today. The
    // credibility check above therefore reads measuredPct directly.
    pct: cfg.enabled ? measuredPct : null,
    paneIdle: guardPaneState === 'idle',
    paneBusy: guardPaneState === 'busy',
    sessionReady,
    handoffMtime: needPct ? handoffMtime(name) : null,
    // Already reconciled with the measurement above, so decideGuard itself
    // needs no change and every existing net regression test still applies.
    paneSaturated: paneSaturatedTrusted,
    // Context-size probe, paid for only when the idle-flush tier is armed.
    // Note the condition is cfg.idleFlushEnabled, NOT cfg.enabled: the two
    // tiers are independently switchable, so an agent running the idle tier
    // alone must still get its measurements.
    contextTokens: running && needPct && cfg.idleFlushEnabled ? measureContextTokens(name) : null,
    // idleMs is NOT gated on the idle-flush tier: the handoff-staleness check
    // (handoffStaleMinutes) needs the transcript mtime on every decision path
    // that can restart, and the probe is a single stat().
    idleMs: running && needPct ? measureIdleMs(name, nowMs) : null,
    // Seed-on-first-ARMED-sight, and forget-while-disarmed on every sweep:
    // dailyHandoffSweep decides both, applyDailyHandoffSweep applies the record.
    // The fast round only ever sees await-handoff, so it passes eligible=false
    // here: the record is kept (armed) or forgotten (disarmed), exactly as the
    // full sweep would do, and nothing is ever due from a fast round.
    dailyHandoffDue: applyDailyHandoffSweep(lastDailyHandoff, name, cfg, running && state.phase === 'idle', localMidnightMs(nowMs), nowMs),
  }

  // L2 (Viktor 2453): a cooldown may end early (CGGAPS1013), but never twice
  // in a row. A fresh session whose BASE context already sits above actPct (a
  // limit set too low) would otherwise loop restart -> early exit -> restart
  // every few minutes; the second cooldown in such a chain runs its full
  // length, and the chain is logged loudly.
  const earlyBlocked = state.phase === 'cooldown' && (earlyCooldownExits.get(name) ?? 0) >= 1
  const decision = decideGuard(state, earlyBlocked ? { ...inputs, pct: null } : inputs, cfg)

  if (mode === 'fast') {
    const streak = guardPaneState === 'idle' ? (fastIdleStreak.get(name) ?? 0) + 1 : 0
    fastIdleStreak.set(name, streak)
    if (!fastRoundActs(decision.action, streak, inputs.sessionReady)) return
  }
  if (state.phase === 'cooldown') {
    if (decision.action !== 'none') {
      earlyCooldownExits.set(name, (earlyCooldownExits.get(name) ?? 0) + 1)
      logger.warn({ name, reason: decision.reason, pct: inputs.pct }, 'context-guard: cooldown ended early (the next cooldown in this chain will run its full length)')
    } else if (decision.nextState.phase !== 'cooldown') {
      earlyCooldownExits.delete(name)
    } else if (earlyBlocked && inputs.pct !== null && inputs.pct >= cfg.actPct && !earlyBlockLogged.has(name)) {
      earlyBlockLogged.add(name)
      logger.warn({ name, pct: inputs.pct, limitTokens: cfg.limitTokens }, 'context-guard: second early cooldown exit in a row refused -- is limitTokens below this agent\'s base context?')
    }
    if (decision.nextState.phase !== 'cooldown') earlyBlockLogged.delete(name)
  }

  // Mark the slot served at DECISION time, not after the prompt lands. If the
  // directive fails to send, the machine is already in await-handoff and its
  // timeout force-restarts the agent anyway -- the slot really was consumed.
  // Marking it later would let a send failure re-fire the tier every sweep
  // until midnight.
  if (decision.reason.startsWith(DAILY_HANDOFF_REASON_PREFIX)) {
    lastDailyHandoff.set(name, nowMs)
  }

  // Post-respawn grace for the main session. Making the Linux restart path work
  // (above) also makes it repeatable: measured on 2026-07-26, the saturation net
  // fresh-restarted main five times in one morning, so the agent lost its
  // conversation roughly every half hour. Two causes of a redundant restart,
  // both covered by the same stamp: a session that is still BOOTING can read as
  // saturated/idle again on the next sweep, and ANOTHER respawner (the
  // channel-monitor down-cascade, the auto-restart runner, channel-watchdog.sh)
  // may have just restarted main for its own reasons.
  //
  // Same mechanism every other respawner already shares -- lastMainRespawnAt()
  // plus MARVEEN_POST_RESPAWN_GRACE_MS -- so there is no new tunable and no new
  // number; see the identical gate in stuck-tool-call-watcher.ts. Main only: the
  // stamp describes the main channels session, and a sub-agent restart is
  // cheap and independently coordinated.
  //
  // The state must NOT advance here. decideGuard() has already produced
  // nextState = await-ready; committing that while skipping the restart would
  // leave the machine believing main was restarted, and the next sweep would
  // inject a "continue from your handoff" resume prompt into the SAME saturated
  // pane -- the guard would consume its own recovery and never retry. Keeping
  // the previous state means the next sweep re-decides, and the restart happens
  // once the grace has elapsed.
  if (decision.action === 'restart' && name === MAIN_AGENT_ID) {
    const lastRespawn = lastMainRespawnAt()
    if (shouldDeferForRecentRespawn(lastRespawn, nowMs)) {
      logger.info(
        { name, sinceRespawnMs: lastRespawn ? nowMs - lastRespawn : null, graceMs: MARVEEN_POST_RESPAWN_GRACE_MS },
        'context-guard: recent main respawn within grace, deferring restart (avoid restart loop / boot churn)',
      )
      setGuardState(name, state)
      return
    }
  }

  setGuardState(name, decision.nextState)
  if (decision.action === 'none') {
    // Idle-flush non-decisions carry the measurement that blocked them
    // ("quiet for only 4m of 20m"), which is the only way to see the tier
    // failing to reach its threshold. It matters because the idle clock is the
    // transcript mtime and a SCHEDULED wake resets it: an agent whose schedule
    // period is shorter than idleMinutes can never accumulate enough quiet, and
    // without this line that reads as "the tier is fine, nothing to flush".
    if (decision.reason.startsWith(IDLE_FLUSH_REASON_PREFIX)) {
      logger.debug(
        { name, reason: decision.reason, contextTokens: inputs.contextTokens, idleMs: inputs.idleMs },
        'context-guard: idle-flush not acting',
      )
    }
    return
  }

  const pctRound = inputs.pct !== null ? Math.round(inputs.pct * 100) : null
  logger.info({ name, mode, action: decision.action, reason: decision.reason, pct: pctRound, bannerRaw: paneSaturatedRaw, bannerTrusted: paneSaturatedTrusted, measuredPct: measuredPct !== null ? Math.round(measuredPct * 100) : null }, 'context-guard: acting')

  try {
    switch (decision.action) {
      case 'request-handoff': {
        // GUARDHITELES903: through the authenticated-directive primitive, not
        // bare sendPromptToSession -- this text asks the agent to drop work
        // and STOP, which without a queue anchor is indistinguishable from a
        // prompt injection (measured 2026-09-03: Boni correctly refused it).
        // M1 (Viktor 2453): emitGuard -- never type into a permission prompt,
        // first-run gate, blocking menu or unreadable pane (text + Enter would
        // answer the prompt with its preselected "Yes"). The busy-pane request
        // (hard+busy) is exactly the case where one can open during the idle
        // wait. Nothing typed -> the anchor row is marked failed and the
        // await-handoff timeout stays the fallback.
        // C106C3FF: a resend repeats the original request's wording, so the
        // prompt is chosen by THAT reason, not by the resend's own.
        const promptReason = decision.reason.startsWith(HANDOFF_RESEND_REASON_PREFIX)
          ? (state.requestReason ?? '')
          : decision.reason
        // Whether the request went into a pane still busy after the idle wait.
        let sentBestEffort = false
        const handoffOutcome = await sendSystemDirective(
          name,
          session,
          promptReason.startsWith(STALE_REFRESH_REASON_PREFIX)
            // The handoff exists but went stale while we waited for an idle
            // pane; ask for a refresh, not a first write.
            ? staleRefreshHandoffPrompt(((sm) => typeof sm === 'number' ? sm : 0)(handoffStaleMinutes(inputs)), handoffPathFor(name))
            : promptReason.startsWith(IDLE_FLUSH_REASON_PREFIX)
              // pct is null whenever the idle tier runs without the proactive
              // tiers, so the alarming percentage-based prompt would read "~0%
              // -- critical". The idle tier states the token count it measured.
              ? idleFlushHandoffPrompt(inputs.contextTokens ?? 0, cfg.idleMinutes, handoffPathFor(name))
              : promptReason.startsWith(DAILY_HANDOFF_REASON_PREFIX)
                // Same trap as the idle tier: pct is null for a daily-only
                // agent, so the percentage prompt would announce "~0% --
                // critical" at 04:00 to a session that is perfectly healthy.
                ? dailyHandoffPrompt(cfg.dailyHandoffTime ?? '', handoffPathFor(name))
                : handoffPrompt(pctRound ?? 0, handoffPathFor(name)),
          null,
          { emitGuard: urgentEmitRefusal, onBusySend: () => { sentBestEffort = true } },
        )
        if (handoffOutcome === 'aborted-guard') {
          logger.warn({ name, reason: decision.reason }, 'context-guard: handoff request NOT typed -- the pane holds a prompt/menu or is unreadable (emit guard)')
        }
        // C106C3FF: remember an unclean delivery, so await-handoff can resend
        // once (decideGuard, MAX_HANDOFF_RESENDS) when the pane goes idle with
        // no handoff written. Only while the state is still the one this
        // decision produced.
        const unclean = handoffOutcome === 'aborted-guard' || (handoffOutcome === 'sent' && sentBestEffort)
        const now = guardStates.get(name)
        if (unclean && now?.phase === 'await-handoff') {
          setGuardState(name, { ...now, requestUnconfirmed: true })
          logger.info({ name, outcome: handoffOutcome, bestEffort: sentBestEffort }, 'context-guard: handoff request not cleanly delivered -- one resend armed for when the pane is idle')
        }
        break
      }
      case 'restart': {
        // A forced restart must never be silent: the supervisor has to know
        // that prompts delivered to the OLD session (queued steering input,
        // parked text, the handoff request itself) may have died with it
        // (2026-07-27: two dispatched instructions lost this way). Snapshot
        // the pane first for post-mortem, then restart, then report on the
        // inter-agent queue -- the channel supervisors actually read.
        let snapshotPath: string | null = null
        try {
          const finalPane = pane ?? capturePane(session)
          if (finalPane) {
            snapshotPath = join(PROJECT_ROOT, 'store', `context-guard-last-pane-${name}.txt`)
            writeFileSync(snapshotPath, finalPane)
          }
        } catch (err) {
          logger.warn({ err, name }, 'context-guard: pre-restart pane snapshot failed')
        }
        try {
          await performRestart(name)
          // The streak is over: only a rescue that actually ran clears it.
          clearRescueFailures(name)
          // CGRESUME1021: from here on the fresh session needs its resume, and
          // a dashboard restart must not lose that.
          recordPendingResume(name, decision.nextState, nowMs)
        } catch (err) {
          // guardStates was advanced to the post-restart phase BEFORE this
          // switch, so a failed rescue would otherwise be filed as a completed
          // one: the guard would wait for a session it never started, inject a
          // resume prompt into the old saturated pane, and then sit out its
          // cooldown. Roll the state back so the next sweep re-measures and
          // retries, and never claim the restart on the message queue.
          setGuardState(name, INITIAL_GUARD_STATE)
          const { count, alert: shouldAlert } = recordRescueFailure(name, nowMs)
          logger.error({ err, name, reason: decision.reason, consecutiveFailures: count }, 'context-guard: rescue restart FAILED -- state rolled back for retry')
          // Honest and silent is still silent. A saturated pane cannot be
          // prompted (dispatch refuses it), so an agent whose rescue keeps
          // failing is unreachable, and the only thing that knows is this log
          // line. Escalate on the third consecutive failure, then hourly.
          if (shouldAlert) {
            try {
              // The alert sink must never be the patient's own inbox. For the
              // MAIN agent a queue message would be addressed to the very agent
              // whose rescue keeps failing -- main-agent delivery is pull-based,
              // and a saturated main does not pull, so the alert would sit
              // "pending" exactly when it matters (measured 2026-09-08: main
              // saturated twice that day). Route the main-agent case to the
              // operator notification channel instead.
              if (name === MAIN_AGENT_ID) {
                await notifyChannel(
                  `[CONTEXT-GUARD] ${count}. EGYMAST KOVETO bukott mentes a FO-AGENSNEL (${name}). ` +
                  `Ok: ${decision.reason}` + (pctRound !== null ? ` (kontextus ~${pctRound}%)` : '') +
                  `. Utolso hiba: ${err instanceof Error ? err.message : String(err)}. ` +
                  'A guard kb. 10 percenkent ujraprobalja; ez a riasztas orankent ismetlodik, amig tart.',
                )
              } else {
              const msg = createAgentMessage(
                name,
                MAIN_AGENT_ID,
                `[CONTEXT-GUARD] ${count}. EGYMAST KOVETO bukott mentes a(z) "${name}" agensnel. ` +
                `Ok: ${decision.reason}` + (pctRound !== null ? ` (kontextus ~${pctRound}%)` : '') +
                `. Utolso hiba: ${err instanceof Error ? err.message : String(err)}. ` +
                'A szaturalt pane-t NEM lehet prompttal elerni (a dispatch visszautasitja), tehat ' +
                'ez az agens addig elerhetetlen, amig a restart nem sikerul. A guard kb. 10 percenkent ' +
                'ujraprobalja magatol, es ez a riasztas orankent ismetlodik, amig tart. Amit nezz meg: ' +
                `fut-e a tmux session (agent-${name}), mit mutat a store/context-guard-last-pane-${name}.txt, ` +
                "es a dashboard.log 'rescue restart FAILED' / 'lost the start race' sorai.",
                'context-guard rescue failure alert',
              )
              if (!msg?.id) throw new Error('createAgentMessage returned no id')
              }
            } catch (alertErr) {
              // The alert is the last channel out of a silent failure; losing it
              // without a trace would restore exactly the silence it exists for.
              logger.error({ err: alertErr, name, consecutiveFailures: count }, 'context-guard: FAILED TO RAISE the rescue-failure alert')
            }
          }
          break
        }
        try {
          createAgentMessage(
            name,
            MAIN_AGENT_ID,
            `[CONTEXT-GUARD] Ujrainditottam a(z) "${name}" agentet -- ok: ${decision.reason}` +
            (pctRound !== null ? ` (kontextus ~${pctRound}%)` : '') +
            `. A regi sessionbe az utolso percekben kuldott uzenetek/utasitasok ELVESZHETTEK -- ellenorizd es kuldd ujra oket.` +
            (typeof decision.nextState.handoffStaleMinutes === 'number'
              // The generic "messages may be lost" line invites the wrong
              // conclusion when the real gap is the ARTIFACT: say explicitly
              // that the handoff does not cover the tail of the session.
              ? ` FIGYELEM: a HANDOFF.md ELAVULT -- az utolso ~${decision.nextState.handoffStaleMinutes} perc munkaja nincs benne, a friss session ezt a szakaszt az elo forrasokbol kapja meg.`
              : decision.nextState.handoffStaleMinutes === 'unknown'
                // The supervisor's manual state-handoff decision runs on this
                // line (2026-08-17: a hand-measured mtime saved a payment-PR
                // verdict); a silent unknown would read as "all fine" to the
                // one reader who could compensate.
                ? ` FIGYELEM: a HANDOFF.md letezik, de a FRISSESSEGET NEM TUDTAM MERNI (transcript-ora olvashatatlan) -- ha a session-ben friss dontes szuletett, kezi allapot-ellenorzes ajanlott (mtime vs. utolso munka).`
                : '') +
            (snapshotPath ? ` Pane-snapshot a restart elotti allapotrol: ${snapshotPath}` : ''),
            'context-guard restart notice',
          )
        } catch (err) {
          logger.warn({ err, name }, 'context-guard: restart notice message failed')
        }
        break
      }
      case 'inject-resume': {
        const hadHandoff = inputs.handoffMtime !== null || handoffMtime(name) !== null
        // Staleness was measured at RESTART time and rode here in the state;
        // measuring now would be meaningless (the old session is gone).
        // GUARDHITELES903: anchored like the handoff request -- the resume
        // prompt steers a fresh session's entire first turn.
        // M1 (Viktor 2453): same emit guard. After a ready timeout nothing
        // else gates this send, and a fresh session that went straight to
        // work may be sitting on a permission prompt (e.g. a write to its own
        // ~/.claude). Nothing typed -> stay in await-ready: its deadline has
        // passed, so the next sweep tries again; the guard never cools down
        // on a resume that did not land.
        const resumeOutcome = await sendSystemDirective(
          name,
          session,
          resumePrompt(name, handoffPathFor(name), hadHandoff, state.handoffStaleMinutes),
          null,
          { emitGuard: urgentEmitRefusal },
        )
        if (resumeOutcome === 'aborted-guard') {
          setGuardState(name, state)
          logger.warn({ name }, 'context-guard: resume NOT typed -- the pane holds a prompt/menu or is unreadable (emit guard); retrying next sweep')
        }
        break
      }
    }
  } catch (err) {
    logger.warn({ err, name, action: decision.action }, 'context-guard: action failed')
  }
}

/** Live status for the dashboard/API. */
export function getContextGuardStatus(): Array<{
  agent: string
  phase: string
  pct: number | null
  enabled: boolean
  saturationRestart: boolean
  cooldownUntilMs?: number
}> {
  const names = [MAIN_AGENT_ID, ...listAgentNames()]
  return names.map((name) => {
    const state = guardStates.get(name)
    const cfg = readContextGuardConfig(name)
    const remote = name !== MAIN_AGENT_ID && !!readAgentRemoteHost(name)
    return {
      agent: name,
      phase: state?.phase ?? 'idle',
      pct: cfg.enabled && !remote ? measurePct(name, cfg.limitTokens) : null,
      enabled: cfg.enabled,
      saturationRestart: cfg.saturationRestart,
      ...cooldownStatusExtra(state),
    }
  })
}

/** CGBADGE908: in cooldown the UI shows the REMAINING TIME, because that is
 * what the word promises -- the badge used to append the context pct instead,
 * and "cooldown 19%" read as a cooldown position. The field is sent ONLY in
 * the cooldown phase so no consumer mistakes a stale timestamp for a live
 * timer. Exported so the test pins both branches. */
export function cooldownStatusExtra(
  state: { phase: string; cooldownUntilMs: number } | undefined,
): { cooldownUntilMs?: number } {
  return state?.phase === 'cooldown' && state.cooldownUntilMs > 0
    ? { cooldownUntilMs: state.cooldownUntilMs }
    : {}
}

/**
 * Who the saturation net sweeps: the main agent plus EVERY agent directory,
 * dashboard-hidden technical workers included.
 *
 * Deliberately listAllAgentNames(), not listAgentNames(). A hidden worker is
 * hidden from the OPERATOR, not from the fleet's life support: it runs a real
 * Claude session that can wedge at 100% context exactly like a visible agent,
 * and when it does, this sweep is the only thing that can free it. The hourly
 * heartbeat proved it on 2026-08-04 -- agents/heartbeat wedged, was invisible
 * to this sweep, and the schedule runner's (correct) "defer instead of
 * injecting into a wedged session" turned into an unbounded wait.
 *
 * Exported so the regression test can assert the SET rather than reach into a
 * timer: narrowing this back to listAgentNames() must fail a test, not a
 * production heartbeat.
 *
 * Deduplicated, main first. On an install where agents/<MAIN_AGENT_ID> exists
 * as a real directory (ours does) the main agent appears twice -- once
 * explicitly, once from the listing -- and checkAgent would run its whole
 * decision on it twice per sweep. That is exactly the agent where a doubled
 * decision is least welcome, so the canonical "who do we sweep" answer is a
 * set, not a concatenation.
 */
export function guardSweepAgentNames(): string[] {
  return [...new Set([MAIN_AGENT_ID, ...listAllAgentNames()])]
}

/**
 * Current phase of the hard context-guard for this agent. Returns 'idle' when
 * no state has been recorded. The gate runner uses this for its interlock: when
 * the hard guard is in 'await-handoff' or 'await-ready', the soft gate steps
 * aside so both mechanisms never simultaneously touch the pane.
 */
export function getHardGuardPhase(name: string): string {
  return guardStates.get(name)?.phase ?? 'idle'
}

export function startContextGuardRunner(): NodeJS.Timeout {
  // GUARDHOLD1013: while an agent is asked for its handoff, the router keeps new
  // messages pending so the pane can go idle and the restart can happen (see
  // shouldHoldForGuard in message-router.ts); CGHOLDREADY1021: and after the
  // restart, until the resume is in (see guardDeliveryHold).
  setDeliveryHoldCheck(guardDeliveryHold)
  // One flag for both rounds: a full sweep and a fast round never decide the
  // same agent at the same time.
  let tickRunning = false
  async function sweep() {
    // Re-entrancy guard: checkAgent's 'restart' action now awaits a real
    // restartAgentProcess (no longer a blocking execSync('sleep N')), so a
    // sweep with a restart in flight can still be running when the next
    // interval fires. Skip an overlapping tick; the next tick re-evaluates
    // every agent, so nothing is missed.
    if (tickRunning) {
      logger.debug('context-guard: previous sweep still running, skipping this tick')
      return
    }
    tickRunning = true
    try {
      const now = Date.now()
      for (const name of guardSweepAgentNames()) {
        try { await checkAgent(name, now) } catch (err) { logger.debug({ err, agent: name }, 'context-guard: agent check error') }
      }
    } finally {
      tickRunning = false
    }
  }
  // C106C3FF: the fast round (see FAST_INTERVAL_MS). Skips while a full sweep
  // runs; touches only agents already in await-handoff or (CGRESUME1021)
  // await-ready.
  async function fastRound() {
    if (tickRunning) return
    const waiting = guardSweepAgentNames().filter((n) => FAST_ROUND_PHASES.has(getHardGuardPhase(n)))
    if (waiting.length === 0) return
    tickRunning = true
    try {
      const now = Date.now()
      for (const name of waiting) {
        try { await checkAgent(name, now, 'fast') } catch (err) { logger.debug({ err, agent: name }, 'context-guard: fast round check error') }
      }
    } finally {
      tickRunning = false
    }
  }
  // CGRESUME1021: before the first fast round, so a restart that ran just
  // before this dashboard started still gets its resume within ~20 s.
  restorePendingResumes(Date.now())
  setTimeout(sweep, INITIAL_DELAY_MS)
  setInterval(fastRound, FAST_INTERVAL_MS).unref?.()
  return setInterval(sweep, INTERVAL_MS)
}

/** The phases the fast round re-runs: await-handoff (C106C3FF) and
 *  await-ready (CGRESUME1021). */
export const FAST_ROUND_PHASES: ReadonlySet<string> = new Set(['await-handoff', 'await-ready'])

/**
 * The pane as the guard reads it. A background agent dies with the session
 * (Patrik TG 6938, Klodel 16131: four dave subagents lost at 21:15 because the
 * empty box above their panel read idle, which is right for the router since
 * #82). For the guard a running background agent is work in flight: busy, never
 * idle, so every restart path defers exactly as it does for a live turn. The
 * saturation net is a separate signal and still fires.
 */
export function guardPaneSignals(pane: string | null): { paneState: PaneState; guardPaneState: PaneState; bgAgents: number } {
  const paneState: PaneState = pane !== null ? detectPaneState(pane) : 'unknown'
  const bgAgents = pane !== null ? backgroundAgentCount(pane) : 0
  return { paneState, guardPaneState: bgAgents > 0 ? 'busy' : paneState, bgAgents }
}

/** C106C3FF: the fast round acts on a restart decision only after
 *  FAST_IDLE_CONFIRM consecutive idle readings. CGRESUME1021: and on a resume
 *  only into a session isSessionReadyForPrompt confirmed ready -- the
 *  ready-timeout injection (session not ready) stays on the full sweep.
 *  Nothing else. Pure, for the test. */
export function fastRoundActs(action: string, idleStreak: number, sessionReady = false): boolean {
  if (action === 'restart') return idleStreak >= FAST_IDLE_CONFIRM
  return action === 'inject-resume' && sessionReady
}
