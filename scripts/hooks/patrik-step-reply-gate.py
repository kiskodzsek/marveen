#!/usr/bin/env python3
"""PreToolUse gate (telegram reply): a step put on the owner goes out only after the team measured there is no
internal route.

Why (Klodel 41154; hibanapló 2026-11-13 18:36, second occurrence): Patrik, group TG 6049: "Idiota". TG 6048 put the
Kiemelés button on Patrik although an internal route existed (the video upload through Kernel's
meta-video-url-feltoltes skill); the first occurrence was TG 17727 (card baf41075, Klodel 40533).

What blocks (exit 2): a reply into one of the owner's chats (store/projektek.json elo_uzenet "privat" / "csoport", or
MARVEEN_OWNER_CHATS) whose text puts a step on the reader ("nyomd meg", "te nyomod", "kattints", "lépj be",
"töltsd fel", "te indítod", "futtasd", "másold be", "a gépnél" ...), unless the agent took a fresh PATRIK-LEPES
reply mark for the chat right before (scripts/reply-mark.py PATRIK-LEPES --chat <chat> "<value>"). The value must
name who measured that there is no internal route and the msg_id of that measurement: another fleet agent's name
(<install>/agents/<name>/, or the main agent id; not the writer's own, Viktor 41257 LOW 2) and a 4-7 digit id that is a
row of the inter-agent queue (store/claudeclaw.db agent_messages) from the last 7 days with that agent as its sender or
recipient: the mark is a reference, not a claim. One mark = one message (scripts/lib/reply_marks.py).
A step about signing in (the unquoted text names belépés / bejelentkezés / login / hitelesítés / auth / sign in;
hibanapló 2026-11-16 09:31, Patrik TG 6174, second occurrence after TG 17727): the mark also has to say that a probe
with the EXISTING sign-in failed (an "existing" word and a failure word, not negated), and the referenced queue row has
to report that failed sign-in probe itself (a sign-in word and a failure word in its content). A team claim ("the fleet
token is not allowed") is not a probe. Word matching: an accident guard against a skipped measurement, not a proof.
Viktor 7c4bd122 (card 540745fa): the topic includes the separable-prefix forms ("Be kell lépned", "lépj már be") and
log in / authenticate, not "signing" / "belépő" / "belépett" / "hitelesített"; the failure and its sign-in (or
"existing") word have to stand in one sentence, and a negation after the failure word ("hiba nélkül", "a 401 megszűnt")
or a few words before it ("nem volt hiba", "0 hiba") cancels it. A password or 2FA step is deliberately not a sign-in
topic: for a NEW service there is no existing sign-in to probe, so the rule would block it with no way through.
Viktor 48105 (round 2): a sentence ends only at [.!?;] before a space or the end, or at a line break ("(v2.1.3): 401",
"claude.ai" stay one sentence); "lépésenként", "lépcsőzetesen", "jelentkezését" are no sign-in; a post-verb negation
("hibát nem kaptunk", "401-et nem adott", "egy 401-et sem kaptunk") and "semmi(lyen)" cancel the failure word.
Known limits: a no-failure wording with a bare failure noun ("az error log üres") still reads as a failure, and a probe
reported over two sentences ("Lefuttattam ... a meglévő belépéssel. 401-et adott.") does not count: the price of the
one-sentence rule, which keeps "A Vercel deploy elbukott. Külön téma: a belépés rendben van." from passing.
Card c4f0b5bb (Viktor 7c4bd122 HOLE-OLD): a step also when up to three words stand between the verb and "be" ("lépj
már végre be", "jelentkezz már be"), in the conditional ("Lépnél be újra?"), in English ("Please log in again") and
for "engedélyezd". Known limit (Viktor 48114 I2): a quoted or negated FAIL_OWN phrase ("nincs not logged in", 29552)
still reads as a failure in the mark and the queue-row check; kept on purpose (a quality gate, not a security border).
The owner's chats unknown (no MARVEEN_OWNER_CHATS, store/projektek.json unreadable or of another shape): the gate
passes and says so on stderr, once per call (Viktor 41257 MEDIUM).
Passes: a negated sentence ("nem kell nyomnod", "ne töltsd fel"), past tense ("megnyomtad", "feltöltöttük": no
trigger), a quoted text („...”: customer copy in te-form goes in quotes), a sentence addressed to Balázs (balazs-task-reply-gate.py owns that), edits
(edit_message: the live status message lists what waits on whom by design), other chats, unreadable input.
Wiring: .claude/settings.json PreToolUse, matcher "mcp__plugin_telegram_telegram__reply".
Tests: patrik-step-reply-gate_test.py next to this file.
"""
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'lib'))
INSTALL = os.path.dirname(os.path.dirname(HERE))
# CLAUDE_PROJECT_DIR is what the hook command itself runs from ("$CLAUDE_PROJECT_DIR/scripts/hooks/..."): in
# production the same directory as INSTALL; tests point it at a throwaway root with its own store/projektek.json.
ROOT = os.environ.get('CLAUDE_PROJECT_DIR') or INSTALL
STORE = os.path.join(ROOT, 'store')
MSG_MAX_AGE_S = 7 * 86400

