#!/usr/bin/env bash
# HOSTMON1020 -- host-monitor.sh bands, state file, alert dedupe, and the
# heavy-job.sh link to its state, and the macOS launchd installer (card 1c58f629).
#
# Everything runs in a staged copy: curl and agent-msg.sh are stubs that only
# log their arguments, every metric comes from a HOSTMON_* / MEMGATE_* hook, so
# nothing is read from or sent about the real host.
#
# Run:  bash scripts/__tests__/host-monitor.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
for f in scripts/host-monitor.sh scripts/heavy-job.sh scripts/lib/mem-read.sh scripts/lib/send-telegram.sh; do
  [ -f "$ROOT/$f" ] || { echo "FATAL: missing $f" >&2; exit 2; }
done

FAILS=0; DONE=0
check() { DONE=$((DONE+1)); if [ "$2" = "0" ]; then echo "PASS  $1"; else echo "FAIL  $1${3:+  -- $3}"; FAILS=$((FAILS+1)); fi; }
ok() { [ "$@" ] && echo 0 || echo 1; }

SB="$(mktemp -d "${TMPDIR:-/tmp}/hostmon.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
mkdir -p "$SB/scripts/lib" "$SB/store" "$SB/bin" "$SB/tg"
cp "$ROOT/scripts/host-monitor.sh" "$ROOT/scripts/heavy-job.sh" "$SB/scripts/"
cp "$ROOT/scripts/lib/mem-read.sh" "$ROOT/scripts/lib/send-telegram.sh" "$SB/scripts/lib/"
cat > "$SB/scripts/agent-msg.sh" <<STUB
#!/usr/bin/env bash
echo "\$1 -> \$2: \$(cat)" >> "$SB/agentmsg.log"
STUB
cat > "$SB/bin/curl" <<STUB
#!/usr/bin/env bash
echo "\$*" >> "$SB/curl.log"
[ -f "$SB/curl-fail" ] && { echo "curl: (6) Could not resolve host" >&2; exit 6; }
printf '%s' '{"ok":true,"result":{"message_id":1}}'
STUB
cat > "$SB/sysctl" <<STUB
#!/usr/bin/env bash
case "\$2" in hw.memsize) echo 17179869184 ;; kern.memorystatus_level) cat "$SB/level" ;; *) exit 1 ;; esac
STUB
chmod +x "$SB/bin/curl" "$SB/sysctl" "$SB/scripts/agent-msg.sh"
echo 'TELEGRAM_BOT_TOKEN=000000:FAKE-TEST-TOKEN' > "$SB/tg/.env"
STATE="$SB/store/.host-state"; LOG="$SB/store/host-monitor.log"

NOW=1792480000
# mon <free%> [extra env...] -- one monitor run; everything else healthy by default.
mon() {
  local free="$1"; shift
  echo "$free" > "$SB/level"
  OUT="$(env PATH="$SB/bin:$PATH" MARVEEN_STORE="$SB/store" \
    MEMGATE_PROC_MEMINFO="$SB/no-such" MEMGATE_SYSCTL="$SB/sysctl" \
    HOSTMON_SWAP_PCT="${SWAP:-10}" HOSTMON_DF_KB="${DFKB:-104857600}" HOSTMON_LOAD1="${LOAD:-1.0}" HOSTMON_NCPU=12 \
    HOSTMON_THERM="${THERM:-Note: No thermal warning level has been recorded}" HOSTMON_NOW="$NOW" \
    TELEGRAM_ENV="$SB/tg/.env" MARVEEN_ALERT_CHAT_ID=111 HOSTMON_MAIN_AGENT=mainbot \
    bash "$SB/scripts/host-monitor.sh" "$@" 2>&1)"; RC=$?
}
band_is() { [ "$(cut -d' ' -f1 "$STATE" 2>/dev/null)" = "$1" ]; }

