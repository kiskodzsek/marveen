#!/usr/bin/env python3
"""PreToolUse gate (Bash): an agent shell does not read secrets out of the macOS keychain with `security`.

Why: Viktor 29950 (2026-11-06, card c1921b55). Every agent runs as the same macOS user, so any agent shell can
read any keychain item of that user (another agent's OAuth token, the Vault master key): the accepted structural
risk H1 of 2026-10-12. This gate is the cheap defense-in-depth Viktor asked for, NOT the fix: the fix is per-agent
isolation (H1). It does not see a keychain read made through Python/Node/Swift APIs, osascript's own keychain
calls, or a command name hidden in a variable or made by a substitution (`s=security; $s -i`) beyond the
hidden-name rule below. Do not rely on it.

Known limits (card deede5e4, Viktor r2 point 4 and 49151; the full list is "Not seen" under Script files below):
a relative script word whose directory or name comes from a value the gate does not bind passes unread: a
`while read` loop (piped or from a file), `select`, an arithmetic `for ((..))` loop, cdable_vars, find -execdir
with a relative script, and a variable reassigned after the cd that used it (`D=sub; cd $D; D=zz; python3 m.py`:
the cd is read with the last value of the name; the main gate passes it too).
What an xargs is fed (card 3bf9a741, Viktor 49280 LOW 2; old, main passes each too; the reading itself is described
at XARGS_RX): an xargs inside a quoted shell payload (`bash -c 'echo D | xargs K'`, `sh -c "..."`, an eval '...'
text, a nested `xargs -I{} sh -c 'echo {} | xargs K'`) is not read for its fed words; nor a file's content (`cat
list | xargs`, a redirect `xargs < list`, `-a list`), a computed name (find, an ls glob, tr), a shell expansion in a
fed word (a default param `${X:-..}`, a variable, a brace), a sh -c script reaching its words through $0 or bash -c
through "$@", an xargs whose name is split by quotes ('xa'rgs), and a while read loop's output piped into an xargs.
A script run through a variable's value (card 10624d73 r2, Viktor 49241; card 00c714ea narrows it, does NOT close
it: the KNOWN shapes below stay open): a value is expanded only in a positive shape (value_unread_names): a glob, a
blank or a brace in it at an unquoted use, an escape or an inner quote, or a name the text assigns split by quotes
("HO"ME=...) blocks the script word unread. A script word's brace expansion and glob are read in the shape the gate
models (brace_forms, resolve_lead_glob): Python's glob, [^x] read as [!x], ** recursive, the first match in byte,
case-folded and locale order (the environment's, en_US.UTF-8, hu_HU.UTF-8); a zsh group or qualifier paren in a
script word (`(m|x)easure.py`, `e(vil.py|x)`, `m*.py(.)`, `m*(N)`, `evil.py(.)`) blocks unread when one of its
member forms could match a file (zsh_paren_may_match, zsh_group_globs: zsh's choice among them is not modelled); a
text the lexer cannot read counts its script word as code (fail-closed).
Open, LOW and old (main passes each; Viktor 49408, the names are his independent probe's cases):
KNOWN-KTP-GLOB, a glob Python reads otherwise or not at all: posix-class and posix-alpha ([[:lower:]]vil.py),
  dotstar-bash (bash's .* matches .), dirglob-main (a glob matching a directory, its __main__.py runs), tilde-glob
  and tildeplus-glob (~/e*.py, ~+/e*.py), pwd-glob and pwdq-glob ($PWD/e*.py: a word with a $ is not globbed),
  zshnum-glob (e<->.py), and a locale other than the three above.
KNOWN-KTP-BRACE: brace-pad (e{01..02}.py), brace-step (e{1..3..2}.py), a blank in a member (brace-escblank
  {evil.py,a\\ b}, brace-quotedblank {evil.py,"a b"}).
KNOWN-KTP-WORD, which word is the script: bash-o (`bash -o errexit e*.sh`), node-r (`node -r ./ok.js e*.js`),
  glob-redirin (`</dev/null e*.py`). (direct-glob and direct-brace: closed by card 0196e1ee.)
What a pipe feeds a shell (card 0196e1ee, Viktor 43793 LOW/INFO 2): a glob or brace in the fed words, a reader in a
group or compound after the | (`| { bash; }`, `| while read l; do $l; done`, `| eval "$(cat)"`, `| /usr/bin/env
bash`, `| b"as"h`), a loop / if / case / function feeding it, an echo / printf substitution's output in place, and
a quoted substitution or backtick, a parameter operator (${F:-..}) or a backtick right before the pipe (unread) are
read (stdin_pipelines). The globs, the unread rule and a direct glob hold for a | or a word at a code position of the
command itself, of a heredoc body a shell reads (`bash <<'EOF'`, `. /dev/stdin <<X`, `cat <<'X' |` .. `bash`: its own
pipeline, not a shell word elsewhere on its line, _shell_reads_heredoc) or of an unquoted body's $( ); in a quote or
another heredoc body (a `python3 - <<'PY'` editing a file with `| bash` or a JSDoc `/**` in it: 165 fleet commands
blocked otherwise) the fed words are read as written, as before; a fed line's glob only as its first word or an
interpreter's script word (Viktor 49984). Open, LOW and old (main too):
KNOWN-FEED-PROG, a program that hands a line to a shell itself: py-os-system (os.system('echo ./e*.sh | bash') in a
  `python3 - <<'PY'` body: the glob in its string is read as written).
KNOWN-FEED-FILE, a file between the feeder and the shell: one the command writes and a shell then reads (`echo
  ./x.sh > p1; bash < p1`: the file does not exist when the gate reads), and the unread rule is not applied to a
  script file's body (a binary's bytes matched it).
KNOWN-FEED-CD, a cd the fed text or the reader makes: on separate fed lines (`printf 'cd sub\n./x.sh\n' | bash`) or
  in the reader's own group (reader-cd-fed: `| (cd sub && bash)`); the fed path is read from the command's cwd.
KNOWN-FEED-READER (Viktor 49925), a reader the gate does not take for a shell, or a loop that runs the line in a way
  it does not read: a reader word made by a quoted variable, an operator or a substitution (var-reader-q `| "$S"`,
  var-default `| ${S:-bash}`, subst-reader `| $(echo bash)`), zsh's zsh-equals (`| =bash`), a shell behind a for,
  case or function call (for-reader, case-reader, func-reader: `| for x in 1; do bash; done`, `| case 1 in 1) bash;;
  esac`, `f() { bash; }; .. | f`), a shell after another command of the group or the then-branch (true-then `| {
  true; bash; }`, if-two `| if true; then true; bash; fi`), a while-read loop that runs the line quoted or through
  command (while-quoted `"$a"`, while-command `command $l`) or is fed a glob (while-fed-glob), a process substitution
  (procsub-out: `> >(bash)`, `tee >(bash)`) and `| builtin eval "$(cat)"`. Another program's output (`echo "$(date)"
  | bash`) is H1, as everywhere.
KNOWN-KTP-VAR, a value not bound or bound otherwise: var-ifs, var-array (X=(evil.py)), array-index, var-append
  (X+=), zshsplit-var ($=X), zshglobsubst-var ($~X), var-ansic ($'..'), var-patsub (${X/a/b}), var-plusalt
  (${X:+..}), var-assigndefault (${X:=..}), var-escsemi, read-var, positional-glob (`set -- e*.py; python3 $1`),
  a zsh paren after an unexpanded value or substitution (`$X(easure.py|z)`, `$PWD/e(vil.py|x)`, `$(echo
  m)(easure.py|z)`), and a value set outside the command or by a substitution (`X=$(..)`), as everywhere below.
A backslash in a script word (card e3d2fd6e, under KNOWN-KTP-WORD: `./x\\.sh`, `\\./x.sh`): read at a code
  position, in a shell's payload and in a heredoc a shell reads; inside a quote of a command that may run it some
  other way (`ssh h './x\\.sh'`, `tmux send-keys './x\\.sh'`, `awk '{system("./x\\.sh")}'`) and in a
  heredoc into another program it is data, as on main; an unquoted-delimiter body only while it has no `$(` or
  backtick (the shell runs those: then every backslash word of it is read). A word after a shell's -c is read as a
  command (`bash -c '..' _ 'a ))\\/(( )) b'` blocks: a lean, as for a quoted or `$` word there on main). Open, on main
  too: a doubled backslash the shell halves before it runs the word (heredoc-sh-unq: `sh <<X` + `./x\\\\.sh`;
  eval-dbl: `eval ./x\\\\.sh`), and a backtick inside an unquoted data heredoc body (`` `./x.sh` ``).
KNOWN-KTP-OVER, not open but leans: they block a harmless call (old unless named new): every word a brace makes
  is read as a script (brace-seq, brace-empty, braceargs-benign, bracenested-alt, `python3 {l..n}easure.py
  stat.py` runs leasure.py), a zsh order qualifier (new: zshqual-om2, (On), (om): the order is not modelled),
  noglob-set, mixedquote-star ('*'e*.py), cdback-benign, varbrace-benign, and (new) a zsh paren in a call written
  as data (`cat <<'EOF'` or `python3 - <<'PY'` whose body holds `python3 (measure|zz).py x`) when a member matches
  a file: the "(" in the call's words makes the gate lex the call alone, as code (replay: 4 commands, gate probes).
  New in r3 (Viktor 49709): a `**` script glob whose walk passes MAX_STAR_DIRS directories (`python3 **/stat.py` in
  a large cwd: main passes it, this gate blocks it at once instead of on the 6 s watchdog); a whole-word group with
  no `|` and a substitution in it (a backtick `echo zq` and `, zz` in one group, the script word): zsh reads it as
  a glob qualifier and stops ("unknown file attribute"), the gate reads the substitution as unread.
  New in r4 (Viktor 49785 INFO): a `**` member of a zsh group (`(**/x.py|zz)`: zsh stops, "bad pattern", and bash
  has a syntax error, measured 11-21) is read as a `**` walk; a `**` over a link to a directory: Python's glob follows
  the link, zsh's `**/` does not (its `***/` does), so a script reachable only through a link blocks under `**/`.
  New in r5 (Viktor 49863 INFO and M1): a zsh group after `***/` whose matching members are all harmless
  (`***/(ok|zz).py`: any match blocks the group unread, as for every zsh paren); a brace whose second member is the
  one that matches (every brace word is read as a script, above); a loop value with `**` is read recursively in
  bash too, where without globstar it is one `*` (one more file read, never fewer). Viktor 49878 INFO: a quoted or
  escaped loop value (`for f in "a/*/*/measure.py"`, `'**/measure.py'`, `\\*`) is no glob in the shell, the gate
  reads it as one (the one-star form on main too).
A variable glued to a script word (card 8a73eab1, Dave's audit 11-16; Viktor 49425): the word is read with every
variable whose value the gate does not trust as unset and as set to "": one the text does not set, and one it sets in
an expansion the gate does not trust. Read in bash's and zsh's forms (`evil${X}.py`, `X=; python3 evil$X.py`,
`ev${X:-il}.py`, `ev${X+il}.py`, zsh `evil$X[1].py`, `evil$X:r.py`, `ev$X:h.py` as ev..py, `ev$+X.py` as ev0.py /
ev1.py, `${=X}`, `${${X}:-w}`, `${X/#/il}`, `${X:/*/il}` and `${X::=il}` as il, `ev${X:-i\\}l}.py` as evi}l.py,
`ev${X[1]:-il}.py`, zsh's modifier chain (`ev$X:h:s/./il/.py` as evil.py, `ev$X:&il.py`); var_readings, _zsh_chain).
A name list ${!P*} is any run: a glob in each base (the word's literal parts escaped), it blocks when a file
matches. Blocks as unread (Viktor 49502): a zsh flag group cut at its paren (what follows it may name a dot file or
a subdirectory), zsh :P, :a / :A after :h (the cwd), :& after :h, a modifier after a replacement, a NUL in the
word, a brace nested past MAX_VAR_NEST levels. Over-blocks (main passes
them): a value the text sets is read as empty too when the expansion is not trusted (`X=a; python3 evil$X.py`,
`export X=a;`, `X=; ev${X-il}.py`, `X='$Y'; python3 evil$X.py`), a single-quoted 'evil$X.py' and evil\\$X.py, zsh
`evil$X:h.py` (read with "" too), `${X+evil.py}` as an argv word, and bash's $_ in a word. Not read (old, main passes
them too): KNOWN-V1 one variable unset while another in the same word is "" (two readings, not every mix); KNOWN-V2 a
value from the environment, an earlier command or a loop (`X=ab; ev${X/ab/il}.py`, `X=xil; ev${X#x}.py`, `${X:=w}`
in an earlier command's argv, `for f in il`), and bash's indirection ${!X} through a name the text sets; KNOWN-V3 the
special parameters ($1, $@, $#, $?, ${?}, $!, $0) and the shell's own variables (`evil$OPTIND.py` runs evil1.py,
$SECONDS 0); KNOWN-V4 arithmetic ($((X)), $[X]: 0); KNOWN-V5 a variable in the command word, not the script word
(`$X python3 evil.py`, `python3$X evil.py`, `${X:-python3} evil.py`, `nice $X python3 evil.py`, `$X ./evil.sh`,
`source$X evil.sh`); KNOWN-V6 a glob or brace with the variable (`e$X*.py`, `e${X:-v?l}.py`, `{evil$X,x}.py`) and
IFS splitting (`X=a; IFS=a; python3 evil$X.py` runs ./evil); KNOWN-V7 a brace expansion in a default word
(`ev${X:-{i,}l}.py`, bash); KNOWN-V8 a name list of several names, split into words by the shell (the glob reads it
as one word); KNOWN-V9 a cut flag group in a heredoc body no shell reads as the heredoc (a cat or python body: prop2's
block hit JS template literals `${(a + b)}` there) stays a glob, so a script that body later hands to a zsh (`zsh -c
'./.e${(L)X}vil.py'` in a python body) is read without a dot file or a subdirectory after the paren.
Viktor 49582 (round 3; old, zsh only, main passes each too): KNOWN-V10 (mixed) two variables in one word, each with a
two-valued modifier chain (`ev$X:h:s/./il/$Y:h:s/q/q/.py`): the first-or-last mode is one per word, so the mix of one
replacement and one dot is not read; KNOWN-V11 (escaped) an escaped & in a :s replacement (`ev$X:h:s/./il\\&/.py`, zsh
runs evil&.py): the backslash is taken off before the chain, so the literal-& value is not read; KNOWN-V12 (sub-flag)
a subscript flag in an array index (`evil$X[(r)a].py`, `ev${X[(r)a]:-il}.py`): the word ends at the paren, the index
is not read. A script the command itself makes earlier (`cp x.py evil.py; python3 evil.py`): the gate reads the
files that exist when the hook runs, not the ones the command writes before it runs them.

What blocks (exit 2): a `security` call in command position whose subcommand reads or exports secrets:
  find-generic-password, find-internet-password, dump-keychain, export,
or that reads its subcommands from stdin (`security -i`, `security -p <prompt>`), which would hide the subcommand.
Made subcommand (card d58d5c30, Viktor 48033 LOW L2): `security` in command position whose first word after its
options is not literal (a $ or a backtick in it: `security $(echo dump-keychain)`, `security "$X"`, `security
dump-$(echo keychain)`, `eval security "$(..)"`, `bash -c "security $(..)"`) blocks, whatever it prints. A literal
subcommand with a made argument (`security find-certificate -c "$NAME"`) passes, and so does a loop variable over a
literal list of non-secret subcommands (`for s in add-trusted-cert create-keypair; do security $s -h; done`). Not
seen: a name with quotes inside it (`s"ec"urity $(..)`; the rule reads the text before the quote removal).
Known limits of the made-subcommand rule (Viktor 49221, Kernel's independent probe 49215; old, LOW, not seen on
main either): (1) a subcommand a glob makes at run time: only a $ or a backtick counts as "made" here; a glob in
the word (`security dump-k*`, `security [d]ump-keychain`, `security dump-keych?in`, zsh `(dump-keychai)n`) is the
glob-subcommand rule's below (card 04df07c5); brace expansion (`dump-{keychain,x}`) blocks here. (2) The
loop-variable exception and a sourced file: after `source f` or `. f` the gate still takes the loop variable for its
literal list value (`for s in add-trusted-cert; do :; done; . ./f.sh; security $s`, f.sh setting s=dump-keychain);
every rewrite the shell text itself shows (assignment, read, printf -v, mapfile, declare, eval, let, +=, a function,
unset with a default) blocks.
Glob subcommand (card 04df07c5, Viktor 49104 INFO 1, round 2 on Viktor 49398's tested proposal): `security` in
command position whose words, up to and including the first plain word that is not an option, hold a glob
(unquoted ? * [..], a zsh or extglob group, zsh ^ # ~ (#..) **/) that can match a secret subcommand name or -i / -p
blocks (`security dump-keychai?`, `security (dump-keychai)n`, `security @(dump-keychai)n`, `security -[i]`, `security
-v zz* dump-k*`): with a file of that name in the cwd the shell passes it. The word is read as the shell reads it: a
quoted blank, ; < > ) | is a char of a group alternative or a bracket member, a bracket's leading ! ^ and first ]
and its [:class:] are members; a redirect and its target, a quoted or escaped option and a word that globs are
walked past. The reading leans to a match (a bracket is any one char, a negated group any run) and stays linear:
words cut at 4096 chars, adjacent runs counted as one and more than 4 open runs read as any name. A glob that cannot
match one (`security list-k*`, eight stars and an x), a quoted or escaped glob char (`security 'dump-k*'`), and a
glob after the first plain non-option word pass.
Known limits of the glob-subcommand rule (Viktor 49398 independent probe, 99 cases; each old, main passes it too):
KNOWN-G1 eval re-globs a quoted or escaped star (`eval security "dump-k*"`); KNOWN-G2 a bash -c payload with an
escaped glob; KNOWN-G3 a shell function wrapping the name (glob or literal); KNOWN-G4 find -execdir with an
unqualified name; KNOWN-G5 the command name itself globbed (`/usr/bin/sec*`); KNOWN-G6 the name split by quotes
(`sec"ur"ity dump-k*`). Over-blocks (main passes them): KNOWN-G7 prose right after an opening quote (`echo "security
dump-k* ..."`) and a heredoc body to cat; KNOWN-G8 an uppercase word without nocaseglob and a bracket no file name
can match; KNOWN-G9 1 MB of nested extglob star groups (3.8 s, main the same). A `script -q` wrapper blocks: on the
mini the wrapped call ran (Kernel's run of the probe), in a sandbox with no terminal it did not (Viktor's).
Hidden name (card 03a336e5, Viktor 47750/47751 LOW): a simple command whose first word is not literal (a $ or a
backtick in it: `$(echo security)`, `` `echo security` ``, `$s`, `${S:-security}`, `sec$(echo urity)`) and that has
find-generic-password, find-internet-password or dump-keychain as a word of its own blocks, whatever the name
turns out to be (the gate cannot know what a substitution prints). A literal first word (`echo $(...) dump-keychain`),
`export` / -i / -p after a made name, and a subcommand that is made too (`$s dump-$(echo keychain)`) are not seen.
It reads the command text, and a file the command names only where a shell may run that file (no data or non-shell
extension, a shell shebang, or a shell / source / . before its name): a made name inside a Python or Node file
(`os.system('$S dump-keychain')`) is not seen, a JSON or Markdown text quoting the forms passes.
Command position: the start of the command, or after ; & | ( ) { } a newline, a backtick, $( , an opening quote
(`bash -c "security ..."`, `ssh host 'security ...'`), after find's -exec / -execdir / -ok, and after the
wrapper and keyword words env, sudo, doas, sandbox-exec, exec, command, nohup, time, nice, xargs, caffeinate, arch,
builtin, timeout, stdbuf, setsid, if, then, else, elif, do, while, until, zsh's coproc, noglob, nocorrect and
repeat (card d58d5c30, Viktor 49221 MEDIUM: `noglob security find-...` ran in zsh, the agent shell), `!`, their
flags, numbers (`timeout 5`, `repeat 1`,
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
Known false positive: a quoted string that starts with the blocked call (`grep "security dump-keychain" f`, and
since card d58d5c30 `grep "security $(date)" f`, and a quoted text whose closing backtick of a quoted call is
followed by a quote: `git commit -m "doc: run `security list-keychains`"`, Viktor 48765 F01; and `xargs -i security
{}`, which macOS xargs does not run): search for the subcommand alone instead, or write a name that is not the call.
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
    interpreter runs or eval does, also a `< file` redirect (`0<f`, `a1<f` too) and the files of a `cat`, a path to it
    too (`cat m.py | python3`, `eval "$(/bin/cat m.sh)"`, quoted too), and of a `head` / `tail` in a substitution or
    piped into an interpreter (`eval "$(head m.sh)"`, `tail m.py | python3`; card 3bcd4514); and a
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
  ('sec' + 'urity'), keychain APIs (Security.framework, keyring), a variable set outside the command (card
  deede5e4: a value made of variables set before it in the command is read, `B=/x; O=$B/y`; a for-loop variable over
  plain words or globs is read as each of its values, in a cd target too; over anything else, a substitution, the
  script word blocks unread; a plain assignment of the same name is read as one more value, Viktor deede5e4 r2 P2),
  a value bound some other way than `for NAME in` or NAME= (while read, read, select, for ((..)), set --, $1 of a
  bash -c, case, find -execdir with a relative script, xargs, cdable_vars, a CDPATH: Viktor deede5e4 r2 point 4,
  left Not seen), a relative script word after a directory change the gate does not follow (pushd,
  `cd $(..)`, `cd $T`, env -C, a cd of option words only, a quoted cd or pushd name, a ~ or brace target, a target
  glued to a redirection: every such word of the call blocks unread, card deede5e4, Viktor L1 and r2 P3; a target
  with `..` is read logically AND physically, set -P / cd -P, r2 R1; $PWD and ~+ in a script word are read on each
  base), a quoted path
  with spaces, an interpreter whose own name a substitution makes (`$(echo python3) m.py`, `p=python3; $p m.py`;
  Viktor 43662 INFO 1, 47750: left INFO), a Ruby %w list, a payload a quote opens after other commands (`command '...'`, `time '...'` run a
  command literally named so, which fails). A wrapped script (`sudo -u root python3 m.py`, `ssh localhost python3
  m.py`, `sg staff 'python3 m.py'`) is read like any other (card 3085a683; for ssh the file is looked up here, which
  is right for localhost and a fail-closed guess for a remote host). The gate's own test assembles its fixtures at
  run time, but running it by its path from an agent shell IS blocked (payload caps, the escaped-name rows; card
  deede5e4, measured): CI runs it; in an agent shell its author runs it and notes it on the card as a false
  positive (Viktor deede5e4 r2 INFO 1).
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
import bisect
import json
import os
import re
import stat
import sys
import time

WRAPPERS = (r'(?:env|sudo|doas|sandbox-exec|exec|command|nohup|time|nice|xargs|caffeinate|arch|builtin|timeout|stdbuf|setsid'
            r'|if|then|else|elif|do|while|until|eval|watch|coproc|noglob|nocorrect|repeat)')
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
# Card 946937b7 (Viktor 45520): an assignment's value may hold quoted blanks (`A="a b" python3 m.py`, an everyday
# shape): a quoted run is part of the value. Each alternative starts with its own char (WORD has no quote), and a
# quoted run ends at the next quote or newline, so a token still reads one way only. An escaped char is part of it
# too (Viktor 45626 R4a: `A=a\ b python3 m.py` ran m.py); the plain run has no backslash, so the alternatives do not
# overlap, and the unrolled loop has no possessive quantifier (the fleet's /usr/bin/python3 is 3.9). Timed on 3.9
# against the GIT_CONFIG_PARAMETERS x 20 000 row (full tree, lexer loaded): this form 5.26 s, one char or run per
# step `(?:plain|esc|quoted)*` 5.7 s, a lookahead before the runs 5.26 s, main's WORD* 4.9-5.0 s.
ASSIGN_VALUE = r'[^\s;&|(){}`\'"\\]*(?:(?:\\[\s\S]|"(?:[^"\\\n]|\\.)*"|\'[^\'\n]*\')[^\s;&|(){}`\'"\\]*)*'
CHAIN = (r'(?:(?:' + WRAPPERS + r'\b|!|-(?!(?:exec|execdir|ok)(?=\s))' + WORD + r'*|' + REDIR + r'|[+.]?\d[\w.]*|\w+='
         + ASSIGN_VALUE + r')[ \t]+)*')
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


class NeedRule:
    """A rule pattern searched only where a literal it cannot match without is in the text (card 7ef651a9).

    Why: a POSITION pattern tries its command-position alternation at every character, about 0.1 s per rule on a
    2.5 MB command (`GIT_CONFIG_PARAMETERS=x... ` x 20000: 1.1 s of the hook's 4.4 s in five such rules, measured
    2026-11-20), and the wrapper timing case ran on its 5 s cap. A literal search is about 0.01 s.
    Sound only when `need` is a piece EVERY match contains: written once, outside any alternation, ?, * or {0,}, in
    `rx`. Then a match of `rx` contains a run that `need` matches with the same flags (re.I compares per character),
    so no `need` hit means no `rx` hit; the test checks each rule against its plain pattern on every BLOCK and ALLOW
    case. Same `search(text)` call as a compiled pattern."""
    def __init__(self, need, rx):
        self.rx, self.pattern, self.flags = rx, rx.pattern, rx.flags
        self.need = re.compile(re.escape(need), rx.flags)

    def search(self, text):
        return self.rx.search(text) if self.need.search(text) else None


RULES = [
    ('secret-read', NeedRule('security', re.compile(POSITION + BINARY + OPTIONS + r'\s+' + SECRET_SUB + r'(?![\w-])',
                                                    re.I))),
    ('stdin-mode', NeedRule('security', re.compile(POSITION + BINARY + r'(?:\s+-\S+)*?\s+-[a-z]*[ip][a-z]*'
                                                   r'(?=\s|$|[;&|)`\'"])', re.I))),
]  # + made-subcommand (card d58d5c30), after FnRule below
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
    ('git-credential', NeedRule('credential', re.compile(POSITION + r'credential[ \t]+(?:fill|approve|reject)'
                                                         r'(?![\w-])', re.I))),
    ('git-credential-helper', NeedRule('credential-osxkeychain', re.compile(
        POSITION + r'\\?[\'"]?(?:' + WORD + r'*/)?(?:git-)?credential-osxkeychain(?![\w-])', re.I))),
    # choosing the helper: `git -c credential.helper=osxkeychain ...`, `git config [flags] credential.helper
    # osxkeychain`, GIT_CONFIG_PARAMETERS / GIT_CONFIG_VALUE_<n>; not the words in prose (a commit message that says
    # "the system config sets credential.helper=osxkeychain" passes: two of 19 861 replayed commands were such)
    ('git-credential-helper', NeedRule('osxkeychain', re.compile(
        r'(?<![\w-])-c[ \t]+[\'"]?credential' + HELPER_SCOPE + r'\.helper=[\'"]?!?[^\s\'";|&]*osxkeychain', re.I))),
    ('git-credential-helper', NeedRule('osxkeychain', re.compile(
        POSITION + r'config(?:[ \t]+-' + WORD + r'*)*[ \t]+[\'"]?credential' + HELPER_SCOPE
        + r'\.helper[\'"]?[ \t]+[\'"]?!?[^\s\'";|&]*osxkeychain', re.I))),
    # (GIT_CONFIG_PARAMETERS / GIT_CONFIG_VALUE_<n> naming osxkeychain: env_value_hit below, linear)
    # card 49d58372 (Viktor 42039 MEDIUM 1): a config the command names by indirection brings the helper back, the
    # name of osxkeychain in a file the rules cannot read: `-c include.path=<file>`, `--config-env=credential.helper=
    # VAR` / `--config-env=include.path=VAR`, an include in GIT_CONFIG_PARAMETERS / GIT_CONFIG_KEY_<n> (all measured
    # on git 2.54, Apple Git-157: the helper of the named file or variable is called after the ~/.gitconfig reset)
    ('git-config-override', NeedRule('include', re.compile(r'(?<![\w-])-c[ \t]+[\'"]?' + INCLUDE_KEY + r'=', re.I))),
    ('git-config-override', NeedRule('--config-env', re.compile(
        r'(?<![\w-])--config-env(?:=|[ \t]+)[\'"]?(?:credential' + HELPER_SCOPE + r'\.helper|' + INCLUDE_KEY + r')=',
        re.I))),
    ('git-config-override', NeedRule('GIT_CONFIG_KEY_', re.compile(
        r'(?<![\w-])GIT_CONFIG_KEY_\d+=[\'"]?' + INCLUDE_KEY + r'(?![\w.-])', re.I))),
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
    function walks the wrappers itself, and a bound inside `git;config ...` would cut git from its own options.
    raw (card d58d5c30): judged only on the texts before the quote removal: the removal turns quoted data into a
    command position (`grep "a\\|security" $F` read as `a|security $F`)."""
    def __init__(self, fn, plain=False, raw=False):
        self.search, self.plain, self.raw = fn, plain, raw


GIT_RULES += [('git-credential-helper', FnRule(lambda t: env_value_hit(t, _PARAMS_RX, _OSXKEYCHAIN_RX))),
              ('git-config-override', FnRule(lambda t: env_value_hit(t, _ONLY_PARAMS_RX, _INCLUDE_NAMED_RX))),
              ('git-config-override', FnRule(config_override, plain=True)),
              ('git-config-override', FnRule(config_write))]

# card d58d5c30 (Viktor 48033 LOW L2): the literal name with a subcommand the shell makes at run time (`security
# $(echo dump-keychain)`, `` `echo ...` ``, `"$X"`, `${X}`, `dump-$(echo keychain)`, `eval security "$(..)"`,
# `bash -c "security $(..)"`): bash and zsh ran the secret subcommand, main allowed all 11 forms (measured 11-20, a
# stub on PATH). What the substitution prints is unknown here, so the first word after the options that is not
# literal blocks, whatever it turns out to be (the mirror of the hidden-name rule). Not literal: a $ that starts an
# expansion ($x, ${, $(, $', $", $@ ...), a brace list or range (`{dump-keychain,}`, `dump-{keychain,x}`, `{a..b}`),
# or a backtick that OPENS a substitution. A backtick closes the code span or substitution it stands in (`` `security
# add-trusted-cert` `` in prose, `` `security ...`, ``, `` `SECURITY NOTICE` ``: the fleet replay of 11-20 had 20 such
# rows of documentation and gate texts) only when BOTH: an odd number of backticks stands before it (Viktor 48765
# P1: `` security ` printf dump-keychain` `` opens with a blank after it), and no command's first char follows it
# (an escaped `\`` or a backtick in a comment or in single quotes counts in the parity, and `` echo \`; security
# `printf dump-keychain` `` ran in bash and zsh: parity alone let it pass, measured 11-20, d58d5c30 r2).
# xargs gives the call its subcommand from stdin (Viktor P4): no word after the options, or the -I / -i / -J string
# in it.
# Read on the texts before the quote removal only (FnRule raw): the removal made `grep "x\|security" $F` a pipe into
# `security $F` (a replay row). The quoted name is read here instead: "security" / 'security' (\security needs
# nothing: normalise() takes the backslash off a letter; the mutation round's `\\?` changed no verdict), its
# opening quote after a command position (POSITION counts a quote as one, so a lookbehind on the quote made every
# quoted argument a command: `grep -n "security" "$K"`, a row of the replay's second run).
# One form is read: a loop variable over a literal list (`for s in add-trusted-cert create-keypair; do security $s
# -h`, Viktor's and Kernel's help loops in the same replay): when every `for <var> in` list of that variable in the
# text is plain words, none a secret subcommand or an option, and the variable's name occurs nowhere else in the text
# but in `for NAME in` and as a whole `$NAME` / `${NAME}` (Viktor P3: printf -v, `${s:=}`, zsh `for s (..)`, select,
# foreach name it otherwise), the call is the list's subcommands and passes. Any other word equal to the name counts,
# quoted or escaped too (`printf -v 's'`, `printf -v \s` name it): a one-letter name also in `sed 's/^ *//'` or
# `grep '^\s+-'` blocks the loop (one fleet replay row, Kernel's help loop, 11-20); a longer name passes.
_MADE_SUB_RX = re.compile(POSITION + r'(?:"' + BINARY + r'"|\'' + BINARY + r"'|" + BINARY + r')'
                          + OPTIONS + r'(?:\s+(?=([^\s;&|<>`]*)(\$[\w({@*#?!$\'"-]|`|\{[^\s{}]*(?:,|\.\.))))', re.I)
