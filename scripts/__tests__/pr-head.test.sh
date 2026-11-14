#!/usr/bin/env bash
# PRHEAD1114 -- pr-head.sh: is a PR's head the SHA under review, read anonymously with every credential path shut
# (card 1c205f39, conditions: Viktor 41944).
#
# Offline: the "GitHub" is a local bare repository (file://), a 127.0.0.1 server that answers 401, and a stub git
# on PATH. Nothing leaves the machine.
#
# Run:  bash scripts/__tests__/pr-head.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
S="$ROOT/scripts/pr-head.sh"
[ -e "$S" ] || { echo "FATAL: the script under test is missing: $S" >&2; exit 2; }

FAILS=0; DONE=0; NLC=0
check() { DONE=$((DONE+1)); if [ "$2" = "0" ]; then echo "PASS  $1"; else echo "FAIL  $1${3:+  -- $3}"; FAILS=$((FAILS+1)); fi; }
t() { "$@" && echo 0 || echo 1; }

SB="$(cd -P "$(mktemp -d "${TMPDIR:-/tmp}/prhead.XXXXXX")" && pwd -P)"
SRV_PID=
trap '[ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null; rm -rf "$SB"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t

# The fake remotes: acme/tool.git (HEAD -> main, refs/pull/7/head) and acme/dev.git (HEAD -> develop).
mkdir -p "$SB/remote/acme" "$SB/work"
git init -q -b main "$SB/work"
git -C "$SB/work" commit -q --allow-empty -m base
MAIN=$(git -C "$SB/work" rev-parse HEAD)
git -C "$SB/work" commit -q --allow-empty -m pr
PRH=$(git -C "$SB/work" rev-parse HEAD)
git init -q --bare "$SB/remote/acme/tool.git"
git -C "$SB/remote/acme/tool.git" symbolic-ref HEAD refs/heads/main
git -C "$SB/work" push -q "$SB/remote/acme/tool.git" "$MAIN:refs/heads/main" "$PRH:refs/pull/7/head"
git init -q --bare "$SB/remote/acme/dev.git"
git -C "$SB/remote/acme/dev.git" symbolic-ref HEAD refs/heads/develop
git -C "$SB/work" push -q "$SB/remote/acme/dev.git" "$MAIN:refs/heads/develop" "$PRH:refs/pull/3/head"

run() { PR_HEAD_TEST_ONLY_REMOTE_BASE="file://$SB/remote" bash "$S" "$@" >"$SB/o" 2>"$SB/e"; echo $?; }
has() { grep -qx -- "$1" "$SB/o"; }

# 1. MATCH -> 0, with the fixed fields
rc=$(run acme/tool 7 "$PRH")
check "MATCH exits 0" "$(t [ "$rc" = 0 ])" "rc=$rc $(cat "$SB/o")"
check "result: MATCH" "$(t has "result: MATCH")"
check "pr_head is the PR head" "$(t has "pr_head: $PRH")"
check "default_branch is the remote HEAD" "$(t has "default_branch: main $MAIN")"
check "measured_at from the script's clock" "$(t grep -Eq '^measured_at: [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}' "$SB/o")"
check "note says: valid at measured_at only, headRefOid is a tip" "$(t grep -q '^note: valid at measured_at only.*headRefOid is a tip' "$SB/o")"
check "nothing on stderr" "$(t [ ! -s "$SB/e" ])" "$(cat "$SB/e")"

# 2. DIFFERS -> 1 (main's sha is not the PR head)
rc=$(run acme/tool 7 "$MAIN")
check "DIFFERS exits 1" "$(t [ "$rc" = 1 ])" "rc=$rc"
check "result: DIFFERS, pr_head shown" "$(has "result: DIFFERS" && has "pr_head: $PRH" && echo 0 || echo 1)"

# 3. the default branch is named as it is, not "main"
rc=$(run acme/dev 3 "$PRH")
check "default branch develop reported as develop" "$([ "$rc" = 0 ] && has "default_branch: develop $MAIN" && echo 0 || echo 1)" "$(cat "$SB/o")"

# 4. no such PR -> ERROR 2, never DIFFERS
rc=$(run acme/tool 8 "$PRH")
check "missing PR ref is ERROR, exit 2" "$([ "$rc" = 2 ] && grep -q '^result: ERROR no refs/pull/8/head' "$SB/o" && echo 0 || echo 1)" "rc=$rc $(cat "$SB/o")"
check "missing PR: pr_head UNKNOWN, no MATCH/DIFFERS" "$(has "pr_head: UNKNOWN" && ! grep -Eq 'result: (MATCH|DIFFERS)' "$SB/o" && echo 0 || echo 1)"

