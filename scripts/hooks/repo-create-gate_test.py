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
import time

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, 'repo-create-gate.py')
OK_LINE = 'PATRIK-KERTE: TG 18160 "csinálj egy privát repót sajat-rendszer néven"'
FAILS = []


def run(payload):
    try:
        p = subprocess.run([sys.executable, '-I', GATE], input=json.dumps(payload), capture_output=True, text=True,
                           env={'PATH': '/usr/bin:/bin', 'LEDGER_DB_PATH': '/nonexistent/claudeclaw.db'},
                           timeout=20)
    except subprocess.TimeoutExpired:
        return None, 'TIMEOUT after 20 s (the 10 s hook timeout would let the call through)'
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
        if not os.path.exists(log):
            return p.returncode, ''
        with open(log) as fh:
            return p.returncode, fh.read()


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

# --- Card 3b05ae69 (Viktor 50005/50006): a padded creation must block, and well before the 10 s hook timeout -------
# A timed-out hook does not block. On main these shapes ran 4.6-21 s (quadratic heredoc search, unanchored [\w-]*,
# every `gh api` / `urlopen(` / `curl` start reading on to the line end); each must now block in under 2 s
# (Viktor 50036).
import time  # noqa: E402

CREATE = 'gh repo create kiskodzsek/x --private'


def timed(name, cmd, want, limit=2.0):
    t0 = time.time()
    got = bash(cmd)
    dt = time.time() - t0
    expect(name, got, want)
    if dt > limit:
        FAILS.append(f'{name}: {dt:.2f} s, limit {limit} s')


PAD = 'cat <<E\n' * 37500  # 300 KB
timed('NEG creation then 300 KB of `cat <<E` lines blocks in time (Viktor shape)', CREATE + '\n' + PAD, 2)
timed('NEG 200 KB of `cat <<E` lines then the creation blocks in time', 'cat <<E\n' * 25000 + CREATE, 2)
timed('NEG a 200 KB word run then the creation blocks in time', 'x' + 'a' * 200000 + '\n' + CREATE, 2)
timed('NEG a 200 KB `-a-a` run then the creation blocks in time', '-a' * 100000 + '\n' + CREATE, 2)
timed('NEG 30000 `gh api ` without a field, then -X POST to user/repos, blocks in time',
      'gh api ' * 30000 + 'curl -X POST https://api.github.com/user/repos', 2)
timed('NEG 30000 `urlopen(` without data=, then -X POST to user/repos, blocks in time',
      'urlopen(' * 30000 + 'curl -X POST https://api.github.com/user/repos', 2)
timed('NEG 20000 `git commit ` on a heredoc head line, body creates, blocks in time',
      'git commit ' * 20000 + "x <<'E'\n" + CREATE + '\nE', 2)
# main read every `curl` start on to the segment end: 1 s at 30000, so 50000 against a 1 s limit (new: ~0.02 s)
timed('NEG 50000 `curl ` in one segment then the creation blocks in time', 'curl ' * 50000 + '\n' + CREATE, 2, 1.0)
timed('NEG 30000 `.tee` on a heredoc head line, body creates, blocks in time',
      'echo ' + '.tee' * 30000 + " <<'E'\n" + CREATE + '\nE', 2)
timed('a 200 KB message heredoc into agent-msg.sh that talks about creation passes in time',
      "bash scripts/agent-msg.sh kernel viktor - <<'MSG'\n" + ('a ' + CREATE + '\n') * 4000 + 'MSG', 0)

# --- A body dropped into a sink must be what bash reads as the body (Kernel 50035): on main each of these was ALLOW,
# and bash ran the creation (measured with echo). The gate now finds heredocs as bash quotes the command.
expect('NEG B1 an empty heredoc body, then the creation, blocks', bash(f"cat > n.md <<'E'\nE\n{CREATE}\nE"), 2)
expect("NEG B2 delimiter E'X' (bash: EX) blocks", bash(f"cat > n.md <<E'X'\nEX\n{CREATE}\nE"), 2)
expect('NEG B2b delimiter E-1 blocks', bash(f'cat > n.md <<E-1\nE-1\n{CREATE}\nE'), 2)
expect('NEG B3 a here-string into agent-msg.sh is no heredoc', bash(f'bash scripts/agent-msg.sh k v - <<<E\n{CREATE}\nE'), 2)
expect('NEG B3b a here-string into a dashboard curl is no heredoc',
       bash(f'curl -s -X POST localhost:3420/api/messages -d @- <<<E\n{CREATE}\nE'), 2)
