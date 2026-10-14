// Viktor INFO (review of b4679902): the owner-name exception must stay BEHIND
// the reserved and channel-identity refusals. With a sane OWNER_NAME the order
// is invisible -- moving the exception to the top kept every other suite green.
// It decides only when OWNER_NAME is misconfigured to a privileged id, and then
// the refusal must still win: the owner name is never a way around them.

import { describe, it, expect, vi, afterEach } from 'vitest'
import { COORDINATOR_AGENT_ID, VOICE_CHANNEL_AGENT_ID } from '../channel-coordinator/ingest.js'

async function refusalWithOwnerName(ownerName: string): Promise<string | null> {
  vi.resetModules()
  vi.doMock('../config.js', async (importOriginal) => ({
    ...(await importOriginal<typeof import('../config.js')>()),
    OWNER_NAME: ownerName,
  }))
  const config = await import('../config.js')
  expect(config.OWNER_NAME).toBe(ownerName)
  const { lockOwnerRefusal } = await import('../web/routes/desktop-lock.js')
  return lockOwnerRefusal(ownerName, () => true)
}

afterEach(() => {
  vi.doUnmock('../config.js')
  vi.resetModules()
})

describe('owner-name exception sits behind the privileged-id refusals', () => {
  it('OWNER_NAME misconfigured to the reserved sender is still refused as reserved', async () => {
    for (const name of ['system', 'System']) {
      expect(await refusalWithOwnerName(name), name).toMatch(/reserved/i)
    }
  })

  it('OWNER_NAME misconfigured to a channel identity is still refused as one', async () => {
    for (const name of [COORDINATOR_AGENT_ID, VOICE_CHANNEL_AGENT_ID]) {
      expect(await refusalWithOwnerName(name), name).toMatch(/channel identity/i)
    }
  })

  it('NEGATIVE CONTROL: an ordinary OWNER_NAME is accepted through the exception', async () => {
    // The registry predicate is passed as () => true above, so use one that
    // refuses everything to prove it is the exception, not the registry, that
    // lets the owner through.
    vi.resetModules()
    vi.doMock('../config.js', async (importOriginal) => ({
      ...(await importOriginal<typeof import('../config.js')>()),
      OWNER_NAME: 'Pátrik',
    }))
    const { lockOwnerRefusal } = await import('../web/routes/desktop-lock.js')
    expect(lockOwnerRefusal('Pátrik', () => false)).toBeNull()
  })
})
