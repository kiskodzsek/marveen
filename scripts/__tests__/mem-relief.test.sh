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
check "DRY: no cooldown stamp is written (Viktor 25498)" "$(ok ! -e "$SB/store/.mem-relief.last")" "$(ls -A "$SB/store")"
rm -f "$SB/calls"; run
check "a real pass right after a DRY one acts (no SKIP cooldown)" \
  "$(ok -n "$(calls | grep -x 'colima stop')" -a -z "$(logf | grep 'SKIP cooldown')" -a -e "$SB/store/.mem-relief.last")" "$(calls | tr '\n' ' ') $(logf)"
reset; state critical 10 "free memory 3%"; echo 1000 > "$SB/store/.mem-relief.last"; run env MEM_RELIEF_DRY=1
check "DRY leaves an older stamp as it was" "$(ok "$(cat "$SB/store/.mem-relief.last")" = 1000 -a -n "$(logf | grep 'ACT dry')")" "$(cat "$SB/store/.mem-relief.last") $(logf)"

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

echo "== macOS leak by footprint (2026-11-04: VTDecoderXPCService 44 GB, client the Aerial wallpaper)"
# No VM and no dev server: only the decoder, its client, a large agent process and a small one.
cat > "$SB/ps.leak" <<'EOF2'
    1     0 /sbin/launchd
  728     1 /System/Library/ExtensionKit/Extensions/WallpaperAerialsExtension.appex/Contents/MacOS/WallpaperAerialsExtension -BSServiceDomains {}
40542     1 /System/Library/Frameworks/VideoToolbox.framework/Versions/A/XPCServices/VTDecoderXPCService.xpc/Contents/MacOS/VTDecoderXPCService
  900     1 /opt/homebrew/bin/claude --model x
  901   900 /bin/zsh -c cd /Users/x/marveen/agents/dave/work && python3 render.py
  950     1 /usr/bin/small-tool
EOF2
printf 'PID    MEM\n0      45G\n40542  44G\n728    120M\n901    7012M+\n950    3G\n' > "$SB/top.leak"
leak() { cp "$SB/ps.leak" "$SB/ps"; printf '%s\n' 728 40542 901 950 > "$SB/alive"; rm -f "$SB/calls" "$SB/msgs" "$SB/store/.mem-relief.last" "$SB/store/mem-relief.log"; }
leak; rm -f "$SB/store/.host-state"; SWAP=23000 run env MEM_RELIEF_TOP="$SB/top.leak"
check "swap 23 GB, decoder 44 GB -> the Aerial wallpaper and the decoder get TERM, rc 0" \
  "$(ok "$RC" = 0 -a -n "$(calls | grep -x 'kill -TERM 728')" -a -n "$(calls | grep -x 'kill -TERM 40542')")" "rc=$RC $(calls | tr '\n' ' ') $(logf)"
check "the Aerial wallpaper (the client) is stopped before the decoder" \
  "$(ok "$(calls | grep -n 'kill -TERM' | head -1 | cut -d: -f2)" = "kill -TERM 728")" "$(calls | tr '\n' ' ')"
check "a large process (7 GB) is NOT signalled, it is logged LARGE and named in the message" \
  "$(ok -z "$(calls | grep -E 'kill -[A-Z]+ 90[01]$')" -a -n "$(logf | grep 'LARGE large zsh 6.8 GB owner=dave pid=901')" -a -n "$(grep 'NEM állítottam le' "$SB/msgs" | grep 'large zsh 6.8 GB (pid 901, dave)')")" "$(calls | tr '\n' ' ') $(logf) $(cat "$SB/msgs" 2>/dev/null)"
check "a small process (3 GB) and pid 0 (kernel_task) are not touched or named" \
  "$(ok -z "$(calls | grep -E 'kill -[A-Z]+ (950|0)$')" -a -z "$(grep -E 'small-tool|pid 0' "$SB/msgs")")" "$(calls | tr '\n' ' ')"
check "the large process's owner and the main agent are told, nobody else" \
  "$(ok "$(grep -c . "$SB/msgs")" = 2 -a -n "$(grep '^klodel dave ' "$SB/msgs")" -a -n "$(grep '^klodel klodel ' "$SB/msgs")")" "$(cat "$SB/msgs")"
check "the message names the stop and says macOS starts them again" \
  "$(ok -n "$(grep 'leállítottam: Aerial wallpaper; video decoder 44.0 GB' "$SB/msgs" | grep 'macOS újraindítja')")" "$(head -1 "$SB/msgs")"

leak; printf 'PID    MEM\n40542  3G\n728    120M\n' > "$SB/top.small"; SWAP=23000 run env MEM_RELIEF_TOP="$SB/top.small"
check "a decoder under 4 GB is left alone (only the Aerial wallpaper stops)" \
  "$(ok -z "$(calls | grep -E 'kill -[A-Z]+ 40542$')" -a -n "$(calls | grep -x 'kill -TERM 728')")" "$(calls | tr '\n' ' ')"

leak; grep -v -e WallpaperAerials -e VTDecoder "$SB/ps.leak" > "$SB/ps"; SWAP=23000 run env MEM_RELIEF_TOP="$SB/top.leak"
check "only a large process: nothing is stopped, NOTHING + LARGE in the log, an alert still goes out" \
  "$(ok -z "$(calls | grep 'kill -TERM')" -a -n "$(logf | grep NOTHING)" -a -n "$(logf | grep LARGE)" -a -n "$(grep 'nem találtam ismert, leállítható tettest' "$SB/msgs" | grep 'pid 901')")" "$(calls | tr '\n' ' ') $(logf) $(cat "$SB/msgs" 2>/dev/null)"

leak; SWAP=23000 run env MEM_RELIEF_TOP="$SB/top.leak" MEM_RELIEF_DRY=1
check "DRY: the leak is named, nothing is signalled, no message" \
  "$(ok -z "$(calls | grep 'kill -TERM')" -a ! -e "$SB/msgs" -a -n "$(logf | grep 'DRY would stop: Aerial wallpaper (dry); video decoder 44.0 GB (dry)')")" "$(logf)"

leak; SWAP=23000 run
check "a ps fixture without MEM_RELIEF_TOP reads no live footprint: only the Aerial wallpaper (by name)" \
  "$(ok -n "$(calls | grep -x 'kill -TERM 728')" -a -z "$(calls | grep -E 'kill -[A-Z]+ (40542|901)$')")" "$(calls | tr '\n' ' ')"

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
