// Card d4180ec8 (Viktor 42916 INFO 3): "disableAllHooks": true in a sub-agent's settings turns off every hook,
// the gates included, while the ensure* checks still see the gate entries as wired. Measured on Claude Code 2.1.325:
// it works from the project settings.json, settings.local.json and the config dir's settings.json. The scaffold
// removes it from the files that are the agent's own, at spawn and at every dashboard start.
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  agentHookKillSwitchFiles,
  agentSettingsPath,
  ensureNoHookKillSwitch,
  writeAgentSettingsFromProfile,
} from '../web/agent-scaffold.js'
import { loadProfileTemplate } from '../web/profiles.js'
import { AGENTS_BASE_DIR } from '../web/agent-config.js'
import { MAIN_AGENT_ID, PROJECT_ROOT } from '../config.js'

const TEST_AGENT = 'hook-killswitch-probe'
const root = join(AGENTS_BASE_DIR, TEST_AGENT)
const cfg = join(root, '.claude-config')
const project = agentSettingsPath(TEST_AGENT)
const local = join(root, '.claude', 'settings.local.json')
const user = join(cfg, 'settings.json')
let outside = ''

function cleanup(): void {
  if (existsSync(root)) {
    // Only the throwaway directory this test created: a live agent dir carries a CLAUDE.md or a HANDOFF.md.
    if (existsSync(join(root, 'CLAUDE.md')) || existsSync(join(root, 'HANDOFF.md'))) {
      throw new Error(`refusing: ${root} looks like a live agent, not a test checkout`)
    }
    rmSync(root, { recursive: true, force: true })
  }
  if (outside) rmSync(outside, { recursive: true, force: true })
}
beforeEach(() => {
  cleanup()
  mkdirSync(join(root, '.claude'), { recursive: true })
  mkdirSync(cfg, { recursive: true })
  outside = mkdtempSync(join(tmpdir(), 'killswitch-outside-'))
})
afterEach(cleanup)

const put = (path: string, v: unknown) => writeFileSync(path, JSON.stringify(v, null, 2))
const read = (path: string) => JSON.parse(readFileSync(path, 'utf-8')) as Record<string, unknown>

describe('which files count', () => {
  it('a sub-agent: project settings, settings.local.json and its own config dir', () => {
    expect(agentHookKillSwitchFiles(TEST_AGENT, cfg)).toEqual([project, local, user])
  })

  it('a config dir outside the agent folder (shared plan dir, ~/.claude) is not the agent\'s to rewrite', () => {
    expect(agentHookKillSwitchFiles(TEST_AGENT, outside)).toEqual([project, local])
    expect(agentHookKillSwitchFiles(TEST_AGENT, null)).toEqual([project, local])
    expect(agentHookKillSwitchFiles(TEST_AGENT, root + '-other/.claude-config')).toEqual([project, local])
  })

  it('the main agent: none (its settings are the owner\'s)', () => {
    expect(agentHookKillSwitchFiles(MAIN_AGENT_ID, cfg)).toEqual([])
    expect(ensureNoHookKillSwitch(MAIN_AGENT_ID, cfg)).toEqual([])
  })
})

describe('ensureNoHookKillSwitch', () => {
  it('removes the key from all three files, keeps every other key and the file mode', () => {
    put(project, { hooks: { PreToolUse: [] }, permissions: { allow: ['x'] }, disableAllHooks: true })
    put(local, { disableAllHooks: true, env: { A: '1' } })
    put(user, { disableAllHooks: true, theme: 'dark' })
    chmodSync(user, 0o600)
    expect(ensureNoHookKillSwitch(TEST_AGENT, cfg)).toEqual([
      { path: project, result: 'removed' },
      { path: local, result: 'removed' },
      { path: user, result: 'removed' },
    ])
    expect(read(project)).toEqual({ hooks: { PreToolUse: [] }, permissions: { allow: ['x'] } })
    expect(read(local)).toEqual({ env: { A: '1' } })
    expect(read(user)).toEqual({ theme: 'dark' })
    expect(statSync(user).mode & 0o777).toBe(0o600)
    expect(ensureNoHookKillSwitch(TEST_AGENT, cfg)).toEqual([])
  })

  it('also removes a false or non-boolean value (a key that does nothing is not kept either)', () => {
    put(project, { disableAllHooks: false })
    put(local, { disableAllHooks: 'true' })
    expect(ensureNoHookKillSwitch(TEST_AGENT, cfg).map((r) => r.result)).toEqual(['removed', 'removed'])
    expect(read(project)).toEqual({})
    expect(read(local)).toEqual({})
  })

  it('does not write a file without the key (bytes unchanged), nor one that only mentions it in a value', () => {
    const text = JSON.stringify({ hooks: {}, note: 'disableAllHooks is not set here' }, null, 4)
    writeFileSync(project, text)
    expect(ensureNoHookKillSwitch(TEST_AGENT, cfg)).toEqual([])
    expect(readFileSync(project, 'utf-8')).toBe(text)
  })

  it('a symlink out of the agent folder is reported, and its target is never written', () => {
    const target = join(outside, 'settings.json')
    put(target, { disableAllHooks: true })
    symlinkSync(target, local)
    expect(ensureNoHookKillSwitch(TEST_AGENT, cfg)).toEqual([{ path: local, result: 'outside' }])
    expect(read(target)).toEqual({ disableAllHooks: true })
  })

  it('a file that is not a JSON object is reported, and not rewritten', () => {
    writeFileSync(project, '{ "disableAllHooks": true, ')
    put(local, ['disableAllHooks'])
    expect(ensureNoHookKillSwitch(TEST_AGENT, cfg)).toEqual([
      { path: project, result: 'unreadable' },
      { path: local, result: 'unreadable' },
    ])
    expect(readFileSync(project, 'utf-8')).toBe('{ "disableAllHooks": true, ')
  })
})

describe('wiring', () => {
  it('a spawn writes the settings without the key', () => {
    put(project, { disableAllHooks: true })
    writeAgentSettingsFromProfile(TEST_AGENT, loadProfileTemplate('default'))
    expect(read(project)).not.toHaveProperty('disableAllHooks')
    expect(read(project)).toHaveProperty('permissions')
  })

  it('a spawn also clears settings.local.json', () => {
    put(local, { disableAllHooks: true })
    writeAgentSettingsFromProfile(TEST_AGENT, loadProfileTemplate('default'))
    expect(read(local)).toEqual({})
  })

  it('the dashboard start calls it for every agent and logs what it did', () => {
    const web = readFileSync(join(PROJECT_ROOT, 'src', 'web.ts'), 'utf-8')
    expect(web).toContain('ensureNoHookKillSwitch(agentName)')
    expect(web).toMatch(/if \(killSwitch\.length\) logger\.warn/)
  })
})
