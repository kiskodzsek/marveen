#!/usr/bin/env python3
"""PreToolUse gate (telegram reply, main agent only): a known service named in a reply needs a memory search first.

Why: Klodel 40111 (UGYANAZ A HIBA KÉTSZER NEM). Patrik, group TG 5749-5753: the main agent wrote about Higgsfield as
if there were no subscription, while the memory held both facts (Juró 11-11: the Ultra yearly plan was bought;
Viktor 11-12: the MCP gate). Patrik TG 5750 "van előfizetésunk már ... és mcp is kész", TG 5753 "a memóriád is
elveszett?". The memory-lookup-nudge hook only reminds; this time the reminder was stepped over.

What blocks (exit 2, one line ending with the search recipe): a main-agent `reply` whose text names a known service
or tool (SERVICES below, plus one folded name per line in store/ismert-szolgaltatasok.txt: 3-41 characters of a-z, 0-9, space, ".", "_", "-";
other lines are skipped), when in the current round
no Bash command searched the dashboard memory for that name, i.e. no command text that holds "api/memories" AND the
name (URL-decoded, accents folded, case-insensitive; e.g. `curl -s -G ... --data-urlencode "q=Higgsfield" .../api/
memories`). One search per name per round is enough; several names need several searches (one command may hold more).

The round: the transcript (payload transcript_path) from the last prompt that a person or a schedule started -- an
inbound channel message (`<channel `), a scheduled task (`<scheduled-task `), or a bare terminal prompt. Machine
prompts ([Inbox] nudges, task notifications, skill bodies, system reminders) do not start a round. Only the transcript
tail (TAIL_BYTES) is read; when no round start is in it, the whole tail is the round (the lenient direction).

Not gated: sub-agents (ledger_lib identity, LEDGERCWD828), edit_message (the live status card is its own surface),
a malformed payload, and an unreadable transcript (nothing to measure: allowed). Known limit: a search run from a
script file or by a sub-agent is not visible in the command text; run it as a Bash command in the main session.
Wiring: .claude/settings.json PreToolUse, matcher "mcp__plugin_telegram_telegram__reply".
Tests: service-memory-reply-gate_test.py next to this file.
"""
import json
import os
import re
import shlex
import stat
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.environ.get('CLAUDE_PROJECT_DIR', '/Users/klodel/marveen')
EXTRA_FILE = os.path.join(ROOT, 'store', 'ismert-szolgaltatasok.txt')
TAIL_BYTES = 8 * 1024 * 1024
EXTRA_NAME = re.compile(r'^[a-z0-9][a-z0-9 ._-]{2,40}$')  # Viktor 40315 LOW: no quotes, no 1-2 letter names
ZERO_WIDTH = dict.fromkeys(map(ord, '​‌‍⁠﻿­'))

# (key searched for in the memory command, pattern on the folded reply text). Prefix patterns cover the Hungarian
# suffixes ("Billingóban", "Vercelre", "Higgsfieldet"). "fal" alone is a common Hungarian word (wall): only "fal.ai"
# and the hyphenated forms ("fal-lal", "fal-gen") count.
SERVICES = [
    ('higgsfield', r'\bhiggsfield'),
    ('metricool', r'\bmetricool'),
    ('fal', r'\bfal\.ai\b|\bfal-[a-z]'),
    ('billingo', r'\bbillingo'),
    ('stripe', r'\bstripe'),
    ('vercel', r'\bvercel'),
    ('supabase', r'\bsupabase'),
    ('elevenlabs', r'\beleven ?labs'),
    ('canva', r'\bcanva(?!s)'),
    ('remotion', r'\bremotion'),
    ('semrush', r'\bsemrush'),
    ('sparktoro', r'\bsparktoro'),
    ('dataforseo', r'\bdataforseo'),
    ('postiz', r'\bpostiz'),
]


def fold(text):
    text = unicodedata.normalize('NFKC', str(text)).translate(ZERO_WIDTH)
    text = ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))
    return text.lower()


def services():
    out = [(k, re.compile(p)) for k, p in SERVICES]
    try:
        with open(EXTRA_FILE, encoding='utf-8') as f:
            for line in f:
                name = fold(line.strip())
                if EXTRA_NAME.match(name) and name not in {k for k, _ in out}:
                    out.append((name, re.compile(r'\b' + re.escape(name))))
    except OSError:
        pass
    return out


