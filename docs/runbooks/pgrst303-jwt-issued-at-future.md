# Runbook: PGRST303 "JWT issued at future" (Supabase, Marabel)

Státusz: Pulzus, 2026-11-16; Viktor (biztonság) és Dave átnézésére vár. Forrás: `agents/pulzus/incidents/2026-10-12-vasarlas-jelentes.md` (Tanulság 1, 3, 4, 6, 9, 11, 12; 9. teendő). Ami nem abból vagy a watchdog forrásából jön, "tipp" vagy "nem mért" jelöléssel áll.

Hatókör: egyetlen incidens (2026-10-12) tapasztalata. Ok-hipotézis (tipp): Supabase-oldali óraeltérés az `sb_secret_` kulcsoknál; a status.supabase.com akkor nem jelzett incidenst, a nyilvános issue-kat nem ellenőriztük.

## 1. Tünet
- Szerveroldali Supabase-hívások 401-gyel buknak: `{ code: 'PGRST303', message: 'JWT issued at future' }` (Vercel runtime log).
- A vásárlás oldal (`/vasarlas/*`) HTTP 200 + streamelt renderhibát ad: a státuszkód-alapú figyelés vak (Tanulság 1). A watchdog a `digest` mintát keresi a törzsben (`ops/marabel-watchdog.sh` 133-134. sor).
- Egyszerre eshet ki: vásárlás, fizetés utáni út, `/h`, `/k` (kinyomtatott QR-ek!), cronok (Tanulság 3).
- Felhasználói (admin) JWT-s belépés is hibázhatott (2026-10-12: nem mértük, a restart után 16:48-kor működött).
- Csendes jelek, amelyek NEM bizonyítanak (Tanulság 7-9): `conversion_events` csend, `system_health_runs` 'passed' sor, az alert-notifications és a cron_heartbeats csendje (ugyanazzal a kulccsal futnak, mint ami hibás).

## 2. Megerősítés (csak olvasó, vevői adat nélkül)
1. `date` (Europe/Budapest), idővonal indul.
2. `/h/watchdog-probe-0000000000`: működő kulcsnál HTTP 404, hibásnál nem 404 (watchdog 136. sor; Tanulság 4). Csak GET.
3. Vercel runtime log: `PGRST303` sor a kiesés idejére (`marabel-ops-api` skill, olvasó út).
4. `status.supabase.com` állapota (quarantine-readeren át; a szülő-domaint a promptban nevezd meg).
5. Marketingoldalt böngészővel NEM nyitunk megerősítésre (Link-prefetch hamis eseményt írhat, Tanulság 5; a javítás állapota nem mért).
6. Hasonló tünet más okból is lehet: előbb Viktor ítélje meg a betörés-gyanút (kieses-runbook.md sorrendje).

## 3. Súlyosság és jelzés
P1 (vásárlás/belépés nem működik). Azonnal Klodel (és Viktor, ha biztonsági gyanú), a kieses-runbook.md szerint: Pulzus vezet, karbantartás-kapcsoló a kieses-runbook szerinti előre adott felhatalmazással.

## 4. Javítás: SORREND (Tanulság 12)
Mindegyik lépés külön, kimondott Patrik "mehet" kell, kivéve az előre adott incidens-felhatalmazást (CLAUDE.md "Kiadás és éles üzem").

Előfeltétel (Viktor, 2026-11-16): ez a sorrend CSAK akkor áll, ha Viktor biztonsági ítélete (2. pont 6.) NEM gyanú. Gyanú IGEN vagy ISMERETLEN esetén a restart nem javítás: a kulcscsere és a régi kulcsok visszavonása az első (kieses-runbook.md sorrendje).

**ELSŐ: a Supabase-projekt újraindítása (Patrik indítja a dashboardon).**
- Miért első: 2026-10-12-n ez megszüntette a hibát (16:44:30 indítás, 16:47:05 kész; admin-belépés 16:48, az eredeti `sb_secret_` 5/5 próbán működött), és nincs mellékhatása a kulcsokra.
- A mi tokenünk nem tudja elindítani (403, nincs project_admin_write; Tanulság 12). Hogy kapjon-e ilyen jogot, Viktor és Patrik döntése: NEM döntöttük el.
- Hatás: rövid kiesés a restart alatt (a hossza 10-12-n: ~2,5 perc, egyetlen mérés).
- Utána: 2. pont próbái, Vercel log, `/vasarlas/*` füstpróba.

