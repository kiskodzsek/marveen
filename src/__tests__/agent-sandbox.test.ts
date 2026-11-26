import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createHash } from 'node:crypto'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, realpathSync, rmSync, symlinkSync, chmodSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { tmpdir } from 'node:os'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import {
  SANDBOX_PROFILES, SandboxRenderError, renderSandboxProfile, canonicalPath, readSandboxOptIn, readSandboxState,
  decideAgentSandbox, sandboxLaunchPrefix, recordSandboxStart, type SandboxPaths, type SandboxDecision,
} from '../web/agent-sandbox.js'
import { shSingleQuote } from '../web/agent-process.js'
import { isConfigStartRefusal } from '../web/schedule-runner.js'
import { agentKeyRule } from '../web/agent-key-gate.js'

// Card 6aa0a853, canary step (security review 54105, 54110). See src/web/agent-sandbox.ts.

const sha = (s: string) => createHash('sha256').update(s, 'utf8').digest('hex')
const ROOT_SRC = join(dirname(fileURLToPath(import.meta.url)), '..', '..')

// The kernel instance that review 53372 approved (MEHET + HASH-OK): kc-deny-v4-kernel.sb, rendered by render.py from
// the v4 template with root /Users/klodel/marveen, self kernel, home /Users/klodel.
const APPROVED_KERNEL_SHA = 'fc127b73b32aa31463a342b746fd14d23e101c39a1818405db4e0052c213f3a8'
const FIXED = { root: '/Users/klodel/marveen', home: '/Users/klodel', self: 'kernel' }

let tmp: string
let paths: SandboxPaths
beforeEach(() => {
  // The fixture is the install root of the render, which refuses a '.' (a regex metacharacter): a TMPDIR such as
  // /tmp/kt.noindex/... (tools that move TMPDIR out of Spotlight) cannot be one, so the base is /tmp itself.
  tmp = realpathSync(mkdtempSync(join(process.platform === 'win32' ? tmpdir() : '/tmp', 'sbx-')))
  paths = { optinPath: join(tmp, 'agent-sandbox.json'), statePath: join(tmp, 'agent-sandbox-state.json') }
})
afterEach(() => rmSync(tmp, { recursive: true, force: true }))

const env = (over: Partial<{ root: string; home: string; isMain: boolean; isRemote: boolean }> = {}) => ({
  root: tmp, home: tmp, isMain: false, isRemote: false, ...over,
})
const writeOptIn = (agents: Record<string, unknown>) => writeFileSync(paths.optinPath, JSON.stringify({ version: 1, agents }))
const writeState = (agents: Record<string, unknown>) => writeFileSync(paths.statePath, JSON.stringify({ version: 1, agents }))

describe('the profile and its render (review 54110 V5-1)', () => {
  it('the template constant is the approved v4 template, by its pinned hash', () => {
    expect(sha(SANDBOX_PROFILES['kc-v4'].template)).toBe(SANDBOX_PROFILES['kc-v4'].sha256)
    expect(SANDBOX_PROFILES['kc-v4'].sha256).toBe('057b2693f5eafc1ae3aa539d8850264ffea9a9d41f23f2ede72128b89c246817')
  })
  it('a fixed input renders byte for byte the approved kernel instance', () => {
    expect(sha(renderSandboxProfile('kc-v4', FIXED))).toBe(APPROVED_KERNEL_SHA)
  })
  it.each([
    ['a dot', '/Users/k.l/marveen'], ['a double quote', '/Users/k"l'], ['a backslash', '/Users/k\\l'], ['a parenthesis', '/Users/k)l'],
    ['a newline', '/Users/k\nl'], ['a space', '/Users/k l'], ['a trailing slash', '/Users/klodel/'], ['a double slash', '/Users//klodel'],
    ['a relative path', 'Users/klodel'], ['an empty string', ''], ['a hash sign', '/Users/k#l'], ['a dollar sign', '/Users/k$l'],
  ])('a root or home with %s is refused', (_w, bad) => {
    expect(() => renderSandboxProfile('kc-v4', { ...FIXED, root: bad })).toThrow(SandboxRenderError)
    expect(() => renderSandboxProfile('kc-v4', { ...FIXED, home: bad })).toThrow(SandboxRenderError)
  })
  it.each([['Kernel'], ['../x'], ['a b'], [''], ['-x'], ['x'.repeat(65)], ['ke"rnel']])('the agent id %j is refused', (self) => {
    expect(() => renderSandboxProfile('kc-v4', { ...FIXED, self })).toThrow(SandboxRenderError)
  })
  it('an unknown profile is refused, and no error message carries profile text', () => {
    expect(() => renderSandboxProfile('kc-v5', FIXED)).toThrow('unknown profile')
    expect(() => renderSandboxProfile('__proto__', FIXED)).toThrow('unknown profile')
    try { renderSandboxProfile('kc-v4', { ...FIXED, root: '/a.b' }) } catch (e) { expect(String(e)).not.toMatch(/deny|allow|version/) }
  })
  it('canonicalPath: a link or a non-canonical form is refused, the real path is kept', () => {
    mkdirSync(join(tmp, 'real'))
    symlinkSync(join(tmp, 'real'), join(tmp, 'link'))
    expect(canonicalPath(join(tmp, 'real'))).toBe(join(tmp, 'real'))
    expect(() => canonicalPath(join(tmp, 'link'))).toThrow('not canonical')
    expect(() => canonicalPath(`${tmp}/real/../real`)).toThrow('not canonical') // a raw string: join() would normalise it
    expect(() => canonicalPath(`${tmp}/real/`)).toThrow('not canonical')
    expect(() => canonicalPath(join(tmp, 'none'))).toThrow('cannot be resolved')
  })
})

