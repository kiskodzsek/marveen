// Card c8a65f38 (Viktor 42891 LOW 1): every ensure* gate migration counts a gate as wired only when its entry is
// EXACTLY the one the injector writes. Before it the check was a substring match on the serialized hooks, so an
// agent that appended to the command in its own settings (`... > /dev/null`, `|| true`), changed the timeout or
// added a hook to the entry kept a gate that does not enforce, and the boot migration saw it as wired forever.
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  agentSettingsPath,
  ensureBashEgressParser,
  ensureEgressGate,
  ensureGovernanceGateCommands,
  ensureImageQuarantineGate,
  ensureKeychainReadGate,
  ensureKeychainWriteGate,
  ensureCredentialsWriteGate,
  ensureTimeClaimTelegramGate,
  ensureProdTreeWriteGate,
  ensureRevocationNote,
  ensureTelegramCopyGate,
  hookEntriesSettled,
} from '../web/agent-scaffold.js'
import { loadProfileTemplate, type ProfileTemplate } from '../web/profiles.js'
import { AGENTS_BASE_DIR } from '../web/agent-config.js'

const TEST_AGENT = 'ensure-exact-entry-probe'
const root = join(AGENTS_BASE_DIR, TEST_AGENT)
const path = agentSettingsPath(TEST_AGENT)
const GATED: ProfileTemplate = { ...loadProfileTemplate('default'), destructiveGate: true }

function cleanup(): void {
  if (!existsSync(root)) return
  // Only the throwaway directory this test created: a live agent dir carries a CLAUDE.md or a HANDOFF.md.
  if (existsSync(join(root, 'CLAUDE.md')) || existsSync(join(root, 'HANDOFF.md'))) {
    throw new Error(`refusing: ${root} looks like a live agent, not a test checkout`)
  }
  rmSync(root, { recursive: true, force: true })
}
beforeEach(() => {
  cleanup()
  mkdirSync(join(root, '.claude'), { recursive: true })
  writeFileSync(path, JSON.stringify({ permissions: { allow: [] } }, null, 2))
})
afterEach(cleanup)

type Hook = Record<string, unknown> & { command: string; timeout?: number }
type Entry = Record<string, unknown> & { matcher?: string; hooks: Hook[] }
type Settings = { hooks: Record<string, Entry[]> }
const read = (): Settings => JSON.parse(readFileSync(path, 'utf-8')) as Settings
const write = (s: Settings) => writeFileSync(path, JSON.stringify(s, null, 2))
const mine = (s: Settings, event: string, marker: string) =>
  (s.hooks?.[event] ?? []).filter((e) => JSON.stringify(e).includes(marker))

// Each gate: its ensure, the hook event and the script marker its injector dedupes by.
const GATES: Array<{ marker: string; event: 'PreToolUse' | 'PostToolUse'; ensure: () => boolean }> = [
  { marker: 'outgoing-copy-gate.py', event: 'PreToolUse', ensure: () => ensureTelegramCopyGate(TEST_AGENT) },
  { marker: 'egress-gate.mjs', event: 'PreToolUse', ensure: () => ensureEgressGate(TEST_AGENT) },
  { marker: 'bash-egress-parser.mjs', event: 'PreToolUse', ensure: () => ensureBashEgressParser(TEST_AGENT) },
  { marker: 'image-quarantine-gate.mjs', event: 'PreToolUse', ensure: () => ensureImageQuarantineGate(TEST_AGENT) },
  { marker: 'keychain-read-gate.py', event: 'PreToolUse', ensure: () => ensureKeychainReadGate(TEST_AGENT) },
  { marker: 'keychain-write-gate.py', event: 'PreToolUse', ensure: () => ensureKeychainWriteGate(TEST_AGENT) },
  { marker: 'credentials-write-gate.py', event: 'PreToolUse', ensure: () => ensureCredentialsWriteGate(TEST_AGENT) },
  { marker: 'time-claim-gate.py', event: 'PreToolUse', ensure: () => ensureTimeClaimTelegramGate(TEST_AGENT) },
  { marker: 'prod-tree-write-gate.py', event: 'PreToolUse', ensure: () => ensureProdTreeWriteGate(TEST_AGENT) },
  { marker: 'revocation-evening-note.py', event: 'PostToolUse', ensure: () => ensureRevocationNote(TEST_AGENT) },
  { marker: 'email-send-gate.mjs', event: 'PreToolUse', ensure: () => ensureGovernanceGateCommands(TEST_AGENT, GATED) },
  { marker: 'self-pace-gate.mjs', event: 'PreToolUse', ensure: () => ensureGovernanceGateCommands(TEST_AGENT, GATED) },
  { marker: 'destructive-gate.py', event: 'PreToolUse', ensure: () => ensureGovernanceGateCommands(TEST_AGENT, GATED) },
]

// Wire the gate, check it settles, and return the canonical entry the injector wrote.
function wire(g: (typeof GATES)[number]): Entry {
  expect(g.ensure()).toBe(true)
  expect(g.ensure()).toBe(false)
  const entries = mine(read(), g.event, g.marker)
  expect(entries).toHaveLength(1)
  return entries[0]
}

// Edit this gate's entry in the agent's own settings, as an agent could.
function edit(g: (typeof GATES)[number], change: (e: Entry) => void): void {
  const s = read()
  for (const e of s.hooks[g.event]) if (JSON.stringify(e).includes(g.marker)) change(e)
  write(s)
}

