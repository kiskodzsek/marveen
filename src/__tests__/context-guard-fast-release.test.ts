// C106C3FF (measured 2026-10-14, Viktor review 2659): three changes to the
// await-handoff phase, pinned here.
//   F1 -- a fast round re-runs ONLY the await-handoff -> restart step, every
//         FAST_INTERVAL_MS, with the same decideGuard, and acts only after two
//         consecutive idle readings; it never types anything.
//   F2 -- a handoff request that was not cleanly delivered (best-effort into a
//         busy pane, or not typed at all) is resent ONCE, through the same
//         authenticated directive, when the pane is idle and no handoff exists.
//   F3 -- the router's hold cap is derived from the agent's own config:
//         handoffTimeoutMinutes + one full sweep + slack.
import { describe, it, expect, vi } from 'vitest'
import { mkdtempSync, readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'
import {
  decideGuard,
  DEFAULT_CONTEXT_GUARD,
  INITIAL_GUARD_STATE,
  HANDOFF_RESEND_REASON_PREFIX,
  MAX_HANDOFF_RESENDS,
  STALE_REFRESH_REASON_PREFIX,
  type ContextGuardConfig,
  type GuardInputs,
  type GuardState,
} from '../context-guard.js'

const SANDBOX = mkdtempSync(join(tmpdir(), 'cgfast-'))
vi.mock('../config.js', async (orig) => {
  const actual = await orig<typeof import('../config.js')>()
  return { ...actual, MAIN_AGENT_ID: 'marveen', PROJECT_ROOT: SANDBOX, STORE_DIR: join(SANDBOX, 'store') }
})
vi.mock('../logger.js', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), debug: vi.fn(), error: vi.fn() },
}))
vi.mock('../db.js', () => ({ createAgentMessage: vi.fn() }))
vi.mock('../web/channel-monitor.js', () => ({
  hardRestartMarveenChannels: vi.fn(() => ({ ok: true })),
  lastMainRespawnAt: () => null,
  MARVEEN_POST_RESPAWN_GRACE_MS: 0,
  markAgentRestartPending: vi.fn(),
}))
vi.mock('../web/stuck-tool-call-watcher.js', () => ({ shouldDeferForRecentRespawn: () => false }))
vi.mock('../web/agent-process.js', () => ({
  clearFeedbackModalAndRecheck: () => false,
  agentRunState: () => 'stopped',
  agentSessionName: (n: string) => `agent-${n}`,
  restartAgentProcess: vi.fn(),
  capturePane: () => null,
  sendPromptToSession: vi.fn(),
  isSessionReadyForPrompt: async () => false,
}))

const { fastRoundActs, guardHoldCapMs, guardDeliveryHold, INTERVAL_MS, FAST_INTERVAL_MS, FAST_IDLE_CONFIRM, GUARD_HOLD_SLACK_MS } =
  await import('../web/context-guard-runner.js')

const here = dirname(fileURLToPath(import.meta.url))
const runner = readFileSync(join(here, '..', 'web', 'context-guard-runner.ts'), 'utf-8')

const CFG: ContextGuardConfig = { ...DEFAULT_CONTEXT_GUARD, enabled: true }
const NOW = 1_000_000_000

function inputs(o: Partial<GuardInputs> = {}): GuardInputs {
  return {
    nowMs: NOW, pct: 0.92, running: true, paneIdle: true, paneBusy: false, sessionReady: false,
    handoffMtime: null, paneSaturated: false, dailyHandoffDue: false, contextTokens: null, idleMs: null, ...o,
  }
}

/** The state right after an act-threshold request: what the runner commits. */
function requested(o: Partial<GuardState> = {}): GuardState {
  const d = decideGuard(INITIAL_GUARD_STATE, inputs({ pct: 0.92 }), CFG)
  expect(d.action).toBe('request-handoff')
  return { ...d.nextState, ...o }
}

