#!/usr/bin/env python3
"""scripts/prechecks/patrik-csend-or.sh: the wrapper's contract (Klodel 52701, 52712).

The guard it runs lives outside the repository (agents/kernel/tools/patrik-csend-or/check.py, its own tests), so
a copy of the wrapper is run with that one literal path swapped for a fake guard that exits with a chosen code:
exit 0 (nothing to say) and 10 (nudge sent) -> exactly "SKIP" (no model turn); exit 2 (ERROR), exit 1 (what an
uncaught Python exception gives), any other code, a crash or a missing guard -> the error text and no "SKIP" (the round runs: fail-open); the wrapper always exits 0.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WRAPPER = os.path.join(HERE, '..', 'prechecks', 'patrik-csend-or.sh')
GUARD = '/Users/klodel/marveen/agents/kernel/tools/patrik-csend-or/check.py'
FAILS = []


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + ('' if ok else '  ' + detail))
    if not ok:
        FAILS.append(name)


text = open(WRAPPER, encoding='utf-8').read()
check('the wrapper runs the guard by its literal path, once, with --send',
      text.count(GUARD) == 1 and re.search(re.escape(GUARD) + r' --send\b', text) is not None)
check('python3 -I with no bytecode cache in place of the source', 'python3 -I -X pycache_prefix=/dev/null/x ' in text)
check('no dirname/variable path (the schedule trust walk follows literal paths only)', '$(dirname' not in text)

tmp = tempfile.mkdtemp(prefix='pcs-precheck-')


def run(guard_src):
    fake = os.path.join(tmp, 'guard.py')
    if guard_src is None:
        if os.path.exists(fake):
            os.remove(fake)
    else:
        open(fake, 'w').write(guard_src)
    w = os.path.join(tmp, 'wrapper.sh')
    open(w, 'w').write(text.replace(GUARD, fake))
    p = subprocess.run(['bash', w], capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout.strip()


for code, label in ((0, 'nothing to say'), (10, 'nudge sent')):
    rc, out = run('import sys\nprint("[patrik-csend-or] line")\nsys.exit(%d)\n' % code)
    check('guard exit %d (%s): exactly SKIP, wrapper exit 0' % (code, label), rc == 0 and out == 'SKIP', repr((rc, out)))
for code in (1, 2, 3, 127):
    rc, out = run('import sys\nprint("ERROR patrik-csend-or: boom")\nsys.exit(%d)\n' % code)
    check('guard exit %d: the error text, no SKIP, wrapper exit 0' % code,
          rc == 0 and 'SKIP' not in out and 'ERROR patrik-csend-or: boom' in out, repr((rc, out)))
rc, out = run('raise RuntimeError("crash")\n')
check('a crashing guard: no SKIP (the traceback shows)', rc == 0 and 'SKIP' not in out and 'crash' in out, repr((rc, out)))
rc, out = run(None)
check('a missing guard: no SKIP', rc == 0 and out != 'SKIP' and 'SKIP' not in out.split('\n'), repr((rc, out)))
rc, out = run('import sys\nprint("\\n".join("L%d" % i for i in range(20)))\nsys.exit(2)\n')
check('a long error: at most 5 lines reach the round', rc == 0 and len(out.split('\n')) == 5 and 'SKIP' not in out,
      repr((rc, out)))

print('%d FAIL' % len(FAILS))
sys.exit(1 if FAILS else 0)
