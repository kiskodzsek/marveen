// Card 0069544d (Viktor 43450 LELET 2): the skills routes that write or remove a SKILL.md answered any token caller.
// A token caller that names a sub-agent in X-Agent-Id is now refused for every writing route under /api/skills and
// /api/agents/<n>/skills (the caller rule of sealedWriteRefusal / agentFileWriteRefusal / connectorWriteRefusal); the
// dashboard UI (a session), a token caller without the header and the main agent are not, and the reads are not.
//
// The route cases run the real handlers against a temporary agents/<name>/.claude/skills directory under this
// checkout: on the code before this card the refused DELETE and PUT answered 200 and changed the skill; now they answer
// 403 and the files stay as they were. The routes that create a skill (an LLM-generated SKILL.md, an unpacked zip) or
// reach the main agent's skills dir (the global ~/.claude/skills) are probed only with requests the old code rejects
// before any effect (an empty name, no uploaded file, a skill that does not exist), so this file never generates,
// unpacks or removes a real skill, on either side.
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { Readable } from 'node:stream'
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { MAIN_AGENT_ID, PROJECT_ROOT } from '../config.js'
import { isSkillWrite, skillWriteRefusal } from '../web/skill-write-gate.js'
import { tryHandleAgentsSkills } from '../web/routes/agents-skills.js'
import { tryHandleSkills } from '../web/routes/skills.js'
import type { RouteContext } from '../web/routes/types.js'

const TAG = `zz-0069544d-${process.pid}`
const SK = `${TAG}-skill`
const NONE = `${TAG}-no-such-skill`
const AGENT_DIR = join(PROJECT_ROOT, 'agents', TAG)
const SKILL_DIR = join(AGENT_DIR, '.claude', 'skills', SK)
const SKILL_MD = join(SKILL_DIR, 'SKILL.md')
const ORIGINAL = '---\nname: probe\ndescription: probe skill of card 0069544d\n---\n# probe\n'
const SUB = { kind: 'token', agent: 'dave' } as RouteContext['auth']
const SESSION = { kind: 'session', user: 'patrik' } as RouteContext['auth']

async function call(method: string, pathAndQuery: string, body: unknown, auth: RouteContext['auth'], only?: 'skills') {
  const out: { status: number; body: unknown } = { status: 0, body: null }
  const res = {
    writeHead(status: number) { out.status = status; return res },
    setHeader() { return res },
    end(chunk?: string) { if (chunk) out.body = JSON.parse(chunk) as unknown },
  }
  const url = new URL(`http://localhost:3420${pathAndQuery}`)
  const raw = body === undefined ? [] : [Buffer.from(typeof body === 'string' ? body : JSON.stringify(body))]
  const req = Object.assign(Readable.from(raw), { headers: { 'content-type': 'application/json' } }) as unknown as RouteContext['req']
  const ctx = { req, res, path: url.pathname, method, url, auth } as unknown as RouteContext
  // the order of src/web.ts: the agents-skills router first, then the skills router (only: the skills router alone)
  const handled = only === 'skills' ? await tryHandleSkills(ctx) : (await tryHandleAgentsSkills(ctx)) || (await tryHandleSkills(ctx))
  return { handled, ...out }
}

function reset() {
  rmSync(SKILL_DIR, { recursive: true, force: true })
  mkdirSync(SKILL_DIR, { recursive: true })
  writeFileSync(SKILL_MD, ORIGINAL)
}

beforeAll(reset)
afterAll(() => { rmSync(AGENT_DIR, { recursive: true, force: true }) })

