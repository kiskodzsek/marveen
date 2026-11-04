#!/usr/bin/env bash
# deps-store.sh -- one npm install per lockfile, outside every branch, for worktree-add.sh to link to.
#
#   deps-store.sh [--dry] <worktree-or-clone>
#
# Why (code review 2026-10-30 #16, card f24e6745): worktrees linked their node_modules to whichever
# feature worktree had an install of the right lockfile; when that worktree was removed with its merged
# branch, every link into it broke (2026-11-04: 11 broken, 31 more pointing into feature worktrees).
# A store is not a branch, so nothing removes it from under its links.
#
#   1. the store is <production tree>/agents/<agent>/deps/<repo>-<sha256(package-lock.json), 16 hex>,
#      under the same agent's tree as the worktree (worktree-add.sh links only within one agent);
#   2. if a store of that lockfile already holds an install (node_modules/.package-lock.json), under any
#      <repo> label (the hash is the identity), its path is printed and nothing runs: one install serves
#      every worktree of that lockfile, whatever its clone is called;
#   3. otherwise package.json and package-lock.json (and .npmrc, if there is one) are copied in, and
#      `npm ci --ignore-scripts` runs there under heavy-job.sh (one heavy job at a time, only with free
#      memory and disk). --ignore-scripts: the store has no repository files, so no lifecycle script of
#      the project or of a dependency runs in it; a package that needs one is installed in the worktree
#      itself, as before. Measured on kiskodzsek/marabel 0691037f2 (package-lock.json hasInstallScript):
#      protobufjs 7.6.6 and unrs-resolver 1.12.2 (dev) have one; marveen and mcp-connectors were not measured;
#   4. a failed install leaves no half store behind: it is built in <store>.partial and renamed at the end;
#      the .partial directory is also the lock (a second run for the same lockfile stops with 75), and a
#      store that appeared meanwhile is used, not overwritten. The lock holds the owner's pid; a lock whose
#      owner is gone (a killed run: mem-relief, heavy-job kill, reboot) is taken over, so it never blocks
#      every later run (Viktor 26594);
#   5. a repository .npmrc is copied only without a credential in it (_authToken, _auth, _password).
#
# Afterwards `worktree-add.sh <main-clone> <new> <branch>` takes the store by itself when the main clone
# cannot serve that lockfile. A store nobody links to is the owner's to remove (rm -rf <store>).
#
# Exit codes: 0 = the store is ready (its path on stdout); 3 = the install failed; 64 = usage error (or an
# .npmrc with a credential); 75 = heavy-job.sh did not start the install (busy host), or another install of the
# same lockfile is running.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_DIR="$(git -C "$HERE" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"
PROD_TREE="${MARVEEN_PROD_TREE:-${COMMON_DIR:+$(dirname "$COMMON_DIR")}}"
PROD_TREE="${PROD_TREE:-$HERE/..}"
HEAVY_JOB="${DEPS_STORE_HEAVY_JOB:-$HERE/heavy-job.sh}"
NPM="${DEPS_STORE_NPM:-npm}"

usage() { echo "usage: deps-store.sh [--dry] <worktree-or-clone>" >&2; exit 64; }
phys() { (cd -P -- "$1" 2>/dev/null && pwd -P); }

