#!/usr/bin/env python3
"""Tests for zsh-trap-gate.py (retro 2026-11-13 R6, card cf287c2c). Negative cases first: every trap the hibanapló
recorded, as it was typed. The contract cases run the hook as Claude Code does (PreToolUse JSON on stdin; exit 0
allow, 2 block, never 1); the bulk cases call findings() directly. Hermetic: the commands are text only, nothing
is executed, the error log goes to /dev/null.
Run: python3 -I scripts/hooks/zsh-trap-gate_test.py
"""
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, 'zsh-trap-gate.py')
_spec = importlib.util.spec_from_file_location('zsh_trap_gate', HOOK)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

ZSH = {'SHELL': '/bin/zsh'}
BASH = {'SHELL': '/bin/bash'}
SP = '/private/tmp/claude-501/x/scratchpad/r6'


def run(command, tool='Bash', raw=None, env=None):
    payload = raw if raw is not None else json.dumps({'tool_name': tool, 'tool_input': {'command': command}})
    e = {'PATH': '/usr/bin:/bin', 'HOOK_ERRLOG_PATH': os.devnull, 'SHELL': '/bin/zsh'}
    e.update(env or {})
    p = subprocess.run([sys.executable, '-I', HOOK], input=payload, capture_output=True, text=True, timeout=20,
                       env=e)
    return p.returncode, p.stderr


def kinds(command, env=ZSH):
    return [m.split(' ', 1)[0] for m in gate.findings(command, env)]


def blocks(command, kind, env=ZSH):
    got = gate.findings(command, env)
    ok = any(m.startswith(kind) for m in got)
    if not ok:
        print(f'  expected {kind} block: {command!r} -> {[m[:60] for m in got]}')
    return ok


def passes(command, env=ZSH):
    got = gate.findings(command, env)
    if got:
        print(f'  expected pass: {command!r} -> {[m[:90] for m in got]}')
    return not got


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


# ---- incidents, as typed ---------------------------------------------------------------------------------------

@case
def incident_modifier_git_show_1112(_):
    # hibanapló 2026-11-12 07:18 (Dave, #1286): git show "$T:src/lib/..." -> "bad substitution"
    return all(blocks(c, 'ZSH-CSAPDA (modifier)') for c in (
        'T=origin/main; git show "$T:src/lib/articles.ts" | head',
        'R=/Users/klodel/marveen; git -C x show $R:apps/web/package.json',
        'git show "$BASE:apps/x.md" > /tmp/x',
    ))


@case
def incident_wordsplit_worktree_loop_1112(_):
    # hibanapló 2026-11-12 16:43 (Dave): the worktree loop
    return blocks('for spec in "wt-a fix/a" "wt-b fix/b"; do set -- $spec; '
                  'bash scripts/worktree-add.sh $1 $2 origin/main; done', 'ZSH-CSAPDA (szóbontás)')


@case
def incident_command_variable_1113(_):
    # hibanapló 2026-11-13 17:39 (Dave) and Pulzus 18:12: X="cmd args"; $X ...
    return all(blocks(c, 'ZSH-CSAPDA (változó mint parancs)') for c in (
        'HJ="bash /Users/klodel/marveen/scripts/heavy-job.sh --kill-below 12"; $HJ --name r4f -- python3 qa.py',
        'G="bash agents/pulzus/bin/gh.sh"; $G pr view 253 --json state',
        'G="gh api"\n"$G" repos/x/y',
        'if true; then X="node scripts/a.mjs"; $X --dry; fi',
    ))


@case
def incident_echo_equals_1113(_):
    # hibanapló 2026-11-13 18:03 (Viktor): echo ===X -> "==X not found", the greps after it did not run
    return all(blocks(c, 'ZSH-CSAPDA (=-kibontás)') for c in (
        'echo ===SINK; grep -rn "dangerouslySetInnerHTML" src | head',
        'echo ===',
        'echo ====X',
        'echo =foo',
        'cd /x && echo ===FEJLEC=== && grep -n csp next.config.ts',
        'printf "%s\\n" a; echo ======',
        '[ "$a" == b ] && echo y',
        'test "$a" == b',
        'x==foo',
        'echo "$(echo ===)"',
        'echo `echo ===`',
    ))


