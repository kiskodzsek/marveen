#!/usr/bin/env python3
"""PreToolUse gate (telegram react): no laughing or grinning reaction in Patrik's chats.

Why: Klodel 38093, hibanapló 2026-11-11 16:05. The main agent put a 😁 reaction on Balázs's jokes in the team group,
and Patrik answered in group TG 5436: "faszt vigyorogsz". A memory note alone is not a fix (UGYANAZ A HIBA KÉTSZER NEM).

What blocks (exit 2, a one-line message): a react call whose emoji is in LAUGH (Klodel's list: 😁 🤣 😂 😆 😅 🤡, plus the
other grinning/laughing faces 😀 😃 😄 😹 🤪), in the owner's private chat or the team group. 👍 👀 ❤ and every emoji not in
LAUGH pass. The emoji is compared after NFC and with the variation selectors (U+FE0E/U+FE0F) and zero-width
characters dropped, so "😁️" is the same reaction.

Which chats are gated: store/projektek.json elo_uzenet "privat" and "csoport" (each a plain id or {"chat_id": ...}),
or MARVEEN_OWNER_CHATS (comma-separated) when set; the same lookup as mea-culpa-reply-gate.py. When no chat is known,
every chat is gated (fail closed). A malformed hook payload is allowed (nothing to read).
Wiring: .claude/settings.json PreToolUse, matcher "mcp__plugin_telegram_telegram__react". No chat id is written in
this file: the ids are personal data. Tests: react-emoji-gate_test.py next to this file.
"""
import json
import os
import sys
import unicodedata

ROOT = os.environ.get('CLAUDE_PROJECT_DIR', '/Users/klodel/marveen')
STORE = os.path.join(ROOT, 'store')

LAUGH = {'😁', '🤣', '😂', '😆', '😅', '🤡', '😀', '😃', '😄', '😹', '🤪'}
DROP = dict.fromkeys(map(ord, '︎️​‌‍⁠﻿'))


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


def laughing(emoji):
    e = unicodedata.normalize('NFC', str(emoji or '')).translate(DROP).strip()
    return e in LAUGH or any(c in LAUGH for c in e)


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
    if laughing(ti.get('emoji')):
        sys.stderr.write('REAKCIÓ-KAPU (Patrik csoport TG 5436: "faszt vigyorogsz", Klodel 38093): nevető/vigyorgó reakció '
                         'Patrik chatjeiben nem mehet. 👍, 👀 vagy ❤ mehet, vagy semmi.\n')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
