#!/usr/bin/env python3
"""scripts/lib/hiany_lint.py: the absence-claim lint for delivered research files (retro R10, card 1f943050).

Radar's original cases (agents/radar/.claude/skills/magyar-problema-meres/scripts/hiany_lint.py --selftest, 41254),
plus: the patterns are the reply gate's and the shared idea lint's own objects (no copy to drift), an ITTHON-MERT
target outside the install is refused, and the CLI exit codes.
Run: python3 -I scripts/__tests__/hiany-lint.test.py
"""
import importlib.util
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LINT = os.path.join(HERE, '..', 'lib', 'hiany_lint.py')
FAILS = []


def check(label, got, want):
    ok = got == want
    print(('PASS  ' if ok else 'FAIL  ') + label + ('' if ok else f'  -- got {got!r}, want {want!r}'))
    if not ok:
        FAILS.append(label)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ROOT = tempfile.mkdtemp(prefix='hiany-')
os.makedirs(os.path.join(ROOT, 'shared'))
os.environ['MARVEEN_HIANY_ROOT'] = ROOT
lint = load('hiany_lint', LINT)


def verdict(text, name='t.md'):
    path = os.path.join(ROOT, 'shared', name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return 1 if lint.lint(path) else 0


GOOD = ("- ITTHON: mért (2026-11-13):\n  - Meska: 0 („fa térkép”);\n  - Pepita: 0;\n"
        "  - eMAG: NINCS ADAT, 410 botvédelem;\n"
        "  - site-szűrt keresés (emag.hu, alza.hu, notino.hu, douglas.hu): 0 találat.\n")
CASES = [
    ("TG 5550: absence without ITTHON-MERT", "Ilyen termék itthon nincs, a magyar boltokban nem találtam.\n", 1),
    ("absence + ITTHON-MERT: ez a fájl, full block", "Itthon nincs ilyen.\nITTHON-MERT: ez a fájl\n" + GOOD, 0),
    ("absence + block without Meska (TG 5579)", "Itthon nincs ilyen.\nITTHON-MERT: ez a fájl\n- ITTHON: mért:\n"
     "  - Pepita: 0;\n  - eMAG: 0;\n  - site-szűrt keresés (emag.hu, alza.hu, notino.hu, douglas.hu): 0 találat.\n", 1),
    ("absence + block without the site probe", "Itthon nincs ilyen.\nITTHON-MERT: ez a fájl\n- ITTHON: mért:\n"
     "  - Meska: 0;\n  - Pepita: 0;\n  - eMAG: 0;\n", 1),
    ("absence + site probe with a hit (itthon kapható)", "Itthon nincs ilyen.\nITTHON-MERT: ez a fájl\n"
     + GOOD + "  - site:alza.hu „fa térkép”: 7 találat.\n", 1),
    ("absence + ITTHON-MERT: ez a fájl, but no ITTHON block", "Itthon nincs ilyen.\nITTHON-MERT: ez a fájl\n", 1),
    ("absence + ITTHON-MERT to a missing file", "Hazai bolt nem árulja.\nITTHON-MERT: shared/nincs-ilyen.md\n", 1),
    ("no absence claim", "A Pepitán 76 találat van, itthon is kapható.\n", 0),
    ("absence only in a code block (example)", "```\nitthon nincs ilyen\n```\n", 0),
    ("bare NINCS ADAT (L232)", "Nyitott felhívás: NINCS ADAT\n", 1),
    ("NINCS ADAT with an inline log", "- eMAG: NINCS ADAT, 410 botvédelem (emag.hu, 11-13)\n", 0),
    ("NINCS ADAT with a log reference", "| 3 | gyermekülés | NINCS ADAT | N2 |\n\n## Források (lekérve 2026-11-13)\n"
     "- **N2:** adtargeting.io /child-safety-seat: HTTP 404.\n", 0),
    ("NINCS ADAT with a missing reference", "| 3 | gyermekülés | NINCS ADAT | N7 |\n\n## Források (2026-11-13)\n"
     "- **N2:** adtargeting.io: HTTP 404.\n", 1),
    ("NINCS ADAT with a range reference (N1-N3)", "| 6 | pelenka | NINCS ADAT | N1-N3: nincs |\n\n"
     "## Források (2026-11-13)\n- **N1:** README: a táblában nincs.\n- **N2:** adtargeting.io: HTTP 404.\n", 0),
    ("NINCS ADAT because nobody searched", "Gyártási költség: NINCS ADAT (árajánlatot nem kértünk).\n", 1),
    ("NINCS ADAT, log entry without a result", "Ár: NINCS ADAT (K1)\n\n## Keresés-napló\n- K1: árgép.hu, 2026-11-13\n", 1),
    ("Radar 41442: a copied brief line is not a claim", "Kész, ha: minden szám forrással vagy NINCS ADAT indokkal.\n", 0),
    ("Radar 41442: a legend line is not a claim", "- **Jelölések:** `[file]` = a lap szövege, NINCS ADAT = nem találtuk.\n", 0),
    ("Radar 41442: a backticked NINCS ADAT in a table cell is still a claim", "| 3 | ár | `NINCS ADAT` |\n", 1),
    ("Radar 41442: \"Kész, ha\" mid-line does not exempt", "A brief szerint Kész, ha: ár vagy NINCS ADAT.\n", 1),
    ("NINCS ADAT, log entry without a date", "Ár: NINCS ADAT (K1)\n\n## Keresés-napló\n"
     "- K1: arukereso.hu „babakocsi”: 403\n", 1),
]
for label, text, want in CASES:
    check(label, verdict(text), want)

# ITTHON-MERT pointing outside the install is not read (the target's text would be judged and quoted).
outside = tempfile.NamedTemporaryFile('w', suffix='.md', delete=False, encoding='utf-8')
outside.write(GOOD)
outside.close()
check("ITTHON-MERT to an absolute path outside the install: refused",
      verdict(f"Itthon nincs ilyen.\nITTHON-MERT: {outside.name}\n"), 1)
os.makedirs(os.path.join(ROOT, 'shared', 'k'), exist_ok=True)
with open(os.path.join(ROOT, 'shared', 'k', 'mert.md'), 'w', encoding='utf-8') as f:
    f.write(GOOD)
check("ITTHON-MERT to another file of the install: clean", verdict("Itthon nincs ilyen.\nITTHON-MERT: shared/k/mert.md\n"), 0)

# No copied patterns: the lint uses the reply gate's and the idea lint's objects.
repo = os.path.realpath(os.path.join(HERE, '..', '..'))
gate = load('pig', os.path.join(repo, 'scripts', 'hooks', 'product-image-gate.py'))
idea = load('uok', os.path.join(repo, 'scripts', 'uzleti-otlet-kapu-lint.py'))
check("ITTHON_CLAIM is the reply gate's list", [r.pattern for r in lint.ITTHON_CLAIM], [r.pattern for r in gate.ITTHON_CLAIM])
check("the shop check is the reply gate's function", lint.itthon_shop_gaps.__code__.co_code, gate.itthon_shop_gaps.__code__.co_code)
check("the site probe is the idea lint's function", lint.site_hibak.__code__.co_code, idea.site_hibak.__code__.co_code)

# CLI exit codes
clean = os.path.join(ROOT, 'shared', 'clean.md')
with open(clean, 'w', encoding='utf-8') as f:
    f.write("Semmi hiány.\n")
dirty = os.path.join(ROOT, 'shared', 'dirty.md')
with open(dirty, 'w', encoding='utf-8') as f:
    f.write("Nyitott felhívás: NINCS ADAT\n")
env = dict(os.environ, MARVEEN_HIANY_ROOT=ROOT)
rc = lambda *a: subprocess.run([sys.executable, '-I', LINT, *a], capture_output=True, text=True, env=env, timeout=30).returncode
check("CLI: clean file exit 0", rc(clean), 0)
check("CLI: finding exit 1", rc(dirty), 1)
check("CLI: missing file exit 2", rc(os.path.join(ROOT, 'nope.md')), 2)
check("CLI: no argument exit 2", rc(), 2)

os.unlink(outside.name)
subprocess.run(['rm', '-r', '--', ROOT], check=False)
if FAILS:
    print(f"\n{len(FAILS)} FAILED: {FAILS}", file=sys.stderr)
    sys.exit(1)
print("\nAll hiany-lint tests passed.")
