// OWNERACTIVE1112 (Klodel 39538, Patrik TG 18102 "nagyon lassú vagy, lassan reaglsz az üzenetimre?"): a scheduled
// prompt for the MAIN agent is not typed into the main channels session while a human wrote to it in the last 15
// minutes. Driven through a real runner tick (the harness of feedback-modal-positive-scheduler.test.ts): a pending
// retry of a main-agent task, session present and ready.
//
//   inbound 5 min ago   -> NO send (negative test), the retry row survives;
//   inbound 20 min ago  -> the task fires;
//   no inbound at all   -> the task fires;
//   targetSession set   -> not the channels pane, fires even with a fresh inbound;
//   ledger read throws  -> fails open, fires.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ScheduledTask } from '../web/scheduled-tasks-io.js'

const mockAppendTaskRun = vi.fn()
// Mirrors the real DB: a fired retry's delete removes the row, so the next
// pass of the loop no longer sees it -- without this the fixture re-fires the
// same row on every pass inside the tick window.
let pendingRetries: Array<Record<string, unknown>> = []
const mockDeletePendingRetry = vi.fn((taskName: unknown, _agent?: unknown) => {
  pendingRetries = pendingRetries.filter((r) => r.task_name !== taskName)
})
const mockUpdatePendingRetry = vi.fn(() => true)
const mockListPendingRetries = vi.fn(() => pendingRetries)
const mockSendPrompt = vi.fn(() => 'sent')
const mockSessionExists = vi.fn(() => true)
const mockStartAgent = vi.fn(() => ({ ok: true }))
const mockListScheduledTasks = vi.fn(() => [] as ScheduledTask[])
const mockIsReady = vi.fn(() => false)
const mockClearModal = vi.fn(() => false)
const mockLastInboundAt = vi.fn((_a: string) => null as number | null)
let capturePaneCalls = 0

vi.mock('../logger.js', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), debug: vi.fn(), error: vi.fn() },
}))

vi.mock('../web/atomic-write.js', () => ({
  atomicWriteFileSync: vi.fn(),
}))

vi.mock('../db.js', () => ({
  appendTaskRun: (...a: unknown[]) => mockAppendTaskRun(...a),
  listPendingTaskRetries: () => mockListPendingRetries(),
  deletePendingTaskRetry: (...a: unknown[]) => mockDeletePendingRetry(a[0], a[1]),
  updatePendingTaskRetry: mockUpdatePendingRetry,
  insertPendingTaskRetryIfNew: vi.fn(),
  markPendingTaskRetryAlert: vi.fn(() => false),
  clearPendingTaskRetryAlert: vi.fn(),
  markScheduledTaskKanbanWaiting: vi.fn(),
  lastInboundAt: (a: string) => mockLastInboundAt(a),
}))

// Neutralize the real alert sink (would resolve a real bot token from
// install-level config) -- same rule as the sibling scheduler fixtures.
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
  SCHEDULED_TASKS_DIR: '/tmp/marveen-owner-active-no-tasks-dir',
  // SCHEDPROMPTREF917: attemptFireTask reads these on every fire (size-guard
  // + inline/snapshot threshold). Real values -- the fixtures' short prompts
  // must stay well under them so the size-guard/snapshot path never trips.
  SCHEDULED_TASK_INLINE_MAX_CHARS: 1_500,
  SCHEDULED_TASK_BODY_WARN_CHARS: 20_000,
  MAX_SCHEDULED_TASK_PROMPT_LEN: 50_000,
}))

vi.mock('../web/agent-process.js', () => ({
  clearFeedbackModalAndRecheck: (...a: unknown[]) => mockClearModal(...(a as [])),
  agentSessionName: (name: string) => `agent-${name}`,
  isAgentRunning: () => true,
  isSessionReadyForPrompt: (...a: unknown[]) => mockIsReady(...(a as [])),
  sendPromptToSession: (...a: unknown[]) => mockSendPrompt(...(a as [])),
  startAgentProcess: (...a: unknown[]) => mockStartAgent(...(a as [])),
  sessionExistsOnHost: () => mockSessionExists(),
  // First capture (the not-ready branch's first-run gate check) returns a
  // pane with NO first-run gate on it -- the earlier gate must pass through
  // to the helper, not swallow the modal case. Every later capture (the
  // post-send resubmit loop) returns null so the loop sees nothing parked
  // and stops, same as the sibling fixtures.
  capturePane: (..._a: unknown[]) => (capturePaneCalls++ === 0 ? 'plain pane\n❯ ' : null),
  sendEnterToSession: vi.fn(),
  clearStaleParkedInput: vi.fn(() => false),
  resolveAgentProvider: () => 'telegram',
}))

