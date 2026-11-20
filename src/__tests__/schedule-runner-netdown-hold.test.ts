import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ScheduledTask } from '../web/scheduled-tasks-io.js'
import { mkdtempSync, readFileSync, rmSync, symlinkSync, utimesSync, writeFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'

// Card 91d9911e (DREAM 11-19, measured 2026-11-18 20:12 - 11-19 00:42, Kernel 47551): the
// machine had no network for four and a half hours and 60 messages reached the main agent,
// all symptoms of that one outage; 49 were scheduler notices ("pane N perce foglalt",
// "N perce várakozik"). While the watchdog's net-down marker is fresh the scheduler now
// holds those notices and their owner escalations (the one-shot stamps are still set), and
// the first tick after the marker is gone sends ONE summary to the main agent.

const SANDBOX = mkdtempSync(join(tmpdir(), 'ndh-'))
afterAll(() => rmSync(SANDBOX, { recursive: true, force: true }))

// ---- the pure module --------------------------------------------------------
const { netdownSinceFromMarker, readNetdownSince, NetdownAlertHold, NETDOWN_FRESH_MS } =
  await vi.importActual<typeof import('../web/netdown-hold.js')>('../web/netdown-hold.js')

const NOW = Date.UTC(2026, 10, 18, 22, 0, 0)
const SINCE_S = Math.floor((NOW - 90 * 60_000) / 1000)

describe('netdownSinceFromMarker (pure)', () => {
  it('a fresh marker: the outage start from its first field', () => {
    expect(netdownSinceFromMarker(`${SINCE_S} ${SINCE_S + 1800}\n`, NOW - 60_000, NOW)).toBe(SINCE_S * 1000)
  })
  it('the freshness bound: three watchdog intervals; at it counts, past it not', () => {
    expect(NETDOWN_FRESH_MS).toBe(3 * 300_000)
    expect(netdownSinceFromMarker(`${SINCE_S} 0`, NOW - NETDOWN_FRESH_MS, NOW)).toBe(SINCE_S * 1000)
    expect(netdownSinceFromMarker(`${SINCE_S} 0`, NOW - NETDOWN_FRESH_MS - 1, NOW)).toBeNull()
  })
  it('an mtime from the future (beyond a minute of clock skew): not trusted', () => {
    expect(netdownSinceFromMarker(`${SINCE_S} 0`, NOW + 60_001, NOW)).toBeNull()
    expect(netdownSinceFromMarker(`${SINCE_S} 0`, NOW + 60_000, NOW)).toBe(SINCE_S * 1000)
  })
  it('an unreadable or future start falls back to the mtime (still "down", the start is the best we know)', () => {
    expect(netdownSinceFromMarker('garbage', NOW - 1000, NOW)).toBe(NOW - 1000)
    expect(netdownSinceFromMarker('', NOW - 1000, NOW)).toBe(NOW - 1000)
    expect(netdownSinceFromMarker(`${Math.floor(NOW / 1000) + 3600} 0`, NOW - 1000, NOW)).toBe(NOW - 1000)
  })
})

describe('readNetdownSince (file)', () => {
  it('no marker: null; a fresh marker: its start; a stale one: null; a directory: null', () => {
    const p = join(SANDBOX, 'marabel-watchdog-netdown')
    const now = Date.now()
    expect(readNetdownSince(now, p)).toBeNull()
    writeFileSync(p, `${Math.floor(now / 1000) - 600} 0\n`)
    expect(readNetdownSince(now, p)).toBe((Math.floor(now / 1000) - 600) * 1000)
    const old = (now - NETDOWN_FRESH_MS - 60_000) / 1000
    utimesSync(p, old, old)
    expect(readNetdownSince(now, p)).toBeNull()
    expect(readNetdownSince(now, SANDBOX)).toBeNull()
  })
  it('Viktor r1 (1): a FIFO at the marker path returns null at once (no writer, no wait); a symlinked marker is refused', () => {
    const fifo = join(SANDBOX, 'netdown-fifo')
    execFileSync('mkfifo', [fifo])
    const t0 = Date.now()
    expect(readNetdownSince(t0, fifo)).toBeNull()
    expect(Date.now() - t0).toBeLessThan(2_000)
    const real = join(SANDBOX, 'netdown-real')
    writeFileSync(real, `${Math.floor(t0 / 1000) - 60} 0\n`)
    const link = join(SANDBOX, 'netdown-link')
    symlinkSync(real, link)
    expect(readNetdownSince(t0, real)).not.toBeNull()
    expect(readNetdownSince(t0, link)).toBeNull()
  })
})

describe('NetdownAlertHold', () => {
  const clock = (ms: number) => new Date(ms).toISOString().slice(11, 16)
  it('folds the held alerts per task into one summary with the duration, then empties', () => {
    const h = new NetdownAlertHold()
    expect(h.flush(NOW, clock)).toBeNull()
    h.hold('inflight', 'ci-or-marveen', 'pulzus', NOW - 90 * 60_000)
    h.hold('inflight', 'ci-or-marveen', 'pulzus', NOW - 60 * 60_000)
    h.hold('retry', 'export-or', 'klodel', NOW - 80 * 60_000)
    h.hold('inflight-owner', 'ci-or-marveen', 'pulzus', NOW - 30 * 60_000)
    expect(h.size).toBe(4)
    const text = h.flush(NOW, clock)
    expect(text).not.toBeNull()
    const lines = String(text).split('\n')
    expect(lines[0]).toContain('(20:30 - 22:00, 90 perc')
    expect(lines[0]).toContain('4 ütemező-riasztást')
    expect(lines).toContain('- "export-or" (klodel): várakozó újrapróba 1x')
    expect(lines).toContain('- "ci-or-marveen" (pulzus): pane-foglaltság 2x, pane-foglaltság, üzemeltetői szint 1x')
    expect(h.size).toBe(0)
    expect(h.flush(NOW, clock)).toBeNull()
  })
})

// ---- the scheduler, end to end on the pending-retry path ---------------------
const netdown = { since: null as number | null }
const mockCreateSystemMessage = vi.fn()
const mockMarkAlert = vi.fn(() => true)
const mockMarkOwnerAlert = vi.fn(() => true)
const mockListPendingRetries = vi.fn(() => [] as unknown[])
const mockListScheduledTasks = vi.fn(() => [] as ScheduledTask[])
const mockSendMessage = vi.fn(async () => {})

vi.mock('../web/netdown-hold.js', async (importOriginal) => {
  const real = await importOriginal<typeof import('../web/netdown-hold.js')>()
  return { ...real, readNetdownSince: () => netdown.since }
})
vi.mock('../logger.js', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), debug: vi.fn(), error: vi.fn() },
}))
vi.mock('../web/atomic-write.js', () => ({ atomicWriteFileSync: vi.fn() }))
vi.mock('../db.js', () => ({
  appendTaskRun: vi.fn(),
  listPendingTaskRetries: () => mockListPendingRetries(),
  deletePendingTaskRetry: vi.fn(),
  updatePendingTaskRetry: vi.fn(() => true),
  insertPendingTaskRetryIfNew: vi.fn(),
  markPendingTaskRetryAlert: (...a: unknown[]) => mockMarkAlert(...(a as [])),
  clearPendingTaskRetryAlert: vi.fn(),
  markPendingTaskRetryOwnerAlert: (...a: unknown[]) => mockMarkOwnerAlert(...(a as [])),
  clearPendingTaskRetryOwnerAlert: vi.fn(),
  markScheduledTaskKanbanWaiting: vi.fn(),
  createSystemMessage: (...a: unknown[]) => mockCreateSystemMessage(...a),
  createAgentMessage: vi.fn(),
}))
vi.mock('../channel-provider.js', async (importOriginal) => {
  const real = await importOriginal<typeof import('../channel-provider.js')>()
  return {
    ...real,
    getProvider: (type: Parameters<typeof real.getProvider>[0]) => ({
      ...real.getProvider(type),
      sendMessage: mockSendMessage,
      sendPhoto: vi.fn(async () => {}),
    }),
  }
})
vi.mock('../web/scheduled-tasks-io.js', () => ({
  listScheduledTasks: () => mockListScheduledTasks(),
  readScheduledTask: (n: string) => (mockListScheduledTasks() as Array<{ name: string }>).find(t => t.name === n) ?? null,
  SCHEDULED_TASKS_DIR: '/tmp/marveen-netdown-hold-no-tasks-dir',
  SCHEDULED_TASK_INLINE_MAX_CHARS: 1_500,
  SCHEDULED_TASK_BODY_WARN_CHARS: 20_000,
  MAX_SCHEDULED_TASK_PROMPT_LEN: 50_000,
}))
vi.mock('../web/agent-process.js', () => ({
  clearFeedbackModalAndRecheck: () => false,
  agentSessionName: (name: string) => `agent-${name}`,
  isAgentRunning: () => true,
  // The retry target stays busy: the row keeps waiting, so its aged alerts come due.
  isSessionReadyForPrompt: () => false,
  sendPromptToSession: vi.fn(() => 'sent'),
  startAgentProcess: vi.fn(() => ({ ok: true })),
  sessionExistsOnHost: () => true,
  capturePane: () => null,
  sendEnterToSession: vi.fn(),
  clearStaleParkedInput: vi.fn(() => false),
  resolveAgentProvider: () => 'telegram',
}))

