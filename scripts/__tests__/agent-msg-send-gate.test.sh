#!/usr/bin/env bash
# agent-msg.sh send gate (card aba42256, DREAM 11-11): scripts/lib/msg_gate.py in front of the POST.
#
# WHAT THIS GUARDS. Refused with exit 3 and ZERO POSTs: a secret shape from src/security/secret-gate.ts to anyone;
# to or from majsztro, more than 12 000 characters or an e-mail address outside marabel.hu / myshp.hu. The refusal
# never echoes the matched value. Sent (one POST): exactly 12 000 characters to majsztro, our own addresses to
# majsztro, a long text or a foreign address between other agents. A broken gate (unreadable or emptied pattern
# source) is exit 4 with zero POSTs, never a silent "clean". A missing gate file sends with a WARN.
#
# Retro R5 (card 858f80bc): a klodel work order on a Patrik TG is refused without a KERES-SZO-SZERINT line whose
# quote is in that inbound TG message of a synthetic ledger, and without IGEN: TG m when the source is an idea.
#
# Retro R10 (card 1f943050): a shared/**.md file Radar delivers (a delivery word on the path's line) must pass
# scripts/lib/hiany_lint.py; a mention, a negated delivery, another sender pass; the lint missing is exit 4.
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

# Synthetic Telegram ledger for the request rule (rule 5): conversation_log rows (chat, message_id, direction,
# text, created_at). Chat 111 is the private chat, -222 the group; id 500 exists in both (as measured live).
python3 - "$SANDBOX/ledger.db" <<'PY2'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
con.execute("CREATE TABLE conversation_log (id INTEGER PRIMARY KEY, agent_id TEXT, chat_id TEXT, direction TEXT, "
            "message_id TEXT, text TEXT, ts TEXT, created_at INTEGER)")
rows = [
    ('111', '17858', 'in', 'közben épüljön az új csapatunk', 1000),
    ('111', '18000', 'in', 'Csináljuk meg a receptkönyv borítóját holnapra.', 2000),
    ('111', '18009', 'in', 'igen', 2900),
    ('111', '18010', 'in', 'mi lenne ha csinálnánk egy AI influenszert?', 3000),
    ('111', '18011', 'in', 'igen, mehet', 3100),
    ('-222', '18012', 'in', 'igen', 3200),
    ('111', '18013', 'in', 'nem jó, így ne', 3300),
    ('111', '18014', 'in', 'ok?', 3400),
    ('111', '500', 'in', 'a borító legyen kék', 4000),
    ('-222', '500', 'in', 'lehetne zöld is a háttér', 4100),
    ('111', '18020', 'out', 'készítsd el a teljes tervet most', 5000),
    ('111', '18030', 'in', 'Lehetne egy új oldal. Csináld meg a gombot!', 6000),
    ('111', '18040', 'in', 'Csináld meg a borítót. Lehetne kék is.', 7000),
    ('111', '18050', 'in', 'Megcsinálod a borítót holnapra?', 8000),
    ('111', '18060', 'in', 'Esetleg csináld meg a borítót.', 9000),
    ('111', '18061', 'in', 'Szerintem a gomb legyen piros.', 9100),
    ('111', '18062', 'in', 'Mi van, ha kékre festjük a hátteret.', 9200),
    ('111', '18063', 'in', 'Mi van ha zöld lesz a háttér.', 9300),
]
con.executemany("INSERT INTO conversation_log (agent_id, chat_id, message_id, direction, text, created_at) "
                "VALUES ('klodel', ?, ?, ?, ?, ?)", rows)
con.commit()
PY2

