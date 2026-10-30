#!/usr/bin/env bash
# DAILYCLEANUP1020 -- daily-cleanup.sh (when a run is due, what a run clears),
# heavy-job.sh --ignore-host-disk, and the macOS launchd installer (card 1c58f629).
#
# Every tool a run calls (brew, npm, pip3, go) is a stub that only records its
# argv; HOME, the store, the scratch root and the release dir are inside a
# sandbox. Nothing here touches a real cache, the real store or ops/release.
#
# Run:  bash scripts/__tests__/daily-cleanup.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
DC="$ROOT/scripts/daily-cleanup.sh"
HJ="$ROOT/scripts/heavy-job.sh"
for f in "$DC" "$HJ" "$ROOT/scripts/install-daily-cleanup.sh"; do
  [ -e "$f" ] || { echo "FATAL: the script under test is missing: $f" >&2; exit 2; }
done

FAILS=0; DONE=0
check() { DONE=$((DONE+1)); if [ "$2" = "0" ]; then echo "PASS  $1"; else echo "FAIL  $1${3:+  -- $3}"; FAILS=$((FAILS+1)); fi; }
ok() { [ "$@" ] && echo 0 || echo 1; }

SB="$(mktemp -d "${TMPDIR:-/tmp}/dailycleanup.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
mkdir -p "$SB/store" "$SB/bin" "$SB/home" "$SB/scratch"
for t in brew npm pip3 go; do
  printf '#!/bin/bash\necho "%s $*" >> "%s/calls"\nexit "${STUB_RC_%s:-0}"\n' "$t" "$SB" "$t" > "$SB/bin/$t"
  chmod +x "$SB/bin/$t"
done
# lsof stand-in: the current directories in $SB/cwds, as lsof -Fn prints them.
# With -t -- <file> (the per-file look right before a gzip): rc 0 and a pid when the file is listed in cwds or
# in late (opened after the run's first look), else rc 1.
printf '#!/bin/bash\nif [ "$1" = "-t" ]; then cat "%s/cwds" "%s/late" 2>/dev/null | grep -qxF -- "$3" && { echo 1; exit 0; }; exit 1; fi\necho p1\nwhile IFS= read -r d; do echo "n$d"; done < "%s/cwds"\n' "$SB" "$SB" "$SB" > "$SB/lsof"; chmod +x "$SB/lsof"
: > "$SB/cwds"
# agent-msg.sh stand-in: records "<from> <to> <stdin>" a line; exit $STUB_RC_msg.
printf '#!/bin/bash\necho "$1 $2 $(cat)" >> "%s/msgs"\nexit "${STUB_RC_msg:-0}"\n' "$SB" > "$SB/agent-msg-stub"; chmod +x "$SB/agent-msg-stub"
# The wrapper stand-in: records its argv, then runs the command after --.
cat > "$SB/hj-stub" <<STUB
#!/usr/bin/env bash
echo "\$*" > "$SB/hj.args"
while [ "\$1" != "--" ]; do shift; done; shift
"\$@"
STUB
chmod +x "$SB/hj-stub"
# sysctl stand-in for the real heavy-job.sh: 16 GiB, 70% free.
printf '#!/bin/bash\ncase "$2" in hw.memsize) echo 17179869184 ;; kern.memorystatus_level) echo 70 ;; *) exit 1 ;; esac\n' > "$SB/sysctl"
chmod +x "$SB/sysctl"

NOW=2000000000; H=3600; GB=1048576
# dc <tick|run> with: HOUR, DF_KB (default 50 GiB), LAST (stamp, empty = none), HJ_BIN (default the stub).
# No VM (HEAVY_JOB_VM_PID empty): env -i would drop the export below, and the host may run a real one.
dc() {
  rm -f "$SB/calls" "$SB/hj.args"
  if [ -n "${LAST:-}" ]; then echo "$LAST" > "$SB/store/.daily-cleanup.last"; else rm -f "$SB/store/.daily-cleanup.last"; fi
  OUT="$(env -i PATH="$SB/bin:/usr/bin:/bin" HOME="$SB/home" MARVEEN_STORE="$SB/store" \
      DAILY_CLEANUP_NOW="$NOW" DAILY_CLEANUP_HOUR="${HOUR:-12}" DAILY_CLEANUP_DF_KB="${DF_KB:-$((50 * GB))}" \
      DAILY_CLEANUP_SCRATCH_ROOT="$SB/scratch" DAILY_CLEANUP_HEAVY_JOB="${HJ_BIN:-$SB/hj-stub}" \
      DAILY_CLEANUP_RELEASE_DIR="${REL_DIR:-$SB/no-release}" \
      DAILY_CLEANUP_INSTALL_DIR="${INST:-$SB/no-install}" DAILY_CLEANUP_LSOF="${LSOF_BIN:-$SB/lsof}" \
      DAILY_CLEANUP_AGENT_MSG="$SB/agent-msg-stub" DAILY_CLEANUP_ALERT_TO="${ALERT_TO:-pulzus klodel}" \
      HEAVY_JOB_STORE="$SB/store" HEAVY_JOB_POLL=1 HEAVY_JOB_DF_KB="${HJ_DF:-99999999}" HEAVY_JOB_VM_PID= \
      MEMGATE_PROC_MEMINFO="$SB/no-such" MEMGATE_SYSCTL="$SB/sysctl" \
      ${STUB_ENV:-} bash "$DC" "$@" 2>&1)"; RC=$?
}
ran() { [ -f "$SB/calls" ] && echo 0 || echo 1; }
stamp() { cat "$SB/store/.daily-cleanup.last" 2>/dev/null; }

