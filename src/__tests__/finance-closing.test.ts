// HAVIZARAS1016: the monthly closing view of the finance tab. It reads the
// finance agent's <FINANCE_DIR>/zaras/<company>/<YYYY-MM>.json files with the
// same reader rules as the rest of the tab (no symlink, size cap, fixed name
// patterns) and renders into the same sandboxed srcdoc iframe, so the same
// three risks are pinned: the caller gate, the files, and the output encoding.
// Plus the contract points: an unknown number is "not known", never 0; the
// "needs you" box holds only what waits on Patrik; a month without a file is
// "no data", not "not started".
import { describe, it, expect, vi } from 'vitest'
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, realpathSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { tmpdir } from 'node:os'

const base = realpathSync(mkdtempSync(join(tmpdir(), 'marveen-closing-test-')))
const root = join(base, 'penzugy')
const zaras = join(root, 'zaras')
const outside = join(base, 'outside')
const projectRoot = join(base, 'project')
for (const d of [join(root, 'acme'), join(root, 'beta'), join(zaras, 'acme'), join(zaras, 'beta'), outside, projectRoot]) mkdirSync(d, { recursive: true })

// Synthetic data only.
writeFileSync(join(root, 'acme', 'meta.json'), JSON.stringify({ ceg: 'Acme Kft.' }))
const september = {
  schema: 'zaras-allapot/v1', ceg: 'acme', ceg_nev: 'Acme (fájlból)', honap: '2026-09', frissitve: '2026-10-16T14:05:00+02:00', frissitette: 'juro',
  allapot: 'FOLYAMATBAN', allapot_szoveg: 'párosítás folyik',
  hatarido: { datum: '2026-10-10', mire: 'csomag Heninek', forras: 'README' },
  elkuldve: null,
  kivonatok: [{ szamla: 'Bank HUF', megvan: true, teljes: true, megjegyzes: '009' }, { szamla: 'Bank EUR', megvan: false, teljes: null }],
  terhelesek: { osszes_db: 42, osszes_ft: 1234567, szamlaval_db: 30, szamlaval_ft: 1100000, nem_kell_db: 8, nem_kell_ft: 100000, hianyzik_db: 4, hianyzik_ft: 34567 },
  bevetel: { billingo_db: 3, billingo_netto_ft: 5245000, billingo_brutto_ft: 6661150, rendben: true, megjegyzes: '' },
  nav: { kimeno: { db: 3, netto_ft: 5245000, afa_ft: 1416150, elteres_netto_ft: 0 }, bejovo: { db: null, netto_ft: null, afa_ft: null }, lekerdezve: '2026-10-16T13:38:00+02:00' },
  hianyok: [
    { id: 'h1', datum: '2026-09-03', szallito: 'Felhő Zrt.', osszeg: 20, penznem: 'USD', osszeg_ft: 6500, ok: 'patrikra_var', teendo: 'Admin: számla letöltése', kie: 'patrik', patrikra_var: true },
    { id: 'h2', datum: '2026-09-12', szallito: 'Papír Bt.', osszeg: 12000, penznem: 'HUF', osszeg_ft: 12000, ok: 'papir', teendo: 'szkennelés', kie: 'juro', patrikra_var: false },
    { id: 'h3', datum: '2026-09-20', szallito: 'Távoli Inc.', osszeg: 9.99, penznem: 'EUR', osszeg_ft: null, ok: 'szolgaltatotol_kertuk', kie: 'szolgaltato', patrikra_var: false },
    { id: 'h4', datum: '2026-09-21', szallito: 'Csapat Kft.', osszeg: null, penznem: null, osszeg_ft: null, ok: 'csapat_dolgozik', patrikra_var: false },
  ],
  ki_dolgozik: [{ ki: 'juro', min: 'felhő-számlák' }],
  forrasok: ['~/Konyveles/acme/2026-09/parositas.md'],
  ismeretlen_kulcs: 'NEM JELENHET MEG',
}
writeFileSync(join(zaras, 'acme', '2026-09.json'), JSON.stringify(september))
writeFileSync(join(zaras, 'acme', '2026-08.json'), JSON.stringify({
  schema: 'zaras-allapot/v1', ceg: 'acme', honap: '2026-08', allapot: 'KESZ', elkuldve: { datum: '2026-09-15' }, hatarido: { datum: '2026-09-15' },
  terhelesek: { osszes_db: 30, szamlaval_db: 30, nem_kell_db: 0, hianyzik_db: 0 }, hianyok: [],
}))
writeFileSync(join(zaras, 'beta', '2026-09.json'), JSON.stringify({
  schema: 'zaras-allapot/v1', ceg: 'beta', honap: '2026-09', allapot: 'csomagolas', hatarido: { datum: 'holnap' },
  terhelesek: { osszes_db: -1, szamlaval_db: 2.5, osszes_ft: '100' }, bevetel: { rendben: 'igen' },
  hianyok: [{ szallito: 'X', ok: 'valami', osszeg_ft: 1, penznem: 'forint', patrikra_var: 'igen' }],
}))
writeFileSync(join(zaras, 'beta', '2026-08.json'), '{nem json')
writeFileSync(join(zaras, 'beta', 'jegyzet.txt'), 'nem hónapfájl, nem olvassuk')

