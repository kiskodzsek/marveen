import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ScheduledTask } from '../web/scheduled-tasks-io.js'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

// A pending retry whose target session is MISSING (and whose auto-start fails)
// must survive the tick, not be deleted. Deleting it was a silent abandonment
// that contradicts the never-abandon policy the queue exists for: the one
// real-world window where it bites is a target session vanishing during a
// main-agent restart -- auto-start fails once, and a queued daily task (e.g. a
// morning briefing) is dropped with only a debug log.
//
// What this pins:
//   * result 'missing' does NOT delete the retry row;
//   * the run-log records the TRANSITION into missing exactly once
//     ('missing-retrying'), not one row per 60s tick;
//   * the row's last_reason is refreshed to 'missing' so the age-based
//     operator alert path keeps working;
//   * result 'fired' still deletes the row (the queue drains normally).

const mockAppendTaskRun = vi.fn()
const mockInsertPendingRetry = vi.fn()
const mockDeletePendingRetry = vi.fn()
// Mirrors the real DB: refreshing the row updates its last_reason, so the
// NEXT tick sees the state this tick wrote (the transition-dedup depends on
// exactly that).
const mockUpdatePendingRetry = vi.fn((taskName: unknown, _agent: unknown, _now: unknown, reason: unknown) => {
  for (const row of mockListPendingRetries() as Array<Record<string, unknown>>) {
    if (row.task_name === taskName) row.last_reason = reason
  }
  return true
})
const mockListPendingRetries = vi.fn(() => [] as unknown[])
const mockSendPrompt = vi.fn(() => 'sent')
const mockSessionExists = vi.fn(() => true)
const mockStartAgent = vi.fn(() => ({ ok: false, error: 'tmux unavailable' }))
const mockListScheduledTasks = vi.fn(() => [] as ScheduledTask[])

vi.mock('../logger.js', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), debug: vi.fn(), error: vi.fn() },
}))

// The runner persists its last-run map to store/schedule-last-run.json on every
// fire. Stub the writer so the suite never touches the operator's real store.
vi.mock('../web/atomic-write.js', () => ({
  atomicWriteFileSync: vi.fn(),
}))

vi.mock('../db.js', () => ({
  appendTaskRun: (...a: unknown[]) => mockAppendTaskRun(...a),
  listPendingTaskRetries: () => mockListPendingRetries(),
  deletePendingTaskRetry: (...a: unknown[]) => mockDeletePendingRetry(...a),
  updatePendingTaskRetry: mockUpdatePendingRetry,
  insertPendingTaskRetryIfNew: (...a: unknown[]) => mockInsertPendingRetry(...a),
  markPendingTaskRetryAlert: vi.fn(() => false),
  clearPendingTaskRetryAlert: vi.fn(),
  markScheduledTaskKanbanWaiting: vi.fn(),
}))

// The runner's alert paths resolve a REAL bot token from install-level config
// (HOME-based, so a test worktree does not isolate them) and send to the real
// owner chat. Neutralize the sink entirely: a green suite must never cost the
// operator's attention.
// The runner sends over getProvider(CHANNEL_PROVIDER) since the provider-aware
// alerts (not sendTelegramMessage any more), so THAT is the export to
// neutralize; everything else in channel-provider stays real.
vi.mock('../channel-provider.js', async (importOriginal) => {
  const real = await importOriginal<typeof import('../channel-provider.js')>()
  return {
    ...real,
    getProvider: (type: Parameters<typeof real.getProvider>[0]) => ({
      ...real.getProvider(type),
      sendMessage: vi.fn(async () => {}),
      sendPhoto: vi.fn(async () => {}),
    }),
  }
})

