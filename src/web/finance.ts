// FINANCETAB1013: the read-only finance view (monthly cash-basis P&L, forecast,
// bank balance projection, per-product worst-case cost) rendered from CSV files
// a finance agent drops under FINANCE_DIR. Pure core: file loading, parsing,
// validation and HTML rendering. The route (routes/finance.ts) only gates the
// caller and writes the response. Format: docs/penzugy-ful.md.
//
// Layout under the root (one directory per company, fixed file names):
//   <root>/<company>/pnl.csv                    honap,kategoria,osszeg_huf,tipus[,jeloles,forras]
//   <root>/<company>/elorejelzes.csv            honap,kategoria,osszeg_huf,forgatokonyv[,tipus,jeloles]
//   <root>/<company>/bank_projekcio.csv         datum,szamla_alias,egyenleg_huf,tenyleges[,forgatokonyv,esemeny]
//   <root>/<company>/marabel_termek_koltseg.csv termek,tetel,osszeg_huf_per_egyseg,forgatokonyv
//   <root>/<company>/meta.json                  see readMeta
// Every file is optional; a missing file is a missing section, not an error.
//
// The data is sensitive, so the reader is strict and small:
//   - the root is realpath'd once; company directories are plain directories
//     directly under it (a symlinked directory is skipped, not followed);
//   - files are opened with O_NOFOLLOW and must be regular files <= 1 MB;
//   - only the fixed file names above are read, nothing is listed recursively;
//   - every cell is length-capped and the row count is capped.
//
// Output encoding is the part that carries the load (Viktor, msg 1868 F3). The
// dashboard puts this HTML into an <iframe sandbox="" srcdoc>, which blocks
// script, forms and navigation but NOT resource loads, and the srcdoc inherits
// the parent's policy, not this response's CSP header. The cells come from the
// finance agent's sources, ultimately external data, so an injected
// <img src=//host/?data> would leak from the browser. Therefore: every text
// value goes through escapeHtml (also inside attributes), every SVG coordinate
// is a checked finite number, the page carries no link or URL of its own, and
// the document has its own <meta> CSP with no image, font or connect source.

import { closeSync, constants, fstatSync, lstatSync, openSync, readFileSync, readdirSync, realpathSync, statSync } from 'node:fs'
import { isAbsolute, join, resolve } from 'node:path'

export const FINANCE_MAX_FILE_BYTES = 1024 * 1024
export const FINANCE_MAX_ROWS = 5000
export const FINANCE_MAX_COMPANIES = 10
export const FINANCE_MAX_CELL = 200
const MAX_ERRORS_PER_FILE = 10
const MAX_META_TEXT = 1000

const COMPANY_RE = /^[a-z0-9_-]{1,32}$/
const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/
const DATE_RE = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/
const AMOUNT_RE = /^-?\d{1,15}$/

/** The document's own policy: no script, no image/font/connect, no base, no form. */
export const FINANCE_DOC_CSP = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"

export type Lang = 'hu' | 'en'
export type Theme = 'light' | 'dark'
export type Kind = 'bevetel' | 'koltseg' | 'nem_eredmeny'

export interface PnlRow { month: string; category: string; amount: number; kind: Kind; estimate: boolean; source: string }
export interface ForecastRow { month: string; category: string; amount: number; scenario: string; kind: Kind | null; estimate: boolean }
export interface BankRow { date: string; account: string; balance: number; actual: boolean; scenario: string; event: string }
export interface ProductCostRow { product: string; item: string; amount: number; scenario: string; estimate: boolean }
export interface Meta {
  name: string | null
  generated: string | null
  currency: string | null
  basis: string | null
  sources: string[]
  note: string | null
  forecastMethod: string | null
  missingMonths: string[]
  overrides: Array<{ key: string; reason: string }>
  notIncluded: string[]
  warnings: string[]
  unclassified: number | null
}

export interface FileResult<T> { present: boolean; rows: T[]; errors: string[] }

export interface CompanyData {
  id: string
  meta: Meta
  metaErrors: string[]
  pnl: FileResult<PnlRow>
  forecast: FileResult<ForecastRow>
  bank: FileResult<BankRow>
  productCost: FileResult<ProductCostRow>
}

/** FINANCE_DIR from the .env, resolved and realpath'd; null when unset or not a directory. */
export function resolveFinanceRoot(configured: string | undefined, projectRoot: string): string | null {
  const raw = (configured ?? '').trim()
  if (!raw) return null
  const abs = isAbsolute(raw) ? raw : resolve(projectRoot, raw)
  try {
    const real = realpathSync(abs)
    return statSync(real).isDirectory() ? real : null
  } catch {
    return null
  }
}

/** The subscriptions view's directory under the root (ELOFIZETES1014). It is not a company. */
export const SUBSCRIPTIONS_DIR = 'elofizetesek'

/** Company directory names: plain directories directly under the root, sorted, capped. */
export function listCompanies(root: string): string[] {
  let entries
  try {
    entries = readdirSync(root, { withFileTypes: true })
  } catch {
    return []
  }
  return entries
    .filter((e) => e.isDirectory() && COMPANY_RE.test(e.name) && e.name !== SUBSCRIPTIONS_DIR)
    .map((e) => e.name)
    .sort()
    .slice(0, FINANCE_MAX_COMPANIES)
}

export type ReadResult = { ok: true; text: string } | { ok: false; reason: 'missing' | 'not_regular' | 'too_large' | 'unreadable' }

/** Read one fixed-name file: no symlink, regular file only, size-capped. */
export function readCapped(path: string, maxBytes = FINANCE_MAX_FILE_BYTES): ReadResult {
  let fd: number
  try {
    fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW)
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code
    if (code === 'ENOENT') return { ok: false, reason: 'missing' }
    // ELOOP is what O_NOFOLLOW gives for a symlink.
    if (code === 'ELOOP') return { ok: false, reason: 'not_regular' }
    return { ok: false, reason: 'unreadable' }
  }
  try {
    const st = fstatSync(fd)
    if (!st.isFile()) return { ok: false, reason: 'not_regular' }
    if (st.size > maxBytes) return { ok: false, reason: 'too_large' }
    return { ok: true, text: readFileSync(fd, 'utf8') }
  } catch {
    return { ok: false, reason: 'unreadable' }
  } finally {
    closeSync(fd)
  }
}

/**
 * Minimal RFC 4180 CSV parser. The delimiter is ';' when the header line has a
 * ';' and no ',' (a Hungarian Excel export), ',' otherwise. A leading BOM is
 * dropped, CRLF and LF both end a record, and quoted fields may hold the
 * delimiter, newlines and doubled quotes. Values are data only: nothing is
 * evaluated, and a formula-looking cell stays a string.
 */
export function parseCsv(text: string): string[][] {
  const src = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text
  const firstLine = src.split(/\r?\n/, 1)[0] ?? ''
  const delim = firstLine.includes(';') && !firstLine.includes(',') ? ';' : ','
  const rows: string[][] = []
  let row: string[] = []
  let cell = ''
  let quoted = false
  let i = 0
  while (i < src.length) {
    const ch = src[i]!
    if (quoted) {
      if (ch === '"') {
        if (src[i + 1] === '"') { cell += '"'; i += 2; continue }
        quoted = false; i++; continue
      }
      cell += ch; i++; continue
    }
    if (ch === '"' && cell === '') { quoted = true; i++; continue }
    if (ch === delim) { row.push(cell); cell = ''; i++; continue }
    if (ch === '\r' && src[i + 1] === '\n') { i++; continue }
    if (ch === '\n') {
      row.push(cell); rows.push(row); row = []; cell = ''; i++; continue
    }
    cell += ch; i++
  }
  if (cell !== '' || row.length > 0) { row.push(cell); rows.push(row) }
  return rows.filter((r) => !(r.length === 1 && r[0]!.trim() === ''))
}

type Cells = Record<string, string>
type RowMapper<T> = (c: Cells, line: number, errors: string[]) => T | null

function cap(s: string, max = FINANCE_MAX_CELL): string {
  const t = s.trim()
  return t.length > max ? t.slice(0, max) + '…' : t
}

function pushErr(errors: string[], msg: string): void {
  if (errors.length < MAX_ERRORS_PER_FILE) errors.push(msg)
  else if (errors.length === MAX_ERRORS_PER_FILE) errors.push('…')
}

function amount(raw: string, field: string, line: number, errors: string[]): number | null {
  const v = raw.trim().replace(/[\s ]/g, '')
  if (!AMOUNT_RE.test(v)) { pushErr(errors, `${line}. sor: ${field} nem egész szám`); return null }
  return Number(v)
}

function kindOf(raw: string, line: number, errors: string[], required: boolean): Kind | null | undefined {
  const v = raw.trim().toLowerCase()
  if (v === 'bevetel' || v === 'bevétel') return 'bevetel'
  if (v === 'koltseg' || v === 'költség') return 'koltseg'
  if (v === 'nem_eredmeny') return 'nem_eredmeny'
  if (!required && v === '') return null
  pushErr(errors, `${line}. sor: tipus csak bevetel, koltseg vagy nem_eredmeny lehet`)
  return undefined
}

/** jeloles: teny | tipp. Empty means fact (the column is optional). */
function estimateOf(raw: string | undefined, line: number, errors: string[]): boolean | undefined {
  const v = (raw ?? '').trim().toLowerCase()
  if (v === '' || v === 'teny' || v === 'tény') return false
  if (v === 'tipp') return true
  pushErr(errors, `${line}. sor: jeloles csak teny vagy tipp lehet`)
  return undefined
}

function loadCsv<T>(path: string, required: string[], map: RowMapper<T>): FileResult<T> {
  const read = readCapped(path)
  if (!read.ok) {
    if (read.reason === 'missing') return { present: false, rows: [], errors: [] }
    const why = read.reason === 'too_large' ? 'a fájl nagyobb 1 MB-nál'
      : read.reason === 'not_regular' ? 'nem szabályos fájl (symlink vagy könyvtár)'
      : 'nem olvasható'
    return { present: true, rows: [], errors: [why] }
  }
  const table = parseCsv(read.text)
  if (table.length === 0) return { present: true, rows: [], errors: ['üres fájl'] }
  const header = table[0]!.map((h) => h.trim().toLowerCase())
  const missing = required.filter((k) => !header.includes(k))
  if (missing.length) return { present: true, rows: [], errors: [`hiányzó oszlop: ${missing.join(', ')}`] }
  const errors: string[] = []
  const rows: T[] = []
  const body = table.slice(1)
  if (body.length > FINANCE_MAX_ROWS) pushErr(errors, `${body.length} sor, csak az első ${FINANCE_MAX_ROWS} látszik`)
  body.slice(0, FINANCE_MAX_ROWS).forEach((r, idx) => {
    const cells: Cells = {}
    header.forEach((h, j) => { cells[h] = r[j] ?? '' })
    const mapped = map(cells, idx + 2, errors)
    if (mapped) rows.push(mapped)
  })
  return { present: true, rows, errors }
}

