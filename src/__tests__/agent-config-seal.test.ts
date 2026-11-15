// Card 17901b47 (Viktor 43048 INFO 4, 43132): the agent-config.json seal, the detective half. Measured 2026-11-15: a
// sub-agent can rewrite its own or another agent's agent-config.json (same uid, no hook names it), and the launcher
// reads securityProfile / toolDeny / runAsUser / excludeRootClaudeMd / team from it at every spawn. The seal makes such
// a change visible (logger.error + one kanban card per changed state) without blocking the spawn.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const { warn, error } = vi.hoisted(() => ({ warn: vi.fn(), error: vi.fn() }))
vi.mock('../logger.js', () => ({
  logger: { warn, error, info: vi.fn(), debug: vi.fn(), child: () => ({ warn, error, info: vi.fn(), debug: vi.fn() }) },
  PRETTY_OPTIONS: {},
}))

import {
  acceptAgentConfigSeal, agentConfigSealStatus, canonicalJson, checkAgentConfigSeal, sealDashboardWrite,
  type SealDeps, type SealPaths,
} from '../web/agent-config-seal.js'

const here = dirname(fileURLToPath(import.meta.url))
const web = join(here, '..', 'web')
const unix = process.platform !== 'win32'

const BASE = {
  model: 'x', displayName: 'Zz', securityProfile: 'developer-senior-guarded',
  toolDeny: ['Workflow', 'AskUserQuestion'], excludeRootClaudeMd: true,
  team: { role: 'member', reportsTo: 'klodel', delegatesTo: [], autoDelegation: false, trustFrom: [] },
}

