#!/usr/bin/env python3
"""PreToolUse gate (telegram reply + edit_message): no mea-culpa replies to Patrik.

Why: Patrik group TG 3795 (2026-11-09 14:32): "a minőség azon múlik h azt csinálod-e amit kérek vagy utólag írogatsz
minden 5 percben: igazad van az én hibám volt, látnom kellett volna, ki kellett volna szúrnom blabla". During one
afternoon the main agent sent six or seven such replies in half an hour. The rule is the main agent's memory
no-mea-culpa-replies: one short line about the next result, then only the result. Klodel 34240 asked for a gate.

What blocks (exit 2, a one-line message): a reply or an edit to the owner's private chat or the team group whose text
contains one of the phrases in PHRASES ("igazad van", "jogos", "hibáztam", "az én hibám", "ki kellett volna szúrnom",
"ezentúl", and their plural / obvious word-order forms). Matching is case-insensitive, over normalised text: NFKC,
zero-width characters dropped, accents folded (Patrik writes without accents, so "hibaztam" counts too), "-" and "_"
read as a space, whitespace collapsed. Whole words only: "jogosultság" does not match "jogos" ("jogosan" does: it is
the same concession, listed on its own).

Which chats are gated: store/projektek.json elo_uzenet "privat" and "csoport" (each a plain id or {"chat_id": ...}),
or MARVEEN_OWNER_CHATS (comma-separated) when set. When no chat is known, every chat is gated (fail-closed: this bot
writes to Patrik's chats). A malformed hook payload is allowed (nothing to read).
Wiring: .claude/settings.json PreToolUse, matcher "mcp__plugin_telegram_telegram__reply|...__edit_message" (the main
agent's settings; the sub-agents have their own). No chat id is written in this file: the ids are personal data.
Tests: mea-culpa-reply-gate_test.py next to this file.

Two more checks in the same hook (Klodel 38198, hibanapló 2026-11-11 17:02: an edit_message with the text
"PLACEHOLDER" went out to the live status message of the team group):
- PLACEHOLDER-KAPU, in EVERY chat: the text is a placeholder. Blocks a whole-word upper-case PLACEHOLDER anywhere,
  "lorem ipsum" anywhere, a template variable {{...}}, a line that is only PLACEHOLDER / TODO / TBD / XXX (any case,
  punctuation around it allowed), a bracketed [TODO] / <TBD> / {XXX} / (PLACEHOLDER), and "...: TODO" / TBD / XXX at a
  line end (upper case). Prose that names the word passes ("3 TODO maradt a kódban", "a placeholder szót", "XXL").
  An edit_message whose whole text is shorter than 15 characters (after trimming) is blocked too.
- ELO-ALLAPOT-KAPU: an edit_message to the live status message (store/projektek.json elo_uzenet "csoport" or
  "privat", its chat_id AND message_id) must start with "📊 ÉLŐ ÁLLAPOT" (or "ÉLŐ ÁLLAPOT"), the head that
  ops/elo_allapot.py writes. When the store does not name the message, this check has nothing to compare and passes.
The edit is recognised by tool_name (...__edit_message), or, when the payload has no tool_name, by a message_id in
tool_input.
"""
import json
import os
import re
import sys
import unicodedata

ROOT = os.environ.get('CLAUDE_PROJECT_DIR', '/Users/klodel/marveen')
STORE = os.path.join(ROOT, 'store')

# Written without accents: the text is accent-folded before matching. Klodel 34240's list, plus the plural ("we")
# and the "kellett volna kiszúrnom" order of the same sentences.
PHRASES = [
    ('igazad van', r'\bigazad van\b'),
    ('igazatok van', r'\bigazatok van\b'),
    ('jogos', r'\bjogos(an)?\b'),
    ('hibáztam', r'\bhibaztam\b'),
    ('hibáztunk', r'\bhibaztunk\b'),
    ('az én hibám', r'\baz en hibam\b'),
    ('a mi hibánk', r'\ba mi hibank\b'),
    ('ki kellett volna szúrnom', r'\bki kellett volna szurn(om|unk|i)\b'),
    ('kellett volna kiszúrnom', r'\bkellett volna kiszurn(om|unk|i)\b'),
    ('ezentúl', r'\bezentul\b'),
]
COMPILED = [(label, re.compile(rx)) for label, rx in PHRASES]