const mapPnl: RowMapper<PnlRow> = (c, line, errors) => {
  const month = c['honap']!.trim()
  if (!MONTH_RE.test(month)) { pushErr(errors, `${line}. sor: honap nem ÉÉÉÉ-HH`); return null }
  const amt = amount(c['osszeg_huf']!, 'osszeg_huf', line, errors)
  const kind = kindOf(c['tipus']!, line, errors, true)
  const estimate = estimateOf(c['jeloles'], line, errors)
  if (amt === null || !kind || estimate === undefined) return null
  return { month, category: cap(c['kategoria']!), amount: amt, kind, estimate, source: cap(c['forras'] ?? '') }
}

const mapForecast: RowMapper<ForecastRow> = (c, line, errors) => {
  const month = c['honap']!.trim()
  if (!MONTH_RE.test(month)) { pushErr(errors, `${line}. sor: honap nem ÉÉÉÉ-HH`); return null }
  const amt = amount(c['osszeg_huf']!, 'osszeg_huf', line, errors)
  const kind = kindOf(c['tipus'] ?? '', line, errors, false)
  // A forecast is a projection: absent a jeloles column it counts as an estimate.
  const estimate = c['jeloles'] === undefined ? true : estimateOf(c['jeloles'], line, errors)
  const scenario = cap(c['forgatokonyv']!) || 'alap'
  if (amt === null || kind === undefined || estimate === undefined) return null
  return { month, category: cap(c['kategoria']!), amount: amt, scenario, kind, estimate }
}

const mapBank: RowMapper<BankRow> = (c, line, errors) => {
  const date = c['datum']!.trim()
  if (!DATE_RE.test(date)) { pushErr(errors, `${line}. sor: datum nem ÉÉÉÉ-HH-NN`); return null }
  const bal = amount(c['egyenleg_huf']!, 'egyenleg_huf', line, errors)
  const act = c['tenyleges']!.trim().toLowerCase()
  if (act !== 'true' && act !== 'false') { pushErr(errors, `${line}. sor: tenyleges csak true vagy false lehet`); return null }
  if (bal === null) return null
  const actual = act === 'true'
  // Actual rows belong to every scenario; a projected row without one is 'alap'.
  const scenario = actual ? '' : (cap(c['forgatokonyv'] ?? '') || 'alap')
  return { date, account: cap(c['szamla_alias']!) || '?', balance: bal, actual, scenario, event: cap(c['esemeny'] ?? '') }
}

const mapProductCost: RowMapper<ProductCostRow> = (c, line, errors) => {
  const amt = amount(c['osszeg_huf_per_egyseg']!, 'osszeg_huf_per_egyseg', line, errors)
  // A unit-cost model is an estimate unless a jeloles column says otherwise.
  const estimate = c['jeloles'] === undefined ? true : estimateOf(c['jeloles'], line, errors)
  if (amt === null || estimate === undefined) return null
  return { product: cap(c['termek']!) || '?', item: cap(c['tetel']!), amount: amt, scenario: cap(c['forgatokonyv']!) || 'worst', estimate }
}

const EMPTY_META: Meta = {
  name: null, generated: null, currency: null, basis: null, sources: [], note: null, forecastMethod: null,
  missingMonths: [], overrides: [], notIncluded: [], warnings: [], unclassified: null,
}

/**
 * meta.json: only these keys are read, and only as plain text or numbers; any
 * other key (or a nested value under a text key) is ignored, so a new field the
 * finance agent adds does not show up on the page without a code change.
 *   nev | ceg, generalva, penznem, szemlelet, megjegyzes, elorejelzes_modszer: text
 *   forrasok, nem_szerepel, figyelmeztetesek: text lists
 *   hianyzo_honapok: ÉÉÉÉ-HH list (a gap, not a zero, in the P&L)
 *   alap_feluliras: {kategoria: indoklas} (manual baseline, shown as an estimate)
 *   besorolatlan_tetelek: count
 */
export function readMeta(text: string): { meta: Meta; errors: string[] } {
  let obj: unknown
  try { obj = JSON.parse(text) } catch { return { meta: EMPTY_META, errors: ['meta.json nem érvényes JSON'] } }
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return { meta: EMPTY_META, errors: ['meta.json nem objektum'] }
  const o = obj as Record<string, unknown>
  const str = (v: unknown, max = MAX_META_TEXT): string | null => (typeof v === 'string' && v.trim() ? cap(v, max) : null)
  const list = (v: unknown, max = 20): string[] =>
    Array.isArray(v) ? v.filter((s): s is string => typeof s === 'string' && s.trim() !== '').slice(0, max).map((s) => cap(s, MAX_META_TEXT)) : []
  const overridesRaw = o['alap_feluliras']
  const overrides = overridesRaw && typeof overridesRaw === 'object' && !Array.isArray(overridesRaw)
    ? Object.entries(overridesRaw as Record<string, unknown>)
      .filter((e): e is [string, string] => typeof e[1] === 'string')
      .slice(0, 20)
      .map(([key, reason]) => ({ key: cap(key, 64), reason: cap(reason, MAX_META_TEXT) }))
    : []
  const unclassified = o['besorolatlan_tetelek']
  return {
    meta: {
      name: str(o['nev'], 120) ?? str(o['ceg'], 120),
      generated: str(o['generalva'], 64),
      currency: str(o['penznem'], 16),
      basis: str(o['szemlelet']),
      sources: list(o['forrasok']),
      note: str(o['megjegyzes']),
      forecastMethod: str(o['elorejelzes_modszer'], 2000),
      missingMonths: list(o['hianyzo_honapok'], 120).filter((m) => MONTH_RE.test(m)),
      overrides,
      notIncluded: list(o['nem_szerepel']),
      warnings: list(o['figyelmeztetesek']),
      unclassified: typeof unclassified === 'number' && Number.isInteger(unclassified) && unclassified >= 0 ? unclassified : null,
    },
    errors: [],
  }
}

function loadMeta(path: string): { meta: Meta; errors: string[] } {
  const read = readCapped(path, 64 * 1024)
  if (!read.ok) {
    if (read.reason === 'missing') return { meta: EMPTY_META, errors: [] }
    return { meta: EMPTY_META, errors: ['meta.json nem olvasható'] }
  }
  return readMeta(read.text)
}

export function loadCompany(root: string, id: string): CompanyData {
  const dir = join(root, id)
  const { meta, errors: metaErrors } = loadMeta(join(dir, 'meta.json'))
  return {
    id,
    meta,
    metaErrors,
    pnl: loadCsv(join(dir, 'pnl.csv'), ['honap', 'kategoria', 'osszeg_huf', 'tipus'], mapPnl),
    forecast: loadCsv(join(dir, 'elorejelzes.csv'), ['honap', 'kategoria', 'osszeg_huf', 'forgatokonyv'], mapForecast),
    bank: loadCsv(join(dir, 'bank_projekcio.csv'), ['datum', 'szamla_alias', 'egyenleg_huf', 'tenyleges'], mapBank),
    productCost: loadCsv(join(dir, 'marabel_termek_koltseg.csv'), ['termek', 'tetel', 'osszeg_huf_per_egyseg', 'forgatokonyv'], mapProductCost),
  }
}

export function loadAll(root: string): CompanyData[] {
  return listCompanies(root).map((id) => loadCompany(root, id))
}

/** Company id -> display name from each company's meta.json (nev | ceg); the id when there is none. */
export function companyNames(root: string): Map<string, string> {
  return new Map(listCompanies(root).map((id) => [id, loadMeta(join(root, id, 'meta.json')).meta.name ?? id]))
}

// ------------------------------------------------------- subscriptions (ELOFIZETES1014)
//
// <root>/elofizetesek/ holds the finance agent's subscription list (Juró, card
// ef6f75ce; contract: that folder's README.md and docs/penzugy-ful.md):
//   elofizetesek.csv   one row per item (provider, plan, company, monthly HUF, renewal, flags, source, verified)
//   osszesito.csv      company x category: monthly total, estimate/uncertain parts, statement months, change
//   havi_terheles.csv  company, month, category, actual charge (the trend)
//   meta.json          generated, basis, sources, warnings, not included
// Same reader rules as the company files: fixed names, no symlink, size and cell caps.

const SUB_NOTE_MAX = 600
const SUB_STATUSES = ['aktiv', 'uj', 'proba', 'ismeretlen', 'megszunt'] as const
export type SubStatus = (typeof SUB_STATUSES)[number]
export const SUB_FLAGS = ['duplikalt', 'atfedes', 'nem_hasznalt_gyanu', 'kozelgo_megujulas', 'megszunes_ellenorzendo', 'ellenorizendo'] as const
const STATEMENT_COL_RE = /^kivonat_(\d{4})_(0[1-9]|1[0-2])_huf$/
const CHANGE_COL_RE = /^valtozas_[a-z0-9_]{1,40}_huf$/

export interface SubscriptionRow {
  id: string
  provider: string
  plan: string
  company: string
  category: string
  type: string
  cycle: string
  origAmount: string
  currency: string
  cycleHuf: number | null
  /** null = the price is not known (shown as such, never as 0) */
  monthlyHuf: number | null
  monthlyEstimate: boolean
  monthlyNote: string
  fxSource: string
  lastCharge: string
  lastChargeHuf: number | null
  renewal: string
  renewalNote: string
  trialEnd: string
  status: SubStatus
  usedBy: string
  sourceType: string
  source: string
  /** known flag slugs, then any unknown one as given */
  flags: string[]
  note: string
  verified: boolean
  verifiedNote: string
}

export interface SubSummaryRow {
  company: string
  category: string
  monthly: number
  projected: number
  uncertain: number
  unknownCount: number
  recurring: number
  /** statement months in column order, e.g. [{month:'2026-08', amount}] */
  statements: Array<{ month: string; amount: number }>
  change: number | null
}

