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
Drawing / generation claims (Klodel 35719, the third case: 10:27, Patrik TG 4424, "a papás új rajzai most a háttérben
készülnek" while the order only waited in Dave's queue): "a háttérben készül(nek)", "rajzol(ja|ják|ódnak)",
"generál(ja|ódik|ódnak)", "készülnek a rajzok/képek" pass only when, measured at send time (ps + lsof, no stamp needed),
a fal-gen.mjs run/tts (not --dry), Blender or ffmpeg process runs AND one of its outputs (fal-gen: the job's out_dir)
was written at most MAX_AGE_S ago; else the block ends "mérd meg; tervnél: 'kiadtam Dave-nek'". A queued order is not
work. Known limit: a fal queue wait longer than MAX_AGE_S between two images blocks the claim (the safe direction).
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
from render_claim_lib import newest_write, read_stamp, running_generation_outputs  # noqa: E402

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
# Drawing / generation claims (Klodel 35719, Patrik TG 4424: "a papás új rajzai most a háttérben készülnek" while the
# order only waited in Dave's queue). Measured live: a fal-gen.mjs / Blender / ffmpeg process and its fresh output.
GEN_CLAIMS = [
    re.compile(r'\bhatterben\b.{0,30}\bkeszul(?:nek|ok|unk)?\b'),
    re.compile(r'\bkeszul(?:nek|ok|unk)?\b.{0,30}\bhatterben\b'),
    re.compile(r'\b(?:meg|at|ujra)?rajzol(?:ja|jak|om|juk|ok|unk|nak|odik|odnak)?\b'),
    re.compile(r'\b(?:le)?general(?:ja|jak|om|juk|ok|unk|nak|odik|odnak)?\b'),
    re.compile(r'\bkeszul(?:nek)?\b.{0,20}\b(?:rajz|kep|illusztraci|jelenet)\w*'),
    re.compile(r'\b(?:rajz|kep|illusztraci|jelenet)\w*\b.{0,30}\bkeszul(?:nek)?\b'),
]
VIDEO = re.compile(r'([\w.\-]+\.(?:mp4|mov|webm|mkv))\b', re.I)
ZERO_WIDTH = dict.fromkeys(map(ord, '​‌‍⁠﻿­'))
HINT = "mérd meg; tervnél: 'Dave indítja'"
GEN_HINT = "mérd meg; tervnél: 'kiadtam Dave-nek'"


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


def gen_claims(text):
    plain = norm(text)
    return any(rx.search(plain) for rx in GEN_CLAIMS)


def gen_problem(text, now, outputs):
    """A drawing / generation claim: a generation process runs now and one of its outputs was written <= MAX_AGE_S ago."""
    if not outputs:
        return 'rajz/generálás-állítás, de nem fut fal-gen.mjs / Blender / ffmpeg (sorban álló utasítás nem munka)'
    for o in outputs:
        w = newest_write(o)
        if w is not None and now - w <= MAX_AGE_S:
            return None
    return f'fut generálás, de a kimenete {MAX_AGE_S // 60} percen belül nem íródott'


def problem(text, now=None, gen_outputs=None):
    """None when the text may go, else (reason, hint). gen_outputs: the running generation outputs (measured live when
    None; the tests pass them)."""
    render, gen = claims(text), gen_claims(text)
    if not render and not gen:
        return None
    now = time.time() if now is None else now
    hint = HINT if render else GEN_HINT
    if 'macbook' in norm(text):
        return 'a MacBookot ez a gép nem méri: Dave mért fájlja és ideje kell, nem állapot', hint
    if render:
        why = render_problem(text, now)
        if why:
            return why, HINT
    if gen:
        why = gen_problem(text, now, running_generation_outputs() if gen_outputs is None else gen_outputs)
        if why:
            return why, GEN_HINT
    return None


def render_problem(text, now):
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
    got = problem(ti.get('text') or '')
    if got:
        why, hint = got
        sys.stderr.write(f'RENDER-ÁLLAPOT-KAPU (Klodel 35696/35719, TG 4381/4424): {why} - {hint}\n')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