echo "== when a run is due (tick)"
HOUR=4 LAST= dc tick
check "no stamp, 04 h -> nightly run" "$(ran)" "rc=$RC $OUT"
check "...and the stamp is the run's time" "$(ok "$(stamp)" = "$NOW")" "stamp=$(stamp)"
HOUR=4 LAST=$((NOW - 2 * H)) dc tick
check "last run 2 h ago, 04 h -> nothing" "$(ok "$(ran)" = 1 -a "$RC" = 0)" "rc=$RC"
HOUR=4 LAST=$((NOW - 21 * H)) dc tick
check "last run 21 h ago, 04 h -> nightly run" "$(ran)" "rc=$RC"
HOUR=12 LAST=$((NOW - 21 * H)) dc tick
check "last run 21 h ago, 12 h -> nothing (waits for the night)" "$(ok "$(ran)" = 1)" "rc=$RC"
HOUR=6 LAST=$((NOW - 21 * H)) dc tick
check "the window ends at 06 h" "$(ok "$(ran)" = 1)" "rc=$RC"
HOUR=12 LAST=$((NOW - 31 * H)) dc tick
check "last run 31 h ago, 12 h -> catch-up run" "$(ran)" "rc=$RC"
HOUR=12 LAST=$((NOW - 2 * H)) DF_KB=$((9 * GB)) dc tick
check "9 GiB free, last run 2 h ago -> disk-gate run" "$(ran)" "rc=$RC"
check "...logged with the reason" "$(ok -n "$(grep 'TICK due (disk gate: 9 GiB free)' "$SB/store/daily-cleanup.log")")" "$(tail -3 "$SB/store/daily-cleanup.log")"
HOUR=12 LAST=$((NOW - 1800)) DF_KB=$((9 * GB)) dc tick
check "9 GiB free, last run 30 min ago -> nothing (at most hourly)" "$(ok "$(ran)" = 1)" "rc=$RC"
HOUR=12 LAST=$((NOW - 2 * H)) DF_KB=$((11 * GB)) dc tick
check "11 GiB free, last run 2 h ago -> nothing" "$(ok "$(ran)" = 1)" "rc=$RC"
HOUR=4 LAST= dc tick
check "the run goes through heavy-job, past a disk/swap-warn host state, the disk floor and a running VM" "$(grep -q -- '--name daily-cleanup --ignore-host-disk --ignore-host-swap --min-disk-gb 0 --allow-vm ' "$SB/hj.args" && echo 0 || echo 1)" "$(cat "$SB/hj.args" 2>/dev/null)"

printf '#!/bin/bash\nexit 75\n' > "$SB/hj-75"; chmod +x "$SB/hj-75"
HOUR=4 LAST=$((NOW - 40 * H)) HJ_BIN="$SB/hj-75" dc tick
check "heavy-job did not start it (75) -> rc 75 and the old stamp stays" "$(ok "$RC" = 75 -a "$(stamp)" = $((NOW - 40 * H)))" "rc=$RC stamp=$(stamp)"

echo "== the real heavy-job.sh: a disk-only host state does not block the cleanup, anything else does"
export HEAVY_JOB_VM_PID=""  # no VM: the host running this test may have a real one
hjrun() { OUT="$(env HEAVY_JOB_STORE="$SB/store" HEAVY_JOB_POLL=1 HEAVY_JOB_DF_KB=99999999 MEMGATE_PROC_MEMINFO="$SB/no-such" MEMGATE_SYSCTL="$SB/sysctl" \
    bash "$HJ" --wait 0 "$@" 2>&1)"; RC=$?; }
echo "critical $(date +%s) free disk 2 GiB" > "$SB/store/.host-state"
HOUR=12 LAST=$((NOW - 2 * H)) DF_KB=$((2 * GB)) HJ_DF=$((2 * GB)) HJ_BIN="$HJ" dc tick
check "2 GiB free, host-monitor critical on the disk only -> the cleanup still runs" "$(ok "$RC" = 0 -a "$(ran)" = 0)" "rc=$RC $OUT"
echo "warn $(date +%s) free disk 8 GiB" > "$SB/store/.host-state"
rm -f "$SB/hj-a"; hjrun --ignore-host-disk -- touch "$SB/hj-a"
check "--ignore-host-disk: warn on the disk only -> runs" "$(ok "$RC" = 0 -a -e "$SB/hj-a")" "rc=$RC $OUT"
rm -f "$SB/hj-b"; hjrun -- touch "$SB/hj-b"
check "without the flag the same disk warn still blocks (75)" "$(ok "$RC" = 75 -a ! -e "$SB/hj-b")" "rc=$RC $OUT"
echo "warn $(date +%s) free disk 8 GiB;swap 80%" > "$SB/store/.host-state"
rm -f "$SB/hj-c"; hjrun --ignore-host-disk -- touch "$SB/hj-c"
check "--ignore-host-disk: disk + swap -> blocks (75), says why" "$(ok "$RC" = 75 -a ! -e "$SB/hj-c" -a -n "$(echo "$OUT" | grep 'host-monitor says warn (free disk 8 GiB;swap 80%)')")" "rc=$RC $OUT"
echo "critical $(date +%s) thermal warning recorded" > "$SB/store/.host-state"
rm -f "$SB/hj-d"; hjrun --ignore-host-disk -- touch "$SB/hj-d"
check "--ignore-host-disk: critical thermal -> blocks (75)" "$(ok "$RC" = 75 -a ! -e "$SB/hj-d")" "rc=$RC $OUT"
echo "warn $(date +%s) free memory 20%" > "$SB/store/.host-state"
rm -f "$SB/hj-e"; hjrun --ignore-host-disk -- touch "$SB/hj-e"
check "--ignore-host-disk: memory warn -> blocks (75)" "$(ok "$RC" = 75 -a ! -e "$SB/hj-e")" "rc=$RC $OUT"

