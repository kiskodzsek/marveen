#!/usr/bin/env python3
"""PreToolUse gate (telegram reply): a step put on the owner goes out only after the team measured there is no
internal route.

Why (Klodel 41154; hibanapló 2026-11-13 18:36, second occurrence): Patrik, group TG 6049: "Idiota". TG 6048 put the
Kiemelés button on Patrik although an internal route existed (the video upload through Kernel's
meta-video-url-feltoltes skill); the first occurrence was TG 17727 (card baf41075, Klodel 40533).

What blocks (exit 2): a reply into one of the owner's chats (store/projektek.json elo_uzenet "privat" / "csoport", or
MARVEEN_OWNER_CHATS) whose text puts a step on the reader ("nyomd meg", "te nyomod", "kattints", "lépj be",
"töltsd fel", "te indítod", "futtasd", "másold be", "a gépnél" ...), unless the agent took a fresh PATRIK-LEPES
reply mark for the chat right before (scripts/reply-mark.py PATRIK-LEPES --chat <chat> "<value>"). The value must
name who measured that there is no internal route and the msg_id of that measurement: another fleet agent's name
(<install>/agents/<name>/, or the main agent id; not the writer's own, Viktor 41257 LOW 2) and a 4-7 digit id that is a
row of the inter-agent queue (store/claudeclaw.db agent_messages) from the last 7 days with that agent as its sender or
recipient: the mark is a reference, not a claim. One mark = one message (scripts/lib/reply_marks.py).
The owner's chats unknown (no MARVEEN_OWNER_CHATS, store/projektek.json unreadable or of another shape): the gate
passes and says so on stderr, once per call (Viktor 41257 MEDIUM).
Passes: a negated sentence ("nem kell nyomnod", "ne töltsd fel"), past tense ("megnyomtad", "feltöltöttük": no
trigger), a quoted text („...”: customer copy in te-form goes in quotes), a sentence addressed to Balázs (balazs-task-reply-gate.py owns that), edits
(edit_message: the live status message lists what waits on whom by design), other chats, unreadable input.
Wiring: .claude/settings.json PreToolUse, matcher "mcp__plugin_telegram_telegram__reply".
Tests: patrik-step-reply-gate_test.py next to this file.
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
# CLAUDE_PROJECT_DIR is what the hook command itself runs from ("$CLAUDE_PROJECT_DIR/scripts/hooks/..."): in
# production the same directory as INSTALL; tests point it at a throwaway root with its own store/projektek.json.
ROOT = os.environ.get('CLAUDE_PROJECT_DIR') or INSTALL
STORE = os.path.join(ROOT, 'store')
MSG_MAX_AGE_S = 7 * 86400

INVISIBLE = re.compile('[­᠎​-‏‪-‮⁠-⁤﻿]')
QUOTED = re.compile(r'„[^”\n]*”|“[^”\n]*”|"[^"\n]*"|»[^«\n]*«|«[^»\n]*»')
URL = re.compile(r'https?://\S+')
SENTENCE = re.compile(r'[.!?;\n]+')

# Second-person steps (imperative, "te ...-od", "... kell -ned"). Past tense and first person plural ("megnyomtad",
# "feltöltjük") are deliberately absent: they report, they do not ask.
STEP = re.compile(r'(?<!\w)(?:' + '|'.join([
    r'nyomd\s+(?:meg|rá|le|be)', r'nyomj\s+(?:rá|egy)', r'(?:meg)?nyomod', r'(?:meg)?nyomnod\s+kell',
    r'kattints(?:d|\s+rá)?', r'(?:rá)?kattintasz', r'kattintanod\s+kell',
    r'lépj\s+be', r'jelentkezz\s+be', r'(?:be)?lépsz(?:\s+be)?', r'be\s+kell\s+(?:lépned|jelentkezned)',
    r'töltsd\s+(?:fel|le)', r'tölts\s+fel', r'(?:fel|le)töltöd', r'töltöd\s+(?:fel|le)',
    r'(?:fel|le)\s+kell\s+töltened',
    r'indítsd(?:\s+el)?', r'(?:el)?indítod', r'el\s+kell\s+indítanod',
    r'futtasd(?:\s+le)?', r'(?:le)?futtatod', r'futtass',
    r'másold\s+(?:be|át|ki)', r'illeszd\s+be', r'írd\s+be', r'gépeld\s+be',
    r'add\s+meg\s+(?:a\s+)?(?:jelszót?|kódot?|tokent?)',
    r'telepítsd(?:\s+fel)?', r'(?:fel)?telepíted',
    r'kapcsold\s+(?:be|ki)', r'állítsd\s+be',
    r'a\s+gépnél(?!-)',  # not the noun compound "gépnél-lista" (measured: 3 of 105 hits, 7 days)
]) + r')(?!\w)', re.IGNORECASE)
NEGATION = re.compile(r'(?<!\w)(?:nem|ne|se|sem|nincs|nélküled)(?!\w)', re.IGNORECASE)
NEG_WINDOW_WORDS = 4
MSG_ID = re.compile(r'(?<!\d)\d{4,7}(?!\d)')


def fold(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c)).lower()


def owner_chats():
    """The owner's chats (same rule as patrik-reply-volume-gate.py): MARVEEN_OWNER_CHATS, else projektek.json."""
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