# 5. usage errors -> ERROR 2; a rejected argument is not printed back
SHORT=${PRH:0:8}; UPPER=$(printf '%s' "$PRH" | tr 'a-f' 'A-F')
while IFS='|' read -r a b c n; do
  rc=$(run ${a:+"$a"} ${b:+"$b"} ${c:+"$c"} ${n:+"$n"})
  check "usage ERROR: [$a] [$b] [$c] [$n]" "$([ "$rc" = 2 ] && grep -q '^result: ERROR usage' "$SB/o" && echo 0 || echo 1)" "rc=$rc"
done <<EOF
acme/a..b|7|$PRH|
acme/..|7|$PRH|
acme/x..|7|$PRH|
-acme/tool|7|$PRH|
acme|7|$PRH|
acme/tool|0|$PRH|
acme/tool|12345678|$PRH|
acme/tool|7;id|$PRH|
acme/tool|7|$SHORT|
acme/tool|7|$UPPER|
acme/tool|7||
acme/tool|7|$PRH|extra
EOF
# whole-string validation: a newline, tab, space or non-ASCII byte in any argument is a usage ERROR, before git runs
# (Viktor 41945 LOW 1: a line-wise grep let "7<newline>text" through). The marker proves git never ran.
NL=$'\n'; TAB=$'\t'
for args in "acme/tool|7${NL}x|$PRH" "acme/tool${NL}x|7|$PRH" "acme/tool|7|$PRH${NL}x" "acme/tool|7${TAB}|$PRH" \
            "acme/tool|7 |$PRH" "acme/tööl|7|$PRH" "acme/tool|7|${NL}$PRH"; do
  IFS='|' read -r -d '' a b c <<<"$args"; c=${c%$'\n'}
  rc=$(run "$a" "$b" "$c")
  check "usage ERROR for a control/space/non-ASCII argument #$((++NLC))" "$([ "$rc" = 2 ] && grep -q '^result: ERROR usage' "$SB/o" && echo 0 || echo 1)" "rc=$rc $(grep result "$SB/o")"
done
# a leading dot is a valid repository name (".github"), "." is not
rc=$(run acme/.github 7 "$PRH")
check ".github passes validation (git then finds no such repo: ERROR, not usage)" "$([ "$rc" = 2 ] && ! grep -q '^result: ERROR usage' "$SB/o" && echo 0 || echo 1)" "$(grep result "$SB/o")"
rc=$(run acme/. 7 "$PRH")
check "acme/. is a usage ERROR" "$([ "$rc" = 2 ] && grep -q '^result: ERROR usage' "$SB/o" && echo 0 || echo 1)"

rc=$(run 'acme/$(touch x)' 7 "$PRH")
check "rejected repo is shown as -, not echoed" "$([ "$rc" = 2 ] && has "repo: -" && ! grep -q 'touch' "$SB/o" && echo 0 || echo 1)" "$(cat "$SB/o")"

# 6. the test-only override cannot point anywhere else
for bad in "https://evil.example" "http://127.0.0.2:80" "http://127.0.0.1.evil:80" "file:///x/../y" "http://localhost:80"; do
  rc=$(PR_HEAD_TEST_ONLY_REMOTE_BASE="$bad" bash "$S" acme/tool 7 "$PRH" >"$SB/o" 2>&1; echo $?)
  check "override refused: $bad" "$([ "$rc" = 2 ] && grep -q 'PR_HEAD_TEST_ONLY_REMOTE_BASE must be' "$SB/o" && echo 0 || echo 1)" "rc=$rc"
done

# 7. the caller's global config and the repository it stands in are not used
cat > "$SB/gcfg" <<EOF
[url "file:///nonexistent/"]
	insteadOf = file://$SB/remote/
EOF
rc=$(GIT_CONFIG_GLOBAL="$SB/gcfg" run acme/tool 7 "$PRH")
check "caller's global config ignored" "$(t [ "$rc" = 0 ])" "rc=$rc $(cat "$SB/o")"
git init -q "$SB/caller"
git -C "$SB/caller" config "url.file:///nonexistent/.insteadOf" "file://$SB/remote/"
rc=$(cd "$SB/caller" && run acme/tool 7 "$PRH")
check "caller's repository config ignored" "$(t [ "$rc" = 0 ])" "rc=$rc $(cat "$SB/o")"

