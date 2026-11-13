#!/usr/bin/env python3
"""msg_gate.py -- the pre-send gate of scripts/agent-msg.sh (card aba42256, DREAM 11-11).

    printf '%s' "$TEXT" | python3 -I scripts/lib/msg_gate.py --from <a> --to <b>

Exit 0: send. Exit 3: refused, the reasons are on stderr (names and counts only, never the matched
text). Any other exit: the gate itself failed, which is not a verdict on the text.

Two rules:

1. Secret shapes, every sender and recipient. The patterns are NOT copied here: they are read at
   run time from SECRET_PATTERNS in src/security/secret-gate.ts, the list the commit gate and the
   transcript masking already use, so a pattern added there covers messages too. If that file is
   missing or yields fewer than MIN_PATTERNS, the gate fails (exit 4): a gate that silently runs
   with no patterns would answer "clean" for everything.
   Measured 2026-11-11 on 30 days of agent_messages (32 137 rows): 4 hits, all 2026-10-12, a
   deliberately fake low-entropy Stripe placeholder; nothing else.

2. Majsztro's traffic (--from or --to in STRICT, default "majsztro"): Klodel filters Majsztro's
   text before Patrik sees it, and Majsztro is a marketing agent with a budget that hit 100 %.
   - Longer than MAX_CHARS characters (default 12 000): refused, put the material in a file under
     agents/majsztro/kontext/ and send the path. Measured over 7 days: 5 messages above 12 000 in
     the whole fleet, 4 of them to majsztro (longest 22 789).
   - An e-mail address outside our own domains (default marabel.hu, myshp.hu, subdomains too):
     refused. Measured over 30 days of Majsztro traffic: 11 addresses, 10 were our own marabel.hu
     address quoted in copy text (allowed), 1 a third party's press address.
   Other pairs are not length- or e-mail-gated: 94 fleet messages a week carry an address,
   mostly our own, in mail and order work where the address is the subject.

3. A stop order from Klodel (--from in STOP_FROM, default "klodel"; Klodel 37876, UGYANAZ A HIBA
   KÉTSZER NEM, 2nd time): Patrik's opinion ("senkik vannak", TG 5294) was read as a stop and Radar
   was stopped; Patrik TG 5297: "ne allitsd le". First time: TG 4943 (memory aggaly-nem-elvetes).
   A text with TÁRGYTALAN | állj le | leállít | ne folytasd | nem kell tovább, or (Viktor 37886 L1)
   állítsd le | állítsuk le | zárd le | hagyd abba | abbahagy, is refused unless it carries a line
       LEÁLLÍTÁS-OK: TG <number> "<Patrik's words, verbatim>"
   whose quote holds an explicit stop word: zárd le | nem kell | állítsd le | állítsuk le | hagyjuk |
   hagyom | ne csináld. Both sides are matched without accents (Patrik types "ne allitsd le"), and a
   stop word right after "ne"/"nem" is a negation, not a stop ("ne állítsd le" does not count).
   Measured 2026-11-11 on 30 days of Klodel's messages: 351 of 9584 match the trigger (about 12 a
   day), many of them not a stop order ("a kérdésem tárgytalan", "Blender-leállítás"). A quote that
   says NOT to stop ("nem kell leállítani", "ne hagyjuk abba") never counts, and a text that starts
   with VISSZAVONVA <msg_id> (Klodel's revocation of a stop, 37875) exempts only that prefix. A stop
   verb right after "ne"/"nem" is not a trigger either. Zero-width characters are ignored.
   Known limit: the gate sees agent-msg.sh only; a raw POST /api/messages is not gated.

4. SPEC LOCK (Klodel 38950, hibanapló 2026-11-12 08:24): Klodel released the code of our own system
   (card d9bc643b) with agent-msg before Patrik approved the specification; Patrik TG 17862: "be kéne
   fejezni a specifikaciot mert én még nem akarom hfejlesszetek hülyeségeket". store/spec-zar.json
   lists locked cards: {"<card id>": "<reason>"} or {"<card id>": {"reason": "...", "keywords": [...]}}.
   A text from SPEC_FROM (default "klodel") that names a locked card id or one of its keywords AND a
   code-release word (kód, repó-váz, implement, worktree, PR, push, első szelet) is refused unless it
   carries a line
       SPEC-OK: TG <number>
   A revocation passes: a text that starts with VISSZAVONVA <msg_id> and says the code is not on now
   ("kód ... nincs", "ne pusholj"). Only the revocation form is exempt, a plain negation is not, so
   "nem kell PR, de indulhat a kód" stays refused. A missing lock file means no lock; an unreadable or
   malformed one is a gate failure (exit 4), never a silent "nothing locked".

5. REQUEST VERBATIM (retro 2026-11-13 R5, card 858f80bc): a request was over-read six times in a week
   (an idea turned into a production plan, an opinion read as a stop, an unrequested change; Patrik TG
   17827 "ki a faszom adott erre utasitast?", TG 17829 "ötleteltem cska"). A text from KERES_FROM
   (default "klodel") that hands out work -- a "Kész, ha:" anywhere or a "FELADAT (Patrik TG n)" header --
   and names a Patrik message ("Patrik ... TG n", same sentence, within 40 characters) is refused unless
   it carries a line
       KERES-SZO-SZERINT: "<Patrik's words, at least 3, contiguous>" (TG n)
   whose quote is found, accent- and whitespace-insensitively, in an inbound Telegram message n of the
   main agent's ledger (store/claudeclaw.db, conversation_log, direction 'in', read-only). If the text
   has a "FELADAT (Patrik TG n)" header, that n must be one of the quoted ones. When the source sentence
   of the quote (from the previous . ! ? or line break to the next one) is a question or conditional
   (ends with "?", or holds an IDEA_MARK such as "lehetne", "kéne", "mi lenne", "ötlet"; the list of
   the feladat-kiadas skill's kiadas.py), the text also needs a line
       IGEN: TG m
   where m is a later inbound message in the same chat holding a yes word (igen, ok, oké, mehet, jó,
   csináld, persze, rendben, hajrá, pontosan) that is not negated and does not end a question.
   The message_id alone is ambiguous (measured: private and group chat both hold ids 10-999), so any
   ledger row with that id counts, but the IGEN must be in the chat where the quote was found.
   Measured 2026-11-13 on 30 days of Klodel's messages (9495): 752 hand out work, 623 of them name a
   Patrik TG; of 81 existing "Patrik szó szerint" quotes 51 are found verbatim in their TG (the misses
   are 800-1500 character quotes, hence a short contiguous quote here), 0 TGs are missing from the
   ledger; of 60 source sentences found, 14 are a question or conditional.
   An unreadable ledger, when the rule fires, is a gate failure (exit 4), never a silent pass.
   Known limits: a work order naming only "TG n" without "Patrik" (60 of 752) is not gated; the
   Creatorz ban lives in the reply gate (scripts/hooks/product-image-gate.py CREATORZ_RE).

6. ABSENCE CLAIMS IN A DELIVERED FILE (retro 2026-11-13 R10, card 1f943050; Radar 41254, 41293): Radar wrote "itthon
   nincs" and a bare "NINCS ADAT" into delivered research twice (hibanapló 11-11 L232; Balázs TG 5579). A text from
   HIANY_FROM (default "radar") is refused when a shared/**.md file it DELIVERS fails scripts/lib/hiany_lint.py
   (R10a: an absence claim at home needs ITTHON-MERT and measured Meska / Pepita / eMAG + the 4-domain site probe;
   R10b: every NINCS ADAT needs a search log). Delivered = the path stands on a line with a delivery word (kész,
   leadva, leadás, leadom, elkészült; not right after ne / nem / még nem / nincs); a mere mention of another file
   (a colleague's report, parked work) is not linted (Radar 41293). A named file outside <root>/shared, or missing,
   is refused too; the lint failing to load is exit 4.
   Measured 2026-11-13 on 30 days of Radar's messages (704): 226 deliver a shared file, 162 files; of the 4 files
   delivered after the R10 rule (11-13 12:00) 3 fail today, 2 of them on a real gap. The lint's verdict equals
   Radar's original script on all 1909 shared/**.md files (393 fail in both, outputs identical).

Env (the suite uses them): MARVEEN_MSG_GATE_SECRET_SRC, MARVEEN_MSG_GATE_STRICT (comma list),
MARVEEN_MSG_GATE_MAX_CHARS, MARVEEN_MSG_GATE_OWN_DOMAINS (comma list), MARVEEN_MSG_GATE_STOP_FROM
(comma list), MARVEEN_MSG_GATE_SPEC_LOCK (path), MARVEEN_MSG_GATE_SPEC_FROM (comma list),
MARVEEN_MSG_GATE_KERES_FROM (comma list), MARVEEN_MSG_GATE_LEDGER (path), MARVEEN_MSG_GATE_HIANY_FROM (comma
list), MARVEEN_HIANY_ROOT (the install whose shared/ is read; default this repo).
"""
import json
import os
import re
import sqlite3
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SRC = os.path.join(HERE, '..', '..', 'src', 'security', 'secret-gate.ts')
MIN_PATTERNS = 10

EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})')
# One entry per line in secret-gate.ts:  { name: '...', pattern: /.../flags },
ENTRY = re.compile(r"\{\s*name:\s*'([^']+)',\s*pattern:\s*/((?:\\.|[^/\\\n])+)/([a-z]*)\s*\}")


# Viktor 37183 F1: a JS regex without the u flag has an ASCII \b; Python's str \b is Unicode, so in
# "é" + "sk_live_..." Python sees no boundary before the s and the key passes, while the commit gate
# (JS) catches it. re.ASCII is not the fix: it would also narrow \s below JS. So \b and \B are
# rewritten into ASCII lookarounds, outside character classes only.
_W = '[A-Za-z0-9_]'
_ASCII_B = '(?:(?<!%s)(?=%s)|(?<=%s)(?!%s))' % (_W, _W, _W, _W)
_ASCII_NB = '(?:(?<=%s)(?=%s)|(?<!%s)(?!%s))' % (_W, _W, _W, _W)


def js_to_py(body):
    out, i, in_class = [], 0, False
    while i < len(body):
        ch = body[i]
        if ch == '\\' and i + 1 < len(body):
            nxt = body[i + 1]
            if not in_class and nxt == 'b':
                out.append(_ASCII_B)
            elif not in_class and nxt == 'B':
                out.append(_ASCII_NB)
            elif nxt == '/':
                out.append('/')
            else:
                out.append(body[i:i + 2])
            i += 2
            continue
        if ch == '[' and not in_class:
            in_class = True
        elif ch == ']' and in_class:
            in_class = False
        out.append(ch)
        i += 1
    return ''.join(out)


