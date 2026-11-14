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
  - which files: for an interpreter in command position (python, python3, python3.x, node, bash, sh, zsh, dash,
    ksh, ruby, perl, osascript, deno, bun, tsx, ts-node, php, swift, source, `.`, npx tsx, uv/poetry/pipenv/pdm/
    hatch run), every one of its following words that is an existing regular file, its arguments included (an
    innocent first file, `node -r ./ok.js m.js`, does not hide the script; Viktor 41756 LOW 2), up to MAX_ARGS
    words: more words, or a command running past ARGS_WINDOW, blocks unread ('script-too-many-args', LOW 1); after
    -c / -e or `-` the code is inline or on stdin; source and `.` run their first word only (the rest are that
    script's arguments); python -m mod: the files
    the module runs from the cwd, mod.py, mod/__init__.py, mod/__main__.py and each dotted parent); when an
    interpreter runs, also a `< file` redirect and the files of a `cat` (`cat m.py | python3`, quoted too); and a
    path in command position run directly (`./x.py`, `/abs/x.sh`, `tools/x.py`). A quoted interpreter name counts
    (`'python3' m.py`, `os.system("python3 m.py")`). For these script rules a quote is a command position only where
    a payload opens (`bash -c "./x.sh"`, `bash -c -- '...'`, `eval "..."`, `watch -n 1 '...'`, `tmux new '...'`,
    `do shell script "..."`; Viktor 41790 LOW 1), so the word after a closing quote (`grep -n "x" f.py`) is not a
    command. A relative path is resolved against the
    payload cwd and the directory after each `cd` in order, a relative cd on top of the one before; `~`, `$HOME` and
    variables assigned in the command itself (`F=m.py; python3 $F`) are expanded (Viktor 41715 LOW). The first
    MAX_SCRIPT_BYTES of each file. Fail-closed: more than MAX_SCRIPTS files, MAX_BASES directories or MAX_TRIES
    lookups in one command, a scan past SCRIPT_BUDGET_S, and a WATCHDOG_S alarm on the whole hook (a slow regex
    inside one file included; a hook that times out does not block). A path that is not a regular file is skipped.
  - what blocks in such a file: the shell rules above on its text (a `security find-...` string run by
    os.system, subprocess with shell=True, a shell script), or a literal naming the binary ('security',
    "/usr/bin/security", `security` in a JS template, SEC=security) together with a secret subcommand anywhere in the file
    (find-generic-password, find-internet-password, dump-keychain) or a quoted 'export', '-i' or '-p' argument.
    The second form is what measure.py had: SEC = '/usr/bin/security'; run([SEC, 'find-generic-password', ...]).
  - inline code: when the command calls an interpreter, the literal rule runs on the command text itself
    (`python3 -c "..."`, `python3 - <<'PY' ... PY`).
  Not seen: a module the script imports, a file the script builds or downloads, a name assembled at run time
  ('sec' + 'urity'), keychain APIs (Security.framework, keyring), a variable set outside the command, a quoted path
  with spaces, a Ruby %w list, a payload a quote opens after other commands (`command '...'`, `time '...'` run a
  command literally named so, which fails; `script -q /dev/null python3 m.py`, `su -c`, `ssh` run remotely or are
  not listed). The gate's own test assembles its fixtures at
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
            r'|if|then|else|elif|do|while|until|eval|watch)')
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
# The script rules below (an interpreter, a path run directly, cat into an interpreter) take a quote as a command
# position only where a shell -c payload opens (`bash -c "./x.sh"`, `bash -lc '...'`). With every quote a position, the
# word after a CLOSING quote looked like a command: `grep -n "for x" scripts/hooks/keychain-read-gate.py` read the
# gate's own source as a script it runs and blocked (measured 2026-11-14 on the #275 gate; card 7427e6f4).
# Payloads a quote opens (Viktor 41790 LOW 1): after `-c` and up to four more flags (`bash -c -- '...'`, `-c -x`),
# after eval, watch (its flags and numbers), tmux new / new-session (up to six words), osascript's `do shell script`;
# an escaped quote too (`do shell script \"...\"`). Each run of words is bounded ({0,4}, {0,6}): an unbounded one
# rescanned " -exec" runs (Viktor's first try ran past 5 s on 12 000 x " -exec"). A call in inline code,
# os.system("python3 m.py"), opens at the "(" position with the quote before the interpreter (INTERP_RX below).
PAYLOAD_OPEN = (r'(?:[ \t]-[A-Za-z]*c(?:[ \t]+-' + WORD + r'*){0,4}'
                r'|(?<![\w-])(?:eval|watch(?:[ \t]+(?:-' + WORD + r'*|\d[\w.]*)){0,4}'
                r'|tmux[ \t]+new(?:-session)?(?:[ \t]+' + WORD + r'+){0,6}|do[ \t]+shell[ \t]+script))[ \t]+\\?[\'"]')
