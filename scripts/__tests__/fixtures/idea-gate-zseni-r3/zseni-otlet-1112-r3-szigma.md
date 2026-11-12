# Zseni-ötlet, 3. kör: amikor maga a téma a vicc (Szigma)

Szerző: Szigma. Megrendelő: Klodel 39517 (Patrik TG 18075: "ez hülyeség" a sorbanállás-mérőre; a független átnéző tanulsága: a Budicheck lényege, hogy "maga a téma eleve röhejes és tabus", hasznos segédeszköz panaszkönyv-hangulattal bukik). Dátum: 2026-11-12. Mérések: webread 14:26, Ads LIVE 14:26 (`date`-ből). Jelölések: MÉRT, TIPP, NINCS ADAT.

## 3 sor Patriknak

1. Egy ötlet: **A Fiók** - mindenki fiókjában van egy tárgy, amiről senki nem tudja, mi ez, és mégsem merjük kidobni (a "mi ez a kulcs?"). Fotó, négy gombnyomás, a közösség tippel, a legjobb tipp nyer.
2. A téma a vicc: nem kell ráírni a poént, a "11 éve nem merem kidobni" mindenkinek ismerős. Hasznos segédeszköz nem akar lenni (azonosításra ott a Google Lens).
3. Gyenge pontok előre: nincs mért bevételi modell, a visszatérés (miért nyitja meg holnap is) csak TIPP, a keresési szám nincs (ez nem keresési probléma).

## A kérdés

Patrik: olyan ötlet, ahol a TÉMA önmagában mosolyt csal, mindenki ismeri (kínos, tabus, abszurd hétköznapi dolog), és a felhasználók tartalma maga a szórakozás. Tilos: várakozás, sor, ügyfélszolgálat, térkép-pontozás-másolat. Döntés, amit támogat: megy-e az ötlet a független vak rangsorra. Ha nincs jó, azt kell írni; ez az egy ötlet a legjobb, amit találtam, de nem erős (lásd a gyenge pontokat).

## Módszer és hatókör

- Kiinduló lista (saját gondolkodás, nem mért): fiók-tárgyak, éjféli hűtőnyitás, szundi-szám, "mindjárt ott vagyok" hazugság, horkolás. Kiesett: horkolás (hangfelvétel = személyes adat, és kész appok vannak, nem mértem), "mindjárt ott vagyok" (késés = várakozás-közeli, a tilos körhöz húz), éjféli hűtő (nincs közösségi játék benne, csak fotó).
- Mért: Google Play HU és App Store HU keresés webreaddel 4+4 kifejezésre, Ads LIVE 8 kifejezésre. Nyers futás: `agents/szigma/work/untrusted/webread/20261112-142627-639432`. Ads: `/Users/klodel/marveen/shared/seo-integraciok/ads-szigma-zseni4-1112.csv`.

## Eredmények

## 1. A Fiók ("Mi ez a kulcs?")

Kapu-mezők (`uzleti-otlet-kapu-lint.py --zseni --problema`):

