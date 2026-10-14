import { getDb, getKanbanCard, getKanbanComments, listKanbanCards, moveKanbanCard, addKanbanComment } from '../db.js'
import { logger } from '../logger.js'
import { getEffectiveSettingValue } from '../settings-store.js'
import { getSecret } from './vault.js'
import { TOOL_TIMEOUTS } from '../tool-timeouts.js'

// Card bf868101: a card whose pull request(s) merged is done, and nobody should
// have to remember to say so. A periodic check reads every open card, finds the
// PRs it references, asks GitHub whether they merged, and moves the card to done
// with an automated comment once EVERY referenced PR has.
//
// Conservative by construction -- a wrong "done" hides live work, a missed one
// only costs a manual move, so every doubt resolves to "do nothing":
//   - no PR reference                         -> nothing
//   - any referenced PR open or closed-unmerged -> nothing
//   - any reference outside the configured repos, or a bare "PR #N" that cannot
//     be pinned to ONE repo                   -> nothing (we cannot tell what it is)
//   - any lookup failed                       -> nothing this tick
//   - a PR that merged BEFORE the card existed is context ("follows #26"), not the
//     card's deliverable: it neither counts nor blocks, but at least one
//     deliverable PR must remain
//   - a card the automation already closed once and a human reopened is never
//     touched again (the reopen is the human's verdict)
//
// Credentials and cost: no new credential. The token is read in-process from an
// EXISTING Vault entry (KANBAN_AUTODONE_GITHUB_SECRET_ID, default
// "github-fleet-token" -- the same id scripts/github-pr-monitor.sh resolves as
// GH_TOKEN), never logged. Polling runs inside the dashboard process (no GitHub
// Actions minutes): one REST GET per referenced, not-yet-merged PR every 10 min,
// at most 60 per pass, merged answers cached for good, and open ones re-asked
// with If-None-Match so an unchanged PR costs a 304 (not counted against the
// rate limit for authenticated requests).
//
// Reference sources are the title and the comments (not the description, which
// tends to carry background links). Plain "#N" is NOT a PR reference here: on this
// board "#N" is the kanban card sequence (normalizeKanbanRefs rewrites card refs to
// that form), so only these shapes count:
//   https://github.com/<owner>/<repo>/pull/<n>    (any configured repo)
//   <owner>/<repo>#<n>                             (configured repos only)
//   PR #<n> / PR#<n>                               (resolved to a repo only when
//       exactly one repo is configured, or the card's own URLs name exactly one)

export const AUTODONE_AUTHOR = 'pr-autodone'

export interface PrRef { owner: string; repo: string; number: number }

export function prRefKey(r: PrRef): string {
  return `${r.owner}/${r.repo}#${r.number}`.toLowerCase()
}

export interface PrRefParse {
  refs: PrRef[]
  /** bare "PR #N" mentions that could not be pinned to one repo */
  ambiguous: string[]
  /** PR URLs pointing outside the configured repos */
  foreign: string[]
}

const URL_RE = /https?:\/\/(?:www\.)?github\.com\/([A-Za-z0-9][A-Za-z0-9-]{0,38})\/([A-Za-z0-9._-]{1,100})\/pull\/(\d{1,7})(?!\d)/gi
const SLUG_RE = /(?<![\w./-])([A-Za-z0-9][A-Za-z0-9-]{0,38})\/([A-Za-z0-9._-]{1,100})#(\d{1,7})(?!\d)/g
const BARE_RE = /(?<![\w/])PR\s*#(\d{1,7})(?!\d)/gi

/** `owner/repo` list from a comma/space separated setting value, lowercased, de-duplicated. */
export function parseRepoList(raw: string): string[] {
  return [...new Set(raw.split(/[\s,]+/).map((s) => s.trim().toLowerCase()).filter((s) => /^[a-z0-9][a-z0-9-]{0,38}\/[a-z0-9._-]{1,100}$/.test(s)))]
}

export function parsePrRefs(texts: string[], allowedRepos: string[]): PrRefParse {
  const allowed = new Set(allowedRepos.map((r) => r.toLowerCase()))
  const refs = new Map<string, PrRef>()
  const foreign: string[] = []
  const ambiguous: string[] = []
  const add = (owner: string, repo: string, n: string) => {
    const ref = { owner: owner.toLowerCase(), repo: repo.toLowerCase(), number: Number(n) }
    refs.set(prRefKey(ref), ref)
  }
  const bare: string[] = []
  for (const text of texts) {
    if (!text) continue
    for (const m of text.matchAll(URL_RE)) {
      if (allowed.has(`${m[1]}/${m[2]}`.toLowerCase())) add(m[1], m[2], m[3])
      else foreign.push(m[0])
    }
    // A URL's path never matches SLUG_RE ("pull/12" has no '#<digits>'), so the
    // two patterns cannot double-count. Unconfigured slugs are ignored, not
    // foreign: "src/foo#12"-like text is too common to block a card on.
    for (const m of text.matchAll(SLUG_RE)) {
      if (allowed.has(`${m[1]}/${m[2]}`.toLowerCase())) add(m[1], m[2], m[3])
    }
    for (const m of text.matchAll(BARE_RE)) bare.push(m[1])
  }
  if (bare.length > 0) {
    const hinted = new Set([...refs.values()].map((r) => `${r.owner}/${r.repo}`))
    const target = allowed.size === 1 ? [...allowed][0] : hinted.size === 1 ? [...hinted][0] : null
    for (const n of bare) {
      if (target) { const [o, r] = target.split('/'); add(o, r, n) } else ambiguous.push(`PR #${n}`)
    }
  }
  return { refs: [...refs.values()], ambiguous, foreign }
}

