#!/usr/bin/env python3
"""Tests for este-blokk-write-gate.py (card 0260694d, Klodel 49761).

The install is a temp tree (CLAUDE_PROJECT_DIR, set before the module loads), so a protected path is
<tmp>/store/patrik-este-blokk.json. The tables go through decide() with the install as the payload cwd; a few rows
run the hook as Claude Code does (JSON on stdin; exit 0 allow, 2 block), and the deny log goes through main() with
its state under the temp tree. Hermetic: no file is written outside the temp tree; the commands are only text. The
temp tree is NOT under /tmp (kapu-subagens-bekotes Buktatók), it goes under ~/.cache then.
Run: python3 -I scripts/hooks/este-blokk-write-gate_test.py
"""
import atexit
import hashlib
import importlib.util
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'este-blokk-write-gate.py')
base = tempfile.gettempdir()
if os.path.realpath(base).startswith(('/tmp', '/private/tmp')):
    base = os.path.expanduser('~/.cache')
    os.makedirs(base, exist_ok=True)
TMP = os.path.realpath(tempfile.mkdtemp(prefix='este-gate-test-', dir=base))
atexit.register(shutil.rmtree, TMP, True)
R = os.path.join(TMP, 'install')
os.makedirs(os.path.join(R, 'store'))
os.makedirs(os.path.join(TMP, 'other'))
os.symlink(os.path.join(R, 'store'), os.path.join(TMP, 'storelink'))
B = 'store/patrik-este-blokk.json'
AB = f'{R}/{B}'

DEEP_WRITE = f'echo x > {B}'
for _ in range(4):  # 4 levels of bash -c (the first heads stopped at 3)
    DEEP_WRITE = 'bash -c ' + shlex.quote(DEEP_WRITE)
DEEP_READ = f'jq length {B}'
for _ in range(10):
    DEEP_READ = 'bash -c ' + shlex.quote(DEEP_READ)

