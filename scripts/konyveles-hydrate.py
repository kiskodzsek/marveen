"""Helpers for scripts/konyveles-hydrate.sh (card 7b30ebe5). Run with python3 -I.

  classify <root> <dataless-list> <known-local-list>
      prints "<evicted> <folders>": how many dataless files were local in an earlier
      run, and all their top-level folder names under <root>, sanitized (Viktor 27163
      LOW-1: a folder name is text a OneDrive co-editor controls, and it goes into an
      agent's prompt): allowed letters only, 40 characters each.
  fmt
      sanitized names on stdin -> at most 5 unique names, then "+N".
  hydrate
      reads a NUL-separated path list on stdin, turns dataless materialization on for
      this process (setiopolicy_np) and reads every byte, so the File Provider
      downloads the file; a read that takes longer than READ_TIMEOUT_S counts as
      TIMEOUT (Viktor 27189 INFO-3). Prints the read errors counted by errno
      ("EDEADLK:2"), never a file name (INFO-2).
"""
import collections
import ctypes
import errno
import re
import signal
import sys

READ_TIMEOUT_S = 120  # per file; the whole folder is about 48 MB

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
    print(len(evicted), ",".join(clean) or "-")


def fmt():
    """Sanitized names on stdin (comma or newline separated) -> at most 5 unique names, then "+N"."""
    names = sorted({n for n in re.split(r"[,\n]", sys.stdin.read()) if n and n != "-"})
    out = ",".join(names[:5]) + (",+%d" % (len(names) - 5) if len(names) > 5 else "")
    print(out or "-")


def hydrate():
    libc = ctypes.CDLL(None, use_errno=True)
    # IOPOL_TYPE_VFS_MATERIALIZE_DATALESS_FILES=3, IOPOL_SCOPE_PROCESS=0, IOPOL_MATERIALIZE_DATALESS_FILES_ON=2
    if libc.setiopolicy_np(3, 0, 2) != 0:
        print("setiopolicy_np:%s" % errno.errorcode.get(ctypes.get_errno(), ctypes.get_errno()))
        return
    bad = collections.Counter()

    def on_alarm(signum, frame):
        raise TimeoutError

    signal.signal(signal.SIGALRM, on_alarm)
    for p in sys.stdin.buffer.read().split(b"\0"):
        if not p:
            continue
        signal.alarm(READ_TIMEOUT_S)  # Viktor 27189 INFO-3: one stuck File Provider read must not hold the run
        try:
            with open(p, "rb") as fh:
                while fh.read(8 << 20):
                    pass
        except TimeoutError:
            bad["TIMEOUT"] += 1
        except OSError as e:
            bad[errno.errorcode.get(e.errno, str(e.errno))] += 1
        finally:
            signal.alarm(0)
    print(",".join("%s:%d" % kv for kv in sorted(bad.items())))


if __name__ == "__main__":
    if sys.argv[1:2] == ["classify"] and len(sys.argv) == 5:
        classify(*sys.argv[2:5])
    elif sys.argv[1:2] == ["fmt"]:
        fmt()
    elif sys.argv[1:2] == ["hydrate"]:
        hydrate()
    else:
        sys.exit("usage: konyveles-hydrate.py classify <root> <dataless> <known> | fmt | hydrate")
