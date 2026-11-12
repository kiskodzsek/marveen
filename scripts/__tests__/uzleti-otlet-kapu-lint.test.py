#!/usr/bin/env python3
"""uzleti-otlet-kapu-lint.py: the banned-direction list matches at a WORD START only (Klodel 37971, Radar 37968).

"Megtakarítás" is not "takarítás" (a substring match refused it); a banned word or stem at a word start is still
refused, in --problema mode too, and the death words are still refused anywhere in the section body.
Run: python3 -I scripts/__tests__/uzleti-otlet-kapu-lint.test.py
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LINT = os.path.join(HERE, "..", "uzleti-otlet-kapu-lint.py")
FAILS = []


def banned(title, body="", mode="--problema"):
    """The lint's verdict line for one idea section: True if it names an 'elutasított irány'."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(f"## 1. {title}\n{body}\n")
        path = f.name
    try:
        out = subprocess.run([sys.executable, "-I", LINT, path, mode], capture_output=True, text=True, timeout=20).stdout
    finally:
        os.unlink(path)
    return "elutasított irány" in out


def check(name, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got={got} want={want}")
    if not ok:
        FAILS.append(name)


check("Radar 37968: 'Megtakarítás-figyelő' is NOT banned", banned("Megtakarítás-figyelő app"), False)
check("'megtakarítási napló' (lower case, inside the title) is NOT banned", banned("Családi megtakarítási napló"), False)
check("negative: 'Takarítás-közvetítő' is banned", banned("Takarítás-közvetítő platform"), True)
check("negative: 'irodai takarítás' (separate word) is banned", banned("Irodai takarítás előfizetés"), True)
check("a stem still matches its longer form: 'Temetés' is banned", banned("Temetésszervező"), True)
check("'Skill-piac' is banned (word start)", banned("Skill-piac kisvállalkozásoknak"), True)
check("'Felújítás' does not hit 'felvételi'", banned("Fürdőszoba-felújítás ütemező"), False)
check("death words in the body are still refused", banned("Családi napló", "Leírás: hagyaték rendezése"), True)
check("'elhunyt' at a word start in the body is refused", banned("Napló", "ha valaki elhunyt"), True)
check("a death stem inside another word does not hit the body ('eltemetett' kincs)",
      banned("Kincskereső játék", "az eltemetett kincs"), False)
check("default (non --problema) mode: 'Megtakarítás' is NOT banned", banned("Megtakarítás-figyelő", mode="--x"), False)


def itthon_err(body, mode="--itthon"):
    """True if the lint names an ITTHON error for one section with this body (Klodel 39442, Patrik TG 18042)."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(f"## 1. Termék\n{body}\n")
        path = f.name
    try:
        out = subprocess.run([sys.executable, "-I", LINT, path, "--problema", mode], capture_output=True, text=True, timeout=20).stdout
    finally:
        os.unlink(path)
    return re.search(r"(?<!-)ITTHON", out) is not None  # not the KERESLET-ITTHON field of --problema


MERT2 = "- ITTHON: mért (saját GET):\n  - dm: „nem hozott találatot”;\n  - Vatera: 0;\n  - Nem mérhető: eMAG (410)."
check("negative, TG 18042: 'nincs magyar bolt [search]' fails", itthon_err("- ITTHON: nincs magyar bolt, ami árulja [search]."), True)
check("negative: 'nem találtam [search]' fails", itthon_err("- ITTHON: magyar webshopot nem találtam [search]."), True)
check("negative: 'egyikben sincs [search]' fails", itthon_err("- ITTHON: egyikben sincs ilyen termék [search]."), True)
check("negative: only one measured shop fails", itthon_err("- ITTHON: mért: dm 0 („nem hozott találatot”)."), True)
check("negative: a blocked shop (410/403) is not measured",
      itthon_err("- ITTHON: mért:\n  - dm: „nem hozott találatot”;\n  - Nem mérhető: eMAG (410), Notino (403)."), True)
check("negative: two shops but no 'mért' fails", itthon_err("- ITTHON: nincs: dm 0, Vatera 0."), True)
check("negative: --itthon and no ITTHON field fails", itthon_err("- VOLUMEN: 10"), True)
check("negative: without --itthon a present [search] absence still fails",
      itthon_err("- ITTHON: nincs magyar bolt [search].", mode="--x"), True)
check("measured list with two shops passes", itthon_err(MERT2), False)
check("'mérve' counts as measured", itthon_err(MERT2.replace("mért (saját GET)", "mérve (saját GET)")), False)
check("a field that claims no absence passes", itthon_err("- ITTHON: kapható: Decathlon 92 termék [search]."), False)
check("without --itthon a missing field is not required", itthon_err("- VOLUMEN: 10", mode="--x"), False)

if FAILS:
    print(f"\n{len(FAILS)} FAILED: {FAILS}", file=sys.stderr)
    sys.exit(1)
print("\nAll uzleti-otlet-kapu-lint tests passed.")