@case
def incident_rm_variable_1113(_):
    # hibanapló 2026-11-13 18:38 (Viktor): rm -rf on the $S path
    return all(blocks(c, 'RM-VALTOZO-KAPU') for c in (
        'S=' + SP + '; rm -rf $S/t2 && mkdir -p $S/t2',
        'rm -rf $S',
        'rm -rf "$S"',
        'rm -rf $S/*',
        'rm -rf "$S"/*',
        'rm -rf "${S}/x"',
        'rm -r -f $DIR',
        'rm -fr "$OUT/shots"',
        'rm -R $X',
        'rm --recursive --force $X',
        'cd /tmp && /bin/rm -rf $X',
        'sudo rm -rf $X',
        'nohup rm -rf -- $X &',
        'env A=1 rm -rf "$HOME/.cache/x"',
        'echo a; [ -d x ] && rm -rf $TMPDIR/x',
        'X="$(mktemp -d)"; trap "rm -rf $X" EXIT; rm -rf $X',
        '\\rm -rf $S',                                       # Viktor 41294 LOW 2
        'echo a | xargs rm -rf $S',                             # Kernel 41291
        'find . -name x | xargs -I {} -n 1 rm -rf $S/{}',
        'ls | xargs -0 rm -r "$D"',
        # Viktor 41322 INFO 5/6: every value-taking xargs option, short and long
        'ls | xargs -P 4 rm -rf $S', 'ls | xargs -a f rm -rf $S', 'ls | xargs -L 1 rm -rf $S',
        'ls | xargs -s 100 rm -rf $S', 'ls | xargs -E x rm -rf $S', 'ls | xargs -d x rm -rf $S',
        'ls | xargs -J % rm -rf $S', 'ls | xargs -R 2 rm -rf $S',
        'ls | xargs --max-args 1 rm -rf $S', 'ls | xargs --max-procs 2 rm -rf $S', 'ls | xargs --arg-file f rm -rf $S',
        'ls | xargs -S 255 rm -rf $S',                         # Viktor 41371 INFO 2 (BSD replsize)
    ))



@case
def modifier_letters_measured(_):
    # Viktor 41294 LOW 1 / INFO 3: every letter zsh 5.9 treats as a modifier (W included), gs and g&, blocks;
    # a non-modifier letter, an escaped $ and $$ (the PID) pass
    mods = all(blocks(f'git show "$B:{m}x/y"', 'ZSH-CSAPDA (modifier)') for m in
               ['a', 'A', 'c', 'e', 'h', 'l', 'P', 'q', 'Q', 'r', 's', 't', 'u', 'W', 'gs', 'g&'])
    return mods and all(passes(c) for c in ('git show "$B:docs/x"', 'echo "\\$B:s/x"', 'echo "$$B:s/x"'))


# ---- more negative forms ---------------------------------------------------------------------------------------

@case
def block_wordsplit_forms(_):
    return all(blocks(c, 'ZSH-CSAPDA (szóbontás)') for c in (
        'L="a b c"; for x in $L; do echo $x; done',
        'F=$(ls); for f in $F; do echo $f; done',
        'for f in ${FILES}; do echo $f; done',              # not set here: an env string
        'for f in a $LIST b; do :; done',
        'read -r line; set -- $line',
        'while read -r l; do for w in $l; do echo $w; done; done < f',
        'export L="a b"; for x in $L; do :; done',
    ))


@case
def block_modifier_forms(_):
    return all(blocks(c, 'ZSH-CSAPDA (modifier)') for c in (
        'scp f "$HOST:tmp/x"',
        'echo $USER:admin',
        'python3 - <<EOF\nprint("$T:src/x")\nEOF',           # unquoted heredoc: zsh expands it
        'echo "$1:h"',
    ))


# ---- must pass ------------------------------------------------------------------------------------------------

@case
def pass_wordsplit_safe_forms(_):
    return all(passes(c) for c in (
        'L=(a b c); for x in $L; do echo $x; done',
        'for x in ${=L}; do echo $x; done',
        'for f in $(ls); do echo $f; done',
        'for f in "$@"; do echo $f; done',
        'for f in $@; do echo $f; done',
        'for f in $argv; do :; done',
        'typeset -a L; L=(a b); for x in $L; do :; done',
        'read -rA L; for x in $L; do :; done',
        'for x in "$L"; do :; done',                          # quoted: one word in every shell, as written
        'for f in *.png; do echo "$f"; done',
        'for f in a b c; do :; done',
        'L=one; for x in $L; do :; done',                     # a one-word literal
        'set -- a b; echo $1',
        'set -e; set -o pipefail',
        "bash -c 'for x in $L; do set -- $x; done'",          # single-quoted: bash runs it
        "python3 - <<'PY'\nfor x in L: print(x)\nPY",
        'for (( i=0; i<3; i++ )); do echo $i; done',
    ))


