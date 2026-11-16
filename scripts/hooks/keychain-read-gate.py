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
wrapper and keyword words env, sudo, doas, sandbox-exec, exec, command, nohup, time, nice, xargs, caffeinate, arch,
builtin, timeout, stdbuf, setsid, if, then, else, elif, do, while, until, `!`, their flags, numbers (`timeout 5`,
`nice -n 5`), VAR=value assignments and redirections (`>/dev/null`, `2> err`, `</dev/null`, `>&2`; Viktor 41970
INFO 5, card 15896271). The & of a redirection (`>&2`, `<&3`, `&>x`) is no command end: `x >&2 security ...`
runs x with the word as an argument, and passes. A path before it counts (`/usr/bin/security`). Case-insensitive: the default macOS volume
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
The macOS wrappers that run a command after their own words are walked too (Viktor 41970 LOW 4, card 15896271):
`sandbox-exec -p <profile> cmd`, `lockf -t 5 <file> cmd`, `launchctl asuser <uid> cmd` (any launchctl subcommand's
third word is read as a command: fail-closed; `launchctl submit -l <label> [-o|-e <file>] -- cmd`; with `-p` it blocks),
`login -fp <user> cmd`.
Not seen: everything listed above under "does not see"; a wrapper not in WRAP_ARGS whose flag takes a word, and a
program that runs a command from its own script language (`expect -c 'spawn ...'`; su's `-c` and `script <file> cmd`
block, measured by Viktor 42251), and a quoted string that starts with a wrapped call blocks like one that
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
    words: more words, or a command running past ARGS_WINDOW, blocks unread ('script-too-many-args', LOW 1). Except
    (card 31045f4d, Viktor 43235): for python, ruby, perl and php the first plain word after options the gate knows
    is the script, the words after it are its argv (data: `python3 stat.py regiszter.jsonl` passes), a directory
    there is judged by its __main__.py; and for `bash <this repo's agent-msg.sh> ...` its words are the message
    (resolved from every directory the command may run in: a look-alike keeps the full reading). After
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
  with spaces, an interpreter whose own name a substitution makes (`$(echo python3) m.py`; Viktor 43662 INFO 1), a Ruby %w list, a payload a quote opens after other commands (`command '...'`, `time '...'` run a
  command literally named so, which fails). A wrapped script (`sudo -u root python3 m.py`, `ssh localhost python3
  m.py`, `sg staff 'python3 m.py'`) is read like any other (card 3085a683; for ssh the file is looked up here, which
  is right for localhost and a fail-closed guess for a remote host). The gate's own test assembles its fixtures at
  run time, so running the test is not blocked.
  Shell structure (card fae0712e): the script rules take quotes, heredoc bodies, substitutions and simple commands
  from the shared lexer scripts/lib/shell_lex.py (see lexer_view): a separator inside a quoted argument of a data
  command (echo, printf, grep, test ...; unless the text may redefine it: alias, a function, eval, source, PATH=)
  is no command boundary (`echo 'x; ./m.py'` passes), every command inside
  a substitution and every word after a shell's -c are read as commands (`echo \\`./m.py\\``, `bash -c ./m.py`
  block). A text the lexer does not fully read (an unterminated quote, heredoc or substitution, past its bounds)
  takes the old path. A backslash-newline that ends a comment or follows an escaped backslash is no line join
  (lexer_normalise; hits() judges that text too). On the lexer path (card 31045f4d) every quoted-delimiter heredoc
  into a data recipient (curl -d @-, git commit -F -, this repo's agent-msg.sh) is blanked for the script rules
  when only allowlisted steps stand before it (lexer_data_spans), and in a quoted heredoc into python / node / ruby
  / perl / php a "(" after a blank is prose, not a subshell (nonshell_prose_masked).
  Still blocks, accepted (card 31045f4d): a quoted path after "(" in an interpreter body (`open('data.jsonl')`
  reads like `os.system('./x.sh')` and `exec(open('x').read())`); pass the data file as an argument instead.
  Seen while measuring, not changed here: an interpreter's words end at a backtick, so `python3 \\`true\\` m.py` passes
  (on main too). A data file an argv-reading script runs (`python3 stat.py m.py` with exec(open(sys.argv[1]))) is the
  same boundary as "a file the script builds": not seen.
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

WRAPPERS = (r'(?:env|sudo|doas|sandbox-exec|exec|command|nohup|time|nice|xargs|caffeinate|arch|builtin|timeout|stdbuf|setsid'
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
# A redirection is a token too (`>/dev/null security ...`, `2> err`, `>&2`; Viktor 41970 INFO 5). Its target never
# starts with < or >, so `>>x` reads one way only (`>>` + `x`, not `>` + `>x`): two ways per token backtracked
# exponentially (the 30044 lesson).
REDIR = r'\d*(?:&?>>?\|?|<{1,3}-?)&?[ \t]*[^\s;&|(){}`\'"<>]' + WORD + r'*'
# An & is a position only as a command end: in `>&2`, `<&3`, `&>x` it belongs to a redirection (bash reads it so),
# and with REDIR in CHAIN every such & rescanned the rest of a `>&2 >&2 ...` run (2 000 x ">&2 " ran into the 6 s
# watchdog, measured 2026-11-14; card 15896271).
AMP = r'(?<![<>])&(?!>)'
PIPE = r'(?<!>)\|'  # a | right after > is the noclobber redirection `>|f`, no command end
CHAIN = (r'(?:(?:' + WRAPPERS + r'\b|!|-(?!(?:exec|execdir|ok)(?=\s))' + WORD + r'*|' + REDIR + r'|[+.]?\d[\w.]*|\w+='
         + WORD + r'*)[ \t]+)*')
POSITION = r'(?:^|[;(){}\n`\'"]|' + PIPE + r'|' + AMP + r'|\$\(|\s-(?:exec|execdir|ok)(?=\s))[ \t]*' + CHAIN
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
SCRIPT_POSITION = r'(?:^|[;(){}\n`]|' + PIPE + r'|' + AMP + r'|\$\(|\s-(?:exec|execdir|ok)(?=\s)|' + PAYLOAD_OPEN + r')[ \t]*' + CHAIN
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
_SEG_RX = re.compile(r'\$\(|[;(){}\n`\'"]|' + PIPE + r'|' + AMP)  # the & and | of a redirection do not split
_REDIR_WORD_RX = re.compile(r'\d*(?:&?>>?\|?|<{1,3}-?)&?(\S+)?')
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
        rd = _REDIR_WORD_RX.fullmatch(w)
        if rd:  # a redirection before the command: `HOME=/x 2>&1 git fetch`, `env >/dev/null HOME=/x git ...`
            i += 1 if rd.group(1) else 2
        elif a:
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
            # Only the LEADING option words count (a bash `declare NAME=1 -x` takes -x for a name), `export -n` and
            # `declare +x` take the export away, `readonly` never exports (measured, bash 3.2 and zsh; Viktor 42224 LOW 1)
            opts, expands = [], False
            for x in tail:
                if not re.fullmatch(r'[-+][a-zA-Z]+', x):  # a name, a value, or `--` ends the options
                    # `export $N NAME=1`: $N may be -n (a backtick or a quote never reaches here: _SEG_RX cuts there)
                    expands = '$' in x and '=' not in x
                    break
                opts.append(x)
            # Only x, g, r keep an export (Dave on Viktor 42224, measured bash 3.2 and zsh): any other letter either
            # takes it away (`export -n`) or is an invalid option there (`declare -nx`, `export -q`, `export -f`: the
            # whole declaration fails, nothing is set), so it does not count as one; rare valid ones (-ix, -tx) block.
            unexport = expands or any(o[0] == '+' and 'x' in o or o[0] == '-' and set(o[1:]) - set('xgr') for o in opts)
            exports = not unexport and base != 'readonly' and (
                base == 'export' or any(o[0] == '-' and 'x' in o for o in opts))
            for x in tail:
                name, eq, value = x.partition('=')
                if base == 'unset':
                    if name in OVERRIDE_VARS:
                        st['sets'] = True
                    elif name == 'GIT_CONFIG_NOSYSTEM':
                        st['nosys'] = False
                elif name == 'GIT_CONFIG_NOSYSTEM' and not exports:
                    # not exported: an unexport, or a false value, ends the exemption; a true value or no value keeps an
                    # earlier export's (declare keeps the export attribute; Viktor 42224 D05, D07, D08)
                    st['nosys'] = False if unexport or eq and value.lower() not in _TRUE else st['nosys']
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


def normalise(cmd, joined=False):
    if not joined:
        cmd = cmd.replace('\\\n', '')                # line continuation
    cmd = re.sub(r'\\([A-Za-z])', r'\1', cmd)       # sec\urity -> security
    cmd = re.sub(r'(?<=\w)(?:\'\'|"")(?=\w)', '', cmd)  # sec''urity -> security
    cmd = re.sub(r'\$\{IFS\}|\$IFS\b', ' ', cmd)        # security${IFS}dump-keychain -> a space
    return cmd


# card d11364a4 (Viktor f526b8c6 verdict, pre-existing LOW): a quoted or escaped command name where a shell -c payload
# starts (`bash -c "\"security\" dump-..."`, `sh -c 'sec""urity ...'`, `bash -c "\\security ..."`) was in no pass:
# the outer quote's escaping (\" \\) hid the name from the first, and the quote-free second pass loses the payload's
# command position. The payload is now taken out with bash's own quote rules and judged as a command of its own.
PAYLOAD_DEPTH = 3     # a payload in a payload in a payload; one with a payload still unread blocks ('payload-too-deep')
MAX_PAYLOADS = 64     # distinct payloads read again per text; past it the gate blocks ('payload-unread')
PAYLOAD_QUOTED = re.compile(r'[\'"\\]')
_DQ_BODY = re.compile(r'(?:[^"\\]|\\.)*', re.S)               # up to the closing " (or the end: judged anyway)
_DQ_UNESCAPE = re.compile(r'\\([\\"$`])|\\\n')                # what bash takes off inside "..."
# card aeee72df (Viktor 42941 LOW 2): a payload is the whole shell WORD its quote opens, not the first piece: bash
# goes on after the closing quote, so `bash -c ''\''sec'\''urity dump-...'` runs `'sec'urity dump-...`, and the first
# piece alone ('') read nothing. One piece per match, one way to read each: '...' as written, "..." and $"..." with the
# _DQ_UNESCAPE escapes taken off, $'...' decoded (_ANSI_C), \x as x (backslash-newline: nothing), a plain run as
# written. An unquoted blank or operator ends the word (`$(` too: what it runs is the outer passes' to judge).
_PIECE_RX = re.compile(r"'([^']*)'?|\$?\"((?:[^\"\\]|\\.)*)\"?|\$'((?:[^'\\]|\\.)*)'|\\(.?)|([^\s;&|<>()'\"\\$]+|\$)",
                       re.S)  # an unclosed $'... is a $ and an unclosed '...: read to the end like any other
_ANSI_C = re.compile(r'\\(?:x([0-9A-Fa-f]{1,2})|([0-7]{1,3})|(.))', re.S)
_ANSI_ESC = {'a': '\a', 'b': '\b', 'e': '\x1b', 'E': '\x1b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t', 'v': '\v',
             '\\': '\\', "'": "'", '"': '"', '?': '?'}


def _ansi_c(m):
    x, o, ch = m.groups()
    if x or o:
        return chr(int(x, 16) if x else int(o, 8) & 0xff)
    return _ANSI_ESC.get(ch, '\\' + ch)  # bash keeps an unknown escape as written


def shell_word(text, i):
    """(value, end) of the shell word starting at i, its quoted, escaped and plain pieces joined as bash joins them."""
    out = []
    while i < len(text):
        m = _PIECE_RX.match(text, i)
        if not m:
            break
        sq, dq, ansi, esc, plain = m.groups()
        out.append(sq if sq is not None else _DQ_UNESCAPE.sub(lambda e: e.group(1) or '', dq) if dq is not None
                   else _ANSI_C.sub(_ansi_c, ansi) if ansi is not None else ('' if esc == '\n' else esc)
                   if esc is not None else plain)
        i = m.end()
    return ''.join(out), i


# card aeee72df (Viktor 42941 LOW 4): a shell reads its stdin as a script, so `echo '"sec"urity dump-...' | bash` and
# `bash <<< '"sec"urity dump-...'` run the quoted name the -c forms already block. The text of a pipeline that feeds
# a shell (a shell word, wrappers before it allowed, right after its |), and the word after a <<< in a command with
# a shell word in it (`<<< '...' bash` runs it too), are payloads too. A heredoc into a shell needs nothing: a body
# line starts after a newline (a command position) and the quote-free second pass reads it.
_SHELL_NAME = r'(?:(?:bash|sh|zsh|dash|ksh|fish|csh|tcsh|ash|rbash|pwsh)\d*|\$\{?(?:SHELL|BASH)|\$0)'  # a } or quote after: alone
# The shell word stands alone: no word character, dot or dash glued to it (bashful, x.sh, my-bash), anything else
# around it is a boundary (wider than SHELL_RX: here only a payload more is read).
_ALONE = r'[\w.-]'
STDIN_SHELL_RX = re.compile(r'(?<!' + _ALONE + r')' + _SHELL_NAME + r'(?!' + _ALONE + r')')
# |& pipes too (zsh, bash 4); || and >| do not (the lookbehind rejects the second | of a ||, and the first one is
# followed by no shell word)
# card 74586987 (Viktor 42794 INFO): `source /dev/stdin` and `. /dev/fd/0` read the pipe as a script too (measured
# 2026-11-16 on the live gate: `echo ./measure.py | source /dev/stdin` passed)
STDIN_SOURCE = r'(?:source|\.)[ \t]+[\'"]?(?:/dev/stdin|/dev/fd/0|/proc/self/fd/0)[\'"]?(?![\w./-])'
PIPE_SHELL_RX = re.compile(r'(?<![>|])\|&?[ \t]*' + CHAIN + r'(?:[\'"]?(?:' + WORD + r'*/)?' + _SHELL_NAME
                           + r'(?!' + _ALONE + r')|' + STDIN_SOURCE + r')')
HERE_STRING_RX = re.compile(r'<<<[ \t]*')
PIPELINE_START = ';&\n()`'  # a | does not end the pipeline the shell reads


def stdin_payloads(text):
    """(value, verbatim) of each word a shell reads on stdin: every quoted word of a pipeline that ends in `| <shell>`
    (the quotes walked from the start of the text, so a quote of an earlier word is not taken for an opening one),
    and the word after a <<< whose command has a shell word in it. verbatim: the value stands as written right
    after the word's opening quote (a command position the outer passes judge) or is one plain word (no blank, so
    no rule can match it). Linear: each quote and each word once."""
    import bisect
    pipes = [m.start() for m in PIPE_SHELL_RX.finditer(text)] if '|' in text else []
    heres = [m for m in HERE_STRING_RX.finditer(text)] if '<<<' in text else []
    if not pipes and not heres:
        return []
    starts = [i for i, ch in enumerate(text) if ch in PIPELINE_START]

    def begin(pos, stops):
        k = bisect.bisect_left(stops, pos)
        return stops[k - 1] + 1 if k > 0 else 0

    def word(s):
        w, e = shell_word(text, s)
        return (w, text.startswith(w, s + 1) if text[s:s + 1] in ('"', "'") else text.startswith(w, s)), e
    words = []
    if heres:
        ends = [i for i, ch in enumerate(text) if ch in CMD_END]
        shells = [m.start() for m in STDIN_SHELL_RX.finditer(text)]
        for m in heres:
            k = bisect.bisect_left(shells, begin(m.start(), ends))
            j = bisect.bisect_left(ends, m.end())
            if k < len(shells) and shells[k] < (ends[j] if j < len(ends) else len(text)):  # before or after the <<<
                words.append(word(m.end())[0])
    if pipes:
        ranges = [(begin(p, starts), p) for p in pipes]
        lo = [r[0] for r in ranges]
        last = -1
        for q in (i for i, ch in enumerate(text) if ch in '\'"'):
            if q <= last or (q > 0 and text[q - 1] == '\\'):
                continue
            k = bisect.bisect_right(lo, q) - 1
            wv, end = word(q - 1 if text[q] == "'" and q > 0 and text[q - 1] == '$' else q)
            last = end - 1
            if k >= 0 and q < ranges[k][1]:
                words.append(wv)
    return words


# card 74586987 (Viktor 42794 INFO, measured 2026-11-16 on the live gate d85d82e3): what a shell reads on its stdin
# was judged as text only, and only its QUOTED words (stdin_payloads). `echo ./measure.py | bash`, `printf %s
# './measure.py' | tee /dev/null | sh`, `echo python3 measure.py | sh`, `echo -n ./measure.py | source /dev/stdin`
# ran the script unread, and `echo security dump-keychain | bash` (no quote) passed too. Now every word of the
# pipeline that feeds a shell is read, decoded as bash decodes it:
#   lines: each word alone, and each command's words after its name joined by a blank (what echo prints), a
#          command line of its own: hits_in() judges them (the binary and a subcommand) and the script rules read
#          them (`./x.py`, `python3 x.py`, `cd d; ./x.py`, a $X the text assigns);
#   words: each blank-separated piece of each word, a path the script rules look up as a file (`printf 'python3
#          %s\n' x.py | bash` runs x.py, which no line names at a command position).
# Over-read on purpose, as everywhere in this gate: a word in such a pipeline that names a keychain-reading file
# blocks, run or not (`echo hi measure.py | bash`). The lookups count against MAX_TRIES (past it: block).
# Not seen (as everywhere in this gate): a name the pipeline COMPUTES (printf's format gluing pieces, `printf %s ./mea
# sure.py`, rev, base64 -d, a substitution's output): only the words as written are read.
# A group before the pipe is read whole: `(echo ./x.py) | bash` and `{ echo ./x.py; } | bash` (the pipeline's start
# moves to the opener that matches the ")" or "}" right before the pipe; an unmatched closer reads from the text's
# start). Linear: the pipes with the same start are read once, up to the last of them.
_GROUP_CLOSE = {')': '(', '}': '{'}
_BRACE_AFTER_RX = re.compile(r'[ \t]*\}')  # no newline: a newline is a stop of its own (a run of them stays linear)
_SEG_STOP = ';&|\n(){}<>'


def _group_openers(text):
    """For each ")" / "}" position, the position of the opener that matches it (one stack pass; quotes are not
    tracked, so a bracket in a quote may pair wrongly: that only moves the start, and an unmatched closer maps to
    -1, the text's start: never a shorter read than without the group)."""
    stack, match = [], {}
    for i, ch in enumerate(text):
        if ch in '({':
            stack.append((ch, i))
        elif ch in _GROUP_CLOSE:
            while stack and stack[-1][0] != _GROUP_CLOSE[ch]:
                stack.pop()
            match[i] = stack.pop()[1] if stack else -1
    return match


def stdin_pipelines(text):
    """(lines, words) of every pipeline that feeds a shell on stdin (see the block above)."""
    import bisect
    pipes = [m.start() for m in PIPE_SHELL_RX.finditer(text)] if '|' in text else []
    if not pipes:
        return [], []
    stops = [i for i, ch in enumerate(text) if ch in PIPELINE_START]
    openers = None
    memo = {}  # a position -> the start it leads to: each position is walked once (a chain of groups stays linear)
    brace = {}  # a stop -> the "}" right after it (blanks between), or None
    spans = {}
    for p in pipes:
        b, path = p, []
        while True:  # the pipeline's start, moved past a group that closes right before it
            if b in memo:
                b = memo[b]
                break
            path.append(b)
            k = bisect.bisect_left(stops, b)
            s = stops[k - 1] if k > 0 else -1
            closer = None
            if s >= 0 and text[s] == ')':
                closer = s
            else:
                if s not in brace:  # once per stop: many pipes after one stop do not rescan its blanks
                    m = _BRACE_AFTER_RX.match(text, s + 1)
                    brace[s] = m.end() - 1 if m else None
                if brace[s] is not None and brace[s] < b:
                    closer = brace[s]
            if closer is None:
                b = s + 1
                break
            if openers is None:
                openers = _group_openers(text)
            o = openers.get(closer, -1)
            if not 0 <= o < b:
                b = 0
                break
            b = o
        for x in path:
            memo[x] = b
        spans[b] = max(spans.get(b, p), p)
    merged = []  # overlapping spans (a pipe inside a group that is piped again) read once, as their union
    for b, p in sorted(spans.items()):
        if merged and b <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], p)
        else:
            merged.append([b, p])
    lines, words = [], []
    for b, p in merged:
        seg = text[b:p]
        cmds, cur, i = [], [], 0
        while i < len(seg):
            ch = seg[i]
            if ch in ' \t' or ch in _SEG_STOP:
                if ch in ';&|\n(){}' and cur:
                    cmds.append(cur)
                    cur = []
                i += 1
                continue
            v, e = shell_word(seg, i)
            if e <= i:
                i += 1
                continue
            cur.append(v)
            i = e
        if cur:
            cmds.append(cur)
        for cw in cmds:
            lines.extend(cw)
            if len(cw) > 1:
                lines.append(' '.join(cw[1:]))
            for v in cw:
                words.extend(v.split())
    # each once: a word repeated in many pipelines is one lookup, not one per pipeline (MAX_TRIES)
    return list(dict.fromkeys(lines)), list(dict.fromkeys(words))


