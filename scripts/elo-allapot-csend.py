#!/usr/bin/env python3
"""elo-allapot-csend.py -- the live status round's silence reminder: a primary project is running and the main agent
has not written into its chat for more than 15 minutes.

Usage: python3 -I scripts/elo-allapot-csend.py [--projects FILE] [--now EPOCH]

Why (card 5e664183, hibanapló 2026-11-16, Patrik group TG 6187: "miért nem updatelsz?"): 20 minutes of silence
during the BubekAI work, while only edit_message calls (the live status message) went out. An edit is not an update
for Patrik; a new message is.

What it checks (read only):
  - store/projektek.json projektek[] with "elsodleges": true (Klodel sets it) that are not done (no steps, or a step
    with "kesz" not true), and whose "chat" is "csoport" or "privat" (elo_uzenet.<chat>.chat_id gives the chat id);
  - the newest OUTGOING row of the main agent in that chat in the conversation ledger (store/claudeclaw.db
    conversation_log, direction 'out'). Only replies write those rows (scripts/hooks/ledger-outbound.py); an
    edit_message writes none, so an edit never counts as "written". Only created_at is read, never a text.
Exit codes and output:
  0 = no reminder: no primary project, all of them done, or the last outgoing message is at most SILENCE_S old;
      nothing on stdout or stderr.
  5 = reminder: ONE line on stderr naming the project(s), the chat and the minutes since the last outgoing message
      ("soha" when there is none). The round writes one line to Patrik (a reply, not an edit).
  2 = cannot measure (projects file or ledger unreadable, chat id unknown): one line on stderr; no reminder decided.
The ledger is LEDGER_DB_PATH or the install's (scripts/hooks/ledger_lib.py), opened read-only, never created.
Tests: python3 -I scripts/__tests__/elo-allapot-csend.test.py
"""
import json
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'hooks'))

SILENCE_S = 15 * 60
CHATS = ('csoport', 'privat')
REMIND, CANNOT = 5, 2


def primary_open(data):
    """(title, chat key) of the primary, not-done projects with a known chat key."""
    out = []
    for p in data.get('projektek') or []:
        if not isinstance(p, dict) or p.get('elsodleges') is not True or p.get('chat') not in CHATS:
            continue
        steps = p.get('lepesek')
        done = isinstance(steps, list) and bool(steps) and all(isinstance(s, dict) and s.get('kesz') is True
                                                                for s in steps)
        if not done:
            out.append((str(p.get('cim') or p.get('nev') or p.get('id') or '?')[:60], p['chat']))
    return out


def chat_id(data, key):
    v = (data.get('elo_uzenet') or {}).get(key)
    v = v.get('chat_id') if isinstance(v, dict) else v
    return str(v).strip() if v is not None and str(v).strip() else None


def last_out(db, agent, chat):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=5)
    try:
        row = con.execute("SELECT MAX(created_at) FROM conversation_log WHERE agent_id=? AND chat_id=? "
                          "AND direction='out'", (str(agent), str(chat))).fetchone()
    finally:
        con.close()
    return row[0] if row and isinstance(row[0], int) else None


def main(argv):
    projects, now = os.path.join(ROOT, 'store', 'projektek.json'), None
    rest = list(argv[1:])
    while rest:
        a = rest.pop(0)
        if a == '--projects' and rest:
            projects = rest.pop(0)
        elif a == '--now' and rest and rest[0].isdigit():
            now = int(rest.pop(0))
        else:
            print('usage: elo-allapot-csend.py [--projects FILE] [--now EPOCH]', file=sys.stderr)
            return CANNOT
    now = int(time.time()) if now is None else now
    try:
        with open(projects, encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError('not an object')
    except (OSError, ValueError) as e:
        print(f'elo-allapot-csend: a projektlap nem olvasható ({e.__class__.__name__}), a csend nem mérhető',
              file=sys.stderr)
        return CANNOT
    todo = primary_open(data)
    if not todo:
        return 0
    try:
        import ledger_lib
        db, agent = ledger_lib.db_path(), ledger_lib.main_agent_id()
    except Exception as e:
        print(f'elo-allapot-csend: a napló helye nem állapítható meg ({e.__class__.__name__})', file=sys.stderr)
        return CANNOT
    late = []
    for title, key in todo:
        cid = chat_id(data, key)
        if not cid:
            print(f'elo-allapot-csend: az elo_uzenet.{key}.chat_id ismeretlen, a csend nem mérhető', file=sys.stderr)
            return CANNOT
        try:
            at = last_out(db, agent, cid)
        except sqlite3.Error as e:
            print(f'elo-allapot-csend: a beszélgetésnapló nem olvasható ({e.__class__.__name__})', file=sys.stderr)
            return CANNOT
        if at is None:
            late.append(f'„{title}” ({key}: soha)')
        elif now - at > SILENCE_S:
            late.append(f'„{title}” ({key}: {(now - at) // 60} perce, {time.strftime("%H:%M", time.localtime(at))})')
    if not late:
        return 0
    print('CSEND (5e664183, TG 6187 „miért nem updatelsz?”): elsődleges projekt fut, és a chatjébe '
          f'{SILENCE_S // 60} percnél régebben ment új üzenet (az edit nem számít): ' + '; '.join(late)
          + '. Írj egy sort (reply, nem edit).', file=sys.stderr)
    return REMIND


if __name__ == '__main__':
    sys.exit(main(sys.argv))
