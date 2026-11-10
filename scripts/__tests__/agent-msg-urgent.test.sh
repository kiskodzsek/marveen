#!/usr/bin/env bash
# agent-msg.sh --urgent puts "priority":"urgent" in the POST body (Klodel 35737, Patrik group TG 4465 "mehet").
#
# WHAT THIS GUARDS. The router types an urgent row into a busy pane; the helper is how agents send, so the flag
# must reach the body, must not leak into the content or shift the from/to arguments, and a plain send must
# carry no priority field at all (the server default 'normal' applies, an old server is not confused).
#
# Run:  bash scripts/__tests__/agent-msg-urgent.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
HELPER="${HELPER_BIN:-$ROOT/scripts/agent-msg.sh}"
FAILS=0; N=0
ok() { N=$((N+1)); if [ "$2" = "0" ]; then echo "PASS  $1"; else echo "FAIL  $1${3:+  -- $3}"; FAILS=$((FAILS+1)); fi; }

[ -r "$HELPER" ] || { echo "FATAL: the helper is missing: $HELPER" >&2; exit 2; }

SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/msgurgent.XXXXXX")"
trap 'rm -rf "$SANDBOX"' EXIT
BIN="$SANDBOX/bin"; mkdir -p "$BIN"
printf 'test-token\n' > "$SANDBOX/token"

# curl stub: nothing leaves the machine; the -d body is written to $SANDBOX/body.json.
cat > "$BIN/curl" <<'STUB'
#!/usr/bin/env bash
while [ $# -gt 0 ]; do
  if [ "$1" = "-d" ]; then printf '%s' "$2" > "$BODY_OUT"; shift; fi
  shift
done
printf '{"id":7,"status":"pending"}\n200'
STUB
chmod +x "$BIN/curl"
printf '#!/usr/bin/env bash\nexit 0\n' > "$BIN/sleep"; chmod +x "$BIN/sleep"

field() { python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); v=d.get(sys.argv[2]); print("<absent>" if v is None else v)' "$SANDBOX/body.json" "$1"; }

run() {
  rm -f "$SANDBOX/body.json"
  OUT="$(env PATH="$BIN:$PATH" BODY_OUT="$SANDBOX/body.json" MARVEEN_TOKEN_FILE="$SANDBOX/token" \
             /bin/bash "$HELPER" "$@" 2>/dev/null)"
  RC=$?
}

run --urgent igor hex "javitsd most"
ok "--urgent: sent" "$([ "$RC" = "0" ] && [ "$OUT" = "OK id=7" ] && echo 0 || echo 1)" "rc=$RC out='$OUT'"
ok "--urgent: priority=urgent in the body" "$([ "$(field priority)" = "urgent" ] && echo 0 || echo 1)" "got '$(field priority)'"
ok "--urgent: from/to/content not shifted" \
   "$([ "$(field from)" = "igor" ] && [ "$(field to)" = "hex" ] && [ "$(field content)" = "javitsd most" ] && echo 0 || echo 1)"

run igor hex "sima uzenet"
ok "plain send: no priority field" "$([ "$(field priority)" = "<absent>" ] && echo 0 || echo 1)" "got '$(field priority)'"
ok "plain send: content intact" "$([ "$(field content)" = "sima uzenet" ] && echo 0 || echo 1)"

rm -f "$SANDBOX/body.json"
OUT="$(printf 'stdin szoveg' | env PATH="$BIN:$PATH" BODY_OUT="$SANDBOX/body.json" MARVEEN_TOKEN_FILE="$SANDBOX/token" /bin/bash "$HELPER" --urgent igor hex - 2>/dev/null)"
ok "--urgent with STDIN content" "$([ "$(field priority)" = "urgent" ] && [ "$(field content)" = "stdin szoveg" ] && echo 0 || echo 1)"

echo "---"; echo "$((N-FAILS))/$N passed"
[ "$FAILS" = "0" ]
