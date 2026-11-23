#!/usr/bin/env python3
"""msg_gate.py -- the pre-send gate of scripts/agent-msg.sh (card aba42256, DREAM 11-11).

    printf '%s' "$TEXT" | python3 -I scripts/lib/msg_gate.py --from <a> --to <b>

Exit 0: send. Exit 3: refused, the reasons are on stderr (names and counts only, never the matched
text). Any other exit: the gate itself failed, which is not a verdict on the text.

Rules:

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
   A question of fact is a request (card 8dd5c726, is_idea): "?" with mekkora, mennyi, mikor, hol, ...
   and no idea mark, conditional or choice form ("mennyiért adjuk?", "mennyit érne?" stay ideas).
   Known limits, by name: info-question-word-list, imperative-3sg-definite, imperative-2sg-short-d,
   hat-het, modal-infinitive, comparative, indicative-decision (pinned: agent-msg-send-gate.test.sh,
   "known limit", one row each). info-question-word-list: a question word off the list stays an idea;
   a plain question of fact meant as an idea ("milyen színű a borító?") passes as a request (Klodel's
   Kérés-kapu checks the brief). The choice is a verb form, so a decision asked in other words passes as
   a request too (Viktor 50775; measured: in Patrik's 30 days these shapes ask facts, "hol lehet
   szerkeszteni?", "mennyi kell utalni?"): imperative-3sg-definite -ja/-je ("ki vigye?", the indicative
   of most fact questions); imperative-2sg-short-d, -d after a consonant other than d s z gy ts ("kérd",
   "csináld"; "mi a gond?" has the same shape); hat-het, a -hat/-het verb ("mennyiért adhatom el?");
   modal-infinitive, kell / lehet / szabad / illik with an infinitive ("melyik verziót lehet kiküldeni?");
   comparative ("melyik a jobb?", "melyik éri meg?", "mi a legjobb ár?"); indicative-decision ("melyik
   borítóval indulunk?").
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

7. THE BUYER DOES NOT WRITE (card 42b5e28a, Klodel 41486; Patrik TG 18398, 18401, 18412; hibanapló 2026-11-13
   L308-L310): a video concept had mum writing in the book, a glued-in photo, then an "old way" contrast with an
   empty baby journal and a pen; Patrik: "nem ragasztgatunk képet nem irogat kézzel", and the contrast is
   misleading too. A text from VNI_FROM (default klodel, majsztro, magnes, mira: the material briefers) to VNI_TO
   (default dave, mira, magnes, majsztro: the producers) that names a material format (video, reel, poszt,
   hirdetés, film, koncepció, jelenet, ...) is refused when it holds a word of scripts/lib/vevo_nem_ir.py: toll,
   ragasztó / beragaszt, kézírás / kézzel ír, ír a könyvbe, naplóz / naplót vezet, üres / kitöltős / más
   babanapló. No exception for a contrast. Not checked: Patrik's own words quoted on a "TG n" line (rule 5 asks
   for them verbatim; TG 18395 says "naplóz") and a "TILOS:" line naming what may not appear. The word list
   failing to load is exit 4.
   Measured 2026-11-13 21:5x on 30 days (4439 messages briefer -> producer, 1702 about material): 36 would have
   been refused. 23 are the kind Patrik refused (mostly "nem kell kézzel írni / képet ragasztani / naplót
   vezetni", an empty journal and a pen in a scene). 13 are the known price of "no exception": a "kézzel írható
   oldal" product feature (3), a grandmother's handwritten recipe (2), competitor categories (3), process wording
   such as "kézzel beírt státuszsor" (3), a feather "toll" (1), a handwriting-like font (1); they pass reworded or
   on a TILOS: line.

8. A MEASURED TIME IN THE TEXT ITSELF (card fc1d5065; Viktor 40687, the second occurrence on 2026-11-13: a
   measured time one minute ahead went out in a message file written with the Write tool and sent on stdin). The
   PreToolUse time-claim-gate judges the command text, an @file payload and a "< file" redirect, but not a text
   piped in ("cat f | <sender> -") or built by a program. Here the text is judged as it is sent, every sender and
   recipient, against the clock at the send: the time-claim-gate's send-path rules are LOADED from
   scripts/hooks/time-claim-gate.py, not copied (its rule 1: a placeholder time, HH:Mx or HH:xx; its rule 5: a
   measured time 1-15 minutes after the current minute, with that rule's deadline, plan, estimate and UTC
   exceptions). The fix the refusal names: {{NOW}}, which the dashboard fills in with its own minute, or `date`
   right before the send. The file failing to load is exit 4. TIME_CLAIM_GATE_NOW (HH:MM) is that gate's test
   seam and works here too.
   Replayed 2026-11-13 on 7 days of agent_messages (9854 rows, each at its own created_at minute): 313 would have
   been refused (245 placeholders, 71 times ahead of the clock); since the hook's rule 5 went live (#263, 11-13
   21:05) 144 messages, 0 hits.

9. A TG MESSAGE ATTRIBUTED TO PATRIK THAT SOMEONE ELSE WROTE (Klodel 48538; hibanapló 2026-11-20, the second
   occurrence, the first 2026-11-11): Balázs's group message (TG 6582) was given to Patrik in a work order; the
   rule line in CLAUDE.md did not stop it. A text from PATRIKTG_FROM (default "klodel") is judged where it puts a
   TG number next to Patrik's name ("Patrik ... TG 6582", "Patrik csoport TG 6582", "(Patrik, TG 6533/6535)":
   "patrik" as a whole word, then up to 40 characters on the same line without . ! ?, then "TG <n>"; no other
   person's name -- balazs, eszter -- in between, and not "nem Patrik"; a range "TG 4451-4459" checks its two
   ends). Who wrote n comes from the Telegram plugin's sender log, <state>/inbound-senders.jsonl (and its .1):
   chat, message id, user id.
   A message id counts per chat, and the log starts 2026-11-11 at different heights (measured 11-20: the group
   from id 5475, Patrik's private chat from 17545), so the same number can be two messages:
   - "csoport" between the name and TG: the group rows (chat id < 0) with id n; "privat": the private rows.
   - neither: every row with id n, but a foreign one counts only if it is at most 3 days old (an old private
     message of Patrik's below 17545 may share the number with a group message).
   Refused: the rows that count are there and none is Patrik's. A Patrik row lets it through. No row that counts:
   sent, with a warning on stderr (agent-msg.sh shows it). Patrik's id is his private chat id
   (store/projektek.json elo_uzenet.privat, as the private-topic-group gate reads it; MARVEEN_OWNER_PRIVATE_CHAT
   overrides). The state dir is the main channel's (<install>/.claude/channels/telegram), not TELEGRAM_STATE_DIR
   (a sub-agent's points to its own). Not seen: the TG number first ("TG 6582 (Patrik)"), a suffixed name
   ("Patriknak", "Patriké"), a message the plugin did not log. No sender log or no owner id (an install without
   the Telegram channel): sent with a warning. Either one there but unreadable: exit 4.

Env (the suite uses them): MARVEEN_MSG_GATE_SECRET_SRC, MARVEEN_MSG_GATE_STRICT (comma list),
MARVEEN_MSG_GATE_MAX_CHARS, MARVEEN_MSG_GATE_OWN_DOMAINS (comma list), MARVEEN_MSG_GATE_STOP_FROM
(comma list), MARVEEN_MSG_GATE_SPEC_LOCK (path), MARVEEN_MSG_GATE_SPEC_FROM (comma list),
MARVEEN_MSG_GATE_KERES_FROM (comma list), MARVEEN_MSG_GATE_LEDGER (path), MARVEEN_MSG_GATE_HIANY_FROM (comma
list), MARVEEN_HIANY_ROOT (the install whose shared/ is read; default this repo), MARVEEN_MSG_GATE_VNI_FROM,
MARVEEN_MSG_GATE_VNI_TO (comma lists), TIME_CLAIM_GATE_NOW (HH:MM, rule 8), MARVEEN_MSG_GATE_PATRIKTG_FROM (comma
list), MARVEEN_MSG_GATE_TG_STATE (the plugin state dir), MARVEEN_MSG_GATE_PROJEKTEK (path),
MARVEEN_OWNER_PRIVATE_CHAT (Patrik's user id), rule 9.
"""
import json
import os
import pathlib
import re
import sqlite3
import sys
import time
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
# Viktor 41430 INFO 4: "esetleg", "szerintem", "mi van ha" too ("Esetleg csináld meg a borítót" passed without IGEN).
IDEA_MARKS = ('nenk', 'nank', 'hetne', 'hatna', 'elvileg', 'otlet', 'mi lenne', 'lehetne', 'kene', 'kellene',
              'erdemes', 'vajon', 'gondolkod', 'esetleg', 'szerintem', 'mi van ha', 'mi van, ha')
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


