#!/usr/bin/env python3
"""Negative tests for balazs-task-reply-gate.py (Patrik group TG 4910/4917). Runs the hook as Claude Code does
(JSON on stdin, exit 0 allow / 2 block). The hook came into the repo from the prod tree (Klodel 38142); these tests
pin its current behaviour.
Run: python3 -I scripts/hooks/balazs-task-reply-gate_test.py
"""
import json
import os
import subprocess
import sys

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'balazs-task-reply-gate.py')
FAILS = []


def run(text, raw=None):
    p = subprocess.run([sys.executable, '-I', HOOK],
                       input=raw if raw is not None else json.dumps({'tool_input': {'chat_id': '1', 'text': text}}),
                       capture_output=True, text=True, env={'PATH': '/usr/bin:/bin'}, timeout=20)
    return p.returncode, p.stderr


def check(name, ok):
    print(('PASS ' if ok else 'FAIL ') + name)
    if not ok:
        FAILS.append(name)


# 1. a task put on Balázs is blocked (any case, accents folded)
blocked = [
    'Balázs, a Google Cloud-ban:\n1. lépj be\n2. nyisd meg',
    'Balázsnak: ez a teendő mára.',
    'BALAZS: csináld meg légyszi a TikTok-kódot.',
    'balázs, vár rád a kártya.',
    'Balázs, kérlek nézd meg.',
]
res = [run(t) for t in blocked]
check('task on Balázs blocked', all(rc == 2 and 'BALAZS-KAPU' in err for rc, err in res))

# 2. allowed: with a BALAZS-OK line, or Balázs only mentioned, or no task shape
check('BALAZS-OK line lets it through', run('Balázs, kérlek nézd meg.\nBALAZS-OK: TG 5400')[0] == 0
      and run('Balázs, kérlek nézd meg.\nbalázs ok: TG 1')[0] == 0)
check('BALAZS-OK without a value does not', run('Balázs, kérlek nézd meg.\nBALAZS-OK:')[0] == 2)
# Viktor 38148 L1: the value must be a TG number
check('BALAZS-OK with a non-TG value does not', all(run('Balázs, kérlek nézd meg.\nBALAZS-OK: ' + v)[0] == 2
                                                    for v in ('x', '?', 'TG', 'Patrik kérte', 'msg 38093')))
check('BALAZS-OK: Patrik TG n / TG #n passes', run('Balázs, kérlek nézd meg.\nBALAZS-OK: Patrik TG 4864')[0] == 0
      and run('Balázs, kérlek nézd meg.\nBALAZS-OK: TG #4864')[0] == 0)
check('Balázs only mentioned (not addressed): allowed', run('Kész a teszt, Balázs tesztje szerint is jó.\n1. pont')[0] == 0)
check('addressed without a task shape: allowed', run('Balázs, köszi, jó lett!')[0] == 0)

# 3. PR go-ask to Patrik needs PATRIK-KERTE
check('PR go-ask without PATRIK-KERTE blocked', run('PR #183 mehet élesbe?')[0] == 2
      and 'PR-KÉRÉS-KAPU' in run('PR #183 mehet?')[1])
check('PR go-ask with PATRIK-KERTE allowed', run('PR #183 mehet?\nPATRIK-KÉRTE: TG 17000')[0] == 0)
check('PR mentioned without a go-ask allowed', run('A PR #183 mergelve.')[0] == 0)

# 5. Klodel 39569 (Patrik TG 18102): an addressed RESULT with a numbered list is not a task; a task verb still is.
CAPAS = ('Balázs, a cápás keresés eredménye (Szigma): három szellemi termék jött fel, de egyik sem erős.\n'
         '1. Scholly: ösztöndíj-kereső app (Shark Tank US, 40 000 USD; 2023-ban felvásárolták).\n'
         '2. Talentcube: videós állásjelentkezés (Die Höhle der Löwen, 400 000 EUR). Céges termék, ez a leggyengébb.\n'
         '3. Finanzguru: szerződés- és költségkövető (DHDL, 1 M EUR).\n'
         'Itthon egyiknek sem találtunk megfelelőjét az app-boltokban.')
check('result list addressed to Balázs allowed (the cápás text)', run(CAPAS)[0] == 0)
check('English -ned words in a result are not a task', run('Balázs, eredmény:\n1. Scholly: signed, learned, designed.')[0] == 0)
task_texts = [CAPAS + '\nNézd meg, melyik tetszik.', 'Balázs:\n1. jelentkezz be\n2. kattints a Mentésre',
              'Balázs, a lista:\n1. Scholly\n2. Talentcube\nMegnéznéd, melyik jó?', 'Balázs:\n1. töltsd fel a videót',
              'Balázs, a lista:\n1. Scholly\nLégyszi küldd tovább.']
res = [run(t) for t in task_texts]
check('negative: a numbered list WITH a task verb still blocks', all(rc == 2 and 'BALAZS-KAPU' in err for rc, err in res))
check('a task verb without a list adds no block (no wider gate)', run('Balázs, nem neked kell átvenned, mi intézzük.')[0] == 0)

# 4. malformed payload: nothing to read, allowed
check('malformed payload allowed (exit 0, not a crash)', run('', raw='not json')[0] == 0
      and run('', raw='[1]')[0] == 0 and run('', raw='{"tool_input": "text"}')[0] == 0)

print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'All balazs-task-reply-gate tests passed.'}")
sys.exit(1 if FAILS else 0)
