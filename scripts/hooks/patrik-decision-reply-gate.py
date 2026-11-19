#!/usr/bin/env python3
"""PreToolUse gate (telegram reply): a decision asked of the owner goes out only with a PATRIK-DONTES mark that names
why only he can decide, and where that fact stands.

Why (card dd706ced; hibanapló 2026-11-16 13:54, fifth occurrence of an internal step put before Patrik): group TG
6275 asked Patrik for a yes to start a Codex review round his own request (TG 6272) already covered; TG 6276: "de nem
értem pontosan mit vársz tőlem.. kértem hogy fusson már a code review és azt is elmondtam miként add az
eredményét". patrik-step-reply-gate.py stops a STEP put on him, not a DECISION asked of him.

What blocks (exit 2): a reply into one of the owner's chats (store/projektek.json elo_uzenet "privat" / "csoport", or
MARVEEN_OWNER_CHATS) whose unquoted text asks him to decide (🔴, "igen / nem", "Mehet?", "Indulhat?", "A vagy B?",
"döntés kell tőled", "döntsd el", "jóváhagyod?", "rábólintasz?" ...), unless the agent took a fresh PATRIK-DONTES
reply mark for the chat right before (scripts/reply-mark.py PATRIK-DONTES --chat <chat> "<value>"). The value must:
- name why only he can decide, one of REASONS: penz | titok | jog | termek-ar | eles-env-kulcs | kulso-level |
  adat-torles | uj-epites (a reading or checking step - review, measurement, rerun, order - is none of them);
- reference the fact: "TG <n>" that is an INBOUND message of one of the owner's chats (store/claudeclaw.db
  conversation_log), or a 4-7 digit msg_id that is a row of the inter-agent queue (agent_messages) of the last 7 days.
One mark = one message (scripts/lib/reply_marks.py). Word matching: an accident guard against a reflex question, not
a proof; whoever writes a false reason passes.
The owner's chats unknown: the gate passes and says so on stderr (as patrik-step-reply-gate.py).
Viktor 48130: "Mehet ...?" up to 80 characters in the sentence; a negation counts in its own clause only; the Balázs
exception only for a sentence that addresses him ("Balázs, ..."); "a jóváhagyásod szerint / megkaptuk" is a report.
Passes: a negated sentence ("nem kell döntened", "nincs teendőd, nem kell jóváhagynod"), a report of his decision
("jóváhagytad", "Patrik döntése szerint"), a quoted text („...”), a sentence addressed to Balázs, edits
(edit_message), other chats, unreadable input.
Wiring: .claude/settings.json PreToolUse, matcher "mcp__plugin_telegram_telegram__reply|...edit_message" (edits pass
here by the tool-name check). Tests: patrik-decision-reply-gate_test.py next to this file.
"""
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'lib'))
INSTALL = os.path.dirname(os.path.dirname(HERE))
ROOT = os.environ.get('CLAUDE_PROJECT_DIR') or INSTALL
STORE = os.path.join(ROOT, 'store')
MSG_MAX_AGE_S = 7 * 86400

INVISIBLE = re.compile('[­᠎​-‏‪-‮⁠-⁤﻿]')
QUOTED = re.compile(r'„[^”\n]*”|“[^”\n]*”|"[^"\n]*"|»[^«\n]*«|«[^»\n]*»')
URL = re.compile(r'https?://\S+')
SENTENCE = re.compile(r'[.!?;]+(?=\s|$)|\n+')
RED = '\U0001F534'

