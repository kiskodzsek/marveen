#!/usr/bin/env python3
"""Tests for tmux-kill-gate.py (card ad7edaec). python3 -I scripts/hooks/tmux-kill-gate_test.py; exit 0 = all pass.

decide() on a table of commands, and the hook protocol end to end (stdin JSON -> exit 2 + stderr / exit 0) in a
child process with TMUX pointing at the live socket shape and TMUX_TMPDIR elsewhere: the 2026-11-15 16:45 case.
"""
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, 'tmux-kill-gate.py')
spec = importlib.util.spec_from_file_location('tmux_kill_gate', GATE)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

UID = os.getuid()
BLOCK = [
    # the incident shape and the plain forms
    'tmux kill-server',
    'TMUX_TMPDIR=/private/tmp/iso tmux kill-server',
    'env TMUX_TMPDIR=/x tmux kill-server',
    'tmux kill-ser',
    'tmux -L default kill-server',
    f'tmux -S /private/tmp/tmux-{UID}/default kill-server',
    f'tmux -S /tmp/tmux-{UID}/default kill-server',
    'tmux -S "$SOCK" kill-server',
    '/opt/homebrew/bin/tmux kill-server',
    '\\tmux kill-server',
    't""mux kill-server',
    'tmux new-session -d -s x \\; kill-server',
    'tmux ls; tmux kill-server',
    'true && tmux kill-server',
    'echo "$(tmux kill-server)"',
    'echo `tmux kill-server`',
    'bash -c "tmux kill-server"',
    "sh -lc 'tmux kill-server'",
    'zsh -c "env -u FOO tmux kill-server"',
    'eval "tmux kill-server"',
    "bash <<'EOF'\ntmux kill-server\nEOF",
    'nohup tmux kill-server &',
    'timeout 5 tmux kill-server',
    'sudo -u klodel tmux kill-server',
    'echo x | xargs tmux kill-server',
    'tmux -c "tmux kill-server"',
    'tmux send-keys -t agent-dave "tmux kill-server" Enter',
    'T=tmux; $T kill-server',
    'pkill tmux',
    'pkill -f "tmux: server"',
    'killall tmux',
    'kill $(pgrep tmux)',
    # sessions on the live server
    'tmux kill-session -t agent-dave',
    'tmux kill-session -t =agent-dave',
    'tmux kill-session -t agent',
    'tmux kill-session -t a',
    'tmux kill-session -t klodel-channels',
    'tmux kill-session -t klodel',
    'tmux kill-session',
    'tmux kill-session -a -t scratch',
    'tmux kill-session -t "agent-*"',
    'tmux kill-session -t \'$3\'',
    'tmux kill-session -t "$S"',
    'tmux kill-window -t agent-dave:0',
    'tmux killw -t agent-dave',
    'tmux kill-window',
    'tmux kill-pane -t agent-kernel:0.0',
    'tmux killp',
    'tmux kill-pane -t %3',
    'tmux unlink-window -k -t agent-dave:1',
    'tmux respawn-pane -k -t agent-dave',
    'tmux kill-session -tagent-dave',
    # a socket name in a variable: only a LITERAL assignment earlier in the same command resolves it
    'tmux -L $L kill-server',
    'L=default; tmux -L $L kill-server',
    'L=probe; L=$X; tmux -L $L kill-server',
    'L=probe tmux -L $L kill-server',  # a prefix assignment is applied AFTER $L is expanded
    'L=probe; tmux kill-session -t $T',
    # interpreter code: the 2026-11-15 16:45 incident shape (Viktor's restart probe)
    ("cat > $S/restart_probe.mts <<'EOF'\nimport { execFileSync } from 'node:child_process'\n"
     "execFileSync('tmux', ['kill-server'])\nEOF\nTMUX_TMPDIR=/private/tmp/iso node --import tsx $S/restart_probe.mts"),
    "node <<'EOF'\nrequire('child_process').execSync('tmux kill-session -t agent-dave')\nEOF",
    'python3 -c "import subprocess; subprocess.run([\'tmux\', \'kill-server\'])"',
    "node -e \"require('child_process').execFileSync('tmux', ['killp'])\"",
    "python3 - <<'PY'\nimport subprocess\nsubprocess.run('cd /x && tmux kill-server', shell=True)\nPY",
    "perl -e 'system(\"tmux kill-session -t agent-dave\")'",
    # Viktor 43177 INFO 1 (mutant M3 survived): a glob target without the agent- prefix
    "tmux kill-session -t '*'",
    "tmux kill-session -t '*-viktor'",
    # Viktor 43177 LOW 1/2: -S wins over -L; an -L label with a path part
    f'tmux -S /private/tmp/tmux-{UID}/default -L probe kill-server',
    f'tmux -L ../tmux-{UID}/default kill-server',
    'tmux -L ./default kill-server',
    # Viktor 43177 MEDIUM 2: a window/pane target without a session part resolves in the caller's own session
    'tmux kill-window -t 0',
    'tmux kill-window -t 1',
    'tmux kill-window -t claude',
    'tmux kill-pane -t 0',
    'tmux kill-pane -t 1',
    'tmux kill-pane -t .0',
    'tmux unlink-window -k -t 0',
    'tmux respawn-pane -k -t 0',
    'tmux respawn-window -k -t claude',
    # Viktor 43177 LOW 3: shell text on stdin
    "echo 'tmux kill-server' | sh",
    "echo 'tmux kill-server' | bash",
    "bash <<< 'tmux kill-server'",
    "printf 'tmux kill-server\\n' | sh -s",
    'echo tmux kill-server | xargs -I{} sh -c {}',
    "echo 'tmux kill-session -t agent-dave' | zsh",
    # Viktor 43177 LOW 4: wrappers and runners
    'setsid tmux kill-server',
    'arch -arm64 tmux kill-server',
    'sandbox-exec -f /x/prof.sb tmux kill-server',
    'find . -maxdepth 0 -exec tmux kill-server \\;',
    'exec -a name tmux kill-server',
    "env -S 'tmux kill-server'",
    # Viktor 43177 LOW 5: the subcommand in a literal variable
    'x=kill-server; tmux $x',
    # Viktor 43205 LOW 1: an xargs/find placeholder as the target, and xargs tmux fed the subcommand
    'echo agent-kernel | xargs -I{} tmux kill-session -t {}',
    "tmux ls -F '#S' | grep agent | xargs -I {} tmux kill-session -t {}",
    'find . -exec tmux kill-session -t {} \\;',
    'echo agent-x | xargs -J X tmux kill-session -t X',
    'echo agent-x | xargs -i tmux kill-session -t {}',
    'echo kill-server | xargs tmux',
    'echo agent-dave | xargs tmux kill-session -t',
    # Viktor 43205 LOW 2: a producer's heredoc piped into a shell
    "cat <<'EOF' | sh\ntmux kill-server\nEOF",
    "cat <<EOF | bash\ntmux kill-session -t agent-dave\nEOF",
    # Viktor 43205 LOW 3: a redirection before the command word
    '>/dev/null tmux kill-server',
    '2>/dev/null tmux kill-server',
    '2> /tmp/err tmux kill-server',
    '&>/dev/null tmux kill-server',
    '2>&1 tmux kill-server',
    '< in.txt tmux kill-server',
    '<<< x tmux kill-server',
    '<<<x tmux kill-server',
    '<<EOF tmux kill-server\nhello\nEOF',
    '<< EOF tmux kill-server\nhello\nEOF',
    # own mutation round (mutate2.py): a custom xargs -i string, the -I string as the subcommand, a function body
    # without a kill-* word (the run-time command-word fallback does not cover it)
    'echo agent-x | xargs -iQ tmux kill-session -t Q',
    'echo kill-server | xargs -I{} tmux {}',
    'f() { pkill tmux; }; f',
    # Viktor 43205 LOW 4: one isolated call in the body must not clear a second, live one
    ('python3 -c "import subprocess; subprocess.run([\'tmux\',\'-L\',\'x\',\'new-session\']); '
     'subprocess.run([\'tmux\',\'kill-server\'])"'),
    # Viktor 43205 INFO 1: function definitions, glued/split wrapper values, script, screen, tmux-command arguments
    'function f { tmux kill-server; }; f',
    'f() { tmux kill-server; }; f',
    'f () { tmux kill-server; }; f',
    "env -S'tmux kill-server'",
    "env --split-string='tmux kill-server'",
    'stdbuf -o 0 tmux kill-server',
    'stdbuf -oL tmux kill-server',
    'script -q /dev/null tmux kill-server',
    'screen -dmS x tmux kill-server',
    'watch -d tmux kill-server',
    'tmux kill-server\\;',
    'tmux new -d -s x \\; kill-server\\;',
    'tmux if-shell true kill-server',
    'tmux if true "kill-session -t agent-dave"',
    'tmux confirm-before kill-server',
    'tmux bind-key X kill-server',
    'tmux set-hook -g session-created kill-server',
    # Viktor 43205 INFO 2: every klodel-* session is the fleet's
    'tmux kill-session -t klodel-worker',
    'tmux kill-session -t klodel-worker-fast',
    'tmux respawn-pane -k -t klodel-worker',
    # Viktor 43205 mutation survivors N15, N40: find -execdir/-ok/-okdir, @ and % ids
    'find . -execdir tmux kill-server {} +',
    'find . -ok tmux kill-server \\;',
    'find . -okdir tmux kill-server \\;',
    'tmux kill-session -t @1',
    'tmux kill-session -t %1',
    # Viktor 43301 LOW 1: an outer xargs replace string inside a nested sh -c / eval payload
    "echo agent-dave | xargs -I X sh -c 'tmux kill-session -t X'",
    'echo agent-dave | xargs -I NAME bash -c "tmux kill-session -t NAME"',
    "echo agent-dave | xargs -iQ zsh -c 'tmux kill-session -t Q'",
    'echo agent-dave | xargs -I X eval tmux kill-session -t X',
    "echo agent-dave | xargs -I X sh -c 'tmux kill-session -t X;'",
    "echo agent-dave | xargs -I X sh -c 'echo a; tmux kill-session -t X'",
    "echo agent-dave | xargs -I X sh -c 'echo a | xargs tmux ls; tmux kill-session -t X'",
    # Viktor 43301 LOW 2: a quoted redirection target before the command word
    '>"/tmp/x" tmux kill-server',
    '2>"/tmp/e" tmux kill-session -t agent-dave',
    ">'/tmp/x' tmux kill-server",
    ">/tmp/'x y' tmux kill-server",
    'cd /tmp && 2>"/tmp/e" tmux kill-server',
    'echo x; >"/tmp/x" tmux kill-server',
    "bash -c '>\"/tmp/x\" tmux kill-server'",
    # Viktor 43301 LOW 3: xargs tmux with its input from a redirection, not a pipe
    'xargs -n1 tmux kill-session -t < names.txt',
    'xargs tmux kill-session -t <<< work',
    "xargs -n1 tmux kill-session -t < <(tmux ls -F '#S')",
    # Viktor 43301 test gaps (M03, M12, M25, M27; work/tkg3-cases4.txt)
    'xargs -I X tmux kill-session -t X < names.txt',
    'xargs -I XX tmux kill-session -t pre-XX < names.txt',
    'xargs -J QQ tmux kill-session -t QQ',
    'script -q -t 0 /dev/null tmux kill-server',
    'script -t 0 /dev/null tmux kill-server',
    'script -T x /dev/null tmux kill-server',
    "python3 - <<'E'\nrun(['tmux','-L','x','kill-server']); run(['tmux','kill-server'])\nE",
    "python3 - <<'E'\nsubprocess.run(['tmux','-L','iso','kill-session','-t','x'])\nsubprocess.run(['tmux','kill-server'])\nE",
    ("python3 - <<'E'\nrun(['tmux','-L','i','ls'])\nrun(['tmux','has-session','-t','" + 'a' * 60 +
     "','kill-server'])\nE"),
    # Viktor 43301 INFO, modelled now: {fd}> redirection, coproc, env -S inside a cluster, script -qt cluster
    '{fd}>/tmp/f tmux kill-server',
    'coproc tmux kill-server',
    'coproc P { tmux kill-server; }',
    "env -iS 'tmux kill-server'",
    "env -vS'tmux kill-server'",
    'script -qt 0 /dev/null tmux kill-server',
    # macOS script -F is a flag (man script), so /tmp/p is the FILE and tmux kill-server runs (#326 let it pass)
    'script -F /tmp/p tmux kill-server',
    'script -qF /tmp/p tmux kill-server',
]
# Viktor 43177 MEDIUM 1: compound-command keywords, for three kill forms each
for _k in ('tmux kill-server', 'tmux kill-session -t agent-x', 'pkill tmux'):
    BLOCK += [
        f'if true; then {_k}; fi',
        f'if {_k}; then :; fi',
        f'for i in 1; do {_k}; done',
        f'while true; do {_k}; done',
        f'until false; do {_k}; done',
        f'{{ {_k}; }}',
        f'! {_k}',
        f'if false; then :; else {_k}; fi',
        f'case x in a) {_k};; esac',
        f'case x in a) ls;; b|c) {_k};; esac',
    ]
