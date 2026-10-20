#!/usr/bin/env bash
# MEMGATEMAC1020 -- the macOS memory source (lib/mem-read.sh), the gate on it,
# and the heavy-job lock + watchdog (heavy-job.sh).
#
# WHAT THIS GUARDS, MEASURED 2026-10-20 on the Mac mini:
#   - fleet-memory-gate.sh on origin/main (a36234b5) printed
#     "meminfo-unreadable: allow" on every call: no /proc on macOS, so the gate
#     never limited anything. That morning the box panicked with free memory
#     at 871 pages, an mflux job, a 6 GB VM and 14 claude sessions running.
#   - Nothing serialised heavy jobs (mflux, whisper, render, colima).
#
# Memory is faked with a sysctl stand-in that reads its level from a file, so
# the watchdog can be driven mid-run. Nothing here touches the real store or
# sends anything (curl is stubbed).
#
# Run:  bash scripts/__tests__/memgate-macos-heavy-job.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
GATE="${MEMGATE_SCRIPT:-$ROOT/scripts/fleet-memory-gate.sh}"
HJ="$ROOT/scripts/heavy-job.sh"
for f in "$GATE" "$HJ" "$ROOT/scripts/lib/mem-read.sh"; do
  [ -e "$f" ] || { echo "FATAL: the script under test is missing: $f" >&2; exit 2; }
done

FAILS=0; DONE=0
check() { DONE=$((DONE+1)); if [ "$2" = "0" ]; then echo "PASS  $1"; else echo "FAIL  $1${3:+  -- $3}"; FAILS=$((FAILS+1)); fi; }
ok() { [ "$@" ] && echo 0 || echo 1; }

SB="$(mktemp -d "${TMPDIR:-/tmp}/memgatemac.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
mkdir -p "$SB/store" "$SB/bin"
printf '#!/usr/bin/env bash\necho %s\n' "'{\"ok\":true,\"result\":{\"message_id\":1}}'" > "$SB/bin/curl"
# sysctl stand-in: 16 GiB, free percentage from $SB/level ("bad" -> garbage).
cat > "$SB/sysctl" <<STUB
#!/usr/bin/env bash
case "\$2" in
  hw.memsize) echo 17179869184 ;;
  kern.memorystatus_level) cat "$SB/level" ;;
  *) exit 1 ;;
esac
STUB
chmod +x "$SB/bin/curl" "$SB/sysctl"
level() { echo "$1" > "$SB/level"; }
# No VM unless a test says so: the host running this test may have a real one.
export HEAVY_JOB_VM_PID=""

# MEMGATE_PROC_MEMINFO points at a file that does not exist, so the Linux path
# is skipped on any host and the sysctl stand-in is the only source.
gate() {
  rm -f "$SB/store/.fleet-safe-mode" "$SB/store/.fleet-memgate-alert"
  OUT="$(env PATH="$SB/bin:$PATH" MEMGATE_PROC_MEMINFO="$SB/no-such-meminfo" MEMGATE_SYSCTL="$SB/sysctl" \
      MARVEEN_STORE="$SB/store" MARVEEN_ALERT_CHAT_ID="111" MARVEEN_CORE_AGENTS="__no_core__" \
      MARVEEN_MEM_GATE_OBSERVE=0 bash "$GATE" "$@" 2>&1)"; RC=$?
}

