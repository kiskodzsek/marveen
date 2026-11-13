#!/usr/bin/env python3
"""time-claim-gate.py -- PreToolUse gate: no guessed "measured at" clock time in shared reports and card comments,
no placeholder clock time in an inter-agent message, a memory or the daily log, and no future daily-log heading.

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
  - Rule 3, the daily log only (Dave 39739, 2026-11-12): the entry's own heading time, "## HH:MM" (one to six
    '#') at the very START of a payload's "content" value, must not be later than the current minute (slack 0,
    like #193). Measured read-only on store/claudeclaw.db daily_logs since 2026-11-05: 195 of the 270 entries
    that start with such a heading were written before the time in their heading ("## 15:05" written at 12:43,
    "## 16:58" at 16:48). Only a command that names /api/daily-log, and only the start of the content value:
    a deadline in the body is not judged, and a message that names the endpoint and quotes a heading is not a
    log write. A heading line that names another date (MM-DD, YYYY-MM-DD) passes.
  - Rule 4, card comments only (Dave 39858, 2026-11-13): the comment's own opening time, at the START of a
    payload's "content" value (after at most 30 characters with no digit, e.g. an author name: "Kernel 08:48",
    "Klodel (13:12, date)", "2026-11-13 08:46 - ..."), must not be later than the current minute, with or without
    a marker word. Dave's "2026-11-13 08:46 - #1289 ..." went in at 08:44 because its line has no marker word, so
    rule 2 never looked at it. Measured read-only on store/claudeclaw.db kanban_comments since 2026-11-11: 962
    comments, 49 opened with a time later than their own created_at minute, 26 of them with no marker word.
    Old vs new verdict on those comments, each at its own created_at minute (963 by then): 156 -> 185 blocks,
    29 new, 0 released; all 29 are opening stamps later than the comment's own creation ("Klodel 03:14: kész"
    written at 03:12), none a plan or a deadline.
    Passes: a date other than today right before the time; a time followed by a suffix ("23:50-es", "08:00-kor"),
    a deadline (-ig, -ra, -re, óráig) or a plan word (után, előtt, terv...): "Indulás 08:00 után", "## 23:59 terv".
  <repo-root> is two levels above this file (scripts/hooks/ -> root), so it works in a worktree too.

BLOCKS (exit 2, reason on stderr):
  1. A placeholder clock time anywhere in the judged lines: HH:Mx or HH:xx (x or X), e.g. 19:3x, 10:xx.
  2. A FUTURE MEASURED time: HH:MM (or HH:MM:SS, judged by its HH:MM) later than the current minute, on a
     line that names a measurement
     (mérve, mérés..., mért, `date`, a bare date / (date), date szerint, measured, lefutott, futott, elküldve,
     küldve, lezárva, rögzítve; case-insensitive, accented forms only: unaccented "mert" is the Hungarian "because")
     and that does not name another date (YYYY-MM-DD or MM-DD other than today). A future time with no
     marker on its line (a deadline: "21:00-ig kész") passes: that is the main false-positive guard.
     Exception to "another date": a time written right after TODAY's date ("11-13 02:19", "2026-11-13, 02:19",
     "11-13T02:19") is judged even on a line that names another day (Klodel 39769, 2026-11-13: "Dream Engine
     11-13 <a time 11 minutes ahead> mérése ... (Pulzus átvezetése 11-12 23:26)" passed, because the yesterday
     date exempted the whole line). Only this explicit form: making every date speak for its own time alone was
     measured on the kanban comments since 2026-11-05 and gave 32 new blocks, mostly lists and ranges that
     continue an earlier date ("11-04 13:39-13:49", "L0 11-05 21:50, 23:00"). The narrow form gives 8 new blocks
     there: 5 guessed stamps ("11-06 14:33:" written at 14:29) and 3 plans; the end of a window after "->"
     ("11-08 14:14 -> 11-09 18:00") passes, which removes one of the three.
     A deadline-shaped time passes even on a marker line: followed by -ig / -ra / -re / óráig, or preceded
     by határidő / deadline / until / by ("mérve 19:40, kész 22:00-ig").
  3. A daily-log heading time later than the current minute (SCOPE, rule 3).
  4. A card comment's opening time later than the current minute (SCOPE, rule 4).
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
# Rule 3: the heading at the start of a daily-log payload's "content" value. The rest of the heading line (up to a
# newline, a JSON escape or the closing quote) is captured for the other-day check.
DAILY_LOG = '/api/daily-log'
HEADING_RX = re.compile(r'"content"\s*:\s*"\s*#{1,6}[ \t]*([01]?\d|2[0-3]):([0-5]\d)(?![\d:])([^"\n\\]{0,200})')
# Rule 4: the opening time of a card comment's "content" value. Group 1: the no-digit prefix (an author name);
# groups 2-4: an optional date written right before the time; 5-6: the time.
COMMENT_HEAD_RX = re.compile(
    r'"content"\s*:\s*"([^"\n\\\d]{0,30}?)(?:(?:(\d{4})-)?(\d{2})-(\d{2})(?:[ \t]{1,3}|[ \t]?,[ \t]{0,2}|T))?'
    r'([01]?\d|2[0-3]):([0-5]\d)(?!\d)(?!:\d)')
# Right after the time: a suffix ("23:50-es", "08:00-kor") or a plan word; the time is not the comment's stamp.
COMMENT_HEAD_NOT_STAMP_RX = re.compile(r'-[^\W\d_]|[ \t]+(?:után|előtt|terv\w*)(?!\w)', re.I)
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


def _date_is_other(year, mo, d, now):
    """True / False for a real calendar date (another day / today), None for a non-date (e.g. "45-99")."""
    mo, d = int(mo), int(d)
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return (mo, d) != (now.month, now.day) or bool(year and int(year) != now.year)


def _other_day(line, now):
    return any(_date_is_other(year, mo, d, now) for year, mo, d in DATE_RX.findall(line))


# The text between a date and the time it belongs to: "11-12 23:26", "11-12, 23:26", "11-12T23:26".
ATTACHED_GAP_RX = re.compile(r'[ \t]{1,3}|[ \t]?,[ \t]{0,2}|T')


def _attached_date(line, start, dates):
    """The DATE_RX match written right before the time that starts at `start`, or None."""
    for dm in dates:
        if dm.end() <= start and ATTACHED_GAP_RX.fullmatch(line, dm.end(), start):
            return dm
    return None


def findings(text, now, known_lines=frozenset(), placeholder_only=False):
    """[(line_no, token, kind)] for the lines of `text` that are not in known_lines."""
    out = []
    limit = now.hour * 60 + now.minute + SLACK_MIN
    for n, line in enumerate(text.splitlines(), 1):
        if line in known_lines:
            continue
        for m in PLACEHOLDER_RX.finditer(line):
            out.append((n, m.group(0), 'placeholder'))
        if placeholder_only or not MARKER_RX.search(line):
            continue
        # Bounded work per line (Viktor 38419 LOW): at most MAX_TIMES_PER_LINE times, and the deadline word
        # is looked for only in the DEADLINE_WINDOW characters right before the time.
        line_other = _other_day(line, now)
        dates = [dm for _, dm in zip(range(MAX_TIMES_PER_LINE), DATE_RX.finditer(line))] if line_other else []
        for i, m in enumerate(TIME_RX.finditer(line)):
            if i >= MAX_TIMES_PER_LINE:
                break
            if line_other:
                # Another day on the line: only a time written right after today's date is still judged.
                dm = _attached_date(line, m.start(), dates)
                if dm is None or _date_is_other(*dm.groups(), now) is not False:
                    continue
                if line[:dm.start()].rstrip().endswith(('->', '→')):  # a window's end: "11-08 14:14 -> 11-09 18:00"
                    continue
            if (DEADLINE_AFTER_RX.match(line, m.end())
                    or DEADLINE_BEFORE_RX.search(line[max(0, m.start() - DEADLINE_WINDOW):m.start()])):
                continue
            if int(m.group(1)) * 60 + int(m.group(2)) > limit:
                out.append((n, m.group(0), 'future'))
    return out


def heading_findings(text, now):
    """[(line_no, token, 'heading')] for a daily-log heading time later than the current minute (rule 3)."""
    out = []
    limit = now.hour * 60 + now.minute + SLACK_MIN
    for m in HEADING_RX.finditer(text):
        if len(out) >= MAX_TIMES_PER_LINE:
            break
        if _other_day(m.group(3), now):
            continue
        if int(m.group(1)) * 60 + int(m.group(2)) > limit:
            out.append((text.count('\n', 0, m.start()) + 1, f'{m.group(1)}:{m.group(2)}', 'heading'))
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


def comment_head_findings(text, now):
    """[(line_no, token, 'card-head')] for a card comment's opening time later than the current minute (rule 4)."""
    out = []
    limit = now.hour * 60 + now.minute + SLACK_MIN
    for m in COMMENT_HEAD_RX.finditer(text):
        if len(out) >= MAX_TIMES_PER_LINE:
            break
        if m.group(3) and _date_is_other(m.group(2), m.group(3), m.group(4), now) is not False:
            continue
        if (COMMENT_HEAD_NOT_STAMP_RX.match(text, m.end()) or DEADLINE_AFTER_RX.match(text, m.end())
                or DEADLINE_BEFORE_RX.search(m.group(1))):
            continue
        if int(m.group(5)) * 60 + int(m.group(6)) > limit:
            out.append((text.count('\n', 0, m.start()) + 1, f'{m.group(5)}:{m.group(6)}', 'card-head'))
    return out