const envValues: Record<string, string> = { FINANCE_DIR: root, FINANCE_USERS: 'patrik' }
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

const { listCompanies, companyNames } = await import('../web/finance.js')
const { loadClosing, renderClosingPage, monthRange, previousMonth, CLOSING_MAX_FILE_BYTES } = await import('../web/finance-closing.js')
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

const TODAY = '2026-10-16'

describe('the closing folder is not a company', () => {
  it('listCompanies skips it, so the overview does not show it as a company section', () => {
    expect(listCompanies(root)).toEqual(['acme', 'beta'])
  })
})

describe('months', () => {
  it('previousMonth and monthRange cross the year boundary', () => {
    expect(previousMonth('2026-10-16')).toBe('2026-09')
    expect(previousMonth('2027-01-05')).toBe('2026-12')
    expect(monthRange('2026-11', '2027-02')).toEqual(['2026-11', '2026-12', '2027-01', '2027-02'])
  })
  it('the grid runs from 2026-07 to last month, even where no file exists', () => {
    expect(loadClosing(root, TODAY).months).toEqual(['2026-07', '2026-08', '2026-09'])
  })
  it('a file with an odd month name cannot push the current months out of the grid (Viktor 6826 L1)', () => {
    const r = join(base, 'oddmonths')
    mkdirSync(join(r, 'zaras', 'acme'), { recursive: true })
    for (const m of ['0001-01', '9999-12', '2026-11', '2026-09']) {
      writeFileSync(join(r, 'zaras', 'acme', `${m}.json`), JSON.stringify({ schema: 'zaras-allapot/v1', allapot: 'KESZ' }))
    }
    const d = loadClosing(r, TODAY)
    expect(d.months).toEqual(['2026-07', '2026-08', '2026-09'])
    expect(d.cells.has('acme\u00002026-09')).toBe(true)
    expect(d.fileErrors.map((e) => e.month).sort()).toEqual(['0001-01', '2026-11', '9999-12'])
    expect(d.fileErrors[0]!.error).toContain('tartományon kívül')
    // An old but in-window file still extends the grid backwards, never past 24 months.
    writeFileSync(join(r, 'zaras', 'acme', '2024-11.json'), JSON.stringify({ schema: 'zaras-allapot/v1', allapot: 'KESZ' }))
    const d2 = loadClosing(r, TODAY)
    expect(d2.months[0]).toBe('2024-11')
    expect(d2.months[d2.months.length - 1]).toBe('2026-09')
    expect(d2.months.length).toBeLessThanOrEqual(24)
  })
  it('a newer file extends the grid', () => {
    const r = join(base, 'newer')
    mkdirSync(join(r, 'zaras', 'acme'), { recursive: true })
    writeFileSync(join(r, 'zaras', 'acme', '2026-10.json'), JSON.stringify({ schema: 'zaras-allapot/v1', allapot: 'FOLYAMATBAN' }))
    expect(loadClosing(r, TODAY).months).toEqual(['2026-07', '2026-08', '2026-09', '2026-10'])
  })
})