describe.each(GATES)('$marker: the ensure accepts only the exact entry', (g) => {
  it('an appended command (> /dev/null) is rewritten, then settles', () => {
    const canonical = wire(g)
    edit(g, (e) => { e.hooks[0].command += ' > /dev/null 2>&1 || true' })
    expect(g.ensure()).toBe(true)
    expect(mine(read(), g.event, g.marker)).toEqual([canonical])
    expect(g.ensure()).toBe(false)
  })

  it('a changed timeout is rewritten', () => {
    const canonical = wire(g)
    edit(g, (e) => { e.hooks[0].timeout = 1 })
    expect(g.ensure()).toBe(true)
    expect(mine(read(), g.event, g.marker)).toEqual([canonical])
  })

  // Viktor 42916 INFO 1: without these two, a check that ignored the matcher or the hook type survived mutation.
  it('a changed matcher is rewritten', () => {
    const canonical = wire(g)
    edit(g, (e) => { e.matcher = 'Read' })
    expect(g.ensure()).toBe(true)
    // The Telegram copy-gate injector keeps an entry of its script under another matcher (Viktor 42916 INFO 2):
    // the canonical entry is added next to it. So does the time-claim Telegram injector (card 0faaa397: every
    // sub-agent runs the same script, hand-wired, on Write|Edit|MultiEdit|Bash). Every other gate ends with exactly
    // the canonical entry.
    if (g.marker === 'outgoing-copy-gate.py' || g.marker === 'time-claim-gate.py') expect(mine(read(), g.event, g.marker)).toContainEqual(canonical)
    else expect(mine(read(), g.event, g.marker)).toEqual([canonical])
    expect(g.ensure()).toBe(false)
  })

  it('a changed hook type is rewritten', () => {
    const canonical = wire(g)
    edit(g, (e) => { e.hooks[0].type = 'prompt' })
    expect(g.ensure()).toBe(true)
    expect(mine(read(), g.event, g.marker)).toEqual([canonical])
  })

  it('a second hook added to the entry is rewritten', () => {
    const canonical = wire(g)
    edit(g, (e) => { e.hooks.push({ type: 'command', command: 'true' }) })
    expect(g.ensure()).toBe(true)
    expect(mine(read(), g.event, g.marker)).toEqual([canonical])
  })

  it('a duplicate entry is collapsed to one', () => {
    const canonical = wire(g)
    const s = read()
    s.hooks[g.event].push(JSON.parse(JSON.stringify(canonical)) as Entry)
    write(s)
    expect(g.ensure()).toBe(true)
    expect(mine(read(), g.event, g.marker)).toEqual([canonical])
  })

  it('the same entry with its keys reordered is NOT rewritten (no churn at every boot)', () => {
    const canonical = wire(g)
    edit(g, (e) => {
      const { matcher, hooks } = e
      for (const k of Object.keys(e)) delete e[k]
      e.hooks = hooks.map(({ type, command, timeout }) => ({ timeout, command, type }) as Hook)
      if (matcher !== undefined) e.matcher = matcher
    })
    const before = readFileSync(path, 'utf-8')
    expect(before).not.toBe(JSON.stringify({ hooks: {} }))
    expect(g.ensure()).toBe(false)
    expect(readFileSync(path, 'utf-8')).toBe(before)
    expect(mine(read(), g.event, g.marker)).toEqual([canonical])
  })
})

describe('hookEntriesSettled', () => {
  const inject = (s: Record<string, unknown>) => {
    const hooks = (s.hooks ??= {}) as Record<string, unknown[]>
    const prev = Array.isArray(hooks.PreToolUse) ? hooks.PreToolUse : []
    hooks.PreToolUse = [
      ...prev.filter((e) => !JSON.stringify(e).includes('x-gate.py')),
      { matcher: 'Bash', hooks: [{ type: 'command', command: 'python3 /r/x-gate.py', timeout: 10 }] },
    ]
  }
  const exact = { matcher: 'Bash', hooks: [{ type: 'command', command: 'python3 /r/x-gate.py', timeout: 10 }] }
  const other = { matcher: 'Read', hooks: [{ type: 'command', command: 'python3 /r/other.py' }] }

  it('does not change the settings it checks', () => {
    const s = { hooks: { PreToolUse: [other] } }
    const before = JSON.stringify(s)
    hookEntriesSettled(s, 'PreToolUse', 'x-gate.py', inject)
    expect(JSON.stringify(s)).toBe(before)
  })

  it('is true for the exact entry, wherever the other gates sit', () => {
    expect(hookEntriesSettled({ hooks: { PreToolUse: [exact] } }, 'PreToolUse', 'x-gate.py', inject)).toBe(true)
    expect(hookEntriesSettled({ hooks: { PreToolUse: [exact, other] } }, 'PreToolUse', 'x-gate.py', inject)).toBe(true)
  })

  it('is false when missing, edited, or under another event', () => {
    const edited = { ...exact, hooks: [{ ...exact.hooks[0], command: 'python3 /r/x-gate.py; exit 0' }] }
    expect(hookEntriesSettled({}, 'PreToolUse', 'x-gate.py', inject)).toBe(false)
    expect(hookEntriesSettled({ hooks: { PreToolUse: [other] } }, 'PreToolUse', 'x-gate.py', inject)).toBe(false)
    expect(hookEntriesSettled({ hooks: { PreToolUse: [edited] } }, 'PreToolUse', 'x-gate.py', inject)).toBe(false)
    expect(hookEntriesSettled({ hooks: { PostToolUse: [exact] } }, 'PreToolUse', 'x-gate.py', inject)).toBe(false)
  })
})
