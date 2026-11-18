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
ok('portal.e-szigno.hu over https is allowed (the srv redirect target, Juró 47392)', szl.host_ok('https://portal.e-szigno.hu/x'))
DENY = [
    ('plain http', 'http://srv.e-szigno.hu/eszamlak'),
    ('the bare domain', 'https://e-szigno.hu/eszamlak'),
    ('another subdomain', 'https://www.e-szigno.hu/eszamlak'),
    ('a lookalike suffix', 'https://srv.e-szigno.hu.evil.example/eszamlak'),
    ('a lookalike prefix', 'https://evil-srv.e-szigno.hu/eszamlak'),
    ('userinfo in front of another host', 'https://srv.e-szigno.hu@evil.example/eszamlak'),
    ('microsec.hu (not asked for)', 'https://microsec.hu/szamla.pdf'),
    ('no scheme', 'srv.e-szigno.hu/eszamlak'),
    ('portal over plain http', 'http://portal.e-szigno.hu/x'),
    ('a portal lookalike suffix', 'https://portal.e-szigno.hu.evil.example/x'),
    ('a portal lookalike prefix', 'https://evil-portal.e-szigno.hu/x'),
    ('a deeper portal subdomain', 'https://a.portal.e-szigno.hu/x'),
    ('userinfo portal in front of another host', 'https://portal.e-szigno.hu@evil.example/x'),
]
for name, url in DENY:
    ok(f'denied: {name}', not szl.host_ok(url), url)
# the hosts that were there before stay
for h in ('app.billingo.hu', 'api.billingo.hu', 'www.innvoice.hu', 'innvoice.hu', 'www.szamlazz.hu', 'szamlazz.hu',
          'www.szamlazoprogram.hu', 'szamlazoprogram.hu'):
    ok(f'unchanged: {h}', szl.host_ok(f'https://{h}/x'))
