#!/usr/bin/env python3
"""PreToolUse gate (telegram reply + edit_message): a state claim or a number to Patrik only with its source.

Why: Klodel 35761, Patrik group TG 4477 "1 mehet" (audit shared/atvilagitas-1110/atvilagitas.md, chapter 4, item 3).
The audit counted 20 A-category errors in 6 days: a state or a number told to Patrik before it was measured ("kész",
"beállítottam", "fut", a price, a percentage). The rule ÁLLAPOT CSAK MÉRVE lived in memory and did not hold; the
render-claim gate stopped one verb, this one asks the same of every state claim: say where it comes from.

What blocks (exit 2, one line naming what was found): a reply or an edit to the owner's private chat or the team group
whose text makes a CLAIM and carries no SOURCE.
  CLAIM, in a sentence that is not a question: a state word (kész / elkészült / készen, beállítottam / beállítva,
  élesben / élesítve / élesítettem, fut / futnak, kint van, kiment), or a CAPABILITY ("ki tudjuk emelni",
  "kiemelhetjük", "képesek vagyunk", "meg lehet oldani", "működik", "be van állítva"; retro R2, TG 6035), that is not negated or conditional just before
  ("nincs kész", "még nem fut", "ha kész", "amint kész") nor future ("kész lesz"), or a number with a unit (%, Ft / forint / HUF, $ / USD / EUR / €, db, "N perc múlva").
  SOURCE, anywhere in the message: a "FORRÁS:" line, "mérve" / "mérés:" / "X mérte" / "mértem" (not "nem mértem" /
  "sem mérte": a denied measurement is none, Viktor 41972 LOW 2), "<X> szerint",
  "<X> jelzése", "forrással", "becslés (... szerint)", msg_id / msg 123,
  TG 1234, a PR (#123, PR 123), a file path (a/b.ext or /abs/path), a URL, a commit sha (7-40 hex with a digit and
  a letter), or an attached file (the reply's `files`: the result itself is the evidence).
  SITE STATE (hibanapló 2026-11-10 12:06, Patrik TG 4564 "nem alszik a myshp oldal... mirol beszélsz.."; Klodel
  36285): a down word (alszik / alvó / aludt / leállt / le van állva / leállítva) in one clause with a site or product
  (myshp, marabel, oldal, weboldal, honlap, webshop, *.hu). A department label is not a site ("a mySHP részleg
  alvó", CLAUDE.md "mySHP: alvó"). This claim needs a MEASUREMENT, not just any source: "mérve" / "mérés:" /
  "X mérte" / "mértem", an HTTP status ("HTTP 503", "státusz 200"), or an attached file (a screenshot). A TG number,
  a PR, a file path, a link or "X szerint" is not a measurement of a site's state: "CLAUDE.md szerint" was the
  error itself.
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
    # A capability told as a fact (retro R2, card 8639a3bb; hibanapló 2026-11-13 18:36, TG 6035: "Igen, pont ezt a
    # posztot ki tudjuk emelni" went out unmeasured): "tud" with an infinitive ("ki tudjuk emelni", "feltölteni
    # tudjuk"), the -hat/-het form ("kiemelhetjük"), "képesek vagyunk", "lehet" with an infinitive ("meg lehet
    # oldani"), "működik", "be van állítva".
    ('képesség', NEG + r'(?<!\bhogyan )(\btud(juk|om|unk|ja|jak|nak)\s+(\w+\s+){0,2}?\w{2,}ni\b'
                 r'|\b\w{2,}ni\s+tud(juk|om|unk|nak|ja)\b'
                 r'|\b\w{3,}(hatjuk|hetjuk|hatom|hetem|hatunk|hetunk)\b'
                 r'|\bkepes(ek)?\s+(vagyunk|vagyok)\b'
                 r'|\blehet\s+(\w+\s+)?\w{2,}ni\b'
                 r'|\bmukod(ik|nek|ott|ottek)\b(?!-e\b)'
                 r'|\bbe van(nak)? allitva\b)' + FUT),
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
SITE_LABEL = 'oldal-állapot'
PAGE = r'\w*?oldal(a|ak|at|on|an|unk|uk|ad|ra|rol|hoz|nak)?'  # oldal, nyitooldal, oldala; not "foldalatti"
SITE = re.compile(r'\b(myshp|marabel|webshop|weboldal\w*|honlap\w*|' + PAGE + r')\b|\w[.\u00b7]hu\b')
SITE_EXPLICIT = re.compile(r'\b(webshop|weboldal\w*|honlap\w*|' + PAGE + r')\b|\w[.\u00b7]hu\b')
DOWN = re.compile(r'\b(alszik|alszanak|alvo\w*|aludt\w*|leallt\w*|le van allva|leallitva)\b')
DEPT = re.compile(r'\b\w*reszleg\w*\b')  # reszleg, csapatreszleg (replay 2026-11-10: the correction itself blocked)
MEASURED = [re.compile(rx) for rx in (
    r'\bmerve\b|\bmeres\s*:|\bmert(e|em|uk|ek|ed)\b|\bmeresevel\b|\belo(ben)? meres',
    r'\bhttp\s?[1-5]\d\d\b|\bstatusz(kod)?\s*:?\s*[1-5]\d\d\b|\bstatus\s*:?\s*[1-5]\d\d\b',
)]
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
NEGW = re.compile(r'\b(nem|nincs|sincs|semmi|sem|meg nem)\b')
IDIOM = re.compile(r'\bes kesz\s*[.!]?\s*$')


def _plain(text):
    """Normalized text without quotes; a dot inside a word ("marabel.hu", "a/b.md") is not a sentence end: kept as a
    middle dot for the split."""
    return re.sub(r'(?<=\w)\.(?=\w)', '\u00b7', QUOTED.sub(' ', norm(text)))


def _sentence_claims(sent):
    """The claim labels of one sentence, outside a question and conditional or negated clauses."""
    found = []
    if sent.endswith('?'):
        return found
    for clause in re.split(r'[,;:\u2013\u2014]| - ', sent):
        clause = ' '.join(clause.split())
        if not clause or COND.search(clause) or NEGW.search(clause) or IDIOM.search(clause):
            continue
        for label, rx in CLAIMS:
            if label not in found and rx.search(clause):
                found.append(label)
        if (SITE_LABEL not in found and DOWN.search(clause) and SITE.search(clause)
                and not (DEPT.search(clause) and not SITE_EXPLICIT.search(clause))):
            found.append(SITE_LABEL)
    return found


def claims(text):
    """The claim labels in the text, outside quotes, questions, conditional and negated clauses."""
    found = []
    for sent in sentences(_plain(text)):
        for label in _sentence_claims(sent):
            if label not in found:
                found.append(label)
    return found


# A denied measurement is none ("nem mertem", "nem is mertem", "nincs merve", "nem merve", "meres: nincs"): cut it out
# before the SOURCES / MEASURED patterns look. A measurement right after the denial may follow any run of spaces,
# tabs or newlines ("nem\nmertem"); the text keeps its lines for the "FORRÁS:" line rule. Viktor 41981 LOW 2.
# One word between the denial and the measurement counts on the same line only: "Kész, nincs gond" + newline +
# "mérve: 200" is a real measurement on its own line (Viktor 41984 INFO 1). This rule is the only denial filter: the
# SOURCES / MEASURED patterns have no lookbehind of their own (Viktor 41984 INFO 2, they were dead code).
# A denial split by a line break inside ("Nem is" + newline + "mértem") is still one: the word may cross the line
# when a verb form follows without a colon ("mérve: 200" on its own line stays a measurement). Viktor 42004 LOW 1.
DENIED_MEAS = re.compile(r'\b(nem|sem|se|nincs)\b(?:\s+|[^\S\n]+\w+[^\S\n]+|[^\S\n]+\w+\s+(?=mert\w*\b(?!\s*:)))(mert\w*|merve)\b|\bmeres\s*:\s*(nincs|nem)\b')


def _measure_text(text):
    return DENIED_MEAS.sub(' ', norm(text))


def has_source(text, files):
    if files:
        return True
    plain = _measure_text(text)
    return any(rx.search(plain) for rx in SOURCES)


def has_measurement(text, files):
    """A site's state needs a measurement (or an attached screenshot), not just any source."""
    if files:
        return True
    plain = _measure_text(text)
    return any(rx.search(plain) for rx in MEASURED)