def die(msg):
    print('msg_gate: ' + msg, file=sys.stderr)
    sys.exit(4)


def load_secret_patterns(path):
    try:
        with open(path, encoding='utf-8') as f:
            src = f.read()
    except OSError as e:
        die('cannot read the secret patterns at %s (%s)' % (path, e.strerror))
    start = src.find('export const SECRET_PATTERNS')
    if start < 0:
        die('SECRET_PATTERNS not found in %s' % path)
    end = src.find('\n];', start)
    if end < 0:
        die('SECRET_PATTERNS has no end in %s' % path)
    block = src[start:end]
    out = []
    for name, body, flags in ENTRY.findall(block):
        if set(flags) - {'i'}:
            die('pattern %r has flags %r this gate does not translate' % (name, flags))
        try:
            out.append((name, re.compile(js_to_py(body), re.I if 'i' in flags else 0)))
        except re.error as e:
            die('pattern %r does not compile in Python: %s' % (name, e))
    if len(out) < MIN_PATTERNS:
        die('only %d secret patterns read from %s (expected at least %d)' % (len(out), path, MIN_PATTERNS))
    # Viktor 37183 F2: an entry this parser cannot read (e.g. an unescaped "/" inside a character
    # class, legal in JS) would drop out silently while the count stays above MIN_PATTERNS.
    entries = block.count("name: '")
    if len(out) != entries:
        die('read %d of %d SECRET_PATTERNS entries from %s; an entry is not in the one-line form'
            % (len(out), entries, path))
    return out


