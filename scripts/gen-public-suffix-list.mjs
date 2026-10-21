#!/usr/bin/env node
// Regenerates scripts/hooks/public-suffix-list.json from a LOCAL copy of the
// Public Suffix List (Viktor 13122 L2, 13207).
//
// Why a vendored file: the egress gate refuses an operator allowlist entry
// that names a public suffix (`co.uk`, `vercel.app`) or a parent of one
// (`amazonaws.com`), because the gate's "exact host or any subdomain" rule
// would turn that one entry into every registrant or tenant under it. The
// hand-kept MULTI_TENANT_SUFFIXES list missed regional S3, `r2.dev` and every
// ICANN second-level suffix; the PSL is the maintained source for exactly
// this question.
//
// This script downloads NOTHING. The source is pinned by commit and fetched
// with git, which is content-addressed:
//
//   git init -q psl && cd psl
//   git fetch --depth=1 https://github.com/publicsuffix/list <SHA>
//   git show <SHA>:public_suffix_list.dat > ../public_suffix_list.dat
//   git log -1 --format=%cI <SHA>
//
//   node scripts/gen-public-suffix-list.mjs ../public_suffix_list.dat \
//     --commit <SHA> --commit-date <ISO date from git log>
//
// The script computes the git blob id and the sha256 of the input itself and
// writes both into the JSON, so a reviewer can tie the content to the commit
// (`git rev-parse <SHA>:public_suffix_list.dat` must print the same blob id).
// Same input, same arguments -> byte-identical output: no timestamp of its
// own, rules sorted.
//
// It prints the rules ADDED and REMOVED against the file it replaces. Put the
// removals in the PR description as a separate list: a removed suffix opens
// its registrants or tenants again.
//
// Updating: by hand, through a reviewed PR, quarterly or when a missing suffix
// is reported. Nothing fetches this list automatically.
//
// The rules are stored verbatim (Unicode as in the source, `*.` and `!`
// prefixes kept), so the rule set can be compared line for line with the
// .dat by an independent parser. Conversion to ASCII happens in the loaders.

import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const DEFAULT_OUT = join(dirname(fileURLToPath(import.meta.url)), 'hooks', 'public-suffix-list.json')

// The MPL-2.0 notice the input must open with. The whole leading comment block
// is copied into `_license` line by line, unchanged apart from the `// ` marker
// (MPL-2.0 3.4: a license notice may not be removed or altered; Lex 13212,
// 13213), so a copyright or license line added upstream travels with it.
const MPL_NOTICE =
  'This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0. ' +
  'If a copy of the MPL was not distributed with this file, You can obtain one at https://mozilla.org/MPL/2.0/.'

const SECTIONS = { ICANN: 'icann', PRIVATE: 'private' }

// One rule per line, read up to the first whitespace; `//` lines are comments.
// The BEGIN/END markers are comments too, and they are what assigns a rule to
// its section. A rule outside both sections, a nested or unclosed section, or
// a `*` anywhere but a leading `*.` label is an error: this list decides what
// the gate refuses, so an input the parser does not fully understand stops
// the run instead of producing a quietly smaller file.
export function parsePublicSuffixList(text) {
  const out = { icann: [], private: [] }
  let section = null
  const seen = new Set()
  const lines = text.split(/\r?\n/)
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim()
    if (!line) continue
    if (line.startsWith('//')) {
      const m = /^\/\/ ===(BEGIN|END) (ICANN|PRIVATE) DOMAINS===$/.exec(line)
      if (!m) continue
      const name = SECTIONS[m[2]]
      if (m[1] === 'BEGIN') {
        if (section) throw new Error(`line ${i + 1}: BEGIN ${m[2]} inside ${section}`)
        section = name
      } else {
        if (section !== name) throw new Error(`line ${i + 1}: END ${m[2]} without its BEGIN`)
        section = null
      }
      continue
    }
    const rule = line.split(/\s/)[0].toLowerCase()
    if (!section) throw new Error(`line ${i + 1}: rule outside a section: ${rule}`)
    const body = rule.startsWith('!') ? rule.slice(1) : rule.startsWith('*.') ? rule.slice(2) : rule
    if (!body || body.includes('*') || body.includes('!') || body.startsWith('.') || body.endsWith('.') || body.includes('..')) {
      throw new Error(`line ${i + 1}: unsupported rule shape: ${rule}`)
    }
    if (seen.has(rule)) continue
    seen.add(rule)
    out[section].push(rule)
  }
  if (section) throw new Error(`section ${section} is not closed`)
  for (const k of Object.keys(out)) out[k].sort()
  return out
}

