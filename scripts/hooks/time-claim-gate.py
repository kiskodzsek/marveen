#!/usr/bin/env python3
"""time-claim-gate.py -- PreToolUse gate: no guessed "measured at" clock time in shared reports, card comments,
inter-agent messages, close results and the daily log, no placeholder clock time in a memory either, and a daily-log
heading time only through the {{NOW}} token.

WHY (Klodel 38401, 2026-11-11): an agent three times wrote a GUESSED measurement time into a report or a
kanban comment: a placeholder ("19:3x", "10:xx") or a time later than the wall clock ("mérve 18:15-18:30"
while `date` said 18:14). A guessed time that is a placeholder or still in the future is the catchable form
of that error. The rule logic comes from agents/kernel/tools/ido-jovo-lint, made stricter on false positives.

SCOPE (everything else is allowed at once, exit 0, no output):
  - Write / Edit / MultiEdit of a file whose realpath is under <repo-root>/shared/ and ends in .md.
    Write: tool_input.content; Edit: new_string; MultiEdit: every edits[].new_string.
    Only NEW lines are judged: a line already in the file (Write) or in old_string (Edit) passes, so
    rewriting a report with yesterday's undated lines in it does not trip the gate.
  - Bash, a card comment: the command text contains "/api/kanban/" and "/comments" or "/move" (the "comment"
    field of a move, where the kanban-waiting gate puts the VÁR line; Dave 49788), or a PUT to /api/kanban/
    (`-X PUT`, `-sX PUT`, `--request PUT`, `method='PUT'` in any case, `request[s].put(` (that module's
    top-level put only; httpx.put and a Session's put are not seen),
    `.request('PUT'`) that carries a comment key (JSON, escaped, a Python dict key or `['comment']` subscript,
    `.comment |=`, or bare after `{` `,` `(` `.` or at an indented line start as jq / JS write it; in the
    command or a data file;
    src/web/routes/kanban.ts stores it like a move) and is not itself a message, memory or log write (that
    exclusion holds only when no real curl segment of the command has /api/kanban/ as its own URL and a PUT,
    so a kanban PUT next to a message close or a memory write is still judged; Viktor 49831 L8). The
    command text is judged (inline heredoc / -d payload); a `--data-binary @file`, `--data @file`,
    `--json @file` or `-d @file` payload, and a `< file` stdin redirect when curl reads stdin (`@-`), are read
    too when they are regular files of at most 64 KB (at most MAX_SHELL_TARGETS distinct ones); a `<b>` /
    `<notes.md>` in a text (the name ends right at `>`) is not a stdin redirect (L11; so `<f.json>out` with no
    space is not read either, Viktor 49831 I7).
    Known limits of the card path (Viktor 49811, 49824; the same on /comments): a body on stdin (pipe) is not in
    the command text; a url-var (the URL from a variable, no literal /api/kanban/) is not seen; a relfile (a
    relative @file after a cd) is resolved against the payload cwd only; curl -T (an upload file) is not read;
    rule 4's opening stamp is read in plain JSON or a Python dict (also a triple-quoted or f-/r-/b-/u-prefixed
    value, Viktor 49912 K1; rule 3 also a `content = '## ...'` variable), not escaped inside a double-quoted -d, and as
    HH:MM only, not with seconds ("Kernel 12:30:00:", an ISO stamp ...T12:30:00+01:00; the same on main);
    a jq shorthand key (`{$comment}`, a variable named comment) is not seen as a comment key; prose: a PUT
    description edit or card text that writes "(comment: ...", ", comment: ..." or ".comment = ..." next to a
    plan time is read as a comment key and overblocks (the safe side; text cannot be told from jq, Viktor 49831);
    the same for an indented "  comment: ..." line in a description text, and for a title-edit PUT next to a
    message that quotes the "comment": key (the key search reads the whole command, Viktor 49836); and a
    message or memory that quotes a kanban PUT after a backtick, a ( or a ; or at a line start (a heredoc line
    "x=a 'b c' curl -sX PUT ...") with a plan time in it is judged as a card (the segment search reads quoted text
    too: imitating shell quoting in a hook hid real PUTs twice, Viktor 49845 L13, 49870); send the quote in its own
    command, or write it without those marks. Viktor 50003 R1: a numbered list mark ("1) curl -X PUT ...") is no start
    before the first `case` word with an `in` word after it, and a then / elif / else (do) is a prefix word only after an if (for / while / until /
    select) earlier in the command; a message that also holds such a word still reads them (the safe side).
    envvalue (Viktor 49858): an env prefix whose value holds a $( ) with ; | or parentheses inside (T=$(date | tr a b)
    curl, A=$(( (1+2) )) curl) is no unit of the main's segment search; CURL_SEG2_RX starts a segment after the ),
    so next to a message or memory write that PUT is a card too, also after a lone number ($(echo 1) curl: the ) closes
    the $( and is no list mark, Viktor 50062 R2).
    The 13 smuggle labels of Viktor 49901 (indep7) and the five of 49912 K2 are closed by views next to the main's
    segment search (CURL_SEG2_RX, _kanban_put_segment; a view only adds a card judgment): shell words before curl
    (then, do, {, !, if, time, command, env, timeout N, a redirect ...), "curl" and \\curl, quotes read as units in
    the curl body (a ; in a quoted header, a multi-line -d before the URL), the own URL found with the header and
    data arguments taken out (/api/messages in an env value, a header or a -d), and the line-continuation-joined
    text (cu\\<newline>rl, T\\<newline>=v). Not seen: a curl hidden behind a function, an alias, eval or a variable
    ($c -X PUT ...), and a shell word not in that list (the same on main).
    Rule 7 (the closing stamp, Viktor 49927, his probe_ts7 labels): py-var (the comment text in a Python variable,
    the dict built elsewhere) and jq-arg (jq --arg) are not read, the value is not at a content / comment key;
    hu-dot-date ("2026.11.22. 13:30") and mmdd-short ("(11-22 13:30)") are other date forms, not judged; a named
    time zone other than Z, UTC, GMT, CET, CEST (any case; UTC/GMT with an hour offset) is not judged; deadline-word:
    a stamp right after határidő / deadline / until / by passes on purpose (a deadline, as in rule 2; none in the
    12866-comment replay). Viktor 49939: shellvar-other (the text in a shell variable of another name, like py-var)
    is not read; u0022-in-value (a raw " inside a heredoc JSON value) is invalid JSON, the value ends there;
    key-twice-last-clean (an overblock: two content keys in one object, the last one clean) blocks, every value is
    read, so a second curl in the same command is not skipped. Overblocks accepted in Viktor 49952: js-other-object
    (an object literal with a bare content key that is not the one posted), echo-comma-comment-key (prose
    ", comment: '...'" in an echo), py-sub-dumped-not-posted (a name json.dumps-ed anywhere counts as posted).
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
    a deadline in the body is not judged. A message that names the endpoint and quotes a heading in a JSON or
    Python-dict payload ({'content': '## 13:30 ...'}) is judged as a log write and overblocks (the safe side,
    Viktor 49912 K3: the payload cannot be told from a real one); without the endpoint it passes. A heading line that names another date (MM-DD, YYYY-MM-DD) passes.
  - Rule 4, card comments only (Dave 39858, 2026-11-13): the comment's own opening time, at the START of a
    payload's "content" (or a move's / PUT's "comment", Viktor 49811 L1) value (after at most 30 characters with no digit, e.g. an author name: "Kernel 08:48",
    "Klodel (13:12, date)", "2026-11-13 08:46 - ..."), must not be later than the current minute, with or without
    a marker word. Dave's "2026-11-13 08:46 - #1289 ..." went in at 08:44 because its line has no marker word, so
    rule 2 never looked at it. Measured read-only on store/claudeclaw.db kanban_comments since 2026-11-11: 962
    comments, 49 opened with a time later than their own created_at minute, 26 of them with no marker word.
    Old vs new verdict on those comments, each at its own created_at minute (963 by then): 156 -> 185 blocks,
    29 new, 0 released; all 29 are opening stamps later than the comment's own creation ("Klodel 03:14: kész"
    written at 03:12), none a plan or a deadline.
    Passes: a date other than today right before the time; a time followed by a suffix ("23:50-es", "08:00-kor"),
    a deadline (-ig, -ra, -re, óráig) or a plan word (után, előtt, terv...): "Indulás 08:00 után", "## 23:59 terv".
  - Rule 5, the send path (retro 2026-11-13 R1, card 028205dd): an inter-agent message (agent-msg.sh, a wrapper,
    /api/messages), a close result (msg-close.sh, PUT /api/messages/<id>) or a daily-log entry, NOT a memory. Rule 2
    there, narrowed to the near future: a measured time 1-15 minutes (SEND_WINDOW_MIN) after the current minute,
    unless it is a deadline (rule 2), carries a suffix or plan word ("15:40-kor", "után"), an estimate before it
    ("~", "kb.", "nem"), a UTC stamp after it ("16:13:16Z"), or its line is about a plan (nullázás, reset, ütemez...,
    holnap, tervez..., kivetít..., várható, becsl..., tipp). Measured read-only on store/claudeclaw.db, the 7 days
    before 2026-11-13 19:50, each row judged at its own created_at / completed_at: 9700 messages, 5918 results,
    326 daily-log entries -> 73, 14 and 18 hits; by hand about 87 are stamps typed ahead of the clock ("merve 15:37
    date" stored at 15:35, "a kártyán rögzítve (12:35)" closed at 12:22, "## 21:25" written at 21:17), about 6 are
    unclear (a slot label "10:00 próba-tölcsér" at 09:55). With no upper bound the same rule gave 106 message hits,
    the 33 extra all plans ("ma 15:00", the night batch); every typed-ahead stamp was at most 8 minutes ahead.
    The fix the block text gives: write {{NOW}}, which the dashboard fills in with its own minute at the write
    (src/web/now-token.ts), or run `date`.
  - Rule 6, the daily log only (retro R1): the heading time at the start of the "content" value ("## HH:MM") must
    be the {{NOW}} token, not a typed time of today (past or future); a heading that names another day passes.
  - Rule 7, card comments only (Dave 49852, card fec4c8c8): the comment's own CLOSING stamp, "(YYYY-MM-DD HH:MM)"
    with today's date (seconds and a fraction optional, a T allowed; a time zone Z, +-HH:MM, UTC, GMT, CET or CEST
    is turned into local time) as the very END of the value of a "content" / "comment" key (JSON, a Python dict,
    escaped in a double-quoted -d, or content= / comment= as dict(...) writes it; only that value, Viktor 49927 T1:
    a title, description or author ending in a stamp passes), after which only whitespace, dots, markdown marks
    (* ` _ ~) or a stray backslash follow, must not be later than the current minute (slack 0). A deadline
    ("határidő (... 18:00)", the rule 2 words right before it) passes. Dave's
    move comment written at 22:04 ended "(2026-11-21 22:06)" and passed: rule 2 wants a marker word, rule 4 reads
    only the opening stamp. Measured read-only on the kanban comments of the 14 days before 2026-11-21 22:12
    (12816): 36 end in a parenthesised stamp, 7 of them later than their own created_at; the 4 full date+time ones
    are all typed-ahead stamps (3 move comments +10 minutes, Dave's +2), and 2 of the 3 time-only ones are plans
    ("partner-levelek (14:00)."), so a time with no date is not judged. Another day's date passes.
  - Telegram reply / edit_message (Klodel 48360, hibanapló 2026-11-20 02:20): the "text" field, ONLY rule 1
    (placeholder). A placeholder time went out to the group (TG 6577) because the main agent's matcher named only
    Write|Edit|MultiEdit|Bash. Rule 2 is off here for the reason it is off on the message path: a future time in a
    chat line is mostly a plan or a deadline ("23:00 után"). The text is judged as written (no JSON unescaping), and
    the block text does not offer {{NOW}}: nothing replaces it in a Telegram message.
  - Bash payloads are judged as the reader sees them: a literal backslash-n or backslash-t is a line break or a
    tab, and a backslash-u escape (four hex digits) its character: json.dumps writes the e-acute of "mérve" as such
    an escape, and a literal backslash-n right before "lefutott" hid the marker behind the letter n.
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
  5. A measured time 1-15 minutes ahead on the send path (SCOPE, rule 5).
  6. A typed daily-log heading time of today instead of {{NOW}} (SCOPE, rule 6).
  7. A card comment's closing "(today HH:MM)" stamp later than the current minute (SCOPE, rule 7).
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
import calendar
import datetime
import itertools
import json
import os
import re
import stat
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SHARED_DIR = os.path.join(os.path.realpath(os.path.join(HERE, '..', '..')), 'shared')
# 0: a minute after the current one is already a guess. With 2, Kernel's "08:20 date" written at 08:19:49
# (2026-11-12, hibanapló) passed; the clock is this machine's, so there is no skew to absorb (Klodel 38942).
SLACK_MIN = 0
MAX_DATA_FILE = 64 * 1024
DEADLINE_WINDOW = 40
MAX_TIMES_PER_LINE = 20
# Klodel 48360: the Telegram send tools whose "text" is judged (placeholder rule only).
TELEGRAM_TEXT_TOOLS = ('mcp__plugin_telegram_telegram__reply', 'mcp__plugin_telegram_telegram__edit_message')

# Seconds are optional and judged by their HH:MM ("mérve 08:48:10"); a trailing colon that is not followed by a
# digit ends the time ("08:48: kész", Kernel 39004), so neither form slips past the gate any more.
TIME_RX = re.compile(r'(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?(?!\d)(?!:\d)')
# Viktor 48385 LOW: an underscore after the placeholder does not end the match early: MarkdownV2 italic/underline
# ("_10:xx_", "__10:xx__") is the real format on the Telegram path, and \w counts "_" as a word character.
PLACEHOLDER_RX = re.compile(r'(?<![\d:])(?:[01]?\d|2[0-3]):(?:[0-5][xX]|[xX]{2})(?![^\W_])')
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
# Rule 7 only (Viktor 49939 dl-bold-deadline): the same words in markdown marks (**deadline** (stamp)).
# Round 2 (Viktor 49949 dl-standby-word): a hyphen before the word ("stand-by") is not a deadline either.
DEADLINE_TAIL_RX = re.compile(r'(?<![\w-])[*_`~]*(?:határidő|határidővel|deadline|until|by)[*_`~]*[:\s]+$', re.I)
# Inter-agent message, memory and daily-log writes (placeholder rule only, see SCOPE).
API_WRITE_RX = re.compile(r'(?<![\w-])(?:[a-z]+-msg|msg-close)\.sh(?![\w-])|/api/(?:messages|memories|daily-log)')
# Rule 3: the heading at the start of a daily-log payload's "content" value. The rest of the heading line (up to a
# newline, a JSON escape or the closing quote) is captured for the other-day check.
DAILY_LOG = '/api/daily-log'
HEADING_RX = re.compile(r'"content"\s*:\s*"\s*#{1,6}[ \t]*([01]?\d|2[0-3]):([0-5]\d)(?![\d:])([^"\n\\]{0,200})')
# Rule 4: the opening time of a card comment's "content" value. Group 1: the no-digit prefix (an author name);
# groups 2-4: an optional date written right before the time; 5-6: the time.
COMMENT_HEAD_RX = re.compile(
    r'"(?:content|comment)"\s*:\s*"([^"\n\\\d]{0,30}?)(?:(?:(\d{4})-)?(\d{2})-(\d{2})(?:[ \t]{1,3}|[ \t]?,[ \t]{0,2}|T))?'
    r'([01]?\d|2[0-3]):([0-5]\d)(?!\d)(?!:\d)')
# The same two in a Python dict ('content': '...'), as json.dump in a heredoc or python3 -c writes the payload
# (Klodel 49904 (2), Viktor 49906: rule 3 and rule 4 passed there on every earlier head). Same groups.
# Viktor 49912 K1: the value also as a triple-quoted or f-, r-, b- or u-prefixed literal, key and value quotes
# independent; rule 3 also reads a `content = '## ...'` assignment (the dict then takes the variable).
_PY_OPEN = r'[fFrRbBuU]{0,2}(?:\'\'\'|"""|\'|")'
# After a "..." key the plain "..." value is the JSON form (HEADING_RX, COMMENT_HEAD_RX): not read twice.
_PY_OPEN_DQ_KEY = r'(?:[fFrRbBuU]{1,2}(?:\'\'\'|"""|\'|")|\'\'\'|"""|\')'
HEADING_PY_RX = re.compile(r'(?:\'content\'\s*:\s*' + _PY_OPEN + r'|"content"\s*:\s*' + _PY_OPEN_DQ_KEY
                           + r'|(?<![\w.])content[ \t]*=\s*' + _PY_OPEN + r')'
                           + r'\s*#{1,6}[ \t]*([01]?\d|2[0-3]):([0-5]\d)(?![\d:])([^\'"\n\\]{0,200})')
