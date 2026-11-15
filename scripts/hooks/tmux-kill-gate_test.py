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

# Viktor 43177 INFO 1 (mutant M16 survived): an internal error blocks when the command mentions tmux or kill, and
# allows otherwise. In process: decide() is made to raise, main() reads the hook JSON from a replaced stdin.
import io  # noqa: E402
import signal  # noqa: E402


def _boom(_cmd):
    raise RuntimeError('synthetic')


_real_decide, _real_stdin, _real_stderr = g.decide, sys.stdin, sys.stderr
g.decide = _boom
try:
    for _cmd, _want in (('tmux kill-server', 2), ('kill 1234', 2), ('ls -la', 0)):
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
            _real_stderr.write(f'FAIL exception path: {_cmd!r} -> rc {_rc}, want {_want}\n')
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
lines = open(logf).read().splitlines() if os.path.exists(logf) else []
if len(lines) != 1 or 'kill-server' not in lines[0] or 'TMUX_TMPDIR' in lines[0]:
    bad += 1
    print(f'FAIL hook: expected exactly one deny line without the command text, got {lines}')
# malformed input never blocks
p = subprocess.run([sys.executable, '-I', GATE], input='not json', capture_output=True, text=True, env=env)
if p.returncode != 0:
    bad += 1
    print('FAIL hook: malformed stdin blocked')
print('hook protocol: done')
sys.exit(1 if bad else 0)
