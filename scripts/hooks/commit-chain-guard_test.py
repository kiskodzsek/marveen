#!/usr/bin/env python3
"""Tests for commit-chain-guard.py: python3 -I scripts/hooks/commit-chain-guard_test.py
Nothing is executed: the hook only reads the command text."""
import json
import os
import subprocess
import sys

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'commit-chain-guard.py')

HEREDOC_MSG = '''git commit -m "$(cat <<'EOF'
fix: don't run the lint; npm test stays (it's "quoted")
EOF
)"'''

CASES = [
    # blocked
    ('incident 04:12: test ; amend', 'npx vitest run src/a.test.ts; git commit --amend --no-edit', 2),
    ('incident 11:07: clean gate ; commit', 'node tools/clean-gate.mjs --staged; git commit -F /tmp/m.txt', 2),
    ('newline instead of &&', 'npm test\ngit commit -m x', 2),
    ('|| commits on failure only', 'npm test || git commit -m x', 2),
    ('piped test, status lost', 'npm test 2>&1 | tail -5 && git commit -m x', 2),
    ('piped test with ;', 'python3 -I tools/x_test.py | tail -3; git -C /r commit -m x', 2),
    ('earlier check not chained', 'npm test; npm run lint && git commit -m x', 2),
    ('git add between, ; before it', 'node --test test/; git add -A && git commit -m x', 2),
    ('env prefix and wrapper', 'ROOT=/x sh tools/poc/enter.sh node --test; git commit -m x', 2),
    ('git -c option before commit', 'pytest -q; git -c user.name=x commit -m y', 2),
    ('background test', 'npm test & git commit -m x', 2),
    ('test script by name', 'bash tools/wt-prune-merged_test.sh; git commit -m x', 2),
    ('python -m unittest', 'python3 -m unittest discover; git commit -m x', 2),
    ('pipefail on but ; used', 'set -o pipefail; npm test | tail -3; git commit -m x', 2),
    # 2026-11-16 18:58: set -e does not stop in the Bash tool (zsh eval, measured); a commit passed a red clean gate.
    ('set -e does not make ; safe', 'set -e; npm test; git commit -m x', 2),
    ('set -euo pipefail with newlines', 'set -euo pipefail\nnpm test | tail -5\ngit commit -m x', 2),
    ('the 18:58 incident: set -e, gate on its own line, commit', 'set -e; cd /w; git add -A\nnode tools/clean-gate/cli.ts --staged\nnode tools/clean-gate/cli.ts --msg m.txt\ngit commit -q -F m.txt', 2),
    ('heredoc message after a ; test', 'npm test; ' + HEREDOC_MSG, 2),
    ('gate named by its path, piped', 'node tools/clean-gate/cli.ts --msg m | tail -1 && git commit -F m', 2),
    ('grep on the summary line hides red', 'npx vitest run a.test.ts 2>&1 | grep "Tests " && git commit -m x', 2),
    ('npx tsx running a test file', 'npx tsx test/a.test.ts; git commit -m x', 2),
    ('npm run lint', 'npm run lint; git commit -m x', 2),
    ('heredoc body with an apostrophe, then the incident', "cat > n.txt <<'EOF'\ndon't\nEOF\nnpm test; git commit -m x", 2),
    # 2026-11-20 chain guard (retro 3(b), Klodel 48854): real Codex run and live-swap --apply
    ('incident 11-17 10:24: dry ; real Codex run (launch_detached)',
     'python3 -I tools/codex-review/run_review.py --dry --input i --prompt p --out o --report r1.md; '
     'python3 -I tools/codex-review/launch_detached.py --input i --prompt p --out o --report r2.md', 2),
    ('dry ; real run_review', 'python3 tools/codex-review/run_review.py --dry --report a; '
     'python3 tools/codex-review/run_review.py --report b', 2),
    ('dry, newline, real run', 'python3 -I run_review.py --dry --report a\npython3 -I run_review.py --report b', 2),
    ('dry piped into tail, then real run', 'python3 -I run_review.py --dry --report a | tail -3 && python3 -I run_review.py --report b', 2),
    ('test ; real Codex run', 'npm test; python3 -I tools/codex-review/launch_detached.py --report r', 2),
    ('swap check ; swap apply', 'bash tools/live-swap.sh --live L --new N --live-sha a --new-sha b --tag t; '
     'bash tools/live-swap.sh --live L --new N --live-sha a --new-sha b --tag t --apply', 2),
    ('test ; swap apply', 'python3 -I tools/hooks/wt-lock_test.py; bash tools/live-swap.sh --live L --new N --apply', 2),
    ('test piped ; swap apply direct exec', 'npm test | tail -1 && tools/live-swap.sh --live L --new N --apply', 2),
    ('set -e does not save the swap', 'set -e\nsh tools/full-test_test.sh\nbash tools/live-swap.sh --apply --live L', 2),
    ('swap --apply via env wrapper after ;', 'pytest -q; env FOO=1 bash tools/live-swap.sh --apply --live L', 2),
    # blocked (Viktor 48865: launch_detached.py exits 0 once the child started; its first word is the log)
    ('detached dry && detached real run (D01)',
     'python3 tools/codex-review/launch_detached.py d.log --dry --input i && '
     'python3 tools/codex-review/launch_detached.py l.log --input i', 2),
    ('log named --dry is a real run (D02)',
     'npm test; python3 tools/codex-review/launch_detached.py --dry --input i --prompt p --out o --report r', 2),
    ('dry ; detached run with a log named --dry (D03)',
     'python3 tools/codex-review/run_review.py --dry --input i; python3 tools/codex-review/launch_detached.py --dry --input i', 2),
    ('abbreviated --dr is a dry gate (W04)',
     'python3 tools/codex-review/run_review.py --dr --input i; python3 tools/codex-review/run_review.py --input i', 2),
    # allowed
    ('detached dry alone (log first, then --dry)', 'python3 tools/codex-review/launch_detached.py d.log --dry --input i', 0),
    ('abbreviated --dr && real run', 'python3 -I run_review.py --dr --input i && python3 -I run_review.py --input i', 0),
    ('dry && real Codex run', 'python3 -I run_review.py --dry --report a && python3 -I launch_detached.py --report b', 0),
    ('real Codex run alone', 'python3 -I tools/codex-review/launch_detached.py --input i --report r', 0),
    ('dry alone', 'python3 -I tools/codex-review/run_review.py --dry --report r', 0),
    ('swap check && swap apply', 'bash tools/live-swap.sh --live L --tag t && bash tools/live-swap.sh --live L --tag t --apply', 0),
    ('swap apply alone, then a test after it', 'bash tools/live-swap.sh --live L --apply; python3 -I tools/x_test.py', 0),
    ('two swap applies in a row (no check before)', 'bash tools/live-swap.sh --apply --live A; bash tools/live-swap.sh --apply --live B', 0),
    ('cp then swap apply', 'cp a b; chmod 444 b; bash tools/live-swap.sh --apply --live L', 0),
    ('grep naming live-swap and a test', 'npm test; grep -n live-swap README.md', 0),
    ('editor arg named run_review.py', 'npm test; python3 -I - tools/codex-review/run_review.py <<\'PY\'\nprint(1)\nPY', 0),
    ('heredoc body naming test ; swap', "cat > n <<'EOF'\nnpm test; bash live-swap.sh --apply\nEOF\necho ok", 0),
    # allowed (before 11-20)
    ('heredoc body naming a test is data', "cat > n.txt <<'EOF'\nnpm test\nEOF\ngit commit -m x", 0),
    ('explicit exit on red in a { } group', 'npm test || { echo red; exit 1; }; git commit -m x', 0),
    ('test file edited by an inline script', "python3 -I - src/a.test.ts <<'PY'\nimport sys\nPY\ngit commit -m x", 0),
    ('python -c with a test file argument', 'python3 -c "print(1)" tools/x_test.py; git commit -m x', 0),
    ('npm install is not a check', 'npm install; git commit -m x', 0),
    ('plain script is not a check', 'python3 tools/build.py; git commit -m x', 0),
    ('&& all the way', 'npm test && git add -A && git commit -m x', 0),
    ('pipefail with newlines between pipe and commit', 'set -o pipefail\nnpm test | tail -5\ngit commit -m x', 2),
    ('pipefail and &&', 'set -o pipefail; npm test | tail -5 && git commit -m x', 0),
    ('commit alone', 'git commit -m "npm test; all green"', 0),
    ('heredoc message naming tests', HEREDOC_MSG, 0),
    ('test after the commit', 'git commit -m x; npm test', 0),
    ('test file as git argument', 'git add src/a.test.ts; git commit -m x', 0),
    ('echo naming a test', 'echo "npm test"; git commit -m x', 0),
    ('no commit at all', 'npm test 2>&1 | tail -5; git status --short', 0),
    ('git log mentions commit', 'npm test; git log --oneline -3 # last commit', 0),
    ('redirect is not a background &', 'npm test >out.txt 2>&1 && git commit -m x', 0),
    ('control flow is left alone', 'if npm test; then git commit -m x; fi', 0),
    ('unbalanced quote is left alone', 'npm test; git commit -m "x', 0),
    ('quoted ; in a message', "npm test && git commit -m 'a; b'", 0),
    # Viktor 48870 KÖVETŐ 1-2 (card b3ae9523): a commit behind a wrapper, a package-manager option with a value
    ('F1 env VAR=x before the commit', 'npm test; env GIT_AUTHOR_NAME=x git commit -m y', 2),
    ('F1 command git commit', 'npm test; command git commit -m y', 2),
    ('F1 time git commit', 'pytest -q; time git commit -m y', 2),
    ('F1 nice -n 10 git commit', 'pytest -q; nice -n 10 git commit -m y', 2),
    ('F1 VAR=x env -u NAME git commit', 'npm test; A=1 env -u B git commit -m y', 2),
    ('F2 npm --prefix web test', 'npm --prefix web test; git commit -m x', 2),
    ('F2 npm -w web test, piped', 'npm -w web test | tail -3 && git commit -m x', 2),
    ('F2 pnpm --filter web test', 'pnpm --filter web test; git commit -m x', 2),
    ('F2 pnpm -C web run lint', 'pnpm -C web run lint; git commit -m x', 2),
    ('F2 yarn --cwd web test', 'yarn --cwd web test; git commit -m x', 2),
    ('F2 nice -n 10 npm test', 'nice -n 10 npm test; git commit -m x', 2),
    ('F1 wrapped commit after && passes', 'npm test && env A=1 git commit -m y', 0),
    ('F2 --prefix test after && passes', 'npm --prefix web test && git commit -m x', 0),
    ('F2 pnpm -w is no value: install is not a test', 'pnpm -w install; git commit -m x', 0),
    ('F2 --prefix=web one word, not a test', 'npm --prefix=web install; git commit -m x', 0),
    ('F1 env alone is not a commit', 'npm test; env | grep -c PATH', 0),
    # Viktor, chain-fleet 1st round (Kernel 48922): wrappers with a value or a positional, per wrapper
    ('V1 timeout 60 git commit', 'npm test; timeout 60 git commit -m y', 2),
    ('V1 nohup git commit', 'npm test; nohup git commit -m y', 2),
    ('V1 exec -a NAME git commit', 'npm test; exec -a x git commit -m y', 2),
    ('V1 caffeinate -t 5 git commit', 'npm test; caffeinate -t 5 git commit -m y', 2),
    ('V1 env -S string git commit', "npm test; env -S 'git commit -m y'", 2),
    ('V1 timeout 300 npm test', 'timeout 300 npm test; git commit -m y', 2),
    ('V1 timeout -k 5 300 npm test', 'timeout -k 5 300 npm test; git commit -m y', 2),
    ('V1 stdbuf -oL npm test, piped', 'stdbuf -oL npm test | cat && git commit -m y', 2),
    ('V1 timeout before a real Codex run', 'npm test; timeout 600 python3 tools/codex-review/run_review.py x', 2),
    ('V2 npm -C web test', 'npm -C web test; git commit -m x', 2),
    ('V2 yarn workspace web test', 'yarn workspace web test; git commit -m x', 2),
    ('V1 timeout commit after && passes', 'npm test && timeout 60 git commit -m y', 0),
    ('V1 timeout test && commit passes', 'timeout 300 npm test && git commit -m y', 0),
    ('V1 timeout Codex after && passes', 'npm test && timeout 600 python3 tools/codex-review/run_review.py x', 0),
    ('V2 yarn workspace build is not a test', 'yarn workspace web build; git commit -m x', 0),
    ('V1 env -S with no value is no crash', 'env -S; git commit -m y', 0),
    # 2nd round, from the independent probe (Viktor, chain-fleet b3ae9523)
    ('V3 env -P altpath git commit', 'npm test; env -P /usr/bin git commit -m x', 2),
    ('V3 zsh noglob git commit', 'npm test; noglob git commit -m x', 2),
    ('V3 eval git commit', 'npm test; eval git commit -m x', 2),
    ('V3 eval with a quoted commit', "npm test; eval 'git commit -m x'", 2),
    ('V3 npm --loglevel silent test', 'npm --loglevel silent test; git commit -m x', 2),
    ('V3 pnpm lint shorthand', 'pnpm lint; git commit -m x', 2),
    ('V3 yarn lint shorthand', 'yarn lint; git commit -m x', 2),
    ('V3 pnpm vitest bin', 'pnpm vitest run; git commit -m x', 2),
    ('V3 bun --cwd web test', 'bun --cwd web test; git commit -m x', 2),
    ('V3 bunx vitest', 'bunx vitest run; git commit -m x', 2),
    ('V3 deno test', 'deno test; git commit -m x', 2),
    ('V3 command -v vitest is a lookup, not a run', 'command -v vitest; git commit -m x', 0),
    ('V3 command -V eslint is a lookup, not a run', 'command -V eslint; git commit -m x', 0),
    ('V3 pnpm install is not a test', 'pnpm install; git commit -m x', 0),
    ('V3 yarn build is not a test', 'yarn build; git commit -m x', 0),
    ('V3 deno run app.ts is not a test', 'deno run app.ts; git commit -m x', 0),
    ('V3 eval echo is not a commit', 'npm test; eval echo hi', 0),
    ('V3 bun app.ts is not a test', 'bun app.ts; git commit -m x', 0),
]