expect('NEG B4 an opener inside double quotes is no heredoc', bash(f'bash scripts/agent-msg.sh k v "x <<E y"\n{CREATE}\nE'), 2)
expect('NEG B4b an opener inside single quotes is no heredoc', bash(f"bash scripts/agent-msg.sh k v 'x <<E y'\n{CREATE}\nE"), 2)
expect('NEG B5 an opener in a comment is no heredoc', bash(f'bash scripts/agent-msg.sh k v x # <<E\n{CREATE}\nE'), 2)
expect('NEG B6 an opener line continued by a backslash blocks', bash(f"cat > n.md <<'E' \\\n; {CREATE}\nbody\nE"), 2)
expect('NEG B7 an opener inside a two-line double quote is no heredoc',
       bash(f'bash scripts/agent-msg.sh k v "a\nx <<E y"\n{CREATE}\nE'), 2)
expect('NEG an unterminated quote before an opener: nothing dropped',
       bash(f"bash scripts/agent-msg.sh k v \"x - <<'E'\n{CREATE}\nE"), 2)
expect('NEG B8 a lone & after the opener backgrounds and runs the creation',
       bash(f"bash scripts/agent-msg.sh k v - <<'E' & {CREATE}\nbody\nE"), 2)
expect('NEG B8b a process substitution after the opener runs the creation',
       bash(f"cat > n.md <<'E' <({CREATE})\nbody\nE"), 2)
expect('NEG delimiter "E"X (bash: EX) is no plainly quoted word: nothing dropped',
       bash(f'cat > n.md <<"E"X\nEX\n{CREATE}\nE'), 2)
expect('NEG delimiter \\E (bash: E, quoted) is no plain word: nothing dropped, the body is judged',
       bash(f'cat > n.md <<\\E\n{CREATE}\nE'), 2)
expect('a <<- message heredoc closed by a tab-indented word passes',
       bash(f"bash scripts/agent-msg.sh k v - <<-'E'\n{CREATE} is gated\n\tE"), 0)
expect('a << E message heredoc (a space before the word) passes',
       bash(f"bash scripts/agent-msg.sh k v - << E\n{CREATE} is gated\nE"), 0)
expect('NEG a <<- message heredoc, then the creation after its tab-indented closer, blocks',
       bash(f"bash scripts/agent-msg.sh k v - <<-'E'\nbody\n\tE\n{CREATE}"), 2)
expect('NEG B9 an unquoted message heredoc runs a $( ) in its body',
       bash(f'curl localhost:3420/api/messages -d @- <<-E\n$(\n{CREATE}\n)\n\tE'), 2)
expect('NEG B9b an unquoted message heredoc runs a backtick in its body',
       bash(f'bash scripts/agent-msg.sh k v - <<EOF\nx `{CREATE}` y\nEOF'), 2)
expect('a QUOTED message heredoc with a $( ) in its body is text and passes',
       bash(f"bash scripts/agent-msg.sh k v - <<'EOF'\nx $({CREATE}) y\nEOF"), 0)
expect('an unquoted message heredoc without a substitution passes',
       bash(f'bash scripts/agent-msg.sh k v - <<EOF\n{CREATE} is gated, $HOME too\nEOF'), 0)
expect('NEG <<<<E: the << inside a here-string operator is no opener',
       bash(f'bash scripts/agent-msg.sh k v - <<<<E\n{CREATE}\nE'), 2)
expect('a # inside a word (a#b) is no comment and the message heredoc passes',
       bash(f"bash scripts/agent-msg.sh k v a#b - <<'E'\n{CREATE} is gated\nE"), 0)
expect('NEG an opener line that ends inside a single quote: nothing dropped',
       bash(f"bash scripts/agent-msg.sh k v - <<'E' 'a\n{CREATE}\nE\n'"), 2)
expect('NEG an opener line that ends inside a double quote: nothing dropped',
       bash(f'bash scripts/agent-msg.sh k v - <<\'E\' "a\n{CREATE}\nE\n"'), 2)
expect('NEG a second << on an opener line is not read as a heredoc: its body is judged',
       bash(f"cat <<'A' > n.md <<'B'\nx\nA\n{CREATE}\nB"), 2)
# Mutation survivors M34/M35/M40 (card 3b05ae69): bash runs each creation (measured with echo), the dropped body would
# hide it. A quote opened on the opener line that closes on the NEXT line, with a command after it on that line:
expect("NEG a single quote from the opener line closing on the next line, a command after it, blocks",
       bash(f"bash scripts/agent-msg.sh k v - <<'E' 'a\nb' ; {CREATE}\nE"), 2)
expect('NEG a double quote from the opener line closing on the next line, a command after it, blocks',
       bash(f'bash scripts/agent-msg.sh k v - <<\'E\' "a\nb" ; {CREATE}\nE'), 2)
# ... and an unquoted first heredoc with a quoted second one on the same line: bash expands the first body's $( ).
expect('NEG an unquoted heredoc, then a quoted second << on its line: the first body runs its $( )',
       bash(f"bash scripts/agent-msg.sh k v - <<A <<'B'\n$({CREATE})\nA\nB"), 2)

