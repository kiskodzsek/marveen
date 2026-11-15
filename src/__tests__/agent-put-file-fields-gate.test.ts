// Card a8944247: PUT /api/agents/:name wrote claudeMd / soulMd / mcpJson for any sub-agent with the shared dashboard
// token, so one sub-agent could rewrite another's instructions or add an MCP server to it. A token caller that names a
// sub-agent in X-Agent-Id is now refused for these fields (the caller rule of sealedWriteRefusal, card ec665017);
// the dashboard UI (a session), a token caller without the header and the main agent are not.
//
// The route cases run the real handler against a temporary agents/<name> directory: on the code before this card
// the refused requests answered 200 and wrote the file; now they answer 403 and the directory stays as it was.
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { Readable } from 'node:stream'
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { MAIN_AGENT_ID, PROJECT_ROOT } from '../config.js'
import { agentFileWriteRefusal, AGENT_FILE_FIELDS } from '../web/agent-put-fields.js'
import { tryHandleAgents } from '../web/routes/agents.js'
import type { RouteContext } from '../web/routes/types.js'

const NAME = `zz-a8944247-${process.pid}`
const DIR = join(PROJECT_ROOT, 'agents', NAME)
const WEB_DIR = join(PROJECT_ROOT, 'web')
const SUB = { kind: 'token', agent: 'dave' } as RouteContext['auth']

async function put(body: Record<string, unknown>, auth: RouteContext['auth']) {
  const out: { status: number; body: Record<string, unknown> | null } = { status: 0, body: null }
  const res = {
    writeHead(status: number) { out.status = status; return res },
    setHeader() { return res },
    end(chunk?: string) { if (chunk) out.body = JSON.parse(chunk) as Record<string, unknown> },
  }
  const path = `/api/agents/${NAME}`
  const req = Readable.from([Buffer.from(JSON.stringify(body))]) as unknown as RouteContext['req']
  const ctx = { req, res, path, method: 'PUT', url: new URL(`http://localhost:3420${path}`), auth } as unknown as RouteContext
  expect(await tryHandleAgents(ctx, WEB_DIR)).toBe(true)
  return out
}

beforeAll(() => { mkdirSync(DIR, { recursive: true }) })
afterAll(() => { rmSync(DIR, { recursive: true, force: true }) })

describe('agentFileWriteRefusal (card a8944247)', () => {
  it('refuses a token caller naming a sub-agent, for each of the three fields, and names the fields', () => {
    for (const f of AGENT_FILE_FIELDS) {
      const r = agentFileWriteRefusal({ kind: 'token', agent: 'dave' }, 'klodel', { [f]: 'x' })
      expect(r, f).toContain(f)
      expect(r, f).toContain('not by dave')
    }
    const all = agentFileWriteRefusal({ kind: 'token', agent: 'mira' }, 'klodel', { claudeMd: '', soulMd: '', mcpJson: '{}' })
    expect(all).toContain('claudeMd, soulMd, mcpJson')
  })

  it('an empty string is a write too (it empties the file)', () => {
    expect(agentFileWriteRefusal({ kind: 'token', agent: 'dave' }, 'klodel', { soulMd: '' })).not.toBeNull()
  })

  it('lets the main agent, a token caller without the header, a session, a device and no caller through', () => {
    const body = { claudeMd: 'x' }
    expect(agentFileWriteRefusal({ kind: 'token', agent: 'klodel' }, 'klodel', body)).toBeNull()
    expect(agentFileWriteRefusal({ kind: 'token' }, 'klodel', body)).toBeNull()
    expect(agentFileWriteRefusal({ kind: 'token', agent: '' }, 'klodel', body)).toBeNull()
    expect(agentFileWriteRefusal({ kind: 'session', user: 'patrik' } as { kind: string }, 'klodel', body)).toBeNull()
    expect(agentFileWriteRefusal({ kind: 'device' }, 'klodel', body)).toBeNull()
    expect(agentFileWriteRefusal(undefined, 'klodel', body)).toBeNull()
  })

  it('does not touch a body without the three fields (the other fields keep their own rules)', () => {
    expect(agentFileWriteRefusal({ kind: 'token', agent: 'dave' }, 'klodel', { model: 'claude-sonnet', memoryIsolation: true })).toBeNull()
    expect(agentFileWriteRefusal({ kind: 'token', agent: 'dave' }, 'klodel', {})).toBeNull()
  })

  it('caps the caller name in the message', () => {
    expect(agentFileWriteRefusal({ kind: 'token', agent: 'x'.repeat(500) }, 'klodel', { claudeMd: '' })!.length).toBeLessThan(250)
  })
})

