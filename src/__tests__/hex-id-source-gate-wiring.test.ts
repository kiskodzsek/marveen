// Card 7b2f784f (retro 2026-11-20 R1, Viktor 48909): the hex-id source gate reaches every sub-agent, not only the
// main agent. The hook's own behaviour is tested in scripts/hooks/hex-id-source-gate_test.py; here: the wiring, and
// that the command the scaffold writes really blocks (and fails open with a log line) when Claude Code runs it.
import { describe, it, expect, afterEach } from 'vitest'
import { spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  agentGetsHexIdSourceGate,
  ensureHexIdSourceGate,
  injectHexIdSourceGate,
} from '../web/agent-scaffold.js'
import { MAIN_AGENT_ID, PROJECT_ROOT } from '../config.js'

type Entry = { matcher?: string; hooks: { command: string; timeout?: number }[] }
const ptu = (s: { hooks?: { PreToolUse?: Entry[] } }): Entry[] => s.hooks?.PreToolUse ?? []
const mine = (entries: Entry[]) => entries.filter((e) => JSON.stringify(e).includes('hex-id-source-gate.py'))
const firesFor = (entries: Entry[], tool: string) =>
  mine(entries).some((e) => new RegExp(`^(?:${e.matcher ?? '.*'})$`).test(tool))

const MEASURED = '9b1e9239291f0c2d4e5a6b7c8d9e0f1a2b3c4d5e'

