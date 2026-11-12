#!/usr/bin/env python3
"""time-claim-gate.py -- PreToolUse gate: no guessed "measured at" clock time in shared reports and card comments,
and no placeholder clock time in an inter-agent message, a memory or the daily log.

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
  - Bash that writes a shared/*.md through the shell (Radar 39251: `cat >> .../shared/hibanaplo.md <<'EOF'`
    wrote a future time unseen): a `>` / `>>` / `>|` redirect or a `tee [-a]` whose target resolves to a
    shared/*.md. The command text (the heredoc body) is judged; lines already in a target file pass, like
    Write. A relative target is resolved against the payload cwd and against every `cd /absolute/dir` in
    the command (the gate cannot know which cd ran last, so a match through any of them counts).
  - Bash that sends an inter-agent message or writes a memory or the daily log (Dave 39699, 2026-11-12: his
    39698 went to Klodel with a placeholder measured time while the same text on the card was stopped): the
    command text names agent-msg.sh, a <name>-msg.sh / msg-close.sh wrapper, /api/messages, /api/memories
    or /api/daily-log. Judged like a card comment (command text + @file payload, and a `< file` stdin
    redirect), but ONLY rule 1 (placeholder). Rule 2 is off here: measured on the 7 days of agent_messages
    before 2026-11-12, the 346 "future" hits were mostly plans, deadlines and quota reset times
    ("nullázás 12:05", "23:00 után"), while the 323 placeholders were the real error.
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
future (the block text says to add the date); a shell write whose target is a variable ("> $F"), a relative
path after a relative cd, or a file written by an interpreter (python3 open(..., 'a')) is not seen; only the
cwd and the first 5 distinct cds are bases, and only the first 20 .md words (40 candidate paths) are looked at,
so 20 other "> x.md" redirects before the real target hide it. Any ".md" word after a ">" counts as a target,
so an echo of "a => <...>/shared/x.md" next to a future measured time is blocked too (Viktor 39257 INFO).
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
# Inter-agent message, memory and daily-log writes (placeholder rule only, see SCOPE).
API_WRITE_RX = re.compile(r'(?<![\w-])(?:[a-z]+-msg|msg-close)\.sh(?![\w-])|/api/(?:messages|memories|daily-log)')
STDIN_FILE_RX = re.compile(r'(?<![<\d])<[ \t]*[\'"]?([^\s\'";|&<>()]+)')
DATA_FILE_RX = re.compile(r'(?<![\w-])(?:--data-binary|--data|-d)(?:\s+|=)?[\'"]?@([^\s\'";|&<>()]+)')
# Shell writes (Radar 39251). ">>f", "> 'f'", ">| f"; "2>&1" has no path and does not match. tee takes every
# non-option word up to the next shell operator.
REDIRECT_RX = re.compile(r'>>?\|?[ \t]*[\'"]?([^\s\'";|&<>()]+)')
TEE_RX = re.compile(r'(?<![\w./-])tee((?:[ \t]+[^\s;|&<>()]+)+)')
CD_RX = re.compile(r'(?<![\w./-])cd[ \t]+[\'"]?(/[^\s\'";|&<>()]+)')
MAX_SHELL_TARGETS = 20
MAX_SHELL_BASES = 6
MAX_SHELL_PATHS = 40


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


def findings(text, now, known_lines=frozenset(), placeholder_only=False):
    """[(line_no, token, kind)] for the lines of `text` that are not in known_lines."""
    out = []
    limit = now.hour * 60 + now.minute + SLACK_MIN
    for n, line in enumerate(text.splitlines(), 1):
        if line in known_lines:
            continue
        for m in PLACEHOLDER_RX.finditer(line):
            out.append((n, m.group(0), 'placeholder'))
        if placeholder_only or not MARKER_RX.search(line) or _other_day(line, now):
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


def _shell_shared_md_targets(cmd, cwd):
    """Realpaths of the shared/*.md files a shell redirect or tee in `cmd` writes (at most MAX_SHELL_TARGETS)."""
    words = [m.group(1) for m in REDIRECT_RX.finditer(cmd)]
    for m in TEE_RX.finditer(cmd):
        words += [w.strip('\'"') for w in m.group(1).split() if not w.startswith('-')]
    # Bounded run time (Viktor 38419, 39257 LOW): unique bases, at most MAX_SHELL_BASES (the cwd and the first
    # cds), at most MAX_SHELL_PATHS candidate paths in all, and a set for the seen realpaths. Without the caps
    # 20 relative words x 2000 cds took 4 s.
    bases = [b for b in [cwd] if isinstance(b, str) and os.path.isabs(b)] + CD_RX.findall(cmd)
    bases = list(dict.fromkeys(bases))[:MAX_SHELL_BASES]
    # Only .md words count toward the cap, so twenty "> /dev/null" before the real target do not hide it.
    candidates = []
    for w in [w for w in words if w.lower().endswith('.md')][:MAX_SHELL_TARGETS]:
        w = os.path.expanduser(w)
        candidates += [w] if os.path.isabs(w) else [os.path.join(b, w) for b in bases]
    out, seen = [], set()
    for path in candidates[:MAX_SHELL_PATHS]:
        if _is_shared_md(path):
            real = os.path.realpath(path)
            if real not in seen:
                seen.add(real)
                out.append(real)
    return out


def judged_texts(tool_name, ti, cwd):
    """[(label, text, known_lines)] to judge for this call; [] when the call is out of scope."""
    if tool_name in ('Write', 'Edit', 'MultiEdit'):
        path = ti.get('file_path')
        if not _is_shared_md(path):
            return []
        if tool_name == 'Write':
            content = ti.get('content')
            return [('', content, _existing_lines(path), False)] if isinstance(content, str) else []
        edits = [ti] if tool_name == 'Edit' else ti.get('edits')
        out = []
        for e in edits if isinstance(edits, list) else []:
            if isinstance(e, dict) and isinstance(e.get('new_string'), str):
                old = e.get('old_string')
                out.append(('', e['new_string'], frozenset(old.splitlines()) if isinstance(old, str) else frozenset(),
                            False))
        return out
    if tool_name == 'Bash':
        cmd = ti.get('command')
        if not isinstance(cmd, str):
            return []
        card = '/api/kanban/' in cmd and '/comments' in cmd
        if not card and not API_WRITE_RX.search(cmd):
            targets = _shell_shared_md_targets(cmd, cwd)
            if not targets:
                return []
            return [('command ', cmd, frozenset().union(*(_existing_lines(t) for t in targets)), False)]
        refs = DATA_FILE_RX.findall(cmd)
        if not card:
            # A message body can come from a file on stdin: agent-msg.sh kernel klodel - < body.txt
            refs += STDIN_FILE_RX.findall(cmd)[:MAX_SHELL_TARGETS]
        po = not card  # message / memory / daily log: placeholder rule only
        out = [('command ', cmd, frozenset(), po)]
        for ref in refs:
            path = os.path.expanduser(ref)
            if not os.path.isabs(path):
                if not (isinstance(cwd, str) and os.path.isabs(cwd)):
                    continue
                path = os.path.join(cwd, path)
            body = _read_small(path)
            if body is not None:
                out.append(('@file ', body, frozenset(), po))
        return out
    return []


def verdict(payload):
    ti = payload.get('tool_input')
    if not isinstance(ti, dict):
        return None
    now = _now()
    hits = []
    for label, text, known, po in judged_texts(payload.get('tool_name'), ti, payload.get('cwd')):
        hits += [(label, n, tok, kind) for n, tok, kind in findings(text, now, known, po)]
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
