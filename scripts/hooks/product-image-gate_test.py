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


import re as _re
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib'))
import reply_marks  # noqa: E402

_MARK_LINE = _re.compile(r'(?m)^(PRIVÁT-OK|BALÁZS-KÉRÉS):[ \t]*(.*)\n?')
_MARK_KIND = {'PRIVÁT-OK': 'PRIVAT-OK', 'BALÁZS-KÉRÉS': 'BALAZS-KERES'}


def as_marks(root, tool_input, agent):
    """Klodel 40845 / Viktor 40894: a marker is a reply mark in the ledger, not a line of the text. The cases below
    were written with marker lines; this turns each into a mark for the same chat and agent, and drops the line."""
    os.environ['REPLY_MARKS_PATH'] = os.path.join(root, 'store', 'reply-marks.jsonl')
    ti = dict(tool_input)
    text = ti.get('text')
    if isinstance(text, str):
        for kind, value in _MARK_LINE.findall(text):
            try:
                reply_marks.add(_MARK_KIND[kind], ti.get('chat_id'), agent, value)
            except ValueError:
                pass  # e.g. too short: no mark, as an unreadable marker line was no reason
        ti['text'] = _MARK_LINE.sub('', text)
    return ti


def run(root, tool_input, raw=False):
    # LEDGER_DB_PATH points at a file that does not exist: the live ledger never decides a case (card 9df14a4c).
    env = {'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root, 'MARVEEN_OWNER_PRIVATE_CHAT': PRIV,
           'LEDGER_DB_PATH': os.path.join(root, 'nincs-ledger.db'), 'MARVEEN_AGENT_ID': 'klodel',
           'REPLY_MARKS_PATH': os.path.join(root, 'store', 'reply-marks.jsonl')}
    ti = tool_input if raw else as_marks(root, tool_input, 'klodel')
    p = subprocess.run([sys.executable, '-I', HOOK], input=json.dumps({'tool_input': ti}),
                       capture_output=True, text=True, env=env, timeout=20)
    return p.returncode, p.stderr