SCRIPT_POSITION = (r'(?:^|[;&|(){}\n`]|\$\(|\s-(?:exec|execdir|ok)(?=\s)|' + PAYLOAD_OPEN + r')[ \t]*'
                   r'(?:(?:' + WRAPPERS + r'\b|!|-(?!(?:exec|execdir|ok)(?=\s))' + WORD + r'*|[+.]?\d[\w.]*|\w+=' + WORD
                   + r'*)[ \t]+)*')
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
          r'|source|\.|npx[ \t]+(?:tsx|ts-node)|(?:uv|poetry|pipenv|pdm|hatch)[ \t]+run(?:[ \t]+python[\d.]*)?)')
INTERP_RX = re.compile(SCRIPT_POSITION + r'\\?[\'"]?' + INTERP + r'[\'"]?(?=\s|$)', re.I)
# After the interpreter: its words up to the end of that command, read without a regex (Viktor 41715 LOW a: a flag's
# argument, `-W ignore`, `-o pipefail`, was taken for the file). Every word that is an existing regular file is judged,
# not only the first (Viktor 41756 LOW 2: `node -r ./ok.js measure.js` hid measure.js behind ./ok.js); a code flag
# (-c, -e, --eval, --command) or `-` ends the walk (inline code or stdin). Words past MAX_ARGS, or a command running
# past ARGS_WINDOW, are not read, so they block ('script-too-many-args', Viktor 41756 LOW 1: 12 x -B then measure.py
# passed). 64, not 12: with a block past it, 12 would stop ordinary `python3 x.py --a 1 --b 2 ...` calls.
CMD_END = ';&|\n)`'
MAX_ARGS = 64
ARGS_WINDOW = 4096
MAX_TRIES = 4000  # path lookups per command; past it the gate blocks (an unread path would be a way around)
CODE_FLAG_RX = re.compile(r'-[a-zA-Z]*[ce]|--eval(?:=.*)?|--command(?:=.*)?')
# python -m runs a module, and from the cwd that is a file: `python3 -m measure` runs ./measure.py, `-m pkg.sub` runs
# pkg/__init__.py and pkg/sub.py, `-m pkg` also pkg/__main__.py (measured 2026-11-13; not with -I, judged anyway).
MODULE_FLAG_RX = re.compile(r'-[a-zA-Z]*m')
MODULE_ATTACHED_RX = re.compile(r'-m([A-Za-z_][\w.]*)')
MODULE_NAME_RX = re.compile(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*){0,7}')
# The script on stdin (Viktor 41715 LOW d): `python3 < m.py`, `python3 - < m.py`, `cat m.py | python3`. Only when the
# command runs an interpreter.
REDIRECT_RX = re.compile(r'(?<![<\d&])<(?![<(&])[ \t]*' + PATH_TOKEN)
CAT_RX = re.compile(SCRIPT_POSITION + r'cat((?:[ \t]+[\'"]?' + WORD + r'+[\'"]?)+)')
# Shell variables set in the command (Viktor 41715 LOW f: `F=m.py; python3 $F`), and every cd in order, a relative one
# on top of the one before (LOW b: `cd sub && python3 only.py`).
ASSIGN_RX = re.compile(r'''(?<![\w$])([A-Za-z_]\w*)=(['"]?)([^\s'";|&<>()`$]+)\2(?=\s|$|;)''')
VAR_RX = re.compile(r'\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)')
CD_RX = re.compile(r'''(?<![\w./-])cd[ \t]+''' + PATH_TOKEN)
MAX_BASES = 32


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
DIRECT_RX = re.compile(SCRIPT_POSITION + r'''['"]?((?:\.{1,2}/|/|[\w.-]+/)[^\s'";|&<>()`$]*)['"]?(?=\s|$|[;&|)])''')
# A literal naming the binary: 'security', "/usr/bin/security", `security` (a JS template), or a shell assignment
# SEC=security. The assignment branch walks path segments, not \S*: `=\s*['"]?(?:\S*/)?security` ran to the end of every
# space-free run and searched back for "/" at each "=", quadratic: 100 000 "=" took 9 s, 1 MB never returned within the
# 10 s hook limit, a 300 KB minified bundle 23.7 s (Viktor 41715 MEDIUM, his fix, measured 0.03-0.26 s).
BIN_LITERAL_RX = re.compile(r'''['"`](?:[^'"`\s]*/)?security['"`]|=[ \t]*['"]?/?(?:[\w.~+-]+/)*security['"]?(?=\s|$|;)''',
                            re.I)
