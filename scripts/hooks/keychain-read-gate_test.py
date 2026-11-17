#!/usr/bin/env python3
"""Tests for keychain-read-gate.py (card c1921b55, Viktor 29950).

Runs the hook as Claude Code does (JSON on stdin; exit 0 allow, 2 block). Hermetic: no keychain call, no store
file, no network; the commands are only text.
Run: python3 -I scripts/hooks/keychain-read-gate_test.py
"""
import json
import os
import subprocess
import sys

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'keychain-read-gate.py')
# the repo's own agent-msg.sh, the one data recipient by path (card 8a5d51e8, Viktor 42575)
AM = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'agent-msg.sh'))
AM_ROOT = os.path.dirname(os.path.dirname(AM))

# The fixtures spell the binary with a 3 for its first e ("s3curity"); fix() restores it at run time, so this file
# carries no runnable keychain call and running it is not blocked by the gate it tests (card bc009036). The git
# credential fixtures likewise spell "cr3dential" (card 04d67b39).
def fix(cmd):
    return (cmd.replace('s3c', 'sec').replace('S3C', 'SEC').replace('s"3c"', 's"ec"')
            .replace('cr3d', 'cred').replace('CR3D', 'CRED'))


BLOCK = [
    's3curity find-generic-password -s "Claude Code-credentials" -w',
    's3curity find-internet-password -s example.test',
    's3curity dump-keychain',
    's3curity dump-keychain -d login.keychain-db',
    's3curity export -k login.keychain -t certs -o /tmp/x.p12',
    '/usr/bin/s3curity dump-keychain',
    'S3CURITY find-generic-password -s x',
    's3curity -q find-generic-password -s x',
    'env -i s3curity dump-keychain',
    'env FOO=bar PATH=/usr/bin s3curity export',
    'sudo s3curity find-generic-password -s x',
    'FOO=1 s3curity find-internet-password -s x',
    'xargs s3curity dump-keychain < /dev/null',
    'ls; s3curity dump-keychain',
    'ls && s3curity export -o x',
    'true || s3curity find-generic-password -w -s x',
    'cat a | s3curity dump-keychain',
    'x=$(s3curity find-generic-password -w -s y); echo ok',
    'echo `s3curity find-generic-password -w -s y`',
    'bash -c "s3curity dump-keychain"',
    "sh -c 's3curity find-generic-password -s x -w'",
    'ssh host \'s3curity dump-keychain\'',
    's3c\\urity dump-keychain',
    "s3c''urity dump-keychain",
    's3curity \\\n  dump-keychain',
    'echo dump-keychain | s3curity -i',
    's3curity -p "> " < cmds.txt',
    '( s3curity dump-keychain )',
    'if true; then\ns3curity export\nfi',
    # Viktor 30044 hardening: keyword positions, quoted words, $IFS, wrappers with an argument, find -exec.
    'if true; then s3curity dump-keychain; fi',
    'while true; do s3curity export; done',
    '! s3curity dump-keychain',
    '"s3curity" find-generic-password -s x',
    's"3c"urity dump-keychain',
    's3curity "find-generic-password" -s x',
    's3curity find-generic-"password" -s x',
    's3curity${IFS}find-generic-password -s x',
    's3curity$IFS dump-keychain',
    'timeout 5 s3curity dump-keychain',
    'timeout .5 s3curity dump-keychain',
    'nice -n 5 s3curity dump-keychain',
    'stdbuf -o0 s3curity export',
    'setsid s3curity dump-keychain',
    'find . -name x -exec s3curity dump-keychain {} +',
    # card 3085a683 (Viktor 30044 known gap, 41831 INFO 3): a wrapper flag with a word argument, or a wrapper's
    # positional word, no longer breaks the chain (all allow on 43305327)
    'sudo -u root s3curity find-generic-password -s x',
    'sudo -Eu root s3curity dump-keychain',
    'sudo -uroot s3curity dump-keychain',  # the word attached: the next one is the command
    'sudo -h s3curity dump-keychain',  # a mark in the wrong place (if -h took no word) never lifts a block
    'sudo -u root s3curity find-generic-password -s x -w',
    'sudo --user root s3curity dump-keychain',
    'sudo --user=root -g wheel s3curity dump-keychain',
    'sudo -p "Pass: " s3curity dump-keychain',
    'sudo -u $(whoami) s3curity dump-keychain',
    'sudo -- s3curity dump-keychain',
    '/usr/bin/sudo -u root s3curity dump-keychain',
    '/usr/bin/env -u HOME s3curity dump-keychain',  # a path before the wrapper (main: allow; the sudo row is not)
    '/usr/bin/ssh h s3curity dump-keychain',
    'SUDO -u root s3curity dump-keychain',
    '"sudo" "-u" root s3curity dump-keychain',
    'doas -u root s3curity dump-keychain',
    'env -u HOME s3curity dump-keychain',
    'env -u HOME -u PATH A=1 s3curity export',
    'env -C /tmp s3curity export',
    'timeout -s KILL 5 s3curity dump-keychain',
    'timeout -k 1 -s TERM 5s s3curity dump-keychain',
    'timeout --signal KILL 5 s3curity dump-keychain',
    'exec -a x s3curity dump-keychain',
    'script -q /dev/null s3curity dump-keychain',
    'script -q -t 0 /dev/null s3curity dump-keychain',
    'ssh localhost s3curity dump-keychain',
    'ssh -p 22 -i key -o BatchMode=yes localhost s3curity find-generic-password -s x',
    'flock /tmp/l s3curity dump-keychain',
    'flock -w 5 /tmp/l s3curity dump-keychain',
    'sg staff s3curity dump-keychain',
    'chroot / s3curity dump-keychain',
    'xargs -I {} s3curity dump-keychain {}',
    'arch -arch x86_64 s3curity dump-keychain',
    'caffeinate -t 5 s3curity dump-keychain',
    'time -o /tmp/t s3curity dump-keychain',
    'stdbuf -o L s3curity export',
    'nice -n 5 sudo -u root env -u HOME s3curity dump-keychain',  # wrappers in a row
    'sudo -u a env -u B timeout -s KILL 5 ssh h s3curity dump-keychain',
    'ls; sudo -u root s3curity dump-keychain',
    'bash -c "sudo -u root s3curity dump-keychain"',
    # accepted false positive, the class above: a quoted string that starts with the blocked call
    'git commit -m "sudo -u root s3curity dump-keychain"',
    # Viktor 41970 LOW 1: an escaped blank or separator is part of the flag's word
    'sudo -p a\\ b s3curity find-generic-password -s x',
    'sudo -p a\\)b s3curity dump-keychain',
    'sudo -p a\\;b s3curity dump-keychain',
    'sudo -p a\\&b s3curity dump-keychain',
    'sudo -p a\\|b s3curity dump-keychain',
    'sudo -p a\\`b s3curity dump-keychain',
    'sudo -u a\\ b -u c s3curity dump-keychain',
    'env -u A\\ B s3curity dump-keychain',
    'ssh -o A\\ B host s3curity dump-keychain',
    # Viktor 41970 LOW 2: a wrapper written with its path is no CHAIN word, with or without a flag
    '/usr/bin/env s3curity find-generic-password -s x',
    '/usr/bin/env -i s3curity dump-keychain',
    '/usr/bin/env A=b s3curity dump-keychain',
    '/usr/bin/nice s3curity dump-keychain',
    '/usr/bin/caffeinate s3curity dump-keychain',
    '/usr/bin/caffeinate -i s3curity dump-keychain',
    '/usr/bin/arch s3curity dump-keychain',
    '/usr/bin/xargs s3curity dump-keychain',
    '/usr/bin/time s3curity dump-keychain',
    '/usr/bin/nohup s3curity dump-keychain',
    'sudo -u root /usr/bin/env s3curity dump-keychain',
    # a chain is walked once per pass (Viktor 41970 LOW 3), yet a command substitution in a flag's argument, which
    # runs, still blocks
    'sudo -u "$(env -u X s3curity dump-keychain)" ls',
    "sudo -p 'a b' sudo -u \"$(env -u X s3curity dump-keychain)\" ls",
    # card 04d67b39 (Viktor 41943 HIGH, Klodel 41948): git's credential paths into the login keychain (all allow
    # on f877074a)
    'git cr3dential fill',
    'git cr3dential approve',
    'git cr3dential reject',
    'git -C /tmp cr3dential fill',
    'git -c a=b -c c=d cr3dential fill',
    'git --git-dir /x/.git cr3dential fill',
    'git --git-dir=/x/.git --no-pager cr3dential fill',
    "printf 'protocol=https\\nhost=github.com\\n\\n' | git cr3dential fill",
    'echo x | /usr/bin/git cr3dential fill',
    '"git" cr3dential fill',
    'GIT CR3DENTIAL FILL',  # the default macOS volume is case-insensitive
    'git cr3dential "fill"',
    'x=$(git cr3dential fill)',
    "bash -c 'git cr3dential fill'",
    'python3 -c "import os; os.system(\'git cr3dential fill\')"',
    'ssh localhost git cr3dential fill',
    'sudo -u root git cr3dential fill',
    'git cr3dential-osxkeychain get',
    'git cr3dential-osxkeychain erase',
    'git-cr3dential-osxkeychain get',
    'git-cr3dential-osxkeychain',
    '/Library/Developer/CommandLineTools/usr/libexec/git-core/git-cr3dential-osxkeychain get',
    'xcrun git cr3dential fill',
    'xcrun -sdk macosx git cr3dential fill',
    'xcrun s3curity find-generic-password -s x',  # xcrun is a wrapper too
    'git -c cr3dential.helper=osxkeychain fetch',
    'git -c "cr3dential.helper=osxkeychain" push origin HEAD',
    'git -c cr3dential.helper= -c cr3dential.helper=osxkeychain ls-remote origin',
    'git config --global cr3dential.helper osxkeychain',
    'git config --system --add cr3dential.helper osxkeychain',
    'GIT_CONFIG_PARAMETERS="\'cr3dential.helper\'=\'osxkeychain\'" git fetch',
    'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=cr3dential.helper GIT_CONFIG_VALUE_0=osxkeychain git fetch',
    # card 49d58372 (Viktor 42039 MEDIUM 1): the ~/.gitconfig helper reset taken away before git, or rewritten
    'HOME=/tmp/x git fetch',
    'GIT_CONFIG_GLOBAL=/dev/null git ls-remote origin',
    'GIT_CONFIG_SYSTEM=/tmp/s git fetch',
    'env HOME=/tmp/x git fetch',
    'env -i git fetch',
    'env -i PATH=/usr/bin /usr/bin/git ls-remote origin',
    'env -u HOME git fetch',
    'env --unset=HOME git fetch',
    'env --unset HOME git fetch',
    'env - git fetch',
    'sudo -u a HOME=/x git fetch',
    'timeout 5 env -u HOME git fetch',
    'xcrun env -i git fetch',
    'cd /tmp && HOME=$PWD git fetch',
    'export HOME=/tmp/x; git fetch',
    'export GIT_CONFIG_GLOBAL=/dev/null && git push',
    'HOME=/tmp/x; git fetch',
    'unset HOME; git fetch',
    'HOME="/tmp/x y" git fetch',
    "HOME=/x bash -c 'git fetch'",
    'env -i bash -c "git ls-remote origin"',
    'git -c include.path=/tmp/e.cfg fetch',
    'git -c "include.path=/tmp/e.cfg" fetch',
    'git -c includeIf.gitdir:/x/.path=/tmp/e.cfg fetch',
    'git --config-env=cr3dential.helper=H fetch',
    'git --config-env cr3dential.helper=H fetch',
    'git --config-env=include.path=F fetch',
    'GIT_CONFIG_PARAMETERS="\'include.path\'=\'/tmp/e.cfg\'" git fetch',
    'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=include.path GIT_CONFIG_VALUE_0=/tmp/e.cfg git fetch',
    'git -c cr3dential.https://github.com.helper=osxkeychain fetch',
    'git config cr3dential.https://github.com.helper osxkeychain',
    "git config --global cr3dential.helper ''",
    'git config --global --unset-all cr3dential.helper',
    'git config --global --unset cr3dential.helper',
    'git config --system cr3dential.helper x',
    'git config --global --remove-section cr3dential',
    'git config --global --rename-section cr3dential old',
    'git config --global -e',
    'git config --global --edit',
    'git config edit --global',
    'git config set --global cr3dential.helper x',
    'git config unset --global cr3dential.helper',
    "git config --file ~/.gitconfig cr3dential.helper ''",
    'git config --file=/Users/x/.gitconfig cr3dential.helper x',
    'git config -f /Users/x/.gitconfig --unset cr3dential.helper',
    'git config --global cr3dential.https://github.com.helper x',
    'git config include.path /tmp/e.cfg',
    'git config --local include.path /tmp/e.cfg',
    'git config --global includeIf.gitdir:~/x/.path /tmp/e.cfg',
    'git -C /tmp/r config --global --unset-all cr3dential.helper',
    'GIT_CONFIG_NOSYSTEM=0 GIT_CONFIG_GLOBAL=/dev/null git fetch',  # 0 keeps the system helper (measured)
    'GIT_CONFIG_NOSYSTEM=1 env -u GIT_CONFIG_NOSYSTEM HOME=/x git fetch',
    'export GIT_CONFIG_NOSYSTEM=1; unset GIT_CONFIG_NOSYSTEM; HOME=/x git fetch',
    'export GIT_CONFIG_NOSYSTEM=1; unset GIT_CONFIG_NOSYSTEM; GIT_CONFIG_GLOBAL=/dev/null git fetch',  # the unset alone (mutant, 15896271)
    # Viktor 42251 MEDIUM 1: a redirection between the assignment and git hid the git (measured, bash 3.2 and zsh: the
    # osxkeychain helper is the last value)
    'HOME=/x 2>&1 git fetch origin',
    'HOME=/x >/dev/null git fetch origin',
    'GIT_CONFIG_GLOBAL=/dev/null 2>&1 git fetch origin',
    'env -i 2>&1 git fetch origin',
    'env >/dev/null HOME=/x git fetch origin',
    'HOME=/x >/dev/null; git fetch origin',
    'HOME=/x > /dev/null git fetch origin',  # the target as a word of its own
    'HOME=/x &>/dev/null git fetch origin',  # the & before and after the operator (mutant, d868a616)
    'HOME=/x >& /dev/null git fetch origin',
    # Viktor 42295 LOW 1: rows for his surviving mutants (the gate blocked them already; nothing guarded it)
    'echo a | HOME=/x git fetch origin',  # a pipe ends the simple command (N02)
    'true | env -i git fetch origin',
    'echo a | GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    'HOME=/x >| f git fetch origin',  # >| with its target as a word of its own (N04)
    'env >| f HOME=/x git fetch origin',
    'HOME=/x <<< x git fetch origin',  # << and <<< with the word apart (N05)
    'HOME=/x << EOF git fetch origin',
    'HOME=/x <<- EOF git fetch origin',  # the <<- heredoc (N06)
    # Viktor 42251 INFO 6: an expanded word may be the option (`N=-n`): no export
    'export $N GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    'export `printf -- -n` GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    'HOME=/x git -c cr3dential.helper=foo fetch',  # a helper added, the system one kept
    'HOME=/x git -c cr3dential.helper= -c cr3dential.helper=osxkeychain fetch',
    'HOME=/x node -e "require(\'child_process\').execSync(\'git fetch\')"',
    'HOME=/x python3 -c "import os; os.system(\'git fetch\')"',  # the ; is inside the quotes: same command
    'HOME=/x git -C /r config --unset user.name',
    'env -i git config --global cr3dential.helper x',
    'if HOME=/x git fetch; then :; fi',  # a chain word between the prefix and git
    '! HOME=/x git fetch',
    'env --ignore-environment git fetch',
    # Viktor 42207 M1: NOSYSTEM does not cover a config FILE or a HOME the call names (it can name the helper itself)
    'GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/tmp/f git fetch origin',
    'GIT_CONFIG_NOSYSTEM=1 HOME=/tmp/h git fetch origin',
    'export GIT_CONFIG_NOSYSTEM=1; export GIT_CONFIG_GLOBAL=/tmp/f; git fetch origin',
    # Viktor 42207 M2: a NOSYSTEM that is not exported is a shell variable only (measured: the system helper is back)
    'GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    'GIT_CONFIG_NOSYSTEM=1 && env -u HOME git fetch',
    'GIT_CONFIG_NOSYSTEM=1\nGIT_CONFIG_GLOBAL=/dev/null git fetch',
    'declare GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch',
    'readonly GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch',
    'f() { local GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch; }; f',
    'export GIT_CONFIG_NOSYSTEM=1; declare GIT_CONFIG_NOSYSTEM=0; GIT_CONFIG_GLOBAL=/dev/null git fetch',
    # Viktor 42224 LOW 1: an unexport takes the exemption away (measured, bash 3.2 and zsh: the system helper is back);
    # a -x after the name is a name in bash 3.2, readonly never exports
    'export -n GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    'export GIT_CONFIG_NOSYSTEM=1; declare +x GIT_CONFIG_NOSYSTEM; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    'declare +x GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    'export GIT_CONFIG_NOSYSTEM=1; export -n GIT_CONFIG_NOSYSTEM; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    'declare GIT_CONFIG_NOSYSTEM=1 -x; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    'declare -- -x GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    'readonly -x GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    # an option outside x, g, r: invalid in bash 3.2 and zsh (the declaration fails, nothing is exported; measured)
    'declare -nx GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    'typeset -nx GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    'export -q GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    'export -f GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    # Viktor 42207 M3: a declaration longer than MAX_ARGS words is read to its end
    'f() { local HOME; git fetch; }; f',  # a local without a value: HOME unset in the function (measured)
    'f() { declare HOME; git fetch; }; f',
    "K=cr3dential.helper; git config --global $K ''",  # an expanded word can be any key or scope
    "git config --global \"$K\" ''",
    "git config $(echo --global) cr3dential.helper ''",
    "git config --global `echo cr3dential.helper` ''",
    "git config --global cr3dential.{helper,x} ''",
    'git config $K /tmp/e.cfg',
    "git config --global ${K} ''",
    "git config --global cr3d$(echo ential.helper) ''",
    "git config --global$(echo) cr3dential.helper ''",
    "git config --global cr3dential.h* ''",
    'HOME=/x git -ccr3dential.helper= ls-remote x',  # joined: no git option (git: unknown option), not a reset
    # accepted false positive, the class above
    "grep -n 'git cr3dential fill' notes.md",
    # card 15896271 (Viktor 41970 INFO 5): a redirection before the command
    '>/dev/null s3curity find-generic-password -s x',
    '2>/dev/null s3curity dump-keychain',
    '2> /dev/null s3curity dump-keychain',
    '</dev/null s3curity dump-keychain',
    '>&2 s3curity dump-keychain',
    '&>/dev/null s3curity dump-keychain',
    # Viktor 42251 LOW 3: noclobber, here-string and heredoc before the command
    '>|f s3curity dump-keychain',
    '<<<x s3curity dump-keychain',
    '<<EOF s3curity dump-keychain',
    # Viktor 42251 LOW 4: launchctl submit runs the command after --
    'launchctl submit -l a -o /tmp/o -- /usr/bin/s3curity dump-keychain',
    'launchctl submit -l a -e /tmp/e -o /tmp/o -- s3curity dump-keychain',
    # -p prog runs prog with the words after -- as argv, argv0 any word (Dave, measured on this branch): not read, blocks
    'launchctl submit -l a -p /usr/bin/s3curity -- s3curity dump-keychain',
    'launchctl submit -l a -p /usr/bin/s3curity -- x dump-keychain',
    'launchctl submit -l a -p /usr/bin/env -- x s3curity dump-keychain',
    'sudo launchctl submit -p /usr/bin/s3curity -l a -- x dump-keychain',
    'launchctl submit -l a -p /bin/echo -- echo hi',  # fail-closed: any -p blocks
    # Viktor 42295 LOW 1: the p in any flag word, joined or bundled (N33, N34), and <<- before the call (N19)
    'launchctl submit -l a -p/usr/bin/s3curity -- x dump-keychain',
    'launchctl submit -lp a /usr/bin/s3curity -- x dump-keychain',
    'launchctl submit -l a -pl /usr/bin/s3curity -- x dump-keychain',
    'launchctl submit -l a -op x /usr/bin/s3curity -- x dump-keychain',
    '<<- EOF s3curity dump-keychain',
    'echo a; >>log s3curity dump-keychain',
    'sudo -u root >/dev/null s3curity dump-keychain',
    'env >>log s3curity dump-keychain',
    # Viktor 41970 LOW 4: the macOS wrappers that run their command, and doas as a chain word
    'doas s3curity dump-keychain',
    'doas -n s3curity dump-keychain',
    'sandbox-exec -p "(version 1)(allow default)" s3curity dump-keychain',
    'sandbox-exec -n no-network -D A=b s3curity dump-keychain',
    'lockf -k /tmp/l s3curity dump-keychain',
    'launchctl asuser 501 s3curity dump-keychain',
    '/bin/launchctl bsexec 1 s3curity dump-keychain',
    'login -fp root s3curity dump-keychain',
    'login -f -h h root s3curity dump-keychain',
    'sandbox-exec s3curity dump-keychain',  # a chain word with no flag skipped (mutant sandbox_chain_out)
    'sudo 2>&1 s3curity dump-keychain',
    # card fae0712e (differential fuzz against bash and zsh, both ran line 2): normalise() joined a backslash-newline
    # whose backslash ends a comment or is the second half of an escaped backslash; the next line is a command
    ': |#\\\ns3curity dump-keychain',
    'echo x \\\\\ns3curity dump-keychain',
    'true # a \\\ns3curity find-generic-password -s x',
]
# Viktor 41970 INFO 6: one row per WRAP_ARGS entry, so a dropped or mistyped entry fails here. A spec of its own,
# not read from the gate: wrapper -> (short flags with a word, whole flags with the next word, positional words).
WRAP_SPEC = {
    'sudo': ('CDghprRtTuU', ['--user', '--group', '--close-from', '--chdir', '--host', '--prompt', '--role', '--type',
                             '--command-timeout', '--other-user', '--chroot'], 0),
    'doas': ('Cu', [], 0),
    'env': ('uCP', ['--unset', '--chdir'], 0),
    'timeout': ('sk', ['--signal', '--kill-after'], 1),
    'nice': ('n', ['--adjustment'], 0),
    'xargs': ('IJLnPEdsaRS', ['--max-args', '--max-procs', '--delimiter', '--arg-file', '--max-lines', '--replace',
                              '--eof', '--max-chars'], 0),
    'stdbuf': ('ioe', ['--input', '--output', '--error'], 0),
    'exec': ('a', [], 0),
    'time': ('of', ['--output', '--format'], 0),
    'caffeinate': ('tw', [], 0),
    'arch': ('', ['-arch'], 0),
    'script': ('tTEoIOBm', ['--timing', '--log-io', '--log-in', '--log-out', '--log-timing', '--logging-format',
                            '--echo', '--output-limit'], 1),
    'ssh': ('BbcDEeFIiJLlmOopQRSWw', [], 1),
    'flock': ('wE', ['--timeout', '--wait', '--conflict-exit-code'], 1),
    'sg': ('', [], 1),
    'chroot': ('ugG', ['--userspec', '--groups'], 1),
    # card 15896271
    'sandbox-exec': ('fnpD', [], 0),
    'lockf': ('t', [], 1),
    'launchctl': ('', [], 2),
    'login': ('h', [], 1),
    # card 04d67b39
    'git': ('Cc', ['--git-dir', '--work-tree', '--namespace', '--config-env', '--super-prefix'], 0),
    'xcrun': ('f', ['-sdk', '--sdk', '-toolchain', '--toolchain', '--find'], 0),
}
for _w, (_short, _whole, _pos) in WRAP_SPEC.items():
    _tail = ' p0s' * _pos + ' s3curity dump-keychain'  # the word is a letter run: CHAIN would read a number
    BLOCK += [f'{_w} -{c} w0rd{_tail}' for c in _short] + [f'{_w} {f} w0rd{_tail}' for f in _whole]
    if _pos:
        BLOCK.append(f'{_w}{_tail}')
