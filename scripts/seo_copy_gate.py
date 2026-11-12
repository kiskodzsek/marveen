#!/usr/bin/env python3
"""seo_copy_gate.py -- the owner's page-level wording rules, checked against the final SEO title/H1 set.

Why (hibanapló 2026-11-12 10:06, Klodel 39141, card 2994d805): the seven-page title/H1 set (Marabel #1287)
passed three reviews while the /elso-eved H1 did not carry the owner's difference sentence ("több mint egy
babanapló", Patrik TG 17921) and the /marabello title narrowed a four-option product to one occasion
("anyák napi"). The owner's words lived in a chat message; no check read them. This gate does.

Usage: seo_copy_gate.py <title-h1-vegleges.json> <patrik-kotelezo.json>
  copy file:  {"/page": {"title": "...", "h1": "...", "first_sentence": "..."}, ...}
  rules file: {"/page": {"h1_kotelezo": [RULE...], "tiltott": [RULE...]}, ...}
     RULE = {"kifejezes": "...", "forras": "Patrik TG <n> ...", "mezok": ["h1", "title", ...]}
     mezok defaults: h1_kotelezo -> ["h1"], tiltott -> ["title", "h1", "first_sentence"].
Matching: case-insensitive, NFC, whitespace collapsed; a phrase matches at a word start and may carry a
suffix (the rule "anyák nap" catches "anyák napi", "Anyák napjára"; "anyának" does not catch "nagyanyának").
Exit: 0 all rules hold; 1 a rule is broken (one line each); 2 a malformed rules or copy file (fail-closed:
an unknown key, a rule without a TG source, a ruled page missing from the copy file); 64 usage.
"""
import json
import re
import sys
import unicodedata

FIELDS = ("title", "h1", "first_sentence")
DEFAULT_FIELDS = {"h1_kotelezo": ["h1"], "tiltott": ["title", "h1", "first_sentence"]}
SOURCE_RX = re.compile(r"\bTG\s*\d+")


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(s))).strip().casefold()


def contains(text, phrase):
    # a word start before the phrase; the end is open, so a Hungarian suffix still matches
    return re.search(r"(?<!\w)" + re.escape(norm(phrase)), norm(text)) is not None


class Malformed(Exception):
    pass


def load_rules(rules):
    if not isinstance(rules, dict) or not rules:
        raise Malformed("rules: not a non-empty object")
    out = {}
    for page, spec in rules.items():
        if not isinstance(page, str) or not page.startswith("/"):
            raise Malformed(f"rules: page key {page!r} is not a path")
        if not isinstance(spec, dict):
            raise Malformed(f"rules {page}: not an object")
        unknown = set(spec) - set(DEFAULT_FIELDS)
        if unknown:
            raise Malformed(f"rules {page}: unknown key(s) {sorted(unknown)}")
        for kind in DEFAULT_FIELDS:
            for i, r in enumerate(spec.get(kind, [])):
                if not isinstance(r, dict) or not isinstance(r.get("kifejezes"), str) or not r["kifejezes"].strip():
                    raise Malformed(f"rules {page} {kind}[{i}]: no kifejezes")
                if not isinstance(r.get("forras"), str) or not SOURCE_RX.search(r["forras"]):
                    raise Malformed(f"rules {page} {kind}[{i}]: forras must name the owner's message (TG <n>)")
                fields = r.get("mezok", DEFAULT_FIELDS[kind])
                if not isinstance(fields, list) or not fields or any(f not in FIELDS for f in fields):
                    raise Malformed(f"rules {page} {kind}[{i}]: mezok must be a subset of {list(FIELDS)}")
                out.setdefault(page, []).append((kind, r["kifejezes"], r["forras"], fields))
    return out


def check(copy, rules):
    """Returns the list of broken-rule lines (empty = pass). Raises Malformed on a bad input."""
    if not isinstance(copy, dict):
        raise Malformed("copy: not an object")
    parsed = load_rules(rules)
    broken = []
    for page, items in parsed.items():
        entry = copy.get(page)
        if not isinstance(entry, dict):
            raise Malformed(f"copy: ruled page {page} is missing")
        for kind, phrase, source, fields in items:
            source = source.split(":")[0].strip()  # "Patrik TG 17921": the full quote stays in the rules file
            for f in fields:
                text = entry.get(f)
                if not isinstance(text, str):
                    raise Malformed(f"copy {page}: field {f} missing")
                hit = contains(text, phrase)
                if kind == "h1_kotelezo" and not hit:
                    broken.append(f"{page} {f}: hiányzik a kötelező „{phrase}” ({source}); most: „{text}”")
                if kind == "tiltott" and hit:
                    broken.append(f"{page} {f}: tiltott „{phrase}” ({source}); most: „{text}”")
    return broken


def main(argv):
    if len(argv) != 3:
        print("usage: seo_copy_gate.py <title-h1-vegleges.json> <patrik-kotelezo.json>", file=sys.stderr)
        return 64
    try:
        with open(argv[1], encoding="utf-8") as fh:
            copy = json.load(fh)
        with open(argv[2], encoding="utf-8") as fh:
            rules = json.load(fh)
        broken = check(copy, rules)
    except (OSError, json.JSONDecodeError, Malformed) as e:
        print(f"seo-copy-gate: REFUSED (fail-closed): {e}", file=sys.stderr)
        return 2
    if broken:
        print(f"seo-copy-gate: BUKIK, {len(broken)} szabály sérül:")
        for line in broken:
            print("  - " + line)
        return 1
    print(f"seo-copy-gate: OK ({sum(len(v) for v in load_rules(rules).values())} szabály, {len(load_rules(rules))} oldal)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
