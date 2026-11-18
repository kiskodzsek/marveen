#!/usr/bin/env python3
"""Tests for big-read-gate.py (card b073a7e3). Run: python3 -I scripts/hooks/big-read-gate_test.py

The decision table runs in-process; the exit code, the stderr hint and the content-free log run in a child process
on a copy of the gate inside a synthetic tree, so the log lands in that tree's store/, not in the repo's.
The synthetic tree goes under ~/.cache when the temp dir is under /tmp (kapu-subagens-bekotes, Buktatók).
"""
import atexit
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
GATE = os.path.join(HERE, 'big-read-gate.py')
spec = importlib.util.spec_from_file_location('big_read_gate', GATE)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

base = tempfile.gettempdir()
if os.path.realpath(base).startswith(('/tmp', '/private/tmp')):
    base = os.path.join(os.path.expanduser('~'), '.cache')
    os.makedirs(base, exist_ok=True)
TREE = tempfile.mkdtemp(prefix='big-read-gate-test-', dir=base)
atexit.register(shutil.rmtree, TREE, True)

FILES = os.path.join(TREE, 'files')
os.makedirs(FILES)


def mk(name, size):
    p = os.path.join(FILES, name)
    with open(p, 'wb') as f:
        f.write(b'x' * size)
    return p


BIG = mk('big.ts', g.LIMIT_BYTES + 1)
EDGE = mk('edge.ts', g.LIMIT_BYTES)
SMALL = mk('small.md', 100)
BIGPNG = mk('shot.PNG', 5 * g.LIMIT_BYTES)
BIGPDF = mk('doc.pdf', 5 * g.LIMIT_BYTES)
BIGNB = mk('nb.ipynb', 5 * g.LIMIT_BYTES)
TOOLRES = os.path.join(TREE, 'proj', 'tool-results')
os.makedirs(TOOLRES)
SAVED = os.path.join(TOOLRES, 'bzgdgbqgk.txt')
with open(SAVED, 'wb') as f:
    f.write(b'y' * (3 * g.LIMIT_BYTES))
LINK = os.path.join(FILES, 'link-to-big')
os.symlink(BIG, LINK)
# A directory whose own st_size is over the limit (APFS: 700 entries = 22464 bytes, measured 2026-11-18): Read on a
# directory is not a file read, so it must not get the hint.
WIDE = os.path.join(TREE, 'wide')
os.makedirs(WIDE)
for i in range(2000):
    open(os.path.join(WIDE, 'f%05d' % i), 'w').close()


def read(path, **kw):
    inp = {'file_path': path}
    inp.update(kw)
    return {'tool_name': 'Read', 'tool_input': inp, 'cwd': FILES,
            'transcript_path': '/Users/x/marveen/agents/dave/.claude-config/projects/p/s.jsonl'}


CASES = [
    # (name, payload, expected block)
    ('big text file, no limit', read(BIG), True),
    ('saved tool output re-read whole', read(SAVED), True),
    ('symlink to a big file', read(LINK), True),
    ('big file, offset only (still up to 2000 lines)', read(BIG, offset=10), True),
    ('relative path resolved against cwd', read('big.ts'), True),
    ('exactly the limit is allowed', read(EDGE), False),
    ('small file', read(SMALL), False),
    ('explicit limit', read(BIG, limit=120), False),
    ('explicit big limit is a deliberate whole read', read(BIG, offset=1, limit=2000), False),
    ('explicit limit 0 is still explicit', read(BIG, limit=0), False),
    ('image, upper-case extension', read(BIGPNG), False),
    ('pdf', read(BIGPDF, pages='1-3'), False),
    ('notebook', read(BIGNB), False),
    ('directory', read(FILES), False),
    ('directory larger than the limit', read(WIDE) if os.stat(WIDE).st_size > g.LIMIT_BYTES else None, False),
    ('missing file', read(os.path.join(FILES, 'nope.ts')), False),
    ('limit null counts as absent', read(BIG, limit=None), True),
    ('other tool', {'tool_name': 'Bash', 'tool_input': {'command': 'cat ' + BIG}}, False),
    ('Edit on a big file', {'tool_name': 'Edit', 'tool_input': {'file_path': BIG}}, False),
    ('relative path without a usable cwd', {'tool_name': 'Read', 'tool_input': {'file_path': 'big.ts'}}, False),
    ('tool_input not a dict', {'tool_name': 'Read', 'tool_input': 'x'}, False),
    ('file_path not a string', {'tool_name': 'Read', 'tool_input': {'file_path': 7}}, False),
    ('NUL in path', read(BIG + '\x00x'), False),
]

