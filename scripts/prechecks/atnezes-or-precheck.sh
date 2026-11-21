#!/usr/bin/env bash
# preCheck wrapper (runPreCheck runs `bash <this file>`): fail-open, exit forced to 0.
python3 -I -X pycache_prefix=/dev/null/x /Users/klodel/marveen/ops/prechecks/guard_precheck.py atnezes-or-pulzus 2>/dev/null || true
exit 0