# every row must block (Bash, cwd = the install)
BLOCK = [
    # the 78 measured hand writes were python json.dump (76) and redirections (4)
    f"""python3 -c "import json; json.dump([], open('{B}','w'))" """,
    f"""python3 -c "import json; d=json.load(open('{AB}')); d.append(1); json.dump(d, open('{AB}','w'), indent=2)" """,
    f"python3 - <<'PY'\nimport json\nd = json.load(open('{B}'))\nd = d[1:]\njson.dump(d, open('{B}', 'w'))\nPY",
    f"python3 <<'PY'\nimport json\nwith open('{B}', 'w') as f:\n    json.dump([], f)\nPY",
    f"cd {R} && python3 - <<'PY'\nimport json\nopen('{B}', 'w').write('[]')\nPY",
    f"""python3 - <<<"import json;json.dump([],open('{B}','w'))" """,
    f"""python3 -c "import pathlib; pathlib.Path('{B}').write_text('[]')" """,
    f"""python3 -c "import os; os.remove('{B}')" """,
    f"""python3 -c "import os; os.replace('/x/new.json', '{AB}')" """,
    f"""python3 -c "import shutil; shutil.copy('{B}.utolso-drain.json', '{B}')" """,
    f"""python3.12 -c "open('{B}.hiba.jsonl', 'a').write('x')" """,
    # node: the smoke-test miss (require('fs') is no bare fs.), and fs.promises
    f"""node -e "require('fs').writeFileSync('{B}','[]')" """,
    f"""node -e "fs.promises.writeFile('{B}','[]')" """,
    f"""node -e "require('fs').unlinkSync('{B}.lock')" """,
    f"""ruby -e "File.write('{B}','[]')" """,
    "node -e 'require(\"fs\").writeFileSync(`" + B + "`, \"[]\")'",  # a JS template literal is a literal
    f"perl -i -pe 's/a/b/' {B}",
    f"perl -pi -e 's/a/b/' {AB}",
    # redirections
    f"echo '[]' > {B}",
    f"echo x >> {AB}",
    f"echo x >| {B}",
    f"printf '[]' &> {B}",
    f"cat > {B} <<'EOF'\n[]\nEOF",
    f"jq '.[1:]' {B} > /x/t && cat /x/t > {B}",
    f"echo x > {R}/Store/Patrik-Este-Blokk.json",  # APFS is case-insensitive
    # writers (the credentials-write-gate model)
    f"cat /x/a | tee {B}",
    f"cp /x/a.json {B}",
    f"cp {B} /x/backup.json",  # a copy by hand is a read by hand
    f"mv {B}.hiba.jsonl /x/",
    f"dd if=/dev/null of={B}",
    f"truncate -s0 {B}",
    f"touch {B}.lock",
    f"sed -i '' 's/a/b/' {B}",
    # removers, globs
    f"rm {B}.lock",
    f"rm -f {AB}",
    f"unlink {B}",
    f"rm store/patrik-este-*.json",
    # variables, cd, nested shells
    f"F={B}; echo x > $F",
    f"F={AB}; cp /x/a $F",
    f"cd store && echo x > patrik-este-blokk.json",
    f"cd {R}/store; rm patrik-este-blokk.json.lock",
    f"""bash -c "echo x > {B}" """,
    f"""eval "echo x > {B}" """,
    f"bash <<'SH'\necho x > {B}\nSH",
    f"echo 'echo x > {B}' | bash",
    f"""python3 -c "f = open('{B}', 'w'); f.close()" """,
    f"""python3 -c "import json; m = 'w'; json.dump([], open('{B}', m))" """,  # the mode in a variable
    f"echo x > $UNKNOWN/patrik-este-blokk.json",  # cannot be resolved: counts
    # Viktor 49773 L1: the shapes the first head let through
    f"""python3 -Ic "open('{B}','w').write('[]')" """,
    f"""python3 -IBc "import json; json.dump([], open('{B}','w'))" """,
    f"pushd store && echo x > patrik-este-blokk.json",
    f"pushd {R}/store; rm patrik-este-blokk.json.lock",
    f"""python3 -c "import sys,json; json.dump([], open(sys.argv[1],'w'))" {B}""",
    f"""P={B} python3 -c "import os; open(os.environ['P'],'w').write('[]')" """,
    f"python3 - {B} <<'PY'\nimport sys\nopen(sys.argv[1], 'w').write('[]')\nPY",
    f'for f in {B}; do cp /x/a "$f"; done',
    f"for f in /x/a {AB}.lock; do rm $f; done",
    f"F={B} bash -c 'echo x > $F'",
    f"F={B}; bash -c \"echo x > $F\"",
    f"""perl -e 'open(my $fh, ">", "{B}") or die'""",
    f"""perl -e "open(F, '>>', '{B}')" """,
    f"""perl -e "open(F, '+<', '{B}')" """,
    # Viktor 49773 test gaps: a brace name (E05), a perl -ne cluster (E24)
    f"rm store/patrik-este-blokk.{{json,x}}",
    f"""perl -ne 'open(F, ">", "{B}")' /x/in""",
    # Viktor 49776 L2: a restore into the store directory, the name kept by the copy
    "cp /backup/patrik-este-blokk.json store/",
    "cp -t store /backup/patrik-este-blokk.json",
    "cp --target-directory=store /backup/patrik-este-blokk.json",  # Viktor 49783 F18
    f"mv /x/patrik-este-blokk.json.hiba.jsonl {R}/store",
    # Viktor 49776 L3: -IPc cluster, argv with a here-string, a variable inside the code
    f"""python3 -IPc "open('{B}','w').write('[]')" """,
    f"""python3 - {B} <<< "import sys; open(sys.argv[1],'w').write('[]')" """,
    f'F={B}; python3 -c "open(\\"$F\\", \'w\').write(\'[]\')"',
    # Viktor 49783 L1: a bare name in a for list, an unquoted here-document's substitutions, deep nesting, Path.replace,
    # os.open, node --eval=, ruby FileUtils / File.delete, perl unlink / rename
    'for f in patrik-este-blokk.json; do cp /x/t "store/$f"; done',
    f"cat > notes.md <<EOF\n`rm {B}.lock`\nEOF",
    f"cat > notes.md <<EOF\n$(echo x > {B})\nEOF",
    DEEP_WRITE,
    f"""python3 -c "from pathlib import Path; Path('/x/t.json').replace('{B}')" """,
    f"python3 - <<'PY'\nfrom pathlib import Path\np = '{B}'\nPath('/x/t.json').replace(p)\nPY",
    f"""python3 -c "import os; fd = os.open('{B}', os.O_WRONLY | os.O_TRUNC)" """,
    f"""node --eval="require('fs').writeFileSync('{B}','[]')" """,
    f"""ruby -rfileutils -e "FileUtils.mv('/x/t', '{B}')" """,
    f"""ruby -e "File.delete('{B}.lock')" """,
    f"""perl -e "unlink('{B}.lock')" """,
    f"""perl -e "rename('/x/t', '{B}')" """,
    # an open quote while the text names the file: fail-closed
    f"""python3 -c "open('{B}','w')""",
    # through a symlinked directory
    f"echo x > {TMP}/storelink/patrik-este-blokk.json",
]

