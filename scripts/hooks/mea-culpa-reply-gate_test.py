#!/usr/bin/env python3
"""Tests for mea-culpa-reply-gate.py (Klodel 34240, Patrik group TG 3795).

Runs the hook as Claude Code does (JSON on stdin; exit 0 allow, 2 block) against a throw-away
CLAUDE_PROJECT_DIR with synthetic chat ids and a synthetic store: the live store is never read.
Run: python3 -I scripts/hooks/mea-culpa-reply-gate_test.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mea-culpa-reply-gate.py')
GROUP = '-1000000000001'  # synthetic
PRIV = '5040302010'       # synthetic
OTHER = '7777777'         # synthetic, not an owner chat
PROJEKTEK = {'elo_uzenet': {'csoport': {'chat_id': GROUP, 'message_id': 1}, 'privat': PRIV}}


def setup(root, projektek=PROJEKTEK):
    store = os.path.join(root, 'store')
    os.makedirs(store, exist_ok=True)
    if projektek is not None:
        with open(os.path.join(store, 'projektek.json'), 'w', encoding='utf-8') as f:
            f.write(projektek if isinstance(projektek, str) else json.dumps(projektek, ensure_ascii=False))


def run(root, tool_input, env_extra=None, raw=None, tool=None):
    env = {'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root, **(env_extra or {})}
    body = {'tool_input': tool_input}
    if tool:
        body['tool_name'] = 'mcp__plugin_telegram_telegram__' + tool
    payload = raw if raw is not None else json.dumps(body)
    p = subprocess.run([sys.executable, '-I', HOOK], input=payload, capture_output=True, text=True, env=env, timeout=20)
    return p.returncode, p.stderr


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def blocks_each_listed_phrase_in_both_owner_chats(root):
    setup(root)
    texts = ['Igazad van, ezt elnéztem.', 'Jogos.', 'Hibáztam a briefnél.', 'Ez az én hibám volt.',
             'Ki kellett volna szúrnom.', 'Ezentúl mindig megnézem.', 'Jogosan szólsz.', 'Igazatok van.',
             'Hibáztunk.', 'A mi hibánk.', 'Kellett volna kiszúrnom.', 'Ki kellett volna szúrni.']
    return all(run(root, {'chat_id': chat, 'text': t})[0] == 2 for chat in (GROUP, PRIV) for t in texts)


@case
def blocks_unaccented_upper_and_spaced_forms(root):
    setup(root)
    texts = ['igazad van', 'HIBAZTAM', 'az en hibam', 'ezentul igy lesz', 'ki  kellett\nvolna szurnom',
             'igazad van', 'iga​zad van', 'az én-hibám']
    return all(run(root, {'chat_id': GROUP, 'text': t})[0] == 2 for t in texts)


@case
def message_is_one_line_and_names_the_memory(root):
    setup(root)
    rc, err = run(root, {'chat_id': PRIV, 'text': 'Igazad van, ezentúl figyelek.'})
    lines = err.strip().splitlines()
    return rc == 2 and len(lines) == 1 and 'no-mea-culpa-replies' in err and 'igazad van' in err and 'ezentúl' in err


@case
def clean_result_messages_pass(root):
    setup(root)
    texts = ['Kész: PR #1236 új fej ee88105c, Pulzus éjjel élesíti.',
             'A jogosultság beállítva, a csak-olvasó kulcs él.',  # "jogos" inside a longer word
             'Az igazolás megvan, a hiba oka a lastmod volt.',
             'Holnap 9-kor jön a következő kép.',
             '']
    return all(run(root, {'chat_id': GROUP, 'text': t})[0] == 0 for t in texts)


@case
def other_chat_is_not_gated(root):
    setup(root)
    return run(root, {'chat_id': OTHER, 'text': 'Igazad van, hibáztam.'})[0] == 0


@case
def edit_message_payload_is_gated_the_same(root):
    setup(root)
    return run(root, {'chat_id': GROUP, 'message_id': '42', 'text': 'Jogos, az én hibám.'})[0] == 2


@case
def unknown_chats_gate_everything(root):
    # No store, a broken store, or a store without the two chats: every chat is gated (fail-closed).
    no_store = run(root, {'chat_id': OTHER, 'text': 'Igazad van.'})[0] == 2
    setup(root, projektek='{not json')
    broken = run(root, {'chat_id': OTHER, 'text': 'Igazad van.'})[0] == 2
    setup(root, projektek={'elo_uzenet': {}})
    empty = run(root, {'chat_id': OTHER, 'text': 'Igazad van.'})[0] == 2
    clean = run(root, {'chat_id': OTHER, 'text': 'Kész.'})[0] == 0
    return no_store and broken and empty and clean


@case
def env_override_names_the_owner_chats(root):
    setup(root)
    env = {'MARVEEN_OWNER_CHATS': f'{OTHER}, 123'}
    return (run(root, {'chat_id': OTHER, 'text': 'Igazad van.'}, env)[0] == 2
            and run(root, {'chat_id': GROUP, 'text': 'Igazad van.'}, env)[0] == 0)


# Klodel 38198 (hibanapló 11-11 17:02): "PLACEHOLDER" edit_message on the group's live status message.
@case
def placeholder_blocked_in_every_chat(root):
    setup(root)
    texts = ['PLACEHOLDER', 'placeholder', 'Új ötlet: PLACEHOLDER', 'TODO', '  tbd. ', '[TODO] részletek', 'Ár: TBD',
             'Határidő: XXX', 'Lorem ipsum dolor sit amet', 'Szia {{nev}}!', '<PLACEHOLDER>', '✅ TODO', 'PLACE​HOLDER']
    res = [run(root, {'chat_id': chat, 'text': t}, tool='reply') for chat in (GROUP, PRIV, OTHER) for t in texts]
    return all(rc == 2 and 'PLACEHOLDER-KAPU' in err for rc, err in res)


@case
def soft_hyphen_blocked_in_every_chat(root):
    # Klodel 38201: U+00AD went out twice on 2026-11-11 (TG 17568, 5477). A ZWJ emoji (U+200D) is not affected.
    setup(root)
    res = [run(root, {'chat_id': chat, 'text': 'Kész: a recept\u00adkönyv minta elkészült.'}, tool=tool)
           for chat in (GROUP, OTHER) for tool in ('reply', 'edit_message')]
    family = run(root, {'chat_id': GROUP, 'text': 'Család: 👨\u200d👩\u200d👧 kész a fotó.'}, tool='reply')[0]
    return all(rc == 2 and 'U+00AD' in err for rc, err in res) and family == 0


@case
def placeholder_word_in_prose_passes(root):
    setup(root)
    texts = ['3 TODO maradt a kódban, holnap zárom.', 'A placeholder szót mostantól a kapu fogja.',
             'XXL póló készült, 12 db.', 'A TBD státuszú kártyákat Klodel rendezi.', 'Kész: PR #187, TODO-lista üres.',
             'Ár: 4 990 Ft', '📊 ÉLŐ ÁLLAPOT · frissítve 17:05\n\nMarabel: 3 rendelés']
    return all(run(root, {'chat_id': GROUP, 'text': t}, tool='reply')[0] == 0 for t in texts)


@case
def short_edit_blocked_short_reply_not(root):
    setup(root)
    return (run(root, {'chat_id': OTHER, 'message_id': '7', 'text': 'Dolgozom…'}, tool='edit_message')[0] == 2
            and run(root, {'chat_id': OTHER, 'message_id': '7', 'text': ' '}, tool='edit_message')[0] == 2
            and run(root, {'chat_id': OTHER, 'text': 'Kész.'}, tool='reply')[0] == 0
            and run(root, {'chat_id': OTHER, 'message_id': '7', 'text': 'Kész: a kép elkészült, 2 db.'},
                    tool='edit_message')[0] == 0)


@case
def live_status_edit_needs_the_head(root):
    setup(root, projektek={'elo_uzenet': {'csoport': {'chat_id': GROUP, 'message_id': '1869'},
                                          'privat': {'chat_id': PRIV, 'message_id': 55}}})
    bad = [run(root, {'chat_id': GROUP, 'message_id': '1869', 'text': 'Frissítés: minden rendben, 3 rendelés.'},
               tool='edit_message'),
           run(root, {'chat_id': int(PRIV), 'message_id': 55, 'text': 'Frissítés: minden rendben, 3 rendelés.'},
               tool='edit_message')]
    good = [run(root, {'chat_id': GROUP, 'message_id': '1869', 'text': '📊 ÉLŐ ÁLLAPOT · frissítve 17:05\n\nx'},
                tool='edit_message'),
            run(root, {'chat_id': PRIV, 'message_id': '55', 'text': 'ÉLŐ ÁLLAPOT · frissítve 17:05, minden rendben'},
                tool='edit_message'),
            # another message in the same chat, and a reply to the live message, are not the live edit
            run(root, {'chat_id': GROUP, 'message_id': '1870', 'text': 'Frissítés: minden rendben, 3 rendelés.'},
                tool='edit_message'),
            run(root, {'chat_id': GROUP, 'reply_to': '1869', 'text': 'Frissítés: minden rendben, 3 rendelés.'},
                tool='reply')]
    return (all(rc == 2 and 'ELO-ALLAPOT-KAPU' in err for rc, err in bad)
            and all(rc == 0 for rc, _ in good))


@case
def live_status_check_without_store_ids_passes(root):
    setup(root)  # PROJEKTEK names chat ids but the privat entry has no message_id
    return run(root, {'chat_id': PRIV, 'message_id': '55', 'text': 'Frissítés: minden rendben, 3 rendelés.'},
               tool='edit_message')[0] == 0


@case
def malformed_payload_is_allowed(root):
    setup(root)
    return (run(root, None, raw='not json')[0] == 0
            and run(root, None, raw=json.dumps({'tool_input': 'x'}))[0] == 0)


@case
def settings_wire_gate_on_reply_and_edit_message(root):
    # SETTINGS_JSON=<path> measures another copy (e.g. the live one).
    path = os.environ.get('SETTINGS_JSON') or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HOOK))),
                                                           '.claude', 'settings.json')
    entries = json.load(open(path, encoding='utf-8')).get('hooks', {}).get('PreToolUse', [])

    def wired(tool):
        for e in entries:
            m = e.get('matcher')
            if m and re.fullmatch(m, tool) and any('mea-culpa-reply-gate.py' in str(h.get('command', ''))
                                                   for h in e.get('hooks', [])):
                return True
        return False
    return all(wired(t) for t in ('mcp__plugin_telegram_telegram__reply', 'mcp__plugin_telegram_telegram__edit_message'))


def main():
    bad = 0
    for fn in CASES:
        with tempfile.TemporaryDirectory() as root:
            ok = fn(root)
        print(('PASS ' if ok else 'FAIL ') + fn.__name__)
        bad += not ok
    print(f'{len(CASES) - bad}/{len(CASES)} pass')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