COMMENT_HEAD_PY_RX = re.compile(
    r'(?:\'(?:content|comment)\'\s*:\s*' + _PY_OPEN + r'|"(?:content|comment)"\s*:\s*' + _PY_OPEN_DQ_KEY
    + r')([^\'"\n\\\d]{0,30}?)'
    r'(?:(?:(\d{4})-)?(\d{2})-(\d{2})(?:[ \t]{1,3}|[ \t]?,[ \t]{0,2}|T))?([01]?\d|2[0-3]):([0-5]\d)(?!\d)(?!:\d)')


def _heads(rx, rx_py, text):
    return itertools.chain(rx.finditer(text), rx_py.finditer(text))
# Right after the time: a suffix ("23:50-es", "08:00-kor") or a plan word; the time is not the comment's stamp.
COMMENT_HEAD_NOT_STAMP_RX = re.compile(r'-[^\W\d_]|[ \t]+(?:után|előtt|terv\w*)(?!\w)', re.I)
# Rule 7 (Dave 49852, card fec4c8c8): the comment's own closing stamp. Only the value of a "content" / "comment" key
# is read (Viktor 49927 T1: a title, description or author value ending in a stamp is not the comment): JSON or a
# Python dict key with a "..." or '...' value, the key and value escaped inside a double-quoted -d, or a content= /
# comment= keyword (dict(...), a kwarg). The value runs to its first unescaped closing quote, one unit per char
# (linear: no value can overlap the next key's quote).
# Viktor 49939 item 2: a Python subscript (body['content'] = ...), a bare key (a JS object or jq, content: "..."),
# and an f-, r-, b- or u-prefixed Python literal (f'{n}/28 ...'). Round 2 (Viktor 49949 R1, 8 overblocks: a YAML
# line, a git message, a shell comment, "comment:" inside another text): a bare key counts only as an object-literal
# key, right after { or a comma; a subscript only when the same name is what the command posts (json.dumps(body),
# json=body, data=body, see POSTED_RX), so meta['content'] passes; jq's .comment = "..." (Viktor fo-jq-dot-assign)
# counts after a quote, a pipe, a paren or a blank.
_TAIL_KEY = (r'(?:(?P<k>["\'])(?:content|comment)(?P=k)\s*:'
             r'|(?P<sub>\[)(?P<k2>["\'])(?:content|comment)(?P=k2)\]\s*='
             r'|[{,]\s*(?:content|comment)\s*:|(?<![\w.$-])(?:content|comment)\s*='
             r'|(?<=[\'"|(\s])\.(?:content|comment)\s*\|?=)\s*(?:[rRbBfFuU]{1,2})?')
