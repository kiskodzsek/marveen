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
A wrapper flag with a word argument and a wrapper's positional words (`sudo -u root`, `env -u A`, `timeout -s KILL
5`, `exec -a x`, `script -q /dev/null`, `ssh host`, `flock f`, `sg g`, `chroot d`) no longer hide the command: the
blank before the command they run becomes a command boundary (wrapper_bounds, WRAP_ARGS; card 3085a683, the gap
Viktor 30044 and 41831 INFO 3 named). A walk past MAX_ARGS words blocks ('wrapper-unread').
git's credential paths into the login keychain (card 04d67b39, Viktor 41943): `git credential fill|approve|reject`,
the osxkeychain helper called directly (`git credential-osxkeychain get`, `git-credential-osxkeychain`, by path),
and choosing it (`git -c credential.helper=osxkeychain ...`, `git config ... credential.helper osxkeychain`,
GIT_CONFIG_PARAMETERS / GIT_CONFIG_VALUE_<n>), with git's own options before the subcommand (`git -C d -c a=b`) and
behind xcrun. Plain `git fetch` / `git push` pass. These read the command text, not a script file's (GIT_RULES).
And what takes away the ~/.gitconfig helper reset (card 49d58372, Viktor 42039 MEDIUM 1): GIT_CONFIG_GLOBAL=,
GIT_CONFIG_SYSTEM=, HOME= before git or set in the shell before a later git (export, unset, a bare assignment), env -i /
env -u HOME before git; an include (`-c include.path=`, `--config-env=`, GIT_CONFIG_PARAMETERS, GIT_CONFIG_KEY_<n>,
`git config include.path ...` in any scope), `--config-env=credential.helper=VAR`, a URL-scoped helper naming
osxkeychain; `git config --global` / `--system` / `--file` writing the credential helper or its section, or `-e`;
a writing `git config` whose scope or key the shell still expands (`$K`, `$(...)`, `credential.{helper,x}`).
Passes: reading (`git config --get ...`, `--list`), GIT_CONFIG_NOSYSTEM=1 (no system helper), the call's own
`-c credential.helper=` (it empties the list last). A git that a program other than a shell runs (`HOME=/x npm
test`) is not seen, nor a write to ~/.gitconfig by an editor or a Write tool (a path hook's job).
Not seen: everything listed above under "does not see"; a wrapper not in WRAP_ARGS whose flag takes a word (su,
runuser, ionice, taskset, unbuffer ...), and a quoted string that starts with a wrapped call blocks like one that
starts with the call (`git commit -m "sudo -u root security dump-keychain"`).
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
    -c / -e or `-` the code is inline or on stdin; source and `.` judge their first word, and the rest only when
    that first word is an existing regular file (the sourced script gets them as $1...: `source runner.sh m.py`,
    Viktor 41831 LOW 1; a sentence-ending "." in prose is followed by a word that is no file); python -m mod: the files
    the module runs from the cwd, mod.py, mod/__init__.py, mod/__main__.py and each dotted parent); when an
    interpreter runs, also a `< file` redirect and the files of a `cat` (`cat m.py | python3`, quoted too); and a
    path in command position run directly (`./x.py`, `/abs/x.sh`, `tools/x.py`). A quoted interpreter name counts
    (`'python3' m.py`, `os.system("python3 m.py")`). For these script rules a quote is a command position only where
    a payload opens (`bash -c "./x.sh"`, `bash -c -- '...'`, `eval "..."`, `watch -n 1 '...'`, `tmux new '...'`,
    `do shell script "..."`; Viktor 41790 LOW 1), so the word after a closing quote (`grep -n "x" f.py`) is not a
    command. Past those bounds (a fifth watch word, a fifteenth tmux new word: PAYLOAD_OVER_RX) and after a -c
    word of any command (`su -c`, `flock f -c`, `script -q -c`, `"$SHELL" -c`, `bash -c -o pipefail '...'`; Viktor
    41831 LOW 2, 41859 B, 41893 LOW 1, Klodel 41895), the first quote later in the same command, and every quote
    there when a shell word stands before the -c (a quoted option argument: `bash -c -o 'pipefail' '...'`), is
    turned into a command boundary and the payload is judged by these same rules (payload_quotes). Not a blind
    block: `ls -c -l -a -h -t -r "my dir"`, `grep -c ... "x"`, `git log -c ... 'f'` pass (Viktor 41859 A); a quoted
    interpreter call on a keychain-reading file after any -c blocks (`grep -c "python3 m.py" f`), as on the live
    gate 741204a4: accepted (Klodel 41895). A relative path is resolved against the
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
  command literally named so, which fails). A wrapped script (`sudo -u root python3 m.py`, `ssh localhost python3
  m.py`, `sg staff 'python3 m.py'`) is read like any other (card 3085a683; for ssh the file is looked up here, which
  is right for localhost and a fail-closed guess for a remote host). The gate's own test assembles its fixtures at
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
# CHAIN: the words that may stand before the command (one way to read each token, see above).
CHAIN = r'(?:(?:' + WRAPPERS + r'\b|!|-(?!(?:exec|execdir|ok)(?=\s))' + WORD + r'*|[+.]?\d[\w.]*|\w+=' + WORD + r'*)[ \t]+)*'
POSITION = r'(?:^|[;&|(){}\n`\'"]|\$\(|\s-(?:exec|execdir|ok)(?=\s))[ \t]*' + CHAIN
# The script rules below (an interpreter, a path run directly, cat into an interpreter) take a quote as a command
# position only where a shell -c payload opens (`bash -c "./x.sh"`, `bash -lc '...'`). With every quote a position, the
# word after a CLOSING quote looked like a command: `grep -n "for x" scripts/hooks/keychain-read-gate.py` read the
# gate's own source as a script it runs and blocked (measured 2026-11-14 on the #275 gate; card 7427e6f4).
# Payloads a quote opens (Viktor 41790 LOW 1): after eval, watch (its flags and numbers), tmux new / new-session (up to fourteen words), osascript's `do shell script`;
# an escaped quote too (`do shell script \"...\"`). A -c is not here but in payload_quotes(), with any options
# between it and the payload (Viktor 41859 B, 41893). Each run of words is bounded ({0,4}, {0,14}): an unbounded one
# rescanned " -exec" runs (Viktor's first try ran past 5 s on 12 000 x " -exec"). Past the bound the run is not
# read (Viktor 41831 LOW 2: `bash -c` with five -x, tmux new with seven words let the payload through): payload_quotes()
# turns the first quote after it into a boundary, for watch / tmux past their bound (PAYLOAD_OVER_RX) and for a
# shell word followed by a -c word (SHELL_RX, C_WORD_RX), and the payload is judged like any command. Linear: one
# pass per command, the next command end looked up in an index (a scan per match was quadratic).
# tmux new takes fourteen words (six stopped `tmux new-session -d -s a -x 1 -y 1 '...'`, a real call; with -n and
# -c a real call has eleven). A find -exec is not a -c flag: 12 000 x " -exec" read as one blocked. A call in inline code,
# os.system("python3 m.py"), opens at the "(" position with the quote before the interpreter (INTERP_RX below).
PAYLOAD_OPEN = (r'(?:(?<![\w-])(?:eval|watch(?:[ \t]+(?:-' + WORD + r'*|\d[\w.]*)){0,4}'
                r'|tmux[ \t]+new(?:-session)?(?:[ \t]+' + WORD + r'+){0,14}|do[ \t]+shell[ \t]+script))[ \t]+\\?[\'"]')
