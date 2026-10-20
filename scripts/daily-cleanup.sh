#!/usr/bin/env bash
# daily-cleanup.sh -- clear the regenerable caches once a day, and earlier when the disk runs low.
#
#   daily-cleanup.sh tick    # launchd calls this every hour; it decides whether a run is due
#   daily-cleanup.sh run     # the cleanup itself (tick starts it under heavy-job.sh)
#
# Why (card 1c58f629): the Mac mini panicked at 07:02 on 2026-10-20. That
# morning the data volume was down to 5.6 GiB free, and the by-hand cleanup of
# the same caches gave back 6.0 GiB (agents/kernel/reports/lemez-2026-10-20.md).
# By 12:00 the npm cache alone had grown back to 0.5 GB. Nothing cleared them
# on a schedule.
#
# When a run is due (tick):
#   - the nightly run: the last run is >= 20 h old and the local hour is 03-05;
#   - catch-up: the last run is >= 30 h old (the Mac was off or busy at night);
#   - the disk gate: free disk < DAILY_CLEANUP_LOW_GB (default 10 GiB, the
#     host-monitor WARN line) and the last run is >= 1 h old.
# The run goes through heavy-job.sh: one heavy job at a time, and only with
# free memory. --ignore-host-disk and --min-disk-gb 0, because a low disk puts
# host-monitor into warn or critical (and below 3 GiB heavy-job's own disk
# check refuses), and those would block the one job that frees disk. A memory,
# swap, load or thermal reason in the host state still blocks it. The memory
# floor is 20% to start / 10% to stop, below heavy-job's 40/25: the cleanup
# itself needs little memory, which is also why a running Colima VM does not
# hold it back (--allow-vm): a VM left up for days must not stop the disk
# cleanup. A "not started" (75)
# writes no stamp, so the next tick tries again.
#
# What a run clears -- only caches the tools rebuild by themselves:
#   brew   brew cleanup -s --prune=all          (the Homebrew download cache AND
#                                                the kegs of outdated formula
#                                                versions; a venv that points at
#                                                /opt/homebrew/opt/<f> keeps
#                                                working, one at a Cellar/<f>/<v>
#                                                path would not)
#   npm    npm cache clean --force              (~/.npm/_cacache only; _npx stays,
#                                                the MCP servers run from it)
#   pip    pip3 cache purge
#   go     go clean -cache
#   scratch  /private/tmp/claude-<uid>/<project>/<session> directories with no
#            file changed for DAILY_CLEANUP_SCRATCH_DAYS (default 7) days.
#            Only Claude Code project dirs (the name starts with "-"); other
#            dirs there (bash-edit-diff, Claude Code's own) are left alone.
#            Symlinks are not followed; nothing outside that tree is touched.
# Not here, on purpose: worktrees and their node_modules, models (whisper,
# Hugging Face, mflux), the Colima disk, ms-playwright. Those belong to an
# agent or are in use; the morning report lists them for their owners.
#
# Output: one line per step in store/daily-cleanup.log (rc and the change in
# free disk). The tools' own output of the last run is in
# store/daily-cleanup.last-run.txt, overwritten each run.
#
# Exit codes (run): 0 = every step ok or skipped, 1 = a step failed (the
# others still ran). tick: 0 = not due or the run finished, otherwise the
# heavy-job.sh code (75 = not started).
#
# Test hooks: DAILY_CLEANUP_NOW (epoch), DAILY_CLEANUP_HOUR (00-23),
# DAILY_CLEANUP_DF_KB (free disk KB), DAILY_CLEANUP_SCRATCH_ROOT,
# DAILY_CLEANUP_HEAVY_JOB (the wrapper), MARVEEN_STORE.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STORE="${MARVEEN_STORE:-$HERE/../store}"
STAMP="$STORE/.daily-cleanup.last"
LOG="$STORE/daily-cleanup.log"
LOW_GB="${DAILY_CLEANUP_LOW_GB:-10}"
SCRATCH_DAYS="${DAILY_CLEANUP_SCRATCH_DAYS:-7}"
SCRATCH_ROOT="${DAILY_CLEANUP_SCRATCH_ROOT:-/private/tmp/claude-$(id -u)}"
HEAVY_JOB="${DAILY_CLEANUP_HEAVY_JOB:-$HERE/heavy-job.sh}"

