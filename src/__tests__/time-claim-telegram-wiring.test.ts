// Card 0faaa397 (Klodel 48360; hibanapló 2026-11-20 02:20): the time-claim gate's placeholder rule reaches the
// Telegram reply/edit_message text of every agent, the main one through the repo-shipped project settings, the
// sub-agents through the scaffold. The hook's own behaviour is tested in scripts/hooks/time-claim-gate_test.py;
// here: the wiring, that the hand-wired "Write|Edit|MultiEdit|Bash" entry every sub-agent already carries survives,
// and that the command the scaffold writes really blocks when Claude Code runs it.
import { describe, it, expect, afterEach } from 'vitest'
import { spawnSync } from 'node:child_process'
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  TELEGRAM_COPY_GATE_MATCHER,
  agentGetsTimeClaimTelegramGate,
  ensureTimeClaimTelegramGate,
  injectTimeClaimTelegramGate,
} from '../web/agent-scaffold.js'
import { MAIN_AGENT_ID, PROJECT_ROOT } from '../config.js'

type Entry = { matcher?: string; hooks: { command: string; timeout?: number }[] }
const ptu = (s: { hooks?: { PreToolUse?: Entry[] } }): Entry[] => s.hooks?.PreToolUse ?? []
const mine = (entries: Entry[]) => entries.filter((e) => JSON.stringify(e).includes('time-claim-gate.py'))
const firesFor = (entries: Entry[], tool: string) =>
  mine(entries).some((e) => new RegExp(`^(?:${e.matcher ?? '.*'})$`).test(tool))

const REPLY = 'mcp__plugin_telegram_telegram__reply'
const EDIT = 'mcp__plugin_telegram_telegram__edit_message'
const SCRIPT = join(PROJECT_ROOT, 'scripts', 'hooks', 'time-claim-gate.py')
// The entry every sub-agent carries today (hand-wired): it gates shared/*.md writes and card comments.
const HAND_WIRED: Entry = {
  matcher: 'Write|Edit|MultiEdit|Bash',
  hooks: [{ command: `bash -c '[ -f ${SCRIPT} ] && exec python3 ${SCRIPT}; exit 0'`, timeout: 10 }],
}

// Run a hook command the way Claude Code does: a shell, the PreToolUse JSON on stdin.
function runHook(command: string, tool: string, text: string): number {
  const p = spawnSync('bash', ['-c', command], {
    input: JSON.stringify({ tool_name: tool, tool_input: { chat_id: '-1001', text } }),
    encoding: 'utf-8',
    env: { PATH: process.env.PATH ?? '/usr/bin:/bin', CLAUDE_PROJECT_DIR: PROJECT_ROOT },
    timeout: 20000,
  })
  return p.status ?? -1
}