describe('skillWriteRefusal (card 0069544d)', () => {
  it('refuses a token caller naming a sub-agent on every writing skills route, and names the route', () => {
    const writes: Array<[string, string]> = [
      ['POST', '/api/agents/mira/skills'], ['POST', '/api/agents/mira/skills/import'],
      ['DELETE', '/api/agents/mira/skills/x'], ['POST', `/api/agents/${MAIN_AGENT_ID}/skills/import`],
      ['DELETE', `/api/agents/${MAIN_AGENT_ID}/skills/x`],
      ['POST', '/api/skills'], ['POST', '/api/skills/import'], ['POST', '/api/skills/x/assign'], ['PUT', '/api/skills/x'],
      ['PATCH', '/api/skills/x'], ['DELETE', '/api/skills/x'],
    ]
    for (const [m, p] of writes) {
      const r = skillWriteRefusal({ kind: 'token', agent: 'mira' }, 'klodel', p, m)
      expect(r, `${m} ${p}`).toContain(`${m} ${p}`)
      expect(r, `${m} ${p}`).toContain('not by mira')
    }
  })

  it('does not touch the reads or routes outside the two prefixes', () => {
    const sub = { kind: 'token', agent: 'dave' }
    for (const [m, p] of [
      ['GET', '/api/skills'], ['GET', '/api/skills/local'], ['GET', '/api/skills/export'], ['GET', '/api/skills/x'],
      ['HEAD', '/api/skills'], ['GET', '/api/agents/mira/skills'],
      ['POST', '/api/skillsx'], ['POST', '/api/agents/mira/skillset'], ['PUT', '/api/agents/mira'],
      ['POST', '/api/agents/mira/skill'], ['POST', '/api/connectors'],
    ] as Array<[string, string]>) {
      expect(isSkillWrite(p, m), `${m} ${p}`).toBe(false)
      expect(skillWriteRefusal(sub, 'klodel', p, m), `${m} ${p}`).toBeNull()
    }
  })

  it('lets the main agent, a token caller without the header, a session, a device and no caller through', () => {
    const p = '/api/skills/x'
    expect(skillWriteRefusal({ kind: 'token', agent: 'klodel' }, 'klodel', p, 'PUT')).toBeNull()
    expect(skillWriteRefusal({ kind: 'token' }, 'klodel', p, 'PUT')).toBeNull()
    expect(skillWriteRefusal({ kind: 'token', agent: '' }, 'klodel', p, 'PUT')).toBeNull()
    expect(skillWriteRefusal({ kind: 'session' }, 'klodel', p, 'PUT')).toBeNull()
    expect(skillWriteRefusal({ kind: 'device' }, 'klodel', p, 'PUT')).toBeNull()
    expect(skillWriteRefusal(null, 'klodel', p, 'PUT')).toBeNull()
    expect(skillWriteRefusal(undefined, 'klodel', p, 'PUT')).toBeNull()
  })

  it('caps the caller name and the path in the message', () => {
    const r = skillWriteRefusal({ kind: 'token', agent: 'a'.repeat(500) }, 'klodel', `/api/skills/${'p'.repeat(500)}`, 'PUT')
    expect(r).not.toBeNull()
    expect((r as string).length).toBeLessThan(400)
  })
})

