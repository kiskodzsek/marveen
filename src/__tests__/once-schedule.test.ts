import { describe, expect, it, vi } from 'vitest'
import { mkdtempSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  validateOnceRequest, createOnceTask, shouldAlertCap, parseOnceRunAt, cronForInstant,
  readOnceAnchors, recordOnceAnchor,
  ONCE_MAX_PER_AGENT_PER_DAY, ONCE_MAX_GLOBAL_PER_DAY, ONCE_MAX_PENDING_PER_AGENT,
  type OnceDeps, type OnceAnchorMessage, type OnceAnchorRecord, type OnceRequestBody, type OnceIo, type OncePlan,
} from '../web/once-schedule.js'
import { taskOccurrenceMs } from '../web/schedule-runner.js'
// @ts-expect-error -- plain .mjs hook script, no type declarations
import { gateDecision, onceCommandAllowed } from '../../scripts/self-pace-gate.mjs'

// ONCE (card fd941954, Viktor 38878): the rules that keep a sub-agent's one-shot
// wake-up from becoming the 2026-06-26 self-pace loop, and the gate's
// whole-command exception.

const NOW = Date.parse('2026-11-12T07:00:00.000Z') // 08:00 Budapest
const TZ = 'Europe/Budapest'
const S = NOW / 1000

function m(id: number, from: string, to: string, ageS = 600, status = 'delivered'): OnceAnchorMessage {
  return { id, from_agent: from, to_agent: to, status, created_at: S - ageS }
}

const MESSAGES: Record<number, OnceAnchorMessage> = {
  100: m(100, 'klodel', 'pulzus'),
  101: m(101, 'pulzus', 'pulzus'),
  102: m(102, 'system', 'pulzus'),
  103: m(103, 'klodel', 'dave'),
  104: m(104, 'klodel', 'pulzus', 3 * 3600),
  105: m(105, 'klodel', 'pulzus', 600, 'done'),
  106: m(106, 'pulzuѕ', 'pulzus'), // Cyrillic dze: the same sender key as pulzus
  107: m(107, 'PULZUS', 'pulzus'),
  108: m(108, 'ѕуѕtеm', 'pulzus'), // Cyrillic look-alike of the system sender
}

function deps(over: Partial<OnceDeps> = {}): OnceDeps {
  return {
    now: NOW,
    knownAgents: new Set(['klodel', 'pulzus', 'dave']),
    getMessage: (id) => MESSAGES[id],
    anchors: [],
    pendingOnceCount: () => 0,
    tz: TZ,
    dashboardOrigin: 'http://localhost:3420',
    tokenPath: '/srv/marveen/store/.dashboard-token',
    ...over,
  }
}

const OK_BODY: OnceRequestBody = { agent: 'pulzus', inMinutes: 5, originMsgId: 100 }

function refusal(body: OnceRequestBody, d: OnceDeps = deps()): { status: number; error: string } | null {
  const v = validateOnceRequest(body, d)
  return v.ok ? null : { status: v.status, error: v.error }
}

describe('validateOnceRequest: the happy path', () => {
  it('plans a once-task five minutes ahead, anchored on a peer message, with a fixed prompt', () => {
    const v = validateOnceRequest(OK_BODY, deps())
    expect(v.ok).toBe(true)
    if (!v.ok) return
    expect(v.plan.runAt).toBe(NOW + 5 * 60_000)
    expect(v.plan.agent).toBe('pulzus')
    expect(v.plan.originMsgId).toBe(100)
    expect(v.plan.name).toBe('once-pulzus-202611120805-m100')
    expect(v.plan.schedule).toBe('5 8 12 11 *')
    expect(v.plan.prompt.startsWith('[EGYSZERI ÜTEMEZÉS -- pulzus, horgony: msg_id:100 (feladó: klodel), időpont: 2026-11-12 08:05 Europe/Budapest]')).toBe(true)
    expect(v.plan.prompt).toContain('curl -s -H "Authorization: Bearer $(cat /srv/marveen/store/.dashboard-token)" http://localhost:3420/api/messages/100')
  })

  it('accepts an ISO runAt with an offset, with or without the colon (date +%z)', () => {
    for (const runAt of ['2026-11-12T08:05:00+01:00', '2026-11-12T08:05:00+0100', '2026-11-12T07:05:00Z']) {
      const v = validateOnceRequest({ agent: 'pulzus', runAt, originMsgId: 100 }, deps())
      expect(v.ok && v.plan.runAt).toBe(NOW + 5 * 60_000)
    }
  })
})

