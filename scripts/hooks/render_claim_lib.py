"""The measured video-export state the render-claim gate reads (Klodel 35696, Patrik TG 4381).

ops/video_export_status.py (the measuring tool; ops/ is local, not in git) calls write_stamp() on every run, so a
render claim to Patrik can be checked against a measurement, not a memory: store/video-export-status.json holds the
time of the run and the output of every running export (a file for an export, a directory for a frames export or a
Blender render). The gate re-reads each output's mtime at send time: a process that still runs but has not written
for minutes is not "rendering" (the 09:06 case: the target had not been written for 12 minutes).
"""
import json
import os
import shutil
import subprocess
import tempfile
import time

STAMP_NAME = 'video-export-status.json'
MEDIA = ('.mp4', '.mov', '.webm', '.mkv')


def stamp_path(root):
    return os.path.join(root, 'store', STAMP_NAME)


def output_of(cmd):
    """The output a render command writes, or None: render.mjs <dir> export ... <file>, render.mjs <dir> frames,
    Blender -o <path> (its directory), ffmpeg ... <file>. Known limit: the motion-drv style `render.mjs <dir> frames`
    writes its stills into a fresh temp directory, not into <dir>; <dir> then rarely looks fresh, so the gate stays
    closed for a frames claim (the safe direction: a frames check is not a film render)."""
    args = cmd.split()
    if not args:
        return None
    if 'render.mjs' in cmd and 'export' in args:
        return args[-1] if args[-1].endswith(MEDIA) else None
    if 'render.mjs' in cmd and 'frames' in args:
        i = args.index('frames')
        return args[i - 1] if i >= 1 else None
    if args[0].endswith('/Blender') and '-o' in args:
        i = args.index('-o')
        if i + 1 >= len(args):
            return None
        return os.path.dirname(args[i + 1]) or None
    if args[0].endswith('ffmpeg') and args[-1].endswith(MEDIA):
        return args[-1]
    return None


def lsof_path():
    """macOS keeps lsof in /usr/sbin, which an agent shell's PATH may lack (measured 2026-11-10)."""
    return shutil.which('lsof') or ('/usr/sbin/lsof' if os.access('/usr/sbin/lsof', os.X_OK) else None)


def proc_cwd(pid):
    """The working directory of a running process (lsof), or None."""
    lsof = lsof_path()
    if not lsof:
        return None
    try:
        out = subprocess.run([lsof, '-a', '-p', str(pid), '-d', 'cwd', '-Fn'],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if line.startswith('n/'):
            return line[1:]
    return None


def output_of_process(pid, cmd):
    """output_of() made absolute against the process's own working directory (ffmpeg is often given out/x.mp4), not
    against the measuring tool's. An unknown working directory gives None: the gate then stays closed."""
    o = output_of(cmd)
    if not o or os.path.isabs(o):
        return o
    cwd = proc_cwd(pid)
    return os.path.normpath(os.path.join(cwd, o)) if cwd else None


def write_stamp(root, outputs, now=None):
    """outputs: the absolute paths (or None) of the running exports; a relative path is dropped (we cannot know what
    it is relative to). Written atomically, 0644."""
    data = {'v': 1, 'ran_at': time.time() if now is None else now,
            'outputs': [o if o and os.path.isabs(o) else None for o in outputs]}
    d = os.path.join(root, 'store')
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.vexport-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        os.chmod(tmp, 0o644)
        os.replace(tmp, stamp_path(root))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_stamp(root):
    try:
        with open(stamp_path(root), encoding='utf-8') as f:
            d = json.load(f)
        ran = float(d['ran_at'])
        outs = [o for o in d.get('outputs') or [] if isinstance(o, str) and o]
        return ran, outs
    except Exception:
        return None, []


def newest_write(path):
    """The last write under an output: the file's mtime, or for a directory the newest of it and its direct entries."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    if not os.path.isdir(path):
        return st.st_mtime
    newest = st.st_mtime
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    newest = max(newest, e.stat(follow_symlinks=False).st_mtime)
                except OSError:
                    pass
    except OSError:
        pass
    return newest
