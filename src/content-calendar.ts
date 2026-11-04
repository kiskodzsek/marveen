// CONTENTCAL1104 -- the marketing content calendar (marketing infra I3, card
// b84e1760; plan: shared/marketing/upgrade-1103/terv.md 3. I3, 7., 12.(2)).
//
// One row = one social post, keyed by its campaign code. Two agents (Mágnes
// writes briefs, Mira drafts and schedules) write the same rows, so the
// calendar is a table behind field-level PATCH, not a file that one writer's
// full rewrite would clobber.
//
// What the code enforces (plan 7., "Semmi nem megy ki Patrik szava nélkül"):
//   1. Status changes only along TRANSITIONS; every write leaves an event row.
//   2. Entering 'jovahagyas-kerve' freezes the post: the server computes
//      content_hash over the fields Patrik approves (text, hook, link,
//      channels, time, media + sha256, AI status). While frozen those fields
//      cannot change; editing means an explicit move back to 'piszkozat',
//      which drops the hash and any approval.
//   3. 'jovahagyva' only with an approvals row that is status 'approved',
//      category 'social_post', carries the SAME content_hash, and was resolved
//      by the approval bot's button (resolution_channel 'approval_bot', which
//      no API route can write; Viktor 25867). The
//      social_post category itself is I4 (not built yet), so today no post
//      can reach 'jovahagyva' -- the intended state while nothing is
//      published (Patrik TG 14215, 14348).
//   4. A post that needs Lex's look goes through 'jogi-ok' (with a reference)
//      before it can ask for approval; 'jogi-ok' is frozen too.
// What it does NOT enforce: the media files themselves (path + sha256 are
// caller-supplied, the path only restricted to the install tree outside store/
// and dot-directories; Mira's pre-scheduling shasum check, plan 7.2(a), is the
// gate), who the caller is (the actor is self-asserted, one shared token), and
// Metricool itself (a process gate: the scheduler re-reads the row first).
// Nothing here publishes or talks to Metricool.

import { createHash } from 'node:crypto'
import { getDb, getApproval } from './db.js'
import { PROJECT_ROOT } from './config.js'

export const CONTENT_STATUSES = [
  'brief', 'piszkozat', 'jogi-ok', 'jovahagyas-kerve', 'jovahagyva',
  'elutasitva', 'utemezve', 'kint', 'merve', 'elvetve',
] as const
export type ContentStatus = (typeof CONTENT_STATUSES)[number]

export const TRANSITIONS: Record<ContentStatus, readonly ContentStatus[]> = {
  brief: ['piszkozat', 'elvetve'],
  piszkozat: ['brief', 'jogi-ok', 'jovahagyas-kerve', 'elvetve'],
  'jogi-ok': ['piszkozat', 'jovahagyas-kerve', 'elvetve'],
  'jovahagyas-kerve': ['jovahagyva', 'elutasitva', 'piszkozat'],
  jovahagyva: ['utemezve', 'piszkozat', 'elvetve'],
  elutasitva: ['piszkozat', 'elvetve'],
  // back to 'jovahagyva' = pulled out of Metricool again (plan 7.4 stop button)
  utemezve: ['kint', 'jovahagyva', 'elvetve'],
  kint: ['merve'],
  merve: [],
  elvetve: [],
}

/** Statuses in which the approved (hashed) fields are locked. */
const FROZEN: ReadonlySet<ContentStatus> = new Set(['jogi-ok', 'jovahagyas-kerve', 'jovahagyva', 'utemezve', 'kint', 'merve'])
/** Statuses in which Mira's after-scheduling fields may be written. */
const SCHEDULED: ReadonlySet<ContentStatus> = new Set(['utemezve', 'kint', 'merve'])

export const AI_STATUSES = ['nincs', 'mi-segitett', 'mi-generalt'] as const
export const FORMATS = ['4:5', '9:16', '1:1', '16:9', '1.91:1'] as const
export const APPROVAL_CATEGORY = 'social_post'