INVISIBLE = re.compile('[­᠎​-‏‪-‮⁠-⁤﻿]')
QUOTED = re.compile(r'„[^”\n]*”|“[^”\n]*”|"[^"\n]*"|»[^«\n]*«|«[^»\n]*»')
URL = re.compile(r'https?://\S+')
SENTENCE = re.compile(r'[.!?;\n]+')

# Second-person steps (imperative, "te ...-od", "... kell -ned"). Past tense and first person plural ("megnyomtad",
# "feltöltjük") are deliberately absent: they report, they do not ask.
STEP = re.compile(r'(?<!\w)(?:' + '|'.join([
    r'nyomd\s+(?:meg|rá|le|be)', r'nyomj\s+(?:rá|egy)', r'(?:meg)?nyomod', r'(?:meg)?nyomnod\s+kell',
    r'kattints(?:d|\s+rá)?', r'(?:rá)?kattintasz', r'kattintanod\s+kell',
    r'lépj\s+be', r'jelentkezz\s+be', r'(?:be)?lépsz(?:\s+be)?', r'be\s+kell\s+(?:lépned|jelentkezned)',
    # card c4f0b5bb (Viktor 7c4bd122 HOLE-OLD): up to three words between the verb and "be", the conditional form
    r'(?:lépj|lépnél|jelentkezz|jelentkeznél)(?:\s+\w+){1,3}?\s+be', r'(?:lépnél|jelentkeznél)\s+be',
    r'please\s+(?:log|sign)[\s-]?in', r'^\s*(?:log|sign)[\s-]?in\s+again',  # imperative only at sentence start
    r'engedélyezd', r'engedélyezned\s+kell',
    r'töltsd\s+(?:fel|le)', r'tölts\s+fel', r'(?:fel|le)töltöd', r'töltöd\s+(?:fel|le)',
    r'(?:fel|le)\s+kell\s+töltened',
    r'indítsd(?:\s+el)?', r'(?:el)?indítod', r'el\s+kell\s+indítanod',
    r'futtasd(?:\s+le)?', r'(?:le)?futtatod', r'futtass',
    r'másold\s+(?:be|át|ki)', r'illeszd\s+be', r'írd\s+be', r'gépeld\s+be',
    r'add\s+meg\s+(?:a\s+)?(?:jelszót?|kódot?|tokent?)',
    r'telepítsd(?:\s+fel)?', r'(?:fel)?telepíted',
    r'kapcsold\s+(?:be|ki)', r'állítsd\s+be',
    r'a\s+gépnél(?!-)',  # not the noun compound "gépnél-lista" (measured: 3 of 105 hits, 7 days)
]) + r')(?!\w)', re.IGNORECASE)
NEGATION = re.compile(r'(?<!\w)(?:nem|ne|se|sem|nincs|nélküled)(?!\w)', re.IGNORECASE)
NEG_WINDOW_WORDS = 4
MSG_ID = re.compile(r'(?<!\d)\d{4,7}(?!\d)')

# A step about signing in (hibanapló 2026-11-16 09:31, Patrik TG 6174: "be van lépve már mindegiyk claude és codex is
# most is azookon futtok nem értem a kérést"; second occurrence after TG 17727). On folded text (no accents, lower).
# Viktor 7c4bd122 (card 540745fa): L1 the separable-prefix forms ("Be kell lépned", "lépj már végre be", "Lépnél be
# újra?"), log in / authenticate; L3 not "signing", "belépő" (a ticket), "belépett", "hitelesített" (a certified copy).
LOGIN_TOPIC = re.compile(
    r'(?<![a-z])(?:belep(?!o|ett)|bejelentkez|hitelesit(?!ett)|autentik|o?auth(?![a-z])|authenticat[a-z]*'
    r'|login|log[\s-]?in(?![a-z])|sign[\s-]?in(?![a-z])|setup-token'
    r'|be\s+(?:kell(?:ene)?\s+|tudsz\s+|tudnal\s+)?(?:lep(?!es|cso)|jelentkez(?!es|o))[a-z]*'
    r'|(?:lepj|lepnel|lepsz|lepjel|jelentkezz|jelentkeznel|jelentkezzel)[a-z]*\s+(?:[a-z]+\s+){0,3}be(?![a-z]))')