echo "== gate on the macOS source"
level 75; gate --status --dry-run
check "free 75% -> used=25%, band ok, src=memorystatus" "$(ok "$RC" = 0 -a -n "$(echo "$OUT" | grep 'used=25% .*band=ok src=memorystatus')")" "rc=$RC $OUT"
level 15; gate --check worker --dry-run
check "free 15% -> non-core start blocked (warn, exit 10)" "$(ok "$RC" = 10 -a -n "$(echo "$OUT" | grep 'block non-core (warn)')")" "rc=$RC $OUT"
level 5; gate --check worker --dry-run
check "free 5% -> hard pause (exit 10)" "$(ok "$RC" = 10 -a -n "$(echo "$OUT" | grep 'band=hard')")" "rc=$RC $OUT"
level bad; gate --check worker --dry-run
check "garbage level -> fail-open allow (the gate never freezes the fleet)" "$(ok "$RC" = 0 -a -n "$(echo "$OUT" | grep 'meminfo-unreadable: allow')")" "rc=$RC $OUT"
printf 'MemTotal:       16000000 kB\nMemAvailable:    8000000 kB\n' > "$SB/meminfo"
OUT="$(env PATH="$SB/bin:$PATH" MEMGATE_PROC_MEMINFO="$SB/meminfo" MARVEEN_STORE="$SB/store" bash "$GATE" --status --dry-run 2>&1)"
check "Linux meminfo path unchanged (used=50%, src=meminfo)" "$(ok -n "$(echo "$OUT" | grep 'used=50% .*src=meminfo')")" "$OUT"
if [ "$(uname)" = "Darwin" ]; then
  OUT="$(env PATH="$SB/bin:$PATH" MARVEEN_STORE="$SB/store" bash "$GATE" --status --dry-run 2>&1)"
  check "real host (Darwin): the gate reads memory, not fail-open" "$(ok -n "$(echo "$OUT" | grep 'src=memorystatus')")" "$OUT"
fi

echo "== heavy-job.sh"
hj() { OUT="$(env HEAVY_JOB_STORE="$SB/store" HEAVY_JOB_POLL=1 MEMGATE_PROC_MEMINFO="$SB/no-such-meminfo" MEMGATE_SYSCTL="$SB/sysctl" \
      HEAVY_JOB_DF_KB="${DF_KB:-99999999}" bash "$HJ" "$@" 2>&1)"; RC=$?; }
LOCK="$SB/store/.heavy-job.lock"

level 70; hj --name t1 -- bash -c 'echo ran > "$0"; exit 3' "$SB/ran1"
check "runs the job and passes its exit code through (3)" "$(ok "$RC" = 3 -a -f "$SB/ran1")" "rc=$RC $OUT"
check "the lock is released after the job" "$(ok ! -e "$LOCK")"
check "START and END are logged" "$(ok -n "$(grep 'START free=70%' "$SB/store/heavy-job.log")" -a -n "$(grep 'END rc=3' "$SB/store/heavy-job.log")")"

level 30; hj --wait 0 -- touch "$SB/ran2"
check "free 30% < 40% -> not started (75), job did not run" "$(ok "$RC" = 75 -a ! -e "$SB/ran2")" "rc=$RC $OUT"

level bad; hj --wait 0 -- touch "$SB/ran3"
check "unreadable memory -> not started (fail-closed, 75)" "$(ok "$RC" = 75 -a ! -e "$SB/ran3")" "rc=$RC $OUT"

level 70; DF_KB=1000 hj --wait 0 -- touch "$SB/ran4"
check "disk below --min-disk-gb -> not started (75)" "$(ok "$RC" = 75 -a ! -e "$SB/ran4")" "rc=$RC $OUT"

sleep 60 & LIVE=$!
mkdir "$LOCK"; echo "$LIVE other $(date +%s)" > "$LOCK/owner"
hj --wait 1 -- touch "$SB/ran5"
check "lock held by a live job -> not started (75), says who holds it" "$(ok "$RC" = 75 -a ! -e "$SB/ran5" -a -n "$(echo "$OUT" | grep 'lock held by: '"$LIVE"' other')")" "rc=$RC $OUT"
check "a refused start leaves the other job's lock alone" "$(ok -n "$(grep "^$LIVE " "$LOCK/owner" 2>/dev/null)")"
kill "$LIVE" 2>/dev/null; wait "$LIVE" 2>/dev/null
hj --wait 2 -- touch "$SB/ran6"
check "stale lock (owner pid dead) is taken over and the job runs" "$(ok "$RC" = 0 -a -f "$SB/ran6" -a ! -e "$LOCK")" "rc=$RC $OUT"

