#!/usr/bin/env python3
"""marveen-update-safe.py -- run update.sh on the production tree without losing local files or local settings.

Usage (from anywhere):
  python3 -I scripts/marveen-update-safe.py            # CHECK only: fetch, classify, print the plan; writes nothing
  python3 -I scripts/marveen-update-safe.py --apply    # check, then park / reset, run update.sh, restore, verify
--list prints every untracked KEEP file (default: one line per folder, with a count).
Test seams: --root DIR (default: the repo this file is in), --update-cmd "CMD ..." (default: bash <root>/update.sh),
--remote / --branch (default origin / the current branch).

Why (Klodel 39777, card 840231cf, 2026-11-13): on 2026-11-12 Pulzus carried merged files onto the production tree by
hand six times before update.sh (#197, #198, #178/#199, #200, #219), and after every update put the local
.claude/settings.json difference ("effortLevel", a hook wiring) back with a one-off script. Measured on a throw-away
repo: a file that is NOT tracked locally but arrives with the update stops `git pull --ff-only` ("untracked working
tree files would be overwritten"), even when its content is identical; and under AUTO_STASH the `git stash pop`
fails on it ("already exists, no checkout"), which leaves EVERY stashed untracked file (e.g. a live hook) in the
stash instead of on disk.

What it does. Every local change (git status, untracked included, ignored excluded) is measured against HEAD and
the fetched upstream (<remote>/<branch>):
  KEEP      local only (not in upstream, or a local edit of a file the update does not change): survives the
            AUTO_STASH stash/pop of update.sh; listed so nothing is silent.
  PARK      untracked / added file identical to the incoming one: moved to the backup before the update, the pull
            brings it back; verified after.
  RESET     tracked file whose local content already equals upstream (carried over by hand): reset to HEAD before
            the update (copy in the backup), the pull brings it back; verified after.
  SETTINGS  .claude/settings.json local difference: three-way JSON merge (old HEAD = base, local, new HEAD); the
            file is reset to HEAD before the update and the merged result is written after (indent 2), only when
            it differs from the new HEAD version.
  STOP      an untracked / added file that DIFFERS from the incoming one, a local edit of a file the update also
            changes, a settings conflict (both sides changed the same value), unreadable JSON, no upstream: the
            check fails and --apply runs nothing.
--apply writes a backup under <root>/store/update-safe/<YYYYmmdd-HHMMSS>/ (files + settings + manifest.json), runs
`AUTO_STASH=1 <update-cmd>`, then verifies. If update.sh fails with HEAD unchanged, the parked / reset files and
the local settings are put back. A grown `git stash list` (an auto-stash pop that failed) is reported as a failure.
Exit: 0 = OK (check: would proceed), 1 = STOP or a failed verification, 2 = usage, 128+N = stopped by signal N.

Stopping it (Pulzus 39788, first live run 2026-11-13: a SIGTERM mid-run killed the wrapper, update.sh ran on
orphaned with the restart, and the settings merge and the verification never ran). The CHECK and the
classification write nothing and stop at once. From the first file move on, SIGTERM / SIGINT / SIGHUP are
deferred: before update.sh starts, everything is put back and it exits 128+N; while update.sh runs (in its own
session, so a terminal Ctrl-C does not cut it in half), it prints that update.sh cannot be interrupted, waits for
it, finishes the settings merge and the verification, then exits 128+N.
The classification hashes only what it compares: a file that exists only locally is never hashed (the first live
run spent about 40 s hashing 2 384 such files).
Tests: python3 -I scripts/__tests__/marveen-update-safe.test.py
"""
import argparse
import datetime
import json
import os
import shutil
import signal
import subprocess
import sys

SETTINGS = '.claude/settings.json'
SKIP = {'HEARTBEAT.md'}  # rewritten every heartbeat tick; update.sh ignores it too
MISSING = object()


def git(root, *args, text=True):
    p = subprocess.run(['git', '-C', root, *args], capture_output=True, text=text)
    return p.returncode, (p.stdout.strip() if text else p.stdout)