# 8. Viktor's negative test: a 127.0.0.1 server answers 401 (WWW-Authenticate: Basic); the caller's SYSTEM and
#    GLOBAL config both name a credential helper that leaves a marker file. The script must give ERROR and no
#    helper may run. A positive control proves the setup does call the helpers when nothing shuts them.
python3 -I - "$SB/port" <<'PY' &
import http.server, sys
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(401); self.send_header("WWW-Authenticate", 'Basic realm="t"')
        self.send_header("Content-Length", "0"); self.end_headers()
    def log_message(self, *a): pass
srv = http.server.HTTPServer(("127.0.0.1", 0), H)
open(sys.argv[1] + ".tmp", "w").write(str(srv.server_address[1]))
import os; os.rename(sys.argv[1] + ".tmp", sys.argv[1])
srv.serve_forever()
PY
SRV_PID=$!
for _ in $(seq 1 50); do [ -s "$SB/port" ] && break; sleep 0.1; done
PORT=$(cat "$SB/port" 2>/dev/null || true)
check "401 server is up" "$(t [ -n "$PORT" ])"
printf '[credential]\n\thelper = "!f() { touch %s/marker-system; }; f"\n' "$SB" > "$SB/sys.cfg"
printf '[credential]\n\thelper = "!f() { touch %s/marker-global; }; f"\n' "$SB" > "$SB/glob.cfg"
mkdir -p "$SB/neutral"
# positive control: plain git with the same caller environment does call both helpers
( cd "$SB/neutral" && env -u GIT_CONFIG_NOSYSTEM GIT_CONFIG_SYSTEM="$SB/sys.cfg" GIT_CONFIG_GLOBAL="$SB/glob.cfg" \
    GIT_TERMINAL_PROMPT=0 git ls-remote "http://127.0.0.1:$PORT/acme/tool.git" >/dev/null 2>&1 )
check "control: unshut git runs the system helper" "$(t [ -e "$SB/marker-system" ])"
check "control: unshut git runs the global helper" "$(t [ -e "$SB/marker-global" ])"
rm -f "$SB/marker-system" "$SB/marker-global"
rc=$(cd "$SB/neutral" && env -u GIT_CONFIG_NOSYSTEM GIT_CONFIG_SYSTEM="$SB/sys.cfg" GIT_CONFIG_GLOBAL="$SB/glob.cfg" \
       PR_HEAD_TEST_ONLY_REMOTE_BASE="http://127.0.0.1:$PORT" bash "$S" acme/tool 7 "$PRH" >"$SB/o" 2>"$SB/e"; echo $?)
check "401: ERROR exit 2" "$([ "$rc" = 2 ] && grep -q '^result: ERROR not readable anonymously' "$SB/o" && echo 0 || echo 1)" "rc=$rc $(cat "$SB/o")"
check "401: the system credential helper did NOT run" "$(t [ ! -e "$SB/marker-system" ])"
check "401: the global credential helper did NOT run" "$(t [ ! -e "$SB/marker-global" ])"
kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null; SRV_PID=

# 9. stub git (the caller sets every variable the script must override): how git is called, and what a
#    private repository's answer becomes
mkdir -p "$SB/bin"
cat > "$SB/bin/git" <<STUB
#!/usr/bin/env bash
{ echo "ARGS \$*"; echo "PWD \$PWD"; echo "HOME \$HOME"; echo "NOSYSTEM \${GIT_CONFIG_NOSYSTEM:-}";
  echo "SYSTEM \${GIT_CONFIG_SYSTEM:-}"; echo "GLOBAL \${GIT_CONFIG_GLOBAL:-}"; echo "PROMPT \${GIT_TERMINAL_PROMPT:-}";
  echo "ASKPASS \${GIT_ASKPASS:-unset}"; echo "SSH_ASKPASS \${SSH_ASKPASS:-unset}"; echo "ALLOW \${GIT_ALLOW_PROTOCOL:-unset}";
  echo "PARAMS \${GIT_CONFIG_PARAMETERS:-unset}"; echo "SSLNOVERIFY \${GIT_SSL_NO_VERIFY:-unset}";
  echo "CAINFO \${GIT_SSL_CAINFO:-unset}"; echo "PROXY \${https_proxy:-unset} \${HTTPS_PROXY:-unset} \${ALL_PROXY:-unset}";
  echo "LCALL \${LC_ALL:-unset}"; } > "$SB/stub.log"
case "\${STUB_MODE:-}" in
  private) echo "fatal: could not read Username for 'https://github.com': terminal prompts disabled LEAKME" >&2; exit 128 ;;
  net) echo "fatal: unable to access 'https://github.com/acme/tool.git/': Could not resolve host LEAKME" >&2; exit 128 ;;
