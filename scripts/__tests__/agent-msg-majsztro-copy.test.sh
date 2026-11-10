#!/usr/bin/env bash
# agent-msg.sh: a message to majsztro is copied to klodel while Majsztro's budget is at 100 % (Klodel 36866,
# CLAUDE.md MÁJSZTRÓ HELYETTES; 2026-11-10 18:35 Radar's research sat with an out-of-budget Majsztro while Patrik
# asked "Na?", private TG 17341).
#
# WHAT THIS GUARDS. Copy only when: the recipient is majsztro, the sender is not klodel, the original was accepted,
# and store/mod-state/majsztro.json shows seven_day >= 100 % or five_hour >= 100 % before its resetsAt. Below the
# budget, after the 5-hour reset, with no/broken state file, to anyone else: exactly one POST. A failed copy keeps
# the original's OK and exit 0.
#
# Run:  bash scripts/__tests__/agent-msg-majsztro-copy.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
HELPER="${HELPER_BIN:-$ROOT/scripts/agent-msg.sh}"
FAILS=0; N=0
ok() { N=$((N+1)); if [ "$2" = "0" ]; then echo "PASS  $1"; else echo "FAIL  $1${3:+  -- $3}"; FAILS=$((FAILS+1)); fi; }

[ -r "$HELPER" ] || { echo "FATAL: the helper is missing: $HELPER" >&2; exit 2; }

SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/msgmajsztro.XXXXXX")"
trap 'rm -rf "$SANDBOX"' EXIT
BIN="$SANDBOX/bin"; mkdir -p "$BIN"
printf 'test-token\n' > "$SANDBOX/token"
STATE="$SANDBOX/majsztro.json"

