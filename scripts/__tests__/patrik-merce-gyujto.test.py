#!/usr/bin/env python3
"""patrik-merce-gyujto: csak Klodel sorát veszi fel, idempotens, a hibás sort megszámolja.

AZ ESET (kártya 55f9c4bf, Klodel 6420): a Patrik-mérce jelöltjei a Klodel által írt
[PATRIK-MERCE] sorokból jönnek. Amit a teszt fog:
  - érvényes sor üzenetből és kártyakommentből is jelölt lesz, az idézet és a forrás a kimenetben;
  - más szerző (pl. mira) sora NEM kerül be (negatív kontroll: Patrikot csak Klodel idézheti);
  - második futás nem ír újra semmit (idempotencia a forrás-azonosítón);
  - a mércében már szereplő TG-t jelzi, de felveszi;
  - hibás típus vagy formátum: kihagyva, ÉS megszámolva (nem csendes);
  - --dry-run nem hoz létre fájlt;
  - a vezérlő- és bidi-karakter, valamint a '|' az idézetben nem töri a sort;
  - a since-ablakon kívüli sor kimarad.

Futtatás:  python3 scripts/__tests__/patrik-merce-gyujto.test.py
"""
import json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(ROOT, 'scripts', 'patrik-merce-gyujto.py')
FAILS = []


