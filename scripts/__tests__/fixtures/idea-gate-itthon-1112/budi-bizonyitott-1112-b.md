# Budi-bizonyított, B-kör: kint nagy, itthon nincs magyar nyelvű változata (Radar, 2026-11-12)

Kérés (Klodel 39537; Patrik TG 18069/18089). Pontosított mérce:
- ITTHON = nincs magyar nyelvű, magyar közösségű változat;
- kint mért nagy siker (1M+ letöltés vagy hasonló, 4,0+ csillag);
- mindenkit érint, a téma maga vicces;
- WC-téma kizárva, a korábbi kizártak maradnak;
- max. 3, BIZONYITEK sorral.

Jelölés: **mért** = saját GET 2026-11-12 14:39 | **[search]** | **[tipp]** | **NINCS ADAT**.

Egy jelöltet adok le. Ez felel meg minden mért feltételnek; másikat, ami a WC-tilalom és a kizárások után is átment volna, nem találtam.

## 1. Nextdoor-minta: a szomszédság közös hírfolyama (USA, Nextdoor, Inc.)

- BIZONYITEK: Nextdoor: Neighborhood Network (USA, Nextdoor, Inc.): Google Play US „4.6 star 445K reviews 10M+ Downloads”, App Store US „2.2M RATINGS 4.7”, „CHART #6 News”, a cég szerint „110 million verified neighbors across 350,000 neighborhoods”; https://play.google.com/store/apps/details?id=com.nextdoor&hl=en&gl=US ; https://apps.apple.com/us/app/id640360962 ; https://about.nextdoor.com/ ; 2026-11-12
- MIT CSINÁL: a szomszédság egy hírfolyamot kap, csak a hitelesített lakóké. Megy rajta a riasztás, a „ki fúr hajnalban”, az elcsatangolt macska, az ajánlás (melyik szerelő jó), az ingyen elvihető holmi és a helyi esemény. A tartalom a lakóké. Hogy a szomszédi bejegyzések maguk szórakoztatnak, azt külföldön a nagy követőszámú „Best of Nextdoor” típusú gyűjtőoldalak mutatják [tipp, nem mértem].
- MINDENKI: senkit: szomszédja mindenkinek van, panelban, társasházban és faluban egyaránt, 16 és 70 év között [tipp].
- VICCES: „Hajnali hatkor fúr valaki a lépcsőházban: a hírfolyamon már tizennégyen nyomoznak, ki az.”
- ITTHON: mérve (saját GET 14:39):
  - App Store HU: a Nextdoor (id640360962) magyar oldala HTTP 404, itthon nem tölthető le.
  - Google Play HU: a Nextdoor oldala megjelenik („10 M+ letöltés”), de „Telepítés” gomb nincs rajta (a Poop Map magyar oldalán volt).
  - Google Play HU, „szomszéd”: játékok („Neighbours from Hell”), szomszéd-közösségi app 0.
  - Google Play HU, „szomszédság közösség”: egy indiai klón („Nextdoor Neighborhood”, EQUITYSOFT TECHNOLOGIES), a Bébicsősz.hu és nem kapcsolódó appok. Magyar nyelvű, magyar közösségű szomszéd-hálózat: 0.
  - site-szűrt keresés (emag.hu, alza.hu, notino.hu, douglas.hu): 0 találat (14:41; a találatok játékok és okosotthon-app, szomszéd-közösségi app nincs köztük).
  - Tényleges versenytárs a Facebook helyi lakócsoportjai, de ezek nem külön app [tipp, nem mértem].
- VOLUMEN: NINCS ADAT. A Google Ads API kvótája 14:40-kor kimerült (HTTP 429 RESOURCE_EXHAUSTED). Egy korábbi mérés: „zajos szomszéd” 20/hó (Mágnes, `shared/seo-integraciok/zseni-otlet-r2-magnes-1112.csv`).
- PROBLEMA: a szomszéddal kapcsolatos hétköznapi ügyek (zaj, csomag, ajánlás, riasztás) nem a keresőben, hanem helyi Facebook-csoportokban mennek; az USA-ban erre 110 millió hitelesített szomszéd jelentkezett (Nextdoor, mért).
- MEGCSINALHATO: IGEN.
  - Első működő változat: Dave PWA-ja a meglévő Next.js + Supabase alapon (cím szerinti szomszédság, hírfolyam, kategóriák).
  - A lakóhely-hitelesítés a nehéz rész; a módja NINCS ADAT (Lex: GDPR).
- NEHEZEN-MASOLHATO: IGEN [tipp]: hálózati hatás, mert a szomszédság csak akkor él, ha a szomszédok fent vannak. Aki később jön, üres utcákkal indul. Kockázat: a Facebook-csoportok megszokása.
- KERESLET-ITTHON: NEM mért. Az Ads-kvóta kimerült; egyetlen korábbi szám („zajos szomszéd” 20/hó) kevés ahhoz, hogy keresleti bizonyíték legyen.
- TERJESZTES: lépcsőházi szórólap és QR-kód a postaládákon, 1 társasház = 1 indulás [tipp]; mért szám: NINCS ADAT.
- KOCKAZAT: rágalmazás, név szerinti szomszédvita, lakcím-adat (Lex); a moderálás emberi munka.

## Források (lekérve 2026-11-12, saját GET 14:39)

- https://play.google.com/store/apps/details?id=com.nextdoor&hl=en&gl=US
- https://play.google.com/store/apps/details?id=com.nextdoor&hl=hu&gl=HU
- https://apps.apple.com/us/app/id640360962 ; https://apps.apple.com/hu/app/id640360962 (404)
- https://about.nextdoor.com/
- https://play.google.com/store/search?q=szomsz%C3%A9d&c=apps&hl=hu&gl=HU ; https://play.google.com/store/search?q=szomsz%C3%A9ds%C3%A1g%20k%C3%B6z%C3%B6ss%C3%A9g&c=apps&hl=hu&gl=HU
- `shared/seo-integraciok/zseni-otlet-r2-magnes-1112.csv` (Mágnes mérése)
