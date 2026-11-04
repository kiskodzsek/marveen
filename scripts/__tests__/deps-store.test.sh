#!/usr/bin/env bash
# DEPSSTORE1104 -- deps-store.sh: one install per lockfile at agents/<agent>/deps/<repo>-<lock sha, 16 hex>,
# reused when it is there, built under heavy-job.sh with npm ci --ignore-scripts, and never left half-made
# (code review 2026-10-30 #16, card f24e6745).
#
# Everything runs in a sandbox: npm and heavy-job.sh are stubs that only log, nothing is downloaded.
#
# Run:  bash scripts/__tests__/deps-store.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
DS="$ROOT/scripts/deps-store.sh"
[ -e "$DS" ] || { echo "FATAL: the script under test is missing: $DS" >&2; exit 2; }

FAILS=0; DONE=0
check() { DONE=$((DONE+1)); if [ "$2" = "0" ]; then echo "PASS  $1"; else echo "FAIL  $1${3:+  -- $3}"; FAILS=$((FAILS+1)); fi; }
ok() { [ "$@" ] && echo 0 || echo 1; }

SB="$(cd -P "$(mktemp -d "${TMPDIR:-/tmp}/depsstore.XXXXXX")" && pwd -P)"
trap 'rm -rf "$SB"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t

# heavy-job stand-in: logs its argv and its directory, then runs the command after -- (or exits $STUB_HJ_RC).
cat > "$SB/hj" <<STUB
#!/usr/bin/env bash
echo "\$PWD | \$*" >> "$SB/hj.log"
[ -n "\${STUB_HJ_RC:-}" ] && exit "\$STUB_HJ_RC"
while [ "\$1" != "--" ]; do shift; done; shift
"\$@"
STUB
# npm stand-in: "npm ci" makes an installed node_modules unless STUB_NPM_FAIL is set.
cat > "$SB/npm" <<STUB
#!/usr/bin/env bash
echo "\$*" >> "$SB/npm.log"
[ -n "\${STUB_NPM_FAIL:-}" ] && { mkdir -p node_modules/half; exit 1; }
[ -n "\${STUB_RACE_STORE:-}" ] && mkdir -p "\$STUB_RACE_STORE/node_modules" && echo '{}' > "\$STUB_RACE_STORE/node_modules/.package-lock.json"
mkdir -p node_modules/dep && echo '{}' > node_modules/.package-lock.json
STUB
chmod +x "$SB/hj" "$SB/npm"

FLEET="$SB/fleet"
mkrepo() {
  mkdir -p "$1" && git -C "$1" init -q -b main
  echo '{"name":"x"}' > "$1/package.json"
  echo "{\"lockfileVersion\":3,\"packages\":{\"\":{\"name\":\"x\"},\"node_modules/$2\":{}}}" > "$1/package-lock.json"
  git -C "$1" add -A && git -C "$1" commit -q -m init
}
ds() { rm -f "$SB/npm.log" "$SB/hj.log"; OUT="$(env MARVEEN_PROD_TREE="$FLEET" DEPS_STORE_HEAVY_JOB="$SB/hj" DEPS_STORE_NPM="$SB/npm" ${STUB_ENV:-} bash "$DS" "$@" 2>&1)"; RC=$?; }

mkrepo "$FLEET/agents/carol/repos/shop" a
git -C "$FLEET/agents/carol/repos/shop" worktree add -q "$FLEET/agents/carol/repos/shop-wt" -b feat/x
H="$(shasum -a 256 "$FLEET/agents/carol/repos/shop/package-lock.json" | cut -c1-16)"
STORE="$FLEET/agents/carol/deps/shop-$H"

echo "== --dry: names the store, installs nothing"
ds --dry "$FLEET/agents/carol/repos/shop-wt"
check "exit 0, the store path on stdout" "$(ok "$RC" = 0 -a -n "$(echo "$OUT" | grep -x "$STORE")")" "$RC $OUT"
check "named after the main clone's directory and the lock hash, in the agent's own deps/" "$(ok -n "$(echo "$OUT" | grep -F "/agents/carol/deps/shop-$H")")" "$OUT"
check "nothing ran, nothing made" "$(ok ! -f "$SB/npm.log" -a ! -e "$STORE" -a ! -e "$STORE.partial")"

echo "== the install"
ds "$FLEET/agents/carol/repos/shop-wt"
check "exit 0, the store path on stdout" "$(ok "$RC" = 0 -a "$(echo "$OUT" | tail -1)" = "$STORE")" "$RC $OUT"
check "installed: node_modules/.package-lock.json, package.json and the lockfile beside it" "$(ok -f "$STORE/node_modules/.package-lock.json" -a -f "$STORE/package.json" -a -f "$STORE/package-lock.json")"
check "the lockfile is the worktree's, byte for byte" "$(cmp -s "$STORE/package-lock.json" "$FLEET/agents/carol/repos/shop-wt/package-lock.json" && echo 0 || echo 1)"
check "npm ci --ignore-scripts, nothing else" "$(ok "$(cat "$SB/npm.log")" = "ci --ignore-scripts --no-audit --no-fund")" "$(cat "$SB/npm.log")"
check "under heavy-job.sh, run in the .partial directory" "$(ok -n "$(grep -F "$STORE.partial | --name deps-store-shop -- " "$SB/hj.log")")" "$(cat "$SB/hj.log")"
check "no .partial left" "$(ok ! -e "$STORE.partial")"

