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
# 0. The heavy-process gate, EVERY pass (60 s), whatever the memory band and the cooldown (Klodel 34315/34318): a
#    heavy process (Blender, ffmpeg, mflux) that does not run under scripts/heavy-job.sh (scripts/swap-culprits.py
#    --ungated-heavy) gets SIGTERM, SIGKILL after the wait, and its owner and the main agent are told how to run it.
#    heavy-job.sh starts one heavy job at a time and only with free memory. And on a memory trigger (below), step 0b
#    stops the LARGEST heavy process first, gated or not (a gated job can run with a low --kill-below). Why: the second kernel panic,
#    2026-11-09 15:19 (panic-full-2026-11-09-151916.0002.panic: watchdog timeout, 908 free pages, ~15 GiB wired):
#    two ungated Blender renders, 11.2 + 6.4 GB resident on the 16 GiB Mac. heavy-job.sh runs one heavy job at a
#    time and stops it when free memory falls (its watchdog); steps 1-2c below never stop an unknown large process.
#    MEM_RELIEF_RENDER_GATE=0 switches the gate off; MEM_RELIEF_DRY=1 only logs it.
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
#   2b. a memory leak of macOS itself (scripts/swap-culprits.py, by footprint; 2026-11-04: the video
#      decoder VTDecoderXPCService held 44 GB for its client, the Aerial wallpaper extension): the
#      WallpaperAerialsExtension and a VTDecoderXPCService over MEM_RELIEF_DECODER_GB (4) GB get
#      SIGTERM, SIGKILL after the wait. Both are stateless system services that launchd starts again
#      when needed; a static wallpaper keeps the Aerial one from coming back.
#      A process over MEM_RELIEF_LARGE_GB (6) GB that is none of the above is NOT stopped: it is named
#      in the message (LARGE in the log), so its owner and the main agent see it.
#   2c. only when 1-2b stopped nothing and swap used is over MEM_RELIEF_IDLE_SWAP_GB (12) GB (Klodel
#      26838/26862: on 2026-11-04 he freed memory by restarting five idle agents by hand): up to
#      MEM_RELIEF_IDLE_MAX (3) idle sub-agents are restarted through the dashboard
#      (POST /api/agents/<id>/restart, which keeps the conversation: --continue). Idle = the
#      tmux pane agent-<id> stands at an empty prompt (the scripts/idle-check.py test) AND no
#      process under the pane uses MEM_RELIEF_IDLE_CPU (10) % CPU or more and no Bash tool call of
#      the agent is still running (a shell-snapshots/snapshot-* shell), so a render, a build or a
#      background wait is never cut off. The main agent and the ids in MEM_RELIEF_IDLE_SKIP
#      (default "dave": his renders run on his own seat, as ALWAYS_BUSY in scripts/idle-check.py)
#      are never restarted. The restarted ones are named to the main agent.
#      Limits (Viktor 26889 F1: a restarted agent is idle again at once, and on 2026-11-04 20:28-21:08
#      five passes in a row found no culprit at 16-23 GB swap, so without them the same agents would
#      restart every 10 minutes, each --continue re-reading its whole conversation):
#        - one agent at most once per MEM_RELIEF_IDLE_GAP_SECS (6 h; store/.mem-relief-idle/id-<id>);
#        - at most MEM_RELIEF_IDLE_DAY_MAX (6) restarts a day, all agents together;
#        - no new round while the swap has not dropped since the last round (within the 6 h);
#        - an agent with an undelivered message, or one delivered in the last 15 min, is not idle
#          (a restart can lose what arrived just before it).
#      The state is written BEFORE the restart, and a write that fails stops the round (Viktor 26919
#      LOW-1: on a full disk the limits would otherwise never be recorded, the very day they matter).
#   3. one inter-agent message to each owner (the agents/<id>/ path in the process chain) and the
#      main agent, naming what was stopped and why. A line per action in store/mem-relief.log.
# MEM_RELIEF_DRY=1: decide and log what it would do, stop nothing, send nothing, and leave the
# cooldown stamp as it was: a dry pass that wrote it held the next real trigger off for 600 s
# (measured 2026-11-03 18:16 on the live store; Viktor 25498).
#
# Exit: 0 (nothing to do, or done), 1 (an action failed; the rest still ran).
# Test hooks: MEM_RELIEF_INBOX (a command run with the agent id, printing its count of fresh messages),
# MEM_RELIEF_TMUX (a tmux stand-in), MEM_RELIEF_PSCPU (a `ps -axo pid=,ppid=,%cpu=,command=`
# file), MEM_RELIEF_RESTART (a command run with the agent id instead of the dashboard call), MEM_RELIEF_TOP (a `top -l 1 -stats pid,mem` file), MEM_RELIEF_NOW, MEM_RELIEF_KEEP_MAX, MEM_RELIEF_KEEP_MAX_SECS, MEM_RELIEF_SWAP_MB, MEM_RELIEF_PS (a `ps -axo pid=,ppid=,command=`
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
GATE_TELL_GAP="${MEM_RELIEF_GATE_TELL_GAP:-600}"   # one heavy-gate message per recipient per 10 min (Viktor 34374)
COLIMA_WAIT="${MEM_RELIEF_COLIMA_WAIT:-60}"
KILL_WAIT="${MEM_RELIEF_KILL_WAIT:-10}"
KEEP_MAX="${MEM_RELIEF_KEEP_MAX:-2}"
KEEP_MAX_SECS="${MEM_RELIEF_KEEP_MAX_SECS:-28800}"
DECODER_GB="${MEM_RELIEF_DECODER_GB:-4}"
LARGE_GB="${MEM_RELIEF_LARGE_GB:-6}"
IDLE_SWAP_GB="${MEM_RELIEF_IDLE_SWAP_GB:-12}"
IDLE_MAX="${MEM_RELIEF_IDLE_MAX:-3}"
IDLE_CPU="${MEM_RELIEF_IDLE_CPU:-10}"
IDLE_SKIP="${MEM_RELIEF_IDLE_SKIP-dave}"
TMUX_BIN="${MEM_RELIEF_TMUX:-$(command -v tmux || echo /opt/homebrew/bin/tmux)}"
IDLE_GAP="${MEM_RELIEF_IDLE_GAP_SECS:-21600}"
IDLE_DAY_MAX="${MEM_RELIEF_IDLE_DAY_MAX:-6}"
IDLE_DIR="$STORE/.mem-relief-idle"
COLIMA="${MEM_RELIEF_COLIMA:-$(command -v colima || echo /opt/homebrew/bin/colima)}"
LIMACTL="${MEM_RELIEF_LIMACTL:-$(command -v limactl || echo /opt/homebrew/bin/limactl)}"
KILL="${MEM_RELIEF_KILL:-kill}"
AGENT_MSG="${MEM_RELIEF_AGENT_MSG:-$HERE/agent-msg.sh}"
DRY="${MEM_RELIEF_DRY:-0}"
RENDER_GATE="${MEM_RELIEF_RENDER_GATE:-1}"

