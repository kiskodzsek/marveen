#!/usr/bin/env bash
# host-restart-watchdog.sh
#
# Fires once at every user-manager start (oneshot, WantedBy=default.target),
# and on macOS at every login plus every 5 minutes (launchd RunAtLoad +
# StartInterval, scripts/install-host-restart-watchdog.sh).
# Under WSL2 the whole utility VM can shut down and re-boot (vmIdleTimeout
# auto-shutdown, Windows sleep/resume, `wsl --shutdown`), which tears down the
# kernel + system/user systemd + tmux + dashboard + channels all at once and is
# NOT an application crash. This watchdog detects that host/VM restart via the
# kernel boot time (/proc/stat btime) and sends ONE Telegram notice that names
# it as a host/WSL-VM restart (with an estimated downtime), so a fleet-wide
# silence is never mistaken for a CostOps/app crash.
#
# macOS (Patrik TG 3775, card 1c58f629): after the 2026-10-20 07:02 kernel panic
# the fleet was silent until 07:56 and nobody was told why. The boot time comes
# from kern.boottime, and a panic report filed after this boot adds the panic
# time and its first line, so the notice says what happened. With FileVault on,
# nothing (this script included) runs before someone logs in: the notice arrives
# as the team comes back, not when the box goes down.
#
# App/service crashes do NOT change btime and never trigger this script -- they
# are reported separately by the OnFailure= drop-ins (marveen-notify@.service).
# That split is the whole point: btime-change => host restart; OnFailure => app.
#
# Safe by construction: read-only except for the state file; Telegram send is
# best-effort; the script always exits 0 so the oneshot unit never enters
# `failed` (a failing watchdog would itself look like an incident).

set -uo pipefail

STATE_DIR="${MARVEEN_STORE:-$HOME/marveen/store}"
STATE_FILE="$STATE_DIR/.last-btime"
INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# #915: main channel state is install-scoped once migrated; the legacy shared
# path only serves unmigrated installs.
TG_CHAN_DIR="${TELEGRAM_STATE_DIR:-}"
if [ -z "$TG_CHAN_DIR" ]; then
  TG_CHAN_DIR="$INSTALL_DIR/.claude/channels/telegram"
  [ -f "$TG_CHAN_DIR/.env" ] || TG_CHAN_DIR="$HOME/.claude/channels/telegram"
fi
ENV_FILE="${TELEGRAM_ENV:-$TG_CHAN_DIR/.env}"
# Alert target chat-id -- MUST come from the install's own config; there is
# deliberately NO hardcoded fallback (a hardcoded id would make every downstream
# install send its host-stability alerts to that one private chat).
CHAT_ID="${MARVEEN_ALERT_CHAT_ID:-}"
# ZAKARFELUGY921 (kulso bejelentes, 2026-09-21): a MARVEEN_ALERT_CHAT_ID-t SEMMI
# nem allitotta be -- se unit-sablon, se az install-linux.sh (merve: 0 elofordulas
# mindkettoben) --, tehat ervenyes tokennel SEM ment ki semmi. Beegetni tilos, es a
# unitba irni sem lehet: a telepito a unitokat a PAROSITAS ELOTT irja ki, amikor a
# CHAT_ID meg a "0" placeholder (install-linux.sh:812, es a docs/channels.md ki is
# mondja ezt a sorrend-fuggest). Ezert FUTASIDOBEN oldjuk fel, ugyanazzal az alakkal,
# amit a scripts/fleet-memory-gate.sh mar hasznal: az access.json elso engedelyezett
# kuldoje -- ugyanaz a lista, amit a plugin befele is betartat, tehat a feloldott id
# kezbesitheto. Ures marad -> a kuldes kimarad es a hiany NEVESITVE naplozodik.
ACCESS_JSON="${TELEGRAM_ACCESS:-$TG_CHAN_DIR/access.json}"
if [[ -z "$CHAT_ID" && -f "$ACCESS_JSON" ]] && command -v python3 >/dev/null 2>&1; then
  CHAT_ID="$(python3 -c 'import json,sys