describe('F2: one resend for a request that was not cleanly delivered', () => {
  it('a fresh request records its reason and starts with an unspent budget', () => {
    const s = requested()
    expect(s.phase).toBe('await-handoff')
    expect(s.requestReason).toMatch(/^act threshold/)
    expect(s.requestUnconfirmed).toBe(false)
    expect(s.handoffResendCount).toBe(0)
  })

  it('unconfirmed + idle pane + no handoff -> resend, carrying the original reason', () => {
    const s = requested({ requestUnconfirmed: true })
    const d = decideGuard(s, inputs({ nowMs: NOW + 5 * 60_000 }), CFG)
    expect(d.action).toBe('request-handoff')
    expect(d.reason.startsWith(`${HANDOFF_RESEND_REASON_PREFIX}: act threshold`)).toBe(true)
    expect(d.nextState.phase).toBe('await-handoff')
    expect(d.nextState.handoffResendCount).toBe(1)
    expect(d.nextState.requestUnconfirmed).toBe(false)
    // The original reason is kept for the runner's wording, never the resend's own.
    expect(d.nextState.requestReason).toBe(s.requestReason)
    // The timeout is NOT extended by a resend.
    expect(d.nextState.deadlineMs).toBe(s.deadlineMs)
  })

  it(`at most ${MAX_HANDOFF_RESENDS} per await-handoff, even if the resend is unclean again`, () => {
    const s = requested({ requestUnconfirmed: true, handoffResendCount: MAX_HANDOFF_RESENDS })
    expect(decideGuard(s, inputs({ nowMs: NOW + 10 * 60_000 }), CFG).action).toBe('none')
  })

  it('a cleanly delivered request is never resent (unanswered is not lost)', () => {
    expect(decideGuard(requested(), inputs({ nowMs: NOW + 5 * 60_000 }), CFG).action).toBe('none')
  })

  it('no resend into a busy or unknown pane: it would be best-effort again', () => {
    const s = requested({ requestUnconfirmed: true })
    expect(decideGuard(s, inputs({ nowMs: NOW + 60_000, paneIdle: false, paneBusy: true }), CFG).action).toBe('none')
    expect(decideGuard(s, inputs({ nowMs: NOW + 60_000, paneIdle: false, paneBusy: false }), CFG).action).toBe('none')
  })

  it('no resend once the handoff is written: that path restarts as before', () => {
    const s = requested({ requestUnconfirmed: true })
    const d = decideGuard(s, inputs({ nowMs: NOW + 60_000, handoffMtime: NOW + 30_000, idleMs: 30_000 }), CFG)
    expect(d.action).toBe('restart')
  })

  it('the timeout and the hard threshold still win over a resend', () => {
    const s = requested({ requestUnconfirmed: true })
    expect(decideGuard(s, inputs({ nowMs: s.deadlineMs }), CFG).action).toBe('restart')
    expect(decideGuard(s, inputs({ nowMs: NOW + 60_000, pct: 0.98 }), CFG).action).toBe('restart')
  })

  it('a stale-refresh request is the one a resend repeats', () => {
    const s = requested({ handoffMtimeAtRequest: null })
    const d = decideGuard(s, inputs({ nowMs: NOW + 10 * 60_000, handoffMtime: NOW + 60_000, idleMs: 0 }), CFG)
    expect(d.action).toBe('request-handoff')
    expect(d.nextState.requestReason?.startsWith(STALE_REFRESH_REASON_PREFIX)).toBe(true)
  })
})

describe('F2 wiring in the runner', () => {
  it('the resend goes through the existing request-handoff case: still exactly two directive call sites, both emit-guarded', () => {
    const calls = runner.split('sendSystemDirective(').slice(1)
    expect(calls.length).toBe(2)
  })
  it('the resend is worded by the ORIGINAL reason', () => {
    expect(runner).toContain('decision.reason.startsWith(HANDOFF_RESEND_REASON_PREFIX)')
    expect(runner).toContain('? (state.requestReason ?? \'\')')
    expect(runner).not.toMatch(/\? staleRefreshHandoffPrompt[\s\S]{0,400}decision\.reason\.startsWith\(IDLE_FLUSH_REASON_PREFIX\)/)
  })
  it('an unclean delivery (best-effort into a busy pane, or the emit guard) arms the resend', () => {
    expect(runner).toContain('onBusySend: () => { sentBestEffort = true }')
    expect(runner).toContain("handoffOutcome === 'aborted-guard' || (handoffOutcome === 'sent' && sentBestEffort)")
    expect(runner).toContain('requestUnconfirmed: true')
  })
})