# The value forms after a key, in one alternation (one scan of the text, round 2: five separate regexes cost about
# 1.5x per byte): a Python triple-quoted value first (Viktor 49949 fo-py-triple-quote; a lone quote inside it is one
# unit, so the scan stays linear), then "...", '...' and a JS template literal (fo-js-template). Groups v1..v5.
VALUE_GROUPS = ('v1', 'v2', 'v3', 'v4', 'v5')
COMMENT_VALUE_RXS = (
    re.compile(_TAIL_KEY + r"(?:'''(?P<v1>(?:[^'\\]|\\[\s\S]|'(?!''))*)'''"
               r'|"""(?P<v2>(?:[^"\\]|\\[\s\S]|"(?!""))*)"""'
               r'|"(?P<v3>(?:[^"\\]|\\[\s\S])*)"'
               r"|'(?P<v4>(?:[^'\\]|\\[\s\S])*)'"
               r'|`(?P<v5>(?:[^`\\]|\\[\s\S])*)`)'),
    # Inside a double-quoted -d the shell turns \\ into a JSON backslash and \" into a JSON quote, so a JSON escape
    # is \\ followed by \\, \" or a plain char, and a lone backslash with a plain char (\n) is one too. Viktor 49939
    # dq-escquote-before-stamp: the old unit list read \\ then stopped at the \" of an escaped \\\" quote.
    re.compile(r'\\"(?:content|comment)\\"\s*:\s*\\"(?P<v1>(?:[^"\\]|\\\\(?:\\\\|\\"|[^\\])|\\[^"\\])*)\\"'),
)
# The stamp at the very end of the value, once the trailing whitespace, dots, markdown marks and a stray backslash
# are stripped (_value_end): "(YYYY-MM-DD HH:MM)", seconds and a fraction optional, a T allowed, and a time zone
# (Viktor 49927 T2: Z, +-HH:MM, or a name; a named zone outside TAIL_TZ_MIN is not judged). Groups 1-5: date, time.
# Viktor 49939 item 3: two blanks or a comma between the date and the time, a fraction of up to 9 digits, a bare
# +HH offset, a lower-case zone name, UTC+1 / GMT-5, and a nested closing paren ("(review ok (stamp))").
COMMENT_TAIL_RX = re.compile(
    r'\((\d{4})-(\d{2})-(\d{2})(?:T|,?[ \t]+)([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d(?:[.,]\d{1,9})?)?'
    r'(?:[ \t]?(?P<tz>Z|[+-](?:[01]\d|2[0-3])(?::?[0-5]\d)?|(?P<tzn>[A-Za-z]{2,5})(?P<tzo>[+-]\d{1,2})?))?\)'
    r'(?:[ \t]*\))?\Z')
