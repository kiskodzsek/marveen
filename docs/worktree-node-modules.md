# Worktree és node_modules: egy közös telepítés, nem másolat

Patrik döntése (TG 4599, 2026-10-21), kártya 1c58f629.

## Mi a szabály

Ha új git worktree-t nyitsz egy Node-projekthez (Marabel, mcp-connectors, Company-OS), akkor a node_modules-a ne saját telepítés legyen. Legyen egy symlink, ami a saját fő klónod node_modules-ára mutat. Erre szolgál a `scripts/worktree-add.sh`:

```bash
scripts/worktree-add.sh <fő-klón> <új-worktree> <ág> [<kiinduló commit>]
# példa:
scripts/worktree-add.sh agents/pixel/repos/marabel agents/pixel/repos/marabel-wt-x feat/x origin/main
```

## Miért

2026-10-21 01:55-kor az `agents/` alatt 60 valódi node_modules volt, összesen 31,7 GB, worktree-nként kb. 0,75 GB. 13 óra alatt a szabad lemez 49 GiB-ról 4 GiB-ra fogyott (`agents/kernel/reports/lemez-2026-10-21-0155.md`). Ugyanahhoz a lockfile-hoz nem kell második példány.

## Mit csinál a szkript

1. Létrehozza a worktree-t. Ha az ág már létezik, azt veszi ki, különben új ágat nyit a megadott commitból.
2. A node_modules-t a fő klón **fizikai** node_modules-ára linkeli, feloldva. Így nincs lánc (link a linkre), ami egy régi worktree törlésekor elszakadna.
3. Csak akkor linkel, ha az új worktree `package-lock.json`-ja bájtra azonos annak a klónnak a lockfile-jával, amelyiké a node_modules, és ha azt a node_modules-t az npm telepítette.
4. A prod fára (a marveen telepítés gyökerére) soha nem linkel. A prod fa alapból annak a repónak a fő worktree-je, amelyikben a szkript van (a git common dir szülője), így az őr akkor is tart, ha a szkriptet egy ág-worktree-ből futtatod. Ettől függetlenül minden olyan forrást elutasít, amelyiknek a node_modules-a mellett `store/claudeclaw.db` van (Marveen-telepítés), bárhol is legyen.
5. Másik ügynök klónjára sem linkel: a `<prod fa>/agents/<név>/` alatt a forrásnak és az új worktree-nek ugyanahhoz a névhez kell tartoznia (egy Unix-felhasználó fut mindenkinél, így egy npm install az egyik ágensnél a másik node_modules-át írná).
6. Linkelt worktree node_modules-ára SOHA nem linkel (code review 2026-10-30, #16; kártya f24e6745). Egy ág-worktree eltűnik, amikor az ága beolvad, és vele minden rá mutató link eltörik. Mérve 2026-11-04-én: 46 link közül 11 törött volt, és további 31 mutatott ág-worktree-re (pl. `wt-mmk`, `wt-kosz-final`), azaz a következő takarításnál azok is eltörtek volna. Stabil forrás csak a fő klón és a deps-tár (lent).
7. Ha `--node-modules-from` nélkül hívod, és a fő klón nem tudja kiszolgálni az új worktree-t (nincs telepítése, vagy más a lockfile-ja), a szkript magától a deps-tárat veszi, ha van az új worktree lockfile-jához.
8. A linket kizárja a gitből. A `.gitignore`-ban a `node_modules/` (perjellel) csak könyvtárra illeszkedik, symlinkre nem. Ha a repó nem fedi le, a szkript a `/node_modules` sort az `info/exclude`-ba írja.

Kilépési kódok:
- 0: linkelve;
- 3: a worktree elkészült, de NINCS linkelve (az okot kiírja);
- 64: hibás használat.

## Amit TILOS

- **Linkelt worktree-ben `npm install` / `npm ci`.** A fő klón közös node_modules-át írná át, és minden rá linkelő worktree-t elrontana.
- Másik ügynök klónjára linkelni. Mindenki a saját fő klónjára mutat.

## A deps-tár: egy telepítés lockfile-onként, ágtól függetlenül

Ha a fő klónodnak nincs telepítése, vagy a munkád más lockfile-on fut, mint a fő klón (a Marabelnél ez a gyakori eset), ne egy ág-worktree node_modules-ára linkelj, hanem egyszer hozz létre egy deps-tárat:

```bash
scripts/deps-store.sh <egy worktree vagy klón ezzel a lockfile-lal>      # --dry: csak kiírja, hova kerülne
# -> agents/<te>/deps/<repó>-<a package-lock.json sha256-jának első 16 jegye>/
```

Ez a heavy-job kapu alatt egyszer lefuttat egy `npm ci --ignore-scripts`-et a tár saját mappájában (csak a `package.json` és a lockfile van ott, a repó fájljai nem). Ha a tár már megvan, semmit nem futtat, csak kiírja az útját. Utána a `worktree-add.sh` magától erre linkel minden ugyanilyen lockfile-ú új worktree-t. A tárat ág-takarítás nem viszi el; amelyikre már semmi nem mutat, azt a gazdája törli (`rm -rf`).

`--ignore-scripts`: a kiskodzsek/marabel 0691037f2-n két csomagnak van install-szkriptje (protobufjs, unrs-resolver, utóbbi csak dev). Ha valamelyikre mégis szükség van, az az adott worktree saját telepítésében fut, ahogy eddig.

## Ha az ág függőséget változtat

Eltérő lockfile esetén a szkript nem linkel (exit 3). Ilyenkor a worktree saját telepítést kap, a heavy-job kapu alatt:

```bash
heavy-job.sh --name npm-ci -- npm ci
```

## Ismert korlát

A Turbopack nem fogad el a projekt gyökerén kívüli node_modules-t. Ezért a `next build`-et vagy Turbopacket igénylő ellenőrzés (például a Marabel og-preview) linkelt worktree-ben bukik, és a CI-ben fut (mérve 2026-10-20-án, `ops-tmp/ci-babysetup-on2e8270-2026-10-20.log`). A tsc, az eslint és a node-os ellenőrző szkriptek linkkel is futnak.

## Meglévő worktree-k

A szkript csak az új worktree-ket kezeli. A meglévő saját másolatokat mindenki maga cserélheti linkre, ha a worktree tiszta és a lockfile azonos: törli a node_modules-t, és létrehozza a linket. A törlés az ő döntése, a daily-cleanup ehhez nem nyúl.