def run_tool(root, tool_name, tool_input, raw=False):
    env = {'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root, 'MARVEEN_OWNER_PRIVATE_CHAT': PRIV,
           'LEDGER_DB_PATH': os.path.join(root, 'nincs-ledger.db'), 'MARVEEN_AGENT_ID': 'klodel',
           'REPLY_MARKS_PATH': os.path.join(root, 'store', 'reply-marks.jsonl')}
    ti = tool_input if raw else as_marks(root, tool_input, 'klodel')
    p = subprocess.run([sys.executable, '-I', HOOK], input=json.dumps({'tool_name': tool_name, 'tool_input': ti}),
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
SAV_9X16_OK = 'SAV: 9x16 felso 269 also 672 430-1240'  # inside the Reel band (269-1248)
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
def private_media_not_held_window_open(root):
    # Patrik privát TG 18453 (2026-11-13): "Akkor azt a kaput nagyon gyorsan kiiktatni". Media to the owner's
    # PRIVATE chat is not held by the media checks: he reviews it himself.
    window(root, time.time() + 3600)
    img = os.path.join(root, 'kep.png')
    open(img, 'wb').write(b'\x89PNG')
    rc, err = run(root, {'chat_id': PRIV, 'text': 'Kész a kép.', 'files': [img]})
    return rc == 0 and err == ''


@case
def NEG_group_media_still_checked(root):
    # The same image without its attestation to the GROUP: the full media check stays.
    img = os.path.join(root, 'kep.png')
    open(img, 'wb').write(b'\x89PNG')
    rc, err = run(root, {'chat_id': GROUP, 'text': 'Kész a kép.', 'files': [img]})
    return rc == 2 and 'nincs ellenőrző lap' in err


@case
def window_overflow_until_closed(root):
    # Viktor 29457 (1): {"until": 1e400 as an int} made float() raise OverflowError, the hook exited 1 with a
    # traceback, and exit 1 does not block -- not even the media check. Now: closed, exit 2.
    window(root, None, raw='{"until": 1' + '0' * 400 + ', "ok": "' + REASON + '"}')
    rc, err = run(root, {'chat_id': PRIV, 'text': 'Kész a kép.'})
    return rc == 2 and 'PRIVÁT-KAPU' in err and 'Traceback' not in err


@case
def private_media_not_held_window_overflow(root):
    # A broken window file does not crash the hook (Viktor 29457), and private media passes (TG 18453).
    window(root, None, raw='{"until": 1' + '0' * 400 + ', "ok": "' + REASON + '"}')
    img = os.path.join(root, 'kep.png')
    open(img, 'wb').write(b'\x89PNG')
    rc, err = run(root, {'chat_id': PRIV, 'text': 'PRIVÁT-OK: ' + REASON + '\nKész a kép.', 'files': [img]})
    return rc == 0 and 'Traceback' not in err


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
def sav_9x16_reel_band_only_the_old_feed_crop_case_passes(root):
    # Patrik TG 5732 (Klodel 40094): "egyedül arra kell figyelni h reels és hogy ha kimaszkolnak vmit akkor ne takarjon
    # ki". The Reel C v10 logo at y 290 is inside the Reel band (269-1248): it passes now, no 4:5 feed-crop check.
    r = sav_check(root, 1080, 1920, '9x16 felso 269 also 672 290-1231')
    return 'SAV' not in r and '4:5 középső vágata' not in r and 'ARC-ITELET' in r


@case
def NEG_sav_9x16_reel_band_edges_still_block(root):
    # The Reel band itself still holds: 269-1248 passes, one row out at either end blocks.
    ok_ = sav_check(root, 1080, 1920, '9x16 felso 269 also 672 269-1248')
    top = sav_check(root, 1080, 1920, '9x16 felso 269 also 672 268-1248')
    bot = sav_check(root, 1080, 1920, '9x16 felso 269 also 672 269-1249')
    return ('SAV' not in ok_ and 'belelóg a levágott sávba' in top and 'belelóg a levágott sávba' in bot)


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


def run_idea(root, tool_input, raw=False):
    """run() with store/mod-state/majsztro.json at 100 % (synthetic): the idea cases carry "MAJSZTRO: helyettes-klodel",
    because a subprocess run cannot reach the queue for a "MAJSZTRO: MEHET <id>" (those are in-process, idea_majsztro_*)."""
    budget(root, 100)
    return run(root, tool_input, raw=raw)


MJ = '\nMAJSZTRO: helyettes-klodel teszt, Májsztró kerete 100 %-on'


PRIV_OK ='PRIVÁT-OK: Patrik privátban kérdezte, privát ügy\n'
IDEA_LINE = ('ÖTLET-KAPU: nem Marabel/könyv, termékpaletta ellenőrizve (6 termékkel összevetve)\nATNEZO: MEHET a1b2c3d4e5\n'
             'MAJSZTRO: helyettes-klodel teszt, Májsztró kerete 100 %-on\n')


@case
def idea_private_without_line_blocked(root):
    rc, err = run_idea(root, {'chat_id': PRIV, 'text': PRIV_OK + 'Van egy új ötletem: könyv a kutyáknak.'})
    return rc == 2 and 'ÖTLET-KAPU' in err and 'new-direction-start-from-market' in err


@case
def idea_private_forms_blocked(root):
    # ötletek / ötletet / capitalised Ötlet all count
    texts = ('Három ötletek jönnek.', 'Hoztam egy ötletet.', 'Ötlet: AI-tanácsadás.')
    return all(run_idea(root, {'chat_id': PRIV, 'text': PRIV_OK + t})[0] == 2 for t in texts)


@case
def idea_private_decomposed_accent_blocked(root):
    # NFD "ötlet" (o + combining diaeresis) is the same word
    rc, _ = run_idea(root, {'chat_id': PRIV, 'text': PRIV_OK + 'Egy ötlet.'})
    return rc == 2


@case
def idea_private_half_line_blocked(root):
    # only one of the two statements: not enough
    rc, _ = run_idea(root, {'chat_id': PRIV, 'text': PRIV_OK + 'ÖTLET-KAPU: nem Marabel/könyv\nÚj ötlet.'})
    return rc == 2


@case
def idea_private_with_line_allowed(root):
    rc, _ = run_idea(root, {'chat_id': PRIV, 'text': PRIV_OK + IDEA_LINE + 'Új ötlet: X piac, Y vevő.'})
    return rc == 0


@case
def idea_private_window_open_still_gated(root):
    window(root, time.time() + 3600)
    blocked = run_idea(root, {'chat_id': PRIV, 'text': 'Új ötlet: X.'})[0] == 2
    allowed = run_idea(root, {'chat_id': PRIV, 'text': IDEA_LINE + 'Új ötlet: X.'})[0] == 0
    return blocked and allowed


@case
def idea_irany_word_start_only(root):
    # Klodel 37827: "irány" only at a word start, not the verb irányít-; "ötlet" stays a substring (üzletötlet).
    neg = ['A WP-oldalakról 301-es átirányítás megy a Next.js-re.', 'Útirány: Budapest.', 'Az irányítópult kész.',
           'Az irányítás nálad van.']
    pos = ['Új irány: évkönyv.', 'Új irányt javaslok.', 'Három irányban lépnénk.', 'Ötletek a hétre.',
           'Üzletötlet: tabló.', 'Ez az IRÁNY jó.']
    rn = [run_idea(root, {'chat_id': GROUP, 'text': t})[0] for t in neg]
    rp = [run_idea(root, {'chat_id': GROUP, 'text': t})[0] for t in pos]
    return all(r == 0 for r in rn) and all(r == 2 for r in rp)


@case
def idea_group_gated(root):
    # Patrik csoport TG 4978: the group is gated too, and "irány" triggers like "ötlet".
    rc, _ = run_idea(root, {'chat_id': GROUP, 'text': 'Négy új irány: évkönyv.'})
    rc2, _ = run_idea(root, {'chat_id': GROUP, 'text': 'Új irány.\nÖTLET-KAPU: nem Marabel/könyv, termékpaletta ellenőrizve: 6 termék\nATNEZO: MEHET a1b2c3d4e5\nMAJSZTRO: helyettes-klodel teszt, Májsztró kerete 100 %-on'})
    rc3, _ = run_idea(root, {'chat_id': GROUP, 'text': 'Radar dolgozik.'})
    rc4, _ = run_idea(root, {'chat_id': GROUP, 'text': '📊 ÉLŐ ÁLLAPOT · frissítve 10:31\nÚj üzletág: új irány'})
    return rc == 2 and rc2 == 0 and rc3 == 0 and rc4 == 0


@case
def idea_refused_direction_blocked_despite_line(root):
    # Klodel 38049 (Patrik TG 17453/17460): a valid ÖTLET-KAPU line does not let a refused direction through.
    texts = ('Új ötlet: AI-recepciós szalonoknak.', 'Új irány: telefonos asszisztens kisboltoknak.',
             'Ötlet: társasházi közös képviselet.', 'Ötlet: Recepciós MI fodrászoknak.')
    res = [run_idea(root, {'chat_id': GROUP, 'text': IDEA_LINE + t}) for t in texts]
    return all(rc == 2 and 'elutasított irányt' in err and 'ELVETETT-DE-KERT' in err for rc, err in res)


@case
def idea_refused_direction_names_the_word(root):
    rc, err = run_idea(root, {'chat_id': GROUP, 'text': IDEA_LINE + 'Új ötlet: AI-recepciós szalonoknak.'})
    return rc == 2 and 'recepciós' in err


@case
def idea_refused_direction_asked_allowed(root):
    # Patrik asked for it himself: an ELVETETT-DE-KERT line with his TG message number lets it pass.
    ok = run_idea(root, {'chat_id': GROUP, 'text': IDEA_LINE + 'ELVETETT-DE-KERT: TG 17454\nÚj ötlet: AI-recepciós.'})[0]
    ok2 = run_idea(root, {'chat_id': PRIV, 'text': PRIV_OK + IDEA_LINE + 'Ötlet: recepciós.\nELVETETT-DE-KERT: TG 17454'})[0]
    return ok == 0 and ok2 == 0


@case
def idea_refused_direction_asked_needs_number(root):
    # Without a TG number, or not at a line start, the marker does not count.
    texts = ('ELVETETT-DE-KERT: Patrik kérte\nÚj ötlet: AI-recepciós.',
             'ELVETETT-DE-KERT:\nÚj ötlet: AI-recepciós.',
             'Új ötlet: AI-recepciós. (ELVETETT-DE-KERT: TG 17454)')
    return all(run_idea(root, {'chat_id': GROUP, 'text': IDEA_LINE + t})[0] == 2 for t in texts)


@case
def idea_refused_direction_asked_still_needs_idea_line(root):
    # The ELVETETT-DE-KERT line lifts the refused-direction check only, not the ÖTLET-KAPU line.
    rc, err = run_idea(root, {'chat_id': GROUP, 'text': 'ELVETETT-DE-KERT: TG 17454\nÚj ötlet: AI-recepciós.'})
    return rc == 2 and 'new-direction-start-from-market' in err


@case
def idea_refused_direction_word_start_only(root):
    # Same rule as the lint (Klodel 37971): "megtakarítás" is not "takarítás".
    neg = ('Ötlet: megtakarítás-kalkulátor.', 'Új irány: nyugdíj-előtakarékosság.')
    pos = ('Ötlet: takarítás-közvetítő.', 'Ötlet: takarításközvetítő.')
    rn = [run_idea(root, {'chat_id': GROUP, 'text': IDEA_LINE + t})[0] for t in neg]
    rp = [run_idea(root, {'chat_id': GROUP, 'text': IDEA_LINE + t})[0] for t in pos]
    return all(r == 0 for r in rn) and all(r == 2 for r in rp)


@case
def idea_marabel_in_text_not_refused(root):
    # "marabel" is in the lint list for idea titles, but a chat text may name Marabel (the ÖTLET-KAPU line covers it).
    rc, _ = run_idea(root, {'chat_id': GROUP, 'text': IDEA_LINE + 'Új irány: nem a Marabel, hanem hűtőmágnes-bolt.'})
    return rc == 0


@case
def no_idea_refused_word_unchanged(root):
    # Without "ötlet"/"irány" the gate does not look at the text: a refused word alone blocks nothing.
    rc, _ = run_idea(root, {'chat_id': GROUP, 'text': 'Kész a runbook, a recepciós teszt-fiók törölve.'})
    return rc == 0


@case
def idea_refused_list_missing_fails_closed(root):
    # A copy of the hook without the lint next to it: an idea text stops, a non-idea text still passes.
    import shutil
    here = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(root, 'scripts', 'hooks'))
    os.makedirs(os.path.join(root, 'scripts', 'lib'))
    hook = os.path.join(root, 'scripts', 'hooks', 'product-image-gate.py')
    shutil.copy(HOOK, hook)
    shutil.copy(os.path.join(here, '..', 'lib', 'owner_chat.py'), os.path.join(root, 'scripts', 'lib', 'owner_chat.py'))
    shutil.copy(os.path.join(here, '..', 'lib', 'reply_marks.py'), os.path.join(root, 'scripts', 'lib', 'reply_marks.py'))
    shutil.copy(os.path.join(here, 'ledger_lib.py'), os.path.join(root, 'scripts', 'hooks', 'ledger_lib.py'))
    budget(root, 100)
    env = {'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root, 'MARVEEN_OWNER_PRIVATE_CHAT': PRIV}

    def go(text):
        p = subprocess.run([sys.executable, '-I', hook], input=json.dumps({'tool_input': {'chat_id': GROUP, 'text': text}}),
                           capture_output=True, text=True, env=env, timeout=20)
        return p.returncode, p.stderr
    rc, err = go(IDEA_LINE + 'Új ötlet: hűtőmágnes-bolt.')
    rc2, _ = go('Radar dolgozik.')
    return rc == 2 and 'nem olvasható' in err and rc2 == 0


def gate_copy(root, lint_text):
    """A copy of the hook with the given text as its uzleti-otlet-kapu-lint.py; returns a runner for chat texts."""
    import shutil
    here = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(root, 'scripts', 'hooks'), exist_ok=True)
    os.makedirs(os.path.join(root, 'scripts', 'lib'), exist_ok=True)
    hook = os.path.join(root, 'scripts', 'hooks', 'product-image-gate.py')
    shutil.copy(HOOK, hook)
    shutil.copy(os.path.join(here, '..', 'lib', 'owner_chat.py'), os.path.join(root, 'scripts', 'lib', 'owner_chat.py'))
    shutil.copy(os.path.join(here, '..', 'lib', 'reply_marks.py'), os.path.join(root, 'scripts', 'lib', 'reply_marks.py'))
    shutil.copy(os.path.join(here, 'ledger_lib.py'), os.path.join(root, 'scripts', 'hooks', 'ledger_lib.py'))
    if lint_text is not None:
        with open(os.path.join(root, 'scripts', 'uzleti-otlet-kapu-lint.py'), 'w', encoding='utf-8') as f:
            f.write(lint_text)
    budget(root, 100)
    env = {'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root, 'MARVEEN_OWNER_PRIVATE_CHAT': PRIV}

    def go(text):
        p = subprocess.run([sys.executable, '-I', hook], input=json.dumps({'tool_input': {'chat_id': GROUP, 'text': text}}),
                           capture_output=True, text=True, env=env, timeout=20)
        return p.returncode, p.stderr
    return go


@case
def idea_refused_list_read_as_data(root):
    # Viktor 38060 L1: the lint is parsed, not run. A lint that exits at import, or a short/emptied list, must not
    # switch the check off.
    words = ', '.join(f'"w{i}"' for i in range(12))
    exiting = f'import sys\nsys.exit(0)\nELUTASITOTT = [{words}, "recepciós"]\n'
    rc1, _ = gate_copy(os.path.join(root, 'a'), exiting)(IDEA_LINE + 'Új ötlet: AI-recepciós.')
    rc2, err2 = gate_copy(os.path.join(root, 'b'), 'ELUTASITOTT = []\n')(IDEA_LINE + 'Új ötlet: kalkulátor.')
    rc3, err3 = gate_copy(os.path.join(root, 'c'), 'ELUTASITOTT = ["recepciós"]\n')(IDEA_LINE + 'Új ötlet: kalkulátor.')
    rc4, _ = gate_copy(os.path.join(root, 'd'), f'ELUTASITOTT = [{words}]\n')(IDEA_LINE + 'Új ötlet: kalkulátor.')
    pyc = any(n.startswith('uzleti') and n.endswith('.pyc') for _, _, fs in os.walk(root) for n in fs)
    return (rc1 == 2 and rc2 == 2 and 'nem olvasható' in err2 and rc3 == 2 and 'nem olvasható' in err3 and rc4 == 0
            and not pyc)


@case
def idea_refused_direction_inside_marker_line_blocked(root):
    # Viktor 38060 L2: only the gate's own phrases are cut out; a refused direction inside a marker line still stops.
    texts = ('ÖTLET-KAPU: nem Marabel/könyv, termékpaletta ellenőrizve, recepciós\nÚj ötlet.',
             'PRIVÁT-OK: telefonos asszisztens ügy, Patrik kérdezte\n' + IDEA_LINE + 'Új ötlet.')
    # raw: a marker line in the text is itself refused now (JELÖLŐ-KAPU, Klodel 40845), so it can never carry the idea.
    hits = [run_idea(root, {'chat_id': GROUP, 'text': t}, raw=True)[0] for t in texts]
    ok, _ = run_idea(root, {'chat_id': GROUP, 'text': IDEA_LINE + 'Új ötlet: hűtőmágnes-bolt.'})
    # A negation in the marker line is the declaration the gate asks for (TG 17460: "nem AI-tanácsadás"): it passes.
    # In the body a negation gets no pass.
    neg_line, _ = run_idea(root, {'chat_id': GROUP, 'text': 'ÖTLET-KAPU: nem Marabel/könyv, nem AI-tanácsadás, nem telefonos '
                                                       'asszisztens, termékpaletta ellenőrizve\nATNEZO: MEHET a1b2c3d4e5\nMAJSZTRO: helyettes-klodel teszt, Májsztró kerete 100 %-on\nÚj ötlet: kalkulátor.'})
    neg_body, _ = run_idea(root, {'chat_id': GROUP, 'text': IDEA_LINE + 'Új ötlet: nem recepciós, hanem kalkulátor.'})
    return all(r == 2 for r in hits) and ok == 0 and neg_line == 0 and neg_body == 2


BALAZS = '8366648365'


def tg_state(root, senders=(), evidence=()):
    """Synthetic plugin logs under the throw-away project dir: inbound-senders.jsonl (who) and inbound-evidence.jsonl."""
    d = os.path.join(root, '.claude', 'channels', 'telegram')
    os.makedirs(d, exist_ok=True)
    for name, rows in (('inbound-senders.jsonl', senders), ('inbound-evidence.jsonl', evidence)):
        with open(os.path.join(d, name), 'w', encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps(r) + '\n')


def balazs_asked(root, mid='901', text='Mi a helyzet a Creatorz-zal?', user=BALAZS, chat=GROUP):
    tg_state(root, senders=[{'chat_id': chat, 'message_id': mid, 'user_id': user, 'at': 1}],
             evidence=[{'chat_id': chat, 'message_id': mid, 'text': text, 'at': 1}])


@case
def creatorz_blocked_without_balazs_question(root):
    # Klodel 38073 (Patrik csoport TG 5419): the Creatorz topic is not brought up again; every spelling counts.
    texts = ('A Creatorz-féle megoldás jó volna.', 'CREATORZ', 'creatorz.hu', 'Creat\u200borz megint.')
    res = [run(root, {'chat_id': GROUP, 'text': t}) for t in texts]
    priv = run(root, {'chat_id': PRIV, 'text': PRIV_OK + 'A Creatorz-ról.'})
    return all(rc == 2 and 'CREATORZ-KAPU' in err for rc, err in res) and priv[0] == 2


@case
def creatorz_reply_to_balazs_naming_it_allowed(root):
    balazs_asked(root)
    rc, _ = run(root, {'chat_id': GROUP, 'text': 'A Creatorz-ról: nem visszük tovább.', 'reply_to': '901'})
    rc_int, _ = run(root, {'chat_id': GROUP, 'text': 'A Creatorz-ról: nem.', 'reply_to': 901})
    return rc == 0 and rc_int == 0


@case
def creatorz_reply_not_enough(root):
    # Balázs's message without the word, someone else's message with it, another chat, no record: still blocked.
    balazs_asked(root, text='Mi a helyzet a kampánnyal?')
    a = run(root, {'chat_id': GROUP, 'text': 'A Creatorz-ról.', 'reply_to': '901'})[0]
    balazs_asked(root, user='5040302010')
    b = run(root, {'chat_id': GROUP, 'text': 'A Creatorz-ról.', 'reply_to': '901'})[0]
    balazs_asked(root, chat='-1000000000099')
    c = run(root, {'chat_id': GROUP, 'text': 'A Creatorz-ról.', 'reply_to': '901'})[0]
    balazs_asked(root)
    d = run(root, {'chat_id': GROUP, 'text': 'A Creatorz-ról.', 'reply_to': '902'})[0]
    return a == b == c == d == 2


@case
def creatorz_no_sender_log_fails_closed(root):
    # The "who" plugin patch not live yet: the evidence alone does not prove Balázs wrote it.
    tg_state(root, evidence=[{'chat_id': GROUP, 'message_id': '901', 'text': 'Creatorz?', 'at': 1}])
    rc, _ = run(root, {'chat_id': GROUP, 'text': 'A Creatorz-ról.', 'reply_to': '901'})
    return rc == 2


@case
def creatorz_corrupt_log_still_blocks(root):
    # Viktor 38110 L1: a non-object line ([1], a string) in either log must not crash the gate into letting it pass.
    d = os.path.join(root, '.claude', 'channels', 'telegram')
    os.makedirs(d, exist_ok=True)
    for name in ('inbound-senders.jsonl', 'inbound-evidence.jsonl'):
        with open(os.path.join(d, name), 'w', encoding='utf-8') as f:
            f.write('[1]\n"x"\n')
    rc, err = run(root, {'chat_id': GROUP, 'text': 'A Creatorz-ról.', 'reply_to': '901'})
    balazs_asked(root)
    with open(os.path.join(d, 'inbound-senders.jsonl'), 'a', encoding='utf-8') as f:
        f.write('[1]\n')
    ok, _ = run(root, {'chat_id': GROUP, 'text': 'A Creatorz-ról.', 'reply_to': '901'})
    return rc == 2 and 'CREATORZ-KAPU' in err and ok == 0


@case
def creatorz_absent_unchanged(root):
    rc, _ = run(root, {'chat_id': GROUP, 'text': 'A kreatív anyag kész, a creator-oldal is.'})
    return rc == 0


@case
def no_idea_private_unchanged(root):
    rc, _ = run(root, {'chat_id': PRIV, 'text': PRIV_OK + 'Kész a riport.'})
    return rc == 0


# ELTUNT (Klodel 39281, Patrik TG 17953, 2026-11-12): a website before/after pair says what disappeared. The fixture is
# the shape of the real 11-12 sheets (alk*-mobil-hero-par.jpg.ok). Synthetic ledger: inbound 17953, outbound 17946.
def web_pair(root, eltunt=None, name='hero-par.png', konyv=None, ledger=True, a5='n/a weboldal-képernyőkép'):
    import sqlite3
    kapu = os.path.join(root, 'store', 'kep-kapu')
    os.makedirs(kapu, exist_ok=True)
    img = os.path.join(root, name)
    open(img, 'wb').write(b'\x89PNG')
    if ledger and not os.path.exists(os.path.join(root, 'store', 'claudeclaw.db')):
        con = sqlite3.connect(os.path.join(root, 'store', 'claudeclaw.db'))
        con.execute('CREATE TABLE conversation_log (id INTEGER PRIMARY KEY, agent_id TEXT, chat_id TEXT, direction TEXT, '
                    'message_id TEXT, text TEXT, ts TEXT, created_at INTEGER, source TEXT)')
        con.execute("INSERT INTO conversation_log (agent_id, chat_id, direction, message_id, created_at, source) "
                    "VALUES ('klodel', ?, 'in', '17953', 1, 'plugin:telegram:telegram')", (GROUP,))
        con.execute("INSERT INTO conversation_log (agent_id, chat_id, direction, message_id, created_at, source) "
                    "VALUES ('klodel', ?, 'out', '17946', 1, 'plugin:telegram:telegram')", (GROUP,))
        con.commit()
        con.close()
    lines = [f'KONYV: {konyv or "a meglévő termékképek, a PR csak oldalszerkezetet módosít; weboldal előtte-utána pár"}',
             f'A5: {a5}', 'PAPIR: n/a weboldal-képernyőkép', 'SAJAT: ok saját oldalunk, dev szerver',
             'KERES: teszt kérés, egyezik', 'NAGYITVA: Read-del megnézve, nincs törés',
             'MAJSZTRO: nem-marketing weboldal-változás jóváhagyásra']
    if eltunt is not None:
        lines.append(f'ELTUNT: {eltunt}')
    open(os.path.join(kapu, name + '.ok'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    return run(root, {'chat_id': GROUP, 'text': 'x', 'files': [img]})


@case
def web_pair_without_eltunt_blocked(root):
    rc, err = web_pair(root)
    return rc == 2 and 'ELTUNT' in err and '17953' in err


@case
def web_pair_eltunt_nincs_allowed(root):
    return web_pair(root, 'nincs')[0] == 0 and web_pair(root, 'Nincs.')[0] == 0


@case
def web_pair_nincs_with_text_blocked(root):
    # the 11-12 case written as a "nincs" with an excuse after it is not "nothing is gone"
    rc, err = web_pair(root, 'nincs, csak a 8 színkör ment ki a heróból')
    return rc == 2 and 'PATRIK-KERTE' in err


@case
def web_pair_removal_without_kerte_blocked(root):
    rc, err = web_pair(root, 'a hero 8 színköre')
    return rc == 2 and 'PATRIK-KERTE' in err


@case
def web_pair_removal_with_kerte_allowed(root):
    return web_pair(root, 'a hero 8 színköre PATRIK-KERTE TG 17953')[0] == 0


@case
def web_pair_kerte_outbound_or_unknown_tg_blocked(root):
    # 17946 is our own outbound message (the "change" sent to Patrik), 99999 does not exist
    rc1, err1 = web_pair(root, 'a hero 8 színköre PATRIK-KERTE TG 17946')
    rc2, _ = web_pair(root, 'a hero 8 színköre PATRIK-KERTE TG 99999', name='masik-par.png')
    return rc1 == 2 and '17946' in err1 and rc2 == 2


@case
def web_pair_kerte_without_ledger_blocked(root):
    rc, err = web_pair(root, 'a hero 8 színköre PATRIK-KERTE TG 17953', ledger=False)
    return rc == 2 and 'ELTUNT' in err


@case
def web_pair_detected_by_file_name(root):
    # KONYV/A5 say "weboldal" but not "előtte-utána"; the file name carries "-par"
    rc, _ = web_pair(root, konyv='n/a weboldal-képernyőkép', name='alk1-mobil-hero-par.jpg')
    return rc == 2


@case
def elotte_utana_file_name_alone_is_a_pair(root):
    # Viktor 39289 MEDIUM: 5 live elotte-*/utana-* sheets say "KONYV: nincs / A5: nincs-konyv", no "weboldal"
    rc1, err = web_pair(root, konyv='nincs', a5='nincs-konyv', name='elotte-x-mobil.png')
    rc2, _ = web_pair(root, konyv='nincs', a5='nincs-konyv', name='utana-80-koszonto-mobil-1.jpg')
    rc3, _ = web_pair(root, 'nincs', konyv='nincs', a5='nincs-konyv', name='after-hero.png')
    return rc1 == 2 and 'ELTUNT' in err and rc2 == 2 and rc3 == 0


@case
def par_file_word_without_weboldal_unchanged(root):
    # "pár" is a common Hungarian word: a par/pair file word counts only with "weboldal" in KONYV/A5
    rc, _ = web_pair(root, konyv='nincs', a5='nincs-konyv', name='jelenet-par.png')
    return rc == 0


@case
def nincs_named_as_removed_blocked(root):
    # Viktor 39289 INFO 3: "nincs PATRIK-KERTE TG <n>" names nothing that is gone
    rc, err = web_pair(root, 'nincs PATRIK-KERTE TG 17953')
    return rc == 2 and 'PATRIK-KERTE' in err


@case
def web_pair_text_pair_word(root):
    # Viktor 39289 INFO 1: "pair" in KONYV/A5 counts like "pár"
    rc, _ = web_pair(root, konyv='weboldal screenshot pair', name='hero.png')
    return rc == 2


@case
def web_single_screenshot_unchanged(root):
    # a single website screenshot (no pair word in KONYV/A5 or the name) needs no ELTUNT line; "parnak" is not "par"
    rc, _ = web_pair(root, konyv='n/a weboldal-képernyőkép', name='ajandek-parnak-mobil.png')
    return rc == 0


@case
def book_image_needs_no_eltunt(root):
    img = book_fixture(root, 'van fotós borító')
    rc, _ = run(root, {'chat_id': GROUP, 'text': 'x', 'files': [img]})
    return rc == 0

# Klodel 39520 (Patrik TG 18075 "ez hülyeség"): an ÖTLET-KAPU text needs the blind reviewer's ATNEZO line.
TG18074 = ('Megvan az első. Szigma és Mágnes egymástól függetlenül ugyanoda jutott:\n\n'
           'Sorbanállás-mérő. A postán, orvosnál, kormányablakban vagy a bolti pénztárnál két gomb van: „itt vagyok, '
           'sorban állok” és „sorra kerültem”. Az app ebből kiszámolja, hol mennyit kell várni napszak szerint, a '
           'várakozásért pedig jelvény jár (pl. „Türelem Nagymestere”).\n'
           '• Mindenkit érint: sorban állni mindenki szokott, 16 évestől 70 évesig, városban és falun is. Csak az marad '
           'ki, akinek nincs okostelefonja, ahogy a Budicheckből is.\n'
           '• Vicces mondat (Mágnesé): „Mindig a másik sor halad gyorsabban. Most végre számokkal.” Szigmáé: „47 perc a '
           'postán, előttem 6 ember és 1 ablak: ez már nem sor, hanem életforma.”\n'
           '• Itthon: a Google Térkép becsül forgalmasságot, a Kormányablak-app pedig várakozási időt. A Telex szerint az '
           'utóbbi hónapokig hibásan mutatta. Olyat, ahol az emberek maguk jelzik a sort, viccesen, jelvényekkel, nem '
           'találtunk.\n'
           '• Gyenge pont: indulásnál üres, amíg kevesen jelzik a sort. A pénz még csak tipp: a hivatalok és a boltok '
           'fizethetnek a valós várakozási adatokért.\n\n'
           'Radar ötletei még jönnek, és a független átnéző 15:00-ra rangsorol.\n\n'
           'ÖTLET-KAPU: nem Marabel/könyv, termékpaletta ellenőrizve (Meséld el!, Első éved, Receptkönyv, Köszönjük, '
           'Marabello, Chats)\n'
           'PRIVÁT-OK: Patrik privát kérése (TG 18069), új üzletág')


@case
def idea_tg18074_without_reviewer_blocked(root):
    # The exact text of TG 18074: a valid ÖTLET-KAPU line, no ATNEZO line -> blocked, and the message says why.
    rc, err = run_idea(root, {'chat_id': PRIV, 'text': TG18074})
    rc2, _ = run_idea(root, {'chat_id': GROUP, 'text': TG18074})
    return rc == 2 and rc2 == 2 and 'ATNEZO: MEHET' in err and '18075' in err


@case
def idea_tg18074_with_reviewer_id_allowed(root):
    return run_idea(root, {'chat_id': PRIV, 'text': TG18074 + MJ + '\nATNEZO: MEHET agent-task-7f3a9c'})[0] == 0


@case
def idea_reviewer_file_must_say_mehet(root):
    os.makedirs(os.path.join(root, 'shared', 'k-f'), exist_ok=True)
    with open(os.path.join(root, 'shared', 'k-f', 'atnezo-ok.md'), 'w', encoding='utf-8') as f:
        f.write('Vak átnéző ítélete: MEHET (1. ötlet)\n')
    with open(os.path.join(root, 'shared', 'k-f', 'atnezo-javitando.md'), 'w', encoding='utf-8') as f:
        f.write('Vak átnéző ítélete: JAVÍTANDÓ, nem megy\n')
    ok = run_idea(root, {'chat_id': GROUP, 'text': TG18074 + MJ + '\nATNEZO: MEHET shared/k-f/atnezo-ok.md'})[0]
    bad = run_idea(root, {'chat_id': GROUP, 'text': TG18074 + MJ + '\nATNEZO: MEHET shared/k-f/atnezo-javitando.md'})[0]
    missing = run_idea(root, {'chat_id': GROUP, 'text': TG18074 + MJ + '\nATNEZO: MEHET shared/k-f/nincs-ilyen.md'})[0]
    outside = run_idea(root, {'chat_id': GROUP, 'text': TG18074 + MJ + '\nATNEZO: MEHET /etc/hosts'})[0]
    return ok == 0 and bad == 2 and missing == 2 and outside == 2


@case
def idea_reviewer_line_forms(root):
    texts_bad = [TG18074 + MJ + '\nATNEZO: MEHET', TG18074 + MJ + '\nATNEZO: MEHET abc', TG18074 + MJ + '\nATNEZO: JAVÍTANDÓ x1y2z3w4',
                 TG18074 + MJ + '\nATNEZO: nincs-otlet ok', TG18074 + MJ + '\nMegjegyzés: ATNEZO: MEHET a1b2c3d4e5']
    texts_ok = ['Állapot: Radar ötletei még jönnek.\n' + IDEA_LINE.split('\n')[0] + MJ + '\nATNEZO: nincs-otlet csak állapot, új ötlet nincs benne',
                TG18074 + MJ + '\nATNÉZŐ: MEHET a1b2c3d4e5']
    return (all(run_idea(root, {'chat_id': GROUP, 'text': t})[0] == 2 for t in texts_bad)
            and all(run_idea(root, {'chat_id': GROUP, 'text': t})[0] == 0 for t in texts_ok))


# Klodel 39550 (Patrik TG 18106 "nálunk is van chatgpt agent mégis állandóan a ti hülyeségeketek jön csak"): the K+F
# lead is Majsztro; an ÖTLET-KAPU text needs "MAJSZTRO: MEHET <msg_id>" or, at a 100 % budget, "helyettes-klodel".
# TG 18099 is the literal text Klodel sent around him (ledger, conversation_log, read-only).
TG18099 = ('Ha a következő ötletkört a Gemini 4 Argon is megcsinálná: nálunk nincs bekötve, Kernel beköti, a használata '
           'API-díjas. Kéred?\n\nPRIVÁT-OK: Patrik privát kérdése (TG 18092), új üzletág\nÖTLET-KAPU: nem Marabel/könyv, '
           'termékpaletta ellenőrizve (Meséld el!, Első éved, Receptkönyv, Köszönjük, Marabello, Chats)')


@case
def idea_without_majsztro_blocked(root):
    # A valid ATNEZO line is not enough: without a MAJSZTRO line the text stops, and the message says why.
    rc, err = run(root, {'chat_id': PRIV, 'text': TG18074 + '\nATNEZO: MEHET agent-task-7f3a9c'})
    rc2, err2 = run(root, {'chat_id': PRIV, 'text': TG18099 + '\nATNEZO: nincs-otlet csak kérdés, új ötlet nincs benne'})
    budget(root, 100)  # a full budget does not make the line optional
    rc3, _ = run(root, {'chat_id': GROUP, 'text': TG18074 + '\nATNEZO: MEHET agent-task-7f3a9c'})
    return (rc == 2 and '18106' in err and 'MAJSZTRO: MEHET' in err and rc2 == 2 and '18106' in err2 and rc3 == 2)


@case
def idea_majsztro_substitute_only_at_full_budget(root):
    text = TG18074 + '\nATNEZO: MEHET agent-task-7f3a9c' + MJ
    none = run(root, {'chat_id': GROUP, 'text': text})
    budget(root, 99)
    part = run(root, {'chat_id': GROUP, 'text': text})
    budget(root, 100)
    full = run(root, {'chat_id': GROUP, 'text': text})[0]
    # the 5-hour window at 100 % before its reset counts too (CLAUDE.md MÁJSZTRÓ HELYETTES)
    json.dump({'usage': {'rateLimits': [{'kind': 'five_hour', 'percentUsed': 100, 'resetsAt': '2099-01-01T00:00:00Z'},
                                        {'kind': 'seven_day', 'percentUsed': 40}]}},
              open(os.path.join(root, 'store', 'mod-state', 'majsztro.json'), 'w'))
    five = run(root, {'chat_id': GROUP, 'text': text})[0]
    return (none[0] == 2 and 'helyettes-klodel' in none[1] and part[0] == 2 and 'helyettes-klodel' in part[1]
            and full == 0 and five == 0)


@case
def idea_majsztro_line_forms(root):
    # The image-gate forms do not count for an idea, the line must start the row, the substitute needs a reason.
    budget(root, 100)
    base = TG18074 + '\nATNEZO: MEHET agent-task-7f3a9c\n'
    bad = ['MAJSZTRO: nem-marketing ez csak egy ötlet', 'MAJSZTRO: kivetel-1881 12345', 'MAJSZTRO: helyettes-klodel',
           'Megjegyzés: MAJSZTRO: helyettes-klodel Májsztró kerete elfogyott', 'MAJSZTRO: MEHET', 'MAJSZTRO: OK 12345']
    ok = ['MAJSZTRÓ: helyettes-klodel Májsztró kerete elfogyott', 'majsztro: helyettes-klodel Májsztró kerete elfogyott']
    return (all(run(root, {'chat_id': GROUP, 'text': base + b})[0] == 2 for b in bad)
            and all(run(root, {'chat_id': GROUP, 'text': base + o})[0] == 0 for o in ok))


def idea_majsztro_queue(root, row):
    """idea_check in-process with the queue read stubbed: row is what GET /api/messages/<id> returns (or an exception)."""
    mod = gate_module()
    mod.ROOT = root
    os.makedirs(os.path.join(root, 'store'), exist_ok=True)
    open(os.path.join(root, 'store', '.dashboard-token'), 'w').write('synthetic')
    seen = []

    def fake(req, timeout=5):
        seen.append(req.full_url)
        if isinstance(row, Exception):
            raise row
        return FakeResponse(row)
    mod.urllib.request.urlopen = fake
    return mod.idea_check(TG18074 + '\nATNEZO: MEHET agent-task-7f3a9c\nMAJSZTRO: MEHET 39999'), seen


@case
def idea_majsztro_mehet_from_queue(root):
    ok, seen = idea_majsztro_queue(root, {'from_agent': 'majsztro', 'content': 'Az 1. ötlet: MEHET.'})
    other, _ = idea_majsztro_queue(root, {'from_agent': 'klodel', 'content': 'MEHET'})
    fix, _ = idea_majsztro_queue(root, {'from_agent': 'majsztro', 'content': 'MEHET helyett JAVÍTANDÓ'})
    down, _ = idea_majsztro_queue(root, OSError('queue down'))
    return (ok is None and seen == ['http://localhost:3420/api/messages/39999'] and other and '18106' in other
            and fix and down and 'nem olvasható' in down)


# Klodel 39617 (Balázs TG 5579 "megkérdeztem mi a magyar piac"): an "itthon nincs" claim in a reply needs
# "ITTHON-MERT: <file>"; TG 5550 is the literal text that went out without Meska and Pepita (ledger, read-only).
TG5550 = ('A „1000 helyről venni” kint igaz, itthon nem: Radar a mért magyar boltokban személyre szabott domborzati '
          'térképet nem talált. Amit kint árulnak, ott a vevő maga jelöli be a helyeket, vagy kész mintát választ.\n\n'
          'Három dolog, amit szerintem csak mi tudunk beletenni (ez javaslat, még nem mért):\n'
          '1. A vevő semmit nem jelöl kézzel. Feltölti a telefonja fotóit vagy a Google helyelőzményeit, és mi '
          'kirajzoljuk belőle az összes utat, évszámmal és útvonallal.\n'
          '2. Minden helyhez tartozik egy kis felirat vagy QR-kód, ami az ottani fotókhoz és történethez visz. Ettől lesz '
          'az övé, és nem egy térkép a sok közül.\n'
          '3. Előnézet a saját falán: lefotózza a szobát, és megmutatjuk benne a kész darabot, a színeket a lakáshoz '
          'igazítva.\nAz 1. pont személyes helyadat, ezért Lexnek és Viktornak előbb meg kell néznie.\n\n'
          'Radar most azt méri, mit árulnak kint utazós falitérképből (kaparós, tűzős, világítós), mennyiért, és mi '
          'hiányzik mindegyikből. A különlegességet ezzel ellenőrizzük, nem fejből.\n\n'
          'ÖTLET-KAPU: nem Marabel/könyv, termékpaletta ellenőrizve (Meséld el!, Első éved, Receptkönyv, Köszönjük, '
          'Marabello, Chats)\nFORRÁS: shared/k-f/ai-tervezes-termek-1112.md (Radar, ma) ')
TG5550_BODY = TG5550.split('\n\nÖTLET-KAPU')[0]  # without the idea line, so only this gate speaks in a subprocess run
ITTHON_OK = ('## 1. Személyre szabott domborzati térkép\n'
             '- ITTHON: nincs magyar bolt, ami árulja (mérve, saját GET):\n'
             '  - Meska: 0 találat („domborzati térkép”)\n'
             '  - Pepita: 0 találat\n'
             '  - eMAG: NINCS ADAT, 410 botvédelem, a site-próba pótolja\n'
             '  - site-szűrt keresés: emag.hu 0; alza.hu 0; notino.hu „nincs találat”; douglas.hu 0.\n')


def itthon_file(root, body, name='itthon.md'):
    d = os.path.join(root, 'shared', 'k-f')
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), 'w', encoding='utf-8') as f:
        f.write(body)
    return f'shared/k-f/{name}'


@case
def itthon_tg5550_blocked(root):
    # In-process: the literal TG 5550 is an absence claim without ITTHON-MERT (independent of the idea gates).
    mod = gate_module()
    mod.ROOT = root
    why = mod.itthon_mert_check(TG5550)
    rc, err = run(root, {'chat_id': GROUP, 'text': TG5550_BODY})
    return bool(why) and '5579' in why and rc == 2 and 'ITTHON-KAPU' in err and 'Meska' in err


@case
def itthon_measured_file_allowed(root):
    rel = itthon_file(root, ITTHON_OK)
    rc, err = run(root, {'chat_id': GROUP, 'text': TG5550_BODY + '\nITTHON-MERT: ' + rel})
    return rc == 0 and not err.strip()


@case
def itthon_file_must_name_meska_pepita_emag(root):
    res = []
    for body in (ITTHON_OK.replace('  - Meska: 0 találat („domborzati térkép”)\n', ''),            # no Meska
                 ITTHON_OK.replace('  - Pepita: 0 találat\n', ''),                                  # no Pepita
                 ITTHON_OK.replace('  - eMAG: NINCS ADAT, 410 botvédelem, a site-próba pótolja\n', ''),  # eMAG only in site line
                 ITTHON_OK.replace('Meska: 0 találat („domborzati térkép”)', 'Meska: 410'),          # not measured
                 ITTHON_OK.replace('NINCS ADAT, 410 botvédelem, a site-próba pótolja', 'NINCS ADAT')):  # no reason
        rel = itthon_file(root, body)
        res.append(run(root, {'chat_id': GROUP, 'text': TG5550_BODY + '\nITTHON-MERT: ' + rel}))
    names = ['meska', 'pepita', 'emag', 'meska', 'emag']
    return all(rc == 2 and n in err for (rc, err), n in zip(res, names))


@case
def itthon_file_must_pass_the_lint(root):
    # No "mért" word, and only one shop with a result (eMAG is NINCS ADAT): the shared lint's ITTHON rule fails it.
    bad = ITTHON_OK.replace('(mérve, saját GET)', '(saját GET)')
    rc, err = run(root, {'chat_id': GROUP, 'text': TG5550_BODY + '\nITTHON-MERT: ' + itthon_file(root, bad)})
    nosec = ITTHON_OK.replace('## 1. ', '# ')  # no "## N." section: the lint gives no verdict
    rc2, err2 = run(root, {'chat_id': GROUP, 'text': TG5550_BODY + '\nITTHON-MERT: ' + itthon_file(root, nosec, 'b.md')})
    return rc == 2 and 'lint:' in err and rc2 == 2 and 'ítéletet' in err2


@case
def itthon_mert_line_forms(root):
    rel = itthon_file(root, ITTHON_OK)
    texts = [TG5550_BODY + '\nITTHON-MERT: shared/k-f/nincs-ilyen.md', TG5550_BODY + '\nITTHON-MERT: /etc/hosts',
             TG5550_BODY + '\nForrás, ITTHON-MERT: ' + rel, TG5550_BODY + '\nITTHON-MERT:',
             TG5550_BODY + '\nITTHON-MERT: ' + itthon_file(root, '## 1. X\n- Leírás: nincs ITTHON mező\n', 'c.md')]
    return all(run(root, {'chat_id': GROUP, 'text': t})[0] == 2 for t in texts)


@case
def itthon_claims_from_the_ledger_detected(root):
    # Real sentences (Klodel's sent texts, 2026-11-12) are claims; data-gap sentences are not.
    mod = gate_module()
    mod.ROOT = root
    claims = ['Itthon egyiknek sem találtunk megfelelőjét az app-boltokban.', 'Magyar boltban nem találtunk ilyet.',
              'Kint 41 ezer felhasználó, itthon nincs ilyen app.', 'Itthon senki nem csinálja.',
              'Itthon személyre szabott változatot nem találtunk.', 'Nincs magyar megfelelője.']
    plain = ['Magyar bevételi adat (RPM) nincs.', 'A magyar mérés pedig nincs meg.', 'Itthon is kapható a Meskán.',
             'Hogy itthon kellene-e, azt nem tudjuk.', 'Kész a riport.']
    return (all(mod.itthon_mert_check(t) for t in claims) and not any(mod.itthon_mert_check(t) for t in plain))


# Card 9df14a4c (Klodel 40009, Patrik csoport TG 5704: "most meg ide reagálsz arra az üzenetemre amit a másik
# chatbe irtam"): where the owner wrote last decides. A throw-away conversation_log ledger, synthetic ids.
def ledger(root, *chats, agent='main', age_s=0, texts=None):
    import sqlite3
    import time
    db = os.path.join(root, 'ledger.db')
    con = sqlite3.connect(db)
    con.execute('CREATE TABLE conversation_log (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT, '
                'chat_id TEXT, direction TEXT, text TEXT, created_at INTEGER)')
    for i, chat in enumerate(chats):
        con.execute("INSERT INTO conversation_log (agent_id, chat_id, direction, text, created_at) "
                    "VALUES (?, ?, 'in', ?, ?)", (agent, chat, (texts or {}).get(i, 'x'), int(time.time()) - age_s))
    con.commit()
    con.close()
    return db


def run_ledger(root, db, tool_input, agent='main', tool='mcp__plugin_telegram_telegram__reply', raw=False, group_env=GROUP):
    env = {'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root, 'MARVEEN_OWNER_PRIVATE_CHAT': PRIV,
           'MARVEEN_OWNER_GROUP_CHAT': group_env, 'LEDGER_DB_PATH': db, 'MAIN_AGENT_ID': 'main',
           'MARVEEN_AGENT_ID': agent, 'REPLY_MARKS_PATH': os.path.join(root, 'store', 'reply-marks.jsonl')}
    ti = tool_input if raw else as_marks(root, tool_input, agent)
    p = subprocess.run([sys.executable, '-I', HOOK], input=json.dumps({'tool_name': tool, 'tool_input': ti}),
                       capture_output=True, text=True, env=env, timeout=20)
    return p.returncode, p.stderr


@case
def latest_private_private_reply_without_marker_allowed(root):
    db = ledger(root, GROUP, PRIV)
    rc, err = run_ledger(root, db, {'chat_id': PRIV, 'text': 'Rendben, megnézem.'})
    return rc == 0 and 'Traceback' not in err


@case
def latest_private_group_reply_blocked(root):
    db = ledger(root, GROUP, PRIV)
    rc, err = run_ledger(root, db, {'chat_id': GROUP, 'text': 'Rendben, megnézem.'})
    return rc == 2 and 'PRIVÁT-VÁLASZ-KAPU' in err


@case
def NEG_latest_private_group_reply_noncanonical_group_config_blocked(root):
    # Viktor 40902 INFO b: a non-canonical group id in the config ("-0..." / "+...") is the same chat.
    out = []
    for cfg in ('-0' + GROUP[1:], ' ' + GROUP + ' '):
        sub = tempfile.mkdtemp(dir=root)
        db = ledger(sub, GROUP, PRIV)
        rc, err = run_ledger(sub, db, {'chat_id': GROUP, 'text': 'Rendben, megnézem.'}, group_env=cfg)
        out.append(rc == 2 and 'PRIVÁT-VÁLASZ-KAPU' in err)
    return all(out)


# Patrik privát TG 18521 (Klodel 40951): "Ok mehet ki a masik chatben posztot irj es ott megtargyaljuk". When his
# latest private message itself sends the work to the group, the group reply passes PRIVÁT-VÁLASZ-KAPU.
@case
def latest_private_owner_asked_group_reply_allowed(root):
    out = []
    for text in ('Ok mehet ki a masik chatben posztot irj es ott megtargyaljuk', 'A MÁSIK CHATBEN írd meg',
                 'írd a csoportba, ott beszéljük meg'):
        sub = tempfile.mkdtemp(dir=root)
        os.makedirs(os.path.join(sub, 'store'), exist_ok=True)
        db = ledger(sub, GROUP, PRIV, texts={1: text})
        rc, err = run_ledger(sub, db, {'chat_id': GROUP, 'text': 'Itt a poszt-terv, beszéljük meg.'})
        out.append(rc == 0 and 'PRIVÁT-VÁLASZ-KAPU' not in err and 'Traceback' not in err)
    return all(out)


@case
def NEG_owner_asked_group_once_per_message(root):
    # Viktor 40974 LOW (a): one private request = one group reply; the second needs a new request.
    os.makedirs(os.path.join(root, 'store'), exist_ok=True)
    db = ledger(root, GROUP, PRIV, texts={1: 'Ok mehet ki a masik chatben posztot irj es ott megtargyaljuk'})
    rc1, _ = run_ledger(root, db, {'chat_id': GROUP, 'text': 'Itt a poszt-terv.'})
    rc2, err2 = run_ledger(root, db, {'chat_id': GROUP, 'text': 'Még egy csoport-üzenet.'})
    return rc1 == 0 and rc2 == 2 and 'PRIVÁT-VÁLASZ-KAPU' in err2


@case
def NEG_owner_mentions_group_without_asking_blocked(root):
    # Viktor 40974 LOW (measured): a negation, a question or a mere mention of the group is not a request.
    out = []
    for text in ('Ne írj a csoportba, itt beszéljük meg', 'nem a másik chatbe, ide válaszolj', 'mi van a csoportban?',
                 'a csoportban küldött kép rossz', 'csoportos számla kell'):
        sub = tempfile.mkdtemp(dir=root)
        os.makedirs(os.path.join(sub, 'store'), exist_ok=True)
        db = ledger(sub, GROUP, PRIV, texts={1: text})
        rc, err = run_ledger(sub, db, {'chat_id': GROUP, 'text': 'Itt a poszt-terv.'})
        out.append(rc == 2 and 'PRIVÁT-VÁLASZ-KAPU' in err)
    return all(out)


@case
def NEG_latest_private_plain_message_group_reply_still_blocked(root):
    # A plain private message, an older private "másik chat" followed by a plain one, and a "másik chat" said in
    # the GROUP (not the latest private) do not open the group reply.
    out = []
    for chats, texts in (((GROUP, PRIV), {1: 'Rendben, köszönöm.'}),
                         ((GROUP, PRIV, PRIV), {1: 'írj a másik chatben', 2: 'Inkább itt maradjunk.'}),
                         ((PRIV, GROUP, PRIV), {1: 'a másik chatben', 2: 'ok'})):
        sub = tempfile.mkdtemp(dir=root)
        db = ledger(sub, *chats, texts=texts)
        rc, err = run_ledger(sub, db, {'chat_id': GROUP, 'text': 'Itt a poszt-terv.'})
        out.append(rc == 2 and 'PRIVÁT-VÁLASZ-KAPU' in err)
    return all(out)


@case
def latest_group_private_reply_without_marker_blocked(root):
    db = ledger(root, PRIV, GROUP)
    rc, err = run_ledger(root, db, {'chat_id': PRIV, 'text': 'Rendben, megnézem.'})
    return rc == 2 and 'PRIVÁT-KAPU' in err and 'PRIVÁT-VÁLASZ-KAPU' not in err


@case
def latest_group_group_reply_allowed(root):
    db = ledger(root, PRIV, GROUP)
    rc, err = run_ledger(root, db, {'chat_id': GROUP, 'text': 'Rendben, megnézem.'})
    return rc == 0 and 'Traceback' not in err


@case
def other_agent_latest_private_keeps_marker_rule(root):
    # dave's own rows say "latest private": the main-agent-only rule must still not release his reply
    db = ledger(root, GROUP, PRIV, agent='dave')
    rc, err = run_ledger(root, db, {'chat_id': PRIV, 'text': 'Rendben.'}, agent='dave')
    return rc == 2 and 'PRIVÁT-KAPU' in err


@case
def NEG_edit_message_to_group_is_not_redirected_when_latest_is_private(root):
    # Viktor 40081 L1: the live status message in the group is edited in place; it must not stop updating.
    db = ledger(root, GROUP, PRIV)
    rc, err = run_ledger(root, db, {'chat_id': GROUP, 'text': 'Állapot: 3/5 kész.'},
                         tool='mcp__plugin_telegram_telegram__edit_message')
    return rc == 0 and 'PRIVÁT-VÁLASZ-KAPU' not in err


@case
def NEG_stale_private_inbound_does_not_lift_the_marker(root):
    # Viktor 40081 L2: Patrik's private message from 2 hours ago does not open his private chat now.
    db = ledger(root, GROUP, PRIV, age_s=2 * 3600)
    rc, err = run_ledger(root, db, {'chat_id': PRIV, 'text': 'Rendben, megnézem.'})
    return rc == 2 and 'PRIVÁT-KAPU' in err and 'PRIVÁT-VÁLASZ-KAPU' not in err


@case
def stale_private_inbound_does_not_close_the_group(root):
    db = ledger(root, GROUP, PRIV, age_s=2 * 3600)
    rc, err = run_ledger(root, db, {'chat_id': GROUP, 'text': 'Rendben, megnézem.'})
    return rc == 0 and 'Traceback' not in err


@case
def fresh_private_inbound_within_30_min_still_decides(root):
    db = ledger(root, GROUP, PRIV, age_s=20 * 60)
    rc, err = run_ledger(root, db, {'chat_id': GROUP, 'text': 'Rendben, megnézem.'})
    return rc == 2 and 'PRIVÁT-VÁLASZ-KAPU' in err


@case
def no_ledger_keeps_marker_rule(root):
    rc, err = run_ledger(root, os.path.join(root, 'nincs.db'), {'chat_id': PRIV, 'text': 'Rendben.'})
    return rc == 2 and 'PRIVÁT-KAPU' in err and not os.path.exists(os.path.join(root, 'nincs.db'))


# Klodel 40686 (Balázs csoport TG 5918 waited): Patrik writes privately about another topic, and the answer to
# Balázs's own group request must still go to the group. Proof: reply_to, or a "BALÁZS-KÉRÉS: TG <id>" line, names a
# fresh group message of an allowlisted non-owner sender in inbound-senders.jsonl. Synthetic ids throughout.
OTHER = '7000000001'  # synthetic third person, not on the allowlist


def group_req_state(root, mid='5918', user=BALAZS, chat=GROUP, age_s=60, allow=(PRIV, BALAZS)):
    import time
    d = os.path.join(root, '.claude', 'channels', 'telegram')
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'access.json'), 'w', encoding='utf-8') as f:
        json.dump({'groups': {GROUP: {'requireMention': False, 'allowFrom': list(allow)}}}, f)
    with open(os.path.join(d, 'inbound-senders.jsonl'), 'w', encoding='utf-8') as f:
        f.write(json.dumps({'chat_id': chat, 'message_id': mid, 'user_id': user,
                            'at': int((time.time() - age_s) * 1000)}) + '\n')


