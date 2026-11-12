# Zseni-ötletek, 2. kör: amit TÉNYLEG mindenki átél (Szigma)

Szerző: Szigma. Megrendelő: Klodel 39498 (Patrik TG 18069: "egyik sem tetszik sokkal jobb otlet kéne.. a budichecknél még az is jó hogy tényleg MINDEN embert érint és lehet róla viccesen is kommunikalni"). Dátum: 2026-11-12. Mérések: Ads LIVE 14:19, WebSearch 14:15-14:19 (`date`-ből). Jelölések: MÉRT, ÁTVETT, [search] (WebSearch-találat, nem reader-ellenőrzött), TIPP, NINCS ADAT.

## 3 sor Patriknak

1. Két ötlet, az 1. a javaslatom: **Sorbanállás-mérő** (várakozás: posta, orvos, kormányablak, pénztár; "ennyit vártam" jelvényekkel és rangsorral). A 2. gyengébb: **Ár-leleplező** (mennyibe került ma a lángos, kávé, kenyér, ahol nincs hivatalos árfigyelő).
2. A "mindenki" próbán az 1. átmegy (mindenki vár valahol, 16-70 éves, város és falu), a 2. félig (nem mindenki eszik kint, ezért az ételár mellé kenyér, tej kell).
3. A kereslet csak ellenőrzés: a "sorban állás" Ads-keresés alacsony (320/hó, csökkenő), mert a várakozás élmény, nem keresés; ez a Budicheckre is igaz lenne. Az "itthon nincs" állítás keresésen alapul, nem teljes mérésen.

## A kérdés

Patrik új sorrendje: NEM a keresési számból indulunk, hanem abból, amit tényleg mindenki átél (16-70 éves, város és falu, kutya, autó, gyerek nélkül is). Mindegyiknél: (1) "mindenki" próba, (2) egy vicces, megosztható mondat, (3) itthon van-e már, (4) mért kereslet csak ellenőrzésnek, (5) Dave-vel megépíthető-e, (6) miből jön pénz. Döntés, amit támogat: melyik ötlet megy tovább a független rangsoroláshoz és Patrikhoz.

## Módszer és hatókör

- Kiinduló lista (saját gondolkodás, nem mért): várakozás, sorban állás, szomszéd, időjárás, evés, alvás, ügyintézés, boltban fizetés. Kiesett a "mindenki" próbán vagy a jogi kockázaton: szomszéd (személyek értékelése, adatvédelmi és becsületsértési kockázat: Lex), alvás (nincs közösségi tartalom, az alvás-appok kész termékek, nem mértem), "mit főzzek" (9 900 keresés/hó MÉRT, de receptoldal-piac, nincs közösségi térkép-logika; nem néztem utána).
- Ads (MÉRT, havi átlag HU, 12 havi sor, LIVE 14:19): `/Users/klodel/marveen/shared/seo-integraciok/ads-szigma-zseni3-1112.csv` (14 kifejezés, lint rendben).
- Itthoni meglévő: WebSearch standard [search], 14:15-14:19. App-store keresést és `site:` szűrőt nem tudok géppel mérni (korábbi jelzés, 39471 és 39485), ezért a "nincs itthon" nem teljes mérés.
- Külföldi minta: WebSearch [search]; a számok ÁTVETT, harmadik fél oldaláról.

## Eredmények

## 1. Sorbanállás-mérő

Kapu-mezők (`uzleti-otlet-kapu-lint.py --zseni --problema`, Klodel 39507; a mezők alatt a részletek):

