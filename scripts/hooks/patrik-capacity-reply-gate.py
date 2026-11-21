#!/usr/bin/env python3
"""PreToolUse gate (telegram reply): a proposal of more paid AI capacity (a new account, seat, subscription, plan or
credit, or options for a running-out team quota) goes to the owner only after a teammate measured the existing quotas.

Why (card 13909285, retro 2026-11-20 R6; hibanapló 2026-11-16 11:15, third occurrence of an internal choice put
before Patrik): group TG 6198 told Patrik the team's weekly quota runs out and put "three options with prices" before
him (a third account, 180 EUR/month, signal card c8618be2), although nobody had measured how much heavy work Dave's
own seat (10 % used that week) could take. Patrik, TG 6199: "Van masik keret amire at tudunk allni.. plusz dave sajat
kerete is". patrik-decision-reply-gate.py did not stop it: its words do not cover "egy döntés vár rád", and its
"penz" reason would have let a capacity purchase through anyway. That gate asks WHY only Patrik can decide; this one
asks WHETHER the internal route was measured first.

What blocks (exit 2): a reply into one of the owner's chats (store/projektek.json elo_uzenet "privat" / "csoport", or
MARVEEN_OWNER_CHATS) where one sentence of the unquoted text (a ';' does not end it) names AI capacity (CAPACITY: keret with a quota word -
heti / 5 órás / csapat / flotta / Claude / Codex ... -, or a seat / subscription / plan / account / credit of an AI
provider) AND offers more of it or options for it (OFFER: javaslat, lehetőség, opció, vegyünk, vásárlás, előfizetés,
bővítés, upgrade, új / harmadik / további fiók, a price per month, "döntés vár"), unless the agent took a fresh
BELSO-UT-MERVE reply mark for the chat right before (scripts/reply-mark.py BELSO-UT-MERVE --chat <chat> "<value>").
The value must name ANOTHER fleet agent and a 4-7 digit msg_id that is a row of the inter-agent queue (agent_messages)
of the last 7 days with that agent as sender or recipient, and that row must itself report a quota measurement: in one
sentence a quota word (keret, seat, hely, fiók, quota, limit) and a percentage ("7d 25 %", "heti 10 %"). A team claim
without a number is not a measurement. One mark = one message (scripts/lib/reply_marks.py).
Word matching: an accident guard against a skipped measurement, not a proof; whoever writes a false row passes.
Passes: a negated offer ("új fiókot nem indítok", "nem kell új előfizetés"), a quoted text („...”), a sentence
addressed to Balázs only, edits (edit_message: the live status message), other chats, unreadable input. The owner's
chats unknown: the gate passes and says so on stderr (as patrik-step-reply-gate.py).
Wiring: .claude/settings.json PreToolUse, matcher "mcp__plugin_telegram_telegram__reply|...edit_message" (edits pass
here by the tool-name check). Tests: patrik-capacity-reply-gate_test.py next to this file.
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
ROOT = os.environ.get('CLAUDE_PROJECT_DIR') or INSTALL
STORE = os.path.join(ROOT, 'store')
MSG_MAX_AGE_S = 7 * 86400

INVISIBLE = re.compile('[­᠎​-‏‪-‮⁠-⁤﻿]')
QUOTED = re.compile(r'„[^”\n]*”|“[^”\n]*”|"[^"\n]*"|»[^«\n]*«|«[^»\n]*»')
URL = re.compile(r'https?://\S+')
SENTENCE_END = re.compile(r'[.!?;]+(?=\s|$)|\n+')
# The offer check keeps a ';' clause in its sentence: "A heti keret holnap betelik; két lehetőség árral ..." is one
# offer split by a semicolon (re-measured on the same 3826 messages: still 1 hit, TG 6198).
OFFER_SENTENCE_END = re.compile(r'[.!?]+(?=\s|$)|\n+')

# On folded text (no accents, lower). A quota "keret" needs its quota word: "hirdetési keret", "fal-keret" and
# "STOP_AT_USD keret" are money ceilings Patrik already owns, not capacity.
PROVIDER = r'(?:claude|codex|anthropic|openai|chatgpt|fable|opus|sonnet)'
# Measured on 21 days of outbound owner-chat messages (3826, 2026-11-21): a bare "új fiók" is a Marabel customer
# sign-up, "napi keret" an ad budget, "kredit" a music credit or Higgsfield, so capacity has to be tied to an AI
# provider or to a quota keret (heti, 5 órás, csapat, flotta).
CAPACITY = re.compile(r'(?<![a-z0-9])(?:' + '|'.join([
    r'(?:heti|5\s*oras|otoras|csapat\w*|flotta\w*|fleet|' + PROVIDER + r'[\s-]*)\s*keret\w*',
    r'keret\w*\s+(?:a\s+)?(?:heten\s+|ma\s+ejjel\s+|holnap\s+)?(?:elfogy|betel|kifut)\w*',
    r'(?:elfogy|betel|kifut)\w*\s+(?:a\s+)?(?:csapat\w*\s+|heti\s+|flotta\w*\s+)keret\w*',
    PROVIDER + r'[\s-]*(?:fiok|helye?|seat|plan|csomag|elofizetes|kredit|credit)\w*',
    r'(?:max|team|pro)\s+(?:' + PROVIDER + r'[\s-]*)(?:csomag|plan|elofizetes|seat)\w*',
    r'(?:claude|anthropic)\s+(?:max|team|pro)\w*', r'extra\s+usage',
    r'(?:harmadik|negyedik|otodik|tovabbi|plusz)\s+(?:' + PROVIDER + r'[\s-]*)?(?:fiok|seat|elofizetes)\w*',
]) + r')(?![a-z0-9])')
OFFER = re.compile(r'(?<![a-z0-9])(?:' + '|'.join([
    r'javasl\w*', r'vegyunk', r'vegyuk', r'vasarol\w*', r'vasarlas\w*', r'megvesz\w*', r'megvenn\w*',
    r'elofizet(?:unk|ni|nenk|nel|nek|ned)', r'bovit\w*', r'upgrade\w*',
    r'(?:harmadik|negyedik|otodik|tovabbi|plusz)\s+(?:fiok|seat|elofizetes)\w*',
    r'dontes\w*\s+var', r'var\s+(?:egy\s+|ra\w*\s+)?dontes\w*',
    r'lehetoseg\w*\s+arral', r'opcio\w*\s+arral', r'arral',
    r'\d[\d\s.,]*\s*(?:eur|usd|\$|ft)\s*/\s*(?:ho|honap|month|mo)', r'(?:eur|usd|\$)\s*\d[\d.,]*\s*/\s*(?:ho|honap|month|mo)',
]) + r')(?![a-z0-9])')
NEGATION = re.compile(r'(?<![a-z])(?:nem|ne|se|sem|nincs|nelkul)(?![a-z])')
NEG_WINDOW_WORDS = 4
MSG_ID = re.compile(r'(?<![\d#])\d{4,7}(?!\d)')
# The referenced queue row has to carry the measurement: a quota word and a percentage in one sentence.
ROW_QUOTA = re.compile(r'(?<![a-z])(?:keret\w*|seat\w*|hely\w*|fiok\w*|quota\w*|limit\w*|7d|5h|seven_day|five_hour)(?![a-z])')
ROW_PCT = re.compile(r'(?<![\d.,])\d{1,3}(?:[.,]\d+)?\s*%')


def fold(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c)).lower()


def owner_chats():
    """The owner's chats (same rule as patrik-step-reply-gate.py): MARVEEN_OWNER_CHATS, else projektek.json."""
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


