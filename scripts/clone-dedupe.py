#!/usr/bin/env python3
"""Lossless disk reclaim: byte-identical files become APFS clones of one another.

    clone-dedupe.py --root DIR [--root DIR ...] [--min-mb 1] [--min-age-min 60] [--dry-run]

Why (card 152400f3, 2026-11-03 16:3x): the free disk fell to 365 MiB, and the agents' out/ and
shared/ trees held the same renders, photos and PDFs in several places (a pick/, a sel/, a final/
copy of one image). Replacing each extra copy with a clone of the first gave back 1.25 GiB in two
runs, measured with df, with every path and every byte still there.

A clone shares the data blocks on APFS (cp -c, clonefile(2)); a later write to either path
copies only the blocks it changes, so the two files stay independent. Nothing is deleted.

Rules:
  - regular files only, never a symlink; directories named node_modules, .git, .next are skipped;
  - at least --min-mb MB (small files are not worth the hashing);
  - not modified for --min-age-min minutes, so a render or a download still being written is left alone;
  - two files are the same only when their size AND sha256 match; the clone is written next to the
    target as <name>.clonetmp, its sha256 checked again, then moved over the target in one rename
    (os.replace). The target's mode and times are kept (cp -p). On any error the target is untouched.
  - a group already sharing blocks gives back nothing; df before/after is the honest measure,
    the "MB" count printed here is the logical size of the replaced copies.

Output: one "clone <target> <- <source>" line per replacement, then
"groups=G cloned=C failed=F logical_mb=M". Exit 0, or 1 when a replacement failed.
"""
import argparse
import collections
import hashlib
import os
import subprocess
import sys
import time

SKIP_DIRS = {"node_modules", ".git", ".next"}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def candidates(roots, min_bytes, cutoff):
    by_size = collections.defaultdict(list)
    for root in roots:
        if not os.path.isdir(root) or os.path.islink(root):
            continue
        for base, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(base, d))]
            for name in files:
                if name.endswith(".clonetmp"):
                    continue
                path = os.path.join(base, name)
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                if not os.path.isfile(path) or os.path.islink(path) or st.st_size < min_bytes or st.st_mtime > cutoff:
                    continue
                by_size[st.st_size].append(path)
    return by_size


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", action="append", required=True)
    parser.add_argument("--min-mb", type=float, default=1)
    parser.add_argument("--min-age-min", type=float, default=60)
    parser.add_argument("--now", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    now = args.now if args.now is not None else time.time()
    by_size = candidates(args.root, int(args.min_mb * 1024 * 1024), now - args.min_age_min * 60)

    groups = cloned = failed = logical = 0
    for size, paths in sorted(by_size.items()):
        if len(paths) < 2:
            continue
        by_hash = collections.defaultdict(list)
        for path in sorted(paths):
            try:
                by_hash[sha256(path)].append(path)
            except OSError:
                continue
        for digest, same in by_hash.items():
            if len(same) < 2:
                continue
            groups += 1
            source = same[0]
            for target in same[1:]:
                print(f"clone {target} <- {source}")
                if args.dry_run:
                    cloned += 1
                    logical += size
                    continue
                tmp = target + ".clonetmp"
                try:
                    subprocess.run(["cp", "-c", "-p", source, tmp], check=True, capture_output=True)
                    if sha256(tmp) != digest:
                        raise OSError("sha256 mismatch after clone")
                    os.replace(tmp, target)
                    cloned += 1
                    logical += size
                except (OSError, subprocess.CalledProcessError) as error:
                    print(f"failed {target}: {error}")
                    failed = 1
                    if os.path.lexists(tmp):
                        os.remove(tmp)
    print(f"groups={groups} cloned={cloned} failed={failed} logical_mb={logical >> 20}")
    return failed


if __name__ == "__main__":
    sys.exit(main())
