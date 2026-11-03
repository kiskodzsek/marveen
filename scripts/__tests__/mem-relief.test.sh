#!/usr/bin/env bash
# MEMRELIEF1103 -- mem-relief.sh (when it acts, what it stops, whom it tells) and its launchd installer
# (card 1c58f629, Klodel 25411).
#
# colima, limactl, kill and agent-msg.sh are stubs; the process list is a `ps` fixture, the store is
# inside a sandbox. Nothing here stops a real VM, signals a real process or sends a real message.
#
# Run:  bash scripts/__tests__/mem-relief.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
MR="$ROOT/scripts/mem-relief.sh"
INST="$ROOT/scripts/install-mem-relief.sh"
for f in "$MR" "$INST"; do
  [ -e "$f" ] || { echo "FATAL: the script under test is missing: $f" >&2; exit 2; }
done

FAILS=0; DONE=0
check() { DONE=$((DONE+1)); if [ "$2" = "0" ]; then echo "PASS  $1"; else echo "FAIL  $1${3:+  -- $3}"; FAILS=$((FAILS+1)); fi; }
ok() { [ "$@" ] && echo 0 || echo 1; }

SB="$(mktemp -d "${TMPDIR:-/tmp}/memrelief.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
mkdir -p "$SB/store" "$SB/install"
echo 'MAIN_AGENT_ID="klodel"' > "$SB/install/.env"

# The process list: a Colima VM (launchd-started, no owner) and two next dev servers with a child each.
cat > "$SB/ps.base" <<'EOF'
    1     0 /sbin/launchd
  100     1 /opt/homebrew/bin/limactl hostagent --pidfile /Users/x/.colima/_lima/colima/ha.pid colima
  200     1 /bin/zsh -c source /Users/x/marveen/agents/dave/.claude-config/shell-snapshots/s.sh && cd /Users/x/marveen/agents/dave/repos/wt-a && npm run dev -- -p 3495
  201   200 node /Users/x/marveen/agents/dave/repos/wt-a/node_modules/.bin/next dev -p 3495
  202   201 next-server (v15.5.2)
  300     1 /bin/zsh -c source /Users/x/marveen/agents/kernel/.claude-config/shell-snapshots/s.sh && cd /Users/x/marveen/agents/kernel/repos/wt-b && npx next dev -p 3471
  301   300 node /Users/x/marveen/agents/kernel/repos/wt-b/node_modules/.bin/next dev -p 3471
  302   301 next-server (v15.5.2)
  400     1 claude -p please run next dev -p 3000 in the tree and report
  401   400 node /Users/x/marveen/agents/kernel/repos/wt-b/scripts/helper.js
  500     1 npm exec next dev --webpack -H localhost -p 3499
EOF

# colima / limactl stand-ins: record argv; with STUB_COLIMA_OK=1 / STUB_LIMA_OK=1 the VM leaves the ps fixture.
printf '#!/bin/bash\necho "colima $*" >> "%s/calls"\n[ "${STUB_COLIMA_OK:-1}" = 1 ] && sed -i "" "/limactl hostagent/d" "%s/ps"\nexit 0\n' "$SB" "$SB" > "$SB/colima"
printf '#!/bin/bash\necho "limactl $*" >> "%s/calls"\n[ "${STUB_LIMA_OK:-1}" = 1 ] && sed -i "" "/limactl hostagent/d" "%s/ps"\nexit 0\n' "$SB" "$SB" > "$SB/limactl"
# kill stand-in: records "kill <sig> <pid>". -0 answers from $SB/alive (rc 0 = alive); -TERM removes the pid
# from alive unless it is in $SB/stubborn; -KILL always removes it.
cat > "$SB/kill" <<STUB
#!/bin/bash
echo "kill \$1 \$2" >> "$SB/calls"
case "\$1" in
  -0) grep -qx -- "\$2" "$SB/alive" 2>/dev/null; exit \$? ;;
  -TERM) grep -qx -- "\$2" "$SB/stubborn" 2>/dev/null && exit 0 ;;