# Rule 3. Patterns are written WITHOUT accents and matched against fold(text). Whitespace inside a phrase is \s+
# (Viktor 37886 L1: "állj  le", "állj\nle").
_B = r'(?<![a-z0-9])'
# Viktor 37886 L1: the imperative stop verbs are triggers too ("Állítsd le Radart", "Zárd le a feladatot").
STOP_VERB = re.compile(_B + r'(?:allj\s+le|leallit|allitsd\s+le|allitsuk\s+le|zard\s+le|hagyd\s+abba|abbahagy)')
STOP_PHRASE = re.compile(_B + r'(?:targytalan|ne\s+folytasd|nem\s+kell\s+tovabb)')
STOP_OK_LINE = re.compile(r'^[ \t]*leallitas-ok:[ \t]*tg[ \t]*(\d+)[ \t]+["„“”](.+?)["“”][ \t]*$', re.M)
STOP_WORD = re.compile(_B + r'(?:zard\s+le|nem\s+kell|allitsd\s+le|allitsuk\s+le|hagyjuk|hagyom|ne\s+csinald)(?![a-z0-9])')
SELF_NEGATED = re.compile(r'(?:ne\s+csinald|nem\s+kell)$')
# "ne állítsd le", "nem kell leállítani". Viktor 37910 L5: only a short window before the verb is searched
# (NEG_WINDOW), so a text of many negated verbs stays linear; a longer gap reads as no negation (the safe side).
# Klodel 39243: "nem azt mondtam zárd le" (Patrik TG 4943) denies a stop, it does not give one; the denied
# saying ("nem azt mondtam/írtam/kértem", optional ", hogy") right before the verb is a negation too. Kept
# narrow on purpose: "nem azt mondtam, hogy folytasd, hanem zárd le" is still a stop (the window ends at
# "hanem").
NEGATION = re.compile(_B + r'(?:ne|nem(?:\s+kell)?|nem\s+azt\s+(?:mondtam|irtam|kertem),?(?:\s+hogy)?)\s+$')
NEG_WINDOW = 24
# "nem kell leállítani", "ne hagyjuk abba": a quote that says NOT to stop is never a stop, whatever else it holds.
NEG_STOP = re.compile(_B + r'(?:nem\s+kell\s+(?:leallit|lezar|abbahagy|befejez)|ne\s+(?:hagyjuk|hagyd)\s+abba)')
# Klodel's revocation of a stop (37875: "VISSZAVONVA a 37874 leállítás: ..."). Viktor 37886 L2: the prefix needs the
# msg_id, and it only exempts itself; the rest of the text is still checked ("... Közben: állj le Radar." is refused).
REVOKE = re.compile(r'^\s*visszavonva[\s:]+(?:a\s+)?\d{4,}(?:\s+leallitas\w*)?')


def fold(text):
    """Lower case, accents removed (á -> a, ő -> o), so "ne allitsd le" and "ne állítsd le" read the same.
    Format characters (zero-width space/joiner, soft hyphen; category Cf) are dropped (Viktor 37886 L4)."""
    # Viktor 37910 L6: NFKD, so full-width letters fold to ASCII too.
    return ''.join(c for c in unicodedata.normalize('NFKD', text)
                   if not unicodedata.combining(c) and unicodedata.category(c) != 'Cf').lower()


def is_stop_order(folded):
    """A stop phrase, or a stop verb that is not negated ("ne állítsd le" is the opposite of a stop)."""
    if STOP_PHRASE.search(folded):
        return True
    return any(not NEGATION.search(folded[max(0, m.start() - NEG_WINDOW):m.start()])
               for m in STOP_VERB.finditer(folded))


def quote_stops(quote):
    """True if the quote holds an explicit stop word that is not negated ("ne allitsd le" is not a stop)."""
    q = fold(quote)
    if NEG_STOP.search(q):
        return False
    for m in STOP_WORD.finditer(q):
        if SELF_NEGATED.match(m.group(0)) or not NEGATION.search(q[max(0, m.start() - NEG_WINDOW):m.start()]):
            return True
    return False


