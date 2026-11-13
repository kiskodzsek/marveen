#!/usr/bin/env bash
# heavy-job.sh point 5 (retro R4, card 686f1b5f; Klodel 41236): a film export starts only after the film gate and
# the size gate, whichever script calls heavy-job.sh. 2026-11-13: the Meséld el! v10 export ran from a new script
# without ops/film_export_gate.py (Patrik TG 3735), and the v10c went out small and cut (Patrik csoport TG 5798).
#
# The two gates are stubbed (HEAVY_JOB_FILM_GATE_BIN / HEAVY_JOB_SIZE_GATE_BIN): each passes or fails on a marker file
# and records its arguments. Memory is faked as in memgate-macos-heavy-job.test.sh. Nothing touches the real store.
#
# Run:  bash scripts/__tests__/heavy-job-film-gate.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
HJ="$ROOT/scripts/heavy-job.sh"
[ -e "$HJ" ] || { echo "FATAL: missing $HJ" >&2; exit 2; }

FAILS=0; DONE=0
check() { DONE=$((DONE+1)); if [ "$2" = "0" ]; then echo "PASS  $1"; else echo "FAIL  $1${3:+  -- $3}"; FAILS=$((FAILS+1)); fi; }
# A case whose job really starts goes through heavy-job.sh's memory, swap, VM and lock checks, which this suite fakes
# for macOS only (the sysctl stand-in, as memgate-macos-heavy-job.test.sh, a MACOS_ONLY suite). Off macOS those cases
# are listed as SKIP; every refusal (exit 77) happens before the memory checks and runs everywhere.
IS_MAC=0; [ "$(uname -s)" = Darwin ] && IS_MAC=1
runs() { if [ "$IS_MAC" = 1 ]; then check "$@"; else echo "SKIP  $1 (starts the job: macOS memory path)"; fi; }
ok() { [ "$@" ] && echo 0 || echo 1; }

SB="$(mktemp -d "${TMPDIR:-/tmp}/hjfilm.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
mkdir -p "$SB/store" "$SB/stills" "$SB/frames"
cat > "$SB/sysctl" <<'STUB'
#!/usr/bin/env bash
case "$2" in
  hw.memsize) echo 17179869184 ;;
  kern.memorystatus_level) echo 70 ;;
  *) exit 1 ;;
esac
STUB
for g in film size; do
  cat > "$SB/$g-gate.py" <<STUB
import sys, os
open("$SB/$g-args", "w").write(" ".join(sys.argv[1:]))
sys.exit(1 if os.path.exists("$SB/$g-fail") else 0)
STUB
done
chmod +x "$SB/sysctl"
export HEAVY_JOB_VM_PID="" HEAVY_JOB_DETACH=0

hj() {
  rm -f "$SB/film-args" "$SB/size-args" "$SB/ran"
  OUT="$(env HEAVY_JOB_STORE="$SB/store" HEAVY_JOB_POLL=1 MEMGATE_PROC_MEMINFO="$SB/no-such-meminfo" MEMGATE_SYSCTL="$SB/sysctl" \
      HEAVY_JOB_DF_KB=99999999 HEAVY_JOB_FILM_GATE_BIN="$SB/film-gate.py" HEAVY_JOB_SIZE_GATE_BIN="$SB/size-gate.py" \
      bash "$HJ" "$@" 2>&1)"; RC=$?
}
RAN="touch $SB/ran"
EXPORT="cd /x && node render.mjs /w/film export /w/out/v10-raw.mp4; $RAN"

# --- detection: which commands are film exports ---
hj --name t -- bash -c "$EXPORT"
check "render.mjs export without gates is refused (77), the job does not run" "$(ok "$RC" = 77 -a ! -e "$SB/ran")" "rc=$RC $OUT"
check "the refusal names both flags" "$(ok -n "$(printf '%s' "$OUT" | grep -- '--film-gate' | grep -- '--size-gate')")" "$OUT"
check "the refusal is logged" "$(ok -n "$(grep 'REFUSED film export without gates' "$SB/store/heavy-job.log")")"

hj --name t -- bash -c "/Users/x/tools/hyperframes/hf render proj -o out.mp4; $RAN"
check "hyperframes hf render is a film export" "$(ok "$RC" = 77)" "rc=$RC"
hj --name t -- bash -c "ffmpeg -i a.mp4 -c copy /Users/klodel/marveen/shared/marketing/x/final/v.mp4; $RAN"
check "an mp4 written under shared/marketing/ is a film export" "$(ok "$RC" = 77)" "rc=$RC"

