import { describe, expect, it, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, readdirSync, rmSync, symlinkSync, statSync, chmodSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import {
  decideClaudeJsonRestore,
  resolveOwnClaudeJsonPath,
  takeClaudeJsonSnapshot,
  restoreClaudeJsonAfterStop,
  waitForPidExit,
  shaHex,
  describeShape,
} from '../web/claude-json-guard.js'

// Synthetic stand-in for an isolated .claude.json: the measured live loss
// (juro, 2026-10-13/14) took it from 25 top-level keys to 12, dropping
// tipsHistory, other projects and user-scope mcpServers.
const MARKER = 'SYNTHETIC_MCP_ENV_VALUE_do_not_log'
function fullConfig(): Record<string, unknown> {
  const cfg: Record<string, unknown> = {
    numStartups: 41,
    tipsHistory: { a: 1, b: 2 },
    lastReleaseNotesSeen: '2.1.296',
    hasCompletedOnboarding: true,
    userID: 'u-synthetic',
    projects: {
      '/x/agents/a': { hasTrustDialogAccepted: true, lastCost: 1 },
      '/x/agents/a/repos/r': { hasTrustDialogAccepted: true },
    },
    mcpServers: { billingo: { command: 'node', env: { TOKEN: MARKER } } },
  }
  for (let i = 0; i < 18; i++) cfg[`cache${i}`] = i
  return cfg
}
function truncatedConfig(): Record<string, unknown> {
  return {
    numStartups: 1,
    hasCompletedOnboarding: true,
    userID: 'u-synthetic',
    migrationVersion: 7,
    projects: { '/x/agents/a': { hasTrustDialogAccepted: true, hasCompletedProjectOnboarding: true } },
  }
}

describe('decideClaudeJsonRestore', () => {
  it('keeps a file the exit write only grew', () => {
    const snap = fullConfig()
    const live = { ...fullConfig(), lastSessionId: 's2' }
    expect(decideClaudeJsonRestore(snap, JSON.stringify(live)).action).toBe('keep')
  })

  it('restores the pre-stop values when protected maps lost entries', () => {
    const d = decideClaudeJsonRestore(fullConfig(), JSON.stringify(truncatedConfig()))
    expect(d.action).toBe('restore')
    if (d.action !== 'restore') return
    expect(d.reason).toBe('lost-protected')
    expect(d.lost).toEqual(['projects', 'mcpServers'])
    // snapshot-first: the truncated reset value does not win
    expect(d.merged.numStartups).toBe(41)
    expect(d.merged.tipsHistory).toEqual({ a: 1, b: 2 })
    expect(Object.keys(d.merged.projects as object).sort()).toEqual(['/x/agents/a', '/x/agents/a/repos/r'])
    // live-only additions survive
    expect(d.merged.migrationVersion).toBe(7)
  })

  it('never adds an mcpServers entry the pre-stop file did not have (gate 4)', () => {
    const snap = fullConfig()
    const live = { ...truncatedConfig(), mcpServers: { addedLive: { command: 'x' } } }
    const d = decideClaudeJsonRestore(snap, JSON.stringify(live))
    expect(d.action).toBe('restore')
    if (d.action !== 'restore') return
    const names = Object.keys(d.merged.mcpServers as object).sort()
    expect(names).toEqual(['addedLive', 'billingo'])
    const allowed = new Set([...Object.keys(snap.mcpServers as object), ...Object.keys(live.mcpServers)])
    for (const n of names) expect(allowed.has(n)).toBe(true)
  })

  it('treats a halved top-level key count as damage even with protected maps intact', () => {
    const snap = fullConfig()
    const live = { projects: snap.projects, mcpServers: snap.mcpServers, userID: 'u' }
    const d = decideClaudeJsonRestore(snap, JSON.stringify(live))
    expect(d.action).toBe('restore')
    if (d.action === 'restore') expect(d.reason).toBe('lost-top-level')
  })

  it('restores the snapshot over an unparseable file', () => {
    const d = decideClaudeJsonRestore(fullConfig(), '{"numStartups": 1, "proj')
    expect(d.action).toBe('restore')
    if (d.action === 'restore') expect(d.merged).toEqual(fullConfig())
  })
})

describe('resolveOwnClaudeJsonPath (gate 2)', () => {
  let root: string
  beforeEach(() => { root = mkdtempSync(join(tmpdir(), 'cjguard-')) })
  afterEach(() => { rmSync(root, { recursive: true, force: true }) })

  function agent(n: string): string {
    const dir = join(root, 'agents', n)
    mkdirSync(join(dir, '.claude-config'), { recursive: true })
    writeFileSync(join(dir, '.claude-config', '.claude.json'), JSON.stringify(fullConfig()), { mode: 0o600 })
    return dir
  }

  it('returns the agent own isolated file', () => {
    const a = agent('a')
    expect(resolveOwnClaudeJsonPath(a)).toBe(join(a, '.claude-config', '.claude.json'))
  })

  it('refuses a symlinked .claude.json (shared root)', () => {
    const a = join(root, 'agents', 'a')
    mkdirSync(join(a, '.claude-config'), { recursive: true })
    writeFileSync(join(root, 'shared.json'), '{}')
    symlinkSync(join(root, 'shared.json'), join(a, '.claude-config', '.claude.json'))
    expect(resolveOwnClaudeJsonPath(a)).toBeNull()
  })

  it('refuses a .claude-config that is a symlink into another agent (negative)', () => {
    const b = agent('b')
    const a = join(root, 'agents', 'a')
    mkdirSync(a, { recursive: true })
    symlinkSync(join(b, '.claude-config'), join(a, '.claude-config'))
    expect(resolveOwnClaudeJsonPath(a)).toBeNull()
  })

  it('returns null when there is no isolated config (shared-root agent)', () => {
    const a = join(root, 'agents', 'a')
    mkdirSync(a, { recursive: true })
    expect(resolveOwnClaudeJsonPath(a)).toBeNull()
  })
})

describe('restoreClaudeJsonAfterStop (gates 1-3)', () => {
  let root: string
  let aDir: string
  let bDir: string
  let aFile: string
  let bFile: string
  beforeEach(() => {
    root = mkdtempSync(join(tmpdir(), 'cjguard-'))
    aDir = join(root, 'agents', 'a')
    bDir = join(root, 'agents', 'b')
    for (const d of [aDir, bDir]) {
      mkdirSync(join(d, '.claude-config'), { recursive: true })
      writeFileSync(join(d, '.claude-config', '.claude.json'), JSON.stringify(fullConfig(), null, 2), { mode: 0o600 })
      chmodSync(join(d, '.claude-config', '.claude.json'), 0o600)
    }
    aFile = join(aDir, '.claude-config', '.claude.json')
    bFile = join(bDir, '.claude-config', '.claude.json')
  })
  afterEach(() => { rmSync(root, { recursive: true, force: true }) })

  const deps = (over: Partial<{ exited: boolean; resolveTarget: () => string | null }> = {}) => ({
    waitForExit: async () => over.exited ?? true,
    resolveTarget: over.resolveTarget ?? (() => resolveOwnClaudeJsonPath(aDir)),
  })

  it('restores a truncated file, keeps the mode, leaves no extra file and touches no other agent', async () => {
    const snap = takeClaudeJsonSnapshot(aFile)!
    const bBefore = shaHex(readFileSync(bFile))
    writeFileSync(aFile, JSON.stringify(truncatedConfig()))
    const r = await restoreClaudeJsonAfterStop(snap, deps())
    expect(r.outcome).toBe('restored')
    const after = JSON.parse(readFileSync(aFile, 'utf-8'))
    expect(after.numStartups).toBe(41)
    expect(after.mcpServers.billingo.env.TOKEN).toBe(MARKER)
    expect(statSync(aFile).mode & 0o777).toBe(0o600)
    expect(readdirSync(join(aDir, '.claude-config'))).toEqual(['.claude.json'])
    expect(shaHex(readFileSync(bFile))).toBe(bBefore)
    // gate 1: the outcome (what gets logged) carries structure only
    expect(JSON.stringify(r)).not.toContain(MARKER)
    expect(JSON.stringify(r)).not.toContain('/x/agents')
  })

  it('does nothing while the old PID is still alive', async () => {
    const snap = takeClaudeJsonSnapshot(aFile)!
    const truncated = JSON.stringify(truncatedConfig())
    writeFileSync(aFile, truncated)
    const r = await restoreClaudeJsonAfterStop(snap, deps({ exited: false }))
    expect(r).toEqual({ outcome: 'skipped', reason: 'old-pid-still-alive' })
    expect(readFileSync(aFile, 'utf-8')).toBe(truncated)
  })

  it('does not overwrite a write that landed after the evaluation (compare-and-swap)', async () => {
    const snap = takeClaudeJsonSnapshot(aFile)!
    writeFileSync(aFile, JSON.stringify(truncatedConfig()))
    const newer = JSON.stringify({ written: 'by the new process' })
    const r = await restoreClaudeJsonAfterStop(snap, deps({
      resolveTarget: () => { writeFileSync(aFile, newer); return aFile },
    }))
    expect(r).toEqual({ outcome: 'skipped', reason: 'live-changed-before-swap' })
    expect(readFileSync(aFile, 'utf-8')).toBe(newer)
  })

  it('does not write when the target stopped resolving to the own file', async () => {
    const snap = takeClaudeJsonSnapshot(aFile)!
    const truncated = JSON.stringify(truncatedConfig())
    writeFileSync(aFile, truncated)
    const r = await restoreClaudeJsonAfterStop(snap, deps({ resolveTarget: () => null }))
    expect(r).toEqual({ outcome: 'skipped', reason: 'target-moved' })
    expect(readFileSync(aFile, 'utf-8')).toBe(truncated)
  })

  it('negative: a snapshot whose path is another agent file is refused by the own-path check', async () => {
    // A snapshot pointing at agent b while restoring for agent a: resolveTarget
    // (a's own path) does not match, so b's file is never written.
    const snapB = takeClaudeJsonSnapshot(bFile)!
    const truncated = JSON.stringify(truncatedConfig())
    writeFileSync(bFile, truncated)
    const r = await restoreClaudeJsonAfterStop(snapB, deps({ resolveTarget: () => resolveOwnClaudeJsonPath(aDir) }))
    expect(r).toEqual({ outcome: 'skipped', reason: 'target-moved' })
    expect(readFileSync(bFile, 'utf-8')).toBe(truncated)
  })

  it('caps the restored mode at 0600 even when the live file is wider (viktor L2)', async () => {
    const snap = takeClaudeJsonSnapshot(aFile)!
    writeFileSync(aFile, JSON.stringify(truncatedConfig()))
    chmodSync(aFile, 0o644)
    const r = await restoreClaudeJsonAfterStop(snap, deps())
    expect(r.outcome).toBe('restored')
    expect(statSync(aFile).mode & 0o777).toBe(0o600)
  })

  it('carries no content or non-schema key name in any outcome (gate 1, viktor L1)', async () => {
    // Sentinels in every place content could leak from: a top-level key name,
    // a project path, an mcpServers entry name and its env value.
    const SENT = 'SENTINEL_c4f1'
    const withSentinels = {
      ...fullConfig(),
      [`${SENT}_topkey`]: `${SENT}_topval`,
      projects: { ...(fullConfig().projects as object), [`/${SENT}_project`]: { hasTrustDialogAccepted: true } },
      mcpServers: { [`${SENT}_server`]: { command: 'node', env: { TOKEN: `${SENT}_env` } } },
    }
    const truncated = JSON.stringify(truncatedConfig())
    const forbidden = [SENT, 'numStartups', 'tipsHistory', 'userID', 'migrationVersion', 'cache0', 'hasCompletedOnboarding']
    const outcomes: unknown[] = []
    const reset = (content: string) => { writeFileSync(aFile, content); chmodSync(aFile, 0o600) }

    reset(JSON.stringify(withSentinels, null, 2))
    let snap = takeClaudeJsonSnapshot(aFile)!
    reset(truncated)
    outcomes.push(await restoreClaudeJsonAfterStop(snap, deps())) // restored, lost-protected

    reset(JSON.stringify(withSentinels, null, 2))
    snap = takeClaudeJsonSnapshot(aFile)!
    reset(JSON.stringify({ projects: withSentinels.projects, mcpServers: withSentinels.mcpServers }))
    outcomes.push(await restoreClaudeJsonAfterStop(snap, deps())) // restored, lost-top-level

    reset(JSON.stringify(withSentinels, null, 2))
    snap = takeClaudeJsonSnapshot(aFile)!
    reset('{"broken')
    outcomes.push(await restoreClaudeJsonAfterStop(snap, deps())) // restored, unparseable

    reset(JSON.stringify(withSentinels, null, 2))
    snap = takeClaudeJsonSnapshot(aFile)!
    reset(truncated)
    outcomes.push(await restoreClaudeJsonAfterStop(snap, deps({ exited: false })))
    outcomes.push(await restoreClaudeJsonAfterStop(snap, deps({ resolveTarget: () => null })))
    outcomes.push(await restoreClaudeJsonAfterStop(snap, deps({ resolveTarget: () => { writeFileSync(aFile, '{}'); return aFile } })))

    reset(JSON.stringify(withSentinels, null, 2))
    snap = takeClaudeJsonSnapshot(aFile)!
    reset(JSON.stringify({ ...withSentinels, lastSessionId: 's' }))
    outcomes.push(await restoreClaudeJsonAfterStop(snap, deps())) // intact

    // the stop path logs the snapshot shape on skip
    outcomes.push(describeShape(snap.bytes, snap.data, snap.sha))

    expect(outcomes.map((o) => (o as { outcome?: string }).outcome)).toEqual(
      ['restored', 'restored', 'restored', 'skipped', 'skipped', 'skipped', 'intact', undefined],
    )
    for (const o of outcomes) {
      const text = JSON.stringify(o)
      for (const f of forbidden) expect(text).not.toContain(f)
    }
  })

  it('reports intact when the exit write kept every key', async () => {
    const snap = takeClaudeJsonSnapshot(aFile)!
    writeFileSync(aFile, JSON.stringify({ ...fullConfig(), lastSessionId: 's' }))
    expect(await restoreClaudeJsonAfterStop(snap, deps())).toEqual({ outcome: 'intact' })
  })
})

describe('waitForPidExit', () => {
  it('returns true once the pid is gone', async () => {
    let calls = 0
    expect(await waitForPidExit(1, 1000, () => ++calls < 3, async () => {})).toBe(true)
    expect(calls).toBe(3)
  })

  it('gives up after the timeout', async () => {
    expect(await waitForPidExit(1, 0, () => true, async () => {})).toBe(false)
  })
})
