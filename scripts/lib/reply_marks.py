"""Reply marks: the gate markers (PRIVÁT-OK, KÉSZ-EREDMÉNY, BALÁZS-KÉRÉS, BELSŐ-ÚT-MÉRVE) kept OUT of the text the
owner reads (Klodel 40845: "ne Patriknak látszó szövegben legyen"; Viktor 40894 conditions).

An agent writes a mark with scripts/reply-mark.py right before it sends; a gate takes it when the message passes.
- One mark = one message, spent only when the message is SENT (Klodel 41147): a gate that passes on a mark HOLDS it
  for its tool call (spend_pending at exit 0 writes a "hold" row with the call's tool_use_id), and the PostToolUse
  hook reply-marks-spend.py spends what that call held. PostToolUse runs only when the tool ran, so when another
  PreToolUse gate blocks the same reply (2026-11-13 18:30, claim-source-reply-gate), the mark is NOT spent and the
  corrected reply passes on it. Without a tool_use_id in the payload the gate spends at once, as before.
- A hold by ANOTHER call keeps the mark from a second reply until it is spent: it is void only when the session
  transcript has an is_error tool_result for that call (a blocked or failed call sent nothing; 2026-11-13 mérve: a
  PreToolUse-blocked call gets an is_error tool_result) or when it is older than HOLD_MAX_S. A successful call's
  tool_result does NOT free it (Viktor 41241 LOW 1: the harness may write it before PostToolUse spends). An
  unreadable transcript leaves it live (the reply blocks with "jelölj újra"; a new mark is a new nonce).
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
import re
import secrets
import stat
import time

KINDS = ('PRIVAT-OK', 'KESZ-EREDMENY', 'BALAZS-KERES', 'BELSO-UT-MERVE')
TTL_S = 180
TAIL_BYTES = 64 * 1024
MAX_LINE = 1024
MIN_VALUE, MAX_VALUE = 3, 300

HOLD_MAX_S = 600
TRANSCRIPT_TAIL_BYTES = 16 * 1024 * 1024
_CALL_ID = re.compile(r'[A-Za-z0-9_-]{1,128}')

_pending = []  # (path, nonce) taken by this hook run, held (or spent) at exit 0
_call = {'id': None, 'transcript': None, 'done': None}  # this hook run's tool call (bind_call)


def bind_call(payload):
    """Hold mode for this hook run: the tool call's tool_use_id (and transcript) from the hook payload. Without a
    well-formed tool_use_id the run stays in the old mode (spend at exit 0)."""
    _call.update(id=None, transcript=None, done=None)
    if not isinstance(payload, dict):
        return
    tid = payload.get('tool_use_id')
    if isinstance(tid, str) and _CALL_ID.fullmatch(tid):
        _call['id'] = tid
        tp = payload.get('transcript_path')
        _call['transcript'] = tp if isinstance(tp, str) and tp else None


def _call_failed(tid):
    """True when the session transcript already holds an is_error tool_result for call `tid`: a PreToolUse gate blocked
    it or the tool failed, so it sent nothing. A successful call's hold stays live until reply-marks-spend.py spends it
    (or HOLD_MAX_S), whatever order the harness writes the tool_result and runs PostToolUse in (Viktor 41241 LOW 1);
    and a spend hook that did not run leaves the mark spent-like, not free (LOW 2). Unreadable transcript, a FIFO or
    any non-regular file = False (the hold stays live)."""
    if _call['done'] is None:
        data = b''
        tp = _call['transcript']
        if tp:
            try:
                fd = os.open(tp, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
                try:
                    st = os.fstat(fd)
                    if stat.S_ISREG(st.st_mode):
                        os.lseek(fd, max(0, st.st_size - TRANSCRIPT_TAIL_BYTES), os.SEEK_SET)
                        chunks, left = [], TRANSCRIPT_TAIL_BYTES  # bounded even if the file grows meanwhile
                        while left > 0:
                            b = os.read(fd, min(1 << 20, left))
                            if not b:
                                break
                            chunks.append(b)
                            left -= len(b)
                        data = b''.join(chunks)
                finally:
                    os.close(fd)
            except OSError:
                data = b''
        _call['done'] = data
    needle = b'"tool_use_id":"' + tid.encode('ascii') + b'"'
    for line in _call['done'].split(b'\n'):
        if needle not in line:
            continue
        try:
            ev = json.loads(line.decode('utf-8'))
        except ValueError:
            continue
        msg = ev.get('message') if isinstance(ev, dict) else None
        content = msg.get('content') if isinstance(msg, dict) else None
        for b in content if isinstance(content, list) else ():
            if (isinstance(b, dict) and b.get('type') == 'tool_result' and b.get('tool_use_id') == tid
                    and b.get('is_error') is True):
                return True
    return False


def _taken(rows, now):
    """Nonces no hook run may take now: spent ones, and ones held by another, possibly still running call."""
    out = {r.get('used') for r in rows if 'used' in r}
    for r in rows:
        h, c, ts = r.get('hold'), r.get('call'), r.get('ts')
        if not isinstance(h, str) or not isinstance(c, str) or c == _call['id']:
            continue
        if isinstance(ts, int) and 0 <= now - ts <= HOLD_MAX_S and _CALL_ID.fullmatch(c) and not _call_failed(c):
            out.add(h)
    return out


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
    used = _taken(rows, now)
    chat = norm_chat(chat)
    for r in reversed(rows):
        if (r.get('kind') == kind and r.get('chat') == chat and r.get('agent') == str(agent)
                and isinstance(r.get('ts'), int) and 0 <= now - r['ts'] <= TTL_S
                and isinstance(r.get('nonce'), str) and r['nonce'] not in used
                and isinstance(r.get('value'), str)):
            # Once per run: a second take of the same mark must not make spend_pending see it as spent by
            # someone else (Viktor 40933 INFO 5).
            if (path, r['nonce']) not in _pending:
                _pending.append((path, r['nonce']))
            return r['value']
    return None


def reserve_once(token):
    """A one-time permission that is not an agent's mark (e.g. the owner's own message, Viktor 40974 LOW): True when
    `token` was never spent; it is then reserved for this hook run and spent by spend_pending() when the hook passes,
    so it lets exactly one message through. The ledger is created (0600) if it does not exist yet. Any error = False.
    Only the last 64 KB is read: a token spent longer ago than that is not seen (the callers' own freshness windows
    are far shorter than the time 64 KB of marks takes)."""
    path = ledger_path()
    try:
        fd = _open(path, True)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        if token in _taken(_rows(fd), time.time()):
            return False
    except OSError:
        return False
    finally:
        os.close(fd)
    if (path, token) not in _pending:
        _pending.append((path, token))
    return True


def spend_pending():
    """Call at the hook's exit 0. Bound to a tool call (bind_call): HOLD every mark this run took for that call, and
    the PostToolUse hook spends it once the message went out. Unbound: spend at once. Atomic either way: False when
    a mark was spent, or is held by another call that may still be running, in the meantime (two hooks at once on one
    mark); the caller must then block."""
    ok = True
    now = time.time()
    for path, nonce in _pending:
        try:
            fd = _open(path, False)
        except OSError:
            ok = False
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            if nonce in _taken(_rows(fd), now):
                ok = False
                continue
            row = {'used': nonce} if _call['id'] is None else {'hold': nonce, 'call': _call['id']}
            row['ts'] = int(now)
            os.write(fd, (json.dumps(row) + '\n').encode('utf-8'))
        finally:
            os.close(fd)
    _pending.clear()
    return ok


def spend_held(call_id):
    """PostToolUse: spend every mark the tool call `call_id` held (it went out). Returns how many were spent.
    Any error = 0; never raises."""
    if not isinstance(call_id, str) or not _CALL_ID.fullmatch(call_id):
        return 0
    try:
        fd = _open(ledger_path(), False)
    except OSError:
        return 0
    n = 0
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        rows = _rows(fd)
        used = {r.get('used') for r in rows if 'used' in r}
        for r in rows:
            h = r.get('hold')
            if r.get('call') == call_id and isinstance(h, str) and h not in used:
                os.write(fd, (json.dumps({'used': h, 'ts': int(time.time())}) + '\n').encode('utf-8'))
                used.add(h)
                n += 1
    except OSError:
        return n
    finally:
        os.close(fd)
    return n
