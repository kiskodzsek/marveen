#!/usr/bin/env python3
"""Negative tests for react-emoji-gate.py (Klodel 38093, Patrik group TG 5436). Runs the hook as Claude Code does
(JSON on stdin, exit 0 allow / 2 block) with MARVEEN_OWNER_CHATS set to synthetic ids, or a throw-away project dir.
Run: python3 -I scripts/hooks/react-emoji-gate_test.py
"""
import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'react-emoji-gate.py')
PRIV, GROUP, OTHER = '5040302010', '-1000000000001', '-1000000000777'  # synthetic
FAILS = []


def run(ti, chats=f'{PRIV},{GROUP}', root=None):
    env = {'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root or tempfile.gettempdir()}
    if chats is not None:
        env['MARVEEN_OWNER_CHATS'] = chats
    p = subprocess.run([sys.executable, '-I', HOOK], input=ti if isinstance(ti, str) else json.dumps({'tool_input': ti}),
                       capture_output=True, text=True, env=env, timeout=20)
    return p.returncode, p.stderr


def check(name, ok):
    print(('PASS ' if ok else 'FAIL ') + name)
    if not ok:
        FAILS.append(name)


laugh = ['😁', '🤣', '😂', '😆', '😅', '🤡', '😀', '😃', '😄', '😹', '🤪', '😁️', '​😂']
for chat in (PRIV, GROUP):
    res = [run({'chat_id': chat, 'message_id': '1', 'emoji': e}) for e in laugh]
    check(f'laughing blocked in {"private" if chat == PRIV else "group"}',
          all(rc == 2 and 'REAKCIÓ-KAPU' in err for rc, err in res))
ok = ['👍', '👀', '❤', '❤️', '🔥', '🙏']
check('👍 👀 ❤ and other non-laughing pass', all(run({'chat_id': GROUP, 'message_id': '1', 'emoji': e})[0] == 0 for e in ok))
check('another chat is not gated', run({'chat_id': OTHER, 'message_id': '1', 'emoji': '😁'})[0] == 0)
check('int chat id is the same chat', run({'chat_id': int(GROUP), 'message_id': 1, 'emoji': '🤣'})[0] == 2)

with tempfile.TemporaryDirectory() as root:
    os.makedirs(os.path.join(root, 'store'))
    with open(os.path.join(root, 'store', 'projektek.json'), 'w', encoding='utf-8') as f:
        json.dump({'elo_uzenet': {'privat': PRIV, 'csoport': {'chat_id': GROUP}}}, f)
    check('chats from projektek.json (plain and {"chat_id"})',
          run({'chat_id': GROUP, 'emoji': '😂'}, chats=None, root=root)[0] == 2
          and run({'chat_id': PRIV, 'emoji': '😂'}, chats=None, root=root)[0] == 2
          and run({'chat_id': OTHER, 'emoji': '😂'}, chats=None, root=root)[0] == 0)
with tempfile.TemporaryDirectory() as root:
    check('no chat known: every chat gated (fail closed)', run({'chat_id': OTHER, 'emoji': '😁'}, chats=None, root=root)[0] == 2)
check('malformed payload allowed', run('not json')[0] == 0)

print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'All react-emoji-gate tests passed.'}")
sys.exit(1 if FAILS else 0)
