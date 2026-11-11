#!/usr/bin/env python3
"""Negative (and one positive) tests for product-image-gate.py: the private-chat gate and the KEPES line.

Card 0ecad9e5 (Patrik TG 1862: the same mistake twice is not acceptable). Runs the hook as Claude Code does
(JSON on stdin, exit 0 allow / 2 block) against a throw-away CLAUDE_PROJECT_DIR, so no real attestation,
token or dashboard call is touched (MAJSZTRO: nem-marketing skips the API and the marketing branch).
Private window (Klodel 28916, Patrik TG 14496, card 8a62e689): store/privat-ablak.json under the throw-away
CLAUDE_PROJECT_DIR, so the live window never leaks into a run (it did when the hook read the file next to
itself: on 2026-11-06 three private-chat cases failed while the live window was open).
Run: python3 -I scripts/hooks/product-image-gate_test.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'product-image-gate.py')
PRIV = '5040302010'  # synthetic; the hook gets it from MARVEEN_OWNER_PRIVATE_CHAT
GROUP = '-1000000000001'  # synthetic group chat id (Viktor 29457 INFO-4)


def run(root, tool_input):
    env = {'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root, 'MARVEEN_OWNER_PRIVATE_CHAT': PRIV}
    p = subprocess.run([sys.executable, '-I', HOOK], input=json.dumps({'tool_input': tool_input}),
                       capture_output=True, text=True, env=env, timeout=20)
    return p.returncode, p.stderr


VALODI_OK = 'igen valódi fehér lap, papírszál és gerinc-árnyék 100%-on nézve'


def book_fixture(root, kepes, merce='nyitott 300/170', kez='nyitott 300/180', valodi=VALODI_OK,
                 majsztro='nem-marketing teszt-fixture', uzenet=None, extra=()):
    kapu = os.path.join(root, 'store', 'kep-kapu')
    os.makedirs(kapu, exist_ok=True)
    img = os.path.join(root, 'kep.png')
    crop = os.path.join(root, 'crop.png')
    for f in (img, crop):
        open(f, 'wb').write(b'\x89PNG')
    lines = ['KONYV: van', 'A5: ok', 'PAPIR: feher', 'SAJAT: ok', 'KERES: teszt kérés, egyezik',
             f'NAGYITVA: {crop}', f'MAJSZTRO: {majsztro}',
             'EP: ok a teljes jelenet ép, semmi nincs levágva', 'HELY: tiszta asztalon fekszik',
             f'MERCE: {merce}', 'FENY: papír L* 88 / jelenet L* 92, finom gerinc']
    if kez is not None:
        lines.append(f'KEZ: {kez}')
    lines.extend(extra)
    if kepes is not None:
        lines.append(f'KEPES: {kepes}')
    if valodi is not None:
        lines.append(f'VALODI: {valodi}')
    if uzenet is not None:
        lines.append(f'UZENET: {uzenet}')
    open(os.path.join(kapu, 'kep.png.ok'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    return img


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def private_without_reason_blocked(root):
    rc, err = run(root, {'chat_id': PRIV, 'text': 'Kész a kép.'})
    return rc == 2 and 'PRIVÁT-KAPU' in err


@case
def private_with_too_short_reason_blocked(root):
    rc, _ = run(root, {'chat_id': PRIV, 'text': 'PRIVÁT-OK: mert\nKész.'})
    return rc == 2


@case
def private_with_reason_allowed(root):
    rc, _ = run(root, {'chat_id': PRIV, 'text': 'PRIVÁT-OK: Patrik privátban kérdezte, privát ügy\nVálasz.'})
    return rc == 0


@case
def private_ascii_variant_blocked(root):
    # only the exact marker counts; "PRIVAT-OK" without accent is not a reason line
    rc, _ = run(root, {'chat_id': PRIV, 'text': 'PRIVAT-OK: Patrik privátban kérdezte, privát ügy'})
    return rc == 2


@case
def group_reply_allowed(root):
    rc, _ = run(root, {'chat_id': GROUP, 'text': 'Kész a kép.'})
    return rc == 0


@case
def book_without_kepes_blocked(root):
    img = book_fixture(root, None)
    rc, err = run(root, {'chat_id': GROUP, 'text': 'x', 'files': [img]})
    return rc == 2 and 'KEPES' in err


@case
def book_with_bare_kepes_nincs_blocked(root):
    img = book_fixture(root, 'nincs')
    rc, err = run(root, {'chat_id': GROUP, 'text': 'x', 'files': [img]})
    return rc == 2 and 'KEPES' in err


@case
def book_with_kepes_van_allowed(root):
    img = book_fixture(root, 'van fotós borító, a nagyszülők képe')
    rc, err = run(root, {'chat_id': GROUP, 'text': 'x', 'files': [img]})
    return rc == 0


@case
def book_with_kepes_nincs_reason_allowed(root):
    img = book_fixture(root, 'nincs a könyv zárva, hátlap látszik, azon nincs fotó')
    rc, _ = run(root, {'chat_id': GROUP, 'text': 'x', 'files': [img]})
    return rc == 0


NO_PERSON_KEZ = 'nincs 3D könyvmotor, stúdióháttér, ember nincs a képen'
KEPES_OK = 'van fotós borító, a nagyszülők képe'


def no_person(root, merce):
    img = book_fixture(root, KEPES_OK, merce=merce, kez=NO_PERSON_KEZ)
    return run(root, {'chat_id': GROUP, 'text': 'x', 'files': [img]})


@case
def no_person_open_a5_allowed(root):
    rc, _ = no_person(root, 'nincs-ember nyitott 888/630')   # 1.41: 2x148 / 210 mm
    return rc == 0


@case
def no_person_closed_a5_allowed(root):
    rc, _ = no_person(root, 'nincs-ember zart 444/630')      # 0.70: 148 / 210 mm
    return rc == 0


@case
def no_person_open_too_wide_blocked(root):
    rc, err = no_person(root, 'nincs-ember nyitott 1000/630')  # 1.59: wider than an A5 spread
    return rc == 2 and 'A5-ös keménytábla' in err


@case
def no_person_open_1_8_blocked(root):
    rc, err = no_person(root, 'nincs-ember nyitott 1134/630')  # 1.80
    return rc == 2 and 'A5-ös keménytábla' in err


@case
def no_person_closed_square_blocked(root):
    rc, err = no_person(root, 'nincs-ember zart 1/1')          # the short2 bypass, now on the shape branch
    return rc == 2 and 'A5-ös keménytábla' in err


@case
def no_person_without_kind_blocked(root):
    rc, err = no_person(root, 'nincs-ember 444/630')
    return rc == 2 and 'MERCE hiányzik/hibás' in err


# Klodel 34282 (Patrik TG 3788): an engine frame at an angle measures out of band (oa-seq3 f120: 1.74); it is
# measured on a FRONT render of the same book, which must exist and be another image.
def front_ref(root, name='szembol.png'):
    ref = os.path.join(root, name)
    open(ref, 'wb').write(b'\x89PNG')
    return ref


@case
def no_person_angled_frame_still_blocked(root):
    rc, err = no_person(root, 'nincs-ember nyitott 1096/630')  # 1.74, the measured oa-seq3 f120 frame
    return rc == 2 and 'A5-ös keménytábla' in err and 'szembol' in err


@case
def no_person_front_render_open_allowed(root):
    rc, _ = no_person(root, f'nincs-ember nyitott szembol 888/630 {front_ref(root)}')
    return rc == 0


@case
def no_person_front_render_closed_accented_allowed(root):
    rc, _ = no_person(root, f'nincs-ember zart szemből 444/630 {front_ref(root)}')
    return rc == 0


@case
def no_person_front_render_path_with_space_allowed(root):
    rc, _ = no_person(root, f'nincs-ember nyitott szembol 888/630 {front_ref(root, "szembol kep.png")}')
    return rc == 0


@case
def no_person_front_render_out_of_band_blocked(root):
    rc, err = no_person(root, f'nincs-ember nyitott szembol 1096/630 {front_ref(root)}')
    return rc == 2 and 'A5-ös keménytábla' in err


@case
def no_person_front_render_missing_file_blocked(root):
    rc, err = no_person(root, f'nincs-ember nyitott szembol 888/630 {os.path.join(root, "nincs-ilyen.png")}')
    return rc == 2 and 'referencia-fájl' in err


@case
def no_person_front_render_without_file_blocked(root):
    rc, err = no_person(root, 'nincs-ember nyitott szembol 888/630')
    return rc == 2 and 'referencia-fájl' in err


@case
def no_person_front_render_not_an_image_blocked(root):
    txt = os.path.join(root, 'meres.txt')
    open(txt, 'w').write('888/630')
    rc, err = no_person(root, f'nincs-ember nyitott szembol 888/630 {txt}')
    return rc == 2 and 'referencia-fájl' in err


@case
def no_person_front_render_self_reference_blocked(root):
    rc, err = no_person(root, f'nincs-ember nyitott szembol 888/630 {os.path.join(root, "kep.png")}')
    return rc == 2 and 'referencia-fájl' in err


@case
def front_render_needs_no_person(root):
    # "szembol" is the engine branch only: on the head branch it is not a kind, the line is malformed.
    img = book_fixture(root, KEPES_OK, merce=f'nyitott szembol 888/630 {front_ref(root)}')
    rc, err = run(root, {'chat_id': GROUP, 'text': 'x', 'files': [img]})
    return rc == 2 and 'MERCE hiányzik/hibás' in err


@case
def front_render_still_needs_valodi(root):
    img = book_fixture(root, KEPES_OK, merce=f'nincs-ember nyitott szembol 888/630 {front_ref(root)}',
                       kez=NO_PERSON_KEZ, valodi=None)
    rc, err = run(root, {'chat_id': GROUP, 'text': 'x', 'files': [img]})
    return rc == 2 and 'VALODI' in err


@case
def short2_head_merce_without_hand_blocked(root):
    # The short2 sheet (11-06): "zart 1/1" on the head branch, KEZ: nincs, no person in the frame.
    img = book_fixture(root, KEPES_OK, merce='zart 1/1', kez='nincs a könyves kockákon nincs kéz, 3D motor renderje')
    rc, err = run(root, {'chat_id': GROUP, 'text': 'x', 'files': [img]})
    return rc == 2 and 'KEZ: nincs, de a MERCE fejhez mért' in err


@case
def head_merce_with_hand_still_allowed(root):
    img = book_fixture(root, KEPES_OK, merce='zart 100/110', kez='zárt 100/120')
    rc, _ = run(root, {'chat_id': GROUP, 'text': 'x', 'files': [img]})
    return rc == 0


# "MERCE: profil" (card 9e040e9c, Klodel 30821, Dave MERES-v10): a head in profile gives 1.42 for an exact open
# A5, so the head band is skipped -- and the size rests on a real, in-band hand measure. Dave's numbers: open
# spread 906 px, head length 640 px, hand 176 mm x 3.06 px/mm = 539 px at the book's depth.
PROFILE = 'profil nyitott 906/640'
PROFILE_KEZ = 'nyitott 906/539'


def edit_ok(root, old, new):
    okf = os.path.join(root, 'store', 'kep-kapu', 'kep.png.ok')
    txt = open(okf, encoding='utf-8').read()
    assert old in txt, old
    open(okf, 'w', encoding='utf-8').write(txt.replace(old, new))


@case
def profile_with_depth_correct_hand_allowed(root):
    rc, _ = sent(root, merce=PROFILE, kez=PROFILE_KEZ)
    return rc == 0


@case
def profile_with_kez_nincs_blocked(root):
    rc, err = sent(root, merce=PROFILE, kez='nincs a kéz takarásban van, a fejhez mértem')
    return rc == 2 and 'MERCE: profil, de KEZ: nincs' in err


@case
def profile_with_bare_kez_nincs_blocked(root):
    rc, err = sent(root, merce=PROFILE, kez='nincs')
    return rc == 2 and 'MERCE: profil, de KEZ: nincs' in err


@case
def profile_with_empty_kez_blocked(root):
    rc, err = sent(root, merce=PROFILE, kez='')
    return rc == 2 and 'KEZ hiányzik/hibás' in err


@case
def profile_with_kez_out_of_band_blocked(root):
    rc, err = sent(root, merce=PROFILE, kez='nyitott 906/400')   # 2.27: the book is too big for the hand
    return rc == 2 and 'nem A5 a kézhez mérve' in err


@case
def profile_with_kez_too_small_blocked(root):
    rc, err = sent(root, merce=PROFILE, kez='nyitott 600/539')   # 1.11: an open book smaller than A5
    return rc == 2 and 'nem A5 a kézhez mérve' in err


@case
def profile_without_feny_blocked(root):
    img = book_fixture(root, KEPES_OK, merce=PROFILE, kez=PROFILE_KEZ)
    edit_ok(root, 'FENY: papír L* 88 / jelenet L* 92, finom gerinc\n', '')
    rc, err = run(root, {'chat_id': GROUP, 'text': 'x', 'files': [img]})
    return rc == 2 and 'FENY hiányzik' in err


@case
def profile_without_zoomed_crop_blocked(root):
    img = book_fixture(root, KEPES_OK, merce=PROFILE, kez=PROFILE_KEZ)
    edit_ok(root, f'NAGYITVA: {os.path.join(root, "crop.png")}', 'NAGYITVA: -')
    rc, err = run(root, {'chat_id': GROUP, 'text': 'x', 'files': [img]})
    return rc == 2 and 'nincs nagyított kivágás' in err


@case
def profile_without_kind_blocked(root):
    rc, err = sent(root, merce='profil 906/640', kez=PROFILE_KEZ)
    return rc == 2 and 'MERCE hiányzik/hibás' in err


@case
def profile_unknown_kind_blocked(root):
    rc, err = sent(root, merce='profil szemből 906/640', kez=PROFILE_KEZ)
    return rc == 2 and 'MERCE hiányzik/hibás' in err


@case
def profile_zero_head_blocked(root):
    rc, err = sent(root, merce='profil nyitott 906/0', kez=PROFILE_KEZ)
    return rc == 2 and 'MERCE hiányzik/hibás' in err


@case
def profile_negative_px_blocked(root):
    rc, err = sent(root, merce='profil nyitott -906/-640', kez=PROFILE_KEZ)
    return rc == 2 and 'MERCE hiányzik/hibás' in err


@case
def head_branch_1_42_still_blocked(root):
    # The same frame on the old head branch: 1.42 is under the 1.5-2.0 band, even with a good hand measure.
    rc, err = sent(root, merce='nyitott 906/640', kez=PROFILE_KEZ)
    return rc == 2 and 'nem A5 a fejhez mérve' in err and 'MERCE: profil' in err


# UZENET + VALODI (Patrik TG 14836, shared/hibanaplo.md 2026-11-06 13:37, card ca0737c2).
SAV_9X16_OK = 'SAV: 9x16 felso 269 also 672 430-1240'  # inside the Reel band AND the feed's 4:5 crop (420-1248)
MARKETING = 'MEHET 1'  # the MAJSZTRO API check comes after UZENET/VALODI; here it fails (no token): rc 2, MAJSZTRO
UZENET_OK = 'nagyszülőnek ajándékot kereső felnőtt gyerek | karácsony előtt, amíg még elkészül'


def sent(root, **kw):
    img = book_fixture(root, KEPES_OK, **kw)
    return run(root, {'chat_id': GROUP, 'text': 'x', 'files': [img]})


@case
def engine_frame_without_valodi_blocked(root):
    rc, err = sent(root, merce='nincs-ember nyitott 888/630', kez=NO_PERSON_KEZ, valodi=None)
    return rc == 2 and 'VALODI' in err


@case
def engine_frame_valodi_nem_blocked(root):
    rc, err = sent(root, merce='nincs-ember nyitott 888/630', kez=NO_PERSON_KEZ, valodi='nem 3D-makettnek hat, túl sima a lap')
    return rc == 2 and 'VALODI' in err


@case
def engine_frame_bare_valodi_igen_blocked(root):
    rc, err = sent(root, merce='nincs-ember nyitott 888/630', kez=NO_PERSON_KEZ, valodi='igen ok')
    return rc == 2 and 'VALODI' in err


@case
def non_marketing_head_measured_without_valodi_allowed(root):
    # Not marketing and not a 3D-engine frame: VALODI is not asked (an internal photo check, as before).
    rc, _ = sent(root, merce='zart 100/110', kez='zárt 100/120', valodi=None)
    return rc == 0


@case
def marketing_without_uzenet_blocked(root):
    rc, err = sent(root, majsztro=MARKETING)
    return rc == 2 and 'UZENET' in err


@case
def marketing_uzenet_one_part_blocked(root):
    rc, err = sent(root, majsztro=MARKETING, uzenet='mindenkinek szól, mert szép')
    return rc == 2 and 'UZENET' in err


@case
def marketing_uzenet_short_part_blocked(root):
    rc, err = sent(root, majsztro=MARKETING, uzenet='anyák | most')
    return rc == 2 and 'UZENET' in err


@case
def marketing_book_without_valodi_blocked(root):
    rc, err = sent(root, majsztro=MARKETING, uzenet=UZENET_OK, valodi=None)
    return rc == 2 and 'VALODI' in err


@case
def marketing_with_uzenet_and_valodi_reaches_majsztro(root):
    rc, err = sent(root, majsztro=MARKETING, uzenet=UZENET_OK)
    return rc == 2 and 'MAJSZTRO' in err and 'UZENET' not in err and 'VALODI' not in err


@case
def marketing_without_book_needs_no_valodi(root):
    img = book_fixture(root, KEPES_OK, majsztro=MARKETING, uzenet=UZENET_OK, valodi=None)
    okf = os.path.join(root, 'store', 'kep-kapu', 'kep.png.ok')
    open(okf, 'w', encoding='utf-8').write(open(okf, encoding='utf-8').read().replace('KONYV: van', 'KONYV: nincs'))
    rc, err = run(root, {'chat_id': GROUP, 'text': 'x', 'files': [img]})
    return rc == 2 and 'VALODI' not in err and 'UZENET' not in err


REASON = 'Patrik TG 14496: nem-Marabel téma privátban'


def window(root, until, ok=REASON, mode=0o600, raw=None):
    store = os.path.join(root, 'store')
    os.makedirs(store, exist_ok=True)
    path = os.path.join(store, 'privat-ablak.json')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(raw if raw is not None else json.dumps({'until': until, 'ok': ok}))
    os.chmod(path, mode)
    return path


@case
def window_open_private_allowed(root):
    window(root, time.time() + 3600)
    rc, _ = run(root, {'chat_id': PRIV, 'text': 'Kész a kép.'})
    return rc == 0


@case
def window_expired_blocked(root):
    window(root, time.time() - 60)
    rc, err = run(root, {'chat_id': PRIV, 'text': 'Kész a kép.'})
    return rc == 2 and 'PRIVÁT-KAPU' in err


@case
def window_missing_blocked(root):
    rc, err = run(root, {'chat_id': PRIV, 'text': 'Kész a kép.'})
    return rc == 2 and 'PRIVÁT-KAPU' in err


@case
def window_short_reason_blocked(root):
    window(root, time.time() + 3600, ok='mert')
    rc, _ = run(root, {'chat_id': PRIV, 'text': 'Kész a kép.'})
    return rc == 2


@case
def window_group_readable_blocked(root):
    window(root, time.time() + 3600, mode=0o644)
    rc, _ = run(root, {'chat_id': PRIV, 'text': 'Kész a kép.'})
    return rc == 2


@case
def window_malformed_blocked(root):
    window(root, None, raw='["until", 9999999999]')
    rc, _ = run(root, {'chat_id': PRIV, 'text': 'Kész a kép.'})
    return rc == 2


@case
def window_symlink_blocked(root):
    real = os.path.join(root, 'elsewhere.json')
    with open(real, 'w', encoding='utf-8') as f:
        json.dump({'until': time.time() + 3600, 'ok': REASON}, f)
    os.chmod(real, 0o600)
    os.makedirs(os.path.join(root, 'store'), exist_ok=True)
    os.symlink(real, os.path.join(root, 'store', 'privat-ablak.json'))
    rc, _ = run(root, {'chat_id': PRIV, 'text': 'Kész a kép.'})
    return rc == 2


@case
def window_open_media_still_checked(root):
    # The window lifts the marker rule only: an image without its attestation is still blocked.
    window(root, time.time() + 3600)
    img = os.path.join(root, 'kep.png')
    open(img, 'wb').write(b'\x89PNG')
    rc, err = run(root, {'chat_id': PRIV, 'text': 'Kész a kép.', 'files': [img]})
    return rc == 2 and 'nincs ellenőrző lap' in err


@case
def window_overflow_until_closed(root):
    # Viktor 29457 (1): {"until": 1e400 as an int} made float() raise OverflowError, the hook exited 1 with a
    # traceback, and exit 1 does not block -- not even the media check. Now: closed, exit 2.
    window(root, None, raw='{"until": 1' + '0' * 400 + ', "ok": "' + REASON + '"}')
    rc, err = run(root, {'chat_id': PRIV, 'text': 'Kész a kép.'})
    return rc == 2 and 'PRIVÁT-KAPU' in err and 'Traceback' not in err


@case
def window_overflow_media_still_blocked(root):
    window(root, None, raw='{"until": 1' + '0' * 400 + ', "ok": "' + REASON + '"}')
    img = os.path.join(root, 'kep.png')
    open(img, 'wb').write(b'\x89PNG')
    # private chat, marker present (so the private gate passes), image without attestation: must still block
    rc, err = run(root, {'chat_id': PRIV, 'text': 'PRIVÁT-OK: ' + REASON + '\nKész a kép.', 'files': [img]})
    return rc == 2 and 'nincs ellenőrző lap' in err and 'Traceback' not in err


@case
def window_too_far_closed(root):
    # Viktor 29457 (3): a window more than 24 h ahead (forgotten, mistyped) is closed.
    window(root, time.time() + 2 * 86400)
    rc, _ = run(root, {'chat_id': PRIV, 'text': 'Kész a kép.'})
    return rc == 2


@case
def window_infinity_closed(root):
    window(root, None, raw='{"until": Infinity, "ok": "' + REASON + '"}')
    rc, _ = run(root, {'chat_id': PRIV, 'text': 'Kész a kép.'})
    return rc == 2


@case
def ok_file_not_utf8_blocked(root):
    # Viktor 29457 (2): a latin-1 saved .ok raised UnicodeDecodeError in parse() -> exit 1 -> the image passed.
    img = book_fixture(root, 'van a borító fotója')
    okf = os.path.join(root, 'store', 'kep-kapu', 'kep.png.ok')
    open(okf, 'ab').write('KERES: árvíz\n'.encode('latin-1'))
    rc, err = run(root, {'chat_id': GROUP, 'text': 'x', 'files': [img]})
    return rc == 2 and 'nem olvasható' in err and 'Traceback' not in err


# POSZTSZOVEG body cap (Patrik TG 1981: 3 lines, 200 characters) without the file's metadata lines (card 296af564,
# Klodel 2026-11-06): the Első éved Short v3.9 caption, verbatim, was blocked as "4 lines, 232 characters" because
# the music credit ("CC BY 4.0", not "cc-by") and the SZERZO line were counted as text.
ELSO_EVED_CAPTION = (
    'Az emlékek halványulnak, nem is hinnénk mennyire. \U0001F49B\n'
    'Meséljétek el a fotók mögötti történeteket a Marabel Első éved könyvében.\n'
    '\n'
    '27 980 Ft, a nyomtatott könyvvel együtt.\n'
    'marabel.hu/elso-eved\n'
    '\n'
    'Zene: "Morning" Kevin MacLeod (incompetech.com), CC BY 4.0.\n'
    '\n'
    'SZERZO: majsztro 29474 (Meta-hirdetés, Első éved)\n'
)
LONG_BODY = '\n'.join(f'{i}. sor: ez a mondat valódi szöveg, amit Patrik elolvas a hírfolyamban, és hosszú.' for i in range(1, 5))


def gate_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location('product_image_gate', HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def caption_check(root, caption):
    """The hook's check() on a marketing video whose only difference is its caption file. Majsztro's MEHET (a live
    queue read) is stubbed; ROOT and KAPU point into the throw-away root, so the SZERZO read after the length cap
    finds no token and stops there: a result naming SZERZO means the length cap let the caption through."""
    mod = gate_module()
    mod.ROOT = root
    mod.KAPU = os.path.join(root, 'store', 'kep-kapu')
    mod.majsztro_ok = lambda _value: None
    mod.izles_ref = lambda _fp, _value: None  # IZLES-REF has its own cases (izles_*)
    os.makedirs(mod.KAPU, exist_ok=True)
    video = os.path.join(root, 'short.mp4')
    open(video, 'wb').write(b'\x00')
    sheet = os.path.join(root, 'feed.png')
    open(sheet, 'wb').write(b'\x89PNG')
    cap = os.path.join(root, 'posztszoveg.txt')
    open(cap, 'w', encoding='utf-8').write(caption)
    lines = ['KONYV: nincs', 'A5: nincs-konyv', 'PAPIR: nincs-konyv', 'SAJAT: nincs-konyv', 'KERES: teszt kérés, egyezik',
             'NAGYITVA: -', 'MAJSZTRO: MEHET 1', 'UZENET: friss szülők, akik fotóznak | most kezdődik az első év',
             'MARKA: logó + marabel.hu látható a képen (jobb alsó sarok)', f'FEED: ok {sheet}', f'POSZTSZOVEG: {cap}',
             SAV_9X16_OK]
    mod.media_size = lambda _fp: (1080, 1920)  # the video here is a 1-byte stub; the safe band has its own cases
    open(os.path.join(mod.KAPU, 'short.mp4.ok'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    later = time.time() + 5
    os.utime(sheet, (later, later))
    os.utime(os.path.join(mod.KAPU, 'short.mp4.ok'), (later, later))
    return mod.check(video) or ''


@case
def caption_credit_and_author_not_counted(root):
    body = gate_module().caption_body(ELSO_EVED_CAPTION)
    return body == ['Az emlékek halványulnak, nem is hinnénk mennyire. \U0001F49B',
                    'Meséljétek el a fotók mögötti történeteket a Marabel Első éved könyvében.']


@case
def caption_real_short_one_passes_the_cap(root):
    err = caption_check(root, ELSO_EVED_CAPTION)
    return 'túl hosszú' not in err and 'SZERZO' in err


@case
def caption_too_long_body_still_blocked(root):
    # Negative: four real text lines stay too long, credit and author lines or not.
    err = caption_check(root, LONG_BODY + '\n\nZene: "Jul" Scott Buckley, CC BY 4.0.\n\nSZERZO: majsztro 29474\n')
    return 'túl hosszú (4 sor' in err


@case
def caption_over_200_chars_still_blocked(root):
    two = 'Ez egy nagyon hosszú első mondat, ami mindent el akar mondani a termékről egyszerre, ' * 2
    err = caption_check(root, f'{two}\n{two}\n\nZene: x, CC BY 4.0.\nSZERZO: majsztro 1\n')
    return 'túl hosszú (2 sor' in err


@case
def caption_music_word_inside_text_still_counted(root):
    # Only a line that STARTS with the credit/author label is metadata; "zene" inside a sentence is text.
    body = gate_module().caption_body('A zene is szól a könyvben.\nSzerzői jog nélkül nincs zene.\nHarmadik.\nNegyedik.\n')
    return len(body) == 4


# MARABEL.HU on every second of a marketing video (Patrik csoport TG 3109, 2026-11-07: "Vegig legyen minden snitten
# marabel.hu"; TG 4539). The OCR itself is stubbed in the portable cases (CI runs on Linux, no Vision); the last case
# runs the real macOS Vision helper on a generated video and is skipped elsewhere.
def ocr_module(root):
    mod = gate_module()
    mod.ROOT = root
    mod.KAPU = os.path.join(root, 'store', 'kep-kapu')
    os.makedirs(mod.KAPU, exist_ok=True)
    video = os.path.join(root, 'reel.mp4')
    open(video, 'wb').write(b'synthetic video bytes')
    return mod, video


def write_cache(mod, video, missing, tool=None, seconds=4):
    d = os.path.join(mod.KAPU, '.ocr')
    os.makedirs(d, exist_ok=True)
    sha = mod._sha256(video)
    json.dump({'sha256': sha, 'tool': tool or mod.ocr_tool_id(), 'seconds': seconds, 'missing': missing},
              open(os.path.join(d, sha + '.json'), 'w'))


def no_ocr(*_a, **_k):
    raise AssertionError('the OCR ran although the cache was valid')


@case
def brand_cached_missing_second_blocked(root):
    mod, video = ocr_module(root)
    write_cache(mod, video, [3])
    mod.run_ocr = no_ocr
    r = mod.brand_check(video)
    return bool(r) and 'nincs "marabel.hu" a videó 3. másodpercében' in r and '1/4 s' in r


@case
def brand_cached_missing_ranges_listed(root):
    mod, video = ocr_module(root)
    write_cache(mod, video, [0, 1, 2, 5, 7, 8], seconds=10)
    mod.run_ocr = no_ocr
    r = mod.brand_check(video) or ''
    return '0-2, 5, 7-8. másodpercében' in r


@case
def brand_cached_all_present_passes(root):
    mod, video = ocr_module(root)
    write_cache(mod, video, [])
    mod.run_ocr = no_ocr
    return mod.brand_check(video) is None


@case
def brand_cache_of_another_helper_not_trusted(root):
    # A cache written by another OCR helper (or by hand with a made-up tool id) is not read: the OCR runs again.
    mod, video = ocr_module(root)
    write_cache(mod, video, [], tool='0000000000000000')
    mod.run_ocr = lambda fp, budget: {0: 'marabel.hu', 1: 'Anya, te hívtad el apát?', 2: 'MARABEL.HU/meseld-el'}
    r = mod.brand_check(video) or ''
    return '1. másodpercében' in r


@case
def brand_cache_of_another_video_not_trusted(root):
    mod, video = ocr_module(root)
    write_cache(mod, video, [])
    open(video, 'ab').write(b' re-exported')            # new bytes, new sha256: the old cache does not apply
    mod.run_ocr = lambda fp, budget: {0: 'Marabel', 1: 'marabel.hu'}
    r = mod.brand_check(video) or ''
    return '0. másodpercében' in r


@case
def brand_cache_copied_from_another_video_not_trusted(root):
    # A clean video's "all present" cache copied under this video's sha256 name: the sha inside must match too.
    mod, video = ocr_module(root)
    d = os.path.join(mod.KAPU, '.ocr')
    os.makedirs(d, exist_ok=True)
    json.dump({'sha256': '0' * 64, 'tool': mod.ocr_tool_id(), 'seconds': 2, 'missing': []},
              open(os.path.join(d, mod._sha256(video) + '.json'), 'w'))
    mod.run_ocr = lambda fp, budget: {0: 'marabel.hu', 1: 'nincs cím'}
    return '1. másodpercében' in (mod.brand_check(video) or '')


@case
def brand_text_match_ignores_case_and_spaces(root):
    mod, video = ocr_module(root)
    mod.run_ocr = lambda fp, budget: {0: 'MARABEL.HU', 1: 'marabel. hu', 2: 'x\nmarabel.hu/meseld-el'}
    return mod.brand_check(video) is None


@case
def brand_logo_word_alone_blocked(root):
    mod, video = ocr_module(root)
    mod.run_ocr = lambda fp, budget: {0: 'marabel.hu', 1: 'Marabel\nMeséld el!'}
    r = mod.brand_check(video) or ''
    return '1. másodpercében' in r


@case
def brand_result_is_cached(root):
    mod, video = ocr_module(root)
    calls = []
    mod.run_ocr = lambda fp, budget: calls.append(1) or {0: 'marabel.hu', 1: 'semmi'}
    first = mod.brand_check(video)
    second = mod.brand_check(video)
    return len(calls) == 1 and first == second and '1. másodpercében' in (first or '')


@case
def brand_ocr_error_blocks(root):
    mod, video = ocr_module(root)

    def boom(fp, budget):
        raise mod.OcrError('nincs macOS Vision / swiftc ezen a gépen')
    mod.run_ocr = boom
    r = mod.brand_check(video) or ''
    return 'nem futott le' in r and 'tilt' in r


@case
def brand_unexpected_error_blocks(root):
    mod, video = ocr_module(root)
    mod.run_ocr = lambda fp, budget: 1 / 0
    r = mod.brand_check(video) or ''
    return 'nem futott le (ZeroDivisionError)' in r


def fake_helper(root, body):
    path = os.path.join(root, 'fake_ocr')
    open(path, 'w').write('#!/bin/sh\n' + body + '\n')
    os.chmod(path, 0o700)
    return path


@case
def brand_ocr_timeout_blocks_with_warmup_hint(root):
    mod, video = ocr_module(root)
    helper = fake_helper(root, 'sleep 5')
    mod.ocr_binary = lambda _tid: helper
    r = mod.brand_check(video, budget=1) or ''
    return 'nem fért bele 1 s-be' in r and '--ocr' in r


@case
def brand_ocr_incomplete_output_blocks(root):
    mod, video = ocr_module(root)
    helper = fake_helper(root, 'echo \'{"t": 0, "text": "marabel.hu"}\'; echo \'{"done": 3}\'')
    mod.ocr_binary = lambda _tid: helper
    r = mod.brand_check(video) or ''
    return 'hiányos' in r


@case
def brand_ocr_no_done_line_blocks(root):
    mod, video = ocr_module(root)
    helper = fake_helper(root, 'echo \'{"t": 0, "text": "marabel.hu"}\'')
    mod.ocr_binary = lambda _tid: helper
    r = mod.brand_check(video) or ''
    return 'hiányos' in r


@case
def brand_ocr_helper_failure_blocks(root):
    mod, video = ocr_module(root)
    helper = fake_helper(root, 'echo \'{"done": 0}\'; exit 2')
    mod.ocr_binary = lambda _tid: helper
    r = mod.brand_check(video) or ''
    return 'hibával állt le' in r


class FakeResponse:
    def __init__(self, row):
        self.data = json.dumps(row).encode()

    def read(self, *_a):
        return self.data


@case
def marketing_video_check_runs_the_ocr(root):
    # Wiring: check() on a marketing video that passes every other line reaches brand_check(), and the MARKA line
    # (self-attested) does not let it through. Majsztro's MEHET and the SZERZO row are stubbed.
    mod = caption_check_setup(root)
    mod.run_ocr = lambda fp, budget: {0: 'marabel.hu', 1: 'Anya, te hívtad el apát?'}
    r = mod.check(os.path.join(root, 'short.mp4')) or ''
    return '1. másodpercében' in r


@case
def marketing_video_needs_no_marka_line(root):
    mod = caption_check_setup(root, marka=False)
    mod.run_ocr = lambda fp, budget: {0: 'marabel.hu', 1: 'MARABEL.HU'}
    return mod.check(os.path.join(root, 'short.mp4')) is None


@case
def marketing_image_still_needs_marka(root):
    img = book_fixture(root, KEPES_OK, majsztro=MARKETING, uzenet=UZENET_OK)
    mod = gate_module()
    mod.ROOT = root
    mod.KAPU = os.path.join(root, 'store', 'kep-kapu')
    mod.majsztro_ok = lambda _value: None
    mod.izles_ref = lambda _fp, _value: None  # IZLES-REF has its own cases (izles_*)
    return 'MARKA sor hiányzik' in (mod.check(img) or '')


def caption_check_setup(root, marka=True):
    mod = gate_module()
    mod.ROOT = root
    mod.KAPU = os.path.join(root, 'store', 'kep-kapu')
    mod.majsztro_ok = lambda _value: None
    mod.izles_ref = lambda _fp, _value: None  # IZLES-REF has its own cases (izles_*)
    os.makedirs(mod.KAPU, exist_ok=True)
    video = os.path.join(root, 'short.mp4')
    open(video, 'wb').write(b'\x00')
    sheet = os.path.join(root, 'feed.png')
    open(sheet, 'wb').write(b'\x89PNG')
    cap = os.path.join(root, 'posztszoveg.txt')
    open(cap, 'w', encoding='utf-8').write(ELSO_EVED_CAPTION)
    open(os.path.join(root, 'store', '.dashboard-token'), 'w').write('synthetic')
    body = mod.caption_body(ELSO_EVED_CAPTION)
    mod.urllib.request.urlopen = lambda req, timeout=5: FakeResponse({'from_agent': 'majsztro', 'content': ' '.join(body)})
    lines = ['KONYV: nincs', 'A5: nincs-konyv', 'PAPIR: nincs-konyv', 'SAJAT: nincs-konyv', 'KERES: teszt kérés, egyezik',
             'NAGYITVA: -', 'MAJSZTRO: MEHET 1', 'UZENET: friss szülők, akik fotóznak | most kezdődik az első év',
             f'FEED: ok {sheet}', f'POSZTSZOVEG: {cap}', SAV_9X16_OK]
    mod.media_size = lambda _fp: (1080, 1920)  # the video here is a 1-byte stub; the safe band has its own cases
    if marka:
        lines.append('MARKA: logó + marabel.hu látható a képen (jobb alsó sarok)')
    open(os.path.join(mod.KAPU, 'short.mp4.ok'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    later = time.time() + 5
    os.utime(sheet, (later, later))
    os.utime(os.path.join(mod.KAPU, 'short.mp4.ok'), (later, later))
    return mod


RENDER_SWIFT = r"""
import AppKit
let args = CommandLine.arguments
let img = NSImage(size: NSSize(width: 540, height: 960))
img.lockFocus()
NSColor.white.setFill(); NSRect(x: 0, y: 0, width: 540, height: 960).fill()
if args[2] != "" {
    let attrs: [NSAttributedString.Key: Any] = [.font: NSFont.boldSystemFont(ofSize: 56), .foregroundColor: NSColor.black]
    (args[2] as NSString).draw(at: NSPoint(x: 90, y: 440), withAttributes: attrs)
}
img.unlockFocus()
let rep = NSBitmapImageRep(data: img.tiffRepresentation!)!
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: args[1]))
"""


@case
def brand_real_vision_ocr_on_generated_video(root):
    """macOS only: 4 one-second shots, the third without the address -> the real helper reports second 2."""
    import shutil
    ffmpeg = shutil.which('ffmpeg') or '/opt/homebrew/bin/ffmpeg'
    if sys.platform != 'darwin' or not os.access(ffmpeg, os.X_OK) or not os.access('/usr/bin/swift', os.X_OK):
        print('SKIP brand_real_vision_ocr_on_generated_video (needs macOS, swift, ffmpeg)')
        return True
    src = os.path.join(root, 'render.swift')
    open(src, 'w').write(RENDER_SWIFT)
    text, blank = os.path.join(root, 'text.png'), os.path.join(root, 'blank.png')
    for out, t in ((text, 'marabel.hu'), (blank, '')):
        subprocess.run(['/usr/bin/swift', src, out, t], check=True, capture_output=True, timeout=120)
    video = os.path.join(root, 'reel.mp4')
    shots = [text, text, blank, text]
    cmd = [ffmpeg, '-v', 'error', '-y']
    for s in shots:
        cmd += ['-loop', '1', '-t', '1', '-framerate', '25', '-i', s]
    cmd += ['-filter_complex', f'concat=n={len(shots)}:v=1:a=0', '-pix_fmt', 'yuv420p', video]
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    mod = gate_module()
    mod.ROOT = root
    mod.KAPU = os.path.join(root, 'store', 'kep-kapu')
    r = mod.brand_check(video, budget=None) or ''
    ok = 'a videó 2. másodpercében (1/4 s' in r
    if not ok:
        print(f'  brand_real_vision_ocr_on_generated_video got: {r!r}')
    return ok



# SAFE BAND (Patrik privát TG 15669, 2026-11-08: "lathatonak kell lennie a fontos reszeknek scrollozasnal is.. levag
# alul felul vmennyit a fb"; CLAUDE.md BIZTONSÁGI SÁV; card c68d3745). 4:5: 10 % top and bottom; 9:16: 14 % top,
# 35 % bottom. The gate measures the file itself; the images here are real PNG headers of the given size.
def png(path, w, h):
    import struct
    import zlib
    ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    chunk = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xFFFFFFFF)
    open(path, 'wb').write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IEND', b''))
    return path


def sav_check(root, w, h, sav, name='poszt.png'):
    """check() on a marketing image without a book whose only open question is the SAV line. Majsztro's MEHET is
    stubbed; the next check after SAV for an image is ARC-ITELET, so a result naming ARC-ITELET means SAV passed."""
    mod = gate_module()
    mod.ROOT = root
    mod.KAPU = os.path.join(root, 'store', 'kep-kapu')
    mod.majsztro_ok = lambda _value: None
    mod.izles_ref = lambda _fp, _value: None  # IZLES-REF has its own cases (izles_*)
    os.makedirs(mod.KAPU, exist_ok=True)
    img = os.path.join(root, name)
    if w:
        png(img, w, h)
    else:
        open(img, 'wb').write(b'\x89PNG')  # not measurable
    lines = ['KONYV: nincs', 'A5: nincs-konyv', 'PAPIR: nincs-konyv', 'SAJAT: nincs-konyv', 'KERES: teszt kérés, egyezik',
             'NAGYITVA: -', 'MAJSZTRO: MEHET 1', 'UZENET: friss szülők, akik fotóznak | most kezdődik az első év',
             'MARKA: logó + marabel.hu látható a képen (jobb alsó sarok)']
    if sav is not None:
        lines.append(f'SAV: {sav}')
    okf = os.path.join(mod.KAPU, name + '.ok')
    open(okf, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    later = time.time() + 5
    os.utime(okf, (later, later))
    return mod.check(img) or ''


@case
def sav_missing_blocked(root):
    return 'SAV sor hiányzik' in sav_check(root, 1080, 1350, None)


@case
def sav_malformed_blocked(root):
    return 'SAV sor hiányzik' in sav_check(root, 1080, 1350, '4x5 rendben, minden belül van')


@case
def sav_4x5_inside_passes(root):
    r = sav_check(root, 1080, 1350, '4x5 felso 135 also 135 140-1210')
    return 'SAV' not in r and 'ARC-ITELET' in r


@case
def sav_4x5_accented_words_pass(root):
    r = sav_check(root, 1080, 1350, '4x5 felső 135 alsó 135 135-1215')
    return 'SAV' not in r and 'ARC-ITELET' in r


@case
def sav_4x5_top_band_blocked(root):
    return 'belelóg a levágott sávba' in sav_check(root, 1080, 1350, '4x5 felso 135 also 135 100-1200')


@case
def sav_4x5_bottom_band_blocked(root):
    return 'belelóg a levágott sávba' in sav_check(root, 1080, 1350, '4x5 felso 135 also 135 200-1250')


@case
def sav_9x16_inside_passes(root):
    r = sav_check(root, 1080, 1920, '9x16 felso 269 also 672 430-1240')
    return 'SAV' not in r and 'ARC-ITELET' in r


@case
def sav_9x16_feed_crop_top_blocked(root):
    # Dave 36310 / Klodel 36308: the Reel C v10 closing logo at y 290 is inside the Reel band (269-1248) but under the
    # FB feed's 4:5 centre crop top band (crop 285-1635, free 420-1500). The negative test of the miss.
    r = sav_check(root, 1080, 1920, '9x16 felso 269 also 672 290-1231')
    return '4:5 középső vágata' in r and '420-1248' in r


@case
def sav_9x16_feed_crop_edges(root):
    # 420 is the first free row of the feed crop, 1248 the last of the Reel band: the common part passes, one row out fails.
    ok_ = sav_check(root, 1080, 1920, '9x16 felso 269 also 672 420-1248')
    out = sav_check(root, 1080, 1920, '9x16 felso 269 also 672 419-1248')
    return 'SAV' not in ok_ and 'ARC-ITELET' in ok_ and '4:5 középső vágata' in out


@case
def sav_9x16_bottom_35_blocked(root):
    # Fine for a 4:5 band (1920*0.9=1728) but inside the Reel's bottom 35 % (from 1248 down).
    return 'belelóg a levágott sávba' in sav_check(root, 1080, 1920, '9x16 felso 269 also 672 300-1300')


@case
def sav_9x16_top_14_blocked(root):
    return 'belelóg a levágott sávba' in sav_check(root, 1080, 1920, '9x16 felso 269 also 672 200-1200')


@case
def sav_format_must_fit_the_file(root):
    return 'ez 9x16' in sav_check(root, 1080, 1920, '4x5 felso 192 also 192 300-1200')


@case
def sav_band_px_must_fit_the_height(root):
    # 10 % of 1350 is 135: a maker who measured the bands on another height is stopped.
    return 'a sorban 100/100' in sav_check(root, 1080, 1350, '4x5 felso 100 also 100 140-1200')


@case
def sav_upright_other_ratio_blocked(root):
    # 2:3 upright is none of 4:5, 9:16, 1:1: blocked (Klodel 31805 opened only 1:1 and landscape).
    return 'se 4:5, se 9:16' in sav_check(root, 1080, 1620, '4x5 felso 162 also 162 200-1400')


@case
def sav_1x1_inside_passes(root):
    # Klodel 31805: 1:1 gets 10 % / 10 % like 4:5 (108 px on 1080).
    r = sav_check(root, 1080, 1080, '1x1 felso 108 also 108 110-970')
    return 'SAV' not in r and 'ARC-ITELET' in r


@case
def sav_1x1_top_band_blocked(root):
    return 'belelóg a levágott sávba' in sav_check(root, 1080, 1080, '1x1 felso 108 also 108 100-900')


@case
def sav_1x1_band_px_must_fit(root):
    # a 9:16-style 14/35 % band on a square is wrong: 151/378 instead of 108/108
    return 'a sorban 151/378' in sav_check(root, 1080, 1080, '1x1 felso 151 also 378 200-600')


@case
def sav_landscape_inside_passes(root):
    # 1200x628 link image: 10 % of 628 = 63 px, free 63-565.
    r = sav_check(root, 1200, 628, 'fekvo felso 63 also 63 70-560')
    return 'SAV' not in r and 'ARC-ITELET' in r


@case
def sav_landscape_accented_word_passes(root):
    r = sav_check(root, 1920, 1080, 'fekvő felső 108 alsó 108 120-960')
    return 'SAV' not in r and 'ARC-ITELET' in r


@case
def sav_landscape_bottom_band_blocked(root):
    return 'belelóg a levágott sávba' in sav_check(root, 1200, 628, 'fekvo felso 63 also 63 70-600')


@case
def sav_landscape_file_called_square_blocked(root):
    return 'ez fekvo' in sav_check(root, 1200, 628, '1x1 felso 63 also 63 70-560')


@case
def sav_square_file_called_4x5_blocked(root):
    return 'ez 1x1' in sav_check(root, 1080, 1080, '4x5 felso 108 also 108 200-900')


@case
def sav_unmeasurable_file_blocked(root):
    return 'nem mérhető' in sav_check(root, 0, 0, '4x5 felso 135 also 135 140-1200')


@case
def sav_box_outside_the_image_blocked(root):
    return 'nem fér' in sav_check(root, 1080, 1350, '4x5 felso 135 also 135 1210-140')


@case
def sav_not_asked_on_non_marketing(root):
    img = book_fixture(root, KEPES_OK)  # MAJSZTRO: nem-marketing, no SAV line
    rc, err = run(root, {'chat_id': GROUP, 'text': 'x', 'files': [img]})
    return rc == 0 and 'SAV' not in err


@case
def sav_webp_and_gif_headers_measured(root):
    import struct
    mod = gate_module()
    vp8x = b'RIFF' + struct.pack('<I', 30) + b'WEBPVP8X' + struct.pack('<I', 10) + b'\x00' * 4 \
        + (1080 - 1).to_bytes(3, 'little') + (1350 - 1).to_bytes(3, 'little')
    bits = (1080 - 1) | ((1920 - 1) << 14)
    vp8l = b'RIFF' + struct.pack('<I', 30) + b'WEBPVP8L' + struct.pack('<I', 10) + b'\x2f' + bits.to_bytes(4, 'little') + b'\x00' * 8
    gif = b'GIF89a' + struct.pack('<HH', 1080, 1350) + b'\x00' * 8
    out = []
    for name, data in (('x.webp', vp8x), ('y.webp', vp8l), ('z.gif', gif)):
        fp = os.path.join(root, name)
        open(fp, 'wb').write(data)
        out.append(mod.image_size(fp))
    return out == [(1080, 1350), (1080, 1920), (1080, 1350)]


@case
def sav_real_video_measured_with_ffprobe(root):
    # A real 9:16 mp4 through media_size() and check(): the next line after SAV for a video is FEED. Skipped where
    # there is no ffmpeg (CI on Linux without it).
    import shutil as sh
    ffmpeg = sh.which('ffmpeg') or next((p for p in ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg') if os.path.exists(p)), None)
    if not ffmpeg:
        print('  (skip: no ffmpeg)')
        return True
    video = os.path.join(root, 'reel.mp4')
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=white:s=1080x1920:d=1', '-pix_fmt',
                    'yuv420p', video], check=True, timeout=60)
    mod = gate_module()
    mod.ROOT = root
    mod.KAPU = os.path.join(root, 'store', 'kep-kapu')
    mod.majsztro_ok = lambda _value: None
    mod.izles_ref = lambda _fp, _value: None  # IZLES-REF has its own cases (izles_*)
    os.makedirs(mod.KAPU, exist_ok=True)
    if mod.media_size(video) != (1080, 1920):
        return False
    base = ['KONYV: nincs', 'A5: nincs-konyv', 'PAPIR: nincs-konyv', 'SAJAT: nincs-konyv', 'KERES: teszt kérés, egyezik',
            'NAGYITVA: -', 'MAJSZTRO: MEHET 1', 'UZENET: friss szülők, akik fotóznak | most kezdődik az első év']
    results = []
    for sav in ('9x16 felso 269 also 672 430-1240', '9x16 felso 269 also 672 430-1700'):
        okf = os.path.join(mod.KAPU, 'reel.mp4.ok')
        open(okf, 'w', encoding='utf-8').write('\n'.join(base + [f'SAV: {sav}']) + '\n')
        later = time.time() + 5
        os.utime(okf, (later, later))
        results.append(mod.check(video) or '')
    return 'FEED' in results[0] and 'SAV' not in results[0] and 'belelóg a levágott sávba' in results[1]

# Klodel 32029 (2026-11-08): "ELRENDEZES: kulon-elem <indok>" -- the book next to the photo as its own layout
# element. KEZ becomes optional only on an in-band head MERCE, or on "nincs-ember" in A5 ratio + VALODI: igen.
LAYOUT = 'ELRENDEZES: kulon-elem a könyv a fotó mellett áll, nem jelenetben az emberrel'


def layout_run(root, merce, kez=None, valodi=VALODI_OK, layout=LAYOUT):
    img = book_fixture(root, KEPES_OK, merce=merce, kez=kez, valodi=valodi, extra=(layout,) if layout else ())
    return run(root, {'chat_id': GROUP, 'text': 'x', 'files': [img]})


@case
def layout_head_in_band_without_kez_allowed(root):
    rc, _ = layout_run(root, 'zart 95/100')  # Klodel 32029: Rozi frame, head ratio 0.95
    return rc == 0


@case
def layout_head_in_band_kez_nincs_allowed(root):
    rc, _ = layout_run(root, 'zart 110/100', kez='nincs')  # baby frame, 1.10, no adult hand
    return rc == 0


@case
def layout_open_head_in_band_without_kez_allowed(root):
    rc, _ = layout_run(root, 'nyitott 300/170')
    return rc == 0


@case
def no_layout_head_without_kez_still_blocked(root):
    rc, err = layout_run(root, 'zart 95/100', layout=None)  # negative: without ELRENDEZES the rule stays
    return rc == 2 and 'KEZ hiányzik/hibás' in err


@case
def no_layout_head_kez_nincs_still_blocked(root):
    rc, err = layout_run(root, 'zart 95/100', kez='nincs semmi, a fejhez mértem csak', layout=None)
    return rc == 2 and 'KEZ: nincs, de a MERCE fejhez mért' in err


@case
def layout_head_out_of_band_blocked(root):
    rc, err = layout_run(root, 'zart 150/100')  # 1.50: not A5 against the head, ELRENDEZES does not help
    return rc == 2 and 'fejhez mérve' in err


@case
def layout_measured_kez_out_of_band_still_blocked(root):
    rc, err = layout_run(root, 'zart 95/100', kez='zart 227/100')  # a measured KEZ is still checked
    return rc == 2 and 'kézhez mérve' in err


@case
def layout_no_person_a5_without_kez_allowed(root):
    rc, _ = layout_run(root, 'nincs-ember zart 444/630')
    return rc == 0


@case
def layout_no_person_wrong_ratio_blocked(root):
    rc, err = layout_run(root, 'nincs-ember nyitott 1000/630')
    return rc == 2 and 'A5-ös keménytábla' in err


@case
def layout_no_person_without_valodi_blocked(root):
    rc, err = layout_run(root, 'nincs-ember zart 444/630', valodi=None)
    return rc == 2 and 'VALODI' in err


@case
def layout_profile_still_needs_hand(root):
    rc, err = layout_run(root, 'profil nyitott 300/200')
    return rc == 2 and 'KEZ' in err


@case
def layout_short_reason_blocked(root):
    rc, err = layout_run(root, 'zart 95/100', layout='ELRENDEZES: kulon-elem rövid')
    return rc == 2 and 'ELRENDEZES sor hibás' in err


@case
def layout_wrong_keyword_blocked(root):
    rc, err = layout_run(root, 'zart 95/100', layout='ELRENDEZES: jelenet a könyv az ember kezében van most')
    return rc == 2 and 'ELRENDEZES sor hibás' in err



# Klodel 33823 (2026-11-09): while Majsztro's weekly budget is at 100 % Klodel writes the caption in his place,
# "SZERZO: helyettes-klodel <indok>"; the MAJSZTRO line has accepted "helyettes-klodel" since 2026-11-07. Both use
# majsztro_budget_full(), which reads store/mod-state/majsztro.json (synthetic here).
SUB_CAPTION = 'Mikor mosolygott rád először?\nMeséld el az első évét.\n\nmarabel.hu\n\nSZERZO: helyettes-klodel Májsztró heti kerete elfogyott\n'


def budget(root, pct):
    os.makedirs(os.path.join(root, 'store', 'mod-state'), exist_ok=True)
    json.dump({'usage': {'rateLimits': [{'kind': 'five_hour', 'percentUsed': 0},
                                        {'kind': 'seven_day', 'percentUsed': pct}]}},
              open(os.path.join(root, 'store', 'mod-state', 'majsztro.json'), 'w'))


def sub_caption_run(root, pct, caption=SUB_CAPTION):
    mod = caption_check_setup(root)
    if pct is not None:
        budget(root, pct)
    open(os.path.join(root, 'posztszoveg.txt'), 'w', encoding='utf-8').write(caption)
    mod.urllib.request.urlopen = lambda req, timeout=5: (_ for _ in ()).throw(AssertionError('no queue read'))
    mod.run_ocr = lambda fp, budget: {0: 'marabel.hu', 1: 'marabel.hu'}
    return mod.check(os.path.join(root, 'short.mp4'))


@case
def caption_substitute_passes_at_full_budget(root):
    return sub_caption_run(root, 100) is None


@case
def caption_substitute_blocked_below_full_budget(root):
    r = sub_caption_run(root, 99) or ''
    return 'helyettes-klodel csak akkor' in r


@case
def caption_substitute_blocked_without_budget_file(root):
    r = sub_caption_run(root, None) or ''
    return 'helyettes-klodel csak akkor' in r


@case
def caption_substitute_needs_reason(root):
    r = sub_caption_run(root, 100, SUB_CAPTION.replace(' Májsztró heti kerete elfogyott', ' x')) or ''
    return 'indok nélkül' in r


@case
def caption_other_author_still_blocked_at_full_budget(root):
    r = sub_caption_run(root, 100, SUB_CAPTION.replace('helyettes-klodel', 'kernel')) or ''
    return 'nincs "SZERZO: majsztro <msg_id>"' in r


@case
def majsztro_line_substitute_follows_budget(root):
    mod = gate_module()
    mod.ROOT = root
    budget(root, 100)
    full = mod.majsztro_ok('helyettes-klodel Májsztró heti kerete elfogyott') is None
    budget(root, 80)
    low = 'helyettes-klodel csak akkor' in (mod.majsztro_ok('helyettes-klodel Májsztró heti kerete elfogyott') or '')
    return full and low


@case
def majsztro_substitute_on_five_hour_window(root):
    import datetime as dt
    mod = gate_module()
    mod.ROOT = root
    os.makedirs(os.path.join(root, 'store', 'mod-state'), exist_ok=True)
    f = os.path.join(root, 'store', 'mod-state', 'majsztro.json')
    fut = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat().replace('+00:00', 'Z')
    past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).isoformat().replace('+00:00', 'Z')
    json.dump({'usage': {'rateLimits': [{'kind': 'five_hour', 'percentUsed': 100, 'resetsAt': fut},
                                        {'kind': 'seven_day', 'percentUsed': 50}]}}, open(f, 'w'))
    out = mod.majsztro_budget_full()
    json.dump({'usage': {'rateLimits': [{'kind': 'five_hour', 'percentUsed': 100, 'resetsAt': past},
                                        {'kind': 'seven_day', 'percentUsed': 50}]}}, open(f, 'w'))
    reset = mod.majsztro_budget_full()
    json.dump({'usage': {'rateLimits': [{'kind': 'five_hour', 'percentUsed': 90, 'resetsAt': fut},
                                        {'kind': 'seven_day', 'percentUsed': 50}]}}, open(f, 'w'))
    partial = mod.majsztro_budget_full()
    return out and not reset and not partial


# IZLES-REF (Patrik TG 4793, 2026-11-10, Klodel 36836): a marketing piece goes to Patrik only next to an earlier piece
# he praised. Synthetic ledger (store/claudeclaw.db under the throw-away root): inbound 4741 in a group chat, and an
# OUTBOUND 5555 (our own reply: not a praise).
def izles_setup(root, ledger=True):
    import sqlite3
    mod = gate_module()
    mod.ROOT = root
    os.makedirs(os.path.join(root, 'store'), exist_ok=True)
    if ledger:
        con = sqlite3.connect(os.path.join(root, 'store', 'claudeclaw.db'))
        con.execute('CREATE TABLE conversation_log (id INTEGER PRIMARY KEY, agent_id TEXT, chat_id TEXT, direction TEXT, '
                    'message_id TEXT, text TEXT, ts TEXT, created_at INTEGER, source TEXT)')
        con.execute("INSERT INTO conversation_log (agent_id, chat_id, direction, message_id, created_at, source) "
                    "VALUES ('klodel', ?, 'in', '4741', 1, 'plugin:telegram:telegram')", (GROUP,))
        con.execute("INSERT INTO conversation_log (agent_id, chat_id, direction, message_id, created_at, source) "
                    "VALUES ('klodel', ?, 'out', '5555', 1, 'plugin:telegram:telegram')", (GROUP,))
        con.commit()
        con.close()
    paths = {}
    for name in ('uj.png', 'dicsert.png', 'osszevetes.png'):
        paths[name] = os.path.join(root, name)
        open(paths[name], 'wb').write(b'\x89PNG')
    now = time.time()
    os.utime(paths['dicsert.png'], (now - 86400, now - 86400))
    os.utime(paths['uj.png'], (now - 60, now - 60))
    os.utime(paths['osszevetes.png'], (now, now))
    return mod, paths


def izles_line(p, tg='4741', ref=None, cmp_=None):
    return f"{ref or p['dicsert.png']} | {tg} | {cmp_ or p['osszevetes.png']}"


def izles(root, value=None, ledger=True, **kw):
    mod, p = izles_setup(root, ledger)
    return mod.izles_ref(p['uj.png'], izles_line(p, **kw) if value is None else value) or ''


@case
def izles_valid_passes(root):
    return izles(root) == ''


@case
def izles_tg_prefix_passes(root):
    return izles(root, tg='TG 4741') == ''


@case
def izles_missing_line_blocked(root):
    return 'IZLES-REF sor hiányzik' in izles(root, value='')


@case
def izles_nincs_blocked(root):
    return 'IZLES-REF: nincs' in izles(root, value='nincs')


@case
def izles_nincs_with_reason_blocked(root):
    return 'IZLES-REF: nincs' in izles(root, value='nincs, még semmit nem dicsért')


@case
def izles_two_parts_blocked(root):
    mod, p = izles_setup(root)
    return 'sor hibás' in (mod.izles_ref(p['uj.png'], f"{p['dicsert.png']} | 4741") or '')


@case
def izles_empty_part_blocked(root):
    mod, p = izles_setup(root)
    return 'sor hibás' in (mod.izles_ref(p['uj.png'], f"{p['dicsert.png']} |  | {p['osszevetes.png']}") or '')


@case
def izles_missing_reference_file_blocked(root):
    return 'referencia-fájl nem létezik' in izles(root, ref=os.path.join(root, 'nincs-ilyen.png'))


@case
def izles_reference_not_media_blocked(root):
    txt = os.path.join(root, 'dicseret.txt')
    open(txt, 'w').write('szép')
    return 'nem kép/videó' in izles(root, ref=txt)


@case
def izles_reference_is_the_file_blocked(root):
    return 'maga a vizsgált fájl' in izles(root, ref=os.path.join(root, 'uj.png'))


@case
def izles_tg_not_a_number_blocked(root):
    return 'nem szám' in izles(root, tg='tegnap')


@case
def izles_tg_unknown_id_blocked(root):
    return 'nincs a bejövő naplóban' in izles(root, tg='9999')


@case
def izles_tg_outbound_only_blocked(root):
    return 'nincs a bejövő naplóban' in izles(root, tg='5555')


@case
def izles_no_ledger_blocked(root):
    return 'nincs a bejövő naplóban' in izles(root, ledger=False)


@case
def izles_missing_comparison_blocked(root):
    return 'összehasonlító kép nem létezik' in izles(root, cmp_=os.path.join(root, 'nincs.png'))


@case
def izles_comparison_not_an_image_blocked(root):
    vid = os.path.join(root, 'osszevetes.mp4')
    open(vid, 'wb').write(b'\x00')
    return 'nem kép' in izles(root, cmp_=vid)


@case
def izles_comparison_is_the_reference_blocked(root):
    return 'külön lap legyen' in izles(root, cmp_=os.path.join(root, 'dicsert.png'))


@case
def izles_comparison_older_than_file_blocked(root):
    mod, p = izles_setup(root)
    old = time.time() - 3600
    os.utime(p['osszevetes.png'], (old, old))
    return 'nem frissebb' in (mod.izles_ref(p['uj.png'], izles_line(p)) or '')


@case
def izles_comparison_same_mtime_blocked(root):
    mod, p = izles_setup(root)
    t = os.path.getmtime(p['uj.png'])
    os.utime(p['osszevetes.png'], (t, t))
    return 'nem frissebb' in (mod.izles_ref(p['uj.png'], izles_line(p)) or '')


def izles_check_run(root, line):
    """The whole check() on a marketing video (caption_check_setup) with the REAL izles_ref, bound to this root."""
    mod = caption_check_setup(root)
    real, p = izles_setup(root)
    mod.izles_ref = real.izles_ref
    mod.run_ocr = lambda fp, budget: {0: 'marabel.hu', 1: 'marabel.hu'}
    okf = os.path.join(mod.KAPU, 'short.mp4.ok')
    if line is not None:
        open(okf, 'a', encoding='utf-8').write(f'IZLES-REF: {line(p)}\n')
    later = time.time() + 5
    os.utime(okf, (later, later))
    os.utime(p['osszevetes.png'], (later, later))
    return mod.check(os.path.join(root, 'short.mp4')) or ''


@case
def izles_marketing_video_without_line_blocked(root):
    return 'IZLES-REF sor hiányzik' in izles_check_run(root, None)


@case
def izles_marketing_video_nincs_blocked(root):
    return 'IZLES-REF: nincs' in izles_check_run(root, lambda p: 'nincs')


@case
def izles_marketing_video_with_reference_passes(root):
    return izles_check_run(root, izles_line) == ''


@case
def izles_not_asked_on_non_marketing(root):
    # book_fixture is "MAJSZTRO: nem-marketing" and carries no IZLES-REF line: allowed as before.
    img = book_fixture(root, KEPES_OK)
    rc, err = run(root, {'chat_id': GROUP, 'text': 'x', 'files': [img]})
    return rc == 0 and 'IZLES-REF' not in err


PRIV_OK ='PRIVÁT-OK: Patrik privátban kérdezte, privát ügy\n'
IDEA_LINE = 'ÖTLET-KAPU: nem Marabel/könyv, termékpaletta ellenőrizve (6 termékkel összevetve)\n'


@case
def idea_private_without_line_blocked(root):
    rc, err = run(root, {'chat_id': PRIV, 'text': PRIV_OK + 'Van egy új ötletem: könyv a kutyáknak.'})
    return rc == 2 and 'ÖTLET-KAPU' in err and 'new-direction-start-from-market' in err


@case
def idea_private_forms_blocked(root):
    # ötletek / ötletet / capitalised Ötlet all count
    texts = ('Három ötletek jönnek.', 'Hoztam egy ötletet.', 'Ötlet: AI-tanácsadás.')
    return all(run(root, {'chat_id': PRIV, 'text': PRIV_OK + t})[0] == 2 for t in texts)


@case
def idea_private_decomposed_accent_blocked(root):
    # NFD "ötlet" (o + combining diaeresis) is the same word
    rc, _ = run(root, {'chat_id': PRIV, 'text': PRIV_OK + 'Egy ötlet.'})
    return rc == 2


@case
def idea_private_half_line_blocked(root):
    # only one of the two statements: not enough
    rc, _ = run(root, {'chat_id': PRIV, 'text': PRIV_OK + 'ÖTLET-KAPU: nem Marabel/könyv\nÚj ötlet.'})
    return rc == 2


@case
def idea_private_with_line_allowed(root):
    rc, _ = run(root, {'chat_id': PRIV, 'text': PRIV_OK + IDEA_LINE + 'Új ötlet: X piac, Y vevő.'})
    return rc == 0


@case
def idea_private_window_open_still_gated(root):
    window(root, time.time() + 3600)
    blocked = run(root, {'chat_id': PRIV, 'text': 'Új ötlet: X.'})[0] == 2
    allowed = run(root, {'chat_id': PRIV, 'text': IDEA_LINE + 'Új ötlet: X.'})[0] == 0
    return blocked and allowed


@case
def idea_group_gated(root):
    # Patrik csoport TG 4978: the group is gated too, and "irány" triggers like "ötlet".
    rc, _ = run(root, {'chat_id': GROUP, 'text': 'Négy új irány: évkönyv.'})
    rc2, _ = run(root, {'chat_id': GROUP, 'text': 'Új irány.\nÖTLET-KAPU: nem Marabel/könyv, termékpaletta ellenőrizve: 6 termék'})
    rc3, _ = run(root, {'chat_id': GROUP, 'text': 'Radar dolgozik.'})
    rc4, _ = run(root, {'chat_id': GROUP, 'text': '📊 ÉLŐ ÁLLAPOT · frissítve 10:31\nÚj üzletág: új irány'})
    return rc == 2 and rc2 == 0 and rc3 == 0 and rc4 == 0


@case
def no_idea_private_unchanged(root):
    rc, _ = run(root, {'chat_id': PRIV, 'text': PRIV_OK + 'Kész a riport.'})
    return rc == 0


def main():
    bad = 0
    for fn in CASES:
        with tempfile.TemporaryDirectory() as root:
            ok = fn(root)
        print(('PASS ' if ok else 'FAIL ') + fn.__name__)
        bad += not ok
    print(f'{len(CASES) - bad}/{len(CASES)} pass')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