# A value built by concatenation, 'x' + ' (stamp)' (Viktor 49927 py-concat): the last literal of the chain counts,
# also across a name ('x ' + n + ' (stamp)', Viktor 49939 concat-var-mid) and for adjacent literals ('x' ' (stamp)',
# py-implicit-concat).
# Round 2 (Viktor 49949): a call in the chain (+ str(n) +, fo-concat-call-mid), and an adjacent literal only when a
# closing , } ) ] + or a further literal follows it (ob-adjacent-shell-arg: echo comment="1 ok" "more" glued the next
# shell word; a chain's last literal still needs the closing mark, time-adjacent-many).
_CONCAT_LIT = r'(?:"(?P<{0}>(?:[^"\\]|\\[\s\S])*)"|\'(?P<{1}>(?:[^\'\\]|\\[\s\S])*)\')'
CONCAT_RX = re.compile(r'\s*\+\s*(?:[A-Za-z_][\w.]*(?:\([^()\'"\n]*\))?\s*\+\s*)*' + _CONCAT_LIT.format('d', 's')
                       + r'|[ \t]+' + _CONCAT_LIT.format('d2', 's2') + r'(?=\s*[,})\]+\'"])')
# A subscript key counts only when its name is what the command posts (Viktor 49949 ob-other-dict-subscript).
# Collected once per command (Viktor 49952 R2: a re.search per subscript match re-read the whole command, 300 KB of
# subscripts took 62 s against a 10 s hook timeout); the subscript branch then only checks membership.
# data=json.dumps(x): the data= branch must not take "json" as the name (it would consume the json.dumps(x) match).
POSTED_RX = re.compile(r'(?:json\.dumps\(\s*|(?<![\w.])(?:json|data)\s*=\s*(?!json\.dumps\())([A-Za-z_]\w*)(?!\w)')
# The subscripted name, read back from at most 64 chars before the [ (the key branch is anchored on the [, so the
# scan does not start a name match at every word).
SUB_NAME_RX = re.compile(r'(?<![\w.])([A-Za-z_]\w*)\Z')
# Trailing chars after the stamp that do not end the comment's own text: whitespace, dots, markdown marks, a no-break
# space, a stray backslash, an escaped quote, and (Viktor 49939 item 3) ! ? ; ] , a variation selector, and any
# format char (zero-width space), emoji or symbol (TAIL_STRIP_CATS).
TAIL_STRIP_CATS = frozenset(('Cf', 'So', 'Sk'))
TAIL_STRIP = frozenset(' \t\r\n.*`_~ \\"\'!?;]\ufe0f')
TAIL_TZ_MIN = {'Z': 0, 'UTC': 0, 'GMT': 0, 'CET': 60, 'CEST': 120}
# Rule 5, the send path (retro R1, card 028205dd): an inter-agent message, a close result or a daily-log entry.
# Not a memory: a memory is not a report to anyone, and its times are mostly plans.
SEND_PATH_RX = re.compile(r'(?<![\w-])(?:[a-z]+-msg|msg-close)\.sh(?![\w-])|/api/(?:messages|daily-log)')
# A guessed measured time runs a few minutes ahead; a time further ahead is a plan (measured, see SCOPE rule 5).
SEND_WINDOW_MIN = 15
# A line that is about a plan or an estimate, not a measurement.
SEND_PLAN_LINE_RX = re.compile(
    r'(?<!\w)(?:nullázás\w*|reset\w*|ütemez\w*|holnap\w*|tervez\w*|kivetít\w*|várható\w*|becsl\w*|tipp\w*)(?!\w)', re.I)
# Right before the time: an estimate ("~16:50", "kb. 16:50") or a correction ("nem 14:00").
SEND_ESTIMATE_BEFORE_RX = re.compile(r'(?:~|(?<!\w)kb\.?[ \t]*|(?<!\w)körülbelül[ \t]+|(?<!\w)nem[ \t]+)$', re.I)
# Right after the time: a UTC stamp ("16:13:16Z"), not the install's clock.
UTC_AFTER_RX = re.compile(r'(?::[0-5]\d)?Z(?!\w)')
# not a <b> / <notes.md> tag or autolink in a text: a name that ends right at > is not a redirect
STDIN_FILE_RX = re.compile(r'(?<![<\d])<[ \t]*[\'"]?(?![^\s\'";|&<>()]*>)([^\s\'";|&<>()]+)')
DATA_FILE_RX = re.compile(r'(?<![\w-])(?:--data-binary|--data|--json|-d)(?:\s+|=)?[\'"]?@([^\s\'";|&<>()]+)')
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
    for m in _heads(HEADING_RX, HEADING_PY_RX, text):
        if len(out) >= MAX_TIMES_PER_LINE:
            break
        if _other_day(m.group(3), now):
            continue
        if int(m.group(1)) * 60 + int(m.group(2)) > limit:
            out.append((text.count('\n', 0, m.start()) + 1, f'{m.group(1)}:{m.group(2)}', 'heading'))
    return out


