#!/usr/bin/env bash
# related-tests-gate.sh -- pre-push sub-hook: a push that changes a hook or the hook wiring does not leave the
# machine until the tests that scan hooks as a WHOLE have passed on exactly the commit being pushed.
#
# Why (Pulzus retro 2026-11-13, R7, card a8354557): a hook shipped fully unit-tested but with the wiring tests
# unrun, and CI went red on it -- pr-kerdes-gate 2026-11-11 (Kernel L199), the hook wiring 2026-11-13 (Kernel
# L301), #178 on three checks. The by-name search of a changed file never finds the tests that scan
# scripts/hooks/ or the settings files as a corpus: a NEW hook's name is in no test yet.
#
# Rule: the push is checked per ref. If the commits being pushed (merge-base with origin/main ... pushed sha)
# touch scripts/hooks/*, .claude/settings.json or templates/settings.json.template, then
#   - hook-registration-completeness and project-settings-hook-anchor must pass (always), and
#   - every test file that names a changed hook (by file stem) must pass.
# FAIL-CLOSED: when the check cannot be run (the ref is not the checked-out HEAD, the tracked tree is dirty, no
# node_modules, no merge-base, vitest missing) the push is refused, with the reason and what to do. A push that
# touches none of those paths passes at once and runs nothing.
#
# Known limits, said so nobody reads this as a wall:
#   - `git push --no-verify` skips every git hook; this is a drift control against a forgotten check, not
#     enforcement (CI stays the wall).
#   - It lives in the clone whose .git/hooks the installer wrote (scripts/install-git-related-tests-hook.sh,
#     run by sync-hooks.sh on update); linked worktrees of that clone share it. A push from a scratch bare
#     repo or another clone is not gated.
#   - Only vitest files run; the python hook tests (scripts/hooks/*_test.py) are not run here.
#
# stdin: the pre-push ref list (<local ref> <local sha> <remote ref> <remote sha>). Exit 0 = push may go.
# Portable to macOS bash 3.2 (no mapfile, no associative arrays).
set -uo pipefail

ZERO="0000000000000000000000000000000000000000"
# The two scans that read every hook / the settings files as a corpus.
REQUIRED="src/__tests__/hook-registration-completeness.test.ts src/__tests__/project-settings-hook-anchor.test.ts"

TOP="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "related-tests-gate: not inside a work tree" >&2; exit 1; }
cd "$TOP" || exit 1

refuse() { echo "" >&2; echo "BLOCKED by related-tests-gate: $1" >&2; shift; for l in "$@"; do echo "  $l" >&2; done; fail=1; }

is_gated_path() {
  case "$1" in
    scripts/hooks/*|.claude/settings.json|templates/settings.json.template) return 0 ;;
  esac
  return 1
}

fail=0
while read -r local_ref local_sha remote_ref remote_sha; do
  [ -n "${local_sha:-}" ] || continue
  [ "$local_sha" = "$ZERO" ] && continue            # branch deletion

  base="$(git merge-base "$local_sha" origin/main 2>/dev/null)" || {
    refuse "no merge-base of ${local_ref} with origin/main (git fetch origin first)."
    continue
  }
  changed="$(git diff --name-only "$base" "$local_sha")"

  gated=""
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    is_gated_path "$f" && gated="${gated}${f}"$'\n'
  done <<EOF
$changed
EOF
  [ -n "$gated" ] || continue                       # nothing hook-related in this push

  head_sha="$(git rev-parse HEAD)"
  if [ "$local_sha" != "$head_sha" ]; then
    refuse "${local_ref} changes hook files but is not the checked-out HEAD here, so its tests cannot be run on it." \
      "Push it from the worktree where that branch is checked out."
    continue
  fi
  if ! git diff --quiet HEAD -- || ! git diff --cached --quiet --; then
    refuse "the tracked files differ from the commit being pushed; the tests would run on something else." \
      "Commit or revert the changes, then push."
    continue
  fi
  if [ ! -e node_modules ]; then
    refuse "no node_modules in ${TOP}; vitest cannot run." \
      "bash scripts/deps-store.sh ${TOP}, then bash scripts/worktree-add.sh again, or run the tests where node_modules exists."
    continue
  fi

  # The tests: the two corpus scans, plus every test file that names a changed hook by its stem.
  tests="$REQUIRED"
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    case "$f" in scripts/hooks/*) ;; *) continue ;; esac
    [ -f "$f" ] || continue                         # a deleted hook: the corpus scans cover it
    stem="$(basename "$f")"; stem="${stem%.*}"; stem="${stem%_test}"
    [ -n "$stem" ] || continue
    named="$(grep -rlF --include='*.test.ts' --include='*.test.mjs' --include='*.test.js' \
      --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=dist -e "$stem" src scripts 2>/dev/null || true)"
    tests="${tests}"$'\n'"${named}"
  done <<EOF
$gated
EOF
  tests="$(printf '%s\n' "$tests" | tr ' ' '\n' | sed '/^$/d' | sort -u)"
  for t in $REQUIRED; do
    [ -f "$t" ] || { refuse "the required test ${t} does not exist in this tree."; continue 2; }
  done

  n="$(printf '%s\n' "$tests" | wc -l | tr -d ' ')"
  echo "related-tests-gate: ${local_ref} touches hook files; running ${n} test file(s) on ${local_sha:0:8}" >&2
  set -f
  # shellcheck disable=SC2086
  set -- $tests
  set +f
  # stdin from /dev/null: this loop reads the ref list on stdin and vitest must not eat it.
  if ! npx vitest run "$@" >&2 </dev/null; then
    refuse "the tests above failed on ${local_sha:0:8}; the push does not go." \
      "Fix them, commit, and push again (CI would go red on the same ones)."
  fi
done
exit $fail
