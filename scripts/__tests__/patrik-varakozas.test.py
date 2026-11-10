#!/usr/bin/env python3
"""Tests for scripts/patrik-varakozas.py (the waiting clock + free-machine guard, Klodel 35735, Patrik TG 4453/4454)
and the reply_to / files columns ledger-outbound.py now records for it.

The two cases of 2026-11-10 as negative tests, on SYNTHETIC text with the real times: the baby-film change promised at
10:14 ("Amint kész, küldöm") came at 10:35 (an alert was due at 10:29), and the MacBook rendered nothing from 10:20 to 10:32 while
Patrik waited (an alert was due by 10:25). Hermetic: temp DB and store, synthetic chat ids, --dry (nothing is sent).
Run: python3 -I scripts/__tests__/patrik-varakozas.test.py
"""
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
SCRIPT = os.path.join(SCRIPTS, 'patrik-varakozas.py')
OUTBOUND = os.path.join(SCRIPTS, 'hooks', 'ledger-outbound.py')
_spec = importlib.util.spec_from_file_location('patrik_varakozas', SCRIPT)
W = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(W)

GROUP = '-1000000000002'  # synthetic
PRIV = '6050403020'        # synthetic
BASE = time.mktime((2026, 11, 10, 0, 0, 0, 0, 0, -1))


def at(hhmmss):
    h, m, s = (int(x) for x in hhmmss.split(':'))
    return BASE + h * 3600 + m * 60 + s


def row(direction, mid, hhmmss, text, reply_to=None, att=None, chat=GROUP):
    return {'chat': chat, 'dir': direction, 'mid': str(mid), 'at': at(hhmmss), 'text': text, 'reply_to': reply_to,
            'attachment_kind': att}


# 2026-11-10 10:04-10:35, the shape of the real turns (synthetic words, the real times and kinds of reply).
TODAY = [
    row('in', 4372, '10:04:43', 'jo toljad a papásat is lássuk'),
    row('out', 4374, '10:04:49', 'Megy, Dave a rajzok után egyből összerakja a papás filmet.'),
    row('in', 4389, '10:13:03', 'a nyitó felirat inkább egy napra legyen, a végén a könyves rész hosszabb'),
    row('out', 4391, '10:13:14', 'Átírva: egy napra. A könyves rész hosszabb lesz, lassan lapoz.'),
    row('in', 4392, '10:14:08', 'a záró felirat ez legyen: minden apró pillanat egy könyvben'),
    row('out', 4394, '10:14:13', 'Betűre így kerül be, Dave ezzel vágja a könyves részt. Amint kész, küldöm.'),
    row('in', 4395, '10:17:38', 'na'),
    row('out', 4397, '10:18:32', 'Kész a papás film (35 mp), a végén a könyv és a zárókártya.'),
    row('in', 4405, '10:24:25', 'mi értelme a business fióknak? nem lett volna jobb a sima?'),
    row('out', 4407, '10:24:38', 'Röviden: a zenén a sima fiók nem segítene.'),
    row('in', 4419, '10:26:16', 'add inkább a kész javított videókat'),
    row('out', 4421, '10:26:47', 'A javított változatok még nincsenek kész. Amint az első kész, küldöm.'),
    row('in', 4422, '10:27:02', 'kurvalassu'),
]

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def mids(reqs):
    return [q['mid'] for q in reqs]


@case
def the_baby_film_wait_alerts_by_1030(_root):
    now = at('10:29:10')
    reqs = W.open_requests(TODAY, {}, now)
    # 4372: the 10:18 "Kész a papás" names its product -> closed. 4389: answered without a promise. 4405: answered.
    # 4392: promised at 10:14 ("Amint kész, küldöm"), no result -> open. 4419: promised at 10:26.
    assert mids(reqs) == ['4392', '4419'], mids(reqs)
    assert mids(W.due_alerts(reqs, {}, now)) == ['4392']
    assert W.due_alerts(W.open_requests(TODAY, {}, at('10:28:00')), {}, at('10:28:00')) == []  # not 15 min yet


