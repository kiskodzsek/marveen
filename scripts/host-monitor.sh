#!/usr/bin/env bash
# host-monitor.sh -- one pass of the host health check (launchd/systemd: every 60 s).
#
#   host-monitor.sh            measure, write store/.host-state, alert on CRITICAL
#   host-monitor.sh --status   measure and print, no state write, no alert
#
# Why (2026-10-20, card 1c58f629): the Mac mini panicked at 07:02:20 with free
# memory at 871 pages, and at 08:08 the data volume was down to 5.6 GiB free.
# Nobody saw either coming. Patrik: "tudnotok kell a rendszer helyzetét
# figyelni, és nem terhelhetitek olyan állapotig, hogy újraindulást vagy
# leállást kockáztassunk."
#
# Measures: free memory % (lib/mem-read.sh), swap use %, free disk on the
# store's volume, 1-minute load per CPU, and on macOS whether `pmset -g therm`
# has recorded a thermal warning (temperatures need root, so none are read).
#
# Bands (defaults, env-overridable):
#   CRITICAL  free mem < 12% | disk < 3 GiB | swap >= 90% with free mem < 25%
#             | a thermal warning is recorded
#   WARN      free mem < 25% | disk < 10 GiB | swap >= 75% | load1 > 2 x CPUs
#   OK        otherwise
#
# Effects:
#   - store/.host-state = "<band> <epoch> <reason>" (written atomically).
#     heavy-job.sh refuses to start while it says warn/critical; the fleet
#     memory gate keeps its own memory bands for agent starts.
#   - store/host-monitor.log: one line per band CHANGE, not per run.
#   - entering CRITICAL (and every 30 min while it lasts): one Telegram line to
#     the owner chat and one inter-agent message to the main agent. A failed
#     Telegram send does not stamp the cooldown, so it is retried next run.
#   - It never kills, pauses or restarts anything. Pausing non-core agents in
#     CRITICAL is a separate, approved step, not a side effect of a monitor.
#
# Test hooks: MEMGATE_PROC_MEMINFO / MEMGATE_SYSCTL (memory), HOSTMON_SWAP_PCT,
# HOSTMON_DF_KB, HOSTMON_LOAD1, HOSTMON_NCPU, HOSTMON_THERM (text of
# `pmset -g therm`), HOSTMON_NOW (epoch), MARVEEN_STORE (state dir).

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$(cd "$HERE/.." && pwd)"
STORE="${MARVEEN_STORE:-$INSTALL_DIR/store}"
STATE="$STORE/.host-state"
LOG="$STORE/host-monitor.log"
STAMP="$STORE/.host-monitor-alert"
MODE="run"; [[ "${1:-}" == "--status" ]] && MODE="status"

CRIT_FREE="${HOSTMON_CRIT_FREE_PCT:-12}"
WARN_FREE="${HOSTMON_WARN_FREE_PCT:-25}"
CRIT_DISK_GB="${HOSTMON_CRIT_DISK_GB:-3}"
WARN_DISK_GB="${HOSTMON_WARN_DISK_GB:-10}"
WARN_SWAP="${HOSTMON_WARN_SWAP_PCT:-75}"
CRIT_SWAP="${HOSTMON_CRIT_SWAP_PCT:-90}"
COOLDOWN="${HOSTMON_ALERT_COOLDOWN:-1800}"
NOW="${HOSTMON_NOW:-$(date +%s)}"
SYSCTL="${MEMGATE_SYSCTL:-/usr/sbin/sysctl}"

. "$HERE/lib/mem-read.sh"

# --- measure (an unreadable metric is reported, never guessed) ---
free_pct="?"; mem_read && free_pct="$MEM_FREE_PCT"

swap_pct="${HOSTMON_SWAP_PCT:-}"
if [[ -z "$swap_pct" ]]; then
  if [[ -r /proc/meminfo ]]; then
    swap_pct="$(awk '/^SwapTotal:/{t=$2}/^SwapFree:/{f=$2}END{if(t>0)printf "%d",(t-f)*100/t; else print 0}' /proc/meminfo)"
  else
    # "total = 4096.00M  used = 2621.62M  free = ..."
    swap_pct="$("$SYSCTL" -n vm.swapusage 2>/dev/null | awk '{t=$3;u=$6;gsub(/M/,"",t);gsub(/M/,"",u);if(t>0)printf "%d",u*100/t; else print 0}')"
  fi
