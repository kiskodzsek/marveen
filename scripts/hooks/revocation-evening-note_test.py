#!/usr/bin/env python3
"""Tests for revocation-evening-note.py and scripts/lib/este_blokk.py (card 7702bb13).

Runs the hook as Claude Code does (PostToolUse JSON on stdin) against a temp evening block (ESTE_BLOKK_PATH).
Nothing is executed; the commands are only text. Run: python3 -I scripts/hooks/revocation-evening-note_test.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, 'revocation-evening-note.py')
CLI = os.path.join(os.path.dirname(HERE), 'este-blokk-add.py')

NOTE = [  # (command, the phrase the item must carry)
    ('CLAUDE_CONFIG_DIR=agents/dave/.claude-config claude mcp logout higgsfield', 'claude mcp logout higgsfield'),
    ('claude mcp remove -s user higgsfield', 'claude mcp remove higgsfield'),
    ('claude mcp remove --verbose higgsfield', 'claude mcp remove higgsfield'),
    ('claude logout', 'claude logout'),
    ('gh auth logout', 'gh logout'),
    ('npx vercel logout', 'vercel logout'),
    ('vercel logout --scope x', 'vercel logout'),
    ('supabase logout', 'supabase logout'),
    ('op signout', 'op signout'),
    ('gcloud auth revoke', 'gcloud revoke'),
    ('aws sso logout', 'aws logout'),
    ('security delete-generic-password -s "Claude Code-credentials"', 'delete-generic-password -s Claude Code-credentials'),
    ('/usr/bin/security delete-internet-password -s example.test', 'delete-internet-password -s example.test'),
    ('git credential-osxkeychain erase', 'git credential erase'),
    ('curl -s -X POST https://api.example.test/oauth/revoke -d token=abc', 'HTTP revoke (api.example.test)'),
    ("bash -c 'gh auth logout'", 'gh logout'),
    ('ls && claude logout', 'claude logout'),
    ('timeout 30 gh auth logout', 'gh logout'),
    ('sudo env A=1 docker logout', 'docker logout'),
    ("bash <<'E'\ngh auth logout\nE", 'gh logout'),
    ('cd /tmp\nnpm logout', 'npm logout'),
]
QUIET = [
    'git commit -m "fix: gh auth logout docs"',
    "cat <<'E'\ngh auth logout\nclaude mcp logout higgsfield\nE",
    'grep -n "claude mcp logout" notes.md',
    'echo claude mcp logout x',
    'claude mcp list',
    'claude mcp get higgsfield',
    'gh auth status',
    'vercel deploy --prebuilt',
    'git credential fill',
    'curl -s https://api.example.test/v1/logouts.json',
    'ls -la',
]


def run_hook(cmd, path, cwd=None, tool='Bash', raw=None, env_extra=None):
    payload = raw if raw is not None else json.dumps(
        {'tool_name': tool, 'tool_input': {'command': cmd}, **({'cwd': cwd} if cwd else {})})
    env = {'PATH': '/usr/bin:/bin', 'ESTE_BLOKK_PATH': path, **(env_extra or {})}
    p = subprocess.run([sys.executable, '-I', HOOK], input=payload, capture_output=True, text=True, env=env,
                       timeout=20)
    return p.returncode


def items(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def main():
    fails = []
    n = 0
    with tempfile.TemporaryDirectory() as d:
        for i, (cmd, phrase) in enumerate(NOTE):
            n += 1
            path = os.path.join(d, f'n{i}.json')
            rc = run_hook(cmd, path, cwd='/Users/x/marveen/agents/kernel')
            got = items(path)
            if rc != 0 or len(got) != 1 or phrase not in got[0].get('mi', ''):
                fails.append(f'should note {phrase!r}: rc {rc}, {got!r}'[:300])
            elif got[0].get('agens') != 'kernel' or got[0].get('tipus') != 'visszavonas' or got[0].get('auto') is not True:
                fails.append(f'item fields wrong: {got[0]!r}'[:300])
        # whose config: CLAUDE_CONFIG_DIR names it
        n += 1
        got = items(os.path.join(d, 'n0.json'))
        if not got or 'dave configjában' not in got[0]['mi']:
            fails.append(f'config owner missing: {got!r}'[:300])
        for i, cmd in enumerate(QUIET):
            n += 1
            path = os.path.join(d, f'q{i}.json')
            rc = run_hook(cmd, path)
            if rc != 0 or items(path):
                fails.append(f'should stay quiet: {cmd[:60]!r} -> rc {rc}, {items(path)!r}'[:300])
        # the command is never copied: a token in it does not reach the file
        n += 1
        path = os.path.join(d, 's.json')
        run_hook('curl -H "Authorization: Bearer SECRETTOKEN123" https://id.example.test/oauth2/revoke?token=SECRET2', path)
        body = open(path, encoding='utf-8').read() if os.path.exists(path) else ''
        if 'SECRET' in body or 'revoke' not in body:
            fails.append(f'secret leaked or item missing: {body[:200]!r}')
        # not a Bash call, malformed input: exit 0, nothing written
        for raw in ['', 'not json', json.dumps([1]), json.dumps({'tool_name': 'Bash', 'tool_input': None})]:
            n += 1
            path = os.path.join(d, 'm.json')
            if run_hook(None, path, raw=raw) != 0 or items(path):
                fails.append(f'malformed input should pass quietly: {raw!r}')
        n += 1
        path = os.path.join(d, 'r.json')
        if run_hook('gh auth logout', path, tool='Read') != 0 or items(path):
            fails.append('a non-Bash tool should not note')
        # the agent: from the cwd, else the main agent
        n += 1
        path = os.path.join(d, 'a.json')
        run_hook('gh auth logout', path, cwd='/Users/x/marveen')
        got = items(path)
        if not got or got[0]['agens'] != 'fő ágens':
            fails.append(f'agent without agents/<name> should be the main agent: {got!r}')
        # same item, same day: once; existing items are kept; mode is kept
        n += 1
        path = os.path.join(d, 'k.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump([{'tema': 'kézi tétel'}], f)
        os.chmod(path, 0o644)
        run_hook('gh auth logout', path, cwd='/Users/x/marveen/agents/kernel')
        run_hook('gh auth logout', path, cwd='/Users/x/marveen/agents/kernel')
        got = items(path)
        if len(got) != 2 or got[0] != {'tema': 'kézi tétel'}:
            fails.append(f'dedupe or keep failed: {got!r}'[:300])
        if os.stat(path).st_mode & 0o777 != 0o644:
            fails.append(f'mode not kept: {oct(os.stat(path).st_mode & 0o777)}')
        # a file that is not a JSON list is left untouched; the item is parked
        n += 1
        path = os.path.join(d, 'bad.json')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('{"kézzel": "elrontva"')
        run_hook('gh auth logout', path)
        if open(path, encoding='utf-8').read() != '{"kézzel": "elrontva"' or not os.path.exists(path + '.hiba.jsonl'):
            fails.append('a broken block must stay untouched and the item go to .hiba.jsonl')
        # 40 hooks at once, each with its input already on stdin (a file), so they really run together: none
        # drops another's item (flock + os.replace)
        n += 1
        path = os.path.join(d, 'c.json')
        env = {'PATH': '/usr/bin:/bin', 'ESTE_BLOKK_PATH': path}
        ins = []
        for i in range(40):
            fp = os.path.join(d, f'in{i}.json')
            with open(fp, 'w', encoding='utf-8') as f:
                json.dump({'tool_name': 'Bash', 'tool_input': {'command': f'claude mcp logout srv{i}'}}, f)
            ins.append(open(fp, encoding='utf-8'))
        procs = [subprocess.Popen([sys.executable, '-I', HOOK], stdin=fh, env=env) for fh in ins]
        for p in procs:
            p.wait(timeout=60)
        for fh in ins:
            fh.close()
        if len(items(path)) != 40:
            fails.append(f'concurrent writers lost items: {len(items(path))}/40')
        # long inputs decide fast (bounded runs; ReDoS)
        for cmd in ['env a=b ' * 20000 + 'x', 'curl ' + 'a' * 100000, "<<'E'\n" * 10000, ' -c "' * 20000,
                    'claude mcp logout' + ' -x' * 20000, 'security delete-generic-password' + ' a' * 50000,
                    'curl https://x/' + 'a/' * 50000]:
            n += 1
            t = time.monotonic()
            rc = run_hook(cmd, os.path.join(d, 'redos.json'))
            took = time.monotonic() - t
            if rc != 0 or took > 2:
                fails.append(f'slow or failing on {cmd[:30]!r}: rc {rc} in {took:.1f} s')
        # the CLI for scripts
        n += 1
        path = os.path.join(d, 'cli.json')
        env = {'PATH': '/usr/bin:/bin', 'ESTE_BLOKK_PATH': path}
        p = subprocess.run([sys.executable, '-I', CLI, '--mi', 'Higgsfield MCP kijelentkeztetve', '--forras',
                            'higgsfield-gate', '--agens', 'kernel'], capture_output=True, text=True, env=env, timeout=20)
        got = items(path)
        if p.returncode != 0 or p.stdout.strip() != 'added' or len(got) != 1 or got[0]['forras'] != 'higgsfield-gate':
            fails.append(f'CLI add failed: rc {p.returncode} {p.stdout!r} {got!r}'[:300])
        n += 1
        p = subprocess.run([sys.executable, '-I', CLI, '--mi', ' ', '--forras', 'x'], capture_output=True, text=True,
                           env=env, timeout=20)
        if p.returncode != 2 or len(items(path)) != 1:
            fails.append(f'CLI with an empty --mi should exit 2 and write nothing (rc {p.returncode})')
    for f in fails:
        print('FAIL', f)
    print(f'{n - len(fails)}/{n} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