# --- Viktor 50057 (each shape run by bash in his own_rcl.py / probe_rcl.py: the creation ran) ---
# R1: bash closes on the bare word (<<- after leading tabs only); a line with spaces around it does not close
for label, line in (('trailing spaces', 'E  '), ('leading spaces', '  E'), ('a leading tab without <<-', '\tE')):
    expect(f'NEG R1 a closing line with {label}, then a sink heredoc, blocks',
           bash(f"cat > n.md <<'E'\n{line}\ncat > m.md <<'Z'\nE\n{CREATE}\nZ"), 2)
expect('R1 a body line "E  " is text, the real closing line closes: the message passes',
       bash(f"bash scripts/agent-msg.sh k v - <<'E'\nE  \n{CREATE} is gated\nE"), 0)
# R2: a second << on the opener line: no heredoc after it is dropped
expect("NEG R2 a second quoted << on the opener line, a sink opener in its body, blocks",
       bash(f"cat > n.md <<'A' <<'B'\nx\nA\ncat > m.md <<'Z'\nB\n{CREATE}\nZ"), 2)
expect('NEG R2 a second unquoted << on the opener line, a sink opener in its body, blocks',
       bash(f"cat > n.md <<A <<B\nx\nA\ncat > m.md <<'Z'\nB\n{CREATE}\nZ"), 2)
# (a) an interpreter that reads its program from stdin runs the body; the sink word is only an argument
for head in ('sh -s scripts/agent-msg.sh', 'bash -s agent-msg.sh klodel', 'ksh -s tee n.md', 'ksh -s git commit -F -',
             'python3 - scripts/agent-msg.sh', 'perl - curl /api/messages', 'python3 -X utf8 - scripts/agent-msg.sh',
             'bash -o pipefail -s agent-msg.sh k', 'sh -O extglob -s scripts/agent-msg.sh'):
    expect(f'NEG (a) {head} reads the body as its program', bash(f"{head} <<'E'\n{CREATE}\nE"), 2)
# an option's own argument is no script operand, even when it names the message script (OPT_ARG; both run the body)
for head in ('bash --rcfile scripts/agent-msg.sh -s agent-msg.sh k', 'python3 -X scripts/agent-msg.sh - scripts/agent-msg.sh'):
    expect(f'NEG (a) {head}: the option argument is skipped', bash(f"{head} <<'E'\n{CREATE}\nE"), 2)
expect('(a) bash running the message script file is a sink and passes',
       bash(f"bash scripts/agent-msg.sh k v - <<'E'\n{CREATE} is gated\nE"), 0)
# (c) the wrapped test comes from the walk's stack (a quoted ")" or a case pattern fooled the count)
expect('NEG (c) a quoted ")" before $(sh <<E: wrapped', bash(f"scripts/agent-msg.sh a \")\" $(sh <<'E'\n{CREATE}\nE\n)"), 2)
expect('NEG (c) a case pattern ( ) inside $( ): wrapped',
       bash(f"scripts/agent-msg.sh a b $(case a in (a) sh <<'E'\n{CREATE}\nE\n;; esac)"), 2)
expect("NEG (c) a quoted backtick before a backtick substitution: wrapped",
       bash(f"scripts/agent-msg.sh a '`' `sh <<'E'\n{CREATE}\nE\n`"), 2)
# (d) no opener inside $[ ], $(( )) or ${ }
for arg in ('$[1<<E ]', '")" $((1<<E ))', '${u:-<<E }', '${u#<<E }'):
    expect(f'NEG (d) {arg} holds no opener: the next lines run', bash(f'scripts/agent-msg.sh a b {arg}\n{CREATE}\nE'), 2)
expect('NEG (d) "$((1<<E ))" inside double quotes holds no opener', bash(f'scripts/agent-msg.sh a "$((1<<E ))"\n{CREATE}\nE'), 2)
# ... and the contexts close: an arithmetic, a ${ } or a here-string BEFORE a real message heredoc keeps it a message
expect('$((1<<2)) before a message heredoc passes', bash(f"bash scripts/agent-msg.sh k $((1<<2)) - <<'E'\n{CREATE} is gated\nE"), 0)
expect('"$((1<<2))" before a message heredoc passes',
       bash(f"bash scripts/agent-msg.sh k \"$((1<<2))\" - <<'E'\n{CREATE} is gated\nE"), 0)
expect('"${HOME}" before a message heredoc passes', bash(f"bash scripts/agent-msg.sh \"${{HOME}}\" k - <<'E'\n{CREATE} is gated\nE"), 0)
expect('a here-string, then a message heredoc, passes',
       bash(f"cat <<<x; bash scripts/agent-msg.sh k v - <<'E'\n{CREATE} is gated\nE"), 0)
