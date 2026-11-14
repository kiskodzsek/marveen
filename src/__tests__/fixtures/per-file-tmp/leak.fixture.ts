// Fixture for per-file-tmp.test.ts: a file that leaks into its temp dir, once through a path it saved at import
// time (Kernel 42203: a module-level tmpdir() must land in the file's own directory too), and, with
// FIXTURE_ESCAPE=1, once into the run root (what the per-file directory cannot catch; STRICT must).
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, dirname, join } from 'node:path'
import { expect, it } from 'vitest'

const atImport = tmpdir()

it('leaks into its own temp dir', () => {
  expect(basename(atImport)).toMatch(/^[0-9a-z]{1,3}$/)
  expect(basename(dirname(atImport))).toMatch(/^mvt-/)
  mkdtempSync(join(tmpdir(), 'leak-fixture-'))
  writeFileSync(join(atImport, 'leak-at-import.txt'), 'x')
  if (process.env.FIXTURE_ESCAPE === '1') mkdtempSync(join(dirname(tmpdir()), 'escaped-'))
})
