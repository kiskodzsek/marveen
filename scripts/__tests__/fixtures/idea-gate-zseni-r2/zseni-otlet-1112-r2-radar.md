# Zseni-ötlet, 2. kör: egy ötlet, amit tényleg mindenki átél (Radar, 2026-11-12)

Kérés (Patrik privát TG 18069, szó szerint): "egyik sem tetszik sokkal jobb otlet kéne.. a budichecknél még az is jó hogy tényleg MINDEN embert érint és lehet róla viccesen is kommunikalni stb.. ezek amiket aadtál erőltetett dolgok"
Kész, ha (Klodel 39496): legfeljebb 3 ötlet, inkább 1 jó, ami mindenkit érint (16-70 év, város és falu). Kötelező: (1) „mindenki” próba; (2) egy vicces, megosztható mondat; (3) van-e már itthon; (4) mért kereslet csak ellenőrzésnek; (5) Dave-vel megépíthető; (6) miből jön pénz.

Jelölés: **mért** = saját GET vagy Google Ads API, 2026-11-12 | **[search]** = keresési kivonat | **[tipp]** | **NINCS ADAT**.

Egy ötletet adok le. A `--zseni` lint MINDENKI-próbáján őszintén bukik (nem „senkit”): a 16-18 évesek egy része kimarad, ezt nem írtam át. Egy második (a polcon más ár, mint a kasszán) a kereslet-ellenőrzésen elbukott: „árfeltüntetés” 30/hó, „zsugorinfláció” 40/hó (Google Ads, mért).

## 1. Ember-vonal: közösségi útmutató ahhoz, hogyan jutsz el emberig az ügyfélszolgálaton

**Mi ez:** a felhasználók beküldik, melyik gombsorral jutottak el élő ügyintézőig (MVM, Telekom, Yettel, E.ON, NAV, bankok, biztosítók). Egy stopperrel azt is, mennyit vártak. Az app cégenként megmutatja:
- a legfrissebb működő gombsort („2-3-0”);
- a mai átlagos várakozást és a legjobb hívási idősávot;
- egy havi toplistát: hol várunk a legtöbbet.

Mint a Budicheck: a tartalmat a felhasználók építik, jár XP és jelvény, például „Türelem mestere: 47 perc a vonalban”.

- MINDENKI: kihagyja a 16-18 évesek egy részét [tipp]. Ki marad ki? Akinek nincs áram-, telefon-, bank- vagy adóügye, és sosem hív ügyfélszolgálatot. Ez főleg a 16-18 évesek egy része [tipp]. Mindenki másnak van áramszolgáltatója és mobilszolgáltatója. A falusi 70 éves inkább telefonál, mint online intéz, neki a legfontosabb [tipp].
- VICCES: „Megmutatja, hányast nyomj, hogy ne a Négy évszakot hallgasd negyedszer.” (a gombsor a felhasználók beküldéséből jön, a mondat példa)
- ITTHON: mérve (saját GET 14:20):
  - Google Play magyar áruház, „ügyfélszolgálat várakozás”: csak a cégek saját appjai („E.ON Ügyfélszolgálat … 1,8 star”, „MVM Next … 4,2 star”, „OneTV … 2,4 star”). Több céget átfogó, emberhez juttató app 0.
  - Google Play, „gethuman”: a GetHuman (GetHuman Inc.) megjelenik, de amerikai cégekre szól [tipp; magyar cég a listáján NINCS ADAT].
  - App Store [search]: a találatok várólista-appok (Waitwhile, QueuePad) és egy tárhelyszolgáltató saját support-appja; emberhez juttató app 0.
  - site-szűrt keresés (emag.hu, alza.hu, notino.hu, douglas.hu): 0 találat (az alzás találatok nem kapcsolódó márkaoldalak, ügyfélszolgálati app nincs köztük).
  - .hu webes keresés [search]: csak egy 2016-os Pénzcentrum-cikk („Soha többé várakozás: így hívd a mobilcégek ügyfélszolgálatát”, saját GET) és fórumkérdések (hoxa.hu 2013: „Telefonos ügyfélszolgálaton, hogy lehet emberrel beszélni nem géppel?”, saját GET).