def payload_texts(text, script=False):
    """The text of each payload a quote opens (payload_quotes(), PAYLOAD_OPEN): '...' as written, "..." with \\ \" \\$
    \\` and backslash-newline unescaped, as bash reads it. An escaped opening quote (`do shell script \\"...\\"`) is
    left to the payload around it. A quote inside an earlier payload belongs to it, so the walk is linear. Only a
    payload with a quote or a backslash in it is returned: one without stands verbatim after its opening quote (a
    command position) in the text the outer passes judge already, so reading it again adds nothing (and 30 000
    `-c 'a'` paddings stay fast). Each distinct text once; None past MAX_PAYLOADS.
    Card aeee72df: the whole shell word the quote opens is a payload too (shell_word(), LOW 2), when it is more than
    its first piece, and so is what a shell reads on stdin (stdin_payloads(), LOW 4). Both only add texts: the walk
    and the first-piece payloads are the ones before (a mark only ever adds a block)."""
    starts = set(payload_quotes(text))
    starts.update(m.end() - 1 for m in re.finditer(PAYLOAD_OPEN, text))
    out, seen, last, word_end = [], set(), -1, 0

    def add(p, verbatim):
        if p in seen or (verbatim and not PAYLOAD_QUOTED.search(p)):
            return True
        if len(out) == MAX_PAYLOADS:
            return False
        seen.add(p)
        out.append(p)
        return True
    marks = sorted(starts)
    for q in marks:
        if q <= last or (q > 0 and text[q - 1] == '\\'):
            continue
        if text[q] == "'":
            e = text.find("'", q + 1)
            e = len(text) if e < 0 else e
            p = text[q + 1:e]
        else:
            e = _DQ_BODY.match(text, q + 1).end()
            p = _DQ_UNESCAPE.sub(lambda m: m.group(1) or '', text[q + 1:e])
        last = e
        if not add(p, True):
            return None
    # The words keep a place of their own: the piece walk above reads $'it\'s' as two pieces ('it\' and an opening
    # quote) and can run past the next word's first quote. Each word once, from its first mark (a $'...' from its $).
    for q in marks:
        if q < word_end or (q > 0 and text[q - 1] == '\\'):
            continue
        w, word_end = shell_word(text, q - 1 if text[q] == "'" and q > 0 and text[q - 1] == '$' else q)
        if not add(w, text.startswith(w, q + 1)):
            return None
    # card 74586987 (replay r2): a "| bash" in a data heredoc's body is prose, no pipeline (data_body_pipes_masked;
    # the same length, so every position stays; not on a script file's text, which is not lexed)
    src = text
    if not script and '|' in text and '<<' in text:
        src = data_body_pipes_masked(text, lex_or_none(text), None)
    for w, verbatim in stdin_payloads(src):
        if not add(w, verbatim):
            return None
    return out


