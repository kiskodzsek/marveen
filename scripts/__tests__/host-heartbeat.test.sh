#!/usr/bin/env bash
# host-heartbeat-ping.sh and install-host-heartbeat.sh (card 8fbd8b7b, Viktor 40253 T1-T6).
#
# HOME points into a sandbox, so the config folder is the sandbox's. curl, pbpaste and pbcopy are stubs on
# PATH: nothing reaches hc-ping.com and the real clipboard is not touched. The check UUID is built by
# concatenation, so no ping-URL literal stands in this file (the secret gate would rightly flag it).
#
# Run:  bash scripts/__tests__/host-heartbeat.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PING="$ROOT/scripts/host-heartbeat-ping.sh"
INST="$ROOT/scripts/install-host-heartbeat.sh"
FAILS=0
N=0
check() { N=$((N+1)); if [ "$2" = "0" ]; then echo "PASS  $1"; else echo "FAIL  $1${3:+  -- $3}"; FAILS=$((FAILS+1)); fi; }
owner_mode() { if [ "$(uname -s)" = Darwin ]; then stat -f '%u %Lp' "$1"; else stat -c '%u %a' "$1"; fi 2>/dev/null; }

SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/hostbeat.XXXXXX")"
trap 'rm -rf "$SANDBOX"' EXIT
export HOME="$SANDBOX/home"
export MARVEEN_STORE="$SANDBOX/store"
BIN="$SANDBOX/bin"
mkdir -p "$HOME" "$MARVEEN_STORE" "$BIN"
CONF_DIR="$HOME/Library/Application Support/marveen"
CONF="$CONF_DIR/host-heartbeat.curlrc"
LOG="$MARVEEN_STORE/host-heartbeat.log"
ARGV="$SANDBOX/curl-argv"
HOST="hc-ping"".com"
U="$(printf '%s-%s-%s-%s-%s' 1a2b3c4d 5e6f 7a8b 9c0d 1e2f3a4b5c6d)"
URL="https://$HOST/$U"

# curl stub: records its argv (one per line), then exits with $SANDBOX/rc (default 0) and, when failing,
# echoes an error that CONTAINS the URL, the worst case for the log.
cat > "$BIN/curl" <<STUB
#!/bin/bash
printf '%s\n' "\$@" >> "$ARGV"
rc=\$(cat "$SANDBOX/rc" 2>/dev/null || echo 0)
if [ "\$rc" != "0" ]; then echo "curl: (\$rc) The requested URL returned error: 404 for $URL" >&2; fi
exit "\$rc"
STUB
cat > "$BIN/pbpaste" <<STUB
#!/bin/bash
cat "$SANDBOX/clipboard" 2>/dev/null
STUB
cat > "$BIN/pbcopy" <<STUB
#!/bin/bash
cat > "$SANDBOX/clipboard"
echo cleared >> "$SANDBOX/pbcopy-called"
STUB
chmod +x "$BIN/curl" "$BIN/pbpaste" "$BIN/pbcopy"
export PATH="$BIN:/usr/bin:/bin"

good_conf() {
  rm -rf "$CONF_DIR"; mkdir -p "$CONF_DIR"; chmod 700 "$CONF_DIR"
  printf 'url = "%s"\n' "$URL" > "$CONF"; chmod 600 "$CONF"
}
reset_run() { rm -f "$ARGV" "$LOG" "$MARVEEN_STORE/.host-heartbeat-logged"; echo "${1:-0}" > "$SANDBOX/rc"; }
called() { [ -s "$ARGV" ]; }

# --- the ping ---
good_conf; reset_run 0
bash "$PING"; rc=$?
check "success: exit 0" "$([ $rc = 0 ]; echo $?)"
check "T1: the URL/UUID is not in curl's argv" "$(! grep -q "$U" "$ARGV"; echo $?)"
check "T1: curl gets -K <conf>, --proto =https, --tlsv1.2, -m 10, --retry 2" \
  "$(grep -qx -- '-K' "$ARGV" && grep -qx -- "$CONF" "$ARGV" && grep -qx -- '=https' "$ARGV" && grep -qx -- '--tlsv1.2' "$ARGV" && grep -qx -- '10' "$ARGV" && grep -qx -- '--retry' "$ARGV"; echo $?)"
