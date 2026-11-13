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


# --- Generation claims (Klodel 35719, Patrik TG 4424) --------------------------------------------------------------
# 10:27: "a papás új rajzai most a háttérben készülnek" went to Patrik while the order only waited in Dave's queue (no
# fal-gen ran). A drawing / generation claim is measured at send time, here: a running fal-gen.mjs run/tts (not --dry),
# Blender or ffmpeg, and the output it writes (fal-gen: the job's out_dir; Blender/ffmpeg: as output_of()).

def ps_path():
    """ps lives in /bin on macOS and Linux; an agent shell's PATH may be thin."""
    return shutil.which('ps') or ('/bin/ps' if os.access('/bin/ps', os.X_OK) else None)


def processes():
    """[(pid, command)] of the running, not stopped, processes; [] when ps cannot be run (the gate then stays closed)."""
    ps = ps_path()
    if not ps:
        return []
    try:
        out = subprocess.run([ps, '-axo', 'pid=,stat=,command='], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3 or parts[1].startswith(('T', 'Z')):
            continue
        rows.append((parts[0], parts[2]))
    return rows


# --- A render.mjs export writes its file only at the END (Klodel 40352, 2026-11-13 14:12) ---------------------------
# The v10c export ran 13:17-13:28 with no output file (export log), so "the output was written in the last 2 minutes"
# was false for the whole run, and a true "fut" claim and the live status edit were blocked. For a render.mjs export the
# live signal is the export's process tree (node + its Chrome for Testing children) using CPU now, summed %CPU from one
# ps snapshot (measured 14:13 on the v10d run: node 10.9 + Chrome 67.9 + renderer 55.5 + GPU 1.3). A stuck export
# decays toward 0 % CPU and stays blocked. ffmpeg / Blender write as they go: their mtime rule is unchanged.
LIVE_CPU = 10.0


def _ps_tree_rows():
    """[(pid, ppid, stat, pcpu, command)] from one ps snapshot; [] when ps cannot be run."""
    ps = ps_path()
    if not ps:
        return []
    try:
        out = subprocess.run([ps, '-axo', 'pid=,ppid=,stat=,pcpu=,command='], capture_output=True, text=True,
                             timeout=5).stdout
    except Exception:
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            rows.append((parts[0], parts[1], parts[2], float(parts[3].replace(',', '.')), parts[4]))
        except ValueError:
            continue
    return rows


def is_render_export(cmd):
    """node ... <x>render.mjs ... export ... <out>: the executable is node and a render.mjs argument comes before
    'export' (Viktor 40367 LOW: a bare substring let 'grep render.mjs export x.mp4' count). A bash -c / caffeinate
    wrapper does not match; its node child does."""
    args = cmd.split()
    if not args or os.path.basename(args[0]) != 'node' or 'export' not in args:
        return False
    i = args.index('export')
    return any(a.endswith('render.mjs') for a in args[1:i]) and output_of(cmd) is not None


def live_export_outputs(rows=None, min_cpu=LIVE_CPU):
    """The absolute outputs of the running render.mjs exports whose process tree uses at least min_cpu %CPU now."""
    rows = _ps_tree_rows() if rows is None else rows
    kids = {}
    cpu = {}
    for pid, ppid, _stat, pcpu, _cmd in rows:
        kids.setdefault(ppid, []).append(pid)
        cpu[pid] = pcpu
    outs = []
    for pid, _ppid, stat, _pcpu, cmd in rows:
        if stat.startswith(('T', 'Z')) or not is_render_export(cmd):
            continue
        total, todo, seen = 0.0, [pid], set()
        while todo:
            p = todo.pop()
            if p in seen:
                continue
            seen.add(p)
            total += cpu.get(p, 0.0)
            todo.extend(kids.get(p, []))
        if total < min_cpu:
            continue
        o = output_of_process(pid, cmd)
        if o:
            outs.append(os.path.normpath(o))
    return outs


def _absolute(path, cwd):
    if not path:
        return None
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(cwd, path)) if cwd else None


def is_generation(cmd):
    args = cmd.split()
    if not args:
        return False
    if any(a.endswith('fal-gen.mjs') for a in args):
        return True
    return args[0].endswith('/Blender') or args[0].endswith('ffmpeg')


def generation_output(cmd, cwd):
    """The absolute output of a generation command run in cwd, or None (unknown: the gate stays closed).
    fal-gen.mjs run|tts <job.json> -> the job's out_dir (a --dry run generates nothing); Blender/ffmpeg -> output_of()."""
    args = cmd.split()
    for i, a in enumerate(args):
        if a.endswith('fal-gen.mjs'):
            if '--dry' in args or i + 2 >= len(args) or args[i + 1] not in ('run', 'tts'):
                return None
            job = _absolute(args[i + 2], cwd)
            try:
                if not job or os.path.getsize(job) > 1_000_000:
                    return None
                with open(job, encoding='utf-8') as f:
                    out_dir = json.load(f).get('out_dir')
            except Exception:
                return None
            return _absolute(out_dir, cwd) if isinstance(out_dir, str) else None
    if is_generation(cmd):
        return _absolute(output_of(cmd), cwd)
    return None


def running_generation_outputs():
    """The outputs of the generation processes running now (measured, not remembered)."""
    outs = []
    for pid, cmd in processes():
        if not is_generation(cmd):
            continue
        o = generation_output(cmd, proc_cwd(pid))
        if o:
            outs.append(o)
    return outs
