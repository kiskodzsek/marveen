#!/usr/bin/env python3
"""PreToolUse gate: no image/video goes to the owner on Telegram without a
written product-image check (TERMEKKEP-KAPU).

Why (Patrik, 2026-11-05 14:02, TG 1690/1694): scene images with a book that was
not A5-proportioned and had ecru/yellow paper were sent to him after a "Read"
review. He had flagged the same defect many times; the agent kept writing
"I should have caught it". He asked for a rule that makes it impossible to
happen again. A memory note did not stop it, so this is a hard gate.

How it works: every image/video in `files` of a telegram reply must have an
attestation file  store/kep-kapu/<basename>.ok  written AFTER the file's last
modification, containing ALL of these lines with a value:
    KONYV: van|nincs
    A5: ok|nincs-konyv        (book measured against hands/lap, open ~30x21 cm)
    PAPIR: feher|nincs-konyv  (white paper, not ecru/yellow)
    SAJAT: ok|nincs-konyv     (our book: our 3D engine / our pages / our cover)
    KERES: <one line: what Patrik asked, and that this matches it>
    NAGYITVA: <crop file path that was Read>   (zoomed crop of the book, or "-")
If KONYV is "van", A5/PAPIR/SAJAT must be ok/feher/ok and NAGYITVA a real path,
and two MEASURED lines are required (Patrik TG 1718, 14:27: J8 book "at least A4",
J1 paper "too white, almost glows" -- both passed a self-attested "A5: ok"):
    MERCE: nyitott|zart <book width px>/<adult head width px>
           open A5 (30 cm) vs adult head (~15 cm): ratio 1.5-2.0; closed (14.8 cm): 0.8-1.2
           or, with no person in the frame (3D book engine, studio): "MERCE: nincs-ember nyitott|zart
           <book width px>/<book height px>" -- the book's own proportions: open 1.38-1.52, closed 0.64-0.74
           an engine frame seen at an angle (3/4 view): perspective puts the ratio out of band, so the maker measures
           a FRONT render of the same book: "MERCE: nincs-ember nyitott|zart szembol <px>/<px> <front render file>"
           -- the file must exist and be another image; the front ratio is held to the same band (Klodel 34282)
           (A5 hardcover board 2x148-160 / 210-216 mm). Shape only: an A4 book has the same ratio.
           or, with the head seen in PROFILE: "MERCE: profil nyitott|zart <book px>/<head px>" -- no head band (a
           profile shows the head's length, ~20 cm, not its width, so an exact open A5 gives 1.41-1.48; card
           9e040e9c, MERES-v10). Only whoever writes down the depth-correct hand measure (the hand at the book's
           depth, projected onto the page plane) may use the "profil" form: it needs a real, in-band KEZ line.
    KEZ:nyitott|zart <book edge px>/<adult hand wrist-to-fingertip px>  (hand nearest the book's depth)
           closed: 0.6-1.1, open: 1.3-2.0; or "KEZ: nincs <reason, what else was measured>" -- only together
           with "MERCE: nincs-ember ..." (Klodel 28805: a head-measured frame needs a hand measure)
    ELRENDEZES: kulon-elem <reason>  (optional; Klodel 32029) the book stands next to the photo as its own layout
           element, not in a scene with the person: KEZ may then be absent or "nincs" if the MERCE head ratio is in
           band, or MERCE is "nincs-ember" in the book's own A5 ratio + VALODI: igen. Not with "profil".
    FENY: <paper L* (Lab)> / <brightest comparable white in the scene L*> + gutter shadow
           paper may not be brighter than the scene's own whites (no glowing page)
    KEPES: van <what photo cover/page shows> | nincs <reason>   (Patrik TG 1806)
And (Patrik TG 14836, 2026-11-06; message_and_real): a marketing image needs "UZENET: <kit fog meg> | <miért
most>", and a book on a marketing image or on a 3D-engine frame ("MERCE: nincs-ember") needs "VALODI: igen <reason>".
Also (card 0ecad9e5, Patrik TG 14472): a reply to the owner's PRIVATE chat is blocked unless the
text carries "PRIVÁT-OK: <reason>"; team work goes to the group chat. An open private window
(store/privat-ablak.json, 0600, see private_window_open; Patrik TG 14496) lifts the marker rule only;
the media checks still run.
Idea gate (Klodel 33881, 2026-11-09): a private-chat text that mentions "ötlet" (ötlet, ötletek, ötletet) is blocked
unless it carries an "ÖTLET-KAPU:" line with both "nem Marabel/könyv" and "termékpaletta ellenőrizve" (idea_check);
an open private window does not lift it.
Marketing video (Patrik csoport TG 3109, 2026-11-07: "Vegig legyen minden snitten marabel.hu"; TG 4539): the
self-attested MARKA line does not decide. One frame per second is read with the macOS Vision framework
(scripts/lib/video_text_ocr.swift) and every second must show "marabel.hu", or the gate blocks with the missing
seconds. The result is cached on the video's sha256 (store/kep-kapu/.ocr/). If the OCR does not fit in the hook's
budget, the gate blocks; warm the cache with: python3 scripts/hooks/product-image-gate.py --ocr <video>.
Safe band (Patrik privát TG 15669, 2026-11-08 07:03, CLAUDE.md BIZTONSÁGI SÁV; card c68d3745): the feed and the
Reel/Story UI cover the top and the bottom of the frame while scrolling, so every marketing image and video carries
    SAV: 4x5|9x16|1x1|fekvo felso <px> also <px> <y1>-<y2>
<y1>-<y2> is the vertical extent of the bounding box of every important element (headline, product, steps, logo,
price/CTA). The gate measures the file itself (sips / ffprobe), so the format must fit the real aspect, the bands must
equal 10 % / 10 % (4:5, 1:1, landscape) or 14 % top / 35 % bottom (9:16) of the real height (+-2 px), and the box
must stay out of them. On 9:16 only the Reel band counts (1080x1920: 269-1248): Patrik csoport TG 5732 (2026-11-13,
Klodel 40094), word for word: "egyedül arra kell figyelni h reels és hogy ha kimaszkolnak vmit akkor ne takarjon ki".
The earlier extra check against the FB feed's 4:5 centre crop (Dave 36310, Klodel 36308, free part 420-1500) is
removed: it blocked every Reel frame of the 11-13 v8 set while Patrik waited.
1:1 and landscape (any width > height) carry 10 % / 10 % too (Klodel 31805); only an upright
format other than 4:5 and 9:16 is blocked.
Taste reference (Patrik TG 4793, 2026-11-10: "Ezek ocsmany anyagotk", the third taste rejection; Klodel 36836): every
marketing image and video (not "MAJSZTRO: nem-marketing") carries
    IZLES-REF: <earlier file Patrik praised> | <TG msg id of the praise> | <side-by-side comparison image>
Both files must exist, the TG id must be an inbound message in store/claudeclaw.db conversation_log (the ledger has no
sender column: it proves the message arrived, not who wrote it), and the comparison image must be newer than the checked
file. "IZLES-REF: nincs" blocks (see izles_ref).
Website before/after pair (Klodel 39281, Patrik TG 17953, 2026-11-12: the /marabello hero lost its 8 colour circles and
went to Patrik as a "change"): an elotte/utana/before/after word in the file name, or KONYV/A5 "n/a weboldal" +
előtte/utána/pár (or a par/pair word in the file name) needs
    ELTUNT: nincs | <what is gone> PATRIK-KERTE TG <inbound TG msg id>
(see eltunt_check).
Tests: product-image-gate_test.py next to this file.
Exit 0 = allow, exit 2 = block (stderr to the model).
"""
import hashlib
import json
import sqlite3
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import time
import unicodedata
import urllib.request

MEDIA = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.mp4', '.mov', '.webm')
ROOT = os.environ.get('CLAUDE_PROJECT_DIR', '/Users/klodel/marveen')
KAPU = os.path.join(ROOT, 'store', 'kep-kapu')
REQ = ('KONYV', 'A5', 'PAPIR', 'SAJAT', 'KERES', 'NAGYITVA')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # ledger_lib (owner_latest_inbound_chat)
import owner_chat  # noqa: E402
import reply_marks  # noqa: E402
import ledger_lib  # noqa: E402


def owner_private_chat():
    """The owner's private chat id: MARVEEN_OWNER_PRIVATE_CHAT, else the install's resolved owner chat
    (scripts/lib/owner_chat.py, the .env ALLOWED_CHAT_ID / access.json rule). Never hard-coded: the id is
    personal data and stays out of the repo. "" when unknown: then no reply counts as private."""
    v = (os.environ.get('MARVEEN_OWNER_PRIVATE_CHAT') or '').strip()
    if v:
        return norm_chat(v)
    install = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        return norm_chat(owner_chat.resolve_owner_chat_id(os.path.join(install, '.env')))
    except Exception:
        return ''


def owner_group_chat():
    """The owner's team group chat: MARVEEN_OWNER_GROUP_CHAT, else store/projektek.json elo_uzenet "csoport"
    (a plain id or {"chat_id": ...}). Never hard-coded (personal data). "" when unknown."""
    v = (os.environ.get('MARVEEN_OWNER_GROUP_CHAT') or '').strip()
    if v:
        return v
    install = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        with open(os.path.join(install, 'store', 'projektek.json'), encoding='utf-8') as f:
            g = (json.load(f).get('elo_uzenet') or {}).get('csoport')
        if isinstance(g, dict):
            g = g.get('chat_id')
        return str(g).strip() if g is not None else ''
    except Exception:
        return ''


# Viktor 40081 L2: "where the owner wrote last" is about the conversation going on now. An inbound older than this
# no longer opens the private chat without the PRIVÁT-OK marker, and no longer closes the group.
LATEST_INBOUND_MAX_AGE_S = 30 * 60


def owner_latest_inbound_chat(payload, now=None):
    """Which of the owner's two chats (private / group) the MAIN agent's latest inbound message came in
    (store/claudeclaw.db conversation_log, by row id), if it came at most LATEST_INBOUND_MAX_AGE_S ago. None for
    another agent, for an older message, or when unknown."""
    priv, group = owner_private_chat(), owner_group_chat()
    if not priv or not group:
        return None
    try:
        import ledger_lib
        agent = ledger_lib.agent_id_from_payload(payload) or ledger_lib.main_agent_id()
        if agent != ledger_lib.main_agent_id():
            return None
        con = sqlite3.connect(f'file:{ledger_lib.db_path()}?mode=ro', uri=True, timeout=5)  # never create a ledger
        try:
            row = con.execute(
                "SELECT chat_id, created_at FROM conversation_log WHERE agent_id=? AND direction='in' AND chat_id IN (?, ?)"
                " ORDER BY id DESC LIMIT 1", (str(agent), priv, group)).fetchone()
        finally:
            con.close()
        if not row:
            return None
        now = time.time() if now is None else now
        try:
            fresh = now - float(row[1]) <= LATEST_INBOUND_MAX_AGE_S
        except (TypeError, ValueError):
            fresh = False
        return str(row[0]) if fresh else None
    except Exception:
        return None


WINDOW_MAX_S = 86400


def private_window_open(now=None):
    """True while store/privat-ablak.json opens the private chat without the PRIVÁT-OK marker.

    Patrik privát TG 14479/14496 (2026-11-06): non-Marabel topics go to his private chat, and he does not
    want to read "PRIVÁT-OK" lines there. The window is {"until": <unix ts>, "ok": "<reason, TG id>"}:
    open only while until is in the future, at most WINDOW_MAX_S (24 h) ahead, and the reason has at least
    10 characters. The file lives
    under CLAUDE_PROJECT_DIR like store/kep-kapu, and it counts only when it is a regular file owned by
    this user and NOT readable or writable by group or others (0600, Klodel 28916): whoever can write
    it opens the gate. Anything unreadable or malformed means closed: the marker rule applies.
    """
    path = os.path.join(ROOT, 'store', 'privat-ablak.json')
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077:
            return False
        with open(path, encoding='utf-8') as f:
            win = json.load(f)
        until = float(win.get('until') or 0)
        reason = str(win.get('ok') or '').strip()
    except Exception:
        # any failure (OSError, bad JSON, OverflowError from a huge int, ...) means closed; a traceback here
        # would exit 1, which Claude Code treats as non-blocking, and the media check would not block either
        return False
    t = time.time() if now is None else now
    # the window is a "for today" opening: one that reaches further than WINDOW_MAX_S (or is inf/nan) is closed,
    # so a forgotten or mistyped window cannot switch the marker rule off for good (Viktor 29457)
    return t < until <= t + WINDOW_MAX_S and len(reason) >= 10


