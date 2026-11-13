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
                       env={'PATH': '/usr/bin:/bin', 'LEDGER_DB_PATH': '/nonexistent/claudeclaw.db'},
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

# --- Viktor 40095 L1: a question is not an approval; the quote must stand in the ledger row -----------------------
INCIDENT_Q = 'PATRIK-KERTE: TG 18152 "nyilván kell egy repo, nem????"'
expect('NEG the incident question as the quote blocks', bash(f'gh repo create x --private  # {INCIDENT_Q}'), 2)


def ledger_run(cmd, rows):
    import sqlite3
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, 'claudeclaw.db')
        con = sqlite3.connect(db)
        con.execute('CREATE TABLE conversation_log (id INTEGER PRIMARY KEY, agent_id TEXT, chat_id TEXT, '
                    'direction TEXT, message_id TEXT, text TEXT, created_at INTEGER)')
        for mid, text in rows:
            con.execute("INSERT INTO conversation_log (agent_id, chat_id, direction, message_id, text, created_at) "
                        "VALUES ('main', '1', 'in', ?, ?, 0)", (mid, text))
        con.commit()
        con.close()
        p = subprocess.run([sys.executable, '-I', GATE], input=json.dumps(
            {'tool_name': 'Bash', 'tool_input': {'command': cmd}}), capture_output=True, text=True,
            env={'PATH': '/usr/bin:/bin', 'LEDGER_DB_PATH': db}, timeout=20)
        log = os.path.join(d, 'repo-create-gate.log')
        return p.returncode, (open(log).read() if os.path.exists(log) else '')


OKQ = 'PATRIK-KERTE: TG 18160 "csinálj egy privát repót sajat-rendszer néven"'
rc, _ = ledger_run(f'gh repo create x --private  # {OKQ}', [('18160', 'Csinálj  egy privát repót sajat-rendszer néven, köszi')])
expect('ledger row holds the quote -> passes', (rc, ''), 0)
rc, _ = ledger_run(f'gh repo create x --private  # {OKQ}', [('18160', 'nyilván kell egy repo, nem????')])
expect('NEG ledger row exists but the quote is not in it -> blocks', (rc, ''), 2)
rc, log = ledger_run(f'gh repo create x --private  # {OKQ}', [('99999', 'más üzenet')])
expect('id not in the ledger -> passes, and is logged', (rc if 'not in the ledger' in log else 99, ''), 0)

# --- Viktor 40095 L2: accidental paths ---------------------------------------------------------------------------
expect('NEG GraphQL createRepository blocks',
       bash("gh api graphql -f query='mutation{createRepository(input:{name:\"x\",visibility:PRIVATE}){repository{url}}}'"), 2)
expect('NEG Octokit createForAuthenticatedUser blocks',
       bash("node -e \"octokit.rest.repos.createForAuthenticatedUser({name:'x'})\""), 2)
expect('NEG Octokit request("POST /user/repos") blocks', bash("node -e \"octokit.request('POST /user/repos', {name:'x'})\""), 2)
expect('NEG trailing slash on the REST path blocks', bash('gh api -X POST /user/repos/ -f name=x'), 2)
with tempfile.TemporaryDirectory() as d:
    lst = os.path.join(d, 'mk2.py')
    with open(lst, 'w') as fh:
        fh.write('import subprocess\nsubprocess.run(["gh", "repo", "create", "x", "--private"])\n')
    os.chmod(lst, 0o755)
    expect('NEG subprocess list form in a file blocks', bash(f'python3 {lst}'), 2)
    expect('NEG direct ./script execution blocks', bash('./mk2.py', cwd=d), 2)
    expect('NEG npx tsx / source of a named file blocks', bash(f'npx tsx {lst}'), 2)

# --- talking about it is not doing it (5 of 8 hits on 7 days of real calls) ------------------------------------------
expect('a message that describes the gate passes',
       bash("bash agent-msg.sh kernel viktor - <<'MSG'\nA kapu blokkolja: gh repo create, POST user/repos.\nMSG"), 0)
expect('a hibanaplo line about the incident passes',
       bash("cat >> shared/hibanaplo.md <<'EOF'\n- Klodel gh repo create-del nyitott repót kérdésre.\nEOF"), 0)
expect('a commit message from a heredoc passes',
       bash("git commit -q -F - <<'EOF'\nfeat: block gh repo create and POST user/repos\nEOF"), 0)
expect('NEG a heredoc fed to python that creates a repo still blocks',
       bash("python3 - <<'PY'\nimport subprocess\nsubprocess.run(['gh','repo','create','x'])\nPY"), 2)
expect('NEG a heredoc fed to bash that creates a repo still blocks',
       bash("bash <<'SH'\ngh repo create x --private\nSH"), 2)

