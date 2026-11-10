#!/usr/bin/env bash
# WORKTREEADD1021 -- worktree-add.sh: a new worktree's node_modules is a symlink to the main clone's
# physical node_modules, only with a byte-identical lockfile, never into the production tree (also
# when run from a linked worktree), never to another agent's clone, and never visible to git (Patrik TG 4599, card 1c58f629).
#
# Every repository is a throwaway one inside a sandbox; nothing here touches a real clone.
#
# Run:  bash scripts/__tests__/worktree-add.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
WA="$ROOT/scripts/worktree-add.sh"
[ -e "$WA" ] || { echo "FATAL: the script under test is missing: $WA" >&2; exit 2; }

FAILS=0; DONE=0
check() { DONE=$((DONE+1)); if [ "$2" = "0" ]; then echo "PASS  $1"; else echo "FAIL  $1${3:+  -- $3}"; FAILS=$((FAILS+1)); fi; }
ok() { [ "$@" ] && echo 0 || echo 1; }

SB="$(cd -P "$(mktemp -d "${TMPDIR:-/tmp}/worktreeadd.XXXXXX")" && pwd -P)"
trap 'rm -rf "$SB"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t

# mkclone DIR IGNORE_LINE: a repo with package-lock.json, a .gitignore, and an npm-installed node_modules.
mkclone() {
  mkdir -p "$1" && git -C "$1" init -q -b main
  echo '{"lockfileVersion":3,"packages":{"":{"name":"x"}}}' > "$1/package-lock.json"
  printf '%s\n' "$2" > "$1/.gitignore"
  git -C "$1" add -A && git -C "$1" commit -q -m init
  mkdir -p "$1/node_modules/dep" && echo '{}' > "$1/node_modules/.package-lock.json"
}
wa() { OUT="$(MARVEEN_PROD_TREE="${PROD:-$SB/no-prod}" bash "$WA" "$@" 2>&1)"; RC=$?; }

echo "== same lockfile: linked to the physical node_modules, invisible to git"
mkclone "$SB/main" "node_modules"
wa "$SB/main" "$SB/wt1" feat/one
check "exit 0" "$(ok "$RC" = 0)" "$RC $OUT"
check "node_modules is a symlink" "$(ok -L "$SB/wt1/node_modules")"
check "it points at the main clone's physical node_modules" "$(ok "$(readlink "$SB/wt1/node_modules")" = "$SB/main/node_modules")"
check "the branch was created" "$(ok "$(git -C "$SB/wt1" branch --show-current)" = feat/one)"
check "git status is clean in the worktree" "$(ok -z "$(git -C "$SB/wt1" status --porcelain)")"
check "the .gitignore covered it: info/exclude untouched" "$(ok "$(cat "$SB/main/.git/info/exclude" 2>/dev/null | grep -c '^/node_modules$')" = 0)"

echo "== a worktree of a worktree links to the physical directory, not to the link"
wa "$SB/wt1" "$SB/wt2" feat/two
check "exit 0" "$(ok "$RC" = 0)" "$RC $OUT"
check "no chain: points at main/node_modules" "$(ok "$(readlink "$SB/wt2/node_modules")" = "$SB/main/node_modules")"

echo "== a different lockfile: created, not linked"
git -C "$SB/main" checkout -q -b deps
echo '{"lockfileVersion":3,"packages":{"":{"name":"x"},"node_modules/new":{}}}' > "$SB/main/package-lock.json"
git -C "$SB/main" commit -q -am deps && git -C "$SB/main" checkout -q main
wa "$SB/main" "$SB/wt3" feat/three deps
check "exit 3" "$(ok "$RC" = 3)" "$RC $OUT"
check "the worktree exists" "$(ok -f "$SB/wt3/package-lock.json")"
check "no node_modules" "$(ok ! -e "$SB/wt3/node_modules")"
check "says why" "$(echo "$OUT" | grep -q 'package-lock.json differs' && echo 0 || echo 1)" "$OUT"
check "names the gated install" "$(echo "$OUT" | grep -q 'heavy-job.sh --name npm-ci -- npm ci' && echo 0 || echo 1)"

