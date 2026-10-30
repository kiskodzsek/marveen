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
  it('an own setup-token file is a seat, keyed by the hashed path, shared by whoever points at it', () => {
    // 2fb86ef2: such an agent counted as fleet, and its own seat's numbers raised the fleet's.
    const key = quotaPlanKey('dave', { oauthTokenFile: '/Users/x/.secrets/dave-token' })
    expect(key).toMatch(/^tok:[0-9a-f]{8}$/)
    expect(key).not.toContain('/Users')
    expect(quotaPlanKey('pixel', { oauthTokenFile: '/Users/x/.secrets/dave-token' })).toBe(key)
    expect(quotaPlanKey('lex', { oauthTokenFile: '/Users/x/.secrets/lex-token' })).not.toBe(key)
    // a token file and a config dir at the same path are still two different seats
    expect(quotaPlanKey('a', { claudeConfigDir: '/p' })).not.toBe(quotaPlanKey('a', { oauthTokenFile: '/p' }))
    // the launcher refuses a token file next to own_team, a plan or a config dir; the key follows those
    expect(quotaPlanKey('dave', { authMode: 'own_team', oauthTokenFile: '/t' })).toBe('own:dave')
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

  it('names every agent reporting the seat, not only the winner of each window (Klodel 21626)', () => {
    source('pulzus', 18, 32)
    source('kernel', 19, 32)
    source('lex', 19, 32)
    const fleet = readModQuotaSnapshot(dir, NOW)
    expect(fleet.sourceAgents?.length).toBeLessThanOrEqual(2)
    expect(fleet.reportingAgents).toEqual(['kernel', 'lex', 'pulzus'])
    // a filtered-out agent is not a reporter of this seat
    expect(readModQuotaSnapshot(dir, NOW, undefined, (a) => a !== 'lex').reportingAgents).toEqual(['kernel', 'pulzus'])
  })

  it('a reading of a window already reset does not make its agent a reporter', () => {
    source('kernel', 19, 32)
    writeFileSync(join(dir, 'bella.json'), JSON.stringify({
      agent: 'bella', state: 'ended', alive_at: (NOW - 900000) * 1000,
      usage: { rateLimits: [{ kind: 'seven_day', percentUsed: 81, resetsAt: iso(NOW - 86400) }] },
    }))
    expect(readModQuotaSnapshot(dir, NOW).reportingAgents).toEqual(['kernel'])
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
    expect(SRC).toMatch(/oauthTokenFile: readAgentOauthTokenFilePath\(a\)/)
    // only a valid setting counts: an invalid one refuses the launch, so the agent runs on no seat
    expect(SRC).toMatch(/setting\.state === 'set' \? setting\.path : null/)
  })

  it('the overview page renders the seats and has the container for them', () => {
    expect(read('../../web/app.js')).toMatch(/renderQuotaStrip\(d\.quota, d\.quotaFable\)\s*renderQuotaSeats\(d\.quotaSeats\)/)
    expect(read('../../web/index.html')).toContain('id="quotaSeats"')
  })

  it('the seat messages exist in both languages', () => {
    for (const lang of ['hu', 'en']) {
      const L = read(`../../web/lang/${lang}.js`)
      for (const key of ['overview.quota.seat', 'overview.quota.seat_none', 'overview.quota.reporting']) expect(L, `${lang}: ${key}`).toContain(`'${key}'`)
    }
  })
})