vi.mock('../web/scheduled-tasks-io.js', () => ({
  listScheduledTasks: () => mockListScheduledTasks(),
  readScheduledTask: (n: string) => (mockListScheduledTasks() as Array<{ name: string }>).find(t => t.name === n) ?? null,
  SCHEDULED_TASKS_DIR: '/tmp/marveen-retry-missing-no-tasks-dir',
  // SCHEDPROMPTREF917: attemptFireTask reads these on every fire (size-guard
  // + inline/snapshot threshold). Real values -- the fixtures' short prompts
  // must stay well under them so the size-guard/snapshot path never trips.
  SCHEDULED_TASK_INLINE_MAX_CHARS: 1_500,
  SCHEDULED_TASK_BODY_WARN_CHARS: 20_000,
  MAX_SCHEDULED_TASK_PROMPT_LEN: 50_000,
}))

vi.mock('../web/agent-process.js', () => ({
  // The not-ready-path modal clear: false = no modal, so every caller keeps
  // its existing skip/busy behaviour and these fixtures are unaffected.
  clearFeedbackModalAndRecheck: () => false,
  agentSessionName: (name: string) => `agent-${name}`,
  isAgentRunning: () => true,
  isSessionReadyForPrompt: () => true,
  sendPromptToSession: (...a: unknown[]) => mockSendPrompt(...(a as [])),
  startAgentProcess: (...a: unknown[]) => mockStartAgent(...(a as [])),
  sessionExistsOnHost: () => mockSessionExists(),
  // null capture => the post-send resubmit loop sees nothing parked and stops.
  capturePane: () => null,
  sendEnterToSession: vi.fn(),
  clearStaleParkedInput: vi.fn(() => false),
  resolveAgentProvider: () => 'telegram',
}))

function task(overrides: Partial<ScheduledTask> & { name: string; schedule: string }): ScheduledTask {
  return {
    description: 'retry-missing fixture',
    prompt: 'Do the thing.',
    agent: 'retryagent',
    enabled: true,
    createdAt: 0,
    type: 'task',
    targetSession: 'retry-test-session',
    ...overrides,
  }
}

const DAILY = task({ name: 'retry-missing-e2e-daily', schedule: '0 8 * * *' })

function retryRow(overrides: Record<string, unknown> = {}) {
  return {
    task_name: DAILY.name,
    agent_name: 'retryagent',
    first_attempt: Date.now() - 5 * 60000,
    last_attempt: Date.now() - 60000,
    attempt_count: 5,
    last_reason: 'busy',
    alerted_at: null,
    ...overrides,
  }
}

async function loadRunner() {
  vi.resetModules()
  return await import('../web/schedule-runner.js')
}

async function runOneTick() {
  const { startScheduleRunner } = await loadRunner()
  const stop = startScheduleRunner()
  // First tick is scheduled, not immediate: advance past the 60s interval and
  // let the async tick body drain.
  await vi.advanceTimersByTimeAsync(61_000)
  clearInterval(stop)
}

describe('schedule runner: pending retry survives a missing target session', () => {
  beforeEach(() => {
    vi.stubEnv('SCHEDULER_TZ', 'Europe/Budapest')
    vi.clearAllMocks()
    vi.useFakeTimers()
    // A quiet moment (no cron occurrence for the fixture) so only the
    // pending-retry loop acts.
    vi.setSystemTime(new Date('2026-07-31T10:30:00.000Z'))
    mockListScheduledTasks.mockReturnValue([DAILY])
    // The target session is gone and auto-start fails => attemptFireTask
    // resolves 'missing'.
    mockSessionExists.mockReturnValue(false)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllEnvs()
  })

  it("keeps the retry row on 'missing' and logs the transition once across ticks", async () => {
    mockListPendingRetries.mockReturnValue([retryRow()])
    await runOneTick()

    // The row survives...
    expect(mockDeletePendingRetry).not.toHaveBeenCalled()
    // ...its live state is refreshed to 'missing' (feeds the age-based alert)...
    expect(mockUpdatePendingRetry).toHaveBeenCalledWith(DAILY.name, 'retryagent', expect.any(Number), 'missing')
    // ...and the run-log records the TRANSITION exactly once, even though the
    // runner ticked several times inside the window -- a stuck-missing task
    // must not write a run-log row per tick.
    const runs = mockAppendTaskRun.mock.calls.filter(c => c[0] === DAILY.name).map(c => String(c[2]))
    expect(runs).toEqual(['missing-retrying'])
  })

  it('does not re-log a retry already known to be missing', async () => {
    mockListPendingRetries.mockReturnValue([retryRow({ last_reason: 'missing' })])
    await runOneTick()

    expect(mockDeletePendingRetry).not.toHaveBeenCalled()
    const runs = mockAppendTaskRun.mock.calls.filter(c => c[0] === DAILY.name).map(c => String(c[2]))
    expect(runs).toEqual([])
  })

  it("still deletes the row when the retry finally fires", async () => {
    mockSessionExists.mockReturnValue(true)
    mockListPendingRetries.mockReturnValue([retryRow()])
    await runOneTick()

    expect(mockDeletePendingRetry).toHaveBeenCalledWith(DAILY.name, 'retryagent')
  })
})