def file_blob(root, path):
    full = os.path.join(root, path)
    if not os.path.isfile(full) or os.path.islink(full):
        return None
    rc, out = git(root, 'hash-object', '--', path)
    return out if rc == 0 else None


def tree(root, ref):
    """{path: blob sha} for every file in ref (one git call)."""
    rc, out = git(root, 'ls-tree', '-r', '-z', '--full-tree', ref, text=False)
    if rc != 0:
        return None
    out_map = {}
    for rec in out.decode('utf-8', 'surrogateescape').split('\0'):
        meta, _, path = rec.partition('\t')
        parts = meta.split()
        if len(parts) == 3 and parts[1] == 'blob':
            out_map[path] = parts[2]
    return out_map


def hash_files(root, paths):
    """{path: blob sha} for the regular files among paths (one git call)."""
    files = [p for p in paths if os.path.isfile(os.path.join(root, p)) and not os.path.islink(os.path.join(root, p))]
    if not files:
        return {}
    p = subprocess.run(['git', '-C', root, 'hash-object', '--stdin-paths'], input='\n'.join(files) + '\n',
                       capture_output=True, text=True)
    shas = p.stdout.split()
    return dict(zip(files, shas)) if p.returncode == 0 and len(shas) == len(files) else {}


def show(root, ref, path):
    rc, out = git(root, 'show', f'{ref}:{path}', text=False)
    return out if rc == 0 else None


def changes(root):
    """[(xy, path)] from git status (untracked included, ignored excluded); a rename yields both paths."""
    rc, out = git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=all', text=False)
    if rc != 0:
        return None
    items, parts, i = [], out.decode('utf-8', 'surrogateescape').split('\0'), 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        xy, path = e[:2], e[3:]
        items.append((xy, path))
        if 'R' in xy or 'C' in xy:  # the next field is the source path
            if i < len(parts) and parts[i]:
                items.append((xy, parts[i]))
            i += 1
    return items


# ---- three-way JSON merge ----

def _key(x):
    # A hook command object is unique by its command inside one hooks list; anything else by its whole content
    # (hook entries repeat the same matcher, so a matcher is not an identity).
    if isinstance(x, dict) and isinstance(x.get('command'), str):
        return ('command', x['command'])
    return ('json', json.dumps(x, sort_keys=True, ensure_ascii=False))


def merge3(base, local, theirs, path, conflicts):
    if local == base:
        return theirs
    if theirs == base or theirs == local:
        return local
    if local is MISSING or theirs is MISSING:
        conflicts.append(path or '/')  # deleted on one side, changed on the other
        return theirs
    if isinstance(local, dict) and isinstance(theirs, dict) and (base is MISSING or isinstance(base, dict)):
        b = {} if base is MISSING else base
        out = {}
        for k in list(theirs) + [k for k in local if k not in theirs]:
            v = merge3(b.get(k, MISSING), local.get(k, MISSING), theirs.get(k, MISSING), f'{path}/{k}', conflicts)
            if v is not MISSING:
                out[k] = v
        return out
    if isinstance(local, list) and isinstance(theirs, list) and (base is MISSING or isinstance(base, list)):
        b = [] if base is MISSING else base
        bk, lk, tk = ({_key(x): x for x in lst} for lst in (b, local, theirs))
        if len(bk) != len(b) or len(lk) != len(local) or len(tk) != len(theirs):
            conflicts.append(path + ' (duplicate list items)')
            return theirs
        out = []
        for x in theirs:
            k = _key(x)
            if k in bk and k not in lk:  # removed locally
                if x != bk[k]:
                    conflicts.append(f'{path}[{k[1][:60]}]')
                    out.append(x)
                continue
            out.append(merge3(bk.get(k, MISSING), lk[k], x, f'{path}[{k[1][:60]}]', conflicts) if k in lk else x)
        for x in local:
            k = _key(x)
            if k not in tk:
                if k not in bk:
                    out.append(x)  # added locally
                elif x != bk[k]:
                    conflicts.append(f'{path}[{k[1][:60]}]')  # changed locally, removed upstream
        return out
    conflicts.append(path or '/')
    return theirs


