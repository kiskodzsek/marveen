import { describe, it, expect } from 'vitest'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
// @ts-expect-error -- plain .mjs hook script, no types
import { gateDecision, isSendInvocation, sendOnlyByStrictHeredoc, strictHeredocCut, buildHeredocStrictMsg, looseHeredocCut, HEREDOC_RE } from '../../scripts/email-send-gate.mjs'

// HDSTRICT1122 (card bbc6bad4, Viktor 50205 / 50220): the loose heredoc cut of both mail gates could drop a command
// bash runs; the strict second pass only ADDS sends. The shared verdicts live in send-invocation-cases.json (the
// conformance test); this file pins what is NOT shared: the hard-gate's deny kind and its way-out message, the known
// twin divergence on a comment, and the run time on 1 MB inputs (Viktor 50205 point 2: under 2 s on both gates).

const ROOT = join(__dirname, '..', '..')
const GATE_PY = join(ROOT, 'scripts', 'hooks', 'outgoing-copy-gate.py')

// The python side reads its input from a temp FILE, not stdin: a full-suite run once left the child blocked in
// read() on its stdin for 18 minutes (no EOF arrived), while the same test was green in the related run. A timeout
// turns any such hang into a failure instead of a stuck suite.
function runPy(script: string, input: unknown): string {
  const dir = mkdtempSync(join(tmpdir(), 'hdstrict-'))
  try {
    const file = join(dir, 'in.json')
    writeFileSync(file, JSON.stringify(input))
    return execFileSync('python3', ['-c', script, file], {
      encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'], maxBuffer: 64 * 1024 * 1024, timeout: 600_000,
    })
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

function pySend(cmds: string[]): { verdicts: boolean[]; seconds: number[] } {
  const out = runPy(`
import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("gate", ${JSON.stringify(GATE_PY)})
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
v, t = [], []
for c in json.load(open(sys.argv[1])):
    t0 = time.perf_counter(); v.append(bool(g.is_send_invocation(c))); t.append(time.perf_counter() - t0)
print(json.dumps({"verdicts": v, "seconds": t}))
`, cmds)
  return JSON.parse(out.trim())
}

describe('HDSTRICT1122: the hard-gate deny for a send only the strict heredoc pass sees', () => {
  it('gives kind heredoc-strict when only the strict pass sees the send, the plain deny otherwise', () => {
    const emptyBody = 'cat <<E\nE\nsendmail -t a@b.hu\nE'
    expect(sendOnlyByStrictHeredoc(emptyBody)).toBe(true)
    expect(gateDecision('Bash', { command: emptyBody })).toEqual({ deny: true, kind: 'heredoc-strict' })
    expect(gateDecision('Bash', { command: 'sendmail -t a@b.hu <<E\nx\nE' })).toEqual({ deny: true })
    expect(gateDecision('Bash', { command: "cat <<'EOF' > n.md\nsendmail is how it worked\nEOF" })).toEqual({ deny: false })
  })

  it('the message names the way out: the text from a file, not a heredoc', () => {
    const msg = buildHeredocStrictMsg()
    expect(msg).toContain('TILTVA')
    expect(msg).toContain('ird a szoveget fajlba')
    expect(msg).toContain('ne heredocbol')
  })

  it('the strict cut keeps the opener line and drops only a body bash surely reads', () => {
    expect(strictHeredocCut("cat <<'E' > f\nbody\nE\necho x")).toBe("cat <<'E' > f\necho x")
    expect(strictHeredocCut('cat <<E\nE\nsendmail a')).toBe('cat <<E\nsendmail a')
    expect(strictHeredocCut('cat <<<E\nsendmail a\nE')).toBe('cat <<<E\nsendmail a\nE')
    expect(strictHeredocCut('echo "<<E"\nsendmail a\nE')).toBe('echo "<<E"\nsendmail a\nE')
    expect(strictHeredocCut('cat <<-E\nx\n\tE\nsendmail a\nE')).toBe('cat <<-E\nsendmail a\nE')
    expect(strictHeredocCut('cat <<E\nunclosed\nsendmail a')).toBe('cat <<E\nunclosed\nsendmail a')
  })

  // Round 2 (Viktor 50275 I1): the python strict cut had no unit of its own (mutant P09, "an unclosed body cuts the
  // rest", lived; bash agrees with that mutant -- an unclosed heredoc runs nothing after it -- so no shared bash row
  // can kill it: the "cut nothing" rule is a design choice that errs toward an extra audit, pinned here per twin).
  it('the python strict cut gives the same text as the JS one on the same units', () => {
    const units = [
      "cat <<'E' > f\nbody\nE\necho x", 'cat <<E\nE\nsendmail a', 'cat <<<E\nsendmail a\nE', 'echo "<<E"\nsendmail a\nE',
      'cat <<-E\nx\n\tE\nsendmail a\nE', 'cat <<E\nunclosed\nsendmail a', '# cat <<E\nsendmail a\nE',
      'cat <<E \\\n; sendmail a\nE', 'cat <<E\nEx\nE\nsendmail a',
    ]
    const out = runPy(`
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("gate", ${JSON.stringify(GATE_PY)})
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
print(json.dumps([g._strict_heredoc_cut(c) for c in json.load(open(sys.argv[1]))]))
`, units)
    expect(JSON.parse(out.trim())).toEqual(units.map((u) => strictHeredocCut(u)))
    expect(strictHeredocCut('cat <<E\nunclosed\nsendmail a')).toBe('cat <<E\nunclosed\nsendmail a')
  })
})

describe('HDSTRICT1122: known twin divergence (not in the shared list; card e00a44b0)', () => {
  it('opener-comment: the python twin misses a send after a commented opener line, the JS twin sees it', () => {
    // shlex reads the comment over the newline, so the next line joins it; the JS tokenizer has no comment
    // handling. Measured on main as well (pre-existing). Pinned here so a fix on either side shows up.
    const cmd = "cat <<'E' # c\nE\nsendmail -t a@b.hu\n"
    expect(isSendInvocation(cmd)).toBe(true)
    expect(pySend([cmd]).verdicts).toEqual([false])
  })
})

describe('HDSTRICT1122: 1 MB inputs stay under 2 s on both gates (Viktor 50205 point 2)', () => {
  const line = 'a line of plain notes text, nothing to run\n'
  const body = line.repeat(Math.floor(1_000_000 / line.length))
  const shapes = [
    "cat > n.md <<'EOF'\n" + body + 'EOF',
    "cat > n.md <<'EOF'\n" + body,
    'cat <<E\nx\nE\n'.repeat(Math.floor(1_000_000 / 12)),
    Array.from({ length: 120_000 }, (_, i) => `x <<Q${i}\n`).join(''),
    'x <<Q\n'.repeat(Math.floor(1_000_000 / 6)),
    "cat > n.md <<'EOF'\n" + "don't\n".repeat(Math.floor(1_000_000 / 6)) + 'EOF',
  ]

  it('the JS hard-gate', () => {
    for (const s of shapes) {
      const t0 = performance.now()
      isSendInvocation(s)
      expect((performance.now() - t0) / 1000).toBeLessThan(2)
    }
  })

  it('the python copy gate', () => {
    const { seconds } = pySend(shapes)
    for (const s of seconds) expect(s).toBeLessThan(2)
  })

  // Viktor 50253 (measured on main: python 165 KB 26 s, the JS hook 693 KB 77 s, a timed-out hook lets the command
  // through): a real send line FIRST, then 1 MB of unclosed openers, distinct and same; both gates must still say
  // send, under 2 s.
  const SEND = 'sendmail -t a@b.hu < /tmp/mail.txt\n'
  const sendFirst = [
    SEND + Array.from({ length: 90_000 }, (_, i) => `x <<Q${i}\n`).join(''),
    SEND + 'x <<Q\n'.repeat(Math.floor(1_000_000 / 6)),
  ]

  it('a send line before 1 MB of unclosed openers: both gates see the send, under 2 s', () => {
    for (const s of sendFirst) {
      const t0 = performance.now()
      expect(isSendInvocation(s)).toBe(true)
      expect((performance.now() - t0) / 1000).toBeLessThan(2)
    }
    const { verdicts, seconds } = pySend(sendFirst)
    expect(verdicts).toEqual([true, true])
    for (const s of seconds) expect(s).toBeLessThan(2)
  })
})

// LOOSELIN1122 (card bbc6bad4): the loose cut was HEREDOC_RE / _HEREDOC.sub, quadratic on unclosed openers (main
// too: a timed-out hook lets the command through). The linear rewrite must give the same text as the regex; the
// regex stays exported as the reference. Generated strings from a small alphabet that hits every branch: prefix
// backtracking of the word (E, EO, EOF), an empty body, whitespace (and newlines) before the word, <<- and quotes,
// many openers on one line, unicode \w and \s differences between the twins.
const LOOSE_ALPHABET = ['<<', '<', '-', "'", ' ', '\n', '\t', 'E', 'EO', 'EOF', 'F', 'a', '\u00e9', '_', '1', ';',
  '\x1c', '\u00a0', '\n\n', '<<-', "<<'E'", '\nE\n', '\nEOF ']
function looseStrings(seed: number, count: number): string[] {
  let x = seed
  const rnd = () => { x = (x * 1103515245 + 12345) % 2147483648; return x / 2147483648 }
  const out: string[] = []
  for (let i = 0; i < count; i++) {
    let t = ''
    const k = Math.floor(rnd() * 41)
    for (let j = 0; j < k; j++) t += LOOSE_ALPHABET[Math.floor(rnd() * LOOSE_ALPHABET.length)]
    out.push(t)
  }
  return out
}
const LOOSE_PINNED = [
  'cat <<EOF\nbody\nEO\nx\nEOF\nsendmail a',
  'cat <<EOF\nbody\nEO x\nsendmail a',
  'cat <<E\nE\nsendmail a\nE',
  'cat <<\n EOF\nbody\nEOF\nsendmail a',
  "cat <<-'E' > f\nbody\nE\necho x",
  'cat <<E; cat <<F; cat <<G\nbody\nF\nsendmail a',
  'x <<Q1\nx <<Q2\nsendmail a',
]

describe('LOOSELIN1122: the linear loose cut gives the regex text on both gates', () => {
  it('the JS hard-gate', () => {
    for (const t of [...LOOSE_PINNED, ...looseStrings(1, 20_000), ...looseStrings(2, 20_000)]) {
      expect(looseHeredocCut(t)).toBe(t.replace(HEREDOC_RE, '$1'))
    }
  })

  it('the python copy gate', () => {
    const cmds = [...LOOSE_PINNED, ...looseStrings(1, 20_000), ...looseStrings(2, 20_000)]
    const out = runPy(`
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("gate", ${JSON.stringify(GATE_PY)})
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
cmds = json.load(open(sys.argv[1]))
bad = [c for c in cmds if g._loose_heredoc_cut(c) != g._HEREDOC.sub(r"\\1", c)]
print(json.dumps({"n": len(cmds), "bad": bad[:5]}))
`, cmds)
    const r = JSON.parse(out.trim())
    expect(r.n).toBe(cmds.length)
    expect(r.bad).toEqual([])
  })
})