/** The fields Patrik's approval covers, in hash order. */
const HASHED_FIELDS = ['final_text', 'hook', 'link', 'channels', 'scheduled_at', 'media', 'ai_status'] as const
const DRAFT_FIELDS = ['title', 'brand', 'source_render', 'license', 'lex_gate_required', 'lex_gate_ref', 'brief', ...HASHED_FIELDS] as const
const POST_SCHEDULE_FIELDS = ['metricool_date', 'metricool_networks', 'metricool_readback', 'readback_matches', 'live_url'] as const
const ANYTIME_FIELDS = ['notes'] as const
const WRITABLE = new Set<string>([...DRAFT_FIELDS, ...POST_SCHEDULE_FIELDS, ...ANYTIME_FIELDS, 'approval_id'])

export interface ContentChannel { network: string; format: string }
export interface ContentMedia { path: string; sha256: string }

export interface ContentItem {
  id: string
  brand: string
  title: string
  status: ContentStatus
  channels: ContentChannel[]
  scheduled_at: string | null
  final_text: string | null
  hook: string | null
  link: string | null
  media: ContentMedia[]
  source_render: string | null
  ai_status: string | null
  license: string | null
  lex_gate_required: boolean | null
  lex_gate_ref: string | null
  brief: string | null
  notes: string | null
  content_hash: string | null
  approval_id: string | null
  approved_at: number | null
  metricool_date: string | null
  metricool_networks: string | null
  metricool_readback: string | null
  readback_matches: boolean | null
  live_url: string | null
  created_by: string
  updated_by: string
  created_at: number
  updated_at: number
}

export interface ContentEvent { id: number; item_id: string; at: number; actor: string; from_status: string | null; to_status: string | null; fields: string[] }

/** A rejected write: `status` is the HTTP status the route answers with. */
export class ContentError extends Error {
  constructor(readonly status: 400 | 404 | 409, message: string) { super(message) }
}

// Campaign code (plan "mérés"): lowercase letters, digits, '-' and '_', at most
// 40 chars, and no run of 7+ digits (a date like 20261106 is not a code).
export const CAMPAIGN_CODE_RE = /^[a-z0-9_-]{1,40}$/
const ACTOR_RE = /^[a-z0-9_-]{1,40}$/
const BRAND_RE = /^[a-z0-9-]{2,30}$/
const NETWORK_RE = /^[a-z_]{2,20}$/
const SHA256_RE = /^[0-9a-f]{64}$/
const ISO_WITH_OFFSET_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:\d{2})$/

export function isCampaignCode(id: string): boolean {
  return CAMPAIGN_CODE_RE.test(id) && !/\d{7,}/.test(id)
}

function bad(msg: string): never { throw new ContentError(400, msg) }

function text(field: string, v: unknown, max: number): string | null {
  if (v === null) return null
  if (typeof v !== 'string') bad(`${field} must be a string or null`)
  if (v.length > max) bad(`${field} is longer than ${max} characters`)
  if (v.includes('\0')) bad(`${field} contains a NUL character`)
  return v
}

function httpsUrl(field: string, v: unknown): string | null {
  const s = text(field, v, 1000)
  if (s === null) return null
  let u: URL
  try { u = new URL(s) } catch { bad(`${field} is not a URL`) }
  if (u.protocol !== 'https:') bad(`${field} must be an https:// URL`)
  return s
}

function bool(field: string, v: unknown): number | null {
  if (v === null) return null
  if (typeof v !== 'boolean') bad(`${field} must be true, false or null`)
  return v ? 1 : 0
}

