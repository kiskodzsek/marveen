#!/usr/bin/env python3
"""PreToolUse gate (Bash): an agent shell does not read secrets out of the macOS keychain with `security`.

Why: Viktor 29950 (2026-11-06, card c1921b55). Every agent runs as the same macOS user, so any agent shell can
read any keychain item of that user (another agent's OAuth token, the Vault master key): the accepted structural
risk H1 of 2026-10-12. This gate is the cheap defense-in-depth Viktor asked for, NOT the fix: the fix is per-agent
isolation (H1). It does not see a keychain read made through Python/Node/Swift APIs, osascript's own keychain
calls, or a command name hidden in a variable (`s=security; $s dump-keychain`). Do not rely on it.

What blocks (exit 2): a `security` call in command position whose subcommand reads or exports secrets:
  find-generic-password, find-internet-password, dump-keychain, export,
or that reads its subcommands from stdin (`security -i`, `security -p <prompt>`), which would hide the subcommand.
Command position: the start of the command, or after ; & | ( ) { } a newline, a backtick, $( , an opening quote
(`bash -c "security ..."`, `ssh host 'security ...'`), after find's -exec / -execdir / -ok, and after the
wrapper and keyword words env, sudo, exec, command, nohup, time, nice, xargs, caffeinate, arch, builtin, timeout,
stdbuf, setsid, if, then, else, elif, do, while, until, `!`, their flags, numbers (`timeout 5`, `nice -n 5`) and
VAR=value assignments. A path before it counts (`/usr/bin/security`). Case-insensitive: the default macOS volume
resolves `SECURITY` to the same binary.
Before matching, shell escapes that do not change the word are removed: backslash-newline, a backslash before a
letter (`sec\\urity`), empty quotes inside a word (`sec''urity`), and `$IFS` / `${IFS}` read as a space. A second
pass matches with every quote and backslash removed (`"security" find-...`, `s"ec"urity`, `security "export"`).
Not seen (known gaps, Viktor 30044): a wrapper flag with a word argument (`sudo -u root`, `env -u A`,
`script -q /dev/null`), and everything listed above under "does not see".
Allowed: every other `security` subcommand (list-keychains, find-identity, find-certificate, show-keychain-info,
verify-cert ...) and the word in plain text (`grep find-generic-password notes.md`, `git commit -m "fix: security"`).
Known false positive: a quoted string that starts with the blocked call (`grep "security dump-keychain" f`):
search for the subcommand alone instead.
Script files (card bc009036; Kernel 41497, Viktor 41502, 2026-11-13: a keychain measurement ran as
`python3 measure.py` and wrote a fake token into the login keychain; the gate saw only "python3 measure.py"). The
file a command runs is read and judged too:
  - which files: the first path argument of an interpreter in command position (python, python3, python3.x, node,
    bash, sh, zsh, dash, ksh, ruby, perl, osascript, deno, bun, tsx, ts-node, php, swift; its flags skipped; after
    a -c / -e flag the code is inline, not a file; python -m mod: the files the module runs from the cwd, mod.py,
    mod/__init__.py, mod/__main__.py and each dotted parent), and a path in command position run directly (`./x.py`,
    `/abs/x.sh`, `tools/x.py`). A relative path is resolved against the payload cwd and every `cd /absolute` in
    the command. The first MAX_SCRIPT_BYTES of each file; more than MAX_SCRIPTS files in one command blocks (an
    unread eleventh file would be a way around), and so does a scan that runs past SCRIPT_BUDGET_S (a hook that
    times out does not block). A path that is not a regular file is skipped (the interpreter cannot run it either).
  - what blocks in such a file: the shell rules above on its text (a `security find-...` string run by
    os.system, subprocess with shell=True, a shell script), or a literal naming the binary ('security',
    "/usr/bin/security", SEC=security) together with a secret subcommand anywhere in the file
    (find-generic-password, find-internet-password, dump-keychain) or a quoted 'export', '-i' or '-p' argument.
    The second form is what measure.py had: SEC = '/usr/bin/security'; run([SEC, 'find-generic-password', ...]).
  - inline code: when the command calls an interpreter, the literal rule runs on the command text itself
    (`python3 -c "..."`, `python3 - <<'PY' ... PY`).
  Not seen: a module the script imports, a file the script builds or downloads, a name assembled at run time
  ('sec' + 'urity'), keychain APIs (Security.framework, keyring). The gate's own test assembles its fixtures at
  run time, so running the test is not blocked.
Any error while matching blocks (fail-closed; exit 1 would not block). Input that is not a Bash call is allowed.
The command text is never logged: it may itself carry a secret.
Tests: keychain-read-gate_test.py next to this file.
"""
import json
import os
import re
import stat
import sys
import time

