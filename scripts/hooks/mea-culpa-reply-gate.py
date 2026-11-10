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


def hits(text):
    plain = norm(text)
    return [label for label, rx in COMPILED if rx.search(plain)]


def main():
    try:
        ti = json.load(sys.stdin).get('tool_input') or {}
    except Exception:
        return 0
    if not isinstance(ti, dict):
        return 0
    chats = owner_chats()
    if chats and str(ti.get('chat_id') or '').strip() not in chats:
        return 0
    found = hits(ti.get('text') or '')
    if found:
        sys.stderr.write(
            f'MEA-CULPA-KAPU: {", ".join(found)} - Patriknak nincs "igazad van / hibáztam / ezentúl" válasz (TG 3795, '
            'memória no-mea-culpa-replies): egy sor a következő eredményről, utána csak az eredmény.\n')
        return 2
    return 0


if __name__ == '__main__':
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from gate_log import watch as _gate_log_watch  # one line per block, store/gate-blocks.jsonl (Klodel 35878)
    except Exception:
        from contextlib import nullcontext as _gate_log_watch
    with _gate_log_watch('mea-culpa'):
        sys.exit(main())
