import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

// card 116c95c8 (Viktor 42177 INFO 1 f, 42180 INFO 1): the fd close and the short-read guard of
// readLastIngestionTimestamp, measured through a wrapped node:fs. The dashboard runs for days; a leaked fd
// per call (once a minute, plus once per agent every 5 minutes) would slowly exhaust the descriptor table,
// and a short read (a file truncated under the reader) would splice two lines into one.
const fsState = vi.hoisted(() => ({ opened: 0, closed: 0, shortRead: false, throwOnRead: false }))

vi.mock('node:fs', async (importOriginal) => {
  const real = await importOriginal<typeof import('node:fs')>()
  const wrapped = {
    ...real,
    openSync: ((...args: Parameters<typeof real.openSync>) => { const fd = real.openSync(...args); fsState.opened++; return fd }) as typeof real.openSync,
    closeSync: ((fd: number) => { fsState.closed++; return real.closeSync(fd) }) as typeof real.closeSync,
    readSync: ((fd: number, buf: NodeJS.ArrayBufferView, off: number, len: number, pos: number) => {
      if (fsState.throwOnRead) throw Object.assign(new Error('EIO'), { code: 'EIO' })
      const n = real.readSync(fd, buf, off, len, pos)
      return fsState.shortRead ? Math.max(0, n - 1) : n
    }) as typeof real.readSync,
  }
  return { ...wrapped, default: wrapped }
})

const { mkdtempSync, writeFileSync, rmSync } = await import('node:fs')
const { readLastIngestionTimestamp } = await import('../web/inbound-probe.js')

const CHANNEL = '<channel source="plugin:telegram:telegram" chat_id="1">hi</channel>'
const inboundLine = (ts: string) => JSON.stringify({ type: 'user', timestamp: ts, message: { role: 'user', content: CHANNEL } })
const filler = (n: number) => Array.from({ length: n }, () => JSON.stringify({ type: 'assistant', message: { content: 'x'.repeat(60) } }))

describe('readLastIngestionTimestamp -- fd and short-read guards', () => {
  let dir = ''
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'inbound-probe-fs-'))
    Object.assign(fsState, { opened: 0, closed: 0, shortRead: false, throwOnRead: false })
  })
  afterEach(() => { rmSync(dir, { recursive: true, force: true }) })

  it('closes every fd it opens: found, not found, and a read that throws', () => {
    const ts = '2026-06-01T10:00:00.000Z'
    writeFileSync(join(dir, 'a.jsonl'), [inboundLine(ts), ...filler(50)].join('\n') + '\n')
    writeFileSync(join(dir, 'b.jsonl'), filler(50).join('\n') + '\n')
    for (let i = 0; i < 200; i++) expect(readLastIngestionTimestamp(dir, { chunkBytes: 512 })).toBe(new Date(ts).getTime())
    expect(fsState.opened).toBeGreaterThanOrEqual(200)
    expect(fsState.closed).toBe(fsState.opened)
    fsState.throwOnRead = true
    for (let i = 0; i < 50; i++) expect(readLastIngestionTimestamp(dir)).toBe(null)
    expect(fsState.closed).toBe(fsState.opened)
  })

  it('a short read gives up on the file instead of splicing lines', () => {
    // The only inbound line sits before a chunk boundary; with every read one byte short, a reader without the
    // guard would join the tail of one chunk to the head of the next. The guard returns null for the file.
    writeFileSync(join(dir, 'a.jsonl'), [inboundLine('2026-06-01T10:00:00.000Z'), ...filler(50)].join('\n') + '\n')
    fsState.shortRead = true
    expect(readLastIngestionTimestamp(dir, { chunkBytes: 512 })).toBe(null)
    expect(fsState.closed).toBe(fsState.opened)
    fsState.shortRead = false
    expect(readLastIngestionTimestamp(dir, { chunkBytes: 512 })).toBe(new Date('2026-06-01T10:00:00.000Z').getTime())
  })
})