PAYLOAD_OVER_RX = re.compile(r'(?<![\w-])watch(?:[ \t]+(?:-' + WORD + r'*|\d[\w.]*)){5}'
                             r'|tmux[ \t]+new(?:-session)?(?:[ \t]+' + WORD + r'+){15}')
# A -c word (-c, -lc, -xc, and -exec: bash reads it as -e -x -e -c and runs the payload, measured 2026-11-14) after
# ANY command opens a payload at the next quote: su -c, flock f -c, script -q -c, sg g -c, fish -c, "$SHELL" -c ...
# all run one, and the live gate (741204a4) read every one (Viktor 41893 LOW 1, Klodel 41895: a list of shells is
# never complete, the merge must not weaken the live gate). The -c word may be quoted itself (`bash '-c' '...'`
# runs the payload; Viktor 41906 LOW 1). Accepted cost, wider than the live gate's (which only read a quote right
# after the -c): a quoted interpreter call on a keychain-reading file after any -c of the same command blocks
# (`grep -c "python3 m.py" f`, `grep -c -i "python3 m.py" f`, `ssh -c aes128-ctr h "python3 m.py"`).
# A shell word before the -c in the same command (bash5, "bash", /bin/bash, $SHELL, $BASH, $0 too): every quote up
# to the next ; & | or newline opens one, since an option argument before the payload can be quoted too (`bash -c
# -o 'pipefail' '...'`, `bash -c "-x" '...'`; Viktor 41893 LOW 2), and can come from a $(...) whose ")" would end
# the command too early (`bash -c $(echo -x) '...'`; Viktor 41906 LOW 2).
SHELL_RX = re.compile(r'(?:^|(?<=[\s;&|(){}`\'"/]))(?:(?:bash|sh|zsh|dash|ksh|fish|csh|tcsh|ash|rbash|pwsh)\d*'
                      r'|\$\{?(?:SHELL|BASH)\}?|\$0)[\'"]?(?=[ \t])')
