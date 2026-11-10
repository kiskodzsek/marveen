// Klodel 35737 (Patrik group TG 4465 "mehet"): an urgent inter-agent message does not wait for the recipient's
// idle gap. Measured cause: Patrik's baby-film fixes (35704/35705) waited 13.5 min in Dave's queue.
//
// Pinned here:
//   1. orderPendingByPriority: urgent rows first, each group keeps its oldest-first order;
//   2. urgentTypeIntoBusyPane: only a plainly busy pane that asks nothing (never a permission prompt, the usage
//      limit, an idle-but-not-ready or unreadable pane);
//   3. the tick: busy pane + one normal + one urgent row -> the urgent row is typed at once
//      (waitForIdle:false, with the emit guard) and marked delivered, the normal row stays pending; a permission
//      prompt gets nothing; a refusal at the last look leaves the urgent row pending.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { detectPaneState } from '../pane-state.js'

const PERMISSION_PANE = readFileSync(join(__dirname, 'fixtures/pane/permission-prompt-bash-grep.txt'), 'utf8')
const QUOTA_PANE = readFileSync(join(__dirname, 'fixtures/pane/quota-wall-usage-limit.txt'), 'utf8')
const SEP = '─'.repeat(80)
// A pane mid-turn: spinner with the interrupt hint, empty input box.
const BUSY_PANE = [
  '⏺ Bash(npx vitest run src/__tests__/x.test.ts)',
  '  ⎿  Running…',
  '',
  '✻ Churning… (42s · ↓ 1.2k tokens · esc to interrupt)',
  '',
  SEP,
  '> ',
  SEP,
  '  ⏵⏵ bypass permissions on (shift+tab to cycle) · esc to interrupt',
].join('\n')
const IDLE_PANE = ['⏺ Done.', '', SEP, '> ', SEP, '  ⏵⏵ bypass permissions on (shift+tab to cycle)'].join('\n')

const mockGetPendingMessages = vi.fn()
const mockCapturePane = vi.fn((..._a: unknown[]): string | null => null)
const mockSend = vi.fn(async (..._a: unknown[]): Promise<string> => 'sent')
const mockMarkDelivered = vi.fn((..._a: unknown[]) => true)

vi.mock('../logger.js', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), debug: vi.fn(), error: vi.fn() },
}))

vi.mock('../config.js', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../config.js')>()),
  MAIN_AGENT_ID: 'orin',
  SUBAGENT_TELEGRAM_WAKE_ENABLED: false,
}))

vi.mock('../db.js', () => ({
  getPendingMessages: (toAgent?: string) => (toAgent ? [] : mockGetPendingMessages()),
  getMessageStatus: (..._a: unknown[]) => 'pending',
  markMessageDelivered: (...a: unknown[]) => mockMarkDelivered(...a),
  markMessageFailed: (..._a: unknown[]) => true,
  markMessageDone: (..._a: unknown[]) => true,
  markPendingFederatedFailed: (..._a: unknown[]) => 0,
  setMessageResult: (..._a: unknown[]) => true,
  createAgentMessage: (..._a: unknown[]) => ({ id: 999 }),
  createSystemMessage: (..._a: unknown[]) => ({ id: 998 }),
  countNewerMessagesFromSameSender: (..._a: unknown[]) => 0,
  stampMessageTrace: (..._a: unknown[]) => false,
  upsertOtelSpan: (..._a: unknown[]) => undefined,
  closeOtelSpan: (..._a: unknown[]) => false,
}))

vi.mock('../web/voice-directive.js', () => ({
  resolveAgentChannelStateDir: () => '/tmp/none',
}))

vi.mock('../web/agent-config.js', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../web/agent-config.js')>()),
  readAgentRemoteHost: () => null,
  readAgentVoiceConfig: () => ({ responseMode: 'text' }),
  isKnownAgent: () => true,
  agentDir: () => '/tmp/none-agentdir',
  readAgentWorksourceChannel: () => false,
}))

vi.mock('../web/agent-process.js', () => ({
  agentSessionName: (name: string) => `agent-${name}`,
  // The pane is busy for the whole test: not ready for a prompt.
  isSessionReadyForPrompt: vi.fn(async () => false),
  clearStaleParkedInput: vi.fn(async () => false),
  sendPromptToSession: (...a: unknown[]) => mockSend(...a),
  sessionExistsOnHost: vi.fn(() => true),
  capturePane: (...a: unknown[]) => mockCapturePane(...a),
  clearFeedbackModalAndRecheck: vi.fn(async () => false),
}))

vi.mock('../web/voice-modality.js', () => ({
  setLastInboundModality: vi.fn(),
}))

vi.mock('../web/main-agent.js', () => ({
  MAIN_CHANNELS_SESSION: 'orin-channels',
}))

vi.mock('../web/delivery-turn-check.js', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../web/delivery-turn-check.js')>()),
  scheduleDeliveryTurnCheck: vi.fn(),
  snapshotTranscriptOffsets: vi.fn(() => null),
}))

const { runMessageRouterTick, orderPendingByPriority, urgentTypeIntoBusyPane } = await import('../web/message-router.js')

