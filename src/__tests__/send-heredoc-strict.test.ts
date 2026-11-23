import { describe, it, expect } from 'vitest'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
// @ts-expect-error -- plain .mjs hook script, no types
import { gateDecision, isSendInvocation, sendInReading, sendOnlyByStrictHeredoc, strictHeredocCut, buildHeredocStrictMsg, looseHeredocCut, HEREDOC_RE } from '../../scripts/email-send-gate.mjs'

// HDSTRICT1122 (card bbc6bad4, Viktor 50205 / 50220): the loose heredoc cut of both mail gates could drop a command
// bash runs; the strict second pass only ADDS sends. The shared verdicts live in send-invocation-cases.json (the
// conformance test); this file pins what is NOT shared: the hard-gate's deny kind and its way-out message, the
// opener-comment case both twins now see (SENDCOMMENT1122), and the run time on 1 MB inputs (Viktor 50205 point 2: under 2 s on both gates).

// Viktor 50311 I2: the 2 s bounds are CPU seconds of the gate (python time.process_time, node process.cpuUsage), not
// wall time. Wall time failed once in a sandbox under load 3.3 (6.7 s for the whole it, the shapes 2.0 s each, the
// same bytes on the previous head), a red CI run that costs credit and says nothing about the gate. A quadratic
// regression still shows: it is CPU the gate itself burns.
// Viktor 50318 I1: CPU time is not load-proof either: under load 6-10 the python 1 MB shapes took 2.5-2.6 s of
// process_time (1.5-2.0 s at load 3). The python bound is therefore 4 s of CPU: the regressions these tests guard
// against cost 9 s and more at 1 MB (a quadratic shlex token 9.1 s, the lazy heredoc regex 26 s at 165 KB), so 4 s
// still tells them apart, and the hook timeout it protects is 10 s. The JS bound stays 2 s (0.2 s measured).
const PY_CPU = 4