_BT_OPENS_RX = re.compile(r'[\w$(/\\{"\'-]')  # a command's first char after a backtick: it opens a substitution
# The command xargs runs is found by its WRAP_ARGS walk (wrap_command_start: its flags and their words, one way to
# read each word), not by a regex over the words between: `[^;&|\n]*?` took any word there, and with no end to the
# name the call was `xargs grep securityProfile` and `xargs grep -l security` (d58d5c30 r2 fleet replay: 14 runs of
# another gate's test, whose rows hold the first, blocked; Viktor's, Kernel's and mine).
_XARGS_RX = re.compile(r'(?<![\w-])xargs\b', re.I)
_XARGS_CALL_RX = re.compile(r'(?:' + WORD + r'*/)?(["\']?)security\1(?![^\s;&|)<>])((?:[ \t]+-\S+)*)'
                            r'(?:[ \t]+([^\s;&|)<>]+))?', re.I)


def _xargs_sub(text):
    for x in _XARGS_RX.finditer(text):
        k = wrap_command_start(text, x.end(), 'xargs', True)
        # Viktor 48860 LOW 2 (his prop2 J2): `xargs env security`, `xargs nice -n 5 security`: walk each wrapper the
        # command is, up to WRAP_PASSES (past that: not read, blocks)
        for _ in range(WRAP_PASSES):
            if k is None or k < 0:
                break
            w = _WRAP_NAME_RX.match(text, k)
            if not w:
                break
            k = wrap_command_start(text, w.end(), w.group(1).lower(), True)
        else:
            k = -1
        if k is None:
            continue
        if k < 0:
            return x  # past MAX_ARGS flag words: not read, blocks (as wrapper_bounds)
        m = _XARGS_CALL_RX.match(text, k)
        if not m:
            continue
        if m.group(3) is None:
            return m
        r = re.search(r'\s-(?:[IJ][ \t]*(\S+)|i(\S*))', ' ' + text[x.end():k])  # BSD -J % puts it at the % too
        if r and (r.group(1) or r.group(2) or '{}') in m.group(3):
            return m
    return None


_MADE_VAR_RX = re.compile(r'"?\$(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))"?(?=[\s;&|)]|$)')
_FOR_RX = re.compile(r'(?<![\w$-])for[ \t]+([A-Za-z_]\w*)[ \t]+in[ \t]+([^;\n]*)')
_LIST_WORD_RX = re.compile(r'[A-Za-z0-9_./:+=,@%^-]+')
_SECRET_SUB_RX = re.compile(SECRET_SUB, re.I)
_SECRET_SUB_NAMES = tuple(SECRET_SUB[3:-1].split('|'))  # the alternatives of SECRET_SUB, one source
_PREFIX_UNSURE_RX = re.compile(r'[$`{}*?\[\]~()^#]')  # Viktor r3: zsh (..), ^, # and bash extglob @(..) glob too


def _prefix_rules_out(prefix):
    """True when the literal start of the made word already rules out every secret subcommand: whatever the shell
    makes after it, the word starts with this, and no secret subcommand (nor an abbreviation of one) does. Quotes and
    backslashes are taken off; a `$`, a backtick, a brace, a glob or a tilde in it: not sure, not ruled out."""
    if not prefix or _PREFIX_UNSURE_RX.search(prefix):
        return False
    lit = prefix.replace('\\', '').replace('"', '').replace("'", '').lower()
    return not any(n.startswith(lit) for n in _SECRET_SUB_NAMES)  # an empty start ('"$X"') rules out nothing


_READ_VAR_RX = re.compile(r'\$(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))')
_NAME_WORD_RX = re.compile(r'(?<![\w])[A-Za-z_]\w*')


def _literal_loops(text):
    """The names that are for-loop variables over plain non-secret words only, and that occur NOWHERE else in the
    text but in `for NAME in` and as a whole `$NAME` / `${NAME}` word (Viktor prop: printf -v, unset + ${s:=},
    zsh ${s::=}, zsh for s (..), select, foreach all name the variable some other way)."""
    lists, spans = {}, set()
    for m in _FOR_RX.finditer(text):
        lists.setdefault(m.group(1), []).append(m.group(2).split())
        spans.add(m.start(1))
    uses = {m.start(1) if m.group(1) else m.start(2) for m in _READ_VAR_RX.finditer(text)}  # $s=1 only reads
    other = set()  # one pass over every name-like word: a name seen outside `for NAME in` and `$NAME` is taken
    for o in _NAME_WORD_RX.finditer(text):
        if o.group(0) in lists and o.start() not in spans and o.start() not in uses:
            other.add(o.group(0))
    return {n for n, ls in lists.items() if n not in other and all(ls) and all(
        _LIST_WORD_RX.fullmatch(w) and not w.startswith('-') and not _SECRET_SUB_RX.fullmatch(w)
        for words in ls for w in words)}


def _real_backticks(text):
    """The positions of the backticks the shell reads as a substitution's ends (Viktor 48860 LOW 1: an escaped
    `\\``, a `'`'`, a `$'\\`'` or a commented backtick before the real opener made it look odd). A closing backtick
    needs an odd count by this AND by the plain count. One reading per text, counted with bisect.
    The lexer's reading: the backticks of the code class. Not his hand count (prop2 J1), measured with bash and zsh
    (r3/gbt-hd3): `cat <<'E'` + a body holding one backtick + `<name> ` printf dump-keychain`` ran dump-keychain, and
    the hand count took the literal body backtick for real. A heredoc body, quoted or not, is read apart from the line
    around it, so none of its backticks counts (`<<\\E` reaches here as `<<E`: normalise takes the backslash off a
    letter). When the lexer does not read the text (a problem such as a trailing unclosed quote, which bash runs the
    lines before; or past its bounds): no backtick is real, so every one after the name opens and blocks (the hand
    count there let the heredoc form with a trailing `echo "` through, bash ran it: r3/gbt-hd4)."""
    lx = lex_or_none(text)
    if lx is None:
        return []
    cls = lx['cls']
    return [b.start() for b in re.finditer('`', text) if cls[b.start()] == 'c']


def made_subcommand(text):
    """The made-subcommand rule (card d58d5c30, see above); a literal search for the name first (as NeedRule)."""
    if 'security' not in text.lower():
        return None
    x = _xargs_sub(text)
    if x:
        return x
    loops = plain = real = None
    for m in _MADE_SUB_RX.finditer(text):
        bt = m.end() + len(m.group(1))
        if m.group(2) == '`':
            if plain is None:  # positions once, counted with bisect: text.count(.., 0, bt) per call was quadratic
                plain = [b.start() for b in re.finditer('`', text)]  # (50 000 closing spans, 1.15 MB: 7.1 s, r3)
                real = _real_backticks(text)
            if (bisect.bisect_left(plain, bt) % 2 and bisect.bisect_left(real, bt) % 2
                    and not _BT_OPENS_RX.match(text, bt + 1)):
                continue  # an odd count before it (plain AND real) and no command's first char after it: it closes a span
        if _prefix_rules_out(m.group(1)):
            continue  # `<name> definer`...`: no secret subcommand starts with the word's literal start
        v = _MADE_VAR_RX.match(text, m.end())
        if v:
            if loops is None:
                loops = _literal_loops(text)
            if (v.group(1) or v.group(2)) in loops:
                continue
        return m
    return None


RULES += [('made-subcommand', FnRule(made_subcommand, raw=True))]

# card 04df07c5 (Viktor 49104 INFO 1, d58d5c30 round 4 rows J12-J14): the literal name with a subcommand word that
# globs, no substitution in it (`security dump-keychai?`, zsh `security (dump-keychai)n`, bash extglob
# `security @(dump-keychai)n`). With a file of the secret name in the cwd (the agent can create it first, even in the
# same command) bash and zsh ran the secret subcommand; main allowed all three (measured by Viktor, shell3.txt). The
# made-subcommand rule looks for a $ or a backtick, so it is not the place. Here: the first word after the options is
# read as a shell pattern (unquoted ? * [..], a zsh or extglob group (..) with its | alternatives and an @ ? * + !
# before it, zsh's ^ negation, x# / x## repetition, a~b exclusion and (#i) flags), and it blocks when the pattern
# can match a secret subcommand name (SECRET_SUB, case folded like the secret-read rule). The reading leans to a
# match: a bracket is any one char, a negated group or a ^ is any run, a~b is read as a, an unknown (#..) flag is
# any run. A quoted or backslash-escaped glob char is literal (`security 'dump-k*'` passes: security
# gets the literal word, no such subcommand). A $ or a backtick in the word is the made-subcommand rule's, a brace
# list too (it blocks there). Read on the texts before the quote removal (raw), as made-subcommand.
_GLOB_SUB_RX = re.compile(POSITION + r'(?:"' + BINARY + r'"|\'' + BINARY + r"'|" + BINARY + r')' + OPTIONS
                          + r'[ \t]+(?=[^\s;&|`])', re.I)  # Viktor r1: < > may start the next word (a redirect)
_GLOB_WORD_END = set(' \t\n;&|<>`')
_GLOB_SEP = ' \t\n;&<>`'  # the word end outside quotes; not |: a group's alternatives (the loop stops at it outside)
_GLOB_MAX_DEPTH = 8
_GLOB_MAX_WORD = 4096  # Viktor r1: a longer word is read as any name (the reading leans to a match), and stays linear
_GLOB_MAX_WORDS = 32  # Viktor r1: words walked after the name and its options
_GLOB_MAX_RUNS = 4  # Viktor r1: more open runs than this read as any name (no backtracking blow-up in the regex).
# Kernel r2: 4, not 6: a word of 6 runs cost up to 0.88 ms per fullmatch round (`*?*?*?*?*?*?x`), so 40 000 such
# words in one command took 36 s (the watchdog blocks: an over-block); 4 runs cost at most 0.074 ms
_GLOB_REDIR_RX = re.compile(r'(?:\d+|&)?[<>]+[&|]?')
_GLOB_TARGETS = _SECRET_SUB_NAMES + ('-i', '-p')


def _glob_word_end(text, i):
    """Viktor r1 (card 04df07c5): (end, cut) of the shell word at i: the first blank or command end OUTSIDE quotes. A
    quoted blank, ;, <, > is a char of the word, and in a group or a bracket one alternative or member among others
    (a group alternative or a bracket member with a quoted blank ran the secret subcommand). A backslash escapes. cut
    is True past _GLOB_MAX_WORD chars (the caller reads the first _GLOB_MAX_WORD chars as the pattern and the rest
    as any run). A | or a ) outside every group ends the word too (a pipe, the end of a subshell): without it each
    of `security list-k*|` x 80000 scanned to the cap (9.8 s)."""
    n, q, s, depth = len(text), '', i, 0
    while i < n:
        if i - s > _GLOB_MAX_WORD:
            return i, True
        c = text[i]
        if q:
            if c == q:
                q = ''
            elif c == '\\' and q == '"':
                i += 1
        elif c == '\\':
            i += 1
        elif c in '\'"':
            q = c
        elif c == '(':
            depth += 1
        elif c == ')' or c == '|':
            if not depth:
                return i, False
            depth -= c == ')'
        elif c in _GLOB_SEP:
            return i, False
        i += 1
    return n, False


def _glob_bracket_end(text, i, n):
    """Viktor r1: the index of the ']' that closes the bracket at i, or -1: a leading ! or ^ and a first ] are
    members, a [:class:] [.x.] [=x=] is read whole, a quoted or escaped char is a member (each of these ran it)."""
    j = i + 1
    if j < n and text[j] in '!^':
        j += 1
    if j < n and text[j] == ']':
        j += 1
    while j < n:
        c = text[j]
        if c == ']':
            return j
        if c == '\\':
            j += 2
            continue
        if c in '\'"':
            k = text.find(c, j + 1, n)
            if k < 0:
                return -1
            j = k + 1
            continue
        if c == '[' and j + 1 < n and text[j + 1] in ':.=':
            k = text.find(text[j + 1] + ']', j + 2, n)
            if k >= 0:
                j = k + 2
                continue
        j += 1
    return -1


def _glob_word(text, i):
    """The shell word at i as (pattern pieces, globbed): each piece ('lit', s) or ('any'|'one', None) or ('grp',
    prefix, [alternatives]) or ('rep', piece, '*'|'+'); the word ends at a blank or a command end outside quotes and
    groups, or at a ')' with no group open. None when a $ or a backtick is in it (made-subcommand's), or a group is
    left open. Linear: one scan to the word end (_glob_word_end, capped), groups nested deeper than _GLOB_MAX_DEPTH
    read as any run."""
    n, cut = _glob_word_end(text, i)
    if cut:  # the capped prefix is the pattern, the rest any run (a 1 MB `?` word still cannot match a short name)
        w = _glob_word(text[i:n], 0)
        return ([('any', None)] if w is None else w[0] + [('any', None)]), True
    out, globbed, w0 = [], False, i
    while i < n:
        c = text[i]
        if c in _GLOB_WORD_END or c == ')':
            break
        if c in '$`':
            return None
        if c == '\\':
            out.append(('lit', text[i + 1:i + 2]))
            i += 2
            continue
        if c in '\'"':
            j = text.find(c, i + 1, n)
            j = n if j < 0 else j
            if c == '"' and ('$' in text[i + 1:j] or '`' in text[i + 1:j]):
                return None
            out.append(('lit', text[i + 1:j]))
            i = j + 1
            continue
        if c == '(' and text.startswith('(#', i):  # zsh glob flags: (#i) and the like change no name here
            j = text.find(')', i, n)
            if j < 0:
                return None
            if text[i + 2:j] not in ('i', 'I', 'l', 'b', 'B', 'm', 'M', 'q'):
                return [('any', None)], True  # (#a1) approximate and the rest: the whole word can match anything
            globbed, i = True, j + 1
            continue
        if c in '@?*+!' and i + 1 < n and text[i + 1] == '(' or c == '(':
            pre = '' if c == '(' else c
            k = i + (0 if c == '(' else 1)
            depth, j, alts, start = 0, k, [], k + 1
            while j < n:
                if text[j] == '\\':
                    j += 2
                    continue
                if text[j] in '\'"':  # Viktor r1: a quoted ) or | is a char of the alternative
                    q = text.find(text[j], j + 1, n)
                    if q < 0:
                        return None
                    if text[j] == '"' and ('$' in text[j + 1:q] or '`' in text[j + 1:q]):
                        return None
                    j = q + 1
                    continue
                if text[j] == '(':
                    depth += 1
                    if depth > _GLOB_MAX_DEPTH:
                        return [('any', None)], True
                elif text[j] == ')':
                    depth -= 1
                    if depth == 0:
                        break
                elif text[j] == '|' and depth == 1:
                    alts.append(text[start:j])
                    start = j + 1
                elif text[j] in '$`':
                    return None
                j += 1
            if j >= n:
                return None
            alts.append(text[start:j])
            out.append(('grp', pre, alts))
            globbed, i = True, j + 1
            continue
        if text.startswith('**/', i):  # Viktor r1: zsh (and bash globstar) **/ matches zero directories too
            out.append(('any', None))
            globbed, i = True, i + 3
            continue
        if c == '*':
            out.append(('any', None))
        elif c == '?':
            out.append(('one', None))
        elif c == '[':
            j = _glob_bracket_end(text, i, n)
            if j < 0:
                out.append(('lit', c))
                i += 1
                continue
            out.append(('one', None))
            i = j + 1
            globbed = True
            continue
        elif c == '^':  # zsh negation: anything but the rest, so it can match any name
            out, i = [('any', None)], n
        elif c == '#':  # zsh: the element before it, zero or more times (## once or more)
            prev = out.pop() if out else ('lit', '')
            plus = text.startswith('##', i)
            if prev[0] == 'rep':  # Kernel r2: `x###...` nested a quantifier per # ((?:(?:x)*)*: 14 # took over 2 s);
                prev, plus = prev[1], False  # a # on a repetition is zero or more of its element (a superset: leans)
            out.append(('rep', prev, '+' if plus else '*'))
            globbed, i = True, i + (2 if plus else 1)
            continue
        elif c == '~' and i > w0:  # zsh exclusion `a~b`: what a matches less what b matches; a is enough here
            globbed = True
            break
        else:
            out.append(('lit', c))
            i += 1
            continue
        globbed, i = True, i + 1
    return out, globbed


def _glob_regex(pieces, runs):
    """The pieces of _glob_word as (regex text, literal only), leaning to a match. runs: a one-item list, the open
    runs left (Viktor r1: `security ************x` took 5 s and 14 stars hit the watchdog, main 0.05 s): adjacent
    runs are one, a `*(..)` or `!(..)` group, and a repeated group or element (`+(..)`, x#) whose inside is not
    literal, is one open run, and
    the caller reads the word as any name when runs[0] < 0. A bare group at the end may be a zsh qualifier (`(.)`,
    `(N)`), so it is optional."""
    parts, lit = [], True

    def run():  # only a new run counts: merged adjacent runs are one (8 stars + x is `.*x`, no secret name)
        if not parts or parts[-1] != '.*':
            runs[0] -= 1
            parts.append('.*')

    for k, p in enumerate(pieces):
        if p[0] == 'lit':
            parts.append(re.escape(p[1]))
        elif p[0] == 'any':
            lit = False
            run()
        elif p[0] == 'one':
            lit = False
            parts.append('.')
        elif p[0] == 'rep':
            inner, ilit = _glob_regex([p[1]], runs)
            lit = lit and ilit
            if ilit:
                parts.append('(?:' + inner + ')' + p[2])
            else:
                run()
        else:
            pre, alts = p[1], p[2]
            # Viktor r1: `*(` is an extglob group in bash but a star and a qualifier (or a group) in zsh: zsh ran
            # `dump-k*(.)`. A run covers both readings (each matches only what `.*` matches).
            if pre in ('!', '*'):  # not `pre in '!*'`: '' is in every string (a bare group read as any run)
                lit = False
                run()
                continue
            sub, glit = [], True
            for a in alts:
                w = _glob_word(a, 0)
                if w is None:
                    sub.append('.*')
                    runs[0] -= 1
                    glit = False
                else:
                    r, rl = _glob_regex(w[0], runs)
                    sub.append(r)
                    glit = glit and rl
            lit = lit and glit
            if pre == '+' and not glit:
                run()
                continue
            last = k == len(pieces) - 1
            alt = '(?:' + '|'.join(sub) + ')'
            if pre == '?':  # bash extglob: zero or one; zsh: any one char, then the group (a qualifier when last)
                lit = False
                parts.append('(?:' + alt + '?|.' + alt + ('?' if last else '') + ')')
                continue
            q = {'': '', '@': '', '+': '+'}[pre]
            if not q and last:
                q = '?'
            parts.append(alt + q)
    return ''.join(parts), lit


def _glob_can_match(pieces):
    """Viktor r1: True when the pattern can match a secret subcommand or -i / -p (too many open runs: True)."""
    runs = [_GLOB_MAX_RUNS]
    rx, _ = _glob_regex(pieces, runs)
    if runs[0] < 0:
        return True
    rx = re.compile(rx, re.I | re.S)
    return any(rx.fullmatch(name) for name in _GLOB_TARGETS)


def _glob_walk(text, i):
    """Viktor r1: from the first word after the name and its options, True when a word that globs can match a secret
    subcommand or -i / -p; checked on each word up to and including the first plain word that is not an option. On
    the way it passes a redirect and its target (`>/dev/null dump-k*`), a quoted or escaped option (`"-v"`, `\\-q`),
    and a word that globs (it may be an option, `[-]v`, or vanish under nullglob or zsh (N): `zz* dump-k*`)."""
    n = len(text)
    for _ in range(_GLOB_MAX_WORDS):
        while i < n and text[i] in ' \t':
            i += 1
        r = _GLOB_REDIR_RX.match(text, i)
        if r:
            i = r.end()
            while i < n and text[i] in ' \t':
                i += 1
            i = _glob_word_end(text, i)[0]
            continue
        if i >= n or text[i] in '\n;&|)':
            return False
        e, cut = _glob_word_end(text, i)
        w = _glob_word(text[i:e], 0)
        if w is None:
            return cut  # a capped word whose prefix leaves a group open leans to a match
        if cut:
            w = w[0] + [('any', None)], True
        if w[1]:
            if _glob_can_match(w[0]):
                return True
        elif not ''.join(p[1] for p in w[0] if p[0] == 'lit').startswith('-'):
            return False
        i = max(e, i + 1)
    return False


def glob_subcommand(text):
    """The glob-subcommand rule (card 04df07c5, see above); a literal search for the name first (as NeedRule).
    Viktor r1: an option word of the match that globs (`-[i]`, a file named -i in the cwd: the subcommands are read
    from stdin) blocks too."""
    if 'security' not in text.lower():
        return None
    for m in _GLOB_SUB_RX.finditer(text):
        t = re.search(r'(?:\s+-\S+)+\s*$', m.group(0))
        for o in (t.group(0).split() if t else ()):
            ow = _glob_word(o, 0)
            if ow is None or ow[1]:
                return m
        if _glob_walk(text, m.end()):
            return m
    return None


RULES += [('glob-subcommand', FnRule(glob_subcommand, raw=True))]

# Card 03a336e5 (Viktor 47750/47751 LOW, defense-in-depth; the class the docstring names): a command NAME the shell
# makes at run time (`$(echo security) dump-keychain`, `` `echo security` ``, `s=security; $s ...`, `${S:-security}`,
# `sec$(echo urity)`, `$(printf '\163...')`) passed, 16 forms measured on the live gate. secret-read needs the literal
# name, and what the substitution prints is unknown here, so the rule is Viktor's: a simple command whose FIRST word is
# not literal (a $ or a backtick in it) and that has a secret subcommand standing as a word of its own blocks.
# Only find-generic-password, find-internet-password and dump-keychain: `export` is an everyday word after a
# variable command (`$PY x.py export`), and a name made at run time with -i / -p stays unseen (docstring).
# The name: plain chars, quoted runs, and $( ) (one level of parens inside), backticks, ${ }, $ pieces, at least one
# of the last; each piece starts with its own char, so it reads one way only. A blank must follow it (a quote right
# after it is the end of a quoted string, not a command: `echo "$(date)" dump-keychain` passes). The rest of the
# command up to ; & | or a newline is searched for the word; texts without one of the three words skip the regex.
# Linear (measured 2026-11-19): the first form, one regex POSITION + name + a lazy scan to the word, took 2.3 s on a
# 20 KB line of `$($a ` heads and as long on glued backtick or quoted pieces, every start reading the same long name
# again; at 80 KB it blocked on the 6 s watchdog. Now only the lines that hold the word are read (a name, its blank and
# the scan never cross a newline); _hn_names() reads each name once, right to left; a name hits when the first word
# after its blank comes before the next ; & |; and the regex only asks whether a command position reaches such a name,
# at a NUL mark put in front of it (every way of reading the wrapper words, as the first form's backtracking did).
_HN_SECRET = r'(?<![^\s\'"])(?:find-generic-password|find-internet-password|dump-keychain)(?=[\s;&|)\'"`]|$)'
_HN_SECRET_RX = re.compile(_HN_SECRET, re.I)
_HN_MARK_RX = re.compile(POSITION + '\x00', re.I)
_HN_NOT_PLAIN = frozenset(';&|(){}<>')


def _hn_names(line):
    """{start: index after its blank} for every name in line (no newline in it) with a $ or backtick piece that a blank
    follows. Pieces as the first form's regex read them: a plain char (not blank, ; & | ( ) { } < > or a quote, $,
    backtick), "..." with backslash pairs, '...', $( ) with one level of parens inside, `...`, ${ }, else a bare $.
    Each piece starts with its own char and ends one way, so the name from an index is its pieces up to the first char
    that starts none; filled right to left, every index once."""
    n = len(line)
    nbt, nsq, nbr, npa = [n] * (n + 2), [n] * (n + 2), [n] * (n + 2), [n] * (n + 2)
    dq, pe = [-1] * (n + 3), [-1] * (n + 3)  # inside "..." / $( ): the index after the closing quote / paren, or -1
    cend, cdyn = list(range(n + 2)), [False] * (n + 2)
    out = {}
    for i in range(n - 1, -1, -1):
        c = line[i]
        nbt[i] = i if c == '`' else nbt[i + 1]
        nsq[i] = i if c == "'" else nsq[i + 1]
        nbr[i] = i if c == '}' else nbr[i + 1]
        npa[i] = i if c in '()' else npa[i + 1]
        dq[i] = i + 1 if c == '"' else (dq[i + 2] if i + 1 < n else -1) if c == '\\' else dq[i + 1]
        if c == ')':
            pe[i] = i + 1
        elif c == '(':
            k = npa[i + 1]
            pe[i] = pe[k + 1] if k < n and line[k] == ')' else -1
        else:
            pe[i] = pe[i + 1]
        j, dyn = None, False
        if c == '$':
            dyn = True
            if line[i + 1:i + 2] == '(' and pe[i + 2] != -1:
                j = pe[i + 2]
            elif line[i + 1:i + 2] == '{' and nbr[i + 2] < n:
                j = nbr[i + 2] + 1
            else:
                j = i + 1
        elif c == '`':
            dyn = True
            j = nbt[i + 1] + 1 if nbt[i + 1] < n else None
        elif c == '"':
            j = dq[i + 1] if dq[i + 1] != -1 else None
        elif c == "'":
            j = nsq[i + 1] + 1 if nsq[i + 1] < n else None
        elif not (c.isspace() or c in _HN_NOT_PLAIN):
            j = i + 1
        if j is not None:
            cend[i], cdyn[i] = cend[j], dyn or cdyn[j]
            if cdyn[i] and cend[i] < n and line[cend[i]] in ' \t':
                out[i] = cend[i] + 1
    return out


def hidden_name(text):
    if '$' not in text and '`' not in text:
        return False
    import bisect
    words = [m.start() for m in _HN_SECRET_RX.finditer(text)]
    done = -1
    for w in words:
        if w < done:
            continue  # this line was read already
        ls = text.rfind('\n', 0, w) + 1
        done = text.find('\n', w)
        done = len(text) if done < 0 else done
        line = text[ls:done]
        names = _hn_names(line)
        if not names:
            continue
        lw = [x - ls for x in words[bisect.bisect_left(words, ls):bisect.bisect_left(words, done)]]
        seps = [i for i, c in enumerate(line) if c in ';&|']
        hits = []
        for q, e in names.items():
            k = bisect.bisect_left(lw, e)
            j = bisect.bisect_left(seps, e)
            if k < len(lw) and (j == len(seps) or lw[k] < seps[j]):
                hits.append(q)
        if hits:
            # a later line gets its newline back in front (a command position, and the \s of `\s-exec`); the first
            # line starts at ^ (no newline: `-exec $S dump-keychain` as the whole text is no find -exec)
            # (a NUL of the command itself is read as another plain char, not as a mark)
            plain = line.replace('\x00', '\x01')
            parts, prev = ['\n' if ls else ''], 0
            for q in sorted(hits):
                parts += [plain[prev:q], '\x00']
                prev = q
            if _HN_MARK_RX.search(''.join(parts) + plain[prev:]):
                return True
    return False


# The command text only, as GIT_RULES (_hits with script=False). A file the command names is judged by it only when a
# shell may run it (_hn_shell_file, in script_hits): the fleet replay (2026-11-19) blocked a kanban dump read by a
# python heredoc (kb.json, this card's own description quotes `$(printf %s S) find-generic-password`), a PR.md and a
# .diff that quote the forms; the made name is a shell form, a JSON, Markdown or Python file runs no shell word.
CMD_RULES = [('hidden-name', FnRule(hidden_name))]
# a file with one of these extensions is not shell code unless a shell shebang opens it or the command runs it with a
# shell word (bash x.md); any other extension, or none, may be shell code (fail-closed)
_HN_NOT_SHELL_EXT = frozenset(
    '.json .jsonl .md .markdown .txt .diff .patch .csv .tsv .log .py .pyi .js .mjs .cjs .ts .tsx .jsx .html .htm '
    '.css .xml .yml .yaml .toml .ini .sql .rb .pl .php'.split())
_HN_SHEBANG_RX = re.compile(r'#![ \t]*\S*?(?:/env[ \t]+(?:-\S+[ \t]+)*)?(?:ba|z|k|da)?sh\b')
# card 3bcd4514 (Viktor 48033 LOW L1): a shell's options before the file's name, one that takes a word too: -o / +o /
# -O / +O (a cluster ending in it, `-eo pipefail`), --rcfile / --init-file. `bash -o errexit made.md` ran made.md,
# the word after -o cut the old `(?:-\S+[ \t]+)*` walk. Each option is also read alone, as main read it (`bash -o
# made.md` stays blocked: an over-read, bash does not run it). The walk is bounded: unbounded, `-o` read with its
# word ran each walk from every shell word to the text's end (`bash -o bash -o ...`, quadratic, measured 11-20 past
# 120 s at 300 KB). Past _HN_MAX_OPTS options the shell counts as a reader and the file as its script (fail-closed;
# the interpreter walk blocks such a call past MAX_ARGS words anyway).
_HN_MAX_OPTS = 16
_HN_ARG = r'[^\s;&|<>()\'"`-][^\s;&|<>()]*'
_HN_OPT = (r'[ \t]+(?:[-+][A-Za-z]*[oO][ \t]+' + _HN_ARG + r'|--(?:rcfile|init-file)[ \t]+' + _HN_ARG
           + r'|[-+][^\s;&|<>()]*)')
_HN_OPTS = r'(?:' + _HN_OPT + r'){0,%d}' % _HN_MAX_OPTS
_HN_OPTS_OVER = r'(?:[ \t]+[-+][^\s;&|<>()]*){%d}' % (_HN_MAX_OPTS + 1)
# A shell that reads code from its stdin or from a substitution in its words (card 3bcd4514): a shell word with no
# operand after its options (`bash`, `bash -x`, `bash < f`, `bash <(cat f)`; a newline ends the command too), or
# with -s / -c anywhere in a cluster (`sh -s`, `bash -cx "$(< f)"`), eval anywhere, source / . of a <( or of
# /dev/stdin. Over-read on purpose, as everywhere in this gate: the shell word may be prose (`echo bash < f`); a
# shell with a script operand reads its stdin as data (`bash agent-msg.sh dave x - < f`, the fleet's own message
# form) and is no reader.
_HN_READER = []  # compiled on first use: _SHELL_NAME and STDIN_SOURCE are defined further down