def hits(cmd, script=False, _depth=0):
    """Rule names the text matches; a script file's text (script=True) is not judged by GIT_RULES."""
    found = _hits(cmd, script)
    if _depth >= PAYLOAD_DEPTH:
        # card aeee72df (Viktor 42941 LOW 1): a payload this deep is not read again, so one still in it blocks, as
        # past MAX_PAYLOADS (fail-closed); before, it was left to the outer passes, and a 4-deep quoted name ran
        if payload_texts(cmd, script) != []:
            found.append('payload-too-deep')
    else:
        # A hook past its timeout does not block. Reading a payload again costs about what the outer text cost, so it
        # starts only inside half the budget; past it (or past the budget during the payloads) the gate blocks.
        slow = found + ([] if 'payload-too-slow' in found else ['payload-too-slow'])
        if time.monotonic() - T0 > script_budget() / 2:
            return slow if PAYLOAD_QUOTED.search(cmd) and payload_texts(cmd, script) != [] else found
        payloads = payload_texts(cmd, script)
        if payloads is None:
            return found + ([] if 'payload-unread' in found else ['payload-unread'])
        for p in payloads:
            if time.monotonic() - T0 > script_budget():
                return slow
            found += [n for n in hits(p, script, _depth + 1) if n not in found]
    return found


def _hits(cmd, script=False):
    """The passes on one text, its payloads not read again (hits() does that)."""
    found = hits_in(normalise(cmd), script)
    # card 74586987: the words a shell reads on stdin, quoted or not, as command lines of their own (stdin_pipelines)
    # (the pipes of a data heredoc's body are prose: data_body_pipes_masked; not on a script file's text, which is
    # not lexed, see below)
    src = cmd
    if not script and '|' in cmd and '<<' in cmd:
        src = data_body_pipes_masked(cmd, lex_or_none(cmd), None)
    lines = stdin_pipelines(normalise(src))[0]
    if lines:
        found += [h for h in hits_in('\n'.join(lines), script) if h not in found]
    # card fae0712e: normalise() joins every backslash-newline, also one whose backslash ends a comment or is half of
    # an escaped backslash, and the next line (a command for the shell) became part of a word: `: |#\` + newline +
    # `security dump-keychain` passed. The command text with only the shell's own joins (lexer_normalise) is judged TOO,
    # so this only adds a block; not a script file's text (a 1 MB file would be lexed on every read), and only when
    # the lexer fully reads the text (no problem, inside its bounds).
    if not script and '\\\n' in cmd:
        lx = lex_or_none(cmd)
        if lx is not None:
            alt = lexer_normalise(cmd, lx['cls'], 0, len(cmd))
            if alt != normalise(cmd):
                found += [h for h in hits_in(alt, script) if h not in found]
    return found


def hits_in(text, script=False):
    """hits() on a normalised text."""
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
# `-mmod`, and after python's no-argument flags `-Imod` / `-Bqmmod` (card 70c94516: the old `-m...` only at the start
# let `-Imevil` pass); read on the word with its quotes removed (`-m"evil"`)
# (a name, a quote or a substitution after the m: `-m)` is the end of `$(echo -m)`, no module)
MODULE_JOINED_RX = re.compile(r'-[bBdEhiIOPqsSuvVx]*m([A-Za-z_\'"$`].*)')
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
# A redirection right after the path ends it too (`./m.py>>log`, `./m.py<in`: the shell runs m.py; found by the
# differential fuzz, card fae0712e)
DIRECT_RX = re.compile(SCRIPT_POSITION + r'''['"]?((?:\.{1,2}/|/|[\w.-]+/)[^\s'";|&<>()`$]*)['"]?(?=\s|$|[;&|)<>])''')
# Card 70c94516 (Viktor 43662 LELET 2): the whole path word up to a blank, when DIRECT_RX stops at a quote or a
# substitution inside it (`./x$(true).sh`, `./"ev"il.sh` run x.sh / evil.sh); read with word_forms' rules
DIRECT_WORD_RX = re.compile(SCRIPT_POSITION + r'''(['"]?(?:\.{1,2}/|/|[\w.-]+/)[^\s'";|&<>()`$]*['"`$]\S*)''')
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


def shell_unquote(word):
    """Card 70c94516 (Viktor 43662 LELET 1): bash's quote removal over the WHOLE word, not only an outer pair:
    `"ev"il.py`, `e"vil".py`, `'ev'il.py` and `$'ev'il.py` all run evil.py. The pieces are read by shell_word (the
    payload reader's rules: '...', "..." / $"..." unescaped, $'...' decoded, \\x as x); a character no piece reads
    (a paren of a substitution, an operator) is kept as written, so the result is one more name to look up, never
    fewer (the caller keeps strip_quotes' form as well)."""
    out, i = [], 0
    while i < len(word):
        value, j = shell_word(word, i)
        out.append(value)
        if j == i:
            out.append(word[i])
            j = i + 1
        i = j
    return ''.join(out)


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
    if CHDIR_OTHER_RX.search(text) or (ENV_WORD_RX.search(text) and ENV_CHDIR_RX.search(text)) or len(CD_WORD_RX.findall(text)) > len(CD_RX.findall(text)):
        return Bases(bases, unknown=True)  # a directory change the lines above did not follow
    return Bases(bases)


class Bases(list):
    """cd_bases result; unknown = the command also changes directory in a way cd_bases cannot follow (pushd, `cd $(..)`,
    `cd ${PWD}/x`, a bare `cd`, `env -C`), so "this agent-msg.sh is ours in every directory" is not known (Viktor 43304 A)."""
    def __init__(self, items=(), unknown=False):
        super().__init__(items)
        self.unknown = unknown


CD_WORD_RX = re.compile(r'(?<![\w./-])cd(?![\w./-])')
CHDIR_OTHER_RX = re.compile(r'(?<![\w./-])(?:pushd|popd|chdir)(?![\w./-])')
ENV_WORD_RX = re.compile(r'(?<![\w./-])env(?![\w./-])')
ENV_CHDIR_RX = re.compile(r'(?<=[ \t])(?:-\w*C|--chdir)(?=[ \t=]|$)')  # two linear scans, not one nested pattern (ReDoS)


class AgentMsgGroup:
    """`bash scripts/agent-msg.sh to from "message"` (card 31045f4d, Klodel 43233): when the script is THIS repo's
    agent-msg.sh in every directory the command may run it from, its words are the message (data), as for a
    heredoc into it; otherwise (a look-alike, a runner.sh) every word is judged, as for any bash script."""
    def __init__(self, first, rest, over):
        self.first, self.rest, self.over = first, rest, over


AGENT_MSG_SHELL_RX = re.compile(r'(?:(?:/usr)?/bin/)?(?:bash|sh)')


def agent_msg_everywhere(word, bases):
    """word (a plain path) is this repo's agent-msg.sh from every base it exists in, and exists in one."""
    if not PLAIN_SCRIPT_RX.fullmatch(word) or os.path.basename(word) != 'agent-msg.sh' or len(bases) > MAX_BASES \
            or getattr(bases, 'unknown', False):
        return False  # (past MAX_BASES cd_bases stopped collecting: not every directory is known)
    cands = [word] if os.path.isabs(word) else [os.path.join(b, word) for b in bases]
    found = [os.path.realpath(c) for c in cands if os.path.exists(c)]
    return bool(found) and all(f == AGENT_MSG for f in found)


class TooManyArgs(Exception):
    """An interpreter call with words the gate does not read (past MAX_ARGS or ARGS_WINDOW): the caller blocks."""


class SourceGroup:
    """`source f a b`: the rest (a, b) is judged only when f is an existing regular file; `over` names why the rest
    is not all read (past MAX_ARGS or ARGS_WINDOW), and then such a call blocks. Card 70c94516: `firsts` are the
    readings of f (as written, quotes removed, substitutions removed, the next word when f may print nothing); the
    rest is judged when any of them is a file."""
    def __init__(self, firsts, rest, over):
        self.firsts, self.rest, self.over = firsts, rest, over


# `>`, `2>>`, `>&`, `&>`, `>|` alone (target next) or with it; the & and | of a redirection no longer end the words
# (_CALL_END_RX, Viktor 42251 LOW 2), so `python3 2>&1 ./x.py` and `python3 >& out.txt x.py` read x.py.
OUT_REDIR_RX = re.compile(r'(?:\d*>>?[&|]?|&>>?)(\S+)?$')
# the end of an interpreter call's words: a ; newline ) backtick, a | or & that is no part of a redirection (`>&2`, `2>&1`, `&>f`, `>|f`)
_CALL_END_RX = re.compile(r'[;\n)`]|' + PIPE + r'|' + AMP)