const MAIN = 'marveen' // MAIN_AGENT_ID default (config.ts) -- the test env sets no MAIN_AGENT_ID

function task(overrides: Partial<ScheduledTask> & { name: string; schedule: string }): ScheduledTask {
  return {
    description: 'owner-active fixture',
    prompt: 'Do the thing.',
    agent: MAIN,
    enabled: true,
    createdAt: 0,
    type: 'heartbeat',
    ...overrides,
  }
}

const HB = task({ name: 'owner-active-heartbeat', schedule: '0 8 * * *' })

function retryRow(name = HB.name) {
  return {
    task_name: name,
    agent_name: MAIN,
    first_attempt: Date.now() - 5 * 60000,
    last_attempt: Date.now() - 60000,
    attempt_count: 1,
    last_reason: 'busy',
    alerted_at: null,
  }
}

async function runOneTick() {
  vi.resetModules()
  const { startScheduleRunner } = await import('../web/schedule-runner.js')
  const stop = startScheduleRunner()
  await vi.advanceTimersByTimeAsync(61_000)
  clearInterval(stop)
}

const NOW = new Date('2026-11-12T12:34:00.000Z')
const sec = (msAgo: number) => Math.floor((NOW.getTime() - msAgo) / 1000)

describe('ownerActiveDefers (pure)', () => {
  it('inside the window defers, outside does not, none does not, a future stamp defers', async () => {
    const { ownerActiveDefers, OWNER_ACTIVE_WINDOW_MS } = await import('../web/owner-activity.js')
    const now = NOW.getTime()
    expect(OWNER_ACTIVE_WINDOW_MS).toBe(15 * 60_000)
    expect(ownerActiveDefers(sec(5 * 60_000), now)).toBe(true)
    expect(ownerActiveDefers(sec(14 * 60_000 + 59_000), now)).toBe(true)
    expect(ownerActiveDefers(sec(15 * 60_000 + 1_000), now)).toBe(false)
    expect(ownerActiveDefers(null, now)).toBe(false)
    expect(ownerActiveDefers(Number.NaN, now)).toBe(false)
    expect(ownerActiveDefers(sec(-60_000), now)).toBe(true)
  })
})

describe('schedule runner: no scheduled prompt into the main channels pane while the owner is talking', () => {
  beforeEach(() => {
    vi.stubEnv('SCHEDULER_TZ', 'Europe/Budapest')
    vi.clearAllMocks()
    vi.useFakeTimers()
    // Quiet moment (no cron occurrence): only the pending-retry loop acts.
    vi.setSystemTime(NOW)
    mockListScheduledTasks.mockReturnValue([HB])
    mockSessionExists.mockReturnValue(true)
    mockIsReady.mockResolvedValue(true as never)
    mockClearModal.mockResolvedValue(false as never)
    mockLastInboundAt.mockReset()
    capturePaneCalls = 0
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllEnvs()
  })

  it('negative: Patrik wrote 5 minutes ago -> nothing is sent, the retry row survives', async () => {
    mockLastInboundAt.mockReturnValue(sec(5 * 60_000))
    pendingRetries = [retryRow()]
    await runOneTick()
    expect(mockLastInboundAt).toHaveBeenCalledWith(MAIN)
    expect(mockSendPrompt).not.toHaveBeenCalled()
    expect(mockDeletePendingRetry).not.toHaveBeenCalled()
  })

  it('quiet for 20 minutes -> the task fires', async () => {
    mockLastInboundAt.mockReturnValue(sec(20 * 60_000))
    pendingRetries = [retryRow()]
    await runOneTick()
    expect(mockSendPrompt).toHaveBeenCalledTimes(1)
    expect(mockDeletePendingRetry).toHaveBeenCalledWith(HB.name, MAIN)
  })

  it('no inbound at all -> the task fires', async () => {
    mockLastInboundAt.mockReturnValue(null)
    pendingRetries = [retryRow()]
    await runOneTick()
    expect(mockSendPrompt).toHaveBeenCalledTimes(1)
  })

  it('a task with its own targetSession is not held by owner activity', async () => {
    const own = task({ name: 'owner-active-own-session', schedule: '0 8 * * *', targetSession: 'other-pane' })
    mockListScheduledTasks.mockReturnValue([own])
    mockLastInboundAt.mockReturnValue(sec(60_000))
    pendingRetries = [retryRow(own.name)]
    await runOneTick()
    expect(mockSendPrompt).toHaveBeenCalledTimes(1)
  })

  it('a failing ledger read fails open -> the task fires', async () => {
    mockLastInboundAt.mockImplementation(() => { throw new Error('db locked') })
    pendingRetries = [retryRow()]
    await runOneTick()
    expect(mockSendPrompt).toHaveBeenCalledTimes(1)
  })
})
