#!/usr/bin/env python3
"""PreToolUse gate (telegram reply + edit_message): the owner's private topics do not go to the team group.

Why: Patrik privát TG 14479 and group TG 2251 (2026-11-06, "az ssd ügyem nem marabel"): non-Marabel matters
(SSD, YouTube trial) appeared in the group, where Balázs reads too. On 2026-11-06 13:41 and 13:47 the private
Meta ad project (store/projektek.json, chat "privat") leaked into the group twice (shared/hibanaplo.md 13:52,
card 6dbeadad); an edit_message would have carried it the same way, so both tools are gated.

What blocks (exit 2): a message to the group chat whose text (or a file name) matches
  - a regex in store/privat-temak.json "minta" (an invalid regex is matched as plain text), or
  - a keyword (plain text) in store/projektek.json, "kulcsszavak" of every project with "chat": "privat"
    (the live list and the archive).
Matching is case-insensitive, over normalised text: NFKC, zero-width characters dropped, "-" and "_" read as a
space, whitespace collapsed (a no-break space in "12 500 Ft" matches; "meta_hirdetés" matches "Meta-hirdetés").
A keyword is a substring match, so suffixed forms match too; a keyword ending in a/e also matches the lengthened
á/é stem ("Meta" -> "Metában").
Wiring: .claude/settings.json PreToolUse, matcher "mcp__plugin_telegram_telegram__reply|...__edit_message"; the
test checks it (SETTINGS_JSON=<path> measures another copy, e.g. the live one).
Which chats are gated: every chat except the owner's private one (MARVEEN_OWNER_PRIVATE_CHAT, else
store/projektek.json elo_uzenet.privat): the group, and any other chat the bot writes to (Viktor 29635 INFO-3).
When the private chat is unknown, every chat is gated (fail-closed). Any error while matching blocks too
(Viktor 29635: an OverflowError from re.compile used to exit 1, which Claude Code does not treat as a block).
No chat id is written in this file: the ids are personal data.
Tests: private-topic-group-gate_test.py next to this file.
"""
import json
import os
import re
import sys
import unicodedata

ROOT = os.environ.get('CLAUDE_PROJECT_DIR', '/Users/klodel/marveen')
STORE = os.path.join(ROOT, 'store')
# The prod copy's fallback (2026-11-06) when store/privat-temak.json is missing or unreadable.
FALLBACK = [r'\bSSD', r'vidIQ', r'\bYT\b']


def load(name):
    try:
        with open(os.path.join(STORE, name), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


ZERO_WIDTH = dict.fromkeys(map(ord, '\u200b\u200c\u200d\u2060\ufeff\u00ad'))


def norm(text):
    text = unicodedata.normalize('NFKC', str(text)).translate(ZERO_WIDTH).replace('-', ' ').replace('_', ' ')
    return ' '.join(text.split()).casefold()


def patterns(temak, projektek):
    """(label, compiled regex) pairs: privat-temak.json regexes, then the private projects' keywords."""
    out = []
    raw = temak.get('minta') if isinstance(temak, dict) else None
    for p in (raw if isinstance(raw, list) else FALLBACK):
        p = str(p)
        try:
            out.append((p, re.compile(p, re.I)))
        except Exception:  # re.error, but also OverflowError/RecursionError (Viktor 29635)
            out.append((p, re.compile(re.escape(norm(p)))))
    if isinstance(projektek, dict):
        for key in ('projektek', 'archiv'):
            items = projektek.get(key)
            for proj in items if isinstance(items, list) else []:
                if not isinstance(proj, dict) or str(proj.get('chat', '')).lower() != 'privat':
                    continue
                words = proj.get('kulcsszavak')
                for w in words if isinstance(words, list) else []:
                    w = norm(w)
                    if not w:
                        continue
                    # A keyword is matched as a substring, so a suffixed form ("hirdetésben") is caught already. A final
                    # a/e lengthens before a suffix in Hungarian ("Meta" -> "Metában", "csatorna" -> "csatornán"), so
                    # both vowels match there (Klodel 30145, card 6dbeadad).
                    rx = re.escape(w[:-1]) + {'a': '[aá]', 'e': '[eé]'}[w[-1]] if w[-1] in 'ae' else re.escape(w)
                    out.append((f'{proj.get("id", "?")}: {w}', re.compile(rx)))
    return out


def gated(chat, projektek):
    elo = projektek.get('elo_uzenet') if isinstance(projektek, dict) else None
    elo = elo if isinstance(elo, dict) else {}
    # The live store keeps each chat as {"chat_id": ..., "message_id": ...} (the status card's message); a plain id
    # is read too. Reading the dict as text made no chat private, so the owner's own chat was gated (2026-11-06).
    priv = elo.get('privat')
    if isinstance(priv, dict):
        priv = priv.get('chat_id')
    private = (os.environ.get('MARVEEN_OWNER_PRIVATE_CHAT') or str(priv if priv is not None else '')).strip()
    return not private or chat != private


def main():
    try:
        ti = json.load(sys.stdin).get('tool_input') or {}
    except Exception:
        return 0
    if not isinstance(ti, dict):
        return 0
    projektek = load('projektek.json')
    if not gated(str(ti.get('chat_id') or '').strip(), projektek):
        return 0
    files = ti.get('files')
    text = str(ti.get('text') or '') + ' ' + ' '.join(map(str, files if isinstance(files, list) else []))
    try:
        plain = norm(text)
        hits = [label for label, rx in patterns(load('privat-temak.json'), projektek) if rx.search(text) or rx.search(plain)]
    except Exception as e:  # fail-closed: no error may switch the gate off (Viktor 29635)
        hits = [f'a kapu hibára futott ({e.__class__.__name__}), ezért blokkol']
    if hits:
        sys.stderr.write(
            f'PRIVÁT-TÉMA-KAPU: privát téma a csoportban: {hits}. Patrik privát ügyei (nem-Marabel ügyek, a "privat" '
            'projektek, pl. a fizetett hirdetés) csak a privát chatbe mehetnek (TG 14479/2251, hibanapló 11-06 13:52). '
            'Vedd ki a szövegből, vagy küldd privátba. Hamis találatnál: store/privat-temak.json, ill. a projekt '
            '"kulcsszavak" listája a store/projektek.json-ban.\n')
        return 2
    return 0


if __name__ == '__main__':
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from gate_log import watch as _gate_log_watch  # one line per block, store/gate-blocks.jsonl (Klodel 35878)
    except Exception:
        from contextlib import nullcontext as _gate_log_watch
    with _gate_log_watch('private-topic'):
        sys.exit(main())
