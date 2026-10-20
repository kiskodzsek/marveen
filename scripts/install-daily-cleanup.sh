#!/bin/bash
# install-daily-cleanup.sh
#
# Installs the launchd job that runs scripts/daily-cleanup.sh on macOS: the
# regenerable caches (brew, npm, pip, go, idle agent scratch) cleared once a
# night, and earlier when free disk drops below 10 GiB (card 1c58f629).
#
# Period:
#   StartInterval 3600   -> one tick an hour; daily-cleanup.sh tick decides
#                           whether a run is due (nightly 03-05, catch-up after
#                           30 h, or the disk gate), so a missed or extra tick
#                           does no harm
#   RunAtLoad true       -> a tick at every login, so a low disk after a
#                           reboot does not wait an hour
#
# Output: the script logs one line per step to store/daily-cleanup.log and
# keeps the tools' output of the last run in store/daily-cleanup.last-run.txt.
# stdout goes to /dev/null; stderr is kept in store/daily-cleanup.err.log.
#
# This installer only writes the plist. It does not load it: loading is
# `launchctl bootstrap gui/<uid> <plist>` after the plist's sha256 has been
# checked against the self-pace gate pin (Viktor 9759 L1 on the host-monitor
# installer: no legacy load/unload path).
#
# Usage:
#   scripts/install-daily-cleanup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LABEL="com.marveen.daily-cleanup"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
CLEANUP="$PROJECT_DIR/scripts/daily-cleanup.sh"

if [ "$#" -ne 0 ]; then
  echo "usage: install-daily-cleanup.sh (no options; load with launchctl bootstrap)" >&2
  exit 64
fi

if [ ! -f "$CLEANUP" ]; then
  echo "ERROR: $CLEANUP not found." >&2
  exit 1
fi

# macOS only, said out loud: a plist nothing reads plus a zero exit is worse
# than a failure. There is no systemd twin yet.
if [ "$(uname -s)" != "Darwin" ]; then
  echo "ERROR: this installer is macOS-only (it writes a launchd plist; $(uname -s) has no launchd)." >&2
  echo "       On Linux daily-cleanup.sh has no unit yet; run 'daily-cleanup.sh tick' from a systemd timer every hour." >&2
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
    <string>$CLEANUP</string>
    <string>tick</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT_DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>3600</integer>
  <key>StandardOutPath</key>
  <string>/dev/null</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_DIR/store/daily-cleanup.err.log</string>
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
echo "Installed but NOT loaded. Check: shasum -a 256 $PLIST"
echo "Then: launchctl bootstrap gui/$(id -u) $PLIST"
