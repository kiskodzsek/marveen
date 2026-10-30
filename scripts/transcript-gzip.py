#!/usr/bin/env python3
"""transcript-gzip.py -- gzip the agents' old Claude Code session transcripts in place.

    transcript-gzip.py --install-dir DIR [--home DIR] [--days N] [--min-free-gb G]
                       [--lsof PATH] [--now EPOCH] [--dry-run]

Why (card c310dd1b, Klodel 21739, 2026-10-30): the session transcripts were
6.9 GB of the full data volume (Dave 3.6, Pulzus 1.6). Gzipping the ones older
than 7 days by hand gave back 3.0 GB; Klodel asked for the same every night.

What is looked at: every *.jsonl under <install>/agents/*/.claude-config/projects
and <home>/.claude/projects (the main agent's), each root once after symlinks are
resolved. A directory named memory is never entered, and nothing but *.jsonl is
touched (a session's subagent transcripts are *.jsonl under its directory too).

A transcript is gzipped (`gzip -9`: the mtime stays, file.jsonl becomes
file.jsonl.gz, the original goes only on success) when its mtime is older than
--days days (default 7, at least 2: today's and yesterday's always stay), no
process has it open (lsof; when lsof cannot be run, nothing is gzipped), and
the free disk is at least --min-free-gb (default 3) before it starts, so the
.gz written beside the original cannot fill the disk. Right before each gzip
the file is looked at again (mtime, and `lsof -t -- <file>`): a session
resumed while the run goes would otherwise append to the deleted original
(Viktor 21765 L1). A file whose .gz already exists (a `gunzip -k` by hand) is
skipped, not failed.

The cost, accepted by Klodel 21739: a gzipped session can no longer be resumed
(`claude --resume` does not read .gz). `gunzip <file>` brings it back.

Output: one "gzip <path>" line per file, then one summary line
"gzipped=N mb_before=A mb_after=B open=O exists=E". Exit 0, 1 when a gzip failed (the
rest still ran), 2 on bad arguments.
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import time


def roots(install, home):
    found, seen = [], set()
    for path in sorted(glob.glob(os.path.join(install, "agents", "*", ".claude-config", "projects"))) + [os.path.join(home, ".claude", "projects")]:
        resolved = os.path.realpath(path)
        if os.path.isdir(resolved) and resolved not in seen:
            seen.add(resolved)
            found.append(resolved)
    return found


def open_files(lsof):
    """The resolved paths of every open *.jsonl, or None when lsof cannot be run."""
    try:
        out = subprocess.run([lsof, "-n", "-P", "-Fn"], capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode not in (0, 1) or not out.stdout:
        return None
    return {os.path.realpath(line[1:]) for line in out.stdout.splitlines() if line.startswith("n/") and line.endswith(".jsonl")}


def still_closed(lsof, path, newer_than):
    """Looked at again right before the gzip: unchanged since the walk, and no process has it open."""
    try:
        if os.lstat(path).st_mtime > newer_than:
            return False
        out = subprocess.run([lsof, "-t", "--", path], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    # lsof -t: rc 0 and pids when open, rc 1 and nothing when not; anything else: do not touch it.
    return out.returncode == 1 and not out.stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-dir", required=True)
    parser.add_argument("--home", default=os.path.expanduser("~"))
    parser.add_argument("--days", type=float, default=7)
    parser.add_argument("--min-free-gb", type=float, default=3)
    parser.add_argument("--lsof", default="/usr/sbin/lsof")
    parser.add_argument("--now", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.days < 2:
        print("stop: --days must be at least 2 (today's and yesterday's transcripts stay)")
        return 2
    now = args.now if args.now is not None else time.time()
    opened = open_files(args.lsof)
    if opened is None:
        print(f"stop: lsof unavailable ({args.lsof}): nothing gzipped")
        print("gzipped=0 mb_before=0 mb_after=0 open=0 exists=0")
        return 0

    gzipped = failed = busy = exists = 0
    before = after = 0
    for root in roots(os.path.realpath(args.install_dir), args.home):
        for dirpath, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if d != "memory" and not os.path.islink(os.path.join(dirpath, d))]
            for name in files:
                path = os.path.join(dirpath, name)
                if not name.endswith(".jsonl") or os.path.islink(path):
                    continue
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                if st.st_mtime > now - args.days * 86400:
                    continue
                if os.path.realpath(path) in opened:
                    busy += 1
                    continue
                if os.path.lexists(path + ".gz"):
                    exists += 1
                    continue
                if shutil.disk_usage(dirpath).free < args.min_free_gb * 1024 ** 3:
                    print(f"stop: under {args.min_free_gb:g} GiB free")
                    print(f"gzipped={gzipped} mb_before={before // 2**20} mb_after={after // 2**20} open={busy} exists={exists}")
                    return failed
                print(f"gzip {path}")
                if args.dry_run:
                    gzipped += 1
                    before += st.st_size
                    continue
                if not still_closed(args.lsof, path, now - args.days * 86400):
                    busy += 1
                    continue
                if subprocess.run(["gzip", "-9", "--", path], capture_output=True).returncode == 0 and os.path.exists(path + ".gz"):
                    gzipped += 1
                    before += st.st_size
                    after += os.lstat(path + ".gz").st_size
                else:
                    print(f"failed {path}")
                    failed = 1
    print(f"gzipped={gzipped} mb_before={before // 2**20} mb_after={after // 2**20} open={busy} exists={exists}")
    return failed


if __name__ == "__main__":
    sys.exit(main())