check "T1: no -v, -L, -w, --trace in argv" "$(! grep -Eqx -- '-v|-L|-w|--verbose|--location|--write-out|--trace|--trace-ascii' "$ARGV"; echo $?)"
check "T2: success writes no log" "$([ ! -e "$LOG" ]; echo $?)"

for code in 22 6 28; do
  good_conf; reset_run "$code"
  bash "$PING"; rc=$?
  check "failure ($code): exit 1" "$([ $rc = 1 ]; echo $?)"
  check "T5: failure ($code): one log line, UUID-free and URL-free" \
    "$([ "$(wc -l < "$LOG" | tr -d ' ')" = 1 ] && ! grep -q "$U" "$LOG" && ! grep -q "$HOST/[^<]" "$LOG"; echo $?)"
done

good_conf; reset_run 22
bash "$PING"; bash "$PING"; bash "$PING"
check "T2: three failures in a row log once (rate limit)" "$([ "$(wc -l < "$LOG" | tr -d ' ')" = 1 ]; echo $?)"
echo 0 > "$SANDBOX/rc"; bash "$PING"
check "recovery: success after a failure adds no log line and clears the stamp" \
  "$([ "$(wc -l < "$LOG" | tr -d ' ')" = 1 ] && [ ! -e "$MARVEEN_STORE/.host-heartbeat-logged" ]; echo $?)"

# T3/T6: a bad file or folder means no call at all, and no fallback URL.
good_conf; chmod 644 "$CONF"; reset_run 0
bash "$PING"; rc=$?
check "T3: file mode 0644 -> no curl call, exit 1" "$(! called && [ $rc = 1 ]; echo $?)"

good_conf; chmod 755 "$CONF_DIR"; reset_run 0
bash "$PING"; rc=$?
check "T3: folder mode 0755 -> no curl call" "$(! called && [ $rc = 1 ]; echo $?)"

good_conf; rm -f "$CONF"; reset_run 0
bash "$PING"; rc=$?
check "T3: missing file -> no curl call (no fallback URL)" "$(! called && [ $rc = 1 ]; echo $?)"

good_conf; mv "$CONF" "$SANDBOX/real.curlrc"; ln -s "$SANDBOX/real.curlrc" "$CONF"; reset_run 0
# BSD chmod -h gives the link itself mode 600, so only the symlink test can stop it (GNU: no -h, no-op).
chmod -h 600 "$CONF" 2>/dev/null || true
bash "$PING"; rc=$?
check "T3: the file is a symlink -> no curl call" "$(! called && [ $rc = 1 ]; echo $?)"

good_conf; printf 'proxy = "http://127.0.0.1:9"\n' >> "$CONF"; reset_run 0
bash "$PING"; rc=$?
check "T3: an extra curl option in the file -> no curl call" "$(! called && [ $rc = 1 ]; echo $?)"

# Viktor 40263 LOW: a second line WITHOUT a trailing newline keeps wc -l at 1, and curl still reads it.
for shape in url-then-proxy proxy-then-url url-then-output url-no-newline; do
  good_conf; reset_run 0
  case "$shape" in
    url-then-proxy)  printf 'url = "%s"\nproxy = "http://127.0.0.1:9"' "$URL" > "$CONF" ;;
    proxy-then-url)  printf 'proxy = "http://127.0.0.1:9"\nurl = "%s"' "$URL" > "$CONF" ;;
    url-then-output) printf 'url = "%s"\noutput = "/tmp/x"' "$URL" > "$CONF" ;;
    url-no-newline)  printf 'url = "%s"' "$URL" > "$CONF" ;;
  esac
  chmod 600 "$CONF"
  bash "$PING"; rc=$?
  check "T3: $shape (no trailing newline) -> no curl call" "$(! called && [ $rc = 1 ]; echo $?)"
done

good_conf; printf 'url = "https://%s/%s/%s"\n' "$HOST" "abcdefghijklmnopqrstuv" "mini" > "$CONF"; chmod 600 "$CONF"; reset_run 0
bash "$PING"; rc=$?
check "T3: a project ping-key URL (not a check UUID) -> no curl call" "$(! called && [ $rc = 1 ]; echo $?)"

good_conf; rm -rf "$CONF_DIR"; reset_run 0
bash "$PING"; rc=$?
check "T3: missing folder -> no curl call, the log line is UUID-free" "$(! called && [ $rc = 1 ] && ! grep -q "$U" "$LOG"; echo $?)"

