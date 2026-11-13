#!/bin/bash
# host-heartbeat-ping.sh -- one "alive" ping from this machine to an external dead-man's switch.
#
# Why (card 8fbd8b7b, Viktor 20230 H2 and 40253): on 2026-11-13 the box went down at 09:15 and sat on the
# FileVault unlock screen until 10:07. Nothing on the box could tell anyone, because nothing ran. An outside
# service that expects a ping every minute can: when the pings stop for period + grace (1 + 5 minutes), it
# mails the owner. The check lives at healthchecks.io (free plan); the owner holds the account.
#
# The ping URL carries the check's UUID, and the UUID is the only credential: whoever knows it can send
# "alive" and silence the alarm ("You should treat check UUIDs and project Ping keys as secrets",
# https://healthchecks.io/docs/). So:
#   - the URL lives in a curl config file, never in argv (ps), the plist, the repo or a log;
#     ~/Library/Application Support/marveen/host-heartbeat.curlrc, folder 0700, file 0600, owned by us;
#   - the file must hold exactly one line, url = "https://hc-ping.com/<uuid>", and nothing else, so it
#     cannot smuggle other curl options (proxy, output, ...);
#   - if the file or the folder is missing, a symlink, someone else's, or has another mode: no ping and no
#     fallback URL. A missing ping is the safe failure: the owner gets mailed;
#   - success writes nothing. A failure writes one masked line (no URL, no UUID), at most once per
#     LOG_EVERY_S, to $MARVEEN_STORE/host-heartbeat.log.
#
# Run by launchd every 60 s (scripts/install-host-heartbeat.sh). No arguments.

set -u

CONF_DIR="$HOME/Library/Application Support/marveen"
CONF="$CONF_DIR/host-heartbeat.curlrc"
STORE="${MARVEEN_STORE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/store}"
LOG="$STORE/host-heartbeat.log"
STAMP="$STORE/.host-heartbeat-logged"
LOG_EVERY_S=900
URL_LINE_RE='^url = "https://hc-ping\.com/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"$'

# "<uid> <octal mode>" of a path, on macOS (BSD stat) and Linux (GNU stat, the CI).
# GNU stat -f means file-system status, so the platform decides, not a fallback.
owner_mode() {
  if [ "$(uname -s)" = Darwin ]; then stat -f '%u %Lp' "$1" 2>/dev/null; else stat -c '%u %a' "$1" 2>/dev/null; fi
}

# Never let a UUID or the ping path through, printable characters only, short.
mask() {
  sed -E -e 's#[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}#<uuid>#g' \
         -e 's#hc-ping\.com/[^ "]*#hc-ping.com/<masked>#g' \
    | tr -cd '[:print:]\n' | tr '\n' ' ' | cut -c1-200
}

# One masked line, at most once per LOG_EVERY_S (a dead network would otherwise write 1440 lines a day).
log_failure() {
  local now last=0
  now=$(date +%s)
  [ -f "$STAMP" ] && last=$(cat "$STAMP" 2>/dev/null || echo 0)
  case "$last" in ''|*[!0-9]*) last=0 ;; esac
  [ $((now - last)) -lt "$LOG_EVERY_S" ] && return 0
  mkdir -p "$STORE" 2>/dev/null || return 0
  printf '%s host-heartbeat: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$(printf '%s' "$1" | mask)" >> "$LOG"
  printf '%s' "$now" > "$STAMP"
}

me=$(id -u)

if [ ! -d "$CONF_DIR" ] || [ -L "$CONF_DIR" ] || [ "$(owner_mode "$CONF_DIR")" != "$me 700" ]; then
  log_failure "config folder missing or not ours with mode 700; no ping"
  exit 1
fi
if [ ! -f "$CONF" ] || [ -L "$CONF" ] || [ "$(owner_mode "$CONF")" != "$me 600" ]; then
  log_failure "config file missing or not ours with mode 600; no ping"
  exit 1
fi
# Exactly one line WITH its newline: wc -l counts newlines, grep -c '' counts lines, so a second line without a
# trailing newline (wc -l = 1, curl still reads it) fails the second test (Viktor 40263 LOW).
if [ "$(wc -l < "$CONF" | tr -d ' ')" != "1" ] || [ "$(grep -c '' "$CONF")" != "1" ] || ! grep -Eq "$URL_LINE_RE" "$CONF"; then
  log_failure "config file is not exactly one hc-ping.com check URL line; no ping"
  exit 1
fi

if err=$(curl -fsS -m 10 --retry 2 --proto =https --tlsv1.2 -K "$CONF" -o /dev/null 2>&1); then
  rm -f "$STAMP"
  exit 0
fi
log_failure "ping failed: ${err:-no message}"
exit 1