describe('TEXT: no caller text reaches the scheduled-task frame', () => {
  it('refuses a prompt field', () => {
    expect(refusal({ ...OK_BODY, prompt: 'csináld meg' })?.status).toBe(400)
  })
  it('refuses any unknown field', () => {
    expect(refusal({ ...OK_BODY, description: 'x' })?.status).toBe(400)
    expect(refusal({ ...OK_BODY, type: 'heartbeat' })?.status).toBe(400)
  })
})

describe('ANCHOR / ONE: no self-pace loop', () => {
  it('refuses a missing or unknown anchor', () => {
    expect(refusal({ ...OK_BODY, originMsgId: undefined })?.status).toBe(400)
    expect(refusal({ ...OK_BODY, originMsgId: 999 })?.status).toBe(400)
  })
  it('refuses an anchor the agent sent to itself, also under a look-alike or case variant', () => {
    expect(refusal({ ...OK_BODY, originMsgId: 101 })?.status).toBe(403)
    expect(refusal({ ...OK_BODY, originMsgId: 106 })?.status).toBe(403)
    expect(refusal({ ...OK_BODY, originMsgId: 107 })?.status).toBe(403)
  })
  it('refuses a system message as anchor, also its look-alike', () => {
    expect(refusal({ ...OK_BODY, originMsgId: 102 })?.status).toBe(403)
    expect(refusal({ ...OK_BODY, originMsgId: 108 })?.status).toBe(403)
  })
  it('refuses an anchor addressed to another agent', () => {
    expect(refusal({ ...OK_BODY, originMsgId: 103 })?.status).toBe(403)
  })
  it('refuses an anchor older than 2 hours', () => {
    expect(refusal({ ...OK_BODY, originMsgId: 104 })?.status).toBe(403)
  })
  it('refuses an anchor that is no longer delivered (already closed)', () => {
    expect(refusal({ ...OK_BODY, originMsgId: 105 })?.status).toBe(403)
  })
  it('one message, one wake-up: a used anchor is refused for good', () => {
    const anchors = [{ msgId: 100, agent: 'pulzus', name: 'once-pulzus-x', at: NOW - 3600_000 * 20 }]
    expect(refusal(OK_BODY, deps({ anchors }))?.status).toBe(409)
  })
})

describe('CAPS', () => {
  const rec = (i: number, agent: string, at = NOW - 60_000): OnceAnchorRecord => ({ msgId: 1000 + i, agent, name: `n${i}`, at })
  it('per agent per rolling day', () => {
    const anchors = Array.from({ length: ONCE_MAX_PER_AGENT_PER_DAY }, (_, i) => rec(i, 'pulzus'))
    const v = validateOnceRequest(OK_BODY, deps({ anchors }))
    expect(!v.ok && v.status === 429 && v.cap).toBe('agent-day')
    expect(refusal(OK_BODY, deps({ anchors: anchors.map(a => ({ ...a, at: NOW - 25 * 3600_000 })) }))).toBeNull()
  })
  it('fleet-wide per rolling day', () => {
    const anchors = Array.from({ length: ONCE_MAX_GLOBAL_PER_DAY }, (_, i) => rec(i, `agent${i}`))
    const v = validateOnceRequest(OK_BODY, deps({ anchors }))
    expect(!v.ok && v.status === 429 && v.cap).toBe('global-day')
  })
  it('pending per agent', () => {
    const v = validateOnceRequest(OK_BODY, deps({ pendingOnceCount: () => ONCE_MAX_PENDING_PER_AGENT }))
    expect(!v.ok && v.status === 429 && v.cap).toBe('agent-pending')
  })
  it('a cap alert goes out once per agent and kind a day', () => {
    const seen = new Map<string, number>()
    expect(shouldAlertCap('pulzus', 'agent-day', NOW, seen)).toBe(true)
    expect(shouldAlertCap('pulzus', 'agent-day', NOW + 3600_000, seen)).toBe(false)
    expect(shouldAlertCap('pulzus', 'global-day', NOW + 3600_000, seen)).toBe(true)
    expect(shouldAlertCap('dave', 'agent-day', NOW + 3600_000, seen)).toBe(true)
    expect(shouldAlertCap('pulzus', 'agent-day', NOW + 25 * 3600_000, seen)).toBe(true)
  })
})