@case
def group_reply_to_balazs_request_passes_while_latest_is_private(root):
    db = ledger(root, GROUP, PRIV)
    group_req_state(root)
    rc, err = run_ledger(root, db, {'chat_id': GROUP, 'reply_to': '5918', 'text': 'Kész a látványterv.'})
    return rc == 0 and 'PRIVÁT-VÁLASZ-KAPU' not in err and 'Traceback' not in err


@case
def group_reply_with_balazs_keres_line_passes_while_latest_is_private(root):
    db = ledger(root, GROUP, PRIV)
    group_req_state(root)
    rc, err = run_ledger(root, db, {'chat_id': GROUP, 'text': 'BALÁZS-KÉRÉS: TG 5918\nKész a látványterv.'})
    return rc == 0 and 'PRIVÁT-VÁLASZ-KAPU' not in err and 'Traceback' not in err


@case
def NEG_group_reply_to_patrik_private_message_still_blocked(root):
    # the reply_to is Patrik's PRIVATE message (another chat): no group record, the gate holds
    db = ledger(root, GROUP, PRIV)
    group_req_state(root, mid='18364', user=PRIV, chat=PRIV)
    rc, err = run_ledger(root, db, {'chat_id': GROUP, 'reply_to': '18364', 'text': 'Rendben, megnézem.'})
    return rc == 2 and 'PRIVÁT-VÁLASZ-KAPU' in err


