#!/usr/bin/env python3
"""LINEXTRACT1122 (card bbc6bad4, Viktor 50275 B1): the two lazy heredoc regexes left on the python hook path are
replaced by linear code that returns the SAME text.

 1. email_extract._heredoc_bodies == [m.group(2) for m in _HEREDOC_BODY_RE.finditer(cmd)]
 2. outgoing-copy-gate._loose_heredoc_first_body == the body of re.search(_HEREDOC) (curl -d @- branch)
 3. _loose_heredoc_cut still == _HEREDOC.sub(r"\\1", cmd) after it became a wrapper over _loose_heredoc_spans
Pinned shapes first (a line that only BEGINS with the word closes the extractor's heredoc, an empty body,
overlapping openers, a non-ASCII word, quoted and <<- openers, a miss followed by a match), then generated strings,
then the 1 MB budget: a send with ~1 MB of unclosed openers through collect_email_envelope('Bash', ...) (what
email-approval-gate.py and outgoing-copy-gate.py call after is_send_invocation said yes) under 2 s, distinct, same
and dash-indented openers; the old regex took 3.3 s at 158 KB, x4 per doubling.

Run: python3 <thisfile>   Exit 0 = all pass.
"""
import importlib.util
import os
import random
import re
import sys
import time

HOOKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'hooks')
sys.path.insert(0, HOOKS)
os.environ.setdefault('LEDGER_DB_PATH', '/nonexistent/claudeclaw.db')


def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HOOKS, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ee = load('email_extract_linear_t', 'email_extract.py')
gate = load('occ_linear_t', 'outgoing-copy-gate.py')
REF_FIRST = re.compile(r"<<-?\s*'?(\w+)'?[^\n]*\n(.*?)\n\1(?=\s|$)", re.S)
fails = []


def check(label, ok, detail=''):
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', label, '' if ok else ' -- ' + detail))
    if not ok:
        fails.append(label)


def ref_bodies(s):
    return [m.group(2) for m in ee._HEREDOC_BODY_RE.finditer(s)]


def ref_first(s):
    m = REF_FIRST.search(s)
    return m.group(2) if m else None


PINNED = [
    "cat <<EOF\nhello\nEOF\n",
    "cat <<EOF\nhello\nEOFx\n",            # \n\1 has no lookahead: a line BEGINNING with the word closes it
    "cat <<E\n\nE\n",                       # an empty body
    "cat <<E\nE\n",                         # the opener's own newline is no closing newline
    "x <<<<E\nbody\nE\n",                   # overlapping openers
    "x <<E<<F\nbody\nF\nE\n",
    "cat <<'EOF'\nquoted\nEOF\n",
    "cat <<-EOF\n\tdash\n\tEOF\nEOF\n",
    "cat <<ét\nbody\nét\n",      # a non-ASCII \\w word
    "x <<A\nno end\ny <<B\nbody\nB\n",      # a miss, then a match
    "x <<A\nb\nA\n<<A\nc\nA\n",             # two matches, the second after the first's end
    "x <<A\nb\nAB\nA\n",                    # the first line beginning with the word wins (lazy)
    "x <<AB\nb\nA\nAB\n",
    "<<\nE\nbody\nE\n",                     # \\s* takes the newline before the word
    "x <<E y\nbody\nE\n",                   # extractor: no text after the word; the cut: [^\\n]* allows it
    "",
    "no heredoc at all",
]
for s in PINNED:
    check('bodies pinned %r' % s[:28], ee._heredoc_bodies(s) == ref_bodies(s),
          '%r != %r' % (ee._heredoc_bodies(s), ref_bodies(s)))
    check('first body pinned %r' % s[:28], gate._loose_heredoc_first_body(s) == ref_first(s),
          '%r != %r' % (gate._loose_heredoc_first_body(s), ref_first(s)))
    check('cut pinned %r' % s[:28], gate._loose_heredoc_cut(s) == gate._HEREDOC.sub(r"\1", s))

TOK = ['<<', '<<', '<<-', "'", '"', 'E', 'E', 'EOF', 'EO', 'Ex', 'EOFx', 'a', ' ', '\n', '\n', '\n', '\t', '<', '-',
       '_1', 'é', '٣', ' ', 'x ', ';', '\nE', '\nEOF', '\nE\n', '\x1c']
rnd = random.Random(1122)
bad = [0, 0, 0]
first = [None, None, None]
for _ in range(40000):
    s = ''.join(rnd.choice(TOK) for _ in range(rnd.randint(1, 14)))
    for i, (got, want) in enumerate(((ee._heredoc_bodies(s), ref_bodies(s)),
                                     (gate._loose_heredoc_first_body(s), ref_first(s)),
                                     (gate._loose_heredoc_cut(s), gate._HEREDOC.sub(r"\1", s)))):
        if got != want:
            bad[i] += 1
            first[i] = first[i] or s
check('generated: _heredoc_bodies == finditer reference on 40000 strings', bad[0] == 0, '%d, e.g. %r' % (bad[0], first[0]))
check('generated: _loose_heredoc_first_body == search reference on 40000 strings', bad[1] == 0,
      '%d, e.g. %r' % (bad[1], first[1]))
check('generated: _loose_heredoc_cut == sub reference on 40000 strings', bad[2] == 0, '%d, e.g. %r' % (bad[2], first[2]))

SEND = 'send' + 'mail -t a@b.hu < /dev/null\n'
SHAPES = {
    'distinct unclosed openers': SEND + ''.join('x <<Q%d\n' % i for i in range(110000)),
    'same unclosed opener': SEND + 'x <<Q\n' * 170000,
    'dash-indented unclosed openers': SEND + ''.join('\tx <<-Q%d\n' % i for i in range(90000)),
    'distinct openers, each closed by a longer line only': SEND + ''.join('x <<Q%d\nQ%dz\n' % (i, i) for i in range(60000)),
}
for name, c in SHAPES.items():
    t = time.perf_counter()
    env = ee.collect_email_envelope('Bash', {'command': c})
    dt = time.perf_counter() - t
    check('1 MB budget: collect_email_envelope, %s (%d bytes) %.2f s < 2 s' % (name, len(c), dt),
          dt < 2.0 and isinstance(env, dict), 'took %.2f s' % dt)
c = 'curl -s --data-binary @- http://localhost:1/x <<E\n' + ''.join('x <<Q%d\n' % i for i in range(110000))
t = time.perf_counter()
gate._loose_heredoc_first_body(c)
dt = time.perf_counter() - t
check('1 MB budget: _loose_heredoc_first_body after curl -d @- (%d bytes) %.2f s < 2 s' % (len(c), dt), dt < 2.0)

if fails:
    print('\n%d FAIL: %s' % (len(fails), '; '.join(fails[:5])))
    sys.exit(1)
print('\nAll email-extract linear tests passed.')