mkdir -p "$STORE" 2>/dev/null
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >>"$LOG" 2>/dev/null; }
now() { echo "${MEM_RELIEF_NOW:-$(date +%s)}"; }

swap_mb() {
  local v="${MEM_RELIEF_SWAP_MB:-}"
  [[ -n "$v" ]] || v="$(/usr/sbin/sysctl -n vm.swapusage 2>/dev/null | sed -n 's/.*used = \([0-9]*\)[.0-9]*M.*/\1/p')"
  [[ "$v" =~ ^[0-9]+$ ]] && echo "$v" || echo 0
}
ps_snapshot() { if [[ -n "${MEM_RELIEF_PS:-}" ]]; then cat "$MEM_RELIEF_PS" 2>/dev/null; else ps -axo pid=,ppid=,command= 2>/dev/null; fi; }
culprits() { python3 -I "$HERE/swap-culprits.py" ${MEM_RELIEF_PS:+--ps "$MEM_RELIEF_PS"} ${MEM_RELIEF_TOP:+--top "$MEM_RELIEF_TOP"} \
  --decoder-gb "$DECODER_GB" --large-gb "$LARGE_GB" 2>/dev/null; }

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

# SIGTERM to the given pids, SIGKILL to what is left after KILL_WAIT s.
stop_pids() {
  local p w=0 alive=1
  for p in "$@"; do "$KILL" -TERM "$p" 2>/dev/null; done
  while (( w < KILL_WAIT )); do
    alive=0; for p in "$@"; do "$KILL" -0 "$p" 2>/dev/null && alive=1; done
    (( alive )) || break
    sleep 1; w=$((w + 1))
  done
  if (( alive )); then for p in "$@"; do "$KILL" -KILL "$p" 2>/dev/null; done; sleep 1; fi
  # Viktor 26868 LOW-1: say so when a pid survives (EPERM, or alive even after KILL).
  for p in "$@"; do "$KILL" -0 "$p" 2>/dev/null && return 1; done
  return 0
}