# run <from> <to> ; the text comes from $SANDBOX/text (STDIN mode, so 20 000 characters fit)
run() {
  : > "$SANDBOX/bodies"
  OUT="$(env PATH="$BIN:$PATH" BODIES="$SANDBOX/bodies" MARVEEN_TOKEN_FILE="$SANDBOX/token" \
             MARVEEN_MAJSZTRO_STATE=/nonexistent MARVEEN_HOMOGLYPH_BIN=/nonexistent \
             MARVEEN_MSG_GATE_LEDGER="$SANDBOX/ledger.db" ${GATE_ENV:-} \
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
REL='KERES-SZO-SZERINT: „közben épüljön az új csapatunk” (TG 17858)
Klodel -> Kernel (d9bc643b saját rendszer): Patrik TG 17858 szó szerint: „közben épüljön az új csapatunk”. Kész, ha: terv-muszaki-1111.md 6. pont 1. lépése fut a mi gépünkön: repó-váz, runner, claude-adapter. Gazda: te (mag).'
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

# --- retro R5 (card 858f80bc): a work order on a Patrik TG carries the request verbatim, an idea needs IGEN ---
WO='Kernel, Patrik TG 18000 kérése. Kész, ha: a borító kész, mobil és asztali képpel.'
text "$WO"
run klodel dave
ok "keres: a work order on a Patrik TG without KERES-SZO-SZERINT: refused" "$(refused)" "rc=$RC posts=$POSTS"
ok "keres: the refusal names the KERES-SZO-SZERINT line" "$(grep -q 'KERES-SZO-SZERINT' "$SANDBOX/err" && echo 0 || echo 1)"
text "$WO
KERES-SZO-SZERINT: \"Csináljuk meg a receptkönyv borítóját\" (TG 18000)"
run klodel dave
ok "keres: a verbatim quote found in TG 18000: sent" "$(sent)" "rc=$RC posts=$POSTS"
text "$WO
KERES-SZO-SZERINT: \"csinaljuk  meg a receptkonyv boritojat\" (TG 18000)"
run klodel dave
ok "keres: accent- and whitespace-free quote: sent" "$(sent)" "rc=$RC posts=$POSTS"
text "$WO
KÉRÉS-SZÓ-SZERINT: „Csináljuk meg a receptkönyv borítóját” (TG 18000)"
run klodel dave
ok "keres: accented label and Hungarian quotes: sent" "$(sent)" "rc=$RC posts=$POSTS"
text "$WO
KERES-SZO-SZERINT: \"csináljuk meg a teljes webshopot\" (TG 18000)"
run klodel dave
ok "keres: a quote Patrik did not write: refused" "$(refused)" "rc=$RC posts=$POSTS"
ok "keres: the refusal never echoes the quote" "$(grep -qF 'teljes webshopot' "$SANDBOX/err" && echo 1 || echo 0)"
text "$WO
KERES-SZO-SZERINT: \"Csináljuk meg\" (TG 18000)"
run klodel dave
ok "keres: a two-word quote: refused" "$(refused)" "rc=$RC posts=$POSTS"
text "$WO
KERES-SZO-SZERINT: \"Csináljuk meg a receptkönyv borítóját\" (TG 18999)"
run klodel dave
ok "keres: a TG that is not in the ledger: refused" "$(refused)" "rc=$RC posts=$POSTS"
text "$WO
KERES-SZO-SZERINT: \"készítsd el a teljes tervet\" (TG 18020)"
run klodel dave
ok "keres: our own outbound message is not Patrik's words: refused" "$(refused)" "rc=$RC posts=$POSTS"
text "$WO KERES-SZO-SZERINT: \"Csináljuk meg a receptkönyv borítóját\" (TG 18000)"
run klodel dave
ok "keres: KERES-SZO-SZERINT not on its own line: refused" "$(refused)" "rc=$RC posts=$POSTS"
# an idea (TG 17827/17829 shape): a question or conditional source needs Patrik's later yes in the same chat
IDEA='FELADAT (Patrik TG 18010), gazda: radar
KERES-SZO-SZERINT: "csinálnánk egy AI influenszert" (TG 18010)
Kész, ha: terv a kártyán.'
text "$IDEA"
run klodel radar
ok "keres: a conditional source without IGEN: refused" "$(refused)" "rc=$RC posts=$POSTS"
ok "keres: the refusal names the IGEN line" "$(grep -q 'IGEN: TG' "$SANDBOX/err" && echo 0 || echo 1)"
text "$IDEA
IGEN: TG 18011"
run klodel radar
ok "keres: with IGEN: TG 18011 (later, same chat, \"igen, mehet\"): sent" "$(sent)" "rc=$RC posts=$POSTS"
text "$IDEA
IGEN: TG 18012"
run klodel radar
ok "keres: a yes from another chat: refused" "$(refused)" "rc=$RC posts=$POSTS"
text "$IDEA
IGEN: TG 18009"
run klodel radar
ok "keres: a yes from before the idea: refused" "$(refused)" "rc=$RC posts=$POSTS"
text "$IDEA
IGEN: TG 18013"
run klodel radar
ok "keres: a negated \"nem jó\": refused" "$(refused)" "rc=$RC posts=$POSTS"
text "$IDEA
IGEN: TG 18014"
run klodel radar
ok "keres: \"ok?\" is a question, not a yes: refused" "$(refused)" "rc=$RC posts=$POSTS"
# the same message_id in both chats (measured live): each quote is checked where it is found
text "$WO
KERES-SZO-SZERINT: \"a borító legyen kék\" (TG 500)"
run klodel dave
ok "keres: TG 500, the private-chat sentence (imperative): sent" "$(sent)" "rc=$RC posts=$POSTS"
text "$WO
KERES-SZO-SZERINT: \"zöld is a háttér\" (TG 500)"
run klodel dave
ok "keres: TG 500, the group sentence (\"lehetne\") without IGEN: refused" "$(refused)" "rc=$RC posts=$POSTS"
# the source sentence is the quote's own: an idea next to an order does not taint it, and the reverse
text "$WO
KERES-SZO-SZERINT: \"Csináld meg a gombot\" (TG 18030)"
run klodel dave
ok "keres: an order after an idea sentence in the same message: sent" "$(sent)" "rc=$RC posts=$POSTS"
text "$WO
KERES-SZO-SZERINT: \"Lehetne egy új oldal\" (TG 18030)"
run klodel dave
ok "keres: the idea sentence of the same message: refused" "$(refused)" "rc=$RC posts=$POSTS"
text "$WO
KERES-SZO-SZERINT: \"Csináld meg a borítót.\" (TG 18040)"
run klodel dave
ok "keres: a quote ending in \".\" before an idea sentence: sent" "$(sent)" "rc=$RC posts=$POSTS"
text "$WO
KERES-SZO-SZERINT: \"Megcsinálod a borítót holnapra\" (TG 18050)"
run klodel dave
ok "keres: a plain question (\"?\" only, no idea word) without IGEN: refused" "$(refused)" "rc=$RC posts=$POSTS"
# Viktor 41430 INFO 4: esetleg / szerintem / mi van ha are idea marks too
# (each quote is also sent with its IGEN, so a refusal for any other reason would show)
for pair in '18060|Esetleg csináld meg a borítót' '18061|Szerintem a gomb legyen piros' \
            '18062|Mi van, ha kékre festjük a hátteret' '18062|kékre festjük a hátteret' \
            '18063|zöld lesz a háttér'; do
  tg="${pair%%|*}"; q="${pair#*|}"
  text "$WO
KERES-SZO-SZERINT: \"$q\" (TG $tg)"
  run klodel dave
  ok "keres: idea mark, \"$q\" (TG $tg) without IGEN: refused" "$(refused)" "rc=$RC posts=$POSTS"
  ok "keres: the refusal is the IGEN one" "$(grep -q 'IGEN: TG' "$SANDBOX/err" && echo 0 || echo 1)"
done
# Viktor 41430 INFO 1: a ledger path with ? # % keeps mode=ro and opens the right file; the connection is read-only
mkdir -p "$SANDBOX/a?b#c%d" && cp "$SANDBOX/ledger.db" "$SANDBOX/a?b#c%d/ledger.db"
text "$WO
KERES-SZO-SZERINT: \"Csináljuk meg a receptkönyv borítóját\" (TG 18000)"
GATE_ENV="MARVEEN_MSG_GATE_LEDGER=$SANDBOX/a?b#c%d/ledger.db" run klodel dave
ok "keres: a ledger under a path with ? # %: read, sent" "$(sent)" "rc=$RC posts=$POSTS"
RO="$(python3 -I - "$GATE" "$SANDBOX/a?b#c%d/ledger.db" <<'PY3'
import importlib.util, sqlite3, sys
spec = importlib.util.spec_from_file_location('mg', sys.argv[1]); mg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mg)
con = mg.open_ledger(sys.argv[2])
try:
    con.execute('CREATE TABLE w (a)')
    print('writable')
