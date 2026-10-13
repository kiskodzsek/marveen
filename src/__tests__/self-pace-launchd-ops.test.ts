// LAUNCHDOPS1013 (Klodel 2233 B; Viktor 2275/2338): the narrow launchd exception
// for Pulzus in the self-pace gate, and the shell-wrapper hole it uncovered
// (Kernel 2371: `bash -c "<scheduler> ..."` passed). Every refusal Viktor listed
// has a case here; the plist checks run against real temp files.
import { describe, it, expect, beforeAll } from 'vitest'
import { createHash } from 'node:crypto'
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, readFileSync, unlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  gateDecision,
  launchdOpsDecision,
  agentFromConfigDir,
  wrappedPayloads,
  LAUNCHD_OPS_AGENTS,
  LAUNCHD_APPROVED_PLIST_SHA256,
  // @ts-expect-error -- plain .mjs hook script, no types
} from '../../scripts/self-pace-gate.mjs'
import { SELF_PACE_LAUNCHD_AGENTS, selfPaceGateArgs, injectSelfPaceGate } from '../web/agent-scaffold.js'

const UID = 501
const home = mkdtempSync(join(tmpdir(), 'launchd-ops-'))
const agentsDir = join(home, 'Library', 'LaunchAgents')
const PLIST = join(agentsDir, 'hu.myshp.szamla.worker.plist')
let approvedBody: Buffer
const pulzus = { agent: 'pulzus', configDirAgent: 'pulzus', uid: UID, home }
const L = 'launchctl'                       // spelled once, so the test source reads plainly

beforeAll(() => {
  mkdirSync(agentsDir, { recursive: true })
  // A byte-identical copy of the approved worker plist (ops/szamla/deploy, Viktor 2205).
  approvedBody = readFileSync(join(__dirname, 'fixtures', 'hu.myshp.szamla.worker.plist'))
})

function writeApprovedPlist() {
  writeFileSync(PLIST, approvedBody)
}

describe('fixture sanity', () => {
  it('the fixture is byte-identical to the approved szamla worker plist', () => {
    const sha = createHash('sha256').update(approvedBody).digest('hex')
    expect(LAUNCHD_APPROVED_PLIST_SHA256['hu.myshp.szamla.worker'].has(sha)).toBe(true)
  })
})

describe('allowed: the three exact shapes, for pulzus only', () => {
  it('kickstart [-k] of the dashboard, the worker and the watchdog', () => {
    for (const label of ['com.klodel.dashboard', 'hu.myshp.szamla.worker', 'hu.myshp.marabel-watchdog']) {
      for (const k of ['', '-k ']) {
        const r = gateDecision('Bash', { command: `${L} kickstart ${k}gui/${UID}/${label}` }, pulzus)
        expect(r.deny, label).toBe(false)
        expect(r.launchdOps).toEqual([{ sub: 'kickstart', label }])
      }
    }
  })
  it('bootout and bootstrap of the worker, with /bin/ too', () => {
    writeApprovedPlist()
    for (const bin of [L, `/bin/${L}`]) {
      expect(gateDecision('Bash', { command: `${bin} bootout gui/${UID}/hu.myshp.szamla.worker` }, pulzus).deny).toBe(false)
      const r = gateDecision('Bash', { command: `${bin} bootstrap gui/${UID} ${PLIST}` }, pulzus)
      expect(r.deny).toBe(false)
      expect(r.launchdOps[0].plist_sha256).toMatch(/^[0-9a-f]{64}$/)
    }
  })
})

describe('the incident checker (Pulzus 2369)', () => {
  const INC = 'hu.myshp.marabel-incident-passziv'
  const incPlist = join(agentsDir, `${INC}.plist`)
  it('kickstart passes; bootstrap only with the approved plist; a changed plist is refused', () => {
    expect(gateDecision('Bash', { command: `${L} kickstart -k gui/${UID}/${INC}` }, pulzus).deny).toBe(false)
    writeFileSync(incPlist, readFileSync(join(__dirname, 'fixtures', `${INC}.plist`)))
    const ok = gateDecision('Bash', { command: `${L} bootstrap gui/${UID} ${incPlist}` }, pulzus)
    expect(ok.deny).toBe(false)
    expect(ok.launchdOps[0].plist_sha256).toBe('606b9bd893a2681054d38ca49f4ccb607c5994df073b96f8a2aadf74739aa9c1')
    writeFileSync(incPlist, '<plist>other program</plist>')
    expect(gateDecision('Bash', { command: `${L} bootstrap gui/${UID} ${incPlist}` }, pulzus).deny).toBe(true)
  })
})

