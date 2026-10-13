import { json, methodNotAllowed } from '../http-helpers.js'
import { PROJECT_ROOT } from '../../config.js'
import { readEnvFile } from '../../env.js'
import { logger } from '../../logger.js'
import { listCompanies, loadAll, renderFinancePage, resolveFinanceRoot, type Lang, type Theme } from '../finance.js'
import { kindAllowed, FORBIDDEN_KIND } from './auth.js'
import type { RouteContext } from './types.js'

// FINANCETAB1013 routes: the read-only finance view on the dashboard.
//
// Who may read it: a logged-in dashboard user ('session') whose username is
// on FINANCE_USERS. Everything else is a 403, fail-closed (a missing auth, an
// unknown kind, an empty or unset FINANCE_USERS included).
//
// What this gate is worth, stated precisely (Viktor, msg 1868 F1), so nobody
// reads more into it:
//   - It refuses every credential that lives OFF this machine: a device key,
//     an operator (Bridge) session, which resolves as 'device', and a
//     federation peer.
//   - It refuses the shared fleet 'token', so a routine agent curl does not
//     get the data. /api/* auth is one shared Bearer token that every
//     sub-agent reads out of store/.dashboard-token.
//   - It does NOT stop a determined local agent. The fleet token may create a
//     dashboard user (USER_ADMIN_KINDS in auth.ts); FINANCE_USERS is what keeps
//     such a new user out. But store/claudeclaw.db and the CSVs under
//     FINANCE_DIR are writable/readable by the same UNIX user every agent runs
//     as. Hiding the data from local agents would need OS-level separation.
//
// /api/finance/config answers only whether the feature is on (to reveal the
// sidebar link), so any authenticated caller may ask it.
const FINANCE_VIEW_KINDS = ['session'] as const

// Second layer, after the dashboard's <iframe sandbox="" srcdoc>. NOTE: a
// srcdoc document does not get this header (it inherits the parent's policy),
// which is why the document carries its own <meta> CSP (FINANCE_DOC_CSP) and
// why output encoding is the part that carries the load (finance.ts header).
// The header still covers a direct load of the URL.
const VIEW_HEADERS = {
  'Content-Type': 'text/html; charset=utf-8',
  'Cache-Control': 'private, no-store',
  'X-Content-Type-Options': 'nosniff',
  'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'",
  'Referrer-Policy': 'no-referrer',
} as const

/** Read per request: the .env is the source (launchd does not pass it in env). */
function financeConfig(): { root: string | null; users: Set<string> } {
  const env = readEnvFile(['FINANCE_DIR', 'FINANCE_USERS'])
  const users = new Set((env['FINANCE_USERS'] ?? '').split(',').map((u) => u.trim()).filter(Boolean))
  return { root: resolveFinanceRoot(env['FINANCE_DIR'], PROJECT_ROOT), users }
}

export async function tryHandleFinance(ctx: RouteContext): Promise<boolean> {
  const { res, path, method, url } = ctx

  if (path === '/api/finance/config') {
    if (method !== 'GET') { methodNotAllowed(res, method, ['GET']); return true }
    const cfg = financeConfig()
    json(res, { enabled: cfg.root !== null && cfg.users.size > 0 })
    return true
  }

  if (path === '/api/finance/view') {
    if (method !== 'GET' && method !== 'HEAD') { methodNotAllowed(res, method, ['GET', 'HEAD']); return true }
    // Caller gate BEFORE anything else, so a fleet-token holder cannot even
    // learn whether the feature is configured from a 404/403 difference.
    if (!kindAllowed(ctx.auth, FINANCE_VIEW_KINDS)) {
      json(res, FORBIDDEN_KIND, 403)
      return true
    }
    const cfg = financeConfig()
    const user = ctx.auth?.user ?? ''
    if (!user || !cfg.users.has(user)) {
      logger.warn({ user }, 'finance view refused: user not on FINANCE_USERS')
      json(res, { error: 'Forbidden for this user' }, 403)
      return true
    }
    if (!cfg.root) { json(res, { error: 'finance_disabled' }, 404); return true }
    const lang: Lang = url.searchParams.get('lang') === 'en' ? 'en' : 'hu'
    const theme: Theme = url.searchParams.get('theme') === 'dark' ? 'dark' : 'light'
    const html = renderFinancePage(loadAll(cfg.root), { lang, theme })
    // Who opened which companies, never what it showed (F5).
    logger.info({ user, companies: listCompanies(cfg.root) }, 'finance view served')
    res.writeHead(200, VIEW_HEADERS)
    res.end(method === 'HEAD' ? undefined : html)
    return true
  }

  return false
}