def stop_reason(text):
    """None if the text is not a stop order or carries a valid LEÁLLÍTÁS-OK line, else the refusal reason."""
    folded = fold(text)
    revoke = REVOKE.match(folded)
    if not is_stop_order(folded[revoke.end():] if revoke else folded):
        return None
    for m in STOP_OK_LINE.finditer(folded):
        if quote_stops(m.group(2)):
            return None
    return ('leállító üzenet (TÁRGYTALAN / állj le / leállít / állítsd le / zárd le / hagyd abba / ne folytasd / '
            'nem kell tovább) Patrik kifejezett leállító szava nélkül. Patrik véleménye nem leállítás. Ha Patrik '
            'tényleg leállította, tegyél bele egy sort: LEÁLLÍTÁS-OK: TG <szám> "<Patrik szó szerinti szava>", az '
            'idézetben kifejezett leállító szóval (zárd le | nem kell | állítsd le | állítsuk le | hagyjuk | hagyom | '
            'ne csináld; a "ne állítsd le" nem az). Ha nem állította le, ne állítsd le.')


# Rule 4. Matched against fold(text), like rule 3.
DEFAULT_SPEC_LOCK = os.path.join(HERE, '..', '..', 'store', 'spec-zar.json')
CODE_WORD = re.compile(_B + r'(?:kod|repo[\s-]*vaz|implement|worktree|pr(?![a-z])|push|elso\s+szelet)')
SPEC_OK_LINE = re.compile(r'^[ \t]*spec-ok:[ \t]*tg[ \t]*\d+[ \t]*$', re.M)
# "Kód, repó-váz, próba most NINCS", "ne pusholj": a code word with "nincs" after it in the same clause, or "ne"
# right before it.
NO_CODE = re.compile(r'(?:' + _B + r'(?:kod|repo[\s-]*vaz|implement|worktree|push|elso\s+szelet)[^.!?\n]{0,40}?'
                     r'(?<![a-z0-9])nincs(?![a-z0-9])|' + _B + r'ne\s+(?:pushol|kodol|implemental))')

# The revocation opens the text, after an optional "Klodel -> Kernel:" header (38944 starts that way).
REVOKE_SPEC = re.compile(r'^\s*(?:[a-z]+\s*->\s*[a-z]+(?:\s*\([^)\n]*\))?\s*:\s*)?visszavonva[\s:]+(?:a\s+)?\d{4,}')


def load_spec_locks(path):
    """{card id: [folded keywords]}. Missing file: no lock. Unreadable or malformed: the gate fails (exit 4)."""
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        die('spec lock file unreadable or not JSON: %s' % path)
    if not isinstance(raw, dict):
        die('spec lock file is not an object: %s' % path)
    locks = {}
    for card, v in raw.items():
        if not isinstance(card, str) or not re.fullmatch(r'[0-9a-f]{8}', card.lower()):
            die('spec lock: a key is not an 8-hex card id')
        kws = v.get('keywords', []) if isinstance(v, dict) else []
        if not (isinstance(v, str) or isinstance(v, dict)) or not isinstance(kws, list) \
                or not all(isinstance(k, str) and k.strip() for k in kws):
            die('spec lock: card %s has a malformed value' % card)
        locks[card.lower()] = [fold(k).strip() for k in kws]
    return locks


def spec_lock_reason(text, locks):
    """None if no locked card is released for code, else the refusal reason (names the card only)."""
    folded = fold(text)
    hit = None
    for card, kws in locks.items():
        if re.search(r'(?<![0-9a-f])' + card + r'(?![0-9a-f])', folded) or any(
                re.search(_B + r'\s+'.join(map(re.escape, k.split())) + r'(?![a-z0-9])', folded) for k in kws):
            hit = card
            break
    if hit is None or not CODE_WORD.search(folded):
        return None
    if SPEC_OK_LINE.search(folded):
        return None
    if REVOKE_SPEC.match(folded) and NO_CODE.search(folded):
        return None
    return ('kód-kiadás zárolt kártyára (%s, store/spec-zar.json) Patrik spec-OK-ja nélkül. Amíg Patrik a '
            'specifikációt jóvá nem hagyja, kód, repó-váz, worktree, PR, push nem indul. Ha jóváhagyta, tegyél bele '
            'egy sort: SPEC-OK: TG <szám>.' % hit)


