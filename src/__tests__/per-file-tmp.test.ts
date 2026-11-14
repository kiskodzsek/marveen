import { spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, readdirSync, rmSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterAll, describe, expect, it } from 'vitest'

import { KNOWN_SEAMS } from './setup/disk-and-tmp-root.js'
import { fileLeftoverNote, perFileDir } from './setup/per-file-tmp.js'

// Card 400faadf (Kernel's inventory 2026-11-14: a full run left 604 temp entries): every test file runs with its own
// TMPDIR under the per-run root, removed after the file; a file that leaves something is named; what escapes the
// file's scope reaches the run root, which MARVEEN_TEST_TMP_STRICT=1 turns red. Measured with a NESTED vitest run of
// the real globalSetup and setup file (fixtures/per-file-tmp), not by calling the hook by hand.

const fixtures = fileURLToPath(new URL('./fixtures/per-file-tmp/', import.meta.url))
const vitestBin = join(dirname(createRequire(import.meta.url).resolve('vitest/package.json')), 'vitest.mjs')
const bases: string[] = []
afterAll(() => { for (const b of bases) rmSync(b, { recursive: true, force: true }) })

function nested(env: Record<string, string>): { rc: number | null; out: string; base: string } {
  const base = mkdtempSync(join(tmpdir(), 'nest-'))
  bases.push(base)
  const r = spawnSync(process.execPath, [vitestBin, 'run', '--root', fixtures, '--config',
    join(fixtures, 'vitest.fixture.config.ts')], {
    encoding: 'utf8',
    timeout: 50_000,
    env: { ...process.env, TMPDIR: base, MARVEEN_TEST_MIN_FREE_GIB: '0', MARVEEN_TEST_TMP_STRICT: '', FIXTURE_ESCAPE: '',
      ...env },
  })
  return { rc: r.status, out: `${r.stdout}\n${r.stderr}`, base }
}

describe('per-file temp directory', () => {
  it('a leaking file is named with what it left, and the run root stays clean: STRICT=1 is green', () => {
    const { rc, out, base } = nested({ MARVEEN_TEST_TMP_STRICT: '1' })
    expect(rc, out).toBe(0)
    expect(out).toMatch(/TMP-MARADEK \(fájl\): \S*leak\.fixture\.ts 2 bejegyzést/)
    expect(out).toContain('leak-fixture-')
    expect(out).toContain('leak-at-import.txt')  // a path saved at import time is the file's own directory too
    expect(out).not.toMatch(/TMP-MARADEK \(fájl\): \S*clean\.fixture\.ts/)
    expect(out).not.toContain('TMP-MARADEK: a tesztfutás után')
    expect(readdirSync(base)).toEqual([])  // the run root (mvt-*) is gone with everything under it
  }, 60_000)

  it('what escapes the file into the run root turns STRICT=1 red, with its name', () => {
    const { rc, out, base } = nested({ MARVEEN_TEST_TMP_STRICT: '1', FIXTURE_ESCAPE: '1' })
    expect(rc, out).not.toBe(0)
    expect(out).toContain('TMP-MARADEK: a tesztfutás után 1 bejegyzés')
    expect(out).toContain('escaped-')
    expect(readdirSync(base)).toEqual([])
  }, 60_000)

  it('without STRICT the escape is a warning and the run stays green', () => {
    const { rc, out } = nested({ FIXTURE_ESCAPE: '1' })
    expect(rc, out).toBe(0)
    expect(out).toContain('TMP-MARADEK: a tesztfutás után 1 bejegyzés')
  }, 60_000)

  it('this file itself runs in its own directory under the run root', () => {
    expect(tmpdir()).toMatch(/\/mvt-[^/]+\/[0-9a-z]{1,3}$/)
    expect(existsSync(tmpdir())).toBe(true)
  })
})

describe('fileLeftoverNote', () => {
  it('names the file, the count and the first five entries; nothing left is null', () => {
    expect(fileLeftoverNote('a.test.ts', [])).toBeNull()
    const msg = fileLeftoverNote('a.test.ts', ['x1', 'x2', 'x3', 'x4', 'x5', 'x6'])
    expect(msg).toContain('a.test.ts 6 bejegyzést')
    expect(msg).toContain('x5, ...')
    expect(msg).not.toContain('x6')
  })

  it('perFileDir takes the first free base-36 name, so parallel files never share one', () => {
    const root = mkdtempSync(join(tmpdir(), 'pfd-'))
    bases.push(root)
    expect(perFileDir(root)).toBe(join(root, '0'))
    expect(perFileDir(root)).toBe(join(root, '1'))
    rmSync(join(root, '0'), { recursive: true })
    expect(perFileDir(root)).toBe(join(root, '0'))
  })

  it('a known seam is not a leftover', () => {
    expect(fileLeftoverNote('a.test.ts', [...KNOWN_SEAMS])).toBeNull()
  })
})
