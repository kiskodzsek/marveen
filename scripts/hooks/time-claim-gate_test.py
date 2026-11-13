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