describe('ATOMIC: createOnceTask', () => {
  function harness() {
    const ledger: OnceAnchorRecord[] = []
    const order: string[] = []
    const written: OncePlan[] = []
    const alertCap = vi.fn()
    const io: OnceIo = {
      taskExists: (name) => written.some(p => p.name === name),
      recordAnchor: (r) => { order.push('ledger'); ledger.push(r) },
      writeTask: (p) => { order.push('task'); written.push(p) },
      alertCap,
    }
    // deps are read per call, as the route does (no await in between).
    const call = (body: OnceRequestBody) => createOnceTask(body, deps({ anchors: [...ledger] }), io)
    return { ledger, order, written, alertCap, call }
  }

  it('writes the ledger before the task, and a second request on the same anchor is refused', () => {
    const h = harness()
    expect(h.call(OK_BODY).ok).toBe(true)
    const second = h.call({ ...OK_BODY, inMinutes: 10 })
    expect(!second.ok && second.status).toBe(409)
    expect(h.order).toEqual(['ledger', 'task'])
    expect(h.written).toHaveLength(1)
  })

  it('a cap hit raises the alert hook; a plain refusal does not', () => {
    const h = harness()
    for (let i = 0; i < ONCE_MAX_PER_AGENT_PER_DAY; i++) h.ledger.push({ msgId: 2000 + i, agent: 'pulzus', name: `x${i}`, at: NOW - 60_000 })
    h.call(OK_BODY)
    expect(h.alertCap).toHaveBeenCalledWith('pulzus', 'agent-day', expect.stringContaining('max'))
    h.alertCap.mockClear()
    h.call({ ...OK_BODY, originMsgId: 101 })
    expect(h.alertCap).not.toHaveBeenCalled()
  })
})

describe('once helpers', () => {
  it('parseOnceRunAt: epoch ms passes, junk and naive local times do not', () => {
    expect(parseOnceRunAt(NOW)).toBe(NOW)
    expect(parseOnceRunAt('holnap')).toBeNull()
    expect(parseOnceRunAt(1.5)).toBeNull()
    expect(parseOnceRunAt('2026-11-12T08:05:00')).toBeNull()
  })
  it('keeps runAt between one minute and 24 hours ahead', () => {
    expect(refusal({ ...OK_BODY, inMinutes: 0 })?.status).toBe(400)
    expect(refusal({ ...OK_BODY, inMinutes: -5 })?.status).toBe(400)
    expect(refusal({ ...OK_BODY, inMinutes: 24 * 60 + 1 })?.status).toBe(400)
    expect(refusal({ ...OK_BODY, inMinutes: 24 * 60 })).toBeNull()
    expect(refusal({ ...OK_BODY, inMinutes: 1.5 })?.status).toBe(400)
    expect(refusal({ ...OK_BODY, runAt: '2026-11-12T08:05:00+01:00' })?.status).toBe(400) // both given
  })
  it('refuses all, system and unknown agents', () => {
    expect(refusal({ ...OK_BODY, agent: 'all' })?.status).toBe(400)
    expect(refusal({ ...OK_BODY, agent: 'system' })?.status).toBe(400)
    expect(refusal({ ...OK_BODY, agent: 'nobody' })?.status).toBe(400)
  })
  it('cronForInstant follows the wall clock across DST', () => {
    expect(cronForInstant(Date.parse('2026-07-31T10:30:00Z'), TZ)).toBe('30 12 31 7 *')
    expect(cronForInstant(Date.parse('2026-12-24T17:00:00Z'), TZ)).toBe('0 18 24 12 *')
  })
  it('the anchor ledger round-trips, skips a broken line and is owner-only', () => {
    const path = join(mkdtempSync(join(tmpdir(), 'once-ledger-')), 'a.jsonl')
    expect(readOnceAnchors(path)).toEqual([])
    recordOnceAnchor({ msgId: 1, agent: 'pulzus', name: 'n', at: 5 }, path)
    recordOnceAnchor({ msgId: 2, agent: 'dave', name: 'm', at: 6 }, path)
    expect(readOnceAnchors(path).map(a => a.msgId)).toEqual([1, 2])
    expect(statSync(path).mode & 0o777).toBe(0o600)
  })
  it('taskOccurrenceMs: runAt replaces the cron, with no lower bound', () => {
    expect(taskOccurrenceMs({ schedule: '* * * * *', runAt: NOW - 10 * 3600_000 }, NOW - 60_000, NOW)).toBe(NOW - 10 * 3600_000)
    expect(taskOccurrenceMs({ schedule: '* * * * *', runAt: NOW + 60_000 }, NOW - 60_000, NOW)).toBeNull()
  })
})

