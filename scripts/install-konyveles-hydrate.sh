#!/bin/bash
# install-konyveles-hydrate.sh
#
# Installs the launchd job that runs scripts/konyveles-hydrate.sh on macOS: once
# at login and every hour it downloads any cloud-only (dataless) file under the
# OneDrive accounting folder, so the owner and the finance agent can always open
# them locally (Klodel 27133/27138, card 7b30ebe5).
#
# Period:
#   RunAtLoad true        -> a pass at every login
#   StartInterval 3600    -> one pass an hour; a pass with nothing to do is two
#                            `find` walks over ~400 files
#   LowPriorityIO, Nice   -> the download never competes with interactive work
#
# Output: one line per run in store/konyveles-hydrate.log; stdout goes to
# /dev/null, stderr is kept in store/konyveles-hydrate.err.log.
#
# This installer only writes the plist. It does not load it: loading is
# `launchctl bootstrap gui/<uid> <plist>` after the plist's sha256 has been
# checked against the self-pace gate pin.
#
# Usage:
#   scripts/install-konyveles-hydrate.sh [<folder>]
#     <folder> default: ~/Library/CloudStorage/OneDrive-mySHPSolutionsBt/Könyvelés
# Test hook: KONYVELES_LAUNCH_AGENTS (default ~/Library/LaunchAgents).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LABEL="com.marveen.konyveles-hydrate"
LA="${KONYVELES_LAUNCH_AGENTS:-$HOME/Library/LaunchAgents}"
PLIST="$LA/$LABEL.plist"
RUNNER="$PROJECT_DIR/scripts/konyveles-hydrate.sh"
ROOT="${1:-$HOME/Library/CloudStorage/OneDrive-mySHPSolutionsBt/Könyvelés}"
CARD="7b30ebe5"

if [ ! -f "$RUNNER" ]; then
  echo "ERROR: $RUNNER not found." >&2
  exit 1
fi
if [ "$(uname -s)" != "Darwin" ]; then
  echo "ERROR: this installer is macOS-only (launchd plist, File Provider dataless files)." >&2
  exit 1
fi
if [ ! -d "$ROOT" ]; then
  echo "ERROR: folder not found: $ROOT" >&2
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
    <string>$RUNNER</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT_DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>3600</integer>
  <key>LowPriorityIO</key>
  <true/>
  <key>Nice</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>/dev/null</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_DIR/store/konyveles-hydrate.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>HOME</key>
    <string>$HOME</string>
    <key>TZ</key>
    <string>Europe/Budapest</string>
    <key>MARVEEN_STORE</key>
    <string>$PROJECT_DIR/store</string>
    <key>KONYVELES_ROOT</key>
    <string>$ROOT</string>
    <key>KONYVELES_CARD</key>
    <string>$CARD</string>
  </dict>
</dict>
</plist>
PLIST_EOF
plutil -lint "$PLIST" >/dev/null
echo "Wrote launchd unit: $PLIST (sha256 $(shasum -a 256 "$PLIST" | cut -d' ' -f1))"
echo "Then: launchctl bootstrap gui/$(id -u) $PLIST"