C_WORD_RX = re.compile(r'(?<=[ \t])[\'"]?-[A-Za-z]*c[\'"]?(?=[ \t])')
QUOTE_RX = re.compile(r'[\'"]')
SCRIPT_POSITION = r'(?:^|[;&|(){}\n`]|\$\(|\s-(?:exec|execdir|ok)(?=\s)|' + PAYLOAD_OPEN + r')[ \t]*' + CHAIN
BINARY = r'(?:' + WORD + r'*/)?security'
OPTIONS = r'(?:\s+-\S+)*'
SECRET_SUB = r'(?:find-generic-password|find-internet-password|dump-keychain|export)'
RULES = [
    ('secret-read', re.compile(POSITION + BINARY + OPTIONS + r'\s+' + SECRET_SUB + r'(?![\w-])', re.I)),
    ('stdin-mode', re.compile(POSITION + BINARY + r'(?:\s+-\S+)*?\s+-[a-z]*[ip][a-z]*(?=\s|$|[;&|)`\'"])', re.I)),
]
# git's credential paths into the login keychain (Viktor 41943 HIGH, Klodel 41948, card 04d67b39): the system git
# config names osxkeychain as the helper, so `git credential fill` (and approve / reject, which store and erase) and
# the helper itself (`git credential-osxkeychain get`, `git-credential-osxkeychain get`, by path too) read or write
# the login keychain's credentials, other agents' included. `git` is walked like a wrapper (WRAP_ARGS: -C, -c,
# --git-dir ...), and its subcommand is always marked a command position, so `git -C d -c a=b credential fill` is
# read as `credential fill`. Choosing the helper by name blocks too (`git -c credential.helper=osxkeychain fetch`,
# `git config credential.helper osxkeychain`). A plain `git fetch` / `git push` passes (Klodel 41948: Pulzus and
# the push scripts use an extraheader); what the system helper does inside them is the config's to fix (card
# 1c205f39: GIT_CONFIG_NOSYSTEM), not this gate's.
# These rules read the COMMAND text (inline code in it too), not a script file's text: scripts/gh-pr.mjs runs
# `git credential fill` with the helper list reset to the clone's own helpers (the keychain helper never asked) and
# names it in a comment and a string, both of which read as a command position.
# A URL-scoped helper (`credential.https://github.com.helper`) is a helper too; an include names a file of config
# (`include.path`, `includeIf.gitdir:~/x/.path`). Bounded runs: one way to read a word, no rescan of a long one.
HELPER_SCOPE = r'(?:\.[^\s=\'"]{1,200})?'
INCLUDE_KEY = r'include(?:if\.[^\s=\'"]{1,300})?\.path'
GIT_RULES = [
    ('git-credential', re.compile(POSITION + r'credential[ \t]+(?:fill|approve|reject)(?![\w-])', re.I)),
    ('git-credential-helper', re.compile(POSITION + r'\\?[\'"]?(?:' + WORD + r'*/)?(?:git-)?credential-osxkeychain'
                                         r'(?![\w-])', re.I)),
    # choosing the helper: `git -c credential.helper=osxkeychain ...`, `git config [flags] credential.helper
    # osxkeychain`, GIT_CONFIG_PARAMETERS / GIT_CONFIG_VALUE_<n>; not the words in prose (a commit message that says
    # "the system config sets credential.helper=osxkeychain" passes: two of 19 861 replayed commands were such)
    ('git-credential-helper', re.compile(r'(?<![\w-])-c[ \t]+[\'"]?credential' + HELPER_SCOPE + r'\.helper=[\'"]?!?'
                                         r'[^\s\'";|&]*osxkeychain', re.I)),
    ('git-credential-helper', re.compile(POSITION + r'config(?:[ \t]+-' + WORD + r'*)*[ \t]+[\'"]?credential'
                                         + HELPER_SCOPE + r'\.helper[\'"]?[ \t]+[\'"]?!?[^\s\'";|&]*osxkeychain',
                                         re.I)),
    # (GIT_CONFIG_PARAMETERS / GIT_CONFIG_VALUE_<n> naming osxkeychain: env_value_hit below, linear)
    # card 49d58372 (Viktor 42039 MEDIUM 1): a config the command names by indirection brings the helper back, the
    # name of osxkeychain in a file the rules cannot read: `-c include.path=<file>`, `--config-env=credential.helper=
    # VAR` / `--config-env=include.path=VAR`, an include in GIT_CONFIG_PARAMETERS / GIT_CONFIG_KEY_<n> (all measured
    # on git 2.54, Apple Git-157: the helper of the named file or variable is called after the ~/.gitconfig reset)
    ('git-config-override', re.compile(r'(?<![\w-])-c[ \t]+[\'"]?' + INCLUDE_KEY + r'=', re.I)),
    ('git-config-override', re.compile(r'(?<![\w-])--config-env(?:=|[ \t]+)[\'"]?(?:credential' + HELPER_SCOPE
                                       + r'\.helper|' + INCLUDE_KEY + r')=', re.I)),
    ('git-config-override', re.compile(r'(?<![\w-])GIT_CONFIG_KEY_\d+=[\'"]?' + INCLUDE_KEY + r'(?![\w.-])', re.I)),
]

# card 49d58372 (Viktor 42039 MEDIUM 1): ~/.gitconfig empties the helper list (card 7e47b573), so the system
# osxkeychain helper is not asked. Measured on git 2.54 (Apple Git-157), these take the reset away before git runs:
# GIT_CONFIG_GLOBAL=<other file or /dev/null>, HOME=<other dir>, `env -i` / `env -u HOME` (no HOME: no global
# config). GIT_CONFIG_SYSTEM does not (the system layer is read before the global reset; Viktor asked for it, and it
# has no use here). Blocked: such a prefix of the git call (`HOME=/x git fetch`, `env -i git ...`, `sudo -u a
# HOME=/x git`); a shell-level one before a later git (`export HOME=/x; git fetch`, `unset HOME && git ...`); one on
# a shell or an interpreter whose own command runs git (`HOME=/x bash -c 'git fetch'`), up to that command's end
# (the first ; & | or newline outside quotes). Not blocked, each measured: GIT_CONFIG_NOSYSTEM=1 / true / yes / on
# in force (no system layer, no helper at all), the git call's own `-c credential.helper=` (it empties the list
# last; a helper named after it that is osxkeychain blocks by the rule above), and a git config that only reads
# (`git config --get-all credential.helper`). A git inside some other program the prefix starts (`HOME=/x npm test`)
# is not seen: a script's git, as everywhere in this gate.
OVERRIDE_VARS = {'HOME', 'GIT_CONFIG_GLOBAL', 'GIT_CONFIG_SYSTEM'}
_DECL = {'export', 'declare', 'typeset', 'readonly', 'local', 'unset'}
_CHAIN_WORDS = set(re.findall(r'[a-z-]+', WRAPPERS)) | {'!'}
_CARRY = {'bash', 'sh', 'zsh', 'dash', 'ksh', 'fish', 'csh', 'tcsh', 'ash', 'rbash', 'pwsh', 'python', 'node', 'perl',
          'ruby', 'osascript', 'deno', 'bun', 'tsx', 'php', 'swift', 'eval', 'source', '.'}
# a simple command starts after these (the secret rules' positions: an opening quote too, `bash -c "..."`)
_SEG_RX = re.compile(r'\$\(|[;&|(){}\n`\'"]')
_ASSIGN_RX = re.compile(r'([A-Za-z_]\w*)=(.*)', re.S)
_TRUE = {'1', 'true', 'yes', 'on'}


def _env_flags(words, i, name, st):
    """Skip the flags and positional words of wrapper `name` from words[i]; return the next index. For env, note in
    st what it does to HOME (-i / --ignore-environment / - / -u HOME / --unset HOME: 'sets') and to
    GIT_CONFIG_NOSYSTEM (-i or -u it: 'nosys' False)."""
    short, whole, positional = WRAP_ARGS[name]
    flags_done = False
    env = name == 'env'

    def unset(var):
        if var == 'HOME':
            st['sets'] = True
        elif var == 'GIT_CONFIG_NOSYSTEM':
            st['nosys'] = False
    while i < len(words):
        t = strip_quotes(words[i])
        if not flags_done and t == '--':
            flags_done = True
        elif not flags_done and env and t == '-':
            st['sets'], st['nosys'] = True, False
        elif not flags_done and t.startswith('--'):
            key, eq, val = t.partition('=')
            if env and key == '--ignore-environment':
                st['sets'], st['nosys'] = True, False
            if key in whole and not eq:
                i += 1
                val = strip_quotes(words[i]) if i < len(words) else ''
            if env and key == '--unset':
                unset(val)
        elif not flags_done and t.startswith('-') and len(t) > 1:
            for k, ch in enumerate(t[1:], 1):
                if env and ch == 'i':
                    st['sets'], st['nosys'] = True, False
                if ch in short:
                    arg = t[k + 1:]
                    if not arg:
                        i += 1
                        arg = strip_quotes(words[i]) if i < len(words) else ''
                    if env and ch == 'u':
                        unset(arg)
                    break
        elif positional:
            positional -= 1
        else:
            break
        i += 1
    return i