describe('agent-config seal', () => {
  let dir = ''
  let paths: SealPaths
  let cards: { title: string; description: string }[]
  let comments: string[]
  let deps: SealDeps
  let t = 1000
  const cfg = (name: string) => join(dir, 'agents', name, 'agent-config.json')
  const writeCfg = (name: string, v: unknown) => writeFileSync(cfg(name), typeof v === 'string' ? v : JSON.stringify(v, null, 2))
  const seal = () => JSON.parse(readFileSync(paths.sealPath, 'utf-8'))

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'cfgseal-'))
    for (const n of ['zza', 'zzb']) mkdirSync(join(dir, 'agents', n), { recursive: true })
    mkdirSync(join(dir, 'store'))
    paths = { configPath: cfg, sealPath: join(dir, 'store', 'agent-config-seal.json') }
    cards = []
    comments = []
    deps = {
      fileCard: (title, description) => { cards.push({ title, description }); return `C${cards.length}` },
      comment: (id, by, text) => { comments.push(`${id}|${by}|${text}`) },
      now: () => ++t,
    }
    warn.mockClear()
    error.mockClear()
  })
  afterEach(() => { rmSync(dir, { recursive: true, force: true }) })

  it('seals on the first spawn (trust on first use, a warning), then matches', () => {
    writeCfg('zza', BASE)
    expect(checkAgentConfigSeal('zza', paths, deps)).toEqual({ status: 'first-seal' })
    expect(warn).toHaveBeenCalledTimes(1)
    expect(seal().agents.zza.by).toBe('first-spawn')
    expect(checkAgentConfigSeal('zza', paths, deps)).toEqual({ status: 'ok' })
    expect(cards).toHaveLength(0)
  })

  it('a non-security field, or the key order, is no change', () => {
    writeCfg('zza', BASE)
    checkAgentConfigSeal('zza', paths, deps)
    const reordered = Object.fromEntries(Object.entries({ ...BASE, displayName: 'Other', model: 'y' }).reverse())
    reordered.team = Object.fromEntries(Object.entries(BASE.team).reverse()) as typeof BASE.team
    writeCfg('zza', reordered)
    expect(checkAgentConfigSeal('zza', paths, deps)).toEqual({ status: 'ok' })
  })

  it.each([
    ['securityProfile', { securityProfile: 'applier' }],
    ['toolDeny', { toolDeny: [] }],
    ['runAsUser', { runAsUser: 'root' }],
    ['excludeRootClaudeMd', { excludeRootClaudeMd: false }],
    ['team', { team: { ...BASE.team, role: 'leader' } }],
    ['team', { team: { ...BASE.team, trustFrom: ['zzb'] } }],
  ])('a rewritten %s is an error and a card, the spawn is not refused', (field, patch) => {
    writeCfg('zza', BASE)
    checkAgentConfigSeal('zza', paths, deps)
    writeCfg('zza', { ...BASE, ...patch })
    const r = checkAgentConfigSeal('zza', paths, deps)
    expect(r).toEqual({ status: 'changed', fields: [field], cardId: 'C1' })
    expect(error).toHaveBeenCalled()
    expect(cards).toHaveLength(1)
    expect(cards[0].title).toContain('zza')
    expect(cards[0].title).toContain(field)
    expect(cards[0].description).toContain('/api/agents/zza/config-seal/accept')
  })

  it('a deleted security field is a change too (the key gone = null)', () => {
    writeCfg('zza', BASE)
    checkAgentConfigSeal('zza', paths, deps)
    const { toolDeny: _drop, ...rest } = BASE
    writeCfg('zza', rest)
    expect(checkAgentConfigSeal('zza', paths, deps)).toMatchObject({ status: 'changed', fields: ['toolDeny'] })
  })

  it('one card per changed state: the next spawn with the same state files none, a further change files one', () => {
    writeCfg('zza', BASE)
    checkAgentConfigSeal('zza', paths, deps)
    writeCfg('zza', { ...BASE, toolDeny: [] })
    checkAgentConfigSeal('zza', paths, deps)
    expect(checkAgentConfigSeal('zza', paths, deps)).toEqual({ status: 'changed', fields: ['toolDeny'], cardId: 'C1' })
    expect(cards).toHaveLength(1)
    writeCfg('zza', { ...BASE, toolDeny: [], securityProfile: 'applier' })
    checkAgentConfigSeal('zza', paths, deps)
    expect(cards).toHaveLength(2)
  })

  it("another agent's file is checked against that agent's own seal", () => {
    writeCfg('zza', BASE)
    writeCfg('zzb', { ...BASE, securityProfile: 'researcher' })
    checkAgentConfigSeal('zza', paths, deps)
    checkAgentConfigSeal('zzb', paths, deps)
    writeCfg('zzb', { ...BASE, securityProfile: 'applier' }) // zza rewrites zzb's file
    expect(checkAgentConfigSeal('zza', paths, deps).status).toBe('ok')
    expect(checkAgentConfigSeal('zzb', paths, deps)).toMatchObject({ status: 'changed', fields: ['securityProfile'] })
  })

  it('a dashboard write moves ITS field only: an earlier hand edit of another field is still reported', () => {
    writeCfg('zza', BASE)
    checkAgentConfigSeal('zza', paths, deps)
    writeCfg('zza', { ...BASE, toolDeny: [] }) // the hand edit
    writeCfg('zza', { ...BASE, toolDeny: [], securityProfile: 'researcher' }) // then the dashboard writes the profile
    sealDashboardWrite('zza', 'securityProfile', 'researcher', paths, deps.now)
    expect(seal().agents.zza.by).toBe('dashboard:securityProfile')
    expect(checkAgentConfigSeal('zza', paths, deps)).toMatchObject({ status: 'changed', fields: ['toolDeny'] })
  })

  it('a dashboard team write matches the file it wrote (an undefined member is dropped like JSON drops it)', () => {
    writeCfg('zza', BASE)
    checkAgentConfigSeal('zza', paths, deps)
    const team = { ...BASE.team, reportsTo: 'zzb', extra: undefined }
    writeCfg('zza', { ...BASE, team })
    sealDashboardWrite('zza', 'team', team, paths, deps.now)
    expect(checkAgentConfigSeal('zza', paths, deps)).toEqual({ status: 'ok' })
  })

  it('a dashboard write before any seal leaves the seal to the first spawn', () => {
    writeCfg('zza', BASE)
    sealDashboardWrite('zza', 'securityProfile', 'researcher', paths, deps.now)
    expect(() => readFileSync(paths.sealPath)).toThrow()
  })

  it('accept moves the seal to the file, records the caller, and comments the alert card of that state', () => {
    writeCfg('zza', BASE)
    checkAgentConfigSeal('zza', paths, deps)
    writeCfg('zza', { ...BASE, toolDeny: ['Workflow'] })
    checkAgentConfigSeal('zza', paths, deps)
    expect(agentConfigSealStatus('zza', paths)).toMatchObject({ sealed: true, matches: false, changed: ['toolDeny'] })
    const e = acceptAgentConfigSeal('zza', 'token:klodel', paths, deps)
    expect(e?.by).toBe('token:klodel')
    expect(comments).toEqual([expect.stringMatching(/^C1\|token:klodel\|Elfogadva/)])
    expect(checkAgentConfigSeal('zza', paths, deps)).toEqual({ status: 'ok' })
    expect(agentConfigSealStatus('zza', paths)).toMatchObject({ sealed: true, matches: true, changed: [] })
  })

  it('accept of a state no card was filed for comments nothing', () => {
    writeCfg('zza', BASE)
    checkAgentConfigSeal('zza', paths, deps)
    writeCfg('zza', { ...BASE, toolDeny: [] })
    checkAgentConfigSeal('zza', paths, deps)
    writeCfg('zza', { ...BASE, toolDeny: ['X'] }) // changed again, not yet spawned
    acceptAgentConfigSeal('zza', 'session', paths, deps)
    expect(comments).toEqual([])
  })

  it('never throws and never blocks: no file, a broken file, a broken seal, a failing card, an unwritable store', () => {
    expect(checkAgentConfigSeal('zza', paths, deps)).toEqual({ status: 'no-config' })
    writeCfg('zza', '{not json')
    expect(checkAgentConfigSeal('zza', paths, deps)).toEqual({ status: 'no-config' })
    writeCfg('zza', '[1,2]')
    expect(checkAgentConfigSeal('zza', paths, deps)).toEqual({ status: 'no-config' })
    writeCfg('zza', BASE)
    writeFileSync(paths.sealPath, 'garbage')
    expect(checkAgentConfigSeal('zza', paths, deps)).toEqual({ status: 'first-seal' })
    writeCfg('zza', { ...BASE, toolDeny: [] })
    const throwing: SealDeps = { ...deps, fileCard: () => { throw new Error('db down') } }
    expect(checkAgentConfigSeal('zza', paths, throwing)).toEqual({ status: 'changed', fields: ['toolDeny'], cardId: null })
    const gone: SealPaths = { configPath: cfg, sealPath: join(dir, 'no-such-dir', 'seal.json') }
    expect(checkAgentConfigSeal('zza', gone, deps)).toEqual({ status: 'no-config' })
  })

  it.skipIf(!unix)('a FIFO in place of the config or the seal is not read (returns at once)', () => {
    execFileSync('mkfifo', [cfg('zza')])
    const t0 = Date.now()
    expect(checkAgentConfigSeal('zza', paths, deps)).toEqual({ status: 'no-config' })
    rmSync(cfg('zza'))
    writeCfg('zza', BASE)
    execFileSync('mkfifo', [paths.sealPath])
    expect(agentConfigSealStatus('zza', paths)).toMatchObject({ sealed: false })
    expect(Date.now() - t0).toBeLessThan(2000)
  })

  it('canonicalJson sorts keys at every depth and keeps array order', () => {
    expect(canonicalJson({ b: 1, a: { d: [2, 1], c: null } })).toBe('{"a":{"c":null,"d":[2,1]},"b":1}')
    expect(canonicalJson(undefined)).toBe('null')
  })
})