except sqlite3.OperationalError as e:
    print('readonly' if 'readonly' in str(e) else 'other: %s' % e)
PY3
)"
ok "keres: the gate's ledger connection refuses a write (mode=ro)" "$([ "$RO" = readonly ] && echo 0 || echo 1)" "got=$RO"
# the header's TG must be the quoted one; every KERES line must hold
text 'FELADAT (Patrik TG 18010), gazda: dave
KERES-SZO-SZERINT: "Csináljuk meg a receptkönyv borítóját" (TG 18000)
Kész, ha: kész.'
run klodel dave
ok "keres: FELADAT header TG not quoted (another TG quoted): refused" "$(refused)" "rc=$RC posts=$POSTS"
text "$WO
KERES-SZO-SZERINT: \"Csináljuk meg a receptkönyv borítóját\" (TG 18000)
KERES-SZO-SZERINT: \"csináljuk meg a teljes webshopot\" (TG 18000)"
run klodel dave
ok "keres: one valid and one false KERES line: refused" "$(refused)" "rc=$RC posts=$POSTS"
# scope
text "$WO"
run dave kernel
ok "keres: only klodel's work orders are gated (dave): sent" "$(sent)" "rc=$RC posts=$POSTS"
text 'A Patrik TG 18000 szerinti borító kész, a kártya done.'
run klodel kernel
ok "keres: a Patrik TG without a work order: sent" "$(sent)" "rc=$RC posts=$POSTS"
text 'Kész, ha: a CI zöld és a PR mergelve.'
run klodel kernel
ok "keres: a work order without a Patrik TG: sent" "$(sent)" "rc=$RC posts=$POSTS"
text "$WO
KERES-SZO-SZERINT: \"Csináljuk meg a receptkönyv borítóját\" (TG 18000)"
GATE_ENV="MARVEEN_MSG_GATE_LEDGER=$SANDBOX/nonexistent.db" run klodel dave
ok "keres: the ledger missing when the rule fires: exit 4, no POST" "$([ "$RC" = "4" ] && [ "$POSTS" = "0" ] && echo 0 || echo 1)" "rc=$RC posts=$POSTS"
text 'Kész a riport.'
GATE_ENV="MARVEEN_MSG_GATE_LEDGER=$SANDBOX/nonexistent.db" run klodel dave
ok "keres: the ledger missing when the rule does not fire: sent" "$(sent)" "rc=$RC posts=$POSTS"