describe('the opt-in file (review 54110 M1)', () => {
  it('missing, unreadable, over the cap, not JSON, wrong shape', () => {
    expect(readSandboxOptIn(paths.optinPath)).toEqual({ kind: 'missing' })
    writeFileSync(paths.optinPath, '{')
    expect(readSandboxOptIn(paths.optinPath)).toMatchObject({ kind: 'bad', reason: 'not JSON' })
    writeFileSync(paths.optinPath, 'x'.repeat(64 * 1024 + 1))
    expect(readSandboxOptIn(paths.optinPath)).toMatchObject({ kind: 'bad', reason: 'unreadable' })
    for (const v of [[], { version: 2, agents: {} }, { version: 1 }, { version: 1, agents: [] }]) {
      writeFileSync(paths.optinPath, JSON.stringify(v))
      expect(readSandboxOptIn(paths.optinPath)).toMatchObject({ kind: 'bad', reason: 'bad shape' })
    }
    writeFileSync(paths.optinPath, JSON.stringify({ version: 1, agents: {}, extra: 1 }))
    expect(readSandboxOptIn(paths.optinPath)).toMatchObject({ kind: 'bad', reason: 'unknown key' })
    writeOptIn({ kernel: 1 })
    expect(readSandboxOptIn(paths.optinPath)).toMatchObject({ kind: 'bad', reason: 'bad entry' })
    writeOptIn({ 'Bad Name': 'kc-v4' })
    expect(readSandboxOptIn(paths.optinPath)).toMatchObject({ kind: 'bad', reason: 'bad entry' })
    writeOptIn({ kernel: 'kc-v4' })
    expect(readSandboxOptIn(paths.optinPath)).toEqual({ kind: 'ok', agents: { kernel: 'kc-v4' } })
  })
  it.skipIf(process.platform === 'win32')('a FIFO and a directory are unreadable, and the read does not block', () => {
    expect(spawnSync('mkfifo', [paths.optinPath]).status).toBe(0)
    expect(readSandboxOptIn(paths.optinPath)).toMatchObject({ kind: 'bad', reason: 'unreadable' })
    rmSync(paths.optinPath)
    mkdirSync(paths.optinPath)
    expect(readSandboxOptIn(paths.optinPath)).toMatchObject({ kind: 'bad', reason: 'unreadable' })
  })
})

