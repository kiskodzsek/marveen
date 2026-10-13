// FLEETEXPORT1013 (Viktor, HIGH; Klodel 2435): the fleet export returns the
// whole Vault and the import rewrites it, so both require the owner's browser
// session. Every other credential -- the fleet's shared Bearer token above all
// -- gets 403, an audit row and an owner alert; the transfer itself never runs.
import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'
import type http from 'node:http'
import { Readable } from 'node:stream'
import { initDatabase, getDb, createDashboardUser } from '../db.js'
import { SESSION_COOKIE_NAME } from '../web/auth-gate.js'
import { createSession, _clearSessionCacheForTest } from '../web/auth-sessions.js'
import type { RouteContext } from '../web/routes/types.js'

// Never reach the real notifier (a production checkout would alert the owner).
const notify = vi.hoisted(() => vi.fn(async () => {}))
vi.mock('../notify.js', () => ({
  notifyChannel: vi.fn(async () => {}),
  notifyTelegram: vi.fn(async () => {}),
  notifySecurityEvent: notify,
}))
// The transfer must not run on a refusal; on an allowed call a stub is enough.
const transfer = vi.hoisted(() => ({
  exportFleet: vi.fn(() => ({ data: '{"stub":true}', exportedAt: '2026-10-13T00:00:00.000Z' })),
  importFleet: vi.fn(() => ({ dryRun: true, errors: [] })),
}))
vi.mock('../web/fleet-transfer.js', async (orig) => ({
  ...(await orig<typeof import('../web/fleet-transfer.js')>()),
  exportFleet: transfer.exportFleet,
  importFleet: transfer.importFleet,
}))

const { tryHandleFleet, fleetOwnerSession } = await import('../web/routes/fleet.js')

interface MockRes { statusCode: number; body: string; writeHead(s: number, h?: unknown): MockRes; end(d?: unknown): void }
function mkRes(): MockRes {
  return {
    statusCode: 0,
    body: '',
    writeHead(s) { this.statusCode = s; return this },
    end(d) { if (d !== undefined) this.body += String(d) },
  }
}

async function call(method: string, full: string, opts: { cookie?: string; auth?: RouteContext['auth']; bearer?: boolean } = {}) {
  const r = Readable.from([Buffer.from('{}')]) as unknown as http.IncomingMessage
  r.headers = {
    ...(opts.cookie ? { cookie: `${SESSION_COOKIE_NAME}=${opts.cookie}` } : {}),
    ...(opts.bearer ? { authorization: 'Bearer x' } : {}),
  }
  const res = mkRes()
  const handled = await tryHandleFleet({
    req: r, res: res as unknown as http.ServerResponse, path: full.split('?')[0], method,
    url: new URL(`http://127.0.0.1:3420${full}`), auth: opts.auth,
  } as RouteContext)
  return { handled, res }
}

function auditRows(): Array<{ key: string; actor: string }> {
  return getDb().prepare("SELECT key, actor FROM config_change_log WHERE key LIKE 'security.fleet_%' ORDER BY id").all() as Array<{ key: string; actor: string }>
}

let ownerCookie = ''
beforeAll(() => {
  process.env.NODE_ENV = 'test'
  initDatabase(':memory:')
})
beforeEach(() => {
  getDb().exec("DELETE FROM auth_sessions; DELETE FROM dashboard_users; DELETE FROM config_change_log WHERE key LIKE 'security.fleet_%'")
  _clearSessionCacheForTest()
  notify.mockClear(); transfer.exportFleet.mockClear(); transfer.importFleet.mockClear()
  const u = createDashboardUser('patrik', 'not-a-real-hash')
  ownerCookie = createSession({ userId: u.id, username: u.username })
})

const ROUTES: Array<[string, string]> = [
  ['GET', '/api/fleet/export'],
  ['POST', '/api/fleet/import'],
  ['POST', '/api/fleet/import?apply=true'],
]

describe('refused without the owner session', () => {
  const credentials: Array<[string, RouteContext['auth']]> = [
    ['the shared Bearer token', { kind: 'token' }],
    ['the token with an agent claim', { kind: 'token', agent: 'dave' }],
    ['a full-scope device key', { kind: 'device', device: 'phone', scope: 'full' }],
    ['a federation peer', { kind: 'federation', peer: 'p1' }],
    ['no principal', undefined],
  ]
  for (const [method, full] of ROUTES) {
    for (const [name, auth] of credentials) {
      it(`${method} ${full} with ${name}: 403, nothing transferred, audited, owner alerted`, async () => {
        const { handled, res } = await call(method, full, { auth })
        expect(handled).toBe(true)
        expect(res.statusCode).toBe(403)
        expect(transfer.exportFleet).not.toHaveBeenCalled()
        expect(transfer.importFleet).not.toHaveBeenCalled()
        const rows = auditRows()
        expect(rows).toHaveLength(1)
        expect(rows[0].key).toMatch(/^security\.fleet_(export|import_dryrun|import_apply)_denied$/)
        expect(notify).toHaveBeenCalledTimes(1)
      })
    }
  }
  it('a forged or expired session cookie is refused too', async () => {
    const { res } = await call('GET', '/api/fleet/export', { cookie: 'forged-value', auth: { kind: 'token' } })
    expect(res.statusCode).toBe(403)
    expect(transfer.exportFleet).not.toHaveBeenCalled()
  })
  it('a session claimed only in ctx.auth (no real cookie) is not enough', async () => {
    const { res } = await call('GET', '/api/fleet/export', { auth: { kind: 'session', user: 'patrik' } })
    expect(res.statusCode).toBe(403)
  })
})

describe('allowed with the owner session', () => {
  it('export runs and the access is audited with the user', async () => {
    const { res } = await call('GET', '/api/fleet/export', { cookie: ownerCookie, auth: { kind: 'session', user: 'patrik' } })
    expect(res.statusCode).toBe(200)
    expect(transfer.exportFleet).toHaveBeenCalledTimes(1)
    expect(auditRows()).toEqual([{ key: 'security.fleet_export', actor: 'session:patrik' }])
    expect(notify).not.toHaveBeenCalled()
  })
  it('the session cookie decides even when the UI also sends the Bearer (token mode)', async () => {
    const { res } = await call('GET', '/api/fleet/export', { cookie: ownerCookie, bearer: true, auth: { kind: 'token' } })
    expect(res.statusCode).toBe(200)
  })
  it('import dry-run and apply are audited separately', async () => {
    await call('POST', '/api/fleet/import', { cookie: ownerCookie })
    await call('POST', '/api/fleet/import?apply=true', { cookie: ownerCookie })
    expect(auditRows().map((r) => r.key)).toEqual(['security.fleet_import_dryrun', 'security.fleet_import_apply'])
    expect(transfer.importFleet).toHaveBeenCalledTimes(2)
  })
  it('fleetOwnerSession reads only a valid cookie', () => {
    expect(fleetOwnerSession({ headers: { cookie: `${SESSION_COOKIE_NAME}=${ownerCookie}` } })).toBe('patrik')
    expect(fleetOwnerSession({ headers: {} })).toBeNull()
    expect(fleetOwnerSession({ headers: { cookie: `${SESSION_COOKIE_NAME}=nope` } })).toBeNull()
  })
})

describe('other paths are not handled', () => {
  it('returns false for a neighbouring path', async () => {
    const { handled } = await call('GET', '/api/fleet/other', { auth: { kind: 'token' } })
    expect(handled).toBe(false)
  })
})
