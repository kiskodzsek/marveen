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
# Every tick, after a run if one was due: free disk under
# DAILY_CLEANUP_ALERT_GB (default 20 GiB, Klodel 21709) sends one inter-agent
# message to DAILY_CLEANUP_ALERT_TO (default: pulzus and the main agent), at
# most once per DAILY_CLEANUP_ALERT_COOLDOWN seconds (default 6 h). The
# host-monitor pages only at CRITICAL (3 GiB): this is the earlier warning,
# while there is still room to decide what goes.
# The run goes through heavy-job.sh: one heavy job at a time, and only with
# free memory. --ignore-host-disk and --min-disk-gb 0, because a low disk puts
# host-monitor into warn or critical (and below 3 GiB heavy-job's own disk
# check refuses), and those would block the one job that frees disk.
# --ignore-host-swap, because the warn-level swap reason can stand for hours
# on macOS while free memory is fine, and on 2026-10-20 it held the cleanup
# back at 8 GiB free disk (Pulzus 12317); the memory floor below still
# applies. A memory, critical swap, load or thermal reason in the host state
# still blocks it. The memory
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
#            file changed for DAILY_CLEANUP_SCRATCH_DAYS (default 2) days
#            (7 until 2026-10-30; Klodel 21709: trial shots past 2 days go).
#            Only Claude Code project dirs (the name starts with "-"); other
#            dirs there (bash-edit-diff, Claude Code's own) are left alone.
#            Symlinks are not followed; nothing outside that tree is touched.
#   release-runs  ops/release/runs/<run>: src/ when the run's last ledger entry
#            is DAILY_CLEANUP_RELEASE_DAYS (default 3) days old, src.tar.gz
#            only when the run is that old AND closed (deployed, covered or
#            merge-stopped); every *.json stays. The release engine unpacks
#            src/ from the tarball each time and reads a tarball only for the
#            run it is executing (Pulzus 14571). Rules and reasons:
#            scripts/release-runs-prune.py.
#   worktrees  merged, clean, idle (DAILY_CLEANUP_WORKTREE_DAYS, default 3)
#            worktrees of the agents' clones, by `git worktree remove`, and
#            the build caches (.next, .turbo, ...) of trees idle for
#            DAILY_CLEANUP_CACHE_HOURS (default 24); never a busy tree (a
#            process has its cwd in it), one another tree's node_modules
#            links into, or one under a path in store/daily-cleanup.keep.
#            Rules and reasons: scripts/worktree-prune.py (card c310dd1b).
#   transcripts  the agents' Claude Code session transcripts (*.jsonl under
#            agents/*/.claude-config/projects and ~/.claude/projects) older
#            than DAILY_CLEANUP_TRANSCRIPT_DAYS (default 7) days, gzipped in
#            place when no process has them open; such a session can no longer
#            be resumed, gunzip brings it back (Klodel 21739). A *.jsonl.gz
#            older than DAILY_CLEANUP_TRANSCRIPT_EXPIRE_DAYS (default 30, as
#            Claude Code's own cleanupPeriodDays) is deleted (Lex 21777).
#            Rules and reasons: scripts/transcript-gzip.py.
# Not here, on purpose: unmerged worktrees, node_modules, models (whisper,
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
# DAILY_CLEANUP_HEAVY_JOB (the wrapper), DAILY_CLEANUP_RELEASE_DIR, MARVEEN_STORE,
# DAILY_CLEANUP_INSTALL_DIR, DAILY_CLEANUP_LSOF, DAILY_CLEANUP_AGENT_MSG.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STORE="${MARVEEN_STORE:-$HERE/../store}"
STAMP="$STORE/.daily-cleanup.last"
LOG="$STORE/daily-cleanup.log"
LOW_GB="${DAILY_CLEANUP_LOW_GB:-10}"
SCRATCH_DAYS="${DAILY_CLEANUP_SCRATCH_DAYS:-2}"
SCRATCH_ROOT="${DAILY_CLEANUP_SCRATCH_ROOT:-/private/tmp/claude-$(id -u)}"
HEAVY_JOB="${DAILY_CLEANUP_HEAVY_JOB:-$HERE/heavy-job.sh}"
RELEASE_DIR="${DAILY_CLEANUP_RELEASE_DIR:-$HERE/../ops/release}"
RELEASE_DAYS="${DAILY_CLEANUP_RELEASE_DAYS:-3}"
INSTALL_DIR="${DAILY_CLEANUP_INSTALL_DIR:-$HERE/..}"
WORKTREE_DAYS="${DAILY_CLEANUP_WORKTREE_DAYS:-3}"
CACHE_HOURS="${DAILY_CLEANUP_CACHE_HOURS:-24}"
TRANSCRIPT_DAYS="${DAILY_CLEANUP_TRANSCRIPT_DAYS:-7}"
TRANSCRIPT_EXPIRE_DAYS="${DAILY_CLEANUP_TRANSCRIPT_EXPIRE_DAYS:-30}"
LSOF="${DAILY_CLEANUP_LSOF:-/usr/sbin/lsof}"
ALERT_GB="${DAILY_CLEANUP_ALERT_GB:-20}"
ALERT_COOLDOWN="${DAILY_CLEANUP_ALERT_COOLDOWN:-21600}"
ALERT_STAMP="$STORE/.daily-cleanup.alert"
AGENT_MSG="${DAILY_CLEANUP_AGENT_MSG:-$HERE/agent-msg.sh}"

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
  local rc=0
  if [[ -n "$reason" ]]; then
    log "TICK due ($reason)"
    bash "$HEAVY_JOB" --name daily-cleanup --ignore-host-disk --ignore-host-swap --min-disk-gb 0 --allow-vm \
      --min-free 20 --kill-below 10 --wait 1800 -- bash "$HERE/daily-cleanup.sh" run
    rc=$?
    # 0 and 1 both mean the run happened; anything else (75 not started, 70
    # stopped by the watchdog) leaves the stamp, so the next tick retries.
    if (( rc == 0 || rc == 1 )); then now >"$STAMP"; fi
  fi
  alert_low_disk
  return "$rc"
}