**MÁSODIK, csak ha a restart nem segít: kulcscsere** (2026-10-12: legacy `service_role` kulcsra, `SUPABASE_SECRET_KEY` Vercel env + redeploy, pipe-ban, sehol nem mentve). Legacy `service_role` kulcsra váltva az hosszú lejáratú JWT, egyenként nem vonható vissza, csak a JWT-titok cseréjével (Viktor szerint a Supabase-dokumentáció alapján; NEM mért): ez ideiglenes megoldás, a visszaállás `sb_secret_` kulcsra határidős teendő a helyreállás után. Mellékhatásokkal jár, ezért előtte a kulcs-felhasználók listája (Tanulság 11):
- PostgREST (szerveroldali kliensek);
- edge functionök: a support-chat a kulcs AZONOSSÁGÁT ellenőrzi (`SUPABASE_SECRET_KEYS`), cserénél eltört (AI-súgó);
- HMAC-aláírás: a belépőlink (`src/lib/auth/post-purchase-link.ts`), az email-proof (`email-proof.ts`) és a render-token (`src/lib/print-renderer/render-auth.ts`) a `linkSigningSecrets()`-en át a `MARABEL_LINK_SIGNING_SECRET`-tel ír alá, ha az be van állítva, és csak nélküle esik vissza a `SUPABASE_SECRET_KEY`-re (`link-signing.ts`, marabel main f682d3868; Viktor átnézte). MÉRVE 2026-11-16 (Pulzus, Vercel env-metaadat, érték nélkül): a `MARABEL_LINK_SIGNING_SECRET` production, sensitive, frissítve 2026-10-14 15:36, tehát a kulcscsere ezeket NEM érvényteleníti. Ha a változó hiányzik vagy 32 karakternél rövid, a csere a kiadott belépőlinkeket, a jelszó-visszaállító sütiket és a 10 perces render-linkeket érvényteleníti: csere előtt újra kell mérni (`GET /v9/projects/<prj>/env`, csak key/target/type/updatedAt).
- külső hívó (Dave, marabel origin/main 9453ea38, a workflow-fájlokat és a szkriptet olvastam én is): a GitHub Actions `.github/workflows/daily-e2e-smoke.yml` mindkét jobja (content-pipeline smoke, guest answer UI smoke) a `prod-smoke` environment `secrets.SUPABASE_SECRET_KEY`-ével fut (`scripts/e2e/daily-content-pipeline-smoke.mjs`). Kulcscserénél ezt a GitHub-environment secretet is cserélni kell, különben a napi smoke piros (Tanulság 10); ez is kulcsművelet, Patrik "mehet" kell hozzá. Kézi szkript: `scripts/billingo-test-proforma.mjs --order` (env-ből olvas, nem ütemezett). NEM ezt használják: a pg_cron workerek (saját vault-titkok), az `edge-deploy.yml` (csak `SUPABASE_ACCESS_TOKEN`). Nem mért: a GitHub-environment secret tényleges értéke (csak a hivatkozást olvastuk), és a repón kívüli hívó (pl. más gépen futó szkript).
A GUEST_AUTH_SECRET-re épülők (vendég/mesélő session, leiratkozó link, question-prompt token, rate-limit) nem érintettek.

A jóváhagyás-kérés a pontos lépést nevezi meg a CLAUDE.md "JÓVÁHAGYÁS KELL" alakjában; hallgatás nem jóváhagyás (Tanulság 6). Előre adott, a tünethez kötött P1-felhatalmazás csak a RESTARTRA javasolható, a kulcscserére nem (mellékhatások, kulcs-kezelés; Viktor, 2026-11-16). Egyik sincs megadva, most nem él; a döntés Patriké.

