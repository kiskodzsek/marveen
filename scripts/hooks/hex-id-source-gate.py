#!/usr/bin/env python3
"""PreToolUse (Bash) gate: a hex id (8-64 hex digits: sha, blob, tree, card id) in an outgoing message must have been
SEEN by the sender before: it has to occur in an earlier record of the sender's own transcript that the agent did not
write itself (tool output, inbound message, hook output). Card 7b2f784f, retro 2026-11-20 R1 (Dave (c)).

Why: hibanapló 2026-11-12 15:00 (Kernel, a PR sha256 written before the shasum ran), 2026-11-14 20:09 (Dave, a
migration sha256 from the same parallel tool block, a different value). A 9-day replay (work/hexid-1120/E0-eredmeny.md)
found 15 blocks in 8278 hex-bearing sends; most were mistyped or unmeasured hashes (9b1e92392916 for 9b1e9239291f).

Scope: a SEND command = agent-msg.sh, kernel-msg.sh, msg-close.sh, card-comment.sh, send-stamped.sh, send-and-close.sh,
or a write call (POST/PUT/PATCH, a data, form or upload flag, --json, -T) to /api/messages or /api/kanban. Its text is
the command plus the files it reads as message text (`< f`, `0< f`, `< "f"`, `@f`, `cat f |`, `"$(cat "f")"`, `-T f`,
the positional message file of send-stamped.sh and send-and-close.sh, quoted or not, and a `$(cat f)` in an UNQUOTED
heredoc body), outside header arguments (-H, --header), never `$(< f)` (the dashboard token is read that way), a
secret-looking path or a script file, at most 1 MiB. A relative file is looked up in cwd and in every directory the
command cd's into. A path only mentioned in the message text is not read.
A token counts when it has a digit AND a letter (pure digits are ids and epochs, pure letters are words) and is not a
file name (`c1589627.txt`). It is sourced when it is the prefix or the suffix of a hex run in an earlier non-assistant
record (so the 8-digit prefix of a measured 40/64-digit hash passes), and the agent had NOT written it itself before
that record, unless the record shows a run that is not a part of any run the agent wrote with it (a mistyped
40-digit sha, then the measured one with the same prefix): a tool output that only echoes the agent's own text (a
draft read back, `cat` of an own heredoc, the harness file-change note, this gate's own block message) is not a source.
Not sources either: `api-request-blob` (the agent's own earlier text) and the compact summary (written by the model).

Known limits (Viktor, rounds 1-2, probe rows L4 and P4): a file the agent changed with a command that does not hold
the hex (sed -i, cp) comes back in the harness file-change note as if measured; and a LONGER run the agent builds
from its own digits (printf '%s%s' <hex> 00) counts as a measurement. Neither happens by a typo; both need the
agent to route its own value through a tool. Also not caught (Viktor, bekötési kör, independent probe G08 G12-G14):
a payload path held in a variable (`@"$F"`); a file an EARLIER session wrote (a HANDOFF.md read back is a tool
output here); a hex glued to a letter suffix (`5e6f7a8b9dra`, the suffix could be hex) or to `.Word` (read as a file
extension). Not read on purpose: `$(< f)` and secret-looking paths (the gate must never open a secret).

The block message names a token by its first 8 digits only: a file read by mistake must not echo a secret in full.

Fail-open (exit 0) when the transcript is missing or unreadable, the hook input is not understood, or an error the
code did not foresee happens (reason internal-error, never a silent exit 1; a json record too deep to decode is
skipped, which can only block): this gate guards
accuracy, not access, and a broken read must not stop every message of the fleet. Exit 2 + stderr = blocked.
Every fail-open is OBSERVABLE (Viktor 48897 (a)): one content-free line (time, reason) in store/hex-gate-failopen.log,
so a hook-payload field rename that switches the gate off fleet-wide shows up there. The line never carries the
command, a token or a path; the log stops growing at 1 MiB.
"""
import json
import os
import re
import sys

# The script is a send only in command position (segment start, after VAR=x, after a shell keyword such as then/do,
# or the argument of a runner such as bash, env, nohup, timeout, nice), so a 'grep -n <hex> scripts/agent-msg.sh' is
# not one.
SEND_SCRIPT_RX = re.compile(r'(?:^|[;&|\n(`{]|(?<![\w.-])(?:bash|sh|zsh|exec|env|nohup|command|xargs|timeout|time'
                            r'|nice|caffeinate|stdbuf|then|do|else|elif|if|while|until)\s)'
                            r'\s*(?:(?:-[\w-]+|\w+=\S*|\d+[smh]?)\s+)*["\']?(?:[^\s;&|()`\'"]*/)?'
                            r'(agent-msg|kernel-msg|msg-close|card-comment|send-stamped|send-and-close)\.sh\b')
