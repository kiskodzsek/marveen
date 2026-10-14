// Viktor INFO (3354, review of 095a413c): the desktop-lock owner becomes the
// from_agent of a fleet-wide broadcast, but unlike the from of /api/messages it
// was never checked against the agent registry. Any holder of the shared token
// could lock the screen as an agent that does not exist, and every agent would
// receive a [DESKTOP-LOCK] row from it.
//
// The registry here is the mocked directory listing, so the DEFAULT predicate
// is what runs -- the other suites inject one because they have no agents/ dir.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { existsSync } from 'node:fs'
import { Readable } from 'node:stream'

const ON_DISK = ['kernel', 'viktor', 'hidden-worker']

vi.mock('../web/agent-config.js', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../web/agent-config.js')>()),
  listAllAgentNames: () => [...ON_DISK],
}))

const createAgentMessage = vi.fn()
vi.mock('../db.js', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../db.js')>()),
  createAgentMessage: (...args: unknown[]) => createAgentMessage(...args),
}))

import { MAIN_AGENT_ID, OWNER_NAME } from '../config.js'
import { lockOwnerRefusal, isRegisteredLockOwner, tryHandleDesktopLock } from '../web/routes/desktop-lock.js'
import { DESKTOP_LOCK_PATH } from '../web/desktop-lock.js'

describe('desktop-lock owner must be a registered agent (Viktor INFO 3354)', () => {
  it('accepts every agent on disk and the main agent', () => {
    for (const ok of [...ON_DISK, MAIN_AGENT_ID]) {
      expect(lockOwnerRefusal(ok), ok).toBeNull()
    }
  })

  it('accepts the configured human owner, who has no agents/ directory', () => {
    expect(ON_DISK).not.toContain(OWNER_NAME)
    expect(lockOwnerRefusal(OWNER_NAME)).toBeNull()
  })

  it('refuses a plain id that names no agent', () => {
    for (const bad of ['ghost', 'kernel2', 'zack']) {
      expect(lockOwnerRefusal(bad), bad).toMatch(/not a registered fleet agent/)
    }
  })

  it('refuses a case variant of a registered name', () => {
    // A stat of agents/Kernel succeeds on a case-insensitive filesystem
    // (macOS default), so an isKnownAgent-style check would let these through.
    for (const bad of ['Kernel', 'KERNEL', 'Viktor']) {
      expect(isRegisteredLockOwner(bad), bad).toBe(false)
      expect(lockOwnerRefusal(bad), bad).toMatch(/not a registered fleet agent/)
    }
  })

  it('keeps the earlier, more specific refusals ahead of the registry check', () => {
    expect(lockOwnerRefusal('system')).toMatch(/reserved/i)
    expect(lockOwnerRefusal('kernel x')).toMatch(/plain id/)
  })
})

describe('POST /api/desktop-lock with an unregistered owner', () => {
  beforeEach(() => createAgentMessage.mockClear())

  it('is refused with 403 before any state change or broadcast', async () => {
    const req = Readable.from([Buffer.from(JSON.stringify({
      owner: 'ghost', note: 'hagyjatok a kepernyot', estimatedMinutes: 5,
    }))]) as any
    let status = 0
    let out = ''
    const res = { writeHead(s: number) { status = s }, end(b?: string) { out = b ?? '' } } as any
    const lockedBefore = existsSync(DESKTOP_LOCK_PATH)
    const handled = await tryHandleDesktopLock({
      req, res, path: '/api/desktop-lock', method: 'POST',
      url: new URL('http://x/api/desktop-lock'), auth: { kind: 'token' },
    } as any)
    expect(handled).toBe(true)
    expect(status).toBe(403)
    expect(String(JSON.parse(out)?.error)).toMatch(/not a registered fleet agent/)
    expect(existsSync(DESKTOP_LOCK_PATH)).toBe(lockedBefore)
    expect(createAgentMessage).not.toHaveBeenCalled()
  })
})