echo "== --ignore-host-swap: only the warn-level swap reason passes (Pulzus 12317)"
echo "warn $(date +%s) free disk 8 GiB;swap 94%" > "$SB/store/.host-state"
rm -f "$SB/hj-f"; hjrun --ignore-host-disk --ignore-host-swap -- touch "$SB/hj-f"
check "both flags: disk + swap warn (the 2026-10-20 23:5x state) -> runs" "$(ok "$RC" = 0 -a -e "$SB/hj-f")" "rc=$RC $OUT"
rm -f "$SB/hj-g"; hjrun --ignore-host-swap -- touch "$SB/hj-g"
check "--ignore-host-swap alone: the disk reason still blocks (75)" "$(ok "$RC" = 75 -a ! -e "$SB/hj-g")" "rc=$RC $OUT"
echo "warn $(date +%s) swap 94%" > "$SB/store/.host-state"
rm -f "$SB/hj-h"; hjrun --ignore-host-swap -- touch "$SB/hj-h"
check "--ignore-host-swap: swap warn only -> runs" "$(ok "$RC" = 0 -a -e "$SB/hj-h")" "rc=$RC $OUT"
rm -f "$SB/hj-i"; hjrun -- touch "$SB/hj-i"
check "without the flag the same swap warn still blocks (75)" "$(ok "$RC" = 75 -a ! -e "$SB/hj-i")" "rc=$RC $OUT"
rm -f "$SB/hj-j"; hjrun --ignore-host-swap --min-free 80 --kill-below 10 -- touch "$SB/hj-j"
check "--ignore-host-swap: heavy-job's own memory floor still applies (70% free < 80%) -> blocks (75)" "$(ok "$RC" = 75 -a ! -e "$SB/hj-j" -a -n "$(echo "$OUT" | grep 'free memory 70% < 80%')")" "rc=$RC $OUT"
echo "critical $(date +%s) free disk 2 GiB;swap 95% with free memory 20%" > "$SB/store/.host-state"
rm -f "$SB/hj-k"; hjrun --ignore-host-disk --ignore-host-swap -- touch "$SB/hj-k"
check "both flags: critical swap with low memory -> blocks (75)" "$(ok "$RC" = 75 -a ! -e "$SB/hj-k")" "rc=$RC $OUT"
echo "warn $(date +%s) free disk 8 GiB;swap 94%;load 20.1 on 8 CPUs" > "$SB/store/.host-state"
rm -f "$SB/hj-l"; hjrun --ignore-host-disk --ignore-host-swap -- touch "$SB/hj-l"
check "both flags: a load reason next to them -> blocks (75)" "$(ok "$RC" = 75 -a ! -e "$SB/hj-l")" "rc=$RC $OUT"
echo "warn $(date +%s) free memory 20%;swap 94%" > "$SB/store/.host-state"
rm -f "$SB/hj-m"; hjrun --ignore-host-disk --ignore-host-swap -- touch "$SB/hj-m"
check "both flags: a memory warn next to the swap -> blocks (75)" "$(ok "$RC" = 75 -a ! -e "$SB/hj-m")" "rc=$RC $OUT"
rm -f "$SB/store/.host-state"

echo "== what a run clears"
LAST= dc run
check "run: brew, npm, pip, go each called once with the cache command" "$(grep -qx 'brew cleanup -s --prune=all' "$SB/calls" && grep -qx 'npm cache clean --force' "$SB/calls" && grep -qx 'pip3 cache purge' "$SB/calls" && grep -qx 'go clean -cache' "$SB/calls" && [ "$(wc -l < "$SB/calls")" -eq 4 ] && echo 0 || echo 1)" "$(cat "$SB/calls" 2>/dev/null)"
check "...rc 0, one STEP line per tool in the log" "$(ok "$RC" = 0 -a "$(grep -c 'STEP \(brew\|npm\|pip\|go\) rc=0' "$SB/store/daily-cleanup.log")" -ge 4)" "rc=$RC"
check "...the tools' output is in last-run.txt, not on stdout" "$(ok -z "$OUT" -a -n "$(grep '== npm' "$SB/store/daily-cleanup.last-run.txt")")" "out=$OUT"
STUB_ENV="STUB_RC_brew=1" LAST= dc run
check "a failing step: rc 1, the other steps still run" "$(ok "$RC" = 1 -a "$(wc -l < "$SB/calls")" -eq 4)" "rc=$RC $(cat "$SB/calls")"
mv "$SB/bin/go" "$SB/go.off"
LAST= dc run
check "a missing tool is skipped and logged, rc 0" "$(ok "$RC" = 0 -a -n "$(grep 'STEP go skipped: go not installed' "$SB/store/daily-cleanup.log")")" "rc=$RC"
mv "$SB/go.off" "$SB/bin/go"

