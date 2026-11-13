#!/usr/bin/env python3
"""Unit tests for scripts/lib/vevo_nem_ir.py (card 42b5e28a, Patrik TG 18398, 18401, 18412).

Every label has a positive case (the contrast form too: Patrik TG 18412 "nehogy megtévesztő legyen"), and every
form narrowed out on 30 days of real traffic has a negative case, so a widened or narrowed regex shows up here.
Run: python3 -I scripts/lib/vevo_nem_ir_test.py
"""
import importlib.util
import os
import sys

_spec = importlib.util.spec_from_file_location(
    'vevo_nem_ir', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vevo_nem_ir.py'))
vni = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vni)

TOLL = 'toll'
RAG = 'ragasztó / ragasztás'
KEZ = 'kézírás / kézzel ír'
IR = 'ír a könyvbe'
NAPLO = 'naplóz / naplót vezet'
MAS = 'más (üres) babanapló'

# (text, the label that must be found)
POSITIVE = [
    ('anya tollal ír', TOLL),
    ('A kép sarkában egy golyóstoll.', TOLL),
    ('Toll az asztalon', TOLL),
    ('filctollak a háttérben', TOLL),
    ('nem ragasztgatunk képet', RAG),
    ('ragasztó és olló', RAG),
    ('a fotót beragasztja', RAG),
    ('felragasztott fénykép', RAG),
    ('ragaszt egy fotót', RAG),
    ('a képet ragasztja be', RAG),
    ('kézírás a lapon', KEZ),
    ('kézírásos jegyzet', KEZ),
    ('nem kell kézzel írni', KEZ),
    ('kézzel beleírja', KEZ),
    ('kézzel írható oldal', KEZ),
    ('anya írja a könyvet', IR),
    ('beleírja a könyvbe', IR),
    ('beírja a babakönyvbe', IR),
    ('írunk a könyvünket', IR),
    ('a könyvbe beleír', IR),
    ('anya naplóz', NAPLO),
    ('nem kell naplózni', NAPLO),
    ('naplót vezet minden nap', NAPLO),
    ('naplózgatás helyett', NAPLO),
    ('egy üres babanapló', MAS),
    ('kitöltős emlékkönyv', MAS),
    ('a régi papír babanapló', MAS),
    ('hagyományos babakönyv', MAS),
    ('más naplo', MAS),
    # folding: accents, case, zero-width characters and soft hyphens
    ('TOLLAL', TOLL),
    ('kez​zel írni', KEZ),
    ('nap­lóz', NAPLO),
    ('ＴＯＬＬ', TOLL),  # full-width letters fold by NFKC
    # a quote without a TG number on the line is checked
    ('"anya naplóz benne"', NAPLO),
    # a TG line is checked outside the quote
    ('Patrik TG 18395 "x", és anya naplóz', NAPLO),
    # a TILOS: line only exempts itself, not the next line
    ('TILOS: toll\nde a jelenetben toll van', TOLL),
]

# texts that must stay clean
NEGATIVE = [
    'naplózva a ledgerben',
    'naplózd a futást',
    'a kézirat lektorálása',
    'a fotó ráragasztottnak hat, javítsd',
    'ragasztott kötés, keményborító',
    'babanapló kulcsszó a SEO-hoz',
    'Pamacs tollazata puha',
    'tollas bagoly',
    'kézbesítés írásban',
    'a könyv magától készül, a mesélő mesél',
    'írja meg az üzenetet',
    'Patrik TG 18395 "a könyv ahogy naplóz anya benne"',
    'Patrik (TG 18412): „ne tegyél bele olyan könyvet, h ragasztgatni kell meg kézzel írni”',
    'TILOS: toll, ragasztó, kézírás, ír a könyvbe, naplóz, üres babanapló',
    '  tilos:   toll',
    'atollal',  # a word that only contains "toll" after a letter
    'kontroll',
    'kézzel írat',  # kezzel ir(?!at)
    '',
]

MATERIAL_YES = ['Reel koncepció', 'a hirdetéskép', 'új jelenet', 'TikTok poszt', 'storyboard v2']
MATERIAL_NO = ['a kapu tesztje', 'PR #268 review', 'migráció időbélyeg']


def main():
    bad = 0
    for text, label in POSITIVE:
        got = vni.found(text)
        if label not in got:
            print(f'FAIL positive {text!r}: want {label!r}, got {got}')
            bad += 1
    for text in NEGATIVE:
        got = vni.found(text)
        if got:
            print(f'FAIL negative {text!r}: got {got}')
            bad += 1
    for text in MATERIAL_YES:
        if not vni.is_material(text):
            print(f'FAIL material {text!r}')
            bad += 1
    for text in MATERIAL_NO:
        if vni.is_material(text):
            print(f'FAIL not material {text!r}')
            bad += 1
    # order and dedup: one label per kind, in TERMS order
    got = vni.found('toll, toll, naplóz, ragasztó')
    if got != [TOLL, RAG, NAPLO]:
        print(f'FAIL order {got}')
        bad += 1
    r = vni.reason([TOLL], 'az .ok lapban:')
    if 'TG 18398' not in r or 'az .ok lapban: toll' not in r or 'TILOS:' not in r:
        print(f'FAIL reason {r!r}')
        bad += 1
    if [l for l, _ in vni.TERMS] != [TOLL, RAG, KEZ, IR, NAPLO, MAS]:
        print('FAIL the six labels changed')
        bad += 1
    n = len(POSITIVE) + len(NEGATIVE) + len(MATERIAL_YES) + len(MATERIAL_NO) + 3
    print(f'{n - bad}/{n} pass')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
