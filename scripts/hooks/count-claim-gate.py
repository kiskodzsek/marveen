#!/usr/bin/env python3
"""count-claim-gate.py -- PreToolUse (Bash) gate, opt-in per agent: a count- or id-shaped claim in an outgoing
inter-agent message or card comment needs a "MÉRVE: <command or file:line>" line.

WHY (Klodel 39869, hibanapló 2026-11-13): Kernel wrote three concrete values before measuring them, each in a
call that ran in parallel with the measurement: a sha256 (11-12, 39581), a message id ("39836 körül" on card
b71236d8, the real one was 39834) and a count ("15 Klodel-komment" in 39861, measured: 20). The hash already has
its own gate (agents/kernel/tools/kernel-msg.sh rc=5); ids and counts had none, and copy discipline alone is not
a machine catch (alapszabály, second occurrence).

SCOPE (everything else is allowed at once, exit 0, no output):
  - Bash only, and only for an agent in AGENTS (agent id from the payload: ledger_lib.agent_id_from_payload,
    transcript_path first). Opt-in, because counts and ids are in almost every report of the fleet; another agent
    joins by adding its id here, in its own PR.
  - Only a command that sends an inter-agent message or closes one with a result (agent-msg.sh, a
    <name>-msg.sh / msg-close.sh wrapper, a POST to /api/messages, or a /api/messages/<id> call whose judged text
    carries a "result" key), posts a card comment (/api/kanban/.../comments) or writes the daily log (a write to
    /api/daily-log; retro R1, card 028205dd: the log is a report too).
    READ-ONLY (Klodel 39980, measured 2026-11-13: three blocks of Kernel's own calls in one morning): a GET of
    /api/messages/<id> or /api/messages?..., and a status-only PUT /api/messages/<id> ({"status":"done"}) carry no
    claim to anyone; the id in their URL or in the script that loops over them is an address, not a claim.
    A /api/messages? or /api/messages/ (no id) call counts as a read only when the command shows no write
    (-X POST/PUT/PATCH, -d, --data*, --json, a heredoc or < redirect, method=/data= in inline code): Viktor 40140.
  - Judged, each on its own (a MÉRVE: line covers the text it stands in): the command text (heredoc / -d payload) and a --data-binary @file, --data @file, -d @file or
    `< file` body when it is a regular file of at most 64 KB. A literal "\\n" (a JSON string's line break) counts
    as a line break.

BLOCKS (exit 2, reason on stderr) when the judged text has a CLAIM and no EVIDENCE line:
  CLAIM  - a count with its noun: a number followed, within two words, by db, darab, komment, blokk, sor, üzenet,
           kártya, fájl, eset, találat, hiba, oldal, PR, commit, teszt, mutáns or ügynök ("29 új blokk",
           "20 Klodel-komment", "963 komment");
         - an id: a number of 5 or more digits standing alone (a message id, a TG number; not inside a URL path,
           a word or a dotted/dashed name), "msg" / "id" / "kártya" / "card" followed by 4+ digits, or "kártya" /
           "card" followed by an 8-character hex id.
  EVIDENCE - a line starting with "MÉRVE:" (or "MERVE:", any case, after optional "- ", "* ", "> ") whose text names
           a source: a path (a '/'), a backticked command, or a file:line ("x.py:42").
  ZERO   - a zero count ("0 db", "0 maradék", "nincs maradék", "egy mappa sem maradt") needs more: a MÉRVE line
           that names a counting command (find, wc, grep -c, count() and no `ls` with a glob (retro R1, Kernel's
           input b: zsh stops `ls x-* | wc -l` on a glob with no match and wc prints 0).
A time ("08:51"), a year, a short number ("3 pont"), a version or a hex SHA alone is not a claim here (the time
has its own gate, time-claim-gate.py).

CONTRACT (hook-exit-code-invariant): exit 2 = block, exit 0 = allow, never exit 1. Malformed stdin or an internal
error allows (fail OPEN) and is recorded in store/hook-errors.log through hook_errlog.
Also a CLI for kernel-msg.sh: count-claim-gate.py --check <file>: exit 1 and the reason on stderr when the file
has a claim without evidence, else 0 (no agent check there: the wrapper is the agent's own).
Tests: python3 -I scripts/hooks/count-claim-gate_test.py
"""
import json
import os
import re
import sys