CAP_LABEL = 'képesség'
# A capability may also go out as a labelled guess (CLAUDE.md "Tények és találgatás": a tipp is marked as one IN THE
# SAME SENTENCE): "tipp", "[tipp]", "nem ellenőriztem", "nem mértem". Only for the capability label: a state claim
# ("kész", "fut") still needs a source (replay 2026-11-13: "100 kép ..., ezt tudjuk kinyerni belőle (a
# megvalósíthatóság tipp, próbaképsoron mérjük)" was a correct sentence).
# The label counts in the capability's own sentence only, and a denied one is no label (Viktor 41287 LOW 1: "Ki tudjuk
# emelni. Egyébként a tipp: holnap szólok." and "Ki tudjuk emelni! Ez nem tipp, ez biztos." both went through).
HEDGE = re.compile(r'\btipp\b|\bnem ellenoriztem\b|\bnem mertem\b|\bnem mert\b')
# A denial stands right before the label ("nem tipp", "nem is tipp", "nem csak egy tipp", "korantsem tipp", "nincs
# itt semmi tipp", "nem (tipp)") or right after it ("tipp helyett", "tipp nelkul"): up to two words and no comma between.
DENY_BEFORE = re.compile(r'\b(nem|sem|se|korantsem|semmi|nincs)\b(?:(?:\s+\w+){0,2}\s*|\s*[(\["*_]+)$')
DENY_AFTER = re.compile(r'tipp\W*(helyett|nelkul)\b')