echo "== an existing branch is checked out, not recreated"
git -C "$SB/main" branch feat/existing
wa "$SB/main" "$SB/wt4" feat/existing
check "exit 0" "$(ok "$RC" = 0)" "$RC $OUT"
check "on the existing branch" "$(ok "$(git -C "$SB/wt4" branch --show-current)" = feat/existing)"

echo "== never into the production tree"
PROD="$SB/main" wa "$SB/main" "$SB/wt5" feat/five
check "exit 3" "$(ok "$RC" = 3)" "$RC $OUT"
check "no node_modules" "$(ok ! -e "$SB/wt5/node_modules")"
check "says production tree" "$(echo "$OUT" | grep -q 'production tree' && echo 0 || echo 1)" "$OUT"
mkclone "$SB/other" "node_modules"
mkdir -p "$SB/viaLink" && ln -s "$SB/main/node_modules" "$SB/viaLink/node_modules"
PROD="$SB/main" wa --node-modules-from "$SB/viaLink" "$SB/main" "$SB/wt6" feat/six
check "a link that resolves into the production tree is refused too" "$(ok "$RC" = 3 -a ! -e "$SB/wt6/node_modules")" "$RC $OUT"

echo "== --node-modules-from another clone"
wa --node-modules-from "$SB/other" "$SB/main" "$SB/wt7" feat/seven
check "exit 0" "$(ok "$RC" = 0)" "$RC $OUT"
check "points at the other clone" "$(ok "$(readlink "$SB/wt7/node_modules")" = "$SB/other/node_modules")"

echo "== not installed by npm: not linked"
mkclone "$SB/bare" "node_modules"
rm -f "$SB/bare/node_modules/.package-lock.json"
wa "$SB/bare" "$SB/wt8" feat/eight
check "exit 3" "$(ok "$RC" = 3 -a ! -e "$SB/wt8/node_modules")" "$RC $OUT"

echo "== a .gitignore that only matches a directory: info/exclude keeps the link out of git"
mkclone "$SB/dironly" "node_modules/"
wa "$SB/dironly" "$SB/wt9" feat/nine
check "exit 0" "$(ok "$RC" = 0)" "$RC $OUT"
check "/node_modules in info/exclude" "$(ok "$(grep -c '^/node_modules$' "$SB/dironly/.git/info/exclude")" = 1)"
check "git status is clean" "$(ok -z "$(git -C "$SB/wt9" status --porcelain)")" "$(git -C "$SB/wt9" status --porcelain)"

echo "== a Marveen install (store/claudeclaw.db) is refused wherever it is"
mkclone "$SB/inst" "node_modules"
mkdir -p "$SB/inst/store" && : > "$SB/inst/store/claudeclaw.db"
wa "$SB/inst" "$SB/wt10" feat/ten
check "exit 3" "$(ok "$RC" = 3 -a ! -e "$SB/wt10/node_modules")" "$RC $OUT"
check "says Marveen install" "$(echo "$OUT" | grep -q 'Marveen install' && echo 0 || echo 1)" "$OUT"

