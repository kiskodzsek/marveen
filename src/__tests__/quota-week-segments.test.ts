// Overview -> subscription quota: the weekly bar is split into the 7 days of
// the CURRENT window, with day names underneath and a "now" marker (Tom,
// 2026-09-29, kanban a646a038). The window is not a calendar week: it ends at
// resetsAt and began 7 days earlier (measured: Monday 09:00 CEST for both the
// previous and the current window), so a Monday-first hard-code would be
// right today only by coincidence. Evaluated from web/app.js, not a copy.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const APP = readFileSync(join(__dirname, '../../web/app.js'), 'utf-8')
const CSS = readFileSync(join(__dirname, '../../web/style.css'), 'utf-8')

function extractFn(name: string): string {
  const re = new RegExp(`(?:async )?function ${name}\\s*\\([^)]*\\)\\s*\\{`)
  const m = re.exec(APP)
  if (!m) throw new Error(`${name} missing from web/app.js`)
  let depth = 0
  for (let j = APP.indexOf('{', m.index); j < APP.length; j++) {
    if (APP[j] === '{') depth++
    else if (APP[j] === '}' && --depth === 0) return APP.slice(m.index, j + 1)
  }
  throw new Error(`${name}: unbalanced braces`)
}

type Week = { starts: number[]; labels: string[]; shortLabels: string[]; narrowLabels: string[] | null; nowPct: number } | null
// eslint-disable-next-line @typescript-eslint/no-implied-eval
const weekSegments = new Function(`${extractFn('weekSegments')}; return weekSegments`)() as (
  resetsAt: unknown, nowSec: unknown, lang: string, timeZone?: string,
) => Week

const TZ = 'Europe/Budapest'
// The live reading of 2026-09-29: resets Monday 2026-10-05 09:00 CEST.
const MONDAY_RESET = 1791183600
// Tuesday 2026-09-29 23:17 CEST = 21:17 UTC.
const TUE_2317 = Date.UTC(2026, 8, 29, 21, 17) / 1000

const localHm = (sec: number) =>
  new Date(sec * 1000).toLocaleTimeString('hu-HU', { timeZone: TZ, hour: '2-digit', minute: '2-digit' })

describe('weekSegments', () => {
  it('Monday reset: Hétfő..Vasárnap, every boundary at 09:00', () => {
    const w = weekSegments(MONDAY_RESET, TUE_2317, 'hu', TZ)!
    expect(w.labels).toEqual(['Hétfő', 'Kedd', 'Szerda', 'Csütörtök', 'Péntek', 'Szombat', 'Vasárnap'])
    expect(w.starts.map(localHm)).toEqual(Array(7).fill('09:00'))
  })

  it('Thursday reset: the labels follow the window, not the calendar', () => {
    const thuReset = MONDAY_RESET - 4 * 86400 // Thursday 2026-10-01 09:00
    const w = weekSegments(thuReset, TUE_2317, 'hu', TZ)!
    expect(w.labels).toEqual(['Csütörtök', 'Péntek', 'Szombat', 'Vasárnap', 'Hétfő', 'Kedd', 'Szerda'])
  })

  it('English day names', () => {
    expect(weekSegments(MONDAY_RESET, TUE_2317, 'en', TZ)!.labels)
      .toEqual(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'])
  })

  it('short and narrow labels: hu H K Sze Cs P Szo V and no narrow tier (never a bare "Sz"), en Mon..Sun / M T W T F S S', () => {
    const hu = weekSegments(MONDAY_RESET, TUE_2317, 'hu', TZ)!
    expect(hu.shortLabels).toEqual(['H', 'K', 'Sze', 'Cs', 'P', 'Szo', 'V'])
    expect(new Set(hu.shortLabels).size).toBe(7)
    expect(hu.narrowLabels).toBeNull()
    const en = weekSegments(MONDAY_RESET, TUE_2317, 'en', TZ)!
    expect(en.shortLabels).toEqual(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])
    expect(en.narrowLabels).toEqual(['M', 'T', 'W', 'T', 'F', 'S', 'S'])
    // a Thursday window keeps the short forms in window order too
    expect(weekSegments(MONDAY_RESET - 4 * 86400, TUE_2317, 'hu', TZ)!.shortLabels)
      .toEqual(['Cs', 'P', 'Szo', 'V', 'H', 'K', 'Sze'])
  })

  it('now marker: Tuesday 23:17 is 1d 14h 17m into the window, ~22.8%', () => {
    const w = weekSegments(MONDAY_RESET, TUE_2317, 'hu', TZ)!
    const expected = ((TUE_2317 - (MONDAY_RESET - 7 * 86400)) / (7 * 86400)) * 100
    expect(w.nowPct).toBeCloseTo(expected, 6)
    expect(w.nowPct).toBeCloseTo(22.8, 1)
  })

  it('no usable window -> null (the row keeps the plain bar)', () => {
    for (const bad of [null, undefined, NaN, Infinity, '1791183600', {}]) {
      expect(weekSegments(bad, TUE_2317, 'hu', TZ)).toBeNull()
    }
    expect(weekSegments(TUE_2317 - 1, TUE_2317, 'hu', TZ)).toBeNull() // already reset
    expect(weekSegments(TUE_2317 + 8 * 86400, TUE_2317, 'hu', TZ)).toBeNull() // window not started
  })
})

