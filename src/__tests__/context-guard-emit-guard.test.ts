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
