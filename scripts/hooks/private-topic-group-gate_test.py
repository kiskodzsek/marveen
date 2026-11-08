#!/usr/bin/env python3
"""Tests for private-topic-group-gate.py (card 6dbeadad, shared/hibanaplo.md 2026-11-06 13:52).

Runs the hook as Claude Code does (JSON on stdin; exit 0 allow, 2 block) against a throw-away
CLAUDE_PROJECT_DIR with synthetic chat ids and synthetic store files: the live store is never read.
Run: python3 -I scripts/hooks/private-topic-group-gate_test.py
"""
import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'private-topic-group-gate.py')
GROUP = '-1000000000001'  # synthetic
PRIV = '5040302010'       # synthetic
TEMAK = {'minta': [r'\bSSD', 'vidIQ', '(rossz']}
PROJEKTEK = {
    'elo_uzenet': {'csoport': GROUP, 'privat': PRIV},
    'projektek': [
        {'id': 'hirdetes-x', 'chat': 'privat', 'kulcsszavak': ['hirdetéskép', 'Meta-hirdetés', '12 500 Ft']},
        {'id': 'csoportos-y', 'chat': 'csoport', 'kulcsszavak': ['posztnaptár']},
    ],
    'archiv': [{'id': 'regi-z', 'chat': 'privat', 'kulcsszavak': ['faceless']}],
}