def _assign(st, name, value):
    if name in OVERRIDE_VARS:
        st['sets'] = True
        # a config file the git call reads: it can name a helper itself (an empty value or /dev/null: no global
        # config at all, measured on git 2.54)
        if strip_quotes(value) not in (('',) if name == 'HOME' else ('', '/dev/null')) and name != 'GIT_CONFIG_SYSTEM':
            st['file'] = True
    elif name == 'GIT_CONFIG_NOSYSTEM':
        st['nosys'] = value.lower() in _TRUE


def _segment(seg):
    """One simple command: {'sets': one of OVERRIDE_VARS set or HOME cleared, 'nosys': GIT_CONFIG_NOSYSTEM in force
    (None: not touched), 'cmd': the command word (None: a shell-level assignment, export, unset), 'rest': its words}."""
    every = seg.split()
    words = every[:MAX_ARGS]
    st = {'sets': False, 'file': False, 'nosys': None, 'cmd': None, 'rest': [], 'bare_nosys': False}
    wrapper = None
    bare_nosys = False
    i = 0
    while i < len(words):
        w = strip_quotes(words[i])
        base = w.rsplit('/', 1)[-1].lower()
        a = _ASSIGN_RX.match(w)
        if a:
            _assign(st, a.group(1), a.group(2))
            bare_nosys |= a.group(1) == 'GIT_CONFIG_NOSYSTEM'
            i += 1
        elif base in WRAP_ARGS and base != 'git':
            wrapper = base
            i = _env_flags(words, i + 1, base, st)
        elif base in _CHAIN_WORDS or w.startswith('-') or re.fullmatch(r'[+.]?\d[\w.]*', w):
            wrapper = wrapper or base
            i += 1
        elif base in _DECL:  # export HOME=/x, unset HOME: the shell's own, for what runs after it
            tail = [strip_quotes(x) for x in every[i + 1:]]  # every word, not the MAX_ARGS slice (Viktor 42207 M3)
            # only export, or declare / typeset / local with -x, exports: `declare GIT_CONFIG_NOSYSTEM=1` and
            # `readonly ...` leave git the system helper (measured, bash; Dave on Viktor 42207 M2)
            exports = base == 'export' or any(re.fullmatch(r'-[a-zA-Z]*x[a-zA-Z]*', x) for x in tail)
            for x in tail:
                name, eq, value = x.partition('=')
                if base == 'unset':
                    if name in OVERRIDE_VARS:
                        st['sets'] = True
                    elif name == 'GIT_CONFIG_NOSYSTEM':
                        st['nosys'] = False
                elif name == 'GIT_CONFIG_NOSYSTEM' and not exports:
                    st['nosys'] = False if eq and value.lower() not in _TRUE else st['nosys']
                elif eq or name in OVERRIDE_VARS:  # `export HOME` after `HOME=/x;` counts too
                    _assign(st, name, value)
            return st
        else:
            st['cmd'], st['rest'] = base, [strip_quotes(x) for x in words[i + 1:]]
            return st
    if len(every) > MAX_ARGS and any(strip_quotes(x).rsplit('/', 1)[-1].lower() == 'git' for x in every[i:]):
        # a prefix past MAX_ARGS words is not read: with a git after it, fail closed
        st['sets'], st['cmd'] = True, 'git'
    elif wrapper:
        st['cmd'] = wrapper  # a wrapper with nothing after it (`env -i`) changes nothing for later commands
    st['bare_nosys'] = bare_nosys
    return st


def _git_resets(rest):
    """The git call itself takes the helper away: its own `-c credential.helper=` (empty), or it only reads config."""
    short, whole, _ = WRAP_ARGS['git']
    reset = False
    i = 0
    while i < len(rest):
        t = rest[i]
        if t in whole or t in ('-C', '-c'):
            arg = rest[i + 1] if i + 1 < len(rest) else ''
            reset |= t == '-c' and arg.lower() == 'credential.helper='
            i += 2
            continue
        if not t.startswith('-'):  # a joined `-ccredential.helper=` is no git option (unknown option, measured)
            if t.lower() == 'config':
                low = [x.lower() for x in rest[i + 1:]]
                verb = next((x for x in low if not x.startswith('-')), '')
                return reset or verb in ('get', 'list') or any(x in _CONFIG_READ for x in low)
            return reset
        i += 1
    return reset


_TOKEN_RX = re.compile(r'[ \t]*((?:[^\s\'";&|]+|\'[^\']*\'|"[^"]*")+)')


def _rest_words(text, pos):
    """The words of the command from pos up to its end (a ; & | newline outside quotes), quotes taken off as the
    shell does, after the first word that is git: `git -c 'credential.helper=' ...` keeps its empty value. At most
    MAX_ARGS words and ARGS_WINDOW characters are read (a bounded walk per git call)."""
    words = []
    end = min(len(text), pos + ARGS_WINDOW)
    while len(words) < MAX_ARGS:
        m = _TOKEN_RX.match(text, pos, end)
        if not m:
            break
        words.append(re.sub(r'\'([^\']*)\'|"([^"]*)"', lambda q: q.group(1) or q.group(2) or '', m.group(1)))
        pos = m.end()
    i = next((j for j, w in enumerate(words) if w.rsplit('/', 1)[-1].lower() == 'git'), None)
    return None if i is None else words[i + 1:]