describe('hex-id source gate wiring (7b2f784f)', () => {
  const TEST_AGENT = 'hex-id-source-gate-test-agent'
  const testAgentDir = join(PROJECT_ROOT, 'agents', TEST_AGENT)
  const settingsPath = join(testAgentDir, '.claude', 'settings.json')
  const transcript = join(testAgentDir, 'transcript.jsonl')
  const failopenLog = join(testAgentDir, 'failopen.log')

  // Run a hook command the way Claude Code does: a shell, the PreToolUse JSON (with the sub-agent's transcript_path)
  // on stdin. The fail-open log is pointed into the test agent's folder so the test never writes store/.
  function runHook(command: string, bashCommand: string, withTranscript = true): number {
    const payload: Record<string, unknown> = { tool_name: 'Bash', tool_input: { command: bashCommand }, cwd: testAgentDir }
    if (withTranscript) payload.transcript_path = transcript
    const p = spawnSync('bash', ['-c', command], {
      input: JSON.stringify(payload),
      encoding: 'utf-8',
      env: { PATH: process.env.PATH ?? '/usr/bin:/bin', CLAUDE_PROJECT_DIR: PROJECT_ROOT, HEX_GATE_FAILOPEN_LOG: failopenLog },
      timeout: 20000,
    })
    return p.status ?? -1
  }

  afterEach(() => {
    rmSync(testAgentDir, { recursive: true, force: true })
  })

  it('every sub-agent gets it, the main agent does not (it has the project-settings hook)', () => {
    expect(agentGetsHexIdSourceGate(TEST_AGENT)).toBe(true)
    expect(agentGetsHexIdSourceGate(MAIN_AGENT_ID)).toBe(false)
  })

  it('inject writes one Bash entry, idempotently, and drops a stale one', () => {
    const settings = { hooks: { PreToolUse: [
      { matcher: 'Read', hooks: [{ command: 'python3 /x/other-hook.py' }] },
      { matcher: 'Edit', hooks: [{ command: 'python3 /old/hex-id-source-gate.py' }] },
    ] } }
    injectHexIdSourceGate(settings as unknown as Record<string, unknown>)
    injectHexIdSourceGate(settings as unknown as Record<string, unknown>)
    const entries = ptu(settings)
    expect(mine(entries)).toHaveLength(1)
    expect(mine(entries)[0].matcher).toBe('Bash')
    expect(mine(entries)[0].hooks[0].timeout).toBe(10)
    expect(firesFor(entries, 'Bash')).toBe(true)
    expect(entries.some((e) => JSON.stringify(e).includes('other-hook.py'))).toBe(true)
  })

  it('the written command blocks an unmeasured hex in a send and allows a measured one (run as Claude Code does)', () => {
    mkdirSync(testAgentDir, { recursive: true })
    writeFileSync(transcript, JSON.stringify({ type: 'user', message: { role: 'user', content: [
      { type: 'tool_result', tool_use_id: 'x', content: `${MEASURED}\n` }] } }) + '\n')
    const settings = {}
    injectHexIdSourceGate(settings)
    const command = mine(ptu(settings))[0].hooks[0].command
    expect(runHook(command, 'bash scripts/agent-msg.sh kernel viktor "fej 9b1e92392916"')).toBe(2)
    expect(runHook(command, 'bash scripts/agent-msg.sh kernel viktor "fej 9b1e9239291f"')).toBe(0)
    expect(runHook(command, `bash scripts/agent-msg.sh kernel viktor "fej ${MEASURED}"`)).toBe(0)
    expect(runHook(command, 'git show 9b1e92392916')).toBe(0)
    expect(existsSync(failopenLog)).toBe(false)
  })

  it('the written command fails open with one content-free log line when the transcript_path is missing', () => {
    mkdirSync(testAgentDir, { recursive: true })
    const settings = {}
    injectHexIdSourceGate(settings)
    const command = mine(ptu(settings))[0].hooks[0].command
    expect(runHook(command, 'bash scripts/agent-msg.sh kernel viktor "fej 9b1e92392916"', false)).toBe(0)
    const log = readFileSync(failopenLog, 'utf-8')
    expect(log.trim().split('\n')).toHaveLength(1)
    expect(log).toMatch(/\tno-transcript-path\n$/)
    expect(log).not.toContain('9b1e9239')
  })

  it('ensureHexIdSourceGate wires an existing sub-agent once, replaces a wrong matcher, then settles', () => {
    mkdirSync(join(testAgentDir, '.claude'), { recursive: true })
    const wrong = { matcher: 'Read', hooks: [{ type: 'command', command: `python3 "${join(PROJECT_ROOT, 'scripts', 'hooks', 'hex-id-source-gate.py')}"`, timeout: 10 }] }
    writeFileSync(settingsPath, JSON.stringify({ hooks: { PreToolUse: [wrong] } }, null, 2))
    expect(ensureHexIdSourceGate(TEST_AGENT)).toBe(true)
    expect(ensureHexIdSourceGate(TEST_AGENT)).toBe(false)
    const entries = ptu(JSON.parse(readFileSync(settingsPath, 'utf-8')))
    expect(mine(entries)).toHaveLength(1)
    expect(firesFor(entries, 'Bash')).toBe(true)
  })

  it('ensureHexIdSourceGate wires a sub-agent that has settings but no hooks', () => {
    mkdirSync(join(testAgentDir, '.claude'), { recursive: true })
    writeFileSync(settingsPath, JSON.stringify({ permissions: { allow: [] } }, null, 2))
    expect(ensureHexIdSourceGate(TEST_AGENT)).toBe(true)
    const s = JSON.parse(readFileSync(settingsPath, 'utf-8'))
    expect(s.permissions).toEqual({ allow: [] })
    expect(firesFor(ptu(s), 'Bash')).toBe(true)
  })

  it('leaves the main agent and a never-spawned agent alone', () => {
    expect(ensureHexIdSourceGate(MAIN_AGENT_ID)).toBe(false)
    expect(ensureHexIdSourceGate(TEST_AGENT)).toBe(false)
  })

  it('the spawn path and the boot migration both call it', () => {
    const scaffold = readFileSync(join(PROJECT_ROOT, 'src', 'web', 'agent-scaffold.ts'), 'utf-8')
    expect(scaffold).toContain('if (agentGetsHexIdSourceGate(name)) injectHexIdSourceGate(existing)')
    const web = readFileSync(join(PROJECT_ROOT, 'src', 'web.ts'), 'utf-8')
    expect(web).toMatch(/if \(ensureHexIdSourceGate\(agentName\)\) hexIdSourcePatched\.push\(agentName\)/)
  })

  it('the main agent carries it in the repo-shipped project settings, on Bash', () => {
    const settings = JSON.parse(readFileSync(join(PROJECT_ROOT, '.claude', 'settings.json'), 'utf-8'))
    expect(firesFor(ptu(settings), 'Bash')).toBe(true)
  })
})