export interface PrState {
  merged: boolean
  /** 'open' | 'closed' as GitHub reports it */
  state: string
  /** epoch seconds, null when not merged */
  mergedAt: number | null
  mergeSha: string | null
}

export type AutodoneDecision =
  | { action: 'done'; merged: Array<{ ref: PrRef; sha: string | null }> }
  | { action: 'skip'; reason: 'no-pr' | 'ambiguous' | 'foreign' | 'unknown' | 'not-merged' | 'only-context' }

export function decideAutodone(parse: PrRefParse, states: Map<string, PrState | null>, cardCreatedAt: number): AutodoneDecision {
  if (parse.foreign.length > 0) return { action: 'skip', reason: 'foreign' }
  if (parse.ambiguous.length > 0) return { action: 'skip', reason: 'ambiguous' }
  if (parse.refs.length === 0) return { action: 'skip', reason: 'no-pr' }
  const deliverables: Array<{ ref: PrRef; sha: string | null }> = []
  for (const ref of parse.refs) {
    const st = states.get(prRefKey(ref))
    if (!st) return { action: 'skip', reason: 'unknown' }
    if (!st.merged) return { action: 'skip', reason: 'not-merged' }
    // Merged before the card existed: context, not this card's deliverable.
    if (st.mergedAt !== null && st.mergedAt < cardCreatedAt) continue
    deliverables.push({ ref, sha: st.mergeSha })
  }
  if (deliverables.length === 0) return { action: 'skip', reason: 'only-context' }
  return { action: 'done', merged: deliverables }
}

export function autodoneComment(merged: Array<{ ref: PrRef; sha: string | null }>): string {
  const short = (sha: string | null) => (sha ? sha.slice(0, 7) : 'sha ismeretlen')
  if (merged.length === 1) {
    const { ref, sha } = merged[0]
    return `Automatikusan done: a PR #${ref.number} beolvadt (${short(sha)}), ${ref.owner}/${ref.repo}.`
  }
  return `Automatikusan done: minden hivatkozott PR beolvadt: ${merged.map(({ ref, sha }) => `${ref.owner}/${ref.repo}#${ref.number} (${short(sha)})`).join(', ')}.`
}

export type PrFetcher = (ref: PrRef) => Promise<PrState | null>

export interface AutodoneDeps {
  repos: string[]
  fetchPr: PrFetcher
  /** upper bound on GitHub lookups per pass; refs beyond it read as unknown this pass */
  maxFetches?: number
}

export interface AutodonePassResult { examined: number; fetched: number; closed: Array<{ id: string; comment: string }> }

// Merged is terminal, so a merged answer is cached for the process lifetime and
// never asked again; open/closed answers are re-asked every pass.
const mergedCache = new Map<string, PrState>()
export function _resetAutodoneCacheForTests(): void { mergedCache.clear() }

export async function runKanbanPrAutodonePass(deps: AutodoneDeps): Promise<AutodonePassResult> {
  const maxFetches = deps.maxFetches ?? 60
  const candidates: Array<{ id: string; createdAt: number; parse: PrRefParse }> = []
  const cards = listKanbanCards().filter((c) => c.status !== 'done')
  for (const card of cards) {
    const comments = getKanbanComments(card.id)
    if (comments.some((c) => c.author === AUTODONE_AUTHOR)) continue
    const parse = parsePrRefs([card.title, ...comments.map((c) => c.content)], deps.repos)
    if (parse.refs.length === 0 || parse.foreign.length > 0 || parse.ambiguous.length > 0) continue
    candidates.push({ id: card.id, createdAt: card.created_at, parse })
  }

  const states = new Map<string, PrState | null>()
  let fetched = 0
  for (const { parse } of candidates) {
    for (const ref of parse.refs) {
      const key = prRefKey(ref)
      if (states.has(key)) continue
      const cached = mergedCache.get(key)
      if (cached) { states.set(key, cached); continue }
      if (fetched >= maxFetches) { states.set(key, null); continue }
      fetched++
      let st: PrState | null = null
      try { st = await deps.fetchPr(ref) } catch { st = null }
      states.set(key, st)
      if (st?.merged) mergedCache.set(key, st)
    }
  }

  const closed: AutodonePassResult['closed'] = []
  for (const cand of candidates) {
    const decision = decideAutodone(cand.parse, states, cand.createdAt)
    if (decision.action !== 'done') continue
    // The lookups were async: a human may have moved or archived the card meanwhile.
    const fresh = getKanbanCard(cand.id)
    if (!fresh || fresh.status === 'done' || fresh.archived_at) continue
    const comment = autodoneComment(decision.merged)
    getDb().transaction(() => {
      moveKanbanCard(cand.id, 'done', 0, AUTODONE_AUTHOR)
      addKanbanComment(cand.id, AUTODONE_AUTHOR, comment, { automated: true })
    })()
    closed.push({ id: cand.id, comment })
  }
  return { examined: cards.length, fetched, closed }
}