echo "== without MARVEEN_PROD_TREE: the production tree is the repo's main worktree, not the script's"
mkclone "$SB/prod" "node_modules"
mkdir -p "$SB/prod/scripts" && cp "$WA" "$SB/prod/scripts/worktree-add.sh"
git -C "$SB/prod" add scripts && git -C "$SB/prod" commit -q -m script
git -C "$SB/prod" worktree add -q "$SB/prod-wt" -b feat/agent-wt
wa_def() { OUT="$(env -u MARVEEN_PROD_TREE bash "$@" 2>&1)"; RC=$?; }
wa_def "$SB/prod-wt/scripts/worktree-add.sh" "$SB/prod" "$SB/wt11" feat/eleven
check "run from a linked worktree, source = main clone: exit 3" "$(ok "$RC" = 3 -a ! -e "$SB/wt11/node_modules")" "$RC $OUT"
check "says production tree" "$(echo "$OUT" | grep -q 'production tree' && echo 0 || echo 1)" "$OUT"
wa_def "$SB/prod/scripts/worktree-add.sh" "$SB/prod" "$SB/wt12" feat/twelve
check "run from the main clone itself: exit 3" "$(ok "$RC" = 3 -a ! -e "$SB/wt12/node_modules")" "$RC $OUT"
wa_def "$SB/prod-wt/scripts/worktree-add.sh" --node-modules-from "$SB/other" "$SB/main" "$SB/wt13" feat/thirteen
check "control: another clone still links" "$(ok "$RC" = 0 -a -L "$SB/wt13/node_modules")" "$RC $OUT"

echo "== never to another agent's clone"
mkclone "$SB/fleet/agents/alice/repo" "node_modules"
mkclone "$SB/fleet/agents/bob/repo" "node_modules"
PROD="$SB/fleet" wa "$SB/fleet/agents/alice/repo" "$SB/fleet/agents/alice/repo-wt" feat/a
check "same agent: exit 0" "$(ok "$RC" = 0 -a -L "$SB/fleet/agents/alice/repo-wt/node_modules")" "$RC $OUT"
PROD="$SB/fleet" wa --node-modules-from "$SB/fleet/agents/alice/repo" "$SB/fleet/agents/bob/repo" "$SB/fleet/agents/bob/repo-wt" feat/b
check "another agent's node_modules: exit 3" "$(ok "$RC" = 3 -a ! -e "$SB/fleet/agents/bob/repo-wt/node_modules")" "$RC $OUT"
check "says another agent's tree" "$(echo "$OUT" | grep -q "not in the same agent's tree" && echo 0 || echo 1)" "$OUT"
PROD="$SB/fleet" wa --node-modules-from "$SB/other" "$SB/fleet/agents/bob/repo" "$SB/fleet/agents/bob/repo-wt2" feat/b2
check "a source outside agents/ into an agent's tree: exit 3" "$(ok "$RC" = 3 -a ! -e "$SB/fleet/agents/bob/repo-wt2/node_modules")" "$RC $OUT"

echo "== a relative <new-path> is taken from the caller's directory, not from <main-clone>"
mkdir -p "$SB/callerdir"
OUT="$(cd "$SB/callerdir" && MARVEEN_PROD_TREE="$SB/no-prod" bash "$WA" "$SB/main" rel-wt feat/rel 2>&1)"; RC=$?
check "exit 0" "$(ok "$RC" = 0)" "$RC $OUT"
check "created under the caller's directory" "$(ok -f "$SB/callerdir/rel-wt/package-lock.json")"
check "not under <main-clone>" "$(ok ! -e "$SB/main/rel-wt")"
check "linked" "$(ok -L "$SB/callerdir/rel-wt/node_modules")"

echo "== never into a linked worktree's node_modules (code review #16, card f24e6745)"
git -C "$SB/other" worktree add -q "$SB/other-feat" -b feat/other-feat
mkdir -p "$SB/other-feat/node_modules/dep" && echo '{}' > "$SB/other-feat/node_modules/.package-lock.json"
wa --node-modules-from "$SB/other-feat" "$SB/main" "$SB/wt14" feat/fourteen
check "--node-modules-from a linked worktree: exit 3, not linked" "$(ok "$RC" = 3 -a ! -e "$SB/wt14/node_modules")" "$RC $OUT"
check "says linked worktree and names the store" "$(echo "$OUT" | grep -q 'is a linked worktree' && echo "$OUT" | grep -q 'deps-store.sh' && echo 0 || echo 1)" "$OUT"
wa "$SB/other-feat" "$SB/wt15" feat/fifteen
check "a linked worktree as <main-clone> with its own install: exit 3" "$(ok "$RC" = 3 -a ! -e "$SB/wt15/node_modules")" "$RC $OUT"
wa "$SB/wt1" "$SB/wt16" feat/sixteen
check "control: a linked worktree whose node_modules is a link to the main clone still links (to the main clone)" "$(ok "$RC" = 0 -a "$(readlink "$SB/wt16/node_modules")" = "$SB/main/node_modules")" "$RC $OUT"