ALLOW = [
    'tmux -L kernelprobe kill-server',
    'tmux -Lkernelprobe kill-server',
    'tmux -S /private/tmp/claude-501/iso.sock kill-server',
    'TMUX= tmux -L iso kill-server',
    'tmux -L iso kill-session -t agent-x',
    'tmux kill-session -t scratch-1115',
    'tmux kill-session -t =scratch',
    'tmux kill-window -t scratch:1',
    'tmux capture-pane -p -t agent-dave',
    'tmux send-keys -t agent-dave "hello" Enter',
    'tmux ls',
    'tmux list-sessions -F "#{session_name}"',
    'tmux display -p "#{socket_path}"',
    'tmux respawn-pane -t agent-dave',
    'tmux unlink-window -t agent-dave:1',
    'tmux kill-s',  # ambiguous: tmux refuses it itself
    'echo "tmux kill-server"',
    'git commit -m "gate against tmux kill-server"',
    'grep -n kill-server scripts/hooks/tmux-kill-gate.py',
    "cat > notes.md <<'EOF'\ntmux kill-server\nEOF",
    "bash tools/kernel-msg.sh klodel - <<'MSG'\nNever run tmux kill-server.\nMSG",
    'kill 12345',
    'pkill -f node',
    'ls -la',
    'L=probe; tmux -L $L kill-server',
    'L=probe && tmux -L "$L" kill-server',
    'L=probe; tmux -L ${L} kill-server',
    'S=/private/tmp/claude-501/iso.sock; tmux -S $S kill-server',
    'T=scratch; tmux kill-session -t $T',
    # interpreter code with an explicit socket, and the same code only written to a file (no interpreter runs it)
    ("cat > $S/restart_probe.mts <<'EOF'\nimport { execFileSync } from 'node:child_process'\n"
     "execFileSync('tmux', ['-L', 'iso', 'kill-server'])\nEOF\nnode --import tsx $S/restart_probe.mts"),
    "cat > notes.md <<'EOF'\nexecFileSync('tmux', ['kill-server'])\nEOF",
    "python3 -c \"import subprocess; subprocess.run(['tmux', 'ls'])\"",
    'python3 -I scripts/hooks/tmux-kill-gate_test.py',
    # prose about the incident written by an interpreter (E1 2026-11-15 16:10, a hibanapló line): not code
    ("python3 -I - <<'PY'\nline = '- 2026-11-15 | Viktor | a próba végén tmux kill-server futott, minden session leállt'\n"
     "open('/tmp/x.md', 'a').write(line)\nPY"),
    # Viktor 43177: -S decides over -L (the iso socket), a window target WITH a non-agent session part
    'tmux -S /private/tmp/iso/sock -L default kill-server',
    'tmux kill-window -t scratch:2',
    'tmux kill-pane -t scratch:1.0',
    'if true; then tmux ls; fi',
    'for s in a b; do tmux capture-pane -p -t agent-$s; done',
    'case x in a) ls;; esac',
    'echo hello | sh',
    'echo tmux kill-server',
    'bash tools/x.sh < notes.txt',
    'find . -name "*.py" -exec grep -l tmux {} \\;',
    'setsid tmux -L iso kill-server',
    "env -S 'tmux ls'",
    # Viktor 43205 follow-up: the new readings keep the isolated and harmless forms open
    'echo scratch | xargs -I{} tmux -L iso kill-session -t {}',
    'echo a | xargs -0 tmux display -p',
    "cat <<'EOF' | sh\ntmux ls\nEOF",
    "cat <<'EOF' | sh\ntmux -L iso kill-server\nEOF",
    '>/dev/null tmux ls',
    '2>/dev/null tmux -L iso kill-server',
    ('python3 -c "import subprocess; subprocess.run([\'tmux\',\'-L\',\'x\',\'kill-server\']); '
     'subprocess.run([\'tmux\',\'ls\'])"'),
    'function f { tmux ls; }; f',
    'screen -dmS x tmux -L iso kill-server',
    'stdbuf -oL tmux ls',
    'watch -d tmux ls',
    'tmux kill-session -t scratch\\;',
    'tmux if-shell true "display hi"',
    'tmux -L iso if-shell true kill-server',
    'tmux bind-key X display hi',
    'env ' * 30 + 'tmux ls',
    "bash <<< 'tmux ls'",
    '<<< x tmux ls',
    # an xargs replace string belongs to its own segment only
    'ls | xargs -I s echo s; tmux kill-session -t scratch',
    # Viktor 43301 round: the isolated and harmless forms stay open
    "echo scratch | xargs -I X sh -c 'tmux -L iso kill-session -t X'",
    'xargs tmux ls < names.txt',
    'xargs -n1 tmux -L iso kill-session -t < names.txt',
    '>"/tmp/x" tmux ls',
    "python3 - <<'E'\nrun(['tmux','-L','iso','ls'])\nk = 'kill-server'\nE",
    'coproc tmux ls',
    "env -iS 'tmux ls'",
]