def parse(path):
    out = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            if ':' in line:
                k, v = line.split(':', 1)
                out[k.strip().upper()] = v.strip()
    return out


def majsztro_budget_full():
    """Patrik TG 15348/15489 (2026-11-07): when Majsztro's weekly budget is used up, Klodel takes over his whole
    role. True while store/mod-state/majsztro.json shows the seven_day limit at >= 100 %, or the five_hour
    limit at >= 100 % before its resetsAt; a missing or
    unreadable file is False (the substitute is never the default)."""
    try:
        st = json.load(open(os.path.join(ROOT, 'store', 'mod-state', 'majsztro.json')))
        rl = st.get('usage', {}).get('rateLimits', [])
        sd = [r for r in rl if r.get('kind') == 'seven_day']
        if sd and float(sd[0].get('percentUsed', 0)) >= 100:
            return True
        # CLAUDE.md MÁJSZTRÓ HELYETTES (Patrik TG 15348: "Ha majsztro kifogy te veszed at a szerepet haladjatok"):
        # the 5-hour window at 100 % also means he is out until its reset (Klodel, 2026-11-10, Patrik waiting on TikTok).
        fh = [r for r in rl if r.get('kind') == 'five_hour']
        if fh and float(fh[0].get('percentUsed', 0)) >= 100:
            ra = fh[0].get('resetsAt')
            if not ra:
                return True
            import datetime as _dt
            return _dt.datetime.fromisoformat(ra.replace('Z', '+00:00')) > _dt.datetime.now(_dt.timezone.utc)
        return False
    except Exception:
        return False


def majsztro_ok(val):
    """Patrik TG 1879 (2026-11-05): 'mivel majsztro a főfasz ezért rajta is át kell menjen minden'.
    MAJSZTRO: MEHET <msg_id>  -> the queue row must exist, come from majsztro and contain MEHET.
    MAJSZTRO: nem-marketing <indok>  -> only for non-marketing screenshots (dashboard, bug proof)."""
    v = (val or '').strip()
    if v.lower().startswith('nem-marketing') and len(v) > len('nem-marketing') + 5:
        return None
    # Patrik TG 15348/15489 (2026-11-07): Klodel stands in for Majsztro only while his weekly budget is at 100 %.
    if v.lower().startswith('helyettes-klodel') and len(v) > len('helyettes-klodel') + 5:
        if majsztro_budget_full():
            return None
        return 'MAJSZTRO: helyettes-klodel csak akkor, ha Majsztro heti kerete 100 % (store/mod-state/majsztro.json).'
    parts = v.split()
    # Patrik TG 1881/1882: the Christmas film v9.x and Short r2v8 were already in production before
    # Majsztro took over; he gives an OPINION (any verdict), the work is not restarted.
    exc = len(parts) >= 2 and parts[0].lower() == 'kivetel-1881' and parts[1].isdigit()
    if exc:
        parts = ['MEHET', parts[1]]
    if len(parts) < 2 or parts[0].upper() != 'MEHET' or not parts[1].isdigit():
        return ('MAJSZTRO sor hiányzik/hibás. Alak: "MAJSZTRO: MEHET <msg_id>" (Májsztró MEHET-üzenetének id-je), '
                'vagy nem marketing anyagnál "MAJSZTRO: nem-marketing <indok>" (Patrik TG 1879).')
    try:
        tok = open(os.path.join(ROOT, 'store', '.dashboard-token')).read().strip()
        req = urllib.request.Request(f'http://localhost:3420/api/messages/{parts[1]}',
                                     headers={'Authorization': f'Bearer {tok}'})
        row = json.load(urllib.request.urlopen(req, timeout=5))
    except Exception as e:
        return f'MAJSZTRO: a {parts[1]} üzenet nem olvasható ({e.__class__.__name__}).'
    c = (row.get('content') or '').upper()
    if exc:
        return None if row.get('from_agent') == 'majsztro' else f'MAJSZTRO: a {parts[1]} üzenet nem Májsztrótól jött.'
    if row.get('from_agent') != 'majsztro' or 'MEHET' not in c or 'JAVÍTANDÓ' in c or 'JAVITANDO' in c or 'ELDOBANDÓ' in c:
        return f'MAJSZTRO: a {parts[1]} üzenet nem Májsztró MEHET-je.'
    return None


IZLES_FORM = ('Alak: "IZLES-REF: <Patrik által dicsért korábbi anyag fájlja> | <TG msg id a dicséretről> | '
              '<egymás mellé tett összehasonlító kép útja>" (Patrik TG 4793: "Ezek ocsmany anyagotk", a 3. '
              'ízlés-elutasítás).')
IMAGE = ('.jpg', '.jpeg', '.png', '.webp')


def tg_inbound_exists(msg_id):
    """True if the conversation ledger (store/claudeclaw.db -> conversation_log) holds an inbound Telegram message
    with this id. The ledger has no sender column, so this proves the message arrived, not that Patrik wrote it."""
    import sqlite3
    db = os.path.join(ROOT, 'store', 'claudeclaw.db')
    if not os.path.exists(db):
        return False
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=2)
    try:
        row = con.execute("SELECT 1 FROM conversation_log WHERE direction = 'in' AND message_id = ? "
                          "AND (source IS NULL OR source LIKE '%telegram%') LIMIT 1", (str(msg_id),)).fetchone()
    finally:
        con.close()
    return row is not None


def izles_ref(fp, val):
    """Patrik TG 4793 (2026-11-10 18:40, Klodel 36836): "Ezek ocsmany anyagotk" on the K6 FB/IG image and the Reel
    v11, the third taste rejection; the defect checklists passed all three. A marketing image or video goes to him
    only next to an earlier piece HE praised:
        IZLES-REF: <praised earlier file> | <TG msg id of the praise> | <side-by-side comparison image>
    The praised file and the comparison image must exist, the TG id must be an inbound message in the ledger, and the
    comparison image must be newer than the checked file (made from its final state). "IZLES-REF: nincs" (no praised
    reference) blocks: then the piece is not ready for him."""
    v = (val or '').strip()
    if not v:
        return 'IZLES-REF sor hiányzik. ' + IZLES_FORM
    if v.lower().startswith('nincs'):
        return ('IZLES-REF: nincs -- Patrik által dicsért referencia nélkül marketing-anyag nem megy elé. Keress egy '
                'korábbi anyagot, amit megdicsért (TG id), és tedd mellé. ' + IZLES_FORM)
    parts = [p.strip() for p in v.split('|')]
    if len(parts) != 3 or not all(parts):
        return 'IZLES-REF sor hibás (három, |-vel elválasztott rész kell). ' + IZLES_FORM
    ref, tg, cmp_ = parts
    real = lambda p: os.path.realpath(os.path.expanduser(p))
    ref, cmp_ = os.path.expanduser(ref), os.path.expanduser(cmp_)
    if not os.path.isfile(ref):
        return f'IZLES-REF: a dicsért referencia-fájl nem létezik ({ref}).'
    if not ref.lower().endswith(MEDIA):
        return f'IZLES-REF: a dicsért referencia nem kép/videó ({ref}).'
    if real(ref) == real(fp):
        return 'IZLES-REF: a referencia maga a vizsgált fájl; egy korábbi, Patrik által dicsért anyag kell.'
    m = re.fullmatch(r'(?:TG\s*)?(\d+)', tg, re.I)
    if not m:
        return f'IZLES-REF: a TG-azonosító nem szám ({tg}). ' + IZLES_FORM
    try:
        found = tg_inbound_exists(m.group(1))
    except Exception as e:
        return f'IZLES-REF: a TG-napló nem olvasható ({e.__class__.__name__}).'
    if not found:
        return f'IZLES-REF: a TG {m.group(1)} üzenet nincs a bejövő naplóban (store/claudeclaw.db conversation_log).'
    if not os.path.isfile(cmp_):
        return f'IZLES-REF: az összehasonlító kép nem létezik ({cmp_}).'
    if not cmp_.lower().endswith(IMAGE):
        return f'IZLES-REF: az összehasonlító lap nem kép ({cmp_}).'
    if real(cmp_) in (real(fp), real(ref)):
        return 'IZLES-REF: az összehasonlító kép külön lap legyen (a referencia és az új anyag egymás mellett).'
    try:
        if os.path.exists(fp) and os.path.getmtime(cmp_) <= os.path.getmtime(fp):
            return 'IZLES-REF: az összehasonlító kép nem frissebb a vizsgált fájlnál; a végső állapotból készítsd újra.'
    except OSError as e:
        return f'IZLES-REF: az időbélyeg nem olvasható ({e.__class__.__name__}).'
    return None


BRAND = 'marabel.hu'
OCR_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib', 'video_text_ocr.swift')
# Inside the hook. Two fast Vision reads per frame, ~0.07 s together (measured 2026-11-13 on a 30 s reel), plus a
# one-off swiftc build (~2 s).
OCR_BUDGET_S = 40
VIDEO = ('.mp4', '.mov', '.webm')


class OcrError(Exception):
    pass


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def ocr_tool_id():
    """The OCR helper's identity: its source's sha256 (16 hex). A changed helper never reuses an old cache."""
    return _sha256(OCR_SRC)[:16]