# The early warning (Klodel 21709): after the cleanup has done what it safely
# can, a disk still under ALERT_GB needs a person to decide what else goes.
alert_low_disk() {
  local kb gb last to sent=0 recipients main
  kb="$(free_kb)"
  (( kb < ALERT_GB * 1024 * 1024 )) || return 0
  last="$(cat "$ALERT_STAMP" 2>/dev/null)"; [[ "$last" =~ ^[0-9]+$ ]] || last=0
  (( $(now) - last >= ALERT_COOLDOWN )) || return 0
  gb=$(( kb / 1048576 ))
  # The main agent's id, as host-monitor.sh reads it: only that one line of .env.
  main=""
  [[ -f "$INSTALL_DIR/.env" ]] && main="$(grep -E '^MAIN_AGENT_ID=' "$INSTALL_DIR/.env" | head -1 | cut -d= -f2- | tr -d '"'"'"'\r')"
  recipients="${DAILY_CLEANUP_ALERT_TO:-pulzus $main}"
  local ran ran_at="még nem futott"
  ran="$(cat "$STAMP" 2>/dev/null)"
  [[ "$ran" =~ ^[0-9]+$ ]] && ran_at="$(date -r "$ran" '+%m-%d %H:%M' 2>/dev/null || echo "$ran")"
  local msg="[DAILY-CLEANUP] A lemezen ${gb} GiB szabad, a ${ALERT_GB} GiB-os jelzési szint alatt. Az automatikus takarítás utolsó futása: ${ran_at} (store/daily-cleanup.log). Ami még nagy, azt csak a gazdája döntheti el: be nem olvasztott worktree, out/, modellek, transcriptek."
  for to in $recipients; do
    if echo "$msg" | bash "$AGENT_MSG" daily-cleanup "$to" - >/dev/null 2>&1; then sent=1; else log "ALERT to $to FAILED"; fi
  done
  # Only a delivered alert starts the cooldown: a failed one is tried again next tick.
  (( sent )) && now >"$ALERT_STAMP"
  log "ALERT low disk ${gb} GiB < ${ALERT_GB} sent=$sent to=${recipients}"
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

# The release engine's run directories: the age and closed-ness come from the
# ledger, so the decision is in Python (scripts/release-runs-prune.py).
clean_release_runs() {
  local before after out rc
  if [[ ! -d "$RELEASE_DIR/runs" || -L "$RELEASE_DIR/runs" ]]; then log "STEP release-runs skipped: no $RELEASE_DIR/runs"; return; fi
  if ! command -v python3 >/dev/null 2>&1; then log "STEP release-runs skipped: python3 not installed"; return; fi
  before="$(free_kb)"
  echo "== release-runs: src/ and closed tarballs of runs idle for ${RELEASE_DAYS} days under $RELEASE_DIR/runs"
  out="$(python3 -I "$HERE/release-runs-prune.py" --release-dir "$RELEASE_DIR" --days "$RELEASE_DAYS" --now "$(now)")"; rc=$?
  echo "$out"
  (( rc == 0 )) || FAILED=1
  after="$(free_kb)"
  log "STEP release-runs rc=$rc $(echo "$out" | tail -1) disk_delta_mb=$(( (after - before) / 1024 ))"
}

# Merged, idle worktrees and idle build caches: the checks (merged, clean,
# not busy, not linked) are in Python (scripts/worktree-prune.py).
clean_worktrees() {
  local before after out rc keep="$STORE/daily-cleanup.keep"
  if ! command -v git >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then log "STEP worktrees skipped: git or python3 not installed"; return; fi
  # Run from a worktree copy of the scripts, git would still list the live trees.
  if [[ ! -d "$INSTALL_DIR/.git" || -L "$INSTALL_DIR/.git" ]]; then log "STEP worktrees skipped: $INSTALL_DIR is not a clone's main tree"; return; fi
  before="$(free_kb)"
  echo "== worktrees: merged and idle for ${WORKTREE_DAYS} days, build caches idle for ${CACHE_HOURS} h, under $INSTALL_DIR/agents"
  out="$(python3 -I "$HERE/worktree-prune.py" --install-dir "$INSTALL_DIR" --days "$WORKTREE_DAYS" --cache-hours "$CACHE_HOURS" \
    --keep-file "$keep" --lsof "$LSOF" --now "$(now)")"; rc=$?
  echo "$out"
  (( rc == 0 )) || FAILED=1
  after="$(free_kb)"
  log "STEP worktrees rc=$rc $(echo "$out" | tail -1) disk_delta_mb=$(( (after - before) / 1024 ))"
}

# Old session transcripts, gzipped in place; expired .gz deleted (scripts/transcript-gzip.py).
clean_transcripts() {
  local before after out rc
  if ! command -v gzip >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then log "STEP transcripts skipped: gzip or python3 not installed"; return; fi
  before="$(free_kb)"
  echo "== transcripts: *.jsonl idle for ${TRANSCRIPT_DAYS} days gzipped in place, *.jsonl.gz older than ${TRANSCRIPT_EXPIRE_DAYS} days deleted"
  out="$(python3 -I "$HERE/transcript-gzip.py" --install-dir "$INSTALL_DIR" --home "$HOME" --days "$TRANSCRIPT_DAYS" \
    --expire-days "$TRANSCRIPT_EXPIRE_DAYS" --lsof "$LSOF" --now "$(now)")"; rc=$?
  echo "$out"
  (( rc == 0 )) || FAILED=1
  after="$(free_kb)"
  log "STEP transcripts rc=$rc $(echo "$out" | tail -1) disk_delta_mb=$(( (after - before) / 1024 ))"
}

run() {
  exec >"$STORE/daily-cleanup.last-run.txt" 2>&1
  log "RUN start free_gb=$(( $(free_kb) / 1048576 ))"
  step brew brew env HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ANALYTICS=1 brew cleanup -s --prune=all
  step npm npm npm cache clean --force
  step pip pip3 pip3 cache purge
  step go go go clean -cache
  clean_scratch
  clean_release_runs
  clean_worktrees
  clean_transcripts
  log "RUN end free_gb=$(( $(free_kb) / 1048576 )) failed=$FAILED"
  return "$FAILED"
}

case "${1:-}" in
  tick) tick ;;
  run) run ;;
  *) echo "usage: daily-cleanup.sh tick|run" >&2; exit 64 ;;
esac
