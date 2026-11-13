#!/usr/bin/env python3
"""Tests of repo-create-gate.py. Run: python3 -I scripts/hooks/repo-create-gate_test.py

Negative cases first: every way a repository was or could be created (the Klodel 40048 incident: a question,
"nyilván kell egy repo, nem????", TG 18152, answered by creating a repository) must block without the
PATRIK-KERTE line; reads, unrelated commands and approved creations pass.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, 'repo-create-gate.py')
OK_LINE = 'PATRIK-KERTE: TG 18160 "csinálj egy privát repót sajat-rendszer néven"'
FAILS = []


def run(payload):
    p = subprocess.run([sys.executable, '-I', GATE], input=json.dumps(payload), capture_output=True, text=True,
                       timeout=20)
    return p.returncode, p.stderr


def bash(cmd, desc='', cwd=None):
    payload = {'tool_name': 'Bash', 'tool_input': {'command': cmd, 'description': desc}}
    if cwd:
        payload['cwd'] = cwd
    return run(payload)


def expect(name, got, want):
    rc = got[0]
    if rc != want:
        FAILS.append(f'{name}: rc={rc}, want {want}; stderr={got[1][:200]!r}')
    else:
        print(f'ok   {name}')


# --- NEGATIVE: creation without Patrik's words blocks ------------------------------------------------------
expect('gh repo create blocks', bash('gh repo create klodeldev/sajat-rendszer --private --source . --push'), 2)
expect('gh repo fork blocks', bash('gh repo fork someone/thing --clone'), 2)
expect('curl POST user/repos blocks',
       bash('curl -s -X POST -H "Authorization: Bearer $T" https://api.github.com/user/repos -d \'{"name":"x"}\''), 2)
expect('curl --json orgs/x/repos blocks',
       bash('curl -s https://api.github.com/orgs/acme/repos --json \'{"name":"x","private":true}\''), 2)
expect('gh api -f user/repos blocks', bash('gh api user/repos -f name=sajat-rendszer -F private=true'), 2)
expect('gh api --method POST forks blocks', bash('gh api --method POST repos/a/b/forks'), 2)
expect('python -c requests.post blocks',
       bash('python3 -c "import requests; requests.post(\'https://api.github.com/user/repos\', json={\'name\':\'x\'})"'), 2)
expect('a question is not an order (quote without TG id) blocks',
       bash('gh repo create x --private', desc='Patrik: "nyilván kell egy repo, nem????"'), 2)
expect('PATRIK-KERTE with a too short quote blocks',
       bash('gh repo create x --private', desc='PATRIK-KERTE: TG 18152 "kell repo"'), 2)

with tempfile.TemporaryDirectory() as d:
    script = os.path.join(d, 'mk.py')
    with open(script, 'w') as fh:
        fh.write("import urllib.request, json\n"
                 "req = urllib.request.Request('https://api.github.com/user/repos', method='POST',\n"
                 "    data=json.dumps({'name': 'x'}).encode())\nurllib.request.urlopen(req)\n")
    expect('python3 <script file> creating a repo blocks', bash(f'python3 {script}'), 2)
    expect('relative script path with cwd blocks', bash('python3 -I mk.py', cwd=d), 2)
    body = os.path.join(d, 'body.json')
    with open(body, 'w') as fh:
        fh.write('{"name":"x"}')
    expect('curl --data-binary @file to user/repos blocks',
           bash(f'curl -s https://api.github.com/user/repos --data-binary @{body}'), 2)
    # approved through the script itself
    with open(script, 'a') as fh:
        fh.write(f'# {OK_LINE}\n')
    expect('script carrying the PATRIK-KERTE line passes', bash(f'python3 {script}'), 0)

expect('MCP create_repository blocks', run({'tool_name': 'mcp__github__create_repository',
                                            'tool_input': {'name': 'x', 'private': True}}), 2)
expect('MCP fork_repository blocks', run({'tool_name': 'mcp__gh__fork_repository',
                                          'tool_input': {'owner': 'a', 'repo': 'b'}}), 2)

# --- POSITIVE: approved creations, reads and unrelated commands pass ---------------------------------------
expect('gh repo create with PATRIK-KERTE in the command passes',
       bash(f'gh repo create x --private  # {OK_LINE}'), 0)
expect('gh repo create with PATRIK-KERTE in the description passes',
       bash('gh repo create x --private', desc=OK_LINE), 0)
expect('MCP create with PATRIK-KERTE in the input passes',
       run({'tool_name': 'mcp__github__create_repository', 'tool_input': {'name': 'x', 'description': OK_LINE}}), 0)
expect('listing user/repos (GET) passes', bash('gh api user/repos --paginate -q ".[].full_name"'), 0)
expect('curl GET user/repos passes', bash('curl -s -H "Authorization: Bearer $T" https://api.github.com/user/repos'), 0)
expect('gh repo view passes', bash('gh repo view klodeldev/sajat-rendszer --json name'), 0)
expect('gh pr create passes', bash('gh pr create --title t --body b'), 0)
expect('git push passes', bash('git push -u origin feat/x'), 0)
expect('a POST to another endpoint passes', bash('gh api --method POST repos/a/b/issues -f title=t'), 0)
expect('non-Bash tool passes', run({'tool_name': 'Read', 'tool_input': {'file_path': '/tmp/x'}}), 0)
expect('malformed stdin fails open', (subprocess.run([sys.executable, '-I', GATE], input='not json',
                                                     capture_output=True, text=True).returncode, ''), 0)

if FAILS:
    print('\nFAILED:\n' + '\n'.join(FAILS))
    sys.exit(1)
print('\nall passed')