// SCHEDREFUSED1115 (card 97379849): a start refused by the agent's own config ('oauthTokenFile: ...', e.g. the
// Codex-bridge majsztro) cannot succeed on a later tick. Measured 2026-11-13 10:08 -> 2026-11-15 14:40: one retry row
// for such a target restarted it every tick, 12 625 times, and never delivered. It ends the row with one run-log line.
describe("schedule runner: a target whose config refuses a session is not retried", () => {
  beforeEach(() => {
    vi.stubEnv('SCHEDULER_TZ', 'Europe/Budapest')
    vi.clearAllMocks()
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-31T10:30:00.000Z'))
    mockListScheduledTasks.mockReturnValue([DAILY])
    mockSessionExists.mockReturnValue(false)
  })
  afterEach(() => {
    mockStartAgent.mockImplementation(() => ({ ok: false, error: 'tmux unavailable' }))
    mockListPendingRetries.mockImplementation(() => [])
    mockDeletePendingRetry.mockImplementation(() => {})
    vi.useRealTimers()
    vi.unstubAllEnvs()
  })

  it("pending retry + 'oauthTokenFile: non-claude-model' -> row deleted, run-log 'refused', one start attempt", async () => {
    mockStartAgent.mockImplementation(() => ({ ok: false, error: 'oauthTokenFile: non-claude-model' }))
    // Like the real table: a deleted row is gone on the next tick (the runner ticks several times in the window).
    const rows = [retryRow({ last_reason: 'missing' })]
    mockListPendingRetries.mockImplementation(() => rows)
    mockDeletePendingRetry.mockImplementation(() => { rows.length = 0 })
    await runOneTick()
    expect(mockDeletePendingRetry).toHaveBeenCalledWith(DAILY.name, 'retryagent')
    expect(mockUpdatePendingRetry).not.toHaveBeenCalled()
    const runs = mockAppendTaskRun.mock.calls.filter(c => c[0] === DAILY.name).map(c => String(c[2]))
    expect(runs).toEqual(['refused'])
    expect(mockStartAgent).toHaveBeenCalledTimes(1)
  })

  it("any other start failure is still 'missing': the row is kept (never-abandon unchanged)", async () => {
    mockStartAgent.mockImplementation(() => ({ ok: false, error: 'Agent not found' }))
    mockListPendingRetries.mockReturnValue([retryRow()])
    await runOneTick()
    expect(mockDeletePendingRetry).not.toHaveBeenCalled()
    expect(mockUpdatePendingRetry).toHaveBeenCalledWith(DAILY.name, 'retryagent', expect.any(Number), 'missing')
  })

  it("a cron fire on such a target queues no retry and writes 'refused'", async () => {
    // 10:30Z = 12:30 Budapest (CEST); the tick after 61 s lands in minute 12:31.
    const DUE = task({ name: 'retry-refused-cron', schedule: '31 12 * * *' })
    mockListScheduledTasks.mockReturnValue([DUE])
    mockListPendingRetries.mockReturnValue([])
    mockStartAgent.mockImplementation(() => ({ ok: false, error: 'oauthTokenFile: non-claude-model' }))
    await runOneTick()
    expect(mockStartAgent).toHaveBeenCalled()
    expect(mockInsertPendingRetry).not.toHaveBeenCalled()
    const runs = mockAppendTaskRun.mock.calls.filter(c => c[0] === DUE.name).map(c => String(c[2]))
    expect(runs).toEqual(['refused'])
  })
})

