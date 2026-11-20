#!/usr/bin/env python3
"""Tests for credentials-write-gate.py (card a467f621, Viktor 48495).

The table goes through the module's judge(cmd, cwd); a few rows also run the hook as Claude Code does (JSON on
stdin; exit 0 allow, 2 block), and the deny log through the module with its state under a temp directory.
Hermetic: no file is written outside the temp tree; the commands are only text. The temp tree is NOT under /tmp
(a /tmp ancestor would change the relative-path rows; kapu-subagens-bekotes Buktatók), it goes under ~/.cache then.
Run: python3 -I scripts/hooks/credentials-write-gate_test.py
"""
import atexit
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'credentials-write-gate.py')
base = tempfile.gettempdir()
if os.path.realpath(base).startswith(('/tmp', '/private/tmp')):
    base = os.path.expanduser('~/.cache')
    os.makedirs(base, exist_ok=True)
TMP = os.path.realpath(tempfile.mkdtemp(prefix='credjson-gate-test-', dir=base))
atexit.register(shutil.rmtree, TMP, True)
DIR = os.path.join(TMP, 'cfg')          # an existing directory (an agent's config dir in real use)
os.makedirs(os.path.join(DIR, 'sub'))
ELSE = os.path.join(TMP, 'elsewhere')   # a cwd where `sub` does not exist
os.makedirs(ELSE)
C = '.credentials.json'


def fix(cmd):
    return cmd.replace('{DIR}', DIR).replace('{ELSE}', ELSE)


# (command, cwd or None): every row must block
BLOCK = [
    # the card's list: cp, mv, ln -s, install, ditto, rsync, tee, redirection
    (f'cp /a/tok.json ~/.claude/{C}', None),
    (f'cp ~/.claude/{C} agents/dave/.claude-config/', None),
    (f'cp /x/{C} {{DIR}}', None),
    (f'cp /x/{C} sub', '{DIR}'),
    (f'cd {{DIR}} && cp /x/{C} sub', '{ELSE}'),
    (f'cd {{DIR}}; cd sub; cp /x/{C} .', None),
    (f'mv old.json {C}', None),
    (f'mv /x/{C} {{DIR}}/sub', None),
    (f'ln -s /a/{C} ~/.claude-config/{C}', None),
    (f'ln -s /a/{C}', None),
    (f'ln -sf /a/{C} "$HOME/.claude/"', None),
    (f'install -m 600 tok.json ~/.claude/{C}', None),
    (f'install -m 600 /x/{C} {{DIR}}', None),
    (f'ditto a.json ~/.claude/{C}', None),
    (f'rsync -a a.json ~/.claude/{C}', None),
    (f'rsync -a --exclude x /a/{C} {{DIR}}/', None),
    (f'gcp -t ~/.claude/ /a/{C}', None),
    (f'cp --target-directory=/x /a/{C}', None),
    (f'cp --target-directory /x /a/{C}', None),
    (f'cp -- a.json {C}', None),
    (f'tee ~/.claude/{C} < x', None),
    (f'echo y | tee -a {C} >/dev/null', None),
    (f'echo x > ~/.claude/{C}', None),
    (f'echo x >> {C}', None),
    (f'echo x 2> {C}', None),
    (f'echo x &> {C}', None),
    (f'echo x >| {C}', None),
    (f'cat a >{C}', None),
    (f'exec 3<> {C}', None),
    (f'printf x | cat > "$HOME/.claude/{C}"', None),
    # the other writers
    (f'touch {C}', None),
    (f'touch -t 202611200000 {C}', None),
    (f'truncate -s 0 {C}', None),
    (f'dd if=a of=/x/{C}', None),
    (f"sed -i '' 's/a/b/' ~/.claude/{C}", None),
    (f"perl -pi -e 's/a/b/' {C}", None),
    (f'curl -sSLo {C} https://example.invalid/x', None),
    (f'curl -o {C} https://example.invalid/x', None),
    (f'curl --output={C} https://example.invalid/x', None),
    (f'wget -O {C} https://example.invalid/x', None),
    # letter case (APFS), glob, brace, variables
    ('cp a ~/.claude/.Credentials.JSON', None),
    ('cp a ~/.claude/.cred*', None),
    (f'cp a ~/.claude/{{{C},b}}', None),
    (f'F=~/.claude/{C}; cp a "$F"', None),
    (f'export D=/x; cp a $D/{C}', None),
    (f'cp /a/{C} "$UNKNOWN_DEST"', None),
    # wrappers and text a shell runs
    (f'sudo cp a {C}', None),
    (f'env X=1 cp a {C}', None),
    (f'nohup tee {C} </dev/null', None),
    (f'bash -c "cp a ~/.claude/{C}"', None),
    (f"sh -lc 'echo x > {C}'", None),
    (f'eval cp a {C}', None),
    (f'echo "$(cp a {C})"', None),
    (f"bash <<'EOF'\ncp a {C}\nEOF", None),
    (f"echo 'cp a {C}' | bash", None),
    (f'true && (cp a {C})', None),
    # fail-closed: an open quote while the text names the file
    (f"cp a {C} 'x", None),
]

