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
from render_claim_lib import lsof_path, macbook_out, read_stamp_macbook, output_of, output_of_process, generation_output, is_generation, read_stamp, write_stamp  # noqa: E402
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


def run(root, text, chat=GROUP, raw=None, files=None):
    env = {'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': root}
    ti = {'chat_id': chat, 'text': text}
    if files is not None:
        ti['files'] = files
    payload = raw if raw is not None else json.dumps({'tool_input': ti})
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


# --- MacBook claims are measured, not always blocked (Klodel 35878, 2026-11-10 12:0x) ---
# The 12:0x case: "a MacBook ... exportál" was blocked although the measured result file went with it.
def mac_stamp(root, outs, age_s=5):
    write_stamp(root, [], now=time.time() - age_s, macbook=outs)


@case
def a_macbook_capability_claim_with_its_fresh_result_passes(root):
    setup(root)
    res = output(root, 'aranyevek-tt.mp4', 6 * 60)
    text = f'A MacBook mostantól videót is exportál, mérve 12:00: {res} (178,5 mp).'
    rc, err = run(root, text)
    assert rc == 0, (rc, err)
    rc, err = run(root, 'A MacBook mostantól videót is exportál.', files=[res])
    assert rc == 0, (rc, err)


@case
def a_macbook_claim_with_an_old_or_missing_result_is_blocked(root):
    setup(root)
    old = output(root, 'regi.mp4', 40 * 60)
    for text, files in [(f'A MacBook exportál: {old}', None), ('A MacBook exportál.', None),
                        ('A MacBook exportál.', [os.path.join(root, 'out', 'nincs.mp4')])]:
        rc, err = run(root, text, files=files)
        assert rc == 2 and 'MacBook' in err, (text, rc, err)


@case
def a_progressive_macbook_claim_needs_a_running_export_not_a_file(root):
    setup(root)
    res = output(root, 'papas.mp4', 60)
    for text in [f'A papás most a MacBookon exportál: {res}', 'A MacBookon készül a papás.']:
        rc, err = run(root, text)
        assert rc == 2 and 'MacBook' in err, (text, rc, err)
    mac_stamp(root, ['/w/out/papas.mp4'])
    for text in ['A papás most a MacBookon exportál.', 'A MacBookon készül a papás, papas.mp4.']:
        rc, err = run(root, text)
        assert rc == 0, (text, rc, err)
    rc, err = run(root, 'A MacBookon most exportál a nagyi.mp4')
    assert rc == 2, (rc, err)
    mac_stamp(root, ['/w/out/papas.mp4'], age_s=3 * 60)
    assert run(root, 'A papás most a MacBookon exportál.')[0] == 2, 'an old stamp is no measurement'


@case
def mixed_reply_checks_each_machine_on_its_own(root):
    setup(root)
    write_stamp(root, [output(root, 'babas.mp4', 5)], macbook=['/w/out/papas.mp4'])
    assert run(root, 'a babás most renderel a minin, a papás a MacBookon exportál')[0] == 0
    write_stamp(root, [output(root, 'babas.mp4', 12 * 60)], macbook=['/w/out/papas.mp4'])
    rc, err = run(root, 'a babás most renderel a minin, a papás a MacBookon exportál')
    assert rc == 2 and 'sem íródott' in err, (rc, err)


@case
def macbook_out_reads_the_client_command(root):
    assert macbook_out('/bin/bash /x/tools/remote-render/mac-export.sh /w/film /w/out/a.mp4') == '/w/out/a.mp4'
    assert macbook_out('bash mac-export.sh /w/film out/a.mp4 1920') == 'out/a.mp4'
    assert macbook_out('bash mac-export.sh /w/film') is None
    assert macbook_out('node render.mjs /w/film export /w/a.mp4') is None
    write_stamp(root, [], macbook=['/w/a.mp4', 'rel/b.mp4', None])
    assert read_stamp_macbook(root)[1] == ['/w/a.mp4'], read_stamp_macbook(root)


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
    # Through the real hook (a MacBook clause makes it deterministic: generation there is never measured).
    setup(root)
    rc, err = run(root, 'a MacBook most rajzolja a papás képeit')
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