describe('PUT /api/agents/:name refuses a sub-agent for CLAUDE.md, SOUL.md, .mcp.json (card a8944247)', () => {
  it('403 for each field from a sub-agent token caller, and no file is written', async () => {
    for (const f of AGENT_FILE_FIELDS) {
      const out = await put({ [f]: f === 'mcpJson' ? '{"mcpServers":{"x":{"command":"/bin/true"}}}' : '# injected' }, SUB)
      expect(out.status, f).toBe(403)
      expect(String(out.body?.error), f).toContain('card a8944247')
    }
    expect(readdirSync(DIR)).toEqual([])
  })

  it('refuses before the first write of the handler: memoryIsolation in the same body is not written either', async () => {
    const out = await put({ memoryIsolation: true, mcpJson: '{}' }, SUB)
    expect(out.status).toBe(403)
    expect(readdirSync(DIR)).toEqual([])
  })

  it('also refuses a sub-agent writing its own files (whichever agent it targets)', async () => {
    const out = await put({ soulMd: 'x' }, { kind: 'token', agent: NAME } as RouteContext['auth'])
    expect(out.status).toBe(403)
    expect(readdirSync(DIR)).toEqual([])
  })

  it('the dashboard UI (a session) still writes them: the route path the refusal sits on is reachable', async () => {
    const out = await put({ claudeMd: '# from the UI', soulMd: 'soul', mcpJson: '{}' }, { kind: 'session', user: 'patrik' })
    expect(out.status).toBe(200)
    expect(readFileSync(join(DIR, 'CLAUDE.md'), 'utf-8')).toBe('# from the UI')
    expect(readFileSync(join(DIR, 'SOUL.md'), 'utf-8')).toBe('soul')
    expect(existsSync(join(DIR, '.mcp.json'))).toBe(true)
  })

  it('a token caller without X-Agent-Id (the UI in token mode, a script) is not refused', async () => {
    const out = await put({ soulMd: 'token soul' }, { kind: 'token' })
    expect(out.status).toBe(200)
    expect(readFileSync(join(DIR, 'SOUL.md'), 'utf-8')).toBe('token soul')
  })
})

describe('handler order (card a8944247)', () => {
  it('the refusal is checked after the field check and before the first writer of the PUT handler', () => {
    const s = readFileSync(join(PROJECT_ROOT, 'src', 'web', 'routes', 'agents.ts'), 'utf-8')
    const put = s.slice(s.indexOf("if (agentMatch && method === 'PUT') {"))
    const end = put.indexOf("json(res, { ok: true })")
    const handler = put.slice(0, end)
    const gate = handler.indexOf('const fileRefusal = agentFileWriteRefusal(ctx.auth, MAIN_AGENT_ID, data)')
    expect(gate).toBeGreaterThan(handler.indexOf('checkAgentPutFields(name, data)'))
    expect(handler.slice(gate)).toMatch(/^[^\n]*\n\s*if \(fileRefusal\) \{ json\(res, \{ error: fileRefusal \}, 403\); return true \}/)
    for (const w of ['writeAgentMemoryIsolation(', 'atomicWriteFileSync(', 'writeAgentModel(', 'writeAgentModelProfile(',
      'writeAgentCustomProvider(', 'writeAgentAuthMode(', 'setSecret(', 'deleteSecret(', 'writeAgentClaudePlan(']) {
      const at = handler.indexOf(w)
      expect(at, w).toBeGreaterThan(gate)
    }
  })
})
