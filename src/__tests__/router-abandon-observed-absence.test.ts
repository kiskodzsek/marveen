// Card 6a9c1cc0 (Klodel 39907): the machine went down at 09:15 on 2026-11-13
// and was force-restarted at 10:07. The router's first tick at 10:08 saw two
// 09:07 rows (39893, 39894) at age 61 min, their target sessions not started
// yet, and failed them at once as "absent for full retry window" -- an absence
// nobody had observed. Klodel had to re-send both by hand.
//
// Two contracts are pinned here:
//   1. abandon needs the router to have SEEN the target absent for the full
//      window (updateAbsenceClocks + shouldAbandon's observedAbsentMs), and a
//      gap in the router's own ticks restarts every clock;
//   2. a row abandoned for absence goes out once more when the target session
//      is back (requeueAbandonedOnReturn), and only once.

import { describe, it, expect, beforeAll } from 'vitest'
import { initDatabase, createAgentMessage, markMessageFailed, getAgentMessage } from '../db.js'
import {
  shouldAbandon,
  updateAbsenceClocks,
  absentAbandonReason,
  requeueAbandonedOnReturn,
  ABANDON_REASON_ABSENT,
  ABANDON_REASON_ABSENT_AGAIN,
  REQUEUED_AFTER_ABSENCE_MARKER,
} from '../web/message-router.js'

beforeAll(() => { initDatabase(':memory:') })

const WINDOW_MS = 60 * 60 * 1000
const GAP_MS = 5 * 60 * 1000
const MIN = 60 * 1000

describe('shouldAbandon: the absence must have been observed', () => {
  it('NEGATIVE: an old row whose absence was not observed is kept (the 11-13 reboot case)', () => {
    // age 61 min, session absent, but the router has only just started watching
    expect(shouldAbandon(false, 61 * MIN, WINDOW_MS, 0)).toBe(false)
    expect(shouldAbandon(false, 61 * MIN, WINDOW_MS, 30 * MIN)).toBe(false)
  })

  it('abandons once the router has watched the absence for the full window', () => {
    expect(shouldAbandon(false, 125 * MIN, WINDOW_MS, 61 * MIN)).toBe(true)
  })

  it('NEGATIVE: a long observed absence does not abandon a fresh row', () => {
    expect(shouldAbandon(false, 10 * MIN, WINDOW_MS, 3 * WINDOW_MS)).toBe(false)
  })
})

describe('updateAbsenceClocks', () => {
  it('starts a clock at the first absent tick and keeps it while absent', () => {
    const c = new Map<string, number>()
    updateAbsenceClocks(c, new Set(['radar']), 1000, null, GAP_MS)
    updateAbsenceClocks(c, new Set(['radar']), 6000, 1000, GAP_MS)
    expect(c.get('radar')).toBe(1000)
  })

  it('NEGATIVE: drops the clock when the agent is present or no longer observed', () => {
    const c = new Map<string, number>([['radar', 1000], ['szigma', 1000]])
    updateAbsenceClocks(c, new Set(['szigma']), 6000, 1000, GAP_MS)
    expect(c.has('radar')).toBe(false)
    expect(c.get('szigma')).toBe(1000)
  })

  it('NEGATIVE: a gap in the router ticks restarts every clock (nobody was watching)', () => {
    const c = new Map<string, number>([['radar', 1000]])
    const now = 1000 + 52 * MIN // machine down 52 min, the router's next tick
    updateAbsenceClocks(c, new Set(['radar']), now, 1000 + 5000, GAP_MS)
    expect(c.get('radar')).toBe(now)
  })
})

describe('absentAbandonReason', () => {
  it('first abandon -> re-sendable reason; after a re-queue -> final reason', () => {
    expect(absentAbandonReason(null)).toBe(ABANDON_REASON_ABSENT)
    expect(absentAbandonReason(REQUEUED_AFTER_ABSENCE_MARKER)).toBe(ABANDON_REASON_ABSENT_AGAIN)
    expect(ABANDON_REASON_ABSENT_AGAIN).not.toBe(ABANDON_REASON_ABSENT)
  })

  it('NEGATIVE: the pre-change reason text is not the re-sendable one (no duplicate on deploy)', () => {
    expect(ABANDON_REASON_ABSENT).not.toBe('Abandoned: target session absent for full retry window')
  })
})

describe('requeueAbandonedOnReturn', () => {
  const uniq = () => `${Date.now()}-${Math.floor(performance.now() * 1000)}`

  it('re-queues an abandoned row once when the session is back, never a second time', () => {
    const to = 'rq-back-' + uniq()
    const m = createAgentMessage('szigma', to, 'padel')
    markMessageFailed(m.id, absentAbandonReason(null))
    const now = Date.now()

    // session still absent -> nothing happens
    expect(requeueAbandonedOnReturn(now, () => false)).not.toContain(m.id)
    expect(getAgentMessage(m.id)?.status).toBe('failed')

    // session back -> pending again, marked
    expect(requeueAbandonedOnReturn(now, (a) => a === to)).toContain(m.id)
    const row = getAgentMessage(m.id)
    expect(row?.status).toBe('pending')
    expect(row?.result).toBe(REQUEUED_AFTER_ABSENCE_MARKER)
    expect(row?.completed_at).toBeNull()

    // NEGATIVE: abandoned again -> final reason, and it is not re-queued again
    markMessageFailed(m.id, absentAbandonReason(row?.result))
    expect(requeueAbandonedOnReturn(Date.now(), (a) => a === to)).not.toContain(m.id)
    expect(getAgentMessage(m.id)?.status).toBe('failed')
    expect(getAgentMessage(m.id)?.result).toBe(ABANDON_REASON_ABSENT_AGAIN)
  })

  it('NEGATIVE: other failures, old-text abandons and stale abandons are left alone', () => {
    const to = 'rq-other-' + uniq()
    const inject = createAgentMessage('a', to, 'x')
    markMessageFailed(inject.id, 'Failed to inject into tmux session after 3 attempts')
    const oldText = createAgentMessage('a', to, 'y')
    markMessageFailed(oldText.id, 'Abandoned: target session absent for full retry window')
    const stale = createAgentMessage('a', to, 'z')
    markMessageFailed(stale.id, ABANDON_REASON_ABSENT)

    // 25 h later the stale one is outside the 24 h re-send window
    const later = Date.now() + 25 * 60 * MIN
    const ids = requeueAbandonedOnReturn(later, (a) => a === to)
    expect(ids).not.toContain(inject.id)
    expect(ids).not.toContain(oldText.id)
    expect(ids).not.toContain(stale.id)
    for (const id of [inject.id, oldText.id, stale.id]) expect(getAgentMessage(id)?.status).toBe('failed')
  })
})