def ocr_binary(tool_id):
    """The compiled helper for this source, built once with swiftc into ~/Library/Caches/marveen."""
    d = os.path.join(os.path.expanduser('~'), 'Library', 'Caches', 'marveen')
    b = os.path.join(d, f'video_text_ocr-{tool_id}')
    if os.path.isfile(b) and os.access(b, os.X_OK):
        return b
    swiftc = shutil.which('swiftc') or '/usr/bin/swiftc'
    if sys.platform != 'darwin' or not os.access(swiftc, os.X_OK):
        raise OcrError('nincs macOS Vision / swiftc ezen a gépen')
    os.makedirs(d, exist_ok=True)
    tmp = f'{b}.tmp{os.getpid()}'
    p = subprocess.run([swiftc, '-O', OCR_SRC, '-o', tmp], capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise OcrError('a video_text_ocr.swift nem fordult le')
    os.replace(tmp, b)
    return b


def run_ocr(fp, budget):
    """{second: text} for every second of the video, from the helper's JSON lines. Anything odd raises OcrError."""
    tid = ocr_tool_id()
    binary = ocr_binary(tid)
    try:
        p = subprocess.run([binary, fp], capture_output=True, text=True, timeout=budget)
    except subprocess.TimeoutExpired:
        raise OcrError(f'az OCR nem fért bele {budget} s-be. Futtasd előre: python3 '
                       f'{os.path.abspath(__file__)} --ocr {fp} , utána küldd újra')
    if p.returncode != 0:
        raise OcrError(f'az OCR hibával állt le ({(p.stderr or "").strip()[:120]})')
    texts, done = {}, None
    for line in p.stdout.splitlines():
        o = json.loads(line)
        if 'done' in o:
            done = o['done']
        else:
            texts[int(o['t'])] = str(o['text'])
    if not done or sorted(texts) != list(range(done)):
        raise OcrError('az OCR kimenete hiányos')
    return texts


def _ranges(secs):
    out, start = [], None
    for i, s in enumerate(secs):
        if start is None:
            start = s
        if i + 1 == len(secs) or secs[i + 1] != s + 1:
            out.append(f'{start}' if start == s else f'{start}-{s}')
            start = None
    return ', '.join(out)


def brand_check(fp, budget=OCR_BUDGET_S):
    """Patrik TG 3109 (2026-11-07, csoport): "Vegig legyen minden snitten marabel.hu" (before: TG 4539, 2026-10-20,
    "sehol egy logo sehol egy marebel.hu"). The v9 Christmas Reel carried MARKA "logó + marabel.hu" and showed the
    address on the end card only. One frame per second, OCR, cached on the video's sha256 and the helper's id.
    Returns the reason to block, or None. budget=None (the --ocr warm-up) waits as long as the OCR takes."""
    try:
        vsha = _sha256(fp)
        tid = ocr_tool_id()
    except OSError as e:
        return f'a videó vagy az OCR-segéd nem olvasható ({e.__class__.__name__}).'
    cache = os.path.join(KAPU, '.ocr', vsha + '.json')
    res = None
    try:
        with open(cache, encoding='utf-8') as f:
            c = json.load(f)
        if c.get('sha256') == vsha and c.get('tool') == tid and isinstance(c.get('missing'), list):
            res = c
    except Exception:
        res = None
    if res is None:
        try:
            texts = run_ocr(fp, budget)
        except OcrError as e:
            return f'MARABEL.HU-OCR nem futott le: {e}. A kapu ilyenkor tilt.'
        except Exception as e:
            return f'MARABEL.HU-OCR nem futott le ({e.__class__.__name__}). A kapu ilyenkor tilt.'
        missing = [t for t in sorted(texts) if BRAND not in ''.join(texts[t].lower().split())]
        res = {'sha256': vsha, 'tool': tid, 'seconds': len(texts), 'missing': missing,
               'text': {str(t): texts[t][:300] for t in sorted(texts)}}
        try:
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            tmp = f'{cache}.tmp{os.getpid()}'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(res, f, ensure_ascii=False)
            os.replace(tmp, cache)
        except OSError:
            pass
    if res['missing']:
        return (f'nincs "{BRAND}" a videó {_ranges(res["missing"])}. másodpercében ({len(res["missing"])}/'
                f'{res.get("seconds", "?")} s; OCR, másodpercenként egy kocka). Patrik TG 3109: "Vegig legyen minden '
                f'snitten marabel.hu". Az OCR-szöveg: {cache}')
    return None


MESSAGE_PART_MIN = 8
REAL_REASON_MIN = 20


def message_and_real(d):
    """Patrik TG 14836 (2026-11-06 13:37, shared/hibanaplo.md): an ad image passed every gate (A5, light, page
    edge) and he answered "túl AI a könyv.. nem tunik valodi könyvnek.. és mi a mondanivaloja a képnek? ... kit
    és miért fogna meg?". The gates measured technique, not whether the book looks REAL and WHOM the image speaks to.
    UZENET: <kit fog meg> | <miért most>   -- every marketing image (not "MAJSZTRO: nem-marketing").
    VALODI: igen <what makes it a real book, looked at 100%>   -- every image with a book that is marketing or a
            3D-engine frame ("MERCE: nincs-ember ..."); anything but "igen <reason>" blocks.
    Returns the reason to block, or None."""
    marketing = not (d.get('MAJSZTRO') or '').lower().startswith('nem-marketing')
    if marketing:
        parts = [p.strip() for p in (d.get('UZENET') or '').split('|')]
        if len(parts) != 2 or min(len(p) for p in parts) < MESSAGE_PART_MIN:
            return ('UZENET sor hiányzik/hibás. Alak: "UZENET: <kit fog meg> | <miért most>", mindkét rész legalább '
                    f'{MESSAGE_PART_MIN} karakter (Patrik TG 14836: "mi a mondanivaloja a képnek? ... kit és miért '
                    'fogna meg?"). Ha egy mondatban nem mondható ki, a kép ELDOBANDÓ.')
    book = (d.get('KONYV') or '').lower().startswith('van')
    engine = (d.get('MERCE') or '').lower().startswith('nincs-ember')
    if book and (marketing or engine):
        v = (d.get('VALODI') or '').split(None, 1)
        if len(v) < 2 or v[0].lower() != 'igen' or len(v[1].strip()) < REAL_REASON_MIN:
            return ('VALODI sor hiányzik/hibás. Alak: "VALODI: igen <mi teszi valódi könyvnek, 100%-on nézve>", '
                    f'az indok legalább {REAL_REASON_MIN} karakter. Ha 3D-makettnek vagy MI-nek hat, a kép nem mehet '
                    '(Patrik TG 14836: "túl AI a könyv.. nem tunik valodi könyvnek").')
    return None


# Safe bands as a share of the frame height: (top, bottom). Klodel 31782 / CLAUDE.md BIZTONSÁGI SÁV (Patrik TG 15669).
# 1:1 and landscape: 10 % / 10 % like 4:5 (Klodel 31805, 2026-11-08). 'fekvo' is any width > height outside the 1:1
# tolerance (1.91:1 link image, 16:9 video, ...).
SAFE_BANDS = {'4x5': (0.10, 0.10), '9x16': (0.14, 0.35), '1x1': (0.10, 0.10), 'fekvo': (0.10, 0.10)}
SAFE_ASPECT = {'4x5': 5 / 4, '9x16': 16 / 9, '1x1': 1.0}  # height / width
SAFE_ASPECT_TOL = 0.02
SAFE_PX_TOL = 2
LAYOUT_REASON_MIN = 15  # ELRENDEZES: kulon-elem <reason> (Klodel 32029)
SUB_REASON_MIN = 10  # SZERZO: helyettes-klodel <reason> (Klodel 33823)
SAV_RX = re.compile(r'^(4x5|9x16|1x1|fekv[oő])\s+fels[oő]\s+(\d+)\s+als[oó]\s+(\d+)\s+(\d+)\s*-\s*(\d+)\s*$',
                    re.I)
FFPROBE_PATHS = ('/opt/homebrew/bin/ffprobe', '/usr/local/bin/ffprobe')


def image_size(fp):
    """(width, height) from the file header, pure Python (CI runs on Linux, no sips): PNG, GIF, WebP, JPEG.
    A JPEG's EXIF orientation is not applied: a rotated phone photo reads landscape and fails closed (no 4:5/9:16)."""
    with open(fp, 'rb') as f:
        data = f.read(1 << 20)
    if data[:8] == b'\x89PNG\r\n\x1a\n' and data[12:16] == b'IHDR':
        return struct.unpack('>II', data[16:24])
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return struct.unpack('<HH', data[6:10])
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        kind = data[12:16]
        if kind == b'VP8X':
            return 1 + int.from_bytes(data[24:27], 'little'), 1 + int.from_bytes(data[27:30], 'little')
        if kind == b'VP8L':
            b = int.from_bytes(data[21:25], 'little')
            return (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
        if kind == b'VP8 ':
            w, h = struct.unpack('<HH', data[26:30])
            return w & 0x3FFF, h & 0x3FFF
        return None
    if data[:2] == b'\xff\xd8':
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack('>HH', data[i + 5:i + 9])
                return w, h
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
                i += 2 if marker != 0xFF else 1
                continue
            i += 2 + struct.unpack('>H', data[i + 2:i + 4])[0]
    return None


def media_size(fp):
    """(width, height) of the image (sips) or video (ffprobe), read from the file; None if it cannot be measured.
    A video is read with its rotation applied (a phone clip stored 1920x1080 with rotation -90 shows 1080x1920)."""
    try:
        if fp.lower().endswith(VIDEO):
            probe = shutil.which('ffprobe') or next((p for p in FFPROBE_PATHS if os.path.exists(p)), None)
            if not probe:
                return None
            r = subprocess.run([probe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                'stream=width,height:stream_side_data=rotation:stream_tags=rotate', '-of', 'json', fp],
                               capture_output=True, text=True, timeout=10)
            st = json.loads(r.stdout or '{}').get('streams') or [{}]
            w, h = int(st[0]['width']), int(st[0]['height'])
            rot = [sd.get('rotation') for sd in st[0].get('side_data_list') or [] if 'rotation' in sd]
            rot = rot[0] if rot else (st[0].get('tags') or {}).get('rotate', 0)
            if abs(int(float(rot or 0))) % 180 == 90:
                w, h = h, w
            return w, h
        size = image_size(fp)
        if size:
            return tuple(int(x) for x in size)
        if not os.path.exists('/usr/bin/sips'):
            return None
        r = subprocess.run(['/usr/bin/sips', '-g', 'pixelWidth', '-g', 'pixelHeight', fp],
                           capture_output=True, text=True, timeout=10)
        w = re.search(r'pixelWidth:\s*(\d+)', r.stdout)
        h = re.search(r'pixelHeight:\s*(\d+)', r.stdout)
        return (int(w.group(1)), int(h.group(1))) if w and h else None
    except Exception:
        return None


def safe_band(fp, value):
    """Patrik TG 15669: "lathatonak kell lennie a fontos reszeknek scrollozasnal is.. levag alul felul vmennyit a fb".
    Returns the reason to block, or None."""
    form = ('Alak: "SAV: 4x5|9x16|1x1|fekvo felso <px> also <px> <y1>-<y2>", az y-tartomány a fontos elemek (cím, termék, '
            'lépések, logó, ár/CTA) közös befoglaló dobozáé (CLAUDE.md BIZTONSÁGI SÁV, Patrik TG 15669).')
    m = SAV_RX.match((value or '').strip())
    if not m:
        return 'SAV sor hiányzik/hibás. ' + form
    fmt, top, bot, y1, y2 = m.group(1).lower().replace('ő', 'o'), *(int(m.group(i)) for i in range(2, 6))
    size = media_size(fp)
    if not size or min(size) <= 0:
        return 'SAV: a fájl mérete nem mérhető (sips/ffprobe), a sávot nem tudom ellenőrizni.'
    w, h = size
    real = next((k for k, a in SAFE_ASPECT.items() if abs(h / w - a) <= a * SAFE_ASPECT_TOL), None)
    if real is None and h < w:
        real = 'fekvo'
    if real is None:
        return (f'SAV: a fájl {w}x{h} álló, de se 4:5, se 9:16; a hírfolyam-sávot ezekre mérjük (és 1:1-re, fekvőre). '
                'Készítsd 4:5 (pl. 1080x1350), 9:16 (pl. 1080x1920) vagy 1:1 (pl. 1080x1080) arányban.')
    if real != fmt:
        return f'SAV: a sor {fmt}, de a fájl {w}x{h}, ez {real}. ' + form
    want_top, want_bot = (round(h * f) for f in SAFE_BANDS[fmt])
    if abs(top - want_top) > SAFE_PX_TOL or abs(bot - want_bot) > SAFE_PX_TOL:
        return (f'SAV: {h} px magas {fmt} képen a sáv felül {want_top}, alul {want_bot} px '
                f'({SAFE_BANDS[fmt][0]:.0%} / {SAFE_BANDS[fmt][1]:.0%}), a sorban {top}/{bot}.')
    if not 0 <= y1 < y2 <= h:
        return f'SAV: az y-tartomány {y1}-{y2} nem fér a {h} px magas képbe. ' + form
    if y1 < want_top or y2 > h - want_bot:
        return (f'SAV: a fontos elem ({y1}-{y2}) belelóg a levágott sávba: a szabad rész {want_top}-{h - want_bot} px. '
                'Görgetésnél a hírfolyam és a Reel-felület ezt eltakarja (Patrik TG 15669). Told beljebb, és nézd meg '
                'a levágott változatot Read-del.')
    # Patrik TG 5732 (Klodel 40094): on 9:16 the Reel band above is the only rule; no 4:5 feed-crop check.
    return None


CAPTION_META_PREFIXES = ('ZENE:', 'SZERZO:', 'SZERZŐ:')


def caption_body(text):
    """The caption lines Patrik reads as text (TG 1981 cap: 3 lines, 200 characters), up to the IG block: not the
    price, the link, a heading or a note in brackets, and not the file's metadata lines -- the music credit
    ("Zene: ... CC BY 4.0.") and the author line ("SZERZO: majsztro <id>"), which the first-line check in main()
    already skips. Card 296af564 (Klodel, 2026-11-06): a 2-line Első éved caption was "4 lines, 232 characters"
    because the credit says "CC BY" (the filter knew only "cc-by") and SZERZO was counted."""
    body = []
    for ln in text.splitlines():
        t = ln.strip()
        if t.upper().startswith('IG'):
            break
        low = t.lower()
        if (not t or t.endswith(':') or t.startswith('(') or 'http' in low or 'scottbuckley' in low
                or 'cc-by' in low or 'cc by' in low or ' ft' in low or 'marabel.hu' in low
                or t.upper().startswith(CAPTION_META_PREFIXES)):
            continue
        body.append(t)
    return body


# Klodel 39281 (hibanapló 2026-11-12 11:43, Patrik TG 17953): in a website before/after pair the /marabello hero lost
# its 8 colour circles, and the pair went to Patrik as a "change" (TG 17946). A website pair now says what is gone:
#     ELTUNT: nincs                                   (nothing visible on "before" is missing on "after")
#     ELTUNT: <what is gone> PATRIK-KERTE TG <n>      (Patrik asked for the removal; n is an inbound TG message)
# A pair: the file name has an elotte / utana / before / after word (on its own, Viktor 39289 MEDIUM: 5 live
# elotte-*/utana-* sheets say "KONYV: nincs", not "weboldal"), or KONYV/A5 name "weboldal" AND (KONYV/A5 say
# előtte / utána / pár / pair / before / after, or the file name has a par / pair word; "pár" alone is too common a
# Hungarian word to count without "weboldal"). A missing line, a "nincs" with anything after it, a removal without
# PATRIK-KERTE TG <n> of an inbound message, or "nincs PATRIK-KERTE ..." blocks. The ledger has no sender column, so
# any inbound id passes as PATRIK-KERTE: this catches the forgotten line, not a deliberate misuse.
WEB_PAIR_TEXT_RX = re.compile(r'(?<![a-z0-9])(?:elotte|utana|par|pair|before|after)(?![a-z0-9])')
PAIR_FILE_RX = re.compile(r'(?<![a-z0-9])(?:elotte|utana|before|after)(?![a-z0-9])')
WEB_PAIR_FILE_RX = re.compile(r'(?<![a-z0-9])(?:par|pair)(?![a-z0-9])')
ELTUNT_KERTE_RX = re.compile(r'^(?P<what>.*?\S)\s+patrik-kerte\s*:?\s*tg\s*(?P<tg>\d+)\s*\.?$', re.I)
ELTUNT_FORM = ('Alak: "ELTUNT: nincs" (az előtte-képen látható elemek mind megvannak az utána-képen), vagy '
               '"ELTUNT: <mi tűnt el> PATRIK-KERTE TG <n>" (Patrik kérte az eltávolítást; n a bejövő TG-üzenete).')


def _fold(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s or '') if not unicodedata.combining(c)).lower()


def is_web_pair(fp, d):
    name = _fold(os.path.basename(fp))
    if PAIR_FILE_RX.search(name):
        return True
    head = _fold(' '.join(d.get(k) or '' for k in ('KONYV', 'A5')))
    if 'weboldal' not in head:
        return False
    return bool(WEB_PAIR_TEXT_RX.search(head) or WEB_PAIR_FILE_RX.search(name))


def eltunt_check(fp, d):
    """None, or the block reason for a website before/after pair without a valid ELTUNT line (Klodel 39281)."""
    if not is_web_pair(fp, d):
        return None
    val = (d.get('ELTUNT') or d.get('ELTŰNT') or '').strip()
    if not val:
        return ('weboldal előtte/utána pár, de nincs ELTUNT sor: nézd meg, mi tűnt el az előtte-képhez képest '
                '(Patrik TG 17953: a /marabello hero 8 színköre eltűnt, és "változásként" ment elé). ' + ELTUNT_FORM)
    if _fold(val).rstrip('.').strip() == 'nincs':
        return None
    m = ELTUNT_KERTE_RX.match(val)
    if m and _fold(m.group('what')).strip(' .,:;-') == 'nincs':
        m = None  # "nincs PATRIK-KERTE TG <n>" names nothing that is gone (Viktor 39289 INFO 3)
    if not m:
        return ('ELTUNT: ha valami eltűnt, csak Patrik kérésére mehet elé, PATRIK-KERTE TG <n> hivatkozással; a '
                '"nincs" után nem állhat más. ' + ELTUNT_FORM)
    try:
        if not tg_inbound_exists(m.group('tg')):
            return f'ELTUNT: a TG {m.group("tg")} üzenet nincs a bejövő naplóban (store/claudeclaw.db conversation_log).'
    except Exception as e:
        return f'ELTUNT: a TG-napló nem olvasható ({e.__class__.__name__}).'
    return None


def check(fp):
    base = os.path.basename(fp)
    ok = os.path.join(KAPU, base + '.ok')
    if not os.path.exists(ok):
        return f'{base}: nincs ellenőrző lap ({ok}).'
    try:
        if os.path.exists(fp) and os.path.getmtime(ok) < os.path.getmtime(fp):
            return f'{base}: a fájl az ellenőrzés UTÁN változott, újra kell nézni.'
    except OSError:
        pass
    try:
        d = parse(ok)
    except Exception as e:
        # e.g. a latin-1 saved .ok (UnicodeDecodeError): block with a reason instead of a traceback (exit 1 = pass)
        return f'{base}: az .ok nem olvasható ({e.__class__.__name__}).'
    miss = [k for k in REQ if not d.get(k)]
    if miss:
        return f'{base}: hiányzó mezők: {", ".join(miss)}.'
    el = eltunt_check(fp, d)
    if el:
        return f'{base}: {el}'
    msg = message_and_real(d)
    if msg:
        return f'{base}: {msg}'
    me = majsztro_ok(d.get('MAJSZTRO'))
    if me:
        return f'{base}: {me}'
    # Patrik TG 1946 (2026-11-05 19:00): "rajta van a logo de vhigy az h marabel.hu sehol a kepen".
    # Every marketing image carries the visible web address next to the logo.
    if not (d.get('MAJSZTRO') or '').lower().startswith('nem-marketing'):
        # Patrik TG 4793 (2026-11-10): the third taste rejection -- every marketing piece stands next to one he praised.
        ir = izles_ref(fp, d.get('IZLES-REF'))
        if ir:
            return f'{base}: {ir}'
        # a video's MARKA line is not enough: brand_check() reads every second (Patrik TG 3109), at the end of the
        # video branch below, after the cheap checks
        if not fp.lower().endswith(VIDEO) and 'marabel.hu' not in (d.get('MARKA') or '').lower():
            return (f'{base}: MARKA sor hiányzik. Alak: "MARKA: logó + marabel.hu látható a képen (<hol>)" '
                    '(Patrik TG 1946: a logó mellett a marabel.hu is kell).')
        # Patrik TG 15669 (2026-11-08): the important part stays visible with the feed's top/bottom cut.
        sb = safe_band(fp, d.get('SAV'))
        if sb:
            return f'{base}: {sb}'
        # Patrik TG 1952/1958 (2026-11-05 19:23): the Short went to him without a post text ("mi a szovege
        # a posztnak?", "Reelshez is kell szöveg amúgy?? Link legyen"). A marketing video goes with its
        # per-channel caption file (FB/IG/YT, link line) or not at all.
        if fp.lower().endswith(('.mp4', '.mov', '.webm')):
            # Patrik TG 2376 (2026-11-06): "Igy latszik a reels fb-n ha csak scrollozok ... levagja a lenyeget".
            # The FB feed shows a centred 4:5 crop with the page name on top and the caption at the bottom;
            # the Short's headline and link sat in the hidden bands. Require a looked-at feed-crop sheet.
            fe = (d.get('FEED') or '').split()
            if len(fe) < 2 or fe[0].lower() != 'ok' or not os.path.exists(fe[1]):
                return (f'{base}: FEED sor hiányzik. Alak: "FEED: ok <lap útvonala>", a lapot az '
                        'ops/feed_crop_sheet.py készíti, és Read-del megnézted: minden főcím, CTA, link a piros '
                        'sávokon kívül (Patrik TG 2376: a hírfolyam levágja a lényeget).')
            if os.path.exists(fp) and os.path.getmtime(fe[1]) < os.path.getmtime(fp):
                return f'{base}: a FEED-lap régebbi a videónál, készítsd újra (ops/feed_crop_sheet.py).'
            ps = (d.get('POSZTSZOVEG') or '').strip()
            if not ps or not os.path.exists(ps.split()[0]):
                return (f'{base}: POSZTSZOVEG sor hiányzik. Alak: "POSZTSZOVEG: <fájl útvonala>" (FB/IG/YT szöveg + link + '
                        'zenekredit; Patrik TG 1958: a Reelshez is kell szöveg, és mindig legyen link).')
            # Patrik TG 1981 (2026-11-05 20:38): "A poszt sziveg borzalom" -- second time after TG 1233
            # ("Fuu borzalmas szövegek"); his taste (TG 1235): short, plain, like a friend wrote it.
            # The narrative v9 caption had ~220 chars of story before price/link. Body cap: 3 lines, 200 chars.
            try:
                body = caption_body(open(ps.split()[0], encoding='utf-8').read())
            except (OSError, ValueError) as e:
                return f'{base}: POSZTSZOVEG nem olvasható ({e.__class__.__name__}).'
            n = sum(len(t) for t in body)
            if len(body) > 3 or n > 200:
                return (f'{base}: a posztszöveg túl hosszú ({len(body)} sor, {n} karakter az ár/link/kredit előtt; '
                        'max 3 sor, 200 karakter). Patrik TG 1981: "A poszt szoveg borzalom"; TG 1235: rövid, '
                        'egyszerű, mintha egy barát írná.')
            # Patrik TG 1985/1988 (2026-11-05 20:48): "Ezek majsztro szovegri? Nem hiszem" / "te nem irhatsz".
            # Klodel had drafted the caption and Majsztro only approved it. The caption must be Majsztro's own:
            # "SZERZO: majsztro <msg_id>" in the caption file, that row from majsztro, containing every body line.
            try:
                raw = open(ps.split()[0], encoding='utf-8').read()
            except (OSError, ValueError) as e:
                return f'{base}: POSZTSZOVEG nem olvasható ({e.__class__.__name__}).'
            sz = [l.split(':', 1)[1].split() for l in raw.splitlines() if l.strip().upper().startswith('SZERZO:')]
            # Klodel 33823 (CLAUDE.md MÁJSZTRÓ HELYETTES, TELJES SZEREP; Patrik TG 15348/15489): while Majsztro's
            # weekly budget is at 100 %, Klodel writes the caption in his place: "SZERZO: helyettes-klodel <indok>",
            # the same budget condition as the MAJSZTRO line. There is no Majsztro queue row to compare against.
            sub = bool(sz and sz[0] and sz[0][0].lower() == 'helyettes-klodel')
            if sub and len(' '.join(sz[0][1:])) < SUB_REASON_MIN:
                return (f'{base}: SZERZO: helyettes-klodel indok nélkül. Alak: "SZERZO: helyettes-klodel <indok>" '
                        f'(legalább {SUB_REASON_MIN} karakter).')
            if sub and not majsztro_budget_full():
                return (f'{base}: SZERZO: helyettes-klodel csak akkor, ha Majsztro heti kerete 100 % '
                        '(store/mod-state/majsztro.json); egyébként "SZERZO: majsztro <msg_id>".')
            if not sub and (not sz or len(sz[0]) < 2 or sz[0][0].lower() != 'majsztro' or not sz[0][1].isdigit()):
                return (f'{base}: a posztszövegben nincs "SZERZO: majsztro <msg_id>" sor. Vevői szöveget csak Májsztró ír '
                        '(Patrik TG 1985/1988: "te nem irhatsz").')
            if not sub:
                try:
                    tok = open(os.path.join(ROOT, 'store', '.dashboard-token')).read().strip()
                    req = urllib.request.Request(f'http://localhost:3420/api/messages/{sz[0][1]}',
                                                 headers={'Authorization': f'Bearer {tok}'})
                    row = json.load(urllib.request.urlopen(req, timeout=5))
                except Exception as e:
                    return f'{base}: SZERZO: a {sz[0][1]} üzenet nem olvasható ({e.__class__.__name__}).'
                norm = lambda x: ' '.join(x.split())
                mc = norm(row.get('content') or '')
                if row.get('from_agent') != 'majsztro' or not all(norm(t) in mc for t in body):
                    return (f'{base}: a posztszöveg nem szó szerint Májsztró {sz[0][1]}. üzenetéből való '
                            '(Patrik TG 1985: "Ezek majsztro szovegri? Nem hiszem").')
            br = brand_check(fp)
            if br:
                return f'{base}: {br}'
        # Patrik TG 1751 + TG 1937 (2026-11-05): "Nagyon viaszos mű ai arcok" -- twice in one day, both passed
        # a 100% eyeball review by the maker and by Klodel. A numeric skin-texture score (ops/face_texture_check.py)
        # was tried and does NOT separate waxy from good faces (Kernel calibration: rejected 4.78/2.80/1.71/2.04 vs
        # ok 2.06/4.58), so the gate demands a separate written face verdict from the INDEPENDENT reviewer
        # (not the maker), saved after the image's last change.
        if fp.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            ai = (d.get('ARC-ITELET') or '').strip()
            if ai.lower().startswith('nincs-arc') and len(ai) > 20:
                pass
            else:
                pth = ai.split()[0] if ai else ''
                if not pth or not os.path.exists(pth):
                    return (f'{base}: ARC-ITELET sor hiányzik. Alak: "ARC-ITELET: <a független felülvizsgáló ítélet-fájlja>" '
                            '(benne "ARC: MEHET", az arcok 200%-on nézve), vagy "ARC-ITELET: nincs-arc <indok>" '
                            '(Patrik TG 1937: viaszos arc).')
                try:
                    if os.path.exists(fp) and os.path.getmtime(pth) < os.path.getmtime(fp):
                        return f'{base}: az ARC-ITELET a kép utolsó változása ELŐTT készült, újra kell nézetni.'
                    txt = open(pth, encoding='utf-8').read().upper()
                except (OSError, ValueError) as e:
                    return f'{base}: ARC-ITELET nem olvasható ({e.__class__.__name__}).'
                if 'ARC: MEHET' not in txt or 'ARC: JAVÍTANDÓ' in txt or 'ARC: JAVITANDO' in txt:
                    return f'{base}: az ARC-ITELET nem "ARC: MEHET" (viaszos/AI-arc gyanú, Patrik TG 1937).'
                # 2026-11-05 21:3x: the maker self-reported KEZ 0.88 on a B5-sized book (independent reviewer
                # measured 1.37). The maker's numbers are not enough: the reviewer's whole-image verdict must be
                # "KEP: MEHET" too, written after the image's last change (same file, same mtime check above).
                if 'KEP: MEHET' not in txt or 'KEP: JAVÍTANDÓ' in txt or 'KEP: ELDOBANDÓ' in txt:
                    return (f'{base}: a független felülvizsgáló képi ítélete nem "KEP: MEHET" '
                            '(a készítő saját mérése nem elég; Patrik TG 1718: túl nagy könyv).')
                # Patrik TG 2045 (2026-11-05 22:16): "ez kuka… beállított kép… ráadásul ilyen tészta ilyen deszka.
                # Senki semmire se.." -- the gyúrós v11 passed maker, reviewer and Majsztro on a defect checklist
                # (size, cut-off, hands) while nobody asked whether it reads as a real, unposed moment. The
                # reviewer answers that FIRST, as its own line: "VALODI: MEHET <miért hat igazi pillanatnak>".
                if 'VALODI: MEHET' not in txt or 'VALODI: JAVÍTANDÓ' in txt or 'VALODI: ELDOBANDÓ' in txt:
                    return (f'{base}: a felülvizsgálói fájlban nincs "VALODI: MEHET <indok>" sor: igazi, beállítatlan '
                            'pillanatnak hat-e (anyagok, tárgyak, póz, fény), a hibalista ELŐTT '
                            '(Patrik TG 2045: "beállított kép… ilyen tészta ilyen deszka").')
    if d['KONYV'].lower().startswith('van'):
        # Patrik TG 2015 (2026-11-05 21:03): "És a könyv miért lenne belebaszva a lisztbe????" -- the book sat in
        # flour because "fit into the scene" was read as "dirty it like the scene". The maker states where the
        # book lies and that it is clean: "HELY: tiszta <hol>" (no food, flour, liquid on or under it).
        # Patrik TG 2030 (2026-11-05 21:32): "levágtátok a deszkát ... szánalmas" -- to make room for the book the
        # board was cut with a straight artificial edge. The maker checks the WHOLE scene: "EP: ok <mit néztél>".
        ep = (d.get('EP') or '').strip().lower()
        if not ep.startswith('ok') or len(ep) < 15:
            return (f'{base}: EP sor hiányzik. Alak: "EP: ok <a teljes jelenet minden tárgya ép, természetes, nincs '
                    'levágva/elvágva; mit néztél>" (Patrik TG 2030: levágott deszka).')
        hely = (d.get('HELY') or '').strip().lower()
        if not hely.startswith('tiszta') or any(w in hely for w in ('liszt', 'étel', 'etel', 'folyadék', 'morzsa')):
            return (f'{base}: HELY sor hiányzik vagy nem tiszta. Alak: "HELY: tiszta <hol fekszik a könyv>" '
                    '(Patrik TG 2015: a könyv nem kerülhet lisztbe, ételbe; ahová ember a saját könyvét tenné).')
        # Patrik TG 1806 (2026-11-05, card 0ecad9e5, TG 1862 "ugyanaz a hiba kétszer nem"): a book shown with a
        # text-only cover/page where our product carries photos. The maker states whether a PHOTO cover or page is
        # visible; if not, why: "KEPES: van <mi látszik>" or "KEPES: nincs <indok, legalább 15 karakter>".
        kepes = (d.get('KEPES') or '').strip()
        kl = kepes.lower()
        if not ((kl.startswith('van') and len(kepes) >= 8) or (kl.startswith('nincs') and len(kepes[5:].strip()) >= 15)):
            return (f'{base}: KEPES sor hiányzik/hibás. Alak: "KEPES: van <a fotós borító/oldal, ami látszik>" vagy '
                    '"KEPES: nincs <miért nincs fotó a látható borítón/oldalon>" (Patrik TG 1806).')
        if d['A5'].lower() != 'ok' or d['PAPIR'].lower() != 'feher' or d['SAJAT'].lower() != 'ok':
            return f'{base}: könyv van a képen, de A5/PAPIR/SAJAT nem ok/feher/ok.'
        crop = d['NAGYITVA']
        if crop == '-' or not os.path.exists(crop):
            return f'{base}: könyv van a képen, de nincs nagyított kivágás (NAGYITVA).'
        m = (d.get('MERCE') or '').split()
        # Klodel 28800/28801 (2026-11-06): a frame with no person (studio 3D render of our book engine) has no
        # physical scale -- no head, no hand -- and "zart 1/1" passed the head branch without a head. There only
        # the engine's own A5 board ratio can be checked, so such a frame says "nincs-ember" and gives the book's
        # width/height in px. This checks SHAPE, not size: an A4 book has the same ratio (2x210/297 = 1.41).
        no_person = bool(m) and m[0].lower() == 'nincs-ember'
        # Card 9e040e9c (Klodel 30821, Dave MERES-v10, Majsztro 30817): a head seen in profile shows its length
        # (~20 cm), not its width (~15 cm), so an exact open A5 measures 1.41-1.48 against it and the head band
        # (1.5-2.0) blocks a correct book. "profil" skips the head band; the size then rests on the hand alone,
        # so the hand measure below is compulsory and must be in band ("KEZ: nincs" blocks).
        profile = bool(m) and m[0].lower() == 'profil'
        if no_person or profile:
            m = m[1:]
        # Klodel 34282 (2026-11-09, Patrik TG 3788): our own 3D book engine's open book seen at an angle measures out of
        # band in the frame (oa-seq3 f120: 1.74 vs 1.38-1.52) because of perspective, not because the book is wrong. Such
        # a frame is measured on a FRONT render of the same book: "nincs-ember nyitott|zart szembol <px>/<px> <file>".
        # The file must exist and be an image other than this one; its ratio goes through the same A5 band below.
        frontal = no_person and len(m) >= 2 and m[1].lower() in ('szembol', 'szemből')
        if frontal:
            ref = ' '.join(m[3:]).strip()
            if (not ref or not ref.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) or not os.path.isfile(ref)
                    or os.path.abspath(ref) == os.path.abspath(fp)):
                return (f'{base}: MERCE: nincs-ember ... szembol, de a szemből renderelt referencia-fájl hiányzik, nem kép, '
                        'vagy maga a kocka. Alak: "MERCE: nincs-ember nyitott|zart szembol <könyv szélesség px>/<könyv '
                        'magasság px> <a szemből renderelt referencia-kép útja>" (Klodel 34282).')
            m = [m[0]] + m[2:3]
        try:
            kind = m[0].lower()
            if (no_person or profile) and not kind.startswith(('nyit', 'zar', 'zár')):
                raise ValueError(kind)
            bpx, hpx = (float(x) for x in m[1].split('/'))
            if profile and not (bpx > 0 and hpx > 0):
                raise ValueError(m[1])
            r = bpx / hpx
        except Exception:
            return (f'{base}: MERCE hiányzik/hibás. Alak: "MERCE: nyitott <könyv px>/<felnőtt fej px>" '
                    '(mérve a képen, nem becsülve), vagy ember nélküli képen '
                    '"MERCE: nincs-ember nyitott|zart <könyv szélesség px>/<könyv magasság px>", vagy profilban '
                    'látott fejnél "MERCE: profil nyitott|zart <könyv px>/<fej px>" (csak mért KEZ-zel).')
        if profile:
            pass
        elif no_person:
            lo, hi = (1.38, 1.52) if kind.startswith('nyit') else (0.64, 0.74)
            if not (lo <= r <= hi):
                return (f'{base}: a könyv aránya nem A5-ös keménytábla: {kind} szélesség/magasság {r:.2f}, '
                        f'elvárt {lo}-{hi} (A5 tábla 2x148-160 / 210-216 mm).'
                        + ('' if frontal else ' Ferde nézetű motor-kockánál a szemből renderelt referencián mérj: '
                           '"MERCE: nincs-ember nyitott|zart szembol <px>/<px> <referencia-kép>".'))
        else:
            lo, hi = (1.5, 2.0) if kind.startswith('nyit') else (0.8, 1.2)
            if not (lo <= r <= hi):
                return (f'{base}: a könyv nem A5 a fejhez mérve: {kind} arány {r:.2f}, '
                        f'elvárt {lo}-{hi} (A4-es vagy apró könyv). Ha a fej profilban látszik: '
                        '"MERCE: profil ..." és mélységhelyes KEZ-mérés.')
        # Patrik TG 1718 + 2026-11-05 19:0x: the head-based MERCE let A4-sized books through three
        # times (2/10 v3, 5/10, P1): the head width was ESTIMATED and sat further from the camera.
        # Second, independent measure against the nearest adult HAND at the book's depth
        # (wrist to fingertip ~18 cm): closed 14.8 cm edge -> ~0.82, open 30 cm -> ~1.67.
        k = (d.get('KEZ') or '').split()
        # Klodel 32029 (2026-11-08, Patrik "Gogogo"): a web layout where the book stands NEXT TO a photo, as its own
        # element, not in a scene with the person. There the nearest hand is not at the book's depth (a fist in
        # foreshortening measured 2.27; the baby frame has no adult hand), so the hand measure means nothing. With
        # "ELRENDEZES: kulon-elem <indok>" the KEZ line is optional (absent or "nincs") -- the scale still rests on a
        # MERCE that passed above: the head band, or "nincs-ember" with the book's own A5 ratio + VALODI: igen.
        # "profil" is not covered (it has no head band, the hand is its only size). A measured KEZ is still checked.
        lay_raw = (d.get('ELRENDEZES') or '').strip()
        lay = lay_raw.split(None, 1)
        layout = (len(lay) == 2 and lay[0].lower() in ('kulon-elem', 'külön-elem')
                  and len(lay[1].strip()) >= LAYOUT_REASON_MIN)
        if lay_raw and not layout:
            return (f'{base}: ELRENDEZES sor hibás. Alak: "ELRENDEZES: kulon-elem <miért külön elem a könyv, nem '
                    f'jelenetben az emberrel>", az indok legalább {LAYOUT_REASON_MIN} karakter.')
        hand_optional = layout and not profile and (not k or k[0].lower() == 'nincs')
        if hand_optional and no_person and not (d.get('VALODI') or '').lower().startswith('igen'):
            return f'{base}: ELRENDEZES: kulon-elem ember nélküli MERCE-vel csak "VALODI: igen <indok>" sorral.'
        if not hand_optional:
            if profile and k and k[0].lower() == 'nincs':
                return (f'{base}: MERCE: profil, de KEZ: nincs. A profil-mérés a fej-sávot kihagyja, ezért a méretet a '
                        'kézmérés adja: "KEZ: nyitott|zart <könyv él px>/<kézfej px>", a könyv mélységében lévő kéz, a lap '
                        'síkjára vetítve (kártya 9e040e9c).')
            if k and k[0].lower() == 'nincs' and not no_person:
                # Klodel 28805 (2026-11-06): with no hand the head branch was the only scale, and short2 passed with
                # an invented "zart 1/1" and no person in the frame. Without a hand, the frame must be the no-person
                # one, measured on the book's own proportions; a frame with a person needs the hand measure.
                return (f'{base}: KEZ: nincs, de a MERCE fejhez mért. Kéz nélkül csak az ember nélküli mérés fogadható el: '
                        '"MERCE: nincs-ember nyitott|zart <könyv szélesség px>/<könyv magasság px>"; ha van ember a '
                        'képen, a könyv mélységéhez legközelebbi kézhez mérj (KEZ).')
            if k and k[0].lower() == 'nincs' and len(' '.join(k[1:])) >= 15:
                pass
            else:
                try:
                    kk = k[0].lower()
                    bk, hk = (float(x) for x in k[1].split('/'))
                    rk = bk / hk
                except Exception:
                    return (f'{base}: KEZ hiányzik/hibás. Alak: "KEZ: zart|nyitott <könyv él px>/<felnőtt kézfej '
                            'csuklótól ujjhegyig px, a könyv mélységéhez legközelebbi kéz>" (mérve), vagy '
                            '"KEZ: nincs <miért nincs kéz a képen, mihez mértél helyette>".')
                klo, khi = (1.3, 2.0) if kk.startswith('nyit') else (0.6, 1.1)
                if not (klo <= rk <= khi):
                    return (f'{base}: a könyv nem A5 a kézhez mérve: {kk} arány {rk:.2f}, elvárt {klo}-{khi} '
                            '(1 kézfej kb. 18 cm; a zárt A5 éle 14,8 cm).')
        f = d.get('FENY') or ''
        if 'L*' not in f and 'l*' not in f:
            return (f'{base}: FENY hiányzik. Alak: "FENY: papír L* <x> / jelenet legfehérebb hasonló felülete '
                    'L* <y>, csak keskeny, finom gerinc-árnyék" -- a lap nem világíthat jobban a jelenet fehérjeinél, és a gerinc mellett sem szürkül be (Patrik TG 1728).')
    return None