# every row must pass (Bash, cwd = the install)
ALLOW = [
    f"cat {B}",
    f"jq length {AB}",
    f"ls -la store/patrik-este-blokk.json*",
    f"python3 -I scripts/este-blokk-add.py --tipus dontes --agens kernel --forras x --mi 'y'",
    "python3 -I scripts/este-blokk-drain.py",
    f"""python3 -c "import json; print(len(json.load(open('{B}'))))" """,
    f"""python3 -c "import json; d=json.load(open('{B}')); print(d.copy())" """,
    f"python3 - <<'PY'\nimport json\nfor x in json.load(open('{B}')):\n    print(x['tipus'])\nPY",
    f"cp {B}.utolso-drain.json /x/a",
    f"echo x > {B}.utolso-drain.json",
    f"cp {B}.bak-1121 /x/",
    f"echo x > {TMP}/other/patrik-este-blokk.json",
    f"""python3 -c "open('{TMP}/other/patrik-este-blokk.json','w').write('[]')" """,
    f"""python3 -c "open('/x/out.json','w').write('[]')" """,
    # a here-document no shell or interpreter runs: a note, a card comment, a message read by a script
    f"cat > HANDOFF.md <<'EOF'\npython3 -c \"json.dump(x, open('{B}','w'))\"\necho x > {B}\nEOF",
    f"bash tools/card-comment.sh 0260694d - <<'MSG'\nne: echo x > {B}\nMSG",
    f"bash scripts/agent-msg.sh klodel kernel - <<'MSG'\nrm {B}.lock\nMSG",
    f"grep -n 'patrik-este-blokk' .claude/skills/napi-eredmeny-este/SKILL.md",
    # Python code writing markdown that names the file in backticks (7 of 321 replayed main-agent calls)
    f"python3 -I - <<'PY'\nf='.claude/skills/x/SKILL.md'\nt=open(f).read()\nt += '- ne írd a `{B}`-t kézzel'\n"
    f"open(f,'w').write(t)\nPY",
    "echo nothing to do with the block > /x/y",
    "cp /backup/patrik-este-blokk.json /x/",
    # Viktor 49783: a quoted here-document's backticks are text; str.replace takes two arguments; a keyword replace;
    # a deep but harmless nesting (10 levels of bash -c, 118 KB); a bare name in a for list that is only read
    f"cat > notes.md <<'EOF'\n`rm {B}.lock`\nEOF",
    f"""python3 -c "import json; d = json.load(open('{B}')); print(str(d).replace('a', 'b'))" """,
    f"""python3 -c "import json, datetime; d = json.load(open('{B}')); print(datetime.datetime.now().replace(hour=0))" """,
    DEEP_READ,
    'for f in patrik-este-blokk.json; do cat "store/$f"; done',
    "cp /x/other.json store/",
    # Viktor 49773: reads through argv, stdin, -Ic, pushd; the add script with the name in an argument
    f"""python3 -c "import sys,json; print(len(json.load(open(sys.argv[1]))))" {B}""",
    f"""python3 -c "import sys,json; print(json.load(sys.stdin))" < {B}""",
    f"""python3 -Ic "print(open('{B}').read())" """,
    f"pushd store && cat patrik-este-blokk.json",
    f"python3 -I scripts/este-blokk-add.py --tipus dontes --agens kernel --forras x --mi 'lasd {B}'",
    f"for f in {B}; do cat $f; done",
]

