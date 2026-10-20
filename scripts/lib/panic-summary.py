#!/usr/bin/env python3
"""One line about a macOS panic report, for host-restart-watchdog.sh.

Usage: panic-summary.py <panic-full-*.panic>
Prints "kernel panic HH:MM: <first line of the panic>" in local time, or
nothing (exit 0) when the file cannot be read or parsed. The report is two
JSON documents: a one-line header, then the body with panicString and
panicTimeInSecsAndUsecs ("wall <epoch> s <usec> us"). Only the panic time and
the panic's first line are taken, cut to 160 printable characters.
"""
import json
import re
import sys
import time

MAX_READ = 8 * 1024 * 1024


def summary(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read(MAX_READ)
    parts = raw.split("\n", 1)
    if len(parts) < 2:
        return ""
    doc, _ = json.JSONDecoder().raw_decode(parts[1].lstrip())
    if not isinstance(doc, dict):
        return ""
    lines = str(doc.get("panicString") or "").splitlines()
    first = re.sub(r"^panic\([^)]*\):\s*", "", lines[0]) if lines else ""
    first = "".join(c for c in first if c.isprintable())[:160]
    m = re.search(r"wall\s+(\d+)\s*s", str(doc.get("panicTimeInSecsAndUsecs", "")))
    when = time.strftime("%H:%M", time.localtime(int(m.group(1)))) if m else "?"
    return "kernel panic %s: %s" % (when, first or "?")


if __name__ == "__main__":
    try:
        out = summary(sys.argv[1])
    except Exception:  # unreadable or not a panic report: no line, never a failure
        out = ""
    if out:
        print(out)