# Card 8dd5c726 (Klodel, 11-23): Patrik's information question is his request, not an idea. TG 18808 "kültéri
# konyha, mekkora piac?" asked a measurement; rule 5 read the "?" as ötletelés and wanted an IGEN, and the
# decision-reply gate refuses the "Így értem: ... Mehet?" that would have fetched it: a direct question took one more
# round with Patrik. A "?" sentence with a question word of fact (how big, how much, how many, when, where, from
# where, which, what kind, what is) is a request, unless it also holds an idea mark, a conditional verb or a form
# that asks him to choose. Measured on 30 days of his inbound '?' sentences (1831; measure_flip.py, card 8dd5c726):
# - "miért" is no question word here: "miért nem popup?", "logo-t miért nem?", "miért nem egységesítünk?" suggest;
# - a conditional stays an idea ("mekkora piac lenne?", TG 18802 "vhogy lehetne ... hogy tudnék beszállni?");
# - a choice stays an idea, it is his decision (product, money): "hány oldala legyen a receptkönyv?", "milyen üzletbe
#   kezdjünk?", "hány seat-et vegyek?";
# - a yes/no question has no question word and stays an idea ("Megcsinálod a borítót holnapra?");
# - "hogy" and "ki" are not question words (a conjunction, a verb prefix).
INFO_QUESTION = re.compile(_B + r'(?:mekkora|mennyi(?:be|t|re|ert|vel)?|hany(?:an|szor|at|adik|ra)?|mikor|hol|honnan|'
                           r'hova|milyen|melyik|mi\s+(?:a|az)|mik\s+(?:a|az))(?![a-z0-9])')
