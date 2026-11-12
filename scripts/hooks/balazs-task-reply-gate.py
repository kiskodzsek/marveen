#!/usr/bin/env python3
"""PreToolUse gate (telegram reply + edit_message): no to-do steps put on Balázs.

Why: Patrik group TG 4910 (2026-11-11 09:54): "megint hülyeségeket találsz ki balázsnak nem kértem hogy basztasd
random, sőt". Klodel had sent Balázs a numbered Google Cloud step list (TG 4864) because a stale card said
"VÁR: Balázs". Second occurrence after TG 3428 (TikTok code, "random basztatás"); the memory note alone did not stop it.

What blocks (exit 2): a reply/edit whose text names Balázs AND carries a task shape ("vár rád", "teendő", "lépés",
"csináld", "kérlek", or numbered steps WITH a task verb such as "lépj be", "nézd meg", "töltsd fel", "megnéznéd").
A numbered list without a task verb is a result list for him, not a task (Klodel 39569). Allowed only with a line "BALAZS-OK: <Patrik TG szám>" that cites
Patrik's own assignment. The value must be a TG number ("BALAZS-OK: TG 4864", "Patrik" before it is fine): a
line with any other value does not count (Viktor 38148 L1). Text is accent-folded and case-folded before matching.
Wiring: .claude/settings.json PreToolUse, matcher "mcp__plugin_telegram_telegram__reply|...__edit_message".
"""
import json
import re
import sys
import unicodedata


def norm(text):
    text = unicodedata.normalize('NFKC', str(text))
    text = ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))
    return text.casefold()


# Klodel 39569 (Patrik TG 18102 "nagyon lassú vagy"): "Balázs, a cápás keresés eredménye ... 1. Scholly ..." was a
# result for him, not a task, and the numbered list alone blocked it. A numbered list is a task shape only together
# with a task verb (imperative or a 2nd-person "would you" form). A task verb alone adds no block: measured on Klodel's
# group texts of 7 days (1297), that would have blocked 19 more, many false ("nem neked kell", a text to Patrik
# naming "Tasnádi Balázs,"), the opposite of the request.
TASK_VERB = re.compile(
    r'\b(?:csinald|nezd|nezz|kuldd|kuldj|toltsd|tolts|kattints|lepj|ird|irj|add meg|allitsd|allits|hozd|hozz|menj|'
    r'nyisd|nyiss|jelentkezz|telepitsd|telepits|masold|hivd|intezd|ellenorizd|ellenorizz|keresd|regisztralj|valaszolj|'
    r'fogadd|hagyd|engedelyezd|oszd meg|vedd fel|kerdezd|probald|nyomd|jovahagyd|szolj|irasd|toltsd fel|tedd)\b'
    r'|\blegyszi\b|\bszukseg van rad\b|\bneked kell\b')
# "megnéznéd", "feltöltenéd": matched WITH accents (casefolded only), so English "signed"/"learned" do not hit.
TASK_COND = re.compile(r'\b\w{3,}n[áé]d\b')
NUMBERED = re.compile(r'(?m)^\s*[1-9]\.\s')
TASK = [
    re.compile(r'\bvar rad\b'),
    re.compile(r'\bteendo'),
    re.compile(r'\blepes'),
    re.compile(r'\bcsinald\b'),
    re.compile(r'\bkerlek\b'),
]


def check(text):
    t = norm(text)
    # Csak a Balázsnak SZÓLÓ szöveg (megszólítás), nem az, ami csak említi (pl. "Balázs tesztje" az állapot-üzenetben).
    if not re.search(r'(?m)^\s*balazs\b|\bbalazs,|\bbalazs:|\bbalazsnak\b', t):
        return None
    if re.search(r'(?m)^\s*balazs ok:\s*(?:patrik\s+)?tg\s*#?\s*\d+', t.replace('-', ' ')):
        return None
    verb = TASK_VERB.search(t) or TASK_COND.search(unicodedata.normalize('NFKC', str(text)).casefold())
    if any(rx.search(t) for rx in TASK) or (NUMBERED.search(t) and verb):
        return ('BALAZS-KAPU (Patrik TG 4910: "nem kértem hogy basztasd random"): Balázsra feladatot/lépést csak '
                'Patrik kifejezett kiosztására teszel; ilyenkor egy sor: "BALAZS-OK: <Patrik TG szám>". '
                'Ami a táblán "VÁR: Balázs", az előbb Patrikhoz megy kérdésként, nem Balázshoz.')
    return None


PR_ASK = re.compile(r'\bpr\s*#\s*\d+')
GO_ASK = re.compile(r'\bmehet\b.*\?|\belesbe\?')


def check_pr(text):
    """Patrik TG 4910/4917 (2026-11-11): "nem kértem ... nem kell ez a sok szar modositas" -- a PR élesítési kérdése
    csak akkor mehet Patrik elé, ha Patrik maga kérte a változást: egy sor "PATRIK-KERTE: TG <szám>" a saját kérésével."""
    t = norm(text)
    if PR_ASK.search(t) and GO_ASK.search(t) and not re.search(r'(?m)^\s*patrik.kerte:\s*tg\s*\d+', t):
        return ('PR-KÉRÉS-KAPU (Patrik TG 4917: "nem kell ez a sok szar modositas"): PR élesítését csak Patrik saját '
                'kérésére kérdezed; írd bele: "PATRIK-KERTE: TG <a kérése>". Ha nincs ilyen, a PR nem megy elé.')
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    ti = payload.get('tool_input') if isinstance(payload, dict) else None
    if not isinstance(ti, dict):
        return 0
    msg = check(ti.get('text', '')) or check_pr(ti.get('text', ''))
    if msg:
        print(msg, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
