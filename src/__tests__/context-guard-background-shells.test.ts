// Card 70dad0d7 (measured 2026-11-16): a Codex review ran in a background SHELL
// of the kernel session (run_review, pid 44934) while the context-guard prepared
// a restart; the guard waited for background agents but not for shells, and the
// restart had to be held by hand. A restart kills the shell with the session.
//
// The fix: the live footer's shell pill is counted (backgroundShellCount), and
// while a shell runs the idle pane reads busy for the guard, so every restart
// path waits as for a live turn -- up to BG_SHELL_WAIT_MAX_MS, after which the
// restart goes ahead and its notice names the shells it cut. No shell: nothing
// changes.
import { describe, it, expect, vi, afterAll } from 'vitest'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'
import { backgroundAgentCount, backgroundShellCount, detectPaneState } from '../pane-state.js'
import {
  decideGuard,
  DEFAULT_CONTEXT_GUARD,
  INITIAL_GUARD_STATE,
  type ContextGuardConfig,
  type GuardInputs,
  type GuardState,
} from '../context-guard.js'

const SANDBOX = mkdtempSync(join(tmpdir(), 'cgsh-'))
afterAll(() => rmSync(SANDBOX, { recursive: true, force: true }))
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

const { guardPaneSignals, bgShellHold, withShellHold, BG_SHELL_WAIT_MAX_MS, BG_SHELL_CLEAR_IDLE_READINGS } = await import('../web/context-guard-runner.js')

const here = dirname(fileURLToPath(import.meta.url))
const runner = readFileSync(join(here, '..', 'web', 'context-guard-runner.ts'), 'utf-8')

const SEP = '─'.repeat(100)
/** A pane with the live input box and the given footer as its last line. */
function pane(footer: string, tail: string[] = []): string {
  return [
    '⏺ Kész, a teszt zöld.',
    '',
    `${SEP} Kernel ─`,
    '❯ ',
    SEP,
    `  ${footer}`,
    ...tail,
  ].join('\n')
}

const IDLE_ONE_SHELL = pane('⏵⏵ bypass permissions on · 1 shell')
const NO_SHELL = pane('⏵⏵ bypass permissions on (shift+tab to cycle)')

describe('backgroundShellCount: the shell pill of the live footer', () => {
  it('idle bare pill, busy footer, two shells, a notice segment, a mix with a monitor', () => {
    expect(backgroundShellCount(IDLE_ONE_SHELL)).toBe(1)
    // Measured 2026-11-18 on the kernel pane while a run_in_background sleep ran.
    expect(backgroundShellCount(pane('⏵⏵ bypass permissions on · 1 shell · esc to interrupt · ↓ to manage'))).toBe(1)
    expect(backgroundShellCount(pane('⏵⏵ bypass permissions on · 2 shells · ↓ to manage'))).toBe(2)
    expect(backgroundShellCount(pane('⏵⏵ bypass permissions on · install gh for PR status · 2 shells'))).toBe(2)
    expect(backgroundShellCount(pane('⏵⏵ bypass permissions on · 1 shell, 1 monitor · ↓ to manage'))).toBe(1)
    expect(backgroundShellCount(pane('⏵⏵ accept edits on · 3 background tasks'))).toBe(3)
  })

  it('the bare-pill fixture is what the router reads as idle', () => {
    expect(detectPaneState(IDLE_ONE_SHELL)).toBe('idle')
  })

  it('no shell: no pill, a monitor alone, an agent alone', () => {
    expect(backgroundShellCount(NO_SHELL)).toBe(0)
    expect(backgroundShellCount(pane('⏵⏵ bypass permissions on · 1 monitor · ↓ to manage'))).toBe(0)
    expect(backgroundShellCount(pane('⏵⏵ bypass permissions on · 1 local agent'))).toBe(0)
    expect(backgroundShellCount('')).toBe(0)
  })

  it('a pill quoted in scrollback, or a footer-shaped last line with no input box, is not a signal', () => {
    const quoted = ['  ⏵⏵ bypass permissions on · 2 shells', ...NO_SHELL.split('\n')].join('\n')
    expect(backgroundShellCount(quoted)).toBe(0)
    expect(backgroundShellCount(['$ tail log', 'x', 'y', 'z', 'w', 'v', 'u', '⏵⏵ bypass permissions on · 1 shell'].join('\n'))).toBe(0)
  })

  it('a background-agent panel under the footer does not hide the shell pill', () => {
    const p = pane('⏵⏵ bypass permissions on · 1 shell', ['', '  ⏺ main', '  ◯ general-purpose  Testing … 1m 2s · ↓ 3.1k tokens'])
    expect(backgroundAgentCount(p)).toBe(1)
    expect(backgroundShellCount(p)).toBe(1)
  })
})