@case
def pass_command_variable_safe_forms(_):
    return all(passes(c) for c in (
        'X=(bash heavy-job.sh --kill-below 12); $X --name a -- true',
        'PY=python3; $PY -V',
        'PY=$(command -v python3); $PY -V',
        '$EDITOR file.txt',                                   # not set here: the env value, may be one word
        'X="a b"; echo $X',                                   # not in command position
        'X="a b"; echo "$X"',
        'f() { echo hi; }; f',
    ))


@case
def pass_modifier_safe_forms(_):
    return all(passes(c) for c in (
        'git show "${T}:src/lib/articles.ts"',
        'git show "${R}:apps/web/package.json" | head',
        'echo "$HOST:$PORT" "$H:mm" "$IP:22" "$A:-x"',
        'echo ${F:h} ${F:t} ${0:A:h}',
        "echo '$T:src/x'",
        "cat <<'EOF'\n$T:src/x\nEOF",
        'echo \\$T:src/x',
        'echo $PATH:/usr/local/bin',
        'git show "$B:docs/x.md"',                            # :d is no modifier (measured): zsh leaves it
        '# git show $T:src/x\necho ok',
    ))


@case
def pass_equals_safe_forms(_):
    return all(passes(c) for c in (
        'echo "===" "=== X ==="',
        "echo '===X'",
        'echo \\=foo',
        'echo =',
        '[ "$a" = b ] && echo y',
        'test "$a" = b',
        '[[ "$a" == b ]] && echo y',
        '[[ $a == b && $c == d ]] || echo n',
        'if [[ $x =~ ^a ]]; then echo y; fi',
        'git log --format=%H -1 a=b --opt=val',
        'cat =(echo procsub)',
        'cut -d= -f2 file',
        'awk -F= \'{print $2}\' f',
        'echo "--- X"',
        '[[ a == b ]]',
        "python3 -c \"print('===')\"",
        "cat <<EOF\n=== X ===\nEOF",
        "cat <<'EOF'\n===\nEOF",
        'A=b B=c env | grep A',
        'sed -n "/^===/p" f',
        '(( a == b )) && echo y',
        'echo "a==b" a"==="',
    ))


@case
def printf_unquoted_equals_blocks(_):
    return blocks('printf "%s\\n" ===', 'ZSH-CSAPDA (=-kibontás)')


@case
def pass_rm_safe_forms(_):
    return all(passes(c) for c in (
        'rm -rf ' + SP + '/x',
        'rm -rf -- "${S:?}"',
        'rm -rf "${S:?}/sub"',
        'rm -rf ${S:?}/x',
        'rm -rf "${S?}"/x',
        'rm -rf /Users/klodel/marveen/agents/dave/repos/x/$NAME',   # literal absolute prefix
        'rm -rf ./build dist',
        'rm -f $S',                                                # not recursive
        'rm "$S"/a.txt',
        'find $S -name "*.tmp" -exec rm -rf {} +',
        'echo rm -rf $S',                                          # not an rm call
        "bash -c 'rm -rf $S'",                                     # single-quoted: not judged
        'git rm -r --cached $X',
        "cat <<EOF\nrm -rf $S\nEOF",
    ))


@case
def bash_shell_skips_zsh_checks_but_not_rm(_):
    zsh_only = ('echo ===', 'L="a b"; for x in $L; do :; done', 'git show "$T:src/x"', 'X="a b"; $X')
    return (all(passes(c, env=BASH) for c in zsh_only)
            and blocks('rm -rf $S', 'RM-VALTOZO-KAPU', env=BASH)
            and blocks('echo ===', 'ZSH-CSAPDA', env={'CLAUDE_CODE_SHELL': '/bin/zsh', 'SHELL': '/bin/bash'})
            and blocks('echo ===', 'ZSH-CSAPDA', env={}))     # unknown shell = zsh (the fleet's shell)