esac
grep -vx -- "\$2" "$SB/alive" > "$SB/alive.n" 2>/dev/null; mv "$SB/alive.n" "$SB/alive"; exit 0
STUB
# agent-msg.sh stand-in: records "<from> <to> <stdin>".
printf '#!/bin/bash\necho "$1 $2 $(cat)" >> "%s/msgs"\nexit 0\n' "$SB" > "$SB/agent-msg-stub"
chmod +x "$SB/colima" "$SB/limactl" "$SB/kill" "$SB/agent-msg-stub"

reset() {
  cp "$SB/ps.base" "$SB/ps"
  printf '%s\n' 200 201 202 300 301 302 > "$SB/alive"
  rm -f "$SB/calls" "$SB/msgs" "$SB/stubborn" "$SB/store/.mem-relief.last" "$SB/store/mem-relief.log" "$SB/store/dev-keep.list"
}
state() { echo "$1 $(( $(date +%s) - ${2:-0} )) $3" > "$SB/store/.host-state"; }
run() {
  OUT="$(MARVEEN_STORE="$SB/store" MEM_RELIEF_INSTALL_DIR="$SB/install" MEM_RELIEF_PS="$SB/ps" \
    MEM_RELIEF_COLIMA="$SB/colima" MEM_RELIEF_LIMACTL="$SB/limactl" MEM_RELIEF_KILL="$SB/kill" \
    MEM_RELIEF_AGENT_MSG="$SB/agent-msg-stub" MEM_RELIEF_SWAP_MB="${SWAP:-0}" MEM_RELIEF_KILL_WAIT=2 \
    MEM_RELIEF_COLIMA_WAIT=5 "$@" bash "$MR" 2>&1)"; RC=$?
}
calls() { cat "$SB/calls" 2>/dev/null; }
logf() { cat "$SB/store/mem-relief.log" 2>/dev/null; }

echo "== when it acts"
reset; state critical 10 "free memory 3%;swap 96%"; run
check "critical, fresh, memory/swap reason -> colima stop, both servers stopped, rc 0" \
  "$(ok "$RC" = 0 -a -n "$(calls | grep -x 'colima stop')" -a -n "$(calls | grep -x 'kill -TERM 201')" -a -n "$(calls | grep -x 'kill -TERM 301')")" "rc=$RC $(calls | tr '\n' ' ') $(logf)"
check "the server's descendants get the signal too (next-server child)" \
  "$(ok -n "$(calls | grep -x 'kill -TERM 202')" -a -n "$(calls | grep -x 'kill -TERM 302')")" "$(calls | tr '\n' ' ')"
check "the parent shell is not signalled (not a descendant of the server)" "$(ok -z "$(calls | grep -E 'kill -[A-Z]+ (200|300)$')")" "$(calls | tr '\n' ' ')"
check "a process that only mentions 'next dev' (claude -p ..., npm exec) and its child are not signalled (Viktor 25470 d)" "$(ok -z "$(calls | grep -E 'kill -[A-Z]+ (400|401|500)$')")" "$(calls | tr '\n' ' ')"
check "a TERM that worked needs no KILL" "$(ok -z "$(calls | grep 'kill -KILL')")" "$(calls | tr '\n' ' ')"
check "limactl -f is not needed when colima stop worked" "$(ok -z "$(calls | grep limactl)")"
check "the log says STOP for the VM and each server" \
  "$(ok "$(logf | grep -c '^.* STOP ')" = 3)" "$(logf)"