describe('the real skills handlers (card 0069544d)', () => {
  it('DELETE of an agent skill from a sub-agent: 403, and the skill stays (the old code removed it)', async () => {
    reset()
    const r = await call('DELETE', `/api/agents/${TAG}/skills/${SK}`, undefined, SUB)
    expect(r.status).toBe(403)
    expect(String((r.body as { error?: string })?.error)).toContain('card 0069544d')
    expect(readFileSync(SKILL_MD, 'utf-8')).toBe(ORIGINAL)
  })

  it('PUT of an agent skill (skills router, ?agent=) from a sub-agent: 403, and the SKILL.md is unchanged', async () => {
    reset()
    const r = await call('PUT', `/api/skills/${SK}?agent=${TAG}`, { content: 'replaced by a sub-agent' }, SUB)
    expect(r.status).toBe(403)
    expect(readFileSync(SKILL_MD, 'utf-8')).toBe(ORIGINAL)
  })

  it('the other writing routes from a sub-agent, the main agent\'s (global) dir included: 403', async () => {
    for (const [m, p, body] of [
      ['POST', `/api/agents/${TAG}/skills`, { name: '', description: '' }],
      ['POST', `/api/agents/${TAG}/skills/import`, '{}'],
      ['POST', `/api/agents/${MAIN_AGENT_ID}/skills/import`, '{}'],
      ['DELETE', `/api/agents/${MAIN_AGENT_ID}/skills/${NONE}`, undefined],
      ['POST', '/api/skills', { name: '', description: '' }],
      ['POST', '/api/skills/import', '{}'],
      ['POST', `/api/skills/${NONE}/assign`, { agents: [TAG] }],
      ['PUT', `/api/skills/${NONE}`, { content: 'x' }],
    ] as Array<[string, string, unknown]>) {
      const r = await call(m, p, body, SUB)
      expect(r.status, `${m} ${p}`).toBe(403)
    }
    expect(readFileSync(SKILL_MD, 'utf-8')).toBe(ORIGINAL)
  })

  it('the skills router refuses by itself too (it does not rely on the agents-skills router running first)', async () => {
    reset()
    const r = await call('PUT', `/api/skills/${SK}?agent=${TAG}`, { content: 'replaced by a sub-agent' }, SUB, 'skills')
    expect(r.status).toBe(403)
    expect(readFileSync(SKILL_MD, 'utf-8')).toBe(ORIGINAL)
  })

  it('the refusal comes before the body is read: a sub-agent with a broken body still gets 403', async () => {
    reset()
    const r = await call('PUT', `/api/skills/${SK}?agent=${TAG}`, '{not json', SUB)
    expect(r.status).toBe(403)
  })

  it('a sub-agent still reads: GET /api/agents/<n>/skills lists the skill', async () => {
    reset()
    const r = await call('GET', `/api/agents/${TAG}/skills`, undefined, SUB)
    expect(r.status).toBe(200)
    expect((r.body as Array<{ name: string }>).some(s => s.name === SK)).toBe(true)
  })

  it('the dashboard UI (a session) still edits and deletes an agent skill', async () => {
    reset()
    let r = await call('PUT', `/api/skills/${SK}?agent=${TAG}`, { content: 'edited in the dashboard' }, SESSION)
    expect(r.status).toBe(200)
    expect(readFileSync(SKILL_MD, 'utf-8')).toBe('edited in the dashboard')
    r = await call('DELETE', `/api/agents/${TAG}/skills/${SK}`, undefined, SESSION)
    expect(r.status).toBe(200)
    expect(existsSync(SKILL_DIR)).toBe(false)
  })

  it('a token caller without the header and the main agent still delete an agent skill', async () => {
    reset()
    let r = await call('DELETE', `/api/agents/${TAG}/skills/${SK}`, undefined, { kind: 'token' } as RouteContext['auth'])
    expect(r.status).toBe(200)
    expect(existsSync(SKILL_DIR)).toBe(false)
    reset()
    r = await call('DELETE', `/api/agents/${TAG}/skills/${SK}`, undefined, { kind: 'token', agent: MAIN_AGENT_ID } as RouteContext['auth'])
    expect(r.status).toBe(200)
    expect(existsSync(SKILL_DIR)).toBe(false)
  })

  it('order guard: in both routers the gate is the first statement after the destructuring', () => {
    for (const [file, fnName] of [
      ['src/web/routes/agents-skills.ts', 'export async function tryHandleAgentsSkills('],
      ['src/web/routes/skills.ts', 'export async function tryHandleSkills('],
    ]) {
      const src = readFileSync(join(PROJECT_ROOT, file), 'utf-8')
      const fn = src.indexOf(fnName)
      const gate = src.indexOf('skillWriteRefusal(ctx.auth, MAIN_AGENT_ID, path, method)', fn)
      expect(fn, file).toBeGreaterThan(-1)
      expect(gate, file).toBeGreaterThan(fn)
      for (const first of ['readBody(', 'atomicWriteFileSync(', 'rmSync(', 'mkdirSync(', 'execSync(', 'path.match(', 'if (path ===']) {
        const at = src.indexOf(first, fn)
        if (at !== -1) expect(at, `${file}: ${first}`).toBeGreaterThan(gate)
      }
    }
  })
})
