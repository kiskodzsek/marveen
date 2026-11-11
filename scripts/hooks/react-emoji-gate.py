#!/usr/bin/env python3
"""PreToolUse gate (telegram react): in Patrik's chats only 👍 👀 ❤ as a reaction (no laughing or grinning).

Why: Klodel 38093, hibanapló 2026-11-11 16:05. The main agent put a 😁 reaction on Balázs's jokes in the team group,
and Patrik answered in group TG 5436: "faszt vigyorogsz". A memory note alone is not a fix (UGYANAZ A HIBA KÉTSZER NEM).

What blocks (exit 2, a one-line message): in the owner's private chat or the team group, every react emoji that is not
in ALLOW (👍 👀 ❤). An allowlist, not a blocklist (Viktor 38120 L1: 😏 😎 🥲 🤭 😸 passed the first, LAUGH-only
version; Klodel 38093: "👍 👀 ❤ mehet"). The emoji is compared after NFC and with the variation selectors
(U+FE0E/U+FE0F), zero-width and bidi marks, the soft hyphen and the skin-tone modifiers dropped, so "❤️" is ❤ and
"😁️" is still not allowed. An empty emoji (no reaction) passes.

Which chats are gated: store/projektek.json elo_uzenet "privat" and "csoport" (each a plain id or {"chat_id": ...}),
or MARVEEN_OWNER_CHATS (comma-separated) when set; the same lookup as mea-culpa-reply-gate.py. When no chat is known,
every chat is gated (fail closed); a call without a chat_id is gated too (Viktor 38120 INFO). A malformed hook payload
is allowed (nothing to read).
Wiring: .claude/settings.json PreToolUse, matcher "mcp__plugin_telegram_telegram__react". No chat id is written in
this file: the ids are personal data. Tests: react-emoji-gate_test.py next to this file.
"""
import json
import os
import sys
import unicodedata

ROOT = os.environ.get('CLAUDE_PROJECT_DIR', '/Users/klodel/marveen')
STORE = os.path.join(ROOT, 'store')

ALLOW = {'👍', '👀', '❤'}
DROP = dict.fromkeys([0xFE0E, 0xFE0F, 0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD, 0x200E, 0x200F,
                      *range(0x202A, 0x202F), *range(0x2066, 0x206A), *range(0x1F3FB, 0x1F400)])


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


def allowed(emoji):
    e = unicodedata.normalize('NFC', str(emoji or '')).translate(DROP).strip()
    return e == '' or e in ALLOW


def main():
    try:
        ti = json.load(sys.stdin).get('tool_input') or {}
    except Exception:
        return 0
    if not isinstance(ti, dict):
        return 0
    chats = owner_chats()
    chat = str(ti.get('chat_id') or '').strip()
    if chats and chat and chat not in chats:
        return 0
    if not allowed(ti.get('emoji')):
        sys.stderr.write('REAKCIÓ-KAPU (Patrik csoport TG 5436: "faszt vigyorogsz", Klodel 38093): Patrik chatjeiben csak '
                         '👍, 👀 vagy ❤ reakció mehet, vagy semmi.\n')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
