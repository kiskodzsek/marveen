#!/usr/bin/env bash
# agent-msg.sh send gate (card aba42256, DREAM 11-11): scripts/lib/msg_gate.py in front of the POST.
#
# WHAT THIS GUARDS. Refused with exit 3 and ZERO POSTs: a secret shape from src/security/secret-gate.ts to anyone;
# to or from majsztro, more than 12 000 characters or an e-mail address outside marabel.hu / myshp.hu. The refusal
# never echoes the matched value. Sent (one POST): exactly 12 000 characters to majsztro, our own addresses to
# majsztro, a long text or a foreign address between other agents. A broken gate (unreadable or emptied pattern
# source) is exit 4 with zero POSTs, never a silent "clean". A missing gate file sends with a WARN.
#
# Run:  bash scripts/__tests__/agent-msg-send-gate.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
HELPER="${HELPER_BIN:-$ROOT/scripts/agent-msg.sh}"
GATE="$ROOT/scripts/lib/msg_gate.py"
FAILS=0; N=0
ok() { N=$((N+1)); if [ "$2" = "0" ]; then echo "PASS  $1"; else echo "FAIL  $1${3:+  -- $3}"; FAILS=$((FAILS+1)); fi; }

[ -r "$HELPER" ] || { echo "FATAL: the helper is missing: $HELPER" >&2; exit 2; }
[ -r "$GATE" ] || { echo "FATAL: the gate is missing: $GATE" >&2; exit 2; }

SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/msggate.XXXXXX")"
trap 'rm -rf "$SANDBOX"' EXIT
BIN="$SANDBOX/bin"; mkdir -p "$BIN"
printf 'test-token\n' > "$SANDBOX/token"