- MINDENKI: senkit (aki sosem áll sorban, az nincs; csak a telefon nélküliek maradnak ki, mint a Budicheckben)
- VICCES: "47 perc a postán, előttem 6 ember és 1 ablak: ez már nem sor, hanem életforma."
- MEGCSINALHATO: IGEN (TIPP: Dave erősítse meg, Next.js + Supabase, nincs hardver)
- NEHEZEN-MASOLHATO: IGEN (a kód másolható, a közösség által mért adat nem; TIPP)
- KERESLET-ITTHON: IGEN (gyenge, csak ellenőrzés): "sorban állás" 320/hó, "várakozási idő" 20/hó (Ads LIVE, MÉRT, 2026-11-12 14:19)
- PROBLEMA: kormányablak átlagos várakozása 21 perc, kb. 30 perc a teljes ügyintézéssel (ÁTVETT, [search] 14:15, az eredeti forrás nem azonosított, ezért gyenge)
- TERJESZTES: NINCS ADAT, mért szám nincs; ötlet-szint (TIPP): megosztható rekord-kártya és helyi csoportok
- VOLUMEN: "sorban állás" 320/hó, "várakozási idő" 20/hó (Ads, MÉRT); CPC nincs lekérve
- ITTHON: közösségi várakozás-mérő app a magyar app-store-okban nem jött fel (mért, webread, 2026-11-12 14:22-14:23, nyers futások: `agents/szigma/work/untrusted/webread/20261112-142212-db87cd` és `...142231-2b06ca`):
  - Google Play HU, "sorban állás": 0 releváns találat (álláshirdetés és játék); "sorban állás mérő": 0 releváns (mérőszalag-appok); "várakozás posta orvos": 0 várakozás-mérő (Magyar Posta applikáció és Országos Vérellátó app: hivatalos szolgáltatói appok, funkciójukat nem ellenőriztem).
  - App Store HU, "sorban állás": 2 üzleti sorszám-app (QR Wait Mini, Bart), közösségi mérő 0; "várakozási idő": 0 releváns; "sor hossz": 0 találat (No Results).
  - Google Play HU, "queue wait time": kb. 20 nemzetközi sorkezelő és sor-idő app (pl. WaitLessQ, Qsensor reptéri várakozás, ER Wait Time, Theme Park Wait Times) és egy magyar nevű "Sorszámhívó" (TMTsoftware, hivatali sorszámhívó, nem közösségi mérő).
  - site-próba (emag.hu, alza.hu, notino.hu, douglas.hu): nem mérhető, NINCS ADAT. Ok: a keresőmotor-oldalakat a webread nem éri el (két keresőből az egyik blokkolt, a másik üres oldalt adott), a WebSearch pedig nem alkalmaz site szűrőt. Az ötlet nem bolti termék, ezért a boltok jelenléte nem is releváns.

Működés (TIPP, saját ötlet): a felhasználó egy helyen megnyomja az "Itt vagyok, sorban állok" gombot, majd a "Sorra kerültem" gombot; az app a perceket rögzíti. A hely kap egy várakozási átlagot napszakra és napra, a felhasználó XP-t és jelvényt (pl. "Türelem Nagymestere" 10 óra összvárakozás után). A hely lehet posta, kormányablak, orvosi rendelő, bolti pénztár, MÁV-pénztár, gyógyszertár.

