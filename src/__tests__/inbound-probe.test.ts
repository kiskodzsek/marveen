import { describe, it, expect, afterEach } from 'vitest'
import { mkdtempSync, writeFileSync, mkdirSync, rmdirSync, rmSync, statSync, utimesSync, chmodSync } from 'node:fs'
import { tmpdir, homedir } from 'node:os'
import { join } from 'node:path'
import { shouldTriggerDeafnessRespawn, readLastIngestionTimestamp, readLastIngestionTimestampAcross, inboundChannelLineTs, INGESTION_READ_DEFAULTS, INGESTION_FUTURE_SKEW_MS, mainTranscriptDirs, mainConfigRoots, TRANSCRIPT_DIR } from '../web/inbound-probe.js'
import { projectsDirFor } from '../web/active-model.js'
import { PROJECT_ROOT } from '../config.js'

// ---------------------------------------------------------------------------
// AC coverage map (channel-watchdog-prompt.md D3 + wolf-swarm-trial.md #3)
//
//   AC-D3-1: shouldTriggerDeafnessRespawn — exact probeTimeoutMs boundary
//   AC-D3-2: readLastIngestionTimestamp — large file (>256KB): an inbound line
//            near the END of the file is found
//   AC-D3-3: readLastIngestionTimestamp — large file (>256KB): an inbound line
//            that lives ONLY in the first 10KB is found too (card 194e7ada: the
//            reader walks backward under a byte budget, no fixed tail window)
// ---------------------------------------------------------------------------

// Real transcript line shapes (measured 2026-11-14 on the main agent's
// transcripts, card 194e7ada). Only inboundLine and enqueueLine are ingestions.
const CHANNEL = '<channel source="plugin:telegram:telegram" chat_id="1" user="u">hi</channel>'
const inboundLine = (ts: string, text = 'hello') =>
  JSON.stringify({ type: 'user', timestamp: ts, message: { role: 'user', content: CHANNEL.replace('hi', text) } })
const enqueueLine = (ts: string) =>
  JSON.stringify({ type: 'queue-operation', operation: 'enqueue', timestamp: ts, sessionId: 's', content: CHANNEL })
const mcpDeltaLine = (ts: string) =>
  JSON.stringify({ type: 'attachment', timestamp: ts, attachment: { type: 'mcp_instructions_delta', addedNames: ['telegram'], addedBlocks: ['Messages arrive as <channel source="telegram" chat_id="..."> ...'], removedNames: [] } })
const systemBlobLine = () =>
  JSON.stringify({ type: 'api-request-blob', message: { role: 'system', content: [{ type: 'text', text: 'The sender reads <channel source="telegram"> blocks.' }] } })