fi
[[ "$swap_pct" =~ ^[0-9]+$ ]] || swap_pct="?"

disk_dir="$STORE"; [[ -d "$disk_dir" ]] || disk_dir="$INSTALL_DIR"
disk_kb="${HOSTMON_DF_KB:-$(df -Pk "$disk_dir" 2>/dev/null | awk 'NR==2{print $4}')}"
[[ "$disk_kb" =~ ^[0-9]+$ ]] || disk_kb="?"
disk_gb="?"; [[ "$disk_kb" != "?" ]] && disk_gb=$(( disk_kb / 1048576 ))

ncpu="${HOSTMON_NCPU:-$("$SYSCTL" -n hw.ncpu 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null)}"
load1="${HOSTMON_LOAD1:-}"
if [[ -z "$load1" ]]; then
  if [[ -r /proc/loadavg ]]; then load1="$(cut -d' ' -f1 /proc/loadavg)"
  else load1="$("$SYSCTL" -n vm.loadavg 2>/dev/null | awk '{print $2}')"; fi
fi
load_int="${load1%%.*}"; [[ "$load_int" =~ ^[0-9]+$ && "$ncpu" =~ ^[0-9]+$ ]] || { load_int="?"; }

therm="${HOSTMON_THERM-$( [[ -x /usr/bin/pmset ]] && /usr/bin/pmset -g therm 2>/dev/null )}"
therm_warn=0
# "No thermal warning level has been recorded" is the healthy text; a
# recorded level reads "Thermal warning level set to <n>." (n > 0 = throttled).
if echo "$therm" | grep -qiE 'thermal warning level set to [1-9]'; then therm_warn=1; fi

# --- band ---
band="ok"; why=()
crit() { band="critical"; why+=("$1"); }
warn() { [[ "$band" == "critical" ]] || band="warn"; why+=("$1"); }
if [[ "$free_pct" != "?" ]]; then
  if (( free_pct < CRIT_FREE )); then crit "free memory ${free_pct}%"
  elif (( free_pct < WARN_FREE )); then warn "free memory ${free_pct}%"; fi
fi
if [[ "$disk_gb" != "?" ]]; then
  if (( disk_gb < CRIT_DISK_GB )); then crit "free disk ${disk_gb} GiB"
  elif (( disk_gb < WARN_DISK_GB )); then warn "free disk ${disk_gb} GiB"; fi
fi
if [[ "$swap_pct" != "?" ]]; then
  if (( swap_pct >= CRIT_SWAP )) && [[ "$free_pct" != "?" ]] && (( free_pct < WARN_FREE )); then crit "swap ${swap_pct}% with free memory ${free_pct}%"
  elif (( swap_pct >= WARN_SWAP )); then warn "swap ${swap_pct}%"; fi
fi
if [[ "$load_int" != "?" ]] && (( load_int > 2 * ncpu )); then warn "load ${load1} on ${ncpu} CPUs"; fi
(( therm_warn )) && crit "thermal warning recorded"
[[ "$free_pct" == "?" ]] && warn "memory unreadable"

reason="$(IFS=';'; echo "${why[*]:-}")"
line="band=${band} free=${free_pct}% swap=${swap_pct}% disk=${disk_gb}GiB load1=${load1:-?}/${ncpu:-?}cpu therm=${therm_warn}${reason:+ reason=${reason}}"

if [[ "$MODE" == "status" ]]; then echo "$line"; exit 0; fi

mkdir -p "$STORE" 2>/dev/null
prev_band="$(cut -d' ' -f1 "$STATE" 2>/dev/null)"
tmp="$STATE.tmp.$$"
echo "${band} ${NOW} ${reason}" >"$tmp" 2>/dev/null && mv -f "$tmp" "$STATE" 2>/dev/null
if [[ "$band" != "${prev_band:-}" ]]; then
  echo "$(date -r "$NOW" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date '+%Y-%m-%d %H:%M:%S') ${prev_band:-none} -> ${line}" >>"$LOG" 2>/dev/null
