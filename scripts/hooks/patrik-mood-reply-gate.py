#!/usr/bin/env python3
"""PreToolUse gate (telegram reply, edit_message): no laughing in Patrik's chats while Patrik is upset.

Why (Klodel 48551; hibanapló 2026-11-20, the same class the THIRD time: 2026-11-09 TG 3479, 2026-11-11 TG 5436
"faszt vigyorogsz", 2026-11-20 TG 6629 "még sosem voltál szánalmasabb ennél"): after Patrik's frustrated lines in
the team group (TG 6615, 6617) the main agent sent joke lines with 😄 as replies. react-emoji-gate.py catches a
REACTION only, not the text of a reply.

What blocks (exit 2, one message naming the signals and the TG number of Patrik's line, never his text), for a
reply or an edit into one of the owner's chats (store/projektek.json elo_uzenet "privat" / "csoport", or
MARVEEN_OWNER_CHATS; the same lookup as react-emoji-gate.py):
  1. the text laughs: a FACE emoji (the ranges in FACES: U+1F600-1F64F, 1F910-1F92F, 1F970-1F97A, 1FAE0-1FAE8,
     1F638-1F640) or 🐷, compared after NFC with variation selectors, zero-width and bidi marks and skin tones
     dropped; or a laughing word on its own: lol, haha, hehe, xd, :D, ;) (accents and case ignored). Content emoji
     (🎙 📖 🎁 ✨ 🤍 🌙) and status marks pass: Klodel 48590 on the replay (9 days, 33 replies with a signal under a
     full allowlist, 17 blocked, 13 of them content emoji in post drafts, not laughs);
  2. AND Patrik wrote a frustrated line within the last MOOD_WINDOW_S seconds, in any chat: a message of his
     (user id = his private chat id, store/projektek.json elo_uzenet.privat or MARVEEN_OWNER_PRIVATE_CHAT) in
     <state>/inbound-evidence.jsonl (text, at) joined with <state>/inbound-senders.jsonl (user id) on chat and
     message id, whose text (accents and case ignored) holds a word of FRUSTRATION (stems, from the start of a
     word) or of the extension file store/frusztracio-szavak.txt (one plain stem per line, # comments; plain
     text, not a regex). <state> is TELEGRAM_STATE_DIR, else <install>/.claude/channels/telegram.
Without a frustrated line in the window the text is not judged (a joke is fine on a calm day; CLAUDE.md "Légkör").
frustrated_line() is also patrik-reply-volume-gate.py's rule 3 condition (Klodel 48590): one definition of "upset".
Anything unreadable (payload, logs, owner id) passes: the gate must not block an unrelated reply. NOT MODELLED: a
laugh in other words ("vicces", "röhej"), an image or sticker, frustration without a listed word, a message the
plugin did not log.
Wiring: .claude/settings.json PreToolUse, matcher "mcp__plugin_telegram_telegram__reply|..._edit_message" (main
agent only). No chat or user id is written in this file. Tests: patrik-mood-reply-gate_test.py next to this file.
"""
import json
import os
import re
import sys
import time
import unicodedata

ROOT = os.environ.get('CLAUDE_PROJECT_DIR') or os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.realpath(__file__))))
STORE = os.path.join(ROOT, 'store')
MOOD_WINDOW_S = 60 * 60

# Laughing emoji (Klodel 48590): the face ranges and the pig; every other emoji passes.
FACES = ((0x1F600, 0x1F64F), (0x1F910, 0x1F92F), (0x1F970, 0x1F97A), (0x1FAE0, 0x1FAE8), (0x1F638, 0x1F640))
PIG = 0x1F437
DROP = dict.fromkeys([0xFE0E, 0xFE0F, 0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD, 0x200E, 0x200F,
                      *range(0x202A, 0x202F), *range(0x2066, 0x206A), *range(0x1F3FB, 0x1F400)])
LAUGH_WORD = re.compile(r'(?<![a-z0-9])(?:l+o+l+|ha(?:ha)+h?|he(?:he)+|x+d+)(?![a-z0-9])'
                        r'|(?:^|(?<=\s))(?::-?d+|;-?\)+|;-?d+)(?=$|[\s.,!?])')
# Stems, matched from the start of a word in the folded text (Klodel 48551's list). "szar" leaves out the words
# that only start with it: származ-, száraz, szarv-, szárny-, szárd-, szárít-.
FRUSTRATION = [r'szanalmas', r'hulladek', r'behany', r'idiot', r'fasz', r'szar(?!maz|az|v|ny|d|it|u)', r'basztat',
               r'spammel', r'hasztalan', r'ostobasag']