echo "== scratch"
S="$SB/scratch"; OUTSIDE="$SB/outside"
mkdir -p "$S/-projA/old/sub" "$S/-projA/fresh" "$S/-projB/deep/a/b" "$S/bash-edit-diff/oldhash" "$OUTSIDE/victim"
echo x > "$S/-projA/old/sub/f"; echo x > "$S/-projA/fresh/f"; echo x > "$S/-projB/deep/a/b/f"; echo x > "$OUTSIDE/victim/f"; echo x > "$S/topfile"
echo x > "$S/bash-edit-diff/oldhash/f"
touch -t 202001010000 "$S/bash-edit-diff/oldhash/f" "$S/bash-edit-diff/oldhash" "$S/-projA/old/sub/f" "$S/-projA/old/sub" "$S/-projA/old" "$S/-projB/deep/a" "$S/-projB/deep" "$OUTSIDE/victim/f" "$OUTSIDE/victim" "$S/topfile"
ln -s "$OUTSIDE/victim" "$S/-projA/linked"
ln -s "$OUTSIDE" "$S/-projC"
LAST= dc run
check "a session dir idle for 7+ days is removed" "$(ok ! -e "$S/-projA/old")" "$(ls -la "$S/-projA")"
check "a fresh session dir stays" "$(ok -f "$S/-projA/fresh/f")"
check "an old session dir with one recent file deep inside stays" "$(ok -f "$S/-projB/deep/a/b/f")"
check "a symlinked session and project are not followed: their target stays" "$(ok -f "$OUTSIDE/victim/f" -a -L "$S/-projA/linked" -a -L "$S/-projC")"
check "a non-project dir (bash-edit-diff), even if idle, is not touched" "$(ok -f "$S/bash-edit-diff/oldhash/f")"
check "files at the top of the scratch root are not touched" "$(ok -f "$S/topfile")"
check "...logged: removed=1" "$(ok -n "$(grep 'STEP scratch removed=1 ' "$SB/store/daily-cleanup.log")")" "$(grep scratch "$SB/store/daily-cleanup.log")"

echo "== release runs (Pulzus 14571)"
R="$SB/release"; RR="$R/runs"; mkdir -p "$RR" "$SB/rel-outside/src"; echo x > "$SB/rel-outside/src/f"
iso() { python3 -c 'import datetime as d,sys; print(d.datetime.fromtimestamp(int(sys.argv[1]), d.timezone.utc).isoformat())' "$1"; }
D=86400; OLD="$(iso $((NOW - 5 * D)))"; NEW="$(iso $((NOW - D)))"
mkrun() { mkdir -p "$RR/$1/src/sub"; echo x > "$RR/$1/src/sub/f"; echo t > "$RR/$1/src.tar.gz"; echo '{}' > "$RR/$1/state.json"; echo '{}' > "$RR/$1/merge.json"; }
for r in 20330101-000000-aaa1 20330101-000000-aaa2 20330101-000000-aaa3 20330101-000000-aaa4 20330101-000000-aaa5 20330101-000000-aaa6; do mkrun "$r"; done
mkdir -p "$RR/20330101-000000-aaa7"; ln -s "$SB/rel-outside/src" "$RR/20330101-000000-aaa7/src"; echo t > "$RR/20330101-000000-aaa7/src.tar.gz"
mkdir -p "$RR/notarun/src"; echo x > "$RR/notarun/src/f"
{
  echo "{\"run_id\":\"20330101-000000-aaa1\",\"step\":\"merged\",\"ts\":\"$OLD\"}"
  echo "{\"run_id\":\"20330101-000000-aaa1\",\"step\":\"deployed\",\"ts\":\"$OLD\"}"
  echo "{\"run_id\":\"20330101-000000-aaa2\",\"step\":\"merged\",\"ts\":\"$OLD\"}"
  echo "{\"run_id\":\"20330101-000000-aaa2\",\"step\":\"migration_applied\",\"ts\":\"$OLD\"}"
  echo "{\"run_id\":\"20330101-000000-aaa3\",\"step\":\"deployed\",\"ts\":\"$NEW\"}"
  echo "{\"run_id\":\"20330101-000000-aaa4\",\"step\":\"deploy_stopped\",\"ts\":\"$OLD\"}"
  echo "{\"run_id\":\"20330101-000000-aaa5\",\"step\":\"deployed\",\"ts\":\"$OLD\"}"
  echo 'not json'
  echo "{\"run_id\":\"20330101-000000-aaa5\",\"step\":\"release_token_note\",\"ts\":\"$NEW\"}"
  echo "{\"run_id\":\"20330101-000000-aaa7\",\"step\":\"deployed\",\"ts\":\"$OLD\"}"
  echo "{\"run_id\":\"notarun\",\"step\":\"deployed\",\"ts\":\"$OLD\"}"
} > "$R/ledger.jsonl"
REL_DIR="$R" LAST= dc run
check "closed run, last entry 5 days old: src/ and the tarball go" "$(ok ! -e "$RR/20330101-000000-aaa1/src" -a ! -e "$RR/20330101-000000-aaa1/src.tar.gz")" "$(ls "$RR/20330101-000000-aaa1")"
check "...its *.json stay (audit)" "$(ok -f "$RR/20330101-000000-aaa1/state.json" -a -f "$RR/20330101-000000-aaa1/merge.json")"
check "merged + migrated but not deployed, 5 days: src/ goes, the tarball stays" "$(ok ! -e "$RR/20330101-000000-aaa2/src" -a -f "$RR/20330101-000000-aaa2/src.tar.gz")"
check "closed run, last entry 1 day old: both stay" "$(ok -f "$RR/20330101-000000-aaa3/src/sub/f" -a -f "$RR/20330101-000000-aaa3/src.tar.gz")"
check "deploy_stopped only (a resume reads the tarball): the tarball stays, src/ goes" "$(ok -f "$RR/20330101-000000-aaa4/src.tar.gz" -a ! -e "$RR/20330101-000000-aaa4/src")"
check "the age is the LAST ledger entry: an old deploy with a 1-day-old note stays" "$(ok -f "$RR/20330101-000000-aaa5/src/sub/f" -a -f "$RR/20330101-000000-aaa5/src.tar.gz")"
check "a run with no ledger entry is not touched" "$(ok -f "$RR/20330101-000000-aaa6/src/sub/f" -a -f "$RR/20330101-000000-aaa6/src.tar.gz")"
check "a symlinked src/ is left, and its target is not touched" "$(ok -L "$RR/20330101-000000-aaa7/src" -a -f "$SB/rel-outside/src/f" -a ! -e "$RR/20330101-000000-aaa7/src.tar.gz")"
check "a directory not named like a run id is not touched" "$(ok -f "$RR/notarun/src/f")"
check "...rc 0, logged with the counts" "$(ok "$RC" = 0 -a -n "$(grep 'STEP release-runs rc=0 removed_src=3 removed_tar=2 kept_open=2 ' "$SB/store/daily-cleanup.log")")" "rc=$RC $(grep release-runs "$SB/store/daily-cleanup.log" | tail -1)"
mv "$R/ledger.jsonl" "$R/ledger.off"; mkrun 20330101-000000-aab1
REL_DIR="$R" LAST= dc run
check "no readable ledger: nothing removed, the step fails (rc 1)" "$(ok "$RC" = 1 -a -f "$RR/20330101-000000-aab1/src/sub/f" -a -n "$(grep 'STEP release-runs rc=1 stop: the ledger cannot be read' "$SB/store/daily-cleanup.log")")" "rc=$RC $(grep release-runs "$SB/store/daily-cleanup.log" | tail -1)"
mv "$R/ledger.off" "$R/ledger.jsonl"; echo "{\"run_id\":\"20330101-000000-aab1\",\"step\":\"deployed\",\"ts\":\"$OLD\"}" >> "$R/ledger.jsonl"
for days in 0 -1 0.5 nan; do
  REL_DIR="$R" LAST= STUB_ENV="DAILY_CLEANUP_RELEASE_DAYS=$days" dc run
  check "DAILY_CLEANUP_RELEASE_DAYS=$days is refused: nothing removed, the step fails (rc 2)" "$(ok "$RC" = 1 -a -f "$RR/20330101-000000-aab1/src/sub/f" -a -f "$RR/20330101-000000-aab1/src.tar.gz" -a -n "$(grep 'STEP release-runs rc=2 ' "$SB/store/daily-cleanup.log" | tail -1)")" "rc=$RC $(grep release-runs "$SB/store/daily-cleanup.log" | tail -1)"
  printf '' > "$SB/store/daily-cleanup.log"