# Card ba07fdfe (Klodel 49041): a send piped without pipefail, '&&' after it. Marker KULDES-LANC-OR when blocked.
SEND_CASES = [
    # blocked: the 463 shape and its relatives
    ('463 case: send-and-close | tail && send-stamped',
     'bash tools/send-and-close.sh --head /w abc 463 work/m.txt kernel 2>&1 | tail -2 && bash tools/send-stamped.sh klodel work/k.txt', 2),
    ('kernel-msg heredoc | tail && next step',
     "tools/kernel-msg.sh klodel - <<'MSG' 2>&1 | tail -1 && printf ok\nszoveg; 1\nMSG", 2),
    ('card-comment | tail && card-move',
     "bash tools/card-comment.sh abc - < c.txt 2>&1 | tail -2 && bash tools/card-move.sh abc done", 2),
    ('agent-msg | grep && echo', 'bash scripts/agent-msg.sh kernel klodel "x" | grep -q OK && echo sent', 2),
    ('send behind env and cd ;', 'cd /x; env A=1 bash tools/msg-close.sh "r" 1 | tail -1 && echo done', 2),
    ('send piped twice', 'bash scripts/agent-msg.sh a b c 2>&1 | tee /tmp/o | tail -1 && echo x', 2),
    ('pipefail set AFTER the send pipeline', 'bash scripts/agent-msg.sh a b c | tail -1 && set -o pipefail && echo x', 2),
    # round 1 (Viktor ba07fdfe): each of these passed on 4ab58b30
    ('B47 bash -o pipefail is the inner shell only', 'bash -o pipefail scripts/agent-msg.sh a b c | tail -2 && echo ok', 2),
    ('B47 bash -O extglob', 'bash -O extglob scripts/agent-msg.sh a b c | tail -2 && echo ok', 2),
    ('B33 set +o pipefail switches it off', 'set -o pipefail; set +o pipefail; bash scripts/agent-msg.sh a b c | tail && echo x', 2),
    ('B34 set -- -o pipefail is positional', 'set -- -o pipefail; bash scripts/agent-msg.sh a b c | tail && echo x', 2),
    ('B48 send piped into a send', 'bash scripts/agent-msg.sh a b c | bash tools/kernel-msg.sh klodel - && echo x', 2),
    ('unsetopt pipefail', 'setopt pipefail; unsetopt pipefail; bash scripts/agent-msg.sh a b c | tail -1 && echo x', 2),
    ('setopt nopipefail', 'set -o pipefail; setopt no_pipefail; bash scripts/agent-msg.sh a b c | tail -1 && echo x', 2),
    ('R15 zsh set -o nopipefail is off', 'set -o pipefail; set -o nopipefail; bash scripts/agent-msg.sh a b c | tail -1 && echo x', 2),
    ('R16 zsh set +o PIPE_FAIL is off', 'set -o pipefail; set +o PIPE_FAIL; bash scripts/agent-msg.sh a b c | tail -1 && echo x', 2),
    ('R17 zsh set -o no_pipe_fail is off', 'set -o pipefail; set -o no_pipe_fail; bash scripts/agent-msg.sh a b c | tail -1 && echo x', 2),
    ('R24 bash --rcfile takes a value', 'bash --rcfile /dev/null scripts/agent-msg.sh a b c | tail -1 && echo x', 2),
    # allowed
    ('pipefail before the piped send', 'set -o pipefail; bash tools/send-and-close.sh x | tail -2 && bash tools/send-stamped.sh k f', 0),
    ('set -euo pipefail before', 'set -euo pipefail\nbash scripts/agent-msg.sh a b c | tail -1 && echo x', 0),
    ('no pipe: send && next', 'bash tools/kernel-msg.sh klodel - < m.txt && bash tools/msg-close.sh "r" 1', 0),
    ('piped send, nothing after', 'bash scripts/agent-msg.sh a b c 2>&1 | tail -1', 0),
    ('piped send, ; after (not &&)', 'bash scripts/agent-msg.sh a b c | tail -1; echo x', 0),
    ('send last in the pipe', 'cat m.txt | bash tools/kernel-msg.sh klodel - && echo x', 0),
    ('send script only an argument', 'ls -l scripts/agent-msg.sh | tail -1 && echo x', 0),
    ('grep in a send script', 'grep -n x tools/card-comment.sh | head -3 && echo y', 0),
    ('send name inside quotes only', 'echo "agent-msg.sh a | tail" | wc -l && echo x', 0),
    ('control flow fails open', 'for f in a b; do bash scripts/agent-msg.sh a b $f | tail -1 && echo x; done', 0),
    ('zsh setopt pipefail (INFO V04)', 'setopt pipefail; bash scripts/agent-msg.sh a b c | tail -1 && echo x', 0),
    ('zsh setopt PIPE_FAIL (INFO V05)', 'setopt PIPE_FAIL; bash scripts/agent-msg.sh a b c | tail -1 && echo x', 0),
    ('set +o then -o pipefail: on', 'set +o pipefail; set -o pipefail; bash scripts/agent-msg.sh a b c | tail -1 && echo x', 0),
    ('set -eo pipefail combined', 'set -eo pipefail; bash scripts/agent-msg.sh a b c | tail -1 && echo x', 0),
    ('bash -o pipefail, send last in the pipe', 'cat m | bash -o pipefail scripts/agent-msg.sh a b - && echo x', 0),
    ('known limit: send behind a variable', 'X=tools/send-stamped.sh; bash $X klodel f | tail -1 && echo next', 0),
    ('known limit: send inside bash -c', "bash -c 'bash scripts/agent-msg.sh a b c' | tail -1 && echo x", 0),
]


