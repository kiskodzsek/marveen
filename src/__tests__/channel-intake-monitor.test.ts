// A dead inbound pipe produces no event: nothing arrives, nothing errors, and
// the pane keeps rendering a connected plugin. Finy was deaf for five days in
// July 2026 and every existing check was satisfied the whole time.
//
// These tests pin the two positive signals that DO exist while the channel is
// deaf, so the detection never rests on an absence again:
//   1. getWebhookInfo.pending_update_count > 0 -- updates queued upstream that
//      nobody is fetching. Proof, not suspicion.
//   2. getMe answering ok:false -- the token itself is gone.
// Inbound silence alone stays a suspicion and must never alert on its own: an
// agent with nothing to do is legitimately silent for days.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { homedir, tmpdir } from 'node:os'
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { MAIN_AGENT_ID } from '../config.js'
import {
  channelEnvPathCandidates,
  channelEnvPathFor,
  parseIntakeProbe,
  decideIntakeVerdict,
  intakeStateEntry,
  noTokenStateEntryFor,
  recoveryNoticeFor,
  seedMainStateFrom,
  seedIntakeStateFromFile,
  intakeStateSnapshot,
  applyIntakeProbe,
  isTokenRejection,
  resetIntakeObservations,
  startChannelIntakeMonitor,
  SEED_MAX_STRETCH_MS,
  ERROR_TEXT_MAX,
  ONGOING_OUTAGE_NOTICE_MS,
  ongoingOutageNoticeFor,
  STATE_SEED_MAX_AGE_MS,
  INTAKE_ALERT_COOLDOWN_MS,
  unreachableRecoveredAfter,
  formatUnreachableRecovered,
  writeIntakeState,
  UNREACHABLE_RECOVERY_NOTICE_MS,
  type IntakeStateEntry,
  type IntakeProbe,
  type IntakeObservation,
} from '../web/channel-intake-monitor.js'

const DAY_MS = 24 * 60 * 60 * 1000
const SILENCE_MS = 2 * DAY_MS
const NOW = 1_760_000_000_000

function probe(over: Partial<IntakeProbe> = {}): IntakeProbe {
  return { reachable: true, tokenOk: true, pendingUpdates: 0, webhookUrl: '', lastErrorMessage: null, httpStatus: 200, ...over }
}

describe('parseIntakeProbe', () => {
  it('reads the pending update count out of a healthy getWebhookInfo body', () => {
    const r = parseIntakeProbe(200, {
      ok: true,
      result: { url: '', pending_update_count: 7, last_error_message: 'wrong response' },
    })
    expect(r).toEqual({
      reachable: true,
      tokenOk: true,
      pendingUpdates: 7,
      webhookUrl: '',
      lastErrorMessage: 'wrong response',
      httpStatus: 200,
    })
  })

  it('parses the exact body a healthy live bot returned on 2026-09-06', () => {
    // Verbatim from getWebhookInfo against a running fleet agent's token.
    const r = parseIntakeProbe(200, {
      ok: true,
      result: { url: '', has_custom_certificate: false, pending_update_count: 0 },
    })
    expect(r.tokenOk).toBe(true)
    expect(r.pendingUpdates).toBe(0)
    expect(r.lastErrorMessage).toBeNull()
  })

  it('marks the token invalid when Telegram rejects it', () => {
    const r = parseIntakeProbe(401, { ok: false, error_code: 401, description: 'Unauthorized' })
    expect(r.tokenOk).toBe(false)
    expect(r.reachable).toBe(true)
    expect(r.pendingUpdates).toBeNull()
  })

  it('reports unreachable (not token-invalid) when the HTTP call itself failed', () => {
    const r = parseIntakeProbe(0, null)
    expect(r.reachable).toBe(false)
    expect(r.tokenOk).toBe(true)
    expect(r.pendingUpdates).toBeNull()
  })
})