# Case-sensitive, unlike the binary: `security List-keychains` is "unknown command" while `SECURITY list-keychains`
# runs (APFS is case-insensitive; measured 2026-11-13). With re.I a UI string table ('Security' label, 'Export'
# button: web/lang/en.js) read as a keychain read.
SECRET_WORD_RX = re.compile(r'(?<![\w-])(?:find-generic-password|find-internet-password|dump-keychain)(?![\w-])'
                            r'''|['"](?:export|-i|-p)['"]''')  # not `-p`: a code span in a comment (2 false
# positives in src/ with it: pane-state.ts, agent-worker.ts); a template literal still shows the full subcommand word


def literal_hit(text):
    return bool(BIN_LITERAL_RX.search(text) and SECRET_WORD_RX.search(text))


def strip_quotes(word):
    # a backslash too: the escaped quote that closes `do shell script \"python3 m.py\"` left "m.py\"
    return word[1:-1] if len(word) >= 2 and word[0] == word[-1] and word[0] in '\'"' else word.strip('\'"\\')


def expand(text):
    """$VAR / ${VAR} from assignments in the command itself, and $HOME; ~ is expanded per word later."""
    env = {'HOME': os.path.expanduser('~')}
    for m in ASSIGN_RX.finditer(text):
        env[m.group(1)] = m.group(3)
    return VAR_RX.sub(lambda m: env.get(m.group(1) or m.group(2), m.group(0)), text)


def cd_bases(text, cwd):
    """cwd, then the directory after each cd in order (a relative cd on top of the one before)."""
    cur = cwd if isinstance(cwd, str) and os.path.isabs(cwd) else None
    bases = [cur] if cur else []
    for m in CD_RX.finditer(text):
        t = os.path.expanduser(m.group(1))
        if os.path.isabs(t):
            cur = t
        elif cur:
            cur = os.path.join(cur, t)
        else:
            continue
        if cur not in bases:
            bases.append(cur)
            if len(bases) > MAX_BASES:  # the caller only needs "too many"; collecting on was quadratic (25 000 cd: 2 s)
                break
    return bases


class TooManyArgs(Exception):
    """An interpreter call with words the gate does not read (past MAX_ARGS or ARGS_WINDOW): the caller blocks."""


def interp_groups(text):
    """For each interpreter call: the words that may be its script, in order (every existing file is judged).
    Raises TooManyArgs when a call's words run past MAX_ARGS or ARGS_WINDOW and the walk did not stop before."""
    groups = []
    for m in INTERP_RX.finditer(text):
        python = 'python' in m.group(0).lower()
        name = re.split(r'[\s;&|(){}`\'"/\\]', m.group(0).rstrip('\'"\\'))[-1]
        rest = text[m.end():m.end() + ARGS_WINDOW]  # a window, not the rest: 6 000 calls x the rest was quadratic
        cut = min([i for i in (rest.find(ch) for ch in CMD_END) if i >= 0] or [len(rest)])
        all_words = rest[:cut].split()
        if name in ('.', 'source'):
            # source runs its first word; the rest are that script's arguments. Prose after a ")" made a sentence-
            # ending "." read as source of a file named later in the sentence (an agent-msg heredoc, 2026-11-14).
            first = [strip_quotes(w) for w in all_words[:2] if not w.startswith('-')][:1]  # `. -- f.sh` too
            if first and first[0]:
                groups.append(first)
            continue
        # the window ended inside this command: what follows it is not read
        clipped = cut == len(rest) == ARGS_WINDOW and m.end() + ARGS_WINDOW < len(text)
        words = [strip_quotes(w) for w in all_words[:MAX_ARGS]]
        group = []
        stopped = False
        i = 0
        while i < len(words):
            w = words[i]
            attached = MODULE_ATTACHED_RX.fullmatch(w) if python else None
            if attached:
                groups += [[c] for c in module_files(attached.group(1))]
                stopped = True
                break
            if python and MODULE_FLAG_RX.fullmatch(w):
                if i + 1 < len(words):
                    groups += [[c] for c in module_files(words[i + 1])]
                stopped = True
                break
            if w == '-' or CODE_FLAG_RX.fullmatch(w):
                stopped = True
                break
            if not w.startswith('-') and w:
                group.append(w)
            i += 1
        if not stopped and clipped:
            raise TooManyArgs(f'a parancs hosszabb a {ARGS_WINDOW} karakteres ablaknál')
        if not stopped and len(all_words) > MAX_ARGS:
            raise TooManyArgs(f'{len(all_words)} szó, MAX_ARGS {MAX_ARGS}')
        if group:
            groups.append(group)
    return groups


