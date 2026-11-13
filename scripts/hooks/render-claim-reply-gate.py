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

Ready-time claims (Klodel 40023, hibanapló 2026-11-13 11:08, Patrik TG 5709): Dave's estimate ("11:45") was passed on
to Patrik as a ready time; the measured run took 2 minutes. A REPLY (not edit_message: the live status card is its own
surface) whose text gives a ready time for render / image / video work, "HH:MM körül / -ra kész", "X óra / perc
(múlva) kész", "becslés ... szerint", passes only with a line
    MÉRVE: <time per piece> (<file or mtime>)        e.g.  MÉRVE: 2 perc/darab (out/papas-v3.mp4, mtime 11:43)
i.e. a number with a time unit, and in parentheses a path, a file name or "mtime". Without it the block ends
"mérd meg a darabidőt; ha nincs mérés: 'szólok, ha kész'".

Conditional video work (Klodel 40261, hibanapló 2026-11-13 13:16, Patrik csoport TG 5790/5793 "jojjon mar a video" /
"Ezert alltatok egesz eddig"): at 12:39 the reply "... Cseréljük? ... A te igened után 12 perc, és küldöm." asked
Patrik a question about the reel and parked the v10c export on his answer until 13:15. A REPLY whose text names video
work (render, export, film, videó, reel, klip, mp4, animáció) AND, in one sentence, ties a delivery or a start to the
owner's answer ("igened után ... küldöm", "ha mehet, indul", "jóváhagyásod után áll össze") passes only with a line
    RENDER: fut <pid>            the pid is an export ops/video_export_status.py lists right now (measured at send)
    RENDER: nem-kell <indok>     at least 10 characters why no render has to run (e.g. a question about a finished film)
i.e. the render runs while the question waits, or the text says why it does not have to. Else the block ends
"indítsd el most, a kérdés közben fusson; vagy 'RENDER: nem-kell <indok>'".

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
# Ready-time claims (Klodel 40023). Judged per sentence: the sentence names render / image / video work AND promises
# a FUTURE ready time. Past forms ("elkészült", "kész volt", "14:17-re elkészült") and log stamps ("21:38, ...") are not
# promises. Measured on 7 days of real owner-chat replies before narrowing: 57 hits, mostly past tense and stamps.
READY_CONTEXT = re.compile(r'\b(?:render\w*|export\w*|video\w*|film\w*|kep(?:ek|et|eket|ei|eit|ekkel)?|rajz\w*|'
                           r'illusztraci\w*|jelenet\w*|mp4|klip\w*|reel\w*|animaci\w*|felvetel\w*)\b')
_CLOCK = r'\b(?:[01]?\d|2[0-3])[:.][0-5]\d\b'
_DUR = r'\b\d+(?:[.,]\d+)? ?(?:ora|perc|mp|masodperc)\w*'
# "kész" as a promise: "kész lesz", "kész", "készen lesz", "elkészül(nek)" -- never "elkészült", "kész volt/lett".
_READY = r'\b(?:kesz(?:ek|en)?\b(?! ?(?:volt|lett|vannak|van))|elkeszul(?:nek)?\b(?!t)|megvan(?:nak)?\b(?! ?mar))'
READY_CLAIMS = [
    re.compile(_CLOCK + r' ?(?:korul|kor|ra|re|tajan|fele|ig)\b.{0,30}' + _READY),
    re.compile(_READY + r'.{0,20}\blesz\w*\b.{0,20}' + _CLOCK + r' ?(?:korul|kor|ra|re|tajan|fele|ig)?\b'),
    re.compile(_DUR + r' ?mulva\b.{0,30}' + _READY),
    re.compile(_READY + r'.{0,30}' + _DUR + r' ?mulva\b'),
    re.compile(r'\bbecsles\w*\b.{0,60}\bszerint\b.{0,60}(?:' + _READY + r'|\blesz\b|' + _CLOCK + r')'),
]
SENTENCE_SPLIT = re.compile(r'(?<![Kk]b\.)(?<![Pp]l\.)(?<!ill\.)(?<!stb\.)(?<!kb\.)(?<=[.!?])\s+|\n+')
MERVE_LINE = re.compile(r'(?mi)^[ \t]*(?:[-*>][ \t]*)?m[ée]rve:[ \t]*(?P<body>[^\n]+)$')
MERVE_DURATION = re.compile(r'\d+(?:[.,]\d+)?[ \t]*(?:mp|s|sec|perc|p|min|ora|óra|h)\b', re.I)
MERVE_SOURCE = re.compile(r'\([^)]*(?:/|\.\w{2,4}\b|mtime)[^)]*\)', re.I)
READY_HINT = "mérd meg a darabidőt; ha nincs mérés: 'szólok, ha kész'"
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


def ready_claims(text):
    for sentence in SENTENCE_SPLIT.split(str(text)):
        plain = norm(sentence)
        if READY_CONTEXT.search(plain) and any(rx.search(plain) for rx in READY_CLAIMS):
            return True
    return False


