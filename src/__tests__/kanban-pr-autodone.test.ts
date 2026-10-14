// Card bf868101: a card whose referenced PRs all merged moves to done on its own.
// Under test: the reference parser (what counts as a PR, what is ambiguous or
// foreign), the all-merged rule (one open / closed-unmerged / unknown PR keeps the
// card where it is; a PR merged before the card existed is context), and one real
// pass over an in-memory board with an injected fetcher -- no network.
import { describe, it, expect, beforeEach } from 'vitest'
import {
  initDatabase, createKanbanCard, getKanbanCard, getKanbanComments, addKanbanComment, moveKanbanCard,
} from '../db.js'
import {
  parsePrRefs, parseRepoList, decideAutodone, autodoneComment, prRefKey, runKanbanPrAutodonePass,
  createGithubPrFetcher, AUTODONE_AUTHOR, _resetAutodoneCacheForTests, _resetPrEtagCacheForTests, type PrState, type PrRef,
} from '../web/kanban-pr-autodone.js'
import { getSettingDefinition, validateSettingValue } from '../config-registry.js'

const MARABEL = 'kiskodzsek/marabel'
const MARVEEN = 'kiskodzsek/marveen'
const BOTH = [MARABEL, MARVEEN]
const now = () => Math.floor(Date.now() / 1000)
const merged = (sha = 'abcdef1234567', at = now() + 5): PrState => ({ state: 'closed', merged: true, mergedAt: at, mergeSha: sha })
const open: PrState = { state: 'open', merged: false, mergedAt: null, mergeSha: null }
const closedUnmerged: PrState = { state: 'closed', merged: false, mergedAt: null, mergeSha: null }

describe('parsePrRefs', () => {
  it('reads full PR URLs of configured repos, case-insensitively, de-duplicated', () => {
    const p = parsePrRefs([
      'PR: https://github.com/kiskodzsek/marabel/pull/412',
      'ugyanaz: https://github.com/Kiskodzsek/Marabel/pull/412/files, és https://github.com/kiskodzsek/marveen/pull/27#issuecomment-1',
    ], BOTH)
    expect(p.refs.map(prRefKey).sort()).toEqual(['kiskodzsek/marabel#412', 'kiskodzsek/marveen#27'])
    expect(p.foreign).toEqual([])
    expect(p.ambiguous).toEqual([])
  })

  it('marks a PR URL outside the configured repos as foreign', () => {
    const p = parsePrRefs(['upstream: https://github.com/Szotasz/marveen/pull/1501'], BOTH)
    expect(p.refs).toEqual([])
    expect(p.foreign).toHaveLength(1)
  })

  it('reads owner/repo#N for configured repos only, and ignores other slash-hash text', () => {
    const p = parsePrRefs(['kiskodzsek/marveen#26 és src/foo#12 és other/repo#3'], BOTH)
    expect(p.refs.map(prRefKey)).toEqual(['kiskodzsek/marveen#26'])
    expect(p.foreign).toEqual([])
  })

  it('does NOT read a plain "#N" (that is the kanban card sequence on this board)', () => {
    const p = parsePrRefs(['lásd #123 és #4567'], [MARABEL])
    expect(p.refs).toEqual([])
    expect(p.ambiguous).toEqual([])
  })

  it('resolves "PR #N" when exactly one repo is configured', () => {
    const p = parsePrRefs(['PR #88 kész, PR#89 is'], [MARABEL])
    expect(p.refs.map(prRefKey).sort()).toEqual(['kiskodzsek/marabel#88', 'kiskodzsek/marabel#89'])
  })

  it('resolves "PR #N" to the one repo the card URLs name', () => {
    const p = parsePrRefs(['https://github.com/kiskodzsek/marveen/pull/27', 'a követő PR #28'], BOTH)
    expect(p.refs.map(prRefKey).sort()).toEqual(['kiskodzsek/marveen#27', 'kiskodzsek/marveen#28'])
  })

  it('leaves "PR #N" ambiguous with several repos configured and no single-repo hint', () => {
    expect(parsePrRefs(['PR #28'], BOTH).ambiguous).toEqual(['PR #28'])
    const mixed = parsePrRefs([
      'https://github.com/kiskodzsek/marveen/pull/27', 'https://github.com/kiskodzsek/marabel/pull/5', 'PR #6',
    ], BOTH)
    expect(mixed.ambiguous).toEqual(['PR #6'])
  })

  it('parseRepoList normalises and drops junk', () => {
    expect(parseRepoList(' Kiskodzsek/Marabel, kiskodzsek/marabel  kiskodzsek/marveen,nope')).toEqual([MARABEL, MARVEEN])
    expect(parseRepoList('')).toEqual([])
  })
})

