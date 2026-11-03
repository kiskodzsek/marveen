#!/bin/bash
# install-mem-relief.sh
#
# Installs the launchd job that runs scripts/mem-relief.sh on macOS: the hard
# step that stops the Colima VM and the next dev servers when host-monitor says
# critical for memory/swap/disk, or the swap is above 11 GB (Klodel 25411,
# card 1c58f629; the 2026-11-03 16:56:57 kernel panic,
# shared/cleanup-1103/panic-1103-elemzes.md).
#
# Period:
#   StartInterval 60     -> one pass a minute. On 2026-11-03 host-monitor was
#                           CRITICAL from 16:43:24 and the panic came at
#                           16:56:57: a pass a minute acts ~12 minutes before
#                           that. A pass with no trigger reads one state file
#                           and sysctl, nothing else.
#   RunAtLoad true       -> a pass at every login, so a VM that comes back with
#                           the session is looked at at once.
#
# Output: one line per action in store/mem-relief.log. stdout goes to
# /dev/null; stderr is kept in store/mem-relief.err.log.
#
# This installer only writes the plist. It does not load it: loading is
# `launchctl bootstrap gui/<uid> <plist>` after the plist's sha256 has been
# checked against the self-pace gate pin (Viktor 9759 L1: no legacy
# load/unload path).
#
# Usage:
#   scripts/install-mem-relief.sh
# Test hook: MEM_RELIEF_LAUNCH_AGENTS (default ~/Library/LaunchAgents).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LABEL="com.marveen.mem-relief"
LA="${MEM_RELIEF_LAUNCH_AGENTS:-$HOME/Library/LaunchAgents}"
PLIST="$LA/$LABEL.plist"
RELIEF="$PROJECT_DIR/scripts/mem-relief.sh"

if [ "$#" -ne 0 ]; then
  echo "usage: install-mem-relief.sh (no options; load with launchctl bootstrap)" >&2
  exit 64
fi

if [ ! -f "$RELIEF" ]; then
  echo "ERROR: $RELIEF not found." >&2
  exit 1
fi

if [ "$(uname -s)" != "Darwin" ]; then
  echo "ERROR: this installer is macOS-only (it writes a launchd plist; $(uname -s) has no launchd)." >&2
  exit 1
fi

mkdir -p "$LA"
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
    <string>$RELIEF</string>
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
  <string>$PROJECT_DIR/store/mem-relief.err.log</string>
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