def step_phrase(text):
    """The first step the text puts on the reader, or None."""
    t = INVISIBLE.sub('', unicodedata.normalize('NFKC', str(text or '')))
    t = URL.sub(' ', QUOTED.sub(' ', t))
    for sentence in SENTENCE.split(t):
        low = fold(sentence)
        if 'balazs' in low and 'patrik' not in low:
            continue
        for m in STEP.finditer(sentence):
            before = sentence[:m.start()].split()[-NEG_WINDOW_WORDS:]
            if any(NEGATION.fullmatch(w.strip(',:()')) for w in before):
                continue
            return m.group(0)
    return None


def agent_names():
    names = set()
    d = os.environ.get('MARVEEN_AGENTS_DIR') or os.path.join(ROOT, 'agents')
    try:
        for n in os.listdir(d):
            if os.path.isdir(os.path.join(d, n)) and re.fullmatch(r'[a-z][a-z0-9_-]{1,30}', n):
                names.add(n)
    except OSError:
        pass
    try:
        import ledger_lib
        main = ledger_lib.main_agent_id()
        if main:
            names.add(fold(main))
    except Exception:
        pass
    return names


def value_problem(value, names, writer='', now=None):
    """Why a PATRIK-LEPES value does not name the measurement, or None. The value must name ANOTHER fleet agent and a
    msg_id that is a queue row of the last 7 days with that agent as sender or recipient."""
    v = fold(value or '')
    ids = [int(x) for x in MSG_ID.findall(v)]
    if not ids:
        return 'nincs benne a mérés msg_id-je (4-7 jegyű szám)'
    words = set(re.findall(r'[a-z0-9_-]+', v))
    named = (words & names) - {fold(writer or '')}
    if not named:
        return ('nem nevez meg MÁSIK csapattagot (ki mérte: ' + ', '.join(sorted(names - {fold(writer or '')}))
                + '; a saját neved nem mérés)')
    now = time.time() if now is None else now
    try:
        import ledger_lib
        con = sqlite3.connect(f'file:{ledger_lib.db_path()}?mode=ro', uri=True, timeout=5)
        try:
            rows = con.execute(
                'SELECT from_agent, to_agent, created_at FROM agent_messages WHERE id IN (%s)' % ','.join('?' * len(ids)),
                ids).fetchall()
        finally:
            con.close()
    except Exception:
        return 'az üzenetsor nem olvasható, a msg_id nem ellenőrizhető'
    for frm, to, at in rows:
        if (fold(str(frm)) in named or fold(str(to)) in named) and isinstance(at, int) and 0 <= now - at <= MSG_MAX_AGE_S:
            return None
    return ('a msg_id (' + ', '.join(map(str, ids)) + ') nem olyan 7 napon belüli üzenet az üzenetsorban, amelynek '
            + ' vagy '.join(sorted(named)) + ' a feladója vagy címzettje')


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
        print('patrik-step-reply-gate: the owner\'s chats are unknown (MARVEEN_OWNER_CHATS / store/projektek.json '
              'elo_uzenet); the gate is off.', file=sys.stderr)
        return 0
    if chat not in chats:
        return 0
    phrase = step_phrase(ti.get('text', ''))
    if not phrase:
        return 0
    try:
        import ledger_lib
        import reply_marks
        agent = ledger_lib.agent_id_from_payload(payload) or ledger_lib.main_agent_id()
        reply_marks.bind_call(payload)
        value = reply_marks.take('PATRIK-LEPES', chat, agent)
    except Exception:
        agent, value = '', None
    head = (f'LÉPÉS-KAPU (Patrik TG 6049 „Idiota”, TG 17727; Klodel 41154): a szöveg Patrikra tesz teendőt '
            f'(„{phrase}”). ')
    how = ('Előbb mérd meg, van-e belső út (csapattag, skill, API); ha nincs, jelöld előtte (a szövegbe nem kerül): '
           'python3 -I scripts/reply-mark.py PATRIK-LEPES --chat <privat|csoport> "<ki mérte> <msg_id>: <miért nincs '
           'belső út>" (a msg_id a csapattag 7 napon belüli üzenete az üzenetsorban). Ha nem neki szól, írd át („mi feltöltjük”); vevőnek szóló szöveg (poszt, hirdetés) „...” közé.')
    if value is None:
        print(head + how, file=sys.stderr)
        return 2
    problem = value_problem(value, agent_names(), agent)
    if problem:
        print(head + f'A PATRIK-LEPES jel {problem}. ' + how, file=sys.stderr)
        return 2
    if not reply_marks.spend_pending():
        print('LÉPÉS-KAPU: a PATRIK-LEPES jel közben elfogyott (egy jel = egy üzenet); jelölj újra.', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