describe('loading', () => {
  const data = loadClosing(root, TODAY)
  const sep = data.cells.get('acme\u00002026-09')!
  const bad = data.cells.get('beta\u00002026-09')!
  it('reads the fields', () => {
    expect(sep.status).toBe('FOLYAMATBAN')
    expect(sep.charges).toEqual({ totalDb: 42, totalFt: 1234567, invoicedDb: 30, invoicedFt: 1100000, notNeededDb: 8, notNeededFt: 100000, missingDb: 4, missingFt: 34567 })
    expect(sep.statements).toEqual([{ account: 'Bank HUF', has: true, complete: true, note: '009' }, { account: 'Bank EUR', has: false, complete: null, note: '' }])
    expect(sep.missing.map((m) => m.reason)).toEqual(['patrikra_var', 'papir', 'szolgaltatotol_kertuk', 'csapat_dolgozik'])
    expect(sep.missing.map((m) => m.waitsOnPatrik)).toEqual([true, false, false, false])
    expect(sep.nav.out).toEqual({ db: 3, netFt: 5245000, vatFt: 1416150, diffNetFt: 0, ownGrossFt: null, diffGrossFt: null })
    expect(sep.errors).toEqual([])
  })
  it('an unknown amount is null, never 0', () => {
    expect(sep.missing[2]!.amountFt).toBeNull()
    expect(sep.missing[3]!.amount).toBeNull()
    expect(data.cells.get('acme\u00002026-08')!.charges.totalFt).toBeNull()
  })
  it('invalid values are dropped and named, not guessed; patrikra_var is only an explicit true', () => {
    expect(bad.status).toBe('ismeretlen')
    expect(bad.deadline).toEqual({ date: null, what: '', source: '', guess: false })
    expect(bad.charges.totalDb).toBeNull()
    expect(bad.charges.invoicedDb).toBeNull()
    expect(bad.charges.totalFt).toBeNull()
    expect(bad.income.ok).toBeNull()
    expect(bad.missing[0]!.reason).toBe('ismeretlen')
    expect(bad.missing[0]!.currency).toBe('')
    expect(bad.missing[0]!.waitsOnPatrik).toBe(false)
    expect(bad.errors).toEqual(expect.arrayContaining([
      'allapot: ismeretlen érték', 'hatarido.datum: nem ÉÉÉÉ-HH-NN dátum', 'terhelesek.osszes_db: nem egész szám', 'hianyok[0].ok: ismeretlen érték',
    ]))
  })
  it('an unparsable file is a file error, a non-month name is not read', () => {
    expect(data.cells.has('beta\u00002026-08')).toBe(false)
    expect(data.fileErrors).toEqual([{ company: 'beta', month: '2026-08', error: 'nem érvényes JSON' }])
  })
  it('the v1 additions: NAV amounts with fillér round to forints, deadline guess, sender, own list, notes', () => {
    const r = join(base, 'v1add')
    mkdirSync(join(r, 'zaras', 'acme'), { recursive: true })
    writeFileSync(join(r, 'zaras', 'acme', '2026-09.json'), JSON.stringify({
      schema: 'zaras-allapot/v1', allapot: 'KESZ',
      hatarido: { datum: '2026-10-12', mire: 'csomag', tipp: true }, elkuldve: { datum: '2026-10-13', ki: 'Eszter' },
      nav: { bejovo: { db: 26, netto_ft: 803393.25, afa_ft: 96475.5, sajat_brutto_ft: 899868.59, elteres_brutto_ft: -1.4 } },
      megjegyzesek: ['egy eltérés', 7, ''],
    }))
    const c = loadClosing(r, TODAY).cells.get('acme\u00002026-09')!
    expect(c.errors).toEqual([])
    expect(c.nav.in).toEqual({ db: 26, netFt: 803393, vatFt: 96476, diffNetFt: null, ownGrossFt: 899869, diffGrossFt: -1 })
    expect(c.deadline!.guess).toBe(true)
    expect(c.sent).toEqual({ date: '2026-10-13', by: 'Eszter', source: '' })
    expect(c.notes).toEqual(['egy eltérés'])
    const out = renderClosingPage(loadClosing(r, TODAY), new Map(), { lang: 'hu', theme: 'light', today: TODAY })
    expect(out).toContain('2026-10-12 [tipp] (csomag)')
    expect(out).toContain('2026-10-13 (küldte: Eszter)')
    expect(out).toMatch(/<dd class="zloud">bejövő: 26 számla, nettó 803.393 Ft, áfa 96.476 Ft, saját lista bruttó 899.869 Ft \(ELTÉRÉS -1 Ft\)/)
    expect(out).toContain('<dt>Megjegyzések</dt><dd>egy eltérés</dd>')
  })
  it('a wrong schema string is reported', () => {
    const r = join(base, 'oldschema')
    mkdirSync(join(r, 'zaras', 'acme'), { recursive: true })
    writeFileSync(join(r, 'zaras', 'acme', '2026-09.json'), JSON.stringify({ schema: 1, allapot: 'KESZ' }))
    expect(loadClosing(r, TODAY).cells.get('acme\u00002026-09')!.errors).toContain('schema: nem zaras-allapot/v1')
  })
})

