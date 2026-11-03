// Office view API (see ../iroda.ts for what is reduced and why).
//
//   GET /api/iroda/snapshot       one reduced snapshot for the whole view (polled every few seconds)
//   GET /api/iroda/thumb/<agent>  the agent's current monitor thumbnail (jpeg), from the allowlist only
//
// Both sit behind the dashboard's /api/* Bearer gate like every other route;
// nothing here is reachable without the token.

import { execFile } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, readdirSync, unlinkSync } from 'node:fs'
import { basename, extname, join } from 'node:path'
import { promisify } from 'node:util'
import { PROJECT_ROOT, STORE_DIR } from '../../config.js'
import { getDb, listKanbanCards } from '../../db.js'
import { json, jsonMaybeGzip, serveFile } from '../http-helpers.js'
import {
  activityLine, findLatestMedia, loadOrg, loadThumbDirs, mediaCaption, messageSubject, scrubText, withUnplacedAgents,
  type MediaHit,
} from '../iroda.js'
import { collectAgentStatusRows } from './agents.js'
import type { RouteContext } from './types.js'

const run = promisify(execFile)

/** Messages shown in the log / animated, newest first. */
const MESSAGE_WINDOW_SEC = 30 * 60
/** A media file this old or newer counts as "what it is doing now". */
const MEDIA_MAX_AGE_MS = 6 * 3600 * 1000
/** Media scan result cache: the walk is bounded, but the view polls every few seconds. */
const MEDIA_CACHE_MS = 30 * 1000
const THUMB_DIR = join(STORE_DIR, 'iroda-thumbs')
const AGENT_ID = /^[a-z0-9][a-z0-9-]{0,40}$/

const mediaCache = new Map<string, { at: number; hit: MediaHit | null }>()

function latestMedia(agent: string, dirs: string[], now: number): MediaHit | null {
  const c = mediaCache.get(agent)
  if (c && now - c.at < MEDIA_CACHE_MS) return c.hit
  const hit = findLatestMedia(PROJECT_ROOT, dirs, now, MEDIA_MAX_AGE_MS)
  mediaCache.set(agent, { at: now, hit })
  return hit
}

interface ProjectStep { nev: string; kesz: boolean }
function readProjects(): { projects: Array<{ id: string; cim: string; hatarido: string; lepesek: ProjectStep[] }>; patrikraVar: string[] } {
  try {
    const raw = JSON.parse(readFileSync(join(STORE_DIR, 'projektek.json'), 'utf-8')) as Record<string, unknown>
    const list = Array.isArray(raw.projektek) ? raw.projektek as Array<Record<string, unknown>> : []
    const projects = list.map((p) => ({
      id: String(p.id ?? ''),
      cim: scrubText(String(p.cim ?? '')),
      hatarido: String(p.hatarido ?? ''),
      lepesek: (Array.isArray(p.lepesek) ? p.lepesek as Array<Record<string, unknown>> : [])
        .map((s) => ({ nev: scrubText(String(s.nev ?? '')), kesz: s.kesz === true })),
    }))
    const pv = Array.isArray(raw.patrikra_var) ? raw.patrikra_var : []
    const patrikraVar = pv.map((x) => scrubText(typeof x === 'string' ? x : String((x as Record<string, unknown>)?.mit ?? ''))).filter(Boolean)
    return { projects, patrikraVar }
  } catch {
    return { projects: [], patrikraVar: [] }
  }
}

const PRIO: Record<string, number> = { urgent: 0, high: 1, normal: 2, low: 3 }
const STATUS_ORDER: Record<string, number> = { in_progress: 0, testing: 1, waiting: 2, planned: 3 }