# Rule 5. Matched against fold(text), like rules 3 and 4.
DEFAULT_LEDGER = os.path.join(HERE, '..', '..', 'store', 'claudeclaw.db')
WORK_ORDER = re.compile(_B + r'kesz,?\s+ha\s*:|' + _B + r'feladat\s*\(\s*patrik\s+tg')
PATRIK_TG = re.compile(_B + r'patrik(?![a-z0-9])[^\n.!?]{0,40}?' + _B + r'tg\s*#?\s*\d+')
FELADAT_TG = re.compile(_B + r'feladat\s*\(\s*patrik\s+tg\s*#?\s*(\d+)')
KERES_LINE = re.compile(r'^[ \t]*keres-szo-szerint:[ \t]*["„“”](.+?)["“”][ \t]*\([ \t]*tg[ \t]*(\d+)[ \t]*\)[ \t]*$', re.M)
IGEN_LINE = re.compile(r'^[ \t]*igen:[ \t]*tg[ \t]*(\d+)[ \t]*$', re.M)
# The ötletelés-kapu marks of the feladat-kiadas skill (kiadas.py OTLET_JELEK), folded; "?" is checked apart.
IDEA_MARKS = ('nenk', 'nank', 'hetne', 'hatna', 'elvileg', 'otlet', 'mi lenne', 'lehetne', 'kene', 'kellene',
              'erdemes', 'vajon', 'gondolkod')
YES_WORD = re.compile(_B + r'(?:igen|ok|oke|okes|okay|mehet|jo|csinald|csinaljuk|persze|rendben|hajra|pontosan)'
                      r'(?![a-z0-9])')
MIN_QUOTE_WORDS = 3


def squash(folded):
    return re.sub(r'\s+', ' ', folded).strip()


def source_sentence(text, i, j):
    """The sentence(s) of text[i:j]: from the last . ! ? or line break before i to the first one at or after the
    last character of the span (so a span ending in "?" ends its sentence there)."""
    a = max(text.rfind(ch, 0, i) for ch in '.!?\n') + 1
    ends = [k for k in (text.find(ch, max(i, j - 1)) for ch in '.!?\n') if k >= 0]
    return text[a:(min(ends) + 1 if ends else len(text))]


def is_idea(sentence):
    return '?' in sentence or any(m in sentence for m in IDEA_MARKS)


def says_yes(folded):
    """A yes word that is not negated ("nem jó") and whose sentence is not a question ("ok?")."""
    for m in YES_WORD.finditer(folded):
        if NEGATION.search(folded[max(0, m.start() - NEG_WINDOW):m.start()]):
            continue
        if '?' in source_sentence(folded, m.start(), m.end()):
            continue
        return True
    return False


def open_ledger(path):
    """A read-only connection; the ledger is never created. Missing or unreadable: the gate fails (exit 4)."""
    if not os.path.isfile(path):
        die('the Telegram ledger is missing: %s' % path)
    try:
        con = sqlite3.connect('file:%s?mode=ro' % path, uri=True, timeout=5)
        con.execute('SELECT chat_id, message_id, text, created_at FROM conversation_log LIMIT 1').fetchall()
        return con
    except sqlite3.Error as e:
        die('the Telegram ledger is unreadable: %s (%s)' % (path, e))


def inbound(con, tg):
    """[(chat_id, created_at, folded text)] of the inbound ledger rows with this message_id."""
    try:
        rows = con.execute("SELECT chat_id, created_at, text FROM conversation_log WHERE direction='in' "
                           "AND CAST(message_id AS TEXT)=?", (str(tg),)).fetchall()
    except sqlite3.Error as e:
        die('the Telegram ledger query failed (%s)' % e)
    return [(str(c), ts or 0, squash(fold(t or ''))) for c, ts, t in rows]