reset; state critical 10 "load 40.2 on 8 CPUs"; run
check "critical for load only -> nothing (left to the owner)" "$(ok "$RC" = 0 -a -z "$(calls)" -a ! -e "$SB/store/.mem-relief.last")" "rc=$RC $(calls)"
reset; state critical 600 "free memory 3%;swap 96%"; run
check "critical but 600 s old (host-monitor not running) -> nothing" "$(ok -z "$(calls)")" "$(calls)"
reset; state warn 10 "swap 94%"; run
check "warn band -> nothing" "$(ok -z "$(calls)")" "$(calls)"
reset; state critical 10 "free disk 1 GiB"; run
check "critical for disk (the swap lives on the same APFS container) -> acts" "$(ok -n "$(calls | grep -x 'colima stop')")" "$(calls)"
reset; rm -f "$SB/store/.host-state"; SWAP=12288 run
check "no host state, swap 12 GB > 11 GB -> acts" "$(ok -n "$(calls | grep -x 'colima stop')" -a -n "$(logf | grep 'swap 12288 MB')")" "$(logf)"
reset; SWAP=11000 run
check "no host state, swap 11000 MB (under 11 GB) -> nothing" "$(ok -z "$(calls)")" "$(calls)"

echo "== cooldown"
reset; state critical 10 "free memory 3%"; run; cp "$SB/ps.base" "$SB/ps"; rm -f "$SB/calls"; run
check "a second pass within 600 s does nothing and logs SKIP cooldown" "$(ok -z "$(calls)" -a -n "$(logf | grep 'SKIP cooldown')")" "$(calls) $(logf)"
T2=$(( $(date +%s) + 601 )); echo "critical $T2 free memory 3%" > "$SB/store/.host-state"; rm -f "$SB/calls"; run env MEM_RELIEF_NOW=$T2
check "after 600 s it acts again" "$(ok -n "$(calls | grep -x 'colima stop')")" "$(calls)"

echo "== what stays"
reset; state critical 10 "free memory 3%"; printf '# Dave print render (Klodel ok)\n 3495 until=%s \n' "$(( $(date +%s) + 3600 ))" > "$SB/store/dev-keep.list"; run
check "a port in store/dev-keep.list stays (no signal to 201/202), the other stops" \
  "$(ok -z "$(calls | grep -E 'kill -[A-Z]+ 20[12]$')" -a -n "$(calls | grep -x 'kill -TERM 301')" -a -n "$(logf | grep 'KEEP next dev :3495')")" "$(calls | tr '\n' ' ') $(logf)"
check "the kept server's owner is not told" "$(ok -z "$(grep '^klodel dave ' "$SB/msgs" 2>/dev/null)")" "$(cat "$SB/msgs" 2>/dev/null)"

for bad in "3495" "3495 until=$(( $(date +%s) - 5 ))" "3495 until=$(( $(date +%s) + 9 * 3600 ))" "3495 forever"; do
  reset; state critical 10 "free memory 3%"; echo "$bad" > "$SB/store/dev-keep.list"; run
  check "dev-keep '$bad' does not count: 3495 stops, the line is logged IGNORE" "$(ok -n "$(calls | grep -x 'kill -TERM 201')" -a -n "$(logf | grep 'IGNORE dev-keep')")" "$(calls | tr '\n' ' ') $(logf)"
done
reset; state critical 10 "free memory 3%"; U=$(( $(date +%s) + 3600 ))
printf '3000 until=%s\n3001 until=%s\n3495 until=%s\n' "$U" "$U" "$U" > "$SB/store/dev-keep.list"; run
check "only the first 2 valid lines count: the third (3495) stops, logged" "$(ok -n "$(calls | grep -x 'kill -TERM 201')" -a -n "$(logf | grep 'only 2 ports may be kept')")" "$(logf)"
reset; state critical 10 "free memory 3%"; run env MEM_RELIEF_DRY=1
check "DRY: no stop, no signal, no message, the log names what it would do" \
  "$(ok "$RC" = 0 -a -z "$(calls)" -a ! -e "$SB/msgs" -a -n "$(logf | grep 'ACT dry')" -a -n "$(logf | grep 'DRY would tell: dave kernel klodel')")" "rc=$RC $(calls) $(logf)"

