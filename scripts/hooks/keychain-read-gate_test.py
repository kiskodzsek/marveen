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

BLOCK = [
    'security find-generic-password -s "Claude Code-credentials" -w',
    'security find-internet-password -s example.test',
    'security dump-keychain',
    'security dump-keychain -d login.keychain-db',
    'security export -k login.keychain -t certs -o /tmp/x.p12',
    '/usr/bin/security dump-keychain',
    'SECURITY find-generic-password -s x',
    'security -q find-generic-password -s x',
    'env -i security dump-keychain',
    'env FOO=bar PATH=/usr/bin security export',
    'sudo security find-generic-password -s x',
    'FOO=1 security find-internet-password -s x',
    'xargs security dump-keychain < /dev/null',
    'ls; security dump-keychain',
    'ls && security export -o x',
    'true || security find-generic-password -w -s x',
    'cat a | security dump-keychain',
    'x=$(security find-generic-password -w -s y); echo ok',
    'echo `security find-generic-password -w -s y`',
    'bash -c "security dump-keychain"',
    "sh -c 'security find-generic-password -s x -w'",
    'ssh host \'security dump-keychain\'',
    'sec\\urity dump-keychain',
    "sec''urity dump-keychain",
    'security \\\n  dump-keychain',
    'echo dump-keychain | security -i',
    'security -p "> " < cmds.txt',
    '( security dump-keychain )',
    'if true; then\nsecurity export\nfi',
]

ALLOW = [
    'ls -la',
    'security list-keychains',
    'security find-identity -p codesigning -v',
    'security find-certificate -a -c Apple',
    'security show-keychain-info login.keychain',
    'security -v list-keychains',
    'export FOO=1',
    'echo export',
    'grep -n find-generic-password notes.md',
    'git commit -m "fix: security export docs"',
    'echo "the security team"',
    'npm audit --security',
    'python3 security_check.py dump-keychain-list',
    'security find-generic-password-helper',
    'node scripts/security-review.mjs',
]


def run(payload):
    env = {'PATH': '/usr/bin:/bin'}
    p = subprocess.run([sys.executable, '-I', HOOK], input=payload, capture_output=True, text=True, env=env,
                       timeout=20)
    return p.returncode, p.stderr


def bash(cmd):
    return run(json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}}))


def main():
    fails = []
    for cmd in BLOCK:
        code, err = bash(cmd)
        if code != 2 or 'KULCSKARIKA-KAPU' not in err:
            fails.append(f'should block (got {code}): {cmd!r}')
        elif cmd in err or 'Claude Code-credentials' in err or 'example.test' in err:
            fails.append(f'block message echoes the command: {cmd!r}')
    for cmd in ALLOW:
        code, err = bash(cmd)
        if code != 0:
            fails.append(f'should allow (got {code}): {cmd!r} {err[:120]}')
    # Not a Bash call / malformed input: allowed, never crashes.
    for payload in ['', 'not json', json.dumps({'tool_input': None}), json.dumps({'tool_input': {'command': None}}),
                    json.dumps({'tool_input': {'file_path': '/tmp/x'}}), json.dumps([1, 2])]:
        code, _ = run(payload)
        if code != 0:
            fails.append(f'non-Bash input should pass (got {code}): {payload!r}')
    total = len(BLOCK) + len(ALLOW) + 6
    for f in fails:
        print('FAIL', f)
    print(f'{total - len(fails)}/{total} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
