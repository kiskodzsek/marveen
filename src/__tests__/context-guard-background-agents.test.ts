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

const { guardPaneSignals } = await import('../web/context-guard-runner.js')

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
