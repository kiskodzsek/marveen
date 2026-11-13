"""Reply marks: the gate markers (PRIVÁT-OK, KÉSZ-EREDMÉNY, BALÁZS-KÉRÉS, BELSŐ-ÚT-MÉRVE) kept OUT of the text the
owner reads (Klodel 40845: "ne Patriknak látszó szövegben legyen"; Viktor 40894 conditions).

An agent writes a mark with scripts/reply-mark.py right before it sends; a gate takes it when the message passes.
- One mark = one message: the gate spends it when the whole hook passes (spend_pending at exit 0). A second message
  needs a new mark; if a later gate blocks, mark again.
- Bound to the kind, the chat (as a number when it is one), and the agent that wrote it; 3 minutes to live.
- Spending is atomic (flock on the ledger): two hooks running at once cannot both pass on one mark.
- The ledger is store/reply-marks.jsonl of the install (REPLY_MARKS_PATH in tests): a regular file of our own uid,
  mode 0600; only its last 64 KB is read; a broken or oversized line is no mark. The agent writes it as itself:
  a mark is the agent's own statement, exactly as the text marker was; it is not proof of anything else
  (BALÁZS-KÉRÉS carries the message id only, the proof stays inbound-senders.jsonl).
- Never an exception to PARANCS-KAPU (Viktor 40894 (6)).
"""
import fcntl
import json
import os
import secrets
import stat
import time

KINDS = ('PRIVAT-OK', 'KESZ-EREDMENY', 'BALAZS-KERES', 'BELSO-UT-MERVE')
TTL_S = 180
TAIL_BYTES = 64 * 1024
MAX_LINE = 1024
MIN_VALUE, MAX_VALUE = 3, 300

_pending = []  # (path, nonce) taken by this hook run, spent at exit 0


def ledger_path():
    p = os.environ.get('REPLY_MARKS_PATH')
    if p:
        return p
    install = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(install, 'store', 'reply-marks.jsonl')


def norm_chat(v):
    t = str(v or '').strip()
    try:
        return str(int(t))
    except ValueError:
        return t


def _open(path, create):
    flags = os.O_RDWR | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0)
    if create:
        flags |= os.O_CREAT
    fd = os.open(path, flags, 0o600)
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or (st.st_mode & 0o077):
        os.close(fd)
        raise OSError('reply-marks ledger is not a private regular file')
    return fd


def _rows(fd):
    size = os.fstat(fd).st_size
    start = max(0, size - TAIL_BYTES)
    os.lseek(fd, start, os.SEEK_SET)
    data = os.read(fd, size - start)
    lines = data.split(b'\n')
    if start > 0:
        lines = lines[1:]  # the first line may be cut
    out = []
    for raw in lines:
        if not raw or len(raw) > MAX_LINE:
            continue
        try:
            r = json.loads(raw.decode('utf-8'))
        except ValueError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def add(kind, chat, agent, value, now=None):
    """Write a mark. Returns its nonce. Raises ValueError on a bad kind, chat, agent or value."""
    if kind not in KINDS:
        raise ValueError('unknown kind')
    chat = norm_chat(chat)
    value = ' '.join(str(value or '').split())
    if not chat or not agent or not (MIN_VALUE <= len(value) <= MAX_VALUE):
        raise ValueError('chat, agent and a 3-300 character value are required')
    row = {'ts': int(now if now is not None else time.time()), 'nonce': secrets.token_hex(8), 'kind': kind,
           'chat': chat, 'agent': str(agent), 'value': value}
    line = (json.dumps(row, ensure_ascii=False) + '\n').encode('utf-8')
    if len(line) > MAX_LINE:
        raise ValueError('mark too long')
    path = ledger_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = _open(path, True)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, line)
    finally:
        os.close(fd)
    return row['nonce']


def take(kind, chat, agent, now=None):
    """The newest unspent, unexpired mark of this kind for this chat by this agent: its value, else None. The mark is
    reserved for this hook run and spent by spend_pending() when the hook passes. Any error = no mark."""
    path = ledger_path()
    now = now if now is not None else time.time()
    try:
        fd = _open(path, False)
    except OSError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        rows = _rows(fd)
    except OSError:
        return None
    finally:
        os.close(fd)
    used = {r.get('used') for r in rows if 'used' in r}
    chat = norm_chat(chat)
    for r in reversed(rows):
        if (r.get('kind') == kind and r.get('chat') == chat and r.get('agent') == str(agent)
                and isinstance(r.get('ts'), int) and 0 <= now - r['ts'] <= TTL_S
                and isinstance(r.get('nonce'), str) and r['nonce'] not in used
                and isinstance(r.get('value'), str)):
            _pending.append((path, r['nonce']))
            return r['value']
    return None


def spend_pending():
    """Spend every mark this hook run took, atomically. False when one was spent by someone else in the meantime
    (two hooks at once on one mark): the caller must then block."""
    ok = True
    for path, nonce in _pending:
        try:
            fd = _open(path, False)
        except OSError:
            ok = False
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            if any(r.get('used') == nonce for r in _rows(fd)):
                ok = False
                continue
            os.write(fd, (json.dumps({'used': nonce, 'ts': int(time.time())}) + '\n').encode('utf-8'))
        finally:
            os.close(fd)
    _pending.clear()
    return ok