def keres_reason(text, ledger_path):
    """None if the text is not a work order on a Patrik TG, or carries valid KERES-SZO-SZERINT (and IGEN)
    lines; else the refusal reason (TG numbers only, never the quote)."""
    folded = fold(text)
    if not (WORK_ORDER.search(folded) and PATRIK_TG.search(folded)):
        return None
    lines = KERES_LINE.findall(folded)
    if not lines:
        return ('kiadás Patrik TG-üzenetére hivatkozva, de nincs benne a kérés szó szerint. Tegyél bele egy '
                'külön sort: KERES-SZO-SZERINT: "<Patrik legalább 3 egymás utáni szava>" (TG <szám>), és ha az a '
                'mondat kérdő vagy feltételes (ötletelés), egy IGEN: TG <szám> sort is Patrik későbbi igenjével.')
    con = open_ledger(ledger_path)
    try:
        ok_tgs, problems = set(), []
        yes_cache = {}
        for quote, tg in lines:
            q = squash(quote)
            if len(q.split()) < MIN_QUOTE_WORDS:
                problems.append('TG %s: az idézet rövidebb %d szónál' % (tg, MIN_QUOTE_WORDS))
                continue
            rows = inbound(con, tg)
            if not rows:
                problems.append('TG %s: nincs ilyen bejövő üzenet a naplóban (store/claudeclaw.db)' % tg)
                continue
            hit = None
            for chat, ts, body in rows:
                i = body.find(q)
                if i >= 0:
                    hit = (chat, ts, body, i)
                    break
            if hit is None:
                problems.append('TG %s: az idézet nincs benne szó szerint (egybefüggő részlet kell)' % tg)
                continue
            chat, ts, body, i = hit
            if is_idea(source_sentence(body, i, i + len(q))):
                yes = False
                for m in IGEN_LINE.findall(folded):
                    key = (m, chat, ts)
                    if key not in yes_cache:
                        yes_cache[key] = any(c == chat and t2 > ts and says_yes(b) for c, t2, b in inbound(con, m))
                    if yes_cache[key]:
                        yes = True
                        break
                if not yes:
                    problems.append('TG %s: a forrásmondat kérdő vagy feltételes (ötletelés), kell egy IGEN: TG <szám> '
                                    'sor Patrik későbbi, ugyanabban a chatben adott igenjével ("Így értem: X. Nem '
                                    'csinálom: Y." után)' % tg)
                    continue
            ok_tgs.add(tg)
    finally:
        con.close()
    # Every KERES line must hold (a false one is a false claim of Patrik's words), and the header's TG is covered.
    head = FELADAT_TG.search(folded)
    if head and head.group(1) not in ok_tgs:
        problems.append('a FELADAT (Patrik TG %s) fejléc TG-jére nincs érvényes KERES-SZO-SZERINT sor' % head.group(1))
    if not problems:
        return None
    return 'kérés-kapu (retró R5): ' + '; '.join(problems)


# Rule 6. The delivery word is matched on fold(line); the path on the raw line.
DELIVER = re.compile(_B + r'(?:kesz|leadva|leadas|leadom|elkeszult)(?![a-z0-9])')
NOT_YET = re.compile(_B + r'(?:ne|nem|meg\s+nem|nincs)\s+$')
# Viktor 41461 LOW 3 (CWE-1333): the path is bounded to 240 characters, so a long run of "shared/" without a blank
# stays linear instead of quadratic (140 KB took 8 s).
SHARED_MD = re.compile(r'(?<![\w.-])(shared/[^\s`\'"()<>,;|]{1,240}?\.md)(?![\w-])')
MAX_FINDINGS = 3


def delivered_files(text):
    """shared/**.md paths that stand on a line with a non-negated delivery word, in order, once each."""
    out = []
    for ln in text.splitlines():
        f = fold(ln)
        if not any(not NOT_YET.search(f[max(0, m.start() - 12):m.start()]) for m in DELIVER.finditer(f)):
            continue
        for p in SHARED_MD.findall(ln):
            if p not in out:
                out.append(p)
    return out


def hiany_reason(text):
    """None if no delivered shared file fails the absence-claim lint, else the refusal reason."""
    files = delivered_files(text)
    if not files:
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('_hiany_lint', os.path.join(HERE, 'hiany_lint.py'))
        lint = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lint)
    except Exception as e:  # a missing or broken lint is a gate failure, never a silent pass
        die('scripts/lib/hiany_lint.py does not load (%s)' % e.__class__.__name__)
    shared = os.path.join(lint.root(), 'shared')
    bad = []
    for rel in files:
        path = os.path.realpath(os.path.join(lint.root(), rel))
        if not path.startswith(shared + os.sep):
            bad.append('%s: a shared/ mappán kívülre mutat' % rel)
            continue
        try:
            findings = lint.lint(path)
        except OSError as e:
            bad.append('%s: nem olvasható (%s)' % (rel, e.__class__.__name__))
            continue
        if findings:
            more = ' (+%d további)' % (len(findings) - MAX_FINDINGS) if len(findings) > MAX_FINDINGS else ''
            bad.append('%s: %s%s' % (rel, ' | '.join(x[:200] for x in findings[:MAX_FINDINGS]), more))
    if not bad:
        return None
    return ('hiány-kapu (retró R10): a leadott fájl nem megy át a hiány-linten (python3 -I scripts/lib/hiany_lint.py '
            '<fájl>). Itthoni hiányhoz ITTHON-MERT sor és mért Meska / Pepita / eMAG + site-próba, minden NINCS ADAT '
            'mellé forrás + eredmény vagy napló-hivatkozás kell. ' + '; '.join(bad))