function channels(v: unknown): string {
  if (!Array.isArray(v) || v.length > 10) bad('channels must be an array of at most 10 {network, format}')
  const out = v.map((c, i) => {
    if (!c || typeof c !== 'object' || Array.isArray(c)) bad(`channels[${i}] must be an object`)
    const { network, format, ...rest } = c as Record<string, unknown>
    if (Object.keys(rest).length) bad(`channels[${i}] has unknown keys: ${Object.keys(rest).join(', ')}`)
    if (typeof network !== 'string' || !NETWORK_RE.test(network)) bad(`channels[${i}].network must match ${NETWORK_RE}`)
    if (typeof format !== 'string' || !(FORMATS as readonly string[]).includes(format)) bad(`channels[${i}].format must be one of ${FORMATS.join(', ')}`)
    return { network, format }
  })
  return JSON.stringify(out)
}

function media(v: unknown): string {
  if (!Array.isArray(v) || v.length > 20) bad('media must be an array of at most 20 {path, sha256}')
  const out = v.map((m, i) => {
    if (!m || typeof m !== 'object' || Array.isArray(m)) bad(`media[${i}] must be an object`)
    const { path, sha256, ...rest } = m as Record<string, unknown>
    if (Object.keys(rest).length) bad(`media[${i}] has unknown keys: ${Object.keys(rest).join(', ')}`)
    // Viktor 25867 (LOW, defense in depth): media lives in the install tree, never
    // in store/ (DB, tokens) or a dot-directory (.env, .claude-config, .git).
    const segs = typeof path === 'string' ? path.slice(PROJECT_ROOT.length + 1).split('/') : []
    if (typeof path !== 'string' || path.length > 1000 || path.includes('\0') || !path.startsWith(PROJECT_ROOT + '/') ||
        segs.some((g) => g === '' || g === '..' || g.startsWith('.')) || segs[0] === 'store') {
      bad(`media[${i}].path must be an absolute path under ${PROJECT_ROOT}/, not in store/ or a dot-directory, without '..'`)
    }
    if (typeof sha256 !== 'string' || !SHA256_RE.test(sha256)) bad(`media[${i}].sha256 must be 64 lowercase hex characters`)
    return { path, sha256 }
  })
  return JSON.stringify(out)
}

function scheduledAt(v: unknown): string | null {
  if (v === null) return null
  if (typeof v !== 'string' || !ISO_WITH_OFFSET_RE.test(v) || Number.isNaN(Date.parse(v))) {
    bad('scheduled_at must be ISO 8601 with an explicit offset, e.g. 2026-11-12T18:00:00+01:00 (Europe/Budapest)')
  }
  return v
}

/** Validates one writable field and returns the value as stored in SQLite. */
function columnValue(field: string, v: unknown): string | number | null {
  switch (field) {
    case 'title': {
      const s = text(field, v, 200)
      if (!s || !s.trim()) bad('title must not be empty')
      return s
    }
    case 'brand':
      if (typeof v !== 'string' || !BRAND_RE.test(v)) bad(`brand must match ${BRAND_RE}`)
      return v
    case 'channels': return channels(v)
    case 'media': return media(v)
    case 'scheduled_at': return scheduledAt(v)
    case 'final_text': return text(field, v, 10000)
    case 'hook': return text(field, v, 500)
    case 'link': return httpsUrl(field, v)
    case 'live_url': return httpsUrl(field, v)
    case 'ai_status':
      if (v !== null && !(AI_STATUSES as readonly unknown[]).includes(v)) bad(`ai_status must be one of ${AI_STATUSES.join(', ')} or null`)
      return v as string | null
    case 'lex_gate_required': return bool(field, v)
    case 'readback_matches': return bool(field, v)
    case 'brief': return text(field, v, 10000)
    case 'notes': return text(field, v, 5000)
    case 'license': return text(field, v, 2000)
    case 'source_render': return text(field, v, 1000)
    case 'lex_gate_ref': return text(field, v, 500)
    case 'metricool_date': return text(field, v, 50)
    case 'metricool_networks': return text(field, v, 200)
    case 'metricool_readback': return text(field, v, 10000)
    case 'approval_id': return text(field, v, 100)
    default: return bad(`unknown field: ${field}`)
  }
}

