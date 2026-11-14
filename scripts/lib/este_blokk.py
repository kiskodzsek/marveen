"""Append one item to Patrik's evening block (store/patrik-este-blokk.json).

Why (retro 2026-11-13, Kernel c; card 7702bb13): on 11-12 08:01 an agent signed Patrik's Higgsfield login out
(`claude mcp logout higgsfield`), nobody told him, and on 11-13 he had to log in again without knowing why (TG 18290,
hibanapló 11-13 15:16). A revocation that may touch Patrik now lands in the evening block on its own, and the
18:05 evening message (napi-eredmeny-este skill) puts it in front of him.

The file is a JSON list Klodel reads at 18:05 and empties to [] after sending. Items written here carry
`"auto": true`, a minute (`ido`, local time), `tipus`, `mi`, `forras` and `agens`, optionally `javaslat`.
- One writer at a time: an exclusive flock on a sidecar lock file, the list rewritten through a temp file and
  os.replace, so a reader never sees half a file and two hooks never drop each other's item.
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


def add_item(tipus, mi, forras, agens=None, javaslat=None, path=None, now=None):
    """Append one item; returns 'added', 'duplicate' or 'parked'."""
    path = path or blokk_path()
    now = now or datetime.datetime.now()
    item = {'ido': now.strftime('%Y-%m-%d %H:%M'), 'tipus': clean(tipus, 40), 'mi': clean(mi),
            'forras': clean(forras, 120), 'agens': clean(agens or 'ismeretlen', 40), 'auto': True}
    if javaslat:
        item['javaslat'] = clean(javaslat)
    folder = os.path.dirname(os.path.abspath(path))
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
        fd, tmp = tempfile.mkstemp(dir=folder, prefix='.patrik-este-blokk.')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
                f.write('\n')
            try:
                os.chmod(tmp, os.stat(path).st_mode & 0o777)
            except FileNotFoundError:
                os.chmod(tmp, 0o644)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    return 'added'
