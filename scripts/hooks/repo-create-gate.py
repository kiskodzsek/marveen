#!/usr/bin/env python3
"""repo-create-gate.py -- PreToolUse gate: no GitHub repository is created without Patrik's own words.

WHY (Klodel 40048, hibanapló 2026-11-13 11:27): Patrik asked a question ("nyilván kell egy repo, nem????", TG 18152)
and a repository was created under a name nobody asked for, without asking him. A question is not an order, and
a repository is an outward, hard-to-undo step (it is visible on the account, invitations go out, it gets a name).

SCOPE (everything else is allowed at once, exit 0, no output). Every agent, no opt-in.
  - Bash: the command text, the Bash `description`, and each script or payload file the command names
    (`python3 x.py`, `node x.mjs`, `bash x.sh`, `--data-binary @f`, `--input f`, `< f`; regular file, at most 64 KB).
  - An MCP tool whose name ends in create_repository, fork_repository or create_repository_using_template
    (GitHub MCP servers): the whole tool_input is judged.

CREATES A REPOSITORY (any of):
  - `gh repo create`, `gh repo fork`;
  - the REST paths `user/repos`, `orgs/<org>/repos`, `repos/<o>/<r>/forks`, `repos/<o>/<r>/generate`
    (with or without the api.github.com host) together with a write signal in the same text: -X/--method POST,
    `gh api` with -f/-F/--field/--raw-field/--input, curl -d/--data*/--json, `method='POST'` / "POST", requests/httpx
    .post(, urlopen(...data=). A GET of `user/repos` (listing) is not a creation.
  - the MCP tools above.

ALLOWED ONLY WITH (anywhere in the judged texts):
    PATRIK-KERTE: TG <number> "<Patrik's words, verbatim, at least 3 words>"
  Viktor 40095 L1 (MEDIUM): the line is written by the model, so the incident's own sentence would pass as approval.
  Hence: a quote ending in "?" is a question, not a request, and never approves. When the TG id is in the ledger
  (store/claudeclaw.db conversation_log, an inbound row with that message_id), the quote must stand in that row's
  text (case and whitespace folded). When the id is not in the ledger (measured: TG 18152 itself is missing), the
  line is accepted and the fact is appended to store/repo-create-gate.log, so it can be checked afterwards.

SCOPE OF THE MATCH (Viktor 40095 L2/L3): this stops an accidental model error, not a deliberate bypass. Covered:
  gh repo create/fork also in list form (["gh", "repo", "create"]), GraphQL createRepository, Octokit
  createForAuthenticatedUser / createInOrg / createUsingTemplate / createFork and "POST /user/repos", a trailing
  slash on the REST path, and every regular file of at most 64 KB that the command names in any position
  (./mk.py, npx tsx x.ts, source x.sh, @payload, < file). Not covered on purpose: aliases, variables holding
  "repo", line continuations, oversize commands or files.

CONTRACT (hook-exit-code-invariant): exit 2 = block, exit 0 = allow, never exit 1. Malformed stdin or an internal
error allows (fail OPEN) and is recorded in store/hook-errors.log through hook_errlog.
Tests: python3 -I scripts/hooks/repo-create-gate_test.py
"""
import json
import os
import re
import sys
import time

GH_CLI_RX = re.compile(r'(?<![\w-])gh[\'",\s]+repo[\'",\s]+(?:create|fork)(?![\w-])')
CREATE_API_RX = re.compile(
    r'\b(?:createRepository|createForAuthenticatedUser|createInOrg|createUsingTemplate|createFork)\b'
    r'|\bPOST[ \t]+/?(?:user/repos|orgs/[\w.-]+/repos|repos/[\w.-]+/[\w.-]+/(?:forks|generate))\b')
REST_PATH_RX = re.compile(
    r'(?<![\w-])(?:user/repos|orgs/[\w.-]+/repos|repos/[\w.-]+/[\w.-]+/(?:forks|generate))/?(?![\w/-])')