def named(text, table=None):
    plain = fold(text)
    return sorted({k for k, rx in (table or services()) if rx.search(plain)})


def round_start(text):
    """A prompt that a person or a schedule started (see the module doc)."""
    if '<channel ' in text or '<scheduled-task ' in text:
        return True
    s = text.lstrip()
    if not s or s.startswith(('<', '[', '/')) or s.startswith('Base directory for this skill'):
        return False
    return True


def _texts(entry):
    content = (entry.get('message') or {}).get('content')
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [b.get('text') or '' for b in content if isinstance(b, dict) and b.get('type') == 'text']
    return []


def round_commands(path):
    """The Bash command texts since the last round start, or None when the transcript cannot be read."""
    try:
        # Viktor 40315 INFO 1: only a regular file. O_NONBLOCK: a FIFO would block a plain open() before any check.
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            return None
        with os.fdopen(fd, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            raw = f.read()
    except (OSError, TypeError, ValueError):
        return None
    lines = raw.split(b'\n')
    if size > TAIL_BYTES:
        lines = lines[1:]  # the first line is cut
    cmds = []
    for ln in lines:
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        if e.get('type') == 'user' and any(round_start(t) for t in _texts(e)):
            cmds = []
            continue
        if e.get('type') != 'assistant':
            continue
        content = (e.get('message') or {}).get('content')
        for b in content if isinstance(content, list) else []:
            if isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('name') == 'Bash':
                cmd = (b.get('input') or {}).get('command')
                if isinstance(cmd, str):
                    cmds.append(cmd)
    return cmds


PCT = re.compile(r'(?:%[0-9a-fA-F]{2})+')


def unquote(text):
    """URL percent-decoding ('+' = space) with re only: the scaffold memory-claim test keeps any network-looking import
    out of a hook that names the memories endpoint (agent-scaffold-memory-load-claim.test.ts COMMAND_MATCHERS)."""
    return PCT.sub(lambda m: bytes.fromhex(m.group(0).replace('%', '')).decode('utf-8', 'replace'), text.replace('+', ' '))


WRITE_METHOD = re.compile(r'(?:-X|--request)\s*["\']?(?:POST|PUT|PATCH|DELETE)\b', re.I)


def searched(key, cmds):
    """A memory READ in the round names the key. Saving a memory about it is not a search."""
    for cmd in cmds:
        if 'api/memories' not in cmd or WRITE_METHOD.search(cmd):
            continue
        try:
            plain = fold(unquote(cmd))
        except Exception:
            plain = fold(cmd)
        if key in plain:
            return True
    return False


def missing(text, cmds, table=None):
    return [k for k in named(text, table) if not searched(k, cmds)]


def is_main(payload):
    try:
        import ledger_lib
        return ledger_lib.agent_id_from_payload(payload) == ledger_lib.main_agent_id()
    except Exception:
        cwd = os.path.realpath(payload.get('cwd') or '')
        return not cwd.startswith(os.path.join(os.path.realpath(ROOT), 'agents') + os.sep)


def main():
    try:
        payload = json.load(sys.stdin)
        ti = payload.get('tool_input') or {}
        tool = str(payload.get('tool_name') or '')
    except Exception:
        return 0
    if not isinstance(payload, dict) or not isinstance(ti, dict) or tool.endswith('edit_message'):
        return 0
    text = ti.get('text') or ''
    names = named(text)
    if not names or not is_main(payload):
        return 0
    cmds = round_commands(payload.get('transcript_path') or '')
    if cmds is None:
        return 0
    gone = [k for k in names if not searched(k, cmds)]
    if not gone:
        return 0
    first = gone[0]
    sys.stderr.write(
        'MEMÓRIA-KAPU (Klodel 40111, TG 5750/5753): a válasz ismert szolgáltatást említ (%s), de ebben a körben nem '
        'kerestél rá a memóriában. Előbb Bash-ban: curl -s -G -D /tmp/mem-fejlec.txt -H "Authorization: Bearer '
        '$(cat %s/store/.dashboard-token)" --data-urlencode %s "http://localhost:3420/api/memories" '
        '(nevenként egy keresés), utána küldd.\n' % (', '.join(gone), ROOT, shlex.quote('q=' + first)))
    return 2


if __name__ == '__main__':
    sys.exit(main())
