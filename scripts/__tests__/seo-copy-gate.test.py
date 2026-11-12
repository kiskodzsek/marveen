#!/usr/bin/env python3
"""Tests for scripts/seo_copy_gate.py (Klodel 39141, card 2994d805; hibanapló 2026-11-12 10:06).

The two failures of 2026-11-12 are the negative cases, word for word from the set that passed three
reviews: the /elso-eved H1 "Babanapló, de több annál: ..." (no "több mint egy babanapló", Patrik TG 17921)
and the /marabello title/H1 "Anyák napi ajándék: ..." / "Ajándék anyának, ..." (a four-option product
narrowed to one occasion). The corrected set passes. Synthetic copy, no customer data.
Run: python3 -I scripts/__tests__/seo-copy-gate.test.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), 'seo_copy_gate.py')
_spec = importlib.util.spec_from_file_location('seo_copy_gate', SCRIPT)
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)

Q = 'Patrik TG 17921: „... derüljön ki h ez nem csak egy sima Babanapló.. Több mint egy Babanaplo vagy vmi”'
RULES = {
    '/elso-eved': {'h1_kotelezo': [{'kifejezes': 'több mint egy babanapló', 'forras': Q, 'mezok': ['h1', 'title']}]},
    '/marabello': {'tiltott': [{'kifejezes': 'anyák nap', 'forras': Q}, {'kifejezes': 'anyának', 'forras': Q}]},
}
NEW = {
    '/elso-eved': {'title': 'Több mint egy babanapló: könyv a ti szavaitokból',
                   'h1': 'Több mint egy babanapló. Az első évére ő még nem fog emlékezni. Ti igen.',
                   'first_sentence': 'Babanapló az első évről: pillanatokat meséltek el fotókkal.'},
    '/marabello': {'title': 'Egyedi ajándék: leporelló a saját szavaidból',
                   'h1': 'Egyedi ajándék, ami néhány saját mondatból készül.',
                   'first_sentence': 'Öt üzenet a saját szavaiddal, kicsi, kihajtható leporellóban: egyedi ajándék, ami csak tőled szól.'},
}
# The set of 2026-11-12 before the fix (title-h1-vegleges.json.bak-39170 and Klodel 39044 for /marabello).
OLD = {
    '/elso-eved': {'title': 'Babanapló, de több: ti meséltek, könyv lesz belőle',
                   'h1': 'Babanapló, de több annál: az első évére ő még nem fog emlékezni. Ti igen.',
                   'first_sentence': NEW['/elso-eved']['first_sentence']},
    '/marabello': {'title': 'Anyák napi ajándék: leporelló a saját szavaidból',
                   'h1': 'Ajándék anyának, ami néhány saját mondatodból készül.',
                   'first_sentence': 'Anyák napi ajándék, ami csak tőled szól: öt üzenet a saját szavaiddal, kicsi, kihajtható leporellóban.'},
}


def run(copy, rules):
    with tempfile.TemporaryDirectory() as d:
        c, r = os.path.join(d, 'c.json'), os.path.join(d, 'r.json')
        json.dump(copy, open(c, 'w', encoding='utf-8'), ensure_ascii=False)
        json.dump(rules, open(r, 'w', encoding='utf-8'), ensure_ascii=False)
        p = subprocess.run([sys.executable, '-I', SCRIPT, c, r], capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr


def test_corrected_set_passes():
    rc, out = run(NEW, RULES)
    assert rc == 0 and 'OK (3 szabály, 2 oldal)' in out, out


def test_old_set_fails_on_both_mistakes_of_the_day():
    rc, out = run(OLD, RULES)
    assert rc == 1, out
    assert '/elso-eved h1: hiányzik a kötelező „több mint egy babanapló” (Patrik TG 17921)' in out, out
    assert '/elso-eved title: hiányzik' in out, out
    assert '/marabello title: tiltott „anyák nap”' in out, out
    assert '/marabello first_sentence: tiltott „anyák nap”' in out, out
    assert '/marabello h1: tiltott „anyának”' in out, out
    assert '5 szabály sérül' in out, out


def test_each_mistake_alone_fails():
    one = json.loads(json.dumps(NEW)); one['/elso-eved'] = OLD['/elso-eved']
    assert run(one, RULES)[0] == 1
    two = json.loads(json.dumps(NEW)); two['/marabello']['h1'] = 'Egyedi ajándék Anyák napjára.'
    rc, out = run(two, RULES)
    assert rc == 1 and 'tiltott „anyák nap”' in out, out


def test_word_start_matching_case_suffix_and_spaces():
    assert G.contains('ANYÁK  NAPJÁRA', 'anyák nap')
    assert G.contains('Több  mint egy\nBabanapló.', 'több mint egy babanapló')
    assert not G.contains('ajándék nagyanyának', 'anyának')
    assert G.contains('ajándék anyának', 'anyának')


def test_fail_closed_inputs():
    # a ruled page missing from the copy, a rule without a TG source, an unknown key, a bad field: exit 2
    assert run({'/marabello': NEW['/marabello']}, RULES)[0] == 2
    no_src = {'/marabello': {'tiltott': [{'kifejezes': 'anyák nap', 'forras': 'Klodel szerint'}]}}
    rc, out = run(NEW, no_src)
    assert rc == 2 and 'TG <n>' in out, out
    assert run(NEW, {'/marabello': {'tilott': []}})[0] == 2
    assert run(NEW, {'/marabello': {'tiltott': [{'kifejezes': 'x', 'forras': Q, 'mezok': ['meta']}]}})[0] == 2
    assert run(NEW, {})[0] == 2


def test_usage():
    p = subprocess.run([sys.executable, '-I', SCRIPT], capture_output=True, text=True)
    assert p.returncode == 64


CASES = [test_corrected_set_passes, test_old_set_fails_on_both_mistakes_of_the_day, test_each_mistake_alone_fails,
         test_word_start_matching_case_suffix_and_spaces, test_fail_closed_inputs, test_usage]


def main():
    failed = 0
    for fn in CASES:
        try:
            fn()
            print(f'ok   {fn.__name__}')
        except AssertionError as e:
            failed += 1
            print(f'FAIL {fn.__name__}: {e}')
    print(f'{len(CASES) - failed}/{len(CASES)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