export interface SubChargeRow { company: string; month: string; category: string; amount: number; estimate: boolean }

export interface SubMeta {
  generated: string | null
  basis: string | null
  meaning: string | null
  change: string | null
  sources: string[]
  notIncluded: string[]
  warnings: string[]
}

export interface SubscriptionsData {
  present: boolean
  meta: SubMeta
  metaErrors: string[]
  items: FileResult<SubscriptionRow>
  summary: FileResult<SubSummaryRow>
  charges: FileResult<SubChargeRow>
}

/** An optional whole-forint amount: empty is null (unknown), anything else must be an integer. */
function optAmount(raw: string | undefined, field: string, line: number, errors: string[]): number | null | undefined {
  const v = (raw ?? '').trim()
  if (v === '') return null
  const n = amount(v, field, line, errors)
  return n === null ? undefined : n
}

const mapSubscription: RowMapper<SubscriptionRow> = (c, line, errors) => {
  const status = (c['statusz'] ?? '').trim().toLowerCase() as SubStatus
  if (!SUB_STATUSES.includes(status)) { pushErr(errors, `${line}. sor: statusz csak ${SUB_STATUSES.join(', ')} lehet`); return null }
  const cycleHuf = optAmount(c['ciklusdij_huf'], 'ciklusdij_huf', line, errors)
  const monthlyHuf = optAmount(c['havi_huf'], 'havi_huf', line, errors)
  const lastChargeHuf = optAmount(c['utolso_terheles_huf'], 'utolso_terheles_huf', line, errors)
  if (cycleHuf === undefined || monthlyHuf === undefined || lastChargeHuf === undefined) return null
  const monthlyNote = cap(c['havi_huf_jeloles'] ?? '')
  const rawFlags = (c['jeloles'] ?? '').split(',').map((f) => cap(f, 40).toLowerCase()).filter(Boolean)
  const flags = [...SUB_FLAGS.filter((f) => rawFlags.includes(f)), ...rawFlags.filter((f) => !(SUB_FLAGS as readonly string[]).includes(f))]
  const verifiedRaw = cap(c['ellenorzott'] ?? '')
  return {
    id: cap(c['id'] ?? '', 64),
    provider: cap(c['szolgaltato'] ?? '') || '?',
    plan: cap(c['csomag'] ?? ''),
    company: cap(c['ceg'] ?? '', 64) || '?',
    category: cap(c['kategoria'] ?? '', 64),
    type: cap(c['tipus'] ?? '', 64),
    cycle: cap(c['ciklus'] ?? '', 64),
    origAmount: cap(c['dij_eredeti'] ?? '', 32),
    currency: cap(c['deviza'] ?? '', 32),
    cycleHuf,
    monthlyHuf,
    // The contract: a "tipp..." note marks an estimate (a yearly fee / 12 and the like).
    monthlyEstimate: /^tipp/i.test(monthlyNote),
    monthlyNote,
    fxSource: cap(c['arfolyam_forras'] ?? ''),
    lastCharge: cap(c['utolso_terheles'] ?? ''),
    lastChargeHuf,
    renewal: cap(c['kovetkezo_megujulas'] ?? ''),
    renewalNote: cap(c['megujulas_jeloles'] ?? ''),
    trialEnd: cap(c['probaido_vege'] ?? ''),
    status,
    usedBy: cap(c['hasznalja'] ?? ''),
    sourceType: cap(c['forras_tipus'] ?? '', 64),
    source: cap(c['forras'] ?? '', SUB_NOTE_MAX),
    flags,
    note: cap(c['megjegyzes'] ?? '', SUB_NOTE_MAX),
    // Only an explicit "igen..." counts as verified; empty or anything else is shown as not verified.
    verified: /^igen\b/i.test(verifiedRaw),
    verifiedNote: verifiedRaw,
  }
}

/** The statement-month and change columns are named by month (kivonat_2026_09_huf), so they are found by pattern. */
function summaryMapper(header: string[]): RowMapper<SubSummaryRow> {
  const statementCols = header.filter((h) => STATEMENT_COL_RE.test(h)).sort()
  const changeCol = header.find((h) => CHANGE_COL_RE.test(h))
  return (c, line, errors) => {
    const nums = ['elofizetes_havi_huf', 'ebbol_vetitett_tipp_huf', 'bizonytalan_havi_huf', 'ismetlodo_dij_havi_huf']
      .map((f) => optAmount(c[f], f, line, errors))
    const cnt = (c['ar_nem_ismert_db'] ?? '').trim()
    if (cnt !== '' && !/^\d{1,6}$/.test(cnt)) { pushErr(errors, `${line}. sor: ar_nem_ismert_db nem nemnegatív egész`); return null }
    const statements = statementCols.map((col) => {
      const m = STATEMENT_COL_RE.exec(col)!
      return { month: `${m[1]}-${m[2]}`, amount: optAmount(c[col], col, line, errors) }
    })
    const change = changeCol ? optAmount(c[changeCol], changeCol, line, errors) : null
    if (nums.some((n) => n === undefined) || statements.some((s) => s.amount === undefined) || change === undefined) return null
    return {
      company: cap(c['ceg'] ?? '', 64) || '?',
      category: cap(c['kategoria'] ?? '', 64),
      monthly: nums[0] ?? 0,
      projected: nums[1] ?? 0,
      uncertain: nums[2] ?? 0,
      unknownCount: cnt === '' ? 0 : Number(cnt),
      recurring: nums[3] ?? 0,
      statements: statements.map((s) => ({ month: s.month, amount: s.amount ?? 0 })),
      change,
    }
  }
}

const mapCharge: RowMapper<SubChargeRow> = (c, line, errors) => {
  const month = (c['honap'] ?? '').trim()
  if (!MONTH_RE.test(month)) { pushErr(errors, `${line}. sor: honap nem ÉÉÉÉ-HH`); return null }
  const amt = amount(c['terheles_huf'] ?? '', 'terheles_huf', line, errors)
  const estimate = estimateOf(c['jeloles'], line, errors)
  if (amt === null || estimate === undefined) return null
  return { company: cap(c['ceg'] ?? '', 64) || '?', month, category: cap(c['kategoria'] ?? '', 64), amount: amt, estimate }
}

/** meta.json of the subscriptions folder; like readMeta, only these keys, as plain text. */
export function readSubscriptionMeta(text: string): { meta: SubMeta; errors: string[] } {
  const empty: SubMeta = { generated: null, basis: null, meaning: null, change: null, sources: [], notIncluded: [], warnings: [] }
  let obj: unknown
  try { obj = JSON.parse(text) } catch { return { meta: empty, errors: ['meta.json nem érvényes JSON'] } }
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return { meta: empty, errors: ['meta.json nem objektum'] }
  const o = obj as Record<string, unknown>
  const str = (v: unknown, max = MAX_META_TEXT): string | null => (typeof v === 'string' && v.trim() ? cap(v, max) : null)
  const list = (v: unknown, max = 20): string[] =>
    Array.isArray(v) ? v.filter((s): s is string => typeof s === 'string' && s.trim() !== '').slice(0, max).map((s) => cap(s, MAX_META_TEXT)) : []
  return {
    meta: {
      generated: str(o['keszult'], 64) ?? str(o['generalva'], 64),
      basis: str(o['szemlelet']),
      meaning: str(o['havi_osszeg_jelentese'], 2000),
      change: str(o['valtozas']),
      sources: list(o['forrasok']),
      notIncluded: list(o['nem_szerepel']),
      warnings: list(o['figyelmeztetesek']),
    },
    errors: [],
  }
}

function loadCsvWith<T>(path: string, required: string[], mapperFor: (header: string[]) => RowMapper<T>): FileResult<T> {
  // The header decides the mapper (month-named columns), so peek at it first; loadCsv re-reads the capped file.
  const read = readCapped(path)
  const header = read.ok ? (parseCsv(read.text)[0] ?? []).map((h) => h.trim().toLowerCase()) : []
  return loadCsv(path, required, mapperFor(header))
}

export function loadSubscriptions(root: string): SubscriptionsData {
  const dir = join(root, SUBSCRIPTIONS_DIR)
  let isDir = false
  try { isDir = lstatSync(dir).isDirectory() } catch { /* absent */ }
  const none: FileResult<never> = { present: false, rows: [], errors: [] }
  if (!isDir) {
    return { present: false, meta: readSubscriptionMeta('{}').meta, metaErrors: [], items: none, summary: none, charges: none }
  }
  const metaRead = readCapped(join(dir, 'meta.json'), 64 * 1024)
  const { meta, errors: metaErrors } = metaRead.ok ? readSubscriptionMeta(metaRead.text)
    : metaRead.reason === 'missing' ? readSubscriptionMeta('{}') : { meta: readSubscriptionMeta('{}').meta, errors: ['meta.json nem olvasható'] }
  const items = loadCsv(join(dir, 'elofizetesek.csv'), ['szolgaltato', 'ceg', 'kategoria', 'havi_huf', 'statusz'], mapSubscription)
  const summary = loadCsvWith(join(dir, 'osszesito.csv'), ['ceg', 'kategoria', 'elofizetes_havi_huf'], summaryMapper)
  const charges = loadCsv(join(dir, 'havi_terheles.csv'), ['ceg', 'honap', 'kategoria', 'terheles_huf'], mapCharge)
  return { present: items.present || summary.present || charges.present, meta, metaErrors, items, summary, charges }
}

// ---------------------------------------------------------------- aggregation

export interface MonthTotals {
  month: string
  /** true for a month the meta lists as missing and the rows do not cover: a gap, not a zero */
  missing: boolean
  income: number
  cost: number
  result: number
  /** signed sum of the nem_eredmeny rows: cash that moved but is not result */
  other: number
  estimate: boolean
}

/**
 * Monthly income/cost/result, cash basis. Costs are summed as magnitudes,
 * whatever sign the file used; nem_eredmeny rows stay out of the result and
 * are summed signed into `other`. A month in `missingMonths` with no rows is a
 * gap row (missing: true).
 */
