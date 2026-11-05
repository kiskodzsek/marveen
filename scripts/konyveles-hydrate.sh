#!/bin/bash
# konyveles-hydrate.sh
#
# Keeps the OneDrive accounting folder ("Könyvelés") downloaded on this Mac.
# On 2026-11-05 every file under it was found dataless (cloud-only); a read of a
# dataless file fails here with "Resource deadlock avoided", so the bank KYC PDFs
# could not be opened while the owner waited at the bank, and the finance agent
# hits the same wall (Klodel 27133/27138). The cause of the eviction is not known
# (the File Provider purged 0 bytes in the log window that still exists).
#
# Read-only towards OneDrive: it never writes, moves, renames or deletes there.
# Each run:
#   1. lists the dataless files with `find -flags +dataless` (stat only, no download);
#   2. splits them into EVICTED (local in an earlier run) and NEW (never seen
#      local, e.g. added from another device: downloaded, not reported);
#   3. downloads them (scripts/konyveles-hydrate.py hydrate: dataless
#      materialization on for its own process, every byte read);
#   4. reports evictions, rate-limited (Viktor 27163 LOW-2): to the finance agent
#      and the card at most once per 6 hours (the count is summed in between);
#      to the lead agent at most once a day, and only when evictions repeat
#      within 7 days.
# A walk that sees no file at all, or a failing `find`, is an ERROR (Viktor 27163
# INFO-1: launchd may not see into ~/Library/CloudStorage), reported once a day.
# Messages carry counts and sanitized top-level folder names only (LOW-1: a folder
# name is text a OneDrive co-editor controls); the log carries no file names
# (INFO-2): errors are counted by errno.
#
# Environment (written into the plist by install-konyveles-hydrate.sh):
#   KONYVELES_ROOT   the folder to keep local (required)
#   KONYVELES_CARD   kanban card id for the comments (optional)
#   KONYVELES_HYDRATE_MAX_S  watchdog over one download pass (default 1800)
#   MARVEEN_STORE    store dir: state in $MARVEEN_STORE/konyveles-hydrate/,
#                    log in $MARVEEN_STORE/konyveles-hydrate.log
#   DRY_NOTIFY=1     test: log the notifications instead of sending them

set -u
umask 077  # Viktor 27189 INFO-2: the state lists hold full accounting file paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
STORE="${MARVEEN_STORE:-$PROJECT_DIR/store}"
ROOT="${KONYVELES_ROOT:-}"
CARD="${KONYVELES_CARD:-}"
STATE="$STORE/konyveles-hydrate"
HYDRATE_MAX_S=${KONYVELES_HYDRATE_MAX_S:-1800}  # the whole download pass; the job runs hourly
LOG="$STORE/konyveles-hydrate.log"
mkdir -p "$STATE"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }
now=$(date +%s)

# notify <to> <text>: one inter-agent line (or a log line under DRY_NOTIFY)
notify() {
  if [ -n "${DRY_NOTIFY:-}" ]; then log "DRY_NOTIFY to=$1: $2"; return; fi
  bash "$SCRIPT_DIR/agent-msg.sh" kernel "$1" "$2" >> "$LOG" 2>&1
}
# card_comment <text>
card_comment() {
  [ -n "$CARD" ] || return 0
  if [ -n "${DRY_NOTIFY:-}" ]; then log "DRY_NOTIFY card=$CARD: $1"; return; fi
  python3 -I - "$STORE/.dashboard-token" "$CARD" "$1" >> "$LOG" 2>&1 <<'PY'
import json, sys, urllib.request
tok_path, card, msg = sys.argv[1:4]
tok = open(tok_path).read().strip()
req = urllib.request.Request("http://localhost:3420/api/kanban/%s/comments" % card, method="POST",
    data=json.dumps({"author": "kernel", "content": "[konyveles-hydrate] " + msg}).encode(),
    headers={"Content-Type": "application/json", "Authorization": "Bearer " + tok})
print("card-comment", urllib.request.urlopen(req, timeout=10).status)
PY
}
# due <stamp-file> <seconds>: true if the stamp is older than <seconds> (or missing)
due() { local t; t=$(cat "$STATE/$1" 2>/dev/null || echo 0); [ $((now - t)) -ge "$2" ]; }
stamp() { echo "$now" > "$STATE/$1"; }

fail() {
  log "ERROR $1"
  if due last-error 86400; then
    stamp last-error
    local msg="Könyvelés-visszatöltő HIBA: $1. A mappa lehet, hogy nincs helyben. Napló: store/konyveles-hydrate.log"
    card_comment "$msg"
    notify pulzus "Kernel -> Pulzus (automatikus, konyveles-hydrate): $msg"
  fi
  exit 1
}

[ -n "$ROOT" ] || fail "KONYVELES_ROOT is not set"
[ -d "$ROOT" ] || fail "the folder is missing or not visible"

