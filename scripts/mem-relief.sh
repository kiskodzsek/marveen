#!/usr/bin/env bash
# mem-relief.sh -- the hard step before the Mac runs out of memory (Klodel 25411, card 1c58f629).
#
#   mem-relief.sh            one pass (launchd: every 60 s, scripts/install-mem-relief.sh)
#
# Why: 2026-11-03 16:56:57 the Mac mini took a kernel panic, "watchdog timeout: no checkins
# from watchdogd in 92 seconds" (/Library/Logs/DiagnosticReports/panic-full-2026-11-03-173033.0002.panic):
# 908 free pages, the compressor at 100% of its segments limit, 17 swap files and LOW swap space,
# 0 GiB free disk at 16:52:25. Five next dev servers (19.6 GB) and a Colima VM (3.5 GB) held
# the memory; the VM and four of the servers had been started again at 16:41, minutes after
# they were stopped by hand. host-monitor.sh was CRITICAL from 16:43:24 and could only page:
# a stop on CRITICAL is "a separate, approved step, not a side effect of a monitor" (its header).
# This is that step. Analysis: shared/cleanup-1103/panic-1103-elemzes.md.
#
# When it acts (both read fresh each pass):
#   - store/.host-state says critical, is at most MEM_RELIEF_STATE_MAX_AGE (180) s old, and a
#     reason is memory, swap or disk (a load- or thermal-only critical is left to the owner); or
#   - swap used is above MEM_RELIEF_SWAP_GB (default 11) GB, whatever the band says.
# And not within MEM_RELIEF_COOLDOWN (600) s of its last action, so a VM that someone starts
# again is stopped again only after the owners were told and had time to see it.
#
# What it does, in this order, and nothing else (no file is touched):
#   1. the Colima VM: `colima stop`, up to MEM_RELIEF_COLIMA_WAIT (60) s; if the VM is still up,
#      `limactl stop -f colima`. The VM's disk stays; `colima start` brings it back.
#   2. every next dev server (scripts/swap-culprits.py) whose port is not kept in
#      store/dev-keep.list: SIGTERM to the server and its descendants, SIGKILL to what is left
#      after MEM_RELIEF_KILL_WAIT (10) s.
#      store/dev-keep.list is managed by Klodel/Kernel, not by the agents (they ask; Viktor 25470 c),
#      and is empty by decision (Klodel 25469). A line is "<port> until=<epoch>": it counts only
#      while until is in the future and at most MEM_RELIEF_KEEP_MAX_SECS (8 h) ahead; only the
#      first MEM_RELIEF_KEEP_MAX (2) valid lines count; a bare port or anything else is ignored
#      (and logged). The VM can never be kept. Every KEEP is logged.
#      The worktree, its .next and node_modules stay; `npm run dev` brings it back.
#   3. one inter-agent message to each owner (the agents/<id>/ path in the process chain) and the
#      main agent, naming what was stopped and why. A line per action in store/mem-relief.log.
# MEM_RELIEF_DRY=1: decide and log what it would do, stop nothing, send nothing.
#
# Exit: 0 (nothing to do, or done), 1 (an action failed; the rest still ran).
# Test hooks: MEM_RELIEF_NOW, MEM_RELIEF_KEEP_MAX, MEM_RELIEF_KEEP_MAX_SECS, MEM_RELIEF_SWAP_MB, MEM_RELIEF_PS (a `ps -axo pid=,ppid=,command=`
# file), MEM_RELIEF_COLIMA, MEM_RELIEF_LIMACTL, MEM_RELIEF_KILL, MEM_RELIEF_AGENT_MSG,
# MEM_RELIEF_INSTALL_DIR, MARVEEN_STORE.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STORE="${MARVEEN_STORE:-$HERE/../store}"
INSTALL_DIR="${MEM_RELIEF_INSTALL_DIR:-$HERE/..}"
LOG="$STORE/mem-relief.log"
STAMP="$STORE/.mem-relief.last"
KEEP="$STORE/dev-keep.list"
STATE_MAX_AGE="${MEM_RELIEF_STATE_MAX_AGE:-180}"
SWAP_GB="${MEM_RELIEF_SWAP_GB:-11}"
COOLDOWN="${MEM_RELIEF_COOLDOWN:-600}"
COLIMA_WAIT="${MEM_RELIEF_COLIMA_WAIT:-60}"
KILL_WAIT="${MEM_RELIEF_KILL_WAIT:-10}"
KEEP_MAX="${MEM_RELIEF_KEEP_MAX:-2}"
KEEP_MAX_SECS="${MEM_RELIEF_KEEP_MAX_SECS:-28800}"
COLIMA="${MEM_RELIEF_COLIMA:-$(command -v colima || echo /opt/homebrew/bin/colima)}"
LIMACTL="${MEM_RELIEF_LIMACTL:-$(command -v limactl || echo /opt/homebrew/bin/limactl)}"
KILL="${MEM_RELIEF_KILL:-kill}"
AGENT_MSG="${MEM_RELIEF_AGENT_MSG:-$HERE/agent-msg.sh}"
DRY="${MEM_RELIEF_DRY:-0}"

