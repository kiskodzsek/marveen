#!/usr/bin/env python3
"""PreToolUse gate (telegram reply): the main agent's summaries to Patrik are plain sentences, not machine output.

Why: retro 2026-11-13 R9 (card dddca664). shared/hibanaplo.md L185 (2026-11-10): the evening decision summary
(D20261110-1800) went out with the signal block word for word, with "┆" detail lines; Patrik TG 4735: "ilyen szar
olvashatatlan üzenetet ne adj, mintha kódot kéne olvasnom" (second time; first 10-13: "átláthatatlan"). The rule
lives in the scheduled task text (~/.claude/scheduled-tasks/dontes-osszesito-este/SKILL.md: at most 5 numbered
points, each one plain Hungarian sentence, no detail lines, file paths, code names) and the motor refuses a "┆"
line in its own output (ops/decisions/dontes_motor.py, EGYSORJELZES1110); nothing checked the text Klodel actually
sends. The length is already gated for every main-agent reply to Patrik's chats (patrik-reply-volume-gate.py:
max 6 lines / 600 characters); this gate adds the form.

What blocks (exit 2, one Hungarian line), only for the MAIN agent's reply into one of the owner's chats
(store/projektek.json elo_uzenet "privat" / "csoport", or MARVEEN_OWNER_CHATS):
  - any reply: a "┆" (or "¦") detail line -- it is always pasted machine output;
  - a SUMMARY: a first line that names one ("Mai eredmény", "Napi eredmény", "Döntés-összesítő", "Döntések",
    "Esti összesítő", ...), or two numbered points plus an answer template ("1 mehet", "2 nem", "1 igen");
    in a summary:
      1. a file path (shared/..., store/..., /Users/..., x.md, x.py, ...) or a backtick;
      2. a card id (8 hex characters with a letter and a digit), a summary id (D20261110-1800) or a code name
         (EGYSORJELZES1110);
      3. more than 5 numbered points;
      4. a point that runs on into an indented detail line;
      5. a point longer than MAX_POINT characters.
Sources stay ("Mira 41233", "TG 6033", "#1298"): the claim-source gate asks for them.
Anything unreadable (bad payload, other agent, other tool, other chat) passes; an internal error fails open with a
line in store/hook-errors.log.
Wiring: .claude/settings.json PreToolUse, next to patrik-reply-volume-gate.py under the reply|edit_message matcher
(main agent only). Only reply is checked, on purpose (Viktor 41446 INFO 2): a summary goes out as a reply, and
edit_message is the live status message edited in place, which the volume gate leaves alone for the same reason.
Tests: summary-form-reply-gate_test.py next to this file.
"""
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
STORE = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'store')

MAX_POINTS = 5
MAX_POINT = 220

DETAIL_RX = re.compile(r'^\s*[┆¦]', re.M)
NUMBERED_RX = re.compile(r'^\s*(\d{1,2})[.)]\s+\S')
ITEM_RX = re.compile(r'^\s*(?:\d{1,2}[.)]|[-•*])\s+\S')
# folded (no accents, lower case) first line of a summary
HEADER_RX = re.compile(r'^\W*(?:(?:mai|napi|esti|heti|reggeli)\s+)?(?:eredmeny|osszesito|osszefoglalo|'
                       r'dontes[ -]?osszesito|dontesek)\b|^\W*mai nap\b')
# an answer template: two numbered answers on one line ("1 mehet, 2 nem", "pl. 1 igen 2 holnap")
_ANS = r'\d{1,2}\s*[:=-]?\s*(?:mehet|igen|nem|holnap|kesz)\b'
ANSWER_RX = re.compile(r'\b' + _ANS + r'[^\n]{0,40}?\b' + _ANS)
PATH_RX = re.compile(r'(?:/Users/|~/|(?<![\w.])(?:shared|store|scripts|ops|src|agents|docs|templates)/[\w.-])'
                     r'|\b[\w-]+\.(?:md|py|json|tsx?|sh|mjs|txt|ya?ml|sql)\b')
CODE_RX = re.compile(r'\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{8}\b'   # card id
                     r'|\bD\d{8}-\d{4}\b'                                 # summary id
                     r'|\b[A-ZÁÉÍÓÖŐÚÜŰ]{4,}\d{3,}\b')                     # code name (EGYSORJELZES1110)


def fold(text):
    t = unicodedata.normalize('NFKD', unicodedata.normalize('NFKC', str(text)))
    return ''.join(c for c in t if not unicodedata.combining(c)).lower()


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


def is_summary(text):
    lines = [ln for ln in str(text).splitlines() if ln.strip()]
    if not lines:
        return False
    if HEADER_RX.search(fold(lines[0])):
        return True
    numbered = sum(1 for ln in lines if NUMBERED_RX.match(ln))
    return numbered >= 2 and bool(ANSWER_RX.search(fold(text)))


def check(text):
    """Pure decision: the block message, or None."""
    text = str(text or '')
    head = 'ÖSSZESÍTŐ-KAPU (Patrik TG 4735: "ilyen szar olvashatatlan üzenetet ne adj, mintha kódot kéne olvasnom"): '
    if DETAIL_RX.search(text):
        return head + 'részletsor (┆) nem mehet ki; minden tétel egy sima mondat, a részlet a kártyán marad.'
    if not is_summary(text):
        return None
    m = PATH_RX.search(text)
    if m or '`' in text:
        what = m.group(0) if m else 'backtick'
        return head + f'fájlút vagy kód ({what}) nincs az összesítőben; írd le, mi az, egy mondatban.'
    m = CODE_RX.search(text)
    if m:
        return head + f'belső azonosító ({m.group(0)}) nincs az összesítőben; írd le, miről szól.'
    lines = text.splitlines()
    points = [ln for ln in lines if NUMBERED_RX.match(ln)]
    if len(points) > MAX_POINTS:
        return head + f'legfeljebb {MAX_POINTS} számozott pont (most {len(points)}); a többi a következő összesítőbe megy.'
    in_item = False
    for ln in lines:
        if not ln.strip():
            in_item = False
            continue
        if ITEM_RX.match(ln):
            in_item = True
            if len(ln.strip()) > MAX_POINT:
                return head + (f'egy pont legfeljebb {MAX_POINT} karakter (most {len(ln.strip())}): '
                               f'"{ln.strip()[:60]}..."; egy pont = egy rövid mondat.')
            continue
        if in_item and ln[:1] in (' ', '\t'):
            return head + f'a pont részletsorral folytatódik ("{ln.strip()[:60]}"); egy pont = egy sor.'
    return None


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
    if not isinstance(ti, dict) or not ti.get('chat_id') or not isinstance(ti.get('text'), str):
        return 0
    if str(ti['chat_id']).strip() not in owner_chats():
        return 0
    try:
        import ledger_lib
        agent_id = ledger_lib.agent_id_from_payload(payload) or ledger_lib.main_agent_id()
        if agent_id != ledger_lib.main_agent_id():
            return 0
    except Exception as ex:  # Viktor 41446 INFO 4: a broken identity check must not switch the gate off silently
        try:
            import hook_errlog
            hook_errlog.report('summary-form-reply-gate', 'agent identity unreadable, allowed', ex)
        except Exception:
            pass
        return 0
    msg = check(ti['text'])
    if msg:
        print(msg, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    try:
        rc = main()
    except Exception as ex:  # fail OPEN on an internal error, recorded in store/hook-errors.log
        try:
            import hook_errlog
            hook_errlog.report('summary-form-reply-gate', 'internal error, allowed', ex)
        except Exception:
            pass
        rc = 0
    sys.exit(rc)