ZERO_WIDTH = dict.fromkeys(map(ord, '​‌‍⁠﻿­'))


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


PLACEHOLDER_RX = [
    re.compile(r'\bPLACEHOLDER\b'),
    re.compile(r'lorem\s+ipsum', re.IGNORECASE),
    re.compile(r'\{\{[^{}\n]{0,80}\}\}'),
    re.compile(r'(?im)^[\W_]*(placeholder|todo|tbd|xxx)[\W_]*$'),
    re.compile(r'(?i)[\[<{(]\s*(placeholder|todo|tbd|xxx)\s*[\]>})]'),
    re.compile(r'(?m):\s*(TODO|TBD|XXX)[\W_]*$'),
]
EDIT_MIN_CHARS = 15
LIVE_HEAD = re.compile(r'^\s*(📊\s*)?ÉLŐ ÁLLAPOT')


def placeholder(text, is_edit):
    t = unicodedata.normalize('NFKC', str(text)).translate(ZERO_WIDTH)
    for rx in PLACEHOLDER_RX:
        m = rx.search(t)
        if m:
            return m.group(0).strip()[:30]
    if is_edit and len(t.strip()) < EDIT_MIN_CHARS:
        return f'{len(t.strip())} karakteres szerkesztés'
    return None


def live_messages():
    """(chat_id, message_id) of the live status messages named in store/projektek.json elo_uzenet."""
    try:
        with open(os.path.join(STORE, 'projektek.json'), encoding='utf-8') as f:
            elo = json.load(f).get('elo_uzenet')
    except Exception:
        return set()
    out = set()
    for key in ('privat', 'csoport'):
        v = elo.get(key) if isinstance(elo, dict) else None
        if isinstance(v, dict) and v.get('chat_id') is not None and v.get('message_id') is not None:
            out.add((str(v['chat_id']).strip(), str(v['message_id']).strip()))
    return out


def hits(text):
    plain = norm(text)
    return [label for label, rx in COMPILED if rx.search(plain)]


def main():
    try:
        payload = json.load(sys.stdin)
        ti = payload.get('tool_input') or {}
    except Exception:
        return 0
    if not isinstance(ti, dict):
        return 0
    tool = str(payload.get('tool_name') or '')
    is_edit = tool.endswith('edit_message') if tool else 'message_id' in ti
    text = ti.get('text') if isinstance(ti.get('text'), str) else ''
    ph = placeholder(text, is_edit)
    if ph:
        sys.stderr.write(f'PLACEHOLDER-KAPU (Klodel 38198, hibanapló 11-11 17:02): helyőrző szöveg nem megy ki ("{ph}"). '
                         'Írd meg a valódi szöveget, vagy ne küldd el.\n')
        return 2
    target = (str(ti.get('chat_id') or '').strip(), str(ti.get('message_id') or '').strip())
    if is_edit and target in live_messages() and not LIVE_HEAD.match(unicodedata.normalize('NFC', text)):
        sys.stderr.write('ELO-ALLAPOT-KAPU (Klodel 38198): az élő állapot-üzenetet csak "📊 ÉLŐ ÁLLAPOT" kezdetű '
                         'szöveg írhatja felül (ops/elo_allapot.py kimenete).\n')
        return 2
    chats = owner_chats()
    if chats and str(ti.get('chat_id') or '').strip() not in chats:
        return 0
    found = hits(text)
    if found:
        sys.stderr.write(
            f'MEA-CULPA-KAPU: {", ".join(found)} - Patriknak nincs "igazad van / hibáztam / ezentúl" válasz (TG 3795, '
            'memória no-mea-culpa-replies): egy sor a következő eredményről, utána csak az eredmény.\n')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
