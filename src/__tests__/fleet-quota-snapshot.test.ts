// FLEETQUOTA1023 (Klodel 14644): the fleet seat had no quota history and no
// threshold alert, because the only writer of store/.claude-rate-limits.json
// (the statusLine) gets no rate_limits on a setup-token login.
// scripts/fleet-quota-snapshot.py records /api/overview's quota every run and
// messages the main agent once per band crossing. Driven here through its
// file/env hooks: no dashboard, no real inter-agent message.
import { describe, it, expect, beforeEach } from 'vitest'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, writeFileSync, readFileSync, existsSync, chmodSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const SCRIPT = join(__dirname, '..', '..', 'scripts', 'fleet-quota-snapshot.py')
const NOW = 1792740000
const RESET_7D = 1793329200
const RESET_5H = 1792747200

let dir: string
let sentLog: string

function overview(fleet7d: number | null, opts: { status?: string; fleet5h?: number; reset7d?: number; dave7d?: number } = {}) {
  const quota = fleet7d === null
    ? { status: 'missing', ageSec: null, maxAgeSec: 21600, fiveHour: null, sevenDay: null, reason: 'no-source' }
    : {
        status: opts.status ?? 'ok', ageSec: 60, maxAgeSec: 21600, source: 'mod', sourceAgents: ['pulzus'],
        fiveHour: { usedPercentage: opts.fleet5h ?? 2, resetsAt: RESET_5H, expired: false, sourceAgent: 'pulzus' },
        sevenDay: { usedPercentage: fleet7d, resetsAt: opts.reset7d ?? RESET_7D, expired: false, sourceAgent: 'pulzus' },
      }
  const quotaSeats = opts.dave7d === undefined ? [] : [{
    key: 'own:dave', label: 'Dave', agents: ['dave'],
    quota: { status: 'ok', ageSec: 1, maxAgeSec: 21600, source: 'mod', sourceAgents: ['dave'],
      fiveHour: { usedPercentage: 3, resetsAt: RESET_5H, expired: false }, sevenDay: { usedPercentage: opts.dave7d, resetsAt: 1792987200, expired: false } },
  }]
  writeFileSync(join(dir, 'overview.json'), JSON.stringify({ quota, quotaSeats }))
}

function run(args: string[] = [], env: Record<string, string> = {}) {
  return spawnSync('python3', [SCRIPT, ...args], {
    encoding: 'utf-8',
    env: {
      PATH: process.env.PATH ?? '/usr/bin:/bin',
      TZ: 'Europe/Budapest',
      MARVEEN_STORE: dir,
      FLEETQ_OVERVIEW_FILE: join(dir, 'overview.json'),
      FLEETQ_NOW: String(NOW),
      FLEETQ_AGENT_MSG: join(dir, 'agent-msg-stub.sh'),
      ...env,
    },
  })
}

function sent(): string[] {
  return existsSync(sentLog) ? readFileSync(sentLog, 'utf-8').split('\n---\n').filter(Boolean) : []
}

function history(): Array<{ ts: number; seats: Record<string, { status: string; sevenDay: { pct: number } | null }> }> {
  return readFileSync(join(dir, 'fleet-quota.jsonl'), 'utf-8').trim().split('\n').map((l) => JSON.parse(l))
}

function stub(exitCode: number) {
  const p = join(dir, 'agent-msg-stub.sh')
  writeFileSync(p, `#!/bin/bash\n[ "$1" = fleet-quota ] && [ "$2" = klodel ] && [ "$3" = - ] || exit 9\ncat >> "${sentLog}"\nprintf '\\n---\\n' >> "${sentLog}"\nexit ${exitCode}\n`)
  chmodSync(p, 0o755)
}

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), 'fleetq-'))
  sentLog = join(dir, 'sent.txt')
  stub(0)
})

