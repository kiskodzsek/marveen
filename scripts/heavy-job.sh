#!/usr/bin/env bash
# heavy-job.sh -- run ONE heavy job at a time, only with free memory, under a watchdog.
#
#   heavy-job.sh [--name N] [--min-free PCT] [--kill-below PCT] [--min-disk-gb GB]
#                [--wait SEC] -- <command> [args...]
#
# Why: the Mac mini (16 GB) panicked at 07:02:20 on 2026-10-20 ("no checkins
# from watchdogd in 93 seconds"). In the panic stackshot free memory was 871
# pages and the compressor held ~12 GiB, while an mflux image job (9.7 GB MLX
# peak), a 6 GB Colima VM, ollama and 14 claude sessions shared the machine.
# Nothing stopped two heavy jobs from overlapping, and the fleet memory gate
# was fail-open on macOS. This wrapper is the shared rule for mflux, whisper,
# render/video and `colima start`:
#
#   1. a single machine-wide lock (store/.heavy-job.lock): one heavy job at a time;
#   2. start only when free memory >= --min-free (default 40%), the data
#      volume has >= --min-disk-gb (default 3) free, and a fresh
#      store/.host-state (host-monitor.sh) is not warn/critical; otherwise wait up to --wait
#      seconds (default 600), then give up with exit 75;
#   3. while the job runs, a 3 s watchdog stops the WHOLE process group (TERM,
#      then KILL after 10 s) if free memory drops below --kill-below (default
#      25%) or the disk below --min-disk-gb. Exit 70 then, so the caller can
#      tell "the watchdog stopped it" from the job's own failure.
#
# Unreadable memory = do not start (exit 75). This is deliberately the
# opposite of fleet-memory-gate.sh, which fails open so a broken gate never
# freezes the fleet: a heavy job is optional work, and starting it blind is
# exactly what caused the panic.
#
# Exit codes: the job's own exit code; 75 = not started (lock busy, low memory
# or disk, unreadable memory, until --wait ran out); 70 = stopped by the
# watchdog; 64 = usage error.
#
# Every start/stop/refusal is one line in store/heavy-job.log.
# Test hooks: MEMGATE_PROC_MEMINFO / MEMGATE_SYSCTL (lib/mem-read.sh),
# HEAVY_JOB_STORE (state dir), HEAVY_JOB_DF_KB (fixed free-disk KB),
# HEAVY_JOB_POLL (seconds between checks, default 3).

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STORE="${HEAVY_JOB_STORE:-$HERE/../store}"
LOCK="$STORE/.heavy-job.lock"
LOG="$STORE/heavy-job.log"
POLL="${HEAVY_JOB_POLL:-3}"