1. "Mindenki" próba (TIPP, saját gondolatmenet): ki marad ki? Aki sosem áll sorban, az nincs: 16 évestől 70 évesig mindenki vár boltban, orvosnál, postán, buszon. Falun is (posta, orvos, bolt). Kimarad, akinek nincs okostelefonja: ez a Budicheck-ra is igaz. Kutya, autó, gyerek nélkül is működik. Átmegy.
2. Megosztható mondat (TIPP): "47 perc a postán, előttem 6 ember és 1 ablak: ez már nem sor, hanem életforma." Jelvény-szöveg: "Türelem Nagymestere: eddig 10 órát vártam, hogy mások is spóroljanak."
3. Itthon van-e már: közösségi várakozás-mérő nem jött fel a keresésben [search, 14:15]. Van hivatalos Kormányablak app, amely várakozási időt becsül és sorszámot ad; a Telex szerint hónapokig hibás nyitvatartást és várakozási időt mutatott, és a minisztérium a kérdésük után javította (2025-10-30) [search]. Postára a keresés semmit nem adott. Google Maps "népszerű időpontok" lehetséges átfedés, ezt nem néztem meg (NINCS ADAT). Külföldi megfelelő, mért (App Store HU, "queue wait time", 14:23): niche sor-idő appok léteznek határátlépésre (Border Radar, Kordon Online: Border Queues), reptérre (Kontrol: Airport Queue Times), vidámparkra (Queue Times, WaitScout); mindennapi helyekre (posta, orvos, bolt) nem jött fel. A letöltés- és felhasználószámot nem mértem (NINCS ADAT). Külföldön: a LineKing egy egyetemi, közösségi várakozás-becslő prototípus (kávézó-sor, 2-3 perc átlagos hiba, nem DMV vagy posta) [search]; működő, nagy közösségi termék nem jött fel (NINCS ADAT). Az iparági sorkezelő programokat (Qminder, NextMe) a hivatalok használják, nem közösségiek.
4. Mért kereslet (ellenőrzésnek, MÉRT Ads, 14:19): "sorban állás" 320/hó (390 -> 210 -> 260, enyhén csökkenő), "várakozási idő" 20/hó, "mennyi a várakozási idő" 10/hó, "mikor érdemes menni a postára" a Google nem adott sort (NINCS ADAT). Következtetés: a keresés gyenge, a várakozás viszont nem keresés-szerű probléma; ez a mérőszám az ötletet nem támasztja alá és nem cáfolja (TIPP).
5. Dave-vel megépíthető-e (TIPP, Dave megerősítése kell; Klodel 39482: Next.js + Supabase, nincs hardver): első működő változat = helylista (kézzel felvitt 200 hely, pl. posták, kormányablakok, rendelők), két gomb (érkezés, sorra kerülés), hely-átlag napszakra, rangsor és 3 jelvény, bejelentkezés nélkül. Kívülről kell: helyadatbázis (OpenStreetMap vagy hivatalos lista, licenc ellenőrizendő), térkép-megjelenítő (ára NINCS ADAT). Helyadat a telefonról személyes adat: minimum az érkezés helye és ideje, felhasználó-azonosító nélkül; Viktor és Lex kérdés.
6. Pénz (TIPP, nem mért): önkormányzatok, hivatalok és szolgáltatók fizethetnek a valós várakozási adatért (a Kormányablak-app hibája mutatja, hogy a hivatalos becslés nem megbízható, [search]); szponzorált "gyors hely" jelzés; nincs hirdetés-alapú terv.

## 2. Ár-leleplező (gyengébb)

- MINDENKI: nem mindenki (aki nem eszik kint, kimarad; ezért nem megy át a kapun, és nem is erőltetem)
- VICCES: "3 200 Ft a lángos: a Balaton-nézet benne van az árban."

Működés (TIPP): a felhasználó beírja, mit fizetett (lángos, kávé, sör, kenyér, tej, fagyi) és hol; a térkép megmutatja a környék árait, a rangsor "legdrágább lángos" és "legolcsóbb kávé".