describe('decideIntakeVerdict', () => {
  it('stays silent while the channel is quiet but the intake is clean', () => {
    const d = decideIntakeVerdict({
      probe: probe(),
      prev: null,
      lastInboundAt: NOW - 5 * DAY_MS,
      now: NOW,
      silenceThresholdMs: SILENCE_MS,
    })
    expect(d.verdict).toBe('quiet')
    expect(d.alert).toBe(false)
  })

  it('says ok when inbound arrived inside the silence window', () => {
    const d = decideIntakeVerdict({
      probe: probe(),
      prev: null,
      lastInboundAt: NOW - 60_000,
      now: NOW,
      silenceThresholdMs: SILENCE_MS,
    })
    expect(d.verdict).toBe('ok')
    expect(d.alert).toBe(false)
  })

  it('does not alert on a single backlog reading -- one tick can catch a burst mid-fetch', () => {
    const d = decideIntakeVerdict({
      probe: probe({ pendingUpdates: 3 }),
      prev: null,
      lastInboundAt: NOW - 5 * DAY_MS,
      now: NOW,
      silenceThresholdMs: SILENCE_MS,
    })
    expect(d.verdict).toBe('backlog-suspected')
    expect(d.alert).toBe(false)
  })

  it('alerts when the backlog is still there on the next tick and has not shrunk', () => {
    const prev: IntakeObservation = { at: NOW - 5 * 60_000, pendingUpdates: 3 }
    const d = decideIntakeVerdict({
      probe: probe({ pendingUpdates: 4 }),
      prev,
      lastInboundAt: NOW - 5 * DAY_MS,
      now: NOW,
      silenceThresholdMs: SILENCE_MS,
    })
    expect(d.verdict).toBe('deaf-backlog')
    expect(d.alert).toBe(true)
  })

  it('alerts on a persistent backlog even when inbound is recent -- deafness is not a silence question', () => {
    const prev: IntakeObservation = { at: NOW - 5 * 60_000, pendingUpdates: 2 }
    const d = decideIntakeVerdict({
      probe: probe({ pendingUpdates: 2 }),
      prev,
      lastInboundAt: NOW - 60_000,
      now: NOW,
      silenceThresholdMs: SILENCE_MS,
    })
    expect(d.verdict).toBe('deaf-backlog')
    expect(d.alert).toBe(true)
  })

  it('clears the suspicion when the poller drained the queue between ticks', () => {
    const prev: IntakeObservation = { at: NOW - 5 * 60_000, pendingUpdates: 9 }
    const d = decideIntakeVerdict({
      probe: probe({ pendingUpdates: 2 }),
      prev,
      lastInboundAt: NOW - 60_000,
      now: NOW,
      silenceThresholdMs: SILENCE_MS,
    })
    expect(d.verdict).toBe('draining')
    expect(d.alert).toBe(false)
  })

  it('does not confirm a backlog from two readings taken in the same moment', () => {
    const prev: IntakeObservation = { at: NOW - 1_000, pendingUpdates: 3 }
    const d = decideIntakeVerdict({
      probe: probe({ pendingUpdates: 3 }),
      prev,
      lastInboundAt: NOW - 60_000,
      now: NOW,
      silenceThresholdMs: SILENCE_MS,
    })
    expect(d.verdict).toBe('backlog-suspected')
    expect(d.alert).toBe(false)
  })

  it('alerts when the token stopped working', () => {
    const d = decideIntakeVerdict({
      probe: probe({ tokenOk: false, pendingUpdates: null }),
      prev: null,
      lastInboundAt: NOW - 60_000,
      now: NOW,
      silenceThresholdMs: SILENCE_MS,
    })
    expect(d.verdict).toBe('token-invalid')
    expect(d.alert).toBe(true)
  })

  it('never alerts when our own side could not reach Telegram', () => {
    const d = decideIntakeVerdict({
      probe: probe({ reachable: false, pendingUpdates: null, httpStatus: null }),
      prev: null,
      lastInboundAt: NOW - 9 * DAY_MS,
      now: NOW,
      silenceThresholdMs: SILENCE_MS,
    })
    expect(d.verdict).toBe('unreachable')
    expect(d.alert).toBe(false)
  })

  it('reports a missing ingestion timestamp as unknown, never as proven silence', () => {
    const d = decideIntakeVerdict({
      probe: probe(),
      prev: null,
      lastInboundAt: null,
      now: NOW,
      silenceThresholdMs: SILENCE_MS,
    })
    expect(d.verdict).toBe('unknown-inbound')
    expect(d.alert).toBe(false)
  })
})

// Card 6a9c1cc0 (Klodel kanban 20225): the main bot was deaf 07:20-10:38 on
// 2026-11-13 and this monitor never probed it -- it looked for the main token
// under homedir()/.claude/channels/telegram, while channels.sh runs the main
// session with TELEGRAM_STATE_DIR=$INSTALL_DIR/.claude/channels/telegram.
describe('channelEnvPathFor: the main agent is probed with the token its session uses', () => {
  const ROOT = '/opt/marveen-install'
  const installEnv = `${ROOT}/.claude/channels/telegram/.env`
  const homeEnv = `${homedir()}/.claude/channels/telegram/.env`

  it('prefers the install-dir channel (channels.sh MAIN_CHAN_DIR) for the main agent', () => {
    expect(channelEnvPathCandidates(MAIN_AGENT_ID, ROOT)[0]).toBe(installEnv)
    expect(channelEnvPathFor(MAIN_AGENT_ID, ROOT, p => p === installEnv)).toBe(installEnv)
  })

  it('NEGATIVE: with only the install-dir .env present it does NOT pick the missing home path (the 11-13 blind spot)', () => {
    expect(channelEnvPathFor(MAIN_AGENT_ID, ROOT, p => p === installEnv)).not.toBe(homeEnv)
  })

  it('falls back to the home channel on an older install', () => {
    expect(channelEnvPathFor(MAIN_AGENT_ID, ROOT, p => p === homeEnv)).toBe(homeEnv)
  })

  it('NEGATIVE: a sub-agent never reads the main install or home channel', () => {
    const c = channelEnvPathCandidates('subagent-x', ROOT)
    expect(c).toHaveLength(1)
    expect(c[0]).not.toBe(installEnv)
    expect(c[0]).not.toBe(homeEnv)
    expect(c[0].endsWith('/subagent-x/.claude/channels/telegram/.env')).toBe(true)
  })
})