# Round 2 (Viktor 50740): a word list caught a few inflected forms only, so 14 choice and conditional questions read
# as requests ("mennyiért adjuk a könyvet?", "mikor küldjük ki?", "melyik közös élményt tennétek bele?", "mennyit
# érne?"). Both are grammatical shapes now (folded text: ö -> o, ü -> u):
# - a conditional verb: 2+ letters, "n", a conditional person ending: -na/-ne, -nák/-nék, -nám/-ném, -nál/-nél,
#   -nád/-néd, -nátok/-nétek ("érne", "csinálnál", "tennétek"); -nának/-nének is the -ák/-ék shape after
#   "n" ("adna" + n + ak), and -nánk/-nénk ("árulnánk") is an IDEA_MARK already (round-2 mutation: both
#   alternatives were equivalent, so they are not listed);
# - a choice (imperative / subjunctive): 2+ letters, the mood sign -j or its assimilated form (-zz, -ssz, -ss, -gy,
#   -ts: "árazzuk", "válasszam", "fizessük", "tegyük", "higgyük", "tanítsuk"; -ty and -ny of Viktor's
#   proposal are no mood sign of a verb, they only catch nouns such as "lányon"), a person ending: -uk/-ük, -unk/-ünk,
#   -ak/-ek, -am/-em, -on/-en/-ön, -atok/-etek ("adjuk", "kérjünk", "induljon", "menjen", "kezdjem"); the 3rd
#   person plural -janak/-jenek ("induljanak") ends in -nak/-nek and is caught by CONDITIONAL,
#   and -önk/-enk, Patrik's typo of -ünk (TG 17486 "milyen uzletbe kezdjonk?", named in round 1).
# Both over-catch: the dative and adessive -nak/-nek, -nál/-nél ("a csomagnak", "a gépnél"), the indicative
# "csináljuk" (we do it), a noun such as "hegyen", "hajón", "színe". An over-caught fact question stays an idea and
# wants an IGEN, the side the rule had before this card (Viktor 50740: "A túlfogás ... ötlet marad, az a régi,
# biztonságos oldal"). Not caught: the 3rd person definite imperative -ja/-je ("ki vigye?"): it is the indicative of
# most fact questions ("hol tartja?"); Known limit imperative-3sg-definite in the module header.
# Round 3 (Viktor 50775: 2nd person singular, -ddz, a one-letter stem read as requests): the choice also takes
# - the 2nd person singular long forms -jál/-jél, -jad/-jed ("kérjél", "küldjed"; also after the assimilated signs);
# - the assimilated sign -ddz of a stem in -dz ("eddzük") and a one-letter stem before -j, -gy, -ddz ("igyunk",
#   "együnk");
# - the bare short forms: a consonant + -j ("kérj", "adj", "csinálj") and -dd, -sd, -zd, -gyd ("küldd", "tedd",
#   "fizesd", "hozd", "hagyd"); -tsd ("tanítsd") ends in -sd (round-3 mutation: a -tsd alternative was equivalent).
# Measured on the 129 '?' sentences of Patrik's 30 days that round 2 reads as requests (work/keres-info-1123/r3/
# variants.py): the long forms turn 2 into ideas (the instrumental -ssal/-zzel: "prototípussal", "eszközzel"), -dd 1
# ("group add"), the rest 0. The short -d after any other consonant ("kérd", "csináld") would turn 4 ("mi a gond?",
# "majd"): Known limit imperative-2sg-short-d in the module header.
CONDITIONAL = re.compile(_B + r'(?:volna|[a-z]{2,}n(?:a|e|ak|ek|am|em|al|el|ad|ed|atok|etek))'
                         r'(?![a-z0-9])')
