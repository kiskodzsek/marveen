#!/usr/bin/env python3
"""Tests for count-claim-gate.py (Klodel 39869).

Runs a COPY of the hook (with ledger_lib.py and hook_errlog.py) in a throw-away install root, as Claude Code does
(PreToolUse JSON on stdin; exit 0 allow, 2 block). The agent comes from transcript_path under <root>/agents/<id>/.
Run: python3 -I scripts/hooks/count-claim-gate_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = 'count-claim-gate.py'
MSG = "bash /Users/klodel/marveen/agents/kernel/tools/kernel-msg.sh klodel - <<'MSG'\n"
CARD = ("curl -s -X POST http://localhost:3420/api/kanban/b71236d8/comments -H 'Content-Type: application/json' "
        "--data-binary @- <<'JSON'\n")
CLOSE = "curl -s -X PUT http://localhost:3420/api/messages/39858 -H 'Content-Type: application/json' --data-binary @- <<'JSON'\n"
CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def make_root(tmp):
    hooks = os.path.join(tmp, 'scripts', 'hooks')
    os.makedirs(hooks)
    for f in (HOOK, 'ledger_lib.py', 'hook_errlog.py'):
        shutil.copy(os.path.join(HERE, f), hooks)
    return os.path.join(hooks, HOOK)


def run(root, command, agent='kernel', tool='Bash', raw=None, cwd=None):
    hook = os.path.join(root, 'scripts', 'hooks', HOOK)
    tp = os.path.join(root, 'agents', agent, '.claude-config', 'projects', 'x', 's.jsonl')
    body = {'tool_name': tool, 'tool_input': {'command': command}, 'transcript_path': tp, 'cwd': cwd or root}
    env = {'PATH': '/usr/bin:/bin', 'HOOK_ERRLOG_PATH': os.devnull, 'MAIN_AGENT_ID': 'klodel'}
    p = subprocess.run([sys.executable, '-I', hook], input=raw if raw is not None else json.dumps(body),
                       capture_output=True, text=True, env=env, timeout=20)
    return p.returncode, p.stdout, p.stderr


def card(content):
    return CARD + json.dumps({'author': 'kernel', 'content': content}, ensure_ascii=False) + '\nJSON'


@case
def block_guessed_count_and_id(root):
    # The three 11-13 shapes: a count in a push request, a guessed msg id on a card, a card id.
    code, out, err = run(root, MSG + 'a 29 új blokkból 15 Klodel-komment\nMSG')
    return (code == 2 and 'MÉRVE' in err and '29 új blokk' in err and out == ''
            and run(root, card('Pulzustól kértem egy count-ot (39836 körül).'))[0] == 2
            and run(root, card('a kártya b71236d8 lezárva'))[0] == 2
            and run(root, MSG + 'msg 3986 és id=39861\nMSG')[0] == 2
            and run(root, MSG + 'lásd msg 3986\nMSG')[0] == 2
            and run(root, CLOSE + '{"status":"done","result":"963 komment, 0 elengedett"}\nJSON')[0] == 2)


@case
def evidence_line_lets_it_through(root):
    return (run(root, MSG + 'a 29 új blokkból 20 Klodel-komment\nMÉRVE: /private/tmp/x/regress.py kimenete\nMSG')[0] == 0
            # a JSON string's line break is a literal \n
            and run(root, card('kérés: 39834\\nMÉRVE: `kernel-msg.sh` válasza, OK id=39834'))[0] == 0
            and run(root, MSG + '963 komment\n- merve: scripts/hooks/time-claim-gate.py:229\nMSG')[0] == 0)


@case
def evidence_without_a_source_does_not_count(root):
    return (run(root, MSG + '29 új blokk\nMÉRVE: igen, megszámoltam\nMSG')[0] == 2
            and run(root, MSG + '29 új blokk, MÉRVE: /tmp/x mid-line\nMSG')[0] == 2)


@case
def no_claim_passes(root):
    return all(run(root, MSG + t + '\nMSG')[0] == 0 for t in (
        'Kész, nincs teendő.',
        'A flotta kerete 22 % 08:50-kor, 3 pont rendben.',
        'Ág feat/x 03c41d7e, alap 8db3b0b0, 2026-11-13.',
        'Lásd http://localhost:3420/api/messages/39858 és /api/kanban/b71236d8/comments'))


@case
def only_opted_in_agents_and_only_sends(root):
    return (run(root, MSG + '29 új blokk\nMSG', agent='dave')[0] == 0
            and run(root, MSG + '29 új blokk\nMSG', agent='klodel')[0] == 0
            and run(root, 'echo "29 új blokk, msg 39836"')[0] == 0
            and run(root, 'git commit -m "29 new blocks (39861)"')[0] == 0
            and run(root, 'curl -s -H "Authorization: Bearer x" "http://localhost:3420/api/daily-log?agent=kernel"')[0] == 0
            # a read of the log with an id in the same command is not a write (mutation M19)
            and run(root, 'curl -s "http://localhost:3420/api/daily-log?agent=kernel" | grep -c 41038')[0] == 0)


@case
def daily_log_write_is_judged(root):
    # Retro R1 (card 028205dd): the daily log is a report too; a write to it is judged, a read is not.
    log = "curl -s -X POST http://localhost:3420/api/daily-log -d '{\"content\":\"%s\"}'"
    return (run(root, log % '29 blokk')[0] == 2
            and run(root, log % '29 blokk\\nMÉRVE: `sqlite3 x.db count(*)`')[0] == 0
            and run(root, "curl -s -X POST http://localhost:3420/api/daily-log --data-binary @- <<'J'\n"
                          '{"content":"## {{NOW}} -- 29 blokk"}\nJ')[0] == 2)


@case
def zero_claim_needs_a_counting_measurement(root):
    # Kernel's retro input (b), hibanapló 2026-11-13 18:04: "0 maradék" went to Viktor under a MÉRVE line whose
    # `ls -d x-* | wc -l` had stopped on a zsh glob with no match; 48 folders were left.
    blocked = [
        '0 db t1-* maradék\nMÉRVE: `ls -d $T/t1-* | wc -l`',          # the incident: ls with a glob
        'nincs maradék\nMÉRVE: /tmp/x megnézve',                       # a source, but nothing counted
        'Egy mappa sem maradt.\nMÉRVE: agents/kernel/tools/README.md:5',
        '0 találat\nMÉRVE: `ls /tmp/a?`',
        '0 db\nMÉRVE: `cd /x && ls -d t1-* | wc -l`',                  # ls after &&
        '0 db\nMÉRVE: `echo $(ls x-* | wc -l)`',                       # ls in $(...)
        # Viktor 41387 INFO 1: the forms the first prefix list missed
        '0 db\nMÉRVE: `for d in a b; do ls $d/x-* | wc -l; done`',
        '0 db\nMÉRVE: `if true; then ls x-* | wc -l; fi`',
        '0 db\nMÉRVE: `time ls x-* | wc -l`',
        '0 db\nMÉRVE: `sudo ls x-* | wc -l`',
        '0 db\nMÉRVE: `command ls x-* | wc -l`',
        '0 db\nMÉRVE: `/bin/ls x-* | wc -l`',
        '0 db\nMÉRVE: `\\ls x-* | wc -l`',
        '0 db\nMÉRVE: `{ ls x-*; } | wc -l`',
        '0 db\nMÉRVE: `! ls x-* | wc -l`',
        "0 db\nMÉRVE: `bash -c 'ls x-* | wc -l'`",
    ]
    passed = [
        '0 db t1-* maradék\nMÉRVE: `find /tmp -maxdepth 1 -name \'t1-*\' | wc -l`',
        'nincs maradék\nMÉRVE: `sqlite3 x.db "select count(*) from t"`',
        '0 találat\nMÉRVE: `grep -c foo /tmp/x.log`',
        '10 db kész\nMÉRVE: /tmp/x.log',                               # not a zero: the old rule only
        "0 db\nMÉRVE: `find /x -name 'ls*' | wc -l`",                # ls inside a find pattern (Viktor 41354)
        '0 db\nMÉRVE: `find /x -type d | wc -l` (nem ls, mert [zsh])',  # the word ls in prose
        'kész, 0 hiba nélkül? nem: a teszt zöld\nMÉRVE: `npm test` kimenete',  # "0 hiba" is not a zero-count noun
    ]
    return (all(run(root, MSG + t + '\nMSG')[0] == 2 for t in blocked)
            and all(run(root, MSG + t + '\nMSG')[0] == 0 for t in passed))


@case
def ls_glob_regex_stays_linear(root):
    # Viktor 41387 LOW (CWE-1333): "ls" + 27 blanks + "x" with no glob took 11 s in the old regex (10 s hook timeout).
    import importlib.util
    import time
    spec = importlib.util.spec_from_file_location('ccg', os.path.join(HERE, HOOK))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # 26 blanks first: the old regex needs about 3 s there (measured), so it fails fast instead of hanging on the
    # long lines below.
    t0 = time.time()
    if mod.LS_GLOB_RX.search('`find /x | wc -l` ; ls' + ' ' * 26 + 'x') or time.time() - t0 > 1.0:
        return False
    t0 = time.time()
    for line in ('ls' + ' \t' * 20000 + 'x', 'ls' + ' a' * 20000 + ' b'):
        if mod.LS_GLOB_RX.search(line):
            return False
    if time.time() - t0 >= 1.0 or mod.LS_GLOB_RX.search('ls' + ' ' * 40 + 'x-*') is None:
        return False
    # Viktor 41421 LOW: a repeated prefixed "ls" (32 KB took 3.1 s with an unbounded token run).
    t0 = time.time()
    for pre in ("'", '"', '(', '{', '!'):
        if mod.LS_GLOB_RX.search((pre + 'ls ') * 8000):
            return False
    if time.time() - t0 >= 1.0:
        return False
    # The bound: a glob after 64 argument tokens is still found, after 70 it is not (documented, not a hole that
    # matters: no measuring command lists 65 names before its glob).
    return (mod.LS_GLOB_RX.search('ls' + ' a' * 64 + ' x-*') is not None
            and mod.LS_GLOB_RX.search('ls' + ' a' * 70 + ' x-*') is None)


@case
def file_payloads_are_judged(root):
    body = os.path.join(root, 'body.json')
    with open(body, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps({'content': 'Pulzustól kértem (39836 körül).'}))
    msg = os.path.join(root, 'msg.txt')
    with open(msg, 'w', encoding='utf-8') as fh:
        fh.write('29 új blokk\n')
    ok_msg = os.path.join(root, 'ok.txt')
    with open(ok_msg, 'w', encoding='utf-8') as fh:
        fh.write('29 új blokk\nMÉRVE: /tmp/regress.py\n')
    return (run(root, 'curl -s -X POST http://localhost:3420/api/kanban/abc/comments --data-binary @' + body)[0] == 2
            and run(root, 'bash agents/kernel/tools/kernel-msg.sh klodel - < msg.txt', cwd=root)[0] == 2
            and run(root, 'bash agents/kernel/tools/kernel-msg.sh klodel - < ' + ok_msg)[0] == 0)


@case
def cli_check_for_the_wrapper(root):
    hook = os.path.join(root, 'scripts', 'hooks', HOOK)
    bad, good = os.path.join(root, 'b.txt'), os.path.join(root, 'g.txt')
    with open(bad, 'w', encoding='utf-8') as fh:
        fh.write('15 Klodel-komment\n')
    with open(good, 'w', encoding='utf-8') as fh:
        fh.write('20 Klodel-komment\nMÉRVE: /tmp/regress.py\n')
    r = lambda f: subprocess.run([sys.executable, '-I', hook, '--check', f], capture_output=True, text=True).returncode
    return r(bad) == 1 and r(good) == 0 and r(os.path.join(root, 'missing.txt')) == 1


@case
def other_tools_and_garbage_pass(root):
    return (run(root, MSG + '29 blokk\nMSG', tool='Write')[0] == 0
            and run(root, None, raw='not json')[0] == 0
            and run(root, None, raw=json.dumps({'tool_name': 'Bash', 'tool_input': ['x']}))[0] == 0
            and run(root, None, raw=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 5}}))[0] == 0)


GET_ONE = "curl -s -H 'Authorization: Bearer x' http://localhost:3420/api/messages/40094"
LIST = "curl -s -H 'Authorization: Bearer x' 'http://localhost:3420/api/messages?agent=kernel&limit=60'"


@case
def read_only_and_status_only_message_calls_pass(root):
    # Klodel 39980: three of Kernel's own reads / status-only closes were blocked on 11-13 because an id stood in the
    # command. A GET, a list, a status-only PUT and a script looping over ids claim nothing to anyone.
    script = os.path.join(root, 'close.py')
    with open(script, 'w') as fh:
        fh.write("for i in (40094, 40081):\n    put(f'/api/messages/{i}', {'status': 'done'})\n")
    return (run(root, GET_ONE)[0] == 0
            and run(root, LIST + ' # 40050 40048')[0] == 0
            and run(root, CLOSE + '{"status":"done"}\nJSON')[0] == 0
            and run(root, "cat > close.py <<'EOF'\nfor i in (40094, 40081):\n    put(f'/api/messages/{i}', "
                          "{'status': 'done'})\nEOF\npython3 -I close.py")[0] == 0
            and run(root, f'python3 -I {script}')[0] == 0)


@case
def NEG_a_close_with_a_result_is_still_judged(root):
    # The narrowing must not open the close-with-result path: inline and in a payload file.
    payload = os.path.join(root, 'res.json')
    with open(payload, 'w') as fh:
        fh.write('{"status":"done","notify":true,"result":"963 komment, 0 elengedett"}')
    # Known limit, unchanged by this fix: a script FILE run with python3 is not read (only payload files are).
    return (run(root, CLOSE + '{"status":"done","result":"963 komment, 0 elengedett"}\nJSON')[0] == 2
            and run(root, GET_ONE.replace('curl -s', 'curl -s -X PUT') + f' --data-binary @{payload}')[0] == 2)


@case
def NEG_a_new_message_post_is_still_judged(root):
    post = ("curl -s -X POST http://localhost:3420/api/messages -H 'Content-Type: application/json' "
            "--data-binary @- <<'JSON'\n{\"from\":\"kernel\",\"to\":\"klodel\",\"content\":\"29 új blokk\"}\nJSON")
    return run(root, post)[0] == 2

@case
def NEG_query_slash_and_escaped_result_forms_are_judged(root):
    # Viktor 40140 LOW: these passed the first version of the narrowing (rc 0) and were blocked on main.
    body = " -H 'Content-Type: application/json' --data-binary @- <<'JSON'\n{\"content\":\"29 új blokk\"}\nJSON"
    esc = ('curl -s -X PUT http://localhost:3420/api/messages/39858 -H "Content-Type: application/json" '
           '-d "{\\"status\\":\\"done\\",\\"result\\":\\"963 komment\\"}"')
    return (run(root, 'curl -s -X POST "http://localhost:3420/api/messages?x=1"' + body)[0] == 2
            and run(root, 'curl -s -X POST "localhost:3420/api/messages?"' + body)[0] == 2
            and run(root, 'curl -s -X POST http://localhost:3420/api/messages/' + body)[0] == 2
            and run(root, 'curl -s -X POST http://localhost:3420/api/messages//' + body)[0] == 2
            and run(root, esc)[0] == 2
            and run(root, CLOSE + "{'status':'done','result':'963 komment'}\nJSON")[0] == 2)


@case
def list_reads_with_trailing_slash_or_query_still_pass(root):
    return (run(root, "curl -s -H 'Authorization: Bearer x' 'http://localhost:3420/api/messages/?agent=kernel' # 40050")[0] == 0
            and run(root, LIST + ' | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" # 963 db')[0] == 0)


def main():
    failed = 0
    for fn in CASES:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = os.path.realpath(tmp)
            make_root(tmp)
            try:
                ok = fn(tmp)
            except Exception as e:  # a crash is a failure, with its reason
                ok = False
                print(f'  {fn.__name__}: {e!r}')
        print(('PASS ' if ok else 'FAIL ') + fn.__name__)
        failed += not ok
    print(f'{len(CASES) - failed}/{len(CASES)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
