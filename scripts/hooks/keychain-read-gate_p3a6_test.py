#!/usr/bin/env python3
"""Tests of the card bcadf02a one-time exemption in keychain-read-gate.py (p3a6_exempt).

Kept apart from keychain-read-gate_test.py on purpose: that suite carries the gate's trigger words in its own text, so
an agent shell cannot run it by path (the gate's docstring, card deede5e4); this file has none, so its author can run
it before the push. Run: python3 -I scripts/hooks/keychain-read-gate_p3a6_test.py
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'keychain-read-gate.py')
spec = importlib.util.spec_from_file_location('kc_gate_p3a6', HOOK)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

fails, n = [], 0


def t(name, ok):
    global n
    n += 1
    if not ok:
        fails.append(name)
        print(f'FAIL {name}')


def hook(cmd):
    p = subprocess.run([sys.executable, '-I', HOOK], input=json.dumps({'tool_input': {'command': cmd}}),
                       capture_output=True, text=True, timeout=120)
    return p.returncode


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


U = gate.P3A6_UNTIL
t('the deadline is 2026-11-25 23:59:59 Budapest', U == 1795647599)
t('three pinned files (runner, probe, head module), all under the probe dir',
  [p for p, _ in gate.P3A6_FILES] == [gate.P3A6_DIR + '/run-p3a6.sh', gate.P3A6_DIR + '/indep/probe_e.mts',
                                      gate.P3A6_DIR + '/head8/src/engine/test-sandbox.ts'])
t('every file the pinned command names is pinned', all(
  all(w in {p for p, _ in gate.P3A6_FILES} for w in c.split()[1:4]) for c in gate.P3A6_CMDS))
t('every pinned hash is 64 lowercase hex', all(len(h) == 64 and set(h) <= set('0123456789abcdef') for _, h in gate.P3A6_FILES))

with tempfile.TemporaryDirectory() as tmp:
    tmp = os.path.realpath(tmp)
    files = []
    for i in range(4):
        p = os.path.join(tmp, f'f{i}')
        with open(p, 'w') as f:
            f.write(f'content {i}\n')
        files.append((p, sha(p)))
    C = f'bash {tmp}/run.sh {tmp}/f1 {tmp}/f2 {tmp}/indep-x.txt'
    saved = gate.P3A6_CMDS
    gate.P3A6_CMDS = (C,)
    try:
        t('pinned text, pinned files, at the deadline: passes', gate.p3a6_exempt(C, U, files) is True)
        t('one trailing newline: passes', gate.p3a6_exempt(C + '\n', U - 60, files) is True)
        t('two trailing newlines: no', gate.p3a6_exempt(C + '\n\n', 0, files) is False)
        t('one second after the deadline: no', gate.p3a6_exempt(C, U + 1, files) is False)
        t('a command before it: no', gate.p3a6_exempt('cd /tmp && ' + C, 0, files) is False)
        t('a command after it: no', gate.p3a6_exempt(C + '; true', 0, files) is False)
        t('another output file: no', gate.p3a6_exempt(C.replace('indep-x', 'indep-y'), 0, files) is False)
        t('a leading blank: no', gate.p3a6_exempt(' ' + C, 0, files) is False)
        t('not a string / no time: no', gate.p3a6_exempt(None, 0, files) is False and gate.p3a6_exempt(C, None, files) is False)
        with open(files[2][0], 'a') as f:
            f.write('x')
        t('one file changed by a byte: no', gate.p3a6_exempt(C, 0, files) is False)
        with open(files[2][0], 'w') as f:
            f.write('content 2\n')
        t('the file restored: passes again', gate.p3a6_exempt(C, 0, files) is True)
        real = files[1][0]
        os.rename(real, real + '.real')
        os.symlink(real + '.real', real)
        t('a file replaced by a link to the same content: no', gate.p3a6_exempt(C, 0, files) is False)
        os.unlink(real)
        os.rename(real + '.real', real)
        os.mkdir(os.path.join(tmp, 'd'))
        os.symlink(os.path.join(tmp, 'd'), os.path.join(tmp, 'ld'))
        q = os.path.join(tmp, 'd', 'g')
        with open(q, 'w') as f:
            f.write('g\n')
        via_link = [files[0], files[1], files[2], (os.path.join(tmp, 'ld', 'g'), sha(q))]
        t('a linked directory on the path: no', gate.p3a6_exempt(C, 0, via_link) is False)
        try:
            r = gate.p3a6_exempt(C, 0, files[:3] + [(os.path.join(tmp, 'd'), files[3][1])])
        except OSError:
            r = 'raised'
        t('a directory in place of a file: no', r is False)
        # a FIFO would make open() wait for a writer: the hook would hang until its watchdog; it must be refused unopened
        fifo = os.path.join(tmp, 'fifo')
        os.mkfifo(fifo)
        code = ('import importlib.util,sys;s=importlib.util.spec_from_file_location("g",sys.argv[1]);g=importlib.util.module_from_spec(s);'
                's.loader.exec_module(g);print(g.p3a6_file_ok(sys.argv[2],"0"*64))')
        try:
            p = subprocess.run([sys.executable, '-I', '-c', code, HOOK, fifo], capture_output=True, text=True, timeout=10)
            r = p.stdout.strip()
        except subprocess.TimeoutExpired:
            r = 'hung'
        t('a FIFO in place of a file: refused without opening it', r == 'False')
        try:
            r = gate.p3a6_exempt(C, 0, files[:3] + [(os.path.join(tmp, 'missing'), files[3][1])])
        except OSError:
            r = 'raised'
        t('a missing file: no pass (False or an error, which main() turns into the usual judgement)', r is not True)
    finally:
        gate.P3A6_CMDS = saved

# The real pins: the files as they are on this machine now (informational when the dir is absent, e.g. in CI).
if os.path.isdir(gate.P3A6_DIR):
    t('the pinned probe files match their pins now', all(gate.p3a6_file_ok(p, h) for p, h in gate.P3A6_FILES))
t('exactly one pinned text (the head run), with Viktor\'s sha256 (53888 line 1)',
  len(gate.P3A6_CMDS) == 1 and tuple(hashlib.sha256(c.encode()).hexdigest() for c in gate.P3A6_CMDS) == gate.P3A6_CMDS_SHA256
  and gate.P3A6_CMDS_SHA256 == ('5fb38b35170b645f89fb698ad73bb628c6130115aafdd102b611385939c0aa8d',))
t('every pinned command runs the pinned runner, nothing before it',
  all(c.startswith('bash ' + gate.P3A6_DIR + '/run-p3a6.sh ') and '\n' not in c for c in gate.P3A6_CMDS))

# Through the hook as Claude Code runs it: a pinned text passes until the deadline (when the files are here), and the
# same text with one byte more is judged as usual (blocked: the module argument carries the trigger).
import time
for c in gate.P3A6_CMDS:
    if os.path.isdir(gate.P3A6_DIR):
        want = 0 if time.time() <= U else 2
        t(f'hook, pinned text: rc {want}', hook(c) == want)
        t('hook, pinned text plus a suffix: blocked', hook(c + ' ') == 2)
if os.path.isdir(gate.P3A6_DIR):
    probe = f'bash {gate.P3A6_DIR}/run-p3a6.sh {gate.P3A6_DIR}/indep/probe_e.mts {gate.P3A6_DIR}/head8/src/engine/test-sandbox.ts {gate.P3A6_DIR}/indep-e/indep-e-unpinned.txt'
    if probe not in gate.P3A6_CMDS:
        t('hook, an unpinned run of the same probe: blocked (the hit the exemption is for)', hook(probe) == 2)
    # Viktor 53888 line 2, the parent-module control: the gate lets it through without the exemption (why it is not
    # pinned); if this ever blocks, the control needs its own decision, not a silent widening here
    parent = (f'bash {gate.P3A6_DIR}/run-p3a6.sh {gate.P3A6_DIR}/indep/probe_e.mts {gate.P3A6_DIR}/head/src/engine/test-sandbox.ts '
              f'{gate.P3A6_DIR}/indep/indep-e-parent.txt')
    if hashlib.sha256(parent.encode()).hexdigest() == '14de16c3b9665441dec11d5a10f28829f291087dec89586e45d7ce6f6c96ca6d':
        t('hook, the parent control (53888 line 2): allowed by the usual rules, not by the exemption',
          parent not in gate.P3A6_CMDS and hook(parent) == 0)
    else:
        t('the parent control text rebuilt here is Viktor\'s line 2', False)

print(f'{"ok" if not fails else "FAIL"}: p3a6 exemption {n - len(fails)}/{n}')
sys.exit(1 if fails else 0)