API_RX = re.compile(r'/api/(messages|kanban)\b')
API_WRITE_RX = re.compile(r'-X\s*(POST|PUT|PATCH)\b|--request\s*(POST|PUT|PATCH)\b|--data(-binary|-raw|-urlencode)?\b'
                          r'|--json\b|--form\b|(?<!\S)-[dFT]|--upload-file\b')
HEX_RX = re.compile(r'(?<![0-9A-Za-z])[0-9a-fA-F]{8,64}(?![0-9A-Za-z])')
FILE_EXT_RX = re.compile(r'\.[A-Za-z][A-Za-z0-9]{0,7}\b')
RUN_RX = re.compile(r'[0-9a-f]{8,}')
HEREDOC_RX = re.compile(r'<<-?\s*([\'"]?)([A-Za-z_][A-Za-z0-9_]*)\1')
HEADER_ARG_RX = re.compile(r'(?<!\S)(?:-H|--header)(?:\s*|=)(?:"[^"]*"|\'[^\']*\'|\S+)')
PAYLOAD_RX = re.compile(r'(?:(?:(?<![<0-9(])|(?<=(?<!\S)0))<(?![<(&])|@)\s*["\']?([^\s;|&<>()\'"`]+)')
WORD = r'(?:"[^"\s$`]+"|\'[^\'\s]+\'|[^\s;|&<>()\'"`]+)'
UPLOAD_RX = re.compile(r'(?<!\S)(?:-T|--upload-file)(?:\s+|=)?' + WORD)
CD_RX = re.compile(r'(?:^|[;&|\n({]|\bthen|\bdo)\s*cd\s+(' + WORD + ')')
SUBST_CAT_RX = re.compile(r'(?:\$\(|`)\s*cat((?:\s+' + WORD + ')+)\s*(?:\)|`)')
CAT_RX = re.compile(r'(?<![\w.-])cat((?:\s+' + WORD + ')+)')
WRAPPER_ARGS_RX = re.compile(r'(?:send-stamped|send-and-close)\.sh((?:\s+' + WORD + ')+)')
SECRET_PATH_RX = re.compile(r'token|secret|credential|passw|\.env\b|\.pem\b|\.key\b|id_rsa|id_ed25519', re.I)
SCRIPT_EXT_RX = re.compile(r'\.(sh|bash|zsh|py|mjs|cjs|js|ts)$')
GATE_TAG = 'HEX-FORRAS-KAPU'
SHELL_HEREDOC_RX = re.compile(r'(?<![\w.-])(?:bash|sh|zsh|dash|ksh)(?:\s+-[\w-]+)*\s*<<'
                              r'|<<.*\|\s*(?:\S*/)?(?:bash|sh|zsh|dash|ksh)\b')