# curl stub: nothing leaves the machine; every -d body is one line in $BODIES, call n answers id=n.
cat > "$BIN/curl" <<'STUB'
#!/usr/bin/env bash
while [ $# -gt 0 ]; do
  if [ "$1" = "-d" ]; then printf '%s\n' "$2" >> "$BODIES"; shift; fi
  shift
done
n=$(wc -l < "$BODIES" | tr -d ' ')
printf '{"id":%s,"status":"pending"}\n200' "$n"
STUB
chmod +x "$BIN/curl"
printf '#!/usr/bin/env bash\nexit 0\n' > "$BIN/sleep"; chmod +x "$BIN/sleep"

# run <from> <to> ; the text comes from $SANDBOX/text (STDIN mode, so 20 000 characters fit)
run() {
  : > "$SANDBOX/bodies"
  OUT="$(env PATH="$BIN:$PATH" BODIES="$SANDBOX/bodies" MARVEEN_TOKEN_FILE="$SANDBOX/token" \
             MARVEEN_MAJSZTRO_STATE=/nonexistent MARVEEN_HOMOGLYPH_BIN=/nonexistent ${GATE_ENV:-} \
             /bin/bash "$HELPER" "$1" "$2" - < "$SANDBOX/text" 2>"$SANDBOX/err")"
  RC=$?
  POSTS=$(wc -l < "$SANDBOX/bodies" | tr -d ' ')
}
text() { printf '%s' "$1" > "$SANDBOX/text"; }
chars() { python3 -c 'import sys; sys.stdout.write("é" * int(sys.argv[1]))' "$1" > "$SANDBOX/text"; }
refused() { [ "$RC" = "3" ] && [ "$POSTS" = "0" ] && echo 0 || echo 1; }
sent() { [ "$RC" = "0" ] && [ "$POSTS" = "1" ] && echo 0 || echo 1; }

# Fake secrets are assembled at run time so this file itself never carries a secret shape (the commit gate
# scans it). Each is a shape from SECRET_PATTERNS, not a real key.
STRIPE="sk_""live_$(printf 'Ab1%.0s' $(seq 1 8))"
GH="gh""p_$(printf 'aB3%.0s' $(seq 1 12))"
PEM="-----BEGIN RSA ""PRIVATE KEY-----"

# --- secrets: refused for everyone ---
text "a kulcs: $STRIPE kész"
run kernel dave
ok "Stripe key shape to dave: exit 3, no POST" "$(refused)" "rc=$RC posts=$POSTS"
ok "the refusal names the pattern" "$(grep -q 'Stripe secret/restricted key' "$SANDBOX/err" && echo 0 || echo 1)"
ok "the refusal never echoes the value" "$(grep -qF "$STRIPE" "$SANDBOX/err" && echo 1 || echo 0)"
ok "nothing on stdout but no OK line" "$(printf '%s' "$OUT" | grep -q '^OK' && echo 1 || echo 0)"

text "token: $GH"
run viktor klodel
ok "GitHub token shape viktor->klodel: refused" "$(refused)" "rc=$RC posts=$POSTS"

text "$PEM
MIIE..."
run pulzus kernel
ok "private key block: refused" "$(refused)" "rc=$RC posts=$POSTS"

text "STRIPE_SECRET_KEY a Vaultban, helykitöltő: sk_live_<helykitöltő>"
run kernel dave
ok "secret named by its place, placeholder in <>: sent" "$(sent)" "rc=$RC posts=$POSTS"

# --- Majsztro: length ---
chars 12001
run radar majsztro
ok "12 001 characters to majsztro: refused" "$(refused)" "rc=$RC posts=$POSTS"
ok "the refusal points to a file under kontext/" "$(grep -q 'agents/majsztro/kontext/' "$SANDBOX/err" && echo 0 || echo 1)"

chars 12000
run radar majsztro
ok "exactly 12 000 characters (multibyte é) to majsztro: sent" "$(sent)" "rc=$RC posts=$POSTS"

chars 12001
run majsztro klodel
ok "12 001 characters FROM majsztro: refused" "$(refused)" "rc=$RC posts=$POSTS"

chars 20000
run radar Majsztro
ok "recipient in other case (Majsztro): refused" "$(refused)" "rc=$RC posts=$POSTS"

chars 20000
run klodel dave
ok "20 000 characters klodel->dave: sent (not Majsztro's traffic)" "$(sent)" "rc=$RC posts=$POSTS"

# --- Majsztro: e-mail ---
text "Sajtócím: press@example-radio.hu, írj nekik."
run magnes majsztro
ok "third-party address to majsztro: refused" "$(refused)" "rc=$RC posts=$POSTS"
ok "the refusal never echoes the address" "$(grep -q 'example-radio' "$SANDBOX/err" && echo 1 || echo 0)"

text "Kérdés esetén: adatvedelem@marabel.hu vagy info@mail.myshp.hu."
run mira majsztro
ok "our own domains (and a subdomain) to majsztro: sent" "$(sent)" "rc=$RC posts=$POSTS"

text "Lookalike: info@marabel.hu.evil.net"
run mira majsztro
ok "lookalike domain marabel.hu.evil.net: refused" "$(refused)" "rc=$RC posts=$POSTS"

text "A vevő címe: vevo@gmail.com"
run klodel pulzus
ok "foreign address klodel->pulzus: sent (only Majsztro's traffic is e-mail-gated)" "$(sent)" "rc=$RC posts=$POSTS"

# --- the gate itself fails: exit 4, nothing sent ---
text "ártalmatlan"
GATE_ENV="MARVEEN_MSG_GATE_SECRET_SRC=$SANDBOX/missing.ts" run kernel dave
ok "pattern source unreadable: exit 4, no POST" "$([ "$RC" = "4" ] && [ "$POSTS" = "0" ] && echo 0 || echo 1)" "rc=$RC posts=$POSTS"
ok "the crash says it is not a verdict" "$(grep -q 'not a verdict' "$SANDBOX/err" && echo 0 || echo 1)"

printf 'export const SECRET_PATTERNS = [\n];\n' > "$SANDBOX/empty.ts"
GATE_ENV="MARVEEN_MSG_GATE_SECRET_SRC=$SANDBOX/empty.ts" run kernel dave
ok "empty pattern list: exit 4, never a silent clean" "$([ "$RC" = "4" ] && [ "$POSTS" = "0" ] && echo 0 || echo 1)" "rc=$RC posts=$POSTS"

# --- the live list really is read (a pattern only there catches) ---
python3 - "$ROOT/src/security/secret-gate.ts" "$SANDBOX/extra.ts" <<'PY'
import sys
s = open(sys.argv[1]).read()
s = s.replace("export const SECRET_PATTERNS: { name: string; pattern: RegExp }[] = [\n",
              "export const SECRET_PATTERNS: { name: string; pattern: RegExp }[] = [\n  { name: 'test-only shape', pattern: /\\bzzqx_[0-9]{6}\\b/ },\n", 1)
open(sys.argv[2], 'w').write(s)
PY
text "érték: zzqx_123456"
GATE_ENV="MARVEEN_MSG_GATE_SECRET_SRC=$SANDBOX/extra.ts" run kernel dave
ok "a pattern added to secret-gate.ts is enforced without touching the gate" "$(refused)" "rc=$RC posts=$POSTS"

# --- every entry of the live list is read (a reformatted secret-gate.ts must break CI, not the fleet) ---
# The gate parses one-line `{ name: '...', pattern: /.../ }` entries. An entry written differently would be
# skipped silently, and a list reformatted wholesale would drop below MIN_PATTERNS and stop every message.
PARITY="$(python3 -I - "$GATE" "$ROOT/src/security/secret-gate.ts" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location('msg_gate', sys.argv[1]); g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
src = open(sys.argv[2]).read(); s = src.index('export const SECRET_PATTERNS'); block = src[s:src.index('\n];', s)]
print(len(g.load_secret_patterns(sys.argv[2])), block.count("name: '"))
PY
)"
ok "every SECRET_PATTERNS entry is parsed (parsed, entries: $PARITY)" "$(set -- $PARITY; [ -n "${1:-}" ] && [ "$1" = "${2:-x}" ] && echo 0 || echo 1)"

