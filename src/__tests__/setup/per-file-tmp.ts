// setupFile: every test FILE gets its own temp directory under the per-run root, removed after the file (card
// 400faadf, Kernel's leftover inventory 2026-11-14: a full run left 604 entries under ~163 prefixes in ~105 files).
//
// WHY: disk-and-tmp-root.ts (card 8ae42dd0) removes the per-run root after the whole run, so a leaking test cannot
// fill the disk across runs; but within a run every leaked mkdtemp piled up until the end, and with 604 leftovers
// MARVEEN_TEST_TMP_STRICT=1 could not be switched on. Here the leak is bounded by one file: TMPDIR points to
// <run root>/f<rand> while the file runs (os.tmpdir() reads TMPDIR on every call, and a spawned child inherits it),
// and afterAll removes the directory whatever it holds. What a file leaves is named with the file (a warning, so
// the tests can be fixed one by one); what escapes the file's scope (a detached process writing after afterAll, a
// path built from the run root) still reaches the run root, which STRICT judges.
//
// Listed LAST in setupFiles: the earlier seams (default-ssh-dir-seam.ts) read tmpdir() as the run root.
// The directory name is a base-36 number, the first free one (`0`, `1`, ... `z`, `10` ...; mkdirSync is atomic, so
// files running in parallel never share one): a Unix socket path under it must stay under macOS's 104 bytes.
// Measured: with `f` + mkdtemp's 6 characters, tmux-exact-target's socket path was 107 bytes ("File name too long");
// with the number it is 101.
import { mkdirSync, mkdtempSync, readdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterAll, expect } from 'vitest'

import { KNOWN_SEAMS, removeRoot } from './disk-and-tmp-root.js'

export function fileLeftoverNote(file: string, names: string[]): string | null {
  const left = names.filter((n) => !KNOWN_SEAMS.includes(n))
  if (left.length === 0) return null
  return `TMP-MARADEK (fájl): ${file} ${left.length} bejegyzést hagyott a saját temp-könyvtárában (törölve): ` +
    left.slice(0, 5).join(', ') + (left.length > 5 ? ', ...' : '') + '. / The file left temp entries (removed).'
}

export function perFileDir(root: string): string {
  for (let i = 0; i < 36 ** 3; i++) {
    const d = join(root, i.toString(36))
    try {
      mkdirSync(d, { mode: 0o700 })
      return d
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== 'EEXIST') throw e
    }
  }
  return mkdtempSync(join(root, 'f'))
}

const runRoot = process.env.TMPDIR ?? tmpdir()
const dir = perFileDir(runRoot)
process.env.TMPDIR = dir

afterAll(() => {
  const file = expect.getState().testPath ?? '(ismeretlen fájl)'
  process.env.TMPDIR = runRoot
  let names: string[] = []
  try { names = readdirSync(dir) } catch { names = [] }
  const stuck = removeRoot(dir)
  const msg = [fileLeftoverNote(file, names), stuck].filter(Boolean).join(' ')
  // stderr directly: a console.warn in a setup file's afterAll is not printed by vitest 4.1 (measured: the file was
  // removed, the warning never showed)
  if (msg) process.stderr.write(msg + '\n')
})
