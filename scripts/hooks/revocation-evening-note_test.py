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
DRAIN = os.path.join(os.path.dirname(HERE), 'este-blokk-drain.py')
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'lib'))
import este_blokk  # noqa: E402
ERRLOG = os.path.join(tempfile.mkdtemp(), 'hook-errors.log')  # never the install's store/hook-errors.log
# the fake key in the secret cases, assembled at run time
KEY = 'sk_' + 'live_' + 'Ab12Cd34Ef56Gh78'
KEY2 = 'Xq7' + 'Lm2Pz9'  # mixed case and digits, no known prefix, no 4-digit run

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
    ('gh \\\n  auth logout', 'gh logout'),
    ('cat <<< hi\ngh auth logout', 'gh logout'),  # a here-string is not a heredoc: the next line runs
    ("cat <<'E'\nnotes\nE\nclaude logout", 'claude logout'),  # after the terminator the commands run again  # backslash-newline joins the line
    # Viktor 41840 LOW 1: no secret in the phrase
    ('security delete-generic-password -s "free text with spaces"', 'delete-generic-password -s <megadva>'),
    ('claude mcp remove ' + KEY, 'claude mcp remove <név nem ismert>'),
    ('curl -X POST https://' + KEY + ':@api.example.test/v1/oauth/revoke', 'HTTP revoke (host rejtve'),
    ('security delete-generic-password -s ' + KEY, 'delete-generic-password -s <megadva>'),
    ('security delete-generic-password -s ' + KEY2, 'delete-generic-password -s <megadva>'),
    ('claude mcp logout github-dave', 'claude mcp logout github-dave'),
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
    'cat <<E\nnotes\ngh auth logout',  # an unterminated heredoc: its body is the rest of the text (as in bash)
    'x' * 100000 + '\ngh auth logout',  # past MAX_CMD: not read (documented limit, keeps the hook fast)
]


