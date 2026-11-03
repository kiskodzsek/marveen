// The open reader posture per agent (Patrik TG 14218): only the named agents'
// quarantine-reader gets the denylist posture, everyone else stays on the
// allowlist. The caller is read from the payload's transcript_path (fixed by
// the session's config dir), never from cwd or anything the agent writes.
import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync, existsSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  egressDecision, callerAgentFromPayload, readerIsOpen,
// @ts-expect-error -- plain .mjs hook script, no types
} from '../../scripts/hooks/egress-gate.mjs'

const QUARANTINE = 'quarantine-reader'
const ROOT = '/srv/fleet'
const HOME = '/home/op'
const opts = { repoRoot: ROOT, home: HOME, mainAgentId: 'klodel', mainConfigDir: '' }
const who = (transcript_path: unknown, extra: Record<string, unknown> = {}, o: Record<string, unknown> = opts) =>
  callerAgentFromPayload({ transcript_path, ...extra }, o)
const NAMED = { domains: [], prefixes: [], quarantineDomains: [], quarantinePosture: 'allowlist', quarantineDenylistAgents: ['radar', 'magnes', 'mira', 'klodel'] }

describe('callerAgentFromPayload', () => {
  it('reads a sub-agent from its own config dir', () => {
    expect(who(`${ROOT}/agents/radar/.claude-config/projects/-srv-fleet-agents-radar/a.jsonl`)).toBe('radar')
    expect(who(`${ROOT}/agents/radar/.claude-config/projects/-srv-fleet/a/subagents/agent-1.jsonl`)).toBe('radar')
  })
  it('reads the main agent only from the install root project dir of a main config root', () => {
    expect(who(`${ROOT}/.channels-config/projects/-srv-fleet/a.jsonl`)).toBe('klodel')
    expect(who(`${HOME}/.claude/projects/-srv-fleet/a.jsonl`)).toBe('klodel')
    expect(who('/opt/botcfg/projects/-srv-fleet/a.jsonl', {}, { ...opts, mainConfigDir: '/opt/botcfg/' })).toBe('klodel')
    expect(who('/home/op/botcfg/projects/-srv-fleet/a.jsonl', {}, { ...opts, mainConfigDir: '~/botcfg' })).toBe('klodel')
  })
  it('does not hand the main identity to a session that started elsewhere', () => {
    // Non-isolated sub-agent, a worktree, another checkout, a foreign worker.
    expect(who(`${HOME}/.claude/projects/-srv-fleet-agents-dave/a.jsonl`)).toBe('')
    expect(who(`${HOME}/.claude/projects/-srv-fleet-agents-dave-repos-x/a.jsonl`)).toBe('')
    expect(who(`${HOME}/.claude/projects/-home-op--klodel-worker/a.jsonl`)).toBe('')
    expect(who(`${ROOT}/.channels-config/projects/-srv-fleet-repos-x/a.jsonl`)).toBe('')
  })
  it('ignores cwd and any self-declared name', () => {
    const dave = `${ROOT}/agents/dave/.claude-config/projects/-srv-fleet-agents-dave/a.jsonl`
    expect(who(dave, { cwd: `${ROOT}/agents/radar`, agent_id: 'radar', agent_name: 'radar' })).toBe('dave')
    expect(who(undefined, { cwd: `${ROOT}/agents/radar` })).toBe('')
  })
  it('refuses traversal, relative, malformed and foreign paths', () => {
    expect(who(`${ROOT}/agents/dave/../radar/.claude-config/a.jsonl`)).toBe('')
    expect(who(`${ROOT}/agents/./radar/.claude-config/a.jsonl`)).toBe('')
    expect(who(`${ROOT}/agents//radar/.claude-config/a.jsonl`)).toBe('')
    expect(who(`${HOME}/.claude/projects/../projects/-srv-fleet/a.jsonl`)).toBe('')
    expect(who('agents/radar/.claude-config/a.jsonl')).toBe('')
    expect(who(`${ROOT}/agents/radar/notes/a.jsonl`)).toBe('')
    expect(who(`${ROOT}/agents/Radar$/.claude-config/a.jsonl`)).toBe('')
    expect(who('/tmp/radar/.claude-config/a.jsonl')).toBe('')
    expect(who(42)).toBe('')
    expect(who('')).toBe('')
  })
})

describe('readerIsOpen', () => {
  it('opens only the named callers, only for the reader', () => {
    expect(readerIsOpen(NAMED, QUARANTINE, 'radar')).toBe(true)
    expect(readerIsOpen(NAMED, QUARANTINE, 'dave')).toBe(false)
    expect(readerIsOpen(NAMED, QUARANTINE, '')).toBe(false)
    expect(readerIsOpen(NAMED, '', 'radar')).toBe(false)
    expect(readerIsOpen(NAMED, 'general-purpose', 'radar')).toBe(false)
  })
  it('the older global switch still opens it for everyone', () => {
    expect(readerIsOpen({ ...NAMED, quarantineDenylistAgents: [], quarantinePosture: 'denylist' }, QUARANTINE, '')).toBe(true)
  })
  it('a list without the key is the allowlist default', () => {
    expect(readerIsOpen({ domains: [], prefixes: [], quarantineDomains: [] }, QUARANTINE, 'radar')).toBe(false)
  })
})