# (e) an outer << the walk cannot follow (never closes, or E-1): bash expands the inner $( )
expect('NEG (e) an outer unclosed unquoted heredoc expands the inner body',
       bash(f"cat <<Z >/dev/null\nbash scripts/agent-msg.sh k v - <<'E'\n$({CREATE})\nE"), 2)
expect('NEG (e) an outer <<E-1 heredoc expands the inner body',
       bash(f"cat <<E-1 >/dev/null\nbash scripts/agent-msg.sh k v - <<'Q'\n$({CREATE})\nQ\nE-1"), 2)
expect('NEG (e) <<EOF closing only at a line E (bash reads on and expands): no later heredoc is dropped',
       bash(f"cat <<EOF >/dev/null\nx\nE\nbash scripts/agent-msg.sh k v - <<'Q'\n$({CREATE})\nQ"), 2)
# (f) a backslash-newline in an unquoted body joins lines: bash may close there
expect('NEG (f) an unquoted body whose backslash-newline forms the closing line',
       bash(f'bash scripts/agent-msg.sh k v - <<E\nhi\nE\\\n\n{CREATE}\nE'), 2)
# (g) a creation past the 256 KB cut
expect('NEG (g) 300 KB of true; segments, the creation at the tail past the cut, blocks',
       bash('true; ' * 50000 + CREATE), 2)
expect('NEG an opener line whose $( goes on past the line: no later heredoc is dropped',
       bash(f"cat > n.md <<'A' $(true\n)\nbody\nA\nbash scripts/agent-msg.sh k v - <<'B'\n{CREATE}\nB"), 2)
# ... and the usual shapes still pass: a quote, a comment, a $( ) or an apostrophe around a message heredoc
expect("a message heredoc with an apostrophe in the body passes",
       bash(f"bash scripts/agent-msg.sh k v - <<'MSG'\nit's about {CREATE}\nMSG"), 0)
expect('a comment line, then a message heredoc, passes',
       bash(f"# it's a note\nbash scripts/agent-msg.sh k v - <<'MSG'\n{CREATE} is gated\nMSG"), 0)
expect('a quoted argument with ( ) and a $( ) before a message heredoc passes',
       bash(f"bash scripts/agent-msg.sh \"$(echo k)\" 'v (x)' - <<'MSG'\n{CREATE} is gated\nMSG"), 0)
expect("an escaped quote (\\') before a message heredoc is no quote and passes",
       bash(f"echo \\' ; bash scripts/agent-msg.sh k v - <<'E'\n{CREATE} is gated\nE"), 0)
expect('an escaped double quote inside a double-quoted argument passes',
       bash(f"bash scripts/agent-msg.sh k \"a\\\"b\" - <<'E'\n{CREATE} is gated\nE"), 0)
expect("a $'a\\'b' argument (an escaped quote inside $'...') passes",
       bash(f"bash scripts/agent-msg.sh k $'a\\'b' - <<'E'\n{CREATE} is gated\nE"), 0)
expect('two message heredocs in one command pass',
       bash(f"bash scripts/agent-msg.sh k v - <<'A'\n{CREATE}\nA\nbash scripts/agent-msg.sh k w - <<'B'\n{CREATE}\nB"), 0)
expect('NEG two heredocs, the creation between them, blocks',
       bash(f"bash scripts/agent-msg.sh k v - <<'A'\nx\nA\n{CREATE}\nbash scripts/agent-msg.sh k w - <<'B'\ny\nB"), 2)

# Watchdog: whatever runs slow blocks (exit 2) before the hook timeout; the env seam can only lower the limit.
try:
    p = subprocess.run([sys.executable, '-I', GATE], capture_output=True, text=True, timeout=20,
                       input=json.dumps({'tool_name': 'Bash',
                                         'tool_input': {'command': 'echo ' + 'cat <<E\n' * 60000}}),
                       env={'PATH': '/usr/bin:/bin', 'LEDGER_DB_PATH': '/nonexistent/claudeclaw.db',
                            'REPO_GATE_WATCHDOG_S': '0.001'})
    wd = (p.returncode, p.stderr)
except subprocess.TimeoutExpired:
    wd = (None, 'TIMEOUT after 20 s')
expect('NEG the watchdog fires: exit 2', wd, 2)
if 'watchdog' not in wd[1]:
    FAILS.append(f'watchdog message missing: {wd[1][:200]!r}')
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location('repo_create_gate_mod', GATE)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_ws = getattr(_mod, 'watchdog_s', None)
if _ws is None:
    FAILS.append('watchdog_s: missing (no watchdog)')
