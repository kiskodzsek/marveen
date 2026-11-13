#!/usr/bin/env python3
"""Tests for render-claim-reply-gate.py (Klodel 35696, Patrik TG 4381).

Runs the hook as Claude Code does (JSON on stdin; exit 0 allow, 2 block) against a throw-away CLAUDE_PROJECT_DIR with
synthetic chat ids, a synthetic store and synthetic output files: the live store is never read.
Run: python3 -I scripts/hooks/render-claim-reply-gate_test.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, 'render-claim-reply-gate.py')
sys.path.insert(0, HERE)
from render_claim_lib import lsof_path, output_of, output_of_process, generation_output, is_generation, read_stamp, write_stamp  # noqa: E402
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location('render_claim_reply_gate', HOOK)
GATE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(GATE)

GROUP = '-1000000000001'  # synthetic
PRIV = '5040302010'       # synthetic
OTHER = '7777777'         # synthetic, not an owner chat
PROJEKTEK = {'elo_uzenet': {'csoport': {'chat_id': GROUP, 'message_id': 1}, 'privat': PRIV}}
# The 09:06 reply, word for word (Klodel 35696).
THE_0906 = 'a babás most renderel a minin, a papás a MacBookon készül'


def setup(root):
    store = os.path.join(root, 'store')
    os.makedirs(store, exist_ok=True)
    with open(os.path.join(store, 'projektek.json'), 'w', encoding='utf-8') as f:
        json.dump(PROJEKTEK, f)


def output(root, name, age_s):
    p = os.path.join(root, 'out', name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'wb') as f:
        f.write(b'x')
    t = time.time() - age_s
    os.utime(p, (t, t))
    return p


def run(root, text, chat=GROUP, raw=None):
    env = {'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root}
    payload = raw if raw is not None else json.dumps({'tool_input': {'chat_id': chat, 'text': text}})
    p = subprocess.run([sys.executable, '-I', HOOK], input=payload, capture_output=True, text=True, env=env, timeout=20)
    return p.returncode, p.stderr


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def the_0906_reply_is_blocked_without_a_measurement(root):
    setup(root)
    rc, err = run(root, THE_0906)
    assert rc == 2 and "mérd meg; tervnél: 'Dave indítja'" in err, (rc, err)


@case
def the_0906_reply_is_blocked_even_with_a_fresh_measurement_because_of_the_macbook(root):
    setup(root)
    write_stamp(root, [output(root, 'babas.mp4', 5)])
    rc, err = run(root, THE_0906)
    assert rc == 2 and 'MacBook' in err, (rc, err)


@case
def a_stale_target_blocks_the_09_06_minin_claim(root):
    # The process may still run, but the target was last written 12 minutes ago: not rendering.
    setup(root)
    write_stamp(root, [output(root, 'babas.mp4', 12 * 60)])
    rc, err = run(root, 'a babás most renderel a minin')
    assert rc == 2 and 'sem íródott' in err, (rc, err)


@case
def a_fresh_measurement_and_a_fresh_target_let_the_claim_go(root):
    setup(root)
    write_stamp(root, [output(root, 'babas.mp4', 10)])
    for text in ['a babás most renderel a minin', 'Fut a render, babas.mp4 most íródik.', 'Exportálódik a film.']:
        rc, err = run(root, text)
        assert rc == 0, (text, rc, err)


@case
def an_old_measurement_blocks_even_with_a_fresh_target(root):
    setup(root)
    write_stamp(root, [output(root, 'babas.mp4', 5)], now=time.time() - 3 * 60)
    rc, err = run(root, 'renderel a babás')
    assert rc == 2 and 'mérés nélkül' in err, (rc, err)


@case
def a_named_file_must_be_one_of_the_fresh_outputs(root):
    setup(root)
    write_stamp(root, [output(root, 'babas.mp4', 5), output(root, 'papas.mp4', 600)])
    assert run(root, 'babas.mp4 renderel')[0] == 0
    rc, err = run(root, 'papas.mp4 renderel')
    assert rc == 2 and 'papas.mp4' in err, (rc, err)
    rc, err = run(root, 'nagyi.mp4 renderel')
    assert rc == 2 and 'nagyi.mp4' in err, (rc, err)


@case
def a_frames_directory_counts_by_its_newest_entry(root):
    setup(root)
    d = os.path.join(root, 'frames')
    os.makedirs(d)
    old = time.time() - 900
    os.utime(d, (old, old))
    write_stamp(root, [d])
    assert run(root, 'renderelődik a jelenet')[0] == 2, 'an old, empty frames dir is no proof'
    with open(os.path.join(d, 'f0001.png'), 'wb') as f:
        f.write(b'x')
    assert run(root, 'renderelődik a jelenet')[0] == 0


@case
def plans_past_forms_and_other_texts_pass(root):
    setup(root)
    for text in ["Dave indítja a renderelést 10:30-kor.", 'A babás renderelt, kész: babas.mp4.',
                 'A renderelés kész.', 'Holnap exportált anyagot küldök.', 'Készül a szöveg, délre kész.']:
        rc, err = run(root, text)
        assert rc == 0, (text, rc, err)


@case
def inflections_accents_and_zero_width_are_caught(root):
    setup(root)
    for text in ['Most RENDERELÜNK.', 'renderelnek a gépek', 'rende​rel', 'Exportalok most',
                 'a render most fut', 'Készül a gépen a film.', 'renderel']:
        rc, err = run(root, text)
        assert rc == 2, (text, rc, err)


@case
def other_chats_and_malformed_payloads_pass(root):
    setup(root)
    assert run(root, THE_0906, chat=OTHER)[0] == 0
    assert run(root, '', raw='not json')[0] == 0


@case
def output_of_reads_each_render_command(root):
    assert output_of('node render.mjs /w/film export --x 1 /w/out/a.mp4') == '/w/out/a.mp4'
    assert output_of('node render.mjs /w/film frames 0,100') == '/w/film'
    assert output_of('/Applications/Blender.app/Contents/MacOS/Blender -b x.blend -o /w/seq/f#### -a') == '/w/seq'
    assert output_of('/opt/homebrew/bin/ffmpeg -i a.mov -c:v libx264 /w/out/b.mp4') == '/w/out/b.mp4'
    assert output_of('/Applications/Blender.app/Contents/MacOS/Blender -b x.blend -o') is None
    assert output_of('node render.mjs /w/film export') is None


@case
def a_relative_output_resolves_against_the_process_cwd(root):
    # Live 10:3x: ffmpeg was given out/tt/x.mp4 and the stamp resolved it against the measuring tool's directory.
    cwd = os.path.join(root, 'proc')
    os.makedirs(cwd)
    child = subprocess.Popen(['sleep', '30'], cwd=cwd)
    try:
        got = output_of_process(child.pid, 'ffmpeg -v error -i a.mov -c:v libx264 out/tt/c.mp4')
    finally:
        child.kill()
        child.wait()
    want = os.path.join(os.path.realpath(cwd), 'out', 'tt', 'c.mp4') if lsof_path() else None
    assert got == want, (got, want)
    assert output_of_process(child.pid, 'ffmpeg -i a.mov /w/out/d.mp4') == '/w/out/d.mp4'
    # A relative path that reaches the stamp anyway is dropped, not guessed.
    setup(root)
    write_stamp(root, ['out/x.mp4', '/w/out/y.mp4', None])
    assert read_stamp(root)[1] == ['/w/out/y.mp4'], read_stamp(root)


# --- Drawing / generation claims (Klodel 35719, Patrik TG 4424) ---
# The 10:27 reply, word for word: the order only waited in Dave's queue, no fal-gen ran.
THE_1027 = 'a papás új rajzai most a háttérben készülnek'


@case
def the_1027_reply_is_blocked_when_nothing_generates(root):
    got = GATE.problem(THE_1027, gen_outputs=[])
    assert got and 'nem fut fal-gen' in got[0] and got[1] == GATE.GEN_HINT, got
    assert "kiadtam Dave-nek" in GATE.GEN_HINT


@case
def the_1027_reply_is_blocked_when_the_generation_output_is_stale(root):
    stale = output(root, 'rajz-1.png', 12 * 60)
    old = time.time() - 12 * 60
    os.utime(os.path.dirname(stale), (old, old))  # the directory itself was last changed then too
    got = GATE.problem(THE_1027, gen_outputs=[os.path.dirname(stale)])
    assert got and 'nem íródott' in got[0], got


@case
def a_running_generation_with_a_fresh_output_lets_the_claim_go(root):
    fresh = output(root, 'rajz-2.png', 10)
    for text in [THE_1027, 'A fal most rajzolja a 3. jelenetet.', 'Generálódnak a képek.']:
        assert GATE.problem(text, gen_outputs=[os.path.dirname(fresh)]) is None, text


@case
def generation_inflections_are_caught(root):
    for text in [THE_1027, 'rajzolja a fal', 'generálódnak a képek', 'Most generálom', 'készülnek a rajzok',
                 'a képek most készülnek', 'megrajzolja a borítót', 'A HÁTTÉRBEN KÉSZÜL', 'rajzol​ódnak']:
        assert GATE.gen_claims(text), text


@case
def generation_plans_and_past_forms_pass(root):
    for text in ['Kiadtam Dave-nek a papás rajzait.', 'A rajzok elkészültek: 12 kép.', 'Lerajzolta, kész.',
                 'A generált képek a mappában.', 'Készül a szöveg, délre kész.', 'A képernyőkép kész.']:
        assert not GATE.gen_claims(text) and GATE.problem(text, gen_outputs=[]) is None, text


@case
def a_generation_claim_through_the_hook_gets_its_own_hint(root):
    # Through the real hook (the MacBook makes it deterministic: blocked whatever runs on this machine).
    setup(root)
    rc, err = run(root, THE_1027 + ', a MacBook-mappába')
    assert rc == 2 and "kiadtam Dave-nek" in err, (rc, err)


@case
def generation_output_reads_fal_gen_blender_and_ffmpeg(root):
    cwd = os.path.join(root, 'work')
    os.makedirs(cwd)
    with open(os.path.join(cwd, 'job.json'), 'w', encoding='utf-8') as f:
        json.dump({'endpoint': 'x', 'out_dir': 'out/papa'}, f)
    want = os.path.join(cwd, 'out', 'papa')
    assert generation_output('node fal-gen.mjs run job.json', cwd) == want
    # fal-gen resolves a relative out_dir against its own cwd: unknown cwd -> unknown output (gate closed).
    assert generation_output('node /t/fal-gen.mjs tts ' + os.path.join(cwd, 'job.json'), None) is None
    with open(os.path.join(cwd, 'abs.json'), 'w', encoding='utf-8') as f:
        json.dump({'out_dir': '/w/out/mama'}, f)
    assert generation_output('node /t/fal-gen.mjs run ' + os.path.join(cwd, 'abs.json'), None) == '/w/out/mama'
    assert generation_output('node fal-gen.mjs run job.json --dry', cwd) is None
    assert generation_output('node fal-gen.mjs status', cwd) is None
    assert generation_output('node fal-gen.mjs run missing.json', cwd) is None
    assert generation_output('/opt/homebrew/bin/ffmpeg -i a.mov out/b.mp4', cwd) == os.path.join(cwd, 'out', 'b.mp4')
    assert generation_output('/opt/homebrew/bin/ffmpeg -i a.mov out/b.mp4', None) is None
    assert generation_output('/Applications/Blender.app/Contents/MacOS/Blender -b x.blend -o /w/seq/f####', cwd) == '/w/seq'
    assert is_generation('node fal-gen.mjs run job.json') and not is_generation('node render.mjs /w export /w/a.mp4')


# --- Ready-time claims (Klodel 40023, Patrik TG 5709): an estimate passed on as a ready time --------------------------
THE_1105 = 'A képek becslés szerint (Dave szerint) 11:45-12:00 körül lesznek készek.'  # 11-13 11:05, word for word in spirit
GOOD_MERVE = '\nMÉRVE: 2 perc/darab (out/papas.mp4, mtime 11:43)'


def run_tool(root, text, tool, chat=GROUP):
    payload = json.dumps({'tool_name': tool, 'tool_input': {'chat_id': chat, 'text': text}})
    return run(root, text, chat=chat, raw=payload)


@case
def NEG_the_1105_estimate_is_blocked_without_a_merve_line(root):
    setup(root)
    rc, err = run_tool(root, THE_1105, 'mcp__plugin_telegram_telegram__reply')
    assert rc == 2 and 'KÉSZ-IDŐPONT-KAPU' in err and "szólok, ha kész" in err, (rc, err)


@case
def NEG_every_ready_time_shape_blocks_in_both_owner_chats(root):
    setup(root)
    for text in ['A papás videó 11:45-re kész.', 'Dave becslése szerint a render 12:00 körül kész lesz.',
                 'A képek kb. 2 óra múlva készek.', 'A render 20 perc múlva elkészül.',
                 'Az export Dave becslése szerint kb. 10 perc, amint kész, küldöm.']:
        for chat in (GROUP, PRIV):
            rc, err = run_tool(root, text, 'mcp__plugin_telegram_telegram__reply', chat=chat)
            assert rc == 2 and 'KÉSZ-IDŐPONT-KAPU' in err, (text, chat, rc, err)


@case
def NEG_a_merve_line_without_a_source_or_duration_still_blocks(root):
    setup(root)
    for line in ['\nMÉRVE: 2 perc/darab', '\nMÉRVE: (out/papas.mp4)', '\nMÉRVE: Dave szerint']:
        rc, err = run_tool(root, 'A papás videó 11:45-re kész.' + line, 'mcp__plugin_telegram_telegram__reply')
        assert rc == 2, (line, rc, err)


@case
def a_measured_piece_time_lets_the_ready_time_go(root):
    setup(root)
    for text in ['A papás videó 11:45-re kész.' + GOOD_MERVE, THE_1105 + '\nMÉRVE: 40 mp/kép (out/kepek/, mtime 11:02)']:
        rc, err = run_tool(root, text, 'mcp__plugin_telegram_telegram__reply')
        assert rc == 0, (text, rc, err)


@case
def past_tense_stamps_and_other_work_are_not_ready_time_claims(root):
    setup(root)
    for text in ['A videó kész, itt van.', 'A videó 14:17-re elkészült.', 'A videó 12:00-ra kész volt.', 'Holnap 10:00-kor megbeszéljük a videót.',
                 'A számla 12:00-ra kész.', '21:38, MÉRVE: Dave: az adatbázis rész kész.',
                 'Mágnes 13:30-ra kéthetes tervet készít, az első 6 videóval.']:
        rc, err = run_tool(root, text, 'mcp__plugin_telegram_telegram__reply')
        assert rc == 0, (text, rc, err)


@case
def the_ready_time_rule_skips_edit_message_and_foreign_chats(root):
    setup(root)
    assert run_tool(root, THE_1105, 'mcp__plugin_telegram_telegram__edit_message')[0] == 0
    assert run_tool(root, THE_1105, 'mcp__plugin_telegram_telegram__reply', chat=OTHER)[0] == 0


# Conditional video work (Klodel 40261, TG 5790/5793). The 12:39 reply (conversation_log 14979), shortened only where
# it does not matter: the reel is done, a question to Patrik, and the export parked on his answer.
THE_1239 = ('A Meséld el! reel kész, az ugrást kijavítottuk. Egy kérdés, mielőtt a végleges megy: Cseréljük? '
            'Közben a marabel.hu felirat nagyobb lesz. A te igened után 12 perc, és küldöm.')
REPLY = 'mcp__plugin_telegram_telegram__reply'


@case
def NEG_the_1239_reply_is_blocked_in_both_owner_chats(root):
    setup(root)
    for chat in (GROUP, PRIV):
        rc, err = run_tool(root, THE_1239, REPLY, chat=chat)
        assert rc == 2 and 'FELTÉTELES-RENDER-KAPU' in err and 'kérdés közben fusson' in err, (chat, rc, err)


@case
def NEG_other_answer_conditions_on_video_work_block(root):
    setup(root)
    for text in ['A jeleneteket előbb neked küldöm, és csak a te jóváhagyásod után áll össze belőle a film.',
                 'Ha mehet, indul a render, kb. 10 perc.', 'A videó az igenedre vár: ha rábólintasz, küldöm.']:
        rc, err = run_tool(root, text, REPLY)
        assert rc == 2 and 'FELTÉTELES-RENDER-KAPU' in err, (text, rc, err)


@case
def NEG_a_render_line_with_a_pid_that_is_not_an_export_blocks(root):
    setup(root)
    rc, err = run_tool(root, THE_1239 + '\nRENDER: fut 1', REPLY)  # pid 1 is launchd/init, never an export
    assert rc == 2 and 'nem export' in err, (rc, err)


@case
def NEG_a_nem_kell_line_needs_a_reason(root):
    setup(root)
    rc, err = run_tool(root, THE_1239 + '\nRENDER: nem-kell kész', REPLY)
    assert rc == 2, (rc, err)


@case
def a_reasoned_nem_kell_line_lets_it_go(root):
    setup(root)
    rc, err = run_tool(root, THE_1239 + '\nRENDER: nem-kell a film kész, csak a feltöltés vár a válaszra', REPLY)
    assert rc == 0, (rc, err)


# ops/ is install-local (gitignored), so the test puts a stand-in there with the same contract: exports() -> rows whose
# first field is the pid. The last case below runs the install's real script when this machine has it.
STAND_IN = '''import subprocess
def exports():
    out = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True, text=True).stdout
    return [(ln.split(None, 1)[0], '', '', '') for ln in out.splitlines()
            if 'render.mjs' in ln and ' export ' in ln + ' ' and ln.split(None, 1)[1].startswith('node ')]
'''
REAL_VES = '/Users/klodel/marveen/ops/video_export_status.py'


def fake_export():
    # "node render.mjs film export out.mp4" in ps, via exec -a: what ops/video_export_status.py counts as an export.
    p = subprocess.Popen(['/bin/bash', '-c', 'exec -a "node render.mjs film export out.mp4" sleep 30'])
    time.sleep(0.3)
    return p


@case
def a_running_export_pid_measured_now_lets_it_go(root):
    setup(root)
    os.makedirs(os.path.join(root, 'ops'))
    with open(os.path.join(root, 'ops', 'video_export_status.py'), 'w') as f:
        f.write(STAND_IN)
    p = fake_export()
    try:
        rc, err = run_tool(root, THE_1239 + f'\nRENDER: fut {p.pid}', REPLY)
        assert rc == 0, (rc, err)
    finally:
        p.kill()
        p.wait()
    rc, err = run_tool(root, THE_1239 + f'\nRENDER: fut {p.pid}', REPLY)
    assert rc == 2 and 'nem export' in err, ('the same pid after the export ended', rc, err)


@case
def NEG_no_export_status_script_means_no_pid_passes(root):
    setup(root)  # no ops/ at all: fail closed
    p = fake_export()
    try:
        rc, err = run_tool(root, THE_1239 + f'\nRENDER: fut {p.pid}', REPLY)
        assert rc == 2, (rc, err)
    finally:
        p.kill()
        p.wait()


def put_ops(root, body, mode=0o644):
    os.makedirs(os.path.join(root, 'ops'), exist_ok=True)
    path = os.path.join(root, 'ops', 'video_export_status.py')
    with open(path, 'w') as f:
        f.write(body)
    os.chmod(path, mode)
    return path


def run_with_ops(root, body, mode=0o644):
    """The 12:39 text with a RENDER: fut line for a live fake export, against the given ops script."""
    setup(root)
    put_ops(root, body, mode)
    p = fake_export()
    try:
        t0 = time.time()
        payload = json.dumps({'tool_name': REPLY, 'tool_input': {'chat_id': GROUP, 'text': THE_1239 + f'\nRENDER: fut {p.pid}'}})
        env = {'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root}
        r = subprocess.run([sys.executable, '-I', HOOK], input=payload, capture_output=True, text=True, env=env, timeout=20)
        return r.returncode, r.stdout, r.stderr, time.time() - t0
    finally:
        p.kill()
        p.wait()


@case
def NEG_a_system_exit_in_the_status_script_does_not_open_the_gate(root):
    # Viktor 40283 LOW 1: SystemExit is a BaseException; at module level and inside exports().
    for body in ['import sys\nsys.exit(0)\n', 'def exports():\n    raise SystemExit(0)\n', 'def exports():\n    raise KeyboardInterrupt\n']:
        rc, out, err, _ = run_with_ops(root, body)
        assert rc == 2 and 'nem export' in err, (body, rc, err)


@case
def NEG_a_stuck_status_script_blocks_in_time(root):
    # Viktor 40283 LOW 2: the hook has 10 s; a stuck lookup gives up after EXPORT_LOOKUP_S and blocks.
    rc, out, err, took = run_with_ops(root, 'import time\ndef exports():\n    time.sleep(30)\n    return []\n')
    assert rc == 2 and took < 8, (rc, took, err)


@case
def NEG_the_status_script_cannot_speak_for_the_hook(root):
    # Viktor 40283 INFO 1: whatever the module prints never becomes the hook's stdout.
    body = 'print(\'{"decision": "approve"}\')\n' + STAND_IN
    rc, out, err, _ = run_with_ops(root, body)
    assert rc == 0 and out.strip() == '', (rc, out, err)


@case
def NEG_an_untrusted_status_script_is_not_loaded(root):
    # group-writable, or a symlink to a valid script: not loaded, so no pid passes.
    rc, out, err, _ = run_with_ops(root, STAND_IN, mode=0o664)
    assert rc == 2, ('group-writable', rc, err)
    setup(root)
    real = os.path.join(root, 'elsewhere.py')
    with open(real, 'w') as f:
        f.write(STAND_IN)
    os.makedirs(os.path.join(root, 'ops'), exist_ok=True)
    link = os.path.join(root, 'ops', 'video_export_status.py')
    if os.path.lexists(link):
        os.remove(link)
    os.symlink(real, link)
    p = fake_export()
    try:
        rc, err = run_tool(root, THE_1239 + f'\nRENDER: fut {p.pid}', REPLY)
        assert rc == 2, ('symlink', rc, err)
    finally:
        p.kill()
        p.wait()
    assert not os.path.isdir(os.path.join(root, 'ops', '__pycache__')), 'no bytecode written next to ops/'


@case
def the_install_real_export_status_script_agrees(root):
    if not os.path.isfile(REAL_VES):
        print('     (skip: no install ops/video_export_status.py on this machine)')
        return
    setup(root)
    os.makedirs(os.path.join(root, 'ops'))
    with open(REAL_VES) as src, open(os.path.join(root, 'ops', 'video_export_status.py'), 'w') as dst:
        dst.write(src.read())
    p = fake_export()
    try:
        rc, err = run_tool(root, THE_1239 + f'\nRENDER: fut {p.pid}', REPLY)
        assert rc == 0, (rc, err)
    finally:
        p.kill()
        p.wait()


@case
def questions_finished_work_and_other_conditions_pass(root):
    setup(root)
    for text in ['A reel kész, itt van.', 'Tetszik a videó? A zene maradhat?', 'Ha mehet, küldöm a számlát.',
                 'A film kész. Ha mehet, Mira feltölti?', 'Lex szerint a szöveg rendben van, cseréljük?']:
        rc, err = run_tool(root, text, REPLY)
        assert rc == 0 or 'FELTÉTELES-RENDER-KAPU' not in err, (text, rc, err)
    # the edit of the live status card and foreign chats are not gated by this rule
    assert run_tool(root, THE_1239, 'mcp__plugin_telegram_telegram__edit_message')[0] == 0
    assert run_tool(root, THE_1239, REPLY, chat=OTHER)[0] == 0


def main():
    failed = 0
    for fn in CASES:
        with tempfile.TemporaryDirectory() as root:
            try:
                fn(root)
                print(f'ok   {fn.__name__}')
            except AssertionError as e:
                failed += 1
                print(f'FAIL {fn.__name__}: {e}')
    print(f'{len(CASES) - failed}/{len(CASES)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
