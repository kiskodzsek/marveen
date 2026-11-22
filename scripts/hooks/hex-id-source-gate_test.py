#!/usr/bin/env python3
"""Tests for hex-id-source-gate.py: python3 -I hex-id-source-gate_test.py
Synthetic transcripts in a temp dir; the hook runs as a subprocess on its real stdin protocol. Nothing is sent."""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOK = os.environ.get('HEX_GATE_SCRIPT',
                      os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hex-id-source-gate.py'))
TMP = tempfile.mkdtemp(prefix='hexgate-')
atexit.register(shutil.rmtree, TMP, True)

SHA64 = '6ba2ea2d4a38fd7a32cd2bb9aa22ddc1b3b0fff1c12bdc90d48b1ff21891781f'
COMMIT = '9b1e9239291f0c2d4e5a6b7c8d9e0f1a2b3c4d5e'
CARD = '396f0d8f'


def tool_result(text):
    return {'type': 'user', 'message': {'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': 'x', 'content': text}]}}


def inbound(text):
    return {'type': 'user', 'message': {'role': 'user', 'content': text}}


def attachment(text):
    return {'type': 'attachment', 'attachment': {'type': 'queued_command', 'prompt': text}}


def own_text(text):
    return {'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}}


def own_tool_use(cmd):
    return {'type': 'assistant', 'message': {'role': 'assistant', 'content': [
        {'type': 'tool_use', 'id': 't', 'name': 'Bash', 'input': {'command': cmd}}]}}


def api_blob(text):
    return {'type': 'api-request-blob', 'message': {'role': 'system', 'content': text}}


BASE = [tool_result(SHA64 + '  migrations/x.sql'), tool_result('commit ' + COMMIT), inbound('kártya ' + CARD)]


def transcript(records, name):
    p = os.path.join(TMP, name + '.jsonl')
    with open(p, 'w') as f:
        for r in records:
            f.write(json.dumps(r) + '\n')
    return p


def run(cmd, records=BASE, name='t', tool='Bash', cwd=None, raw=None):
    data = raw if raw is not None else json.dumps({'tool_name': tool, 'tool_input': {'command': cmd},
                                                   'transcript_path': transcript(records, name) if records is not None
                                                   else os.path.join(TMP, 'missing.jsonl'), 'cwd': cwd or TMP})
    p = subprocess.run([sys.executable, '-I', '-B', HOOK], input=data, capture_output=True, text=True,
                       env=dict(os.environ, HEX_GATE_FAILOPEN_LOG=FOLOG))
    return p.returncode, p.stderr


FOLOG = os.path.join(TMP, 'failopen.log')


def folog():
    try:
        with open(FOLOG) as f:
            return f.read()
    except OSError:
        return ''


def fresh(fn):
    """Run fn with an empty fail-open log; return (rc, stderr, log text)."""
    if os.path.exists(FOLOG):
        os.unlink(FOLOG)
    rc, err = fn()
    return rc, err, folog()


def failopen_case(fn, reason):
    rc, err, log = fresh(fn)
    lines = log.splitlines()
    ok = rc == 0 and len(lines) == 1 and lines[0].split('\t')[1:] == [reason] and 'ab12cd34ef' not in log
    return (0 if ok else 9), err


def payload(name, text):
    p = os.path.join(TMP, name)
    with open(p, 'w') as f:
        f.write(text)
    return p


MSG = 'bash scripts/agent-msg.sh kernel viktor '
CARD_PUT = "curl -s -X PUT http://localhost:3420/api/kanban/abc -d '{\"comment\":\""


def timed(cmd, budget=3.0):
    """run(), but a run over the budget fails the case (rc -2), whatever it returned."""
    import time
    t0 = time.monotonic()
    rc, err = run(cmd)
    dt = time.monotonic() - t0
    return (rc, err) if dt < budget else (-2, 'took %.1f s (budget %.1f s)' % (dt, budget))

CASES = [
    # blocked
    ('invented sha in agent-msg', lambda: run(MSG + '"sha256 c7ab0f53aa11bb22cc33dd44ee55ff66"'), 2),
    ('mistyped commit (9b1e92392916)', lambda: run(MSG + '"fej 9b1e92392916"'), 2),
    ('hex only in own earlier text', lambda: run(MSG + '"x 1a2b3c4d5e6f"', BASE + [own_text('lesz 1a2b3c4d5e6f')]), 2),
    ('hex only in own earlier tool_use', lambda: run(MSG + '"x 1a2b3c4d5e6f"',
                                                     BASE + [own_tool_use('echo 1a2b3c4d5e6f')]), 2),
    ('hex only in api-request-blob', lambda: run(MSG + '"x 1a2b3c4d5e6f"', BASE + [api_blob('1a2b3c4d5e6f')]), 2),
    ('kernel-msg.sh payload file', lambda: run('bash tools/kernel-msg.sh viktor - < ' +
                                               payload('m1.txt', 'hash 0123abcd4567ef89')), 2),
    ('relative payload file from cwd', lambda: (payload('m2.txt', 'hash 0123abcd4567ef89'),
                                                run('bash tools/kernel-msg.sh viktor - < m2.txt'))[1], 2),
    ('curl POST /api/messages with @file', lambda: run(
        'curl -s -X POST localhost:3420/api/messages --data-binary @' + payload('p.json', '{"content":"ab12cd34ef"}')), 2),
    ('kanban comment via curl -d', lambda: run("curl -s localhost:3420/api/kanban/x/comments -d '{\"c\":\"ab12cd34ef\"}'"), 2),
    ('msg-close result', lambda: run('bash tools/msg-close.sh "kész, fej ab12cd34ef" 48854'), 2),
    ('card-comment heredoc', lambda: run("bash tools/card-comment.sh 396f0d8f - <<'TXT'\nfej ab12cd34ef\nTXT"), 2),
    ('uppercase invented', lambda: run(MSG + '"AB12CD34EF"'), 2),
    # allowed
    ('measured 64-hex', lambda: run(MSG + '"sha256 ' + SHA64 + '"'), 0),
    ('8-digit prefix of measured hash', lambda: run(MSG + '"sha256 6ba2ea2d"'), 0),
    ('uppercase of a measured hash', lambda: run(MSG + '"' + COMMIT[:12].upper() + '"'), 0),
    ('card id from an inbound message', lambda: run(MSG + '"kártya ' + CARD + '"'), 0),
    ('hex from an attachment (queued message)', lambda: run(MSG + '"x 77aa88bb99"', BASE + [attachment('77aa88bb99')]), 0),
    ('pure digits are not hex ids', lambda: run(MSG + '"msg 48878123 és 1795189258"'), 0),
    ('pure letters are words', lambda: run(MSG + '"deadbeefcafe facade"'), 0),
    ('file name with hex', lambda: run('cat > $S/c15896271.txt <<\'EOF\'\nx\nEOF\n' + MSG + '- < $S/c15896271.txt'), 0),
    ('heredoc is not a payload file', lambda: run("bash tools/card-comment.sh x - <<'TXT'\nkártya " + CARD + "\nTXT"), 0),
    ('unquoted heredoc delimiter is not a file', lambda: (payload('EOF', 'x ab12cd34ef'),
                                                          run('bash tools/card-comment.sh x - <<EOF\nkártya ' + CARD +
                                                              '\nEOF'))[1], 0),
    ('payload file with measured hash', lambda: run('bash tools/kernel-msg.sh viktor - < ' +
                                                    payload('m3.txt', 'fej ' + COMMIT)), 0),
    ('GET /api/messages is not a send', lambda: run('curl -s "localhost:3420/api/messages?agent=kernel" | grep ab12cd34ef'), 0),
    ('not a send command', lambda: run('git show ab12cd34ef'), 0),
    ('email @ is not a file problem', lambda: run(MSG + '"patrik@myshp.hu, fej ' + COMMIT[:8] + '"'), 0),
    ('missing transcript fails open', lambda: run(MSG + '"ab12cd34ef"', records=None), 0),
    ('non-Bash tool', lambda: run(MSG + '"ab12cd34ef"', tool='Write'), 0),
    ('malformed stdin', lambda: run('', raw='not json'), 0),
    # fail-open is logged without content (Viktor 48897 (a))
    ('log: missing transcript', lambda: failopen_case(lambda: run(MSG + '"ab12cd34ef"', records=None),
                                                      'transcript-unreadable'), 0),
    ('log: no transcript_path field', lambda: failopen_case(lambda: run('', raw=json.dumps(
        {'tool_name': 'Bash', 'tool_input': {'command': MSG + '"ab12cd34ef"'}, 'cwd': TMP})), 'no-transcript-path'), 0),
    ('log: stdin not json', lambda: failopen_case(lambda: run('', raw='not json'), 'stdin-not-json'), 0),
    ('log: input not an object', lambda: failopen_case(lambda: run('', raw='[1]'), 'input-not-object'), 0),
    ('log: a normal allow writes nothing', lambda: (lambda r: (0 if r[0] == 0 and r[2] == '' else 9, r[1]))(
        fresh(lambda: run(MSG + '"kártya ' + CARD + '"'))), 0),
    ('log: a block writes nothing', lambda: (lambda r: (0 if r[0] == 2 and r[2] == '' else 9, r[1]))(
        fresh(lambda: run(MSG + '"ab12cd34ef"'))), 0),
    ('log: a send without hex needs no transcript', lambda: (lambda r: (0 if r[0] == 0 and r[2] == '' else 9, r[1]))(
        fresh(lambda: run(MSG + '"semmi"', records=None))), 0),
    ('log: capped at 1 MiB', lambda: (open(FOLOG, 'w').write('x' * (1 << 20)),
                                      run('', raw='not json'), (0 if os.path.getsize(FOLOG) == 1 << 20 else 9, ''))[2], 0),
    ('no hex at all', lambda: run(MSG + '"semmi"'), 0),
]


# Viktor 1st round (Kernel 48889): real record shapes measured on a live transcript (a hook block is a user
# tool_result, a file-change echo is an attachment, CLAUDE.md is an attachment of type instructions). The secret is a
# FAKE 64-hex in TMP; no real token is read.
MEAS = SHA64
INV = '1a2b3c4d5e6f'
FAKE_SECRET = 'f00dfeed' * 8


def tr_err(text):
    r = tool_result(text)
    r['message']['content'][0]['is_error'] = True
    return r


def att(text, kind='edited_text_file'):
    return {'type': 'attachment', 'attachment': {'type': kind, 'content': text}}


def own_use(name, inp):
    return {'type': 'assistant', 'message': {'role': 'assistant', 'content': [
        {'type': 'tool_use', 'id': 't', 'name': name, 'input': inp}]}}


def no_secret(res):
    rc, err = res
    return (99 if FAKE_SECRET[:16] in err else rc), err


def all_blocked(cmds, recs):
    res = [run(c, recs) for c in cmds]
    return (2 if all(rc == 2 for rc, _ in res) else 0), res[-1][1]


BASE2 = BASE + [att('# CLAUDE.md ... kártya 9dbb581a ...', 'instructions')]
SECRET_PATH = payload('dashboard-token', FAKE_SECRET + '\n')
DRAFT = payload('draft.txt', 'fej ' + INV + '\n')
GOOD = payload('good.txt', 'fej ' + MEAS[:12] + '\n')
MIDDLE8 = MEAS[20:][:8]
BLOCK_MSG = ('PreToolUse:Bash hook error: [python3 hex-id-source-gate.py]: HEX-FORRAS-KAPU (kártya 7b2f784f): ' + INV)
AUTH = '-H "Authorization: Bearer $(< ' + SECRET_PATH + ')" '
CURL_MSG = 'curl -s -X POST localhost:3420/api/messages '

CASES += [
    # the token file is never payload, the block message never carries it
    ('M1 dollar-paren read of the token in a header is not payload', lambda: no_secret(run(
        CURL_MSG + AUTH + "--data-binary @- <<'JSON'\n{\"content\":\"kártya " + CARD + "\"}\nJSON", BASE2)), 0),
    ('M2 same with an invented hex: blocked, secret not echoed', lambda: no_secret(run(
        CURL_MSG + AUTH + "--data-binary @- <<'JSON'\n{\"content\":\"fej " + INV + "\"}\nJSON", BASE2)), 2),
    ('M3 curl -H @headerfile is not payload', lambda: no_secret(run(
        'curl -s -X POST localhost:3420/api/kanban/x/comments -H @' +
        payload('hdr.txt', 'Authorization: Bearer ' + FAKE_SECRET + '\n') + " -d '{\"c\":\"ok\"}'", BASE2)), 0),
    # an echo of the agent's own text is not a source
    ('L1 retry after the gate block', lambda: run(MSG + '"fej ' + INV + '"', BASE2 + [
        own_use('Bash', {'command': MSG + '"fej ' + INV + '"'}), tr_err(BLOCK_MSG)]), 2),
    ('L2 Write draft, Read back, send', lambda: run(MSG + '- < ' + DRAFT, BASE2 + [
        own_use('Write', {'file_path': DRAFT, 'content': 'fej ' + INV}), tool_result('1\tfej ' + INV)]), 2),
    ('L3 heredoc draft, cat back, send', lambda: run(MSG + '- < ' + DRAFT, BASE2 + [
        own_use('Bash', {'command': 'cat > ' + DRAFT + " <<'T'\nfej " + INV + '\nT'}), tool_result(''),
        own_use('Bash', {'command': 'cat ' + DRAFT}), tool_result('fej ' + INV)]), 2),
    # Kernel, 2nd round: after an own mention a LONGER run is a measurement (git rev-parse <short> -> 40 digits; the
    # 14-day replay's 22e1da9c, fca47183, 87f7caaa), Viktor's L5 asked 2; the same-length echo stays blocked (L1-L3).
    ('L5 own text, then a longer run in a tool output = measured', lambda: run(MSG + '"fej ' + INV + '"', BASE2 + [
        own_text('a fej ' + INV + ' lesz'), own_use('Bash', {'command': 'git log -1'}), tool_result(INV + 'aa')]), 0),
    ('own short sha, then git rev-parse gives 40', lambda: run(MSG + '"fej 22e1da9c"', BASE2 + [
        own_use('Bash', {'command': 'git rev-parse 22e1da9c'}),
        tool_result('22e1da9c0f1e2d3c4b5a69788796a5b4c3d2e1f0')]), 0),
    ('own long hex, the same run echoed back = blocked', lambda: run(MSG + '"fej ' + INV + 'aa"', BASE2 + [
        own_use('Bash', {'command': 'echo ' + INV + 'aa'}), tool_result(INV + 'aa')]), 2),
    ('gate block text next to a measured hash: the hash is a source', lambda: run(MSG + '"fej 5e6f7a8b9c0d"', BASE2 + [
        tool_result('5e6f7a8b9c0d1e2f  x.py\nFAIL y (rc 2: HEX-FORRAS-KAPU (k): 0a0b0c0d... copy it from there.)')]), 0),
    ('gate block text only: the token it names is not a source', lambda: run(MSG + '"fej 0a0b0c0d"', BASE2 + [
        tool_result('rc 2: HEX-FORRAS-KAPU (k): 0a0b0c0d... measure it and copy it from there.')]), 2),
    ('fork transcript: the parent Agent prompt is a source', lambda: run(MSG + '"fej ' + INV + '"', [
        {'type': 'fork-context-ref'}, dict(own_use('Agent', {'prompt': 'nézd a ' + INV + ' fejet'}), isSidechain=True,
                                           parentUuid=None),
        inbound('nézd a ' + INV + ' fejet')]), 0),
    # Viktor 2nd round: in the PARENT's transcript its Agent prompt stays its own text (P1), a shell running a heredoc
    # makes the body a command (P2), a Bash call without tool_input.command is a logged fail-open (P3)
    ('P1 parent transcript: own Agent prompt echoed by the result is not a source', lambda: run(
        MSG + '"fej ' + INV + '"', BASE2 + [dict(own_use('Agent', {'prompt': 'egyezik-e a ' + INV + '?'}),
                                                 isSidechain=False, parentUuid='u1'),
                                        tool_result('A ' + INV + ' nem egyezik.')]), 2),
    ('P1 a nested Agent call inside a fork (has parentUuid) stays own', lambda: run(MSG + '"fej ' + INV + '"', BASE2 + [
        dict(own_use('Agent', {'prompt': 'fej ' + INV}), isSidechain=True, parentUuid='u2'), tool_result('fej ' + INV)]), 2),
    ('P2 bash heredoc running agent-msg.sh is a send', lambda: run("bash <<'X'\n" + MSG + '"fej ' + INV + '"\nX', BASE2), 2),
    ('P2 sh -s heredoc running a curl POST is a send', lambda: run(
        "sh -s <<'X'\ncurl -s -X POST localhost:3420/api/messages -d '{\"c\":\"fej " + INV + "\"}'\nX", BASE2), 2),
    ('P2 cat heredoc piped to bash is a send', lambda: run("cat <<'X' | bash\n" + MSG + '"fej ' + INV + '"\nX', BASE2), 2),
    ('P3 log: Bash call without tool_input.command', lambda: failopen_case(lambda: run('', raw=json.dumps(
        {'tool_name': 'Bash', 'tool_input': {'cmd': MSG + INV}, 'transcript_path': 'x', 'cwd': TMP})), 'no-command'), 0),
    ('P3 log: tool_input not an object', lambda: failopen_case(lambda: run('', raw=json.dumps(
        {'tool_name': 'Bash', 'tool_input': [MSG + INV], 'transcript_path': 'x', 'cwd': TMP})), 'no-command'), 0),
    ('own text with an Agent call: the text still counts as own', lambda: run(MSG + '"fej ' + INV + '"', BASE2 + [
        {'type': 'assistant', 'message': {'role': 'assistant', 'content': [
            {'type': 'text', 'text': 'fej ' + INV}, {'type': 'tool_use', 'id': 'a', 'name': 'Agent', 'input': {}}]}},
        tool_result('fej ' + INV)]), 2),
    ('send line only in a heredoc body is not a send', lambda: run("python3 -I - <<'PY'\ncmd = 'bash scripts/agent-msg.sh"
                                                                 " a b 0f0e0d0c0b0a'\nPY", BASE2), 0),
    ('heredoc message to a send script is still a send', lambda: run("bash tools/kernel-msg.sh viktor - <<'MSG'\n"
                                                                    "fej 0f0e0d0c0b0a\nMSG", BASE2), 2),
    # payload and send coverage
    ('C1 quoted payload path', lambda: run(MSG + '- < "' + DRAFT + '"', BASE2), 2),
    ('C2 cat f piped into agent-msg.sh', lambda: run('cat ' + DRAFT + ' | ' + MSG + '-', BASE2), 2),
    ('C3 dollar-paren cat f as the text', lambda: run(MSG + '"$(cat ' + DRAFT + ')"', BASE2), 2),
    ('C4 positional message file of send-and-close.sh', lambda: run(
        'bash tools/send-and-close.sh 48889 ' + DRAFT + ' kernel', BASE2), 2),
    ('C5 curl --json @f', lambda: run('curl -s --json @' + DRAFT + ' localhost:3420/api/messages', BASE2), 2),
    ('C6 curl --request POST with -F', lambda: run(
        'curl -s --request POST localhost:3420/api/kanban/x/comments -F "c=fej ' + INV + '"', BASE2), 2),
    ('C7 8 hex from the middle of a measured run', lambda: run(MSG + '"fej ' + MIDDLE8 + '"', BASE2), 2),
    ('C8 runner forms are sends (env, timeout, /bin/bash)', lambda: all_blocked(
        [c + ' "fej ' + INV + '"' for c in ('env -i A=1 bash scripts/agent-msg.sh k v',
                                           'timeout 10 scripts/agent-msg.sh k v', '/bin/bash scripts/agent-msg.sh k v')],
        BASE2), 2),
    # must pass
    ('B1 measured, written, read back, sent', lambda: run(MSG + '- < ' + GOOD, BASE2 + [
        own_use('Write', {'file_path': GOOD, 'content': 'fej ' + MEAS[:12]}), tool_result('1\tfej ' + MEAS[:12])]), 0),
    ('B2 id from CLAUDE.md (instructions attachment)', lambda: run(MSG + '"kártya 9dbb581a"', BASE2), 0),
    ('B3 inbound id typed into a command first', lambda: run(MSG + '"kártya ' + CARD + '"', BASE2 + [
        own_use('Bash', {'command': 'curl -s localhost:3420/api/kanban/' + CARD}),
        tool_result('{"id":"' + CARD + '"}')]), 0),
    ('B4 grep for a hex in agent-msg.sh is not a send', lambda: run(
        'grep -n ' + INV + ' scripts/agent-msg.sh tools/send-and-close.sh', BASE2), 0),
    ('B5 measured prefix in a quoted payload path', lambda: run(MSG + '- < "' + GOOD + '"', BASE2), 0),
    ('B7 a path only mentioned in the text is not payload', lambda: run(MSG + '"lásd ' + DRAFT + '"', BASE2), 0),
    ('B8 cat > f heredoc, then send < f (measured)', lambda: run(
        'cat > ' + GOOD + " <<'T'\nfej " + MEAS[:12] + '\nT\n' + MSG + '- < ' + GOOD, BASE2), 0),
]


# Viktor, bekötési kör (Kernel 48918), an independent probe on c07619c5 (work/hx3-1120/indep-hexgate.txt): one
# over-block (P09) and nine reading forms that let an unseen hex through. All values are made up.
TYPO40 = '9b1e92392916aa00bb11cc22dd33ee44ff556677'
SUBDIR = os.path.join(TMP, 'sub')
os.makedirs(SUBDIR, exist_ok=True)
SUBDRAFT = payload(os.path.join('sub', 'm.txt'), 'fej ' + INV + '\n')
DEEP = 200000  # json raises RecursionError on this depth; the record must be skipped, not crash the hook
DEEP_LINE = json.dumps(own_use('mcp__x__y', {'k': 'PH'})).replace('"PH"', '[' * DEEP + '"' + INV + '"' + ']' * DEEP)


def run_lines(cmd, lines):
    p = os.path.join(TMP, 'deep.jsonl')
    with open(p, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    return run('', raw=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}, 'transcript_path': p,
                                   'cwd': TMP}))