# L1 (Viktor 9013): pid reuse, ownerless locks, the takeover mutex, the race.
true & DEAD=$!; wait "$DEAD"
clean() { rm -rf "$LOCK" "$LOCK.takeover"; }
clean; sleep 60 & LIVE=$!
mkdir "$LOCK"; echo "$LIVE other 1000" > "$LOCK/owner"
hj --wait 2 -- touch "$SB/ran7"
check "owner pid alive but started after the lock (reused pid) -> taken over" "$(ok "$RC" = 0 -a -f "$SB/ran7")" "rc=$RC $OUT"
kill "$LIVE" 2>/dev/null; wait "$LIVE" 2>/dev/null

clean; mkdir "$LOCK"
hj --wait 1 -- touch "$SB/ran8"
check "ownerless lock younger than 60 s is left alone (75)" "$(ok "$RC" = 75 -a ! -e "$SB/ran8" -a -d "$LOCK")" "rc=$RC $OUT"
touch -t 202001010000 "$LOCK"
hj --wait 2 -- touch "$SB/ran9"
check "ownerless lock older than 60 s is taken over" "$(ok "$RC" = 0 -a -f "$SB/ran9" -a ! -e "$LOCK")" "rc=$RC $OUT"

clean; mkdir "$LOCK" "$LOCK.takeover"; echo "$DEAD gone 1000" > "$LOCK/owner"
hj --wait 1 -- touch "$SB/ran10"
check "a fresh takeover mutex blocks the takeover; the stale lock stays" "$(ok "$RC" = 75 -a ! -e "$SB/ran10" -a -n "$(grep "^$DEAD gone" "$LOCK/owner" 2>/dev/null)")" "rc=$RC $OUT"
touch -t 202001010000 "$LOCK.takeover"
hj --wait 3 -- touch "$SB/ran11"
check "a takeover mutex older than 60 s is cleared, then the job runs" "$(ok "$RC" = 0 -a -f "$SB/ran11" -a ! -e "$LOCK" -a ! -e "$LOCK.takeover")" "rc=$RC $OUT"

# Six waiters see the same stale owner at once; the jobs must never overlap.
clean; mkdir "$LOCK"; echo "$DEAD gone 1000" > "$LOCK/owner"; : > "$SB/race"
for i in 1 2 3 4 5 6; do
  ( env HEAVY_JOB_STORE="$SB/store" HEAVY_JOB_POLL=1 MEMGATE_PROC_MEMINFO="$SB/no-such-meminfo" MEMGATE_SYSCTL="$SB/sysctl" \
      HEAVY_JOB_DF_KB=99999999 bash "$HJ" --wait 30 -- bash -c 'echo S >> "$0"; sleep 0.3; echo E >> "$0"' "$SB/race" >/dev/null 2>&1 ) &
done
wait
RACE="$(tr -d '\n' < "$SB/race")"
check "six waiters on one stale lock: all six ran, never two at once" "$(ok "$RACE" = SESESESESESE)" "sequence=$RACE"
check "no lock or takeover mutex is left behind" "$(ok ! -e "$LOCK" -a ! -e "$LOCK.takeover")"

# I1 (Viktor 9013): the log keeps the command name, not its arguments.
clean; SECRET="customer-$$.wav"
hj --name i1 --wait 5 -- bash -c 'exit 0' "$SB/$SECRET" $'two\nSTART forged'
check "the log has the command name only: no argument, no forged line" "$(ok "$RC" = 0 -a -z "$(grep -e "$SECRET" -e 'forged' "$SB/store/heavy-job.log")" -a -n "$(grep 'i1 .*START free=.*: bash$' "$SB/store/heavy-job.log")")" "$(tail -3 "$SB/store/heavy-job.log")"