function cpuSeconds(fn: () => unknown): number {
  const t0 = process.cpuUsage()
  fn()
  const d = process.cpuUsage(t0)
  return (d.user + d.system) / 1e6
}

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
    t0 = time.process_time(); v.append(bool(g.is_send_invocation(c))); t.append(time.process_time() - t0)
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

  // SENDFANOUT1123 (round 6): every outside entry starts with a full read budget. A call that spent it must not leave
  // the next call audited: a stale budget would make every later small command a send (or turn the heredoc-strict
  // deny into the plain one, the hook's second looseSendInvocation call).
  it('SENDFANOUT1123: each outside entry refills the read budget, a spent one does not leak into the next call', () => {
    const esc = (s: string) => s.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\$/g, '\\$').replace(/`/g, '\\`')
    let spent = 'true # (( x\n'.repeat(Math.floor((20 * 1024) / 12)) + 'true'
    for (let i = 0; i < 3; i++) spent = 'eval "' + esc(spent) + '"'
    const small = 'cat <<E\nx\nE'
    expect(isSendInvocation(spent), 'the budget is spent').toBe(true)
    expect(sendInReading(small, 0, 'A'), 'sendInReading after a spent budget').toBe(false)
    expect(isSendInvocation(spent)).toBe(true)
    expect(sendOnlyByStrictHeredoc(small), 'sendOnlyByStrictHeredoc after a spent budget').toBe(false)
    // 700 KB of harmless "# ((" lines and a heredoc, no sender: four readings, each with its strict pass, are past the
    // budget (8 x 700 KB > 3 MiB + 2 x 700 KB), so the gate denies; the hook's second, loose-only call reads 700 KB
    // once inside a fresh budget and finds no loose send, so the kind is the heredoc-strict one (a stale budget
    // would make it the plain deny). The wording past the budget is the heredoc-strict one today (the safe side).
    const pad = ': abcdefg # (( x\n'.repeat(Math.floor((700 * 1024) / 18))
    expect(gateDecision('Bash', { command: pad + 'cat <<E\nx\nE' })).toEqual({ deny: true, kind: 'heredoc-strict' })
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

describe('HDSTRICT1122: the opener-comment divergence is gone (SENDCOMMENT1122, card 64d10325)', () => {
  it('opener-comment: both twins see a send after a commented opener line', () => {
    // Until card 64d10325 the python twin missed it (shlex read the comment over the masked newline, so the next
    // line joined it) while the JS twin saw it. The comment is now dropped line by line in both masks; the shape is
    // also a shared row in send-invocation-cases.json.
    const cmd = "cat <<'E' # c\nE\nsendmail -t a@b.hu\n"
    expect(isSendInvocation(cmd)).toBe(true)
    expect(pySend([cmd]).verdicts).toEqual([true])
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
    for (const s of shapes) expect(cpuSeconds(() => isSendInvocation(s))).toBeLessThan(2)
  })

  it('the python copy gate', () => {
    const { seconds } = pySend(shapes)
    for (const s of seconds) expect(s).toBeLessThan(PY_CPU)
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
      let v = false
      expect(cpuSeconds(() => { v = isSendInvocation(s) })).toBeLessThan(2)
      expect(v).toBe(true)
    }
    const { verdicts, seconds } = pySend(sendFirst)
    expect(verdicts).toEqual([true, true])
    for (const s of seconds) expect(s).toBeLessThan(PY_CPU)
  })
})

// LONGTOK1122 (card bbc6bad4 round 3, Viktor 50311 B1): shlex is quadratic in the length of ONE token, so a long
// word after a send ('sendmail a@b.hu ' + 1 MB of 'w': 9.1 s, main 9.8 s) ran past the approval gate's 10 s hook
// timeout. Past a 32 KiB token run the python send check skips shlex and decides on a sender name anywhere in the
// command (an extra audit, never a miss). The JS twin tokenizes in linear time and keeps its exact reading.
describe('LONGTOK1122: a long token after a send stays under the CPU bound on the python gate, and still counts', () => {
  const W = 'w'.repeat(1_000_000)
  const T32 = 'w'.repeat(32 * 1024)
  const cases: Array<[string, string, boolean]> = [
    ['a long word after the send', 'sendmail a@b.hu ' + W, true],
    ['the same word after echo', 'echo ' + W, false],
    ['a 1 MB quoted string with spaces', "echo '" + 'w '.repeat(500_000) + "'", false],
    ['a 1 MB double-quoted string with spaces', 'echo "' + 'w '.repeat(500_000) + '"', false],
    ['a 1 MB quoted string with spaces after the send', "sendmail -t a@b.hu '" + 'w '.repeat(500_000) + "'", true],
    ['a 1 MB operator run', 'echo ' + ';'.repeat(1_000_000), false],
    ['1 MB of newlines (masked to an operator run)', 'echo\n' + '\n'.repeat(1_000_000), false],
    ['graph-mail send with a long argument', 'graph-mail send --to a@b.hu ' + 'w'.repeat(40_000), true],
    ['a shell -c string with a long word', "bash -c 'sendmail a@b.hu " + 'w'.repeat(40_000) + "'", true],
    ['31 tokens just under the bound after the send', 'sendmail a@b.hu ' + Array(31).fill(T32).join(' '), true],
    ['31 tokens just under the bound after echo', 'echo ' + Array(31).fill(T32).join(' '), false],
    ['a long heredoc body line is cut before the bound is read', "cat > n.md <<'E'\n" + W + '\nE', false],
    // the loose cut takes the quoted '<<E' for an opener and drops the next line, the strict pass keeps it (bash runs
    // it): the bound is read on the strict text too, and the sender name decides there as well
    ['a long token on a line only the strict pass keeps', "echo 'x <<E'\nsendmail a@b.hu " + 'w'.repeat(40_000) + '\nE\n', true],
  ]

  it('every shape: the verdict, and under the CPU bound', () => {
    const { verdicts, seconds } = pySend(cases.map((c) => c[1]))
    cases.forEach(([name, , want], i) => {
      expect([name, verdicts[i]]).toEqual([name, want])
      expect([name, seconds[i] < PY_CPU]).toEqual([name, true])
    })
  })

  it('below the bound the quoted mention is content (exact reading); above it, an audit by design', () => {
    const mention = (n: number) => "echo 'sendmail' " + 'w'.repeat(n)
    expect(pySend([mention(30_000), mention(40_000)]).verdicts).toEqual([false, true])
    // a long command of SHORT tokens keeps the exact reading: the bound is the longest token run, not the length
    expect(pySend(["echo 'sendmail' " + 'w '.repeat(20_000)]).verdicts).toEqual([false])
    // the known twin divergence past the bound: the JS twin keeps reading positions
    expect(isSendInvocation(mention(40_000))).toBe(false)
  })

  // Viktor 50318 B1: the shell removes quotes and backslashes before it runs a word, so a split sender name next to a
  // long token is a send (bash and zsh run all of these); the literal search runs on a dequoted copy.
  it('a split sender name next to a 40 KB token is a send, as it is without the token', () => {
    const PAD = 'x'.repeat(40_000)
    const split = [
      's"e"ndmail a@b.hu ',
      "send''mail a@b.hu ",
      'sendmai\\l a@b.hu ',
      'python3 scripts/support-mail/se""nd.py --to=a@b.hu --subject x ',
      "$'sendmail' a@b.hu ",
    ]
    expect(pySend(split.map((c) => c + PAD)).verdicts).toEqual(split.map(() => true))
    expect(pySend([PAD + ' ; s"e"ndmail a@b.hu']).verdicts).toEqual([true])
    // a backslash-newline inside the name (bash joins it), and a split name on a line only the strict pass keeps
    expect(pySend(['s\\\nendmail a@b.hu ' + PAD, "echo 'x <<E'\ns\"e\"ndmail a@b.hu " + PAD + '\nE\n']).verdicts)
      .toEqual([true, true])
    // the controls: the same shapes without the token take the exact (shlex) reading
    expect(pySend(split.slice(0, 4).map((c) => c.trim())).verdicts).toEqual([true, true, true, true])
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
