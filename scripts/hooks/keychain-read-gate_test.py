#!/usr/bin/env python3
"""Tests for keychain-read-gate.py (card c1921b55, Viktor 29950).

Runs the hook as Claude Code does (JSON on stdin; exit 0 allow, 2 block). Hermetic: no keychain call, no store
file, no network; the commands are only text.
Run: python3 -I scripts/hooks/keychain-read-gate_test.py
"""
import json
import os
import subprocess
import sys

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'keychain-read-gate.py')

# The fixtures spell the binary with a 3 for its first e ("s3curity"); fix() restores it at run time, so this file
# carries no runnable keychain call and running it is not blocked by the gate it tests (card bc009036).
def fix(cmd):
    return cmd.replace('s3c', 'sec').replace('S3C', 'SEC').replace('s"3c"', 's"ec"')


BLOCK = [
    's3curity find-generic-password -s "Claude Code-credentials" -w',
    's3curity find-internet-password -s example.test',
    's3curity dump-keychain',
    's3curity dump-keychain -d login.keychain-db',
    's3curity export -k login.keychain -t certs -o /tmp/x.p12',
    '/usr/bin/s3curity dump-keychain',
    'S3CURITY find-generic-password -s x',
    's3curity -q find-generic-password -s x',
    'env -i s3curity dump-keychain',
    'env FOO=bar PATH=/usr/bin s3curity export',
    'sudo s3curity find-generic-password -s x',
    'FOO=1 s3curity find-internet-password -s x',
    'xargs s3curity dump-keychain < /dev/null',
    'ls; s3curity dump-keychain',
    'ls && s3curity export -o x',
    'true || s3curity find-generic-password -w -s x',
    'cat a | s3curity dump-keychain',
    'x=$(s3curity find-generic-password -w -s y); echo ok',
    'echo `s3curity find-generic-password -w -s y`',
    'bash -c "s3curity dump-keychain"',
    "sh -c 's3curity find-generic-password -s x -w'",
    'ssh host \'s3curity dump-keychain\'',
    's3c\\urity dump-keychain',
    "s3c''urity dump-keychain",
    's3curity \\\n  dump-keychain',
    'echo dump-keychain | s3curity -i',
    's3curity -p "> " < cmds.txt',
    '( s3curity dump-keychain )',
    'if true; then\ns3curity export\nfi',
    # Viktor 30044 hardening: keyword positions, quoted words, $IFS, wrappers with an argument, find -exec.
    'if true; then s3curity dump-keychain; fi',
    'while true; do s3curity export; done',
    '! s3curity dump-keychain',
    '"s3curity" find-generic-password -s x',
    's"3c"urity dump-keychain',
    's3curity "find-generic-password" -s x',
    's3curity find-generic-"password" -s x',
    's3curity${IFS}find-generic-password -s x',
    's3curity$IFS dump-keychain',
    'timeout 5 s3curity dump-keychain',
    'timeout .5 s3curity dump-keychain',
    'nice -n 5 s3curity dump-keychain',
    'stdbuf -o0 s3curity export',
    'setsid s3curity dump-keychain',
    'find . -name x -exec s3curity dump-keychain {} +',
]

ALLOW = [
    'ls -la',
    's3curity list-keychains',
    's3curity find-identity -p codesigning -v',
    's3curity find-certificate -a -c Apple',
    's3curity show-keychain-info login.keychain',
    's3curity -v list-keychains',
    'export FOO=1',
    'echo export',
    'grep -n find-generic-password notes.md',
    'git commit -m "fix: s3curity export docs"',
    'echo "the s3curity team"',
    'npm audit --s3curity',
    'python3 s3curity_check.py dump-keychain-list',
    's3curity find-generic-password-helper',
    'node scripts/s3curity-review.mjs',
]


def run(payload):
    env = {'PATH': '/usr/bin:/bin'}
    p = subprocess.run([sys.executable, '-I', HOOK], input=payload, capture_output=True, text=True, env=env,
                       timeout=20)
    return p.returncode, p.stderr