# Card 31045f4d (Viktor 43235/43236, Klodel 43233): for python, ruby, perl and php the FIRST word that is no option is
# the script, and the words after it are its arguments (sys.argv, ARGV, @ARGV, $argv): data the script may read, not a
# file the interpreter runs. A data file named there (`python3 stat.py regiszter.jsonl`, whose text names the blocked
# call in prose) blocked as 'script-file'. This gives no more than writing the path into the script already does (B/C
# in Viktor 43235: allowed today); the gate is no wall against a script that reads and runs a file (see "Not seen").
# Only when every word before the script is an option the gate knows, with no argument or with a known argument:
#   python: clusters of the no-argument flags below; -W / -X with their argument (next word or attached: -Wignore);
#   ruby, perl, php: no option at all (ruby -r and perl -M preload code, php -c / -d set an ini: not read here).
# Anything else keeps the old walk (every existing file judged): node -r preloads, bash/sh/source run their $1.
DATA_ARGV_RX = re.compile(r'python[\d.]*|ruby|perl|php', re.I)
PY_NOARG = frozenset('bBdEhiIOPqsSuvVx')
PY_WITHARG = frozenset('WX')
PY_ATTACHED_RX = re.compile(r'-[^-cmWX][^cmWX]*[WX]|-[WX]')  # a cluster whose first c/m/W/X is a W or an X
PLAIN_SCRIPT_RX = re.compile(r'''['"]?[\w./+@%,:=-]+['"]?''')  # no $, `, glob, brace, ~ or backslash: one fixed word


def _argv_option(w, python):
    """How an option word before the script is read: 0 = not known (keep the old walk), 1 = no argument, 2 = its
    argument is the next word."""
    if not python or len(w) < 2 or w.startswith('--'):
        return 0
    for k, ch in enumerate(w[1:], 1):
        if ch in PY_WITHARG:
            return 2 if k == len(w) - 1 else 1  # -W alone takes the next word; -Wignore / -uWignore carry it
        if ch not in PY_NOARG:
            return 0
    return 1


def backtick_openers(text):
    """Card 217f551b: {start: end} of the backtick substitutions that OPEN at a position of text, from the shared
    lexer; None when text has a backtick the lexer did not read (not loaded, past its bounds, a problem). Card 4bdf7309
    (Viktor 43448 LELET 1, his proposed diff): the $( ) substitutions too, the same way."""
    if '`' not in text and '$(' not in text:
        return {}
    if shell_lex is None:
        return None
    try:
        lx = shell_lex.lex(text)
    except Exception:  # LexTooBig, or a lexer bug
        return None
    if lx['problems']:
        return None
    return {s['start']: s['end'] for s in lx['substs'] if s['kind'] in ('`', '$(')}


def _call_end(rest, base, openers):
    """The end of an interpreter call's words in rest (rest starts at text index base). Card 217f551b: a backtick that
    OPENS a substitution is part of a word, not the end of the call: bash runs `true` in `python3 \x60true\x60 m.py`,
    pastes its (empty) output and runs m.py; the old reader stopped at the backtick and judged nothing. A backtick that
    closes the substitution the call stands in (`x=\x60python3 m.py\x60`) still ends it. An escaped backtick (after an
    odd run of backslashes) is a character of a word, or inside a backtick substitution a nested one, which the lexer
    does not list (`x=\x60python3 \\\x60true\\\x60 m.py\x60` runs m.py): it never ends a call. Without the lexer's
    reading (openers None) no backtick ends a call: more words are judged, never fewer. Card 4bdf7309: a $( ) that
    opens inside the call's words is a word of it too (`python3 $(true) m.py` runs m.py); the ")" of the one the call
    stands in (`x=$(python3 m.py)`) still ends it."""
    pos = 0
    while True:
        end = _CALL_END_RX.search(rest, pos)
        if end is None:
            return len(rest)
        k = end.start()
        if rest[k] == '`':
            j = k
            while j > 0 and rest[j - 1] == '\\':
                j -= 1
            if openers is None or (k - j) % 2:
                pos = end.end()
                continue
        # any substitution (backtick or dollar-paren) that STARTS inside the call's words and still holds this
        # character is one word of the call: jump to its end. One that started before the call (the one the call stands
        # in) is not in range here, so its closing backtick or paren still ends the call.
        if openers:
            a = base + k
            inner = [e for st, e in openers.items() if base <= st <= a < e]
            if inner:
                pos = max(end.end(), max(inner) - base)
                continue
        return k


_SUBST_SPAN_RX = re.compile(r'`[^`]*`|\$\([^()]*\)')


def without_substs(w):
    """Card 4bdf7309 (Viktor 43448 LELET 1 b): the word as bash reads it when every substitution in it prints nothing
    (`python3 \x60true\x60evil.py` and `python3 $(true)./evil.py` run evil.py). Inner $( ) first, then the outer."""
    prev = None
    while prev != w:
        prev, w = w, _SUBST_SPAN_RX.sub('', w)
    return w


def has_subst(w):
    return '`' in w or '$(' in w


def merged_span(all_words, i):
    """The call's words are split at blanks, so a substitution with a blank in it (`$(echo $(true))m.py`) is in
    pieces: join the pieces from i while a backtick or a "(" is still open (at most MAX_ARGS pieces).
    -> (the joined word, the index of its last piece)."""
    s = all_words[i]
    j = i
    while (s.count('`') % 2 or s.count('(') > s.count(')')) and j + 1 < len(all_words) and j - i < MAX_ARGS:
        j += 1
        s += ' ' + all_words[j]
    return s, j


def merged_word(all_words, i):
    return merged_span(all_words, i)[0]


def needs_forms(raw):
    """A word bash reads otherwise than strip_quotes does: a substitution, or a quote / backslash anywhere in it."""
    return has_subst(raw) or '\\' in raw or bool(QUOTE_RX.search(raw[1:-1] if len(raw) > 1 else ''))


def word_forms(all_words, i):
    """Card 70c94516 (Viktor 43662 LELET 1): the other names bash may run for word i, besides strip_quotes' form:
    the whole-word quote removal (`"ev"il.py`), and with a substitution in it (pieces joined) the word without the
    substitutions, before and after the quote removal (`"$(true)"evil.py`, `evil"$(true)".py`). Distinct, in order;
    "" when a substitution may leave nothing. The caller adds them to the strip_quotes form: never fewer words."""
    raw = merged_word(all_words, i) if has_subst(all_words[i]) else all_words[i]
    forms = [shell_unquote(raw)]
    if has_subst(raw):
        forms += [without_substs(strip_quotes(raw)), shell_unquote(without_substs(raw))]
    return list(dict.fromkeys(forms))

# Only digits: a {fd} before the operator is cut off as a word of its own, so both readings are judged. zsh and bash
# 4+ redirect it and run the next word; macOS bash 3.2 has no {fd} and runs a file named `{fd}` (measured 11-16,
# mutation round 2: with `\{\w+\}` here such a file was never read).
_FD_PREFIX_RX = re.compile(r'\d+')


# One set for a path word and an interpreter call's words: in the call's words a ; & | is left only next to a < or >
# (`2>&1`, `&>f`, `>|f`: _CALL_END_RX ends the call at any other), where OUT_REDIR_RX reads both splits alike
# (mutation round 2, card e05330a4: a second set for the call words was never told apart).
_REDIR_OPS = ';&|<>'
_TOP = ('', 0, False)  # _redir_scan's state: the open quote, the $( ) depth, an open backtick


def redir_at(w):
    """G1 (Viktor, card 70c94516): the index where bash ends word w at an unquoted operator (`m.py>/dev/null`,
    `m.py&>f`, `"x".sh;true`), 0 when there is none. Quotes, $'..', a backslash and a balanced $( ) / backtick are
    stepped over. A quote or substitution the word leaves open AFTER the operator does not move it: the cut is at the
    top level, so bash ends the word there (`./"x".sh>"a b"` runs x.sh; mutation round 3, card e05330a4: with
    `0 if any(state)` the gate let it through). The caller adds w[:cut] to the word's forms, never drops one. The
    digits of `2>f` are no word (a {fd} is: see _FD_PREFIX_RX), and `x<(true)` is one word in bash."""
    return _redir_scan(w)[0]


def _redir_scan(w, state=_TOP):
    """redir_at's scan: (the cut in w, the state at the end of w). state goes on from the piece before, when a quote or
    substitution left open joins w to it over a blank: each piece is scanned once (card e05330a4 r3: rescanning the
    joined word ran nested `python3 m.py $(` calls into the 6 s watchdog). A cut in such a piece comes after the char
    that closed the state, so its prefix in w is never all digits, as in the joined word."""
    q, depth, tick = state
    cut, i, n = 0, 0, len(w)
    while i < n:
        c = w[i]
        if q:
            if c == '\\' and q != "'":
                i += 1
            elif c == q[-1]:
                q = ''
        elif c == '\\':
            i += 1
        elif c in '\'"':
            q = "$'" if c == "'" and i and w[i - 1] == '$' else c
        elif c == '`':
            tick = not tick
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        elif c in _REDIR_OPS and not cut and not depth and not tick and w[i + 1:i + 2] != '(':
            # an unescaped & of `&>` is an operator itself and cuts first; at i = 0 the cut is 0, no cut (mutation
            # round 3: a step back over a `\&` cut `m.py\&>f` before the escaped & and blocked a call of `m.py&`)
            if not _FD_PREFIX_RX.fullmatch(w[:i]):
                cut = i
        i += 1
    return cut, (q, depth, tick)


# G2 (Viktor, card 70c94516): a shell's -e is errexit, not code: `bash -e x.sh`, `sh -e x.sh`, `bash -o pipefail -e x.sh`
# run x.sh. For a shell only a cluster with a c in it takes a command string (`-c`, `-ec`, `-ce`).
SHELL_NAMES = ('bash', 'sh', 'zsh', 'dash', 'ksh')
SHELL_CODE_FLAG_RX = re.compile(r'-[a-zA-Z]*c[a-zA-Z]*')

def split_redirections(words, cache):
    """`python3 m.py>/dev/null` runs m.py: the glued redirection becomes a word of its own (read as before). Only the
    words the walk reads (MAX_ARGS); cache: one scan per distinct word and state of a text (the windows of calls
    overlap, and a $( ) nests them)."""
    def scan(w, state=_TOP):
        r = cache.get((w, state))
        if r is None:
            r = cache[(w, state)] = _redir_scan(w, state)
        return r
    out = []
    n = 0
    while n < len(words):
        if len(out) > MAX_ARGS:
            return out + words[n:]
        w = words[n]
        k, state = scan(w)
        if k and not any(state):
            out += [w[:k], w[k:]]
            n += 1
            continue
        # card e05330a4 (G1 with a blank): a quote or substitution left open goes on over the blank, so the shell
        # word is the pieces joined (`python3 m.py>"a b"`, `python3 $(true x)m.py>/dev/null`): cut the joined word,
        # in the piece the cut falls in. Not open, or no operator in the joined word: the pieces as they were.
        j, at = n, len(w) + 1
        while any(state) and j + 1 < len(words) and j - n < MAX_ARGS:
            j += 1
            c, state = scan(words[j], state)
            k = k or (c and at + c)
            at += len(words[j]) + 1
        k = 0 if any(state) else k  # never closed: no cut (closed without a join: k is 0, a cut went on above)
        start = 0
        for p in range(n, j + 1):
            piece, local = words[p], k - start
            out += [piece[:local], piece[local:]] if 0 < local < len(piece) else [piece]
            start += len(piece) + 1
        n = j + 1
    return out