echo "== the deps store: taken by itself when the main clone cannot serve the lockfile"
mkclone "$SB/fleet/agents/carol/repo" "node_modules"
rm -rf "$SB/fleet/agents/carol/repo/node_modules"
H="$(shasum -a 256 "$SB/fleet/agents/carol/repo/package-lock.json" | cut -c1-16)"
mkstore() { mkdir -p "$1/node_modules/dep" && echo '{}' > "$1/node_modules/.package-lock.json" && cp "$SB/fleet/agents/carol/repo/package-lock.json" "$1/"; }
PROD="$SB/fleet" wa "$SB/fleet/agents/carol/repo" "$SB/fleet/agents/carol/wt-a" feat/ca
check "no install, no store: exit 3, names deps-store.sh" "$(ok "$RC" = 3 -a ! -e "$SB/fleet/agents/carol/wt-a/node_modules" -a -n "$(echo "$OUT" | grep 'deps-store.sh')")" "$RC $OUT"
mkstore "$SB/fleet/agents/alice/deps/repo-$H"
PROD="$SB/fleet" wa "$SB/fleet/agents/carol/repo" "$SB/fleet/agents/carol/wt-b" feat/cb
check "another agent's store of the same lockfile is not taken" "$(ok "$RC" = 3 -a ! -e "$SB/fleet/agents/carol/wt-b/node_modules")" "$RC $OUT"
mkstore "$SB/fleet/agents/carol/deps/repo-0000000000000000"
PROD="$SB/fleet" wa "$SB/fleet/agents/carol/repo" "$SB/fleet/agents/carol/wt-c" feat/cc
check "a store of another lockfile is not taken" "$(ok "$RC" = 3 -a ! -e "$SB/fleet/agents/carol/wt-c/node_modules")" "$RC $OUT"
mkstore "$SB/fleet/agents/carol/deps/repo-$H"
PROD="$SB/fleet" wa "$SB/fleet/agents/carol/repo" "$SB/fleet/agents/carol/wt-d" feat/cd
check "own store of this lockfile: exit 0, linked to the store" "$(ok "$RC" = 0 -a "$(readlink "$SB/fleet/agents/carol/wt-d/node_modules")" = "$SB/fleet/agents/carol/deps/repo-$H/node_modules")" "$RC $OUT"
check "git status is clean" "$(ok -z "$(git -C "$SB/fleet/agents/carol/wt-d" status --porcelain)")" "$(git -C "$SB/fleet/agents/carol/wt-d" status --porcelain)"
PROD="$SB/fleet" wa "$SB/fleet/agents/carol/wt-d" "$SB/fleet/agents/carol/wt-e" feat/ce
check "a worktree of that worktree goes to the store too" "$(ok "$RC" = 0 -a "$(readlink "$SB/fleet/agents/carol/wt-e/node_modules")" = "$SB/fleet/agents/carol/deps/repo-$H/node_modules")" "$RC $OUT"
git clone -q "$SB/fleet/agents/carol/repo" "$SB/fleet/agents/carol/repo-copy"
PROD="$SB/fleet" wa "$SB/fleet/agents/carol/repo-copy" "$SB/fleet/agents/carol/wt-g" feat/cg
check "a second clone under another name shares the store (the hash is the identity)" "$(ok "$RC" = 0 -a "$(readlink "$SB/fleet/agents/carol/wt-g/node_modules")" = "$SB/fleet/agents/carol/deps/repo-$H/node_modules")" "$RC $OUT"
mkdir -p "$SB/fleet/agents/carol/repo/node_modules/dep" && echo '{}' > "$SB/fleet/agents/carol/repo/node_modules/.package-lock.json"
PROD="$SB/fleet" wa "$SB/fleet/agents/carol/repo" "$SB/fleet/agents/carol/wt-f" feat/cf
check "an installed main clone of the same lockfile is still first" "$(ok "$RC" = 0 -a "$(readlink "$SB/fleet/agents/carol/wt-f/node_modules")" = "$SB/fleet/agents/carol/repo/node_modules")" "$RC $OUT"