// t() stub: the key, plus its params when there are any -- enough to see
// which message and which values a row rendered.
const tStub = (k: string, p?: Record<string, unknown>) =>
  p && Object.keys(p).length ? `${k}(${Object.entries(p).map(([a, b]) => `${a}=${b}`).join(',')})` : k

// quotaResetLabel with the REAL lang strings (hu.js / en.js loaded for their
// window._i18n side effect, the lang-parity idiom) and the same {param}
// substitution t() does, so the asserted text is what Patrik reads.
const LANG: Record<string, Record<string, string>> = {}
function loadLang(lang: 'hu' | 'en'): Record<string, string> {
  if (!LANG[lang]) {
    const window = { _i18n: {} as Record<string, Record<string, string>> }
    // eslint-disable-next-line @typescript-eslint/no-implied-eval
    new Function('window', readFileSync(join(__dirname, `../../web/lang/${lang}.js`), 'utf-8'))(window)
    LANG[lang] = window._i18n[lang]
  }
  return LANG[lang]
}
function resetLabel(resetsAt: unknown, lang: 'hu' | 'en', timeZone?: string): string {
  const dict = loadLang(lang)
  const t = (k: string, p: Record<string, string> = {}) =>
    (dict[k] ?? k).replace(/\{(\w+)\}/g, (_, n: string) => p[n] ?? `{${n}}`)
  // eslint-disable-next-line @typescript-eslint/no-implied-eval
  const fn = new Function('t', `${extractFn('quotaResetLabel')}; return quotaResetLabel`)(t) as (
    r: unknown, l: string, tz?: string) => string
  return timeZone === undefined ? fn(resetsAt, lang) : fn(resetsAt, lang, timeZone)
}