def send_findings(text, now):
    """[(line_no, token, 'send')] for a measured time 1-SEND_WINDOW_MIN minutes after the current minute on the send
    path (rule 5): rule 2's marker line and exceptions, plus a plan line, a suffix, an estimate and a UTC stamp."""
    out = []
    lines = text.splitlines()
    cur = now.hour * 60 + now.minute
    for n, tok, kind in findings(text, now):
        if kind != 'future' or len(out) >= MAX_TIMES_PER_LINE:
            continue
        line = lines[n - 1]
        if SEND_PLAN_LINE_RX.search(line):
            continue
        for i, m in enumerate(TIME_RX.finditer(line)):
            if i >= MAX_TIMES_PER_LINE:
                break
            if m.group(0) != tok:
                continue
            if (COMMENT_HEAD_NOT_STAMP_RX.match(line, m.end()) or UTC_AFTER_RX.match(line, m.end())
                    or SEND_ESTIMATE_BEFORE_RX.search(line[max(0, m.start() - DEADLINE_WINDOW):m.start()])):
                continue
            if 0 < int(m.group(1)) * 60 + int(m.group(2)) - cur <= SEND_WINDOW_MIN:
                out.append((n, tok, 'send'))
                break
    return out


def typed_heading_findings(text, now):
    """[(line_no, token, 'heading-typed')] for a daily-log heading with a typed time of today (rule 6): the heading
    time is "{{NOW}}", which the dashboard fills in at the write. A heading that names another day passes."""
    out = []
    for m in _heads(HEADING_RX, HEADING_PY_RX, text):
        if len(out) >= MAX_TIMES_PER_LINE:
            break
        if _other_day(m.group(3), now):
            continue
        out.append((text.count('\n', 0, m.start()) + 1, f'{m.group(1)}:{m.group(2)}', 'heading-typed'))
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
    for m in _heads(COMMENT_HEAD_RX, COMMENT_HEAD_PY_RX, text):
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


def _value_end(v):
    """The index after the last char of the value that is not trailing whitespace, a dot, a markdown mark or a
    stray backslash (one pass from the end: linear, no copy)."""
    i = len(v)
    while i and (v[i - 1] in TAIL_STRIP or unicodedata.category(v[i - 1]) in TAIL_STRIP_CATS):
        i -= 1
    return i


def _tail_local(m):
    """The stamp as a local naive datetime, or None (a bad date, an unknown named zone)."""
    try:
        stamp = datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
    except ValueError:
        return None
    tz = m.group('tz')
    if not tz:
        return stamp
    if m.group('tzn'):  # a name, upper-cased (utc), optionally with an hour offset (UTC+1, GMT-5)
        name, hours = m.group('tzn').upper(), m.group('tzo')
        if name not in TAIL_TZ_MIN or (hours and name not in ('UTC', 'GMT')):
            return None
        off = TAIL_TZ_MIN[name] + (int(hours) * 60 if hours else 0)
    elif tz in TAIL_TZ_MIN:
        off = TAIL_TZ_MIN[tz]
    else:  # +HH, +HHMM, +HH:MM
        digits = tz[1:].replace(':', '')
        off = (int(digits[:2]) * 60 + int(digits[2:] or 0)) * (1 if tz[0] == '+' else -1)
    return datetime.datetime.fromtimestamp(calendar.timegm(stamp.timetuple()) - off * 60)


def comment_tail_findings(text, now):
    """[(line_no, token, 'card-tail')] for a card comment's closing "(today HH:MM)" stamp later than the current
    minute (rule 7), read from the content / comment value only. Another day's date passes, past or future, and so
    does a deadline ("határidő (... 18:00)", as rule 2)."""
    out = []
    limit = now.hour * 60 + now.minute + SLACK_MIN
    posted = None  # the posted names, read once on the first subscript
    for rx in COMMENT_VALUE_RXS:
        for mv in rx.finditer(text):
            if len(out) >= MAX_TIMES_PER_LINE:
                return out
            if mv.groupdict().get('sub'):
                mn = SUB_NAME_RX.search(text, max(0, mv.start() - 64), mv.start())
                if posted is None:
                    posted = {m.group(1) for m in POSTED_RX.finditer(text)}
                if not mn or mn.group(1) not in posted:
                    continue
            vg = next(g for g in VALUE_GROUPS if mv.groupdict().get(g) is not None)
            v, vstart, pos = mv.group(vg), mv.start(vg), mv.end()
            while True:  # 'x' + ' (stamp)': the last literal of a concatenation
                mc = CONCAT_RX.match(text, pos)
                if not mc:
                    break
                grp = next(g for g in ('d', 's', 'd2', 's2') if mc.group(g) is not None)
                v, vstart, pos = mc.group(grp), mc.start(grp), mc.end()
            end = _value_end(v)
            tail = v[max(0, end - 120):end]
            m = COMMENT_TAIL_RX.search(tail)
            if not m or DEADLINE_TAIL_RX.search(tail[:m.start()]):
                continue
            local = _tail_local(m)
            # Today's stamp: today's date written, or a zoned stamp that lands on today (Viktor 49939
            # tz-today-to-tomorrow: "(today 23:30 -05:00)" is tomorrow morning here, still ahead of the clock).
            written_today = (int(m.group(1)), int(m.group(2)), int(m.group(3))) == (now.year, now.month, now.day)
            if local is None or local.date() < now.date() or (local.date() != now.date() and not written_today):
                continue
            if local.date() > now.date() or local.hour * 60 + local.minute > limit:
                out.append((text.count('\n', 0, vstart + end) + 1, f'{local:%H:%M}', 'card-tail'))
    return out


JSON_U_RX = re.compile(r'\\u([0-9a-fA-F]{4})')


def _json_text(text):
    """A JSON payload as the reader will see it (retro R1): a literal \\n, \\t or \\r (Viktor 49927 T3) is a line
    break, a tab or a carriage return, and a \\uXXXX escape is its character -- json.dumps writes "M\\u00e9rve", and
    "x\\nlefutott" hid the marker behind the letter n. A \\" stays as it is: the heading and comment-stamp patterns
    read the JSON string's end from it."""
    text = text.replace('\\n', '\n').replace('\\t', '\t').replace('\\r', '\r')
    return JSON_U_RX.sub(lambda m: chr(int(m.group(1), 16)), text)