# Viktor 26868 LOW-2: right before the signal, the pid must still run the expected program (argv0
# ends with /<name>) in a FRESH snapshot: the ps and top passes are seconds old by now (the dev
# servers take up to 10 s each), and a pid can be reused.
argv0_is() {
  local c
  c="$(ps_snapshot | awk -v p="$1" '$1==p {print $3; exit}')"
  [[ "$c" == */"$2" ]]
}

# Is agent-<id> idle? An empty prompt in the pane (as scripts/idle-check.py reads it) and nothing
# busy under the pane (CPU >= IDLE_CPU %, from a `ps` snapshot with %cpu).
pane_idle() {
  local pane last
  # "=agent-<id>:" = exactly that session (Viktor 26889 INFO-2: a bare name also matches a prefix).
  pane="$("$TMUX_BIN" capture-pane -p -t "=agent-$1:" 2>/dev/null)" || return 1
  [[ -n "$pane" ]] || return 1
  echo "$pane" | grep -qE 'esc to interrupt|to interrupt\)' && return 1
  # Claude Code draws the prompt as "❯" + a no-break space (U+00A0, measured 2026-11-04 on agent-juro);
  # [[:space:]] does not match it, Python's strip() in idle-check.py does.
  last="$(echo "$pane" | sed $'s/\xc2\xa0/ /g' | grep -v '^[[:space:]]*$' | tail -4)"
  echo "$last" | grep -qx '[[:space:]]*❯[[:space:]]*' || return 1
  return 0
}
pane_busy() {
  local root p
  root="$("$TMUX_BIN" display-message -p -t "=agent-$1:" '#{pane_pid}' 2>/dev/null)"
  [[ "$root" =~ ^[0-9]+$ ]] || return 0   # unknown = busy: never restart blind
  for p in $(PSDATA="$PSCPU" descendants "$root" | sort -u); do
    [[ "$p" == "$root" ]] && continue
    # Busy: CPU at or over the limit, or a Bash tool call of the agent still running (Claude Code runs
    # each one as a shell sourcing .claude-config/shell-snapshots/snapshot-*; a background wait on a
    # remote job sleeps at 0% CPU and would be cut off by the restart).
    echo "$PSCPU" | awk -v p="$p" -v lim="$IDLE_CPU" '$1==p && ($3+0 >= lim || /shell-snapshots\/snapshot-/) {f=1} END{exit !f}' && return 0
  done
  return 1
}
# The dashboard token goes to curl on stdin (-K -), not on its command line, where ps would show it
# (Viktor 26889 INFO-1).
dash() {
  local tok; tok="$(cat "$STORE/.dashboard-token" 2>/dev/null)"
  [[ -n "$tok" ]] || return 1
  printf 'header = "Authorization: Bearer %s"\n' "$tok" | curl -s -f -m 60 -K - "$@"
}
restart_agent() {
  if [[ -n "${MEM_RELIEF_RESTART:-}" ]]; then "$MEM_RELIEF_RESTART" "$1"; return; fi
  dash -X POST "http://localhost:${MEM_RELIEF_PORT:-3420}/api/agents/$1/restart" \
    -H "Content-Type: application/json" --data-binary '{}' >/dev/null
}
# How many messages to <id> are undelivered, or were delivered in the last 15 min. Unreadable = 1
# (busy: never restart blind).
fresh_inbox() {
  if [[ -n "${MEM_RELIEF_INBOX:-}" ]]; then "$MEM_RELIEF_INBOX" "$1"; return; fi
  dash "http://localhost:${MEM_RELIEF_PORT:-3420}/api/messages?agent=$1&limit=200" 2>/dev/null | python3 -I -c '
import json, sys, time
try:
    d = json.load(sys.stdin); d = d if isinstance(d, list) else d.get("messages", [])
except Exception:
    print(1); sys.exit()
t = time.time()
print(sum(1 for m in d if m.get("to_agent") == sys.argv[1] and (m.get("status") == "pending"
      or (m.get("status") == "delivered" and t - (m.get("delivered_at") or m.get("created_at") or 0) < 900))))' "$1" 2>/dev/null || echo 1
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

# 0. The heavy-process gate (see the header): every pass, before and apart from the memory trigger.
ungated_now() {
  python3 -I "$HERE/swap-culprits.py" --ungated-heavy ${MEM_RELIEF_PS:+--ps "$MEM_RELIEF_PS"} 2>/dev/null
}
render_gate() {
  [[ "$RENDER_GATE" == "1" ]] || return 0
  local list who pid what pids rc=0 stopped=() owners="" main="" from msg to
  list="$(ungated_now)"
  [[ -n "$list" ]] || return 0
  PSDATA="$(ps_snapshot)"
  while IFS=$'\t' read -r who pid what; do
    [[ "$pid" =~ ^[0-9]+$ ]] || continue
    if [[ "$DRY" == "1" ]]; then log "DRY would stop $what pid=$pid owner=$who"; continue; fi
    # Viktor 26868 LOW-2, as for the decoder: a fresh snapshot right before the signal (pid reuse).
    if ! ungated_now | awk -F'\t' -v p="$pid" '$2==p{f=1} END{exit !f}'; then log "SKIP $what pid=$pid: no longer an ungated heavy process"; continue; fi
    pids="$(descendants "$pid" | sort -u | tr '\n' ' ')"
    # shellcheck disable=SC2086
    if stop_pids $pids; then log "STOP $what owner=$who pids=$pids"; stopped+=("${what#ungated } pid $pid ($who)")
    else log "FAIL $what owner=$who pids=$pids: still alive after KILL"; rc=1; stopped+=("${what#ungated } pid $pid ($who, NEM sikerült leállítani)"); fi
    owners+=" $who"
  done <<< "$list"
  (( ${#stopped[@]} )) || return "$rc"
  [[ -f "$INSTALL_DIR/.env" ]] && main="$(grep -E '^MAIN_AGENT_ID=' "$INSTALL_DIR/.env" | head -1 | cut -d= -f2- | tr -d '"'"'"'\r')"
  from="${MEM_RELIEF_FROM:-$main}"
  [[ -n "$from" ]] || { log "TELL nobody: no sender id (MAIN_AGENT_ID)"; return "$rc"; }
  msg="[MEM-RELIEF] Nehéz folyamat heavy-job nélkül futott, leállítottam: $(printf '%s; ' "${stopped[@]}" | sed 's/; $//'). Blender, ffmpeg és mflux csak a kapun át indulhat: bash /Users/klodel/marveen/scripts/heavy-job.sh --name <név> --kill-below 12 -- <a parancs>. Így egyszerre egy nehéz futás megy, csak szabad memóriával, és a memória-őr megállítja, mielőtt a gép elfogy (kernel panic 2026-11-09 15:19: két kapu nélküli Blender). Fájlhoz nem nyúltam."
  # Viktor 34374 LOW-2: a process restarted every minute must not mean a message every minute. One gate message
  # per recipient per GATE_TELL_GAP; the stop itself is never rate-limited, only the message.
  local stamp last
  for to in $(echo "$owners $main" | tr ' ' '\n' | awk 'NF && $0!="-" && !s[$0]++'); do
    stamp="$STORE/.mem-relief.gate-tell.$(printf %s "$to" | tr -c 'A-Za-z0-9_-' '_')"
    last="$(cat "$stamp" 2>/dev/null)"; [[ "$last" =~ ^[0-9]+$ ]] || last=0
    if (( $(now) - last < GATE_TELL_GAP )); then log "TELL $to suppressed (gate message within ${GATE_TELL_GAP}s)"; continue; fi
    if echo "$msg" | bash "$AGENT_MSG" "$from" "$to" - >/dev/null 2>&1; then log "TELL $to"; now > "$stamp"
    else log "TELL $to FAILED"; fi
  done
  return "$rc"
}

main() {
  local why last list rc=0 done_lines=() large_lines=() owners=""
  why="$(trigger)"
  [[ -n "$why" ]] || return 0
  last="$(cat "$STAMP" 2>/dev/null)"; [[ "$last" =~ ^[0-9]+$ ]] || last=0
  if (( $(now) - last < COOLDOWN )); then log "SKIP cooldown ($why)"; return 0; fi
  PSDATA="$(ps_snapshot)"
  KEPT="$(kept_ports)"
  list="$(culprits)"
  local dl=""; [[ "$DRY" == "1" ]] && dl=" dry"
  log "ACT${dl} ($why) suspects=$(echo "$list" | grep -c . )"

  # 0b. The largest heavy process, gated or not (Klodel 34318: "ha a memória kritikusra fogy, a kapu állítsa le a
  # legnagyobbat, mielőtt a gép befagy"). Only the largest one: the others may finish once it is gone.
  local hv hwho hpid hwhat hpids
  hv="$(python3 -I "$HERE/swap-culprits.py" --heavy ${MEM_RELIEF_PS:+--ps "$MEM_RELIEF_PS"} ${MEM_RELIEF_TOP:+--top "$MEM_RELIEF_TOP"} 2>/dev/null | head -1)"
  if [[ -n "$hv" ]]; then
    IFS=$'\t' read -r hwho hpid hwhat <<< "$hv"
    if [[ "$DRY" == "1" ]]; then done_lines+=("$hwhat (dry)"); owners+=" $hwho"
    else
      hpids="$(descendants "$hpid" | sort -u | tr '\n' ' ')"
      # shellcheck disable=SC2086
      if stop_pids $hpids; then log "STOP largest $hwhat owner=$hwho pids=$hpids"; done_lines+=("a legnagyobb nehéz folyamat: $hwhat (pid $hpid, $hwho)")
      else log "FAIL largest $hwhat owner=$hwho pids=$hpids: still alive after KILL"; rc=1; done_lines+=("$hwhat (pid $hpid, NEM sikerült leállítani)"); fi
      owners+=" $hwho"
    fi
  fi

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
    # shellcheck disable=SC2086
    if stop_pids $pids; then log "STOP $what owner=$who pids=$pids"; done_lines+=("$what")
    else log "FAIL $what owner=$who pids=$pids: still alive after KILL"; rc=1; done_lines+=("$what (NEM sikerült leállítani)"); fi
    owners+=" $who"
  done <<< "$list"

  # 2b. The macOS leak (the Aerial wallpaper first: it is the decoder's client), and the large ones.
  while IFS=$'\t' read -r who pid what; do
    case "$what" in
      "Aerial wallpaper"|"video decoder "*)
        if [[ "$DRY" == "1" ]]; then done_lines+=("$what (dry)"); continue; fi
        local want=VTDecoderXPCService; [[ "$what" == "Aerial wallpaper" ]] && want=WallpaperAerialsExtension
        if ! argv0_is "$pid" "$want"; then log "SKIP $what pid=$pid: no longer $want"; continue; fi
        if stop_pids "$pid"; then log "STOP $what pid=$pid"; done_lines+=("$what")
        else log "FAIL $what pid=$pid: still alive after KILL"; rc=1; done_lines+=("$what (NEM sikerült leállítani)"); fi ;;
      "large "*)
        log "LARGE $what owner=$who pid=$pid (not stopped)"
        large_lines+=("$what (pid $pid, ${who})"); owners+=" $who" ;;
    esac
  done <<< "$(echo "$list" | awk -F'\t' '$3=="Aerial wallpaper"' ; echo "$list" | awk -F'\t' '$3!="Aerial wallpaper"')"

  # 2c. Idle agents, only when nothing above was stopped and the swap is still high.
  local restarted=() mb a n=0 main_id=""
  mb="$(swap_mb)"
  [[ -f "$INSTALL_DIR/.env" ]] && main_id="$(grep -E '^MAIN_AGENT_ID=' "$INSTALL_DIR/.env" | head -1 | cut -d= -f2- | tr -d '"'"'"'\r')"
  local t day used=0 lastmb lastt
  t="$(now)"; day="$(date -r "$t" +%F 2>/dev/null || date +%F)"
  [[ "$(cut -d' ' -f1 "$IDLE_DIR/day" 2>/dev/null)" == "$day" ]] && used="$(cut -d' ' -f2 "$IDLE_DIR/day" 2>/dev/null)"
  [[ "$used" =~ ^[0-9]+$ ]] || used=0
  { read -r lastt lastmb < "$IDLE_DIR/last-round"; } 2>/dev/null || true
  if (( ${#done_lines[@]} == 0 && mb > IDLE_SWAP_GB * 1024 )) && [[ "${lastt:-}" =~ ^[0-9]+$ && "${lastmb:-}" =~ ^[0-9]+$ ]] \
     && (( t - lastt < IDLE_GAP && mb >= lastmb )); then
    log "IDLE-SKIP the swap did not drop since the last round (${lastmb} MB -> ${mb} MB)"
  elif (( ${#done_lines[@]} == 0 && mb > IDLE_SWAP_GB * 1024 && used >= IDLE_DAY_MAX )); then
    log "IDLE-SKIP the daily limit (${IDLE_DAY_MAX} restarts) is reached"
  elif (( ${#done_lines[@]} == 0 && mb > IDLE_SWAP_GB * 1024 )); then
    if [[ -n "${MEM_RELIEF_PSCPU:-}" ]]; then PSCPU="$(cat "$MEM_RELIEF_PSCPU" 2>/dev/null)"; else PSCPU="$(ps -axo pid=,ppid=,%cpu=,command= 2>/dev/null)"; fi
    for a in $("$TMUX_BIN" ls -F '#{session_name}' 2>/dev/null | sed -n 's/^agent-\([a-z0-9_-]*\)$/\1/p'); do
      (( n < IDLE_MAX && used + n < IDLE_DAY_MAX )) || break
      [[ "$a" == "$main_id" ]] && continue
      [[ " $IDLE_SKIP " == *" $a "* ]] && continue
      local la; la="$(cat "$IDLE_DIR/id-$a" 2>/dev/null)"
      if [[ "$la" =~ ^[0-9]+$ ]] && (( t - la < IDLE_GAP )); then log "IDLE-KEEP $a (restarted $(( (t - la) / 60 )) min ago)"; continue; fi
      pane_idle "$a" || continue
      if pane_busy "$a"; then log "IDLE-KEEP $a (a process under the pane is busy)"; continue; fi
      if [[ "$(fresh_inbox "$a")" != "0" ]]; then log "IDLE-KEEP $a (a message is pending or just delivered)"; continue; fi
      if [[ "$DRY" == "1" ]]; then n=$((n + 1)); restarted+=("$a (dry)"); continue; fi
      # The limits first, the restart after: a state that cannot be written stops the round.
      if ! { mkdir -p "$IDLE_DIR" && echo "$t" > "$IDLE_DIR/id-$a" && echo "$day $(( used + n + 1 ))" > "$IDLE_DIR/day" \
             && echo "$t $mb" > "$IDLE_DIR/last-round"; } 2>/dev/null; then
        log "IDLE-SKIP cannot write the restart state in $IDLE_DIR: no restart"; rc=1; break
      fi
      n=$((n + 1))
      if restart_agent "$a"; then log "RESTART idle agent $a"; restarted+=("$a")
      else log "FAIL restart idle agent $a"; rc=1; fi
    done
    (( ${#restarted[@]} )) && done_lines+=("tétlen ágens újraindítva: $(printf '%s, ' "${restarted[@]}" | sed 's/, $//')")
  fi

  # Only a real pass starts the cooldown (MEM_RELIEF_DRY above).
  [[ "$DRY" == "1" ]] || now >"$STAMP"
  (( ${#done_lines[@]} )) || log "NOTHING to stop ($why)"
  (( ${#done_lines[@]} + ${#large_lines[@]} )) || return "$rc"

  # 3. Tell the owners and the main agent.
  local main="" from to msg stopped large
  [[ -f "$INSTALL_DIR/.env" ]] && main="$(grep -E '^MAIN_AGENT_ID=' "$INSTALL_DIR/.env" | head -1 | cut -d= -f2- | tr -d '"'"'"'\r')"
  from="${MEM_RELIEF_FROM:-$main}"
  stopped=""; (( ${#done_lines[@]} )) && { stopped="$(printf '%s; ' "${done_lines[@]}")"; stopped="${stopped%; }"; }
  if (( ${#done_lines[@]} )); then
    msg="[MEM-RELIEF] A gép a memória-határon volt (${why}), ezért leállítottam: ${stopped}. Fájlhoz nem nyúltam; colima start / npm run dev visszahozza, de csak ha a swap és a lemez rendben van. Ha egy szervernek mégis futnia kell, kérj kivételt Klodeltől (store/dev-keep.list, legfeljebb 8 óra, legfeljebb 2 port)."
    echo "$stopped" | grep -qE 'Aerial wallpaper|video decoder' && msg+=" A videódekódert és az Aerial háttérképet a macOS újraindítja, ha kell; statikus háttérkép mellett az Aerial nem jön vissza."
  else
    msg="[MEM-RELIEF] A gép a memória-határon van (${why}), és nem találtam ismert, leállítható tettest."
  fi
  if (( ${#large_lines[@]} )); then
    large="$(printf '%s; ' "${large_lines[@]}")"; large="${large%; }"
    msg+=" Nagy memóriájú folyamat (NEM állítottam le, a gazdája döntsön): ${large}."
  fi
  [[ "$DRY" == "1" && -n "$stopped" ]] && log "DRY would stop: ${stopped}"
  [[ "$DRY" == "1" ]] && { log "DRY would tell:$(echo "$owners $main" | tr ' ' '\n' | awk 'NF && $0!="-" && !s[$0]++{printf " %s",$0}')"; return "$rc"; }
  [[ -n "$from" ]] || { log "TELL nobody: no sender id (MAIN_AGENT_ID)"; return "$rc"; }
  for to in $(echo "$owners $main" | tr ' ' '\n' | awk 'NF && $0!="-" && !s[$0]++'); do
    echo "$msg" | bash "$AGENT_MSG" "$from" "$to" - >/dev/null 2>&1 && log "TELL $to" || log "TELL $to FAILED"
  done
  return "$rc"
}

render_gate; RG=$?
main; MR=$?
(( RG || MR )) && exit 1
exit 0
