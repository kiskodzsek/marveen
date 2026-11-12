#!/usr/bin/env python3
"""Tests for scripts/elo-allapot-valtozas.py (Klodel 39721, card 12610b8d): the live status message is edited only
when it changed beyond the "frissítve HH:MM" stamps and the daily joke.

Hermetic: synthetic text in the shape of ops/elo_allapot.py's output, a temp state file (--state), no store/ write.
Run: python3 -I scripts/__tests__/elo-allapot-valtozas.test.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), 'elo-allapot-valtozas.py')


def text(stamp='16:50', joke='A babás film ma is szebb, mint a tegnapi.', done=1, visitors=('16:55', 12),
         var=('Ads-keret jóváhagyása',)):
    out = [f'📊 ÉLŐ ÁLLAPOT · frissítve {stamp}', '']
    if visitors:
        out += ['👥 ÉRKEZÉSEK MA (szerveroldali belépések, Szigma)',
                f'belépés {visitors[1]} (kampánylinkről 0, közösségi 3), próba 1, regisztráció 0, pénztárig 0, vásárlás 0',
                f'frissítve {visitors[0]}', '']
    out += [f'🟡 Receptkönyv: {done}/3 · {round(100 * done / 3)}%', '🟨🟨🟨⬜⬜⬜⬜⬜⬜⬜', '👉 most: nyomdai minta', '']
    if var:
        out += [f'🙋 PATRIKRA VÁR ({len(var)})'] + [f'• {v}' for v in var] + ['']
    if joke:
        out += [f'😄 {joke}', '']
    out.append('10 percenként frissül; ha valami kész vagy elakad, külön szólok.')
    return '\n'.join(out)


def run(state, stdin, *args):
    p = subprocess.run([sys.executable, '-I', SCRIPT, 'csoport', '--state', state, *args], input=stdin,
                       capture_output=True, text=True, timeout=20)
    return p.returncode, p.stdout


def read(path):
    try:
        with open(path, encoding='ascii') as fh:
            return fh.read()
    except OSError:
        return None


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def first_run_is_a_change_and_records(state):
    t = text()
    code, out = run(state, t)
    return code == 0 and out == t and read(state) is not None and len(read(state).strip()) == 64


@case
def only_stamps_and_joke_differ_is_no_change(state):
    run(state, text())
    before = read(state)
    code, out = run(state, text(stamp='17:00', joke='Új nap, új poén a csapatról.', visitors=('17:55', 12)))
    return code == 3 and out == '' and read(state) == before


@case
def joke_gone_or_new_is_no_change(state):
    run(state, text())
    return run(state, text(joke=None))[0] == 3 and run(state, text(joke='Még egy.'))[0] == 3


@case
def a_step_done_is_a_change(state):
    run(state, text())
    code, out = run(state, text(stamp='17:00', done=2))
    return code == 0 and '2/3' in out and run(state, text(stamp='17:10', done=2))[0] == 3


@case
def visitor_numbers_or_block_ageing_out_is_a_change(state):
    run(state, text())
    return run(state, text(visitors=('17:55', 13)))[0] == 0 and run(state, text(visitors=None))[0] == 0


@case
def patrikra_var_change_is_a_change(state):
    run(state, text())
    return run(state, text(var=('Ads-keret jóváhagyása', 'Nyomdai minta OK')))[0] == 0


@case
def no_record_compares_only(state):
    run(state, text())
    before = read(state)
    code, out = run(state, text(done=3), '--no-record')
    return code == 0 and out and read(state) == before and run(state, text(done=3))[0] == 0


@case
def empty_input_or_bad_usage_never_edits(state):
    p = subprocess.run([sys.executable, '-I', SCRIPT, 'mindegy', '--state', state], input=text(),
                       capture_output=True, text=True, timeout=20)
    return (run(state, '')[0] == 2 and run(state, '  \n')[0] == 2 and read(state) is None
            and p.returncode == 2 and p.stdout == '')


@case
def unreadable_state_counts_as_change(state):
    os.makedirs(os.path.dirname(state))
    with open(state, 'wb') as fh:
        fh.write(b'\xff\xfe garbage')
    return run(state, text())[0] == 0


def main():
    failed = 0
    for fn in CASES:
        with tempfile.TemporaryDirectory() as d:
            try:
                ok = fn(os.path.join(d, 'store', 'elo-allapot-csoport.sha256'))
            except Exception as e:  # a crash is a failure, with its reason
                ok = False
                print(f'ERROR {fn.__name__}: {e!r}')
        print(('PASS ' if ok else 'FAIL ') + fn.__name__)
        failed += not ok
    print(f'{len(CASES) - failed}/{len(CASES)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
