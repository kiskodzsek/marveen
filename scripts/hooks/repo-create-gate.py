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
  The quote must be his request for THIS repository, not a question about one; the gate cannot judge that, the
  line makes the claim checkable afterwards (the TG id points at the message).

CONTRACT (hook-exit-code-invariant): exit 2 = block, exit 0 = allow, never exit 1. Malformed stdin or an internal
error allows (fail OPEN) and is recorded in store/hook-errors.log through hook_errlog.
Tests: python3 -I scripts/hooks/repo-create-gate_test.py
"""
import json
import os
import re
import sys

GH_CLI_RX = re.compile(r'(?<![\w-])gh[ \t]+repo[ \t]+(?:create|fork)(?![\w-])')
REST_PATH_RX = re.compile(
    r'(?<![\w-])(?:user/repos|orgs/[\w.-]+/repos|repos/[\w.-]+/[\w.-]+/(?:forks|generate))(?![\w/-])')
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
SCRIPT_RX = re.compile(r'(?<![\w-])(?:python3?|node|bash|sh|zsh|deno|bun|ruby)(?:[ \t]+-[\w-]+)*[ \t]+[\'"]?([^\s\'";|&<>()]+)')
DATA_FILE_RX = re.compile(r'(?<![\w-])(?:--data-binary|--data|-d)(?:\s+|=)?[\'"]?@([^\s\'";|&<>()]+)')
INPUT_FILE_RX = re.compile(r'(?<![\w-])--input(?:\s+|=)[\'"]?([^\s\'";|&<>()]+)')
STDIN_FILE_RX = re.compile(r'(?<![<\d])<[ \t]*[\'"]?([^\s\'";|&<>()]+)')
MAX_FILE = 64 * 1024
MAX_TEXT = 256 * 1024
MAX_FILES = 20


def creates_repo(text):
    """True when `text` creates a GitHub repository (see the docstring)."""
    if GH_CLI_RX.search(text):
        return True
    return bool(REST_PATH_RX.search(text) and WRITE_RX.search(text))


def has_approval(texts):
    for t in texts:
        for m in APPROVAL_RX.finditer(t):
            if len(m.group(2).split()) >= 3:
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
    refs = (SCRIPT_RX.findall(cmd) + DATA_FILE_RX.findall(cmd) + INPUT_FILE_RX.findall(cmd)
            + STDIN_FILE_RX.findall(cmd))[:MAX_FILES]
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
        if not any(creates_repo(t) for t in [cmd] + files):
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