echo "== usage"
wa "$SB/main" "$SB/wt1" feat/x
check "an existing path is refused (64)" "$(ok "$RC" = 64)" "$RC"
wa "$SB/main" "$SB/wtX"
check "missing branch (64)" "$(ok "$RC" = 64 -a ! -e "$SB/wtX")" "$RC"
echo "== npm workspaces: never a shared node_modules (2026-11-10, mcp-connectors)"
mkclone "$SB/ws" "node_modules"
echo '{"name":"ws","workspaces":["common","billingo"]}' > "$SB/ws/package.json"
git -C "$SB/ws" add package.json && git -C "$SB/ws" commit -q -m ws
wa "$SB/ws" "$SB/wtW1" feat/ws1
check "workspaces: exit 3, no link" "$(ok "$RC" = 3 -a ! -e "$SB/wtW1/node_modules")" "$RC $OUT"
check "workspaces: says why and the own install" "$(echo "$OUT" | grep -q 'npm workspaces' && echo "$OUT" | grep -q 'npm ci --ignore-scripts' && echo 0 || echo 1)" "$OUT"
check "workspaces: no npm ci line without --ignore-scripts (Viktor 36920 a)" "$(echo "$OUT" | grep 'npm ci' | grep -vq -- '--ignore-scripts' && echo 1 || echo 0)" "$OUT"
check "workspaces: the worktree itself is created" "$(ok "$(git -C "$SB/wtW1" branch --show-current)" = feat/ws1)"
wa --node-modules-from "$SB/other" "$SB/ws" "$SB/wtW2" feat/ws2
check "workspaces: refused with --node-modules-from too" "$(ok "$RC" = 3 -a ! -e "$SB/wtW2/node_modules")" "$RC $OUT"
mkclone "$SB/badpkg" "node_modules"
echo '{"name":"bad","workspaces":' > "$SB/badpkg/package.json"
git -C "$SB/badpkg" add package.json && git -C "$SB/badpkg" commit -q -m bad
wa "$SB/badpkg" "$SB/wtW4" feat/ws4
check "an unparsable package.json takes the old path (Viktor 36920 b, documented)" "$(ok "$RC" = 0 -a -L "$SB/wtW4/node_modules")" "$RC $OUT"
mkclone "$SB/plainpkg" "node_modules"
echo '{"name":"plain","workspaces":[]}' > "$SB/plainpkg/package.json"
git -C "$SB/plainpkg" add package.json && git -C "$SB/plainpkg" commit -q -m plain
wa "$SB/plainpkg" "$SB/wtW3" feat/ws3
check "an empty workspaces list is not workspaces: linked as before" "$(ok "$RC" = 0 -a -L "$SB/wtW3/node_modules")" "$RC $OUT"

wa "$SB/no-such" "$SB/wtY" feat/y
check "not a work tree (64)" "$(ok "$RC" = 64)" "$RC"
wa --bogus "$SB/main" "$SB/wtZ" feat/z
check "unknown option (64)" "$(ok "$RC" = 64)" "$RC"

echo
echo "$((DONE-FAILS))/$DONE passed"
[ "$FAILS" -eq 0 ]