describe('bgShellHold: wait for the shell, capped', () => {
  const NOW = 1_000_000_000
  it('no shell: no hold, the clock is cleared', () => {
    expect(bgShellHold(undefined, 0, NOW)).toEqual({ hold: false, sinceMs: undefined, capPassed: false, zeroStreak: 0 })
    expect(bgShellHold(NOW - 5_000, 0, NOW)).toEqual({ hold: false, sinceMs: undefined, capPassed: false, zeroStreak: 0 })
  })
  it('first sight starts the clock and holds; still holds just below the cap', () => {
    expect(bgShellHold(undefined, 1, NOW)).toEqual({ hold: true, sinceMs: NOW, capPassed: false, zeroStreak: 0 })
    expect(bgShellHold(NOW, 1, NOW + BG_SHELL_WAIT_MAX_MS - 1)).toEqual({ hold: true, sinceMs: NOW, capPassed: false, zeroStreak: 0 })
  })
  it('at the cap the restart no longer waits, and the cap is said', () => {
    expect(bgShellHold(NOW, 2, NOW + BG_SHELL_WAIT_MAX_MS)).toEqual({ hold: false, sinceMs: NOW, capPassed: true, zeroStreak: 0 })
  })
  it('the cap is a bounded wait, not an unbounded one', () => {
    expect(BG_SHELL_WAIT_MAX_MS).toBeGreaterThan(0)
    expect(BG_SHELL_WAIT_MAX_MS).toBeLessThanOrEqual(2 * 60 * 60_000)
  })
})

// Card d23bec1d (measured 2026-11-20 on the kernel pane, 100 one-second captures
// while 2-3 shells ran): 3 read 0 shells, all while a long message was typed
// into the input box (2 typing, 1 unknown): the box is taller than the footer's
// box distance. On Dave the same day such a 0 dropped the clock and the
// 45-minute cap started again at 18:25 for a shell running since 17:38.
// The shape below is the measured one: the ❯ row, 9 wrapped rows, the
// separator, the footer with "3 shells" (text neutral).
const TYPING_LONG = [
  '⏺ Kész.',
  '',
  `${SEP} Kernel ─`,
  '❯ Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore',
  ...Array.from({ length: 9 }, (_, i) => `  magna aliqua ${i}: ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea`),
  SEP,
  '  ⏵⏵ bypass permissions on · 3 shells',
].join('\n')