POST_NEG_WORDS = 2
# Only this many characters around a match are split for the negation words: splitting the whole sentence prefix at
# every match was quadratic (tools/redos-probe.py, 2026-11-21: 2.1 s on a 400 000-character ';'-joined text).
NEG_SCAN_CHARS = 200


def _negated(text, start, end=None):
    """A negation among the few words right before the match, or right after it ("új fiókot nem indítok", "kredit
    nem kell"), within its own clause."""
    lo = max(0, start - NEG_SCAN_CHARS)
    parts = re.split(r'[,:;()]|\s[-–]\s', text[lo:start])
    before = parts[-1].split()
    if lo and len(parts) == 1 and before and not text[lo - 1].isspace() and not text[lo].isspace():
        before = before[1:]  # a word cut by the window is not a word ("xnem" must not read as "nem")
    before = before[-NEG_WINDOW_WORDS:]
    if any(NEGATION.fullmatch(w.strip('.,:;!?()')) for w in before):
        return True
    if end is None:
        return False
    hi = end + NEG_SCAN_CHARS
    parts = re.split(r'[,:;()]|\s[-–]\s', text[end:hi])
    after = parts[0].split()
    if hi < len(text) and len(parts) == 1 and after and not text[hi - 1].isspace() and not text[hi].isspace():
        after = after[:-1]  # the word cut by the window ("nemzet" must not read as "nem")
    after = after[:POST_NEG_WORDS]
    return any(NEGATION.fullmatch(w.strip('.,:;!?()')) for w in after)


