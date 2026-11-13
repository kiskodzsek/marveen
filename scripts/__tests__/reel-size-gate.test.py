#!/usr/bin/env python3
"""scripts/reel-size-gate.py as a gate (retro R4, card 686f1b5f; Viktor 41284 (2)): nothing measured is not a pass,
and a mistyped option is a usage error, not a silently dropped one.

The gate needs numpy (the Mac mini has it); off a numpy host the cases print SKIP: they test the gate's edges, not a
measurement, and the size measurement itself is calibrated on real reels (see the gate's docstring).
Run: python3 -I scripts/__tests__/reel-size-gate.test.py
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GATE = os.path.join(ROOT, 'scripts', 'reel-size-gate.py')

try:
    import numpy  # noqa: F401
except ImportError:
    print('SKIP  reel-size-gate: numpy is not installed on this host')
    sys.exit(0)


def run(*args):
    r = subprocess.run([sys.executable, '-I', GATE, *args], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


fails = 0
cases = 0


def check(name, cond, info=''):
    global fails, cases
    cases += 1
    print(('PASS  ' if cond else 'FAIL  ') + name + ('' if cond else f'  -- {info}'))
    fails += 0 if cond else 1


with tempfile.TemporaryDirectory() as d:
    rc, out = run(d)
    check('an empty frames dir is NOT OK (exit 1)', rc == 1 and 'no measurable frame' in out, f'rc={rc} {out}')
    open(os.path.join(d, 'frame-0001.png'), 'wb').write(b'\x89PNG')
    rc, out = run(d)
    check('frames not named t_<sec>.png measure nothing: exit 1', rc == 1 and 'no measurable frame' in out, f'rc={rc} {out}')
    rc, out = run(d, '--zon', '512,1165')
    check('a mistyped option (--zon) is a usage error (exit 2)', rc == 2 and '--zon' in out, f'rc={rc} {out}')
    rc, out = run(d, '--end')
    check('an option without a value is a usage error (exit 2)', rc == 2, f'rc={rc} {out}')
    rc, out = run('--end', '5')
    check('no source is a usage error (exit 2)', rc == 2, f'rc={rc}')

print(f'{cases - fails}/{cases} pass')
sys.exit(1 if fails else 0)