def warm_ocr(paths):
    """python3 product-image-gate.py --ocr <video>...: fill the OCR cache with no time limit, print the verdict."""
    bad = 0
    for fp in paths:
        r = brand_check(fp, budget=None)
        print(f'{os.path.basename(fp)}: ' + (r or f'OK, "{BRAND}" minden másodpercben'))
        bad += bool(r)
    return 2 if bad else 0


IDEA_WORD = 'ötlet'  # ötlet, ötletek, ötletet, Ötlet ... (case-insensitive substring)
# Patrik csoport TG 4978 (11-11): "számtalanszor leirtam már erre van pont a köszönjük termék" -- the gate was
# private-only and keyed on "ötlet", so a group message saying "irány" pitched an existing product (évkönyv/tabló
# = Köszönjük). Now: every chat, and "irány" triggers too.
IDEA_WORDS = (IDEA_WORD, 'irány')
# Klodel 37827 (11-11 13:28, a "301-es átirányítás" technical reply was blocked): "irány" matched as a SUBSTRING, so
# átirányítás, útirány, irányítás triggered too. Now "irány" only at a word start, and not the verb irányít-
# (irányítás, irányító: control, not direction). "ötlet" stays a substring ON PURPOSE: üzletötlet, termékötlet are
# exactly the pitches the gate is for.
IDEA_RE = re.compile(r'ötlet|(?<!\w)irány(?!ít)')
IDEA_MARK = 'ÖTLET-KAPU:'
IDEA_NEEDS = ('nem marabel/könyv', 'termékpaletta ellenőrizve')
# Klodel 38049 (hibanapló 11-11 15:46): an "AI-recepciós/titkárság" idea went to Patrik (TG 17453/17460) with a valid
# ÖTLET-KAPU line, although "recepciós" and "telefonos asszisztens" are directions Patrik already refused. The gate
# checked only that the line was there. Now the text of an idea message is matched against the lint's ELUTASITOTT
# list, imported from scripts/uzleti-otlet-kapu-lint.py (one source, no copy), at a word start like the lint does.
# A direction Patrik asks for again passes only with an "ELVETETT-DE-KERT: TG <n>" line naming his message.
IDEA_LINT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'uzleti-otlet-kapu-lint.py')
IDEA_ASKED_RE = re.compile(r'(?m)^\s*ELVETETT-DE-KERT:\s*TG\s*\d+')
# "marabel" stays in the lint (an idea TITLE must not be a Marabel variation), but not in a chat text: Marabel is the
# team's daily subject, and the ÖTLET-KAPU line already states "nem Marabel/könyv". Measured on Klodel's sent messages
# of 14 days (2026-11-11): 299 trigger the idea gate, 121 hold a banned word, 91 of those only "marabel"; 47 without it.
IDEA_TEXT_SKIP = ('marabel',)
# The gate's own required phrases are cut out before the match ("nem Marabel/könyv" would hit "marabel"); the rest of
# a marker line stays under the check, so a refused direction written INTO an ÖTLET-KAPU line still stops (Viktor 38060 L2).
IDEA_OWN_PHRASES = re.compile(r'ötlet-kapu:|privát-ok:|elvetett-de-kert:\s*tg\s*\d+|nem marabel/könyv|termékpaletta ellenőrizve')
IDEA_MARKER_STARTS = ('ötlet-kapu:', 'privát-ok:', 'elvetett-de-kert:')
# Inside a marker line a negation is the declaration the gate asks for ("ÖTLET-KAPU: ..., nem AI-tanácsadás"; TG 17460
# was stopped for it, measured 2026-11-11): "nem <word>" is cut there. In the message body a negation gets no pass.
IDEA_MARKER_NEGATION = re.compile(r'(?<!\w)nem\s+[\w/-]+')
# Fewer entries than this = the list was emptied or cut, which would switch the check off silently: fail closed.
IDEA_MIN_REFUSED = 10