# every row must pass
ALLOW = [
    (f'ls -la ~/.claude/{C}', None),
    (f'stat -f %z {C}', None),
    (f'test -f {C} && echo y', None),
    (f'[ -e "$c/{C}" ] && echo CRED-FILE || echo no-cred', None),
    (f'cat ~/.claude/{C} | wc -c', None),
    (f'grep -c x {C} 2>/dev/null', None),
    (f'ls {C} 2>&1 | cut -c1-80', None),
    (f'shasum -a 256 {C}', None),
    (f'find ~ -maxdepth 3 -name {C}', None),
    (f'rm -f ~/.claude-config/{C}', None),
    (f'chmod 600 {C}', None),
    (f'echo {C}', None),
    (f'cp {C}.bak /backup/x.json', None),
    (f'cp /a/{C} sub', '{ELSE}'),          # `sub` is no directory here: a file copy out, not a placement
    (f'mv {C} {C}.expired-1120', '{ELSE}'),
    ('D=/x; cp kepek/* "$D"/', None),          # a dotless glob never names a dotfile in the shell
    (f'rsync -a --exclude {C} src/ dst/', None),
    (f'rsync -a --exclude={C} src/ dst/', None),
    (f"cat > notes.md <<'EOF'\ncp a ~/.claude/{C}\necho x > {C}\nEOF", None),
    (f'bash scripts/agent-msg.sh kernel klodel "never cp x > {C}"', None),
    (f'curl -O https://example.invalid/{C}.txt', None),
    (f'sed -n 1p {C}', None),
    ('cp a b', None),
    ('echo credit > report.txt', None),
    # documented gap (NOT MODELLED): an interpreter's own open(..., 'w') passes
    (f"python3 -c \"open('{C}', 'w')\"", None),
]


def run(cmd, tool='Bash', cwd=None):
    payload = {'tool_name': tool, 'tool_input': {'command': cmd}}
    if cwd:
        payload['cwd'] = cwd
    p = subprocess.run([sys.executable, '-I', HOOK], input=json.dumps(payload), capture_output=True, text=True,
                       timeout=20)
    return p.returncode, p.stderr


def load():
    spec = importlib.util.spec_from_file_location('credjson_write_gate', HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    fails = 0
    mod = load()
    for raw, cwd in BLOCK:
        cmd, cwd = fix(raw), (fix(cwd) if cwd else None)
        if not mod.judge(cmd, cwd):
            print(f'FAIL block: {cmd!r} (cwd {cwd})')
            fails += 1
    for raw, cwd in ALLOW:
        cmd, cwd = fix(raw), (fix(cwd) if cwd else None)
        why = mod.judge(cmd, cwd)
        if why:
            print(f'FAIL allow: {cmd!r} (cwd {cwd}) -> {why}')
            fails += 1
    extra = 0

    # the hook as Claude Code runs it: a block, a pass, the payload cwd, another tool, unreadable stdin
    for cmd, tool, cwd, want in ((f'cp a ~/.claude/{C}', 'Bash', None, 2), (f'ls -la {C}', 'Bash', None, 0),
                                 (f'cp /x/{C} sub', 'Bash', DIR, 2), (f'cp /x/{C} sub', 'Bash', ELSE, 0),
                                 (f'cp a {C}', 'Read', None, 0),
                                 (f'mv {C} {C}.expired-1120', 'Bash', None, 0)):  # no payload cwd: the hook's own
        extra += 1
        rc, err = run(cmd, tool, cwd)
        if rc != want or (want == 2 and 'CREDENTIALS-WRITE-GATE (card a467f621)' not in err):
            print(f'FAIL hook: {cmd!r} tool {tool} cwd {cwd}: rc={rc} want {want} {err[-160:]!r}')
            fails += 1
    extra += 1
    p = subprocess.run([sys.executable, '-I', HOOK], input='not json', capture_output=True, text=True, timeout=20)
    if p.returncode != 0:
        print(f'FAIL: unreadable stdin JSON must pass like the sibling gates, rc={p.returncode}')
        fails += 1
    # fail-closed: an error inside the gate blocks (a lone surrogate cannot be encoded for the hash)
    extra += 1
    payload = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': f'echo \ud800; cp a {C}'}})
    p = subprocess.run([sys.executable, '-I', HOOK], input=payload, capture_output=True, text=True, timeout=20)
    if p.returncode != 2 or 'CREDENTIALS-WRITE-GATE error' not in p.stderr:
        print(f'FAIL: an exception in the gate must block (exit 2), rc={p.returncode} {p.stderr[-120:]!r}')
        fails += 1

    # deny log through the module, state under TMP: sha256 + reason, never the command text
    state = os.path.join(TMP, 'state')
    mod.STATE, mod.DENY_LOG = state, os.path.join(state, 'deny.log')
    cmd = f'echo SECRETTOKEN > ~/.claude/{C}'
    digest = hashlib.sha256(cmd.encode()).hexdigest()
    old_in, old_err = sys.stdin, sys.stderr
    sys.stdin, sys.stderr = io.StringIO(json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}})), io.StringIO()
    try:
        rc, err = mod.main(), sys.stderr.getvalue()
    finally:
        sys.stdin, sys.stderr = old_in, old_err
    extra += 3
    if rc != 2 or 'SECRETTOKEN' in err:
        print(f'FAIL: deny message: rc={rc} {err!r}')
        fails += 1
    with open(mod.DENY_LOG) as f:
        log = f.read()
    if digest not in log or 'SECRETTOKEN' in log or 'redirection' not in log:
        print(f'FAIL: deny log: {log!r}')
        fails += 1
    if os.stat(mod.DENY_LOG).st_mode & 0o077:
        print('FAIL: deny log not owner-only')
        fails += 1

    total = len(BLOCK) + len(ALLOW) + extra
    print(f'{total - fails}/{total} ok' if not fails else f'{fails} FAIL of {total}')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