@case
def message_names_the_fix(_):
    m = gate.findings('echo ===X', ZSH)[0]
    r = gate.findings('rm -rf $S', ZSH)[0]
    w = gate.findings('L="a b"; for x in $L; do :; done', ZSH)[0]
    d = gate.findings('git show "$T:src/x"', ZSH)[0]
    c = gate.findings('X="a b"; $X', ZSH)[0]
    return ('echo "=== X ==="' in m and '==X not found' in m and '"${S:?}/alut"' in r and '${=L}' in w
            and '"${VAR}:út"' in d and 'X=(' in c)


@case
def several_traps_one_message_each(_):
    k = kinds('echo ===; rm -rf $S; git show "$T:src/x"')
    return len(k) == 3


# ---- the hook contract -----------------------------------------------------------------------------------------

@case
def contract_block_is_exit_2_with_reason(_):
    code, err = run('echo ===X; grep -n x f')
    return code == 2 and 'ZSH-CSAPDA' in err and '==X not found' in err


@case
def contract_allow_is_exit_0_silent(_):
    code, err = run('echo "=== X ==="; grep -n x f')
    return code == 0 and err == ''


@case
def contract_other_tools_and_garbage_pass(_):
    return (run(None, raw=json.dumps({'tool_name': 'Write', 'tool_input': {'content': 'echo ==='}}))[0] == 0
            and run(None, raw=json.dumps({'tool_name': 'Edit', 'tool_input': {'command': 'echo ==='}}))[0] == 0
            and run(None, raw='not json')[0] == 0
            and run(None, raw='[]')[0] == 0
            and run(None, raw=json.dumps({'tool_name': 'Bash', 'tool_input': ['x']}))[0] == 0
            and run(None, raw=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 5}}))[0] == 0
            and run(None, raw=json.dumps({'tool_name': 'Bash', 'tool_input': {}}))[0] == 0)


@case
def contract_internal_error_fails_open_and_logs(_):
    # Force a crash inside findings(): the parser gets a value that is not a string-like command.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        log = os.path.join(d, 'hook-errors.log')
        code = subprocess.run(
            [sys.executable, '-I', '-c',
             'import runpy,sys; sys.argv=[%r]; g=runpy.run_path(%r, run_name="x"); '
             'g["findings"]=None; import io; sys.stdin=io.StringIO(%r); '
             'f=g["main"]; f.__globals__["findings"]=lambda c: 1/0; sys.exit(f())'
             % (HOOK, HOOK, json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'echo ==='}}))],
            capture_output=True, text=True, timeout=20,
            env={'PATH': '/usr/bin:/bin', 'HOOK_ERRLOG_PATH': log}).returncode
        logged = os.path.exists(log) and 'zsh-trap-gate' in open(log, encoding='utf-8').read()
    return code == 0 and logged


@case
def unterminated_input_does_not_hang_or_crash(_):
    for c in ('echo "abc', "echo 'abc", 'echo $(ls', 'echo ${x', 'cat <<EOF\nno end', 'echo `ls', 'a=(b c',
              '[[ a == b', '((', ')))', '$', '\\', '<<', 'for', 'rm -rf', 'echo $((1+'):
        gate.findings(c, ZSH)
    return True


# Card 3b05ae69 (the gate-timing probe): 1-2 KB of repeated nesting units ran into Python's recursion limit, an
# internal error that allowed silently. Past MAX_DEPTH nested sequences the gate now blocks with MSG_DEEP.
DEEP = [('$(', 500), ('(a=', 500), ('"$(', 340), ('<(', 1000), ('=(', 500), ('$( ', 500),
        # match_paren and read_dq call each other, past parse_seq (redos-probe fuzz, work/zshtrap-1122/rec.log)
        ('"$((', 500), ('x"$((|', 500), ('a=$"$(((', 500)]


@case
def deep_nesting_blocks_instead_of_crashing(_):
    ok = all(blocks(u * k, 'ZSH-CSAPDA (mélység)') for u, k in DEEP)
    ok = ok and blocks('$(' * 500, 'ZSH-CSAPDA (mélység)', env=BASH)   # the rm check runs in any shell
    rc, err = run('$(' * 500, env={'HOOK_ERRLOG_PATH': os.devnull})
    return ok and rc == 2 and 'mélység' in err


@case
def nesting_up_to_the_cap_is_parsed(_):
    # the top-level sequence counts as one level: 63 nested $( reach MAX_DEPTH, 64 go past it. Literal counts, not
    # gate.MAX_DEPTH: a lowered cap (6 would still pass the 5-level command) must fail here (mutation M2)
    real = 'echo $(echo $(echo $(echo $(echo a))))'
    return (passes('$(' * 63) and blocks('$(' * 64, 'ZSH-CSAPDA (mélység)')
            and passes(real) and blocks('for f in $(echo $(echo x)) $V; do :; done', 'ZSH-CSAPDA (szóbontás)'))