describe('quotaResetLabel (kanban 32f9b92b: the reset moment, not the last segment start)', () => {
  // Friday 2026-10-16 05:00 CEST = 03:00 UTC: the weekly reset of TG 2074.
  const FRI_0500_CEST = Date.UTC(2026, 9, 16, 3, 0) / 1000

  // day and time are joined by a no-break space (\u00a0) so a phone wraps
  // after "Nullázódik:", not inside "péntek 05:00"
  it('hu: "Nullázódik: péntek 05:00", en: "Resets: Friday 05:00"', () => {
    expect(resetLabel(FRI_0500_CEST, 'hu')).toBe('Nullázódik: péntek\u00a005:00')
    expect(resetLabel(FRI_0500_CEST, 'en')).toBe('Resets: Friday\u00a005:00')
  })

  it('names the reset day, which is the day AFTER the last segment label', () => {
    const w = weekSegments(FRI_0500_CEST, FRI_0500_CEST - 86400 * 2, 'hu', TZ)!
    expect(w.labels[6]).toBe('Csütörtök')
    expect(resetLabel(FRI_0500_CEST, 'hu')).toBe('Nullázódik: péntek\u00a005:00')
  })

  it('defaults to Europe/Budapest whatever the process zone is', () => {
    // the test process may run in any zone; the label must not follow it
    expect(resetLabel(FRI_0500_CEST, 'hu', undefined)).toBe('Nullázódik: péntek\u00a005:00')
    expect(resetLabel(FRI_0500_CEST, 'hu', 'UTC')).toBe('Nullázódik: péntek\u00a003:00')
  })

  it('DST end (2026-10-25 03:00 CEST -> 02:00 CET): the hour follows the switch', () => {
    // Sunday 2026-10-25 04:00 UTC = 05:00 CET (a fixed +2h would say 06:00)
    expect(resetLabel(Date.UTC(2026, 9, 25, 4, 0) / 1000, 'hu')).toBe('Nullázódik: vasárnap\u00a005:00')
    // the week after, still CET: Friday 2026-10-30 04:00 UTC = 05:00 CET
    expect(resetLabel(Date.UTC(2026, 9, 30, 4, 0) / 1000, 'hu')).toBe('Nullázódik: péntek\u00a005:00')
    // the same instant one week earlier (03:00 UTC on 10-23) is 05:00 CEST
    expect(resetLabel(Date.UTC(2026, 9, 23, 3, 0) / 1000, 'en')).toBe('Resets: Friday\u00a005:00')
  })

  it('DST start (2027-03-28 02:00 CET -> 03:00 CEST)', () => {
    // Sunday 2027-03-28 03:00 UTC = 05:00 CEST; 00:30 UTC = 01:30 CET
    expect(resetLabel(Date.UTC(2027, 2, 28, 3, 0) / 1000, 'hu')).toBe('Nullázódik: vasárnap\u00a005:00')
    expect(resetLabel(Date.UTC(2027, 2, 28, 0, 30) / 1000, 'hu')).toBe('Nullázódik: vasárnap\u00a001:30')
  })

  it('local midnight is "00:00" on the new day, never "24:00" on the old one', () => {
    // Saturday 2026-10-17 00:00 CEST = Friday 22:00 UTC
    expect(resetLabel(Date.UTC(2026, 9, 16, 22, 0) / 1000, 'hu')).toBe('Nullázódik: szombat\u00a000:00')
    expect(resetLabel(Date.UTC(2026, 9, 16, 22, 0) / 1000, 'en')).toBe('Resets: Saturday\u00a000:00')
  })

  it('missing or unusable resetsAt -> empty string (show nothing)', () => {
    for (const bad of [null, undefined, NaN, Infinity, -Infinity, '1791183600', {}]) {
      expect(resetLabel(bad, 'hu')).toBe('')
      expect(resetLabel(bad, 'en')).toBe('')
    }
  })
})

// The rendered row, with the DOM and helpers stubbed: the week pieces appear on
// the weekly row only, and a missing resetsAt leaves the old bar untouched.
function render(quota: Record<string, unknown>, lang = 'hu'): string[] {
  const els: Record<string, { hidden: boolean; innerHTML: string; textContent: string; className: string; children: string[]; appendChild: (c: { innerHTML: string }) => void }> = {}
  for (const id of ['quotaStrip', 'quotaBars', 'quotaStripNote', 'quotaStripAge']) {
    const el = { hidden: true, innerHTML: '', textContent: '', className: '', children: [] as string[],
      appendChild(c: { innerHTML: string }) { this.children.push(c.innerHTML) } }
    els[id] = el
  }
  const document = { getElementById: (id: string) => els[id], createElement: () => ({ className: '', innerHTML: '' }) }
  // eslint-disable-next-line @typescript-eslint/no-implied-eval
  const fn = new Function('document', 'window', 't', 'escapeHtml', 'formatDurationShort', 'formatRelative',
    `${extractFn('quotaLevelClass')}; ${extractFn('quotaMeasuredText')}; ${extractFn('weekSegments')}; ${extractFn('quotaResetLabel')}; ${extractFn('quotaBarRow')}; ${extractFn('renderQuotaStrip')}; return renderQuotaStrip`,
  )(document, { _lang: lang }, tStub, (s: string) => String(s), () => '1n', () => 'most')
  fn(quota, null)
  return els.quotaBars.children
}

// The portrait-phone fix: the day row must never fall back to an ellipsis
// ("Hé… Ke… Sz…"); it swaps to shorter names by its own width instead.
function daysCss(): string {
  const from = CSS.indexOf('.quota-bar-days {')
  const to = CSS.indexOf('.quota-bar-fill {', from)
  if (from < 0 || to < 0) throw new Error('.quota-bar-days rules missing from web/style.css')
  return CSS.slice(from, to)
}

