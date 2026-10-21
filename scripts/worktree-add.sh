#!/usr/bin/env bash
# worktree-add.sh -- a new git worktree whose node_modules is a symlink to the main clone's, not a copy.
#
#   worktree-add.sh [--node-modules-from DIR] <main-clone> <new-path> <branch> [<start-point>]
#
# Why (Patrik TG 4599, card 1c58f629, agents/kernel/reports/lemez-2026-10-21-0155.md): on
# 2026-10-21 01:55 the agents/ tree held 60 real node_modules (31.7 GB), about 0.75 GB per
# worktree, and the free disk fell from 49 GiB to 4 GiB in 13 hours. A worktree of the same
# lockfile needs no copy of its own.
#
#   1. git worktree add: <branch> if it exists, else -b <branch> from <start-point> (default HEAD);
#   2. node_modules: a symlink to the PHYSICAL node_modules of <main-clone> (or of
#      --node-modules-from DIR), resolved, so no worktree links to a link. Only when the new
#      worktree's package-lock.json is byte-identical to the package-lock.json next to that
#      physical node_modules, and that node_modules was installed (.package-lock.json present).
#      Otherwise the worktree is created without node_modules, and the script says why;
#   3. never a link into the production tree: an `npm install` in the worktree would rewrite
#      the live node_modules. The production tree is MARVEEN_PROD_TREE, by default the main
#      worktree of the repository this script lives in (its git common dir's parent), so the
#      guard holds when the script runs from a linked worktree too; and any source with a
#      store/claudeclaw.db next to its node_modules counts as a Marveen install, wherever it is;
#   4. never a link to another agent's clone: under <production tree>/agents/<name>/, the
#      source and the new worktree must belong to the same <name> (same Unix user, so an npm
#      install in one agent's tree would write the other's node_modules);
#   5. the link is kept out of git: if `git check-ignore` does not cover node_modules, the
#      script adds /node_modules to the repository's info/exclude ("node_modules/" in a
#      .gitignore matches a directory only, not a symlink).
#
# In a linked worktree, npm install / npm ci is FORBIDDEN: it writes into the shared
# node_modules of the main clone. A branch that changes the dependencies gets its own
# install (no link), under the heavy-job gate:
#   heavy-job.sh --name npm-ci -- npm ci
# Known limit: Turbopack refuses a node_modules outside the project root, so a check that
# needs `next build`/Turbopack (e.g. Marabel og-preview) runs in CI, not in a linked worktree.
#
# Exit codes: 0 = worktree created and node_modules linked; 3 = worktree created, NOT linked
# (the reason is printed); 64 = usage error; otherwise git worktree add's own exit code.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_DIR="$(git -C "$HERE" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"
PROD_TREE="${MARVEEN_PROD_TREE:-${COMMON_DIR:+$(dirname "$COMMON_DIR")}}"
PROD_TREE="${PROD_TREE:-$HERE/..}"

usage() { echo "usage: worktree-add.sh [--node-modules-from DIR] <main-clone> <new-path> <branch> [<start-point>]" >&2; exit 64; }
phys() { (cd -P -- "$1" 2>/dev/null && pwd -P); }

FROM=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --node-modules-from) [[ $# -ge 2 ]] || usage; FROM="$2"; shift 2 ;;
    --) shift; break ;;
    -*) usage ;;
    *) break ;;
  esac
done
[[ $# -eq 3 || $# -eq 4 ]] || usage
MAIN="$1"; NEW="$2"; BRANCH="$3"; START="${4:-HEAD}"
[[ -n "$MAIN" && -n "$NEW" && -n "$BRANCH" ]] || usage
git -C "$MAIN" rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "worktree-add: not a git work tree: $MAIN" >&2; exit 64; }
# git -C "$MAIN" resolves a relative path against <main-clone>, not the caller's directory.
[[ "$NEW" == /* ]] || NEW="$PWD/$NEW"
[[ -e "$NEW" ]] && { echo "worktree-add: already exists: $NEW" >&2; exit 64; }

if git -C "$MAIN" show-ref --verify --quiet "refs/heads/$BRANCH"; then
  git -C "$MAIN" worktree add -- "$NEW" "$BRANCH"
else
  git -C "$MAIN" worktree add -b "$BRANCH" -- "$NEW" "$START"
fi
rc=$?
[[ $rc -eq 0 ]] || exit "$rc"
NEW="$(phys "$NEW")"
[[ -n "$NEW" ]] || { echo "worktree-add: the new worktree cannot be resolved" >&2; exit 64; }

not_linked() { echo "worktree-add: $NEW created, node_modules NOT linked: $1" >&2; echo "  own install, under the gate: heavy-job.sh --name npm-ci -- npm ci" >&2; exit 3; }

SRC_NM="$(phys "${FROM:-$MAIN}/node_modules")"
[[ -n "$SRC_NM" ]] || not_linked "no node_modules in ${FROM:-$MAIN}"
OWNER="$(dirname "$SRC_NM")"
PROD="$(phys "$PROD_TREE")"
[[ -n "$PROD" && "$OWNER" == "$PROD" ]] && not_linked "the source is the production tree ($PROD); an npm install here would rewrite the live node_modules"
[[ -e "$OWNER/store/claudeclaw.db" ]] && not_linked "the source is a Marveen install ($OWNER/store/claudeclaw.db); an npm install here would rewrite the live node_modules"
# agent_of PATH: <name> if PATH is under <production tree>/agents/<name>, else empty.
agent_of() { local rest="${1#"$PROD"/agents/}"; [[ -n "$PROD" && "$rest" != "$1" ]] && echo "${rest%%/*}"; }
[[ "$(agent_of "$OWNER")" == "$(agent_of "$NEW")" ]] || not_linked "the source $OWNER is not in the same agent's tree as $NEW"
[[ -f "$SRC_NM/.package-lock.json" ]] || not_linked "$SRC_NM was not installed by npm (no .package-lock.json)"
[[ -f "$OWNER/package-lock.json" && -f "$NEW/package-lock.json" ]] || not_linked "package-lock.json missing in $OWNER or in the new worktree"
cmp -s "$OWNER/package-lock.json" "$NEW/package-lock.json" || not_linked "package-lock.json differs from $OWNER (other dependencies)"

ln -s -- "$SRC_NM" "$NEW/node_modules" || not_linked "ln -s failed"
if ! git -C "$NEW" check-ignore -q node_modules; then
  EXCLUDE="$(git -C "$NEW" rev-parse --path-format=absolute --git-common-dir)/info/exclude"
  mkdir -p "$(dirname "$EXCLUDE")" && printf '/node_modules\n' >> "$EXCLUDE"
fi
echo "worktree-add: $NEW -> node_modules linked to $SRC_NM (do NOT npm install/ci here)"