esac
STUB
chmod +x "$SB/bin/git"
stub() { STUB_MODE=$1 GIT_CONFIG_NOSYSTEM=0 GIT_CONFIG_SYSTEM="$SB/sys.cfg" GIT_CONFIG_GLOBAL="$SB/glob.cfg" \
  GIT_TERMINAL_PROMPT=1 GIT_ASKPASS=/bin/echo SSH_ASKPASS=/bin/echo GIT_ALLOW_PROTOCOL=https:ssh:file \
  GIT_CONFIG_PARAMETERS="'credential.helper'='store'" GIT_SSL_NO_VERIFY=1 GIT_SSL_CAINFO=/tmp/ca.pem \
  https_proxy=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 ALL_PROXY=http://127.0.0.1:9 LC_ALL=hu_HU.UTF-8 PATH="$SB/bin:$PATH" bash "$S" acme/tool 7 "$PRH" >"$SB/o" 2>"$SB/e"; echo $?; }
L="$SB/stub.log"
rc=$(stub private)
check "private repo: ERROR exit 2" "$([ "$rc" = 2 ] && grep -q '^result: ERROR not readable anonymously' "$SB/o" && echo 0 || echo 1)" "rc=$rc"
check "git's stderr text is not passed on" "$(! grep -q LEAKME "$SB/o" "$SB/e" && echo 0 || echo 1)"
check "the github URL, HEAD and the PR ref only" "$(t grep -q 'ls-remote --symref https://github.com/acme/tool.git HEAD refs/pull/7/head$' "$L")" "$(head -1 "$L")"
check "credential.helper emptied" "$(t grep -q -- '-c credential.helper= ' "$L")"
check "redirects off" "$(t grep -q -- '-c http.followRedirects=false' "$L")"
check "core.askPass fails" "$(t grep -Eq -- '-c core.askPass=(/usr)?/bin/false' "$L")"
check "system config off (NOSYSTEM)" "$(t grep -qx 'NOSYSTEM 1' "$L")"
check "system config off (/dev/null)" "$(t grep -qx 'SYSTEM /dev/null' "$L")"
check "global config /dev/null" "$(t grep -qx 'GLOBAL /dev/null' "$L")"
check "terminal prompt off" "$(t grep -qx 'PROMPT 0' "$L")"
check "GIT_ASKPASS fails" "$(t grep -Eqx 'ASKPASS (/usr)?/bin/false' "$L")" "$(grep '^ASKPASS' "$L")"
check "SSH_ASKPASS fails" "$(t grep -Eqx 'SSH_ASKPASS (/usr)?/bin/false' "$L")"
check "https only" "$(t grep -qx 'ALLOW https' "$L")"
check "caller's -c parameters dropped" "$(t grep -qx 'PARAMS unset' "$L")"
check "caller's GIT_SSL_NO_VERIFY dropped" "$(t grep -qx 'SSLNOVERIFY unset' "$L")"
check "caller's GIT_SSL_CAINFO dropped" "$(t grep -qx 'CAINFO unset' "$L")"
check "caller's proxy variables dropped" "$(t grep -qx 'PROXY unset unset unset' "$L")"
check "git runs with LC_ALL=C" "$(t grep -qx 'LCALL C' "$L")"
check "TLS verification forced, proxy emptied" "$(grep -q -- '-c http.sslVerify=true -c http.proxy= ' "$L" && echo 0 || echo 1)"
h=$(sed -n 's/^HOME //p' "$L"); p=$(sed -n 's/^PWD //p' "$L")
check "HOME is not the user's home" "$([ -n "$h" ] && [ "$h" != "$HOME" ] && echo 0 || echo 1)" "HOME=$h"
check "runs from the empty directory" "$([ "$(cd -P "$p" 2>/dev/null && pwd -P)" = "$(cd -P "$h" 2>/dev/null && pwd -P)" ] || [ "$p" = "$h" ] && echo 0 || echo 1)" "PWD=$p HOME=$h"
check "the empty directory is removed" "$(t [ ! -e "$h" ])" "$h"
rc=$(stub net)
check "network failure: ERROR exit 2, no stderr text" "$([ "$rc" = 2 ] && grep -q '^result: ERROR git ls-remote failed' "$SB/o" && ! grep -q LEAKME "$SB/o" "$SB/e" && echo 0 || echo 1)" "rc=$rc"
rc=$(stub empty)
check "empty answer: ERROR, not DIFFERS" "$([ "$rc" = 2 ] && grep -q '^result: ERROR no refs/pull/7/head' "$SB/o" && echo 0 || echo 1)" "rc=$rc"

echo "--- $DONE checks, $FAILS failed"
[ "$FAILS" = 0 ]