type Row = Record<string, unknown>

function toItem(r: Row): ContentItem {
  const asBool = (v: unknown) => (v === null || v === undefined ? null : v === 1)
  return {
    ...(r as unknown as ContentItem),
    channels: JSON.parse((r.channels as string) || '[]'),
    media: JSON.parse((r.media as string) || '[]'),
    lex_gate_required: asBool(r.lex_gate_required),
    readback_matches: asBool(r.readback_matches),
  }
}

/** sha256 over the approved fields, in a fixed order, as stored. */
export function contentHashOf(item: Pick<ContentItem, (typeof HASHED_FIELDS)[number]>): string {
  const canonical = JSON.stringify({
    final_text: item.final_text ?? null,
    hook: item.hook ?? null,
    link: item.link ?? null,
    channels: item.channels.map((c) => ({ network: c.network, format: c.format })),
    scheduled_at: item.scheduled_at ?? null,
    media: item.media.map((m) => ({ path: m.path, sha256: m.sha256 })),
    ai_status: item.ai_status ?? null,
  })
  return createHash('sha256').update(canonical, 'utf8').digest('hex')
}

function actorOf(v: unknown): string {
  if (typeof v !== 'string' || !ACTOR_RE.test(v)) bad('actor is required (your agent id, e.g. "mira"), as body.actor or the X-Agent-Id header')
  return v
}

function logEvent(itemId: string, at: number, actor: string, from: string | null, to: string | null, fields: string[]): void {
  getDb().prepare('INSERT INTO content_item_events (item_id, at, actor, from_status, to_status, fields) VALUES (?, ?, ?, ?, ?, ?)')
    .run(itemId, at, actor, from, to, JSON.stringify(fields))
}

function readRow(id: string): Row | undefined {
  return getDb().prepare('SELECT * FROM content_items WHERE id = ?').get(id) as Row | undefined
}

export function getContentItem(id: string): ContentItem | undefined {
  const r = readRow(id)
  return r ? toItem(r) : undefined
}

export function listContentEvents(id: string): ContentEvent[] {
  const rows = getDb().prepare('SELECT * FROM content_item_events WHERE item_id = ? ORDER BY at, id').all(id) as Row[]
  return rows.map((r) => ({ ...(r as unknown as ContentEvent), fields: JSON.parse((r.fields as string) || '[]') }))
}

export interface ContentListFilter { status?: string[]; brand?: string; from?: string; to?: string }

/** Ordered by scheduled time (unscheduled last), then id. from/to compare instants, so mixed offsets are fine. */
export function listContentItems(filter: ContentListFilter = {}): ContentItem[] {
  const rows = getDb().prepare('SELECT * FROM content_items').all() as Row[]
  const from = filter.from ? Date.parse(filter.from) : null
  const to = filter.to ? Date.parse(filter.to) : null
  return rows.map(toItem)
    .filter((i) => !filter.status?.length || filter.status.includes(i.status))
    .filter((i) => !filter.brand || i.brand === filter.brand)
    .filter((i) => {
      if (from === null && to === null) return true
      if (!i.scheduled_at) return false
      const t = Date.parse(i.scheduled_at)
      return (from === null || t >= from) && (to === null || t <= to)
    })
    .sort((a, b) => {
      const ta = a.scheduled_at ? Date.parse(a.scheduled_at) : Infinity
      const tb = b.scheduled_at ? Date.parse(b.scheduled_at) : Infinity
      return ta === tb ? a.id.localeCompare(b.id) : ta - tb
    })
}

