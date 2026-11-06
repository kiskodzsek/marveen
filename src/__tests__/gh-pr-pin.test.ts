// GHPRPIN (card 54bd5c28, Viktor 30388 P1-P2): the egress parser lets scripts/gh-pr.mjs run only in the exact,
// pinned, stand-alone shape `node <ROOT>/scripts/gh-pr.mjs ...`, and fails CLOSED on that path when the pin
// is missing or wrong. Two claims, both tested:
//   (a) the shapes the fleet uses pass: plain, -C, output to a file, the body from a heredoc on stdin;
//       commands that only NAME the file (cat, shasum, git add, grep) are not touched;
//   (b) every other shape is denied: VAR= / NODE_OPTIONS, a wrapper, a node option before the script,
//       ; && | $(...) anywhere, bash -c, a relative / dotted / symlinked / copied path, a wrong or missing pin.
// The pin file is a temp file (BASH_EGRESS_SCRIPT_PINS), read at call time. Nothing runs, nothing is fetched.
import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, copyFileSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { createHash } from 'node:crypto'
import { fileURLToPath } from 'node:url'
// @ts-expect-error -- plain .mjs hook, no type declarations
import { classify, gateMessage, GH_PR_SCRIPT } from '../../scripts/hooks/bash-egress-parser.mjs'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const S = join(ROOT, 'scripts', 'gh-pr.mjs')
const dir = mkdtempSync(join(tmpdir(), 'gh-pr-pin-'))
const PINS = join(dir, 'pins.json')
const sha = createHash('sha256').update(readFileSync(S)).digest('hex')
const saved = process.env.BASH_EGRESS_SCRIPT_PINS
const pinWith = (v: unknown) => writeFileSync(PINS, JSON.stringify(v))
const deny = (cmd: string) => classify(cmd) as { deny: boolean, reason: string | null }

beforeAll(() => { process.env.BASH_EGRESS_SCRIPT_PINS = PINS; pinWith({ 'scripts/gh-pr.mjs': sha }) })
afterAll(() => { if (saved === undefined) delete process.env.BASH_EGRESS_SCRIPT_PINS; else process.env.BASH_EGRESS_SCRIPT_PINS = saved })

describe('GHPRPIN: the shapes the fleet uses pass', () => {
  it('the canonical path is the one the parser pins', () => {
    expect(GH_PR_SCRIPT).toBe(S)
  })
  it('plain, -C, output to a file, a body heredoc on stdin (whose text may hold ; && |)', () => {
    for (const cmd of [
      `node ${S} marabel pr get 1171`,
      `node ${S} -C /Users/x/repos/marabel marabel ci runs --branch feat/a`,
      `node ${S} marabel ci log 128093120674 > /tmp/log.txt 2>&1`,
      `/opt/homebrew/bin/node ${S} marabel pr list`,
      `node ${S} marabel pr edit 1171 --body-file - <<'EOF'\n## What\na; b && c | d $(not run)\nEOF`,
      `node "${S}" marabel pr get 1`,
    ]) expect({ cmd, ...deny(cmd) }).toMatchObject({ cmd, deny: false })
  })
  it('commands that only name the file are not gated', () => {
    for (const cmd of [`cat ${S}`, `shasum -a 256 ${S}`, 'git add scripts/gh-pr.mjs && git commit -m x',
      `grep -n x ${S} | head`, 'npx vitest run src/__tests__/gh-pr-script.test.ts'])
      expect({ cmd, ...deny(cmd) }).toMatchObject({ cmd, deny: false })
  })
})