CHOICE = re.compile(_B + r'(?:(?:[a-z]{2,}(?:zz|ssz|ss|ts)|[a-z]+(?:j|gy|ddz))'
                    r'(?:uk|unk|onk|enk|ak|ek|am|em|on|en|atok|etek|al|el|ad|ed)'
                    r'|[a-z]*[bcdfghklmnpqrstvwxyz]j|[a-z]+(?:dd|sd|zd|gyd))'
                    r'(?![a-z0-9])')


def is_idea(sentence):
    if any(m in sentence for m in IDEA_MARKS):
        return True
    if '?' not in sentence:
        return False
    return not (INFO_QUESTION.search(sentence) and not CONDITIONAL.search(sentence) and not CHOICE.search(sentence))


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
        # as_uri() percent-encodes ? # %: pasted raw, a "?" in the path would end the file name and drop mode=ro
        # (Viktor 41430 INFO 1).
        con = sqlite3.connect(pathlib.Path(os.path.abspath(path)).as_uri() + '?mode=ro', uri=True, timeout=5)
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
    except BaseException as e:  # a missing or broken lint is a gate failure, never a silent pass
        # (BaseException: a hook file that calls sys.exit while it loads raised SystemExit past Exception and
        # turned every rule off, the secret rule too; Viktor 41626 LOW)
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


