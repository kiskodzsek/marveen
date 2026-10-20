#!/bin/bash
# install-host-restart-watchdog.sh
#
# Installs the launchd twin of scripts/systemd/marveen-host-watchdog.service
# (macOS). Without it scripts/host-restart-watchdog.sh never runs on a Mac:
# the 2026-10-20 07:02 kernel panic took the fleet down until 07:56, and
# Patrik got no word of why (Patrik TG 3775, card 1c58f629).
#
# Period:
#   RunAtLoad true        -> runs at every login, i.e. right after a reboot
#                            (a LaunchAgent cannot run before the login, and
#                            with FileVault on nothing can)
#   StartInterval 300     -> retries every 5 minutes; the script stamps its
#                            btime baseline only after a confirmed send, so a
#                            failed notice is retried, not lost
#
# Usage:
#   scripts/install-host-restart-watchdog.sh            # install, do not start
#   scripts/install-host-restart-watchdog.sh --load     # install and start

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LABEL="com.marveen.host-restart-watchdog"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
WATCHDOG="$PROJECT_DIR/scripts/host-restart-watchdog.sh"

LOAD=0
[ "${1:-}" = "--load" ] && LOAD=1

if [ ! -f "$WATCHDOG" ]; then
  echo "ERROR: $WATCHDOG not found." >&2
  exit 1
fi

# macOS only, said out loud: a plist nothing reads plus a zero exit is worse
# than a failure. On Linux the twin is scripts/systemd/marveen-host-watchdog.service.
if [ "$(uname -s)" != "Darwin" ]; then
  echo "ERROR: this installer is macOS-only (it writes a launchd plist; $(uname -s) has no launchd)." >&2
  echo "       On Linux the watchdog ships as scripts/systemd/marveen-host-watchdog.service (install-linux.sh)." >&2
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
    <string>$WATCHDOG</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT_DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>300</integer>
  <key>StandardOutPath</key>
  <string>$PROJECT_DIR/store/host-restart-watchdog.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_DIR/store/host-restart-watchdog.log</string>
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
  echo "Loaded $LABEL (at login + every 300s). The first run only records the boot time; the next reboot sends the notice."
else
  echo "Installed but NOT loaded. To start: launchctl load $PLIST"
fi