// ---------------------------------------------------------------------------
// shouldTriggerDeafnessRespawn
// ---------------------------------------------------------------------------
describe('shouldTriggerDeafnessRespawn', () => {
  const NOW = 1_000_000
  const TIMEOUT = 60_000
  const MARKER = NOW - TIMEOUT // exactly at boundary

  it('returns false when timeout has not elapsed yet', () => {
    expect(shouldTriggerDeafnessRespawn({
      markerTs: NOW - TIMEOUT + 1,
      lastIngestionTs: null,
      probeTimeoutMs: TIMEOUT,
      nowMs: NOW,
    })).toBe(false)
  })

  // AC-D3-1: exact boundary — at nowMs - markerTs === probeTimeoutMs the timeout
  // IS considered elapsed (the condition is `< probeTimeoutMs`, not `<=`). This
  // pins the off-by-one: 1 ms before the boundary → false; at boundary → true.
  it('returns true at EXACTLY the probeTimeoutMs boundary with no ingestion', () => {
    // nowMs - markerTs === TIMEOUT: the < guard is not triggered
    expect(shouldTriggerDeafnessRespawn({
      markerTs: MARKER,  // MARKER = NOW - TIMEOUT, so nowMs - markerTs = TIMEOUT exactly
      lastIngestionTs: null,
      probeTimeoutMs: TIMEOUT,
      nowMs: NOW,
    })).toBe(true)
  })

  it('returns false 1ms BEFORE the probeTimeoutMs boundary', () => {
    // nowMs - markerTs = TIMEOUT - 1: the < guard IS triggered
    expect(shouldTriggerDeafnessRespawn({
      markerTs: NOW - TIMEOUT + 1,
      lastIngestionTs: null,
      probeTimeoutMs: TIMEOUT,
      nowMs: NOW,
    })).toBe(false)
  })

  it('returns true when timeout elapsed and no ingestion ever', () => {
    expect(shouldTriggerDeafnessRespawn({
      markerTs: MARKER,
      lastIngestionTs: null,
      probeTimeoutMs: TIMEOUT,
      nowMs: NOW,
    })).toBe(true)
  })

  it('returns true when timeout elapsed and last ingestion predates the marker', () => {
    expect(shouldTriggerDeafnessRespawn({
      markerTs: MARKER,
      lastIngestionTs: MARKER - 1,
      probeTimeoutMs: TIMEOUT,
      nowMs: NOW,
    })).toBe(true)
  })

  it('returns false when timeout elapsed but ingestion is AFTER the marker (healthy)', () => {
    expect(shouldTriggerDeafnessRespawn({
      markerTs: MARKER,
      lastIngestionTs: MARKER + 1,
      probeTimeoutMs: TIMEOUT,
      nowMs: NOW,
    })).toBe(false)
  })

  it('returns false when timeout elapsed and ingestion equals the marker timestamp', () => {
    // Equal means the ping itself was the ingestion — treat as healthy.
    expect(shouldTriggerDeafnessRespawn({
      markerTs: MARKER,
      lastIngestionTs: MARKER,
      probeTimeoutMs: TIMEOUT,
      nowMs: NOW,
    })).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// readLastIngestionTimestamp
// ---------------------------------------------------------------------------
describe('readLastIngestionTimestamp', () => {
  const tmpDirs: string[] = []

  afterEach(() => {
    for (const d of tmpDirs) {
      try { rmSync(d, { recursive: true, force: true }) } catch { /* ignore */ }
    }
    tmpDirs.length = 0
  })

  function makeTmpDir(): string {
    const d = mkdtempSync(join(tmpdir(), 'inbound-probe-test-'))
    tmpDirs.push(d)
    return d
  }

  function writeSession(dir: string, name: string, lines: string[], mtime?: string): string {
    const p = join(dir, name)
    writeFileSync(p, lines.join('\n') + '\n', 'utf-8')
    if (mtime) utimesSync(p, new Date(mtime), new Date(mtime))
    return p
  }

  // ~100-byte line with no marker
  const filler = (n: number, ts = '2026-06-01T09:00:00.000Z') =>
    Array.from({ length: n }, () => JSON.stringify({ type: 'assistant', timestamp: ts, message: { role: 'assistant', content: 'x'.repeat(60) } }))

  it('returns null for an empty directory (no JSONL files)', () => {
    const dir = makeTmpDir()
    expect(readLastIngestionTimestamp(dir)).toBe(null)
  })

  it('returns null when no lines contain <channel source=', () => {
    const dir = makeTmpDir()
    writeSession(dir, 'session.jsonl', [
      JSON.stringify({ type: 'user', timestamp: '2026-06-01T10:00:00.000Z', message: { role: 'user', content: 'some message' } }),
      JSON.stringify({ type: 'user', timestamp: '2026-06-01T10:01:00.000Z', message: { role: 'user', content: 'another message' } }),
    ])
    expect(readLastIngestionTimestamp(dir)).toBe(null)
  })

  it('returns the timestamp of the last inbound channel message', () => {
    const dir = makeTmpDir()
    const ts2 = '2026-06-01T10:05:00.000Z'
    writeSession(dir, 'session.jsonl', [
      inboundLine('2026-06-01T10:00:00.000Z', 'hello'),
      JSON.stringify({ type: 'user', timestamp: '2026-06-01T10:03:00.000Z', message: { role: 'user', content: 'no channel here' } }),
      inboundLine(ts2, 'world'),
    ])
    expect(readLastIngestionTimestamp(dir)).toBe(new Date(ts2).getTime())
  })

  it('counts a queue-operation enqueue (the message arrived while busy)', () => {
    const dir = makeTmpDir()
    const ts = '2026-06-01T10:07:00.000Z'
    writeSession(dir, 'session.jsonl', [inboundLine('2026-06-01T10:00:00.000Z'), enqueueLine(ts)])
    expect(readLastIngestionTimestamp(dir)).toBe(new Date(ts).getTime())
  })

  it('skips malformed JSON lines without aborting', () => {
    const dir = makeTmpDir()
    const ts = '2026-06-01T11:00:00.000Z'
    writeSession(dir, 'session.jsonl', [inboundLine(ts, 'ok'), 'this is not json <channel source=telegram>'])
    expect(readLastIngestionTimestamp(dir)).toBe(new Date(ts).getTime())
  })

  it('returns null when the directory does not exist', () => {
    expect(readLastIngestionTimestamp('/tmp/nonexistent-inbound-probe-dir-' + Date.now())).toBe(null)
  })

  // NEGATIVE (card 194e7ada): the marker inside a non-inbound line is not an
  // ingestion. Every real session file starts with an mcp_instructions_delta
  // attachment stamped with the SESSION START time, plus the system prompt blob;
  // before the fix a fresh file under 256 KB returned the start time as inbound.
  it('ignores the mcp_instructions_delta attachment, the system-prompt blob and a queue remove', () => {
    const dir = makeTmpDir()
    writeSession(dir, 'session.jsonl', [
      mcpDeltaLine('2026-06-01T12:00:00.000Z'),
      systemBlobLine(),
      JSON.stringify({ type: 'queue-operation', operation: 'remove', timestamp: '2026-06-01T12:02:00.000Z', content: CHANNEL }),
      JSON.stringify({ type: 'user', timestamp: '2026-06-01T12:03:00.000Z', message: { role: 'user', content: [{ type: 'tool_result', content: CHANNEL }] } }),
      JSON.stringify({ type: 'assistant', timestamp: '2026-06-01T12:04:00.000Z', message: { role: 'assistant', content: CHANNEL } }),
      JSON.stringify({ type: 'user', timestamp: '2026-06-01T12:05:00.000Z', message: { role: 'user', content: 'quoted: ' + CHANNEL } }),
    ])
    expect(readLastIngestionTimestamp(dir)).toBe(null)
  })

  it('a later non-inbound marker line does not shadow an earlier real inbound', () => {
    const dir = makeTmpDir()
    const real = '2026-06-01T11:30:00.000Z'
    writeSession(dir, 'session.jsonl', [inboundLine(real), mcpDeltaLine('2026-06-01T12:00:00.000Z'), systemBlobLine()])
    expect(readLastIngestionTimestamp(dir)).toBe(new Date(real).getTime())
  })

  // AC-D3-2: an inbound line near the END of a >256KB file is found.
  it('finds an inbound line near the END of a >256KB file (AC-D3-2)', () => {
    const dir = makeTmpDir()
    const knownTs = '2026-06-01T15:00:00.000Z'
    writeSession(dir, 'session.jsonl', [...filler(3000), inboundLine(knownTs, 'tail-test')])
    expect(readLastIngestionTimestamp(dir)).toBe(new Date(knownTs).getTime())
  })

  // AC-D3-3 (was a locked known limitation, card 194e7ada): the only inbound
  // line in the first 10 KB of a >256KB file IS found now -- the reader walks
  // backward past the old 256 KB tail window.
  it('finds the only inbound line in the first 10KB of a >256KB file (AC-D3-3)', () => {
    const dir = makeTmpDir()
    const earlyTs = '2026-06-01T08:00:00.000Z'
    writeSession(dir, 'session.jsonl', [inboundLine(earlyTs, 'early-line'), ...filler(3000)])
    expect(readLastIngestionTimestamp(dir)).toBe(new Date(earlyTs).getTime())
  })

  it('a line split across a chunk boundary is read whole', () => {
    const dir = makeTmpDir()
    const ts = '2026-06-01T08:30:00.000Z'
    const lines = [inboundLine(ts, 'z'.repeat(300)), ...filler(5)]
    writeSession(dir, 'session.jsonl', lines)
    // every chunk size from 7 to 97 bytes puts the boundary at a different place in the target line
    for (let chunkBytes = 7; chunkBytes < 100; chunkBytes += 10) {
      expect(readLastIngestionTimestamp(dir, { chunkBytes })).toBe(new Date(ts).getTime())
    }
  })

  it('a line longer than one chunk is read whole', () => {
    const dir = makeTmpDir()
    const ts = '2026-06-01T08:40:00.000Z'
    writeSession(dir, 'session.jsonl', [inboundLine(ts, 'w'.repeat(5000)), ...filler(2)])
    expect(readLastIngestionTimestamp(dir, { chunkBytes: 512 })).toBe(new Date(ts).getTime())
  })

  it('falls back to an older file when the newest has no inbound (a restart opened a new file)', () => {
    const dir = makeTmpDir()
    const ts = '2026-06-01T07:00:00.000Z'
    writeSession(dir, 'old.jsonl', [inboundLine(ts), ...filler(3)], '2026-06-01T07:05:00.000Z')
    writeSession(dir, 'new.jsonl', [mcpDeltaLine('2026-06-01T08:00:00.000Z'), systemBlobLine(), ...filler(3)], '2026-06-01T08:10:00.000Z')
    expect(readLastIngestionTimestamp(dir)).toBe(new Date(ts).getTime())
  })

  it('takes the newest inbound across files, not the first file that has one', () => {
    const dir = makeTmpDir()
    // mtime order is a proxy; a resumed older file can hold the later line
    const later = '2026-06-01T09:30:00.000Z'
    writeSession(dir, 'a.jsonl', [inboundLine('2026-06-01T09:00:00.000Z')], '2026-06-01T09:40:00.000Z')
    writeSession(dir, 'b.jsonl', [inboundLine(later)], '2026-06-01T09:35:00.000Z')
    expect(readLastIngestionTimestamp(dir)).toBe(new Date(later).getTime())
  })

  it('stops at a file whose mtime is older than the match already found', () => {
    const dir = makeTmpDir()
    const ts = '2026-06-01T09:00:00.000Z'
    writeSession(dir, 'new.jsonl', [inboundLine(ts)], '2026-06-01T09:05:00.000Z')
    // an older file can hold no later line; a (corrupt) later stamp in it must not win
    writeSession(dir, 'old.jsonl', [inboundLine('2026-06-01T23:00:00.000Z')], '2026-06-01T08:00:00.000Z')
    expect(readLastIngestionTimestamp(dir)).toBe(new Date(ts).getTime())
  })

  it('honours maxFiles: an inbound only in a file beyond the limit is not read', () => {
    const dir = makeTmpDir()
    writeSession(dir, 'old.jsonl', [inboundLine('2026-06-01T07:00:00.000Z')], '2026-06-01T07:00:00.000Z')
    writeSession(dir, 'mid.jsonl', filler(2), '2026-06-01T08:00:00.000Z')
    writeSession(dir, 'new.jsonl', filler(2), '2026-06-01T09:00:00.000Z')
    expect(readLastIngestionTimestamp(dir, { maxFiles: 2 })).toBe(null)
    expect(readLastIngestionTimestamp(dir, { maxFiles: 3 })).toBe(new Date('2026-06-01T07:00:00.000Z').getTime())
  })

  it('honours maxBytes: the budget is shared across files and bounds the read', () => {
    const dir = makeTmpDir()
    const ts = '2026-06-01T07:00:00.000Z'
    writeSession(dir, 'old.jsonl', [inboundLine(ts)], '2026-06-01T07:00:00.000Z')
    const newer = writeSession(dir, 'new.jsonl', filler(3000), '2026-06-01T09:00:00.000Z')
    const newerSize = statSync(newer).size
    expect(readLastIngestionTimestamp(dir, { maxBytes: newerSize })).toBe(null)
    expect(readLastIngestionTimestamp(dir, { maxBytes: newerSize + 4096 })).toBe(new Date(ts).getTime())
  })

  // Viktor 42177 INFO 1 (c): the max-across rule -- a later-visited file with an OLDER inbound must not win.
  it('an older inbound in a later-visited file does not override a newer one already found', () => {
    const dir = makeTmpDir()
    const newer = '2026-06-01T09:30:00.000Z'
    writeSession(dir, 'a.jsonl', [inboundLine(newer)], '2026-06-01T10:00:00.000Z')
    writeSession(dir, 'b.jsonl', [inboundLine('2026-06-01T09:00:00.000Z')], '2026-06-01T09:40:00.000Z')
    expect(readLastIngestionTimestamp(dir)).toBe(new Date(newer).getTime())
  })

  // INFO 1 (d): only *.jsonl is read -- a newer .bak, .gz or .jsonl.bak with an inbound line is not.
  it('reads only *.jsonl files', () => {
    const dir = makeTmpDir()
    const ts = '2026-06-01T07:00:00.000Z'
    writeSession(dir, 'real.jsonl', [inboundLine(ts)], '2026-06-01T07:00:00.000Z')
    for (const name of ['x.bak', 'x.jsonl.bak', 'x.jsonl.gz', 'x.json']) {
      writeSession(dir, name, [inboundLine('2026-06-01T12:00:00.000Z')], '2026-06-01T12:00:00.000Z')
    }
    expect(readLastIngestionTimestamp(dir)).toBe(new Date(ts).getTime())
  })

  // INFO 1 (f): one unreadable file or a directory named *.jsonl does not lose the others.
  it('skips an unreadable file and a directory named *.jsonl, and still reads the rest', () => {
    const dir = makeTmpDir()
    const ts = '2026-06-01T07:00:00.000Z'
    writeSession(dir, 'ok.jsonl', [inboundLine(ts)], '2026-06-01T07:00:00.000Z')
    const locked = writeSession(dir, 'locked.jsonl', [inboundLine('2026-06-01T11:00:00.000Z')], '2026-06-01T11:00:00.000Z')
    chmodSync(locked, 0o000)
    mkdirSync(join(dir, 'd.jsonl'))
    utimesSync(join(dir, 'd.jsonl'), new Date('2026-06-01T12:00:00.000Z'), new Date('2026-06-01T12:00:00.000Z'))
    try {
      expect(readLastIngestionTimestamp(dir)).toBe(new Date(ts).getTime())
    } finally {
      chmodSync(locked, 0o600)
    }
  })

  // INFO 1 (e): pin the defaults. On 2026-11-14 the main agent's last inbound sat in its 15th newest
  // file, about 23 MB back; a smaller limit keeps every other test green but reads null live.
  it('pins the default limits (the live main dir needs 15 files / ~23 MB; 24 since card 116c95c8)', () => {
    expect(INGESTION_READ_DEFAULTS).toEqual({ maxFiles: 24, maxBytes: 32 * 1024 * 1024, chunkBytes: 256 * 1024 })
    expect(INGESTION_FUTURE_SKEW_MS).toBe(5 * 60 * 1000)
  })

  // card 116c95c8 (Viktor 42177 INFO 5): a line stamped beyond now + skew is skipped, the scan goes on.
  it('skips an inbound line stamped in the future and returns the previous real one', () => {
    const dir = makeTmpDir()
    const now = new Date('2026-06-01T12:00:00.000Z').getTime()
    const real = '2026-06-01T11:00:00.000Z'
    writeSession(dir, 'session.jsonl', [inboundLine(real), inboundLine('2026-06-02T12:00:00.000Z')])
    expect(readLastIngestionTimestamp(dir, { nowMs: now })).toBe(new Date(real).getTime())
  })

  it('accepts a line inside the skew, refuses one just past it', () => {
    const dir = makeTmpDir()
    const now = new Date('2026-06-01T12:00:00.000Z').getTime()
    const inside = new Date(now + INGESTION_FUTURE_SKEW_MS).toISOString()
    const past = new Date(now + INGESTION_FUTURE_SKEW_MS + 1).toISOString()
    writeSession(dir, 'a.jsonl', [inboundLine(inside)])
    expect(readLastIngestionTimestamp(dir, { nowMs: now })).toBe(now + INGESTION_FUTURE_SKEW_MS)
    writeSession(dir, 'a.jsonl', [inboundLine(past)])
    expect(readLastIngestionTimestamp(dir, { nowMs: now })).toBe(null)
  })

  it('a future line in a newer file does not hide the real one in an older file', () => {
    const dir = makeTmpDir()
    const now = new Date('2026-06-01T12:00:00.000Z').getTime()
    const real = '2026-06-01T10:00:00.000Z'
    writeSession(dir, 'old.jsonl', [inboundLine(real)], '2026-06-01T10:05:00.000Z')
    writeSession(dir, 'new.jsonl', [inboundLine('2026-07-01T00:00:00.000Z')], '2026-06-01T11:00:00.000Z')
    expect(readLastIngestionTimestamp(dir, { nowMs: now })).toBe(new Date(real).getTime())
  })

  it('the default budget is bounded (B1: no unbounded synchronous read)', () => {
    expect(INGESTION_READ_DEFAULTS.maxBytes).toBeLessThanOrEqual(32 * 1024 * 1024)
    expect(INGESTION_READ_DEFAULTS.maxFiles).toBeLessThanOrEqual(24)
  })
})

describe('inboundChannelLineTs', () => {
  it('accepts exactly the two inbound shapes', () => {
    const ts = '2026-06-01T10:00:00.000Z'
    expect(inboundChannelLineTs(inboundLine(ts))).toBe(new Date(ts).getTime())
    expect(inboundChannelLineTs(enqueueLine(ts))).toBe(new Date(ts).getTime())
  })

  it('rejects the non-inbound shapes and a bad timestamp', () => {
    expect(inboundChannelLineTs(mcpDeltaLine('2026-06-01T10:00:00.000Z'))).toBe(null)
    expect(inboundChannelLineTs(systemBlobLine())).toBe(null)
    expect(inboundChannelLineTs(JSON.stringify({ type: 'user', timestamp: 'not a date', message: { role: 'user', content: CHANNEL } }))).toBe(null)
    expect(inboundChannelLineTs(JSON.stringify({ type: 'user', message: { role: 'user', content: CHANNEL } }))).toBe(null)
    expect(inboundChannelLineTs(JSON.stringify({ type: 'user', timestamp: '2026-06-01T10:00:00.000Z', message: null }))).toBe(null)
    // Viktor 42177 INFO 1 (a): the enqueue branch also needs the marker at the START
    expect(inboundChannelLineTs(JSON.stringify({ type: 'queue-operation', operation: 'enqueue', timestamp: '2026-06-01T10:00:00.000Z', content: 'x ' + CHANNEL }))).toBe(null)
    expect(inboundChannelLineTs(JSON.stringify({ type: 'queue-operation', operation: 'enqueue', timestamp: '2026-06-01T10:00:00.000Z', content: ' ' + CHANNEL }))).toBe(null)
    // INFO 1 (b): a numeric timestamp is refused (the transcript writes ISO strings)
    expect(inboundChannelLineTs(JSON.stringify({ type: 'user', timestamp: 1780000000000, message: { role: 'user', content: CHANNEL } }))).toBe(null)
    expect(inboundChannelLineTs(JSON.stringify({ type: 'queue-operation', operation: 'enqueue', timestamp: 1780000000000, content: CHANNEL }))).toBe(null)
    expect(inboundChannelLineTs('null')).toBe(null)
    expect(inboundChannelLineTs('{')).toBe(null)
  })
})

// ---------------------------------------------------------------------------
// CONFIG-DIR BLIND SPOT regression (2026-09-11)
//
// The main channels agent can run with an isolated CLAUDE_CONFIG_DIR
// (MAIN_AGENT_ISOLATED_CONFIG=1 -> <PROJECT_ROOT>/.channels-config), which puts
// its transcript under THAT root instead of the shared ~/.claude. Reading only
// the shared root reported "no inbound ever" while the owner was actively
// chatting: the keepalive file was never warmed from live traffic, aged past the
// 18-minute staleness threshold, and the watchdog respawn-paned the running
// conversation away (twice in 30 minutes, "124 perce nem frissult").
//
//   AC-CFG-1: mainTranscriptDirs() offers BOTH the shared and the isolated root
//   AC-CFG-2: readLastIngestionTimestampAcross() takes the NEWEST across roots,
//             so the isolated root wins when the shared one is stale
//   AC-CFG-3: a non-existent candidate root is ignored, not fatal
// ---------------------------------------------------------------------------
describe('transcript roots across config dirs', () => {
  const tmpDirs: string[] = []

  afterEach(() => {
    for (const d of tmpDirs) {
      try { rmSync(d, { recursive: true, force: true }) } catch { /* ignore */ }
    }
    tmpDirs.length = 0
  })

  function makeTmpDir(): string {
    const d = mkdtempSync(join(tmpdir(), 'inbound-probe-roots-'))
    tmpDirs.push(d)
    return d
  }

  function writeIngestion(dir: string, ts: string): void {
    writeFileSync(
      join(dir, 'session.jsonl'),
      inboundLine(ts),
      'utf-8',
    )
  }

  // AC-CFG-1
  it('mainTranscriptDirs offers both the shared and the isolated config root', () => {
    const dirs = mainTranscriptDirs()
    expect(dirs.length).toBeGreaterThanOrEqual(2)
    expect(dirs.some(d => d.includes(join('.claude', 'projects')))).toBe(true)
    expect(dirs.some(d => d.includes(join('.channels-config', 'projects')))).toBe(true)
    // no duplicates — the candidates are de-duplicated
    expect(new Set(dirs).size).toBe(dirs.length)
  })

  // AC-CFG-2: this is the actual bug. The shared root holds an old transcript
  // (from before isolation was turned on) and the isolated root holds the live
  // one. Reading the shared root alone returns the STALE timestamp and the
  // keepalive never gets warmed.
  it('takes the newest ingestion across roots when the live one is isolated', () => {
    const shared = makeTmpDir()
    const isolated = makeTmpDir()
    const stale = '2026-09-11T18:36:00.000Z'
    const live = '2026-09-11T20:41:00.000Z'
    writeIngestion(shared, stale)
    writeIngestion(isolated, live)

    expect(readLastIngestionTimestamp(shared)).toBe(new Date(stale).getTime())
    expect(readLastIngestionTimestampAcross([shared, isolated])).toBe(new Date(live).getTime())
  })

  it('never moves backward: an older isolated root does not beat a live shared one', () => {
    const shared = makeTmpDir()
    const isolated = makeTmpDir()
    const live = '2026-09-11T20:41:00.000Z'
    writeIngestion(shared, live)
    writeIngestion(isolated, '2026-09-11T18:36:00.000Z')
    expect(readLastIngestionTimestampAcross([shared, isolated])).toBe(new Date(live).getTime())
  })

  // AC-CFG-3
  it('ignores candidate roots that do not exist', () => {
    const real = makeTmpDir()
    const ts = '2026-09-11T20:41:00.000Z'
    writeIngestion(real, ts)
    const missing = '/tmp/nonexistent-inbound-probe-root-' + Date.now()
    expect(readLastIngestionTimestampAcross([missing, real])).toBe(new Date(ts).getTime())
  })

  it('returns null when no candidate root has an ingestion', () => {
    expect(readLastIngestionTimestampAcross([makeTmpDir(), makeTmpDir()])).toBe(null)
  })
})

// ---------------------------------------------------------------------------
// PROJECT-DIR ENCODING regression (866da985, 2026-09-20)
//
// Claude Code encodes a project working-dir by replacing EVERY character
// that is not alphanumeric with '-' (see projectsDirFor in active-model.ts,
// already relied on by schedule-runner and the context-guard/restart-gate
// watchdogs) -- not just '/'. TRANSCRIPT_DIR and mainTranscriptDirs() used to
// hand-roll their own PROJECT_ROOT.replace(/\//g, '-'), which only strips
// slashes. On any host whose PROJECT_ROOT contains another separator
// character that Claude Code also encodes (e.g. a dot in the username, as in
// /Users/a.kobza/marveen), the two encoders disagree: the hand-rolled one
// computes a directory Claude Code never creates, so
// readLastIngestionTimestampAcross() always returns null -- real inbound
// traffic never refreshes the keepalive file, and the channel-monitor
// watchdog respawns the session on a ~15 minute metronome forever (measured
// live: 63 respawns in one day, see kanban 866da985).
//
//   AC-ENC-1: TRANSCRIPT_DIR must match projectsDirFor's encoding exactly
//   AC-ENC-2: every mainTranscriptDirs() candidate must match projectsDirFor
//             for its corresponding config root
// ---------------------------------------------------------------------------
describe('project-dir encoding matches Claude Code (866da985)', () => {
  // AC-ENC-1
  it('TRANSCRIPT_DIR encodes PROJECT_ROOT the same way projectsDirFor does', () => {
    const expected = projectsDirFor(PROJECT_ROOT, join(process.env.HOME ?? homedir(), '.claude'))
    expect(TRANSCRIPT_DIR).toBe(expected)
  })

  // AC-ENC-2
  it('every mainTranscriptDirs() candidate matches projectsDirFor for its config root', () => {
    const dirs = mainTranscriptDirs()
    const roots = mainConfigRoots()
    for (const root of roots) {
      expect(dirs).toContain(projectsDirFor(PROJECT_ROOT, root))
    }
  })
})
