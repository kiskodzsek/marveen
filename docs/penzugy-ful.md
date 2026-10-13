# Pénzügy fül (FINANCETAB1013)

A dashboard "Pénzügy" füle cégenként, csak olvasható módon mutatja ezeket:
- a havi pénzforgalmi eredményt;
- az utolsó hónap kategóriáit;
- az előrejelzést forgatókönyvenként;
- a bankegyenleg-projekciót számlánként és összesítve;
- a termékenkénti worst-case költséget.

Az adatot a pénzügyes ágens CSV-fájlokban adja, a dashboard csak megjeleníti.

## Bekapcsolás

A `.env`-ben két kulcs kell, és ha bármelyik üres, a fül ki van kapcsolva:
- `FINANCE_DIR=shared/penzugy`: abszolút út, vagy a projekt gyökeréhez viszonyított;
- `FINANCE_USERS=patrik`: vesszővel elválasztott dashboard-felhasználónevek.

## Ki láthatja, és mit véd ez valójában

**A nézetet csak az a jelszóval bejelentkezett dashboard-felhasználó (session) kapja meg, aki rajta van a `FINANCE_USERS` listán.** Minden más 403:
- a közös flotta-token,
- a device-kulcs,
- az operator-, azaz Bridge-session,
- a federation-peer,
- a hiányzó hitelesítés.

**Amit a kapu kizár:**
- minden, a gépen KÍVÜLI hozzáférést (device-kulcs, Bridge, federation);
- az ágensek rutin flotta-tokenes hívásait;
- a flotta-tokennel létrehozott új dashboard-felhasználót (`FINANCE_USERS`).

**Amit NEM zár ki:** egy szándékosan próbálkozó helyi ágenst. A CSV-fájlok és a `store/claudeclaw.db` a lemezen vannak, és minden ágens ugyanazzal a UNIX-felhasználóval fut. Ehhez OS-szintű szétválasztás kellene.

**Hogyan jut el a nézet a böngészőbe:**
- A fül XMLHttpRequest-tel kéri le, így csak a session-cookie megy, a tárolt token nem.
- A HTML egy üres sandboxú iframe-be kerül (`srcdoc`): nincs benne script, nincs same-origin hozzáférés.
- A dokumentum saját `<meta>` CSP-t visz, mert a srcdoc a válasz CSP-fejlécét nem kapja meg. Ez képet, betűtípust és hálózati kapcsolatot sem enged.
- Minden érték HTML-escape-elve kerül a lapra, a lapon nincs link és nincs URL.

A hozzáférés naplózva van: ki, mikor, melyik cégek. Az adat maga nem kerül a naplóba.

## Fájlformátum

Minden cég egy almappa (`[a-z0-9_-]{1,32}`), benne rögzített nevű fájlok. Egyik sem kötelező; ha egy fájl hiányzik, az a szakasz nem jelenik meg.

A CSV fejléce kötelező, és lehet `,` vagy `;` elválasztójú. Az összeg egész forint (negatív is lehet). Egy fájl legfeljebb 1 MB és 5000 sor.

| Fájl | Kötelező oszlopok | Opcionális |
|---|---|---|
| `pnl.csv` | honap (ÉÉÉÉ-HH), kategoria, osszeg_huf, tipus (bevetel / koltseg / nem_eredmeny) | jeloles (teny / tipp; üres = tény), forras |
| `elorejelzes.csv` | honap, kategoria, osszeg_huf, forgatokonyv (pl. alap / rossz) | tipus, jeloles (ha nincs oszlop: tipp) |
| `bank_projekcio.csv` | datum (ÉÉÉÉ-HH-NN), szamla_alias, egyenleg_huf, tenyleges (true/false) | forgatokonyv (a tényleges sorban üres), esemeny (partnernév nélkül) |
| `marabel_termek_koltseg.csv` | termek, tetel, osszeg_huf_per_egyseg, forgatokonyv | |

**Hogyan számol a nézet:**
- A költség előjele mindegy, abszolút értékben számít.
- A `nem_eredmeny` sor kimarad az eredményből, és külön oszlopban látszik.
- Az előrejelzésben a `tipus` nélküli sor előjelesen adódik a nettóhoz.
- A tipp-sorok `~` jellel és dőlten jelennek meg.
- A bank-összesen minden dátumra a számlák utolsó ismert egyenlegének összege.
- A kategória-slugok magyar nevet kapnak: bevetel, ber_jarulek, adok, infra_saas, auto, konyvelo, bank_dij, egyeb_koltseg, nem_eredmeny. Az ismeretlen slug változatlanul jelenik meg.

**A `meta.json`-ból csak ezek a kulcsok jelennek meg, szövegként:**
- `nev` vagy `ceg`;
- `generalva`, `penznem`, `szemlelet`, `megjegyzes`, `elorejelzes_modszer`;
- `forrasok`, `nem_szerepel`, `figyelmeztetesek` (szöveglista; a figyelmeztetés kiemelve látszik);
- `hianyzo_honapok`: ezek a hónapok "nincs adat" sorként jelennek meg, nem nullaként;
- `alap_feluliras` (`{kategoria: indoklás}`, tippként);
- `besorolatlan_tetelek` (darabszám).

Minden más kulcs kód-módosítás nélkül nem jelenik meg.

Személynév, számlaszám és partneradat ne kerüljön a fájlokba, csak összesítés. Tranzakciószintű bankadathoz új review kell (d651a52b, B6).
