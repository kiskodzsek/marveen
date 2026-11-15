// Card 11c4a5fe (Klodel 42872, Viktor 42810): the prod-tree write gate reaches every sub-agent through its own
// settings (no root-owned managed settings). The gate's behaviour is tested in
// scripts/hooks/prod-tree-write-gate_test.py; here: the wiring, and that the command the scaffold writes really
// denies a sub-agent's write into the checkout when Claude Code runs it.
import { describe, it, expect, afterEach } from 'vitest'
import { spawnSync } from 'node:child_process'
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  agentGetsProdTreeWriteGate,
  ensureProdTreeWriteGate,
  injectProdTreeWriteGate,
} from '../web/agent-scaffold.js'
import { MAIN_AGENT_ID, PROJECT_ROOT } from '../config.js'

const MATCHER = 'Write|Edit|MultiEdit|NotebookEdit|Bash'
type Entry = { matcher?: string; hooks: { command: string; timeout?: number }[] }
const ptu = (s: { hooks?: { PreToolUse?: Entry[] } }): Entry[] => s.hooks?.PreToolUse ?? []
const mine = (entries: Entry[]) => entries.filter((e) => JSON.stringify(e).includes('prod-tree-write-gate.py'))
const firesFor = (entries: Entry[], tool: string) =>
  mine(entries).some((e) => new RegExp(`^(?:${e.matcher ?? '.*'})$`).test(tool))

// Run a hook command the way Claude Code does: a shell, the PreToolUse JSON on stdin. -> [exit code, stdout]
function runHook(command: string, payload: Record<string, unknown>): [number, string] {
  const p = spawnSync('bash', ['-c', command], {
    input: JSON.stringify(payload),
    encoding: 'utf-8',
    env: { PATH: process.env.PATH ?? '/usr/bin:/bin', CLAUDE_PROJECT_DIR: PROJECT_ROOT },
    timeout: 20000,
  })
  return [p.status ?? -1, p.stdout ?? '']
}