def _hn_reader_rx():
    if not _HN_READER:
        _HN_READER.append(re.compile(
            r'(?<![\w.-])' + _SHELL_NAME + r'(?![\w.-])[\'"]?(?:' + _HN_OPTS_OVER + r'|' + _HN_OPTS
            + r'(?:[ \t]*(?:$|[;&|)\n<>]|\d+[<>])|[ \t]+[-+][A-Za-z]*[sc]|[ \t]+#'
            r'|[ \t]+[\'"]?(?:/dev/stdin|/dev/fd/0|/proc/self/fd/0)(?![\w/.-])))'
            r'|(?<![\w.-])eval(?![\w.-])'
            r'|(?<![\w.-])(?:source|\.)[ \t]+<\(|(?<![\w.-])' + STDIN_SOURCE))
    return _HN_READER[0]


_HN_FEED_READERS = frozenset(('cat', 'head', 'tail'))
# words that may stand before the reader and leave what it prints unchanged (`command cat f`, `LC_ALL=C cat f`,
# `nice -n 5 head f`, `sudo -u x cat f`): _FEEDER_WRAPPERS plus sudo / doas
_HN_PRE_WORDS = frozenset(('builtin', 'command', 'exec', 'nohup', 'time', 'env', 'nice', 'sudo', 'doas'))
# a redirection operator with its fd (`2>`, `0<`, `<`, `>>`) is one token, so `2>/dev/null cat f` starts at cat; a
# digit glued to a word stays in the word (`a1<f`: the word is a1, the < is stdin's)
_HN_TOKEN_RX = re.compile(r'\d*<+|\d*>+|[^\s;&|()<>`]+|[;&|()`\n]+')


def _hn_fed(base, cmd):
    """True when the command hands the file named base to a reader's stdin or output: a < redirect of it (`< f`,
    `0<f`, `$(< f)`; not << / <<<, whose word is no file), or a word of a cat / head / tail command (`cat f | bash`,
    `$(cat f)`, `<(cat f)`). One forward pass over the tokens: each simple command's first word, a redirection's
    target skipped (`< x cat f`, `2>/dev/null cat f`: cat is the command)."""
    pre, feeder, skip, prev = True, False, False, None
    for m in _HN_TOKEN_RX.finditer(cmd):
        tok = m.group()
        if tok[0] in ';&|()`\n':
            pre, feeder, skip, prev = True, False, False, tok
            continue
        redir = prev is not None and prev[-1] in '<>'
        if tok[-1] in '<>':
            prev = tok
            continue
        word = strip_quotes(tok)
        if word == base or word.endswith('/' + base):
            if (redir and prev.lstrip('0123456789') == '<') or feeder:
                return True
        if pre and not redir:
            name = os.path.basename(word)
            if skip:
                skip = False
            elif name in _HN_FEED_READERS:
                pre, feeder = False, True
            elif word.startswith('-'):
                skip = word in _FEEDER_ARG_FLAGS
            elif not (name in _HN_PRE_WORDS or word.isdigit() or _FEEDER_ASSIGN_RX.match(word)):
                pre = False
        prev = tok
    return False


def _hn_shell_file(path, body, cmd, piped=()):
    """True when a shell may run this file's text as code: not a data or non-shell extension, a shell shebang, a
    shell word / source / . right before its name in the command (after options, -o's word too), or (card 3bcd4514)
    the command feeds the file to a reader of code: a < redirect / a cat-like word of it (_hn_fed), or a word of a
    pipeline into a shell (piped: stdin_pipelines' words), and a shell that reads its stdin or a substitution as code
    stands in the command (_hn_reader_rx). Not seen: a name the command computes, and other filters (`sed '' f |
    bash` outside a pipeline into a shell, `$(sed '' f)`)."""
    if os.path.splitext(path)[1].lower() not in _HN_NOT_SHELL_EXT or _HN_SHEBANG_RX.match(body):
        return True
    name = os.path.basename(path)
    base = re.escape(name)
    if re.search(r'(?:^|[\s;&|(`/])(?:(?:ba|z|k|da)?sh|source|\.)(?:' + _HN_OPTS_OVER + r'|' + _HN_OPTS
                 + r'[ \t]+[\'"]?[^\s;&|]*?' + base + r'(?![^\s;&|\'")]))', cmd) is not None:
        return True
    # piped: the lexer's words, unquoted already (`sed p 'f' | bash`, `'f'`, `\f`: measured 11-20)
    fed = any(os.path.basename(w) == name for w in piped) or _hn_fed(name, cmd)
    return fed and _hn_reader_rx().search(cmd) is not None


# card 39d885ef (Viktor 43793 MEDIUM 1): True while pipes_union() reads the text a second time, with every
# backslash-letter kept as written, so the escapes printf / echo -e print (\n: a new command line) are seen
_KEEP_ESC = [False]
# backslash-letters normalise() took off so far (never reset: a nested call only adds); pipes_union reads the text
# a second time only when a first reading took one off, else the kept reading is the same text
_ESC_TAKEN = [0]
_ESC_SKIP = [True]  # the tests turn it off to compare the skipped reading with the full one


def normalise(cmd, joined=False):
    if not joined:
        cmd = cmd.replace('\\\n', '')                # line continuation
    if not _KEEP_ESC[0]:
        cmd, n = re.subn(r'\\([A-Za-z])', r'\1', cmd)   # sec\urity -> security
        _ESC_TAKEN[0] += n
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
# card 0196e1ee (Viktor 43793 LOW/INFO 2): readers of the pipe PIPE_SHELL_RX does not see, measured with bash (the
# fed ./x.sh ran): a shell in a group or a compound after the | (`| { bash; }`, `| ( bash )`, `| if true; then bash;
# fi`, `| while read l; do bash $l; done`), a path to env (`| /usr/bin/env bash`), and code the pipe's lines become:
# `| eval "$(cat)"`, `| while read l; do $l; done`, `| { read c; $c; }`, `| { read c; eval $c; }`, a $var as the
# command. Any of them after a | makes the pipeline's text a shell's input (stdin_pipelines); a quoted shell name
# (`| b"as"h`) is read by its decoded word there.
_READER_HEAD = (r'(?:[({][ \t]*|(?:if|while|until)\b[^|]*?\b(?:then|do)\b[ \t]*'
                r'|(?:[\w./-]*/)?env\b[ \t]+(?:-\S+[ \t]+|\w+=\S*[ \t]+)*)*')
# a $var as the command: a whole word (a binary's `|$A)` bytes, read as a script file, are none)
_READER_CODE = (r'(?:eval(?=[ \t]|$)|\$\{?[A-Za-z_]\w*\}?(?=[ \t;&\n]|$)|' + _SHELL_NAME + r'(?!' + _ALONE + r'))')
PIPE_READER_RX = re.compile(r'(?<![>|])\|&?[ \t]*' + _READER_HEAD + r'(?:' + _READER_CODE
                            + r'|read\b[^|]*?[;\n][ \t]*' + _READER_CODE + r')')
_SHELL_WORD_RX = re.compile(r'(?:[\w./-]*/)?' + _SHELL_NAME)
PIPELINE_START = ';&\n()`'  # a | does not end the pipeline the shell reads


def stdin_payloads(text, pipes=True):
    """(value, verbatim) of each word a shell reads on stdin: every quoted word of a pipeline that ends in `| <shell>`
    (the quotes walked from the start of the text, so a quote of an earlier word is not taken for an opening one),
    and the word after a <<< whose command has a shell word in it. verbatim: the value stands as written right
    after the word's opening quote (a command position the outer passes judge) or is one plain word (no blank, so
    no rule can match it). Linear: each quote and each word once."""
    import bisect
    pipes = [m.start() for m in PIPE_SHELL_RX.finditer(text)] if pipes and '|' in text else []  # False: <<< only
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
_BLANK_RX, _BLANKS_RX = re.compile(r'\s'), re.compile(r'\s*')  # card 0196e1ee: str.split's blanks (str.isspace)
_BRACE_AFTER_RX = re.compile(r'[ \t]*\}')  # no newline: a newline is a stop of its own (a run of them stays linear)
_SEG_STOP = ';&|\n(){}<>'


def _group_openers(text, code=None):
    """For each ")" / "}" position, the position of the opener that matches it (one stack pass); an unmatched closer
    maps to -1, the text's start. code (card 39d885ef, Viktor 43793 LOW 1): the lexer's code positions; a bracket in
    a quote is skipped. It was not: `(echo ./x.sh; echo "(") | bash` paired the quoted "(" and read the pipeline from
    after it, a SHORTER read (the old docstring said it never was). Without the lexer (code None) brackets in quotes
    still pair."""
    stack, match = [], {}
    for i, ch in enumerate(text):
        if code is not None and not code[i]:
            continue
        if ch in '({':
            stack.append((ch, i))
        elif ch in _GROUP_CLOSE:
            while stack and stack[-1][0] != _GROUP_CLOSE[ch]:
                stack.pop()
            match[i] = stack.pop()[1] if stack else -1
    return match


_UNESC_RX = re.compile(r'\\(?:x([0-9A-Fa-f]{1,2})|([0-7]{1,3})|([nrfvtae])|u([0-9A-Fa-f]{1,4})|U([0-9A-Fa-f]{1,8}))')
# echo -e, %b, zsh's echo and print (card c7234bed, Viktor 47808 LOW L1): \0 then up to three octal digits is one
# char (`echo -e 'x\0012...'` prints a newline; printf's own format reads \001 then "2")
_UNESC_ZERO_RX = re.compile(r'\\(?:x([0-9A-Fa-f]{1,2})|0([0-7]{0,3})|([0-7]{1,3})|([nrfvtae])|u([0-9A-Fa-f]{1,4})'
                            r'|U([0-9A-Fa-f]{1,8}))')


def _unesc_char(x, o, c, u):
    if x or o is not None:
        return chr(int(x, 16) if x else int(o or '0', 8) & 0xff)
    if u:  # \uHHHH / \UHHHHHHHH: zsh's printf, echo and print, bash 4.2+ (Viktor 47808 LOW L1)
        n = int(u, 16)
        return chr(n) if n <= 0x10FFFF and not 0xD800 <= n <= 0xDFFF else ''
    return '\n' if c in 'nrfv' else ' '


def _printf_unescape(v, zero=False):
    """Card 39d885ef (Viktor 43793): what printf / echo -e print for the backslash escapes of a word (\\n, \\r, \\f,
    \\v a newline: a command position; \\t, \\a, \\e a blank; \\xHH, octal and \\u / \\U their char). zero: the echo
    -e / %b reading, where \\0NNN is one octal char (card c7234bed)."""
    if zero:
        def one(m):
            x, z, o, c, u4, u8 = m.groups()
            return _unesc_char(x, z if z is not None else o, c, u4 or u8)
        return _UNESC_ZERO_RX.sub(one, v)

    def one(m):
        x, o, c, u4, u8 = m.groups()
        return _unesc_char(x, o, c, u4 or u8)
    return _UNESC_RX.sub(one, v)


_PRINTF_CONV_RX = re.compile(r'%(%|[-+ #0]*\d*(?:\.\d*)?[sbqdiouxXeEfgGc])')
_PRINTF_MAX_OUT = 65536


def _printf_output(fmt, args):
    """Card 39d885ef: what printf prints: each conversion takes the next argument (%b unescapes it), the format is
    used again while arguments are left, and the format's own escapes are applied. `printf 'x\\ns3curity %s\\n'
    dump-keychain` prints the call on a line of its own; its words alone never stand next to each other. Bounded: at
    most one pass per argument plus one, and _PRINTF_MAX_OUT chars."""
    args, out = list(args), []
    for _ in range(len(args) + 1):
        def conv(m):
            if m.group(1) == '%':
                return '%'
            a = args.pop(0) if args else ''
            return _printf_unescape(a, zero=True) if m.group(1).endswith('b') else a
        out.append(_printf_unescape(_PRINTF_CONV_RX.sub(conv, fmt)))
        if not args or not _PRINTF_CONV_RX.search(fmt) or sum(map(len, out)) > _PRINTF_MAX_OUT:
            break
    return ''.join(out)[:_PRINTF_MAX_OUT]


_FEEDER_WRAPPERS = frozenset({'builtin', 'command', 'exec', 'nohup', 'time', 'env', 'nice'})
_FEEDER_ARG_FLAGS = frozenset({'-u', '-a', '-n', '-S', '-P', '-C'})  # env -u NAME, exec -a NAME, nice -n N ...
_FEEDER_ASSIGN_RX = re.compile(r'[A-Za-z_]\w*=')
_FEEDER_MAX_WORDS = 32


def _feeder_words(cw):
    """Card c7234bed (Viktor 47808 LOW L1): a feeder's words with the words before it skipped that leave what it
    prints unchanged (`builtin printf`, `command -p echo -e`, `env -i A=1 printf`, `nohup`, `time -p`, `nice -n 5`,
    VAR=value): its name's basename first, then its arguments. [] when no name stands within _FEEDER_MAX_WORDS words."""
    i, wrapped = 0, False
    while i < min(len(cw), _FEEDER_MAX_WORDS):
        w = cw[i]
        if w.rsplit('/', 1)[-1] in _FEEDER_WRAPPERS:
            wrapped = True
        elif wrapped and w.startswith('-'):
            i += w in _FEEDER_ARG_FLAGS
        elif not _FEEDER_ASSIGN_RX.match(w):
            return [w.rsplit('/', 1)[-1]] + cw[i + 1:]
        i += 1
    return []


_REDIR_OP_RX = re.compile(r'&?[<>]+[&|]?')
_REDIR_FD_RX = re.compile(r'\d+|\{\w+\}')
_DUP_TARGET_RX = re.compile(r'\d+-?|-')
_BRACE_FD_RX = re.compile(r'\{\w+\}(?=&?[<>])')


def _seg_cmds(seg, strip=False):
    """The commands of one pipeline segment, each a list of its words (stdin_pipelines). strip (card 39d885ef): a
    redirection is no word: its operator, the fd number glued before it (`2>`, `{fd}>`), and its target (`>x`,
    `2>&1`, `<<<w`); a process substitution `<(..)` / `>(..)` keeps the old reading."""
    cmds, cur, i, last_end = [], [], 0, -1
    while i < len(seg):
        ch = seg[i]
        if strip and ch == '{':
            fd = _BRACE_FD_RX.match(seg, i)  # `{fd}>f`: zsh and bash 4+ redirect (a { would end the command here)
            if fd:
                i = fd.end()
                continue
        if strip and (ch in '<>' or seg.startswith('&>', i)) and seg[i + 1:i + 2] != '(':
            if cur and last_end == i and _REDIR_FD_RX.fullmatch(cur[-1]):
                cur.pop()
            op = _REDIR_OP_RX.match(seg, i)
            i = op.end()
            if op.group().endswith('&'):
                d = _DUP_TARGET_RX.match(seg, i)
                if d:
                    i = d.end()
                    continue
            while i < len(seg) and seg[i] in ' \t':
                i += 1
            if i < len(seg) and seg[i] not in _SEG_STOP:
                i = max(shell_word(seg, i)[1], i + 1)
            continue
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
        i = last_end = e
    if cur:
        cmds.append(cur)
    return cmds


def pipes_union(make_src, lexed=True, since=None):
    """Card 39d885ef (Viktor 43793): stdin_pipelines() of make_src() as read so far, united with the reading that keeps
    a backslash-letter (normalise() turns the quoted \\n of printf '...\\n...' | bash into n before any rule sees it).
    The union, not the second read alone: `\\bash`, `ba\\sh` need the first. lexed: see stdin_pipelines.
    since: _ESC_TAKEN when the caller began the text make_src() may hand back unchanged (default: now). When no
    normalise() since then took a backslash-letter off, the second text is the first one: not read again (the
    second lexer_view cost 1.25 s on a 100 000-word wrapper, past the 5 s timing cap)."""
    if since is None:
        since = _ESC_TAKEN[0]
    _XARGS_UNREAD[0] = False  # card 3bf9a741: set by either reading below, read by the caller right after
    _FEED_UNREAD[0] = False  # card 0196e1ee: the same
    _FEED_LIVE_WORDS[0] = set()  # card 0196e1ee: the words of a pipeline fed by a | of the command itself
    l1, w1 = stdin_pipelines(make_src(), lexed)
    if _ESC_SKIP[0] and _ESC_TAKEN[0] == since:
        return list(dict.fromkeys(l1)), list(dict.fromkeys(w1))
    _KEEP_ESC[0] = True
    try:
        l2, w2 = stdin_pipelines(make_src(), lexed)
    finally:
        _KEEP_ESC[0] = False
    return list(dict.fromkeys(l1 + l2)), list(dict.fromkeys(w1 + w2))


# card c7234bed (Viktor 47570 MEDIUM, 48033 M1): shell code a command or process substitution prints, where a shell
# runs it. `eval "$(echo python3 m.py)"`, `bash -c "$(printf ...)"`, `sh <<<"$(echo ...)"`, `. <(echo ...)`, `bash <(printf
# ...)`, `x=$(echo ...); eval "$x"` and `. /dev/stdin <<<'python3 m.py'` passed on main and on 39d885ef, while bash
# or zsh ran m.py (measured, work/c7234bed/truth1). A SITE is a substitution in the command of a reader of shell code
# (the lexer's segment, its reader word at a code position anywhere before the opener: 48033 M1, `bash -o pipefail -c
# "$(..)"`, `eval -- "$(..)"`, `eval "true; $(..)"`, `sh < <(..)`): eval (not of a <( ), source / . (of a <( only), a
# shell word (not of a <( that is a here-string's word), a <<< whose command has a shell word or a /dev/stdin source.
# What a site prints: every echo, printf or print at a code position in its body, each to the end of its own command
# (`$(true; echo ..)`, `$(if ..; then echo ..; fi)`, `$( (echo ..) )`, a nested one), read as a pipeline into a shell
# reads it (the printf and echo -e decoding of 39d885ef). A $var a reader takes (`eval "$x"`, `bash -c "$x"`, `bash
# <<<"$x"`, `echo "$x" | bash`, `. <(echo "$x")`: 48033 INFO V1) reads every feeder substitution of the text (x was set
# from one). A heredoc body a shell reads is read the same way (its own eval / bash -c lines; in an unquoted one the
# outer shell runs every substitution first, so each is a site), and so are the lines a site prints (to GEN_MAX_DEPTH).
# The word of a here-string to `source` / `.` of /dev/stdin is read too. Each only at a code position (the lexer's
# class; a $( in "..." is one). Only adds lines. A substitution of another program (`eval "$(ssh-agent -s)"`, `eval
# "$(brew shellenv)"`) prints what that program prints: not read (H1, accepted). When the lexer does not read the
# text: a reader anywhere in the GEN_RAW_BEFORE chars before the opener, every feeder word of the body.
_GEN_READER_RX = re.compile(r'(?P<ev>(?<![\w./-])eval(?![\w./-]))|(?P<so>(?<![\w./-])(?:source|\.)(?=[ \t]))'
                            r'|(?P<sh>(?<!' + _ALONE + r')' + _SHELL_NAME + r'(?!' + _ALONE + r'))|(?P<hs><<<)')
GEN_FEEDER_RX = re.compile(r'(?<![\w./-])(?:[\w./-]*/)?(?:echo|printf|print)(?=[ \t\n;&|)`]|\Z)')
GEN_VAR_RX = re.compile(r'\$(?:\{?[A-Za-z_0-9]|\{?[@*])')
GEN_SOURCE_HERE_RX = re.compile(STDIN_SOURCE + r'[^\n;&|]*?<<<[ \t]*')
GEN_HERE_READER_RX = re.compile(r'(?<!' + _ALONE + r')' + _SHELL_NAME + r'(?!' + _ALONE + r')|' + STDIN_SOURCE)
GEN_PIPE_SHELL_RX = re.compile(r'[ \t]*\|&?[ \t]*(?:[\w./-]*/)?' + _SHELL_NAME + r'(?!' + _ALONE + r')')
GEN_HS_PS_RX = re.compile(r'<<<[ \t]*\Z')
GEN_OPEN_RX = re.compile(r'\$\((?!\()|<\(|`')
GEN_KINDS = ('$(', '`', '<(')
GEN_RAW_STOPS = ';&\n)`'
GEN_RAW_BEFORE = 160  # the lexer-less path: a reader within this many chars before (a text the lexer does not read
# is no command bash runs as is; a Python or JSON file: reading every opener after any reader cost 0.26 s on a 207 KB
# JSON file, 13x, and 6 fleet commands went past the script budget in the replay)
GEN_LEX_MAX = 65536  # past it (and on a script file's text) the lexer-less path: lexing a 1 MB text cost 1-4 s a reading
# (the replay: 6 fleet commands went past the script budget; the gate lexes no script file's text, card 39d885ef)
GEN_RAW_SCAN = 16384  # the lexer-less path reads a substitution's body to this many chars at most
GEN_FEEDER_START_RX = re.compile(r'[ \t\n]*(?:[\w./-]*/)?(?:echo|printf|print)(?=[ \t\n;&|)`]|\Z)')
GEN_RAW_PART = 2048  # the lexer-less path reads a feeder to this many chars at most (over a JSON file's quotes a
# raw body ran to the file's end: 114 readings of up to 200 KB, 3 489 lines)
MAX_GEN_SUBSTS = 64
GEN_MAX_DEPTH = 2


def _subst_end(text, i, limit=None):
    """The index right after the substitution whose opener (`$(`, `<(`, `>(` or a backtick) starts at i, or -1 when it
    does not close. Quotes inside are skipped ('...' whole, "..." with its backslash escapes), and a comment (a # that
    starts a word, to the line's end: 48033 M1 (7), `$(echo x # it's` + newline); a $( or ( inside opens a level.
    limit: read at most this many chars (-1 past it)."""
    n = len(text) if limit is None else min(len(text), i + limit)
    if text[i] == '`':
        j = i + 1
        while j < n:
            if text[j] == '\\':
                j += 2
                continue
            if text[j] == '`':
                return j + 1
            j += 1
        return -1
    depth, j = 1, i + 2
    while j < n:
        ch = text[j]
        if ch == '\\':
            j += 2
            continue
        if ch == '#' and (j == i + 2 or text[j - 1] in ' \t\n;&|('):
            k = text.find('\n', j, n)
            if k < 0:
                return -1
            j = k
            continue
        if ch == "'":
            k = text.find("'", j + 1, n)
            if k < 0:
                return -1
            j = k + 1
            continue
        if ch == '"':
            j += 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == '\\' else 1
            j += 1
            continue
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return -1


def _gen_segment(segs, p):
    """The lexer's innermost command segment that holds p (a ${ } or $(( )) is part of its command), or None. segs:
    (the segments sorted by start, their starts)."""
    ss, starts = segs
    i = bisect.bisect_right(starts, p) - 1
    while i >= 0:  # the holder with the greatest start is the innermost
        s = ss[i]
        if p < s['end'] and s['frame'] not in ('${', '$(('):
            return s
        i -= 1
    return None


def _gen_reads(text, cls, lo, o, kind):
    """True when a reader of shell code in text[lo:o] (at a code position, when cls is known) takes what the
    substitution of kind opening at o prints (a $var: kind '$(') as shell code."""
    for m in _GEN_READER_RX.finditer(text, lo, o):
        if cls is not None and cls[m.start()] != 'c':
            continue
        g = m.lastgroup
        if g == 'ev' and kind != '<(' or g == 'so' and kind == '<(':
            return True
        if g == 'sh' and not (kind == '<(' and GEN_HS_PS_RX.search(text, lo, o)):
            return True
        if g == 'hs' and kind != '<(':  # a here-string feeds a shell or a /dev/stdin source of its own command
            raw = max(text.rfind(c, 0, o) for c in ';&\n') + 1
            hi = min([k for k in (text.find(c, o) for c in ';&\n') if k >= 0] or [len(text)])
            if GEN_HERE_READER_RX.search(text, raw if cls is None else min(lo, raw), hi) is not None:
                return True
    return False


def generated_lines(text, depth=0, all_sites=False, lexed=True):
    """The command lines the echo / printf / print substitutions at a site of text print (see the block above), and the
    words of the here-strings `source` / `.` read from /dev/stdin. None past MAX_GEN_SUBSTS sites (the caller blocks
    unread). all_sites: every substitution is a site (an unquoted heredoc body a shell reads). lexed=False (a script
    file's text) or a text past GEN_LEX_MAX: the lexer-less path."""
    if not ('echo' in text or 'print' in text or '<<' in text):
        return []
    # a raw look first (no lexing: the gate lexes no script file's text for nothing, card 39d885ef): a reader word
    # and an opener with a feeder word after it (either first: `x=$(echo ..); eval "$x"`), a heredoc with a reader,
    # or a /dev/stdin here-string
    if not all_sites and _GEN_READER_RX.search(text) is None:
        return []
    op = GEN_OPEN_RX.search(text)
    if not ((op is not None and GEN_FEEDER_RX.search(text, op.end()) is not None)
            or '<<' in text and GEN_HERE_READER_RX.search(text) is not None):
        return []
    lx = lex_or_none(text) if lexed and len(text) <= GEN_LEX_MAX else None
    cls = lx['cls'] if lx is not None else None
    feed = [f.start() for f in GEN_FEEDER_RX.finditer(text) if cls is None or cls[f.start()] == 'c']
    here = list(GEN_SOURCE_HERE_RX.finditer(text)) if '<<<' in text else []
    docs = [h for h in lx['heredocs']] if lx is not None else []
    if not feed and not here and not docs:
        return []
    # (opener, its kind, body start, body end) of each substitution with a feeder word in its body
    subs = []
    if lx is not None:
        for x in lx['substs']:
            if x['kind'] in GEN_KINDS:
                a, b = x['inner']
                k = bisect.bisect_left(feed, a)
                if k < len(feed) and feed[k] < b:
                    subs.append((x['start'], x['kind'], a, b))
    else:  # only an opener with a reader in its window, or one a feeder starts (the var rule): the body's end costs
        for m in GEN_OPEN_RX.finditer(text):
            o = m.start()
            kind = '<(' if text[o] == '<' else '`' if text[o] == '`' else '$('
            if not (all_sites or _gen_reads(text, None, max(0, o - GEN_RAW_BEFORE), o, kind)
                    or GEN_FEEDER_START_RX.match(text, m.end())):
                continue
            e = _subst_end(text, o, GEN_RAW_SCAN)
            if e < 0:
                continue
            a, b = m.end(), e - 1
            k = bisect.bisect_left(feed, a)
            if k < len(feed) and feed[k] < b:
                subs.append((o, kind, a, b))
    ss = sorted(lx['segments'], key=lambda s: s['start']) if lx is not None else []
    segs = (ss, [s['start'] for s in ss])
    sites, rest = [], []
    for sub in subs:
        o, kind = sub[0], sub[1]
        s = _gen_segment(segs, o) if lx is not None else None
        ok = all_sites or _gen_reads(text, cls, s['start'] if s is not None else max(0, o - GEN_RAW_BEFORE), o, kind) \
            or s is not None and kind != '<(' and GEN_PIPE_SHELL_RX.match(text, s['end']) is not None
        (sites if ok else rest).append(sub)
    if rest and '$' in text:  # a $var a reader takes: any feeder may have set it
        for v in GEN_VAR_RX.finditer(text):
            p = v.start()
            if cls is not None and cls[p] not in 'cd':
                continue
            s = _gen_segment(segs, p) if lx is not None else None
            lo = s['start'] if s is not None else max(0, p - GEN_RAW_BEFORE)
            if (_gen_reads(text, cls, lo, p, '$(') or any(a <= p < b for _, _, a, b in sites)
                    or s is not None and GEN_PIPE_SHELL_RX.match(text, s['end'])):
                sites += rest
                break
    if len(sites) > MAX_GEN_SUBSTS:
        return None
    lines = []
    for _, _, a, b in sites:
        for f in feed[bisect.bisect_left(feed, a):bisect.bisect_left(feed, b)]:
            if lx is not None:
                s = _gen_segment(segs, f)
                parts = [text[f:min(s['end'], b) if s is not None else b]]
            else:  # to the body's end, GEN_RAW_PART at most, and to its first stop (the stop may be quoted). The whole
                # body first: its lines keep their order when the list is made unique (`eval "$(echo $(echo s3c''urity)
                # dump-k''eychain)"` in a shell file: the cut part first put a `$` line between the two words)
                bb = min(b, f + GEN_RAW_PART)
                stop = min([k for k in (text.find(c, f, bb) for c in GEN_RAW_STOPS) if k >= 0] or [bb])
                parts = list(dict.fromkeys((text[f:bb], text[f:stop])))
            for part in parts:
                lines += stdin_pipelines(part + ' | bash')[0]
    for m in here:
        if cls is not None and cls[m.start()] != 'c':
            continue
        w = shell_word(text, m.end())[0]
        lines += [ln for ln in w.split('\n') if ln.strip()]
    if depth < GEN_MAX_DEPTH:
        for h in docs:  # a heredoc body a shell (or a /dev/stdin source) of its command reads
            s = _gen_segment(segs, h['op'])
            lo = s['start'] if s is not None else 0
            if any(cls[m.start()] == 'c' for m in GEN_HERE_READER_RX.finditer(text, lo, h['op'])) \
                    or s is not None and GEN_PIPE_SHELL_RX.match(text, s['end']) is not None:
                sub = generated_lines(text[h['bodyStart']:h['bodyEnd']], depth + 1, all_sites=not h['quoted'], lexed=lexed and h['quoted'])
                if sub is None:
                    return None
                lines += sub
        lines = list(dict.fromkeys(lines))
        if lines:  # what a site prints may hold a site of its own
            more = generated_lines('\n'.join(lines), depth + 1, lexed=lexed)
            if more is None:
                return None
            lines += more
    return list(dict.fromkeys(lines))


def gen_union(make_src, since=None, lexed=True):
    """Card c7234bed: generated_lines() of make_src(), united with the reading that keeps a backslash-letter (as
    pipes_union: printf's \\n). None when either is None."""
    if since is None:
        since = _ESC_TAKEN[0]
    g1 = generated_lines(make_src(), lexed=lexed)
    if g1 is None or (_ESC_SKIP[0] and _ESC_TAKEN[0] == since):
        return g1
    _KEEP_ESC[0] = True
    try:
        g2 = generated_lines(make_src(), lexed=lexed)
    finally:
        _KEEP_ESC[0] = False
    return None if g2 is None else list(dict.fromkeys(g1 + g2))


