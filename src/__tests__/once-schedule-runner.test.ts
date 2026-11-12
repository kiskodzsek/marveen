import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ScheduledTask } from '../web/scheduled-tasks-io.js'

// ONCE (card fd941954): a one-shot task through the REAL runner tick.
//   * due (runAt <= now)          -> fires once, then its directory is removed;
//   * runAt in the future         -> nothing, even though its cron says "every minute";
//   * stale (far past catch-up)   -> recorded 'missed' and removed, never fired;
//   * a plain cron task           -> fires and is NOT removed (control).
// Harness copied from schedule-runner-fire-current-def.test.ts.

const mockAppendTaskRun = vi.fn()
const mockRemove = vi.fn()
const mockListScheduledTasks = vi.fn(() => [] as ScheduledTask[])
const sentPrompts: Array<{ session: string; prompt: string }> = []

vi.mock('../logger.js', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), debug: vi.fn(), error: vi.fn() },
}))

vi.mock('../web/atomic-write.js', () => ({
  atomicWriteFileSync: vi.fn(),
}))

vi.mock('../db.js', () => ({
  appendTaskRun: (...a: unknown[]) => mockAppendTaskRun(...a),
  listPendingTaskRetries: () => [],
  getPendingTaskRetry: () => undefined,
  deletePendingTaskRetry: vi.fn(),
  updatePendingTaskRetry: vi.fn(() => true),
  insertPendingTaskRetryIfNew: vi.fn(),
  markPendingTaskRetryAlert: vi.fn(() => false),
  clearPendingTaskRetryAlert: vi.fn(),
  markScheduledTaskKanbanWaiting: vi.fn(),
}))

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
  readScheduledTask: (n: string) => mockListScheduledTasks().find(t => t.name === n) ?? null,
  removeScheduledTaskDir: (n: string) => mockRemove(n),
  SCHEDULED_TASKS_DIR: '/tmp/marveen-once-runner-no-tasks-dir',
  SCHEDULED_TASK_INLINE_MAX_CHARS: 1_500,
  SCHEDULED_TASK_BODY_WARN_CHARS: 20_000,
  MAX_SCHEDULED_TASK_PROMPT_LEN: 50_000,
}))

vi.mock('../web/agent-process.js', () => ({
  clearFeedbackModalAndRecheck: () => false,
  agentSessionName: (name: string) => `agent-${name}`,
  isAgentRunning: () => true,
  isSessionReadyForPrompt: () => true,
  sendPromptToSession: async (session: string, prompt: string) => {
    sentPrompts.push({ session, prompt })
    return 'sent'
  },
  startAgentProcess: vi.fn(() => ({ ok: false, error: 'not in tests' })),
  sessionExistsOnHost: () => true,
  capturePane: () => null,
  sendEnterToSession: vi.fn(),
  clearStaleParkedInput: vi.fn(() => false),
  resolveAgentProvider: () => 'telegram',
}))

const NOW = Date.parse('2026-07-31T10:30:00.000Z')

function task(overrides: Partial<ScheduledTask> & { name: string }): ScheduledTask {
  return {
    description: 'once-runner fixture',
    prompt: 'Wake up and continue.',
    schedule: '* * * * *',
    agent: 'curagent',
    enabled: true,
    createdAt: 0,
    type: 'task',
    telegramChatId: 'none',
    ...overrides,
  }
}

async function runOneTick() {
  vi.resetModules()
  const { startScheduleRunner } = await import('../web/schedule-runner.js')
  const stop = startScheduleRunner()
  await vi.advanceTimersByTimeAsync(6_000)
  clearInterval(stop)
}

describe('schedule runner: one-shot (runAt) tasks', () => {
  beforeEach(() => {
    vi.stubEnv('SCHEDULER_TZ', 'Europe/Budapest')
    vi.clearAllMocks()
    vi.useFakeTimers()
    vi.setSystemTime(new Date(NOW))
    sentPrompts.length = 0
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllEnvs()
  })

  it('fires a due once-task exactly once and removes it', async () => {
    mockListScheduledTasks.mockReturnValue([task({ name: 'once-due', runAt: NOW, targetSession: 'once-session' })])
    await runOneTick()
    expect(sentPrompts.filter(p => p.session === 'once-session')).toHaveLength(1)
    expect(mockRemove).toHaveBeenCalledWith('once-due')
    expect(mockAppendTaskRun).toHaveBeenCalledWith('once-due', 'curagent', expect.stringMatching(/^fired/))
  })

  it('ignores the cron of a once-task whose runAt is still ahead', async () => {
    mockListScheduledTasks.mockReturnValue([task({ name: 'once-later', runAt: NOW + 15 * 60_000, targetSession: 'later-session' })])
    await runOneTick()
    expect(sentPrompts).toHaveLength(0)
    expect(mockRemove).not.toHaveBeenCalled()
  })

  it('records a stale once-task as missed and removes it without firing', async () => {
    mockListScheduledTasks.mockReturnValue([task({ name: 'once-stale', runAt: NOW - 6 * 60 * 60_000, targetSession: 'stale-session' })])
    await runOneTick()
    expect(sentPrompts).toHaveLength(0)
    expect(mockAppendTaskRun).toHaveBeenCalledWith('once-stale', 'curagent', 'missed')
    expect(mockRemove).toHaveBeenCalledWith('once-stale')
  })

  it('control: a plain cron task fires and is not removed', async () => {
    mockListScheduledTasks.mockReturnValue([task({ name: 'plain-cron', targetSession: 'plain-session' })])
    await runOneTick()
    expect(sentPrompts.filter(p => p.session === 'plain-session')).toHaveLength(1)
    expect(mockRemove).not.toHaveBeenCalled()
  })
})