const TASK: ScheduledTask = {
  name: 'netdown-hold-fixture', description: 'fixture', prompt: 'Do the thing.', agent: 'ndagent',
  enabled: true, createdAt: 0, type: 'task', schedule: '0 8 * * *', targetSession: 'nd-session',
}
/** A retry row waiting long enough for both the main-agent notice and the owner escalation. */
function agedRow() {
  return {
    task_name: TASK.name, agent_name: 'ndagent',
    first_attempt: Date.now() - 4 * 60 * 60_000, last_attempt: Date.now() - 60_000,
    attempt_count: 200, last_reason: 'busy', alerted_at: null, owner_alert_sent_at: null,
  }
}

async function runTicks(n: number): Promise<void> {
  vi.resetModules()
  const { startScheduleRunner } = await import('../web/schedule-runner.js')
  const stop = startScheduleRunner()
  await vi.advanceTimersByTimeAsync(n * 60_000 + 1_000)
  clearInterval(stop)
}

const systemTexts = () => mockCreateSystemMessage.mock.calls.map((c) => String(c[1]))

describe('schedule runner: alerts held while the network is down', () => {
  beforeEach(() => {
    vi.stubEnv('SCHEDULER_TZ', 'Europe/Budapest')
    vi.clearAllMocks()
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-31T10:30:00.000Z'))
    mockListScheduledTasks.mockReturnValue([TASK])
    netdown.since = null
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllEnvs()
  })

  it('control (network up): the aged retry notice goes to the main agent as before', async () => {
    const row = agedRow()
    mockListPendingRetries.mockReturnValue([row])
    // Like the real table: the stamp is claimed once.
    mockMarkAlert.mockImplementationOnce(() => true).mockImplementation(() => false)
    await runTicks(1)
    expect(systemTexts().some((t) => t.includes('perce várakozik'))).toBe(true)
    expect(systemTexts().some((t) => t.includes('Hálózat-kiesés alatt'))).toBe(false)
  })

  it('network down: no notice, the stamps are claimed; network back: one summary, once', async () => {
    mockListPendingRetries.mockReturnValue([agedRow()])
    mockMarkAlert.mockImplementationOnce(() => true).mockImplementation(() => false)
    mockMarkOwnerAlert.mockImplementationOnce(() => true).mockImplementation(() => false)
    netdown.since = Date.now() - 2 * 60 * 60_000
    // The runner module stays the same across the outage and the recovery (one dashboard life).
    vi.resetModules()
    const { startScheduleRunner } = await import('../web/schedule-runner.js')
    const stop = startScheduleRunner()
    await vi.advanceTimersByTimeAsync(3 * 60_000 + 1_000)
    expect(mockMarkAlert).toHaveBeenCalled()
    expect(mockMarkOwnerAlert).toHaveBeenCalled()
    expect(mockCreateSystemMessage).not.toHaveBeenCalled()
    expect(mockSendMessage).not.toHaveBeenCalled()

    netdown.since = null
    await vi.advanceTimersByTimeAsync(3 * 60_000)
    clearInterval(stop)
    const texts = systemTexts()
    expect(texts).toHaveLength(1)
    expect(texts[0]).toContain('Hálózat-kiesés alatt')
    expect(texts[0]).toContain('2 ütemező-riasztást')
    expect(texts[0]).toContain(`- "${TASK.name}" (ndagent): várakozó újrapróba 1x, várakozó újrapróba, üzemeltetői szint 1x`)
    expect(mockSendMessage).not.toHaveBeenCalled()
  })
})

describe('runner wiring (source pins)', () => {
  const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'web', 'schedule-runner.ts'), 'utf-8')
  it('one marker reading per tick, and the summary on the first tick without it', () => {
    expect(src).toMatch(/const netdownSince = readNetdownSince\(now\)\n\s*if \(netdownSince === null\) flushNetdownHold\(now\)/)
  })
  it('the busy-pane notice and its owner escalation are held while down; the one-shot flags are set either way', () => {
    expect(src).toMatch(/if \(netdownSince !== null\) holdInflightAlert\('inflight', entry, netdownSince\)\n\s*else sendTaskInflightMainAgentNotice\(entry, now - entry\.injectedAt\)\n\s*entry\.alerted = true/)
    expect(src).toMatch(/if \(netdownSince !== null\) holdInflightAlert\('inflight-owner', entry, netdownSince\)\n\s*else sendTaskTimeoutAlert\(entry, now - entry\.injectedAt\)\n\s*entry\.ownerAlerted = true/)
  })
})
