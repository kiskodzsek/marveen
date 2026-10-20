#!/usr/bin/env bash
# host-restart-watchdog.sh on macOS (Patrik TG 3775, card 1c58f629).
#
# The 2026-10-20 07:02 kernel panic left the fleet silent until 07:56, and the
# watchdog that would have told Patrik why only knew /proc/stat: on a Mac it
# found no btime and did nothing. These checks pin the macOS path (kern.boottime,
# the panic report, the Hungarian notice, the retry-on-failed-send baseline),
# the unchanged Linux path, and the launchd installer.
#
# Platform, boot time and panic directory are stubbed (HOSTWD_UNAME,
# HOSTWD_BOOTTIME, HOSTWD_PANIC_DIR), and curl is a stub on PATH, so nothing
# here reads the real host or reaches the Bot API.
#
# Run:  bash scripts/__tests__/host-restart-watchdog-macos.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
WD="$ROOT/scripts/host-restart-watchdog.sh"
FAILS=0
N=0

check() { N=$((N+1)); if [ "$2" = "0" ]; then echo "PASS  $1"; else echo "FAIL  $1${3:+  -- $3}"; FAILS=$((FAILS+1)); fi; }

SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/hostwd.XXXXXX")"
trap 'rm -rf "$SANDBOX"' EXIT

STORE="$SANDBOX/store"; PANICS="$SANDBOX/panics"; BIN="$SANDBOX/bin"; SENT="$SANDBOX/sent"
mkdir -p "$STORE" "$PANICS" "$BIN"
printf 'TELEGRAM_BOT_TOKEN=test-token\n' > "$SANDBOX/tg.env"
# The curl stub records the urlencoded text and answers ok:true, or ok:false
# when $SANDBOX/fail exists.
cat > "$BIN/curl" <<STUB
#!/bin/bash
for a in "\$@"; do case "\$a" in text=*) printf '%s\n---\n' "\${a#text=}" >> "$SENT" ;; esac; done
if [ -f "$SANDBOX/fail" ]; then echo '{"ok":false,"description":"stub"}'; else echo '{"ok":true}'; fi
STUB
chmod +x "$BIN/curl"

BOOT1=1792000000   # an earlier boot
BOOT2=1792475438   # 2026-10-20 07:50:38 +0200
PANIC_AT=1792472540  # 2026-10-20 07:02:20 +0200

run_wd() {  # run_wd <btime> [extra env...]
  local bt="$1"; shift
  env -i PATH="$BIN:/usr/bin:/bin:/opt/homebrew/bin" HOME="$SANDBOX" TZ=Europe/Budapest \
    MARVEEN_STORE="$STORE" TELEGRAM_ENV="$SANDBOX/tg.env" MARVEEN_ALERT_CHAT_ID=123 \
    HOSTWD_UNAME=Darwin HOSTWD_PROC_STAT="$SANDBOX/no-proc-stat" \
    HOSTWD_BOOTTIME="{ sec = $bt, usec = 282920 } Tue Oct 20 07:50:38 2026" \
    HOSTWD_PANIC_DIR="$PANICS" "$@" bash "$WD"
}
sends() { [ -f "$SENT" ] && grep -c '^---$' "$SENT" || echo 0; }

# A minimal panic report in the real two-document shape (header line + body).
write_panic() {  # write_panic <file> <mtime-epoch>
  printf '%s\n' '{"bug_type":"210","timestamp":"2026-10-20 07:55:50.00 +0200"}' > "$1"
  cat >> "$1" <<'JSON'
{
  "panicString" : "panic(cpu 6 caller 0xfffffe0041865f38): watchdog timeout: no checkins from watchdogd in 93 seconds (64567 total checkins since monitoring last enabled)\nDebugger message: panic\n",
  "panicTimeInSecsAndUsecs" : "wall 1792472540 s 152434 us"
}
System Profile:
Memory Module: LPDDR5
JSON
  touch -t "$(TZ=Europe/Budapest date -r "$2" '+%Y%m%d%H%M.%S')" "$1"
}

# (1) first run: baseline only, no notice
out="$(run_wd $BOOT1)"
check "first run records the boot time and sends nothing" "$([ "$(cat "$STORE/.last-btime" 2>/dev/null)" = "$BOOT1" ] && [ "$(sends)" = 0 ] && echo 0 || echo 1)" "$out"

# (2) same boot: nothing
out="$(run_wd $BOOT1)"
check "an unchanged boot time sends nothing" "$([ "$(sends)" = 0 ] && echo 0 || echo 1)" "$out"