let seq = 0
// A fresh recipient per test: the router keeps per-agent state (stuck clock) at module level.
function row(to: string, content: string, priority?: 'urgent' | 'normal', createdAt = Math.floor(Date.now() / 1000)) {
  return {
    id: 7000 + seq++, from_agent: 'klodel', to_agent: to, content, status: 'pending',
    created_at: createdAt, ...(priority ? { priority } : {}),
  }
}
const sentTexts = () => mockSend.mock.calls.map((c) => String(c[1]))
const deliveredIds = () => mockMarkDelivered.mock.calls.map((c) => c[0])

describe('orderPendingByPriority (pure)', () => {
  it('urgent rows first, each group keeps its order; no priority = normal', () => {
    const a = row('x', 'a'), b = row('x', 'b', 'urgent'), c = row('y', 'c', 'normal'), d = row('y', 'd', 'urgent')
    const out = orderPendingByPriority([a, b, c, d] as never)
    expect(out.map((m) => m.content)).toEqual(['b', 'd', 'a', 'c'])
  })
  it('no urgent row -> unchanged order', () => {
    const rows = [row('x', 'a'), row('x', 'b'), row('y', 'c')]
    expect(orderPendingByPriority(rows as never).map((m) => m.content)).toEqual(['a', 'b', 'c'])
  })
})

describe('urgentTypeIntoBusyPane (pure)', () => {
  it('fixture sanity: the busy fixture reads busy, the idle one does not', () => {
    expect(detectPaneState(BUSY_PANE)).toBe('busy')
    expect(detectPaneState(IDLE_PANE)).not.toBe('busy')
  })
  it('a plainly busy pane -> yes', () => {
    expect(urgentTypeIntoBusyPane(BUSY_PANE)).toBe(true)
  })
  it('a permission prompt, the usage limit, an idle-but-not-ready pane, no pane -> no', () => {
    expect(urgentTypeIntoBusyPane(PERMISSION_PANE)).toBe(false)
    expect(urgentTypeIntoBusyPane(QUOTA_PANE)).toBe(false)
    expect(urgentTypeIntoBusyPane(IDLE_PANE)).toBe(false)
    expect(urgentTypeIntoBusyPane(null)).toBe(false)
  })
})

describe('router tick: urgent row into a busy pane', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSend.mockImplementation(async () => 'sent')
  })
  afterEach(() => vi.restoreAllMocks())

  it('busy pane: the urgent row is typed at once and delivered, the older normal row stays pending', async () => {
    const t0 = Math.floor(Date.now() / 1000)
    const normal = row('dexu1', 'NORMAL-older', undefined, t0 - 600)
    const urgent = row('dexu1', 'URGENT-newer', 'urgent', t0)
    mockGetPendingMessages.mockReturnValue([normal, urgent])
    mockCapturePane.mockReturnValue(BUSY_PANE)
    const started = Date.now()
    await runMessageRouterTick()
    expect(Date.now() - started).toBeLessThan(60_000)
    expect(mockSend).toHaveBeenCalledTimes(1)
    const [session, text, , opts] = mockSend.mock.calls[0] as [string, string, unknown, Record<string, unknown>]
    expect(session).toBe('agent-dexu1')
    expect(text).toContain('URGENT-newer')
    expect(text).not.toContain('NORMAL-older') // alone, no batch mates
    expect(opts.waitForIdle).toBe(false)
    expect(typeof opts.emitGuard).toBe('function')
    expect(deliveredIds()).toEqual([urgent.id])
  })

  it('control: busy pane, only normal rows -> nothing typed, nothing delivered', async () => {
    mockGetPendingMessages.mockReturnValue([row('dexu2', 'n1'), row('dexu2', 'n2', 'normal')])
    mockCapturePane.mockReturnValue(BUSY_PANE)
    await runMessageRouterTick()
    expect(mockSend).not.toHaveBeenCalled()
    expect(deliveredIds()).toEqual([])
  })

  it('a permission prompt: the urgent row is not typed and stays pending', async () => {
    mockGetPendingMessages.mockReturnValue([row('dexu3', 'URGENT', 'urgent')])
    mockCapturePane.mockReturnValue(PERMISSION_PANE)
    await runMessageRouterTick()
    expect(sentTexts()).toEqual([])
    expect(deliveredIds()).toEqual([])
  })

  it('the usage limit: the urgent row is not typed and stays pending', async () => {
    mockGetPendingMessages.mockReturnValue([row('dexu4', 'URGENT', 'urgent')])
    mockCapturePane.mockReturnValue(QUOTA_PANE)
    await runMessageRouterTick()
    expect(sentTexts()).toEqual([])
    expect(deliveredIds()).toEqual([])
  })

  it('refused at the last look (pane turned into a prompt): stays pending, not failed', async () => {
    mockSend.mockImplementation(async () => 'aborted-guard')
    const u = row('dexu5', 'URGENT', 'urgent')
    mockGetPendingMessages.mockReturnValue([u])
    mockCapturePane.mockReturnValue(BUSY_PANE)
    await runMessageRouterTick()
    expect(mockSend).toHaveBeenCalledTimes(1)
    expect(deliveredIds()).toEqual([])
  })
})
