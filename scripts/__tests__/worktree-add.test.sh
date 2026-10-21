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

echo "== usage"
wa "$SB/main" "$SB/wt1" feat/x
check "an existing path is refused (64)" "$(ok "$RC" = 64)" "$RC"
wa "$SB/main" "$SB/wtX"
check "missing branch (64)" "$(ok "$RC" = 64 -a ! -e "$SB/wtX")" "$RC"
wa "$SB/no-such" "$SB/wtY" feat/y
check "not a work tree (64)" "$(ok "$RC" = 64)" "$RC"
wa --bogus "$SB/main" "$SB/wtZ" feat/z
check "unknown option (64)" "$(ok "$RC" = 64)" "$RC"

echo
echo "$((DONE-FAILS))/$DONE passed"
[ "$FAILS" -eq 0 ]