try:
  a=json.load(open(sys.argv[1]));v=a.get("allowFrom") or []
  print(v[0] if v else "")
except Exception: print("")' "$ACCESS_JSON" 2>/dev/null)"
fi
# EGYETLEN ELTERES a fleet-memory-gate meglevo alakjatol, es szandekos: a "0" a
# telepito placeholder-e, nem chat (install-linux.sh:812). Ott ez a sor nincs meg;
# ha a gyakorlatban kell neki is, kulon korben megy at, nem mellekhatasként.
[ "$CHAT_ID" = "0" ] && CHAT_ID=""

log() { echo "[host-restart-watchdog] $*"; }

# GNU date/stat on Linux, BSD on macOS.
fmt_epoch() { date -d "@$1" "+$2" 2>/dev/null || date -r "$1" "+$2" 2>/dev/null || echo "@$1"; }
mtime_of() { stat -c '%Y' "$1" 2>/dev/null || stat -f '%m' "$1" 2>/dev/null || echo 0; }
IS_DARWIN=0
[[ "${HOSTWD_UNAME:-$(uname -s 2>/dev/null)}" == "Darwin" ]] && IS_DARWIN=1

# Real WSL check -- only under WSL is a whole-VM reboot the expected surprise;
# on a bare-metal/other Linux host a btime change is an ordinary reboot, so we
# word the alert accordingly instead of always claiming "WSL VM restarted".
if grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null \
   || [[ -n "${WSL_DISTRO_NAME:-}" ]] || [[ -e /run/WSL ]]; then
  HOST_KIND="WSL VM"
elif (( IS_DARWIN )); then
  HOST_KIND="Mac"
else
  HOST_KIND="host"
fi

# Current kernel boot epoch (changes only on a real (re)boot of the VM/host).
# Linux: /proc/stat btime. macOS: kern.boottime, "{ sec = 1792475438, usec = ... } ...";
# /usr/sbin is not on a launchd job's PATH, hence the full path.
# HOSTWD_PROC_STAT, HOSTWD_BOOTTIME (a raw kern.boottime line) and HOSTWD_UNAME
# exist for tests only.
PROC_STAT="${HOSTWD_PROC_STAT:-/proc/stat}"
btime="$(awk '/^btime/{print $2}' "$PROC_STAT" 2>/dev/null)"
if [[ -z "${btime:-}" ]] && (( IS_DARWIN )); then
  boottime_raw="${HOSTWD_BOOTTIME:-$(/usr/sbin/sysctl -n kern.boottime 2>/dev/null)}"
  btime="$(printf '%s\n' "$boottime_raw" | sed -n 's/^{ *sec *= *\([0-9][0-9]*\),.*/\1/p' | head -1)"
fi
if [[ -z "${btime:-}" ]]; then
  log "no boot time ($PROC_STAT btime / kern.boottime); nothing to do"
  exit 0
fi

mkdir -p "$STATE_DIR" 2>/dev/null || true
prev=""
[[ -f "$STATE_FILE" ]] && prev="$(tr -dc '0-9' <"$STATE_FILE" 2>/dev/null)"

# The btime baseline is persisted on init below, but after a DETECTED restart
# only once the notice actually delivered (see the send block): this is a
# one-shot message, and stamping before a failed send lost it forever
# (NOTIFYVAKSWEEP826). While the send keeps failing, every timer run retries.

if [[ -z "$prev" ]]; then
  echo "$btime" >"$STATE_FILE" 2>/dev/null || true
  log "baseline initialised (btime=$btime); no alert on first run"
  exit 0
fi

if [[ "$prev" == "$btime" ]]; then
  log "btime unchanged ($btime) -- user-manager restart without a host reboot; no alert"
  exit 0
fi

# --- host/VM restart detected (btime changed) ---
boot_local="$(fmt_epoch "$btime" '%Y-%m-%d %H:%M:%S %Z')"