@case
def backtick_glued_to_a_word_closes_its_sequence(_):
    # before: the closing backtick glued to a word opened a new nested sequence (500 x 'a`' crashed), and the
    # rest of the command was read inside it, so the word-split trap after it was missed
    return (passes('a`' * 500) and passes('echo a`date`b')
            and blocks('for f in `ls`x $V; do :; done', 'ZSH-CSAPDA (szóbontás)')
            and blocks('echo a`b`c; for f in x $V; do :; done', 'ZSH-CSAPDA (szóbontás)'))


# ---- round 2 (Viktor 50179, independent probe indep12) ----------------------------------------------------------

@case
def closed_prefix_value_options_cmdvar_after_prefix_eqsplit_and_procsub_redirect(_):
    # closed in round 2: sudo -u / nice -n values, a variable as the command after nohup / command, $=V in rm,
    # and a process substitution after a redirect no longer eats the next command's first word
    rm, cv, sp, eq = 'RM-VALTOZO-KAPU', 'ZSH-CSAPDA (változó mint parancs)', 'ZSH-CSAPDA (szóbontás)', 'ZSH-CSAPDA (='
    return (blocks(r'sudo -u root rm -rf $S', rm) and blocks(r'nice -n 10 rm -rf $S/tmp', rm)
            and blocks(r'env -u HOME -C /tmp rm -rf $S', rm) and blocks(r'rm -rf $=D/cache', rm)
            and blocks(r'rm -rf $~D', rm)
            and blocks(r'HJ="bash heavy-job.sh --fast"; nohup $HJ > job.log 2>&1 &', cv)
            and blocks(r'G="git -C repo status"; command $G', cv)
            and blocks(r'cat < <(ls); rm -rf $S', rm) and blocks(r'cat < <(ls); for x in $FILES; do :; done', sp)
            and blocks(r'sort < <(ls) ; echo ===X', eq) and blocks('x > >(cat)\nrm -rf $S', rm)
            and passes(r'G="git x"; command -v $G') and passes(r'sudo -u root ls $S')
            and passes(r'nice -n 10 rm -rf "${S:?}/tmp"') and passes(r'echo $=D')
            and passes(r'HJ=(a b); nohup $HJ') and passes(r'cat < <(ls); echo ok')
            and passes(r'diff <(ls a) <(ls b); rm -rf "${S:?}"'))


@case
def prefix_follow_ups_exec_a_env_split_sudo_h_command_lookup(_):
    # e6a0f476 (Viktor 50227 round 2 LOW/INFO; main lets the first group through, overblocks the last group)
    rm, cv = 'RM-VALTOZO-KAPU', 'ZSH-CSAPDA (változó mint parancs)'
    nested = 'env -S "env -S ' + "'rm -rf $S'" + '"'
    return (
        # LOW 1: exec -a NAME takes a value
        blocks(r'exec -a nm rm -rf $S', rm) and blocks(r'exec -a nm rm -rf $S/*', rm) and passes(r'exec -a nm ls')
        # LOW 2: env -S / --split-string: its one word is the command line env runs
        and blocks(r'env -S "rm -rf $S"', rm) and blocks(r"env -S 'rm -rf $S'", rm)
        and blocks(r'env --split-string="rm -rf $S"', rm) and blocks(r'env -u A -S "rm -rf $S"', rm)
        and blocks(r'env -Srm\ -rf\ $S', rm) and blocks(nested, rm)
        and passes(r'env -S "ls -la"') and passes(r'env -S "rm -rf ${S:?}"')
        # INFO 2: sudo -h is --help or -h HOST; both ways are looked at
        and blocks(r'sudo -h rm -rf $S', rm) and blocks(r'sudo -h host rm -rf $S', rm) and passes(r'sudo -h')
        and passes(r'sudo -h host ls $S')
        and blocks(r'G="git x"; sudo -h $G', cv) and passes(r'G="git x"; sudo -u root ls $G')
        # INFO 1: a -v / -V in a cluster (-pv, -vp) or after -p only looks the name up
        and passes(r'G="git x"; command -pv $G') and passes(r'G="git x"; command -vp $G')
        and passes(r'G="git x"; command -p -v $G') and passes(r'command -pv rm -rf $S')
        and blocks(r'G="git x"; command -p $G', cv) and blocks(r'command rm -rf $S', rm)
        and blocks(r'command -p rm -rf $S', rm))