describe('GHPRPIN: every other shape is denied', () => {
  it('P1: no VAR=, wrapper, node option, ; && | $(...), bash -c, substitution', () => {
    for (const cmd of [
      `NODE_OPTIONS=--require=/tmp/x.js node ${S} marabel pr get 1`,
      `X=1 node ${S} marabel pr get 1`,
      `env node ${S} marabel pr get 1`,
      `timeout 10 node ${S} marabel pr get 1`,
      `sudo -u x node ${S} marabel pr get 1`,
      `node --import /tmp/x.mjs ${S} marabel pr get 1`,
      `node -r /tmp/x.js ${S} marabel pr get 1`,
      `node --experimental-loader /tmp/l.mjs ${S} marabel pr get 1`,
      `cd /x && node ${S} marabel pr get 1`,
      `echo x > ${S}; node ${S} marabel pr get 1`,
      `node ${S} marabel pr get 1 | python3 -c 'import sys'`,
      `node ${S} marabel pr get 1 && cp /tmp/e ${S}`,
      `node ${S} marabel pr edit 1 --title "$(cp /tmp/e ${S})"`,
      `node ${S} marabel pr edit 1 --title "\`cp /tmp/e ${S}\`"`,
      `bash -c 'node ${S} marabel pr get 1'`,
      `x=$(node ${S} marabel pr get 1)`,
      `node -e "import('${S}')"`,
      `node ${S} marabel pr edit 1 --body-file - <<EOF\nx $(cp /tmp/e ${S})\nEOF`,
      `node ${S} marabel pr edit 1 --body-file - <<EOF\nx \`cp /tmp/e ${S}\`\nEOF`,
      `node ${S} marabel pr edit 1 --body-file - <<'EOF'\nx\nEOF\nrm -rf /tmp/y`,
      `bun ${S} marabel pr get 1 ; true`,
      `G=${S}; node $G marabel pr get 1`,
      `G=${S}; NODE_OPTIONS=--require=/tmp/x.js node "$G" marabel pr get 1`,
      `export G=${S} && node \${G} marabel pr get 1`,
      `for s in ${S}; do node $s marabel pr get 1; done`,
    ]) expect({ cmd, ...deny(cmd) }).toMatchObject({ cmd, deny: true })
  })
  it('VAR= and wrappers are refused by the shape rule itself, not only by the path rule behind it', () => {
    for (const cmd of [
      `NODE_OPTIONS=--require=/tmp/x.js node ${S} marabel pr get 1`, `X=1 node ${S} marabel pr get 1`,
      `env node ${S} marabel pr get 1`, `timeout 10 node ${S} marabel pr get 1`, `sudo -u x node ${S} marabel pr get 1`,
    ]) expect({ cmd, ...deny(cmd) }).toMatchObject({ cmd, deny: true, reason: 'gh-pr-pin-shape' })
  })
  it('the path: absolute, no dot segment, not a symlink, not a copy', () => {
    const copy = join(dir, 'gh-pr.mjs'); copyFileSync(S, copy)
    const link = join(dir, 'link', 'gh-pr.mjs')
    mkdirSync(join(dir, 'link'), { recursive: true }); symlinkSync(S, link)
    for (const cmd of [
      'node scripts/gh-pr.mjs marabel pr get 1',
      `node ${ROOT}/scripts/../scripts/gh-pr.mjs marabel pr get 1`,
      `node ${ROOT}/./scripts/gh-pr.mjs marabel pr get 1`,
      `node ${copy} marabel pr get 1`,
      `node ${link} marabel pr get 1`,
    ]) expect({ cmd, ...deny(cmd) }).toMatchObject({ cmd, deny: true, reason: 'gh-pr-pin-path' })
  })
  it('P2: a wrong, malformed or missing pin denies (fail-closed)', () => {
    const cmd = `node ${S} marabel pr get 1`
    pinWith({ 'scripts/gh-pr.mjs': '0'.repeat(64) })
    expect(deny(cmd)).toMatchObject({ deny: true, reason: 'gh-pr-pin-hash' })
    pinWith({ 'scripts/gh-pr.mjs': 'not-a-sha' })
    expect(deny(cmd)).toMatchObject({ deny: true, reason: 'gh-pr-pin-missing' })
    pinWith({})
    expect(deny(cmd)).toMatchObject({ deny: true, reason: 'gh-pr-pin-missing' })
    writeFileSync(PINS, '{broken')
    expect(deny(cmd)).toMatchObject({ deny: true, reason: 'gh-pr-pin-missing' })
    process.env.BASH_EGRESS_SCRIPT_PINS = join(dir, 'no-such-file.json')
    expect(deny(cmd)).toMatchObject({ deny: true, reason: 'gh-pr-pin-missing' })
    process.env.BASH_EGRESS_SCRIPT_PINS = PINS
    pinWith({ 'scripts/gh-pr.mjs': sha })
    expect(deny(cmd)).toMatchObject({ deny: false })
  })
  it('the deny message names the exact shape and the pin', () => {
    const m = gateMessage({ deny: true, reason: 'gh-pr-pin-shape', hosts: [] })
    expect(m).toContain('GHPRPIN')
    expect(m).toContain('egress-script-pins.json')
    expect(m).toContain('gh-pr-pin-shape')
  })
})