def changed_paths(base, local, path=''):
    """The JSON paths where local differs from base (dicts recursed, a list counts as one value)."""
    if base == local:
        return []
    if isinstance(base, dict) and isinstance(local, dict):
        out = []
        for k in list(base) + [k for k in local if k not in base]:
            out += changed_paths(base.get(k, MISSING), local.get(k, MISSING), f'{path}/{k}')
        return out
    return [path or '/']


def parse_json(raw):
    try:
        return json.loads(raw.decode('utf-8')) if raw is not None else MISSING
    except (UnicodeDecodeError, ValueError):
        return None


# ---- plan ----

def plan(root, up):
    """(actions, stops, notes): actions = [(kind, path, info)], stops = [str], notes = [str]."""
    actions, stops, notes = [], [], []
    items = changes(root)
    if items is None:
        return [], ['git status failed (not a git checkout?)'], notes
    head_tree, up_tree = tree(root, 'HEAD'), tree(root, up)
    if head_tree is None or up_tree is None:
        return [], ['git ls-tree failed for HEAD or upstream'], notes
    todo, seen = [], set()
    for xy, path in items:
        if path not in seen and os.path.basename(path) not in SKIP:
            seen.add(path)
            todo.append((xy, path))
    # Hash only what is compared: a file in neither HEAD nor upstream is local only (KEEP) without hashing.
    wts = hash_files(root, [p for _, p in todo if p in head_tree or p in up_tree])
    for xy, path in todo:
        head, upb, wt = head_tree.get(path), up_tree.get(path), wts.get(path)
        incoming = head != upb
        if path == SETTINGS:
            if wt == head:
                continue
            base, local, theirs = (parse_json(r) for r in (show(root, 'HEAD', path),
                                                          _read(os.path.join(root, path)), show(root, up, path)))
            if None in (base, local, theirs):
                stops.append(f'{path}: unreadable JSON (HEAD, local or upstream)')
                continue
            conflicts = []
            merge3(base, local, theirs, '', conflicts)
            if conflicts:
                stops.append(f'{path}: local and upstream both changed {", ".join(conflicts[:5])}')
            else:
                actions.append(('SETTINGS', path, 'local difference ' + ', '.join(changed_paths(base, local)[:8])
                                + '; merged onto the new HEAD after the update'))
            continue
        untracked = xy == '??' or head is None
        if untracked:
            if upb is None:
                actions.append(('KEEP', path, 'local only, not in upstream'))
            elif wt == upb:
                actions.append(('PARK', path, upb))
            else:
                stops.append(f'{path}: not tracked here, and the update brings a DIFFERENT version')
            continue
        if wt == upb:
            if incoming:
                actions.append(('RESET', path, upb))
            continue
        if not incoming:
            actions.append(('KEEP', path, 'local edit; the update does not change this file'))
        else:
            stops.append(f'{path}: local edit, and the update changes this file too')
    return actions, stops, notes


def _read(full):
    try:
        with open(full, 'rb') as fh:
            return fh.read()
    except OSError:
        return None


def _group(path):
    parts = path.split('/')
    return './' if len(parts) == 1 else '/'.join(parts[:min(2, len(parts) - 1)]) + '/'


def print_plan(actions, stops, head, upstream_sha, full=False):
    print(f'HEAD {head[:8]} -> upstream {upstream_sha[:8]}')
    order = {'STOP': 0, 'SETTINGS': 1, 'PARK': 2, 'RESET': 3, 'KEEP': 4}
    groups = {}
    for kind, path, info in sorted(actions, key=lambda a: (order[a[0]], a[1])):
        if kind == 'KEEP' and not full and info.startswith('local only'):
            groups.setdefault(_group(path), []).append(path)  # untracked, not in upstream: one line per folder
            continue
        detail = info if kind in ('KEEP', 'SETTINGS') else f'equals upstream {info[:8]}'
        print(f'{kind:<8} {path}  ({detail})')
    for grp, paths in sorted(groups.items()):
        print(f'KEEP     {grp}  ({len(paths)} untracked, not in upstream)')
    for s in stops:
        print(f'STOP     {s}')
    counts = {k: sum(1 for a in actions if a[0] == k) for k in order if k != 'STOP'}
    print('SUMMARY ' + ', '.join(f'{k} {v}' for k, v in counts.items()) + f', STOP {len(stops)}')