describe('refused (Viktor 2338)', () => {
  const deny = (command: string, opts: Record<string, unknown> = pulzus) => gateDecision('Bash', { command }, opts).deny
  it('M1: the dashboard cannot be booted out (it could not be loaded back)', () => {
    expect(deny(`${L} bootout gui/${UID}/com.klodel.dashboard`)).toBe(true)
    expect(deny(`${L} bootstrap gui/${UID} ${join(agentsDir, 'com.klodel.dashboard.plist')}`)).toBe(true)
  })
  it('a label outside the lists, e.g. hu.myshp.evil', () => {
    expect(deny(`${L} kickstart -k gui/${UID}/hu.myshp.evil`)).toBe(true)
  })
  it('M3: gui/$(id -u), another uid', () => {
    expect(deny(`${L} kickstart -k gui/$(id -u)/com.klodel.dashboard`)).toBe(true)
    expect(deny(`${L} kickstart -k gui/0/com.klodel.dashboard`)).toBe(true)
  })
  it('a prefix, an extra argument, another subcommand, another binary path', () => {
    expect(deny(`sudo ${L} kickstart -k gui/${UID}/com.klodel.dashboard`)).toBe(true)
    expect(deny(`env X=1 ${L} kickstart -k gui/${UID}/com.klodel.dashboard`)).toBe(true)
    expect(deny(`${L} kickstart -k -p gui/${UID}/com.klodel.dashboard`)).toBe(true)
    expect(deny(`${L} load ${PLIST}`)).toBe(true)
    expect(deny(`${L} submit -l x -- /bin/true`)).toBe(true)
    expect(deny(`/usr/local/bin/${L} kickstart -k gui/${UID}/com.klodel.dashboard`)).toBe(true)
  })
  it('M2: a plist with another hash, a symlinked plist, a plist elsewhere', () => {
    writeFileSync(PLIST, '<plist>tampered</plist>')
    expect(deny(`${L} bootstrap gui/${UID} ${PLIST}`)).toBe(true)
    const real = join(home, 'real.plist')
    writeFileSync(real, approvedBody)
    const link = join(agentsDir, 'hu.myshp.szamla.worker.plist')
    try { unlinkSync(link) } catch { /* none */ }
    symlinkSync(real, link)
    expect(deny(`${L} bootstrap gui/${UID} ${link}`)).toBe(true)
    expect(deny(`${L} bootstrap gui/${UID} /tmp/hu.myshp.szamla.worker.plist`)).toBe(true)
    unlinkSync(link)
  })
  it('the same good shapes for any other agent, or without --agent', () => {
    expect(deny(`${L} kickstart -k gui/${UID}/com.klodel.dashboard`, { ...pulzus, agent: 'kernel', configDirAgent: 'kernel' })).toBe(true)
    expect(deny(`${L} kickstart -k gui/${UID}/com.klodel.dashboard`, { ...pulzus, agent: null })).toBe(true)
  })
  it('(2) --agent pulzus from a session whose CLAUDE_CONFIG_DIR is another agent: refused, marked mismatch', () => {
    const r = gateDecision('Bash', { command: `${L} kickstart -k gui/${UID}/com.klodel.dashboard` }, { ...pulzus, configDirAgent: 'mira' })
    expect(r).toEqual({ deny: true, reason: 'launchd-agent-mismatch' })
  })
  it('a wrapped call: bash -c / sh -c / eval, even with a good shape inside', () => {
    expect(deny(`bash -c "${L} bootstrap gui/${UID} /tmp/x.plist"`)).toBe(true)
    expect(deny(`sh -c '${L} kickstart -k gui/${UID}/com.klodel.dashboard'`)).toBe(true)
    expect(deny(`eval "${L} kickstart -k gui/${UID}/com.klodel.dashboard"`)).toBe(true)
    expect(deny(`/bin/zsh -lc '${L} bootout gui/${UID}/hu.myshp.szamla.worker'`)).toBe(true)
  })
  it('a nesting deeper than the limit is refused', () => {
    // Two quote kinds cannot nest deeper than 2 without escapes, so the guard is
    // exercised directly: a wrapper found at the limit depth is refused.
    expect(gateDecision('Bash', { command: `sh -c 'echo hi'` }, { depth: 3 }).deny).toBe(true)
    expect(gateDecision('Bash', { command: `sh -c 'echo hi'` }, { depth: 2 }).deny).toBe(false)
  })
})

describe('the wrapper scan does not over-block', () => {
  it('a harmless sh -c and a read-only listing pass', () => {
    expect(gateDecision('Bash', { command: `sh -c 'echo hello && ls'` }).deny).toBe(false)
    expect(gateDecision('Bash', { command: `bash -c "${L} print gui/${UID}/com.klodel.dashboard"` }).deny).toBe(false)
  })
  it('extracts the payloads', () => {
    expect(wrappedPayloads(`bash -c "a b"; eval 'c'`)).toEqual(['a b', 'c'])
  })
})

describe('identity helpers and scaffold wiring', () => {
  it('agentFromConfigDir', () => {
    expect(agentFromConfigDir('/Users/klodel/marveen/agents/pulzus/.claude-config')).toBe('pulzus')
    expect(agentFromConfigDir('/Users/klodel/.claude')).toBeNull()
    expect(agentFromConfigDir(undefined)).toBeNull()
  })
  it('the scaffold list equals the gate list', () => {
    expect([...LAUNCHD_OPS_AGENTS].sort()).toEqual([...SELF_PACE_LAUNCHD_AGENTS].sort())
  })
  it('only an eligible agent gets --agent in its hook command; others stay byte-identical', () => {
    expect(selfPaceGateArgs('pulzus')).toEqual(['--agent', 'pulzus'])
    expect(selfPaceGateArgs('kernel')).toEqual([])
    const a: Record<string, unknown> = {}
    const b: Record<string, unknown> = {}
    injectSelfPaceGate(a, 'pulzus')
    injectSelfPaceGate(b, 'kernel')
    expect(JSON.stringify(a)).toContain('self-pace-gate.mjs\\" --agent pulzus')
    expect(JSON.stringify(b)).not.toContain('--agent')
    const c: Record<string, unknown> = {}
    injectSelfPaceGate(c)
    expect(JSON.stringify(c)).toBe(JSON.stringify(b))
  })
  it('launchdOpsDecision is exported pure (no exception without a uid)', () => {
    expect(launchdOpsDecision(`${L} kickstart -k gui/${UID}/com.klodel.dashboard`, { ...pulzus, uid: null }).allowed).toBe(false)
  })
})