def vni_reason(text):
    """Rule 7: None, or the refusal reason when a material brief holds a buyer-writes word."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('_vevo_nem_ir', os.path.join(HERE, 'vevo_nem_ir.py'))
        vni = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vni)
    except BaseException as e:  # a missing or broken word list is a gate failure, never a silent pass
        # (BaseException: a hook file that calls sys.exit while it loads raised SystemExit past Exception and
        # turned every rule off, the secret rule too; Viktor 41626 LOW)
        die('scripts/lib/vevo_nem_ir.py does not load (%s)' % e.__class__.__name__)
    if not vni.is_material(text):
        return None
    labels = vni.found(text)
    return vni.reason(labels, 'a brief Marabel-anyagról szól, és benne van:') if labels else None


def time_reason(text):
    """Rule 8: None, or the refusal reason when the text holds a placeholder time or a measured time ahead of the
    clock (the time-claim-gate's send-path rules, loaded from the hook file)."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            '_time_claim_gate', os.path.join(HERE, '..', 'hooks', 'time-claim-gate.py'))
        tc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tc)
        now = tc._now()
        found = tc.findings(text, now, placeholder_only=True) + tc.send_findings(text, now)
    except BaseException as e:  # a missing or broken rule file is a gate failure, never a silent pass
        # (BaseException: a hook file that calls sys.exit while it loads raised SystemExit past Exception and
        # turned every rule off, the secret rule too; Viktor 41626 LOW)
        die('scripts/hooks/time-claim-gate.py does not load (%s)' % e.__class__.__name__)
    if not found:
        return None
    shown = ', '.join('%d. sor %s' % (n, tok) for n, tok, _ in found[:5])
    return ('idő-kapu (Viktor 40687, kártya fc1d5065): a szövegben %s, most %02d:%02d. Helykitöltő idő (óó:px) és '
            'az óránál későbbi mért idő nem mehet ki: írd {{NOW}}-t (a dashboard a beírás percére cseréli), vagy '
            'futtasd a date-et közvetlenül a küldés előtt.' % (shown, now.hour, now.minute))


# Rule 9. Matched on fold(text); the numbers after "TG" (a list with / , and a range's two ends). The words between
# the name and "TG" may name the chat: "csoport" (a group, chat id < 0) or "privat" (a private chat, chat id > 0).
# A second number may repeat "TG" or join with + ("TG 6537 és TG 6582", "TG 6537 + 6582"), and "TG: n", "TG-n" count
# (Viktor 48596 LOW 1, his tested form).
PATRIK_ATTR = re.compile(_B + r'patrik(?![a-z0-9])([^\n.!?]{0,40}?)' + _B
                         + r'tg\s*[:#-]?\s*(\d+(?:\s*(?:/|,|-|es|\+)\s*(?:tg\s*#?\s*)?\d+)*)')
# Another person, by first name, nickname or surname, with any suffix ("Balázsé", "Bazsi", "Tasnádi"; Viktor 48596 LOW 2);
# not the town "Esztergom" (Viktor 48660 INFO 1: "Patrik esztergomi útja TG 6582" read as a name).
_OTHER = r'(?:balazs|bazsi|tasnadi|eszter(?!gom))'
OTHER_PERSON = re.compile(_B + _OTHER + r'[a-z]*')
# After the number only a name BOUND to it names the sender (Viktor 48660 INFO 1: "Patrik TG 6582 kérte, Balázs is
# látta" or "..., szólok Balázsnak" dropped 6582 from the check): first in brackets "(Balázs)", "(Balázs üzenete)", the
# possessive "Balázsé",
# "Balázstól", or the name right before a verb of sending, "Balázs írta / küldte / kérte".
BOUND_OTHER = re.compile(r'\(\s*' + _OTHER + r'|' + _B + _OTHER + r'(?:e|tol)(?![a-z0-9])|' + _B + _OTHER
                         + r'\s+(?:irta|kuldte|kerte|jelezte|mondta|uzente)(?![a-z0-9])')