def interp_groups(text, expanded=False):
    """For each interpreter call: the words that may be its script, in order (every existing file is judged).
    Raises TooManyArgs when a call's words run past MAX_ARGS or ARGS_WINDOW and the walk did not stop before."""
    groups = []
    openers = backtick_openers(text)
    redir_cache = {}
    for m in INTERP_RX.finditer(text):
        python = 'python' in m.group(0).lower()
        name = re.split(r'[\s;&|(){}`\'"/\\]', m.group(0).rstrip('\'"\\'))[-1]
        argv_data = bool(DATA_ARGV_RX.fullmatch(name)) and not expanded  # still True after a known option; False = the old walk
        # (expanded: expand() read a VAR=value anywhere in the text as this shell's assignment; the real value may be empty
        # (X=a python3 $X m.py, unset X, a comment) and the script the second word: such a text keeps the old walk)
        rest = text[m.end():m.end() + ARGS_WINDOW]  # a window, not the rest: 6 000 calls x the rest was quadratic
        cut = _call_end(rest, m.end(), openers)
        all_words = split_redirections(rest[:cut].split(), redir_cache)
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
                # card 70c94516 (Viktor 43662 LELET 2): f read as bash does (quotes, substitutions); when a
                # substitution may leave nothing of it (`source $(true) x.sh`), the next word is the file
                firsts = [first]
                if needs_forms(all_words[idx]):
                    forms = word_forms(all_words, idx)
                    firsts += [f for f in forms if f and f not in firsts]
                    end = merged_span(all_words, idx)[1]
                    if '' in forms and end + 1 < len(all_words):
                        firsts.append(strip_quotes(all_words[end + 1]))
                tail = all_words[idx + 1:]
                over = clipped or len(all_words) > MAX_ARGS
                rest = []
                for k, w in enumerate(tail[:MAX_ARGS], idx + 1):
                    if not w.startswith('-'):
                        rest.append(strip_quotes(w))
                        if needs_forms(w):
                            rest += [f for f in word_forms(all_words, k) if f and not f.startswith('-')]
                groups.append(SourceGroup(firsts, rest,
                                          f'source: {len(all_words)} szó, MAX_ARGS {MAX_ARGS}' if len(all_words) > MAX_ARGS
                                          else (f'source: a parancs hosszabb a {ARGS_WINDOW} karakteres ablaknál'
                                                if over else '')))
            continue
        if not expanded and AGENT_MSG_SHELL_RX.fullmatch(name) and all_words and os.path.basename(
                strip_quotes(all_words[0])) == 'agent-msg.sh':  # no option before it: `bash -s x` reads stdin
            over = clipped or len(all_words) > MAX_ARGS
            groups.append(AgentMsgGroup(strip_quotes(all_words[0]), [strip_quotes(w) for w in all_words[1:MAX_ARGS]
                                                                     if not w.startswith('-')],
                                        f'{len(all_words)} szó, MAX_ARGS {MAX_ARGS}' if over else ''))
            continue
        words = [strip_quotes(w) for w in all_words[:MAX_ARGS]]
        group = []
        stopped = False
        subst_seen = False
        i = 0
        while i < len(words):
            w = words[i]
            if python and PY_ATTACHED_RX.match(w):
                # -Wignore, -Xdev, -uWerror: the first of c/m/W/X in the cluster is W or X, so the rest is its
                # argument, not a -c / -e / -m (CODE_FLAG_RX took -Wignore for a code flag and stopped the walk:
                # `python3 -Wignore m.py` passed unread; found on card 31045f4d)
                kind = _argv_option(w, python) if argv_data else 1
                if kind == 0:
                    argv_data = False
                i += 2 if kind == 2 else 1
                continue
            # card 70c94516 (Viktor 43662 LELET 3): a module name the gate cannot read -- a substitution or a variable
            # in it (`-m $(echo evilmod)`, `-m ${M:-evilmod}`, `-m $(echo evil)mod`) -- blocks: any module may run.
            # Joined (`-mevil`, `-Imevil`, `-m"evil"`) and quoted forms are read with the quotes removed.
            joined = MODULE_JOINED_RX.fullmatch(shell_unquote(all_words[i])) if python else None
            if joined:
                if '$' in all_words[i] or '`' in all_words[i]:
                    raise TooManyArgs('python -m: a modulnév helyettesítés vagy változó, nem olvasható')
                groups += [[c] for c in module_files(joined.group(1))]
                stopped = True
                break
            if python and MODULE_FLAG_RX.fullmatch(w):
                if i + 1 < len(words):
                    raw = all_words[i + 1]
                    if '$' in raw or '`' in raw:
                        raise TooManyArgs('python -m: a modulnév helyettesítés vagy változó, nem olvasható')
                    groups += [[c] for c in module_files(words[i + 1])]
                    groups += [[c] for c in module_files(shell_unquote(raw))]
                stopped = True
                break
            if w == '-' or (SHELL_CODE_FLAG_RX if name in SHELL_NAMES else CODE_FLAG_RX).fullmatch(w):
                stopped = True
                break
            # an output redirection's target is written, not run (`python3 x.py > out.txt`; card 15896271): a file
            # an earlier run filled with the blocked call made the next run block. An input one (`< x.py`) is read.
            out_redir = OUT_REDIR_RX.match(w)
            if out_redir:
                i += 1 if out_redir.group(1) else 2
                continue
            if argv_data and w.startswith('-'):
                kind = _argv_option(w, python)
                if kind == 0:
                    argv_data = False  # an option the gate does not know: every word is judged, as before
                i += 1  # (a -W / -X cluster, kind 2, never gets here: PY_ATTACHED_RX above takes it and its argument)
                continue
            # card 4bdf7309 (LELET 1 b): `\x60true\x60evil.py` runs evil.py: the word without its substitutions; card
            # 70c94516 (LELET 1): `"ev"il.py`, `"$(true)"evil.py`: the word with every quote removed (word_forms)
            forms = word_forms(all_words, i) if needs_forms(all_words[i]) else []
            if python and subst_seen and not w.startswith('-') and w:
                # card 4bdf7309 (LELET 1 c): after a substitution word, any word may be a module name (`python3
                # \x60echo -m\x60 evilmod` runs evilmod.py): judged as one too, never fewer words
                for f in dict.fromkeys([without_substs(w)] + forms):
                    groups += [[c] for c in module_files(f)]
            if has_subst(all_words[i]):
                subst_seen = True
            if not w.startswith('-') and w:
                group.append(w)
                group += [f for f in forms if f and f != w and not f.startswith('-')]
                # the script: the words after it are its arguments (see DATA_ARGV_RX). Only a plain word: an unset
                # $X or a glob may vanish or become another file (`python3 $X m.py` runs m.py), and a word the
                # window cut may be longer than what was read
                if argv_data and PLAIN_SCRIPT_RX.fullmatch(all_words[i]) and not (
                        clipped and i == len(all_words) - 1):
                    if python:
                        group.append(os.path.join(w, '__main__.py'))  # a directory runs its __main__.py
                    stopped = True
                    break
                argv_data = False
            i += 1
        if not stopped and clipped:
            raise TooManyArgs(f'a parancs hosszabb a {ARGS_WINDOW} karakteres ablaknál')
        if not stopped and len(all_words) > MAX_ARGS:
            raise TooManyArgs(f'{len(all_words)} szó, MAX_ARGS {MAX_ARGS}')
        if group:
            groups.append(group)
    return groups


def script_paths(cmd, cwd, normalised=None, extra=()):
    """The script files the command runs (resolved, existing regular files), at most MAX_SCRIPTS (an eleventh file
    or more than MAX_BASES directories returns MAX_SCRIPTS + 1 entries: the caller blocks). Raises TooManyArgs.
    extra: more words to look up as files (a pipeline into a shell, card 74586987)."""
    norm = normalise(cmd) if normalised is None else normalised
    text = expand(norm)
    groups = interp_groups(text, text != norm) + [[w] for w in extra]
    # card 70c94516 (Viktor 43662 LELET 1): normalise() takes the backslash of a $'\x65' escape (`\x` -> `x`), which
    # bash decodes in a word (`python3 $'\x65vil.py'` runs evil.py): such a command is read without it too
    word_texts = [text]
    if "$'" in cmd and '\\' in cmd:
        raw = expand(cmd)
        groups += interp_groups(raw, raw != cmd)
        word_texts.append(raw)
    if INTERP_RX.search(text):  # the script on stdin: only when an interpreter runs
        groups += [[m.group(1)] for m in REDIRECT_RX.finditer(text)]
        for m in CAT_RX.finditer(text):
            cat_words = m.group(1).split()
            if len(cat_words) > MAX_ARGS:
                raise TooManyArgs(f'cat: {len(cat_words)} szó, MAX_ARGS {MAX_ARGS}')
            groups += [[strip_quotes(w)] for w in cat_words if not w.startswith('-')]
    groups += [[m.group(1)] for m in DIRECT_RX.finditer(text)]
    for m in (m for t in word_texts for m in DIRECT_WORD_RX.finditer(t)):
        raw = m.group(1).rstrip(';&|<>')
        if len(raw) > ARGS_WINDOW:  # without_substs is a loop per nesting level: an unbounded word is not read
            raise TooManyArgs(f'egy útvonal-szó hosszabb {ARGS_WINDOW} karakternél')
        # a ")" may close the substitution the path stands in (`$(./x"y".sh)`): read with and without it
        k = redir_at(raw)  # G1: `./"x".sh;true`, `./"x".sh>log`: the word ends at the operator
        groups.append([f for r in dict.fromkeys([raw, raw.rstrip(')')] + ([raw[:k]] if k else []))
                       for f in word_forms([r], 0) if f])
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
            # card 74586987: /dev/stdout, /dev/fd/1 and the like name THIS hook's own descriptors, never a file of the
            # command (its shell's fds exist only when it runs). A hook whose stdout was a file (the replay worker)
            # took /dev/fd/1 for a regular file, could not read it and blocked (PermissionError, fail-closed).
            if real == '/dev' or real.startswith('/dev/'):
                continue
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
        if isinstance(group, AgentMsgGroup):
            if agent_msg_everywhere(group.first, bases):
                group = [group.first]  # its words are the message
            elif group.over:
                raise TooManyArgs(group.over)
            else:
                group = [group.first] + group.rest
        if isinstance(group, SourceGroup):
            first = False
            for f in group.firsts:
                r = resolve(f)
                if r is None:
                    return [''] * (MAX_SCRIPTS + 1)
                first = first or r
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
    # card 15896271 (Viktor 41970 LOW 4): the macOS wrappers that exist here and run their command
    'sandbox-exec': ('fnpD', set(), 0),  # -p <profile> / -f <file> / -n <name> / -D key=value
    'lockf': ('t', set(), 1),  # lockf [-kns] [-t seconds] <file> cmd
    'launchctl': ('', set(), 2),  # launchctl asuser <uid> cmd, bsexec <pid> cmd
    'login': ('h', set(), 1),  # login -fp [-h host] <user> cmd
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
    submit = name == 'launchctl' and re.match(r'[ \t]*submit(?=[ \t])', text[i:i + 24])
    if submit:
        short, positional = 'loe', 1  # launchctl submit -l label [-p prog] [-o out] [-e err] -- command args
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
            if submit and 'p' in t[1:]:  # `-p prog -- argv0 args` runs prog with any argv0: the words after `--`
                return -1  # are not the command, so it is not read (blocks; Dave on Viktor 42251 LOW 4)
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


