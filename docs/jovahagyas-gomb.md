# Jóváhagyás egy gombnyomással (APPROVALBOT1013)

Patrik telefonról, egy gombnyomással dönt a jóváhagyás-kérésekről (Telegram 1623/1653). Klodel nincs a láncban: a gombnyomást a dashboard maga dolgozza fel. A biztonsági tervet Viktor nézte át (msg 2302).

## Hogyan működik

- Minden jóváhagyás-kérés egy **külön jóváhagyó bottól** jön, két gombbal: **✅ Jóváhagyom** / **❌ Elutasítom**.
- A gombnyomás után a gombok eltűnnek, és a helyükre az eredmény kerül ("✅ Jóváhagyva 18:42").
- A lezárásról a fő bot ugyanúgy riaszt, mint eddig, ezzel a jelöléssel: "lezárta: Telegram-gomb (approval_bot, a szerver ellenőrizte)".
- Ha a bot nincs beállítva, vagy a küldés elbukik, a kérés a régi úton, a fő bottal megy.

**Miért külön bot:** a fő bot frissítéseit a csatorna-plugin kéri le, és az a jóváhagyó gombokat eldobja. Ha a dashboard is lekérné őket, a Telegram 409-es ütközést adna.

## Mikor számít egy gombnyomás

Mind igaz kell legyen:
1. **A tulajdonos nyomta:** a `from.id` egyezik az `APPROVAL_OWNER_TELEGRAM_ID`-vel, a chat privát, és a chat.id is ugyanez. Más esetben elutasítás és riasztás.
2. **Arra az üzenetre nyomta, amit a szerver küldött:** a message_id és a chat egyezik az adatbázisban tárolttal.
3. **Az üzenet szövege és gombjai változatlanok:**
   - a sha256-a egyezik a küldéskor tárolttal;
   - az üzeneten nincs `edit_date` (a szerver döntés előtt soha nem szerkeszt, így egy másik szerkesztés elrejthetné a leírás egy részét);
   - a billentyűzet pontosan az a két gomb, amit a szerver küldött, ugyanazzal a titokkal (különben az "Elutasítom" felirat alatt jóváhagyó gomb lehetne).
   Eltérésnél elutasítás és ⚠️ riasztás.
4. **A gombon az egyszer használható, 128 bites titok van.** Az adatbázisban csak a hash-e áll, időállandó összehasonlítással; első használatkor, bármilyen lezáráskor és lejáratkor törlődik.
5. **A kérés még nyitott, és nem járt le.**

További szabályok:
- A `PATCH /api/approvals/:id` úton a `resolved_by: "telegram_button"` tiltott (400).
- A `resolution_channel = 'approval_bot'` jelölést API-n nem lehet írni.
- Ha valaki más is lekéri a bot frissítéseit (409), vagy webhook van beállítva, riasztás megy.
- A token nem kerül logba.
- A token az API-n sem érhető el: a `GET /api/vault/<id>` erre az id-ra 403-at ad (audit-sorral), és env-változóhoz vagy fejléchez sem köthető. Ha a Vaultban a token lecserélődik, riasztás megy.

## Mit NEM véd

A prompt-injektált, API-n át cselekvő ágens ellen véd: a tokent az API nem adja ki, és a gombnyomás az eredeti, változatlan üzenethez kötött.

**Nem véd** ott, ahol egy ágens a dashboard kódját, a `store/` fájljait (a Vault titkosított tárát és a kulcsát), vagy a `.env`-et közvetlenül, fájlszinten olvassa vagy írja ugyanazon a UID-n. A `POST /api/vault` a token felülírását nem tiltja; ezt a csere-riasztás teszi láthatóvá. Ezeket a 9a2925a7 2. lépése (TOTP, izolált jóváhagyás, külön uid) zárja le.

## Beállítás

1. **Patrik:**
   - a Telegramban a @BotFather-nél `/newbot`, egy név és egy felhasználónév;
   - a kapott tokent a dashboard Vault-oldalán menti, az id `telegram-approval-bot`;
   - megnyitja az új botot, és megnyomja a **Start**-ot.
2. **Pulzus:** a `.env`-be beírja Patrik numerikus Telegram-azonosítóját: `APPROVAL_OWNER_TELEGRAM_ID=`. Egy bekapcsolt `APPROVAL_BOT_VAULT_ID=` csak akkor kell, ha a Vault-id nem az alapértelmezett.
3. A dashboard percenként újraolvassa a beállítást, újraindítás nem kell.
4. **Próba:** egy teszt-jóváhagyás kérése után Patrik a gombos üzenetet kapja; megnyomja, és a dashboardon a kérés `approved`, csatorna `approval_bot`.
