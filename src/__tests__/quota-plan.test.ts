import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { quotaPlanKey, readModQuotaSnapshot } from '../web/quota.js'

// QUOTAPLAN1014: an agent on its own seat (Dave on Patrik's Team Premium seat,
// TG 2220/2225) reports that seat's rate limits; they must neither raise the
// fleet's number nor be hidden -- each seat is read on its own.

const NOW = 1_791_200_000
const iso = (sec: number) => new Date(sec * 1000).toISOString()

let dir: string
beforeEach(() => { dir = mkdtempSync(join(tmpdir(), 'quota-plan-')) })
afterEach(() => { rmSync(dir, { recursive: true, force: true }) })

function source(agent: string, five: number, week: number) {
  writeFileSync(join(dir, `${agent}.json`), JSON.stringify({
    agent, state: 'idle', alive_at: (NOW - 5) * 1000, updated_at: (NOW - 5) * 1000,
    history: [{ ts: (NOW - 30) * 1000, from: 'working', to: 'idle', reason: 'turn.complete:answer' }],
    usage: { rateLimits: [
      { kind: 'five_hour', percentUsed: five, resetsAt: iso(NOW + 3600) },
      { kind: 'seven_day', percentUsed: week, resetsAt: iso(NOW + 4 * 86400) },
    ] },
  }))
}

describe('quotaPlanKey', () => {
  it('own_team is a seat of its own, and wins over a plan or a config dir', () => {
    expect(quotaPlanKey('dave', { authMode: 'own_team' })).toBe('own:dave')
    expect(quotaPlanKey('dave', { authMode: 'own_team', claudePlan: 'team', claudeConfigDir: '/x' })).toBe('own:dave')
  })
  it('a named plan and a raw config dir are shared by whoever uses them', () => {
    expect(quotaPlanKey('a', { authMode: 'shared', claudePlan: 'team' })).toBe('plan:team')
    // Viktor L1: the key travels on /api/overview, so the path goes out hashed, never raw.
    const key = quotaPlanKey('a', { claudeConfigDir: '/Users/x/.claude-b' })
    expect(key).toMatch(/^dir:[0-9a-f]{8}$/)
    expect(key).not.toContain('/Users')
    expect(quotaPlanKey('b', { claudeConfigDir: '/Users/x/.claude-b' })).toBe(key)
    expect(quotaPlanKey('c', { claudeConfigDir: '/Users/x/.claude-c' })).not.toBe(key)
  })
  it('everything else draws from the fleet', () => {
    expect(quotaPlanKey('a', {})).toBe('fleet')
    expect(quotaPlanKey('a', { authMode: 'shared', claudePlan: null, claudeConfigDir: null })).toBe('fleet')
  })
})

describe('readModQuotaSnapshot with an agent filter', () => {
  it("an own-seat agent's 95% does not raise the fleet's number", () => {
    source('bella', 5, 78)
    source('dave', 95, 97)
    const fleet = readModQuotaSnapshot(dir, NOW, undefined, (a) => a !== 'dave')
    expect(fleet.fiveHour?.usedPercentage).toBe(5)
    expect(fleet.sevenDay?.usedPercentage).toBe(78)
    expect(fleet.sourceAgents).toEqual(['bella'])
  })

  it("the seat's snapshot holds only its own agents' readings", () => {
    source('bella', 50, 78)
    source('dave', 3, 10)
    const seat = readModQuotaSnapshot(dir, NOW, undefined, (a) => a === 'dave')
    expect(seat.fiveHour?.usedPercentage).toBe(3)
    expect(seat.sevenDay?.sourceAgent).toBe('dave')
  })

  it('a seat with no state file is missing, not borrowed from the fleet', () => {
    source('bella', 50, 78)
    const seat = readModQuotaSnapshot(dir, NOW, undefined, (a) => a === 'dave')
    expect(seat.status).toBe('missing')
    expect(seat.fiveHour).toBeNull()
  })

  it('without a filter every file counts, as before', () => {
    source('bella', 5, 78)
    source('dave', 95, 97)
    expect(readModQuotaSnapshot(dir, NOW).fiveHour?.usedPercentage).toBe(95)
  })
})

describe('the wiring', () => {
  const read = (rel: string) => readFileSync(join(__dirname, rel), 'utf-8')

  it('the overview sends the seats next to the fleet quota, each read from its own agents', () => {
    const SRC = read('../web/routes/overview.ts')
    expect(SRC).toMatch(/const quotaSeats = readSeatQuotas\(Math\.floor\(Date\.now\(\) \/ 1000\)\)/)
    expect(SRC).toMatch(/quota,\s*quotaSeats,\s*quotaFable,/)
    expect(SRC).toMatch(/readModQuotaSnapshot\(STATE_OBSERVER_STATE_DIR, nowSec, maxAgeSec, \(a\) => agents\.includes\(a\)\)/)
    expect(SRC).toMatch(/authMode: readAgentAuthMode\(a\)/)
  })

  it('the overview page renders the seats and has the container for them', () => {
    expect(read('../../web/app.js')).toMatch(/renderQuotaStrip\(d\.quota, d\.quotaFable\)\s*renderQuotaSeats\(d\.quotaSeats\)/)
    expect(read('../../web/index.html')).toContain('id="quotaSeats"')
  })

  it('the seat messages exist in both languages', () => {
    for (const lang of ['hu', 'en']) {
      const L = read(`../../web/lang/${lang}.js`)
      for (const key of ['overview.quota.seat', 'overview.quota.seat_none']) expect(L, `${lang}: ${key}`).toContain(`'${key}'`)
    }
  })
})