echo "== an existing store is reused"
ds "$FLEET/agents/carol/repos/shop"
check "the main clone of the same lockfile: exit 0, same store, no install" "$(ok "$RC" = 0 -a "$OUT" = "$STORE" -a ! -f "$SB/npm.log")" "$RC $OUT"

git clone -q "$FLEET/agents/carol/repos/shop" "$FLEET/agents/carol/repos/shop-2"
ds "$FLEET/agents/carol/repos/shop-2"
check "a clone under another name, same lockfile: the existing store, no install" "$(ok "$RC" = 0 -a "$OUT" = "$STORE" -a ! -f "$SB/npm.log")" "$RC $OUT"

echo "== a failed install leaves nothing"
mkrepo "$FLEET/agents/carol/repos/other" b
H2="$(shasum -a 256 "$FLEET/agents/carol/repos/other/package-lock.json" | cut -c1-16)"
STUB_ENV="STUB_NPM_FAIL=1" ds "$FLEET/agents/carol/repos/other"
check "exit 3" "$(ok "$RC" = 3)" "$RC $OUT"
check "no store, no .partial" "$(ok ! -e "$FLEET/agents/carol/deps/other-$H2" -a ! -e "$FLEET/agents/carol/deps/other-$H2.partial")"
STUB_ENV="STUB_HJ_RC=75" ds "$FLEET/agents/carol/repos/other"
check "heavy-job.sh busy: exit 75, nothing ran, nothing left" "$(ok "$RC" = 75 -a ! -f "$SB/npm.log" -a ! -e "$FLEET/agents/carol/deps/other-$H2.partial")" "$RC $OUT"

echo "== two runs of one lockfile (Viktor 26587 LOW-1)"
mkrepo "$FLEET/agents/carol/repos/race" d
H3="$(shasum -a 256 "$FLEET/agents/carol/repos/race/package-lock.json" | cut -c1-16)"
R3="$FLEET/agents/carol/deps/race-$H3"
mkdir -p "$R3.partial" && echo first > "$R3.partial/marker"
ds "$FLEET/agents/carol/repos/race"
check "a .partial in place: exit 75, the other run's files untouched, nothing ran" "$(ok "$RC" = 75 -a -f "$R3.partial/marker" -a ! -f "$SB/npm.log")" "$RC $OUT"
# Its own lockfile, so no earlier case has built this store already.
mkrepo "$FLEET/agents/carol/repos/race2" g
H6="$(shasum -a 256 "$FLEET/agents/carol/repos/race2/package-lock.json" | cut -c1-16)"
R6="$FLEET/agents/carol/deps/race2-$H6"
STUB_ENV="STUB_RACE_STORE=$R6" ds "$FLEET/agents/carol/repos/race2"
check "the store appeared during the install: exit 0, that store, nothing nested in it, no .partial" "$(ok "$RC" = 0 -a "$(echo "$OUT" | tail -1)" = "$R6" -a -f "$SB/npm.log" -a -z "$(ls "$R6" | grep partial)" -a ! -e "$R6.partial")" "$RC $OUT $(ls "$R6")"

