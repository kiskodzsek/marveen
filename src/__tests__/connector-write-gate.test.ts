// Card 4cd20267 (Viktor 43450 LELET 1): the connectors routes that change MCP configuration answered any token caller.
// A token caller that names a sub-agent in X-Agent-Id is now refused for every writing route under /api/connectors
// and below /api/mcp-catalog/ (install, uninstall: Viktor 43488 LELET 1) (the caller rule of sealedWriteRefusal / agentFileWriteRefusal); the dashboard UI (a session), a token caller without
// the header and the main agent are not, and the reads are not.
//
// The route cases run the real handler against temporary agents/<name> directories under this checkout: on the code
// before this card the refused assign / DELETE answered 200 and changed the .mcp.json files; now they answer 403 and
// the files stay as they were. The other writing routes are probed only with bodies the old code rejects before any
// effect (an empty name, an empty URL, a relative path, an unknown repo), so this file never runs `claude mcp add`,
// git or npm, on either side.
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { Readable } from 'node:stream'
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { MAIN_AGENT_ID, PROJECT_ROOT } from '../config.js'
import { connectorWriteRefusal, isConnectorWrite } from '../web/connector-write-gate.js'
import { tryHandleConnectors } from '../web/routes/connectors.js'
import type { RouteContext } from '../web/routes/types.js'

const TAG = `zz-4cd20267-${process.pid}`
const CONN = `${TAG}-conn`
const SRC = `${TAG}-src` // holds the connector (the config assign copies)
const TGT = `${TAG}-tgt` // an assign target
const HAS = `${TAG}-has` // already has the connector (allAgents removal, DELETE)
const dirOf = (a: string) => join(PROJECT_ROOT, 'agents', a)
const mcpOf = (a: string) => join(dirOf(a), '.mcp.json')
const CONFIG = { command: 'true', args: [], env: { ZZ_PROBE: 'not-a-secret' } }
const SUB = { kind: 'token', agent: 'dave' } as RouteContext['auth']
const SESSION = { kind: 'session', user: 'patrik' } as RouteContext['auth']

async function call(method: string, path: string, body: unknown, auth: RouteContext['auth']) {
  const out: { status: number; body: Record<string, unknown> | null } = { status: 0, body: null }
  const res = {
    writeHead(status: number) { out.status = status; return res },
    setHeader() { return res },
    end(chunk?: string) { if (chunk) out.body = JSON.parse(chunk) as Record<string, unknown> },
  }
  const raw = body === undefined ? [] : [Buffer.from(typeof body === 'string' ? body : JSON.stringify(body))]
  const req = Readable.from(raw) as unknown as RouteContext['req']
  const ctx = { req, res, path, method, url: new URL(`http://localhost:3420${path}`), auth } as unknown as RouteContext
  const handled = await tryHandleConnectors(ctx)
  return { handled, ...out }
}

function reset() {
  for (const a of [SRC, TGT, HAS]) mkdirSync(dirOf(a), { recursive: true })
  writeFileSync(mcpOf(SRC), JSON.stringify({ mcpServers: { [CONN]: CONFIG } }, null, 2))
  writeFileSync(mcpOf(TGT), JSON.stringify({ mcpServers: {} }, null, 2))
  writeFileSync(mcpOf(HAS), JSON.stringify({ mcpServers: { [CONN]: CONFIG } }, null, 2))
}
const snapshot = () => [SRC, TGT, HAS].map(a => readFileSync(mcpOf(a), 'utf-8'))
const servers = (a: string) => (JSON.parse(readFileSync(mcpOf(a), 'utf-8')) as { mcpServers?: Record<string, unknown> }).mcpServers ?? {}

beforeAll(reset)
afterAll(() => { for (const a of [SRC, TGT, HAS]) rmSync(dirOf(a), { recursive: true, force: true }) })

