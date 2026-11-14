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

ALLOW = [
    'ls -la',
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
        w('runner.sh', 'python3 "$1"\n')  # runs its first argument: `source runner.sh m.py` runs m.py
        w('word.py', "print('the " + S + " team writes find-generic-password docs')\n")
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
        block = [
            ('python3 measure.py', d),
            ('python3 -I ./measure.py', d),
            # card 15896271: a redirection before the interpreter; an output target skipped, the script still read
            ('>/dev/null python3 measure.py', d),
            ('sudo -u root 2>/dev/null python3 measure.py', d),
            ('python3 > out.txt measure.py', d),
            ('python3 2>err.log measure.py', d),
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
            ('python3 list.py measure.py', d),  # was allowed ("the rest are its arguments"); an argument is read too
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
        ]
        allow = [
            ('python3 list.py', d),
            # card 15896271: an output redirection's target is written, not run
            ('python3 list.py > out.txt', d),
            ('python3 list.py >out.txt', d),
            ('python3 list.py >> out.txt', d),
            ('python3 list.py 2>&1 > out.txt', d),
            ('python3 list.py &> out.txt', d),
            ('python3 list.py >| out.txt', d),
            ('python3 list.py 2> out.txt', d),
            ('python3 list.py > measure.py', d),  # truncated, not run
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
            ('python3 x ' + '=/' * 50000, 2),
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
            ('python3 ' + '-B ' * 12 + 'measure.py ' + 'a ' * 60, d),
            ('python3 ' + 'A' * 5000 + ' measure.py', d),
            ('python3 list.py ' + ' '.join(f'a{i}' for i in range(64)), d),
            ('cat ' + 'x ' * 70 + 'measure.py | python3', d),
            ('cat ' + 'x ' * 64 + 'list.py | python3', d),  # 65 words
            ('python3 ' + 'A' * 4096, d),  # one char past the window
        ]
        for cmd, cwd in too_many:
            code, err = bash_in(cmd, cwd)
            if code != 2 or 'script-too-many-args' not in err:
                fails.append(f'script: past MAX_ARGS/ARGS_WINDOW should block (got {code}): {cmd[:60]!r}')
        # Viktor 41790 INFO 3: the message says why (the word count and the limit, or the window)
        _, err = bash_in('python3 list.py ' + ' '.join(f'a{i}' for i in range(69)), d)
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
        code, err = bash_in('cd a && ' * 31 + ' ; '.join('python3 ' + ' '.join(f'm{j}' for j in range(62))
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
            ('do shell script ' * 10000, 0), ('os.system(' * 20000, 0), ('"python3" ' * 20000, 2),  # past MAX_ARGS: blocks, fast
        ]
        for cmd, want in payload_redos:
            t = _t.monotonic()
            code, _ = bash_in(cmd, d)
            took = _t.monotonic() - t
            if code != want or took > 2:
                fails.append(f'script: payload padding {cmd[:24]!r}: want rc {want} under 2 s, got {code} in {took:.1f} s')
        # Viktor 41756 INFO 4 (s1): past MAX_TRIES (4000) path lookups the gate blocks. 31 directories x 3 calls x
        # 60 missing words = 5580 lookups, no file found anywhere.
        code, err = bash_in('cd a && ' * 30 + ' ; '.join('python3 ' + ' '.join(f'm{j}' for j in range(60))
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
        return fails, len(block) + len(allow) + 8 + 3 + len(timed) + 2 + 1 + len(too_many) + 2 + 2 + 3 + 2 + 2 + 1 + 1 + len(payload_redos)


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
                  ('ssh h ' * 20000 + sec, 2), ('nice -n 5 sudo -u a ' * 10000 + sec, 2)]
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
    total = len(BLOCK) + len(ALLOW) + 6 + 11 + len(wrap_timed) + 1 + script_n
    for f in fails:
        print('FAIL', f)
    print(f'{total - len(fails)}/{total} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