describe('decideAgentSandbox (fail closed, review 54110 M1)', () => {
  it('nothing opted in, nothing recorded: off, no warning', () => {
    expect(decideAgentSandbox('kernel', paths, env())).toEqual({ kind: 'off', downgradedFrom: null, warning: null })
  })
  it('the opt-in file is gone after a sandboxed start: refused', () => {
    writeState({ kernel: { profile: 'kc-v4', at: 1 } })
    expect(decideAgentSandbox('kernel', paths, env())).toMatchObject({ kind: 'refused', reason: 'opt-in file missing after a sandboxed start' })
    // another agent, never sandboxed, starts as before
    expect(decideAgentSandbox('juro', paths, env())).toMatchObject({ kind: 'off', downgradedFrom: null })
  })
  it('an unreadable opt-in file: refused after a sandboxed start, otherwise off with a warning', () => {
    writeFileSync(paths.optinPath, '{"version":1,')
    expect(decideAgentSandbox('juro', paths, env())).toEqual({ kind: 'off', downgradedFrom: null, warning: 'opt-in file not JSON' })
    writeState({ kernel: { profile: 'kc-v4', at: 1 } })
    expect(decideAgentSandbox('kernel', paths, env())).toMatchObject({ kind: 'refused', reason: 'opt-in file not JSON after a sandboxed start' })
  })
  it('taken out of the opt-in after a sandboxed start: off, reported as a downgrade', () => {
    writeOptIn({})
    writeState({ kernel: { profile: 'kc-v4', at: 1 } })
    expect(decideAgentSandbox('kernel', paths, env())).toEqual({ kind: 'off', downgradedFrom: 'kc-v4', warning: null })
  })
  it('an unknown profile name, the main agent, a remote agent, a non-canonical root: refused', () => {
    writeOptIn({ kernel: 'kc-v9' })
    expect(decideAgentSandbox('kernel', paths, env())).toMatchObject({ kind: 'refused', reason: 'unknown profile' })
    writeOptIn({ kernel: 'kc-v4' })
    expect(decideAgentSandbox('kernel', paths, env({ isMain: true }))).toMatchObject({ kind: 'refused' })
    expect(decideAgentSandbox('kernel', paths, env({ isRemote: true }))).toMatchObject({ kind: 'refused' })
    symlinkSync(tmp, join(tmp, 'rootlink'))
    expect(decideAgentSandbox('kernel', paths, env({ root: join(tmp, 'rootlink') }))).toMatchObject({ kind: 'refused', reason: 'path is not canonical' })
  })
  it.each([['Kernel'], ['KERNEL'], ['kerneL'], ['kernel '], ['kernel/'], ['']])('a name that is not the canonical agent id (%j) is refused, opted in or not (review 54118 B1)', (n) => {
    writeOptIn({ kernel: 'kc-v4' })
    expect(decideAgentSandbox(n, paths, env())).toEqual({ kind: 'refused', reason: 'not a canonical agent id' })
    writeOptIn({})
    expect(decideAgentSandbox(n, paths, env())).toEqual({ kind: 'refused', reason: 'not a canonical agent id' })
  })
  it('a present state entry that is not {profile: string|null} counts as sandboxed (review 54118 B2 (b))', () => {
    for (const bad of [{ profile: 1 }, { profile: {} }, 'kc-v4', null, [], {}]) {
      writeState({ kernel: bad })
      expect(decideAgentSandbox('kernel', paths, env())).toMatchObject({ kind: 'refused' })
      writeOptIn({})
      expect(decideAgentSandbox('kernel', paths, env())).toMatchObject({ kind: 'off', downgradedFrom: '(unreadable state entry)' })
      rmSync(paths.optinPath)
    }
  })
  it('an inherited member is no entry: "constructor" finds nothing in the state or the opt-in (review 54118 B3)', () => {
    expect(decideAgentSandbox('constructor', paths, env())).toEqual({ kind: 'off', downgradedFrom: null, warning: null })
    writeOptIn({})
    expect(decideAgentSandbox('constructor', paths, env())).toEqual({ kind: 'off', downgradedFrom: null, warning: null })
    expect(readSandboxState(paths.statePath)).toEqual({})
    expect(Object.getPrototypeOf(readSandboxState(paths.statePath))).toBeNull()
  })
  it('opted in: on, the rendered profile of this agent', () => {
    writeOptIn({ kernel: 'kc-v4' })
    const d = decideAgentSandbox('kernel', paths, env())
    expect(d).toMatchObject({ kind: 'on', profile: 'kc-v4' })
    expect((d as { text: string }).text).toBe(renderSandboxProfile('kc-v4', { root: tmp, home: tmp, self: 'kernel' }))
  })
  it('the start mode is recorded atomically and read back; an unwritable store reports false', () => {
    expect(recordSandboxStart('kernel', 'kc-v4', paths, 5000)).toBe(true)
    expect(recordSandboxStart('juro', null, paths, 6000)).toBe(true)
    expect(readSandboxState(paths.statePath)).toEqual({ kernel: 'kc-v4', juro: null })
    expect(JSON.parse(readFileSync(paths.statePath, 'utf8')).agents.kernel.at).toBe(5)
    const ro = join(tmp, 'ro')
    mkdirSync(ro)
    chmodSync(ro, 0o500)
    try {
      expect(recordSandboxStart('kernel', 'kc-v4', { optinPath: paths.optinPath, statePath: join(ro, 's.json') })).toBe(false)
    } finally {
      chmodSync(ro, 0o700)
    }
  })
})

