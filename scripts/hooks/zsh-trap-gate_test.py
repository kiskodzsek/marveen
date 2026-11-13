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
    ))


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