@case
def NEG_group_reply_to_patrik_own_group_message_still_blocked(root):
    # Patrik is on the allowlist, but he is the owner: his group message is not a teammate's request
    db = ledger(root, GROUP, PRIV)
    group_req_state(root, mid='5917', user=PRIV)
    rc, err = run_ledger(root, db, {'chat_id': GROUP, 'reply_to': '5917', 'text': 'BALÁZS-KÉRÉS: TG 5917\nRendben.'})
    return rc == 2 and 'PRIVÁT-VÁLASZ-KAPU' in err


@case
def NEG_group_request_from_non_allowlisted_sender_still_blocked(root):
    db = ledger(root, GROUP, PRIV)
    group_req_state(root, mid='5920', user=OTHER)
    rc, err = run_ledger(root, db, {'chat_id': GROUP, 'reply_to': '5920', 'text': 'Rendben.'})
    return rc == 2 and 'PRIVÁT-VÁLASZ-KAPU' in err


@case
def NEG_balazs_keres_line_with_unknown_id_still_blocked(root):
    db = ledger(root, GROUP, PRIV)
    group_req_state(root)
    rc, err = run_ledger(root, db, {'chat_id': GROUP, 'text': 'BALÁZS-KÉRÉS: TG 9999\nRendben.'})
    return rc == 2 and 'PRIVÁT-VÁLASZ-KAPU' in err and 'BALAZS-KERES' in err