KNOWN="$STATE/known-local.txt"; touch "$KNOWN"
DL="$STATE/dataless.txt"
ALL="$STATE/all.txt"
FERR="$STATE/find.err"
find "$ROOT" -type f > "$ALL" 2>"$FERR"; rc_all=$?
# find_why: the first find error reduced to an errno name and whether it hit
# ROOT itself or something below it (Viktor 15528: no file name, no free text).
find_why() {
  local line where="below-ROOT" why="OTHER"
  line=$(head -n 1 "$FERR" 2>/dev/null | cut -c1-200)
  rm -f "$FERR"   # the raw stderr names files: never kept
  [ -n "$line" ] || { echo "no-stderr"; return; }
  case "$line" in "find: $ROOT: "*) where="at-ROOT" ;; esac
  case "$line" in
    *"Operation not permitted") why="EPERM" ;;
    *"Permission denied") why="EACCES" ;;
    *"No such file or directory") why="ENOENT" ;;
    *"Resource deadlock avoided") why="EDEADLK" ;;
    *"Operation timed out") why="ETIMEDOUT" ;;
  esac
  echo "$why $where"
}
[ "$rc_all" = 0 ] || fail "find exited non-zero ($rc_all, $(find_why))"
: > "$FERR"
find "$ROOT" -type f -flags +dataless > "$DL" 2>"$FERR"; rc_dl=$?
total=$(grep -c . "$ALL" || true)
[ "$rc_dl" = 0 ] || fail "find exited non-zero (dataless walk $rc_dl, files=$total, $(find_why))"
rm -f "$FERR"
[ "$total" -gt 0 ] || fail "the walk saw no file (files=0; launchd without access to ~/Library/CloudStorage?)"
n=$(grep -c . "$DL" || true)

evicted=0; new=0; left=0; errs=""; folders=""; names=""
if [ "$n" -gt 0 ]; then
  # evicted count and sanitized top-level folder names (LOW-1), then the download (errors by errno only)
  read -r evicted names <<< "$(python3 -I "$SCRIPT_DIR/konyveles-hydrate.py" classify "$ROOT" "$DL" "$KNOWN")"
  case "$evicted" in ''|*[!0-9]*) evicted=0 ;; esac
  new=$((n - evicted))
  [ "$evicted" -gt 0 ] && folders=$(printf '%s' "$names" | python3 -I "$SCRIPT_DIR/konyveles-hydrate.py" fmt)
  # the download, with a watchdog over the whole pass (INFO-3: a read the per-file alarm cannot break)
  tr '\n' '\0' < "$DL" | python3 -I "$SCRIPT_DIR/konyveles-hydrate.py" hydrate > "$STATE/errs.txt" 2>/dev/null &
  hp=$!; waited=0
  while kill -0 "$hp" 2>/dev/null && [ "$waited" -lt "$HYDRATE_MAX_S" ]; do sleep 1; waited=$((waited + 1)); done
  if kill -0 "$hp" 2>/dev/null; then
    kill "$hp" 2>/dev/null
    fail "the download ran longer than $HYDRATE_MAX_S s and was stopped ($n cloud-only files)"
  fi
  wait "$hp" 2>/dev/null
  errs=$(cat "$STATE/errs.txt" 2>/dev/null)
  left=$(find "$ROOT" -type f -flags +dataless 2>/dev/null | grep -c . || true)
fi
# every file that is local now is "known local" for the next run
find "$ROOT" -type f ! -flags +dataless 2>/dev/null | sort > "$KNOWN.tmp" && mv "$KNOWN.tmp" "$KNOWN"
log "files=$total dataless=$n evicted=$evicted new=$new still_dataless=$left${errs:+ read_errors=$errs}${folders:+ folders=$folders}"

# reporting (LOW-2): sum evictions, report at most every 6 h to Juró + card, once a day to Klodel on repeats
EV="$STATE/evictions.txt"
if [ "$evicted" -gt 0 ]; then
  echo "$now $evicted" >> "$EV"
  p=$(cat "$STATE/pending" 2>/dev/null || echo 0); echo $((p + evicted)) > "$STATE/pending"
  printf '%s\n' "$names" | tr ',' '\n' >> "$STATE/pending-folders"  # INFO-4: summed like the count
fi
pending=$(cat "$STATE/pending" 2>/dev/null || echo 0)
if [ "$pending" -gt 0 ] && due last-juro 21600; then
  pf=$(python3 -I "$SCRIPT_DIR/konyveles-hydrate.py" fmt < "$STATE/pending-folders" 2>/dev/null || echo "-")
  msg="Könyvelés (OneDrive): $pending fájl csak a felhőben volt (kiürült), visszatöltve; mappák: $pf; még felhőben: $left. Napló: store/konyveles-hydrate.log"
  notify juro "Kernel -> Juró (automatikus, óránkénti ellenőrzés): $msg"
  card_comment "$msg"
  stamp last-juro; echo 0 > "$STATE/pending"; rm -f "$STATE/pending-folders"
  events=$(awk -v t=$((now - 7 * 86400)) '$1 >= t' "$EV" 2>/dev/null | grep -c . || true)
  if [ "$events" -gt 1 ] && due last-klodel 86400; then
    notify klodel "Kernel -> Klodel (konyveles-hydrate, ISMÉTLŐDIK: 7 napon belül $events kiürülés): $msg"
    stamp last-klodel
  fi
fi
exit 0
