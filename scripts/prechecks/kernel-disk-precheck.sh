#!/usr/bin/env bash
# preCheck wrapper for Kernel's disk heartbeat (runPreCheck runs `bash <this file>`). The logic and its
# fail-open contract live in kernel_heartbeat_precheck.py next to it; a failure to even start it must also
# run the round, so the exit status is forced to 0 and nothing is printed on that path.
python3 -I "$(dirname "$0")/kernel_heartbeat_precheck.py" disk 2>/dev/null || true
exit 0