@case
def NEG_stale_balazs_request_older_than_a_day_still_blocked(root):
    db = ledger(root, GROUP, PRIV)
    group_req_state(root, age_s=25 * 3600)
    rc, err = run_ledger(root, db, {'chat_id': GROUP, 'reply_to': '5918', 'text': 'Rendben.'})
    return rc == 2 and 'PRIVÁT-VÁLASZ-KAPU' in err


@case
def NEG_group_reply_without_any_pointer_still_blocked(root):
    db = ledger(root, GROUP, PRIV)
    group_req_state(root)
    rc, err = run_ledger(root, db, {'chat_id': GROUP, 'text': 'Kész a látványterv.'})
    return rc == 2 and 'PRIVÁT-VÁLASZ-KAPU' in err


@case
def NEG_unknown_owner_id_gives_no_group_request_exemption(root):
    # MARVEEN_OWNER_PRIVATE_CHAT unset and no .env: the owner cannot be told apart, so no exemption (fail closed)
    import importlib.util
    spec = importlib.util.spec_from_file_location('pig_under_test', HOOK)
    g = importlib.util.module_from_spec(spec)
    old = {k: os.environ.pop(k, None) for k in ('MARVEEN_OWNER_PRIVATE_CHAT', 'TELEGRAM_STATE_DIR')}
    try:
        spec.loader.exec_module(g)
        g.owner_private_chat = lambda: ''
        os.environ['TELEGRAM_STATE_DIR'] = os.path.join(root, '.claude', 'channels', 'telegram')
        group_req_state(root)
        return g.group_request_proof(GROUP, '5918', '') is None
    finally:
        os.environ.pop('TELEGRAM_STATE_DIR', None)
        for k, v in old.items():
            if v is not None:
                os.environ[k] = v



