#!/usr/bin/env python3
"""PreToolUse gate (telegram reply + edit_message): a state claim or a number to Patrik only with its source.

Why: Klodel 35761, Patrik group TG 4477 "1 mehet" (audit shared/atvilagitas-1110/atvilagitas.md, chapter 4, item 3).
The audit counted 20 A-category errors in 6 days: a state or a number told to Patrik before it was measured ("kész",
"beállítottam", "fut", a price, a percentage). The rule ÁLLAPOT CSAK MÉRVE lived in memory and did not hold; the
render-claim gate stopped one verb, this one asks the same of every state claim: say where it comes from.

What blocks (exit 2, one line naming what was found): a reply or an edit to the owner's private chat or the team group
whose text makes a CLAIM and carries no SOURCE.
  CLAIM, in a sentence that is not a question: a state word (kész / elkészült / készen, beállítottam / beállítva,
  élesben / élesítve / élesítettem, fut / futnak, kint van, kiment) that is not negated or conditional just before
  ("nincs kész", "még nem fut", "ha kész", "amint kész") nor the consequent of a conditional ("Ha így van, kész.")
  nor future ("kész lesz"), or a number with a unit (%, Ft / forint / HUF, $ / USD / EUR / €, db, "N perc múlva").
  SOURCE, anywhere in the message: a "FORRÁS:" line, "mérve" / "mérés:" / "X mérte" / "mértem", "<X> szerint",
  "<X> jelzése", "forrással", "becslés (... szerint)", msg_id / msg 123,
  TG 1234, a PR (#123, PR 123), a file path (a/b.ext or /abs/path), a URL, a commit sha (7-40 hex with a digit and
  a letter), or an attached file (the reply's `files`: the result itself is the evidence).
Quoted text is not a claim of ours: «...», "...", „...", `...` are dropped before matching (Patrik's own words).
Every block is logged to store/claim-source-gate.log as one JSON line (time, chat kind, the claim labels, the text
length): never the text itself, it may hold personal data.

CLAIM_SOURCE_GATE_MODE=log (in the hook command) logs the would-be blocks and lets everything through: for a measuring
day before enforcing. Replay of 2026-11-08/10 (827 real replies to Patrik's chats): 78 would block (9.4 %).
Which chats are gated: as mea-culpa-reply-gate.py (store/projektek.json elo_uzenet privat / csoport, or
MARVEEN_OWNER_CHATS; none known = every chat). A malformed payload is allowed (nothing to read).
Wiring: .claude/settings.json PreToolUse, matcher "mcp__plugin_telegram_telegram__reply|...__edit_message".
Tests: claim-source-reply-gate_test.py next to this file (positive, negative, and the replay of a day's real replies).
"""
import json
import os
import re
import sys
import time
import unicodedata

ROOT = os.environ.get('CLAUDE_PROJECT_DIR', '/Users/klodel/marveen')
STORE = os.path.join(ROOT, 'store')
LOG = os.path.join(STORE, 'claim-source-gate.log')

ZERO_WIDTH = dict.fromkeys(map(ord, '​‌‍⁠﻿­'))
QUOTED = re.compile(r'«[^»]*»|"[^"\n]*"|„[^"”\n]*["”]|“[^”\n]*”|`[^`\n]*`')
# Not a claim: negated ("nincs kész"), conditional or future ("ha kész", "amint kész", "mire kész", "kész lesz").
NEG = (r'(?<!\bnincs )(?<!\bnem )(?<!\bsincs )(?<!\bsem )(?<!\bha )(?<!\bamint )(?<!\bmire )(?<!\bha mar )'
       r'(?<!\bamikor )(?<!\d )')  # "3 kész, posztolható videó": a count before it makes it attributive
FUT = r'(?! lesz\b)(?! lesznek\b)(?! leszek\b)'
STATE = [
    # "kész" as a predicate only ("kész a film", "a film kész.", "kész van", "készen vannak"); the attributive "kész
    # anyagot", "3 kész, posztolható videó" is not a state claim (replay 2026-11-08/10: 9 such false blocks).
    ('kész', NEG + r'(\bkesz(?=\s+(a|az|van|vannak|lett|lettek|vagyok|vagyunk)\b|\s*[.:!;)]|\s*$)'
             r'|\bkeszen\s+(van|vannak|all|allnak)\b|\belkeszult(ek)?\b)' + FUT),
    ('beállítva', NEG + r'\b(beallitottam|beallitottuk|beallitotta|beallitva)\b'),
    ('élesben', NEG + r'\b(elesben|elesitve|elesitettem|elesitettuk|elesitette)\b'),
    ('fut', NEG + r'\b(fut|futnak)\b'),
    ('kint van', NEG + r'\bkint van(nak)?\b'),
    ('kiment', NEG + r'\bkiment(ek)?\b'),
]
NUM = r'\d[\d  .,]*'
NUMBERS = [
    ('%', NUM + r'\s?%'),
    ('Ft', NUM + r'\s?(ft|forint|huf)\b'),
    ('$/EUR', r'(' + NUM + r'\s?(\$|usd\b|eur\b|€)|[$€]\s?\d)'),
    ('db', NUM + r'\s?db\b'),
    ('perc múlva', NUM + r'\s?perc(en belul| mulva)\b'),
]
CLAIMS = [(label, re.compile(rx)) for label, rx in STATE + NUMBERS]
SOURCES = [re.compile(rx) for rx in (
    r'(^|\n)\s*forras\s*:',
    r'\bmerve\b|\bmeres\s*:|\bmert(e|em|uk|ek|ed)\b|\bmeresevel\b|\belo(ben)? meres',
    r'\b\w+ szerint\b|\b\w+ jelzese\b|\bforrassal\b|\bforras\s*:',
    r'\bbecsles\s*\([^)]*szerint[^)]*\)',
    r'\bmsg[_ ]?(id)?[:= #]?\s?\d{3,}',
    r'\btg\s?\d{3,}',
    r'(^|\s)#\d{2,}\b|\bpr\s?#?\d{2,}\b',
    r'(^|[\s(])(/[\w.@-]+){2,}|\b[\w.-]+/[\w./-]*\.(md|py|ts|mjs|js|json|mp4|mov|png|jpg|jpeg|pdf|sh|txt|log|csv|html)\b',
    r'https?://\S+',
    r'\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b',
)]