# ---- apply ----

def _stash_count(root):
    rc, out = git(root, 'stash', 'list')
    return len(out.splitlines()) if rc == 0 and out else 0


def _copy_in(root, backup, path):
    src = os.path.join(root, path)
    dst = os.path.join(backup, 'files', path)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def _put_back(root, backup, path):
    src = os.path.join(backup, 'files', path)
    dst = os.path.join(root, path)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def _write_json(full, value):
    tmp = full + '.update-safe.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(value, fh, indent=2, ensure_ascii=False)
        fh.write('\n')
    os.replace(tmp, full)


class _Signals:
    """Defers SIGTERM / SIGINT / SIGHUP while the tree is being changed (see "Stopping it")."""

    NAMES = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)

    def __init__(self):
        self.got, self.updating, self.old = None, False, {}

    def __enter__(self):
        for s in self.NAMES:
            self.old[s] = signal.signal(s, self._handle)
        return self

    def __exit__(self, *exc):
        for s, h in self.old.items():
            signal.signal(s, h)

    def _handle(self, signum, frame):
        first = self.got is None
        self.got = self.got or signum
        if first:
            what = ('update.sh fut, nem szakítható: megvárom, befejezem az ellenőrzést és a settings-visszafésülést, '
                    'utána leállok' if self.updating else 'leállás: a félretett fájlok és a settings visszakerülnek')
            print(f'SIGNAL   {signal.Signals(signum).name}: {what}', flush=True)


def apply(root, up, actions, update_cmd):
    with _Signals() as sig:
        rc = _apply(root, up, actions, update_cmd, sig)
    return rc


def _put_back_all(root, backup, actions, settings_local):
    for kind, path, info in actions:
        if kind in ('PARK', 'RESET') and os.path.isfile(os.path.join(backup, 'files', path)):
            _put_back(root, backup, path)
    if settings_local is not None:
        with open(os.path.join(root, SETTINGS), 'wb') as fh:
            fh.write(settings_local)