export function monthlyPnl(rows: PnlRow[], missingMonths: string[] = []): MonthTotals[] {
  const by = new Map<string, MonthTotals>()
  for (const r of rows) {
    const m = by.get(r.month) ?? { month: r.month, missing: false, income: 0, cost: 0, result: 0, other: 0, estimate: false }
    if (r.kind === 'bevetel') m.income += r.amount
    else if (r.kind === 'koltseg') m.cost += Math.abs(r.amount)
    else m.other += r.amount
    m.result = m.income - m.cost
    m.estimate = m.estimate || r.estimate
    by.set(r.month, m)
  }
  for (const month of missingMonths) {
    if (!by.has(month)) by.set(month, { month, missing: true, income: 0, cost: 0, result: 0, other: 0, estimate: false })
  }
  return [...by.values()].sort((a, b) => a.month.localeCompare(b.month))
}

export interface CategoryTotal { category: string; kind: Kind; amount: number; estimate: boolean }

/** Totals per (category, kind), largest first. Costs as magnitudes, nem_eredmeny signed. */
export function categoryTotals(rows: PnlRow[]): CategoryTotal[] {
  const by = new Map<string, CategoryTotal>()
  for (const r of rows) {
    const key = `${r.kind}\u0000${r.category}`
    const c = by.get(key) ?? { category: r.category, kind: r.kind, amount: 0, estimate: false }
    c.amount += r.kind === 'koltseg' ? Math.abs(r.amount) : r.amount
    c.estimate = c.estimate || r.estimate
    by.set(key, c)
  }
  return [...by.values()].sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount) || a.category.localeCompare(b.category))
}

export interface ForecastCell { net: number; estimate: boolean }

/**
 * month -> scenario -> net. A typed row adds as income (+) or cost (-, by
 * magnitude); an untyped row adds signed, which is how a forecast file whose
 * costs are already negative reads correctly. nem_eredmeny stays out.
 */
export function forecastTable(rows: ForecastRow[]): { months: string[]; scenarios: string[]; cells: Map<string, ForecastCell> } {
  const cells = new Map<string, ForecastCell>()
  const months = new Set<string>()
  const scenarios = new Set<string>()
  for (const r of rows) {
    if (r.kind === 'nem_eredmeny') continue
    months.add(r.month)
    scenarios.add(r.scenario)
    const key = `${r.month}\u0000${r.scenario}`
    const c = cells.get(key) ?? { net: 0, estimate: false }
    if (r.kind === 'bevetel') c.net += r.amount
    else if (r.kind === 'koltseg') c.net -= Math.abs(r.amount)
    else c.net += r.amount
    c.estimate = c.estimate || r.estimate
    cells.set(key, c)
  }
  return { months: [...months].sort(), scenarios: [...scenarios].sort(), cells }
}

export const TOTAL_ACCOUNT = '\u0000total'

export interface BankPoint { date: string; balance: number; actual: boolean }
export interface BankLine { account: string; scenario: string; points: BankPoint[] }
export interface BankSummary {
  account: string
  scenario: string
  min: BankPoint | null
  /** first date the balance is below zero, or null */
  firstNegative: BankPoint | null
}

/** The scenarios the projection has; '' (actual only) when there is no projected row. */
export function bankScenarios(rows: BankRow[]): string[] {
  const s = [...new Set(rows.filter((r) => !r.actual).map((r) => r.scenario))].sort()
  return s.length ? s : ['']
}

/**
 * One line per (account, scenario): the account's actual rows plus that
 * scenario's projected rows, by date. Plus a TOTAL line per scenario: at each
 * date, the sum over accounts of each account's latest known balance on or
 * before that date (an account counts from its first row on).
 */
export function bankLines(rows: BankRow[]): BankLine[] {
  const accounts = [...new Set(rows.map((r) => r.account))].sort()
  const lines: BankLine[] = []
  for (const scenario of bankScenarios(rows)) {
    const perAccount = new Map<string, BankPoint[]>()
    for (const a of accounts) {
      const pts = rows
        .filter((r) => r.account === a && (r.actual || r.scenario === scenario))
        .map((r) => ({ date: r.date, balance: r.balance, actual: r.actual }))
        .sort((x, y) => x.date.localeCompare(y.date))
      perAccount.set(a, pts)
      lines.push({ account: a, scenario, points: pts })
    }
    const dates = [...new Set([...perAccount.values()].flatMap((p) => p.map((x) => x.date)))].sort()
    const total: BankPoint[] = []
    for (const d of dates) {
      let sum = 0
      let allActual = true
      for (const pts of perAccount.values()) {
        let last: BankPoint | null = null
        for (const p of pts) { if (p.date <= d) last = p; else break }
        if (last) { sum += last.balance; allActual = allActual && last.actual }
      }
      total.push({ date: d, balance: sum, actual: allActual })
    }
    lines.push({ account: TOTAL_ACCOUNT, scenario, points: total })
  }
  return lines
}

export function summarizeLine(line: BankLine): BankSummary {
  let min: BankPoint | null = null
  let firstNegative: BankPoint | null = null
  for (const p of line.points) {
    if (min === null || p.balance < min.balance) min = p
    if (firstNegative === null && p.balance < 0) firstNegative = p
  }
  return { account: line.account, scenario: line.scenario, min, firstNegative }
}

export interface ProductCostTable {
  products: Array<{ product: string; items: string[] }>
  scenarios: string[]
  cells: Map<string, { amount: number; estimate: boolean }>
}

/** Products and their items in file order; scenarios in file order; one cell per (product, item, scenario), summed if repeated. */
export function productCostTable(rows: ProductCostRow[]): ProductCostTable {
  const products: Array<{ product: string; items: string[] }> = []
  const scenarios: string[] = []
  const cells = new Map<string, { amount: number; estimate: boolean }>()
  for (const r of rows) {
    let p = products.find((x) => x.product === r.product)
    if (!p) { p = { product: r.product, items: [] }; products.push(p) }
    if (!p.items.includes(r.item)) p.items.push(r.item)
    if (!scenarios.includes(r.scenario)) scenarios.push(r.scenario)
    const key = `${r.product}\u0000${r.item}\u0000${r.scenario}`
    const c = cells.get(key) ?? { amount: 0, estimate: false }
    c.amount += r.amount
    c.estimate = c.estimate || r.estimate
    cells.set(key, c)
  }
  return { products, scenarios, cells }
}

// ------------------------------------------------------------------ rendering

const L: Record<Lang, Record<string, string>> = {
  hu: {
    title: 'Pénzügy', none: 'Nincs még adat a pénzügyi mappában.', noFiles: 'Ehhez a céghez még nincs adatfájl.',
    generated: 'Adat készült', sources: 'Források', basis: 'Szemlélet',
    pnl: 'Havi eredmény (pénzforgalmi)', month: 'Hónap', income: 'Bevétel', cost: 'Költség', result: 'Eredmény',
    other: 'Nem eredmény (pénzmozgás)', total: 'Összesen', gap: 'nincs adat', missingMonths: 'Hiányzó hónapok',
    categories: 'Kategóriák', kind: 'Típus', forecast: 'Előrejelzés (nettó)', scenario: 'Forgatókönyv',
    method: 'Az előrejelzés módszere', bank: 'Bankegyenleg-projekció', account: 'Számla', allAccounts: 'Összes számla',
    lowest: 'Legalacsonyabb pont', balance: 'Egyenleg', firstNeg: 'Először mínuszban', never: 'nem megy mínuszba', actual: 'tényleges',
    projected: 'előrejelzett', events: 'Egyszeri tételek', product: 'Termékenkénti egységköltség és fedezet (Ft / rendelés)',
    item: 'Tétel', errors: 'Hibák (a hibás sorok kimaradtak)',
    estimateNote: '~ és dőlt: tipp (vetítés vagy bizonytalan besorolás), a többi tény (kivonatból).',
    overrides: 'Kézi alapszint (tipp)', notIncluded: 'Nem szerepel benne', unclassified: 'Besorolatlan tételek',
    warnings: 'Figyelmeztetés',
  },
  en: {
    title: 'Finance', none: 'No data in the finance folder yet.', noFiles: 'No data file for this company yet.',
    generated: 'Data generated', sources: 'Sources', basis: 'Basis',
    pnl: 'Monthly result (cash basis)', month: 'Month', income: 'Income', cost: 'Cost', result: 'Result',
    other: 'Non-result (cash movement)', total: 'Total', gap: 'no data', missingMonths: 'Missing months',
    categories: 'Categories', kind: 'Type', forecast: 'Forecast (net)', scenario: 'Scenario',
    method: 'Forecast method', bank: 'Bank balance projection', account: 'Account', allAccounts: 'All accounts',
    lowest: 'Lowest point', balance: 'Balance', firstNeg: 'First below zero', never: 'stays above zero', actual: 'actual',
    projected: 'projected', events: 'One-off items', product: 'Unit cost and margin per product (HUF / order)',
    item: 'Item', errors: 'Problems (invalid rows skipped)',
    estimateNote: '~ and italic: estimate (projection or uncertain classification), the rest is fact (from statements).',
    overrides: 'Manual baseline (estimate)', notIncluded: 'Not included', unclassified: 'Unclassified items',
    warnings: 'Warning',
  },
}

/** The finance agent's fixed category slugs (Juró, msg 1867). An unknown slug is shown as is. */
const CATEGORY: Record<Lang, Record<string, string>> = {
  hu: {
    bevetel: 'Bevétel', ber_jarulek: 'Bér és járulék', adok: 'Adók', infra_saas: 'Infrastruktúra és SaaS', auto: 'Autó',
    konyvelo: 'Könyvelő', bank_dij: 'Bankdíj', egyeb_koltseg: 'Egyéb költség', nem_eredmeny: 'Nem eredmény',
  },
  en: {
    bevetel: 'Income', ber_jarulek: 'Payroll and contributions', adok: 'Taxes', infra_saas: 'Infrastructure and SaaS', auto: 'Car',
    konyvelo: 'Accountant', bank_dij: 'Bank fees', egyeb_koltseg: 'Other costs', nem_eredmeny: 'Non-result',
  },
}