def refused_directions():
    """ELUTASITOTT from the lint, read as DATA (ast.literal_eval), not executed (Viktor 38060 L1): no second file runs
    in the hook, no .pyc is written, and a lint that exits at import cannot turn the gate off."""
    import ast
    with open(IDEA_LINT, encoding='utf-8') as f:
        tree = ast.parse(f.read(), IDEA_LINT)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(x, ast.Name) and x.id == 'ELUTASITOTT' for x in node.targets):
            val = ast.literal_eval(node.value)
            if isinstance(val, list) and len(val) >= IDEA_MIN_REFUSED and all(isinstance(k, str) and k for k in val):
                return val
            raise ValueError(f'ELUTASITOTT: {len(val) if isinstance(val, list) else type(val).__name__} elem')
    raise ValueError('ELUTASITOTT nincs a fájlban')


def word_start(k, t):
    """The lint's szokezdet(): the refused word or stem at a word start ("megtakarítás" is not "takarítás")."""
    return re.search(r'(?<!\w)' + re.escape(k), t) is not None


def refused_in_text(t):
    """Banned directions named in the text (the gate's own phrases cut out). Fail closed: without the list, an idea
    text stops."""
    lines = t.lower().splitlines()
    body = IDEA_OWN_PHRASES.sub(' ', '\n'.join(
        IDEA_MARKER_NEGATION.sub(' ', ln) if ln.strip().startswith(IDEA_MARKER_STARTS) else ln for ln in lines))
    try:
        banned = refused_directions()
    except Exception as e:
        return [f'(az elutasított irányok listája nem olvasható: {IDEA_LINT}: {type(e).__name__})']
    return [k for k in banned if k not in IDEA_TEXT_SKIP and word_start(k, body)]


