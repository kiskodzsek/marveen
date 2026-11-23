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
) as { cases: Array<{ name: string; cmd: string; expected: boolean; expected_A?: boolean; expected_PP?: boolean; expected_A1?: boolean }> }

// One python process for the whole list: stdin carries the JSON cases, stdout
// returns the per-case verdicts. Spawning per-case would be ~30x slower.
function pythonVerdicts(cmds: string[]): Array<[boolean, boolean, boolean, boolean]> {
  const out = execFileSync('python3', ['-c', `
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("gate", ${JSON.stringify(GATE_PY)})
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
cmds = json.load(sys.stdin)
print(json.dumps([[g.is_send_invocation(c), g._is_send_in_reading(c, 0, 'A'), g._is_send_in_reading(c, 0, 'PP'), g._is_send_in_reading(c, 0, 'A1')] for c in cmds]))
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
      // ... and the "A1" reading alone (round 5, Viktor 50388 R1: a lone ) after (( turns the A into a P)
      if (c.expected_A1 !== undefined) {
        expect(sendInReading(c.cmd, 0, 'A1'), `JS A1 reading for: ${c.cmd}`).toBe(c.expected_A1)
        expect(py[i][3], `python A1 reading for: ${c.cmd}`).toBe(c.expected_A1)
      }
    })
  })

  // Round 5 (Viktor 50388 R1): the R1 shape below and above the python twin's 256 KiB multi-reading bound, padded
  // with short-token lines (no token run past the 32 KiB long-token bound). Below it, both twins see the send in
  // the A1 reading; above it, the python twin decides on the sender literal, the JS twin still runs every reading.
  it('the R1 shape is a send below and above the 256 KiB bound, in the A1 reading where it is read', () => {
    const tail = "((true) ) # it's\n(( 1 # 2 )); sendmail a@b.hu # '"
    const pad = (target: number) => {
      const line = ': ' + 'abcdefg '.repeat(12) + '\n'
      const room = target - tail.length
      const k = Math.floor((room - 10) / line.length)
      return line.repeat(k) + ': ' + 'b'.repeat(room - k * line.length - 3) + '\n' + tail
    }
    const below = pad(256 * 1024 - 16)
    const above = pad(256 * 1024 + 16)
    expect(below.length).toBe(256 * 1024 - 16)
    expect(above.length).toBe(256 * 1024 + 16)
    const pv = pythonVerdicts([below, above])
    expect(pv[0][0], 'python, below the bound').toBe(true)
    expect(pv[0][3], 'python A1 reading, below the bound').toBe(true)
    expect(pv[0][2], 'python PP reading, below the bound').toBe(false)
    expect(pv[1][0], 'python, above the bound (sender literal)').toBe(true)
    for (const c of [below, above]) {
      expect(isSendInvocation(c), `JS verdict, length ${c.length}`).toBe(true)
      expect(sendInReading(c, 0, 'A1'), `JS A1 reading, length ${c.length}`).toBe(true)
      expect(sendInReading(c, 0, 'A'), `JS A reading, length ${c.length}`).toBe(false)
    }
  })

  // Round 5 (Viktor 50388 M3): the documented fail-opens stay pinned in the shared list, and the module docstring
  // names each of them in its first 80 lines (a closed one must leave both places, an undocumented one must not
  // be pinned)
  it('every KNOWN-LIMIT row of the shared list is named in the first 80 lines of the python module', () => {
    const head = readFileSync(GATE_PY, 'utf-8').split('\n').slice(0, 80).join('\n')
    const labels = CASES.cases.filter((c) => c.name.startsWith('KNOWN-LIMIT ')).map((c) => c.name.split(': ').pop()!)
    expect(labels.length).toBe(10)
    for (const l of labels) expect(head, `docstring names ${l}`).toContain(l)
  })

  it('the shared list is non-trivial in both directions', () => {
    expect(CASES.cases.some((c) => c.expected)).toBe(true)
    expect(CASES.cases.some((c) => !c.expected)).toBe(true)
    expect(CASES.cases.length).toBeGreaterThanOrEqual(20)
  })
})