bad = 0
for c in BLOCK:
    r = g.decide(c)
    if not r:
        bad += 1
        print(f'FAIL (allowed, should block): {c!r}')
for c in ALLOW:
    r = g.decide(c)
    if r:
        bad += 1
        print(f'FAIL (blocked, should allow): {c!r} -> {r}')
print(f'decide: {len(BLOCK)} block + {len(ALLOW)} allow cases, {bad} failed')

# Viktor 43205 mutation survivors N48, N49: past the text limit and past the nesting limit -> block
_long = 'tmux ls ' + 'x' * 210_000
if g.decide(_long) != ['command too long to read']:
    bad += 1
    print('FAIL limits: a 210 000 character command naming tmux is not blocked as too long')
import shlex  # noqa: E402
_nest = 'tmux ls'
for _ in range(8):
    _nest = 'sh -c ' + shlex.quote(_nest)
if 'nesting too deep to read' not in g.decide(_nest):
    bad += 1
    print('FAIL limits: 8 nested sh -c levels are not blocked')
# Viktor 43205 INFO 1: more nested wrappers than the loop reads raise (main() turns that into a block when the
# command names tmux or kill)
try:
    g.decide('env ' * 70 + 'tmux kill-server')
    bad += 1
    print('FAIL limits: 70 nested env wrappers did not raise')
