import { describe, it, expect } from 'vitest'
import { spawnSync } from 'node:child_process'
import { join } from 'node:path'

const ROOT = join(__dirname, '..', '..')

// scripts/storage-mirror/ (card 4e790bdd) is dependency-free and has its own
// node:test suite; it runs here so `npm test` covers it without a workflow
// change (Viktor 15290 I3). NODE_OPTIONS is cleared so vitest's own loader
// flags do not leak into the child.
describe('storage mirror restore + negative test (scripts/storage-mirror)', () => {
  it('the node:test suite passes (untrusted manifest, pin, no DELETE, AccessDenied-only probes)', () => {
    const env = { ...process.env }
    delete env.NODE_OPTIONS
    const res = spawnSync(process.execPath, ['--test', join(ROOT, 'scripts', '__tests__', 'storage-mirror.node-test.mjs')], {
      encoding: 'utf-8',
      timeout: 120_000,
      env,
    })
    if (res.status !== 0) {
      console.error(res.stdout)
      console.error(res.stderr)
    }
    expect(res.status).toBe(0)
  })
})
