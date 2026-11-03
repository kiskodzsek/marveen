// "Iroda" (office) view of the fleet: an org chart where every agent sits at a
// desk with a small monitor showing what it is doing, and inter-agent messages
// travel along the chart's lines (Patrik TG 14058/14078/14081/14087/14112/14115,
// mockup: shared/csapat-fejlesztes-1103/dashboard-mockup-v2).
//
// This module is the pure / filesystem side; the route (routes/iroda.ts) does
// the DB and pane I/O. Everything that leaves the server through the snapshot
// is REDUCED here first: the view never receives a raw message body, a raw
// command line or a full file path. The existing dashboard already shows those
// to the same token holder, but this view is made to be screenshotted into a
// chat, so it carries only what a glance needs.
//
// Monitor thumbnails come ONLY from directories named in the allowlist
// (store/iroda-thumbs.json, defaults below), never from a customer or upload
// folder: a path whose any segment matches EXCLUDED_SEGMENT is skipped even
// inside an allowed directory. No allowlist entry -> no thumbnail, the card
// title is shown instead.

import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { basename, join, relative, resolve, sep } from 'node:path'

// ---------------------------------------------------------------------------
// Text reduction
// ---------------------------------------------------------------------------

const EMAIL = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g
// Hungarian bank account (8-8 or 8-8-8), IBAN, and any long digit run (phone, tax number, card).
const ACCOUNT = /\b\d{8}-\d{8}(?:-\d{8})?\b/g
const IBAN = /\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b/g
const PHONE = /(?:\+|\b)\d[\d ()/-]{7,}\d\b/g
// A date ("2026-11-03", optionally followed by the hour) also matches PHONE; it is not personal data.
const DATE_TIME = /^\d{4}-\d{2}-\d{2}(?: \d{1,2})?$/
// Key/token shapes: known prefixes, then any long unbroken run of key characters.
const TOKENISH = /\b(?:sk|rk|pk|ghp|gho|ghs|github_pat|xox[bpas]|AKIA|eyJ)[A-Za-z0-9_\-.]{8,}/g
const LONGRUN = /[A-Za-z0-9_\-+/=]{28,}/g
const URL_RE = /\bhttps?:\/\/([^\s/?#]+)[^\s]*/g

/** Mask anything that looks like personal data or a secret. Order matters: URLs first (host only). */
export function scrubText(input: string): string {
  return input
    .replace(URL_RE, (_m, host: string) => host)
    .replace(EMAIL, '<e-mail>')
    .replace(TOKENISH, '<titok>')
    .replace(IBAN, '<számla>')
    .replace(ACCOUNT, '<számla>')
    .replace(PHONE, (m) => (DATE_TIME.test(m) ? m : '<szám>'))
    .replace(LONGRUN, '…')
}

function clip(s: string, max: number): string {
  const t = s.replace(/\s+/g, ' ').trim()
  return t.length <= max ? t : t.slice(0, max - 1).trimEnd() + '…'
}

const AGENT_PREFIX = /^\s*(?:\[[^\]]{1,40}\]\s*)?(?:[A-ZÁÉÍÓÖŐÚÜŰa-záéíóöőúüű]{2,12}\s*(?:->|→)\s*[A-ZÁÉÍÓÖŐÚÜŰa-záéíóöőúüű]{2,12}\s*[,:]\s*)/
const NAME_PREFIX = /^\s*(?:Klodel|Kernel|Pulzus|Dave|Pixel|Viktor|Lex|Juró|Juro|Mira|Szigma)\s*[,:]\s*/i
const RESULT_PREFIX = /^\s*\[Eredmény\]\s*msg_id:\d+\s*status:\w+\s*/i

/**
 * One-line subject of an inter-agent message for the view: the routing
 * prefixes ("Klodel -> Kernel,", "[Eredmény] msg_id:N status:done") removed,
 * the first sentence kept, personal data and secrets masked, clipped.
 */
export function messageSubject(content: string, max = 72): string {
  let s = content.replace(/\r?\n/g, ' ')
  s = s.replace(RESULT_PREFIX, 'Eredmény: ')
  s = s.replace(AGENT_PREFIX, '').replace(NAME_PREFIX, '')
  // first sentence, but not cut at a decimal point or an abbreviation-like "pl."
  const m = /^(.{12,}?[.!?])\s/.exec(s)
  if (m && m[1].length <= max) s = m[1]
  return clip(scrubText(s), max)
}

// ---------------------------------------------------------------------------
// Monitor line from the latest tool call
// ---------------------------------------------------------------------------

const SHELL_LEADS = new Set(['cd', 'export', 'set', 'T=', 'TOK=', 'source', '.'])
const SUBCOMMANDS = new Set(['git', 'npm', 'npx', 'gh', 'node', 'python3', 'python', 'bash', 'tmux', 'docker', 'swift', 'swiftc', 'vercel', 'supabase'])

/** The program (and for multi-command tools, the subcommand) of a shell line, without arguments or paths. */
export function shellVerb(command: string): string {
  const parts = command.split(/&&|;|\|\||\|/).map((p) => p.trim()).filter(Boolean)
  for (const part of parts) {
    const words = part.split(/\s+/).filter((w) => !/^[A-Z_][A-Z0-9_]*=/.test(w))
    if (!words.length) continue
    const prog = basename(words[0])
    if (SHELL_LEADS.has(prog) || prog === '') continue
    if (!/^[\w.+-]+$/.test(prog)) continue
    if (SUBCOMMANDS.has(prog) && words[1] && /^[a-z][\w:-]*$/.test(words[1])) {
      // for interpreters show the script name, not its path
      if (/^(node|python3?|bash|swift)$/.test(prog)) return `${prog} ${basename(words[1])}`
      return `${prog} ${words[1]}`
    }
    if (/^(node|python3?|bash)$/.test(prog) && words[1]) {
      const w = words[1].startsWith('-') ? words[2] : words[1]
      return w ? `${prog} ${basename(w)}` : prog
    }
    return prog
  }
  return 'parancs'
}

/**
 * What the monitor's first line says for the agent's latest tool call. Only a
 * verb and, for file tools, the file's base name: never a full path, never
 * command arguments, never a query string.
 */
export function activityLine(toolName: string, inputSummary: string | null): string {
  const input = inputSummary ?? ''
  switch (toolName) {
    case 'Bash':
    case 'bash':
      return `> ${clip(scrubText(shellVerb(input)), 40)}`
    case 'Read':
      return `olvas: ${clip(scrubText(basename(input)), 40)}`
    case 'Edit':
    case 'MultiEdit':
      return `szerkeszt: ${clip(scrubText(basename(input)), 36)}`
    case 'Write':
      return `ír: ${clip(scrubText(basename(input)), 40)}`
    case 'WebFetch':
    case 'WebSearch': {
      const host = /^https?:\/\/([^/?#\s]+)/.exec(input)?.[1]
      return host ? `web: ${host}` : 'webes keresés'
    }
    case 'Skill':
      return `skill: ${clip(scrubText(input.split(/\s/)[0] ?? ''), 36)}`
    case 'Agent':
    case 'Task':
      return 'alügynököt futtat'
    default:
      if (toolName.startsWith('mcp__')) return `eszköz: ${clip(toolName.split('__').slice(1).join(' '), 36)}`
      return clip(toolName, 40)
  }
}

// ---------------------------------------------------------------------------
// Thumbnails: latest media file in allowlisted, non-customer directories
// ---------------------------------------------------------------------------

export const MEDIA_EXT = /\.(png|jpe?g|webp|mp4|mov)$/i
/** Path segments that mark customer / buyer / upload material: never shown. */
export const EXCLUDED_SEGMENT = /(ugyfel|ügyfél|vevo|vevő|customer|buyer|order|rendeles|rendelés|upload|feltolt|feltölt|photo-?gate|private|privat|szemelyes|személyes|node_modules|\.next|\.git)/i

/** Default allowlist, relative to the project root. Override: store/iroda-thumbs.json {agent: [dirs]}. */
export const DEFAULT_THUMB_DIRS: Record<string, string[]> = {
  dave: ['agents/dave/out'],
  pixel: ['agents/pixel/out'],
  mira: ['agents/mira/out', 'agents/mira/drafts'],
  kernel: ['agents/kernel/out'],
}

export function loadThumbDirs(storeDir: string): Record<string, string[]> {
  const p = join(storeDir, 'iroda-thumbs.json')
  if (!existsSync(p)) return DEFAULT_THUMB_DIRS
  try {
    const raw = JSON.parse(readFileSync(p, 'utf-8')) as unknown
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return DEFAULT_THUMB_DIRS
    const out: Record<string, string[]> = {}
    for (const [agent, dirs] of Object.entries(raw as Record<string, unknown>)) {
      if (Array.isArray(dirs)) out[agent] = dirs.filter((d): d is string => typeof d === 'string')
    }
    return out
  } catch {
    return DEFAULT_THUMB_DIRS
  }
}

export interface MediaHit { path: string; mtimeMs: number; kind: 'image' | 'video' }

/**
 * Newest media file under the given directories, modified within maxAgeMs.
 * Bounded walk (depth and entry count) so a huge render folder cannot stall
 * the dashboard; symlinks are not followed; a directory outside `root` is
 * ignored even if the allowlist names it.
 */
export function findLatestMedia(
  root: string,
  dirs: string[],
  nowMs: number,
  maxAgeMs: number,
  limits: { maxDepth?: number; maxEntries?: number } = {},
): MediaHit | null {
  const maxDepth = limits.maxDepth ?? 5
  let budget = limits.maxEntries ?? 6000
  const rootAbs = resolve(root)
  let best: MediaHit | null = null
  const walk = (dir: string, depth: number): void => {
    if (depth > maxDepth || budget <= 0) return
    let entries: import('node:fs').Dirent[]
    try { entries = readdirSync(dir, { withFileTypes: true }) } catch { return }
    for (const e of entries) {
      if (--budget <= 0) return
      if (e.name.startsWith('.') || EXCLUDED_SEGMENT.test(e.name)) continue
      const full = join(dir, e.name)
      if (e.isDirectory()) { walk(full, depth + 1); continue }
      if (!e.isFile() || !MEDIA_EXT.test(e.name)) continue
      let st
      try { st = statSync(full) } catch { continue }
      if (nowMs - st.mtimeMs > maxAgeMs) continue
      if (!best || st.mtimeMs > best.mtimeMs) {
        best = { path: full, mtimeMs: st.mtimeMs, kind: /\.(mp4|mov)$/i.test(e.name) ? 'video' : 'image' }
      }
    }
  }
  for (const d of dirs) {
    const abs = resolve(rootAbs, d)
    if (abs !== rootAbs && !abs.startsWith(rootAbs + sep)) continue
    if (relative(rootAbs, abs).split(sep).some((seg) => EXCLUDED_SEGMENT.test(seg))) continue
    walk(abs, 0)
  }
  return best
}

/** Human caption for a media hit: kind + the file's base name without extension, scrubbed. */
export function mediaCaption(hit: MediaHit): string {
  const name = basename(hit.path).replace(MEDIA_EXT, '').replace(/[-_]+/g, ' ')
  return `${hit.kind === 'video' ? '▶ videó' : 'kép'} · ${clip(scrubText(name), 34)}`
}

// ---------------------------------------------------------------------------
// Org chart (javaslat-v1.1). Override: store/iroda-org.json with the same shape.
// ---------------------------------------------------------------------------

export interface OrgSeat { id: string; name: string; role: string; placeholder?: boolean }
export interface OrgDept { id: string; name: string; lead: string; seats: OrgSeat[] }
/** hidden: agents that still have a directory but are not part of the team (e.g. wound down); never shown. */
export interface Org { lead: OrgSeat; depts: OrgDept[]; hidden?: string[] }

export const DEFAULT_ORG: Org = {
  lead: { id: 'klodel', name: 'Klodel', role: 'vezérigazgató-helyettes' },
  // Pixel was wound down on 2026-10-21 (TG 4619); the directory still exists.
  hidden: ['pixel'],
  depts: [
    { id: 'marabel', name: 'Marabel üzletág', lead: 'vezeti: Klodel, amíg fókusz', seats: [
      { id: 'dave', name: 'Dave', role: 'fejlesztő' },
      { id: 'pulzus', name: 'Pulzus', role: 'üzemeltetés' },
    ] },
    { id: 'mkt', name: 'Marketing', lead: 'vezető: Mágnes', seats: [
      { id: 'magnes', name: 'Mágnes', role: 'marketing-stratéga' },
      { id: 'mira', name: 'Mira', role: 'social media' },
    ] },
    { id: 'kf', name: 'K+F', lead: 'kutató: Radar', seats: [
      { id: 'radar', name: 'Radar', role: 'K+F-kutató' },
    ] },
    { id: 'myshp', name: 'mySHP', lead: 'alvó, ha lesz munka', seats: [
      { id: 'myshp-vezeto', name: 'mySHP-vezető', role: 'alvó üzletág', placeholder: true },
    ] },
    { id: 'common', name: 'Közös szakértők', lead: 'közvetlenül Klodelnek', seats: [
      { id: 'viktor', name: 'Viktor', role: 'biztonság' },
      { id: 'lex', name: 'Lex', role: 'jog, adatvédelem' },
      { id: 'juro', name: 'Juró', role: 'pénzügy' },
      { id: 'szigma', name: 'Szigma', role: 'adat, BI' },
      { id: 'kernel', name: 'Kernel', role: 'rendszerek, integrációk' },
    ] },
  ],
}

function isSeat(x: unknown): x is OrgSeat {
  const s = x as OrgSeat
  return !!s && typeof s.id === 'string' && typeof s.name === 'string' && typeof s.role === 'string'
}

export function loadOrg(storeDir: string): Org {
  const p = join(storeDir, 'iroda-org.json')
  if (!existsSync(p)) return DEFAULT_ORG
  try {
    const raw = JSON.parse(readFileSync(p, 'utf-8')) as Org
    if (!isSeat(raw.lead) || !Array.isArray(raw.depts)) return DEFAULT_ORG
    const depts = raw.depts.filter((d) => d && typeof d.id === 'string' && typeof d.name === 'string' && Array.isArray(d.seats))
      .map((d) => ({ id: d.id, name: d.name, lead: typeof d.lead === 'string' ? d.lead : '', seats: d.seats.filter(isSeat) }))
    const hidden = Array.isArray(raw.hidden) ? raw.hidden.filter((h): h is string => typeof h === 'string') : []
    return { lead: raw.lead, depts, hidden }
  } catch {
    return DEFAULT_ORG
  }
}

/** Agents that run but are not on the chart land in an extra room, so nobody silently disappears. */
export function withUnplacedAgents(org: Org, agentIds: string[]): Org {
  const placed = new Set([org.lead.id, ...org.depts.flatMap((d) => d.seats.map((s) => s.id)), ...(org.hidden ?? [])])
  const extra = agentIds.filter((a) => !placed.has(a))
  if (!extra.length) return org
  return { ...org, depts: [...org.depts, { id: 'other', name: 'Egyéb', lead: 'nincs az ábrán', seats: extra.map((id) => ({ id, name: id, role: '' })) }] }
}
