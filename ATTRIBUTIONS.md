# Köszönet

A Marveen több nyílt forrású projektre és koncepcióra épít. Ez a dokumentum azokat a forrásokat kreditálja, amelyek beépültek a kódbasebe vagy érdemi hatással voltak a tervezésre.

A Marveen saját licensze: [LICENSE](./LICENSE) (MIT).

## Becsomagolt vagy adaptált kód

### Bumblebee (ellátási-lánc biztonsági scanner)
- **Forrás**: https://github.com/perplexityai/bumblebee
- **Szerző**: Perplexity AI
- **Licensz**: Apache 2.0
- **Hol a Marveen-ben**: `seed-scheduled-tasks/bumblebee-hygiene-scan/` (a bináris, a scan profil és a beépített threat-intel katalógusok az integráció időpontjában aktuális verziójukkal)
- **Mit csinál nálunk**: heti hétfő 09:00-kor read-only leltár a telepített csomagokról, MCP konfigurációkról és kiterjesztésekről, összeillesztve a beépített ellátási-lánc fenyegetés-katalógusokkal. Csak találat esetén szól.

### Zhutov skill csomag (handoff / retrospective / skill-management)
- **Forrás**: https://artemxtech.substack.com/p/3-claude-code-skills-that-make-claude
- **Szerző**: Artem Zhutov
- **Hol a Marveen-ben**: `seed-skills/handoff/`, `seed-skills/retrospective/`, `seed-skills/skill-management/`
- **Mit csinál nálunk**: a skill-csontváz a Marveen flotta-architektúrájára adaptálva. Az 5-szekciós handoff struktúra (Goal, Current Progress, What Worked, What Didn't Work, Next Steps), a sub-agent retrospective minta, és a skill-rot életciklus-kezelés koncepció mind Zhutov csomagjából származik. A megvalósítás TypeScript-ben újraírva, integrálva a Marveen checkpoint, DREAM, memória és inter-agent message rendszereivel.

### printing-press (agent-CLI generátor)
- **Forrás**: https://github.com/mvanhorn/cli-printing-press
- **Szerző**: Mike Van Horn
- **Hol a Marveen-ben**: generátor eszközként használjuk (nem becsomagolva) -- ezzel készülnek a `skool-cli`, `aiam-blog-pp-cli`, `connectors-hu` CLI csomagok, amelyek külső API-kat csomagolnak, plus a hozzájuk tartozó Claude Code skill fájlok.

## Helyben futtatott külső modellek (nincsenek a repóban)

A képszűrő (`scripts/image-safety/`) két detektor-modellt tölt be. A hívó kód saját (`detectors.py`: onnxruntime a CPU-provideren, illetve transformers safetensors-ból), és minden modellfájlt sha256-tal pinnel, betöltés ELŐTT ellenőrizve; eltérésnél, hiányzó vagy nem pinnelt fájlnál a detektor nem tölt be. A modellfájlok viszont NEM részei a repónak és nem is lesznek: a telepítés helyi, git-ignorált modellkönyvtárában vannak (alapból `<mflux-gyökér>/models/image-safety/`). Semmilyen telepítő vagy scaffold nem tölti le őket automatikusan. Modell nélkül a `check.py` 3-as kóddal kilép, és egyetlen képet sem enged át (fail-closed); aki saját telepítésen használja, a modellt maga, a saját felelősségére tölti le.

### NudeNet (meztelenség-detektor)
- **Forrás**: a PyPI `nudenet==3.4.2` wheel (`nudenet-3.4.2-py3-none-any.whl`, sha256 `5937dbd84e5d8e5de038f08ffea5a1bb50a08475776bf2b4795914ce0eaf0331`), ebből csak a `nudenet/320n.onnx` (sha256 `c15d8273adad2d0a92f014cc69ab2d6c311a06777a55545f2c4eb46f51911f0f`), zipfile-lal, pontos névvel; a csomag nincs telepítve, a kódja nem fut. Projekt: https://github.com/notAI-tech/NudeNet
- **Licensz**: AGPL-3.0. A PyPI-metaadat "MIT"-et ír, a wheel saját `dist-info/LICENSE` fájlja viszont az AGPL v3 teljes szövege (2026-10-20-án olvasva); ellentmondás esetén a szigorúbbat alkalmazzuk.
- **Hol a Marveen-ben**: sehol. A `model.onnx`, `labels.json` és `config.json` csak helyben van, git-ignorálva. A `labels.json` a pinnelt forrás címkelistájából, a `config.json` (`input_size` 320) a forrás alapértékéből készült; mindkettő tartalom szerint pinnelve.
- **Használat**: helyi, nem terjesztett, nem módosított futtatás; hálózati szolgáltatásként nem érhető el. A NudeNet forrásából nem másoltunk kódot.

### ViT NSFW-osztályozó (második detektor)
- **Modell**: Falconsai/nsfw_image_detection (Hugging Face), revízió `96cb0d0342c7afb80cab76ecc58b265fa44da256`. Pinnelt fájlok: `model.safetensors` (sha256 `97b2ce64ec146884b37f98ee7944ca4891aa72f6827dc0cb10684a1cbecd5830`, = HF LFS), `config.json` (`cd8c0a19566f199b5c64da402f1d6a9daf80d094fe6536befb060a2cc59449c2`), `preprocessor_config.json` (`a34861a24e781942424ad790b82bc99348404a2e64ea882de88c40905851698d`). Pickle-formátum (`.bin`, `.pt`) nincs.
- **Licensz**: apache-2.0 a HF API cardData szerint (2026-10-20, nem gated); a súlyfájl saját licenc-fájlját és a betanító adat jogait NEM néztük. Ez a feltöltő által deklarált metaadat, nem a licenc szövege: terjesztés vagy más telepítés előtt újra kell nézni.

### onnxruntime (a NudeNet futtatója)
- **Forrás**: a PyPI `onnxruntime==1.30.0` wheel (`onnxruntime-1.30.0-cp314-cp314-macosx_14_0_arm64.whl`, sha256 `8b6169c16a48429890d2f4a0c774ebf54dfe9066a998514aad0518a16d398547`), a képgeneráló venv-ben `--no-deps --no-index --require-hashes` telepítve, OSV-ellenőrzés után. A `flatbuffers` függőség szándékosan hiányzik (csak a `tools` és a `quantization` modul importálja), ezért a `pip check` jelez.
- **Licensz**: MIT, Copyright (c) Microsoft Corporation (a wheel saját `onnxruntime/LICENSE` fájljából idézve); a wheelben `ThirdPartyNotices.txt` is van.
- **Használat**: csak `InferenceSession`, kizárólag a `CPUExecutionProvider`-rel, custom op nélkül.

## Koncepcionális hatás (nem becsomagolt kód)

### Mark Kashef -- Claude Code-alapú AI-asszisztens architektúra
- **Forrás**: https://youtube.com/@mark_kashef
- **Hol a Marveen-ben**: a Marveen alapkoncepciója (Claude Code mint folyamatosan futó AI-asszisztens, saját Telegram-csatornával, tmux-session-alapú headless működéssel, scheduled-task-okkal). A közösség a megközelítést "Claude Claw" / "ClaudeClaw" néven hivatkozza; a Marveen első verziója is ezen a néven indult (2026-04-08), nem fork, hanem a koncepció alapján nulláról felépített saját implementáció. A névváltás Marveen-re azután történt, hogy elegendő saját megoldás (memory tiers, kanban, channel-plugin, autonómia-config, multi-agent inter-agent messaging) került be ahhoz, hogy a projekt önálló identitást viseljen.

### Karpathy CLAUDE.md alapelvek
- **Forrás**: Andrej Karpathy CLAUDE.md útmutatása (publikus)
- **Hol a Marveen-ben**: a saját gyökér `CLAUDE.md` mintareferenciája. Nem másoltunk kódot; a felépítés és a szabály-stílus Karpathy mintájából inspirálódott.

### Matt Pocock -- "/handoff is my new favourite skill"
- **Forrás**: https://youtu.be/dtAJ2dOd3ko
- **Hol a Marveen-ben**: a "purpose" argumentum mint kötelező paraméter a `/handoff`-on, és a cross-agent portable design (hogy egy HANDOFF.md működjön Claude Code, Codex, Copilot CLI stb. között) Matt videós design-javaslataiból átvéve.

---

Ha hiányzó attribúciót észlelsz vagy korrekciót szeretnél, nyiss egy issue-t vagy PR-t: https://github.com/Szotasz/marveen.
