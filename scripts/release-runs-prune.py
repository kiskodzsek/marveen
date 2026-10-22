#!/usr/bin/env python3
"""release-runs-prune.py -- drop the regenerable source copies of old release runs.

    release-runs-prune.py --release-dir DIR [--days N] [--now EPOCH] [--dry-run]

Why (card 7f6796ef, Pulzus 14571): on 2026-10-22 ops/release/runs held 5.0 GiB
in 192 run directories while the data volume was down to 6 GiB free. 2.9 GiB of
it was the unpacked src/ trees, 2.1 GiB the src.tar.gz tarballs.

What the release engine reads (Pulzus 14571, from the code):
  - src/ is never kept: extract_tarball (release.py) always removes it and
    unpacks the tarball again; migrate.py and the deploy's edge step both
    unpack first.
  - src.tar.gz is read only for the run being executed (migrate.py --run <id>,
    deploy and deploy --resume), and its sha256 must match the ledger. The way
    back (promote the previous deployment) reads nothing under runs/.

The rule, from that:
  - the age of a run is the time since its LAST ledger entry
    (ops/release/ledger.jsonl), not a file mtime;
  - src/ goes when the run is older than --days;
  - src.tar.gz goes only when the run is older than --days AND closed: one of
    its ledger steps is deployed, deploy_covered_by or merge_stopped. A run
    that stopped in deploy (deploy_stopped) can still be resumed, and a run
    that is merged or migrated but not deployed may still be deployed, so
    their tarballs stay at any age;
  - a run directory with no ledger entry is left alone (no merge, so there is
    nothing to drop, and its age is unknown);
  - every *.json stays: it is the audit trail.

Only directories named like a run id (YYYYMMDD-HHMMSS-xxxx) directly under
runs/ are looked at. Symlinks are never followed or removed: a symlinked src/
or tarball is reported and left.

Output: one "remove <path>" line per removal, then one summary line
"removed_src=N removed_tar=M kept_open=K" (with --dry-run: what would go,
nothing is removed). Exit 0, or 1 when the ledger cannot
be read (then nothing is removed) or a removal failed.
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import time

CLOSED_STEPS = {"deployed", "deploy_covered_by", "merge_stopped"}
RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")


def read_ledger(path):
    """run_id -> (last entry epoch, set of steps). Lines that are not JSON are skipped."""
    runs = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
                run_id = entry.get("run_id")
                ts = dt.datetime.fromisoformat(entry["ts"]).timestamp()
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            if not isinstance(run_id, str):
                continue
            last, steps = runs.get(run_id, (0.0, set()))
            steps.add(entry.get("step"))
            runs[run_id] = (max(last, ts), steps)
    return runs


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--release-dir", required=True)
    ap.add_argument("--days", type=float, default=3)
    ap.add_argument("--now", type=float, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    runs_dir = os.path.join(args.release_dir, "runs")
    ledger = os.path.join(args.release_dir, "ledger.jsonl")
    if not os.path.isdir(runs_dir) or os.path.islink(runs_dir):
        print(f"skip: no {runs_dir}")
        return 0
    try:
        runs = read_ledger(ledger)
    except OSError as err:
        print(f"stop: the ledger cannot be read ({err.strerror}), nothing removed")
        return 1

    now = args.now if args.now is not None else time.time()
    cutoff = now - args.days * 86400
    removed_src = removed_tar = kept_open = 0
    failed = False
    for name in sorted(os.listdir(runs_dir)):
        run_path = os.path.join(runs_dir, name)
        if not RUN_ID_RE.match(name) or os.path.islink(run_path) or not os.path.isdir(run_path):
            continue
        if name not in runs:
            continue
        last, steps = runs[name]
        if last > cutoff:
            continue
        src = os.path.join(run_path, "src")
        tar = os.path.join(run_path, "src.tar.gz")
        for path, is_dir in ((src, True), (tar, False)):
            if not os.path.lexists(path):
                continue
            if os.path.islink(path):
                print(f"left (symlink): {path}")
                continue
            if not is_dir and not steps & CLOSED_STEPS:
                kept_open += 1
                continue
            if is_dir != os.path.isdir(path):
                print(f"left (unexpected type): {path}")
                continue
            print(f"remove {path}")
            try:
                if is_dir:
                    if not args.dry_run:
                        shutil.rmtree(path)
                    removed_src += 1
                else:
                    if not args.dry_run:
                        os.unlink(path)
                    removed_tar += 1
            except OSError as err:
                print(f"failed: {path}: {err.strerror}")
                failed = True
    print(f"removed_src={removed_src} removed_tar={removed_tar} kept_open={kept_open}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
