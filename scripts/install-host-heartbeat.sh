#!/bin/bash
# install-host-heartbeat.sh -- the launchd job for scripts/host-heartbeat-ping.sh, and the one safe way to
# put the ping URL in place (card 8fbd8b7b, Viktor 40253).
#
#   scripts/install-host-heartbeat.sh --set-url-from-clipboard   # the owner copied the check's ping URL
#   scripts/install-host-heartbeat.sh                            # write the plist, do not start
#   scripts/install-host-heartbeat.sh --load                     # write the plist and start
#
# --set-url-from-clipboard reads the clipboard (pbpaste), accepts exactly https://hc-ping.com/<check uuid>
# (a check URL, not a project ping-key URL), writes ~/Library/Application Support/marveen/host-heartbeat.curlrc
# (folder 0700, file 0600, umask 077, atomic rename), clears the clipboard, and prints the URL masked. Bad input
# writes nothing. The URL never goes through a chat, an argument or a log.
#
# The plist carries no URL: the job runs the ping script every 60 s and at login. A LaunchAgent cannot run
# before the login, and with FileVault on nothing can: exactly then the pings stop and the owner gets mailed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LABEL="com.marveen.host-heartbeat"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PING="$PROJECT_DIR/scripts/host-heartbeat-ping.sh"
CONF_DIR="$HOME/Library/Application Support/marveen"
CONF="$CONF_DIR/host-heartbeat.curlrc"
URL_RE='^https://hc-ping\.com/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'

set_url_from_clipboard() {
  local url tmp
  url=$(pbpaste 2>/dev/null | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | tr 'A-F' 'a-f')
  if [ "$(printf '%s\n' "$url" | wc -l | tr -d ' ')" != "1" ] || ! printf '%s\n' "$url" | grep -Eq "$URL_RE"; then
    echo "ERROR: the clipboard does not hold exactly one https://hc-ping.com/<check uuid> URL. Nothing written." >&2
    echo "       Copy the check's ping URL (Details page of the check), then run this again." >&2
    exit 2
  fi
  umask 077
  mkdir -p "$CONF_DIR"
  if [ -L "$CONF_DIR" ]; then
    echo "ERROR: $CONF_DIR is a symlink. Nothing written." >&2
    exit 2
  fi
  chmod 700 "$CONF_DIR"
  tmp=$(mktemp "$CONF_DIR/.host-heartbeat.XXXXXX")
  printf 'url = "%s"\n' "$url" > "$tmp"
  chmod 600 "$tmp"
  mv -f "$tmp" "$CONF"
  printf '' | pbcopy 2>/dev/null || true
  echo "Wrote $CONF (0600): https://hc-ping.com/********-****-****-****-********${url: -4}"
  echo "The clipboard was cleared."
}

case "${1:-}" in
  --set-url-from-clipboard) set_url_from_clipboard; exit 0 ;;
  ''|--load) ;;
  *) echo "usage: $0 [--load | --set-url-from-clipboard]" >&2; exit 64 ;;
esac

if [ "$(uname -s)" != "Darwin" ]; then
  echo "ERROR: this installer is macOS-only (it writes a launchd plist)." >&2
  exit 1
fi
if [ ! -f "$PING" ]; then
  echo "ERROR: $PING not found." >&2
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
    <string>$PING</string>
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
  <string>$PROJECT_DIR/store/host-heartbeat.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/bin:/bin</string>
    <key>HOME</key>
    <string>$HOME</string>
    <key>TZ</key>
    <string>Europe/Budapest</string>
    <key>MARVEEN_STORE</key>
    <string>$PROJECT_DIR/store</string>
  </dict>
</dict>
</plist>
PLIST_EOF
echo "Wrote launchd unit: $PLIST"
[ -f "$CONF" ] || echo "NOTE: $CONF does not exist yet; run with --set-url-from-clipboard first, or the job pings nothing."

if [ "${1:-}" = "--load" ]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST"
  echo "Loaded $LABEL (at login + every 60 s)."
else
  echo "Installed but NOT loaded. To start: launchctl load $PLIST"
fi