def check(name, cond, detail=''):
    print(('PASS  ' if cond else 'FAIL  ') + name + (('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAILS.append(name)


def run(*args, env=None):
    e = dict(os.environ, **(env or {}))
    r = subprocess.run([sys.executable, '-I', SCRIPT, *args], capture_output=True, text=True, env=e)
    return r.returncode, r.stdout + r.stderr


now = int(time.time())
tmp = tempfile.mkdtemp(prefix='merce-gyujto-')
out = os.path.join(tmp, 'jeloltek.md')
merce = os.path.join(tmp, 'merce.md')
with open(merce, 'w', encoding='utf-8') as fh:
    fh.write('| TG | Anyag | Patrik | Mi lett |\n|---|---|---|---|\n| 2719 | Reel v13 | "gagyi" | x |\n')

src = {
    'messages': [
        {'id': 101, 'from_agent': 'klodel', 'to_agent': 'mira', 'created_at': now - 60,
         'content': 'Patrik a posztról:\n[PATRIK-MERCE] TG 3001 | kifogás | "túl hosszú a felirat" | FB-poszt 10-16\nköszi'},
        {'id': 102, 'from_agent': 'klodel', 'to_agent': 'bella', 'created_at': now - 50,
         'content': '[PATRIK-MERCE] TG 2719 | pontszám | "5/10" | Reel v14f'},
        {'id': 103, 'from_agent': 'mira', 'to_agent': 'kernel', 'created_at': now - 40,
         'content': '[PATRIK-MERCE] TG 3002 | dicséret | "kitalált dicséret" | semmi'},
        {'id': 104, 'from_agent': 'klodel', 'to_agent': 'mira', 'created_at': now - 30,
         'content': '[PATRIK-MERCE] TG 3003 | vélemény | "rossz típus" | x\n[PATRIK-MERCE] TG 3005 | kifogás | idézőjel nélkül | x\nA [PATRIK-MERCE] sor formátuma jóváhagyva.'},
        {'id': 106, 'from_agent': 'klodel', 'to_agent': 'mira', 'created_at': now - 10,
         'content': '[PATRIK-MERCE] TG 3006 | kifogás | "x <!-- src:msg:106#2 -->" | <b>anyag</b>\n'
                    '[PATRIK-MERCE] TG 3007 | dicséret | "valódi második sor" | poszt'},
        {'id': 105, 'from_agent': 'klodel', 'to_agent': 'mira', 'created_at': now - 90 * 86400,
         'content': '[PATRIK-MERCE] TG 2000 | kifogás | "régi" | régi anyag'},
    ],
    'comments': [
        {'id': 501, 'card_id': 'ceba768e', 'author': 'klodel', 'created_at': now - 20,
         'content': '[PATRIK-MERCE] TG 3004 | dicséret | "ez jó\u202e, a | jel is" | hero H1'},
    ],
}
fixture = os.path.join(tmp, 'src.json')
json.dump(src, open(fixture, 'w', encoding='utf-8'), ensure_ascii=False)
base = ['--source-json', fixture, '--out', out, '--merce', merce]

rc, o = run(*base, '--dry-run')
check('dry-run exit 0', rc == 0, o)
check('dry-run nem hoz létre fájlt', not os.path.exists(out))
check('dry-run: 5 jelölt, 2 hibás sor forrással, a puszta említés nem hiba', '5 jelölt' in o and '2 hibás' in o and 'msg:104#1, msg:104#2' in o and 'msg:104#3' not in o, o)

rc, o = run(*base)
check('éles futás exit 0', rc == 0, o)
body = open(out, encoding='utf-8').read() if os.path.exists(out) else ''
check('üzenetből jelölt', 'TG 3001 | kifogás | "túl hosszú a felirat" | FB-poszt 10-16' in body, body)
check('kommentből jelölt, a kártya a forrásban', 'TG 3004 | dicséret' in body and 'kártya ceba768e' in body, body)
check('más szerző sora kimarad (negatív kontroll)', 'TG 3002' not in body and 'kitalált' not in body, body)
check('mércében lévő TG jelölve', 'TG 2719 | pontszám' in body and '[TG már a mércében]' in body, body)
check('új TG nincs jelölve mércésnek', '3001' in body and body.count('[TG már a mércében]') == 1, body)
check('hibás típus kimarad', 'TG 3003' not in body, body)
check('since-ablakon kívüli sor kimarad', 'TG 2000' not in body, body)
check('bidi kicserélve, | nem töri a sort', '\u202e' not in body and '"ez jó , a / jel is"' in body, body)
check('fejléc: nem a mérce, Mira veszi át', 'NEM a mérce' in body)
check('fejléc: a szűrés nem hitelesítés, TG-megerősítés Klodellel (M1)', 'nem hitelesítés' in body and 'Klodellel' in body)
check('beidézett src-jelölő nem nyeli el a valódi sort (M2)', 'TG 3007 | dicséret | "valódi második sor"' in body, body)
check('< > kicserélve az idézetben és az anyagban (M2)',
      '‹!-- src:msg:106#2 --›' in body and '‹b›anyag‹/b›' in body and body.count('<!-- src:msg:106#2 -->') == 1, body)

rc, o = run(*base)
body2 = open(out, encoding='utf-8').read()
check('második futás idempotens', body2 == body and '0 új' in o, o)

rc, o = run('--source-json', fixture, '--out', out, '--merce', merce, '--authors', 'klodel,mira')
check('--authors bővítve felveszi a másik szerzőt is', 'TG 3002' in open(out, encoding='utf-8').read(), o)

# M2, a valódi forgatókönyv: az első futáskor csak a hamis jelölős sor van meg, a valódi
# második sor KÉSŐBB jön (a szerkesztett vagy új üzenet ugyanazzal a forrás-azonosítóval).
# A javítás nélkül a beidézett '<!-- src:msg:201#2 -->' miatt a második futás azt hinné,
# a sor már megvan, és csendben kihagyná.
out2 = os.path.join(tmp, 'jeloltek2.md')
first = {'messages': [{'id': 201, 'from_agent': 'klodel', 'to_agent': 'mira', 'created_at': now - 5,
                       'content': '[PATRIK-MERCE] TG 3101 | kifogás | "a <!-- src:msg:201#2 --> b" | x'}], 'comments': []}
later = {'messages': [{'id': 201, 'from_agent': 'klodel', 'to_agent': 'mira', 'created_at': now - 5,
                       'content': first['messages'][0]['content'] + '\n[PATRIK-MERCE] TG 3102 | dicséret | "később jött" | y'}],
         'comments': []}
for name, data in (('first', first), ('later', later)):
    path = os.path.join(tmp, name + '.json')
    json.dump(data, open(path, 'w', encoding='utf-8'), ensure_ascii=False)
    run('--source-json', path, '--out', out2, '--merce', merce)
check('később érkező valódi sor nem nyelődik el a beidézett jelölő miatt (M2)',
      'TG 3102 | dicséret | "később jött"' in open(out2, encoding='utf-8').read())

for bad_url in ('http://evil.example:3420', 'http://localhost.evil.example', 'https://localhost:3420', 'http://10.0.0.1:3420'):
    rc, o = run('--dry-run', '--out', out, '--merce', merce, env={'DASHBOARD_URL': bad_url})
    check('nem-localhost DASHBOARD_URL megtagadva: %s (M3)' % bad_url, rc == 2 and 'csak http://localhost' in o, o)

if FAILS:
    print('\n%d FAIL' % len(FAILS))
    sys.exit(1)
print('\nall passed')