# Klodel 39520 (hibanapló 2026-11-12 14:28, Patrik TG 18075 "ez hülyeség"): the queue-meter idea went to Patrik (TG
# 18074) with a valid ÖTLET-KAPU line but without the independent blind reviewer Klodel had promised. A text with an
# ÖTLET-KAPU line now also needs "ATNEZO: MEHET <agent-task id or file>" (the reviewer's verdict), or, when the text
# carries no new idea (status only), "ATNEZO: nincs-otlet <reason>". A file reference must exist (relative to the
# project dir or absolute, inside the project dir) and contain the word MEHET; an id is at least 6 characters of [A-Za-z0-9_-].
ATNEZO_RE = re.compile(r'(?mi)^\s*ATN[EÉ]Z[OŐ]:\s*(MEHET|nincs-[oö]tlet)\b[ \t]*(.*)$')
ATNEZO_ID = re.compile(r'[A-Za-z0-9_-]{6,}')


def atnezo_check(t):
    """None if the ÖTLET-KAPU text has a valid ATNEZO line, else the reason to block."""
    need = ('ÖTLET-KAPU (Klodel 39520, Patrik TG 18075): ötletet csak a független vak átnéző MEHET-je után küldj. Írd a '
            'szövegbe: "ATNEZO: MEHET <agent-task azonosító vagy az ítélet fájlja>"; ha nincs benne új ötlet, csak '
            'állapot: "ATNEZO: nincs-otlet <ok>".')
    for m in ATNEZO_RE.finditer(t):
        kind, ref = m.group(1).lower(), m.group(2).strip()
        if kind.startswith('nincs'):
            if len(ref) >= 10:
                return None
            continue
        tok = ref.split()[0] if ref else ''
        if '/' in tok:
            path = os.path.realpath(tok if os.path.isabs(tok) else os.path.join(ROOT, tok))
            try:
                if not path.startswith(os.path.realpath(ROOT) + os.sep):
                    raise OSError('outside the project dir')
                with open(path, encoding='utf-8', errors='replace') as f:
                    if re.search(r'(?<!\w)MEHET(?!\w)', f.read(1_000_000)):
                        return None
            except OSError:
                pass
            return need + f' (a fájl nem olvasható vagy nincs benne MEHET: {tok})'
        if ATNEZO_ID.fullmatch(tok):
            return None
    return need


# Klodel 39550 (Patrik TG 18106, 2026-11-12: "nálunk is van chatgpt agent mégis állandóan a ti hülyeségeketek jön csak"):
# the K+F lead is Majsztro (CLAUDE.md), and the idea rounds went to Patrik around him. An ÖTLET-KAPU text now also
# needs "MAJSZTRO: MEHET <msg_id>" (a queue row from majsztro that says MEHET, checked by majsztro_ok) or
# "MAJSZTRO: helyettes-klodel <reason>" (only while store/mod-state/majsztro.json shows the weekly or the 5-hour
# limit at 100 %). The image-gate forms "nem-marketing" and "kivetel-1881" do not count here.
MAJSZTRO_LINE_RE = re.compile(r'(?mi)^\s*MAJSZTR[OÓ]:[ \t]*(.*)$')
MAJSZTRO_IDEA_FORMS = ('mehet', 'helyettes-klodel')


def idea_majsztro_check(t):
    """None if the ÖTLET-KAPU text has a valid MAJSZTRO line, else the reason to block."""
    need = ('ÖTLET-KAPU (Klodel 39550, Patrik TG 18106): a K+F vezetője Májsztró, ötlet csak az ő MEHET-jével megy. '
            'Írd a szövegbe: "MAJSZTRO: MEHET <Májsztró MEHET-üzenetének msg_id-je>", vagy ha a kerete 100 %-on áll '
            '(store/mod-state/majsztro.json, heti vagy 5 órás): "MAJSZTRO: helyettes-klodel <indok>".')
    why = None
    for m in MAJSZTRO_LINE_RE.finditer(t):
        v = m.group(1).strip()
        head = v.split()[0].lower() if v else ''
        if head not in MAJSZTRO_IDEA_FORMS:
            continue
        err = majsztro_ok(v)
        if err is None:
            return None
        why = err
    return need + (f' ({why})' if why else '')


def idea_check(text):
    """Klodel 33881: a private-chat text that mentions an idea ("ötlet") passes only with an "ÖTLET-KAPU:" line that
    contains both "nem Marabel/könyv" and "termékpaletta ellenőrizve". Klodel 38049: and it names no direction Patrik
    already refused, unless an "ELVETETT-DE-KERT: TG <n>" line says he asked for it. Returns the reason to block, or None."""
    t = unicodedata.normalize('NFC', text)
    if t.lstrip().startswith('📊 ÉLŐ ÁLLAPOT'):  # generated by ops/elo_allapot.py from card titles, not a pitch
        return None
    if not IDEA_RE.search(t.lower()):
        return None
    if not IDEA_ASKED_RE.search(t):
        hits = refused_in_text(t)
        if hits:
            return ('ÖTLET-KAPU (Klodel 38049): a szöveg elutasított irányt nevez meg: ' + ', '.join(hits) + '. Patrik ezt '
                    'már elvetette (scripts/uzleti-otlet-kapu-lint.py ELUTASITOTT). Ha most ő maga kérte, írd a szövegbe: '
                    '"ELVETETT-DE-KERT: TG <az üzenete száma>".')
    for ln in t.splitlines():
        s = ln.strip()
        if s.upper().startswith(IDEA_MARK) and all(n in s.lower() for n in IDEA_NEEDS):
            return atnezo_check(t) or idea_majsztro_check(t)
    return ('ÖTLET-KAPU: új irány ne legyen Marabel/könyv-variáció, AI-tanácsadás, saját rendszer eladása; vesd össze '
            'a 6 termékkel (memória new-direction-start-from-market). Ha megvan, írd a szövegbe: "ÖTLET-KAPU: nem '
            'Marabel/könyv, termékpaletta ellenőrizve <mivel vetetted össze>".')


# Klodel 38073 (hibanapló 11-11 15:55, Patrik csoport TG 5419): the Creatorz topic is not brought up to Patrik again.
# A Telegram reply naming it is blocked, unless it answers (reply_to) a message in which Balázs himself named it.
# "Balázs wrote it" is read from what only the plugin process sees: <state>/inbound-senders.jsonl (chat_id,
# message_id, user_id; the "who" plugin patch) and the text from <state>/inbound-evidence.jsonl (the "evid" patch).
# Without those records (the patch not live yet, a rotated-away message) the reply is blocked: fail closed.
CREATORZ_RE = re.compile(r'creatorz')
BALAZS_USER_ID = '8366648365'
ZERO_WIDTH_RE = re.compile('[­​-‏⁠-⁤﻿]')


def channel_state_dir():
    return os.environ.get('TELEGRAM_STATE_DIR') or os.path.join(ROOT, '.claude', 'channels', 'telegram')