describe('self-pace gate: the whole-command /api/schedules/once exception (Viktor 38878 #4)', () => {
  const deny = (command: string) => gateDecision('Bash', { command }).deny
  const H = '-H "Content-Type: application/json" -H "Authorization: Bearer $(cat /srv/marveen/store/.dashboard-token)"'
  const URL = 'http://localhost:3420/api/schedules/once'

  it('lets the documented recipe through (heredoc, inline -d, with and without -X POST)', () => {
    expect(deny(`curl -s -X POST ${URL} ${H} --data-binary @- <<'JSON'\n{"agent":"pulzus","inMinutes":30,"originMsgId":38752}\nJSON`)).toBe(false)
    expect(deny(`curl -s -X POST ${URL} ${H} -d '{"agent":"pulzus","inMinutes":30,"originMsgId":38752}'`)).toBe(false)
    expect(deny(`curl -s ${URL} ${H} --data-binary @/tmp/o.json`)).toBe(false)
  })

  it('denies every chain, method override and path trick', () => {
    const bad = [
      `curl -s -X POST ${URL} ${H} -d @x; curl -X PUT http://localhost:3420/api/schedules/x -d @y`,
      `curl -s -X POST ${URL} ${H} -d @x && curl -X DELETE http://localhost:3420/api/schedules/x`,
      `curl -s -X POST ${URL} ${H} -d @x | sh`,
      `curl -s -X POST ${URL}/../x ${H} -d @x`,
      `curl -s -X POST http://localhost:3420/api/schedules/once%2F..%2Fx ${H} -d @x`,
      `curl -s --path-as-is -X POST ${URL} ${H} -d @x`,
      `curl -s -X POST -X PUT ${URL} ${H} -d @x`,
      `curl -s -XPUT ${URL} ${H} -d @x`,
      `curl -s --request=DELETE ${URL} ${H} -d @x`,
      `curl -s -X POST "${URL}?x=1" ${H} -d @x`,
      `curl -s -X POST ${URL}x ${H} -d @x`,
      `curl -s -X POST http://localhost:3420/API/SCHEDULES/ONCE ${H} -d @x`,
      `curl -s -X POST ${URL} http://localhost:3420/api/schedules ${H} -d @x`,
      `curl -s -K /tmp/cfg -X POST ${URL} ${H} -d @x`,
      `curl -s -X POST ${URL} ${H} -d @x --next -X PUT http://localhost:3420/api/memories/1`,
      // (a URL held wholly in a variable never names /api/schedules, so the gate
      // never saw it, before or after this change: the server check is the gate)
      `curl -s -X POST ${URL}$SUFFIX ${H} -d @x`,
      `curl -s -X POST ${URL} -H "X: \${HOME}" ${H} -d @x`,
      `curl -s -X POST \`echo ${URL}\` ${H} -d @x`,
      `curl -s -X POST ${URL} ${H} -d "$(cat /tmp/x)"`,
      `sh -c 'curl -s -X POST ${URL} -d @x'`,
      `curl -s -X POST http://localhost:3420/api/schedules -d @x.json`,
      `curl -s -X POST ${URL} ${H} --data-binary @- <<'JSON'\n{"next":"/api/schedules/x"}\nJSON`,
      `curl -s -X POST ${URL} ${H} --data-binary @- <<JSON\n{"agent":"$(id)"}\nJSON`,
    ]
    const passed = bad.filter(c => !deny(c))
    expect(passed, `commands the gate let through:\n${passed.join('\n')}`).toEqual([])
  })

  it('onceCommandAllowed is the whole-command test, and a GET of the list stays allowed', () => {
    expect(onceCommandAllowed(`curl -s -X POST ${URL} ${H} -d @x`)).toBe(true)
    expect(onceCommandAllowed(`echo hi; curl -s -X POST ${URL} ${H} -d @x`)).toBe(false)
    expect(deny('curl -s http://localhost:3420/api/schedules')).toBe(false)
  })
})