1. "Mindenki" próba (TIPP): ki marad ki? Aki nem eszik kint, nem iszik kávét: ezért kell kenyér, tej, hogy mindenki vegyen valamit. Félig átmegy: a tartalom egy része nem mindenkit érint.
2. Megosztható mondat (TIPP): "3 200 Ft a lángos: a Balaton-nézet benne van az árban."
3. Itthon van-e már: közösségi árgyűjtő lángosra, kávéra, sörre, fagyira nem jött fel [search, 14:16]. Van hivatalos Árfigyelő (GVH), 78 termékkategória, hat lánc 1 277 üzlete [search, Trade Magazin], tehát a láncboltok ára lefedett, a vendéglátás és kisboltok nem. Külföldön a Numbeo a minta: közösségi ár-adatbázis, "kb. 9,88 M ár, 884 749 hozzájáruló, 12 810 város" az oldalon [ÁTVETT, [search], dátum nincs]; az adatminőséget és a kevés hozzájárulójú városok torzítását a konkurens oldalak kifogásolják [search]. A Numbeo városszintű, helyszín-szintű (lángosos) adat nem.
4. Mért kereslet (MÉRT Ads, 14:19): "mennyibe kerül" 6 600/hó, 12 hónap alatt 1 600 -> 12 100 (7-szeres, általános kérdés, nem csak ár-gyűjtő; Ads-sáv), "árfigyelő" 12 100 -> 9 900, "kávé ára" 390 -> 170 (csökken, HIGH verseny), "lángos ára" 140 (nyári csúcs 260). A "mennyibe kerül" növekedése az ár-tudatosság jele (TIPP, korreláció, nem ok-okozat).
5. Dave-vel megépíthető-e (TIPP, Dave kell): első változat = hely- és tételválasztó, ár-beküldés, térkép, rangsor. Kívülről kell: térkép-megjelenítő (NINCS ADAT az árról), induló adat (kézi). Kockázat: hamis vagy rossz ár (moderálás), versenytörvényi és becsületsértési kérdés egy bolt "leleplezésénél": Lex.
6. Pénz (TIPP, nem mért): helyi vendéglátók "korrekt ár" jelvénye, városi turisztikai partner; a bevétel bizonytalan.

## Javaslat (AJÁNLÁS, nem döntés)

1. Az 1. ötlet menjen a vak rangsorolásra: ez a "mindenki" próbán a legtisztább, a Budicheck-logikát követi (hely, értékelés, jelvény, térkép), a vicc-lehetőség erős, és közösségi várakozás-mérőt itthon és külföldön sem találtam [search].
2. A 2. ötlet csak tartalék: félig mindenkit érint, és a Numbeo-szerű modell már létezik (városszint).
3. Mérési lépés az 1.-hez, ha továbbmegy: Google Maps "népszerű időpontok" és app-store ellenőrzés géppel olvasott eszközzel (Pulzus, Kernel, Dave); Lex és Viktor a helyadatról. Idő- és költségbecslést Dave-től kell kérni, nem becsülök.

FELTETEL-SAJAT: nincs platform-ajánlás

## Nyitott kérdések

- Mennyire fedi le a Google Maps népszerű időpontok a posta, orvos, kormányablak várakozását? (Nem mértem.)
- Elég lesz-e a beküldő az induláshoz (hálózati hatás): nincs mérve, TIPP.
- Közösségi helyadat jogi kezelése (GDPR, hely és idő): Lex, Viktor.

## Patrikra váró döntések

Nincs külön döntés; a független rangsorolás után Patrik a legjobb 1-2 ötletről dönt.

## Források

- Ads: `/Users/klodel/marveen/shared/seo-integraciok/ads-szigma-zseni3-1112.csv` (LIVE, 2026-11-12 14:19).
- Kormányablak és várakozás (WebSearch, 14:15): `https://telex.hu/techtud/2025/10/30/kormanyablak-mobilalkalmazas-app-nem-mukodik-hibak-ugyintezes-miniszterium-javitas-digitalis-allampolgar-dap`; LineKing: `https://cse.buffalo.edu/~demirbas/publications/lineking.pdf`; sorkezelő szoftverek: `https://www.qminder.com/government-queuing-app`.
- Árak (WebSearch, 14:16): `https://trademagazin.hu/en/az-online-arfigyelovel-sokat-sporolhatnak-a-csaladok`, `https://infostart.hu/eletmod/2023/07/31/megneztuk-mennyibe-kerulnek-most-a-langosok-talaltunk-kimondottan-olcsot-is`; Numbeo: `https://www.numbeo.com/` és `https://wraltechwire.com/2019/03/06/need-quality-of-life-info-check-out-crowdsourced-site-numbeo/` (WebSearch, 14:17).
- WebSearch-találatok külső adat, nem reader-ellenőrzöttek; a lekérések időpontja `date`-ből.
