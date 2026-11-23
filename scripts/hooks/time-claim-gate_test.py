#!/usr/bin/env python3
"""Tests for time-claim-gate.py (Klodel 38401).

Runs the hook as Claude Code does (PreToolUse JSON on stdin; exit 0 allow, 2 block) with a fixed
TIME_CLAIM_GATE_NOW. Most cases run a COPY of the hook in a throw-away root, so <root>/shared/ is a temp
directory and no file is created in the checkout; one case runs the real file to pin the root resolution.
Fixture dates are built from today's date, so the "same day" / "other day" cases hold on any day.
Run: python3 -I scripts/hooks/time-claim-gate_test.py
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REAL_HOOK = os.path.join(HERE, 'time-claim-gate.py')
TODAY = datetime.date.today()
TOMORROW = TODAY + datetime.timedelta(days=1)
KANBAN = 'curl -s -X POST http://localhost:3420/api/kanban/abc/comments -H "Content-Type: application/json"'


def make_root(tmp):
    hooks = os.path.join(tmp, 'scripts', 'hooks')
    os.makedirs(hooks)
    shutil.copy(REAL_HOOK, hooks)
    shutil.copy(os.path.join(HERE, 'hook_errlog.py'), hooks)
    os.makedirs(os.path.join(tmp, 'shared', 'x'))
    return os.path.join(hooks, 'time-claim-gate.py')


def run(hook, tool, tool_input=None, now='18:14', raw=None, cwd=None, errlog=None):
    env = {'PATH': '/usr/bin:/bin', 'TIME_CLAIM_GATE_NOW': now, 'HOOK_ERRLOG_PATH': errlog or os.devnull}
    if os.environ.get('TZ'):  # Viktor 49949 (3): the gate runs in the test's zone, so TZ=UTC measures the gate too
        env['TZ'] = os.environ['TZ']
    body = {'tool_name': tool, 'tool_input': tool_input}
    if cwd:
        body['cwd'] = cwd
    payload = raw if raw is not None else json.dumps(body)
    p = subprocess.run([sys.executable, '-I', hook], input=payload, capture_output=True, text=True, env=env, timeout=20)
    return p.returncode, p.stdout, p.stderr


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def write(root, text, name='x/report.md', **kw):
    return run(root['hook'], 'Write', {'file_path': os.path.join(root['dir'], 'shared', name), 'content': text}, **kw)



# ---- inter-agent message, memory, daily log (Dave 39699): placeholder rule only ----

MSG = "bash /Users/klodel/marveen/scripts/agent-msg.sh dave klodel - <<'TXT'\n"
API = 'curl -s -X POST http://localhost:3420/api/'


@case
def block_agent_msg_heredoc_placeholder(root):
    # Dave 39698, the case that went out: a placeholder measured time in a message to Klodel.
    code, out, err = run(root['hook'], 'Bash', {'command': MSG + 'Kész, mérve 16:3x date.\nTXT'})
    return code == 2 and '16:3x' in err and out == ''


@case
def block_wrapper_msg_and_close_placeholder(root):
    h = root['hook']
    return (run(h, 'Bash', {'command': "bash tools/kernel-msg.sh klodel - <<'TXT'\nlefutott 10:xx-kor\nTXT"})[0] == 2
            and run(h, 'Bash', {'command': 'bash tools/msg-close.sh "kész 09:4X" 123'})[0] == 2)


@case
def block_api_messages_memories_daily_log(root):
    h = root['hook']
    return all(run(h, 'Bash', {'command': API + ep + " --data-binary @- <<'JSON'\n{\"content\":\"mérve 11:2x\"}\nJSON"})[0] == 2
               for ep in ('messages', 'messages/77', 'memories', 'daily-log'))


@case
def block_message_body_from_data_file_and_stdin_file(root):
    body = os.path.join(root['dir'], 'body.txt')
    with open(body, 'w', encoding='utf-8') as fh:
        fh.write('Pulzus: élesben, mérve 14:5x.\n')
    h = root['hook']
    return (run(h, 'Bash', {'command': API + 'messages --data-binary @' + body})[0] == 2
            and run(h, 'Bash', {'command': 'bash scripts/agent-msg.sh pulzus klodel - < ' + body})[0] == 2
            and run(h, 'Bash', {'command': 'bash scripts/agent-msg.sh pulzus klodel - <body.txt',
                                'description': 'x'}, cwd=root['dir'])[0] == 2)  # relative: resolved against cwd


@case
def allow_message_far_future_time_is_a_plan(root):
    # 346 "future" hits in a week of real messages were plans, deadlines and reset times: allowed in a message
    # when more than SEND_WINDOW_MIN minutes ahead or on a plan line (rule 5 judges only the near future).
    h = root['hook']
    return all(run(h, 'Bash', {'command': MSG + t + '\nTXT'}, now='18:14')[0] == 0 for t in (
        'Mért: a keret 100 %, nullázás 23:36.',
        'mérve 18:10; deploy csak éjjel, 23:00 után',
        'Kész, ha 19:30, mért forgalom mellett.'))


@case
def allow_message_reads_and_clean_sends(root):
    h = root['hook']
    return (run(h, 'Bash', {'command': 'curl -s -H "Authorization: Bearer x" http://localhost:3420/api/messages?agent=kernel'})[0] == 0
            and run(h, 'Bash', {'command': MSG + 'Kész, mérve 18:12 (date).\nTXT'}, now='18:14')[0] == 0
            and run(h, 'Bash', {'command': 'python3 x.py 2>&1 | bash scripts/agent-msg.sh a b -'})[0] == 0)


MOVE = 'curl -s -X POST http://localhost:3420/api/kanban/abc/move -H "Content-Type: application/json"'


@case
def block_move_comment_placeholder(root):
    # Dave 49788, card 00c714ea, the move comment that went out with HTTP 200 (verbatim, today's date in place of
    # 2026-11-21 so the case holds on any day): the /move "comment" field is a card comment too.
    text = ('Mérőkör fut: work/00c714ea-r8 (teszt, neg, 6 mutáns, replay). (' + TODAY.isoformat() + ' 19:2x)')
    body = json.dumps({'status': 'waiting', 'comment': text})
    h = root['hook']
    return (run(h, 'Bash', {'command': MOVE + " --data-binary @- <<'J'\n" + body + "\nJ"}, now='19:30')[0] == 2
            and run(h, 'Bash', {'command': MOVE + " -d '" + body + "'"}, now='19:30')[0] == 2)


@case
def block_move_comment_future_and_from_data_file(root):
    # The card rules, not only the placeholder: a future measured time, and a body read from a data file.
    body = os.path.join(root['dir'], 'move.json')
    with open(body, 'w', encoding='utf-8') as fh:
        json.dump({'status': 'waiting', 'comment': 'VÁR: Dave - a review-ra, mérve 18:30'}, fh)
    return run(root['hook'], 'Bash', {'command': MOVE + ' --data-binary @' + body}, now='18:14')[0] == 2


def _tail(text):
    return text + ' (' + TODAY.isoformat() + ' 22:06)'


@case
def block_closing_stamp_ahead(root):
    # Rule 7, Dave 49852, card fec4c8c8: the move comment written at 22:04 ended "(<today> 22:06)" and passed
    # (no marker word for rule 2, rule 4 reads only the opening stamp). Verbatim shape, today's date.
    h = root['hook']
    verbatim = _tail('Mutáció kész: 27/28 KILLED (1 egyenértékű).')
    body = json.dumps({'status': 'waiting', 'comment': verbatim})
    py = ("python3 - <<'P'\nimport json, urllib.request\nd = {'author': 'dave', 'content': '"
          + _tail('Kör 3 kész') + "'}\nurllib.request.urlopen(urllib.request.Request("
          "'http://localhost:3420/api/kanban/abc/comments', json.dumps(d).encode()))\nP")
    shapes = [
        MOVE + " --data-binary @- <<'J'\n" + body + "\nJ",
        MOVE + " -d '" + body + "'",
        KANBAN + " -d '" + json.dumps({'author': 'dave', 'content': _tail('Kör 3 kész') + '.'}) + "'",
        KANBAN + " -d '" + json.dumps({'author': 'dave', 'content': 'Kör 3 kész (' + TODAY.isoformat() + 'T22:06:30) '}) + "'",
        KANBAN + " -d '" + json.dumps({'content': '1. sor\n2. sor ' + _tail('')}) + "'",
        PUT + " -d '" + json.dumps({'comment': _tail('VÁR: Viktor, 12. kör')}) + "'",
        py,
        # the closing quote escaped in a double-quoted -d, and a trailing newline (printf '%s\n' into the body)
        MOVE + ' -d "{\\"status\\":\\"waiting\\",\\"comment\\":\\"' + _tail('Kör 3 kész') + '\\"}"',
        KANBAN + " -d '" + json.dumps({'content': _tail('Kör 3 kész') + '\n'}) + "'",
        KANBAN + " --data-binary @- <<'J'\n" + json.dumps({'content': _tail('Kör 3 kész') + ' .\n\n'}) + "\nJ",
    ]
    return all(run(h, 'Bash', {'command': c}, now='22:04')[0] == 2 for c in shapes)


@case
def block_closing_stamp_from_data_file(root):
    body = os.path.join(root['dir'], 'tail.json')
    with open(body, 'w', encoding='utf-8') as fh:
        json.dump({'status': 'waiting', 'comment': _tail('VÁR: review, 3. kör')}, fh)
    p = run(root['hook'], 'Bash', {'command': MOVE + ' --data-binary @' + body}, now='22:04')
    return p[0] == 2 and 'closing comment stamp' in p[2]


@case
def allow_closing_stamp_not_ahead_or_not_a_stamp(root):
    h = root['hook']
    yesterday = (TODAY - datetime.timedelta(days=1)).isoformat()
    ok = [
        (KANBAN + " -d '" + json.dumps({'content': _tail('Kör 3 kész')}) + "'", '22:06'),  # same minute
        (KANBAN + " -d '" + json.dumps({'content': _tail('Kör 3 kész')}) + "'", '22:07'),
        (KANBAN + " -d '" + json.dumps({'content': 'Kör 3 kész (' + TODAY.isoformat() + ' 21:30)'}) + "'", '22:04'),  # past
        (KANBAN + " -d '" + json.dumps({'content': 'Kör 3 kész (' + yesterday + ' 22:06)'}) + "'", '22:04'),  # another day
        (KANBAN + " -d '" + json.dumps({'content': 'Kör 3: partner-levelek (22:06).'}) + "'", '22:04'),  # time only: a plan
        (KANBAN + " -d '" + json.dumps({'content': _tail('Kör 3 kész') + ' után indul a kör'}) + "'", '22:04'),  # not the end
        (KANBAN + " -d '" + json.dumps({'content': _tail('Kör 3 kész'), 'x': 1}) + "'", '22:06'),
        (MOVE + " -d '" + json.dumps({'status': 'done', 'comment': 'Kör 3 kész ' + TODAY.isoformat() + ' 22:06'}) + "'",
         '22:04'),  # no parentheses
        (API + "memories -d '" + json.dumps({'agent_id': 'dave', 'content': _tail('Kör 3 kész')}) + "'",
         '22:04'),  # not a card comment (a memory: placeholder rule only)
        (PUT + " -d '" + json.dumps({'description': _tail('terv')}) + "'", '22:04'),  # no comment key: not a comment
    ]
    return all(run(h, 'Bash', {'command': c}, now=n)[0] == 0 for c, n in ok)


def _zoned_stamps(hh=22, mm=6):
    """Today's local hh:mm written with an offset, as UTC with Z, and as UTC (the date may differ): the gate turns
    each back into local time, so the cases hold in any machine zone (a UTC CI runner too)."""
    import time as _t
    ts = _t.mktime((TODAY.year, TODAY.month, TODAY.day, hh, mm, 0, 0, 0, -1))
    off = _t.localtime(ts).tm_gmtoff // 60
    sign = '+' if off >= 0 else '-'
    local = f'{TODAY.isoformat()}T{hh:02d}:{mm:02d}'
    utc = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
    return [f'({local}:00{sign}{abs(off) // 60:02d}:{abs(off) % 60:02d})', f'({utc:%Y-%m-%dT%H:%M:%S}Z)',
            f'({utc:%Y-%m-%dT%H:%M:%S}.250Z)', f'({utc:%Y-%m-%d %H:%M} UTC)']


@case
def block_closing_stamp_round2_shapes(root):
    # Viktor 49927: T2 time zones (an offset, Z, a fraction, a UTC name), T3 a JSON-escaped CRLF, and his probe's
    # py-dict-call-last, md-bold, md-code, a doubled backslash-n in a double-quoted -d, and py-concat.
    h = root['hook']
    ok = True
    for stamp in _zoned_stamps():
        ok &= run(h, 'Bash', {'command': KANBAN + " -d '" + json.dumps({'content': 'Kör 3 kész ' + stamp}) + "'"},
                  now='22:04')[0] == 2
    py = "python3 - <<'P'\nimport json, urllib.request\n{}\nurllib.request.urlopen(urllib.request.Request(" \
         "'http://localhost:3420/api/kanban/abc/comments', json.dumps(d).encode()))\nP"
    shapes = [
        KANBAN + " -d '{\"content\":\"Kör 3 kész " + _tail('').strip() + "\\r\\n\"}'",
        py.format("d = dict(author='dave', content='Kör 3 kész " + _tail('').strip() + "')"),
        KANBAN + " -d '" + json.dumps({'content': 'Kör 3 kész **' + _tail('').strip() + '**'}) + "'",
        KANBAN + " -d '" + json.dumps({'content': 'Kör 3 kész `' + _tail('').strip() + '`'}) + "'",
        MOVE + ' -d "{\\"status\\":\\"waiting\\",\\"comment\\":\\"' + _tail('Kör 3 kész') + '\\\\n\\"}"',
        py.format("d = {'content': 'Kör 3 kész' + ' " + _tail('').strip() + "'}"),
    ]
    for c in shapes:
        ok &= run(h, 'Bash', {'command': c}, now='22:04')[0] == 2
    return ok


@case
def closing_stamp_after_an_escaped_quote_in_a_double_quoted_d(root):
    # Viktor 49939 dq-escquote-before-stamp: in a double-quoted -d a JSON-escaped quote is \\\" in the command; the
    # value runs past it to the stamp (BLOCK), and still ends at its own \" so a later title's stamp is not read.
    h = root['hook']
    stamp = _tail('').strip()
    block = [
        MOVE + r' -d "{\"status\":\"waiting\",\"comment\":\"27/28 \\\"kész\\\" ' + stamp + r'\"}"',
        KANBAN + r' -d "{\"author\":\"kernel\",\"content\":\"27/28 \\\"kész\\\" ' + stamp + r'\"}"',
        KANBAN + r' -d "{\"content\":\"Kör 3 \\\\\\\"idézet\\\\\\\" kész ' + stamp + r'\"}"',
    ]
    allow = [
        PUT + r' -d "{\"comment\":\"27/28 \\\"kész\\\"\",\"title\":\"Teszt 2 ' + stamp + r'\"}"',
        KANBAN + r' -d "{\"content\":\"27/28 \\\"kész\\\" rendben\",\"author\":\"viktor ' + stamp + r'\"}"',
    ]
    ok = all(run(h, 'Bash', {'command': c}, now='22:04')[0] == 2 for c in block)
    return ok and all(run(h, 'Bash', {'command': c}, now='22:04')[0] == 0 for c in allow)


@case
def closing_stamp_in_a_subscript_a_bare_key_or_a_prefixed_literal(root):
    # Viktor 49939 item 2: py-fstring, py-subscript, js-bare-key, jq-bare-key (BLOCK); the same shapes on a title
    # key, and a longer word ending in "content", pass.
    h = root['hook']
    stamp = _tail('').strip()
    py = "python3 - <<'P'\nimport json, urllib.request\n{}\nurllib.request.urlopen(urllib.request.Request(" \
         "'http://localhost:3420/api/kanban/abc/comments', json.dumps(body).encode()))\nP"
    node = ("node -e 'fetch(\"http://localhost:3420/api/kanban/abc/comments\",{{method:\"POST\","
            "body:JSON.stringify({{author:\"kernel\",{}:\"27/28 kész " + stamp + "\"}})}})'")
    jq = ("jq -n '{{author:\"kernel\",{}:\"27/28 kész " + stamp + "\"}}' | curl -s -X POST "
          "http://localhost:3420/api/kanban/abc/comments --data-binary @-")
    block = [
        py.format("n = 27\nbody = {'author': 'kernel', 'content': f'{n}/28 kész " + stamp + "'}"),
        py.format("body = {'author': 'kernel'}\nbody['content'] = '27/28 kész " + stamp + "'"),
        py.format("body = {}\nbody[\"comment\"] = rb'27/28 kész " + stamp + "'"),
        node.format('content'),
        jq.format('content'),
    ]
    allow = [
        py.format("body = {'content': '27/28 kész'}\nbody['title'] = 'Teszt 2 " + stamp + "'"),
        node.format('title'),
        jq.format('discontent'),
    ]
    ok = all(run(h, 'Bash', {'command': c}, now='22:04')[0] == 2 for c in block)
    return ok and all(run(h, 'Bash', {'command': c}, now='22:04')[0] == 0 for c in allow)


def _zst(hh, mm, zone_off, suffix, sep=' ', secs=''):
    """A stamp whose LOCAL time is today hh:mm, written in a zone zone_off minutes from UTC (Viktor's zst)."""
    import time as _t
    loc = _t.localtime(_t.mktime((TODAY.year, TODAY.month, TODAY.day, hh, mm, 0, 0, 0, -1))).tm_gmtoff // 60
    d = datetime.datetime.combine(TODAY, datetime.time(hh, mm)) - datetime.timedelta(minutes=loc - zone_off)
    return f'({d:%Y-%m-%d}{sep}{d:%H:%M}{secs}{suffix})'


@case
def closing_stamp_round3_ends_zones_separators_and_concatenation(root):
    # Viktor 49939 item 3: a closing ! ? ; ] emoji, zero-width space, nested paren or escaped quote after the stamp;
    # utc in lower case, UTC+1, a bare +HH, a 9-digit fraction, a stamp written today that lands on tomorrow here;
    # two blanks or a comma before the time; a name in a concatenation, adjacent literals (BLOCK). A zoned stamp
    # written today that lands on yesterday, an unknown or offset non-UTC zone, a past UTC+1, a stamp in the
    # middle (ALLOW).
    h = root['hook']
    s, t = _tail('').strip(), TODAY.isoformat()

    def j(val):
        return KANBAN + " --data-binary @- <<'J'\n" + json.dumps({'author': 'kernel', 'content': val},
                                                                   ensure_ascii=False) + '\nJ'
    py = "python3 - <<'P'\nimport json, urllib.request\n{}\nurllib.request.urlopen(urllib.request.Request(" \
         "'http://localhost:3420/api/kanban/abc/comments', json.dumps(body).encode()))\nP"
    block = [j('27/28 kész ' + s + e) for e in ('!', '?', ';', ' ✅', '​')] + [
        j('[27/28 kész ' + s + ']'),
        j('27/28 kész (review ok ' + s + ')'),
        KANBAN + " -d '" + r'{"content":"27/28 \"kész ' + s + r'\""}' + "'",
        j('27/28 kész ' + _zst(22, 6, 0, ' utc')),
        j('27/28 kész ' + _zst(22, 6, 60, ' UTC+1')),
        j('27/28 kész ' + _zst(22, 6, 60, '+01')),
        j('27/28 kész ' + _zst(22, 6, 0, 'Z', 'T', ':05.123456789')),
        j('27/28 kész (' + t + ' 23:30 -05:00)'),
        j('27/28 kész (' + t + '  22:06)'),
        j('27/28 kész (' + t + ', 22:06)'),
        py.format("n = '27'\nbody = {'author': 'kernel', 'content': '27/28 ' + n + ' kész " + s + "'}"),
        py.format("body = {'author': 'kernel', 'content': '27/28 kész' ' " + s + "'}"),
    ]
    allow = [
        j('27/28 kész (' + t + ' 12:30 +14:00)'),
        j('27/28 kész (' + t + ' 22:06 PST)'),
        j('27/28 kész ' + _zst(22, 6, 120, ' CET+1')),
        j('27/28 kész ' + _zst(21, 30, 60, ' UTC+1')),
        j('27/28 kész (review ok ' + s + ') és tovább'),
    ]
    bad = [c for c in block if run(h, 'Bash', {'command': c}, now='22:04')[0] != 2]
    bad += [c for c in allow if run(h, 'Bash', {'command': c}, now='22:04')[0] != 0]
    for c in bad:
        print('  round3 wrong verdict:', c[-90:].replace('\n', ' | '))
    return not bad


@case
def closing_stamp_after_a_marked_deadline_word(root):
    # Viktor 49939 dl-bold-deadline (an overblock): a deadline word in markdown marks passes like a bare one; a bold
    # word that is not a deadline still blocks.
    h = root['hook']
    s = _tail('').strip()

    def j(val):
        return KANBAN + " -d '" + json.dumps({'content': val}, ensure_ascii=False) + "'"
    return (all(run(h, 'Bash', {'command': j(v)}, now='22:04')[0] == 0
                for v in ('27/28 **deadline** ' + s, '27/28 _határidő_: ' + s, '27/28 `until` ' + s))
            and run(h, 'Bash', {'command': j('27/28 **kész** ' + s)}, now='22:04')[0] == 2)


@case
def round2_key_shapes_outside_a_posted_object_pass(root):
    # Viktor 49949 R1 (8 overblocks of round 1): a bare "comment:" / "content:" counts only as an object-literal key
    # (after { or a comma), a subscript only on the posted dict, an adjacent literal only before a closing mark. A
    # title text, the comment's own middle, a shell comment, a YAML heredoc, a markdown list line, a git message,
    # another dict, and the next shell word pass; the comment itself is clean.
    h = root['hook']
    s = _tail('').strip()
    clean = KANBAN + " -d '{\"content\":\"1 ok\"}'"
    py = "python3 - <<'P'\nimport json, urllib.request\n{}\nurllib.request.urlopen(urllib.request.Request(" \
         "'http://localhost:3420/api/kanban/abc/comments', json.dumps(body).encode()))\nP"
    allow = [
        PUT + " -d '" + json.dumps({'title': "9 Re comment: 'átnézve " + s + "' marad", 'comment': '1 ok'},
                                   ensure_ascii=False) + "'",
        py.format("body = {'content': '3 átírva: comment: \"vázlat " + s + "\" helyett végleges'}"),
        '# comment: "vázlat ' + s + '"\n' + clean,
        "cat > notes.yml <<'EOF'\ncomment: \"9 jegyzet " + s + "\"\nEOF\n" + clean,
        "cat > plan.md <<'EOF'\n- content: \"9 terv " + s + "\"\nEOF\n" + clean,
        'git commit -m "content: \'rendrakás ' + s + '\'" && ' + clean,
        py.format("meta = {}\nmeta['content'] = '9 cache " + s + "'\nbody = {'content': '1 ok'}"),
        'echo comment="1 ok" "más ' + s + '" >> log.txt\n' + clean,
    ]
    bad = [c for c in allow if run(h, 'Bash', {'command': c}, now='22:04')[0] != 0]
    for c in bad:
        print('  round2 overblock:', c[:90].replace('\n', ' | '))
    return not bad


@case
def round2_closing_stamp_shapes_that_block(root):
    # Viktor 49949 new fail-opens: a hyphen-word before the stamp (stand-by) is no deadline, a call in a concatenation,
    # jq's .comment = "...", a Python triple-quoted value, a JS template literal, and a chain of adjacent literals.
    h = root['hook']
    s = _tail('').strip()
    py = "python3 - <<'P'\nimport json, urllib.request\n{}\nurllib.request.urlopen(urllib.request.Request(" \
         "'http://localhost:3420/api/kanban/abc/comments', json.dumps(body).encode()))\nP"
    block = [
        KANBAN + " -d '" + json.dumps({'content': '1 szerver stand-by ' + s}) + "'",
        py.format("n = 27\nbody = {'content': 'kész ' + str(n) + ' " + s + "'}"),
        "jq -n '.comment = \"2 kész " + s + "\"' | curl -s -X PUT http://localhost:3420/api/kanban/abc --data-binary @-",
        py.format("body = {'content': \x27\x27\x2727/28 kész " + s + "\x27\x27\x27}"),
        "node -e 'fetch(\"http://localhost:3420/api/kanban/abc/comments\", {method: \"POST\", "
        "body: JSON.stringify({content: `27/28 kész " + s + "`})})'",
        py.format("body = {'content': '1'" + " 'a'" * 40 + " ' " + s + "'}"),
        "python3 - <<'P'\nimport requests\nbody = {}\nbody['comment'] = '27/28 kész " + s + "'\n"
        "requests.post('http://localhost:3420/api/kanban/abc/comments', json=body)\nP",
    ]
    bad = [c for c in block if run(h, 'Bash', {'command': c}, now='22:04')[0] != 2]
    for c in bad:
        print('  round2 fail-open:', c[:90].replace('\n', ' | '))
    return not bad


@case
def round3_subscripts_scale_and_data_dumps_counts_as_posted(root):
    # Viktor 49952 R2: a re.search per subscript match re-read the whole command (300 KB of x['content'] = 'a' lines
    # took 62 s, the hook timeout is 10 s). The posted names are read once; a posted name's future stamp after the
    # run still blocks, an unposted name's run passes, each under 3 s. data=json.dumps(x) posts x (the data= branch
    # must not take "json" as the posted name).
    import time as _t
    h = root['hook']
    s = _tail('').strip()
    n = 300 * 1024 // len("x['content'] = 'a'\n")
    post = "requests.post('http://localhost:3420/api/kanban/abc/comments', {})"

    def py(body):
        return "python3 - <<'P'\nimport json, requests\n" + body + "\nP"
    rows = [
        (0, py("x = {}\n" + "x['content'] = 'a'\n" * n + "body = {'content': '1 ok'}\n" + post.format('json=body'))),
        (0, py("".join(f"x{i % 97}['comment'] = 'a'\n" for i in range(n)) + "body = {'content': '1 ok'}\n"
               + post.format('json=body'))),
        (2, py("body = {}\n" + "body['content'] = 'a'\n" * n + "body['content'] = '27/28 kész " + s + "'\n"
               + post.format('json=body'))),
        (2, py("x = {}\nx['comment'] = '27/28 kész " + s + "'\n" + post.format('data=json.dumps(x)'))),
    ]
    ok = True
    for want, cmd in rows:
        t0 = _t.monotonic()
        got = run(h, 'Bash', {'command': cmd}, now='22:04')[0]
        took = _t.monotonic() - t0
        if got != want or took >= 3:
            ok = False
            print(f'  round3: want {want} got {got} in {took:.2f} s, {len(cmd)} bytes:', cmd[-90:].replace('\n', ' | '))
    return ok


@case
def zoned_rows_hold_under_utc_and_tokyo(root):
    # Viktor 49949 (3): the zone branch with the gate in another machine zone (TZ passed by run()), as on a UTC CI
    # runner and far east; the stamps and today's date are computed in that zone.
    import time as _t
    h = root['hook']
    saved = os.environ.get('TZ')
    ok = True
    try:
        for zone in ('UTC', 'Asia/Tokyo'):
            os.environ['TZ'] = zone
            _t.tzset()
            d = datetime.date.fromtimestamp(_t.time())
            ts = _t.mktime((d.year, d.month, d.day, 22, 6, 0, 0, 0, -1))
            off = _t.localtime(ts).tm_gmtoff // 60
            utc = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
            sign = '+' if off >= 0 else '-'
            zoned = f'({d.isoformat()}T22:06:00{sign}{abs(off) // 60:02d}:{abs(off) % 60:02d})'
            block = [f'({d.isoformat()} 22:06)', zoned, f'({utc:%Y-%m-%dT%H:%M:%S}Z)', f'({utc:%Y-%m-%d %H:%M} utc)']
            allow = [f'({d.isoformat()} 21:00)', f'({utc - datetime.timedelta(hours=2):%Y-%m-%dT%H:%M}Z)']

            def j(stamp):
                return KANBAN + " -d '" + json.dumps({'content': '27/28 kész ' + stamp}) + "'"
            got_b = [run(h, 'Bash', {'command': j(x)}, now='22:04')[0] for x in block]
            got_a = [run(h, 'Bash', {'command': j(x)}, now='22:04')[0] for x in allow]
            if got_b != [2] * len(block) or got_a != [0] * len(allow):
                print('  zone', zone, 'block rc', got_b, 'allow rc', got_a)
                ok = False
    finally:
        if saved is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = saved
        _t.tzset()
    return ok


@case
def allow_closing_stamp_outside_the_comment_value(root):
    # Viktor 49927 T1 (a regression of round 1): only the content / comment value is read; a title, description or
    # author ending in a stamp passes (his A-put-title, A-put-title-first, A-comment-author), and so does a
    # deadline. Known limits pinned: the text in a Python variable (py-var) and jq --arg (jq-arg).
    h = root['hook']
    stamp = _tail('').strip()
    py_var = ("python3 - <<'P'\nimport json, urllib.request\nc = 'Kör 3 kész " + stamp + "'\nd = {'content': c}\n"
              "urllib.request.urlopen(urllib.request.Request('http://localhost:3420/api/kanban/abc/comments', "
              "json.dumps(d).encode()))\nP")
    jq_arg = ("jq -n --arg c 'Kör 3 kész " + stamp + "' '{content: $c}' | curl -s -X POST "
              "http://localhost:3420/api/kanban/abc/comments --data-binary @-")
    cases = [
        PUT + " -d '" + json.dumps({'comment': 'Kör 3 rendben', 'title': 'Teszt 2 ' + stamp}) + "'",
        PUT + " -d '" + json.dumps({'title': 'Teszt 2 ' + stamp, 'comment': 'Kör 3 rendben'}) + "'",
        KANBAN + " -d '" + json.dumps({'content': 'Kör 3 rendben', 'author': 'viktor ' + stamp}) + "'",
        KANBAN + " -d '" + json.dumps({'content': 'Kör 3: 2 tétel, határidő ' + stamp}) + "'",
        py_var,
        jq_arg,
    ]
    return all(run(h, 'Bash', {'command': c}, now='22:04')[0] == 0 for c in cases)


@case
def closing_stamp_same_as_opening_is_reported_once(root):
    text = '22:06 kész (' + TODAY.isoformat() + ' 22:06)'
    p = run(root['hook'], 'Bash', {'command': KANBAN + " -d '" + json.dumps({'content': text}) + "'"}, now='22:04')
    return p[0] == 2 and p[2].count('"22:06"') == 1


@case
def allow_move_clean_and_without_comment(root):
    h = root['hook']
    return (run(h, 'Bash', {'command': MOVE + ' -d \'{"status":"done"}\''})[0] == 0
            and run(h, 'Bash', {'command': MOVE + " -d '" + json.dumps(
                {'status': 'waiting', 'comment': 'VÁR: Dave - a review-ra, mérve 18:12'}) + "'"}, now='18:14')[0] == 0)


PUT = 'curl -s -X PUT http://localhost:3420/api/kanban/abc -H "Content-Type: application/json"'


@case
def block_put_card_comment_placeholder_inline_and_data_file(root):
    # PUT /api/kanban/<id> stores its "comment" field like a move (src/web/routes/kanban.ts storeMoveComment).
    body = os.path.join(root['dir'], 'put.json')
    with open(body, 'w', encoding='utf-8') as fh:
        json.dump({'status': 'waiting', 'comment': 'VÁR: Dave - mérve 19:2x'}, fh)
    h = root['hook']
    return (run(h, 'Bash', {'command': PUT + " -d '" + json.dumps({'comment': 'kész, mérve 19:2x'}) + "'"}, now='19:30')[0] == 2
            and run(h, 'Bash', {'command': PUT + ' --data-binary @' + body}, now='19:30')[0] == 2)


@case
def allow_put_card_edit_without_comment_keeps_plan_times(root):
    # A title or description edit is not a comment: a plan time in it passes, as before.
    return run(root['hook'], 'Bash', {'command': PUT + " -d '" + json.dumps(
        {'description': 'Deploy éjjel, 23:00 után; határidő 22:30.'}) + "'"}, now='18:14')[0] == 0


@case
def allow_put_card_edit_without_comment_is_not_judged_as_a_comment(root):
    # Without "comment" the PUT is not a card comment: a near-future "mérve" time that the card rule blocks
    # (card_comment_keeps_the_future_rule) passes in a description edit, inline and from a data file.
    body = os.path.join(root['dir'], 'put-desc.json')
    with open(body, 'w', encoding='utf-8') as fh:
        json.dump({'description': 'mérve 18:30'}, fh)
    h = root['hook']
    return (run(h, 'Bash', {'command': PUT + " -d '" + json.dumps({'description': 'mérve 18:30'}) + "'"}, now='18:14')[0] == 0
            and run(h, 'Bash', {'command': PUT + ' --data-binary @' + body}, now='18:14')[0] == 0)


KB = 'http://localhost:3420/api/kanban/abc'


def _ph(text='kész 19:2x'):
    return json.dumps({'comment': text})


@case
def block_move_and_put_comment_opening_stamp_ahead(root):
    # Viktor 49811 L1: rule 4 (the comment's own opening time) reads a move's / PUT's "comment" value too; no
    # marker word needed. The same text on /comments was blocked already.
    h = root['hook']
    body = json.dumps({'status': 'waiting', 'comment': 'Viktor 18:44 VÁR: Dave - delta'})
    return (run(h, 'Bash', {'command': MOVE + " -d '" + body + "'"}, now='18:14')[0] == 2
            and run(h, 'Bash', {'command': PUT + " -d '" + body + "'"}, now='18:14')[0] == 2
            and run(h, 'Bash', {'command': MOVE + " -d '" + json.dumps(
                {'status': 'waiting', 'comment': 'Viktor 18:10 VÁR: Dave - delta'}) + "'"}, now='18:14')[0] == 0)


@case
def block_put_method_shapes(root):
    # Viktor 49811 L2 and I1 (M04, M05, M18): every way curl takes PUT, quoted, glued, tabbed, continued.
    h = root['hook']
    cmds = ["curl -s -X 'PUT' " + KB, 'curl -s -X "PUT" ' + KB, "curl -s -X'PUT' " + KB, 'curl -s --request "PUT" ' + KB,
            'curl -s -XPUT ' + KB, 'curl -s --request PUT ' + KB, 'curl -s -X\tPUT ' + KB,
            'curl -s -X \\\nPUT ' + KB, 'curl -s --request \\\n  PUT ' + KB]
    return all(run(h, 'Bash', {'command': c + " -d '" + _ph() + "'"}, now='19:30')[0] == 2 for c in cmds)


@case
def block_put_comment_key_shapes(root):
    # Viktor 49811 L2: the comment key escaped in a double-quoted -d, as a Python dict key, bare in jq.
    h = root['hook']
    return (run(h, 'Bash', {'command': PUT + ' -d "{\\"comment\\":\\"kész 19:2x\\"}"'}, now='19:30')[0] == 2
            and run(h, 'Bash', {'command': "python3 -c \"import json; print(json.dumps({'comment': 'kész 19:2x'}))\" | "
                                           + PUT + ' -d @-'}, now='19:30')[0] == 2
            and run(h, 'Bash', {'command': "jq -n '{comment: \"kész 19:2x\"}' | " + PUT + ' -d @-'}, now='19:30')[0] == 2)


@case
def block_put_relative_data_file_and_stdin_redirect(root):
    # I1 (M09, M17): a relative @file against the payload cwd; P5: a `< file` stdin body; P4: --json @file.
    with open(os.path.join(root['dir'], 'put-rel.json'), 'w', encoding='utf-8') as fh:
        fh.write(_ph())
    h = root['hook']
    return (run(h, 'Bash', {'command': PUT + ' -d @put-rel.json'}, now='19:30', cwd=root['dir'])[0] == 2
            and run(h, 'Bash', {'command': PUT + ' -d @- < put-rel.json'}, now='19:30', cwd=root['dir'])[0] == 2
            and run(h, 'Bash', {'command': MOVE + ' --json @put-rel.json'}, now='19:30', cwd=root['dir'])[0] == 2)


@case
def allow_comment_key_outside_a_card_comment(root):
    # I1 overblock side (M06, M12, M21): a comment key in a kanban call that stores no comment, and a PUT to
    # another API, is not a card comment; a near-future "mérve" time that the card rule blocks passes there.
    h = root['hook']
    body = " -d '" + json.dumps({'title': 'x', 'comment': 'mérve 18:30'}) + "'"
    return all(run(h, 'Bash', {'command': c + body}, now='18:14')[0] == 0 for c in (
        'curl -s -X POST http://localhost:3420/api/kanban',
        'curl -s -X POST http://localhost:3420/api/kanban/abc/archive',
        'curl -s -X PATCH ' + KB,
        'curl -s -X PUT http://localhost:3420/api/agents/abc'))


@case
def put_many_data_file_args_judged_once(root):
    # Viktor 49811 L3: 51000 `-d @g` (a 4 KB file with the comment key) took 24 s on 8ade408e, over the 10 s hook
    # limit; the data files are deduplicated and capped (MAX_SHELL_TARGETS), so it is one read.
    g = os.path.join(root['dir'], 'g.json')
    with open(g, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps({'comment': 'VÁR: Dave - ' + 'x' * 4000}))
    import time
    t = time.monotonic()
    code = run(root['hook'], 'Bash', {'command': PUT + (' -d @' + g) * 51000}, now='19:30')[0]
    took = time.monotonic() - t
    # The same without a comment key (a description edit): the comment check must not read the file 51000 times.
    d = os.path.join(root['dir'], 'd.json')
    with open(d, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps({'description': 'x' * 4000}))
    t = time.monotonic()
    code2 = run(root['hook'], 'Bash', {'command': PUT + (' -d @' + d) * 51000}, now='19:30')[0]
    if not (code == 0 and code2 == 0 and took < 3.0 and time.monotonic() - t < 3.0):
        return False
    # Counted, not timed (a 4 KB read is too cheap to time): the comment check reads each data file once, at most
    # MAX_SHELL_TARGETS of them, however often the command names it.
    import importlib.util
    spec = importlib.util.spec_from_file_location('tcg_count', root['hook'])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    reads, orig = [], mod._read_small
    mod._read_small = lambda p: reads.append(p) or orig(p)
    names = [os.path.join(root['dir'], f'n{i}.json') for i in range(mod.MAX_SHELL_TARGETS + 5)]
    for p in names:
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write('{}')
    mod.judged_texts('Bash', {'command': PUT + (' -d @' + d) * 500 + ''.join(' -d @' + p for p in names)}, root['dir'])
    return reads.count(d) == 1 and len(set(reads)) <= mod.MAX_SHELL_TARGETS


@case
def block_put_combined_switch_and_code_method(root):
    # Viktor 49824 L4: curl's combined short switches (-sX, -fsSX); L5: a PUT from code (python urllib
    # method='PUT', node fetch method:'PUT') with a comment key.
    h = root['hook']
    py = ("python3 -c \"import json, urllib.request as u; u.urlopen(u.Request('" + KB + "', data=json.dumps("
          "{'comment': 'kész 19:2x'}).encode(), method='PUT'))\"")
    node = "node -e \"fetch('" + KB + "', {method: 'PUT', body: JSON.stringify({comment: 'kész 19:2x'})})\""
    return all(run(h, 'Bash', {'command': c}, now='19:30')[0] == 2 for c in (
        'curl -sX PUT ' + KB + " -d '" + _ph() + "'", 'curl -fsSX PUT ' + KB + " -d '" + _ph() + "'", py, node))


@case
def block_put_stdin_redirects_deduplicated(root):
    # Viktor 49824 L6: 21 identical `< same.json` must not fill MAX_SHELL_TARGETS and hide the next, bad file.
    with open(os.path.join(root['dir'], 'same.json'), 'w', encoding='utf-8') as fh:
        fh.write(_ph('VÁR: Dave - delta'))
    with open(os.path.join(root['dir'], 'bad.json'), 'w', encoding='utf-8') as fh:
        fh.write(_ph())
    cmd = PUT + ' -d @-' + ' < same.json' * 21 + ' < bad.json'
    return run(root['hook'], 'Bash', {'command': cmd}, now='19:30', cwd=root['dir'])[0] == 2


@case
def allow_no_overblock_on_lt_text_desc_word_and_quoted_put(root):
    # Viktor 49824 L7 (all passed on the parent): a "<b>" / "<notes.md>" in a comment is not a stdin file when
    # curl does not read stdin (no @-); "comment:" as a word in a description is not a key; a message, a close
    # result or a memory that quotes a kanban PUT is judged on its own path, not as a card comment.
    for name in ('b', 'notes.md'):
        with open(os.path.join(root['dir'], name), 'w', encoding='utf-8') as fh:
            fh.write('mérve 19:2x\n')
    h = root['hook']
    lt = [MOVE + " -d '" + json.dumps({'status': 'waiting', 'comment': 'VÁR: Dave - a <b> rész'}) + "'",
          MOVE + " -d '" + json.dumps({'status': 'waiting', 'comment': 'VÁR: Dave - lásd <notes.md>'}) + "'"]
    quoted = 'curl -X PUT ' + KB + ' -d {"comment": "mérve 18:40"}'
    others = [PUT + " -d '" + json.dumps({'description': 'Review comment: mérve 18:40'}) + "'",
              "bash scripts/agent-msg.sh kernel klodel 'példa: " + quoted + "'",
              "bash tools/msg-close.sh 'példa: " + quoted + "' 77",
              API + "memories -d '" + json.dumps({'agent_id': 'kernel', 'content': 'példa: ' + quoted}) + "'"]
    # without @- curl does not read stdin: a `< file` holding a comment key does not make a description edit a comment
    with open(os.path.join(root['dir'], 'c.json'), 'w', encoding='utf-8') as fh:
        fh.write(_ph('ok'))
    lt.append(PUT + " -d '" + json.dumps({'description': 'mérve 19:50'}) + "' < c.json")
    return (all(run(h, 'Bash', {'command': c}, now='19:30', cwd=root['dir'])[0] == 0 for c in lt)
            and all(run(h, 'Bash', {'command': c}, now='18:14')[0] == 0 for c in others))


@case
def block_put_next_to_message_close_memory_or_log_write(root):
    # Viktor 49831 L8 (a regression of 49824 R3): a real kanban PUT with a comment was let through whenever the same
    # command also closed a message or wrote a memory / the daily log, a common closing step. Only a curl segment
    # whose own URL is /api/kanban/ counts, so the quoted PUTs of the test above still pass.
    bad4 = json.dumps({'status': 'done', 'comment': 'Kernel 18:44: kész'})
    bad2 = json.dumps({'status': 'done', 'comment': 'Kész, mérve 18:44'})
    with open(os.path.join(root['dir'], 'put4.json'), 'w', encoding='utf-8') as fh:
        fh.write(bad4)
    h = root['hook']
    mem = json.dumps({'agent_id': 'kernel', 'content': 'Kártya lezárva.', 'category': 'warm'})
    log = json.dumps({'agent_id': 'kernel', 'content': '## {{NOW}} -- Kártya\nok'})
    cmds = ["curl -s -X PUT http://localhost:3420/api/messages/77 -d '{\"status\":\"done\"}' && "
            + PUT + " -d '" + bad4 + "'",
            'curl -sX PUT ' + KB + " -d '" + bad2 + "' && bash /Users/klodel/marveen/scripts/agent-msg.sh kernel klodel"
            + ' "Kártya kész."',
            'curl -sX PUT ' + KB + " -d '" + bad2 + "'\n" + API + "memories --data-binary @- <<'JSON'\n" + mem + '\nJSON',
            'curl -sX PUT ' + KB + ' --data-binary @put4.json && ' + API + "daily-log --data-binary @- <<'JSON'\n"
            + log + '\nJSON']
    clean = ("curl -s -X PUT http://localhost:3420/api/messages/77 -d '{\"status\":\"done\"}' && "
             + PUT + " -d '" + json.dumps({'status': 'done', 'comment': 'Kernel 18:10: kész'}) + "'")
    return (all(run(h, 'Bash', {'command': c}, now='18:14', cwd=root['dir'])[0] == 2 for c in cmds)
            and run(h, 'Bash', {'command': clean}, now='18:14')[0] == 0)


@case
def put_segment_shapes_next_to_a_message_close(root):
    # The curl segment of L8 in the shapes a real command has: an env prefix (NO_PROXY=... curl), a backtick
    # substitution, and a multi-line curl whose -X PUT is on a backslash-continued line. And the other side: a
    # kanban GET (its segment has no PUT) next to a message close is not a card PUT; the close keeps the send path,
    # where a "mérve" 30 minutes ahead passes (the card rule would block it).
    h = root['hook']
    bad = " -d '" + json.dumps({'status': 'done', 'comment': 'Kész, mérve 18:44'}) + "'"
    close = " && curl -s -X PUT http://localhost:3420/api/messages/77 -d '{\"status\":\"done\"}'"
    blocks = ['NO_PROXY=localhost curl -sX PUT ' + KB + bad + close,
              'r=`curl -sX PUT ' + KB + bad + '`' + close,
              'curl -s ' + KB + ' \\\n  -X PUT \\\n  -H "Content-Type: application/json"' + bad + close]
    read_then_close = ('curl -s ' + KB + ' -o card.json && curl -s -X PUT http://localhost:3420/api/messages/77 -d \''
                       + json.dumps({'status': 'done', 'result': 'kész (comment: mérve 18:44)'}) + "'")
    return (all(run(h, 'Bash', {'command': c}, now='18:14')[0] == 2 for c in blocks)
            and run(h, 'Bash', {'command': read_then_close}, now='18:14')[0] == 0)


@case
def known_limit_message_quoting_a_card_put_is_a_card(root):
    # Viktor 49836 L13 -> 49845 Known limit: a backtick, a ( or a ; inside a quoted text or a heredoc body counts as a
    # curl segment start, so a message that quotes a kanban PUT next to a plan time is judged as a card (overblock,
    # the safe side). Two shell-quoting parsers hid real PUTs (prop6, prop7), so the gate does not imitate quoting.
    h = root['hook']
    put = "curl -sX PUT " + KB + " -d '{\"comment\":\"VÁR: Dave\"}'"
    plan = 'Következő mérés 14:00-kor.'
    bad4 = json.dumps({'status': 'done', 'comment': 'Kernel 12:30: kész'})
    hdr = " -H 'Content-Type: application/json' --data-binary @- <<'JSON'\n"
    cmds = ["bash /Users/klodel/marveen/scripts/agent-msg.sh viktor dave - <<'EOF'\nJavaslat: `" + put + "`\n" + plan + '\nEOF',
            "bash /Users/klodel/marveen/scripts/agent-msg.sh viktor klodel - <<'EOF'\nLelet: `curl -sX PUT " + KB
            + " -d '" + bad4 + "'` átment a kapun.\nEOF",
            API + 'memories' + hdr + json.dumps({'agent_id': 'viktor', 'category': 'warm', 'content':
                'Tanulság: a kártya-PUT (curl -sX PUT ' + KB + ' -d {"comment":"..."}) is komment. ' + plan},
                ensure_ascii=False) + '\nJSON',
            API + 'messages' + hdr + json.dumps({'from': 'viktor', 'to': 'dave', 'content':
                'Lépések: kártya lezárása; curl -sX PUT ' + KB + ' -d {"comment":"VÁR"}. ' + plan},
                ensure_ascii=False) + '\nJSON']
    return all(run(h, 'Bash', {'command': c}, now='12:00')[0] == 2 for c in cmds)


@case
def block_put_in_a_live_substitution_next_to_a_message(root):
    # The other side of L13: in double quotes a $( ) and a backtick still run (bash executes them), so a card PUT
    # there, next to a message write, is a real card PUT.
    with open(os.path.join(root['dir'], 'put4.json'), 'w', encoding='utf-8') as fh:
        fh.write(json.dumps({'status': 'done', 'comment': 'Kernel 18:44: kész'}))
    h = root['hook']
    msg = ' && bash /Users/klodel/marveen/scripts/agent-msg.sh kernel klodel "Kártya kész."'
    cmds = ['r="$(curl -sX PUT ' + KB + ' --data-binary @put4.json)"' + msg,
            # (inline: a data file glued to the closing backtick, @put4.json`, is not read; an old data-file limit)
            'r="`curl -sX PUT ' + KB + ' -d {\\"comment\\":\\"Kész, mérve 18:44\\"}`"' + msg,
            # not right after an assignment (that is a segment through the env-prefix rule anyway)
            'echo "kártya: $(curl -sX PUT ' + KB + ' --data-binary @put4.json)"' + msg,
            'echo "kártya: `curl -sX PUT ' + KB + ' -d {\\"comment\\":\\"Kész, mérve 18:44\\"}`"' + msg,
            # a real card PUT AFTER a quoted message heredoc: the heredoc body ends at its terminator
            "bash /Users/klodel/marveen/scripts/agent-msg.sh kernel klodel - <<'EOF'\nKártya kész.\nEOF\ncurl -sX PUT " + KB
            + ' --data-binary @put4.json']
    return all(run(h, 'Bash', {'command': c}, now='18:14', cwd=root['dir'])[0] == 2 for c in cmds)


@case
def curl_segment_assign_token_is_linear(root):
    # Viktor 49836 L12: the value class of an env prefix held ( and the backtick, both segment starts, so a long
    # "(a=(a=..." or "`a=`a=..." token rescanned from every start: 100 KB took 15.6 s on e4c1d631 (hook limit 10 s).
    # Viktor 49845: under 2 s.
    import time
    tail = '\n-X PUT /api/kanban/x\nbash /Users/klodel/marveen/scripts/agent-msg.sh kernel klodel x\n'
    texts = [unit * (100 * 1024 // len(unit) + 1) for unit in ('(a=', '`a=')]
    # Viktor 49858 (the four 300 KB shapes of his value-class mutants) and the round-5 value units: a quote, an
    # escape, an arithmetic $((
    texts += ['$(a=' * 75000, 'a=a ' * 75000, 'a=' + '$' * 300000, 'a' + '=a' * 150000,
              'a=\\(' * 75000, "(a='" * 75000, '(a="' * 75000, '(a=$((' * 50000]
    # Each env-value char has one unit only: a bare $ before ' or a plain ' / " / backslash that could also open a
    # quote or an escape unit backtracks exponentially (mutants 22, 25, 26 of round 5: over 8 s on these short runs)
    texts += ["a=" + "$'a'" * 30, "a=" + "'a'" * 30, 'a=' + '\\a' * 400]
    # Viktor 49870 L14: a VAR=value chain with no curl after it was re-read from every ( ` ; inside its escapes and
    # quotes to the line end (120 KB 24.6 s on 201485cc); his four units, W07, W12, and quotes over lines, 300 KB each
    for unit in (' A=$H\\(A=$H', "$'\\(`A=$H\\(\\'", "$'|;$((A=$H\\'", ' a=\\(a=b', ' a=' + '\\(' * 8, ' a=x"y(a="',
                 ";a='(a=\n", ' a=\\\n', "(a='curl\n", ' a="(curl"', ' a="\\"(a="', ' a="\\\\(a="', "$'\\'(a=",
                 '"\\"' + '\\"', ' a="(\n', "'\"(x=a", "\"'(x='\"", ' a="\\\n', '; \\\n'):
        texts.append(unit * (300 * 1000 // len(unit)))
    # Viktor 49898 L16: one quoted value of backslash-newlines (with or without a blank after each) after (a=; a
    # repeated backslash-newline in the start + VAR= lookahead re-read the rest of the run (60 KB 18.7 s on c0454a1d)
    for quote in ('"', "'", "$'"):
        for unit in ('\\\n', '\\\n '):
            texts.append('(a=' + quote + unit * (300 * 1000 // len(unit)))
    for text in texts:
        t = time.monotonic()
        run(root['hook'], 'Bash', {'command': text + tail}, now='19:30')
        if time.monotonic() - t > 2.0:
            return False
    return True


@case
def block_put_after_a_command_substitution_assignment(root):
    # Viktor 49846: the L12 fix must keep a curl after VAR=$( ... ) (e4c1d631 blocked it, his U1 class let it
    # through next to a message): the env value takes a $( ) as one unit, spaces inside included.
    with open(os.path.join(root['dir'], 'put4.json'), 'w', encoding='utf-8') as fh:
        fh.write(json.dumps({'status': 'done', 'comment': 'Kernel 18:44: kész'}))
    msg = ' && bash /Users/klodel/marveen/scripts/agent-msg.sh kernel klodel "Kártya kész."'
    cmds = ['T=$(date) curl -sX PUT ' + KB + ' --data-binary @put4.json' + msg,
            'NOW=$(date +%H:%M) A=$HOME curl -sX PUT ' + KB + ' --data-binary @put4.json' + msg]
    # Viktor 49858 V1: the env values that e4c1d631 read and the bare-paren class lost (quoted, arithmetic, an escape,
    # an ANSI-C quote, a quoted backtick), and lower-case names (his V16 test gap)
    for pre in ('N=$((1+2)) ', "A='x(y)' ", 'A="(x)" ', 'A=a\\(b ', "A=$'x(y)' ", 'T=$((10#08)) ', "A='a`b' ",
                "A='a b' ", 't=$(date) ', 'h=1 ',
                # Viktor 49870: escapes with no cap (W06, five), a quote with a backslash in it (M23's real PUT), a
                # quote over a line, a backslash-newline (bash and zsh run the curl after each), a quote holding curl
                'A=a\\(b\\(c ', 'A=a\\(b\\)c\\;d ', 'A=\\a\\b\\c\\d\\e ', 'A="a\\"b" ', 'A="a\\\\" ',
                "A='a\nb' ", 'A=a\\\nb ', 'A=x"y z"w ', 'A="curl" ',
                # an escape inside "..." and $'...' and a newline inside them (bash and zsh: one word, the curl runs)
                'A="a\\\\ b" ', "A=$'a\\' b' ", 'A="a\nb" ', "A=$'a\nb' ", 'A="a\\\nb c" '):
        cmds.append(pre + 'curl -sX PUT ' + KB + ' --data-binary @put4.json' + msg)
    return all(run(root['hook'], 'Bash', {'command': c}, now='18:14', cwd=root['dir'])[0] == 2 for c in cmds)


@case
def block_put_more_method_and_comment_key_shapes(root):
    # Viktor 49831 L9: requests.put(, a lowercase fetch method 'put' (Fetch upper-cases it), http.client
    # request('PUT'; L10: a bare key at an indented line start (multi-line JS), jq .comment |=, b['comment'] =.
    h = root['hook']
    c = "'Kész, mérve 18:44'"
    cmds = ["python3 -c \"import requests; requests.put('" + KB + "', json={'status': 'done', 'comment': " + c + "})\"",
            "node -e \"fetch('" + KB + "', {method: 'put', body: JSON.stringify({status: 'done', comment: " + c + "})})\"",
            "python3 -c \"import http.client, json; k = http.client.HTTPConnection('localhost', 3420); k.request('PUT', "
            "'/api/kanban/abc', body=json.dumps({'comment': " + c + "}))\"",
            "node - <<'JS'\nconst c = " + c + ";\nfetch('" + KB + "', {\n  method: 'PUT',\n  body: JSON.stringify({\n"
            "    status: 'done',\n    comment: c,\n  }),\n});\nJS",
            "jq '.comment |= \"Kész, mérve 18:44\"' base.json | curl -sX PUT " + KB + ' --data-binary @-',
            "python3 -c \"import json, urllib.request as u; b = {'status': 'done'}; b['comment'] = " + c
            + "; u.urlopen(u.Request('" + KB + "', data=json.dumps(b).encode(), method='PUT'))\""]
    return all(run(h, 'Bash', {'command': x}, now='18:14')[0] == 2 for x in cmds)


@case
def allow_html_tag_in_a_stdin_herestring_body(root):
    # Viktor 49831 L11: with @- a "<b>" in the text was read as a `< b` stdin file (here holding a placeholder).
    with open(os.path.join(root['dir'], 'b'), 'w', encoding='utf-8') as fh:
        fh.write('trap 19:2x\n')
    body = json.dumps({'status': 'done', 'comment': 'a <b>fontos</b> rész kész'})
    return run(root['hook'], 'Bash', {'command': 'curl -sX PUT ' + KB + " --data-binary @- <<< '" + body + "'"},
               now='19:30', cwd=root['dir'])[0] == 0


@case
def allow_assignment_chain_with_no_curl_and_known_limit_subst(root):
    # A VAR=value chain is consumed even with no curl after it (Viktor 49870 L14); only a match with the curl group is a
    # segment, so a kanban URL and -XPUT in assignments next to a message are no card PUT. The old envvalue known limit
    # (a $( ) holding a pipe or nested parentheses before curl) is closed by CURL_SEG2_RX's ) start: that PUT blocks.
    with open(os.path.join(root['dir'], 'put4.json'), 'w', encoding='utf-8') as fh:
        fh.write(json.dumps({'status': 'done', 'comment': 'Kernel 18:44: kész'}))
    msg = ' && bash /Users/klodel/marveen/scripts/agent-msg.sh kernel klodel "Kártya kész."'
    h, d = root['hook'], root['dir']
    return (run(h, 'Bash', {'command': 'A=' + KB + ' B=-sXPUT --data-binary @put4.json' + msg}, now='18:14', cwd=d)[0] == 0
            and all(run(h, 'Bash', {'command': pre + 'curl -sX PUT ' + KB + ' --data-binary @put4.json' + msg},
                        now='18:14', cwd=d)[0] == 2
                    for pre in ('T=$(date | tr a b) ', 'T=$(printf %s $(date)) ', 'A=$(( (1+2) )) ')))


@case
def smuggle_shapes_next_to_a_write_are_cards(root):
    # Viktor 49901 (indep7, the 13 smuggle labels of the old Known limit) and 49912 K2 (command, env, timeout, time,
    # if before curl), plus sudo -u, timeout -s SIG, a case arm: next to a message / memory write the card PUT is a
    # card (BLOCK), as alone. CURL_SEG2_RX and the joined view find it; the main's search did not.
    url = 'http://localhost:3420/api/kanban/abc123'
    msg = ("curl -s -X POST http://localhost:3420/api/messages -H 'Content-Type: application/json' "
           """-d '{"from":"kernel","to":"klodel","content":"Kész."}'""")
    mem = ("curl -s -X POST http://localhost:3420/api/" + "memories -H 'Content-Type: application/json' "
           """-d '{"agent_id":"kernel","content":"jegyzet","category":"hot"}'""")
    amsg = 'bash /Users/klodel/marveen/scripts/agent-msg.sh kernel klodel "Kész."'
    bs, nl, fut = '\\', '\n', 'Kernel 12:30: kész'
    body = """-d '{"comment":\"""" + fut + """\"}'"""

    def put(pre='', name='curl'):
        return pre + name + ' -s -X PUT ' + url + " -H 'Content-Type: application/json' " + body
    shapes = {  # label: (the shape alone, the write next to it)
        'name-cont-env-dq': ('T' + bs + nl + '="b c" ' + put(), nl + msg),
        'cmd-name-cont': (put(name='cu' + bs + nl + 'rl'), nl + msg),
        'hdr-charset-semicolon': ("curl -s -X PUT -H 'Content-Type: application/json; charset=utf-8' " + body + ' ' + url,
                                  nl + msg),
        'data-multiline-url-last': ("curl -s -X PUT -H 'Content-Type: application/json' -d '{" + nl + '  "comment": "'
                                    + fut + '"' + nl + "}' " + url, nl + msg),
        'env-apiword-first': (put(pre='R="ld /api/messages" '), ''),
        'hdr-apiword-first': ("curl -s -X PUT -H 'X-Ref: /api/" + "memories' " + url + ' ' + body, nl + mem),
        'data-apiword-first': ("curl -s -X PUT -d '{\"comment\":\"" + fut + " /api/messages\"}' " + url, nl + msg),
        'kw-then': ('if true; then ' + put() + '; fi', nl + msg),
        'kw-do': ('for i in 1; do ' + put(pre='T="b c" ') + '; done', nl + msg),
        'kw-brace': ('{ ' + put() + '; }', nl + mem),
        'kw-bang': ('! ' + put(), nl + msg),
        'redir-prefix': ('2>/dev/null ' + put(), nl + msg),
        'quoted-cmd-name': (put(name='"curl"'), nl + msg),
        'bs-cmd-name': (put(name=bs + 'curl'), nl + msg),
        'pre-command': (put(pre='command '), nl + mem),
        'pre-env': (put(pre='env T=1 '), nl + mem),
        'pre-timeout': (put(pre='timeout 10 '), nl + mem),
        'pre-timeout-signal': (put(pre='timeout -s KILL 10 '), ' && ' + amsg),
        'pre-time': (put(pre='time '), nl + mem),
        'pre-if': ('if ' + put() + '; then :; fi', nl + mem),
        'pre-sudo': (put(pre='sudo -u klodel '), ' && ' + amsg),
        'case-arm': ('case "$1" in *) ' + put() + ' ;; esac', '; ' + amsg),
        'kw-while': ('while ' + put() + '; do break; done', nl + msg),
        'kw-until': ('until ' + put() + '; do :; done', nl + msg),
        'kw-else': ('if false; then :; else ' + put() + '; fi', nl + msg),
        'kw-elif': ('if false; then :; elif ' + put() + '; then :; fi', nl + msg),
        'pre-nohup': ('(nohup ' + put() + ')', nl + msg),
        'pre-exec': ('(exec ' + put() + ')', nl + msg),
        'pre-builtin': (put(pre='builtin '), nl + msg),
        'env-then-prefix': (put(pre='T=1 timeout 10 '), nl + msg),
        'hdr-ansi-quote-semicolon': ("curl -s -X PUT -H $'X-Note: it\\'s; ok' " + body + ' ' + url, nl + msg),
        'hdr-dq-semicolon': ('curl -s -X PUT -H "Content-Type: application/json; charset=utf-8" ' + body + ' ' + url,
                             nl + msg),
        'pre-nice': (put(pre='nice -n 5 '), nl + msg),
        'pre-time-p': (put(pre='time -p '), nl + msg),
        'pre-env-flag': (put(pre='env -i T=1 '), nl + msg),
        'pre-xargs': ('echo x | xargs -I{} ' + put(), ' && ' + amsg),
        'pre-redirect-fd': (put(pre='>&2 '), nl + msg),
        'pre-redirect-amp': (put(pre='&>/dev/null '), nl + msg),
        'pre-timeout-kill-after': (put(pre='timeout -k 5 10s '), nl + msg),
    }
    h, d = root['hook'], root['dir']
    bad = []
    for label, (shape, write) in shapes.items():
        alone = shape.replace('/api/messages', '/x').replace('/api/' + 'memories', '/x')
        if (run(h, 'Bash', {'command': shape + write}, now='12:00', cwd=d)[0] != 2
                or run(h, 'Bash', {'command': alone}, now='12:00', cwd=d)[0] != 2):
            bad.append(label)
    # a long run of the view's start chars and prefix words next to the write stays bounded (the ) start once read
    # the rest of a ) run per char: 120 KB 27 s)
    import time as _t
    for unit in (')', 'then ', 'xargs -I{} ', '\\' + nl, "'", '; curl -X PUT '):
        cmd = amsg + nl + 'echo -X PUT' + nl + unit * (300 * 1024 // len(unit)) + ' ' + url
        t0 = _t.monotonic()
        run(h, 'Bash', {'command': cmd}, now='12:00', cwd=d)
        if _t.monotonic() - t0 >= 3:
            bad.append('slow ' + repr(unit))
    # the same shapes with a past opening stamp pass: the view adds the card judgment, not a block
    past = put(pre='command ').replace('12:30', '11:30') + nl + msg
    if run(h, 'Bash', {'command': past}, now='12:00', cwd=d)[0] != 0:
        bad.append('past-passes')
    for b in bad:
        print('  smuggle:', b)
    return not bad


@case
def numbered_list_in_a_message_is_no_case_arm(root):
    # Viktor 50003 R1 (his probe_tsm labels, verbatim shapes): a numbered list mark in a message is no segment start
    # (main lets it through, the ) start had made it a card); a case arm stays one, also with a number, and a list
    # after a `case WORD in` blocks (the safe side). A then at a message line start, with no if before it, is no prefix
    # word (main lets it through); a real multi-line if/then and a do after while stay cards, and a message that also
    # says "if" reads the then (the safe side, Known limits).
    url = 'http://localhost:3420/api/kanban/abc123'
    amsg = 'bash /Users/klodel/marveen/scripts/agent-msg.sh viktor dave '
    put = 'curl -s -X PUT ' + url + """ -d '{"comment":"Viktor 14:30: kész"}'"""
    h, d = root['hook'], root['dir']
    cases = {
        'msg-numbered-list-paren': (amsg + "'Lépések: 1) curl -s -X PUT " + url
                                    + ' -d {"comment":"Viktor 14:30: kész"} 2) szólj.' + "'", 0),
        'msg-numbered-list-line-start': (amsg + "- <<'EOF'\nLépések:\n12) " + put + '\n13) szólj.\nEOF', 0),
        'case-arm-number': ('case "$1" in 1) ' + put + ' ;; esac; ' + amsg + '"Kész."', 2),
        'list-after-case-in': ('case "$1" in *) : ;; esac; ' + amsg + "'1) " + put.replace("'", '') + "'", 2),
        'known-quote-linestart-then': (amsg + "- <<'EOF'\nHa zöld:\n  then " + put + '\nEOF', 0),
        'msg-numbered-then-else-do': (amsg + "- <<'EOF'\n1) then " + put + '\n  else ' + put + '\ndo ' + put
                                      + '\nEOF', 0),
        'multiline-if-then': ('if true\nthen ' + put + '\nfi\n' + amsg + '"Kész."', 2),
        'multiline-elif': ('if false\nthen :\nelif ' + put + '\nthen :\nfi\n' + amsg + '"Kész."', 2),
        'while-newline-do': ('while true\ndo ' + put + '; break\ndone\n' + amsg + '"Kész."', 2),
        'msg-if-then-safe-side': (amsg + "- <<'EOF'\nif zöld\n  then " + put + '\nEOF', 2),
        'msg-semicolon-then': (amsg + "- <<'EOF'\nHa zöld; then " + put + '\nEOF', 0),
        'msg-if-inside-a-word': (amsg + "- <<'EOF'\nVerifikáció:\n  then " + put + '\nEOF', 0),
        'env-value-word-digit-paren': ('T=$(echo a | tr a b1) ' + put + '\n' + amsg + '"Kész."', 2),
        # Viktor 50062 R2: a ) that closes an open $( is no list mark (his own_tsm2 shapes, after a message write)
        'msg+subst-empty-1-glued': (amsg + '"Kész."; $(: 1)' + put, 2),
        'msg+subst-empty-1-glued-dq': (amsg + '"Kész."; "$(: 1)"' + put, 2),
        'msg+subst-true-12-glued': (amsg + '"Kész."; $(true 12)' + put, 2),
        'msg+env-subst-pipe-1': (amsg + '"Kész."; T=$(echo a | tr a 1) ' + put, 2),
        'msg+env-subst-semi-12': (amsg + '"Kész."; T=$(true; echo 12) ' + put, 2),
        'msg-list-after-balanced-parens': (amsg + "'Lépések (két dolog): 1) curl -s -X PUT " + url
                                           + ' -d {"comment":"Viktor 14:30: kész"} 2) szólj.' + "'", 0),
        'msg-word-case-no-case-in': (amsg + "'In this case: 1) curl -s -X PUT " + url
                                     + ' -d {"comment":"Viktor 14:30: kész"} 2) szólj.' + "'", 0),
        # round 3: bash also takes a newline before `in` and a WORD with spaces in a $( ); the narrow `case WORD in`
        # form let these numbered arms through (bash runs the curl in all three; 0619a859 blocks them)
        'case-subst-word': ('case $(echo 1) in 1) ' + put + ' ;; esac; ' + amsg + '"Kész."', 2),
        'case-newline-in': ('case 1\nin 1) ' + put + ' ;; esac; ' + amsg + '"Kész."', 2),
        'case-newline-in-nl-arm': ('case 1\nin\n1) ' + put + ' ;; esac; ' + amsg + '"Kész."', 2),
        'for-in-before-case-newline-in': ('for i in 1; do :; done; case 1\nin 1) ' + put + ' ;; esac; ' + amsg
                                          + '"Kész."', 2),
        'msg-case-then-in-safe-side': (amsg + "'In case: 1) curl -s -X PUT " + url
                                       + ' -d {"comment":"Viktor 14:30: kész"} 2) szólj in.' + "'", 2),
        # only a number of up to three digits at a word start is a list mark; the kept ) closes its parenthesis
        'msg-lettered-mark-stays-start': (amsg + "'Lépések: a) curl -s -X PUT " + url
                                          + ' -d {"comment":"Viktor 14:30: kész"} b) szólj.' + "'", 2),
        'msg-digit-glued-to-word-stays-start': (amsg + "'Lépések: x1) curl -s -X PUT " + url
                                                + ' -d {"comment":"Viktor 14:30: kész"} x2) szólj.' + "'", 2),
        'msg-list-after-closed-subst-text': (amsg + "'Jegyzet $(: 1) után: 2) curl -s -X PUT " + url
                                             + ' -d {"comment":"Viktor 14:30: kész"} 3) szólj.' + "'", 0),
        # Viktor 50100 R3 (his own_tsm3b shapes): a stray ) before the list mark (a smiley, a quoted ")", an "a)"
        # list) closes nothing; the depth stays at 0, so the ) of a later $( is no list mark (bash runs the curl)
        'msg-smiley+subst-empty-1-glued': (amsg + '"Kész :)"; $(: 1)' + put, 2),
        'msg-smiley+env-subst-pipe-1': (amsg + '"Kész :)"; T=$(echo a | tr a 1) ' + put, 2),
        'msg-smiley+env-subst-semi-12': (amsg + '"Kész :)"; T=$(true; echo 12) ' + put, 2),
        'msg-smiley+subst-true-12-glued': (amsg + '"Kész :)"; $(true 12)' + put, 2),
        'msg+sq-paren+subst-empty-1-glued': (amsg + '"Kész."; echo \')\'; $(: 1)' + put, 2),
        'msg-ab-list+subst-empty-1-glued': (amsg + '"a) kész b) mérve"; $(: 1)' + put, 2),
        'msg-two-smiley+env-subst-1': (amsg + '"ok :) :)"; T=$(echo 1) ' + put, 2),
        'msg-smiley-then-numbered-list': (amsg + "'Kész :) Lépések: 1) curl -s -X PUT " + url
                                          + ' -d {"comment":"Viktor 14:30: kész"} 2) szólj.' + "'", 0),
        # a mark kept at depth 2 leaves depth 1; the ) after it closes that, so the next marks are list marks again
        # (the depth is carried from mark to mark, each ( and ) read once: no rescan from the start, no stale depth)
        'msg-list-after-mark-at-depth-2': (amsg + "'Jegyzet ((lásd 1) x) után: 2) curl -s -X PUT " + url
                                           + ' -d {"comment":"Viktor 14:30: kész"} 3) szólj.' + "'", 0),
        'msg-second-list-after-mark-at-depth-2': (amsg + "'Jegyzet ((lásd 1) x) után: 2) szólj 3) curl -s -X PUT "
                                                  + url + ' -d {"comment":"Viktor 14:30: kész"}' + "'", 0),
        # Viktor 50142 R4 (his indep9 shapes): a quoted ) inside the $( ) of an env value closes nothing; the depth
        # counts only the shell's own parentheses, so the real ) after the number is no list mark (bash runs the curl)
        'envsubst-quoted-smiley': (amsg + "'kész :)'\nT=$(echo ':)' 1) " + put, 2),
        'envsubst-printf-paren': (amsg + "'1) ok'\nT=$(printf '%s' ')'; echo 1) " + put, 2),
        'envsubst-dq-paren': (amsg + "'kész'\nT=$(echo \")\" 1) " + put, 2),
        'envsubst-escaped-paren': (amsg + "'kész'\nT=$(echo \\) 1) " + put, 2),
        # a quoted ( does not open one either: the list after it stays a list
        'msg-quoted-open-paren-then-list': (amsg + "'Nézd: \"(\" Lépések: 1) curl -s -X PUT " + url
                                            + ' -d {"comment":"Viktor 14:30: kész"} 2) szólj.' + "'", 0),
        # round-5 mutation holes: a $( ) nested in a "..." $( ) keeps its own depth (the list after it stays a list),
        # and a kept, quoted mark inside a $( ) closes no level (the real ) after it is still kept: bash runs the curl)
        'msg-dq-nested-subst-then-list': (amsg + '"x $(echo $(echo a) )" ' + "'Lépések: 1) curl -s -X PUT " + url
                                          + ' -d {"comment":"Viktor 14:30: kész"} 2) szólj.' + "'", 0),
        'envsubst-quoted-kept-mark': (amsg + "'kész'\nT=$(echo ' 1)' 1) " + put, 2),
    }
    bad = [label for label, (cmd, want) in cases.items()
           if run(h, 'Bash', {'command': cmd}, now='12:00', cwd=d)[0] != want]
    for b in bad:
        print('  r1:', b)
    return not bad


@case
def quote_blind_view_counts_only_the_shells_own_parentheses(root):
    # Viktor 50142 R4, the round-5 view: inside '...' and "..." and after a backslash every char is a space; a $( in
    # "..." is a real substitution (its parentheses stay, quoting starts over in it, its ) returns to the "..."), and
    # a \" does not end a "..." (round-5 mutation holes M5, M9: checked on the view itself)
    import importlib.util
    spec = importlib.util.spec_from_file_location('tcg_view', root['hook'])
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    want = {
        '"a $(b) c)" d)': '   $(b)     d)',
        '"a \\" b)" c)': '          c)',
        '"$(echo $(echo a) )" x)': ' $(echo $(echo a) )  x)',
        "echo ' 1)' 1)": 'echo       1)',
        'a \\) b)': 'a    b)',
        '"$(echo ")") x)" y)': ' $(echo    )     y)',
    }
    bad = [k for k, v in want.items() if g._quote_blind(k) != v or len(g._quote_blind(k)) != len(k)]
    for b in bad:
        print('  view:', repr(b), '->', repr(g._quote_blind(b)))
    return not bad


@case
def unmodeled_sign_in_a_substitution_keeps_the_list_mark(root):
    # Viktor 50181 R5 (card 09f76463, his verify_r5 shapes): inside the $( ) of an env value, a $'...' with \', a
    # comment, a ${...} and a heredoc are not modeled by _quote_blind, and each showed or hid a ) so that the real ) after
    # the number read as a list mark at depth 0 (main and the round-5 head let the PUT through; zsh runs it in all four,
    # /bin/bash 3.2 in the first two). Fail-closed: from such a sign at a depth above 0 on, no list mark is blanked.
    # Each has an ALLOW pair: the same sign at the top level (depth 0) before a numbered list in a message.
    url = 'http://localhost:3420/api/kanban/abc123'
    amsg = 'bash /Users/klodel/marveen/scripts/agent-msg.sh viktor dave '
    put = 'curl -s -X PUT ' + url + """ -d '{"comment":"Viktor 14:30: kész"}'"""
    lst = "'Lépések: 1) curl -s -X PUT " + url + ' -d {"comment":"Viktor 14:30: kész"} 2) szólj.' + "'"
    h, d = root['hook'], root['dir']

    def sub(inner, msg="'kész :)'"):
        return amsg + msg + '\nT=$(' + inner + ' 1) ' + put
    cases = {
        'fo-ansic-escq-paren': (sub("echo $'\\')'"), 2),
        'fo-ansic-escq-paren-list': (sub("echo $'\\')'", "'1) ok'"), 2),
        'fo-comment-paren': (sub('echo a # )\n'), 2),
        'fo-brace-default': (sub('echo ${x:-)}'), 2),
        'fo-heredoc-paren': (sub('cat <<E\n)\nE\n'), 2),
        # the ALLOW pairs: the sign at depth 0, then a message with a numbered list (no PUT runs)
        'top-ansic-then-list': (amsg + "$'it\\'s 1) curl -X PUT " + url + " Viktor 14:30: kész'", 0),
        'top-comment-then-list': ('# jegyzet: a lista lent\n' + amsg + lst, 0),
        'top-brace-then-list': ('echo ${HOME:-x}; ' + amsg + lst, 0),
        'top-heredoc-then-list': (amsg + "- <<'EOF'\nLépések:\n12) " + put + '\n13) szólj.\nEOF', 0),
        # inside a substitution but modeled: a quoted #, a mid-word #, a quoted ${ change nothing (the depth is right)
        'sub-quoted-hash-list-after': (amsg + "\"$(echo '#')\" " + lst, 0),
        'sub-midword-hash-list-after': (amsg + '"$(echo a#b)" ' + lst, 0),
    }
    bad = [label for label, (cmd, want) in cases.items()
           if run(h, 'Bash', {'command': cmd}, now='12:00', cwd=d)[0] != want]
    for b in bad:
        print('  r5:', b)
    import importlib.util
    spec = importlib.util.spec_from_file_location('tcg_r5', root['hook'])
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    want = {
        "T=$(echo $'a' 1)": 9,      # $' inside the $(
        'T=$(a # c\n 1)': 6,        # a word-start #
        'T=$(a;# c\n 1)': 6,
        'T=$(a#b 1)': 10,           # a mid-word # is no comment: none (len)
        'T=$(echo ${x} 1)': 9,
        'T=$(cat <<E\n)\nE\n 1)': 8,
        "T=$(echo '#${<<' 1)": 19,  # quoted: text
        "echo $'a' ${x} # c <<E": 22,  # depth 0: none
        'T=$(a) # c': 10,           # the $( closed before the #
        '"$(echo ${x})"': 8,        # a $( inside "..." is a real substitution
        'a) # c': 6,                # a stray ) leaves the depth at 0, not below: the # is at depth 0
    }
    for k, v in want.items():
        got = g._unmodeled_from(k, g._quote_blind(k))
        if got != v:
            bad.append(k)
            print('  unmodeled:', repr(k), '->', got, 'want', v)
    return not bad


@case
def depth0_sign_that_hides_a_substitution_keeps_the_list_mark(root):
    # Viktor 50390 D1 (card 09f76463 round 2; his independent probe 6711eb542264, 19 cases, main lets all through): a
    # depth-0 comment, $'...' or heredoc body with an apostrophe opens a quote in _quote_blind that the shell does not
    # have, it blanks the ( of the $( after it, and the ) after the number reads as a list mark at depth 0 (zsh and
    # bash run the PUT). After a depth-0 sign, a $( <( >( that the drift blanked is itself unmodeled. Each BLOCK shape
    # has an ALLOW pair: the same sign, then only a numbered list written in a message.
    url = 'http://localhost:3420/api/kanban/abc123'
    amsg = 'bash /Users/klodel/marveen/scripts/agent-msg.sh viktor dave '
    put = 'curl -s -X PUT ' + url + """ -d '{"comment":"Viktor 14:30: kész"}'"""
    lst = "'Lépések: 1) curl -s -X PUT " + url + ' -d {"comment":"Viktor 14:30: kész"} 2) szólj.' + "'"
    env = 'T=$(echo a | tr a 1) '
    h, d = root['hook'], root['dir']
    cases = {
        'd0-comment-apostrophe': ("# it's\n" + env + put + '\n' + amsg + "'ok'", 2),
        'd0-msg-then-comment': (amsg + "'ok'\n# it's\n" + env + put, 2),
        'd0-ansi-c': ("echo $'it\\'s' >/dev/null; " + env + put + '; ' + amsg + "'ok'", 2),
        'd0-heredoc-apostrophe': ("cat >/dev/null <<E\nit's\nE\n" + env + put + '\n' + amsg + "'ok'", 2),
        'd0-backtick-comment': ("T=`echo a # don't`\nU=$(echo a | tr a 1) " + put + '\n' + amsg + "'ok'", 2),
        'd0-glued': ("# it's\n$(: 1)" + put + '\n' + amsg + "'ok'", 2),
        # the curl segment ends at a word-start #: an apostrophe in a trailing comment no longer swallows the next line
        'd0-trailing-comment': ("curl -s -X POST http://localhost:3420/api/messages -d '{\"content\":\"ok\"}' # don't\n"
                                + env + put, 2),
        # the ALLOW pairs: the same sign, then a list only written in a message
        'allow-comment-apostrophe': ("# it's\n" + amsg + lst, 0),
        'allow-msg-then-comment': (amsg + "'ok'\n# it's\n" + amsg + lst, 0),
        'allow-ansi-c': ("echo $'it\\'s' >/dev/null; " + amsg + lst, 0),
        'allow-heredoc-apostrophe': ("cat >/dev/null <<E\nit's\nE\n" + amsg + lst, 0),
        'allow-backtick-comment': ("T=`echo a # don't`\n" + amsg + lst, 0),
        'allow-trailing-comment-list': ("curl -s -X POST http://localhost:3420/api/messages -d '{\"content\":\"ok\"}'"
                                        " # don't 1) " + put, 0),
        # a mid-word # (a URL fragment) stays in the curl segment: the PUT is still read
        'fragment-put-blocks': ('curl -s -X PUT ' + url + "#x -d '{\"comment\":\"Viktor 14:30: kész\"}'", 2),
        # ... also before the -X PUT, where only the CURL_SEG2_RX view (env value with a pipe) reads the segment
        'midword-hash-before-put-blocks': (amsg + "'ok'\nT=$(date | tr a b) curl -s -d note#1 -X PUT " + url
                                           + " -d '{\"comment\":\"Viktor 14:30: kész\"}'", 2),
        # a bare ( hidden by the drift is no substitution: a message heredoc line keeps its list ALLOW
        'allow-heredoc-apostrophe-paren': (amsg + "- <<'E'\nPatrik's (lista:\n1) " + put + '\n2) szólj.\nE', 0),
    }
    bad = [label for label, (cmd, want) in cases.items()
           if run(h, 'Bash', {'command': cmd}, now='12:00', cwd=d)[0] != want]
    for b in bad:
        print('  d1:', b)
    import importlib.util
    spec = importlib.util.spec_from_file_location('tcg_d1', root['hook'])
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    want = {
        "# it's\nT=$(a 1)": 10,      # the ( of the $( the drift blanked
        "# it's\nT=<(a 1)": 10,      # a process substitution too
        "# it's\nT=(a 1)": 14,       # a bare ( is no substitution: none (len)
        "# its\nT=$(a 1)": 14,       # no drift: the $( is counted, nothing unmodeled (len)
        "T=$(a 1) # it's": 15,        # the sign after the $(: none (len)
        "echo '$(a 1)'": 13,          # quoted text without a sign before it: none (len)
    }
    for k, v in want.items():
        got = g._unmodeled_from(k, g._quote_blind(k))
        if got != v:
            bad.append(k)
            print('  unmodeled d1:', repr(k), '->', got, 'want', v)
    return not bad


@case
def brace_and_substitution_units_keep_the_curl_segment(root):
    # Round 3 (Viktor 50406 R1, Klodel 50408): round 2's word-start # rule ended the curl segment inside a ${...}
    # too ("${X:- #}" is no comment for the shell), so a PUT glued after "$(: 1)" next to a message passed (main and
    # cf7e431a block it; bash runs it). Round 4: these rows now pass because CURL_SEG2_RX is the main's again (no #
    # rule) and the # rule is the separate CURL_SEG3_RX view; the rows stay as they were.
    url = 'http://localhost:3420/api/kanban/abc123'
    amsg = 'bash /Users/klodel/marveen/scripts/agent-msg.sh viktor dave '
    data = """ -d '{"comment":"Viktor 14:30: kész"}'"""
    put = 'curl -s -X PUT ' + url + data
    env = 'T=$(echo a | tr a 1) '
    h, d = root['hook'], root['dir']
    cases = {
        'brace-space-glued': (amsg + "'ok'\n$(: 1)curl -s -X PUT ${X:- #} " + url + data, 2),
        'brace-tab-glued': (amsg + "'ok'\n$(: 1)curl -s -X PUT ${X:-\t#} " + url + data, 2),
        'brace-space-plain': (amsg + "'ok'\ncurl -s -X PUT ${X:- #} " + url + data, 2),
        'brace-tab-plain': (amsg + "'ok'\ncurl -s -X PUT ${X:-\t#} " + url + data, 2),
        'substitution-hash-kept': (amsg + "'ok'\n$(: 1)curl -s -X PUT $(: x #) " + url + data, 2),
        # Viktor 50406 I4 T15: a tab before a trailing comment ends the segment like a blank (the apostrophe in it
        # does not swallow the next line's PUT)
        'tab-trailing-comment': ("curl -s -X POST http://localhost:3420/api/messages -d '{\"content\":\"ok\"}'\t# don't\n"
                                 + env + put, 2),
        # the round 2 rows stay: a blank before the comment, and the ALLOW pair with the list in a message
        'space-trailing-comment': ("curl -s -X POST http://localhost:3420/api/messages -d '{\"content\":\"ok\"}' # don't\n"
                                   + env + put, 2),
        # a ${ unit stops at a newline: a ${...} over lines falls back to the lone $, so the next line's PUT is its
        # own segment (an overblock: bash and zsh keep that line inside the expansion and run no PUT; the main
        # blocks the line-start one too, its search stops at the newline; the glued one only CURL_SEG2_RX sees)
        'brace-over-lines-kept': (amsg + "'ok'\ncurl -s -d x ${X:- # it\n" + put + '\n}', 2),
        'brace-over-lines-glued-kept': (amsg + "'ok'\ncurl -s -d x ${X:- # it\n$(: 1)" + put + '\n}', 2),
        'allow-brace-list-in-message': ("curl -s -X POST http://localhost:3420/api/messages -d '{\"content\":\"${X:- #} "
                                        "1) curl -s -X PUT " + url + " -d {comment: Viktor 14:30}\"}'", 0),
    }
    bad = [label for label, (cmd, want) in cases.items()
           if run(h, 'Bash', {'command': cmd}, now='12:00', cwd=d)[0] != want]
    for b in bad:
        print('  r3:', b)
    return not bad


@case
def hash_rule_is_its_own_view_and_never_hides_a_main_put(root):
    # Round 4 (Viktor 50421 R2, R3; regressions to main): round 3's ${...} / $(...) unit read a quoted } or ) as its
    # closer, and the apostrophe left over opened a quote that swallowed the next PUT (R2, 11 shapes); a # after a
    # nested ${${b}} or a backtick still cut the segment before the kanban URL (R3). bash and zsh run every PUT here
    # (agents/kernel/work/tcr5-r4-1123/oracle.txt, stub curl); main blocks all of them. The # rule is now the
    # CURL_SEG3_RX view next to CURL_SEG2_RX (the main's, byte for byte), and either view's card PUT counts.
    a = "'"
    url = 'http://localhost:3420/api/kanban/abc123'
    data = """ -d '{"comment":"Viktor 14:30: kész"}'"""
    put = '{ curl -s -X PUT ' + url + data + '; }'
    msg = 'curl -s -X POST http://localhost:3420/api/messages -d ' + a + '{"content":"ok"}' + a + ' '
    sqb, dqb = '${V:-' + a + '}' + a + '}', '${V:-"}"}'
    sqp, dqp = '$(printf ' + a + '%s)' + a + ' x)', '$(echo "a)b")'
    h, d = root['hook'], root['dir']
    cases = {
        'msg-sq-brace-semi': (msg + sqb + ' ; ' + put, 2),
        'msg-sq-brace-and': (msg + sqb + ' && ' + put, 2),
        'msg-sq-brace-pipe': (msg + sqb + ' | ' + put, 2),
        'msg-sq-brace-nl': (msg + sqb + '\n' + put, 2),
        'msg-dq-brace-semi': (msg + dqb + ' ; ' + put, 2),
        'msg-sq-paren-semi': (msg + sqp + ' ; ' + put, 2),
        'msg-sq-paren-and': (msg + sqp + ' && ' + put, 2),
        'msg-dq-paren-nl': (msg + dqp + '\n' + put, 2),
        'case-arm-sq-brace': ('case a in a) ' + msg + sqb + ' ; ' + put + ' ;; esac', 2),
        'tsubst-sq-brace': ('T=$(' + msg + sqb + ' ; ' + put + ')', 2),
        'procsub-sq-paren': ('cat <(' + msg + sqp + ' ; ' + put + ')', 2),
        'glued-nested-brace-before-url': (msg + '\n$(: 1)curl -s ${a:- ${b} #c} -X PUT ' + url + data, 2),
        'glued-brace-subst-inside-before-url': (msg + '\n$(: 1)curl -s ${V:- $(printf y) #c} -X PUT ' + url + data, 2),
        'glued-bq-hash-before-url': (msg + '\n$(: 1)curl -s `echo a #b` -X PUT ' + url + data, 2),
        'env-nested-brace-before-url': (msg + '\nT=$(date | tr a b) curl -s ${a:- ${b} #c} -X PUT ' + url + data, 2),
        'env-bq-hash-before-url': (msg + '\nT=$(date | tr a b) curl -s `echo a #b` -X PUT ' + url + data, 2),
        # the ALLOW pairs: the same ${...} / $(...) in a message, no PUT after it
        'allow-msg-sq-brace': (msg + sqb, 0),
        'allow-msg-sq-paren-list': (msg + sqp + " -d 'Lépések: 1) curl -s -X PUT " + url
                                    + ' -d {"comment":"Viktor 14:30: kész"} 2) szólj.' + a, 0),
    }
    bad = [label for label, (cmd, want) in cases.items()
           if run(h, 'Bash', {'command': cmd}, now='12:00', cwd=d)[0] != want]
    for b in bad:
        print('  r4:', b)
    import importlib.util
    spec = importlib.util.spec_from_file_location('tcg_r4', root['hook'])
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    # the # rule lives only in the CURL_SEG3_RX view, as round 2 wrote it; CURL_SEG2_RX keeps a word-start # in the body
    if r'(?<!\s)#' not in g.CURL_SEG3_RX.pattern or '#' in g.CURL_SEG2_RX.pattern.split('curl\\b', 1)[1]:
        bad.append('views: the # rule is not exactly in CURL_SEG3_RX')
        print('  r4: views')
    return not bad


# Viktor 50406 K1 (old fail-opens, main and the round 2 head pass them too; Klodel 50408: Known limits, no code). The
# probe_tc22 inputs verbatim; a later fix turns its row red on purpose. The control row blocks the same stamp.
_K1_A = "'"
_K1_U = 'http://localhost:3420/api/kanban/x'
_K1_PJ = _K1_A + '{"comment":"mérve 18:15"}' + _K1_A
_K1_PUT = 'curl -s -X PUT ' + _K1_U + ' -H ' + _K1_A + 'Content-Type: application/json' + _K1_A + ' -d ' + _K1_PJ
_K1_MSGW = ('curl -s -X POST http://localhost:3420/api/messages -d ' + _K1_A
            + '{"from":"viktor","to":"klodel","content":"ok"}' + _K1_A)
KNOWN_K1 = {
    'bq-dq-apos-sub': _K1_MSGW + '\nX="`echo "it' + _K1_A + 's"`"; T=$(date; echo 1) ' + _K1_PUT,
    'bq-dq-apos-glued': _K1_MSGW + '\nX="`echo "it' + _K1_A + 's"`"; $(: 1)' + _K1_PUT,
    'bq-dq-sq-sub': _K1_MSGW + '\nX="`echo ' + _K1_A + '"' + _K1_A + '`"; T=$(date; echo 1) ' + _K1_PUT,
    'nl-in-subst-arg': _K1_MSGW + '\n$(: 1)curl -s -X PUT $(\n) ' + _K1_U + ' -d ' + _K1_PJ,
    # Viktor 50421 I4 (old, main and the round 3 head pass it too): agents/kernel/work/tcr5-r4-1123/i4.txt
    'msg-subst-put': 'curl -s -X POST http://localhost:3420/api/messages -d "$(' + _K1_PUT + ')"',
}


@case
def known_limit_k1_rows_pin_todays_allow(root):
    h, d = root['hook'], root['dir']
    bad = []
    if run(h, 'Bash', {'command': _K1_MSGW + '; ' + _K1_PUT}, now='12:00', cwd=d)[0] != 2:
        bad.append('control: the stamp is not blocked')
    for label, cmd in KNOWN_K1.items():
        if run(h, 'Bash', {'command': cmd}, now='12:00', cwd=d)[0] != 0:
            bad.append(label + ': blocks now (the documented limit changed)')
    with open(h, encoding='utf-8') as f:
        head = ''.join(f.readlines()[:80])
    bad += [label + ': not named in the first 80 lines of the module' for label in KNOWN_K1 if label not in head]
    for b in bad:
        print('  k1:', b)
    return not bad and len(KNOWN_K1) == 5


@case
def python_dict_triple_fstring_and_variable_on_rules_3_and_4(root):
    # Viktor 49912 K1: rule 3 (daily-log heading) and rule 4 (card opening stamp) read a triple-quoted or f-prefixed
    # Python value, rule 3 also a `content = '## ...'` variable; a past card stamp, another endpoint, the {{NOW}} token
    # pass (a typed daily-log heading of today blocks even when past: rule 6).
    h = root['hook']

    def py(url, src, pre=''):
        return ("python3 - <<'PY'\nimport json, urllib.request\n" + pre + 'body = ' + src + '\n'
                "urllib.request.urlopen(urllib.request.Request('http://localhost:3420" + url
                + "', data=json.dumps(body).encode(), method='POST'))\nPY")
    dl, card = '/api/daily-log', '/api/kanban/abc123/comments'
    block = [
        py(dl, "{'agent_id': 'kernel', 'content': '''## 13:30 -- Audit\nKész.'''}"),
        py(dl, '{"agent_id": "kernel", "content": """## 13:30 -- Audit"""}'),
        py(dl, "{'agent_id': 'kernel', 'content': f'## 13:30 -- {t}'}", pre="t = 'Audit'\n"),
        py(dl, "{'agent_id': 'kernel', 'content': content}", pre="content = '## 13:30 -- Audit\\nKész.'\n"),
        py(card, "{'author': 'kernel', 'content': '''Kernel 13:30: kész'''}"),
        py(card, "{'author': 'kernel', 'content': f'Kernel 13:30: {r}'}", pre="r = 'kész'\n"),
    ]
    allow = [
        py(dl, "{'agent_id': 'kernel', 'content': f'## {{NOW}} -- {t}'}", pre="t = 'Audit'\n"),
        py('/api/' + 'memories', "{'agent_id': 'kernel', 'content': content}", pre="content = '## 13:30 -- jegyzet'\n"),
        py(card, "{'author': 'kernel', 'content': f'Kernel 12:30: {r}'}", pre="r = 'kész'\n"),
    ]
    bad = [c for c in block if run(h, 'Bash', {'command': c}, now='13:00')[0] != 2]
    bad += [c for c in allow if run(h, 'Bash', {'command': c}, now='13:00')[0] != 0]
    for c in bad:
        print('  K1:', c[30:110].replace('\n', ' | '))
    return not bad


@case
def frequent_shapes_block(root):
    # Klodel 49904 (2), Viktor 49906: the shapes agents really write keep blocking (gate 12:00, times 12:30 / 12:3x),
    # among them rule 4 and rule 3 in a Python dict (json.dump in a heredoc and in python3 -c), new in this PR.
    url = 'http://localhost:3420/api/kanban/abc'
    api = 'http://localhost:3420/api/'
    iso = TODAY.isoformat() + 'T12:30'
    cj = " -H 'Content-Type: application/json' "

    def py_heredoc(path, body):
        return ("python3 - <<'PY'\nimport json\njson.dump(" + repr(body) + ", open('p.json', 'w'))\nPY\n"
                'curl -s -X POST ' + api + path + cj + '--data-binary @p.json')

    def py_c(path, body):
        return ('python3 -c "import json,sys; json.dump(' + repr(body) + ', sys.stdout)" | curl -s -X POST '
                + api + path + cj + '--data-binary @-')
    card = {'author': 'kernel', 'content': 'Kernel 12:30: kész'}
    log = {'agent_id': 'kernel', 'content': '## 12:30 -- teszt'}
    cmds = ["bash /Users/klodel/marveen/scripts/agent-msg.sh kernel klodel - <<'TXT'\nmérve 12:3x, kész\nTXT",
            'curl -s -X POST ' + url + '/comments' + cj + "--data-binary @- <<'JSON'\n"
            + '{"author":"kernel","content":"Kernel 12:30: kész"}\nJSON',
            'curl -s -X POST ' + url + '/move' + cj + """-d '{"status":"waiting","comment":"Kernel 12:30: VÁR"}'""",
            'curl -s -X PUT ' + url + cj + """-d '{"comment":"Kernel 12:30: kész"}'""",
            'curl -s -X POST ' + api + 'daily-log' + cj + "--data-binary @- <<'JSON'\n"
            + '{"agent_id":"kernel","content":"## 12:30 -- x"}\nJSON',
            'curl -s -X PUT ' + api + 'memories/12' + cj + "--data-binary @- <<'JSON'\n" + '{"content":"mérve 12:3x"}\nJSON',
            py_heredoc('kanban/abc/comments', card), py_c('kanban/abc/comments', card),
            py_heredoc('daily-log', log), py_c('daily-log', log),
            py_heredoc('kanban/abc/move', {'status': 'waiting', 'comment': 'VÁR, mérve 12:30'}),
            "python3 -c \"import json, urllib.request as u; u.urlopen(u.Request('" + url
            + "', data=json.dumps({'comment': 'kész 12:3x'}).encode(), method='PUT'))\"",
            'curl -s -X POST ' + url + '/move' + cj + """-d '{"status":"waiting","comment":"Kernel """ + iso + """+01:00: VÁR"}'""",
            'curl -s -X POST ' + url + '/comments' + cj + """-d '{"author":"kernel","content":"mérve """ + iso + """:00+01:00"}'"""]
    h, d = root['hook'], root['dir']
    past = [py_c('kanban/abc/comments', {'author': 'kernel', 'content': 'Kernel 11:30: kész'}),
            py_heredoc('daily-log', {'agent_id': 'kernel', 'content': '## {{NOW}} -- teszt'})]
    return (all(run(h, 'Bash', {'command': c}, now='12:00', cwd=d)[0] == 2 for c in cmds)
            and all(run(h, 'Bash', {'command': c}, now='12:00', cwd=d)[0] == 0 for c in past))


@case
def block_real_put_after_a_quote_the_shell_does_not_open(root):
    # Viktor 49884 L15: a quote the shell does not read as one (inside another quote, in a heredoc text), right after
    # a segment start and VAR=, was opened by the regex and closed inside the real PUT's quoted env value, so the
    # consumed chain swallowed the real ; or line start. A unit never holds a segment start followed by VAR=.
    with open(os.path.join(root['dir'], 'put4.json'), 'w', encoding='utf-8') as fh:
        fh.write(json.dumps({'status': 'done', 'comment': 'Kernel 18:44: kész'}))
    put = 'curl -sX PUT ' + KB + ' --data-binary @put4.json'
    am = 'bash /Users/klodel/marveen/scripts/agent-msg.sh kernel klodel '
    msg = ' && ' + am + '"Kártya kész."'
    cmds = ["echo \"(x='a\" ; T='b c' " + put + msg, "echo '(x=\"a' ; T=\"b c\" " + put + msg,
            am + "\"Kész (x=Kernel's fix)\" ; T='a b' " + put, am + "\"Kész (x=Kernel's fix)\" && T='a b' " + put,
            am + "- <<'EOF'\nok (x=it's done\nEOF\nT='a b' " + put, am + "- <<'EOF'\nok (x=\"quote\nEOF\nT=\"a b\" " + put,
            "echo \"(x='a\" ; A=1 T='b c' " + put + msg, "echo \"`x='a\" ; T='b c' " + put + msg,
            # Viktor 49887: a backslash-newline between the start and VAR=, a comment ending in a backslash
            "echo '(x=\"a' ; \\\nT=\"b c\" " + put + msg, "echo '(x=\"a' && \\\nT=\"b c\" " + put + msg,
            "# jegyzet (x=\"a \\\nT=\"b c\" " + put + msg, "# jegyzet (x=$'a \\\nT=$'b c' " + put + msg,
            "# jegyzet (x=\"a \\\n  T=\"b c\" " + put + msg, "# jegyzet (x=$'a \\\n\tT=$'b c' " + put + msg,
            # Viktor 49901 L17: a comment ending in a backslash, then a real PUT with no env prefix
            '# lepes 1;b=c\\\n' + put + msg, '# jegyzet (x=a\\\n' + put + '\n' + am + '"Kész."',
            '# jegyzet (x="a\\\n' + put + '\n' + am + '"Kész."', '# lepes 1;b=c\\\n' + put + '\n' + am + '"Kész."',
            '# lepes 1 && b=c\\\n' + put + msg, '# note (x=a\\\n/usr/bin/' + put + msg,
            # the swallowed comment's /api/messages would be the segment's first URL: VAR= and blanks stop it too
            '# lepes 1;b=/api/messages\\\nT=1 ' + put + msg, '# lepes 1;b=/api/messages\\\n  ' + put + msg,
            am + "- <<'EOF'\nok (x=\"idézet\nEOF\ntrue && \\\nT=\"a b\" " + put]
    return all(run(root['hook'], 'Bash', {'command': c}, now='18:14', cwd=root['dir'])[0] == 2 for c in cmds)


@case
def curl_segment_scan_is_linear(root):
    # Viktor 49831: the new curl-segment regex on 300 KB commands (his first draft took over 60 s on 300 000 '&').
    import time
    h = root['hook']
    k = 'http://localhost:3420/api/kanban/abc'
    cmds = ['&' * 300000 + ' curl -X PUT ' + k + ' /api/messages',
            ('curl -s http://localhost:3420/api/messages/77 ; ') * 6000 + 'curl -sX PUT ' + k + " -d '{\"comment\":\"ok\"}'",
            'curl -sX PUT ' + k + ' ' + '\\\n -H x ' * 40000 + " -d '{\"comment\":\"ok\"}' && curl /api/messages",
            '&/' * 150000 + ' curl -X PUT ' + k + ' /api/' + 'memories',
            ';A=' * 100000 + 'curl -X PUT ' + k + ' /api/' + 'memories',
            '(' * 300000 + 'curl -X PUT ' + k + ' /api/' + 'memories']
    for c in cmds:
        t = time.monotonic()
        run(h, 'Bash', {'command': c}, now='19:30')
        if time.monotonic() - t > 3.0:
            return False
    return True


@case
def card_comment_keeps_the_future_rule(root):
    # The message scope is narrower; a card comment is judged by both rules as before.
    return run(root['hook'], 'Bash', {'command': KANBAN + " -d @- <<'J'\nmérve 18:30\nJ"}, now='18:14')[0] == 2



# ---- the send path (retro R1, card 028205dd): rule 5, a measured time a few minutes ahead ----

def _close(result):
    return {'command': API + "messages/77 -X PUT --data-binary @- <<'JSON'\n" + json.dumps({'status': 'done', 'result': result})
            + "\nJSON"}


@case
def block_send_path_near_future_measured_time(root):
    # Measured (read only, 7 days before 11-13): Viktor 40555 "merve 15:37 date" stored at 15:35, Mira's results
    # "a kártyán rögzítve (12:35)" closed at 12:22, Radar's "## 21:25" log written at 21:17.
    h = root['hook']
    body = os.path.join(root['dir'], 'send-body.txt')
    with open(body, 'w', encoding='utf-8') as fh:
        fh.write('Pulzus: élesben, mérve 15:36.\n')
    code, _, err = run(h, 'Bash', {'command': MSG + 'Viktor -> Klodel (merve 15:37 date): HASH-OK\nTXT'}, now='15:35')
    return (code == 2 and '15:37' in err and '{{NOW}}' in err
            and run(h, 'Bash', {'command': 'bash tools/msg-close.sh "kész, mérve 15:39" 123'}, now='15:35')[0] == 2
            and run(h, 'Bash', _close('Mérve (15:39): a letöltés kész'), now='15:35')[0] == 2
            and run(h, 'Bash', {'command': LOG + '{"content":"## {{NOW}} -- x\\nlefutott 15:40"}\nJSON'}, now='15:35')[0] == 2
            and run(h, 'Bash', {'command': 'bash scripts/agent-msg.sh pulzus klodel - < ' + body}, now='15:35')[0] == 2
            and run(h, 'Bash', {'command': MSG + 'mérve 15:50\nTXT'}, now='15:35')[0] == 2)  # the window's edge



@case
def send_path_file_payload_is_json_decoded(root):
    # A json.dumps body file: the marker's e-acute is a \u escape and the line break a literal \n (mutation M13).
    body = os.path.join(root['dir'], 'close-body.json')
    with open(body, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps({'status': 'done', 'result': 'kész\nMérve 15:39: a letöltés kész'}))
    with open(body, encoding='utf-8') as fh:
        raw = fh.read()
    return ('\\u00e9' in raw and '\\n' in raw
            and run(root['hook'], 'Bash', {'command': API + 'messages/77 -X PUT --data-binary @' + body}, now='15:35')[0] == 2)

@case
def allow_send_path_now_plans_estimates_and_far_times(root):
    h = root['hook']
    return (all(run(h, 'Bash', {'command': MSG + t + '\nTXT'}, now='15:35')[0] == 0 for t in (
                'mérve 15:35 date',                      # the current minute
                'mérve {{NOW}} date',                    # the server fills it in
                'mérve 15:51',                           # past the window: a plan, not a guessed stamp
                'mérve 15:20, kész kb. 15:40',           # an estimate
                'mérve 15:20, a végén ~15:40',
                'lefutott; újra 15:40-kor',              # a suffix
                'a keret elfogyott (mért), nullázás 15:40',  # a plan line
                'lefutott 15:40:00Z',                    # a UTC stamp
                'mért, de nem 15:40, hanem most',        # a correction
                'mérve 15:30, kész 15:45-ig'))           # a deadline
            and run(h, 'Bash', {'command': API + "memories --data-binary @- <<'JSON'\n{\"content\":\"mérve 15:37\"}\nJSON"},
                    now='15:35')[0] == 0)                # a memory is not the send path


# ---- daily-log heading (Dave 39739): rule 3 ----

LOG = API + "daily-log -H 'Content-Type: application/json' --data-binary @- <<'JSON'\n"
YESTERDAY = TODAY - datetime.timedelta(days=1)


@case
def block_daily_log_future_heading(root):
    # Dave 1375, the case that went in: "## 16:58" written at 16:48.
    h = root['hook']
    code, out, err = run(h, 'Bash', {'command': LOG + '{"agent_id":"dave","content":"## 16:58 -- PR #1293\\nkész"}\nJSON'},
                         now='16:48')
    body = os.path.join(root['dir'], 'log.json')
    with open(body, 'w', encoding='utf-8') as fh:
        fh.write('{"agent_id": "radar", "content": "# 9:05 -- kör"}')
    return (code == 2 and '16:58' in err and 'heading' in err and out == ''
            and run(h, 'Bash', {'command': API + 'daily-log --data-binary @' + body}, now='08:59')[0] == 2
            and run(h, 'Bash', {'command': LOG + '{"content": "###16:49"}\nJSON'}, now='16:48')[0] == 2)


@case
def allow_daily_log_heading_now_token_other_day_or_body_deadline(root):
    h = root['hook']
    return all(run(h, 'Bash', {'command': LOG + c + '\nJSON'}, now='16:48')[0] == 0 for c in (
        '{"content":"## {{NOW}} -- kész"}',
        '{"content":"## {{NOW}} -- PR kész\\nPulzus 23:00-ig élesíti"}',
        '{"content":"## 23:40 (' + f'{YESTERDAY:%m-%d}' + ') -- éjjeli kör"}',
        '{"content":"Napi összegzés\\n## 23:59 terv"}'))



@case
def block_daily_log_typed_heading_of_today(root):
    # Retro R1: the heading time is written only by the {{NOW}} substitution; a typed time of today is blocked even
    # when it is not ahead (rule 6), and the message names the token.
    h = root['hook']
    code, _, err = run(h, 'Bash', {'command': LOG + '{"content":"## 16:40 -- PR kész"}\nJSON'}, now='16:48')
    return (code == 2 and '16:40' in err and '## {{NOW}}' in err
            and run(h, 'Bash', {'command': LOG + '{"content":"## 16:48 -- kész"}\nJSON'}, now='16:48')[0] == 2
            and run(h, 'Bash', {'command': LOG + '{"agent_id":"x", "content": "### 9:05 -- reggel"}\nJSON'},
                    now='16:48')[0] == 2)

@case
def heading_rule_is_daily_log_only(root):
    # A message or memory that starts with a heading, or a message that names the endpoint and quotes a heading,
    # is not a log write (Dave 39739: his own local rule stopped his proposal message this way).
    h = root['hook']
    return (run(h, 'Bash', {'command': API + "messages --data-binary @- <<'JSON'\n{\"content\":\"## 23:59 terv\"}\nJSON"},
                now='19:25')[0] == 0
            and run(h, 'Bash', {'command': API + "memories --data-binary @- <<'JSON'\n{\"content\":\"## 23:59\"}\nJSON"},
                    now='19:25')[0] == 0
            and run(h, 'Bash', {'command': MSG + 'javaslat: a /api/daily-log fejléce (## 23:59) jövőbeli\nTXT'},
                    now='19:25')[0] == 0
            and run(h, 'Bash', {'command': KANBAN + " -d @- <<'J'\n{\"content\":\"## 23:59 terv\"}\nJ"},
                    now='19:25')[0] == 0)


# ---- card-comment opening stamp (Dave 39858): rule 4 ----

CARD = KANBAN + " --data-binary @- <<'JSON'\n"


def card_json(content):
    return CARD + json.dumps({'author': 'dave', 'content': content}, ensure_ascii=False) + '\nJSON'


@case
def block_card_comment_future_stamp_without_marker(root):
    # Dave 20196, the case that went in at 08:44: no marker word on the line, so rule 2 never judged it.
    h = root['hook']
    code, out, err = run(h, 'Bash', {'command': card_json(f'{TODAY:%Y-%m-%d} 08:46 - #1289 új fej 1302c5e52 (docs-only)')},
                         now='08:44')
    body = os.path.join(root['dir'], 'c.json')
    with open(body, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps({'author': 'kernel', 'content': '12:25 (5) DataForSEO: források'}))
    return (code == 2 and '08:46' in err and 'comment stamp' in err and out == ''
            and run(h, 'Bash', {'command': card_json('Kernel 08:48 lap kész')}, now='08:47')[0] == 2
            and run(h, 'Bash', {'command': card_json(f'Magnes {TODAY:%m-%d}, 10:15 - kész')}, now='10:12')[0] == 2
            and run(h, 'Bash', {'command': card_json('Klodel (13:12, date): összesítő')}, now='13:06')[0] == 2
            and run(h, 'Bash', {'command': card_json('08:46: kész a lap')}, now='08:44')[0] == 2
            and run(h, 'Bash', {'command': KANBAN + ' --data-binary @' + body}, now='12:07')[0] == 2)


@case
def allow_card_comment_stamp_now_past_other_day_plan_or_body(root):
    h = root['hook']
    return all(run(h, 'Bash', {'command': card_json(c)}, now='08:44')[0] == 0 for c in (
        f'{TODAY:%Y-%m-%d} 08:44 - kész',
        'Kernel 08:30 (date): kész',
        f'{YESTERDAY:%m-%d} 23:40 - éjjeli kör',
        'Indulás 09:00 után (Klodel: éjjel nem)',
        'VÁR: Pulzus -- a 23:50-es export nem érkezett meg',
        '## 23:59 terv',
        '22:00-ig kész a PR',
        '22:00 óráig kész a PR',
        'PR #1290 kész, 23:00 deploy',
        'Határidő 17:30: kész / mi akadt el',
        'Kész a lap.\n23:59-kor jön a következő kör',
        'PR #1289 zöld, a köteg 23:00 után megy'))


@case
def comment_stamp_rule_is_card_only(root):
    # A message, a memory or a daily-log body that opens with a later time is not a card comment (rule 1 only there).
    h = root['hook']
    return all(run(h, 'Bash', {'command': API + ep + " --data-binary @- <<'JSON'\n{\"content\":\"Kernel 23:59 terv nélkül\"}\nJSON"},
                   now='08:44')[0] == 0 for ep in ('messages', 'memories', 'daily-log'))


@case
def unrelated_msg_words_are_out_of_scope(root):
    h = root['hook']
    return (run(h, 'Bash', {'command': 'echo "sms.sh 10:xx"; cat agent-msg-notes.txt'})[0] == 0
            and run(h, 'Bash', {'command': 'grep 10:xx /tmp/api-messages.log'})[0] == 0)

# ---- BLOCK ----

@case
def block_future_range_dated_today(root):
    code, out, err = write(root, f'Kernel, {TODAY:%Y-%m-%d} (mérve 18:15-18:30, `date`)')
    return code == 2 and '18:30' in err and 'line 1' in err and out == ''


@case
def block_placeholder_in_shared_md(root):
    code, _, err = write(root, 'fejléc\naz Ads-hívás 19:3x és 18:00 között')
    return code == 2 and '19:3x' in err and 'line 2' in err


@case
def block_placeholder_upper_x(root):
    return write(root, 'kész 09:3X-kor')[0] == 2 and write(root, 'kész 10:XX-re')[0] == 2


@case
def block_edit_future_measured(root):
    ti = {'file_path': os.path.join(root['dir'], 'shared', 'x', 'r.md'), 'old_string': 'TODO', 'new_string': 'mérve 23:58'}
    code, _, err = run(root['hook'], 'Edit', ti)
    return code == 2 and '23:58' in err


@case
def block_multiedit_second_edit(root):
    ti = {'file_path': os.path.join(root['dir'], 'shared', 'x', 'r.md'),
          'edits': [{'old_string': 'a', 'new_string': 'rendben'}, {'old_string': 'b', 'new_string': 'measured 20:00'}]}
    return run(root['hook'], 'MultiEdit', ti)[0] == 2


@case
def block_kanban_heredoc_placeholder(root):
    cmd = KANBAN + " --data-binary @- <<'JSON'\n{\"author\":\"kernel\",\"content\":\"Kernel 10:xx: kész\"}\nJSON"
    code, _, err = run(root['hook'], 'Bash', {'command': cmd})
    return code == 2 and '10:xx' in err and 'command line 2' in err


@case
def block_kanban_data_file(root):
    path = os.path.join(root['dir'], 'payload.json')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('{"author":"kernel","content":"riport, mérve 23:50"}\n')
    code, _, err = run(root['hook'], 'Bash', {'command': KANBAN + f' --data-binary @{path}'})
    return code == 2 and '@file line 1' in err and '23:50' in err


@case
def block_kanban_relative_data_file_d_flag(root):
    with open(os.path.join(root['dir'], 'p.json'), 'w', encoding='utf-8') as fh:
        fh.write('{"content":"lezárva 19:00"}')
    return run(root['hook'], 'Bash', {'command': KANBAN + ' -d @p.json'}, cwd=root['dir'])[0] == 2


@case
def block_range_not_misread_as_date(root):
    # "10:05-11:30" contains "05-11"; it must not count as the date May 11 and hide the line.
    return write(root, 'mérve 10:05-11:30', now='09:00')[0] == 2


@case
def block_marker_case_insensitive(root):
    return write(root, 'MÉRVE 20:00')[0] == 2 and write(root, 'date szerint 20:00')[0] == 2


@case
def block_same_line_with_today_mmdd(root):
    return write(root, f'{TODAY:%m-%d} mérve 23:00')[0] == 2


@case
def block_real_hook_resolves_repo_shared(root):
    # The real file: <repo-root>/shared/ is two levels above scripts/hooks/. The path need not exist.
    repo = os.path.realpath(os.path.join(HERE, '..', '..'))
    ti = {'file_path': os.path.join(repo, 'shared', 'no-such-dir-tcg', 'r.md'), 'content': 'mérve 23:59'}
    return run(REAL_HOOK, 'Write', ti)[0] == 2


# ---- PASS ----

@case
def pass_future_deadline_without_marker(root):
    return all(write(root, t)[0] == 0 for t in ('határidő 21:00-ig kész', 'holnap 10:00', 'kész lesz 23:30-ra'))


@case
def pass_deadline_on_a_marker_line(root):
    # A measured line may name a deadline; the deadline is not a measured time.
    texts = ('mérve 18:10, kész 22:00-ig', 'mérve 18:10; határidő 22:00', 'measured 18:10, due by 22:00',
             'mért 18:10, 21:30-ra kész', 'lefutott 18:12, 22:00 óráig')
    return all(write(root, t)[0] == 0 for t in texts)


@case
def block_measured_future_next_to_deadline(root):
    # The deadline exemption is per time token: the guessed measured time on the same line still blocks.
    code, _, err = write(root, 'mérve 20:15, kész 22:00-ig')
    return code == 2 and '20:15' in err and '22:00' not in err


@case
def long_line_is_bounded(root):
    # Viktor 38419 LOW: 20000 times on one line took 13.6 s (quadratic prefix scan). Now bounded.
    import time
    t0 = time.monotonic()
    code = write(root, 'mérve ' + '10:00 ' * 20000, now='11:00')[0]
    return code == 0 and time.monotonic() - t0 < 3


@case
def pass_past_and_current_minute(root):
    return write(root, 'mérve 18:08-18:14')[0] == 0 and write(root, 'mérve 18:14')[0] == 0


@case
def block_one_minute_ahead(root):
    # 2026-11-12: "08:20 date" written at 08:19:49 passed the old 2-minute slack (Klodel 38942)
    return write(root, 'mérve 18:15')[0] == 2 and write(root, 'mérve 18:16')[0] == 2


@case
def block_bare_date_marker_kanban(root):
    # 2026-11-12 (Kernel 39004): "Kernel 08:48 date:" and "Kernel, 08:48 (date)" passed, the bare word was no marker
    def kanban(text):
        cmd = KANBAN + " --data-binary @- <<'JSON'\n{\"author\":\"kernel\",\"content\":\"" + text + "\"}\nJSON"
        return run(root['hook'], 'Bash', {'command': cmd}, now='08:47')[0]
    return kanban('Kernel 08:48 date: lap kész') == 2 and kanban('Kernel, 08:48 (date)') == 2


@case
def block_time_followed_by_colon(root):
    # 2026-11-12 (Kernel 39004): "mérve 08:48: lap kész" passed, the trailing colon hid the time
    return write(root, 'mérve 08:48: lap kész', now='08:47')[0] == 2


@case
def block_future_time_with_seconds(root):
    # HH:MM:SS was skipped as a whole; it is judged by its HH:MM now
    return write(root, 'mérve 08:48:10', now='08:47')[0] == 2 and write(root, 'mérve 08:47:59', now='08:47')[0] == 0


@case
def pass_date_word_without_measurement(root):
    # "date" inside a word, a JS call or a dotted / dashed name is no marker; a deadline next to date passes;
    # the current minute with the bare marker passes
    return all(write(root, t, now='08:47')[0] == 0 for t in (
        'update 22:00', 'new Date(2026) 22:00', 'date.now 22:00', 'date-fns 22:00',
        'date szerint kész 22:00-ig', 'Kernel 08:47 (date)', 'Kernel 08:47:54 date:'))


@case
def pass_not_clock_times(root):
    return all(write(root, t)[0] == 0 for t in ('cron 0 9 * * *', 'arány 3:2', 'hex 0x1f', 'mérve 2026-11-11T23:30:00'))


@case
def block_today_time_next_to_a_dated_yesterday_time(root):
    # Klodel 39769 (card fd941954, 2026-11-13 02:08): the yesterday date attached to the second time exempted the
    # whole line, the today-dated future time included.
    yday = TODAY - datetime.timedelta(days=1)
    code, _, err = run(root['hook'], 'Bash', {'command': KANBAN + " --data-binary @- <<'JSON'\n" + json.dumps(
        {'author': 'klodel', 'content': f'Dream Engine {TODAY:%m-%d} 02:19 mérése: a #192 benne van a fő fa '
                                        f'HEAD-jében (258ef299, Pulzus átvezetése {yday:%m-%d} 23:26). Kész.'},
        ensure_ascii=False) + '\nJSON'}, now='02:08')
    h = root['hook']
    return (code == 2 and '02:19' in err and '23:26' not in err
            and write(root, f'mérve {yday:%m-%d} 23:26 óta, és most {TODAY:%Y-%m-%d}, 02:19', now='02:08')[0] == 2
            and run(h, 'Bash', {'command': KANBAN + f" -d @- <<'J'\nmérve {TODAY:%m-%d} 02:19\nJ"}, now='02:08')[0] == 2)


@case
def pass_dated_yesterday_times_and_a_free_other_date(root):
    yday = TODAY - datetime.timedelta(days=1)
    return (write(root, f'Pulzus átvezetése {yday:%m-%d} 23:26, mérve {TODAY:%m-%d} 02:05', now='02:08')[0] == 0
            and write(root, f'{yday:%m-%d} este: mérve 23:40, lefutott 23:55', now='02:08')[0] == 0
            and write(root, f'mérve {yday:%Y-%m-%d}, 23:40 és {yday:%m-%d}T23:55', now='02:08')[0] == 0
            # Lists and ranges that continue an earlier date stay exempt (the 32-block first draft).
            and write(root, f'mérve: a futás {yday:%m-%d} 13:39-13:49 lefutott', now='02:08')[0] == 0
            and write(root, f'mérve: ablak {yday:%m-%d} 21:50 -> {TODAY:%m-%d} 07:30', now='02:08')[0] == 0
            and write(root, f'mérve 02:19, a {yday:%m-%d}T23:26-os futás után', now='02:08')[0] == 0)


@case
def pass_other_day_line(root):
    return (write(root, f'{TOMORROW:%Y-%m-%d} mérve 23:00')[0] == 0
            and write(root, f'{TOMORROW:%m-%d} lefutott 23:00')[0] == 0)


@case
def pass_out_of_scope_paths_and_tools(root):
    shared_txt = os.path.join(root['dir'], 'shared', 'x', 'notes.txt')
    outside_md = os.path.join(root['dir'], 'docs', 'r.md')
    h = root['hook']
    return (run(h, 'Write', {'file_path': shared_txt, 'content': 'mérve 23:59 19:3x'})[0] == 0
            and run(h, 'Write', {'file_path': outside_md, 'content': 'mérve 23:59 19:3x'})[0] == 0
            and run(h, 'Read', {'file_path': os.path.join(root['dir'], 'shared', 'x', 'r.md')})[0] == 0
            and run(h, 'Bash', {'command': 'echo "mérve 23:59 19:3x" > /dev/null'})[0] == 0
            and run(h, 'Bash', {'command': 'curl http://localhost:3420/api/kanban/abc -d "19:3x"'})[0] == 0)


@case
def pass_symlink_out_of_shared_is_judged_by_realpath(root):
    # A link under shared/ that points outside: the realpath is not in shared/, so it is out of scope.
    target = os.path.join(root['dir'], 'outside.md')
    open(target, 'w').close()
    link = os.path.join(root['dir'], 'shared', 'x', 'link.md')
    os.symlink(target, link)
    return run(root['hook'], 'Write', {'file_path': link, 'content': 'mérve 23:59'})[0] == 0


@case
def pass_write_keeps_existing_lines(root):
    # Rewriting a report whose old, undated lines hold a later time: only the NEW lines are judged.
    path = os.path.join(root['dir'], 'shared', 'x', 'log.md')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('tegnap: mérve 22:10\n')
    ok_keep = run(root['hook'], 'Write', {'file_path': path, 'content': 'tegnap: mérve 22:10\nma: mérve 18:00\n'})[0] == 0
    bad_new = run(root['hook'], 'Write', {'file_path': path, 'content': 'tegnap: mérve 22:10\nma: mérve 22:11\n'})[0] == 2
    return ok_keep and bad_new


@case
def pass_edit_context_lines_from_old_string(root):
    ti = {'file_path': os.path.join(root['dir'], 'shared', 'x', 'r.md'),
          'old_string': 'tegnap: mérve 22:10', 'new_string': 'tegnap: mérve 22:10\nma: mérve 18:00'}
    return run(root['hook'], 'Edit', ti)[0] == 0


@case
def pass_kanban_data_file_too_big_or_missing(root):
    big = os.path.join(root['dir'], 'big.json')
    with open(big, 'w', encoding='utf-8') as fh:
        fh.write('mérve 23:50\n' + 'x' * (64 * 1024 + 1))
    return (run(root['hook'], 'Bash', {'command': KANBAN + f' --data-binary @{big}'})[0] == 0
            and run(root['hook'], 'Bash', {'command': KANBAN + ' --data-binary @/no/such/file.json'})[0] == 0)


@case
def pass_fail_open_on_garbage(root):
    h = root['hook']
    return (run(h, 'Write', raw='this is not json')[0] == 0
            and run(h, 'Write', raw='[1, 2]')[0] == 0
            and run(h, 'Write', ['not-a-dict'])[0] == 0
            and run(h, 'Write', {'file_path': 7, 'content': None})[0] == 0
            and run(h, 'MultiEdit', {'file_path': os.path.join(root['dir'], 'shared', 'a.md'), 'edits': 'x'})[0] == 0
            and run(h, 'Write', raw='')[0] == 0)


@case
def bad_now_override_is_ignored_not_crashing(root):
    code, _, err = write(root, 'rendben', now='25:99')
    return code == 0 and err == ''


# ---- shell writes to shared/*.md (Radar 39251) ----

def _sh(root, cmd, cwd=None, now='18:14'):
    return run(root['hook'], 'Bash', {'command': cmd}, now=now, cwd=cwd)[0]


@case
def block_shell_append_heredoc_absolute(root):
    # Radar 39251 shape: cat >> <abs>/shared/hibanaplo.md <<'EOF', a future time on a `date` line.
    path = os.path.join(root['dir'], 'shared', 'hibanaplo.md')
    cmd = f"cat >> {path} <<'EOF'\n| {TODAY:%Y-%m-%d} 08:29 (date) | radar | hiba |\nEOF"
    code, _, err = run(root['hook'], 'Bash', {'command': cmd}, now='08:28')
    return code == 2 and '08:29' in err and 'command line 2' in err


@case
def block_shell_relative_target_cwd_and_cd(root):
    body = " <<'EOF'\nmérve 23:59\nEOF"
    return (_sh(root, 'cat >> shared/x/n.md' + body, cwd=root['dir']) == 2
            and _sh(root, f'cd {root["dir"]} && cat >>shared/x/n.md' + body, cwd='/') == 2
            and _sh(root, f"cd '{root['dir']}'; cat > 'shared/x/n.md'" + body, cwd='/') == 2)


@case
def block_shell_tee_and_placeholder(root):
    path = os.path.join(root['dir'], 'shared', 'x', 'n.md')
    return (_sh(root, f'printf "%s\\n" "lezárva 23:00" | tee -a {path} >/dev/null') == 2
            and _sh(root, f'echo "kész 10:xx" | tee /dev/null {path}') == 2
            and _sh(root, f'echo "kész 10:xx" >| {path}') == 2)


@case
def block_shell_target_after_many_other_redirects(root):
    # The cap counts .md targets only: 30 "> /dev/null" before the real one do not push it out.
    path = os.path.join(root['dir'], 'shared', 'x', 'n.md')
    return _sh(root, 'echo a > /dev/null; ' * 30 + f"cat >> {path} <<'EOF'\nmérve 23:59\nEOF") == 2


@case
def bounded_time_with_many_cds(root):
    # Viktor 39257 LOW: 20 relative .md words x 2000 distinct cds took 4 s; now the bases are capped.
    import time
    cds = ''.join(f'cd /shared/d{i}; ' for i in range(3000))
    words = ' '.join(f'> shared/x/w{i}.md' for i in range(20))
    t = time.time()
    code = _sh(root, cds + f'echo "mérve 23:59" {words}', cwd='/')
    fast = time.time() - t < 2.0
    # The same cd repeated 3000 times is one base, so the real target stays in reach.
    dup = _sh(root, f'cd {root["dir"]}; ' * 3000 + "cat >> shared/x/n.md <<'EOF'\nmérve 23:59\nEOF", cwd='/')
    return code == 0 and fast and dup == 2


@case
def pass_shell_write_out_of_scope_or_clean(root):
    shared_md = os.path.join(root['dir'], 'shared', 'x', 'n.md')
    with open(shared_md, 'w', encoding='utf-8') as fh:
        fh.write('régi sor, mérve 23:59\n')
    return (_sh(root, f"cat >> {root['dir']}/notes.md <<'EOF'\nmérve 23:59\nEOF") == 0       # not under shared/
            and _sh(root, f"cat >> {root['dir']}/shared/x/n.txt <<'EOF'\nmérve 23:59\nEOF") == 0  # not .md
            and _sh(root, f"cat >> {shared_md} <<'EOF'\nmérve 18:10, kész 22:00-ig\nEOF") == 0  # past + deadline
            and _sh(root, f"cat > {shared_md} <<'EOF'\nrégi sor, mérve 23:59\nEOF") == 0     # line already in file
            and _sh(root, 'cat >> shared/x/n.md <<EOF\nmérve 23:59\nEOF', cwd='/') == 0       # relative, no base
            and _sh(root, f'ls {shared_md} 2>&1 | grep mérve-23:59') == 0                     # a read, not a write
            and _sh(root, 'F=shared/x/n.md; echo "mérve 23:59" >> "$F"', cwd=root['dir']) == 0)  # known gap


@case
def block_text_names_only_the_token(root):
    secretish = 'SZINTETIKUS-titok-szoveg-ne-jelenjen-meg'
    code, _, err = write(root, f'{secretish} mérve 23:40')
    return code == 2 and secretish not in err and '23:40' in err


# ---- Telegram reply / edit_message (Klodel 48360, hibanapló 2026-11-20 02:20): placeholder rule only ----

TG_REPLY = 'mcp__plugin_telegram_telegram__reply'
TG_EDIT = 'mcp__plugin_telegram_telegram__edit_message'
# Verbatim lines of the two group messages that went out with a placeholder (TG 6577 and 6574, the ledger).
TG_6577 = ('Kint van (Pulzus mérte, 02:2x előtt 0 látogatóval): a Köszönjük és a Marabello oldalán a Google már '
           'látja a szállítást, és hogy személyre szabott termék lévén nincs visszaküldés; az ár nem változott.')
TG_6574 = 'Kint van (Pulzus mérte, 23:1x): a riasztó mostantól mind az 5 háttérfolyamatnál tudja, melyik hívott.'


def tg(root, text, tool=TG_REPLY, **kw):
    return run(root['hook'], tool, {'chat_id': '-1001', 'text': text}, **kw)


@case
def block_telegram_reply_placeholder_verbatim(root):
    c1, _, e1 = tg(root, TG_6577, now='02:21')
    c2, _, e2 = tg(root, TG_6574, now='23:20')
    c3, _, _ = tg(root, 'első sor\nkész, 10:xx', tool=TG_EDIT)
    c4, _, _ = tg(root, 'mérve 19:3X', tool=TG_EDIT)
    # Viktor 48385 LOW: MarkdownV2 italic and underline, and an underscore right after the placeholder
    md = [tg(root, t)[0] for t in ('kész _02:2x_', 'kész __02:2x__', 'mérve 02:2x_ előtt')]
    return (c1, c2, c3, c4) == (2, 2, 2, 2) and md == [2, 2, 2] and '"02:2x"' in e1 and '"23:1x"' in e2


@case
def block_telegram_text_does_not_offer_now_token(root):
    # nothing replaces {{NOW}} in a Telegram message: the block text says so instead of offering it
    code, _, err = tg(root, TG_6577, now='02:21')
    return code == 2 and 'Telegramban a {{NOW}} nem' in err and 'napi naplóban írd' not in err


@case
def allow_telegram_measured_time_plan_and_future(root):
    # a measured time, a plan ("23:00 után") and even a future measured time pass: rule 2 is off on the chat path
    texts = ['Kint van (Pulzus mérte, 02:20): rendben.', '23:00 után élesítünk.', 'mérve 23:59, kész',
             'Holnap 08:00-kor indul.', 'Arány 16:9, 2x gyorsabb', '',
             # Viktor 48385 INFO: the other rules stay off on this path: a measured time 1-15 minutes ahead (send
             # rule), a typed daily-log heading and a "content": line (heading and card rules), and a backslash-u
             # escape (no JSON unescaping of a chat text)
             'mérve 02:28, kész', '"content": "## 02:20 -- Téma"', '"content":"02:28 ok"',
             'kész 10:\\u0078\\u0078 (idézet egy logból)', 'kész 02:2xa']
    return all(tg(root, t, now='02:21')[0] == 0 for t in texts) and all(
        tg(root, t, tool=TG_EDIT, now='02:21')[0] == 0 for t in texts)


@case
def telegram_scope_is_the_text_of_reply_and_edit(root):
    h = root['hook']
    # a text that is not a str is out of scope, not an internal error (the error log stays empty)
    errlog = os.path.join(os.path.dirname(h), 'tg-scope-err.log')
    return (run(h, 'mcp__plugin_telegram_telegram__react', {'chat_id': '-1', 'emoji': 'x', 'text': '10:xx'})[0] == 0
            and run(h, TG_REPLY, {'chat_id': '-1', 'text': 'ok', 'files': ['/tmp/10:xx.png']})[0] == 0
            and run(h, TG_REPLY, {'chat_id': '-1', 'text': ['10:xx']}, errlog=errlog)[0] == 0
            and run(h, TG_EDIT, {'chat_id': '-1', 'text': {'a': '10:xx'}}, errlog=errlog)[0] == 0
            and not os.path.exists(errlog)
            and run(h, 'mcp__plugin_discord_discord__reply', {'chat_id': '-1', 'text': '10:xx'})[0] == 0)


def main():
    failed = []
    for fn in CASES:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = os.path.realpath(tmp)
            root = {'dir': tmp, 'hook': make_root(tmp)}
            try:
                ok = fn(root)
            except Exception as ex:  # a crashing case is a failing case
                ok = False
                print(f'  {fn.__name__}: {ex!r}')
        print(('PASS ' if ok else 'FAIL ') + fn.__name__)
        if not ok:
            failed.append(fn.__name__)
    print(f'{len(CASES) - len(failed)}/{len(CASES)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