# --- Viktor 40174 MEDIUM: the heredoc body is dropped only for a known non-executing sink -------------------------------
expect('NEG cat heredoc piped to bash blocks', bash("cat <<'EOF' | bash\ngh repo create x --private\nEOF"), 2)
expect('NEG sh -c "$(cat heredoc)" blocks', bash("sh -c \"$(cat <<'EOF'\ngh repo create x --private\nEOF\n)\""), 2)
expect('NEG tee mk.sh heredoc then bash mk.sh blocks',
       bash("tee mk.sh <<'EOF'\ngh repo create x --private\nEOF\nbash mk.sh"), 2)
expect('NEG cat > notes.md heredoc then ./mk.sh blocks',
       bash("cat > notes.md <<'EOF'\ngh repo create x --private\nEOF\n./mk.sh"), 2)
expect('NEG gh api graphql --input - heredoc blocks',
       bash("gh api graphql --input - <<'EOF'\n{\"query\":\"mutation{createRepository(input:{name:\\\"x\\\"}){repository{url}}}\"}\nEOF"), 2)
expect('NEG cat > mk.sh (not a text sink) blocks', bash("cat > mk.sh <<'EOF'\ngh repo create x --private\nEOF"), 2)
expect('agent-msg.sh heredoc about the gate passes',
       bash("bash /Users/klodel/marveen/scripts/agent-msg.sh kernel viktor - <<'MSG'\nA kapu a gh repo create-et blokkolja.\nMSG"), 0)
expect('curl to /api/messages heredoc about the gate passes',
       bash("curl -s -X POST http://localhost:3420/api/messages --data-binary @- <<'JSON'\n"
            "{\"content\":\"gh repo create blokkolva\"}\nJSON"), 0)
expect('cd && cat >> notes.md heredoc about the gate passes (real 11-13 hibanaplo call)',
       bash("cd /x && cat >> shared/hibanaplo.md <<'EOF'\n- nyilván kell egy repo, gh repo create\nEOF"), 0)
expect('git add && git commit -F - heredoc passes (real 11-13 commit)',
       bash("git add -A x && git commit -q -F - <<'EOF'\nfeat: gh repo create needs Patrik\nEOF"), 0)
expect('NEG cd && cat heredoc | bash still blocks', bash("cd /x && cat <<'EOF' | bash\ngh repo create x\nEOF"), 2)
expect('NEG cat > notes.md heredoc && bash after the opener blocks',
       bash("cat > notes.md <<'EOF' && bash -c 'true'\ngh repo create x\nEOF"), 2)
expect('curl /api/messages heredoc with a closed $(cat token) header passes (real 11-13 Viktor call)',
       bash("curl -s -X PUT http://localhost:3420/api/messages/1 -H \"Authorization: Bearer $(cat t)\" "
            "--data-binary @- <<'JSON'\n{\"result\":\"gh repo create blokkolva\"}\nJSON"), 0)
with tempfile.TemporaryDirectory() as d:
    note = os.path.join(d, 'msg.txt')
    with open(note, 'w') as fh:
        fh.write('A kapu a gh repo create-et és a POST user/repos-t blokkolja.\n')
    expect('a message file fed to agent-msg.sh is not read as a run (real 11-13 Viktor call)',
           bash(f'bash /Users/klodel/marveen/scripts/agent-msg.sh kernel viktor - < {note}'), 0)
    expect('NEG the same file fed to bash still blocks', bash(f'bash < {note}'), 2)
    expect('NEG the same file as a curl payload to user/repos still blocks',
           bash(f'curl -s -X POST https://api.github.com/user/repos --data-binary @{note}'), 2)
expect('cat > report.md heredoc about the gate passes',
       bash("cat > reports/x.md <<'EOF'\nThe gate blocks gh repo create.\nEOF"), 0)
expect('grep for the phrase with "." as a path does not read every file',
       bash('diff . scripts/hooks/x.py; echo done'), 0)
with tempfile.TemporaryDirectory() as d:
    absf = os.path.join(d, 'mk3.py')
    with open(absf, 'w') as fh:
        fh.write('import subprocess\nsubprocess.run(["gh", "repo", "create", "x"])\n')
    os.chmod(absf, 0o755)
    expect('NEG an absolute-path script at command start blocks', bash(absf), 2)

# --- Viktor 40174 LOW: a quote cut before the question mark is still a question ------------------------------------
QQ = 'PATRIK-KERTE: TG 18152 "nyilván kell egy repo"'
rc, _ = ledger_run(f'gh repo create x --private  # {QQ}', [('18152', 'nyilván kell egy repo, nem????')])
expect('NEG quote cut before "?" in a question row blocks', (rc, ''), 2)
QS = 'PATRIK-KERTE: TG 18153 "csinálj egy repót sajat néven"'
rc, _ = ledger_run(f'gh repo create x --private  # {QS}', [('18153', 'Csinálj egy repót sajat néven. Utána mi jön?')])
expect('a statement followed by a separate question passes', (rc, ''), 0)

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