hj --name t -- bash -c "cd /x && node render.mjs /w/film frames 0.5,1.5; $RAN"
runs "render.mjs frames (the size gate's own frames) is not an export" "$(ok "$RC" = 0 -a -e "$SB/ran")" "rc=$RC $OUT"
hj --name t -- bash -c "ffmpeg -i a.mp4 -c copy /w/out/v-tg.mp4; $RAN"
runs "ffmpeg into a work dir is not an export" "$(ok "$RC" = 0 -a -e "$SB/ran")" "rc=$RC $OUT"
hj --name t -- bash -c "/Users/x/tools/hyperframes/hf check proj; $RAN"
runs "hf check is not an export" "$(ok "$RC" = 0 -a -e "$SB/ran")" "rc=$RC $OUT"

# --- gates ---
hj --name t --film-gate "$SB/stills|t_*.png" --size-gate "$SB/frames --end 24 --skip 7.5" -- bash -c "$EXPORT"
runs "both gates pass: the export runs" "$(ok "$RC" = 0 -a -e "$SB/ran")" "rc=$RC $OUT"
runs "the film gate got <stills> <glob>" "$(ok "$(cat "$SB/film-args" 2>/dev/null)" = "$SB/stills t_*.png")" "$(cat "$SB/film-args" 2>/dev/null)"
runs "the size gate got <frames> and its args" "$(ok "$(cat "$SB/size-args" 2>/dev/null)" = "$SB/frames --end 24 --skip 7.5")" "$(cat "$SB/size-args" 2>/dev/null)"

touch "$SB/film-fail"
hj --name t --film-gate "$SB/stills|t_*.png" --size-gate "$SB/frames --end 24" -- bash -c "$EXPORT"
check "a failing film gate refuses (77), no export" "$(ok "$RC" = 77 -a ! -e "$SB/ran")" "rc=$RC $OUT"
rm -f "$SB/film-fail"; touch "$SB/size-fail"
hj --name t --film-gate "$SB/stills|t_*.png" --size-gate "$SB/frames --end 24" -- bash -c "$EXPORT"
check "a failing size gate refuses (77), no export" "$(ok "$RC" = 77 -a ! -e "$SB/ran")" "rc=$RC $OUT"
rm -f "$SB/size-fail"

hj --name t --film-gate "$SB/stills" --size-gate "$SB/frames" -- bash -c "$EXPORT"
check "--film-gate without |<glob> is refused" "$(ok "$RC" = 77 -a ! -e "$SB/ran")" "rc=$RC $OUT"
hj --name t --film-gate "$SB/stills|*.png" --size-gate "$SB/no-such-frames" -- bash -c "$EXPORT"
check "a missing frames dir is refused" "$(ok "$RC" = 77 -a ! -e "$SB/ran")" "rc=$RC $OUT"
hj --name t --film-gate "$SB/stills|*.png" -- bash -c "$EXPORT"
check "only one of the two flags is refused" "$(ok "$RC" = 77 -a ! -e "$SB/ran")" "rc=$RC $OUT"

# --- waivers ---
hj --name t --film-gate "nincs: Bubek demó, nem marketing-film" --size-gate "nincs: 16:9 demó, nem 9:16 reel" -- bash -c "$EXPORT"
runs "\"nincs: <reason>\" waives both, the export runs" "$(ok "$RC" = 0 -a -e "$SB/ran")" "rc=$RC $OUT"
runs "the waiver reason is logged" "$(ok -n "$(grep 'waived: Bubek demó' "$SB/store/heavy-job.log")")"
hj --name t --film-gate "nincs: x" --size-gate "nincs: 16:9 demó, nem 9:16 reel" -- bash -c "$EXPORT"
check "\"nincs:\" with a too short reason is refused" "$(ok "$RC" = 77 -a ! -e "$SB/ran")" "rc=$RC $OUT"

# --- detached mode: the gates run once, in the caller (the supervisor re-runs heavy-job.sh with HEAVY_JOB_RUN) ---
rm -f "$SB/film-args"; before="$(grep -c 'film export gates passed' "$SB/store/heavy-job.log")"
OUT="$(env HEAVY_JOB_DETACH=1 HEAVY_JOB_STORE="$SB/store" HEAVY_JOB_POLL=1 MEMGATE_PROC_MEMINFO="$SB/no-such-meminfo" \
    MEMGATE_SYSCTL="$SB/sysctl" HEAVY_JOB_DF_KB=99999999 HEAVY_JOB_FILM_GATE_BIN="$SB/film-gate.py" \
    HEAVY_JOB_SIZE_GATE_BIN="$SB/size-gate.py" bash "$HJ" --name td --film-gate "$SB/stills|*.png" \
    --size-gate "$SB/frames" -- bash -c "$EXPORT" 2>&1)"; RC=$?
runs "detached: gates pass and the export runs" "$(ok "$RC" = 0 -a -e "$SB/ran")" "rc=$RC $OUT"
after="$(grep -c 'film export gates passed' "$SB/store/heavy-job.log")"
runs "detached: the gates ran once (caller only, not again in the supervisor)" "$(ok "$((after - before))" = 1)" "before=$before after=$after"

echo "$((DONE-FAILS))/$DONE pass"
[ "$FAILS" -eq 0 ]