done
LAST= dc run
check "no release dir: the step is skipped and logged, rc 0" "$(ok "$RC" = 0 -a -n "$(grep "STEP release-runs skipped: no $SB/no-release/runs" "$SB/store/daily-cleanup.log")")" "rc=$RC"

echo "== worktrees and build caches (card c310dd1b)"
G() { git -c user.name=t -c user.email=t@t -c init.defaultBranch=main -c advice.detachedHead=false "$@" >/dev/null 2>&1; }
I="$SB/inst"; A="$I/agents/a/repos"
mkdir -p "$I" && G -C "$I" init && echo base > "$I/f"
# As in the real repos: the caches and node_modules are ignored, so they never make a tree dirty.
printf '.next\n.turbo\ntest-results\nplaywright-report\nnode_modules\n.env*.local\nout/\n.DS_Store\n' > "$I/.gitignore"
G -C "$I" add f .gitignore && G -C "$I" commit -m base
mkdir -p "$A"
G -C "$I" update-ref refs/remotes/origin/main HEAD
for w in merged dirty recent busy target kept linker envlocal regen evil; do G -C "$I" worktree add -b "b-$w" "$A/wt-$w" origin/main; done
# Unmerged: a commit main does not have.
G -C "$I" worktree add -b b-unmerged "$A/wt-unmerged" origin/main
echo u > "$A/wt-unmerged/u" && G -C "$A/wt-unmerged" add u && G -C "$A/wt-unmerged" commit -m unmerged
# Squash-merged: one commit, and main got a patch-equivalent one.
G -C "$I" worktree add -b b-squash "$A/wt-squash" origin/main
echo s > "$A/wt-squash/s" && G -C "$A/wt-squash" add s && G -C "$A/wt-squash" commit -m squash
G -C "$I" cherry-pick b-squash && G -C "$I" update-ref refs/remotes/origin/main HEAD
# A second clone under repos/, with a merged worktree of its own.
C="$A/c1"; mkdir -p "$C" && G -C "$C" init && echo c > "$C/f" && G -C "$C" add f && G -C "$C" commit -m c && G -C "$C" update-ref refs/remotes/origin/main HEAD
G -C "$C" worktree add -b c-merged "$A/c1-merged" origin/main
# A merged worktree outside agents/: never removed, its cache never touched.
G -C "$I" worktree add -b b-outside "$SB/outside-wt" origin/main
echo x > "$A/wt-dirty/untracked"
# Ignored but precious (Viktor 21749 M1): a pulled .env.local and a local out/ keep a merged tree.
echo "SOMETHING=1" > "$A/wt-envlocal/.env.local"; mkdir -p "$A/wt-envlocal/out" && echo r > "$A/wt-envlocal/out/render.png"
# Ignored and regenerable only: still goes.
echo d > "$A/wt-regen/.DS_Store"; mkdir -p "$A/wt-regen/.next" "$A/wt-regen/node_modules/x"
# A symlinked apps/<x> leading out of the tree (Viktor 21749 L1): the .next behind it is not this tree's.
mkdir -p "$SB/elsewhere/.next/keep" "$A/wt-evil/apps" && ln -s "$SB/elsewhere" "$A/wt-evil/apps/evil"
echo "u" > "$A/wt-evil/u" && G -C "$A/wt-evil" add -A && G -C "$A/wt-evil" commit -m evil   # unmerged: kept, its caches looked at
ln -s "$A/wt-target/node_modules" "$A/wt-linker/node_modules"; mkdir -p "$A/wt-target/node_modules"
echo "$A/wt-kept  # Dave's running work" > "$SB/store/daily-cleanup.keep"
for t in "$A/wt-unmerged" "$A/wt-busy" "$SB/outside-wt" "$I"; do mkdir -p "$t/.next/cache" && echo b > "$t/.next/cache/b"; done
mkdir -p "$A/wt-unmerged/apps/web/.next" "$A/wt-unmerged/test-results"
ln -s "$SB/home" "$A/wt-unmerged/.turbo"
# Everything is years older than NOW (2033) except the recent tree.
touch -t 203305170000 "$A/wt-recent/f"
echo "$A/wt-busy/sub" > "$SB/cwds"; mkdir -p "$A/wt-busy/sub"
INST="$I" LAST= dc run
WL="$(grep 'STEP worktrees' "$SB/store/daily-cleanup.log" | tail -1)"
AR="$(cd "$A" && pwd -P)"  # the script prints resolved paths (/var -> /private/var on macOS)
check "a merged, clean, idle worktree is removed (and pruned from the list)" "$(ok ! -e "$A/wt-merged" -a -z "$(git -C "$I" worktree list | grep wt-merged)")" "$WL"
check "...its branch stays" "$(git -C "$I" rev-parse --verify --quiet b-merged >/dev/null && echo 0 || echo 1)"
check "a squash-merged single commit counts as merged (git cherry)" "$(ok ! -e "$A/wt-squash")" "$WL"
check "a merged worktree of a second clone under repos/ is removed" "$(ok ! -e "$A/c1-merged")"
check "not merged: kept, its idle .next, apps/*/.next and test-results go" "$(ok -d "$A/wt-unmerged" -a ! -e "$A/wt-unmerged/.next" -a ! -e "$A/wt-unmerged/apps/web/.next" -a ! -e "$A/wt-unmerged/test-results")"
check "...a symlinked cache is not followed or removed" "$(ok -L "$A/wt-unmerged/.turbo" -a -d "$SB/home")"
check "an ignored .env.local / out/: kept, listed with the ignored paths" "$(ok -f "$A/wt-envlocal/.env.local" -a -f "$A/wt-envlocal/out/render.png" -a -n "$(grep "keep $AR/wt-envlocal ignored files: " "$SB/store/daily-cleanup.last-run.txt")")" "$(grep wt-envlocal "$SB/store/daily-cleanup.last-run.txt")"
check "ignored but regenerable only (.DS_Store, .next, node_modules): removed" "$(ok ! -e "$A/wt-regen")"
check "a .next behind a symlinked apps/<x> is outside the tree: untouched" "$(ok -d "$SB/elsewhere/.next/keep" -a -L "$A/wt-evil/apps/evil")"
check "dirty (an untracked file): kept" "$(ok -f "$A/wt-dirty/untracked")"
check "a source file changed within 3 days: kept" "$(ok -d "$A/wt-recent")"
check "busy (a process cwd inside): kept, and its .next too" "$(ok -d "$A/wt-busy" -a -f "$A/wt-busy/.next/cache/b")"
check "another tree's node_modules links into it: kept" "$(ok -d "$A/wt-target" -a -d "$A/wt-target/node_modules")"
check "...the tree that links (merged, clean) goes; the symlink only, its target stays" "$(ok ! -e "$A/wt-linker" -a -d "$A/wt-target/node_modules")"
check "listed in store/daily-cleanup.keep: kept" "$(ok -d "$A/wt-kept")"
check "outside agents/: kept, its .next untouched" "$(ok -d "$SB/outside-wt" -a -f "$SB/outside-wt/.next/cache/b")"
check "the install dir's own .next is never touched" "$(ok -f "$I/.next/cache/b")"
check "...the run's rc is 0, logged with the counts" "$(ok "$RC" = 0 -a -n "$(echo "$WL" | grep 'rc=0 worktrees_removed=5 caches_removed=3 ')")" "rc=$RC $WL"
check "...each kept merged tree is listed with its reason" "$(L="$SB/store/daily-cleanup.last-run.txt"; grep -q "keep $AR/wt-dirty dirty" "$L" && grep -q "keep $AR/wt-target linked" "$L" && grep -q "keep $AR/wt-kept keep-file" "$L" && grep -q "keep $AR/wt-busy busy" "$L" && grep -q "keep $AR/wt-unmerged not merged" "$L" && grep -q "keep $AR/wt-recent changed within 3 days" "$L" && echo 0 || echo 1)" "$(grep keep "$SB/store/daily-cleanup.last-run.txt")"
# lsof cannot run: every tree is busy, nothing goes.
G -C "$I" worktree add -b b-merged2 "$A/wt-merged2" origin/main; mkdir -p "$A/wt-unmerged/.next"
INST="$I" LSOF_BIN="$SB/no-lsof" LAST= dc run
check "lsof unavailable: nothing removed, said so" "$(ok -d "$A/wt-merged2" -a -d "$A/wt-unmerged/.next" -a -n "$(grep 'lsof unavailable' "$SB/store/daily-cleanup.last-run.txt")")" "$(tail -3 "$SB/store/daily-cleanup.last-run.txt")"
# Run from a worktree copy: the install is not a main tree, the step is skipped.
INST="$A/wt-merged2" LAST= dc run
check "the install dir is a worktree, not a main tree: the step is skipped, rc 0" "$(ok "$RC" = 0 -a -d "$A/wt-merged2" -a -n "$(grep "STEP worktrees skipped: $A/wt-merged2 is not a clone's main tree" "$SB/store/daily-cleanup.log")")" "rc=$RC"
check "no install dir: skipped (the other steps' tests above rely on it)" "$(ok -n "$(grep "STEP worktrees skipped: $SB/no-install is not a clone's main tree" "$SB/store/daily-cleanup.log")")"