@case
def a_result_quoting_the_request_or_the_promise_closes_it(_root):
    for quote in ('4392', '4394'):
        rows = TODAY + [row('out', 4445, '10:35:29', 'Kész a babás a javításaiddal (38 mp).', reply_to=quote)]
        assert mids(W.open_requests(rows, {}, at('10:36:00'))) == ['4419'], quote
    # Unquoted, naming another product, with two promises open: closes neither (the 10:13-10:35 gap is real).
    rows = TODAY + [row('out', 4445, '10:35:29', 'Kész a recept film.')]
    assert mids(W.open_requests(rows, {}, at('10:36:00'))) == ['4392', '4419']


@case
def a_file_is_a_result_an_ack_promise_is_not(_root):
    base = [row('in', 1, '09:00:00', 'csináld meg a papás filmet a mai szöveggel'),
            row('out', 2, '09:00:20', 'Átadtam Dave-nek, ő rajzolja.')]
    assert mids(W.open_requests(base, {}, at('09:20:00'))) == ['1']
    filed = base + [row('out', 3, '09:18:00', 'Itt a film', att='file')]
    assert W.open_requests(filed, {}, at('09:20:00')) == []
    unanswered = [row('in', 5, '09:00:00', 'hol tart a chat-könyv teszt?')]
    assert mids(W.open_requests(unanswered, {}, at('09:16:00'))) == ['5']  # no reply at all: open too


@case
def answers_acks_and_nudges(_root):
    rows = [row('in', 1, '09:00:00', 'macbookot használjátok?'), row('out', 2, '09:00:30', 'Ma még nem.'),
            row('in', 3, '09:01:00', 'ok'), row('in', 4, '09:02:00', 'jo lesz a babás'), row('in', 5, '09:03:00', 'videok'),
            row('in', 6, '09:04:00', '👍'), row('in', 7, '09:05:00', 'te gyökér')]
    assert W.open_requests(rows, {}, at('09:40:00')) == []
    assert not W.is_ack('jo toljad a papásat is lássuk') and W.is_ack('neeem') and W.is_ack('OK.')
    assert W.is_result({'text': '**Kész** a babás'}) and W.is_result({'text': 'Elkészült.'})
    assert not W.is_result({'text': 'Átadtam Dave-nek'})
    assert W.is_promise('Indul a receptes film, Dave a papás után rajzolja.') and W.is_promise('Amint kész, küldöm.')
    assert not W.is_promise('Rendben, a filmek zene nélkül jönnek.')


@case
def a_manual_close_alerts_repeat_and_stop(_root):
    reqs = W.open_requests(TODAY, {'4392': {'at': at('10:20:00'), 'note': 'kiadva'}}, at('10:29:10'))
    assert '4392' not in mids(reqs)
    state = {}
    reqs = W.open_requests(TODAY, {}, at('10:29:10'))
    assert len(W.due_alerts(reqs, state, at('10:29:10'))) == 1
    assert W.due_alerts(reqs, state, at('10:34:10')) == []  # one message per 15 min
    assert mids(W.due_alerts(reqs, state, at('10:44:10'))) == ['4392', '4419']
    for t in ('10:59:10', '11:14:10'):
        W.due_alerts(reqs, state, at(t))
    assert state['alerted']['4392'][1] == W.MAX_ALERTS
    assert mids(W.due_alerts(reqs, state, at('11:29:10'))) == ['4419']  # 4392: named 4 times
    assert '4392' not in mids(W.open_requests(TODAY, {}, at('10:14:08') + W.MAX_AGE_S + 1))  # too old: not chased


