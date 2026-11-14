// Fixture for per-file-tmp.test.ts: a file that cleans up after itself, so it is not named.
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, it } from 'vitest'

it('cleans up its own temp dir', () => {
  const d = mkdtempSync(join(tmpdir(), 'clean-fixture-'))
  rmSync(d, { recursive: true, force: true })
  expect(true).toBe(true)
})