DRY=0
[[ "${1:-}" == "--dry" ]] && { DRY=1; shift; }
[[ $# -eq 1 ]] || usage
WT="$(phys "$1")"
[[ -n "$WT" ]] || { echo "deps-store: no such directory: $1" >&2; exit 64; }
[[ -f "$WT/package-lock.json" && -f "$WT/package.json" ]] || { echo "deps-store: no package.json + package-lock.json in $WT" >&2; exit 64; }
PROD="$(phys "$PROD_TREE")"
REST="${WT#"$PROD"/agents/}"
[[ -n "$PROD" && "$REST" != "$WT" ]] || { echo "deps-store: $WT is not under $PROD/agents/<agent>/" >&2; exit 64; }
AGENT="${REST%%/*}"
COMMON="$(git -C "$WT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"
[[ -n "$COMMON" ]] || { echo "deps-store: not a git work tree: $WT" >&2; exit 64; }
REPO="$(basename "$(dirname "$COMMON")")"
HASH="$(shasum -a 256 "$WT/package-lock.json" | cut -c1-16)"
STORE="$PROD/agents/$AGENT/deps/$REPO-$HASH"

# The hash is the identity, <repo> only a label: a store of this lockfile under any name is reused.
for d in "$PROD/agents/$AGENT/deps/"*-"$HASH"; do
  [[ -f "$d/node_modules/.package-lock.json" ]] && { echo "$d"; exit 0; }
done
if (( DRY )); then
  echo "deps-store: would install $REPO's lockfile $HASH into $STORE (npm ci --ignore-scripts under heavy-job.sh)" >&2
  echo "$STORE"
  exit 0
fi

# A repository .npmrc may carry a registry credential; the store never gets a copy of one (Viktor 26587 INFO-1).
if [[ -f "$WT/.npmrc" ]] && grep -Eq '(_authToken|_auth|_password)[[:space:]]*=' "$WT/.npmrc"; then
  echo "deps-store: $WT/.npmrc holds a credential; not copied, nothing installed (install in the worktree itself)" >&2
  exit 64
fi
# The .partial directory is the lock (Viktor 26587 LOW-1): mkdir is atomic, so a second run for the same lockfile
# finds it and stops instead of deleting the first run's work. The owner writes its pid into it at once.
# A stale lock (Viktor 26594): the pid is not running (ps -p, which sees every user's process, unlike kill -0),
# or there is no pid file and nothing in the directory changed for 10 minutes (a run from before this file, or
# one killed between mkdir and the write). Only the holder of $PART.takeover (mkdir, atomic) removes a stale lock,
# and nobody else ever removes a lock it does not own, so two runs that both see it stale cannot delete each
# other's fresh one. A reused pid reads as alive: the run stops with 75, the safe direction.
PART="$STORE.partial"
mkdir -p -- "$(dirname "$PART")" || { echo "deps-store: cannot create $(dirname "$PART")" >&2; exit 3; }
lock_is_stale() {
  local pid
  if [[ -f "$PART/.deps-store.pid" ]]; then
    pid="$(head -c 32 "$PART/.deps-store.pid" | tr -cd '0-9')"
    [[ -n "$pid" ]] && ! ps -p "$pid" >/dev/null 2>&1
  else
    [[ -n "$(find "$PART" -maxdepth 0 -mmin +10 2>/dev/null)" ]]
  fi
}
take_lock() { mkdir -- "$PART" 2>/dev/null && echo "$$" > "$PART/.deps-store.pid"; }
if ! take_lock; then
  if lock_is_stale && mkdir -- "$PART.takeover" 2>/dev/null; then
    # Checked again under the takeover lock: the stale lock is still there and still stale, so it is ours to remove.
    if lock_is_stale; then
      echo "deps-store: $PART was left by a run that is gone; taking it over" >&2
      rm -rf -- "$PART"
    fi
    take_lock; got=$?
    rmdir -- "$PART.takeover"
    (( got == 0 )) || { echo "deps-store: $PART exists: another install of this lockfile is running" >&2; exit 75; }
  else
    echo "deps-store: $PART exists: another install of this lockfile is running (its pid: $PART/.deps-store.pid)" >&2
    # A takeover killed midway (it holds no pid) is the one thing left by hand; it is said, never guessed.
    [[ -d "$PART.takeover" ]] && echo "deps-store: a takeover is in progress; if no deps-store runs, remove it: rmdir $PART.takeover" >&2
    exit 75
  fi
fi
# Another run may have finished this store while we waited for the lock: use it, no second install.
for d in "$PROD/agents/$AGENT/deps/"*-"$HASH"; do
  [[ -f "$d/node_modules/.package-lock.json" ]] && { rm -rf -- "$PART"; echo "$d"; exit 0; }
done
cp -- "$WT/package.json" "$WT/package-lock.json" "$PART/" || { rm -rf -- "$PART"; exit 3; }
[[ -f "$WT/.npmrc" ]] && cp -- "$WT/.npmrc" "$PART/"
(cd -- "$PART" && bash "$HEAVY_JOB" --name "deps-store-$REPO" -- "$NPM" ci --ignore-scripts --no-audit --no-fund)
rc=$?
if (( rc == 75 )); then rm -rf -- "$PART"; echo "deps-store: heavy-job.sh did not start the install (busy host); try again later" >&2; exit 75; fi
if (( rc != 0 )) || [[ ! -f "$PART/node_modules/.package-lock.json" ]]; then
  rm -rf -- "$PART"; echo "deps-store: npm ci failed (rc=$rc); nothing kept" >&2; exit 3
fi
# A store that appeared meanwhile is kept and used: mv would put this one inside it (Viktor 26587 LOW-1).
if [[ -e "$STORE" ]]; then rm -rf -- "$PART"; echo "$STORE"; exit 0; fi
# The pid file is the lock's, not the store's; without it the lock reads as fresh (its mtime is now), not stale.
rm -f -- "$PART/.deps-store.pid"
mv -- "$PART" "$STORE" || { rm -rf -- "$PART"; echo "deps-store: cannot move $PART to $STORE" >&2; exit 3; }
echo "$STORE"
