#!/usr/bin/env python3
"""Tests for session-meta-reply-gate.py (retro 2026-11-13 R8, card 84858637).

Run: python3 -I scripts/hooks/session-meta-reply-gate_test.py
Hermetic: the owner chats come from MARVEEN_OWNER_CHATS or a throw-away CLAUDE_PROJECT_DIR; no network, no real store.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, 'session-meta-reply-gate.py')
OWNER, GROUP, OTHER = '111', '-222', '333'

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def run(text, chat=OWNER, tool='mcp__plugin_telegram_telegram__reply', env=None, raw=None):
    e = dict(os.environ)
    e.pop('MARVEEN_OWNER_CHATS', None)
    e['MARVEEN_OWNER_CHATS'] = f'{OWNER},{GROUP}'
    e['CLAUDE_PROJECT_DIR'] = tempfile.mkdtemp()
    if env is not None:
        e.update(env)
        for k, v in env.items():
            if v is None:
                e.pop(k, None)
    data = raw if raw is not None else json.dumps({'tool_name': tool, 'tool_input': {'chat_id': chat, 'text': text}})
    r = subprocess.run([sys.executable, '-I', GATE], input=data, capture_output=True, text=True, env=e)
    return r.returncode, r.stderr


def blocks(text, **kw):
    rc, err = run(text, **kw)
    if rc != 2:
        print(f'  expected block: {text!r} -> rc {rc} {err[:80]}')
    return rc == 2 and 'SESSION-META-KAPU' in err


def passes(text, **kw):
    rc, err = run(text, **kw)
    if rc != 0:
        print(f'  expected pass: {text!r} -> rc {rc} {err[:120]}')
    return rc == 0


@case
def incident_tg665_blocked(_=None):
    # the line Dave sent on 2026-11-13 15:56 (TG 665) and 11-11 (TG 632), and its close variants
    return all(blocks(t) for t in (
        'Friss kontextussal folytatom.',
        'friss kontextussal folytatom a munkat',          # Patrik's chats are often without accents
        'Restart után friss kontextussal folytatom a megkezdett munkát.',
        'Folytatom a megkezdett munkát, a HANDOFF.md szerint.',
    ))


@case
def session_meta_forms_blocked(_=None):
    return all(blocks(t) for t in (
        'A context-guard újraindított, de minden megvan.',
        'Auto-handoff után itt vagyok.',
        'A handoff után itt vagyok, a PR áll.',
        'A kontextusom megtelt, ezért újraindultam.',
        'Új session-ben vagyok, a kártyák rendben.',
        'A sessionom restart után tiszta.',
        'Újraindítottak, de a PR áll.',
        'Resuming after a restart, all good.',
        'Fresh context, picking up the PR.',
        'My context filled up, back now.',
    ))


@case
def edit_message_gated_too(_=None):
    return blocks('Friss kontextussal folytatom.', tool='mcp__plugin_telegram_telegram__edit_message')


@case
def group_chat_gated(_=None):
    return blocks('Friss kontextussal folytatom.', chat=GROUP)


@case
def other_chat_not_gated(_=None):
    return passes('Friss kontextussal folytatom.', chat=OTHER)


@case
def real_content_passes(_=None):
    # restart of something else, words alone, and ordinary work reports
    return all(passes(t) for t in (
        'A Vercel-deploy restart után a /meseld-el 200-at ad.',
        'A szerver újraindulása után a webhookok futnak.',
        'A dev szervert újraindítottam a 3335-ös porton.',
        'A #1298 PR kész, Pulzus éjjeli kötegében megy.',
        'A kontextus az, hogy a vevő mesél, nem ír.',            # "kontextus" as a word, nothing after it
        'Folytatom a lapozó képeit, 10 perc múlva küldöm.',
        'A session süti 30 napig él.',                           # Marabel session cookie, no restart
        # Patrik asked about another agent: Dave's real answers (replay), shortened
        'Klodel él és dolgozik: 20:54-kor újraindult (context restart), azóta rendben megy.',
        'Ma 10:10-kor újraindult az egész flotta, az ágensek üzenetsorában van nála 2 nyitott.',
        'Ezért nem segített az újraindítás sem: az új session ugyanúgy elhasalt.',
        # Viktor 41381 LOW 1: the words alone, in answers to Patrik's own questions
        'A feladat handoffja Dave-nek megtörtént, kártya frissítve.',
        'Patrik, a handoff.md-t kérted? Ott van a shared mappában.',
        'A context-guard szabályt a kernel írta, nem én.',
        'A fresh context módszer a promptolásban azt jelenti, hogy tiszta lappal indul a modell.',
    ))


@case
def new_session_branch_blocked(_=None):
    # Viktor 41381 INFO 3: the "folytatom" and "indultam" ends of the new-session pattern
    return all(blocks(t) for t in (
        'Új sessionben folytatom a PR-t.',
        'Uj munkamenetben indultam, minden rendben.',
        'Folytatom friss kontextussal.',
        'A handoff alapján folytatom a #1298-at.',
        'Dave friss kontextussal folytatja (auto-handoff).',            # replay: third-person self-report
        'Friss kontextussal viszem tovább a kóstoló-törlést.',
    ))


@case
def internal_error_fails_open_and_logs(_=None):
    # Viktor 41381 INFO 3: an exception inside main() is allowed (rc 0) and written to the hook error log
    log = os.path.join(tempfile.mkdtemp(), 'hook-errors.log')
    e = dict(os.environ, MARVEEN_OWNER_CHATS=OWNER, HOOK_ERRLOG_PATH=log, CLAUDE_PROJECT_DIR=tempfile.mkdtemp())
    code = ('import runpy, unicodedata, sys; sys.path.insert(0, %r); '
            'unicodedata.normalize = lambda *a: 1 / 0; runpy.run_path(%r, run_name="__main__")' % (HERE, GATE))
    data = json.dumps({'tool_name': 'mcp__plugin_telegram_telegram__reply',
                       'tool_input': {'chat_id': OWNER, 'text': 'Friss kontextussal folytatom.'}})
    r = subprocess.run([sys.executable, '-I', '-c', code], input=data, capture_output=True, text=True, env=e)
    logged = os.path.exists(log) and 'session-meta-reply-gate' in open(log, encoding='utf-8').read()
    if r.returncode != 0 or not logged:
        print(f'  rc {r.returncode}, logged {logged}, {r.stderr[:160]}')
    return r.returncode == 0 and logged


@case
def no_known_chat_fails_closed(_=None):
    # no MARVEEN_OWNER_CHATS and no store/projektek.json: every chat is gated
    return blocks('Friss kontextussal folytatom.', chat=OTHER, env={'MARVEEN_OWNER_CHATS': None})


@case
def projektek_json_chats(_=None):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, 'store'))
    json.dump({'elo_uzenet': {'privat': OWNER, 'csoport': {'chat_id': GROUP, 'message_id': 5}}},
              open(os.path.join(d, 'store', 'projektek.json'), 'w'))
    e = dict(os.environ)
    e.pop('MARVEEN_OWNER_CHATS', None)
    e['CLAUDE_PROJECT_DIR'] = d

    def rc(chat):
        data = json.dumps({'tool_name': 'mcp__plugin_telegram_telegram__reply',
                           'tool_input': {'chat_id': chat, 'text': 'Friss kontextussal folytatom.'}})
        return subprocess.run([sys.executable, '-I', GATE], input=data, capture_output=True, text=True, env=e).returncode
    return rc(OWNER) == 2 and rc(GROUP) == 2 and rc(OTHER) == 0


@case
def malformed_payload_allowed(_=None):
    return all(run('', raw=r)[0] == 0 for r in ('', 'not json', '[]', '{"tool_input": 5}',
                                                 json.dumps({'tool_input': {'chat_id': OWNER, 'text': None}})))


@case
def zero_width_and_hyphen_normalised(_=None):
    return blocks('fri​ss kon­textussal folytatom') and blocks('context_guard restart')


def main():
    fails = 0
    for fn in CASES:
        try:
            ok = fn()
        except Exception as ex:
            ok = False
            print(f'  {fn.__name__}: {ex!r}')
        print(('PASS ' if ok else 'FAIL ') + fn.__name__)
        fails += 0 if ok else 1
    print(f'{len(CASES) - fails}/{len(CASES)} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
