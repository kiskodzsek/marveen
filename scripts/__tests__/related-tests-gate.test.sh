#!/bin/bash
# Negative + positive test of the push-time related-tests gate (retro R7, card a8354557).
# Run: bash scripts/__tests__/related-tests-gate.test.sh
#
# Hermetic: a temp bare "origin" and a temp clone that carries copies of the installers and the gate; the
# installer writes into THAT clone's .git/hooks. The clone's node_modules/.bin/vitest is a shim that records its
# arguments and the GIT_* variables it sees and exits with the code the case wants, so no real vitest runs and
# nothing touches the network or this checkout's hooks.
#
# Asserts: a push that changes scripts/hooks/* or .claude/settings.json runs the two corpus scans plus the tests
# that name the changed hook, and a failing test STOPS the push (the branch never reaches origin); a push that
# touches no hook path runs nothing; every "cannot check" case (not HEAD, dirty tree, no node_modules, gate
# script missing) refuses; a branch deletion passes; the installer is idempotent and writes only into its own repo.

set -u
PASS=0; FAIL=0
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

SRC="$(cd "$(dirname "$0")/../.." && pwd)"
ORIGIN="$TMP/origin.git"
CLONE="$TMP/clone"
CALLS="$TMP/vitest-calls.log"
ENVLOG="$TMP/vitest-env.log"
export NPX_CALLS="$CALLS" VT_ENV="$ENVLOG"
make_vitest() { # the shim lives in the clone's node_modules/.bin, where the gate looks for it
  mkdir -p "$CLONE/node_modules/.bin"
  cat > "$CLONE/node_modules/.bin/vitest" <<'EOF'
#!/bin/bash
echo "$*" >> "$NPX_CALLS"
echo "GIT_DIR=${GIT_DIR:-} GIT_INDEX_FILE=${GIT_INDEX_FILE:-} GIT_WORK_TREE=${GIT_WORK_TREE:-}" >> "$VT_ENV"
exit "${NPX_RC:-0}"
EOF
  chmod +x "$CLONE/node_modules/.bin/vitest"
}

git_q() { git -C "$CLONE" -c user.email=t@t -c user.name=t "$@"; }

git init -q --bare -b main "$ORIGIN"
git clone -q "$ORIGIN" "$CLONE" 2>/dev/null
mkdir -p "$CLONE/scripts/git-hooks" "$CLONE/scripts/hooks" "$CLONE/src/__tests__" "$CLONE/.claude"
cp "$SRC/scripts/git-hooks/related-tests-gate.sh" "$CLONE/scripts/git-hooks/"
cp "$SRC/scripts/install-git-related-tests-hook.sh" "$SRC/scripts/install-git-guard-hook.sh" "$CLONE/scripts/"
: > "$CLONE/src/__tests__/hook-registration-completeness.test.ts"
: > "$CLONE/src/__tests__/project-settings-hook-anchor.test.ts"
echo "{}" > "$CLONE/.claude/settings.json"
echo "base" > "$CLONE/README.md"
git_q checkout -q -b main 2>/dev/null
git_q add -A && git_q commit -q -m base && git_q push -q origin main 2>/dev/null
make_vitest; echo "node_modules/" > "$CLONE/.gitignore"; git_q add .gitignore && git_q commit -q -m ignore && git_q push -q origin main 2>/dev/null

# The real checkout's stub (if the installer ran there on purpose) must come out of this test exactly as it went in:
# a fingerprint, not "does not exist" (that failed on every machine where the installer had legitimately run).
# --git-common-dir also covers a linked worktree, where $SRC/.git is a file.
REAL_HOOKS="$(cd "$SRC" && cd "$(git rev-parse --git-common-dir 2>/dev/null)" 2>/dev/null && pwd)/hooks/pre-push.d"
real_stub_fp() { if [ -e "$REAL_HOOKS/20-related-tests-gate" ]; then shasum "$REAL_HOOKS/20-related-tests-gate" | cut -d' ' -f1; else echo absent; fi; }
REAL_STUB_BEFORE="$(real_stub_fp)"
echo "== installer"
( cd "$TMP" && bash "$CLONE/scripts/install-git-related-tests-hook.sh" >/dev/null 2>&1 ) && pass "installer runs from another cwd" || fail "installer failed"
STUB="$CLONE/.git/hooks/pre-push.d/20-related-tests-gate"
[ -x "$STUB" ] && pass "stub installed in the clone's own .git/hooks" || fail "stub missing"
grep -q "$CLONE/scripts/git-hooks/related-tests-gate.sh" "$STUB" && pass "stub points at the clone's tracked gate" || fail "stub path wrong"
[ -x "$CLONE/.git/hooks/pre-push.d/10-no-force-push-protected" ] && pass "guard dispatcher installed first" || fail "dispatcher missing"
H1="$(shasum "$STUB" | cut -d' ' -f1)"
( cd "$TMP" && bash "$CLONE/scripts/install-git-related-tests-hook.sh" >/dev/null 2>&1 )
[ "$H1" = "$(shasum "$STUB" | cut -d' ' -f1)" ] && pass "second run is a no-op (identical stub)" || fail "not idempotent"
[ "$(real_stub_fp)" = "$REAL_STUB_BEFORE" ] && pass "this checkout's hooks were not touched by the test" || fail "test wrote into the real repo"