fi
echo "$line"

[[ "$band" == "critical" ]] || exit 0

# --- CRITICAL alert, cooldown-deduped ---
last="$(cat "$STAMP" 2>/dev/null | tr -dc '0-9')"
tg_due=1
if [[ -n "$last" ]] && (( NOW - last < COOLDOWN )) && [[ "${prev_band:-}" == "critical" ]]; then tg_due=0; fi

msg="Mac mini KRITIKUS: ${reason}. Szabad memória ${free_pct}%, swap ${swap_pct}%, lemez ${disk_gb} GiB. Nehéz munka nem indul; nézzétek, mi fut."

TG_CHAN_DIR="${TELEGRAM_STATE_DIR:-}"
if [[ -z "$TG_CHAN_DIR" ]]; then
  TG_CHAN_DIR="$INSTALL_DIR/.claude/channels/telegram"
  [[ -f "$TG_CHAN_DIR/.env" ]] || TG_CHAN_DIR="$HOME/.claude/channels/telegram"
fi
ENV_FILE="${TELEGRAM_ENV:-$TG_CHAN_DIR/.env}"
ACCESS_JSON="${TELEGRAM_ACCESS:-$TG_CHAN_DIR/access.json}"
CHAT_ID="${MARVEEN_ALERT_CHAT_ID:-}"
if [[ -z "$CHAT_ID" && -f "$ACCESS_JSON" ]] && command -v python3 >/dev/null 2>&1; then
  CHAT_ID="$(python3 -c 'import json,sys
try:
  a=json.load(open(sys.argv[1]));v=a.get("allowFrom") or []
  print(v[0] if len(v)==1 else "")
except Exception: print("")' "$ACCESS_JSON" 2>/dev/null)"
fi
[[ "$CHAT_ID" == "0" ]] && CHAT_ID=""
token=""
[[ -f "$ENV_FILE" ]] && token="$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"' \r\n')"

sent=0
if (( ! tg_due )); then
  :
elif [[ -n "$token" && -n "$CHAT_ID" ]]; then
  . "$HERE/lib/send-telegram.sh"
  if send_err="$(send_telegram_message "$token" "$CHAT_ID" "$msg" 2>&1)"; then
    sent=1; echo "$NOW" >"$STAMP" 2>/dev/null
  else
    echo "$(date '+%Y-%m-%d %H:%M:%S') Telegram FAILED (cooldown not stamped): ${send_err}" >>"$LOG" 2>/dev/null
  fi
else
  echo "$(date '+%Y-%m-%d %H:%M:%S') Telegram skipped: no token or no single owner chat" >>"$LOG" 2>/dev/null
fi

MAIN_AGENT="${HOSTMON_MAIN_AGENT:-$( [[ -f "$INSTALL_DIR/.env" ]] && grep -E '^MAIN_AGENT_ID=' "$INSTALL_DIR/.env" | head -1 | cut -d= -f2- | tr -d '"'"'"'\r' )}"
# Own cooldown stamp: a failing Telegram must not turn this into a message
# to the main agent on every 60 s run.
alast="$(cat "$STAMP.agent" 2>/dev/null | tr -dc '0-9')"
if [[ -n "${MAIN_AGENT:-}" && -f "$HERE/agent-msg.sh" ]] \
   && ! { [[ -n "$alast" ]] && (( NOW - alast < COOLDOWN )) && [[ "${prev_band:-}" == "critical" ]]; }; then
  if echo "[HOST-MONITOR] ${msg}" | bash "$HERE/agent-msg.sh" host-monitor "$MAIN_AGENT" - >/dev/null 2>&1; then
    echo "$NOW" >"$STAMP.agent" 2>/dev/null
  else
    echo "$(date '+%Y-%m-%d %H:%M:%S') inter-agent message to ${MAIN_AGENT} FAILED" >>"$LOG" 2>/dev/null
  fi
fi
(( sent )) && echo "alert sent"
exit 0
