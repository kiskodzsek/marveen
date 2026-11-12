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

# --- Klodel 37876 (UGYANAZ A HIBA KÉTSZER NEM): a stop order from klodel needs Patrik's explicit stop word ---
# negative: the 37874 text (Patrik's opinion "senkik vannak" read as a stop)
text "37872 TÁRGYTALAN, állj le: Patrik TG 5294 a Creatorz-alkotókról: 'senkik vannak'. Nem kell lista. Köszi."
run klodel radar
ok "stop: 37874 (opinion read as a stop) klodel->radar: refused" "$(refused)" "rc=$RC posts=$POSTS"
ok "stop: the refusal names the LEÁLLÍTÁS-OK line" "$(grep -q 'LEÁLLÍTÁS-OK: TG' "$SANDBOX/err" && echo 0 || echo 1)"
# positive: the Klodel-given example
text 'Radar, állj le a K+F-szállal, az anyagok maradnak.
LEÁLLÍTÁS-OK: TG 5282 "na én ezt most hagyom"'
run klodel radar
ok "stop: with LEÁLLÍTÁS-OK TG 5282 \"na én ezt most hagyom\": sent" "$(sent)" "rc=$RC posts=$POSTS"
# Patrik types without accents, and "ne allitsd le" (TG 5297) is the opposite of a stop
text 'TÁRGYTALAN, állj le.
LEÁLLÍTÁS-OK: TG 5297 "ne allitsd le"'
run klodel radar
ok "stop: a negated quote \"ne allitsd le\" does not unlock: refused" "$(refused)" "rc=$RC posts=$POSTS"
text 'Állj le.
LEÁLLÍTÁS-OK: TG 5300 "nem kell leállítani"'
run klodel radar
ok "stop: \"nem kell leállítani\" does not unlock: refused" "$(refused)" "rc=$RC posts=$POSTS"
text 'Állj le.
LEÁLLÍTÁS-OK: TG 5294 "senkik vannak"'
run klodel radar
ok "stop: a quote without a stop word (an opinion) does not unlock: refused" "$(refused)" "rc=$RC posts=$POSTS"
text 'Tárgytalan, LEÁLLÍTÁS-OK: TG 5282 "hagyom"'
run klodel radar
ok "stop: LEÁLLÍTÁS-OK not on its own line: refused" "$(refused)" "rc=$RC posts=$POSTS"
text 'Tárgytalan, a 4949d8de lezárva.
LEÁLLÍTÁS-OK: TG 5301 "ezt allitsuk le"'
run klodel szigma
ok "stop: accent-free quote \"ezt allitsuk le\": sent" "$(sent)" "rc=$RC posts=$POSTS"
text "targytalan, allj le"
run klodel radar
ok "stop: an accent-free trigger is caught too: refused" "$(refused)" "rc=$RC posts=$POSTS"
# Klodel 39243: Patrik TG 4943 "nem azt mondtam zárd le" denies a stop; quoted in a brief it is not a stop order
text 'Brief (ea036ae1). Kérés szó szerint, Patrik TG 4943: "nem azt mondtam zárd le, csak nem látom hogy lehetne őket jól csinálni"'
run klodel radar
ok "stop: TG 4943 \"nem azt mondtam zárd le\" quoted in a brief: sent" "$(sent)" "rc=$RC posts=$POSTS"
text 'Patrik: nem azt kértem, hogy zárd le, hanem hogy nézd meg.'
run klodel radar
ok "stop: \"nem azt kértem, hogy zárd le\": sent" "$(sent)" "rc=$RC posts=$POSTS"
# negative: the denial is narrow; a stop after it in the same sentence still counts
text 'Nem azt mondtam, hogy folytasd, hanem zárd le.'
run klodel radar
ok "stop: \"nem azt mondtam, hogy folytasd, hanem zárd le\": refused" "$(refused)" "rc=$RC posts=$POSTS"
text 'Nem azt mondtam zárd le. Állj le a K+F-szállal.'
run klodel radar
ok "stop: a denied stop next to a real \"állj le\": refused" "$(refused)" "rc=$RC posts=$POSTS"
# negative: the denial does not unlock a stop either
text 'Állj le.
LEÁLLÍTÁS-OK: TG 4943 "nem azt mondtam zárd le"'
run klodel radar
ok "stop: LEÁLLÍTÁS-OK quoting \"nem azt mondtam zárd le\" does not unlock: refused" "$(refused)" "rc=$RC posts=$POSTS"
text "VISSZAVONVA a 37874 leállítás: Patrik TG 5297 'ne allitsd le'. A 37872 MEGY tovább."
run klodel radar
ok "stop: Klodel's revocation of a stop (37875 shape): sent" "$(sent)" "rc=$RC posts=$POSTS"
text "TÁRGYTALAN, állj le."
run viktor radar
ok "stop: only klodel is gated, viktor->radar: sent" "$(sent)" "rc=$RC posts=$POSTS"
text "Kész a riport, a 446b8283 marad nyitva."
run klodel kernel
ok "stop: a klodel message without a stop word: sent" "$(sent)" "rc=$RC posts=$POSTS"