push() { # <branch> -> exit code of git push, output in $TMP/push.out
  git -C "$CLONE" push -q origin "$1" >"$TMP/push.out" 2>&1
}
on_origin() { git -C "$ORIGIN" rev-parse -q --verify "refs/heads/$1" >/dev/null 2>&1; }
new_branch() { git_q checkout -q main && git_q checkout -q -b "$1" && mkdir -p "$CLONE/scripts/hooks"; }

echo "== a push that touches no hook path runs nothing"
: > "$CALLS"; new_branch plain
echo x >> "$CLONE/README.md"; git_q commit -qam plain
push plain && on_origin plain && pass "plain push goes" || fail "plain push blocked: $(cat "$TMP/push.out")"
[ ! -s "$CALLS" ] && pass "no test was run" || fail "tests ran for a plain push"

echo "== a hook change runs the corpus scans and the tests naming it"
: > "$CALLS"; new_branch hookok
echo "print('x')" > "$CLONE/scripts/hooks/new-gate.py"
echo "// new-gate" > "$CLONE/src/__tests__/new-gate.test.ts"
git_q add -A && git_q commit -qm "hook"
NPX_RC=0 push hookok && on_origin hookok && pass "green tests: the push goes" || fail "green push blocked: $(cat "$TMP/push.out")"
grep -q "hook-registration-completeness.test.ts" "$CALLS" && grep -q "project-settings-hook-anchor.test.ts" "$CALLS" && pass "both corpus scans ran" || fail "corpus scans missing: $(cat "$CALLS")"
grep -q "new-gate.test.ts" "$CALLS" && pass "the test naming the hook ran" || fail "named test missing: $(cat "$CALLS")"

echo "== a failing test stops the push"
: > "$CALLS"; new_branch hookred
echo "print('y')" > "$CLONE/scripts/hooks/red-gate.py"; git_q add -A && git_q commit -qm "hook red"
NPX_RC=1 push hookred && fail "red tests but the push went" || pass "red tests: push refused"
on_origin hookred && fail "the branch reached origin" || pass "the branch never reached origin"
grep -q "BLOCKED by related-tests-gate" "$TMP/push.out" && pass "the refusal says why" || fail "no reason printed"

echo "== .claude/settings.json alone gates too"
: > "$CALLS"; new_branch setred
echo '{"a":1}' > "$CLONE/.claude/settings.json"; git_q commit -qam settings
NPX_RC=1 push setred && fail "settings change with red tests went" || pass "settings change: red tests stop the push"
[ -s "$CALLS" ] && pass "the scans ran for a settings-only change" || fail "settings-only change ran nothing"

echo "== cannot check -> refuse (fail closed)"
new_branch dirty
echo "print('z')" > "$CLONE/scripts/hooks/dirty-gate.py"; git_q add -A && git_q commit -qm "hook dirty"
echo "edit" >> "$CLONE/scripts/hooks/dirty-gate.py"
NPX_RC=0 push dirty && fail "dirty tree pushed" || pass "dirty tracked tree refused"
git_q checkout -q -- .
new_branch nomods
echo "print('n')" > "$CLONE/scripts/hooks/nomods-gate.py"; git_q add -A && git_q commit -qm "hook nomods"
mv "$CLONE/node_modules" "$CLONE/node_modules.off"
NPX_RC=0 push nomods && fail "no node_modules but pushed" || pass "no node_modules refused"
mv "$CLONE/node_modules.off" "$CLONE/node_modules"
git_q checkout -q main
NPX_RC=0 push nomods && fail "ref that is not HEAD pushed" || pass "a hook branch that is not the checked-out HEAD refused"
git_q checkout -q nomods
mv "$CLONE/scripts/git-hooks/related-tests-gate.sh" "$CLONE/scripts/git-hooks/related-tests-gate.sh.off"
NPX_RC=0 push nomods && fail "gate script missing but pushed" || pass "missing gate script: the stub refuses"
mv "$CLONE/scripts/git-hooks/related-tests-gate.sh.off" "$CLONE/scripts/git-hooks/related-tests-gate.sh"

