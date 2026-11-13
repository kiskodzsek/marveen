#!/usr/bin/env python3
"""Tests for scripts/marveen-update-safe.py (Klodel 39777, card 840231cf).

Hermetic: a throw-away bare "origin", a "dev" clone that pushes the upstream change and a "prod" clone that gets
updated; a fake update.sh (outside the repos) does what the real one does to git: AUTO_STASH stash -u when a tracked
file is dirty, `git pull --ff-only`, stash pop. No network, no real store/.
Run: python3 -I scripts/__tests__/marveen-update-safe.test.py
"""
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), 'marveen-update-safe.py')
spec = importlib.util.spec_from_file_location('mus', SCRIPT)
mus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mus)

ENV = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t',
           GIT_COMMITTER_EMAIL='t@t', GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
FAKE_UPDATE = r'''#!/bin/bash
STASHED=0
if [ -n "$(git status --porcelain --untracked-files=no)" ] && [ "${AUTO_STASH:-0}" = 1 ]; then
  git stash push -q -u -m "marveen-update-auto-stash" || exit 3; STASHED=1
fi
if ! git pull -q --ff-only origin main; then
  [ $STASHED = 1 ] && git stash pop -q
  exit 1
fi
if [ $STASHED = 1 ]; then git stash pop -q || echo "pop conflict"; fi
exit 0
'''
SETTINGS = {'permissions': {'allow': []},
            'hooks': {'PreToolUse': [
                {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': 'python3 a.py'}]},
                {'matcher': 'reply', 'hooks': [{'type': 'command', 'command': 'python3 copy.py', 'timeout': 15}]},
                {'matcher': 'reply', 'hooks': [{'type': 'command', 'command': 'python3 other.py'}]}]}}
LINK = {'type': 'command', 'command': 'python3 link.py', 'timeout': 10}


def sh(cwd, *args):
    p = subprocess.run(args, cwd=cwd, env=ENV, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def g(cwd, *args):
    return sh(cwd, 'git', '-c', 'core.hooksPath=/dev/null', *args)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)


def read(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return fh.read()
    except OSError:
        return None


def setup(tmp):
    """origin, dev, prod with one commit (a tracked file, the settings); returns dict of paths."""
    o, dev, prod = (os.path.join(tmp, n) for n in ('origin.git', 'dev', 'prod'))
    g(tmp, 'init', '-q', '--bare', '-b', 'main', o)
    g(tmp, 'clone', '-q', o, dev)
    write(os.path.join(dev, 'app.py'), 'v1\n')
    write(os.path.join(dev, 'keep.py'), 'k1\n')
    write(os.path.join(dev, '.claude', 'settings.json'), json.dumps(SETTINGS) + '\n')
    write(os.path.join(dev, '.gitignore'), 'store/\n')
    g(dev, 'add', '-A')
    g(dev, 'commit', '-q', '-m', 'init')
    g(dev, 'push', '-q', 'origin', 'main')
    g(tmp, 'clone', '-q', o, prod)
    fake = os.path.join(tmp, 'fake-update.sh')
    write(fake, FAKE_UPDATE)
    return {'dev': dev, 'prod': prod, 'fake': fake, 'tmp': tmp}


def push_upstream(r, files, settings=None):
    for rel, text in files.items():
        write(os.path.join(r['dev'], rel), text)
    if settings is not None:
        write(os.path.join(r['dev'], '.claude', 'settings.json'), json.dumps(settings) + '\n')
    g(r['dev'], 'add', '-A')
    g(r['dev'], 'commit', '-q', '-m', 'upstream')
    g(r['dev'], 'push', '-q', 'origin', 'main')


def run(r, *args, cmd=None):
    full = [sys.executable, '-I', SCRIPT, '--root', r['prod'], '--update-cmd', cmd or f'bash {r["fake"]}', *args]
    p = subprocess.run(full, env=ENV, capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + p.stderr


def local_settings():
    s = json.loads(json.dumps(SETTINGS))
    s['effortLevel'] = 'high'
    s['hooks']['PreToolUse'][1]['hooks'].append(LINK)
    return s


def head(r, ref='HEAD'):
    return g(r['prod'], 'rev-parse', ref)[1].strip()


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def baseline_update_fails_on_identical_untracked_file(r):
    # The defect: the same file, identical, not tracked here -> the pull refuses (no wrapper).
    push_upstream(r, {'hooks/gate.py': 'G\n'})
    write(os.path.join(r['prod'], 'hooks', 'gate.py'), 'G\n')
    rc, _ = sh(r['prod'], 'bash', r['fake'])
    return rc != 0 and head(r) != g(r['dev'], 'rev-parse', 'HEAD')[1].strip()


@case
def check_mode_writes_nothing(r):
    push_upstream(r, {'hooks/gate.py': 'G\n'})
    write(os.path.join(r['prod'], 'hooks', 'gate.py'), 'G\n')
    write(os.path.join(r['prod'], '.claude', 'settings.json'), json.dumps(local_settings()) + '\n')
    before = g(r['prod'], 'status', '--porcelain')[1]
    rc, out = run(r)
    return (rc == 0 and 'PARK     hooks/gate.py' in out and 'SETTINGS' in out and 'CHECK OK' in out
            and g(r['prod'], 'status', '--porcelain')[1] == before
            and not os.path.exists(os.path.join(r['prod'], 'store')))


@case
def apply_parks_identical_untracked_keeps_local_and_merges_settings(r):
    up = json.loads(json.dumps(SETTINGS))
    up['hooks']['PreToolUse'].append({'matcher': 'Write', 'hooks': [{'type': 'command', 'command': 'python3 w.py'}]})
    push_upstream(r, {'hooks/gate.py': 'G\n', 'app.py': 'v2\n'}, settings=up)
    write(os.path.join(r['prod'], 'hooks', 'gate.py'), 'G\n')               # carried over by hand, untracked
    write(os.path.join(r['prod'], 'notes', 'local.txt'), 'mine\n')          # local only
    write(os.path.join(r['prod'], 'keep.py'), 'k1 local\n')                 # local edit, not incoming
    write(os.path.join(r['prod'], '.claude', 'settings.json'), json.dumps(local_settings()) + '\n')
    rc, out = run(r, '--apply')
    s = json.loads(read(os.path.join(r['prod'], '.claude', 'settings.json')))
    reply = [h['command'] for e in s['hooks']['PreToolUse'] if e['matcher'] == 'reply' for h in e['hooks']]
    return (rc == 0 and head(r) == head(r, 'origin/main')
            and read(os.path.join(r['prod'], 'hooks', 'gate.py')) == 'G\n'
            and read(os.path.join(r['prod'], 'notes', 'local.txt')) == 'mine\n'
            and read(os.path.join(r['prod'], 'keep.py')) == 'k1 local\n'
            and read(os.path.join(r['prod'], 'app.py')) == 'v2\n'
            and s.get('effortLevel') == 'high' and reply.count('python3 link.py') == 1
            and any(e['matcher'] == 'Write' for e in s['hooks']['PreToolUse'])
            and g(r['prod'], 'stash', 'list')[1].strip() == ''
            and 'gate.py' not in g(r['prod'], 'status', '--porcelain')[1])


@case
def settings_already_upstream_is_not_duplicated(r):
    # #219 case: upstream brings the same hook wiring the prod tree had locally; only effortLevel stays local.
    up = json.loads(json.dumps(SETTINGS))
    up['hooks']['PreToolUse'][1]['hooks'].append(LINK)
    push_upstream(r, {}, settings=up)
    write(os.path.join(r['prod'], '.claude', 'settings.json'), json.dumps(local_settings()) + '\n')
    rc, out = run(r, '--apply')
    s = json.loads(read(os.path.join(r['prod'], '.claude', 'settings.json')))
    links = [h for e in s['hooks']['PreToolUse'] for h in e['hooks'] if h['command'] == 'python3 link.py']
    return rc == 0 and len(links) == 1 and s.get('effortLevel') == 'high'


@case
def reset_carried_over_tracked_file(r):
    push_upstream(r, {'app.py': 'v2\n'})
    write(os.path.join(r['prod'], 'app.py'), 'v2\n')  # git checkout origin/main -- app.py, by hand
    g(r['prod'], 'add', 'app.py')
    rc, out = run(r, '--apply')
    return (rc == 0 and 'RESET    app.py' in out and head(r) == head(r, 'origin/main')
            and g(r['prod'], 'status', '--porcelain')[1].strip() == '')


@case
def stop_on_untracked_file_that_differs(r):
    push_upstream(r, {'hooks/gate.py': 'G\n'})
    write(os.path.join(r['prod'], 'hooks', 'gate.py'), 'G local\n')
    marker = os.path.join(r['tmp'], 'ran')
    rc, out = run(r, '--apply', cmd=f'touch {marker}')
    return (rc == 1 and 'STOP     hooks/gate.py' in out and not os.path.exists(marker)
            and read(os.path.join(r['prod'], 'hooks', 'gate.py')) == 'G local\n')


@case
def stop_on_local_edit_of_incoming_file(r):
    push_upstream(r, {'app.py': 'v2\n'})
    write(os.path.join(r['prod'], 'app.py'), 'v1 local\n')
    rc, out = run(r)
    return rc == 1 and 'STOP     app.py' in out


@case
def stop_on_settings_conflict(r):
    up = json.loads(json.dumps(SETTINGS))
    up['effortLevel'] = 'low'
    push_upstream(r, {}, settings=up)
    write(os.path.join(r['prod'], '.claude', 'settings.json'), json.dumps(local_settings()) + '\n')
    rc, out = run(r)
    return rc == 1 and 'effortLevel' in out and 'STOP' in out


@case
def failed_update_puts_everything_back(r):
    push_upstream(r, {'hooks/gate.py': 'G\n'})
    write(os.path.join(r['prod'], 'hooks', 'gate.py'), 'G\n')
    local = json.dumps(local_settings()) + '\n'
    write(os.path.join(r['prod'], '.claude', 'settings.json'), local)
    old = head(r)
    rc, out = run(r, '--apply', cmd='false')
    return (rc == 1 and head(r) == old and read(os.path.join(r['prod'], 'hooks', 'gate.py')) == 'G\n'
            and read(os.path.join(r['prod'], '.claude', 'settings.json')) == local and 'put back' in out)


@case
def grown_stash_list_is_a_failure(r):
    push_upstream(r, {'app.py': 'v2\n'})
    write(os.path.join(r['prod'], 'keep.py'), 'k1 local\n')
    leave = os.path.join(r['tmp'], 'leave-stash.sh')
    write(leave, 'git stash push -q -m stranded\ngit pull -q --ff-only origin main\n')
    rc, out = run(r, '--apply', cmd=f'bash {leave}')
    return rc == 1 and 'stash list grew' in out


@case
def classification_does_not_hash_local_only_files(r):
    # Pulzus 39788: the first live run spent about 40 s hashing 2 384 local-only files one git call each.
    push_upstream(r, {'hooks/gate.py': 'G\n'})
    write(os.path.join(r['prod'], 'hooks', 'gate.py'), 'G\n')
    for i in range(200):
        write(os.path.join(r['prod'], 'bak', f'f{i}.txt'), f'{i}\n')
    g(r['prod'], 'fetch', '-q', 'origin', 'main')
    calls, real = [], mus.git
    mus.git = lambda root, *a, **k: (calls.append(a), real(root, *a, **k))[1]
    real_hash = mus.hash_files
    hashed = []
    mus.hash_files = lambda root, paths: (hashed.extend(paths), real_hash(root, paths))[1]
    try:
        actions, stops, _ = mus.plan(r['prod'], 'origin/main')
    finally:
        mus.git, mus.hash_files = real, real_hash
    return (not stops and len(calls) < 10 and hashed == ['hooks/gate.py']
            and sum(1 for a in actions if a[0] == 'KEEP') == 200 and ('PARK', 'hooks/gate.py') in [a[:2] for a in actions])


@case
def stop_signal_during_update_waits_and_finishes(r):
    # Pulzus 39788: a SIGTERM mid-run left update.sh orphaned and skipped the settings merge and the verification.
    push_upstream(r, {'hooks/gate.py': 'G\n'})
    write(os.path.join(r['prod'], 'hooks', 'gate.py'), 'G\n')
    write(os.path.join(r['prod'], '.claude', 'settings.json'), json.dumps(local_settings()) + '\n')
    slow = os.path.join(r['tmp'], 'slow-update.sh')
    write(slow, 'sleep 2\n' + FAKE_UPDATE.split('\n', 1)[1])
    p = subprocess.Popen([sys.executable, '-I', SCRIPT, '--root', r['prod'], '--update-cmd', f'bash {slow}', '--apply'],
                         env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = []
    for line in p.stdout:
        out.append(line)
        if line.startswith('UPDATE'):
            p.send_signal(signal.SIGTERM)
            break
    out += p.stdout.readlines()
    rc = p.wait(timeout=60)
    text = ''.join(out)
    s = json.loads(read(os.path.join(r['prod'], '.claude', 'settings.json')))
    return (rc == 128 + signal.SIGTERM and 'nem szakítható' in text and 'OK       hooks/gate.py' in text
            and head(r) == g(r['dev'], 'rev-parse', 'HEAD')[1].strip() and s.get('effortLevel') == 'high')


@case
def merge3_units(r):
    c = []
    ok1 = mus.merge3({'a': 1}, {'a': 1, 'b': 2}, {'a': 1, 'c': 3}, '', c) == {'a': 1, 'c': 3, 'b': 2} and not c
    c2 = []
    mus.merge3({'a': 1}, {'a': 2}, {'a': 3}, '', c2)
    c3 = []
    mus.merge3({'a': {'x': 1}}, {}, {'a': {'x': 2}}, '', c3)  # deleted locally, changed upstream
    c4 = []
    ok4 = mus.merge3([1, 2], [1], [1, 2, 3], '', c4) == [1, 3] and not c4
    return ok1 and c2 == ['/a'] and c3 == ['/a'] and ok4


def main():
    failed = 0
    for fn in CASES:
        with tempfile.TemporaryDirectory() as d:
            try:
                ok = fn(setup(d))
            except Exception as e:  # a crash is a failure, with its reason
                ok = False
                print(f'ERROR {fn.__name__}: {e!r}')
        print(('PASS ' if ok else 'FAIL ') + fn.__name__)
        failed += not ok
    print(f'{len(CASES) - failed}/{len(CASES)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