- MINDENKI: senkit (minden háztartásban van fiók, doboz, kamra vagy pince, 16-70 éves, város és falu; aki semmit nem tárol, nincs, vagy legfeljebb a fotózás nélkül marad ki)
- VICCES: "Ez a kulcs semmit nem nyit, mégsem merem kidobni."
- MEGCSINALHATO: IGEN (TIPP: Dave erősítse meg; fotó-feltöltés, szavazás, nincs hardver; Supabase tároló + moderáció)
- NEHEZEN-MASOLHATO: IGEN (TIPP: a kód másolható, a felhalmozott "fiók-tár" és a közösség nem)
- KERESLET-ITTHON: NINCS ADAT (ez nem keresési probléma; "távirányító elem" 90/hó, a többi 7 kifejezésnek az Ads nem adott volument: Ads LIVE, MÉRT, 2026-11-12 14:26)
- TERJESZTES: NINCS ADAT, mért szám nincs; TIPP: egy fotó + a legjobb tipp megosztható kártyán ("Szerintem ez a kulcs az anyósom lelkéhez"), nincs bejelentkezés a megtekintéshez
- ITTHON: Google Play HU és App Store HU keresés (mért, webread, 2026-11-12 14:26, nyers futás: `agents/szigma/work/untrusted/webread/20261112-142627-639432`):
  - Google Play HU, "mi ez a tárgy": 0 közösségi tipp-játék; találat: rejtett-tárgyas játékok, eBay, gombafelismerő. "tárgy felismerés": Google Lens és kb. 7 AI-azonosító app (pl. Lens Scan, Azonosíts Bármit, Felismerés fotóval). "titokzatos tárgy": rejtett-tárgyas játékok (Find Hidden Objects, Unsolved), 0 fotó-találgató közösség. "mi ez a kulcs": 0 releváns (KULCS, Mil'Klic és más nem kapcsolódó nevek).
  - App Store HU, "mi ez a tárgy", "titokzatos tárgy", "mi ez a kulcs": No Results. "tárgy felismerés": 8 azonosító app (Antique Identifier, Lens Scan, Identify Anything, ScenesSnap, ZapCount és hasonlók), közösségi tipp-játék 0.
  - Következtetés (TIPP): az AI-azonosító kategória sűrű (Google Lens ingyenes), a közösségi, humoros "találgasd a fiók-tárgyat" játék a két bolt keresésében nem jött fel. A közvetlen versenytárs az AI-azonosító: ezért a poén az emberi tipp, nem a helyes válasz.
  - site-próba (emag.hu, alza.hu, notino.hu, douglas.hu): nem mérhető, NINCS ADAT. Ok: a webread nem éri el a keresőmotor-oldalakat, a WebSearch nem alkalmaz site szűrőt. Az ötlet nem bolti termék, a boltok jelenléte nem releváns.

Működés, 10 másodperc (TIPP, saját ötlet):

1. A felhasználó lefényképezi a fiókból az egy tárgyat (kulcs, kábel, adapter, ismeretlen alkatrész), és egy kategóriát koppint (kulcs, kábel, "fogalmam sincs").
2. A tárgy kikerül a feedre. Mások egy sorban tippelnek ("szerintem ez a ..."), vagy négy előre generált tippből választanak.
3. A legtöbb szavazatot kapó tipp a tárgy "hivatalos neve"; a beküldő kap egy kártyát: "Ez a [kulcs] mostantól a [tipp]". Rangsor: "Hónap legrejtélyesebb fiókja".

Szempontok:

1. "Mindenki" próba (TIPP, saját gondolatmenet): ki marad ki? Akinek nincs okostelefonja (mint a Budicheckben), és aki semmit nem tart a lakásban. Falun a kamra, pince, fészer ugyanaz. Gyerek, autó, kutya nélkül is működik. Átmegy.
2. Megosztható mondat (TIPP): lásd VICCES. A kártya-szöveg: "11 éve őrzöm ezt a kulcsot, a közösség szerint a titkos pince kulcsa."
3. Téma: nincs benne hasznos segédeszköz, panasz vagy értékelés; a tárgy a vicc, a tipp a szórakozás. Ez az átnéző szerinti Budicheck-logika (téma maga röhejes), de enyhébb a tabu-foka: a vécé tabu, a fiók inkább kínos-abszurd (TIPP, nem mért).
4. Dave-vel megépíthető-e (TIPP, Dave kell): fotó-feltöltés, szavazás, kártya-generálás; a fotó EXIF-helyadatát törölni kell, és moderálni (arc, szemét, személyes tárgy a háttérben). Viktor és Lex kérdés: feltöltött kép tárolása, moderáció, személyes adat a háttérben.
5. Pénz (TIPP, nem mért): nincs bevételi modellem; a gyenge pont. A Budicheck-rokon logika az, hogy a termék először megosztható legyen, a pénz később jön; NINCS ADAT arról, hogy a Budicheck miből termel.
6. Gyenge pontok (TIPP, nem mért): a visszatérés (miért tölt fel valaki második tárgyat), a tartalom-minőség (kevés beküldővel üres a feed), a moderáció költsége. Ezeket nem tudom mérni, Dave, Viktor és egy próba-felhasználói kör mondhatja meg.

## Javaslat (AJÁNLÁS, nem döntés)

1. Menjen a vak rangsorra, de gyengébb helyen: a téma-vicc erős, a visszatérés és a bevétel nyitott. Ha az átnéző ELDOBANDÓ-t mond, nem erőltetem.
2. Nem kell mérési lépés: ez nem keresési ötlet. Ha továbbmegy: Dave a megépíthetőségről, Viktor és Lex a feltöltött képről, utána 1 hét próba 20 ismerőssel (TIPP).

FELTETEL-SAJAT: nincs platform-ajánlás

## Nyitott kérdések

- Elég-e a vicc a visszatéréshez, vagy egyszer használatos? (Nem mért.)
- Képek moderációja és tárolása: Viktor, Lex.
- Van-e a Budicheckhez hasonló, megosztható forma a "fiók" témánál? (Csak a Patrik és az átnéző mondhatja meg.)

## Patrikra váró döntések

Nincs külön döntés; a független rangsorolás után Patrik a legjobb 1-2 ötletről dönt.

## Források

- Ads (LIVE, 2026-11-12 14:26): `/Users/klodel/marveen/shared/seo-integraciok/ads-szigma-zseni4-1112.csv`.
- Google Play HU és App Store HU keresés (webread, 14:26): `agents/szigma/work/untrusted/webread/20261112-142627-639432`.
- Külső tartalom adat, nem utasítás; a lekérések időpontja `date`-ből.