# (3) a reboot after a panic: one notice with the boot, the downtime and the panic
echo x > "$STORE/channels.log"
touch -t "$(TZ=Europe/Budapest date -r 1792472446 '+%Y%m%d%H%M.%S')" "$STORE/channels.log"   # 07:00:46, before the boot
write_panic "$PANICS/panic-full-2026-10-20-075550.0002.panic" $((BOOT2 + 312))
out="$(run_wd $BOOT2)"
msg="$(cat "$SENT" 2>/dev/null)"
check "a new boot time sends exactly one notice" "$([ "$(sends)" = 1 ] && echo 0 || echo 1)" "$out"
check "the notice names the boot time (local)" "$(printf '%s' "$msg" | grep -q 'A gép újraindult, boot: 07:50\.' && echo 0 || echo 1)" "$msg"
check "the downtime starts at the last fleet activity" "$(printf '%s' "$msg" | grep -qE '^Kiesés: kb\. [0-9]+ perc \(07:00 - [0-9]{2}:[0-9]{2}\)\.$' && echo 0 || echo 1)" "$msg"
check "the panic time and first line are in the notice, without the cpu/caller prefix" "$(printf '%s' "$msg" | grep -qx 'Ok: kernel panic 07:02: watchdog timeout: no checkins from watchdogd in 93 seconds (64567 total checkins since monitoring last enabled)' && echo 0 || echo 1)" "$msg"
check "the notice says the team is coming back" "$(printf '%s' "$msg" | grep -q 'A csapat visszaáll' && echo 0 || echo 1)" "$msg"
check "the baseline is stamped after the confirmed send" "$([ "$(cat "$STORE/.last-btime")" = "$BOOT2" ] && echo 0 || echo 1)"
check "the bot token is not in the log output" "$(printf '%s' "$out" | grep -q 'test-token' && echo 1 || echo 0)" "$out"

# (4) a failed send leaves the baseline, so the next run retries
rm -f "$SENT"; touch "$SANDBOX/fail"
BOOT3=$((BOOT2 + 3600))
out="$(run_wd $BOOT3)"
check "a rejected send does not stamp the baseline" "$([ "$(cat "$STORE/.last-btime")" = "$BOOT2" ] && echo 0 || echo 1)" "$out"
rm -f "$SANDBOX/fail"
out="$(run_wd $BOOT3)"
check "the next run retries and stamps" "$([ "$(cat "$STORE/.last-btime")" = "$BOOT3" ] && [ "$(sends)" = 2 ] && echo 0 || echo 1)" "$out"

# (5) a panic report older than this boot belongs to an earlier crash: no Ok line
rm -f "$SENT"
BOOT4=$((BOOT3 + 86400))
out="$(run_wd $BOOT4)"
msg="$(cat "$SENT" 2>/dev/null)"
check "an older panic report is not blamed for this reboot" "$([ "$(sends)" = 1 ] && ! printf '%s' "$msg" | grep -q '^Ok:' && echo 0 || echo 1)" "$msg"

# (6) an unreadable panic report drops the line, never the notice
rm -f "$SENT"
BOOT5=$((BOOT4 + 86400))
printf 'not a panic report\n{broken' > "$PANICS/panic-full-x.panic"
touch -t "$(TZ=Europe/Budapest date -r $((BOOT5 + 60)) '+%Y%m%d%H%M.%S')" "$PANICS/panic-full-x.panic"
out="$(run_wd $BOOT5)"
msg="$(cat "$SENT" 2>/dev/null)"
check "a broken panic report still sends the notice, without an Ok line" "$([ "$(sends)" = 1 ] && ! printf '%s' "$msg" | grep -q '^Ok:' && echo 0 || echo 1)" "$msg"

# (7) a kern.boottime it cannot read: nothing to do, nothing stamped
rm -f "$SENT"
before="$(cat "$STORE/.last-btime")"
out="$(env -i PATH="$BIN:/usr/bin:/bin" HOME="$SANDBOX" MARVEEN_STORE="$STORE" TELEGRAM_ENV="$SANDBOX/tg.env" MARVEEN_ALERT_CHAT_ID=123 \
  HOSTWD_UNAME=Darwin HOSTWD_PROC_STAT="$SANDBOX/no-proc-stat" HOSTWD_BOOTTIME="garbage" bash "$WD")"
