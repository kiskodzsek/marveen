#!/usr/bin/env python3
"""time-claim-gate.py -- PreToolUse gate: no guessed "measured at" clock time in shared reports and card comments.

WHY (Klodel 38401, 2026-11-11): an agent three times wrote a GUESSED measurement time into a report or a
kanban comment: a placeholder ("19:3x", "10:xx") or a time later than the wall clock ("mérve 18:15-18:30"
while `date` said 18:14). A guessed time that is a placeholder or still in the future is the catchable form
of that error. The rule logic comes from agents/kernel/tools/ido-jovo-lint, made stricter on false positives.

SCOPE (everything else is allowed at once, exit 0, no output):
  - Write / Edit / MultiEdit of a file whose realpath is under <repo-root>/shared/ and ends in .md.
    Write: tool_input.content; Edit: new_string; MultiEdit: every edits[].new_string.
    Only NEW lines are judged: a line already in the file (Write) or in old_string (Edit) passes, so
    rewriting a report with yesterday's undated lines in it does not trip the gate.
  - Bash, only when the command text contains "/api/kanban/" and "/comments" (a card comment). The command
    text is judged (inline heredoc / -d payload); a `--data-binary @file`, `--data @file` or `-d @file`
    payload is read too when it is a regular file of at most 64 KB.
  <repo-root> is two levels above this file (scripts/hooks/ -> root), so it works in a worktree too.

BLOCKS (exit 2, reason on stderr):
  1. A placeholder clock time anywhere in the judged lines: HH:Mx or HH:xx (x or X), e.g. 19:3x, 10:xx.
  2. A FUTURE MEASURED time: HH:MM (or HH:MM:SS, judged by its HH:MM) later than the current minute, on a
     line that names a measurement
     (mérve, mérés..., mért, `date`, a bare date / (date), date szerint, measured, lefutott, futott, elküldve,
     küldve, lezárva, rögzítve; case-insensitive, accented forms only: unaccented "mert" is the Hungarian "because")
     and that does not name another date (YYYY-MM-DD or MM-DD other than today). A future time with no
     marker on its line (a deadline: "21:00-ig kész") passes: that is the main false-positive guard.
     A deadline-shaped time passes even on a marker line: followed by -ig / -ra / -re / óráig, or preceded
     by határidő / deadline / until / by ("mérve 19:40, kész 22:00-ig").
Known gaps: a time written after midnight about the previous evening without a date on the line is read as
future (the block text says to add the date); a shared/*.md written through Bash (cat > file) is not seen.
Per line only the first 20 clock times are judged, the deadline word only within 40 characters before the time
(bounded run time, Viktor 38419). This is a hygiene gate for a common mistake, not a security control.

CONTRACT (hook-exit-code-invariant): exit 2 = block, exit 0 = allow, never exit 1. Malformed stdin, an
unexpected type or an unreadable file is not a verdict: allow (fail OPEN); an internal error is recorded in
store/hook-errors.log through hook_errlog. The block text names only the offending token and its line
number, never the surrounding text.

TEST SEAM: TIME_CLAIM_GATE_NOW="HH:MM" replaces the wall-clock hour and minute (the date stays today's);
an unparseable value is ignored. Nothing else is read from the environment.
Tests: python3 -I scripts/hooks/time-claim-gate_test.py
"""
import datetime
import json
import os
import re
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SHARED_DIR = os.path.join(os.path.realpath(os.path.join(HERE, '..', '..')), 'shared')
# 0: a minute after the current one is already a guess. With 2, Kernel's "08:20 date" written at 08:19:49
# (2026-11-12, hibanapló) passed; the clock is this machine's, so there is no skew to absorb (Klodel 38942).
SLACK_MIN = 0
MAX_DATA_FILE = 64 * 1024
DEADLINE_WINDOW = 40
MAX_TIMES_PER_LINE = 20

# Seconds are optional and judged by their HH:MM ("mérve 08:48:10"); a trailing colon that is not followed by a
# digit ends the time ("08:48: kész", Kernel 39004), so neither form slips past the gate any more.
TIME_RX = re.compile(r'(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?(?!\d)(?!:\d)')
PLACEHOLDER_RX = re.compile(r'(?<![\d:])(?:[01]?\d|2[0-3]):(?:[0-5][xX]|[xX]{2})(?!\w)')
# Not preceded or followed by ':' so the range "10:05-11:30" is not read as the date 05-11.
DATE_RX = re.compile(r'(?<![\d:])(?:(\d{4})-)?(\d{2})-(\d{2})(?![\d:])')
MARKER_RX = re.compile(
    r'(?<!\w)(?:mérve|mérés\w*|mért|measured|lefutott|futott|elküldve|küldve|lezárva|rögzítve|date\s+szerint)(?!\w)'
    r'|`date\b'
    # A bare "date" / "(date)" names the `date` command too ("Kernel 08:48 date:", Kernel 39004). Not inside a
    # word, a JS call or a dotted / dashed name: "update", "Date(", "date.now", "date-fns" are not markers.
    r'|(?<![\w.$/-])date(?![\w(.-])', re.I)
# A deadline, not a measurement: "22:00-ig", "22:00-ra", "22:00 óráig"; "határidő 22:00", "by 22:00".
DEADLINE_AFTER_RX = re.compile(r'\s?-?\s?(?:ig|ra|re)(?!\w)|\s+óráig(?!\w)', re.I)
DEADLINE_BEFORE_RX = re.compile(r'(?<!\w)(?:határidő|határidővel|deadline|until|by)[:\s]+$', re.I)
DATA_FILE_RX = re.compile(r'(?<![\w-])(?:--data-binary|--data|-d)(?:\s+|=)?[\'"]?@([^\s\'";|&<>()]+)')