mkdir -p "$STORE" 2>/dev/null
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >>"$LOG" 2>/dev/null; }
now() { echo "${MEM_RELIEF_NOW:-$(date +%s)}"; }

swap_mb() {
  local v="${MEM_RELIEF_SWAP_MB:-}"
  [[ -n "$v" ]] || v="$(/usr/sbin/sysctl -n vm.swapusage 2>/dev/null | sed -n 's/.*used = \([0-9]*\)[.0-9]*M.*/\1/p')"
  [[ "$v" =~ ^[0-9]+$ ]] && echo "$v" || echo 0
}
ps_snapshot() { if [[ -n "${MEM_RELIEF_PS:-}" ]]; then cat "$MEM_RELIEF_PS" 2>/dev/null; else ps -axo pid=,ppid=,command= 2>/dev/null; fi; }
culprits() { python3 -I "$HERE/swap-culprits.py" ${MEM_RELIEF_PS:+--ps "$MEM_RELIEF_PS"} 2>/dev/null; }

# Why act now? Prints the reason, or nothing.
trigger() {
  local band ts rest mb
  mb="$(swap_mb)"
  if (( mb > SWAP_GB * 1024 )); then echo "swap ${mb} MB > ${SWAP_GB} GB"; return; fi
  [[ -r "$STORE/.host-state" ]] || return
  read -r band ts rest < "$STORE/.host-state" || return
  [[ "$band" == "critical" && "$ts" =~ ^[0-9]+$ ]] || return
  (( $(now) - ts <= STATE_MAX_AGE )) || return
  [[ "$rest" =~ (memory|swap|disk) ]] || return
  echo "host-monitor critical: $rest"
}

descendants() {
  local p="$1" c
  echo "$p"
  for c in $(echo "$PSDATA" | awk -v p="$p" '$2==p{print $1}'); do descendants "$c"; done
}

# The ports store/dev-keep.list keeps right now (see point 2 above), one a line; a line that does
# not count is logged once per pass.
kept_ports() {
  [[ -f "$KEEP" ]] || return 0
  local line port until n=0 t; t="$(now)"
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"; line="$(echo "$line" | tr -d '\r' | xargs 2>/dev/null)"
    [[ -n "$line" ]] || continue
    if [[ "$line" =~ ^([0-9]+)\ until=([0-9]+)$ ]]; then
      port="${BASH_REMATCH[1]}"; until="${BASH_REMATCH[2]}"
      if (( until <= t )); then log "IGNORE dev-keep '$line': expired"; continue; fi
      if (( until - t > KEEP_MAX_SECS )); then log "IGNORE dev-keep '$line': more than ${KEEP_MAX_SECS} s ahead"; continue; fi
      if (( n >= KEEP_MAX )); then log "IGNORE dev-keep '$line': only ${KEEP_MAX} ports may be kept"; continue; fi
      echo "$port"; n=$((n + 1))
    else
      log "IGNORE dev-keep '$(echo "$line" | tr -c 'A-Za-z0-9 =._-' '_' | cut -c1-60)': not '<port> until=<epoch>'"
    fi
  done < "$KEEP"
}

