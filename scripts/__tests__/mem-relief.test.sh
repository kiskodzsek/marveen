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
  -KILL) grep -qx -- "\$2" "$SB/immortal" 2>/dev/null && exit 1 ;;
esac
# With \$SB/reuse-40542: once the Aerial wallpaper (728) is signalled, pid 40542 runs another program.
[ "\$1 \$2" = "-TERM 728" ] && [ -f "$SB/reuse-40542" ] && sed -i '' 's#^40542 .*#40542     1 /usr/bin/some-new-process#' "$SB/ps"
grep -vx -- "\$2" "$SB/alive" > "$SB/alive.n" 2>/dev/null; mv "$SB/alive.n" "$SB/alive"; exit 0
STUB
# agent-msg.sh stand-in: records "<from> <to> <stdin>".
printf '#!/bin/bash\necho "$1 $2 $(cat)" >> "%s/msgs"\nexit 0\n' "$SB" > "$SB/agent-msg-stub"
# tmux stand-in: sessions from $SB/tmux.sessions, a pane's text from $SB/pane-<id>, its pid from $SB/panepid-<id>.
# Only the exact target form "=agent-<id>:" answers (Viktor 26889 INFO-2); every target is recorded.
cat > "$SB/tmux" <<STUB
#!/bin/bash
[ -n "\${4:-}" ] && echo "tmux-target \$4" >> "$SB/targets"
case "\$4" in =agent-*:) id="\${4#=agent-}"; id="\${id%:}" ;; *) id="" ;; esac
case "\$1" in
  ls) cat "$SB/tmux.sessions" 2>/dev/null ;;
  capture-pane) [ -n "\$id" ] && cat "$SB/pane-\$id" 2>/dev/null ;;
  display-message) [ -n "\$id" ] && cat "$SB/panepid-\$id" 2>/dev/null ;;
esac
exit 0
STUB
# inbox stand-in: the count of fresh messages to <id> from $SB/inbox-<id>, 0 by default.
printf '#!/bin/bash\ncat "%s/inbox-$1" 2>/dev/null || echo 0\n' "$SB" > "$SB/inbox-stub"
# restart stand-in: records "restart <id>".
printf '#!/bin/bash\necho "restart $1" >> "%s/calls"\n' "$SB" > "$SB/restart-stub"
chmod +x "$SB/colima" "$SB/limactl" "$SB/kill" "$SB/agent-msg-stub" "$SB/tmux" "$SB/restart-stub" "$SB/inbox-stub"

