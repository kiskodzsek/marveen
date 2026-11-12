#!/usr/bin/env python3
"""Tests for pr-kerdes-gate.py and scripts/pr-kerdes.py (hibanapló 2026-11-11 07:3x, Klodel 37320).

The hook runs as Claude Code runs it (JSON on stdin; exit 0 allow, 2 block) against a throw-away
CLAUDE_PROJECT_DIR; the generator runs with a fake GitHub (no network, no token). Synthetic data only.
Run: python3 -I scripts/hooks/pr-kerdes-gate_test.py
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, 'pr-kerdes-gate.py')
GEN = os.path.join(os.path.dirname(HERE), 'pr-kerdes.py')
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
HEAD = 'a' * 40
FILES = ['src/app/receptkonyv/page.tsx', 'src/app/page.tsx', 'src/app/gyik/page.tsx', 'src/__tests__/x.test.ts']

FAILS = []


def ok(cond, name):
    print(('PASS ' if cond else 'FAIL ') + name)
    if not cond:
        FAILS.append(name)


def run(root, text, files=None, tool='reply', env_extra=None):
    ti = {'chat_id': '-1000000000001', 'text': text}
    if files is not None:
        ti['files'] = files
    env = {'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root, **(env_extra or {})}
    p = subprocess.run([sys.executable, '-I', HOOK],
                       input=json.dumps({'tool_name': f'mcp__plugin_telegram_telegram__{tool}', 'tool_input': ti}),
                       capture_output=True, text=True, env=env, timeout=20)
    return p.returncode, p.stderr


def lhash(paths):
    return hashlib.sha256('\n'.join(sorted(paths)).encode()).hexdigest()


def sheet(root, n, answers, paths=FILES, gen=None, repo='kiskodzsek/marabel', pr=None, lista=None):
    d = os.path.join(root, 'store', 'pr-kerdes')
    os.makedirs(d, exist_ok=True)
    gen = gen or datetime.now(timezone.utc)
    lines = [f'REPO: {repo}', f'PR: {pr if pr is not None else n}', f'HEAD: {HEAD}',
             f'GENERALT: {gen.strftime("%Y-%m-%dT%H:%M:%SZ")}',
             lista if lista is not None else f'LISTA: {len(paths)} {lhash(paths)}']
    lines += [f'FILE: {p} | KEPEN: {answers.get(p, "?")}' for p in paths]
    with open(os.path.join(d, f'{n}.ok'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def images(root):
    a, b = os.path.join(root, 'recept.png'), os.path.join(root, 'fooldal.jpg')
    for p in (a, b):
        open(p, 'wb').write(b'\x89PNG fake')
    return a, b


def full(a, b):
    return {FILES[0]: f'igen {a}', FILES[1]: f'igen {b}', FILES[2]: f'igen {b}',
            FILES[3]: 'nem-vevoi teszt, nem fut a böngészőben'}


def hook_tests():
    with tempfile.TemporaryDirectory() as root:
        a, b = images(root)
        ask = 'A PR #1273 élesítéséhez kérem az OK-t, képek mellékelve. Mehet?'

        ok(run(root, 'Reggelt, a nyomda ma szállít.')[0] == 0, 'no PR number -> allow')
        ok(run(root, 'A #1273 áttekintése folyik, Dave nézi.')[0] == 0, 'PR number without a shipping word -> allow')

        rc, err = run(root, ask, [a])
        ok(rc == 2 and 'store/pr-kerdes/1273.ok' in err and 'pr-kerdes.py init' in err,
           'ask with no sheet -> block, names the sheet and the generator')

        sheet(root, 1273, full(a, b))
        ok(run(root, ask, [a, b])[0] == 0, 'complete sheet, every image attached -> allow')

        # The #1273 incident: one section's picture attached, two other pages changed too.
        rc, err = run(root, ask, [a])
        ok(rc == 2 and 'src/app/page.tsx' in err and 'nincs csatolva' in err,
           'the #1273 shape: only one section picture attached -> block, names the uncovered file')

        # A sheet typed from memory: the two other pages left out.
        sheet(root, 1273, full(a, b), paths=FILES[:1] + FILES[3:], lista=f'LISTA: {len(FILES)} {lhash(FILES)}')
        rc, err = run(root, ask, [a, b])
        ok(rc == 2 and 'nem a generált fájllista' in err, 'FILE lines dropped from the generated list -> block')

        # Same count, one path swapped for one the asker has a picture of: only the hash sees it.
        swapped = [FILES[0], FILES[0].replace('receptkonyv', 'kepeskonyv')] + FILES[2:]
        sheet(root, 1273, {**full(a, b), swapped[1]: f'igen {a}'}, paths=swapped,
              lista=f'LISTA: {len(FILES)} {lhash(FILES)}')
        rc, err = run(root, ask, [a, b])
        ok(rc == 2 and 'nem a generált fájllista' in err, 'a FILE path swapped, count unchanged -> block (LISTA hash)')

        sheet(root, 1273, {**full(a, b), FILES[2]: '?'})
        rc, err = run(root, ask, [a, b])
        ok(rc == 2 and 'gyik/page.tsx: nincs KEPEN' in err, 'an unanswered KEPEN (?) -> block')

        sheet(root, 1273, {**full(a, b), FILES[3]: 'nem-vevoi teszt'})
        ok(run(root, ask, [a, b])[0] == 2, 'nem-vevoi with a too-short reason -> block')

        sheet(root, 1273, {**full(a, b), FILES[0]: f'igen {root}/nincs-ilyen.png'})
        ok(run(root, ask, [a, b])[0] == 2, 'igen with a missing image -> block')

        sheet(root, 1273, {**full(a, b), FILES[0]: 'igen recept.png'})
        ok(run(root, ask, [a, b])[0] == 2, 'igen with a relative path -> block')

        sheet(root, 1273, full(a, b), gen=datetime.now(timezone.utc) - timedelta(hours=13))
        rc, err = run(root, ask, [a, b])
        ok(rc == 2 and 'órás' in err, 'sheet older than 12 h -> block (a push may have come since)')

        sheet(root, 1273, full(a, b), pr=1274)
        ok(run(root, ask, [a, b])[0] == 2, 'sheet PR line of another number -> block')

        sheet(root, 1273, full(a, b), repo='someone/else')
        ok(run(root, ask, [a, b])[0] == 2, 'sheet of a repo outside kiskodzsek -> block')

        sheet(root, 1273, full(a, b))
        ok(run(root, 'élesíthető a #1273? A képek itt.', [a, b])[0] == 0, 'accented ask with a complete sheet -> allow')
        rc, err = run(root, 'ELESITHETO a pr 1273 es a #1280?', [a, b])
        ok(rc == 2 and 'PR #1280' in err and 'PR #1273' not in err, 'two PRs, one without a sheet -> block that one')
        ok(run(root, 'A PR #1280 mehet?', [a, b], tool='edit_message')[0] == 2, 'edit_message is gated the same way')
        # Viktor 37340: the everyday Hungarian forms and the missing shipping words.
        for txt in ('Az 1280-as PR mehet élesbe?', 'az 1280-as pr-t élesíthetjük?', 'A PR-1280 kimehet?',
                    'Kerülhet ki a #1280?', 'Jóváhagyod a PR 1280-at?', 'Indulhat az 1280-as PR?',
                    'Can PR 1280 go live?', 'Ship #1280?', 'Publikálhatjuk a 1280-es PR-t?'):
            rc, err = run(root, txt, [a, b])
            ok(rc == 2 and 'PR #1280' in err, f'trigger form: {txt!r} -> block')
        ok(run(root, 'A galéria PR mehet?', [a, b])[0] == 0, 'a PR named without a number -> not caught (documented)')
        ok(run(root, 'A P​R #1280 m​ehet?', [a, b])[0] == 2, 'zero-width characters do not hide the ask')

        esc = 'A #1280 élesben van, Pulzus mérte 07:40-kor.\nPR-KERDES: nem-keres beszámoló, nem kér döntést'
        ok(run(root, esc, [])[0] == 0, 'escape line with a reason -> allow')
        ok(run(root, 'A #1280 élesben van.\nPR-KERDES: nem-keres info', [])[0] == 2, 'escape line with a short reason -> block')

        open(os.path.join(root, 'store', 'pr-kerdes', '1290.ok'), 'wb').write(b'\xff\xfe\x00broken')
        rc, err = run(root, 'PR #1290 mehet?', [a])
        ok(rc == 2 and 'hibára futott' in err, 'an unreadable sheet fails closed -> block')

        p = subprocess.run([sys.executable, '-I', HOOK], input='not json', capture_output=True, text=True,
                           env={'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root}, timeout=20)
        ok(p.returncode == 0, 'unreadable hook payload -> allow (nothing to check)')


def load_gen(root):
    os.environ['CLAUDE_PROJECT_DIR'] = root
    spec = importlib.util.spec_from_file_location('pr_kerdes', GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake_github(paths, head=HEAD, changed=None, blob=lambda p: hashlib.sha1(p.encode()).hexdigest()):
    calls = []

    def get(path, token):
        calls.append(path)
        assert token == 'tok-synthetic'
        if path.endswith('/pulls/1273'):
            return {'head': {'sha': head}, 'changed_files': len(paths) if changed is None else changed}
        page = int(path.rsplit('page=', 1)[1])
        return [{'filename': p, 'sha': blob(p)} for p in paths[(page - 1) * 100:page * 100]]
    return get, calls


def gen_tests():
    with tempfile.TemporaryDirectory() as root:
        gen = load_gen(root)
        a, b = images(root)
        many = [f'src/app/oldal{i:03d}/page.tsx' for i in range(103)]
        get, calls = fake_github(many)
        gen.init('kiskodzsek/marabel', 1273, False, 'tok-synthetic', get)
        path = os.path.join(root, 'store', 'pr-kerdes', '1273.ok')
        text = open(path, encoding='utf-8').read()
        ok(text.count('FILE: ') == 103 and text.count('KEPEN: ?') == 103 and len(calls) == 3,
           'generator: 103 files over two pages, every KEPEN open')
        ok('tok-synthetic' not in text, 'generator: the token is not in the sheet')
        rc, err = run(root, 'PR #1273 mehet?', [a])
        ok(rc == 2 and 'nincs KEPEN' in err, 'hook: a fresh generated sheet blocks until it is filled')

        filled = text.replace('KEPEN: ?', f'KEPEN: igen {a}')
        open(path, 'w', encoding='utf-8').write(filled)
        ok(run(root, 'PR #1273 mehet?', [a])[0] == 0, 'hook: the generated, filled sheet passes (same LISTA hash)')

        ok(text.count('# SHA: ') == 103, 'generator: every file has its blob sha line')

        # A new push: one file more, one file changed again. Unchanged blobs keep their answer; the changed file
        # and the new one are open (Viktor 37340: a carried-over answer must not look fresh).
        again = many[5]
        get, _ = fake_github(many + ['src/app/uj/page.tsx'], head='b' * 40,
                             blob=lambda p: ('f' * 40) if p == again else hashlib.sha1(p.encode()).hexdigest())
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            gen.init('kiskodzsek/marabel', 1273, False, 'tok-synthetic', get)
        text = open(path, encoding='utf-8').read()
        ok(text.count(f'KEPEN: igen {a}') == 102 and text.count('KEPEN: ?') == 2 and 'HEAD: ' + 'b' * 40 in text
           and f'FILE: {again} | KEPEN: ?' in text and again in buf.getvalue(),
           'generator: re-run after a push keeps unchanged-blob answers, reopens and names the changed file')

        try:
            get, _ = fake_github(many, changed=200)
            gen.init('kiskodzsek/marabel', 1273, False, 'tok-synthetic', get)
            ok(False, 'generator: a short file list is refused')
        except SystemExit as e:
            ok('not writing a partial list' in str(e) and 'HEAD: ' + 'b' * 40 in open(path).read(),
               'generator: a short file list is refused, the old sheet stays')

        for repo, name in (('kiskodzsek/marveen', 'another repo with the same number needs --force'),
                           ('evil/marabel', 'a repo outside kiskodzsek is refused')):
            try:
                gen.init(repo, 1273, False, 'tok-synthetic', fake_github(many)[0])
                ok(False, 'generator: ' + name)
            except SystemExit:
                ok(True, 'generator: ' + name)

        nr = [h for h in gen._OPENER.handlers if isinstance(h, gen._NoRedirect)]
        ok(len(nr) == 1 and nr[0].redirect_request(None, None, 302, 'Found', {}, 'https://elsewhere.example/') is None,
           'generator: the opener does not follow redirects (the token stays on api.github.com)')

        env = {'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root, 'GITHUB_PERSONAL_ACCESS_TOKEN': 'vault:x'}
        p = subprocess.run([sys.executable, '-I', GEN, 'init', 'kiskodzsek/marabel', '1'], capture_output=True,
                           text=True, env=env, timeout=20)
        ok(p.returncode == 2 and 'vault-env-wrapper' in p.stderr, 'generator: an unresolved vault: ref stops before any call')


def wiring_test():
    path = os.environ.get('SETTINGS_JSON') or os.path.join(REPO_ROOT, '.claude', 'settings.json')
    hooks = json.load(open(path, encoding='utf-8'))['hooks']['PreToolUse']
    hit = [e for e in hooks if any('pr-kerdes-gate.py' in h.get('command', '') for h in e.get('hooks', []))]
    m = hit[0]['matcher'] if hit else ''
    ok(len(hit) == 1 and 'mcp__plugin_telegram_telegram__reply' in m and 'mcp__plugin_telegram_telegram__edit_message' in m,
       'wired in .claude/settings.json on telegram reply + edit_message')


if __name__ == '__main__':
    hook_tests()
    gen_tests()
    wiring_test()
    print(f'{"FAILED " + str(len(FAILS)) if FAILS else "ALL PASS"}')
    sys.exit(1 if FAILS else 0)