main() {
  local why last list rc=0 done_lines=() owners=""
  why="$(trigger)"
  [[ -n "$why" ]] || return 0
  last="$(cat "$STAMP" 2>/dev/null)"; [[ "$last" =~ ^[0-9]+$ ]] || last=0
  if (( $(now) - last < COOLDOWN )); then log "SKIP cooldown ($why)"; return 0; fi
  PSDATA="$(ps_snapshot)"
  KEPT="$(kept_ports)"
  list="$(culprits)"
  local dl=""; [[ "$DRY" == "1" ]] && dl=" dry"
  log "ACT${dl} ($why) suspects=$(echo "$list" | grep -c . )"

  # 1. The VM.
  if echo "$list" | grep -q $'\tColima VM$'; then
    if [[ "$DRY" == "1" ]]; then
      done_lines+=("Colima VM (dry)")
    else
      "$COLIMA" stop >/dev/null 2>&1 &
      local cp=$! waited=0
      while kill -0 "$cp" 2>/dev/null && (( waited < COLIMA_WAIT )); do sleep 1; waited=$((waited + 1)); done
      kill -0 "$cp" 2>/dev/null && kill "$cp" 2>/dev/null
      if culprits | grep -q $'\tColima VM$'; then
        "$LIMACTL" stop -f colima >/dev/null 2>&1 || true
      fi
      if culprits | grep -q $'\tColima VM$'; then log "FAIL Colima VM still up after colima stop and limactl stop -f"; rc=1
      else log "STOP Colima VM"; done_lines+=("Colima VM"); fi
    fi
    owners+=" $(echo "$list" | awk -F'\t' '$3=="Colima VM" && $1!="-"{print $1}')"
  fi

  # 2. The dev servers.
  local who pid what port pids p
  while IFS=$'\t' read -r who pid what; do
    [[ "$what" == next\ dev* ]] || continue
    port="$(echo "$what" | sed -n 's/^next dev :\([0-9?]*\).*/\1/p')"
    if [[ -n "$port" ]] && echo "$KEPT" | grep -qx -- "$port"; then log "KEEP $what (store/dev-keep.list)"; continue; fi
    if [[ "$DRY" == "1" ]]; then done_lines+=("$what (dry)"); owners+=" $who"; continue; fi
    pids="$(descendants "$pid" | sort -u | tr '\n' ' ')"
    for p in $pids; do "$KILL" -TERM "$p" 2>/dev/null; done
    local w=0 alive=1
    while (( w < KILL_WAIT )); do
      alive=0; for p in $pids; do "$KILL" -0 "$p" 2>/dev/null && alive=1; done
      (( alive )) || break
      sleep 1; w=$((w + 1))
    done
    if (( alive )); then for p in $pids; do "$KILL" -KILL "$p" 2>/dev/null; done; fi
    log "STOP $what owner=$who pids=$pids"
    done_lines+=("$what"); owners+=" $who"
  done <<< "$list"

  now >"$STAMP"
  (( ${#done_lines[@]} )) || { log "NOTHING to stop ($why)"; return "$rc"; }

  # 3. Tell the owners and the main agent.
  local main="" from to msg stopped
  [[ -f "$INSTALL_DIR/.env" ]] && main="$(grep -E '^MAIN_AGENT_ID=' "$INSTALL_DIR/.env" | head -1 | cut -d= -f2- | tr -d '"'"'"'\r')"
  from="${MEM_RELIEF_FROM:-$main}"
  stopped="$(printf '%s; ' "${done_lines[@]}")"; stopped="${stopped%; }"
  msg="[MEM-RELIEF] A gép a memória-határon volt (${why}), ezért leállítottam: ${stopped}. Fájlhoz nem nyúltam; colima start / npm run dev visszahozza, de csak ha a swap és a lemez rendben van. Ha egy szervernek mégis futnia kell, kérj kivételt Klodeltől (store/dev-keep.list, legfeljebb 8 óra, legfeljebb 2 port)."
  [[ "$DRY" == "1" ]] && log "DRY would stop: ${stopped}"
  [[ "$DRY" == "1" ]] && { log "DRY would tell:$(echo "$owners $main" | tr ' ' '\n' | awk 'NF && $0!="-" && !s[$0]++{printf " %s",$0}')"; return "$rc"; }
  [[ -n "$from" ]] || { log "TELL nobody: no sender id (MAIN_AGENT_ID)"; return "$rc"; }
  for to in $(echo "$owners $main" | tr ' ' '\n' | awk 'NF && $0!="-" && !s[$0]++'); do
    echo "$msg" | bash "$AGENT_MSG" "$from" "$to" - >/dev/null 2>&1 && log "TELL $to" || log "TELL $to FAILED"
  done
  return "$rc"
}

main
