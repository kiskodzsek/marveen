// Card bf868101: a card moved INTO waiting through the API must say who it waits
// for and on what -- a "VÁR: <ki> - <mire>" line, either in the move's `comment`
// or in the card's latest comment. Otherwise 400, and the card does not move.
// A move within the column (reorder, whole-card PUT echo) is not a transition and
// stays unchecked.
import { describe, it, expect, beforeEach } from 'vitest'
import { Readable } from 'node:stream'
import { initDatabase, createKanbanCard, getKanbanCard, getKanbanComments, addKanbanComment } from '../db.js'
import { tryHandleKanban } from '../web/routes/kanban.js'
import { hasVarLine, WAITING_GATE_ERROR } from '../web/kanban-waiting-gate.js'
import type { RouteContext } from '../web/routes/types.js'

function call(method: 'POST' | 'PUT', path: string, payload: unknown): { ctx: RouteContext; out: { status: number; body: any } } {
  const out: { status: number; body: any } = { status: 200, body: null }
  const res: any = {
    writeHead(status: number) { out.status = status; return res },
    setHeader() { return res },
    end(chunk?: string) { if (chunk) out.body = JSON.parse(chunk) },
  }
  const req: any = Readable.from([Buffer.from(JSON.stringify(payload))])
  const url = new URL(`http://localhost:3420${path}`)
  return { ctx: { req, res, path: url.pathname, method, url } as RouteContext, out }
}

async function move(id: string, payload: Record<string, unknown>) {
  const { ctx, out } = call('POST', `/api/kanban/${id}/move`, payload)
  expect(await tryHandleKanban(ctx)).toBe(true)
  return out
}

async function put(id: string, payload: Record<string, unknown>) {
  const { ctx, out } = call('PUT', `/api/kanban/${id}`, payload)
  expect(await tryHandleKanban(ctx)).toBe(true)
  return out
}

describe('hasVarLine', () => {
  it('accepts a line starting with VÁR: and some text', () => {
    expect(hasVarLine('VÁR: Patrik - mehet a K6a-ra')).toBe(true)
    expect(hasVarLine('Összefoglaló...\n  VÁR: Viktor - review')).toBe(true)
    expect(hasVarLine('- VÁR: Lex - jogi OK')).toBe(true)
    expect(hasVarLine('Vár: Patrik - döntés')).toBe(true)
    expect(hasVarLine('VAR: Patrik - dontes')).toBe(true)
    // decomposed accent (A + U+0301) behaves like the precomposed letter
    expect(hasVarLine('VÁR: Patrik - OK')).toBe(true)
  })

  it('accepts a capital VÁR: after a sentence end on the same line', () => {
    expect(hasVarLine('#486 átadva Pulzusnak (4997). VÁR: Pulzus - merge + élesítés.')).toBe(true)
    expect(hasVarLine('Kész! VAR: Viktor - review')).toBe(true)
  })

  it('rejects a mention mid-line, an empty VÁR:, and nothing at all', () => {
    expect(hasVarLine('Patrikra vár: mehet?')).toBe(false)
    expect(hasVarLine('Kész. vár: Patrik - mehet')).toBe(false)
    expect(hasVarLine('Átadva VÁR: Pulzus - merge')).toBe(false)
    expect(hasVarLine('VÁR:')).toBe(false)
    expect(hasVarLine('VÁR:   ')).toBe(false)
    expect(hasVarLine('')).toBe(false)
    expect(hasVarLine(null)).toBe(false)
  })
})

