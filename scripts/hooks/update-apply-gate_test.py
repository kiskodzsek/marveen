#!/usr/bin/env python3
"""Tests for update-apply-gate.py (Klodel 39791, card 840231cf). Runs the hook as Claude Code does (PreToolUse JSON
on stdin; exit 0 allow, 2 block). Hermetic: the commands are text only, nothing is executed.
Run: python3 -I scripts/hooks/update-apply-gate_test.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, 'update-apply-gate.py')
GATE = 'python3 -I /Users/klodel/marveen/agents/pulzus/scripts/session-1113/apply_gate.py'


def run(command, tool='Bash', raw=None):
    payload = raw if raw is not None else json.dumps({'tool_name': tool, 'tool_input': {'command': command}})
    p = subprocess.run([sys.executable, '-I', HOOK], input=payload, capture_output=True, text=True, timeout=20,
                       env={'PATH': '/usr/bin:/bin', 'HOOK_ERRLOG_PATH': os.devnull})
    return p.returncode, p.stderr


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def block_direct_apply_the_02_32_shape(_):
    # The incident shape (Pulzus 39790): the apply typed directly, no go-ahead.
    code, err = run('cd /Users/klodel/marveen && python3 -I scripts/marveen-update-safe.py --apply')
    return code == 2 and 'UPDATE-APPLY-KAPU' in err and 'apply_gate.py' in err


@case
def block_apply_forms(_):
    return all(run(c)[0] == 2 for c in (
        'python3 /Users/klodel/marveen/scripts/marveen-update-safe.py --root /Users/klodel/marveen --apply',
        './scripts/marveen-update-safe.py --app',                       # argparse prefix
        'python3 scripts/marveen-update-safe.py --a',
        'python3 scripts/marveen-update-safe.py --apply=1 2>&1 | tee /tmp/x.log',
        'python3 -c "import subprocess; subprocess.run([\'python3\',\'scripts/marveen-update-safe.py\',\'--apply\'])"',
        "python3 - <<'PY'\nimport subprocess\nsubprocess.run(['python3', 'marveen-update-safe.py', '--apply'])\nPY",
        GATE + ' 39800 --check-only && python3 -I scripts/marveen-update-safe.py --apply',  # gate check, then direct
        'timeout 600 python3 marveen-update-safe --apply',
    ))


@case
def allow_the_gate_call(_):
    return run(GATE + ' 39800')[0] == 0 and run(GATE + ' 39800 --check-only')[0] == 0


@case
def allow_check_list_tests_and_unrelated(_):
    return all(run(c)[0] == 0 for c in (
        'python3 -I scripts/marveen-update-safe.py',
        'python3 -I scripts/marveen-update-safe.py --list --root /Users/klodel/marveen',
        'python3 -I scripts/__tests__/marveen-update-safe.test.py',
        'git apply --apply patch.diff',                                  # --apply without the script
        'grep -n "def apply" scripts/marveen-update-safe.py',
        'python3 scripts/marveen-update-safe.py --app-name x',          # not a prefix of --apply
        'cat notes.txt | grep marveen-update-safe; echo done --apply',  # name and flag in different segments
    ))


@case
def other_tools_and_garbage_pass(_):
    return (run('', tool='Write')[0] == 0
            and run(None, raw=json.dumps({'tool_name': 'Write', 'tool_input': {'content': 'marveen-update-safe.py --apply'}}))[0] == 0
            # a non-Bash tool is not judged even when its input has a "command" field (mutation: drop the tool check)
            and run(None, raw=json.dumps({'tool_name': 'Edit', 'tool_input': {'command': 'marveen-update-safe.py --apply'}}))[0] == 0
            and run(None, raw='not json')[0] == 0
            and run(None, raw=json.dumps({'tool_name': 'Bash', 'tool_input': ['x']}))[0] == 0
            and run(None, raw=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 5}}))[0] == 0)


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
