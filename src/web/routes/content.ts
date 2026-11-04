import {
  ContentError,
  CONTENT_STATUSES,
  createContentItem,
  getContentItem,
  listContentEvents,
  listContentItems,
  updateContentItem,
} from '../../content-calendar.js'
import { json, methodNotAllowed, readBody } from '../http-helpers.js'
import type { RouteContext } from './types.js'

// CONTENTCAL1104 -- the marketing content calendar API (card b84e1760).
//   GET   /api/content[?status=a,b&brand=&from=&to=]   list, ordered by scheduled time
//   POST  /api/content                                  new post (status brief|piszkozat)
//   GET   /api/content/<campaign-code>                  one post + its event log
//   PATCH /api/content/<campaign-code>                  fields and/or status
// Rules (state machine, freeze + content hash, approval binding) live in
// src/content-calendar.ts. There is no DELETE: a dropped post is 'elvetve'.
// Bearer-gated like every /api/* route; the actor is body.actor or X-Agent-Id.

const MAX_BODY = 256 * 1024
const ITEM_RE = /^\/api\/content\/([^/]+)$/

async function readJson(ctx: RouteContext): Promise<Record<string, unknown>> {
  const raw = (await readBody(ctx.req, { maxBytes: MAX_BODY })).toString('utf8')
  let parsed: unknown
  try { parsed = JSON.parse(raw) } catch { throw new ContentError(400, 'body must be a JSON object') }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new ContentError(400, 'body must be a JSON object')
  return parsed as Record<string, unknown>
}

function fail(ctx: RouteContext, err: unknown): boolean {
  if (err instanceof ContentError) { json(ctx.res, { error: err.message }, err.status); return true }
  throw err
}

export async function tryHandleContent(ctx: RouteContext): Promise<boolean> {
  const { res, path, method, url } = ctx
  const agent = ctx.auth?.agent

  if (path === '/api/content') {
    if (method === 'GET') {
      const status = (url.searchParams.get('status') ?? '').split(',').map((s) => s.trim()).filter(Boolean)
      const unknown = status.filter((s) => !(CONTENT_STATUSES as readonly string[]).includes(s))
      if (unknown.length) { json(res, { error: `unknown status: ${unknown.join(', ')}` }, 400); return true }
      for (const k of ['from', 'to'] as const) {
        const v = url.searchParams.get(k)
        if (v && Number.isNaN(Date.parse(v))) { json(res, { error: `${k} must be an ISO date or date-time` }, 400); return true }
      }
      const items = listContentItems({
        status,
        brand: url.searchParams.get('brand') ?? undefined,
        from: url.searchParams.get('from') ?? undefined,
        to: url.searchParams.get('to') ?? undefined,
      })
      json(res, { items })
      return true
    }
    if (method === 'POST') {
      try {
        const item = createContentItem(await readJson(ctx), agent)
        json(res, item, 201)
      } catch (err) { return fail(ctx, err) }
      return true
    }
    methodNotAllowed(res, method, ['GET', 'POST'])
    return true
  }

  const m = path.match(ITEM_RE)
  if (m) {
    let id: string
    try { id = decodeURIComponent(m[1]) } catch { json(res, { error: 'bad percent-encoding in the path' }, 400); return true }
    if (method === 'GET') {
      const item = getContentItem(id)
      if (!item) { json(res, { error: `content item ${id} not found` }, 404); return true }
      json(res, { ...item, events: listContentEvents(id) })
      return true
    }
    if (method === 'PATCH') {
      try {
        json(res, updateContentItem(id, await readJson(ctx), agent))
      } catch (err) { return fail(ctx, err) }
      return true
    }
    methodNotAllowed(res, method, ['GET', 'PATCH'])
    return true
  }

  return false
}
