// Card 45dea12e slice 2 (security review 53307 point 5): the narrow key is issued at agent start and retired at stop.
// Contract under test:
//   - a local agent gets <agent dir>/.claude-config/agent-api-key, 0600, holding a key that resolves to that agent;
//     the earlier key is revoked by the issue; a missing config folder is made 0700;
//   - the main agent, a remote agent and a runAsUser agent get no key, and an earlier live key of theirs is revoked;
//   - a config folder that is a link or not a directory: no write anywhere,
//     no live key, the other agent's key file untouched;
//   - retire: every live key revoked, the file (or a link at its path) removed, the link's target untouched;
//   - a failure never throws.
import { describe, it, expect, beforeAll, afterAll, beforeEach } from 'vitest'
import { existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { initDatabase, getDb } from '../db.js'
import { issueAgentKey, resolveAgentKey } from '../web/auth-agent-keys.js'
import { agentKeyPath, provisionAgentKey, retireAgentKey } from '../web/agent-key-provision.js'

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
  it('only the named agent\'s keys', () => {
    issueAgentKey('viktor', join(ROOT, `v-${++n}`))
    const d = agentFolder()
    provisionAgentKey('kernel', d, LOCAL)
    retireAgentKey('kernel', d)
    expect(live('viktor')).toBe(1)
  })
})
