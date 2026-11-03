#!/usr/bin/env node
// Daily summary of the quarantine-reader's open-posture traffic (Viktor 24670 Q2).
//
//   node scripts/egress-quarantine-daily.mjs [--date YYYY-MM-DD] [--log <path>] [--json]
//
// Reads the ALLOWED_QUARANTINE_OPEN / BLOCKED_QUARANTINE_OPEN lines that
// scripts/hooks/egress-gate.mjs writes to store/egress-blocked.log. Those lines
// carry host, a cut path, query length and hash -- never the query -- so this
// summary cannot leak more than the log does. The day is the Europe/Budapest
// calendar day (the install's single time zone). Read-only; prints to stdout.
//
// Alerts (exit code stays 0, the lines start with "RIASZTÁS"):
//   - one host more than HOURLY_ALERT times in one hour,
//   - any query-too-long / url-too-long / collector refusal (a URL shaped like exfiltration),
//   - any query flagged base64-like.
import { existsSync, readFileSync, realpathSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
export const HOURLY_ALERT = 30
const TZ = 'Europe/Budapest'
const LINE = /^(\S+) (?:SELFTEST_)?(ALLOWED_QUARANTINE_OPEN|BLOCKED_QUARANTINE_OPEN) host="([^"]*)" path="[^"]*" path_len=(\d+) query_len=(\d+)(?: query_sha8=[0-9a-f]+)?( query_b64like=1)? reason="([^"]*)"/
const EXFIL_REASONS = new Set(['query-too-long', 'url-too-long', 'collector-host', 'collector-path', 'userinfo'])

const dayOf = (iso) => new Intl.DateTimeFormat('sv-SE', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(iso))
const hourOf = (iso) => new Intl.DateTimeFormat('sv-SE', { timeZone: TZ, hour: '2-digit', hour12: false }).format(new Date(iso))

export function summarize(text, day) {
  const seenBefore = new Set()
  const s = { day, allowed: 0, blocked: 0, hosts: {}, newHosts: [], maxQueryLen: 0, reasons: {}, b64like: 0, perHourMax: {}, selftest: 0 }
  const hourly = {}
  for (const raw of text.split('\n')) {
    const m = LINE.exec(raw)
    if (!m) continue
    if (raw.includes(' SELFTEST_')) { s.selftest++; continue }
    const [, ts, kind, host, , qlen, b64, reason] = m
    const d = dayOf(ts)
    if (d < day) { seenBefore.add(host); continue }
    if (d > day) continue
    if (kind === 'ALLOWED_QUARANTINE_OPEN') {
      s.allowed++
      s.hosts[host] = (s.hosts[host] ?? 0) + 1
      if (!seenBefore.has(host) && !s.newHosts.includes(host)) s.newHosts.push(host)
      const k = `${host} ${hourOf(ts)}`
      hourly[k] = (hourly[k] ?? 0) + 1
      s.perHourMax[host] = Math.max(s.perHourMax[host] ?? 0, hourly[k])
    } else {
      s.blocked++
      s.reasons[reason] = (s.reasons[reason] ?? 0) + 1
    }
    s.maxQueryLen = Math.max(s.maxQueryLen, Number(qlen))
    if (b64) s.b64like++
  }
  s.alerts = []
  for (const [h, n] of Object.entries(s.perHourMax)) if (n > HOURLY_ALERT) s.alerts.push(`${h}: ${n} kérés egy órán belül (> ${HOURLY_ALERT})`)
  const exfil = Object.entries(s.reasons).filter(([r]) => EXFIL_REASONS.has(r))
  if (exfil.length) s.alerts.push(`kiszivárogtatás-alakú URL elutasítva: ${exfil.map(([r, n]) => `${r} ${n}`).join(', ')}`)
  if (s.b64like) s.alerts.push(`base64-szerű lekérdezés: ${s.b64like} db`)
  return s
}

export function render(s) {
  const top = Object.entries(s.hosts).sort((a, b) => b[1] - a[1])
  const out = [
    `# Quarantine-reader nyitott mód, ${s.day}`,
    `Engedélyezett: ${s.allowed}, elutasított: ${s.blocked}, max query-hossz: ${s.maxQueryLen}${s.selftest ? `, SELFTEST-sor kihagyva: ${s.selftest}` : ''}`,
    `Új hostok (${s.newHosts.length}): ${s.newHosts.join(', ') || '-'}`,
    `Hostok: ${top.map(([h, n]) => `${h} ${n}`).join(', ') || '-'}`,
    `Elutasítás oka: ${Object.entries(s.reasons).map(([r, n]) => `${r} ${n}`).join(', ') || '-'}`,
  ]
  for (const a of s.alerts) out.push(`RIASZTÁS: ${a}`)
  return out.join('\n')
}

function isInvokedDirectly() {
  try { return realpathSync(fileURLToPath(import.meta.url)) === realpathSync(process.argv[1] ?? '') } catch { return false }
}

if (isInvokedDirectly()) {
  const args = process.argv.slice(2)
  const opt = (n) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : undefined }
  const day = opt('--date') ?? dayOf(new Date().toISOString())
  const logPath = opt('--log') ?? join(REPO_ROOT, 'store', 'egress-blocked.log')
  const text = existsSync(logPath) ? readFileSync(logPath, 'utf-8') : ''
  const s = summarize(text, day)
  process.stdout.write((args.includes('--json') ? JSON.stringify(s) : render(s)) + '\n')
}