@case
def prefix_round2_split_rest_clusters_quoted_options_dash_and_set_after_prefix(_):
    # e6a0f476 round 2 (Viktor 50424 L1-L6; old, main lets every BLOCK row through). zsh -f with an rm stub first on
    # PATH runs rm in each BLOCK row (agents/kernel/work/ztf-r2-1123/oracle.txt; env -P /bin runs the real /bin/rm
    # there, S a missing temp path), except the sudo rows (no sudo run; getopt clustering as the man page reads).
    rm, sp, cv = 'RM-VALTOZO-KAPU', 'ZSH-CSAPDA (szóbontás)', 'ZSH-CSAPDA (változó mint parancs)'
    r = ' rm -rf $S'
    return (
        # L1: env -S takes one word, env appends the words after it
        blocks('env -S' + r, rm) and blocks("env -S 'rm -rf' $S", rm) and blocks('env -S env -S' + r, rm)
        and blocks('echo $(env -S' + r + ')', rm) and blocks("env -S 'rm #x' -rf $S", rm)
        and passes("env -S 'echo #' rm -rf $S") and passes("env -S 'echo rm -rf' $S")
        # L2: a cluster whose last letter takes a value takes the next word; a glued value does not
        and blocks('exec -cla x' + r, rm) and blocks('exec -lca x' + r, rm) and blocks('true && exec -ca x' + r, rm)
        and blocks('true | exec -cla x' + r, rm) and blocks('true\nexec -cla x' + r, rm)
        and blocks('time noglob exec -cla x' + r, rm) and blocks('exec -cax' + r, rm)
        and blocks('env -vS' + r, rm) and blocks('env -vu FOO' + r, rm) and blocks('env -vC /tmp' + r, rm)
        and blocks('env -vP /bin' + r, rm) and blocks('sudo -iu root' + r, rm) and blocks('sudo -Eu root' + r, rm)
        and blocks('HJ="rm -rf"; exec -cla x $HJ /tmp/x', cv) and passes('exec -a rm echo -rf $S')
        # L3: env -P altpath
        and blocks('env -P /bin' + r, rm)
        # L4: a quoted option or assignment word is still one
        and blocks('exec "-a" x' + r, rm) and blocks('env "-Srm -rf $S"', rm) and blocks('env "-S" "rm -rf $S"', rm)
        and blocks('env "FOO=a b"' + r, rm)
        # L5: zsh's - precommand
        and blocks('true; -' + r, rm)
        # L6: set -- after a prefix word splits nothing either
        and blocks("V='a b'; noglob set -- $V", sp) and blocks("V='a b'; builtin set -- $V", sp)
        and passes("V='a b'; noglob set -- ${=V}"))