BLOCK += ['/usr/bin/' + w + ' s3curity dump-keychain' for w in ('setsid', 'command', 'builtin')]  # path only (nohup above)

BLOCK += ['export ' + 'A ' * k + 'HOME=/x; git fetch origin' for k in (63, 64, 65, 200)]
BLOCK += ['declare -x ' + 'A ' * 100 + 'HOME=/x; git fetch', 'unset ' + 'A ' * 100 + 'HOME; git fetch',
          'export ' + 'A=1 ' * 100 + 'GIT_CONFIG_GLOBAL=/dev/null; git fetch']
# Viktor 42207 mutation survivors: the git call's own words past MAX_ARGS are not read (fail-closed: a reset after
# them is not seen); a backtick starts a command
BLOCK += ['HOME=/x git ' + '-C . ' * 40 + '-c cr3dential.helper= ls-remote x', 'echo `HOME=/x git fetch`']
# card d11364a4 (Viktor 42835 / f526b8c6 verdict, pre-existing LOW): a quoted or escaped command name right where a
# shell -c payload starts. Top-level forms block already; in the payload the escaping of the outer quotes (\" \\)
# hid the name: 51 of 252 generated forms passed on f6d09386 (work/d11364a4/probe.py). The payload is now taken out
# with bash's own quote rules and judged as a command of its own.
def _dq(c):
    return c.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')


_KC_NAMES = ['\\s3curity', 's3c""urity', "s3c''urity", 's3c\\urity', '"s3curity"', "'s3curity'"]
_KC_SUBS = ['find-generic-password -a x -w', 'dump-keychain', 'find-internet-password -s x -w', 'export -o /tmp/x']
for _sh in ('bash -c', 'sh -c', 'bash -lc', 'zsh -c', '"$SHELL" -c', 'bash -c -o pipefail'):
    for _nm in _KC_NAMES:
        for _sb in _KC_SUBS:
            BLOCK.append(_sh + ' "' + _dq(_nm + ' ' + _sb) + '"')
            if "'" not in _nm:
                BLOCK.append(_sh + " '" + _nm + ' ' + _sb + "'")
# nested: a payload inside a payload, and after a ; inside the payload
BLOCK += ['bash -c "sh -c \\"\\\\\\"s3curity\\\\\\" dump-keychain\\""', "bash -c 'true; \"s3curity\" dump-keychain'",
          'bash -c "echo a; \\"s3curity\\" export"']
# MAX_PAYLOADS (64) distinct quoted payloads are read again; a 65th blocks ('payload-unread') instead of going unread
BLOCK += ['bash -c ' + ' '.join("'\"a%d\"'" % i for i in range(65)),
          'bash -c ' + ' '.join("'\"a%d\"'" % i for i in range(64)) + " '\"s3curity\" dump-keychain'"]
# mutation survivors (work/d11364a4/mut.out, kill-probe.py): a payload PAYLOAD_OPEN opens (tmux new, do shell script,
# eval around a shell) is read again too; an escaped quote opens none, so it cannot swallow the payload after it
BLOCK += ['tmux new -d "' + _dq('"s3curity" dump-keychain') + '"',
          "osascript -e 'do shell script \"" + _dq('"s3curity" dump-keychain') + "\"'",
          'eval "' + _dq('bash -c "' + _dq('"s3curity" dump-keychain') + '"') + '"',
          "eval \\'x ; bash -c '\"s3curity\" dump-keychain'"]
# card aeee72df (Viktor 42941, pre-existing on main; each form ran under a real bash 3.2 with a proxy rule,
# work/aeee72df/probe.py). LOW 1: a payload past PAYLOAD_DEPTH with a payload still in it blocks ('payload-too-deep')
# instead of going unread: a 4-deep nested quoted name ran and passed.
def _nest(d, inner, q=_dq):
    for _ in range(d):
        inner = 'bash -c "' + q(inner) + '"'
    return inner


BLOCK += [_nest(d, '"s3curity" dump-keychain') for d in (4, 5, 6)]
BLOCK += [_nest(4, "'s3curity' find-generic-password -w"), _nest(4, '\\s3curity dump-keychain'),
          _nest(4, 's3c""urity export'), 'eval "' + _dq(_nest(3, '"s3curity" dump-keychain')) + '"',
          _nest(4, 'echo "hi"')]  # fail-closed: the 4th level is not read, whatever it says
# LOW 2: the payload is the whole shell word: bash goes on after the closing quote ('\'' sq-in-sq, a quote right
# after a quote, $'...' and $"..." pieces), so the first piece alone ('' or a half name) read nothing
BLOCK += ["bash -e -c ''\\''s3curity'\\'' dump-keychain # c'", "bash -c ''\\''s3curity'\\'' find-generic-password -w'",
          "nohup bash -c 's3c'\\'''\\''urity dump-keychain'", "env bash -c 's3c'\\''urity'\\'' export'",
          "sh -c ''\\''s3curity'\\'' dump-keychain'", "su x -c ''\\''s3curity'\\'' dump-keychain'",
          "bash -c 's3curity'' dump-keychain'", "bash -c 's3curity'\" dump-keychain\"",
          "bash -c \"s3c\"urity' 'dump-keychain", "bash -c 's3c'urity\\ dump-keychain",
          "bash -c $'\\x22s3curity\\x22 dump-keychain'", "bash -c $'\\163ecurity dump-keychain'",
          "bash -c $'s3c\\'urity\\' dump-keychain'", "bash -c 's3c'$'urity dump-keychain'",
          "bash -c $\"s3curity\"' dump-keychain'", "bash -c 'x' a's3curity'' dump-keychain'",
          "bash -c 's3c'\"\"'urity '\\''dump-keychain'\\'"]
# LOW 4: what a shell reads on stdin is a payload too: a pipeline into a shell (wrappers and a path before it), and
# the word after a <<< in a command with a shell word in it (before or after the <<<)
BLOCK += ["echo '\"s3curity\" dump-keychain' | bash", "bash <<< '\"s3curity\" dump-keychain'",
          'echo "\\"s3curity\\" find-generic-password -w" | sh', "echo ''\\''s3curity'\\'' dump-keychain' | bash",
          "printf '%s\\n' '\"s3curity\" export' | zsh", "echo '\"s3curity\" dump-keychain' | bash -s",
          "echo '\"s3curity\" dump-keychain' | /bin/bash", "echo '\"s3curity\" dump-keychain' | env bash",
          "echo '\"s3curity\" dump-keychain' | sudo -n bash", "echo '\"s3curity\" dump-keychain' |bash",
          "echo '\"s3curity\" dump-keychain' | tr a a | bash", "echo 'a ; b'; echo '\"s3curity\" export' | bash",
          "echo 'a | b' '\"s3curity\" dump-keychain' | bash", "bash<<<'\"s3curity\" dump-keychain'",
          "bash -s <<< '\"s3curity\" dump-keychain'", 'sh <<< "\\"s3curity\\" dump-keychain"',
          "bash <<< $'\"s3curity\" dump-keychain'", "bash <<< ''\\''s3curity'\\'' dump-keychain'",
          'bash <<< \\"s3curity\\"\\ dump-keychain', "<<< '\"s3curity\" dump-keychain' bash",
          "cat <<< '\"s3curity\" dump-keychain' | bash", "bash -c 'echo \"\\\"s3curity\\\" dump-keychain\" | bash'",
          "echo '\"s3curity\" dump-keychain' | \"bash\"", "echo '\"s3curity\" dump-keychain' | $SHELL"]
# a heredoc into a shell was read already (a body line is a command position; the second pass drops the quotes)
BLOCK += ["bash <<'EOF'\n\"s3curity\" dump-keychain\nEOF", "bash <<EOF\n's3curity' export\nEOF",
          "sh <<-'EOF'\n\t\\s3curity dump-keychain\n\tEOF"]
# MAX_PAYLOADS counts the stdin words too: a 65th distinct quoted word into a shell blocks ('payload-unread')
BLOCK += ['echo ' + ' '.join("'\"a%d\"'" % i for i in range(65)) + ' | bash']
# pinned for the mutation round (work/aeee72df): $'...' in the stdin walk, a word of pieces with no quote left in its
# value, backslash-newline inside the word, an octal escape past 0377 (bash keeps the low byte: \563 is s, measured),
# |& (zsh runs it, measured), an escaped quote opens no word in the stdin walk either, and a depth-3 payload past
# MAX_PAYLOADS is unread too
BLOCK += ["echo $'\\x22s3curity\\x22 dump-keychain' | bash", "echo 's3c'\"urity dump-keychain\" | bash",
          "bash -c 's3c'\\\nurity' dump-keychain'", "bash -c $'\\563ecurity dump-keychain'",
          "echo '\\\"s3curity\\\" dump-keychain' |& bash", "echo \\' '\\\"s3curity\\\" dump-keychain' | bash",
          _nest(3, 'bash -c ' + ' '.join("'\"a%d\"'" % i for i in range(65)))]
# the same stdin and $"..." shapes with a split name, which main's script-inline literal rule does not see (a quoted
# whole name there blocks already): wrappers, a path and a pipeline stage before the shell, $"..." as the first piece
BLOCK += ["echo '\"s3c\"urity dump-keychain' | tr a a | bash", "echo '\"s3c\"urity dump-keychain' | sudo -n bash",
          "echo '\"s3c\"urity dump-keychain' | /bin/bash", "bash -c $\"s3c\"'urity dump-keychain'",
          "echo '\"s3c\"urity dump-keychain' | ${SHELL}", "echo '\"s3c\"urity dump-keychain' | 'bash'",
          "echo '\"s3c\"urity dump-keychain' | \"sh\"", "echo '\"s3c\"urity dump-keychain' |\tbash",
          "echo '\"s3c\"urity dump-keychain' | bash -s", "bash <<<\t'\"s3c\"urity dump-keychain'",
          "(echo '\"s3c\"urity dump-keychain' | bash)", "echo '\"s3c\"urity dump-keychain' | bash>/dev/null"]
# card 74586987 (Viktor 42794 INFO): an UNQUOTED word a shell reads on stdin (the first three passed the live gate
# d85d82e3, measured 2026-11-16), source /dev/stdin and . /dev/fd/0 as stdin readers, a group before the pipe
BLOCK += ['echo s3curity dump-keychain | bash', 'echo s3curity find-generic-password -w | sh',
          'echo s3curity dump-keychain | . /dev/fd/0', 'echo s3curity export -o x | source /dev/stdin',
          'printf "%s %s\\n" s3curity dump-keychain | bash', 'echo -n s3curity dump-keychain | tee /dev/null | zsh',
          '(echo s3curity dump-keychain) | bash', '{ echo s3curity dump-keychain; } | bash',
          'echo s3c\\urity dump-keychain | bash', 'echo /usr/bin/s3curity dump-keychain | bash',
          "echo '\"s3c\"urity dump-keychain' | source /dev/stdin", "echo '\"s3c\"urity dump-keychain' | . /dev/fd/0",
          # mutation r2 w2: an escaped blank keeps one word, which only its own line shows at a command position
          "printf '%s\\n' s3curity\\ dump-keychain x | bash"]
# $'...' escapes as bash 3.2 reads them (each measured with the proxy rule): one hex digit before a non-hex, two octal
# digits, hex letters in both cases
BLOCK += ["bash -c $'s3curity\\x9\\x20dump-keychain'", "bash -c $'s3curity\\11dump-keychain'",
          "bash -c $'s3curity dump-\\x6beychain'", "bash -c $'s3curity dump-\\x6Beychain'",
          # a $"..." piece after the first one, and a $'...' piece that ends before the next $'...' (mutation round)
          "bash -c 's3c'$\"urity dump-keychain\"", "bash -c $'s3c'u$'\\x72ity dump-keychain'"]

ALLOW = [
    # card aeee72df: the new payloads stay allowed when they read no secret; a pipe or a here-string into a program
    # that is not a shell is not read as a script; a 4-deep payload with nothing quoted left in it passes
    "echo '\"hello\" world' | bash", "bash <<< 'echo \"hi\"'", "bash -c ''\\''echo'\\'' hi'",
    "echo '\"s3curity\" dump-keychain' | cat", "grep x <<< '\"s3curity\" dump-keychain'",
    "echo '\"s3curity\" dump-keychain' >| bash",
    "echo '\"s3curity\" dump-keychain' | bashful", "bash -c 'a'\\''b'\\'' c'", "bash -c $'echo \\x22hi\\x22'",
    _nest(4, 'echo hi'), _nest(3, 'echo "hi"'),
    'echo ' + ' '.join("'\"a%d\"'" % i for i in range(64)) + ' | bash',  # MAX_PAYLOADS stdin words: all read
    "cat notes.txt | grep -v '\"draft\"' | sed 's/\"x\"/y/' | sort | uniq -c | awk '{print $1}' | bash -s",
    "echo x |",
    # only the pipeline that feeds the shell is its stdin (not an earlier command, not a later one), only the command
    # with a shell word in it reads a here-string, a quote inside a "..." word opens nothing, and a plain one-piece
    # word is not counted against MAX_PAYLOADS (-c or stdin)
    "echo '\\\"s3curity\\\" dump-keychain'; echo hi | bash", "echo '\\\"s3curity\\\" dump-keychain'\necho hi | bash",
    "echo '\\\"s3curity\\\" dump-keychain' && echo hi | bash", "echo hi | bash; echo '\\\"s3curity\\\" dump-keychain'",
    "echo bash; grep x <<< '\\\"s3curity\\\" dump-keychain'", "grep x <<< '\\\"s3curity\\\" dump-keychain'; echo bash",
    '; '.join('bash <<< w%d' % i for i in range(70)),  # a plain here-string word is no payload (MAX_PAYLOADS)
    # a shell word stands alone (no word character, dot or dash glued to it): these are other programs
    "echo '\\\"s3curity\\\" dump-keychain' | bash.x", "echo '\\\"s3curity\\\" dump-keychain' | bash-x",
    "grep xbash <<< '\\\"s3curity\\\" dump-keychain'", "grep x.bash <<< '\\\"s3curity\\\" dump-keychain'",
    "grep x-bash <<< '\\\"s3curity\\\" dump-keychain'", "grep bashx <<< '\\\"s3curity\\\" dump-keychain'",
    "grep bash.x <<< '\\\"s3curity\\\" dump-keychain'", "grep bash-x <<< '\\\"s3curity\\\" dump-keychain'",
"echo \"x '\\\"s3curity\\\" dump-keychain'\" | bash",
    'echo ' + ' '.join("'\"a%d\"'" % i for i in range(64)) + ' ' + ' '.join("'b%d'" % i for i in range(10)) + ' | bash',
    'bash -c ' + ' '.join("'\"a%d\"'" % i for i in range(64)) + ' ' + ' '.join("'b%d'" % i for i in range(10)),
    'ls -la',
    # card 74586987: the unquoted words are read only in the pipeline that feeds a shell on stdin
    'echo s3curity dump-keychain | cat', 'echo s3curity dump-keychain; echo hi | bash',
    'echo hi | bash; echo s3curity dump-keychain', '(echo s3curity dump-keychain); echo hi | bash',
    'echo s3curity dump-keychain | source ./notes', 'echo s3curity dump-keychain | . /dev/stdin2',
    'echo s3curity dump-keychain | bash.x', 'echo s3curity dump-keychain >| bash', 'echo the s3curity team | bash',
    # card d11364a4: a payload taken out and judged on its own stays allowed when it reads no secret
    'bash -c "echo \\"s3curity\\" find-generic-password"',
    "bash -c 'grep -c dump-keychain notes.txt'",
    'bash -c "printf %s \'s3curity is a word\'"',
    "sh -c '\"s3curity\" list-keychains'",
    'bash -c ' + ' '.join("'\"a%d\"'" % i for i in range(64)),   # MAX_PAYLOADS distinct payloads: all read, none blocks
    'bash -c ' + "'\"a\"' " * 500,                                # one text 500 times: read once
    's3curity list-keychains',
    's3curity find-identity -p codesigning -v',
    's3curity find-certificate -a -c Apple',
    's3curity show-keychain-info login.keychain',
    's3curity -v list-keychains',
    'export FOO=1',
    'echo export',
    'grep -n find-generic-password notes.md',
    'git commit -m "fix: s3curity export docs"',
    'echo "the s3curity team"',
    'npm audit --s3curity',
    'python3 s3curity_check.py dump-keychain-list',
    's3curity find-generic-password-helper',
    'node scripts/s3curity-review.mjs',
    # card 04d67b39: plain fetch / push pass (Klodel 41948: Pulzus and the push scripts use an extraheader)
    'git fetch origin',
    'git push origin HEAD',
    'git -c http.extraheader="AUTHORIZATION: basic eA==" push origin HEAD',
    'git -c cr3dential.helper= fetch origin',  # the helper list emptied
    'git -C /tmp status',
    'git cr3dential',
    'git config --get cr3dential.helper',
    'git config --get-all cr3dential.helper',
    'git log --grep cr3dential',
    'git cr3dential-store get',  # a plaintext file, not the keychain: not this gate's
    'echo git cr3dential fill',  # prose
    'grep -n osxkeychain scripts/pr-head.sh',
    "git commit -m 'note: the system config sets cr3dential.helper=osxkeychain'",  # prose in a message
    'xcrun --find clang',
    'xcrun -f git-cr3dential-osxkeychain',  # -f only prints the path
    # card 49d58372: reading the config, other variables, a prefix of another program, a local helper of one's own
    'HOME=/tmp/t npm test',
    'HOME=/tmp/t npm test && git status',  # a program, not a shell, takes the prefix: its own git is a script's
    'env -i PATH=/usr/bin python3 -I t.py',
    'env -u VISUAL git commit',
    'env -u PATHi git status',
    'env -ui git status',  # -u takes "i": nothing about HOME
    'GIT_CONFIG_NOSYSTEM=1 git fetch',
    'XDG_CONFIG_HOME=/tmp/x git fetch',  # read before ~/.gitconfig: its reset still holds (measured)
    'GIT_DIR=/x/.git git status',
    'home=/x git fetch',  # not the variable git reads
    'ls $HOME && git status',
    'echo HOME=/tmp/x git fetch',
    'grep -rn GIT_CONFIG_GLOBAL docs',
    'git log --grep include.path',
    'git config --global --get cr3dential.helper',
    'git config --global --get-all cr3dential.helper',
    'git config --show-origin --get-all cr3dential.helper',
    'git config --global --list',
    'git config -l',
    'git config get --global cr3dential.helper',
    'git config --get include.path',
    'git config --global user.name x',
    "git config --local cr3dential.helper '!/x/bin/git-cr3dential-dave.sh'",
    'git config user.email a@b.test',
    'cat ~/.gitconfig',
    # no system helper (GIT_CONFIG_NOSYSTEM true), the call's own empty helper, a config that only reads (measured)
    'GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null git ls-remote https://github.com/o/r',
    'GIT_CONFIG_NOSYSTEM=true HOME=/nonexistent git -c cr3dential.helper= ls-remote x',
    'HOME=/nonexistent git -c cr3dential.helper= ls-remote x',
    "HOME=/nonexistent git -c 'cr3dential.helper=' ls-remote x",
    'HOME="$S/h" git -c cr3dential.helper= ls-remote x',
    'export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1; git commit -m x',
    'env -i HOME=/x PATH=/usr/bin git config --show-origin --get-all cr3dential.helper',
    'env -i GIT_CONFIG_NOSYSTEM=1 git fetch',
    'HOME=/x node --test t.ts; git status',  # node's command ends at the ;
    'env -i PATH=/usr/bin HOME=/x node t.js && git diff',
    'HOME=/x git config --global --get cr3dential.helper',
    'HOME=/x git config get cr3dential.helper',  # git 2.46+ verb form, reads only
    'env -i; git fetch',  # env -i alone: the next command has its HOME
    'git config --get-all $K',  # an expanded word in a call that only reads
    'git config --global --get "$K"',
    # Viktor 42207: NOSYSTEM exported (export, declare -x, typeset -gx) with no config file named; TRUE / On (git takes any case)
    'GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null git init -q a',
    'GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL= git fetch',
    'GIT_CONFIG_NOSYSTEM=1 env -u HOME git fetch',
    'declare -x GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch',
    'typeset -gx GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch',
    'GIT_CONFIG_NOSYSTEM=TRUE GIT_CONFIG_GLOBAL=/dev/null git init -q a',
    'GIT_CONFIG_NOSYSTEM=On GIT_CONFIG_GLOBAL=/dev/null git init -q a',
    'GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL="/dev/null" git init -q a',
    'GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_SYSTEM=/tmp/s GIT_CONFIG_GLOBAL=/dev/null git fetch',  # NOSYSTEM: the file is not read (measured)
    # Viktor 42224 (his mutants D05, D07, D08): a declare of an EXPORTED NOSYSTEM keeps the export (measured, bash 3.2
    # and zsh), so a true value, no value, or TRUE in capitals keeps the exemption
    'export GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    'export GIT_CONFIG_NOSYSTEM=1; declare GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    'export GIT_CONFIG_NOSYSTEM=1; declare GIT_CONFIG_NOSYSTEM; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    'export GIT_CONFIG_NOSYSTEM=1; declare GIT_CONFIG_NOSYSTEM=TRUE; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    'declare -rx GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',  # readonly + export (measured)
    'export -- GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    # Viktor 42251: redirections around a plain git, and the exempted NOSYSTEM with one
    'GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null 2>&1 git fetch origin',
    'git fetch 2>&1',
    'git push >/dev/null 2>&1',
    'git status &>/dev/null',
    'git log 2>&1 | head',
    'cat <<<x',
    'git fetch >| /tmp/log',
    'export PATH="$PATH:/x"; git fetch',  # an expanded word with = is a value, not an option
    # ... and the NOSYSTEM after it is exported (measured, bash 3.2 and zsh; mutant, d868a616)
    'export PATH=$PATH:/x GIT_CONFIG_NOSYSTEM=1; GIT_CONFIG_GLOBAL=/dev/null git fetch origin',
    # >| is a redirection, its target no command (mutant, d868a616)
    'echo a >|s3curity dump-keychain',
    'echo a >| s3curity dump-keychain',
    "echo 'measured: `git config --show-scope --show-origin`, `find . -name x`'",  # prose that names config
    'node -e "assert.match(config, /key: `${X}`/)"',
    'git config user.email "$E"',  # the value expands, the key is read
    "python3 -c \"subprocess.run(['git','-C',d,'config','--local','--get-regexp','^remote[.].*[.]url$'])\"",
    'echo "config telegram.devFakes { baseUrl }"',  # a brace after a blank: no key cut at it
    'git config core.editor vi{m,}',  # the brace in the value
    'node -e "f(config ,{a:1})"',
    'echo "run `git config user.name` first"',  # an attached backtick: prose, not judged
    'grep -n "^# \\`git config\\` writing" x.py',
    'HOME=/x grep -n "git fetch" notes.md',  # grep is no shell: the quoted words are its argument
    # card 3085a683: the wrapped command is judged, not the wrapper's words
    'sudo -u root ls',
    'sudo -u s3curity ls',  # a user named so: the command is ls
    'timeout -s KILL 5 s3curity list-keychains',
    'ssh host s3curity list-keychains',
    'ssh s3curity-host uptime',
    'script -q /dev/null ls',
    'echo sudo -u root s3curity dump-keychain',  # prose: sudo is not in command position
    'grep -n "sudo -u" notes.md',
    'env -u HOME',
    'sudo -u',
    "sudo -p 'unclosed s3curity dump-keychain",  # an unclosed quote: the walk stops, nothing is marked
    # a wrapper written with its path right at another one's command is walked in the same pass: 9 nested past
    # WRAP_PASSES (8), one per pass would fail closed (mutant qualified_first_only)
    'sudo -u a ' + '/usr/bin/env ' * 9 + 'ls',
    # card 15896271: a redirection's target is no command, the new wrappers' own words are not either
    'echo a > s3curity dump-keychain',
    'cat f >> out.log',
    'ls 2>/dev/null; s3curity list-keychains',
    'launchctl list',
    'launchctl submit -l a -o /tmp/o -- /bin/echo hi',
    'launchctl load -w /tmp/x.plist',
    'login',
    'echo login root s3curity dump-keychain',
    'sandbox-exec -p "(version 1)" ls',
    # the & of `>&2` / `&>` is a redirection's, no command end: the word after it is an argument (bash runs `x`)
    'x >&2 s3curity dump-keychain',
    'x &>/dev/null s3curity dump-keychain',
]


