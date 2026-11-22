#!/usr/bin/env python3
"""Tests for probe.py: python3 -I scripts/gate-timing/probe_test.py

S1 `run` outside the sandbox refuses (exit 3) and runs no gate: on any OS (on Linux there is no sandbox-exec, so the
   write outside ROOT succeeds and the self-check names it).
S2 the table: a synthetic results.jsonl -> the per-gate row (worst from the confirm rerun, ratio, > 1 s count,
   timeout count), the EXCLUDED row and the fail-open detail line.
S3 macOS only (skipped elsewhere): `all` on this repo's HEAD with one fast gate and a small size -> exit 0, the
   table file is written, the gate has a row, and nothing was written outside the work dir.
Viktor 50112 (independent probe gtp labels in brackets):
S4 R1 the write probe: a symlink at the old fixed escape name is not written through and a file there is kept
   [a9, a10]; a read-only ROOT parent still refuses for the write reason, through HOME [a6].
S5 R1 past the self-check: ROOT=/ and a ROOT that is not a root-* directory are refused (exit 2), no gate runs.
S6 R2 a rev that starts with - is refused by prepare and all (exit 2), no --output file is written [b4, b10].
S7 R3 the table: bad lines are skipped and counted [c2-c4], a gate with only a BASELINE or none [c5, c6], a | and a
   newline cannot shift a cell or forge a row [c8, c9], a failed confirm rerun [c10] and a failed BASELINE [c11] show
   in the rc / timeout cells and on a detail line.
S8 R4 usage errors exit 2 without a traceback: --workers x [d4], a prepare root that is a file [b3] or a dangling
   symlink [b7].
S9 macOS only: inside gatetime.sb a .credentials.json is unreadable (a stand-in file), a plain file is readable.
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


def probe_run(args, env=None, cwd=None):
    e = dict(os.environ, HOME=os.path.join(TMP, 'home')) if env is None else env
    return subprocess.run([sys.executable, '-I', PROBE] + args, capture_output=True, text=True, timeout=120, env=e,
                          cwd=cwd)


def marker_root(name):
    root = os.path.join(TMP, name, 'root')
    os.makedirs(os.path.join(root, 'scripts', 'hooks'))
    marker = os.path.join(root, 'scripts', 'hooks', 'marker-gate.py')
    with open(marker, 'w') as fh:
        fh.write("open(__file__ + '.ran', 'w').write('x')\n")
    return root, marker + '.ran'


def s4_write_probe():
    os.makedirs(os.path.join(TMP, 'home'), exist_ok=True)
    ok = True
    # a symlink and a file at the old fixed name next to ROOT: never written through, never removed
    root, ran = marker_root('s4a')
    victim = os.path.join(TMP, 's4a-victim.txt')
    with open(victim, 'w') as fh:
        fh.write('precious')
    os.symlink(victim, os.path.join(TMP, 's4a', '.gate-timing-escape-test'))
    p = probe_run(['run', root, '--workers', '1', '--size', '10'])
    with open(victim) as fh:
        ok &= p.returncode == 3 and fh.read() == 'precious' and not os.path.exists(ran)
    root, ran = marker_root('s4b')
    pre = os.path.join(TMP, 's4b', '.gate-timing-escape-test')
    with open(pre, 'w') as fh:
        fh.write('user data')
    p = probe_run(['run', root, '--workers', '1', '--size', '10'])
    with open(pre) as fh:
        ok &= p.returncode == 3 and fh.read() == 'user data'
    # a read-only parent: the write reason still fires (HOME is writable), not only the localhost / token checks
    root, ran = marker_root('s4c')
    os.chmod(os.path.join(TMP, 's4c'), 0o555)
    try:
        p = probe_run(['run', root, '--workers', '1', '--size', '10'])
    finally:
        os.chmod(os.path.join(TMP, 's4c'), 0o755)
    ok &= p.returncode == 3 and 'a write outside ROOT succeeded' in p.stderr and not os.path.exists(ran)
    left = [n for n in os.listdir(os.path.join(TMP, 'home')) if n.startswith('.gate-timing-escape-')]
    return ok and not left


def s5_root_shape():
    saved = probe.self_check
    probe.self_check = lambda root: None  # as if sandboxed: the ROOT shape check is the next gate
    try:
        notroot, ran = marker_root('s5')
        return (probe.cmd_run('/', 1, 10, set(), sys.executable) == 2
                and probe.cmd_run(os.path.dirname(notroot), 1, 10, set(), sys.executable) == 2
                and probe.cmd_run(notroot, 1, 10, set(), sys.executable) == 2  # named "root", not "root-..."
                and not os.path.exists(ran))
    finally:
        probe.self_check = saved


def s6_rev_option_refused():
    evil = os.path.join(TMP, 's6-evil.tar')
    p1 = probe_run(['prepare', REPO, '--output=' + evil, os.path.join(TMP, 's6root')])
    p2 = probe_run(['all', REPO, '--output=' + evil, os.path.join(TMP, 's6work')])
    p3 = probe_run(['prepare', REPO, 'no-such-rev-xyz', os.path.join(TMP, 's6root2')])
    return (p1.returncode == 2 and p2.returncode == 2 and p3.returncode == 2 and not os.path.exists(evil)
            and 'Traceback' not in p1.stderr + p2.stderr + p3.stderr)


def s7_table_hostile():
    def row(gate, unit, t=0.01, rc=0, crash=False, err=None, tool='Bash'):
        r = {'gate': gate, 'event': 'PreToolUse', 'tool': tool, 'ctx': 'bare', 'unit': unit, 'bytes': 10, 't': t,
             'rc': rc, 'crash': crash}
        if err:
            r['err'] = err
        return r
    objs = [{'meta': True, 'python': 'py', 'version': 'Python 3', 'size': 10, 'cases': 9, 'workers': 1},
            row('g-gate.py', 'BASELINE'), row('g-gate.py', 'a '),
            {'gate': 'g-gate.py', 'unit': 'x'},                                   # missing keys
            row('b-gate.py', 'BASELINE'),                                         # only a baseline
            row('n-gate.py', 'a '),                                               # no baseline
            row('evil|x|y-gate.py', 'BASELINE'), row('evil|x|y-gate.py', 'a '),   # pipes in the name
            row('e-gate.py', 'BASELINE'),
            row('e-gate.py', 'a ', crash=True, err='boom\n| FAKE-gate.py | Bash | 1 | 1 | 1 | 0.00 | x | | 0 | 0 | 0 | 0 |'),
            row('c-gate.py', 'BASELINE'), row('c-gate.py', 'a ', t=0.9),
            {'confirm': True, 'gate': 'c-gate.py', 'tool': 'Bash', 'ctx': 'bare', 'unit': 'a ', 't_full': 0.9,
             'rc_full': 1, 't_half': 12.0, 'rc_half': 'timeout'},
            row('z-gate.py', 'BASELINE', rc=1), row('z-gate.py', 'BASELINE', rc='timeout', tool='Write'),
            row('z-gate.py', 'a ')]
    path = os.path.join(TMP, 's7.jsonl')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(json.dumps(o, ensure_ascii=False) for o in objs) + '\n{not json\n[1, 2]\n5\n')
    t = probe.cmd_table(path)
    rows = [ln for ln in t.splitlines() if ln.startswith('| ') and not ln.startswith('| gate |')]

    def cells(prefix):
        ln = [r for r in rows if r.startswith('| ' + prefix)]
        return [c.strip() for c in ln[0].split('|')[1:-1]] if len(ln) == 1 else []
    c, z = cells('c-gate.py'), cells('z-gate.py')
    return (all(r.count('|') == 13 for r in rows) and not any(r.startswith('| FAKE') for r in rows)
            and 'SKIPPED 4 line(s)' in t
            and cells('b-gate.py')[2] == '0' and cells('n-gate.py')[3] == '-'
            and c[9:12] == ['1', '0', '1'] and '- c-gate.py: confirm rerun' in t
            and z[9:12] == ['1', '0', '1'] and '- z-gate.py: BASELINE failed' in t)


def s8_usage_errors():
    root_file = os.path.join(TMP, 's8-root-file')
    with open(root_file, 'w') as fh:
        fh.write('x')
    dangling = os.path.join(TMP, 's8-dangling')
    os.symlink(os.path.join(TMP, 's8-nowhere'), dangling)
    ps = [probe_run(['run', os.path.join(TMP, 's8root'), '--workers', 'x']),
          probe_run(['prepare', REPO, 'HEAD', root_file]),
          probe_run(['prepare', REPO, 'HEAD', dangling])]
    return (all(p.returncode == 2 and 'Traceback' not in p.stderr for p in ps)
            and not os.path.exists(os.path.join(TMP, 's8-nowhere')))


def s9_sandbox_denies_credential_reads():
    if sys.platform != 'darwin' or not os.path.exists('/usr/bin/sandbox-exec'):
        return 'skip'
    root = os.path.join(TMP, 's9', 'root-s9')
    os.makedirs(root)
    cred = os.path.join(TMP, 's9', '.credentials.json')   # a stand-in: no real secret is read
    plain = os.path.join(TMP, 's9', 'plain.txt')
    for f in (cred, plain):
        with open(f, 'w') as fh:
            fh.write('marker-s9')
    real = os.path.realpath(root)

    def cat(f):
        return subprocess.run(['/usr/bin/sandbox-exec', '-D', 'ROOT=' + real, '-f', probe.PROFILE, '/bin/cat',
                               os.path.realpath(f)], capture_output=True, text=True, timeout=30)
    c, p = cat(cred), cat(plain)
    return c.returncode != 0 and 'marker-s9' not in c.stdout and p.returncode == 0 and p.stdout == 'marker-s9'


def main():
    failed = 0
    try:
        for fn in (s1_unsandboxed_run_refuses, s2_table, s3_sandboxed_all, s4_write_probe, s5_root_shape,
                   s6_rev_option_refused, s7_table_hostile, s8_usage_errors, s9_sandbox_denies_credential_reads):
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