describe('F1: the fast round', () => {
  it('runs between 15 and 30 seconds, well inside one full sweep', () => {
    expect(FAST_INTERVAL_MS).toBeGreaterThanOrEqual(15_000)
    expect(FAST_INTERVAL_MS).toBeLessThanOrEqual(30_000)
    expect(FAST_INTERVAL_MS).toBeLessThan(INTERVAL_MS)
  })
  it('acts on a restart decision only, and only after two consecutive idle readings', () => {
    expect(FAST_IDLE_CONFIRM).toBe(2)
    expect(fastRoundActs('restart', 2)).toBe(true)
    expect(fastRoundActs('restart', 3)).toBe(true)
    expect(fastRoundActs('restart', 1)).toBe(false)
    expect(fastRoundActs('restart', 0)).toBe(false)
    // request-handoff (incl. a resend) stays on the full sweep; inject-resume
    // only into a ready session (CGRESUME1021, see context-guard-fast-resume).
    expect(fastRoundActs('request-handoff', 5)).toBe(false)
    expect(fastRoundActs('request-handoff', 5, true)).toBe(false)
    expect(fastRoundActs('inject-resume', 5)).toBe(false)
    expect(fastRoundActs('none', 5)).toBe(false)
    expect(fastRoundActs('none', 5, true)).toBe(false)
  })
  it('the same decideGuard, an agent outside the fast-round phases is never touched, a dropped decision leaves the state alone', () => {
    expect(runner).toContain("if (mode === 'fast' && !FAST_ROUND_PHASES.has(state.phase)) return")
    const i = runner.indexOf("if (mode === 'fast') {")
    expect(i).toBeGreaterThan(runner.indexOf('const decision = decideGuard('))
    // ...and it returns before setGuardState(name, decision.nextState).
    expect(i).toBeLessThan(runner.indexOf('setGuardState(name, decision.nextState)'))
    expect(runner.slice(i, i + 300)).toContain('if (!fastRoundActs(decision.action, streak, inputs.sessionReady)) return')
  })
  it('the streak counts only idle readings and resets outside await-handoff', () => {
    expect(runner).toContain("const streak = paneState === 'idle' ? (fastIdleStreak.get(name) ?? 0) + 1 : 0")
    expect(runner).toContain("if (state.phase !== 'await-handoff') fastIdleStreak.delete(name)")
  })
  it('a full sweep and a fast round never run at the same time', () => {
    const f = runner.slice(runner.indexOf('async function fastRound()'))
    expect(f.slice(0, 120)).toContain('if (tickRunning) return')
    expect(f).toContain('tickRunning = true')
  })
  it('the hold is still released only by the phase change (no "handoff written" shortcut)', () => {
    expect(runner).toContain('setDeliveryHoldCheck(guardDeliveryHold)')
    expect(runner).toContain("if (getHardGuardPhase(name) !== 'await-handoff') return null")
  })
})

describe('F3: the hold cap comes from the config', () => {
  it('invariant: cap = handoffTimeoutMinutes + one full sweep + slack, for any timeout', () => {
    for (const t of [1, 6, 20, 45, 120, 600]) {
      const cap = guardHoldCapMs({ handoffTimeoutMinutes: t })
      expect(cap).toBe(t * 60_000 + INTERVAL_MS + GUARD_HOLD_SLACK_MS)
      // The designed path (timeout, then the restart on the next full sweep)
      // always fits under the cap, with room for one slow sweep.
      expect(cap).toBeGreaterThan(t * 60_000 + INTERVAL_MS)
    }
  })
  it('today\'s fleet config (20 min) gives 27 minutes', () => {
    expect(guardHoldCapMs(DEFAULT_CONTEXT_GUARD)).toBe(27 * 60_000)
  })
  it('no hold for an agent that is not in await-handoff', () => {
    expect(guardDeliveryHold('nobody')).toBeNull()
  })
})