except RuntimeError:
    pass
print('limits: done')

# Viktor 43177 INFO 1 (mutant M16 survived): an internal error blocks when the command mentions tmux or kill, and
# allows otherwise. In process: decide() is made to raise, main() reads the hook JSON from a replaced stdin.
import io  # noqa: E402
import signal  # noqa: E402


def _boom(_cmd):
    raise RuntimeError('synthetic')


_real_decide, _real_stdin, _real_stderr = g.decide, sys.stdin, sys.stderr
# _fake: decide() raises (Viktor 43177 INFO 1); otherwise the real decide past the wrapper limit (Viktor 43205 INFO 1):
# tmux or kill named -> 2, not named -> 0.
try:
    for _cmd, _want, _fake in (('tmux kill-server', 2, True), ('kill 1234', 2, True), ('ls -la', 0, True),
                               ('env ' * 70 + 'tmux kill-server', 2, False), ('env ' * 70 + 'ls', 0, False)):
        g.decide = _boom if _fake else _real_decide
        sys.stdin = io.StringIO(json.dumps({'tool_name': 'Bash', 'tool_input': {'command': _cmd}}))
        sys.stderr = io.StringIO()
        _orig_log = g.log_deny
        g.log_deny = lambda *a, **k: None  # keep the real store/ clean
        try:
            _rc = g.main()
        finally:
            g.log_deny = _orig_log
            signal.setitimer(signal.ITIMER_REAL, 0)
        if _rc != _want:
            bad += 1
            _real_stderr.write(f'FAIL exception path: {_cmd[:60]!r} -> rc {_rc}, want {_want}\n')