@case
def env_split_long_chains_stay_linear(_):
    # e6a0f476 round 2: only the first split option of a command recurses (the split text holds the words after it),
    # so a 150 KB env -S chain is a few parses, not one per env word; an exec -cla chain is one pass
    import time
    for cmd in ('time ' + 'env -S env ' * (150 * 1024 // 11) + 'rm -rf $S',
                'exec -cla x ' * (150 * 1024 // 12) + 'rm -rf $S'):
        t0 = time.monotonic()
        got = gate.findings(cmd, ZSH)
        dt = time.monotonic() - t0
        if not got or dt > 2.0:
            print(f'  long chain {cmd[:20]!r}: {len(got)} finding(s), {dt:.2f} s')
            return False
    return True


@case
def env_split_nesting_past_the_depth_bound_blocks(_):
    # e6a0f476: env -S inside env -S is read up to MAX_SPLIT_DEPTH levels; past it the gate blocks (fail-closed)
    cmd = 'rm -rf $S'
    for _i in range(gate.MAX_SPLIT_DEPTH + 1):
        cmd = 'env -S ' + json.dumps(cmd)
    m = gate.findings(cmd, ZSH)
    return bool(m) and m[0].startswith('ZSH-CSAPDA (mélység)')


class _W:
    def __init__(self, t):
        self.t = t

    def plain(self):
        return self.t


class _CountingWords(list):
    """A word list that counts every word handed out, by index or inside a slice copy."""
    touched = 0

    def __getitem__(self, k):
        got = list.__getitem__(self, k)
        type(self).touched += len(got) if isinstance(k, slice) else 1
        return got

    def __iter__(self):
        for i in range(len(self)):
            yield self[i]


@case
def command_lookup_only_is_linear_on_a_command_chain(_):
    # e6a0f476 ReDoS round: words[j + 1:] copied the rest of the command for every `command` word, so
    # "command -p " x 8000 took 0.255 s against 0.034 s before (x3.7 per doubling, redos-probe --repeat). Counted,
    # not timed: n `command -p` pairs may touch a few words each, not the whole tail.
    n = 4000
    words = _CountingWords([_W(t) for _ in range(n) for t in ('command', '-p')] + [_W('rm')])
    _CountingWords.touched = 0
    hits = [j for j in range(len(words) - 1) if gate.command_lookup_only(words, j)]
    return not hits and _CountingWords.touched <= 10 * n


@case
def deep_message_counts_parser_levels(_):
    # Viktor 50179 INFO: a quoted $( ) counts two levels, so the message says parser levels
    m = gate.findings('echo ' + '"$(' * 40, ZSH)
    return bool(m) and m[0].startswith('ZSH-CSAPDA (mélység)') and 'két szintnek' in m[0]


# KNOWN-LIMIT rows: each pins today's behaviour of a documented Known limit (the docstring names the label);
# the input is the indep12 probe's, verbatim. A later fix turns its row red on purpose.
KNOWN_LIMIT_INPUTS = [
    ('bt-escaped-inner-rm', 'x=`echo \\`rm -rf $S\\``'),
    ('dq-bt-escaped-inner-rm', 'x="`echo \\`rm -rf $S/build\\``"'),
    ('bt-escaped-inner-for', 'y=`echo \\`for f in $FILES; do echo $f; done\\``'),
    ('arith-cmdsub-rm', 'echo $(( $(rm -rf $S; echo 1) + 1 ))'),
    ('dq-arith-cmdsub-rm', 'echo "$(( $(rm -rf $S/tmp; echo 1) ))"'),
    ('dparen-cmd-arith-cmdsub-rm', '(( n = $(rm -rf $S; echo 3) )) && echo $n'),
    ('brace-default-cmdsub-rm', 'echo ${OUT:-$(rm -rf $S)}'),
    ('dq-brace-default-bt-rm', 'echo "${OUT:-`rm -rf $S`}"'),
    ('brace-default-cmdsub-setsplit', 'echo ${R:-$(set -- $SPEC; echo $1)}'),
    ('dq-brace-default-cmdsub-eq', 'echo "${R:-$(echo === done)}"'),
    ('dollar-dparen-fallback-rm', 'echo $((rm -rf $S); echo done)'),
    ('dparen-start-subshell-rm', '((rm -rf $S) ; echo done)'),
    ('dq-case-subst-rm', 'x="$(case a in a) echo a;; esac; rm -rf $S)"'),
    ('bt-heredoc-tail-rm', 'x=`cat <<EOF\nhi\nEOF`\nrm -rf $S'),
    ('dollar-bracket-shift-tail-rm', 'echo $[1<<2]\nrm -rf $S'),
]
DATA_LINE = 'line 000000 some ordinary data text, no traps here\n'
KNOWN_LIMIT_INPUTS += [
    ('time-data-heredoc-300k-tail-rm', "cat > out.txt <<'EOF'\n" + DATA_LINE * 6000 + 'EOF\nrm -rf $S'),
    ('time-1mb-tail-rm', "cat > out.txt <<'EOF'\n" + DATA_LINE * 20000 + 'EOF\nrm -rf $S'),
]


@case
def known_limit_rows_pin_todays_allow(_):
    ok = True
    for label, cmd in KNOWN_LIMIT_INPUTS:
        if gate.findings(cmd, ZSH):
            print(f'  KNOWN-LIMIT {label}: blocks now (the documented limit changed)')
            ok = False
    return ok and len(KNOWN_LIMIT_INPUTS) == 17


def main():
    failed = 0
    for fn in CASES:
        try:
            ok = fn(None)
        except Exception as e:  # a crash is a failure, with its reason
            ok = False
            print(f'ERROR {fn.__name__}: {e!r}')
        print(('PASS ' if ok else 'FAIL ') + fn.__name__)
        failed += not ok
    print(f'{len(CASES) - failed}/{len(CASES)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
