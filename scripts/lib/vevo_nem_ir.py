#!/usr/bin/env python3
"""vevo_nem_ir.py -- "the buyer does not write": the words that may not stand in Marabel material.

Card 42b5e28a (Klodel 41486). Patrik, private TG on 2026-11-13, word for word:
  TG 18398 "pont h nem irja mert ezt nem kell írni" (a video concept had mum writing in the book),
  TG 18401 "nem ragasztgatunk képet nem irogat kézzel" (it had a glued-in photo),
  TG 18412 "de nehogy megtévesztő legyen h itt ragasztgatni kell meg kézzel írni ne tegyél bele olyan könyvet"
           (the "old way" contrast with an empty baby journal and a pen was misleading too).
So in Marabel material none of these appear, also not as a contrast ("nem kell kézzel írni"): a pen, glue or
gluing a photo in, handwriting / writing by hand, writing in the book, journaling ("naplóz", "naplót vezet"),
another (empty, fill-in) baby journal. hibanapló 2026-11-13 L308-L310.

Used by scripts/lib/msg_gate.py (rule 7, briefs) and scripts/hooks/product-image-gate.py (the image .ok sheet).
Matching is on folded text (NFKC, accents dropped, lower case, zero-width characters dropped). Two things are
cut out before matching, and nothing else:
  - a quote ("...", „...”) on a line that names a Telegram message ("TG 18395"): Patrik's request is quoted word
    for word by rule (msg_gate rule 5), and his words were "a könyv ahogy naplóz anya benne" (TG 18395);
  - a line that starts with "TILOS:": the place to name what may not appear ("TILOS: toll, ragasztó").
Word forms were narrowed on 30 days of real traffic (2026-11-13, 4439 messages from the material briefers to the
producers): "naplózva", "naplózd" (logging), "kézirat" (manuscript), "ráragasztottnak hat" (an image flaw),
"ragasztott kötés" (binding) and a bare "babanapló" (Patrik's own SEO keyword, TG 17883) do not count.
Measured on the same 30 days: 36 briefs would stop, 23 of the refused kind, 13 the price of "no exception"
(numbers in msg_gate.py rule 7); of the 577 image .ok sheets 5 stop (3 contrasts, 2 a grandmother's handwritten
recipe book). Known limit: "toll" is also a feather (Pamacs is an owl): write "tollazat".
Test: scripts/lib/vevo_nem_ir_test.py
"""
import re
import unicodedata

_ZW = dict.fromkeys(map(ord, '​‌‍⁠﻿­'))
_L = r'(?<![a-z-])'

TERMS = (
    ('toll', re.compile(r'(?:' + _L + r'|golyos|tolto|filc)toll(?:al|at|ak|akat|ok|ban|ba|ra|rol|bol|hoz|nak|unk|unkat)?'
                        r'(?![a-z])')),
    ('ragasztó / ragasztás', re.compile(
        r'ragasztgat|ragaszto(?!t)|(?<!ra)(?:be|fel)ragaszt'
        r'|ragaszt\w*\s+(?:\w+\s+){0,2}(?:foto|kep)|(?:foto|kep)\w*\s+(?:\w+\s+){0,2}(?:be|fel)?ragaszt')),
    ('kézírás / kézzel ír', re.compile(_L + r'kezira(?:s|so)|kezzel\s+(?:\w+\s+)?(?:bele|be|at)?ir(?!at)|kezzel\s+irhato')),
    ('ír a könyvbe', re.compile(
        r'(?<![a-z])(?:bele|be)?ir(?:ja|od|om|unk|jak|nak|ni|sz)?\s+(?:bele\s+)?(?:a\s+)?(?:\w+\s+)?(?:baba|emlek)?konyv(?:be|et|unket)'
        r'(?![a-z])|konyvbe\s+(?:bele|be)?ir')),
    ('naplóz / naplót vezet', re.compile(_L + r'naploz(?:ik|ni|nak|ok|unk|sz|gat\w*)?(?![a-z])|naplot\s+vezet')),
    ('más (üres) babanapló', re.compile(
        r'(?<![a-z])(?:ures|kitoltos|kitoltendo|mas|papir|hagyomanyos)\s+(?:baba)?(?:naplo|emlekkonyv|konyv)')),
)

# A message is about material when it names a format of it (video, reel, post, ad, film, concept, scene...).
MATERIAL = re.compile(r'(?<![a-z])(?:video|reel|poszt|hirdet|film|kisfilm|koncepci|vizual|jelenet|plakat|carousel|story'
                      r'|short|tiktok|storyboard|forgatokonyv|snitt|termekkep|hirdeteskep)')

_QUOTE = re.compile(r'["„“”][^"„“”\n]{1,600}["“”]')
_TG = re.compile(r'(?<![a-z])tg\s*#?\s*\d+')
_TILOS = re.compile(r'^\s*tilos\s*:')


def fold(text):
    t = unicodedata.normalize('NFKC', str(text)).translate(_ZW)
    return ''.join(c for c in unicodedata.normalize('NFKD', t) if not unicodedata.combining(c)).lower()


def checked_text(folded):
    """The folded text without Patrik's quoted words (on a TG line) and without TILOS: lines."""
    out = []
    for line in folded.splitlines():
        if _TILOS.match(line):
            continue
        if _TG.search(line):
            line = _QUOTE.sub(' ', line)
        out.append(line)
    return '\n'.join(out)


def found(text):
    """The labels of the forbidden words in the text, in TERMS order (empty: clean)."""
    body = checked_text(fold(text))
    return [label for label, rx in TERMS if rx.search(body)]


def is_material(text):
    return MATERIAL.search(fold(text)) is not None


def reason(labels, where):
    return ('vevő-nem-ír kapu (Patrik TG 18398, 18401, 18412: "nem ragasztgatunk képet nem irogat kézzel"): %s %s. '
            'Marabel-anyagban ezek kontrasztként sem szerepelhetnek: a vevő mesél vagy fotót küld, a szöveg és a fotó '
            'magától kerül a könyvbe. Patrik szavai idézőjelben a TG-sorban, a tiltás egy "TILOS:" sorban maradhat.'
            % (where, ', '.join(labels)))
