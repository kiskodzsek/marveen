#!/usr/bin/env python3
"""Tests for mute-video-reply-gate.py (Klodel 35741, Patrik TG 4483: "a babás csak egy gif, ez jo igy?").

Hermetic part (runs in CI, no ffmpeg): synthetic ISO-BMFF files built box by box -- a video-only file is blocked,
a video+audio file passes, moov at the end and 64-bit box sizes are read, a non-MP4 falls back to ffprobe and,
without it, is blocked. Real part (only where ffmpeg/ffprobe exist, e.g. the Mac mini): a silent H.264 mp4 is
blocked, the same with an anullsrc AAC track passes, and the box reader agrees with ffprobe on both.

Run: python3 -I scripts/hooks/mute-video-reply-gate_test.py
"""
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, 'mute-video-reply-gate.py')
spec = importlib.util.spec_from_file_location('gate', GATE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

FAILS = 0
N = 0


def ok(name, cond, detail=''):
    global FAILS, N
    N += 1
    if cond:
        print(f'PASS  {name}')
    else:
        FAILS += 1
        print(f'FAIL  {name}' + (f'  -- {detail}' if detail else ''))


def box(kind, payload=b''):
    return struct.pack('>I4s', 8 + len(payload), kind) + payload


def box64(kind, payload=b''):
    return struct.pack('>I4sQ', 1, kind, 16 + len(payload)) + payload


def hdlr(handler):
    return box(b'hdlr', b'\x00\x00\x00\x00' + b'\x00\x00\x00\x00' + handler + b'\x00' * 12 + b'name\x00')


def trak(handler):
    return box(b'trak', box(b'tkhd', b'\x00' * 84) + box(b'mdia', box(b'mdhd', b'\x00' * 24) + hdlr(handler)
                                                       + box(b'minf', hdlr(b'alis'))))


def mp4(tracks, moov_last=False, big_mdat=False):
    ftyp = box(b'ftyp', b'isom\x00\x00\x02\x00isomiso2mp41')
    meta = box(b'udta', box(b'meta', b'\x00' * 4 + hdlr(b'mdir')))  # a 'mdir' handler outside any track
    moov = box(b'moov', box(b'mvhd', b'\x00' * 100) + b''.join(trak(h) for h in tracks) + meta)
    mdat = (box64 if big_mdat else box)(b'mdat', b'\x00' * 64)
    return ftyp + (mdat + moov if moov_last else moov + mdat)


TMP = tempfile.mkdtemp(prefix='mutevideo-')


def write(name, data):
    p = os.path.join(TMP, name)
    with open(p, 'wb') as f:
        f.write(data)
    return p


def run_hook(payload):
    r = subprocess.run([sys.executable, '-I', GATE], input=payload if isinstance(payload, str) else json.dumps(payload),
                       capture_output=True, text=True, timeout=60)
    return r.returncode, r.stderr


def reply(*files):
    return {'tool_name': 'mcp__plugin_telegram_telegram__reply',
            'tool_input': {'chat_id': '1', 'text': 'film', 'files': list(files)}}


# ---- hermetic: the box reader ----
silent = write('silent.mp4', mp4([b'vide']))
sound = write('sound.mp4', mp4([b'vide', b'soun']))
ok('box reader: video only -> no audio', gate.audio_by_boxes(silent) is False)
ok('box reader: video + soun -> audio', gate.audio_by_boxes(sound) is True)
ok('box reader: the minf data handler (alis) and udta/meta (mdir) are not audio',
   gate.audio_by_boxes(write('alis.mov', mp4([b'vide']))) is False)
ok('box reader: moov at the end (no faststart)', gate.audio_by_boxes(write('late.mp4', mp4([b'vide', b'soun'], moov_last=True))) is True)
ok('box reader: 64-bit mdat size', gate.audio_by_boxes(write('big.mp4', mp4([b'vide'], big_mdat=True))) is False)
ok('box reader: audio-only track list still audio', gate.audio_by_boxes(write('a.m4v', mp4([b'soun']))) is True)
ok('box reader: not ISO-BMFF -> None', gate.audio_by_boxes(write('junk.mp4', b'not a video at all, just bytes')) is None)
ok('box reader: truncated box -> None', gate.audio_by_boxes(write('trunc.mp4', mp4([b'vide'])[:40])) is None)
ok('box reader: no moov -> None', gate.audio_by_boxes(write('nomoov.mp4', box(b'ftyp', b'isom') + box(b'mdat', b'x' * 10))) is None)

# ---- hermetic: the hook ----
rc, err = run_hook(reply(silent))
ok('hook: silent mp4 -> blocked (exit 2)', rc == 2, f'rc={rc}')
ok('  ...names the file, the GIF effect and the anullsrc fix', 'silent.mp4' in err and 'GIF' in err and 'anullsrc' in err, err)
rc, err = run_hook(reply(sound))
ok('hook: mp4 with an audio track -> passes', rc == 0, f'rc={rc} {err}')
rc, err = run_hook(reply(write('silent.MOV', mp4([b'vide']))))
ok('hook: upper-case .MOV is gated too', rc == 2, f'rc={rc}')
rc, err = run_hook(reply(sound, silent))
ok('hook: one silent file among several -> blocked', rc == 2 and 'silent.mp4' in err and 'sound.mp4' not in err, err)
img = write('kep.png', b'\x89PNG\r\n\x1a\n')
rc, _ = run_hook(reply(img, write('anim.gif', b'GIF89a'), write('clip.webm', b'\x1aE\xdf\xa3')))
ok('hook: images, .gif, .webm pass untouched', rc == 0)
rc, _ = run_hook(reply(os.path.join(TMP, 'missing.mp4')))
ok('hook: a missing file is left to the tool', rc == 0)
rc, _ = run_hook({'tool_input': {'chat_id': '1', 'text': 'csak szöveg'}})
ok('hook: no files -> passes', rc == 0)
rc, _ = run_hook('not json')
ok('hook: malformed payload -> allowed', rc == 0)

# ffprobe fallback, decided without a real ffprobe: monkeypatch inside this process.
junk = os.path.join(TMP, 'junk.mp4')
orig = gate.audio_by_ffprobe
gate.audio_by_ffprobe = lambda p: None
ok('unreadable boxes, no ffprobe -> blocked (fail-closed)', gate.check(junk) is not None and 'nem tudom megmérni' in gate.check(junk))
gate.audio_by_ffprobe = lambda p: True
ok('unreadable boxes, ffprobe says audio -> passes', gate.check(junk) is None)
gate.audio_by_ffprobe = lambda p: False
ok('unreadable boxes, ffprobe says no audio -> blocked', 'nincs hangsáv' in (gate.check(junk) or ''))
gate.audio_by_ffprobe = orig

# ---- real files (only where ffmpeg + ffprobe exist) ----
ffmpeg = shutil.which('ffmpeg') or next((p for p in ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg') if os.path.exists(p)), None)
if ffmpeg and (shutil.which('ffprobe') or any(os.path.exists(p) for p in gate.FFPROBE_PATHS)):
    real_silent = os.path.join(TMP, 'real-silent.mp4')
    real_sound = os.path.join(TMP, 'real-anullsrc.mp4')
    real_late = os.path.join(TMP, 'real-anullsrc-late.mov')
    base = [ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=white:s=160x284:d=1']
    subprocess.run(base + ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', real_silent], check=True)
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-i', real_silent, '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
                    '-c:v', 'copy', '-c:a', 'aac', '-shortest', real_sound], check=True)
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-i', real_sound, '-c', 'copy', real_late], check=True)
    rc, err = run_hook(reply(real_silent))
    ok('real: ffmpeg silent H.264 mp4 -> blocked', rc == 2, f'rc={rc}')
    rc, err = run_hook(reply(real_sound))
    ok('real: the same with an anullsrc AAC track -> passes', rc == 0, f'rc={rc} {err}')
    rc, err = run_hook(reply(real_late))
    ok('real: .mov remux (moov at the end) with audio -> passes', rc == 0, f'rc={rc} {err}')
    for p in (real_silent, real_sound, real_late):
        ok(f'real: box reader agrees with ffprobe on {os.path.basename(p)}',
           gate.audio_by_boxes(p) == gate.audio_by_ffprobe(p) and gate.audio_by_boxes(p) is not None,
           f'boxes={gate.audio_by_boxes(p)} ffprobe={gate.audio_by_ffprobe(p)}')
else:
    print('SKIP  real-file cases: no ffmpeg/ffprobe on this machine (the hermetic cases above still ran)')

shutil.rmtree(TMP, ignore_errors=True)
print(f'---\n{N - FAILS}/{N} passed')
sys.exit(1 if FAILS else 0)