def capacity_offer(text):
    """(capacity phrase, offer phrase) of the first sentence that names AI capacity and, outside that phrase, offers
    more of it or a choice about it; or None. One sentence: a paragraph-wide pairing hit 27 of 3826 measured messages,
    nearly all false."""
    t = INVISIBLE.sub('', unicodedata.normalize('NFKC', str(text or '')))
    t = fold(URL.sub(' ', QUOTED.sub(' ', t)))
    for sent in OFFER_SENTENCE_END.split(t):
        if 'balazs' in sent and 'patrik' not in sent and not re.search(r'(?<![a-z])(?:te|neked|toled|rad)(?![a-z])', sent):
            continue
        caps = [m for m in CAPACITY.finditer(sent) if not _negated(sent, m.start(), m.end())]
        if not caps:
            continue
        for off in OFFER.finditer(sent):
            if _negated(sent, off.start(), off.end()):
                continue
            if any(c.start() < off.end() and off.start() < c.end() for c in caps):
                continue  # the offer word is the capacity phrase itself ("harmadik fiók" alone is not an offer)
            return caps[0].group(0).strip(), off.group(0).strip()
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


def row_is_measurement(content):
    c = fold(str(content or ''))
    return any(ROW_QUOTA.search(s) and ROW_PCT.search(s) for s in SENTENCE_END.split(c))


def value_problem(value, names, writer='', now=None):
    """Why a BELSO-UT-MERVE value does not reference a measurement of the existing quotas, or None."""
    v = fold(value or '')
    ids = [int(x) for x in MSG_ID.findall(v)]
    if not ids:
        return 'nincs benne a mérés msg_id-je (4-7 jegyű szám)'
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
            if row_is_measurement(content):
                return None
    if party:
        return ('a hivatkozott üzenet (' + ', '.join(map(str, ids)) + ') nem keret-mérés (nincs benne egy mondatban '
                'keret/hely/fiók-szó és százalék); előbb mérjétek meg a meglévő kereteket (pl. Kernel seat-check)')
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
        print('patrik-capacity-reply-gate: the owner\'s chats are unknown (MARVEEN_OWNER_CHATS / store/projektek.json '
              'elo_uzenet); the gate is off.', file=sys.stderr)
        return 0
    if chat not in chats:
        return 0
    hit = capacity_offer(ti.get('text', ''))
    if not hit:
        return 0
    try:
        import ledger_lib
        import reply_marks
        agent = ledger_lib.agent_id_from_payload(payload) or ledger_lib.main_agent_id()
        reply_marks.bind_call(payload)
        value = reply_marks.take('BELSO-UT-MERVE', chat, agent)
    except Exception:
        agent, value = '', None
    head = (f'KERET-KAPU (TG 6198/6199 „plusz dave sajat kerete is”, kártya 13909285): a szöveg AI-keretről szól '
            f'(„{hit[0]}”) és többet vagy választást ajánl („{hit[1]}”). ')
    how = ('Előbb mérjétek meg a meglévő kereteket és az átrendezést (Kernel: tools/quota/seat-check.py, '
           'quota-forecast.py); utána jelöld előtte (a szövegbe nem kerül): python3 -I scripts/reply-mark.py '
           'BELSO-UT-MERVE --chat <privat|csoport> "<ki mérte> <msg_id>: <mi mérve>" (a msg_id a csapattag 7 napon '
           'belüli üzenete, benne egy mondatban keret-szó és százalék). Ha nem ajánlasz, írd át („új fiókot nem '
           'indítunk”).')
    if value is None:
        print(head + how, file=sys.stderr)
        return 2
    problem = value_problem(value, agent_names(), agent)
    if problem:
        print(head + f'A BELSO-UT-MERVE jel {problem}. ' + how, file=sys.stderr)
        return 2
    if not reply_marks.spend_pending():
        print('KERET-KAPU: a BELSO-UT-MERVE jel közben elfogyott (egy jel = egy üzenet); jelölj újra.', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
