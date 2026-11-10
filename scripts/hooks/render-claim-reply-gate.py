#!/usr/bin/env python3
"""PreToolUse gate (telegram reply + edit_message): a render-state claim to Patrik only on a fresh measurement.

Why: Klodel 35696 (2026-11-10), the second time the same mistake reached Patrik. 09:06: "a babás most renderel a
minin, a papás a MacBookon készül", while the target file had not been written for 12 minutes and the second film was
still a drawing (Patrik TG 4381: "látom h nem renderel ne hazudj"). The first time was the v9 (TG 1856), after which
ops/video_export_status.py was written; the rule "only from its output" lived in memory and did not hold.

What blocks (exit 2, one line ending "mérd meg; tervnél: 'Dave indítja'"): a reply or an edit to the owner's private
chat or the team group whose text claims a render is in progress ("renderel", "exportál", "fut a render", "készül a
minin / MacBookon / gépen", and their plain inflections), unless
  1. ops/video_export_status.py ran at most MAX_AGE_S ago (its store/video-export-status.json, render_claim_lib), and
  2. an output it listed was written at most MAX_AGE_S ago, measured now (a file's mtime; a frames directory's newest
     entry); when the text names a video file (x.mp4), that file must be one of those fresh outputs.
A claim about the MacBook is always blocked: this machine cannot measure it (ask Dave for the measured file and time).
Past or planned forms ("renderelt", "a renderelés kész", "Dave indítja") are not claims.

Matching: NFKC, zero-width characters dropped, accents folded, case-insensitive, whole words. Which chats are gated:
as mea-culpa-reply-gate.py (store/projektek.json elo_uzenet privat / csoport, or MARVEEN_OWNER_CHATS; none known =
every chat). A malformed payload is allowed (nothing to read).
Wiring: .claude/settings.json PreToolUse, matcher "mcp__plugin_telegram_telegram__reply|...__edit_message".
Tests: render-claim-reply-gate_test.py next to this file.
"""
import json
import os
import re
import sys
import time
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_claim_lib import newest_write, read_stamp  # noqa: E402

ROOT = os.environ.get('CLAUDE_PROJECT_DIR', '/Users/klodel/marveen')
STORE = os.path.join(ROOT, 'store')
MAX_AGE_S = 120

MACHINES = r'(?:minin|minire|macbookon|macbookra|gepen)'
CLAIMS = [
    re.compile(r'\brenderel(?:ek|unk|nek|odik|odnek)?\b'),
    re.compile(r'\bexportal(?:ok|unk|nak|odik|odnak)?\b'),
    re.compile(r'\bfut(?:nak)? (?:a|az) (?:render|export)\w*'),
    re.compile(r'\b(?:render|export)\w* (?:most |meg )?fut(?:nak)?\b'),
    re.compile(r'\bkeszul\w*\b.{0,30}\b' + MACHINES + r'\b'),
    re.compile(r'\b' + MACHINES + r'\b.{0,30}\bkeszul\w*'),
]
VIDEO = re.compile(r'([\w.\-]+\.(?:mp4|mov|webm|mkv))\b', re.I)
ZERO_WIDTH = dict.fromkeys(map(ord, '​‌‍⁠﻿­'))
HINT = "mérd meg; tervnél: 'Dave indítja'"


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


def claims(text):
    plain = norm(text)
    return any(rx.search(plain) for rx in CLAIMS)


def problem(text, now=None):
    """None when the text may go, else the reason (without the hint)."""
    if not claims(text):
        return None
    now = time.time() if now is None else now
    if 'macbook' in norm(text):
        return 'a MacBookot ez a gép nem méri: Dave mért fájlja és ideje kell, nem állapot'
    ran, outputs = read_stamp(ROOT)
    if ran is None or now - ran > MAX_AGE_S:
        return f'render-állapot mérés nélkül (ops/video_export_status.py {MAX_AGE_S // 60} percen belül nem futott)'
    fresh = set()
    for o in outputs:
        w = newest_write(o)
        if w is not None and now - w <= MAX_AGE_S:
            fresh.add(os.path.basename(os.path.normpath(o)))
    named = {m.group(1) for m in VIDEO.finditer(str(text))}
    if named:
        missing = sorted(n for n in named if n not in fresh)
        if missing:
            return f'{", ".join(missing)}: nem íródott {MAX_AGE_S // 60} percen belül (vagy nem fut rá export)'
        return None
    if not fresh:
        return f'egyik futó export kimenete sem íródott {MAX_AGE_S // 60} percen belül'
    return None


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
    why = problem(ti.get('text') or '')
    if why:
        sys.stderr.write(f'RENDER-ÁLLAPOT-KAPU (Klodel 35696, TG 4381): {why} - {HINT}\n')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