def config_override(text):
    """True when git runs with the ~/.gitconfig reset taken away (see OVERRIDE_VARS)."""
    shell_sets, shell_nosys, shell_file = False, None, False  # set by the shell itself: holds to the end of the text
    carry, open_q = False, None  # a prefix on a shell or an interpreter: holds to its command's end
    pos = 0
    for m in list(_SEG_RX.finditer(text)) + [None]:
        seg = text[pos:m.start()] if m else text[pos:]
        st = _segment(seg)
        cmd = st['cmd']
        nosys = st['nosys'] if st['nosys'] is not None else shell_nosys
        if cmd == 'git' and (st['sets'] or shell_sets or carry) and not (nosys and not (st['file'] or shell_file)):
            rest = _rest_words(text, pos)
            if not _git_resets(st['rest'] if rest is None else rest):
                return True
        if cmd is None:
            shell_sets |= st['sets']
            shell_file |= st['file']
            # `GIT_CONFIG_NOSYSTEM=1;` alone (the statement ends at ; & | or a newline) is a shell variable, not
            # exported: a later git does not see it (measured: the system helper comes back)
            if not (st['bare_nosys'] and (m is None or m.group(0) in ';&|\n')):
                shell_nosys = st['nosys'] if st['nosys'] is not None else shell_nosys
        elif st['sets'] and re.sub(r'[\d.]+$', '', cmd) in _CARRY:
            carry, open_q = True, None
        if m is None:
            break
        sep = m.group(0)
        if carry:
            if sep in '\'"':
                open_q = None if open_q == sep else (open_q or sep)
            elif sep in ';&|\n' and open_q is None:
                carry = False
        pos = m.end()
    return False


# `git config` writing the helper of the global or system config (or of a file named with -f), its credential
# section, or an include in any scope (a local include is read after the global reset too); one whose scope or key
# is still expanded by the shell (_unread_key). Reading passes (`--get`, `--get-all`, `--list`, `git config get ...`).
_CONFIG_RX = re.compile(POSITION + r'config(?![\w.-])', re.I)
_HELPER_KEY_RX = re.compile(r'credential' + HELPER_SCOPE + r'\.helper', re.I)
_INCLUDE_KEY_RX = re.compile(INCLUDE_KEY, re.I)
_SECTION_RX = re.compile(r'(?:credential|include(?:if)?)(?:\..*)?', re.I)
_CONFIG_END_RX = re.compile(r'[;&|\n)`({}]|\$\(')
_EXPANDS_RX = re.compile(r'[$*?\[]')  # (a brace or a backtick ends the window: never in a word)
_KEYLIKE_RX = re.compile(r'[\w.$*?\[\]-]+')


def _unread_key(rest, stop, words, low):
    """A writing `git config` whose scope or key the shell still expands, so it can be any of them:
    `K=credential.helper; git config --global $K ''`, `git config $(echo --global) ...`, `git config --global
    credential.{helper,x} ''`. Only the flags and the key are read (a value's `$E` is the value), only a word shaped
    like a key, and a `$(` or a backtick only after a blank: prose and code that name `config` (`git config --list`,
    in backticks; `assert.match(config, /{...}/)`) are no such call (measured on the replay)."""
    key_i = next((i for i, w in enumerate(low) if not w.startswith('-')), None)
    head = words if key_i is None else words[:key_i + 1]
    if any(_KEYLIKE_RX.fullmatch(w) and _EXPANDS_RX.search(w) for w in head):
        return True
    if not stop:
        return False
    at, sep = stop.start(), stop.group(0)
    before = rest[at - 1:at]  # at 0: right after `config` (`` `git config` `` in prose), attached
    if (sep == '$(' or (sep == '`' and before.isspace())) and key_i is None:
        return True  # the scope or the key comes from a substitution
    # `cred$(echo ential).helper`, `credential.{helper,x}`: the key cut at a substitution or a brace attached to it
    # (an attached backtick is not judged: prose writes `git config user.name` in backticks)
    return sep in ('$(', '{') and not before.isspace() and key_i is not None and key_i == len(words) - 1 \
        and _KEYLIKE_RX.fullmatch(words[key_i]) is not None


_CONFIG_READ = {'--get', '--get-all', '--get-regexp', '--get-urlmatch', '-l', '--list', '--get-color',
                '--get-colorbool'}


def config_write(text):
    for m in _CONFIG_RX.finditer(text):
        rest = text[m.end():m.end() + ARGS_WINDOW]
        stop = _CONFIG_END_RX.search(rest)  # the command ends, or another one starts: `(config (config ...` read once
        words = [strip_quotes(w) for w in rest[:stop.start() if stop else len(rest)].split()[:MAX_ARGS]]
        low = [w.lower() for w in words]
        verb = next((w for w in low if not w.startswith('-')), '')
        if verb in ('get', 'list') or any(w in _CONFIG_READ for w in low):
            continue
        if _unread_key(rest, stop, words, low):
            return True
        scoped = any(w in ('--global', '--system', '--file', '-f') or w.startswith('--file=') for w in low)
        if any(_INCLUDE_KEY_RX.fullmatch(w) for w in words):
            return True
        if scoped and (any(_HELPER_KEY_RX.fullmatch(w) for w in words)
                       or (any(w in ('--remove-section', '--rename-section', 'remove-section', 'rename-section')
                               for w in low) and any(_SECTION_RX.fullmatch(w) for w in words))
                       or any(w in ('-e', '--edit', 'edit') for w in low)):
            return True
    return False


