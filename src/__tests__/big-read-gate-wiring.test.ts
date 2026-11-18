// Card b073a7e3 (Klodel 46838, 46967): the big-read gate reaches every sub-agent (not the main agent: its project
// settings are the owner's call). The hook's own behaviour is tested in scripts/hooks/big-read-gate_test.py; here:
// the wiring, and that the command the scaffold writes really stops a whole read of a big file when Claude Code runs
// it, and lets an explicit limit through.
import { describe, it, expect, afterEach, beforeAll, afterAll } from 'vitest'
import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import {
  agentGetsBigReadGate,
  ensureBigReadGate,
  injectBigReadGate,
} from '../web/agent-scaffold.js'
import { MAIN_AGENT_ID, PROJECT_ROOT } from '../config.js'

type Entry = { matcher?: string; hooks: { command: string; timeout?: number }[] }
const ptu = (s: { hooks?: { PreToolUse?: Entry[] } }): Entry[] => s.hooks?.PreToolUse ?? []
const mine = (entries: Entry[]) => entries.filter((e) => JSON.stringify(e).includes('big-read-gate.py'))
const firesFor = (entries: Entry[], tool: string) =>
  mine(entries).some((e) => new RegExp(`^(?:${e.matcher ?? '.*'})$`).test(tool))

let dir = ''
let big = ''
let small = ''

beforeAll(() => {
  mkdirSync(join(homedir(), '.cache'), { recursive: true })
  dir = mkdtempSync(join(homedir(), '.cache', 'big-read-gate-wiring-'))
  big = join(dir, 'big.ts')
  small = join(dir, 'small.ts')
  writeFileSync(big, 'x'.repeat(64 * 1024))
  writeFileSync(small, 'x'.repeat(100))
})

afterAll(() => {
  if (dir) rmSync(dir, { recursive: true, force: true })
})

// Run a hook command the way Claude Code does: a shell, the PreToolUse JSON on stdin. The transcript path names a
// throwaway agent, so the block line the gate logs is attributable to the test.
function runHook(command: string, toolInput: Record<string, unknown>, tool = 'Read'): { status: number; stderr: string } {
  const p = spawnSync('bash', ['-c', command], {
    input: JSON.stringify({
      tool_name: tool,
      tool_input: toolInput,
      cwd: dir,
      transcript_path: join(PROJECT_ROOT, 'agents', 'big-read-gate-test-agent', '.claude-config', 'projects', 'p', 's.jsonl'),
    }),
    encoding: 'utf-8',
    env: { PATH: process.env.PATH ?? '/usr/bin:/bin', CLAUDE_PROJECT_DIR: PROJECT_ROOT },
    timeout: 20000,
  })
  return { status: p.status ?? -1, stderr: p.stderr ?? '' }
}

describe('big-read gate wiring (b073a7e3)', () => {
  const TEST_AGENT = 'big-read-gate-test-agent'
  const testAgentDir = join(PROJECT_ROOT, 'agents', TEST_AGENT)
  const settingsPath = join(testAgentDir, '.claude', 'settings.json')

  afterEach(() => {
    rmSync(testAgentDir, { recursive: true, force: true })
  })

  it('every sub-agent gets it, the main agent does not', () => {
    expect(agentGetsBigReadGate(TEST_AGENT)).toBe(true)
    expect(agentGetsBigReadGate(MAIN_AGENT_ID)).toBe(false)
  })

  it('inject writes one Read entry, idempotently, and drops a stale one', () => {
    const settings = { hooks: { PreToolUse: [
      { matcher: 'Bash', hooks: [{ command: 'python3 /x/other-hook.py' }] },
      { matcher: 'Edit', hooks: [{ command: 'python3 /old/big-read-gate.py' }] },
    ] } }
    injectBigReadGate(settings as unknown as Record<string, unknown>)
    injectBigReadGate(settings as unknown as Record<string, unknown>)
    const entries = ptu(settings)
    expect(mine(entries)).toHaveLength(1)
    expect(mine(entries)[0].matcher).toBe('Read')
    expect(mine(entries)[0].hooks[0].timeout).toBe(10)
    expect(firesFor(entries, 'Read')).toBe(true)
    expect(firesFor(entries, 'Bash')).toBe(false)
    expect(entries.some((e) => JSON.stringify(e).includes('other-hook.py'))).toBe(true)
  })

  it('the written command stops a whole read of a big file and lets the rest through (run as Claude Code does)', () => {
    const settings = {}
    injectBigReadGate(settings)
    const command = mine(ptu(settings))[0].hooks[0].command
    const blocked = runHook(command, { file_path: big })
    expect(blocked.status).toBe(2)
    expect(blocked.stderr).toContain('big.ts')
    expect(blocked.stderr).toContain('limit')
    expect(runHook(command, { file_path: big, offset: 1, limit: 120 }).status).toBe(0)
    expect(runHook(command, { file_path: small }).status).toBe(0)
    expect(runHook(command, { command: `cat ${big}` }, 'Bash').status).toBe(0)
  })

  it('ensureBigReadGate wires an existing sub-agent once, replaces a wrong matcher, then settles', () => {
    mkdirSync(join(testAgentDir, '.claude'), { recursive: true })
    const wrong = { matcher: 'Bash', hooks: [{ type: 'command', command: `python3 "${join(PROJECT_ROOT, 'scripts', 'hooks', 'big-read-gate.py')}"`, timeout: 10 }] }
    writeFileSync(settingsPath, JSON.stringify({ hooks: { PreToolUse: [wrong] } }, null, 2))
    expect(ensureBigReadGate(TEST_AGENT)).toBe(true)
    expect(ensureBigReadGate(TEST_AGENT)).toBe(false)
    const entries = ptu(JSON.parse(readFileSync(settingsPath, 'utf-8')))
    expect(mine(entries)).toHaveLength(1)
    expect(firesFor(entries, 'Read')).toBe(true)
  })

  it('ensureBigReadGate writes back an entry taken out of a sub-agent settings file', () => {
    mkdirSync(join(testAgentDir, '.claude'), { recursive: true })
    writeFileSync(settingsPath, JSON.stringify({ permissions: { allow: [] } }, null, 2))
    expect(ensureBigReadGate(TEST_AGENT)).toBe(true)
    const s = JSON.parse(readFileSync(settingsPath, 'utf-8'))
    expect(s.permissions).toEqual({ allow: [] })
    expect(firesFor(ptu(s), 'Read')).toBe(true)
  })

  it('leaves the main agent and a never-spawned agent alone', () => {
    expect(ensureBigReadGate(MAIN_AGENT_ID)).toBe(false)
    expect(ensureBigReadGate(TEST_AGENT)).toBe(false)
  })

  it('the spawn path and the boot migration both call it', () => {
    const scaffold = readFileSync(join(PROJECT_ROOT, 'src', 'web', 'agent-scaffold.ts'), 'utf-8')
    expect(scaffold).toContain('if (agentGetsBigReadGate(name)) injectBigReadGate(existing)')
    const web = readFileSync(join(PROJECT_ROOT, 'src', 'web.ts'), 'utf-8')
    expect(web).toMatch(/if \(ensureBigReadGate\(agentName\)\) bigReadGatePatched\.push\(agentName\)/)
  })
})
