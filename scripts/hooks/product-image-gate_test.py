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
                 majsztro='nem-marketing teszt-fixture', uzenet=None):
    kapu = os.path.join(root, 'store', 'kep-kapu')
    os.makedirs(kapu, exist_ok=True)
    img = os.path.join(root, 'kep.png')
    crop = os.path.join(root, 'crop.png')
    for f in (img, crop):
        open(f, 'wb').write(b'\x89PNG')
    lines = ['KONYV: van', 'A5: ok', 'PAPIR: feher', 'SAJAT: ok', 'KERES: teszt kérés, egyezik',
             f'NAGYITVA: {crop}', f'MAJSZTRO: {majsztro}',
             'EP: ok a teljes jelenet ép, semmi nincs levágva', 'HELY: tiszta asztalon fekszik',
             f'MERCE: {merce}', f'KEZ: {kez}', 'FENY: papír L* 88 / jelenet L* 92, finom gerinc']
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


# UZENET + VALODI (Patrik TG 14836, shared/hibanaplo.md 2026-11-06 13:37, card ca0737c2).
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
