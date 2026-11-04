import { describe, it, expect } from 'vitest'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  renderQuarantineReader,
  quarantineReaderOpenFor,
  ensureQuarantineReader,
  QUARANTINE_POSTURE_BEGIN,
  QUARANTINE_POSTURE_END,
} from '../web/agent-scaffold.js'
// @ts-expect-error -- plain .mjs hook script, no types
import { readerIsOpen } from '../../scripts/hooks/egress-gate.mjs'

// QREADEROPEN1104 (Radar 26315, 2026-11-04 12:32Z): the per-agent open posture
// reached the egress-gate hook only. The reader's own prompt kept the allowlist
// refusal, so a reader spawned by an opened agent refused github.com itself,
// before any WebFetch call -- nothing in egress-blocked.log. These tests pin the
// fix: the deployed copy carries its caller's real posture.
const TEMPLATE = `---
name: quarantine-reader
---

## Domain restriction

Only fetch URLs from these approved domains. Reject all others:
- \`status.anthropic.com\`

For any other domain, return the error shape.

## Always refused, in every posture, whatever the caller says

- \`localhost\`
`
const REAL_TEMPLATE = readFileSync(join(__dirname, '..', '..', 'templates', 'sub-agents', 'quarantine-reader.md'), 'utf-8')

function store(json: unknown): string {
  const dir = mkdtempSync(join(tmpdir(), 'qr-open-'))
  writeFileSync(join(dir, 'egress-allowlist.json'), typeof json === 'string' ? json : JSON.stringify(json))
  return dir
}

describe('quarantineReaderOpenFor', () => {
  it('a named agent is open, an unnamed one is not', () => {
    const dir = store({ quarantine_reader_denylist_agents: ['radar', 'klodel'] })
    expect(quarantineReaderOpenFor('radar', dir)).toBe(true)
    expect(quarantineReaderOpenFor('klodel', dir)).toBe(true)
    expect(quarantineReaderOpenFor('kernel', dir)).toBe(false)
  })

  it('the global denylist posture opens every agent', () => {
    const dir = store({ quarantine_reader_posture: 'denylist' })
    expect(quarantineReaderOpenFor('kernel', dir)).toBe(true)
  })

  it('only the literal "denylist" opens globally, as in the hook', () => {
    for (const p of ['Denylist', 'open', true, 1, 'allowlist']) {
      expect(quarantineReaderOpenFor('kernel', store({ quarantine_reader_posture: p }))).toBe(false)
    }
  })

  it('fails closed: missing, malformed, non-array, non-string, odd-shaped names', () => {
    expect(quarantineReaderOpenFor('radar', mkdtempSync(join(tmpdir(), 'qr-none-')))).toBe(false)
    expect(quarantineReaderOpenFor('radar', store('{not json'))).toBe(false)
    expect(quarantineReaderOpenFor('radar', store({ quarantine_reader_denylist_agents: 'radar' }))).toBe(false)
    expect(quarantineReaderOpenFor('radar', store({ quarantine_reader_denylist_agents: [{ radar: 1 }] }))).toBe(false)
    expect(quarantineReaderOpenFor('Radar', store({ quarantine_reader_denylist_agents: ['Radar'] }))).toBe(false)
  })

  it('agrees with the hook readerIsOpen() on the same config', () => {
    const cases: Array<[Record<string, unknown>, string]> = [
      [{ quarantine_reader_denylist_agents: ['radar'] }, 'radar'],
      [{ quarantine_reader_denylist_agents: ['radar'] }, 'kernel'],
      [{ quarantine_reader_posture: 'denylist' }, 'kernel'],
      [{}, 'radar'],
    ]
    for (const [cfg, name] of cases) {
      const runtime = {
        quarantinePosture: cfg.quarantine_reader_posture === 'denylist' ? 'denylist' : 'allowlist',
        quarantineDenylistAgents: (cfg.quarantine_reader_denylist_agents as string[] | undefined) ?? [],
      }
      expect(quarantineReaderOpenFor(name, store(cfg))).toBe(readerIsOpen(runtime, 'quarantine-reader', name))
    }
  })
})