def stdin_pipelines(text, lexed=True):
    """(lines, words) of every pipeline that feeds a shell on stdin (see the block above).
    lexed=False (a script file's text, _hits(script=True)): every stop counts, as on main; the gate does not lex a
    script file's text (see _hits). Lexed, the fleet replay's node files (82 KB, 30 lexer retries for their `((`) cost
    about 1 s per reading, four readings per file: 133 -> 1 345 ms, 894 -> 3 945 ms on one command, and benign
    commands blocked on the script budget. The lexer only takes stops away, so a reading without it is main's."""
    import bisect
    pipes = [m.start() for m in PIPE_SHELL_RX.finditer(text)] if '|' in text else []
    readers = _pipe_readers(text) if '|' in text else []  # card 0196e1ee
    xmatches = list(XARGS_RX.finditer(text)) if 'xargs' in text else []  # card 3bf9a741
    if not pipes and not readers and not xmatches:
        return [], []
    lx = lex_or_none(text) if lexed else None
    code = [c == 'c' for c in lx['cls']] if lx is not None else None
    # a heredoc body is the text of whatever reads it, not the outer command's: by the outer lexing every stop in it
    # was gone, and a pipeline in a Python string of a `python3 - <<'PY'` body started at the body's top, its words
    # taking in the lines above (the fleet replay: the gate file named two lines up blocked as script-file). The
    # body's stops are those of the body lexed on its own (every stop, as on main, when it does not lex): a lexing
    # only takes stops away, so this reads no shorter than main.
    outer = list(code) if code is not None else None  # card 0196e1ee: the command's own code, before the bodies
    dstarts, dends = [], []  # card 0196e1ee: the bodies of the heredocs no shell reads (data), in order
    if code is not None:
        for h in lx['heredocs']:
            bs, be = h.get('bodyStart'), h.get('bodyEnd')
            if bs is None or be is None or be <= bs:
                continue
            sub = lex_or_none(text[bs:be])
            for k in range(bs, be):
                code[k] = sub is None or sub['cls'][k - bs] == 'c'
            if _shell_reads_heredoc(text, h):  # card 0196e1ee: its pipelines are the shell's own (`bash <<'EOF'`)
                outer[bs:be] = code[bs:be]
            else:
                if sub is not None and not h['quoted']:
                    # Viktor 49984: an unquoted delimiter's body is expanded, and the shell runs its $( ) and
                    # backticks then (`cat > n <<X` + `$(echo ./e*.sh | bash)`: bash ran evil.sh): those are live
                    for x in sub['substs']:
                        if x['kind'] in ('$(', '`'):
                            i0, i1 = bs + x['inner'][0], min(bs + x['inner'][1], be)
                            outer[i0:i1] = code[i0:i1]
                dstarts.append(bs)
                dends.append(be)
    # card 0196e1ee: a | in a quote is prose (lexed), one in a heredoc body is the body's own (lexed above); without
    # the lexer every one counts, as PIPE_SHELL_RX's do
    if readers:
        pipes = sorted(set(pipes) | {r for r in readers if code is None or code[r]})
    # card 39d885ef (Viktor 43793 LOW 1): a stop is a CODE position (not in a quote: `echo './x.sh;' | bash` printed
    # the ;), and not the & of a redirection (2>&1, &>, <&: `echo ./x.sh 2>&1 | bash` started the pipeline after it)
    # card 0196e1ee: and the newline that ends a heredoc's terminator line (class t): the pipeline after it started at
    # the body's last line, its first word the delimiter (`f() { echo ./x.sh; }; cat <<'E'` .. `E` + `f | bash` passed
    # the function rule; bash ran x.sh)
    stops = [i for i, ch in enumerate(text) if ch in PIPELINE_START
             and (code is None or code[i] or (ch == '\n' and lx['cls'][i] == 't'))
             and not (ch == '&' and ((i > 0 and text[i - 1] in '<>') or text[i + 1:i + 2] == '>'))]
    openers = None
    memo = {}  # a position -> the start it leads to: each position is walked once (a chain of groups stays linear)
    brace = {}  # a stop -> the "}" right after it (blanks between), or None
    firsts, names = {}, None  # card 0196e1ee: a start -> its first non-blank; (blanks, names, longest name)
    spans = {}
    xpipes = []  # card 3bf9a741: (the xargs match, the position of the | that feeds it, or None)
    for m in xmatches[:XARGS_SCAN_MAX + 1]:
        s = m.start()
        if text[s:s + 1] in _XARGS_SEP and code is not None and not code[s]:
            continue  # a separator in a quote: prose (`git commit -m "... | xargs python3"`); ^ matches no char
        pp = s if text[s:s + 1] == '|' else s - 1 if text[s:s + 1] == '&' and text[s - 1:s] == '|' else None
        if pp is not None and (text[pp - 1:pp] in ('>', '|') or text[pp + 1:pp + 2] == '|'):
            pp = None  # >| is a redirection, || no pipe: the xargs reads the shell's own stdin
        xpipes.append((m, pp))
    # an xargs no | stands right before still reads a pipe in a group, a loop, an if, a $( ) or a >( ) after one
    # (`echo m.py | (cd d && xargs python3)`, `| tee >(xargs python3)`): it is fed by every pipeline before it
    allp = ([i for i, ch in enumerate(text) if ch == '|' and (code is None or code[i]) and text[i - 1:i] not in ('>', '|')
             and text[i + 1:i + 2] != '|'] if any(pp is None for _, pp in xpipes) else [])
    start = {}
    for p in pipes + [pp for _, pp in xpipes if pp is not None] + allp:
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
                # card 0196e1ee (Viktor 43793 LOW/INFO 2): a loop, an if, a case or a function the text defines feeds
                # the pipe (`for f in ./x.sh; do echo $f; done | bash`, `if ..; then echo ./x.sh; fi | bash`, `case ..
                # esac | bash`, `f() { echo ./x.sh; }; f | bash`, bash ran x.sh): its body is not between the last stop
                # and the |, so the whole text before the | is read (over-read, never shorter)
                # (linear: the blanks and the defined names found once, each start's blank run skipped once, and
                # a word longer than every name never cut out: 20 000 pipes of `echo x | bash; ` ran the whole-text
                # search per pipe into the watchdog, 5 000 nested groups a word scan per group to the text's end)
                if names is None:
                    fn = _defined_functions(text) | {'done', 'fi', 'esac'}
                    names = ([m.start() for m in _BLANK_RX.finditer(text)], fn, max(map(len, fn)))
                if b not in firsts:
                    firsts[b] = _BLANKS_RX.match(text, b).end()
                st = firsts[b]
                k = bisect.bisect_left(names[0], st)
                end = min(names[0][k] if k < len(names[0]) else len(text), p)
                if 0 < end - st <= names[2] and text[st:end] in names[1]:
                    b = 0
                break
            if openers is None:
                openers = _group_openers(text, code)
            o = openers.get(closer, -1)
            if not 0 <= o < b:
                b = 0
                break
            b = o
        for x in path:
            memo[x] = b
        # card 0196e1ee (fleet replay 2): a pipeline in the body of a heredoc no shell reads starts in that body: a
        # walk to 0 there (a function name or an unmatched ")" of the body's Python, which does not lex) took in the
        # outer command's words (`cd`, read as a script word after a cd: 1 fleet command blocked). Its pipes are no
        # live ones (outer), so only those over-read words go
        k = bisect.bisect_right(dstarts, p) - 1
        start[p] = dstarts[k] if k >= 0 and p < dends[k] and b < dstarts[k] else b
    lspans = {}  # card 0196e1ee: a start -> its last | at a code position of the command itself (see below)
    for p in pipes:
        spans[start[p]] = max(spans.get(start[p], p), p)
        if outer is None or outer[p]:
            lspans[start[p]] = max(lspans.get(start[p], p), p)
    # card 0196e1ee (Viktor 43793 LOW/INFO 2): what a fed text makes by itself. Measured with bash, each ran the
    # fed script: `echo '\x60./x.sh\x60' | bash` and `echo '$(./x.sh)' | bash` (a quoted substitution: the shell that
    # reads the pipe runs it), `echo zzprobe ${F:-zzsub} | bash` (a parameter operator makes the word), `echo zzprobe
    # \x60echo zzsub\x60 | bash` (a backtick is a pipeline start: one right before the span closed a substitution the
    # feeder prints): unread. A $( at a code position is the feeder's own substitution: generated_lines reads what
    # an echo / printf in it prints, and its output another program makes (`echo "$(date)" | bash`) is H1, accepted
    # (Viktor 48205's controls); here its echo / printf output is also put in place (`echo zzprobe $(echo zzsub) |
    # bash`: the line `zzprobe zzsub`). Without the lexer every $( and backtick in the span counts as quoted
    # card 0196e1ee: the unread rule and the fed globs only for a | at a code position of the command itself. A | in
    # a quote or in a heredoc body (lexed on its own above, so its pipelines are read: over-read words, harmless) is
    # a pipe of whatever reads that text, mostly data (`python3 - <<'PY'` editing a file with `| bash` in it): the
    # fleet replay blocked 52 such commands. Without the lexer every | counts (fail-closed).
    merged = []  # overlapping spans (a pipe inside a group that is piped again) read once, as their union
    for b, p in sorted(spans.items()):
        live = b in lspans  # its words are live (over-read past the last live |: stricter, never fewer)
        if merged and b <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], p)
            merged[-1][2] = merged[-1][2] or live
        else:
            merged.append([b, p, live])
    # the operators and substitutions over the union of the live spans (the same chars; 5 000 nested groups scanned
    # per span ran quadratic, and no `$(` or `${` spans two spans: a span ends at a |)
    lmerged = []
    for b, p in sorted(lspans.items()):
        if b > 0 and text[b - 1] == '`':
            _FEED_UNREAD[0] = True
        if lmerged and b <= lmerged[-1][1]:
            lmerged[-1][1] = max(lmerged[-1][1], p)
        else:
            lmerged.append([b, p])
    for b, p in lmerged:
        if _FEED_PARAM_RX.search(text, b, p) or any(
                code is None or not code[m.start()] for m in _FEED_MADE_RX.finditer(text, b, p)):
            _FEED_UNREAD[0] = True
    lines, words = [], []
    for b, p, live in merged:
        seg = text[b:p]
        cmds = _seg_cmds(seg)
        # Viktor 49925 L2: the dedup through a set (a list scan per command was quadratic: a `done` feeder's span is
        # the text from its start, 28 000 commands of nested loops took 1 s)
        seen = {tuple(cw) for cw in cmds}

        def _new(cws):
            out = [cw for cw in cws if tuple(cw) not in seen]
            seen.update(tuple(cw) for cw in out)
            return out
        # card 39d885ef: the same words without the redirections: `echo s3curity 2>/dev/null dump-keychain` prints the
        # call whole (bash and zsh ran it, measured); zsh's MULTIOS sends a `>x` to the pipe too. Never fewer reads
        cmds += _new(_seg_cmds(seg, strip=True))
        # card 0196e1ee: an echo / printf substitution at a code position, its output put in place (see above)
        put = _FEED_ECHO_SUBST_RX.sub(lambda e: ' '.join(_feeder_words(_seg_cmds(e.group(1))[0])[1:])
                                      if _seg_cmds(e.group(1)) else '', seg)
        if put != seg:
            cmds += _new(_seg_cmds(put))
        for cw in cmds:
            # Viktor 49925 L1: a pipeline that is not live (a heredoc body no shell reads, a quote) is read as
            # written, as on main: a glob / brace word at the command position of one of its lines goes quoted, so
            # the direct-pattern rule (new in this card) does not glob it there (`cat > notes.md <<'X'` + `echo
            # ./e*.sh | bash`: the line `./e*.sh` matched evil.sh). The other words stay: an interpreter's glob word
            # (`echo python3 ./m*.py | bash` in a quote) is read as on main
            lw = cw if live else [_quote_pattern_word(v) for v in cw]
            lines.extend(lw)
            if len(cw) > 1:
                lines.append(' '.join(lw[1:2] + cw[2:]))
            for v in cw:
                words.extend(v.split())
                if live:  # Viktor 49984 L1b: a fed line's first word, the command the shell runs (`echo 'echo
                    # ./e*.sh' | bash` prints the glob; a word after a ; or an interpreter's: the line in `text`)
                    _FEED_LIVE_WORDS[0].update(ln.split(None, 1)[0] for ln in v.split('\n') if ln.strip())
            fw = _feeder_words(cw)  # card c7234bed (Viktor 47808 LOW L1): after builtin / command / env ..., and print
            if fw and fw[0] in ('printf', 'echo', 'print') and any('\\' in v for v in fw[1:]):  # 39d885ef
                for v in fw[1:]:
                    for u in dict.fromkeys((_printf_unescape(v), _printf_unescape(v, zero=True))):
                        if u != v:
                            for ln in u.split('\n'):
                                lines.append(_quote_line(ln, live))
                                words.extend(ln.split())
            # a bare `printf` (fw[1] missing) raised IndexError here, on main too (`cw[1]`): an 'error' block
            if fw and fw[0] == 'printf' and len(fw) > 1 and len(fw) > 1 + (fw[1] == '--'):
                f = 1 + (fw[1] == '--')  # card 39d885ef: the arguments put into the format (printf 'x\n%s y\n' z)
                for ln in _printf_output(fw[f], fw[f + 1:]).split('\n'):
                    lines.append(_quote_line(ln, live))
                    words.extend(ln.split())
    if len(xpipes) > XARGS_SCAN_MAX:
        _XARGS_UNREAD[0] = True
    size = 0
    counted = 0  # the xargs that run no plain data command (XARGS_DATA): the ones read
    read = {}  # (start, pipe) -> the words that pipeline feeds: each read once

    def fed_of(b, q):
        if (b, q) not in read:
            s1, e1 = _fed_words(text[b:q])
            s2, e2 = _here_fed(text, b, q, not lexed)
            read[(b, q)] = (s1 + s2, e1 + e2)
        return read[(b, q)]
    for m, pp in xpipes[:XARGS_SCAN_MAX]:
        argv, sq, ev = _xargs_cmd(text, m.end(), not lexed)
        k, repl, each, delim = _xargs_opts(argv)
        c0 = argv[k] if k < len(argv) else 'echo'  # no command: xargs runs echo
        if _XARGS_PLAIN_RX.fullmatch(c0) and c0.rsplit('/', 1)[-1] in XARGS_DATA:
            continue  # a plain data command: its words, fed or not, run nothing
        counted += 1
        if counted > (XARGS_MAX if lexed else XARGS_SCAN_MAX):  # a script file's xargs read line-bounded
            _XARGS_UNREAD[0] = True
            break
        if pp is not None:
            # a script file's text: from the line's start at most (the start walk crosses a Python call's parens
            # there and took in the file up to its top: a test file of another gate blocked, replay 2026-11-21)
            seqs, every = fed_of(start[pp] if lexed else max(start[pp], text.rfind('\n', 0, pp) + 1), pp)
        else:
            last = {}  # per pipeline start, its last pipe before this xargs (one reading of the longest span)
            # a script file's text (not lexed): only the pipelines on the xargs's own line. Every pipeline of the
            # file before it took in a log's or a review file's every word, past XARGS_MAX_WORDS: 2 such xargs in a
            # 377 KB jsonl blocked every command that names the file (fleet replay 2026-11-21, 229 rows)
            lo = -1 if lexed else text.rfind('\n', 0, m.start())
            for q in allp:
                if q >= m.start():
                    break
                if q > lo:
                    last[start[q]] = q
            seqs, every, seen = [], [], dict.fromkeys(ev)
            for b, q in last.items():
                sq2, ev2 = fed_of(b, q)
                seqs.extend(sq2)
                every.extend(ev2)
                seen.update(dict.fromkeys(ev2))
                if len(seen) > XARGS_MAX_WORDS + 1:  # the final words are a superset (+1: the empty word _flat drops)
                    break
            if len(seen) > XARGS_MAX_WORDS + 1:
                _XARGS_UNREAD[0] = True
                continue
        seqs = sq + seqs  # its own here-string / heredoc / < <( ) first: that is its stdin
        if delim:  # GNU -d: the words split there too
            seqs = seqs + [[p for w in s for p in w.split(delim)] for s in seqs]
            every = every + [p for w in every for p in w.split(delim)]
        seqs = [list(t) for t in dict.fromkeys(tuple(w for w in s if w) for s in seqs) if t]
        every = _flat(ev + every + [w for s in seqs for w in s])
        if len(every) > XARGS_MAX_WORDS:
            _XARGS_UNREAD[0] = True
            continue
        for ln in _xargs_lines(argv[k:], seqs, every, repl, each):
            size += len(ln)
            if size > XARGS_MAX_CHARS:
                _XARGS_UNREAD[0] = True
                break
            lines.append(ln)
    # each once: a word repeated in many pipelines is one lookup, not one per pipeline (MAX_TRIES)
    return list(dict.fromkeys(lines)), list(dict.fromkeys(words))


# card 3bf9a741 (the 74586987 side gap; measured 2026-11-20 on main 915e2f70, work/3bf9a741/main.txt): xargs adds the
# words it reads on stdin to the argv of the command it runs, and neither the script rules nor the secret rules saw
# them. `echo measure.py | xargs python3`, `| xargs -I{} node {}`, `printf measure.py | xargs -0 python3`, `xargs
# python3 <<'E'` ran the script unread (37 of 49 probe rows wrong, bash ran every one), and `echo dump-keychain |
# xargs security` made the keychain call unread. Now the command an xargs runs is read as a command line WITH the
# words it is fed, where a shell pipeline's lines go (stdin_pipelines' lines: the secret rules and the script rules
# read them):
#   all at once: the command and every fed word (xargs without -n / -L / -I);
#   one per word too, with -n, -L, -l, -I, -i, -J, --max-args, --max-lines, --replace (each word may come first);
#   with a replace string (-I R, -i, -J R, --replace): each input line put in place of R instead (BSD xargs puts the
#   entire line there, man xargs; Viktor 49280 MEDIUM 1: `echo security dump-keychain | xargs -I{} sh -c '{}'`), and
#   each word too, and every word in place of a whole-argument R (BSD -J); nothing is appended then, as xargs appends
#   nothing. The word after a shell's -c (sh, bash, zsh, dash, ksh) is always quoted in the line, so the gate reads it
#   as the shell's code (`echo ./x.sh | xargs -I{} sh -c '{}'` runs ./x.sh; Viktor 49280 LOW 2b).
# The fed words are no file candidates of their own: `echo measure.py | xargs grep -c x`, `| xargs python3 stat.py`
# read measure.py as data, as the line written out would be. Each word is shell-quoted unless plain ([\w./@%+=:,-]):
# xargs runs no shell, so a quote, a ; or a $( in a fed word is a character of the argument, and an unbalanced quote
# must not swallow the lines after it.
# The fed words: every word of the pipeline before the | (the commands' words, a group before it, a printf's output and
# an echo -e's decoding, as for a shell; a feeder's name and echo's own flags left out: `echo -m x | xargs python3`
# is `python3 -m x`), a here-string's word, a heredoc's body (to its terminator line, as bash reads it), and what a
# process substitution's commands write (`xargs python3 < <(echo m.py)`, `xargs -a <(echo m.py) python3`), each
# whole and split at blanks (and at a -d delimiter). Not seen, as everywhere in this gate: a file's content (`xargs
# python3 < list`, `cat list | xargs`: only the name `list` is a fed word), a computed name (`ls *.py | xargs
# python3`), a computed command (`xargs $(echo python3)`). Over-read on purpose: every xargs of the text, fed or not
# (a here-string), its pipeline read to its start, every word as a possible first. Past XARGS_MAX xargs commands,
# XARGS_MAX_WORDS fed words of one, or XARGS_MAX_CHARS of lines in all, the gate blocks (xargs-unread).
XARGS_RX = re.compile(r'(?:^|[;(){}\n`]|' + PIPE + r'|' + AMP + r'|\$\()[ \t]*' + CHAIN
                      + r'\\?[\'"]?(?:' + WORD + r'*/)?xargs[\'"]?(?=[ \t])')
XARGS_MAX = 64
# Only an xargs that runs no plain data command counts toward XARGS_MAX: an `xargs grep x` / `xargs wc -l` (a literal
# name of XARGS_DATA, whatever path) runs no program from its words and no keychain call, and is not read at all.
# Counting every xargs blocked running a script file that only lists many such lines (70 `xargs grep` strings in a
# Python list, no keychain word: main allowed it; measured 2026-11-21, work/3bf9a741/risk2.txt). Past XARGS_SCAN_MAX
# xargs of any kind the gate blocks unread, so the cheap look at each command stays bounded.
# A script file's text (stdin_pipelines lexed=False) is read line by line for xargs: the words of its command and of
# the pipeline that feeds it end at the line's end and start at its start (a heredoc's body still from the lines
# after), and an xargs no | stands right before is fed by its own line's pipelines only. So each one costs one line,
# and up to XARGS_SCAN_MAX of them are read there (XARGS_MAX_CHARS still bounds the lines in all). Not seen there: a
# pipeline or a group that crosses lines (`echo m.py | while read; do` + newline + `xargs python3`); main reads no
# xargs at all.
XARGS_SCAN_MAX = 4096
XARGS_DATA = frozenset({'echo', 'printf', 'grep', 'egrep', 'fgrep', 'true', 'false', ':', 'test', '[', 'cat', 'head',
                        'tail', 'wc', 'ls', 'basename', 'dirname'})
XARGS_MAX_WORDS = 512
XARGS_MAX_CHARS = 200_000
_XARGS_UNREAD = [False]  # set by stdin_pipelines, reset by pipes_union, read by its callers
_FEED_MADE_RX = re.compile(r'\$\(|`')
_FEED_PARAM_RX = re.compile(r'\$\{(?:[#!]|\w+(?:\[[^]]*\])?[^}\w])')
_FEED_ECHO_SUBST_RX = re.compile(r'\$\([ \t]*((?:echo|printf|print)(?:[ \t]+[^$`()|;&<>\n]*)?)\)')


def _pipe_readers(text):
    """Card 0196e1ee: the | positions PIPE_READER_RX finds, and a | whose next word, decoded as the shell does
    (quotes and backslashes taken off), is a shell (`| b"as"h`, `| 'ba''sh'`)."""
    out = [m.start() for m in PIPE_READER_RX.finditer(text)]
    for m in re.finditer(r'(?<![>|])\|&?[ \t]*(?=[\w./\\\'"-]*[\\\'"])', text):
        w = shell_word(text, m.end())[0]
        if _SHELL_WORD_RX.fullmatch(w):
            out.append(m.start())
    return out


# a `function` keyword consumes only itself and its blanks, so a name right after it is found again as a `name()`
_FUNC_DEF_RX = re.compile(r'(?<![\w.:-])(?:([\w.:-]+)[ \t]*\([ \t]*\)|function[ \t]+(?=([\w.:-]+)))')


def _defined_functions(text):
    """Card 0196e1ee: the names of the shell functions the text defines (`name()`, `function name`), one pass."""
    return {a or b for a, b in _FUNC_DEF_RX.findall(text)}
_FEED_UNREAD = [False]  # card 0196e1ee: the same for a pipeline into a shell whose fed text the gate does not read
_FEED_LIVE_WORDS = [set()]  # card 0196e1ee: the fed words of a | at a code position of the command (set as above)
_XARGS_SEP = frozenset(';(){}\n`|&$')  # the chars XARGS_RX's position may start with (^ starts with none)
_XARGS_PLAIN_RX = re.compile(r'[\w./@%+=:,-]+')
_XARGS_REDIR_RX = re.compile(r'\d*(?:&>>?|[<>]&|<<<|<<-?|<>|>>?\|?|<)')
_ECHO_FLAG_RX = re.compile(r'-[neE]+')


def _shq(v):
    return v if _XARGS_PLAIN_RX.fullmatch(v) else "'" + v.replace("'", "'\\''") + "'"


def _fed_words(seg):
    """Card 3bf9a741: (seqs, every) of what a pipeline segment (or a process substitution's body) writes to an xargs.
    seqs: the words in the order xargs reads them, one list per reading of the segment, with the redirections' words
    and without them (`cat <<'E' | xargs python3`: E is no word cat writes, and it must not stand first); each
    command's words without the feeder's name and echo's own flags, a printf's output, an echo -e / printf decoding,
    split at blanks. every: each of those words whole and split, and every other reading (the raw words, both
    decodings): the words that may come first under -n / -L / -I."""
    seqs, every = [], []
    for cmds in (_seg_cmds(seg), _seg_cmds(seg, strip=True)):
        seq = []
        for cw in cmds:
            fw = _feeder_words(cw)
            args = fw[1:] if fw else cw
            name = fw[0] if fw else None
            if name == 'echo':
                n = 0
                while n < len(args) and _ECHO_FLAG_RX.fullmatch(args[n]):
                    n += 1
                args = args[n:]
            outs = [args]
            if name in ('printf', 'echo', 'print') and any('\\' in v for v in args):
                outs = [[_printf_unescape(v) for v in args], [_printf_unescape(v, zero=True) for v in args], args]
            if name == 'printf' and len(fw) > 1 + (fw[1:2] == ['--']):
                f = 1 + (fw[1] == '--')
                outs.insert(0, [_printf_output(fw[f], fw[f + 1:])])
            seq += ' '.join(outs[0]).split()
            every += [w for o in outs for v in o for w in [v] + v.split()]
            # Viktor 49280 MEDIUM 1: BSD xargs -I / -J puts the ENTIRE input line in place of the replace string (man
            # xargs: "with the entire line of input"), so each output line of the feeder is a fed word whole as well
            every += [ln for o in outs for ln in ' '.join(o).split('\n')]
        seqs.append(seq)
    return seqs, every


def _flat(words):
    return [w for w in dict.fromkeys(words) if w]


def _paren_end(text, i):
    """The index of the ")" that closes the "(" at i (no quote is read: a longer body only reads more), or len(text)."""
    depth = 0
    for j in range(i, len(text)):
        if text[j] == '(':
            depth += 1
        elif text[j] == ')':
            depth -= 1
            if not depth:
                return j
    return len(text)


_HERE_OP_RX = re.compile(r'<<<|<<-?')


def _here_body(text, op, v, i, ended=False):
    """Card 3bf9a741: the words a here-string (op <<<, its word v) or a heredoc (<< / <<-, its delimiter v, the
    operator's command ending at or after i) feeds: the word; the body's lines, after this line up to the terminator
    line or the text's end, as bash reads it: (seq, every), see _fed_words. ended (a script file's text, read line
    by line): a body with no terminator line gives nothing (a Python string's `<<'E'\\n..` is no heredoc; read to the
    file's end it took in every word below, past XARGS_MAX_WORDS)."""
    if op == '<<<':
        body = [v]
    elif op in ('<<', '<<-'):
        nl = text.find('\n', i)
        body, closed = [], False
        for ln in (text[nl + 1:].split('\n') if nl >= 0 else []):
            if (ln.lstrip('\t') if op == '<<-' else ln) == v:
                closed = True
                break
            body.append(ln)
        if ended and not closed:
            return [], []
    else:
        return [], []
    return ' '.join(body).split(), [w for ln in body for w in [ln] + ln.split()]


def _here_fed(text, a, b, line=False):
    """Card 3bf9a741: (seqs, every) of the here-strings and heredocs in text[a:b] (`cat <<'E' | xargs python3`).
    line: a script file's text, see _xargs_cmd and _here_body."""
    seqs, every, i = [], [], a
    while True:
        m = _HERE_OP_RX.search(text, i, b)
        if not m:
            return seqs, every
        j = m.end()
        while j < len(text) and text[j] in ' \t':
            j += 1
        if j >= len(text) or text[j] in CMD_END:
            i = j
            continue
        v, e = shell_word(text[:b] if line else text, j)
        i = max(e, j + 1)
        seq, ev = _here_body(text, m.group(), v, i, line)
        seqs.append(seq)
        every += ev


def _xargs_cmd(full, i, line=False):
    """Card 3bf9a741: (argv, seqs, every) of the xargs command whose words start at i, up to the end of that command
    or ARGS_WINDOW chars: argv its options and the command it runs (no redirection); seqs and every (see _fed_words)
    what a here-string, a heredoc or a process substitution of it gives xargs. line: a script file's text (not
    lexed): its words end at the line's end (a Python string's quote there read on over the lines below, and their
    `<` / `<<` as its own input: a test file of another gate blocked, replay 2026-11-21); a heredoc's body is still
    read from the lines after it."""
    eol = full.find('\n', i) if line else -1
    text = full[:eol] if eol >= 0 else full
    argv, seqs, every = [], [], []
    end = min(len(text), i + ARGS_WINDOW)
    while i < end:
        ch = text[i]
        if ch in ' \t':
            i += 1
            continue
        if ch in CMD_END:
            break
        if text.startswith('<(', i) or text.startswith('>(', i):  # a word: /dev/fd/N (`-a <(echo m.py)`)
            j = _paren_end(text, i + 1)
            if ch == '<':
                sq, ev = _fed_words(text[i + 2:j])
                seqs += sq
                every += ev
            argv.append('/dev/fd/63')
            i = j + 1
            continue
        r = _XARGS_REDIR_RX.match(text, i)
        if r:
            op = r.group().lstrip('0123456789')
            j = r.end()
            while j < len(text) and text[j] in ' \t':
                j += 1
            if text.startswith('<(', j):  # `< <(echo m.py)`
                k = _paren_end(text, j + 1)
                sq, ev = _fed_words(text[j + 2:k])
                seqs += sq
                every += ev
                i = k + 1
                continue
            if j >= len(text) or text[j] in CMD_END:
                i = j
                continue
            v, e = shell_word(text, j)
            i = max(e, j + 1)
            sq, ev = _here_body(full, op, v, i, line)
            seqs.append(sq)
            every += ev
            continue
        v, e = shell_word(text, i)
        if e <= i:
            i += 1
            continue
        argv.append(v)
        i = e
    return argv, seqs, every


def _xargs_opts(argv):
    """Card 3bf9a741: (index of the command's first word, the replace string or None, one run per word, the -d
    delimiter or None) of an xargs argv (WRAP_ARGS' flags; BSD and GNU)."""
    short, whole = WRAP_ARGS['xargs'][0], WRAP_ARGS['xargs'][1]
    k, repl, each, delim = 0, None, False, None
    while k < len(argv):
        v = argv[k]
        if v == '--':
            return k + 1, repl, each, delim
        if v.startswith('--'):
            name, eq, val = v.partition('=')
            if name in whole and not eq:
                k += 1
                val = argv[k] if k < len(argv) else ''
            if name == '--replace':
                repl, each = (val if eq else '{}'), True
            elif name in ('--max-args', '--max-lines'):
                each = True
            elif name == '--delimiter':
                delim, each = val, True
            elif name == '--null':
                each = True
            k += 1
            continue
        if not v.startswith('-') or v == '-':
            break
        for j in range(1, len(v)):
            c = v[j]
            if c in short:
                arg = v[j + 1:]
                if not arg:
                    k += 1
                    arg = argv[k] if k < len(argv) else ''
                if c in 'IJ':
                    repl, each = arg, True
                elif c in 'nL':
                    each = True
                elif c == 'd':
                    delim, each = arg, True
                break
            if c == 'i':  # GNU -i[R]: --replace
                repl, each = v[j + 1:] or '{}', True
                break
            if c == 'l':  # GNU -l[N]: --max-lines
                each = True
                break
            if c == 'e':  # GNU -e[EOF]: its argument glued
                break
            if c == '0':  # NUL-separated: a word with a blank is one argument (every has it whole)
                each = True
        k += 1
    return k, repl, each, delim


def _xargs_lines(cmd, seqs, every, repl, each):
    """Card 3bf9a741: the command lines an xargs running cmd runs (see the block above): one per reading of what it
    is fed (seqs, all at once), and with each, one per word of every."""
    if not cmd:  # xargs's own default, echo
        return []
    if repl:
        out = [_xargs_join([x.replace(repl, w) for x in cmd]) for w in every] if each else []
        return out + [_xargs_join([q for x in cmd for q in (seq if x == repl else [x])]) for seq in seqs]
    out = [_xargs_join(cmd + seq) for seq in seqs] or [_xargs_join(cmd)]
    if each:
        out += [_xargs_join(cmd + [w]) for w in every]
    return out


def _xargs_join(argv):
    """Card 3bf9a741: an argv as a command line (_shq each word); after a shell's -c flag the word is quoted even when
    plain (Viktor 49280 LOW 2b): the gate reads a quoted -c argument as the shell's code, an unquoted one it does not."""
    at = _xargs_shell_at(argv)
    return ' '.join("'" + v.replace("'", "'\\''") + "'" if at is not None and i > at
                    and SHELL_CODE_FLAG_RX.fullmatch(argv[i - 1]) else _shq(v) for i, v in enumerate(argv))


_XARGS_SHELL_WRAPPERS = _FEEDER_WRAPPERS | {'sudo', 'doas', 'timeout', 'gtimeout'}
_XARGS_WRAP_VALUE_RX = re.compile(r'\d[\w.]*')


