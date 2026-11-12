# Zseni-ötlet r2: amit TÉNYLEG MINDENKI átél (Mágnes, 2026-11-12)

Kérés (Patrik privát TG 18069, szó szerint): „egyik sem tetszik sokkal jobb otlet kéne.. a budichecknél még az is jó hogy tényleg MINDEN embert érint és lehet róla viccesen is kommunikalni stb.. ezek amiket aadtál erőltetett dolgok". Klodel 39497: NEM a keresési számból indulunk; 16 évestől 70 évesig, város és falu, kutya/autó/gyerek nélkül is; mindegyiknél (1) „mindenki" próba, (2) egy vicces mondat, (3) van-e itthon, (4) kereslet csak ellenőrzésnek, (5) Dave-vel megépíthető, (6) miből jön pénz. Legfeljebb 3 ötlet. Elvetve (nem érintem): parkoló, csomagautomata, kutyás, poloska, hulladékudvar.

Jelölés: **mért** = saját lekérés, **[search]** = keresési kivonat (nem bizonyíték), **[tipp]**, **NINCS ADAT**. A vicces mondatok és a „megosztanák" ítélet **[tipp]**: ízlés, nem mérhető.

## 3 sor Patriknak
1. **Első helyen a Sorbanálló** - mindenki sorban áll valahol (bolt, posta, rendelő, hivatal), és mindenkinek ugyanaz a sztorija: „mindig a másik sor halad gyorsabban". Közösségi, egy érintéses sorhossz-jelentés, heti „Magyarország legtürelmesebb boltja/postája" lista.
2. **Itthon részben van:** a Google Térkép népszerű időpont/várakozási idő adatot mutat, a Kormányablak app a kormányablakokét; közösségi, játékos, pénztársor-szintű magyar app a keresésben nem jött fel **[search]**.
3. **Gyenge pont, őszintén:** hidegindítás (kevés jelentésnél üres a térkép) és a pénz [tipp]; ez ugyanaz a gond, mint a Budicheck-nél, amiből nincs közölt felhasználószám vagy bevétel (We Love Budapest cikk, 2026-11-04, korábbi körben nézve).

## Rangsor és javaslat

| Ötlet | Mindenki | Megosztható mondat | Itthon | Megépíthető [tipp] | Pénz [tipp] |
|---|---|---|---|---|---|
| 1 Sorbanálló | igen | erős [tipp] | részben van (Google, Kormányablak) | kis-közepes | van B2B irány |
| 2 Szomszéd-bingó | igen (nagyon kevés kivétel) | jó [tipp] | rokon van (Miutcánk) | nagyon kis | nincs |
| 3 Kabát-index | igen | közepes [tipp] | rokon van (Időkép) | nagyon kis | nincs |

**Javaslatom: az 1, egyedül.** A 2 és a 3 olcsó, de pénz nincs bennük; az 1-ben van B2B irány, és a „másik sor mindig gyorsabb" érzést mindenki ismeri. A legnagyobb kérdés ugyanaz, mint a Budicheck-nél: induláskor kevés a jelentés, ezért az első verzió sztori és heti lista, nem élő térkép.

## 1. Sorbanálló (legerősebb)

Mi ez: egy érintés: „Mekkora a sor?" (0 / 1-3 / 4-8 / 9+ ember), hely: bolt, posta, rendelő, gyógyszertár, hivatal, pékség. Az utolsó 30 perc átlaga látszik. Hetente lista: legtürelmesebb hely, legrosszabb csütörtök 17:00.

