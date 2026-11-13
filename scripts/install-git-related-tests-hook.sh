#!/usr/bin/env bash
# Idempotent installer: the push-time related-tests gate (scripts/git-hooks/related-tests-gate.sh) as a
# pre-push sub-hook of THIS clone. Auto-run by scripts/sync-hooks.sh on update (every install-*-hook.sh).
#
# What it writes: .git/hooks/pre-push.d/20-related-tests-gate, a three-line stub that runs the tracked gate
# script from this checkout. The gate itself stays in git, so updating it is a normal PR, not a re-install;
# the stub only points at it. Linked worktrees of this clone share .git/hooks, so they are gated too.
# A missing gate script makes the stub refuse the push (fail closed), never silently pass.
#
# Composes with the pre-push.d/ dispatcher of install-git-guard-hook.sh; if that is not installed yet, it is
# run first (the dispatcher is what calls every pre-push.d/* hook).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Same trap as install-git-guard-hook.sh: `rev-parse --git-common-dir` answers relative to the repo, so a bare
# `cd` on it would resolve against the CALLER's cwd and could write the hook into another repository.
GIT_COMMON_DIR="$(git -C "$ROOT" rev-parse --git-common-dir)"
case "$GIT_COMMON_DIR" in /*) ;; *) GIT_COMMON_DIR="$ROOT/$GIT_COMMON_DIR" ;; esac
HOOK_DIR="$(cd "$GIT_COMMON_DIR" && pwd)/hooks"
DISPATCH="$HOOK_DIR/pre-push"
STUB="$HOOK_DIR/pre-push.d/20-related-tests-gate"
GATE="$ROOT/scripts/git-hooks/related-tests-gate.sh"

[ -f "$GATE" ] || { echo "install-git-related-tests-hook: $GATE is missing" >&2; exit 1; }

if ! grep -q "marveen-pre-push-dispatcher" "$DISPATCH" 2>/dev/null; then
  bash "$ROOT/scripts/install-git-guard-hook.sh"
fi
mkdir -p "$HOOK_DIR/pre-push.d"

cat > "$STUB" <<EOF
#!/usr/bin/env bash
# related-tests-gate stub (scripts/install-git-related-tests-hook.sh): run the tracked gate, fail closed.
GATE="$GATE"
[ -f "\$GATE" ] || { echo "BLOCKED: related-tests gate script missing: \$GATE" >&2; exit 1; }
exec bash "\$GATE" "\$@"
EOF
chmod +x "$STUB"

echo "✓ related-tests gate: hook/settings pushes run the corpus scans before they leave the machine."