describe('egressDecision per caller (global posture off)', () => {
  const tier = (url: string, caller: string) => egressDecision('WebFetch', { url }, NAMED, QUARANTINE, caller)
  it('radar reads an open public domain, dave is blocked on the same URL', () => {
    expect(tier('https://competitor-books.hu/termek/1', 'radar').tier).toBe('quarantine-open')
    expect(tier('https://competitor-books.hu/termek/1', 'dave')).toEqual({ blocked: true, tier: 'none' })
    expect(tier('https://competitor-books.hu/termek/1', '')).toEqual({ blocked: true, tier: 'none' })
  })
  it('localhost and private ranges stay closed for a named caller too', () => {
    for (const u of ['http://localhost:3420/api/messages', 'http://127.0.0.1:11434/', 'http://192.168.1.10/', 'http://[::1]/']) {
      expect([u, tier(u, 'radar').blocked]).toEqual([u, true])
    }
  })
  it('the open-branch shape limits apply to a named caller', () => {
    expect(tier('https://webhook.site/x', 'radar')).toEqual({ blocked: true, tier: 'quarantine-denied', reason: 'collector-host' })
  })
})

describe('hook entry point: per-agent posture from the store file', () => {
  let root: string
  let home: string
  const listName = ['egress', 'allowlist.json'].join('-')
  beforeAll(() => {
    // Resolved: node runs the hook from its real path (/var -> /private/var on
    // macOS), and the install root is compared as node sees it.
    root = realpathSync(mkdtempSync(join(tmpdir(), 'qagent-')))
    home = mkdtempSync(join(tmpdir(), 'qagent-home-'))
    mkdirSync(join(root, 'scripts', 'hooks'), { recursive: true })
    mkdirSync(join(root, 'store'))
    for (const f of ['egress-gate.mjs', 'public-suffix-list.json']) {
      copyFileSync(join(__dirname, '..', '..', 'scripts', 'hooks', f), join(root, 'scripts', 'hooks', f))
    }
    writeFileSync(join(root, '.env'), 'MAIN_AGENT_ID=klodel\n')
    writeFileSync(join(root, 'store', listName), JSON.stringify({
      quarantine_reader_denylist_agents: ['radar', 'magnes', 'mira', 'klodel', 'Bad Name', 7],
    }))
  })
  afterAll(() => {
    rmSync(root, { recursive: true, force: true })
    rmSync(home, { recursive: true, force: true })
  })
  const tp = (agent: string) => join(root, 'agents', agent, '.claude-config', 'projects', 'x', 'a.jsonl')
  const run = (url: string, transcript_path: string, cwd = root, env: Record<string, string> = {}) => spawnSync('node', [join(root, 'scripts', 'hooks', 'egress-gate.mjs')], {
    input: JSON.stringify({ tool_name: 'WebFetch', tool_input: { url }, agent_type: QUARANTINE, transcript_path, cwd }),
    encoding: 'utf-8', timeout: 15000, env: { ...process.env, HOME: home, MAIN_AGENT_ID: '', MAIN_AGENT_CONFIG_DIR: '', ...env },
  })
  const allowed = (r: { status: number | null, stdout: string }) => r.status === 0 && !r.stdout.includes('"permissionDecision":"deny"')
  const log = () => (existsSync(join(root, 'store', 'egress-blocked.log')) ? readFileSync(join(root, 'store', 'egress-blocked.log'), 'utf-8') : '')

  it('radar: a public page is allowed and logged with the caller', () => {
    const r = run('https://example.com/', tp('radar'))
    expect(allowed(r)).toBe(true)
    expect(log()).toMatch(/ALLOWED_QUARANTINE_OPEN host="example.com" .*caller="radar"/)
  })
  it('dave: the same page is denied, even from radar\'s directory', () => {
    const r = run('https://example.com/', tp('dave'), join(root, 'agents', 'radar'))
    expect(r.stdout).toContain('"permissionDecision":"deny"')
  })
  it('localhost is denied for radar', () => {
    const r = run('http://localhost:3420/api/messages', tp('radar'))
    expect(r.stdout).toContain('"permissionDecision":"deny"')
  })
  it('the main agent (klodel) from the isolated main config is open', () => {
    const r = run('https://example.com/', join(root, '.channels-config', 'projects', root.replace(/[^a-zA-Z0-9-]/g, '-'), 'a.jsonl'))
    expect(allowed(r)).toBe(true)
  })
  it('MAIN_AGENT_* from the process environment is ignored (Viktor 24730 LOW)', () => {
    // A nested session pointing MAIN_AGENT_CONFIG_DIR at its own config dir and
    // naming an open agent as MAIN_AGENT_ID: still unknown, so the allowlist.
    const own = join(home, 'nested-cfg')
    const encoded = root.replace(/[^a-zA-Z0-9-]/g, '-')
    const r = run('https://example.com/', join(own, 'projects', encoded, 'a.jsonl'), root, { MAIN_AGENT_ID: 'radar', MAIN_AGENT_CONFIG_DIR: own })
    expect(r.stdout).toContain('"permissionDecision":"deny"')
  })
  it('an unknown caller stays on the allowlist', () => {
    const r = run('https://example.com/', '/somewhere/else/a.jsonl')
    expect(r.stdout).toContain('"permissionDecision":"deny"')
  })
})