PUT_RX = re.compile(r'(?:(?<![\w-])-[A-Za-z]*X|--request)(?:[ \t]|\\\r?\n)*[\'"]?PUT\b'
                    r'|(?<![\w-])method[\'"]?[ \t]*[:=][ \t]*[\'"](?i:put)[\'"]'
                    r'|(?<![\w.])request[s]\.put\(|\.request\([ \t]*[\'"]PUT[\'"]')
# A real curl command segment (not a PUT quoted inside a message text): it starts at a line start or after
# ; & | ( or a backtick, and runs to the next unescaped newline / ; & | (a backslash-newline continues it).
# The env value (VAR=... before curl) is read unit by unit, first fit wins: $(( )) and $( ) with no ( ) or backtick
# inside (T=$(date) curl ...), $'...' and "..." with their \x escapes, '...', all three also over lines, a \x escape
# (also a backslash-newline: bash joins the lines; Viktor 49870 old gaps S-sq-nl, S-esc-nl), then any other char
# but whitespace, ; & | ( backtick or a bare backslash (a quote that is no unit is a plain char, as on 4314d041;
# the bare-backslash exclusion only matters at the very end of a command, the escape unit comes first).
# Viktor 49858 V1: A='x(y)', A="(x)", A=a\(b, A=$'x(y)', N=$((1+2)) before curl are segments.
# The value is read atomically (lookahead + backreference, Python 3.9 has no possessive quantifier): no backtracking
# into it, so no unit split can blow up (round-5 mutants 22, 25, 26). The VAR=value chain always matches and the
# curl is an optional group (a match counts only with it): a chain with no curl after it is consumed, and the search
# does not restart at a ( ` ; inside its quotes or escapes (Viktor 49870 L14: a failing chain was re-read from every
# inner start to the line end, 120 KB 24.6 s). No unit holds the word curl, so a curl inside a quote or a $( ) is
# not swallowed: the quote is read as a plain char, the value stops at the inner start, and that start is searched.
# Nor does a unit hold a segment start followed by VAR= (Viktor 49884 L15: a quote the shell does not read as one,
# echo "(x='a" ; T='b c' curl ..., opened at x= and closed inside the real T='b c', swallowing the real ;); and an
# escape inside "..." or $'...' does not take a newline that VAR= follows (Viktor 49887: a line continuation or a
# comment ending in a backslash before the real line). A backslash-newline between the start and VAR= needs no own
# branch: the newline is itself a start, so the last one before VAR= stops the unit (per char in '...', by the last
# escape's lookahead in "..." and $'...'). A repeated backslash-newline in these lookaheads re-read the rest of a
# backslash-newline run at every step (Viktor 49898 L16: 60 KB 18.7 s), so they stay [ \t]* (linear).
# A bare escape outside quotes does not take a newline that VAR= or a curl (also with a path) follows (Viktor 49901
# L17: a comment ending in a backslash, "# step 1;b=c\", then a real PUT with no env prefix: the shell runs the PUT,
# the comment's backslash continues nothing, but the escape took the newline and the value ran on through curl).
# In a real continuation (b=c\ newline curl) the shell joins the word; reading a segment there only overblocks.
_START_VAR = r'[;&|(`\n][ \t]*\w+='
_UNIT_GUARD = r'(?!curl\b|' + _START_VAR + r')'
_QUOTED_ESC = r'\\(?:[^\n]|\n(?![ \t]*\w+=))'
_BARE_ESC = r'\\(?:[^\n]|\n(?![ \t]*(?:\w+=|(?:[^\s;&|(`]*/)?curl\b)))'
_ENV_UNIT = (r'\$\(\((?:' + _UNIT_GUARD + r'[^;&|()`\n])*\)\)|\$\((?:' + _UNIT_GUARD + r'[^;&|()`\n])*\)'
             r'|\$\'(?:' + _UNIT_GUARD + r'(?:[^\'\\]|' + _QUOTED_ESC + r'))*\'|\'(?:' + _UNIT_GUARD + r'[^\'])*\''
             r'|"(?:' + _UNIT_GUARD + r'(?:[^"\\]|' + _QUOTED_ESC + r'))*"'
             r'|' + _BARE_ESC + r'|[^\s;&|(`\\]')


def _env_assign(name):
    return r'\w+=(?=(?P<' + name + r'>(?:' + _ENV_UNIT + r')*))(?P=' + name + r')'


CURL_SEG_RX = re.compile(r'(?:^|[;&|(`])[ \t]*(?:' + _env_assign('v1') + r'[ \t]+)*(?:' + _env_assign('v2') + r')?'
                         r'(?P<curl>(?:[^\s;&|(`]*/)?curl\b(?:[^\n;&|\\]|\\[\s\S])*)?', re.M)
# The comment key as JSON writes it, escaped inside a double-quoted -d, as a Python dict key, or bare (jq).
COMMENT_KEY_RX = re.compile(r'(?:(?<![\w-])\\?[\'"]comment\\?[\'"]\]?|(?:(?<=[{,(.])|(?<=[{,(][ \t])|(?m:^)[ \t]+)comment)'
                            r'[ \t]*\|?[:=]')


# Viktor 49901 (indep7, 13 smuggle labels) and 49912 K2: views next to CURL_SEG_RX, which stays as it was. A card
# PUT counts when ANY view finds it, so a view can only add a card judgment (an overblock), never hide one the main's
# search found. CURL_SEG2_RX: shell words before curl (then, do, else, if, while, until, time, command, builtin, exec,
# nohup, env, nice, timeout [-s SIG] N, sudo -u x, xargs -I{}, !, {, a redirect such as 2>/dev/null), before and after
# the VAR= chain, also after a ) (a case arm); a sudo / xargs option argument is never the curl word itself (the
# curl group is optional, so a consumed curl would not be given back: xargs -I{} curl); the path before the curl
# word stops at a ), the new start char (else every ) re-read the rest of a ) run: 120 KB of ) took 27 s); the curl word
# also as "curl", 'curl' or \curl; the body reads quotes as units ('...', "...", $'...', also over lines), so a ; in
# a quoted header or a multi-line -d does not end it. Each quote unit stops at its first closing quote (linear).
_PREFIX = (r'(?:(?:then|do|else|elif|if|while|until|time(?:[ \t]+-p)?|command|builtin|exec|nohup|!|\{'
           r'|env(?:[ \t]+-[\w-]+)*|nice(?:[ \t]+-n)?(?:[ \t]+-?\d+)?'
           r'|timeout(?:[ \t]+-[^\s;&|(`]+(?:[ \t]+(?:[A-Z][A-Z0-9]*|\d+(?:\.\d+)?[smhd]?))?)*[ \t]+\d+(?:\.\d+)?[smhd]?'
           r'|(?:sudo|xargs)(?:[ \t]+-[^\s;&|(`]+(?:[ \t]+(?!-|[\\"\']?(?:[^\s;&|(`)]*/)?curl\b)[^\s;&|(`]+)?)*'
           r'|\d*(?:>>?|<|>&|&>>?)[ \t]*[^\s;&|(`<>]+)[ \t]+)*')