def _jsonl_rows(name):
    base = os.path.join(channel_state_dir(), name)
    for path in (base + '.1', base):
        try:
            with open(path, encoding='utf-8') as f:
                for ln in f:
                    try:
                        row = json.loads(ln)
                    except Exception:
                        continue
                    if isinstance(row, dict):  # Viktor 38110 L1: a non-object line must not crash the gate
                        yield row
        except OSError:
            continue


def creatorz_text(text):
    return CREATORZ_RE.search(ZERO_WIDTH_RE.sub('', unicodedata.normalize('NFKC', text)).lower()) is not None


def balazs_named_it(chat, reply_to):
    """True if message <reply_to> in <chat> came from Balázs (inbound-senders) and its text names Creatorz (evidence)."""
    if not chat or reply_to in (None, ''):
        return False
    rid = str(reply_to).strip()
    sent_by_balazs = any(str(r.get('chat_id')) == chat and str(r.get('message_id')) == rid
                         and str(r.get('user_id')) == BALAZS_USER_ID for r in _jsonl_rows('inbound-senders.jsonl'))
    if not sent_by_balazs:
        return False
    return any(str(r.get('chat_id')) == chat and str(r.get('message_id')) == rid and creatorz_text(str(r.get('text') or ''))
               for r in _jsonl_rows('inbound-evidence.jsonl'))


# Klodel 40686 (Balázs csoport TG 5918 waited): the PRIVÁT-VÁLASZ-KAPU held a group reply that answers Balázs's own
# group request only because Patrik's latest message came in privately (about another topic). A group reply is the
# answer to a teammate's group request when it points at that request: its reply_to, or a "BALÁZS-KÉRÉS: TG <id>" line,
# is a group message from an allowlisted sender who is NOT the owner, recorded by the plugin in inbound-senders.jsonl
# (same evidence as the Creatorz exemption), at most GROUP_REQUEST_MAX_AGE_S old. No record = no exemption.
GROUP_REQUEST_RE = re.compile(r'BAL[AÁ]ZS-K[EÉ]R[EÉ]S:\s*TG\s*(\d{1,12})\b')
GROUP_REQUEST_MAX_AGE_S = 24 * 3600


def group_allowlist(chat):
    """The plugin's allowFrom list for <chat> (access.json groups.<chat>.allowFrom), as strings; empty when unknown."""
    try:
        with open(os.path.join(channel_state_dir(), 'access.json'), encoding='utf-8') as f:
            g = (json.load(f).get('groups') or {}).get(chat) or {}
        return {str(x).strip() for x in (g.get('allowFrom') or []) if str(x).strip()}
    except Exception:
        return set()


def group_request_proof(chat, reply_to, text, now=None):
    # text: "BALÁZS-KÉRÉS: TG <id>" built from the BALAZS-KERES reply mark (never the sent text, Klodel 40845); a
    # mark only names the id, the proof is the plugin's inbound-senders.jsonl row below (Viktor 40894 (3)).
    """The id of a fresh group message from a non-owner allowlisted sender that this reply answers, else None."""
    if not chat:
        return None
    owner = owner_private_chat()
    if not owner:
        return None  # without the owner's id his own group message could pass as a teammate's: fail closed
    allowed = (group_allowlist(chat) | {BALAZS_USER_ID}) - {owner, ''}
    ids = set(GROUP_REQUEST_RE.findall(ZERO_WIDTH_RE.sub('', unicodedata.normalize('NFKC', text or ''))))
    if reply_to not in (None, ''):
        ids.add(str(reply_to).strip())
    if not ids:
        return None
    now_ms = (time.time() if now is None else now) * 1000
    for r in _jsonl_rows('inbound-senders.jsonl'):
        mid, user = str(r.get('message_id')), str(r.get('user_id'))
        if str(r.get('chat_id')) != chat or mid not in ids or user not in allowed or user == owner:
            continue
        try:
            fresh = 0 <= now_ms - float(r.get('at')) <= GROUP_REQUEST_MAX_AGE_S * 1000
        except (TypeError, ValueError):
            fresh = False
        if fresh:
            return mid
    return None


def creatorz_check(chat, text, reply_to):
    if not creatorz_text(text):
        return None
    try:
        if balazs_named_it(chat, reply_to):
            return None
    except Exception:  # any error reading the records = no proof = blocked (fail closed; a crash would let it pass)
        pass
    return ('CREATORZ-KAPU (Patrik csoport TG 5419, Klodel 38073): a Creatorz-t Patriknak többé nem hozzuk fel. Csak '
            'akkor mehet, ha a válasz (reply_to) Balázs saját üzenetére megy, amelyben ő maga írta a szót.')



# Klodel 39617 (Balázs group TG 5579 "ha 4. visszakérdezés után találsz ilyen cégeket holott megkérdeztem mi a magyar
# piac"; second case today after Patrik TG 18042 "Mindegyik van itthon is"): TG 5550 said "Radar a mért magyar boltokban
# személyre szabott domborzati térképet nem talált" without Meska and Pepita, and Meska sells three (Szigma 39612). The
# lint measured the research file, not the Telegram reply. A reply that claims something is missing at home now needs
# "ITTHON-MERT: <file>": the file passes the shared lint's ITTHON rule (--itthon; Radar's itthon_check.py rules live
# there since #203/#204) AND every ITTHON block names Meska, Pepita and eMAG, each with a measured result or
# "NINCS ADAT <reason>" (the site-probe line does not count as a shop). Patterns measured on Klodel's 2577 sent texts
# of 7 days: 34 hits, all "not available here" claims (data-gap sentences such as "magyar mérés nincs" do not hit).
ITTHON_VERB = r'(talál|kaph|árul|forgalmaz|létezik|érhető el|csinál|kínál|gyárt)'
ITTHON_CLAIM = [
    re.compile(r'(?i)\bitthon(\s+(még|viszont|pedig|is|sem|már))?\s+(nincs|sincs|hiányzik)\b'),
    re.compile(r'(?i)\bitthon\s+nem\s*[:.,;)]'),
    re.compile(r'(?i)\bitthon\b(\s+[\wáéíóöőúüű-]+){0,4}?\s+(nem|sem)\s+' + ITTHON_VERB),
    re.compile(r'(?i)\bitthon\s+senki\s+(sem|nem)\b'),
    re.compile(r'(?i)\bitthon\s+egyik\w*(\s+[\w-]+){0,2}\s+sem\b'),
    re.compile(r'(?i)\b(magyar|hazai)\s+(bolt|webshop|piac|platform|szolgáltat|stúdió|ügynökség|alapítású|megfelel|'
               r'változat|versenytárs|cég|app|termék)\w*[^.\n]{0,60}?(nem talál|nincs|sincs|nem kaph|nem árul)'),
    re.compile(r'(?i)nincs\s+(magyar|hazai)\s+(megfelel|változat|bolt|versenytárs|kínál|termék|app|platform)'),
]
ITTHON_MERT_RE = re.compile(r'(?mi)^\s*ITTHON-M[EÉ]RT:[ \t]*(\S+)')
ITTHON_SHOPS = {'meska': r'meska', 'pepita': r'pepita', 'emag': r'e-?mag'}
ITTHON_RESULT = re.compile(r'(?i)\d|nincs találat|nem hozott találatot|nem talált')
ITTHON_NOT_MEASURED = re.compile(r'(?i)nem mérhető|nem mért|(?<!\d)(403|404|410)(?!\d)|captcha')
ITTHON_NO_DATA = re.compile(r'(?i)NINCS ADAT\W+\w[^\n]{9,}')
ITTHON_SITE = re.compile(r'(?i)(?<!\w)site(:|-szűrt|-próba| szűrt)')


def itthon_blocks(t):
    out, lines = [], t.splitlines()
    for i, ln in enumerate(lines):
        if re.match(r'^\s*[-*]?\s*ITTHON:', ln):
            blk = [ln]
            for k in lines[i + 1:]:
                if k.startswith('  ') and k.strip():
                    blk.append(k)
                else:
                    break
            out.append(blk)
    return out


def itthon_shop_gaps(blk):
    """The shops of ITTHON_SHOPS that this ITTHON block does not answer (measured result or NINCS ADAT + reason)."""
    gaps = []
    for name, rx in ITTHON_SHOPS.items():
        ok = False
        for ln in blk:
            # On a site-probe line the domains (emag.hu, ...) are absence evidence, not a shop search (Klodel 39550):
            # they are cut out, the line's own shop name ("eMAG: NINCS ADAT ..., a site-próba pótolja") still counts.
            if ITTHON_SITE.search(ln):
                ln = re.sub(r'(?i)(?<![\w.])[\w-]+\.hu(?!\w)', ' ', ln)
            if not re.search(r'(?i)(?<!\w)' + rx + r'(?!\w)', ln):
                continue
            if ITTHON_NO_DATA.search(ln) or (ITTHON_RESULT.search(ln) and not ITTHON_NOT_MEASURED.search(ln)):
                ok = True
                break
        if not ok:
            gaps.append(name)
    return gaps


def itthon_mert_check(text):
    """None if the text claims no absence at home, or carries a valid ITTHON-MERT line; else the reason to block."""
    t = unicodedata.normalize('NFC', text)
    if not any(rx.search(t) for rx in ITTHON_CLAIM):
        return None
    need = ('ITTHON-KAPU (Klodel 39617, Balázs TG 5579 "megkérdeztem mi a magyar piac"): itthoni hiányt csak mérve '
            'állíts. Írd a szövegbe: "ITTHON-MERT: <kutatási fájl>"; a fájl ITTHON mezője menjen át a közös linten '
            '(scripts/uzleti-otlet-kapu-lint.py --itthon), és minden ITTHON-blokkban legyen Meska, Pepita és eMAG '
            'mért eredménnyel, vagy "NINCS ADAT <indok>". Ha nem mérted, ne állítsd.')
    m = ITTHON_MERT_RE.search(t)
    if not m:
        return need
    tok = m.group(1)
    path = os.path.realpath(tok if os.path.isabs(tok) else os.path.join(ROOT, tok))
    if not path.startswith(os.path.realpath(ROOT) + os.sep):
        return need + f' (a fájl a projekten kívül van: {tok})'
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            body = f.read(2_000_000)
    except OSError as e:
        return need + f' (a fájl nem olvasható: {tok}, {e.__class__.__name__})'
    blocks = itthon_blocks(body)
    if not blocks:
        return need + f' (a fájlban nincs ITTHON mező: {tok})'
    gaps = sorted({g for b in blocks for g in itthon_shop_gaps(b)})
    if gaps:
        return need + f' (hiányzó bolt az ITTHON-blokkban: {", ".join(gaps)})'
    # The shared lint decides the ITTHON rule (measured, two shops, site probe). It runs as its own process with -I, so
    # nothing it does at import reaches this hook; anything but a clean verdict blocks (fail closed).
    try:
        import subprocess
        p = subprocess.run([sys.executable, '-I', IDEA_LINT, path, '--itthon'], capture_output=True, text=True,
                           timeout=20, cwd=os.path.dirname(path))
        verdicts = [ln for ln in p.stdout.splitlines() if ln.startswith(('MEHET', 'NEM MEGY'))]
    except Exception as e:
        return need + f' (a lint nem futott: {e.__class__.__name__})'
    if not verdicts:
        return need + f' (a lint nem adott ítéletet a fájlra; "## 1." szakaszok kellenek: {tok})'
    # "NEM MEGY  1. <title>: <err>; <err>" -- a title may hold a colon, so the ITTHON error is searched, not split out
    bad = [m.group(0).strip() for ln in verdicts for m in re.finditer(r'(?<![\w-])ITTHON(?: hiányzik|:)[^;]*', ln)]
    if bad:
        return need + f' (lint: {bad[0][:160]})'
    return None

# Patrik privát TG 18455 (2026-11-13): "Nem vagyok hajlando ujabb parancsokat futtatni mit kepzeltek ti". Text to the
# owner's PRIVATE chat never carries a shell command for him to run: no sudo, no command chain, no checksum line, no
# shell path, no pipe into a shell. A step that needs root goes a root-free way, or it is dropped (Klodel 40845).
COMMAND_PATTERNS = (
    (re.compile(r'(?i)\bsudo\b'), 'sudo'),
    (re.compile(r'&&|\|\|'), '&& / ||'),
    (re.compile(r'\bshasum\b|\bsha256sum\b'), 'shasum'),
    (re.compile(r'/bin/(?:ba|z|da|k)?sh\b|/usr/bin/env\s'), '/bin/bash'),
    (re.compile(r'\|\s*(?:sudo\s+)?(?:ba|z)?sh\b'), '| bash'),
    (re.compile(r'\b(?:launchctl|chmod|chown|defaults\s+write|xattr|spctl|csrutil|osascript)\b'), 'rendszerparancs'),
    (re.compile(r'\b(?:curl|wget)\s+(?:-|https?://)'), 'curl/wget'),
    (re.compile(r'(?m)^[$%][ \t]+\S'), 'parancssor-prompt'),
)
# A line (or an inline `code` span) that starts with a lower-case command and an argument. A line with Hungarian
# accented letters is a sentence, not a command ("git push megtörtént", Viktor 40870).
COMMAND_LINE = re.compile(
    r'^(?:cd|export|npm|npx|node|python3?|pip3?|brew|git|bash|zsh|sh|install|rm|mv|cp|tar|ssh|scp|kill|killall|'
    r'open|ln|mkdir)[ \t]+[-./~$\w]')