# A GIT_CONFIG_PARAMETERS / GIT_CONFIG_VALUE_<n> value up to the end of its command, each value read once: the
# pattern `GIT_CONFIG_PARAMETERS=[^\n;&|]*osxkeychain` rescanned the rest of the line from every assignment
# (20 000 x `GIT_CONFIG_PARAMETERS=x...` ran into the 6 s watchdog on main c08e49fc too, measured 2026-11-14).
_PARAMS_RX = re.compile(r'(?<![\w-])GIT_CONFIG_(?:PARAMETERS|VALUE_\d+)=', re.I)
_ONLY_PARAMS_RX = re.compile(r'(?<![\w-])GIT_CONFIG_PARAMETERS=', re.I)
_VALUE_END_RX = re.compile(r'[\n;&|]')
_OSXKEYCHAIN_RX = re.compile(r'osxkeychain', re.I)
_INCLUDE_NAMED_RX = re.compile(INCLUDE_KEY + r'(?![\w.-])', re.I)


def env_value_hit(text, var_rx, needle_rx):
    reach = 0
    for m in var_rx.finditer(text):
        if m.end() < reach:  # inside a value already read from an earlier assignment of the same command
            continue
        e = _VALUE_END_RX.search(text, m.end())
        reach = e.start() if e else len(text)
        if needle_rx.search(text, m.end(), reach):
            return True
    return False


class FnRule:
    """A rule judged by a function (the same `search(text)` call as a compiled pattern). plain: judged on the
    command text only (and with its quotes taken off), not on the text with the wrapped commands' bounds: the
    function walks the wrappers itself, and a bound inside `git;config ...` would cut git from its own options."""
    def __init__(self, fn, plain=False):
        self.search, self.plain = fn, plain


GIT_RULES += [('git-credential-helper', FnRule(lambda t: env_value_hit(t, _PARAMS_RX, _OSXKEYCHAIN_RX))),
              ('git-config-override', FnRule(lambda t: env_value_hit(t, _ONLY_PARAMS_RX, _INCLUDE_NAMED_RX))),
              ('git-config-override', FnRule(config_override, plain=True)),
              ('git-config-override', FnRule(config_write))]


def normalise(cmd):
    cmd = cmd.replace('\\\n', '')                    # line continuation
    cmd = re.sub(r'\\([A-Za-z])', r'\1', cmd)       # sec\urity -> security
    cmd = re.sub(r'(?<=\w)(?:\'\'|"")(?=\w)', '', cmd)  # sec''urity -> security
    cmd = re.sub(r'\$\{IFS\}|\$IFS\b', ' ', cmd)        # security${IFS}dump-keychain -> a space
    return cmd


def hits(cmd, script=False):
    """Rule names the text matches; a script file's text (script=True) is not judged by GIT_RULES."""
    text = normalise(cmd)
    # `sudo -u root security ...` (card 3085a683): the text with the wrapped commands' boundaries is judged TOO, not
    # instead: a wrong mark (a flag the table reads as taking a word that it does not) could split a call the plain
    # text blocks (`security;dump-keychain`), so a mark only ever adds a block
    bounded = wrapper_bounds(text, WRAP_RX)
    if bounded is None:
        return ['wrapper-unread']
    # Second pass with every quote and backslash removed: "security" find-..., s"ec"urity, security "export".
    # More false positives than the first pass, which the gate already accepts (see the docstring).
    texts = [text] if bounded == text else [text, bounded]
    texts += [re.sub(r'[\'"\\]', '', t) for t in texts]
    found = []
    plain = [text, re.sub(r'[\'"\\]', '', text)]
    for name, rx in RULES + ([] if script else GIT_RULES):
        if name not in found and any(rx.search(t) for t in (plain if getattr(rx, 'plain', False) else texts)):
            found.append(name)
    return found


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


class SourceGroup:
    """`source f a b`: the rest (a, b) is judged only when f is an existing regular file; `over` names why the rest
    is not all read (past MAX_ARGS or ARGS_WINDOW), and then such a call blocks."""
    def __init__(self, first, rest, over):
        self.first, self.rest, self.over = first, rest, over


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
        # the window ended inside this command: what follows it is not read
        clipped = cut == len(rest) == ARGS_WINDOW and m.end() + ARGS_WINDOW < len(text)
        if name in ('.', 'source'):
            # source runs its first word and hands it the rest as $1...: a runner.sh that runs its $1 would hide
            # m.py in `source runner.sh m.py` (Viktor 41831 LOW 1). The rest is judged only when the first word is an
            # existing file (script_paths): prose after a ")" made a sentence-ending "." read as source of a file
            # named later in the sentence (an agent-msg heredoc, 2026-11-14), and there the next word is no file.
            idx = next((i for i, w in enumerate(all_words[:2]) if not w.startswith('-')), None)  # `. -- f.sh` too
            first = strip_quotes(all_words[idx]) if idx is not None else ''
            if first:
                tail = all_words[idx + 1:]
                over = clipped or len(all_words) > MAX_ARGS
                groups.append(SourceGroup(first, [strip_quotes(w) for w in tail[:MAX_ARGS] if not w.startswith('-')],
                                          f'source: {len(all_words)} szó, MAX_ARGS {MAX_ARGS}' if len(all_words) > MAX_ARGS
                                          else (f'source: a parancs hosszabb a {ARGS_WINDOW} karakteres ablaknál'
                                                if over else '')))
            continue
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


def script_paths(cmd, cwd, normalised=None):
    """The script files the command runs (resolved, existing regular files), at most MAX_SCRIPTS (an eleventh file
    or more than MAX_BASES directories returns MAX_SCRIPTS + 1 entries: the caller blocks). Raises TooManyArgs."""
    text = expand(normalise(cmd) if normalised is None else normalised)
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
    tries = [0]

    def resolve(c):
        """Add the existing regular files word c names; True if there was one. None: past MAX_TRIES."""
        c = os.path.expanduser(c)
        if not c or c in ('-', '--'):
            return False
        found = False
        for t in ([c] if os.path.isabs(c) else [os.path.join(b, c) for b in bases]):
            tries[0] += 1
            if tries[0] > MAX_TRIES:
                return None
            real = os.path.realpath(t)
            try:
                st = os.stat(real)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                found = True
                if real not in out:
                    out.append(real)
        return found

    for group in groups:
        if isinstance(group, SourceGroup):
            first = resolve(group.first)
            if first is None:
                return [''] * (MAX_SCRIPTS + 1)
            if first:  # bash runs it and hands it the rest
                if group.over:
                    raise TooManyArgs(group.over)
                group = group.rest
            else:
                group = []
        for c in group:
            if resolve(c) is None:
                return [''] * (MAX_SCRIPTS + 1)
        if len(out) > MAX_SCRIPTS:
            break
    return out