describe('decideAutodone (all-merged rule)', () => {
  const ref = (n: number, repo = 'marabel'): PrRef => ({ owner: 'kiskodzsek', repo, number: n })
  const parse = (refs: PrRef[]) => ({ refs, ambiguous: [], foreign: [] })
  const states = (pairs: Array<[PrRef, PrState | null]>) => new Map(pairs.map(([r, s]) => [prRefKey(r), s]))
  const created = now()

  it('done when every referenced PR merged after the card was created', () => {
    const d = decideAutodone(parse([ref(1), ref(2)]), states([[ref(1), merged('1111111aaa')], [ref(2), merged('2222222bbb')]]), created)
    expect(d.action).toBe('done')
  })

  it('nothing when one PR is still open', () => {
    expect(decideAutodone(parse([ref(1), ref(2)]), states([[ref(1), merged()], [ref(2), open]]), created))
      .toEqual({ action: 'skip', reason: 'not-merged' })
  })

  it('nothing when one PR was closed without merging', () => {
    expect(decideAutodone(parse([ref(1)]), states([[ref(1), closedUnmerged]]), created))
      .toEqual({ action: 'skip', reason: 'not-merged' })
  })

  it('nothing when a lookup failed', () => {
    expect(decideAutodone(parse([ref(1), ref(2)]), states([[ref(1), merged()], [ref(2), null]]), created))
      .toEqual({ action: 'skip', reason: 'unknown' })
  })

  it('nothing without a PR reference, or with an ambiguous / foreign one', () => {
    expect(decideAutodone(parse([]), new Map(), created)).toEqual({ action: 'skip', reason: 'no-pr' })
    expect(decideAutodone({ refs: [ref(1)], ambiguous: ['PR #2'], foreign: [] }, states([[ref(1), merged()]]), created).action).toBe('skip')
    expect(decideAutodone({ refs: [ref(1)], ambiguous: [], foreign: ['x'] }, states([[ref(1), merged()]]), created).action).toBe('skip')
  })

  it('a PR merged before the card existed is context: it neither counts nor blocks', () => {
    const old = merged('0000000old', created - 3600)
    expect(decideAutodone(parse([ref(1)]), states([[ref(1), old]]), created)).toEqual({ action: 'skip', reason: 'only-context' })
    const d = decideAutodone(parse([ref(1), ref(2)]), states([[ref(1), old], [ref(2), merged('2222222new')]]), created)
    expect(d).toEqual({ action: 'done', merged: [{ ref: ref(2), sha: '2222222new' }] })
  })

  it('comment names the PR number and the short sha', () => {
    expect(autodoneComment([{ ref: ref(412), sha: 'abcdef1234567' }]))
      .toBe('Automatikusan done: a PR #412 beolvadt (abcdef1), kiskodzsek/marabel.')
    expect(autodoneComment([{ ref: ref(1), sha: 'aaaaaaaa1' }, { ref: ref(27, 'marveen'), sha: null }]))
      .toContain('kiskodzsek/marabel#1 (aaaaaaa), kiskodzsek/marveen#27 (sha ismeretlen)')
  })
})

