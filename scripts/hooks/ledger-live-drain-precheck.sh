#!/usr/bin/env bash
# Scheduler preCheck for the ledger-live-drain task (runPreCheck contract:
# stdout "SKIP" = no model turn this tick; empty stdout = run the task).
#
# The drain task used to cost a full model turn every 2 minutes only to run a
# script that prints nothing on almost every tick. This asks the drain the same
# question in --precheck mode, which never records anything: the scheduler's
# busy/skipIfBusy gate runs AFTER the preCheck, so a question marked surfaced
# here and then dropped by that gate would be deduplicated away for good.
#
# cwd is pinned to the install root so the drain attributes the open question to
# the main agent, exactly as it does inside the live session.
cd "$(dirname "$0")/../.." || exit 1
# PRECHECKTRUST1114 (Viktor 42472 RES1/RES2): -I keeps PYTHONPATH, the user site
# and sitecustomize out (the drain puts its own dir on sys.path for ledger_lib);
# the pycache prefix under /dev/null means no cached bytecode replaces the source.
exec python3 -I -X pycache_prefix=/dev/null/x scripts/hooks/ledger-live-drain.py --precheck