# Watchdog: the job spawns a grandchild; memory drops mid-run; both must die.
clean
level 70
( sleep 3; level 10 ) &
T0=$(date +%s)
hj --name wd --wait 5 -- bash -c 'sleep 120 & echo $! > "$0"; wait' "$SB/grandchild"
T1=$(date +%s)
GC="$(cat "$SB/grandchild" 2>/dev/null)"
check "memory below --kill-below mid-run -> watchdog stop, exit 70" "$(ok "$RC" = 70)" "rc=$RC $OUT"
check "the watchdog acted within 15 s" "$(ok $((T1-T0)) -le 15)" "took $((T1-T0))s"
GC_ALIVE=no; [ -n "$GC" ] && kill -0 "$GC" 2>/dev/null && GC_ALIVE=yes
check "the grandchild (whole process group) is gone" "$(ok -n "$GC" -a "$GC_ALIVE" = no)" "gc=$GC alive=$GC_ALIVE"
[ "$GC_ALIVE" = yes ] && kill "$GC"
check "WATCHDOG STOP is logged" "$(ok -n "$(grep 'WATCHDOG STOP: free memory 10% < 25%' "$SB/store/heavy-job.log")")"
check "the lock is released after a watchdog stop" "$(ok ! -e "$LOCK")"

echo "== a running Colima VM holds the machine (Viktor 9013 L2)"
clean; level 70
HEAVY_JOB_VM_PID=4242 hj --name mflux --wait 1 -- bash -c 'echo ran > "$0"' "$SB/vm1"
check "VM running -> another heavy job is not started (75) and does not run" "$(ok "$RC" = 75 -a ! -e "$SB/vm1")" "rc=$RC $OUT"
check "...says it is the VM, with its pid and the way out" "$(ok -n "$(echo "$OUT" | grep 'a Colima VM is running (limactl pid 4242): it holds its memory until colima stop')")" "$OUT"
check "...and takes no lock" "$(ok ! -e "$LOCK")"
check "the test hook leaves a WARN in heavy-job.log (Viktor I1)" "$(ok -n "$(grep "WARN test hook HEAVY_JOB_VM_PID='4242'" "$SB/store/heavy-job.log")")"
HEAVY_JOB_VM_PID=4242 hj --name colima --allow-vm --wait 1 -- bash -c 'echo ran > "$0"' "$SB/vm2"
check "--allow-vm (the VM's own start, the cleanup) runs past a running VM" "$(ok "$RC" = 0 -a -f "$SB/vm2")" "rc=$RC $OUT"
level 30; HEAVY_JOB_VM_PID=4242 hj --name colima --allow-vm --wait 1 -- bash -c 'echo ran > "$0"' "$SB/vm3"
check "--allow-vm still waits for memory (75 at 30% free)" "$(ok "$RC" = 75 -a ! -e "$SB/vm3")" "rc=$RC $OUT"
level 70
# The real probe: a process that looks like Lima's host agent is found.
mkdir -p "$SB/lima"; printf '#!/usr/bin/env bash\nexec sleep 30\n' > "$SB/lima/limactl"; chmod +x "$SB/lima/limactl"
"$SB/lima/limactl" hostagent --pidfile x &
FAKE=$!; sleep 0.3
OUT="$(env -u HEAVY_JOB_VM_PID HEAVY_JOB_STORE="$SB/store" HEAVY_JOB_POLL=1 MEMGATE_PROC_MEMINFO="$SB/no-such-meminfo" MEMGATE_SYSCTL="$SB/sysctl" \
    HEAVY_JOB_DF_KB=99999999 bash "$HJ" --name probe --wait 0 -- bash -c 'echo ran > "$0"' "$SB/vm4" 2>&1)"; RC=$?
kill "$FAKE" 2>/dev/null; wait "$FAKE" 2>/dev/null
check "...and without the hook there is no WARN" "$(ok -z "$(echo "$OUT" | grep 'WARN test hook')")" "$OUT"
check "without the hook, a running 'limactl hostagent' is detected (75)" "$(ok "$RC" = 75 -a ! -e "$SB/vm4" -a -n "$(echo "$OUT" | grep 'a Colima VM is running (limactl pid [0-9]')")" "rc=$RC $OUT"

hj --name x
check "no command -> usage error (64)" "$(ok "$RC" = 64)" "rc=$RC"
hj --min-free 20 --kill-below 30 -- true
check "--kill-below >= --min-free -> usage error (64)" "$(ok "$RC" = 64)" "rc=$RC"

echo
echo "$((DONE-FAILS))/$DONE passed"
[ "$FAILS" = "0" ] || exit 1