describe('containment', () => {
  it('a symlinked closing folder, company folder or month file is not followed', () => {
    writeFileSync(join(outside, '2026-09.json'), JSON.stringify({ ...september, hianyok: [{ szallito: 'KÍVÜLRŐL', ok: 'papir' }] }))
    const r1 = join(base, 'linkroot1')
    mkdirSync(r1)
    symlinkSync(outside, join(r1, 'zaras'))
    expect(loadClosing(r1, TODAY).present).toBe(false)

    const r2 = join(base, 'linkroot2')
    mkdirSync(join(r2, 'zaras'), { recursive: true })
    symlinkSync(outside, join(r2, 'zaras', 'acme'))
    expect(loadClosing(r2, TODAY).companies).toEqual([])

    const r3 = join(base, 'linkroot3')
    mkdirSync(join(r3, 'zaras', 'acme'), { recursive: true })
    symlinkSync(join(outside, '2026-09.json'), join(r3, 'zaras', 'acme', '2026-09.json'))
    const d3 = loadClosing(r3, TODAY)
    expect(d3.cells.size).toBe(0)
    expect(d3.fileErrors).toEqual([{ company: 'acme', month: '2026-09', error: 'nem olvasható (not_regular)' }])
  })
  it('an oversized file is refused', () => {
    const r = join(base, 'bigroot')
    mkdirSync(join(r, 'zaras', 'acme'), { recursive: true })
    writeFileSync(join(r, 'zaras', 'acme', '2026-09.json'), JSON.stringify({ schema: 1, x: 'a'.repeat(CLOSING_MAX_FILE_BYTES) }))
    expect(loadClosing(r, TODAY).fileErrors[0]!.error).toBe('nem olvasható (too_large)')
  })
})