# --- Viktor 37183 F2: an entry the parser cannot read stops the gate at run time, not only in CI ---
python3 - "$ROOT/src/security/secret-gate.ts" "$SANDBOX/unparsed.ts" <<'PY'
import sys
s = open(sys.argv[1]).read()
s = s.replace("export const SECRET_PATTERNS: { name: string; pattern: RegExp }[] = [\n",
              "export const SECRET_PATTERNS: { name: string; pattern: RegExp }[] = [\n  { name: 'slash in class', pattern: /\\bzz[/]q_[0-9]{6}/ },\n", 1)
open(sys.argv[2], 'w').write(s)
PY
text "ártalmatlan"
GATE_ENV="MARVEEN_MSG_GATE_SECRET_SRC=$SANDBOX/unparsed.ts" run kernel dave
ok "an unparsed entry (unescaped / in a class, legal in JS): exit 4, no POST (F2)" "$([ "$RC" = "4" ] && [ "$POSTS" = "0" ] && echo 0 || echo 1)" "rc=$RC posts=$POSTS"
ok "F2: stderr says how many entries were read" "$(grep -q 'SECRET_PATTERNS entries' "$SANDBOX/err" && echo 0 || echo 1)"

# --- Viktor 37183 F1: JS \b is ASCII; a non-ASCII letter next to the key must not hide it ---
text "é$STRIPE"
run kernel dave
ok "é right before a Stripe key: refused (F1, leading \\b)" "$(refused)" "rc=$RC posts=$POSTS"
AWS="AKIA""$(printf 'QWERTYUIOPASDFGH')"
text "kulcs: ${AWS}é"
run kernel dave
ok "é right after an AWS key id: refused (F1, trailing \\b)" "$(refused)" "rc=$RC posts=$POSTS"
text "kulcs: ${AWS}X"
run kernel dave
ok "an ASCII letter after the AWS key id: no boundary, sent (as in JS)" "$(sent)" "rc=$RC posts=$POSTS"

# --- missing gate file at the DEFAULT path: send, loudly (an install without the file) ---
mkdir -p "$SANDBOX/inst/scripts"; cp "$HELPER" "$SANDBOX/inst/scripts/agent-msg.sh"
text "ártalmatlan"
HELPER_SAVED="$HELPER"; HELPER="$SANDBOX/inst/scripts/agent-msg.sh"
run kernel dave
HELPER="$HELPER_SAVED"
ok "missing gate at the default path: sent" "$(sent)" "rc=$RC posts=$POSTS"
ok "missing gate at the default path: WARN on stderr" "$(grep -q 'send gate not found' "$SANDBOX/err" && echo 0 || echo 1)"

# --- Viktor 37183 (a): an explicitly named gate that cannot be read: refused ---
GATE_ENV="MARVEEN_MSG_GATE_BIN=/nonexistent" run kernel dave
ok "MARVEEN_MSG_GATE_BIN set but unreadable: exit 4, no POST" "$([ "$RC" = "4" ] && [ "$POSTS" = "0" ] && echo 0 || echo 1)" "rc=$RC posts=$POSTS"

# --- a plain message is untouched ---
text "Kész: PR #172, 'idézőjel' és \"dupla\"."
run kernel klodel
ok "plain message: OK id=1" "$([ "$OUT" = "OK id=1" ] && [ "$POSTS" = "1" ] && echo 0 || echo 1)" "out='$OUT'"
ok "the body is the sender's text, not the gate's output" \
   "$(sed -n 1p "$SANDBOX/bodies" | python3 -c 'import json,sys; print(json.load(sys.stdin)["content"])' | grep -qF "Kész: PR #172, 'idézőjel' és \"dupla\"." && echo 0 || echo 1)"

echo "---"; echo "$((N-FAILS))/$N passed"
[ "$FAILS" = "0" ]