WRITE_RX = re.compile(
    r'(?:-X|--request|--method)[ \t=]*[\'"]?POST\b'
    r'|(?<![\w-])gh[ \t]+api\b[^\n]*?(?<![\w-])(?:-f|-F|--field|--raw-field|--input)(?![\w-])'
    r'|(?<![\w-])(?:-d|--data(?:-binary|-raw|-urlencode)?|--json)(?:[ \t=]|$)'
    r'|method[ \t]*=[ \t]*[\'"]POST[\'"]'
    r'|[\'"]POST[\'"]'
    r'|\b(?:requests|httpx|session|client)\.post\('
    r'|urlopen\([^)]*data[ \t]*=', re.I)
MCP_CREATE_RX = re.compile(r'(?:^|__)(?:create_repository(?:_using_template)?|fork_repository)$')
APPROVAL_RX = re.compile(r'PATRIK-KERTE:[ \t]*TG[ \t]*#?(\d{2,})[ \t]+["„“]([^"”\n]+)["”]')
SCRIPT_RX = re.compile(r'(?<![\w./-])(?:python3?|node|bash|sh|zsh|deno|bun|ruby|tsx|ts-node|npx(?:[ \t]+(?:tsx|ts-node))?'
                       r'|source)(?:[ \t]+-[\w-]+)*[ \t]+[\'"]?([^\s\'";|&<>()]+)'
                       # "." (source) only at a command start: `diff . x` is not a run (Viktor 40174 INFO)
                       r'|(?:^|[;&|(\n])[ \t]*\.[ \t]+[\'"]?([^\s\'";|&<>()]+)')
# ./x, ../x and an absolute /x at a command start (Viktor 40174 INFO: /abs/mk.py was not judged)
DIRECT_RX = re.compile(r'(?:^|[;&|(\n][ \t]*)[\'"]?(\.{0,2}/[^\s\'";|&<>()]+)')
DATA_FILE_RX = re.compile(r'(?<![\w-])(?:--data-binary|--data|-d)(?:\s+|=)?[\'"]?@([^\s\'";|&<>()]+)')
INPUT_FILE_RX = re.compile(r'(?<![\w-])--input(?:\s+|=)[\'"]?([^\s\'";|&<>()]+)')
STDIN_FILE_RX = re.compile(r'(?<![<\d])<[ \t]*[\'"]?([^\s\'";|&<>()]+)')
MAX_FILE = 64 * 1024
MAX_TEXT = 256 * 1024
MAX_FILES = 20


HEREDOC_RX = re.compile(r'<<-?[ \t]*([\'"]?)(\w+)\1[^\n]*\n(.*?)\n[ \t]*\2[ \t]*(?=\n|$)', re.S)
# A heredoc body is dropped ONLY when it goes into a known sink that does not execute it (Viktor 40174 MEDIUM: the
# earlier denylist of interpreter heads let `cat <<EOF | bash`, `sh -c "$(cat <<EOF ...)"` and `tee mk.sh <<EOF;
# bash mk.sh` through): a message wrapper, a commit message, a dashboard curl, or a text/data file.
MSG_SH = r'(?:[\w-]*-msg|msg-close)\.sh'
SINK_RX = re.compile(r'(?:^|[\s;&(/])' + MSG_SH + r'(?![\w.-])'
                     r'|(?<![\w-])git[ \t]+commit\b[^\n]*?(?<![\w-])-F[ \t]*-(?![\w-])'
                     r'|(?<![\w-])curl\b[^\n]*/api/(?:messages|kanban)\b'
                     r'|(?<![\w-])(?:cat[ \t]*>{1,2}|tee(?:[ \t]+-a)?)[ \t]*[\'"]?[^\s\'";|&<>()]+'
                     r'\.(?:md|txt|json|jsonl|log)[\'"]?[ \t]*$')
OPENER_RISK_RX = re.compile(r'\||\$\(|`|&&|;')
MSG_SH_RX = re.compile(MSG_SH + r'$')