echo "== transcripts (Klodel 21739)"
TP="$I/agents/a/.claude-config/projects/-x"; HP="$SB/home/.claude/projects/-y"
mkdir -p "$TP/sess/subagents" "$TP/memory" "$HP" "$I/agents/b/.claude-config"
for f in "$TP/late.jsonl" "$TP/dup.jsonl" "$TP/old.jsonl" "$TP/recent.jsonl" "$TP/sess/subagents/s.jsonl" "$TP/memory/m.jsonl" "$TP/notes.md" "$TP/open.jsonl" "$HP/main.jsonl"; do printf '{"a":1}\n%.0s' $(seq 1 200) > "$f"; done
touch -t 203305170000 "$TP/recent.jsonl"   # a day before NOW (2033): stays
echo kept > "$TP/dup.jsonl.gz"   # a gunzip -k by hand left the .gz: skipped, not failed
ln -s "$I/agents/a/.claude-config/projects" "$I/agents/b/.claude-config/projects"   # the same dir twice: once
echo "$TP/open.jsonl" > "$SB/cwds"; echo "$(cd "$TP" && pwd -P)/late.jsonl" > "$SB/late"   # resumed while the run goes (lsof prints resolved paths)
INST="$I" LAST= dc run
TL="$(grep 'STEP transcripts' "$SB/store/daily-cleanup.log" | tail -1)"
check "an old transcript is gzipped in place (the .gz readable, the original gone)" "$(ok -f "$TP/old.jsonl.gz" -a ! -e "$TP/old.jsonl" -a "$(gzip -dc "$TP/old.jsonl.gz" | wc -l | tr -d ' ')" = 200)" "$TL"
check "...a subagent transcript under a session dir too, and the main agent's under ~/.claude/projects" "$(ok -f "$TP/sess/subagents/s.jsonl.gz" -a -f "$HP/main.jsonl.gz")"
check "changed within 7 days: stays" "$(ok -f "$TP/recent.jsonl" -a ! -e "$TP/recent.jsonl.gz")"
check "opened after the run's first look (the per-file lsof right before the gzip): stays (Viktor 21765)" "$(ok -f "$TP/late.jsonl" -a ! -e "$TP/late.jsonl.gz")"
check "open (lsof): stays" "$(ok -f "$TP/open.jsonl")"
check "a .gz already there: the .jsonl is skipped, both stay" "$(ok -f "$TP/dup.jsonl" -a "$(cat "$TP/dup.jsonl.gz")" = kept)"
check "memory/ and non-jsonl files are never touched" "$(ok -f "$TP/memory/m.jsonl" -a -f "$TP/notes.md")"
check "...rc 0, logged with the counts; a symlinked projects dir is walked once" "$(ok "$RC" = 0 -a -n "$(echo "$TL" | grep 'rc=0 gzipped=3 .* open=2 exists=1 ')")" "rc=$RC $TL"
: > "$SB/cwds"; printf '{"a":1}\n' > "$TP/old2.jsonl"
INST="$I" LSOF_BIN="$SB/no-lsof" LAST= dc run
check "lsof unavailable: nothing gzipped, said so, rc 0" "$(ok "$RC" = 0 -a -f "$TP/old2.jsonl" -a -n "$(grep 'stop: lsof unavailable' "$SB/store/daily-cleanup.last-run.txt")")" "rc=$RC"
INST="$I" LAST= STUB_ENV="DAILY_CLEANUP_TRANSCRIPT_DAYS=1" dc run
check "DAILY_CLEANUP_TRANSCRIPT_DAYS=1 is refused: nothing gzipped, the step fails" "$(ok "$RC" = 1 -a -f "$TP/old2.jsonl" -a -n "$(grep 'STEP transcripts rc=2 ' "$SB/store/daily-cleanup.log")")" "rc=$RC"