def _xargs_shell_at(argv):
    """Viktor r2 (card 3bf9a741): the index of the shell an xargs runs, past the wrappers that keep the shell in
    command position (`env sh -c`, `nice -n 5 bash -c`, `timeout 5 sh -c`, `sudo -n sh -c`, VAR=value); None when the
    first other word is not a shell."""
    wrapped = False
    for i, w in enumerate(argv[:_FEEDER_MAX_WORDS]):
        b = os.path.basename(w)
        if b in SHELL_NAMES:
            return i
        if b in _XARGS_SHELL_WRAPPERS:
            wrapped = True
        elif not (wrapped and (w.startswith('-') or _XARGS_WRAP_VALUE_RX.fullmatch(w)
                               or argv[i - 1] in _FEEDER_ARG_FLAGS) or _FEEDER_ASSIGN_RX.match(w)):
            return None
    return None


def payload_texts(text, script=False, subst=False):
    """The text of each payload a quote opens (payload_quotes(), PAYLOAD_OPEN): '...' as written, "..." with \\ \" \\$
    \\` and backslash-newline unescaped, as bash reads it. An escaped opening quote (`do shell script \\"...\\"`) is
    left to the payload around it. A quote inside an earlier payload belongs to it, so the walk is linear. Only a
    payload with a quote or a backslash in it is returned: one without stands verbatim after its opening quote (a
    command position) in the text the outer passes judge already, so reading it again adds nothing (and 30 000
    `-c 'a'` paddings stay fast). Each distinct text once; None past MAX_PAYLOADS.
    Card aeee72df: the whole shell word the quote opens is a payload too (shell_word(), LOW 2), when it is more than
    its first piece, and so is what a shell reads on stdin (stdin_payloads(), LOW 4). Both only add texts: the walk
    and the first-piece payloads are the ones before (a mark only ever adds a block).
    Card 2917e6b6 (subst=True, decoded_payloads): a verbatim payload with a backtick is returned too. Its text stands
    in the outer text as quoted text, where the call's words are cut at the backtick, which may open a substitution
    in them: `eval 'python3 \x60:\x60 evil.py'` read no script, and bash and zsh ran evil.py (main 01a9dded too).
    Read as a text of its own, the lexer reads it as code. Not in the outer passes: a backtick that closes a call there (prose
    in a heredoc: `python3 x`) cut it right, and searching on from it blocked 16 benign fleet commands (the replay)."""
    starts = set(payload_quotes(text))
    starts.update(m.end() - 1 for m in re.finditer(PAYLOAD_OPEN, text))
    out, seen, last, word_end = [], set(), -1, 0

    def add(p, verbatim):
        # card c7234bed (48033 M1 rework): a verbatim payload with a substitution and a feeder word in it is read as a
        # text of its own too: generated_lines() reads code positions only, and in the outer text it is quoted
        # (`bash -c 'eval $(echo ..)'` passed on main and on 79e1a907)
        if p in seen or (verbatim and not PAYLOAD_QUOTED.search(p) and not (subst and '`' in p)
                         and not (GEN_OPEN_RX.search(p) and GEN_FEEDER_RX.search(p))):
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
    """Rule names the text matches; a script file's text (script=True) is not judged by GIT_RULES or CMD_RULES."""
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
    lines = pipes_union(lambda: normalise(src), lexed=not script)[0]  # since: normalise(src) is made inside
    if _XARGS_UNREAD[0]:  # card 3bf9a741: an xargs past XARGS_MAX / XARGS_MAX_WORDS / XARGS_MAX_CHARS
        found += [h for h in ['xargs-unread'] if h not in found]
    if _FEED_UNREAD[0] and not script:  # card 0196e1ee: a fed text with a substitution or a backtick; not in a
        found += [h for h in ['stdin-feed-unread'] if h not in found]  # script file's body (KNOWN-FEED-FILE)
    if lines:
        found += [h for h in hits_in('\n'.join(lines), script) if h not in found]
    # card c7234bed: what an echo / printf substitution prints where a reader of shell code runs it (generated_lines)
    gen = gen_union(lambda: normalise(src), lexed=not script)  # a script file's text: not lexed (39d885ef)
    if gen is None:
        found += [h for h in ['payload-unread'] if h not in found]
    elif gen:
        found += [h for h in hits_in('\n'.join(gen), script) if h not in found]
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
        else:  # card 70a5fb2a (Viktor): the old path joins every one; the text with none joined is judged too
            alt = normalise(re.sub(r'\\+\n', '\n', cmd))
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
    raw = list(texts)  # card d58d5c30: the texts before the quote removal (an FnRule with raw=True reads only these)
    texts += [re.sub(r'[\'"\\]', '', t) for t in texts]
    found = []
    plain = [text, re.sub(r'[\'"\\]', '', text)]
    for name, rx in RULES + ([] if script else GIT_RULES + CMD_RULES):
        pick = raw if getattr(rx, 'raw', False) else plain if getattr(rx, 'plain', False) else texts
        if name not in found and any(rx.search(t) for t in pick):
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
# command runs an interpreter, or (card 3bcd4514) a reader of shell code stands in it (_hn_reader_rx, eval too):
# `eval "$(cat m.sh)"` and `eval "$(< m.sh)"` ran the file's keychain call on main. A < after a digit is read too (card 3bcd4514): `bash 0<m.sh` (fd 0) and `bash -s a1<m.sh` (a
# digit glued to a word is no fd: the word is a1, the < is stdin's) ran m.sh on main; `2<f` (another fd) is read on
# purpose (only a file more).
REDIRECT_RX = re.compile(r'(?<!<)<(?![<(&])[ \t]*' + PATH_TOKEN)
# card 3bcd4514: a path to the binary is the same binary (`eval "$(/bin/cat m.sh)"` ran its keychain call on main)
_CAT_ARGS = r'((?:[ \t]+[\'"]?' + WORD + r'+[\'"]?)+)'
CAT_RX = re.compile(SCRIPT_POSITION + r'(?:' + WORD + r'*/)?cat' + _CAT_ARGS)
# head and tail print the file too (`eval "$(head m.sh)"`, `head m.py | python3` ran it on main), but only where what
# they print can become code: in a substitution, or piped straight into an interpreter. Everywhere else (`head -1
# HANDOFF.md && bash x.sh`, `tail out.txt; python3 ...`) they read an output file: the replay of 11-20 had 105
# fleet commands blocked by such a file (mutation logs, HANDOFF.md, the error register) and none of them ran it.
HEADTAIL_RX = re.compile(r'(?:\$\(|<\(|`)[ \t]*' + CHAIN + r'(?:' + WORD + r'*/)?(?:head|tail)' + _CAT_ARGS
                         + r'|' + SCRIPT_POSITION + r'(?:' + WORD + r'*/)?(?:head|tail)' + _CAT_ARGS
                         + r'(?=[ \t]*\|(?!\|)[ \t]*\\?[\'"]?' + INTERP + r'[\'"]?(?=\s|$)'
                         # an interpreter given its code by -c / -e reads the pipe as data (`tail -1 reg.jsonl |
                         # python3 -c 'import json...'`, the fleet's error-register form: 5 of the replay's rows)
                         + r'(?![^\n;&|()]*?[ \t][\'"]?-(?-i:[A-Za-z]*[ce])(?=[\s\'"]|$)))', re.I)
# Shell variables set in the command (Viktor 41715 LOW f: `F=m.py; python3 $F`), and every cd in order, a relative one
# on top of the one before (LOW b: `cd sub && python3 only.py`).
ASSIGN_RX = re.compile(r'''(?<![\w$])([A-Za-z_]\w*)=(['"]?)([^\s'";|&<>()`$]+)\2(?=\s|$|;)''')
VAR_RX = re.compile(r'\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)')
ASSIGN_CHAIN_RX = re.compile(r'''(?<![\w$])([A-Za-z_]\w*)=(['"]?)((?:[^\s'";|&<>()`$]|\$\{[A-Za-z_]\w*\}|\$[A-Za-z_]\w*)+)\2'''
                             r'''(?=\s|$|;)''')
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
# card e3d2fd6e (Dave 11-16, main too): a backslash in the word (`./dump\.sh`, `\./dump.sh`, `{ ./dump\.sh; }`,
# `$(./dump\.sh)`): bash and zsh take it off and run dump.sh (measured 11-21, bin/shell-truth.py); normalise() takes
# off only a backslash before a letter. Such a word is read with word_forms' rules too, and so is one whose path
# start holds the backslash (`\./dump.sh`, `.\/dump.sh`, `\.\/dump.sh`, `\/abs`, `sub\/x.sh`)
_ESC_PATH_START = r'''(?=[.\\]*\\)(?:\\?\.){1,2}\\?/|\\/|[\w.-]+\\/'''
DIRECT_WORD_RX = re.compile(SCRIPT_POSITION + r'''((?:['"]?(?:\.{1,2}/|/|[\w.-]+/)[^\s'";|&<>()`$]*['"`$\\]|'''
                            + _ESC_PATH_START + r''')\S*)''')
# The words DIRECT_WORD_RX took before card e3d2fd6e (a quote, `$` or backtick after the path start). A word it takes
# only for a backslash is read at a code position alone (_esc_word_at_code): the fleet replay on main 99ee40e4 found
# 5 commands whose regex text (`/\.(?:py|sh)$/` in a JS file a `python3 - <<'PY'` writes, `\/` in a `sed '...'`
# script) a zsh-group reading then took for an unread script word
_DIRECT_WORD_PLAIN_RX = re.compile(SCRIPT_POSITION + r'''(['"]?(?:\.{1,2}/|/|[\w.-]+/)[^\s'";|&<>()`$]*['"`$]\S*)''')
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


def expand(text, keep=()):
    """$VAR / ${VAR} from assignments in the command itself, and $HOME; ~ is expanded per word later.
    keep: names left as written (for-loop variables: their values are read by loop_word_paths)."""
    env = {'HOME': os.path.expanduser('~')}
    for m in ASSIGN_RX.finditer(text):
        env[m.group(1)] = m.group(3)
    if '$' in text:
        # card deede5e4: a value made of variables set before it (`B=/x; O=$B/y; cd $O`), in order; a value with any
        # other $ (a substitution, an unknown name) stays unknown, and an unknown value read later is not "known"
        known = {'HOME': env['HOME']}
        for m in ASSIGN_CHAIN_RX.finditer(text):
            v = VAR_RX.sub(lambda v: known.get(v.group(1) or v.group(2), v.group(0)), m.group(3))
            if '$' in v:
                known.pop(m.group(1), None)
            else:
                known[m.group(1)] = v
                env.setdefault(m.group(1), v)
    return VAR_RX.sub(lambda m: m.group(0) if (m.group(1) or m.group(2)) in keep
                      else env.get(m.group(1) or m.group(2), m.group(0)), text)



ASSIGN_WORD_RX = re.compile(r'[A-Za-z_]\w*=.*', re.S)
# what may change a variable without naming it (a sourced file, eval of a made text) or split $X another way (IFS)
TRUST_OFF_RX = re.compile(r'(?<![\w./-])(?:source|eval|\.)(?=[ \t])|(?<!\w)IFS(?!\w)')


def expansion_trusted(text, keep=()):
    """Card 10624d73 (Viktor 43324 LELET 1, its price): expand() reads any NAME=value in the text as this shell's
    assignment, but the real $NAME may be empty (`echo X=notes.py`, a comment, `X=a cmd`, `unset X`, `false && X=a`)
    and then `python3 $X evil.py` runs evil.py; so an expanded text keeps the old walk (every word judged, no
    agent-msg reading). This says when the expansion is what the shell does: every name expand() replaced is set
    exactly once (HOME: not set, or set once), by a simple command of plain assignments only at the top level
    (lexer: depth 0, not a subshell, a substitution, a pipe, `&`, a heredoc, a comment or a quote; not after && or
    ||, not inside if / { / a function), before its first use, every use unquoted or in double quotes, and the name
    appears nowhere else in the text (unset, read, export -n, for NAME, ${NAME:-x}, NAME as a word ...); and no
    source, `.`, eval (they may set it without naming it) or IFS (it splits $NAME another way). Anything the lexer
    cannot read: not trusted. Then the measuring forms (`P=$SP/probe; python3 -I $P/x.py <hook file>`) read
    their argv as data again, as a literal path does."""
    uses = [m for m in VAR_RX.finditer(text) if (m.group(1) or m.group(2)) not in keep]
    if not uses:
        return True
    if TRUST_OFF_RX.search(text):
        return False
    lx = lex_or_none(text)
    if lx is None:
        return False
    cls = lx['cls']
    segs = lx['segments']
    n = len(text)
    for name in {m.group(1) or m.group(2) for m in uses}:
        mine = [m for m in uses if (m.group(1) or m.group(2)) == name]
        if any(cls[m.start()] not in 'cd' for m in mine):
            return False
        sites = [m.start() for m in re.finditer(r'(?<![\w$])' + name + '=', text)]
        if len(sites) > 1 or (not sites and name != 'HOME'):
            return False
        allowed = {m.start() + (2 if m.group(1) else 1) for m in mine} | set(sites)
        if any(m.start() not in allowed for m in re.finditer(r'(?<!\w)' + name + r'(?!\w)', text)):
            return False
        for p in sites:
            if cls[p] != 'c' or p > min(m.start() for m in mine):
                return False
            seg = max((g for g in segs if g['start'] <= p < g['end']), key=lambda g: g['depth'], default=None)
            if seg is None or seg['depth'] != 0 or seg['frame'] != 'top':
                return False
            if not all(ASSIGN_WORD_RX.fullmatch(w['text']) for w in shell_lex.words(text, lx, seg)):
                return False
            q = seg['start'] - 1
            while q >= 0 and text[q] in ' \t' and cls[q] == 'c':
                q -= 1
            if q >= 0 and cls[q] == 'c' and text[q] in '|&(':
                return False
            r = seg['end']
            while r < n and text[r] in ' \t' and cls[r] == 'c':
                r += 1
            if r < n and cls[r] == 'c' and (text[r] == '|' and text[r + 1:r + 2] != '|' or
                                             text[r] == '&' and text[r + 1:r + 2] != '&'):
                return False
    return _trust_shape(text, lx, uses)


# card 10624d73 r1 (Viktor): names the shell sets or refuses by itself (readonly, self-changing, set by a builtin
# without being named: read, getopts, mapfile, the last word of a command)
TRUST_NAMES_OFF = frozenset(('_', 'REPLY', 'OPTARG', 'OPTIND', 'MAPFILE', 'UID', 'EUID', 'PPID', 'RANDOM', 'SRANDOM',
                             'SECONDS', 'LINENO', 'BASHPID', 'EPOCHSECONDS', 'EPOCHREALTIME', 'BASHOPTS', 'SHELLOPTS',
                             'PWD', 'OLDPWD', 'HISTCMD', 'GROUPS', 'FUNCNAME', 'IFS', 'COLUMNS', 'LINES',
                             'DIRSTACK', 'PIPESTATUS', 'SHLVL', 'HOSTNAME', 'HOME', 'PATH', 'CDPATH'))
# r1 (Viktor): the raw text of an assignment-only command is plain unquoted ASCII name=value words, so the value the
# lexer reads is the value the shell stores (no quote, escape, glob, brace, CR/VT/NBSP, expansion)
_TRUST_ASSIGN_RAW = re.compile(r'[ \t]*[A-Za-z_]\w*=[A-Za-z0-9_./+,:@%=-]*(?:[ \t]+[A-Za-z_]\w*=[A-Za-z0-9_./+,:@%=-]*)*[ \t]*')


def _trust_shape(text, lx, uses):
    """Card 10624d73 r1 (Viktor): a positive shape, not a list of what may change a name. Every use sits in ONE
    top-level command, and every top-level command before it is made of plain assignments only (no command
    substitution, no backtick, no arithmetic), joined by ; or a newline only: then nothing ran between the assignment
    and the use that could unset, read into or declare a name without naming it (unset of a printf-made name, read
    into REPLY, getopts, a sourced file, if/then on lines, a function body, && at a line end). The character after a
    use is a word end or a slash (zsh reads $X[..] and $X:h as a subscript and a modifier)."""
    cls = lx['cls']
    segs = lx['segments']
    n = len(text)
    names = {m.group(1) or m.group(2) for m in uses}
    if names & TRUST_NAMES_OFF or any(x.startswith(('BASH', 'ZSH', 'COMP_')) for x in names):
        return False
    for m in uses:
        e = m.end()
        if e < n and text[e] not in ' \t\n/;"\'|&)':
            return False
    def top_seg(pos):
        return max((g for g in segs if g['start'] <= pos < g['end']), key=lambda g: g['depth'], default=None)
    use_segs = {id(top_seg(m.start())) for m in uses}
    ug = top_seg(uses[0].start())
    if len(use_segs) != 1 or ug is None or ug['depth'] != 0 or ug['frame'] != 'top':
        return False
    prev_end = 0
    for g in segs:
        if g['depth'] != 0 or g['start'] > ug['start']:
            continue
        gap = text[prev_end:g['start']]
        if any(ch not in ' \t\n;' for ch in gap) or any(cls[q] != 'c' for q in range(prev_end, g['start'])
                                                         if text[q] in ';\n'):
            return False
        prev_end = g['end']
        if g is ug:
            break
        if not _TRUST_ASSIGN_RAW.fullmatch(text, g['start'], g['end']):
            return False
    return True

def cd_bases(text, cwd, loops=None):
    """cwd, then the directory after each cd in order (a relative cd on top of the one before).
    loops (card deede5e4, script_paths only): the for-loop lists of the text (loop_lists). With it, a cd to a word
    with a loop variable over plain words is followed to each value, a cd word inside a heredoc body no shell reads
    (`python3 - <<'PY' ... re.compile('cd|export') ... PY`) is not a directory change, and `env -C` counts only in an
    env call's own options: the replay of the first draft blocked 675 fleet commands, most on these readings. The
    agent-msg check (loops None) keeps the reading Viktor 43304 A reviewed."""
    cur = cwd if isinstance(cwd, str) and os.path.isabs(cwd) else None
    bases = [cur] if cur else []
    if loops is not None:
        return _cd_bases_loops(text, cur, bases, loops)
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


# card e3d2fd6e r1 (Viktor 49996 R1): _esc_word_at_code asked for each backslash word, and building the blanked text
# per word was quadratic (a data heredoc with 3 000 `\./x.sh` lines ran into the 6 s watchdog, main 0.59 s); each text
# is read once, as lex_or_none does (the results are only read)
_HD_CACHE = {}
_HD_CACHE_MAX = 32


def _data_heredoc_view(text):
    """(blanked, bodies, starts) for text, or None when the lexer does not read it. blanked: text with the body of
    every heredoc no shell reads blanked (same length). bodies: (bodyStart, bodyEnd, shell-read, substitution) per
    heredoc in text order, starts their bodyStart (for bisect); substitution: an unquoted-delimiter body with a `$(`
    or a backtick (the shell runs it when it expands the body)."""
    if text in _HD_CACHE:
        return _HD_CACHE[text]
    lx = lex_or_none(text)
    view = None
    if lx is not None:
        out = list(text) if lx['heredocs'] else None
        bodies = []
        for hd in lx['heredocs']:
            ls = text.rfind('\n', 0, hd['op']) + 1
            le = text.find('\n', hd['opEnd'])
            read = bool(STDIN_SHELL_RX.search(text[ls:len(text) if le < 0 else le]))
            body = text[hd['bodyStart']:hd['bodyEnd']]
            bodies.append((hd['bodyStart'], hd['bodyEnd'], read,
                           not hd['quoted'] and ('$(' in body or '`' in body)))
            if not read:
                for i in range(hd['bodyStart'], hd['bodyEnd']):
                    if out[i] != '\n':
                        out[i] = ' '
        view = (''.join(out) if out is not None else text, bodies, [b[0] for b in bodies])
    if len(_HD_CACHE) >= _HD_CACHE_MAX:
        _HD_CACHE.clear()
    _HD_CACHE[text] = view
    return view


def _blank_data_heredocs(text):
    """text with the body of every heredoc no shell reads blanked (same length); text itself without the lexer's
    reading (then every cd word in a body still counts, as before)."""
    view = _data_heredoc_view(text)
    return text if view is None else view[0]


_ESC_MAX_COPIES = 64


def _esc_word_at_code(text, at, cmd=None, word=None):
    """card e3d2fd6e: a word DIRECT_WORD_RX takes only for a backslash, starting at text[at], is read unless the char
    before it is inside a quote ('...', $'...', the literal part of "...") or the word is in the body of a
    quoted-delimiter heredoc no shell reads (its own first char: the newline before a body's first line is the
    command line's). A shell's payload (`bash -c '..'`, `eval '..'`) is read as a text of its own, where it is code.
    A text the lexer does not fully read keeps the word (fail-closed), unless it is a text made from cmd (the lexer
    view: the r3 replay found a `sed '..\\/$(( ))\\/..'` read there) and every copy of the word in cmd, which the lexer
    reads, is data, and the text has it no more often (at most _ESC_MAX_COPIES copies are looked at)."""
    lx = lex_or_none(text)
    if lx is None:
        if cmd is None or text == cmd or not word:
            return True
        n = cmd.count(word)
        if not n or n > _ESC_MAX_COPIES or text.count(word) > n:
            return True  # (a cmd the lexer does not read either: its first copy below keeps the word)
        i = cmd.find(word)
        while i >= 0:
            if _esc_word_at_code(cmd, i):
                return True
            i = cmd.find(word, i + 1)
        return False
    cls = lx['cls']
    if cls[at] in ('h', 'u'):
        # r1 (Viktor 49996 R2): an unquoted-delimiter body no shell reads is data too (`cat > notes.md <<X` +
        # `./dump\.sh`: nothing runs it); only its `$( )` and backticks run, so a body with one keeps every word
        # (fail-closed: the lexer marks the whole body 'u', a word inside the substitution is not told apart)
        _, bodies, starts = _data_heredoc_view(text)
        k = bisect.bisect_right(starts, at) - 1
        if k < 0 or not bodies[k][0] <= at < bodies[k][1]:
            return True
        return bodies[k][2] or bodies[k][3]
    return not (at and cls[at - 1] in ('q', 'a', 'd'))


# a cd and its target word: plain characters and ${NAME}/$NAME, up to a blank or an operator; `cd $(..)`, a bare cd
# and `cd;` have none (not followed)
_CD_TARGET_RX = re.compile(r'(?<![\w./-])cd(?:[ \t]+(?:-[A-Za-z@]+|--))*[ \t]+((?:[^\s;&|<>()`$]|\$\{[A-Za-z_]\w*\}|\$[A-Za-z_]\w*)+)')
_ENV_OPT_ARG = ('-u', '-P', '-S', '--unset', '--split-string')
_ENV_CHDIR_WORD_RX = re.compile(r'-[A-Za-z]*C.*|--chdir(?:=.*)?')
_ENV_ASSIGN_WORD_RX = re.compile(r'[A-Za-z_]\w*=.*')


def _env_chdir(text):
    """An env call with -C / --chdir among its own options (before its command word)."""
    for m in ENV_WORD_RX.finditer(text):
        end = len(text)
        for ch in ';&|\n':
            k = text.find(ch, m.end())
            if 0 <= k < end:
                end = k
        skip = False
        for w in text[m.end():min(end, m.end() + ARGS_WINDOW)].split()[:MAX_ARGS]:
            w = strip_quotes(w)
            if skip:
                skip = False
            elif w in _ENV_OPT_ARG:
                skip = True
            elif _ENV_CHDIR_WORD_RX.fullmatch(w):
                return True
            elif not (w.startswith('-') or _ENV_ASSIGN_WORD_RX.fullmatch(w)):
                break
    return False


def _cd_bases_loops(text, cur, bases, loops):
    text = _blank_data_heredocs(text)
    unknown = bool(CHDIR_OTHER_RX.search(text)) or _env_chdir(text)
    q = re.sub(r'[\'"\\]', '', text)
    unknown = unknown or bool(CHDIR_OTHER_RX.search(q)) or len(CD_WORD_RX.findall(q)) != len(CD_WORD_RX.findall(text))
    curs = [cur] if cur else []
    # the word must end where the shell's word ends: `cd "$(echo sub)"` matched only its opening quote
    targets = {m.start(): m.group(1) for m in _CD_TARGET_RX.finditer(text)
               if m.end() == len(text) or text[m.end()] in ' \t\n;&|)'}
    for m in CD_WORD_RX.finditer(text):
        word = targets.get(m.start())
        # a bare cd, `cd;`, `cd $(..)`, `cd "$(..)"`, only option words (`cd -P`; Viktor deede5e4 r1 P1): not followed
        if word is None or not shell_unquote(word) or re.fullmatch(r'-[A-Za-z@]+|--', shell_unquote(word)):
            unknown = True
            continue
        try:
            vals = loop_word_paths(shell_unquote(word), loops)
        except PathUnread:
            unknown = True
            continue
        vals = [os.path.expanduser(v) for v in vals]
        if any('$' in v or v == '-' or _GLOB_CHARS_RX.search(v) or v.startswith('~') or '{' in v for v in vals):  # an outside variable, `cd -`, a glob
            unknown = True
            continue
        nxt = []
        for v in vals:
            for j in ([v] if os.path.isabs(v) else [os.path.join(c, v) for c in curs]):
                nxt.append(os.path.normpath(j))
                if '..' in v.split('/'):  # physical (set -P, cd -P): Viktor deede5e4 r1 R1
                    nxt.append(j)
        curs = list(dict.fromkeys(nxt))
        for c in curs:
            if c not in bases:
                bases.append(c)
        if len(bases) > MAX_BASES:
            break
    return Bases(bases, unknown=unknown)


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


class PathUnread(Exception):
    """A script word the gate cannot look up (card deede5e4, Viktor LOW L1): a relative path after a directory change
    cd_bases does not follow (pushd, `cd $(..)`, `cd $T` with T set outside the command, env -C), or a path with a
    for-loop variable whose list is not plain words or globs. The file was not read, so the caller blocks (an unread path was a way around:
    `for d in x; do cd $d; python3 m.py; done`, `pushd x; python3 m.py`)."""


# `for NAME in <words>`: the loop variables a script path may name (deede5e4: `for f in m.py; do python3 $f; done`
# ran m.py unread). A list of plain words is substituted (each value a candidate path, at most MAX_LOOP_PATHS);
# any other list (a glob, a substitution, a quote run, none: `for f; do`) leaves the variable unknown.
_LOOP_RX = re.compile(r'(?<![\w$-])for[ \t]+([A-Za-z_]\w*)(?:[ \t]+in[ \t]+([^;\n]*))?')
_LOOP_WORD_RX = re.compile(r'[A-Za-z0-9_./:+=,@%^~*?\[\]-]+')  # a glob is expanded where the value is looked up
_GLOB_CHARS_RX = re.compile(r'[*?\[]')
MAX_LOOP_PATHS = 64
MAX_LEAD_GLOB = 4096  # card 00c714ea: a script-position glob matching more blocks unread (a bounded directory walk)
MAX_STAR_DIRS = 2000  # card 00c714ea r3 (Viktor 49709 L2): a `**` walk over more directories blocks unread at once
# card 00c714ea r4 (Viktor 49785 L1): zsh's `***/` walks like `**/` and follows links (python3 ***/evil.py ran
# a/b/c/evil.py and one behind a link, measured 11-21); Python's glob reads `***` as one `*`: the whole component is
# read as `**` (Python's `**` follows links too, and star_walk_bounded bounds it the same way)
_STAR3_RX = re.compile(r'(?:^|(?<=/))\*\*\*(?=/)')


def star_walk_bounded(p):
    """Card 00c714ea r3 (Viktor 49709 L2): glob's `**` walks every directory under the pattern's literal head, and the
    MAX_LEAD_GLOB cap counts matches, not directories: `python3 **/stat.py` in a large cwd (/Users/klodel) walked
    until the 6 s watchdog blocked it (main 0.08 s). Before the walk the directories glob would enter are counted as
    it enters them (not hidden; a link to a directory too, as glob follows it), and past MAX_STAR_DIRS the word is
    unread: the watchdog's decision, without the wait. A pattern with no `**` component is not walked here."""
    parts = p.split('/')
    if '**' not in parts:
        return
    k = next(i for i, s in enumerate(parts) if _GLOB_CHARS_RX.search(s))
    todo, seen = ['/'.join(parts[:k]) or ('/' if p.startswith('/') else '.')], 0
    while todo:
        try:
            with os.scandir(todo.pop()) as it:
                for e in it:
                    try:
                        if e.name.startswith('.') or not e.is_dir():
                            continue
                    except OSError:
                        continue
                    seen += 1
                    if seen > MAX_STAR_DIRS:
                        raise PathUnread(f'a ** glob over more than {MAX_STAR_DIRS} directories: {p[-40:]}')
                    todo.append(e.path)
        except OSError:
            pass
_PWD_RX = re.compile(r'\$\{PWD\}|\$PWD(?!\w)')

# card 00c714ea (Viktor 49241 follow-up, old LOW, main too): a variable's value is trusted only in a positive shape.
# expand() reads NAME=value with a regex, the shell reads the word: `X=e*.py` / `X=[e]vil.py` (a glob at the use),
# `X='evil.py notes.py'` / `X=\ ` (split at the use), `X=notes.py\;z` (an escaped ;) and `export "HO"ME=evil.py` (a
# name split by quotes) ran another script than the one read. Such a name (an unquoted backslash in its assignment
# word; a blank, a glob or a brace in its value and an unquoted use; a quote or a backslash inside the name where the
# text assigns it) blocks unread (PathUnread) where it stands in a script position (ScriptGroup.lead) of the text
# read with it unexpanded; the expanded reading stays as it was. A value the gate does not read at all ($(..), a
# backtick, a ; in quotes) keeps the old reading (a variable set outside the command). And a script position's own
# brace expansion and glob are made as the shell makes them (brace_forms, resolve_lead_glob in script_paths).
_ASSIGN_SITE_RX = re.compile(r'(?<![\w$])([A-Za-z_]\w*)=')
_VALUE_PLAIN_RX = re.compile(r'''(['"]?)(?:[A-Za-z0-9_./+,:@%=~-]|\$\{[A-Za-z_]\w*\}|\$[A-Za-z_]\w*)*\1''')
_WORD_STOP = frozenset(' \t\n;|&<>()')


def _assign_word(text, i):
    """The assignment value's shell word that starts at i (to an unquoted blank or operator; a backslash escapes)."""
    j, q, n = i, None, len(text)
    while j < n:
        ch = text[j]
        if q:
            if ch == q:
                q = None
            elif ch == '\\' and q == '"':
                j += 1
        elif ch in '\'"':
            q = ch
        elif ch == '\\':
            j += 1
        elif ch in _WORD_STOP:
            break
        j += 1
    return text[i:j]


_VALUE_SPLIT_CHARS_RX = re.compile(r'[\s*?\[{]')


def _assign_value(w):
    """(an unquoted backslash in the word, the word's value with its quotes and escapes removed)."""
    out, q, esc, j = [], None, False, 0
    while j < len(w):
        ch = w[j]
        if q == "'":
            if ch == "'":
                q = None
            else:
                out.append(ch)
        elif q == '"':
            if ch == '"':
                q = None
            elif ch == '\\' and j + 1 < len(w) and w[j + 1] in '$`"\\\n':
                j += 1
                out.append(w[j])
            else:
                out.append(ch)
        elif ch in '\'"':
            q = ch
        elif ch == '\\':
            esc = True
            j += 1
            out.append(w[j] if j < len(w) else '')
        else:
            out.append(ch)
        j += 1
    return esc, ''.join(out)