reset; state critical 10 "free memory 3%"; echo 301 > "$SB/stubborn"; run
check "a server that ignores TERM gets KILL after the wait" "$(ok -n "$(calls | grep -x 'kill -KILL 301')" -a -z "$(calls | grep -x 'kill -KILL 201')")" "$(calls | tr '\n' ' ')"

reset; state critical 10 "free memory 3%"; run env STUB_COLIMA_OK=0
check "colima stop leaves the VM up -> limactl stop -f colima" "$(ok -n "$(calls | grep -x 'limactl stop -f colima')" -a "$RC" = 0)" "rc=$RC $(calls)"
reset; state critical 10 "free memory 3%"; run env STUB_COLIMA_OK=0 STUB_LIMA_OK=0
check "the VM survives both -> FAIL in the log, rc 1, the servers still stop" \
  "$(ok "$RC" = 1 -a -n "$(logf | grep 'FAIL Colima VM still up')" -a -n "$(calls | grep -x 'kill -TERM 201')")" "rc=$RC $(logf)"

echo "== whom it tells"
reset; state critical 10 "free memory 3%"; run
check "one message to each owner and the main agent, from the main agent (as daily-cleanup and backup.sh send)" \
  "$(ok "$(grep -c . "$SB/msgs")" = 3 -a -n "$(grep '^klodel klodel \[MEM-RELIEF\]' "$SB/msgs")" -a -n "$(grep '^klodel dave \[MEM-RELIEF\]' "$SB/msgs")" -a -n "$(grep '^klodel kernel \[MEM-RELIEF\]' "$SB/msgs")")" "$(cat "$SB/msgs")"
check "the owner-less VM sends nothing to \"-\"" "$(ok -z "$(grep -E '^klodel - ' "$SB/msgs")")" "$(cat "$SB/msgs")"
check "the message names what was stopped and why" \
  "$(ok -n "$(grep 'Colima VM; next dev :3495' "$SB/msgs" | grep 'host-monitor critical: free memory 3%' | grep 'kérj kivételt Klodeltől')")" "$(head -1 "$SB/msgs")"
check "no file outside the store was touched: the fixture tree has only the store files" \
  "$(ok "$(cd "$SB/store" && ls -A | sort | tr '\n' ' ')" = ".host-state .mem-relief.last mem-relief.log ")" "$(ls -A "$SB/store")"

reset; printf '    1     0 /sbin/launchd\n' > "$SB/ps"; state critical 10 "free memory 3%"; run
check "nothing to stop -> NOTHING in the log, no message, rc 0" "$(ok "$RC" = 0 -a ! -e "$SB/msgs" -a -n "$(logf | grep NOTHING)")" "rc=$RC $(logf)"

echo "== installer"
PL="$SB/la/com.marveen.mem-relief.plist"
OUT="$(MEM_RELIEF_LAUNCH_AGENTS="$SB/la" bash "$INST" 2>&1)"; RC=$?
check "writes the plist, does not load it" "$(ok "$RC" = 0 -a -f "$PL" -a -n "$(echo "$OUT" | grep -i 'not loaded')")" "rc=$RC $OUT"
check "plist: label, every 60 s, RunAtLoad, runs scripts/mem-relief.sh" \
  "$(ok -n "$(grep -A1 'StartInterval' "$PL" | grep '<integer>60</integer>')" -a -n "$(grep -A1 'RunAtLoad' "$PL" | grep true)" -a -n "$(grep 'com.marveen.mem-relief' "$PL")" -a -n "$(grep "$ROOT/scripts/mem-relief.sh" "$PL")")"
check "plist is valid" "$(plutil -lint "$PL" >/dev/null 2>&1; echo $?)"

echo
echo "$DONE checks, $FAILS failed"
[ "$FAILS" = 0 ]