echo "== bands"
mon 60;                 check "healthy -> ok, state written with the run's epoch" "$(ok "$RC" = 0 -a "$(cat "$STATE")" = "ok $NOW ")" "$(cat "$STATE" 2>/dev/null) | $OUT"
mon 20;                 check "free 20% -> warn" "$(band_is warn; echo $?)" "$OUT"
mon 10;                 check "free 10% -> critical" "$(band_is critical; echo $?)" "$OUT"
DFKB=$((5*1048576)) mon 60; check "disk 5 GiB -> warn" "$(band_is warn; echo $?)" "$OUT"
DFKB=$((2*1048576)) mon 60; check "disk 2 GiB -> critical" "$(band_is critical; echo $?)" "$OUT"
SWAP=80 mon 60;         check "swap 80% -> warn" "$(band_is warn; echo $?)" "$OUT"
SWAP=95 mon 20;         check "swap 95% with free 20% -> critical" "$(band_is critical; echo $?)" "$OUT"
SWAP=95 mon 50;         check "swap 95% with free 50% -> only warn" "$(band_is warn; echo $?)" "$OUT"
LOAD=30.5 mon 60;       check "load 30.5 on 12 CPUs -> warn" "$(band_is warn; echo $?)" "$OUT"
THERM="Thermal warning level set to 2." mon 60; check "a recorded thermal warning -> critical" "$(band_is critical; echo $?)" "$OUT"
mon bad;                check "unreadable memory -> warn (never ok by silence)" "$(ok -n "$(grep '^warn .*memory unreadable' "$STATE")")" "$(cat "$STATE")"
echo "#" > "$STATE.before"; cp "$STATE" "$STATE.before"; mon 10 --status
check "--status prints, but writes no state" "$(ok -n "$(echo "$OUT" | grep band=critical)" -a "$(cat "$STATE")" = "$(cat "$STATE.before")")"

echo "== alerts"
rm -f "$STATE" "$SB/store/.host-monitor-alert"* "$SB/curl.log" "$SB/agentmsg.log" "$LOG"
mon 60; mon 10
check "entering critical -> one Telegram send" "$(ok "$(grep -c sendMessage "$SB/curl.log" 2>/dev/null)" = 1)"
check "the alert text names the reason" "$(ok -n "$(grep 'free memory 10%' "$SB/curl.log")")"
check "entering critical -> one message to the main agent" "$(ok "$(grep -c 'host-monitor -> mainbot: \[HOST-MONITOR\]' "$SB/agentmsg.log" 2>/dev/null)" = 1)"
NOW=$((NOW+600)); mon 10
check "still critical inside the cooldown -> no new Telegram, no new message" "$(ok "$(grep -c sendMessage "$SB/curl.log")" = 1 -a "$(wc -l < "$SB/agentmsg.log" | tr -d ' ')" = 1)"
NOW=$((NOW+1800)); mon 10
check "still critical after the cooldown -> reminded once more" "$(ok "$(grep -c sendMessage "$SB/curl.log")" = 2 -a "$(wc -l < "$SB/agentmsg.log" | tr -d ' ')" = 2)"
check "band changes are logged once each (none->ok, ok->critical)" "$(ok "$(grep -c -- '->' "$LOG")" = 2)" "$(cat "$LOG")"

# L3 (Viktor 9013): flapping on the threshold inside the cooldown pages nobody.
rm -f "$STATE" "$SB/store/.host-monitor-alert"* "$SB/curl.log" "$SB/agentmsg.log"
mon 10; for i in 1 2 3 4 5; do NOW=$((NOW+60)); mon 20; NOW=$((NOW+60)); mon 10; done
check "critical <-> warn flapping for 10 min -> still one Telegram, one message" "$(ok "$(grep -c sendMessage "$SB/curl.log")" = 1 -a "$(wc -l < "$SB/agentmsg.log" | tr -d ' ')" = 1)" "tg=$(grep -c sendMessage "$SB/curl.log") msg=$(wc -l < "$SB/agentmsg.log")"
NOW=$((NOW+1800)); mon 20; NOW=$((NOW+60)); mon 10
check "back to critical after the cooldown -> alerted again" "$(ok "$(grep -c sendMessage "$SB/curl.log")" = 2 -a "$(wc -l < "$SB/agentmsg.log" | tr -d ' ')" = 2)"

rm -f "$STATE" "$SB/store/.host-monitor-alert"* "$SB/curl.log" "$SB/agentmsg.log"; touch "$SB/curl-fail"
mon 10; NOW=$((NOW+60)); mon 10
check "a failed Telegram send is retried on the next run (no stamp)" "$(ok "$(grep -c sendMessage "$SB/curl.log")" = 2 -a ! -f "$SB/store/.host-monitor-alert")"
check "...but the main agent is not messaged every run" "$(ok "$(wc -l < "$SB/agentmsg.log" | tr -d ' ')" = 1)"
check "the failure is logged without the token" "$(ok -n "$(grep 'Telegram FAILED' "$LOG")" -a -z "$(grep FAKE-TEST-TOKEN "$LOG")")"
rm -f "$SB/curl-fail"

