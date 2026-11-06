#!/usr/bin/env python3
"""WTPRUNESQUASH1106: worktree-prune.py removes a clean, idle worktree whose branch was squash-merged
from SEVERAL commits, also when main edited the same file afterwards, and still keeps every tree
with work that main does not have (card 20aaec54, Klodel 29408).

Measured 2026-11-06: of 15 merged, clean Kernel worktrees the daily prune kept 7 as "not merged",
because a squash of several commits has no patch-equivalent commit (`git cherry` gives +N).

Pinned cases (one temporary install: a bare origin, a clone under agents/kernel/repos, linked
worktrees beside it, every file dated 2020 so the idle rule passes):
  1. multi   - two commits, squash-merged as one main commit, then main edits the same file again:
               removed
  2. extra   - the same two commits plus one whose change main never got: kept, "not merged"
  3. own     - one commit main never got: kept, "not merged"
  4. single  - one commit, cherry-picked to main (the old `git cherry` path): removed
  5. odd-in  - like multi, plus a non-ASCII file name that the squash also brought: removed
  6. uml / quote / magic - like multi, plus ONE file main never got whose name `git diff --name-only`
               quotes (non-ASCII, a double quote) or git reads as pathspec magic (":(top)x.md"):
               kept, "not merged" (Viktor 29421: the quoted name matched nothing and the tree went)
  7. detached - multi's two commits on a detached HEAD: kept, "not merged" (no branch holds the
               commits; `git worktree remove` would leave them to the reflog and gc)
  8. an OSError from git (E2BIG: a branch with ~30 000 paths, Viktor 29421) answers "not merged"
     instead of a traceback that would stop every later daily run at the same tree
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "worktree-prune.py")
OLD = 1577836800  # 2020-01-01

ENV = dict(os.environ)
ENV.update({
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
})


def git(cwd, *args):
    out = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env=ENV)
    if out.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} in {cwd}: {out.stderr}")
    return out.stdout.strip()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def commit(tree, message, **files):
    for name, text in files.items():
        write(os.path.join(tree, name), text)
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", message)


def age(tree):
    for root, dirs, files in os.walk(tree):
        for name in files + dirs:
            os.utime(os.path.join(root, name), (OLD, OLD), follow_symlinks=False)
    os.utime(tree, (OLD, OLD))


class SquashMerged(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = os.path.realpath(self.tmp.name)
        origin = os.path.join(root, "origin.git")
        self.install = os.path.join(root, "install")
        repos = os.path.join(self.install, "agents", "kernel", "repos")
        self.clone = os.path.join(repos, "app")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True, env=ENV)
        subprocess.run(["git", "init", "-q", "-b", "main", self.install], check=True, env=ENV)
        commit(self.install, "install", **{"README": "install\n"})
        subprocess.run(["git", "clone", "-q", origin, self.clone], check=True, env=ENV, capture_output=True)
        git(self.clone, "checkout", "-q", "-b", "main")
        commit(self.clone, "base", **{"a.txt": "a0\n", "b.txt": "b0\n", "c.txt": "c0\n"})
        git(self.clone, "push", "-q", "origin", "main")

        self.trees = {}
        for name in ("multi", "extra", "own", "single", "odd-in", "uml", "quote", "magic"):
            path = os.path.join(repos, f"wt-{name}")
            git(self.clone, "worktree", "add", "-q", "-b", name, path, "main")
            self.trees[name] = path
        path = os.path.join(repos, "wt-detached")
        git(self.clone, "worktree", "add", "-q", "--detach", path, "main")
        self.trees["detached"] = path
        for name in ("multi", "extra", "odd-in", "uml", "quote", "magic", "detached"):
            commit(self.trees[name], "a", **{"a.txt": "a1\n"})
            commit(self.trees[name], "b", **{"b.txt": "b1\n"})
        commit(self.trees["extra"], "c not on main", **{"c.txt": "c-extra\n"})
        commit(self.trees["odd-in"], "odd name, on main too", **{"ünï-in.md": "u1\n"})
        commit(self.trees["uml"], "odd name, not on main", **{"ünï.md": "u-own\n"})
        commit(self.trees["quote"], "quote in name, not on main", **{'q"uote.md': "q-own\n"})
        commit(self.trees["magic"], "pathspec magic name, not on main", **{":(top)x.md": "m-own\n"})
        commit(self.trees["own"], "own", **{"c.txt": "c-own\n"})
        commit(self.trees["single"], "single", **{"d.txt": "d1\n"})

        # main: the squash of multi's two commits, the cherry-pick of single, then a later edit of a.txt.
        commit(self.clone, "squash of multi and odd-in (#1)", **{"a.txt": "a1\n", "b.txt": "b1\n", "ünï-in.md": "u1\n"})
        git(self.clone, "cherry-pick", "single")
        commit(self.clone, "later main edit", **{"a.txt": "a2\n"})
        git(self.clone, "push", "-q", "origin", "main")
        git(self.clone, "fetch", "-q", "origin")

        for path in self.trees.values():
            age(path)
        self.lsof = os.path.join(root, "lsof")
        write(self.lsof, "#!/bin/sh\nprintf 'p1\\nn/nonexistent-cwd\\n'\n")
        os.chmod(self.lsof, 0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def run_prune(self, *extra):
        out = subprocess.run([sys.executable, "-I", SCRIPT, "--install-dir", self.install, "--lsof", self.lsof, *extra],
                             capture_output=True, text=True, env=ENV)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        return out.stdout

    def test_dry_run_verdicts(self):
        out = self.run_prune("--dry-run")
        self.assertIn(f"remove {self.trees['multi']}\n", out)
        self.assertIn(f"remove {self.trees['single']}\n", out)
        self.assertIn(f"remove {self.trees['odd-in']}\n", out)
        for name in ("extra", "own", "uml", "quote", "magic", "detached"):
            self.assertIn(f"keep {self.trees[name]} not merged\n", out)
        for path in self.trees.values():
            self.assertTrue(os.path.isdir(path), path)

    def test_removes_only_the_merged_trees(self):
        out = self.run_prune()
        self.assertIn("worktrees_removed=3", out)
        for name in ("multi", "single", "odd-in"):
            self.assertFalse(os.path.exists(self.trees[name]), name)
        for name in ("extra", "own", "uml", "quote", "magic", "detached"):
            self.assertTrue(os.path.isdir(self.trees[name]), name)
        # The branches stay: nothing but the working directory goes.
        self.assertTrue(git(self.clone, "rev-parse", "--verify", "-q", "multi"))


class SquashProbeFailsSafe(unittest.TestCase):
    def test_oserror_keeps_the_tree(self):
        spec = importlib.util.spec_from_file_location("worktree_prune", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        def too_long(cwd, *args, literal=False):
            raise OSError(7, "Argument list too long")

        module.git = too_long
        self.assertFalse(module.squash_merged("/nonexistent", "refs/remotes/origin/main", "0" * 40))


if __name__ == "__main__":
    unittest.main()