def _apply(root, up, actions, update_cmd, sig):
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = os.path.join(root, 'store', 'update-safe', stamp)
    os.makedirs(backup)
    _, old_head = git(root, 'rev-parse', 'HEAD')
    settings_local = settings_base = None
    for kind, path, info in actions:
        if kind == 'PARK':
            _copy_in(root, backup, path)
            git(root, 'rm', '-q', '--cached', '--ignore-unmatch', '--', path)
            os.remove(os.path.join(root, path))
        elif kind == 'RESET':
            if os.path.isfile(os.path.join(root, path)):
                _copy_in(root, backup, path)
            git(root, 'checkout', 'HEAD', '--', path)
        elif kind == 'SETTINGS':
            settings_local = _read(os.path.join(root, path))
            settings_base = show(root, 'HEAD', path)
            for name, raw in (('settings.local.json', settings_local), ('settings.base.json', settings_base)):
                with open(os.path.join(backup, name), 'wb') as fh:
                    fh.write(raw)
            git(root, 'checkout', 'HEAD', '--', path)
    with open(os.path.join(backup, 'manifest.json'), 'w', encoding='utf-8') as fh:
        json.dump({'old_head': old_head, 'upstream': up, 'actions': actions, 'update_cmd': update_cmd}, fh, indent=2)
    print(f'BACKUP   {backup}', flush=True)
    if sig.got:
        _put_back_all(root, backup, actions, settings_local)
        print('STOPPED  before update.sh: local files and settings put back (backup kept)', flush=True)
        return 128 + sig.got
    stashes = _stash_count(root)
    env = dict(os.environ, AUTO_STASH='1')
    sig.updating = True
    child = subprocess.Popen(update_cmd, cwd=root, env=env, start_new_session=True)
    print(f'UPDATE   {" ".join(update_cmd)} (pid {child.pid}); a stop signal waits for it', flush=True)
    rc = child.wait()
    _, new_head = git(root, 'rev-parse', 'HEAD')
    failed = []
    if rc != 0 and new_head == old_head:
        # Nothing was pulled: put the local state back as it was.
        _put_back_all(root, backup, actions, settings_local)
        print(f'FAIL     update exited {rc}, HEAD unchanged: local files and settings put back (backup kept)')
        return 128 + sig.got if sig.got else 1
    if rc != 0:
        failed.append(f'update exited {rc} after moving HEAD {old_head[:8]} -> {new_head[:8]}')
    for kind, path, info in actions:
        if kind not in ('PARK', 'RESET'):
            continue
        now = file_blob(root, path)
        if now == info:
            print(f'OK       {path} == {info[:8]}')
        elif now is None and os.path.isfile(os.path.join(backup, 'files', path)):
            _put_back(root, backup, path)
            failed.append(f'{path}: missing after the update, put back from the backup')
        else:
            failed.append(f'{path}: {str(now)[:8]} after the update, expected {info[:8]} (backup kept)')
    if settings_local is not None:
        base, local = parse_json(settings_base), parse_json(settings_local)
        theirs = parse_json(_read(os.path.join(root, SETTINGS)))
        conflicts = []
        merged = merge3(base, local, theirs, '', conflicts)
        if None in (base, local, theirs) or conflicts:
            failed.append(f'{SETTINGS}: merge conflict after the update {conflicts[:5]}; local copy in the backup')
        elif merged != theirs:
            _write_json(os.path.join(root, SETTINGS), merged)
            ok = parse_json(_read(os.path.join(root, SETTINGS))) == merged
            print(f'{"OK" if ok else "FAIL":<8} {SETTINGS}: local difference restored')
            if not ok:
                failed.append(f'{SETTINGS}: read-back differs')
        else:
            print(f'OK       {SETTINGS}: the new HEAD already carries the local difference')
    if _stash_count(root) > stashes:
        failed.append('git stash list grew: the auto-stash pop failed; check `git stash list` before anything else')
    for f in failed:
        print(f'FAIL     {f}')
    print('DONE' if not failed else 'DONE WITH FAILURES')
    if sig.got:
        print(f'STOPPED  on {signal.Signals(sig.got).name}, after update.sh and the verification', flush=True)
        return 128 + sig.got
    return 1 if failed else 0


def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--root', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument('--update-cmd', default=None)
    ap.add_argument('--remote', default='origin')
    ap.add_argument('--branch', default=None)
    ap.add_argument('--list', action='store_true', help='print every KEEP file, not one line per folder')
    try:
        a = ap.parse_args(argv[1:])
    except SystemExit:
        return 2
    root = os.path.abspath(a.root)
    branch = a.branch or git(root, 'rev-parse', '--abbrev-ref', 'HEAD')[1]
    if not branch or branch == 'HEAD':
        print('STOP     detached HEAD or not a git checkout')
        return 1
    if git(root, 'fetch', '-q', a.remote, branch)[0] != 0:
        print(f'STOP     git fetch {a.remote} {branch} failed')
        return 1
    up = f'{a.remote}/{branch}'
    rc, upstream_sha = git(root, 'rev-parse', up)
    if rc != 0:
        print(f'STOP     no {up}')
        return 1
    _, head = git(root, 'rev-parse', 'HEAD')
    actions, stops, _ = plan(root, up)
    print_plan(actions, stops, head, upstream_sha, a.list)
    if stops:
        return 1
    if not a.apply:
        print('CHECK OK: run again with --apply to update')
        return 0
    cmd = a.update_cmd.split() if a.update_cmd else ['bash', os.path.join(root, 'update.sh')]
    return apply(root, up, actions, cmd)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