WRAPPERS = (r'(?:env|sudo|exec|command|nohup|time|nice|xargs|caffeinate|arch|builtin|timeout|stdbuf|setsid'
            r'|if|then|else|elif|do|while|until)')
# Command position, then any words that may stand before the command: wrapper words, their flags, a number (a
# duration or a niceness: `timeout 5`, `nice -n 5`), VAR=value assignments, `!`. One token matches one way only (a
# token starts with a letter and is a wrapper, with `-`, with a digit or `+`/`.`, or is NAME=...; `\s+` ends it):
# nesting two ways to read the same token backtracked exponentially (Viktor 30044: 26 x "env a=b " never returned).
# WORD: a run that stops at every separator and quote, so the scan from one command position never runs past the
# next one: with \S* a run of 20 000 quotes took 0.7 s and 60 000 about 13 s, longer than a hook may run
# (a hook that times out does not block). Card bc009036, measured 2026-11-13.
WORD = r'[^\s;&|(){}`\'"]'
# Blanks after a position are spaces and tabs only: a newline is a position of its own, and with \s* every newline
# of a 6 000-newline run rescanned the rest (10 s; the same in the gate before card bc009036). A find -exec is a
# position too, so it is not also read as a flag: 12 000 x " -exec" took 112 s that way.
POSITION = (r'(?:^|[;&|(){}\n`\'"]|\$\(|\s-(?:exec|execdir|ok)(?=\s))[ \t]*'
            r'(?:(?:' + WRAPPERS + r'\b|!|-(?!(?:exec|execdir|ok)(?=\s))' + WORD + r'*|[+.]?\d[\w.]*|\w+=' + WORD + r'*)[ \t]+)*')
BINARY = r'(?:' + WORD + r'*/)?security'
OPTIONS = r'(?:\s+-\S+)*'
SECRET_SUB = r'(?:find-generic-password|find-internet-password|dump-keychain|export)'
RULES = [
    ('secret-read', re.compile(POSITION + BINARY + OPTIONS + r'\s+' + SECRET_SUB + r'(?![\w-])', re.I)),
    ('stdin-mode', re.compile(POSITION + BINARY + r'(?:\s+-\S+)*?\s+-[a-z]*[ip][a-z]*(?=\s|$|[;&|)`\'"])', re.I)),
]


def normalise(cmd):
    cmd = cmd.replace('\\\n', '')                    # line continuation
    cmd = re.sub(r'\\([A-Za-z])', r'\1', cmd)       # sec\urity -> security
    cmd = re.sub(r'(?<=\w)(?:\'\'|"")(?=\w)', '', cmd)  # sec''urity -> security
    cmd = re.sub(r'\$\{IFS\}|\$IFS\b', ' ', cmd)        # security${IFS}dump-keychain -> a space
    return cmd


def hits(cmd):
    text = normalise(cmd)
    # Second pass with every quote and backslash removed: "security" find-..., s"ec"urity, security "export".
    # More false positives than the first pass, which the gate already accepts (see the docstring).
    bare = re.sub(r'[\'"\\]', '', text)
    return [name for name, rx in RULES if rx.search(text) or rx.search(bare)]