echo "== cannot check: new refusals (Viktor 41344 LOW 3, INFO 5)"
new_branch nobin
echo "print('b')" > "$CLONE/scripts/hooks/nobin-gate.py"; git_q add -A && git_q commit -qm "hook nobin"
mv "$CLONE/node_modules/.bin/vitest" "$CLONE/node_modules/.bin/vitest.off"
NPX_RC=0 push nobin && fail "node_modules without .bin/vitest but pushed" || pass "node_modules present, no .bin/vitest: refused (no npx fallback)"
grep -q "node_modules/.bin/vitest" "$TMP/push.out" && pass "the refusal names the missing binary" || fail "refusal does not name the binary"
mv "$CLONE/node_modules/.bin/vitest.off" "$CLONE/node_modules/.bin/vitest"
: > "$CALLS"; new_branch untracked
echo "print('u')" > "$CLONE/scripts/hooks/tracked-gate.py"; git_q add -A && git_q commit -qm "hook untracked"
echo "print('forgot git add')" > "$CLONE/scripts/hooks/forgotten-gate.py"
NPX_RC=0 push untracked && fail "untracked hook file but pushed" || pass "an untracked new hook file: refused"
grep -q "forgotten-gate.py" "$TMP/push.out" && pass "the refusal lists the untracked file" || fail "untracked file not listed"
[ ! -s "$CALLS" ] && pass "refused before any test ran" || fail "tests ran despite the untracked file"
rm -f "$CLONE/scripts/hooks/forgotten-gate.py"
NPX_RC=0 push untracked && on_origin untracked && pass "after removing it, the same branch goes" || fail "clean branch blocked: $(cat "$TMP/push.out")"

echo "== a hook moved OUT of scripts/hooks still gates (--no-renames, INFO 6)"
git_q checkout -q main
mkdir -p "$CLONE/scripts/hooks"
echo "print('m')" > "$CLONE/scripts/hooks/moved-gate.py"; git_q add -A && git_q commit -qm "add moved-gate" && git_q push -q origin main 2>/dev/null
: > "$CALLS"; new_branch moved
mkdir -p "$CLONE/scripts/elsewhere"
git_q mv scripts/hooks/moved-gate.py scripts/elsewhere/moved-gate.py && git_q commit -qm "move hook out"
NPX_RC=0 push moved && on_origin moved && pass "green: the move pushes" || fail "move push blocked: $(cat "$TMP/push.out")"
[ -s "$CALLS" ] && pass "the tests ran for the move (old path seen as deleted)" || fail "a hook moved out of scripts/hooks slipped past the gate"
: > "$CALLS"; new_branch movedred
mkdir -p "$CLONE/scripts/elsewhere"
git_q mv scripts/hooks/moved-gate.py scripts/elsewhere/moved-gate.py && git_q commit -qm "move hook out, red"
NPX_RC=1 push movedred && fail "red tests but the move went" || pass "red tests stop the move"

echo "== the GIT_* variables of a hook never reach vitest (INFO 7)"
: > "$ENVLOG"; new_branch envdrop
echo "print('e')" > "$CLONE/scripts/hooks/env-gate.py"; git_q add -A && git_q commit -qm "hook env"
ENV_SHA="$(git -C "$CLONE" rev-parse HEAD)"
( cd "$CLONE" && echo "refs/heads/envdrop $ENV_SHA refs/heads/envdrop 0000000000000000000000000000000000000000" \
    | GIT_DIR="$CLONE/.git" GIT_INDEX_FILE="$CLONE/.git/index" GIT_WORK_TREE="$CLONE" NPX_RC=0 bash scripts/git-hooks/related-tests-gate.sh origin x ) >"$TMP/push.out" 2>&1 \
  && pass "the gate ran with GIT_* set" || fail "gate failed under GIT_*: $(cat "$TMP/push.out")"
[ -s "$ENVLOG" ] && ! grep -v '^GIT_DIR= GIT_INDEX_FILE= GIT_WORK_TREE=$' "$ENVLOG" | grep -q . && pass "vitest saw no GIT_DIR / GIT_INDEX_FILE / GIT_WORK_TREE" || fail "vitest inherited a GIT_* variable: $(cat "$ENVLOG")"

echo "== installer: a path with a space and a \$ stays one word (INFO 8)"
WEIRD="$TMP/we ird \$HOME dir/repo"
mkdir -p "$WEIRD/scripts/git-hooks"
git init -q "$WEIRD" 2>/dev/null
cp "$SRC/scripts/git-hooks/related-tests-gate.sh" "$WEIRD/scripts/git-hooks/"
cp "$SRC/scripts/install-git-related-tests-hook.sh" "$SRC/scripts/install-git-guard-hook.sh" "$WEIRD/scripts/"
( cd "$TMP" && bash "$WEIRD/scripts/install-git-related-tests-hook.sh" >/dev/null 2>&1 ) && pass "installer runs in a path with a space and a \$" || fail "installer failed in the odd path"
WSTUB="$WEIRD/.git/hooks/pre-push.d/20-related-tests-gate"
( cd "$WEIRD" && bash "$WSTUB" </dev/null ) >"$TMP/push.out" 2>&1 && pass "the stub finds the gate (exit 0 on an empty ref list)" || fail "stub did not reach the gate: $(cat "$TMP/push.out")"
grep -q '^GATE=' "$WSTUB" && ! grep -q '^GATE="' "$WSTUB" && pass "the path is escaped, not double-quoted" || fail "stub still double-quotes the path: $(grep GATE= "$WSTUB")"

echo "== a branch deletion passes"
git -C "$CLONE" push -q origin ":plain" >"$TMP/push.out" 2>&1 && ! on_origin plain && pass "deletion goes" || fail "deletion blocked: $(cat "$TMP/push.out")"

echo ""
echo "related-tests-gate: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