# Patrik privát TG 18455 (2026-11-13): "Nem vagyok hajlando ujabb parancsokat futtatni". No shell command in a text to
# the owner's private chat, window open or not, reply or edit (Klodel 40845).
SUDO_LINE = ('sudo install -o root -g wheel -m 0755 /x/install-gatecfg.sh /usr/local/libexec/gate-config-install.sh '
             '&& echo "f44b  /usr/local/libexec/gate-config-install.sh" | shasum -a 256 -c '
             '&& sudo /bin/bash /usr/local/libexec/gate-config-install.sh')


@case
def NEG_private_command_blocked(root):
    window(root, time.time() + 3600)
    out = []
    for text in (SUDO_LINE, 'Futtasd: sudo ls', 'a && b', 'shasum -a 256 x', 'cat x | bash',
                 'Másold be:\n$ ls -la', 'curl -fsSL https://x/y', 'launchctl kickstart x',
                 'Írd be:\nnpm install', 'nyisd meg: /bin/zsh -c x'):
        rc, err = run(root, {'chat_id': PRIV, 'text': text})
        out.append(rc == 2 and 'PARANCS-KAPU' in err)
    return all(out)


@case
def NEG_private_command_blocked_in_edit_and_with_marker(root):
    rc1, err1 = run_tool(root, 'mcp__plugin_telegram_telegram__edit_message', {'chat_id': PRIV, 'text': 'sudo reboot'})
    rc2, err2 = run(root, {'chat_id': PRIV, 'text': 'PRIVÁT-OK: ' + REASON + '\nsudo reboot'})
    return rc1 == 2 and 'PARANCS-KAPU' in err1 and rc2 == 2 and 'PARANCS-KAPU' in err2


