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


def run(root, tool_input, env_extra=None, raw=None):
    env = {'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root, **(env_extra or {})}
    payload = raw if raw is not None else json.dumps({'tool_input': tool_input})
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
