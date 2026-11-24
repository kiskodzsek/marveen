#!/usr/bin/env bash
# preCheck of the patrik-csend-or schedule (Klodel 52701/52712, card 0d64942c). runPreCheck runs `bash <this file>`;
# exactly "SKIP" on stdout = no model turn. check.py sends the nudge to klodel itself (--send): rc 0 (nothing to
# say) and rc 10 (nudge sent) print SKIP; rc 2 (ERROR), rc 1 (an uncaught Python exception) or any other
# code prints the error and no SKIP, so the round runs and Kernel reports it: fail-open, never a silent green. -X pycache_prefix: no stale .pyc runs.
out=$(python3 -I -X pycache_prefix=/dev/null/x /Users/klodel/marveen/agents/kernel/tools/patrik-csend-or/check.py --send 2>&1)
rc=$?
case $rc in
  0|10) echo SKIP ;;
  *) printf '%s\n' "$out" | head -5 ;;
esac
exit 0
