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

const { tryHandleFleet, fleetOwnerSession, shouldAlertFleetDenial, FLEET_DENIED_ALERT_KEY } = await import('../web/routes/fleet.js')
const { tryHandleAuth } = await import('../web/routes/auth.js')

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
  getDb().exec("DELETE FROM auth_sessions; DELETE FROM dashboard_users; DELETE FROM sqlite_sequence WHERE name = 'dashboard_users'; DELETE FROM config_change_log WHERE key LIKE 'security.fleet_%' OR key = 'security.alert.fleet_denied'")
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

// Viktor 2460 (HIGH): token -> create a user -> log in -> session -> export.
describe('only the OWNER session, and no token-minted user', () => {
  async function authCall(method: string, path: string, auth: RouteContext['auth'], body?: unknown) {
    const r = Readable.from(body === undefined ? [] : [Buffer.from(JSON.stringify(body))]) as unknown as http.IncomingMessage
    r.headers = {}
    const res = mkRes()
    await tryHandleAuth({ req: r, res: res as unknown as http.ServerResponse, path, method, url: new URL(`http://127.0.0.1:3420${path}`), auth } as RouteContext)
    return res
  }
  it('the token can no longer create a user once the install has one: 403, audited', async () => {
    const res = await authCall('POST', '/api/auth/users', { kind: 'token' }, { username: 'evil', password: 'long-enough-password-1' })
    expect(res.statusCode).toBe(403)
    const rows = getDb().prepare("SELECT key FROM config_change_log WHERE key = 'security.dashboard_user_create_denied'").all()
    expect(rows).toHaveLength(1)
  })
  it('deleting every user does not reopen token creation (the install HAD a user)', async () => {
    getDb().exec('DELETE FROM dashboard_users')
    const res = await authCall('POST', '/api/auth/users', { kind: 'token' }, { username: 'evil', password: 'long-enough-password-1' })
    expect(res.statusCode).toBe(403)
  })
  it('first-run (never had a user): the token may still create the first one, audited and alerted', async () => {
    getDb().exec("DELETE FROM dashboard_users; DELETE FROM sqlite_sequence WHERE name = 'dashboard_users'")
    const res = await authCall('POST', '/api/auth/users', { kind: 'token' }, { username: 'owner', password: 'long-enough-password-1' })
    expect(res.statusCode).toBe(201)
    expect(getDb().prepare("SELECT key FROM config_change_log WHERE key = 'security.dashboard_user_created'").all()).toHaveLength(1)
    expect(notify).toHaveBeenCalledTimes(1)
  })
  it('a second user (created from the owner session) has a valid session but gets 403 on the fleet routes', async () => {
    const res = await authCall('POST', '/api/auth/users', { kind: 'session', user: 'patrik' }, { username: 'second', password: 'long-enough-password-1' })
    expect(res.statusCode).toBe(201)
    expect(notify).toHaveBeenCalledTimes(1)                       // creation alert
    const second = getDb().prepare("SELECT id, username FROM dashboard_users WHERE username = 'second'").get() as { id: number; username: string }
    const cookie = createSession({ userId: second.id, username: second.username })
    for (const [method, full] of ROUTES) {
      const out = await call(method, full, { cookie, auth: { kind: 'session', user: 'second' } })
      expect(out.res.statusCode, full).toBe(403)
    }
    expect(transfer.exportFleet).not.toHaveBeenCalled()
    expect(transfer.importFleet).not.toHaveBeenCalled()
  })
  it('the owner disabled: nobody passes (fail closed)', async () => {
    getDb().exec('UPDATE dashboard_users SET disabled = 1 WHERE id = 1')
    const { res } = await call('GET', '/api/fleet/export', { cookie: ownerCookie })
    expect(res.statusCode).toBe(403)
  })
})