def _now():
    now = datetime.datetime.now()
    override = os.environ.get('TIME_CLAIM_GATE_NOW', '')
    m = re.fullmatch(r'([01]?\d|2[0-3]):([0-5]\d)', override)
    if m:
        now = now.replace(hour=int(m.group(1)), minute=int(m.group(2)))
    return now


def _other_day(line, now):
    for year, mo, d in DATE_RX.findall(line):
        mo, d = int(mo), int(d)
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            continue
        if (mo, d) != (now.month, now.day) or (year and int(year) != now.year):
            return True
    return False


def findings(text, now, known_lines=frozenset()):
    """[(line_no, token, kind)] for the lines of `text` that are not in known_lines."""
    out = []
    limit = now.hour * 60 + now.minute + SLACK_MIN
    for n, line in enumerate(text.splitlines(), 1):
        if line in known_lines:
            continue
        for m in PLACEHOLDER_RX.finditer(line):
            out.append((n, m.group(0), 'placeholder'))
        if not MARKER_RX.search(line) or _other_day(line, now):
            continue
        # Bounded work per line (Viktor 38419 LOW): at most MAX_TIMES_PER_LINE times, and the deadline word
        # is looked for only in the DEADLINE_WINDOW characters right before the time.
        for i, m in enumerate(TIME_RX.finditer(line)):
            if i >= MAX_TIMES_PER_LINE:
                break
            if (DEADLINE_AFTER_RX.match(line, m.end())
                    or DEADLINE_BEFORE_RX.search(line[max(0, m.start() - DEADLINE_WINDOW):m.start()])):
                continue
            if int(m.group(1)) * 60 + int(m.group(2)) > limit:
                out.append((n, m.group(0), 'future'))
    return out


def _is_shared_md(path):
    if not isinstance(path, str) or not path:
        return False
    real = os.path.realpath(path)
    return real.lower().endswith('.md') and real.startswith(SHARED_DIR + os.sep)


def _read_small(path):
    """Text of a regular file of at most MAX_DATA_FILE bytes, else None."""
    try:
        st = os.stat(path)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_DATA_FILE:
            return None
        with open(path, encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except OSError:
        return None


def _existing_lines(path):
    """Lines of the file a Write replaces (a new or unreadable file has none)."""
    try:
        if os.stat(path).st_size > 4 * 1024 * 1024:
            return frozenset()
        with open(path, encoding='utf-8', errors='replace') as fh:
            return frozenset(fh.read().splitlines())
    except OSError:
        return frozenset()


def judged_texts(tool_name, ti, cwd):
    """[(label, text, known_lines)] to judge for this call; [] when the call is out of scope."""
    if tool_name in ('Write', 'Edit', 'MultiEdit'):
        path = ti.get('file_path')
        if not _is_shared_md(path):
            return []
        if tool_name == 'Write':
            content = ti.get('content')
            return [('', content, _existing_lines(path))] if isinstance(content, str) else []
        edits = [ti] if tool_name == 'Edit' else ti.get('edits')
        out = []
        for e in edits if isinstance(edits, list) else []:
            if isinstance(e, dict) and isinstance(e.get('new_string'), str):
                old = e.get('old_string')
                out.append(('', e['new_string'], frozenset(old.splitlines()) if isinstance(old, str) else frozenset()))
        return out
    if tool_name == 'Bash':
        cmd = ti.get('command')
        if not isinstance(cmd, str) or '/api/kanban/' not in cmd or '/comments' not in cmd:
            return []
        out = [('command ', cmd, frozenset())]
        for ref in DATA_FILE_RX.findall(cmd):
            path = os.path.expanduser(ref)
            if not os.path.isabs(path):
                if not (isinstance(cwd, str) and os.path.isabs(cwd)):
                    continue
                path = os.path.join(cwd, path)
            body = _read_small(path)
            if body is not None:
                out.append(('@file ', body, frozenset()))
        return out
    return []


def verdict(payload):
    ti = payload.get('tool_input')
    if not isinstance(ti, dict):
        return None
    now = _now()
    hits = []
    for label, text, known in judged_texts(payload.get('tool_name'), ti, payload.get('cwd')):
        hits += [(label, n, tok, kind) for n, tok, kind in findings(text, now, known)]
    if not hits:
        return None
    parts = []
    for label, n, tok, kind in hits[:3]:
        what = 'helykitöltő idő / placeholder time' if kind == 'placeholder' else f'jövőbeli mért idő / future measured time (now {now:%H:%M})'
        parts.append(f'{label}line {n}: "{tok}" = {what}')
    return ('IDO-KAPU / TIME-CLAIM-GATE: ' + '; '.join(parts) + '. '
            'Futtasd a `date`-et, és a MÉRT időt írd be (nem becsültet, nem 19:3x-et). '
            'Run `date` and write the measured time. Ha az idő másik napé, a sorba írd a dátumot (MM-DD). '
            'If the time belongs to another day, put its date (MM-DD) on the line.')


def main():
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        reason = verdict(payload)
    except Exception as ex:  # a crashing gate must not become a silent exit 1
        try:
            import hook_errlog
            hook_errlog.report('time-claim-gate', 'internal error, allowed', ex)
        except Exception:
            pass
        return 0
    if reason:
        sys.stderr.write(reason + '\n')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
