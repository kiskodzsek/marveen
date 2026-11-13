#!/usr/bin/env python3
"""update-apply-gate.py -- PreToolUse (Bash) gate: no direct `marveen-update-safe.py --apply` from an agent shell.

WHY (Klodel 39791, Pulzus 39790, card 840231cf, 2026-11-13): the production-tree update and the restart were
started with `marveen-update-safe.py --apply` without Klodel's explicit "mehet": a delivered, unanswered heads-up
was read as permission. The update now goes through an approval gate (Pulzus: agents/pulzus/scripts/session-1113/
apply_gate.py <go-ahead msg id>), which checks the go-ahead message and then runs --apply as its own child
process. A child process is not an agent tool call, so this hook never sees it; what it stops is the shortcut,
the agent typing the --apply itself.

BLOCKS (exit 2, reason on stderr): a Bash command with a segment (split on newline, ;, &&, ||, |) that names
marveen-update-safe (with or without .py) AND passes --apply or an argparse prefix of it (--a, --ap, --app,
--appl; also --apply=..., and the quoted forms inside a python3 -c / heredoc line).
PASSES: the check (no --apply), `--list`, the approval gate call, the test suite, anything else.
Known gaps (hygiene gate, not a security control): the script name or the flag in a shell variable, split across
lines, or built by an interpreter from pieces; running update.sh itself directly. A text that merely quotes the
forbidden command on one line (echo "...marveen-update-safe.py --apply") is blocked too: write it without the flag.

CONTRACT (hook-exit-code-invariant): exit 2 = block, exit 0 = allow, never exit 1. Malformed stdin or an internal
error allows (fail OPEN) and is recorded in store/hook-errors.log through hook_errlog.
Tests: python3 -I scripts/hooks/update-apply-gate_test.py
"""
import json
import re
import sys

SCRIPT_RX = re.compile(r'(?<![\w.-])marveen-update-safe(?:\.py)?(?![\w-])')
APPLY_RX = re.compile(r'(?<![\w-])--a(?:p(?:p(?:ly?)?)?)?(?=$|[\s\'"=,\]);&|])')
SEGMENT_RX = re.compile(r'\n|;|&&|\|\||\|')
MAX_COMMAND = 256 * 1024

REASON = ('UPDATE-APPLY-KAPU (Klodel 39791): a marveen-update-safe.py --apply közvetlenül nem indítható, csak a '
          'jóváhagyás-kapun át, Klodel kifejezett "mehet"-üzenetének id-jével '
          '(Pulzus: python3 -I agents/pulzus/scripts/session-1113/apply_gate.py <msg_id>). '
          'A csak-ellenőrző futás (--apply nélkül) szabad. / Direct --apply is blocked: run it through the approval '
          'gate with the go-ahead message id.')


def blocked(command):
    if not isinstance(command, str) or not command:
        return False
    for seg in SEGMENT_RX.split(command[:MAX_COMMAND]):
        if SCRIPT_RX.search(seg) and APPLY_RX.search(seg):
            return True
    return False


def main():
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 0
    if not isinstance(payload, dict) or payload.get('tool_name') != 'Bash':
        return 0
    ti = payload.get('tool_input')
    if not isinstance(ti, dict):
        return 0
    try:
        if blocked(ti.get('command')):
            sys.stderr.write(REASON + '\n')
            return 2
    except Exception as ex:  # a crashing gate must not become a silent exit 1
        try:
            import hook_errlog
            hook_errlog.report('update-apply-gate', 'internal error, allowed', ex)
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
