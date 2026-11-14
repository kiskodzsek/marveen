// Card 7702bb13 (retro 2026-11-13, Kernel c): the revocation note reaches every sub-agent and the main agent. The
// hook's own behaviour is tested in scripts/hooks/revocation-evening-note_test.py; here: the wiring, and that the
// command the scaffold writes really notes a revocation when Claude Code runs it.
import { describe, it, expect, afterEach, afterAll } from 'vitest'
import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  agentGetsRevocationNote,
  ensureRevocationNote,
  injectRevocationNote,
} from '../web/agent-scaffold.js'
import { MAIN_AGENT_ID, PROJECT_ROOT } from '../config.js'

type Entry = { matcher?: string; hooks: { command: string; timeout?: number }[] }
const post = (s: { hooks?: { PostToolUse?: Entry[] } }): Entry[] => s.hooks?.PostToolUse ?? []
const mine = (entries: Entry[]) => entries.filter((e) => JSON.stringify(e).includes('revocation-evening-note.py'))
const firesFor = (entries: Entry[], tool: string) =>
  mine(entries).some((e) => new RegExp(`^(?:${e.matcher ?? '.*'})$`).test(tool))

// Run a hook command the way Claude Code does: a shell, the PostToolUse JSON on stdin; the block in a temp file.
function runHook(command: string, bashCommand: string, blokk: string): number {
  const p = spawnSync('bash', ['-c', command], {
    input: JSON.stringify({ tool_name: 'Bash', tool_input: { command: bashCommand }, cwd: '/Users/x/marveen/agents/kernel' }),
    encoding: 'utf-8',
    env: { PATH: process.env.PATH ?? '/usr/bin:/bin', CLAUDE_PROJECT_DIR: PROJECT_ROOT, ESTE_BLOKK_PATH: blokk },
    timeout: 20000,
  })
  return p.status ?? -1
}

describe('revocation evening note wiring (7702bb13)', () => {
  const TEST_AGENT = 'revocation-note-test-agent'
  const testAgentDir = join(PROJECT_ROOT, 'agents', TEST_AGENT)
  const settingsPath = join(testAgentDir, '.claude', 'settings.json')
  const tmp = mkdtempSync(join(tmpdir(), 'revoke-note-'))

  afterEach(() => {
    rmSync(testAgentDir, { recursive: true, force: true })
  })
  afterAll(() => {
    rmSync(tmp, { recursive: true, force: true })
  })

  it('every sub-agent gets it, the main agent does not (it has the project-settings hook)', () => {
    expect(agentGetsRevocationNote(TEST_AGENT)).toBe(true)
    expect(agentGetsRevocationNote(MAIN_AGENT_ID)).toBe(false)
  })

  it('inject writes one Bash PostToolUse entry, idempotently, and drops a stale one', () => {
    const settings = { hooks: { PostToolUse: [
      { matcher: 'Read', hooks: [{ command: 'python3 /x/other-hook.py' }] },
      { matcher: 'Edit', hooks: [{ command: 'python3 /old/revocation-evening-note.py' }] },
    ] } }
    injectRevocationNote(settings as unknown as Record<string, unknown>)
    injectRevocationNote(settings as unknown as Record<string, unknown>)
    const entries = post(settings)
    expect(mine(entries)).toHaveLength(1)
    expect(mine(entries)[0].matcher).toBe('Bash')
    expect(mine(entries)[0].hooks[0].timeout).toBe(10)
    expect(firesFor(entries, 'Bash')).toBe(true)
    expect(entries.some((e) => JSON.stringify(e).includes('other-hook.py'))).toBe(true)
  })

  it('the written command notes a revocation and stays quiet otherwise (run as Claude Code does)', () => {
    const settings = {}
    injectRevocationNote(settings)
    const command = mine(post(settings))[0].hooks[0].command
    const blokk = join(tmp, 'blokk.json')
    expect(runHook(command, 'git status', blokk)).toBe(0)
    expect(existsSync(blokk)).toBe(false)
    expect(runHook(command, 'claude mcp logout higgsfield', blokk)).toBe(0)
    const items = JSON.parse(readFileSync(blokk, 'utf-8'))
    expect(items).toHaveLength(1)
    expect(items[0].mi).toContain('claude mcp logout higgsfield')
    expect(items[0].agens).toBe('kernel')
  })

  it('ensureRevocationNote wires an existing sub-agent once, replaces a wrong matcher, then settles', () => {
    mkdirSync(join(testAgentDir, '.claude'), { recursive: true })
    const wrong = { matcher: 'Read', hooks: [{ type: 'command', command: `python3 "${join(PROJECT_ROOT, 'scripts', 'hooks', 'revocation-evening-note.py')}"`, timeout: 10 }] }
    writeFileSync(settingsPath, JSON.stringify({ hooks: { PostToolUse: [wrong] } }, null, 2))
    expect(ensureRevocationNote(TEST_AGENT)).toBe(true)
    expect(ensureRevocationNote(TEST_AGENT)).toBe(false)
    const entries = post(JSON.parse(readFileSync(settingsPath, 'utf-8')))
    expect(mine(entries)).toHaveLength(1)
    expect(firesFor(entries, 'Bash')).toBe(true)
  })

  it('ensureRevocationNote wires a sub-agent that has settings but no hooks', () => {
    mkdirSync(join(testAgentDir, '.claude'), { recursive: true })
    writeFileSync(settingsPath, JSON.stringify({ permissions: { allow: [] } }, null, 2))
    expect(ensureRevocationNote(TEST_AGENT)).toBe(true)
    const s = JSON.parse(readFileSync(settingsPath, 'utf-8'))
    expect(s.permissions).toEqual({ allow: [] })
    expect(firesFor(post(s), 'Bash')).toBe(true)
  })

  it('leaves the main agent and a never-spawned agent alone', () => {
    expect(ensureRevocationNote(MAIN_AGENT_ID)).toBe(false)
    expect(ensureRevocationNote(TEST_AGENT)).toBe(false)
  })

  it('the spawn path and the boot migration both call it', () => {
    const scaffold = readFileSync(join(PROJECT_ROOT, 'src', 'web', 'agent-scaffold.ts'), 'utf-8')
    expect(scaffold).toContain('if (agentGetsRevocationNote(name)) injectRevocationNote(existing)')
    const web = readFileSync(join(PROJECT_ROOT, 'src', 'web.ts'), 'utf-8')
    expect(web).toMatch(/if \(ensureRevocationNote\(agentName\)\) revokeNotePatched\.push\(agentName\)/)
  })

  it('the main agent carries it in the repo-shipped project settings, on Bash PostToolUse', () => {
    const settings = JSON.parse(readFileSync(join(PROJECT_ROOT, '.claude', 'settings.json'), 'utf-8'))
    expect(firesFor(post(settings), 'Bash')).toBe(true)
  })
})