describe('time-claim gate on the Telegram text (0faaa397)', () => {
  const TEST_AGENT = 'time-claim-telegram-test-agent'
  const testAgentDir = join(PROJECT_ROOT, 'agents', TEST_AGENT)
  const settingsPath = join(testAgentDir, '.claude', 'settings.json')

  afterEach(() => {
    rmSync(testAgentDir, { recursive: true, force: true })
  })

  it('every sub-agent gets it, the main agent does not (it has the project-settings hook)', () => {
    expect(agentGetsTimeClaimTelegramGate(TEST_AGENT)).toBe(true)
    expect(agentGetsTimeClaimTelegramGate(MAIN_AGENT_ID)).toBe(false)
  })

  it('inject adds one Telegram entry, idempotently, and KEEPS the hand-wired Bash entry', () => {
    const settings = { hooks: { PreToolUse: [
      { matcher: 'Read', hooks: [{ command: 'python3 /x/other-hook.py' }] },
      HAND_WIRED,
    ] } }
    injectTimeClaimTelegramGate(settings as unknown as Record<string, unknown>)
    injectTimeClaimTelegramGate(settings as unknown as Record<string, unknown>)
    const entries = ptu(settings)
    expect(mine(entries)).toHaveLength(2)
    expect(entries).toContainEqual(HAND_WIRED)
    const tg = mine(entries).filter((e) => e.matcher === TELEGRAM_COPY_GATE_MATCHER)
    expect(tg).toHaveLength(1)
    expect(tg[0].hooks[0].timeout).toBe(10)
    for (const tool of [REPLY, EDIT, 'Bash', 'Write']) expect(firesFor(entries, tool)).toBe(true)
    expect(firesFor(entries, 'mcp__plugin_telegram_telegram__react')).toBe(false)
    expect(entries.some((e) => JSON.stringify(e).includes('other-hook.py'))).toBe(true)
  })

  it('inject replaces an edited Telegram entry instead of adding a second one', () => {
    const edited = { matcher: TELEGRAM_COPY_GATE_MATCHER, hooks: [{ command: `python3 "${SCRIPT}" || true`, timeout: 10 }] }
    const settings = { hooks: { PreToolUse: [HAND_WIRED, edited] } }
    injectTimeClaimTelegramGate(settings as unknown as Record<string, unknown>)
    const tg = mine(ptu(settings)).filter((e) => e.matcher === TELEGRAM_COPY_GATE_MATCHER)
    expect(tg).toHaveLength(1)
    expect(tg[0].hooks[0].command).not.toContain('|| true')
    expect(ptu(settings)).toContainEqual(HAND_WIRED)
  })

  it('the written command blocks a placeholder time in a reply and an edit, and passes a measured or planned one', () => {
    const settings = {}
    injectTimeClaimTelegramGate(settings)
    const command = mine(ptu(settings))[0].hooks[0].command
    expect(runHook(command, REPLY, 'Kint van (Pulzus mérte, 02:2x előtt 0 látogatóval).')).toBe(2)
    expect(runHook(command, EDIT, 'kész, 10:xx')).toBe(2)
    expect(runHook(command, REPLY, 'Kint van (Pulzus mérte, 02:20).')).toBe(0)
    expect(runHook(command, REPLY, '23:00 után élesítünk.')).toBe(0)
  })

  it('ensureTimeClaimTelegramGate wires an existing sub-agent once, keeps the hand-wired entry, then settles', () => {
    mkdirSync(join(testAgentDir, '.claude'), { recursive: true })
    writeFileSync(settingsPath, JSON.stringify({ hooks: { PreToolUse: [HAND_WIRED] } }, null, 2))
    expect(ensureTimeClaimTelegramGate(TEST_AGENT)).toBe(true)
    expect(ensureTimeClaimTelegramGate(TEST_AGENT)).toBe(false)
    const entries = ptu(JSON.parse(readFileSync(settingsPath, 'utf-8')))
    expect(entries).toContainEqual(HAND_WIRED)
    expect(mine(entries)).toHaveLength(2)
    expect(firesFor(entries, REPLY)).toBe(true)
    expect(firesFor(entries, EDIT)).toBe(true)
  })

  it('ensureTimeClaimTelegramGate wires a sub-agent that has settings but no hooks', () => {
    mkdirSync(join(testAgentDir, '.claude'), { recursive: true })
    writeFileSync(settingsPath, JSON.stringify({ permissions: { allow: [] } }, null, 2))
    expect(ensureTimeClaimTelegramGate(TEST_AGENT)).toBe(true)
    const s = JSON.parse(readFileSync(settingsPath, 'utf-8'))
    expect(s.permissions).toEqual({ allow: [] })
    expect(firesFor(ptu(s), REPLY)).toBe(true)
  })

  it('leaves the main agent and a never-spawned agent alone', () => {
    expect(ensureTimeClaimTelegramGate(MAIN_AGENT_ID)).toBe(false)
    expect(ensureTimeClaimTelegramGate(TEST_AGENT)).toBe(false)
  })

  it('the spawn path and the boot migration both call it', () => {
    const scaffold = readFileSync(join(PROJECT_ROOT, 'src', 'web', 'agent-scaffold.ts'), 'utf-8')
    expect(scaffold).toContain('if (agentGetsTimeClaimTelegramGate(name)) injectTimeClaimTelegramGate(existing)')
    const web = readFileSync(join(PROJECT_ROOT, 'src', 'web.ts'), 'utf-8')
    expect(web).toMatch(/if \(ensureTimeClaimTelegramGate\(agentName\)\) timeClaimTgPatched\.push\(agentName\)/)
  })

  it('the main agent carries it in the repo-shipped project settings, on reply and edit_message', () => {
    const settings = JSON.parse(readFileSync(join(PROJECT_ROOT, '.claude', 'settings.json'), 'utf-8'))
    expect(firesFor(ptu(settings), REPLY)).toBe(true)
    expect(firesFor(ptu(settings), EDIT)).toBe(true)
    expect(firesFor(ptu(settings), 'Bash')).toBe(true)
  })
})
