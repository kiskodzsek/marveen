// Card 47468cc1 (Viktor 50533): every dashboard boot added one more "Write|Edit|MultiEdit|Bash" time-claim-gate
// entry to every sub-agent (47 by 2026-11-23, one per "time-claim-gate hook wired onto Telegram" line in
// store/dashboard.log). Per boot: upgradeLegacyHookCommands rewrote the Telegram entry's fail-closed
// pythonHookCommand to the template's fail-open wrapper (same script basename), syncHookMatchers then moved that
// group onto the template matcher, and ensureTimeClaimTelegramGate found no Telegram entry and appended a new one.
// Here: the boot sequence (ensureAgentHooks, then ensureTimeClaimTelegramGate) run several times keeps exactly one
// entry under each matcher and stops writing; the copies an earlier boot left collapse; and the two passes still do
// their own jobs (a bare legacy command is upgraded, a stale matcher with no other group is re-matched).
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  TELEGRAM_COPY_GATE_MATCHER,
  dedupeIdenticalHookEntries,
  ensureAgentHooks,
  ensureTimeClaimTelegramGate,
  pythonHookCommand,
  syncHookMatchers,
  upgradeLegacyHookCommands,
} from '../web/agent-scaffold.js'
import { PROJECT_ROOT } from '../config.js'

type Hook = { type?: string; command: string; timeout?: number }
type Entry = { matcher?: string; hooks: Hook[] }
type Settings = { hooks?: Record<string, Entry[]> }

const SCRIPT = join(PROJECT_ROOT, 'scripts', 'hooks', 'time-claim-gate.py')
const WRAPPED = `bash -c '[ -f ${SCRIPT} ] && exec python3 ${SCRIPT}; exit 0'`
const WRITE_MATCHER = 'Write|Edit|MultiEdit|Bash'
const HAND_WIRED: Entry = { matcher: WRITE_MATCHER, hooks: [{ type: 'command', command: WRAPPED, timeout: 10 }] }
const TELEGRAM: Entry = {
  matcher: TELEGRAM_COPY_GATE_MATCHER,
  hooks: [{ type: 'command', command: pythonHookCommand(SCRIPT), timeout: 10 }],
}

const timeClaim = (s: Settings) => (s.hooks?.PreToolUse ?? []).filter((e) => JSON.stringify(e).includes('time-claim-gate.py'))
const byMatcher = (s: Settings, m: string) => timeClaim(s).filter((e) => e.matcher === m)

describe('a dashboard boot does not duplicate the time-claim gate (47468cc1)', () => {
  const TEST_AGENT = 'hook-boot-duplicate-test-agent'
  const testAgentDir = join(PROJECT_ROOT, 'agents', TEST_AGENT)
  const settingsPath = join(testAgentDir, '.claude', 'settings.json')
  let scopeRoot = ''
  let scopes: { user: string; project: string }

  beforeEach(() => {
    mkdirSync(join(testAgentDir, '.claude'), { recursive: true })
    scopeRoot = mkdtempSync(join(tmpdir(), 'hookdup-'))
    scopes = { user: join(scopeRoot, 'user.json'), project: join(scopeRoot, 'project.json') }
    writeFileSync(scopes.user, '{}')
    writeFileSync(scopes.project, '{}')
  })
  afterEach(() => {
    rmSync(testAgentDir, { recursive: true, force: true })
    rmSync(scopeRoot, { recursive: true, force: true })
  })

  const boot = () => {
    const a = ensureAgentHooks(TEST_AGENT, scopes)
    const b = ensureTimeClaimTelegramGate(TEST_AGENT)
    return { a, b }
  }
  const read = (): Settings => JSON.parse(readFileSync(settingsPath, 'utf-8'))

  it('five boots leave one Write entry and one fail-closed Telegram entry, and the later boots write nothing', () => {
    writeFileSync(settingsPath, JSON.stringify({ hooks: { PreToolUse: [HAND_WIRED, TELEGRAM] } }, null, 2))
    boot()
    const after1 = readFileSync(settingsPath, 'utf-8')
    for (let i = 0; i < 4; i++) expect(boot()).toEqual({ a: false, b: false })
    expect(readFileSync(settingsPath, 'utf-8')).toBe(after1)
    const s = read()
    expect(byMatcher(s, WRITE_MATCHER)).toHaveLength(1)
    const tg = byMatcher(s, TELEGRAM_COPY_GATE_MATCHER)
    expect(tg).toHaveLength(1)
    expect(tg[0].hooks[0].command).toBe(pythonHookCommand(SCRIPT))
    expect(timeClaim(s)).toHaveLength(2)
  })

  it('the copies an earlier boot left collapse to one on the next boot', () => {
    const copies = Array.from({ length: 47 }, () => HAND_WIRED)
    writeFileSync(settingsPath, JSON.stringify({ hooks: { PreToolUse: [...copies, TELEGRAM] } }, null, 2))
    boot()
    const s = read()
    expect(byMatcher(s, WRITE_MATCHER)).toHaveLength(1)
    expect(byMatcher(s, TELEGRAM_COPY_GATE_MATCHER)).toHaveLength(1)
    expect(boot()).toEqual({ a: false, b: false })
  })
})