def payload_quotes(text):
    """Positions of the quotes that open a payload PAYLOAD_OPEN does not reach, each within its command: the first
    quote after a -c word of any command, every quote after it up to the next ; & | or newline when a shell word
    stands before that -c, and the first quote after watch / tmux new past their bound (Viktor 41831 LOW 2, 41859 A/B,
    41893 LOW 1-2, 41906 LOW 1-2). Linear: command
    ends, quotes and shell words are indexed once; a command whose quotes are all marked is not read again."""
    import bisect
    ends = [i for i, ch in enumerate(text) if ch in CMD_END]
    quotes = [i for i, ch in enumerate(text) if ch in '\'"']
    hard = [i for i, ch in enumerate(text) if ch in ';&|\n']
    shells = [m.start() for m in SHELL_RX.finditer(text)]

    def cmd_end(pos):
        k = bisect.bisect_left(ends, pos)
        return ends[k] if k < len(ends) else len(text)

    def cmd_start(pos):
        k = bisect.bisect_left(ends, pos)
        return ends[k - 1] + 1 if k > 0 else 0

    def next_quote(pos, end):
        k = bisect.bisect_left(quotes, pos)
        return quotes[k] if k < len(quotes) and quotes[k] < end else None
    marks = []
    done = 0
    for c in C_WORD_RX.finditer(text):
        if c.start() < done:  # every quote of this command is marked already
            continue
        end = cmd_end(c.end())
        k = bisect.bisect_left(shells, cmd_start(c.start()))
        if k < len(shells) and shells[k] < c.start():
            j = bisect.bisect_left(hard, c.end())
            end = hard[j] if j < len(hard) else len(text)
            marks += quotes[bisect.bisect_left(quotes, c.end()):bisect.bisect_left(quotes, end)]
            done = end
        else:
            q = next_quote(c.end(), end)
            if q is not None:
                marks.append(q)
    done = 0
    for m in PAYLOAD_OVER_RX.finditer(text):
        if m.start() < done:
            continue
        end = cmd_end(m.end())
        q = QUOTE_RX.search(text, m.end(), end)
        if q:
            marks.append(q.start())
        done = end
    return marks


# A wrapper flag with a word argument broke the chain (Viktor 30044 known gap, 41831 INFO 3, card 3085a683): in
# `sudo -u root security find-...`, `env -u HOME ...`, `timeout -s KILL 5 ...`, `exec -a x ...` the argument word
# ("root") stood where POSITION wants a wrapper, a flag, a number or NAME=value, so the command after it was not in
# command position, and neither the secret rules nor the script rules saw it (measured on 43305327: all allow). Some
# wrappers take positional words before the command too: timeout its duration, script (macOS) its file, ssh its host
# (ssh localhost runs the command here), flock its file, sg its group, chroot its directory.
# wrapper_bounds() walks every such wrapper in command position with this table, without a regex over the arguments
# (one way to read each word: no backtracking), and turns the blank before the command it runs into a command
# boundary (`;`), as payload_quotes() does for a payload; the rules then read that command like any other. A wrapper
# the walk exposes (`sudo -u a env -u B ...`) is found by the next pass; past WRAP_PASSES the gate blocks.
# name: (short flags that take a word, whole flags that take the next word, positional words before the command)
WRAP_ARGS = {
    'sudo': ('CDghprRtTuU', {'--user', '--group', '--close-from', '--chdir', '--host', '--prompt', '--role', '--type',
                             '--command-timeout', '--other-user', '--chroot'}, 0),
    'doas': ('Cu', set(), 0),
    'env': ('uCP', {'--unset', '--chdir'}, 0),
    'timeout': ('sk', {'--signal', '--kill-after'}, 1),
    'nice': ('n', {'--adjustment'}, 0),
    'xargs': ('IJLnPEdsaRS', {'--max-args', '--max-procs', '--delimiter', '--arg-file', '--max-lines', '--replace',
                              '--eof', '--max-chars'}, 0),
    'stdbuf': ('ioe', {'--input', '--output', '--error'}, 0),
    'exec': ('a', set(), 0),
    'time': ('of', {'--output', '--format'}, 0),
    'caffeinate': ('tw', set(), 0),
    'arch': ('', {'-arch'}, 0),
    'script': ('tTEoIOBm', {'--timing', '--log-io', '--log-in', '--log-out', '--log-timing', '--logging-format',
                            '--echo', '--output-limit'}, 1),
    'ssh': ('BbcDEeFIiJLlmOopQRSWw', set(), 1),
    'flock': ('wE', {'--timeout', '--wait', '--conflict-exit-code'}, 1),
    'sg': ('', set(), 1),
    'chroot': ('ugG', {'--userspec', '--groups'}, 1),
    # CHAIN words with no word-taking flag: walked only for their path form (`/usr/bin/nohup cmd`, Viktor 41970 LOW 2)
    'nohup': ('', set(), 0),
    'command': ('', set(), 0),
    'builtin': ('', set(), 0),
    'setsid': ('', set(), 0),
    # card 04d67b39: git's subcommand (GIT_RULES), and the tool xcrun runs (`xcrun security find-...` passed too)
    'git': ('Cc', {'--git-dir', '--work-tree', '--namespace', '--config-env', '--super-prefix'}, 0),
    'xcrun': ('f', {'-sdk', '--sdk', '-toolchain', '--toolchain', '--find'}, 0),  # -f / --find name: only a path
}
# Neither git nor xcrun is a CHAIN word, so the word after their options is marked even when the walk skipped none.
WRAP_ALWAYS = {'git', 'xcrun'}
WRAP_PASSES = 8
_WRAP_NAME = (r'\\?[\'"]?(?:' + WORD + r'*/)?(' + '|'.join(sorted(WRAP_ARGS, key=len, reverse=True))
              + r')[\'"]?(?=[ \t])')
