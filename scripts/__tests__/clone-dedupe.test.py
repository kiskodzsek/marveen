#!/usr/bin/env python3
"""CLONEDEDUPE1103: clone-dedupe.py keeps the target's own mode and times, skips a target written
between the scan and the rename, and never touches database, journal or lock files (Viktor 25425,
card 152400f3).

Pinned cases:
  1. a 0600 target cloned from a 0644 source stays 0600, keeps its own mtime (not the source's),
     and keeps every byte; no .clonetmp is left
  2. a target whose size or mtime changed after the scan is skipped, its new content kept, and the
     run reports skipped=1, failed=0
  3. identical *.db, *-wal, *-shm, *.lock, *.sqlite3 copies are not candidates
"""
import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("clone_dedupe", os.path.join(HERE, "..", "clone-dedupe.py"))
cd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cd)

OLD = 1577836800  # 2020-01-01
OLDER = 1262304000  # 2010-01-01
BLOB = os.urandom(2 * 1024 * 1024)


def write(path, data=BLOB, mode=0o644, mtime=OLD):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    os.chmod(path, mode)
    os.utime(path, (mtime, mtime))


def run(*argv):
    out = io.StringIO()
    old = sys.argv
    sys.argv = ["clone-dedupe.py", *argv]
    try:
        with contextlib.redirect_stdout(out):
            rc = cd.main()
    finally:
        sys.argv = old
    return rc, out.getvalue()


class CloneDedupe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    @unittest.skipUnless(sys.platform == "darwin", "the clone is APFS clonefile(2) via cp -c: macOS only "
                         "(CI runs on Linux, where GNU cp has no -c)")
    def test_target_keeps_its_own_mode_and_times(self):
        src, dst = os.path.join(self.root, "a", "p.png"), os.path.join(self.root, "b", "p.png")
        write(src, mode=0o644, mtime=OLDER)
        write(dst, mode=0o600, mtime=OLD)
        rc, out = run("--root", self.root)
        self.assertEqual(rc, 0, out)
        self.assertIn("cloned=1 failed=0 skipped=0", out)
        st = os.stat(dst)
        self.assertEqual(st.st_mode & 0o7777, 0o600, "the 0600 target must not widen to the source's 0644")
        self.assertEqual(int(st.st_mtime), OLD, "the target keeps its own mtime, not the source's")
        with open(dst, "rb") as handle:
            self.assertEqual(handle.read(), BLOB)
        self.assertEqual(os.stat(src).st_mode & 0o7777, 0o644)
        self.assertEqual([n for n in os.listdir(os.path.dirname(dst)) if n.endswith(".clonetmp")], [])

    @unittest.skipUnless(sys.platform == "darwin", "the clone is APFS clonefile(2) via cp -c: macOS only "
                         "(CI runs on Linux, where GNU cp has no -c)")
    def test_target_written_after_the_scan_is_skipped(self):
        src, dst = os.path.join(self.root, "a", "p.png"), os.path.join(self.root, "b", "p.png")
        write(src)
        write(dst)
        new = b"N" * len(BLOB)
        real = cd.subprocess.run

        def cp_then_write(cmd, **kwargs):
            result = real(cmd, **kwargs)
            write(dst, data=new, mtime=OLD + 60)  # a writer lands between the clone and the rename
            return result

        cd.subprocess.run = cp_then_write
        try:
            rc, out = run("--root", self.root)
        finally:
            cd.subprocess.run = real
        self.assertEqual(rc, 0, out)
        self.assertIn(f"skip {dst}: changed since the scan", out)
        self.assertIn("cloned=0 failed=0 skipped=1", out)
        with open(dst, "rb") as handle:
            self.assertEqual(handle.read(), new, "the new content must survive")
        self.assertFalse(os.path.lexists(dst + ".clonetmp"))

    def test_database_journal_and_lock_files_are_not_candidates(self):
        for name in ("x.db", "x.db-wal", "x.db-shm", "x.lock", "x.sqlite3", "x.db-journal"):
            write(os.path.join(self.root, "a", name))
            write(os.path.join(self.root, "b", name))
        rc, out = run("--root", self.root)
        self.assertEqual(rc, 0, out)
        self.assertIn("groups=0 cloned=0", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