def value_unread_names(text):
    """Card 00c714ea: the names whose value the shell may read otherwise than expand() (see the block above). A value
    that is plain but for a blank, a glob or a brace (quoted around, no escape) changes only at an unquoted use (split,
    globbed, brace-expanded): that name counts only when the lexer finds such a use (or cannot read the text)."""
    if '=' not in text:
        return frozenset()
    lx = lex_or_none(text)  # None: every site and every use counts (fail-closed)

    def code(p):
        return lx is None or lx['cls'][p] == 'c'
    bad, split = set(), set()
    for m in _ASSIGN_SITE_RX.finditer(text):
        if not code(m.start()):
            continue  # `echo "P=$P"`, a quoted heredoc body: no assignment of this shell
        w = _assign_word(text, m.end())
        if ('$(' in w or '`' in w or w.endswith('$') or _PARAM_OP_RX.search(w)
                or _VALUE_PLAIN_RX.fullmatch(w)):
            continue  # `X=$(..)`, `X=${Y:-..}`: a value not read, as one set outside the command
        esc, val = _assign_value(w)
        if esc:
            bad.add(m.group(1))  # an unquoted backslash: the shell drops it, expand() keeps it
        elif _VALUE_SPLIT_CHARS_RX.search(val):
            split.add(m.group(1))
        # else (a ; or a | in quotes ...): ASSIGN_RX does not read such a value at all, as one set outside
    split -= bad
    if lx is None:
        # the lexer cannot read this text (a payload-marked reading, prose): every site counted, a python heredoc's
        # `S=sys.argv[1]` made the shell's plain `S=/x` bad (1 fleet command, measured). Then a name with a plain
        # site too does not count: the expanded reading still globs and brace-expands the script position
        plain = {m.group(1) for m in _ASSIGN_SITE_RX.finditer(text)
                 if _VALUE_PLAIN_RX.fullmatch(_assign_word(text, m.end()))}
        bad -= plain
        split -= plain
    for m in VAR_RX.finditer(text) if split else ():
        name = m.group(1) or m.group(2)
        if name in split and code(m.start()):
            bad.add(name)
    for m in _SPLIT_NAME_RX.finditer(text):  # `export "HO"ME=x`, `H\OME=x`: a name split by a quote or a backslash
        name = re.sub(r'[\'"\\]', '', m.group(1))
        if re.fullmatch(r'[A-Za-z_]\w*', name) and (lx is None or lx['cls'][m.start(1)] in 'cqde'):
            bad.add(name)
    return frozenset(bad)


_PARAM_OP_RX = re.compile(r'\$\{[^}]*[^\w}]')
_SPLIT_NAME_RX = re.compile(r'''(?:^|(?<=[\s;&|(]))((?:[A-Za-z_]|['"\\])[\w'"\\]*['"\\][\w'"\\]*)=''')


class ScriptGroup(list):
    """Card 00c714ea: an interpreter call's candidate words, with lead: the words in its script position (the first
    word the call may run, and its forms). Only those are brace-expanded and globbed, and only those block on a name
    value_unread_names() returns: every word globbed blocked 210 fleet commands (script-too-many, a glob naming more
    than MAX_LOOP_PATHS files: `node x.mjs "src/*.ts"`), measured."""

    def __init__(self, words=(), lead=frozenset(), expand=False, zsh=True):
        super().__init__(words)
        self.lead = lead
        self.expand = expand  # the lead word as written has a glob or a brace outside quotes (unquoted_pattern)
        self.zsh = zsh  # card 0196e1ee: False for a word a pipe feeds a shell (decoded text, not the command's word)


def unquoted_pattern(raw):
    """Card 00c714ea: a glob char or a { outside quotes and not escaped in the word as written: only then does the shell
    glob or brace-expand it (a quoted `'./*/node_modules/*'`, `glob.glob('x/*')` in prose: no; measured, 4 fleet
    commands blocked on them)."""
    q, j = None, 0
    while j < len(raw):
        ch = raw[j]
        if q:
            if ch == q:
                q = None
            elif ch == '\\' and q == '"':
                j += 1
        elif ch in '\'"':
            q = ch
        elif ch == '\\':
            j += 1
        elif ch in '*?[{':
            return True
        elif ch == '(' and (j == 0 or raw[j - 1] not in '$<>='):
            return True  # Viktor r1: a zsh group `(m|x)easure.py` or qualifier `m*.py(.)` ran measure.py
        j += 1
    return False


_BRACE_ALT_RX = re.compile(r'(?<!\$)\{([^{}\s]*,[^{}\s]*|[A-Za-z]\.\.[A-Za-z]|-?\d+\.\.-?\d+)\}')


# Viktor r1 / card 00c714ea r2: a zsh group or qualifier paren in a script word. The call's words end at ) and |, so it
# arrives cut: `(measure`, `m*.py(.`, `m*(N`, `e(vil.py` (zsh -f with the fleet Bash tool's setopts ran evil.py for
# `e(vil.py|x)`, measured 11-21). Every paren: a `$(`, `<(` or `=(` one leaves its prefix's `$`, `<` or `=` in each
# pattern, which no file name matches (zsh_paren_may_match; a lookbehind for them survived mutation as equivalent)
_ZSH_GLOB_PAREN_RX = re.compile(r'\(')
_ZSH_WORD_END = set(' \t\n;&<>')
MAX_ZSH_GROUP_GLOBS = 64
MAX_ZSH_GROUP_DEPTH = 32


class _ZshUnread(Exception):
    """A zsh group the reader below does not follow (a substitution or a value in it, too many forms or too deep): the
    caller falls back to the prefix."""


def zsh_group_globs(text, i):
    """Card 00c714ea r2: the glob patterns of the shell word at text[i:] with its zsh groups made into their members
    (`(measure|zz).py` -> measure.py, zz.py; nested, quoted and escaped members as zsh -f read them, measured 11-21),
    and a last group of one member also dropped (a qualifier: `m*.py(.)` -> m*.py); a form may be empty (the caller
    puts the word's prefix before it). A blank, tab or newline in a group is a member char (`(evil.py|a b)` runs
    evil.py; Viktor 49709 L1, measured with zsh -f and extendedglob). [] when zsh runs nothing: ; & < > in a group (a
    parse error) or a group the text leaves open (`(measure.py|zz x`: bad pattern), measured 11-21. Raises _ZshUnread for a word with a
    substitution or a value ($(..), backticks, $X: `(zz|$(echo measure.py))` ran measure.py), a group nested past
    MAX_ZSH_GROUP_DEPTH or more than MAX_ZSH_GROUP_GLOBS forms."""
    import glob
    n, subst = len(text), [False]

    def seq(i, depth):
        if depth > MAX_ZSH_GROUP_DEPTH:
            raise _ZshUnread  # a deeper nest (RecursionError at 30 000) falls back to the prefix
        items = []
        while i < n:
            ch = text[i]
            if ch in _ZSH_WORD_END:
                if depth and ch in ' \t\n':  # Viktor 49709 L1: a blank in a group is a member char: zsh -f ran
                    items.append(ch)  # `(measure.py|a b)`, a tab, a newline, a nested group; `(measure.py |zz)`
                    i += 1  # looks for "measure.py " (measured 11-21, Dave zblank/drive.py, drive2.py)
                    continue
                if depth:
                    raise ValueError  # ; & < > in a group: a parse error, zsh runs nothing (measured 11-21)
                break
            if ch in '|)':
                break
            if ch == '`' or ch == '$':  # a substitution or a value: its span is skipped, the word is not read
                subst[0] = True
                if ch == '`' or text[i + 1:i + 2] == '(':
                    j = text.find('`', i + 1) if ch == '`' else _close_paren(text, i + 1)
                    if j < 0:
                        raise ValueError  # left open: zsh runs nothing
                    i = j + 1
                else:
                    i += 1
                continue
            if ch == '(':  # `<(..)` and `=(..)` in a group: zsh ran nothing, measured 11-21
                alts, i = [], i + 1
                while True:
                    s, i = seq(i, depth + 1)
                    alts.append(s)
                    if i >= n:
                        raise ValueError  # a group the text leaves open: bad pattern
                    i += 1
                    if text[i - 1] == ')':
                        break
                items.append(alts)
                continue
            if ch in '\'"':
                j = text.find(ch, i + 1)
                if j < 0:
                    raise ValueError
                if ch == '"' and ('$' in text[i + 1:j] or '`' in text[i + 1:j]):
                    subst[0] = True
                items.append(glob.escape(text[i + 1:j]))
                i = j + 1
                continue
            if ch == '\\':
                items.append(glob.escape(text[i + 1:i + 2]))
                i += 2
                continue
            items.append(ch)
            i += 1
        return items, i

    def forms(items):
        out = ['']
        for it in items:
            if isinstance(it, str):
                out = [o + it for o in out]
            else:
                out = [o + f for o in out for alt in it for f in forms(alt)]
            if len(out) > MAX_ZSH_GROUP_GLOBS:
                raise _ZshUnread
        return out

    try:
        items, _ = seq(i, 0)
    except ValueError:
        return []
    if subst[0]:
        raise _ZshUnread
    pats = forms(items)
    if items and isinstance(items[-1], list) and len(items[-1]) == 1:
        pats += forms(items[:-1])
    return pats


def _close_paren(text, i):
    """The index of the ) that closes the ( at text[i], counting nested parens (quotes not followed); -1: none."""
    depth = 0
    for j in range(i, len(text)):
        if text[j] == '(':
            depth += 1
        elif text[j] == ')':
            depth -= 1
            if not depth:
                return j
    return -1


def _locale_firsts(hits):
    """Viktor r1 (card 00c714ea): the first match in a locale's order. bash and zsh sort a glob by LC_COLLATE:
    `_a.py` comes before `-a.py` under en_NZ/en_US.UTF-8, where byte and case-folded order put -a.py first, and
    hu_HU.UTF-8 puts cz before cs (measured: Python's strxfrm gives zsh's order in each). The hook may not get the
    shell's LANG, so the environment's locale, en_US.UTF-8 and hu_HU.UTF-8 each; other locales are not modelled."""
    import locale
    old, out = locale.setlocale(locale.LC_COLLATE), []
    try:
        for loc in ('', 'en_US.UTF-8', 'hu_HU.UTF-8'):
            try:
                locale.setlocale(locale.LC_COLLATE, loc)
            except locale.Error:
                continue
            out.append(min(hits, key=lambda h: (locale.strxfrm(h), h)))
    finally:
        locale.setlocale(locale.LC_COLLATE, old)
    return out


def brace_forms(word):
    """Card 00c714ea: the words a shell's brace expansion makes of word (`{evil.py,$X}`, `{e..e}vil.py`), the word
    itself first; more than MAX_LOOP_PATHS raises PathUnread."""
    if '{' not in word:
        return [word]
    out, todo = [], [word]
    while todo:
        w = todo.pop()
        m = _BRACE_ALT_RX.search(w)
        if not m:
            out.append(w)
            continue
        body = m.group(1)
        if ',' in body:
            alts = body.split(',')
        else:
            a, b = body.split('..')
            if a.lstrip('-').isdigit():
                lo, hi = int(a), int(b)
                alts = [str(k) for k in range(min(lo, hi), max(lo, hi) + 1)[:MAX_LOOP_PATHS + 1]]
            else:
                alts = [chr(k) for k in range(min(ord(a), ord(b)), max(ord(a), ord(b)) + 1)]
        todo += [w[:m.start()] + x + w[m.end():] for x in alts]
        if len(out) + len(todo) > MAX_LOOP_PATHS:
            raise PathUnread(f'a brace expansion making more than {MAX_LOOP_PATHS} words: {word[:40]}')
    return list(dict.fromkeys([word] + out))


def loop_lists(text):
    """{name: [values] or None (not plain words)} for every for-loop variable in text; a name with two loops gets
    the values of both (each run of the text may be in either)."""
    out = {}
    for m in _LOOP_RX.finditer(text):
        name, words = m.group(1), (m.group(2) or '').split()
        words = [strip_quotes(w) for w in words]
        ok = bool(words) and all(_LOOP_WORD_RX.fullmatch(w) for w in words)
        if not ok or out.get(name, []) is None:
            out[name] = None
        else:
            out[name] = out.get(name, []) + words
    return out


def loop_word_paths(word, loops):
    """The paths a word with loop variables names: [word] when it names none; the substituted values when every
    variable it names is a loop over plain words; raises PathUnread when one is a loop over anything else or the
    values are more than MAX_LOOP_PATHS. Other $VARs (set outside the command) stay as written (see "Not seen")."""
    names = [m.group(1) or m.group(2) for m in VAR_RX.finditer(word)]
    loop_names = [n for n in dict.fromkeys(names) if n in loops]
    if not loop_names:
        return [word]
    outs = [word]
    for n in loop_names:
        vals = loops[n]
        if vals is None:
            raise PathUnread(f'a script path with ${n}, a loop over not plain words')
        rx = re.compile(r'\$\{' + n + r'\}|\$' + n + r'(?!\w)')
        outs = [rx.sub(lambda _m, v=v: v, o) for o in outs for v in dict.fromkeys(vals)]
        if len(outs) > MAX_LOOP_PATHS:
            raise PathUnread(f'a script path with loop variables naming more than {MAX_LOOP_PATHS} files')
    return outs


class SourceGroup:
    """`source f a b`: the rest (a, b) is judged only when f is an existing regular file; `over` names why the rest
    is not all read (past MAX_ARGS or ARGS_WINDOW), and then such a call blocks. Card 70c94516: `firsts` are the
    readings of f (as written, quotes removed, substitutions removed, the next word when f may print nothing); the
    rest is judged when any of them is a file."""
    def __init__(self, firsts, rest, over):
        self.firsts, self.rest, self.over = firsts, rest, over


# `>`, `2>>`, `>&`, `&>`, `>|` alone (target next) or with it; the & and | of a redirection no longer end the words
# (_CALL_END_RX, Viktor 42251 LOW 2), so `python3 2>&1 ./x.py` and `python3 >& out.txt x.py` read x.py.
# the target may hold a quoted or escaped blank since card 946937b7 (`>"x y"`, `>x\\ y`: one word from the lexer)
OUT_REDIR_RX = re.compile(r'(?:\d*>>?[&|]?|&>>?)([\s\S]+)?$')
# card 946937b7 (Viktor 45626 R3): before source's file an input redirection or a here-doc / here-string is no file
# either (`source </dev/null x.sh`, `source <<<x x.sh`, `source <&0 x.sh` run x.sh)
SRC_REDIR_RX = re.compile(r'(?:\d*(?:>>?[&|]?|<<<|<<-?|<>|<&|<)|&>>?)([\s\S]+)?$')
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


def _call_end(rest, base, openers, cls=None):
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
        if cls is not None and cls[base + k] != 'c':
            # card 946937b7: a ; & | ) or newline inside a quote or after a backslash is word text (`>"x&"`, `>x\\&`,
            # `-W "a;b"`): bash goes on with the call (lexer class c = code; the lexer read the whole text)
            pos = end.end()
            continue
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


_QUOTED_RX = re.compile(r'[\'"\\]')
_OPENS_RX = re.compile(r'[(`]')  # a substitution (or a subshell) may open here: interp_groups' fail-closed
_BLANK_RUN_RX = re.compile(r'\s+')
_ESC_SEP_RX = re.compile(r'\\[\s;&|)<>]')


# card 946937b7: script_hits sets it: the lexer read the command AS WRITTEN (the only caller of script_paths, so it is
# fresh for every interp_groups call of a decision); False (fail-closed) until then
_CMD_READ = [False]


def _call_alone_groups(name, seg, expanded):
    """interp_groups of one call's own text (its name and its words up to the cut), or None when the lexer does not
    read that text cleanly (card 946937b7, see interp_groups' fail-closed)."""
    if shell_lex is None:
        return None
    try:
        lx = shell_lex.lex(name + seg)
    except Exception:  # LexTooBig, or a lexer bug: no reading
        return None
    if lx['problems']:
        return None
    return interp_groups(name + seg, expanded)


# card af12091a: the characters _own_command_groups may lex in one decision (each candidate end lexes the call's
# text up to it). Past the budget the gate blocks (fail-closed): a text padded to use it up would otherwise hide the
# call that comes after (`bash -c '<1500 x python3 $(a;b ok.py;>'` lexed about 15 million characters, 6 s, the
# watchdog). A benign line of 1500 calls reads about 75 000. There is no limit per call: a call that ran out of tries
# would keep the old reading, and 33 quoted operators would reopen the gap (`eval 'python3 -W "a;...;b" evil.py'`).
# A call quoted in Python code (a heredoc that edits a test file) never reads cleanly: its search runs to the window's
# end and, with the end filter, lexes about 1.5 windows (5 000 characters); the fleet's commands lexed at most 207 000
# (the replay), 400 000 blocked a heredoc of 120 such lines (0.08 s). 2 million: about 400 of them, 0.4 s.
# Every pass of the lexer counts (_own_charge): a '$((' or '((' that is not arithmetic re-lexes the whole text, up to
# MAX_SPLIT_RETRIES + 1 passes per lexing. Counted once per lexing, 70 such openers in a call quoted open made the
# filter give up (past the retries) and its ends cost 2 million characters in 6.4 s, the watchdog (m3 own-budget-off).
OWN_LEX_BUDGET = 2_000_000


def _own_charge(n):
    """Adds n characters about to be lexed to this decision's count; past OWN_LEX_BUDGET the gate blocks."""
    _OWN_LEXED[0] += n
    if _OWN_LEXED[0] > OWN_LEX_BUDGET:
        raise TooManyArgs(f'a hívások saját parancsának keresése túllépte a {OWN_LEX_BUDGET} karakteres keretet (fail-closed)')


def _own_command_groups(name, rest, cut, expanded):
    """Card af12091a (Viktor 45748 K1, his Q1 direction 0f6e9cc5): a call whose cut fell inside a quoted word of its
    payload (`bash -c "python3 -W 'a;b' evil.py"`, `eval 'python3 >"x;y" evil.py'`): the cut is not the end of its
    command, and the old blank split up to it never reaches the script. The call's own command ends at the first
    operator or line end past the cut up to which its text (with the payload's closing quote, or without it) reads
    cleanly: every quote and substitution that opened in the words is closed there, so that operator is code in the
    payload. interp_groups of that text; [] when no end up to the window's reads cleanly (the old reading stands).
    A backtick end adds its reading and the search goes on (it may open a substitution in the words).
    An end after an odd run of backslashes is an escaped operator, not tried. Each call lexes its own command (and
    the shorter prefixes that failed), never the rest of the line: Q1 lexed up to the line end (the whole
    ARGS_WINDOW on a long line) for every call, and judged every later call of the line again, which made one line
    of 1500 calls take 5-6 s and run past MAX_TRIES (a fail-closed block of benign text).
    Once the ends that did not read cleanly have cost twice as much lexing as the search's distance, the call's text
    is lexed once more, four times as far (four times further again when the search passes its end), and an end
    that cannot read cleanly by that lexing is not lexed again (_own_end_filter): a call whose second end reads pays
    nothing for it, a longer search pays in proportion to its distance. Trying every end of a call
    whose text never reads cleanly (a call quoted in a Python heredoc) cost ends x window, about 6 million characters
    on a 4 KB command of the fleet (the replay: 39 benign commands past OWN_LEX_BUDGET). The filter only skips ends;
    every end it lets through is lexed as before, so the reading is the same (a test compares both on every row)."""
    if shell_lex is None or _OWN_DEPTH[0] or cut >= len(rest):
        return []
    groups = []
    pos = cut + 1
    flt = None  # the lexing of name + rest[:flt_len], made once the failed ends cost enough; False: no filter
    flt_len = spent = 0
    while True:
        e = _CALL_END_RX.search(rest, pos)
        seg = rest if e is None else rest[:e.start()]
        if (len(seg) - len(seg.rstrip('\\'))) % 2 == 0:
            for s2 in (seg, seg.rstrip()[:-1] if seg.rstrip()[-1:] in ('"', "'") else None):
                if not s2:
                    continue
                if flt and e is not None and _OWN_FILTER[0]:
                    if e.start() >= flt_len:  # the search passed the lexed part: four times as far
                        flt_len = min(len(rest), 4 * flt_len)
                        flt = _own_end_filter(name, rest[:flt_len])
                    if flt and e.start() < flt_len and not _own_end_may_read(flt, name, rest, e.start(), s2 is seg):
                        continue
                # whether the text reads cleanly is the lexer's problems, not its segments (the part LexTooBig bounds:
                # past LEX_MAX_SUBSTS every end raised it, and the search went on past the call's real end);
                # interp_groups below reads a text past the bounds by its own rule
                lx2 = _lex_no_segments(name + s2)
                if lx2 is None or lx2['problems']:
                    spent += len(name) + len(s2)
                    if flt is None and e is not None and spent >= _OWN_FILTER_AFTER[0] * (len(name) + e.end()):
                        flt_len = min(len(rest), 4 * e.end())
                        flt = _own_end_filter(name, rest[:flt_len])
                    continue
                # the call's own command reads cleanly but is past the lexer's bounds: interp_groups would read it
                # the old way, which the quoted operator fools (`eval 'python3 -W "a;b" $(:)x900 evil.py'`, bash ran
                # evil.py; card 2917e6b6 is the same class for the whole payload)
                if past_lex_bounds(name + s2, lx2['substs']):
                    raise TooManyArgs('egy hívás saját parancsa túl nagy a lexernek (fail-closed)')
                _OWN_DEPTH[0] += 1  # one level: the call's text, read again, does not look for its own end again
                try:
                    found = interp_groups(name + s2, expanded)
                finally:
                    _OWN_DEPTH[0] -= 1
                if e is None or rest[e.start()] != '`':
                    return groups + found
                # a backtick the text before reads cleanly up to is the end of a `...` around the call, or the
                # opening of one in its words (`eval 'python3 -W "a;b" \`true\` evil.py'` runs evil.py): both
                # readings, the later ends are tried too
                groups += found
                break
        if e is None:
            return groups
        pos = e.end()


_OWN_DEPTH = [0]
_OWN_LEXED = [0]  # characters lexed by _own_command_groups in this decision; script_hits sets it to 0
_OWN_FILTER = [True]  # the tests turn it off to compare the filtered reading with the unfiltered one
_OWN_FILTER_AFTER = [2]  # the filter is built once the failed ends cost this many times the search's distance; the
# tests set 0 (built at the first failed end) so that every row's ends go through it


def _no_segments(s, cls, substs):
    return []


def _lex_no_segments(text, retries_only=False):
    """shell_lex.lex(text) without its segments (segments_of is the part LexTooBig bounds; the classes,
    substitutions, heredocs and problems come from the lexing itself). None on a lexer bug.
    retries_only (the end filter): None also when the lexing needs more than MAX_SPLIT_RETRIES retries. lex() then
    splits EVERY '$((' and '((' opener ('$((a #b))' turns into a comment that never closes), so a prefix that
    needed fewer reads differently: such a lexing proves nothing about it.
    Every pass of the lexer is charged to OWN_LEX_BUDGET before it runs (lex(charge=...); card 09283e90: lex() also
    lexes a $( ) with a heredoc once more the bash 3.2 way, and may read the whole text again; a copy of its loop here
    missed both). A test compares it with lex()."""
    seg = shell_lex.segments_of
    shell_lex.segments_of = _no_segments
    try:
        return shell_lex.lex(text, charge=_own_charge, retries_only=retries_only)
    except TooManyArgs:
        raise
    except Exception:
        return None
    finally:
        shell_lex.segments_of = seg


def _own_end_filter(name, rest):
    """One lexing of the call's text (name + rest, rest cut where the caller's search will look) for
    _own_end_may_read, which reads ends before rest's end only: (classes, inside, heredocs, text, broken), inside[p]
    is true when p lies strictly inside a substitution (start < p < end; an open one ends at the text's end). Any
    text that reaches past an end proves the same for it (the proof does not use what comes after). False when the
    text does not lex (no filter: every end is lexed). Counts against OWN_LEX_BUDGET."""
    full = name + rest
    # without its segments: the filter needs the classes, substitutions and heredocs, and segments_of is the part
    # LexTooBig bounds (past LEX_MAX_SUBSTS: Python code quoted in a heredoc opens a '(' frame for every call it makes)
    lx = _lex_no_segments(full, retries_only=True)
    if lx is None:  # a lexer bug, or past the retries: no filter
        return False
    run = [0] * (len(full) + 1)
    for sub in lx['substs']:
        if sub['end'] - sub['start'] > 1:
            run[sub['start'] + 1] += 1
            run[sub['end']] -= 1
    inside, depth = [], 0
    for k in range(len(full)):
        depth += run[k]
        inside.append(depth > 0)
    # a substitution the closing backtick of a body around it ended (inner end == end, short of the text's end; a
    # closed one ends past its closer, an open one at the text's end) is a problem the lexer records there: every
    # prefix that reaches past it holds it (the body's end is found the same way in the prefix)
    broken = min([sub['end'] for sub in lx['substs'] if sub['end'] == sub['inner'][1] < len(full)] + [len(full)])
    return lx['cls'], inside, lx['heredocs'], full, broken


def _own_body_end_may_read(flt, p):
    """A prefix of the call's text that ends at p inside a heredoc body ('h', 'u') reads cleanly only if its last,
    cut line is that heredoc's delimiter (the lexer then finds the body's end there); any other cut line leaves the
    heredoc unterminated."""
    heredocs, full = flt[2], flt[3]
    for h in heredocs:
        if h['bodyStart'] <= p < h['bodyEnd']:
            line = full[full.rfind('\n', 0, p) + 1:p]
            return (line.lstrip('\t') if h['stripTabs'] else line) == h['delim']
    return True


def _own_end_may_read(flt, name, rest, end, whole):
    """False only when the call's text up to rest[end] (whole), or up to the payload's closing quote before it (not
    whole), cannot lex cleanly, by the one lexing of name + rest. The lexer reads left to right: a prefix that lexes
    cleanly leaves the stack at the top at its end, and the whole text's lexing has the same stack there (it looks
    ahead only past a backtick body, at a '$((' whose ')' follows, and one character at the end, none of which can
    turn a closed prefix open). A prefix that holds a heredoc's operator and delimiter but ends before its body
    leaves it unterminated; one that ends in a body reads only if its cut line is the delimiter
    (_own_body_end_may_read). One that reaches past a substitution a backtick body's end broke holds that problem
    (broken). So:
    - whole: the operator at p is read at the top: its class is not a quote's ('q' "'", 'd' '"', 'a' "$'") and no
      substitution is open around it. A comment ('m') or terminator ('t') class is no proof: lexed.
    - not whole: the prefix ends before the quote at q (the last non-blank before the operator), and the operator is
      past blanks only. Read at the top, q opens a quote there: the operator is inside it ('q' for "'", 'd' for '"',
      'c' for a backtick in '"', which opens a substitution there) and in no substitution. When the lexing did not
      read q as a quote character of its own (its class is no quote's, or it follows '\\' or '$', which take it into
      an escape or a "$'"/'$"' word), no proof: lexed. (Rules for those cases saved nothing on the fleet's commands,
      measured: work/af12091a/ablate.py.)"""
    cls, inside, _, full, broken = flt
    p = len(name) + end
    if p > broken or _own_heredoc_pending(flt, p):
        return False
    if whole:
        if cls[p] in 'hu':
            return _own_body_end_may_read(flt, p)
        return not (cls[p] in 'qda' or inside[p])
    q = len(name) + len(rest[:end].rstrip()) - 1
    if cls[q] in 'hu':
        return _own_body_end_may_read(flt, q)
    if cls[q] not in 'qd' or full[q - 1] in '\\$':
        return True
    want = 'q' if full[q] == "'" else ('c' if full[p] == '`' else 'd')
    return cls[p] == want and not inside[p]


def _own_heredoc_pending(flt, k):
    """A prefix that ends at k holds a heredoc's operator and whole delimiter but none of its body: unterminated."""
    return any(h['opEnd'] <= k < h['bodyStart'] for h in flt[2])


def _code_words(seg, base, cls):
    """Card 946937b7: seg (text[base:base + len(seg)]) split at the blanks the lexer reads as code; a quoted or
    escaped blank stays in its word, quotes and backslashes kept (word_forms and strip_quotes read them). cls None:
    the old blank split. In a run of blanks the quoted or escaped ones come first (a quote or a backslash opens them),
    so the word ends at the run's first code blank."""
    if cls is None:
        return seg.split()
    out, start = [], 0
    for m in _BLANK_RUN_RX.finditer(seg):
        at = next((i for i in range(m.start(), m.end()) if cls[base + i] == 'c'), None)
        if at is None:
            continue
        if at > start:
            out.append(seg[start:at])
        start = m.end()
    if start < len(seg):
        out.append(seg[start:])
    return out


def _odd_quote_word(seg):
    """A blank-split word of seg with an odd number of unescaped " or ': the split cut inside a quote."""
    for w in seg.split():
        w = re.sub(r'\\.', '', w)
        if w.count('"') % 2 or w.count("'") % 2:
            return True
    return False


_SUBST_SPAN_RX = re.compile(r'`[^`]*`|\$\([^()]*\)')


def without_substs(w):
    """Card 4bdf7309 (Viktor 43448 LELET 1 b): the word as bash reads it when every substitution in it prints nothing
    (`python3 \x60true\x60evil.py` and `python3 $(true)./evil.py` run evil.py). Inner $( ) first, then the outer."""
    prev = None
    while prev != w:
        prev, w = w, _SUBST_SPAN_RX.sub('', w)
    return w


def without_substs_lexed(w):
    """Card 946937b7 (Viktor 45532): without_substs' regex ends a $( ) at its first ) and knows no quote or backslash
    (`python3 $(true ')')m.py`, `$(true '(')m.py`, `$(true \\))m.py` run m.py); the shared lexer reads the spans as
    bash does. The word without its outermost substitutions; None when the word is cut short (a piece of a
    substitution with a blank in it: the lexer reports a problem; the regex reading stays beside it, never fewer
    words). Fail-closed (Viktor 45533): when a quote or a backslash is in the word and the lexer is not loaded, or
    does not read the word (LexTooBig: past its bounds, or a lexer bug), the regex reading may be the wrong one:
    TooManyArgs, the call is blocked."""
    quoted = '\\' in w or bool(QUOTE_RX.search(w))
    if shell_lex is None:
        if quoted:
            raise TooManyArgs('a lexer nincs betöltve, egy idézetes helyettesítés nem olvasható')
        return None
    try:
        lx = shell_lex.lex(w)
    except Exception:  # LexTooBig, or a lexer bug
        if quoted:
            raise TooManyArgs('a lexer nem olvas egy idézetes helyettesítést (korlát vagy hiba)')
        return None
    if lx['problems']:
        return None
    out, at = [], 0
    for a, b in sorted((s['start'], s['end']) for s in lx['substs'] if s['kind'] in ('`', '$(')):
        if a >= at:  # one nested in a span already cut goes with it
            out.append(w[at:a])
            at = b
    return ''.join(out) + w[at:]


def has_subst(w):
    return '`' in w or '$(' in w