# Write/Edit/MultiEdit/NotebookEdit: (tool, path, want_block)
FILE_TOOLS = [
    ('Write', AB, True),
    ('Edit', AB, True),
    ('MultiEdit', f'{AB}.hiba.jsonl', True),
    ('Write', f'{AB}.lock', True),
    ('Write', f'{R}/store/PATRIK-ESTE-BLOKK.JSON', True),
    ('Write', f'{TMP}/storelink/patrik-este-blokk.json', True),
    ('Write', f'{R}/store/../store/patrik-este-blokk.json', True),
    ('NotebookEdit', AB, True),
    ('Write', f'{AB}.utolso-drain.json', False),
    ('Write', f'{TMP}/other/patrik-este-blokk.json', False),
    ('Edit', f'{R}/HANDOFF.md', False),
    ('Read', AB, False),
]


def load():
    os.environ['CLAUDE_PROJECT_DIR'] = R
    spec = importlib.util.spec_from_file_location('este_gate_under_test', HOOK)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run(payload):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=R)
    p = subprocess.run([sys.executable, '-I', HOOK], input=payload, capture_output=True, text=True, timeout=20,
                       env=env)
    return p.returncode, p.stderr


def bash(cmd, cwd=R):
    return {'tool_name': 'Bash', 'tool_input': {'command': cmd}, 'cwd': cwd}


