#!/bin/bash
# install-fleet-quota-snapshot.sh
#
# Installs the launchd job that runs scripts/fleet-quota-snapshot.py on macOS.
# Without it the fleet seat's quota has no history and no threshold alert:
# the statusLine writer never gets rate_limits on the setup-token login, so
# store/.claude-rate-limits.json does not exist and limit-monitor.sh has
# nothing to read (Klodel 14644, 2026-10-23).
#
# Period:
#   RunAtLoad true        -> a first snapshot at every login
#   StartInterval 900     -> one pass every 15 min (96 history lines a day)
#
# Output: the script prints one line per seat per run; stdout goes to
# /dev/null, failures and sent alerts are logged to store/fleet-quota.log by
# the script itself, stderr is kept in store/fleet-quota.err.log.
#
# Alerts go out as an inter-agent message from `fleet-quota`. POST
# /api/messages accepts that sender only when SYSTEM_SENDER_IDS in .env lists
# it, and the dashboard reads .env at start, so: add it, restart the
# dashboard, THEN install. Without it every alert is a 403 that only the log,
# the history row (`unsent`) and --status show (Viktor 14713 M1). This
# installer checks the key and refuses --load without it; after --load it
# sends one real probe (--test-alert) and fails if that does not get through.
#
# Usage:
#   scripts/install-fleet-quota-snapshot.sh            # install, do not start
#   scripts/install-fleet-quota-snapshot.sh --load     # install, start, probe

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LABEL="com.marveen.fleet-quota-snapshot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
MONITOR="$PROJECT_DIR/scripts/fleet-quota-snapshot.py"

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
  echo "       On Linux fleet-quota-snapshot.py has no unit yet; run it from a systemd timer every 15 min." >&2
  exit 1
fi

# Only the SYSTEM_SENDER_IDS line is read, and only a yes/no is printed.
SENDER_OK=0
if [ -f "$PROJECT_DIR/.env" ] && grep -E '^SYSTEM_SENDER_IDS=' "$PROJECT_DIR/.env" | tail -1 | cut -d= -f2- | tr -d '"'"'"' ' | tr ',' '\n' | grep -qx 'fleet-quota'; then
  SENDER_OK=1
fi
if [ "$SENDER_OK" = "1" ]; then
  echo "SYSTEM_SENDER_IDS lists fleet-quota: yes"
else
  echo "SYSTEM_SENDER_IDS lists fleet-quota: NO -- alerts would be rejected (403)." >&2
  if [ "$LOAD" = "1" ]; then
    echo "ERROR: add fleet-quota to SYSTEM_SENDER_IDS in $PROJECT_DIR/.env, restart the dashboard, then run --load again." >&2
    exit 1
  fi
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
    <string>/usr/bin/python3</string>
    <string>$MONITOR</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT_DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>900</integer>
  <key>StandardOutPath</key>
  <string>/dev/null</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_DIR/store/fleet-quota.err.log</string>
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
  echo "Loaded $LABEL (at login + every 15 min). Check: tail -1 $PROJECT_DIR/store/fleet-quota.jsonl"
  # The dashboard may still run with the old .env: only a delivered probe proves the path.
  if ! /usr/bin/python3 "$MONITOR" --test-alert; then
    echo "ERROR: the probe alert did not get through; the job is loaded but cannot alert. Restart the dashboard if .env was just changed, then: /usr/bin/python3 $MONITOR --test-alert" >&2
    exit 1
  fi
else
  echo "Installed but NOT loaded. To start: launchctl load $PLIST"
fi