finally:
    g.decide, sys.stdin, sys.stderr = _real_decide, _real_stdin, _real_stderr
print('exception path: done')


def hook(cmd, env):
    p = subprocess.run([sys.executable, '-I', GATE], input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd},
                       'cwd': '/nonexistent'}), capture_output=True, text=True, env=env, timeout=30)
    return p.returncode, p.stderr


# The card's negative case: TMUX = the live socket shape, TMUX_TMPDIR = somewhere else -> BLOCK.
env = dict(os.environ, TMUX=f'/private/tmp/tmux-{UID}/default,98216,0', TMUX_TMPDIR='/private/tmp/somewhere-else')
# The deny log goes to the checkout's store/; point HOME-independent: the gate derives it from its own path, so a
# test run appends a line there. Keep it out of the real store: run against a copy of the gate in a temp tree.
import shutil, tempfile, atexit  # noqa: E401
base = os.path.join(os.path.expanduser('~'), '.cache', 'tmux-kill-gate-test')
os.makedirs(base, exist_ok=True)
tree = tempfile.mkdtemp(prefix='t-', dir=base)
atexit.register(shutil.rmtree, tree, True)
os.makedirs(os.path.join(tree, 'scripts', 'hooks'))
os.makedirs(os.path.join(tree, 'scripts', 'lib'))
shutil.copy(GATE, os.path.join(tree, 'scripts', 'hooks', 'tmux-kill-gate.py'))
shutil.copy(os.path.join(os.path.dirname(HERE), 'lib', 'shell_lex.py'), os.path.join(tree, 'scripts', 'lib', 'shell_lex.py'))
GATE = os.path.join(tree, 'scripts', 'hooks', 'tmux-kill-gate.py')

