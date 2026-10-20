#!/usr/bin/env bash
# DAILYCLEANUP1020 -- daily-cleanup.sh (when a run is due, what a run clears),
# heavy-job.sh --ignore-host-disk, and the macOS launchd installer (card 1c58f629).
#
# Every tool a run calls (brew, npm, pip3, go) is a stub that only records its
# argv; HOME, the store and the scratch root are inside a sandbox. Nothing here
# touches a real cache or the real store.
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
check "the run goes through heavy-job, past a disk-only host state, the disk floor and a running VM" "$(grep -q -- '--name daily-cleanup --ignore-host-disk --min-disk-gb 0 --allow-vm ' "$SB/hj.args" && echo 0 || echo 1)" "$(cat "$SB/hj.args" 2>/dev/null)"

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
