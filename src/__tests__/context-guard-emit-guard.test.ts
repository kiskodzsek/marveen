// Viktor 2453 (review of CGGAPS1013): M1 -- every context-guard directive is
// typed only past the urgent emit guard, so a ready-timeout resume or a
// busy-pane handoff request can never answer a permission prompt with its
// preselected "Yes". L2 -- a cooldown never ends early twice in a row.
// The runner's sweep is IO-bound, so its wiring is pinned on the source, the
// same way rescue-failure-alert.test.ts pins its alert path; the guard itself
// runs against the real pane fixtures.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { urgentEmitRefusal } from '../web/message-router.js'

const here = dirname(fileURLToPath(import.meta.url))
const runner = readFileSync(join(here, '..', 'web', 'context-guard-runner.ts'), 'utf-8')
const fixture = (f: string) => readFileSync(join(here, 'fixtures', 'pane', f), 'utf-8')

describe('M1: the emit guard refuses the panes it must', () => {
  it('a permission prompt (all three fixtures), an empty or unreadable pane: refused', () => {
    for (const f of ['permission-prompt-bash-grep.txt', 'permission-prompt-compound-cd.txt', 'permission-prompt-upper-half.txt']) {
      expect(urgentEmitRefusal(fixture(f)), f).not.toBeNull()
    }
    expect(urgentEmitRefusal(null)).not.toBeNull()
    expect(urgentEmitRefusal('   ')).not.toBeNull()
  })
})

// Viktor review R1 of cc6ba6e0: the key-sending callers match dialogs only on
// the live last line, but the emit guard must stay broad. A menu or first-run
// dialog with anything below it (a shell prompt, a future statusline) is not
// answered with keys, and it is not typed into either.
describe('cc6ba6e0 R1: the emit guard keeps the broad dialog anchor', () => {
  const MENU = ['   Manage MCP servers', '   ❯ claude.ai Canva · ✔ connected · 39 tools', '', '   ↑/↓ to navigate · Enter to confirm · Esc to cancel']
  const TRUST = [' Accessing workspace:', '', '   1. Yes, I trust this folder', ' ❯ 2. No, exit', '', ' Enter to confirm · Esc to cancel']
  it('a menu above a shell prompt or a statusline: refused', () => {
    expect(urgentEmitRefusal(['$ cat mcp.txt', ...MENU, '$ '].join('\n'))).toBe('blocking-menu')
    expect(urgentEmitRefusal([...MENU, '  Opus 5.5 | ctx 22%'].join('\n'))).toBe('blocking-menu')
  })
  it('a first-run dialog above a shell prompt: refused', () => {
    expect(urgentEmitRefusal(['$ cat trust.txt', ...TRUST, 'user@host:~$ '].join('\n'))).toBe('first-run')
  })
})

describe('cc6ba6e0: only the key-sending callers use the last-line anchor', () => {
  const src = (f: string) => readFileSync(join(here, '..', 'web', f), 'utf-8')
  it('channel-monitor answers/Escapes and answerFirstRunGates walk on last-line matches', () => {
    expect(src('channel-monitor.ts')).toContain("detectsFirstRunGate(pane, 'last-line')")
    expect(src('channel-monitor.ts')).toContain("detectsBlockingMenu(pane, 'last-line')")
    expect(src('agent-process.ts')).toContain("detectsFirstRunGate(pane, 'last-line')")
  })
  it('the refusing guards do not', () => {
    for (const f of ['message-router.ts', 'schedule-runner.ts', 'channel-mcp-reconnect.ts']) {
      expect(src(f), f).not.toContain("'last-line'")
    }
  })
})

describe('M1: both guard directives are sent with the emit guard', () => {
  it('every sendSystemDirective call in the runner carries { emitGuard: urgentEmitRefusal }', () => {
    const calls = runner.split('sendSystemDirective(').slice(1)
    expect(calls.length).toBe(2)
    for (const c of calls) {
      const body = c.slice(0, c.indexOf('\n        )'))
      expect(body).toMatch(/\{ emitGuard: urgentEmitRefusal[ ,}]/)
    }
  })
  it('an inject-resume the guard refused does not cool down: the await-ready state is kept for a retry', () => {
    const i = runner.indexOf("resumeOutcome === 'aborted-guard'")
    expect(i).toBeGreaterThan(-1)
    expect(runner.slice(i, i + 200)).toContain('guardStates.set(name, state)')
  })
})

describe('L2: no two early cooldown exits in a row', () => {
  it('the second cooldown of a chain is decided with pct withheld, and the counter resets on a normal expiry', () => {
    expect(runner).toContain("const earlyBlocked = state.phase === 'cooldown' && (earlyCooldownExits.get(name) ?? 0) >= 1")
    expect(runner).toContain('decideGuard(state, earlyBlocked ? { ...inputs, pct: null } : inputs, cfg)')
    expect(runner).toContain('earlyCooldownExits.delete(name)')
  })
})