MAX_SCRIPTS = 10
MAX_SCRIPT_BYTES = 1024 * 1024
MAX_BASES = 6
# Time budget for reading the files, from the start of the hook. The hook's timeout is 10 s and a hook that times out
# does not block; ten 1 MB files of newlines took 6.6 s (2026-11-13), so on a loaded machine the scan could run past
# it. Past the budget the gate blocks ('script-too-slow') instead of reading on. KEYCHAIN_GATE_SCRIPT_BUDGET_S can only
# LOWER the budget (the test sets 0); a larger value is ignored.
SCRIPT_BUDGET_S = 4.0
T0 = time.monotonic()


def script_budget():
    try:
        return max(0.0, min(SCRIPT_BUDGET_S, float(os.environ.get('KEYCHAIN_GATE_SCRIPT_BUDGET_S', SCRIPT_BUDGET_S))))
    except ValueError:
        return SCRIPT_BUDGET_S
PATH_TOKEN = r'''['"]?([^\s'";|&<>()`$]+)['"]?'''
INTERP = (r'(?:' + WORD + r'*/)?(?:python[\d.]*|node|bash|sh|zsh|dash|ksh|ruby|perl|osascript|deno|bun|tsx|ts-node|php|swift'
          r'|npx\s+(?:tsx|ts-node))')
# The interpreter's flags, then the file. A flag that takes inline code or a module means no file follows.
INTERP_FILE_RX = re.compile(POSITION + INTERP + r'((?:\s+-[\w-]+(?:=\S+)?)*)\s+' + PATH_TOKEN, re.I)
INTERP_RX = re.compile(POSITION + INTERP + r'(?=\s|$)', re.I)
# The interpreter and its flags with nothing after them but the end of the command (`python3 -mmeasure`).
INTERP_FLAGS_ONLY_RX = re.compile(POSITION + INTERP + r'((?:[ \t]+-[\w-]+(?:=' + WORD + r'+)?)*)(?=[ \t]*(?:$|[;&|)\n]))',
                                  re.I | re.M)
CODE_FLAG_RX = re.compile(r'(?:^|\s)(?:-[a-zA-Z]*[cem]|--eval|--command)(?=\s|$|=)')
# python -m runs a module, and from the cwd that is a file: `python3 -m measure` runs ./measure.py, `-m pkg.sub` runs
# pkg/__init__.py and pkg/sub.py, `-m pkg` also pkg/__main__.py (measured 2026-11-13; not with -I, judged anyway).
MODULE_FLAG_RX = re.compile(r'(?:^|\s)-[a-zA-Z]*m$')
MODULE_ATTACHED_RX = re.compile(r'(?:^|\s)-m([A-Za-z_][\w.]*)(?=\s|$)')
MODULE_NAME_RX = re.compile(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*){0,7}')


def module_files(mod):
    """The files `python -m mod` runs from a search directory, relative to it."""
    if not MODULE_NAME_RX.fullmatch(mod):
        return []
    parts = mod.split('.')
    out = []
    for i in range(1, len(parts) + 1):
        base = '/'.join(parts[:i])
        out += [base + '.py', base + '/__init__.py']
    return out + ['/'.join(parts) + '/__main__.py']
DIRECT_RX = re.compile(POSITION + r'''['"]?((?:\.{1,2}/|/|[\w.-]+/)[^\s'";|&<>()`$]*)['"]?(?=\s|$|[;&|)])''')
CD_RX = re.compile(r'''(?<![\w./-])cd\s+['"]?(/[^\s'";|&<>()`$]+)''')
# A literal naming the binary: 'security', "/usr/bin/security", or a shell assignment SEC=security.
BIN_LITERAL_RX = re.compile(r'''['"](?:[^'"\s]*/)?security['"]|=\s*['"]?(?:\S*/)?security['"]?(?=\s|$|;)''', re.I)
# Case-sensitive, unlike the binary: `security List-keychains` is "unknown command" while `SECURITY list-keychains`
# runs (APFS is case-insensitive; measured 2026-11-13). With re.I a UI string table ('Security' label, 'Export'
# button: web/lang/en.js) read as a keychain read.
SECRET_WORD_RX = re.compile(r'(?<![\w-])(?:find-generic-password|find-internet-password|dump-keychain)(?![\w-])'
                            r'''|['"](?:export|-i|-p)['"]''')