def bash(cmd):
    return run(json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}}))


def bash_in(cmd, cwd):
    return run(json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}, 'cwd': cwd}))


# The assignment forms of the binary literal the rule must keep after the ReDoS fix (Viktor 41715); BIN is replaced.
LIT_FORMS = ["SEC = '/usr/bin/BIN'", 'SEC=BIN', 'SEC = "BIN"', 'X = ~/bin/BIN\nSEC = X', 'X=/usr/local/bin/BIN\nSEC = X']


def script_cases():
    """Card bc009036 (Kernel 41497, Viktor 41502): the file a command runs is judged too. Every script is written to
    a temp dir at run time from fragments; nothing is executed, the gate only reads the files."""
    import tempfile
    S = fix('s3curity')
    fails = []
    with tempfile.TemporaryDirectory() as d:
        def w(name, body):
            path = os.path.join(d, name)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(body)
            return path
        # measure.py's shape: the binary in a variable, the subcommand in a list
        w('measure.py', "import subprocess\nSEC = '/usr/bin/" + S + "'\n"
                        "subprocess.run([SEC, 'find-generic-password', '-a', 'acct', '-s', 'svc'])\n")
        w('stdin.py', "import subprocess\nSEC = '" + S + "'\nsubprocess.Popen([SEC, '-i', '-p', ''])\n")
        w('shellish.py', "import os\nos.system('" + S + " dump-keychain')\n")
        w('read.mjs', "import { execFileSync } from 'node:child_process';\n"
                      "execFileSync('" + S + "', ['find-internet-password', '-s', 'x']);\n")
        w('dump.sh', "#!/bin/sh\nset -e\n" + S + " dump-keychain > /dev/null\n")
        w('assign.sh', "#!/bin/sh\nSEC=/usr/bin/" + S + "\n$SEC find-generic-password -s x\n")
        w('export.py', "import subprocess\nsubprocess.run(['" + S + "', 'export', '-o', 'x.p12'])\n")
        w('list.py', "import subprocess\nsubprocess.run(['" + S + "', 'list-keychains'])\n")
        w('notes.py', "# the gate blocks find-generic-password in a shell\nprint('ok')\n")
        w('ok.js', "console.log('ok');\n")
        w('word.py', "print('the " + S + " team writes find-generic-password docs')\n")
        # a UI string table (web/lang/en.js): a capitalised label and button are not a subcommand
        w('labels.js', "module.exports = {\n  'settings.module." + S + "': '" + S.capitalize() + "',\n"
                       "  'skills.btn.export': 'Export',\n};\n")
        # the binary name is case-insensitive on APFS, the subcommand is not
        w('upper.py', "import subprocess\nsubprocess.run(['" + S.upper() + "', 'find-generic-password', '-s', 'x'])\n")
        os.makedirs(os.path.join(d, 'adir'))
        w('worker.mjs', "// the worker authenticates from the file; a `-p` run does not\n"
                        "execFileSync('/usr/bin/" + S + "', ['delete-generic-password', '-s', 'x']);\n")
        os.makedirs(os.path.join(d, 'sub2'))
        with open(os.path.join(d, 'sub2', 'only.py'), 'w', encoding='utf-8') as f:
            f.write("import subprocess\nsubprocess.run(['" + S + "', 'find-generic-password', '-s', 'x'])\n")
        with open(os.path.join(d, 'sub2', 'twin.py'), 'w', encoding='utf-8') as f:
            f.write("import subprocess\nsubprocess.run(['" + S + "', 'dump-keychain'])\n")
        w('twin.py', 'print(1)\n')
        w('tmpl.mjs', "import { execSync } from 'node:child_process';\nconst B = `/usr/bin/" + S + "`;\n"
                      "execSync(`${B} find-generic-password -s x`);\n")
        for i, form in enumerate(LIT_FORMS):
            w('lit%d.py' % i, form.replace('BIN', S) + "\nrun([SEC, 'dump-keychain'])\n")
        os.makedirs(os.path.join(d, 'initpkg'))
        with open(os.path.join(d, 'initpkg', '__init__.py'), 'w', encoding='utf-8') as f:
            f.write("import subprocess\nsubprocess.run(['" + S + "', 'find-generic-password', '-s', 'x'])\n")
        with open(os.path.join(d, 'initpkg', 'clean.py'), 'w', encoding='utf-8') as f:
            f.write("print(1)\n")
        os.makedirs(os.path.join(d, 'mainpkg'))
        with open(os.path.join(d, 'mainpkg', '__main__.py'), 'w', encoding='utf-8') as f:
            f.write("import subprocess\nsubprocess.run(['" + S + "', 'dump-keychain'])\n")
        sub = os.path.join(d, 'sub')
        os.makedirs(sub)
        with open(os.path.join(sub, 'deep.py'), 'w', encoding='utf-8') as f:
            f.write("SEC = '" + S + "'\nimport subprocess; subprocess.run([SEC, 'dump-keychain'])\n")
        block = [
            ('python3 measure.py', d),
            ('python3 -I ./measure.py', d),
            ('python3 -u -B measure.py --flag', d),
            ('/usr/bin/python3 ' + os.path.join(d, 'measure.py'), None),
            ('cd ' + d + ' && python3 measure.py', None),
            ('cd ' + d + ' && timeout 60 python3 measure.py', None),
            ('python3.12 measure.py', d),
            ('env A=1 python3 measure.py', d),
            ('python3 stdin.py', d),
            ('python3 shellish.py', d),
            ('node read.mjs', d),
            ('bash dump.sh', d),
            ('sh ./assign.sh', d),
            ('./dump.sh', d),
            ('sub/deep.py', d),
            (os.path.join(d, 'sub', 'deep.py') + ' --x', None),
            ('python3 export.py', d),
            ('python3 upper.py', d),
            # python -m runs ./measure.py from the cwd (measured 2026-11-13), attached and dotted forms too
            ('python3 -m measure', d),
            ('python3 -u -m measure --x', d),
            ('python3 -mmeasure', d),
            ('cd ' + d + ' && python3 -m sub.deep', None),
            ('python3 -m mainpkg', d),
            ('python3 -mmeasure --x', d),
            ('python3 -mmeasure arg1', d),
            ('python3 -m initpkg.clean', d),  # -m a.b imports a/__init__.py first
            # Viktor 41715 LOW: a flag's argument is not the file, relative cd, stdin, source, variables, uv run
            ('python3 -W ignore measure.py', d),
            ('python3 -X dev measure.py', d),
            ('bash -o pipefail dump.sh', d),
            ('cd sub2 && python3 only.py', d),
            ('(cd sub2; python3 only.py)', d),
            ('cd ' + d + ' && cd sub2 && python3 only.py', None),
            ('python3 < measure.py', d),
            ('python3 - < measure.py', d),
            ('cat measure.py | python3', d),
            ('source ./dump.sh', d),
            ('. ./dump.sh', d),
            ('F=measure.py; python3 $F', d),
            ('F="measure.py"; python3 "${F}"', d),
            ('uv run measure.py', d),
            ('uv run python measure.py', d),
            ('node tmpl.mjs', d),  # the binary in a JS template literal
            # Viktor 41756 LOW 2: every existing file is judged, an innocent first file does not hide the script
            ('node -r ./ok.js read.mjs', d),
            ('node --require ./ok.js read.mjs', d),
            ('python3 -W ./notes.py measure.py', d),
            ('python3 list.py measure.py', d),  # was allowed ("the rest are its arguments"); an argument is read too
            ('cd sub2 && python3 twin.py', d),  # a clean ./twin.py in the cwd does not hide sub2/twin.py
            # a shell -c payload: its opening quote is a command position for the script rules
            ('bash -c "./dump.sh"', d),
            ("bash -lc 'sub/deep.py --x'", d),
            ('sh -c "python3 measure.py"', d),
        ] + [('python3 lit%d.py' % i, d) for i in range(len(LIT_FORMS))] + [
            ('ls; python3 "measure.py"', d),
            ('python3 -c "import subprocess; subprocess.run([\'' + S + '\', \'dump-keychain\'])"', d),
            ("python3 - <<'PY'\nimport subprocess\nsubprocess.run(['" + S + "', 'find-generic-password'])\nPY", d),
            ("node -e \"require('child_process').execFileSync('" + S + "', ['dump-keychain'])\"", d),
        ]
        allow = [
            ('python3 list.py', d),
            ('python3 notes.py', d),
            ('python3 word.py', d),
            ('node labels.js', d),
            ('python3 missing.py', d),
            ('python3 adir', d),
            ('python3 -m list', d),
            ('python3 -m pip --version', d),
            ('python3 -m sub', d),  # sub/ has no __init__ or __main__ with a read; deep.py is not run by -m sub
            ('node -m measure', d),  # -m is python's; node has no module flag that runs ./measure.py
            ('node -e measure.py', d),  # -e: the text is code (an expression), the file is not run
            ('node -r ./ok.js list.py', d),  # two clean files
            # the word after a CLOSING quote is not a command: grep on a keychain-reading file passes (the #275 gate
            # blocked `grep -n "for x" scripts/hooks/keychain-read-gate.py`, 2026-11-14)
            ('grep -n "for x" sub/deep.py', d),
            ('grep -n "do" -A 18 sub/deep.py', d),
            ("sed -n '1,5p' sub/deep.py", d),
            ('grep -n "x" "sub/deep.py"', d),
            ('echo "run" python3 measure.py', d),
            ('python3 list.py ' + ' '.join(f'a{i}' for i in range(62)), d),  # 63 words: inside MAX_ARGS (64)
            ('python3 -c pass ' + 'a ' * 100, d),  # the walk stops at -c: the rest is not a script's words
            ('cd sub2 && cat only.py', d),  # no interpreter: reading a file is not running it
            ('python3 word.py < notes.py', d),
            ('node worker.mjs', d),  # agent-worker.ts shape: a non-read subcommand, `-p` only in a comment
            ('python3 -c "print(1)"', d),
            ('cat measure.py', d),
            ('grep -n find-generic-password measure.py', d),
            ('python3 measure.py', None),  # relative path, no cwd and no cd: not resolvable, not judged
            ('ls ' + d, None),
        ]
        for cmd, cwd in block:
            code, err = bash_in(cmd, cwd)
            if code != 2 or 'KULCSKARIKA-KAPU' not in err:
                fails.append(f'script: should block (got {code}): {cmd[:80]!r}')
            elif 'acct' in err or "'svc'" in err:
                fails.append(f'script: block message echoes the file: {cmd[:80]!r}')
        for cmd, cwd in allow:
            code, err = bash_in(cmd, cwd)
            if code != 0:
                fails.append(f'script: should allow (got {code}): {cmd[:80]!r} {err[:120]}')
        # the cap (MAX_SCRIPTS = 10): ten clean files pass, an eleventh blocks instead of going unread
        for i in range(11):
            w(f'c{i}.py', 'print(1)\n')
        code, _ = bash_in(' ; '.join(f'python3 c{i}.py' for i in range(10)), d)
        if code != 0:
            fails.append(f'script: ten clean files should pass (got {code})')
        code, err = bash_in(' ; '.join(f'python3 c{i}.py' for i in range(10)) + ' ; python3 measure.py', d)
        if code != 2 or 'script-too-many' not in err:
            fails.append(f'script: an eleventh file should block, not go unread (got {code})')
        # fail-closed: a file the gate cannot read (PermissionError) blocks, it is not skipped
        locked = w('locked.py', 'print(1)\n')
        os.chmod(locked, 0)
        try:
            if os.access(locked, os.R_OK):  # root reads it anyway: the case cannot be built
                fails.append('script: locked.py is readable (running as root?), fail-closed case not tested')
            else:
                code, err = bash_in('python3 locked.py', d)
                if code != 2 or 'PermissionError' not in err:
                    fails.append(f'script: an unreadable file should block fail-closed (got {code})')
        finally:
            os.chmod(locked, 0o600)
        # the time budget: past it the gate blocks instead of reading on (a timed-out hook does not block).
        # The env seam can only lower the budget: 0 blocks a clean file, 999 does not raise it past SCRIPT_BUDGET_S.
        def bash_env(cmd, cwd, extra):
            env = {'PATH': '/usr/bin:/bin', **extra}
            p = subprocess.run([sys.executable, '-I', HOOK], capture_output=True, text=True, env=env, timeout=20,
                               input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}, 'cwd': cwd}))
            return p.returncode, p.stderr
        code, err = bash_env('python3 c0.py', d, {'KEYCHAIN_GATE_SCRIPT_BUDGET_S': '0'})
        if code != 2 or 'script-too-slow' not in err:
            fails.append(f'script: past the budget a clean file should block (got {code})')
        code, _ = bash_env('python3 c0.py', d, {'KEYCHAIN_GATE_SCRIPT_BUDGET_S': 'x'})
        if code != 0:
            fails.append(f'script: a malformed budget falls back to the default (got {code})')
        code, _ = bash_env('ls ' + d, d, {'KEYCHAIN_GATE_SCRIPT_BUDGET_S': '0'})
        if code != 0:
            fails.append(f'script: no script file, the budget does not apply (got {code})')
        # ten 1 MB files of newlines (6.6 s unbudgeted, 2026-11-13): decided well inside the 10 s hook timeout,
        # and the seam cannot raise the budget (999 is capped at SCRIPT_BUDGET_S)
        for i in range(10):
            w(f'n{i}.sh', '\n' * (1024 * 1024))
        import time as _t
        t = _t.monotonic()
        code, err = bash_env(' ; '.join(f'bash n{i}.sh' for i in range(10)), d,
                             {'KEYCHAIN_GATE_SCRIPT_BUDGET_S': '999'})
        took = _t.monotonic() - t
        if took > 8:
            fails.append(f'script: ten 1 MB files took {took:.1f} s (hook timeout 10 s)')
        if code not in (0, 2) or (code == 2 and 'script-too-slow' not in err):
            fails.append(f'script: ten 1 MB clean files: want pass or script-too-slow (got {code}) {err[:120]}')
        # the seam itself: lower-only, malformed = default, negative = 0
        probe = ('import importlib.util as u,sys; s=u.spec_from_file_location("g",sys.argv[1]); m=u.module_from_spec(s);'
                 ' s.loader.exec_module(m); print(m.script_budget())')
        for val, want in [('999', '4.0'), ('0.5', '0.5'), ('x', '4.0'), ('-3', '0.0'), ('inf', '4.0'), ('nan', '4.0')]:
            p = subprocess.run([sys.executable, '-I', '-c', probe, HOOK], capture_output=True, text=True, timeout=20,
                               env={'PATH': '/usr/bin:/bin', 'KEYCHAIN_GATE_SCRIPT_BUDGET_S': val})
            if p.stdout.strip() != want:
                fails.append(f'script: budget seam {val!r} -> {p.stdout.strip()!r}, want {want}')
        # more directories than MAX_BASES (32) before a script: blocks instead of leaving the rest unresolved
        code, err = bash_in('cd a && ' * 40 + 'python3 list.py', d)
        if code != 2 or 'script-too-many' not in err:
            fails.append(f'script: 40 cd before a script should block (got {code})')
        code, _ = bash_in('cd a && ' * 40 + 'ls', d)
        if code != 0:
            fails.append(f'script: 40 cd without a script should pass (got {code})')
        # ~ is the home directory (Viktor 41715 LOW c)
        code, _ = bash_env('python3 ~/measure.py', None, {'HOME': d})
        if code != 2:
            fails.append(f'script: python3 ~/measure.py should block (got {code})')
        # Viktor 41715 MEDIUM: the quadratic assignment branch. Padding in the command or in the file must not carry
        # the gate past the hook limit; each case is decided in under 2 s, and a read behind the padding still blocks.
        w('eq.py', '=' * (1024 * 1024))
        w('eqs.py', '=/' * (512 * 1024))
        w('min.js', 'a=b;c=d;' * (300 * 1024 // 8))
        w('big.py', '=' * 200000 + '\n' + open(os.path.join(d, 'measure.py'), encoding='utf-8').read())
        # (the clean padding sits behind `; echo`: as python3's own word it would run past ARGS_WINDOW and block)
        timed = [
            ('python3 x ; echo ' + '=/' * 50000, 0),
            ('python3 x ; echo ' + '=' * 100000, 0),
            ('python3 x ' + '=/' * 50000, 2),
            ('python3 x ' + '=/' * 60000 + ' ; ' + S + ' dump-keychain', 2),
            ('python3 eq.py', 0), ('python3 eqs.py', 0), ('node min.js', 0), ('python3 big.py', 2),
        ]
        for cmd, want in timed:
            t = _t.monotonic()
            code, err = bash_in(cmd, d)
            took = _t.monotonic() - t
            if code != want or took > 2:
                fails.append(f'script: padding case {cmd[:24]!r}: want rc {want} under 2 s, got {code} in {took:.1f} s')
        # the watchdog: a slow scan is cut and blocks (not the hook timeout that would let it through)
        w('nl.sh', '\n' * (1024 * 1024))
        code, err = bash_env('bash nl.sh', d, {'KEYCHAIN_GATE_WATCHDOG_S': '0.01'})
        if code != 2 or 'watchdog' not in err:
            fails.append(f'script: watchdog 0.01 s on a 1 MB scan should block (got {code})')
        probe = probe.replace('script_budget', 'watchdog_s')
        for val, want in [('999', '6.0'), ('2', '2.0'), ('0', '0.001'), ('-1', '0.001'), ('nan', '6.0'), ('x', '6.0')]:
            p = subprocess.run([sys.executable, '-I', '-c', probe, HOOK], capture_output=True, text=True, timeout=20,
                               env={'PATH': '/usr/bin:/bin', 'KEYCHAIN_GATE_WATCHDOG_S': val})
            if p.stdout.strip() != want:
                fails.append(f'script: watchdog seam {val!r} -> {p.stdout.strip()!r}, want {want}')
        # Viktor 41756 INFO 4 (w5): the watchdog leaves with os._exit, which no except clause can catch (sys.exit's
        # SystemExit could be swallowed)
        probe_w = ('import importlib.util as u,sys; s=u.spec_from_file_location("g",sys.argv[1]); m=u.module_from_spec(s);'
                   ' s.loader.exec_module(m)\ntry:\n    m.on_watchdog(14, None)\nexcept BaseException:\n    print("caught")')
        p = subprocess.run([sys.executable, '-I', '-c', probe_w, HOOK], capture_output=True, text=True, timeout=20,
                           env={'PATH': '/usr/bin:/bin'})
        if p.returncode != 2 or 'caught' in p.stdout:
            fails.append(f'script: the watchdog exit must not be catchable (rc {p.returncode}, {p.stdout.strip()!r})')
        # Viktor 41756 LOW 1: words past MAX_ARGS (64), or a command past ARGS_WINDOW, block instead of going unread
        too_many = [
            ('python3 ' + '-B ' * 64 + 'measure.py', d),
            ('python3 ' + '-B ' * 12 + 'measure.py ' + 'a ' * 60, d),
            ('python3 ' + 'A' * 5000 + ' measure.py', d),
            ('python3 list.py ' + ' '.join(f'a{i}' for i in range(64)), d),
            ('cat ' + 'x ' * 70 + 'measure.py | python3', d),
        ]
        for cmd, cwd in too_many:
            code, err = bash_in(cmd, cwd)
            if code != 2 or 'script-too-many-args' not in err:
                fails.append(f'script: past MAX_ARGS/ARGS_WINDOW should block (got {code}): {cmd[:60]!r}')
        # Viktor 41756 INFO 4 (s1): past MAX_TRIES (4000) path lookups the gate blocks. 31 directories x 3 calls x
        # 60 missing words = 5580 lookups, no file found anywhere.
        code, err = bash_in('cd a && ' * 30 + ' ; '.join('python3 ' + ' '.join(f'm{j}' for j in range(60))
                                                          for _ in range(3)), d)
        if code != 2 or 'script-too-many' not in err:
            fails.append(f'script: past MAX_TRIES lookups should block (got {code})')
        # Viktor 41756 INFO 4 (s11): the per-call window keeps many calls linear (the rest of the text per call
        # was quadratic)
        t = _t.monotonic()
        code, _ = bash_in('python3 x;' * 30000, d)
        took = _t.monotonic() - t
        if took > 2:
            fails.append(f'script: 30 000 interpreter calls took {took:.1f} s (want under 2 s)')
        return fails, len(block) + len(allow) + 8 + 3 + len(timed) + 2 + 1 + len(too_many) + 2


def main():
    fails = []
    for cmd in map(fix, BLOCK):
        code, err = bash(cmd)
        if code != 2 or 'KULCSKARIKA-KAPU' not in err:
            fails.append(f'should block (got {code}): {cmd!r}')
        elif cmd in err or 'Claude Code-credentials' in err or 'example.test' in err:
            fails.append(f'block message echoes the command: {cmd!r}')
    for cmd in map(fix, ALLOW):
        code, err = bash(cmd)
        if code != 0:
            fails.append(f'should allow (got {code}): {cmd!r} {err[:120]}')
    # Not a Bash call / malformed input: allowed, never crashes.
    for payload in ['', 'not json', json.dumps({'tool_input': None}), json.dumps({'tool_input': {'command': None}}),
                    json.dumps({'tool_input': {'file_path': '/tmp/x'}}), json.dumps([1, 2])]:
        code, _ = run(payload)
        if code != 0:
            fails.append(f'non-Bash input should pass (got {code}): {payload!r}')
    # ReDoS (Viktor 30044): many ambiguous wrapper tokens before the call must still block, fast (the old POSITION
    # never returned at 26 x "env a=b ", and a hook that times out does not block).
    for cmd in [('env a=b ' * 30) + '; ' + fix('s3curity') + ' dump-keychain', ('env a=b ' * 60) + 'z',
                'echo ' + 'a=b ' * 2000,
                # card bc009036: runs of positions that rescanned the rest of the command (6 000 newlines took 10 s,
                # 12 000 " -exec" 112 s, 60 000 quotes 13 s before the fix)
                '\n' * 60000, ' -exec' * 12000, '"' * 60000, '\t\n' * 30000,
                '\n' * 30000 + fix('s3curity') + ' dump-keychain',
                # python -m parsing: long flag runs after an interpreter
                'python3' + ' -u' * 20000, ('python3 -m' + ' -x=a' * 10000), 'python3 -mx;' * 6000]:
        # 20 000 x " -u": past MAX_ARGS, so it blocks unread (Viktor 41756 LOW 1); the case still checks the time
        want = 2 if fix('s3curity') in cmd or cmd.startswith('python3 -u -u') else 0
        try:
            p = subprocess.run([sys.executable, '-I', HOOK], capture_output=True, text=True, timeout=5,
                               input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}}),
                               env={'PATH': '/usr/bin:/bin'})
            if p.returncode != want:
                fails.append(f'redos case: want {want}, got {p.returncode}: {cmd[:40]!r}...')
        except subprocess.TimeoutExpired:
            fails.append(f'redos case timed out (5 s): {cmd[:40]!r}...')
    script_fails, script_n = script_cases()
    fails += script_fails
    total = len(BLOCK) + len(ALLOW) + 6 + 11 + script_n
    for f in fails:
        print('FAIL', f)
    print(f'{total - len(fails)}/{total} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