echo "== the low-disk alert (Klodel 21709)"
rm -f "$SB/msgs" "$SB/store/.daily-cleanup.alert"
HOUR=12 LAST=$((NOW - 2 * H)) DF_KB=$((15 * GB)) dc tick
check "15 GiB free, no run due -> one message to each of pulzus and klodel" "$(ok "$(grep -c '^daily-cleanup ' "$SB/msgs" 2>/dev/null)" = 2 -a -n "$(grep '^daily-cleanup pulzus \[DAILY-CLEANUP\] A lemezen 15 GiB szabad' "$SB/msgs")" -a -n "$(grep '^daily-cleanup klodel ' "$SB/msgs")")" "$(cat "$SB/msgs" 2>/dev/null)"
check "...and the cooldown stamp is set" "$(ok "$(cat "$SB/store/.daily-cleanup.alert" 2>/dev/null)" = "$NOW")"
HOUR=12 LAST=$((NOW - 2 * H)) DF_KB=$((15 * GB)) dc tick
check "again within 6 h -> nothing more" "$(ok "$(grep -c '^daily-cleanup ' "$SB/msgs")" = 2)"
echo $((NOW - 7 * H)) > "$SB/store/.daily-cleanup.alert"
HOUR=12 LAST=$((NOW - 2 * H)) DF_KB=$((15 * GB)) dc tick
check "7 h after the last one -> sent again" "$(ok "$(grep -c '^daily-cleanup ' "$SB/msgs")" = 4)"
rm -f "$SB/msgs" "$SB/store/.daily-cleanup.alert"
HOUR=12 LAST=$((NOW - 2 * H)) DF_KB=$((21 * GB)) dc tick
check "21 GiB free -> no alert" "$(ok ! -f "$SB/msgs")"
HOUR=12 LAST=$((NOW - 2 * H)) DF_KB=$((9 * GB)) dc tick
check "9 GiB free: the disk-gate run first, then the alert" "$(ok "$(ran)" = 0 -a "$(grep -c '^daily-cleanup ' "$SB/msgs" 2>/dev/null)" = 2)" "$(cat "$SB/msgs" 2>/dev/null)"
rm -f "$SB/msgs" "$SB/store/.daily-cleanup.alert"
HOUR=12 LAST=$((NOW - 2 * H)) DF_KB=$((15 * GB)) STUB_ENV="STUB_RC_msg=1" dc tick
check "a failed send: no cooldown stamp (next tick retries), logged" "$(ok ! -f "$SB/store/.daily-cleanup.alert" -a -n "$(grep 'ALERT to pulzus FAILED' "$SB/store/daily-cleanup.log")")"
HOUR=12 LAST=$((NOW - 2 * H)) DF_KB=$((15 * GB)) STUB_ENV="DAILY_CLEANUP_ALERT_GB=10" dc tick
check "DAILY_CLEANUP_ALERT_GB=10: 15 GiB free is fine" "$(ok ! -f "$SB/store/.daily-cleanup.alert")"