def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(text or ''))
                   if not unicodedata.combining(c) and unicodedata.category(c) != 'Cf').lower()


def is_laugh_emoji(ch):
    o = ord(ch)
    return o == PIG or any(lo <= o <= hi for lo, hi in FACES)


def laugh_signals(text):
    """The laughing signals of a text: face emoji and 🐷, then laughing words, in order, without repeats."""
    out = []
    for ch in unicodedata.normalize('NFC', str(text or '')).translate(DROP):
        if is_laugh_emoji(ch) and ch not in out:
            out.append(ch)
    for m in LAUGH_WORD.finditer(fold(text)):
        if m.group(0) not in out:
            out.append(m.group(0))
    return out


def owner_chats():
    env = os.environ.get('MARVEEN_OWNER_CHATS')
    if env:
        return {c.strip() for c in env.split(',') if c.strip()}
    out = set()
    for key in ('privat', 'csoport'):
        v = _elo().get(key)
        if isinstance(v, dict):
            v = v.get('chat_id')
        if v is not None and str(v).strip():
            out.add(str(v).strip())
    return out


def _elo():
    try:
        with open(os.path.join(STORE, 'projektek.json'), encoding='utf-8') as f:
            elo = json.load(f).get('elo_uzenet')
        return elo if isinstance(elo, dict) else {}
    except Exception:
        return {}


def owner_user_id():
    env = os.environ.get('MARVEEN_OWNER_PRIVATE_CHAT', '').strip()
    if env:
        return env
    v = _elo().get('privat')
    v = v.get('chat_id') if isinstance(v, dict) else v
    return str(v).strip() if v is not None and str(v).strip().isdigit() else None


def frustration_rx():
    stems = list(FRUSTRATION)
    try:
        with open(os.path.join(STORE, 'frusztracio-szavak.txt'), encoding='utf-8') as f:
            for ln in f:
                ln = fold(ln.split('#', 1)[0]).strip()
                if ln:
                    stems.append(re.escape(ln))
    except OSError:
        pass
    return re.compile(r'(?<![a-z0-9])(?:' + '|'.join(stems) + ')')


def _rows(state, name):
    for path in (os.path.join(state, name + '.1'), os.path.join(state, name)):
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                for ln in f:
                    try:
                        row = json.loads(ln)
                    except ValueError:
                        continue
                    if isinstance(row, dict):
                        yield row
        except OSError:
            continue


def frustrated_line(now=None):
    """The TG message id of Patrik's latest frustrated line within MOOD_WINDOW_S, or None."""
    owner = owner_user_id()
    if not owner:
        return None
    now = time.time() if now is None else now
    state = os.environ.get('TELEGRAM_STATE_DIR') or os.path.join(ROOT, '.claude', 'channels', 'telegram')
    mine = {(str(r.get('chat_id')), str(r.get('message_id'))) for r in _rows(state, 'inbound-senders.jsonl')
            if str(r.get('user_id')) == owner}
    rx = frustration_rx()
    best = None
    for r in _rows(state, 'inbound-evidence.jsonl'):
        try:
            at = float(r.get('at')) / 1000.0
        except (TypeError, ValueError):
            continue
        key = (str(r.get('chat_id')), str(r.get('message_id')))
        if 0 <= now - at <= MOOD_WINDOW_S and key in mine and rx.search(fold(r.get('text'))):
            if best is None or at > best[0]:
                best = (at, key[1])
    return best[1] if best else None


def main():
    try:
        payload = json.load(sys.stdin)
        ti = payload.get('tool_input') or {}
    except Exception:
        return 0
    if not isinstance(ti, dict):
        return 0
    tool = str(payload.get('tool_name') or '')
    if tool and not (tool.endswith('__reply') or tool.endswith('__edit_message')):
        return 0
    chat = str(ti.get('chat_id') or '').strip()
    chats = owner_chats()
    if not chats or chat not in chats:
        return 0
    signals = laugh_signals(ti.get('text'))
    if not signals:
        return 0
    try:
        tg = frustrated_line()
    except Exception:
        return 0
    if tg is None:
        return 0
    sys.stderr.write(f'HUMOR-KAPU (Klodel 48551; Patrik TG 6629 "még sosem voltál szánalmasabb", TG 5436 "faszt '
                     f'vigyorogsz"): Patrik az elmúlt {MOOD_WINDOW_S // 60} percben frusztrált volt (TG {tg}), ebbe a '
                     f'chatbe most nem mehet nevetés: {" ".join(signals)}. Írd tárgyszerűen, poén nélkül.\n')
    return 2


if __name__ == '__main__':
    sys.exit(main())