# Bounded (Viktor 48660 LOW 1, his prop.diff): an unbounded tail ran to the line end for every match, quadratic on a long
# line without punctuation (240k characters: 27.9 s).
SENTENCE_TAIL = re.compile(r'[^\n.!?]{0,300}')
NEXT_TG = re.compile(_B + r'tg\s*[:#-]?\s*\d')
# "Patrik nem írta a TG 6582-t, Balázs igen": Patrik is named as NOT its sender.
NEGATED_VERB = re.compile(_B + r'nem\s+(?:irta|kuldte|kerte|jelezte|mondta|uzente)(?![a-z0-9])')
GROUP_WORD = re.compile(_B + r'csoport')
PRIVATE_WORD = re.compile(_B + r'privat')
NOT_PATRIK = re.compile(_B + r'nem\s+[("\']?$')
BALAZS_USER_ID = '8366648365'  # the same constant as scripts/hooks/private-topic-group-gate.py
RECENT_SECONDS = 3 * 86400     # an unqualified reference is judged only against a message this fresh
DEFAULT_TG_STATE = os.path.join(HERE, '..', '..', '.claude', 'channels', 'telegram')
DEFAULT_PROJEKTEK = os.path.join(HERE, '..', '..', 'store', 'projektek.json')


def attributed_tgs(text):
    """[(n, scope)] the text puts next to Patrik's name, scope 'group' | 'private' | None, without repeats."""
    out = []
    folded = fold(text)
    for m in PATRIK_ATTR.finditer(folded):
        between = m.group(1)
        # "Balazs (nem Patrik), csoport TG ..." names the other sender: a negated name is no attribution
        if (OTHER_PERSON.search(between) or NEGATED_VERB.search(between)
                or NOT_PATRIK.search(folded[max(0, m.start() - 8):m.start()])):
            continue
        # "Patrik szerint a TG 6582 (Balázs) üzenet", "a TG 6582 viszont Balázsé": another person bound to the number,
        # in the same sentence, names its sender -- unless a TG number of their own follows ("Patrik TG 6537, (Balázs)
        # TG 6582": that name belongs to 6582, and 6537 stays checked).
        tail = SENTENCE_TAIL.match(folded, m.end()).group(0)
        if BOUND_OTHER.search(tail) and not NEXT_TG.search(tail):
            continue
        scope = 'group' if GROUP_WORD.search(between) else 'private' if PRIVATE_WORD.search(between) else None
        for n in re.findall(r'\d+', m.group(2)):
            if (n, scope) not in out:
                out.append((n, scope))
    return out


def patrik_user_id():
    """Patrik's user id, or None when this install does not record it (no store/projektek.json elo_uzenet.privat)."""
    env = os.environ.get('MARVEEN_OWNER_PRIVATE_CHAT', '').strip()
    if env:
        return env
    try:
        with open(os.environ.get('MARVEEN_MSG_GATE_PROJEKTEK', DEFAULT_PROJEKTEK), encoding='utf-8') as f:
            elo = (json.load(f) or {}).get('elo_uzenet') or {}
        priv = elo.get('privat')
        priv = priv.get('chat_id') if isinstance(priv, dict) else priv
    except FileNotFoundError:
        return None
    except (OSError, ValueError, AttributeError) as e:
        die("rule 9: Patrik's user id is unreadable (store/projektek.json elo_uzenet.privat): %s" % type(e).__name__)
    return str(priv).strip() if priv is not None and str(priv).strip().isdigit() else None


def tg_senders(wanted, now):
    """{message_id: [(chat_id, user_id, at_seconds)]} from the plugin's sender log (the file and its .1) for the
    wanted ids, only rows logged at or before now (the replay judges a message as it stood when it was sent);
    None when neither file exists (an install without the Telegram channel)."""
    base = os.path.join(os.environ.get('MARVEEN_MSG_GATE_TG_STATE', DEFAULT_TG_STATE), 'inbound-senders.jsonl')
    found, read_any = {}, False
    for path in (base + '.1', base):
        try:
            f = open(path, encoding='utf-8', errors='replace')
        except FileNotFoundError:
            continue
        except OSError as e:
            die('rule 9: the Telegram sender log is unreadable: %s (%s)' % (path, type(e).__name__))
        read_any = True
        with f:
            for ln in f:
                try:
                    row = json.loads(ln)
                    at = float(row.get('at')) / 1000.0
                except (ValueError, TypeError, AttributeError):
                    continue
                mid = str(row.get('message_id'))
                if mid in wanted and at <= now:
                    found.setdefault(mid, []).append((str(row.get('chat_id')), str(row.get('user_id')), at))
    return found if read_any else None