# Card 8a73eab1 (Dave's audit 11-16): a variable glued to the script name is empty when unset or set to "" (`python3
# evil${X}.py`, `python3 evil$X.py`, `X=; python3 evil$X.py` run evil.py; main read the name as written and allowed).
# Only a NAME: $1, $@, $# and the other special parameters are not read (see the Known limits in the docstring).
_VAR_USE_RX = re.compile(r'\$(?:\{|[=~^]*[A-Za-z_]|[+#][A-Za-z_])')  # Viktor r1: any ${ (zsh ${(L)X}, ${=X},
# ${${X}}, ${:-w}); Kernel r2: zsh $+X (0 unset, 1 set) and $#X (0)
_PLAIN_VAR_RX = re.compile(r'\$[=~^]*[A-Za-z_]\w*')  # Viktor r1: zsh $=X, $~X, $^X
# Viktor r1: zsh reads a subscript and modifiers glued to a plain name as part of it (`evil$X[1].py`, `evil$X:r.py`
# run evil.py in zsh; bash reads [1] and :r as text): a second reading, never fewer. Kernel r2 (measured in zsh 5.9
# -f and with the fleet's setopt): on an empty value :a :A :c :e :l :q :Q :r :t :u and :s/l/r/ give "" (any
# delimiter but a word char or a blank, g before it; with no closing delimiter it runs to the word's end, as in zsh),
# :h gives "." (`ev$X:h.py` runs ev..py: a third reading), :P gives the cwd (blocks: _zsh_plain); $+X gives 0 or 1,
# $#X 0 (`ev$+X.py` runs ev0.py / ev1.py)
# Kernel r3 (Viktor 49502 LELET 3): the whole chain, :& and :g& (a repeated substitution) and a backslash-escaped
# delimiter in :s too; _zsh_chain gives its values
_ZSH_MOD = r'(?:[aAcehlPqQrtu&]|g&|g?s([^\w\s\\])(?:\\.|(?!\3)[^\s\\])*\3(?:\\.|(?!\3)[^\s\\])*\3?)'
_ZSH_PLAIN_VAR_RX = re.compile(r'\$([=~^]*|[+#])[A-Za-z_]\w*(?:\[[^\]\s]*\])?((?::' + _ZSH_MOD + r')*)')
_ZSH_MOD_TOKEN_RX = re.compile(r':(?:([aAcehlPqQrtu&]|g&)|g?s([^\w\s\\])(?:\\.|(?!\2)[^\s\\])*\2'
                               r'((?:\\.|(?!\2)[^\s\\])*)\2?)')
# Viktor r1: ${!PREFIX*} / ${!PREFIX@} expand to the NAMES of the shell's variables (`ev${!HOM*}il.py` runs
# evHOMEil.py), not to an empty value; and a zsh flag group ${(L)X}: the call's words end at ( and ), so it arrives
# cut (`evil${(L`). The name list is a glob: any run (GLOB_MARK; resolve() globs it per base, the word's literal
# parts escaped), so `meas${!HOM*}ure.py` blocks when a measure.py-like file is there (a variable's name holds no dot
# and no slash). Kernel r3 (Viktor 49502 LELET 1): the cut group blocks (TooManyArgs, as in prop2): what follows the
# paren is lost, so the name may go on into a dot file or a subdirectory a glob does not see. Except in a heredoc
# body no shell reads (the direct path scan reads every body: prop2's block hit a JS template literal `${(a + b)}`
# in a heredoc to cat in the replay): there it stays a glob (KNOWN-V9). A NUL in the word as written blocks (LELET
# 4: a glob would read it as any run); the mark is var_readings' alone (_GLOB_MARKED)
_NAME_LIST_RX = re.compile(r'\$\{![A-Za-z_]\w*[*@]\}|\$\{\([^)]*$')
_CUT_GROUP_RX = re.compile(r'\$\{\([^)]*$')
GLOB_MARK = '\x00'
_GLOB_MARKED = set()  # the forms word_forms made with the mark (resolve() globs these only)
# ${NAME}, ${NAME:-w} / ${NAME-w} / = / + / ?, ${#NAME}, ${!NAME}, and the other modifiers (${NAME#p}, ${NAME/a/b},
# ${NAME:0:1}, zsh ${NAME:h}): innermost first, a word holding no brace (so a nested ${Y} inside w is read on the
# round before). The (?!\w) ends the name where it ends: without it `${A` + 1 MB of letters gave the name back one
# char at a time and rescanned the rest each time (quadratic, measured: past 120 s)
# Viktor r1: zsh flags and an empty name too: ${(L)X}, ${=X}, ${~X}, ${^X}, and ${:-w} (zsh: w; what an inner
# ${X} leaves of `${${X}:-evil}`; bash: a bad substitution, nothing runs, so the extra reading costs nothing)
# Kernel r2: zsh ${+X} (0 or 1), and the modifier text kept (group 6) for the alt reading (_empty_param)
# Kernel r3 (Viktor 49502 LELET 2): a subscript after the name (`ev${X[1]:-il}.py`, `${X[@]:-il}` run evil.py)
_BRACE_VAR_RX = re.compile(r'\$\{((?:\([^(){}]*\))?[=~^]*[#!+]?)((?:[A-Za-z_]\w*)?)(?!\w)(?:\[[^\[\]{}]*\])?'
                           r'(?:(:?)([-=+?])([^{}]*)|([^{}]*))\}')
# Kernel r2: the same with a quoted or escaped brace in the word (`ev${X:-i\}l}.py`, `ev${X:-i'}'l}.py` run
# evi}l.py in bash and zsh; the plain form ends at the first brace). A reading of its own: an unbalanced quote in the
# word (`${X:-it's}`) does not match here and keeps the plain form's reading
_BRACE_WORD_Q = r'(?:\\.|' + r"'[^']*'" + r'|"(?:\\.|[^"\\])*"|' + r"""[^{}\\'"])*"""
_BRACE_VAR_Q_RX = re.compile(r'\$\{((?:\([^(){}]*\))?[=~^]*[#!+]?)((?:[A-Za-z_]\w*)?)(?!\w)(?:\[[^\[\]{}]*\])?'
                             r'(?:(:?)([-=+?])(' + _BRACE_WORD_Q + r')|(' + _BRACE_WORD_Q + r'))\}')
# Kernel r2 (measured in zsh 5.9): on an empty value a pattern substitution whose pattern matches "" gives its
# replacement (`ev${X/#/il}.py`, `${X/%/il}`, `${X//*/il}`, `${X/*/il}` run evil.py), and ${X::=w} gives w
_ZSH_SUBST_RX = re.compile(r'/[/#%]?(?:\\.|[^/\\])*/(.*)', re.S)
MAX_VAR_NEST = 8


def _zsh_chain(mods):
    """Kernel r3 (Viktor 49502 LELET 3; measured in zsh 5.9, -f and with the fleet's setopt): the values zsh gives a
    modifier chain (`:h:a`, `:s/a/b/:P`, `:&`) on an empty or unset value, in order. "" stays "" under every modifier
    but :h ("."); "." stays "." under :c :h :l :q :Q :t :u, becomes "" under :e :r, and under a substitution "." or
    its replacement. Not read, TooManyArgs (the call blocks): :P and :a / :A on "." (the cwd's absolute path), :& on
    "." (its pattern is the previous one), and any modifier after a replacement. The chain ends at the first text
    that is no modifier (`$X:x.py` is ":x.py" in zsh). At most two values; a linear walk."""
    vals = ['']
    pos = 0
    while pos < len(mods):
        m = _ZSH_MOD_TOKEN_RX.match(mods, pos)
        if not m:
            break
        pos = m.end()
        op = m.group(1)
        nxt = []
        for v in vals:
            if v not in ('', '.'):
                raise TooManyArgs('zsh módosító egy csere után a szkript nevében: nem olvasható')
            if op == 'P' or (v == '.' and op in ('a', 'A')):
                raise TooManyArgs('zsh :P vagy :h:a módosító egy változón a szkript nevében: a cwd, nem olvasható')
            if op is None:  # :s / :gs: "" has nothing to replace; "." is kept or replaced
                rep = re.sub(r'\\(.)', r'\1', m.group(3))
                nxt += [v] + ([rep, rep.replace('&', '.')] if v == '.' else [])
            elif op in ('&', 'g&'):
                if v == '.':
                    raise TooManyArgs('zsh :& módosító a :h után a szkript nevében: nem olvasható')
                nxt.append(v)
            elif op == 'h':
                nxt.append('.')
            elif op in ('e', 'r'):
                nxt.append('')
            else:
                nxt.append(v)
        vals = list(dict.fromkeys(nxt))
    return vals


def _empty_param(m, set_empty, alt=0):
    """The value of one ${...} when NAME is unset (set_empty False) or set to "" (True). alt (Kernel r2/r3): zsh's
    reading where bash's and zsh's differ on an empty value: a pattern substitution (also zsh's ${X:/p/r}) gives its
    replacement, ${X::=w} gives w, a modifier chain its zsh value (_zsh_chain: alt 1 the first, alt 2 the last);
    without alt they give ""."""
    pre, colon, op, word = m.group(1)[-1:], m.group(3), m.group(4), m.group(5)
    if pre == '#':
        return '0'  # the length of an empty value
    if pre == '+':
        return '1' if set_empty else '0'  # zsh: is NAME set
    if op is None:
        rest = m.group(6) or ''
        if pre == '!':
            return ''  # indirection through an empty name
        if rest.startswith('::='):
            return rest[3:] if alt else ''
        sub = _ZSH_SUBST_RX.match(rest[1:] if rest.startswith(':/') else rest)
        if sub:
            return sub.group(1) if alt else ''
        if rest.startswith(':'):
            vals = _zsh_chain(rest)  # raises on :P and :h:a, alt or not
            return (vals[0] if alt == 1 else vals[-1]) if alt else ''
        return ''  # a modifier of "" (bash, and zsh without alt)
    if pre == '!' or op == '?':
        return ''  # indirection through an empty name, or ${X?msg} (an error: nothing runs)
    takes_word = bool(colon) or not set_empty  # ':' treats "" as unset; without it only an unset name is
    if op in '-=':
        return word if takes_word else ''
    return '' if takes_word else word  # '+': the word only for a set name


def _zsh_plain(m, set_empty, mode):
    """Kernel r2/r3: zsh's value of one plain $NAME with its subscript and modifier chain, NAME unset or set to "".
    mode 0: "" for the chain (read with "" too), 1 / 2: the first / last value _zsh_chain gives."""
    pre, mods = m.group(1), m.group(2)
    if pre == '+':
        return '1' if set_empty else '0'
    if pre == '#':
        return '0'
    vals = _zsh_chain(mods) if mods else ['']  # raises on :P and :h:a in every mode
    return '' if mode == 0 else (vals[0] if mode == 1 else vals[-1])


def var_readings(w, cut_glob=False):
    """Card 8a73eab1: w as the shell reads it when every variable in it is unset, and when every one is set to "":
    $NAME and ${NAME} are empty, ${NAME:-w} gives w, ${NAME+w} gives w only for the set-to-"" reading, and so on;
    and (Viktor r1, Kernel r2/r3) zsh's readings: a plain name's subscript and modifier chain, $+X, $#X, a pattern
    substitution's replacement, ${X::=w}, :h as ".", a subscript in a brace, and a quoted or escaped brace in a
    default word. [] when no variable is in w. A name list ${!P*} is any run (GLOB_MARK, a glob for resolve()). Not
    read, TooManyArgs (the call blocks; a linear walk per level, no unbounded loop): a brace nested past
    MAX_VAR_NEST levels, a zsh :P or :h:a, a NUL in w, and a zsh flag group cut at its paren, except where the
    caller says cut_glob (a heredoc body no shell reads: a glob there, KNOWN-V9). The caller adds the readings to
    the word's forms: never fewer."""
    if GLOB_MARK in w:
        raise TooManyArgs('NUL karakter a szkript nevében: nem olvasható')
    if not _VAR_USE_RX.search(w):
        return []
    if not cut_glob and _CUT_GROUP_RX.search(w):
        raise TooManyArgs('kettévágott zsh-jelzőcsoport (${() a szkript nevében: a folytatása nem olvasható')
    if _NAME_LIST_RX.search(w):
        w = _NAME_LIST_RX.sub(GLOB_MARK, w)  # a glob (see _NAME_LIST_RX)
    # the extra passes only where they can give another reading (each pass is a linear walk per level)
    brace_rxs = (_BRACE_VAR_RX, _BRACE_VAR_Q_RX) if ('\\' in w or "'" in w or '"' in w) else (_BRACE_VAR_RX,)
    # an alt reading only changes a brace; the last value (2) differs from the first (1) only after a substitution
    two = (1, 2) if (':s' in w or ':gs' in w) else (1,)
    alts = (0,) + two if ('${' in w and (':' in w or '/' in w)) else (0,)
    modes = (0,) + two if ':' in w else (0,)
    out = []
    for set_empty in (False, True):
        for brx in brace_rxs:
            for alt in alts:
                s = w
                for _ in range(MAX_VAR_NEST + 1):
                    prev, s = s, brx.sub(lambda m: _empty_param(m, set_empty, alt), s)
                    if s == prev:
                        break
                else:
                    if brx.search(s):
                        raise TooManyArgs(
                            f'egy változó-kifejezés {MAX_VAR_NEST} szintnél mélyebben egymásba ágyazva')
                out.append(_PLAIN_VAR_RX.sub('', s))
                for mode in modes:
                    out.append(_ZSH_PLAIN_VAR_RX.sub(lambda m: _zsh_plain(m, set_empty, mode), s))
    return list(dict.fromkeys(out))


def merged_span(all_words, i, quoted=False):
    """The call's words are split at blanks, so a substitution with a blank in it (`$(echo $(true))m.py`) is in
    pieces: join the pieces from i while a backtick or a "(" is still open (at most MAX_ARGS pieces).
    quoted (card 946937b7, Viktor 45532): a quote, a backslash and the parens in them as bash reads them, with
    _redir_scan's state (`$(true ')' $(true '('))m.py` is one word; the count joins too few pieces). The caller
    reads both joins: never fewer words. -> (the joined word, the index of its last piece)."""
    s = all_words[i]
    j = i
    if quoted:
        state = _redir_scan(s)[1]
        while any(state) and j + 1 < len(all_words) and j - i < MAX_ARGS:
            j += 1
            s += ' ' + all_words[j]
            state = _redir_scan(all_words[j], state)[1]
        return s, j
    while (s.count('`') % 2 or s.count('(') > s.count(')')) and j + 1 < len(all_words) and j - i < MAX_ARGS:
        j += 1
        s += ' ' + all_words[j]
    return s, j


def merged_word(all_words, i):
    return merged_span(all_words, i)[0]


def needs_forms(raw):
    """A word bash reads otherwise than strip_quotes does: a substitution, a variable (card 8a73eab1), or a quote /
    backslash anywhere in it."""
    return (has_subst(raw) or '\\' in raw or bool(_VAR_USE_RX.search(raw))
            or bool(QUOTE_RX.search(raw[1:-1] if len(raw) > 1 else '')))


def word_forms(all_words, i, cut_glob=False):
    """Card 70c94516 (Viktor 43662 LELET 1): the other names bash may run for word i, besides strip_quotes' form:
    the whole-word quote removal (`"ev"il.py`), and with a substitution in it (pieces joined) the word without the
    substitutions, before and after the quote removal (`"$(true)"evil.py`, `evil"$(true)".py`). Distinct, in order;
    "" when a substitution may leave nothing. The caller adds them to the strip_quotes form: never fewer words.
    cut_glob: var_readings' (a word of a heredoc body no shell reads)."""
    raw = merged_word(all_words, i) if has_subst(all_words[i]) else all_words[i]
    forms = [shell_unquote(raw)]
    if has_subst(raw):
        forms += [without_substs(strip_quotes(raw)), shell_unquote(without_substs(raw))]
        for r in dict.fromkeys([raw, merged_span(all_words, i, quoted=True)[0]]):
            lexed = without_substs_lexed(r)
            if lexed is not None:
                forms.append(shell_unquote(lexed))
    # card 8a73eab1: every variable left in the word (expand() replaced the ones the text sets to a plain value) may
    # be empty: `evil${X}.py`, `"ev"il$X.py`, `evil${X:-}.py`, `$(true)evil$X.py`
    for v in var_readings(raw, cut_glob):
        if v != raw:
            forms.append(shell_unquote(v))
            if has_subst(v):
                forms.append(shell_unquote(without_substs(v)))
    if GLOB_MARK in raw or any(GLOB_MARK in f for f in forms[1:]):
        _GLOB_MARKED.update(f for f in forms if GLOB_MARK in f)  # Kernel r3: the marks var_readings made
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
    # card 946937b7 (Viktor 45520): which chars are code, not quoted or escaped; a blank or an operator in a quote is
    # word text (`python3 -W "a b" m.py`, `python3 >"x y" m.py`, `python3 "a b.py"`). No quote, no backslash: the
    # blank split is the shell's, and the lexer is not run.
    quoted = bool(_QUOTED_RX.search(text))
    lx = lex_or_none(text) if quoted else None
    cls = lx['cls'] if lx else None
    redir_cache = {}
    for m in INTERP_RX.finditer(text):
        python = 'python' in m.group(0).lower()
        name = re.split(r'[\s;&|(){}`\'"/\\]', m.group(0).rstrip('\'"\\'))[-1]
        argv_data = bool(DATA_ARGV_RX.fullmatch(name)) and not expanded  # still True after a known option; False = the old walk
        # (expanded: expand() read a VAR=value anywhere in the text as this shell's assignment; the real value may be empty
        # (X=a python3 $X m.py, unset X, a comment) and the script the second word: such a text keeps the old walk)
        rest = text[m.end():m.end() + ARGS_WINDOW]  # a window, not the rest: 6 000 calls x the rest was quadratic
        # the lexer's classes read a call whose name is code; one inside a quoted payload (`eval "python3 m.py"`,
        # `tmux new 'python3 m.py'`) is all quoted text to them, and its words would never split: it keeps the old
        # reading here, and the payload pass reads the payload's own text as code
        ccls = cls if cls is not None and cls[m.end() - 1] == 'c' else None
        cut = _call_end(rest, m.end(), openers, ccls)
        unread = (openers is None and _OPENS_RX.search(rest, 0, cut)) or (cls is None and quoted and (
            _odd_quote_word(rest[:cut]) or _ESC_SEP_RX.search(rest, 0, cut + 1)))
        if unread:
            # card 946937b7 (replay of 59811cb0: 916 everyday fleet commands blocked): the text the lexer did not
            # read is this gate's own view (a payload's quotes marked as `;`, a python -c body, prose), so a
            # quote there is often unbalanced although the shell read the command. The call's OWN words, lexed
            # alone: when they read cleanly, their reading decides (the cut was the call's end); when not (a cut
            # inside a substitution or a quote that opened in the words), the fail-closed below stands
            # an odd run of backslashes right before the cut: the cut is on an escaped operator, not the call's end
            esc = len(rest[:cut]) - len(rest[:cut].rstrip('\\'))
            local = None if esc % 2 else _call_alone_groups(name, rest[:cut], expanded)
            if local is not None:
                groups += local
                continue
            groups += _own_command_groups(name, rest, cut, expanded)
        # ... and when the command AS WRITTEN reads cleanly (886 of the 893 replay rows), the unread text is this gate's
        # view only: the old reading stands, as before card 946937b7. Viktor's shapes are commands the lexer refuses
        # as written (past LEX_MAX_SUBSTS or LEX_MAX_WORK): there the fail-closed stands
        if not _CMD_READ[0] and openers is None and _OPENS_RX.search(rest, 0, cut):
            # card 946937b7 (Viktor 45543, fail-closed): without the lexer's reading (not loaded, past LEX_MAX_SUBSTS or
            # LEX_MAX_WORK, a lexer bug) a ")" may close a substitution that opened inside the call's words and cut it
            # short (`python3 $(true)m.py; echo` and 64 more substitutions ran m.py). No "(" and no backtick before
            # the cut: the cut is the call's own end, the old reading stands
            raise TooManyArgs('a lexer nem olvasta a szöveget, és a hívás szavaiban helyettesítés nyílik (fail-closed)')
        if not _CMD_READ[0] and cls is None and quoted and (
                _odd_quote_word(rest[:cut]) or _ESC_SEP_RX.search(rest, 0, cut + 1)):
            # card 946937b7 (Viktor 45520, fail-closed): the lexer could not read the text, and a quote in the call's
            # words leaves the old blank split unsure which word is the script; so does an escaped blank or operator
            # (Viktor 45626 R4b: `python3 2>x\& m.py` with 66 substitutions in the text ran m.py)
            raise TooManyArgs('az interpreter-hívás szavaiban páratlan idézőjel, a lexer nem olvasta (fail-closed)')
        # card 946937b7 (Viktor 45626 R2): a call the lexer read as quoted text (an eval payload, a heredoc body)
        # keeps the old blank split above, which a quoted blank fools (`eval 'python3 -W "a b" m.py'`). Its own
        # text, lexed alone (without the payload's closing quote if it does not read otherwise), is read as code
        # too: its groups are ADDED, the old reading stays
        # (card af12091a: an expanded text skips that lexed reading, as before, but not the call's own command below:
        # `echo X=notes.py; eval 'python3 -W "a;b" $X evil.py'` ran evil.py, X is empty in bash; expanded keeps the
        # old walk there)
        # card 2917e6b6 (2026-11-18, measured with bash and zsh): a substitution in the payload cuts the call too, at
        # its ")" or backtick, with no quote before it: `eval 'python3 $(:) evil.py'` read the script as `$(:` and ran
        # evil.py on main and on this branch (one substitution is enough; past LEX_MAX_SUBSTS too). A "(" or a
        # backtick before the cut takes the same path as a quote (a cut ON an opening backtick: decoded_payloads)
        if ccls is None and cls is not None and (_QUOTED_RX.search(rest, 0, cut) or _OPENS_RX.search(rest, 0, cut)):
            seg = rest[:cut]
            esc2 = len(seg) - len(seg.rstrip('\\'))
            for s2 in ((None, None) if expanded or esc2 % 2 else (seg, seg.rstrip()[:-1] if seg.rstrip()[-1:] in ('"', "'") else None)):
                if s2 is None or shell_lex is None:
                    continue
                try:
                    lx2 = shell_lex.lex(s2)
                except Exception:
                    continue
                if not lx2['problems']:
                    groups += interp_groups(name + s2)
                    break
            else:
                groups += _own_command_groups(name, rest, cut, expanded)
        all_words = split_redirections(_code_words(rest[:cut], m.end(), ccls), redir_cache)
        # the window ended inside this command: what follows it is not read
        clipped = cut == len(rest) == ARGS_WINDOW and m.end() + ARGS_WINDOW < len(text)
        if name in ('.', 'source'):
            # source runs its first word and hands it the rest as $1...: a runner.sh that runs its $1 would hide
            # m.py in `source runner.sh m.py` (Viktor 41831 LOW 1). The rest is judged only when the first word is an
            # existing file (script_paths): prose after a ")" made a sentence-ending "." read as source of a file
            # named later in the sentence (an agent-msg heredoc, 2026-11-14), and there the next word is no file.
            # card 946937b7: a redirection before the file is no file (`source >"a b" x.sh`, `source </dev/null x.sh`)
            lead = 0
            while lead < len(all_words):
                rd = SRC_REDIR_RX.match(all_words[lead])
                if not rd:
                    break
                lead += 1 if rd.group(1) else 2
            all_words = all_words[lead:]
            idx = next((i for i, w in enumerate(all_words[:2]) if not w.startswith('-')), None)  # `. -- f.sh` too
            first = strip_quotes(all_words[idx]) if idx is not None else ''
            if first:
                # card 70c94516 (Viktor 43662 LELET 2): f read as bash does (quotes, substitutions); when a
                # substitution may leave nothing of it (`source $(true) x.sh`), the next word is the file
                firsts = [first]
                if needs_forms(all_words[idx]):
                    forms = word_forms(all_words, idx)
                    firsts += [f for f in forms if f and f not in firsts]
                    for end in dict.fromkeys([merged_span(all_words, idx)[1], merged_span(all_words, idx, quoted=True)[1]]):
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
        group = ScriptGroup()
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
                if not group.lead:  # card 00c714ea: the script position (the first word the call may run)
                    group.lead = frozenset([w] + forms)
                    # only a call in code: one inside a quoted text (`python3 -c "x = 'bash ' * 3"`) is read as
                    # its own text by the payload pass, where the shell would glob (1 fleet command, measured)
                    group.expand = unquoted_pattern(all_words[i]) and (cls is None or cls[m.end() - 1] == 'c')
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


