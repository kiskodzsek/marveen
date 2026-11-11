#!/usr/bin/env python3
"""PreToolUse gate (telegram reply + edit_message): no to-do steps put on Balázs.

Why: Patrik group TG 4910 (2026-11-11 09:54): "megint hülyeségeket találsz ki balázsnak nem kértem hogy basztasd
random, sőt". Klodel had sent Balázs a numbered Google Cloud step list (TG 4864) because a stale card said
"VÁR: Balázs". Second occurrence after TG 3428 (TikTok code, "random basztatás"); the memory note alone did not stop it.

What blocks (exit 2): a reply/edit whose text names Balázs AND carries a task shape (numbered steps, "vár rád",
"teendő", "lépés", "csináld", "kérlek ... Balázs"). Allowed only with a line "BALAZS-OK: <Patrik TG szám>" that cites
Patrik's own assignment. Text is accent-folded and case-folded before matching.
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


TASK = [
    re.compile(r'(?m)^\s*[1-9]\.\s'),
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
    if re.search(r'(?m)^\s*balazs ok:\s*\S', t.replace('-', ' ')):
        return None
    if any(rx.search(t) for rx in TASK):
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
    ti = payload.get('tool_input') or {}
    msg = check(ti.get('text', '')) or check_pr(ti.get('text', ''))
    if msg:
        print(msg, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