describe('connectorWriteRefusal (card 4cd20267)', () => {
  it('refuses a token caller naming a sub-agent on every writing connectors route, and names the route', () => {
    const writes: Array<[string, string]> = [
      ['POST', '/api/connectors'],
      ['DELETE', `/api/connectors/${CONN}`],
      ['POST', `/api/connectors/${CONN}/assign`],
      ['POST', '/api/connectors/external-paths'],
      ['DELETE', '/api/connectors/external-paths'],
      ['POST', '/api/connectors/github-repos'],
      ['DELETE', '/api/connectors/github-repos/x'],
      ['PATCH', '/api/connectors/github-repos/x'],
      ['PUT', '/api/connectors/anything-new'],
      ['POST', '/api/mcp-catalog/some-item/install'],
      ['DELETE', '/api/mcp-catalog/some-item/uninstall'],
      ['POST', '/api/mcp-catalog/some-item/anything-new'],
    ]
    for (const [m, p] of writes) {
      const r = connectorWriteRefusal({ kind: 'token', agent: 'mira' }, 'klodel', p, m)
      expect(r, `${m} ${p}`).toContain(`${m} ${p}`)
      expect(r, `${m} ${p}`).toContain('not by mira')
    }
  })

  it('does not touch the reads, the cache refresh, the vault routes or another router with a similar prefix', () => {
    const sub = { kind: 'token', agent: 'dave' }
    for (const [m, p] of [
      ['GET', '/api/connectors'], ['GET', `/api/connectors/${CONN}`], ['HEAD', '/api/connectors'],
      ['GET', '/api/connectors/status'], ['POST', '/api/connectors/refresh'], ['GET', '/api/connectors/external-paths'],
      ['POST', '/api/vault'], ['POST', '/api/vault/bindings'], ['POST', '/api/connectors-hu/install'],
      ['POST', '/api/connectorsx'], ['POST', '/api/mcp-catalog'], ['GET', '/api/mcp-catalog'],
      ['GET', '/api/mcp-catalog/some-item/install'], ['HEAD', '/api/mcp-catalog/some-item/uninstall'],
      ['POST', '/api/mcp-catalogx/some-item/install'],
    ] as Array<[string, string]>) {
      expect(isConnectorWrite(p, m), `${m} ${p}`).toBe(false)
      expect(connectorWriteRefusal(sub, 'klodel', p, m), `${m} ${p}`).toBeNull()
    }
  })

  it('lets the main agent, a token caller without the header, a session, a device and no caller through', () => {
    const p = `/api/connectors/${CONN}/assign`
    expect(connectorWriteRefusal({ kind: 'token', agent: 'klodel' }, 'klodel', p, 'POST')).toBeNull()
    expect(connectorWriteRefusal({ kind: 'token' }, 'klodel', p, 'POST')).toBeNull()
    expect(connectorWriteRefusal({ kind: 'token', agent: '' }, 'klodel', p, 'POST')).toBeNull()
    expect(connectorWriteRefusal({ kind: 'session' }, 'klodel', p, 'POST')).toBeNull()
    expect(connectorWriteRefusal({ kind: 'device' }, 'klodel', p, 'POST')).toBeNull()
    expect(connectorWriteRefusal(null, 'klodel', p, 'POST')).toBeNull()
    expect(connectorWriteRefusal(undefined, 'klodel', p, 'POST')).toBeNull()
  })

  it('caps the caller name and the path in the message', () => {
    const r = connectorWriteRefusal({ kind: 'token', agent: 'a'.repeat(500) }, 'klodel', `/api/connectors/${'p'.repeat(500)}`, 'DELETE')
    expect(r).not.toBeNull()
    expect((r as string).length).toBeLessThan(400)
  })
})

