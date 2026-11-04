// CONTENTCAL1104: the content calendar API (routes/content.ts + content-calendar.ts)
// against an in-memory database. The negative cases are the point: a post must
// not reach 'jovahagyva' without a matching social_post approval, approved
// fields must not change behind the approval, and no status may be skipped.
import { describe, it, expect, beforeEach } from 'vitest'
import { Readable } from 'node:stream'
import { initDatabase, getDb } from '../db.js'
import { tryHandleContent } from '../web/routes/content.js'
import { contentHashOf, isCampaignCode } from '../content-calendar.js'
import { PROJECT_ROOT } from '../config.js'
import type { RouteContext } from '../web/routes/types.js'

async function call(method: string, path: string, body?: unknown, agent?: string): Promise<{ status: number; body: any; handled: boolean }> {
  const out: { status: number; body: any } = { status: 0, body: null }
  const res: any = {
    writeHead(status: number) { out.status = status; return res },
    end(chunk?: string) { if (chunk) out.body = JSON.parse(chunk) },
  }
  const req: any = Readable.from(body === undefined ? [] : [Buffer.from(typeof body === 'string' ? body : JSON.stringify(body))])
  const url = new URL(`http://localhost:3420${path}`)
  const ctx = { req, res, path: url.pathname, method, url, auth: agent ? { kind: 'token', agent } : { kind: 'token' } } as RouteContext
  const handled = await tryHandleContent(ctx)
  return { ...out, handled }
}

const SHA = 'a'.repeat(64)
const READY = {
  final_text: 'Mesélj nekünk! #marabel https://marabel.hu/?utm_campaign=p-w45-feed1',
  hook: 'Mesélj nekünk!',
  link: 'https://marabel.hu/meseld-el?utm_campaign=p-w45-feed1',
  channels: [{ network: 'ig', format: '4:5' }, { network: 'fb', format: '4:5' }],
  scheduled_at: '2026-11-12T18:00:00+01:00',
  media: [{ path: `${PROJECT_ROOT}/agents/mira/drafts/p-w45-feed1.png`, sha256: SHA }],
  ai_status: 'mi-generalt',
  lex_gate_required: false,
}

// by: how the approval was resolved. 'bot' = what resolveApprovalByBot writes (the
// only path that counts); anything else = what a route-side PATCH can produce.
function approve(id: string, hash: string | null, category = 'social_post', status = 'approved',
  by: { resolved_by: string; channel: string | null } = { resolved_by: 'telegram_button', channel: 'approval_bot' }): void {
  getDb().prepare('INSERT INTO approvals (id, agent_id, category, action_description, status, resolved_at, content_hash, resolved_by, resolution_channel) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)')
    .run(id, 'kernel', category, 'test', status, 1793800000, hash, by.resolved_by, by.channel)
}

async function toAsking(id = 'p-w45-feed1'): Promise<any> {
  expect((await call('POST', '/api/content', { id, brand: 'marabel', title: 'Feed 1', actor: 'magnes' })).status).toBe(201)
  expect((await call('PATCH', `/api/content/${id}`, { status: 'piszkozat', ...READY, actor: 'mira' })).status).toBe(200)
  const r = await call('PATCH', `/api/content/${id}`, { status: 'jovahagyas-kerve', actor: 'mira' })
  expect(r.status).toBe(200)
  return r.body
}