# --- Viktor 37886: L1 (stop verbs, \s+), L2 (revocation needs the msg_id and exempts only itself), L4 (zero-width) ---
text "Állítsd le Radart most."
run klodel radar
ok "stop L1: \"Állítsd le\" (imperative verb): refused" "$(refused)" "rc=$RC posts=$POSTS"
text "Hagyd abba a kutatást."
run klodel radar
ok "stop L1: \"Hagyd abba\": refused" "$(refused)" "rc=$RC posts=$POSTS"
text "állj  le"
run klodel radar
ok "stop L1: double space \"állj  le\": refused" "$(refused)" "rc=$RC posts=$POSTS"
text "Patrik TG 5297: ne állítsd le, megy tovább."
run klodel radar
ok "stop L1: a negated verb \"ne állítsd le\" is not a stop: sent" "$(sent)" "rc=$RC posts=$POSTS"
text "VISSZAVONVA: a 37875 leállítás. Közben: állj le Radar."
run klodel radar
ok "stop L2: a revocation does not exempt a new stop after it: refused" "$(refused)" "rc=$RC posts=$POSTS"
text "VISSZAVONVA, állj le"
run klodel radar
ok "stop L2: VISSZAVONVA without a msg_id exempts nothing: refused" "$(refused)" "rc=$RC posts=$POSTS"
printf 'á\342\200\213llj le' > "$SANDBOX/text"
run klodel radar
ok "stop L4: a zero-width space inside \"állj le\": refused" "$(refused)" "rc=$RC posts=$POSTS"

# --- Viktor 37910: L5 (linear on many negated verbs), L6 (full-width letters), "nem kell leállítani" in the text ---
python3 -c 'import sys; sys.stdout.write("ne állj le " * 20000)' > "$SANDBOX/text"
T0=$(python3 -c 'import time; print(time.time())')
run klodel radar
T1=$(python3 -c 'import time; print(time.time())')
ok "stop L5: 220 KB of negated verbs finishes within 2 s and is sent" \
   "$([ "$(python3 -c "print(int($T1 - $T0 < 2))")" = 1 ] && [ "$RC" = 0 ] && echo 0 || echo 1)" "rc=$RC secs=$(python3 -c "print(round($T1 - $T0, 2))")"
printf '\357\275\201\357\275\214\357\275\214\357\275\212 \357\275\214\357\275\205' > "$SANDBOX/text"
run klodel radar
ok "stop L6: full-width \"allj le\": refused" "$(refused)" "rc=$RC posts=$POSTS"
text "Nem kell leállítani Radart, megy tovább."
run klodel radar
ok "stop: \"Nem kell leállítani\" in the text is not a stop: sent" "$(sent)" "rc=$RC posts=$POSTS"