describe('the real connectors handler (card 4cd20267)', () => {
  it('assign from a sub-agent: 403, and no .mcp.json changes (the old code wrote the target)', async () => {
    reset()
    const before = snapshot()
    const r = await call('POST', `/api/connectors/${CONN}/assign`, { agents: [TGT] }, SUB)
    expect(r.status).toBe(403)
    expect(String(r.body?.error)).toContain('card 4cd20267')
    expect(snapshot()).toEqual(before)
  })

  it('assign with allAgents from a sub-agent: 403, and the connector is not removed from the others', async () => {
    reset()
    const before = snapshot()
    const r = await call('POST', `/api/connectors/${CONN}/assign`, { agents: [], allAgents: [HAS] }, SUB)
    expect(r.status).toBe(403)
    expect(snapshot()).toEqual(before)
    expect(servers(HAS)[CONN]).toBeDefined()
  })

  it('DELETE from a sub-agent: 403, and the connector stays in every config', async () => {
    reset()
    const before = snapshot()
    const r = await call('DELETE', `/api/connectors/${CONN}`, undefined, SUB)
    expect(r.status).toBe(403)
    expect(snapshot()).toEqual(before)
  })

  it('the other writing routes from a sub-agent: 403 (bodies the old code rejects before any effect)', async () => {
    for (const [m, p, body] of [
      ['POST', '/api/connectors', { name: '' }],
      ['POST', '/api/connectors/external-paths', { path: 'relative/not-absolute' }],
      ['POST', '/api/connectors/github-repos', { url: '' }],
      ['DELETE', `/api/connectors/github-repos/${TAG}-no-such-repo`, undefined],
      ['PATCH', `/api/connectors/github-repos/${TAG}-no-such-repo`, undefined],
    ] as Array<[string, string, unknown]>) {
      const r = await call(m, p, body, SUB)
      expect(r.status, `${m} ${p}`).toBe(403)
    }
  })

  it('the catalog install / uninstall from a sub-agent: 403 before the catalog lookup (Viktor 43488 LELET 1)', async () => {
    // an id that is not in the catalog: the old code reached the handler and answered 404, with no effect
    const id = `${TAG}-no-such-item`
    for (const [m, p] of [['POST', `/api/mcp-catalog/${id}/install`], ['DELETE', `/api/mcp-catalog/${id}/uninstall`]]) {
      const r = await call(m, p, m === 'POST' ? { env: {} } : undefined, SUB)
      expect(r.status, `${m} ${p}`).toBe(403)
      expect(String(r.body?.error), `${m} ${p}`).toContain('card 4cd20267')
    }
  })

  it('the catalog install / uninstall from the dashboard UI (a session) still reach the handler: 404 for an unknown id', async () => {
    const id = `${TAG}-no-such-item`
    for (const [m, p] of [['POST', `/api/mcp-catalog/${id}/install`], ['DELETE', `/api/mcp-catalog/${id}/uninstall`]]) {
      const r = await call(m, p, m === 'POST' ? { env: {} } : undefined, SESSION)
      expect(r.handled, `${m} ${p}`).toBe(true)
      expect(r.status, `${m} ${p}`).toBe(404)
    }
  })

  it('the refusal comes before the body is read: a sub-agent with a broken body still gets 403', async () => {
    const r = await call('POST', `/api/connectors/${CONN}/assign`, '{not json', SUB)
    expect(r.status).toBe(403)
  })

  it('a sub-agent still reads: GET /api/connectors/<n> answers the connector (env masked)', async () => {
    reset()
    const r = await call('GET', `/api/connectors/${CONN}`, undefined, SUB)
    expect(r.status).toBe(200)
    expect(r.body?.name).toBe(CONN)
    expect(r.body?.env).toEqual({ ZZ_PROBE: '***' })
  })

  it('the dashboard UI (a session) still assigns, removes through allAgents and deletes', async () => {
    reset()
    let r = await call('POST', `/api/connectors/${CONN}/assign`, { agents: [TGT], allAgents: [TGT, HAS] }, SESSION)
    expect(r.status).toBe(200)
    expect(servers(TGT)[CONN]).toEqual(CONFIG)
    expect(servers(HAS)[CONN]).toBeUndefined()
    r = await call('DELETE', `/api/connectors/${CONN}`, undefined, SESSION)
    expect(r.status).toBe(200)
    expect(servers(SRC)[CONN]).toBeUndefined()
    expect(servers(TGT)[CONN]).toBeUndefined()
  })

  it('a token caller without the header and the main agent still assign', async () => {
    reset()
    let r = await call('POST', `/api/connectors/${CONN}/assign`, { agents: [TGT] }, { kind: 'token' } as RouteContext['auth'])
    expect(r.status).toBe(200)
    expect(servers(TGT)[CONN]).toEqual(CONFIG)
    reset()
    r = await call('POST', `/api/connectors/${CONN}/assign`, { agents: [TGT] }, { kind: 'token', agent: MAIN_AGENT_ID } as RouteContext['auth'])
    expect(r.status).toBe(200)
    expect(servers(TGT)[CONN]).toEqual(CONFIG)
  })

  it('order guard: the gate is the first statement after the destructuring, before any readBody or write', () => {
    const src = readFileSync(join(PROJECT_ROOT, 'src/web/routes/connectors.ts'), 'utf-8')
    const fn = src.indexOf('export async function tryHandleConnectors(')
    const gate = src.indexOf('connectorWriteRefusal(ctx.auth, MAIN_AGENT_ID, path, method)', fn)
    expect(fn).toBeGreaterThan(-1)
    expect(gate).toBeGreaterThan(fn)
    for (const first of ['readBody(', 'atomicWriteFileSync(', 'execSync(', 'installGitHubRepo(', 'if (path ===']) {
      const at = src.indexOf(first, fn)
      expect(at, first).toBeGreaterThan(gate)
    }
  })
})