export function createContentItem(body: Record<string, unknown>, headerActor?: string): ContentItem {
  const { id, status = 'brief', actor = headerActor, ...fields } = body
  const who = actorOf(actor)
  if (typeof id !== 'string' || !isCampaignCode(id)) {
    bad('id must be the campaign code: lowercase letters, digits, - and _, at most 40, no run of 7+ digits (p-w45-reel1)')
  }
  if (status !== 'brief' && status !== 'piszkozat') bad("a new post starts as 'brief' or 'piszkozat'")
  for (const k of Object.keys(fields)) {
    if (!(DRAFT_FIELDS as readonly string[]).includes(k) && !(ANYTIME_FIELDS as readonly string[]).includes(k)) {
      bad(`${k} cannot be set on create`)
    }
  }
  if (fields.title === undefined || fields.brand === undefined) bad('title and brand are required')
  const cols: Record<string, string | number | null> = {}
  for (const [k, v] of Object.entries(fields)) cols[k] = columnValue(k, v)
  const now = Date.now()
  const db = getDb()
  const tx = db.transaction(() => {
    if (readRow(id)) throw new ContentError(409, `content item ${id} already exists`)
    const all = { id, status, channels: '[]', media: '[]', ...cols, created_by: who, updated_by: who, created_at: now, updated_at: now }
    const names = Object.keys(all)
    db.prepare(`INSERT INTO content_items (${names.join(', ')}) VALUES (${names.map(() => '?').join(', ')})`).run(...Object.values(all))
    logEvent(id, now, who, null, status as string, Object.keys(cols))
  })
  tx()
  return getContentItem(id)!
}

