#!/usr/bin/env python3
"""English homographs in the accent check of scripts/hooks/outgoing-copy-gate.py.

Why (2026-10-12, Klodel): the gate blocked a correct Telegram reply twice,
because "all users" read as the accent-stripped Hungarian "áll". Patrik's rule
is that technical terms stay in English inside Hungarian sentences. The fix
masks "all" and "level" only in an English context (an unambiguous English
neighbour word, or quotes); the accent-stripped Hungarian "áll"/"levél" must
still block. Both halves are pinned here, on the tokenizer and end to end.
Run:
  python3 scripts/__tests__/outgoing-copy-gate-english-homographs.test.py
Exit 0 = all pass; non-zero = a failure (message on stderr).
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(os.path.dirname(HERE), "hooks", "outgoing-copy-gate.py")

spec = importlib.util.spec_from_file_location("outgoing_copy_gate", HOOK)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

FAILS = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" ({detail})" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def accent_hits(text):
    return [w for w, _ in gate.accent_check_tokens(text) if w in gate.ACCENTLESS]


def run_hook(text, rules_file):
    env = dict(os.environ, OUTGOING_COPY_GATE_RULES=rules_file)
    payload = {"tool_name": "mcp__plugin_telegram_telegram__reply", "tool_input": {"chat_id": "0", "text": text}}
    p = subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=20)
    return p.returncode, p.stderr


# English context: must NOT be an accent hit.
ENGLISH = [
    "all users",
    "Ez minden all users-re vonatkozik.",
    "all, users",
    "access level",
    "log level debug",
    'A kulcs neve "all".',
    "„level” a mező neve.",
]
# Hungarian prose without accents: must STILL be a hit.
HUNGARIAN = [
    ("A szerver nem all le.", "all"),
    ("nem all be", "all"),
    ("Ugy all a dolog.", "all"),
    ("a level megjott", "level"),
    ("az all. Users", "all"),  # a sentence break is not an English neighbour
]


def main():
    print("tokenizer: English context is masked")
    for text in ENGLISH:
        hits = accent_hits(text)
        check(f"{text!r} has no all/level hit", not ({"all", "level"} & set(hits)), f"hits={hits}")

    print("tokenizer: accent-stripped Hungarian still hits")
    for text, word in HUNGARIAN:
        hits = accent_hits(text)
        check(f"{text!r} still flags {word!r}", word in hits, f"hits={hits}")

    print("the context list holds no common Hungarian word")
    for word in ("is", "be", "a", "az", "el", "le", "meg", "ki", "at", "to", "on", "in", "fel", "ne"):
        check(f"{word!r} is not English context", word not in gate.ENGLISH_CONTEXT)

    print("end to end, Telegram reply")
    with tempfile.TemporaryDirectory() as tmp:
        rules = os.path.join(tmp, "rules.json")
        with open(rules, "w", encoding="utf-8") as fh:
            json.dump({"bad_name_patterns": [r"\bTeszt[- ]?Elek\b"], "correction": "a helyes alak: Teszt Elemér"}, fh)
        ok_text = "Szia! A jogosultság most all users szinten van, a log level pedig debug. Holnap átnézem."
        code, err = run_hook(ok_text, rules)
        check("a correct Hungarian reply with 'all users' and 'log level' passes (exit 0)", code == 0, err.strip()[:300])
        bad_text = "Szia! A jogosultság rendben van, a szolgáltatás nem all le, holnap átnézem."
        code, err = run_hook(bad_text, rules)
        check("'nem all le' still blocks (exit 2)", code == 2, err.strip()[:300])
        check("and names the missing accent", "HIANYZO EKEZETEK" in err and "all -> áll" in err, err.strip()[:300])

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {FAILS}", file=sys.stderr)
        sys.exit(1)
    print("\nALL PASSED")


if __name__ == "__main__":
    main()