describe('prod-tree write gate wiring (11c4a5fe)', () => {
  const TEST_AGENT = 'prod-tree-gate-test-agent'
  const testAgentDir = join(PROJECT_ROOT, 'agents', TEST_AGENT)
  const settingsPath = join(testAgentDir, '.claude', 'settings.json')

  afterEach(() => {
    rmSync(testAgentDir, { recursive: true, force: true })
  })

  it('every sub-agent gets it, the main agent does not', () => {
    expect(agentGetsProdTreeWriteGate(TEST_AGENT)).toBe(true)
    expect(agentGetsProdTreeWriteGate(MAIN_AGENT_ID)).toBe(false)
  })

  it('inject writes one entry on the write tools and Bash, idempotently, and drops a stale one', () => {
    const settings = { hooks: { PreToolUse: [
      { matcher: 'Read', hooks: [{ command: 'python3 /x/other-hook.py' }] },
      { matcher: 'Bash', hooks: [{ command: 'python3 /old/prod-tree-write-gate.py' }] },
    ] } }
    injectProdTreeWriteGate(settings as unknown as Record<string, unknown>)
    injectProdTreeWriteGate(settings as unknown as Record<string, unknown>)
    const entries = ptu(settings)
    expect(mine(entries)).toHaveLength(1)
    expect(mine(entries)[0].matcher).toBe(MATCHER)
    expect(mine(entries)[0].hooks[0].timeout).toBe(15)
    for (const tool of ['Write', 'Edit', 'MultiEdit', 'NotebookEdit', 'Bash']) expect(firesFor(entries, tool)).toBe(true)
    expect(firesFor(entries, 'Read')).toBe(false)
    expect(entries.some((e) => JSON.stringify(e).includes('other-hook.py'))).toBe(true)
  })

  it('the written command denies a sub-agent write into the checkout and lets the main agent through', () => {
    const settings = {}
    injectProdTreeWriteGate(settings)
    const command = mine(ptu(settings))[0].hooks[0].command
    const sub = join(PROJECT_ROOT, 'agents', TEST_AGENT, '.claude-config', 'projects', 'x', 's.jsonl')
    const write = (tp: string, path: string) => ({
      tool_name: 'Write', tool_input: { file_path: path }, cwd: PROJECT_ROOT, transcript_path: tp,
    })
    const [rc, out] = runHook(command, write(sub, join(PROJECT_ROOT, 'scripts', 'hooks', 'synthetic.py')))
    expect(rc).toBe(0)
    expect(JSON.parse(out).hookSpecificOutput.permissionDecision).toBe('deny')
    expect(out).toContain('worktree + PR')
    expect(runHook(command, write(sub, join(PROJECT_ROOT, 'agents', TEST_AGENT, 'notes.md')))).toEqual([0, ''])
    expect(runHook(command, write('/nonexistent/.claude/projects/x/s.jsonl',
      join(PROJECT_ROOT, 'scripts', 'hooks', 'synthetic.py')))).toEqual([0, ''])
  })

  it('ensureProdTreeWriteGate wires an existing sub-agent once, replaces a wrong matcher, then settles', () => {
    mkdirSync(join(testAgentDir, '.claude'), { recursive: true })
    const wrong = { matcher: 'Bash', hooks: [{ type: 'command', command: `python3 "${join(PROJECT_ROOT, 'scripts', 'hooks', 'prod-tree-write-gate.py')}"`, timeout: 15 }] }
    writeFileSync(settingsPath, JSON.stringify({ hooks: { PreToolUse: [wrong] } }, null, 2))
    expect(ensureProdTreeWriteGate(TEST_AGENT)).toBe(true)
    expect(ensureProdTreeWriteGate(TEST_AGENT)).toBe(false)
    const entries = ptu(JSON.parse(readFileSync(settingsPath, 'utf-8')))
    expect(mine(entries)).toHaveLength(1)
    expect(firesFor(entries, 'Edit')).toBe(true)
  })

  it('ensureProdTreeWriteGate writes back an entry the agent took out of its own settings', () => {
    mkdirSync(join(testAgentDir, '.claude'), { recursive: true })
    writeFileSync(settingsPath, JSON.stringify({ permissions: { allow: [] } }, null, 2))
    expect(ensureProdTreeWriteGate(TEST_AGENT)).toBe(true)
    const s = JSON.parse(readFileSync(settingsPath, 'utf-8'))
    expect(s.permissions).toEqual({ allow: [] })
    expect(firesFor(ptu(s), 'Write')).toBe(true)
    s.hooks.PreToolUse = ptu(s).filter((e) => !JSON.stringify(e).includes('prod-tree-write-gate.py'))
    writeFileSync(settingsPath, JSON.stringify(s, null, 2))
    expect(ensureProdTreeWriteGate(TEST_AGENT)).toBe(true)
    expect(firesFor(ptu(JSON.parse(readFileSync(settingsPath, 'utf-8'))), 'Write')).toBe(true)
  })

  it('leaves the main agent and a never-spawned agent alone', () => {
    expect(ensureProdTreeWriteGate(MAIN_AGENT_ID)).toBe(false)
    expect(ensureProdTreeWriteGate(TEST_AGENT)).toBe(false)
  })

  it('the spawn path and the boot migration both call it', () => {
    const scaffold = readFileSync(join(PROJECT_ROOT, 'src', 'web', 'agent-scaffold.ts'), 'utf-8')
    expect(scaffold).toContain('if (agentGetsProdTreeWriteGate(name)) injectProdTreeWriteGate(existing)')
    const web = readFileSync(join(PROJECT_ROOT, 'src', 'web.ts'), 'utf-8')
    expect(web).toMatch(/if \(ensureProdTreeWriteGate\(agentName\)\) prodTreeGatePatched\.push\(agentName\)/)
  })
})