else:
    for raw, want in [('100', 6.0), ('6', 6.0), ('2.5', 2.5), ('0', 0.001), ('-1', 0.001), ('nan', 6.0), ('x', 6.0)]:
        os.environ['REPO_GATE_WATCHDOG_S'] = raw
        got = _ws()
        if got != want:
            FAILS.append(f'watchdog_s({raw!r}) = {got}, want {want}')
        else:
            print(f'ok   watchdog_s({raw!r}) = {want}')
    os.environ.pop('REPO_GATE_WATCHDOG_S', None)
    got = _ws()
    expect('watchdog_s() unset = 6.0', (0 if got == 6.0 else 1, str(got)), 0)

# --- The linear sink / write tests keep the old regex's edges (mutation survivors of the first round, card 3b05ae69) ---
expect('NEG agent-msg.sh.bak is no message wrapper: the body is judged',
       bash(f"cat x/agent-msg.sh.bak <<'E'\n{CREATE}\nE"), 2)
expect('NEG -F - BEFORE git commit is no commit-message sink',
       bash(f"echo -F - git commit x <<'E'\n{CREATE}\nE"), 2)
expect('NEG cat > n.md x: the notes file must be the last word of the head',
       bash(f"cat > n.md x <<'E'\n{CREATE}\nE"), 2)
expect('NEG xtee n.md is no tee', bash(f"xtee n.md <<'E'\n{CREATE}\nE"), 2)
expect('cat > "n.md" (a quoted notes file) is a sink and passes', bash(f"cat > \"n.md\" <<'E'\n{CREATE} is gated\nE"), 0)
expect('tee -a n.md is a sink and passes', bash(f"tee -a n.md <<'E'\n{CREATE} is gated\nE"), 0)
with tempfile.TemporaryDirectory() as d:
    with open(os.path.join(d, 'm.json'), 'w') as fh:
        fh.write('{"content": "A kapu blokkolja: gh repo create x --private"}\n')  # a creation: read, it would BLOCK
    expect('a payload file posted to a dashboard curl is a message, not a run, and passes',
           bash('curl -s -X POST localhost:3420/api/messages -d @m.json', cwd=d), 0)
expect('NEG urlopen(..., data=) to user/repos blocks',
       bash("python3 -c \"import urllib.request as u; u.urlopen('https://api.github.com/user/repos', data=b'{}')\""), 2)
expect('urlopen( whose data= lies past the next ")" is no write and passes',
       bash("python3 -c \"u.urlopen(r); f('https://api.github.com/user/repos', data=1)\""), 0)
expect('gh api user/repos --fieldset x (no field flag) is a read and passes', bash('gh api user/repos --fieldset x'), 0)

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

# --- INTERNAL ERROR (Viktor 50057 follow-up): verdict() crashes, then only the raw creation regexes decide --------
# No input crashes verdict() today (Viktor: 0 ERR on the probes), so a wrapper runs the real main() with verdict()
# (and, for the last rows, creates_repo()) replaced by a raising function; stdin, stderr, the log and the exit code
# are the real ones.
CRASH_WRAP = '''import importlib.util, sys
spec = importlib.util.spec_from_file_location('rcg', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
def boom(*a, **k):
    raise RuntimeError('injected')
def kbi(*a, **k):
    raise KeyboardInterrupt
m.verdict = kbi if sys.argv[2].startswith('kbi') else boom
if sys.argv[2] == 'both':
    m.creates_repo = boom
if sys.argv[2] == 'kbi-both':
    m.creates_repo = kbi
sys.exit(m.main())
'''


def crash_run(payload, mode='verdict'):
    d = tempfile.mkdtemp(prefix='rcg-crash-')
    log = os.path.join(d, 'hook-errors.log')
    p = subprocess.run([sys.executable, '-I', '-c', CRASH_WRAP, GATE, mode], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=20,
                       env={'PATH': '/usr/bin:/bin', 'LEDGER_DB_PATH': '/nonexistent/claudeclaw.db',
                            'HOOK_ERRLOG_PATH': log})
    logged = ''
    if os.path.exists(log):
        with open(log) as fh:
            logged = fh.read()
    return p.returncode, p.stderr, logged


def crash_expect(name, got, want_rc, want_log):
    rc, err, logged = got
    if rc != want_rc or want_log not in logged:
        FAILS.append(f'{name}: rc={rc}, want {want_rc}; log has {want_log!r}: {want_log in logged}; stderr={err[:200]!r}')
    else:
        print(f'ok   {name}')


def bash_payload(cmd):
    return {'tool_name': 'Bash', 'tool_input': {'command': cmd, 'description': ''}}


crash_expect('NEG internal error + a raw creation blocks', crash_run(bash_payload(CREATE)), 2, 'blocked (raw creation)')
crash_expect('NEG internal error + a creation only in a message heredoc body blocks (no dropping on a crash)',
             crash_run(bash_payload(f"bash scripts/agent-msg.sh k v - <<'E'\n{CREATE}\nE")), 2, 'blocked (raw creation)')