describe('waiting gate on POST /api/kanban/:id/move', () => {
  beforeEach(() => { initDatabase(':memory:') })

  it('refuses a move into waiting without a VÁR line, and the card stays', async () => {
    createKanbanCard({ id: 'c1', title: 'Card', status: 'in_progress' })
    addKanbanComment('c1', 'dave', 'Elakadtam, kellene valaki.')
    const out = await move('c1', { status: 'waiting', actor: 'dave' })
    expect(out.status).toBe(400)
    expect(out.body.error).toBe(WAITING_GATE_ERROR)
    expect(out.body.error).toContain('VÁR:')
    expect(getKanbanCard('c1')!.status).toBe('in_progress')
  })

  it('accepts the VÁR line in the move comment and stores it on the card', async () => {
    createKanbanCard({ id: 'c2', title: 'Card', status: 'in_progress' })
    const out = await move('c2', { status: 'waiting', actor: 'dave', comment: 'VÁR: Patrik - mehet a K6a-ra' })
    expect(out.status).toBe(200)
    expect(getKanbanCard('c2')!.status).toBe('waiting')
    const comments = getKanbanComments('c2')
    expect(comments).toHaveLength(1)
    expect(comments[0]).toMatchObject({ author: 'dave', content: 'VÁR: Patrik - mehet a K6a-ra' })
  })

  it('accepts a VÁR line in the latest card comment (comment-then-move order)', async () => {
    createKanbanCard({ id: 'c3', title: 'Card', status: 'in_progress' })
    addKanbanComment('c3', 'dave', 'Klodel: kell a döntésed.\nVÁR: Klodel - melyik változat')
    const out = await move('c3', { status: 'waiting', actor: 'dave' })
    expect(out.status).toBe(200)
    expect(getKanbanCard('c3')!.status).toBe('waiting')
  })

  it('only the LATEST comment counts', async () => {
    createKanbanCard({ id: 'c4', title: 'Card', status: 'in_progress' })
    addKanbanComment('c4', 'dave', 'VÁR: Patrik - régi kérdés')
    addKanbanComment('c4', 'dave', 'Megoldva, megyek tovább.')
    expect((await move('c4', { status: 'waiting', actor: 'dave' })).status).toBe(400)
  })

  it('a machine comment after the VÁR line does not void it', async () => {
    createKanbanCard({ id: 'c4b', title: 'Card', status: 'in_progress' })
    addKanbanComment('c4b', 'dave', 'VÁR: Klodel - review')
    addKanbanComment('c4b', 'system', 'A kártya in_progress lett, de ...')
    addKanbanComment('c4b', 'pr-autodone', 'gépi jegyzet', { automated: true })
    expect((await move('c4b', { status: 'waiting', actor: 'dave' })).status).toBe(200)
  })

  it('a reorder inside the waiting column is not checked', async () => {
    createKanbanCard({ id: 'c5', title: 'Card', status: 'waiting' })
    const out = await move('c5', { status: 'waiting', sort_order: 3 })
    expect(out.status).toBe(200)
  })

  it('moves to other columns are unaffected', async () => {
    createKanbanCard({ id: 'c6', title: 'Card', status: 'planned' })
    expect((await move('c6', { status: 'in_progress', actor: 'dave' })).status).toBe(200)
    expect((await move('c6', { status: 'done', actor: 'dave' })).status).toBe(200)
  })

  it('a missing card still answers 404, not the waiting 400', async () => {
    expect((await move('nope', { status: 'waiting' })).status).toBe(404)
  })

  it('refuses a non-string or blank comment before any write', async () => {
    createKanbanCard({ id: 'c7', title: 'Card', status: 'planned' })
    expect((await move('c7', { status: 'in_progress', comment: 42 })).status).toBe(400)
    expect((await move('c7', { status: 'in_progress', comment: '  ' })).status).toBe(400)
    expect(getKanbanCard('c7')!.status).toBe('planned')
  })
})

describe('waiting gate on PUT /api/kanban/:id', () => {
  beforeEach(() => { initDatabase(':memory:') })

  it('refuses a status change into waiting without a VÁR line', async () => {
    createKanbanCard({ id: 'p1', title: 'Card', status: 'in_progress' })
    const out = await put('p1', { status: 'waiting', actor: 'dave' })
    expect(out.status).toBe(400)
    expect(getKanbanCard('p1')!.status).toBe('in_progress')
  })

  it('accepts it with a VÁR comment in the body', async () => {
    createKanbanCard({ id: 'p2', title: 'Card', status: 'in_progress' })
    const out = await put('p2', { status: 'waiting', actor: 'dave', comment: 'VÁR: Viktor - security review' })
    expect(out.status).toBe(200)
    expect(getKanbanCard('p2')!.status).toBe('waiting')
    expect(getKanbanComments('p2')[0].content).toBe('VÁR: Viktor - security review')
  })

  it('a whole-card PUT on an already-waiting card (assignee edit) is not checked', async () => {
    createKanbanCard({ id: 'p3', title: 'Card', status: 'waiting', assignee: 'dave' })
    const card = getKanbanCard('p3')!
    const out = await put('p3', { ...card, assignee: 'klodel' })
    expect(out.status).toBe(200)
    expect(getKanbanCard('p3')!.assignee).toBe('klodel')
  })
})