def script_paths(cmd, cwd, normalised=None, extra=(), live=None):
    """The script files the command runs (resolved, existing regular files), at most MAX_SCRIPTS (an eleventh file
    or more than MAX_BASES directories returns MAX_SCRIPTS + 1 entries: the caller blocks). Raises TooManyArgs.
    extra: more words to look up as files (a pipeline into a shell, card 74586987)."""
    norm = normalise(cmd) if normalised is None else normalised
    # a for-loop variable keeps its $NAME here (Viktor deede5e4 r1 P2: `F=ok.py; for F in ev.py; do python3 $F`
    # read ok.py only): loop_word_paths reads every loop value AND every plain value assigned to the name
    lnames = frozenset(loop_lists(_blank_data_heredocs(norm))) if 'for' in norm else frozenset()
    text = expand(norm, lnames)
    # card 00c714ea: a name whose value the shell reads otherwise than expand() blocks in a script position; the
    # reading above stays as it was (only a block is added: keeping such a name unexpanded there let 5 fleet commands
    # through that the expanded reading blocked, measured)
    vbad = value_unread_names(norm) - lnames
    if vbad:
        for g in interp_groups(expand(norm, lnames | vbad), True):
            for c in getattr(g, 'lead', ()):
                # a name inside a substitution is no part of the script word (`bash $(sh -c "$C")` in prose)
                if ({v.group(1) or v.group(2) for v in VAR_RX.finditer(without_substs(c))} & vbad
                        or ('HOME' in vbad and c.startswith('~'))):
                    raise PathUnread(f'a script word from a value the shell splits, globs or unescapes: {c[:40]}')
    # card 10624d73: an expansion the shell makes as read (expansion_trusted) keeps the argv-data reading; on the
    # command as written too, not only on this text: a payload-marked text turned the quote of `bash -c 'python3 $X
    # evil.py'` into a boundary, and its $X (empty in the inner bash) looked unquoted (found by the oracle cases)
    plain = normalise(cmd)
    trusted = (plain == cmd and expansion_trusted(norm, lnames) and
               (norm == plain or expansion_trusted(plain, lnames)))  # r1: normalise() changed nothing
    # card 0196e1ee (Viktor 43793 LOW 2): a word a pipe feeds a shell is globbed and brace-expanded by that shell (or
    # by the feeder's own shell, unquoted), whatever its quotes were: `echo ./x.s? | bash`, `echo './x.*' | bash`,
    # `echo ./{x,y}.sh | bash` ran x.sh. Its first match is the command, as for a script word (resolve_word)
    groups = interp_groups(text, text != norm and not trusted) + [
        ScriptGroup([w], lead=frozenset([w]), expand=True, zsh=False)
        if (_GLOB_CHARS_RX.search(w) or _BRACE_ALT_RX.search(w)) and (live is None or w in live) else [w]
        for w in extra]
    if text != norm and not trusted:
        # card 8a73eab1: an expansion the shell may not make (`echo X=a; python3 evil$X.py`: $X is empty, evil.py
        # runs) is read without it too, so the variable-empty readings of word_forms see the $X
        groups += interp_groups(norm, True)
    # card 70c94516 (Viktor 43662 LELET 1): normalise() takes the backslash of a $'\x65' escape (`\x` -> `x`), which
    # bash decodes in a word (`python3 $'\x65vil.py'` runs evil.py): such a command is read without it too
    word_texts = [text]
    if "$'" in cmd and '\\' in cmd:
        raw = expand(cmd, lnames)
        groups += interp_groups(raw, raw != cmd)
        word_texts.append(raw)
    # the script on stdin: only when an interpreter runs, or (card 3bcd4514) a reader of shell code: eval (`eval
    # "$(cat m.sh)"`), and a shell under a name INTERP does not list (`$SHELL < m.sh`, `bash5 < m.sh`, `fish`; found
    # by the mutation round). The reader's eval reads the quoted and escaped forms too (`"eval"`, `\eval`)
    if INTERP_RX.search(text) or _hn_reader_rx().search(text):
        groups += [[m.group(1)] for m in REDIRECT_RX.finditer(text)]
        for m in [*CAT_RX.finditer(text), *HEADTAIL_RX.finditer(text)]:
            cat_words = (m.group(1) or m.group(2)).split()
            if len(cat_words) > MAX_ARGS:
                raise TooManyArgs(f'cat: {len(cat_words)} szó, MAX_ARGS {MAX_ARGS}')
            groups += [[strip_quotes(w)] for w in cat_words if not w.startswith('-')]
    # card 0196e1ee (Viktor 43793 LOW 2, KNOWN-KTP-WORD direct-glob / direct-brace): a path run directly is globbed
    # and brace-expanded too (`./x.s?`, `./x.*`, `./{evil,x}.sh` ran x.sh / evil.sh): its first match is the script.
    # Only when no quote opens the word (`'./x.s?'` runs the file named so)
    dcls = None  # card 0196e1ee: a direct pattern is globbed only at a code position or in a heredoc body a shell
    # reads (a JSDoc `/**` line in a `python3 - <<'PY'` body is data: the fleet replay blocked 113 such commands on
    # the walk from /); no lexer: all. Nor right after a process substitution's ")" (`diff <(sed ..) b/k*.py`: the
    # word is diff's argument; the fleet replay blocked one such command); a text the lexer does not read: the
    # command's own lexing (_direct_code_view)
    raw_left = [_DIRECT_RAW_MAX]
    has_quote = None  # Viktor 49925 L2: searched once per text (per match it was quadratic: 27 000 fed globs, 54 s)
    for m in DIRECT_RX.finditer(text):
        w = m.group(1)
        quoted = m.start(1) > 0 and text[m.start(1) - 1] in '\'"'
        pat = not quoted and unquoted_pattern(w)
        if pat and has_quote is None:
            has_quote = _QUOTED_RX.search(text) is not None
        if pat and (has_quote or text[m.start()] == ')'):
            if dcls is None:
                dcls = _direct_code_view(text, cmd)
            if dcls is False:
                pass
            elif dcls[0] is None:
                pat = not _only_in_data_bodies(w, text, cmd, dcls[1], raw_left)
            else:
                pat = (dcls[0][m.start(1)] == 'c' or any(
                    a is not None and b is not None and a <= m.start(1) < b for a, b in dcls[1])) and not (
                    text[m.start()] == ')' and m.start() + 1 in dcls[2])
        groups.append(ScriptGroup([w], lead=frozenset([w]), expand=True) if pat else [w])
    # Kernel r3: a heredoc body no shell reads (blanked here) keeps the cut zsh flag group's glob reading (KNOWN-V9)
    data_texts = {id(t): _blank_data_heredocs(t) if '${(' in t else t for t in word_texts}
    for t, m in ((t, m) for t in word_texts for m in DIRECT_WORD_RX.finditer(t)):
        if not _DIRECT_WORD_PLAIN_RX.match(t, m.start()) and not _esc_word_at_code(t, m.start(1), cmd, m.group(1)):
            continue
        in_data = data_texts[id(t)][m.start(1)] != t[m.start(1)]
        raw = m.group(1).rstrip(';&|<>')
        if len(raw) > ARGS_WINDOW:  # without_substs is a loop per nesting level: an unbounded word is not read
            raise TooManyArgs(f'egy útvonal-szó hosszabb {ARGS_WINDOW} karakternél')
        raws = [raw]
        if has_subst(raw):
            # card 946937b7 (Viktor 45533): a substitution with a blank in it (`./$(true ')')x.sh`) goes on past the
            # blank: the pieces joined as bash reads quotes and parens (merged_span quoted), within ARGS_WINDOW
            at = m.start(1)
            joined = merged_span(t[at:at + ARGS_WINDOW].split()[:MAX_ARGS + 1], 0, quoted=True)[0].rstrip(';&|<>')
            if joined != raw:
                raws.append(joined)
        group = ScriptGroup()
        for raw in raws:
            # a ")" may close the substitution the path stands in (`$(./x"y".sh)`): read with and without it
            k = redir_at(raw)  # G1: `./"x".sh;true`, `./"x".sh>log`: the word ends at the operator
            group += [f for r in dict.fromkeys([raw, raw.rstrip(')')] + ([raw[:k]] if k else []))
                      for f in word_forms([r], 0, in_data) if f]
        group = list(dict.fromkeys(group))
        groups.append(ScriptGroup(group, lead=frozenset(group),  # card 00c714ea: a path run directly is the script
                                  expand=any(unquoted_pattern(r) for r in raws)))
    # a `for x in os.listdir(d):` of a python heredoc is not the shell's loop (loop_lists of a blanked body)
    loops = loop_lists(_blank_data_heredocs(text)) if 'for' in text else {}
    for m in ASSIGN_CHAIN_RX.finditer(text):
        if loops.get(m.group(1)) is not None:
            v = expand(m.group(3), lnames)
            loops[m.group(1)] = None if '$' in v else loops[m.group(1)] + [strip_quotes(v)]
    bases = cd_bases(text, cwd, loops)
    if groups and len(bases) > MAX_BASES:
        return [''] * (MAX_SCRIPTS + 1)
    out = []
    tries = [0]

    def resolve(c):
        """Add the existing regular files word c names; True if there was one. None: past MAX_TRIES. Raises
        PathUnread (deede5e4): a relative word after a directory change cd_bases does not follow, or a word with a
        loop variable over not plain words."""
        if GLOB_MARK in c:  # card 8a73eab1: a name list (var_readings' mark): a glob per base, the rest escaped
            if c not in _GLOB_MARKED:  # Kernel r3 (Viktor 49502 LELET 4): a NUL in the word as written
                raise TooManyArgs('NUL karakter a szkript nevében: nem olvasható')
            import glob
            return resolve_glob('*'.join(glob.escape(os.path.expanduser(part) if k == 0 else part)
                                         for k, part in enumerate(c.split(GLOB_MARK))))
        c = os.path.expanduser(c)
        if not c or c in ('-', '--'):
            return False
        if c.startswith('~+') and c[2:3] in ('', '/'):
            c = '$PWD' + c[2:]
        if _PWD_RX.search(c):  # the shell's current directory: each base (Viktor deede5e4 r1 L2)
            if bases.unknown or not bases:
                raise PathUnread(f'$PWD after a directory change the gate does not follow: {c[:40]}')
            found = False
            for b in list(bases):
                r = resolve(_PWD_RX.sub(lambda _m, b=b: b, c))
                if r is None:
                    return None
                found = found or r
            return found
        if '$' in c and loops:
            found = False
            for v in loop_word_paths(c, loops):
                if v == c:
                    break
                # a value naming a directory: `python3 $f` runs its __main__.py, as a plain script word does ("a
                # directory runs its __main__.py" above); read for every interpreter (one more file, never fewer)
                for u in (v, os.path.join(v, '__main__.py')):
                    r = resolve_glob(u) if _GLOB_CHARS_RX.search(u) else resolve(u)
                    if r is None:
                        return None
                    found = found or r
            else:
                return found
        if bases.unknown and not os.path.isabs(c):
            raise PathUnread(f'a relative script path after a directory change the gate does not follow: {c[:40]}')
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

    def resolve_glob(v):
        """A loop value with a glob (`for f in sub/*.py; do python3 $f`): each file it matches in each base, as bash
        expands it there (at most MAX_LOOP_PATHS; more raises PathUnread); none: the word as written.
        r5 (Viktor 49863 M1, old, main too): read as resolve_lead_glob reads a glob. `for f in **/measure.py; do python3
        "$f"; done` (and `***/`, `**/*.py`) ran a/b/c/measure.py in zsh, while a plain iglob read `**` and `***` as one
        `*` and found nothing: `**` is read recursively (bash without globstar reads it as `*`: one more file, never
        fewer), `***/` as `**/`, the walk bounded by MAX_STAR_DIRS, and `[^x]` as `[!x]`."""
        import glob
        g = _STAR3_RX.sub('**', v.replace('[^', '[!'))  # the glob as the shell reads it; none matched: v as written
        if bases.unknown and not os.path.isabs(v):
            raise PathUnread(f'a relative script path after a directory change the gate does not follow: {v[:40]}')
        hits = []
        for b in ([None] if os.path.isabs(g) else bases):
            pat = g if b is None else os.path.join(glob.escape(b), g)
            star_walk_bounded(pat)
            for h in glob.iglob(pat, recursive=True):
                hits.append(h)
                if len(hits) > MAX_LOOP_PATHS:
                    raise PathUnread(f'a loop glob naming more than {MAX_LOOP_PATHS} files: {v[:40]}')
        if not hits:
            return resolve(v)
        found = False
        for h in hits:
            r = resolve(h)
            if r is None:
                return None
            found = found or r
        return found

    def resolve_lead_glob(v):
        """Card 00c714ea: a glob in the script position runs its FIRST match (the others are its arguments): in each
        base the first match in byte order and in case-folded order (bash sorts by the locale); none matched, the
        word as written. Reading every match blocked 26 fleet commands (script-too-many, past MAX_LOOP_PATHS)."""
        import glob
        v = v.replace('[^', '[!')  # Viktor r1: bash and zsh read [^x] as [!x]; fnmatch reads ^ as a member
        v = _STAR3_RX.sub('**', v)  # r4 (Viktor 49785 L1): zsh's ***/ walks like **/ and follows links
        if bases.unknown and not os.path.isabs(v):
            raise PathUnread(f'a relative script path after a directory change the gate does not follow: {v[:40]}')
        firsts = []
        for b in ([None] if os.path.isabs(v) else bases):
            hits, pat = [], v if b is None else os.path.join(glob.escape(b), v)
            star_walk_bounded(pat)  # Viktor 49709 L2: a `**` walk is bounded by directories, not only matches
            for h in glob.iglob(pat, recursive=True):
                hits.append(h)
                if len(hits) > MAX_LEAD_GLOB:
                    raise PathUnread(f'a script glob naming more than {MAX_LEAD_GLOB} files: {v[:40]}')
            if hits:
                firsts += [min(hits), min(hits, key=lambda h: (h.casefold(), h))] + _locale_firsts(hits)
        if not firsts:
            return resolve(v)
        found = False
        for h in dict.fromkeys(firsts):
            r = resolve(h)
            if r is None:
                return None
            found = found or r
        return found

    def zsh_paren_may_match(c):
        """Card 00c714ea r2: True when a zsh group or qualifier paren in script word c could hand a file to the
        interpreter. The word arrives cut at ) and |, so it is looked up in the command text and its groups are made
        into their members (zsh_group_globs, every occurrence: a decoy before the call cannot hide it); a text it does
        not follow, or a word it does not find there, falls back to what precedes the paren plus `*`. Any of those
        patterns matching a file or directory in a base (hidden ones too: the last component is also tried with a
        leading dot, as `(.evil|x).py` and `*(D)` match; include_hidden is 3.11+, the hook may run on 3.9) blocks the
        word unread: zsh's choice among them is not modelled. None matching, zsh runs nothing ("no matches found") and
        bash stops on the paren. A `$` before the paren: the value is not expanded here, the patterns keep the `$`
        and match no file (KNOWN-KTP-VAR). Why: every
        paren read as unread blocked 311 fleet commands on the replay, and the prefix alone 97 (words cut from python,
        JS and prose: `(15`, `(argv,`, `/${p}`), none of which zsh could run."""
        import glob
        m = _ZSH_GLOB_PAREN_RX.search(c)
        if not m:
            return False
        pats, seen = [], 0
        # the paren part (to its first blank, at most 32 chars) after the prefix the gate made: `"m"(easure.py|x)`
        # arrives as m(easure.py, a backtick span joined to the next one as `/usr/bin/sqlite3(rows, ..`, and a quote or
        # a substitution the gate took out may stand between its chars (`("measure.py"|zz)`, "(`python3 -c`," ->
        # `(,`: replay rows 11-14, 11-20)
        lead = c[:m.start()]
        skip = r'''(?:['"]|`[^`]*`|\$\([^()]*\))*'''
        needle = re.compile(skip.join(re.escape(ch) for ch in re.split(r'\s', c[m.start():], maxsplit=1)[0][:32]))
        try:
            for t in dict.fromkeys((cmd, norm)):
                for f in needle.finditer(t):
                    seen += 1
                    if seen > MAX_ZSH_GROUP_GLOBS:
                        raise _ZshUnread
                    pats += [lead + g for g in zsh_group_globs(t, f.start()) if lead + g]
        except _ZshUnread:
            seen = 0
        if not seen:  # the prefix: any name that starts the way the word does
            pats = [re.sub(r'\\(.)', lambda e: glob.escape(e.group(1)), c[:m.start()]) + '*']
        out = []
        for p in pats:  # a relative pattern after a cd the gate does not follow: resolve_word's reading raises
            p = _STAR3_RX.sub('**', os.path.expanduser(p).replace('[^', '[!'))  # r4: zsh's ***/ (see _STAR3_RX)
            for f in brace_forms(p):
                head, _, last = f.rpartition('/')
                out += [f, (head + '/' if head or f.startswith('/') else '') + '.' + last]
        for p in dict.fromkeys(out):
            for b in ([None] if os.path.isabs(p) else bases):
                pat = p if b is None else os.path.join(glob.escape(b), p)
                star_walk_bounded(pat)  # Viktor 49709 L2: a no-match `**` walked the whole tree
                if next(glob.iglob(pat, recursive=True), None):
                    return True
        return False

    def resolve_word(c, zsh=True):
        """Card 00c714ea: a script word as the shell makes it: each word its brace expansion makes, a glob in it
        expanded in each base (resolve_lead_glob). zsh False (card 0196e1ee): a word a pipe feeds a shell is decoded
        text, not a word of the command text the zsh paren is looked up in."""
        if zsh and zsh_paren_may_match(c):
            raise PathUnread(f'a zsh glob group or qualifier in a script word: {c[:40]}')
        found = False
        for f in brace_forms(c):
            r = resolve_lead_glob(f) if _GLOB_CHARS_RX.search(f) and '$' not in f else resolve(f)
            if r is None:
                return None
            found = found or r
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
        # every word, not "the words before the first file": `pushd x && node -r /abs/ok.js m.js` runs m.js too
        # (Viktor 41756 LOW 2); measured, that exception spared 33 of the replay's rows only
        lead = getattr(group, 'lead', ()) if getattr(group, 'expand', False) else ()
        for c in group:
            if (resolve_word(c, getattr(group, 'zsh', True)) if c in lead else resolve(c)) is None:
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
_WRAP_NAME_RX = re.compile(_WRAP_NAME, re.I)  # a wrapper right where a walk ended (xargs env ..., d58d5c30 r3)
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
C_FLAG_RX = re.compile(r'-[A-Za-z]*c[A-Za-z]*')  # any cluster with a c, as SHELL_CODE_FLAG_RX: `bash -cx ./m.sh`
CODE_FRAMES = ('`', '$(', '<(', '>(', '(')


class LexTooBig(Exception):
    """The text is past the lexer's bounds: the caller takes the old path."""


def past_lex_bounds(s, substs):
    """The lexer's bounds (LEX_MAX_SUBSTS, LEX_MAX_WORK units of segments_of) for text s and its substitutions."""
    work = (len(s) + sum(max(0, x['inner'][1] - x['inner'][0]) for x in substs)) * (len(substs) + 1)
    return len(substs) > LEX_MAX_SUBSTS or work > LEX_MAX_WORK


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
        if past_lex_bounds(s, substs):
            raise LexTooBig()
        return full(s, cls, substs)
    mod.segments_of = bounded
    return mod


shell_lex = _load_shell_lex()


# hits() and script_hits() lex the same command: once. Card 39d885ef: not only the last text. stdin_pipelines lexes
# its text for the code positions, pipes_union reads two texts in turn and the payloads are judged again, so a
# one-entry cache lexed the same texts over and over (the fleet replay: 133 -> 1 345 ms, 894 -> 3 945 ms on one
# command, 126 lexer passes). The lexings are only read, never changed (no caller writes into one).
_LEX_CACHE = {}
_LEX_CACHE_MAX = 32


def lex_or_none(cmd):
    """The lexer's view of cmd, or None: not loaded, raised, past the bounds, or a problem (see above)."""
    if shell_lex is None:
        return None
    if cmd in _LEX_CACHE:
        return _LEX_CACHE[cmd]
    try:
        lx = shell_lex.lex(cmd)
    except Exception:  # LexTooBig, or a lexer bug: the old path
        lx = None
    lx = None if lx is None or lx['problems'] else lx
    if len(_LEX_CACHE) >= _LEX_CACHE_MAX:
        _LEX_CACHE.clear()
    _LEX_CACHE[cmd] = lx
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
    only shows the shell's own line structure; a join never hid less.
    Nor where the backslash ends a heredoc's terminator line (class 't'; card 70a5fb2a, Viktor 43324 LELET 3): a quoted
    delimiter may end in a backslash (`curl -d @- <<'J\\'`), its terminator line is `J\\`, and the shell takes that
    line as the end of the body, so the next line is a command; the join glued it onto the terminator and the script
    it ran (`./x.sh`) was not read."""
    out = []
    p = a
    while p < b:
        if view[p] == '\\' and p + 1 < b and view[p + 1] == '\n' and cls[p] not in 'met':
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


_MASK_CACHE = {}


def data_body_pipes_masked(cmd, lx, cwd):
    """_data_body_pipes_masked, once per (cmd, cwd). Card 39d885ef (Viktor 43793 INFO 1): payload_texts, _hits and
    script_hits each masked the same text (with many data heredocs about 3x the time), and the escape-keeping second
    read (pipes_union) would have doubled it again. Every caller passes lex_or_none(cmd) as lx, so (cmd, cwd) is the
    key; at most 32 entries (a hook call judges a handful of texts)."""
    key = (cmd, cwd, lx is None)
    if key not in _MASK_CACHE:
        if len(_MASK_CACHE) >= 32:
            _MASK_CACHE.clear()
        _MASK_CACHE[key] = _data_body_pipes_masked(cmd, lx, cwd)
    return _MASK_CACHE[key]


def _data_body_pipes_masked(cmd, lx, cwd):
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


def _payload_marked(text):
    """text with every quote that opens a payload past PAYLOAD_OPEN's reach (payload_quotes) as a `;`: the script
    rules read that payload as a command; nothing else changes."""
    marks = payload_quotes(text)
    if not marks:
        return text
    chars = list(text)
    for i in marks:
        chars[i] = ';'
    return ''.join(chars)


def decoded_payloads(text):
    """Card af12091a (Viktor 47244 (1)): every payload of text as the shell reads it (payload_texts), and the payloads
    in those, to PAYLOAD_DEPTH levels; each distinct text once. None (the caller blocks) when a level-PAYLOAD_DEPTH
    text still holds a payload, or past MAX_PAYLOADS texts in all (one count for every level), or when payload_texts
    gives up. Breadth first: a text is read once, whatever level it is found at."""
    out, seen, level = [], set(), [text]
    for depth in range(PAYLOAD_DEPTH + 1):
        nxt = []
        for t in level:
            ps = payload_texts(t, subst=True)
            if ps is None:
                return None
            for p in ps:
                if p in seen:
                    continue
                if depth == PAYLOAD_DEPTH or len(seen) == MAX_PAYLOADS:
                    return None
                seen.add(p)
                out.append(p)
                nxt.append(p)
        level = nxt
        if not level:
            break
    return out


def _quote_pattern_word(v):
    """Viktor 49925 L1 (card 0196e1ee): a glob / brace word of a pipeline that is not live, single-quoted for its
    line, so DIRECT_RX reads it as written (a word with a ' in it stays as it is: the quote rule sees that one)."""
    if "'" not in v and (_GLOB_CHARS_RX.search(v) or _BRACE_ALT_RX.search(v)):
        return "'" + v + "'"
    return v


# Viktor 49984 L1b (card 0196e1ee): the commands whose words run nothing; a shell name among them (`grep -c sh <<'X'`)
# does not make their heredoc a shell's (XARGS_DATA's plain readers, and tee, which only copies)
_HD_DATA_CMDS = frozenset({'cat', 'tee', 'grep', 'egrep', 'fgrep', 'wc', 'head', 'tail', 'echo', 'printf', 'true',
                           'false', ':'})
_HD_NEST = frozenset('(){}`')
_HD_MAX_NEXT = 8  # lines a pipeline that a heredoc's line leaves open (`cat <<'X' |`) is followed past its body


def _hd_line_bounds(cmd, a, b):
    """The line around [a, b) (the texts read here are normalised: a backslash-newline is joined already)."""
    le = cmd.find('\n', b)
    return cmd.rfind('\n', 0, a) + 1, len(cmd) if le < 0 else le


def _hd_cuts(cmd, cls, a, b):
    """(separators, pipes) at code positions in cmd[a:b]: ;, &, &&, || (not a redirection's &), and | / |&."""
    seps, pipes, i = [], [], a
    while i < b:
        ch = cmd[i]
        if cls[i] != 'c' or ch not in ';&|':
            i += 1
            continue
        nxt = cmd[i + 1:i + 2]
        if ch == ';':
            seps.append(i)
        elif ch == '&':
            if cmd[i - 1:i] not in ('<', '>') and nxt != '>':
                seps.append(i)
                i += nxt == '&'
        elif nxt == '|':
            seps.append(i)
            i += 1
        elif cmd[i - 1:i] != '>':  # >| is a redirection
            pipes.append(i)
            i += nxt == '&'
        i += 1
    return seps, pipes


def _hd_cmd_reads(part):
    """One command of a heredoc's pipeline reads shell code: a shell name or `source /dev/stdin` in it, and it is
    not one of _HD_DATA_CMDS (its name read as the shell reads it, past env / nohup / VAR=..; not read: kept)."""
    if not GEN_HERE_READER_RX.search(part):
        return False
    cws = _seg_cmds(part, strip=True)
    fw = _feeder_words(cws[0]) if len(cws) == 1 else []
    return not (fw and fw[0] in _HD_DATA_CMDS)


def _quote_line(ln, live):
    """Viktor 49984 L1b: a printf / echo -e output line of a pipeline that is not live, its glob / brace words quoted
    as _quote_pattern_word does a fed word (`printf '%s\\n' ./e{v,x}il.sh | sh` in a data heredoc printed the brace)."""
    return ln if live else ' '.join(_quote_pattern_word(x) for x in ln.split())


def _shell_reads_heredoc(cmd, hd):
    """Card 0196e1ee: a shell reads this heredoc of the lexer's (its body is the shell's code, not data). Was (and is,
    where the line is not plain): its command line has a shell word (shell_heredoc_bodies' test). Viktor 49984 L1b:
    on a plain line (no group, substitution or backtick in it, the lexer reads it) only the heredoc's own pipeline
    counts, between the separators around it, and in it no command of _HD_DATA_CMDS (`grep -c sh <<'X'`, `cat > n
    <<'A'; bash <<'B'`, `cat > n <<'X'; echo hi | bash`: their body is data, bash ran none of it); a pipeline the line
    leaves open after a | (`cat <<'X' |` + body + `X` + `bash`) goes on past the bodies, up to _HD_MAX_NEXT lines
    (past them: read). `source /dev/stdin` and `. /dev/stdin` read it too (they were missed: the body ran unread)."""
    import bisect
    ls, le = _hd_line_bounds(cmd, hd['op'], hd['opEnd'])
    lx = lex_or_none(cmd)
    if lx is None:
        return GEN_HERE_READER_RX.search(cmd[ls:le]) is not None
    # once per line and per pipeline (many heredocs on one line: `cat <<A <<B ..` read the line once, not per heredoc)
    memo = lx.setdefault('_hd_memo', {})
    if (ls, le) not in memo:
        line = cmd[ls:le]
        nest = bool(_HD_NEST.intersection(line))
        memo[(ls, le)] = (nest, GEN_HERE_READER_RX.search(line) is not None,
                          *(([], []) if nest else _hd_cuts(cmd, lx['cls'], ls, le)))
    nest, anywhere, seps, pipes = memo[(ls, le)]
    if nest:
        return anywhere
    cls = lx['cls']
    k = bisect.bisect_left(seps, hd['op'])
    a = (seps[k - 1] if k else ls - 1) + 1
    k = bisect.bisect_left(seps, hd['opEnd'])
    b = seps[k] if k < len(seps) else le
    cuts = pipes[bisect.bisect_left(pipes, a):bisect.bisect_left(pipes, b)]
    going_on = b == le and cuts and not cmd[cuts[-1] + 1:le].replace('\\\n', '').strip(' \t&')
    if not going_on:
        if not anywhere:
            return False
        if ('p', a, b) not in memo:
            memo[('p', a, b)] = any(_hd_cmd_reads(cmd[x + 1:y]) for x, y in zip([a - 1] + cuts, cuts + [b]))
        return memo[('p', a, b)]
    # the line ends in a | : the pipeline goes on after the last body of the line's heredocs
    parts = [cmd[x + 1:y] for x, y in zip([a - 1] + cuts, cuts)]
    ops = lx.get('_hd_ops')
    if ops is None:
        ops = lx['_hd_ops'] = [h['op'] for h in lx['heredocs']]
    at = max(h['end'] for h in lx['heredocs'][bisect.bisect_left(ops, ls):bisect.bisect_left(ops, le)])
    for _ in range(_HD_MAX_NEXT):
        if at >= len(cmd):
            break
        nls, nle = _hd_line_bounds(cmd, at, at)
        nxt = cmd[nls:nle]
        if _HD_NEST.intersection(nxt) or '<<' in nxt:
            return GEN_HERE_READER_RX.search(nxt) is not None or any(_hd_cmd_reads(p) for p in parts)
        nseps, npipes = _hd_cuts(cmd, cls, nls, nle)
        end = min(nseps, default=nle)
        ncuts = [p for p in npipes if p < end]
        if end == nle and ncuts and not cmd[ncuts[-1] + 1:nle].replace('\\\n', '').strip(' \t&'):
            parts += [cmd[x + 1:y] for x, y in zip([nls - 1] + ncuts, ncuts)]
            at = nle + 1
            continue
        parts += [cmd[x + 1:y] for x, y in zip([nls - 1] + ncuts, ncuts + [end])]
        break
    else:
        return True
    return any(_hd_cmd_reads(p) for p in parts)


_DIRECT_RAW_MAX = 64  # card 0196e1ee: _only_in_data_bodies' scans of the command per text (past it: a pattern)


def _direct_code_view(text, cmd):
    """Card 0196e1ee (fleet replay 2): what script_paths' direct-pattern test reads. A text the lexer reads: (its
    classes, the bodies of the heredocs a shell reads, the ends of its <( / >( substitutions). One it does not (a
    payload mark in a `python3 - <<'PY'` body cut it: 2 fleet commands blocked on a JSDoc `/**`): (None, the bodies
    of the command's own heredocs no shell reads, None). Neither lexed: False (every pattern is globbed)."""
    lx = lex_or_none(text)
    if lx is not None:
        return (lx['cls'], [(h['bodyStart'], h['bodyEnd']) for h in lx['heredocs'] if _shell_reads_heredoc(text, h)],
                {s['end'] for s in lx['substs'] if s.get('kind') in ('<(', '>(')})
    rl = lex_or_none(cmd)
    if rl is None:
        return False
    return (None, [(h['bodyStart'], h['bodyEnd']) for h in rl['heredocs'] if h.get('bodyStart') is not None
                   and h.get('bodyEnd') is not None and not _shell_reads_heredoc(cmd, h)], None)


def _occurrences(s, w):
    """Every start of w in s, overlapping ones too."""
    out, i = [], s.find(w)
    while i >= 0:
        out.append(i)
        i = s.find(w, i + 1)
    return out


def _only_in_data_bodies(w, text, cmd, bodies, left):
    """Card 0196e1ee: w stands in cmd, only inside those bodies, and the text has it no more often than they do (an
    occurrence a $NAME made is none of theirs: it stays a pattern). left: scans still allowed (past them: False)."""
    if not bodies or left[0] <= 0:
        return False
    left[0] -= 1
    occ = _occurrences(cmd, w)
    inside = [i for i in occ if any(a <= i and i + len(w) <= b for a, b in bodies)]
    return bool(occ) and len(inside) == len(occ) and len(_occurrences(text, w)) <= len(inside)


def shell_heredoc_bodies(cmd, lx):
    """Card 2917e6b6: the body of each heredoc (the lexer's) whose command line has a shell word in it (STDIN_SHELL_RX,
    as for a here-string: `bash <<'EOF'`, `sudo -u a sh <<EOF`; over-read, a shell elsewhere on the line counts too).
    [] without the lexer's reading (the old path reads the text as before)."""
    if lx is None:
        return []
    out = []
    for hd in lx['heredocs']:
        ls = cmd.rfind('\n', 0, hd['op']) + 1
        le = cmd.find('\n', hd['opEnd'])
        if STDIN_SHELL_RX.search(cmd[ls:len(cmd) if le < 0 else le]):
            out.append(cmd[hd['bodyStart']:hd['bodyEnd']])
    return out


def script_hits(cmd, cwd):
    """Rule names for inline interpreter code and for the files the command runs."""
    found = []
    esc0 = _ESC_TAKEN[0]  # pipes_union: the texts below are made from here on
    if INTERP_RX.search(normalise(cmd)) and literal_hit(cmd):
        found.append('script-inline')
    # the payload a quote opens past PAYLOAD_OPEN's reach: that quote becomes a command boundary (`;`), so the
    # script rules read the payload as a command; nothing else changes
    # blank on the RAW text, normalise after (Viktor 42695 HIGH 1): inside a quoted-delimiter body bash does not join
    # a backslash-newline, so the terminator must be looked for where bash looks; the blanking keeps the length, so
    # normalise() gives the same result on the blanked text
    span = data_heredoc_span(cmd, cwd)
    lx = lex_or_none(cmd)
    _CMD_READ[0] = lx is not None
    _OWN_LEXED[0] = 0
    if lx is None:  # the old path (card fae0712e: fail-closed, today's decision)
        text = normalise(blank_span(cmd, span))
        if '\\\n' in cmd:  # card 70a5fb2a (Viktor): and the text with no backslash-newline joined (only adds)
            split = normalise(re.sub(r'\\+\n', '\n', blank_span(cmd, span)))
            if split != text:
                text += '\n' + split
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
    def _pipe_src():
        masked = data_body_pipes_masked(cmd, lx, cwd) if lx is not None else cmd
        if masked != cmd:  # the same steps as above, on the masked text (same length as cmd)
            pb = blank_span(masked, span)
            for s in lexer_data_spans(cmd, cwd, lx):
                pb = blank_span(pb, s)
            pview, pextras = lexer_view(nonshell_prose_masked(pb, cmd, lx), cmd, lx, cwd)
            return pview + ''.join('\n' + e for e in pextras)
        if lx is not None and _KEEP_ESC[0]:  # card 39d885ef: the view again, with the backslash-letters kept
            kview, kextras = lexer_view(blanked, cmd, lx, cwd)
            return kview + ''.join('\n' + e for e in kextras)
        if lx is None and _KEEP_ESC[0]:  # card 39d885ef: the old path again, with the backslash-letters kept
            return normalise(blank_span(cmd, span))
        return text
    pipe_srcs = []  # the texts the pipelines were read from, before `text` grows below (main's pipe_src)

    def _pipe_src_seen():
        s = _pipe_src()
        pipe_srcs.append(s)
        return s
    pipe_lines, pipe_words = pipes_union(_pipe_src_seen, since=esc0)
    pipe_live = frozenset(_FEED_LIVE_WORDS[0])  # card 0196e1ee: taken now, before another reading resets it
    if _XARGS_UNREAD[0]:  # card 3bf9a741: not "read the first ones": an xargs past the bounds would slip past
        return found + ['xargs-unread']
    if _FEED_UNREAD[0]:  # card 0196e1ee: what a fed text makes by itself is not read
        return found + ['stdin-feed-unread']
    text += ''.join('\n' + ln for ln in pipe_lines)
    # card 946937b7 (Viktor 45626 R1): a here-string a shell reads (`bash <<<'python3 m.py'`, `<<<'./m.sh' sh`) runs
    # its word as a command line: read like a pipeline's lines (stdin_payloads knows which <<< feeds a shell); of
    # both pipe readings (card 39d885ef: a union, it only adds)
    for src in dict.fromkeys(pipe_srcs):
        if '<<<' in src:
            text += ''.join('\n' + w for w, _ in stdin_payloads(src, pipes=False))
    # card c7234bed: what an echo / printf substitution prints where a reader of shell code runs it (generated_lines),
    # from both pipe readings (the escape-kept one decodes printf's \n)
    gen = []
    for src in dict.fromkeys(pipe_srcs):
        g = generated_lines(src)
        if g is None:
            return found + ['payload-unread']
        gen += g
    text += ''.join('\n' + ln for ln in dict.fromkeys(gen))
    # card af12091a (Viktor 45748 K1, 47244 (1)): a payload as the shell reads it (payload_texts: '\'' -> ', \" -> ")
    # is a command text too, and so are the payloads in it: a call whose outer quoting hid its operator
    # (`eval 'python3 -W '\''a;b'\'' m.py'`, `eval 'eval "python3 -W \"a;b\" m.py"'`) reads as code there. They are
    # judged as a text of their own (the files only add: the command's own reading is not changed); past
    # PAYLOAD_DEPTH levels or MAX_PAYLOADS texts in all the gate blocks unread
    decoded = decoded_payloads(text)
    if decoded is None:
        return found + ['payload-unread']
    # card 2917e6b6: the body of a heredoc a shell reads, with a backtick in it, is a text of its own too
    # (decoded_payloads: in the outer text it is quoted text, and its call's words were cut at the backtick:
    # `bash <<'EOF'` + `python3 \x60:\x60 evil.py` ran evil.py, main 01a9dded too)
    decoded += [b for b in shell_heredoc_bodies(cmd, lx) if '`' in b and b not in decoded]
    texts = [_payload_marked(text)] + ([_payload_marked('\n'.join(normalise(p) for p in decoded))] if decoded else [])
    text = texts[0]
    # `sudo -u root python3 m.py` (card 3085a683): the files of the text with the wrapped commands' boundaries are
    # judged TOO, as in hits(): a mark only ever adds a file
    bounds = [wrapper_bounds(t, SCRIPT_WRAP_RX) for t in texts]
    if None in bounds:
        return found + ['wrapper-unread']
    try:
        paths = script_paths(cmd, cwd, text, pipe_words, pipe_live)
        for t in dict.fromkeys(bounds[:1] + texts[1:] + bounds[1:]):
            if t == text:
                continue
            paths +=[p for p in script_paths(cmd, cwd, t) if p not in paths]
    except TooManyArgs as e:  # not "judge the first MAX_ARGS words": a file behind them would slip past (fail-closed)
        return found + [f'script-too-many-args ({e})']
    except PathUnread as e:  # card deede5e4: a script word the gate cannot look up is not "no file" (fail-closed)
        return found + [f'script-path-unread ({e})']
    if len(paths) > MAX_SCRIPTS:  # not "check the first ten": an eleventh file would slip past (fail-closed)
        return found + ['script-too-many']
    budget = script_budget()
    for path in paths:
        if time.monotonic() - T0 > budget:  # not "allow the rest": a timed-out hook would not block either
            return found + ['script-too-slow']
        with open(path, 'rb') as f:
            body = f.read(MAX_SCRIPT_BYTES).decode('utf-8', errors='replace')
        if hits(body, script=True) or literal_hit(body) or (_hn_shell_file(path, body, cmd, pipe_words)
                                                             and hidden_name(body)):
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