# curl stub: nothing leaves the machine. Every -d body is appended (one JSON per line) to $BODIES; the n-th call
# answers id=n. CURL_FAIL_FROM=k makes call k and later answer HTTP 500 with no id.
cat > "$BIN/curl" <<'STUB'
#!/usr/bin/env bash
while [ $# -gt 0 ]; do
  if [ "$1" = "-d" ]; then printf '%s\n' "$2" >> "$BODIES"; shift; fi
  shift
done
n=$(wc -l < "$BODIES" | tr -d ' ')
if [ -n "${CURL_FAIL_FROM:-}" ] && [ "$n" -ge "$CURL_FAIL_FROM" ]; then printf '{"error":"x"}\n500'; exit 0; fi
printf '{"id":%s,"status":"pending"}\n200' "$n"
STUB
chmod +x "$BIN/curl"
printf '#!/usr/bin/env bash\nexit 0\n' > "$BIN/sleep"; chmod +x "$BIN/sleep"

iso() { python3 -c 'import datetime as d,sys; print((d.datetime.now(d.timezone.utc)+d.timedelta(hours=float(sys.argv[1]))).isoformat().replace("+00:00","Z"))' "$1"; }
state() {  # state <five_hour %> <seven_day %> [five_hour resetsAt]
  python3 -c 'import json,sys
fh={"kind":"five_hour","percentUsed":float(sys.argv[1])}
if len(sys.argv)>4 and sys.argv[4]: fh["resetsAt"]=sys.argv[4]
json.dump({"usage":{"rateLimits":[fh,{"kind":"seven_day","percentUsed":float(sys.argv[2])}]}},open(sys.argv[3],"w"))' "$1" "$2" "$STATE" "${3:-}"
}

run() {
  : > "$SANDBOX/bodies"
  OUT="$(env PATH="$BIN:$PATH" BODIES="$SANDBOX/bodies" MARVEEN_TOKEN_FILE="$SANDBOX/token" \
             MARVEEN_MAJSZTRO_STATE="$STATE" MARVEEN_HOMOGLYPH_BIN=/nonexistent CURL_FAIL_FROM="${CURL_FAIL_FROM:-}" \
             /bin/bash "$HELPER" "$@" 2>"$SANDBOX/err")"
  RC=$?
  POSTS=$(wc -l < "$SANDBOX/bodies" | tr -d ' ')
}
body() { sed -n "${1}p" "$SANDBOX/bodies" | python3 -c 'import json,sys; d=json.load(sys.stdin); v=d.get(sys.argv[1]); print("<absent>" if v is None else v)' "$2" 2>/dev/null; }

# --- copy goes out ---
state 10 100
run radar majsztro "Kutatás kész: X."
ok "seven_day 100: original OK" "$([ "$RC" = "0" ] && [ "$OUT" = "OK id=1" ] && echo 0 || echo 1)" "rc=$RC out='$OUT'"
ok "seven_day 100: two POSTs" "$([ "$POSTS" = "2" ] && echo 0 || echo 1)" "posts=$POSTS"
ok "copy goes to klodel, from the original sender" \
   "$([ "$(body 2 to)" = "klodel" ] && [ "$(body 2 from)" = "radar" ] && echo 0 || echo 1)"
ok "copy carries the prefix, the original id and the full text" \
   "$(body 2 content | head -1 | grep -q '^\[MAJSZTRO-HELYETTES MÁSOLAT\] (eredeti: id=1, radar -> majsztro' && body 2 content | grep -q '^Kutatás kész: X\.$' && echo 0 || echo 1)"
ok "original body unchanged (to majsztro, no prefix)" \
   "$([ "$(body 1 to)" = "majsztro" ] && [ "$(body 1 content)" = "Kutatás kész: X." ] && echo 0 || echo 1)"
ok "stderr names the copy id" "$(grep -q 'másolat klodelnek: id=2' "$SANDBOX/err" && echo 0 || echo 1)"

state 100 40 "$(iso 1)"
run radar Majsztro "öt órás ablak"
ok "five_hour 100 before reset (and To in other case): copy" "$([ "$POSTS" = "2" ] && [ "$(body 2 to)" = "klodel" ] && echo 0 || echo 1)" "posts=$POSTS"

state 100 40
run radar majsztro "nincs resetsAt"
ok "five_hour 100 without resetsAt: copy" "$([ "$POSTS" = "2" ] && echo 0 || echo 1)" "posts=$POSTS"

state 10 100
run --urgent radar majsztro "sürgős"
ok "--urgent: the copy is urgent too" "$([ "$(body 2 priority)" = "urgent" ] && [ "$(body 1 priority)" = "urgent" ] && echo 0 || echo 1)"

state 10 100
run radar majsztro "nem sürgős"
ok "plain send: the copy has no priority field" "$([ "$(body 2 priority)" = "<absent>" ] && echo 0 || echo 1)"

# --- no copy (negative) ---
state 99 99
run radar majsztro "keret alatt"
ok "below budget (99/99): exactly one POST" "$([ "$RC" = "0" ] && [ "$POSTS" = "1" ] && echo 0 || echo 1)" "posts=$POSTS"
ok "below budget: no substitute line on stderr" "$(grep -q 'MAJSZTRO-HELYETTES' "$SANDBOX/err" && echo 1 || echo 0)"

state 100 40 "$(iso -1)"
run radar majsztro "ablak lejárt"
ok "five_hour 100 after its reset: no copy" "$([ "$POSTS" = "1" ] && echo 0 || echo 1)" "posts=$POSTS"

rm -f "$STATE"
run radar majsztro "nincs állapotfájl"
ok "no state file: no copy" "$([ "$RC" = "0" ] && [ "$POSTS" = "1" ] && echo 0 || echo 1)" "posts=$POSTS"

printf 'nem json' > "$STATE"
run radar majsztro "hibás állapotfájl"
ok "broken state file: no copy, send still OK" "$([ "$RC" = "0" ] && [ "$POSTS" = "1" ] && echo 0 || echo 1)" "posts=$POSTS"

state 10 100
run radar dave "Dave-nek"
ok "budget full, recipient dave: no copy" "$([ "$POSTS" = "1" ] && echo 0 || echo 1)" "posts=$POSTS"

state 10 100
run klodel majsztro "Klodel írja"
ok "budget full, sender klodel: no copy" "$([ "$POSTS" = "1" ] && echo 0 || echo 1)" "posts=$POSTS"

# --- failures ---
state 10 100
CURL_FAIL_FROM=1 run radar majsztro "az eredeti bukik"
ok "original fails: exit 1, no copy attempt beyond the 3 retries" "$([ "$RC" = "1" ] && [ "$POSTS" = "3" ] && echo 0 || echo 1)" "rc=$RC posts=$POSTS"

state 10 100
CURL_FAIL_FROM=2 run radar majsztro "a másolat bukik"
ok "copy fails: original still OK, exit 0" "$([ "$RC" = "0" ] && [ "$OUT" = "OK id=1" ] && echo 0 || echo 1)" "rc=$RC out='$OUT'"
ok "copy fails: 3 copy tries, WARN on stderr" "$([ "$POSTS" = "4" ] && grep -q 'klodel-másolat NEM ment ki' "$SANDBOX/err" && echo 0 || echo 1)" "posts=$POSTS"

echo "---"; echo "$((N-FAILS))/$N passed"
[ "$FAILS" = "0" ]
