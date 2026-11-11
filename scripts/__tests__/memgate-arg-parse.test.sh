#!/usr/bin/env bash
# MEMGATEARG924 -- fleet-memory-gate.sh argument parsing.
#
# WHAT THIS GUARDS, MEASURED 2026-09-24 on the unfixed script:
#   1. `--check` as the LAST argument -> infinite loop. `shift 2` with one
#      argument left is a bash error that shifts nothing, so `$#` stays 1 and
#      `while [[ $# -gt 0 ]]` never ends. Measured: exit 124 under `timeout 5`.
#   2. `--check --dry-run` -> the switch was SWALLOWED as the agent name
#      (ARG="--dry-run") and DRY_RUN stayed 0. That is the quiet one: a run
#      asked to be side-effect free wrote the safe-mode flag and attempted a
#      Telegram alert. Measured: the flag appeared.
#
# The live callers pass a name (channel-monitor.ts execFileSync, and
# fleet-safe-start.sh:78/80), and channel-monitor additionally has a 5s timeout
# plus fail-open, so case 1 does not freeze the fleet today. Case 2 is reachable
# by hand, which is precisely when a human is being careful.
#
# MEMGATE_SCRIPT overrides the script under test (used to measure the fix
# before/after); it defaults to the repo copy.
#
# Run:  bash scripts/__tests__/memgate-arg-parse.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
GATE="${MEMGATE_SCRIPT:-$ROOT/scripts/fleet-memory-gate.sh}"
# MUSZER-ONIGAZOLAS (HEX merte 2026-09-24): 3 of the 9 of these assertions PASS against a
# script that does not exist, because a no-op assertion is satisfied by nothing
# just as well as by correct silence. The suite cannot tell "correctly did
# nothing" from "was not there at all" -- so it must first prove its own target.
# Same principle as the positive control below, pointed the other way.
[ -x "$GATE" ] || { echo "FATAL: the script under test is missing or not executable: $GATE" >&2; exit 2; }

FAILS=0; DONE=0

check() { DONE=$((DONE+1)); if [ "$2" = "0" ]; then echo "PASS  $1"; else echo "FAIL  $1${3:+  -- $3}"; FAILS=$((FAILS+1)); fi; }

SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/memgatearg.XXXXXX")"
trap 'rm -rf "$SANDBOX"' EXIT
mkdir -p "$SANDBOX/store" "$SANDBOX/bin"

# curl stub: nothing leaves the machine even if an alert is attempted.
cat > "$SANDBOX/bin/curl" <<'STUB'
#!/usr/bin/env bash
echo '{"ok":true,"result":{"message_id":1}}'
STUB
chmod +x "$SANDBOX/bin/curl"

# Well past the hard band, so the safe-mode flag is written on every non-dry run.
printf 'MemTotal:       16000000 kB\nMemAvailable:     400000 kB\n' > "$SANDBOX/meminfo"

SAFE_FLAG="$SANDBOX/store/.fleet-safe-mode"

# _timeout <sec> <cmd...>: GNU timeout semantics (exit 124 when it had to kill).
# macOS ships no `timeout`; there `env ... timeout` exited 127 before the gate
# ever ran, so 7 of 9 checks failed AND check 1 ("terminates", RC != 124) went
# green on a run that measured nothing (2026-10-15). gtimeout (coreutils) if
# present, else a perl fork+alarm with the same 124 contract.
_timeout() {
  local secs="$1"; shift
  if command -v timeout >/dev/null 2>&1; then timeout "$secs" "$@"; return $?; fi
  if command -v gtimeout >/dev/null 2>&1; then gtimeout "$secs" "$@"; return $?; fi
  perl -e '
    my $s = shift; my $pid = fork; die "fork: $!" unless defined $pid;
    if (!$pid) { setpgrp(0, 0); exec @ARGV; exit 127 }
    $SIG{ALRM} = sub { kill "KILL", -$pid; waitpid $pid, 0; exit 124 };
    alarm $s; waitpid $pid, 0;
    exit(($? & 127) ? 128 + ($? & 127) : $? >> 8);
  ' "$secs" "$@"
}
# The instrument proves itself before it is trusted: it must pass an exit code
# through AND kill a hang with 124, or every RC below means nothing.
_timeout 5 bash -c 'exit 3'; [ $? = 3 ] || { echo "FATAL: _timeout does not pass the exit code through" >&2; exit 2; }
_timeout 1 bash -c 'while :; do :; done'; [ $? = 124 ] || { echo "FATAL: _timeout does not stop a hang with 124" >&2; exit 2; }

# run_gate <timeout-sec> <args...>  -> exit code in RC, stdout+stderr in OUT
run_gate() {
  local secs="$1"; shift
  rm -f "$SAFE_FLAG" "$SANDBOX/store/.fleet-memgate-alert"
  OUT="$(_timeout "$secs" env PATH="$SANDBOX/bin:$PATH" \
      MEMGATE_PROC_MEMINFO="$SANDBOX/meminfo" \
      MARVEEN_STORE="$SANDBOX/store" \
      MARVEEN_ALERT_CHAT_ID="111" \
      MARVEEN_CORE_AGENTS="__no_core__" \
      MARVEEN_MEM_GATE_OBSERVE=0 \
      bash "$GATE" "$@" 2>&1)"
  RC=$?
}

