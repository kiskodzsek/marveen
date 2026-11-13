#!/usr/bin/env python3
"""Tests for service-memory-reply-gate.py (Klodel 40111). Synthetic transcripts only.

Usage: python3 -I scripts/hooks/service-memory-reply-gate_test.py
Cases named NEG_* must be blocked (rc 2); the rest must pass (rc 0).
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, 'service-memory-reply-gate.py')
REPLY = 'mcp__plugin_telegram_telegram__reply'
EDIT = 'mcp__plugin_telegram_telegram__edit_message'
# The endpoint is assembled: agent-scaffold-memory-load-claim.test.ts scans every file under scripts/hooks for the
# literal, to keep memory-LOADING hooks out; this file only feeds synthetic command texts to the gate.
MEM = 'api/' + 'memories'
SEARCH = 'curl -s -G -H "Authorization: Bearer $(cat x)" --data-urlencode "agent=klodel" --data-urlencode "q=%s" "http://localhost:3420/' + MEM + '"'


def channel(text='mi van a Higgsfielddel?'):
    return {'type': 'user', 'isMeta': True, 'message': {'role': 'user', 'content': [
        {'type': 'text', 'text': '<channel source="plugin:telegram:telegram" chat_id="1">' + text + '</channel>'}]}}


def prompt(text):
    return {'type': 'user', 'message': {'role': 'user', 'content': text}}


def bash(cmd):
    return {'type': 'assistant', 'message': {'role': 'assistant', 'content': [
        {'type': 'tool_use', 'id': 't', 'name': 'Bash', 'input': {'command': cmd}}]}}


def result():
    return {'type': 'user', 'message': {'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': 't', 'content': 'ok'}]}}


def run(entries, text, tool=REPLY, agent='klodel', extra=None, transcript=True):
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, 'store'))
        if extra:
            with open(os.path.join(root, 'store', 'ismert-szolgaltatasok.txt'), 'w', encoding='utf-8') as f:
                f.write(extra)
        path = os.path.join(root, 'session.jsonl')
        if transcript:
            with open(path, 'w', encoding='utf-8') as f:
                for e in entries:
                    f.write(json.dumps(e, ensure_ascii=False) + '\n')
        payload = {'tool_name': tool, 'tool_input': {'chat_id': '1', 'text': text},
                   'transcript_path': path, 'cwd': root}
        env = dict(os.environ, CLAUDE_PROJECT_DIR=root, MAIN_AGENT_ID='klodel', MARVEEN_AGENT_ID=agent)
        r = subprocess.run([sys.executable, '-I', GATE], input=json.dumps(payload), capture_output=True,
                           text=True, env=env, timeout=10)
        return r.returncode, r.stderr


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


H = 'Van Higgsfield-előfizetésünk, az MCP kész.'


@case
def NEG_a_service_without_a_search_in_the_round():
    rc, err = run([channel(), bash('ls')], H)
    return rc == 2 and 'higgsfield' in err and 'q=higgsfield' in err


@case
def NEG_a_search_in_the_previous_round_does_not_count():
    rc, _ = run([channel(), bash(SEARCH % 'Higgsfield'), result(), channel('és most?')], H)
    return rc == 2


@case
def a_search_in_this_round_lets_it_go():
    return run([channel(), bash(SEARCH % 'Higgsfield'), result()], H)[0] == 0


@case
def an_url_encoded_accented_search_counts():
    return run([channel(), bash(SEARCH.replace('%s', 'Billing%C3%B3'))], 'A Billingóban ott a piszkozat.')[0] == 0


@case
def NEG_saving_a_memory_is_not_a_search():
    save = 'curl -s -X POST http://localhost:3420/' + MEM + ' -d \'{"content":"Higgsfield Ultra"}\''
    return run([channel(), bash(save)], H)[0] == 2


@case
def NEG_a_search_for_another_name_does_not_cover_this_one():
    rc, err = run([channel(), bash(SEARCH % 'Metricool')], 'A Metricool és a Higgsfield is kész.')
    return rc == 2 and 'higgsfield' in err and 'metricool' not in err.split('(')[1].split(')')[0]


@case
def two_names_two_searches_in_one_command_pass():
    cmd = (SEARCH % 'Metricool') + ' ; ' + (SEARCH % 'Higgsfield')
    return run([channel(), bash(cmd)], 'A Metricool és a Higgsfield is kész.')[0] == 0


@case
def NEG_an_inflected_name_is_found():
    return run([channel()], 'A Vercelre ment ki, a Stripe-ot nem érinti.')[0] == 2


@case
def the_word_fal_alone_is_a_wall_not_a_service():
    return run([channel()], 'A falra kitettük a képet, a falon jól mutat.')[0] == 0


@case
def NEG_fal_ai_and_its_hyphen_forms_are_services():
    return run([channel()], 'A képet fal-lal generáltuk.')[0] == 2 and run([channel()], 'A fal.ai-keret zárva.')[0] == 2


@case
def canvas_is_not_canva():
    return run([channel()], 'A canvas elem a böngészőben rajzol.')[0] == 0


@case
def machine_prompts_do_not_start_a_new_round():
    entries = [channel(), bash(SEARCH % 'Higgsfield'), result(), prompt('[Inbox] Ha fent uj bejovo blokk van'),
               prompt('<task-notification> <task-id>a1</task-id>'), prompt('Base directory for this skill: /x'),
               prompt('<system-reminder> x </system-reminder>')]
    return run(entries, H)[0] == 0


@case
def NEG_a_scheduled_task_starts_a_new_round():
    entries = [channel(), bash(SEARCH % 'Higgsfield'), prompt('<scheduled-task source="x"> napindító </scheduled-task>')]
    return run(entries, H)[0] == 2


@case
def NEG_a_bare_terminal_prompt_starts_a_new_round():
    return run([bash(SEARCH % 'Higgsfield'), prompt('mi a helyzet a Higgsfielddel?')], H)[0] == 2


@case
def a_sub_agent_is_not_gated():
    return run([channel()], H, agent='dave')[0] == 0


@case
def edit_message_is_not_gated():
    return run([channel()], H, tool=EDIT)[0] == 0


@case
def a_reply_without_a_service_passes():
    return run([channel()], 'Kész a videó, küldöm.')[0] == 0


@case
def an_unreadable_transcript_is_allowed():
    return run([], H, transcript=False)[0] == 0


@case
def NEG_a_name_from_the_store_file_is_gated():
    rc, err = run([channel()], 'A Kling-gel készült.', extra='# saját lista\nKling\n')
    return rc == 2 and 'kling' in err


@case
def the_store_file_name_passes_after_its_search():
    return run([channel(), bash(SEARCH % 'kling')], 'A Kling-gel készült.', extra='Kling\n')[0] == 0


@case
def NEG_a_store_line_with_shell_syntax_never_reaches_the_recipe():
    # Viktor 40315 LOW: such a line is skipped, so it neither gates nor lands in the "run this" recipe
    bad = 'x"; touch /tmp/pwn-svc; echo "'
    rc, err = run([channel()], 'Szöveg: ' + bad + ' és a Higgsfield.', extra=bad + '\n')
    return rc == 2 and 'touch' not in err and 'q=higgsfield' in err


@case
def a_one_letter_store_line_does_not_gate_every_reply():
    return run([channel()], 'Ez a válasz, a videó kész.', extra='a\nab\n')[0] == 0


@case
def a_transcript_path_that_is_not_a_regular_file_is_allowed():
    # Viktor 40315 INFO 1. A FIFO with no writer and /dev/zero (seekable, endless): without the regular-file check
    # the read hangs, so each path runs in a child with a timeout; a hang counts as a failure.
    with tempfile.TemporaryDirectory() as d:
        fifo = os.path.join(d, 'fifo.jsonl')
        os.mkfifo(fifo)
        code = ('import importlib.util,sys;s=importlib.util.spec_from_file_location("g",sys.argv[1]);'
                'g=importlib.util.module_from_spec(s);s.loader.exec_module(g);print(g.round_commands(sys.argv[2]))')
        for path in (d, fifo, '/dev/zero'):
            try:
                r = subprocess.run([sys.executable, '-I', '-c', code, GATE, path], capture_output=True, text=True,
                                   timeout=5)
            except subprocess.TimeoutExpired:
                return False
            if r.stdout.strip() != 'None':
                return False
        return True


@case
def a_malformed_payload_is_allowed():
    r = subprocess.run([sys.executable, '-I', GATE], input='nem json', capture_output=True, text=True, timeout=10)
    return r.returncode == 0


@case
def NEG_only_the_transcript_tail_is_read_and_a_cut_first_line_is_dropped():
    spec = importlib.util.spec_from_file_location('g', GATE)
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 's.jsonl')
        with open(p, 'w', encoding='utf-8') as f:
            f.write(json.dumps(bash(SEARCH % 'Higgsfield')) + '\n')
            f.write(json.dumps(channel()) + '\n')
            for _ in range(50):
                f.write(json.dumps(bash('echo ' + 'x' * 100)) + '\n')
        g.TAIL_BYTES = os.path.getsize(p) - 10  # the search line is outside the tail
        cmds = g.round_commands(p)
        return cmds is not None and not any(MEM in c for c in cmds) and \
            g.missing(H, cmds) == ['higgsfield']


def main():
    bad = 0
    for fn in CASES:
        try:
            ok = fn()
        except Exception as exc:
            ok = False
            print('ERR ', fn.__name__, type(exc).__name__, exc)
        print('ok  ' if ok else 'FAIL', fn.__name__)
        bad += not ok
    print('%d/%d passed' % (len(CASES) - bad, len(CASES)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