@case
def the_idle_macbook_1020_1032_alerts_by_1025(_root):
    state = {}
    assert W.machine_alerts(state, {'Mac mini': True, 'MacBook': False}, True, at('10:20:00')) == []
    assert W.machine_alerts(state, {'Mac mini': True, 'MacBook': False}, True, at('10:23:00')) == []
    got = W.machine_alerts(state, {'Mac mini': True, 'MacBook': False}, True, at('10:25:00'))
    assert [m for m, _ in got] == ['MacBook'], got
    assert W.machine_alerts(state, {'Mac mini': True, 'MacBook': False}, True, at('10:30:00')) == []
    assert [m for m, _ in W.machine_alerts(state, {'Mac mini': True, 'MacBook': False}, True, at('10:40:00'))] == ['MacBook']
    # Nobody waits: no alert, however long the machine stands.
    assert W.machine_alerts({}, {'MacBook': False}, False, at('10:00:00')) == []
    s2 = {'machines': {'MacBook': {'last_busy': at('09:00:00')}}}
    assert W.machine_alerts(s2, {'MacBook': False}, False, at('10:00:00')) == []
    # A busy machine resets its clock.
    s3 = {'machines': {'MacBook': {'last_busy': at('09:00:00')}}}
    assert W.machine_alerts(s3, {'MacBook': True}, True, at('10:00:00')) == []
    assert W.machine_alerts(s3, {'MacBook': False}, True, at('10:04:00')) == []


@case
def only_render_work_makes_a_free_machine_alert(_root):
    # 2026-11-10 11:00, the first live run: four [SZABAD GÉP] messages for requests that named no render work.
    for text, promise in [
        ('egy induló webshop vagyunk, a márka bevezetése a cél', 'Átállítom rá a csapatot, Májsztró átírja a tervet.'),
        ('nézzétek meg mások miként csinálták, mik a mai trendek', 'Radar 12:00-ra összegyűjti.'),
        ('ha felderítunk egy hibát, legyen rá kapu', 'A két kaput kiadtam Kernelnek, ma készül.'),
        ('képes vagy rá holnapra?', 'Megnézem, ma készül.'),
    ]:
        assert not W.render_related({'text': text, 'promise': promise}), text
    for text, promise in [
        ('a babás még mindig nem jó', 'Dave most javítja, amint kész, küldöm.'),
        ('mikor lesz meg?', 'A papás kisfilm most renderel a MacBookon.'),
        ('kérem a TikTok-videókat', 'Indul.'),
        ('csináljatok új képeket a receptkönyvhöz', 'Átadtam Dave-nek.'),
        ('a 3D könyv nem A5', 'Dave most javítja.'),
        ('Reels kell belőle', 'Amint kész, küldöm.'),
        ('a záró felirat ez legyen', 'Amint kész, küldöm.'),
    ]:
        assert W.render_related({'text': text, 'promise': promise}), text
    # The day's baby-film requests in the fixture are render work.
    reqs = W.open_requests(TODAY, {}, at('10:29:10'))
    assert all(W.render_related(q) for q in reqs), [q['text'] for q in reqs]


@case
def two_idle_machines_are_one_message(_root):
    now = at('11:00:00')
    waiting = [{'text': 'a babás még mindig nem jó', 'at': at('10:40:00'), 'promise': 'Dave most javítja.'}]
    one = W.free_machine_text([('Mac mini', 300), ('MacBook', 360)], waiting, now)
    assert one.count('[SZABAD GÉP]') == 1 and 'Mac mini (5 perce' in one and 'MacBook (6 perce' in one, one
    assert '«a babás még mindig nem jó» (20 p)' in one, one
    assert W.free_machine_text([], waiting, now) is None


@case
def machines_busy_reads_the_processes(_root):
    procs = [('1', 'ssh -n -F /x/ssh_config render-mac render 1901ea62-c9e7-4093-83e3-da4f1f50fd7c'),
             ('2', 'grep render-mac')]
    assert W.machines_busy(procs) == {'Mac mini': False, 'MacBook': True}
    for cmd in ['node render.mjs /w/film export /w/out/a.mp4', '/Applications/Blender.app/Contents/MacOS/Blender -b x',
                '/opt/homebrew/bin/ffmpeg -v error -i a.mov b.mp4']:
        assert W.machines_busy([('3', cmd)]) == {'Mac mini': True, 'MacBook': False}, cmd
    assert W.machines_busy([('4', 'ssh -F /x render-mac ping')]) == {'Mac mini': False, 'MacBook': False}


