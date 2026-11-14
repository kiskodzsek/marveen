import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import type { ScheduledTask } from '../web/scheduled-tasks-io.js'

// DATEDONCE1115 (card cb2c20bc): a dated one-off cron through the REAL runner
// tick. Its day over -> its task-config.json is rewritten with enabled:false (the
// rest kept); a dated task still ahead, a daily cron and a runAt one-shot are not.
// Harness copied from once-schedule-runner.test.ts; the task dir is a real temp dir.

const mockAppendTaskRun = vi.fn()
const mockRemove = vi.fn()
const H = vi.hoisted(() => {
  const fs = require('node:fs') as typeof import('node:fs'); const os = require('node:os') as typeof import('node:os'); const path = require('node:path') as typeof import('node:path')
  return { dir: fs.mkdtempSync(path.join(os.tmpdir(), 'dated-once-runner-')) }
})
const mockWrite = vi.fn()
const mockListScheduledTasks = vi.fn(() => [] as ScheduledTask[])
const sentPrompts: Array<{ session: string; prompt: string }> = []

vi.mock('../logger.js', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), debug: vi.fn(), error: vi.fn() },
}))

vi.mock('../web/atomic-write.js', () => ({
  atomicWriteFileSync: (...a: unknown[]) => mockWrite(...a),
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
  SCHEDULED_TASKS_DIR: H.dir,
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

// 2026-11-15 10:30 local: the 9 November task's day (and its 3 h catch-up) is over.
const NOW = new Date(2026, 10, 15, 10, 30).getTime()
const CREATED = Math.floor(new Date(2026, 10, 8, 12).getTime() / 1000)

function task(overrides: Partial<ScheduledTask> & { name: string }): ScheduledTask {
  return {
    description: 'dated-once fixture',
    prompt: 'Measure.',
    schedule: '55 10 9 11 *',
    agent: 'curagent',
    enabled: true,
    createdAt: CREATED,
    type: 'task',
    telegramChatId: 'none',
    ...overrides,
  }
}

function onDisk(t: ScheduledTask) {
  mkdirSync(join(H.dir, t.name), { recursive: true })
  writeFileSync(join(H.dir, t.name, 'task-config.json'), JSON.stringify({ schedule: t.schedule, agent: t.agent, enabled: true, createdAt: t.createdAt, type: t.type }))
  return t
}

async function runOneTick() {
  vi.resetModules()
  const { startScheduleRunner } = await import('../web/schedule-runner.js')
  const stop = startScheduleRunner()
  await vi.advanceTimersByTimeAsync(6_000)
  clearInterval(stop)
}

const writesTo = (name: string) => mockWrite.mock.calls.filter(c => c[0] === join(H.dir, name, 'task-config.json'))

describe('schedule runner: a dated one-off cron is switched off after its day', () => {
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

  afterAll(() => rmSync(H.dir, { recursive: true, force: true }))

  it('rewrites the expired one with enabled:false, keeps the rest, and does not fire it', async () => {
    mockListScheduledTasks.mockReturnValue([onDisk(task({ name: 'szigma-meta-24h-1109', targetSession: 'dated-session' }))])
    await runOneTick()
    const w = writesTo('szigma-meta-24h-1109')
    expect(w).toHaveLength(1)
    expect(JSON.parse(w[0][1] as string)).toEqual({ schedule: '55 10 9 11 *', agent: 'curagent', enabled: false, createdAt: CREATED, type: 'task' })
    expect(sentPrompts).toHaveLength(0)
    expect(mockRemove).not.toHaveBeenCalled()
  })

  it.each([
    ['a dated task still ahead', { name: 'ahead-1119', schedule: '0 8 19 11 *' }],
    ['a daily cron', { name: 'daily', schedule: '0 8 * * *' }],
    ['a runAt one-shot (the runner removes that one itself)', { name: 'once-ahead', runAt: NOW + 60 * 60_000 }],
  ])('leaves %s alone', async (_label, o) => {
    mockListScheduledTasks.mockReturnValue([onDisk(task(o as Partial<ScheduledTask> & { name: string }))])
    await runOneTick()
    expect(writesTo(o.name)).toHaveLength(0)
  })

  // Viktor 42609 LOW: the listed name comes from the SKILL.md frontmatter. A planted
  // task whose frontmatter names a live guard (or a path outside the task dir) and
  // whose own cron is an expired dated one must not switch that other config off.
  it('a frontmatter name pointing at a live task or outside the task dir writes nothing', async () => {
    mkdirSync(join(H.dir, 'live-guard'), { recursive: true })
    writeFileSync(join(H.dir, 'live-guard', 'task-config.json'), JSON.stringify({ schedule: '*/5 * * * *', agent: 'kernel', enabled: true, createdAt: CREATED - 86_400 }))
    mockListScheduledTasks.mockReturnValue([task({ name: 'live-guard' }), task({ name: '../outside/x' })])
    await runOneTick()
    expect(mockWrite.mock.calls.filter(c => String(c[0]).endsWith('task-config.json'))).toHaveLength(0)
  })
})