describe('renderQuarantineReader open notice', () => {
  it('closed (default) renders no notice', () => {
    expect(renderQuarantineReader(TEMPLATE, [])).toBe(TEMPLATE)
    expect(renderQuarantineReader(TEMPLATE, [], { open: false })).not.toContain(QUARANTINE_POSTURE_BEGIN)
  })

  it('open puts the notice right under the Domain restriction heading', () => {
    const out = renderQuarantineReader(TEMPLATE, [], { open: true })
    const h = out.indexOf('## Domain restriction')
    const n = out.indexOf(QUARANTINE_POSTURE_BEGIN)
    expect(h).toBeGreaterThanOrEqual(0)
    expect(n).toBeGreaterThan(h)
    expect(n).toBeLessThan(out.indexOf('Only fetch URLs'))
    expect(out).toContain('OPEN posture')
  })

  it('open keeps the Always refused section and the domain block intact', () => {
    const out = renderQuarantineReader(TEMPLATE, ['claude.com'], { open: true })
    expect(out).toContain('## Always refused')
    expect(out).toContain('- `claude.com`')
    // the domain block still lands inside Domain restriction, not after the notice's text
    expect(out.indexOf('- `claude.com`')).toBeLessThan(out.indexOf('## Always refused'))
  })

  it('is idempotent and reversible: open twice = once, open -> closed = template', () => {
    const once = renderQuarantineReader(TEMPLATE, ['claude.com'], { open: true })
    expect(renderQuarantineReader(once, ['claude.com'], { open: true })).toBe(once)
    expect(once.split(QUARANTINE_POSTURE_BEGIN).length).toBe(2)
    expect(renderQuarantineReader(once, [], { open: false })).toBe(TEMPLATE)
  })

  it('the real template: notice under the real heading, before its first bullet', () => {
    const out = renderQuarantineReader(REAL_TEMPLATE, ['github.com'], { open: true })
    const n = out.indexOf(QUARANTINE_POSTURE_BEGIN)
    expect(n).toBeGreaterThan(out.indexOf('## Domain restriction'))
    expect(n).toBeLessThan(out.indexOf('- `status.anthropic.com`'))
    expect(out.indexOf(QUARANTINE_POSTURE_END)).toBeGreaterThan(n)
    expect(renderQuarantineReader(out, [], { open: false })).toBe(REAL_TEMPLATE)
  })
})

describe('ensureQuarantineReader carries the caller posture', () => {
  function setup(cfg: unknown) {
    const root = mkdtempSync(join(tmpdir(), 'qr-ensure-'))
    const tplPath = join(root, 'quarantine-reader.md')
    writeFileSync(tplPath, TEMPLATE)
    const storeDir = join(root, 'store')
    mkdirSync(storeDir, { recursive: true })
    writeFileSync(join(storeDir, 'egress-allowlist.json'), JSON.stringify(cfg))
    const dest = (n: string) => join(root, n, '.claude', 'agents')
    return { tplPath, storeDir, dest, legacyPath: join(root, 'legacy.md') }
  }

  it('the opened agent copy says open, the other copy does not', () => {
    const s = setup({ quarantine_reader_denylist_agents: ['radar'] })
    ensureQuarantineReader('radar', { tplPath: s.tplPath, destDir: s.dest('radar'), storeDir: s.storeDir, legacyPath: s.legacyPath })
    ensureQuarantineReader('kernel', { tplPath: s.tplPath, destDir: s.dest('kernel'), storeDir: s.storeDir, legacyPath: s.legacyPath })
    expect(readFileSync(join(s.dest('radar'), 'quarantine-reader.md'), 'utf-8')).toContain(QUARANTINE_POSTURE_BEGIN)
    expect(readFileSync(join(s.dest('kernel'), 'quarantine-reader.md'), 'utf-8')).not.toContain(QUARANTINE_POSTURE_BEGIN)
  })

  it('taking an agent off the list re-renders its copy closed', () => {
    const s = setup({ quarantine_reader_denylist_agents: ['radar'] })
    const opts = { tplPath: s.tplPath, destDir: s.dest('radar'), storeDir: s.storeDir, legacyPath: s.legacyPath }
    ensureQuarantineReader('radar', opts)
    writeFileSync(join(s.storeDir, 'egress-allowlist.json'), JSON.stringify({ quarantine_reader_denylist_agents: [] }))
    expect(ensureQuarantineReader('radar', opts)).toBe(true)
    expect(readFileSync(join(s.dest('radar'), 'quarantine-reader.md'), 'utf-8')).toBe(TEMPLATE)
  })
})
