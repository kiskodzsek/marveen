#!/usr/bin/env python3
"""Tests for mcp-pin-run.py: a throw-away dir with a tiny script; nothing outside it is read or run.
Run: python3 -I scripts/__tests__/mcp-pin-run.test.py"""
import hashlib
import os
import subprocess
import sys
import tempfile

RUN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'mcp-pin-run.py')
PY = sys.executable


def sh(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def run(args):
    p = subprocess.run([PY, '-I', RUN] + args, capture_output=True, text=True, timeout=20)
    return p.returncode, p.stdout, p.stderr


def main():
    out = []
    with tempfile.TemporaryDirectory() as d:
        d = os.path.realpath(d)
        srv = os.path.join(d, 'srv.py')
        lib = os.path.join(d, 'lib.mjs')
        open(srv, 'w').write('print("STARTED")\n')
        open(lib, 'w').write('export const x = 1;\n')
        ok_pins = [f'{sh(srv)}={srv}', f'{sh(lib)}={lib}']

        rc, so, _ = run(ok_pins + ['--', PY, '-I', srv])
        out.append(('match: the server starts (exec)', rc == 0 and so.strip() == 'STARTED'))

        rc, so, se = run([f'{"0" * 64}={srv}', f'{sh(lib)}={lib}', '--', PY, '-I', srv])
        out.append(('changed server file: 78, not started', rc == 78 and 'STARTED' not in so and 'srv.py' in se))

        rc, so, se = run([f'{sh(srv)}={srv}', f'{"1" * 64}={lib}', '--', PY, '-I', srv])
        out.append(('changed imported lib: 78, not started', rc == 78 and 'STARTED' not in so and 'lib.mjs' in se))

        rc, so, se = run([f'{sh(lib)}={lib}', '--', PY, '-I', srv])
        out.append(('server script not pinned: 78', rc == 78 and 'not pinned' in se and 'STARTED' not in so))

        rc, _, se = run([f'{sh(srv)}={os.path.join(d, "nincs.py")}', '--', PY, '-I', srv])
        out.append(('missing pinned file: 78', rc == 78 and 'unreadable' in se))

        rc, _, se = run([f'{sh(srv)[:16]}={srv}', '--', PY, '-I', srv])
        out.append(('short (16 hex) pin refused: 78', rc == 78 and 'not <64 hex' in se))

        rc, _, se = run([f'{sh(srv)}=srv.py', '--', PY, '-I', srv])
        out.append(('relative pin path refused: 78', rc == 78))

        rc, _, se = run(ok_pins)
        out.append(('no "--": 78', rc == 78 and 'usage' in se))

        rc, _, se = run(ok_pins + ['--', os.path.join(d, 'no-such-binary')])
        out.append(('command that cannot start: 78', rc == 78 and 'cannot start' in se))

        link = os.path.join(d, 'link.py')
        os.symlink(srv, link)
        rc, so, _ = run([f'{sh(srv)}={link}', f'{sh(lib)}={lib}', '--', PY, '-I', srv])
        out.append(('pin through a symlink is checked on the realpath', rc == 0 and so.strip() == 'STARTED'))

        # Viktor 39318 MEDIUM: a pin that is not an argument (vault-resolve.mjs) is checked too
        rc, so, se = run(ok_pins + [f'{"2" * 64}={lib}', '--', PY, '-I', srv])
        out.append(('extra (non-argument) pin mismatch: 78', rc == 78 and 'STARTED' not in so))
        # Viktor 39318 INFO 1: the pinned realpath is what runs, not the symlink named in the command
        rc, so, _ = run([f'{sh(srv)}={link}', f'{sh(lib)}={lib}', '--', PY, '-I', link])
        out.append(('a pinned symlink in the command runs its hashed realpath', rc == 0 and so.strip() == 'STARTED'))
        # the interpreter itself pinned: exec'd by realpath
        pyreal = os.path.realpath(PY)
        rc, so, _ = run(ok_pins + [f'{sh(pyreal)}={pyreal}', '--', PY, '-I', srv])
        out.append(('a pinned interpreter is exec\'d by its realpath', rc == 0 and so.strip() == 'STARTED'))
        rc, so, _ = run(ok_pins + [f'{"3" * 64}={pyreal}', '--', PY, '-I', srv])
        out.append(('a changed interpreter: 78', rc == 78 and 'STARTED' not in so))
        open(srv, 'w').write('print("CHANGED")\n')
        rc, so, se = run(ok_pins + ['--', PY, '-I', srv])
        out.append(('edited after pinning: 78, the stderr has no file content', rc == 78 and 'CHANGED' not in so + se))
    bad = 0
    for name, ok in out:
        print(('PASS ' if ok else 'FAIL ') + name)
        bad += not ok
    print(f'{len(out) - bad}/{len(out)} passed')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
