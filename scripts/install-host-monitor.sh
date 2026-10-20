#!/bin/bash
# install-host-monitor.sh
#
# Installs the launchd job that runs scripts/host-monitor.sh on macOS. Without
# it store/.host-state is never written, so heavy-job.sh has no host verdict to
# wait on and a CRITICAL band (free memory, swap, disk, thermal) pages nobody:
# the 2026-10-20 07:02 kernel panic came with free memory at 871 pages and
# nobody saw it coming (card 1c58f629).
#
# Period:
#   RunAtLoad true        -> a first measurement at every login
#   StartInterval 60      -> one pass a minute; heavy-job.sh ignores a state
#                            file older than 300 s (HEAVY_JOB_STATE_MAX_AGE),
#                            so missed runs degrade to "no verdict", never to
#                            a stale one
#
# Output: host-monitor.sh prints one status line per run, and logs only band
# changes to store/host-monitor.log itself. stdout goes to /dev/null so a
# 60 s job does not grow a log by 1440 lines a day; stderr is kept in
# store/host-monitor.err.log.
#
# Usage:
#   scripts/install-host-monitor.sh            # install, do not start
#   scripts/install-host-monitor.sh --load     # install and start

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LABEL="com.marveen.host-monitor"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
MONITOR="$PROJECT_DIR/scripts/host-monitor.sh"

LOAD=0
[ "${1:-}" = "--load" ] && LOAD=1

if [ ! -f "$MONITOR" ]; then
  echo "ERROR: $MONITOR not found." >&2
  exit 1
fi

# macOS only, said out loud: a plist nothing reads plus a zero exit is worse
# than a failure. There is no systemd twin yet; on Linux the monitor is not
# scheduled by any installer.
if [ "$(uname -s)" != "Darwin" ]; then
  echo "ERROR: this installer is macOS-only (it writes a launchd plist; $(uname -s) has no launchd)." >&2
  echo "       On Linux host-monitor.sh has no unit yet; run it from a systemd timer every 60 s." >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$MONITOR</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT_DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>60</integer>
  <key>StandardOutPath</key>
  <string>/dev/null</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_DIR/store/host-monitor.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>HOME</key>
    <string>$HOME</string>
    <key>USER</key>
    <string>$(id -un)</string>
    <key>TZ</key>
    <string>Europe/Budapest</string>
    <key>MARVEEN_STORE</key>
    <string>$PROJECT_DIR/store</string>
  </dict>
</dict>
</plist>
PLIST_EOF
echo "Wrote launchd unit: $PLIST"

if [ "$LOAD" = "1" ]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST"
  echo "Loaded $LABEL (at login + every 60s). Check: cat $PROJECT_DIR/store/.host-state"
else
  echo "Installed but NOT loaded. To start: launchctl load $PLIST"
fi