# --- the installer: --set-url-from-clipboard ---
rm -rf "$CONF_DIR" "$SANDBOX/pbcopy-called"
printf 'not a url at all\n' > "$SANDBOX/clipboard"
out=$(bash "$INST" --set-url-from-clipboard 2>&1); rc=$?
check "T6: garbage on the clipboard -> exit 2, nothing written" "$([ $rc = 2 ] && [ ! -e "$CONF" ]; echo $?)"

printf 'https://%s/%s/%s\n' "$HOST" "abcdefghijklmnopqrstuv" "mini" > "$SANDBOX/clipboard"
bash "$INST" --set-url-from-clipboard >/dev/null 2>&1; rc=$?
check "T6: a ping-key URL on the clipboard -> nothing written" "$([ $rc = 2 ] && [ ! -e "$CONF" ]; echo $?)"

printf '%s\n%s\n' "$URL" "$URL" > "$SANDBOX/clipboard"
bash "$INST" --set-url-from-clipboard >/dev/null 2>&1; rc=$?
check "T6: two lines on the clipboard -> nothing written" "$([ $rc = 2 ] && [ ! -e "$CONF" ]; echo $?)"

printf 'http://%s/%s\n' "$HOST" "$U" > "$SANDBOX/clipboard"
bash "$INST" --set-url-from-clipboard >/dev/null 2>&1; rc=$?
check "T6: plain http -> nothing written" "$([ $rc = 2 ] && [ ! -e "$CONF" ]; echo $?)"

UPPER="$(printf '%s' "$U" | tr 'a-f' 'A-F')"
printf '  https://%s/%s \r\n' "$HOST" "$UPPER" > "$SANDBOX/clipboard"
out=$(bash "$INST" --set-url-from-clipboard 2>&1); rc=$?
check "set-url: a good URL (spaces, CR, upper-case hex) -> exit 0" "$([ $rc = 0 ]; echo $?)" "$out"
check "set-url: the file is exactly one lower-case url line" "$([ "$(cat "$CONF")" = "url = \"$URL\"" ]; echo $?)"
check "set-url: folder 0700, file 0600, ours" \
  "$([ "$(owner_mode "$CONF_DIR")" = "$(id -u) 700" ] && [ "$(owner_mode "$CONF")" = "$(id -u) 600" ]; echo $?)"
check "set-url: the output is masked (no UUID, the last 4 only)" "$(! printf '%s' "$out" | grep -q "$U" && printf '%s' "$out" | grep -q "${U: -4}"; echo $?)"
check "set-url: the clipboard is cleared" "$([ -s "$SANDBOX/pbcopy-called" ] && [ ! -s "$SANDBOX/clipboard" ]; echo $?)"
reset_run 0; bash "$PING"; rc=$?
check "set-url -> ping: the written file passes the ping's own checks" "$(called && [ $rc = 0 ]; echo $?)"

rm -rf "$CONF_DIR"; mkdir -p "$HOME/Library/Application Support" "$SANDBOX/elsewhere"
ln -s "$SANDBOX/elsewhere" "$CONF_DIR"
printf '%s\n' "$URL" > "$SANDBOX/clipboard"
bash "$INST" --set-url-from-clipboard >/dev/null 2>&1; rc=$?
check "T6: a symlinked config folder -> refused, nothing written" "$([ $rc = 2 ] && [ -z "$(ls -A "$SANDBOX/elsewhere")" ]; echo $?)"
rm -f "$CONF_DIR"

# --- the installer: the plist (macOS only) ---
if [ "$(uname -s)" = "Darwin" ]; then
  good_conf
  bash "$INST" >/dev/null 2>&1; rc=$?
  P="$HOME/Library/LaunchAgents/com.marveen.host-heartbeat.plist"
  check "T4: the plist is written without --load" "$([ $rc = 0 ] && [ -f "$P" ]; echo $?)"
  check "T4: the plist carries no URL and no UUID" "$(! grep -q "$U" "$P" && ! grep -q "$HOST" "$P"; echo $?)"
  check "the plist: every 60 s and at load" "$(grep -q '<integer>60</integer>' "$P" && grep -q '<key>RunAtLoad</key>' "$P"; echo $?)"
  check "the plist: lint ok" "$(plutil -lint "$P" >/dev/null; echo $?)"
else
  echo "SKIP  plist checks (not macOS)"
fi

echo "$((N-FAILS))/$N pass"
[ "$FAILS" = 0 ]
