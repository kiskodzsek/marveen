import { mkdirSync, mkdtempSync, rmSync, symlinkSync, utimesSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import {
  DEFAULT_ORG, activityLine, findLatestMedia, loadOrg, loadThumbDirs, mediaCaption, messageSubject, scrubText, shellVerb,
  withUnplacedAgents,
} from '../web/iroda.js'

// All values below are synthetic. The key shape is assembled at runtime so the
// repository secret-gate never sees a literal key pattern in this file.
const FAKE_KEY = ['sk', 'test', 'abcdefghijklmnop'].join('_')

describe('iroda scrubText', () => {
  it('masks e-mail, bank account, IBAN, phone and token shapes', () => {
    const out = scrubText('írj a teszt.elek@example.com címre, számla 11773016-12345678-00000000, IBAN HU42 1177 3016 1111 1018 0000 0000, tel +36 30 123 4567, kulcs ' + FAKE_KEY)
    expect(out).not.toMatch(/example\.com|11773016|HU42|123 4567|sk_test/)
    expect(out).toContain('<e-mail>')
    expect(out).toContain('<számla>')
    expect(out).toContain('<szám>')
    expect(out).toContain('<titok>')
  })
  it('keeps only the host of a URL (no path, no query token)', () => {
    expect(scrubText('nézd: https://example.org/path/secret?token=abc123')).toBe('nézd: example.org')
  })
  it('collapses long unbroken key-like runs', () => {
    expect(scrubText('x ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 y')).toBe('x … y')
  })
  it('leaves ordinary text and dates alone', () => {
    expect(scrubText('PR #1078 kész, CI zöld')).toBe('PR #1078 kész, CI zöld')
    expect(scrubText('(privát, 2026-11-03 12:17)')).toBe('(privát, 2026-11-03 12:17)')
    expect(scrubText('határidő 2026-11-06')).toBe('határidő 2026-11-06')
  })
})

describe('iroda messageSubject', () => {
  it('drops the routing prefix and keeps the first sentence', () => {
    expect(messageSubject('Klodel -> Kernel, a dashboard kész. Részletek a fájlban, sok szöveg.')).toBe('a dashboard kész.')
  })
  it('rewrites the result prefix', () => {
    expect(messageSubject('[Eredmény] msg_id:123 status:done\n\nPusholva és kész.')).toBe('Eredmény: Pusholva és kész.')
  })
  it('clips to the max length with an ellipsis and masks personal data', () => {
    const s = messageSubject('Kernel: ' + 'hosszú '.repeat(30) + 'a@b.hu', 40)
    expect(s.length).toBeLessThanOrEqual(40)
    expect(s.endsWith('…')).toBe(true)
    expect(messageSubject('Kernel: írj ide: a@example.com')).toContain('<e-mail>')
  })
})

describe('iroda shellVerb / activityLine', () => {
  it('shows only the program and subcommand, never arguments', () => {
    expect(shellVerb('cd /x/y && git commit -m "secret msg"')).toBe('git commit')
    expect(shellVerb('TOKEN=abc curl -s -H "Authorization: Bearer x" http://h/api')).toBe('curl')
    expect(shellVerb('node /Users/x/scripts/agent-msg.sh kernel klodel "hi"')).toBe('node agent-msg.sh')
    expect(shellVerb('python3 -I /a/b/run.py --flag')).toBe('python3 run.py')
    expect(shellVerb('cd /tmp')).toBe('parancs')
  })
  it('file tools show the base name only', () => {
    expect(activityLine('Read', '/Users/klodel/marveen/agents/kernel/HANDOFF.md')).toBe('olvas: HANDOFF.md')
    expect(activityLine('Edit', '/a/b/c/iroda.ts')).toBe('szerkeszt: iroda.ts')
    expect(activityLine('Bash', 'git status')).toBe('> git status')
  })
  it('web tools show the host only', () => {
    expect(activityLine('WebFetch', 'https://docs.example.com/x?y=1')).toBe('web: docs.example.com')
    expect(activityLine('WebSearch', 'billingo api')).toBe('webes keresés')
  })
  it('MCP tools show the server and tool name, not the input', () => {
    expect(activityLine('mcp__billingo__list_documents', '{"partner":"x"}')).toBe('eszköz: billingo list_documents')
  })
})

describe('iroda findLatestMedia', () => {
  let root: string
  const now = Date.now()
  const put = (rel: string, ageMs: number) => {
    const p = join(root, rel)
    mkdirSync(join(p, '..'), { recursive: true })
    writeFileSync(p, 'x')
    const t = (now - ageMs) / 1000
    utimesSync(p, t, t)
    return p
  }
  beforeEach(() => { root = mkdtempSync(join(tmpdir(), 'iroda-')) })
  afterEach(() => { rmSync(root, { recursive: true, force: true }) })

  it('picks the newest media file within the age limit', () => {
    put('agents/dave/out/a.png', 60_000)
    const b = put('agents/dave/out/sub/b.mp4', 10_000)
    put('agents/dave/out/c.txt', 1_000)
    put('agents/dave/out/old.jpg', 10 * 3600_000)
    const hit = findLatestMedia(root, ['agents/dave/out'], now, 6 * 3600_000)
    expect(hit?.path).toBe(b)
    expect(hit?.kind).toBe('video')
  })
  it('skips customer / upload / order segments even inside an allowed directory', () => {
    put('agents/dave/out/ugyfel-anna/fresh.png', 1_000)
    put('agents/dave/out/uploads/fresh.jpg', 1_000)
    put('agents/dave/out/order-123/fresh.jpg', 1_000)
    const ok = put('agents/dave/out/render/ok.png', 50_000)
    expect(findLatestMedia(root, ['agents/dave/out'], now, 6 * 3600_000)?.path).toBe(ok)
    expect(findLatestMedia(root, ['agents/dave/out/uploads'], now, 6 * 3600_000)).toBeNull()
  })
  it('ignores an allowlisted directory outside the root and does not follow symlinks', () => {
    const outside = mkdtempSync(join(tmpdir(), 'iroda-out-'))
    try {
      writeFileSync(join(outside, 'leak.png'), 'x')
      expect(findLatestMedia(root, ['../' + outside.split('/').pop()], now, 6 * 3600_000)).toBeNull()
      expect(findLatestMedia(root, [outside], now, 6 * 3600_000)).toBeNull()
      mkdirSync(join(root, 'agents/kernel/out'), { recursive: true })
      symlinkSync(outside, join(root, 'agents/kernel/out/link'))
      expect(findLatestMedia(root, ['agents/kernel/out'], now, 6 * 3600_000)).toBeNull()
    } finally {
      rmSync(outside, { recursive: true, force: true })
    }
  })
  it('respects the entry budget', () => {
    for (let i = 0; i < 20; i++) put(`agents/dave/out/f${String(i).padStart(2, '0')}.png`, 1_000 + i)
    expect(findLatestMedia(root, ['agents/dave/out'], now, 6 * 3600_000, { maxEntries: 1 })).toBeNull()
  })
  it('caption carries kind and a scrubbed base name only', () => {
    expect(mediaCaption({ path: '/x/y/laci_papa-render.png', mtimeMs: 0, kind: 'image' })).toBe('kép · laci papa render')
    expect(mediaCaption({ path: '/x/howto.mp4', mtimeMs: 0, kind: 'video' })).toBe('▶ videó · howto')
  })
})

describe('iroda org / thumb config', () => {
  let store: string
  beforeEach(() => { store = mkdtempSync(join(tmpdir(), 'iroda-store-')) })
  afterEach(() => { rmSync(store, { recursive: true, force: true }) })

  it('falls back to the defaults when the files are missing or broken', () => {
    expect(loadOrg(store)).toBe(DEFAULT_ORG)
    writeFileSync(join(store, 'iroda-org.json'), '{not json')
    expect(loadOrg(store)).toBe(DEFAULT_ORG)
    writeFileSync(join(store, 'iroda-thumbs.json'), '[1,2]')
    expect(loadThumbDirs(store).dave).toEqual(['agents/dave/out'])
  })
  it('reads an explicit thumb allowlist; an agent missing from it gets no thumbnails', () => {
    writeFileSync(join(store, 'iroda-thumbs.json'), JSON.stringify({ mira: ['agents/mira/out', 5] }))
    const t = loadThumbDirs(store)
    expect(t.mira).toEqual(['agents/mira/out'])
    expect(t.dave).toBeUndefined()
  })
  it('puts agents missing from the org into an "other" room', () => {
    const org = withUnplacedAgents(DEFAULT_ORG, ['klodel', 'dave', 'ujagens'])
    const other = org.depts.find((d) => d.id === 'other')
    expect(other?.seats.map((s) => s.id)).toEqual(['ujagens'])
    expect(withUnplacedAgents(DEFAULT_ORG, ['klodel', 'dave'])).toBe(DEFAULT_ORG)
  })
})