# The probe with the existing sign-in failed. Folded text. A failure word right after a negation ("nem bukott el",
# "not failed", "nem volt hiba", "nem adott 401-et", "0 hiba") or right before one ("hiba nélkül", "a 401 megszűnt")
# does not count; "nem működik" / "nem megy" / "nem sikerült" are failure phrases of their own (Viktor 7c4bd122 L2, L3).
FAIL_OWN = re.compile(r'(?<![a-z])(?:nem\s+mukodik|nem\s+megy|nem\s+sikerult|nem\s+ment\s+at|not\s+logged\s+in|nincs\s+belepve)'
                      r'(?![a-z])')
FAIL_WORD = re.compile(r'(?<![a-z0-9])(?:elbuk\w*|bukott\w*|hibas?|hibat|hibaval|401|403|failed|failure|'
                       r'authentication_failed|unauthorized|lejart\w*|expired|invalid|sikertelen\w*|(?:vissza|el)utasit\w*|'
                       r'rejected|denied|error\w*)(?![a-z0-9])')
FAIL_NEGATED = re.compile(r'(?:(?<![a-z])(?:nem|not|no|sem|nincs|never|without)\s+(?:el\s+|volt\s+(?:[a-z]+\s+)?|adott\s+|kaptam\s+'
                          r'|kaptunk\s+|kapott\s+|jott\s+|lett\s+)?(?:semmi(?:lyen)?\s+|egy\s+)?|(?<![a-z])semmi(?:lyen)?\s+'
                          r'|(?<![\d.])0\s+)$')
FAIL_POSTNEG = re.compile(r'^(?:-?[a-z]{0,4})?\s+(?:nelkul|megszunt\w*|elmult|sem|nem\s+(?:jott|kaptunk|kaptam|kapott|adott|volt'
                          r'|dobott|jelzett))(?![a-z])')
EXISTING = re.compile(r'(?<![a-z])(?:meglev\w*|mostani\w*|jelenlegi\w*|existing|current|flotta\w*|fleet)(?![a-z])')


def has_failure(text_folded):
    """A failed-probe statement in folded text, not negated."""
    if FAIL_OWN.search(text_folded):
        return True
    for m in FAIL_WORD.finditer(text_folded):
        if FAIL_NEGATED.search(text_folded[max(0, m.start() - 28):m.start()]):
            continue
        if FAIL_POSTNEG.search(text_folded[m.end():m.end() + 24]):
            continue
        return True
    return False


SENTENCE_END = re.compile(r'[.!?;]+(?=\s|$)|\n+')


def sentence_with(text_folded, *checks):
    """Whether ONE sentence of the folded text passes every check (Viktor 7c4bd122 L2: "A Vercel deploy elbukott.
    Külön téma: a belépés rendben van." is no failed sign-in)."""
    return any(all(c(s) for c in checks) for s in SENTENCE_END.split(text_folded))


def login_topic(text):
    """Whether the unquoted text is about signing in (belépés, login, hitelesítés ...)."""
    t = INVISIBLE.sub('', unicodedata.normalize('NFKC', str(text or '')))
    return bool(LOGIN_TOPIC.search(fold(URL.sub(' ', QUOTED.sub(' ', t)))))


def fold(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c)).lower()


def owner_chats():
    """The owner's chats (same rule as patrik-reply-volume-gate.py): MARVEEN_OWNER_CHATS, else projektek.json."""
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


def step_phrase(text):
    """The first step the text puts on the reader, or None."""
    t = INVISIBLE.sub('', unicodedata.normalize('NFKC', str(text or '')))
    t = URL.sub(' ', QUOTED.sub(' ', t))
    for sentence in SENTENCE.split(t):
        low = fold(sentence)
        if 'balazs' in low and 'patrik' not in low:
            continue
        for m in STEP.finditer(sentence):
            before = sentence[:m.start()].split()[-NEG_WINDOW_WORDS:]
            if any(NEGATION.fullmatch(w.strip(',:()')) for w in before):
                continue
            return m.group(0).strip()
    return None


def agent_names():
    names = set()
    d = os.environ.get('MARVEEN_AGENTS_DIR') or os.path.join(ROOT, 'agents')
    try:
        for n in os.listdir(d):
            if os.path.isdir(os.path.join(d, n)) and re.fullmatch(r'[a-z][a-z0-9_-]{1,30}', n):
                names.add(n)
    except OSError:
        pass
    try:
        import ledger_lib
        main = ledger_lib.main_agent_id()
        if main:
            names.add(fold(main))
    except Exception:
        pass
    return names