def judged_texts(tool_name, ti, cwd):
    """[(label, text, known_lines, placeholder_only, daily_log, card)] to judge; [] when the call is out of scope."""
    if tool_name in ('Write', 'Edit', 'MultiEdit'):
        path = ti.get('file_path')
        if not _is_shared_md(path):
            return []
        if tool_name == 'Write':
            content = ti.get('content')
            return [('', content, _existing_lines(path), False, False, False)] if isinstance(content, str) else []
        edits = [ti] if tool_name == 'Edit' else ti.get('edits')
        out = []
        for e in edits if isinstance(edits, list) else []:
            if isinstance(e, dict) and isinstance(e.get('new_string'), str):
                old = e.get('old_string')
                out.append(('', e['new_string'], frozenset(old.splitlines()) if isinstance(old, str) else frozenset(),
                            False, False, False))
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
            return [('command ', cmd, frozenset().union(*(_existing_lines(t) for t in targets)), False, False, False)]
        refs = DATA_FILE_RX.findall(cmd)
        if not card:
            # A message body can come from a file on stdin: agent-msg.sh kernel klodel - < body.txt
            refs += STDIN_FILE_RX.findall(cmd)[:MAX_SHELL_TARGETS]
        po = not card  # message / memory / daily log: placeholder rule only
        hd = not card and DAILY_LOG in cmd  # rule 3: the daily-log heading
        out = [('command ', cmd, frozenset(), po, hd, card)]
        for ref in refs:
            path = os.path.expanduser(ref)
            if not os.path.isabs(path):
                if not (isinstance(cwd, str) and os.path.isabs(cwd)):
                    continue
                path = os.path.join(cwd, path)
            body = _read_small(path)
            if body is not None:
                out.append(('@file ', body, frozenset(), po, hd, card))
        return out
    return []


def verdict(payload):
    ti = payload.get('tool_input')
    if not isinstance(ti, dict):
        return None
    now = _now()
    hits = []
    for label, text, known, po, hd, card in judged_texts(payload.get('tool_name'), ti, payload.get('cwd')):
        found = findings(text, now, known, po)
        hits += [(label, n, tok, kind) for n, tok, kind in found]
        if hd:
            hits += [(label, n, tok, kind) for n, tok, kind in heading_findings(text, now)]
        if card:
            seen = {(n, tok) for n, tok, _ in found}
            hits += [(label, n, tok, kind) for n, tok, kind in comment_head_findings(text, now) if (n, tok) not in seen]
    if not hits:
        return None
    parts = []
    for label, n, tok, kind in hits[:3]:
        what = ('helykitöltő idő / placeholder time' if kind == 'placeholder'
                else f'jövőbeli naplófejléc / future daily-log heading (now {now:%H:%M})' if kind == 'heading'
                else f'jövőbeli komment-időbélyeg / future comment stamp (now {now:%H:%M})' if kind == 'card-head'
                else f'jövőbeli mért idő / future measured time (now {now:%H:%M})')
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
