#!/usr/bin/env bash
# pr-head.sh -- does a GitHub pull request's head equal the SHA under review? Read anonymously, with no credential.
#
#   pr-head.sh <owner/repo> <pr-number> <expected-sha-40-hex>
#
# Why (card 1c205f39): Viktor's verdicts name a PR head he cannot see ("no gh here, I cannot see the PR head"),
# so the SHA he approves is the one the requester typed. A public repository (kiskodzsek/marveen, measured
# 2026-11-14) serves refs/pull/<n>/head to an anonymous `git ls-remote`, so the head can be checked without a token.
# Conditions: Viktor 41944.
#
# What it does: one `git ls-remote --symref https://github.com/<owner/repo>.git HEAD refs/pull/<n>/head`, with
# every credential path shut. No system or global git config (the system config on the mini sets
# credential.helper=osxkeychain, which would hand a private repository the login keychain's GitHub credential),
# credential.helper emptied, askpass a program that fails, no terminal prompt, https only, no redirect, HOME and
# cwd an empty directory (no repository config, insteadOf or hook applies). There is no fallback: a failure is
# ERROR, never a retry with a credential.
#
# Output: fixed fields only; git's own error text is never printed (we do not know what it may carry).
#   measured_at: <the script's own clock>
#   repo: <owner/repo>
#   pr: <n>
#   pr_head: <40-hex sha> | UNKNOWN
#   default_branch: <name> <40-hex sha> | UNKNOWN      (the remote's HEAD: the PR's base may be another branch)
#   expected: <40-hex sha>
#   result: MATCH | DIFFERS | ERROR <reason>
#   note: ...
# Exit: 0 MATCH, 1 DIFFERS, 2 ERROR (usage, private repository, no such PR, network, anything else).
#
# What MATCH means, and what it does not:
# - It holds at measured_at only: the PR head can move before the merge, so the merge gate runs this again
#   right before merging.
# - refs/pull/<n>/head is the PR's head per GitHub's documentation; that it equals the API's headRefOid is a
#   tip (it matched in the 2026-11-14 measurement), not a guarantee.
# - A private repository gives ERROR. Whoever merges (and has a token) checks there, in their own environment.
#
# PR_HEAD_TEST_ONLY_REMOTE_BASE: for the tests only. Replaces https://github.com with a file:/// path or an
# http://127.0.0.1:<port> server; anything else is refused. Credentials are off either way.
set -u

measured_at=$(date '+%Y-%m-%d %H:%M:%S %Z')
repo=${1:-}; pr=${2:-}; expected=${3:-}
pr_head=UNKNOWN; default_branch=UNKNOWN

report() {  # report <result> <exit>
  printf 'measured_at: %s\nrepo: %s\npr: %s\npr_head: %s\ndefault_branch: %s\nexpected: %s\nresult: %s\n' \
    "$measured_at" "$repo" "$pr" "$pr_head" "$default_branch" "$expected" "$1"
  echo "note: valid at measured_at only, re-run right before the merge; refs/pull/<n>/head = PR head per GitHub docs (equality with headRefOid is a tip)"
  exit "$2"
}

# Validation before anything runs. A rejected argument is shown as "-", never printed back.
repo_ok=-; pr_ok=-; exp_ok=-
bad() { repo=$repo_ok; pr=$pr_ok; expected=$exp_ok; report "ERROR usage: $1" 2; }
[ $# -eq 3 ] || bad "pr-head.sh <owner/repo> <pr-number> <expected-sha-40-hex>"
# owner: letters, digits, dashes, no leading dash; repo: letters, digits, dot, dash, underscore, no leading dot
# or dash, no "..".
if printf '%s' "$repo" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}$' \
   && ! case "$repo" in (*..*) true;; (*) false;; esac; then repo_ok=$repo; else bad "owner/repo"; fi
if printf '%s' "$pr" | grep -Eq '^[1-9][0-9]{0,6}$'; then pr_ok=$pr; else bad "pr-number (1-7 digits)"; fi
if printf '%s' "$expected" | grep -Eq '^[0-9a-f]{40}$'; then exp_ok=$expected; else bad "expected sha (exactly 40 lower-case hex)"; fi

prefix=https://github.com; protocol=https
if [ -n "${PR_HEAD_TEST_ONLY_REMOTE_BASE:-}" ]; then
  t=$PR_HEAD_TEST_ONLY_REMOTE_BASE
  if printf '%s' "$t" | grep -Eq '^file:///[A-Za-z0-9_./-]+$' && ! case "$t" in (*..*) true;; (*) false;; esac; then
    prefix=${t%/}; protocol=file
  elif printf '%s' "$t" | grep -Eq '^http://127\.0\.0\.1:[0-9]{1,5}$'; then
    prefix=$t; protocol=http
  else
    report "ERROR usage: PR_HEAD_TEST_ONLY_REMOTE_BASE must be file:///<path> or http://127.0.0.1:<port>" 2
  fi
fi
url="$prefix/$repo.git"

empty=$(mktemp -d "${TMPDIR:-/tmp}/pr-head.XXXXXX") || report "ERROR internal: no temp directory" 2
out="$empty.out"; err="$empty.err"
trap 'rm -rf "$empty" "$out" "$err"' EXIT
FAIL=/usr/bin/false; [ -x "$FAIL" ] || FAIL=/bin/false

( cd "$empty" && env -u GIT_DIR -u GIT_WORK_TREE -u GIT_CONFIG_PARAMETERS -u GIT_CONFIG_COUNT \
    -u GIT_SSH -u GIT_SSH_COMMAND -u GIT_PROXY_COMMAND -u GIT_TRACE -u GIT_TRACE_CURL -u GIT_CURL_VERBOSE \
    HOME="$empty" XDG_CONFIG_HOME="$empty" \
    GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_SYSTEM=/dev/null GIT_CONFIG_GLOBAL=/dev/null \
    GIT_TERMINAL_PROMPT=0 GIT_ASKPASS="$FAIL" SSH_ASKPASS="$FAIL" GCM_INTERACTIVE=never \
    GIT_ALLOW_PROTOCOL="$protocol" \
    git -c credential.helper= -c core.askPass="$FAIL" -c http.followRedirects=false \
      -c http.lowSpeedLimit=1 -c http.lowSpeedTime=20 \
      ls-remote --symref "$url" HEAD "refs/pull/$pr/head" ) >"$out" 2>"$err"
rc=$?

if [ $rc -ne 0 ]; then
  if grep -Eq 'could not read Username|Authentication failed|terminal prompts disabled|Repository not found|HTTP 40[13]' "$err"; then
    report "ERROR not readable anonymously (private repository, or none)" 2
  fi
  report "ERROR git ls-remote failed (exit $rc)" 2
fi

h=$(awk -v r="refs/pull/$pr/head" '$2==r {print $1}' "$out")
d_name=$(awk '$1=="ref:" && $3=="HEAD" {sub("^refs/heads/","",$2); print $2}' "$out")
d_sha=$(awk '$2=="HEAD" && $1!="ref:" {print $1}' "$out")
if printf '%s' "$d_sha" | grep -Eq '^[0-9a-f]{40}$' && printf '%s' "$d_name" | grep -Eq '^[A-Za-z0-9._/-]{1,200}$'; then
  default_branch="$d_name $d_sha"
fi
printf '%s' "$h" | grep -Eq '^[0-9a-f]{40}$' || report "ERROR no refs/pull/$pr/head (no such PR)" 2
pr_head=$h
[ "$pr_head" = "$expected" ] && report MATCH 0
report DIFFERS 1
