// Card b3ae9523 (retro 2026-11-20, Klodel 48876; logic Viktor 48985): the commit chain guard reaches every sub-agent,
// not only Kernel's own settings. The hook's own behaviour is tested in scripts/hooks/commit-chain-guard_test.py;
// here: the wiring, and that the command the scaffold writes really blocks when Claude Code runs it.
import { describe, it, expect, afterEach } from 'vitest'
import { spawnSync } from 'node:child_process'
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  agentGetsCommitChainGuard,
  ensureCommitChainGuard,
  injectCommitChainGuard,
} from '../web/agent-scaffold.js'
import { MAIN_AGENT_ID, PROJECT_ROOT } from '../config.js'

type Entry = { matcher?: string; hooks: { command: string; timeout?: number }[] }
const ptu = (s: { hooks?: { PreToolUse?: Entry[] } }): Entry[] => s.hooks?.PreToolUse ?? []
const mine = (entries: Entry[]) => entries.filter((e) => JSON.stringify(e).includes('commit-chain-guard.py'))
const firesFor = (entries: Entry[], tool: string) =>
  mine(entries).some((e) => new RegExp(`^(?:${e.matcher ?? '.*'})$`).test(tool))

describe('commit chain guard wiring (b3ae9523)', () => {
  const TEST_AGENT = 'commit-chain-guard-test-agent'
  const testAgentDir = join(PROJECT_ROOT, 'agents', TEST_AGENT)
  const settingsPath = join(testAgentDir, '.claude', 'settings.json')

  // Run a hook command the way Claude Code does: a shell, the PreToolUse JSON on stdin. Nothing in bashCommand runs.
  function runHook(command: string, bashCommand: string): number {
    const payload = { tool_name: 'Bash', tool_input: { command: bashCommand }, cwd: testAgentDir }
    const p = spawnSync('bash', ['-c', command], {
      input: JSON.stringify(payload),
      encoding: 'utf-8',
      env: { PATH: process.env.PATH ?? '/usr/bin:/bin', CLAUDE_PROJECT_DIR: PROJECT_ROOT },
      timeout: 20000,
    })
    return p.status ?? -1
  }

  afterEach(() => {
    rmSync(testAgentDir, { recursive: true, force: true })
  })

  it('every sub-agent gets it, the main agent does not (it does not commit)', () => {
    expect(agentGetsCommitChainGuard(TEST_AGENT)).toBe(true)
    expect(agentGetsCommitChainGuard('dave')).toBe(true)
    expect(agentGetsCommitChainGuard(MAIN_AGENT_ID)).toBe(false)
  })

  it('inject writes one Bash entry, idempotently, and replaces Kernel\'s own copy and a stale one', () => {
    const settings = { hooks: { PreToolUse: [
      { matcher: 'Read', hooks: [{ command: 'python3 /x/other-hook.py' }] },
      { matcher: 'Bash', hooks: [{ command: 'python3 -I /Users/klodel/marveen/agents/kernel/tools/hooks/commit-chain-guard.py' }] },
      { matcher: 'Edit', hooks: [{ command: 'python3 /old/commit-chain-guard.py' }] },
    ] } }
    injectCommitChainGuard(settings as unknown as Record<string, unknown>)
    injectCommitChainGuard(settings as unknown as Record<string, unknown>)
    const entries = ptu(settings)
    expect(mine(entries)).toHaveLength(1)
    expect(mine(entries)[0].matcher).toBe('Bash')
    expect(mine(entries)[0].hooks[0].timeout).toBe(10)
    expect(mine(entries)[0].hooks[0].command).toContain(join(PROJECT_ROOT, 'scripts', 'hooks', 'commit-chain-guard.py'))
    expect(firesFor(entries, 'Bash')).toBe(true)
    expect(entries.some((e) => JSON.stringify(e).includes('other-hook.py'))).toBe(true)
  })

  it('the written command blocks a commit behind ";" or a piped test, and allows an && chain (run as Claude Code does)', () => {
    const settings = {}
    injectCommitChainGuard(settings)
    const command = mine(ptu(settings))[0].hooks[0].command
    expect(runHook(command, 'npx vitest run; git commit -m x')).toBe(2)
    expect(runHook(command, 'npm test | tail -3 && git commit -m x')).toBe(2)
    expect(runHook(command, 'python3 -I scripts/hooks/x_test.py\ngit commit -m x')).toBe(2)
    expect(runHook(command, 'npx vitest run && git commit -m x')).toBe(0)
    expect(runHook(command, 'git commit -m "npm test; fine"')).toBe(0)
    expect(runHook(command, 'git status')).toBe(0)
  })

  it('ensureCommitChainGuard wires an existing sub-agent once, replaces a wrong matcher, then settles', () => {
    mkdirSync(join(testAgentDir, '.claude'), { recursive: true })
    const wrong = { matcher: 'Read', hooks: [{ type: 'command', command: `python3 "${join(PROJECT_ROOT, 'scripts', 'hooks', 'commit-chain-guard.py')}"`, timeout: 10 }] }
    writeFileSync(settingsPath, JSON.stringify({ hooks: { PreToolUse: [wrong] } }, null, 2))
    expect(ensureCommitChainGuard(TEST_AGENT)).toBe(true)
    expect(ensureCommitChainGuard(TEST_AGENT)).toBe(false)
    const entries = ptu(JSON.parse(readFileSync(settingsPath, 'utf-8')))
    expect(mine(entries)).toHaveLength(1)
    expect(firesFor(entries, 'Bash')).toBe(true)
  })

  it('ensureCommitChainGuard wires a sub-agent that has settings but no hooks', () => {
    mkdirSync(join(testAgentDir, '.claude'), { recursive: true })
    writeFileSync(settingsPath, JSON.stringify({ permissions: { allow: [] } }, null, 2))
    expect(ensureCommitChainGuard(TEST_AGENT)).toBe(true)
    const s = JSON.parse(readFileSync(settingsPath, 'utf-8'))
    expect(s.permissions).toEqual({ allow: [] })
    expect(firesFor(ptu(s), 'Bash')).toBe(true)
  })

  it('leaves the main agent and a never-spawned agent alone', () => {
    expect(ensureCommitChainGuard(MAIN_AGENT_ID)).toBe(false)
    expect(ensureCommitChainGuard(TEST_AGENT)).toBe(false)
  })

  it('the spawn path and the boot migration both call it', () => {
    const scaffold = readFileSync(join(PROJECT_ROOT, 'src', 'web', 'agent-scaffold.ts'), 'utf-8')
    expect(scaffold).toContain('if (agentGetsCommitChainGuard(name)) injectCommitChainGuard(existing)')
    const web = readFileSync(join(PROJECT_ROOT, 'src', 'web.ts'), 'utf-8')
    expect(web).toMatch(/if \(ensureCommitChainGuard\(agentName\)\) commitChainPatched\.push\(agentName\)/)
  })
})