# --- retro R10 (card 1f943050): a shared file Radar DELIVERS must pass scripts/lib/hiany_lint.py ---
HR="$SANDBOX/root"; mkdir -p "$HR/shared/k"
printf 'Nyitott felhívás: NINCS ADAT\n' > "$HR/shared/k/bad.md"
printf -- '- eMAG: NINCS ADAT, 410 botvédelem (emag.hu, 11-13)\n' > "$HR/shared/k/good.md"
printf 'Ilyen itthon nincs.\n' > "$HR/shared/k/itthon.md"
HROOT="MARVEEN_HIANY_ROOT=$HR"
text 'KÉSZ: shared/k/bad.md, a 3. pont kész.'
GATE_ENV="$HROOT" run radar klodel
ok "hiany: a delivered file with a bare NINCS ADAT: refused" "$(refused)" "rc=$RC posts=$POSTS"
ok "hiany: the refusal names the file and R10b" "$(grep -q 'shared/k/bad.md' "$SANDBOX/err" && grep -q 'R10b' "$SANDBOX/err" && echo 0 || echo 1)"
text 'Leadva: /Users/klodel/marveen/shared/k/itthon.md'
GATE_ENV="$HROOT" run radar klodel
ok "hiany: an absolute path, an absence claim without ITTHON-MERT: refused (R10a)" "$(refused)" "rc=$RC posts=$POSTS"
ok "hiany: the refusal says R10a" "$(grep -q 'R10a' "$SANDBOX/err" && echo 0 || echo 1)"
text 'KÉSZ: shared/k/good.md (forrás a soron).'
GATE_ENV="$HROOT" run radar klodel
ok "hiany: a delivered file that passes the lint: sent" "$(sent)" "rc=$RC posts=$POSTS"
text 'Dave riportja (shared/k/bad.md) alapján dolgozom, a saját anyagom holnap.'
GATE_ENV="$HROOT" run radar klodel
ok "hiany: a mere mention of a file, no delivery word: sent (Radar 41293)" "$(sent)" "rc=$RC posts=$POSTS"
text 'A shared/k/bad.md még nem kész, parkolva.'
GATE_ENV="$HROOT" run radar klodel
ok "hiany: \"még nem kész\" is not a delivery: sent" "$(sent)" "rc=$RC posts=$POSTS"
text 'Kész.
Háttér: shared/k/bad.md'
GATE_ENV="$HROOT" run radar klodel
ok "hiany: the delivery word on another line than the path: sent" "$(sent)" "rc=$RC posts=$POSTS"
text 'KÉSZ: shared/k/nincs-ilyen.md'
GATE_ENV="$HROOT" run radar klodel
ok "hiany: a delivered file that does not exist: refused" "$(refused)" "rc=$RC posts=$POSTS"
text 'KÉSZ: shared/../../etc/x.md'
GATE_ENV="$HROOT" run radar klodel
ok "hiany: a path that leaves shared/: refused" "$(refused)" "rc=$RC posts=$POSTS"
printf 'Semmi hiány.\n' > "$HR/outside.md"
text 'KÉSZ: shared/../outside.md'
GATE_ENV="$HROOT" run radar klodel
ok "hiany: a clean, existing file outside shared/ (via ..): refused" "$(refused)" "rc=$RC posts=$POSTS"
# Viktor 41461 INFO 4: a symlink inside shared/ that resolves to a sibling "shared-evil/" (prefix without separator)
# or out of the install (abspath instead of realpath) is refused
mkdir -p "$HR/shared-evil" "$SANDBOX/out"; printf 'Semmi hiány.\n' > "$HR/shared-evil/x.md"; printf 'Semmi hiány.\n' > "$SANDBOX/out/y.md"
ln -s "$HR/shared-evil/x.md" "$HR/shared/k/evil.md"; ln -s "$SANDBOX/out/y.md" "$HR/shared/k/out.md"
text 'KÉSZ: shared/k/evil.md'
GATE_ENV="$HROOT" run radar klodel
ok "hiany: a symlink in shared/ to a sibling shared-evil/: refused" "$(refused)" "rc=$RC posts=$POSTS"
text 'KÉSZ: shared/k/out.md'
GATE_ENV="$HROOT" run radar klodel
ok "hiany: a symlink in shared/ out of the install: refused" "$(refused)" "rc=$RC posts=$POSTS"
# Viktor 41461 LOW 3: a long run of "shared/" without a blank stays linear
python3 -c 'import sys; sys.stdout.write("kész " + "shared/" * 20000)' > "$SANDBOX/text"
T0=$(python3 -c 'import time; print(time.time())')
GATE_ENV="$HROOT" run radar klodel
T1=$(python3 -c 'import time; print(time.time())')
ok "hiany: 140 KB of shared/ on a delivery line finishes within 2 s" "$([ "$(python3 -c "print(int($T1 - $T0 < 2))")" = 1 ] && echo 0 || echo 1)" "secs=$(python3 -c "print(round($T1 - $T0, 2))")"
text 'KÉSZ: shared/k/bad.md'
GATE_ENV="$HROOT" run kernel klodel
ok "hiany: only radar's deliveries are linted (kernel): sent" "$(sent)" "rc=$RC posts=$POSTS"
# the lint missing next to the gate: exit 4, nothing sent (never a silent pass)
mkdir -p "$SANDBOX/gate-only"; cp "$GATE" "$SANDBOX/gate-only/msg_gate.py"
text 'KÉSZ: shared/k/good.md'
GATE_ENV="$HROOT MARVEEN_MSG_GATE_BIN=$SANDBOX/gate-only/msg_gate.py MARVEEN_MSG_GATE_SECRET_SRC=$ROOT/src/security/secret-gate.ts" run radar klodel
ok "hiany: the lint missing when the rule fires: exit 4, no POST" "$([ "$RC" = "4" ] && [ "$POSTS" = "0" ] && echo 0 || echo 1)" "rc=$RC posts=$POSTS"
text 'Kész a heti összefoglaló, nincs fájl.'
GATE_ENV="$HROOT MARVEEN_MSG_GATE_BIN=$SANDBOX/gate-only/msg_gate.py MARVEEN_MSG_GATE_SECRET_SRC=$ROOT/src/security/secret-gate.ts" run radar klodel
ok "hiany: the lint missing, no delivered file: sent" "$(sent)" "rc=$RC posts=$POSTS"

# --- a plain message is untouched ---
text "Kész: PR #172, 'idézőjel' és \"dupla\"."
run kernel klodel
ok "plain message: OK id=1" "$([ "$OUT" = "OK id=1" ] && [ "$POSTS" = "1" ] && echo 0 || echo 1)" "out='$OUT'"
ok "the body is the sender's text, not the gate's output" \
   "$(sed -n 1p "$SANDBOX/bodies" | python3 -c 'import json,sys; print(json.load(sys.stdin)["content"])' | grep -qF "Kész: PR #172, 'idézőjel' és \"dupla\"." && echo 0 || echo 1)"

echo "---"; echo "$((N-FAILS))/$N passed"
[ "$FAILS" = "0" ]