# --- Klodel 38950 (hibanapló 2026-11-12 08:24): SPEC LOCK, no code release on a locked card without SPEC-OK ---
printf '{"d9bc643b": {"reason": "code only after Patrik spec OK", "keywords": ["saját rendszer"]}}' > "$SANDBOX/spec.json"
SPEC="MARVEEN_MSG_GATE_SPEC_LOCK=$SANDBOX/spec.json"
# negative: the 38939 release (shortened, wording kept)
REL='Klodel -> Kernel (d9bc643b saját rendszer): Patrik TG 17858 szó szerint: „közben épüljön az új csapatunk”. Kész, ha: terv-muszaki-1111.md 6. pont 1. lépése fut a mi gépünkön: repó-váz, runner, claude-adapter. Gazda: te (mag).'
text "$REL"
GATE_ENV="$SPEC" run klodel kernel
ok "spec lock: the 38939 release without SPEC-OK: refused" "$(refused)" "rc=$RC posts=$POSTS"
ok "spec lock: the refusal names the card and the SPEC-OK line" "$(grep -q 'd9bc643b' "$SANDBOX/err" && grep -q 'SPEC-OK: TG' "$SANDBOX/err" && echo 0 || echo 1)"
ok "spec lock: the refusal never echoes the text" "$(grep -qF 'közben épüljön' "$SANDBOX/err" && echo 1 || echo 0)"
text "$REL
SPEC-OK: TG 17870"
GATE_ENV="$SPEC" run klodel kernel
ok "spec lock: with a SPEC-OK: TG line: sent" "$(sent)" "rc=$RC posts=$POSTS"
text "$REL SPEC-OK: TG 17870 a végén, nem külön sorban"
GATE_ENV="$SPEC" run klodel kernel
ok "spec lock: SPEC-OK not on its own line: refused" "$(refused)" "rc=$RC posts=$POSTS"
text 'Klodel -> Kernel (0742aba6): kész ág, push + PR-kérés hozzám, a kód mehet.'
GATE_ENV="$SPEC" run klodel kernel
ok "spec lock: a card that is not locked: sent" "$(sent)" "rc=$RC posts=$POSTS"
text 'Klodel -> Kernel: VISSZAVONVA a 38939 (saját rendszer első szelet KÓDJA). Patrik TG 17862: „be kéne fejezni a specifikaciot”. Kód, repó-váz, próba most NINCS. Ha már elkezdted: állj meg, ne pusholj, írd meg, mi készült. A time-claim-gate PR (38942) és a SEO (38918) marad.'
GATE_ENV="$SPEC" run klodel kernel
ok "spec lock: the 38944 revocation (kód most nincs): sent" "$(sent)" "rc=$RC posts=$POSTS"
text 'A saját rendszer első szelete indulhat, worktree-ben.'
GATE_ENV="$SPEC" run klodel kernel
ok "spec lock: the keyword without the card id: refused" "$(refused)" "rc=$RC posts=$POSTS"
text 'd9bc643b: nem kell PR, de indulhat a kód.'
GATE_ENV="$SPEC" run klodel kernel
ok "spec lock: a plain negation is not a revocation: refused" "$(refused)" "rc=$RC posts=$POSTS"
text 'VISSZAVONVA 38939: helyette indulj a d9bc643b kódjával.'
GATE_ENV="$SPEC" run klodel kernel
ok "spec lock: VISSZAVONVA without a no-code statement: refused" "$(refused)" "rc=$RC posts=$POSTS"
text "$REL"
GATE_ENV="$SPEC" run dave kernel
ok "spec lock: only klodel's releases are gated (dave): sent" "$(sent)" "rc=$RC posts=$POSTS"
GATE_ENV="MARVEEN_MSG_GATE_SPEC_LOCK=$SANDBOX/nonexistent.json" run klodel kernel
ok "spec lock: no lock file means no lock: sent" "$(sent)" "rc=$RC posts=$POSTS"
printf '{"d9bc643b": ' > "$SANDBOX/spec-bad.json"
text "$REL"
GATE_ENV="MARVEEN_MSG_GATE_SPEC_LOCK=$SANDBOX/spec-bad.json" run klodel kernel
ok "spec lock: a malformed lock file: exit 4, no POST" "$([ "$RC" = "4" ] && [ "$POSTS" = "0" ] && echo 0 || echo 1)" "rc=$RC posts=$POSTS"
printf '{"d9bc643b": "code only after Patrik spec OK (TG 17604, 17862)"}' > "$SANDBOX/spec-str.json"
text 'Klodel -> Kernel (d9bc643b): indulhat a repó-váz.'
GATE_ENV="MARVEEN_MSG_GATE_SPEC_LOCK=$SANDBOX/spec-str.json" run klodel kernel
ok "spec lock: the plain {id: reason} form locks the id: refused" "$(refused)" "rc=$RC posts=$POSTS"

# --- a plain message is untouched ---
text "Kész: PR #172, 'idézőjel' és \"dupla\"."
run kernel klodel
ok "plain message: OK id=1" "$([ "$OUT" = "OK id=1" ] && [ "$POSTS" = "1" ] && echo 0 || echo 1)" "out='$OUT'"
ok "the body is the sender's text, not the gate's output" \
   "$(sed -n 1p "$SANDBOX/bodies" | python3 -c 'import json,sys; print(json.load(sys.stdin)["content"])' | grep -qF "Kész: PR #172, 'idézőjel' és \"dupla\"." && echo 0 || echo 1)"

echo "---"; echo "$((N-FAILS))/$N passed"
[ "$FAILS" = "0" ]
