import { logger } from '../../logger.js'
import { readBody, json } from '../http-helpers.js'
import { exportFleet, importFleet, MIN_VAULT_PASSWORD_LEN, UserFacingError, type ExportedFleet } from '../fleet-transfer.js'
import { parseCookies, SESSION_COOKIE_NAME } from '../auth-gate.js'
import { resolveSession } from '../auth-sessions.js'
import { logConfigChange, getOwnerDashboardUser } from '../../db.js'
import { notifySecurityEvent } from '../../notify.js'
import type { RouteContext } from './types.js'

// FLEETEXPORT1013 (Viktor, HIGH; Klodel 2435): the export returns the whole
// Vault -- its master key included -- and the import rewrites it. Both were
// reachable with the fleet's shared Bearer token, i.e. by every agent. They
// now require the OWNER'S BROWSER SESSION (the mv_session cookie of a logged-in
// dashboard user), read from the cookie itself: a Bearer header in the same
// request (the dashboard UI adds one in token mode) wins the general auth
// gate, but neither grants nor blocks access here. Token, device, operator
// and federation credentials get 403. Every attempt, allowed or refused,
// writes an audit row (config_change_log); a refusal also alerts the owner.
// Only the OWNER's session counts (Viktor 2460): the first dashboard user this
// install created (db.ts getOwnerDashboardUser), not any logged-in user.
// Residual, stated:
//  - a token holder can still break-glass reset the owner's password
//    (auth.ts) and then log in -- that path alerts the owner on its own;
//  - an agent running under the SAME uid can write the SQLite file directly
//    (an auth_sessions row = a forged owner session). No route check can stop
//    that; the boundary is a separate uid for the dashboard (H1).
export function fleetOwnerSession(req: { headers: { cookie?: string } }): string | null {
  const cookie = parseCookies(req.headers.cookie)[SESSION_COOKIE_NAME]
  if (!cookie) return null
  const session = resolveSession(cookie)
  const owner = getOwnerDashboardUser()
  return session && owner && session.userId === owner.id ? session.username : null
}

// LOW (Viktor 2460): one refusal alert per caller per window, so a looping
// caller cannot flood the owner's Telegram. Every refusal is still audited.
const DENIED_ALERT_WINDOW_MS = 10 * 60_000
const lastDeniedAlert = new Map<string, number>()
export function shouldAlertFleetDenial(caller: string, nowMs: number): boolean {
  const last = lastDeniedAlert.get(caller)
  if (last !== undefined && nowMs - last < DENIED_ALERT_WINDOW_MS) return false
  lastDeniedAlert.set(caller, nowMs)
  return true
}
/** Test seam. */
export function _resetFleetDenialAlertsForTest(): void { lastDeniedAlert.clear() }

function callerLabel(auth: RouteContext['auth']): string {
  if (!auth) return 'none'
  if (auth.kind === 'token') return `token${auth.agent ? `:${auth.agent}` : ''}`
  if (auth.kind === 'device') return `device:${auth.device ?? '?'}`
  if (auth.kind === 'federation') return `federation:${auth.peer ?? '?'}`
  return `session:${auth.user ?? '?'}`
}

export async function tryHandleFleet(ctx: RouteContext): Promise<boolean> {
  const { req, res, path, method } = ctx

  if (path !== '/api/fleet/export' && path !== '/api/fleet/import') return false

  const op = path === '/api/fleet/export' ? 'export' : `import${ctx.url.searchParams.get('apply') === 'true' ? '_apply' : '_dryrun'}`
  const owner = fleetOwnerSession(req)
  if (!owner) {
    const caller = callerLabel(ctx.auth)
    logConfigChange(`security.fleet_${op}_denied`, null, method, caller)
    logger.warn({ path, method, caller }, 'fleet: refused -- owner browser session required (FLEETEXPORT1013)')
    if (shouldAlertFleetDenial(caller, Date.now())) void notifySecurityEvent(`🚨 Flotta-${op} kísérlet a dashboardon, ELUTASÍTVA (${caller}). Ez a teljes Vaultot adná ki vagy írná felül; csak a bejelentkezett tulajdonos böngészője hívhatja. Ha nem te voltál, szólj Viktornak.`)
    json(res, { error: 'A flotta export/import csak bejelentkezett tulajdonosi böngésző-sessionnel érhető el (a hozzáférési token nem elég).' }, 403)
    return true
  }
  logConfigChange(`security.fleet_${op}`, null, method, `session:${owner}`)
  logger.warn({ path, method, user: owner }, 'fleet: owner session access (FLEETEXPORT1013)')

  // H1: vault password via header, not query string (avoids access-log / proxy-log / browser-history leakage)
  const vaultPassword = req.headers['x-vault-password'] as string | undefined

  if (path === '/api/fleet/export' && method === 'GET') {
    if (vaultPassword !== undefined && vaultPassword.length < MIN_VAULT_PASSWORD_LEN) {
      json(res, { error: `X-Vault-Password must be at least ${MIN_VAULT_PASSWORD_LEN} characters.` }, 400)
      return true
    }
    try {
      const exported: ExportedFleet = exportFleet({ vaultPassword: vaultPassword || undefined })
      const buf = Buffer.from(exported.data)
      res.writeHead(200, {
        'Content-Type': 'application/json',
        'Content-Disposition': `attachment; filename="fleet-export-${exported.exportedAt.slice(0, 10)}.json"`,
        'Content-Length': buf.byteLength,
      })
      res.end(buf)
    } catch (err: any) {
      if (err instanceof UserFacingError) {
        json(res, { error: err.message }, 400)
      } else {
        logger.error({ err: err.message }, 'Fleet export failed')
        json(res, { error: `Export hiba: ${err.message}` }, 500)
      }
    }
    return true
  }

  if (path === '/api/fleet/import' && method === 'POST') {
    const apply = ctx.url.searchParams.get('apply') === 'true'

    // M1: check vault password length for import side too
    if (vaultPassword !== undefined && vaultPassword.length < MIN_VAULT_PASSWORD_LEN) {
      json(res, { error: `X-Vault-Password must be at least ${MIN_VAULT_PASSWORD_LEN} characters.` }, 400)
      return true
    }

    let rawBody: string
    try {
      const buf = await readBody(req)
      rawBody = buf.toString()
    } catch (err: any) {
      json(res, { error: `Kérés olvasási hiba: ${err.message}` }, 400)
      return true
    }

    // importFleet handles JSON parse (and encrypted blob detection) internally
    try {
      const result = importFleet(rawBody, { vaultPassword: vaultPassword || undefined, apply })
      if ('dryRun' in result && result.errors.length > 0) {
        json(res, result, 400)
      } else {
        json(res, result, 200)
      }
    } catch (err: any) {
      logger.error({ err: err.message }, 'Fleet import failed')
      json(res, { error: `Import hiba: ${err.message}` }, 500)
    }
    return true
  }

  return false
}