NAME="job"; MIN_FREE=40; KILL_BELOW=25; MIN_DISK_GB=3; WAIT=600
usage() { echo "usage: heavy-job.sh [--name N] [--min-free PCT] [--kill-below PCT] [--min-disk-gb GB] [--wait SEC] -- cmd [args...]" >&2; exit 64; }
num() { [[ "${1:-}" =~ ^[0-9]+$ ]] || usage; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)        [[ $# -ge 2 ]] || usage; NAME="$2"; shift 2 ;;
    --min-free)    [[ $# -ge 2 ]] || usage; num "$2"; MIN_FREE="$2"; shift 2 ;;
    --kill-below)  [[ $# -ge 2 ]] || usage; num "$2"; KILL_BELOW="$2"; shift 2 ;;
    --min-disk-gb) [[ $# -ge 2 ]] || usage; num "$2"; MIN_DISK_GB="$2"; shift 2 ;;
    --wait)        [[ $# -ge 2 ]] || usage; num "$2"; WAIT="$2"; shift 2 ;;
    --) shift; break ;;
    *) usage ;;
  esac
done
[[ $# -ge 1 ]] || usage
(( KILL_BELOW < MIN_FREE )) || { echo "heavy-job: --kill-below must be lower than --min-free" >&2; exit 64; }
NAME="$(printf '%s' "$NAME" | tr -c 'A-Za-z0-9._-' '_' | cut -c1-40)"

mkdir -p "$STORE" 2>/dev/null
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [$NAME pid=$$] $*" >>"$LOG" 2>/dev/null; echo "heavy-job: $*" >&2; }

. "$HERE/lib/mem-read.sh" || { echo "heavy-job: cannot load lib/mem-read.sh" >&2; exit 75; }

disk_free_kb() {
  if [[ -n "${HEAVY_JOB_DF_KB:-}" ]]; then echo "$HEAVY_JOB_DF_KB"; return; fi
  df -Pk "$STORE" 2>/dev/null | awk 'NR==2{print $4}'
}
MIN_DISK_KB=$(( MIN_DISK_GB * 1024 * 1024 ))

# host-monitor.sh's verdict (store/.host-state): a FRESH warn/critical blocks
# the start (it also covers swap, load and heat, which this script does not
# measure). A missing or stale file is ignored: no monitor installed, or it
# stopped running -- then the memory and disk checks above still apply.
host_state() {
  local b e r now; now="$(date +%s)"
  read -r b e r < "$STORE/.host-state" 2>/dev/null || return 0
  [[ "$e" =~ ^[0-9]+$ ]] || return 0
  (( now - e <= ${HEAVY_JOB_STATE_MAX_AGE:-300} )) || return 0
  [[ "$b" == "warn" || "$b" == "critical" ]] && echo "$b (${r:-no reason})"
  return 0
}

# --- lock: mkdir is atomic on every filesystem we run on; flock is not on macOS ---
have_lock=0
release() { (( have_lock )) && rm -rf "$LOCK" 2>/dev/null; have_lock=0; }
try_lock() {
  if mkdir "$LOCK" 2>/dev/null; then
    echo "$$ $NAME $(date +%s)" >"$LOCK/owner"; have_lock=1; return 0
  fi
  # Stale lock: the owner pid is gone (crash, kill -9, reboot).
  local opid; opid="$(cut -d' ' -f1 "$LOCK/owner" 2>/dev/null)"
  if [[ "$opid" =~ ^[0-9]+$ ]] && ! kill -0 "$opid" 2>/dev/null; then
    log "stale lock from pid $opid removed"
    rm -rf "$LOCK" 2>/dev/null
    mkdir "$LOCK" 2>/dev/null && { echo "$$ $NAME $(date +%s)" >"$LOCK/owner"; have_lock=1; return 0; }
  fi
  return 1
}

child=0
on_signal() {
  if (( child > 0 )); then kill -TERM -- "-$child" 2>/dev/null; fi
  log "interrupted, job stopped"; release; exit 130
}
trap on_signal INT TERM
trap release EXIT

# --- wait for lock + memory + disk ---
deadline=$(( $(date +%s) + WAIT )); reason=""
while :; do
  if ! mem_read; then
    reason="memory unreadable"
  elif (( MEM_FREE_PCT < MIN_FREE )); then
    reason="free memory ${MEM_FREE_PCT}% < ${MIN_FREE}%"
  elif d="$(disk_free_kb)"; [[ ! "$d" =~ ^[0-9]+$ ]] || (( d < MIN_DISK_KB )); then
    reason="free disk ${d:-?} KB < ${MIN_DISK_GB} GB"
  elif hs="$(host_state)"; [[ -n "$hs" ]]; then
    reason="host-monitor says $hs"
  elif try_lock; then
    break
  else
    reason="lock held by: $(cat "$LOCK/owner" 2>/dev/null || echo '?')"
  fi
  if (( $(date +%s) >= deadline )); then
    log "NOT STARTED after ${WAIT}s: $reason"; exit 75
  fi
  sleep "$POLL"
done

log "START free=${MEM_FREE_PCT}% src=${MEM_SOURCE}: $*"
# Job control gives the background job its own process group, so the watchdog
# can stop the job AND everything it spawned (panna.sh -> mflux -> python).
set -m
"$@" &
child=$!
set +m

stopped=""
while kill -0 "$child" 2>/dev/null; do
  sleep "$POLL"
  kill -0 "$child" 2>/dev/null || break
  if ! mem_read; then
    stopped="memory unreadable while running"
  elif (( MEM_FREE_PCT < KILL_BELOW )); then
    stopped="free memory ${MEM_FREE_PCT}% < ${KILL_BELOW}%"
  elif d="$(disk_free_kb)"; [[ "$d" =~ ^[0-9]+$ ]] && (( d < MIN_DISK_KB )); then
    stopped="free disk ${d} KB < ${MIN_DISK_GB} GB"
  fi
  if [[ -n "$stopped" ]]; then
    kill -TERM -- "-$child" 2>/dev/null
    for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$child" 2>/dev/null || break; sleep 1; done
    kill -KILL -- "-$child" 2>/dev/null
    wait "$child" 2>/dev/null
    log "WATCHDOG STOP: $stopped"
    exit 70
  fi
done
wait "$child"; rc=$?
log "END rc=$rc"
exit "$rc"