def script_paths(cmd, cwd):
    """The script files the command runs (resolved, existing regular files), at most MAX_SCRIPTS (an eleventh file
    or more than MAX_BASES directories returns MAX_SCRIPTS + 1 entries: the caller blocks). Raises TooManyArgs."""
    text = expand(normalise(cmd))
    groups = interp_groups(text)
    if INTERP_RX.search(text):  # the script on stdin: only when an interpreter runs
        groups += [[m.group(1)] for m in REDIRECT_RX.finditer(text)]
        for m in CAT_RX.finditer(text):
            cat_words = m.group(1).split()
            if len(cat_words) > MAX_ARGS:
                raise TooManyArgs(f'cat: {len(cat_words)} szó, MAX_ARGS {MAX_ARGS}')
            groups += [[strip_quotes(w)] for w in cat_words if not w.startswith('-')]
    groups += [[m.group(1)] for m in DIRECT_RX.finditer(text)]
    bases = cd_bases(text, cwd)
    if groups and len(bases) > MAX_BASES:
        return [''] * (MAX_SCRIPTS + 1)
    out = []
    tries = 0
    for group in groups:
        for c in group:
            c = os.path.expanduser(c)
            if c in ('-', '--'):
                continue
            for t in ([c] if os.path.isabs(c) else [os.path.join(b, c) for b in bases]):
                tries += 1
                if tries > MAX_TRIES:
                    return [''] * (MAX_SCRIPTS + 1)
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
    try:
        paths = script_paths(cmd, cwd)
    except TooManyArgs as e:  # not "judge the first MAX_ARGS words": a file behind them would slip past (fail-closed)
        return found + [f'script-too-many-args ({e})']
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


# Watchdog (Viktor 41715 MEDIUM, belt and braces): whatever runs slow, a regex inside one file included, the gate
# blocks before the 10 s hook timeout, which would let the call through. Python's re checks for signals while it
# matches (measured 2026-11-13: a quadratic search on 600 000 chars was cut at 1 s, rc 2). os._exit, so no except
# clause can swallow it. KEYCHAIN_GATE_WATCHDOG_S can only lower it (a test seam), never to 0 (0 disarms an itimer).
WATCHDOG_S = 6.0  # 8 s left ~1.3 s to the 10 s hook limit (Viktor 41756 INFO 3: the alarm came 0.72 s late)


def watchdog_s():
    try:
        v = float(os.environ.get('KEYCHAIN_GATE_WATCHDOG_S', WATCHDOG_S))
    except ValueError:
        return WATCHDOG_S
    return WATCHDOG_S if v != v else max(0.001, min(WATCHDOG_S, v))  # v != v: nan


def on_watchdog(signum, frame):
    os.write(2, 'KULCSKARIKA-KAPU: a kapu nem végzett időben (watchdog), ezért blokkol: a hook-időtúllépés '
                'átengedné a hívást.\n'.encode('utf-8'))
    os._exit(2)


def arm_watchdog():
    import signal
    signal.signal(signal.SIGALRM, on_watchdog)
    signal.setitimer(signal.ITIMER_REAL, watchdog_s())


def main():
    arm_watchdog()
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