def literal_hit(text):
    return bool(BIN_LITERAL_RX.search(text) and SECRET_WORD_RX.search(text))


def script_paths(cmd, cwd):
    """The script files the command runs (resolved, existing regular files), at most MAX_SCRIPTS."""
    text = normalise(cmd)
    cands = []
    for m in INTERP_FILE_RX.finditer(text):
        flags = m.group(1) or ''
        python = 'python' in m.group(0).lower()
        attached = MODULE_ATTACHED_RX.search(flags) if python else None
        if attached:
            cands += module_files(attached.group(1))
        elif python and MODULE_FLAG_RX.search(flags):
            cands += module_files(m.group(2))
        elif not CODE_FLAG_RX.search(flags):
            cands.append(m.group(2))
    if 'python' in text.lower():  # `python3 -mmeasure` alone: no path token follows, INTERP_FILE_RX does not match
        for m in INTERP_FLAGS_ONLY_RX.finditer(text):
            a = MODULE_ATTACHED_RX.search(m.group(1) or '')
            if a and 'python' in m.group(0).lower():
                cands += module_files(a.group(1))
    cands += [m.group(1) for m in DIRECT_RX.finditer(text)]
    bases = ([cwd] if isinstance(cwd, str) and os.path.isabs(cwd) else []) + CD_RX.findall(text)
    out = []
    for c in cands:
        if c in ('-', '--') or c.startswith('-'):
            continue
        tries = [c] if os.path.isabs(c) else [os.path.join(b, c) for b in bases[:MAX_BASES]]
        for t in tries:
            real = os.path.realpath(t)
            try:
                st = os.stat(real)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode) and real not in out:
                out.append(real)
        if len(out) > MAX_SCRIPTS:
            break
    return out


def script_hits(cmd, cwd):
    """Rule names for inline interpreter code and for the files the command runs."""
    found = []
    if INTERP_RX.search(normalise(cmd)) and literal_hit(cmd):
        found.append('script-inline')
    paths = script_paths(cmd, cwd)
    if len(paths) > MAX_SCRIPTS:  # not "check the first ten": an eleventh file would slip past (fail-closed)
        return found + ['script-too-many']
    budget = script_budget()
    for path in paths:
        if time.monotonic() - T0 > budget:  # not "allow the rest": a timed-out hook would not block either
            return found + ['script-too-slow']
        with open(path, 'rb') as f:
            body = f.read(MAX_SCRIPT_BYTES).decode('utf-8', errors='replace')
        if hits(body) or literal_hit(body):
            found.append('script-file')
            break
    return found


def main():
    try:
        data = json.load(sys.stdin)
        ti = data.get('tool_input') or {}
    except Exception:
        return 0
    if not isinstance(ti, dict):
        return 0
    cmd = ti.get('command')
    if not isinstance(cmd, str) or not cmd:
        return 0
    cwd = data.get('cwd') if isinstance(data, dict) else None
    try:
        found = hits(cmd)
        found += [h for h in script_hits(cmd, cwd) if h not in found]
    except Exception as e:  # fail-closed
        found = [f'a kapu hibára futott ({e.__class__.__name__}), ezért blokkol']
    if found:
        sys.stderr.write(
            f'KULCSKARIKA-KAPU: a parancs (vagy az általa futtatott szkript) a macOS kulcskarikából olvasna titkot '
            f'({", ".join(found)}): '
            'security find-generic-password / find-internet-password / dump-keychain / export, vagy -i/-p mód. '
            'Ágens-shellből ez tilos (Viktor 29950, H1): más ágens credentialje is ott van. Ha egy kulcs kell, '
            'a Vault-wrapper adja (scripts/vault-env-wrapper.sh), az értékét ne írd ki. Ha csak egy szövegben '
            'keresel, a subcommandot keresd magában (pl. grep find-generic-password).\n')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