# A heredoc whose RECIPIENT only stores or sends its body (Viktor 42491, card 8a5d51e8): a commit message, an
# agent-msg, a curl body. A path at a line start in it was read as a script run (`git commit -F - <<'MSG'` naming
# keychain-read-gate_test.py blocked, 2026-11-14). Only a QUOTED delimiter (<<'D', <<"D"): an unquoted body runs its
# $(...) and backticks; normalise() turns <<\D into <<D, so that form stays unquoted and kept. Only these recipients, as
# the operator's own command, with nothing after the operator on its line (conservative): `python3 - <<'PY'`,
# `bash <<'SH'`, `cat <<'E' | bash` and `cat > f <<'E'` (the file may be run next) keep their bodies. hits() still
# reads the whole text; only the script-path walk skips the body.
# Viktor 42575 HIGH: the regex does not know the shell's state, so `<<'D'` may be no operator at all: a here-string
# (`<<<'D'`), an escaped `\<` (then `<'D'` is an input redirection), inside a quote (`-m "x <<'D'"`, a quote opened on
# an earlier line), after a comment (`true # a; git commit -F - <<'D'`) or inside an earlier heredoc's body. Blanking
# then hid real command lines up to the next line equal to D. So ONLY the text's first heredoc can be data, and only
# when nothing before it can change the shell's state: no quote, `#`, backslash, backtick or `$` before it (a `$(`
# or a backtick left open before the operator ends on a body line, and what follows there runs: measured with bash,
# card 8a5d51e8). An earlier heredoc needs a quote or the SAFE_PREFIX_RX steps below, so `<<` is not listed.
HEREDOC_OP_RX = re.compile(r'(?<!<)<<-?[ \t]*(?:\'(\w+)\'|"(\w+)")')
STATE_BEFORE_OP_RX = re.compile(r'[\'"#\\`$]')
# anchored at the command's first word: `bash -s agent-msg.sh <<'M'` reads its script from the heredoc, `python3 - git
# commit -F -` is python, so the recipient must BE the command, not a word inside it. No VAR=x prefix: PATH=,
# GIT_EXEC_PATH=, BASH_ENV= and the like can make the recipient hand its stdin to a program of the caller's choosing
DATA_RECIPIENT_RX = re.compile(
    r'^\s*(?:'
    r'git\s+(?:-C\s+\S+\s+)?(?:commit|tag)\s.*?(?:-F\s*-|--file[= ]-)(?=\s|$)'
    r'|(?:(?:/usr)?(?:/bin/)?(?:bash|sh)\s+)?(?P<msg>\S*agent-msg\.sh)\s'
    r'|curl\s.*?(?:--data(?:-binary|-raw)?|-d)\s+@-(?=\s|$))')
# Viktor 42639 (delta on 722fd7be): a denylist of what may stand around the operator kept leaking, so both sides are
# an ALLOWLIST now. Before the recipient's command only `cd <plain path>` or `true` steps, joined by &&, ||, ;, | or a
# newline: a function (`git() { bash; }`), `export PATH=`, `alias`, `hash -p` or a planted program earlier in the text
# makes the recipient something else. After the operator nothing at all on its line: a quote left open there makes the
# next lines part of the command line (`<<'MSG' -m "x` + newline + `" ; ./run.py`), and the body starts only after
# them. The bash of `bash agent-msg.sh` is the bare one or /bin, /usr/bin: an absolute `/tmp/x/bash` is the caller's.
# `git add <plain paths>` is a step too: the fleet's real form is `git add f && git commit -F - <<'MSG'` (replay of 150
# transcripts: without it 0 of the false blocks went away); it runs only what the repo's own config runs, the same as
# the commit itself.
SAFE_PREFIX_RX = re.compile(
    r'(?:[ \t]*(?:cd[ \t]+[\w./-]+|true|git[ \t]+add(?:[ \t]+[\w./-]+)+)[ \t]*(?:&&|\|\||;|\||\n))*')
# Viktor 42575 MEDIUM: agent-msg.sh is a recipient only as THIS repo's script (resolved against the cwd): a look-alike
# `./agent-msg.sh` or `./scripts/agent-msg.sh` written elsewhere may run its stdin
AGENT_MSG = os.path.realpath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'agent-msg.sh'))


def data_heredoc_blanked(text, cwd):
    """text with the body of its first heredoc blanked (same length, newlines kept) when that heredoc is data: a quoted
    delimiter, nothing before it that changes the shell's state, a data recipient as the operator's own command, and
    nothing after the operator on its line."""
    return blank_span(text, data_heredoc_span(text, cwd))


def blank_span(text, span):
    """text with [start, end) blanked: every character but a newline becomes a space (same length)."""
    if span is None:
        return text
    a, b = span
    return text[:a] + re.sub(r'.', ' ', text[a:b]) + text[b:]


def data_heredoc_span(text, cwd):
    """[start, end) of the body data_heredoc_blanked() blanks, or None (see there)."""
    m = HEREDOC_OP_RX.search(text)
    if not m or STATE_BEFORE_OP_RX.search(text, 0, m.start()):
        return None
    delim = m.group(1) or m.group(2)
    line_start = text.rfind('\n', 0, m.start()) + 1
    line_end = text.find('\n', m.end())
    if line_end < 0:
        return None
    head = re.split(r'[;&|]', text[line_start:m.start()])[-1]
    if text[m.end():line_end].strip() or not SAFE_PREFIX_RX.fullmatch(text[:m.start() - len(head)]):
        return None
    rec = DATA_RECIPIENT_RX.search(head + ' ')
    if not rec:
        return None
    if rec.group('msg') is not None:
        path = rec.group('msg')
        if not os.path.isabs(path):
            # a relative path resolves against the cwd only when nothing before it may have moved the shell: an
            # earlier `cd /x &&`, `;`, `&` or line (or a sourced file). A pipe's earlier parts run in subshells.
            if not cwd or re.search(r'[;&\n]', text[:m.start()]):
                return None
            path = os.path.join(cwd, path)
        if os.path.realpath(path) != AGENT_MSG:
            return None
    term = re.compile(r'^\t*' + re.escape(delim) + r'$', re.M).search(text, line_end + 1)
    if not term:
        return None
    return line_end + 1, term.start()


# Card fae0712e (DREAM 11-15; Viktor 42695 LOW 1-2, 42697): the SHELL STRUCTURE the script rules read comes from the
# shared lexer, scripts/lib/shell_lex.py (the Python twin of shell-lex.mjs, both checked against a real bash): where a
# quote, a heredoc body and a substitution start and end, and which simple command a word belongs to. The rules that
# judge a text (interp_groups, DIRECT_RX, CAT_RX, payload_quotes, wrapper_bounds) stay as they are and read:
#   - the command text, where a separator inside a QUOTED argument of a command that never runs its arguments
#     (DATA_COMMANDS: `echo 'x; ./m.py'`) is no command boundary any more (it read as one: a false block). Every other
#     command's quotes are read as before (`ssh h 'a; ./m.py'`, `awk '{system("./m.sh")}'`, `tmux send-keys '...'`
#     may run them, and no list of such commands is ever complete);
#   - and, on separate lines, every simple command inside a substitution (`echo \`./m.py\``: the backtick right after
#     the path hid it from DIRECT_RX, Viktor 42695 LOW 1), and every word after a shell's -c word, unquoted too
#     (`bash -c ./m.py`, Viktor 42695 LOW 2; a quoted one was already read through payload_quotes).
# A heredoc body stays in the text (an interpreter may read it); the data-heredoc blanking is kept, and blanks only
# when the lexer agrees that the span is exactly the body of the text's first heredoc.
# Fail-closed: when the lexer reports a problem (an unterminated quote, heredoc or substitution, a heredoc inside a
# substitution), cannot be loaded, raises, or the text is past LEX_MAX_SUBSTS / LEX_MAX_WORK, the text takes the old
# path unchanged (today's decision): a lexer result never makes an allow on text it does not fully understand.
# The bounds: segments_of() costs about (length + the length of every substitution's inside) x substitutions, cubic
# in nested unclosed ones (measured 2026-11-15: 64 x `f(` before 10 000 chars took 2.5 s, 300 x `f(` 6.9 s, 1 000 x
# `f(` 255 s), so it is not started past LEX_MAX_WORK units (about 0.2 s).
_LEX_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib', 'shell_lex.py')
LEX_MAX_SUBSTS = 64
LEX_MAX_WORK = 3_000_000
# not rg: `rg --pre <cmd>` runs a program per file; not sed (GNU sed's `e`), awk, find, xargs, git, gh, curl ...
DATA_COMMANDS = frozenset({'echo', 'printf', 'grep', 'egrep', 'fgrep', 'true', 'false', ':', 'test', '['})
MASK_CHARS = frozenset(';&|(){}<>`\n')
# what can turn a data command into another command, change how the text is read, or hand a data command's words to
# a later command (`$_` is the previous command's last word: `echo 'x; ./m.py'; bash -c "$_"` runs it; a DEBUG trap
# or PS4 sees BASH_COMMAND): then no argument is masked (anywhere in the text, quoted too: a false "no" only keeps
# the old reading). `.` as a command word: COMPOUND_WORDS. The shell's own command line read back (`echo 'x; ./m.py';
# ps -o args= -p $$ | cut -d"'" -f2 | bash` ran in bash and zsh): ps, pgrep, lsof, PPID keep the old reading too.
# Not seen, as everywhere in this gate (see "Not seen"): a command built at run time by an interpreter (a python3 -c
# that reads its parent's arguments); the old gate did not see `printf '\x2e/m.py' | bash` either, and the
# data-heredoc blanking has the same limit.
REDEF_RX = re.compile(r'(?<![\w$-])(?:alias|unalias|function|eval|source|hash|enable|disable|autoload|zmodload'
                      r'|unfunction|functions|setopt|unsetopt|shopt|emulate|histchars|trap|fc|history|PS4'
                      r'|PROMPT_COMMAND|BASH_COMMAND|preexec|precmd|ps|pgrep|lsof|PPID|procargs2?)(?![\w-])|\(\s*\)'
                      r'|(?<![\w$])(?:PATH|path|FPATH|fpath)\+?=|\$\{?_(?!\w)')
SHELL_WORD_RX = re.compile(r'(?:.*/)?(?:bash|sh|zsh|dash|ksh|fish|csh|tcsh|ash|rbash|pwsh)\d*|\$\{?(?:SHELL|BASH)\}?|\$0')
C_FLAG_RX = re.compile(r'-[A-Za-z]*c')
CODE_FRAMES = ('`', '$(', '<(', '>(', '(')


class LexTooBig(Exception):
    """The text is past the lexer's bounds: the caller takes the old path."""