# A decision asked of the reader, on folded text (no accents, lower). Second person or a bare question: a report of
# a decision ("jóváhagytad", "Patrik döntése szerint") is absent by design.
DECISION = re.compile(r'(?<![a-z0-9])(?:' + '|'.join([
    r'igen\s*(?:/|vagy|-)\s*nem',
    r'mehet(?:-e)?[^!?\n]{0,80}\?',
    r'indulhat(?:ok|unk|nak)?(?:-e)?[^!?\n]{0,80}\?', r'indulhat(?:ok|unk|nak)?-e',
    r'dontes(?:ed)?\s+kell(?:ene)?(?:\s+toled|\s+toletek)?', r'kell\s+(?:egy\s+|ket\s+)?dontes(?:ed)?',
    r'dontsd\s+el', r'dontsetek\s+el', r'te\s+dontod',
    r'a\s+te\s+dontesed(?!\s+(?:szerint|alapjan|volt|nyoman))', r'dontesedre', r'dontened\s+kell', r'kell\s+dontened',
    r'jovahagyod', r'jovahagyasod(?:at|ra)?(?!\s+(?:utan|nelkul|szerint|megkaptuk|megvan))', r'jovahagyast\s+kerek', r'jovahagynod\s+kell', r'kell\s+jovahagynod',
    r'rabolintasz', r'rabolintassz', r'igent\s+mondasz', r'igent\s+kerek',
    r'(?:melyik|melyiket)\s+(?:legyen|valasztod|kered)',
]) + r')(?![a-z0-9])')
A_OR_B = re.compile(r'(?<![\w])(?:\(?[AB12][).]?)\s+vagy\s+\(?[AB12][).]?(?![\w])[^?\n]{0,80}\?')
NEGATION = re.compile(r'(?<![a-z])(?:nem|ne|se|sem|nincs|nelkuled)(?![a-z])')
NEG_WINDOW_WORDS = 4
CLAUSE = re.compile(r'[,:;()]|\s[-\u2013]\s')

REASONS = ('penz', 'titok', 'jog', 'termek-ar', 'eles-env-kulcs', 'kulso-level', 'adat-torles', 'uj-epites')
REASON = re.compile(r'(?<![a-z0-9-])(' + '|'.join(re.escape(r) for r in REASONS) + r')(?![a-z0-9-])')
TG_REF = re.compile(r'(?<![a-z])tg\s*#?\s*(\d{2,7})(?!\d)')
MSG_ID = re.compile(r'(?<![\d#])\d{4,7}(?!\d)')


def fold(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c)).lower()


def owner_chats():
    """The owner's chats (same rule as patrik-step-reply-gate.py): MARVEEN_OWNER_CHATS, else projektek.json."""
    env = os.environ.get('MARVEEN_OWNER_CHATS')
    if env:
        return {c.strip() for c in env.split(',') if c.strip()}
    try:
        with open(os.path.join(STORE, 'projektek.json'), encoding='utf-8') as f:
            elo = json.load(f).get('elo_uzenet')
    except Exception:
        return set()
    out = set()
    for key in ('privat', 'csoport'):
        v = elo.get(key) if isinstance(elo, dict) else None
        if isinstance(v, dict):
            v = v.get('chat_id')
        if v is not None and str(v).strip():
            out.add(str(v).strip())
    return out


def decision_phrase(text):
    """The first decision the unquoted text asks of the reader, or None."""
    t = INVISIBLE.sub('', unicodedata.normalize('NFKC', str(text or '')))
    t = URL.sub(' ', QUOTED.sub(' ', t))
    # The red circle is the "döntés kell tőle" mark of the patrik-telegram-kommunikacio skill (rule 5): it always asks.
    if RED in t:
        return RED
    start = 0
    for end_m in list(SENTENCE.finditer(t)) + [None]:
        stop = end_m.start() if end_m else len(t)
        # The question mark ends the sentence; it stays with it ("Mehet?" is a question, "Mehet." is not).
        sentence = t[start:stop] + ('?' if end_m and '?' in end_m.group(0) else '')
        start = end_m.end() if end_m else len(t)
        low = fold(sentence)
        if re.match(r'\W*balazs\s*[,:!]', low) and 'patrik' not in low:
            continue
        m = A_OR_B.search(sentence)
        if m:
            return m.group(0)[:40]
        low_q = low
        for m in DECISION.finditer(low_q):
            before = CLAUSE.split(low_q[max(0, m.start() - 160):m.start()])[-1].split()[-NEG_WINDOW_WORDS:]
            if any(NEGATION.fullmatch(w.strip(',:()')) for w in before):
                continue
            return m.group(0)
    return None