describe('agent-config seal: wired where it must be (source pins)', () => {
  const src = (f: string) => readFileSync(join(web, f), 'utf-8')

  it('startAgentProcess checks the seal right after the unsafe-file refusal, before any other read', () => {
    const s = src('agent-process.ts')
    const start = s.indexOf('export async function startAgentProcess(')
    const refusal = s.indexOf('agentConfigRefusal(name)', start)
    const check = s.indexOf('checkAgentConfigSeal(name, DEFAULT_SEAL_PATHS, LAUNCHER_SEAL_DEPS)', start)
    const remote = s.indexOf('readAgentRemoteConfig(name)', start)
    expect(start).toBeGreaterThan(0)
    expect(refusal).toBeGreaterThan(start)
    expect(check).toBeGreaterThan(refusal)
    expect(check).toBeLessThan(remote)
  })

  it('the dashboard writers of a sealed field move that field only', () => {
    expect(src('agent-config.ts')).toMatch(/config\.securityProfile = profileId\n\s+atomicWriteFileSync\(configPath, [^\n]+\n\s+sealDashboardWrite\(name, 'securityProfile', profileId\)/)
    expect(src('agent-team.ts')).toMatch(/config\.team = team\n\s+atomicWriteFileSync\(configPath, [^\n]+\n\s+sealDashboardWrite\(name, 'team', team\)/)
  })

  it('the seal module imports no database and not agent-config (no cycle; the kanban side is injected)', () => {
    const s = src('agent-config-seal.ts')
    expect(s).not.toMatch(/from '\.\.\/db\.js'/)
    expect(s).not.toMatch(/from '\.\/agent-config\.js'/)
    expect(s).not.toMatch(/from '\.\/agent-team\.js'/)
  })
})