def _load_shell_lex():
    """The lexer as a private module object, loaded by path from this file's own scripts/lib: the hook runs with
    python3 -I (no script dir, no cwd on sys.path), and nothing is added to sys.path or sys.modules, so no other
    shell_lex.py can be picked up. Its segments_of() is wrapped with the bounds (lex() calls it by its global name).
    None when it cannot be loaded: every text then takes the old path."""
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location('keychain_gate_shell_lex', _LEX_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        full = mod.segments_of
    except Exception:
        return None

    def bounded(s, cls, substs):
        work = (len(s) + sum(max(0, x['inner'][1] - x['inner'][0]) for x in substs)) * (len(substs) + 1)
        if len(substs) > LEX_MAX_SUBSTS or work > LEX_MAX_WORK:
            raise LexTooBig()
        return full(s, cls, substs)
    mod.segments_of = bounded
    return mod


shell_lex = _load_shell_lex()


_LEX_LAST = [None, None]  # hits() and script_hits() lex the same command: once


def lex_or_none(cmd):
    """The lexer's view of cmd, or None: not loaded, raised, past the bounds, or a problem (see above)."""
    if shell_lex is None:
        return None
    if _LEX_LAST[0] == cmd:
        return _LEX_LAST[1]
    try:
        lx = shell_lex.lex(cmd)
    except Exception:  # LexTooBig, or a lexer bug: the old path
        lx = None
    lx = None if lx is None or lx['problems'] else lx
    _LEX_LAST[:] = [cmd, lx]
    return lx


def _owners(n, substs):
    """owner[p]: the index of the innermost substitution whose inside holds p, -1 at the top level."""
    owner = [-1] * n
    for k, x in sorted(enumerate(substs), key=lambda kx: kx[1]['start']):
        a, b = x['inner'][0], min(x['inner'][1], n)
        if b > a:
            owner[a:b] = [k] * (b - a)
    return owner


def _first_word(text, cls, seg):
    """The segment's first word when it is plain code (no quote, escape or expansion in it), else None."""
    j = seg['start']
    while j < seg['end'] and not (text[j] in ' \t' and cls[j] == 'c'):
        if cls[j] != 'c' or text[j] in '$`\\\'"':
            return None
        j += 1
    return text[seg['start']:j]


# A data command's output can still become code: piped into a shell (`echo '...' | bash`), written to a file run
# next (`echo '...' > f; bash f`, `exec >f`), captured by a substitution (`bash <(echo '...')`, `x=$(echo '...');
# bash -c "$x"`), stored in a variable (`printf -v x '...'`), or as the output of a compound command that is piped
# (`{ true; echo '...'; } | bash`, `if ...` + newline + `echo '...'` + newline + `fi | bash`). So no argument is masked
# when any segment starts with one of these words or the text has a brace that is not a ${...}; and a segment is
# masked only at the top level, with no < or > of its own, not followed by a pipe, and printf only without -v.
# (Found by review on card fae0712e: the old gate read the quoted separator and blocked all of these by accident.)
COMPOUND_WORDS = frozenset({'.', 'exec', 'if', 'then', 'else', 'elif', 'fi', 'do', 'done', 'while', 'until', 'for',
                            'case', 'esac', 'select', 'coproc', 'repeat', 'foreach', 'end', '{', '}'})
PRINTF_V_RX = re.compile(r'(?<![\w-])-[A-Za-z]*v')


def _mask_allowed(cmd, cls, lx):
    """No data command's argument may be masked in cmd (see above) -> False."""
    if REDEF_RX.search(cmd):
        return False
    words = [_first_word(cmd, cls, s) for s in lx['segments']]
    if any(w in COMPOUND_WORDS or (w and w[0] in '{}') for w in words):
        return False
    braces = {x['start'] + 1 for x in lx['substs'] if x['kind'] == '${'}
    braces |= {x['end'] - 1 for x in lx['substs'] if x['kind'] == '${'}
    return not any(ch in '{}' and cls[p] == 'c' and p not in braces for p, ch in enumerate(cmd))


def _data_segment(cmd, cls, seg, owner, lx=None, bases=None):
    """seg is a data command whose quoted arguments may be masked (see above). This repo's agent-msg.sh is one too
    (card 31045f4d): `bash scripts/agent-msg.sh to from "message"` sends its words, it runs none of them; only when the
    path is ours from every directory the command may run in (agent_msg_everywhere), so a look-alike is not."""
    word = _first_word(cmd, cls, seg)
    if seg['frame'] != 'top':
        return False
    if word not in DATA_COMMANDS:
        if lx is None or not word or not (AGENT_MSG_SHELL_RX.fullmatch(word) or word.endswith('agent-msg.sh')):
            return False
        ws = shell_lex.words(cmd, lx, seg)
        path = ws[1]['text'] if AGENT_MSG_SHELL_RX.fullmatch(word) and len(ws) > 1 else ws[0]['text']
        if not agent_msg_everywhere(path, bases or []):
            return False
    if word == 'printf' and PRINTF_V_RX.search(cmd, seg['start'], seg['end']):
        return False
    if any(cmd[p] in '<>' and cls[p] == 'c' and owner[p] == -1 for p in range(seg['start'], seg['end'])):
        return False
    p = seg['end']
    while p < len(cmd) and (cmd[p] in ' \t' or cls[p] == 'l'):
        p += 1
    return not (p < len(cmd) and cmd[p] == '|' and cls[p] == 'c' and cmd[p + 1:p + 2] != '|')


def lexer_view(text, cmd, lx, cwd=None):
    """The text the script rules read (see the block above): `text` (cmd, maybe with the data heredoc blanked; same
    length) with the separators inside data commands' quoted arguments masked, plus the extra command texts."""
    cls = lx['cls']
    segs = lx['segments']
    owner = _owners(len(cmd), lx['substs'])
    bases = cd_bases(normalise(cmd), cwd)  # where an agent-msg.sh path may be resolved from (every cd in the text)
    chars = None
    if _mask_allowed(cmd, cls, lx):
        for seg in segs:
            if not _data_segment(cmd, cls, seg, owner, lx, bases):
                continue
            for p in range(seg['start'], seg['end']):
                if cls[p] in 'qdae' and text[p] in MASK_CHARS and owner[p] == seg['frameAt']:
                    chars = chars or list(text)
                    chars[p] = '_'
    view = ''.join(chars) if chars else text
    extras = [lexer_normalise(view, cls, s['start'], s['end']) for s in segs
              if s['depth'] > 0 and s['frame'] in CODE_FRAMES]
    for seg in segs:
        raw = cmd[seg['start']:seg['end']]
        if not (C_FLAG_RX.search(raw) and SHELL_RX.search(' ' + raw + ' ')):  # cheap first: words() is not linear
            continue
        ws = shell_lex.words(cmd, lx, seg)
        shell = next((i for i, w in enumerate(ws) if SHELL_WORD_RX.fullmatch(w['text'])), None)
        c = next((i for i, w in enumerate(ws) if shell is not None and i > shell and C_FLAG_RX.fullmatch(w['text'])),
                 None)
        if c is not None:
            extras += [normalise(w['text']) for w in ws[c + 1:]]  # shell code: a \ + newline in it does join
    return lexer_normalise(view, cls, 0, len(view)), extras


def lexer_normalise(view, cls, a, b):
    """normalise() of view[a:b] (same length as the lexed text, cls its classes), with its join of a backslash-newline
    left out where the backslash ends a comment (`: |#\\` + newline + cmd) or is the second half of an escaped
    backslash (`x \\\\` + newline + cmd): there the next line is a command of its own for bash and zsh, and the blind
    join made it part of a word (both found by a differential fuzz against bash and zsh, card fae0712e; the old gate
    let the script run, and hits() let `security dump-keychain` through). Inside quotes and heredoc bodies it joins as
    before: they may be a payload whose own shell joins (`bash -c 'python3 m\\` + newline + `.py'`). Splitting there
    only shows the shell's own line structure; a join never hid less."""
    out = []
    p = a
    while p < b:
        if view[p] == '\\' and p + 1 < b and view[p + 1] == '\n' and cls[p] not in 'me':
            p += 2
            continue
        out.append(view[p])
        p += 1
    return normalise(''.join(out), joined=True)


# Card 31045f4d (Pulzus 43167, Klodel 43233, Viktor 43200/43235): the data heredoc, read by the lexer. The regex path
# above blanks only the text's FIRST heredoc and only with nothing that may change the shell's state before it (no
# quote, $, backtick, # or backslash), so the fleet's own forms blocked on the prose of their body:
#   curl ... -H "Authorization: Bearer $(cat store/.dashboard-token)" --data-binary @- <<'JSON'   (a $ and a quote)
#   T="Authorization: Bearer $(cat ...)" + newline + curl ... -H "$T" --data-binary @- <<'JSON'  (a step before)
#   a card comment and an agent-msg in one command                                              (a second heredoc)
# When the lexer reads the whole text (no problem), it says where each heredoc and each simple command is, so the
# state question is answered by the lexer, not by the absence of quotes. The rest stays an ALLOWLIST (Viktor 42639):
#   - the heredoc's delimiter is quoted (a body with live $( ) is not data) and it is the only heredoc of its command;
#   - its command, from its first word to the operator, is a DATA_RECIPIENT_RX recipient, with nothing after the
#     operator on its line (the body starts on the next line);
#   - every top-level command before it is a step: `cd <plain path>`, `true`, a bare `echo` (Klodel's own comment +
#     memory call printed a blank line between two curls), `git add <plain paths>`, an assignment
#     to a ONE-LETTER variable (T=..., S=...: no one-letter name is exported or read by curl, git, bash or the
#     dynamic loader; its value may hold a $( ) whose command runs in a subshell and is read by the script rules as
#     before), or an earlier data-heredoc command. The first other command ends the walk: nothing after it is blanked;
#   - no alias, function, eval, source, PATH=, hash, trap ... in the CODE of the text (REDEF_RX on code characters
#     only: the prose of a body or a quoted argument cannot define anything; a source in a JSON body blocked);
#   - agent-msg.sh only as this repo's script, a relative path only when no step before it is a cd.
# The body is blanked for the script-path rules only; hits() still reads the whole text, and every $( ) outside the
# body is read as its own command (lexer_view extras).
STEP_RX = re.compile(r'(?:cd[ \t]+[\w./-]+|true|echo|git[ \t]+add(?:[ \t]+[\w./-]+)+)[ \t]*')
ONE_LETTER_ASSIGN_RX = re.compile(r'[A-Za-z]=')
STEP_SEP_RX = re.compile(r'[ \t]*(?:&&|\|\||;|\||\n)[ \t\n]*')


def _agent_msg_is_ours(path, cwd, moved):
    """path (the recipient word) names this repo's agent-msg.sh: absolute, or relative to cwd when nothing before it
    may have moved the shell."""
    if not os.path.isabs(path):
        if not cwd or moved:
            return False
        path = os.path.join(cwd, path)
    return os.path.realpath(path) == AGENT_MSG


def data_body_pipes_masked(cmd, lx, cwd):
    """Card 74586987 (replay r2, a card comment blocked as secret-read): cmd (same length) with every "|" made a blank
    inside the body of a quoted-delimiter heredoc whose recipient only stores or sends it (DATA_RECIPIENT_RX: git
    commit -F -, curl -d @-, this repo's agent-msg.sh), for stdin_pipelines() only. Such a body is data, never code of
    this shell, so prose in it (`... echo security dump-keychain | bash`) is no pipeline into a shell. The same checks
    as lexer_data_spans() on the heredoc itself (top level, one heredoc in its command, quoted delimiter, nothing after
    the operator on its line, no REDEF_RX in the text's code, agent-msg.sh only as ours, a relative one only without a
    cd before it), but not its walk over the steps before: those decide whether the script rules may skip the body,
    and no step before changes that a data recipient's body is data (a redefinition is REDEF_RX's). Everything else
    still reads the body as before: hits(), the script rules, the payloads."""
    if lx is None or not lx['heredocs'] or '|' not in cmd:
        return cmd
    cls = lx['cls']
    code = ''.join(ch if cls[p] == 'c' else ' ' for p, ch in enumerate(cmd))
    if REDEF_RX.search(code):
        return cmd
    chars = None
    for seg in lx['segments']:
        if seg['depth'] != 0 or seg['frame'] != 'top':
            continue
        hs = [h for h in lx['heredocs'] if seg['start'] <= h['op'] < seg['end']]
        if len(hs) != 1:
            continue
        h = hs[0]
        if not h['quoted'] or not re.search('[\'"]', cmd[h['op']:h['opEnd']]):
            continue
        line_end = cmd.find('\n', h['opEnd'])
        if line_end < 0 or cmd[h['opEnd']:line_end].strip() or h['bodyStart'] != line_end + 1:
            continue
        rec = DATA_RECIPIENT_RX.match(cmd[seg['start']:h['op']] + ' ')
        if not rec:
            continue
        if rec.group('msg') is not None and not _agent_msg_is_ours(
                rec.group('msg'), cwd, bool(re.search(r'(?<![\w.-])cd(?![\w.-])', code[:seg['start']]))):
            continue
        if '|' in cmd[h['bodyStart']:h['bodyEnd']]:
            chars = chars or list(cmd)
            for p in range(h['bodyStart'], h['bodyEnd']):
                if chars[p] == '|':
                    chars[p] = ' '
    return ''.join(chars) if chars else cmd


def lexer_data_spans(cmd, cwd, lx):
    """[(bodyStart, bodyEnd)] of the data heredocs (see the block above), in order; [] when none."""
    cls = lx['cls']
    code = ''.join(ch if cls[p] == 'c' else ' ' for p, ch in enumerate(cmd))
    if REDEF_RX.search(code):
        return []
    tops = [s for s in lx['segments'] if s['depth'] == 0 and s['frame'] == 'top']
    spans = []
    moved = False
    prev_end = 0  # where the command before ends (a heredoc command: its terminator line)
    for seg in tops:
        # the steps are joined by &&, ||, ;, | or newlines, as on the regex path: a `cd x &` runs in the background
        sep = cmd[prev_end:seg['start']]
        # (a heredoc's `end` is past its terminator line's newline: that newline is the join)
        if prev_end and not (STEP_SEP_RX.fullmatch(sep) or (cmd[prev_end - 1] == '\n' and not sep.strip(' \t\n'))):
            break
        hs = [h for h in lx['heredocs'] if seg['start'] <= h['op'] < seg['end']]
        if hs:
            h = hs[0]
            # quoted as <<'D' or <<"D" (the lexer also counts <<\D, which the regex path keeps: so does this one)
            if len(hs) != 1 or not h['quoted'] or not re.search('[\'"]', cmd[h['op']:h['opEnd']]):
                break
            line_end = cmd.find('\n', h['opEnd'])
            if line_end < 0 or cmd[h['opEnd']:line_end].strip() or h['bodyStart'] != line_end + 1:
                break
            rec = DATA_RECIPIENT_RX.match(cmd[seg['start']:h['op']] + ' ')
            if not rec or (rec.group('msg') is not None and not _agent_msg_is_ours(rec.group('msg'), cwd, moved)):
                break
            spans.append((h['bodyStart'], h['bodyEnd']))
            prev_end = h['end']
            continue
        text = cmd[seg['start']:seg['end']]
        prev_end = seg['end']
        if STEP_RX.fullmatch(text):
            moved = moved or text.startswith('cd')
            continue
        if ONE_LETTER_ASSIGN_RX.match(text) and len(shell_lex.words(cmd, lx, seg)) == 1:
            continue
        break
    return spans


# Card 31045f4d (Pulzus 43167, Viktor 43235 point 2): a quoted heredoc whose command is a non-shell interpreter
# (`python3 -I - <<'PY'`) has a body the shell does not read; the script rules read it anyway (the program may run a
# shell command from it), and a prose "( scripts/hooks/x.py" in one of its strings read as a subshell running x.py.
# There, and only there, a "(" right after a blank, followed by an unquoted path, is not a command position:
# `word (./x.sh)` is a syntax error in a shell, and after a separator (`; (./x.sh)`, `&& (./x.sh)`) the path still
# sits at the separator's command position once the "(" is gone. Kept: os.system('./x.sh') and "(./x.sh)" (a quote
# before), perl qx(./x.sh), ruby %x(./x.sh), $(./x.sh), <(./x.sh) (no blank before), a backtick, a separator.
NONSHELL_RX = re.compile(r'(?:.*/)?(?:python[\d.]*|node|ruby|perl|php|deno|bun)', re.I)
PROSE_PAREN_RX = re.compile(r'(?<=[ \t])\((?=[\w./~])')


# Where `word (./x.sh)` runs (measured with a real bash, sh and zsh): after a reserved word that takes a command list
# (time, if, then, elif, else, while, until, do, !, {), after zsh's repeat N and coproc, at the start of a line or of a
# string (a blank only before the paren), and after a separator. After an ordinary word (echo a (./x.sh), x, (./x.sh))
# it is a syntax error. So only a "(" right after a word (letters or digits, or a word ending in . , :) that is no such
# keyword, on the same line, is prose; a word with a backslash (an escape: "\\n (./x.sh)") or starting with - or !
# (time -p (./x.sh)) is not (Viktor 43304).
PROSE_KEYWORDS = frozenset({'time', 'if', 'then', 'elif', 'else', 'while', 'until', 'do', 'coproc', 'repeat', 'nocorrect',
                            'noglob', 'always', 'foreach', 'select', 'case', 'for', 'in'})


PROSE_WORD_RX = re.compile(r'[\w.,:\\!-]+')


def _prose_paren(cmd, p):
    # a bounded window, not the whole line: 40 000 "(x" on one line took 42 s with a scan to the line start per paren
    start = max(0, p - 200)
    seg = cmd[start:p]
    nl = seg.rfind('\n')
    if nl >= 0:
        before = seg[nl + 1:].rstrip(' \t')
    else:
        before = seg.rstrip(' \t')
        if start:  # the window may begin inside a word: drop that first, maybe cut, word
            i = before.find(' ')
            before = before[i + 1:] if i >= 0 else ''
    toks = PROSE_WORD_RX.findall(before)
    if not toks or not before.endswith(toks[-1]):  # a quote, bracket, = or separator right before the blanks: no word
        return False
    tok = toks[-1]
    if '\\' in tok or tok[0] in '-!' or not (tok[-1].isalnum() or tok[-1] in '.,:') or tok in PROSE_KEYWORDS:
        return False
    return not any(t in ('repeat', 'coproc') for t in toks[-3:])


def nonshell_prose_masked(text, cmd, lx):
    """text (same length as cmd) with the prose "(" of the non-shell heredoc bodies made a blank (see above)."""
    chars = None
    for seg in lx['segments']:
        if seg['depth'] != 0 or seg['frame'] != 'top':
            continue
        hs = [h for h in lx['heredocs'] if seg['start'] <= h['op'] < seg['end'] and h['quoted']]
        if not hs:
            continue
        ws = shell_lex.words(cmd, lx, seg)
        if not ws or not NONSHELL_RX.fullmatch(ws[0]['text']):
            continue
        for h in hs:
            for m in PROSE_PAREN_RX.finditer(cmd, h['bodyStart'], h['bodyEnd']):
                if not _prose_paren(cmd, m.start()):
                    continue
                chars = chars or list(text)
                chars[m.start()] = ' '
    return ''.join(chars) if chars else text


def script_hits(cmd, cwd):
    """Rule names for inline interpreter code and for the files the command runs."""
    found = []
    if INTERP_RX.search(normalise(cmd)) and literal_hit(cmd):
        found.append('script-inline')
    # the payload a quote opens past PAYLOAD_OPEN's reach: that quote becomes a command boundary (`;`), so the
    # script rules read the payload as a command; nothing else changes
    # blank on the RAW text, normalise after (Viktor 42695 HIGH 1): inside a quoted-delimiter body bash does not join
    # a backslash-newline, so the terminator must be looked for where bash looks; the blanking keeps the length, so
    # normalise() gives the same result on the blanked text
    span = data_heredoc_span(cmd, cwd)
    lx = lex_or_none(cmd)
    if lx is None:  # the old path (card fae0712e: fail-closed, today's decision)
        text = normalise(blank_span(cmd, span))
    else:
        # the blanking stands only where the lexer agrees: the body of the text's first heredoc, quoted delimiter
        first = lx['heredocs'][0] if lx['heredocs'] else None
        if span is not None and not (first and first['quoted'] and (first['bodyStart'], first['bodyEnd']) == span):
            span = None
        blanked = blank_span(cmd, span)
        for s in lexer_data_spans(cmd, cwd, lx):  # card 31045f4d: the lexer's data heredocs (see there)
            blanked = blank_span(blanked, s)
        blanked = nonshell_prose_masked(blanked, cmd, lx)
        view, extras = lexer_view(blanked, cmd, lx, cwd)  # both normalised already
        text = view + ''.join('\n' + e for e in extras)
    # card 74586987: a pipeline into a shell runs what it prints: its words as command lines, and every piece of them
    # as a file the script rules look up (stdin_pipelines); the pipes of a data heredoc's body are prose
    # (data_body_pipes_masked: only the pipeline reading changes, the script rules read `text` as before)
    pipe_src = text
    masked = data_body_pipes_masked(cmd, lx, cwd) if lx is not None else cmd
    if masked != cmd:  # the same steps as above, on the masked text (same length as cmd)
        pb = blank_span(masked, span)
        for s in lexer_data_spans(cmd, cwd, lx):
            pb = blank_span(pb, s)
        pview, pextras = lexer_view(nonshell_prose_masked(pb, cmd, lx), cmd, lx, cwd)
        pipe_src = pview + ''.join('\n' + e for e in pextras)
    pipe_lines, pipe_words = stdin_pipelines(pipe_src)
    text += ''.join('\n' + ln for ln in pipe_lines)
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
        paths = script_paths(cmd, cwd, text, pipe_words)
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
            'keresel, a subcommandot keresd magában (pl. grep find-generic-password). '
            # Klodel's rule for a false positive (card aeee72df, 31045f4d; Viktor 43236): said where it is needed
            'Ha hamis pozitív: a parancsot átalakíthatod, ha ugyanazt a csak-olvasó feladatot végzi, és jelzed a '
            'kártyán/Dave-nek; ha a cél egy kulcskarika-hívás átjuttatása, állj meg és szólj.\n')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
