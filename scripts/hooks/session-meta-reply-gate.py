#!/usr/bin/env python3
"""PreToolUse gate (telegram reply + edit_message), every sub-agent: no session-meta line to Patrik's chats.

Why: retro 2026-11-13 R8 (card 84858637, Klodel 41352). After a context-guard restart Dave sent "friss kontextussal
folytatom" to Patrik's Telegram twice (2026-11-11 02:3x, TG 632, Klodel 37179; 2026-11-13 15:56, TG 665). Patrik
TG 666 word for word: "miért irogatod ezt ide mindig??? soha többé nem akarom". The memory note did not stop the
second one; Dave's private gate (agents/dave/bin/tg-restart-meta-gate.py) did, but only for Dave. The resume prompt
itself was fixed in src/web/context-guard-runner.ts (no "jelezz a csatornádon" for a sub-agent, tested in
context-guard-resume-prompt.test.ts); this gate stops the habit for every agent that owns a Telegram bot.

What blocks (exit 2, one line): a reply or an edit to the owner's private chat or the team group whose text talks about
the agent's OWN session state: a fresh context, a handoff or the context-guard next to a first-person state verb
("friss kontextussal folytatom", "auto-handoff után itt vagyok"), "my" context/session full, compacted or
restarted ("kontextusom megtelt"), "új sessionben vagyok", "folytatom a megkezdett munkát", "újraindultam" /
"újraindítottak", in Hungarian (accents folded: Patrik's chats are often written without them) or English.
A restart of something else ("a Vercel-deploy restart után") and a report on ANOTHER agent's session that Patrik
asked about ("Klodel 20:54-kor újraindult") pass. Matching runs over normalised text: NFKC, zero-width characters
dropped, accents folded, "-" and "_" read as a space, whitespace collapsed, case-folded.

Which chats are gated: store/projektek.json elo_uzenet "privat" and "csoport" (a plain id or {"chat_id": ...}), or
MARVEEN_OWNER_CHATS (comma-separated) when set; when no chat is known, every chat is gated (fail-closed, as
mea-culpa-reply-gate.py). A sub-agent's own bot writes to the same private chat id (a Telegram private chat id is
the user's id), so Patrik's DM with any bot is covered. A malformed payload is allowed (nothing to read).
Wiring: templates/settings.json.template PreToolUse, matcher "mcp__plugin_telegram_telegram__(reply|edit_message)"
(every seeded agent; ensureAgentHooks merges it at dashboard boot). No chat id is written in this file.
Tests: session-meta-reply-gate_test.py next to this file.
"""
import json
import os
import re
import sys
import unicodedata

ROOT = os.environ.get('CLAUDE_PROJECT_DIR', '/Users/klodel/marveen')
STORE = os.path.join(ROOT, 'store')

ZERO_WIDTH = dict.fromkeys(map(ord, '​‌‍⁠﻿­'))

# Written without accents: the text is accent-folded before matching. Only the agent's OWN session: first person or
# a possessive ("kontextusom", "újraindultam"). A report about ANOTHER agent's restart that Patrik asked for passes
# ("Klodel 20:54-kor újraindult (context restart)", "az új session ugyanúgy elhasalt": 4 of Dave's 90 hits in the
# replay below were such answers, the other 86 were "friss kontextussal folytatom").
OWN = r'(sessionom\w*|sessionjem\w*|munkamenetem\w*|kontextusom\w*|kontextusunk\w*)'
RESTART = r'(restart\w*|ujraindul\w*|ujrainditott\w*|ujrainditas\w*|ujrainditva|megtel\w*|betel\w*|tele\b|tul nagy|' \
          r'elfogy\w*|nullaz\w*|tomorit\w*)'
NEAR = r'\W+(?:\w+\W+){0,4}'
# Viktor 41381 LOW 1: "handoff", "context-guard" and "fresh context" are also ordinary words (Patrik asks where the
# HANDOFF.md is, who wrote the context-guard rule, what "fresh context" means in prompting); they block only next to
# the agent's own state verb (first or third person, or "restarted me"), within four words either way.
# The replay also has the third-person self-report ("Dave friss kontextussal folytatja / megy tovább").
FIRST = r'(vagyok|folytat\w*|indultam|ujraindultam|visszajottem|jottem vissza|dolgozom|dolgozik|kezdem|kezdtem|kezdi|' \
        r'beolvastam|viszem|megyek|megy|tovabb|i\'?m|i am|back|resum\w*|picking up|continu\w*|starting)'
GUARD_ACT = r'(' + FIRST[1:-1] + r'|ujrainditott\w*|leallitott|megallitott|restart\w*)'


def both(a, b):
    return r'\b(?:' + a + r'\w*' + NEAR + b + r'\b|' + b + NEAR + a + r')'


PHRASES = [
    ('friss kontextus', both(r'friss kontextus', FIRST)),
    ('fresh context', both(r'(?:fresh|new) (?:context|session)', FIRST)),
    ('handoff', both(r'(?:auto ?)?handoff', FIRST)),
    ('context-guard', both(r'context ?guard', GUARD_ACT)),
    ('saját kontextus/session', r'\b' + OWN + NEAR + RESTART),
    ('újraindítás + saját', r'\b' + RESTART + NEAR + OWN),
    ('új sessionben vagyok', r'\buj (session|munkamenet)\w*\W+(?:\w+\W+){0,2}(vagyok|folytatom|indultam)\b'),
    ('my context', r'\bmy (context|session)\b'),
    ('folytatom a megkezdett', r'\b(folytatom|folytatva|folytatjuk)\b' + NEAR + r'megkezdett\b'),
    ('újraindultam', r'\b(ujraindultam|ujrainditottak|ujrainditottam magam|restartoltak|i was restarted|restarted me)\b'),
    ('resumed after restart', r'\bresum\w*\W+(?:\w+\W+){0,3}(after|from)\W+(?:\w+\W+){0,2}restart\w*'),
]
COMPILED = [(label, re.compile(rx)) for label, rx in PHRASES]


def norm(text):
    text = unicodedata.normalize('NFKC', str(text)).translate(ZERO_WIDTH).replace('-', ' ').replace('_', ' ')
    text = ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))
    return ' '.join(text.split()).casefold()


def owner_chats():
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


def hits(text):
    plain = norm(text)
    return [label for label, rx in COMPILED if rx.search(plain)]


def main():
    try:
        payload = json.load(sys.stdin)
        ti = payload.get('tool_input') or {}
        text = ti.get('text')
        chat = ti.get('chat_id')
    except Exception:
        return 0
    if not isinstance(text, str) or not text.strip():
        return 0
    chats = owner_chats()
    if chats and str(chat).strip() not in chats:
        return 0
    found = hits(text)
    if not found:
        return 0
    print(
        f'SESSION-META-KAPU: a saját session állapota ({found[0]}) nem megy Patrik csatornájára. Patrik TG 666: '
        '"miért irogatod ezt ide mindig??? soha többé nem akarom". A restart/handoff/kontextus a transzkriptbe '
        'tartozik; ha ez Patriknak szóló tartalom, írd meg session-meta nélkül.',
        file=sys.stderr,
    )
    return 2


if __name__ == '__main__':
    try:
        rc = main()
    except Exception as ex:  # fail OPEN on an internal error, recorded in store/hook-errors.log
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import hook_errlog
            hook_errlog.report('session-meta-reply-gate', 'internal error, allowed', ex)
        except Exception:
            pass
        rc = 0
    sys.exit(rc)