def make_root(root, rows):
    store = os.path.join(root, 'store')
    os.makedirs(store)
    with open(os.path.join(store, 'projektek.json'), 'w', encoding='utf-8') as f:
        json.dump({'elo_uzenet': {'csoport': {'chat_id': GROUP}, 'privat': PRIV}}, f)
    con = sqlite3.connect(os.path.join(store, 'claudeclaw.db'))
    con.execute('CREATE TABLE conversation_log (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL,'
                ' chat_id TEXT NOT NULL, direction TEXT NOT NULL, message_id TEXT, text TEXT, ts TEXT,'
                ' created_at INTEGER NOT NULL, attachment_kind TEXT, attachment_file_id TEXT,'
                ' reply_to_message_id TEXT, source TEXT, UNIQUE(agent_id, chat_id, direction, message_id))')
    for r in rows:
        con.execute('INSERT INTO conversation_log (agent_id, chat_id, direction, message_id, text, created_at,'
                    ' reply_to_message_id, attachment_kind) VALUES (?,?,?,?,?,?,?,?)',
                    ('klodel', r['chat'], r['dir'], r['mid'], r['text'], int(r['at']), r['reply_to'], r['attachment_kind']))
    con.execute("INSERT INTO conversation_log (agent_id, chat_id, direction, message_id, text, created_at)"
                " VALUES ('klodel', '777', 'in', '9', 'egy másik chat kérése, ez nem számít', ?)", (int(at('10:00:00')),))
    con.commit()
    con.close()


def cli(root, *args):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root)
    env.pop('MARVEEN_OWNER_CHATS', None)
    return subprocess.run([sys.executable, '-I', SCRIPT, *args], capture_output=True, text=True, env=env, timeout=60)


@case
def the_cli_reads_the_ledger_and_closes_by_hand(root):
    make_root(root, TODAY)
    r = cli(root, 'check', '--dry', '--now', str(at('10:29:10')))
    assert r.returncode == 0, r.stderr
    assert '[klodel] [VÁRAKOZÁS-ÓRA] 1 kérés' in r.stdout and 'msg 4392' in r.stdout, r.stdout
    assert 'másik chat' not in r.stdout and not os.path.exists(os.path.join(root, 'store', 'patrik-varakozas.json'))
    assert cli(root, 'close', '4392', 'kiadva Dave-nek', '--now', str(at('10:29:30'))).returncode == 0
    r = cli(root, 'check', '--dry', '--now', str(at('10:29:40')))
    assert 'VÁRAKOZÁS-ÓRA' not in r.stdout, r.stdout
    r = cli(root, 'list', '--now', str(at('10:29:40')))
    assert 'msg 4419' in r.stdout and 'msg 4392' not in r.stdout, r.stdout
    assert cli(root, 'close', '12; rm -rf /').returncode == 2


@case
def ledger_outbound_records_reply_to_and_files(root):
    db = os.path.join(root, 'ledger.db')
    env = dict(os.environ, LEDGER_DB_PATH=db, MARVEEN_AGENT_ID='klodel')
    def send(tool_input, mid):
        payload = {'tool_name': 'mcp__plugin_telegram_telegram__reply', 'tool_input': tool_input,
                   'tool_response': [{'type': 'text', 'text': f'sent (id: {mid})'}]}
        subprocess.run([sys.executable, OUTBOUND], input=json.dumps(payload), text=True, env=env, timeout=30, check=True)
    send({'chat_id': GROUP, 'text': 'Kész a babás', 'reply_to': '4389', 'files': ['/tmp/x.mp4']}, 501)
    send({'chat_id': GROUP, 'text': 'Átadtam Dave-nek'}, 502)
    con = sqlite3.connect(db)
    got = con.execute("SELECT message_id, reply_to_message_id, attachment_kind, attachment_file_id FROM conversation_log"
                      " WHERE direction='out' ORDER BY id").fetchall()
    con.close()
    assert got == [('501', '4389', 'file', None), ('502', None, None, None)], got


def main():
    failed = 0
    for fn in CASES:
        with tempfile.TemporaryDirectory() as root:
            try:
                fn(root)
                print(f'ok   {fn.__name__}')
            except AssertionError as e:
                failed += 1
                print(f'FAIL {fn.__name__}: {e}')
    print(f'{len(CASES) - failed}/{len(CASES)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