describe('rendering', () => {
  const html = renderClosingPage(loadClosing(root, TODAY), companyNames(root), { lang: 'hu', theme: 'light', today: TODAY })
  const yours = html.slice(html.indexOf('class="zyours'), html.indexOf('</div>', html.indexOf('class="zyours')))
  it('the "needs you" box holds only the items flagged patrikra_var', () => {
    expect(yours).toContain('TŐLED KELL (1)')
    expect(yours).toContain('Felhő Zrt., 2026-09-03, 6')
    expect(yours).toContain('(20 USD)')
    expect(yours).toContain('Admin: számla letöltése')
    expect(yours).not.toContain('Papír Bt.')
    expect(yours).not.toContain('Távoli Inc.')
  })
  it('the grid: company names, status, invoiced of needed, missing, missing statement, overdue; no file is "no data"', () => {
    expect(html).toContain('<th>Acme Kft.</th>')
    expect(html).toContain('<th>beta</th>')
    expect(html).toContain('FOLYAMATBAN')
    expect(html).toContain('30/34 számlával')
    expect(html).toContain('<strong>4 hiányzik</strong>')
    expect(html).toContain('<span class="zst z-late">1 rád vár</span>')
    expect(html).toContain('<strong>Bankkivonat: HIÁNYZIK</strong>')
    expect(html).toContain('lejárt')
    expect(html).toContain('Heninek elküldve: 2026-09-15')
    expect(html).toContain('nincs adat')
  })
  it('details: unknown amounts read "no data" or the original currency, never 0 Ft; NAV and income lines; unknown keys do not show', () => {
    expect(html).toContain('<td class="num">9,99 EUR</td>')
    expect(html).toContain('<td class="num unk">nincs adat</td>')
    expect(html).not.toContain('>0 Ft<')
    expect(html).toContain('kimenő: 3 számla')
    expect(html).toContain('egyezik')
    expect(html).toContain('rendben · 3 számla')
    expect(html).not.toContain('NEM JELENHET MEG')
    expect(html).toContain('<details class="zmonth">')
  })
  it('a NAV difference is loud, and an empty "needs you" box says so', () => {
    const r = join(base, 'calm')
    mkdirSync(join(r, 'zaras', 'acme'), { recursive: true })
    writeFileSync(join(r, 'zaras', 'acme', '2026-09.json'), JSON.stringify({
      schema: 'zaras-allapot/v1', allapot: 'KESZ', elkuldve: { datum: '2026-10-05' }, nav: { kimeno: { db: 2, netto_ft: 10, elteres_netto_ft: -3 } },
    }))
    const out = renderClosingPage(loadClosing(r, TODAY), new Map(), { lang: 'hu', theme: 'dark', today: TODAY })
    expect(out).toContain('Most nincs rád váró tétel.')
    expect(out).toMatch(/<dd class="zloud">kimenő: 2 számla, nettó 10 Ft, ELTÉRÉS -3 Ft/)
  })
  it('English labels exist for the same page, and no folder means a plain note', () => {
    const en = renderClosingPage(loadClosing(root, TODAY), companyNames(root), { lang: 'en', theme: 'light', today: TODAY })
    expect(en).toContain('NEEDS YOU')
    expect(en).toContain('IN PROGRESS')
    expect(renderClosingPage(loadClosing(outside, TODAY), new Map(), { lang: 'hu', theme: 'light', today: TODAY })).toContain('Még nincs zárási állapotfájl')
  })
})

