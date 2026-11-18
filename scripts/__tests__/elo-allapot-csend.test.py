#!/usr/bin/env python3
"""Tests for scripts/elo-allapot-csend.py (card 5e664183): the silence reminder of the live status round.

Hermetic: a temp projects file, a temp conversation ledger (LEDGER_DB_PATH), MAIN_AGENT_ID=main, synthetic chat ids,
a fixed --now. Nothing under store/ is read or written.
Run: python3 -I scripts/__tests__/elo-allapot-csend.test.py
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), 'elo-allapot-csend.py')
NOW = 1_800_000_000
GROUP, PRIV = '-222', '111'
FAILS = []


def check(label, got, want):
    ok = got == want
    print(('PASS  ' if ok else 'FAIL  ') + label + ('' if ok else f'  -- got {got!r}, want {want!r}'))
    if not ok:
        FAILS.append(label)


tmp = tempfile.mkdtemp(prefix='elo-csend-')
DB = os.path.join(tmp, 'ledger.db')
PROJ = os.path.join(tmp, 'projektek.json')


def reset_db():
    if os.path.exists(DB):
        os.unlink(DB)
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE conversation_log (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL, "
                "chat_id TEXT NOT NULL, direction TEXT NOT NULL, message_id TEXT, text TEXT, ts TEXT, "
                "created_at INTEGER NOT NULL)")
    con.commit()
    con.close()


def row(chat, direction, age, agent='main'):
    con = sqlite3.connect(DB)
    con.execute("INSERT INTO conversation_log (agent_id, chat_id, direction, created_at) VALUES (?, ?, ?, ?)",
                (agent, chat, direction, NOW - age))
    con.commit()
    con.close()


def project(elsodleges=True, chat='csoport', steps=((True,), (False,)), **extra):
    p = {'id': 'p1', 'cim': 'BubekAI PoC', 'chat': chat,
         'lepesek': [{'nev': f's{i}', 'kesz': s[0]} for i, s in enumerate(steps)]}
    if elsodleges is not None:
        p['elsodleges'] = elsodleges
    p.update(extra)
    return p


def write(projects, elo=None):
    with open(PROJ, 'w', encoding='utf-8') as f:
        json.dump({'projektek': projects, 'elo_uzenet': elo if elo is not None else
                   {'csoport': {'chat_id': int(GROUP), 'message_id': 1}, 'privat': {'chat_id': int(PRIV)}}}, f)


def run(db=None, projects=None):
    env = dict(os.environ, LEDGER_DB_PATH=db or DB, MAIN_AGENT_ID='main')
    p = subprocess.run([sys.executable, '-I', SCRIPT, '--projects', projects or PROJ, '--now', str(NOW)],
                       env=env, capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout, p.stderr


reset_db()
write([project()])
row(GROUP, 'out', 5 * 60)
rc, out, err = run()
check('fresh outgoing message (5 min): silent, exit 0', (rc, out, err), (0, '', ''))

reset_db()
row(GROUP, 'out', 20 * 60)
rc, out, err = run()
check('old outgoing message (20 min): exit 5', rc, 5)
check('old: exactly one stderr line, nothing on stdout', (out, len(err.strip().splitlines())), ('', 1))
check('old: the line names the project, the chat and the minutes', all(s in err for s in ('BubekAI PoC', 'csoport: 20 perce')), True)

reset_db()
row(GROUP, 'out', 15 * 60)
check('exactly 15 min: still silent (more than 15 is late)', run()[0], 0)
reset_db()
row(GROUP, 'out', 15 * 60 + 1)
check('15 min 1 s: reminder', run()[0], 5)

reset_db()
write([project(elsodleges=None)])
row(GROUP, 'out', 3600)
check('no primary project: silent', run()[:2], (0, ''))
write([project(elsodleges='true')])
check('"elsodleges": "true" (a string) is not the marker: silent', run()[0], 0)
write([project(steps=((True,), (True,)))])
check('primary but every step done: silent', run()[0], 0)
write([project(chat='archiv')])
check('primary in the archive (chat "archiv"): silent', run()[0], 0)

reset_db()
write([project()])
row(GROUP, 'in', 60)
rc, _, err = run()
check('only inbound rows in the chat (no message of ours ever): reminder with "soha"', (rc, 'soha' in err), (5, True))

reset_db()
row(GROUP, 'out', 60, agent='dave')
check("another agent's fresh message does not count", run()[0], 5)
reset_db()
row(PRIV, 'out', 60)
check('a fresh message in the OTHER chat does not count', run()[0], 5)

reset_db()
write([project(chat='privat')])
row(PRIV, 'out', 60)
check('primary private project, fresh message in the private chat: silent', run()[0], 0)

reset_db()
write([project(), project(id='p2', cim='Másik', chat='privat')])
row(GROUP, 'out', 60)
row(PRIV, 'out', 40 * 60)
rc, _, err = run()
check('two primaries, one silent: one line naming only the late one', (rc, 'Másik' in err, 'BubekAI' in err,
                                                                     len(err.strip().splitlines())), (5, True, False, 1))

write([project()])
check('ledger missing: exit 2 (cannot measure), the file is not created',
      (run(db=os.path.join(tmp, 'nincs.db'))[0], os.path.exists(os.path.join(tmp, 'nincs.db'))), (2, False))
with open(os.path.join(tmp, 'rossz.json'), 'w') as f:
    f.write('{nem json')
check('projects file unreadable: exit 2', run(projects=os.path.join(tmp, 'rossz.json'))[0], 2)
write([project()], elo={'privat': {'chat_id': 1}})
check('chat id of the project chat unknown: exit 2', run()[0], 2)
write([], elo={})
check('no projects at all: silent even without chat ids', run()[0], 0)

subprocess.run(['rm', '-r', '--', tmp], check=False)
if FAILS:
    print(f'\n{len(FAILS)} FAILED: {FAILS}', file=sys.stderr)
    sys.exit(1)
print('\nAll elo-allapot-csend tests passed.')