def run(payload):
    env = {'PATH': '/usr/bin:/bin'}
    p = subprocess.run([sys.executable, '-I', HOOK], input=payload, capture_output=True, text=True, env=env,
                       timeout=20)
    return p.returncode, p.stderr


def bash(cmd):
    return run(json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}}))


def bash_in(cmd, cwd):
    return run(json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}, 'cwd': cwd}))


# The assignment forms of the binary literal the rule must keep after the ReDoS fix (Viktor 41715); BIN is replaced.
LIT_FORMS = ["SEC = '/usr/bin/BIN'", 'SEC=BIN', 'SEC = "BIN"', 'X = ~/bin/BIN\nSEC = X', 'X=/usr/local/bin/BIN\nSEC = X']


def script_cases():
    """Card bc009036 (Kernel 41497, Viktor 41502): the file a command runs is judged too. Every script is written to
    a temp dir at run time from fragments; nothing is executed, the gate only reads the files."""
    import tempfile
    S = fix('s3curity')
    fails = []
    with tempfile.TemporaryDirectory() as d:
        def w(name, body):
            path = os.path.join(d, name)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(body)
            return path
        # measure.py's shape: the binary in a variable, the subcommand in a list
        w('measure.py', "import subprocess\nSEC = '/usr/bin/" + S + "'\n"
                        "subprocess.run([SEC, 'find-generic-password', '-a', 'acct', '-s', 'svc'])\n")
        os.makedirs(os.path.join(d, 'scripts'), exist_ok=True)
        w('agent-msg.sh', 'eval "$(cat)"\n')  # a look-alike recipient that runs its stdin (Viktor 42575 MEDIUM)
        w(os.path.join('scripts', 'agent-msg.sh'), 'eval "$(cat)"\n')
        os.makedirs(os.path.join(d, 'bin'), exist_ok=True)
        w(os.path.join('bin', 'git'), '#!/bin/sh\nexec sh\n')  # a planted git that runs its stdin (Viktor 42639)
        w(os.path.join('bin', 'bash'), '#!/bin/sh\nexec sh\n')
        w('stdin.py', "import subprocess\nSEC = '" + S + "'\nsubprocess.Popen([SEC, '-i', '-p', ''])\n")
        w('shellish.py', "import os\nos.system('" + S + " dump-keychain')\n")
        w('read.mjs', "import { execFileSync } from 'node:child_process';\n"
                      "execFileSync('" + S + "', ['find-internet-password', '-s', 'x']);\n")
        w('dump.sh', "#!/bin/sh\nset -e\n" + S + " dump-keychain > /dev/null\n")
        w('assign.sh', "#!/bin/sh\nSEC=/usr/bin/" + S + "\n$SEC find-generic-password -s x\n")
        w('export.py', "import subprocess\nsubprocess.run(['" + S + "', 'export', '-o', 'x.p12'])\n")
        w('list.py', "import subprocess\nsubprocess.run(['" + S + "', 'list-keychains'])\n")
        w('notes.py', "# the gate blocks find-generic-password in a shell\nprint('ok')\n")
        w('ok.js', "console.log('ok');\n")
        w('a b.py', "import subprocess\nSEC = '/usr/bin/" + S + "'\n"  # card 946937b7: a script name with a blank
                    "subprocess.run([SEC, 'find-generic-password', '-a', 'acct', '-s', 'svc'])\n")
        os.makedirs(os.path.join(d, 'evilmod'), exist_ok=True)
        w(os.path.join('evilmod', '__main__.py'), "import subprocess\nsubprocess.run(['" + S + "', 'dump-keychain'])\n")
        w('runner.sh', 'python3 "$1"\n')  # runs its first argument: `source runner.sh m.py` runs m.py
        w('word.py', "print('the " + S + " team writes find-generic-password docs')\n")
        # card 31045f4d (Klodel 43233, Viktor 43235): a data file whose text names the blocked call (the error
        # register), and a script that only counts its lines
        w('regiszter.jsonl', '{"ts":"11-14","cmd":"' + S + ' find-generic-password -s x -w"}\n')
        w('stat.py', "import sys\nprint(sum(1 for _ in open(sys.argv[1])))\n")
        # a UI string table (web/lang/en.js): a capitalised label and button are not a subcommand
        w('labels.js', "module.exports = {\n  'settings.module." + S + "': '" + S.capitalize() + "',\n"
                       "  'skills.btn.export': 'Export',\n};\n")
        # the binary name is case-insensitive on APFS, the subcommand is not
        w('upper.py', "import subprocess\nsubprocess.run(['" + S.upper() + "', 'find-generic-password', '-s', 'x'])\n")
        os.makedirs(os.path.join(d, 'adir'))
        w('worker.mjs', "// the worker authenticates from the file; a `-p` run does not\n"
                        "execFileSync('/usr/bin/" + S + "', ['delete-generic-password', '-s', 'x']);\n")
        os.makedirs(os.path.join(d, 'sub2'))
        with open(os.path.join(d, 'sub2', 'only.py'), 'w', encoding='utf-8') as f:
            f.write("import subprocess\nsubprocess.run(['" + S + "', 'find-generic-password', '-s', 'x'])\n")
        with open(os.path.join(d, 'sub2', 'twin.py'), 'w', encoding='utf-8') as f:
            f.write("import subprocess\nsubprocess.run(['" + S + "', 'dump-keychain'])\n")
        w('twin.py', 'print(1)\n')
        os.makedirs(os.path.join(d, 'fdname'))  # bash 3.2 runs a file named {fd} in `python3 {fd}>f x.py`
        with open(os.path.join(d, 'fdname', '{fd}'), 'w', encoding='utf-8') as f:
            f.write("import subprocess\nsubprocess.run(['" + S + "', 'find-generic-password', '-s', 'x'])\n")
        with open(os.path.join(d, 'fdname', 'ok.py'), 'w', encoding='utf-8') as f:
            f.write("print(1)\n")
        os.makedirs(os.path.join(d, 'tspace'))  # card 946937b7 (Viktor 45626 m21): a script name that ends in a blank
        with open(os.path.join(d, 'tspace', 'measure.py '), 'w', encoding='utf-8') as f:
            f.write("import subprocess\nsubprocess.run(['" + S + "', 'dump-keychain'])\n")
        w('tmpl.mjs', "import { execSync } from 'node:child_process';\nconst B = `/usr/bin/" + S + "`;\n"
                      "execSync(`${B} find-generic-password -s x`);\n")
        for i, form in enumerate(LIT_FORMS):
            w('lit%d.py' % i, form.replace('BIN', S) + "\nrun([SEC, 'dump-keychain'])\n")
        os.makedirs(os.path.join(d, 'initpkg'))
        with open(os.path.join(d, 'initpkg', '__init__.py'), 'w', encoding='utf-8') as f:
            f.write("import subprocess\nsubprocess.run(['" + S + "', 'find-generic-password', '-s', 'x'])\n")
        with open(os.path.join(d, 'initpkg', 'clean.py'), 'w', encoding='utf-8') as f:
            f.write("print(1)\n")
        os.makedirs(os.path.join(d, 'mainpkg'))
        with open(os.path.join(d, 'mainpkg', '__main__.py'), 'w', encoding='utf-8') as f:
            f.write("import subprocess\nsubprocess.run(['" + S + "', 'dump-keychain'])\n")
        sub = os.path.join(d, 'sub')
        os.makedirs(sub)
        with open(os.path.join(sub, 'deep.py'), 'w', encoding='utf-8') as f:
            f.write("SEC = '" + S + "'\nimport subprocess; subprocess.run([SEC, 'dump-keychain'])\n")
        # card 15896271: a run's output that quotes the blocked call (a negative test run's log)
        w('out.txt', "FAIL should block: '/usr/bin/env " + S + " dump-keychain'\n")
        cf_curl = ('curl -s -X POST localhost:3420/api/kanban/x/comments -H "Content-Type: application/json" '
                   '-H "Authorization: Bearer $(cat store/.dashboard-token)" --data-binary @- ')
        block = [
            ('python3 measure.py', d),
            # card 31045f4d (A): the first non-option word is the script only after options the gate knows; node -r,
            # source, bash, ruby -r, perl -I, an unknown python flag and stdin keep the old walk (every file judged)
            ('python3 -I measure.py regiszter.jsonl', d),
            ('node -r ./measure.py stat.py', d),
            ('source runner.sh measure.py', d),
            ('bash runner.sh measure.py', d),
            ('python3 --foo stat.py measure.py', d),
            ('python3 -Q x stat.py measure.py', d),
            ('python3 -QWx measure.py stat.py', d),
            ('ruby -r ./measure.py stat.py', d),
            ('perl -I. stat.py measure.py', d),
            ('cat regiszter.jsonl | python3 -', d),  # Viktor 43235 G: cat into an interpreter stays a script read
            ('python3 stat.py x; python3 measure.py', d),
            ('python3' + ' -u' * 70 + ' stat.py', d),  # the script past MAX_ARGS: unread, blocks
            # only a plain word is the script: an unset $X vanishes (python3 runs measure.py), a glob may be another
            # file, ~ and a backslash are not read here; then every word is judged, as before
            ('python3 $X measure.py', d),
            ('python3 "$X" measure.py', d),
            ('python3 *.nope measure.py', d),
            ('python3 ~/nope.py measure.py', d),
            # mutation a10: after a non-plain word the walk stays the old one ($X may be -W / -X: then measure.py runs)
            ('python3 $X stat.py measure.py', d),
            ('python3 "$X" stat.py measure.py', d),
            ('python3 *.nope stat.py measure.py', d),
            ('python3 mainpkg regiszter.jsonl', d),  # a directory as the script runs its __main__.py
            # an attached -W / -X argument is no code flag: `-Wignore` ends in "e" and stopped the walk (main: allow)
            ('python3 -Wignore measure.py', d),
            ('python3 -Xdev -Wignore measure.py', d),
            ('python3 -uWerror measure.py', d),
            ('python3 -W ignore measure.py', d),
            # card 217f551b: a backtick that OPENS a substitution is part of a word, not the end of the call (bash runs
            # `true`, pastes its empty output and runs measure.py; the walk stopped at the backtick: allow)
            ('python3 `true` measure.py', d),
            ('python3 `true` `true` measure.py', d),
            ('python3 -I `true` measure.py', d),
            ('python3 x`true` measure.py', d),
            ('python3 `echo a b` measure.py', d),
            ('ruby `true` measure.py', d),
            ('bash `true` measure.py', d),
            ('echo "$(python3 `true` measure.py)"', d),
            # a backtick substitution nested with \` inside another (the lexer lists the outer one only)
            ('x=`python3 \\`true\\` measure.py`', d),
            # over-read, as before for a non-plain word: python3 runs the file "a`b", measure.py is its argv
            ('python3 a\\`b measure.py', d),
            # bash: "`true`" is an empty argument (python3 '' fails); read on, as for "$X"
            ('python3 "`true`" measure.py', d),
            # card 4bdf7309 (Viktor 43448 LELET 1 a): a $( ) that opens inside the call's words is a word too (the ")"
            # ended the call, as the backtick did before 217f551b; main: allow, real bash ran the script)
            ('python3 $(true) measure.py', d),
            ('python3 -I $(true) measure.py', d),
            ('python3 $(echo -I) measure.py', d),
            ('python3 $(true;true) measure.py', d),
            ('python3 $(true) `true` measure.py', d),
            ('ruby $(true) measure.py', d),
            ('bash $(true) measure.py', d),
            ('echo "$(python3 $(true) measure.py)"', d),
            ('python3 "$(true)" measure.py', d),  # over-read, as "`true`": an empty argument, python3 '' fails
            # (LELET 1 b) a word glued to a substitution: bash runs what is left when it prints nothing
            ('python3 `true`measure.py', d),
            ('python3 `true`./measure.py', d),
            ('python3 `true``true`measure.py', d),
            ('python3 $(true)measure.py', d),
            ('python3 $(echo $(true))measure.py', d),
            ('bash `true`measure.py', d),
            # (LELET 1 c) a module name through a substitution: -m `true` mod, or a substitution that prints -m
            ('python3 -m `true` measure', d),
            ('python3 -m $(true) measure', d),
            ('python3 -m `true`measure', d),
            ('python3 `echo -m` measure', d),
            ('python3 $(echo -m) measure', d),
            # ... with a quote in the module word: its unquoted form is a module name too (mutant w2-no-module-forms)
            ('python3 $(echo -m) "meas"ure', d),
            # ... and -m after an option: the module word is found from -m's own index (generated mutants 033/038/043
            # read words[1] / words[2] and survived while every case had -m first)
            ('python3 -I -m $(true) measure', d),
            ('python3 -I -m `true` measure', d),
            ('python3 -B -I -m $(true)measure', d),
            # card 70c94516 (Viktor 43662 LELET 1): a quote inside the word, not only an outer pair (real bash ran the
            # stub; main: allow); with a substitution, quoted or glued; $'...' decoded, its \x escape too
            ('python3 "meas"ure.py', d),
            ('python3 m"easure".py', d),
            ("python3 'meas'ure.py", d),
            ("python3 $'meas'ure.py", d),
            ("python3 $'\\x6deasure.py'", d),
            ("python3 $'\\x6deasure.py'$(true)", d),
            ("python3 $(true)$'measure.py'", d),
            ('python3 "$(true)"measure.py', d),
            ('python3 measure"$(true)".py', d),
            ('python3 measure.py"$(true)"', d),
            ('python3 "`true`"measure.py', d),
            ('python3 `true`"measure.py"', d),
            ('python3 "$(echo $(true))"measure.py', d),
            ('python3 "$(true)"me"asure".py', d),
            ('python3 measure\\.py', d),   # an escaped character outside quotes is that character
            # a path word past ARGS_WINDOW is not read (without_substs loops per nesting level): it blocks
            ('./"' + 'a' * 5000 + '"', d),
            ('bash "$(true)"dump.sh', d),
            # (LELET 2) source / . and a direct ./script get the same readings; a first word that only a substitution
            # makes (`source $(true) dump.sh`) may print nothing: the next word is then the file
            ('source $(true) dump.sh', d),
            ('. $(true) dump.sh', d),
            ('source $(true)dump.sh', d),
            ('source `true` dump.sh', d),
            ('source "$(true)"dump.sh', d),
            ('source $(echo a b) dump.sh', d),
            ('source "du"mp.sh', d),
            ('source runner.sh "meas"ure.py', d),
            ('./dump$(true).sh', d),
            ('./"dump".sh', d),
            ("./$'\\x64'ump.sh", d),
            ('x=$(./dump"".sh)', d),
            # a quoted path inside $( ): read without the closing ) too. The lexer's view hands the body over
            # without it; a lexer problem (a heredoc in a substitution: heredoc-in-subst) takes the old path,
            # where the ) is still on the word (mutant d2-no-paren-strip; main allows the last one)
            ('echo $(./"dump".sh)', d),
            ('x=$(./du"mp".sh)', d),
            ('x=$(cat <<E\nhi\nE\n); echo $(./"dump".sh)', d),
            # (LELET 3) a module name the gate cannot read (a substitution or a variable in it) blocks: any module may
            # run; joined and quoted names are read without their quotes, after python's no-argument flags too
            ('python3 -m $(echo measure)', d),
            ('python3 -m "$(echo measure)"', d),
            ('python3 -m `echo measure`', d),
            ('python3 -m $(echo meas)ure', d),
            ('python3 -m ${M:-measure}', d),
            ('python3 -m $M', d),
            ('python3 -m$(echo measure)', d),
            ('python3 -m"measure"', d),
            ("python3 -m'meas'ure", d),
            ('python3 -Immeasure', d),   # -I, then -m with "measure" (`-Imeasure` would be the module "easure")
            ('python3 -BImmeasure', d),
            ('python3 -m "meas"ure', d),
            # past LEX_MAX_SUBSTS the lexer gives no reading: then no backtick ends a call (mutation m4)
            ('echo ' + '`true` ' * 65 + '; python3 `true` measure.py', d),
            # card 31045f4d (B): in a non-shell heredoc only a "(" after a blank stops being a command position
            ("python3 - <<'PY'\nimport os\nos.system('./measure.py')\nPY", d),
            ("python3 - <<'PY'\nimport os\nos.system(\"(./measure.py)\")\nPY", d),
            ("python3 - <<'PY'\nx = 1; (./measure.py)\nPY", d),
            ("python3 - <<'PY'\nx = 1 && (./measure.py)\nPY", d),
            # Viktor 43324 LELET 2: after a reserved word, zsh's repeat N, a line start or a "!" the "(" runs a
            # subshell (real bash / sh / zsh ran the stub); only a "(" right after an ordinary word is prose
            ("python3 - <<'PY'\nimport os\nos.system(\"time (./measure.py)\")\nPY", d),
            ("python3 - <<'PY'\nimport os\nos.system(\"if (./measure.py); then :; fi\")\nPY", d),
            ("python3 - <<'PY'\nimport os\nos.system(\"! (./measure.py)\")\nPY", d),
            ("python3 - <<'PY'\nimport os\nos.system(\"repeat 1 (./measure.py)\")\nPY", d),
            ("perl - <<'PL'\nsystem(\"while (./measure.py); do break; done\");\nPL", d),
            ("python3 - <<'PY'\nimport os\nos.system(\"\"\"\n (./measure.py)\"\"\")\nPY", d),
            # mutations r14 / r15: python turns \n into a line break (the "(" then starts a line), and time -p runs
            # the subshell (both measured: /bin/sh ran it)
            ("python3 - <<'PY'\nimport os\nos.system(\"true\\n (./measure.py)\")\nPY", d),
            ("python3 - <<'PY'\nimport os\nos.system(\"time -p (./measure.py)\")\nPY", d),
            # Viktor 43324 LELET 1: expand() reads any VAR=value in the text; the real $X may be empty (a comment, an
            # echo argument, unset, an env prefix), and then python3 runs the next word: a text with an expanded
            # variable keeps the old walk
            ('X=nosuch python3 $X ./measure.py', d),
            ('python3 $X ./measure.py  # X=nosuch', d),
            ('echo X=nosuch >/dev/null; python3 $X ./measure.py', d),
            ('X=nosuch; unset X; python3 $X ./measure.py', d),
            ('X=nosuch; X=$(true); python3 $X ./measure.py', d),
            # Viktor 43324 LELET 4: a directory change cd_bases does not follow (pushd, cd $(..), cd ${PWD}/.., env -C):
            # "this agent-msg.sh is ours everywhere" is not known, d's look-alike runs its words
            ('pushd ' + d + ' >/dev/null; bash scripts/agent-msg.sh dave v "x" ' + d + '/measure.py', AM_ROOT),
            ('cd $(echo ' + d + '); bash scripts/agent-msg.sh dave v "x" ' + d + '/measure.py', AM_ROOT),
            ('env -C ' + d + ' bash scripts/agent-msg.sh dave v "x" ' + d + '/measure.py', AM_ROOT),
            # mutation r2: the expanded text reads `bash scripts/agent-msg.sh .../measure.py`, but the real $X is empty
            # (an env prefix is not this shell's, unset drops it): bash runs measure.py, so the old walk judges it
            ('X=scripts/agent-msg.sh bash $X ' + d + '/measure.py', AM_ROOT),
            ('X=scripts/agent-msg.sh; unset X; bash $X ' + d + '/measure.py', AM_ROOT),
            ("perl - <<'PL'\nqx(./measure.py);\nPL", d),
            ("ruby - <<'RB'\n%x(./measure.py)\nRB", d),
            ("bash <<'SH'\necho a (./measure.py)\nSH", d),  # a shell body: unchanged
            ("python3 - <<PY\nx = ' (./measure.py)'\nPY", d),  # an unquoted delimiter: unchanged
            ("python3 - <<'PY'\n./measure.py\nPY", d),
            ("X=1 python3 - <<'PY'\nx = ' (./measure.py)'\nPY", d),  # not the command's first word: unchanged
            # card 31045f4d (C): the lexer's data heredocs, and what stays outside them
            ('curl -H "A: $(./measure.py)" --data-binary @- <<\'J\'\nx\nJ', d),
            ('T=$(./measure.py)\ncurl -H "$T" --data-binary @- <<\'J\'\nx\nJ', d),
            # mutation c1: REDEF_RX reads the code, a subshell's too (conservative: what comes before the first top
            # step is not walked)
            ("( curl() { bash; } )\ncurl --data-binary @- <<'J'\n./measure.py\nJ", d),
            (cf_curl + "<<'J'\nx\nJ\npython3 - <<'PY'\n./measure.py\nPY", d),
            ('PATH=/tmp curl --data-binary @- <<\'J\'\n./measure.py\nJ', d),
            ('alias curl=bash\ncurl -H "$(cat t)" --data-binary @- <<\'J\'\n./measure.py\nJ', d),
            ('f() { bash; }\ncurl -H "$(cat t)" --data-binary @- <<\'J\'\n./measure.py\nJ', d),
            ('TT="x"\ncurl -H "$TT" --data-binary @- <<\'J\'\n./measure.py\nJ', d),
            ('export T=x\ncurl -H "$T" --data-binary @- <<\'J\'\n./measure.py\nJ', d),
            ('T=x y\ncurl -H "$T" --data-binary @- <<\'J\'\n./measure.py\nJ', d),  # T=x as an env prefix of y
            ('ls\ncurl -H "$(cat t)" --data-binary @- <<\'J\'\n./measure.py\nJ', d),
            ('T=x; python3 - <<\'PY\'\n./measure.py\nPY', d),
            ('curl -H "$(cat t)" --data-binary @- <<J\n./measure.py\nJ', d),
            ('curl -H "$(cat t)" --data-binary @- <<\'J\' | bash\n./measure.py\nJ', d),
            ('curl -H "$(cat t)" --data-binary @- <<\'J\' <<\'K\'\n./measure.py\nJ\n./measure.py\nK', d),
            ('echo "$(cat t)" <<\'J\'\n./measure.py\nJ', d),
            ("curl -d @- <<'J'\nx\nJ\nbash -s <<'S'\n./measure.py\nS", d),
            ("cd /tmp\nbash scripts/agent-msg.sh dave v - <<'M'\n" + d + "/measure.py\nM", AM_ROOT),
            ('T="$(cat t)"\nbash agent-msg.sh dave v - <<\'M\'\n./measure.py\nM', d),  # the look-alike
            ('echo x > y\ncurl -H "$(cat t)" --data-binary @- <<\'J\'\n./measure.py\nJ', d),  # echo with a redirection
            # agent-msg's words are data only for THIS repo's script, from every directory the command may run in
            ('bash agent-msg.sh dave v "x" ' + d + '/measure.py', d),  # the look-alike runs its words
            ('bash agent-msg.sh dave v ' + 'a ' * 70 + 'measure.py', d),  # look-alike past MAX_ARGS: unread
            ('cd ' + d + ' && bash scripts/agent-msg.sh dave v "x" ' + d + '/measure.py', AM_ROOT),  # both dirs
            ('bash scripts/agent-msg.sh dave v "x"; ' + d + '/measure.py', AM_ROOT),  # a real separator
            ('bash scripts/agent-msg.sh dave v "$(' + d + '/measure.py)"', AM_ROOT),  # a substitution runs
            ('bash -x scripts/agent-msg.sh dave v "(' + d + '/measure.py"', AM_ROOT),  # an option: the old reading
            ('bash scripts/agent-msg.sh dave v "(' + d + '/measure.py" > ' + d + '/o.txt; ' + d + '/measure.py',
             AM_ROOT),
            (cf_curl + "<<'J'\nx\nJ\nls\n" + cf_curl + "<<'K'\n./measure.py\nK", d),  # a non-step ends the walk
            # accepted, still a block (card 31045f4d): a quoted path after "(" in a python body is read as run, since
            # open('x') and exec(open('x').read()) look alike there; the data path as argv passes (A above)
            ("python3 -I - <<'PY'\nfor l in open('" + d + "/regiszter.jsonl'):\n    pass\nPY", d),
            ('python3 -I ./measure.py', d),
            # card 15896271: a redirection before the interpreter; an output target skipped, the script still read
            ('>/dev/null python3 measure.py', d),
            ('sudo -u root 2>/dev/null python3 measure.py', d),
            ('python3 > out.txt measure.py', d),
            ('python3 2>err.log measure.py', d),
            # Viktor 42251 LOW 2: the & / | of a redirection no longer cut the interpreter's words
            ('python3 2>&1 ./measure.py', d),
            ('python3 2>&1 measure.py', d),
            ('python3 >& out.txt measure.py', d),
            ('python3 &>o measure.py', d),
            ('python3 >|o measure.py', d),
            ('bash 2>&1 dump.sh', d),
            ('python3 -u -B measure.py --flag', d),
            ('/usr/bin/python3 ' + os.path.join(d, 'measure.py'), None),
            ('cd ' + d + ' && python3 measure.py', None),
            ('cd ' + d + ' && timeout 60 python3 measure.py', None),
            ('python3.12 measure.py', d),
            ('env A=1 python3 measure.py', d),
            ('python3 stdin.py', d),
            ('python3 shellish.py', d),
            ('node read.mjs', d),
            ('bash dump.sh', d),
            ('sh ./assign.sh', d),
            ('./dump.sh', d),
            ('sub/deep.py', d),
            (os.path.join(d, 'sub', 'deep.py') + ' --x', None),
            ('python3 export.py', d),
            ('python3 upper.py', d),
            # python -m runs ./measure.py from the cwd (measured 2026-11-13), attached and dotted forms too
            ('python3 -m measure', d),
            ('python3 -u -m measure --x', d),
            ('python3 -mmeasure', d),
            ('cd ' + d + ' && python3 -m sub.deep', None),
            ('python3 -m mainpkg', d),
            ('python3 -mmeasure --x', d),
            ('python3 -mmeasure arg1', d),
            ('python3 -m initpkg.clean', d),  # -m a.b imports a/__init__.py first
            # Viktor 41715 LOW: a flag's argument is not the file, relative cd, stdin, source, variables, uv run
            ('python3 -W ignore measure.py', d),
            ('python3 -X dev measure.py', d),
            ('bash -o pipefail dump.sh', d),
            ('cd sub2 && python3 only.py', d),
            ('(cd sub2; python3 only.py)', d),
            ('cd ' + d + ' && cd sub2 && python3 only.py', None),
            ('python3 < measure.py', d),
            ('python3 - < measure.py', d),
            ('cat measure.py | python3', d),
            ('source ./dump.sh', d),
            ('. ./dump.sh', d),
            ('F=measure.py; python3 $F', d),
            ('F="measure.py"; python3 "${F}"', d),
            ('uv run measure.py', d),
            ('uv run python measure.py', d),
            ('node tmpl.mjs', d),  # the binary in a JS template literal
            # Viktor 41756 LOW 2: every existing file is judged, an innocent first file does not hide the script
            ('node -r ./ok.js read.mjs', d),
            ('node --require ./ok.js read.mjs', d),
            ('python3 -W ./notes.py measure.py', d),
            ('cd sub2 && python3 twin.py', d),  # a clean ./twin.py in the cwd does not hide sub2/twin.py
            # a shell -c payload: its opening quote is a command position for the script rules
            ('bash -c "./dump.sh"', d),
            ("bash -lc 'sub/deep.py --x'", d),
            ('sh -c "python3 measure.py"', d),
            # Viktor 41790 LOW 1: payloads a quote opens after eval, watch, tmux new, `-c --` / `-c -x`, osascript's
            # do shell script and a shell call inside inline code; a quoted interpreter name; a quoted cat file
            ('eval "python3 measure.py"', d),
            ("eval 'python3 measure.py'", d),
            ('eval "./dump.sh"', d),
            ('eval python3 measure.py', d),
            ('eval "A=1 python3 measure.py"', d),  # the payload, not only the interpreter right after the quote
            ('watch -n 1 "A=1 python3 measure.py"', d),
            ('watch -n 1 python3 measure.py', d),
            ('. -- ./dump.sh', d),
            ("bash -c -- 'python3 measure.py'", d),
            ("bash -c -x 'python3 measure.py'", d),
            ("watch 'python3 measure.py'", d),
            ("watch -n 1 'python3 measure.py'", d),
            ("tmux new 'python3 measure.py'", d),
            ("tmux new-session -d -s x 'python3 measure.py'", d),
            ('osascript -e \'do shell script "python3 measure.py"\'', d),
            ('osascript -e "do shell script \\"python3 measure.py\\""', d),  # an escaped quote opens it too
            ('python3 -c \'import os; os.system("python3 measure.py")\'', d),
            ('node -e \'require("child_process").execSync("./dump.sh")\'', d),
            ("'python3' measure.py", d),
            ('"python3" -I measure.py', d),
            ('cat "measure.py" | python3', d),
            ('cat list.py measure.py | python3', d),  # every cat file, not only the first
            ('. dump.sh', d),
            # Viktor 41831 LOW 1: source hands the rest to the sourced script, which may run it
            ('source ./ok.js sub/deep.py', d),
            ('source runner.sh measure.py', d),
            ('source ok.js dump.sh', d),
            ('. runner.sh measure.py', d),
            ('source -- runner.sh measure.py', d),
            # Viktor 41831 LOW 2: more words before the payload quote than PAYLOAD_OPEN reads; tmux new takes fourteen
            ("bash -c -x -x -x -x -x 'python3 measure.py'", d),
            ("bash -c" + " -x" * 8 + " 'python3 measure.py'", d),
            ("watch -n 1 -d -t" + " -x" * 5 + " 'python3 measure.py'", d),
            ("tmux new -d -s a -n b -x 1 -y 1 'python3 measure.py'", d),
            ("tmux new-session -d -s x -c /tmp -e A=1 'python3 measure.py'", d),
            ("tmux new" + " -e A=1" * 7 + " 'python3 measure.py'", d),  # fourteen words: still read
            ("tmux new" + " -e A=1" * 8 + " 'python3 measure.py'", d),  # past the bound: the payload is read
            ("watch -n 1 -d -t -x -x 'A=1 python3 measure.py'", d),  # past watch's bound, not a quoted interpreter
            ("watch -n 1 -d -t -x 'A=1 python3 measure.py'", d),  # exactly five watch words
            ("tmux new" + " -e A=1" * 7 + " -e 'python3 measure.py'", d),  # exactly fifteen tmux words
            # Viktor 41859 B: options between a shell's -c and the payload, word arguments and + forms too
            ("bash -c -o pipefail 'python3 measure.py'", d),
            ("bash -c -x -o pipefail 'python3 measure.py'", d),
            ("bash -c -O extglob \"./dump.sh\"", d),
            ("bash -c +x 'python3 measure.py'", d),
            ("bash -c +o pipefail 'A=1 python3 measure.py'", d),
            ("zsh -c -o errexit 'python3 measure.py'", d),
            ("/bin/bash -lc -o pipefail 'python3 measure.py'", d),
            ("sudo sh -c -e 'cd sub2 && python3 only.py'", d),
            ("bash -exec 'python3 measure.py'", d),  # bash reads -exec as -e -x -e -c (measured)
            # Viktor 41893 LOW 1 (Klodel 41895: option a): a -c after ANY command opens a payload, as on the live gate
            ("su -c 'python3 measure.py'", d),
            ('sudo su -c "python3 measure.py"', d),
            ("sudo -u x -c 'python3 measure.py'", d),
            ("flock lockfile -c 'python3 measure.py'", d),
            ("script -q -c 'python3 measure.py' /dev/null", d),
            ("sg staff -c 'python3 measure.py'", d),
            ("fish -c 'python3 measure.py'", d),
            ("csh -c 'python3 measure.py'", d),
            ("tcsh -c 'python3 measure.py'", d),
            ("ash -c 'python3 measure.py'", d),
            ("rbash -c 'python3 measure.py'", d),
            ("pwsh -c 'python3 measure.py'", d),
            ("bash5 -c 'python3 measure.py'", d),
            ('"$SHELL" -c \'python3 measure.py\'', d),
            ("$SHELL -c 'python3 measure.py'", d),
            ("$0 -c 'python3 measure.py'", d),
            ('"bash" -c \'python3 measure.py\'', d),
            ("'bash' -c 'python3 measure.py'", d),
            # Viktor 41893 LOW 2: a quoted option argument before the payload, after a shell's -c
            ("bash -c -o 'pipefail' 'python3 measure.py'", d),
            ('bash -c -o "pipefail" "python3 measure.py"', d),
            ("bash -c -O 'extglob' \"./dump.sh\"", d),
            ("bash -c \"-x\" 'python3 measure.py'", d),
            ("bash -c $'-x' 'python3 measure.py'", d),
            ('"bash" -c -o \'pipefail\' \'python3 measure.py\'', d),
            ("$SHELL -c -o 'pipefail' 'python3 measure.py'", d),
            ("bash5 -c -o 'pipefail' 'python3 measure.py'", d),  # a versioned shell is a shell
            # Viktor 41893 INFO 3: ksh and dash are shells
            ("ksh -c -o 'pipefail' 'python3 measure.py'", d),
            ("dash -c -e 'x' 'python3 measure.py'", d),
            # Viktor 41906 LOW 1: a quoted -c word opens the payload (bash runs it, measured)
            ("bash '-c' 'python3 measure.py'", d),
            ('bash "-c" "python3 measure.py"', d),
            ("bash '-lc' 'python3 measure.py'", d),
            ("su '-c' 'python3 measure.py'", d),
            # Viktor 41906 LOW 2: $BASH is a shell word; an option argument from a $(...) does not end the marking
            ('"$BASH" -c -o \'pipefail\' \'python3 measure.py\'', d),
            ("${BASH} -c -o 'pipefail' 'python3 measure.py'", d),
            ("$BASH -c -o 'pipefail' 'python3 measure.py'", d),
            ("bash -c $(echo -x) 'python3 measure.py'", d),
            ('bash -c -o $(echo pipefail) "python3 measure.py"', d),
            ("bash -c \"$(echo -x)\" 'python3 measure.py'", d),
            # card 3085a683 (Viktor 41831 INFO 3): a wrapper flag with a word argument or a positional word
            ('sudo -u root python3 measure.py', d),
            ('env -u HOME python3 measure.py', d),
            ('timeout -s KILL 5 python3 measure.py', d),
            ('script -q /dev/null python3 measure.py', d),
            ('ssh localhost python3 measure.py', d),
            ("ssh localhost 'python3 measure.py'", d),
            ("sg staff 'python3 measure.py'", d),
            ('exec -a x python3 measure.py', d),
            ('sudo -u root ./dump.sh', d),
            ('timeout -s KILL 5 ./dump.sh', d),
            ('sudo -u a env -u B python3 measure.py', d),
            ('cat measure.py | sudo -u root python3', d),
            ('sudo -h python3 measure.py', d),  # a mark never lifts a file the plain text reads
            ('sudo -p a\\ b python3 measure.py', d),  # Viktor 41970 LOW 1
            ('/usr/bin/env python3 measure.py', d),  # Viktor 41970 LOW 2
            ('/usr/bin/env ./dump.sh', d),
            # accepted false positives, as on the live gate (Klodel 41895): a quoted interpreter call on a
            # keychain-reading file after any -c
            ('grep -c -i "python3 measure.py" notes.py', d),
            ('bash -n x.sh; grep -c -i "python3 measure.py" notes.py', d),
            ('wc -c "python3 measure.py"', d),
            ("ssh -c aes128-ctr host 'python3 measure.py'", d),
            ('bash -o "pipefail" -c \'python3 measure.py\'', d),  # the payload is the quote after -c, not before
        ] + [('python3 lit%d.py' % i, d) for i in range(len(LIT_FORMS))] + [
            ('ls; python3 "measure.py"', d),
            ('python3 -c "import subprocess; subprocess.run([\'' + S + '\', \'dump-keychain\'])"', d),
            ("python3 - <<'PY'\nimport subprocess\nsubprocess.run(['" + S + "', 'find-generic-password'])\nPY", d),
            ("node -e \"require('child_process').execFileSync('" + S + "', ['dump-keychain'])\"", d),
            # card 8a5d51e8 (Viktor 42491): a heredoc body is code when its recipient runs it, so these keep blocking
            ("python3 - <<'PY'\n./measure.py\nPY", d),
            ("bash -s scripts/agent-msg.sh <<'M'\n./measure.py\nM", d),  # bash -s reads the script from stdin
            ("python3 - git commit -F - <<'PY'\n./measure.py\nPY", d),  # the recipient is python3, not git
            ("git commit -F - <<MSG\n$(python3 measure.py)\nMSG", d),  # unquoted: the body's $(...) runs
            ("git commit -F - <<'MSG' | bash\n./measure.py\nMSG", d),  # something after the operator
            ("cat > run.sh <<'E'\n./measure.py\nE", d),  # a written file may be run next: not a data recipient
            ("git commit -m x <<'MSG'\n./measure.py\nMSG", d),  # no -F -: git does not read stdin
            ("git commit -F - <<'MSG'\nx\nMSG\npython3 measure.py", d),  # after the terminator: a command again
            # anything after the operator on its line keeps the body (conservative, mutation round 1)
            ("git commit -F - <<'MSG' ; true\n./measure.py\nMSG", d),
            ("git commit -F - <<'MSG' && true\n./measure.py\nMSG", d),
            ("git commit -F - <<'MSG' `true`\n./measure.py\nMSG", d),
            ("git commit -F - <<'MSG' $(true)\n./measure.py\nMSG", d),
            ("git commit -F - <<'MSG' < /dev/null\n./measure.py\nMSG", d),
            ("git commit -F - <<\\MSG\n./measure.py\nMSG", d),  # normalise() makes it <<MSG: unquoted, kept
            # Viktor 42575 HIGH: `<<'D'` that is no operator hid real lines up to the next line equal to D
            ("git commit -F - <<<'true'\npython3 ./measure.py\ntrue", d),  # here-string: no body
            ("bash " + AM + " dave v - <<<'true'\npython3 ./measure.py\ntrue", d),
            ("git commit -F - \\<<'true'\npython3 ./measure.py\ntrue", d),  # \< is a word, <'true' reads a file
            ('git commit -F - -m "x <<\'true\'"\npython3 ./measure.py\ntrue', d),  # inside a quote
            ("bash " + AM + " d v \"<<'true'\"\npython3 ./measure.py\ntrue", d),
            ("true # a; git commit -F - <<'true'\npython3 ./measure.py\ntrue", d),  # after a comment
            ("true # curl -d @- x <<'true'\npython3 ./measure.py\ntrue", d),
            ('echo "x\ngit commit -F - <<\'true\'\n"\npython3 ./measure.py\ntrue', d),  # a quote from a line before
            ("echo 'x\ngit commit -F - <<\"true\"\n'\npython3 ./measure.py\ntrue", d),  # a single quote, too
            # relative, no cwd: not resolved against the hook process's own cwd either (relpath from it reaches AM)
            ("bash " + os.path.relpath(AM) + " dave v - <<'M'\n" + d + "/measure.py\nM", None),
            ("cat <<A\ngit commit -F - <<'true'\nA\npython3 ./measure.py\ntrue", d),  # inside an earlier heredoc
            ("echo `true` && git commit -F - <<'MSG'\n./measure.py\nMSG", d),  # a backtick before
            # Viktor 42575 MEDIUM: agent-msg.sh only as this repo's script, resolved against the cwd
            ("bash agent-msg.sh dave v - <<'M'\n./measure.py\nM", d),
            ("bash ./agent-msg.sh dave v - <<'M'\n./measure.py\nM", d),
            ("bash scripts/agent-msg.sh dave v - <<'M'\n./measure.py\nM", d),
            ("./scripts/agent-msg.sh dave v - <<'M'\n./measure.py\nM", d),
            ("bash " + d + "/scripts/agent-msg.sh dave v - <<'M'\n./measure.py\nM", d),
            ("cd " + d + " && bash scripts/agent-msg.sh dave v - <<'M'\n./measure.py\nM", AM_ROOT),  # cd moved it
            ("cd " + d + "\nbash scripts/agent-msg.sh dave v - <<'M'\n./measure.py\nM", AM_ROOT),
            ("cd " + d + "; bash scripts/agent-msg.sh dave v - <<'M'\n./measure.py\nM", AM_ROOT),
            ("cd " + d + " & bash scripts/agent-msg.sh dave v - <<'M'\n./measure.py\nM", AM_ROOT),
            ("bash ~/agent-msg.sh dave v - <<'M'\n" + d + "/measure.py\nM", d),  # ~ is not resolved: kept
            # no VAR=x prefix: PATH=, GIT_EXEC_PATH=, BASH_ENV= can hand the body to a program of the caller's choosing
            ("PATH=" + d + ":/usr/bin bash " + AM + " dave v - <<'M'\n./measure.py\nM", d),
            ("GIT_EXEC_PATH=" + d + " git commit -F - <<'MSG'\n./measure.py\nMSG", d),
            ("_X=1 git commit -F - <<'MSG'\n./measure.py\nMSG", d),
            ("lc=1 git commit -F - <<'MSG'\n./measure.py\nMSG", d),
            ("ZX=1 git commit -F - <<'MSG'\n./measure.py\nMSG", d),
            # Viktor 42639 HIGH: a quote left open after the operator makes the next lines part of the command line
            ('git commit -F - <<\'MSG\' -m "x\n" ; ./measure.py #\nMSG', d),
            ("git commit -F - <<'MSG' -m 'x\n' ; ./measure.py #\nMSG", d),
            ("git commit -F - <<'MSG' 2>/dev/null\n./measure.py\nMSG", d),  # anything after the operator keeps it
            # a quote, comment, backtick or $( opened before the operator ends on a body line: what follows runs (bash)
            ('git commit -F - -m "x <<\'MSG\'\n" ; ./measure.py\nMSG', d),
            ("git commit -F - -m 'x <<\"MSG\"\n' ; ./measure.py\nMSG", d),
            ("git commit -F - #x <<'MSG'\n./measure.py\nMSG", d),
            ("git commit -F - `true <<'MSG'\n` ; ./measure.py\nMSG", d),
            ("git commit -F - $(true <<'MSG'\n) ; ./measure.py\nMSG", d),
            # Viktor 42639 MEDIUM: only `cd <path>` or `true` before the recipient; anything else may redefine it
            ("git() { bash; }\ngit commit -F - <<'MSG'\n./measure.py\nMSG", d),
            ("export PATH=./bin:$PATH\ngit commit -F - <<'MSG'\n./measure.py\nMSG", d),
            ("export PATH=./bin:$PATH\ncurl -d @- x <<'J'\n./measure.py\nJ", d),
            ("alias git=bash; git commit -F - <<'MSG'\n./measure.py\nMSG", d),
            ("echo x && git commit -F - <<'MSG'\n./measure.py\nMSG", d),
            ("git add && git commit -F - <<'MSG'\n./measure.py\nMSG", d),  # git add needs a plain path
            ("git config core.hooksPath x && git commit -F - <<'MSG'\n./measure.py\nMSG", d),  # only git add
            ("git add x:y && git commit -F - <<'MSG'\n./measure.py\nMSG", d),  # a pathspec magic char is no plain path
            ("cd ~ && git commit -F - <<'MSG'\n./measure.py\nMSG", d),  # a cd path with ~ or $ is not plain
            ("cd " + d + " & git commit -F - <<'MSG'\n./measure.py\nMSG", d),  # a lone & is no join
            (d + "/bin/bash " + AM + " dave v - <<'M'\n./measure.py\nM", d),  # the caller's own bash
            ("./bin/bash " + AM + " dave v - <<'M'\n./measure.py\nM", d),
            # (card 31045f4d: a later heredoc is data too when the lexer reads the text: in the allow list now)
            # Viktor 42695 HIGH 1: normalise() joins backslash-newline, bash does not inside a quoted-delimiter body. A
            # body line ending in a backslash and then the terminator line: bash ends the body there and runs what
            # follows; the joined text had no terminator until a LATER one, so the lines between were blanked
            ("git commit -F - <<'MSG'\nx\\\nMSG\n./measure.py\nMSG", d),
            ("git add f && git commit -F - <<'MSG'\nx\\\nMSG\n./measure.py\nMSG", d),
            ("curl -s -d @- <<'J'\nx\\\nJ\n./measure.py\nJ", d),
            ("git commit -F - <<-'MSG'\n\tx\\\n\tMSG\n./measure.py\nMSG", d),
            ("bash " + AM + " dave v - <<'M'\nx\\\nM\n./measure.py\nM", d),
            # card fae0712e: the script rules take the shell structure from scripts/lib/shell_lex.py. A command inside
            # a backtick (Viktor 42695 LOW 1: the backtick right after the path hid it), every word after a shell's -c,
            # unquoted too (LOW 2)
            ('echo `./measure.py`', d),
            ('echo "`./measure.py`"', d),
            # Viktor 42794 (3): two double-quoted backtick substitutions, then a following command; the lexer mutants
            # p11-backtick-close and p13-dq-backtick let this through on the mask path (a real bash runs ./measure.py)
            ('printf %s "`./measure.py`" "`./measure.py`" ; set -x', d),
            # a comment inside a backtick ends at the closing backtick: the command after it runs
            ('echo `echo a #` ; ./measure.py', d),
            # card f7d4ead8 (oracle matrix): an escaped backtick inside a backtick nests, bash runs ./measure.py
            ('echo `true \\`./measure.py\\``', d),
            ('bash -c ./measure.py', d),
            ('sudo bash -c ./measure.py', d),
            ('"$SHELL" -c ./measure.py', d),
            ('bash -c -e ./measure.py', d),
            ('sh -c python3\\ measure.py', d),
            # card fae0712e, fail-closed: a text the lexer does not fully understand (an unterminated quote) takes the
            # old path, which reads the quoted ; as a boundary
            ("echo 'x; ./measure.py", d),
            ('echo "x; ./measure.py', d),
            # card fae0712e: a quoted argument is masked only for a data command, and only when nothing in the text can
            # make that command something else (zsh expands an alias set on an earlier line; a function, eval, PATH,
            # a sourced file)
            ("alias echo='bash -c'\necho 'x; ./measure.py'", d),
            ('echo() { bash -c "$1"; }; echo \'x; ./measure.py\'', d),
            ("eval 'echo() { bash -c \"$1\"; }'; echo 'x; ./measure.py'", d),
            ("export PATH=./bin:$PATH; grep 'x; ./measure.py' notes.py", d),
            (". ./runner.sh; echo 'x; ./measure.py'", d),
            # card fae0712e: every other command's quoted arguments are read as before (they may run them)
            ("tm" + "ux send-keys -t x 'cd sub2; python3 only.py' Enter", d),
            ("awk 'BEGIN{system(\"./measure.py\")}'", d),
            ('git commit -m "x; ./measure.py"', d),  # git is no data command (an alias, a hook): read as before
            # card fae0712e: a data command's substitution is code, and a real separator still ends it
            ("echo 'a' $(./measure.py)", d),
            ("echo 'x;' ; ./measure.py", d),
            # card fae0712e, found by a differential fuzz against bash and zsh (both ran the script, the old gate
            # allowed): normalise() joined a backslash-newline whose backslash ends a comment or is the second half of
            # an escaped backslash, and the next line, a command of its own, became part of a word
            (': |#\\\n./measure.py a', d),
            ('grep -c x \\\\\n./measure.py', d),
            ('grep -c x ;./measure.py>>./measure.py', d),  # the same fuzz: a redirection right after the path
            ('./measure.py<notes.py', d),
            # card fae0712e: a data command's output can become code, so its quotes are read as before when it is piped,
            # redirected, captured, stored, or inside a compound command (bash and zsh ran each of these; the old gate
            # blocked them by reading the quoted separator, the first lexer draft let them through)
            ("echo 'x; ./measure.py' | bash", d),
            ("printf 'x; ./measure.py' | sh", d),
            ("echo 'x; ./measure.py' |\nbash", d),
            ("echo 'x; ./measure.py' > run.sh; bash run.sh", d),
            ("bash <(echo 'x; ./measure.py')", d),
            ("x=$(echo 'x; ./measure.py'); bash -c \"$x\"", d),
            ("printf -v x 'a; ./measure.py'; bash -c \"$x\"", d),
            ("{ true; echo 'x; ./measure.py'; } | bash", d),
            ("{'true'; echo 'x; ./measure.py'; :} | bash", d),  # zsh: a brace group, no blank, quoted first word
            ("if true\nthen\necho 'x; ./measure.py'\nfi | bash", d),
            ("for i in 1\ndo\necho 'x; ./measure.py'\ndone | sh", d),
            ("exec >run.sh; echo 'x; ./measure.py'; exec >/dev/null; bash run.sh", d),
            ("echo $(echo 'a; ./measure.py')", d),  # inside a substitution: not masked (conservative)
            # past the lexer's bounds the old path, which reads the quoted ; (card fae0712e, fail-closed)
            ("echo 'x; ./measure.py' " + '$(true)' * 65, d),  # LEX_MAX_SUBSTS + 1
            ("echo 'x; ./measure.py' " + 'f(' * 40 + ' x' * 2000, d),  # unclosed: a lexer problem
            ("echo 'x; ./measure.py' " + '$(' * 30 + ' x' * 30000 + ')' * 30, d),  # past LEX_MAX_WORK
            # $_ is the previous command's last word (bash and zsh ran it), and the shell's own command line read back
            ("echo 'x; ./measure.py'; bash -c \"$_\"", d),
            ("echo 'x; ./measure.py'; bash -c \"${_}\"", d),
            ("echo 'x; ./measure.py'; ps -o args= -p $$ | cut -d\"'\" -f2 | bash", d),
            ("trap 'bash -c \"${BASH_COMMAND:6:-1}\"' DEBUG; echo 'x; ./measure.py'", d),
            # card fae0712e: a data command's mask stops at its own frame: a nested command's quotes are its own
            ("echo $(awk 'BEGIN{system(\"./measure.py\")}')", d),
            ("echo \"$(awk 'BEGIN{system(\"./measure.py\")}')\"", d),
            # card 74586987 (Viktor 42794 INFO; the first eight passed the live gate d85d82e3, measured 2026-11-16): a
            # pipeline into a shell runs what it prints, quoted or not
            ('echo ./measure.py | bash', d),
            ('echo "./measure.py" | bash', d),
            ("printf %s './measure.py' | tee /dev/null | sh", d),
            ('echo -n "./measure.py" | source /dev/stdin', d),
            ("printf '%s\\n' 'python3 measure.py' | tee /dev/null | bash", d),
            ('echo python3 measure.py | sh', d),
            ("echo 'python3 measure.py' | bash -s", d),
            ('echo ./dump.sh | zsh', d),
            ('echo ./measure.py | . /dev/stdin', d),
            ('echo ./measure.py | source /dev/fd/0', d),
            ('echo ./measure.py | source /proc/self/fd/0', d),
            ("echo ./measure.py | source '/dev/stdin'", d),
            ('echo ./measure.py | bash /dev/stdin', d),
            ('echo ./measure.py | bash -', d),
            ('echo ./measure.py | env bash', d),
            ('echo ./measure.py | sudo -n bash', d),
            ('echo ./measure.py |& bash', d),
            ('echo ./measure.py |bash', d),
            ('echo ./measure.py | bash 2>/dev/null', d),
            ('echo ./measure.py | "$SHELL"', d),
            ('echo ./measure.py | /bin/bash', d),
            ('echo ./measure.py | tr a a | bash', d),
            ('echo sh dump.sh | bash', d),
            ('echo source measure.py | bash', d),
            ('echo cd sub \\; ./deep.py | bash', d),  # an escaped ; is printed, the shell reads it as a separator
            ('cd sub; echo ./deep.py | bash', d),  # a cd before the pipeline moves where the word is looked up
            ('echo python3 -m measure | bash', d),
            # a word that names the file at no command position: printf puts it after the interpreter
            ("printf 'python3 %s\\n' measure.py | bash", d),
            ('X=./measure.py; echo $X | bash', d),  # an assignment in the text (expand())
            # a group right before the pipe is read whole
            ('(echo ./measure.py) | bash', d),
            ('{ echo ./measure.py; } | bash', d),
            ('true; { echo ./measure.py; } | bash', d),
            ('( (echo ./measure.py) ) | bash', d),
            ('(echo ./measure.py) | (cat) | bash', d),
            ('(echo a; echo ./measure.py) | bash', d),
            ('{ echo a; echo ./measure.py; } |& sh', d),
            # mutation round r2 survivors: a quoted ")" leaves the group's real closer unmatched: read from the text's
            # start, not after it (g3); a quoted "(" inside a { } group is popped, not taken for the brace's opener
            # (g5); a word with an escaped blank is a command line of its own (w2); a word's blank-separated pieces
            # are looked up, when only printf's format puts them after the interpreter (w3)
            ('(echo ./measure.py; echo ")") | bash', d),
            ('{ echo ./measure.py; echo "("; } | bash', d),
            ("printf '%s %s\\n' python3 'measure.py x' | bash", d),
            # a heredoc body's pipes stay pipelines unless the heredoc is data (data_body_pipes_masked): a shell or a
            # non-data recipient, an unquoted delimiter, a redefined recipient, the look-alike agent-msg.sh, something
            # after the operator on its line, a second heredoc in the command
            ("bash <<'EOF'\necho ./measure.py | bash\nEOF", d),
            ("cat <<'EOF'\necho ./measure.py | bash\nEOF", d),
            ("curl -d @- http://h <<J\necho ./measure.py | bash\nJ", d),
            ("curl() { bash; }; curl -d @- http://h <<'J'\necho ./measure.py | bash\nJ", d),
            ("bash agent-msg.sh dave v - <<'M'\necho ./measure.py | sh\nM", d),
            ("curl -d @- http://h <<'J' -o out\necho ./measure.py | bash\nJ", d),
            ("curl -d @- http://h <<'J' 3<<'K'\necho ./measure.py | bash\nJ\nx\nK", d),
            ("x=$(curl -d @- http://h <<'J'\necho ./measure.py | bash\nJ\n)", d),  # only a top-level command's heredoc
            ("cd /tmp\nbash scripts/agent-msg.sh dave v - <<'M'\necho " + d + "/measure.py | sh\nM", AM_ROOT),
            ('{ echo a; echo python3 -m measure; } | bash', d),  # each command's words joined apart (not "a echo ...")
            ('echo "$(echo a)" ./measure.py | bash', d),  # a substitution's ")" before the pipe is no group start
            # over-read on purpose: a word that names a keychain-reading file in a pipeline into a shell
            ('echo hi measure.py | bash', d),
            ('cat measure.py | bash', d),
            # card e05330a4 (Viktor 44085 G1, MEDIUM, main: allow, real bash ran the stub): bash ends a word at an
            # unquoted < or > too, so a redirection glued to the script word leaves the script to run
            ('python3 measure.py>/dev/null', d),
            ('python3 measure.py>out.txt', d),
            ('python3 measure.py>>tmp/log', d),
            ('python3 measure.py>/dev/null 2>&1', d),
            ('python3 measure.py</dev/null', d),
            ('python3 measure.py&>/dev/null', d),
            ('python3 measure.py>&2', d),
            ('python3 measure.py>|tmp/o', d),
            ('python3 ./measure.py>/dev/null', d),
            ('python3 ' + os.path.join(d, 'measure.py') + '>/dev/null', d),
            ('ruby measure.py>/dev/null', d),
            ('perl measure.py>/dev/null', d),
            ('python3 -B measure.py>/dev/null', d),
            ('env python3 measure.py>/dev/null', d),
            ('python3 -m measure>/dev/null', d),
            ('python3 -mmeasure>/dev/null', d),
            ('bash dump.sh>/dev/null', d),
            ('bash ./dump.sh>/dev/null', d),
            ('sh dump.sh>/dev/null', d),
            ('source dump.sh>/dev/null', d),
            ('. ./dump.sh>/dev/null', d),
            # ... and a directly run word with a quote in it: the operator glued to it ends the word too
            ('./"dump".sh;true', d),
            ('./"dump".sh&&true', d),
            ('./"dump".sh|cat', d),
            ('./"dump".sh>/dev/null', d),
            ('./dump$(true).sh;true', d),
            # card e05330a4 (Viktor 44085 G2, MEDIUM, main: allow): a shell's -e is errexit, not code; the next word
            # is the file it runs (node / perl / ruby -e stays code, below in allow)
            ('bash -e dump.sh', d),
            ('bash -e ./dump.sh', d),
            ('sh -e dump.sh', d),
            ('zsh -e dump.sh', d),
            ('ksh -e dump.sh', d),
            ('dash -e dump.sh', d),
            ('bash -xe dump.sh', d),
            ('bash -ue dump.sh', d),
            ('bash -e -u dump.sh', d),
            ('bash -e -- dump.sh', d),
            ('bash -o pipefail -e dump.sh', d),
            ('env bash -e dump.sh', d),
            ('bash -e dump.sh arg', d),
            ('cd sub2 && bash -e only.py', d),
            # card e05330a4 (Viktor 45589 R1, MEDIUM, a G2 regression): a -c cluster whose c is not the last letter
            # (-cx, -cu, -co, -cex) is code to the word reading, so its command string must be read; -ce / -lce were
            # open on the fleet gate too (bash ran dump.sh / measure.py in every row)
            ('bash -cx ./dump.sh', d),
            ('sh -cu ./dump.sh', d),
            ('bash -cl ./dump.sh', d),
            ('bash -cv ./dump.sh', d),
            ("bash -cex 'python3 measure.py'", d),
            ('bash -co pipefail ./dump.sh', d),
            ('bash -cx "./dump.sh; true"', d),
            ('bash -ce ./dump.sh', d),
            ("bash -ce 'python3 measure.py'", d),
            ('bash -lce ./dump.sh', d),
            ('zsh -ce ./dump.sh', d),
            # ... with a capital letter on either side of the c (mutation round 6, cflag-lower-after / -before)
            ('bash -cE ./dump.sh', d),
            ('bash -Ec ./dump.sh', d),
            # card e05330a4 (G1 with a blank, allow on fcba0fe6, measured; real bash and zsh ran the stub): a quote or
            # substitution open over a blank goes on into the next piece, the glued redirection still ends the word
            ('python3 measure.py>"a b"', d),
            ("python3 measure.py>'a b'", d),
            ('python3 $(true x)measure.py>/dev/null', d),
            ('python3 `true x`measure.py>/dev/null', d),
            ('python3 "$(true \\")"measure.py>/dev/null', d),
            ('python3 $(true >&2)measure.py>/dev/null', d),
            ('python3 `true >&2`measure.py>/dev/null', d),
            ('bash $(true x)dump.sh>/dev/null', d),
            # the first cut of the joined word wins, and a cut in its third piece sits past both blanks (round 3)
            ('python3 measure.py>"a b">c', d),
            ('python3 $(true x y)measure.py>/dev/null', d),
            # ... and as a path word: a quote opened AFTER the glued redirection leaves the cut where it is (mutation
            # round 3, ret-always-cut survived; on 0d285cbb and on the fleet gate these were allowed, bash and zsh ran)
            ('./"dump".sh>"x y"', d),
            ("./\"dump\".sh>'x y'", d),
            ('./dump"".sh>"x y"', d),
            ('./$(true)dump.sh>"x y"', d),
            # a fd of two digits before > is a redirection, not a word (mutation round 4, fd-rx-one-digit: read `12` as
            # the script; bash ran measure.py)
            ('python3 12>err.log measure.py', d),
            ('python3 12>/dev/null measure.py', d),
            # card 946937b7 (Viktor 45520, MEDIUM; all allow on ed110117 and da7d6cb8, bash and zsh ran the script):
            # a quoted or escaped blank or ; & | in a word before the script is word text, and a quoted value of an
            # assignment before the interpreter is part of it
            ('python3 -W "a b" measure.py', d),
            ('python3 -W "ignore;x" measure.py', d),
            ('python3 -W ignore\\;x measure.py', d),
            ('python3 -X "a&b" measure.py', d),
            ("python3 -W $'a b' measure.py", d),
            ('python3 -X "a b" -m evilmod', d),
            ('python3 >"x y" measure.py', d),
            ('python3 >x\\ y measure.py', d),
            ('python3 >"x&" measure.py', d),
            ("python3 >'x;' measure.py", d),
            ('python3 2>x\\& measure.py', d),
            ('python3 -u >x\\& measure.py', d),
            ('bash >x\\& dump.sh', d),
            ('source >"a b" dump.sh', d),
            ('source > x dump.sh', d),
            ('A="a b" python3 measure.py', d),
            ("A='a b' python3 measure.py", d),
            ('env A="a b" python3 measure.py', d),
            ('A="x\\"y z" python3 measure.py', d),
            ('python3 "a b.py"', d),
            ("python3 'a b.py'", d),
            ('python3 a\\ b.py', d),
            # card 946937b7 (Viktor 45532; all allow on ed110117, da7d6cb8 and 348e7dd4, bash and zsh ran the script): a
            # quoted or escaped paren in a $( ) before the script; without_substs' regex ended it at the first )
            ("python3 $(true ')')measure.py", d),
            ('python3 $(true ")")measure.py', d),
            ("python3 $(true '(')measure.py", d),
            ('python3 $(true \\))measure.py', d),
            ("bash $(true ')')dump.sh", d),
            ("python3 $(true ')')measure.py>/dev/null", d),
            ('python3 "$(true \')\')"measure.py', d),
            ("python3 $(true ')' $(true '('))measure.py", d),
            ("source $(true ')' ) dump.sh", d),
            ('python3 $(true \')\' "x")measure.py', d),
            # was an allow row (generated mutant 032): bash runs ")measure.py" here, but the gate reads a substitution as
            # printing nothing (it cannot know echo from true), and `python3 $(true ")")measure.py` runs measure.py
            ('python3 $(echo ")")measure.py', d),
            ('python3 $(true ")")measure.py', d),
            # ... Viktor 45533 (wider): a direct path, source / ., other commands in the substitution
            ("./$(true ')')dump.sh", d),
            ("./$(true '(')dump.sh", d),
            ("./$(true ')' )dump.sh", d),
            ("source $(true ')')dump.sh", d),
            (". $(true ')')dump.sh", d),
            ("python3 $(: ')')measure.py", d),
            ("python3 $(echo ')' >/dev/null)measure.py", d),
            ("bash -e $(true ')')dump.sh", d),
            # ... and a word past the lexer's bounds (65+ substitutions): its quotes leave the regex reading unsure,
            # fail-closed
            ("python3 $(true ')')" + '$(true)' * 70 + 'measure.py', d),
            ("./$(true ')')" + '$(true)' * 70 + 'dump.sh', d),
            # card 946937b7 (Viktor 45543, MEDIUM, all allow on ed110117; bash and zsh ran the script): the lexer does
            # not read the text (65+ substitutions, or LEX_MAX_WORK with fewer) and a ")" of a substitution in the
            # call's words cut the call: fail-closed when a "(" or a backtick is before the cut
            ('python3 $(true)measure.py; echo ' + '$(true)' * 70, d),
            ('python3 ' + '$(true)' * 70 + 'measure.py', d),
            ('x=$(python3 $(true)measure.py); echo ' + '$(true)' * 70, d),
            ('source $(true)dump.sh; echo ' + '$(true)' * 70, d),
            ('. $(true)dump.sh; echo ' + '$(true)' * 70, d),
            ('./$(true)dump.sh; echo ' + '$(true)' * 70, d),
            ('python3 $(true)measure.py; echo ' + '$(true)' * 59 + ' ' + 'a' * 60000, d),  # LEX_MAX_WORK, 60 substitutions
            ('x=$(python3 measure.py) ; echo ' + '$(true)' * 70, d),  # no "(" before the cut: the old reading blocks
            # card 946937b7 (Viktor 45626; bash ran the script in every row). R1 MEDIUM, a regression from 348e7dd4: a
            # here-string a shell reads is a command line (the fleet gate caught it by chance, through the old split)
            ("bash <<<'python3 measure.py'", d),
            ("bash <<<'python3 -W \"a b\" measure.py'", d),
            ("sh <<<'./dump.sh'", d),
            ("bash -s <<<'python3 measure.py'", d),
            ('bash <<< "python3 measure.py"', d),
            ("<<<'python3 measure.py' bash", d),
            ("zsh <<<'./dump.sh'", d),
            # R2 MEDIUM: a quoted blank in a call the lexer reads as quoted text (an eval payload, a heredoc body)
            ("eval 'python3 -W \"a b\" measure.py'", d),
            ("eval \"python3 >'x y' measure.py\"", d),
            ("eval 'python3 >\"x y\" measure.py'", d),
            ('bash <<EOF\npython3 -W "a b" measure.py\nEOF', d),
            ("bash <<'EOF'\npython3 -W \"a b\" measure.py\nEOF", d),
            ('cat <<EOF\n$(python3 >"x y" measure.py)\nEOF', d),
            # R3 LOW: an input redirection, a here-doc or a here-string before source's file
            ('source </dev/null dump.sh', d),
            ('. </dev/null dump.sh', d),
            ('source <"a b" dump.sh', d),
            ('source 0<"a b" dump.sh', d),
            ('source <<<x dump.sh', d),
            ('source <&0 dump.sh', d),
            ('source <>/dev/null dump.sh', d),
            # R4 MEDIUM: an escaped blank in an assignment's value; past the lexer's bounds an escaped blank or operator
            ('A=a\\ b python3 measure.py', d),
            ('A=a\\ b\\ c python3 measure.py', d),
            ('python3 2>x\\& measure.py; echo' + ' $(true)' * 66, d),
            ('python3 >x\\ y measure.py; echo' + ' $(true)' * 66, d),
            ('python3 -W a\\;b measure.py; echo' + ' $(true)' * 66, d),
            ('bash >x\\& dump.sh; echo' + ' $(true)' * 66, d),
            # mutation survivors of Viktor's round on ab672f53: the odd-quote fail-closed (m03), a backtick that opens
            # past the lexer's bounds (m17), the FIRST code blank of a run ends the word (m21: bash runs "measure.py ")
            ('python3 -W "a b" measure.py; echo' + ' $(true)' * 66, d),
            ('python3 `true \\)`measure.py; echo' + ' $(true)' * 66, d),
            ("python3 'measure.py '  x", os.path.join(d, 'tspace')),
            ('python3 measure.py\\   x "q"', os.path.join(d, 'tspace')),
            # ... and without a blank (mutation round 1: the quote, escape, $'..', $( ) and backtick tracking of the cut)
            ('python3 `true>&2`measure.py>/dev/null', d),
            ('python3 $(true>&2)measure.py>/dev/null', d),
            ('python3 "$(true\\")"measure.py>/dev/null', d),
            ('python3 $(true\\")measure.py>/dev/null', d),
            ("python3 $(true$'\\'')measure.py>/dev/null", d),
            ("python3 $'measure.py'>/dev/null", d),
            # an fd number or a {fd} before the redirection is no script word (zsh runs measure.py; bash 3.2 has no {fd})
            ('python3 {fd}>/dev/null measure.py', d),
            ('python3 2>/dev/null measure.py', d),
            # ... but macOS bash 3.2 runs a FILE named {fd} there (measured 11-16; mutation round 2, fd-rx-no-brace)
            ('python3 {fd}>/dev/null ok.py', os.path.join(d, 'fdname')),
            ("bash -c 'python3 {fd}>/dev/null ok.py'", os.path.join(d, 'fdname')),
            # card 946937b7: the same fleet shapes as the allow rows (the gate's view has an odd quote, the command
            # lexes cleanly), with the script that reads the keychain
            ('python3 -c "import sys; print(\'a b\')" && python3 measure.py "a b"', d),
            ("python3 -c 'print(1)' && python3 measure.py \"it's x\"", d),
            (": <<'NOTE'\npython3 isn't ready\nNOTE\npython3 measure.py", d),
            ('nohup sh -c "python3 measure.py > /tmp/k.log 2>&1" > /dev/null 2>&1 &', d),
            ("TMPDIR=/x sh -c 'unset TMPDIR; python3 measure.py x' 2>&1 | tail -3", d),
            ("python3 -c 'print(1)' && python3 measure.py \"it's x\"; echo" + ' $(true)' * 66, d),
        ]
        prose = 'mérve: 2 fájl változott (' + d + '/measure.py + _test.py), (./measure.py) is'
        allow = [
            ('python3 list.py', d),
            # card 31045f4d (A, Klodel 43233): a data file after the script is its sys.argv, not run
            ('python3 stat.py regiszter.jsonl', d),
            ('python3 -I -B -u stat.py regiszter.jsonl', d),
            ('python3 -W ignore stat.py regiszter.jsonl', d),
            ('python3 -IW ignore stat.py regiszter.jsonl', d),
            ('python3 -Wignore stat.py regiszter.jsonl', d),
            ('python3 -Xdev stat.py measure.py', d),
            ('python3 -W measure.py stat.py', d),  # a warning filter, never run
            ('python3 stat.py measure.py', d),  # Viktor 43235 B/C: the same boundary as a path in the script
            ('/usr/bin/python3 stat.py regiszter.jsonl 2>/dev/null', d),
            ('python3 stat.py ' + ' '.join('a%d' % i for i in range(80)), d),  # argv past MAX_ARGS: data
            ('python3 -c pass -Wignore measure.py', d),  # -c first: inline code, the rest is its argv
            # card 217f551b: the backtick that CLOSES the substitution the call stands in still ends its words
            ('x=`python3 stat.py` measure.py', d),
            ('echo `python3 stat.py` measure.py', d),
            ('x=`python3 stat.py \\`true\\` regiszter.jsonl`', d),
            ('python3 stat.py `true` regiszter.jsonl', d),  # after the plain script: argv data, as before
            ("python3 stat.py '`' measure.py", d),
            # card 4bdf7309: the ")" that CLOSES the $( ) the call stands in still ends its words, and after the plain
            # script a substitution is argv data, as for the backtick
            ('x=$(python3 stat.py) measure.py', d),
            ('echo $(python3 stat.py) measure.py', d),
            ('echo "$(python3 stat.py)" measure.py', d),
            ('python3 stat.py $(true) regiszter.jsonl', d),
            ('python3 stat.py $(true)regiszter.jsonl', d),
            ("python3 stat.py '$(' measure.py", d),
            # a call end RIGHT AFTER a substitution inside the call's words still ends the call (the lexer's end is
            # exclusive; mutation a5, "a <= e", read on into the next command)
            ('python3 $(true); echo measure.py', d),
            ('python3 `true`; echo measure.py', d),
            # card 70c94516: quotes taken off a word that names no keychain-reading file, and the ordinary -m / source
            # / ./ shapes stay allowed
            # (a non-plain script word keeps the old walk, as on main: `python3 "st"at.py regiszter.jsonl` judges the
            # data file too and blocks there; accepted, conservative)
            ('python3 "st"at.py', d),
            ("python3 $'\\x73'tat.py", d),
            ('python3 "no"tes.py stat.py', d),
            ('python3 -m "notes"', d),
            ('python3 -Inotes', d),
            ('python3 -m json.tool regiszter.jsonl', d),
            ('python3 -W ignore -m notes', d),
            ('source "$(true)"runner.sh', d),
            ('. "$(dirname "$0")/notes.py"', d),
            ('./"no"tes.py', d),
            ('echo "a b" \'c d\' $\'e\'', d),
            # an EVEN run of backslashes is escaped backslashes: the backtick after them closes the substitution, and
            # measure.py is no word of bash's call (mutation m11: counting one backslash read it as bash's $2)
            ('x=`bash runner.sh a\\\\` measure.py', d),
            # Viktor 43235 point 1: python's words after the script are its sys.argv (this was a block row: "an
            # argument is read too"; node -r, source and bash keep that reading)
            ('python3 list.py measure.py', d),
            # a later data heredoc after an earlier one (was a block row: "only the first heredoc"); the lexer
            # reads the state the regex could not
            ("git commit -F - <<'A'\nx\nA\ngit commit -F - <<'B'\n./measure.py\nB", d),
            # card 31045f4d (B, Pulzus 43167): prose in a python / node heredoc string
            ("python3 -I - <<'PY'\nr = ('" + prose + "')\nprint(r)\nPY", d),
            ("node - <<'JS'\nconsole.log('" + prose + "')\nJS", d),
            # mutation r12: a "(" at a line start with no word before it (a tuple on a continuation line) is read
            # quietly, not as an error
            ("python3 - <<'PY'\nrows = [\n (1, 2),\n]\nprint(rows)\nPY", d),
            # card 31045f4d (C, Klodel 43233): the fleet's curl and agent-msg forms
            (cf_curl + "<<'JSON'\n{\"content\":\"" + prose + "\"}\nJSON", d),
            ('T="Authorization: Bearer $(cat store/.dashboard-token)"\n' + cf_curl.replace(
                '"Authorization: Bearer $(cat store/.dashboard-token)"', '"$T"') + "<<'JSON'\n" + prose + "\nJSON", d),
            ('cd ' + d + '; S=/tmp/x; T="x"; ' + cf_curl + "<<'JSON'\n" + prose + "\nJSON", d),
            (cf_curl + "<<'JSON'\n" + prose + "\nJSON\nbash scripts/agent-msg.sh dave klodel - <<'M'\n" + prose
             + "\nM", AM_ROOT),
            (cf_curl + "<<'JSON'\n" + prose + " the --source and eval words\nJSON", d),  # REDEF_RX reads code only
            ('true | ' + cf_curl + "<<'JSON'\n" + prose + "\nJSON", d),
            # card 31045f4d: this repo's agent-msg.sh with the message as an argument (Klodel 17:51, the same call)
            ('bash scripts/agent-msg.sh klodel dave "' + prose + '; ' + d + '/measure.py | x"', AM_ROOT),
            ('cd ' + AM_ROOT + '; bash scripts/agent-msg.sh klodel viktor "' + prose + ' ' + 'szó ' * 80 + '"', os.path.join(d, 'sub2')),  # (d has a look-alike scripts/agent-msg.sh)
            ('bash ' + AM + ' klodel dave "(' + d + '/measure.py)"', d),
            # Klodel's blocked call (main transcript 2026-11-15 17:51 UTC, its shape; the prose made to name the fixture):
            # an assignment, a comment, a memory PUT, a bare echo, a second comment
            ('cd ' + d + '; T="Authorization: Bearer $(cat store/.dashboard-token)"\n'
             'curl -s -X POST localhost:3420/api/kanban/d9/comments -H "Content-Type: application/json" -H "$T" '
             "--data-binary @- <<'JSON'\n{\"content\":\"" + prose + "\"}\nJSON\n"
             # the endpoint is two literals: no file under scripts/hooks names it whole
             # (src/__tests__/agent-scaffold-memory-load-claim.test.ts, Kernel 43486)
             'curl -s -X PUT localhost:3420/api/' 'memories/1 -H "Content-Type: application/json" -H "$T" '
             "-H \"X-Agent-Id: klodel\" --data-binary @- <<'JSON'\n{\"content\":\"" + prose + "\"}\nJSON\necho\n"
             'curl -s -X POST localhost:3420/api/kanban/ae/comments -H "Content-Type: application/json" -H "$T" '
             "--data-binary @- <<'JSON'\n{\"content\":\"" + prose + "\"}\nJSON", d),
            # card 15896271: an output redirection's target is written, not run
            ('python3 list.py > out.txt', d),
            ('python3 list.py >out.txt', d),
            ('python3 list.py >> out.txt', d),
            ('python3 list.py 2>&1 > out.txt', d),
            ('python3 list.py &> out.txt', d),
            ('python3 list.py >| out.txt', d),
            ('python3 list.py 2> out.txt', d),
            ('python3 list.py >& out.txt', d),  # Viktor 42251: the target of >& is written, not run
            ('python3 list.py 2>&1 | head', d),
            ('python3 list.py > measure.py', d),  # truncated, not run
            ('echo a >|./measure.py', d),  # the target of >| is written, not run (mutant, d868a616)
            # Viktor 42295 INFO 2: a | or & ends the interpreter's words; the next command's file is read, not run
            ('python3 list.py | grep dump measure.py', d),
            ('python3 list.py & grep dump measure.py', d),
            ('python3 notes.py', d),
            ('python3 word.py', d),
            ('node labels.js', d),
            ('python3 missing.py', d),
            ('python3 adir', d),
            ('python3 -m list', d),
            ('python3 -m pip --version', d),
            ('python3 -m sub', d),  # sub/ has no __init__ or __main__ with a read; deep.py is not run by -m sub
            ('node -m measure', d),  # -m is python's; node has no module flag that runs ./measure.py
            ('node -e measure.py', d),  # -e: the text is code (an expression), the file is not run
            ('node -r ./ok.js list.py', d),  # two clean files
            # the word after a CLOSING quote is not a command: grep on a keychain-reading file passes (the #275 gate
            # blocked `grep -n "for x" scripts/hooks/keychain-read-gate.py`, 2026-11-14)
            ('grep -n "for x" sub/deep.py', d),
            ('grep -n "do" -A 18 sub/deep.py', d),
            ("sed -n '1,5p' sub/deep.py", d),
            ('grep -n "x" "sub/deep.py"', d),
            ('echo "run" python3 measure.py', d),
            ('grep -n "eval" sub/deep.py', d),  # a word that only names a payload command is not one
            ("grep -n 'watch' sub/deep.py", d),
            # prose after a ")": a sentence-ending "." is not `source` of a file named later in the sentence
            # (an agent-msg heredoc blocked on the #275 gate, 2026-11-14)
            ("cat <<'E'\nmerge-base egyezik). Egy commit, csak sub/deep.py es a teszt.\nE", d),
            # source: the rest is judged only when the first word is a file (bash runs nothing otherwise)
            ('source nonexist.sh sub/deep.py', d),
            ('source ok.js list.py', d),
            # inside the PAYLOAD_OPEN bounds and clean; a fifth flag with no quote after it
            ("bash -c -x -x -x -x 'echo hi'", d),
            ("tmux new-session -d -s a -n b -c /tmp -x 1 -y 1 'echo hi'", d),  # eleven words, a real call
            ('grep -c -i -n -r -l -w pattern sub', d),
            # Viktor 41859 A: a -c that is not a shell's, with a quote later, passes (1392cfac blocked them blind)
            ('ls -c -l -a -h -t -r "my dir"', d),
            ('ls -c -l -a -h -t -r "measure.py"', d),
            ('rsync -c -a -v -z -h --progress "src dir" dest/', d),
            ('git diff -c --stat --no-color --name-only -z --abbrev "measure.py"', d),
            ('grep -c -i -n -r -w -H "x" measure.py', d),
            ('watch -n 1 -d -t -x -x "date"', d),
            ("tmux new" + " -e A=1" * 8 + ' "ls"', d),
            ('tar -c -v -z -p -h -X "ex" x', d),
            ("git log -c --stat -p --follow -M -C 'measure.py'", d),
            ('find . -exec -a -b -c -d -e "x" ;', d),
            ("bash -c -o pipefail 'echo hi'", d),
            ("bash -c -o 'pipefail' 'echo hi'", d),
            ("bash '-c' 'echo hi'", d),  # Viktor 41906: a quoted -c with a clean payload passes
            ("\"$BASH\" -c -o 'pipefail' 'echo hi'", d),
            ("bash -c $(echo -x) 'echo hi'", d),
            ("bash -c $(echo -x) 'echo hi'; grep -n 'x' notes.py", d),  # the marking ends at the ;
            ("bash -c -o 'pipefail' 'echo hi'\necho \"python3 measure.py\"", d),  # and at a newline (Viktor 41917)
            ('sort -c "x"', d),
            # card 3085a683: the wrapped command is judged, clean here
            ('sudo -u root python3 list.py', d),
            ("ssh host 'echo hi'", d),
            ('script -q /dev/null ls', d),
            ('timeout -s KILL 5 python3 notes.py', d),
            ('echo sudo -u root python3 measure.py', d),  # prose: sudo is not in command position
            # a quote is not a script position: the script rules walk wrappers at their own positions only
            ('grep -n "sudo -u root python3 measure.py" notes.py', d),
            ("bash x.sh -c 'notes.py'", d),  # no file named so is run by the payload rules: notes.py is clean
            ('bash -c -x ; echo "python3 measure.py"', d),  # the all-quotes rule ends at the shell's command
            ('grep -c x f; echo "a" "python3 measure.py"', d),  # a non-shell -c: its first quote, in its command only
            ('grep -c x f; echo "python3 measure.py"', d),  # no quote in the -c's command: nothing is marked
            ('bash x.sh; grep -c x "a" "python3 measure.py"', d),  # a shell in an EARLIER command: first quote only
            # the boundaries (Viktor 41790 INFO 2): -mMOD stops the walk, exactly MAX_ARGS words, a cat of 64 words,
            # CAT_RX after a closing quote is not a command
            ('python3 -mlist ' + 'a ' * 70, d),
            ('python3 list.py ' + ' '.join(f'a{i}' for i in range(63)), d),
            ('cat ' + 'x ' * 63 + 'list.py | python3', d),
            ('echo "x" cat measure.py | python3', d),
            ('python3 ' + 'A' * 4095, d),  # the window ends exactly at the end of the command: nothing unread
            ('python3 list.py ' + ' '.join(f'a{i}' for i in range(62)), d),  # 63 words: inside MAX_ARGS (64)
            ('python3 -c pass ' + 'a ' * 100, d),  # the walk stops at -c: the rest is not a script's words
            ('cd sub2 && cat only.py', d),  # no interpreter: reading a file is not running it
            ('python3 word.py < notes.py', d),
            ('node worker.mjs', d),  # agent-worker.ts shape: a non-read subcommand, `-p` only in a comment
            ('python3 -c "print(1)"', d),
            ('cat measure.py', d),
            ('grep -n find-generic-password measure.py', d),
            ('python3 measure.py', None),  # relative path, no cwd and no cd: not resolvable, not judged
            ('ls ' + d, None),
            # card 8a5d51e8 (Viktor 42491): a quoted heredoc whose recipient only stores or sends it is data
            ("git commit -q -F - <<'MSG'\ntitle\n\n./measure.py is quoted here\nMSG", d),
            ("git -C . commit -F - <<'MSG'\n./measure.py\nMSG", d),
            ("bash " + AM + " dave viktor - <<'M'\n./measure.py sorai\nM", d),
            ("sh " + AM + " dave viktor - <<'M'\n./measure.py\nM", d),
            (AM + " dave viktor - <<'M'\n./measure.py\nM", d),
            ("bash scripts/agent-msg.sh dave viktor - <<'M'\n" + d + "/measure.py\nM", AM_ROOT),  # first command
            ("true | bash scripts/agent-msg.sh dave viktor - <<'M'\n" + d + "/measure.py\nM", AM_ROOT),  # pipe
            ("/bin/bash " + AM + " dave viktor - <<'M'\n./measure.py\nM", d),
            ("/usr/bin/sh " + AM + " dave viktor - <<'M'\n./measure.py\nM", d),
            ("cd " + d + " || git commit -F - <<'MSG'\n./measure.py\nMSG", d),
            ("\tcd\t" + d + "/./sub-dir\t&&\tgit commit -F - <<'MSG'\n./measure.py\nMSG", d),  # tabs, . and - in the path
            (" true ;  git commit -F - <<'MSG'\n./measure.py\nMSG", d),
            # the fleet's real form (replay): git add <paths> && git commit -F - <<'MSG'
            ("git add src/a_test.py b/c.txt && git commit -q -F - <<'MSG'\n./measure.py\nMSG", d),
            ("cd " + d + " && git add -A && git commit -F - <<'MSG'\n./measure.py\nMSG", d),
            ("git\tadd\tx\n git commit -F - <<'MSG'\n./measure.py\nMSG", d),
            ("cd " + d + "\ntrue\ngit commit -F - <<'MSG'\n./measure.py\nMSG", d),
            ("git commit -F - <<'MSG'   \n./measure.py\nMSG", d),  # trailing blanks after the operator
            ("cd " + d + " && bash " + AM + " dave viktor - <<'M'\n./measure.py\nM", d),  # absolute: any cd
            ("curl -s -X POST localhost:3420/api/messages --data-binary @- <<'J'\n./measure.py\nJ", d),
            # mutation round 1: the operator's forms, the command's prefixes, the terminator only as a whole line
            ("git commit -F - <<-'MSG'\n\t./measure.py\n\tMSG", d),
            ("git commit -F - << 'MSG'\n./measure.py\nMSG", d),
            ("git commit -F - <<\t\"MSG\"\n./measure.py\nMSG", d),
            ("git commit --file=- <<'MSG'\n./measure.py\nMSG", d),
            ("git tag -a v1 --file - <<'MSG'\n./measure.py\nMSG", d),
            ("cd " + d + " && git commit -F - <<'MSG'\n./measure.py\nMSG", d),
            ("cd " + d + "; git commit -F - <<'MSG'\n./measure.py\nMSG", d),
            ("true | git commit -F - <<'MSG'\n./measure.py\nMSG", d),
            ("git commit -F - <<'MSG'\nfix the MSG parser\n./measure.py\nMSG", d),
            # Viktor 42695 HIGH 1 fix (blank on the raw text): a body that really ends at its first terminator line
            ("git commit -F - <<'MSG'\nx\ny\nMSG", d),
            ("git commit -F - <<'MSG'\nfix the path ./measure.py in the note\nMSG", d),
            ("git commit -F - <<'MSG'\nx\\\n./measure.py\nMSG", d),  # a body line ending in \ joins nothing in bash
            # card fae0712e: a separator inside a data command's quoted argument is no command boundary (the old gate
            # blocked these: a false block), nor an escaped one; a data command inside a substitution too
            ("echo 'x; ./measure.py'", d),
            ('echo "x; ./measure.py"', d),
            ('printf "%s\\n" "a | ./measure.py"', d),
            ("grep -n 'x; ./measure.py' notes.py", d),
            ('echo "line\n./measure.py"', d),
            ("echo 'a' 'b && ./measure.py'", d),
            ('echo x\\;./measure.py', d),
            ('test -f "a;./measure.py"', d),
            ("grep -v 'x; ./measure.py' notes.py", d),
            ("echo 'x; ./measure.py' || bash", d),  # || and && pass no output
            ("echo 'x; ./measure.py' " + '$(true)' * 64, d),  # LEX_MAX_SUBSTS substitutions: still the lexer path
            ('grep -c bash ./measure.py', d),  # a -c before the shell word is no shell's -c (mutant shell_any_order)
            # The shared lexer's own rules, each pinned here by a lexer mutant it kills (card fae0712e, Viktor 42697
            # cond. 3; work/fae0712e/lexmut/gateprobe.py): a " MSG" line is body, not the terminator (p02-delim-strip),
            # and a # after an escaped blank is word text, so the quote it opens hides the rest (p06-comment-after-escape).
            ("git commit -F - <<'MSG'\n MSG\npython3 measure.py\nMSG", d),
            ("echo 'x' \\ #'; python3 measure.py'", d),
            # the same lexer rules, regression rows for the allow paths (no lexer mutant flips them today)
            ("git commit -F - <<-'MSG'\n\tpython3 measure.py\n\tMSG", d),
            ("echo $'\\'' 'python3 measure.py'", d),
            ("echo \"$(( (1) ))\" 'python3 measure.py'", d),
            ('echo $"python3 measure.py"', d),
            ("echo 'python3 measure.py' \\\n'x'", d),
            # card 74586987: only a pipeline that feeds a shell on stdin, only that pipeline, only the words before it
            ('echo ./measure.py | cat', d),
            ('echo ./list.py | bash', d),
            ('echo measure.py | grep m', d),
            ('echo measure.py | tee log.txt', d),
            ('grep -l x measure.py | wc -l', d),
            ('echo hi | bash', d),
            ('echo ./measure.py; echo hi | bash', d),
            ('echo ./measure.py\necho hi | bash', d),
            ('echo ./measure.py && echo hi | bash', d),
            ('echo hi | bash; echo ./measure.py', d),
            ('echo hi | bash ./measure.py.txt', d),
            ('(echo ./measure.py); echo hi | bash', d),  # the group ends an earlier command, not this pipeline
            ('{ echo ./measure.py; }; echo hi | bash', d),
            ('echo ./measure.py >| bash', d),  # noclobber redirection, no pipe
            ('echo ./measure.py || bash', d),  # an or-list, no pipe
            ('echo ./measure.py | bashful', d),
            ('echo ./measure.py | source ./notes.py', d),  # source a file: no stdin reader
            ('echo ./measure.py | source /dev/stdin.bak', d),
            # replay r2 (a card comment of this card blocked as secret-read): prose in the body of a quoted heredoc
            # into a data recipient is no pipeline, with steps before it the data-heredoc walk does not take (ID=)
            ('T="Authorization: Bearer x"; ID=$(curl -s -H "$T" http://h/k | python3 -I -c \'print(1)\')\n'
             'curl -s -X POST "http://h/k/$ID/c" -H "$T" --data-binary @- <<\'JSON\'\n'
             '{"content":"unquoted echo ' + fix('s3curity') + ' dump-keychain | bash, echo ./measure.py | bash"}\n'
             'JSON', d),
            ("git commit -F - <<'MSG'\nfix: echo " + fix('s3curity') + " dump-keychain | bash is read now\nMSG", d),
            ("curl -d @- http://h <<'J'\necho ./measure.py | bash\nJ", d),
            ("bash " + AM_ROOT + "/scripts/agent-msg.sh dave v - <<'M'\necho ./measure.py | sh\nM", d),
            ('echo ./measure.py | . /dev/stdinx', d),
            ('echo ./measure.py | dot /dev/stdin', d),
            # card e05330a4: the split redirection's target is written, not run, and an operator inside quotes, an
            # fd number before it, or a process substitution is no end of the script word
            ('python3 stat.py>regiszter.jsonl', d),
            ('python3 stat.py>out.jsonl', d),
            ('python3 stat.py "a>b"', d),
            ('python3 2>/dev/null stat.py', d),
            ('python3 stat.py<(true)', d),
            ('python3 notes.py>/dev/null', d),
            # a shell's -c (also in a cluster with e) still takes a command string: the next word is $0, not run
            ("bash -e -c 'echo hi' dump.sh", d),
            ("bash -ec 'echo hi' dump.sh", d),
            ("sh -ce 'echo hi' dump.sh", d),
            # ... unquoted too: a quoted payload's quotes end the call before dump.sh, so only these read the cluster
            # (mutation round 2: shell-rx-c-first and the class drops of its regex survived the quoted rows)
            ('bash -ec x=1 dump.sh', d),
            ('bash -Ec x=1 dump.sh', d),
            ('sh -ce x=1 dump.sh', d),
            ('bash -cE x=1 dump.sh', d),
            # ... and a -c cluster with letters after the c: its string is the code, dump.sh is $0 (Viktor 45589 R1)
            ('bash -cx "echo hi" dump.sh', d),
            ('bash -ce "echo hi"', d),
            # a -cv cluster after a non-shell word is no shell flag (grep counts, it runs nothing)
            ("grep -cv 'python3 measure.py' data.jsonl", d),
            # node's -e is code: the word after it is the code, not a file (G2 is shell-only)
            ("node -e 'console.log(1)' measure.py", d),
            # card e05330a4: none of these runs measure.py (real bash and zsh, measured): x<( is one word, \& is part of
            # the file name, an operator inside a quote spanning a blank is no cut, a quoted target is written
            ('python3 measure.py<(true)', d),
            # ... also as a path word, where no call end takes the ")" (mutation round 2, cut-no-procsub)
            ('./"dump".sh<(true)', d),
            ('./"dump".sh>(true)', d),
            # an operator in a later piece of the joined word is inside its quote (ret-always-cut), and a target after
            # a word-final > is written (split-drop-target); node: every word is judged (measured: bash, zsh run none)
            ('node ok.js>"a measure.py>b"', d),
            ('node ok.js> measure.py', d),
            ('./"dump".sh\\&;true', d),
            # an escaped & before > is part of the file name: bash runs m.py&, no file (mutation round 3, amp-k-off:
            # 0d285cbb stepped back over the \& and blocked; the fleet gate allows)
            ('python3 measure.py\\&>x', d),
            ('python3 measure.py\\&>>x', d),
            # mutation round 4: a > in single quotes is file-name text (no-sq-track cut there and blocked; bash runs
            # no measure.py), and a lone > in a joined word keeps its target (join-drop-target read measure.py, the
            # target, as the script; bash writes measure.py and runs stat.py)
            ("python3 'measure.py>x'", d),
            ("python3 measure.py'>x'", d),
            ('python3 $(true x)> measure.py stat.py', d),
            # card 946937b7: a quoted argument after the script is argv data, a written target with a blank is written
            ('python3 stat.py "a b" measure.py', d),
            ('python3 stat.py > "measure.py x"', d),
            ('A="a b" python3 stat.py', d),
            ('python3 "x y.py"', d),
            ('source >"dump.sh" stat.py', d),  # the redirection's target is written, the file is stat.py
            # card 946937b7 (Viktor 45626): a here-string to a program that is no shell is data, and a quoted payload
            # that only names a script is prose; an escaped blank ends no assignment (bash sets A="x python3" and looks
            # up measure.py on PATH: no python runs)
            ("grep x <<<'python3 measure.py'", d),
            ("cat <<<'python3 measure.py'", d),
            ("python3 stat.py <<<'a b'", d),
            ("echo \"python3 -W 'a b' measure.py\"", d),
            ('git commit -m "python3 isn\'t ready"', d),
            ('A=x\\ python3 measure.py', d),
            # card 946937b7 (Viktor 45532): the same substitutions before a harmless script, or as data
            ("echo $(true ')')measure.py", d),
            ("python3 '$(true)'stat.py", d),
            ("git log $(true ')')measure.py", d),
            ("python3 $(true ')')stat.py", d),
            ("python3 $(true ')' $(true '('))stat.py", d),
            ("python3 -c 'print(1)' $(true ')')", d),
            ("./$(true ')')stat.py", d),
            ("echo ./$(true ')')dump.sh", d),
            ("./stat.py $(true ')') dump.sh", d),
            # card 946937b7 (Viktor 45543): past the lexer's bounds, a call with no "(" and no backtick before its
            # cut keeps its old reading: no block
            ('python3 stat.py; echo ' + '$(true)' * 70, d),
            ('echo ' + '$(true)' * 70, d),
            ('x=$(python3 stat.py) ; echo ' + '$(true)' * 70, d),
            ('echo ' + '$(true)' * 70 + '; python3 stat.py', d),
            ('python3 stat.py; echo ' + '$(true)' * 59 + ' ' + 'a' * 60000, d),
            ('python3 "x measure.py>y"', d),
            ('python3 stat.py "a b>c"', d),
            ('python3 stat.py>"a b"', d),
            ("python3 'x y'>measure.py", d),
            ('python3 stat.py "$(true x)" >/dev/null', d),
            # card 946937b7 (replay of 59811cb0: 916 fleet commands blocked): the command as written lexes cleanly,
            # only the gate's own view of it (a payload's quotes) has an odd quote; the old reading stands
            ('python3 -c "import sys; print(\'a b\')" && python3 stat.py "a b"', d),
            ("python3 -c 'print(1)' && python3 stat.py \"it's x\"", d),
            # ... and where the call's own words do not lex alone either (mutation round 3: _CMD_READ always False
            # survived): only the reading of the command as written lets them pass
            ('nohup sh -c "python3 stat.py x > /tmp/k.log 2>&1" > /dev/null 2>&1 &', d),
            ("TMPDIR=/x sh -c 'unset TMPDIR; python3 stat.py x' 2>&1 | tail -3", d),
            ("python3 -c \"open('c.txt','w').write('python3 evil\\\\\\\\.py\\n./\\\"' + 'a'*50 + '\\\"\\n')\" && head -c 40 c.txt",
             d),
            # ... and past the lexer's bounds, a call whose own words lex alone keeps their reading (mutation round 3:
            # _call_alone_groups always None survived)
            ("python3 -c 'print(1)' && python3 stat.py \"it's x\"; echo" + ' $(true)' * 66, d),
            ("python3 stat.py \"it's x\"; echo" + ' $(true)' * 66, d),
            # ... the same for a substitution that opens in the gate's view of a call (mutation round 3b:
            # the _CMD_READ guard of the substitution fail-closed survived)
            ('C=\'export -- A=1; /usr/bin/printenv A\'; echo "bash $(/bin/bash -c "$C") zsh $(/bin/zsh -c "$C")"', d),
        ]
        for cmd, cwd in block:
            code, err = bash_in(cmd, cwd)
            if code != 2 or 'KULCSKARIKA-KAPU' not in err:
                fails.append(f'script: should block (got {code}): {cmd[:80]!r}')
            elif 'acct' in err or "'svc'" in err:
                fails.append(f'script: block message echoes the file: {cmd[:80]!r}')
        for cmd, cwd in allow:
            code, err = bash_in(cmd, cwd)
            if code != 0:
                fails.append(f'script: should allow (got {code}): {cmd[:80]!r} {err[:120]}')
        # card 74586987: with the hook's stdout a FILE, /dev/stdout is no script of the command (it took /dev/fd/1 for
        # a regular file, could not read it, and blocked with PermissionError; found by the fleet replay)
        # write-only, as the replay worker's file was (mutation r2 d1: a read-write file let the gate read /dev/fd/1,
        # empty, and allow, so turning the /dev skip off survived)
        with open(os.path.join(d, 'hook-stdout.txt'), 'wb') as out:
            p = subprocess.run([sys.executable, '-I', HOOK], input=json.dumps(
                {'tool_name': 'Bash', 'tool_input': {'command': 'echo x | tee /dev/stdout | bash'}, 'cwd': d}).encode(),
                stdout=out, stderr=subprocess.PIPE, env={'PATH': '/usr/bin:/bin'}, timeout=20)
        if p.returncode != 0:
            fails.append(f'script: /dev/stdout with a file stdout should allow (got {p.returncode}): '
                         f'{p.stderr.decode()[:160]}')
        # the cap (MAX_SCRIPTS = 10): ten clean files pass, an eleventh blocks instead of going unread
        for i in range(11):
            w(f'c{i}.py', 'print(1)\n')
        code, _ = bash_in(' ; '.join(f'python3 c{i}.py' for i in range(10)), d)
        if code != 0:
            fails.append(f'script: ten clean files should pass (got {code})')
        code, err = bash_in(' ; '.join(f'python3 c{i}.py' for i in range(10)) + ' ; python3 measure.py', d)
        if code != 2 or 'script-too-many' not in err:
            fails.append(f'script: an eleventh file should block, not go unread (got {code})')
        # fail-closed: a file the gate cannot read (PermissionError) blocks, it is not skipped
        locked = w('locked.py', 'print(1)\n')
        os.chmod(locked, 0)
        try:
            if os.access(locked, os.R_OK):  # root reads it anyway: the case cannot be built
                fails.append('script: locked.py is readable (running as root?), fail-closed case not tested')
            else:
                code, err = bash_in('python3 locked.py', d)
                if code != 2 or 'PermissionError' not in err:
                    fails.append(f'script: an unreadable file should block fail-closed (got {code})')
        finally:
            os.chmod(locked, 0o600)
        # the time budget: past it the gate blocks instead of reading on (a timed-out hook does not block).
        # The env seam can only lower the budget: 0 blocks a clean file, 999 does not raise it past SCRIPT_BUDGET_S.
        def bash_env(cmd, cwd, extra):
            env = {'PATH': '/usr/bin:/bin', **extra}
            p = subprocess.run([sys.executable, '-I', HOOK], capture_output=True, text=True, env=env, timeout=20,
                               input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}, 'cwd': cwd}))
            return p.returncode, p.stderr
        code, err = bash_env('python3 c0.py', d, {'KEYCHAIN_GATE_SCRIPT_BUDGET_S': '0'})
        if code != 2 or 'script-too-slow' not in err:
            fails.append(f'script: past the budget a clean file should block (got {code})')
        code, _ = bash_env('python3 c0.py', d, {'KEYCHAIN_GATE_SCRIPT_BUDGET_S': 'x'})
        if code != 0:
            fails.append(f'script: a malformed budget falls back to the default (got {code})')
        code, _ = bash_env('ls ' + d, d, {'KEYCHAIN_GATE_SCRIPT_BUDGET_S': '0'})
        if code != 0:
            fails.append(f'script: no script file, the budget does not apply (got {code})')
        # card d11364a4: a payload with a quote in it is read again only inside the budget; past it the gate blocks
        code, err = bash_env("bash -c '\"x\" y'", d, {'KEYCHAIN_GATE_SCRIPT_BUDGET_S': '0'})
        if code != 2 or 'payload-too-slow' not in err:
            fails.append(f'script: a quoted payload past the budget blocks (got {code} {err[-80:]!r})')
        code, _ = bash_env("bash -c 'ls -la'", d, {'KEYCHAIN_GATE_SCRIPT_BUDGET_S': '0'})
        if code != 0:
            fails.append(f'script: a payload without a quote is not read again, the budget does not apply (got {code})')
        # ten 1 MB files of newlines (6.6 s unbudgeted, 2026-11-13): decided well inside the 10 s hook timeout,
        # and the seam cannot raise the budget (999 is capped at SCRIPT_BUDGET_S)
        for i in range(10):
            w(f'n{i}.sh', '\n' * (1024 * 1024))
        import time as _t
        t = _t.monotonic()
        code, err = bash_env(' ; '.join(f'bash n{i}.sh' for i in range(10)), d,
                             {'KEYCHAIN_GATE_SCRIPT_BUDGET_S': '999'})
        took = _t.monotonic() - t
        if took > 8:
            fails.append(f'script: ten 1 MB files took {took:.1f} s (hook timeout 10 s)')
        if code not in (0, 2) or (code == 2 and 'script-too-slow' not in err):
            fails.append(f'script: ten 1 MB clean files: want pass or script-too-slow (got {code}) {err[:120]}')
        # the seam itself: lower-only, malformed = default, negative = 0
        probe = ('import importlib.util as u,sys; s=u.spec_from_file_location("g",sys.argv[1]); m=u.module_from_spec(s);'
                 ' s.loader.exec_module(m); print(m.script_budget())')
        for val, want in [('999', '4.0'), ('0.5', '0.5'), ('x', '4.0'), ('-3', '0.0'), ('inf', '4.0'), ('nan', '4.0')]:
            p = subprocess.run([sys.executable, '-I', '-c', probe, HOOK], capture_output=True, text=True, timeout=20,
                               env={'PATH': '/usr/bin:/bin', 'KEYCHAIN_GATE_SCRIPT_BUDGET_S': val})
            if p.stdout.strip() != want:
                fails.append(f'script: budget seam {val!r} -> {p.stdout.strip()!r}, want {want}')
        # card e05330a4 (mutation survivor split-maxargs-off): the redirection split stops past MAX_ARGS words and hands
        # the rest back as written (the walk blocks past MAX_ARGS anyway); without the stop only time told it apart
        split = ('import importlib.util as u,sys; s=u.spec_from_file_location("g",sys.argv[1]); m=u.module_from_spec(s);'
                 ' s.loader.exec_module(m); r=m.split_redirections(["a>b"]*100, {}); print(len(r), r[-1])')
        p = subprocess.run([sys.executable, '-I', '-c', split, HOOK], capture_output=True, text=True, timeout=20,
                           env={'PATH': '/usr/bin:/bin'})
        if p.stdout.strip() != '133 a>b':
            fails.append(f'script: split past MAX_ARGS -> {p.stdout.strip()!r}, want 133 a>b')
        # card d11364a4 (mutation survivor): past HALF the budget no payload is read again (one more read costs about
        # what the outer text did, and a timed-out hook does not block); 3 s of the default 4 s gone, in-process
        half = ('import importlib.util as u,sys; s=u.spec_from_file_location("g",sys.argv[1]); m=u.module_from_spec(s);'
                 ' s.loader.exec_module(m); m.T0 -= 3.0; print(",".join(m.hits(sys.argv[2])) or "-")')
        for cmd, want in [("bash -c '\"x\" y'", 'payload-too-slow'), ("bash -c 'ls -la'", '-')]:
            p = subprocess.run([sys.executable, '-I', '-c', half, HOOK, cmd], capture_output=True, text=True,
                               timeout=20, env={'PATH': '/usr/bin:/bin'})
            if p.stdout.strip() != want:
                fails.append(f'script: past half the budget {cmd!r} -> {p.stdout.strip()!r}, want {want}')
        # card d11364a4 (mutation survivor): an escaped quote opens no payload in hits(), so it cannot swallow the
        # payload after it. The hook judges each command on its own too, so the hook blocks either way (measured,
        # work/d11364a4/kill-probe-hook.py); this pins hits() itself.
        inproc = half.replace('m.T0 -= 3.0; ', '')
        cmd = fix("eval \\'x ; bash -c '\"s3curity\" dump-keychain'")
        p = subprocess.run([sys.executable, '-I', '-c', inproc, HOOK, cmd], capture_output=True, text=True,
                           timeout=20, env={'PATH': '/usr/bin:/bin'})
        if 'secret-read' not in p.stdout.strip().split(','):
            fails.append(f'script: hits() after an escaped quote {cmd!r} -> {p.stdout.strip()!r}, want secret-read')
        # card fae0712e: the gate loads the shared lexer from its own scripts/lib (by path, under python3 -I); a text
        # with a lexer problem gives None (the old path)
        probe_l = probe.replace('print(m.script_budget())', 'print(m.shell_lex is not None, m.lex_or_none("echo a")'
                                ' is not None, m.lex_or_none("echo \'a") is None)')
        p = subprocess.run([sys.executable, '-I', '-c', probe_l, HOOK], capture_output=True, text=True, timeout=20,
                           env={'PATH': '/usr/bin:/bin'})
        if p.stdout.strip() != 'True True True':
            fails.append(f'script: the shared lexer is not loaded or not fail-closed: {p.stdout.strip()!r} {p.stderr[-200:]!r}')
        # card 946937b7 (Viktor 45626, mutation m08 survived): without the lexer (not loaded), a substitution with a
        # quoted ")" before the script still blocks (bash ran dump.sh); the hook test above always has the lexer
        nolex = half.replace('m.T0 -= 3.0; ', 'm.shell_lex = None; ').replace('m.hits(sys.argv[2])',
                                                                             'm.script_hits(sys.argv[2], sys.argv[3])')
        for cmd in ("./$(true ')')dump.sh", './$(true ")")dump.sh'):
            p = subprocess.run([sys.executable, '-I', '-c', nolex, HOOK, cmd, d], capture_output=True, text=True,
                               timeout=20, env={'PATH': '/usr/bin:/bin'})
            if p.stdout.strip() in ('', '-'):
                fails.append(f'script: without the lexer {cmd!r} should block -> {p.stdout.strip()!r} {p.stderr[-120:]!r}')
        # card aeee72df: hits() itself, where the hook blocks on another rule (script-inline after ||, the 4096
        # window): a <<< with no word after it raises nothing, || is no pipe into a shell, |& is one (zsh, bash 4)
        S3 = fix('s3curity')
        for cmd, want in [('bash <<< ', '-'), ('bash <<< ' * 20000, '-'), ('bash <<< "' + 'a\\"b ' * 100000 + '"', '-'),
                          ("echo '\"%s\" dump-keychain' || bash" % S3, '-'),
                          ("echo '\"%s\" dump-keychain' | bash" % S3, 'secret-read'),
                          ("echo '\"%s\" dump-keychain' |& bash" % S3, 'secret-read')]:
            p = subprocess.run([sys.executable, '-I', '-c', inproc, HOOK, cmd], capture_output=True, text=True,
                               timeout=20, env={'PATH': '/usr/bin:/bin'})
            if p.stdout.strip() != want:
                fails.append(f'script: hits({cmd[:40]!r}) -> {p.stdout.strip()[:60]!r} {p.stderr[-80:]!r}, want {want}')
        # more directories than MAX_BASES (32) before a script: blocks instead of leaving the rest unresolved
        code, err = bash_in('cd a && ' * 40 + 'python3 list.py', d)
        if code != 2 or 'script-too-many' not in err:
            fails.append(f'script: 40 cd before a script should block (got {code})')
        code, _ = bash_in('cd a && ' * 40 + 'ls', d)
        if code != 0:
            fails.append(f'script: 40 cd without a script should pass (got {code})')
        # ~ is the home directory (Viktor 41715 LOW c)
        code, _ = bash_env('python3 ~/measure.py', None, {'HOME': d})
        if code != 2:
            fails.append(f'script: python3 ~/measure.py should block (got {code})')
        # Viktor 41715 MEDIUM: the quadratic assignment branch. Padding in the command or in the file must not carry
        # the gate past the hook limit; each case is decided in under 2 s, and a read behind the padding still blocks.
        w('eq.py', '=' * (1024 * 1024))
        w('eqs.py', '=/' * (512 * 1024))
        w('min.js', 'a=b;c=d;' * (300 * 1024 // 8))
        w('big.py', '=' * 200000 + '\n' + open(os.path.join(d, 'measure.py'), encoding='utf-8').read())
        # (the clean padding sits behind `; echo`: as python3's own word it would run past ARGS_WINDOW and block)
        timed = [
            ('python3 x ; echo ' + '=/' * 50000, 0),
            ('python3 x ; echo ' + '=' * 100000, 0),
            ('node x ' + '=/' * 50000, 2),  # python3: x is the script, the rest data (31045f4d)
            ('python3 x ' + '=/' * 60000 + ' ; ' + S + ' dump-keychain', 2),
            ('python3 eq.py', 0), ('python3 eqs.py', 0), ('node min.js', 0), ('python3 big.py', 2),
        ]
        for cmd, want in timed:
            t = _t.monotonic()
            code, err = bash_in(cmd, d)
            took = _t.monotonic() - t
            if code != want or took > 2:
                fails.append(f'script: padding case {cmd[:24]!r}: want rc {want} under 2 s, got {code} in {took:.1f} s')
        # the watchdog: a slow scan is cut and blocks (not the hook timeout that would let it through)
        w('nl.sh', '\n' * (1024 * 1024))
        code, err = bash_env('bash nl.sh', d, {'KEYCHAIN_GATE_WATCHDOG_S': '0.01'})
        if code != 2 or 'watchdog' not in err:
            fails.append(f'script: watchdog 0.01 s on a 1 MB scan should block (got {code})')
        probe = probe.replace('script_budget', 'watchdog_s')
        for val, want in [('999', '6.0'), ('2', '2.0'), ('0', '0.001'), ('-1', '0.001'), ('nan', '6.0'), ('x', '6.0')]:
            p = subprocess.run([sys.executable, '-I', '-c', probe, HOOK], capture_output=True, text=True, timeout=20,
                               env={'PATH': '/usr/bin:/bin', 'KEYCHAIN_GATE_WATCHDOG_S': val})
            if p.stdout.strip() != want:
                fails.append(f'script: watchdog seam {val!r} -> {p.stdout.strip()!r}, want {want}')
        # Viktor 41756 INFO 4 (w5): the watchdog leaves with os._exit, which no except clause can catch (sys.exit's
        # SystemExit could be swallowed)
        probe_w = ('import importlib.util as u,sys; s=u.spec_from_file_location("g",sys.argv[1]); m=u.module_from_spec(s);'
                   ' s.loader.exec_module(m)\ntry:\n    m.on_watchdog(14, None)\nexcept BaseException:\n    print("caught")')
        p = subprocess.run([sys.executable, '-I', '-c', probe_w, HOOK], capture_output=True, text=True, timeout=20,
                           env={'PATH': '/usr/bin:/bin'})
        if p.returncode != 2 or 'caught' in p.stdout:
            fails.append(f'script: the watchdog exit must not be catchable (rc {p.returncode}, {p.stdout.strip()!r})')
        # Viktor 41756 LOW 1: words past MAX_ARGS (64), or a command past ARGS_WINDOW, block instead of going unread
        too_many = [
            ('python3 ' + '-B ' * 64 + 'measure.py', d),
            ('node ' + '-B ' * 12 + 'measure.py ' + 'a ' * 60, d),
            ('python3 ' + 'A' * 5000 + ' measure.py', d),
            ('node list.py ' + ' '.join(f'a{i}' for i in range(64)), d),  # python3: argv data (31045f4d)
            ('cat ' + 'x ' * 70 + 'measure.py | python3', d),
            ('cat ' + 'x ' * 64 + 'list.py | python3', d),  # 65 words
            ('python3 ' + 'A' * 4096, d),  # one char past the window
        ]
        for cmd, cwd in too_many:
            code, err = bash_in(cmd, cwd)
            if code != 2 or 'script-too-many-args' not in err:
                fails.append(f'script: past MAX_ARGS/ARGS_WINDOW should block (got {code}): {cmd[:60]!r}')
        # Viktor 41790 INFO 3: the message says why (the word count and the limit, or the window)
        _, err = bash_in('node list.py ' + ' '.join(f'a{i}' for i in range(69)), d)
        if '70 szó' not in err or 'MAX_ARGS 64' not in err:
            fails.append(f'script: too-many-args message should name 70 words and MAX_ARGS 64: {err[:200]!r}')
        _, err = bash_in('python3 ' + 'A' * 5000, d)
        if '4096' not in err:
            fails.append(f'script: window message should name the 4096-char window: {err[:200]!r}')
        # past the bound a clean payload passes (it is read, not blocked blind; Viktor 41859 A)
        for cmd in ["bash -c" + " -x" * 5 + " 'echo hi'", "watch" + " -x" * 5 + " 'echo hi'",
                    "tmux new" + " -e A=1" * 7 + " -e" + " 'echo hi'"]:  # the bounds + 1: 5, 5, 15
            code, err = bash_in(cmd, d)
            if code != 0:
                fails.append(f'script: past the payload bound a clean payload should pass (got {code}): {cmd[:60]!r}')
        for cmd in ["watch" + " -x" * 4 + " 'echo hi'", "tmux new" + " -e A=1" * 7 + " 'echo hi'"]:  # 4, 14
            code, err = bash_in(cmd, d)
            if code != 0:
                fails.append(f'script: inside the payload bound should pass (got {code}): {cmd[:60]!r}')
        # source past MAX_ARGS / ARGS_WINDOW with a real first file: the rest is not all read, so it blocks
        for cmd in ['source runner.sh ' + 'a ' * 70 + 'measure.py', 'source runner.sh ' + 'A' * 5000]:
            code, err = bash_in(cmd, d)
            if code != 2 or 'script-too-many-args (source' not in err:
                fails.append(f'script: source past MAX_ARGS/window should block (got {code}): {cmd[:40]!r}')
            elif ('MAX_ARGS 64' if 'a a' in cmd else '4096') not in err:
                fails.append(f'script: source too-many-args message should say why: {err[:200]!r}')
        # past MAX_TRIES on the sourced file itself: blocks, not "no file, skip the rest" (32 directories x 124
        # missing words + 1 = 4000 lookups, so runner.sh's first lookup crosses 4000)
        code, err = bash_in('cd a && ' * 31 + ' ; '.join('node ' + ' '.join(f'm{j}' for j in range(62))
                                                          for _ in range(2)) + ' ; python3 mx ; source runner.sh measure.py', d)
        if code != 2 or 'script-too-many' not in err:
            fails.append(f'script: past MAX_TRIES on a sourced file should block (got {code})')
        code, _ = bash_in('source nonexist.sh ' + 'a ' * 70, d)
        if code != 0:
            fails.append(f'script: source of no file with many words should pass (got {code})')
        # the new payload positions stay linear (Viktor 41790: his first try ran past 5 s on ' -exec' x 12 000)
        payload_redos = [
            # past the bound the payload is read, not blocked: a clean one passes, fast (Viktor 41859 A)
            ('bash -c' + ' -x' * 20000 + " 'a'", 0), ('eval ' * 20000, 0), ('watch -n 1 ' * 10000, 0),
            ('tmux new ' + 'a ' * 20000, 0), ('tmux new a ' * 10000, 0), (' -exec' * 12000, 0), ('-c ' * 30000, 0),
            ('watch ' + '-n ' * 20000, 0), ('tmux new a ' * 3, 0), ('bash -c ' * 30000 + "'", 0),
            # bash as an interpreter whose words run past the window: script-too-many-args, as on 980fb40a
            ('bash ' * 30000, 2), ('bash' + ' -o x' * 20000 + " -c 'a'", 2), ("watch" + " -x" * 30000 + " 'a'", 0), ('tmux new ' * 20000 + "'", 0),
            ('sh -c "' * 20000, 0), ('bash' + " -c 'a'" * 30000, 0), ('watch -x -x -x -x -x ' * 20000 + "'", 0), ('bash -c -o pipefail ' + "'a' " * 20000, 0), ('do shell script \\' * 20000, 0),
            ('do shell script ' * 10000, 0), ('os.system(' * 20000, 0), ('"node" ' * 20000, 2),  # past MAX_ARGS: blocks, fast
            # card fae0712e: the lexer's bounds (LEX_MAX_SUBSTS, LEX_MAX_WORK). Just inside them the lexer path runs
            # (and masks the data command's quotes), past them the old path; both fast. 64 nested unclosed `f(` before
            # 10 000 chars took 2.5 s in segments_of() unbounded, 1 000 x `f(` 255 s.
            ('echo $(true) ' * 64 + 'x ' * 20000, 0), ('echo `true` ' * 64 + "'a; ./measure.py' " * 2000, 0),
            ('f(' * 64 + ' x' * 5000, 0), ('f(' * 1000, 0), ('$(' * 64 + ')' * 64, 0),
            # card 74586987: the pipeline walk stays linear: a chain of groups, many pipes after one stop, nested
            # groups each piped again, a long blank run before a "}"; a repeated word is looked up once; past MAX_TRIES
            # distinct lookups it blocks (fail-closed), fast. ('(x)|bash ' * 10000 blocked on the base too: bash's words)
            ('(x)|bash ' * 10000, 2), ('echo a ' + '| bash ' * 20000, 0), ('(' * 5000 + 'a' + ')|bash' * 5000, 0),
            ('true;' + ' ' * 50000 + '} | bash' * 5000, 0), ('{ a; }|bash;' * 10000, 0), ('echo ' + 'a ' * 20000 + '| bash', 0),
            ('echo ' + ' '.join('a%d' % i for i in range(5000)) + ' | bash', 2),
        ]
        for cmd, want in payload_redos:
            t = _t.monotonic()
            code, _ = bash_in(cmd, d)
            took = _t.monotonic() - t
            if code != want or took > 2:
                fails.append(f'script: payload padding {cmd[:24]!r}: want rc {want} under 2 s, got {code} in {took:.1f} s')
        # Viktor 41756 INFO 4 (s1): past MAX_TRIES (4000) path lookups the gate blocks. 31 directories x 3 calls x
        # 60 missing words = 5580 lookups, no file found anywhere.
        code, err = bash_in('cd a && ' * 30 + ' ; '.join('node ' + ' '.join(f'm{j}' for j in range(60))
                                                          for _ in range(3)), d)
        if code != 2 or 'script-too-many' not in err:
            fails.append(f'script: past MAX_TRIES lookups should block (got {code})')
        # Viktor 41756 INFO 4 (s11): the per-call window keeps many calls linear (the rest of the text per call
        # was quadratic)
        t = _t.monotonic()
        code, _ = bash_in('python3 x;' * 30000, d)
        took = _t.monotonic() - t
        if took > 2:
            fails.append(f'script: 30 000 interpreter calls took {took:.1f} s (want under 2 s)')
        corpus_fails, corpus_n = corpus_cases(d)
        fails += corpus_fails
        return fails, len(block) + len(allow) + 8 + 3 + len(timed) + 2 + 1 + len(too_many) + 2 + 2 + 3 + 2 + 2 + 1 + 1 + len(payload_redos) + 6 + corpus_n + 1 + 1


def corpus_cases(d):
    """Card fae0712e (Viktor 42697): the shared attack corpus, scripts/hooks/shell-attack-corpus.json, its keychain
    column. `d` is script_cases' fixture dir (measure.py reads the keychain, the agent-msg.sh look-alikes and the
    planted bin/ programs run their stdin), the corpus's "script" fixtures. A row whose script RAN in a real shell
    (oracle) must be a block row; an `open` row is a known gap and must still fail (flip it when it is fixed)."""
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shell-attack-corpus.json'), encoding='utf-8') as f:
        rows = json.load(f)['rows']
    fails = []
    n = 0
    for r in rows:
        want = r['want']['keychain']
        if r['oracle'] == 'ran' and want != 'block':
            fails.append(f"corpus {r['id']}: the script ran (oracle) but want.keychain is {want}")
        if want not in ('block', 'allow'):
            continue
        n += 1
        cmd = r['cmd'].replace('{DIR}', d).replace('{AM}', AM)
        cwd = d if r['cwd'] == '{DIR}' else AM_ROOT
        code, err = bash_in(cmd, cwd)
        got = 'block' if code == 2 and 'KULCSKARIKA-KAPU' in err else 'allow' if code == 0 else f'exit {code}'
        if r.get('open'):
            if got == want:
                fails.append(f"corpus {r['id']}: open gap ({r['open']}) now gives {want}: drop `open` in the corpus")
        elif got != want:
            fails.append(f"corpus {r['id']}: want {want}, got {got}: {cmd[:80]!r}")
    return fails, n + 1


def main():
    fails = []
    for cmd in map(fix, BLOCK):
        code, err = bash(cmd)
        if code != 2 or 'KULCSKARIKA-KAPU' not in err:
            fails.append(f'should block (got {code}): {cmd!r}')
        elif cmd in err or 'Claude Code-credentials' in err or 'example.test' in err:
            fails.append(f'block message echoes the command: {cmd!r}')
    for cmd in map(fix, ALLOW):
        code, err = bash(cmd)
        if code != 0:
            fails.append(f'should allow (got {code}): {cmd!r} {err[:120]}')
    # card 31045f4d (Klodel, aeee72df): the deny says what to do with a false positive
    code, err = bash(fix(BLOCK[0]))
    if 'Ha hamis pozitív' not in err or 'állj meg és szólj' not in err:
        fails.append('the block message lacks the false-positive rule (Klodel, card aeee72df)')
    # Not a Bash call / malformed input: allowed, never crashes.
    for payload in ['', 'not json', json.dumps({'tool_input': None}), json.dumps({'tool_input': {'command': None}}),
                    json.dumps({'tool_input': {'file_path': '/tmp/x'}}), json.dumps([1, 2])]:
        code, _ = run(payload)
        if code != 0:
            fails.append(f'non-Bash input should pass (got {code}): {payload!r}')
    # ReDoS (Viktor 30044): many ambiguous wrapper tokens before the call must still block, fast (the old POSITION
    # never returned at 26 x "env a=b ", and a hook that times out does not block).
    for cmd in [('env a=b ' * 30) + '; ' + fix('s3curity') + ' dump-keychain', ('env a=b ' * 60) + 'z',
                'echo ' + 'a=b ' * 2000,
                # card bc009036: runs of positions that rescanned the rest of the command (6 000 newlines took 10 s,
                # 12 000 " -exec" 112 s, 60 000 quotes 13 s before the fix)
                '\n' * 60000, ' -exec' * 12000, '"' * 60000, '\t\n' * 30000,
                '\n' * 30000 + fix('s3curity') + ' dump-keychain',
                # python -m parsing: long flag runs after an interpreter
                'python3' + ' -u' * 20000, ('python3 -m' + ' -x=a' * 10000), 'python3 -mx;' * 6000]:
        # 20 000 x " -u": past MAX_ARGS, so it blocks unread (Viktor 41756 LOW 1); the case still checks the time
        want = 2 if fix('s3curity') in cmd or cmd.startswith('python3 -u -u') else 0
        try:
            p = subprocess.run([sys.executable, '-I', HOOK], capture_output=True, text=True, timeout=5,
                               input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}}),
                               env={'PATH': '/usr/bin:/bin'})
            if p.returncode != want:
                fails.append(f'redos case: want {want}, got {p.returncode}: {cmd[:40]!r}...')
        except subprocess.TimeoutExpired:
            fails.append(f'redos case timed out (5 s): {cmd[:40]!r}...')
    # card 3085a683: the wrapper walk is linear (a walk per wrapper, a wrapper right after another in the same pass);
    # a walk past MAX_ARGS words blocks ('wrapper-unread'): 64 words of flags and arguments pass, 65 block
    sec = fix('s3curity') + ' dump-keychain'
    # (`env -u env -u ...` runs no command at all; in `timeout -s K timeout ...` each wrapper is a word of the one
    # before: 0 is right there)
    wrap_timed = [('sudo -u a ' * 20000 + 'z', 0), ('sudo -u a ' * 20000 + sec, 2), ('timeout -s K ' * 20000, 0),
                  ('ssh -o a ' * 20000, 0), ('env -u ' * 30000, 0), ('sudo -p "' * 20000, 2),
                  ('sudo' + ' -u a' * 20000 + ' ls', 2), ('ssh' + ' -o a' * 20000 + ' h ls', 2),
                  # past the cap after an opening quote (a secret-rule position only): the secret path blocks too
                  ('echo "sudo' + ' -u a' * 40 + ' x"', 2),
                  # Viktor 41970 LOW 3: a quoted flag word made finditer re-walk the chain from every wrapper
                  ('sudo -u "a b" ' * 4000 + 'z', 0), ("env -u 'a b' " * 4000 + 'z', 0),
                  ('sudo -p "a b" ' * 16000 + 'z', 0), ('sudo -u "a b" ' * 4000 + sec, 2),
                  # card 04d67b39: git and xcrun are walked and always marked
                  ('git ' * 30000 + 'status', 0), ('git -c a=b ' * 10000 + fix('cr3dential fill'), 2),
                  ('xcrun git ' * 15000 + 'status', 0), 
                  # card 49d58372: one walk per simple command, one window per config call
                  ('HOME=/x ' * 20000 + 'git fetch', 2), ('export HOME=/x; ' * 20000 + 'ls', 0), ('HOME=/x ls; ' * 20000 + 'git fetch', 0),
                  ('git config ' * 20000, 0), ('(config ' * 20000, 0), ('env -u A ' * 20000 + 'git fetch', 2), ('a=b ' * 70 + 'HOME=/x git fetch', 2), ('a=b ' * 70 + 'ls', 0),
                  (('GIT_CONFIG_PARAMETERS=' + 'x' * 100 + ' ') * 20000, 0),  # each value read once (main: 6 s watchdog)
                  ('GIT_CONFIG_PARAMETERS=x ' * 20000 + 'include.path=/e git fetch', 2),
                  ('HOME=/x git -c x= ; ' * 20000, 2), ('HOME=/x git -c y ' + "'a' " * 20000, 2),
                  ("HOME=/x git -c y '" * 20000, 2), ('HOME=/x bash -c "' + 'a; ' * 20000 + 'git fetch"', 2), ('git -c include.pat ' * 20000, 0),
                  ('git' + ' -c a' * 20000 + ' status', 2),
                  # card 15896271: the redirection token reads one way (`>>x` is `>>` + `x`)
                  (' >>x' * 20000 + ' z', 0), ('>>' * 50000, 0), ('2> x ' * 20000 + sec, 2), ('> ' * 40000, 0),
                  ('sudo -u a >x ' * 10000 + sec, 2), ('lockf f ' * 20000 + 'z', 0), ('launchctl a b ' * 15000, 0),
                  ('>&2 ' * 20000 + 'z', 0), ('2>&1 ' * 20000 + sec, 2), ('&>x ' * 20000 + 'z', 0),
                  ('sudo' + ' -u a' * 32 + ' ls', 0), ('sudo' + ' -u a' * 32 + ' -E ls', 2),
                  ('sudo -u a; ' * 20000, 0), ('(sudo -u a ' * 20000, 0), ('sudo -u a ' * 20000 + 'python3 x.py', 0),
                  ('ssh h ' * 20000 + sec, 2), ('nice -n 5 sudo -u a ' * 10000 + sec, 2),
                  # card e05330a4 r3: a call in the $( ) of another is a word of it, so the windows overlap, and each
                  # open piece is scanned once (the joined word rescanned per piece ran these into the 6 s watchdog;
                  # main 0.4-2.6 s, new 1.5-3.0 s, measured under load; main blocks the last one, past MAX_ARGS).
                  # Card 946937b7 (Viktor 45543): 0 -> 2, the lexer does not read 10 000+ substitutions and a "$(" is
                  # in the call's words: fail-closed; the same 5 s cap
                  ('python3 x.py $(' * 20000, 2), ('python3 x.py a $(' * 10000, 2), ('python3 x.py>x $(' * 10000, 2)]
    # card aeee72df: the word join and the stdin walk are linear (each quote and each word once), and a <<< at the
    # very end has no word (an IndexError there blocked every such command before it was caught). The two `<<<`
    # runs past 4096 characters block on the script rules ('script-too-many-args', main too): timed here, their
    # hits() is pinned in script_cases()
    qsec = '"' + fix('s3curity') + '" dump-keychain'
    wrap_timed += [("echo " + "'a''b'" * 100000 + " | bash", 0), ("bash -c " + "'a'\\''b'" * 100000, 0),
                   ("echo " + "'a''b'" * 100000 + " '" + qsec + "' | bash", 2), ("bash <<< " * 20000, 2),
                   ("echo 'x' | bash; " * 20000, 0), ("'\"" * 50000 + ' | bash', 0), ('<<<' * 50000 + ' bash', 0),
                   ("bash -c " + "''\\''a'\\'' " * 20000 + "''\\''" + qsec.replace('"', '') + "'", 2),
                   ("echo '\"a\"' | " + "sudo -u a " * 20000 + "bash", 0), ('bash <<< "' + 'a\\"b ' * 100000 + '"', 2),
                   (_nest(6, qsec), 2), ("bash -c " + "$'\\x41' " * 40000, 0)]
    for cmd, want in wrap_timed:
        try:
            p = subprocess.run([sys.executable, '-I', HOOK], capture_output=True, text=True, timeout=5,
                               input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}}),
                               env={'PATH': '/usr/bin:/bin'})
            if p.returncode != want:
                fails.append(f'wrapper timing case: want {want}, got {p.returncode}: {cmd[:40]!r}...')
        except subprocess.TimeoutExpired:
            fails.append(f'wrapper timing case timed out (5 s): {cmd[:40]!r}...')
    # card 04d67b39: the GIT_RULES read the command, not a script file: the fleet's GitHub path, which runs
    # `git credential fill` with the helper list reset (and names it in a comment and a string), passes
    repo = os.path.dirname(os.path.dirname(os.path.dirname(HOOK)))
    if not os.path.isfile(os.path.join(repo, 'scripts', 'gh-pr.mjs')):
        fails.append('gh-pr.mjs not found next to the gate: the regression case did not run')
    else:
        code, err = bash_in('node scripts/gh-pr.mjs pr view 1', repo)
        if code != 0:
            fails.append(f'gh-pr.mjs should pass (got {code}): {err[:160]}')
    script_fails, script_n = script_cases()
    fails += script_fails
    total = len(BLOCK) + len(ALLOW) + 1 + 6 + 11 + len(wrap_timed) + 1 + script_n
    for f in fails:
        print('FAIL', f)
    print(f'{total - len(fails)}/{total} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