ok('the allowlist grew by exactly two hosts (srv, portal)', len(szl.ALLOWED) == 10, sorted(szl.ALLOWED))


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
    # --- the real opener path (Viktor 47352): a fake https handler answers, the script's own redirect handler runs
    szl.urllib.request.urlopen = real
    import email.message
    import urllib.response
    hits, ROUTES = [], {}

    class Fake(szl.urllib.request.BaseHandler):
        handler_order = 100

        def _open(self, req):
            u = req.full_url
            hits.append(szl.urllib.parse.urlparse(u).scheme + '://' + req.host)
            code, body, loc, ctype = ROUTES.get(u, (200, b'%PDF-1.7 ok', None, 'application/pdf'))
            h = email.message.Message()
            h['Content-Type'] = ctype
            if loc:
                h['Location'] = loc
            r = urllib.response.addinfourl(io.BytesIO(body), h, u, code)
            r.msg = 'x'
            return r
        https_open = _open
        http_open = _open

    # R0 (Viktor 47372 I1): the module itself installs the checking opener; in production get() calls the global
    # urlopen, so without that line R1/R2 would silently come back (mutant r01 was green before this row)
    ok('R0 the module installs _Redir in the global opener',
       any(isinstance(h, szl._Redir) for h in getattr(szl.urllib.request._opener, 'handlers', [])))
    szl.urllib.request.install_opener(szl.urllib.request.build_opener(Fake(), szl._Redir))
    S0 = 'https://srv.e-szigno.hu/eszamlak&wac=AA'

    def main_res(target, routes):
        ROUTES.clear()
        ROUTES.update(routes)
        hits.clear()
        sys.argv = ['szamla-letolto.py', S0, target]
        try:
            szl.main()
            return 'saved'
        except SystemExit:
            return 'refused'

    K = os.path.join(home, 'Konyveles')
    # R1: an allowed host redirects off the list and back: stops at the first hop, the off-list host gets no request
    t = os.path.join(K, 'r1.pdf')
    res = main_res(t, {S0: (302, b'', 'https://evil.example/c', 'text/html'),
                       'https://evil.example/c': (302, b'', 'https://srv.e-szigno.hu/final.pdf', 'text/html')})
    ok('R1 off-list redirect hop: refused before it is requested',
       (res, hits, os.path.exists(t)) == ('refused', ['https://srv.e-szigno.hu'], False), (res, hits))
    # R2: a plain-http hop in the chain stops too
    res = main_res(t, {S0: (302, b'', 'http://srv.e-szigno.hu/x', 'text/html'),
                       'http://srv.e-szigno.hu/x': (302, b'', 'https://srv.e-szigno.hu/final.pdf', 'text/html')})
    ok('R2 plain-http redirect hop: refused', (res, hits) == ('refused', ['https://srv.e-szigno.hu']), (res, hits))
    # control: an on-list redirect is followed
    res = main_res(t, {S0: (302, b'', 'https://srv.e-szigno.hu/final.pdf', 'text/html')})
    ok('on-list redirect is followed and saved', res == 'saved' and hits == ['https://srv.e-szigno.hu'] * 2, (res, hits))
    # R11 (Juró 47392, KE26/83900): the srv link redirects to portal.e-szigno.hu -- followed and saved
    t = os.path.join(K, 'r11.pdf')
    res = main_res(t, {S0: (302, b'', 'https://portal.e-szigno.hu/szamla/AA', 'text/html')})
    ok('R11 srv -> portal redirect is followed and saved',
       (res, hits, os.path.exists(t)) == ('saved', ['https://srv.e-szigno.hu', 'https://portal.e-szigno.hu'], True),
       (res, hits))
    # R12: the portal redirecting on to an off-list e-szigno host still stops before that hop is requested
    t = os.path.join(K, 'r12.pdf')
    res = main_res(t, {S0: (302, b'', 'https://portal.e-szigno.hu/szamla/AA', 'text/html'),
                       'https://portal.e-szigno.hu/szamla/AA': (302, b'', 'https://www.e-szigno.hu/x.pdf', 'text/html')})
    ok('R12 portal -> off-list hop refused',
       (res, hits, os.path.exists(t)) == ('refused', ['https://srv.e-szigno.hu', 'https://portal.e-szigno.hu'], False),
       (res, hits))
    # R5: on an HTML page only the on-list download link is followed
    t = os.path.join(K, 'r5.pdf')
    res = main_res(t, {S0: (200, b'<a href="https://evil.example/download.pdf">x</a><a href="/letolt/1">y</a>', None,
                            'text/html')})
    ok('R5 html: only the on-list link is followed', (res, hits) == ('saved', ['https://srv.e-szigno.hu'] * 2),
       (res, hits))
    # R7: a symlink inside ~/Konyveles pointing out is refused (realpath)
    lnk = os.path.join(K, 'l.pdf')
    os.symlink(os.path.join(home, 'outside.pdf'), lnk)
    res = main_res(lnk, {})
    ok('R7 symlink out of ~/Konyveles refused', (res, os.path.exists(os.path.join(home, 'outside.pdf')))
       == ('refused', False))
    # R8: a non-.pdf target is refused
    t = os.path.join(K, 'r8.txt')
    ok('R8 non-pdf target refused', (main_res(t, {}), os.path.exists(t)) == ('refused', False))
    # R9: the HTML path's download link answers non-PDF: nothing saved
    t = os.path.join(K, 'r9.pdf')
    res = main_res(t, {S0: (200, b'<a href="/letolt/9">y</a>', None, 'text/html'),
                       'https://srv.e-szigno.hu/letolt/9': (200, b'<html>no</html>', None, 'text/html')})
    ok('R9 html path, a non-PDF answer is not saved', (res, os.path.exists(t)) == ('refused', False))
    # R10: a sibling directory sharing the prefix (~/KonyvelesX) is refused
    os.makedirs(os.path.join(home, 'KonyvelesX'), exist_ok=True)
    t = os.path.join(home, 'KonyvelesX', 'r10.pdf')
    ok('R10 ~/KonyvelesX sibling refused', (main_res(t, {}), os.path.exists(t)) == ('refused', False))
finally:
    szl.urllib.request.urlopen = real
    shutil.rmtree(home, ignore_errors=True)

print(f'---\n{N - FAILS}/{N} passed')
sys.exit(1 if FAILS else 0)