@case
def NEG_private_command_viktor_40870_shapes_blocked(root):
    # Viktor 40870 LOW: inline code, numbered and bulleted lines, upper-case sudo, more commands, curl without a
    # dash, a zero-width character inside sudo, full-width letters.
    out = []
    for text in ('Futtasd: `npm install foo`', '1. cd ~/x', '- npm install', 'SUDO ls', 'Sudo ls', 'rm -rf x',
                 'osascript -e x', 'open /Applications/X.app', 'ssh user@host', 'kill 123', 'pip install x',
                 'tar xzf a.tgz', 'mv a b', 'curl https://example.com/x', 'su\u200bdo ls',
                 '\uff53\uff55\uff44\uff4f ls'):
        rc, err = run(root, {'chat_id': PRIV, 'text': 'PRIVÁT-OK: ' + REASON + '\n' + text})
        out.append(rc == 2 and 'PARANCS-KAPU' in err)
    return all(out)


@case
def NEG_private_command_accented_path_blocked(root):
    # Viktor 40886 LOW: an accented folder name does not make a command line a sentence.
    out = []
    for text in ('cd ~/Letöltések', 'rm -rf ~/Letöltések/x', 'open ~/Letöltések/x.pkg', 'git commit -m "javítás"'):
        rc, err = run(root, {'chat_id': PRIV, 'text': 'PRIVÁT-OK: ' + REASON + '\n' + text})
        out.append(rc == 2 and 'PARANCS-KAPU' in err)
    return all(out)


@case
def NEG_private_chat_id_forms_blocked(root):
    # Viktor 40886 INFO 2: "+id", "0id" and an integer id are the same private chat.
    out = []
    for cid in ('+' + PRIV, '0' + PRIV, int(PRIV)):
        rc, err = run(root, {'chat_id': cid, 'text': 'PRIVÁT-OK: ' + REASON + '\nsudo ls'})
        out.append(rc == 2 and 'PARANCS-KAPU' in err)
    return all(out)


def mark(root, kind, chat, value='Patrik privátban kérdezte, privát ügy', agent='klodel', age=0):
    os.environ['REPLY_MARKS_PATH'] = os.path.join(root, 'store', 'reply-marks.jsonl')
    return reply_marks.add(kind, chat, agent, value, now=time.time() - age)


@case
def NEG_mark_spend_recheck_two_runs_one_mark(root):
    # Viktor 40933 INFO 1: two hook runs reserve the same mark before either spends it; only the first spend
    # passes. Simulated in one process (the real hooks are serialised by process start-up, so the race needs this).
    mark(root, 'PRIVAT-OK', PRIV)
    reply_marks._pending.clear()
    a_val = reply_marks.take('PRIVAT-OK', PRIV, 'klodel')
    run_a = list(reply_marks._pending)
    reply_marks._pending.clear()
    b_val = reply_marks.take('PRIVAT-OK', PRIV, 'klodel')
    run_b = list(reply_marks._pending)
    reply_marks._pending[:] = run_a
    first = reply_marks.spend_pending()
    reply_marks._pending[:] = run_b
    second = reply_marks.spend_pending()
    return bool(a_val) and a_val == b_val and first is True and second is False