// The comment lines before the first blank line, `// ` marker removed. An
// input whose header does not carry the MPL notice stops the run: the file
// would go out under a license it does not state.
export function readLicenseNotice(text) {
  const notice = []
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trimEnd()
    if (!line.trim()) break
    if (!line.startsWith('//')) break
    notice.push(line.replace(/^\/\/ ?/, ''))
  }
  if (!notice.join(' ').includes(MPL_NOTICE)) throw new Error('the input does not open with the MPL-2.0 notice')
  return notice
}

export function gitBlobId(buf) {
  return createHash('sha1').update(`blob ${buf.length}\0`).update(buf).digest('hex')
}

export function buildDocument(buf, { commit, commitDate }) {
  const text = buf.toString('utf-8')
  const license = readLicenseNotice(text)
  const rules = parsePublicSuffixList(text)
  return {
    _license: license,
    _license_text: 'LICENSES/MPL-2.0.txt, https://mozilla.org/MPL/2.0/. This file is MPL-2.0, not covered by ' +
      "the repository's MIT license (THIRD_PARTY_LICENSES.md).",
    _note: 'Derived, filtered extract of public_suffix_list.dat: the rules only (comments dropped), split into ' +
      'the ICANN and PRIVATE sections, lowercased, sorted, duplicates removed.',
    _source: 'Generated by scripts/gen-public-suffix-list.mjs from the Public Suffix List ' +
      '(https://publicsuffix.org/list/), github.com/publicsuffix/list at the commit below. Do not edit by hand.',
    source_url: `https://github.com/publicsuffix/list/blob/${commit}/public_suffix_list.dat`,
    commit,
    commit_date: commitDate,
    path: 'public_suffix_list.dat',
    blob: gitBlobId(buf),
    sha256: createHash('sha256').update(buf).digest('hex'),
    counts: { icann: rules.icann.length, private: rules.private.length },
    icann: rules.icann,
    private: rules.private,
  }
}

export function diffRules(previous, next) {
  const res = {}
  for (const k of ['icann', 'private']) {
    const before = new Set(Array.isArray(previous?.[k]) ? previous[k] : [])
    const after = new Set(next[k])
    res[k] = {
      added: next[k].filter((r) => !before.has(r)),
      removed: [...before].filter((r) => !after.has(r)).sort(),
    }
  }
  return res
}

function main(argv) {
  const args = argv.slice(2)
  const opt = (name) => {
    const i = args.indexOf(name)
    if (i === -1) return undefined
    const v = args[i + 1]
    args.splice(i, 2)
    return v
  }
  const commit = opt('--commit')
  const commitDate = opt('--commit-date')
  const out = opt('--out') ?? DEFAULT_OUT
  const input = args[0]
  if (!input || !/^[0-9a-f]{40}$/.test(commit ?? '') || !commitDate) {
    process.stderr.write('usage: gen-public-suffix-list.mjs <public_suffix_list.dat> --commit <40-hex sha> --commit-date <iso> [--out <json>]\n')
    process.exit(2)
  }
  const doc = buildDocument(readFileSync(input), { commit, commitDate })
  let previous = null
  if (existsSync(out)) {
    try { previous = JSON.parse(readFileSync(out, 'utf-8')) } catch { previous = null }
  }
  const diff = diffRules(previous, doc)
  writeFileSync(out, JSON.stringify(doc, null, 1) + '\n', 'utf-8')
  process.stdout.write(`wrote ${out}\ncommit ${commit} (${commitDate})\nblob ${doc.blob}\nsha256 ${doc.sha256}\n`)
  for (const k of ['icann', 'private']) {
    process.stdout.write(`${k}: ${doc.counts[k]} rules, +${diff[k].added.length} -${diff[k].removed.length}\n`)
  }
  for (const k of ['icann', 'private']) {
    for (const r of diff[k].removed) process.stdout.write(`REMOVED ${k} ${r}\n`)
  }
  for (const k of ['icann', 'private']) {
    for (const r of diff[k].added) process.stdout.write(`ADDED ${k} ${r}\n`)
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) main(process.argv)