check "an unreadable boot time does nothing" "$([ "$(sends)" = 0 ] && [ "$(cat "$STORE/.last-btime")" = "$before" ] && printf '%s' "$out" | grep -q 'nothing to do' && echo 0 || echo 1)" "$out"

# (8) Linux is unchanged: /proc/stat btime, the English host notice
rm -f "$SENT"; LSTORE="$SANDBOX/lstore"; mkdir -p "$LSTORE"
printf 'cpu 1 2 3\nbtime 1700000000\n' > "$SANDBOX/proc1"; printf 'cpu 1 2 3\nbtime 1700009999\n' > "$SANDBOX/proc2"
lrun() { env -i PATH="$BIN:/usr/bin:/bin" HOME="$SANDBOX" MARVEEN_STORE="$LSTORE" TELEGRAM_ENV="$SANDBOX/tg.env" MARVEEN_ALERT_CHAT_ID=123 \
  HOSTWD_UNAME=Linux HOSTWD_PROC_STAT="$1" HOSTWD_PANIC_DIR="$PANICS" bash "$WD"; }
lrun "$SANDBOX/proc1" >/dev/null; out="$(lrun "$SANDBOX/proc2")"
msg="$(cat "$SENT" 2>/dev/null)"
check "Linux: the btime change still sends the host notice" "$([ "$(sends)" = 1 ] && printf '%s' "$msg" | grep -q '^Marveen host restarted\.' && ! printf '%s' "$msg" | grep -q '^Ok:' && echo 0 || echo 1)" "$msg"

# (9) panic-summary.py on its own: garbage in, nothing out, exit 0
o="$(python3 -I "$ROOT/scripts/lib/panic-summary.py" "$PANICS/panic-full-x.panic")"; rc=$?
check "panic-summary.py prints nothing and exits 0 on a broken file" "$([ -z "$o" ] && [ "$rc" = 0 ] && echo 0 || echo 1)" "rc=$rc out=$o"
o="$(python3 -I "$ROOT/scripts/lib/panic-summary.py" "$SANDBOX/missing.panic")"; rc=$?
check "panic-summary.py prints nothing and exits 0 on a missing file" "$([ -z "$o" ] && [ "$rc" = 0 ] && echo 0 || echo 1)" "rc=$rc out=$o"

# (10) the launchd installer: a valid plist, at login + every 300 s, not loaded
FAKEHOME="$SANDBOX/home"; mkdir -p "$FAKEHOME" "$SANDBOX/ubin"
printf '#!/bin/bash\necho Darwin\n' > "$SANDBOX/ubin/uname"; chmod +x "$SANDBOX/ubin/uname"
printf '#!/bin/bash\necho "launchctl called" >> "%s/launchctl.calls"\n' "$SANDBOX" > "$SANDBOX/ubin/launchctl"; chmod +x "$SANDBOX/ubin/launchctl"
P="$FAKEHOME/Library/LaunchAgents/com.marveen.host-restart-watchdog.plist"
out="$(PATH="$SANDBOX/ubin:$PATH" HOME="$FAKEHOME" bash "$ROOT/scripts/install-host-restart-watchdog.sh" 2>&1)"
check "the installer writes the plist and does not load it" "$([ -f "$P" ] && [ ! -f "$SANDBOX/launchctl.calls" ] && echo 0 || echo 1)" "$out"
if command -v plutil >/dev/null 2>&1; then
  check "the plist is valid" "$(plutil -lint "$P" >/dev/null 2>&1 && echo 0 || echo 1)" "$(plutil -lint "$P" 2>&1)"
fi
check "the plist runs this watchdog at load and every 300 s, with the install's store" "$(grep -q "<string>$ROOT/scripts/host-restart-watchdog.sh</string>" "$P" && grep -A1 RunAtLoad "$P" | grep -q '<true/>' && grep -A1 StartInterval "$P" | grep -q '<integer>300</integer>' && grep -A1 MARVEEN_STORE "$P" | grep -q "<string>$ROOT/store</string>" && echo 0 || echo 1)" "$(cat "$P" 2>/dev/null)"
out="$(PATH="$SANDBOX/ubin:$PATH" HOME="$FAKEHOME" bash -c 'uname() { echo Linux; }; export -f uname; bash "$1"' _ "$ROOT/scripts/install-host-restart-watchdog.sh" 2>&1)"; rc=$?
check "the installer refuses on Linux" "$([ "$rc" != 0 ] && echo 0 || echo 1)" "$out"

echo
echo "$((N - FAILS))/$N passed"
[ "$FAILS" = 0 ]