MAX_PAYLOAD = 1 << 20
FAILOPEN_LOG = os.environ.get('HEX_GATE_FAILOPEN_LOG', os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', 'store', 'hex-gate-failopen.log')))
FAILOPEN_MAX = 1 << 20


def note_failopen(reason):
    """One line per fail-open: local time and a fixed reason word, nothing from the input."""
    try:
        if os.path.exists(FAILOPEN_LOG) and os.path.getsize(FAILOPEN_LOG) >= FAILOPEN_MAX:
            return
        import time
        with open(FAILOPEN_LOG, 'a', encoding='utf-8') as f:
            f.write('%s\t%s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), reason))
    except OSError:
        pass


def is_send(cmd):
    # a heredoc body is message text or a script's input, not a command (a gate probe that embeds a send line),
    # unless a shell runs it (bash <<X, sh -s <<X, cat <<X | bash): then the body is the command (Viktor, P2)
    if not SHELL_HEREDOC_RX.search(cmd):
        cmd = strip_heredocs(cmd)
    if SEND_SCRIPT_RX.search(cmd):
        return True
    return bool(API_RX.search(cmd) and API_WRITE_RX.search(cmd))


def tokens(text):
    out = set()
    for m in HEX_RX.finditer(text):
        t = m.group(0).lower()
        if not (re.search(r'[0-9]', t) and re.search(r'[a-f]', t)):
            continue
        if FILE_EXT_RX.match(text, m.end()):
            continue  # a file name such as $S/c15896271.txt
        out.add(t)
    return out


def split_heredocs(cmd):
    """(the command without heredoc bodies and delimiters, the bodies of UNQUOTED heredocs). A word in a body or the
    delimiter itself is not a file the command reads (the body text is still in tokens(cmd)); but the shell expands an
    unquoted body, so a $(cat f) there does read f (Viktor, hx4 G09)."""
    lines, out, pending, bodies = cmd.split('\n'), [], [], []
    for line in lines:
        if pending:
            if line.strip() == pending[0][0] or (line.lstrip('\t') == pending[0][0]):
                pending.pop(0)
            elif not pending[0][1]:
                bodies.append(line)
            continue
        pending.extend((m.group(2), m.group(1)) for m in HEREDOC_RX.finditer(line))
        out.append(HEREDOC_RX.sub(' ', line))
    return '\n'.join(out), '\n'.join(bodies)


def strip_heredocs(cmd):
    return split_heredocs(cmd)[0]


def unquote(w):
    return w[1:-1] if len(w) > 1 and w[0] == w[-1] and w[0] in '"\'' else w


def payload_files(text, body=''):
    """File words the command READS as message text: < f, 0< f, < "f", @f, cat f... (into a pipe or $(cat f)),
    curl -T f, the positional arguments of the two message-file wrappers (quoted or not), and a $(cat f) in an
    unquoted heredoc body. A path only mentioned in the message is not one."""
    out = [m.group(1) for m in PAYLOAD_RX.finditer(text)]
    for m in CAT_RX.finditer(text):
        out += [w for w in m.group(1).split() if not w.startswith('-')]
    for m in WRAPPER_ARGS_RX.finditer(text):
        out += m.group(1).split()
    out += [m.group(0).split(None, 1)[-1].split('=', 1)[-1] for m in UPLOAD_RX.finditer(text)]
    for m in SUBST_CAT_RX.finditer(body):
        out += [w for w in m.group(1).split() if not w.startswith('-')]
    return [unquote(w) for w in out]


def payload_text(cmd, cwd):
    """A relative file is looked up in cwd and in every directory the command cd's into (cd sub && send < f): reading
    one file too many can only block, never let a hex through (Viktor, hx4 G04)."""
    parts, seen = [], set()
    stripped, body = split_heredocs(cmd)
    text = HEADER_ARG_RX.sub(' ', stripped)
    base = cwd or '/'
    bases = [base] + [os.path.join(base, os.path.expanduser(unquote(m.group(1)))) for m in CD_RX.finditer(text)]
    for w in payload_files(text, body):
        if not w or w == '-' or w.startswith('$') or SECRET_PATH_RX.search(w) or SCRIPT_EXT_RX.search(w):
            continue
        p0 = os.path.expanduser(w)
        for p in ([p0] if os.path.isabs(p0) else [os.path.join(b, p0) for b in bases]):
            p = os.path.normpath(p)
            if p in seen:
                continue
            seen.add(p)
            try:
                if os.path.isfile(p) and os.path.getsize(p) <= MAX_PAYLOAD:
                    with open(p, encoding='utf-8', errors='replace') as f:
                        parts.append(f.read())
            except OSError:
                continue
    return '\n'.join(parts)


def own_parts(d):
    """Text the agent itself wrote in an assistant record (text, thinking, every tool input), except the prompt of the
    PARENT's Agent/Task call at the head of a sub-agent's fork transcript (fork-context-ref, then that assistant record,
    then the prompt as user text): for the sub-agent that prompt is a source, not its own writing. That record is the
    only assistant record with isSidechain true and no parentUuid (measured on 400 transcripts: 13 fork heads; the
    259 Agent calls in main transcripts are all isSidechain false, 55 of them without parentUuid). In the PARENT's
    own transcript the Agent prompt stays its own text, or a hex the parent made up would come back as a source
    in the sub-agent's result (Viktor, 2nd round, P1)."""
    msg = d.get('message')
    if not isinstance(msg, dict):
        return ''
    content = msg.get('content')
    if isinstance(content, list) and d.get('isSidechain') is True and not d.get('parentUuid'):
        content = [c for c in content if not (isinstance(c, dict) and c.get('type') == 'tool_use'
                                              and c.get('name') in ('Agent', 'Task'))]
    return json.dumps(content, ensure_ascii=False).lower()


GATE_SPAN_RX = re.compile(re.escape(GATE_TAG.lower()) + r'.*?from there\.', re.S)


def own_runs(text, t):
    """The hex runs in the agent's own text that hold t (empty = not written)."""
    return {r for r in RUN_RX.findall(text) if t in r}


def sourced(transcript, toks):
    """The subset of toks that a non-assistant record showed (None = unreadable). Before the agent wrote a token,
    any prefix/suffix match counts; AFTER it, only a run that is NOT a part of any run the agent wrote with it
    (Kernel, 2nd round of Viktor 48897; Viktor hx4 P09): a tool that reveals digits the agent did not write measured
    it (git rev-parse 22e1da9c -> 40 digits; a mistyped 40-digit sha, then the measured one with the same 8-digit
    prefix), while an echo of the agent's own text (a draft read back, cat of an own heredoc, the file-change note)
    only repeats an own run or a piece of it. This gate's own block message is cut out of a record, not the whole
    record (the shasum output next to it is a real source). A record too deep for json (RecursionError) is skipped:
    a skipped record can only block, never source."""
    try:
        fh = open(transcript, encoding='utf-8', errors='replace')
    except (OSError, TypeError):
        return None
    own, src = {}, set()  # own: token -> runs the agent wrote that hold it
    with fh:
        for line in fh:
            low = line.lower()
            if not any(t in low for t in toks - src):
                continue
            try:
                d = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if not isinstance(d, dict):
                continue
            msg = d.get('message')
            if isinstance(msg, dict) and msg.get('role') == 'assistant':
                text = own_parts(d)
                for t in toks - src:
                    own.setdefault(t, set()).update(own_runs(text, t))
                continue
            if d.get('type') == 'api-request-blob' or d.get('isCompactSummary'):
                continue
            if GATE_TAG.lower() in low:
                low = GATE_SPAN_RX.sub(' ', low)
            runs = RUN_RX.findall(low)
            for t in toks - src:
                if any((r.startswith(t) or r.endswith(t)) and not any(r in o for o in own.get(t, ())) for r in runs):
                    src.add(t)
    return src


def decide(cmd, transcript, cwd):
    """(None, []) = allow; (reason, missing tokens) = block."""
    if not isinstance(cmd, str) or not is_send(cmd):
        return None, []
    toks = tokens(cmd) | tokens(payload_text(cmd, cwd))
    if not toks:
        return None, []
    src = sourced(transcript, toks)
    if src is None:
        note_failopen('transcript-unreadable' if isinstance(transcript, str) and transcript else 'no-transcript-path')
        return None, []
    missing = sorted(toks - src)
    if not missing:
        return None, []
    shown = ', '.join(t if len(t) <= 8 else t[:8] + '...' for t in missing)
    return (GATE_TAG + ' (kártya 7b2f784f, retró 11-20 R1): ez a hex azonosító nem szerepel egyetlen korábbi '
            'tool-kimenetedben vagy bejövő üzenetedben sem, vagy előbb te írtad le, és csak a visszhangja jött vissza: ' +
            shown + '. Mérd meg KÜLÖN hívásban (shasum, git rev-parse, GET), olvasd el, és onnan másold; párhuzamos '
            'blokk eredménye és a saját piszkozatod visszaolvasása nem forrás. / A hex id in this message was never in '
            'your earlier tool output (or only as an echo of your own text); measure it in a separate call and copy it '
            'from there.'), missing


def main():
    """Any error the code did not foresee is a logged fail-open (exit 0), never a silent exit 1 (Viktor, hx4 G15)."""
    try:
        return run()
    except Exception:
        note_failopen('internal-error')
        return 0


def run():
    try:
        data = json.load(sys.stdin)
    except Exception:
        note_failopen('stdin-not-json')
        return 0
    if not isinstance(data, dict):
        note_failopen('input-not-object')
        return 0
    if data.get('tool_name') != 'Bash':
        return 0
    tin = data.get('tool_input')
    cmd = tin.get('command') if isinstance(tin, dict) else None
    if not isinstance(cmd, str):
        note_failopen('no-command')  # a renamed tool_input field must show up, like transcript_path (Viktor, P3)
        return 0
    reason, _ = decide(cmd, data.get('transcript_path'), data.get('cwd'))
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
