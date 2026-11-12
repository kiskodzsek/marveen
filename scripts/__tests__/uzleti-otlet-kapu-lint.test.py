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


SITE4 = "\n  - site-szűrt keresés: emag.hu 0; alza.hu 0; notino.hu „nincs találat”; douglas.hu 0."
MERT2 = "- ITTHON: mért (saját GET):\n  - dm: „nem hozott találatot”;\n  - Vatera: 0;\n  - Nem mérhető: eMAG (410)." + SITE4
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

# Klodel 39454 / Radar 39474: the eMAG (410) sold Rhode and Loop; a site-filtered search on all four domains is required.
MERT2_NOSITE = MERT2.replace(SITE4, "")
check("negative, 39454: measured shops but no site probe fails", itthon_err(MERT2_NOSITE), True)
check("negative: a site probe missing douglas.hu fails",
      itthon_err(MERT2.replace("; douglas.hu 0.", ".")), True)
check("negative, Rhode/Loop: a site probe WITH hits fails (the product is sold here)",
      itthon_err(MERT2.replace("emag.hu 0", "emag.hu 3 találat")), True)
check("negative: a domain named without a result fails",
      itthon_err(MERT2.replace("alza.hu 0", "alza.hu megnézve")), True)
check("all four site probes at 0 with two measured shops passes", itthon_err(MERT2), False)
check("Radar's form: one result after a domain list passes",
      itthon_err(MERT2.replace(SITE4, "\n  - site-szűrt keresés (emag.hu, alza.hu, notino.hu, douglas.hu): 0 találat.")), False)
check("negative: in a domain list the hit of the next domain is not borrowed",
      itthon_err(MERT2.replace(SITE4, "\n  - site: emag.hu, alza.hu 0, notino.hu 0, douglas.hu 2 találat.")), True)


def zseni_err(body, mode="--zseni"):
    """The lint's MINDENKI/VICCES errors for one section (Klodel 39499, Patrik TG 18069), or "" if none."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(f"## 1. Ötlet\n{body}\n")
        path = f.name
    try:
        out = subprocess.run([sys.executable, "-I", LINT, path, "--problema", mode], capture_output=True, text=True, timeout=20).stdout
    finally:
        os.unlink(path)
    return "; ".join(x for x in out.split("; ") if x.startswith(("MINDENKI", "VICCES")) or "MINDENKI" in x or "VICCES" in x)


JO_VICCES = '- VICCES: „Végre egy térkép, ami nem azt mondja, hogy forduljon vissza.”'
# the two forced ideas of 2026-11-12 (Szigma A: free-parking map; Magnes A / biznisz-modell 1: dog places)
check("negative, TG 18069: the parking map leaves out who has no car",
      bool(zseni_err("- MINDENKI: akinek nincs autója\n" + JO_VICCES)), True)
check("negative, TG 18069: the dog-place idea leaves out who has no dog",
      bool(zseni_err("- MINDENKI: aki nem kutyás\n" + JO_VICCES)), True)
check("negative: 'senkit' with a narrowing word still fails ('senkit, csak autósoknak')",
      bool(zseni_err("- MINDENKI: senkit, de főleg autósoknak szól\n" + JO_VICCES)), True)
check("negative: 'senkit' naming parents fails", bool(zseni_err("- MINDENKI: senkit (szülőknek)\n" + JO_VICCES)), True)
check("negative: no MINDENKI field fails", bool(zseni_err(JO_VICCES)), True)
check("negative: no VICCES field fails", bool(zseni_err("- MINDENKI: senkit")), True)
check("negative: VICCES without quotes fails", bool(zseni_err("- MINDENKI: senkit\n- VICCES: majd kitaláljuk")), True)
check("negative: VICCES with two sentences fails",
      bool(zseni_err("- MINDENKI: senkit\n- VICCES: „Ez vicces. Ez is az.”")), True)
check("'senkit' + one quoted sentence passes", zseni_err("- MINDENKI: senkit, mindenki sorban áll valahol\n" + JO_VICCES), "")
check("'automata' is not 'autó'", zseni_err("- MINDENKI: senkit, a csomagautomata mindenkié\n" + JO_VICCES), "")
check("without --zseni the fields are not required", zseni_err("- VOLUMEN: 10", mode="--x"), "")


# Klodel 39531 (Patrik TG 18089): in --zseni every idea needs a BIZONYITEK line: a foreign app/site already working, a
# measured number (downloads/users/ratings), an http(s) source and a date; "[search]", "tipp", "NINCS ADAT" fail.
def biz_err(body):
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(f"## 1. Ötlet\n{body}\n")
        path = f.name
    try:
        out = subprocess.run([sys.executable, "-I", LINT, path, "--zseni"], capture_output=True, text=True, timeout=20).stdout
    finally:
        os.unlink(path)
    return "BIZONYITEK" in out


BIZ_OK = "- BIZONYITEK: Wanna (US) 1,2 millió letöltés a Google Playen, https://play.google.com/store/apps/details?id=x, 2026-11-12"
check("BIZONYITEK: name + measured downloads + source + date passes", biz_err(BIZ_OK), False)
check("negative: no BIZONYITEK line fails", biz_err("- MINDENKI: senkit"), True)
check("negative: [search] fails", biz_err(BIZ_OK + " [search]"), True)
check("negative: tipp fails", biz_err(BIZ_OK.replace("1,2 millió", "tipp: sok")), True)
check("negative: NINCS ADAT fails", biz_err("- BIZONYITEK: Wanna, letöltés NINCS ADAT, https://x.com, 2026-11-12"), True)
check("negative: no http(s) source fails", biz_err(BIZ_OK.replace("https://play.google.com/store/apps/details?id=x", "Google Play")), True)
check("negative: no date fails", biz_err(BIZ_OK.replace(", 2026-11-12", "")), True)
check("negative: a number only in the URL and the date is not a measured number",
      biz_err("- BIZONYITEK: Wanna letöltés, https://example.com/app/123, 2026-11-12"), True)
R3 = os.path.join(HERE, "fixtures", "idea-gate-zseni-r3")
for name in ("zseni-otlet-1112-r3-magnes.md", "zseni-otlet-1112-r3-radar.md", "zseni-otlet-1112-r3-szigma.md"):
    out = subprocess.run([sys.executable, "-I", LINT, os.path.join(R3, name), "--zseni"], capture_output=True, text=True,
                         timeout=20).stdout
    lines = [l for l in out.splitlines() if l.startswith(("MEHET", "NEM MEGY"))]
    check(f"negative, TG 18089: {name} fails on BIZONYITEK in every idea",
          bool(lines) and all(l.startswith("NEM MEGY") and "BIZONYITEK" in l for l in lines), True)

if FAILS:
    print(f"\n{len(FAILS)} FAILED: {FAILS}", file=sys.stderr)
    sys.exit(1)
print("\nAll uzleti-otlet-kapu-lint tests passed.")
