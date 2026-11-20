// Card 759161e3 (Viktor 48285): the keychain-write gate reaches every sub-agent, not only the main agent. The hook's
// own behaviour is tested in scripts/hooks/keychain-write-gate_test.py; here: the wiring, and that the command the
// scaffold writes really blocks when Claude Code runs it.
import { describe, it, expect, afterEach } from 'vitest'
import { spawnSync } from 'node:child_process'
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  agentGetsKeychainWriteGate,
  ensureKeychainWriteGate,
  injectKeychainWriteGate,
} from '../web/agent-scaffold.js'
import { MAIN_AGENT_ID, PROJECT_ROOT } from '../config.js'

type Entry = { matcher?: string; hooks: { command: string; timeout?: number }[] }
const ptu = (s: { hooks?: { PreToolUse?: Entry[] } }): Entry[] => s.hooks?.PreToolUse ?? []
const mine = (entries: Entry[]) => entries.filter((e) => JSON.stringify(e).includes('keychain-write-gate.py'))
const firesFor = (entries: Entry[], tool: string) =>
  mine(entries).some((e) => new RegExp(`^(?:${e.matcher ?? '.*'})$`).test(tool))

// Run a hook command the way Claude Code does: a shell, the PreToolUse JSON on stdin.
function runHook(command: string, bashCommand: string): number {
  const p = spawnSync('bash', ['-c', command], {
    input: JSON.stringify({ tool_name: 'Bash', tool_input: { command: bashCommand } }),
    encoding: 'utf-8',
    env: { PATH: process.env.PATH ?? '/usr/bin:/bin', CLAUDE_PROJECT_DIR: PROJECT_ROOT },
    timeout: 20000,
  })
  return p.status ?? -1
}

describe('keychain-write gate wiring (759161e3)', () => {
  const TEST_AGENT = 'keychain-write-gate-test-agent'
  const testAgentDir = join(PROJECT_ROOT, 'agents', TEST_AGENT)
  const settingsPath = join(testAgentDir, '.claude', 'settings.json')

  afterEach(() => {
    rmSync(testAgentDir, { recursive: true, force: true })
  })

  it('every sub-agent gets it, the main agent does not (it has the project-settings hook)', () => {
    expect(agentGetsKeychainWriteGate(TEST_AGENT)).toBe(true)
    expect(agentGetsKeychainWriteGate(MAIN_AGENT_ID)).toBe(false)
  })

  it('inject writes one Bash entry, idempotently, and drops a stale one', () => {
    const settings = { hooks: { PreToolUse: [
      { matcher: 'Read', hooks: [{ command: 'python3 /x/other-hook.py' }] },
      { matcher: 'Edit', hooks: [{ command: 'python3 /old/keychain-write-gate.py' }] },
    ] } }
    injectKeychainWriteGate(settings as unknown as Record<string, unknown>)
    injectKeychainWriteGate(settings as unknown as Record<string, unknown>)
    const entries = ptu(settings)
    expect(mine(entries)).toHaveLength(1)
    expect(mine(entries)[0].matcher).toBe('Bash')
    expect(mine(entries)[0].hooks[0].timeout).toBe(10)
    expect(firesFor(entries, 'Bash')).toBe(true)
    expect(entries.some((e) => JSON.stringify(e).includes('other-hook.py'))).toBe(true)
  })

  it('the written command blocks a login-keychain write and allows a harmless security call (run as Claude Code does)', () => {
    const settings = {}
    injectKeychainWriteGate(settings)
    const command = mine(ptu(settings))[0].hooks[0].command
    expect(runHook(command, 'security delete-generic-password -s synthetic-item')).toBe(2)
    expect(runHook(command, 'security add-generic-password -a x -s synthetic-item -w x t.keychain-db')).toBe(2)
    expect(runHook(command, 'security list-keychains')).toBe(0)
    expect(runHook(command, 'git status')).toBe(0)
  })

  it('ensureKeychainWriteGate wires an existing sub-agent once, replaces a wrong matcher, then settles', () => {
    mkdirSync(join(testAgentDir, '.claude'), { recursive: true })
    const wrong = { matcher: 'Read', hooks: [{ type: 'command', command: `python3 "${join(PROJECT_ROOT, 'scripts', 'hooks', 'keychain-write-gate.py')}"`, timeout: 10 }] }
    writeFileSync(settingsPath, JSON.stringify({ hooks: { PreToolUse: [wrong] } }, null, 2))
    expect(ensureKeychainWriteGate(TEST_AGENT)).toBe(true)
    expect(ensureKeychainWriteGate(TEST_AGENT)).toBe(false)
    const entries = ptu(JSON.parse(readFileSync(settingsPath, 'utf-8')))
    expect(mine(entries)).toHaveLength(1)
    expect(firesFor(entries, 'Bash')).toBe(true)
  })

  it('ensureKeychainWriteGate wires a sub-agent that has settings but no hooks', () => {
    mkdirSync(join(testAgentDir, '.claude'), { recursive: true })
    writeFileSync(settingsPath, JSON.stringify({ permissions: { allow: [] } }, null, 2))
    expect(ensureKeychainWriteGate(TEST_AGENT)).toBe(true)
    const s = JSON.parse(readFileSync(settingsPath, 'utf-8'))
    expect(s.permissions).toEqual({ allow: [] })
    expect(firesFor(ptu(s), 'Bash')).toBe(true)
  })

  it('leaves the main agent and a never-spawned agent alone', () => {
    expect(ensureKeychainWriteGate(MAIN_AGENT_ID)).toBe(false)
    expect(ensureKeychainWriteGate(TEST_AGENT)).toBe(false)
  })

  it('the spawn path and the boot migration both call it', () => {
    const scaffold = readFileSync(join(PROJECT_ROOT, 'src', 'web', 'agent-scaffold.ts'), 'utf-8')
    expect(scaffold).toContain('if (agentGetsKeychainWriteGate(name)) injectKeychainWriteGate(existing)')
    const web = readFileSync(join(PROJECT_ROOT, 'src', 'web.ts'), 'utf-8')
    expect(web).toMatch(/if \(ensureKeychainWriteGate\(agentName\)\) keychainWritePatched\.push\(agentName\)/)
  })

  it('the main agent carries it in the repo-shipped project settings, on Bash', () => {
    const settings = JSON.parse(readFileSync(join(PROJECT_ROOT, '.claude', 'settings.json'), 'utf-8'))
    expect(firesFor(ptu(settings), 'Bash')).toBe(true)
  })
})