@case
def mark_taken_twice_in_one_run_spent_once(root):
    # Viktor 40933 INFO 5: the same mark taken twice in one run is one pending entry, so the spend passes.
    mark(root, 'PRIVAT-OK', PRIV)
    reply_marks._pending.clear()
    v1 = reply_marks.take('PRIVAT-OK', PRIV, 'klodel')
    v2 = reply_marks.take('PRIVAT-OK', PRIV, 'klodel')
    pending = len(reply_marks._pending)
    ok = reply_marks.spend_pending()
    with open(os.environ['REPLY_MARKS_PATH'], encoding='utf-8') as f:
        used = sum(1 for line in f if '"used"' in line)
    return bool(v1) and v1 == v2 and pending == 1 and ok is True and used == 1


def load_gate_in(root):
    """The hook module loaded from a copy under root (scripts/hooks, scripts/lib linked), so its install-relative
    files (store/projektek.json) are root's."""
    import importlib.util
    real = os.path.dirname(os.path.dirname(os.path.abspath(HOOK)))
    os.makedirs(os.path.join(root, 'scripts', 'hooks'), exist_ok=True)
    if not os.path.exists(os.path.join(root, 'scripts', 'lib')):
        os.symlink(os.path.join(real, 'lib'), os.path.join(root, 'scripts', 'lib'))
    for f in os.listdir(os.path.join(real, 'hooks')):
        if f.endswith('.py') and not f.endswith('_test.py'):
            dst = os.path.join(root, 'scripts', 'hooks', f)
            if not os.path.exists(dst):
                os.symlink(os.path.join(real, 'hooks', f), dst)
    gate = os.path.join(root, 'scripts', 'hooks', 'gate_copy.py')
    with open(HOOK, encoding='utf-8') as src, open(gate, 'w', encoding='utf-8') as dst:
        dst.write(src.read())
    spec = importlib.util.spec_from_file_location('gate_copy', gate)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@case
def NEG_owner_group_chat_from_projektek_normalised(root):
    # Viktor 40940 INFO: the store/projektek.json branch (no env) is normalised too: "-0..." text, an integer,
    # and {"chat_id": " ... "} are the same group as the canonical id.
    m = load_gate_in(root)
    os.makedirs(os.path.join(root, 'store'), exist_ok=True)
    saved = os.environ.pop('MARVEEN_OWNER_GROUP_CHAT', None)
    out = []
    try:
        for g in ('-0' + GROUP[1:], int(GROUP), {'chat_id': ' ' + GROUP + ' '}):
            with open(os.path.join(root, 'store', 'projektek.json'), 'w', encoding='utf-8') as f:
                json.dump({'elo_uzenet': {'csoport': g}}, f)
            out.append(m.owner_group_chat() == GROUP)
    finally:
        if saved is not None:
            os.environ['MARVEEN_OWNER_GROUP_CHAT'] = saved
    return all(out)


@case
def mark_private_ok_one_message_only(root):
    # Viktor 40894 (a): one mark = one message. The second message needs a new mark (replay refused).
    mark(root, 'PRIVAT-OK', PRIV)
    rc1, _ = run(root, {'chat_id': PRIV, 'text': 'Kész.'}, raw=True)
    rc2, err2 = run(root, {'chat_id': PRIV, 'text': 'Még egy.'}, raw=True)
    return rc1 == 0 and rc2 == 2 and 'PRIVÁT-KAPU' in err2


@case
def NEG_mark_wrong_chat_kind_agent_or_expired(root):
    out = []
    for kind, chat, agent, age in (('PRIVAT-OK', GROUP, 'klodel', 0), ('KESZ-EREDMENY', PRIV, 'klodel', 0),
                                   ('PRIVAT-OK', PRIV, 'dave', 0), ('PRIVAT-OK', PRIV, 'klodel', 200)):
        sub = tempfile.mkdtemp(dir=root)
        mark(sub, kind, chat, agent=agent, age=age)
        rc, err = run(sub, {'chat_id': PRIV, 'text': 'Kész.'}, raw=True)
        out.append(rc == 2 and 'PRIVÁT-KAPU' in err)
    return all(out)


@case
def NEG_mark_two_hooks_at_once_one_passes(root):
    # Viktor 40894 (2): two hooks on one mark at the same time: one passes, the other is refused.
    mark(root, 'PRIVAT-OK', PRIV)
    env = {'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root, 'MARVEEN_OWNER_PRIVATE_CHAT': PRIV,
           'LEDGER_DB_PATH': os.path.join(root, 'nincs-ledger.db'), 'MARVEEN_AGENT_ID': 'klodel',
           'REPLY_MARKS_PATH': os.path.join(root, 'store', 'reply-marks.jsonl')}
    body = json.dumps({'tool_input': {'chat_id': PRIV, 'text': 'Kész.'}})
    ps = [subprocess.Popen([sys.executable, '-I', HOOK], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True, env=env) for _ in range(2)]
    rcs = sorted(p.communicate(body, timeout=20)[1] is not None and p.returncode for p in ps)
    return rcs == [0, 2]


@case
def NEG_mark_kept_after_another_gate_blocks_the_call(root):
    # Klodel 41147: the gate HOLDS the mark for its tool call; only reply-marks-spend.py (PostToolUse, the reply went
    # out) spends it. A call another gate blocked (is_error tool_result in the transcript) leaves the mark.
    mark(root, 'PRIVAT-OK', PRIV)
    tr = os.path.join(root, 'session.jsonl')
    open(tr, 'w').close()
    env = {'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root, 'MARVEEN_OWNER_PRIVATE_CHAT': PRIV,
           'LEDGER_DB_PATH': os.path.join(root, 'nincs-ledger.db'), 'MARVEEN_AGENT_ID': 'klodel',
           'REPLY_MARKS_PATH': os.path.join(root, 'store', 'reply-marks.jsonl')}

    def pre(call):
        body = {'tool_input': {'chat_id': PRIV, 'text': 'Kész.'}, 'tool_use_id': call, 'transcript_path': tr}
        return subprocess.run([sys.executable, '-I', HOOK], input=json.dumps(body), capture_output=True, text=True,
                              env=env, timeout=20).returncode

    def blocked(call):
        with open(tr, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': [
                {'type': 'tool_result', 'tool_use_id': call, 'is_error': True}]}}, separators=(',', ':')) + '\n')

    spend = os.path.join(os.path.dirname(os.path.abspath(HOOK)), 'reply-marks-spend.py')
    a = pre('toolu_A')
    in_flight = pre('toolu_X')  # toolu_A has no tool_result yet: it may still send
    blocked('toolu_A')
    blocked('toolu_X')
    b = pre('toolu_B')
    subprocess.run([sys.executable, '-I', spend], input=json.dumps({'tool_use_id': 'toolu_B'}), env=env,
                   capture_output=True, text=True, timeout=20)
    c = pre('toolu_C')
    return (a, in_flight, b, c) == (0, 2, 0, 2)


@case
def NEG_marker_line_in_text_refused_private_group_edit(root):
    # Viktor 40894 (b): the marker as a line of the text is refused in the private chat, the group and edits.
    out = []
    for chat, tool in ((PRIV, None), (GROUP, None), (PRIV, 'mcp__plugin_telegram_telegram__edit_message')):
        for text in ('PRIVÁT-OK: Patrik privátban kérdezte\nKész.', 'KÉSZ-EREDMÉNY: a kért képek', '- BALÁZS-KÉRÉS: TG 5918',
                     'BELSŐ-ÚT-MÉRVE: 40800', 'PRIVAT-OK: ekezet nelkul', 'priv\u200bát-ok: x'):
            ti = {'chat_id': chat, 'text': text}
            env_run = run_tool(root, tool, ti, raw=True) if tool else run(root, ti, raw=True)
            if chat == GROUP:
                env = {'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root, 'MARVEEN_OWNER_PRIVATE_CHAT': PRIV,
                       'MARVEEN_OWNER_GROUP_CHAT': GROUP, 'LEDGER_DB_PATH': os.path.join(root, 'nincs.db'),
                       'MARVEEN_AGENT_ID': 'klodel'}
                p = subprocess.run([sys.executable, '-I', HOOK], input=json.dumps({'tool_input': ti}),
                                   capture_output=True, text=True, env=env, timeout=20)
                env_run = (p.returncode, p.stderr)
            out.append(env_run[0] == 2 and 'JELÖLŐ-KAPU' in env_run[1])
    # Quoted mid-sentence, it is not a marker line.
    rc, err = run(root, {'chat_id': PRIV, 'text': 'PRIVÁT-OK: ok indok, tíz karakter felett\nA "PRIVÁT-OK:" sor kikerült.'})
    return all(out) and 'JELÖLŐ-KAPU' not in err


@case
def private_plain_text_not_a_command(root):
    window(root, time.time() + 3600)
    ok = []
    for text in ('Kész a film, itt van.', 'Node 22 kell hozzá, ezt mi intézzük.', '#marabel #karacsony',
                 '50 % kedvezmény a második könyvre', 'A git-ben megvan, a csapat élesíti.', 'Install nélkül megy.',
                 'git push megtörtént', 'open: a link nyitva van, nézd meg', '1. Kész a borító.'):
        rc, err = run(root, {'chat_id': PRIV, 'text': text})
        ok.append(rc == 0 and 'PARANCS-KAPU' not in err)
    return all(ok)


@case
def group_command_not_this_gate(root):
    # The command gate is for the owner's private chat only.
    rc, err = run(root, {'chat_id': GROUP, 'text': 'sudo ls && echo ok'})
    return 'PARANCS-KAPU' not in err


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