describe('the launch prefix', () => {
  it('off: empty, so an agent that is not opted in launches byte for byte as before (review 54105 V5-2)', () => {
    expect(sandboxLaunchPrefix({ kind: 'off', downgradedFrom: null, warning: null }, shSingleQuote)).toBe('')
    expect(sandboxLaunchPrefix({ kind: 'refused', reason: 'x' }, shSingleQuote)).toBe('')
  })
  it('on: the prefix stays far below the tmux command limit (measured 2026-11-26: 16000 characters run, 32000 "command too long"; a live launch line was 1419)', () => {
    const d: SandboxDecision = { kind: 'on', profile: 'kc-v4', text: renderSandboxProfile('kc-v4', FIXED) }
    expect(sandboxLaunchPrefix(d, shSingleQuote).length).toBeLessThan(8000)
  })
  it.skipIf(process.platform !== 'darwin')('on: the shell passes the profile as one argument, and the profile holds (own key readable, another agent\'s not)', () => {
    for (const a of ['kernel', 'juro']) {
      mkdirSync(join(tmp, 'agents', a, '.claude-config'), { recursive: true })
      writeFileSync(join(tmp, 'agents', a, '.claude-config', 'agent-api-key'), `k-${a}\n`)
    }
    const d: SandboxDecision = { kind: 'on', profile: 'kc-v4', text: renderSandboxProfile('kc-v4', { root: tmp, home: tmp, self: 'kernel' }) }
    const run = (target: string) => spawnSync('/bin/sh', ['-c', `${sandboxLaunchPrefix(d, shSingleQuote)}/bin/cat ${shSingleQuote(target)}`], { encoding: 'utf8' })
    const own = run(join(tmp, 'agents', 'kernel', '.claude-config', 'agent-api-key'))
    expect(own.status).toBe(0)
    expect(own.stdout).toBe('k-kernel\n')
    const other = run(join(tmp, 'agents', 'juro', '.claude-config', 'agent-api-key'))
    expect(other.status).not.toBe(0)
    expect(other.stdout).toBe('')
  })
})

describe('the wiring', () => {
  const src = readFileSync(join(ROOT_SRC, 'src/web/agent-process.ts'), 'utf8')
  const fn = src.slice(src.indexOf('export async function startAgentProcess('))
  it('the decision comes before the remote branch and before the launch command; a refusal returns before any launch', () => {
    const decide = fn.indexOf('const sandbox = decideAgentSandbox(')
    expect(decide).toBeGreaterThan(0)
    expect(decide).toBeLessThan(fn.indexOf('if (remote.host && remote.workdir) {'))
    expect(decide).toBeLessThan(fn.indexOf('const buildLaunchCmd'))
    expect(fn.slice(decide, decide + 900)).toMatch(/if \(sandbox\.kind === 'refused'\) \{\n[^\n]*\n\s*return \{ ok: false, error: `agent-sandbox: refused \(\$\{sandbox\.reason\}\)` \}/)
  })
  it('the prefix stands right before the claude binary, after the cd; the mode is recorded before the first new-session', () => {
    expect(fn).toMatch(/cd "\$\{launchCwd\}" && \$\{sandboxPrefix\}\$\{claudeBin\(\)\} /)
    expect(fn.match(/\$\{sandboxPrefix\}/g)).toHaveLength(1)
    const rec = fn.indexOf('recordSandboxStart(')
    expect(rec).toBeGreaterThan(0)
    expect(rec).toBeLessThan(fn.indexOf("runTmux(startTarget, ['new-session'"))
    // review 54118 B2 (a): a sandboxed start whose mode is not recorded returns before the key and the session
    expect(rec).toBeLessThan(fn.indexOf('keyIssued = issueKeyForStart('))
    expect(fn.slice(rec, rec + 400)).toMatch(/if \(sandbox\.kind === 'on'\) return \{ ok: false, error: 'agent-sandbox: refused \(the start mode could not be recorded\)' \}/)
  })
  it('a sandbox refusal is a config refusal for the scheduler (not retried every tick)', () => {
    expect(isConfigStartRefusal('agent-sandbox: refused (unknown profile)')).toBe(true)
    expect(isConfigStartRefusal('agent-sandbox: something else')).toBe(false)
  })
  it('the narrow agent key has no endpoint that changes an agent\'s config or start (deny by default, review 54105 B2)', () => {
    for (const [m, p] of [
      ['PUT', '/api/agents/kernel'], ['PATCH', '/api/agents/kernel'], ['POST', '/api/agents/kernel/remote'], ['PUT', '/api/agents/kernel/remote'],
      ['POST', '/api/agents/kernel/restart'], ['POST', '/api/agents/kernel/start'], ['POST', '/api/agents/kernel/stop'],
      ['POST', '/api/agents/kernel/config-seal/accept'], ['PUT', '/api/agents/kernel/context-guard'], ['POST', '/api/agents/kernel/auto-restart'],
      ['POST', '/api/agents/kernel/sandbox'], ['PUT', '/api/agents/kernel/sandbox'],
    ] as const) expect(agentKeyRule(m, p)).toBeNull()
  })
})
