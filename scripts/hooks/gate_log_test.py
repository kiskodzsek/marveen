#!/usr/bin/env python3
"""Tests for gate_log.py (Klodel 35878): one line per block, the gate's verdict untouched.

Runs real reply gates as Claude Code does (JSON on stdin; exit 0 allow, 2 block) against a throw-away
CLAUDE_PROJECT_DIR with synthetic chat ids and a throw-away GATE_LOG_PATH: the live store is never read or written.
Run: python3 -I scripts/hooks/gate_log_test.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GROUP = '-1000000000001'  # synthetic
PRIV = '5040302010'       # synthetic
PROJEKTEK = {'elo_uzenet': {'csoport': {'chat_id': GROUP, 'message_id': 1}, 'privat': PRIV}}
# A claim without a source: claim-source blocks it (its own test proves the rule; here only the log matters).
CLAIM = 'Kész a papás film, a te mondataiddal.'
WIRED = ['outgoing-copy-gate', 'product-image-gate', 'mute-video-reply-gate', 'claim-source-reply-gate',
         'private-topic-group-gate', 'mea-culpa-reply-gate', 'render-claim-reply-gate', 'email-approval-gate']

FAILS = 0


def ok(name, cond, detail=''):
    global FAILS
    print(('ok   ' if cond else 'FAIL ') + name + ('' if cond or not detail else f'  -- {detail}'))
    if not cond:
        FAILS += 1


def setup(root):
    os.makedirs(os.path.join(root, 'store'), exist_ok=True)
    with open(os.path.join(root, 'store', 'projektek.json'), 'w', encoding='utf-8') as f:
        json.dump(PROJEKTEK, f)


def run(root, hook, payload, log, extra=None):
    env = {'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root, 'GATE_LOG_PATH': log, **(extra or {})}
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    p = subprocess.run([sys.executable, '-I', os.path.join(HERE, hook + '.py')], input=raw, capture_output=True,
                       text=True, env=env, timeout=30)
    return p.returncode, p.stderr


def lines(log):
    try:
        with open(log, encoding='utf-8') as f:
            return [json.loads(x) for x in f if x.strip()]
    except FileNotFoundError:
        return []


def main():
    with tempfile.TemporaryDirectory() as root:
        setup(root)
        log = os.path.join(root, 'gate-blocks.jsonl')
        # synthetic path under this checkout's agents/ (ledger_lib keys the agent by the install it lives in)
        transcript = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'agents', 'dave', '.claude-config', 'y.jsonl')
        payload = {'tool_input': {'chat_id': GROUP, 'text': CLAIM}, 'transcript_path': transcript}

        rc, err = run(root, 'claim-source-reply-gate', payload, log)
        got = lines(log)
        ok('a block keeps its exit code and message', rc == 2 and 'ÁLLÍTÁS-FORRÁS-KAPU' in err, (rc, err))
        ok('a block is logged as one line', len(got) == 1, got)
        line = got[0] if got else {}
        ok('  ...with gate, time, agent and the reason code', line.get('gate') == 'claim-source'
           and isinstance(line.get('at'), int) and line.get('agent') == 'dave' and line.get('code') == 'kesz', line)
        ok('  ...and nothing of the message, the chat or the path', set(line) == {'at', 'gate', 'agent', 'code'}
           and 'papás' not in json.dumps(line, ensure_ascii=False) and GROUP not in json.dumps(line), line)

        rc, _ = run(root, 'claim-source-reply-gate', {'tool_input': {'chat_id': GROUP, 'text': 'Szia, mikor jó?'}}, log)
        ok('a pass is not logged', rc == 0 and len(lines(log)) == 1, lines(log))
        rc, _ = run(root, 'claim-source-reply-gate', 'not json', log)
        ok('a malformed payload still passes, unlogged', rc == 0 and len(lines(log)) == 1, lines(log))

        rc, err = run(root, 'mea-culpa-reply-gate', {'tool_input': {'chat_id': GROUP, 'text': 'Igazad van, hibáztam.'}},
                      log, {'MARVEEN_AGENT_ID': 'klodel'})
        last = lines(log)[-1]
        ok('another gate logs under its own name, agent from the env when the payload has none',
           rc == 2 and last.get('gate') == 'mea-culpa' and last.get('agent') == 'klodel' and last.get('code') == '',
           (rc, last))

        rc, err = run(root, 'product-image-gate', {'tool_input': {'chat_id': '1', 'text': 'x',
                                                                  'files': [os.path.join(root, 'a.png')]}}, log)
        last = lines(log)[-1]
        ok('product-image names its reason (kep)', rc == 2 and last.get('gate') == 'product-image'
           and last.get('code') == 'kep', (rc, err[:200], last))

        bad = os.path.join(root, 'no-such-dir-file', 'x')
        open(os.path.join(root, 'no-such-dir-file'), 'w').close()  # a file where the log's directory should be
        rc, err = run(root, 'claim-source-reply-gate', payload, bad)
        ok('an unwritable log does not change the verdict', rc == 2 and 'ÁLLÍTÁS-FORRÁS-KAPU' in err, (rc, err))

    for g in WIRED:
        with open(os.path.join(HERE, g + '.py'), encoding='utf-8') as f:
            src = f.read()
        ok(f'{g} is wired to gate_log, with a no-op fallback',
           'from gate_log import watch as _gate_log_watch' in src and 'nullcontext as _gate_log_watch' in src
           and '_gate_log_watch(' in src.split('if __name__ ==')[-1])
    print(f'{"FAILED " + str(FAILS) if FAILS else "all passed"}')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