echo "== heavy-job.sh reads the state"
export HEAVY_JOB_VM_PID=""  # no VM: the host running this test may have a real one
hj() { echo 70 > "$SB/level"; OUT="$(env MEMGATE_PROC_MEMINFO="$SB/no-such" MEMGATE_SYSCTL="$SB/sysctl" HEAVY_JOB_DF_KB=99999999 HEAVY_JOB_POLL=1 \
    bash "$SB/scripts/heavy-job.sh" --wait 0 -- touch "$1" 2>&1)"; RC=$?; }
echo "warn $(date +%s) swap 80%" > "$STATE"; hj "$SB/hj1"
check "fresh warn state -> heavy job not started (75)" "$(ok "$RC" = 75 -a ! -e "$SB/hj1")" "rc=$RC $OUT"
check "...and says why" "$(ok -n "$(echo "$OUT" | grep 'host-monitor says warn (swap 80%)')")" "$OUT"
echo "warn $(( $(date +%s) - 900 )) swap 80%" > "$STATE"; hj "$SB/hj2"
check "stale state (15 min) is ignored -> the job runs" "$(ok "$RC" = 0 -a -e "$SB/hj2")" "rc=$RC $OUT"
echo "ok $(date +%s) " > "$STATE"; hj "$SB/hj3"
check "fresh ok state -> the job runs" "$(ok "$RC" = 0 -a -e "$SB/hj3")" "rc=$RC $OUT"

echo "== install-host-monitor.sh (macOS launchd)"
FAKEHOME="$SB/home"; mkdir -p "$FAKEHOME" "$SB/ubin"
printf '#!/bin/bash\necho Darwin\n' > "$SB/ubin/uname"; chmod +x "$SB/ubin/uname"
printf '#!/bin/bash\necho "launchctl $*" >> "%s/launchctl.calls"\n' "$SB" > "$SB/ubin/launchctl"; chmod +x "$SB/ubin/launchctl"
P="$FAKEHOME/Library/LaunchAgents/com.marveen.host-monitor.plist"
OUT="$(PATH="$SB/ubin:$PATH" HOME="$FAKEHOME" bash "$ROOT/scripts/install-host-monitor.sh" 2>&1)"; RC=$?
check "the installer writes the plist and does not load it" "$(ok "$RC" = 0 -a -f "$P" -a ! -f "$SB/launchctl.calls")" "rc=$RC $OUT"
if command -v plutil >/dev/null 2>&1; then
  check "the plist is valid" "$(plutil -lint "$P" >/dev/null 2>&1 && echo 0 || echo 1)" "$(plutil -lint "$P" 2>&1)"
fi
check "the plist runs this monitor at load and every 60 s, with the install's store" "$(grep -q "<string>$ROOT/scripts/host-monitor.sh</string>" "$P" && grep -A1 RunAtLoad "$P" | grep -q '<true/>' && grep -A1 StartInterval "$P" | grep -q '<integer>60</integer>' && grep -A1 MARVEEN_STORE "$P" | grep -q "<string>$ROOT/store</string>" && echo 0 || echo 1)" "$(cat "$P" 2>/dev/null)"
check "stdout is dropped (one line a minute), stderr kept in the store" "$(grep -A1 StandardOutPath "$P" | grep -q '<string>/dev/null</string>' && grep -A1 StandardErrorPath "$P" | grep -q "<string>$ROOT/store/host-monitor.err.log</string>" && echo 0 || echo 1)" "$(cat "$P" 2>/dev/null)"
OUT="$(PATH="$SB/ubin:$PATH" HOME="$FAKEHOME" bash "$ROOT/scripts/install-host-monitor.sh" --load 2>&1)"; RC=$?
check "--load unloads and loads this plist" "$(ok "$RC" = 0 -a "$(grep -c "$P" "$SB/launchctl.calls" 2>/dev/null)" = 2)" "rc=$RC $(cat "$SB/launchctl.calls" 2>/dev/null)"
OUT="$(PATH="$SB/ubin:$PATH" HOME="$FAKEHOME" bash -c 'uname() { echo Linux; }; export -f uname; bash "$1"' _ "$ROOT/scripts/install-host-monitor.sh" 2>&1)"; RC=$?
check "the installer refuses on Linux" "$(ok "$RC" != 0)" "$OUT"

echo
echo "$((DONE-FAILS))/$DONE passed"
[ "$FAILS" = "0" ] || exit 1