crash_expect('NEG internal error + an approved creation blocks (the approval line is not read on a crash)',
             crash_run(bash_payload(f'{CREATE}  # {OK_LINE}')), 2, 'blocked (raw creation)')
crash_expect('NEG internal error + an MCP create tool blocks',
             crash_run({'tool_name': 'mcp__github__create_repository', 'tool_input': {'name': 'x'}}), 2,
             'blocked (raw creation)')
crash_expect('internal error + a harmless command is allowed and logged', crash_run(bash_payload('git status')), 0,
             'internal error, allowed')
crash_expect('internal error + another MCP tool is allowed', crash_run({'tool_name': 'mcp__github__get_me',
                                                                          'tool_input': {}}), 0, 'allowed')
crash_expect('internal error + a non-dict tool_input is allowed', crash_run({'tool_name': 'Bash', 'tool_input': 'x'}), 0,
             'allowed')
crash_expect('internal error + a non-string command is not judged (as verdict) and is allowed',
             crash_run({'tool_name': 'Bash', 'tool_input': {'command': [CREATE]}}), 0, 'allowed')
crash_expect('internal error in the fallback too: allowed, never exit 1', crash_run(bash_payload(CREATE), 'both'), 0,
             'internal error, allowed')
r = crash_run(bash_payload(CREATE))
expect('the internal-error block message names the cause', (0 if 'belső hibára' in r[1] else 1, r[1]), 0)

# Viktor 50109 (independent probe rcf). R1: "~<lone surrogate>" / "~<NUL>" made expanduser raise inside
# referenced_files(), and the creation in an EARLIER referenced script went through (98e55fd3 and main: 0).
with tempfile.TemporaryDirectory() as d:
    with open(os.path.join(d, 'mk.py'), 'w') as fh:
        fh.write(f'import os\nos.system("{CREATE}")\n')
    expect('NEG R1 a referenced creation, then a ~<lone surrogate> reference, blocks',
           bash('python3 mk.py; python3 ~\ud800/x.py', cwd=d), 2)
    expect('NEG R1 a referenced creation, then a ~<NUL> reference, blocks', bash('python3 mk.py; python3 ~\x00/x.py', cwd=d), 2)
    # (c) after a crash the fallback reads the files the command names too
    crash_expect('NEG internal error + a creation only in a referenced script blocks',
                 crash_run({'tool_name': 'Bash', 'tool_input': {'command': 'python3 mk.py'}, 'cwd': d}), 2,
                 'blocked (raw creation)')
# R2: over 256 KB the rest was searched only from 1 KB before the cut; a REST path before the cut and its gh api
# field after it is one creation (direct-ghapi-words-field-end-1m)
expect('NEG R2 1 MB: the REST path before the cut, the gh api field after it, blocks',
       bash('gh api /user/repos ' + 'w ' * (512 * 1024) + '-f name=x'), 2)
# V02: after a crash the fallback reads the WHOLE command, not the first 256 KB
crash_expect('NEG internal error + a creation past 256 KB blocks',
             crash_run(bash_payload('echo ' + 'w ' * (160 * 1024) + '; ' + CREATE)), 2, 'blocked (raw creation)')
# (d) a null / non-dict tool_input of an MCP create tool carries no approval line (direct-mcp-create-input-null)
expect('NEG an MCP create tool with a null tool_input blocks', run({'tool_name': 'mcp__github__create_repository',
                                                                    'tool_input': None}), 2)
expect('NEG an MCP create tool with a string tool_input blocks', run({'tool_name': 'mcp__github__create_repository',
                                                                      'tool_input': 'x'}), 2)
# (e) a closed stderr still blocks with exit 2, not 1 (direct-stderr-closed-create); a KeyboardInterrupt in the
# judgment takes the crash path (kbi-cli-create)
p = subprocess.run(['/bin/sh', '-c', 'exec "$0" -I "$1" 2>&-', sys.executable, GATE],
                   input=json.dumps(bash_payload(CREATE)), capture_output=True, text=True, timeout=20,
                   env={'PATH': '/usr/bin:/bin', 'LEDGER_DB_PATH': '/nonexistent/claudeclaw.db'})
expect('NEG a creation with a closed stderr exits 2, not 1', (p.returncode, ''), 2)
crash_expect('NEG a KeyboardInterrupt in the judgment + a raw creation blocks',
             crash_run(bash_payload(CREATE), 'kbi'), 2, 'blocked (raw creation)')
# a KeyboardInterrupt in the fallback too is caught like any crash there: allowed, logged, never a traceback exit
crash_expect('a KeyboardInterrupt in the judgment and in the fallback: allowed, never exit 1',
             crash_run(bash_payload(CREATE), 'kbi-both'), 0, 'internal error, allowed')