def csv_env(name, default):
    return [x.strip().lower() for x in os.environ.get(name, default).split(',') if x.strip()]


def main(argv):
    frm = to = None
    i = 0
    while i < len(argv):
        if argv[i] == '--from' and i + 1 < len(argv):
            frm = argv[i + 1]; i += 2
        elif argv[i] == '--to' and i + 1 < len(argv):
            to = argv[i + 1]; i += 2
        else:
            die('usage: msg_gate.py --from <a> --to <b>  (text on stdin)')
    if frm is None or to is None:
        die('usage: msg_gate.py --from <a> --to <b>  (text on stdin)')
    try:
        max_chars = int(os.environ.get('MARVEEN_MSG_GATE_MAX_CHARS', '12000'))
    except ValueError:
        die('MARVEEN_MSG_GATE_MAX_CHARS is not a number')

    text = sys.stdin.buffer.read().decode('utf-8', errors='replace')
    patterns = load_secret_patterns(os.environ.get('MARVEEN_MSG_GATE_SECRET_SRC', DEFAULT_SRC))

    reasons = []
    hits = [name for name, rx in patterns if rx.search(text)]
    if hits:
        reasons.append('titok-minta: %s. Titokra csak névvel és hellyel hivatkozz '
                       '(pl. "STRIPE_SECRET_KEY a Vaultban"); helykitöltő így: <helykitöltő>.'
                       % ', '.join(hits))

    strict = csv_env('MARVEEN_MSG_GATE_STRICT', 'majsztro')
    pair = {frm.lower(), to.lower()}
    if pair & set(strict):
        who = ', '.join(sorted(pair & set(strict)))
        if len(text) > max_chars:
            reasons.append('%d karakter, a határ %d (%s forgalma). Az anyagot tedd fájlba '
                           '(agents/majsztro/kontext/), és az útvonalat küldd.'
                           % (len(text), max_chars, who))
        own = csv_env('MARVEEN_MSG_GATE_OWN_DOMAINS', 'marabel.hu,myshp.hu')
        foreign = 0
        for m in EMAIL.finditer(text):
            d = m.group(1).lower()
            if not any(d == o or d.endswith('.' + o) for o in own):
                foreign += 1
        if foreign:
            reasons.append('%d e-mail-cím nem a saját domainjeinkről (%s; %s forgalma). '
                           'Ne a címet küldd, hanem hogy kié és hol található.'
                           % (foreign, ', '.join(own), who))

    if frm.lower() in csv_env('MARVEEN_MSG_GATE_STOP_FROM', 'klodel'):
        r = stop_reason(text)
        if r:
            reasons.append(r)

    if frm.lower() in csv_env('MARVEEN_MSG_GATE_SPEC_FROM', 'klodel'):
        r = spec_lock_reason(text, load_spec_locks(os.environ.get('MARVEEN_MSG_GATE_SPEC_LOCK', DEFAULT_SPEC_LOCK)))
        if r:
            reasons.append(r)

    if frm.lower() in csv_env('MARVEEN_MSG_GATE_KERES_FROM', 'klodel'):
        r = keres_reason(text, os.environ.get('MARVEEN_MSG_GATE_LEDGER', DEFAULT_LEDGER))
        if r:
            reasons.append(r)

    if frm.lower() in csv_env('MARVEEN_MSG_GATE_HIANY_FROM', 'radar'):
        r = hiany_reason(text)
        if r:
            reasons.append(r)

    if reasons:
        for r in reasons:
            print('  - ' + r, file=sys.stderr)
        return 3
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
