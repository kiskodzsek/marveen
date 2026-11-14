#!/usr/bin/env bash
# preCheck wrapper for Kernel's disk heartbeat (runPreCheck runs `bash <this file>`). The logic and its
# fail-open contract live in kernel_heartbeat_precheck.py next to it; a failure to even start it must also
# run the round, so the exit status is forced to 0 and nothing is printed on that path.
# -I: no PYTHONPATH / user site; -X pycache_prefix: no .pyc from __pycache__ runs in place of a source
# (Viktor 42472 RES 1: an unchecked-hash .pyc beside an unchanged source ran instead of it).
python3 -I -X pycache_prefix=/dev/null/x "$(dirname "$0")/kernel_heartbeat_precheck.py" disk 2>/dev/null || true
exit 0