# the crash path's block message with a closed stderr still exits 2
p = subprocess.run(['/bin/sh', '-c', 'exec "$0" -I -c "$1" "$2" verdict 2>&-', sys.executable, CRASH_WRAP, GATE],
                   input=json.dumps(bash_payload(CREATE)), capture_output=True, text=True, timeout=20,
                   env={'PATH': '/usr/bin:/bin', 'LEDGER_DB_PATH': '/nonexistent/claudeclaw.db',
                        'HOOK_ERRLOG_PATH': os.devnull})
expect('NEG internal error + a raw creation with a closed stderr exits 2, not 1', (p.returncode, ''), 2)

# --- KNOWN LIMITS, pinned (Viktor 50172, Klodel 50170 cap 20; independent probe indep10 labels) --------------------
# Each row pins TODAY's behaviour of a documented Known limit (module docstring), so a later fix shows up as a red
# row here that has to be turned around on purpose. The row name starts with "KNOWN-LIMIT <word>"; the word is the one
# the docstring uses. A row that starts to block is a change of the documented limit, not a regression.
GH_ = 'g' + 'h'
POST_ = 'PO' + 'ST'
UR_ = 'us' + 'er/repos'
API_ = 'https://api.github.com/'
GQL_ = 'mutation{' + 'create' + 'Repository' + '(input:{name:"x",visibility:PRIVATE}){repository{url}}}'
with tempfile.TemporaryDirectory() as kd:
    with open(os.path.join(kd, 'q.graphql'), 'w') as fh:
        fh.write(GQL_ + '\n')
    with open(os.path.join(kd, 'mk.py'), 'w') as fh:
        fh.write("import requests\nrequests.post('" + API_ + UR_ + "', json={'name': 'x'})\n")
    with open(os.path.join(kd, 'mk.sh'), 'w') as fh:
        fh.write(CREATE + '\n')
    pins = [
        ('attached (curl -d with an attached quote)',
         f"curl -H 'Accept: application/json' {API_}{UR_} -d'{{\"name\":\"x\"}}'"),
        ('combined (curl -sSd short-flag cluster)', f"curl -sSd '{{\"name\":\"x\"}}' {API_}{UR_}"),
        ('ascii (curl --data-ascii)', f"curl --data-ascii '{{\"name\":\"x\"}}' {API_}{UR_}"),
        ('wget (wget --post-data)', f"wget --post-data='{{\"name\":\"x\"}}' {API_}{UR_}"),
        ('httpie (http POST)', f'http {POST_} {API_}{UR_} name=x'),
        ('placeholder (shell variables in the forks path)', f'curl -X {POST_} "{API_}repos/$OWNER/$NAME/forks"'),
        ('placeholder (gh api {owner}/{repo} forks)', f'{GH_} api -X {POST_} repos/{{owner}}/{{repo}}/forks'),
        ('attached (gh api -fname=x)', f'{GH_} api {UR_} -fname=x'),
        ('query-at-file (gh api graphql -F query=@file)', f'{GH_} api graphql -F query=@q.graphql'),
        ('cat-subst (gh api graphql -f query="$(cat file)")', f'{GH_} api graphql -f query="$(cat q.graphql)"'),
        ('sink-then-input (heredoc .json sink, --input later)',
         "cat > q2.json <<'EOF'\n" + json.dumps({'query': GQL_}) + f"\nEOF\n{GH_} api graphql --input q2.json"),
        ('session (requests.Session object .post)',
         "python3 -c \"import requests; s=requests.Session(); s.post('" + API_ + UR_ + "', json={'name':'x'})\""),
        ('separate-line (urllib Request data= on its own line)',
         "python3 - <<'EOF'\nimport json, urllib.request as u\nreq = u.Request('" + API_ + UR_
         + "', data=json.dumps({'name': 'x'}).encode())\nu.urlopen(req)\nEOF"),
    ]
    for word, cmd in pins:
        expect(f'KNOWN-LIMIT {word}: allowed today', bash(cmd, cwd=kd), 0)
    expect('KNOWN-LIMIT prefixed (an MCP name that only ends in create_repository): allowed today',
           run({'tool_name': 'mcp__gh__github_create_repository', 'tool_input': {'name': 'x'}, 'cwd': kd}), 0)

    # KNOWN-LIMIT pipe (real-stderr-pipe-closed): a stderr pipe whose reader end is closed makes the final flush fail;
    # a block leaves with 120, not 2.
    pp = subprocess.Popen([sys.executable, '-I', GATE], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE, env={'PATH': '/usr/bin:/bin',
                                                       'LEDGER_DB_PATH': '/nonexistent/claudeclaw.db'})
    pp.stderr.close()
    try:
        pp.stdin.write(json.dumps(bash_payload(CREATE)).encode())
        pp.stdin.close()
    except BrokenPipeError:
        pass
    expect('KNOWN-LIMIT pipe (a closed stderr pipe): a block exits 120 today', (pp.wait(timeout=20), ''), 120)

    # KNOWN-LIMIT fallback-raises: an internal error inside the fallback itself allows (never exit 1).
    INJ_ONE = '''import importlib.util, sys
spec = importlib.util.spec_from_file_location('rcg_pin', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
exc = {'rt': RuntimeError, 'os': OSError}[sys.argv[3]]
def boom(*a, **k):
    raise exc('injected')
setattr(m, sys.argv[2], boom)
sys.exit(m.main())
'''
    for fn, kind, cmd in (('heredocs', 'rt', 'python3 mk.py'), ('_read_small', 'os', 'bash mk.sh'),
                          ('creates_repo', 'rt', CREATE)):
        pi = subprocess.run([sys.executable, '-I', '-c', INJ_ONE, GATE, fn, kind],
                            input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}, 'cwd': kd}),
                            capture_output=True, text=True, timeout=20,
                            env={'PATH': '/usr/bin:/bin', 'LEDGER_DB_PATH': '/nonexistent/claudeclaw.db',
                                 'HOOK_ERRLOG_PATH': os.devnull})
        expect(f'KNOWN-LIMIT fallback-raises ({fn} raises, {cmd.split()[0]} ...): allowed today', (pi.returncode, pi.stderr), 0)

