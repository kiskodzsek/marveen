#!/usr/bin/env python3
"""Tests for credentials-write-gate.py (card a467f621, Viktor 48495; round 2: Viktor 48557).

The table goes through the module's judge(cmd); a few rows also run the hook as Claude Code does (JSON on stdin;
exit 0 allow, 2 block), and the deny log through the module with its state under a temp directory.
Hermetic: no file is written outside the temp tree; the commands are only text. The temp tree is NOT under /tmp
(kapu-subagens-bekotes Buktatók), it goes under ~/.cache then.
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
C = '.credentials.json'

# every row must block
BLOCK = [
    # the card's list: cp, mv, ln -s, install, ditto, rsync, tee, redirection -- the destination
    f'cp /a/tok.json ~/.claude/{C}',
    f'mv old.json {C}',
    f'ln -s /a/tok.json ~/.claude-config/{C}',
    f'install -m 600 tok.json ~/.claude/{C}',
    f'ditto a.json ~/.claude/{C}',
    f'rsync -a a.json ~/.claude/{C}',
    f'cp --target-directory=/x/{C} a',
    f'cp -- a.json {C}',
    f'link a.json {C}',
    # any .credentials.json source (Viktor 48557 Q1: AUTH rule 2 forbids the copy too)
    f'cp ~/.claude/{C} agents/dave/.claude-config/',
    f'cp ~/.claude/{C} /backup/x.json',
    f'cp /x/{C} sub',
    f'mv /x/{C} /y/z',
    f'mv {C} {C}.expired-1120',
    f'ln -s /a/{C}',
    f'ln -sf /a/{C} "$HOME/.claude/"',
    f'install -m 600 /x/{C} /y/',
    f'rsync -a --exclude x /a/{C} /b/',
    f'gcp -t ~/.claude/ /a/{C}',
    f'cp --target-directory /x /a/{C}',
    # a one-level brace, as the shell expands it (Viktor 48557 M1: restore and backup)
    f'cp ~/backup/{C}{{.bak,}}',
    f'mv ~/.claude/{C}{{.bak,}}',
    f'cp -p ~/.claude/{{{C}.bak,{C}}}',
    f'cp ~/.claude/{C}{{,.bak}}',
    # redirections
    f'tee ~/.claude/{C} < x',
    f'echo y | tee -a {C} >/dev/null',
    f'echo x > ~/.claude/{C}',
    f'echo x >> {C}',
    f'echo x 2> {C}',
    f'echo x &> {C}',
    f'echo x >| {C}',
    f'cat a >{C}',
    f'exec 3<> {C}',
    f'printf x | cat > "$HOME/.claude/{C}"',
    # the other writers
    f'touch {C}',
    f'touch -t 202611200000 {C}',
    f'truncate -s 0 {C}',
    f'dd if=a of=/x/{C}',
    f'gdd if=a of=/x/{C}',
    f'gtee {C} < x',
    f'gtouch {C}',
    f'gtruncate -s 0 {C}',
    f'echo x | sponge {C}',
    f'sort -o {C} x',
    # round 2 (Viktor 48607 L1): combined in-place options, and macOS sed -I
    f'gsed -zi s/a/b/ {C}',
    f'sed -si s/a/b/ {C}',
    f'perl -spi -e s/a/b/ {C}',
    f'perl -Tpi -e s/a/b/ {C}',
    f"sed -I '' s/a/b/ {C}",
    f'sed -I.bak s/a/b/ {C}',
    # round 2 (Viktor 48607 INFO 1): the surviving mutants' rows
    f'gsort -o ~/.claude/{C} x',
    f'sed --in-place s/a/b/ ~/.claude/{C}',
    'touch ~/.claude/.credentials{.json,}',
    'tee ~/.claude/{.credentials.json,x} < y',
    f'base64 -i x -o {C}',
    f"sed -i '' 's/a/b/' ~/.claude/{C}",
    f"sed -Ei 's/a/b/' {C}",
    f"perl -pi -e 's/a/b/' {C}",
    f"perl -i.bak -pe 's/a/b/' {C}",
    f'curl -sSLo {C} https://example.invalid/x',
    f'curl -o {C} https://example.invalid/x',
    f'curl --output={C} https://example.invalid/x',
    f'wget -O {C} https://example.invalid/x',
    # letter case (APFS; casefold: U+017F long s, Viktor 48557 L1), glob, brace, variables
    'cp a ~/.claude/.Credentials.JSON',
    'cp a ~/.claude/.credentialſ.json',
    'cp a ~/.claude/.cred*',
    f'cp a ~/.claude/{{{C},b}}',
    f'F=~/.claude/{C}; cp a "$F"',
    f'export D=/x; cp a $D/{C}',
    # wrappers and text a shell runs
    f'sudo cp a {C}',
    f'env X=1 cp a {C}',
    f'nohup tee {C} </dev/null',
    f'bash -c "cp a ~/.claude/{C}"',
    f"sh -lc 'echo x > {C}'",
    f'eval cp a {C}',
    f'echo "$(cp a {C})"',
    f"bash <<'EOF'\ncp a {C}\nEOF",
    f"echo 'cp a {C}' | bash",
    f'true && (cp a {C})',
    f"bash -c \"sh -c 'eval cp x ~/.claude/{C}'\"",   # three levels deep (Viktor 48557 INFO 1, C23)
    # fail-closed: an open quote while the text names the file
    f"cp a {C} 'x",
]

# every row must pass
ALLOW = [
    f'ls -la ~/.claude/{C}',
    f'stat -f %z {C}',
    f'test -f {C} && echo y',
    f'[ -e "$c/{C}" ] && echo CRED-FILE || echo no-cred',
    f'cat ~/.claude/{C} | wc -c',
    f'grep -c x {C} 2>/dev/null',
    f'ls {C} 2>&1 | cut -c1-80',
    f'shasum -a 256 {C}',
    f'find ~ -maxdepth 3 -name {C}',
    f'rm -f ~/.claude-config/{C}',
    f'chmod 600 {C}',
    f'echo {C}',
    f'cp {C}.bak /backup/x.json',
    'cp a{1,2}.txt /x/',
    'cp f{.bak,} /x/z',
    'D=/x; cp kepek/* "$D"/',
    'D=/x; cp credits/* "$D"/',               # a dotless glob never names a dotfile (INFO 1, C04: "cred" passes the pre-check)
    f'F=~/.claude/{C}; unset F; cp x $F',      # an unset name is unknown again (INFO 1, C26)
    f'rsync -a --exclude {C} src/ dst/',
    f'rsync -a --exclude={C} src/ dst/',
    f"cat > notes.md <<'EOF'\ncp a ~/.claude/{C}\necho x > {C}\nEOF",
    f'bash scripts/agent-msg.sh kernel klodel "never cp x > {C}"',
    f'curl -O https://example.invalid/{C}.txt',
    f'sed -n 1p {C}',
    f"perl -Mstrict -ne 'print' {C}",          # -M is no in-place (INFO 2)
    f'perl -MList::Util=max -e 1 {C}',
    f'perl -mstrict -ne 1 {C}',                # -m, -I, -l, -e take or are no in-place (Viktor 48607)
    f'perl -Iinc -ne 1 {C}',
    f'perl -le 1 {C}',
    f'sed -n -e 1p {C}',
    f'sed -e s/i/I/ {C}',
    f'install --mode 600 a /x/',
    'cp a b',
    'echo credit > report.txt',
    # documented gap (NOT MODELLED): an interpreter's own open(..., 'w') passes
    f"python3 -c \"open('{C}', 'w')\"",
]


def run(cmd, tool='Bash'):
    payload = {'tool_name': tool, 'tool_input': {'command': cmd}, 'cwd': TMP}
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
    for cmd in BLOCK:
        if not mod.judge(cmd):
            print(f'FAIL block: {cmd!r}')
            fails += 1
    for cmd in ALLOW:
        why = mod.judge(cmd)
        if why:
            print(f'FAIL allow: {cmd!r} -> {why}')
            fails += 1
    extra = 0

    # the hook as Claude Code runs it: a block, a pass, a copy out, another tool, unreadable stdin
    for cmd, tool, want in ((f'cp a ~/.claude/{C}', 'Bash', 2), (f'ls -la {C}', 'Bash', 0),
                            (f'cp ~/.claude/{C} /backup/x.json', 'Bash', 2), (f'cp a {C}', 'Read', 0)):
        extra += 1
        rc, err = run(cmd, tool)
        if rc != want or (want == 2 and 'CREDENTIALS-WRITE-GATE (card a467f621)' not in err):
            print(f'FAIL hook: {cmd!r} tool {tool}: rc={rc} want {want} {err[-160:]!r}')
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
