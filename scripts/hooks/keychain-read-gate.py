#!/usr/bin/env python3
"""PreToolUse gate (Bash): an agent shell does not read secrets out of the macOS keychain with `security`.

Why: Viktor 29950 (2026-11-06, card c1921b55). Every agent runs as the same macOS user, so any agent shell can
read any keychain item of that user (another agent's OAuth token, the Vault master key): the accepted structural
risk H1 of 2026-10-12. This gate is the cheap defense-in-depth Viktor asked for, NOT the fix: the fix is per-agent
isolation (H1). It does not see a keychain read made through Python/Node/Swift APIs, osascript's own keychain
calls, or a command name hidden in a variable (`s=security; $s dump-keychain`). Do not rely on it.

What blocks (exit 2): a `security` call in command position whose subcommand reads or exports secrets:
  find-generic-password, find-internet-password, dump-keychain, export,
or that reads its subcommands from stdin (`security -i`, `security -p <prompt>`), which would hide the subcommand.
Command position: the start of the command, or after ; & | ( ) { } a newline, a backtick, $( , an opening quote
(`bash -c "security ..."`, `ssh host 'security ...'`), after find's -exec / -execdir / -ok, and after the
wrapper and keyword words env, sudo, exec, command, nohup, time, nice, xargs, caffeinate, arch, builtin, timeout,
stdbuf, setsid, if, then, else, elif, do, while, until, `!`, their flags, numbers (`timeout 5`, `nice -n 5`) and
VAR=value assignments. A path before it counts (`/usr/bin/security`). Case-insensitive: the default macOS volume
resolves `SECURITY` to the same binary.
Before matching, shell escapes that do not change the word are removed: backslash-newline, a backslash before a
letter (`sec\\urity`), empty quotes inside a word (`sec''urity`), and `$IFS` / `${IFS}` read as a space. A second
pass matches with every quote and backslash removed (`"security" find-...`, `s"ec"urity`, `security "export"`).
Not seen (known gaps, Viktor 30044): a wrapper flag with a word argument (`sudo -u root`, `env -u A`,
`script -q /dev/null`), and everything listed above under "does not see".
Allowed: every other `security` subcommand (list-keychains, find-identity, find-certificate, show-keychain-info,
verify-cert ...) and the word in plain text (`grep find-generic-password notes.md`, `git commit -m "fix: security"`).
Known false positive: a quoted string that starts with the blocked call (`grep "security dump-keychain" f`):
search for the subcommand alone instead.
Any error while matching blocks (fail-closed; exit 1 would not block). Input that is not a Bash call is allowed.
The command text is never logged: it may itself carry a secret.
Tests: keychain-read-gate_test.py next to this file.
"""
import json
import re
import sys

WRAPPERS = (r'(?:env|sudo|exec|command|nohup|time|nice|xargs|caffeinate|arch|builtin|timeout|stdbuf|setsid'
            r'|if|then|else|elif|do|while|until)')
# Command position, then any words that may stand before the command: wrapper words, their flags, a number (a
# duration or a niceness: `timeout 5`, `nice -n 5`), VAR=value assignments, `!`. One token matches one way only (a
# token starts with a letter and is a wrapper, with `-`, with a digit or `+`/`.`, or is NAME=...; `\s+` ends it):
# nesting two ways to read the same token backtracked exponentially (Viktor 30044: 26 x "env a=b " never returned).
POSITION = (r'(?:^|[;&|(){}\n`\'"]|\$\(|\s-(?:exec|execdir|ok)(?=\s))\s*'
            r'(?:(?:' + WRAPPERS + r'\b|!|-\S*|[+.]?\d[\w.]*|\w+=\S*)\s+)*')
BINARY = r'(?:\S*/)?security'
OPTIONS = r'(?:\s+-\S+)*'
SECRET_SUB = r'(?:find-generic-password|find-internet-password|dump-keychain|export)'
RULES = [
    ('secret-read', re.compile(POSITION + BINARY + OPTIONS + r'\s+' + SECRET_SUB + r'(?![\w-])', re.I)),
    ('stdin-mode', re.compile(POSITION + BINARY + r'(?:\s+-\S+)*?\s+-[a-z]*[ip][a-z]*(?=\s|$|[;&|)`\'"])', re.I)),
]


def normalise(cmd):
    cmd = cmd.replace('\\\n', '')                    # line continuation
    cmd = re.sub(r'\\([A-Za-z])', r'\1', cmd)       # sec\urity -> security
    cmd = re.sub(r'(?<=\w)(?:\'\'|"")(?=\w)', '', cmd)  # sec''urity -> security
    cmd = re.sub(r'\$\{IFS\}|\$IFS\b', ' ', cmd)        # security${IFS}dump-keychain -> a space
    return cmd


def hits(cmd):
    text = normalise(cmd)
    # Second pass with every quote and backslash removed: "security" find-..., s"ec"urity, security "export".
    # More false positives than the first pass, which the gate already accepts (see the docstring).
    bare = re.sub(r'[\'"\\]', '', text)
    return [name for name, rx in RULES if rx.search(text) or rx.search(bare)]


def main():
    try:
        data = json.load(sys.stdin)
        ti = data.get('tool_input') or {}
    except Exception:
        return 0
    if not isinstance(ti, dict):
        return 0
    cmd = ti.get('command')
    if not isinstance(cmd, str) or not cmd:
        return 0
    try:
        found = hits(cmd)
    except Exception as e:  # fail-closed
        found = [f'a kapu hibára futott ({e.__class__.__name__}), ezért blokkol']
    if found:
        sys.stderr.write(
            f'KULCSKARIKA-KAPU: a parancs a macOS kulcskarikából olvasna titkot ({", ".join(found)}): '
            'security find-generic-password / find-internet-password / dump-keychain / export, vagy -i/-p mód. '
            'Ágens-shellből ez tilos (Viktor 29950, H1): más ágens credentialje is ott van. Ha egy kulcs kell, '
            'a Vault-wrapper adja (scripts/vault-env-wrapper.sh), az értékét ne írd ki. Ha csak egy szövegben '
            'keresel, a subcommandot keresd magában (pl. grep find-generic-password).\n')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