reset() {
  cp "$SB/ps.base" "$SB/ps"
  printf '%s\n' 200 201 202 300 301 302 > "$SB/alive"
  rm -f "$SB/calls" "$SB/msgs" "$SB/stubborn" "$SB/store/.mem-relief.last" "$SB/store/mem-relief.log" "$SB/store/dev-keep.list"
}
state() { echo "$1 $(( $(date +%s) - ${2:-0} )) $3" > "$SB/store/.host-state"; }
run() {
  OUT="$(MARVEEN_STORE="$SB/store" MEM_RELIEF_INSTALL_DIR="$SB/install" MEM_RELIEF_PS="$SB/ps" \
    MEM_RELIEF_COLIMA="$SB/colima" MEM_RELIEF_LIMACTL="$SB/limactl" MEM_RELIEF_KILL="$SB/kill" \
    MEM_RELIEF_AGENT_MSG="$SB/agent-msg-stub" MEM_RELIEF_TMUX="$SB/tmux" MEM_RELIEF_RESTART="$SB/restart-stub" \
    MEM_RELIEF_PSCPU="$SB/pscpu" MEM_RELIEF_INBOX="$SB/inbox-stub" MEM_RELIEF_SWAP_MB="${SWAP:-0}" MEM_RELIEF_KILL_WAIT=2 \
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

echo "== Viktor 26868: verify before the signal, report a survivor, plain names, argv0 only"
leak; rm -f "$SB/immortal"; printf '%s\n' 40542 > "$SB/stubborn"; printf '%s\n' 40542 > "$SB/immortal"; SWAP=23000 run env MEM_RELIEF_TOP="$SB/top.leak"
check "LOW-1: a decoder alive even after KILL -> FAIL in the log, rc 1, the message says it did not stop" \
  "$(ok "$RC" = 1 -a -n "$(logf | grep 'FAIL video decoder 44.0 GB pid=40542: still alive after KILL')" -a -n "$(grep 'video decoder 44.0 GB (NEM sikerült leállítani)' "$SB/msgs")" -a -z "$(logf | grep 'STOP video decoder')")" "rc=$RC $(logf) $(cat "$SB/msgs" 2>/dev/null)"
rm -f "$SB/stubborn" "$SB/immortal"
leak; touch "$SB/reuse-40542"; SWAP=23000 run env MEM_RELIEF_TOP="$SB/top.leak"; rm -f "$SB/reuse-40542"
check "LOW-2: found as the decoder, but another program by the time the signal is due -> SKIP, no signal" \
  "$(ok -z "$(calls | grep -E 'kill -[A-Z]+ 40542$')" -a -n "$(calls | grep -x 'kill -TERM 728')" -a -n "$(logf | grep 'SKIP video decoder 44.0 GB pid=40542: no longer VTDecoderXPCService')")" "$(calls | tr '\n' ' ') $(logf)"
leak; printf '  910     1 /tmp/x/evil$(id)name`whoami`;rm -rf ~ --with-a-very-long-tail-of-characters-to-cut\n' >> "$SB/ps"; printf '910    9G\n' >> "$SB/top.leak"; SWAP=23000 run env MEM_RELIEF_TOP="$SB/top.leak"
check "LOW-3: a large process name reaches the message only as [A-Za-z0-9._-]" \
  "$(ok -n "$(grep 'large evil__id_name_whoami__rm 9.0 GB (pid 910' "$SB/msgs")" -a -z "$(grep -F '$(id)' "$SB/msgs")")" "$(cat "$SB/msgs" 2>/dev/null)"
leak; printf '  920     1 /usr/bin/grep /WallpaperAerialsExtension -r /System\n' >> "$SB/ps"; SWAP=23000 run env MEM_RELIEF_TOP="$SB/top.leak"
check "INFO-1: a process that only names WallpaperAerialsExtension in its arguments is not the Aerial wallpaper" \
  "$(ok -z "$(calls | grep -E 'kill -[A-Z]+ 920$')" -a -n "$(calls | grep -x 'kill -TERM 728')")" "$(calls | tr '\n' ' ')"

echo "== idle agents (2c: nothing known to stop, swap over 12 GB; Klodel 26862)"
idle() {
  printf '    1     0 /sbin/launchd\n' > "$SB/ps"; : > "$SB/alive"
  rm -f "$SB/calls" "$SB/msgs" "$SB/store/.mem-relief.last" "$SB/store/mem-relief.log" "$SB/store/.host-state" "$SB/targets"; find "$SB" -maxdepth 1 -name 'inbox-*' ! -name inbox-stub -delete
  rm -rf "$SB/store/.mem-relief-idle"
  printf 'agent-juro\nagent-dave\nagent-klodel\nagent-radar\nagent-lex\nagent-mira\nagent-viktor\nklodel-channels\n' > "$SB/tmux.sessions"
  for a in juro dave klodel radar lex mira viktor; do printf 'done.\n\xe2\x94\x80\xe2\x94\x80\n\xe2\x9d\xaf\xc2\xa0\n\xe2\x94\x80\xe2\x94\x80\n  bypass permissions on\n' > "$SB/pane-$a"; done
  printf 'working\n✻ Rendering… (esc to interrupt)\n\xe2\x9d\xaf \n' > "$SB/pane-radar"
  i=10; for a in juro dave klodel radar lex mira viktor; do i=$((i+10)); echo "$((i*100))" > "$SB/panepid-$a"; done
  # Dave's pane (3000) runs claude (3001) and a render it started (3002, 95% CPU); the others only claude.
  cat > "$SB/pscpu" <<'EOF2'
 2000     1   0.0 -zsh
 2001  2000   4.0 /opt/homebrew/bin/claude --continue
 3000     1   0.0 -zsh
 3001  3000   3.0 /opt/homebrew/bin/claude --continue
 3002  3001  95.0 python3 render.py
 6000     1   0.0 -zsh
 6001  6000   2.0 /opt/homebrew/bin/claude --continue
 7000     1   0.0 -zsh
 7001  7000   1.0 /opt/homebrew/bin/claude --continue
 8000     1   0.0 -zsh
 8001  8000   1.0 /opt/homebrew/bin/claude --continue
 8002  8001   0.0 /bin/zsh -c source /Users/x/marveen/agents/viktor/.claude-config/shell-snapshots/snapshot-zsh-1.sh && sleep 600
EOF2
}
idle; SWAP=13000 run env MEM_RELIEF_IDLE_SKIP=""
check "swap 13 GB, nothing known to stop -> idle agents restart, at most 3" \
  "$(ok "$RC" = 0 -a "$(calls | grep -c '^restart ')" = 3)" "rc=$RC $(calls | tr '\n' ' ') $(logf)"
check "the main agent (klodel) is never restarted" "$(ok -z "$(calls | grep -x 'restart klodel')")" "$(calls | tr '\n' ' ')"
check "a busy pane (esc to interrupt) is not restarted" "$(ok -z "$(calls | grep -x 'restart radar')")" "$(calls | tr '\n' ' ')"
check "an idle prompt with a busy process under it (Dave's render, 95% CPU) is kept, IDLE-KEEP logged" \
  "$(ok -z "$(calls | grep -x 'restart dave')" -a -n "$(logf | grep 'IDLE-KEEP dave')")" "$(calls | tr '\n' ' ') $(logf)"
check "the restarted ones are juro, lex, mira (tmux order), named to the main agent only" \
  "$(ok "$(calls | grep '^restart ' | tr '\n' ' ')" = "restart juro restart lex restart mira " -a "$(grep -c . "$SB/msgs")" = 1 -a -n "$(grep '^klodel klodel .*tétlen ágens újraindítva: juro, lex, mira' "$SB/msgs")")" "$(calls | tr '\n' ' ') $(cat "$SB/msgs" 2>/dev/null)"
idle; SWAP=11500 run
check "swap 11.2 GB (over the 11 GB trigger, under 12 GB) -> no restart" "$(ok -z "$(calls | grep '^restart ')")" "$(calls | tr '\n' ' ')"
idle; SWAP=13000 run env MEM_RELIEF_IDLE_SKIP="juro lex"
check "MEM_RELIEF_IDLE_SKIP keeps the named agents; viktor is kept by its running Bash call (0% CPU)" \
  "$(ok "$(calls | grep '^restart ' | tr '\n' ' ')" = "restart mira " -a -n "$(logf | grep 'IDLE-KEEP viktor')")" "$(calls | tr '\n' ' ') $(logf)"
idle; rm -f "$SB/pscpu"; printf ' 2000     1   0.0 -zsh\n' > "$SB/pscpu"; for a in juro lex mira viktor; do echo 2000 > "$SB/panepid-$a"; done; echo 2000 > "$SB/panepid-dave"; SWAP=13000 run
check "by default dave is never restarted (MEM_RELIEF_IDLE_SKIP default), even when idle" \
  "$(ok -z "$(calls | grep -x 'restart dave')" -a -z "$(logf | grep 'IDLE-KEEP dave')" -a -n "$(calls | grep -x 'restart juro')")" "$(calls | tr '\n' ' ') $(logf)"
idle; rm -f "$SB/panepid-juro"; SWAP=13000 run env MEM_RELIEF_IDLE_MAX=1 MEM_RELIEF_IDLE_SKIP=""
check "an unknown pane pid counts as busy: juro is kept, lex restarts (IDLE_MAX 1)" "$(ok "$(calls | grep '^restart ' | tr '\n' ' ')" = "restart lex ")" "$(calls | tr '\n' ' ') $(logf)"
idle; cp "$SB/ps.base" "$SB/ps"; printf '%s\n' 200 201 202 300 301 302 > "$SB/alive"; SWAP=13000 run
check "when the VM or a dev server was stopped, no agent is restarted" "$(ok -n "$(calls | grep -x 'colima stop')" -a -z "$(calls | grep '^restart ')")" "$(calls | tr '\n' ' ')"
idle; SWAP=13000 run env MEM_RELIEF_DRY=1 MEM_RELIEF_IDLE_SKIP=""
check "DRY: no restart, the log names them" "$(ok -z "$(calls | grep '^restart ')" -a -n "$(logf | grep 'DRY would stop: tétlen ágens újraindítva: juro (dry), lex (dry), mira (dry)')")" "$(logf)"
idle; printf '#!/bin/bash\nexit 1\n' > "$SB/restart-fail"; chmod +x "$SB/restart-fail"; SWAP=13000 run env MEM_RELIEF_RESTART="$SB/restart-fail" MEM_RELIEF_IDLE_MAX=1
check "a failed restart -> FAIL in the log, rc 1" "$(ok "$RC" = 1 -a -n "$(logf | grep 'FAIL restart idle agent juro')")" "rc=$RC $(logf)"

echo "== idle-agent limits (Viktor 26889 F1, INFO-1, INFO-2)"
idle; SWAP=13000 run env MEM_RELIEF_IDLE_SKIP=""
check "INFO-2: every tmux target is the exact form =agent-<id>:" \
  "$(ok -n "$(cat "$SB/targets")" -a -z "$(grep -v '^tmux-target =agent-[a-z0-9_-]*:$' "$SB/targets")")" "$(sort -u "$SB/targets" | tr '\n' ' ')"
check "a round writes the stamps: one per restarted agent, the day count, the round's swap" \
  "$(ok -f "$SB/store/.mem-relief-idle/id-juro" -a "$(cut -d' ' -f2 "$SB/store/.mem-relief-idle/day")" = 3 -a "$(cut -d' ' -f2 "$SB/store/.mem-relief-idle/last-round")" = 13000)" "$(ls -A "$SB/store/.mem-relief-idle" 2>/dev/null | tr '\n' ' ')"
T1=$(( $(date +%s) + 700 )); rm -f "$SB/calls" "$SB/store/.mem-relief.last"; SWAP=13000 run env MEM_RELIEF_IDLE_SKIP="" MEM_RELIEF_NOW=$T1
check "F1 (c): 10 min later, the swap not lower -> no new round, IDLE-SKIP logged" \
  "$(ok -z "$(calls | grep '^restart ')" -a -n "$(logf | grep 'IDLE-SKIP the swap did not drop since the last round (13000 MB -> 13000 MB)')")" "$(calls | tr '\n' ' ') $(logf | tail -3)"
rm -f "$SB/calls" "$SB/store/.mem-relief.last"; SWAP=12800 run env MEM_RELIEF_IDLE_SKIP="" MEM_RELIEF_NOW=$T1
check "F1 (a): the swap dropped, a new round, but juro/lex/mira (restarted 11 min ago) are kept; viktor busy -> nobody" \
  "$(ok -z "$(calls | grep '^restart ')" -a -n "$(logf | grep 'IDLE-KEEP juro (restarted 11 min ago)')")" "$(calls | tr '\n' ' ') $(logf | tail -5)"
T2=$(( $(date +%s) + 21700 )); rm -f "$SB/calls" "$SB/store/.mem-relief.last"; SWAP=13000 run env MEM_RELIEF_IDLE_SKIP="" MEM_RELIEF_NOW=$T2
check "F1 (a): after 6 h the same agents may restart again" "$(ok "$(calls | grep -c '^restart ')" = 3)" "$(calls | tr '\n' ' ') $(logf | tail -3)"
idle; echo "$(date +%F) 5" > /dev/null; mkdir -p "$SB/store/.mem-relief-idle"; echo "$(date +%F) 5" > "$SB/store/.mem-relief-idle/day"; SWAP=13000 run env MEM_RELIEF_IDLE_SKIP=""
check "F1 (b): 5 of the 6 daily restarts used -> only 1 more" "$(ok "$(calls | grep -c '^restart ')" = 1 -a "$(cut -d' ' -f2 "$SB/store/.mem-relief-idle/day")" = 6)" "$(calls | tr '\n' ' ')"
idle; mkdir -p "$SB/store/.mem-relief-idle"; echo "$(date +%F) 6" > "$SB/store/.mem-relief-idle/day"; SWAP=13000 run env MEM_RELIEF_IDLE_SKIP=""
check "F1 (b): the daily limit reached -> no restart, IDLE-SKIP logged" "$(ok -z "$(calls | grep '^restart ')" -a -n "$(logf | grep 'IDLE-SKIP the daily limit')")" "$(calls | tr '\n' ' ') $(logf | tail -2)"
idle; mkdir -p "$SB/store/.mem-relief-idle"; echo "2000-01-01 6" > "$SB/store/.mem-relief-idle/day"; SWAP=13000 run env MEM_RELIEF_IDLE_SKIP=""
check "F1 (b): yesterday's count does not count today" "$(ok "$(calls | grep -c '^restart ')" = 3)" "$(calls | tr '\n' ' ')"
idle; echo 1 > "$SB/inbox-juro"; SWAP=13000 run env MEM_RELIEF_IDLE_SKIP=""
check "F1 (d): an agent with a pending or just-delivered message is not restarted" \
  "$(ok -z "$(calls | grep -x 'restart juro')" -a -n "$(logf | grep 'IDLE-KEEP juro (a message is pending or just delivered)')")" "$(calls | tr '\n' ' ')"
idle; rm -f "$SB/curl.args"
printf '#!/bin/bash\necho "$*" >> "%s/curl.args"; cat > "%s/curl.stdin"; exit 0\n' "$SB" "$SB" > "$SB/curl"; chmod +x "$SB/curl"
echo "TESTTOKEN-not-real-42" > "$SB/store/.dashboard-token"
SWAP=13000 run env MEM_RELIEF_IDLE_SKIP="" MEM_RELIEF_RESTART="" MEM_RELIEF_IDLE_MAX=1 PATH="$SB:$PATH"
check "INFO-1: the restart call sends the token on curl's stdin (-K -), never on its command line" \
  "$(ok -n "$(grep -- '-K - -X POST http://localhost:3420/api/agents/juro/restart' "$SB/curl.args")" -a -z "$(grep TESTTOKEN "$SB/curl.args")" -a -n "$(grep 'Bearer TESTTOKEN-not-real-42' "$SB/curl.stdin")")" "$(cat "$SB/curl.args" 2>/dev/null)"
rm -f "$SB/curl" "$SB/store/.dashboard-token" "$SB/curl.args" "$SB/curl.stdin"

echo "== Viktor 26919 LOW-1: the state is written before the restart"
idle; mkdir -p "$SB/store/.mem-relief-idle"; chmod 500 "$SB/store/.mem-relief-idle"; SWAP=13000 run env MEM_RELIEF_IDLE_SKIP=""
chmod 700 "$SB/store/.mem-relief-idle"
check "an unwritable state dir -> no restart at all, IDLE-SKIP logged, rc 1" \
  "$(ok -z "$(calls | grep '^restart ')" -a "$RC" = 1 -a -n "$(logf | grep 'IDLE-SKIP cannot write the restart state')")" "rc=$RC $(calls | tr '\n' ' ') $(logf | tail -2)"
idle; printf '#!/bin/bash\necho "restart $1" >> "%s/calls"; cat "%s/store/.mem-relief-idle/id-$1" > /dev/null && echo "stamp-before $1" >> "%s/calls"\n' "$SB" "$SB" "$SB" > "$SB/restart-check"; chmod +x "$SB/restart-check"
SWAP=13000 run env MEM_RELIEF_IDLE_SKIP="" MEM_RELIEF_RESTART="$SB/restart-check" MEM_RELIEF_IDLE_MAX=2
check "each agent's stamp and the day count exist when its restart runs" \
  "$(ok -n "$(calls | grep -x 'stamp-before juro')" -a -n "$(calls | grep -x 'stamp-before lex')" -a "$(cut -d' ' -f2 "$SB/store/.mem-relief-idle/day")" = 2)" "$(calls | tr '\n' ' ')"
check "INFO-1: the per-agent stamp is id-<id>, so a session named 'day' cannot overwrite the day count" \
  "$(ok -f "$SB/store/.mem-relief-idle/id-juro" -a ! -e "$SB/store/.mem-relief-idle/juro")" "$(ls -A "$SB/store/.mem-relief-idle" | tr '\n' ' ')"

echo "== 0. the render gate (Klodel 34315: two ungated Blender renders, kernel panic 2026-11-09 15:19)"
# Blender under a plain shell (700 -> 701, a child 702), under heavy-job.sh (801 -> 802), and under a shell that only
# MENTIONS heavy-job.sh (900 -> 901). No host-state: the memory band is fine, the gate still runs.
render_ps() {
  grep -v Blender "$SB/ps.base" > "$SB/ps"
  cat >> "$SB/ps" <<'EOF'
  700     1 /bin/zsh -c source /Users/x/marveen/agents/dave/.claude-config/shell-snapshots/s.sh && B=/q/Blender.app/Contents/MacOS/Blender; $B -b -P book-final.py
  701   700 /q/Blender.app/Contents/MacOS/Blender -b -P book-final.py -- /out 12 960 540
  702   701 /q/Blender.app/Contents/MacOS/Blender-helper --worker
  800     1 /bin/zsh -c source /Users/x/marveen/agents/dave/.claude-config/shell-snapshots/s.sh && bash /Users/x/marveen/scripts/heavy-job.sh --name render -- /q/Blender.app/Contents/MacOS/Blender -b
  801   800 bash /Users/x/marveen/scripts/heavy-job.sh --name render -- /q/Blender.app/Contents/MacOS/Blender -b
  802   801 /q/Blender.app/Contents/MacOS/Blender -b -P seq.py
  900     1 /bin/zsh -c source /Users/x/marveen/agents/mira/.claude-config/shell-snapshots/s.sh && echo heavy-job.sh; /q/Blender.app/Contents/MacOS/Blender -b
  901   900 /q/Blender.app/Contents/MacOS/Blender -b -P x.py
  950     1 /usr/bin/python3 render_blender_frames.py --blender /q/Blender.app/Contents/MacOS/Blender
EOF
  printf '%s\n' 200 201 202 300 301 302 701 702 802 901 > "$SB/alive"
  rm -f "$SB/store/.host-state"
}
reset; render_ps; run
check "an ungated Blender and its child are stopped with the memory band fine (no host-state), rc 0" \
  "$(ok "$RC" = 0 -a -n "$(calls | grep -x 'kill -TERM 701')" -a -n "$(calls | grep -x 'kill -TERM 702')")" "rc=$RC $(calls | tr '\n' ' ') $(logf)"
check "the shell that started it is not signalled" "$(ok -z "$(calls | grep -E 'kill -[A-Z]+ 700$')")" "$(calls | tr '\n' ' ')"
check "a Blender under heavy-job.sh is left alone (and heavy-job itself)" "$(ok -z "$(calls | grep -E 'kill -[A-Z]+ (800|801|802)$')")" "$(calls | tr '\n' ' ')"
check "a shell that only MENTIONS heavy-job.sh does not gate its Blender" "$(ok -n "$(calls | grep -x 'kill -TERM 901')")" "$(calls | tr '\n' ' ')"
check "a process that only names Blender in an argument is not signalled" "$(ok -z "$(calls | grep -E 'kill -[A-Z]+ 950$')")" "$(calls | tr '\n' ' ')"
check "the dev servers are NOT touched when memory is fine (only the gate ran)" "$(ok -z "$(calls | grep -E 'kill -[A-Z]+ (201|301)$')" -a -z "$(calls | grep colima)")" "$(calls | tr '\n' ' ')"
check "the log has STOP ungated Blender for each, with the owner" \
  "$(ok -n "$(logf | grep 'STOP ungated Blender owner=dave pids=701 702')" -a -n "$(logf | grep 'STOP ungated Blender owner=mira pids=901')")" "$(logf)"
check "the owners and the main agent are told, once each, with the heavy-job.sh command" \
  "$(ok "$(grep -c '^klodel dave ' "$SB/msgs")" = 1 -a "$(grep -c '^klodel mira ' "$SB/msgs")" = 1 -a "$(grep -c '^klodel klodel ' "$SB/msgs")" = 1 -a -n "$(grep 'scripts/heavy-job.sh --name' "$SB/msgs")")" "$(cat "$SB/msgs" 2>/dev/null)"
check "the gate does not start the memory cooldown" "$(ok ! -e "$SB/store/.mem-relief.last")"

reset; render_ps; date +%s > "$SB/store/.mem-relief.last"; state critical 10 "free memory 3%"; run
check "the gate runs inside the memory cooldown too" "$(ok -n "$(calls | grep -x 'kill -TERM 701')" -a -n "$(logf | grep 'SKIP cooldown')")" "$(calls | tr '\n' ' ') $(logf)"

reset; render_ps; run env MEM_RELIEF_RENDER_GATE=0
check "MEM_RELIEF_RENDER_GATE=0: no Blender is signalled" "$(ok -z "$(calls | grep -E 'kill -[A-Z]+ (701|901)$')")" "$(calls | tr '\n' ' ')"

reset; render_ps; run env MEM_RELIEF_DRY=1
check "dry: nothing signalled, nobody told, the log says what it would stop" \
  "$(ok -z "$(calls | grep 'kill -TERM')" -a ! -s "$SB/msgs" -a -n "$(logf | grep 'DRY would stop ungated Blender pid=701 owner=dave')")" "$(calls | tr '\n' ' ') $(logf)"

reset; render_ps; echo 701 > "$SB/stubborn"; echo 701 > "$SB/immortal"; run
check "a Blender that survives KILL: FAIL logged, rc 1, the message says so" \
  "$(ok "$RC" = 1 -a -n "$(logf | grep 'FAIL ungated Blender owner=dave')" -a -n "$(grep 'NEM sikerült' "$SB/msgs")")" "rc=$RC $(logf)"
rm -f "$SB/immortal"

echo "== 0. ffmpeg and mflux too, and 0b: the largest heavy process on a memory trigger (Klodel 34318)"
heavy_ps() {
  render_ps
  cat >> "$SB/ps" <<'EOF'
 1000     1 /bin/zsh -c source /Users/x/marveen/agents/mira/.claude-config/shell-snapshots/s.sh && ffmpeg -i a.mov b.mp4
 1001  1000 /opt/homebrew/bin/ffmpeg -i a.mov b.mp4
 1100     1 /bin/zsh -c source /Users/x/marveen/agents/dave/.claude-config/shell-snapshots/s.sh && mflux-generate --model dev
 1101  1100 /Users/x/.venv/bin/python3 /Users/x/.venv/bin/mflux-generate --model dev
 1200   801 /opt/homebrew/bin/ffmpeg -i frames/%04d.png out.mp4
 1300     1 /usr/bin/python3 make.py --ffmpeg /opt/homebrew/bin/ffmpeg
EOF
  printf '%s\n' 1001 1101 1200 >> "$SB/alive"
}
reset; heavy_ps; run
check "an ungated ffmpeg is stopped" "$(ok -n "$(calls | grep -x 'kill -TERM 1001')")" "$(calls | tr '\n' ' ')"
check "an ungated mflux (console script under python) is stopped" "$(ok -n "$(calls | grep -x 'kill -TERM 1101')")" "$(calls | tr '\n' ' ')"
check "an ffmpeg under heavy-job.sh is left alone; a process naming ffmpeg in an argument is not matched" \
  "$(ok -z "$(calls | grep -E 'kill -[A-Z]+ (1200|1300)$')")" "$(calls | tr '\n' ' ')"
check "the log names the kind" "$(ok -n "$(logf | grep 'STOP ungated ffmpeg owner=mira')" -a -n "$(logf | grep 'STOP ungated mflux owner=dave')")" "$(logf)"

# 0b: a memory trigger with the gated render (802) the largest: it is stopped, the smaller gated ffmpeg (1200) is not.
reset; heavy_ps; printf '  802  9.5G\n 1200  300M\n  201  2G\n' > "$SB/top"; state critical 10 "free memory 3%"
run env MEM_RELIEF_TOP="$SB/top" MEM_RELIEF_RENDER_GATE=0
check "0b: on a memory trigger the largest heavy process is stopped, even under heavy-job.sh" \
  "$(ok -n "$(calls | grep -x 'kill -TERM 802')" -a -n "$(logf | grep 'STOP largest heavy Blender 9.5 GB owner=dave')")" "$(calls | tr '\n' ' ') $(logf)"
check "0b: only the largest one" "$(ok -z "$(calls | grep -E 'kill -[A-Z]+ 1200$')")" "$(calls | tr '\n' ' ')"
check "0b: the owner is told it was the largest heavy process" "$(ok -n "$(grep '^klodel dave .*a legnagyobb nehéz folyamat' "$SB/msgs")")" "$(cat "$SB/msgs" 2>/dev/null)"
reset; heavy_ps; printf '  802  9.5G\n' > "$SB/top"; rm -f "$SB/store/.host-state"; run env MEM_RELIEF_TOP="$SB/top" MEM_RELIEF_RENDER_GATE=0
check "0b: no memory trigger, the gated render runs on" "$(ok -z "$(calls | grep -E 'kill -[A-Z]+ 802$')")" "$(calls | tr '\n' ' ')"

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