def has_merve(text):
    """A 'MÉRVE: <time per piece> (<file or mtime>)' line (read on the raw text: the line structure matters)."""
    for m in MERVE_LINE.finditer(str(text)):
        body = m.group('body')
        if MERVE_DURATION.search(body) and MERVE_SOURCE.search(body):
            return True
    return False


# Conditional video work (Klodel 40261). Context: video words only, not images (a drawing has its own rule above).
COND_CONTEXT = re.compile(r'\b(?:render\w*|export\w*|video\w*|film\w*|reel\w*|klip\w*|mp4|animaci\w*)\b')
# A condition on the owner's answer that a delivery or a start waits for, in ONE sentence ("A te igened után 12 perc,
# és küldöm."). A bare question is not enough: replayed on 7 days of real owner-chat replies (2026-11-06..13, 2303
# texts), "video word + any '?'" hit 78, nearly all unrelated; this shape hits 6, the 12:39 one among them.
COND_WAIT = re.compile(r'\b(?:igened(?:re)? utan|igenedre|ha mehet|ha oke|ha okes|ha igen|ha jovahagyod|jovahagyasod utan|'
                       r'jovahagyas(?:od)? utan|ha rabolintasz|rabolintasod utan|valaszod utan|dontesed utan|amint ramondod|'
                       r'ha ramondod)\b')
COND_DELIVER = re.compile(r'\b(?:kuldom|kuldjuk|megy|indul\w*|inditom|inditjuk|exportal\w*|renderel\w*|keszul\w*|'
                          r'keszitem|kesz|all ossze|osszeall\w*)\b')
RENDER_LINE = re.compile(r'(?mi)^[ \t]*(?:[-*>][ \t]*)?render:[ \t]*(?:fut[ \t]+(?P<pid>\d+)\b|nem-kell[ \t]+(?P<why>[^\n]*))')
COND_HINT = "indítsd el most, a kérdés közben fusson; vagy 'RENDER: nem-kell <indok>'"


def running_export_pids():
    """The pids <install>/ops/video_export_status.py lists as exports right now (ops/ is install-local, not in git).
    Empty when it is missing or fails: then only 'RENDER: nem-kell' lets the text go."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('video_export_status', os.path.join(ROOT, 'ops', 'video_export_status.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return {str(r[0]) for r in mod.exports()}
    except Exception:
        return set()


def conditional_claims(text):
    if not COND_CONTEXT.search(norm(text)):
        return False
    for sentence in SENTENCE_SPLIT.split(str(text)):
        plain = norm(sentence)
        if COND_WAIT.search(plain) and COND_DELIVER.search(plain):
            return True
    return False


def conditional_problem(text, pids=None):
    """None when the text may go, else (reason, hint). pids: the running export pids (measured when None)."""
    if not conditional_claims(text):
        return None
    for m in RENDER_LINE.finditer(str(text)):
        if m.group('why') is not None and len(m.group('why').strip()) >= 10:
            return None
        if m.group('pid'):
            live = running_export_pids() if pids is None else pids
            if m.group('pid') in live:
                return None
            return (f'RENDER: fut {m.group("pid")}, de a video_export_status szerint ez a pid most nem export', COND_HINT)
    return ('videó-munka Patrik válaszára vár ("igened után ... küldöm"), és nincs mért "RENDER: fut <pid>" sor '
            '(TG 5793: "Ezert alltatok egesz eddig")', COND_HINT)


def ready_problem(text):
    """None when the text may go, else (reason, hint)."""
    if not ready_claims(text) or has_merve(text):
        return None
    return ('kész-időpont a render/kép/videó munkára mért darabidő nélkül (becslés továbbadása, TG 5709)', READY_HINT)


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
        payload = json.load(sys.stdin)
        ti = payload.get('tool_input') or {}
        payload_tool = payload.get('tool_name') or ''
    except Exception:
        return 0
    if not isinstance(ti, dict):
        return 0
    chats = owner_chats()
    if chats and str(ti.get('chat_id') or '').strip() not in chats:
        return 0
    text = ti.get('text') or ''
    got = problem(text)
    if got:
        why, hint = got
        sys.stderr.write(f'RENDER-ÁLLAPOT-KAPU (Klodel 35696/35719, TG 4381/4424): {why} - {hint}\n')
        return 2
    if not str(payload_tool).endswith('edit_message'):
        got = ready_problem(text)
        if got:
            why, hint = got
            sys.stderr.write(f'KÉSZ-IDŐPONT-KAPU (Klodel 40023, TG 5709): {why} - {hint}\n')
            return 2
        got = conditional_problem(text)
        if got:
            why, hint = got
            sys.stderr.write(f'FELTÉTELES-RENDER-KAPU (Klodel 40261, TG 5790/5793): {why} - {hint}\n')
            return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