mkdir -p "$STORE" 2>/dev/null
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >>"$LOG" 2>/dev/null; }
now() { echo "${DAILY_CLEANUP_NOW:-$(date +%s)}"; }
# Free disk in KB; 0 when unreadable, so the arithmetic below never breaks
# (an unreadable disk then looks low, and the disk gate errs towards a run).
free_kb() {
  local v="${DAILY_CLEANUP_DF_KB:-}"
  [[ -n "$v" ]] || v="$(df -Pk "$STORE" 2>/dev/null | awk 'NR==2{print $4}')"
  [[ "$v" =~ ^[0-9]+$ ]] && echo "$v" || echo 0
}

tick() {
  local last age hour kb reason=""
  last="$(cat "$STAMP" 2>/dev/null)"; [[ "$last" =~ ^[0-9]+$ ]] || last=0
  age=$(( $(now) - last ))
  hour="${DAILY_CLEANUP_HOUR:-$(date +%H)}"; hour=$(( 10#$hour ))
  kb="$(free_kb)"
  if (( age >= 20 * 3600 && hour >= 3 && hour < 6 )); then
    reason="nightly"
  elif (( age >= 30 * 3600 )); then
    reason="catch-up"
  elif (( kb < LOW_GB * 1024 * 1024 && age >= 3600 )); then
    reason="disk gate: $(( kb / 1048576 )) GiB free"
  fi
  [[ -n "$reason" ]] || return 0
  log "TICK due ($reason)"
  bash "$HEAVY_JOB" --name daily-cleanup --ignore-host-disk --min-disk-gb 0 --allow-vm \
    --min-free 20 --kill-below 10 --wait 1800 -- bash "$HERE/daily-cleanup.sh" run
  local rc=$?
  # 0 and 1 both mean the run happened; anything else (75 not started, 70
  # stopped by the watchdog) leaves the stamp, so the next tick retries.
  if (( rc == 0 || rc == 1 )); then now >"$STAMP"; fi
  return "$rc"
}

FAILED=0
step() {
  local name="$1" tool="$2"; shift 2
  if ! command -v "$tool" >/dev/null 2>&1; then log "STEP $name skipped: $tool not installed"; return; fi
  local before after rc
  before="$(free_kb)"
  echo "== $name: $*"
  "$@"; rc=$?
  after="$(free_kb)"
  (( rc == 0 )) || FAILED=1
  log "STEP $name rc=$rc disk_delta_mb=$(( (after - before) / 1024 ))"
}

# The scratch tree: <root>/<project>/<session>. A session directory goes only
# when nothing under it changed for SCRATCH_DAYS days. find does not follow
# symlinks, and a symlinked session or project is never listed as a directory.
clean_scratch() {
  local before after d n=0
  if [[ ! -d "$SCRATCH_ROOT" || -L "$SCRATCH_ROOT" ]]; then log "STEP scratch skipped: no $SCRATCH_ROOT"; return; fi
  before="$(free_kb)"
  echo "== scratch: session dirs under $SCRATCH_ROOT idle for ${SCRATCH_DAYS} days"
  while IFS= read -r d; do
    case "$d" in "$SCRATCH_ROOT"/-*/*) ;; *) continue ;; esac
    case "$d" in */../*|*/..|*/./*) continue ;; esac
    [[ -d "$d" && ! -L "$d" ]] || continue
    [[ -z "$(find "$d" -xdev -mtime "-$SCRATCH_DAYS" -print 2>/dev/null | head -1)" ]] || continue
    echo "remove $d"
    rm -rf -- "$d" && n=$(( n + 1 ))
  done < <(find "$SCRATCH_ROOT" -xdev -mindepth 2 -maxdepth 2 -type d 2>/dev/null)
  after="$(free_kb)"
  log "STEP scratch removed=$n disk_delta_mb=$(( (after - before) / 1024 ))"
}

run() {
  exec >"$STORE/daily-cleanup.last-run.txt" 2>&1
  log "RUN start free_gb=$(( $(free_kb) / 1048576 ))"
  step brew brew env HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ANALYTICS=1 brew cleanup -s --prune=all
  step npm npm npm cache clean --force
  step pip pip3 pip3 cache purge
  step go go go clean -cache
  clean_scratch
  log "RUN end free_gb=$(( $(free_kb) / 1048576 )) failed=$FAILED"
  return "$FAILED"
}

case "${1:-}" in
  tick) tick ;;
  run) run ;;
  *) echo "usage: daily-cleanup.sh tick|run" >&2; exit 64 ;;
esac
