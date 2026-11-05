"""Helpers for scripts/konyveles-hydrate.sh (card 7b30ebe5). Run with python3 -I.

  classify <root> <dataless-list> <known-local-list>
      prints "<evicted> <folders>": how many dataless files were local in an earlier
      run, and their top-level folder names under <root>, sanitized (Viktor 27163
      LOW-1: a folder name is text a OneDrive co-editor controls, and it goes into an
      agent's prompt): allowed letters only, 40 characters, 5 names, then "+N".
  hydrate
      reads a NUL-separated path list on stdin, turns dataless materialization on for
      this process (setiopolicy_np) and reads every byte, so the File Provider
      downloads the file. Prints the read errors counted by errno ("EDEADLK:2"), never
      a file name (INFO-2).
"""
import collections
import ctypes
import errno
import re
import sys

ALLOWED = re.compile(r"[^A-Za-z0-9ÁÉÍÓÖŐÚÜŰáéíóöőúüű _.-]")


def lines(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return [line for line in fh.read().splitlines() if line]


def classify(root, dataless, known):
    local_before = set(lines(known))
    evicted = [p for p in lines(dataless) if p in local_before]
    tops = set()
    for p in evicted:
        rel = p[len(root) + 1:] if p.startswith(root + "/") else p
        tops.add(rel.split("/", 1)[0] if "/" in rel else "gyoker")
    clean = sorted({(ALLOWED.sub("", t)[:40] or "?").replace(" ", "_") for t in tops})
    out = ",".join(clean[:5]) + (",+%d" % (len(clean) - 5) if len(clean) > 5 else "")
    print(len(evicted), out or "-")


def hydrate():
    libc = ctypes.CDLL(None, use_errno=True)
    # IOPOL_TYPE_VFS_MATERIALIZE_DATALESS_FILES=3, IOPOL_SCOPE_PROCESS=0, IOPOL_MATERIALIZE_DATALESS_FILES_ON=2
    if libc.setiopolicy_np(3, 0, 2) != 0:
        print("setiopolicy_np:%s" % errno.errorcode.get(ctypes.get_errno(), ctypes.get_errno()))
        return
    bad = collections.Counter()
    for p in sys.stdin.buffer.read().split(b"\0"):
        if not p:
            continue
        try:
            with open(p, "rb") as fh:
                while fh.read(8 << 20):
                    pass
        except OSError as e:
            bad[errno.errorcode.get(e.errno, str(e.errno))] += 1
    print(",".join("%s:%d" % kv for kv in sorted(bad.items())))


if __name__ == "__main__":
    if sys.argv[1:2] == ["classify"] and len(sys.argv) == 5:
        classify(*sys.argv[2:5])
    elif sys.argv[1:2] == ["hydrate"]:
        hydrate()
    else:
        sys.exit("usage: konyveles-hydrate.py classify <root> <dataless> <known> | hydrate")
