#!/usr/bin/env python3
"""Üzleti ötlet kapu lint (Klodel, 2026-11-10, Patrik TG 4607/4617/4634).
Minden '## N.' kezdetű ötlet-szakaszban minden mezőnek 'MEZO: IGEN'-nel kell kezdődnie,
és az ötlet címe nem lehet a már elutasított irányok között. Kilépés: 0 = mehet, 1 = nem."""
import re, sys
MEZOK = ["UJ", "AI-SKALA", "NEM-SOFTWARE-KLON", "NEM-FIZIKAI", "HOGYAN", "NINCS-ELOFELTETEL",
         "BIZALOM", "KIEMELKEDES", "KONKRET", "NEM-NAGYVALLALAT", "ERTHETO", "BEVALT", "VIRALIS",
         "ARC-NELKUL", "CHATGPT-VEL-NEM", "KULFOLD", "PENZ"]  # PENZ: Patrik TG 4830 (fő mérce)
ELUTASITOTT = ["ágenscsapat", "ügynökség", "tanácsadás", "képzés", "kurzus", "átvilágítás", "skill",
    "kapucsomag", "fix áras fejlesztés", "legacy", "modernizál", "lokalizáció külföldi szoftver",
    "versenytárs-jelentés", "cfo", "pénzügyi levél", "nis2", "köszönőkönyv", "weboldal-ellenőrzés",
    "átadódokumentáció", "runbook", "recepciós", "telefonos asszisztens", "használtautó", "társasház",
    "takarítás", "airbnb", "érettségi", "pályázat", "felvételi", "nyelvvizsga", "olvasásgyakorló",
    "marabel", "fotókönyv", "arcnélküli", "faceless", "adat-api", "katalógus",
    "köszöntő-videó", "köszöntővideó", "üzenőfal", "tippjáték",  # 5. kör, TG 4844
    "halál", "elhunyt", "temet", "gyász", "hagyaték", "végrendelet",  # TG 4859 "hagyjál már a halállal"
    "titkár",  # Klodel 38081: az AI-titkárság a recepciós irány másik neve (TG 17453/17460)
    "repülőjárat-kártérítés", "járat-kártérítés", "lejárat-őr", "robotpilóta", "bébiszitter", "előfizetés-őr",
    "számlaőr", "kalkulátor-portál", "trend-oldal", "fordítás", "szalon",  # Patrik 11-11 TG 17467/17473/17479/17480 (Klodel 38081)
    "társasjáték", "kártyajáték",
    "egyedi dal", "ai dal", "dalrendelés", "dal rendelés", "dal ajándék"]  # Patrik TG 18004 (11-12): "ez egy undorito termék átverése az embereknek.."  # Patrik TG 17490 "utalom a tarsasjatekokat nem érdekel" (Klodel 38096)
# --problema mód (Patrik TG 4847: "valos nagy kozonseget erinto problema"): a magyar-specifikus
# probléma nem lehet külföldön bevált/virális, ezért ezek nem kötelezők; helyettük PROBLEMA kell számmal.
PROBLEMA_OPCIONALIS = ["BEVALT", "VIRALIS", "KULFOLD", "PENZ"]
# Patrik csoport TG 4855 (11-11): "ezek a random tippek nem érdekelnek, ne ez alapján dőljön el h vmi kiesik";
# szűrő CSAK: MEGCSINALHATO, NEHEZEN-MASOLHATO, KERESLET-ITTHON (mért, forrással). PENZ csak tájékoztató.
PROBLEMA_KOTELEZO = ["MEGCSINALHATO", "NEHEZEN-MASOLHATO", "KERESLET-ITTHON"]
# Patrik csoport TG 5014/5016 (11-11): "nem tudunk semmit csinálni influenszerkedés nélkül" / "bármelyikkel is mennénk
# elérés nélkül kuka". Minden jelölthöz TERJESZTES: honnan jön a vevő arc és hirdetési pénz nélkül, csatorna + mért szám.
PROBLEMA_MOD = "--problema" in sys.argv
# Klodel 37971 (Radar 37968): a "megtakarítás" cím nem "takarítás". Az elutasított irány csak SZÓ ELEJÉN illeszkedik
# (mint a #179 "irány"), a tő a hosszabb alakot továbbra is fogja ("temet" -> "temetés", "takarítás" -> "takarításközvetítő").
# Ára: az összetett szó belseje nem illeszkedik ("ablaktakarítás"), ezért ott a tiltott irányt külön szóként kell felvenni.
def szokezdet(k, t):
    return re.search(r"(?<!\w)" + re.escape(k), t) is not None