// Viktor 43041 LOW 1: only the CONFIG reasons are 'refused'. A token-file STATE (missing, empty, mode-too-open, ...)
// can pass by during a rotation, and config-unparseable can be a half-written save: those stay 'missing', the row is
// kept and the aged alert still fires.
describe('isConfigStartRefusal: config reasons only', () => {
  it('config reasons (with or without a detail) are refusals; token-file states and other errors are not', async () => {
    const { isConfigStartRefusal } = await loadRunner()
    for (const r of ['non-claude-model', 'main-agent', 'auth-mode-own_team', 'explicit-config-dir', 'not-absolute', 'not a Claude OAuth agent']) {
      expect(isConfigStartRefusal(`oauthTokenFile: ${r}`), r).toBe(true)
    }
    expect(isConfigStartRefusal('oauthTokenFile: path-bad-characters (x)')).toBe(true)
    for (const e of ['oauthTokenFile: missing', 'oauthTokenFile: empty', 'oauthTokenFile: mode-too-open (0644)',
      'oauthTokenFile: config-unparseable', 'oauthTokenFile: same-as-fleet-token', 'oauthTokenFile: non-claude-modelX',
      'tmux unavailable', 'Agent not found', '', undefined]) {
      expect(isConfigStartRefusal(e as string | undefined), String(e)).toBe(false)
    }
  })

  it('the list covers every oauthTokenFileConflict reason and every invalid-setting reason but config-unparseable', async () => {
    const { CONFIG_START_REFUSAL_REASONS } = await loadRunner()
    const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'web', 'agent-oauth-token-file.ts'), 'utf-8')
    const conflictBody = src.slice(src.indexOf('export function oauthTokenFileConflict'), src.indexOf('\n}\n', src.indexOf('export function oauthTokenFileConflict')))
    const conflict = [...conflictBody.matchAll(/return '([^']+)'/g)].map((m) => m[1])
    const invalid = [...src.matchAll(/state: 'invalid', reason: '([^']+)'/g)].map((m) => m[1])
    expect(conflict.length).toBeGreaterThanOrEqual(7)
    expect(invalid).toContain('config-unparseable')
    for (const r of [...conflict, ...invalid.filter((x) => x !== 'config-unparseable')]) {
      expect(CONFIG_START_REFUSAL_REASONS.has(r), r).toBe(true)
    }
    expect(CONFIG_START_REFUSAL_REASONS.has('config-unparseable')).toBe(false)
  })

  it("a pending retry on 'oauthTokenFile: missing' is kept (the row stays alive for the aged alert)", async () => {
    vi.stubEnv('SCHEDULER_TZ', 'Europe/Budapest')
    vi.clearAllMocks()
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-31T10:30:00.000Z'))
    mockListScheduledTasks.mockReturnValue([DAILY])
    mockSessionExists.mockReturnValue(false)
    mockStartAgent.mockImplementation(() => ({ ok: false, error: 'oauthTokenFile: missing' }))
    mockListPendingRetries.mockReturnValue([retryRow()])
    try {
      await runOneTick()
      expect(mockDeletePendingRetry).not.toHaveBeenCalled()
      expect(mockUpdatePendingRetry).toHaveBeenCalledWith(DAILY.name, 'retryagent', expect.any(Number), 'missing')
      const runs = mockAppendTaskRun.mock.calls.filter(c => c[0] === DAILY.name).map(c => String(c[2]))
      expect(runs).not.toContain('refused')
    } finally {
      mockStartAgent.mockImplementation(() => ({ ok: false, error: 'tmux unavailable' }))
      vi.useRealTimers()
      vi.unstubAllEnvs()
    }
  })
})