CURL_SEG2_RX = re.compile(r'(?:^|[;&|(`)])[ \t]*' + _PREFIX + r'(?:' + _env_assign('v3') + r'[ \t]+)*' + _PREFIX
                          + r'(?:' + _env_assign('v4') + r')?'
                          r'(?P<curl>(?:[^\s;&|(`)]*/)?(?:\\|["\'])?curl\b'
                          r'(?:[^\n;&|\\\'"$]|\\[\s\S]|\$\'(?:[^\'\\]|\\[\s\S])*\'|\'[^\']*\''
                          r'|"(?:[^"\\]|\\[\s\S])*"|[$\'"])*)?', re.M)
# The curl's own URL in a view: the first /api/ once the header and data arguments are taken out (an /api/messages
# in a header, an env value or a -d before the kanban URL is not the URL; a memory body quoting a kanban PUT after
# the memory URL still is not a kanban segment).
CURL_ARG_RX = re.compile(r'(?<![\w-])(?:-[HdF]|--(?:header|data(?:-raw|-binary|-urlencode|-ascii)?|json|form(?:-string)?))'
                         r'(?:[ \t]+|=|(?=[\'"$]))(?:\$\'(?:[^\'\\]|\\[\s\S])*\'|\'[^\']*\'|"(?:[^"\\]|\\[\s\S])*"'
                         r'|[^\s;&|\'"])+')
# A line continuation joins words in bash (cu\<newline>rl, T\<newline>=v); the views also read the joined text.
BS_NL_RX = re.compile(r'\\\r?\n')
# Viktor 50003 R1: the ) start is for a case arm and a $( ) env value, but a numbered list in a message ("Lépések:
# 1) curl -s -X PUT .../api/kanban/... 2) szólj.") read as a card PUT, which main lets through. A number of up to three
# digits at a line or word start, then ), is a list mark, not a start, until the first `case` word that has an `in` word
# somewhere after it (a case arm such as `1) curl ...` stays a start after it). Not the `case WORD in` form itself: bash
# also takes a newline before `in` and a WORD with spaces inside a $( ) or quotes (case $(echo 1) in 1) curl ...), and
# the narrow form let those arms through (Kernel, round 3). All searches are linear (a bounded \d run per start; one
# pass for the first case word, one for the last in word).
LIST_MARK_RX = re.compile(r'(?:^|(?<=\s))\d{1,3}\)', re.M)
CASE_WORD_RX = re.compile(r'\bcase\b')
IN_WORD_RX = re.compile(r'\bin\b')
# The same R1, its second shape: a message heredoc line "  then curl -s -X PUT ..." read as a card PUT (main lets it
# through). then / elif / else at a start is a prefix word only after an `if` earlier in the command, and do only after
# a for / while / until / select (a real multi-line `if x<newline>then curl ...` has its if); else its first letter
# is changed (same length), so the line reads as on main.
CLAUSE_KW_RX = re.compile(r'(?:^|(?<=[;&|(`)]))[ \t]*(then|elif|else|do)\b', re.M)
IF_RX = re.compile(r'\bif\b')
LOOP_RX = re.compile(r'\b(?:for|while|until|select)\b')


def _unmark_lists(view):
    """`view` (same length) with the ) of each list mark before the first `case` word (with an `in` word after it) blanked, and a then / elif /
    else / do with no opener before it made no prefix word. Viktor 50062 R2: a ) that closes an open ( or $( (an env
    value $(echo a | tr a 1), a curl glued to $(: 1)) is no list mark: the parenthesis depth before it, counted once
    over the view (linear), must be 0."""
    c = CASE_WORD_RX.search(view)
    last_in = None
    for last_in in IN_WORD_RX.finditer(view):
        pass
    lim = c.start() if c and last_in and c.start() < last_in.start() else len(view)
    state = {'pos': 0, 'depth': 0}

    def mark(m):
        close = m.end() - 1
        part = view[state['pos']:close]
        state['depth'] += part.count('(') - part.count(')')
        state['pos'] = close + 1
        if m.start() < lim and state['depth'] <= 0:
            return m.group(0)[:-1] + ' '
        state['depth'] -= 1  # the kept ) closes a parenthesis
        return m.group(0)
    view = LIST_MARK_RX.sub(mark, view)
    f_if, f_loop = IF_RX.search(view), LOOP_RX.search(view)
    first_if = f_if.start() if f_if else len(view)
    first_loop = f_loop.start() if f_loop else len(view)

    def kw(m):
        k, at = m.group(1), m.start(1)
        if at > (first_loop if k == 'do' else first_if):
            return m.group(0)
        return m.group(0)[:at - m.start()] + 'x' + k[1:]
    return CLAUSE_KW_RX.sub(kw, view)


def _kanban_put_segment(cmd):
    """Is there a real curl segment with a PUT whose own URL is a kanban one? The main's search first, then the views
    (each pass linear)."""
    if any(m.group('curl') and _seg_url_is_kanban(m.group(0)) and PUT_RX.search(m.group(0))
           for m in CURL_SEG_RX.finditer(cmd)):
        return True
    joined = BS_NL_RX.sub('', cmd)
    for view in (cmd, joined) if joined != cmd else (cmd,):
        for m in CURL_SEG2_RX.finditer(_unmark_lists(view)):
            if m.group('curl') and PUT_RX.search(m.group(0)):
                own = CURL_ARG_RX.sub(' ', m.group('curl'))
                i = own.find('/api/')
                if i >= 0 and own.startswith('/api/kanban/', i):
                    return True
    return False


def _seg_url_is_kanban(seg):
    # the curl's own URL is the first /api/ in its segment; a kanban PUT quoted in a memory body comes later
    i = seg.find('/api/')
    return i >= 0 and seg.startswith('/api/kanban/', i)


def _data_paths(cmd, cwd):
    """The absolute paths of the `@file` data files a curl command reads (a relative one against an absolute cwd)."""
    out = []
    stdin = STDIN_FILE_RX.findall(cmd) if '@-' in cmd else []  # curl reads stdin only for @-
    for ref in list(dict.fromkeys(DATA_FILE_RX.findall(cmd) + stdin))[:MAX_SHELL_TARGETS]:
        path = os.path.expanduser(ref)
        if not os.path.isabs(path):
            if not (isinstance(cwd, str) and os.path.isabs(cwd)):
                continue
            path = os.path.join(cwd, path)
        out.append(path)
    return out


