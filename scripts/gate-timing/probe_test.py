#!/usr/bin/env python3
"""Tests for probe.py: python3 -I scripts/gate-timing/probe_test.py

S1 `run` outside the sandbox refuses (exit 3) and runs no gate: on any OS (on Linux there is no sandbox-exec, so the
   write outside ROOT succeeds and the self-check names it).
S2 the table: a synthetic results.jsonl -> the per-gate row (worst from the confirm rerun, ratio, > 1 s count,
   timeout count), the EXCLUDED row and the fail-open detail line.
S3 macOS only (skipped elsewhere): `all` on this repo's HEAD with one fast gate and a small size -> exit 0, the
   table file is written, the gate has a row, and nothing was written outside the work dir.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROBE = os.path.join(HERE, 'probe.py')
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import probe  # noqa: E402

TMP = tempfile.mkdtemp(prefix='gate-timing-test-')


def s1_unsandboxed_run_refuses():
    root = os.path.join(TMP, 's1root')
    os.makedirs(os.path.join(root, 'scripts', 'hooks'))
    marker = os.path.join(root, 'scripts', 'hooks', 'marker-gate.py')
    with open(marker, 'w') as fh:
        fh.write("open(__file__ + '.ran', 'w').write('x')\n")
    p = subprocess.run([sys.executable, '-I', PROBE, 'run', root, '--workers', '1', '--size', '100'],
                       capture_output=True, text=True, timeout=60)
    return p.returncode == 3 and 'NOT SANDBOXED' in p.stderr and not os.path.exists(marker + '.ran')


def s2_table():
    path = os.path.join(TMP, 's2.jsonl')
    rows = [
        {'meta': True, 'python': 'py', 'version': 'Python 3', 'size': 1000, 'cases': 4, 'workers': 1},
        {'gate': 'skip-gate.py', 'excluded': 'not a hook'},
        {'gate': 'a-gate.py', 'event': 'PreToolUse', 'tool': 'Bash', 'ctx': 'bare', 'unit': 'BASELINE', 'bytes': 2,
         't': 0.05, 'rc': 0, 'crash': False},
        {'gate': 'a-gate.py', 'event': 'PreToolUse', 'tool': 'Bash', 'ctx': 'bare', 'unit': '\n', 'bytes': 1000,
         't': 3.0, 'rc': 0, 'crash': False},
        {'gate': 'a-gate.py', 'event': 'PreToolUse', 'tool': 'Bash', 'ctx': 'chain', 'unit': 'x', 'bytes': 1000,
         't': 12.0, 'rc': 'timeout', 'crash': False},
        {'gate': 'a-gate.py', 'event': 'PreToolUse', 'tool': 'Bash', 'ctx': 'bare', 'unit': '(a=', 'bytes': 1000,
         't': 0.1, 'rc': 0, 'crash': True, 'err': 'errlog: internal error, allowed'},
        {'confirm': True, 'gate': 'a-gate.py', 'tool': 'Bash', 'ctx': 'chain', 'unit': 'x', 't_full': 12.0,
         't_half': 3.0},
    ]
    with open(path, 'w') as fh:
        fh.write('\n'.join(json.dumps(r) for r in rows) + '\n')
    t = probe.cmd_table(path)
    row = [ln for ln in t.splitlines() if ln.startswith('| a-gate.py |')]
    return (len(row) == 1 and '| 12.00 |' in row[0] and '| 4.0 |' in row[0] and row[0].endswith('| 2 | 0 | 1 | 1 |')
            and '| skip-gate.py |' in t and 'EXCLUDED: not a hook' in t
            and '- a-gate.py: errlog: internal error, allowed -- 1' in t)


def s3_sandboxed_all():
    if sys.platform != 'darwin' or not os.path.exists('/usr/bin/sandbox-exec'):
        return 'skip'
    work = os.path.join(TMP, 's3work')
    os.makedirs(work)
    before = set(os.listdir(TMP))
    p = subprocess.run([sys.executable, '-I', PROBE, 'all', REPO, 'HEAD', work, '--only', 'zsh-trap-gate.py',
                        '--size', '2000', '--workers', '2'], capture_output=True, text=True, timeout=600)
    tables = [f for f in os.listdir(work) if f.startswith('table-') and f.endswith('.md')]
    text = ''
    if tables:
        with open(os.path.join(work, tables[0]), encoding='utf-8') as fh:
            text = fh.read()
    return (p.returncode == 0 and len(tables) == 1 and '| zsh-trap-gate.py |' in text
            and set(os.listdir(TMP)) == before)


def main():
    failed = 0
    try:
        for fn in (s1_unsandboxed_run_refuses, s2_table, s3_sandboxed_all):
            try:
                ok = fn()
            except Exception as ex:  # a crashing case is a failing case
                print(f'  {fn.__name__}: {ex!r}')
                ok = False
            print(('SKIP ' if ok == 'skip' else 'PASS ' if ok else 'FAIL ') + fn.__name__)
            failed += not ok
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print('failed: %d' % failed)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