// The monitor is silent on success, so on 2026-11-13 a working probe of the main
// bot could not be told apart from one that never ran (Pulzus 11:10, card
// 6a9c1cc0). The state file is the positive, measurable trace -- and it must
// never carry the token or anything Telegram echoes back.
describe('intake state: a measurable trace without secrets', () => {
  const TOKEN = '123456:SECRET-token-value'
  const URL = 'https://example.invalid/hook/' + TOKEN

  it('records reachability, token validity, the pending count and the verdict', () => {
    const e = intakeStateEntry(probe({ pendingUpdates: 0 }), 'ok', NOW, null)
    expect(e).toEqual({ at: NOW, verdict: 'ok', reachable: true, tokenOk: true, pending: 0, unreachableSince: null })
  })

  it('NEGATIVE: the entry carries no token, webhook URL or Telegram error text', () => {
    const e = intakeStateEntry(
      probe({ webhookUrl: URL, lastErrorMessage: 'Unauthorized ' + TOKEN, tokenOk: false }),
      'token-invalid', NOW, null,
    )
    const json = JSON.stringify(e)
    expect(json).not.toContain('SECRET')
    expect(json).not.toContain('example.invalid')
    expect(json).not.toContain('Unauthorized')
    expect(Object.keys(e).sort()).toEqual(['at', 'pending', 'reachable', 'tokenOk', 'unreachableSince', 'verdict'])
  })

  it('makes the main-agent blind spot visible as no-token instead of a missing row', () => {
    expect(noTokenStateEntryFor(MAIN_AGENT_ID, NOW)).toEqual({ at: NOW, verdict: 'no-token', reachable: null, tokenOk: null, pending: null, unreachableSince: null })
  })

  it('NEGATIVE: a sub-agent without a token gets no row (no channel is normal there)', () => {
    expect(noTokenStateEntryFor('some-sub-agent', NOW)).toBeNull()
  })

  it('keeps an unknown pending count unknown, never 0 (Viktor 42107 INFO 1, M16)', () => {
    expect(intakeStateEntry(probe({ reachable: false, pendingUpdates: null, httpStatus: null }), 'unreachable', NOW, null).pending).toBeNull()
  })

  it('records the verdict it was given, not a fixed one (M18)', () => {
    expect(intakeStateEntry(probe({ pendingUpdates: 4 }), 'deaf-backlog', NOW, null).verdict).toBe('deaf-backlog')
  })

  it('writes the file atomically, mode 0600, readable back, with no tmp file left over', () => {
    const dir = mkdtempSync(join(tmpdir(), 'intake-state-'))
    try {
      const path = join(dir, 'channel-intake-state.json')
      const entries = new Map<string, IntakeStateEntry>([[MAIN_AGENT_ID, intakeStateEntry(probe(), 'ok', NOW, null)]])
      writeIntakeState(path, entries, NOW + 1)
      const body = JSON.parse(readFileSync(path, 'utf-8'))
      expect(body.writtenAt).toBe(NOW + 1)
      expect(body.agents[MAIN_AGENT_ID].verdict).toBe('ok')
      expect(statSync(path).mode & 0o777).toBe(0o600)
      expect(readdirSync(dir)).toEqual(['channel-intake-state.json'])
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })
})

// 2026-11-13 10:10-10:38: the network was gone, every probe said 'unreachable'
// (correctly silent), and the backlog then landed in one burst with nobody told
// why. The stretch is tracked across ticks and reported once, when it ends.
describe('unreachable stretch: one line when a long outage ends', () => {
  const MIN = 60 * 1000
  const down = probe({ reachable: false, pendingUpdates: null, httpStatus: null })

  it('starts the stretch at the first unreachable reading and keeps that start across ticks', () => {
    const first = intakeStateEntry(down, 'unreachable', NOW, null)
    expect(first.unreachableSince).toBe(NOW)
    const second = intakeStateEntry(down, 'unreachable', NOW + 5 * MIN, first)
    expect(second.unreachableSince).toBe(NOW)
  })

  it('clears the stretch on the first reachable reading', () => {
    const prev = intakeStateEntry(down, 'unreachable', NOW, null)
    expect(intakeStateEntry(probe(), 'ok', NOW + 5 * MIN, prev).unreachableSince).toBeNull()
  })

  it('reports the length when a stretch of at least the threshold ends', () => {
    const prev = intakeStateEntry(down, 'unreachable', NOW, null)
    const len = UNREACHABLE_RECOVERY_NOTICE_MS + 3 * MIN
    expect(unreachableRecoveredAfter(prev, probe(), NOW + len)).toBe(len)
  })

  it('pins the threshold at 30 minutes and reports a stretch of exactly that length (M03, M14)', () => {
    expect(UNREACHABLE_RECOVERY_NOTICE_MS).toBe(30 * MIN)
    const prev = intakeStateEntry(down, 'unreachable', NOW, null)
    expect(unreachableRecoveredAfter(prev, probe(), NOW + 30 * MIN)).toBe(30 * MIN)
  })

  it('NEGATIVE: a short blip is not reported', () => {
    const prev = intakeStateEntry(down, 'unreachable', NOW, null)
    expect(unreachableRecoveredAfter(prev, probe(), NOW + UNREACHABLE_RECOVERY_NOTICE_MS - 1)).toBeNull()
  })

  it('NEGATIVE: nothing is reported while the outage is still going on', () => {
    const prev = intakeStateEntry(down, 'unreachable', NOW, null)
    expect(unreachableRecoveredAfter(prev, down, NOW + 2 * UNREACHABLE_RECOVERY_NOTICE_MS)).toBeNull()
  })

  it('NEGATIVE: a reachable reading after a reachable one is not a recovery', () => {
    const prev = intakeStateEntry(probe(), 'ok', NOW, null)
    expect(unreachableRecoveredAfter(prev, probe(), NOW + 2 * UNREACHABLE_RECOVERY_NOTICE_MS)).toBeNull()
    expect(unreachableRecoveredAfter(null, probe(), NOW)).toBeNull()
  })

  it('says how long and since when, in Budapest time', () => {
    const since = Date.UTC(2026, 10, 13, 9, 10) // 10:10 Budapest
    const text = formatUnreachableRecovered(MAIN_AGENT_ID, 28 * MIN, since)
    expect(text).toContain('28 percig')
    expect(text).toContain('10:10')
    expect(text).toContain(MAIN_AGENT_ID)
  })

  it('rounds the minutes, not truncates (M13)', () => {
    expect(formatUnreachableRecovered(MAIN_AGENT_ID, 28.6 * MIN, NOW)).toContain('29 percig')
  })

  it('marks the deafness as an inference, not a measurement (Viktor 42107 LOW 2)', () => {
    const text = formatUnreachableRecovered(MAIN_AGENT_ID, 40 * MIN, NOW)
    expect(text).toContain('valószínűleg befelé süket')
    expect(text).toContain('feltehetően')
  })

  it('NEGATIVE: the clock does not follow the host time zone (the mini runs in Budapest, a CI runner does not)', () => {
    const saved = process.env.TZ
    process.env.TZ = 'America/New_York'
    try {
      const text = formatUnreachableRecovered(MAIN_AGENT_ID, 28 * MIN, Date.UTC(2026, 10, 13, 9, 10))
      expect(text).toContain('10:10')
      expect(text).not.toContain('04:10')
    } finally {
      if (saved === undefined) delete process.env.TZ
      else process.env.TZ = saved
    }
  })
})

// Viktor 42107 LOW 3: the decision that lives in the runtime (main-only, the
// cooldown) was untested; W01 (a notice per bot) and W02 (no cooldown) survived.
describe('recoveryNoticeFor: one notice, main agent only, with the 3 h cooldown', () => {
  const MIN = 60 * 1000
  const down = probe({ reachable: false, pendingUpdates: null, httpStatus: null })
  const prev = intakeStateEntry(down, 'unreachable', NOW, null)

  it('gives the main agent one notice with the stretch length and the 3 h cooldown', () => {
    const n = recoveryNoticeFor(MAIN_AGENT_ID, prev, probe(), NOW + 40 * MIN)
    expect(n).not.toBeNull()
    expect(n!.key).toBe(`channel-intake:${MAIN_AGENT_ID}:unreachable-recovered`)
    expect(n!.text).toContain('40 percig')
    expect(n!.cooldownMs).toBe(INTAKE_ALERT_COOLDOWN_MS)
    expect(INTAKE_ALERT_COOLDOWN_MS).toBe(3 * 60 * MIN)
  })

  it('NEGATIVE: a sub-agent never gets one, even after the same outage (W01)', () => {
    expect(recoveryNoticeFor('some-sub-agent', prev, probe(), NOW + 40 * MIN)).toBeNull()
  })

  it('NEGATIVE: no notice below the threshold or while still unreachable', () => {
    expect(recoveryNoticeFor(MAIN_AGENT_ID, prev, probe(), NOW + 29 * MIN)).toBeNull()
    expect(recoveryNoticeFor(MAIN_AGENT_ID, prev, down, NOW + 40 * MIN)).toBeNull()
  })
})

// Viktor 42107 LOW 1: a restart in the middle of an outage must not lose the stretch's start.
describe('seedMainStateFrom: carry the main row over a restart, only when fresh and well-formed', () => {
  const MIN = 60 * 1000
  const row = { at: NOW - 5 * MIN, verdict: 'unreachable', reachable: false, tokenOk: true, pending: null, unreachableSince: NOW - 25 * MIN }
  const file = (agents: Record<string, unknown>) => JSON.stringify({ writtenAt: NOW - 5 * MIN, agents })

  it('carries a fresh main row, keeping the stretch start', () => {
    const seeded = seedMainStateFrom(file({ [MAIN_AGENT_ID]: row }), NOW)
    expect(seeded).toEqual(row)
    // after the restart, recovery is measured from the ORIGINAL start
    const n = recoveryNoticeFor(MAIN_AGENT_ID, seeded, probe(), NOW + 10 * MIN)
    expect(n!.text).toContain('35 percig')
    // without the seed the same reading would say nothing (the LOW 1 gap)
    expect(recoveryNoticeFor(MAIN_AGENT_ID, null, probe(), NOW + 10 * MIN)).toBeNull()
  })

  it('pins the freshness window at 15 minutes', () => {
    expect(STATE_SEED_MAX_AGE_MS).toBe(15 * MIN)
    expect(seedMainStateFrom(file({ [MAIN_AGENT_ID]: { ...row, at: NOW - 15 * MIN } }), NOW)).not.toBeNull()
  })

  it('NEGATIVE: a stale row, a row from the future, or a missing file is not carried', () => {
    expect(seedMainStateFrom(file({ [MAIN_AGENT_ID]: { ...row, at: NOW - 15 * MIN - 1 } }), NOW)).toBeNull()
    expect(seedMainStateFrom(file({ [MAIN_AGENT_ID]: { ...row, at: NOW + 1 } }), NOW)).toBeNull()
    expect(seedMainStateFrom(null, NOW)).toBeNull()
  })

  it('NEGATIVE: only the main row is read, and a malformed file or row is ignored', () => {
    expect(seedMainStateFrom(file({ 'some-sub-agent': row }), NOW)).toBeNull()
    expect(seedMainStateFrom('{not json', NOW)).toBeNull()
    expect(seedMainStateFrom(file({ [MAIN_AGENT_ID]: { ...row, unreachableSince: 'yesterday' } }), NOW)).toBeNull()
    expect(seedMainStateFrom(file({ [MAIN_AGENT_ID]: { ...row, reachable: 'no' } }), NOW)).toBeNull()
    expect(seedMainStateFrom(file({ [MAIN_AGENT_ID]: { ...row, unreachableSince: row.at + 1 } }), NOW)).toBeNull()
    expect(seedMainStateFrom('null', NOW)).toBeNull()
  })
})

// Card fe7f332b (Viktor 42107 INFO 3): every non-200 answer used to be read as
// token-invalid, so a Telegram-side 502/429 or a proxy's HTML page would page the
// owner about a "rejected token" and cut an outage stretch short.
describe('parseIntakeProbe: only Telegram refusing the token is a token verdict', () => {
  it('still reads 401 Unauthorized as a rejected token', () => {
    expect(isTokenRejection(401, { ok: false, error_code: 401, description: 'Unauthorized' })).toBe(true)
  })

  it("reads a 404 carrying Telegram's own JSON as a rejected token", () => {
    const r = parseIntakeProbe(404, { ok: false, error_code: 404, description: 'Not Found' })
    expect(r.tokenOk).toBe(false)
    expect(r.reachable).toBe(true)
  })

  it('NEGATIVE: a 502 from Telegram is not a token verdict and does not alert', () => {
    const r = parseIntakeProbe(502, { ok: false, error_code: 502, description: 'Bad Gateway' })
    expect(r).toEqual({ reachable: false, tokenOk: true, pendingUpdates: null, webhookUrl: null, lastErrorMessage: null, httpStatus: 502 })
    const d = decideIntakeVerdict({ probe: r, prev: null, lastInboundAt: null, now: NOW, silenceThresholdMs: SILENCE_MS })
    expect(d).toEqual({ verdict: 'unreachable', alert: false })
  })

  it('NEGATIVE: a 429 rate limit is not a token verdict', () => {
    const r = parseIntakeProbe(429, { ok: false, error_code: 429, description: 'Too Many Requests: retry after 5', parameters: { retry_after: 5 } })
    expect(r.tokenOk).toBe(true)
    expect(r.reachable).toBe(false)
  })

  it("NEGATIVE: a proxy's HTML page (no JSON body) is not a token verdict, whatever its status", () => {
    for (const status of [403, 404, 500, 502, 503]) {
      const r = parseIntakeProbe(status, null)
      expect(r.tokenOk, `status ${status}`).toBe(true)
      expect(r.reachable, `status ${status}`).toBe(false)
    }
  })

  it('NEGATIVE: a 200 without a usable body is not a token verdict', () => {
    expect(parseIntakeProbe(200, { ok: true }).tokenOk).toBe(true)
    expect(parseIntakeProbe(200, { ok: true }).reachable).toBe(false)
    expect(parseIntakeProbe(200, null).tokenOk).toBe(true)
  })

  it('NEGATIVE: a 5xx in the middle of an outage keeps the stretch going instead of cutting it', () => {
    const MIN = 60 * 1000
    const first = intakeStateEntry(parseIntakeProbe(0, null), 'unreachable', NOW, null)
    const mid = intakeStateEntry(parseIntakeProbe(502, { ok: false, error_code: 502 }), 'unreachable', NOW + 10 * MIN, first)
    expect(mid.unreachableSince).toBe(NOW)
  })
})

// Viktor 42111 LOW (W14, W15): the pure decisions were tested, their call sites were not.
describe('applyIntakeProbe: the alerts at their call site', () => {
  const MIN = 60 * 1000
  const down = probe({ reachable: false, pendingUpdates: null, httpStatus: null })
  type Sent = { key: string, text: string, cooldownMs: number }
  const sender = () => {
    const sent: Sent[] = []
    return { sent, send: (key: string, text: string, opts: { cooldownMs: number }) => { sent.push({ key, text, cooldownMs: opts.cooldownMs }) } }
  }
  beforeEach(() => resetIntakeObservations())

  it('sends exactly one outage-end notice for the main agent, with the 3 h cooldown', () => {
    const { sent, send } = sender()
    applyIntakeProbe(MAIN_AGENT_ID, down, null, NOW, send)
    applyIntakeProbe(MAIN_AGENT_ID, down, null, NOW + 20 * MIN, send)
    expect(sent).toEqual([])
    applyIntakeProbe(MAIN_AGENT_ID, probe(), null, NOW + 35 * MIN, send)
    applyIntakeProbe(MAIN_AGENT_ID, probe(), null, NOW + 40 * MIN, send)
    expect(sent).toHaveLength(1)
    expect(sent[0].key).toBe(`channel-intake:${MAIN_AGENT_ID}:unreachable-recovered`)
    expect(sent[0].cooldownMs).toBe(INTAKE_ALERT_COOLDOWN_MS)
    expect(sent[0].text).toContain('kb. 35 percig')
  })

  it('NEGATIVE: a sub-agent behind the same outage sends nothing', () => {
    const { sent, send } = sender()
    applyIntakeProbe('some-sub-agent', down, null, NOW, send)
    applyIntakeProbe('some-sub-agent', probe(), null, NOW + 40 * MIN, send)
    expect(sent).toEqual([])
  })

  it('NEGATIVE: a Telegram-side 502 outage ends in one outage notice and never a token alert', () => {
    const { sent, send } = sender()
    const bad = parseIntakeProbe(502, { ok: false, error_code: 502, description: 'Bad Gateway' })
    for (let m = 0; m <= 35; m += 5) applyIntakeProbe(MAIN_AGENT_ID, bad, null, NOW + m * MIN, send)
    applyIntakeProbe(MAIN_AGENT_ID, probe(), null, NOW + 40 * MIN, send)
    expect(sent.map(x => x.key)).toEqual([`channel-intake:${MAIN_AGENT_ID}:unreachable-recovered`])
  })

  it('sends the deafness alert on a confirmed backlog, with the 3 h cooldown', () => {
    const { sent, send } = sender()
    applyIntakeProbe('some-sub-agent', probe({ pendingUpdates: 3 }), null, NOW, send)
    expect(sent).toEqual([])
    const d = applyIntakeProbe('some-sub-agent', probe({ pendingUpdates: 3 }), null, NOW + 5 * MIN, send)
    expect(d.verdict).toBe('deaf-backlog')
    expect(sent).toHaveLength(1)
    expect(sent[0].key).toBe('channel-intake:some-sub-agent:deaf-backlog')
    expect(sent[0].cooldownMs).toBe(INTAKE_ALERT_COOLDOWN_MS)
  })

  it('records the state row the next write will carry', () => {
    const { send } = sender()
    applyIntakeProbe(MAIN_AGENT_ID, probe({ pendingUpdates: 0 }), null, NOW, send)
    expect(intakeStateSnapshot().get(MAIN_AGENT_ID)).toEqual({ at: NOW, verdict: 'unknown-inbound', reachable: true, tokenOk: true, pending: 0, unreachableSince: null })
  })
})

// Viktor 42111 LOW (W07): the seed must actually run when the monitor starts.
describe('startChannelIntakeMonitor carries the main row over a restart', () => {
  const MIN = 60 * 1000
  const row = { at: NOW - 5 * MIN, verdict: 'unreachable', reachable: false, tokenOk: true, pending: null, unreachableSince: NOW - 25 * MIN }
  beforeEach(() => resetIntakeObservations())

  function withStateFile(body: unknown, fn: (path: string) => void): void {
    const dir = mkdtempSync(join(tmpdir(), 'intake-seed-'))
    vi.useFakeTimers({ now: NOW })
    try {
      const path = join(dir, 'channel-intake-state.json')
      if (body !== undefined) writeFileSync(path, JSON.stringify(body))
      fn(path)
    } finally {
      vi.clearAllTimers()
      vi.useRealTimers()
      rmSync(dir, { recursive: true, force: true })
    }
  }

  it('seeds at start, and the first reachable reading reports the stretch from its ORIGINAL start', () => {
    withStateFile({ writtenAt: row.at, agents: { [MAIN_AGENT_ID]: row } }, (path) => {
      const timer = startChannelIntakeMonitor('/nonexistent-project-root', { stateFile: path })
      clearInterval(timer)
      expect(intakeStateSnapshot().get(MAIN_AGENT_ID)).toEqual(row)
      const sent: string[] = []
      applyIntakeProbe(MAIN_AGENT_ID, probe(), null, NOW + 10 * MIN, (_k, text) => { sent.push(text) })
      expect(sent).toHaveLength(1)
      expect(sent[0]).toContain('kb. 35 percig')
      const since = new Date(row.unreachableSince).toLocaleTimeString('hu-HU', { timeZone: 'Europe/Budapest', hour: '2-digit', minute: '2-digit' })
      expect(sent[0]).toContain(`(${since} óta)`)
    })
  })

  it('NEGATIVE: a stale file seeds nothing at start', () => {
    withStateFile({ writtenAt: 0, agents: { [MAIN_AGENT_ID]: { ...row, at: NOW - 16 * MIN } } }, (path) => {
      clearInterval(startChannelIntakeMonitor('/nonexistent-project-root', { stateFile: path }))
      expect(intakeStateSnapshot().has(MAIN_AGENT_ID)).toBe(false)
    })
  })

  it('NEGATIVE: a missing file seeds nothing and does not throw', () => {
    withStateFile(undefined, (path) => {
      expect(seedIntakeStateFromFile(path, NOW)).toBe(false)
      expect(intakeStateSnapshot().size).toBe(0)
    })
  })
})

// Viktor 42111 INFO 1 and 3: the seed's lower bound and the type checks are pinned.
describe('seedMainStateFrom: lower bound and field types', () => {
  const MIN = 60 * 1000
  const row = { at: NOW - 5 * MIN, verdict: 'unreachable', reachable: false, tokenOk: true, pending: null, unreachableSince: NOW - 25 * MIN }
  const file = (r: Record<string, unknown>) => JSON.stringify({ writtenAt: NOW, agents: { [MAIN_AGENT_ID]: r } })

  it('pins the longest carried stretch at 7 days, inclusive', () => {
    expect(SEED_MAX_STRETCH_MS).toBe(7 * DAY_MS)
    expect(seedMainStateFrom(file({ ...row, unreachableSince: row.at - 7 * DAY_MS }), NOW)).not.toBeNull()
  })

  it('NEGATIVE: an older stretch, the epoch or a far-negative start is dropped (no "29910720 percig")', () => {
    expect(seedMainStateFrom(file({ ...row, unreachableSince: row.at - 7 * DAY_MS - 1 }), NOW)).toBeNull()
    expect(seedMainStateFrom(file({ ...row, unreachableSince: 0 }), NOW)).toBeNull()
    expect(seedMainStateFrom(file({ ...row, unreachableSince: -1e15 }), NOW)).toBeNull()
  })

  it('NEGATIVE: an infinite start, a non-string verdict or a non-number pending is dropped (S07-S09)', () => {
    const raw = file(row).replace(`"unreachableSince":${row.unreachableSince}`, '"unreachableSince":-1e999')
    expect(raw).toContain('-1e999')
    expect(seedMainStateFrom(raw, NOW)).toBeNull()
    expect(seedMainStateFrom(file({ ...row, verdict: 7 }), NOW)).toBeNull()
    expect(seedMainStateFrom(file({ ...row, pending: '3' }), NOW)).toBeNull()
  })

  it('says "kb." in every outage notice: the stretch is measured in 5-minute ticks', () => {
    expect(formatUnreachableRecovered(MAIN_AGENT_ID, 40 * MIN, NOW)).toContain('a gép kb. 40 percig')
  })
})

// Card 8d58be99 (Viktor 42131 INFO 1-4).
describe('parseIntakeProbe: proxy pages, long error texts, the HTTP status', () => {
  it("NEGATIVE: a proxy's 401 page (HTML, plain text, an array) is not a token verdict (INFO 1)", () => {
    for (const body of [null, '<html>401 Authorization Required</html>', [1, 2]]) {
      const r = parseIntakeProbe(401, body)
      expect(r.tokenOk, JSON.stringify(body)).toBe(true)
      expect(r.reachable, JSON.stringify(body)).toBe(false)
    }
    expect(isTokenRejection(401, null)).toBe(false)
  })

  it("still reads Telegram's own 401 JSON as a rejected token", () => {
    const r = parseIntakeProbe(401, { ok: false, error_code: 401, description: 'Unauthorized' })
    expect(r.tokenOk).toBe(false)
    expect(r.lastErrorMessage).toBe('Unauthorized')
  })

  it('clips an unbounded error text to ERROR_TEXT_MAX characters (INFO 2)', () => {
    expect(ERROR_TEXT_MAX).toBe(200)
    const long = 'x'.repeat(100_000)
    const rejected = parseIntakeProbe(401, { ok: false, description: long })
    expect(rejected.lastErrorMessage).toBe('x'.repeat(200) + '…')
    const healthy = parseIntakeProbe(200, { ok: true, result: { pending_update_count: 0, last_error_message: long } })
    expect(healthy.lastErrorMessage).toBe('x'.repeat(200) + '…')
    expect(parseIntakeProbe(401, { ok: false, description: 'x'.repeat(200) }).lastErrorMessage).toBe('x'.repeat(200))
  })

  it('NEGATIVE: a non-string description never becomes the error text (P05)', () => {
    expect(parseIntakeProbe(401, { ok: false, description: { html: 'x' } }).lastErrorMessage).toBeNull()
  })

  it('NEGATIVE: a 200 with ok:false and a result is not a healthy answer (P06)', () => {
    const r = parseIntakeProbe(200, { ok: false, result: { pending_update_count: 0 } })
    expect(r.reachable).toBe(false)
    expect(r.pendingUpdates).toBeNull()
  })

  it('keeps the HTTP status of an answer, and null when the call never completed', () => {
    expect(parseIntakeProbe(502, null).httpStatus).toBe(502)
    expect(parseIntakeProbe(200, { ok: true, result: { pending_update_count: 0 } }).httpStatus).toBe(200)
    expect(parseIntakeProbe(0, null).httpStatus).toBeNull()
  })
})

describe('ongoingOutageNoticeFor: one line WHILE Telegram answers unusably (INFO 3)', () => {
  const MIN = 60 * 1000
  const bad = parseIntakeProbe(502, { ok: false, error_code: 502, description: 'Bad Gateway' })
  const net = parseIntakeProbe(0, null)
  const start = intakeStateEntry(bad, 'unreachable', NOW, null)

  it('pins the threshold at 2 hours and names the last HTTP status', () => {
    expect(ONGOING_OUTAGE_NOTICE_MS).toBe(120 * MIN)
    const entry = intakeStateEntry(bad, 'unreachable', NOW + 120 * MIN, start)
    const n = ongoingOutageNoticeFor(MAIN_AGENT_ID, entry, bad, NOW + 120 * MIN)
    expect(n!.key).toBe(`channel-intake:${MAIN_AGENT_ID}:outage-ongoing`)
    expect(n!.cooldownMs).toBe(INTAKE_ALERT_COOLDOWN_MS)
    expect(n!.text).toContain('kb. 120 perce nem kap használható választ')
    expect(n!.text).toContain('utolsó HTTP-kód: 502')
    expect(n!.text).toContain('valószínűleg')
  })

  it('NEGATIVE: not before 2 hours', () => {
    const entry = intakeStateEntry(bad, 'unreachable', NOW + 120 * MIN - 1, start)
    expect(ongoingOutageNoticeFor(MAIN_AGENT_ID, entry, bad, NOW + 120 * MIN - 1)).toBeNull()
  })

  it('NEGATIVE: not during a network outage (the alert could not go out anyway)', () => {
    const entry = intakeStateEntry(net, 'unreachable', NOW + 180 * MIN, start)
    expect(ongoingOutageNoticeFor(MAIN_AGENT_ID, entry, net, NOW + 180 * MIN)).toBeNull()
  })

  it('NEGATIVE: not for a sub-agent, and not once Telegram answers usefully', () => {
    const entry = intakeStateEntry(bad, 'unreachable', NOW + 180 * MIN, start)
    expect(ongoingOutageNoticeFor('some-sub-agent', entry, bad, NOW + 180 * MIN)).toBeNull()
    const ok = intakeStateEntry(probe(), 'ok', NOW + 180 * MIN, start)
    expect(ongoingOutageNoticeFor(MAIN_AGENT_ID, ok, probe(), NOW + 180 * MIN)).toBeNull()
  })

  it('the outage-end line says "no usable answer", not "could not reach"', () => {
    const text = formatUnreachableRecovered(MAIN_AGENT_ID, 40 * MIN, NOW)
    expect(text).toContain('nem kapott használható választ a Telegramtól')
    expect(text).not.toContain('nem érte el')
  })
})

describe('applyIntakeProbe: the mid-outage line at its call site', () => {
  const MIN = 60 * 1000
  const bad = parseIntakeProbe(502, { ok: false, error_code: 502, description: 'Bad Gateway' })
  beforeEach(() => resetIntakeObservations())

  it('sends outage-ongoing from 2 hours on (the sender applies the 3 h cooldown), then one outage-end line', () => {
    const sent: { key: string, at: number, cooldownMs: number }[] = []
    let at = 0
    const send = (key: string, _t: string, o: { cooldownMs: number }) => { sent.push({ key, at, cooldownMs: o.cooldownMs }) }
    for (let m = 0; m <= 130; m += 5) { at = m; applyIntakeProbe(MAIN_AGENT_ID, bad, null, NOW + m * MIN, send) }
    at = 135
    applyIntakeProbe(MAIN_AGENT_ID, probe(), null, NOW + 135 * MIN, send)
    const ongoing = sent.filter(x => x.key.endsWith(':outage-ongoing'))
    expect(ongoing.map(x => x.at)).toEqual([120, 125, 130])
    expect(ongoing.every(x => x.cooldownMs === INTAKE_ALERT_COOLDOWN_MS)).toBe(true)
    expect(sent.filter(x => x.key.endsWith(':unreachable-recovered')).map(x => x.at)).toEqual([135])
    expect(sent).toHaveLength(4)
  })

  it('NEGATIVE: a sub-agent behind a 3-hour Telegram-side outage sends nothing (M15)', () => {
    const sent: string[] = []
    for (let m = 0; m <= 180; m += 5) applyIntakeProbe('some-sub-agent', bad, null, NOW + m * MIN, (k) => { sent.push(k) })
    applyIntakeProbe('some-sub-agent', probe(), null, NOW + 185 * MIN, (k) => { sent.push(k) })
    expect(sent).toEqual([])
  })

  it('NEGATIVE: a 3-hour network outage sends no mid-outage line', () => {
    const sent: string[] = []
    for (let m = 0; m <= 180; m += 5) applyIntakeProbe(MAIN_AGENT_ID, parseIntakeProbe(0, null), null, NOW + m * MIN, (k) => { sent.push(k) })
    expect(sent).toEqual([])
  })

  it('NEGATIVE: the state snapshot is a copy, not the live map (W26)', () => {
    applyIntakeProbe(MAIN_AGENT_ID, probe(), null, NOW, () => {})
    const snap = intakeStateSnapshot()
    snap.delete(MAIN_AGENT_ID)
    expect(intakeStateSnapshot().has(MAIN_AGENT_ID)).toBe(true)
  })
})