def run(cmd):
    p = subprocess.run([sys.executable, '-I', HOOK], input=json.dumps(
        {'tool_name': 'Bash', 'tool_input': {'command': cmd}, 'cwd': '/'}), capture_output=True, text=True)
    return p.returncode, p.stderr


def main():
    ok = 0
    for name, cmd, want in CASES:
        rc, err = run(cmd)
        good = rc == want and (want == 0 or 'COMMIT-LANC-OR' in err)
        ok += good
        print(('PASS ' if good else 'FAIL ') + name + ('' if good else f' (rc {rc}: {err.strip()[:120]})'))
    for name, cmd, want in SEND_CASES:
        rc, err = run(cmd)
        good = rc == want and (want == 0 or 'KULDES-LANC-OR' in err)
        ok += good
        print(('PASS ' if good else 'FAIL ') + 'send: ' + name + ('' if good else f' (rc {rc}: {err.strip()[:120]})'))
    extra = [
        ('malformed stdin allows', 'not json'),
        ('non-Bash tool allows', json.dumps({'tool_name': 'Write', 'tool_input': {'command': 'npm test; git commit'}})),
    ]
    for name, stdin in extra:
        rc = subprocess.run([sys.executable, '-I', HOOK], input=stdin, capture_output=True, text=True).returncode
        ok += rc == 0
        print(('PASS ' if rc == 0 else 'FAIL ') + name)
    total = len(CASES) + len(SEND_CASES) + len(extra)
    print(f'{ok}/{total} passed')
    return 0 if ok == total else 1


if __name__ == '__main__':
    sys.exit(main())
