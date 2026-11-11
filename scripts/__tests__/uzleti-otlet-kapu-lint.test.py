#!/usr/bin/env python3
"""uzleti-otlet-kapu-lint.py: the banned-direction list matches at a WORD START only (Klodel 37971, Radar 37968).

"Megtakarítás" is not "takarítás" (a substring match refused it); a banned word or stem at a word start is still
refused, in --problema mode too, and the death words are still refused anywhere in the section body.
Run: python3 -I scripts/__tests__/uzleti-otlet-kapu-lint.test.py
"""
import os
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

if FAILS:
    print(f"\n{len(FAILS)} FAILED: {FAILS}", file=sys.stderr)
    sys.exit(1)
print("\nAll uzleti-otlet-kapu-lint tests passed.")
