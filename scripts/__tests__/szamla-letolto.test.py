#!/usr/bin/env python3
"""Tests for scripts/szamla-letolto.py (card b5f36cf6): the host allowlist, the redirect check and the target rule.

Hermetic: no network (urlopen is replaced), no file written outside a throwaway HOME.
Run: python3 -I scripts/__tests__/szamla-letolto.test.py
"""
import importlib.util
import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), 'szamla-letolto.py')

home = tempfile.mkdtemp(prefix='szamla-letolto-')
os.makedirs(os.path.join(home, 'Konyveles'))
os.environ['HOME'] = home  # ROOT = ~/Konyveles is read at import time
spec = importlib.util.spec_from_file_location('szl', SCRIPT)
szl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(szl)

FAILS = 0
N = 0


def ok(name, cond, detail=''):
    global FAILS, N
    N += 1
    print(('PASS  ' if cond else 'FAIL  ') + name + ('' if cond or not detail else f'  -- {detail}'))
    if not cond:
        FAILS += 1


# --- host_ok: the new host, exact match only (Klodel 27131: https://srv.e-szigno.hu/eszamlak&wac=...)
ok('srv.e-szigno.hu over https is allowed', szl.host_ok('https://srv.e-szigno.hu/eszamlak&wac=00ff'))
ok('srv.e-szigno.hu, upper case host is allowed (urlparse folds it)', szl.host_ok('https://SRV.E-Szigno.HU/eszamlak'))
DENY = [
    ('plain http', 'http://srv.e-szigno.hu/eszamlak'),
    ('the bare domain', 'https://e-szigno.hu/eszamlak'),
    ('another subdomain', 'https://www.e-szigno.hu/eszamlak'),
    ('a lookalike suffix', 'https://srv.e-szigno.hu.evil.example/eszamlak'),
    ('a lookalike prefix', 'https://evil-srv.e-szigno.hu/eszamlak'),
    ('userinfo in front of another host', 'https://srv.e-szigno.hu@evil.example/eszamlak'),
    ('microsec.hu (not asked for)', 'https://microsec.hu/szamla.pdf'),
    ('no scheme', 'srv.e-szigno.hu/eszamlak'),
]
for name, url in DENY:
    ok(f'denied: {name}', not szl.host_ok(url), url)
# the hosts that were there before stay
for h in ('app.billingo.hu', 'api.billingo.hu', 'www.innvoice.hu', 'innvoice.hu', 'www.szamlazz.hu', 'szamlazz.hu',
          'www.szamlazoprogram.hu', 'szamlazoprogram.hu'):
    ok(f'unchanged: {h}', szl.host_ok(f'https://{h}/x'))
ok('the allowlist grew by exactly one host', len(szl.ALLOWED) == 9, sorted(szl.ALLOWED))


# --- get(): a redirect away from the allowlist stops, before the body is used
class Resp(io.BytesIO):
    def __init__(self, body, final, ctype='application/pdf'):
        super().__init__(body)
        self._final = final
        self.headers = {'Content-Type': ctype}

    def geturl(self):
        return self._final

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake(body, final):
    def urlopen(req, timeout=30):
        return Resp(body, final)
    return urlopen


real = szl.urllib.request.urlopen
try:
    szl.urllib.request.urlopen = fake(b'%PDF-1.7 x', 'https://evil.example/a.pdf')
    try:
        szl.get('https://srv.e-szigno.hu/eszamlak&wac=1')
        ok('redirect to another host stops', False, 'no exit')
    except SystemExit as e:
        ok('redirect to another host stops', 'átirányítás' in str(e), str(e))
    szl.urllib.request.urlopen = fake(b'%PDF-1.7 x', 'https://srv.e-szigno.hu/eszamlak/letolt.pdf')
    body, _, final = szl.get('https://srv.e-szigno.hu/eszamlak&wac=1')
    ok('same-host answer is returned', body.startswith(b'%PDF') and final.startswith('https://srv.e-szigno.hu/'))
    try:
        szl.get('https://www.e-szigno.hu/eszamlak')
        ok('a not allowed start host stops before any request', False, 'no exit')
    except SystemExit as e:
        ok('a not allowed start host stops before any request', 'TILTOTT host' in str(e), str(e))

    # --- main(): the target rule holds for the new host too
    szl.urllib.request.urlopen = fake(b'%PDF-1.7 x', 'https://srv.e-szigno.hu/eszamlak')
    outside = os.path.join(home, 'Downloads', 'x.pdf')
    sys.argv = ['szamla-letolto.py', 'https://srv.e-szigno.hu/eszamlak&wac=1', outside]
    try:
        szl.main()
        ok('a target outside ~/Konyveles is refused', False, 'no exit')
    except SystemExit as e:
        ok('a target outside ~/Konyveles is refused', 'Konyveles' in str(e) and not os.path.exists(outside), str(e))
    inside = os.path.join(home, 'Konyveles', '_besorolando', 'microsec.pdf')
    sys.argv = ['szamla-letolto.py', 'https://srv.e-szigno.hu/eszamlak&wac=1', inside]
    szl.main()
    ok('a PDF from the new host is saved under ~/Konyveles', open(inside, 'rb').read().startswith(b'%PDF'))
finally:
    szl.urllib.request.urlopen = real
    shutil.rmtree(home, ignore_errors=True)

print(f'---\n{N - FAILS}/{N} passed')
sys.exit(1 if FAILS else 0)