def setup(root, temak=TEMAK, projektek=PROJEKTEK):
    store = os.path.join(root, 'store')
    os.makedirs(store, exist_ok=True)
    if temak is not None:
        json.dump(temak, open(os.path.join(store, 'privat-temak.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    if projektek is not None:
        json.dump(projektek, open(os.path.join(store, 'projektek.json'), 'w', encoding='utf-8'), ensure_ascii=False)


def run(root, tool_input, env_extra=None):
    env = {'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root, **(env_extra or {})}
    p = subprocess.run([sys.executable, '-I', HOOK], input=json.dumps({'tool_input': tool_input}),
                       capture_output=True, text=True, env=env, timeout=20)
    return p.returncode, p.stderr


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def group_private_project_keyword_blocked(root):
    setup(root)
    rc, err = run(root, {'chat_id': GROUP, 'text': 'Kész a Meséld el! hirdetéskép, nézd meg.'})
    return rc == 2 and 'hirdetes-x' in err


@case
def group_keyword_case_insensitive_blocked(root):
    setup(root)
    rc, _ = run(root, {'chat_id': GROUP, 'text': 'A META-HIRDETÉS holnap indul'})
    return rc == 2


@case
def group_keyword_nbsp_blocked(root):
    setup(root)
    rc, _ = run(root, {'chat_id': GROUP, 'text': 'a keret 12 500 Ft'})
    return rc == 2


@case
def group_archived_private_project_blocked(root):
    setup(root)
    rc, _ = run(root, {'chat_id': GROUP, 'text': 'faceless csatorna ötlet'})
    return rc == 2


@case
def group_privat_temak_regex_blocked(root):
    setup(root)
    rc, _ = run(root, {'chat_id': GROUP, 'text': 'az SSD megjött'})
    return rc == 2


@case
def group_file_name_blocked(root):
    setup(root)
    rc, _ = run(root, {'chat_id': GROUP, 'text': 'kép', 'files': ['/x/meta-hirdetés-v2.png']})
    return rc == 2


@case
def edit_message_shape_blocked(root):
    # edit_message has chat_id + message_id + text, no files
    setup(root)
    rc, _ = run(root, {'chat_id': GROUP, 'message_id': '7', 'text': 'javítva: hirdetéskép'})
    return rc == 2


@case
def invalid_regex_as_text_no_crash(root):
    setup(root)
    rc, err = run(root, {'chat_id': GROUP, 'text': 'ez (rossz szöveg'})
    return rc == 2 and 'Traceback' not in err


@case
def group_clean_text_allowed(root):
    setup(root)
    rc, _ = run(root, {'chat_id': GROUP, 'text': 'A receptkönyv 2. darabja kész, posztnaptár holnap.'})
    return rc == 0


@case
def private_chat_allowed(root):
    setup(root)
    rc, _ = run(root, {'chat_id': PRIV, 'text': 'Kész a hirdetéskép.'})
    return rc == 0


@case
def private_chat_allowed_live_store_shape(root):
    # The live store: elo_uzenet.privat is {"chat_id", "message_id"} (the status card), not a bare id.
    live = dict(PROJEKTEK, elo_uzenet={'csoport': {'chat_id': int(GROUP), 'message_id': 11}, 'privat': {'chat_id': int(PRIV), 'message_id': 12}})
    setup(root, projektek=live)
    rc_priv, _ = run(root, {'chat_id': PRIV, 'text': 'Kész a hirdetéskép.'})
    rc_group, _ = run(root, {'chat_id': GROUP, 'text': 'Kész a hirdetéskép.'})
    return rc_priv == 0 and rc_group == 2


@case
def third_chat_gated(root):
    # Viktor 29635 INFO-3: any chat but the owner's private one (e.g. a direct chat with Balázs).
    setup(root)
    rc, _ = run(root, {'chat_id': '999', 'text': 'hirdetéskép'})
    return rc == 2


@case
def env_private_overrides_store(root):
    setup(root)
    rc, _ = run(root, {'chat_id': '-42', 'text': 'hirdetéskép'}, {'MARVEEN_OWNER_PRIVATE_CHAT': '-42'})
    return rc == 0


@case
def overflow_regex_fails_closed(root):
    # Viktor 29635: re.compile('a{99999999999}') raises OverflowError, not re.error; it exited 1 (= no block).
    setup(root, temak={'minta': ['a{99999999999}', 'a{4294967296}']})
    rc, err = run(root, {'chat_id': GROUP, 'text': 'Meta-hirdetés holnap'})
    return rc == 2 and 'Traceback' not in err


@case
def overflow_regex_clean_text_still_passes_or_blocks(root):
    # The bad pattern is matched as text, so a clean message still goes through.
    setup(root, temak={'minta': ['a{99999999999}']})
    rc, err = run(root, {'chat_id': GROUP, 'text': 'A receptkönyv kész.'})
    return rc == 0 and 'Traceback' not in err


@case
def zero_width_and_underscore_blocked(root):
    setup(root)
    rc1, _ = run(root, {'chat_id': GROUP, 'text': 'Meta-hirde\u200btés'})
    rc2, _ = run(root, {'chat_id': GROUP, 'text': 'kép', 'files': ['/x/meta_hirdetés_v2.png']})
    return rc1 == 2 and rc2 == 2


@case
def nothing_known_fail_closed(root):
    setup(root, projektek={k: v for k, v in PROJEKTEK.items() if k != 'elo_uzenet'})
    rc, _ = run(root, {'chat_id': PRIV, 'text': 'hirdetéskép'})
    return rc == 2


@case
def missing_temak_uses_fallback(root):
    setup(root, temak=None)
    rc, _ = run(root, {'chat_id': GROUP, 'text': 'vidIQ próba'})
    return rc == 2


@case
def malformed_store_no_crash(root):
    setup(root, temak=None, projektek=None)
    store = os.path.join(root, 'store')
    open(os.path.join(store, 'projektek.json'), 'w').write('{nem json')
    open(os.path.join(store, 'privat-temak.json'), 'w').write('[1, 2')
    rc, err = run(root, {'chat_id': GROUP, 'text': 'SSD'})
    return rc == 2 and 'Traceback' not in err


@case
def klodel_30145_running_ad_sentence_blocked(root):
    # The sentence that went to the group on 11-06 (Klodel 30145), with the keywords added after it.
    setup(root, projektek=dict(PROJEKTEK, projektek=[{'id': 'hirdetes-x', 'chat': 'privat',
                                                      'kulcsszavak': ['futó hirdetés', 'hirdetésben']}]))
    rc, err = run(root, {'chat_id': GROUP, 'text': 'ez a most futó hirdetésben is benne van'})
    return rc == 2 and 'hirdetes-x' in err


@case
def suffixed_form_of_keyword_blocked(root):
    # Substring match: "hirdetés" catches "hirdetésben", "hirdetést", "hirdetéseinkről".
    setup(root, projektek=dict(PROJEKTEK, projektek=[{'id': 'h', 'chat': 'privat', 'kulcsszavak': ['hirdetés']}]))
    return all(run(root, {'chat_id': GROUP, 'text': t})[0] == 2
               for t in ('a hirdetésben', 'láttad a hirdetést?', 'a hirdetéseinkről'))


@case
def lengthened_final_vowel_blocked(root):
    # Hungarian lengthens a final a/e before a suffix: "Meta" -> "Metában", "csatorna" -> "csatornán", "kecske" -> "kecskét".
    setup(root, projektek=dict(PROJEKTEK, projektek=[{'id': 'p', 'chat': 'privat',
                                                      'kulcsszavak': ['Meta', 'arc nélküli csatorna', 'Heni', 'kecske']}]))
    blocked = all(run(root, {'chat_id': GROUP, 'text': t})[0] == 2
                  for t in ('a METÁBAN fut', 'a Metán', 'az arc nélküli csatornán', 'Henivel beszéltem', 'a kecskét'))
    clean = run(root, {'chat_id': GROUP, 'text': 'A receptkönyv kész, holnap posztnaptár.'})[0] == 0
    private = run(root, {'chat_id': PRIV, 'text': 'a Metában fut'})[0] == 0
    return blocked and clean and private


@case
def settings_wire_gate_on_reply_and_edit_message(root):
    # The gate must run on both Telegram send tools. SETTINGS_JSON=<path> measures another copy (e.g. the live one).
    import re
    path = os.environ.get('SETTINGS_JSON') or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HOOK))),
                                                           '.claude', 'settings.json')
    entries = json.load(open(path, encoding='utf-8')).get('hooks', {}).get('PreToolUse', [])

    def wired(tool):
        for e in entries:
            m = e.get('matcher')
            if m and re.fullmatch(m, tool) and any('private-topic-group-gate.py' in str(h.get('command', ''))
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
