// Card 45dea12e slice 2 (security review 53307 point 5): the narrow key is issued at agent start and retired at stop.
// Contract under test:
//   - a local agent gets <agent dir>/.claude-config/agent-api-key, 0600, holding a key that resolves to that agent;
//     the earlier key is revoked by the issue; a missing config folder is made 0700;
//   - the main agent, a remote agent and a runAsUser agent get no key, and an earlier live key of theirs is revoked;
//   - a config folder that is a link or not a directory: no write anywhere,
//     no live key, the other agent's key file untouched;
//   - retire: every live key revoked, the file (or a link at its path) removed, the link's target untouched; through a
//     linked or non-directory config folder nothing is removed (review 53437 M1);
//   - start and stop wiring (agent-process.ts): the key is issued right before the session, a failed start retires
//     it, a remote start and stop revoke it in the database (review 53437 L1, L2);
//   - a failure never throws.
import { describe, it, expect, beforeAll, afterAll, beforeEach } from 'vitest'
import { existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { initDatabase, getDb } from '../db.js'
import { issueAgentKey, resolveAgentKey } from '../web/auth-agent-keys.js'
import { agentKeyPath, provisionAgentKey, retireAgentKey, revokeAgentKeyOnly } from '../web/agent-key-provision.js'

const ROOT = mkdtempSync(join(tmpdir(), 'agent-key-prov-'))
const LOCAL = { isMainAgent: false, isRemote: false, runAsUser: null }
let n = 0
const agentFolder = (withConfig = true): string => {
  const d = join(ROOT, `agents-${++n}`, 'kernel')
  mkdirSync(withConfig ? join(d, '.claude-config') : d, { recursive: true })
  return d
}
const live = (agent: string): number =>
  (getDb().prepare('SELECT COUNT(*) AS c FROM agent_keys WHERE agent_id = ? AND revoked_at IS NULL').get(agent) as { c: number }).c

beforeAll(() => {
  process.env.NODE_ENV = 'test'
  initDatabase(':memory:')
})
afterAll(() => rmSync(ROOT, { recursive: true, force: true }))
beforeEach(() => {
  getDb().prepare('DELETE FROM agent_keys').run()
})

describe('provisionAgentKey: a local agent', () => {
  it('writes its own key file, 0600, resolving to the agent', () => {
    const d = agentFolder()
    const r = provisionAgentKey('kernel', d, LOCAL)
    expect(r.state).toBe('issued')
    const f = agentKeyPath(d)
    expect(r).toMatchObject({ path: f })
    expect(lstatSync(f).mode & 0o777).toBe(0o600)
    expect(resolveAgentKey(readFileSync(f, 'utf8'))).toMatchObject({ agent: 'kernel' })
    expect(live('kernel')).toBe(1)
  })
  it('a second start revokes the first key', () => {
    const d = agentFolder()
    provisionAgentKey('kernel', d, LOCAL)
    const first = readFileSync(agentKeyPath(d), 'utf8')
    provisionAgentKey('kernel', d, LOCAL)
    const second = readFileSync(agentKeyPath(d), 'utf8')
    expect(second).not.toBe(first)
    expect(resolveAgentKey(first)).toBeNull()
    expect(resolveAgentKey(second)).toMatchObject({ agent: 'kernel' })
    expect(live('kernel')).toBe(1)
  })
  it('makes a missing config folder, 0700', () => {
    const d = agentFolder(false)
    expect(provisionAgentKey('kernel', d, LOCAL).state).toBe('issued')
    expect(lstatSync(join(d, '.claude-config')).mode & 0o777).toBe(0o700)
  })
})

describe('provisionAgentKey: no key for the main, a remote or a runAsUser agent', () => {
  for (const [reason, target] of [
    ['main-agent', { ...LOCAL, isMainAgent: true }],
    ['remote-agent', { ...LOCAL, isRemote: true }],
    ['run-as-user', { ...LOCAL, runAsUser: 'other' }],
  ] as const) {
    it(`${reason}: skipped, no file, an earlier live key revoked`, () => {
      const d = agentFolder()
      issueAgentKey('kernel', join(ROOT, `earlier-${++n}`))
      expect(live('kernel')).toBe(1)
      const r = provisionAgentKey('kernel', d, target)
      expect(r).toMatchObject({ state: 'skipped', reason, revoked: 1 })
      expect(existsSync(agentKeyPath(d))).toBe(false)
      expect(live('kernel')).toBe(0)
    })
  }
})

describe('provisionAgentKey: the config folder must be the agent\'s own', () => {
  it('a link to another agent\'s folder: refused, that agent\'s key file untouched, no live key', () => {
    const base = join(ROOT, `agents-${++n}`)
    const viktor = join(base, 'viktor')
    mkdirSync(join(viktor, '.claude-config'), { recursive: true })
    writeFileSync(join(viktor, '.claude-config', 'agent-api-key'), 'viktor-key', { mode: 0o600 })
    const kernel = join(base, 'kernel')
    mkdirSync(kernel)
    symlinkSync(join(viktor, '.claude-config'), join(kernel, '.claude-config'))
    issueAgentKey('kernel', join(ROOT, `earlier-${++n}`))
    const r = provisionAgentKey('kernel', kernel, LOCAL)
    expect(r).toMatchObject({ state: 'failed', reason: 'config-dir-is-a-link', revoked: 1 })
    expect(readFileSync(join(viktor, '.claude-config', 'agent-api-key'), 'utf8')).toBe('viktor-key')
    expect(live('kernel')).toBe(0)
  })
  it('a file where the folder should be: refused', () => {
    const d = join(ROOT, `agents-${++n}`, 'kernel')
    mkdirSync(d, { recursive: true })
    writeFileSync(join(d, '.claude-config'), 'x')
    expect(provisionAgentKey('kernel', d, LOCAL)).toMatchObject({ state: 'failed', reason: 'config-dir-not-a-directory' })
    expect(live('kernel')).toBe(0)
  })
  it('an agent folder reached through a link still issues (only the config folder itself must not be a link)', () => {
    const real = agentFolder()
    const alias = join(ROOT, `alias-${++n}`)
    symlinkSync(real, alias)
    expect(provisionAgentKey('kernel', alias, LOCAL).state).toBe('issued')
    expect(existsSync(agentKeyPath(real))).toBe(true)
  })
  it('a link planted at the key file path is removed, not followed', () => {
    const d = agentFolder()
    const victim = join(ROOT, `victim-${++n}`)
    writeFileSync(victim, 'untouched')
    symlinkSync(victim, agentKeyPath(d))
    expect(provisionAgentKey('kernel', d, LOCAL).state).toBe('issued')
    expect(readFileSync(victim, 'utf8')).toBe('untouched')
    expect(lstatSync(agentKeyPath(d)).isFile()).toBe(true)
  })
  it('a missing agent folder: failed, never thrown', () => {
    expect(provisionAgentKey('kernel', join(ROOT, 'no-such', 'kernel'), LOCAL)).toMatchObject({ state: 'failed', reason: 'ENOENT' })
  })
  it('an invalid agent id: failed, never thrown, no row', () => {
    expect(provisionAgentKey('Kernel', agentFolder(), LOCAL).state).toBe('failed')
    expect((getDb().prepare('SELECT COUNT(*) AS c FROM agent_keys').get() as { c: number }).c).toBe(0)
  })
})

describe('retireAgentKey', () => {
  it('revokes the live key and removes the file', () => {
    const d = agentFolder()
    provisionAgentKey('kernel', d, LOCAL)
    const raw = readFileSync(agentKeyPath(d), 'utf8')
    expect(retireAgentKey('kernel', d)).toEqual({ revoked: 1, fileRemoved: true })
    expect(resolveAgentKey(raw)).toBeNull()
    expect(existsSync(agentKeyPath(d))).toBe(false)
  })
  it('a link at the key path is removed, its target untouched', () => {
    const d = agentFolder()
    const victim = join(ROOT, `victim-${++n}`)
    writeFileSync(victim, 'untouched')
    symlinkSync(victim, agentKeyPath(d))
    expect(retireAgentKey('kernel', d)).toEqual({ revoked: 0, fileRemoved: true })
    expect(readFileSync(victim, 'utf8')).toBe('untouched')
  })
  it('nothing to retire: zero, never thrown', () => {
    expect(retireAgentKey('kernel', join(ROOT, 'no-such', 'kernel'))).toEqual({ revoked: 0, fileRemoved: false })
  })
  // Review 53437 M1 (Viktor's probe c01-c03, s01): through a linked config folder the unlink would follow the link.
  const victimAgent = (): { base: string; viktorKey: string } => {
    const base = join(ROOT, `agents-${++n}`)
    const vk = join(base, 'viktor', '.claude-config')
    mkdirSync(vk, { recursive: true })
    writeFileSync(join(vk, 'agent-api-key'), 'viktor-key', { mode: 0o600 })
    mkdirSync(join(base, 'kernel'))
    return { base, viktorKey: join(vk, 'agent-api-key') }
  }
  it('c01: a config folder linked (absolute) to another agent\'s: revoked, nothing removed, that file untouched', () => {
    const { base, viktorKey } = victimAgent()
    symlinkSync(join(base, 'viktor', '.claude-config'), join(base, 'kernel', '.claude-config'))
    issueAgentKey('kernel', join(ROOT, `earlier-${++n}`))
    expect(retireAgentKey('kernel', join(base, 'kernel'))).toEqual({ revoked: 1, fileRemoved: false, reason: 'config-dir-is-a-link' })
    expect(readFileSync(viktorKey, 'utf8')).toBe('viktor-key')
    expect(live('kernel')).toBe(0)
  })
  it('c02: the same through a relative link (../viktor/.claude-config)', () => {
    const { base, viktorKey } = victimAgent()
    symlinkSync('../viktor/.claude-config', join(base, 'kernel', '.claude-config'))
    expect(retireAgentKey('kernel', join(base, 'kernel'))).toMatchObject({ fileRemoved: false, reason: 'config-dir-is-a-link' })
    expect(readFileSync(viktorKey, 'utf8')).toBe('viktor-key')
  })
  it('c03: a config folder linked outside the agent folders: nothing removed there', () => {
    const outside = join(ROOT, `outside-${++n}`)
    mkdirSync(outside)
    writeFileSync(join(outside, 'agent-api-key'), 'keep')
    const d = join(ROOT, `agents-${++n}`, 'kernel')
    mkdirSync(d, { recursive: true })
    symlinkSync(outside, join(d, '.claude-config'))
    expect(retireAgentKey('kernel', d)).toMatchObject({ fileRemoved: false, reason: 'config-dir-is-a-link' })
    expect(readFileSync(join(outside, 'agent-api-key'), 'utf8')).toBe('keep')
  })
  it('a file where the config folder should be: revoked, nothing removed', () => {
    const d = join(ROOT, `agents-${++n}`, 'kernel')
    mkdirSync(d, { recursive: true })
    writeFileSync(join(d, '.claude-config'), 'x')
    issueAgentKey('kernel', join(ROOT, `earlier-${++n}`))
    expect(retireAgentKey('kernel', d)).toEqual({ revoked: 1, fileRemoved: false, reason: 'config-dir-not-a-directory' })
    expect(readFileSync(join(d, '.claude-config'), 'utf8')).toBe('x')
  })
  it('only the named agent\'s keys', () => {
    issueAgentKey('viktor', join(ROOT, `v-${++n}`))
    const d = agentFolder()
    provisionAgentKey('kernel', d, LOCAL)
    retireAgentKey('kernel', d)
    expect(live('viktor')).toBe(1)
  })
})

describe('revokeAgentKeyOnly (a remote agent, review 53437 L2)', () => {
  it('revokes every live key of the agent, touches no file', () => {
    const d = agentFolder()
    provisionAgentKey('kernel', d, LOCAL)
    expect(revokeAgentKeyOnly('kernel')).toBe(1)
    expect(live('kernel')).toBe(0)
    expect(existsSync(agentKeyPath(d))).toBe(true)
  })
})

// Review 53437 L1, L2: the wiring in agent-process.ts, pinned on its source (the start path needs tmux and a profile).
describe('start and stop wiring (agent-process.ts)', () => {
  const src = readFileSync(join(__dirname, '..', 'web', 'agent-process.ts'), 'utf8')
  const fnBody = (sig: string): string => {
    const a = src.indexOf(sig)
    expect(a).toBeGreaterThan(-1)
    const b = src.indexOf('\nexport ', a + 1)
    return src.slice(a, b === -1 ? undefined : b)
  }
  it('L1: the key is issued after every refusal of the start, right before the session; a failed start retires it', () => {
    const start = fnBody('export async function startAgentProcess(')
    const issue = start.indexOf('keyIssued = issueKeyForStart(')
    const tmux = start.indexOf("['new-session'", issue)
    expect(issue).toBeGreaterThan(-1)
    expect(start.lastIndexOf('return { ok: false', issue)).toBeLessThan(start.indexOf('const startTarget = agentTmuxTarget(name)'))
    expect(start.slice(issue, tmux)).not.toMatch(/return \{ ok: false|throw /)
    const caught = start.slice(start.lastIndexOf('} catch (err) {'))
    expect(caught).toMatch(/if \(keyIssued\) \{\s*const retired = retireAgentKey\(name, dir\)/)
    const own = start.slice(0, start.indexOf('\nfunction issueKeyForStart('))
    expect(own.match(/issueKeyForStart\(/g)?.length).toBe(1) // one issue per start, no other provisioning call
    expect(own).not.toMatch(/provisionAgentKey\(/)
  })
  it('L2: a remote start revokes before handing over; a remote stop revokes, a local stop retires', () => {
    const start = fnBody('export async function startAgentProcess(')
    const remote = start.indexOf('return startRemoteAgentProcess(')
    expect(start.lastIndexOf('revokeAgentKeyOnly(name)', remote)).toBeGreaterThan(start.lastIndexOf('if (remote.host && remote.workdir) {', remote))
    const stop = fnBody('export async function stopAgentProcess(')
    expect(stop).toMatch(/if \(!host\) \{\s*const retired = retireAgentKey\(name, agentDir\(name\)\)[\s\S]*?\} else \{\s*const revoked = revokeAgentKeyOnly\(name\)/)
  })
})