def executed_text(cmd):
    """The command with the bodies of heredocs that go into a known non-executing sink removed (SINK_RX): a message,
    a commit message or a notes file that talks about creating a repository is not a creation (measured: 5 of 8 hits
    on 7 days of real calls were such texts). Every other heredoc body is kept and judged. Nothing is dropped when the
    opener line pipes or substitutes (|, $(, `, &&, ;), or when the command runs any script other than a message
    wrapper (a file written by this very command does not exist yet when the hook reads it)."""
    bodies = list(HEREDOC_RX.finditer(cmd))
    if not bodies:
        return cmd
    outside, pos = [], 0
    for m in bodies:
        outside.append(cmd[pos:m.start()])
        pos = m.end()
    outside.append(cmd[pos:])
    outside = '\n'.join(outside)
    runs = [a or b for a, b in SCRIPT_RX.findall(outside)] + DIRECT_RX.findall(outside)
    if any(not MSG_SH_RX.search(r) for r in runs if r and not r.startswith('-')):
        return cmd
    out, pos = [], 0
    for m in bodies:
        line_start = cmd.rfind('\n', 0, m.start()) + 1
        head = cmd[line_start:m.start()].rstrip()
        nl = cmd.find('\n', m.start())
        opener_rest = cmd[m.start():nl if nl != -1 else len(cmd)]
        out.append(cmd[pos:m.start()])
        # Only the sink's own segment counts: a `cd x &&` or `date;` before it is a separate command. A pipe or a
        # substitution in that segment, or anything chained after the opener, keeps the body.
        last = re.split(r'&&|\|\||;', head)[-1]
        # an UNCLOSED $( or ` before the opener wraps the heredoc (sh -c "$(cat <<EOF"); a closed one, like a
        # -H "Authorization: Bearer $(cat token)" header, does not
        wrapped = last.count('$(') > last.count(')') or last.count('`') % 2 == 1
        safe = (SINK_RX.search(last) and not wrapped and '|' not in last
                and not OPENER_RISK_RX.search(opener_rest))
        out.append('<<' + m.group(2) + '\n' + m.group(2) if safe else m.group(0))
        pos = m.end()
    out.append(cmd[pos:])
    return ''.join(out)


def creates_repo(text):
    """True when `text` creates a GitHub repository (see the docstring)."""
    if GH_CLI_RX.search(text) or CREATE_API_RX.search(text):
        return True
    return bool(REST_PATH_RX.search(text) and WRITE_RX.search(text))


def _fold(text):
    return ' '.join(str(text).split()).casefold()


