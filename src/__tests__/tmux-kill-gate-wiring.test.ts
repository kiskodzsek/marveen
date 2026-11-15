// Card ad7edaec (Klodel 43120, Viktor 43117): the tmux kill gate reaches every sub-agent, and the main agent through
// the repo-shipped project settings. The hook's own behaviour is tested in scripts/hooks/tmux-kill-gate_test.py;
// here: the wiring, and that the command the scaffold writes really blocks when Claude Code runs it -- with $TMUX on
// the live socket shape and TMUX_TMPDIR elsewhere, the 2026-11-15 16:45 case.
import { describe, it, expect, afterEach } from 'vitest'
import { spawnSync } from 'node:child_process'
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  agentGetsTmuxKillGate,
  ensureTmuxKillGate,
  injectTmuxKillGate,
} from '../web/agent-scaffold.js'
import { MAIN_AGENT_ID, PROJECT_ROOT } from '../config.js'

type Entry = { matcher?: string; hooks: { command: string; timeout?: number }[] }
const ptu = (s: { hooks?: { PreToolUse?: Entry[] } }): Entry[] => s.hooks?.PreToolUse ?? []
const mine = (entries: Entry[]) => entries.filter((e) => JSON.stringify(e).includes('tmux-kill-gate.py'))
const firesFor = (entries: Entry[], tool: string) =>
  mine(entries).some((e) => new RegExp(`^(?:${e.matcher ?? '.*'})$`).test(tool))

const UID = process.getuid ? process.getuid() : 501

// Run a hook command the way Claude Code does: a shell, the PreToolUse JSON on stdin, inside a tmux session.
function runHook(command: string, bashCommand: string): number {
  const p = spawnSync('bash', ['-c', command], {
    input: JSON.stringify({ tool_name: 'Bash', tool_input: { command: bashCommand } }),
    encoding: 'utf-8',
    env: {
      PATH: process.env.PATH ?? '/usr/bin:/bin',
      CLAUDE_PROJECT_DIR: PROJECT_ROOT,
      TMUX: `/private/tmp/tmux-${UID}/default,98216,0`,
      TMUX_TMPDIR: '/private/tmp/somewhere-else',
    },
    timeout: 20000,
  })
  return p.status ?? -1
}

describe('tmux kill gate wiring (ad7edaec)', () => {
  const TEST_AGENT = 'tmux-kill-gate-test-agent'
  const testAgentDir = join(PROJECT_ROOT, 'agents', TEST_AGENT)
  const settingsPath = join(testAgentDir, '.claude', 'settings.json')

  afterEach(() => {
    rmSync(testAgentDir, { recursive: true, force: true })
  })

  it('every sub-agent gets it, the main agent does not (it has the project-settings hook)', () => {
    expect(agentGetsTmuxKillGate(TEST_AGENT)).toBe(true)
    expect(agentGetsTmuxKillGate(MAIN_AGENT_ID)).toBe(false)
  })

  it('inject writes one Bash entry, idempotently, and drops a stale one', () => {
    const settings = { hooks: { PreToolUse: [
      { matcher: 'Read', hooks: [{ command: 'python3 /x/other-hook.py' }] },
      { matcher: 'Edit', hooks: [{ command: 'python3 /old/tmux-kill-gate.py' }] },
    ] } }
    injectTmuxKillGate(settings as unknown as Record<string, unknown>)
    injectTmuxKillGate(settings as unknown as Record<string, unknown>)
    const entries = ptu(settings)
    expect(mine(entries)).toHaveLength(1)
    expect(mine(entries)[0].matcher).toBe('Bash')
    expect(mine(entries)[0].hooks[0].timeout).toBe(10)
    expect(firesFor(entries, 'Bash')).toBe(true)
    expect(entries.some((e) => JSON.stringify(e).includes('other-hook.py'))).toBe(true)
  })

  it('the written command blocks the incident shape and allows an isolated server (run as Claude Code does)', () => {
    const settings = {}
    injectTmuxKillGate(settings)
    const command = mine(ptu(settings))[0].hooks[0].command
    expect(runHook(command, 'TMUX_TMPDIR=/private/tmp/somewhere-else tmux kill-server')).toBe(2)
    expect(runHook(command, 'tmux kill-session -t agent-dave')).toBe(2)
    expect(runHook(command, 'tmux -L kernelprobe kill-server')).toBe(0)
    expect(runHook(command, 'tmux capture-pane -p -t agent-dave')).toBe(0)
    expect(runHook(command, 'git status')).toBe(0)
  })

  it('ensureTmuxKillGate wires an existing sub-agent once, replaces a wrong matcher, then settles', () => {
    mkdirSync(join(testAgentDir, '.claude'), { recursive: true })
    const wrong = { matcher: 'Read', hooks: [{ type: 'command', command: `python3 "${join(PROJECT_ROOT, 'scripts', 'hooks', 'tmux-kill-gate.py')}"`, timeout: 10 }] }
    writeFileSync(settingsPath, JSON.stringify({ hooks: { PreToolUse: [wrong] } }, null, 2))
    expect(ensureTmuxKillGate(TEST_AGENT)).toBe(true)
    expect(ensureTmuxKillGate(TEST_AGENT)).toBe(false)
    const entries = ptu(JSON.parse(readFileSync(settingsPath, 'utf-8')))
    expect(mine(entries)).toHaveLength(1)
    expect(firesFor(entries, 'Bash')).toBe(true)
  })

  it('ensureTmuxKillGate writes back an entry taken out of a sub-agent settings file', () => {
    mkdirSync(join(testAgentDir, '.claude'), { recursive: true })
    writeFileSync(settingsPath, JSON.stringify({ permissions: { allow: [] } }, null, 2))
    expect(ensureTmuxKillGate(TEST_AGENT)).toBe(true)
    const s = JSON.parse(readFileSync(settingsPath, 'utf-8'))
    expect(s.permissions).toEqual({ allow: [] })
    expect(firesFor(ptu(s), 'Bash')).toBe(true)
  })

  it('leaves the main agent and a never-spawned agent alone', () => {
    expect(ensureTmuxKillGate(MAIN_AGENT_ID)).toBe(false)
    expect(ensureTmuxKillGate(TEST_AGENT)).toBe(false)
  })

  it('the spawn path and the boot migration both call it', () => {
    const scaffold = readFileSync(join(PROJECT_ROOT, 'src', 'web', 'agent-scaffold.ts'), 'utf-8')
    expect(scaffold).toContain('if (agentGetsTmuxKillGate(name)) injectTmuxKillGate(existing)')
    const web = readFileSync(join(PROJECT_ROOT, 'src', 'web.ts'), 'utf-8')
    expect(web).toMatch(/if \(ensureTmuxKillGate\(agentName\)\) tmuxKillGatePatched\.push\(agentName\)/)
  })

  it('the main agent carries it in the repo-shipped project settings, on Bash', () => {
    const settings = JSON.parse(readFileSync(join(PROJECT_ROOT, '.claude', 'settings.json'), 'utf-8'))
    expect(firesFor(ptu(settings), 'Bash')).toBe(true)
  })
})
