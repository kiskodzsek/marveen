import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { mkdirSync, mkdtempSync, rmSync, utimesSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import {
  projectsDirFor,
  readContextTokensFromProjectDir,
  resetTranscriptScansForTests,
} from '../web/active-model.js'

// Card 3bbf80ca (measured 2026-11-03 on pulzus): an old transcript's mtime moved with no line appended, the guard
// took it for the live session, read 219 338 tokens (73% of a 300k limit) against a live ~75k, and restarted the
// idle agent every hour. The context reader must follow the newest CONVERSATION, not the newest mtime.

const WORKDIR = '/w/agents/probe'
let root: string
let dir: string

const usageLine = (ts: string | null, tokens: number) =>
  JSON.stringify({
    type: 'assistant',
    ...(ts ? { timestamp: ts } : {}),
    message: { role: 'assistant', model: 'claude-sonnet-5-5', usage: { input_tokens: 10, cache_read_input_tokens: tokens - 10, cache_creation_input_tokens: 0 } },
  })
const userLine = (ts: string) => JSON.stringify({ type: 'user', timestamp: ts, message: { role: 'user', content: 'hi' } })
const bookkeeping = [
  JSON.stringify({ type: 'last-prompt', lastPrompt: 'x' }),
  JSON.stringify({ type: 'cost-state', totalCostUSD: 1 }),
]

function transcript(name: string, lines: string[], mtimeIso: string): void {
  const file = join(dir, `${name}.jsonl`)
  writeFileSync(file, lines.join('\n') + '\n')
  const t = new Date(mtimeIso)
  utimesSync(file, t, t)
}

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), 'live-transcript-'))
  dir = projectsDirFor(WORKDIR, root)
  mkdirSync(dir, { recursive: true })
  resetTranscriptScansForTests()
})
afterEach(() => rmSync(root, { recursive: true, force: true }))

describe('readContextTokensFromProjectDir follows the live session, not the newest mtime', () => {
  it('an old heavy transcript touched after the live one does not count (the pulzus case)', () => {
    transcript('old-heavy', [userLine('2026-11-02T14:05:05.172Z'), usageLine('2026-11-02T14:05:56.624Z', 219_338), ...bookkeeping], '2026-11-03T06:42:00Z')
    transcript('live', [userLine('2026-11-03T05:46:36.000Z'), usageLine('2026-11-03T05:47:10.000Z', 75_000)], '2026-11-03T05:47:10Z')
    expect(readContextTokensFromProjectDir(WORKDIR, root)).toBe(75_000)
  })

  it('a fresh session with no usage yet answers null, not the heavy session it replaced', () => {
    transcript('old-heavy', [userLine('2026-11-03T06:40:00.000Z'), usageLine('2026-11-03T06:45:00.000Z', 219_338)], '2026-11-03T06:46:00Z')
    transcript('fresh', [userLine('2026-11-03T06:46:40.000Z')], '2026-11-03T06:46:40Z')
    expect(readContextTokensFromProjectDir(WORKDIR, root)).toBeNull()
  })

  it('a fresh session with only bookkeeping lines (no conversation yet) ranks by its mtime and still wins', () => {
    transcript('old-heavy', [userLine('2026-11-03T06:40:00.000Z'), usageLine('2026-11-03T06:45:00.000Z', 219_338)], '2026-11-03T06:46:00Z')
    transcript('fresh', bookkeeping, '2026-11-03T06:46:40Z')
    expect(readContextTokensFromProjectDir(WORKDIR, root)).toBeNull()
  })

  it('the newest transcript by mtime is read when it is also the newest conversation', () => {
    transcript('older', [userLine('2026-11-03T04:00:00.000Z'), usageLine('2026-11-03T04:01:00.000Z', 150_000)], '2026-11-03T04:01:00Z')
    transcript('live', [userLine('2026-11-03T06:00:00.000Z'), usageLine('2026-11-03T06:01:00.000Z', 90_000), ...bookkeeping], '2026-11-03T06:30:00Z')
    expect(readContextTokensFromProjectDir(WORKDIR, root)).toBe(90_000)
  })

  it('transcripts without timestamps keep the old newest-mtime choice', () => {
    transcript('a', [usageLine(null, 120_000)], '2026-11-03T04:00:00Z')
    transcript('b', [usageLine(null, 60_000)], '2026-11-03T05:00:00Z')
    expect(readContextTokensFromProjectDir(WORKDIR, root)).toBe(60_000)
  })
})