- KULFOLDI-MINTA: GetHuman (USA): kb. 3 millió látogatás havonta [search, CardRates; saját GET 403, nem ellenőrzött]. A megoldás ugyanez: gombsor, valós idejű várakozás, visszahívás.
- VOLUMEN: kb. 161 000 havi keresés hat szolgáltató ügyfélszolgálatára (Google Ads, mért): mvm ügyfélszolgálat 74 000, telekom ügyfélszolgálat 27 100, nav ügyfélszolgálat 18 100, yettel ügyfélszolgálat 14 800, e.on ügyfélszolgálat 14 800, otp ügyfélszolgálat 12 100. A Telekom egy év alatt 27 100-ról 33 100-ra nőtt, 2026 szeptemberében 40 500 volt.
- APROPO: a téma most hír. Ripost, 2026-02-20: „AZ ÜGYFÉLSZOLGÁLATOKON IS MEGJELENT AZ MI, AZ EMBERI SZÓHOZ VISZONT JOGUNK VAN”. Tudatos Vásárló, 2026-04-21: „Tudunk-e még élő emberrel beszélni az ügyfélszolgálaton?”, az EU Digital Fairness Act kapcsán (mindkettő saját GET). Ahogy a robot-ügyfélszolgálat terjed, egyre nehezebb emberhez jutni [tipp].
- PROBLEMA: kb. 161 000 havi ügyfélszolgálat-keresés hat szolgáltatóra (Google Ads, 2026-11-12); a cégek saját appjainak értékelése 1,8-4,2 csillag (Google Play, mért).
- MEGCSINALHATO: IGEN. Webes app, saját hardver és fizikai munka nincs.
- MEGEPITHETO-CSAPATTAL: IGEN.
  - Első működő változat: Dave PWA-ja a meglévő Next.js + Supabase alapon, ezekkel: cégoldal (nyilvános telefonszám, beküldött gombsorok szavazással, „működik / nem működik”), stopper („hívás indul” → „ember vette fel”), havi toplista.
  - Kívülről semmi nem kötelező: a cégek telefonszáma nyilvános.
  - Később a „várakozik helyetted, visszahív” funkcióhoz telefonos API kell, ennek a költsége NINCS ADAT.
- FELTETEL-SAJAT: az első változat PWA (böngészős app), ehhez nem kell app-áruházas fiók. Natív apphoz Apple Developer és Google Play fejlesztői fiók kell; a díjat a zseni-otlet-1112-radar.md rögzíti. Saját fiókunk: NINCS ADAT.
- NEHEZEN-MASOLHATO: IGEN [tipp]: a közösen gyűjtött, friss gombsor- és várakozási adat hálózati hatás. Aki másolja, üres adatbázissal indul, a cégek menüje pedig változik, ezért csak a folyamatos beküldés tartja naprakészen. A cégek saját appjai nem adnak cégek közötti összehasonlítást.
- KERESLET-ITTHON: IGEN. Kb. 161 000 havi keresés hat szolgáltató ügyfélszolgálatára (Google Ads, mért).
- TERJESZTES: organikus keresés: kb. 161 000 havi „<cég> ügyfélszolgálat” keresés (Google Ads, mért), cégenként egy oldallal.
  - A havi toplista („hol várunk a legtöbbet”) sajtóanyag, a rangsort a média átveszi [tipp].
  - A várakozás-rekord kártya megosztható.
- PENZ [tipp]:
  - (1) a cégoldalak forgalmán szolgáltatóváltó-ajánló (mobil, internet, biztosítás) jutalékkal;
  - (2) havi „Ügyfélszolgálat-index” adatriport cégeknek és sajtónak;
  - (3) később prémium: „várakozik helyetted, visszahív, ha ember van a vonalban” (GetHuman-minta).
  - A jutalék mértéke NINCS ADAT.
- KOCKAZAT: a gombsor elavulhat (a cégek menüje változik), erre a beküldés dátuma és a szavazás való. Cégnév-használat és összehasonlító állítás: Lex.

## Források (lekérve 2026-11-12)

- Google Ads API: `shared/seo-integraciok/zseni-r2-radar-1112.csv` (14:19, `--live`).
- https://play.google.com/store/search?q=%C3%BCgyf%C3%A9lszolg%C3%A1lat%20v%C3%A1rakoz%C3%A1s&c=apps&hl=hu (saját GET 14:20).
- https://play.google.com/store/search?q=gethuman&c=apps&hl=hu (saját GET 14:20).
- https://ripost.hu/insider/2026/02/ugyfelszolgalat-mi-mesterseges-intelligencia-telefon, Ripost, 2026-02-20 (saját GET 14:20).
- https://tudatosvasarlo.hu/ugyfelszolgalat-2026-eltunnek-az-emberek/, Tudatos Vásárló, 2026-04-21 (saját GET 14:20).
- https://www.hoxa.hu/telefonos-ugyfelszolgalaton-hogy-lehet-forum (saját GET 14:20).
- https://www.penzcentrum.hu/vasarlas/20160808/soha-tobbe-varakozas-igy-hivd-a-mobilcegek-ugyfelszolgalatat-1050858, Pénzcentrum, 2016 (saját GET 14:20).
- [search]: https://www.cardrates.com/news/gethuman-expedites-customer-service/ (saját GET 403); App Store-keresés (apps.apple.com); site-szűrt keresés emag.hu, alza.hu, notino.hu, douglas.hu.