## 4a. Mit csinál MÁR a kód (mérve: marabel origin/main f682d3868, `src/lib/supabase/clock-skew-retry.ts` fejléc és konstansok, 2026-11-16)
Ezt a diagnózis előtt tudni kell: a rövid óraeltérést a kód elnyeli, ezért egy tartós PGRST303 már azt jelenti, hogy a 3,5 s-os próbák és a tartalék is elbukott.
- Újrapróbálás CSAK 401 + `PGRST303` (vagy "JWT issued at future") esetén: 0,5 s / 1 s / 2 s, legfeljebb 3 (`CLOCK_SKEW_RETRY_DELAYS_MS`). A proxyban (minden oldalkérés előtt) csak 1 rövid próba, 200 ms.
- Olvasás (GET) mindig; írás (POST/PATCH/PUT/DELETE/RPC) csak `/rest/v1/` úton, csak PGRST303 kóddal, csak újraküldhető törzzsel. Auth, Storage, Edge Functions írása SOHA nem ismétlődik. (A "SQL nem futott a PGRST303 előtt" a kód kommentje szerint PostgREST-dokumentáció, élő Supabase-en nem mért.)
- Naplósor: `Supabase JWT clock-skew (PGRST303), retrying` (útvonal, lekérdezés-paraméter és kulcs nélkül) - ez a Vercel logban a keresendő minta enyhébb eltérésnél. `supabase-admin pgrst303_retry=1` az edge function oldalon.
- `/vasarlas/[slug]`: az újrapróbák után is PGRST303 esetén a "most nem elérhető" oldal, nem 500 (page.tsx 145-147. sor környéke). A watchdog státuszkód-alapú ellenőrzése ettől még vak lehet: a törzset kell nézni (1. pont).
- TARTALÉK KULCS: ha a `SUPABASE_SECRET_KEY_FALLBACK` be van állítva (csak legacy service_role JWT lehet; `sb_` előtagú vagy nem JWT alakú figyelmen kívül marad), az első elutasítás után a szerveroldali service kulcsos kérés azonnal a tartalékkal megy. Nyom: `[ALERT] SUPABASE_SECRET_KEY_FALLBACK_USED` a logban, és az 5 perces health check `security.supabase_secret_key_fallback_used` riasztása (system_alerts). Visszavont/hibás elsődleges kulcsnál (nem PGRST303) NINCS váltás: a visszavonás leállítja a hozzáférést.
- A tartalék kulcs engedélye legfeljebb 30 napra szólt (Viktor, 2026-10-12-től), tehát 2026-11-11-én LEJÁRT (Viktor, 2026-11-16); a kód maga nem jár le. Döntve: lejárt, nincs beállítva. A beállítatlan kódút nem csinál semmit (`src/lib/supabase/server-keys.ts`), így maradhat; a `SUPABASE_SECRET_KEY_FALLBACK` újbóli beállítása env- és kulcsművelet: új Viktor-átnézés és Patrik "mehet". Hogy a `SUPABASE_SECRET_KEY_FALLBACK` MA be van-e állítva élesben: MÉRVE 2026-11-16 (Pulzus, marabel-ops-api, Vercel projekt env-metaadat, érték nélkül): NINCS beállítva (51 változó, nincs FALLBACK/SERVICE/LEGACY/JWT nevű kulcs, nincs lapozás). A `SUPABASE_SECRET_KEY` frissítve 2026-10-12 16:59 (production, sensitive). Ismétlés: `GET /v9/projects/<prj>/env` a vq.sh-val, kimenet csak key/target/type/updatedAt.
- Következmény a diagnózisra: ha a logban `SUPABASE_SECRET_KEY_FALLBACK_USED` van, az eltérés Supabase-oldali és ismétlődik, de a vásárlás addig él; ha a tartalék nincs beállítva vagy az is elutasít, a 3,5 s fölötti tartós hiba megy át a hívóhoz, és ez az a P1 helyzet, amit az 1-3. pont kezel.

## 5. Lezárás
- Helyreállás MÉRÉSSEL: `/h` próba 404, `/vasarlas/*` füstpróba, Vercel log tiszta, vevői út (post-deploy-buyer-path-check).
- Ellenőrizni a kulcscsere mellékhatásait (edge function, belépőlinkek, GitHub `prod-smoke` secret) listából.
- Incidens-jelentés (sablon: Pulzus CLAUDE.md), hatásos rendelés/aktiváció számmal.

## 6. Nyitott pontok (nem mért / nem eldöntött)
- A restart-jog a tokenünknek: Viktor ajánlása NEM, amíg nincs olyan jog, ami csak restartot enged, a `project_admin_write`-nál szélesebb írást nem (hogy ilyen hatókör létezik-e: NEM mért); a döntés Patriké, Klodelen át.
- Kulcstól független külső figyelő a riasztó némasága ellen (Tanulság 9): a watchdog ilyen, a dead man's switch nincs mérve.
- A smoke-hiba (GitHub Daily E2E) gazdája (Tanulság 10).
- A kód-oldali kezelés újraolvasva (4a. szakasz, main f682d3868); a #423, #424, #430, #463, #476 egyenkénti PR-szintű visszakeresése nem történt meg, a main forrása a mérvadó.
- A `SUPABASE_SECRET_KEY_FALLBACK` élő beállítottsága: MÉRVE (2026-11-16), nincs beállítva a Vercelen, tehát PGRST303 esetén tartalék kulcs NINCS: a tartós hiba átmegy a hívóhoz (lásd a 2. pont következményét). A 30 napos engedély 2026-11-11-én lejárt, döntve: nincs beállítva (4a. szakasz). Nyitott maradt: az edge function titkok (Supabase-oldal, nem a Vercel env) NEM mértek.
- A forrás-incidens iratai (`agents/pulzus/incidents/2026-10-12-*`) nem kerülnek a repóba; a hivatkozott Tanulság-számok azokra mutatnak.