// --- default GitHub fetcher + settings wiring ---------------------------------

// Conditional requests: GitHub answers an unchanged resource with 304, and a 304
// to an authenticated request does not count against the rate limit. An open PR
// is re-asked every pass, so this is what keeps a long-open PR nearly free.
// Module-level (the fetcher is rebuilt every tick with the current token), keyed
// by URL, bounded so a long-lived process cannot grow it without limit.
const etagCache = new Map<string, { etag: string; state: PrState }>()
const ETAG_CACHE_MAX = 500
export function _resetPrEtagCacheForTests(): void { etagCache.clear() }

export function createGithubPrFetcher(token: string, fetchImpl: typeof fetch = fetch): PrFetcher {
  return async (ref) => {
    const url = `https://api.github.com/repos/${ref.owner}/${ref.repo}/pulls/${ref.number}`
    const cached = etagCache.get(url)
    const headers: Record<string, string> = {
      'Accept': 'application/vnd.github+json',
      'Authorization': `Bearer ${token}`,
      'User-Agent': 'marveen-kanban-autodone',
      'X-GitHub-Api-Version': '2022-11-28',
    }
    if (cached) headers['If-None-Match'] = cached.etag
    const res = await fetchImpl(url, { headers, signal: AbortSignal.timeout(TOOL_TIMEOUTS['github']) })
    if (res.status === 304 && cached) return cached.state
    if (!res.ok) return null
    const j = await res.json() as { state?: string; merged?: boolean; merged_at?: string | null; merge_commit_sha?: string | null }
    if (typeof j.state !== 'string') return null
    const mergedAt = j.merged_at ? Math.floor(Date.parse(j.merged_at) / 1000) : null
    const state: PrState = {
      state: j.state,
      merged: j.merged === true || (mergedAt !== null && Number.isFinite(mergedAt)),
      mergedAt: mergedAt !== null && Number.isFinite(mergedAt) ? mergedAt : null,
      mergeSha: typeof j.merge_commit_sha === 'string' ? j.merge_commit_sha : null,
    }
    const etag = res.headers.get('etag')
    if (etag && !state.merged) {
      if (etagCache.size >= ETAG_CACHE_MAX) etagCache.clear()
      etagCache.set(url, { etag, state })
    } else {
      etagCache.delete(url)
    }
    return state
  }
}

function setting(key: string): string {
  try { return String(getEffectiveSettingValue(key)).trim() } catch { return '' }
}

let lastConfigWarning = ''
function warnOnce(msg: string): void {
  if (msg === lastConfigWarning) return
  lastConfigWarning = msg
  logger.warn(msg)
}

async function tick(): Promise<void> {
  try {
    if (setting('KANBAN_AUTODONE_ENABLED') !== '1') return
    const repos = parseRepoList(setting('KANBAN_AUTODONE_REPOS'))
    const secretId = setting('KANBAN_AUTODONE_GITHUB_SECRET_ID')
    if (repos.length === 0 || !secretId) {
      warnOnce('Kanban PR-autodone: enabled, but KANBAN_AUTODONE_REPOS or KANBAN_AUTODONE_GITHUB_SECRET_ID is empty -- idle')
      return
    }
    let token: string | null = null
    try { token = getSecret(secretId) } catch { token = null }
    if (!token) {
      warnOnce(`Kanban PR-autodone: Vault secret "${secretId}" not readable -- idle`)
      return
    }
    lastConfigWarning = ''
    const result = await runKanbanPrAutodonePass({ repos, fetchPr: createGithubPrFetcher(token) })
    for (const c of result.closed) logger.info({ card: c.id, comment: c.comment }, 'Kanban PR-autodone: card moved to done')
  } catch (err) {
    // Best-effort like the archive sweep: never take the process down, retry next tick.
    logger.error({ err }, 'Kanban PR-autodone pass failed')
  }
}

const INITIAL_DELAY_MS = 80_000
const INTERVAL_MS = 10 * 60_000

export function startKanbanPrAutodoneRunner(): NodeJS.Timeout {
  setTimeout(() => { void tick() }, INITIAL_DELAY_MS)
  return setInterval(() => { void tick() }, INTERVAL_MS)
}