describe('rendering: output encoding (F3)', () => {
  const HOSTILE = [
    '<img src=//x.example/?leak>',
    '"><svg onload=alert(1)>',
    '</style><img src=x>',
    "' onmouseover='x",
    'a{background:url(//x.example/p)}',
  ]
  const evil = join(base, 'evilroot')
  mkdirSync(join(evil, 'zaras', 'co'), { recursive: true })
  mkdirSync(join(evil, 'co'), { recursive: true })
  writeFileSync(join(evil, 'co', 'meta.json'), JSON.stringify({ nev: HOSTILE[0] }))
  writeFileSync(join(evil, 'zaras', 'co', '2026-09.json'), JSON.stringify({
    schema: 'zaras-allapot/v1', ceg_nev: HOSTILE[2], allapot: HOSTILE[1], allapot_szoveg: HOSTILE[0], frissitve: HOSTILE[2], frissitette: HOSTILE[3],
    hatarido: { datum: HOSTILE[0], mire: HOSTILE[1], forras: HOSTILE[2] }, elkuldve: { datum: HOSTILE[3] },
    kivonatok: HOSTILE.map((h) => ({ szamla: h, megvan: false, megjegyzes: h })),
    bevetel: { rendben: false, megjegyzes: HOSTILE[1] },
    nav: { kimeno: { db: 1, netto_ft: 2, elteres_netto_ft: -5 }, lekerdezve: HOSTILE[4] },
    hianyok: HOSTILE.map((h) => ({ id: h, szallito: h, datum: h, osszeg_ft: 7, penznem: h, ok: 'patrikra_var', teendo: h, kie: h, patrikra_var: true })),
    ki_dolgozik: HOSTILE.map((h) => ({ ki: h, min: h })),
    forrasok: HOSTILE,
  }))
  writeFileSync(join(evil, 'zaras', 'co', '2026-08.json'), HOSTILE[0]!)
  for (const lang of ['hu', 'en'] as const) {
    const out = renderClosingPage(loadClosing(evil, TODAY), companyNames(evil), { lang, theme: 'light', today: TODAY })
    it(`${lang}: no hostile value becomes markup`, () => {
      const tags = out.match(/<[^>]*>/g) ?? []
      const names = new Set(tags.map((t) => /^<\/?([a-z0-9]+)/i.exec(t)?.[1]?.toLowerCase() ?? '?'))
      for (const n of names) {
        expect(['!doctype', 'html', 'head', 'meta', 'title', 'style', 'body', 'section', 'h2', 'h3', 'p', 'div', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
          'h4', 'details', 'summary', 'span', 'strong', 'dl', 'dt', 'dd', 'ul', 'li']).toContain(n === '?' ? '!doctype' : n)
      }
      for (const t of tags) {
        expect(t).not.toMatch(/\son\w+\s*=/i)
        expect(t).not.toMatch(/\b(src|href|xlink:href|action|formaction|background|style)\s*=/i)
        expect(t).not.toMatch(/(https?:)?\/\//i)
      }
      expect(out.match(/<\/style>/g)).toHaveLength(1)
      const css = out.slice(out.indexOf('<style>'), out.indexOf('</style>'))
      expect(css).not.toMatch(/url\(|@import/i)
    })
    it(`${lang}: the hostile text is still visible, escaped, and the rows were shown`, () => {
      expect(out).toContain('&lt;img src=//x.example/?leak&gt;')
      expect(out).toContain('&quot;&gt;&lt;svg onload=alert(1)&gt;')
      expect(out).toContain('<td class="num">7 Ft')
    })
  }
})

describe('the route', () => {
  it('?view=zaras serves the closing view to a listed session, and logs the view', async () => {
    logged.length = 0
    const { ctx, out } = fakeCtx('/api/finance/view?view=zaras', { kind: 'session', user: 'patrik' })
    await tryHandleFinance(ctx)
    expect(out.status).toBe(200)
    expect(out.headers['Cache-Control']).toBe('private, no-store')
    expect(out.headers['Content-Security-Policy']).toContain("default-src 'none'")
    expect(out.body).toContain('TŐLED KELL')
    expect(logged).toEqual([['info', { user: 'patrik', view: 'zaras', companies: ['acme', 'beta'] }, 'finance view served']])
  })
  it('the caller gate is the same: the fleet token, a device and an unlisted user get 403', async () => {
    for (const auth of [{ kind: 'token' }, { kind: 'device' }, { kind: 'session', user: 'mallory' }, undefined]) {
      const { ctx, out } = fakeCtx('/api/finance/view?view=zaras', auth as RouteContext['auth'])
      await tryHandleFinance(ctx)
      expect(out.status).toBe(403)
      expect(out.body).not.toContain('Felhő Zrt.')
    }
  })
})

describe('the dashboard side (static contract)', () => {
  const app = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'web', 'app.js'), 'utf8')
  const index = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'web', 'index.html'), 'utf8')
  it('only the three known view values reach the URL, and the tab button exists', () => {
    expect(app).toContain("financeView = v === 'elofizetesek' || v === 'zaras' ? v : 'overview'")
    expect(app).toContain('&view=${financeView}')
    expect(index).toContain('data-finance-view="zaras"')
  })
})
