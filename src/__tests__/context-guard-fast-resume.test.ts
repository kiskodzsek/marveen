// CGRESUME1021 (measured 2026-10-21): two ways a restarted agent was left at an
// empty prompt, pinned here.
//   R1 -- the fast round restarted the agent, but the resume prompt waited for
//         the full sweep (0-5 minutes). The fast round now runs the await-ready
//         step too, and acts only on a resume into a READY session; the
//         ready-timeout injection into a busy pane stays on the full sweep.
//   R2 -- a dashboard restart right after an agent restart lost the in-memory
//         await-ready state, so the resume was never sent. A restart that ran
//         is persisted, and restored at runner start while it is recent.
import { describe, it, expect, vi } from 'vitest'
import { mkdtempSync, readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'
import {
  decideGuard,
  DEFAULT_CONTEXT_GUARD,
  INITIAL_GUARD_STATE,
  READY_TIMEOUT_MS,
  type ContextGuardConfig,
  type GuardInputs,
  type GuardState,
} from '../context-guard.js'

const SANDBOX = mkdtempSync(join(tmpdir(), 'cgresume-'))
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

const { fastRoundActs, FAST_ROUND_PHASES, INTERVAL_MS, PENDING_RESUME_MAX_AGE_MS, pendingResumesToRestore } =
  await import('../web/context-guard-runner.js')

const here = dirname(fileURLToPath(import.meta.url))
const runner = readFileSync(join(here, '..', 'web', 'context-guard-runner.ts'), 'utf-8')

const CFG: ContextGuardConfig = { ...DEFAULT_CONTEXT_GUARD, enabled: true }
const NOW = 1_000_000_000

function inputs(o: Partial<GuardInputs> = {}): GuardInputs {
  return {
    nowMs: NOW, pct: 0.1, running: true, paneIdle: false, paneBusy: false, sessionReady: false,
    handoffMtime: null, paneSaturated: false, dailyHandoffDue: false, contextTokens: null, idleMs: null, ...o,
  }
}

function awaitReady(o: Partial<GuardState> = {}): GuardState {
  return { ...INITIAL_GUARD_STATE, phase: 'await-ready', deadlineMs: NOW + READY_TIMEOUT_MS, ...o }
}

describe('R1: the fast round sends the resume into a ready session', () => {
  it('runs the await-handoff and the await-ready phases, nothing else', () => {
    expect([...FAST_ROUND_PHASES].sort()).toEqual(['await-handoff', 'await-ready'])
    expect(FAST_ROUND_PHASES.has('idle')).toBe(false)
    expect(FAST_ROUND_PHASES.has('cooldown')).toBe(false)
  })
  it('a ready session: decideGuard says inject-resume, and the fast round acts on it', () => {
    const d = decideGuard(awaitReady(), inputs({ sessionReady: true }), CFG)
    expect(d.action).toBe('inject-resume')
    expect(fastRoundActs(d.action, 0, true)).toBe(true)
  })
  it('a session not yet ready before the deadline: nothing to do', () => {
    const d = decideGuard(awaitReady(), inputs({ sessionReady: false }), CFG)
    expect(d.action).toBe('none')
    expect(fastRoundActs(d.action, 0, false)).toBe(false)
  })
  it('the ready-timeout injection into a busy pane stays on the full sweep', () => {
    const d = decideGuard(awaitReady({ deadlineMs: NOW - 1 }), inputs({ sessionReady: false }), CFG)
    expect(d.action).toBe('inject-resume')
    expect(fastRoundActs(d.action, 5, false)).toBe(false)
  })
  it('the fast round picks its agents by the same phase set', () => {
    expect(runner).toContain('guardSweepAgentNames().filter((n) => FAST_ROUND_PHASES.has(getHardGuardPhase(n)))')
  })
  it('the ready probe is paid for in await-ready, so the fast round sees a real reading', () => {
    expect(runner).toContain("const sessionReady = running && state.phase === 'await-ready'")
  })
})

describe('R2: a restart that ran survives a dashboard restart', () => {
  const entry = (restartedAtMs: number, o: Record<string, unknown> = {}) =>
    ({ restartedAtMs, deadlineMs: restartedAtMs + READY_TIMEOUT_MS, handoffStaleMinutes: null, ...o })

  it('a recent entry is restored as await-ready with its own deadline and staleness', () => {
    const out = pendingResumesToRestore({ dave: entry(NOW - 36_000, { handoffStaleMinutes: 7 }) }, NOW)
    expect(out).toHaveLength(1)
    const [name, s] = out[0]
    expect(name).toBe('dave')
    expect(s.phase).toBe('await-ready')
    expect(s.deadlineMs).toBe(NOW - 36_000 + READY_TIMEOUT_MS)
    expect(s.handoffStaleMinutes).toBe(7)
    expect(s.cooldownUntilMs).toBe(0)
  })
  it("'unknown' staleness rides along; anything else becomes null", () => {
    const out = pendingResumesToRestore({
      a: entry(NOW, { handoffStaleMinutes: 'unknown' }),
      b: entry(NOW, { handoffStaleMinutes: 'x' }),
    }, NOW)
    expect(Object.fromEntries(out.map(([n, s]) => [n, s.handoffStaleMinutes]))).toEqual({ a: 'unknown', b: null })
  })
  it('the age limit is the ready timeout plus one full sweep', () => {
    expect(PENDING_RESUME_MAX_AGE_MS).toBe(READY_TIMEOUT_MS + INTERVAL_MS)
    expect(pendingResumesToRestore({ a: entry(NOW - PENDING_RESUME_MAX_AGE_MS) }, NOW)).toHaveLength(1)
    expect(pendingResumesToRestore({ a: entry(NOW - PENDING_RESUME_MAX_AGE_MS - 1) }, NOW)).toHaveLength(0)
  })
  it('an entry from the future or a malformed one is not restored', () => {
    expect(pendingResumesToRestore({ a: entry(NOW + 1) }, NOW)).toHaveLength(0)
    expect(pendingResumesToRestore({ a: { deadlineMs: NOW } } as never, NOW)).toHaveLength(0)
    expect(pendingResumesToRestore({ a: null } as never, NOW)).toHaveLength(0)
  })
  it('the entry is written only after the restart actually ran', () => {
    const i = runner.indexOf('await performRestart(name)')
    const j = runner.indexOf('recordPendingResume(name, decision.nextState, nowMs)')
    expect(i).toBeGreaterThan(-1)
    expect(j).toBeGreaterThan(i)
    expect(j).toBeLessThan(runner.indexOf('} catch (err) {', i))
  })
  it('every state write in checkAgent goes through setGuardState, which drops the entry outside await-ready', () => {
    const body = runner.slice(runner.indexOf('async function checkAgent('), runner.indexOf('/** Live status for the dashboard/API. */'))
    expect(body).not.toContain('guardStates.set(')
    expect(runner).toContain("if (state.phase !== 'await-ready') clearPendingResume(name)")
  })
  it('the restore runs at runner start, before the first round', () => {
    const start = runner.slice(runner.indexOf('export function startContextGuardRunner('))
    const r = start.indexOf('restorePendingResumes(Date.now())')
    expect(r).toBeGreaterThan(-1)
    expect(r).toBeLessThan(start.indexOf('setTimeout(sweep, INITIAL_DELAY_MS)'))
    expect(r).toBeLessThan(start.indexOf('setInterval(fastRound, FAST_INTERVAL_MS)'))
  })
})