# ITTHON (Klodel 39442, Patrik TG 18042 "Mindegyik van itthon is abbol amiket adtal"; Radar 39450 itthon_check.py):
# "kapható külföldön, itthon hiányzik" jelöltnél a hiány-állítás ("nincs", "nem találtam", "0", "nem árulja") CSAK mért
# bolt-listával megy át: a "mért"/"mérve" szó a mezőben ÉS legalább 2 magyar bolt, mindegyik mellett eredmény ugyanabban
# a sorban. A 403/404/410/captcha/"nem mérhető" bolt nem számít mértnek; [search] forrású hiány-állítás bukik.
# --itthon: az ITTHON mező kötelező. Mód nélkül is ellenőrizzük, ha a mező ott van (kapcsoló-felejtés nem kerülő út).
ITTHON_MOD = "--itthon" in sys.argv
BOLTOK = ["emag", "alza", "decathlon", "pepita", "extreme digital", "edigital", "müller", "mueller", "dm", "rossmann",
    "szimpla", "vatera", "gymbeam", "kifli", "notino", "douglas", "jófogás", "jofogas", "árgép", "argep", "árukereső",
    "arukereso", "olcsóbbat", "játéksziget", "jatekshop", "brendon", "mall", "hervis", "intersport", "libri"]
HIANY = re.compile(r"(?i)(?<!\w)[ns]incs(en)?(?!\w)|nem találtam|nem találtunk|nem hozott találatot|nem árulja|nem árulj"
    r"|(?<![\w.,:])0(?![\w.,:])|egyik(ben)? sem|egyikben sincs")
EREDMENY = re.compile(r"(?i)\d|nem hozott találatot|nem találtunk|nincs találat|„[^”]+”")
NEM_MERT = re.compile(r"(?i)nem mérhető|nem mért|(?<!\d)(403|404|410)(?!\d)|captcha")
def itthon_blokk(p):
    sorok = p.splitlines()
    for i, s in enumerate(sorok):
        if re.match(r"^\s*[-*]?\s*ITTHON:", s):
            blokk = [s]
            for k in sorok[i + 1:]:
                if k.startswith("  ") and k.strip(): blokk.append(k)
                else: break
            return "\n".join(blokk)
    return None
def itthon_hibak(p, kotelezo):
    b = itthon_blokk(p)
    if b is None:
        return ["ITTHON hiányzik (Klodel 39442: itthoni hiány mérve)"] if kotelezo else []
    if not HIANY.search(b): return []
    mert = re.search(r"(?i)(?<!\w)mér(t|ve)(?!\w)", b) is not None
    boltok = set()
    for s in b.splitlines():
        if NEM_MERT.search(s) or not EREDMENY.search(s): continue
        for bo in BOLTOK:
            if re.search(r"(?<!\w)" + re.escape(bo) + r"(?!\w)", s.lower()):
                boltok.add({"mueller": "müller", "edigital": "extreme digital", "jofogas": "jófogás", "argep": "árgép", "arukereso": "árukereső"}.get(bo, bo))
    if "[search]" in b.lower() and not mert:
        return ["ITTHON: hiány-állítás csak [search] forrással (mért bolt-lista kell)"]
    if not mert or len(boltok) < 2:
        return [f"ITTHON: hiány-állítás mért bolt-lista nélkül (mért={'igen' if mert else 'nem'}, mért bolt {len(boltok)}, legalább 2 kell)"]
    return []
