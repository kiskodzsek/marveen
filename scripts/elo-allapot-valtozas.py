#!/usr/bin/env python3
"""elo-allapot-valtozas.py -- pass the live status text on only when it changed in substance.

Usage: python3 -I ops/elo_allapot.py csoport | python3 -I scripts/elo-allapot-valtozas.py csoport [--state FILE]

Why (Klodel 39721, card 12610b8d, 2026-11-12): the elo-allapot-frissites schedule edits the group's live status
message every round, although between two rounds usually only the "frissítve HH:MM" stamp and the daily joke
differ. An edit with nothing new in it is noise for the group; this filter lets the schedule skip it.

What counts as a change: the text from stdin after normalising
  - every "frissítve HH:MM" stamp (the header, and the visitors block's data time) -> "frissítve --:--";
  - the joke line (a line that starts with "😄 ") -> dropped;
  - trailing whitespace per line, runs of blank lines (one counts) and blank lines at both ends.
Everything else (a step done, a project added or cut, the active list, PATRIKRA VÁR, the visitor numbers, the
visitors block appearing or ageing out) is a change.

Exit codes and output:
  0 = changed: the ORIGINAL text goes to stdout unchanged, and its normalised sha256 is recorded in the state file
      (written atomically), so the next round compares against this one.
  3 = no change in substance: nothing on stdout, the state file is not touched. The schedule does NOT edit.
  2 = usage error or empty input: nothing on stdout, state untouched (never edit with an empty text).
State: <repo-root>/store/elo-allapot-<mode>.sha256 (mode: csoport | privat), or --state FILE (test seam).
A missing or unreadable state file counts as "changed" (the first run edits once).

Known limit: the hash is recorded before the edit. If the edit_message call then fails, the next round sees "no
change" until the content really changes. Run with --no-record to compare only, and record with a second run
after a successful edit, if that ever matters.
Tests: python3 -I scripts/__tests__/elo-allapot-valtozas.test.py
"""
import hashlib
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODES = ('csoport', 'privat')
STAMP_RX = re.compile(r'frissítve \d{1,2}:\d{2}')
JOKE_PREFIX = '😄 '
MAX_INPUT = 256 * 1024


def normalise(text):
    lines = []
    for ln in text.splitlines():
        if ln.lstrip().startswith(JOKE_PREFIX):
            continue
        ln = STAMP_RX.sub('frissítve --:--', ln).rstrip()
        if ln or (lines and lines[-1]):  # runs of blank lines count as one (a dropped joke leaves its blank line)
            lines.append(ln)
    return '\n'.join(lines).strip('\n')


def digest(text):
    return hashlib.sha256(normalise(text).encode('utf-8')).hexdigest()


def read_state(path):
    try:
        with open(path, encoding='ascii') as fh:
            return fh.read().strip()
    except (OSError, UnicodeDecodeError):
        return ''


def write_state(path, value):
    d = os.path.dirname(path) or '.'
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.elo-allapot-')
    with os.fdopen(fd, 'w', encoding='ascii') as fh:
        fh.write(value + '\n')
    os.replace(tmp, path)


def main(argv):
    args, state, record, rest = [], None, True, list(argv[1:])
    while rest:
        a = rest.pop(0)
        if a == '--state' and rest:
            state = rest.pop(0)
        elif a.startswith('--state='):
            state = a.split('=', 1)[1]
        elif a == '--no-record':
            record = False
        else:
            args.append(a)
    if len(args) != 1 or args[0] not in MODES or state == '':
        print('usage: elo-allapot-valtozas.py csoport|privat [--state FILE] [--no-record] < text', file=sys.stderr)
        return 2
    mode = args[0]
    state = state or os.path.join(ROOT, 'store', f'elo-allapot-{mode}.sha256')
    text = sys.stdin.read(MAX_INPUT + 1)
    if not text.strip() or len(text) > MAX_INPUT:
        print('elo-allapot-valtozas: empty or oversized input, nothing to edit', file=sys.stderr)
        return 2
    new = digest(text)
    if read_state(state) == new:
        return 3
    if record:
        write_state(state, new)
    sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