WRAP_RX = re.compile(POSITION + _WRAP_NAME, re.I)  # the secret rules' positions (an opening quote is one)
SCRIPT_WRAP_RX = re.compile(SCRIPT_POSITION + _WRAP_NAME, re.I)  # the script rules' positions
NEXT_WRAP_RX = re.compile(CHAIN + _WRAP_NAME, re.I)  # a wrapper the walk exposed, read where the command starts
# The walk ends at CMD_END. A ")" or a backtick there (`sudo -u $(whoami) ...`) needs no mark: it is a command
# position in the plain text, which is judged too (a separate stop list without them changed no decision: mutant)


def wrap_command_start(text, i, name, qualified=False):
    """Index of the first word of the command the wrapper `name` runs, its words starting at i; None if there is
    none in this command (the walk reaches a ; & | newline, the end, or an unclosed quote), or if the walk skipped
    no word POSITION cannot read (a flag's argument, a positional): there the chain reaches the command already, and
    a mark would only cost a pass (26 x `env a=b` needed 26). A wrapper written with its path (`qualified`:
    `/usr/bin/env security ...`) is no CHAIN word, so its command is always marked (Viktor 41970 LOW 2). -1 past
    MAX_ARGS words: the caller blocks (a walk to the end of every command was quadratic, 20 000 x `sudo -p "` ran
    past 5 s; stopping unread would let the command behind 65 flags through). A backslash takes the next character
    into the word: `sudo -p a\\ b` is one word, as for the shell (Viktor 41970 LOW 1)."""
    short, whole, positional = WRAP_ARGS[name]
    n = len(text)
    need_arg = flags_done = False
    skipped = name in WRAP_ALWAYS
    for _ in range(MAX_ARGS + 1):
        while i < n and text[i] in ' \t':
            i += 1
        if i >= n or text[i] in CMD_END:
            return None
        start = i
        while i < n and text[i] not in ' \t' and text[i] not in CMD_END:
            if text[i] in '\'"':  # a quoted word is one word: `sudo -p 'a b' ...`
                j = text.find(text[i], i + 1)
                if j < 0:
                    return None
                i = j + 1
            elif text[i] == '\\':  # an escaped blank or separator is part of the word: `sudo -p a\ b ...`
                i += 2
            else:
                i += 1
        if need_arg:
            need_arg = False
            skipped = True
            continue
        t = strip_quotes(text[start:i])
        if not flags_done and t == '--':
            flags_done = True
            continue
        if not flags_done and t.startswith('-'):
            if t in whole:
                need_arg = True
            elif not t.startswith('--'):  # -uroot carries its word, -Eu takes the next one
                k = next((p for p, ch in enumerate(t[1:], 1) if ch in short), None)
                need_arg = k == len(t) - 1
            continue
        if positional:
            positional -= 1
            skipped = True
            continue
        return start if skipped or qualified else None
    return -1


def wrapper_bounds(text, rx):
    """text with the blank before each wrapped command made a `;` (see WRAP_ARGS); None past WRAP_PASSES. A wrapper
    right at the command another one runs (`sudo -u a env -u B ...`) is walked in the same pass (linear: 20 000 x
    `sudo -u a ` is one pass); a later pass only finds what a mark exposed elsewhere. None also when a walk runs past
    MAX_ARGS words.
    A chain is walked once per pass (`reach`, Viktor 41970 LOW 3, his tested proposal): a quote is a command
    position, so in `sudo -u "a b" sudo -u "a b" ...` finditer found every later wrapper of the chain again and each
    walk ran to the chain's end (4 000 x took 6 s). A command substitution in a flag's argument
    (`sudo -u "$(env -u X security ...)" ls`) still blocks (tested, one pass too)."""
    for _ in range(WRAP_PASSES):
        chars = None
        reach = 0  # a quote makes every later wrapper of a chain a command position: walk each chain once
        for m in rx.finditer(text):
            if m.start() < reach:
                continue
            i, name = m.end(), m.group(1).lower()
            qualified = m.start(1) > 0 and text[m.start(1) - 1] == '/'  # `/usr/bin/env cmd`: CHAIN does not read a path
            while True:
                k = wrap_command_start(text, i, name, qualified)
                if k is None:
                    break
                if k < 0:
                    return None
                reach = k
                if text[k - 1] in ' \t':
                    chars = chars or list(text)
                    chars[k - 1] = ';'
                nxt = NEXT_WRAP_RX.match(text, k)
                if not nxt:
                    break
                i, name = nxt.end(), nxt.group(1).lower()
                qualified = nxt.start(1) > 0 and text[nxt.start(1) - 1] == '/'
        if chars is None:
            return text
        text = ''.join(chars)
    return None


def script_hits(cmd, cwd):
    """Rule names for inline interpreter code and for the files the command runs."""
    found = []
    if INTERP_RX.search(normalise(cmd)) and literal_hit(cmd):
        found.append('script-inline')
    # the payload a quote opens past PAYLOAD_OPEN's reach: that quote becomes a command boundary (`;`), so the
    # script rules read the payload as a command; nothing else changes
    text = normalise(cmd)
    marks = payload_quotes(text)
    if marks:
        chars = list(text)
        for i in marks:
            chars[i] = ';'
        text = ''.join(chars)
    # `sudo -u root python3 m.py` (card 3085a683): the files of the text with the wrapped commands' boundaries are
    # judged TOO, as in hits(): a mark only ever adds a file
    bounded = wrapper_bounds(text, SCRIPT_WRAP_RX)
    if bounded is None:
        return found + ['wrapper-unread']
    try:
        paths = script_paths(cmd, cwd, text)
        if bounded != text:
            paths += [p for p in script_paths(cmd, cwd, bounded) if p not in paths]
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
        if hits(body, script=True) or literal_hit(body):
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