rc, err = hook('TMUX_TMPDIR=/private/tmp/somewhere-else tmux kill-server', env)
if rc != 2 or 'TMUX-KAPU' not in err:
    bad += 1
    print(f'FAIL hook: incident shape not blocked (rc {rc}) {err!r}')
rc, err = hook('tmux -L kernelprobe kill-server', env)
if rc != 0:
    bad += 1
    print(f'FAIL hook: isolated -L blocked (rc {rc}) {err!r}')
rc, err = hook('ls', env)
if rc != 0:
    bad += 1
    print(f'FAIL hook: plain ls blocked (rc {rc})')
logf = os.path.join(tree, 'store', 'tmux-kill-gate', 'gate.jsonl')
lines = []
if os.path.exists(logf):
    with open(logf) as fh:
        lines = fh.read().splitlines()
if len(lines) != 1 or 'kill-server' not in lines[0] or 'TMUX_TMPDIR' in lines[0]:
    bad += 1
    print(f'FAIL hook: expected exactly one deny line without the command text, got {lines}')
# malformed input never blocks
p = subprocess.run([sys.executable, '-I', GATE], input='not json', capture_output=True, text=True, env=env)
if p.returncode != 0:
    bad += 1
    print('FAIL hook: malformed stdin blocked')
# Viktor 43205 N41: the deny log never follows a symlink (O_NOFOLLOW): the block stands, the link target stays empty
victim = os.path.join(tree, 'victim.txt')
open(victim, 'w').close()
os.remove(logf)
os.symlink(victim, logf)
rc, err = hook('tmux kill-server', env)
if rc != 2 or os.path.getsize(victim) != 0:
    bad += 1
    print(f'FAIL hook: log symlink followed or block lost (rc {rc}, victim {os.path.getsize(victim)} bytes)')
# Viktor 43205 N26: the watchdog -- a decide() slower than the limit blocks when tmux/kill is named, allows otherwise
WD = ("import importlib.util, sys, time\n"
      "spec = importlib.util.spec_from_file_location('g', sys.argv[1]); g = importlib.util.module_from_spec(spec)\n"
      "spec.loader.exec_module(g)\n"
      "g.WATCHDOG_S = 0.2\n"
      "g.decide = lambda c: (time.sleep(5), [])[1]\n"
      "sys.exit(g.main())\n")
for _cmd, _want in (('tmux ls', 2), ('ls -la', 0)):
    p = subprocess.run([sys.executable, '-I', '-c', WD, GATE], capture_output=True, text=True, env=env, timeout=30,
                       input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': _cmd}}))
    if p.returncode != _want or (_want == 2 and 'TMUX-KAPU' not in p.stderr):
        bad += 1
        print(f'FAIL watchdog: {_cmd!r} -> rc {p.returncode}, want {_want} {p.stderr!r}')
print('hook protocol: done')
sys.exit(1 if bad else 0)