# KNOWN-LIMIT deep-json: stdin nested too deep to parse is malformed stdin and allows.
deep = ('{"tool_name":"Bash","tool_input":{"command":' + json.dumps(CREATE) + '},"x":' + '[' * 200000
        + ']' * 200000 + '}')
pd = subprocess.run([sys.executable, '-I', GATE], input=deep, capture_output=True, text=True, timeout=20,
                    env={'PATH': '/usr/bin:/bin', 'LEDGER_DB_PATH': '/nonexistent/claudeclaw.db'})
expect('KNOWN-LIMIT deep-json (nesting too deep to parse): allowed today', (pd.returncode, pd.stderr), 0)

# KNOWN-LIMIT malformed (invalid UTF-8 in stdin, UTF-8 locale): malformed stdin allows. Only where the interpreter
# reads stdin with errors='strict' (3.9 here): read() raises, the "malformed stdin" branch allows. With UTF-8 mode
# (the default from 3.15) stdin is surrogateescape, the bytes survive, the command is judged and blocks. The row takes
# the want from this interpreter's own stdin errors setting, under the same env.
_LOC = {'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8', 'LC_ALL': 'en_US.UTF-8'}
_errs = subprocess.run([sys.executable, '-I', '-c', 'import sys; print(sys.stdin.errors)'], capture_output=True,
                       text=True, timeout=20, env=_LOC).stdout.strip()
pm = subprocess.run([sys.executable, '-I', GATE],
                    input=b'{"tool_name":"Bash","tool_input":{"command":"' + CREATE.encode() + b' \xff"}}',
                    capture_output=True, timeout=20,
                    env={'PATH': '/usr/bin:/bin', 'LEDGER_DB_PATH': '/nonexistent/claudeclaw.db',
                         'LANG': 'en_US.UTF-8', 'LC_ALL': 'en_US.UTF-8'})
expect(f'KNOWN-LIMIT malformed (invalid UTF-8 stdin, stdin errors={_errs}): '
       + ('allowed today' if _errs == 'strict' else 'judged and blocked'), (pm.returncode, ''),
       0 if _errs == 'strict' else 2)

# KNOWN-LIMIT watchdog-env: with the env seam at 0.2 s, a closed fd 2 and stdin that arrives late, the watchdog fires
# with nowhere to write, and the call is allowed. The stdin delay (1.5 s) is far above the seam, so a slow start
# under load does not turn the row.
pw = subprocess.Popen(['/bin/sh', '-c', 'exec "$0" -I "$1" 2>&-', sys.executable, GATE], stdin=subprocess.PIPE,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                      env={'PATH': '/usr/bin:/bin', 'LEDGER_DB_PATH': '/nonexistent/claudeclaw.db',
                           'REPO_GATE_WATCHDOG_S': '0.2'})
time.sleep(1.5)
try:
    pw.stdin.write(json.dumps(bash_payload(CREATE)).encode())
    pw.stdin.close()
except BrokenPipeError:
    pass
expect('KNOWN-LIMIT watchdog-env (seam 0.2 s, fd 2 closed, late stdin): allowed today', (pw.wait(timeout=20), ''), 0)

if FAILS:
    print('\nFAILED:\n' + '\n'.join(FAILS))
    sys.exit(1)
print('\nall passed')