def _ledger_text(tg_id):
    """(found, text) for an inbound conversation_log row with this message_id; (False, None) when absent or
    unreadable. Read-only: the ledger is never created."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import sqlite3
        import ledger_lib
        path = ledger_lib.db_path()
        if not os.path.isfile(path):
            return False, None
        con = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=5)
        try:
            row = con.execute("SELECT text FROM conversation_log WHERE direction='in' AND CAST(message_id AS TEXT)=? "
                              "ORDER BY id DESC LIMIT 1", (str(tg_id),)).fetchone()
        finally:
            con.close()
        return (True, row[0] or '') if row else (False, None)
    except Exception:
        return False, None


def _audit(line):
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import ledger_lib
        store = os.path.dirname(ledger_lib.db_path())
        with open(os.path.join(store, 'repo-create-gate.log'), 'a', encoding='utf-8') as fh:
            fh.write(json.dumps({'at': int(time.time()), 'note': line}, ensure_ascii=False) + '\n')
    except Exception:
        pass


def has_approval(texts):
    for t in texts:
        for m in APPROVAL_RX.finditer(t):
            tg_id, quote = m.group(1), m.group(2).strip()
            if len(quote.split()) < 3 or quote.rstrip(' .!').endswith('?'):
                continue  # too short, or a question (the incident: "nyilván kell egy repo, nem????")
            found, text = _ledger_text(tg_id)
            if found:
                ft, fq = _fold(text), _fold(quote)
                i = ft.find(fq)
                if i < 0:
                    continue  # the id is Patrik's message, but he did not write these words
                ends = [c for c in ft[i + len(fq):] if c in '.!?']
                if (ends[0] if ends else ft.rstrip()[-1:]) == '?':
                    continue  # the quoted sentence is a question in Patrik's message (Viktor 40174 LOW)
                return True
            _audit(f'PATRIK-KERTE TG {tg_id}: not in the ledger, accepted on the line alone')
            return True
    return False


def _strings(value, depth=0):
    """Every string inside a JSON value (bounded depth)."""
    if depth > 6:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v, depth + 1)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v, depth + 1)]
    return []


def _read_small(path):
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > MAX_FILE:
            return None
        with open(path, encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except OSError:
        return None


def referenced_files(cmd, cwd):
    out = []
    # Viktor 40095 L2c: the file an EXECUTING form names (interpreter, npx/tsx/ts-node, source, ".", "./x") plus
    # payload files. Not every named file: `git add` / `cat` / `grep` of this gate's own source would then block.
    # Collected from the command WITHOUT the sink heredoc bodies: prose inside a message ("python3 -I, ...") must not
    # fill the MAX_FILES budget and push a real reference out. A payload fed to a message wrapper or to a dashboard
    # curl (/api/messages, /api/kanban) is a message, not a run, and is not read.
    text = executed_text(cmd)
    refs = [a or b for a, b in SCRIPT_RX.findall(text)] + DIRECT_RX.findall(text) + INPUT_FILE_RX.findall(text)
    for seg in re.split(r'&&|\|\||;|\n', text):
        if re.search(MSG_SH + r'(?![\w.-])', seg) or re.search(r'(?<![\w-])curl\b.*/api/(?:messages|kanban)\b', seg):
            continue
        refs += DATA_FILE_RX.findall(seg) + STDIN_FILE_RX.findall(seg)
    refs = refs[:MAX_FILES]
    for ref in refs:
        if ref.startswith('-'):
            continue
        path = os.path.expanduser(ref)
        if not os.path.isabs(path):
            if not (isinstance(cwd, str) and os.path.isabs(cwd)):
                continue
            path = os.path.join(cwd, path)
        body = _read_small(path)
        if body is not None:
            out.append(body)
    return out


REASON = ('REPO-KAPU / REPO-CREATE-GATE (Klodel 40048): GitHub-repó létrehozása (gh repo create/fork, POST '
          'user/repos, orgs/<org>/repos, forks, generate) csak Patrik szó szerinti kérésével mehet. Írd a parancsba '
          'vagy a leírásba: PATRIK-KERTE: TG <id> "<Patrik szavai, legalább 3 szó>". Kérdés nem kérés: ha Patrik '
          'kérdezett, előbb kérdezz vissza (név, hova, privát-e). / Creating a repository needs Patrik\'s verbatim '
          'request on a PATRIK-KERTE: line.')


def verdict(payload):
    if not isinstance(payload, dict):
        return None
    tool = payload.get('tool_name')
    ti = payload.get('tool_input')
    if not isinstance(tool, str) or not isinstance(ti, dict):
        return None
    if tool == 'Bash':
        cmd = ti.get('command')
        if not isinstance(cmd, str):
            return None
        cmd = cmd[:MAX_TEXT]
        files = referenced_files(cmd, payload.get('cwd'))
        if not any(creates_repo(t) for t in [executed_text(cmd)] + files):
            return None
        desc = ti.get('description') if isinstance(ti.get('description'), str) else ''
        return None if has_approval([cmd, desc] + files) else REASON
    if tool.startswith('mcp__') and MCP_CREATE_RX.search(tool):
        # The string values themselves: json.dumps would escape the quote marks the line needs.
        return None if has_approval([v[:MAX_TEXT] for v in _strings(ti)]) else REASON
    return None


def main():
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
            hook_errlog.report('repo-create-gate', 'internal error, allowed', ex)
        except Exception:
            pass
        return 0
    if reason:
        sys.stderr.write(reason + '\n')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
