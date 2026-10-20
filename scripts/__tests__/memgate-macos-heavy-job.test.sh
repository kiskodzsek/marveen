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

# Watchdog: the job spawns a grandchild; memory drops mid-run; both must die.
level 70
( sleep 3; level 10 ) &
T0=$(date +%s)
hj --name wd -- bash -c 'sleep 120 & echo $! > "$0"; wait' "$SB/grandchild"
T1=$(date +%s)
GC="$(cat "$SB/grandchild" 2>/dev/null)"
check "memory below --kill-below mid-run -> watchdog stop, exit 70" "$(ok "$RC" = 70)" "rc=$RC $OUT"
check "the watchdog acted within 15 s" "$(ok $((T1-T0)) -le 15)" "took $((T1-T0))s"
GC_ALIVE=no; [ -n "$GC" ] && kill -0 "$GC" 2>/dev/null && GC_ALIVE=yes
check "the grandchild (whole process group) is gone" "$(ok -n "$GC" -a "$GC_ALIVE" = no)" "gc=$GC alive=$GC_ALIVE"
[ "$GC_ALIVE" = yes ] && kill "$GC"
check "WATCHDOG STOP is logged" "$(ok -n "$(grep 'WATCHDOG STOP: free memory 10% < 25%' "$SB/store/heavy-job.log")")"
check "the lock is released after a watchdog stop" "$(ok ! -e "$LOCK")"

hj --name x
check "no command -> usage error (64)" "$(ok "$RC" = 64)" "rc=$RC"
hj --min-free 20 --kill-below 30 -- true
check "--kill-below >= --min-free -> usage error (64)" "$(ok "$RC" = 64)" "rc=$RC"

echo
echo "$((DONE-FAILS))/$DONE passed"
[ "$FAILS" = "0" ] || exit 1