def value_problem(value, names, writer='', now=None, login=False):
    """Why a PATRIK-LEPES value does not name the measurement, or None. The value must name ANOTHER fleet agent and a
    msg_id that is a queue row of the last 7 days with that agent as sender or recipient.
    login=True (the step is about signing in): the value must also say that a probe with the EXISTING sign-in failed,
    and the referenced queue row must itself report a failed sign-in probe (a sign-in word and a failure word)."""
    v = fold(value or '')
    ids = [int(x) for x in MSG_ID.findall(v)]
    if not ids:
        return 'nincs benne a mérés msg_id-je (4-7 jegyű szám)'
    if login and not sentence_with(v, EXISTING.search, has_failure):
        return ('belépésről szól, de nem mondja ki, hogy a MEGLÉVŐ belépéssel mért próba elbukott (pl. "pulzus 43901: '
                'a meglévő belépéssel claude -p: 401")')
    words = set(re.findall(r'[a-z0-9_-]+', v))
    named = (words & names) - {fold(writer or '')}
    if not named:
        return ('nem nevez meg MÁSIK csapattagot (ki mérte: ' + ', '.join(sorted(names - {fold(writer or '')}))
                + '; a saját neved nem mérés)')
    now = time.time() if now is None else now
    try:
        import ledger_lib
        con = sqlite3.connect(f'file:{ledger_lib.db_path()}?mode=ro', uri=True, timeout=5)
        try:
            rows = con.execute(
                'SELECT from_agent, to_agent, created_at, content FROM agent_messages WHERE id IN (%s)'
                % ','.join('?' * len(ids)), ids).fetchall()
        finally:
            con.close()
    except Exception:
        return 'az üzenetsor nem olvasható, a msg_id nem ellenőrizhető'
    party = False
    for frm, to, at, content in rows:
        if (fold(str(frm)) in named or fold(str(to)) in named) and isinstance(at, int) and 0 <= now - at <= MSG_MAX_AGE_S:
            party = True
            if not login:
                return None
            c = fold(str(content or ''))
            if sentence_with(c, LOGIN_TOPIC.search, has_failure):
                return None
    if party:
        return ('a hivatkozott üzenet (' + ', '.join(map(str, ids)) + ') nem elbukott belépés-próbáról szól (nincs '
                'benne belépés-szó és hiba-szó); előbb mérd meg a meglévő belépéssel')
    return ('a msg_id (' + ', '.join(map(str, ids)) + ') nem olyan 7 napon belüli üzenet az üzenetsorban, amelynek '
            + ' vagy '.join(sorted(named)) + ' a feladója vagy címzettje')


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    tool = str(payload.get('tool_name') or '')
    if tool and not tool.endswith('__reply'):
        return 0
    ti = payload.get('tool_input')
    if not isinstance(ti, dict) or not ti.get('chat_id'):
        return 0
    chat = str(ti['chat_id']).strip()
    chats = owner_chats()
    if not chats:
        print('patrik-step-reply-gate: the owner\'s chats are unknown (MARVEEN_OWNER_CHATS / store/projektek.json '
              'elo_uzenet); the gate is off.', file=sys.stderr)
        return 0
    if chat not in chats:
        return 0
    phrase = step_phrase(ti.get('text', ''))
    if not phrase:
        return 0
    try:
        import ledger_lib
        import reply_marks
        agent = ledger_lib.agent_id_from_payload(payload) or ledger_lib.main_agent_id()
        reply_marks.bind_call(payload)
        value = reply_marks.take('PATRIK-LEPES', chat, agent)
    except Exception:
        agent, value = '', None
    head = (f'LÉPÉS-KAPU (Patrik TG 6049 „Idiota”, TG 17727; Klodel 41154): a szöveg Patrikra tesz teendőt '
            f'(„{phrase}”). ')
    how = ('Előbb mérd meg, van-e belső út (csapattag, skill, API); ha nincs, jelöld előtte (a szövegbe nem kerül): '
           'python3 -I scripts/reply-mark.py PATRIK-LEPES --chat <privat|csoport> "<ki mérte> <msg_id>: <miért nincs '
           'belső út>" (a msg_id a csapattag 7 napon belüli üzenete az üzenetsorban). Belépésről szóló lépésnél a jel és a '
           'hivatkozott üzenet is mondja ki, hogy a MEGLÉVŐ belépéssel mért próba elbukott (TG 6174). Ha nem neki szól, írd át („mi feltöltjük”); vevőnek szóló szöveg (poszt, hirdetés) „...” közé.')
    if value is None:
        print(head + how, file=sys.stderr)
        return 2
    problem = value_problem(value, agent_names(), agent, login=login_topic(ti.get('text', '')))
    if problem:
        print(head + f'A PATRIK-LEPES jel {problem}. ' + how, file=sys.stderr)
        return 2
    if not reply_marks.spend_pending():
        print('LÉPÉS-KAPU: a PATRIK-LEPES jel közben elfogyott (egy jel = egy üzenet); jelölj újra.', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
