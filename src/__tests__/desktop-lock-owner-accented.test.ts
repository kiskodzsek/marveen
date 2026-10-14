// RESERVEDSENDER1013 I4 (Viktor, delta review of 861dcf3f): the desktop-lock
// owner exception -- `!isPlainSenderId(owner) && owner.trim() !== OWNER_NAME.trim()`
// -- never decided anything in the other suites, because there OWNER_NAME is a
// plain id and the positive rule already accepts it. Deleting the exception, or
// loosening it into a sanitized/case-folded comparison (which would bring the
// zero-width bypass back), stayed green.
//
// Here OWNER_NAME carries an accent, so only the exact-match branch can accept
// it, and every near miss has to fall through to the plain-id refusal.

import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const OWNER = 'Pátrik'

vi.mock('../config.js', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../config.js')>()),
  OWNER_NAME: OWNER,
}))

const tmpHome = mkdtempSync(join(tmpdir(), 'desktoplock-owner-'))
const realHome = process.env.HOME
process.env.HOME = tmpHome

let lock: typeof import('../web/routes/desktop-lock.js')

beforeAll(async () => {
  lock = await import('../web/routes/desktop-lock.js')
})

afterAll(() => {
  process.env.HOME = realHome
  rmSync(tmpHome, { recursive: true, force: true })
})

describe('desktop-lock owner exception with an accented OWNER_NAME (Viktor I4)', () => {
  it('the mock is in effect: the configured owner is not a plain id', async () => {
    const config = await import('../config.js')
    const rs = await import('../reserved-sender.js')
    expect(config.OWNER_NAME).toBe(OWNER)
    expect(rs.isPlainSenderId(OWNER)).toBe(false)
  })

  it('accepts the exact configured owner name', () => {
    expect(lock.lockOwnerRefusal(OWNER)).toBeNull()
    // surrounding whitespace is trimmed on both sides of the comparison
    expect(lock.lockOwnerRefusal(` ${OWNER} `)).toBeNull()
  })

  it('refuses every near miss with the plain-id rule', () => {
    const nearMisses = [
      `${OWNER}\u200B`, // zero-width space appended
      `P\u200Bátrik`, // zero-width space inside
      'pátrik', // case-folded
      'Pa\u0301trik', // decomposed accent (NFD): looks identical, different code points
    ]
    for (const bad of nearMisses) {
      expect(lock.lockOwnerRefusal(bad), JSON.stringify(bad)).toMatch(/plain id/)
    }
  })

  it('the accent-stripped name is decided by the agent registry, not by the exception', () => {
    // 'Patrik' is in the id alphabet, so it is judged like any agent id: held
    // only if an agent of that exact name is registered. The owner exception
    // never stretches to it -- the exact accented owner name is the only one.
    expect(lock.lockOwnerRefusal('Patrik', () => false)).toMatch(/not a registered fleet agent/)
    expect(lock.lockOwnerRefusal('Patrik', (id) => id === 'Patrik')).toBeNull()
  })
})
