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
from render_claim_lib import lsof_path, output_of, output_of_process, read_stamp, write_stamp  # noqa: E402

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