export function updateContentItem(id: string, body: Record<string, unknown>, headerActor?: string): ContentItem {
  const { status: nextRaw, actor = headerActor, if_updated_at, ...fields } = body
  const who = actorOf(actor)
  for (const k of Object.keys(fields)) if (!WRITABLE.has(k)) bad(`${k} is not writable (unknown or server-managed)`)
  if (nextRaw !== undefined && !(CONTENT_STATUSES as readonly unknown[]).includes(nextRaw)) bad(`status must be one of ${CONTENT_STATUSES.join(', ')}`)
  if (if_updated_at !== undefined && typeof if_updated_at !== 'number') bad('if_updated_at must be the updated_at number you read')
  const cols: Record<string, string | number | null> = {}
  for (const [k, v] of Object.entries(fields)) cols[k] = columnValue(k, v)
  if (nextRaw === undefined && Object.keys(cols).length === 0) bad('nothing to change')

  const db = getDb()
  const tx = db.transaction((): void => {
    const row = readRow(id)
    if (!row) throw new ContentError(404, `content item ${id} not found`)
    const cur = toItem(row)
    if (if_updated_at !== undefined && if_updated_at !== cur.updated_at) {
      throw new ContentError(409, `content item ${id} changed since you read it (updated_at ${cur.updated_at}); read it again`)
    }
    const next = (nextRaw ?? cur.status) as ContentStatus
    const moving = next !== cur.status
    if (moving && !TRANSITIONS[cur.status].includes(next)) {
      throw new ContentError(409, `${cur.status} -> ${next} is not allowed; from ${cur.status}: ${TRANSITIONS[cur.status].join(', ') || 'none (final)'}`)
    }
    // Field locks. Draft fields: editable unless the row is frozen now; a move
    // back to piszkozat/brief unlocks in the same request, and edits sent with
    // the move INTO a frozen status are part of what gets frozen (and hashed).
    // After-scheduling fields: only where the row ends up scheduled.
    // approval_id: only while asking (or in the very move to jovahagyva).
    if (cur.status === 'elvetve' || cur.status === 'merve') {
      const blocked = Object.keys(cols).filter((k) => k !== 'notes')
      if (blocked.length) throw new ContentError(409, `${cur.status} is final; only notes can change (got ${blocked.join(', ')})`)
    }
    const unlocking = moving && (next === 'piszkozat' || next === 'brief')
    for (const k of Object.keys(cols)) {
      if ((DRAFT_FIELDS as readonly string[]).includes(k) && FROZEN.has(cur.status) && !unlocking) {
        throw new ContentError(409, `${k} is locked in ${cur.status} (the approval covers it); move the post back to piszkozat to edit`)
      }
      if ((POST_SCHEDULE_FIELDS as readonly string[]).includes(k) && !SCHEDULED.has(next)) {
        throw new ContentError(409, `${k} is written after scheduling only (utemezve, kint, merve), not in ${next}`)
      }
      if (k === 'approval_id' && !(next === 'jovahagyas-kerve' || (cur.status === 'jovahagyas-kerve' && next === 'jovahagyva'))) {
        throw new ContentError(409, 'approval_id is set only while the post is in jovahagyas-kerve (or with the move to jovahagyva)')
      }
    }

    const merged = toItem({ ...row, ...cols })
    const extra: Record<string, string | number | null> = {}
    if (moving) {
      if (next === 'piszkozat' || next === 'brief') {
        extra.content_hash = null; extra.approval_id = null; extra.approved_at = null
      }
      if (next === 'jogi-ok') {
        if (!merged.lex_gate_ref?.trim()) throw new ContentError(409, "jogi-ok needs lex_gate_ref (Lex's message or file)")
      }
      if (next === 'jovahagyas-kerve') {
        const missing: string[] = []
        if (!merged.final_text?.trim()) missing.push('final_text')
        if (!merged.channels.length) missing.push('channels')
        if (!merged.scheduled_at) missing.push('scheduled_at')
        if (!merged.ai_status) missing.push('ai_status')
        if (merged.lex_gate_required === null) missing.push('lex_gate_required')
        if (missing.length) throw new ContentError(409, `jovahagyas-kerve needs: ${missing.join(', ')}`)
        if (merged.lex_gate_required && cur.status !== 'jogi-ok') {
          throw new ContentError(409, 'lex_gate_required is true: the post goes through jogi-ok before jovahagyas-kerve')
        }
        extra.content_hash = contentHashOf(merged)
        if (cols.approval_id === undefined) extra.approval_id = null
      }
      if (next === 'jovahagyva' && cur.status === 'jovahagyas-kerve') {
        const approvalId = merged.approval_id
        if (!approvalId) throw new ContentError(409, 'jovahagyva needs approval_id (the approvals row Patrik approved)')
        const a = getApproval(approvalId)
        if (!a) throw new ContentError(409, `approval ${approvalId} not found`)
        if (a.category !== APPROVAL_CATEGORY) throw new ContentError(409, `approval ${approvalId} is category ${a.category}, not ${APPROVAL_CATEGORY}`)
        if (a.status !== 'approved') throw new ContentError(409, `approval ${approvalId} is ${a.status}, not approved`)
        // Viktor 25867: a route-side PATCH can set any status with a self-asserted
        // resolved_by; only the approval bot's button (resolveApprovalByBot, the
        // single writer of resolution_channel='approval_bot') counts as Patrik's word.
        if (a.resolution_channel !== 'approval_bot' || a.resolved_by !== 'telegram_button') {
          throw new ContentError(409, `approval ${approvalId} was not resolved by the approval bot`)
        }
        if (!a.content_hash || a.content_hash !== cur.content_hash) {
          throw new ContentError(409, `approval ${approvalId} is for different content (hash mismatch); request a new approval for this content`)
        }
        extra.approved_at = a.resolved_at ? a.resolved_at * 1000 : Date.now()
      }
      if (next === 'kint' && !merged.live_url) throw new ContentError(409, 'kint needs live_url')
    }

    const now = Date.now()
    const set = { ...cols, ...extra, ...(moving ? { status: next } : {}), updated_by: who, updated_at: now }
    const names = Object.keys(set)
    db.prepare(`UPDATE content_items SET ${names.map((n) => `${n} = ?`).join(', ')} WHERE id = ?`).run(...Object.values(set), id)
    logEvent(id, now, who, moving ? cur.status : null, moving ? next : null, Object.keys(cols))
  })
  tx()
  return getContentItem(id)!
}