echo "== a lock left by a killed run (Viktor 26594)"
mkrepo "$FLEET/agents/carol/repos/stale" h
H7="$(shasum -a 256 "$FLEET/agents/carol/repos/stale/package-lock.json" | cut -c1-16)"
R7="$FLEET/agents/carol/deps/stale-$H7"
DEAD=99997; while ps -p "$DEAD" >/dev/null 2>&1; do DEAD=$((DEAD-1)); done
mkdir -p "$R7.partial/node_modules/half" && echo "$DEAD" > "$R7.partial/.deps-store.pid"
ds "$FLEET/agents/carol/repos/stale"
check "its pid is not running: taken over, installed, exit 0, no .partial, no .takeover" "$(ok "$RC" = 0 -a "$(echo "$OUT" | tail -1)" = "$R7" -a -f "$R7/node_modules/.package-lock.json" -a ! -e "$R7/node_modules/half" -a ! -e "$R7.partial" -a ! -e "$R7.partial.takeover")" "$RC $OUT"
check "the takeover is said on stderr" "$(ok -n "$(echo "$OUT" | grep -F 'taking it over')")" "$OUT"
check "the store holds no pid file of the lock" "$(ok ! -e "$R7/.deps-store.pid")"
rm -rf "$R7"
mkdir -p "$R7.partial" && echo "$$" > "$R7.partial/.deps-store.pid" && echo live > "$R7.partial/marker"
ds "$FLEET/agents/carol/repos/stale"
check "its pid is running: exit 75, untouched, nothing ran" "$(ok "$RC" = 75 -a -f "$R7.partial/marker" -a ! -f "$SB/npm.log")" "$RC $OUT"
rm -rf "$R7.partial"
mkdir -p "$R7.partial" && echo old > "$R7.partial/marker" && touch -t 202601010000 "$R7.partial"
ds "$FLEET/agents/carol/repos/stale"
check "no pid file, unchanged for over 10 minutes: taken over, exit 0" "$(ok "$RC" = 0 -a -f "$R7/node_modules/.package-lock.json" -a ! -e "$R7/marker" -a ! -e "$R7.partial")" "$RC $OUT"
rm -rf "$R7"
mkdir -p "$R7.partial" "$R7.partial.takeover" && echo "$DEAD" > "$R7.partial/.deps-store.pid"
ds "$FLEET/agents/carol/repos/stale"
check "stale, but another run holds the takeover: exit 75, its lock untouched, nothing ran" "$(ok "$RC" = 75 -a -f "$R7.partial/.deps-store.pid" -a -d "$R7.partial.takeover" -a ! -f "$SB/npm.log")" "$RC $OUT"
rm -rf "$R7.partial" "$R7.partial.takeover"
mkdir -p "$R7.partial" && : > "$R7.partial/.deps-store.pid" && touch -t 202601010000 "$R7.partial"
ds "$FLEET/agents/carol/repos/stale"
check "an empty pid file, unchanged for over 10 minutes: the mtime rule, taken over (Viktor 26615 INFO-1)" "$(ok "$RC" = 0 -a -f "$R7/node_modules/.package-lock.json" -a ! -e "$R7.partial")" "$RC $OUT"
rm -rf "$R7"
mkdir -p "$SB/badps" && printf '#!/bin/sh\nexit 1\n' > "$SB/badps/ps" && chmod +x "$SB/badps/ps"
mkdir -p "$R7.partial" && echo "$DEAD" > "$R7.partial/.deps-store.pid" && echo held > "$R7.partial/marker"
STUB_ENV="PATH=$SB/badps:$PATH" ds "$FLEET/agents/carol/repos/stale"
check "ps fails for every pid: not taken over, exit 75, untouched (Viktor 26615 LOW-1)" "$(ok "$RC" = 75 -a -f "$R7.partial/marker" -a ! -f "$SB/npm.log")" "$RC $OUT"
check "the 75 names the pid and the way out by hand (Viktor 26615 INFO-2)" "$(ok -n "$(echo "$OUT" | grep -F "pid: $DEAD" | grep -F "rm -rf $R7.partial")")" "$OUT"
rm -rf "$R7.partial"
ds "$FLEET/agents/carol/repos/stale"
check "a clean run writes no pid file into the store" "$(ok "$RC" = 0 -a ! -e "$R7/.deps-store.pid")" "$RC $OUT"

echo "== .npmrc (Viktor 26587 INFO-1)"
mkrepo "$FLEET/agents/carol/repos/rc1" e
printf '//registry.npmjs.org/:_authToken=FAKE-TEST-TOKEN\n' > "$FLEET/agents/carol/repos/rc1/.npmrc"
H4="$(shasum -a 256 "$FLEET/agents/carol/repos/rc1/package-lock.json" | cut -c1-16)"
ds "$FLEET/agents/carol/repos/rc1"
check "an .npmrc with a token: exit 64, no store, no copy, the token not printed" "$(ok "$RC" = 64 -a ! -e "$FLEET/agents/carol/deps/rc1-$H4" -a ! -e "$FLEET/agents/carol/deps/rc1-$H4.partial" -a -z "$(echo "$OUT" | grep FAKE-TEST-TOKEN)")" "$RC $OUT"
mkrepo "$FLEET/agents/carol/repos/rc2" f
printf 'fund=false\n' > "$FLEET/agents/carol/repos/rc2/.npmrc"
H5="$(shasum -a 256 "$FLEET/agents/carol/repos/rc2/package-lock.json" | cut -c1-16)"
ds "$FLEET/agents/carol/repos/rc2"
check "an .npmrc without a credential is copied" "$(ok "$RC" = 0 -a -f "$FLEET/agents/carol/deps/rc2-$H5/.npmrc")" "$RC $OUT"

echo "== usage"
mkrepo "$SB/outside" c
ds "$SB/outside"
check "not under <prod>/agents/<agent>/: 64" "$(ok "$RC" = 64)" "$RC $OUT"
mkdir -p "$FLEET/agents/carol/nolock"
ds "$FLEET/agents/carol/nolock"
check "no package-lock.json: 64" "$(ok "$RC" = 64)" "$RC $OUT"
ds
check "no argument: 64" "$(ok "$RC" = 64)" "$RC"

echo
echo "$((DONE-FAILS))/$DONE passed"
[ "$FAILS" = "0" ] || exit 1
