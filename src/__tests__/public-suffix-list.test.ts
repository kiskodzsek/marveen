// The vendored Public Suffix List (Viktor 13122 L2, 13207): the generator, the
// committed file, the hook's loader and the scaffold's mirror of it, and the
// two failure modes (reader tier fails closed, main tier keeps the hand list).
import { describe, it, expect, afterEach } from 'vitest'
import { mkdtempSync, writeFileSync, readFileSync, rmSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  buildPublicSuffixIndex as scaffoldBuild, loadPublicSuffixIndex, opensPublicSuffix as scaffoldOpens,
  PSL_MIN_RULES as SCAFFOLD_MIN, PUBLIC_SUFFIX_LIST_PATH, quarantineReaderDomains,
} from '../web/agent-scaffold.js'
// @ts-expect-error -- plain .mjs hook module, no type declarations
import * as hook from '../../scripts/hooks/egress-gate.mjs'
// @ts-expect-error -- plain .mjs script, no type declarations
import { parsePublicSuffixList, buildDocument, diffRules, gitBlobId, readLicenseNotice } from '../../scripts/gen-public-suffix-list.mjs'

const doc = JSON.parse(readFileSync(PUBLIC_SUFFIX_LIST_PATH, 'utf-8'))

// buildPublicSuffixIndex refuses a list below the minimum, so a synthetic
// fixture is padded with filler rules under the reserved .test TLD.
function padded(icann: string[], priv: string[] = []) {
  const fill = (n: number, tag: string) => Array.from({ length: n }, (_, i) => `${tag}${i}.test`)
  return {
    icann: [...icann, ...fill(SCAFFOLD_MIN.icann, 'i')],
    private: [...priv, ...fill(SCAFFOLD_MIN.private, 'p')],
  }
}

function tmp() {
  return mkdtempSync(join(tmpdir(), 'psl-test-'))
}

afterEach(() => {
  hook._resetPublicSuffixIndex()
  delete process.env.HOOK_ERRLOG_PATH
})

describe('committed public-suffix-list.json', () => {
  it('loads in both loaders, above the minimum, with its provenance', () => {
    expect(doc._license).toEqual([
      'This Source Code Form is subject to the terms of the Mozilla Public',
      'License, v. 2.0. If a copy of the MPL was not distributed with this',
      'file, You can obtain one at https://mozilla.org/MPL/2.0/.',
    ])
    expect(doc._license_text).toContain('LICENSES/MPL-2.0.txt')
    expect(doc.source_url).toBe(`https://github.com/publicsuffix/list/blob/${doc.commit}/public_suffix_list.dat`)
    expect(doc.commit).toMatch(/^[0-9a-f]{40}$/)
    expect(doc.blob).toMatch(/^[0-9a-f]{40}$/)
    expect(doc.sha256).toMatch(/^[0-9a-f]{64}$/)
    expect(doc.counts).toEqual({ icann: doc.icann.length, private: doc.private.length })
    expect(doc.icann.length).toBeGreaterThanOrEqual(SCAFFOLD_MIN.icann)
    expect(doc.private.length).toBeGreaterThanOrEqual(SCAFFOLD_MIN.private)
    expect(hook.publicSuffixIndex()).not.toBeNull()
    expect(loadPublicSuffixIndex()).not.toBeNull()
  })

  it('is what the generator makes of itself: sorted, no duplicates', () => {
    for (const k of ['icann', 'private'] as const) {
      expect([...doc[k]].sort()).toEqual(doc[k])
      expect(new Set(doc[k]).size).toBe(doc[k].length)
    }
  })
})

describe('hook and scaffold agree', () => {
  it('same minimum, same index from the committed file', () => {
    expect(SCAFFOLD_MIN).toEqual(hook.PSL_MIN_RULES)
    const a = hook.buildPublicSuffixIndex(doc)
    const b = scaffoldBuild(doc)!
    for (const k of ['suffix', 'wildcard', 'exception', 'parent'] as const) {
      expect([...a[k]].sort()).toEqual([...b[k]].sort())
    }
  })

  it('same verdict on a probe list', () => {
    const idx = hook.publicSuffixIndex()
    const sidx = loadPublicSuffixIndex()
    const probes = ['co.uk', 'com.au', 'r2.dev', 'amazonaws.com', 'myapp.vercel.app', 'docs.stripe.com', 'foo.ck', 'www.ck', 'kawasaki.jp', 'city.kawasaki.jp', 'xn--p1ai', 'github.com']
    for (const p of probes) expect([p, scaffoldOpens(p, sidx)]).toEqual([p, hook.opensPublicSuffix(p, idx)])
  })
})

