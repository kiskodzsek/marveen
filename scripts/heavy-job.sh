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

# Seconds since pid $1 started (ps etime is [[dd-]hh:]mm:ss on macOS and Linux).
proc_age() {
  local e d=0 h=0 m=0 s=0
  e="$(ps -o etime= -p "$1" 2>/dev/null | tr -d ' ')"
  [[ "$e" == *-* ]] && { d="${e%%-*}"; e="${e#*-}"; }
  IFS=: read -r -a p <<< "$e"
  case "${#p[@]}" in
    2) m="${p[0]}"; s="${p[1]}" ;;
    3) h="${p[0]}"; m="${p[1]}"; s="${p[2]}" ;;
    *) return 1 ;;
  esac
  echo $(( 10#$d * 86400 + 10#$h * 3600 + 10#$m * 60 + 10#$s ))
}

# The owner line is "pid name epoch". Stale = the pid is gone (crash, kill -9,
# reboot), or the pid is alive but started after the lock was taken, so the
# number was reused by an unrelated process.
owner_is_stale() {
  local opid _n oepoch age
  read -r opid _n oepoch <<< "$1"
  [[ "$opid" =~ ^[0-9]+$ && "$oepoch" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$opid" 2>/dev/null || return 0
  age="$(proc_age "$opid")" || return 1
  (( $(date +%s) - age > oepoch + 2 ))
}

mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null; }

try_lock() {
  if mkdir "$LOCK" 2>/dev/null; then
    echo "$$ $NAME $(date +%s)" >"$LOCK/owner"; have_lock=1; return 0
  fi
  local seen t; seen="$(cat "$LOCK/owner" 2>/dev/null)"
  if [[ -z "$seen" ]]; then
    # No owner line: either it is being written right now, or the owner died
    # between mkdir and the write. Only the second leaves it there for 60 s.
    t="$(mtime "$LOCK")"
    [[ "$t" =~ ^[0-9]+$ ]] && (( $(date +%s) - t > 60 )) || return 1
  else
    owner_is_stale "$seen" || return 1
  fi
  # Takeover goes through its own mkdir mutex, and the owner is re-read inside
  # it: two waiters that both saw the same stale owner cannot both win, and the
  # loser cannot delete the winner's fresh lock (Viktor 9013 L1). Holding the
  # mutex takes milliseconds, so one older than 60 s is left by a killed
  # process and is cleared.
  local tk="$LOCK.takeover"
  if ! mkdir "$tk" 2>/dev/null; then
    t="$(mtime "$tk")"
    [[ "$t" =~ ^[0-9]+$ ]] && (( $(date +%s) - t > 60 )) && rmdir "$tk" 2>/dev/null
    return 1
  fi
  if [[ "$(cat "$LOCK/owner" 2>/dev/null)" == "$seen" ]]; then
    log "stale lock (owner: ${seen:-none}) removed"
    rm -rf "$LOCK" 2>/dev/null
  fi
  if mkdir "$LOCK" 2>/dev/null; then
    echo "$$ $NAME $(date +%s)" >"$LOCK/owner"; have_lock=1
  fi
  rmdir "$tk" 2>/dev/null
  (( have_lock ))
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

# Only the command's basename goes to the log: the full argv can carry a
# customer file path or a prompt, and a newline in it would forge a log line
# (Viktor 9013 I1).
cmd="$(printf '%s' "${1##*/}" | tr -c 'A-Za-z0-9._+-' '_' | cut -c1-60)"
log "START free=${MEM_FREE_PCT}% src=${MEM_SOURCE}: $cmd"
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