def patrik_tg_reason(text, now=None):
    """Rule 9: (refusal reason or None, warning or None)."""
    tgs = attributed_tgs(text)
    if not tgs:
        return None, None
    now = time.time() if now is None else now
    owner = patrik_user_id()
    senders = tg_senders({n for n, _ in tgs}, now)
    if owner is None or senders is None:
        return None, ('figyelmeztetés (9. szabály): a Patrik-hivatkozást (TG %s) nem tudtam ellenőrizni: %s.'
                      % (', '.join(n for n, _ in tgs),
                         'nincs Patrik-azonosító (store/projektek.json)' if owner is None else 'nincs feladó-napló'))
    wrong, unknown = [], []
    for n, scope in tgs:
        rows = senders.get(n, [])
        if scope == 'group':
            rows = [r for r in rows if r[0].startswith('-')]
        elif scope == 'private':
            rows = [r for r in rows if not r[0].startswith('-')]
        if any(u == owner for _, u, _ in rows):
            continue
        # Unqualified: a message id counts per chat, and the private chat's log starts above the group's ids, so an
        # old private message may share the number; only a fresh foreign message is taken as the one meant.
        if scope is None:
            rows = [r for r in rows if now - r[2] <= RECENT_SECONDS]
        if not rows:
            unknown.append(n)
            continue
        who = 'Balázs' if {u for _, u, _ in rows} == {BALAZS_USER_ID} else 'nem Patrik'
        wrong.append('TG %s (%s)' % (n, who))
    reason = warning = None
    if wrong:
        reason = ('Patrik-hivatkozás (9. szabály, hibanapló 11-20): %s a feladó-napló szerint nem Patrik üzenete. '
                  'Nevezd meg a valódi feladót (pl. "Balázs csoport TG <n>"), vagy hivatkozz Patrik saját '
                  'üzenetére.' % ', '.join(wrong))
    if unknown:
        warning = ('figyelmeztetés (9. szabály): TG %s Patrikhoz kötve, de a feladó-naplóban (inbound-senders.jsonl, '
                   '11-11 óta) nincs hozzá ellenőrizhető sor.' % ', '.join(unknown))
    return reason, warning


def guarded(label, rule, text):
    """Run a rule that calls into a loaded file. The loaders turn an import-time exit into die(), but the calls after
    the load (lint.root/lint.lint, vni.is_material/vni.found) ran outside them: a sys.exit(0) there returned rc 0 and
    the reasons gathered so far, the secret rule too, were lost (Viktor 41651 INFO, CWE-755; card 3629642f). Any
    SystemExit from a rule is a gate failure; die()'s own exit 4 passes through unchanged. Other exceptions already
    end the gate with rc 1, which agent-msg.sh refuses. Not caught: os._exit, which bypasses Python."""
    try:
        return rule(text)
    except SystemExit as e:
        if e.code == 4:
            raise
        die('%s: a loaded file exited while the rule ran (SystemExit %r); the gate cannot decide' % (label, e.code))


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
        r = guarded('hiany', hiany_reason, text)
        if r:
            reasons.append(r)

    if (frm.lower() in csv_env('MARVEEN_MSG_GATE_VNI_FROM', 'klodel,majsztro,magnes,mira')
            and to.lower() in csv_env('MARVEEN_MSG_GATE_VNI_TO', 'dave,mira,magnes,majsztro')):
        r = guarded('vevo-nem-ir', vni_reason, text)
        if r:
            reasons.append(r)

    r = guarded('time', time_reason, text)
    if r:
        reasons.append(r)

    warnings = []
    if frm.lower() in csv_env('MARVEEN_MSG_GATE_PATRIKTG_FROM', 'klodel'):
        r, w = patrik_tg_reason(text)
        if r:
            reasons.append(r)
        if w:
            warnings.append(w)

    if reasons:
        for r in reasons:
            print('  - ' + r, file=sys.stderr)
        return 3
    for w in warnings:
        print('  - ' + w, file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
