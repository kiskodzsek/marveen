#!/usr/bin/env python3
"""big-read-gate.py -- PreToolUse(Read) gate: a whole-file Read of a large text file is stopped once, with a hint.

Why (card b073a7e3, Klodel 46838 / 46967; measured 2026-11-18 over 14 days, 3069 transcripts, 2152 of them .gz):
the context guard restarted the fleet 25 times on 11-17, and file viewing is the largest tool-output share of the
growth. Of 2416 Read calls without a `limit`, 306 returned more than 20 KiB, 9878 KiB in all (Dave 105 calls /
3637 KiB, Kernel 44 / 1333, Viktor 41 / 1227); 48 of them (1778 KiB) re-read a saved large tool output
(.../tool-results/*.txt) whole. Source: agents/kernel/work/context-fill-1118/bigread.py, bigread-1118b.txt.

  BLOCK (exit 2, the hint on stderr): tool Read, no `limit` key in the input, the target is a regular file larger
  than LIMIT_BYTES, and it is not an image, PDF or notebook (Claude Code reads those differently).
  ALLOW (exit 0, nothing printed): an explicit `limit` (any value: a deliberate whole read stays possible, e.g.
  limit 2000), a small file, a directory, a media file, any other tool, and every case the gate cannot decide
  (bad JSON, a missing or unreadable path, an internal error, the 3 s watchdog).

This is an EFFICIENCY gate, not a security boundary: it fails OPEN. NOT MODELLED: Bash cat / sed / head / git diff /
git show output, Grep output, a Read whose `limit` is large (it is the agent's explicit choice), an Agent/Explore
subagent's own reads (they do not land in the caller's context, which is the point).

Log: store/big-read-gate/gate.jsonl, one line per BLOCK (lazily created, O_APPEND|O_NOFOLLOW, mode 0600): time,
agent (from the transcript or cwd path), size in bytes, and sha256/16 of the path -- no path, no content.
"""
import hashlib
import json
import os
import re
import signal
import stat
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
LOG_DIR = os.path.join(ROOT, 'store', 'big-read-gate')
LIMIT_BYTES = 20 * 1024
MEDIA = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.heic', '.tif', '.tiff', '.pdf', '.ipynb')
WATCHDOG_S = 3

MESSAGE = (
    'big-read-gate (card b073a7e3): {name} is {kib} KiB; a Read without `limit` loads all of it into your context '
    '(large file views are the biggest share of the context growth that restarts agents).\n'
    'Instead: find the part you need with `grep -n "<pattern>" {path}` and Read it with offset/limit '
    '(e.g. offset: <line>, limit: 120); for a broad survey, let an Explore/general-purpose subagent read it and '
    'bring back only the conclusion. A saved tool output (tool-results/*.txt) is read the same way.\n'
    'If you really need the whole file, Read it again with an explicit limit (e.g. limit: 2000): the gate lets an '
    'explicit limit through.\n'
)


def agent_of(data):
    for key in ('transcript_path', 'cwd'):
        v = data.get(key)
        if isinstance(v, str):
            m = re.search(r'/agents/([A-Za-z0-9_.-]+)/', v + '/')
            if m:
                return m.group(1)
    return '-'


def decide(data):
    """Return (block, size, path). Never raises for a well-formed dict; anything odd is an allow."""
    if not isinstance(data, dict) or data.get('tool_name') != 'Read':
        return False, 0, ''
    inp = data.get('tool_input')
    if not isinstance(inp, dict):
        return False, 0, ''
    if inp.get('limit') is not None:
        return False, 0, ''
    path = inp.get('file_path')
    if not isinstance(path, str) or not path:
        return False, 0, ''
    if not os.path.isabs(path):
        cwd = data.get('cwd')
        if not isinstance(cwd, str) or not os.path.isabs(cwd):
            return False, 0, ''
        path = os.path.join(cwd, path)
    if path.lower().endswith(MEDIA):
        return False, 0, path
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return False, 0, path
    if not stat.S_ISREG(st.st_mode):
        return False, st.st_size, path
    return st.st_size > LIMIT_BYTES, st.st_size, path


def log_block(data, size, path):
    try:
        os.makedirs(LOG_DIR, mode=0o700, exist_ok=True)
        line = json.dumps({
            'ts': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
            'agent': agent_of(data),
            'size': size,
            'path_sha16': hashlib.sha256(path.encode('utf-8', 'replace')).hexdigest()[:16],
        }) + '\n'
        fd = os.open(os.path.join(LOG_DIR, 'gate.jsonl'),
                     os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, line.encode())
        finally:
            os.close(fd)
    except OSError:
        pass  # the log never changes the decision


def main():
    def _timeout(_sig, _frm):
        os._exit(0)  # fail open: an efficiency gate never holds a Read hostage
    signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(WATCHDOG_S)
    try:
        data = json.loads(sys.stdin.read() or '{}')
        block, size, path = decide(data)
    except Exception:  # noqa: BLE001 -- fail open on anything unexpected
        return 0
    if not block:
        return 0
    log_block(data, size, path)
    sys.stderr.write(MESSAGE.format(name=os.path.basename(path), kib=size // 1024, path=path))
    return 2


if __name__ == '__main__':
    sys.exit(main())