describe('the passes keep their own jobs (47468cc1)', () => {
  it('upgradeLegacyHookCommands still upgrades a bare legacy command, but not the fail-closed pythonHookCommand', () => {
    const tpl = { PreToolUse: [HAND_WIRED] }
    const legacy = { PreToolUse: [{ matcher: WRITE_MATCHER, hooks: [{ command: `python3 ${SCRIPT}` }] }] } as Record<string, unknown>
    expect(upgradeLegacyHookCommands(legacy, tpl)).toBe(true)
    expect((legacy.PreToolUse as Entry[])[0].hooks[0].command).toBe(WRAPPED)
    const gated = { PreToolUse: [JSON.parse(JSON.stringify(TELEGRAM))] } as Record<string, unknown>
    expect(upgradeLegacyHookCommands(gated, tpl)).toBe(false)
    expect((gated.PreToolUse as Entry[])[0].hooks[0].command).toBe(pythonHookCommand(SCRIPT))
  })

  it('syncHookMatchers re-matches a stale group, but not when the template matcher already carries its commands', () => {
    const tpl = { PreToolUse: [HAND_WIRED] }
    const stale = { PreToolUse: [{ matcher: 'Bash', hooks: [{ command: WRAPPED }] }] } as Record<string, unknown>
    expect(syncHookMatchers(stale, tpl)).toBe(true)
    expect((stale.PreToolUse as Entry[])[0].matcher).toBe(WRITE_MATCHER)
    const owned = {
      PreToolUse: [HAND_WIRED, { matcher: TELEGRAM_COPY_GATE_MATCHER, hooks: [{ command: WRAPPED }] }],
    } as Record<string, unknown>
    expect(syncHookMatchers(owned, tpl)).toBe(false)
    expect((owned.PreToolUse as Entry[])[1].matcher).toBe(TELEGRAM_COPY_GATE_MATCHER)
  })

  it('dedupeIdenticalHookEntries drops only identical groups (key order aside) and keeps the first in place', () => {
    const reordered = { hooks: [{ timeout: 10, command: WRAPPED, type: 'command' }], matcher: WRITE_MATCHER }
    const other = { matcher: 'Read', hooks: [{ command: 'python3 /x/other.py' }] }
    const hooks = { PreToolUse: [other, HAND_WIRED, reordered, HAND_WIRED, TELEGRAM] } as Record<string, unknown>
    expect(dedupeIdenticalHookEntries(hooks)).toBe(true)
    expect(hooks.PreToolUse).toEqual([other, HAND_WIRED, TELEGRAM])
    expect(dedupeIdenticalHookEntries(hooks)).toBe(false)
  })
})