AGENTS = {
    'kernel': 'Klodel 39869: three guessed concrete values on 11-12 and 11-13 (hash, msg id, count)',
}
SEND_RX = re.compile(r'(?<![\w-])(?:[a-z]+-msg|msg-close)\.sh(?![\w-])|/api/messages(?![\w/?-])')
# /api/messages/<id> (or a template like /api/messages/{i}): a send only when a result is written (close + notify).
MSG_ITEM_RX = re.compile(r'/api/messages/+[\d{$<]')
# The key in any quoting, also shell-escaped (-d "{\"result\":...}"): Viktor 40140 LOW (a).
RESULT_KEY_RX = re.compile(r'[\\\'"]+result[\\\'"]+[ \t]*:')
# /api/messages? or /api/messages/ with no id after it: a read (a list) UNLESS the command writes; a write there is
# judged like a bare POST (Viktor 40140 LOW (b): the read is what has to be shown, not the missing write).
MSG_OTHER_RX = re.compile(r'/api/messages(?:\?|/+(?![\d{$<]))')
WRITE_RX = re.compile(r'(?:-X|--request)[ \t]*[\'"]?(?:POST|PUT|PATCH)\b|(?<![\w-])(?:-d|--data[\w-]*|--json)(?![\w-])'
                      r'|<<|(?<![<\d&])<(?![<(&])|method=[\'"]?(?:POST|PUT|PATCH)|\bdata=')
CARD_RX = re.compile(r'/api/kanban/[^\s/\'"]+/comments')
# Retro R1 (card 028205dd): the daily log is a report too; a GET of it is a read.
DAILY_LOG_RX = re.compile(r'/api/daily-log(?![\w/-])')
# Retro R1, Kernel's input (b): a ZERO count ("0 db", "nincs maradék") is the claim a broken measurement makes
# most easily -- in zsh a glob with no match stops the whole `ls x-* | wc -l` and wc prints 0 (hibanapló
# 2026-11-13 18:04: "0 maradék" sent, 48 folders were left). Such a claim needs a MÉRVE line that counts:
# find, wc, grep -c or an SQL count(, and no ls with a glob in it.
ZERO_RX = re.compile(
    r'(?<![\w.,:/#-])0[ \t]+(?:db|darab|maradék\w*|maradvány\w*|találat\w*|mappá?\w*|fájl\w*|sor(?:t|a)?)(?!\w)'
    r'|(?<!\w)nincs(?:[ \t]+több)?[ \t]+(?:maradék|maradvány|találat)\w*'
    r'|(?<!\w)egy(?:[ \t]+\w+)?[ \t]+sem[ \t]+maradt(?!\w)', re.I)
COUNTING_RX = re.compile(r'(?<![\w-])(?:find|wc|grep[ \t]+-[a-zA-Z]*c)(?![\w-])|count\(', re.I)
# ls as a COMMAND (at the start, after a backtick, $(, |, ;, &, (, {, !, a quote, or the words do / then / else /
# time / sudo / command; also /bin/ls and \ls) with a glob in its own arguments; "ls*" inside a find pattern or the
# word ls in prose is not one (Viktor 41354 INFO 3, 41387 INFO 1). Every argument token is non-empty, so a run of
# blanks splits one way only: the regex stays linear (Viktor 41387 LOW, CWE-1333: the empty-token form backtracked
# exponentially, 27 blanks took 11 s, past the 10 s hook timeout).
LS_GLOB_RX = re.compile(
    r'(?:^|[`|;&({!\'"]|\$\(|(?<![\w-])(?:do|then|else|time|sudo|command)(?=[ \t]))'
    r'[ \t]*(?:\\|/(?:[\w.-]+/)*)?ls(?:[ \t]+[^|;&`)\s]+)*[ \t]+[^|;&`)\s]*[*?\[]')
NOUNS = (r'db|darab|komment\w*|blokk\w*|sor(?:a|t|ok\w*|ból|ban|ra)?|üzenet\w*|kártyá?\w*|fájl\w*|eset\w*|'
         r'találat\w*|hibá?\w*|oldal\w*|PR\w*|commit\w*|teszt\w*|mutáns\w*|ügynök\w*')
COUNT_RX = re.compile(r'(?<![\w.:/#-])\d+(?:[.,]\d+)?(?:[ \t]+[\w-]+){0,2}?[ \t-]+(?:' + NOUNS + r')(?![\w])', re.I)
ID_RX = re.compile(
    r'(?<![\w./:#-])\d{5,}(?![\w./-])'
    r'|(?<!\w)(?:msg(?:_id)?|id|kártya|card)[ \t]*[:#=]?[ \t]*\d{4,}(?!\w)'
    r'|(?<!\w)(?:kártya|card)[ \t]*[:#=]?[ \t]*[0-9a-f]{8}(?![0-9a-z])', re.I)
EVIDENCE_RX = re.compile(r'(?mi)^[ \t]*(?:[-*>][ \t]*)?M[ÉE]RVE:[ \t]*(\S[^\n]*)$')
SOURCE_RX = re.compile(r'/|`[^`]+`|[\w.-]+\.\w+:\d+')
STDIN_FILE_RX = re.compile(r'(?<![<\d])<[ \t]*[\'"]?([^\s\'";|&<>()]+)')
DATA_FILE_RX = re.compile(r'(?<![\w-])(?:--data-binary|--data|-d)(?:\s+|=)?[\'"]?@([^\s\'";|&<>()]+)')
MAX_FILE = 64 * 1024
MAX_COMMAND = 256 * 1024
MAX_FILES = 20