/** Unit-cost item slugs (Juró, msg 1906). An unknown slug is shown as is. */
const ITEM: Record<Lang, Record<string, string>> = {
  hu: {
    netto_bevetel: 'Nettó bevétel', ai: 'AI', leirat: 'Leirat', sms: 'SMS', gyartas: 'Gyártás', posta: 'Posta',
    stripe: 'Stripe-díj', valtozo_osszesen: 'Változó költség összesen', fedezet: 'Fedezet',
    havi_10_rendeles: 'Havi 10 rendelésnél', havi_50_rendeles: 'Havi 50 rendelésnél', havi_200_rendeles: 'Havi 200 rendelésnél',
  },
  en: {
    netto_bevetel: 'Net revenue', ai: 'AI', leirat: 'Transcription', sms: 'SMS', gyartas: 'Production', posta: 'Postage',
    stripe: 'Stripe fee', valtozo_osszesen: 'Variable cost total', fedezet: 'Margin',
    havi_10_rendeles: 'At 10 orders a month', havi_50_rendeles: 'At 50 orders a month', havi_200_rendeles: 'At 200 orders a month',
  },
}
const MARGIN_ITEMS = new Set(['valtozo_osszesen', 'fedezet'])

function itemLabel(slug: string, lang: Lang): string {
  return ITEM[lang][slug] ?? slug
}

export function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]!))
}

const HUF = new Intl.NumberFormat('hu-HU', { maximumFractionDigits: 0 })
export function fmtHuf(n: number): string {
  return `${HUF.format(n)} Ft`
}

/** An SVG coordinate: only ever a checked finite number, never text. */
function coord(n: number): string {
  return Number.isFinite(n) ? n.toFixed(1) : '0'
}

function numCell(n: number, estimate = false): string {
  const cls = `num${n < 0 ? ' neg' : ''}${estimate ? ' est' : ''}`
  return `<td class="${cls}">${estimate ? '~' : ''}${escapeHtml(fmtHuf(n))}</td>`
}

function catLabel(slug: string, lang: Lang): string {
  return CATEGORY[lang][slug] ?? slug
}

function errorsBlock(file: string, errors: string[], t: Record<string, string>): string {
  if (!errors.length) return ''
  return `<details class="errs"><summary>${escapeHtml(file)}: ${escapeHtml(t.errors!)} (${errors.length})</summary><ul>${
    errors.map((e) => `<li>${escapeHtml(e)}</li>`).join('')}</ul></details>`
}

function pnlChart(months: MonthTotals[], t: Record<string, string>): string {
  const shown = months.slice(-12)
  if (!shown.length) return ''
  const W = 640, H = 200, pad = 28
  const max = Math.max(1, ...shown.map((m) => Math.max(m.income, m.cost)))
  const slot = (W - pad) / shown.length
  const bw = Math.max(2, Math.min(18, slot / 3))
  const y = (v: number): number => H - pad - (v / max) * (H - 2 * pad)
  const bars = shown.map((m, i) => {
    const x = pad + i * slot + slot / 2
    const label = `<text class="ax" x="${coord(x)}" y="${H - 8}" text-anchor="middle">${escapeHtml(m.month.slice(2))}</text>`
    if (m.missing) return `<text class="ax gap" x="${coord(x)}" y="${coord(H - pad - 6)}" text-anchor="middle">${escapeHtml(t.gap!)}</text>${label}`
    const est = m.estimate ? ' est' : ''
    return `<rect class="b-inc${est}" x="${coord(x - bw - 1)}" y="${coord(y(m.income))}" width="${coord(bw)}" height="${coord(H - pad - y(m.income))}"/>` +
      `<rect class="b-cost${est}" x="${coord(x + 1)}" y="${coord(y(m.cost))}" width="${coord(bw)}" height="${coord(H - pad - y(m.cost))}"/>` + label
  }).join('')
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${escapeHtml(t.pnl!)}">` +
    `<line class="base" x1="${pad}" y1="${H - pad}" x2="${W}" y2="${H - pad}"/>` +
    `<text class="ax" x="${pad}" y="${pad - 8}">${escapeHtml(fmtHuf(max))}</text>${bars}</svg>` +
    `<p class="legend"><span class="sw sw-inc"></span>${escapeHtml(t.income!)} <span class="sw sw-cost"></span>${escapeHtml(t.cost!)}</p>`
}

const SCEN_CLASS = ['dash', 'dot']

function bankChart(lines: BankLine[], scenarios: string[], t: Record<string, string>): string {
  const totals = lines.filter((l) => l.account === TOTAL_ACCOUNT)
  const all = totals.flatMap((l) => l.points)
  if (all.length < 2) return ''
  const W = 640, H = 220, pad = 28
  const dates = [...new Set(all.map((p) => p.date))].sort()
  const idx = new Map(dates.map((d, i) => [d, i]))
  const lo = Math.min(0, ...all.map((p) => p.balance))
  const hi = Math.max(1, ...all.map((p) => p.balance))
  const x = (d: string): number => pad + ((idx.get(d) ?? 0) / Math.max(1, dates.length - 1)) * (W - 2 * pad)
  const y = (v: number): number => H - pad - ((v - lo) / (hi - lo || 1)) * (H - 2 * pad)
  const poly = (pts: BankPoint[], cls: string): string =>
    pts.length < 2 ? '' : `<polyline class="${cls}" points="${pts.map((p) => `${coord(x(p.date))},${coord(y(p.balance))}`).join(' ')}"/>`
  let actualDrawn = false
  const parts = totals.map((l) => {
    const si = Math.max(0, scenarios.indexOf(l.scenario))
    const actual = l.points.filter((p) => p.actual)
    const last = actual[actual.length - 1]
    const proj = l.points.filter((p) => !p.actual)
    const a = actualDrawn ? '' : poly(actual, 'tot')
    actualDrawn = true
    return a + poly(last ? [last, ...proj] : proj, `tot ${SCEN_CLASS[si % SCEN_CLASS.length]}`)
  }).join('')
  const zero = lo < 0 ? `<line class="zero" x1="${pad}" y1="${coord(y(0))}" x2="${W - pad}" y2="${coord(y(0))}"/>` : ''
  const labels = `<text class="ax" x="${pad}" y="${pad - 8}">${escapeHtml(fmtHuf(hi))}</text>` +
    (lo < 0 ? `<text class="ax" x="${pad}" y="${coord(y(lo) - 6)}">${escapeHtml(fmtHuf(lo))}</text>` : '') +
    `<text class="ax" x="${pad}" y="${H - 8}">${escapeHtml(dates[0]!)}</text>` +
    `<text class="ax" x="${W - pad}" y="${H - 8}" text-anchor="end">${escapeHtml(dates[dates.length - 1]!)}</text>`
  const legend = [`${escapeHtml(t.allAccounts!)}, ${escapeHtml(t.actual!)}: ───`]
    .concat(scenarios.filter(Boolean).map((s, i) => `${escapeHtml(s)}: ${i % 2 ? '·····' : '- - -'}`))
    .join(' · ')
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${escapeHtml(t.bank!)}">${zero}${parts}${labels}</svg>` +
    `<p class="legend">${legend}</p>`
}

function metaBlock(c: CompanyData, t: Record<string, string>, lang: Lang): string {
  const m = c.meta
  const out: string[] = []
  for (const w of m.warnings) out.push(`<p class="warn">${escapeHtml(t.warnings!)}: ${escapeHtml(w)}</p>`)
  const line: string[] = []
  if (m.generated) line.push(`${escapeHtml(t.generated!)}: ${escapeHtml(m.generated)}`)
  if (m.sources.length) line.push(`${escapeHtml(t.sources!)}: ${m.sources.map(escapeHtml).join(', ')}`)
  if (line.length) out.push(`<p class="meta">${line.join(' · ')}</p>`)
  if (m.basis) out.push(`<p class="basis">${escapeHtml(t.basis!)}: ${escapeHtml(m.basis)}</p>`)
  if (m.note) out.push(`<p class="meta">${escapeHtml(m.note)}</p>`)
  if (m.unclassified) out.push(`<p class="meta">${escapeHtml(t.unclassified!)}: ${m.unclassified}</p>`)
  if (m.notIncluded.length) out.push(`<p class="meta">${escapeHtml(t.notIncluded!)}: ${m.notIncluded.map(escapeHtml).join('; ')}</p>`)
  if (m.overrides.length) {
    out.push(`<p class="meta est">${escapeHtml(t.overrides!)}: ${
      m.overrides.map((o) => `${escapeHtml(catLabel(o.key, lang))}: ${escapeHtml(o.reason)}`).join('; ')}</p>`)
  }
  return out.join('')
}