def run_hook(cmd, path, cwd=None, tool='Bash', raw=None, env_extra=None):
    payload = raw if raw is not None else json.dumps(
        {'tool_name': tool, 'tool_input': {'command': cmd}, **({'cwd': cwd} if cwd else {})})
    env = {'PATH': '/usr/bin:/bin', 'ESTE_BLOKK_PATH': path, 'HOOK_ERRLOG_PATH': ERRLOG,
           'REVOCATION_MCP_CONFIGS': '', **(env_extra or {})}
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
        # Viktor 41840 LOW 1: the fake key never reaches the file, in any of its forms
        for cmd in [c for c, _ in NOTE if KEY in c or KEY2 in c] + ['curl https://u:' + KEY + '@h.example.test/revoke',
                                                       "security delete-internet-password -s '" + KEY + "'"]:
            n += 1
            path = os.path.join(d, 'k%d.json' % n)
            run_hook(cmd, path)
            body = open(path, encoding='utf-8').read() if os.path.exists(path) else ''
            if 'live' in body or 'Ab12' in body or KEY2 in body or not body:
                fails.append(f'key leaked or item missing: {cmd[:40]!r} -> {body[:200]!r}')
        # a server name the configs know is written even when its shape is not the safe one; others are not
        n += 1
        cfg = os.path.join(d, 'mcp.json')
        with open(cfg, 'w', encoding='utf-8') as f:
            json.dump({'mcpServers': {'plugin_telegram_X1': {}}, 'projects': {'/p': {'mcpServers': {'Higgs_2026': {}}}}}, f)
        for name, want in [('plugin_telegram_X1', 'plugin_telegram_X1'), ('Higgs_2026', 'Higgs_2026'),
                           ('Other_2026', '<név nem ismert>')]:
            path = os.path.join(d, f'mk{name}.json')
            run_hook('claude mcp remove ' + name, path, env_extra={'REVOCATION_MCP_CONFIGS': cfg})
            got = items(path)
            if not got or f'claude mcp remove {want}' not in got[0]['mi']:
                fails.append(f'known mcp name {name!r}: want {want!r}, got {got!r}'[:300])
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
        # Viktor 41840 LOW 5: the agent is CLAUDE_CONFIG_DIR's, the cwd only a fallback
        n += 1
        path = os.path.join(d, 'cfgagent.json')
        run_hook('gh auth logout', path, cwd='/Users/x/marveen/agents/dave/repos/wt',
                 env_extra={'CLAUDE_CONFIG_DIR': '/Users/x/marveen/agents/kernel/.claude-config'})
        got = items(path)
        if not got or got[0]['agens'] != 'kernel':
            fails.append(f'agent should come from CLAUDE_CONFIG_DIR: {got!r}'[:300])
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
        # Viktor 41840 LOW 3: the parked item and a failed write are in the hook error log, not only on stderr
        n += 1
        log = open(ERRLOG, encoding='utf-8').read() if os.path.exists(ERRLOG) else ''
        if 'hiba.jsonl' not in log:
            fails.append(f'a parked item should be in the hook error log: {log[-200:]!r}')
        n += 1
        ro = os.path.join(d, 'ro')
        os.makedirs(ro)
        os.chmod(ro, 0o500)
        try:
            run_hook('gh auth logout', os.path.join(ro, 'b.json'))
            log = open(ERRLOG, encoding='utf-8').read() if os.path.exists(ERRLOG) else ''
            if 'PermissionError' not in log or 'nem került a blokkba' not in log:
                fails.append(f'a write that fails should reach the hook error log: {log[-200:]!r}')
        finally:
            os.chmod(ro, 0o700)
        # malformed input is not an error worth a line
        n += 1
        before = open(ERRLOG, encoding='utf-8').read()
        run_hook(None, os.path.join(d, 'm2.json'), raw='not json')
        if open(ERRLOG, encoding='utf-8').read() != before:
            fails.append('malformed hook input should not write the error log')
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
        # long inputs decide fast (bounded runs; ReDoS; Viktor 41840 INFO 6: unterminated heredocs, MAX_CMD)
        for cmd in ["cat <<E\n" * 20000, "bash <<'E'\n" * 20000, 'gh auth logout ' * 30000,'env a=b ' * 20000 + 'x', 'curl ' + 'a' * 100000, "<<'E'\n" * 10000, ' -c "' * 20000,
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
        n += drain_cases(d, fails)
        n += lib_cases(d, fails)
    for f in fails:
        print('FAIL', f)
    print(f'{n - len(fails)}/{n} passed')
    return 1 if fails else 0


def drain_cases(d, fails):
    """Viktor 41840 LOW 2-3: drain() takes everything under the writers' lock and returns the parked items too."""
    n = 0
    path = os.path.join(d, 'dr.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump([{'tema': 'kézi'}], f)
    os.chmod(path, 0o640)
    with open(path + '.hiba.jsonl', 'w', encoding='utf-8') as f:
        f.write(json.dumps({'mi': 'parkolt tétel'}) + '\nnem json\n\n[1]\n')
    env = {'PATH': '/usr/bin:/bin', 'ESTE_BLOKK_PATH': path}
    p = subprocess.run([sys.executable, '-I', DRAIN], capture_output=True, text=True, env=env, timeout=20)
    n += 1
    try:
        out = json.loads(p.stdout)
    except ValueError:
        out = {}
    if (p.returncode != 0 or out.get('tetelek') != [{'tema': 'kézi'}] or out.get('parkolt') != [{'mi': 'parkolt tétel', 'parkolt': True}]
            or out.get('olvashatatlan_sor') != 2 or out.get('hibas_fajl') is not False):
        fails.append(f'drain CLI output wrong: rc {p.returncode} {p.stdout[:300]!r}')
    n += 1
    if items(path) != [] or os.path.exists(path + '.hiba.jsonl') or os.stat(path).st_mode & 0o777 != 0o640:
        fails.append('after drain the block should be [] (mode kept) and the .hiba.jsonl gone')
    n += 1
    try:
        saved = json.load(open(path + '.utolso-drain.json', encoding='utf-8'))
    except (OSError, ValueError):
        saved = {}
    if saved.get('tetelek') != [{'tema': 'kézi'}]:
        fails.append(f'the drained items should be kept in .utolso-drain.json: {saved!r}'[:200])
    n += 1  # an empty block: nothing taken, nothing written
    p = subprocess.run([sys.executable, '-I', DRAIN], capture_output=True, text=True, env=env, timeout=20)
    if p.returncode != 0 or json.loads(p.stdout).get('tetelek') != []:
        fails.append(f'drain of an empty block: {p.stdout[:200]!r}')
    n += 1  # a broken block is left for a person
    bad = os.path.join(d, 'drbad.json')
    with open(bad, 'w', encoding='utf-8') as f:
        f.write('{"x": ')
    out = este_blokk.drain(bad)
    if not out['hibas_fajl'] or open(bad, encoding='utf-8').read() != '{"x": ':
        fails.append(f'drain should leave a broken block untouched: {out!r}')
    n += 1  # drain while 80 writers run: every item is either drained or still in the block, none lost or doubled
    path = os.path.join(d, 'drc.json')
    env = {'PATH': '/usr/bin:/bin', 'ESTE_BLOKK_PATH': path, 'HOOK_ERRLOG_PATH': ERRLOG, 'REVOCATION_MCP_CONFIGS': ''}
    ins = []
    for i in range(80):
        fp = os.path.join(d, f'dri{i}.json')
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump({'tool_name': 'Bash', 'tool_input': {'command': f'claude mcp logout srv{i}x'}}, f)
        ins.append(open(fp, encoding='utf-8'))
    procs = [subprocess.Popen([sys.executable, '-I', HOOK], stdin=fh, env=env) for fh in ins]
    drained = []
    deadline = time.monotonic() + 60
    while any(pr.poll() is None for pr in procs) and time.monotonic() < deadline:  # drain all the time they write
        drained += este_blokk.drain(path)['tetelek']
    for pr in procs:
        pr.wait(timeout=60)
    for fh in ins:
        fh.close()
    drained += este_blokk.drain(path)['tetelek']
    mis = sorted(x['mi'] for x in drained)
    if len(mis) != 80 or len(set(mis)) != 80:
        fails.append(f'drain during writes lost or doubled items: {len(mis)} taken, {len(set(mis))} distinct')
    return n


def lib_cases(d, fails):
    """Mutant survivors (Viktor 41840 INFO 7): dedupe day and agent, text cleaning and cap, temp-file cleanup."""
    import datetime
    n = 0
    path = os.path.join(d, 'lib.json')
    day1, day2 = datetime.datetime(2026, 11, 14, 9, 0), datetime.datetime(2026, 11, 15, 9, 0)
    r = [este_blokk.add_item('t', 'same', 'f', agens='a', path=path, now=day1),
         este_blokk.add_item('t', 'same', 'f', agens='a', path=path, now=day1),
         este_blokk.add_item('t', 'same', 'f', agens='a', path=path, now=day2),
         este_blokk.add_item('t', 'same', 'f', agens='b', path=path, now=day1)]
    n += 1
    if r != ['added', 'duplicate', 'added', 'added'] or len(items(path)) != 3:
        fails.append(f'dedupe should key on day and agent: {r!r}')
    n += 1
    este_blokk.add_item('t', 'a\x00b\n\tc   d' + 'x' * 400, 'f', path=path, now=day1)
    mi = items(path)[-1]['mi']
    if not mi.startswith('a b c d') or len(mi) != 300 or not mi.endswith('…'):
        fails.append(f'text should be cleaned and capped at 300: {mi[:40]!r} len {len(mi)}')
    n += 1
    before = set(os.listdir(d))
    try:
        este_blokk._atomic_write(os.path.join(d, 'x.json'), [object()])
    except TypeError:
        pass
    left = [f for f in set(os.listdir(d)) - before if f.startswith('.patrik-este-blokk.')]
    if left:
        fails.append(f'a failed write should remove its temp file: {left!r}')
    return n


if __name__ == '__main__':
    sys.exit(main())