describe('runKanbanPrAutodonePass (in-memory board, injected fetcher)', () => {
  beforeEach(() => {
    initDatabase(':memory:')
    _resetAutodoneCacheForTests()
  })

  function fetcher(table: Record<string, PrState | null>) {
    const calls: string[] = []
    return {
      calls,
      fetchPr: async (r: PrRef) => { calls.push(prRefKey(r)); return table[prRefKey(r)] ?? null },
    }
  }

  it('moves an all-merged card to done with ONE automated comment, and leaves the others alone', async () => {
    createKanbanCard({ id: 'ok', title: 'Fix https://github.com/kiskodzsek/marabel/pull/10', status: 'waiting' })
    createKanbanCard({ id: 'half', title: 'Két PR', status: 'in_progress' })
    addKanbanComment('half', 'dave', 'https://github.com/kiskodzsek/marabel/pull/10 és https://github.com/kiskodzsek/marabel/pull/11')
    createKanbanCard({ id: 'nopr', title: 'Nincs PR', status: 'in_progress' })
    createKanbanCard({ id: 'already', title: 'https://github.com/kiskodzsek/marabel/pull/10', status: 'done' })
    const f = fetcher({ 'kiskodzsek/marabel#10': merged('1234567890abc'), 'kiskodzsek/marabel#11': open })

    const res = await runKanbanPrAutodonePass({ repos: [MARABEL], fetchPr: f.fetchPr })

    expect(res.closed.map((c) => c.id)).toEqual(['ok'])
    expect(getKanbanCard('ok')!.status).toBe('done')
    const comments = getKanbanComments('ok')
    expect(comments).toHaveLength(1)
    expect(comments[0].author).toBe(AUTODONE_AUTHOR)
    expect(comments[0].automated).toBe(1)
    expect(comments[0].content).toBe('Automatikusan done: a PR #10 beolvadt (1234567), kiskodzsek/marabel.')
    expect(getKanbanCard('half')!.status).toBe('in_progress')
    expect(getKanbanCard('nopr')!.status).toBe('in_progress')
    // each distinct PR asked once per pass, the done card's refs not at all
    expect(f.calls.sort()).toEqual(['kiskodzsek/marabel#10', 'kiskodzsek/marabel#11'])
  })

  it('never touches a card again after a human reopened an auto-closed card', async () => {
    createKanbanCard({ id: 'c', title: 'https://github.com/kiskodzsek/marabel/pull/10', status: 'in_progress' })
    const f = fetcher({ 'kiskodzsek/marabel#10': merged() })
    await runKanbanPrAutodonePass({ repos: [MARABEL], fetchPr: f.fetchPr })
    expect(getKanbanCard('c')!.status).toBe('done')
    moveKanbanCard('c', 'in_progress', 0, 'patrik')
    const again = await runKanbanPrAutodonePass({ repos: [MARABEL], fetchPr: f.fetchPr })
    expect(again.closed).toEqual([])
    expect(getKanbanCard('c')!.status).toBe('in_progress')
  })

  it('ignores the description and refs in the automation own comments', async () => {
    createKanbanCard({ id: 'd', title: 'Leírásban van a PR', status: 'planned', description: 'https://github.com/kiskodzsek/marabel/pull/10' })
    const f = fetcher({ 'kiskodzsek/marabel#10': merged() })
    const res = await runKanbanPrAutodonePass({ repos: [MARABEL], fetchPr: f.fetchPr })
    expect(res.closed).toEqual([])
    expect(f.calls).toEqual([])
  })

  it('a card with a foreign PR URL is not looked up and not moved', async () => {
    createKanbanCard({ id: 'f', title: 'https://github.com/kiskodzsek/marabel/pull/10 + https://github.com/Szotasz/marveen/pull/1', status: 'in_progress' })
    const f = fetcher({ 'kiskodzsek/marabel#10': merged() })
    const res = await runKanbanPrAutodonePass({ repos: [MARABEL], fetchPr: f.fetchPr })
    expect(res.closed).toEqual([])
    expect(f.calls).toEqual([])
  })

  it('a fetcher that throws reads as unknown: nothing moves', async () => {
    createKanbanCard({ id: 't', title: 'https://github.com/kiskodzsek/marabel/pull/10', status: 'in_progress' })
    const res = await runKanbanPrAutodonePass({ repos: [MARABEL], fetchPr: async () => { throw new Error('boom') } })
    expect(res.closed).toEqual([])
    expect(getKanbanCard('t')!.status).toBe('in_progress')
  })

  it('caps the lookups per pass; refs beyond the cap read as unknown', async () => {
    createKanbanCard({ id: 'm', title: 'PR #1 PR #2 PR #3', status: 'in_progress' })
    const f = fetcher({ 'kiskodzsek/marabel#1': merged(), 'kiskodzsek/marabel#2': merged(), 'kiskodzsek/marabel#3': merged() })
    const res = await runKanbanPrAutodonePass({ repos: [MARABEL], fetchPr: f.fetchPr, maxFetches: 2 })
    expect(res.fetched).toBe(2)
    expect(res.closed).toEqual([])
  })
})