describe('bgShellHold: a 0 read while a message is typed does not drop the clock (card d23bec1d)', () => {
  const NOW = 1_000_000_000
  const START = NOW - 33 * 60_000 // the clock started 33 minutes ago, as on Dave 17:52 -> 18:25
  it('the measured typing shape reads 0 shells and is not idle', () => {
    expect(backgroundShellCount(TYPING_LONG)).toBe(0)
    expect(detectPaneState(TYPING_LONG)).not.toBe('idle')
  })
  it('a 0 on a pane that is not idle keeps the clock and the streak, and never holds', () => {
    for (const zeroStreak of [0, 1]) {
      expect(bgShellHold(START, 0, NOW, BG_SHELL_WAIT_MAX_MS, { readIdle: false, zeroStreak }))
        .toEqual({ hold: false, sinceMs: START, capPassed: false, zeroStreak })
    }
  })
  it('the cap still counts from the first sight after the misread', () => {
    const misread = bgShellHold(START, 0, NOW, BG_SHELL_WAIT_MAX_MS, { readIdle: false, zeroStreak: 0 })
    const next = bgShellHold(misread.sinceMs, 1, START + BG_SHELL_WAIT_MAX_MS, BG_SHELL_WAIT_MAX_MS, { readIdle: true, zeroStreak: misread.zeroStreak })
    expect(next).toEqual({ hold: false, sinceMs: START, capPassed: true, zeroStreak: 0 })
  })
  it('the old rule (every 0 drops the clock) would restart the cap: the misread then the next shell reading', () => {
    const old = bgShellHold(START, 0, NOW)
    expect(old.sinceMs).toBeUndefined()
    expect(bgShellHold(old.sinceMs, 1, NOW + 1).sinceMs).toBe(NOW + 1)
  })
  it('one idle 0 keeps the clock; the second in a row drops it; a shell in between resets the streak', () => {
    expect(BG_SHELL_CLEAR_IDLE_READINGS).toBe(2)
    const one = bgShellHold(START, 0, NOW, BG_SHELL_WAIT_MAX_MS, { readIdle: true, zeroStreak: 0 })
    expect(one).toEqual({ hold: false, sinceMs: START, capPassed: false, zeroStreak: 1 })
    expect(bgShellHold(START, 0, NOW, BG_SHELL_WAIT_MAX_MS, { readIdle: true, zeroStreak: one.zeroStreak }))
      .toEqual({ hold: false, sinceMs: undefined, capPassed: false, zeroStreak: 0 })
    expect(bgShellHold(START, 1, NOW, BG_SHELL_WAIT_MAX_MS, { readIdle: true, zeroStreak: 1 }).zeroStreak).toBe(0)
  })
  it('no clock running: a 0 stays a 0 (nothing to keep)', () => {
    expect(bgShellHold(undefined, 0, NOW, BG_SHELL_WAIT_MAX_MS, { readIdle: false, zeroStreak: 0 }))
      .toEqual({ hold: false, sinceMs: undefined, capPassed: false, zeroStreak: 0 })
  })
})

describe('withShellHold: only an idle reading turns busy', () => {
  it('idle + hold -> busy; idle without hold -> idle; busy and unknown are kept', () => {
    expect(withShellHold('idle', true)).toBe('busy')
    expect(withShellHold('idle', false)).toBe('idle')
    expect(withShellHold('busy', false)).toBe('busy')
    expect(withShellHold('unknown', true)).toBe('unknown')
  })
})

// The chain the runner runs: pane -> signals -> shell hold -> decideGuard.
const CFG: ContextGuardConfig = { ...DEFAULT_CONTEXT_GUARD, enabled: true }
const T0 = 2_000_000_000
function decideOn(p: string, state: GuardState, since: number | undefined, nowMs: number, pct = 0.92) {
  const { guardPaneState: g } = guardPaneSignals(p)
  const sh = bgShellHold(since, backgroundShellCount(p), nowMs)
  const st = withShellHold(g, sh.hold)
  const inputs: GuardInputs = {
    nowMs, pct, running: true, paneIdle: st === 'idle', paneBusy: st === 'busy', sessionReady: false,
    handoffMtime: T0 + 1_000, paneSaturated: false, dailyHandoffDue: false, contextTokens: null, idleMs: null,
    backgroundAgents: 0, mainIdle: true,
  }
  return decideGuard(state, inputs, CFG)
}
/** await-handoff with the handoff already written: the next idle reading restarts. */
function handoffWritten(): GuardState {
  const d = decideGuard(INITIAL_GUARD_STATE, {
    nowMs: T0, pct: 0.92, running: true, paneIdle: true, paneBusy: false, sessionReady: false,
    handoffMtime: T0, paneSaturated: false, dailyHandoffDue: false, contextTokens: null, idleMs: null,
  }, CFG)
  expect(d.action).toBe('request-handoff')
  return d.nextState
}