function renderCompany(c: CompanyData, t: Record<string, string>, lang: Lang): string {
  const parts: string[] = []
  parts.push(`<h2>${escapeHtml(c.meta.name ?? c.id)}</h2>`, metaBlock(c, t, lang), errorsBlock('meta.json', c.metaErrors, t))

  if (c.pnl.present) {
    const months = monthlyPnl(c.pnl.rows, c.meta.missingMonths)
    const real = months.filter((m) => !m.missing)
    const tot = real.reduce((a, m) => ({ income: a.income + m.income, cost: a.cost + m.cost, other: a.other + m.other, est: a.est || m.estimate }),
      { income: 0, cost: 0, other: 0, est: false })
    const hasOther = real.some((m) => m.other !== 0)
    parts.push(`<h3>${escapeHtml(t.pnl!)}</h3>`, pnlChart(months, t))
    if (months.length) {
      const otherTh = hasOther ? `<th class="num">${escapeHtml(t.other!)}</th>` : ''
      parts.push(`<table><thead><tr><th>${escapeHtml(t.month!)}</th><th class="num">${escapeHtml(t.income!)}</th><th class="num">${escapeHtml(t.cost!)}</th><th class="num">${escapeHtml(t.result!)}</th>${otherTh}</tr></thead><tbody>${
        months.map((m) => m.missing
          ? `<tr class="gap"><td>${escapeHtml(m.month)}</td><td colspan="${hasOther ? 4 : 3}" class="gaptxt">${escapeHtml(t.gap!)}</td></tr>`
          : `<tr><td>${escapeHtml(m.month)}</td>${numCell(m.income, m.estimate)}${numCell(m.cost, m.estimate)}${numCell(m.result, m.estimate)}${hasOther ? numCell(m.other, m.estimate) : ''}</tr>`,
        ).join('')
      }</tbody><tfoot><tr><th>${escapeHtml(t.total!)}</th>${numCell(tot.income, tot.est)}${numCell(tot.cost, tot.est)}${numCell(tot.income - tot.cost, tot.est)}${hasOther ? numCell(tot.other, tot.est) : ''}</tr></tfoot></table>`)
    }
    if (c.meta.missingMonths.length) parts.push(`<p class="meta">${escapeHtml(t.missingMonths!)}: ${c.meta.missingMonths.map(escapeHtml).join(', ')}</p>`)
    const last = real[real.length - 1]
    if (last) {
      const cats = categoryTotals(c.pnl.rows.filter((r) => r.month === last.month))
      parts.push(`<h3>${escapeHtml(t.categories!)}: ${escapeHtml(last.month)}</h3><table><thead><tr><th>${escapeHtml(t.categories!)}</th><th>${escapeHtml(t.kind!)}</th><th class="num">${escapeHtml(t.total!)}</th></tr></thead><tbody>${
        cats.map((k) => `<tr><td${k.estimate ? ' class="est"' : ''}>${escapeHtml(catLabel(k.category, lang))}</td><td>${escapeHtml(k.kind === 'bevetel' ? t.income! : k.kind === 'koltseg' ? t.cost! : t.other!)}</td>${numCell(k.amount, k.estimate)}</tr>`).join('')
      }</tbody></table>`)
    }
    parts.push(errorsBlock('pnl.csv', c.pnl.errors, t))
  }

  if (c.forecast.present) {
    const f = forecastTable(c.forecast.rows)
    parts.push(`<h3>${escapeHtml(t.forecast!)}</h3>`)
    if (c.meta.forecastMethod) parts.push(`<details class="meta"><summary>${escapeHtml(t.method!)}</summary><p class="est">${escapeHtml(c.meta.forecastMethod)}</p></details>`)
    if (f.months.length) {
      parts.push(`<table><thead><tr><th>${escapeHtml(t.month!)}</th>${
        f.scenarios.map((s) => `<th class="num">${escapeHtml(s)}</th>`).join('')
      }</tr></thead><tbody>${
        f.months.map((m) => `<tr><td>${escapeHtml(m)}</td>${f.scenarios.map((s) => {
          const cell = f.cells.get(`${m}\u0000${s}`)
          return cell ? numCell(cell.net, cell.estimate) : '<td class="num">-</td>'
        }).join('')}</tr>`).join('')
      }</tbody><tfoot><tr><th>${escapeHtml(t.total!)}</th>${f.scenarios.map((s) => {
        let sum = 0, est = false
        for (const m of f.months) { const cell = f.cells.get(`${m}\u0000${s}`); if (cell) { sum += cell.net; est = est || cell.estimate } }
        return numCell(sum, est)
      }).join('')}</tr></tfoot></table>`)
    }
    parts.push(errorsBlock('elorejelzes.csv', c.forecast.errors, t))
  }

  if (c.bank.present) {
    const scenarios = bankScenarios(c.bank.rows)
    const lines = bankLines(c.bank.rows)
    parts.push(`<h3>${escapeHtml(t.bank!)}</h3>`, bankChart(lines, scenarios, t))
    if (lines.length) {
      const sums = lines.map(summarizeLine)
      const accountName = (a: string): string => (a === TOTAL_ACCOUNT ? t.allAccounts! : a)
      const pt = (p: BankPoint | null): string => (p ? `${escapeHtml(p.date)} (${escapeHtml(p.actual ? t.actual! : t.projected!)})` : escapeHtml(t.never!))
      parts.push(`<table><thead><tr><th>${escapeHtml(t.account!)}</th><th>${escapeHtml(t.scenario!)}</th><th>${escapeHtml(t.lowest!)}</th><th class="num">${escapeHtml(t.balance!)}</th><th>${escapeHtml(t.firstNeg!)}</th></tr></thead><tbody>${
        sums.map((s) => `<tr${s.account === TOTAL_ACCOUNT ? ' class="sub"' : ''}><td>${escapeHtml(accountName(s.account))}</td><td>${escapeHtml(s.scenario || t.actual!)}</td><td>${s.min ? pt(s.min) : '-'}</td>${s.min ? numCell(s.min.balance, !s.min.actual) : '<td class="num">-</td>'}<td${s.firstNegative ? ' class="neg"' : ''}>${pt(s.firstNegative)}</td></tr>`).join('')
      }</tbody></table>`)
    }
    const events = c.bank.rows.filter((r) => r.event)
    if (events.length) {
      parts.push(`<p class="meta">${escapeHtml(t.events!)}:</p><ul class="events">${
        events.map((r) => `<li${r.actual ? '' : ' class="est"'}>${escapeHtml(r.date)}, ${escapeHtml(r.account)}${r.scenario ? ` (${escapeHtml(r.scenario)})` : ''}: ${escapeHtml(r.event)}</li>`).join('')
      }</ul>`)
    }
    parts.push(errorsBlock('bank_projekcio.csv', c.bank.errors, t))
  }

  if (c.productCost.present) {
    // Product x item rows, one column per scenario. The values are shown as
    // given (no sum: the file already carries its own subtotal and margin
    // items, so adding them up would double count); a negative margin is red.
    const pc = productCostTable(c.productCost.rows)
    parts.push(`<h3>${escapeHtml(t.product!)}</h3>`)
    if (pc.products.length) {
      parts.push(`<table><thead><tr><th>${escapeHtml(t.item!)}</th>${
        pc.scenarios.map((s) => `<th class="num">${escapeHtml(s)}</th>`).join('')
      }</tr></thead><tbody>${
        pc.products.map((p) => `<tr class="prod"><th colspan="${pc.scenarios.length + 1}">${escapeHtml(p.product)}</th></tr>` +
          p.items.map((it) => `<tr${MARGIN_ITEMS.has(it) ? ' class="sub"' : ''}><td>${escapeHtml(itemLabel(it, lang))}</td>${
            pc.scenarios.map((s) => {
              const cell = pc.cells.get(`${p.product}\u0000${it}\u0000${s}`)
              return cell ? numCell(cell.amount, cell.estimate) : '<td class="num">-</td>'
            }).join('')
          }</tr>`).join(''),
        ).join('')
      }</tbody></table>`)
    }
    parts.push(errorsBlock('marabel_termek_koltseg.csv', c.productCost.errors, t))
  }

  if (!c.pnl.present && !c.forecast.present && !c.bank.present && !c.productCost.present) {
    parts.push(`<p class="meta">${escapeHtml(t.noFiles!)}</p>`)
  }
  return `<section>${parts.join('')}</section>`
}

export function renderFinancePage(companies: CompanyData[], opts: { lang: Lang; theme: Theme }): string {
  const t = L[opts.lang]
  const body = companies.length
    ? `<p class="meta">${escapeHtml(t.estimateNote!)}</p>` + companies.map((c) => renderCompany(c, t, opts.lang)).join('')
    : `<p class="meta">${escapeHtml(t.none!)}</p>`
  return pageShell(t.title!, body, opts)
}

// ------------------------------------------------------- subscriptions rendering

const SL: Record<Lang, Record<string, string>> = {
  hu: {
    title: 'Előfizetések', none: 'Az előfizetés-mappában még nincs adat.',
    summary: 'Havi előfizetés cégenként', byCategory: 'Kategóriánként (havi Ft)', trend: 'Tényleges SaaS-terhelés havonta (kivonat)',
    list: 'Tételek', company: 'Cég', category: 'Kategória', monthly: 'Havi díj', projected: 'ebből becslés',
    uncertain: 'bizonytalan', unknownCount: 'ár nem ismert (db)', recurring: 'Ismétlődő díj (nem előfizetés)',
    statement: 'Kivonat', change: 'Változás', provider: 'Szolgáltató', cycle: 'Ciklus', lastCharge: 'Utolsó terhelés',
    renewal: 'Megújulás', status: 'Állapot', usedBy: 'Ki használja', flags: 'Jelölés', details: 'részletek',
    priceUnknown: 'ár nem ismert', estimate: 'becslés', notVerified: 'nem ellenőrzött', trial: 'próbaidő vége',
    origAmount: 'Eredeti díj', cycleHuf: 'Ciklusdíj', fx: 'Árfolyam', source: 'Forrás', note: 'Megjegyzés',
    monthlyNote: 'Havi díj jelölése', renewalNote: 'Megújulás jelölése', verified: 'Ellenőrzés',
    meaning: 'Mit jelent a havi összeg', recurringBadge: 'ismétlődő díj', usageBadge: 'használatalapú',
    estimateNote: '~ és dőlt: becslés (pl. éves díj / 12). Az "ár nem ismert" nem nulla: ott nincs forint-összeg.',
    otherCompanies: 'Cég nem ismert', all: 'Összesen',
  },
  en: {
    title: 'Subscriptions', none: 'No data in the subscriptions folder yet.',
    summary: 'Monthly subscriptions per company', byCategory: 'Per category (HUF a month)', trend: 'Actual SaaS charges per month (statements)',
    list: 'Items', company: 'Company', category: 'Category', monthly: 'Monthly fee', projected: 'of which estimate',
    uncertain: 'uncertain', unknownCount: 'price unknown (items)', recurring: 'Recurring fee (not a subscription)',
    statement: 'Statement', change: 'Change', provider: 'Provider', cycle: 'Cycle', lastCharge: 'Last charge',
    renewal: 'Renewal', status: 'Status', usedBy: 'Used by', flags: 'Flags', details: 'details',
    priceUnknown: 'price unknown', estimate: 'estimate', notVerified: 'not verified', trial: 'trial ends',
    origAmount: 'Original fee', cycleHuf: 'Fee per cycle', fx: 'Exchange rate', source: 'Source', note: 'Note',
    monthlyNote: 'Monthly fee basis', renewalNote: 'Renewal basis', verified: 'Verification',
    meaning: 'What the monthly sum means', recurringBadge: 'recurring fee', usageBadge: 'usage-based',
    estimateNote: '~ and italic: estimate (e.g. yearly fee / 12). "Price unknown" is not zero: there is no HUF amount.',
    otherCompanies: 'Company not known', all: 'Total',
  },
}