echo "== install-daily-cleanup.sh (macOS launchd)"
FAKEHOME="$SB/ihome"; mkdir -p "$FAKEHOME" "$SB/ubin"
printf '#!/bin/bash\necho Darwin\n' > "$SB/ubin/uname"; chmod +x "$SB/ubin/uname"
printf '#!/bin/bash\necho "launchctl $*" >> "%s/launchctl.calls"\n' "$SB" > "$SB/ubin/launchctl"; chmod +x "$SB/ubin/launchctl"
P="$FAKEHOME/Library/LaunchAgents/com.marveen.daily-cleanup.plist"
OUT="$(PATH="$SB/ubin:$PATH" HOME="$FAKEHOME" bash "$ROOT/scripts/install-daily-cleanup.sh" 2>&1)"; RC=$?
check "the installer writes the plist and does not load it" "$(ok "$RC" = 0 -a -f "$P" -a ! -f "$SB/launchctl.calls")" "rc=$RC $OUT"
if command -v plutil >/dev/null 2>&1; then
  check "the plist is valid" "$(plutil -lint "$P" >/dev/null 2>&1 && echo 0 || echo 1)" "$(plutil -lint "$P" 2>&1)"
fi
check "the plist ticks this script at load and every hour, with the install's store" "$(grep -A3 ProgramArguments "$P" | grep -q "<string>$ROOT/scripts/daily-cleanup.sh</string>" && grep -A4 ProgramArguments "$P" | grep -q '<string>tick</string>' && grep -A1 RunAtLoad "$P" | grep -q '<true/>' && grep -A1 StartInterval "$P" | grep -q '<integer>3600</integer>' && grep -A1 MARVEEN_STORE "$P" | grep -q "<string>$ROOT/store</string>" && echo 0 || echo 1)" "$(cat "$P" 2>/dev/null)"
check "stdout is dropped, stderr kept in the store" "$(grep -A1 StandardOutPath "$P" | grep -q '<string>/dev/null</string>' && grep -A1 StandardErrorPath "$P" | grep -q "<string>$ROOT/store/daily-cleanup.err.log</string>" && echo 0 || echo 1)"
OUT="$(PATH="$SB/ubin:$PATH" HOME="$FAKEHOME" bash "$ROOT/scripts/install-daily-cleanup.sh" --load 2>&1)"; RC=$?
check "there is no --load path: any option is refused (64) and nothing is loaded" "$(ok "$RC" = 64 -a ! -f "$SB/launchctl.calls")" "rc=$RC $OUT"
OUT="$(PATH="$SB/ubin:$PATH" HOME="$FAKEHOME" bash -c 'uname() { echo Linux; }; export -f uname; bash "$1"' _ "$ROOT/scripts/install-daily-cleanup.sh" 2>&1)"; RC=$?
check "the installer refuses on Linux" "$(ok "$RC" != 0)" "$OUT"

echo
echo "$((DONE-FAILS))/$DONE passed"
[ "$FAILS" = "0" ] || exit 1