describe('what the list refuses', () => {
  // Viktor 13122 L2: measured to pass the hand list and open every tenant.
  const MISSED_BY_HAND_LIST = ['s3.eu-central-1.amazonaws.com', 's3-eu-west-1.amazonaws.com', 'r2.dev']
  // Viktor 13207 addendum A: ICANN second-level suffixes, measured to pass.
  const ICANN = ['co.uk', 'com.au']

  it('refuses the measured misses and ICANN suffixes in both tiers', () => {
    for (const d of [...MISSED_BY_HAND_LIST, ...ICANN]) {
      expect([d, hook.isUsableRuntimeDomain(d)]).toEqual([d, false])
      expect([d, hook.isUsableRuntimeDomain(d, 'reader')]).toEqual([d, false])
    }
  })

  it('refuses a parent of a suffix, accepts a single tenant and an ordinary site', () => {
    expect(hook.isUsableRuntimeDomain('amazonaws.com')).toBe(false)
    expect(hook.isUsableRuntimeDomain('myapp.vercel.app', 'reader')).toBe(true)
    expect(hook.isUsableRuntimeDomain('docs.stripe.com', 'reader')).toBe(true)
    expect(hook.isUsableRuntimeDomain('bbc.co.uk', 'reader')).toBe(true)
  })

  it('keeps the hand list for what the PSL lacks', () => {
    expect(hook.opensPublicSuffix('substack.com', hook.publicSuffixIndex())).toBe(false)
    expect(hook.isUsableRuntimeDomain('substack.com')).toBe(false)
  })

  it('a quarantine_domains entry naming co.uk opens no .co.uk site', () => {
    const r = hook.egressDecision('WebFetch', { url: 'https://evil.co.uk/' }, { quarantineDomains: ['co.uk'] }, 'quarantine-reader')
    expect(r.blocked).toBe(true)
  })

  it('wildcard and exception rules, on a synthetic list', () => {
    const idx = hook.buildPublicSuffixIndex(padded(['*.ck', '!www.ck', 'jp', '*.kawasaki.jp', '!city.kawasaki.jp'], ['*.compute.example-cloud.com']))
    expect(hook.opensPublicSuffix('foo.ck', idx)).toBe(true)
    expect(hook.opensPublicSuffix('www.ck', idx)).toBe(false)
    expect(hook.opensPublicSuffix('a.www.ck', idx)).toBe(false)
    expect(hook.opensPublicSuffix('foo.kawasaki.jp', idx)).toBe(true)
    expect(hook.opensPublicSuffix('city.kawasaki.jp', idx)).toBe(false)
    expect(hook.opensPublicSuffix('kawasaki.jp', idx)).toBe(true)        // parent of a wildcard
    expect(hook.opensPublicSuffix('compute.example-cloud.com', idx)).toBe(true)
    expect(hook.opensPublicSuffix('example-cloud.com', idx)).toBe(true)  // parent of a private rule
    expect(hook.opensPublicSuffix('eu.compute.example-cloud.com', idx)).toBe(true)
    expect(hook.opensPublicSuffix('app.eu.compute.example-cloud.com', idx)).toBe(false)
  })

  it('an IDN rule is matched in its ASCII form, the way URL hostnames arrive', () => {
    const idx = hook.buildPublicSuffixIndex(padded(['рф', 'пример.рф']))
    expect(hook.opensPublicSuffix(new URL('https://пример.рф/').hostname, idx)).toBe(true)
    expect(scaffoldOpens(new URL('https://пример.рф/').hostname, scaffoldBuild(padded(['рф', 'пример.рф'])))).toBe(true)
  })
})