describe('content calendar', () => {
  beforeEach(() => { initDatabase(':memory:') })

  it('campaign code rule: lowercase, max 40, no 7+ digit run', () => {
    expect(isCampaignCode('p-w45-reel1')).toBe(true)
    expect(isCampaignCode('20261106')).toBe(false)
    expect(isCampaignCode('P-w45')).toBe(false)
    expect(isCampaignCode('a'.repeat(41))).toBe(false)
  })

  it('creates a brief, lists it, and logs the event with the actor', async () => {
    const c = await call('POST', '/api/content', { id: 'p-w45-reel1', brand: 'marabel', title: 'Reel 1', brief: 'cél: ...' }, 'magnes')
    expect(c.status).toBe(201)
    expect(c.body).toMatchObject({ id: 'p-w45-reel1', status: 'brief', channels: [], media: [], created_by: 'magnes' })
    const list = await call('GET', '/api/content?status=brief')
    expect(list.body.items.map((i: any) => i.id)).toEqual(['p-w45-reel1'])
    const one = await call('GET', '/api/content/p-w45-reel1')
    expect(one.body.events).toHaveLength(1)
    expect(one.body.events[0]).toMatchObject({ actor: 'magnes', from_status: null, to_status: 'brief' })
  })

  it('rejects a bad id, a missing actor, an unknown field and a duplicate', async () => {
    expect((await call('POST', '/api/content', { id: '20261106', brand: 'marabel', title: 't', actor: 'm' })).status).toBe(400)
    expect((await call('POST', '/api/content', { id: 'p1', brand: 'marabel', title: 't' })).status).toBe(400)
    expect((await call('POST', '/api/content', { id: 'p1', brand: 'marabel', title: 't', actor: 'm', content_hash: SHA })).status).toBe(400)
    expect((await call('POST', '/api/content', { id: 'p1', brand: 'marabel', title: 't', actor: 'm', status: 'jovahagyva' })).status).toBe(400)
    expect((await call('POST', '/api/content', { id: 'p1', brand: 'marabel', title: 't', actor: 'm' })).status).toBe(201)
    expect((await call('POST', '/api/content', { id: 'p1', brand: 'marabel', title: 't', actor: 'm' })).status).toBe(409)
    expect((await call('POST', '/api/content', 'not json', 'm')).status).toBe(400)
  })

  it('validates field shapes (offset time, https link, sha256, format)', async () => {
    await call('POST', '/api/content', { id: 'p2', brand: 'marabel', title: 't', actor: 'm' })
    for (const bad of [
      { scheduled_at: '2026-11-12 18:00' },
      { link: 'http://marabel.hu' },
      { media: [{ path: 'rel/x.png', sha256: SHA }] },
      { media: [{ path: `${PROJECT_ROOT}/shared/../store/x`, sha256: SHA }] },
      { media: [{ path: '/etc/passwd', sha256: SHA }] },
      { media: [{ path: `${PROJECT_ROOT}/store/claudeclaw.db`, sha256: SHA }] },
      { media: [{ path: `${PROJECT_ROOT}/.env`, sha256: SHA }] },
      { media: [{ path: `${PROJECT_ROOT}/agents/mira/.claude-config/x.png`, sha256: SHA }] },
      { media: [{ path: `${PROJECT_ROOT}/shared/x.png`, sha256: 'ABC' }] },
      { channels: [{ network: 'ig', format: '4:3' }] },
      { ai_status: 'maybe' },
    ]) {
      expect((await call('PATCH', '/api/content/p2', { ...bad, actor: 'mira' })).status, JSON.stringify(bad)).toBe(400)
    }
  })

  it('does not allow skipping a status', async () => {
    await call('POST', '/api/content', { id: 'p3', brand: 'marabel', title: 't', actor: 'm', ...READY })
    const r = await call('PATCH', '/api/content/p3', { status: 'jovahagyva', actor: 'mira' })
    expect(r.status).toBe(409)
    expect(r.body.error).toContain('brief -> jovahagyva is not allowed')
    expect((await call('PATCH', '/api/content/p3', { status: 'utemezve', actor: 'mira' })).status).toBe(409)
  })

  it('asking for approval needs the full post and freezes it with a server-side hash', async () => {
    await call('POST', '/api/content', { id: 'p4', brand: 'marabel', title: 't', actor: 'm', status: 'piszkozat' })
    const r = await call('PATCH', '/api/content/p4', { status: 'jovahagyas-kerve', actor: 'mira' })
    expect(r.status).toBe(409)
    expect(r.body.error).toContain('final_text')
    const asked = await toAsking('p5')
    expect(asked.content_hash).toBe(contentHashOf(asked))
    const edit = await call('PATCH', '/api/content/p5', { final_text: 'más szöveg', actor: 'mira' })
    expect(edit.status).toBe(409)
    expect(edit.body.error).toContain('locked')
  })

  it('a post that needs Lex goes through jogi-ok with a reference', async () => {
    await call('POST', '/api/content', { id: 'p6', brand: 'marabel', title: 't', actor: 'm', status: 'piszkozat', ...READY, lex_gate_required: true })
    expect((await call('PATCH', '/api/content/p6', { status: 'jovahagyas-kerve', actor: 'mira' })).status).toBe(409)
    expect((await call('PATCH', '/api/content/p6', { status: 'jogi-ok', actor: 'mira' })).status).toBe(409)
    expect((await call('PATCH', '/api/content/p6', { status: 'jogi-ok', lex_gate_ref: 'Lex 25999', actor: 'mira' })).status).toBe(200)
    expect((await call('PATCH', '/api/content/p6', { final_text: 'x', actor: 'mira' })).status).toBe(409)
    expect((await call('PATCH', '/api/content/p6', { status: 'jovahagyas-kerve', actor: 'mira' })).status).toBe(200)
  })

  it('jovahagyva only with an approved social_post approval of the SAME hash', async () => {
    const asked = await toAsking()
    const path = '/api/content/p-w45-feed1'
    expect((await call('PATCH', path, { status: 'jovahagyva', actor: 'mira' })).status).toBe(409) // no approval_id
    approve('ap-missing-cat', asked.content_hash, 'email_send')
    approve('ap-pending', asked.content_hash, 'social_post', 'pending')
    approve('ap-other', 'b'.repeat(64))
    approve('ap-ok', asked.content_hash)
    // Viktor 25867: approved through the route (self-asserted resolved_by), not the bot's button
    approve('ap-route-patrik', asked.content_hash, 'social_post', 'approved', { resolved_by: 'patrik', channel: null })
    approve('ap-route-text', asked.content_hash, 'social_post', 'approved', { resolved_by: 'telegram_text', channel: null })
    approve('ap-route-forged', asked.content_hash, 'social_post', 'approved', { resolved_by: 'patrik', channel: 'approval_bot' })
    for (const id of ['nope', 'ap-missing-cat', 'ap-pending', 'ap-other', 'ap-route-patrik', 'ap-route-text', 'ap-route-forged']) {
      const r = await call('PATCH', path, { status: 'jovahagyva', approval_id: id, actor: 'mira' })
      expect(r.status, id).toBe(409)
    }
    const ok = await call('PATCH', path, { status: 'jovahagyva', approval_id: 'ap-ok', actor: 'mira' })
    expect(ok.status).toBe(200)
    expect(ok.body).toMatchObject({ status: 'jovahagyva', approval_id: 'ap-ok', approved_at: 1793800000 * 1000 })
    expect((await call('PATCH', path, { approval_id: 'ap-other', actor: 'mira' })).status).toBe(409)
  })

  it('back to piszkozat drops hash and approval; scheduling fields only after scheduling; kint needs live_url', async () => {
    const asked = await toAsking()
    const path = '/api/content/p-w45-feed1'
    approve('ap-ok', asked.content_hash)
    await call('PATCH', path, { status: 'jovahagyva', approval_id: 'ap-ok', actor: 'mira' })
    expect((await call('PATCH', path, { metricool_date: '2026-11-12', actor: 'mira' })).status).toBe(409)
    const sched = await call('PATCH', path, { status: 'utemezve', metricool_date: '2026-11-12', metricool_networks: 'ig, fb', actor: 'mira' })
    expect(sched.status).toBe(200)
    expect((await call('PATCH', path, { status: 'kint', actor: 'mira' })).status).toBe(409)
    expect((await call('PATCH', path, { status: 'kint', live_url: 'https://instagram.com/p/x', readback_matches: true, actor: 'mira' })).status).toBe(200)

    const again = await toAsking('p7')
    approve('ap-7', again.content_hash)
    await call('PATCH', '/api/content/p7', { status: 'jovahagyva', approval_id: 'ap-7', actor: 'mira' })
    const back = await call('PATCH', '/api/content/p7', { status: 'piszkozat', final_text: 'javított', actor: 'mira' })
    expect(back.status).toBe(200)
    expect(back.body).toMatchObject({ status: 'piszkozat', content_hash: null, approval_id: null, approved_at: null, final_text: 'javított' })
  })

  it('optimistic lock: a stale if_updated_at is refused', async () => {
    const c = await call('POST', '/api/content', { id: 'p8', brand: 'marabel', title: 't', actor: 'm' })
    expect((await call('PATCH', '/api/content/p8', { title: 'a', if_updated_at: c.body.updated_at, actor: 'mira' })).status).toBe(200)
    expect((await call('PATCH', '/api/content/p8', { title: 'b', if_updated_at: c.body.updated_at - 1, actor: 'magnes' })).status).toBe(409)
  })

  it('elvetve is final except notes; no DELETE; unknown id 404', async () => {
    await call('POST', '/api/content', { id: 'p9', brand: 'marabel', title: 't', actor: 'm' })
    expect((await call('PATCH', '/api/content/p9', { status: 'elvetve', actor: 'magnes' })).status).toBe(200)
    expect((await call('PATCH', '/api/content/p9', { title: 'x', actor: 'magnes' })).status).toBe(409)
    expect((await call('PATCH', '/api/content/p9', { status: 'brief', actor: 'magnes' })).status).toBe(409)
    expect((await call('PATCH', '/api/content/p9', { notes: 'kihagyva, Patrik', actor: 'magnes' })).status).toBe(200)
    expect((await call('DELETE', '/api/content/p9')).status).toBe(405)
    expect((await call('GET', '/api/content/nincs')).status).toBe(404)
    expect((await call('GET', '/api/content/%E0%A4%A')).status).toBe(400)
    expect((await call('GET', '/api/other')).handled).toBe(false)
  })

  it('list filters by time instant across offsets and orders by schedule', async () => {
    await call('POST', '/api/content', { id: 'late', brand: 'marabel', title: 't', actor: 'm', scheduled_at: '2026-11-13T10:00:00+01:00' })
    await call('POST', '/api/content', { id: 'early', brand: 'marabel', title: 't', actor: 'm', scheduled_at: '2026-11-12T08:00:00Z' })
    await call('POST', '/api/content', { id: 'none', brand: 'myshp', title: 't', actor: 'm' })
    expect((await call('GET', '/api/content')).body.items.map((i: any) => i.id)).toEqual(['early', 'late', 'none'])
    expect((await call('GET', '/api/content?from=2026-11-13T00:00:00%2B01:00')).body.items.map((i: any) => i.id)).toEqual(['late'])
    expect((await call('GET', '/api/content?brand=myshp')).body.items.map((i: any) => i.id)).toEqual(['none'])
    expect((await call('GET', '/api/content?status=nope')).status).toBe(400)
  })
})