fails = 0
for name, payload, want in CASES:
    if payload is None:  # a file system whose directory size stays small: the case cannot be built here
        print(f'SKIP decide: {name}: directory st_size not over the limit on this file system')
        continue
    got = g.decide(payload)[0]
    if got != want:
        fails += 1
        print(f'FAIL decide: {name}: got block={got}, want {want}')

# The child-process run: a copy of the gate in a synthetic tree, so ROOT (and the log) is that tree.
HOOKS = os.path.join(TREE, 'root', 'scripts', 'hooks')
os.makedirs(HOOKS)
COPY = os.path.join(HOOKS, 'big-read-gate.py')
shutil.copy(GATE, COPY)
LOG = os.path.join(TREE, 'root', 'store', 'big-read-gate', 'gate.jsonl')


def run(stdin):
    p = subprocess.run([sys.executable, '-I', COPY], input=stdin, capture_output=True, text=True, timeout=20)
    return p.returncode, p.stdout, p.stderr


rc, out, err = run(json.dumps(read(BIG)))
if rc != 2 or out or 'big.ts' not in err or 'limit' not in err or 'grep -n' not in err:
    fails += 1
    print(f'FAIL child block: rc={rc} out={out!r} err={err[:200]!r}')
rc, out, err = run(json.dumps(read(BIG, limit=200)))
if rc != 0 or out or err:
    fails += 1
    print(f'FAIL child allow: rc={rc} out={out!r} err={err!r}')
for bad in ('', 'not json', '[1,2]', '{"tool_name": "Read", "tool_input": {"file_path": ' + json.dumps(BIG) + '}'):
    rc, out, err = run(bad)
    if rc != 0:
        fails += 1
        print(f'FAIL child fail-open on {bad[:20]!r}: rc={rc}')

try:
    with open(LOG) as f:
        lines = [json.loads(x) for x in f]
    st = os.stat(LOG)
except OSError as e:
    lines, st = [], None
    fails += 1
    print(f'FAIL log missing: {e}')
if st is not None:
    if len(lines) != 1:
        fails += 1
        print(f'FAIL log: want exactly 1 block line, got {len(lines)}')
    elif set(lines[0]) != {'ts', 'agent', 'size', 'path_sha16'} or lines[0]['agent'] != 'dave' \
            or lines[0]['size'] != g.LIMIT_BYTES + 1 or BIG in json.dumps(lines[0]) or 'big.ts' in json.dumps(lines[0]):
        fails += 1
        print(f'FAIL log content: {lines[0]}')
    if st.st_mode & 0o077:
        fails += 1
        print(f'FAIL log mode: {oct(st.st_mode)}')

# A log path that is a symlink is not followed (O_NOFOLLOW): the block still happens, nothing is written there.
os.remove(LOG)
TARGET = os.path.join(TREE, 'elsewhere.jsonl')
os.symlink(TARGET, LOG)
rc, out, err = run(json.dumps(read(BIG)))
if rc != 2 or os.path.exists(TARGET):
    fails += 1
    print(f'FAIL symlinked log: rc={rc}, target written={os.path.exists(TARGET)}')

# The watchdog fails open: a payload that never ends (stdin held open) is an allow after WATCHDOG_S, not a block.
p = subprocess.Popen([sys.executable, '-I', COPY], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE)
try:
    rc = p.wait(timeout=g.WATCHDOG_S + 10)
except subprocess.TimeoutExpired:
    p.kill()
    rc = 'hung'
p.stdin.close()
p.stdout.close()
p.stderr.close()
if rc != 0:
    fails += 1
    print(f'FAIL watchdog: rc={rc}, want 0 (fail open)')

total = len(CASES) + 9
print(f'big-read-gate: {total - fails}/{total} ok ({sys.version.split()[0]})')
sys.exit(1 if fails else 0)
