"""Append one item to Patrik's evening block (store/patrik-este-blokk.json).

Why (retro 2026-11-13, Kernel c; card 7702bb13): on 11-12 08:01 an agent signed Patrik's Higgsfield login out
(`claude mcp logout higgsfield`), nobody told him, and on 11-13 he had to log in again without knowing why (TG 18290,
hibanapló 11-13 15:16). A revocation that may touch Patrik now lands in the evening block on its own, and the
18:05 evening message (napi-eredmeny-este skill) puts it in front of him.

The file is a JSON list Klodel takes at 18:05 with drain() (scripts/este-blokk-drain.py), under the same lock the
writers hold, so an item written while the evening message is being made is never overwritten by a later [] and a
sent item never comes back (Viktor 41840 LOW 2; before, the skill read the file and wrote [] minutes later, unlocked).
drain() also returns the parked items of <file>.hiba.jsonl, marked, so they reach Patrik too (LOW 3). Items carry
`"auto": true`, a minute (`ido`, local time), `tipus`, `mi`, `forras` and `agens`, optionally `javaslat`.
- One writer at a time: an exclusive flock on a sidecar lock file, the list rewritten through a temp file and
  os.replace, so a reader never sees half a file and two hooks never drop each other's item. The lock has no timeout
  (a stuck writer holds a hook until its 10 s limit; the hook never blocks the tool call), and the .lock file stays.
- Never destroys what is there: a file that is not a JSON list (a hand edit gone wrong) is left untouched and the
  item goes to <file>.hiba.jsonl instead ('parked').
- The same item (tipus, mi, agens) on the same day is written once ('duplicate').
- Text is cleaned: control characters dropped, whitespace collapsed, length capped. Callers pass only what they
  matched, never a raw command (it may carry a secret).
ESTE_BLOKK_PATH overrides the path (tests).
"""
import datetime
import fcntl
import json
import os
import re
import tempfile

_CTRL = re.compile(r'[\x00-\x1f\x7f]')
_WS = re.compile(r'\s+')


def blokk_path():
    p = os.environ.get('ESTE_BLOKK_PATH')
    if p:
        return p
    install = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(install, 'store', 'patrik-este-blokk.json')


def clean(text, limit=300):
    t = _WS.sub(' ', _CTRL.sub(' ', str(text or ''))).strip()
    return t if len(t) <= limit else t[:limit - 1] + '…'


def _atomic_write(path, data, mode_of=None):
    """Write data as JSON to path through a temp file and os.replace; the mode of mode_of (else path) is kept."""
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=folder, prefix='.patrik-este-blokk.')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.write('\n')
        try:
            os.chmod(tmp, os.stat(mode_of or path).st_mode & 0o777)
        except FileNotFoundError:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def add_item(tipus, mi, forras, agens=None, javaslat=None, path=None, now=None):
    """Append one item; returns 'added', 'duplicate' or 'parked'."""
    path = path or blokk_path()
    now = now or datetime.datetime.now()
    item = {'ido': now.strftime('%Y-%m-%d %H:%M'), 'tipus': clean(tipus, 40), 'mi': clean(mi),
            'forras': clean(forras, 120), 'agens': clean(agens or 'ismeretlen', 40), 'auto': True}
    if javaslat:
        item['javaslat'] = clean(javaslat)
    with open(path + '.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(path, encoding='utf-8') as f:
                raw = f.read()
        except FileNotFoundError:
            raw = ''
        try:
            data = json.loads(raw) if raw.strip() else []
        except ValueError:
            data = None
        if not isinstance(data, list):
            with open(path + '.hiba.jsonl', 'a', encoding='utf-8') as f:
                f.write(json.dumps(item, ensure_ascii=False) + '\n')
            return 'parked'
        day = item['ido'][:10]
        for old in data:
            if (isinstance(old, dict) and old.get('tipus') == item['tipus'] and old.get('mi') == item['mi']
                    and old.get('agens') == item['agens'] and str(old.get('ido', ''))[:10] == day):
                return 'duplicate'
        data.append(item)
        _atomic_write(path, data)
    return 'added'


def drain(path=None):
    """Take every item out, under the writers' lock: the file is emptied to [] atomically, the parked items of
    <file>.hiba.jsonl are returned too (each marked 'parkolt': True) and that file is removed. A copy of what was
    taken goes to <file>.utolso-drain.json first (the one before it kept as .utolso-drain.prev.json, and the
    unreadable .hiba.jsonl lines, cut to 200 characters, in the copy only), so a run that dies after the drain
    loses nothing (Viktor 41865 E).
    A block that is not a JSON list is left untouched ('hibas_fajl': True): a person has to look at it.
    Returns {'tetelek': [...], 'parkolt': [...], 'hibas_fajl': bool, 'olvashatatlan_sor': int}."""
    path = path or blokk_path()
    out = {'tetelek': [], 'parkolt': [], 'hibas_fajl': False, 'olvashatatlan_sor': 0}
    with open(path + '.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        exists = os.path.exists(path)
        if exists:
            with open(path, encoding='utf-8') as f:
                raw = f.read()
            try:
                data = json.loads(raw) if raw.strip() else []
            except ValueError:
                data = None
            if isinstance(data, list):
                out['tetelek'] = data
            else:
                out['hibas_fajl'] = True
        hiba = path + '.hiba.jsonl'
        has_hiba = os.path.exists(hiba)
        bad_lines = []
        if has_hiba:
            with open(hiba, encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except ValueError:
                        out['olvashatatlan_sor'] += 1
                        bad_lines.append(line.rstrip('\n')[:200])
                        continue
                    if isinstance(item, dict):
                        out['parkolt'].append({**item, 'parkolt': True})
                    else:
                        out['olvashatatlan_sor'] += 1
                        bad_lines.append(line.rstrip('\n')[:200])
        if out['tetelek'] or out['parkolt'] or out['olvashatatlan_sor']:
            copy = path + '.utolso-drain.json'
            if os.path.exists(copy):
                os.replace(copy, path + '.utolso-drain.prev.json')
            _atomic_write(copy, {**out, 'olvashatatlan_sorok': bad_lines} if bad_lines else out,
                          mode_of=path if exists else None)
        if exists and not out['hibas_fajl'] and out['tetelek']:
            _atomic_write(path, [])
        if has_hiba:
            os.unlink(hiba)
    return out