def main():
    mod = load()
    fails = 0
    for cmd in BLOCK:
        if not mod.decide(bash(cmd)):
            print(f'FAIL block: {cmd!r}')
            fails += 1
    for cmd in ALLOW:
        why = mod.decide(bash(cmd))
        if why:
            print(f'FAIL allow: {cmd!r} -> {why}')
            fails += 1
    extra = 0
    for tool, path, want in FILE_TOOLS:
        extra += 1
        key = 'notebook_path' if tool == 'NotebookEdit' else 'file_path'
        got = bool(mod.decide({'tool_name': tool, 'tool_input': {key: path}, 'cwd': R}))
        if got != want:
            print(f'FAIL file tool: {tool} {path!r}: block={got} want {want}')
            fails += 1

    # cwd: a relative name is the install's only when the cwd is the install; no cwd counts (fail-closed)
    for cmd, cwd, want in ((f'echo x > {B}', f'{TMP}/other', False), (f'echo x > {B}', None, True),
                           (f"""python3 -c "open('{AB}','w')" """, f'{TMP}/other', True),
                           (f'cd {R} && echo x > {B}', f'{TMP}/other', True),
                           (f'echo x > {B}', 'relative/dir', True),
                           # Viktor 49783 L1: a cd the gate cannot resolve makes the cwd unknown (fail-closed)
                           (f'cd $CLAUDE_PROJECT_DIR && echo x > {B}', f'{R}/scripts', True),
                           (f'cd {TMP}/other; cd - && rm patrik-este-blokk.json.lock', f'{R}/store', True),
                           ('popd; rm patrik-este-blokk.json.lock', f'{TMP}/other', True)):  # a relative payload cwd counts as none (E18)
        extra += 1
        got = bool(mod.decide(bash(cmd, cwd)))
        if got != want:
            print(f'FAIL cwd: {cmd!r} cwd {cwd}: block={got} want {want}')
            fails += 1

    # deeper than MAX_DEPTH: a nested text naming the file blocks (fail-closed); checked with a lowered limit
    extra += 1
    old_max, mod.MAX_DEPTH = mod.MAX_DEPTH, 2
    three = f'jq length {B}'
    for _ in range(3):
        three = 'bash -c ' + shlex.quote(three)
    why = mod.decide(bash(three)) or ''
    mod.MAX_DEPTH = old_max
    if 'nested deeper' not in why:
        print(f'FAIL: a read nested past MAX_DEPTH must block fail-closed, got {why!r}')
        fails += 1

    # ReDoS: many `open(` with no `)` (300 KB) was quadratic before the {0,300} bound (2 s+, redos-probe 2026-11-21)
    extra += 1
    t0 = time.monotonic()
    mod.code_writes_block("open('~~~~~~x; " * 20000, R, 'node')
    if time.monotonic() - t0 > 1.0:
        print(f'FAIL: code_writes_block took {time.monotonic() - t0:.2f}s on 300 KB of unclosed open(')
        fails += 1

    # Viktor 49776 L1: quadratic shapes (many here-documents on one line: 24 s at 4000; an fs.WriteWrite... chain)
    for shape in ('cat <<E; ' * 2000 + f'jq length {B}',
                  "node -e \"const fs=require('fs'); fs." + 'Write' * 16000 + f"; console.log(fs.readFileSync('{B}'))\""):
        extra += 1
        t0 = time.monotonic()
        mod.decide(bash(shape))
        if time.monotonic() - t0 > 1.5:
            print(f'FAIL: decide took {time.monotonic() - t0:.2f}s on {shape[:30]!r} ({len(shape)} chars)')
            fails += 1

    # the hook as Claude Code runs it
    for payload, want in ((bash(f"echo x > {B}"), 2), (bash(f"cat {B}"), 0),
                          ({'tool_name': 'Write', 'tool_input': {'file_path': AB, 'content': '[]'}, 'cwd': R}, 2),
                          ({'tool_name': 'Read', 'tool_input': {'file_path': AB}, 'cwd': R}, 0)):
        extra += 1
        rc, err = run(json.dumps(payload))
        if rc != want or (want == 2 and ('ESTE-BLOKK-KAPU (Klodel 49761, kártya 0260694d)' not in err
                                         or 'este-blokk-add.py' not in err)):
            print(f'FAIL hook: {payload["tool_name"]} rc={rc} want {want} {err[-160:]!r}')
            fails += 1
    for bad in ('not json', '[]'):
        extra += 1
        rc, err = run(bad)
        if rc != 0:
            print(f'FAIL: unreadable or non-object stdin must pass like the sibling gates, rc={rc}')
            fails += 1
    # fail-closed: an error inside the gate blocks (a lone surrogate cannot be encoded for the hash)
    extra += 1
    rc, err = run(json.dumps(bash(f'echo \ud800; echo x > {B}')))
    if rc != 2 or 'ESTE-BLOKK-KAPU error' not in err:
        print(f'FAIL: an exception in the gate must block (exit 2), rc={rc} {err[-120:]!r}')
        fails += 1

    # deny log through main(), state under TMP: sha256 + reason, never the command text
    state = os.path.join(TMP, 'state')
    mod.STATE, mod.DENY_LOG = state, os.path.join(state, 'deny.log')
    cmd = f'echo SECRETTEXT > {B}'
    payload = bash(cmd)
    digest = hashlib.sha256(json.dumps(payload['tool_input'], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    old_in, old_err = sys.stdin, sys.stderr
    sys.stdin, sys.stderr = io.StringIO(json.dumps(payload)), io.StringIO()
    try:
        rc, err = mod.main(), sys.stderr.getvalue()
    finally:
        sys.stdin, sys.stderr = old_in, old_err
    extra += 3
    if rc != 2 or 'SECRETTEXT' in err:
        print(f'FAIL: deny message: rc={rc} {err!r}')
        fails += 1
    with open(mod.DENY_LOG) as f:
        log = f.read()
    if digest not in log or 'SECRETTEXT' in log or 'redirection' not in log:
        print(f'FAIL: deny log: {log!r}')
        fails += 1
    if os.stat(mod.DENY_LOG).st_mode & 0o077:
        print('FAIL: deny log not owner-only')
        fails += 1

    total = len(BLOCK) + len(ALLOW) + extra
    print(f'{total - fails}/{total} ok' if not fails else f'{fails} FAIL of {total}')
    if fails:
        print('FAIL este_blokk_gate_cases')  # the line tools' mutation runner reads as a kill
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