def hedged(sent):
    """True when the sentence carries a guess label that is not denied. Whitespace is collapsed first ("nem  tipp",
    "nem<tab>tipp")."""
    s = ' '.join(sent.split())
    for m in HEDGE.finditer(s):
        if m.group().startswith('tipp') and (DENY_BEFORE.search(s[max(0, m.start() - 40):m.start()])
                                             or DENY_AFTER.match(s, m.start())):
            continue
        return True
    return False


def unhedged_capability(text):
    """True when some sentence claims a capability and carries no guess label of its own."""
    return any(CAP_LABEL in _sentence_claims(sent) and not hedged(sent) for sent in sentences(_plain(text)))


def unsourced(text, files):
    """The claim labels that lack what they need: a source in general (a capability: a source, or a guess label in
    each capability sentence), a measurement for a site's state."""
    found = claims(text)
    out = []
    general = [l for l in found if l not in (SITE_LABEL, CAP_LABEL)]
    if general and not has_source(text, files):
        out += general
    if CAP_LABEL in found and not has_source(text, files) and unhedged_capability(text):
        out.append(CAP_LABEL)
    if SITE_LABEL in found and not has_measurement(text, files):
        out.append(SITE_LABEL)
    return out


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
    found = unsourced(text, ti.get('files') or [])
    if not found:
        return 0
    kind = chats.get(chat, '?') if isinstance(chats, dict) else '?'
    log_mode = os.environ.get('CLAIM_SOURCE_GATE_MODE') == 'log'
    log_block(kind + (' (log-only)' if log_mode else ''), found, len(text))
    if log_mode:  # a measuring day before enforcing: logged, let through
        return 0
    sys.stderr.write(
        f'ÁLLÍTÁS-FORRÁS-KAPU (Klodel 35761, ÁLLAPOT CSAK MÉRVE): {", ".join(found)} forrás nélkül. Írd mellé, honnan '
        'tudod: "FORRÁS: <fájl / msg_id / parancs>", "mérve: ...", TG-szám, PR-szám, fájlút vagy link. Ha nem mérted, '
        'ne állítsd: "Dave indítja", "becslés (X szerint)".'
        + (' Oldal/termék állapota (alszik, leállt) CSAK mérve: "mérve: HTTP 200, 15:02" vagy Pulzus mérése; a '
           'szervezeti címke ("mySHP: alvó" részleg) nem az oldal állapota.' if SITE_LABEL in found else '')
        + (' Képesség ("ki tudjuk", "működik", "be van állítva", retró R2, TG 6035): előbb mérd meg (ki, msg_id), '
           'vagy jelöld tippnek ugyanabban a mondatban ("tipp, nem mértem").' if CAP_LABEL in found else '') + '\n')
    return 2


if __name__ == '__main__':
    sys.exit(main())