describe('history', () => {
  it('appends one line per run with every seat', () => {
    overview(12, { dave7d: 40 })
    expect(run().status).toBe(0)
    overview(13, { dave7d: 41 })
    expect(run([], { FLEETQ_NOW: String(NOW + 900) }).status).toBe(0)
    const h = history()
    expect(h.map((r) => r.ts)).toEqual([NOW, NOW + 900])
    expect(h[1].seats.fleet.sevenDay?.pct).toBe(13)
    expect(h[1].seats['own:dave'].sevenDay?.pct).toBe(41)
  })

  it('--status prints and writes nothing', () => {
    overview(12)
    const r = run(['--status'])
    expect(r.status).toBe(0)
    expect(r.stdout).toContain('fleet ok 5h=2% 7d=12%')
    expect(existsSync(join(dir, 'fleet-quota.jsonl'))).toBe(false)
    expect(sent()).toEqual([])
  })

  it('a torn first line does not switch the trim off', () => {
    writeFileSync(join(dir, 'fleet-quota.jsonl'), `not json\n${JSON.stringify({ ts: NOW - 37 * 86400, seats: {} })}\n`)
    overview(5)
    expect(run().status).toBe(0)
    expect(history().map((r) => r.ts)).toEqual([NOW])
  })

  it('drops lines older than 35 days once the oldest is a day past that', () => {
    const old = NOW - 37 * 86400
    writeFileSync(join(dir, 'fleet-quota.jsonl'), `${JSON.stringify({ ts: old, seats: {} })}\nnot json\n${JSON.stringify({ ts: NOW - 86400, seats: {} })}\n`)
    overview(5)
    expect(run().status).toBe(0)
    expect(history().map((r) => r.ts)).toEqual([NOW - 86400, NOW])
  })

  it('a failed overview read writes no history row and exits non-zero', () => {
    const r = run([], { FLEETQ_OVERVIEW_FILE: join(dir, 'nope.json') })
    expect(r.status).toBe(1)
    expect(existsSync(join(dir, 'fleet-quota.jsonl'))).toBe(false)
    expect(readFileSync(join(dir, 'fleet-quota.log'), 'utf-8')).toContain('overview read FAILED')
  })
})

describe('band alerts', () => {
  it('below every band: no message', () => {
    overview(79)
    run()
    expect(sent()).toEqual([])
  })

  it('one message per band, never the same band twice in a window', () => {
    overview(81)
    run()
    run()
    expect(sent()).toHaveLength(1)
    expect(sent()[0]).toContain('flotta seat: a 7 napos ablak 81% (sáv 80%)')
    overview(92)
    run()
    expect(sent()).toHaveLength(2)
    expect(sent()[1]).toContain('(sáv 90%)')
  })

  it('a jump over several bands sends only the highest', () => {
    overview(97)
    run()
    expect(sent()).toHaveLength(1)
    expect(sent()[0]).toContain('(sáv 95%)')
  })

  it('a new window (new reset time) starts from zero', () => {
    overview(85)
    run()
    overview(85, { reset7d: RESET_7D + 7 * 86400 })
    run()
    expect(sent()).toHaveLength(2)
  })

  it('the 5h window alerts only at 90', () => {
    overview(1, { fleet5h: 85 })
    run()
    expect(sent()).toEqual([])
    overview(1, { fleet5h: 91 })
    run()
    expect(sent()[0]).toContain('a 5 órás ablak 91% (sáv 90%)')
  })

  it('an own seat alerts under its own key', () => {
    overview(1, { dave7d: 96 })
    run()
    expect(sent()).toHaveLength(1)
    expect(sent()[0]).toContain('seat own:dave: a 7 napos ablak 96% (sáv 95%)')
  })

  it('a failed send is not remembered, so the next run retries it', () => {
    stub(1)
    overview(91)
    run()
    expect(readFileSync(join(dir, 'fleet-quota.log'), 'utf-8')).toContain('alert send FAILED')
    // Viktor 14713 M1: the failure is visible outside the log too.
    expect((history()[0] as unknown as { unsent?: string[] }).unsent).toEqual(['fleet|sevenDay'])
    expect(run(['--status']).stdout).toMatch(/unsent alerts: 1 \(last send failure /)
    stub(0)
    run()
    expect(sent()).toHaveLength(2)
    run()
    expect(sent()).toHaveLength(2)
    expect(run(['--status']).stdout).toContain('unsent alerts: 0')
    expect((history().at(-1) as unknown as { unsent?: string[] }).unsent).toBeUndefined()
  })

  it('a stale reading never raises a band alert', () => {
    overview(99, { status: 'stale' })
    run()
    expect(sent().some((m) => m.includes('sáv'))).toBe(false)
  })
})

describe('--test-alert', () => {
  it('sends one real probe through the alert path and reports delivery', () => {
    const r = run(['--test-alert'])
    expect(r.status).toBe(0)
    expect(r.stdout).toContain('test alert delivered')
    expect(sent()).toHaveLength(1)
    expect(sent()[0]).toContain('próbaüzenet')
    expect(existsSync(join(dir, 'fleet-quota.jsonl'))).toBe(false)
  })

  it('a rejected probe exits non-zero and names the likely cause', () => {
    stub(1)
    const r = run(['--test-alert'])
    expect(r.status).toBe(1)
    expect(r.stdout).toContain('SYSTEM_SENDER_IDS')
  })
})

describe('stale fleet seat', () => {
  it('one message per episode, re-armed by a fresh reading', () => {
    overview(null)
    run()
    run()
    expect(sent()).toHaveLength(1)
    expect(sent()[0]).toContain('nem mérhető (missing')
    overview(10)
    run()
    overview(10, { status: 'stale' })
    run()
    expect(sent()).toHaveLength(2)
  })
})