describe('day-name CSS', () => {
  it('no ellipsis anywhere in the day-name rules', () => {
    expect(daysCss()).not.toMatch(/text-overflow/)
  })
  it('the label row is a size container and swaps full -> short -> narrow by its width', () => {
    const css = daysCss()
    expect(css).toMatch(/container-type:\s*inline-size/)
    const block = (w: number) => {
      const i = css.indexOf(`@container quota-days (max-width: ${w}px) {`)
      if (i < 0) throw new Error(`no ${w}px container rule`)
      return css.slice(i, css.indexOf('\n}', i))
    }
    expect(block(440)).toContain('.day-full { display: none; }')
    expect(block(440)).toContain('.day-short { display: inline; }')
    expect(block(180)).toContain('.day-short { display: none; }')
    expect(block(180)).toContain('.day-narrow { display: inline; }')
    // hu has no narrow form: below 180 px its whole day-name row hides
    expect(block(180)).toContain('.quota-bar-days.no-narrow > span { display: none; }')
    expect(css).toMatch(/\.day-short,\s*\.quota-bar-days \.day-narrow \{ display: none; \}/)
  })
})

describe('renderQuotaStrip weekly row', () => {
  const now = Math.floor(Date.now() / 1000)
  const reset = now + 3 * 86400

  it('weekly row gets separators, 7 day names and a now marker; 5-hour row does not', () => {
    const [five, week] = render({ status: 'ok', ageSec: 5,
      fiveHour: { usedPercentage: 26, resetsAt: now + 3600 },
      sevenDay: { usedPercentage: 34, resetsAt: reset } })
    expect(week).toContain('quota-bar-track week')
    expect(week).toContain('class="quota-bar-now"')
    expect((week.match(/<span>/g) || []).length).toBe(7)
    expect(week).toContain('<span class="day-full">Hétfő</span><span class="day-short">H</span></span>')
    expect(week).toContain('<span class="day-full">Szerda</span><span class="day-short">Sze</span>')
    expect(five).not.toContain('quota-bar-days')
    expect(five).not.toContain('quota-bar-now')
    // the absolute reset moment sits under the day row, on the weekly row only
    expect(week).toMatch(/<div class="quota-bar-resets-at">overview\.quota\.resets_at\(when=[a-zéáíóöőúüű]+\u00a0\d\d:\d\d\)<\/div>/)
    expect(five).not.toContain('quota-bar-resets-at')
  })

  // Szotasz's review of #1703: at 390 px the hu short forms (~140 px) ran
  // together in a ~100 px track ("SzeCs"), at 320 px they spilled under the
  // value. hu therefore has no narrow tier: the row is marked no-narrow (the
  // 180 px container rule hides it) and carries no day-narrow spans that
  // could show instead. The track, separators and now marker stay.
  it('hu narrow tier: day row marked no-narrow, no day-narrow spans; separators and marker stay', () => {
    const [, week] = render({ status: 'ok', ageSec: 5,
      fiveHour: { usedPercentage: 26, resetsAt: now + 3600 },
      sevenDay: { usedPercentage: 34, resetsAt: reset } }, 'hu')
    expect(week).toContain('class="quota-bar-days no-narrow"')
    expect(week).not.toContain('day-narrow')
    expect(week).toContain('quota-bar-track week')
    expect(week).toContain('class="quota-bar-now"')
  })

  it('en narrow tier: day row NOT marked no-narrow, one-letter day-narrow spans', () => {
    const [, week] = render({ status: 'ok', ageSec: 5,
      fiveHour: { usedPercentage: 26, resetsAt: now + 3600 },
      sevenDay: { usedPercentage: 34, resetsAt: reset } }, 'en')
    expect(week).toContain('class="quota-bar-days"')
    expect(week).not.toContain('no-narrow')
    expect((week.match(/class="day-narrow">[A-Z]<\/span>/g) || []).length).toBe(7)
  })

  it('missing / null resetsAt: plain bar, no division, no marker', () => {
    for (const sevenDay of [{ usedPercentage: 34 }, { usedPercentage: 34, resetsAt: null }]) {
      const [week] = render({ status: 'ok', ageSec: 5, sevenDay })
      expect(week).toContain('class="quota-bar-track"')
      expect(week).toContain('width:34%')
      expect(week).not.toContain('quota-bar-days')
      expect(week).not.toContain('quota-bar-now')
      expect(week).not.toContain('track week')
      expect(week).not.toContain('quota-bar-resets-at')
      expect(week).not.toContain('resets_at')
    }
  })

  it('expired window: plain bar, no division, no marker', () => {
    const [week] = render({ status: 'ok', ageSec: 5, sevenDay: { usedPercentage: 90, resetsAt: reset, expired: true } })
    expect(week).not.toContain('quota-bar-days')
    expect(week).not.toContain('quota-bar-now')
    expect(week).not.toContain('quota-bar-resets-at')
  })
})