CASES += [
    ('H1 a mistyped full sha, then the measured one: its prefix passes (P09)', lambda: run(MSG + '"fej 9b1e9239"', [
        own_use('Bash', {'command': 'git show ' + TYPO40}), tr_err('fatal: bad object ' + TYPO40),
        own_use('Bash', {'command': 'git rev-parse HEAD'}), tool_result(COMMIT + '\n')]), 0),
    ('H2 the mistyped full sha itself stays blocked', lambda: run(MSG + '"fej ' + TYPO40 + '"', [
        own_use('Bash', {'command': 'git show ' + TYPO40}), tr_err('fatal: bad object ' + TYPO40),
        own_use('Bash', {'command': 'git rev-parse HEAD'}), tool_result(COMMIT + '\n')]), 2),
    ('H3 cat of a quoted path', lambda: run(MSG + '"$(cat "' + DRAFT + '")"', BASE2), 2),
    ('H4 quoted positional file of send-stamped.sh', lambda: run('bash tools/send-stamped.sh dave klodel "' + DRAFT +
                                                               '"', BASE2), 2),
    ('H5 cd into a dir, then a relative file', lambda: run('cd sub && ' + MSG + '"$(cat m.txt)"', BASE2), 2),
    ('H6 a send after then / do / nice (no bash in front)', lambda: all_blocked(
        [c + ' scripts/agent-msg.sh k v "fej ' + INV + '"' for c in ('if true; then', 'for i in 1; do', 'nice -n 5')],
        BASE2), 2),
    ('H6b each of the three alone', lambda: (lambda rs: (2 if all(r[0] == 2 for r in rs) else 0, rs[-1][1]))(
        [run(c + ' scripts/agent-msg.sh k v "fej ' + INV + '"', BASE2) for c in ('if true; then', 'while :; do',
                                                                              'caffeinate -i')]), 2),
    ('H7 curl -T upload to /api/messages', lambda: run('curl -s -T ' + payload('up.json', '{"result":"fej ' + INV +
                                                                                  '"}') +
                                                       ' localhost:3420/api/messages/123', BASE2), 2),
    ('H8 $(cat f) in an unquoted heredoc body', lambda: run(MSG + '- <<EOF\n$(cat ' + DRAFT + ')\nEOF', BASE2), 2),
    ('H9 0< redirect', lambda: run(MSG + '- 0<' + DRAFT, BASE2), 2),
    ('H10 $(cat f) in a QUOTED heredoc body is text, not a read', lambda: run(
        MSG + "- <<'EOF'\n$(cat " + DRAFT + ")\nEOF", BASE2), 0),
    ('H11 a record too deep for json is skipped (blocked, no exit 1)', lambda: run_lines(
        MSG + '"fej ' + INV + '"', [DEEP_LINE]), 2),
    ('H12 an unforeseen error is a logged fail-open', lambda: failopen_case(lambda: run('', raw=json.dumps(
        {'tool_name': 'Bash', 'tool_input': {'command': MSG + '"ab12cd34ef" - < m2.txt'},
         'transcript_path': os.path.join(TMP, 't.jsonl'), 'cwd': 12})), 'internal-error'), 0),
    # card 3b05ae69: the send-script search is matched backwards from each script name, so a long run of a pattern
    # start (newline, '(', '{', backtick) or of a greedy piece no longer reads to the end from every position
    # (main: 20 KB of newlines in a card PUT 11 s, past the hook's 10 s timeout). Each run is 120 KB, the gate must
    # still BLOCK the invented hex after it, within 3 s.
] + [('T1 120 KB of %r before a card PUT with an invented hex blocks in time' % u,
      (lambda u: lambda: timed(CARD_PUT + u * (120000 // len(u)) + ' ab12cd34ef"}\''))(u), 2)
     for u in ('\n', '(a=', '`a=', 'a=(', '{', '${a}')] + [
    ('T2 120 KB of assignments then the script in command position blocks in time',
     lambda: timed('A=1 ' * 30000 + MSG + '"ab12cd34ef"'), 2),
    ('T3 120 KB of A=<script name> words then the script blocks in time',
     lambda: timed('A=agent-msg.sh ' * 8000 + MSG + '"ab12cd34ef"'), 2),
    ('T4 120 KB of " <script name>" words in argument position: not a send, in time',
     lambda: timed('echo' + ' agent-msg.sh' * 9000 + ' ab12cd34ef'), 0),
    ('T5 120 KB of "<< |" on one line, then a send on the next, blocks in time (main: quadratic heredoc-pipe search)',
     lambda: timed('<< |' * 30000 + ' x\n' + MSG + '"ab12cd34ef"'), 2),
    # the command positions the backward match must keep (each also as main's left-to-right search said)
    ('P1 keyword start: then <script>', lambda: run('if true; then bash scripts/agent-msg.sh k v "ab12cd34ef"; fi'), 2),
    ('P2 assignments, a duration and options before the script',
     lambda: run('A=1 B="x" timeout 5s nice -n 5 bash scripts/agent-msg.sh k v "ab12cd34ef"'), 2),
    ('P3 a start char glued to the path', lambda: run('(scripts/agent-msg.sh k v "ab12cd34ef")'), 2),
    ('P4 a quoted path', lambda: run('"/Users/x/scripts/agent-msg.sh" k v "ab12cd34ef"'), 2),
    ('P5 a word before the script that is no runner: not a send', lambda: run('cat scripts/agent-msg.sh ab12cd34ef'), 0),
    ('P6 a keyword glued to a word: not a send', lambda: run('xbash scripts/agent-msg.sh ab12cd34ef'), 0),
    ('P7 a longer name: not a send', lambda: run('bash scripts/agent-msg.shx ab12cd34ef'), 0),
    # the second cd starts at the newline although the '{' before it ends the first cd's word (random diff, seed 3)
    ('P8 a cd after a word ending in { still adds its directory', lambda: (
        os.makedirs(os.path.join(TMP, 'sub8'), exist_ok=True),
        open(os.path.join(TMP, 'sub8', 'm8.txt'), 'w').write('fej ab12cd34ef'),
        run('cd x{ \n cd sub8\n' + MSG + '- < m8.txt'))[-1], 2),
    ('P9 a cd whose start char lies inside the previous cd word is no cd (as main\'s finditer)', lambda: (
        os.makedirs(os.path.join(TMP, 'sub9'), exist_ok=True),
        open(os.path.join(TMP, 'sub9', 'm9.txt'), 'w').write('fej ab12cd34ef'),
        run('cd x{ cd sub9\n' + MSG + '- < m9.txt'))[-1], 0),
    ('P10 a cd at the very start adds its directory', lambda: (
        os.makedirs(os.path.join(TMP, 'sub10'), exist_ok=True),
        open(os.path.join(TMP, 'sub10', 'm10.txt'), 'w').write('fej ab12cd34ef'),
        run('cd sub10 && ' + MSG + '- < m10.txt'))[-1], 2),
    ('P11 then cd adds its directory', lambda: (
        os.makedirs(os.path.join(TMP, 'sub11'), exist_ok=True),
        open(os.path.join(TMP, 'sub11', 'm11.txt'), 'w').write('fej ab12cd34ef'),
        run('if true; then cd sub11 && ' + MSG + '- < m11.txt; fi'))[-1], 2),
    ('P12 a heredoc piped into a shell by path is a send', lambda: run(
        "cat <<'X' | /bin/bash\n" + MSG + '"fej ab12cd34ef"\nX'), 2),
    ('P13 a | into a shell on a later line than the << does not make the shell read the heredoc', lambda: run(
        "cat <<'X'\n" + MSG + '"fej ab12cd34ef"\nX\necho | bash'), 0),
    # mutation survivors of the first run (M8, M24, M27): each row needs exactly that piece
    ('P14 only an assignment before the script path at the start: a send', lambda: run(
        'A=1 scripts/agent-msg.sh k v "ab12cd34ef"'), 2),
    ('P15 a cd right after ; adds its directory', lambda: (
        os.makedirs(os.path.join(TMP, 'sub15'), exist_ok=True),
        open(os.path.join(TMP, 'sub15', 'm15.txt'), 'w').write('fej ab12cd34ef'),
        run('true;cd sub15 && ' + MSG + '- < m15.txt'))[-1], 2),
    ('P16 a << AFTER the | into a shell on the same line does not make the shell read the heredoc (as main)',
     lambda: run("echo x | bash -c 'cat' <<'X'\n" + MSG + '"fej ab12cd34ef"\nX'), 0),
]


def main():
    ok = 0
    for name, fn, want in CASES:
        try:
            rc, err = fn()
            good = rc == want and (want == 0 or 'HEX-FORRAS-KAPU' in err)
        except Exception as e:
            good, rc, err = False, -1, '%s: %s' % (type(e).__name__, e)
        ok += good
        print(('PASS ' if good else 'FAIL ') + name + ('' if good else ' (rc %s: %s)' % (rc, err.strip()[:150])))
    print('%d/%d passed' % (ok, len(CASES)))
    return 0 if ok == len(CASES) else 1


if __name__ == '__main__':
    sys.exit(main())
