// HAVIZARAS1016: the "Havi zárás" (monthly closing) view of the finance tab.
// Patrik (TG 3180/3182, card eb885bd3) wants one glance per company and month:
// where the closing stands, and what waits on him. The finance agent (Juró)
// writes one machine state file per company and month; this module only reads,
// validates and renders them. Contract: <FINANCE_DIR>/zaras/SEMA.md (v1) and
// docs/penzugy-ful.md.
//
// Layout under the finance root:
//   <root>/zaras/<company>/<YYYY-MM>.json
// The company directories use the same names as the company folders of the
// overview (myshp, notramit), so the display name comes from their meta.json.
//
// Same reader rules as the rest of the finance tab (finance.ts header): the
// zaras folder and every company folder are lstat'd and a symlink is not
// followed, files go through readCapped (O_NOFOLLOW, regular file, size cap),
// only names matching the fixed patterns are read, every string is
// length-capped, and every value is escaped on output. The page goes into the
// same sandboxed srcdoc iframe, so the details are <details> elements: no
// script is needed (or allowed) to open a month.

import { lstatSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { CLOSING_DIR, escapeHtml, fmtHuf, pageShell, readCapped, type Lang, type Theme } from './finance.js'

export { CLOSING_DIR }
export const CLOSING_MAX_FILE_BYTES = 256 * 1024
export const CLOSING_MAX_MISSING = 300
export const CLOSING_MAX_TASKS = 50
export const CLOSING_MAX_COMPANIES = 10
export const CLOSING_MAX_MONTHS = 24
/** Patrik's first month (Klodel 6755): the grid starts here even when a month has no file yet. */
export const CLOSING_FIRST_MONTH = '2026-07'

const COMPANY_RE = /^[a-z0-9_-]{1,32}$/
const MONTH_FILE_RE = /^(\d{4}-(0[1-9]|1[0-2]))\.json$/
const DATE_RE = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/
const MAX_TEXT = 300
const MAX_SUPPLIER = 80
const MAX_ERRORS = 10

export const CLOSING_STATUSES = ['KESZ', 'CSOMAG_KESZ', 'FOLYAMATBAN', 'NINCS_ELKEZDVE'] as const
export type ClosingStatus = (typeof CLOSING_STATUSES)[number] | 'ismeretlen'
export const MISSING_REASONS = ['papir', 'patrikra_var', 'szolgaltatotol_kertuk', 'csapat_dolgozik'] as const
export type MissingReason = (typeof MISSING_REASONS)[number] | 'ismeretlen'
const SCHEMA = 'zaras-allapot/v1'
const CURRENCY_RE = /^[A-Z]{3}$/

export interface MissingItem {
  id: string
  date: string | null
  supplier: string
  amount: number | null
  currency: string
  amountFt: number | null
  reason: MissingReason
  task: string
  owner: string
  waitsOnPatrik: boolean
}

export interface NavSide {
  db: number | null; netFt: number | null; vatFt: number | null; diffNetFt: number | null
  /** Incoming only: our own NAV list's gross and its difference (SEMA.md v1 addition); null = no own list. */
  ownGrossFt: number | null; diffGrossFt: number | null
}

export interface ClosingMonth {
  company: string
  month: string
  errors: string[]
  companyName: string
  updated: string
  updatedBy: string
  status: ClosingStatus
  statusText: string
  /** guess: the date is not from a fixed rule (hatarido.tipp), shown with a "tipp" mark. */
  deadline: { date: string | null; what: string; source: string; guess: boolean } | null
  sent: { date: string | null; by: string; source: string } | null
  statements: Array<{ account: string; has: boolean | null; complete: boolean | null; note: string }>
  charges: {
    totalDb: number | null; totalFt: number | null; invoicedDb: number | null; invoicedFt: number | null
    notNeededDb: number | null; notNeededFt: number | null; missingDb: number | null; missingFt: number | null
  }
  income: { db: number | null; netFt: number | null; grossFt: number | null; ok: boolean | null; note: string }
  nav: { out: NavSide | null; in: NavSide | null; queried: string }
  missing: MissingItem[]
  who: Array<{ who: string; what: string }>
  notes: string[]
  sources: string[]
}

export interface ClosingData {
  present: boolean
  companies: string[]
  months: string[]
  /** key `${company}\u0000${month}` -> the month's state; a missing key is "no file". */
  cells: Map<string, ClosingMonth>
  /** A file that exists but could not be read or parsed: shown as an error, never as data. */
  fileErrors: Array<{ company: string; month: string; error: string }>
}

function cap(s: string, max: number): string {
  return s.length > max ? `${s.slice(0, max - 1)}…` : s
}

function text(v: unknown, max = MAX_TEXT): string {
  return typeof v === 'string' ? cap(v.trim(), max) : ''
}

function obj(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {}
}

function list(v: unknown, field: string, errors: string[], max: number): unknown[] {
  if (v === undefined || v === null) return []
  if (!Array.isArray(v)) { pushErr(errors, `${field}: nem lista`); return [] }
  if (v.length > max) pushErr(errors, `${field}: ${v.length} tétel, az első ${max} látszik`)
  return v.slice(0, max)
}

function pushErr(errors: string[], msg: string): void {
  if (errors.length < MAX_ERRORS) errors.push(msg)
}

/** A whole number or null; anything else is an error and reads as null (never as 0). */
function whole(v: unknown, field: string, errors: string[], allowNegative = false): number | null {
  if (v === null || v === undefined) return null
  if (typeof v === 'number' && Number.isSafeInteger(v) && (allowNegative || v >= 0)) return v
  pushErr(errors, `${field}: nem egész szám`)
  return null
}

/**
 * A forint amount that may arrive with decimals (the NAV amounts come with
 * fillér, SEMA.md v1 addition), rounded to whole forints; null stays null.
 */
function forint(v: unknown, field: string, errors: string[]): number | null {
  if (v === null || v === undefined) return null
  if (typeof v === 'number' && Number.isFinite(v) && Math.abs(v) < 1e15) return Math.round(v)
  pushErr(errors, `${field}: nem szám`)
  return null
}

/** A finite number (a foreign-currency amount may have decimals) or null. */
function finite(v: unknown, field: string, errors: string[]): number | null {
  if (v === null || v === undefined) return null
  if (typeof v === 'number' && Number.isFinite(v) && Math.abs(v) < 1e15) return v
  pushErr(errors, `${field}: nem szám`)
  return null
}

function bool(v: unknown, field: string, errors: string[]): boolean | null {
  if (v === null || v === undefined) return null
  if (typeof v === 'boolean') return v
  pushErr(errors, `${field}: nem igaz/hamis`)
  return null
}

function dateOrNull(v: unknown, field: string, errors: string[]): string | null {
  if (v === null || v === undefined || v === '') return null
  if (typeof v === 'string' && DATE_RE.test(v)) return v
  pushErr(errors, `${field}: nem ÉÉÉÉ-HH-NN dátum`)
  return null
}

function oneOf<T extends string>(v: unknown, allowed: readonly T[], field: string, errors: string[]): T | 'ismeretlen' {
  if (typeof v === 'string' && (allowed as readonly string[]).includes(v)) return v as T
  pushErr(errors, `${field}: ismeretlen érték`)
  return 'ismeretlen'
}

function navSide(v: unknown, field: string, errors: string[]): NavSide | null {
  if (v === undefined || v === null) return null
  const o = obj(v)
  return {
    db: whole(o.db, `${field}.db`, errors),
    netFt: forint(o.netto_ft, `${field}.netto_ft`, errors),
    vatFt: forint(o.afa_ft, `${field}.afa_ft`, errors),
    diffNetFt: forint(o.elteres_netto_ft, `${field}.elteres_netto_ft`, errors),
    ownGrossFt: forint(o.sajat_brutto_ft, `${field}.sajat_brutto_ft`, errors),
    diffGrossFt: forint(o.elteres_brutto_ft, `${field}.elteres_brutto_ft`, errors),
  }
}

/** Parse one month file (Juró's SEMA.md v1). Unknown keys are ignored; a bad field is an error and its value is dropped, not guessed. */
export function parseClosingMonth(textIn: string, company: string, month: string): ClosingMonth | { error: string } {
  let raw: unknown
  try { raw = JSON.parse(textIn) } catch { return { error: 'nem érvényes JSON' } }
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return { error: 'nem JSON-objektum' }
  const d = raw as Record<string, unknown>
  const errors: string[] = []
  if (d.schema !== SCHEMA) pushErr(errors, `schema: nem ${SCHEMA}`)
  if (d.ceg !== undefined && d.ceg !== company) pushErr(errors, 'ceg: nem egyezik a mappanévvel')
  if (d.honap !== undefined && d.honap !== month) pushErr(errors, 'honap: nem egyezik a fájlnévvel')

  const deadline = d.hatarido === undefined || d.hatarido === null ? null : (() => {
    const o = obj(d.hatarido)
    return { date: dateOrNull(o.datum, 'hatarido.datum', errors), what: text(o.mire), source: text(o.forras),
      guess: bool(o.tipp, 'hatarido.tipp', errors) === true }
  })()
  const sent = d.elkuldve === undefined || d.elkuldve === null ? null : (() => {
    const o = obj(d.elkuldve)
    return { date: dateOrNull(o.datum, 'elkuldve.datum', errors), by: text(o.ki, 40), source: text(o.forras) }
  })()
  const statements = list(d.kivonatok, 'kivonatok', errors, 20).map((k, i) => {
    const o = obj(k)
    return { account: text(o.szamla, MAX_SUPPLIER) || '?', has: bool(o.megvan, `kivonatok[${i}].megvan`, errors),
      complete: bool(o.teljes, `kivonatok[${i}].teljes`, errors), note: text(o.megjegyzes) }
  })
  const ch = obj(d.terhelesek)
  const inc = obj(d.bevetel)
  const nav = obj(d.nav)
  const missing: MissingItem[] = list(d.hianyok, 'hianyok', errors, CLOSING_MAX_MISSING).map((m, i) => {
    const o = obj(m)
    const currency = text(o.penznem, 3)
    if (o.penznem !== undefined && o.penznem !== null && !CURRENCY_RE.test(currency)) pushErr(errors, `hianyok[${i}].penznem: nem ISO pénznem`)
    return {
      id: text(o.id, 60),
      date: dateOrNull(o.datum, `hianyok[${i}].datum`, errors),
      supplier: text(o.szallito, MAX_SUPPLIER) || '?',
      amount: finite(o.osszeg, `hianyok[${i}].osszeg`, errors),
      currency: CURRENCY_RE.test(currency) ? currency : '',
      amountFt: whole(o.osszeg_ft, `hianyok[${i}].osszeg_ft`, errors, true),
      reason: oneOf(o.ok, MISSING_REASONS, `hianyok[${i}].ok`, errors),
      task: text(o.teendo),
      owner: text(o.kie, 40),
      waitsOnPatrik: o.patrikra_var === true,
    }
  })
  const who = list(d.ki_dolgozik, 'ki_dolgozik', errors, CLOSING_MAX_TASKS).map((w) => {
    const o = obj(w)
    return { who: text(o.ki, 40), what: text(o.min) }
  }).filter((w) => w.who || w.what)
  const notes = list(d.megjegyzesek, 'megjegyzesek', errors, 20).map((x) => text(x)).filter(Boolean)
  const sources = list(d.forrasok, 'forrasok', errors, 20).map((x) => text(x)).filter(Boolean)

  return {
    company,
    month,
    errors,
    companyName: text(d.ceg_nev, MAX_SUPPLIER),
    updated: text(d.frissitve, 40),
    updatedBy: text(d.frissitette, 40),
    status: oneOf(d.allapot, CLOSING_STATUSES, 'allapot', errors),
    statusText: text(d.allapot_szoveg),
    deadline,
    sent,
    statements,
    charges: {
      totalDb: whole(ch.osszes_db, 'terhelesek.osszes_db', errors), totalFt: whole(ch.osszes_ft, 'terhelesek.osszes_ft', errors),
      invoicedDb: whole(ch.szamlaval_db, 'terhelesek.szamlaval_db', errors), invoicedFt: whole(ch.szamlaval_ft, 'terhelesek.szamlaval_ft', errors),
      notNeededDb: whole(ch.nem_kell_db, 'terhelesek.nem_kell_db', errors), notNeededFt: whole(ch.nem_kell_ft, 'terhelesek.nem_kell_ft', errors),
      missingDb: whole(ch.hianyzik_db, 'terhelesek.hianyzik_db', errors), missingFt: whole(ch.hianyzik_ft, 'terhelesek.hianyzik_ft', errors),
    },
    income: {
      db: whole(inc.billingo_db, 'bevetel.billingo_db', errors),
      netFt: whole(inc.billingo_netto_ft, 'bevetel.billingo_netto_ft', errors, true),
      grossFt: whole(inc.billingo_brutto_ft, 'bevetel.billingo_brutto_ft', errors, true),
      ok: bool(inc.rendben, 'bevetel.rendben', errors),
      note: text(inc.megjegyzes),
    },
    nav: { out: navSide(nav.kimeno, 'nav.kimeno', errors), in: navSide(nav.bejovo, 'nav.bejovo', errors), queried: text(nav.lekerdezve, 40) },
    missing,
    who,
    notes,
    sources,
  }
}

function isPlainDir(path: string): boolean {
  try { return lstatSync(path).isDirectory() } catch { return false }
}

/** Every month from `from` to `to` inclusive (YYYY-MM). */
export function monthRange(from: string, to: string): string[] {
  const out: string[] = []
  let [y, m] = from.split('-').map(Number) as [number, number]
  const [ty, tm] = to.split('-').map(Number) as [number, number]
  while ((y < ty || (y === ty && m <= tm)) && out.length < 120) {
    out.push(`${y}-${String(m).padStart(2, '0')}`)
    m += 1
    if (m > 12) { m = 1; y += 1 }
  }
  return out
}

/** `month` (YYYY-MM) shifted by `delta` months. */
export function addMonths(month: string, delta: number): string {
  const [y, m] = month.split('-').map(Number) as [number, number]
  const idx = y * 12 + (m - 1) + delta
  return `${Math.floor(idx / 12)}-${String((idx % 12) + 1).padStart(2, '0')}`
}

/** The month before `today` (YYYY-MM-DD): the latest month that can be closed. */
export function previousMonth(today: string): string {
  const [y, m] = today.split('-').map(Number) as [number, number]
  return m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, '0')}`
}

/**
 * Load <root>/zaras/. The grid's months run from CLOSING_FIRST_MONTH (or an
 * earlier file) to the later of last month and the newest file, newest last.
 * The window is anchored at its end: it never reaches past the current month
 * and never back more than CLOSING_MAX_MONTHS, so a file with an odd month in
 * its name (0001-01, 9999-12) is listed as a file error instead of pushing the
 * current months out of the grid (Viktor 6826, L1).
 */
export function loadClosing(root: string, today: string): ClosingData {
  const dir = join(root, CLOSING_DIR)
  const empty: ClosingData = { present: false, companies: [], months: [], cells: new Map(), fileErrors: [] }
  if (!isPlainDir(dir)) return empty
  let entries
  try { entries = readdirSync(dir, { withFileTypes: true }) } catch { return empty }
  const companies = entries
    .filter((e) => e.isDirectory() && COMPANY_RE.test(e.name))
    .map((e) => e.name)
    .sort()
    .slice(0, CLOSING_MAX_COMPANIES)
  const cells = new Map<string, ClosingMonth>()
  const fileErrors: ClosingData['fileErrors'] = []
  const fileMonths = new Set<string>()
  const lastClosable = previousMonth(today)
  const thisMonth = today.slice(0, 7)
  const oldest = addMonths(lastClosable, -(CLOSING_MAX_MONTHS - 1))
  for (const company of companies) {
    const cdir = join(dir, company)
    let files: string[]
    try { files = readdirSync(cdir) } catch { continue }
    for (const f of files.sort()) {
      const mm = MONTH_FILE_RE.exec(f)
      if (!mm) continue
      const month = mm[1]!
      if (month > thisMonth || month < oldest) {
        fileErrors.push({ company, month, error: `a hónap a megjelenített ${oldest} – ${thisMonth} tartományon kívül esik` })
        continue
      }
      fileMonths.add(month)
      const read = readCapped(join(cdir, f), CLOSING_MAX_FILE_BYTES)
      if (!read.ok) {
        if (read.reason !== 'missing') fileErrors.push({ company, month, error: `nem olvasható (${read.reason})` })
        continue
      }
      const parsed = parseClosingMonth(read.text, company, month)
      if ('error' in parsed) fileErrors.push({ company, month, error: parsed.error })
      else cells.set(`${company}\u0000${month}`, parsed)
    }
  }
  const sorted = [...fileMonths].sort()
  const newest = sorted[sorted.length - 1]
  const last = newest && newest > lastClosable ? newest : lastClosable
  const wanted = sorted[0] && sorted[0] < CLOSING_FIRST_MONTH ? sorted[0] : CLOSING_FIRST_MONTH
  const floor = addMonths(last, -(CLOSING_MAX_MONTHS - 1))
  const months = monthRange(wanted > floor ? wanted : floor, last)
  return { present: companies.length > 0, companies, months, cells, fileErrors }
}

// ------------------------------------------------------------------ rendering

const CL: Record<Lang, Record<string, string>> = {
  hu: {
    title: 'Havi zárás', none: 'Még nincs zárási állapotfájl (zaras/<cég>/<ÉÉÉÉ-HH>.json).',
    yours: 'TŐLED KELL', yoursNone: 'Most nincs rád váró tétel.', month: 'Hónap', noFile: 'nincs adat',
    st_KESZ: 'KÉSZ', st_CSOMAG_KESZ: 'CSOMAG KÉSZ', st_FOLYAMATBAN: 'FOLYAMATBAN', st_NINCS_ELKEZDVE: 'NINCS ELKEZDVE', st_ismeretlen: 'ISMERETLEN',
    sent: 'Heninek elküldve', waitingSend: 'küldésre vár', invoiced: 'számlával', missingN: 'hiányzik', notNeeded: 'nem kell számla',
    deadline: 'Határidő', overdue: 'lejárt', details: 'Részletek hónaponként', statement: 'Bankkivonat', has: 'megvan', hasNot: 'HIÁNYZIK',
    incomplete: 'nem teljes', noData: 'nincs adat', charges: 'Terhelések', income: 'Bevétel (Billingo)', nav: 'NAV',
    navOut: 'kimenő', navIn: 'bejövő', navMatch: 'egyezik', navDiff: 'ELTÉRÉS', navNone: 'még nincs NAV-adat', queried: 'lekérdezve',
    ok: 'rendben', notOk: 'ELTÉRÉS', unchecked: 'nincs ellenőrizve', invoices: 'számla', net: 'nettó', gross: 'bruttó', vat: 'áfa',
    who: 'Ki min dolgozik', updated: 'Frissítve', sources: 'Források', notes: 'Megjegyzések', guess: 'tipp', ownList: 'saját lista bruttó', by: 'küldte',
    missingList: 'Hiánylista', supplier: 'Szállító', date: 'Dátum', amount: 'Összeg', reason: 'Ok', task: 'Teendő', owner: 'Kié',
    r_papir: 'papíron van', r_patrikra_var: 'rád vár', r_szolgaltatotol_kertuk: 'szolgáltatótól kértük', r_csapat_dolgozik: 'a csapat dolgozik rajta', r_ismeretlen: 'ismeretlen',
    noMissing: 'Nincs hiányzó számla.', fileErrors: 'Hibás fájlok (nem jelennek meg)', errors: 'Hibák a fájlban (a hibás mezők kimaradtak)',
  },
  en: {
    title: 'Monthly closing', none: 'No closing state file yet (zaras/<company>/<YYYY-MM>.json).',
    yours: 'NEEDS YOU', yoursNone: 'Nothing is waiting on you now.', month: 'Month', noFile: 'no data',
    st_KESZ: 'DONE', st_CSOMAG_KESZ: 'PACKAGE READY', st_FOLYAMATBAN: 'IN PROGRESS', st_NINCS_ELKEZDVE: 'NOT STARTED', st_ismeretlen: 'UNKNOWN',
    sent: 'Sent to Heni', waitingSend: 'waiting to be sent', invoiced: 'with invoice', missingN: 'missing', notNeeded: 'no invoice needed',
    deadline: 'Deadline', overdue: 'overdue', details: 'Details by month', statement: 'Bank statement', has: 'present', hasNot: 'MISSING',
    incomplete: 'incomplete', noData: 'no data', charges: 'Charges', income: 'Income (Billingo)', nav: 'NAV',
    navOut: 'outgoing', navIn: 'incoming', navMatch: 'matches', navDiff: 'DIFFERENCE', navNone: 'no NAV data yet', queried: 'queried',
    ok: 'in order', notOk: 'DIFFERENCE', unchecked: 'not checked', invoices: 'invoices', net: 'net', gross: 'gross', vat: 'VAT',
    who: 'Who works on what', updated: 'Updated', sources: 'Sources', notes: 'Notes', guess: 'estimate', ownList: 'own list gross', by: 'sent by',
    missingList: 'Missing invoices', supplier: 'Supplier', date: 'Date', amount: 'Amount', reason: 'Reason', task: 'To do', owner: 'Owner',
    r_papir: 'on paper', r_patrikra_var: 'waits on you', r_szolgaltatotol_kertuk: 'requested from supplier', r_csapat_dolgozik: 'team is on it', r_ismeretlen: 'unknown',
    noMissing: 'No missing invoice.', fileErrors: 'Invalid files (not shown)', errors: 'Problems in the file (invalid fields skipped)',
  },
}

const STATUS_CLASS: Record<ClosingStatus, string> = {
  KESZ: 'z-done', CSOMAG_KESZ: 'z-ready', FOLYAMATBAN: 'z-prog', NINCS_ELKEZDVE: 'z-none', ismeretlen: 'z-unk',
}

const NUM = new Intl.NumberFormat('hu-HU', { maximumFractionDigits: 2 })

function companyLabel(id: string, names: Map<string, string>, data?: ClosingData): string {
  if (names.has(id)) return names.get(id)!
  // Fall back to the state files' own ceg_nev, then the folder name.
  for (const c of data?.cells.values() ?? []) if (c.company === id && c.companyName) return c.companyName
  return id
}

function statusBadge(s: ClosingStatus, t: Record<string, string>): string {
  return `<span class="zst ${STATUS_CLASS[s]}">${escapeHtml(t[`st_${s}`]!)}</span>`
}

function huf(n: number | null, t: Record<string, string>): string {
  return n === null ? t.noData! : fmtHuf(n)
}

/** A missing item's amount: forint first, the original currency beside it; "no data" when neither is known. */
function itemAmount(m: MissingItem, t: Record<string, string>): string {
  const orig = m.amount !== null && m.currency && m.currency !== 'HUF' ? `${NUM.format(m.amount)} ${m.currency}` : ''
  if (m.amountFt !== null) return orig ? `${fmtHuf(m.amountFt)} (${orig})` : fmtHuf(m.amountFt)
  if (orig) return orig
  if (m.amount !== null && m.currency === 'HUF') return fmtHuf(Math.round(m.amount))
  return t.noData!
}

function isOverdue(c: ClosingMonth, today: string): boolean {
  return !!c.deadline?.date && c.status !== 'KESZ' && c.deadline.date < today
}

/** "30/34 with invoice": the charges that need an invoice are the total minus the ones that need none. */
function invoicedLine(c: ClosingMonth, t: Record<string, string>): string {
  const { invoicedDb, totalDb, notNeededDb } = c.charges
  if (invoicedDb === null || totalDb === null) return ''
  const need = totalDb - (notNeededDb ?? 0)
  return `${invoicedDb}/${need} ${t.invoiced!}`
}

function missingCount(c: ClosingMonth): number {
  return c.charges.missingDb ?? c.missing.length
}

function gridCell(c: ClosingMonth | undefined, t: Record<string, string>, today: string): string {
  if (!c) return `<td class="zc"><span class="zst z-nofile">${escapeHtml(t.noFile!)}</span></td>`
  const lines: string[] = []
  const inv = invoicedLine(c, t)
  if (inv) lines.push(escapeHtml(inv))
  const miss = missingCount(c)
  if (miss) lines.push(`<strong>${miss} ${escapeHtml(t.missingN!)}</strong>`)
  // A closed month can still hold items that wait on Patrik (e.g. the accountant flagged an invoice after sending).
  const mine = c.missing.filter((m) => m.waitsOnPatrik).length
  if (mine) lines.push(`<span class="zst z-late">${mine} ${escapeHtml(t.r_patrikra_var!)}</span>`)
  if (c.statements.some((s) => s.has === false)) lines.push(`<strong>${escapeHtml(t.statement!)}: ${escapeHtml(t.hasNot!)}</strong>`)
  if (c.status === 'KESZ' && c.sent?.date) lines.push(`${escapeHtml(t.sent!)}: ${escapeHtml(c.sent.date)}`)
  else if (c.deadline?.date) {
    lines.push(`${escapeHtml(t.deadline!)}: ${escapeHtml(c.deadline.date)}${c.deadline.guess ? ` (${escapeHtml(t.guess!)})` : ''}${isOverdue(c, today) ? ` <span class="zst z-late">${escapeHtml(t.overdue!)}</span>` : ''}`)
  }
  return `<td class="zc">${statusBadge(c.status, t)}${lines.map((l) => `<div class="zl">${l}</div>`).join('')}</td>`
}

function grid(data: ClosingData, names: Map<string, string>, t: Record<string, string>, today: string): string {
  const head = `<tr><th>${escapeHtml(t.month!)}</th>${data.companies.map((c) => `<th>${escapeHtml(companyLabel(c, names, data))}</th>`).join('')}</tr>`
  // Newest first: the open months are what Patrik looks for.
  const body = [...data.months].reverse().map((month) =>
    `<tr><th class="zm">${escapeHtml(month)}</th>${data.companies.map((c) => gridCell(data.cells.get(`${c}\u0000${month}`), t, today)).join('')}</tr>`,
  ).join('')
  return `<table class="zgrid"><thead>${head}</thead><tbody>${body}</tbody></table>`
}

function yoursBox(data: ClosingData, names: Map<string, string>, t: Record<string, string>): string {
  const items: string[] = []
  for (const month of [...data.months].reverse()) {
    for (const company of data.companies) {
      const c = data.cells.get(`${company}\u0000${month}`)
      if (!c) continue
      const where = `${escapeHtml(companyLabel(company, names, data))} · ${escapeHtml(month)}`
      for (const m of c.missing.filter((x) => x.waitsOnPatrik)) {
        const what = [m.supplier, m.date ?? '', itemAmount(m, t)].filter(Boolean).join(', ')
        items.push(`<li><span class="zw">${where}</span> <strong>${escapeHtml(what)}</strong>${m.task ? `: ${escapeHtml(m.task)}` : ''}</li>`)
      }
    }
  }
  const body = items.length ? `<ul>${items.join('')}</ul>` : `<p>${escapeHtml(t.yoursNone!)}</p>`
  return `<div class="zyours${items.length ? '' : ' empty'}"><h3>${escapeHtml(t.yours!)}${items.length ? ` (${items.length})` : ''}</h3>${body}</div>`
}

function missingTable(c: ClosingMonth, t: Record<string, string>): string {
  if (!c.missing.length) return `<p class="meta">${escapeHtml(t.noMissing!)}</p>`
  const rows = c.missing.map((m) => {
    const known = m.amountFt !== null || m.amount !== null
    return `<tr${m.waitsOnPatrik ? ' class="zmine"' : ''}><td><strong>${escapeHtml(m.supplier)}</strong></td>` +
      `<td class="num${known ? '' : ' unk'}">${escapeHtml(itemAmount(m, t))}</td><td>${escapeHtml(m.date ?? '-')}</td>` +
      `<td><span class="badge${m.waitsOnPatrik ? ' b-loud' : ''}">${escapeHtml(t[`r_${m.reason}`]!)}</span></td>` +
      `<td>${escapeHtml(m.task || '-')}${m.owner ? `<div class="plan">${escapeHtml(t.owner!)}: ${escapeHtml(m.owner)}</div>` : ''}</td></tr>`
  }).join('')
  return `<div class="wrap"><table class="zmiss"><thead><tr><th>${escapeHtml(t.supplier!)}</th><th class="num">${escapeHtml(t.amount!)}</th>` +
    `<th>${escapeHtml(t.date!)}</th><th>${escapeHtml(t.reason!)}</th><th>${escapeHtml(t.task!)}</th></tr></thead><tbody>${rows}</tbody></table></div>`
}

function navText(side: NavSide | null, label: string, t: Record<string, string>): string {
  if (!side || (side.db === null && side.netFt === null)) return ''
  const diff = (d: number | null) => d === null ? '' : d === 0 ? t.navMatch! : `${t.navDiff!} ${fmtHuf(d)}`
  const own = side.ownGrossFt === null ? '' : `${t.ownList!} ${fmtHuf(side.ownGrossFt)}${side.diffGrossFt !== null ? ` (${diff(side.diffGrossFt)})` : ''}`
  return [`${label}: ${side.db ?? '?'} ${t.invoices!}`, side.netFt !== null ? `${t.net!} ${fmtHuf(side.netFt)}` : '',
    side.vatFt !== null ? `${t.vat!} ${fmtHuf(side.vatFt)}` : '', diff(side.diffNetFt), own].filter(Boolean).join(', ')
}

function monthDetails(c: ClosingMonth, names: Map<string, string>, data: ClosingData, t: Record<string, string>, today: string): string {
  const ch = c.charges
  const chargeText = [
    invoicedLine(c, t),
    ch.totalFt !== null ? `${huf(ch.invoicedFt, t)} / ${huf(ch.totalFt, t)}` : '',
    ch.notNeededDb !== null ? `${t.notNeeded!}: ${ch.notNeededDb}${ch.notNeededFt !== null ? ` (${fmtHuf(ch.notNeededFt)})` : ''}` : '',
    ch.missingDb !== null ? `${t.missingN!}: ${ch.missingDb}${ch.missingFt !== null ? ` (${fmtHuf(ch.missingFt)})` : ''}` : '',
  ].filter(Boolean).join(' · ') || t.noData!
  const statementText = c.statements.length
    ? c.statements.map((s) => `${s.account}: ${s.has === true ? t.has! : s.has === false ? t.hasNot! : t.noData!}${
      s.complete === false ? ` (${t.incomplete!})` : ''}${s.note ? `, ${s.note}` : ''}`).join(' · ')
    : t.noData!
  const inc = c.income
  const incomeText = [inc.ok === true ? t.ok! : inc.ok === false ? t.notOk! : t.unchecked!,
    inc.db !== null ? `${inc.db} ${t.invoices!}` : '', inc.netFt !== null ? `${t.net!} ${fmtHuf(inc.netFt)}` : '',
    inc.grossFt !== null ? `${t.gross!} ${fmtHuf(inc.grossFt)}` : '', inc.note].filter(Boolean).join(' · ')
  const navParts = [navText(c.nav.out, t.navOut!, t), navText(c.nav.in, t.navIn!, t)].filter(Boolean)
  const navAll = navParts.length ? [...navParts, c.nav.queried ? `${t.queried!}: ${c.nav.queried}` : ''].filter(Boolean).join(' · ') : t.navNone!
  const navLoud = [c.nav.out, c.nav.in].some((s) => s !== null && ((s.diffNetFt ?? 0) !== 0 || (s.diffGrossFt ?? 0) !== 0))
  const deadline = c.deadline?.date
    ? `${c.deadline.date}${c.deadline.guess ? ` [${t.guess!}]` : ''}${c.deadline.what ? ` (${c.deadline.what})` : ''}${isOverdue(c, today) ? `: ${t.overdue!}` : ''}` : '-'
  const rows: Array<[string, string, boolean]> = [
    [t.statement!, statementText, c.statements.some((s) => s.has === false)],
    [t.charges!, chargeText, missingCount(c) > 0],
    [t.income!, incomeText, inc.ok === false],
    [t.nav!, navAll, navLoud],
    [t.deadline!, deadline, isOverdue(c, today)],
    [t.sent!, c.sent?.date ? `${c.sent.date}${c.sent.by ? ` (${t.by!}: ${c.sent.by})` : ''}` : c.status === 'CSOMAG_KESZ' ? t.waitingSend! : '-', false],
    [t.who!, c.who.length ? c.who.map((w) => [w.who, w.what].filter(Boolean).join(': ')).join(' · ') : '-', false],
    [t.updated!, [c.updated, c.updatedBy].filter(Boolean).join(', ') || '-', false],
  ]
  if (c.notes.length) rows.push([t.notes!, c.notes.join(' · '), false])
  if (c.sources.length) rows.push([t.sources!, c.sources.join('; '), false])
  const dl = `<dl class="zdl">${rows.map(([k, v, loud]) => `<dt>${escapeHtml(k)}</dt><dd${loud ? ' class="zloud"' : ''}>${escapeHtml(v)}</dd>`).join('')}</dl>`
  const errs = c.errors.length
    ? `<details class="errs"><summary>${escapeHtml(t.errors!)} (${c.errors.length})</summary><ul>${c.errors.map((e) => `<li>${escapeHtml(e)}</li>`).join('')}</ul></details>` : ''
  const miss = missingCount(c)
  const summary = `<span class="zm">${escapeHtml(c.month)}</span> · ${escapeHtml(companyLabel(c.company, names, data))} ${statusBadge(c.status, t)}` +
    (c.statusText ? ` <span class="zl">${escapeHtml(c.statusText)}</span>` : '') +
    (miss ? ` <span class="zl">· ${miss} ${escapeHtml(t.missingN!)}</span>` : '')
  return `<details class="zmonth"><summary>${summary}</summary>${dl}<h4>${escapeHtml(t.missingList!)}</h4>${missingTable(c, t)}${errs}</details>`
}

export function renderClosingPage(data: ClosingData, names: Map<string, string>, opts: { lang: Lang; theme: Theme; today: string }): string {
  const t = CL[opts.lang]
  if (!data.present) return pageShell(t.title!, `<p class="meta">${escapeHtml(t.none!)}</p>`, opts)
  const parts: string[] = [`<h2>${escapeHtml(t.title!)}</h2>`, yoursBox(data, names, t), grid(data, names, t, opts.today)]
  if (data.fileErrors.length) {
    parts.push(`<details class="errs" open><summary>${escapeHtml(t.fileErrors!)} (${data.fileErrors.length})</summary><ul>${
      data.fileErrors.map((e) => `<li>${escapeHtml(`${e.company}/${e.month}.json: ${e.error}`)}</li>`).join('')}</ul></details>`)
  }
  const details: string[] = []
  for (const month of [...data.months].reverse()) {
    for (const company of data.companies) {
      const c = data.cells.get(`${company}\u0000${month}`)
      if (c) details.push(monthDetails(c, names, data, t, opts.today))
    }
  }
  if (details.length) parts.push(`<h3>${escapeHtml(t.details!)}</h3>${details.join('')}`)
  return pageShell(t.title!, `<section>${parts.join('')}</section>`, opts)
}

/** Today in the install's time zone (Europe/Budapest, the process TZ), as YYYY-MM-DD. */
export function localToday(now = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}
