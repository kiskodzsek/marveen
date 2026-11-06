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
           (A5 hardcover board 2x148-160 / 210-216 mm). Shape only: an A4 book has the same ratio.
    KEZ: nyitott|zart <book edge px>/<adult hand wrist-to-fingertip px>  (hand nearest the book's depth)
           closed: 0.6-1.1, open: 1.3-2.0; or "KEZ: nincs <reason, what else was measured>" -- only together
           with "MERCE: nincs-ember ..." (Klodel 28805: a head-measured frame needs a hand measure)
    FENY: <paper L* (Lab)> / <brightest comparable white in the scene L*> + gutter shadow
           paper may not be brighter than the scene's own whites (no glowing page)
    KEPES: van <what photo cover/page shows> | nincs <reason>   (Patrik TG 1806)
And (Patrik TG 14836, 2026-11-06; message_and_real): a marketing image needs "UZENET: <kit fog meg> | <miért
most>", and a book on a marketing image or on a 3D-engine frame ("MERCE: nincs-ember") needs "VALODI: igen <reason>".
Also (card 0ecad9e5, Patrik TG 14472): a reply to the owner's PRIVATE chat is blocked unless the
text carries "PRIVÁT-OK: <reason>"; team work goes to the group chat. An open private window
(store/privat-ablak.json, 0600, see private_window_open; Patrik TG 14496) lifts the marker rule only;
the media checks still run.
Tests: product-image-gate_test.py next to this file.
Exit 0 = allow, exit 2 = block (stderr to the model).
"""
import json
import os
import stat
import sys
import time
import urllib.request

MEDIA = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.mp4', '.mov', '.webm')
ROOT = os.environ.get('CLAUDE_PROJECT_DIR', '/Users/klodel/marveen')
KAPU = os.path.join(ROOT, 'store', 'kep-kapu')
REQ = ('KONYV', 'A5', 'PAPIR', 'SAJAT', 'KERES', 'NAGYITVA')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib'))
import owner_chat  # noqa: E402


def owner_private_chat():
    """The owner's private chat id: MARVEEN_OWNER_PRIVATE_CHAT, else the install's resolved owner chat
    (scripts/lib/owner_chat.py, the .env ALLOWED_CHAT_ID / access.json rule). Never hard-coded: the id is
    personal data and stays out of the repo. "" when unknown: then no reply counts as private."""
    v = (os.environ.get('MARVEEN_OWNER_PRIVATE_CHAT') or '').strip()
    if v:
        return v
    install = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        return str(owner_chat.resolve_owner_chat_id(os.path.join(install, '.env')) or '')
    except Exception:
        return ''


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


def majsztro_ok(val):
    """Patrik TG 1879 (2026-11-05): 'mivel majsztro a főfasz ezért rajta is át kell menjen minden'.
    MAJSZTRO: MEHET <msg_id>  -> the queue row must exist, come from majsztro and contain MEHET.
    MAJSZTRO: nem-marketing <indok>  -> only for non-marketing screenshots (dashboard, bug proof)."""
    v = (val or '').strip()
    if v.lower().startswith('nem-marketing') and len(v) > len('nem-marketing') + 5:
        return None
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
    msg = message_and_real(d)
    if msg:
        return f'{base}: {msg}'
    me = majsztro_ok(d.get('MAJSZTRO'))
    if me:
        return f'{base}: {me}'
    # Patrik TG 1946 (2026-11-05 19:00): "rajta van a logo de vhigy az h marabel.hu sehol a kepen".
    # Every marketing image carries the visible web address next to the logo.
    if not (d.get('MAJSZTRO') or '').lower().startswith('nem-marketing'):
        if 'marabel.hu' not in (d.get('MARKA') or '').lower():
            return (f'{base}: MARKA sor hiányzik. Alak: "MARKA: logó + marabel.hu látható a képen (<hol>)" '
                    '(Patrik TG 1946: a logó mellett a marabel.hu is kell).')
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
            if not sz or len(sz[0]) < 2 or sz[0][0].lower() != 'majsztro' or not sz[0][1].isdigit():
                return (f'{base}: a posztszövegben nincs "SZERZO: majsztro <msg_id>" sor. Vevői szöveget csak Májsztró ír '
                        '(Patrik TG 1985/1988: "te nem irhatsz").')
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
        if no_person:
            m = m[1:]
        try:
            kind = m[0].lower()
            if no_person and not kind.startswith(('nyit', 'zar', 'zár')):
                raise ValueError(kind)
            bpx, hpx = (float(x) for x in m[1].split('/'))
            r = bpx / hpx
        except Exception:
            return (f'{base}: MERCE hiányzik/hibás. Alak: "MERCE: nyitott <könyv px>/<felnőtt fej px>" '
                    '(mérve a képen, nem becsülve), vagy ember nélküli képen '
                    '"MERCE: nincs-ember nyitott|zart <könyv szélesség px>/<könyv magasság px>".')
        if no_person:
            lo, hi = (1.38, 1.52) if kind.startswith('nyit') else (0.64, 0.74)
            if not (lo <= r <= hi):
                return (f'{base}: a könyv aránya nem A5-ös keménytábla: {kind} szélesség/magasság {r:.2f}, '
                        f'elvárt {lo}-{hi} (A5 tábla 2x148-160 / 210-216 mm).')
        else:
            lo, hi = (1.5, 2.0) if kind.startswith('nyit') else (0.8, 1.2)
            if not (lo <= r <= hi):
                return (f'{base}: a könyv nem A5 a fejhez mérve: {kind} arány {r:.2f}, '
                        f'elvárt {lo}-{hi} (A4-es vagy apró könyv).')
        # Patrik TG 1718 + 2026-11-05 19:0x: the head-based MERCE let A4-sized books through three
        # times (2/10 v3, 5/10, P1): the head width was ESTIMATED and sat further from the camera.
        # Second, independent measure against the nearest adult HAND at the book's depth
        # (wrist to fingertip ~18 cm): closed 14.8 cm edge -> ~0.82, open 30 cm -> ~1.67.
        k = (d.get('KEZ') or '').split()
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


def main():
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
    chat = str(ti.get('chat_id') or '').strip()
    if chat and chat == owner_private_chat() and not private_window_open():
        txt = str(ti.get('text') or '')
        i = txt.find('PRIVÁT-OK:')
        if i < 0 or len(txt[i + len('PRIVÁT-OK:'):].split('\n', 1)[0].strip()) < 10:
            sys.stderr.write(
                'PRIVÁT-KAPU (Patrik TG 14472: "elég a marabel csapat chat"): Patrik privát chatjébe csak indokkal '
                'mehet üzenet. Küldd a csapat-csoportba, vagy írd a szövegbe: "PRIVÁT-OK: <miért privátban>".\n')
            return 2
    files = ti.get('files') or []
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
    sys.exit(main())