- MINDENKI: senkit. Aki soha nem megy sehová (csak online vásárol és intéz mindent), gyakorlatilag nincs; falun is van bolt és posta, kis helyen kevesebb jelentés lesz (ez gyakorlati, nem "mindenki" kérdés).
- VICCES: „Mindig a másik sor halad gyorsabban, most végre számokkal" [tipp]. Alternatíva: „12 perc, 1 pénztár, 0 remény: ez a sor trónhoz méltó".
- Itthon (forrás: keresési kivonat és Google súgó, nem mért bolt-lista):
  - Google Térkép: népszerű időpont, élő forgalmasság és üzletre becsült várakozási idő, névtelenített, összesített idővonal-adatból, csak elég látogatónál, a tulajdonos nem módosíthatja (https://support.google.com/maps/answer/11323117?hl=hu, https://support.google.com/business/answer/6263531?hl=hu; [search]). Ez NEM pénztársor-jelentés és nem közösségi/játékos.
  - Kormányablak app: a kormányablakok becsült várakozási ideje (App Store hu listing, [search]); a Telex 2025-10-30 cikke szerint hónapokig hibásan működött.
  - Pénztársor-szintű közösségi magyar app a bolti kereséssel nem jött fel [search], az App Store/Play szűrt keresés sem (egy kör, nem kimerítő; arra, hogy tényleg nincs, NINCS ADAT).
  - Külföldön elv-rokon: „Wait In Line" (US App Store, közösségi várakozási idő becslés, [search]); letöltésszám NINCS ADAT.
- VOLUMEN: „sorban állás" 320/hó, „várakozási idő" 20/hó (Google Ads HU, mért, 2025-11..2026-10; csak ellenőrzés). „sorban állás app", „mennyi a sor", „pénztár sor", „posta sorban állás", „kormányablak várakozás": nem adott havi számot (ez nem nulla, hanem NINCS ADAT).
- TERJESZTES: megosztás: heti lista-kép („legtürelmesebb posta") és sajtótéma, fizetett csatorna nélkül; mért elérés-szám NINCS ADAT (a Budicheck-nél sincs közölt szám); a keresés csak ellenőrzés: 320/hó (mért).
- Megépíthető Dave-vel [tipp, Dave erősítse meg]: mobil web (PWA), a meglévő Next.js + Supabase alapon; helylista és térkép nyílt adatból (OpenStreetMap), egy-érintéses jelentés, 30 perces átlag, heti lista. Kívülről kell: helylista-forrás, ingyenes térkép-csempe. Nincs saját hardver.
- Pénz [tipp]: indulásnál semmi, nincs reklám. Később: fizetős, névtelen csúcsidő-jelentés üzletláncoknak/szolgáltatóknak; jelölt helyi hirdetés. Bevétel-szám: NINCS ADAT.
- Kockázat: hidegindítás (két-három jelentésnél hiteltelen, ezért induláskor csak „sztori + heti lista", nem élő térkép); üzlet-értékelés jogi kerete (Lex); kamu-jelentések.

## 2. Szomszéd-bingó

Mi ez: vicces, névtelen, címadat nélküli játék: bingókártya a hétköznapi szomszédos sztorikkal (vasárnap 8-kor fúr, ugat valami, kolbászszag a lépcsőházban, hétvégén fűnyírás), mindenki bejelöli a sajátját, országos számláló: „Ma Magyarország ennyi fúrást hallott".

- MINDENKI: senkit érdemben: csak azt, akinek egyáltalán nincs szomszédja (tanyán egyedül élő), ez nagyon kevés ember. Határeset: ha a gazda ezt kivételnek számolja, ez az ötlet kiesik.
- VICCES: „Vasárnap reggel 8:00: Magyarország fúr" [tipp].
- Itthon (keresési kivonat): szomszédokat összekötő közösségi app van (Miutcánk: kutatása szerint a magyarok szerint a zaj a legrosszabb szomszédi tulajdonság, tízből hét embert zavar; [search]); társasházkezelő appok vannak (Living, HRTL, Neighbium, [search]); vicces bingó/játék típus a keresésben nem jött fel [search].
- VOLUMEN: „zajos szomszéd" 20/hó (Google Ads HU, mért, csak ellenőrzés); „szomszéd zaj", „szomszéd fúrás": nem adott havi számot (NINCS ADAT).
- TERJESZTES: megosztás: országos számláló-kép és a bingókártya; mért elérés-szám NINCS ADAT; a keresés csak ellenőrzés: 20/hó (mért), ezért ez tisztán megosztás-függő.
- Megépíthető Dave-vel [tipp, Dave erősítse meg]: nagyon egyszerű (statikus kártya, számláló, megosztó kép), bejelentkezés nélkül is. Kívülről: semmi.
- Pénz [tipp]: közvetlenül nincs; közvetetten márka-ismertség. Ez a gyenge pontja.
- Kockázat: SOHA nincs cím, név, konkrét szomszéd; különben személyes adat és rágalmazás (Lex).

## 3. Kabát-index (hideg/meleg érzet, településenként)

Mi ez: egy érintés: „Kabát kell?" (kabát / dzseki / pulcsi / póló). A település mai „kabát-táborai" látszanak.

- MINDENKI: senkit. Mindenki öltözik az időjáráshoz, városban és faluban is.
- VICCES: „Ma Miskolcon a sapkások 3:1-re nyertek" [tipp].
- Itthon (keresési kivonat): Időkép: hőtérkép mért adatokkal, észlelések és fotók felhasználóktól, és cikkek a hőérzetről; szubjektív „fázom / kabát kell" jelentést nem találtam [search], a kisebb funkció meglehet, az Időkép app súgója dönt (NINCS ADAT).
- VOLUMEN: „hány fok van" 1 900/hó, „rossz idő" 40/hó (Google Ads HU, mért, csak ellenőrzés).
- TERJESZTES: megosztás: a település napi „tábor-állása" kép; mért elérés-szám NINCS ADAT; a keresés csak ellenőrzés: 1 900/hó (mért).
- Megépíthető Dave-vel [tipp, Dave erősítse meg]: nagyon egyszerű; település-lista kell (nyílt adat), nincs bejelentkezés. Kívülről: település-lista, esetleg időjárás-API (a free réteg feltételét Dave nézze).
- Pénz [tipp]: gyenge; időjárás-appok pénze reklám, nálunk nincs forgalom. Ez a gyenge pontja.
- Kockázat: az Időkép (nagy, ismert) gyorsan lemásolhatja.

FELTETEL-SAJAT: nincs platform-ajánlás

Források (saját fájlok): `/Users/klodel/marveen/shared/seo-integraciok/zseni-otlet-r2-magnes-1112.txt`, `.csv` (Ads HU, 2025-11..2026-10, napi hívás 63). Előző kör: `/Users/klodel/marveen/shared/k-f/zseni-otlet-1112-magnes.md`.