def _norm(text):
    return text.replace('\\n', '\n')


def claims(text):
    """The first few claim tokens of `text` (normalised), or []."""
    t = _norm(text)
    out = [m.group(0) for m in COUNT_RX.finditer(t)][:3]
    out += [m.group(0) for m in ID_RX.finditer(t)][:3]
    return out


def has_evidence(text):
    return any(SOURCE_RX.search(m.group(1)) for m in EVIDENCE_RX.finditer(_norm(text)))


def zero_claims(text):
    return [m.group(0) for m in ZERO_RX.finditer(_norm(text))][:3]


def has_counting_evidence(text):
    """A MÉRVE line that names a counting command (find, wc, grep -c, count() and no ls glob."""
    for m in EVIDENCE_RX.finditer(_norm(text)):
        line = m.group(1)
        if COUNTING_RX.search(line) and not LS_GLOB_RX.search(line):
            return True
    return False


def check_text(text):
    """None when the text passes, else the reason."""
    found = claims(text)
    if not found or has_evidence(text):
        zero = zero_claims(text)
        if not zero or has_counting_evidence(text):
            return None
        return ('SZAM-KAPU / COUNT-CLAIM-GATE (retró R1): nulla darabot állítasz ('
                + ', '.join(f'"{c}"' for c in zero) + '), de nincs olyan "MÉRVE:" sor, amely számláló parancsot nevez '
                'meg (find, wc, grep -c, count(), glob nélkül. zsh-ban a nem illeszkedő glob ("ls x-* | wc -l") az egész '
                'parancsot leállítja, és a wc 0-t ír. Mérd így: "MÉRVE: `find <mappa> -maxdepth 1 -name \'<minta>\' | '
                'wc -l`". / A zero count needs a MÉRVE line with a counting command and no ls glob.')
    return ('SZAM-KAPU / COUNT-CLAIM-GATE (Klodel 39869): darabszám vagy azonosító áll a szövegben ('
            + ', '.join(f'"{c}"' for c in found[:4]) + '), de nincs "MÉRVE: <parancs vagy fájl:sor>" sor. '
            'Mérd meg, és írd be a forrást egy külön sorba (pl. "MÉRVE: `sqlite3 ... count(*)`" vagy '
            '"MÉRVE: scripts/x.py:42"). / A count or an id needs a "MÉRVE: <command or file:line>" line.')


def _read_small(path):
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > MAX_FILE:
            return None
        with open(path, encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except OSError:
        return None


def judged_texts(cmd, cwd):
    texts = [cmd[:MAX_COMMAND]]
    refs = (DATA_FILE_RX.findall(cmd) + STDIN_FILE_RX.findall(cmd))[:MAX_FILES]
    for ref in refs:
        path = os.path.expanduser(ref)
        if not os.path.isabs(path):
            if not (isinstance(cwd, str) and os.path.isabs(cwd)):
                continue
            path = os.path.join(cwd, path)
        body = _read_small(path)
        if body is not None:
            texts.append(body)
    return texts


def verdict(payload):
    if not isinstance(payload, dict) or payload.get('tool_name') != 'Bash':
        return None
    ti = payload.get('tool_input')
    cmd = ti.get('command') if isinstance(ti, dict) else None
    if not isinstance(cmd, str):
        return None
    send = bool(SEND_RX.search(cmd) or CARD_RX.search(cmd)
                or ((MSG_OTHER_RX.search(cmd) or DAILY_LOG_RX.search(cmd)) and WRITE_RX.search(cmd)))
    item = not send and bool(MSG_ITEM_RX.search(cmd))
    if not send and not item:
        return None
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import ledger_lib
    if ledger_lib.agent_id_from_payload(payload) not in AGENTS:
        return None
    texts = judged_texts(cmd, payload.get('cwd'))
    if item and not any(RESULT_KEY_RX.search(t) for t in texts):
        return None  # a read or a status-only close of /api/messages/<id>: nothing is claimed to anyone
    for t in texts:
        reason = check_text(t)
        if reason:
            return reason
    return None


def main(argv):
    if len(argv) == 3 and argv[1] == '--check':
        body = _read_small(argv[2])
        reason = check_text(body) if body is not None else 'unreadable or over 64 KB: ' + argv[2]
        if reason:
            sys.stderr.write(reason + '\n')
            return 1
        return 0
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 0
    try:
        reason = verdict(payload)
    except Exception as ex:  # a crashing gate must not become a silent exit 1
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import hook_errlog
            hook_errlog.report('count-claim-gate', 'internal error, allowed', ex)
        except Exception:
            pass
        return 0
    if reason:
        sys.stderr.write(reason + '\n')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