export function buildSnapshot(nowMs = Date.now()) {
  const nowSec = Math.floor(nowMs / 1000)
  const db = getDb()
  const org = loadOrg(STORE_DIR)
  const statusRows = collectAgentStatusRows()
  const fullOrg = withUnplacedAgents(org, statusRows.map((r) => r.agent))

  const lastTool = new Map<string, { tool: string; at: number; line: string; file: string | null }>()
  const toolRows = db.prepare(`SELECT t.agent_id, t.tool_name, t.input_summary, t.created_at FROM tool_call_log t
      JOIN (SELECT agent_id, MAX(id) AS mid FROM tool_call_log WHERE created_at >= ? AND agent_id IS NOT NULL GROUP BY agent_id) x
      ON t.id = x.mid`).all(nowSec - 6 * 3600) as Array<{ agent_id: string; tool_name: string; input_summary: string | null; created_at: number }>
  for (const r of toolRows) {
    const isFileTool = ['Write', 'Edit', 'MultiEdit'].includes(r.tool_name)
    lastTool.set(r.agent_id, {
      tool: r.tool_name, at: r.created_at, line: activityLine(r.tool_name, r.input_summary),
      file: isFileTool && r.input_summary ? scrubText(basename(r.input_summary)) : null,
    })
  }

  // Queue = messages the router has not delivered yet ('pending'). A 'delivered' row already reached the
  // agent's session; many are never closed, so counting them reads as a weeks-old backlog.
  const queue = new Map<string, { n: number; oldestSec: number }>()
  for (const q of db.prepare(`SELECT to_agent, COUNT(*) AS n, MIN(created_at) AS oldest FROM agent_messages
      WHERE status = 'pending' AND from_agent <> 'system' GROUP BY to_agent`).all() as Array<{ to_agent: string; n: number; oldest: number }>) {
    queue.set(q.to_agent, { n: q.n, oldestSec: Math.max(0, nowSec - q.oldest) })
  }

  const cardsBy = new Map<string, { counts: Record<string, number>; top: Array<{ id: string; status: string; priority: string; title: string }> }>()
  const openCards = listKanbanCards().filter((c) => c.status !== 'done')
  for (const c of openCards) {
    const a = (c.assignee ?? '').toLowerCase()
    if (!a) continue
    const e = cardsBy.get(a) ?? { counts: { in_progress: 0, waiting: 0, planned: 0 }, top: [] }
    e.counts[c.status] = (e.counts[c.status] ?? 0) + 1
    e.top.push({ id: c.id.slice(0, 8), status: c.status, priority: c.priority, title: c.title })
    cardsBy.set(a, e)
  }
  for (const e of cardsBy.values()) {
    e.top.sort((x, y) => (STATUS_ORDER[x.status] ?? 9) - (STATUS_ORDER[y.status] ?? 9) || (PRIO[x.priority] ?? 9) - (PRIO[y.priority] ?? 9))
    e.top = e.top.slice(0, 4).map((c) => ({ ...c, title: messageSubject(c.title, 96) }))
  }

  const thumbDirs = loadThumbDirs(STORE_DIR)
  const agents = statusRows.map((r) => {
    const tool = lastTool.get(r.agent)
    const dirs = thumbDirs[r.agent]
    const media = dirs ? latestMedia(r.agent, dirs, nowMs) : null
    const cards = cardsBy.get(r.agent)
    return {
      id: r.agent,
      state: r.state,
      running: r.running,
      since: r.sinceSec,
      work: r.work.kind === 'none' ? null : messageSubject(r.work.text, 96),
      activity: tool ? { line: tool.line, ageSec: Math.max(0, nowSec - tool.at), file: tool.file } : null,
      media: media ? { kind: media.kind, caption: mediaCaption(media), ageSec: Math.round((nowMs - media.mtimeMs) / 1000), v: Math.round(media.mtimeMs) } : null,
      queue: queue.get(r.agent) ?? { n: 0, oldestSec: 0 },
      cards: cards ?? { counts: { in_progress: 0, waiting: 0, planned: 0 }, top: [] },
    }
  })

  const messages = (db.prepare(`SELECT id, from_agent, to_agent, content, created_at FROM agent_messages
      WHERE created_at >= ? AND from_agent <> 'system' AND to_agent <> 'system' AND from_agent <> to_agent
      ORDER BY id DESC LIMIT 60`).all(nowSec - MESSAGE_WINDOW_SEC) as Array<{ id: number; from_agent: string; to_agent: string; content: string; created_at: number }>)
    .map((m) => ({ id: m.id, from: m.from_agent, to: m.to_agent, at: m.created_at, subject: messageSubject(m.content) }))

  const { projects, patrikraVar } = readProjects()
  const waiting = openCards
    .filter((c) => (c.assignee ?? '').toLowerCase() === 'patrik')
    .sort((x, y) => (PRIO[x.priority] ?? 9) - (PRIO[y.priority] ?? 9))
    .slice(0, 8)
    .map((c) => ({ id: c.id.slice(0, 8), priority: c.priority, status: c.status, title: messageSubject(c.title, 110) }))

  return { at: nowSec, org: fullOrg, agents, messages, projects, waiting, patrikraVar }
}

async function makeThumb(src: string, kind: 'image' | 'video', out: string): Promise<boolean> {
  try {
    if (kind === 'video') {
      const frame = out.replace(/\.jpg$/, '.frame.jpg')
      await run('ffmpeg', ['-y', '-loglevel', 'error', '-ss', '1', '-i', src, '-frames:v', '1', '-vf', 'scale=360:-2', frame], { timeout: 15000 })
      await run('sips', ['-s', 'format', 'jpeg', '-s', 'formatOptions', '78', frame, '--out', out], { timeout: 15000 })
      try { unlinkSync(frame) } catch { /* best effort */ }
    } else {
      await run('sips', ['-s', 'format', 'jpeg', '-s', 'formatOptions', '78', '-Z', '360', src, '--out', out], { timeout: 15000 })
    }
    return existsSync(out)
  } catch {
    return false
  }
}

export async function tryHandleIroda(ctx: RouteContext): Promise<boolean> {
  const { req, res, path, method } = ctx
  if (path === '/api/iroda/snapshot' && method === 'GET') {
    jsonMaybeGzip(req, res, buildSnapshot())
    return true
  }
  if (path.startsWith('/api/iroda/thumb/') && method === 'GET') {
    const agent = path.slice('/api/iroda/thumb/'.length)
    if (!AGENT_ID.test(agent)) { json(res, { error: 'bad agent' }, 400); return true }
    const dirs = loadThumbDirs(STORE_DIR)[agent]
    const hit = dirs ? latestMedia(agent, dirs, Date.now()) : null
    if (!hit) { res.writeHead(404); res.end(); return true }
    mkdirSync(THUMB_DIR, { recursive: true })
    const out = join(THUMB_DIR, `${agent}-${Math.round(hit.mtimeMs)}.jpg`)
    if (!existsSync(out)) {
      // keep one thumbnail per agent
      for (const f of readdirSync(THUMB_DIR)) if (f.startsWith(agent + '-') && extname(f) === '.jpg') { try { unlinkSync(join(THUMB_DIR, f)) } catch { /* best effort */ } }
      if (!(await makeThumb(hit.path, hit.kind, out))) { res.writeHead(404); res.end(); return true }
    }
    serveFile(req, res, out, { cacheSeconds: 300 })
    return true
  }
  return false
}