describe('createGithubPrFetcher', () => {
  const ref: PrRef = { owner: 'kiskodzsek', repo: 'marabel', number: 7 }
  beforeEach(() => { _resetPrEtagCacheForTests() })
  const fake = (status: number, body: unknown) => {
    const seen: { url?: string; auth?: string } = {}
    const impl = (async (url: string, init: RequestInit) => {
      seen.url = url
      seen.auth = (init.headers as Record<string, string>)['Authorization']
      return new Response(JSON.stringify(body), { status })
    }) as unknown as typeof fetch
    return { impl, seen }
  }

  it('maps a merged PR and sends the token as a Bearer header', async () => {
    const { impl, seen } = fake(200, { state: 'closed', merged: true, merged_at: '2026-10-14T10:00:00Z', merge_commit_sha: 'deadbeef1' })
    const st = await createGithubPrFetcher('tok', impl)(ref)
    expect(seen.url).toBe('https://api.github.com/repos/kiskodzsek/marabel/pulls/7')
    expect(seen.auth).toBe('Bearer tok')
    expect(st).toEqual({ state: 'closed', merged: true, mergedAt: Date.parse('2026-10-14T10:00:00Z') / 1000, mergeSha: 'deadbeef1' })
  })

  it('maps open, and a non-200 to null (unknown)', async () => {
    expect((await createGithubPrFetcher('t', fake(200, { state: 'open', merged: false, merged_at: null }).impl)(ref))?.merged).toBe(false)
    expect(await createGithubPrFetcher('t', fake(404, { message: 'Not Found' }).impl)(ref)).toBeNull()
  })
})

describe('createGithubPrFetcher conditional requests (rate-limit friendly)', () => {
  beforeEach(() => { _resetPrEtagCacheForTests() })
  const ref: PrRef = { owner: 'kiskodzsek', repo: 'marveen', number: 30 }

  it('re-asks an open PR with If-None-Match and serves a 304 from the cache', async () => {
    const sent: Array<string | undefined> = []
    let call = 0
    const impl = (async (_url: string, init: RequestInit) => {
      sent.push((init.headers as Record<string, string>)['If-None-Match'])
      call++
      if (call === 1) return new Response(JSON.stringify({ state: 'open', merged: false, merged_at: null }), { status: 200, headers: { ETag: 'W/"abc"' } })
      return new Response(null, { status: 304 })
    }) as unknown as typeof fetch
    const f = createGithubPrFetcher('t', impl)
    expect((await f(ref))?.state).toBe('open')
    expect((await f(ref))?.state).toBe('open')
    expect(sent).toEqual([undefined, 'W/"abc"'])
  })

  it('a 304 without a cached answer reads as unknown, never as a state', async () => {
    const impl = (async () => new Response(null, { status: 304 })) as unknown as typeof fetch
    expect(await createGithubPrFetcher('t', impl)(ref)).toBeNull()
  })
})

describe('autodone settings', () => {
  it('ships off, with a github-prefixed Vault id and an owner/repo list', () => {
    expect(getSettingDefinition('KANBAN_AUTODONE_ENABLED')!.default).toBe('0')
    const secret = getSettingDefinition('KANBAN_AUTODONE_GITHUB_SECRET_ID')!
    // No new credential: the default is the Vault id scripts/github-pr-monitor.sh already resolves.
    expect(secret.default).toBe('github-fleet-token')
    expect(validateSettingValue(secret, secret.default).ok).toBe(true)
    expect(validateSettingValue(secret, 'github-github_personal_access_token').ok).toBe(true)
    expect(validateSettingValue(secret, 'SUPABASE_ACCESS_TOKEN_OPS').ok).toBe(false)
    const repos = getSettingDefinition('KANBAN_AUTODONE_REPOS')!
    expect(validateSettingValue(repos, 'kiskodzsek/marabel,kiskodzsek/marveen').ok).toBe(true)
    expect(validateSettingValue(repos, 'marabel').ok).toBe(false)
  })
})