describe('the guard with a running background shell', () => {
  it('handoff written, idle pane, no shell: restarts (unchanged)', () => {
    expect(decideOn(NO_SHELL, handoffWritten(), undefined, T0 + 60_000).action).toBe('restart')
  })
  it('handoff written, idle pane, a shell running: no restart', () => {
    const d = decideOn(IDLE_ONE_SHELL, handoffWritten(), T0 + 60_000, T0 + 60_000)
    expect(d.action).not.toBe('restart')
  })
  it('the hard threshold does not cut the shell either: it asks for the handoff instead', () => {
    const hard = CFG.hardPct + 0.01
    // Control: the same reading without a shell restarts at once.
    expect(decideOn(NO_SHELL, INITIAL_GUARD_STATE, undefined, T0, hard).action).toBe('restart')
    expect(decideOn(IDLE_ONE_SHELL, INITIAL_GUARD_STATE, undefined, T0, hard).action).toBe('request-handoff')
  })
  it('handoff timeout with a shell running: still no restart before the cap', () => {
    const s = { ...handoffWritten(), deadlineMs: T0 }
    // Control: past the deadline with no handoff and no shell, the timeout restarts.
    const unwritten = (p: string, since: number | undefined) => decideGuard(s, {
      nowMs: T0 + 10 * 60_000, pct: 0.5, running: true, paneIdle: withShellHold(guardPaneSignals(p).guardPaneState, bgShellHold(since, backgroundShellCount(p), T0 + 10 * 60_000).hold) === 'idle',
      paneBusy: withShellHold(guardPaneSignals(p).guardPaneState, bgShellHold(since, backgroundShellCount(p), T0 + 10 * 60_000).hold) === 'busy',
      sessionReady: false, handoffMtime: T0, paneSaturated: false, dailyHandoffDue: false, contextTokens: null, idleMs: null,
    }, CFG)
    expect(unwritten(NO_SHELL, undefined).action).toBe('restart')
    expect(unwritten(IDLE_ONE_SHELL, T0).action).not.toBe('restart')
  })
  it('past the cap the restart goes ahead', () => {
    const d = decideOn(IDLE_ONE_SHELL, handoffWritten(), T0, T0 + BG_SHELL_WAIT_MAX_MS)
    expect(d.action).toBe('restart')
  })
})

describe('runner wiring (source pins)', () => {
  it('the guard pane state the decision reads is the shell-held one', () => {
    expect(runner).toMatch(/const guardPaneState = withShellHold\(agentGuardPaneState, shell\.hold\)/)
    expect(runner).toMatch(/paneIdle: guardPaneState === 'idle'/)
    expect(runner).toMatch(/paneBusy: guardPaneState === 'busy'/)
  })
  it('the shell clock moves only on a sweep that captured the pane', () => {
    expect(runner).toMatch(/const bgShells = pane !== null \? backgroundShellCount\(pane\) : 0/)
    expect(runner).toMatch(/bgShellSince\.set\(name, shell\.sinceMs\)/)
  })
  it('the runner passes the idle reading and the streak (card d23bec1d)', () => {
    expect(runner).toMatch(/\{ readIdle: paneState === 'idle', zeroStreak: bgShellZeroStreak\.get\(name\) \?\? 0 \}/)
    expect(runner).toMatch(/bgShellZeroStreak\.set\(name, shell\.zeroStreak\)/)
  })
  it('the restart notice names the shells the restart cut', () => {
    expect(runner).toMatch(/bgShells > 0\s*\n?\s*\? ` FIGYELEM: \$\{bgShells\} hatter-shell meg futott/)
  })
})
