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
    "arukereso", "olcsóbbat", "játéksziget", "jatekshop", "brendon", "mall", "hervis", "intersport", "libri",
    "google play", "play áruház", "app store"]  # app-ötlet: a magyar app-áruházak keresése (Klodel 39514)
APP_BOLT = {"google play", "play áruház", "app store"}
HIANY = re.compile(r"(?i)(?<!\w)[ns]incs(en)?(?!\w)|nem találtam|nem találtunk|nem hozott találatot|nem árulja|nem árulj"
    r"|(?<![\w.,:])0(?![\w.,:])|egyik(ben)? sem|egyikben sincs")
EREDMENY = re.compile(r"(?i)\d|nem hozott találatot|nem találtunk|nincs találat|„[^”]+”")
NEM_MERT = re.compile(r"(?i)nem mérhető|nem mért|(?<!\d)(403|404|410)(?!\d)|captcha")
BOLTOK += ["meska"]  # kézműves piactér: 3 személyre szabott domborzati térkép volt rajta (Klodel 39617, Szigma 39612)
# Site-próba (Klodel 39454, Radar 39474): a 403/410-es bolt (eMAG) nem mérhető, mégis árulta a Rhode-ot és a Loop-ot.
# Minden hiány-állításhoz kell keresőmotoros site-próba MIND a négy domainre, eredménnyel (a domain után, a következő
# domainig; ha ott nincs, a sor maradékából: "(emag.hu, alza.hu): 0 találat"). Ha bármelyik site-próba találatot ad (szám > 0), a termék itthon kapható: a hiány-állítás bukik.
# The site probe lives in scripts/lib/itthon_rules.py (card 9a4b245c), shared with scripts/lib/hiany_lint.py.
import os  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from itthon_rules import SITE_DOMAINEK, SITE_SOR, site_hibak  # noqa: E402
# --zseni (Klodel 39499, Patrik TG 18069: "tényleg MINDEN embert érint és lehet róla viccesen is kommunikalni ... ezek
# ... erőltetett dolgok"): MINDENKI mező = kit hagy ki. Csak a "senkit" kezdetű érték megy át, és abban sincs autó,
# kutya, gyerek, szülő, sofőr, tulajdonos (szó elején: az "autós", "kutyás" is). VICCES mező = egy mondat idézőjelben.
ZSENI_MOD = "--zseni" in sys.argv
ZSENI_SZUKITO = ["autó", "kutya", "kutyá", "gyerek", "szülő", "szulo", "sofőr", "sofor", "tulajdonos"]
# BIZONYITEK (Klodel 39531, Patrik TG 18089 "ennyire buta ostoba ötleteket nem láttam még soha"): a vak átnéző MEHET-je
# a "Mit álmodtál?"-ra sem volt elég. --zseni-ben ötletenként kötelező egy BIZONYITEK sor: egy külföldön már működő app
# vagy oldal neve + mért szám (letöltés / felhasználó / értékelés) + http(s) forrás + dátum (ÉÉÉÉ-HH-NN). "[search]",
# "tipp" és "NINCS ADAT" a sorban bukik: ami nem mért, az nem bizonyíték.
BIZ_DATUM = re.compile(r"(?<!\d)20\d\d[-.](0[1-9]|1[0-2])[-.](0[1-9]|[12]\d|3[01])(?!\d)")
BIZ_URL = re.compile(r"https?://[^\s)\]>,;]+")
BIZ_MERO = re.compile(r"(?i)letölt|felhasznál|értékel|download|install|user|rating|review|csillag|MAU|DAU|előfizető|subscriber")
def bizonyitek_hibak(p):
    b = re.search(r"(?m)^\s*[-*]?\s*BIZONYITEK:(.*)$", p)
    if not b: return ["BIZONYITEK hiányzik (Klodel 39531, TG 18089: külföldön működő app/oldal + mért szám + forrás + dátum)"]
    v = b.group(1)
    if re.search(r"(?i)\[search\]|(?<!\w)tipp|nincs adat", v): return ["BIZONYITEK: [search] / tipp / NINCS ADAT nem bizonyíték"]
    hibak = []
    if not BIZ_URL.search(v): hibak.append("BIZONYITEK: nincs http(s) forrás")
    if not BIZ_DATUM.search(v): hibak.append("BIZONYITEK: nincs dátum (ÉÉÉÉ-HH-NN)")
    marad = BIZ_DATUM.sub(" ", BIZ_URL.sub(" ", v))
    if not (re.search(r"\d", marad) and BIZ_MERO.search(marad)):
        hibak.append("BIZONYITEK: nincs mért szám (letöltés/felhasználó/értékelés)")
    if len(re.findall(r"[^\W\d_]{3,}", BIZ_MERO.sub(" ", marad))) < 1:
        hibak.append("BIZONYITEK: nincs megnevezett app/oldal")
    return hibak
