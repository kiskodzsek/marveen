// Card 8121c1f5 (measured 2026-11-20, store/dashboard.log, dave): the background-shell
// clock of the context-guard (bgShellSince) lived only in memory, so every dashboard
// restart started a new 45-minute wait for the same shell (19:31, 19:43, 20:11, 20:27):
// while the dashboard restarted more often than the cap, the cap could never pass.
//
// The fix: the clock is persisted (store/context-guard-bgshell.json), tied to the
// pane's process (tmux session_created + pane_pid), and restored on the first pane
// reading after the dashboard starts. Another pane process (an agent restart killed
// the shells), a malformed entry or a gap longer than BG_SHELL_RESTORE_MAX_GAP_MS:
// dropped, a new clock starts (the restart waits longer, the safe side).
import { describe, it, expect, vi, afterAll, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync, existsSync, symlinkSync, lstatSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const SANDBOX = mkdtempSync(join(tmpdir(), 'cgbp-'))
mkdirSync(join(SANDBOX, 'store'), { recursive: true })
afterAll(() => rmSync(SANDBOX, { recursive: true, force: true }))
const STORE_FILE = join(SANDBOX, 'store', 'context-guard-bgshell.json')

// What the mocked tmux answers; changed by the tests.
const tmux = { key: '1795200000:4242' as string | null, pane: '' }
const info = vi.fn()

vi.mock('../config.js', async (orig) => {
  const actual = await orig<typeof import('../config.js')>()
  return { ...actual, MAIN_AGENT_ID: 'marveen', PROJECT_ROOT: SANDBOX, STORE_DIR: join(SANDBOX, 'store') }
})
vi.mock('../logger.js', () => ({
  // info and warn into one spy: the cap-passed line is a warn.
  logger: { info: (...a: unknown[]) => info(...a), warn: (...a: unknown[]) => info(...a), debug: vi.fn(), error: vi.fn() },
}))
vi.mock('../db.js', () => ({ createAgentMessage: vi.fn() }))
vi.mock('../web/channel-monitor.js', () => ({
  hardRestartMarveenChannels: vi.fn(() => ({ ok: true })),
  lastMainRespawnAt: () => null,
  MARVEEN_POST_RESPAWN_GRACE_MS: 0,
  markAgentRestartPending: vi.fn(),
}))
vi.mock('../web/stuck-tool-call-watcher.js', () => ({ shouldDeferForRecentRespawn: () => false }))
vi.mock('../web/agent-config.js', () => ({
  listAgentNames: () => ['dave'],
  listAllAgentNames: () => ['dave'],
  agentDir: (n: string) => join(SANDBOX, 'agents', n),
  readAgentModel: () => null,
  readAgentRemoteHost: () => null,
}))
vi.mock('../web/context-guard-store.js', async () => {
  const { DEFAULT_CONTEXT_GUARD } = await import('../context-guard.js')
  return { readContextGuardConfig: () => ({ ...DEFAULT_CONTEXT_GUARD, enabled: true }) }
})
vi.mock('../web/agent-process.js', () => ({
  clearFeedbackModalAndRecheck: () => false,
  agentRunState: (n: string) => (n === 'dave' ? 'running' : 'stopped'),
  agentSessionName: (n: string) => `agent-${n}`,
  restartAgentProcess: vi.fn(),
  capturePane: (s: string) => (s === 'agent-dave' ? tmux.pane : null),
  paneInstanceKey: (s: string) => (s === 'agent-dave' ? tmux.key : null),
  sendPromptToSession: vi.fn(),
  isSessionReadyForPrompt: async () => false,
  noteSaturationBannerUntrusted: vi.fn(),
  clearSaturationBannerOverride: vi.fn(),
}))

type Runner = typeof import('../web/context-guard-runner.js')
const first = await import('../web/context-guard-runner.js') as Runner
const { bgShellRestore, bgShellPersistDue, BG_SHELL_RESTORE_MAX_GAP_MS, BG_SHELL_PERSIST_EVERY_MS,
  BG_SHELL_ZERO_DROP_MS, BG_SHELL_WAIT_MAX_MS, INTERVAL_MS } = first

const SEP = '─'.repeat(100)
function pane(footer: string): string {
  return ['⏺ Kész.', '', `${SEP} Dave ─`, '❯ ', SEP, `  ${footer}`].join('\n')
}
const IDLE_ONE_SHELL = pane('⏵⏵ bypass permissions on · 1 shell')
const NO_SHELL = pane('⏵⏵ bypass permissions on (shift+tab to cycle)')

const KEY = '1795200000:4242'
const NOW = 2_000_000_000_000
const entry = (o: Partial<Record<string, unknown>> = {}) =>
  ({ key: KEY, sinceMs: NOW - 20 * 60_000, seenMs: NOW - 60_000, zeroStreak: 0, ...o })

describe('bgShellRestore (pure)', () => {
  it('the same pane process, a recent sighting: the clock comes back with its start', () => {
    expect(bgShellRestore(entry(), KEY, NOW)).toEqual({ sinceMs: NOW - 20 * 60_000, zeroStreak: 0 })
    expect(bgShellRestore(entry({ zeroStreak: 1, zeroSinceMs: NOW - 90_000 }), KEY, NOW))
      .toEqual({ sinceMs: NOW - 20 * 60_000, zeroStreak: 1, zeroSinceMs: NOW - 90_000 })
  })
  it('another pane process or none read: dropped', () => {
    expect(bgShellRestore(entry(), '1795200000:4243', NOW)).toBeNull()
    expect(bgShellRestore(entry(), '1795209999:4242', NOW)).toBeNull()
    expect(bgShellRestore(entry(), null, NOW)).toBeNull()
  })
  it('the gap bound: one sweep plus the zero-drop bound; at it restored, past it dropped', () => {
    expect(BG_SHELL_RESTORE_MAX_GAP_MS).toBe(INTERVAL_MS + BG_SHELL_ZERO_DROP_MS)
    expect(bgShellRestore(entry({ seenMs: NOW - BG_SHELL_RESTORE_MAX_GAP_MS }), KEY, NOW)).not.toBeNull()
    expect(bgShellRestore(entry({ seenMs: NOW - BG_SHELL_RESTORE_MAX_GAP_MS - 1 }), KEY, NOW)).toBeNull()
  })
  it('a sighting from the future, a start after the sighting, malformed fields: dropped', () => {
    expect(bgShellRestore(entry({ seenMs: NOW + 1 }), KEY, NOW)).toBeNull()
    expect(bgShellRestore(entry({ sinceMs: NOW - 30_000 }), KEY, NOW)).toBeNull()
    expect(bgShellRestore(entry({ sinceMs: '1' }), KEY, NOW)).toBeNull()
    expect(bgShellRestore(entry({ seenMs: Number.NaN }), KEY, NOW)).toBeNull()
    expect(bgShellRestore(entry({ zeroStreak: undefined }), KEY, NOW)).toBeNull()
    expect(bgShellRestore(entry({ zeroSinceMs: 'x' }), KEY, NOW)).toBeNull()
    expect(bgShellRestore(null, KEY, NOW)).toBeNull()
    expect(bgShellRestore([entry()], KEY, NOW)).toBeNull()
    expect(bgShellRestore(entry({ key: undefined }), KEY, NOW)).toBeNull()
  })
  it('Viktor r1 (1): a zero-run start before the clock or after the last sighting is dropped', () => {
    expect(bgShellRestore(entry({ zeroSinceMs: NOW + 60 * 60_000 }), KEY, NOW)).toBeNull()
    expect(bgShellRestore(entry({ zeroSinceMs: NOW - 60_000 + 1 }), KEY, NOW)).toBeNull()
    expect(bgShellRestore(entry({ zeroSinceMs: NOW - 20 * 60_000 - 1 }), KEY, NOW)).toBeNull()
    expect(bgShellRestore(entry({ zeroSinceMs: NOW - 20 * 60_000 }), KEY, NOW)).not.toBeNull()
    expect(bgShellRestore(entry({ zeroSinceMs: NOW - 60_000 }), KEY, NOW)).not.toBeNull()
  })
  it('a negative or fractional streak is clamped, not trusted', () => {
    expect(bgShellRestore(entry({ zeroStreak: -3 }), KEY, NOW)?.zeroStreak).toBe(0)
    expect(bgShellRestore(entry({ zeroStreak: 1.7 }), KEY, NOW)?.zeroStreak).toBe(1)
  })
})

describe('bgShellPersistDue (pure)', () => {
  const p = { key: KEY, sinceMs: NOW - 60_000, seenMs: NOW - 30_000, zeroStreak: 0 }
  it('no clock: a write only if an entry is still there', () => {
    expect(bgShellPersistDue(undefined, undefined)).toBe(false)
    expect(bgShellPersistDue(p, undefined)).toBe(true)
  })
  it('a new clock, or any field but the sighting changed: a write', () => {
    expect(bgShellPersistDue(undefined, { ...p, seenMs: NOW })).toBe(true)
    expect(bgShellPersistDue(p, { ...p, sinceMs: NOW, seenMs: NOW })).toBe(true)
    expect(bgShellPersistDue(p, { ...p, zeroStreak: 1 })).toBe(true)
    expect(bgShellPersistDue(p, { ...p, zeroSinceMs: NOW })).toBe(true)
    expect(bgShellPersistDue(p, { ...p, key: '1:2' })).toBe(true)
  })
  it('only the sighting moved: written once it is BG_SHELL_PERSIST_EVERY_MS old', () => {
    expect(bgShellPersistDue(p, { ...p, seenMs: p.seenMs + BG_SHELL_PERSIST_EVERY_MS - 1 })).toBe(false)
    expect(bgShellPersistDue(p, { ...p, seenMs: p.seenMs + BG_SHELL_PERSIST_EVERY_MS })).toBe(true)
  })
})

// The runner end to end: a sweep with a shell running writes the clock; a second
// runner module (a dashboard restart) restores it, so the cap counts from the first
// sighting and passes.
describe('the clock across a dashboard restart (runner, fake timers)', () => {
  const T0 = NOW
  // The first sweep runs INITIAL_DELAY_MS after the runner starts.
  const INITIAL_DELAY_MS = 270_000
  beforeEach(() => {
    rmSync(STORE_FILE, { force: true })
    info.mockClear()
    tmux.key = KEY
    tmux.pane = IDLE_ONE_SHELL
  })
  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
  })
  const stored = () => JSON.parse(readFileSync(STORE_FILE, 'utf-8')) as Record<string, Record<string, unknown>>
  const logged = (msg: string) => info.mock.calls.some((c) => c[1] === msg)
  /** A fresh runner module: the same mocks, new in-memory state (the dashboard restarted). */
  async function freshRunner(): Promise<Runner> {
    vi.resetModules()
    return await import('../web/context-guard-runner.js') as Runner
  }
  async function startAt(r: Runner, startMs: number): Promise<void> {
    vi.clearAllTimers()
    vi.setSystemTime(startMs)
    r.startContextGuardRunner()
    await vi.advanceTimersByTimeAsync(INITIAL_DELAY_MS)
  }

  const CAP_PASSED = 'context-guard: background shell still running past the wait cap -- restarts no longer wait for it'
  const firstSeen = T0 + INITIAL_DELAY_MS
  /** The restarted runner sweeps on until at least one sweep ran past the cap counted
   *  from the FIRST sighting (one interval more, so the last sweep is past it). With a
   *  new clock (the control) the same stretch ends before that clock's cap. */
  async function runUntilFirstCap(): Promise<void> {
    while (Date.now() < firstSeen + BG_SHELL_WAIT_MAX_MS + INTERVAL_MS) await vi.advanceTimersByTimeAsync(INTERVAL_MS)
  }

  it('the first runner writes the clock; the restarted one keeps its start, and the cap passes on time', async () => {
    vi.useFakeTimers({ now: T0 })
    await startAt(await freshRunner(), T0)
    expect(stored().dave).toMatchObject({ key: KEY, sinceMs: firstSeen, zeroStreak: 0 })
    expect(logged('context-guard: background shell running -- the pane counts as busy, restarts wait until it ends or the cap passes')).toBe(true)

    // The dashboard restarts 1 minute after that sweep: the clock is restored.
    const r2 = await freshRunner()
    info.mockClear()
    await startAt(r2, firstSeen + 60_000)
    expect(logged('context-guard: background-shell clock restored after a dashboard restart')).toBe(true)
    expect(stored().dave.sinceMs).toBe(firstSeen)
    await runUntilFirstCap()
    expect(logged(CAP_PASSED)).toBe(true)
    expect(stored().dave.sinceMs).toBe(firstSeen)
  })

  it('control: without the stored file (the behaviour on main) the restart starts a new clock and the cap is not due', async () => {
    vi.useFakeTimers({ now: T0 })
    await startAt(await freshRunner(), T0)
    rmSync(STORE_FILE)
    const r2 = await freshRunner()
    info.mockClear()
    await startAt(r2, firstSeen + 60_000)
    expect(stored().dave.sinceMs).toBe(firstSeen + 60_000 + INITIAL_DELAY_MS)
    await runUntilFirstCap()
    expect(logged(CAP_PASSED)).toBe(false)
  })

  it('another pane process after the restart (the agent was restarted): dropped, a new clock', async () => {
    vi.useFakeTimers({ now: T0 })
    await startAt(await freshRunner(), T0)
    tmux.key = '1795209999:5151'
    const r2 = await freshRunner()
    const start2 = T0 + INITIAL_DELAY_MS + 60_000
    await startAt(r2, start2)
    expect(logged('context-guard: persisted background-shell clock dropped (another pane process, malformed, or too old)')).toBe(true)
    expect(stored().dave).toMatchObject({ key: '1795209999:5151', sinceMs: start2 + INITIAL_DELAY_MS })
  })

  it('a gap longer than the bound: dropped, a new clock', async () => {
    vi.useFakeTimers({ now: T0 })
    await startAt(await freshRunner(), T0)
    const r2 = await freshRunner()
    const start2 = T0 + INITIAL_DELAY_MS + BG_SHELL_RESTORE_MAX_GAP_MS
    await startAt(r2, start2)
    expect(stored().dave.sinceMs).toBe(start2 + INITIAL_DELAY_MS)
  })

  it('the shell ends: the entry is removed with the clock', async () => {
    vi.useFakeTimers({ now: T0 })
    await startAt(await freshRunner(), T0)
    expect(stored().dave).toBeDefined()
    tmux.pane = NO_SHELL
    // Two idle readings of 0 drop the clock (BG_SHELL_CLEAR_IDLE_READINGS).
    await vi.advanceTimersByTimeAsync(2 * INTERVAL_MS)
    expect(existsSync(STORE_FILE)).toBe(true)
    expect(stored().dave).toBeUndefined()
  })

  it('Viktor r1 (2): a clock that started while tmux gave no key is never persisted, even once a key appears', async () => {
    vi.useFakeTimers({ now: T0 })
    tmux.key = null
    await startAt(await freshRunner(), T0)
    expect(existsSync(STORE_FILE) && stored().dave !== undefined).toBe(false)
    // The agent restarted meanwhile: a new pane process answers now, the same clock still runs in memory.
    tmux.key = '1795209999:5151'
    await vi.advanceTimersByTimeAsync(INTERVAL_MS)
    expect(existsSync(STORE_FILE) && stored().dave !== undefined).toBe(false)
  })

  it('Viktor r1 (3): a link planted at the old fixed tmp path is not followed', async () => {
    const victim = join(SANDBOX, 'victim.txt')
    writeFileSync(victim, 'untouched')
    const planted = `${STORE_FILE}.tmp`
    rmSync(planted, { force: true })
    symlinkSync(victim, planted)
    try {
      vi.useFakeTimers({ now: T0 })
      await startAt(await freshRunner(), T0)
      expect(readFileSync(victim, 'utf-8')).toBe('untouched')
      expect(lstatSync(STORE_FILE).isSymbolicLink()).toBe(false)
      expect(stored().dave).toMatchObject({ key: KEY, sinceMs: T0 + INITIAL_DELAY_MS })
    } finally {
      rmSync(planted, { force: true })
      rmSync(victim, { force: true })
    }
  })

  it('a hand-written garbage file does not break the sweep', async () => {
    writeFileSync(STORE_FILE, '{not json')
    vi.useFakeTimers({ now: T0 })
    await startAt(await freshRunner(), T0)
    expect(stored().dave).toMatchObject({ key: KEY, sinceMs: T0 + INITIAL_DELAY_MS })
  })
})
