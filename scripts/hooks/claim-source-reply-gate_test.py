#!/usr/bin/env python3
"""Tests for claim-source-reply-gate.py (Klodel 35761, Patrik group TG 4477, audit item 3; site state: Klodel 36285).

Hermetic: throwaway CLAUDE_PROJECT_DIR, synthetic chat ids, no network, no ledger. The sentences are modelled on the
replay of 2026-11-08/10 (828 real replies): what must block, and the false blocks the rules were cut against.
Run: python3 -I scripts/hooks/claim-source-reply-gate_test.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, 'claim-source-reply-gate.py')
spec = importlib.util.spec_from_file_location('gate', GATE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

FAILS = 0
N = 0


def ok(name, cond, detail=''):
    global FAILS, N
    N += 1
    print(('PASS  ' if cond else 'FAIL  ') + name + ('' if cond or not detail else f'  -- {detail}'))
    if not cond:
        FAILS += 1


BLOCK = [
    ('Kész a papás film (35 mp), a te mondataiddal.', 'kész'),
    ('A próba-javítás kódban kész, a tesztjei zöldek.', 'kész'),
    ('Elkészült a receptkönyv borítója.', 'kész'),
    ('Lex jogi sorai már készen vannak hozzá.', 'kész'),
    ('Beállítottam a heti retrót péntek 15:00-ra.', 'beállítva'),
    ('Igen, a próba élesben fut a hétvége óta.', 'élesben'),
    ('A chat-könyv élesítve, csak adminnak látszik.', 'élesben'),
    ('Most egy render fut a minin.', 'fut'),
    ('A poszt kint van a Facebookon.', 'kint van'),
    ('A levél kiment a nyomdának.', 'kiment'),
    ('A konverzió 3,4 % lett a héten.', '%'),
    ('A számla 180 400 Ft, holnap esedékes.', 'Ft'),
    ('A fal-keret 25 $ maradt.', '$/EUR'),
    ('Ma 12 db próba indult.', 'db'),
    ('A pontos számok 15 percen belül jönnek.', 'perc múlva'),
    # retro R2 (card 8639a3bb): a capability told as a fact; the first is the TG 6035 reply, word for word in part
    ('Igen, pont ezt a posztot ki tudjuk emelni: Mira a Marabel hirdetési fiókjában a meglévő posztra épít hirdetést.',
     'képesség'),
    ('Kiemelhetjük a posztot.', 'képesség'),
    ('A feltöltés működik.', 'képesség'),
    ('Meg lehet oldani holnapra.', 'képesség'),
    ('Be van állítva a keret.', 'képesség'),
    ('Mira be tudja állítani a hirdetést.', 'képesség'),
    ('API-n ki tudunk posztolni.', 'képesség'),
    ('Képesek vagyunk rá.', 'képesség'),
    ('Feltölteni tudjuk mi is.', 'képesség'),
]
PASS_NO_CLAIM = [
    'Kész van már a papás?',                                   # a question
    'Még nincs kész, Dave rajta van.',                         # negated
    'Ha kész, ide teszem.',                                    # conditional
    'Amint a MacBookodon tényleg fut, egy sorban szólok.',     # conditional with words between
    'Élesben addig semmi nem változik.',                       # negated clause
    'Ma nem tervet hozok, hanem kész anyagot.',                # attributive kész
    '17:30-ra 3 kész, posztolható videó jön.',                 # attributive kész
    'Holnapra kész lesz a borító.',                            # future
    'Kiválasztod, a csúszkával beállítod, és kész.',           # idiom
    'Patrik azt írta: «kész van már a film?»',                 # quoted
    'Írd át „élesben fut” helyett erre.',                       # quoted
    'Dave indítja a renderelést, utána szólok.',               # plan, no state word
    'Tudjuk, hogy ma késik.',                                  # "tud" = know, no infinitive
    'Nem tudjuk kiemelni, mert a profil posztja.',             # negated capability
    'Ki tudjuk emelni?',                                       # a question
    'Ha működik, szólok.',                                     # conditional
    'Lehet, hogy holnap.',                                     # "maybe", no infinitive
    'Pulzus megnézi, működik-e a próba.',                      # indirect question
    'Megmutatom, hogyan működik.',                             # explaining how
    'Holnap reggel mire működik a feltöltés, szólok.',         # "mire" mid-clause: not yet a fact
    'A filmet lejátszva fel tudod hozzá mondani.',             # an instruction to the reader, not our capability
    'Nagyi, én is tudok kalácsot sütni!',                      # customer copy, first person singular
]
PASS_WITH_SOURCE = [
    'Kész a papás film. FORRÁS: agents/dave/work/papa-film-1110/out/tt/papa.mp4',
    'A próba élesben fut (Pulzus mérte, 13:42).',
    'Mértem 19:37-kor: még Opus 5.5-ön futok, 3 % a keret.',
    'Élesben: #151 és #152 beolvasztva.',
    'Kész, PR 150 mergelhető.',
    'Kész, msg_id:35777 szerint élesben.',
    'A számla 180 400 Ft (Juró jelzése).',
    'Kész az átvilágítás: shared/atvilagitas-1110/atvilagitas.md',
    'Élesben van: https://marabel.hu/receptkonyv',
    'Élesben a main ef54015c commiton.',
    'Kint van, TG 4477 szerint mehetett.',
    'A konverzió 3 % (becslés (Szigma szerint), a heti adatból).',
    'Ki tudjuk emelni, Mira 41144 szerint.',
]
# A capability may go out as a labelled guess; a state claim may not (retro R2).
CAP_HEDGED = ['Ki tudjuk emelni (tipp, nem mértem).', 'Ezt tudjuk kinyerni belőle (a megvalósíthatóság tipp).',
              'Szerintem meg lehet oldani, de nem ellenőriztem.']

# Site state (hibanapló 2026-11-10 12:06, Patrik TG 4564; Klodel 36285): only with a MEASUREMENT.
SITE_BLOCK = [
    'A mySHP-oldal úgyis alszik',                                  # the original sentence (TG 4563)
    'A mySHP-oldal úgyis alszik, ezért nem sürgős.',
    'A marabel.hu leállt.',
    'A webshop alvó állapotban van, nem kell vele foglalkozni.',
    'A myshp.hu le van állva.',
    'A Marabel nyitóoldala leállt tegnap este.',
    # a source that is not a measurement does not clear a site's state
    'A mySHP-oldal alszik (CLAUDE.md szerint).',
    'A mySHP-oldal alszik, TG 4563.',
    'A myshp.hu alszik: https://myshp.hu',
    'A marabel.hu leállt, PR #1263.',
]
SITE_PASS_NO_CLAIM = [
    'A mySHP részleg alvó, Kernel viszi.',                          # the department label, not the site
    'mySHP: alvó részleg.',
    'A szabályaimban a mySHP mint csapatrészleg van alvónak jelölve (CLAUDE.md), és ezt vittem át az oldalra.',  # TG 4567
    'Nem alszik a myshp oldal.',                                    # negated
    'Leállt a mySHP-oldal?',                                        # a question
    'Ha a marabel.hu leállt, Pulzus kapcsol.',                     # conditional
    'Patrik: «a myshp oldal alszik»',                               # quoted
    'A render leállt a minin.',                                     # no site
    'A földalatti leállt.',                                         # "oldal" inside another word
]
SITE_PASS_MEASURED = [
    'A marabel.hu leállt (mérve: HTTP 503, 14:58).',
    'A mySHP-oldal alszik: Pulzus mérte 15:02-kor.',
    'A myshp.hu leállt, státusz 502 (mértem 15:01).',
]
for text in SITE_BLOCK:
    ok(f'site state, no measurement: {text!r} -> blocks', gate.SITE_LABEL in gate.unsourced(text, []),
       (gate.claims(text), gate.unsourced(text, [])))
for text in SITE_PASS_NO_CLAIM:
    ok(f'site: no claim: {text!r}', gate.SITE_LABEL not in gate.claims(text), gate.claims(text))
for text in SITE_PASS_MEASURED:
    ok(f'site: measured: {text!r}', gate.SITE_LABEL in gate.claims(text) and gate.unsourced(text, []) == [],
       (gate.claims(text), gate.unsourced(text, [])))
ok('site: a screenshot attached is the measurement', gate.unsourced('A marabel.hu leállt.', ['/x/shot.png']) == [])
ok('site: the general claims keep their old rule', gate.unsourced('Kész, PR 150 mergelhető.', []) == [])

for text, label in BLOCK:
    got = gate.claims(text)
    ok(f'claim: {text!r} -> {label}', label in got, got)
    ok(f'  ...and no source in it', not gate.has_source(text, []), text)
for text in PASS_NO_CLAIM:
    ok(f'no claim: {text!r}', gate.claims(text) == [], gate.claims(text))
for text in PASS_WITH_SOURCE:
    ok(f'claim with source: {text!r}', gate.claims(text) != [] and gate.has_source(text, []), (gate.claims(text), text))
for text in CAP_HEDGED:
    ok(f'capability as a labelled guess passes: {text!r}', 'képesség' in gate.claims(text)
       and gate.unsourced(text, []) == [], (gate.claims(text), gate.unsourced(text, [])))
ok('a guess label does not clear a state claim', gate.unsourced('Kész a film (tipp).', []) == ['kész'],
   gate.unsourced('Kész a film (tipp).', []))
ok('"tippet" is no label', gate.unsourced('Ki tudjuk emelni, kérek tippet.', []) == ['képesség'])
# The guess label counts in the capability's own sentence, and a denied label is none (Viktor 41287 LOW 1).
CAP_LABEL_ELSEWHERE = [
    'Ki tudjuk emelni. Egyébként a tipp: holnap szólok.',      # Viktor's case: the label in another sentence
    'Ki tudjuk emelni! Ez nem tipp, ez biztos.',               # Viktor's case: a denied label, another sentence
    'Ki tudjuk emelni, ez nem tipp.',                          # a denied label in the same sentence
    'Ki tudjuk emelni, és ez sem tipp.',
    'Ki tudjuk emelni, ez nem egy tipp.',
    'Ki tudjuk emelni (tipp). A feltöltés is működik.',       # two capabilities, only the first one labelled
]
for text in CAP_LABEL_ELSEWHERE:
    ok(f'capability, no label in its own sentence: {text!r} -> blocks', gate.unsourced(text, []) == ['képesség'],
       (gate.claims(text), gate.unsourced(text, [])))
for text in ['Ki tudjuk emelni (tipp). Holnap szólok.', 'Ki tudjuk emelni (tipp). A feltöltés is működik (tipp).',
             'Holnap szólok. Ki tudjuk emelni, de ez csak tipp.']:
    ok(f'every capability sentence labelled: {text!r} -> passes', gate.unsourced(text, []) == [],
       (gate.claims(text), gate.unsourced(text, [])))
ok('a source anywhere still clears every capability sentence',
   gate.unsourced('Ki tudjuk emelni. A feltöltés is működik. Mira mérte, msg 41144.', []) == [])
# Boundary cases (Viktor 41287 INFO 3/4): the "tud ... -ni" window takes up to two words between, not three; the
# -hetem form is a capability too.
for text in ['Tudjuk a posztot kiemelni.', 'Tudjuk majd emelni.', 'Kiemelhetem a posztot.']:
    ok(f'capability boundary: {text!r} -> blocks', gate.unsourced(text, []) == ['képesség'],
       (gate.claims(text), gate.unsourced(text, [])))
ok('three words between "tud" and the infinitive: no capability (the window is {0,2})',
   'képesség' not in gate.claims('Tudjuk majd a posztot kiemelni.'), gate.claims('Tudjuk majd a posztot kiemelni.'))
ok('an attached file is the source', gate.has_source('Kész a papás film.', ['/x/papa.mp4']))
ok('"mert" (because) is not "mérte"', not gate.has_source('Kész, mert Dave megcsinálta.', []))
ok('"szerintem" is not an attribution', not gate.has_source('Szerintem kész van.', []))
ok('a bare number is not a PR', not gate.has_source('Kész a 3 videó.', []))

# ---- the hook end to end, in a throwaway project dir ----
root = tempfile.mkdtemp(prefix='claimsrc-')
os.makedirs(os.path.join(root, 'store'))
with open(os.path.join(root, 'store', 'projektek.json'), 'w') as f:
    json.dump({'elo_uzenet': {'privat': {'chat_id': '111'}, 'csoport': '-222'}}, f)


def run(chat, text, files=None):
    ti = {'chat_id': chat, 'text': text, **({'files': files} if files else {})}
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root)
    env.pop('MARVEEN_OWNER_CHATS', None)
    r = subprocess.run([sys.executable, '-I', GATE], input=json.dumps({'tool_input': ti}), capture_output=True,
                       text=True, env=env, timeout=30)
    return r.returncode, r.stderr


rc, err = run('-222', 'Most egy render fut a minin, a babás kész.')
ok('hook: group, claim without source -> exit 2', rc == 2, f'rc={rc}')
ok('  ...names the claims and the way out', 'fut' in err and 'kész' in err and 'FORRÁS' in err, err)
log = os.path.join(root, 'store', 'claim-source-gate.log')
line = json.loads(open(log).read().splitlines()[-1]) if os.path.exists(log) else {}
ok('  ...logged: chat kind, labels, length, never the text', line.get('chat') == 'csoport'
   and set(line.get('claims', [])) == {'fut', 'kész'} and 'text' not in line and 'minin' not in json.dumps(line), line)
rc, _ = run('111', 'Kész a papás film.')
ok('hook: private chat is gated too', rc == 2)
os.environ['CLAIM_SOURCE_GATE_MODE'] = 'log'
rc, _ = run('111', 'Kész a papás film.')
del os.environ['CLAIM_SOURCE_GATE_MODE']
last = json.loads(open(log).read().splitlines()[-1])
ok('hook: log mode -> passes, but logged as log-only', rc == 0 and last.get('chat') == 'privat (log-only)', last)
rc, _ = run('111', 'Kész a papás film.', ['/x/papa.mp4'])
ok('hook: with the file attached -> passes', rc == 0)
rc, _ = run('111', 'Kész a papás film (Dave mérte, 11:06).')
ok('hook: with a source -> passes', rc == 0)
rc, _ = run('999', 'Most egy render fut.')
ok('hook: another chat is not gated', rc == 0)
rc, err = run('111', 'A mySHP-oldal úgyis alszik')
ok('hook: the original sentence (TG 4563) -> exit 2, names the site rule', rc == 2 and 'oldal-állapot' in err
   and 'mérve' in err, f'rc={rc} {err}')
rc, _ = run('111', 'A marabel.hu leállt (mérve: HTTP 503, 14:58).')
ok('hook: site state with a measurement -> passes', rc == 0)
rc, _ = run('-222', 'A mySHP részleg alvó, Kernel viszi.')
ok('hook: the department label -> passes', rc == 0)
rc, err = run('-222', 'Igen, pont ezt a posztot ki tudjuk emelni: Mira a meglévő posztra épít hirdetést.')
ok('hook: the TG 6035 reply -> exit 2, names the capability rule', rc == 2 and 'képesség' in err and 'tipp' in err,
   f'rc={rc} {err}')
rc, _ = run('-222', 'Ki tudjuk emelni: Mira mérte, msg 41144.')
ok('hook: capability with a source -> passes', rc == 0)
rc, _ = run('-222', 'Szia, mikor jó a hívás?')
ok('hook: no claim -> passes', rc == 0)
r = subprocess.run([sys.executable, '-I', GATE], input='not json', capture_output=True, text=True,
                   env=dict(os.environ, CLAUDE_PROJECT_DIR=root), timeout=30)
ok('hook: malformed payload -> allowed', r.returncode == 0)

shutil.rmtree(root, ignore_errors=True)
print(f'---\n{N - FAILS}/{N} passed')
sys.exit(1 if FAILS else 0)