/** Juró's fixed slugs (README.md of the folder). An unknown slug is shown as is. */
const SUB_LABELS: Record<Lang, Record<string, Record<string, string>>> = {
  hu: {
    category: { ai: 'AI', felho_hosting: 'Felhő és hosting', szoftver: 'Szoftver', telefon: 'Telefon', domain: 'Domain', egyeb: 'Egyéb', osszesen: 'Összesen' },
    status: { aktiv: 'aktív', uj: 'új', proba: 'próbaidő', ismeretlen: 'ismeretlen', megszunt: 'megszűnt' },
    cycle: { havi: 'havi', eves: 'éves', negyedeves: 'negyedéves', hasznalat: 'használat szerint', feltoltes: 'feltöltés' },
    flag: { duplikalt: 'duplikált', atfedes: 'átfedés', nem_hasznalt_gyanu: 'nem használt?', kozelgo_megujulas: 'közelgő megújulás',
      megszunes_ellenorzendo: 'megszűnés ellenőrzendő', ellenorizendo: 'ellenőrizendő' },
  },
  en: {
    category: { ai: 'AI', felho_hosting: 'Cloud and hosting', szoftver: 'Software', telefon: 'Phone', domain: 'Domain', egyeb: 'Other', osszesen: 'Total' },
    status: { aktiv: 'active', uj: 'new', proba: 'trial', ismeretlen: 'unknown', megszunt: 'ended' },
    cycle: { havi: 'monthly', eves: 'yearly', negyedeves: 'quarterly', hasznalat: 'by usage', feltoltes: 'top-up' },
    flag: { duplikalt: 'duplicate', atfedes: 'overlap', nem_hasznalt_gyanu: 'unused?', kozelgo_megujulas: 'renewal soon',
      megszunes_ellenorzendo: 'check if ended', ellenorizendo: 'to check' },
  },
}
const SUB_CATEGORY_ORDER = ['ai', 'felho_hosting', 'szoftver', 'telefon', 'domain', 'egyeb']
const SUB_STATUS_ORDER: Record<SubStatus, number> = { aktiv: 0, uj: 1, proba: 2, ismeretlen: 3, megszunt: 4 }
/** Flags that ask for a decision are shown louder than "to check". */
const LOUD_FLAGS = new Set(['duplikalt', 'atfedes', 'nem_hasznalt_gyanu', 'kozelgo_megujulas'])
const SUM_COMPANY = 'osszes'
const SUM_CATEGORY = 'osszesen'

function subLabel(kind: string, slug: string, lang: Lang): string {
  return SUB_LABELS[lang][kind]?.[slug] ?? slug
}

function companyLabel(id: string, names: Map<string, string>, t: Record<string, string>): string {
  if (id === SUM_COMPANY) return t.all!
  return names.get(id) ?? id
}

function badge(text: string, cls: string): string {
  return `<span class="badge ${cls}">${escapeHtml(text)}</span>`
}

function moneyOrDash(n: number | null, estimate = false): string {
  return n === null ? '<td class="num">-</td>' : numCell(n, estimate)
}

function subsSummary(rows: SubSummaryRow[], names: Map<string, string>, t: Record<string, string>): string {
  const totals = rows.filter((r) => r.category === SUM_CATEGORY)
  if (!totals.length) return ''
  const months = totals[0]!.statements.map((s) => s.month)
  const hasChange = totals.some((r) => r.change !== null)
  const order = (id: string): number => (id === SUM_COMPANY ? 2 : names.has(id) ? 0 : 1)
  const sorted = [...totals].sort((a, b) => order(a.company) - order(b.company) || a.company.localeCompare(b.company))
  const head = `<tr><th>${escapeHtml(t.company!)}</th><th class="num">${escapeHtml(t.monthly!)}</th><th class="num">${escapeHtml(t.projected!)}</th>` +
    `<th class="num">${escapeHtml(t.uncertain!)}</th><th class="num">${escapeHtml(t.unknownCount!)}</th><th class="num">${escapeHtml(t.recurring!)}</th>` +
    months.map((m) => `<th class="num">${escapeHtml(t.statement!)} ${escapeHtml(m)}</th>`).join('') +
    (hasChange ? `<th class="num">${escapeHtml(t.change!)}</th>` : '') + '</tr>'
  const body = sorted.map((r) => `<tr${r.company === SUM_COMPANY ? ' class="sub"' : ''}><td>${escapeHtml(companyLabel(r.company, names, t))}</td>` +
    numCell(r.monthly) + numCell(r.projected, r.projected !== 0) + numCell(r.uncertain) + `<td class="num">${r.unknownCount}</td>` + numCell(r.recurring) +
    r.statements.map((s) => numCell(s.amount)).join('') + (hasChange ? moneyOrDash(r.change) : '') + '</tr>').join('')
  return `<h3>${escapeHtml(t.summary!)}</h3><div class="wrap"><table class="wide"><thead>${head}</thead><tbody>${body}</tbody></table></div>`
}

function subsByCategory(rows: SubSummaryRow[], names: Map<string, string>, t: Record<string, string>, lang: Lang): string {
  const body = rows.filter((r) => r.category !== SUM_CATEGORY)
  if (!body.length) return ''
  const companies = [...new Set(rows.map((r) => r.company))]
    .sort((a, b) => (a === SUM_COMPANY ? 1 : 0) - (b === SUM_COMPANY ? 1 : 0) || a.localeCompare(b))
  const cats = [...new Set(body.map((r) => r.category))]
    .sort((a, b) => ((SUB_CATEGORY_ORDER.indexOf(a) + 1 || 99) - (SUB_CATEGORY_ORDER.indexOf(b) + 1 || 99)) || a.localeCompare(b))
  const cell = (company: string, cat: string): string => {
    const r = rows.find((x) => x.company === company && x.category === cat)
    return r ? numCell(r.monthly, r.projected !== 0) : '<td class="num">-</td>'
  }
  const changeOf = (cat: string): string => {
    const r = rows.find((x) => x.company === SUM_COMPANY && x.category === cat)
    return r && r.change !== null ? numCell(r.change) : '<td class="num">-</td>'
  }
  const hasChange = rows.some((r) => r.company === SUM_COMPANY && r.change !== null)
  return `<h3>${escapeHtml(t.byCategory!)}</h3><div class="wrap"><table><thead><tr><th>${escapeHtml(t.category!)}</th>${
    companies.map((c) => `<th class="num">${escapeHtml(companyLabel(c, names, t))}</th>`).join('')}${
    hasChange ? `<th class="num">${escapeHtml(t.change!)}</th>` : ''}</tr></thead><tbody>${
    [...cats, SUM_CATEGORY].map((cat) => `<tr${cat === SUM_CATEGORY ? ' class="sub"' : ''}><td>${escapeHtml(subLabel('category', cat, lang))}</td>${
      companies.map((c) => cell(c, cat)).join('')}${hasChange ? changeOf(cat) : ''}</tr>`).join('')
  }</tbody></table></div>`
}

const SERIES_CLASS = ['s1', 's2', 's3', 's4']

/** Grouped bars: per month, one bar per company (sum over categories). */
function subsTrend(rows: SubChargeRow[], names: Map<string, string>, t: Record<string, string>): string {
  if (!rows.length) return ''
  const companies = [...new Set(rows.map((r) => r.company))].sort()
  const months = [...new Set(rows.map((r) => r.month))].sort().slice(-12)
  const sum = new Map<string, number>()
  for (const r of rows) sum.set(`${r.company}\u0000${r.month}`, (sum.get(`${r.company}\u0000${r.month}`) ?? 0) + r.amount)
  const W = 640, H = 200, pad = 28
  const max = Math.max(1, ...[...sum.values()])
  const slot = (W - pad) / months.length
  const bw = Math.max(2, Math.min(16, (slot - 4) / companies.length))
  const y = (v: number): number => H - pad - (Math.max(0, v) / max) * (H - 2 * pad)
  const bars = months.map((m, i) => {
    const x0 = pad + i * slot + slot / 2 - (bw * companies.length) / 2
    const label = `<text class="ax" x="${coord(pad + i * slot + slot / 2)}" y="${H - 8}" text-anchor="middle">${escapeHtml(m.slice(2))}</text>`
    return companies.map((c, j) => {
      const v = sum.get(`${c}\u0000${m}`) ?? 0
      return `<rect class="${SERIES_CLASS[j % SERIES_CLASS.length]}" x="${coord(x0 + j * bw)}" y="${coord(y(v))}" width="${coord(bw - 1)}" height="${coord(H - pad - y(v))}"/>`
    }).join('') + label
  }).join('')
  const legend = companies.map((c, j) => `<span class="sw ${SERIES_CLASS[j % SERIES_CLASS.length]}"></span>${escapeHtml(companyLabel(c, names, t))}`).join(' ')
  return `<h3>${escapeHtml(t.trend!)}</h3><svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${escapeHtml(t.trend!)}">` +
    `<line class="base" x1="${pad}" y1="${H - pad}" x2="${W}" y2="${H - pad}"/>` +
    `<text class="ax" x="${pad}" y="${pad - 8}">${escapeHtml(fmtHuf(max))}</text>${bars}</svg><p class="legend">${legend}</p>`
}