def zseni_hibak(p):
    hibak = []
    mi = re.search(r"(?m)^\s*[-*]?\s*MINDENKI:(.*)$", p)
    if not mi: hibak.append("MINDENKI hiányzik (TG 18069: kit hagy ki)")
    else:
        v = mi.group(1).strip().lower()
        szuk = [k for k in ZSENI_SZUKITO if szokezdet(k, v)]
        if not v.startswith("senkit"): hibak.append(f"MINDENKI: nem 'senkit' ({mi.group(1).strip()[:60]})")
        elif szuk: hibak.append(f"MINDENKI: szűkítő szó ({szuk[0]})")
    vi = re.search(r"(?m)^\s*[-*]?\s*VICCES:(.*)$", p)
    if not vi: hibak.append("VICCES hiányzik (TG 18069: egy vicces mondat)")
    else:
        q = re.search(r"[„\"“]([^”\"“]{8,})[”\"“]", vi.group(1))
        if not q: hibak.append("VICCES: nincs idézőjeles mondat")
        elif len(re.findall(r"[.!?…]+(?=\s+\S)", q.group(1).strip())) > 0: hibak.append("VICCES: egy mondat legyen, nem több")
    return hibak
# Klodel 39550 (Radar 39544): (1) a site-próba sora hiány-bizonyíték, nem bolt-keresés: a benne lévő domainek (emag.hu,
# alza.hu, ...) NEM számítanak mért boltnak (különben egy valódi bolt-keresés + a site-sor már "2 mért bolt").
# (2) Az app-áruház azonosítós 404-e ("App Store HU: ... (id640360962) ... 404", "Google Play HU: id=com.x.y ... 404")
# mért eredmény: az app itthon nem tölthető le. A 403/410/captcha/"nem mérhető" továbbra sem mért; a sor ilyenkor csak
# az app-áruházat adja, más boltot nem.
APP_ID = re.compile(r"(?i)(?<!\w)id\d{6,}(?!\w)|(?<!\w)id=[a-z]\w*(\.\w+)+")
NEM_MERT_404_NELKUL = re.compile(r"(?i)nem mérhető|nem mért|(?<!\d)(403|410)(?!\d)|captcha")
def app_404_mert(s):
    low = s.lower()
    return (re.search(r"(?<!\d)404(?!\d)", s) is not None and APP_ID.search(s) is not None
            and any(a in low for a in APP_BOLT) and not NEM_MERT_404_NELKUL.search(s))
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
        if SITE_SOR.search(s) or not EREDMENY.search(s): continue
        app404 = app_404_mert(s)
        if NEM_MERT.search(s) and not app404: continue
        for bo in (APP_BOLT if app404 else BOLTOK):
            if re.search(r"(?<!\w)" + re.escape(bo) + r"(?!\w)", s.lower()):
                boltok.add({"mueller": "müller", "edigital": "extreme digital", "jofogas": "jófogás", "argep": "árgép", "arukereso": "árukereső"}.get(bo, bo))
    if "[search]" in b.lower() and not mert:
        return ["ITTHON: hiány-állítás csak [search] forrással (mért bolt-lista kell)"]
    # app-ötlet (a szakasz appról szól, és a mért boltok között app-áruház van): a 4 domaines site-próba nem kötelező
    # (az "App Store" nevében lévő "App" nem számít: a bolt neve nélkül keressük)
    p_bolt_nelkul = re.sub(r"(?i)app store|google play|play áruház", " ", p)
    app = bool(boltok & APP_BOLT) and re.search(r"(?i)(?<!\w)(app|appok|alkalmazás|applikáció|pwa)(?!\w)", p_bolt_nelkul) is not None
    hibak = [] if app else site_hibak(b)
    if not mert or len(boltok) < 2:
        hibak.insert(0, f"ITTHON: hiány-állítás mért bolt-lista nélkül (mért={'igen' if mert else 'nem'}, mért bolt {len(boltok)}, legalább 2 kell)")
    return hibak
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
            if PROBLEMA_MOD or ZSENI_MOD: continue  # TG 4855 / Klodel 39514: a régi mezők itt csak tájékoztatók
            mm = re.search(rf"(?m)^\s*[-*]?\s*{re.escape(m)}:\s*(\S+)", p)
            if not mm: hibak.append(f"{m} hiányzik")
            elif not mm.group(1).upper().startswith("IGEN"): hibak.append(f"{m}={mm.group(1)}")
        if "NINCS ADAT" in p.split("KIEMELKEDES:")[-1].splitlines()[0] if "KIEMELKEDES:" in p else False:
            hibak.append("KIEMELKEDES: NINCS ADAT")
        pz = re.search(r"(?m)^\s*[-*]?\s*PENZ:(.*)$", p)
        if pz and not (PROBLEMA_MOD or ZSENI_MOD) and ("NINCS ADAT" in pz.group(1).upper() or not re.search(r"\d", pz.group(1))):
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
        if ZSENI_MOD: hibak += zseni_hibak(p) + bizonyitek_hibak(p)
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