HU_ACCENT = re.compile('[áéíóöőúüűÁÉÍÓÖŐÚÜŰ]')
LIST_MARK = re.compile(r'^(?:[-*\u2022>]|\d{1,3}[.)])[ \t]+')
INVISIBLE = re.compile('[\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]')


MARKER_LINE = re.compile(r'(?mi)^[ \t]*(?:[-*>][ \t]*)?(?:PRIV[AÁ]T-OK|K[EÉ]SZ-EREDM[EÉ]NY|BAL[AÁ]ZS-K[EÉ]R[EÉ]S|'
                         r'BELS[OŐ]-[UÚ]T-M[EÉ]RVE)[ \t]*:')


def marker_line(text):
    """A gate marker written as a line of the text (after NFKC and invisible characters out, Viktor 40894 (b))."""
    return bool(MARKER_LINE.search(INVISIBLE.sub('', unicodedata.normalize('NFKC', text))))


def balazs_mark(chat, reply_to, agent):
    """With reply_to no mark is needed (Viktor 40894 (3)); else the BALAZS-KERES mark as "BALÁZS-KÉRÉS: <value>"."""
    if reply_to not in (None, '') or not agent:
        return ''
    v = reply_marks.take('BALAZS-KERES', chat, agent)
    return f'BALÁZS-KÉRÉS: {v}' if v else ''


def norm_chat(v):
    """A chat id as Telegram means it: a number compares as a number ("+5040", "05040" and "5040" are one chat,
    Viktor 40886 INFO 2); anything else as stripped text."""
    t = str(v or '').strip()
    try:
        return str(int(t))
    except ValueError:
        return t


def command_check(text):
    """A shell command in a text to the owner's private chat: the first match as a short name, else None.
    Normalised first (NFKC, invisible characters out), so "su<zero-width>do" and full-width letters do not pass.
    Each line and each inline `code` span is checked, with a list mark ("1.", "-", "*") taken off the front."""
    t = INVISIBLE.sub('', unicodedata.normalize('NFKC', text))
    pieces = []
    for line in t.splitlines():
        pieces.append(line.strip())
        pieces.extend(x.strip() for x in re.findall(r'`([^`\n]+)`', line))
    pieces = [LIST_MARK.sub('', p) for p in pieces]
    for p in pieces:
        for rx, name in COMMAND_PATTERNS:
            if rx.search(p):
                return name
        line = p.strip('`').strip()
        if COMMAND_LINE.match(line):
            # Viktor 40886 LOW: an accented letter makes it a sentence only when no argument is a path, a flag or a
            # variable ("cd ~/Letöltések", "git commit -m javítás" are commands; "git push megtörtént" is not).
            args = line.split()[1:]
            if not HU_ACCENT.search(line) or any(a[:1] in '-~/$' or '/' in a for a in args):
                return 'parancssor'
    return None


def main():
    if sys.argv[1:2] == ['--ocr']:
        return warm_ocr(sys.argv[2:])
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    ti = data.get('tool_input') or {}
    # Patrik TG 14472 ("elég a marabel csapat chat"), card 0ecad9e5, TG 1862: team work goes to the group,
    # not to Patrik's private chat. A private reply passes only with a written reason in the text:
    # "PRIVÁT-OK: <indok>" (at least 10 characters). Store/projektek.json elo_uzenet.privat is this id.
    # Patrik privát TG 14479/14496 (2026-11-06): non-Marabel topics go to the private chat, and he does not
    # want to see the "PRIVÁT-OK" line. An open private window (store/privat-ablak.json:
    # {"until": <unix ts>, "ok": "<reason, TG id>"}) lets private replies pass without the marker.
    chat = norm_chat(ti.get('chat_id'))
    try:
        agent = ledger_lib.agent_id_from_payload(data) or ''
    except Exception:
        agent = ''
    if chat and chat in (owner_private_chat(), owner_group_chat()) and marker_line(str(ti.get('text') or '')):
        sys.stderr.write(
            'JELÖLŐ-KAPU (Klodel 40845: a jelölő ne Patriknak látszó szövegben legyen): a szövegben '
            'PRIVÁT-OK / KÉSZ-EREDMÉNY / BALÁZS-KÉRÉS / BELSŐ-ÚT-MÉRVE sor van. Vedd ki, és jelöld előtte: '
            'python3 -I scripts/reply-mark.py <PRIVAT-OK|KESZ-EREDMENY|BALAZS-KERES|BELSO-UT-MERVE> '
            '--chat <privat|csoport> "<érték>" (egy jel = egy üzenet, 3 perc).\n')
        return 2
    if chat and not owner_private_chat():
        # Viktor 40886 INFO 1: without the owner's chat id the private-chat gates (PARANCS-KAPU included) are off.
        sys.stderr.write('product-image-gate: the owner private chat id is unknown; the private-chat checks are off.\n')
    if chat and chat == owner_private_chat():
        cmd = command_check(str(ti.get('text') or ''))
        if cmd:
            sys.stderr.write(
                f'PARANCS-KAPU (Patrik TG 18455: "Nem vagyok hajlando ujabb parancsokat futtatni"): a Patriknak menő '
                f'szövegben parancs van ({cmd}). Patriknak soha nincs futtatandó parancs: root nélküli út, vagy a lépés '
                f'elmarad; a parancs a csapaton belül marad.\n')
            return 2
    # Patrik csoport TG 5704 (card 9df14a4c, Klodel 40009): "most meg ide reagálsz arra az üzenetemre amit a
    # másik chatbe irtam". The marker rule above sent the answer to a PRIVATE message into the group. Where the
    # owner wrote last decides: his latest message came in the private chat -> the reply goes there without the
    # PRIVÁT-OK line, and not to the group.
    latest = owner_latest_inbound_chat(data) if chat else None
    # Viktor 40081 L1: only a REPLY is redirected; the live status message in the group is edited in place
    # (edit_message) and must keep updating while Patrik writes privately.
    is_edit = str(data.get('tool_name') or '').endswith('edit_message')
    if (chat and latest and not is_edit and latest == owner_private_chat() and chat == owner_group_chat()
            and not group_request_proof(chat, ti.get('reply_to'), balazs_mark(chat, ti.get('reply_to'), agent))):
        sys.stderr.write(
            'PRIVÁT-VÁLASZ-KAPU (Patrik TG 5704: "ide reagálsz arra az üzenetemre amit a másik chatbe irtam"): '
            'Patrik utoljára PRIVÁTBAN írt, oda válaszolj (PRIVÁT-OK nélkül is mehet), ne a csoportba. '
            'Ha ez Balázs (vagy más csapattag) csoport-kérésére megy: reply_to az ő üzenetére, vagy előtte (a szövegbe '
            'nem kerül): python3 -I scripts/reply-mark.py BALAZS-KERES --chat csoport "TG <az üzenete száma>".\n')
        return 2
    if chat and chat == owner_private_chat() and not private_window_open() and latest != chat:
        why = reply_marks.take('PRIVAT-OK', chat, agent) if agent else None
        if why is None or len(why.strip()) < 10:
            sys.stderr.write(
                'PRIVÁT-KAPU (Patrik TG 14472: "elég a marabel csapat chat"): Patrik privát chatjébe csak indokkal '
                'mehet üzenet. Küldd a csapat-csoportba, vagy jelöld előtte (a szövegbe nem kerül): '
                'python3 -I scripts/reply-mark.py PRIVAT-OK --chat privat "<miért privátban, min. 10 karakter>".\n')
            return 2
    if chat:
        # Klodel 33881 (hibanapló 2026-11-09 12:1x, the third repeat; memory new-direction-start-from-market): a new
        # business idea pitched to Patrik privately came back as yet another Marabel/book variation. A private reply
        # that talks about an idea needs an "ÖTLET-KAPU:" line stating both checks. Applies with the window open too:
        # the window lifts the PRIVÁT-OK marker only.
        idea = idea_check(str(ti.get('text') or ''))
        if idea:
            sys.stderr.write(idea + '\n')
            return 2
        cz = creatorz_check(chat, str(ti.get('text') or ''), ti.get('reply_to'))
        if cz:
            sys.stderr.write(cz + '\n')
            return 2
        im = itthon_mert_check(str(ti.get('text') or ''))
        if im:
            sys.stderr.write(im + '\n')
            return 2
    files = ti.get('files') or []
    # Patrik privát TG 18439/18448/18453 (2026-11-13): "lehet h szar mindegyik ... miert kell konyorognom h elem
    # tedd oket", "Akkor azt a kaput nagyon gyorsan kiiktatni". Media sent to the owner's PRIVATE chat is not
    # held by the media checks: he reviews it himself. Group and every other chat keep the full check.
    if chat and chat == owner_private_chat():
        return 0
    errs = [e for e in (check(f) for f in files if f.lower().endswith(MEDIA)) if e]
    # Patrik TG 2314 (2026-11-06): "hol a szöveg? ne légy már geci tedd ide" -- a finished marketing video goes
    # WITH its caption written into the message itself, not "next to it in a file". The first caption body line
    # must appear in the reply text, unless the .ok says "KULDES: valasztas" (several variants to choose from).
    if not errs:
        txt = str(ti.get('text') or '')
        for f in files:
            if not f.lower().endswith(('.mp4', '.mov', '.webm')):
                continue
            try:
                d = parse(os.path.join(KAPU, os.path.basename(f) + '.ok'))
            except Exception:
                continue
            if (d.get('KULDES') or '').lower().startswith('valasztas'):
                continue
            ps = (d.get('POSZTSZOVEG') or '').strip()
            if not ps or (d.get('MAJSZTRO') or '').lower().startswith('nem-marketing'):
                continue
            first = ''
            try:
                for ln in open(ps.split()[0], encoding='utf-8').read().splitlines():
                    t = ln.strip()
                    if t and not t.endswith(':') and 'http' not in t.lower() and not t.upper().startswith(('SZERZO', 'ZENE')):
                        first = t
                        break
            except Exception:
                pass
            # Patrik TG 2217 (1 emoji a nyitómondat végén) + TG 2320 (2026-11-06: "nem látom hogy itt a szövegbe
            # lennének emojik ... megint vmi hülyeséget adtál"): a reused old caption without emoji went out.
            try:
                _cap = open(ps.split()[0], encoding='utf-8').read()
            except Exception:
                _cap = ''
            import re as _re
            if _cap and not _re.search('[\U0001F300-\U0001FAFF\u2600-\u27BF]', _cap):
                errs.append(f'{os.path.basename(f)}: a posztszövegben nincs emoji (Patrik TG 2217: 1 emoji a nyitómondat '
                            'végén; TG 2320). Régi szöveget új anyag alá ne tegyél: friss szöveg Májsztrótól.')
            if first and first not in txt:
                errs.append(f'{os.path.basename(f)}: a posztszöveg nincs az üzenetben (első sora: "{first[:60]}"). '
                            'Kész videó a szöveggel együtt megy, szó szerint (Patrik TG 2314). Több változatból '
                            'választásnál a .ok-ba: "KULDES: valasztas".')
    if errs:
        sys.stderr.write(
            'TERMÉKKÉP-KAPU (Patrik TG 1694): kép/videó csak írott ellenőrzés után mehet.\n'
            + '\n'.join(errs) + '\n'
            'Teendő: nagyítsd ki a könyvet (sips/ffmpeg crop), nézd meg Read-del, és írd meg: '
            f'{KAPU}/<fájlnév>.ok  KONYV/A5/PAPIR/SAJAT/KERES/NAGYITVA sorokkal.\n')
        return 2
    return 0


if __name__ == '__main__':
    rc = main()
    # A reply mark is spent only when the whole hook passes; a mark spent meanwhile by a parallel hook blocks.
    if rc == 0 and not reply_marks.spend_pending():
        sys.stderr.write('JELÖLŐ-KAPU: a jel közben elfogyott (egy jel = egy üzenet); jelölj újra: scripts/reply-mark.py\n')
        rc = 2
    sys.exit(rc)
