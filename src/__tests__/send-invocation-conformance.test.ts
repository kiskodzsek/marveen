import { describe, it, expect } from 'vitest'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
// @ts-expect-error -- plain .mjs hook script, no types
import { isSendInvocation, sendInReading } from '../../scripts/email-send-gate.mjs'

// SUBGATEPOZ822 / msg 14289: the same command-position recognition now lives
// in TWO languages, in two files (the main-agent copy gate in python, the
// sub-agent hard-gate in JS). Several of today's findings came from exactly
// this pattern -- a parallel copy drifting silently. This test binds the two:
// EVERY case in the shared list runs through BOTH implementations, and both
// must equal the expected verdict. A future fix applied to only one copy
// fails here as a test, instead of surfacing weeks later as an incident.
//
// Deliberately NOT in the shared list: unparseable-input fallbacks. The two
// gates fall back differently by design (copy-gate: strong literals only;
// hard-gate: its full legacy pattern set, because it is a hard-deny that must
// never get weaker on that path) -- each pins its own fallback in its scope
// test. If that difference ever becomes a problem, unify there first.

const ROOT = join(__dirname, '..', '..')
const GATE_PY = join(ROOT, 'scripts', 'hooks', 'outgoing-copy-gate.py')
const CASES = JSON.parse(
  readFileSync(join(ROOT, 'scripts', 'hooks', 'send-invocation-cases.json'), 'utf-8'),
) as { cases: Array<{ name: string; cmd: string; expected: boolean; expected_A?: boolean; expected_PP?: boolean }> }

// One python process for the whole list: stdin carries the JSON cases, stdout
// returns the per-case verdicts. Spawning per-case would be ~30x slower.
function pythonVerdicts(cmds: string[]): Array<[boolean, boolean, boolean]> {
  const out = execFileSync('python3', ['-c', `
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("gate", ${JSON.stringify(GATE_PY)})
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
cmds = json.load(sys.stdin)
print(json.dumps([[g.is_send_invocation(c), g._is_send_in_reading(c, 0, 'A'), g._is_send_in_reading(c, 0, 'PP')] for c in cmds]))
`], { encoding: 'utf-8', input: JSON.stringify(cmds) })
  return JSON.parse(out.trim())
}

describe('send-invocation conformance: both gates agree with the shared contract on every case', () => {
  const py = pythonVerdicts(CASES.cases.map((c) => c.cmd))

  CASES.cases.forEach((c, i) => {
    it(`${c.name} -> ${c.expected}`, () => {
      const js = isSendInvocation(c.cmd)
      expect(js, `JS verdict for: ${c.cmd}`).toBe(c.expected)
      expect(py[i][0], `python verdict for: ${c.cmd}`).toBe(c.expected)
      // SENDMODES1122: a row may also pin the "A" reading alone (the comment mask), which the union can hide
      if (c.expected_A !== undefined) {
        expect(sendInReading(c.cmd, 0, 'A'), `JS A reading for: ${c.cmd}`).toBe(c.expected_A)
        expect(py[i][1], `python A reading for: ${c.cmd}`).toBe(c.expected_A)
      }
      // ... and the "PP" reading alone (a word-start (( read as two subshells), e.g. a send only its strict heredoc
      // pass sees, which the A reading also audits for another reason
      if (c.expected_PP !== undefined) {
        expect(sendInReading(c.cmd, 0, 'PP'), `JS PP reading for: ${c.cmd}`).toBe(c.expected_PP)
        expect(py[i][2], `python PP reading for: ${c.cmd}`).toBe(c.expected_PP)
      }
    })
  })

  it('the shared list is non-trivial in both directions', () => {
    expect(CASES.cases.some((c) => c.expected)).toBe(true)
    expect(CASES.cases.some((c) => !c.expected)).toBe(true)
    expect(CASES.cases.length).toBeGreaterThanOrEqual(20)
  })
})