describe('an unusable list', () => {
  function brokenCases(dir: string): Record<string, string> {
    const cases: Record<string, string> = {
      missing: join(dir, 'does-not-exist.json'),
      unparseable: join(dir, 'bad.json'),
      truncated: join(dir, 'short.json'),
      wrongType: join(dir, 'type.json'),
    }
    writeFileSync(cases.unparseable, '{"icann": [')
    writeFileSync(cases.truncated, JSON.stringify({ icann: doc.icann.slice(0, 100), private: doc.private }))
    writeFileSync(cases.wrongType, JSON.stringify({ ...padded([]), private: [...padded([]).private, 42] }))
    return cases
  }

  it('is null in both loaders, for every broken shape', () => {
    const dir = tmp()
    try {
      for (const [name, path] of Object.entries(brokenCases(dir))) {
        process.env.HOOK_ERRLOG_PATH = join(dir, 'hook-errors.log')
        hook._resetPublicSuffixIndex(path)
        expect([name, hook.publicSuffixIndex()]).toEqual([name, null])
        expect([name, loadPublicSuffixIndex(path)]).toEqual([name, null])
      }
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('reader tier fails closed, main tier keeps the hand list, and it says so', () => {
    const dir = tmp()
    try {
      const log = join(dir, 'hook-errors.log')
      process.env.HOOK_ERRLOG_PATH = log
      hook._resetPublicSuffixIndex(join(dir, 'does-not-exist.json'))

      expect(hook.isUsableRuntimeDomain('docs.stripe.com', 'reader')).toBe(false)
      expect(hook.isUsableRuntimeDomain('docs.stripe.com')).toBe(true)
      expect(hook.isUsableRuntimeDomain('vercel.app')).toBe(false)   // the hand list still guards

      const q = (url: string, list: object) => hook.egressDecision('WebFetch', { url }, list, 'quarantine-reader')
      expect(q('https://docs.stripe.com/x', { quarantineDomains: ['docs.stripe.com'] }).blocked).toBe(true)
      expect(q('https://status.anthropic.com/history.rss', { quarantineDomains: [] }).blocked).toBe(false)   // shipped feed
      expect(q('https://docs.stripe.com/x', { quarantineDomains: [], quarantinePosture: 'denylist' }).blocked).toBe(true)
      expect(hook.egressDecision('WebFetch', { url: 'https://docs.stripe.com/x' }, { domains: ['docs.stripe.com'] }, '').blocked).toBe(false)

      expect(existsSync(log)).toBe(true)
      expect(readFileSync(log, 'utf-8')).toContain('[egress-gate] public suffix list unreadable')
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('the reader prompt follows the hook: no quarantine_domains entry, domains by the hand list', () => {
    const dir = tmp()
    try {
      writeFileSync(join(dir, 'egress-allowlist.json'), JSON.stringify({ domains: ['docs.stripe.com'], quarantine_domains: ['support.stripe.com'] }))
      expect(quarantineReaderDomains(dir)).toEqual(['docs.stripe.com', 'support.stripe.com'])
      expect(quarantineReaderDomains(dir, join(dir, 'does-not-exist.json'))).toEqual(['docs.stripe.com'])
      writeFileSync(join(dir, 'egress-allowlist.json'), JSON.stringify({ domains: ['co.uk', 'vercel.app'] }))
      expect(quarantineReaderDomains(dir)).toEqual([])
      expect(quarantineReaderDomains(dir, join(dir, 'does-not-exist.json'))).toEqual(['co.uk'])   // the hook's step 3 takes it too
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })
})

describe('gen-public-suffix-list', () => {
  const NOTICE = [
    '// This Source Code Form is subject to the terms of the Mozilla Public',
    '// License, v. 2.0. If a copy of the MPL was not distributed with this',
    '// file, You can obtain one at https://mozilla.org/MPL/2.0/.',
  ]
  const SAMPLE = [
    ...NOTICE,
    '',
    '// header comment',
    '// ===BEGIN ICANN DOMAINS===',
    'uk',
    'co.uk',
    '*.ck',
    '!www.ck',
    'CO.UK',
    '// ===END ICANN DOMAINS===',
    '',
    '// ===BEGIN PRIVATE DOMAINS===',
    'vercel.app   trailing text is ignored',
    '// ===END PRIVATE DOMAINS===',
  ].join('\n')

  it('splits the sections, keeps the rules verbatim, drops duplicates', () => {
    expect(parsePublicSuffixList(SAMPLE)).toEqual({ icann: ['!www.ck', '*.ck', 'co.uk', 'uk'], private: ['vercel.app'] })
  })

  it('refuses an input it does not fully understand', () => {
    expect(() => parsePublicSuffixList('co.uk\n')).toThrow(/outside a section/)
    expect(() => parsePublicSuffixList('// ===BEGIN ICANN DOMAINS===\nfoo.*.uk\n// ===END ICANN DOMAINS===\n')).toThrow(/unsupported/)
    expect(() => parsePublicSuffixList('// ===BEGIN ICANN DOMAINS===\nuk\n')).toThrow(/not closed/)
  })

  it('is deterministic and computes the git blob id', () => {
    const buf = Buffer.from(SAMPLE)
    const a = buildDocument(buf, { commit: 'a'.repeat(40), commitDate: '2026-10-20T10:40:47+02:00' })
    const b = buildDocument(buf, { commit: 'a'.repeat(40), commitDate: '2026-10-20T10:40:47+02:00' })
    expect(JSON.stringify(a)).toBe(JSON.stringify(b))
    expect(gitBlobId(Buffer.from('hello\n'))).toBe('ce013625030ba8dba906f756967f9e9ca394464a')   // git hash-object
  })

  it('copies the license header verbatim, every line of it, and refuses an input without the MPL notice', () => {
    expect(readLicenseNotice(SAMPLE)).toEqual(NOTICE.map((l) => l.slice(3)))
    const extra = ['// Copyright (c) Example Contributor', ...NOTICE, '', 'rest'].join('\n')
    expect(readLicenseNotice(extra)).toEqual(['Copyright (c) Example Contributor', ...NOTICE.map((l) => l.slice(3))])
    expect(() => readLicenseNotice('// header comment\n\n// ===BEGIN ICANN DOMAINS===\n')).toThrow(/MPL-2.0 notice/)
    expect(() => buildDocument(Buffer.from(SAMPLE.replace(/Mozilla Public/, 'Other Public')), { commit: 'a'.repeat(40), commitDate: 'x' })).toThrow(/MPL-2.0 notice/)
  })

  it('reports removed rules separately', () => {
    const d = diffRules({ icann: ['co.uk', 'uk'], private: ['vercel.app'] }, { icann: ['uk'], private: ['vercel.app', 'r2.dev'] })
    expect(d.icann).toEqual({ added: [], removed: ['co.uk'] })
    expect(d.private).toEqual({ added: ['r2.dev'], removed: [] })
  })
})
