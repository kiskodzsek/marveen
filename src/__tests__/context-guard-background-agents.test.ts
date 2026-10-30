// Patrik TG 6938, Klodel 16131 (2026-10-23): the context-guard restarted dave at
// 21:14:49 ("restart handoff written", 84%) while four background subagents
// started at 21:14 were still running; their uncommitted work (about 3 minutes,
// Klodel 16133) died with the session. Since #82 the empty box above a background-agent panel reads
// idle (right for the router), and the guard restarted on that idle reading.
//
// The fix: the guard counts the background agents separately and treats a
// running one as busy, so every restart path defers as for a live turn.
import { describe, it, expect, vi } from 'vitest'
import { mkdtempSync, readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'
import { backgroundAgentCount, detectPaneState } from '../pane-state.js'
import {
  BG_REFRESH_REASON_PREFIX,
  BG_RELEASE_REASON_PREFIX,
  bgReleaseCapPct,
  decideGuard,
  DEFAULT_CONTEXT_GUARD,
  INITIAL_GUARD_STATE,
  type ContextGuardConfig,
  type GuardInputs,
  type GuardState,
} from '../context-guard.js'

const SANDBOX = mkdtempSync(join(tmpdir(), 'cgbg-'))
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

const {
  guardPaneSignals, fastRoundBgActs, bgDeferredContinuePrompt, bgDeferredRefreshPrompt,
  deliveryHoldForPhase, bgReleaseWindowOpen, guardHoldCapMs, guardReadyHoldCapMs,
} = await import('../web/context-guard-runner.js')

const here = dirname(fileURLToPath(import.meta.url))
const runner = readFileSync(join(here, '..', 'web', 'context-guard-runner.ts'), 'utf-8')

const SEP = '─'.repeat(60)
// The bottom of store/context-guard-last-pane-dave.txt (21:14, the pre-restart
// snapshot), the prose replaced, the frame and the panel verbatim.
const DAVE_2114 = [
  '  A kártyán felírtam az indulást. A HANDOFF.md-ben benne van a 4 szál.',
  '',
  '✻ Waiting for 4 background agents to finish',
  '',
  `${SEP} Dave ─`,
  '❯ ',
  SEP,
  '  Opus 5.5 (1M context) | ctx 42% | 5h 54% | 7d 53%',
  '  ⏵⏵ bypass permissions on (shift+tab to cycle)',
  '',
  '  ⏺ main',
  '  ◯ general-purpose  Inspecting MARKETING_SAMPLE_PDF… 1m 39s · ↓ 102.5k tokens',
  '  ◯ general-purpose  Inspecting gen_site.py asset jo… 1m 26s · ↓ 106.4k tokens',
  '  ◯ general-purpose  Searching migrations for projec…  1m 5s · ↓ 171.4k tokens',
  '  ◯ general-purpose  Searching product_specs consume…    54s · ↓ 115.6k tokens',
  '',
].join('\n')

// The kernel pane 12 s after its only background agent finished (measured
// 2026-10-23 21:4x with tmux capture-pane): the panel is gone, no row lingers.
const FINISHED = [
  '⏺ Done.',
  '',
  SEP,
  '❯ ',
  SEP,
  '  ⏵⏵ bypass permissions on · 1 shell · /tasks to see subagents · esc to inter…',
  '',
].join('\n')

describe('backgroundAgentCount', () => {
  it('counts the four running dave subagents of 21:14 (panel rows and the Waiting line agree)', () => {
    expect(backgroundAgentCount(DAVE_2114)).toBe(4)
  })

  it('the router reading of the same pane is unchanged: idle (#82)', () => {
    expect(detectPaneState(DAVE_2114)).toBe('idle')
  })

  it('either signal alone is enough', () => {
    const panelOnly = DAVE_2114.replace('✻ Waiting for 4 background agents to finish', '⏺ Started.')
    expect(backgroundAgentCount(panelOnly)).toBe(4)
    const lines = DAVE_2114.split('\n')
    const waitingOnly = lines.slice(0, lines.indexOf('  ⏺ main')).join('\n')
    expect(backgroundAgentCount(waitingOnly)).toBe(4)
    expect(backgroundAgentCount(waitingOnly.replace('4 background agents', '1 background agent'))).toBe(1)
  })

  it('zero once the agents are done, and for an empty capture', () => {
    expect(backgroundAgentCount(FINISHED)).toBe(0)
    expect(backgroundAgentCount('')).toBe(0)
  })

  it('prose quoting the sentence is not the Claude Code line (Viktor 16178)', () => {
    const quoted = FINISHED.replace('⏺ Done.', '⏺ Dave wrote: Waiting for 4 background agents to finish')
    expect(backgroundAgentCount(quoted)).toBe(0)
    const trailing = FINISHED.replace('⏺ Done.', '✻ Waiting for 4 background agents to finish, said the log')
    expect(backgroundAgentCount(trailing)).toBe(0)
  })

  it('a Waiting line far up in the scrollback is history, not a live signal', () => {
    const old = [
      '✻ Waiting for 2 background agents to finish',
      ...Array.from({ length: 8 }, (_, i) => `  line ${i}`),
      FINISHED,
    ].join('\n')
    expect(backgroundAgentCount(old)).toBe(0)
  })
})

describe('guardPaneSignals: what the guard decides on', () => {
  it('the dave 21:14 pane is busy for the guard, idle for everyone else', () => {
    expect(guardPaneSignals(DAVE_2114)).toEqual({ paneState: 'idle', guardPaneState: 'busy', bgAgents: 4 })
  })

  it('without background agents the guard reads the pane exactly as before', () => {
    expect(guardPaneSignals(FINISHED)).toEqual({ paneState: detectPaneState(FINISHED), guardPaneState: detectPaneState(FINISHED), bgAgents: 0 })
    expect(guardPaneSignals(null)).toEqual({ paneState: 'unknown', guardPaneState: 'unknown', bgAgents: 0 })
  })

  it('the runner feeds decideGuard and the fast round from the guard reading, not the raw state', () => {
    expect(runner).toContain("paneIdle: guardPaneState === 'idle'")
    expect(runner).toContain("paneBusy: guardPaneState === 'busy'")
    expect(runner).toContain("const streak = guardPaneState === 'idle'")
    expect(runner).not.toMatch(/paneIdle: paneState ===|paneBusy: paneState ===|streak = paneState ===/)
  })
})

describe('decideGuard on the guard reading of the 21:14 pane', () => {
  const CFG: ContextGuardConfig = { ...DEFAULT_CONTEXT_GUARD, enabled: true, actPct: 0.7, hardPct: 0.97 }
  const NOW = 1_000_000_000
  const { guardPaneState } = guardPaneSignals(DAVE_2114)
  const inputs = (o: Partial<GuardInputs> = {}): GuardInputs => ({
    nowMs: NOW, pct: 0.84, running: true,
    paneIdle: guardPaneState === 'idle', paneBusy: guardPaneState === 'busy',
    sessionReady: false, handoffMtime: null, paneSaturated: false, dailyHandoffDue: false,
    contextTokens: null, idleMs: null, ...o,
  })
  const requested = (): GuardState => {
    const d = decideGuard(INITIAL_GUARD_STATE, inputs({ pct: 0.78 }), CFG)
    expect(d.action).toBe('request-handoff')
    return d.nextState
  }

  it('handoff written: no restart while the agents run (the 21:14:49 restart)', () => {
    const s = requested()
    const d = decideGuard(s, inputs({ nowMs: NOW + 4 * 60_000, handoffMtime: NOW + 60_000, idleMs: 60_000 }), CFG)
    expect(d.action).toBe('none')
    // ...and the same handoff restarts as soon as the panel is gone.
    const after = decideGuard(s, inputs({
      nowMs: NOW + 4 * 60_000, handoffMtime: NOW + 60_000, idleMs: 60_000, paneIdle: true, paneBusy: false,
    }), CFG)
    expect(after.action).toBe('restart')
  })

  it('neither the handoff timeout nor the hard threshold cuts them', () => {
    const s = requested()
    expect(decideGuard(s, inputs({ nowMs: s.deadlineMs + 1 }), CFG).action).toBe('none')
    expect(decideGuard(s, inputs({ nowMs: NOW + 60_000, pct: 0.98 }), CFG).action).toBe('none')
  })

  it('the saturation net still fires: a full context cannot wait for them', () => {
    const s = requested()
    expect(decideGuard(s, inputs({ nowMs: NOW + 60_000, paneSaturated: true }), CFG).action).toBe('restart')
  })
})

// KLODEL18385 (Patrik TG 8933): the restart waits for the agents, but the main
// thread need not. Measured on dave, 2026-10-28: idle 6m43s (07:07-07:14) and
// 10+ minutes from 08:07, the handoff written, two agents running, the last
// directive it had heard "ÁLLJ MEG"; Klodel's plain message did not lift it.
describe('the main thread is released while its background agents defer the restart', () => {
  const CFG: ContextGuardConfig = { ...DEFAULT_CONTEXT_GUARD, enabled: true, actPct: 0.7, hardPct: 0.97 }
  const NOW = 1_000_000_000
  const HANDOFF = NOW + 60_000
  // The guard reading of DAVE_2114 (busy) plus the raw reading of the main box (idle).
  const inputs = (o: Partial<GuardInputs> = {}): GuardInputs => ({
    nowMs: NOW + 2 * 60_000, pct: 0.76, running: true,
    paneIdle: false, paneBusy: true, backgroundAgents: 2, mainIdle: true,
    sessionReady: false, handoffMtime: HANDOFF, paneSaturated: false, dailyHandoffDue: false,
    contextTokens: null, idleMs: 60_000, ...o,
  })
  const requested = (): GuardState => {
    const d = decideGuard(INITIAL_GUARD_STATE, inputs({ nowMs: NOW, handoffMtime: null, backgroundAgents: 0, mainIdle: false }), CFG)
    expect(d.action).toBe('request-handoff')
    return d.nextState
  }
  const released = (): GuardState => {
    const d = decideGuard(requested(), inputs(), CFG)
    expect(d.action).toBe('request-handoff')
    expect(d.reason.startsWith(BG_RELEASE_REASON_PREFIX)).toBe(true)
    return d.nextState
  }

  it('handoff written, main box idle, agents running: one release, and the handoff on disk no longer counts', () => {
    const s = released()
    expect(s.bgReleased).toBe(true)
    expect(s.handoffMtimeAtRequest).toBe(HANDOFF)
    expect(s.phase).toBe('await-handoff')
    // Once: the next sweeps with the same reading do nothing.
    expect(decideGuard(s, inputs({ nowMs: NOW + 3 * 60_000 }), CFG).action).toBe('none')
    expect(decideGuard(s, inputs({ nowMs: s.deadlineMs + 1, mainIdle: false }), CFG).action).toBe('none')
  })

  it('no release mid-turn, before the handoff, without agents, or at the cap', () => {
    const s = requested()
    expect(decideGuard(s, inputs({ mainIdle: false }), CFG).action).toBe('none')
    expect(decideGuard(s, inputs({ handoffMtime: null }), CFG).action).toBe('none')
    expect(decideGuard(s, inputs({ backgroundAgents: 0, mainIdle: false, paneIdle: false, paneBusy: true }), CFG).action).toBe('none')
    expect(bgReleaseCapPct(CFG)).toBeCloseTo(0.835)
    expect(decideGuard(s, inputs({ pct: 0.84 }), CFG).action).toBe('none')
  })

  it('a released thread that reaches the cap is told to stop again, once', () => {
    const s = released()
    const d = decideGuard(s, inputs({ nowMs: NOW + 9 * 60_000, pct: 0.84, mainIdle: false }), CFG)
    expect(d.action).toBe('request-handoff')
    // No release/refresh prefix: the runner sends the critical STOP prompt.
    expect(d.reason.startsWith(BG_RELEASE_REASON_PREFIX) || d.reason.startsWith(BG_REFRESH_REASON_PREFIX)).toBe(false)
    expect(d.nextState.bgRestopSent).toBe(true)
    expect(decideGuard(d.nextState, inputs({ nowMs: NOW + 10 * 60_000, pct: 0.86 }), CFG).action).toBe('none')
  })

  it('the agents done and the thread idle: one refresh with a fresh deadline, then the restart on the new handoff', () => {
    const s = released()
    const late = s.deadlineMs + 5 * 60_000
    const idle = { backgroundAgents: 0, mainIdle: true, paneIdle: true, paneBusy: false }
    const r = decideGuard(s, inputs({ nowMs: late, ...idle }), CFG)
    expect(r.action).toBe('request-handoff')
    expect(r.reason.startsWith(BG_REFRESH_REASON_PREFIX)).toBe(true)
    expect(r.nextState.deadlineMs).toBe(late + CFG.handoffTimeoutMinutes * 60_000)
    // Not a second time while it writes.
    expect(decideGuard(r.nextState, inputs({ nowMs: late + 60_000, ...idle }), CFG).action).toBe('none')
    const written = decideGuard(r.nextState, inputs({ nowMs: late + 2 * 60_000, ...idle, handoffMtime: late + 90_000, idleMs: 30_000 }), CFG)
    expect(written.action).toBe('restart')
  })

  it('a thread that rewrote its handoff itself restarts as soon as the agents are done', () => {
    const s = released()
    const d = decideGuard(s, inputs({
      nowMs: NOW + 12 * 60_000, backgroundAgents: 0, paneIdle: true, paneBusy: false,
      handoffMtime: NOW + 11 * 60_000, idleMs: 60_000,
    }), CFG)
    expect(d.action).toBe('restart')
  })

  it('a released thread that never writes again restarts at the refresh deadline', () => {
    const s = released()
    const idle = { backgroundAgents: 0, mainIdle: true, paneIdle: true, paneBusy: false }
    const r = decideGuard(s, inputs({ nowMs: NOW + 30 * 60_000, ...idle }), CFG)
    expect(r.reason.startsWith(BG_REFRESH_REASON_PREFIX)).toBe(true)
    expect(decideGuard(r.nextState, inputs({ nowMs: r.nextState.deadlineMs + 1, ...idle }), CFG).action).toBe('restart')
  })

  it('the saturation net still outranks all of it', () => {
    const s = released()
    expect(decideGuard(s, inputs({ paneSaturated: true }), CFG).action).toBe('restart')
  })

  it('the fast round sends the release after two idle main readings, the refresh after two idle guard readings', () => {
    const release = { action: 'request-handoff', reason: `${BG_RELEASE_REASON_PREFIX}: x` }
    const refresh = { action: 'request-handoff', reason: `${BG_REFRESH_REASON_PREFIX}: x` }
    expect(fastRoundBgActs(release, 0, 1)).toBe(false)
    expect(fastRoundBgActs(release, 0, 2)).toBe(true)
    expect(fastRoundBgActs(refresh, 1, 5)).toBe(false)
    expect(fastRoundBgActs(refresh, 2, 0)).toBe(true)
    expect(fastRoundBgActs({ action: 'request-handoff', reason: 'act threshold' }, 5, 5)).toBe(false)
    expect(fastRoundBgActs({ action: 'restart', reason: `${BG_RELEASE_REASON_PREFIX}: x` }, 5, 5)).toBe(false)
  })

  it('the prompts lift the STOP in words, forbid a new agent, and announce the refresh', () => {
    const p = bgDeferredContinuePrompt(2, '/x/HANDOFF.md')
    expect(p).toContain('[CONTEXT-GUARD]')
    expect(p).toContain('2 háttér-subagented')
    expect(p).toContain('feloldva')
    expect(p).toContain('Új háttér-subagentet most NE indíts')
    expect(bgDeferredRefreshPrompt('/x/HANDOFF.md')).toContain('ÁLLJ MEG')
    // The runner picks them by prefix, ahead of the stale-refresh wording, and feeds the raw main reading.
    const i = runner.indexOf('promptReason.startsWith(BG_RELEASE_REASON_PREFIX)')
    expect(i).toBeGreaterThan(-1)
    expect(i).toBeLessThan(runner.indexOf('promptReason.startsWith(STALE_REFRESH_REASON_PREFIX)'))
    expect(runner).toContain("mainIdle: paneState === 'idle'")
    expect(runner).toContain('backgroundAgents: bgAgents')
  })

  // ROUTERHOLD1028 (card d480512c, Patrik TG 9207): dave, 2026-10-28, released
  // 12:17:16, re-stopped 12:24:33; six rows held throughout, because the router
  // hold followed the phase (still await-handoff) and not the release.
  describe('ROUTERHOLD1028: the router hold follows the release, not only the phase', () => {
    it('released, not re-stopped: no hold, though the phase is still await-handoff', () => {
      const s = released()
      expect(s.phase).toBe('await-handoff')
      expect(bgReleaseWindowOpen(s)).toBe(true)
      expect(deliveryHoldForPhase(s.phase, CFG, s)).toBeNull()
    })

    it('re-stopped at the cap: the hold is back, with its cap and the reason in detail', () => {
      const d = decideGuard(released(), inputs({ nowMs: NOW + 9 * 60_000, pct: 0.84, mainIdle: false }), CFG)
      expect(d.nextState.bgRestopSent).toBe(true)
      expect(bgReleaseWindowOpen(d.nextState)).toBe(false)
      expect(deliveryHoldForPhase(d.nextState.phase, CFG, d.nextState)).toEqual({
        reason: 'context-guard await-handoff', maxMs: guardHoldCapMs(CFG),
        detail: 'main thread re-stopped at the background-release cap',
      })
    })

    it('the agents done and the refresh requested ("ÁLLJ MEG"): the hold is back', () => {
      const s = released()
      const idle = { backgroundAgents: 0, mainIdle: true, paneIdle: true, paneBusy: false }
      const r = decideGuard(s, inputs({ nowMs: s.deadlineMs + 60_000, ...idle }), CFG)
      expect(r.reason.startsWith(BG_REFRESH_REASON_PREFIX)).toBe(true)
      expect(deliveryHoldForPhase(r.nextState.phase, CFG, r.nextState)).toMatchObject({
        reason: 'context-guard await-handoff', detail: 'background agents done, handoff refresh requested',
      })
    })

    it('before any release (the first STOP), the GUARDHOLD1013 hold is unchanged', () => {
      const s = requested()
      expect(deliveryHoldForPhase(s.phase, CFG, s)).toEqual({ reason: 'context-guard await-handoff', maxMs: guardHoldCapMs(CFG) })
      expect(deliveryHoldForPhase('await-handoff', CFG)).toEqual({ reason: 'context-guard await-handoff', maxMs: guardHoldCapMs(CFG) })
    })

    it('await-ready holds whatever the release flags say (CGHOLDREADY1021)', () => {
      const flags = { bgReleased: true, bgRestopSent: false, bgRefreshSent: false }
      expect(deliveryHoldForPhase('await-ready', CFG, flags)).toEqual({ reason: 'context-guard await-ready', maxMs: guardReadyHoldCapMs(CFG) })
      for (const phase of ['idle', 'cooldown']) expect(deliveryHoldForPhase(phase, CFG, flags)).toBeNull()
    })

    it('the runner hands the guard state to the hold, not the phase alone', () => {
      expect(runner).toContain('deliveryHoldForPhase(phase, readContextGuardConfig(name), state)')
    })
  })
})