def judged_texts(tool_name, ti, cwd):
    """[(label, text, known_lines, placeholder_only, daily_log, card, send)] to judge; [] when out of scope."""
    if tool_name in ('Write', 'Edit', 'MultiEdit'):
        path = ti.get('file_path')
        if not _is_shared_md(path):
            return []
        if tool_name == 'Write':
            content = ti.get('content')
            return [('', content, _existing_lines(path), False, False, False, False)] if isinstance(content, str) else []
        edits = [ti] if tool_name == 'Edit' else ti.get('edits')
        out = []
        for e in edits if isinstance(edits, list) else []:
            if isinstance(e, dict) and isinstance(e.get('new_string'), str):
                old = e.get('old_string')
                out.append(('', e['new_string'], frozenset(old.splitlines()) if isinstance(old, str) else frozenset(),
                            False, False, False, False))
        return out
    if tool_name == 'Bash':
        cmd = ti.get('command')
        if not isinstance(cmd, str):
            return []
        # A card comment, also the "comment" field of a /move (Dave 49788, card 00c714ea: a placeholder time in a
        # move comment went out with HTTP 200, the same text on /comments was blocked; the kanban-waiting gate makes
        # everyone write the VÁR line into the move). PUT /api/kanban/<id> stores a "comment" field the same way
        # (src/web/routes/kanban.ts storeMoveComment); such a PUT counts only when it carries "comment", in the
        # command or a data file it reads, so a title or description edit keeps its plan times.
        card = '/api/kanban/' in cmd and ('/comments' in cmd or '/move' in cmd)
        if not card and '/api/kanban/' in cmd and PUT_RX.search(cmd) and (
                not API_WRITE_RX.search(cmd) or _kanban_put_segment(cmd)):
            card = bool(COMMENT_KEY_RX.search(cmd)) or any(
                'comment' in b and COMMENT_KEY_RX.search(b) for b in (_read_small(p) or '' for p in _data_paths(cmd, cwd)))
        if not card and not API_WRITE_RX.search(cmd):
            targets = _shell_shared_md_targets(cmd, cwd)
            if not targets:
                return []
            return [('command ', cmd, frozenset().union(*(_existing_lines(t) for t in targets)), False, False, False, False)]
        refs = list(dict.fromkeys(DATA_FILE_RX.findall(cmd)))[:MAX_SHELL_TARGETS]
        # A message or card body can come from a file on stdin: agent-msg.sh kernel klodel - < body.txt
        if not card or '@-' in cmd:  # a card body from stdin only when curl reads it (@-)
            refs += list(dict.fromkeys(STDIN_FILE_RX.findall(cmd)))[:MAX_SHELL_TARGETS]
        po = not card  # message / memory / daily log: placeholder rule only
        hd = not card and DAILY_LOG in cmd  # rules 3 and 6: the daily-log heading
        sp = not card and bool(SEND_PATH_RX.search(cmd))  # rule 5: message, close result, daily log
        out = [('command ', _json_text(cmd), frozenset(), po, hd, card, sp)]
        for ref in refs:
            path = os.path.expanduser(ref)
            if not os.path.isabs(path):
                if not (isinstance(cwd, str) and os.path.isabs(cwd)):
                    continue
                path = os.path.join(cwd, path)
            body = _read_small(path)
            if body is not None:
                out.append(('@file ', _json_text(body), frozenset(), po, hd, card, sp))
        return out
    if tool_name in TELEGRAM_TEXT_TOOLS:
        # Klodel 48360: the chat text, placeholder rule only, as written (a chat message is not a JSON payload).
        text = ti.get('text')
        return [('text ', text, frozenset(), True, False, False, False)] if isinstance(text, str) else []
    return []


def verdict(payload):
    ti = payload.get('tool_input')
    if not isinstance(ti, dict):
        return None
    now = _now()
    hits = []
    for label, text, known, po, hd, card, sp in judged_texts(payload.get('tool_name'), ti, payload.get('cwd')):
        found = findings(text, now, known, po)
        hits += [(label, n, tok, kind) for n, tok, kind in found]
        if sp:
            hits += [(label, n, tok, kind) for n, tok, kind in send_findings(text, now)]
        if hd:
            future_heads = heading_findings(text, now)
            hits += [(label, n, tok, kind) for n, tok, kind in future_heads]
            seen = {(n, tok) for n, tok, _ in future_heads}
            hits += [(label, n, tok, kind) for n, tok, kind in typed_heading_findings(text, now) if (n, tok) not in seen]
        if card:
            seen = {(n, tok) for n, tok, _ in found}
            head = comment_head_findings(text, now)
            hits += [(label, n, tok, kind) for n, tok, kind in head if (n, tok) not in seen]
            seen |= {(n, tok) for n, tok, _ in head}
            hits += [(label, n, tok, kind) for n, tok, kind in comment_tail_findings(text, now) if (n, tok) not in seen]
    if not hits:
        return None
    parts = []
    for label, n, tok, kind in hits[:3]:
        what = ('helykitöltő idő / placeholder time' if kind == 'placeholder'
                else f'jövőbeli naplófejléc / future daily-log heading (now {now:%H:%M})' if kind == 'heading'
                else f'jövőbeli komment-időbélyeg / future comment stamp (now {now:%H:%M})' if kind == 'card-head'
                else f'jövőbeli záró komment-bélyeg / future closing comment stamp (now {now:%H:%M})'
                if kind == 'card-tail'
                else 'kézzel írt naplófejléc-idő / typed daily-log heading time' if kind == 'heading-typed'
                else f'jövőbeli mért idő / future measured time (now {now:%H:%M})')
        parts.append(f'{label}line {n}: "{tok}" = {what}')
    if payload.get('tool_name') in TELEGRAM_TEXT_TOOLS:
        # Klodel 48360: no {{NOW}} advice here, nothing replaces it in a Telegram message.
        return ('IDO-KAPU / TIME-CLAIM-GATE: ' + '; '.join(parts) + '. '
                'Futtasd a `date`-et, és a MÉRT időt írd be, vagy hagyd ki az időt; Telegramban a {{NOW}} nem '
                'cserélődik. Run `date` and write the measured time, or leave the time out; Telegram does not '
                'replace {{NOW}}.')
    return ('IDO-KAPU / TIME-CLAIM-GATE: ' + '; '.join(parts) + '. '
            'Futtasd a `date`-et, és a MÉRT időt írd be (nem becsültet, nem 19:3x-et). '
            'Run `date` and write the measured time. Üzenetben, lezárás-resultban és napi naplóban írd: {{NOW}} '
            '(a dashboard a beírás percére cseréli; a naplófejléc: "## {{NOW}} -- Téma"). '
            'In a message, a close result or the daily log write {{NOW}}: the dashboard fills in the minute of the write. '
            'Ha az idő másik napé, a sorba írd a dátumot (MM-DD). '
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