# 1. `--check` alone must terminate (the infinite loop), and fail open.
run_gate 5 --check
check "--check alone terminates (no infinite loop)" \
      "$([ "$RC" != "124" ] && echo 0 || echo 1)" "exit 124 = timeout killed it"
check "--check alone fails open with no-agent" \
      "$(echo "$OUT" | grep -q 'no-agent: allow' && echo 0 || echo 1)" "got: $OUT"

# 2. POSITIVE CONTROL: without --dry-run the flag MUST appear, otherwise test 3
#    would pass for the wrong reason (a blind instrument).
run_gate 5 --check somebody
check "positive control: a non-dry run DOES write the safe-mode flag" \
      "$([ -f "$SAFE_FLAG" ] && echo 0 || echo 1)" "flag missing; the check below would be vacuous"

# 3. `--check --dry-run` must not be swallowed: no flag, and the dry-run log line.
run_gate 5 --check --dry-run
check "--check --dry-run stays dry (no safe-mode flag written)" \
      "$([ ! -f "$SAFE_FLAG" ] && echo 0 || echo 1)" "flag was written: --dry-run was swallowed"
check "--check --dry-run reaches the alert as DRY-RUN" \
      "$(echo "$OUT" | grep -q 'DRY-RUN alert' && echo 0 || echo 1)" "got: $OUT"

# 4. The normal, documented form must keep working.
run_gate 5 --check somebody --dry-run
check "--check <agent> --dry-run still dry" \
      "$([ ! -f "$SAFE_FLAG" ] && echo 0 || echo 1)" "flag was written"
check "--check <agent> --dry-run still names the agent" \
      "$(echo "$OUT" | grep -q 'somebody' && echo 0 || echo 1)" "got: $OUT"

# 5. The other modes are untouched.
run_gate 5 --status --dry-run
check "--status still reports a status line" \
      "$(echo "$OUT" | grep -q 'used=' && echo 0 || echo 1)" "got: $OUT"
run_gate 5 --verdict --dry-run
check "--verdict still reports a status line" \
      "$(echo "$OUT" | grep -q 'used=' && echo 0 || echo 1)" "got: $OUT"

# 6. The running-agent count with a stubbed tmux, so the host's own sessions do not decide the result
#    (card ac602965, CI run 42805724668). `grep -c` prints 0 AND exits 1 on no match, so the old
#    `grep -c ... || echo 0` made running="0<newline>0": the status line split in two and
#    `(( running >= AGENT_CAP ))` was a syntax error. It passed on the Mac mini only because live
#    agent-* sessions made grep exit 0.
printf 'MemTotal:       16000000 kB\nMemAvailable:    8000000 kB\n' > "$SANDBOX/meminfo-ok"
# run_counted <tmux ls output> <args...>: healthy memory, a tmux stub printing the given sessions
run_counted() {
  local sessions="$1"; shift
  printf '#!/usr/bin/env bash\nprintf "%%s" "%s"\n' "$sessions" > "$SANDBOX/bin/tmux"; chmod +x "$SANDBOX/bin/tmux"
  OUT="$(_timeout 5 env PATH="$SANDBOX/bin:$PATH" MEMGATE_PROC_MEMINFO="$SANDBOX/meminfo-ok" \
      MARVEEN_STORE="$SANDBOX/store" MARVEEN_ALERT_CHAT_ID="111" MARVEEN_CORE_AGENTS="__no_core__" \
      MARVEEN_MEM_GATE_OBSERVE=0 MARVEEN_AGENT_CAP=2 bash "$GATE" "$@" 2>&1)"
  RC=$?
}
run_counted "" --verdict --dry-run
check "no agent session: one status line, running_agents=0, src at its end" \
      "$([ "$(printf '%s\n' "$OUT" | wc -l | tr -d ' ')" = 1 ] && echo "$OUT" | grep -q 'running_agents=0 cap=2 .*src=meminfo$' && echo 0 || echo 1)" "got: $OUT"
check "no agent session: --verdict allows (exit 0), no arithmetic error" \
      "$([ "$RC" = 0 ] && ! echo "$OUT" | grep -q 'syntax error' && echo 0 || echo 1)" "rc=$RC got: $OUT"
run_counted "$(printf 'agent-a: 1 windows\nagent-b: 1 windows\nother: 1 windows')" --verdict --dry-run
check "two agent sessions at cap 2: running_agents=2 and --verdict blocks (exit 10)" \
      "$([ "$RC" = 10 ] && echo "$OUT" | grep -q 'running_agents=2 cap=2' && echo 0 || echo 1)" "rc=$RC got: $OUT"
rm -f "$SANDBOX/bin/tmux"

echo
echo "$((DONE-FAILS))/$DONE passed  (script under test: $GATE)"
[ "$FAILS" = "0" ] || exit 1