def value_problem(value, chats, now=None):
    """Why a PATRIK-DONTES value does not name a reason and its fact, or None."""
    v = fold(value or '')
    if not REASON.search(v):
        return ('nem nevezi meg, miért csak Patrik dönthet (' + ' | '.join(REASONS) + '; review, mérés, '
                'újrafuttatás, sorrend nem indok)')
    tgs = [int(x) for x in TG_REF.findall(v)]
    rest = TG_REF.sub(' ', v)
    ids = [int(x) for x in MSG_ID.findall(rest)]
    if not tgs and not ids:
        return 'nincs benne a tényt hordozó TG-szám ("TG <n>") vagy msg_id'
    now = time.time() if now is None else now
    try:
        import ledger_lib
        con = sqlite3.connect(f'file:{ledger_lib.db_path()}?mode=ro', uri=True, timeout=5)
        try:
            if tgs and chats:
                q = ('SELECT 1 FROM conversation_log WHERE direction = \'in\' AND message_id IN (%s) AND chat_id IN (%s) '
                     'LIMIT 1' % (','.join('?' * len(tgs)), ','.join('?' * len(chats))))
                if con.execute(q, [str(x) for x in tgs] + sorted(chats)).fetchone():
                    return None
            if ids:
                rows = con.execute('SELECT created_at FROM agent_messages WHERE id IN (%s)' % ','.join('?' * len(ids)),
                                   ids).fetchall()
                if any(isinstance(at, int) and 0 <= now - at <= MSG_MAX_AGE_S for (at,) in rows):
                    return None
        finally:
            con.close()
    except Exception:
        return 'az adatbázis nem olvasható, a hivatkozás nem ellenőrizhető'
    parts = []
    if tgs:
        parts.append('a TG ' + ', '.join(map(str, tgs)) + ' nem Patrik chatjeibe bejött üzenet')
    if ids:
        parts.append('a msg_id ' + ', '.join(map(str, ids)) + ' nem 7 napon belüli sor az üzenetsorban')
    return ' és '.join(parts)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    tool = str(payload.get('tool_name') or '')
    if tool and not tool.endswith('__reply'):
        return 0
    ti = payload.get('tool_input')
    if not isinstance(ti, dict) or not ti.get('chat_id'):
        return 0
    chat = str(ti['chat_id']).strip()
    chats = owner_chats()
    if not chats:
        print('patrik-decision-reply-gate: the owner\'s chats are unknown (MARVEEN_OWNER_CHATS / store/projektek.json '
              'elo_uzenet); the gate is off.', file=sys.stderr)
        return 0
    if chat not in chats:
        return 0
    phrase = decision_phrase(ti.get('text', ''))
    if not phrase:
        return 0
    try:
        import ledger_lib
        import reply_marks
        agent = ledger_lib.agent_id_from_payload(payload) or ledger_lib.main_agent_id()
        reply_marks.bind_call(payload)
        value = reply_marks.take('PATRIK-DONTES', chat, agent)
    except Exception:
        value = None
    head = (f'DÖNTÉS-KAPU (hibanapló 11-16 13:54, TG 6276; kártya dd706ced): a szöveg döntést kér Patriktól '
            f'(„{phrase}”). ')
    how = ('Ha a kérése vagy a szabály már lefedi, ne kérdezd: csináld, és a kész eredményt jelentsd. Ha tényleg csak ő '
           'dönthet, jelöld előtte (a szövegbe nem kerül): python3 -I scripts/reply-mark.py PATRIK-DONTES --chat '
           '<privat|csoport> "<' + '|'.join(REASONS) + '>: <miért> TG <n> | <msg_id>" (a TG Patrik chatjébe bejött '
           'üzenet, a msg_id 7 napon belüli üzenetsor-sor, ami a tényt hordozza).')
    if value is None:
        print(head + how, file=sys.stderr)
        return 2
    problem = value_problem(value, chats)
    if problem:
        print(head + f'A PATRIK-DONTES jel {problem}. ' + how, file=sys.stderr)
        return 2
    if not reply_marks.spend_pending():
        print('DÖNTÉS-KAPU: a PATRIK-DONTES jel közben elfogyott (egy jel = egy üzenet); jelölj újra.', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
