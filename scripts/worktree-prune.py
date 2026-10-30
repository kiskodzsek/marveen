#!/usr/bin/env python3
"""worktree-prune.py -- remove merged, idle git worktrees and the build caches of idle trees.

    worktree-prune.py --install-dir DIR [--days N] [--cache-hours H] [--keep-file F]
                      [--lsof PATH] [--now EPOCH] [--dry-run]

Why (card c310dd1b, Klodel 21708/21709, Patrik TG 11766 "miert nem cleanupoltok
automatikusan"): on 2026-10-30 the data volume went down to 1.9 GiB free. The
daily cleanup ran twice that afternoon and freed 0 MB: the big items were the
agents' worktrees and their .next caches, which it left alone on purpose. The
by-hand cleanup removed 9 merged, clean worktrees (1.4 GB) and 4 idle .next
caches (1.3 GB) with exactly the rules below
(agents/kernel/out/disk-cleanup-2026-10-30.md).

Which trees: the install dir's own clone and every clone directly under
<install>/agents/*/repos/ (a directory whose .git is a directory), and every
worktree `git worktree list` gives for them.

A worktree is removed (`git worktree remove`, never --force) only when ALL hold:
  - it is a linked worktree, not a clone's main tree, not the install dir, and
    it lies under <install>/agents/;
  - it is not locked, and not listed in the keep file (one absolute path a line,
    # comments; a listed path keeps everything under it);
  - nothing has its current directory in it (lsof); when lsof cannot be run,
    every tree counts as busy, and nothing is removed;
  - no other tree's node_modules symlink points into it (worktree-add.sh links
    node_modules to a main clone: removing that clone breaks the others; on
    2026-10-30 four of Dave's worktrees linked to wt-gifts-cta);
  - `git status --porcelain` is empty (no change, no untracked file);
  - it holds no ignored file but the regenerable ones (`git status --ignored`:
    anything under node_modules, __pycache__, the build caches, .DS_Store,
    *.tsbuildinfo, next-env.d.ts; dist/, supabase/.temp and the like count as
    precious). `git worktree remove` deletes ignored files too, and a
    .env.local from `vercel env pull`, a local out/ or render would go
    silently (Viktor 21749 M1): such a tree is kept and listed;
  - no source file changed for --days days (default 3; .git, node_modules and
    the build caches are not counted);
  - its HEAD is merged: an ancestor of the clone's main ref (origin/main,
    origin/master, gh/main or upstream/main, whichever exist), or every commit
    on it has a patch-equivalent one there (`git cherry`: a squash-merged
    single commit). A squash of several commits is not recognised: such a tree
    is kept and listed. Nothing is fetched; a stale main ref only keeps more.
Then `git worktree prune` on the clone. The branch itself stays.

A build cache (.next, .turbo, test-results, playwright-report at the tree's
root or under apps/* and packages/*; node_modules/.cache when node_modules is
a real directory) is removed when the tree lies under <install>/agents/, is
not busy, and no source file changed for --cache-hours hours (default 24). A
symlinked cache is never followed or removed, nor one reached through a
symlinked apps/<x> (Viktor 21749 L1): the cache's resolved path must lie
inside the tree.

--install-dir must be a clone's main tree (its .git a directory): run from a
worktree copy of the scripts (a test, a review checkout), the "install" would
be that copy, and `git worktree list` would still list the live trees. Then
nothing is done (exit 2).

Output: one "remove <path>" line per removal, one "keep <path> <reason>" line
per worktree left (merged ones that are dirty, linked or recent, and the
unmerged), then one summary line "worktrees_removed=N caches_removed=M
kept=K busy=B". With --dry-run nothing is removed. Exit 0, 1 when a removal
failed (the rest still ran), 2 on bad arguments.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

MAIN_REFS = ("refs/remotes/origin/main", "refs/remotes/origin/master", "refs/remotes/gh/main", "refs/remotes/upstream/main")
CACHE_NAMES = (".next", ".turbo", "test-results", "playwright-report")
NOT_SOURCE = {".git", "node_modules"} | set(CACHE_NAMES)
# Ignored files `git worktree remove` may take with it: regenerable only.
REGENERABLE_DIRS = {"node_modules", "__pycache__"} | set(CACHE_NAMES)
REGENERABLE_FILES = {".DS_Store", "next-env.d.ts"}


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)


def real(path):
    return os.path.realpath(path)


def under(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def clones(install):
    found = [install]
    agents = os.path.join(install, "agents")
    for agent in sorted(os.listdir(agents)) if os.path.isdir(agents) else []:
        repos = os.path.join(agents, agent, "repos")
        if not os.path.isdir(repos) or os.path.islink(repos):
            continue
        for name in sorted(os.listdir(repos)):
            path = os.path.join(repos, name)
            if not os.path.islink(path) and os.path.isdir(os.path.join(path, ".git")) and not os.path.islink(os.path.join(path, ".git")):
                found.append(path)
    return found


def worktrees(clone):
    """[(path, locked)] from `git worktree list --porcelain`; the first is the main tree."""
    out = git(clone, "worktree", "list", "--porcelain")
    if out.returncode != 0:
        return []
    trees, current = [], None
    for line in out.stdout.splitlines():
        if line.startswith("worktree "):
            current = [line[len("worktree "):], False]
            trees.append(current)
        elif line.startswith("locked") and current is not None:
            current[1] = True
    return [(path, locked) for path, locked in trees]


def busy_dirs(lsof):
    """The current directories of every process, or None when lsof cannot be run."""
    try:
        out = subprocess.run([lsof, "-a", "-d", "cwd", "-Fn", "-n", "-P"], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    # lsof exits 1 when some process could not be read; the lines it gave are still good.
    if out.returncode not in (0, 1) or not out.stdout:
        return None
    return {real(line[1:]) for line in out.stdout.splitlines() if line.startswith("n/")}


def newest_source_mtime(tree, newer_than):
    """True when a source file under tree changed after newer_than (stops at the first)."""
    for root, dirs, files in os.walk(tree, followlinks=False):
        dirs[:] = [d for d in dirs if d not in NOT_SOURCE and not os.path.islink(os.path.join(root, d))]
        for name in files + dirs:
            try:
                if os.lstat(os.path.join(root, name)).st_mtime > newer_than:
                    return True
            except OSError:
                continue
    return False


def merged(clone, tree):
    refs = [ref for ref in MAIN_REFS if git(clone, "rev-parse", "--verify", "--quiet", ref).returncode == 0]
    head = git(tree, "rev-parse", "HEAD").stdout.strip()
    if not head or not refs:
        return False
    for ref in refs:
        if git(clone, "merge-base", "--is-ancestor", head, ref).returncode == 0:
            return True
        cherry = git(clone, "cherry", ref, head)
        lines = [line for line in cherry.stdout.splitlines() if line.strip()]
        if cherry.returncode == 0 and lines and all(line.startswith("-") for line in lines):
            return True
    return False


def precious_ignored(tree):
    """The ignored paths in tree that are not regenerable (empty list: none), or None when git cannot say."""
    out = git(tree, "status", "--porcelain", "--ignored")
    if out.returncode != 0:
        return None
    found = []
    for line in out.stdout.splitlines():
        if not line.startswith("!! "):
            continue
        path = line[3:].strip().strip('"').rstrip("/")
        parts = path.split("/")
        if any(part in REGENERABLE_DIRS for part in parts) or parts[-1] in REGENERABLE_FILES or parts[-1].endswith(".tsbuildinfo"):
            continue
        found.append(path)
    return found


def caches(tree):
    found = []
    for base in [tree] + [os.path.join(tree, group, name) for group in ("apps", "packages") if os.path.isdir(os.path.join(tree, group))
                          for name in sorted(os.listdir(os.path.join(tree, group)))]:
        # A symlinked apps/<x> (or apps/ itself) leads out of the tree (Viktor 21749 L1).
        if os.path.islink(base) or not under(real(base), tree):
            continue
        for name in CACHE_NAMES:
            path = os.path.join(base, name)
            if os.path.isdir(path) and not os.path.islink(path):
                found.append(path)
        nm = os.path.join(base, "node_modules")
        if os.path.isdir(nm) and not os.path.islink(nm) and os.path.isdir(os.path.join(nm, ".cache")) and not os.path.islink(os.path.join(nm, ".cache")):
            found.append(os.path.join(nm, ".cache"))
    return found


def read_keep(path):
    keep = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.split("#", 1)[0].strip()
                if line.startswith("/"):
                    keep.append(real(line))
    except OSError:
        pass
    return keep


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-dir", required=True)
    parser.add_argument("--days", type=float, default=3)
    parser.add_argument("--cache-hours", type=float, default=24)
    parser.add_argument("--keep-file", default="")
    parser.add_argument("--lsof", default="/usr/sbin/lsof")
    parser.add_argument("--now", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.days < 1 or args.cache_hours < 1:
        print("stop: --days and --cache-hours must be at least 1")
        return 2

    install = real(args.install_dir)
    if not os.path.isdir(os.path.join(install, ".git")) or os.path.islink(os.path.join(install, ".git")):
        print(f"stop: --install-dir {install} is not a clone's main tree")
        return 2
    agents_root = os.path.join(install, "agents")
    now = args.now if args.now is not None else time.time()
    keep = read_keep(args.keep_file) if args.keep_file else []
    busy = busy_dirs(args.lsof)
    if busy is None:
        print(f"lsof unavailable ({args.lsof}): every tree counts as busy")

    def is_busy(tree):
        return busy is None or any(under(cwd, tree) for cwd in busy)

    def kept(tree):
        return any(under(tree, path) for path in keep)

    # Every tree, and what the node_modules symlinks point into.
    all_trees = []
    for clone in clones(install):
        for index, (path, locked) in enumerate(worktrees(clone)):
            if os.path.isdir(path):
                all_trees.append((clone, real(path), index == 0, locked))
    link_targets = set()
    for _, tree, _, _ in all_trees:
        nm = os.path.join(tree, "node_modules")
        if os.path.islink(nm):
            link_targets.add(real(nm))

    removed = cached = failed = kept_n = busy_n = 0
    pruned = set()
    for clone, tree, is_main, locked in all_trees:
        if tree == install:
            continue
        tree_busy = is_busy(tree)
        busy_n += tree_busy
        if not is_main and under(tree, agents_root):
            reason = None
            if locked:
                reason = "locked"
            elif kept(tree):
                reason = "keep-file"
            elif tree_busy:
                reason = "busy"
            elif any(under(target, tree) for target in link_targets):
                reason = "linked (node_modules of another tree)"
            elif git(tree, "status", "--porcelain").stdout.strip():
                reason = "dirty"
            elif (ignored := precious_ignored(tree)) is None or ignored:
                reason = "ignored files: " + (", ".join(ignored[:3]) + (" ..." if len(ignored) > 3 else "") if ignored else "git status failed")
            elif newest_source_mtime(tree, now - args.days * 86400):
                reason = f"changed within {args.days:g} days"
            elif not merged(clone, tree):
                reason = "not merged"
            if reason is None:
                print(f"remove {tree}")
                if not args.dry_run:
                    if git(clone, "worktree", "remove", tree).returncode == 0:
                        removed += 1
                        pruned.add(clone)
                        continue
                    print(f"failed {tree}: git worktree remove")
                    failed = 1
                else:
                    removed += 1
                    continue
            else:
                print(f"keep {tree} {reason}")
                kept_n += 1
        if not under(tree, agents_root) or tree_busy or kept(tree) or newest_source_mtime(tree, now - args.cache_hours * 3600):
            continue
        for cache in caches(tree):
            print(f"remove {cache}")
            if args.dry_run:
                cached += 1
                continue
            try:
                shutil.rmtree(cache)
                cached += 1
            except OSError as error:
                print(f"failed {cache}: {error}")
                failed = 1
    for clone in sorted(pruned):
        git(clone, "worktree", "prune")
    print(f"worktrees_removed={removed} caches_removed={cached} kept={kept_n} busy={busy_n}")
    return failed


if __name__ == "__main__":
    sys.exit(main())