def main(path):
    t = open(path, encoding="utf-8").read()
    parts = re.split(r"(?m)^## (?=\d+\.)", t)[1:]
    if not parts:
        print("HIBA: nincs '## N.' ötlet-szakasz"); return 1
    bad = 0
    for p in parts:
        cim = p.splitlines()[0].strip()
        hibak = []
        for m in MEZOK:
            if PROBLEMA_MOD: continue  # TG 4855: a régi mezők itt csak tájékoztatók, őszintén kitöltve
            mm = re.search(rf"(?m)^\s*[-*]?\s*{re.escape(m)}:\s*(\S+)", p)
            if not mm: hibak.append(f"{m} hiányzik")
            elif not mm.group(1).upper().startswith("IGEN"): hibak.append(f"{m}={mm.group(1)}")
        if "NINCS ADAT" in p.split("KIEMELKEDES:")[-1].splitlines()[0] if "KIEMELKEDES:" in p else False:
            hibak.append("KIEMELKEDES: NINCS ADAT")
        pz = re.search(r"(?m)^\s*[-*]?\s*PENZ:(.*)$", p)
        if pz and not PROBLEMA_MOD and ("NINCS ADAT" in pz.group(1).upper() or not re.search(r"\d", pz.group(1))):
            hibak.append("PENZ: mért bevétel szám nélkül")
        if PROBLEMA_MOD:
            for m in PROBLEMA_KOTELEZO:
                mm = re.search(rf"(?m)^\s*[-*]?\s*{re.escape(m)}:\s*(\S+)", p)
                if not mm: hibak.append(f"{m} hiányzik")
                elif not mm.group(1).upper().startswith("IGEN"): hibak.append(f"{m}={mm.group(1)}")
            kd = re.search(r"(?m)^\s*[-*]?\s*KERESLET-ITTHON:(.*)$", p)
            if kd and (not re.search(r"\d", kd.group(1)) or "tipp" in kd.group(1).lower()):
                hibak.append("KERESLET-ITTHON: mért szám nélkül vagy tippel")
            pr = re.search(r"(?m)^\s*[-*]?\s*PROBLEMA:(.*)$", p)
            if not pr: hibak.append("PROBLEMA hiányzik")
            elif "NINCS ADAT" in pr.group(1).upper() or not re.search(r"\d", pr.group(1)) or not re.search(r"(?i)forr|http|ksh|\(", pr.group(1)):
                hibak.append("PROBLEMA: mért méret (szám) és forrás nélkül")
        te = re.search(r"(?m)^\s*[-*]?\s*TERJESZTES:(.*)$", p)
        if not te: hibak.append("TERJESZTES hiányzik (TG 5016: elérés nélkül kuka)")
        elif not re.search(r"\d", te.group(1)) or re.search(r"(?i)hirdet|influenc|influensz", te.group(1)):
            hibak.append("TERJESZTES: mért szám nélkül, vagy hirdetésre/influenszerre épül")
        # Patrik TG 5094 (11-11): "tehát azt se tudod hányan keresnek adott kulcsszóra.. ne csak bullshiteljMű".
        # Keresés-alapú jelöltnél VOLUMEN sor kötelező: havi szám (+CPC) forrással, vagy kimondott "NINCS ADAT".
        if re.search(r"(?i)google|keresés|kereses|keresési|autocomplete|suggest|trends", p):
            vo = re.search(r"(?m)^\s*[-*]?\s*VOLUMEN:(.*)$", p)
            if not vo: hibak.append("VOLUMEN hiányzik (keresés-alapú jelölt, TG 5094)")
            elif not (re.search(r"\d", vo.group(1)) or "NINCS ADAT" in vo.group(1).upper()):
                hibak.append("VOLUMEN: se havi szám, se 'NINCS ADAT'")
        hibak += itthon_hibak(p, ITTHON_MOD)
        for k in ELUTASITOTT:
            if szokezdet(k, cim.lower()) or (k in ("halál","elhunyt","temet","gyász","hagyaték","végrendelet") and szokezdet(k, p.lower())): hibak.append(f"elutasított irány: {k}")
        if hibak:
            bad += 1; print(f"NEM MEGY  {cim}: " + "; ".join(hibak))
        else:
            print(f"MEHET     {cim}")
    print(f"\n{len(parts)-bad}/{len(parts)} mehet")
    return 1 if bad else 0
if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(main(args[0]))
