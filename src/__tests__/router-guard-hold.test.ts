// GUARDHOLD1013: while the hard context-guard waits for a handoff
// (await-handoff), the router keeps new inter-agent messages PENDING so the
// agent's pane can go idle and the restart can happen. Measured 2026-10-13:
// Dave worked 7 more prompts for 14 minutes after writing his handoff (84% ->
// 131% of limitTokens), Pixel 14 prompts over 25 minutes (72% -> 149%), because
// the router kept injecting.
//
// Pinned here:
//   1. the pure decision (shouldHoldForGuard): hold only with a reason, never a
//      `system` row, and never past the fail-open cap;
//   2. the tick: a held row never reaches the readiness gate or the pane, is not
//      failed, and is delivered normally once the phase ends;
//   3. no registered check = today's behavior.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const mockGetPendingMessages = vi.fn()
const mockIsReady = vi.fn(async (..._a: unknown[]) => false)
const mockMarkFailed = vi.fn((..._a: unknown[]) => true)

vi.mock('../logger.js', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), debug: vi.fn(), error: vi.fn() },
}))

vi.mock('../config.js', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../config.js')>()),
  MAIN_AGENT_ID: 'orin',
  SUBAGENT_TELEGRAM_WAKE_ENABLED: false,
}))

vi.mock('../db.js', () => ({
  getPendingMessages: (toAgent?: string) => {
    if (toAgent) return []
    return mockGetPendingMessages()
  },
  getMessageStatus: (..._a: unknown[]) => 'pending',
  markMessageDelivered: (..._a: unknown[]) => true,
  markMessageFailed: (...a: unknown[]) => mockMarkFailed(...a),
  markMessageDone: (..._a: unknown[]) => true,
  markPendingFederatedFailed: (..._a: unknown[]) => true,
  setMessageResult: (..._a: unknown[]) => true,
  createAgentMessage: (..._a: unknown[]) => ({ id: 999 }),
  stampMessageTrace: (..._a: unknown[]) => false,
  upsertOtelSpan: (..._a: unknown[]) => undefined,
  closeOtelSpan: (..._a: unknown[]) => false,
}))

vi.mock('../web/voice-directive.js', () => ({
  resolveAgentChannelStateDir: () => '/tmp/none',
}))

vi.mock('../web/agent-config.js', () => ({
  readAgentRemoteHost: () => null,
  readAgentVoiceConfig: () => ({ responseMode: 'text' }),
  readAgentWorksourceChannel: () => false,
}))

vi.mock('../web/agent-process.js', () => ({
  agentSessionName: (name: string) => `agent-${name}`,
  // Not ready: a row that passes the hold stops at the readiness gate, so
  // "the readiness gate was asked" is the observable for "not held".
  isSessionReadyForPrompt: (...a: unknown[]) => mockIsReady(...a),
  clearStaleParkedInput: vi.fn(async () => false),
  clearFeedbackModalAndRecheck: vi.fn(async () => false),
  sendPromptToSession: vi.fn(async () => {}),
  sessionExistsOnHost: vi.fn(() => true),
  capturePane: vi.fn(() => ''),
}))

vi.mock('../web/voice-modality.js', () => ({
  setLastInboundModality: vi.fn(),
}))

vi.mock('../web/main-agent.js', () => ({
  MAIN_CHANNELS_SESSION: 'orin-channels',
}))

const { runMessageRouterTick, setDeliveryHoldCheck, shouldHoldForGuard, GUARD_HOLD_MAX_MS } =
  await import('../web/message-router.js')

const row = (id: number, from: string) => ({
  id, from_agent: from, to_agent: 'dex', content: 'ping', created_at: Math.floor(Date.now() / 1000),
})

describe('shouldHoldForGuard (pure)', () => {
  const MAX = 30 * 60_000
  it('no reason -> no hold', () => {
    expect(shouldHoldForGuard(null, 'pixel', undefined, 0, MAX)).toBe(false)
  })
  it('a system row is never held: the guard directives ride it', () => {
    expect(shouldHoldForGuard('await-handoff', 'system', undefined, 0, MAX)).toBe(false)
  })
  it('holds a first-seen row and a row inside the cap', () => {
    expect(shouldHoldForGuard('await-handoff', 'pixel', undefined, 0, MAX)).toBe(true)
    expect(shouldHoldForGuard('await-handoff', 'pixel', 1_000, 1_000 + MAX - 1, MAX)).toBe(true)
  })
  it('fails open at the cap', () => {
    expect(shouldHoldForGuard('await-handoff', 'pixel', 1_000, 1_000 + MAX, MAX)).toBe(false)
  })
})

describe('router tick under a guard hold', () => {
  let phase: string | null = null
  beforeEach(() => {
    vi.clearAllMocks()
    phase = null
    setDeliveryHoldCheck((agent) => (agent === 'dex' ? phase : null))
  })
  afterEach(() => setDeliveryHoldCheck(null))

  it('control: without a hold the row reaches the readiness gate', async () => {
    mockGetPendingMessages.mockReturnValue([row(1, 'pixel')])
    await runMessageRouterTick()
    expect(mockIsReady).toHaveBeenCalledTimes(1)
  })

  it('await-handoff: a peer row is held (no readiness check, no pane, not failed)', async () => {
    phase = 'context-guard await-handoff'
    mockGetPendingMessages.mockReturnValue([row(2, 'pixel')])
    await runMessageRouterTick()
    await runMessageRouterTick()
    expect(mockIsReady).not.toHaveBeenCalled()
    expect(mockMarkFailed).not.toHaveBeenCalled()
  })

  it('await-handoff: a system row still goes through', async () => {
    phase = 'context-guard await-handoff'
    mockGetPendingMessages.mockReturnValue([row(3, 'system')])
    await runMessageRouterTick()
    expect(mockIsReady).toHaveBeenCalledTimes(1)
  })

  it('the held row is delivered normally once the phase ends', async () => {
    phase = 'context-guard await-handoff'
    mockGetPendingMessages.mockReturnValue([row(4, 'pixel')])
    await runMessageRouterTick()
    expect(mockIsReady).not.toHaveBeenCalled()
    phase = null
    await runMessageRouterTick()
    expect(mockIsReady).toHaveBeenCalledTimes(1)
  })

  it('a phase that never ends fails open after the cap, and stays released', async () => {
    phase = 'context-guard await-handoff'
    const t0 = Date.now()
    mockGetPendingMessages.mockReturnValue([row(5, 'pixel')])
    vi.useFakeTimers()
    try {
      vi.setSystemTime(t0)
      await runMessageRouterTick()
      expect(mockIsReady).not.toHaveBeenCalled()
      vi.setSystemTime(t0 + GUARD_HOLD_MAX_MS)
      await runMessageRouterTick()
      expect(mockIsReady).toHaveBeenCalledTimes(1)
      // Still not deliverable (busy pane): it must not be re-held for a new cap.
      vi.setSystemTime(t0 + GUARD_HOLD_MAX_MS + 5_000)
      await runMessageRouterTick()
      expect(mockIsReady).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it('no registered check = no hold', async () => {
    setDeliveryHoldCheck(null)
    mockGetPendingMessages.mockReturnValue([row(6, 'pixel')])
    await runMessageRouterTick()
    expect(mockIsReady).toHaveBeenCalledTimes(1)
  })
})