function subItemRow(r: SubscriptionRow, t: Record<string, string>, lang: Lang): string {
  const badges: string[] = []
  if (!r.verified) badges.push(badge(t.notVerified!, 'b-unv'))
  for (const f of r.flags) badges.push(badge(subLabel('flag', f, lang), LOUD_FLAGS.has(f) ? 'b-loud' : 'b-flag'))
  const typeBadge = r.type === 'ismetlodo_dij' ? badge(t.recurringBadge!, 'b-type') : r.type === 'hasznalatalapu' ? badge(t.usageBadge!, 'b-type') : ''
  const monthly = r.monthlyHuf === null
    ? `<td class="num unk">${escapeHtml(t.priceUnknown!)}</td>`
    : `<td class="num${r.monthlyEstimate ? ' est' : ''}">${r.monthlyEstimate ? '~' : ''}${escapeHtml(fmtHuf(r.monthlyHuf))}${
      r.monthlyEstimate ? ` ${badge(t.estimate!, 'b-type')}` : ''}</td>`
  const detail: Array<[string, string]> = [
    [t.origAmount!, [r.origAmount, r.currency].filter(Boolean).join(' ')],
    [t.cycleHuf!, r.cycleHuf === null ? '' : fmtHuf(r.cycleHuf)],
    [t.monthlyNote!, r.monthlyNote],
    [t.fx!, r.fxSource],
    [t.lastCharge!, r.lastChargeHuf === null ? '' : fmtHuf(r.lastChargeHuf)],
    [t.renewalNote!, r.renewalNote],
    [t.source!, [r.sourceType, r.source].filter(Boolean).join(': ')],
    [t.verified!, r.verifiedNote],
    [t.note!, r.note],
  ].filter((d): d is [string, string] => d[1] !== '')
  const details = detail.length
    ? `<details><summary>${escapeHtml(t.details!)}</summary><dl>${detail.map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd>`).join('')}</dl></details>`
    : ''
  const renewal = [r.renewal, r.trialEnd ? `${t.trial!}: ${r.trialEnd}` : ''].filter(Boolean).join('; ')
  const cls = [r.status === 'megszunt' ? 'ended' : '', r.verified ? '' : 'unv'].filter(Boolean).join(' ')
  return `<tr${cls ? ` class="${cls}"` : ''}><td><strong>${escapeHtml(r.provider)}</strong>${r.plan ? `<div class="plan">${escapeHtml(r.plan)}</div>` : ''}${details}</td>${monthly}` +
    `<td>${escapeHtml(subLabel('category', r.category, lang))}${typeBadge ? ` ${typeBadge}` : ''}</td>` +
    `<td>${escapeHtml(subLabel('cycle', r.cycle, lang))}</td>` +
    `<td>${escapeHtml(r.lastCharge || '-')}</td><td>${escapeHtml(renewal || '-')}</td>` +
    `<td>${escapeHtml(subLabel('status', r.status, lang))}</td><td>${escapeHtml(r.usedBy || '-')}</td><td>${badges.join(' ')}</td></tr>`
}

function subsList(rows: SubscriptionRow[], names: Map<string, string>, t: Record<string, string>, lang: Lang): string {
  if (!rows.length) return ''
  // Known companies first (in name order), then any other value (e.g. "nem ismert") as its own group, never dropped.
  const groups = [...new Set(rows.map((r) => r.company))]
    .sort((a, b) => (names.has(a) ? 0 : 1) - (names.has(b) ? 0 : 1) || a.localeCompare(b))
  // The monthly fee is the second column and the provider column sticks: on a phone the
  // table scrolls sideways, and the fee and the name must stay in view (2026-10-14 screen check).
  const head = `<tr><th>${escapeHtml(t.provider!)}</th><th class="num">${escapeHtml(t.monthly!)}</th><th>${escapeHtml(t.category!)}</th>` +
    `<th>${escapeHtml(t.cycle!)}</th><th>${escapeHtml(t.lastCharge!)}</th><th>${escapeHtml(t.renewal!)}</th>` +
    `<th>${escapeHtml(t.status!)}</th><th>${escapeHtml(t.usedBy!)}</th><th>${escapeHtml(t.flags!)}</th></tr>`
  const body = groups.map((g) => {
    const items = rows.filter((r) => r.company === g).sort((a, b) =>
      SUB_STATUS_ORDER[a.status] - SUB_STATUS_ORDER[b.status] ||
      (b.monthlyHuf ?? -1) - (a.monthlyHuf ?? -1) || a.provider.localeCompare(b.provider))
    const label = names.has(g) ? names.get(g)! : `${g} (${t.otherCompanies!})`
    return `<tr class="prod"><th colspan="9"><span class="stick">${escapeHtml(label)}</span></th></tr>` + items.map((r) => subItemRow(r, t, lang)).join('')
  }).join('')
  return `<h3>${escapeHtml(t.list!)}</h3><div class="wrap"><table class="wide items"><thead>${head}</thead><tbody>${body}</tbody></table></div>`
}

export function renderSubscriptionsPage(data: SubscriptionsData, names: Map<string, string>, opts: { lang: Lang; theme: Theme }): string {
  const t = SL[opts.lang]
  const ft = L[opts.lang]
  if (!data.present) return pageShell(t.title!, `<p class="meta">${escapeHtml(t.none!)}</p>`, opts)
  const m = data.meta
  const parts: string[] = [`<h2>${escapeHtml(t.title!)}</h2>`]
  for (const w of m.warnings) parts.push(`<p class="warn">${escapeHtml(ft.warnings!)}: ${escapeHtml(w)}</p>`)
  if (m.generated) parts.push(`<p class="meta">${escapeHtml(ft.generated!)}: ${escapeHtml(m.generated)}</p>`)
  if (m.basis) parts.push(`<p class="basis">${escapeHtml(ft.basis!)}: ${escapeHtml(m.basis)}</p>`)
  if (m.meaning) parts.push(`<details class="meta"><summary>${escapeHtml(t.meaning!)}</summary><p>${escapeHtml(m.meaning)}</p></details>`)
  parts.push(`<p class="meta">${escapeHtml(t.estimateNote!)}</p>`, errorsBlock('meta.json', data.metaErrors, ft))
  if (data.summary.present) {
    parts.push(subsSummary(data.summary.rows, names, t), subsByCategory(data.summary.rows, names, t, opts.lang))
    if (m.change) parts.push(`<p class="meta">${escapeHtml(m.change)}</p>`)
    parts.push(errorsBlock('osszesito.csv', data.summary.errors, ft))
  }
  if (data.charges.present) parts.push(subsTrend(data.charges.rows, names, t), errorsBlock('havi_terheles.csv', data.charges.errors, ft))
  if (data.items.present) parts.push(subsList(data.items.rows, names, t, opts.lang), errorsBlock('elofizetesek.csv', data.items.errors, ft))
  if (m.sources.length) parts.push(`<p class="meta">${escapeHtml(ft.sources!)}: ${m.sources.map(escapeHtml).join('; ')}</p>`)
  if (m.notIncluded.length) parts.push(`<p class="meta">${escapeHtml(ft.notIncluded!)}: ${m.notIncluded.map(escapeHtml).join('; ')}</p>`)
  return pageShell(t.title!, `<section>${parts.join('')}</section>`, opts)
}

const STYLE_LIGHT = '--stick:#faf9f5;--fg:#1f2328;--muted:#656d76;--line:#d0d7de;--inc:#1a7f37;--cost:#cf222e;--neg:#cf222e;--tot:#0969da;--warn-bg:#fff8c5;--warn-fg:#4d2d00;--s1:#0969da;--s2:#bf8700;--s3:#8250df;--s4:#1a7f37;--badge:#eaeef2;--loud-bg:#ffebe9;--loud-fg:#a40e26'
const STYLE_DARK = '--stick:#141413;--fg:#e6edf3;--muted:#8d96a0;--line:#30363d;--inc:#3fb950;--cost:#f85149;--neg:#f85149;--tot:#58a6ff;--warn-bg:#3b2e00;--warn-fg:#f2cc60;--s1:#58a6ff;--s2:#d29922;--s3:#a371f7;--s4:#3fb950;--badge:#30363d;--loud-bg:#4c1d24;--loud-fg:#ffa198'

function pageShell(title: string, body: string, opts: { lang: Lang; theme: Theme }): string {
  const vars = opts.theme === 'dark' ? STYLE_DARK : STYLE_LIGHT
  return `<!doctype html><html lang="${opts.lang}"><head><meta charset="utf-8">` +
    `<meta name="viewport" content="width=device-width, initial-scale=1">` +
    `<meta http-equiv="Content-Security-Policy" content="${escapeHtml(FINANCE_DOC_CSP)}">` +
    `<title>${escapeHtml(title)}</title><style>
:root{${vars}}
body{margin:0;padding:16px;background:transparent;color:var(--fg);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
section{margin:0 0 36px}h2{margin:0 0 4px;font-size:20px}h3{margin:20px 0 8px;font-size:15px}
.meta{color:var(--muted);margin:0 0 6px}.basis{margin:0 0 6px;font-weight:600}
.warn{background:var(--warn-bg);color:var(--warn-fg);padding:6px 10px;border-radius:6px;margin:0 0 8px;font-weight:600}
table{border-collapse:collapse;width:100%;max-width:820px;margin:4px 0}
th,td{border-bottom:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.neg{color:var(--neg)}
.est{font-style:italic}tr.gap td{color:var(--muted)}.gaptxt{text-align:center;font-style:italic}
tr.sub th,tr.sub td,tfoot th{font-weight:600}tr.prod th{padding-top:12px;border-bottom:2px solid var(--line)}
.chart{width:100%;max-width:820px;height:auto;display:block}
.chart .base,.chart .zero{stroke:var(--line);stroke-width:1}.chart .zero{stroke-dasharray:2 3}
.chart .ax{fill:var(--muted);font-size:10px}.chart .gap{font-style:italic}
.b-inc{fill:var(--inc)}.b-cost{fill:var(--cost)}.b-inc.est,.b-cost.est{opacity:.55}
polyline{fill:none;stroke-width:2}polyline.tot{stroke:var(--tot)}polyline.dash{stroke-dasharray:6 4}polyline.dot{stroke-dasharray:1 4;stroke-linecap:round}
.legend{color:var(--muted);font-size:12px;margin:2px 0 8px}
.sw{display:inline-block;width:10px;height:10px;margin:0 4px 0 8px;vertical-align:middle}
.sw-inc{background:var(--inc)}.sw-cost{background:var(--cost)}
.events{margin:0 0 8px;padding-left:20px;color:var(--muted)}
.errs{color:var(--neg);font-size:12px;margin:4px 0}
details.meta summary{cursor:default}
.wrap{max-width:100%;overflow-x:auto}table.wide{max-width:none;min-width:720px}table.items{min-width:980px}
.s1{fill:var(--s1)}.s2{fill:var(--s2)}.s3{fill:var(--s3)}.s4{fill:var(--s4)}
.sw.s1{background:var(--s1)}.sw.s2{background:var(--s2)}.sw.s3{background:var(--s3)}.sw.s4{background:var(--s4)}
.badge{display:inline-block;padding:0 6px;border-radius:9px;background:var(--badge);font-size:11px;font-style:normal;white-space:nowrap;margin:1px 0}
.b-loud,.b-unv{background:var(--loud-bg);color:var(--loud-fg);font-weight:600}
.plan{color:var(--muted);font-size:12px}.unk{color:var(--muted);font-style:italic}
tr.ended td{color:var(--muted)}tr.unv td:first-child{box-shadow:inset 3px 0 0 var(--loud-fg)}
.items details{font-size:12px;color:var(--muted)}.items dl{margin:4px 0;display:grid;grid-template-columns:max-content 1fr;gap:2px 8px}
.items td:first-child,.items thead th:first-child{position:sticky;left:0;z-index:1;background:var(--stick);min-width:150px;max-width:180px}
.items .stick{position:sticky;left:8px}
.items dt{font-weight:600}.items dd{margin:0;overflow-wrap:anywhere}
</style></head><body>${body}</body></html>`
}
