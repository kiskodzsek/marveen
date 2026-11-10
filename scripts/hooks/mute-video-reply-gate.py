#!/usr/bin/env python3
"""PreToolUse gate (telegram reply): no video without an audio track.

Why: Patrik TG 4483 (2026-11-10): "a babás csak egy gif, ez jo igy?". A video with no audio stream reaches Telegram
as an animation (a looping GIF without player controls), not as a film. Klodel 35741 asked for a gate: a silent
.mp4/.mov is blocked, and the fix is a silent AAC track (ffmpeg anullsrc), which makes it a real video.

What blocks (exit 2, one line per file): a reply whose `files` carry an .mp4/.mov/.m4v that has no audio track.
How it is measured, without trusting the file name:
  1. a pure-Python read of the ISO-BMFF boxes: moov -> trak -> mdia -> hdlr; a track whose handler type is 'soun'
     is audio. moov may sit at the end of the file (no faststart), 64-bit box sizes are read. This runs everywhere
     (CI has no ffmpeg) and matches ffprobe on the files the tests build;
  2. when the boxes cannot be read (not ISO-BMFF, truncated, no moov), ffprobe decides (`-select_streams a`);
  3. when neither can tell, the reply is blocked with that reason (fail-closed: the reply goes to Patrik's chats).
A missing file is left to the Telegram tool's own error. Other files (images, .gif, .webm, documents) pass.
A malformed hook payload is allowed (nothing to read).

Wiring: .claude/settings.json PreToolUse, matcher "mcp__plugin_telegram_telegram__reply" (edit_message carries no
files). Tests: mute-video-reply-gate_test.py next to this file.
"""
import json
import os
import shutil
import struct
import subprocess
import sys

VIDEO_EXT = ('.mp4', '.mov', '.m4v')
FFPROBE_PATHS = ('/opt/homebrew/bin/ffprobe', '/usr/local/bin/ffprobe', '/usr/bin/ffprobe')
CONTAINERS = {b'moov', b'trak', b'mdia'}
MAX_BOXES = 100_000  # a corrupt file cannot loop the reader forever

FIX = ('tegyél alá néma AAC-sávot: ffmpeg -i be.mp4 -f lavfi -i anullsrc=r=48000:cl=stereo -c:v copy -c:a aac '
       '-shortest ki.mp4')


def _boxes(f, start, end):
    """Yield (type, payload_start, box_end) for the boxes in [start, end)."""
    pos, n = start, 0
    while pos + 8 <= end and n < MAX_BOXES:
        n += 1
        f.seek(pos)
        head = f.read(8)
        if len(head) < 8:
            return
        size, kind = struct.unpack('>I4s', head)
        hdr = 8
        if size == 1:
            big = f.read(8)
            if len(big) < 8:
                return
            size, hdr = struct.unpack('>Q', big)[0], 16
        elif size == 0:
            size = end - pos
        if size < hdr or pos + size > end:
            raise ValueError('box out of bounds')
        yield kind, pos + hdr, pos + size
        pos += size


def audio_by_boxes(path):
    """True/False: the file has / has no audio track; None: the ISO-BMFF boxes cannot be read."""
    try:
        with open(path, 'rb') as f:
            end = os.fstat(f.fileno()).st_size
            handlers, saw_moov = [], False

            def walk(start, stop):
                nonlocal saw_moov
                for kind, body, box_end in _boxes(f, start, stop):
                    if kind == b'moov':
                        saw_moov = True
                    if kind in CONTAINERS:
                        walk(body, box_end)
                    elif kind == b'hdlr' and box_end - body >= 12:
                        f.seek(body + 8)  # version+flags (4), pre_defined (4), handler_type (4)
                        handlers.append(f.read(4))

            walk(0, end)
            if not saw_moov:
                return None
            return b'soun' in handlers
    except (OSError, ValueError, struct.error):
        return None


def audio_by_ffprobe(path):
    """True/False from ffprobe's audio streams; None when ffprobe is missing or fails."""
    probe = shutil.which('ffprobe') or next((p for p in FFPROBE_PATHS if os.path.exists(p)), None)
    if not probe:
        return None
    try:
        r = subprocess.run([probe, '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index',
                            '-of', 'json', path], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        return bool(json.loads(r.stdout or '{}').get('streams'))
    except ValueError:
        return None


def has_audio(path):
    found = audio_by_boxes(path)
    return found if found is not None else audio_by_ffprobe(path)


def check(path):
    """None if the file may go; otherwise the reason it may not."""
    if not str(path).lower().endswith(VIDEO_EXT) or not os.path.isfile(path):
        return None
    found = has_audio(path)
    name = os.path.basename(path)
    if found is True:
        return None
    if found is False:
        return f'{name}: nincs hangsáv, a Telegram GIF-ként mutatja, nem videóként (Patrik TG 4483); {FIX}'
    return f'{name}: a hangsávot nem tudom megmérni (nem olvasható MP4/MOV, ffprobe sincs); ellenőrizd, és {FIX}'


def main():
    try:
        ti = json.load(sys.stdin).get('tool_input') or {}
    except Exception:
        return 0
    files = ti.get('files') or []
    if not isinstance(files, list):
        return 0
    errs = [e for e in (check(str(p)) for p in files) if e]
    if errs:
        sys.stderr.write('NÉMA-VIDEÓ-KAPU (Klodel 35741): ' + '\n'.join(errs) + '\n')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