describe('LOW (Viktor 2460): refusal alerts are rate limited per caller, audit rows are not', () => {
  it('one alert per caller per 10 minutes, every refusal audited', async () => {
    for (let i = 0; i < 5; i++) await call('GET', '/api/fleet/export', { auth: { kind: 'token', agent: 'dave' } })
    expect(notify).toHaveBeenCalledTimes(1)
    expect(auditRows()).toHaveLength(5)
    await call('GET', '/api/fleet/export', { auth: { kind: 'token', agent: 'mira' } })
    expect(notify).toHaveBeenCalledTimes(2)
  })
  it('the window reopens after 10 minutes', () => {
    expect(shouldAlertFleetDenial('x', 0)).toBe(true)
    expect(shouldAlertFleetDenial('x', 9 * 60_000)).toBe(false)
    expect(shouldAlertFleetDenial('x', 10 * 60_000)).toBe(true)
  })
})

describe('LOW (Viktor 2650): the alert window survives a dashboard restart', () => {
  const alertRows = () => getDb().prepare('SELECT actor, created_at FROM config_change_log WHERE key = ? ORDER BY id').all(FLEET_DENIED_ALERT_KEY) as Array<{ actor: string; created_at: number }>

  it('the window is kept in config_change_log, outside the security.fleet_* audit rows', async () => {
    await call('GET', '/api/fleet/export', { auth: { kind: 'token', agent: 'dave' } })
    expect(alertRows().map((r) => r.actor)).toEqual(['token:dave'])
    expect(auditRows()).toEqual([{ key: 'security.fleet_export_denied', actor: 'token:dave' }])
  })

  it('after a restart (no process state, only the DB) a second refusal inside the window does NOT alert, and is still audited', async () => {
    // What survives a restart is the DB alone: an alert row written five minutes ago by the previous process.
    const fiveMinAgo = Math.floor(Date.now() / 1000) - 5 * 60
    getDb().prepare('INSERT INTO config_change_log (key, old_value, new_value, actor, created_at) VALUES (?, NULL, NULL, ?, ?)')
      .run(FLEET_DENIED_ALERT_KEY, 'token:dave', fiveMinAgo)
    const { res } = await call('GET', '/api/fleet/export', { auth: { kind: 'token', agent: 'dave' } })
    expect(res.statusCode).toBe(403)
    expect(notify).not.toHaveBeenCalled()
    expect(auditRows()).toEqual([{ key: 'security.fleet_export_denied', actor: 'token:dave' }])
    expect(alertRows()).toHaveLength(1)
  })

  it('an alert row older than the window does not hold the next alert back', async () => {
    const elevenMinAgo = Math.floor(Date.now() / 1000) - 11 * 60
    getDb().prepare('INSERT INTO config_change_log (key, old_value, new_value, actor, created_at) VALUES (?, NULL, NULL, ?, ?)')
      .run(FLEET_DENIED_ALERT_KEY, 'token:dave', elevenMinAgo)
    await call('GET', '/api/fleet/export', { auth: { kind: 'token', agent: 'dave' } })
    expect(notify).toHaveBeenCalledTimes(1)
    expect(alertRows()).toHaveLength(2)
  })

  it('a caller that keeps trying is reported once per window, not only once', () => {
    // A refusal every 5 minutes for 30 minutes: alerts at 0, 10 and 20 minutes.
    const alerted = [0, 5, 10, 15, 20, 25].filter((m) => shouldAlertFleetDenial('loop', m * 60_000))
    expect(alerted).toEqual([0, 10, 20])
  })

  it('a row dated in the future does not silence the caller (Viktor 2680)', async () => {
    const inAYear = Math.floor(Date.now() / 1000) + 365 * 86400
    getDb().prepare('INSERT INTO config_change_log (key, old_value, new_value, actor, created_at) VALUES (?, NULL, NULL, ?, ?)')
      .run(FLEET_DENIED_ALERT_KEY, 'token:dave', inAYear)
    await call('GET', '/api/fleet/export', { auth: { kind: 'token', agent: 'dave' } })
    expect(notify).toHaveBeenCalledTimes(1)
  })

  it('the window is per caller', () => {
    expect(shouldAlertFleetDenial('a', 0)).toBe(true)
    expect(shouldAlertFleetDenial('b', 60_000)).toBe(true)
    expect(shouldAlertFleetDenial('a', 60_000)).toBe(false)
  })
})

describe('other paths are not handled', () => {
  it('returns false for a neighbouring path', async () => {
    const { handled } = await call('GET', '/api/fleet/other', { auth: { kind: 'token' } })
    expect(handled).toBe(false)
  })
})