def norm(text):
    text = unicodedata.normalize('NFKC', str(text)).translate(ZERO_WIDTH)
    text = ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))
    return text.casefold()


def sentences(text):
    """Split on . ! ? and newlines, keeping the end mark (a question is not a claim)."""
    return [s.strip() for s in re.findall(r'[^.!?\n]+[.!?]*', text) if s.strip()]


# A clause that is conditional ("ha tényleg fut, szólok", "amint a MacBookon fut") or negated ("élesben addig semmi
# nem változik") states nothing; nor does the idiom "..., és kész". Replay 2026-11-08/10 (828 replies): these were the
# false blocks left after the quote, question and attributive-"kész" rules.
COND = re.compile(r'^(ha|amint|amikor|mire|mielott|ahogy|hogy|ameddig|amig)\b')
# The consequent of a conditional ("Ha így van, kész.", Klodel 35878, 2026-11-10 12:0x: blocked as a claim) is as
# conditional as its condition: the clause right after a COND clause states nothing, nor does one opening "akkor".
# Only the next clause: "Ha kérdésed van, szólj, a film kész." still claims the film.
THEN = re.compile(r'^akkor\b')
NEGW = re.compile(r'\b(nem|nincs|sincs|semmi|sem|meg nem)\b')
IDIOM = re.compile(r'\bes kesz\s*[.!]?\s*$')


def claims(text):
    """The claim labels in the text, outside quotes, questions, conditional and negated clauses."""
    plain = QUOTED.sub(' ', norm(text))
    found = []
    for sent in sentences(plain):
        if sent.endswith('?'):
            continue
        after_cond = False
        for clause in re.split(r'[,;:\u2013\u2014]| - ', sent):
            clause = ' '.join(clause.split())
            if not clause:
                continue
            consequent, after_cond = after_cond, bool(COND.search(clause))
            if after_cond or consequent or THEN.search(clause) or NEGW.search(clause) or IDIOM.search(clause):
                continue
            for label, rx in CLAIMS:
                if label not in found and rx.search(clause):
                    found.append(label)
    return found


def has_source(text, files):
    if files:
        return True
    plain = norm(text)
    return any(rx.search(plain) for rx in SOURCES)


def owner_chats():
    env = os.environ.get('MARVEEN_OWNER_CHATS')
    if env:
        return {c.strip() for c in env.split(',') if c.strip()}
    try:
        with open(os.path.join(STORE, 'projektek.json'), encoding='utf-8') as f:
            elo = json.load(f).get('elo_uzenet')
    except Exception:
        return set()
    out = {}
    for key in ('privat', 'csoport'):
        v = elo.get(key) if isinstance(elo, dict) else None
        if isinstance(v, dict):
            v = v.get('chat_id')
        if v is not None and str(v).strip():
            out[str(v).strip()] = key
    return out


def log_block(kind, found, length):
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'at': int(time.time()), 'chat': kind, 'claims': found, 'len': length}) + '\n')
    except OSError:
        pass


def main():
    try:
        ti = json.load(sys.stdin).get('tool_input') or {}
    except Exception:
        return 0
    if not isinstance(ti, dict):
        return 0
    chats = owner_chats()
    chat = str(ti.get('chat_id') or '').strip()
    if chats and chat not in chats:
        return 0
    text = str(ti.get('text') or '')
    found = claims(text)
    if not found or has_source(text, ti.get('files') or []):
        return 0
    kind = chats.get(chat, '?') if isinstance(chats, dict) else '?'
    log_mode = os.environ.get('CLAIM_SOURCE_GATE_MODE') == 'log'
    log_block(kind + (' (log-only)' if log_mode else ''), found, len(text))
    if log_mode:  # a measuring day before enforcing: logged, let through
        return 0
    sys.stderr.write(
        f'ÁLLÍTÁS-FORRÁS-KAPU (Klodel 35761, ÁLLAPOT CSAK MÉRVE): {", ".join(found)} forrás nélkül. Írd mellé, honnan '
        'tudod: "FORRÁS: <fájl / msg_id / parancs>", "mérve: ...", TG-szám, PR-szám, fájlút vagy link. Ha nem mérted, '
        'ne állítsd: "Dave indítja", "becslés (X szerint)".\n')
    return 2


if __name__ == '__main__':
    sys.exit(main())