# Estimate downtime: newest store/*.log mtime that predates this boot ~= last
# fleet activity before the VM went down. gap = boot_time - that mtime.
last_alive=0
if compgen -G "$STATE_DIR/*.log" >/dev/null 2>&1; then
  for f in "$STATE_DIR"/*.log; do
    m="$(mtime_of "$f")"
    if (( m < btime && m > last_alive )); then last_alive="$m"; fi
  done
fi
gap_txt="ismeretlen"
if (( last_alive > 0 )); then
  gap_min=$(( (btime - last_alive) / 60 ))
  last_txt="$(fmt_epoch "$last_alive" '%H:%M:%S')"
  gap_txt="~${gap_min} perc (utolsó aktivitás ${last_txt} előtt)"
fi

if (( IS_DARWIN )); then
  # The crash reporter files a panic report at the next boot, so one newer than
  # this boot belongs to the crash that ended the previous one. HOSTWD_PANIC_DIR
  # exists for tests only.
  PANIC_DIR="${HOSTWD_PANIC_DIR:-/Library/Logs/DiagnosticReports}"
  panic_file=""; panic_m=0
  for f in "$PANIC_DIR"/panic-full-*.panic; do
    [[ -f "$f" ]] || continue
    m="$(mtime_of "$f")"
    if (( m >= btime && m > panic_m )); then panic_file="$f"; panic_m="$m"; fi
  done
  panic_txt=""
  if [[ -n "$panic_file" ]] && command -v python3 >/dev/null 2>&1; then
    panic_txt="$(python3 -I "$INSTALL_DIR/scripts/lib/panic-summary.py" "$panic_file" 2>/dev/null | head -1)"
  fi
  # Downtime runs to NOW, not to the boot: the team is back when this runs
  # (after the login), and that is the gap Patrik saw.
  now_epoch="$(date +%s)"
  down_txt="ismeretlen"
  if (( last_alive > 0 )); then
    down_txt="kb. $(( (now_epoch - last_alive) / 60 )) perc ($(fmt_epoch "$last_alive" '%H:%M') - $(fmt_epoch "$now_epoch" '%H:%M'))"
  fi
  msg="A gép újraindult, boot: $(fmt_epoch "$btime" '%H:%M').
Kiesés: ${down_txt}.${panic_txt:+
Ok: ${panic_txt}}
A csapat visszaáll: Klodel indul elsőként, utána egyenként a többiek."
else
  msg="Marveen ${HOST_KIND} restarted.
Új boot: ${boot_local}
Becsült kiesés: ${gap_txt}
(Ez host/VM szintű restart, NEM app-crash. A dashboard/channels app-crash külön OnFailure-értesítést küld.)"
fi

log "host restart detected: prev btime=$prev new=$btime; sending Telegram"

# Best-effort Telegram send. Never let a send failure fail the unit.
token=""
if [[ -f "$ENV_FILE" ]]; then
  token="$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"' \r\n')"
fi
if [[ -n "$token" && -n "$CHAT_ID" ]]; then
  # Honest send (curl exit 0 AND "ok":true -- an HTTP 200 with ok:false was
  # invisible here before). Baseline stamped ONLY on confirmed delivery: this
  # one-shot notice must survive a transient send failure by retrying on the
  # next run, not by being marked done.
  . "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/send-telegram.sh"
  if send_err="$(send_telegram_message "$token" "$CHAT_ID" "$msg" 2>&1)"; then
    echo "$btime" >"$STATE_FILE" 2>/dev/null || true
    log "Telegram sent (btime baseline stamped)"
  else
    log "Telegram send FAILED -- baseline NOT stamped, will retry next run: ${send_err}"
  fi
else
  log "skipping Telegram (${HOST_KIND} restart still logged): missing${token:+}$( [[ -z "$token" ]] && echo ' TELEGRAM_BOT_TOKEN(via TELEGRAM_ENV)')$( [[ -z "$CHAT_ID" ]] && echo ' MARVEEN_ALERT_CHAT_ID')"
fi

exit 0
