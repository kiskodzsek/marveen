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
# carries no runnable keychain call (card bc009036). The git credential fixtures likewise spell "cr3dential" (card
# 04d67b39), and the launchctl ones "l4unchctl" (card deede5e4, Viktor I1). Running this file by its path from an
# agent shell is still blocked by the gate it tests (measured 2026-11-20, card deede5e4): read as a script, the
# whole file is past the payload caps ('payload-unread'), and the escaped-name rows (`\0163ecurity`) decode to the
# call. CI runs it directly (.github/workflows/test.yml). In an agent shell its author runs it and notes the block
# on the card as a false positive (Klodel's false-positive rule; Viktor deede5e4 r2 INFO 1: a recipe that hides the
# path from the gate works for any script, so it is not written down here). A loop or pushd around it blocks.
def fix(cmd):
    return (cmd.replace('s3c', 'sec').replace('S3C', 'SEC').replace('s"3c"', 's"ec"')
            .replace('cr3d', 'cred').replace('CR3D', 'CRED')
            # card deede5e4 (Viktor I1): the launchctl fixtures too, so the gate does not block a run of this file
            # (`l4unchctl submit -p ...` blocks as text in script mode, fail-closed)
            .replace('l4unchctl', 'launchctl'))


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
    'l4unchctl submit -l a -o /tmp/o -- /usr/bin/s3curity dump-keychain',
    'l4unchctl submit -l a -e /tmp/e -o /tmp/o -- s3curity dump-keychain',
    # -p prog runs prog with the words after -- as argv, argv0 any word (Dave, measured on this branch): not read, blocks
    'l4unchctl submit -l a -p /usr/bin/s3curity -- s3curity dump-keychain',
    'l4unchctl submit -l a -p /usr/bin/s3curity -- x dump-keychain',
    'l4unchctl submit -l a -p /usr/bin/env -- x s3curity dump-keychain',
    'sudo l4unchctl submit -p /usr/bin/s3curity -l a -- x dump-keychain',
    'l4unchctl submit -l a -p /bin/echo -- echo hi',  # fail-closed: any -p blocks
    # Viktor 42295 LOW 1: the p in any flag word, joined or bundled (N33, N34), and <<- before the call (N19)
    'l4unchctl submit -l a -p/usr/bin/s3curity -- x dump-keychain',
    'l4unchctl submit -lp a /usr/bin/s3curity -- x dump-keychain',
    'l4unchctl submit -l a -pl /usr/bin/s3curity -- x dump-keychain',
    'l4unchctl submit -l a -op x /usr/bin/s3curity -- x dump-keychain',
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
    'l4unchctl asuser 501 s3curity dump-keychain',
    '/bin/l4unchctl bsexec 1 s3curity dump-keychain',
    'login -fp root s3curity dump-keychain',
    'login -f -h h root s3curity dump-keychain',
    'sandbox-exec s3curity dump-keychain',  # a chain word with no flag skipped (mutant sandbox_chain_out)
    'sudo 2>&1 s3curity dump-keychain',
    # card fae0712e (differential fuzz against bash and zsh, both ran line 2): normalise() joined a backslash-newline
    # whose backslash ends a comment or is the second half of an escaped backslash; the next line is a command
    ': |#\\\ns3curity dump-keychain',
    'echo x \\\\\ns3curity dump-keychain',
    'true # a \\\ns3curity find-generic-password -s x',
    # card 70a5fb2a (Viktor 43324 LELET 3, a fuzz family of about 58 in 3500): a quoted delimiter ending in a
    # backslash; its terminator line `J\` ends the body for the shell, and lexer_normalise joined it onto the next line
    "curl -d @- <<'J\\'\nhello\nJ\\\ns3curity dump-keychain",
    "git commit -F - <<'J\\'\nmsg\nJ\\\ns3curity find-generic-password -w",
    # card 70a5fb2a round 2 (Viktor 49212 O1, both passed main 915e2f70 and c2da88a9, bash ran the stub): an
    # unterminated heredoc later in the text sends the gate down the old (lexer-free) path, where normalise() joins
    # EVERY backslash-newline (a terminator line, an escaped backslash): the text with none joined is judged too
    "cat <<'J\\' >/dev/null\nhello\nJ\\\ns3curity find-generic-password -s probe\ncat <<Z",
    ': x \\\\\ns3curity find-generic-password -s probe\ncat <<Z',
    ': # note \\\ns3curity dump-keychain\ncat <<Z',
    # card 6772c137 (Viktor 49233 INFO, 70a5fb2a round 2): the lexer decodes \u/\U in a $'..' delimiter (bash 3.2 does
    # not), and zsh -f reads a $".." delimiter otherwise than bash; in each row the lexer ends the body earlier than
    # one shell, which ran the stub in 4 of them (measured on main, r1, r2: all blocked). Pinned so a later change that
    # blinds every heredoc body cannot open them
    ": <<$'J\\u00e9'\nJ\u00e9\n: <<'Z'\nJ\\u00e9\ns3curity dump-keychain\nZ",
    "cat <<$'J\\u00e9' >/dev/null\nJ\u00e9\ncat <<'Z' >/dev/null\nJ\\u00e9\ns3curity dump-keychain\nZ",
    ": <<$'J\\U000000e9'\nJ\u00e9\n: <<'Z'\nJ\\U000000e9\ns3curity dump-keychain\nZ",
    ': <<$"J"\nJ\n: <<\'Z\'\n$J\ns3curity dump-keychain\nZ',
    ': <<$"J"\nJ\n: <<\'Z\'\n$"J"\ns3curity dump-keychain\nZ',
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
          "printf '%s\\n' s3curity\\ dump-keychain x | bash",
          # card 39d885ef (Viktor 43793 MEDIUM 1): printf / echo -e escapes as the shell on stdin gets them: \n a newline,
          # \t a blank, \x and octal a char (a plain n, t was all normalise() left: allowed on main a8b4a4bf)
          "printf 'true\\ns3curity dump-keychain\\n' | bash", "echo -e 'true\\ns3curity dump-keychain' | sh",
          "printf 's3curity\\tdump-keychain' | bash", "printf 's3curity\\x20dump-keychain' | bash",
          "printf 's3curity\\040dump-keychain' | bash", "printf 'true\\n%b\\n' 's3curity\\tdump-keychain' | bash",
          # printf puts its arguments into the format: the call is on a line of its own only after that (allowed on
          # main a8b4a4bf and on the proposal of 43793; bash and zsh ran the stub)
          "printf 'x\\ns3curity %s\\n' dump-keychain | bash", "printf 's3curity %s' dump-keychain | bash",
          "printf '%s dump-keychain\\n' s3curity | bash",
          # a redirection between the printed words is no printed word (bash and zsh ran these; allowed on main and on
          # the proposal); `>x` and `>&2 .. 2>&1`: zsh's MULTIOS sends the output to the pipe too (zsh ran them)
          'echo s3curity 2>/dev/null dump-keychain | bash', 'echo s3curity 2>x dump-keychain | bash',
          'echo s3curity <x dump-keychain | bash', "printf '%s %s\\n' s3curity 2>/dev/null dump-keychain | bash",
          'echo s3curity >x dump-keychain | bash', 'echo s3curity >&2 dump-keychain 2>&1 | bash',
          'echo s3curity {fd}>/dev/null dump-keychain | bash', 'echo s3curity &>/dev/null dump-keychain | zsh',
          # mutation m39 (its survivors, by the differential, 11-19; bash 3.2 and zsh printed each, measured): printf
          # uses its format again while arguments are left (printf-one-pass), `--` ends its options
          # (printf-no-dashdash), %% prints a % and takes no argument (printf-pct-arg), %c and %.1s convert as %s do
          # (printf-s-only)
          "printf '%s' s3c urity ' dump-keychain' | bash", "printf -- 's3c%sity dump-keychain\\n' ur | bash",
          "printf 'true%%;%s dump-keychain\\n' s3curity | bash", "printf 's3c%crity dump-keychain\\n' u | bash",
          # ... \r \f \v read as a newline (Viktor 43793 (b)): bash and zsh keep a CR in the word (measured: `echo A\rB`
          # is one word), so this read is the safe side, kept on purpose (unesc-nl-only-n)
          "printf 'true\\rs3curity dump-keychain' | bash", "printf 'true\\fs3curity dump-keychain' | bash",
          "printf 'true\\vs3curity dump-keychain' | bash",
          # card c7234bed (Viktor 47570): shell code an echo / printf substitution prints, where eval, source, . or a
          # shell runs it (passed on main 171f2e6a and on 39d885ef; bash and zsh ran the stub, work/c7234bed/truth1)
          'eval "$(echo s3curity dump-keychain)"', 'eval `echo s3curity dump-keychain`',
          "eval \"$(printf 'true\\ns3c%sity dump-keychain\\n' ur)\"", 'bash -c "$(echo s3curity dump-keychain)"',
          "sh <<<\"$(echo s3curity dump-keychain)\"", ". <(printf 's3c%sity dump-keychain\\n' ur)",
          "bash <(echo 's3curity dump-keychain')", ". /dev/stdin <<<'s3curity dump-keychain'",
          'x=$(echo s3curity dump-keychain); eval "$x"',
          # mutation round c7234bed (feeder-no-path): echo / printf by its path (work/c7234bed/truth8)
          'eval "$(/bin/echo s3curity dump-keychain)"',
          # mutation round c7234bed (var-no-brace, source-here-nosplit): eval "${x}"; a here-string of two lines to a
          # /dev/stdin source (work/c7234bed/truth9)
          'x=$(echo s3curity dump-keychain); eval "${x}"', ". /dev/stdin <<<'true\ns3curity dump-keychain'",
          # mutation round 2 c7234bed (bt-noesc, sq-off, dq-off, depth-off; bin/mut-diff.py witnesses, bash and zsh ran
          # the stub form, work/c7234bed/truth10, truth11): an escaped backtick, a quoted ")", a nested $( ) inside
          'eval "`echo \\`true\\`; echo s3curity dump-keychain`"',
          'bash -c "`echo \\`echo hi\\`; echo s3curity dump-keychain`"',
          'eval "$(echo \'#)\'; echo s3curity dump-keychain)"', 'eval "$(echo "#)"; echo s3curity dump-keychain)"',
          'eval "$(echo $(echo s3curity) dump-keychain)"',
          # more than MAX_GEN_SUBSTS sites: not read, blocked unread
          '; '.join('. <(echo echo a%d)' % i for i in range(65)),
          # mutation round 2 c7234bed (hits-none-pass; bin/mut-diff.py witness): a bash -c payload past the cap. Since
          # the 48033 M1 rework a site counts at a code position only, and a verbatim payload with a substitution and a
          # feeder word is read as a text of its own (payload_texts), so this is the payload's own 65 sites
          "bash -c '" + '; '.join('. <(echo echo a%d)' % i for i in range(65)) + "'",
          # 48033 M1 rework: a substitution in a verbatim single-quoted payload (no quote in it, so payload_texts did
          # not read it again, and generated_lines() reads code positions only): passed on main and on 79e1a907
          "bash -c 'eval $(echo s3curity dump-keychain)'", "sh -c '. <(echo s3curity dump-keychain)'",
          "bash -c 'eval `echo s3curity dump-keychain`'", "bash -c 'eval -- $(true; echo s3curity dump-keychain)'"]
# card c7234bed (Viktor 48033 M1, agents/viktor/work/kcgen-1119/probe3.out: passed on main f48a5d0f and on 79e1a907,
# bash or zsh ran the stub with the secret subcommand): the reader anywhere in its command (a shell option with its
# value, the substitution after other words of the argument or after other arguments, a redirection from a process
# substitution), the form in a heredoc body a shell reads, a feeder that is not the substitution's first command, a
# comment with a quote in the substitution; 48033 INFO V1 (a $var other readers take) and V2 (a long blank run)
BLOCK += ['bash -o pipefail -c "$(echo s3curity dump-keychain)"', 'bash -c "true; $(echo s3curity dump-keychain)"',
          'eval "true; $(echo s3curity dump-keychain)"', 'eval " $(echo s3curity dump-keychain)"',
          'eval "x=1 $(echo s3curity dump-keychain)"', 'eval -- "$(echo s3curity dump-keychain)"',
          'eval "" "$(echo s3curity dump-keychain)"', 'eval true\\; $(echo s3curity dump-keychain)',
          'sh < <(echo s3curity dump-keychain)', "bash <<'E'\neval \"$(echo s3curity dump-keychain)\"\nE",
          'eval "$(true; echo s3curity dump-keychain)"', 'eval "$({ echo s3curity dump-keychain; })"',
          'eval "$( (echo s3curity dump-keychain) )"', 'eval "$(2>/dev/null echo s3curity dump-keychain)"',
          'eval "$(if true; then echo s3curity dump-keychain; fi)"',
          "eval \"$(printf '%s\\n' \"$(echo s3curity dump-keychain)\")\"",
          "eval \"$(echo x # it's\necho s3curity dump-keychain)\"",
          'x=$(echo s3curity dump-keychain); bash -c "$x"', 'x=$(echo s3curity dump-keychain); bash <<< "$x"',
          'x=$(echo s3curity dump-keychain); echo "$x" | bash', 'x=$(echo s3curity dump-keychain); . <(echo "$x")',
          "bash <<E\n$(echo s3curity dump-keychain)\nE", 'eval' + ' ' * 170 + '"$(echo s3curity dump-keychain)"',
          # M1 mutation round (recurse-off): the site only exists in what the site prints (printf's \x24 is $); passed
          # on main f48a5d0f and on 79e1a907, bash and zsh ran the stub (work/c7234bed/m1/truth-surv.txt)
          "eval \"$(printf 'eval \\x24(echo s3curity dump-keychain)')\"",
          # M1 mutation round (seg-frame-any): a ${ } default value is part of the reader's command; ${1 is no $var
          # name (the var rule does not cover it). The bash -c forms passed on main and on 79e1a907, the eval forms on
          # main; bash and zsh ran the stub (work/c7234bed/m1/truth-skip.txt, truth-skip2.txt)
          'eval "${1:-$(echo s3curity dump-keychain)}"', 'bash -c "${1:-$(echo s3curity dump-keychain)}"',
          'eval "${x:-$(echo s3curity dump-keychain)}"', 'bash -c "${x:-$(echo s3curity dump-keychain)}"']

# card c7234bed (Viktor 48205, 2nd round; agents/viktor/reports/2026-11-19-kc-c7234bed-kor2-itelet.md): M1 a
# positional parameter a reader takes ($1, ${1}, $@, $*; a regression against 79e1a907), M2 a substitution or a heredoc
# piped into a shell, L1 a heredoc in an unquoted heredoc body. main f48a5d0f and bbc4f1cb allowed each, bash and zsh ran
# the stub (|& bash: zsh only, bash 3.2 has no |&) (work/c7234bed/r2/truth-r2.txt)
BLOCK += [
    'f() { eval "$1"; }; f "$(echo s3curity dump-keychain)"',
    'set -- "$(echo s3curity dump-keychain)"; eval "$1"',
    'set -- "$(echo s3curity dump-keychain)"; eval "${1}"',
    'set -- "$(echo s3curity dump-keychain)"; eval "$@"',
    'set -- "$(echo s3curity dump-keychain)"; eval "$*"',
    'f() { bash -c "$1"; }; f "$(echo s3curity dump-keychain)"',
    'echo "$(echo s3curity dump-keychain)" | bash',
    'echo "$(echo s3curity dump-keychain)" | sh -s',
    'printf \'%s\\n\' "$(echo s3curity dump-keychain)" | bash',
    'echo "`echo s3curity dump-keychain`" | bash',
    'echo "$(echo s3curity dump-keychain)" |& bash',
    'echo "$(echo s3curity dump-keychain)" | /bin/bash',
    'cat <<E | bash\n$(echo s3curity dump-keychain)\nE',
    'cat <<\'E\' | bash\neval "$(echo s3curity dump-keychain)"\nE',
    'cat <<E | sh\n$(echo s3curity dump-keychain)\nE',
    'cat <<-E | bash\n\t$(echo s3curity dump-keychain)\n\tE',
    "bash <<E1\nbash <<'E2'\n$(echo s3curity dump-keychain)\nE2\nE1",
    'bash <<E1\nbash <<E2\nbash <<E3\n$(echo s3curity dump-keychain)\nE3\nE2\nE1',
]
# $'...' escapes as bash 3.2 reads them (each measured with the proxy rule): one hex digit before a non-hex, two octal
# digits, hex letters in both cases
BLOCK += ["bash -c $'s3curity\\x9\\x20dump-keychain'", "bash -c $'s3curity\\11dump-keychain'",
          "bash -c $'s3curity dump-\\x6beychain'", "bash -c $'s3curity dump-\\x6Beychain'",
          # a $"..." piece after the first one, and a $'...' piece that ends before the next $'...' (mutation round)
          "bash -c 's3c'$\"urity dump-keychain\"", "bash -c $'s3c'u$'\\x72ity dump-keychain'"]
# card c7234bed L1 mutation round: %b's \0NNN put into the format, the format's own \u (zsh's printf; bash 3.2
# prints it as is: fail-closed there), a wrapper's flag with its word in a substitution a reader runs
BLOCK += ["printf 's%b dump-keychain' '\\0145curity' | bash", "printf '\\u0073%s dump-keychain' ecurity | bash",
          "eval \"$(env -u HOME printf 'x\\ns3curity dump-keychain')\""]
# card c7234bed (Viktor 47808 LOW L1, agents/viktor/work/kcpipe-1119/probe.py: 12 forms passed on main and on
# 9ddb6a43, bash or zsh ran the stub): \0NNN of echo -e / %b / zsh's echo, \u / \U, a feeder after builtin /
# command / env, zsh's print
BLOCK += ["echo -e '\\0163\\0145curity dump-keychain' | bash", "printf '%b' '\\0163ecurity dump-keychain' | bash",
          "echo '\\0163ecurity dump-keychain' | zsh", "printf '\\u0073ecurity dump-keychain' | zsh",
          "printf '\\u0073ecurity dump-keychain' | bash", "echo -e '\\u0073ecurity dump-keychain' | zsh",
          "builtin printf 'x\\ns3curity dump-keychain\\n' | bash", "command printf 'x\\ns3curity dump-keychain\\n' | bash",
          "env printf 'x\\ns3curity dump-keychain\\n' | bash", "command echo -e 'x\\ns3curity dump-keychain' | bash",
          "print 'x\\ns3curity dump-keychain' | zsh", "echo -e 'x\\0012s3curity dump-keychain' | bash",
          # the wrapper words with their own words, and the same in a substitution a reader runs
          "env -u HOME A=1 printf 'x\\ns3curity dump-keychain' | bash", "nice -n 5 printf 'x\\ns3curity dump-keychain' | bash",
          "command -p echo -e 'x\\ns3curity dump-keychain' | bash", "printf '\\U00000073ecurity dump-keychain' | zsh",
          'eval "$(command echo s3curity dump-keychain)"', 'eval "$(print s3curity dump-keychain)"',
          "eval \"$(env A=1 printf 'x\\ns3curity dump-keychain')\"", "bash -c \"$(builtin echo -e 'x\\ns3curity dump-keychain')\""]

# card 03a336e5 (Viktor 47750, agents/viktor/work/kcsubst-1119/probe.py: 16 forms passed the live gate, bash and zsh
# ran the stub): a command name the shell makes, with a secret subcommand as a word of the same command
BLOCK += ['$(echo s3curity) dump-keychain', '`echo s3curity` dump-keychain', '"$(echo s3curity)" dump-keychain',
          '$(printf %s s3curity) find-generic-password -s x -w', '$(echo s3c)urity dump-keychain',
          'x$(echo s3curity) dump-keychain', '$(echo s3c)$(echo urity) dump-keychain', '"$(echo s3cur)ity" dump-keychain',
          'x=$(echo s3curity); $x dump-keychain', 'z=s3curity; $z find-internet-password -s x', '${Z:-s3curity} dump-keychain',
          "$(printf '\\163\\145\\143urity') dump-keychain", 'sudo $(echo s3curity) dump-keychain',
          'env A=1 $S -q find-generic-password -s x -w', '$S "dump-keychain"', "bash -c '$S dump-keychain'",
          'ls; $S dump-keychain', 'true && "${S}" find-internet-password -s x', '$(echo s3curity) -v dump-keychain\n',
          '`echo s3curity` FIND-GENERIC-PASSWORD -s x', '$(echo $(echo s3curity)) dump-keychain']
# card 03a336e5 mutation round: a tab is a blank after the name too; a later line starts at its newline (the gate's
# reading of find's `\s-exec` there; bash would run `-exec` as a command, so this row pins the fail-closed side)
BLOCK += ['$S\tdump-keychain', 'true\n-exec $S dump-keychain']
# card d58d5c30 (Viktor 48033 LOW L2, bash and zsh ran the stub 11-20, work/d58d5c30/gbt1): the literal name with a
# subcommand the shell makes at run time (a substitution, a backtick, a variable, a piece glued to a literal)
BLOCK += ['s3curity $(echo dump-keychain)', 's3curity `echo dump-keychain`', 'eval s3curity "$(echo dump-keychain)"',
          'bash -c "s3curity $(echo dump-keychain)"', 's3curity "$(echo find-generic-password)" -s x',
          's3curity dump-$(echo keychain)', 'X=dump-keychain; s3curity $X', 'X=dump-keychain; s3curity "$X"',
          'X=dump-keychain; s3curity ${X}', 's3curity -v $(echo dump-keychain)', 'sudo s3curity $(echo dump-keychain)',
          "env s3curity \"$(printf 'dump-keychain')\"", '/usr/bin/s3curity $X', 'ls; s3curity\t$X']
# ... the quoted or escaped name, a backtick opening in the word, a loop the rule does not trust (a secret word or an
# option in the list, the variable set again, a list made at run time), a variable with no loop
BLOCK += ['"s3curity" $(echo dump-keychain)', "'s3curity' \"$X\"", '\\s3curity `echo dump-keychain`',
          's3curity dump-`echo keychain`', 'for s in add-trusted-cert dump-keychain; do s3curity $s -h; done',
          'for s in a b; do s=dump-keychain; s3curity $s; done', 'for s in -i; do s3curity $s; done',
          'for s in $(cat list); do s3curity $s -h; done', 's3curity $T -h', 'for s in a b; do read s; s3curity $s; done']
# (mutation round) a wrapper with a flag that takes a word: only the text with the wrapped commands' bounds shows the
# call; and the escaped name in a payload or a pipe into a shell (main allowed all, measured with hook-probe)
BLOCK += ['sudo -u root s3curity $X', 'env -u HOME s3curity $X', 'timeout -s KILL 5 s3curity $X',
          'sudo -g staff -u root s3curity "$(echo x)"', "echo '\\s3curity $X' | bash", "bash -c '\\s3curity $X'",
          "bash <<< '\\s3curity $X'"]
# (mutation round, gate-bash-truth 11-20: bash and zsh ran dump-keychain, main allowed) an ANSI-C or locale quote, the
# positional parameters, a loop variable glued to more (the list word is only a piece of the subcommand)
BLOCK += ["s3curity $'dump-keychain'", "s3curity $'\\x64ump-keychain'", 's3curity $"dump-keychain"',
          'f() { s3curity "$@"; }; f dump-keychain', 's3curity $*', 's3curity $1',
          'for s in dump; do s3curity $s-keychain; done', 'for s in dump; do s3curity ${s}-keychain; done',
          # a word that only ends in "for" is no loop (the variable comes from elsewhere)
          'echo before s in a b; s3curity $s', 'X=$(get) && echo $Xfor s in a; s3curity $s',
          # (mutation round 1's survivors, gate-bash-truth 11-20: bash and zsh ran dump-keychain) an empty list keeps
          # the inherited value; += appends to the list word
          'for s in ; do :; done; s3curity $s', 'for s in dump; do s+=-keychain; s3curity $s; done']
# (Viktor 48765, his rows.txt, measured with a stub in bash and zsh: a secret subcommand ran) a backtick opener with a
# blank, a tab, a redirection or a tilde after it; a brace list; the loop variable named another way (printf -v,
# ${s:=}, zsh ${s::=}, zsh for s (..), select, zsh foreach); xargs giving the subcommand
BLOCK += ['s3curity ` printf dump-keychain`', 's3curity dump-` printf keychain`', 's3curity `\tprintf dump-keychain`',
          's3curity `<tmp/f`', 's3curity `~/x`', 's3curity {dump-keychain,}', 's3curity dump-keychai{n,}',
          's3curity {dump,}-keychain', 's3curity dump-{keychain,x}',
          'for s in list-keychains; do :; done; printf -v s dump-keychain; s3curity $s',
          'for s in list-keychains; do unset s; : ${s:=dump-keychain}; s3curity $s; done',
          'for s in list-keychains; do :; done; for s (dump-keychain) s3curity $s',
          'for s in list-keychains; do : ${s::=dump-keychain}; s3curity $s; done', 's3curity -- $(printf dump-keychain)',
          'for s in list-keychains; do :; done; select s in dump-keychain; do s3curity $s; break; done <<< 1',
          'for s in list-keychains; do :; done; foreach s (dump-keychain) s3curity $s; end',
          'echo dump-keychain | xargs s3curity', 'for s in list-keychains; do :; done; s=dump-keychain s3curity $s',
          'for s in list-keychains; do :; done; IFS=, read s <<< dump-keychain; s3curity $s',
          'xargs -I{} s3curity {} < tmp/f', 'xargs -I% s3curity % < tmp/f', 'xargs -n1 s3curity < tmp/f',
          # (d58d5c30 r2, gate-bash-truth: bash and zsh ran them) a literal backtick before the opener (escaped, in a
          # comment) makes the count odd: the parity alone (Viktor's P1) let them pass, the opener's first char holds
          'echo \\`; s3curity `printf dump-keychain`', '# a ` in a comment\ns3curity `printf dump-keychain`',
          # (d58d5c30 r2 replay fix: the xargs call is read past the walk of its flags) flags with and without a word,
          # a path, a quoted name; BSD -J puts the stdin word at its string too
          'xargs -0 s3curity < tmp/f', 'xargs -n 1 s3curity < tmp/f', 'xargs -P2 -n1 /usr/bin/s3curity < tmp/f',
          'xargs -t "s3curity" < tmp/f', 'xargs --max-args 1 s3curity < tmp/f', 'xargs -J % s3curity % < tmp/f',
          'xargs -0 -L 1 -I {} s3curity {} < tmp/f', 'xargs -- s3curity < tmp/f',
          # past MAX_ARGS flag words the walk stops unread: blocks
          'xargs ' + '-0 ' * 70 + 's3curity < tmp/f',
          # (d58d5c30 r2 mutation round 5, gate-bash-truth: bash and zsh ran dump-keychain, main allows) the opener's
          # first char other than a letter (bt-open-set-narrow; the $C row runs in bash only), a one-letter brace
          # range (brace-range-off), an option after the name before the stdin word (xargs-opts-off)
          'echo \\`; s3curity `/usr/bin/printf dump-keychain`', 'C="printf dump-keychain"; echo \\`; s3curity `$C`',
          'echo \\`; s3curity `"printf" dump-keychain`', "echo \\`; s3curity `'printf' dump-keychain`",
          'echo \\`; s3curity `(printf dump-keychain)`', 'echo \\`; s3curity `{ printf dump-keychain; }`',
          'echo \\`; s3curity `\\printf dump-keychain`',
          's3curity dump-keychai{n..n}', 's3curity {d..d}ump-keychain', 's3curity dump-{k..k}eychain',
          's3curity -q dump-keychai{n..n}',
          'echo dump-keychain | xargs s3curity -q', 'xargs -I{} s3curity -q {} < tmp/f',
          # (xargs-i-default) GNU xargs -i takes {} as its default string; macOS xargs does not run -i (Viktor 48765
          # F13): a deliberate over-read, kept for a GNU xargs on PATH
          'xargs -i s3curity {} < tmp/f',
          # (Viktor 48860, r3; bash and zsh ran dump-keychain, his shell.txt) LOW 1: an escaped or single-quoted
          # backtick before the real opener made its count look odd (R01, R02, R03, R10); LOW 2: a wrapper as the
          # command xargs runs (X01, X03, X06, X07)
          'echo \\`; s3curity ` printf dump-keychain`', 'echo \\`; s3curity `\tprintf dump-keychain`',
          'echo \\`; s3curity `<tmp/f`', "echo '`'; s3curity `./g.sh`", "echo $'\\`'; s3curity ` printf dump-keychain`",
          'echo x # `\necho \\`; s3curity ` printf dump-keychain`',
          'printf dump-keychain | xargs env s3curity', 'printf dump-keychain | xargs nice s3curity',
          'printf dump-keychain | xargs -0 env s3curity', 'printf dump-keychain | xargs nice -n 5 s3curity',
          'printf dump-keychain | xargs env nice -n 5 command s3curity',
          # (r3 mutation round 8) more wrappers than WRAP_PASSES (8) after xargs: not walked to the end, blocks
          'printf dump-keychain | xargs ' + 'env ' * 9 + 's3curity',
          # (r3, found classifying mutation round 7's plain-off survivor; bash and zsh ran dump-keychain, r3/gbt-hd3):
          # a heredoc body's backtick is read apart from the line, quoted delimiter or not (`<<\E` reaches the rule
          # as `<<E`)
          "cat <<'E'\n`\nE\ns3curity ` printf dump-keychain`", 'cat <<"E"\n`\nE\ns3curity ` printf dump-keychain`',
          'cat <<\\E\n`\nE\ns3curity ` printf dump-keychain`', "cat <<-'E'\n\t`\n\tE\ns3curity ` printf dump-keychain`",
          'cat <<E\n\\`\nE\ns3curity ` printf dump-keychain`',
          # a text the lexer does not read (a trailing unclosed quote; bash runs the lines before it, r3/gbt-hd4): no
          # backtick counts as real, so the one after the name opens
          "cat <<'E'\n`\nE\ns3curity ` printf dump-keychain`\necho \"",
          "cat <<'E'\n`\nE\ns3curity ` printf dump-keychain`\necho '",
          'echo "$(echo \'`\')"; s3curity ` printf dump-keychain`',
          # (r3 replay fix, the literal start of the made word) quotes and a backslash taken off, a start a secret
          # subcommand has, and the starts that are not sure: a $, a brace (bash expands it first)
          's3curity d"ump"-$(echo keychain)', "s3curity d'u'mp-`echo keychain`", 's3curity \\dump-$(echo keychain)',
          's3curity e$(echo xport)', 'X=dump; s3curity $X-$(echo keychain)', 's3curity {dump,x}-$(echo keychain)',
          # (mutation round 9, strip-bs-off; bash and zsh made dump-keychain, r3 stub) a backslash before a non-letter
          # (normalise takes it off a letter only)
          's3curity dump\\-$(echo keychain)',
          # (Viktor 49104 r4 LOW, his shell3.txt: zsh or bash made dump-keychain from a file of that name in the cwd)
          # a glob group the literal start did not know: zsh's (..), extendedglob ^ and #, bash extglob on its own
          # line, zsh kshglob; and K05 (zsh (#i)), which the same characters now block
          's3curity (dump-keychai)n$(true)', 'setopt extendedglob; s3curity ^zzz$(true)',
          'setopt extendedglob; s3curity dump-keychainn#$(true)', 'shopt -s extglob\ns3curity @(dump-keychai)n$(true)',
          'shopt -s extglob\ns3curity +(dump-keychai)n$(true)', 'shopt -s extglob\ns3curity !(zzz)$(true)',
          'setopt kshglob; s3curity @(dump-keychai)n$(true)', 'setopt extendedglob; s3curity (#i)DUMP-keychai(n)$(true)']

# card d58d5c30 round 5 (Viktor 49221 MEDIUM; all passed main d1d4936b = the live gate, zsh ran the stub): zsh's
# precommand modifiers before a literal call
BLOCK += ['noglob s3curity find-generic-password -s x', 'nocorrect s3curity dump-keychain',
          'repeat 1 s3curity dump-keychain', 'coproc s3curity find-internet-password -s x',
          'true; nocorrect noglob /usr/bin/s3curity export -o x.p12', 'repeat 2 nocorrect s3curity dump-keychain']

# card 3bf9a741 (the 74586987 side gap; all passed main 915e2f70, measured 2026-11-20, work/3bf9a741/main.txt): xargs
# puts the words it reads on stdin into the argv of the command it runs, here the keychain call's subcommand
BLOCK += ['echo dump-keychain | xargs s3curity', 'echo dump-keychain | xargs -n1 s3curity',
          'xargs s3curity <<< dump-keychain', 'echo s3curity dump-keychain | xargs env',
          "printf '%s\\n' dump-keychain | xargs s3curity", 'echo find-generic-password -w | xargs -I{} s3curity {}',
          'echo dump-keychain | (xargs s3curity)', 'xargs s3curity < <(echo dump-keychain)',
          "xargs s3curity <<'E'\ndump-keychain\nE", 'echo dump-keychain | xargs -0 s3curity',
          'echo dump-keychain | /usr/bin/xargs -P2 -- s3curity', 'echo x | xargs echo; echo dump-keychain | xargs s3curity',
          # round 2 (Viktor 49280 MEDIUM 1; d74afad6 and main allowed the first two, bash ran the stub): BSD xargs -I
          # puts the ENTIRE input line in place of the replace string, here a shell's code
          "echo s3curity find-generic-password -s x | xargs -I{} sh -c '{}'",
          'echo s3curity dump-keychain | xargs -I{} bash -c {}', "printf 's3curity dump-keychain\\n' | xargs -I@ sh -c @",
          'echo s3curity dump-keychain | xargs -I{} bash -ec {}',
          # rebased on 87a887b5: an xargs running the keychain CLI blocks whatever feeds it, an or-list too (main's
          # made-subcommand rule, card d58d5c30: its subcommand comes from stdin); round 1 had it as an ALLOW row
          'echo dump-keychain || xargs s3curity',
          ]

# card 04df07c5 (Viktor 49104 INFO 1, rows J12-J14; main allows them): a glob in the subcommand word, no substitution.
# With a file of the secret name in the cwd bash and zsh run the secret subcommand (J13 in both, J14 in zsh).
BLOCK += ['s3curity dump-keychai?', 's3curity (dump-keychai)n', 'shopt -s extglob; s3curity @(dump-keychai)n',
          'touch dump-keychain; s3curity dump-k*', 's3curity [d]ump-keychain', 's3curity dump-keychai[mn]',
          's3curity exp?rt -k x', 's3curity find-*-password -s x', 's3curity -v dump-keych?in', 's3curity *',
          's3curity "dump-k"*', "s3curity 'dump-'k*", 's3curity (list-keychains|dump-keychain)', 's3curity !(x)',
          'shopt -s extglob\ns3curity +(dump-keychai)n', 'setopt kshglob; s3curity @(dump-keychai)n',
          '(s3curity dump-k*)', 'bash -c "s3curity dump-k*"', "ssh h 's3curity dump-k*'", 'sudo s3curity dump-k*',
          '/usr/bin/s3curity dump-k*', '"s3curity" dump-k*',
          'setopt extendedglob; s3curity ^zzz', 'setopt extendedglob; s3curity dump-keychainn#',
          'setopt extendedglob; s3curity (#i)DUMP-keychai(n)', 'setopt extendedglob; s3curity dump-k*~x',
          'setopt extendedglob; s3curity (#a1)dump-keychaim', 's3curity DUMP-K*']
# card 04df07c5 round 2 (Viktor 49398, his oracle rows with bash/zsh truth; round 1 let each through): a quoted blank,
# separator, ) or | inside a group alternative or a bracket member, a [:class:] member, and a glob in the option
# position (a file named -i in the cwd: the subcommands come from stdin)
BLOCK += ['s3curity (dump-keychain|" ")', 'shopt -s extglob\ns3curity @(dump-keychain|" ")',
          's3curity ["; "d]ump-keychain', 's3curity [" "d]ump-keychain', 's3curity (dump-keychain|";")',
          's3curity ["<"d]ump-keychain', 's3curity (")"|dump-keychain)', 'shopt -s extglob\ns3curity @(")"|dump-keychain)',
          'echo dump-keychain | s3curity -[i]', 'echo dump-keychain | s3curity -?', 'echo dump-keychain | s3curity -v -[i]',
          's3curity [[:alpha:]]ump-keychain']

ALLOW = [
    # card d58d5c30 round 5: the four zsh words in prose, and before a harmless command
    'echo coproc noglob nocorrect repeat 1 s3curity dump-keychain', "git commit -m 'repeat: noglob, nocorrect, coproc'",
    'noglob ls *.py', 'repeat 3 echo hi', 'nocorrect s3curity list-keychains',
    # card c7234bed (L1): the decoded feeders into no shell, a harmless decoded call, another program's substitution
    # card c7234bed (48033 M1 rework): the two rows that blocked unread before (the old count of a quoted text's raw
    # sites, and of a bash -c payload read twice; nothing secret runs in either): an echo prints its quoted text, and
    # 33 harmless sites are in the cap; a quoted substitution no reader takes, a non-secret line in a payload
    "echo '" + '; '.join('. <(echo echo a%d)' % i for i in range(65)) + "'",
    "bash -c '" + '; '.join('. <(echo echo a%d)' % i for i in range(33)) + "'",
    "echo 'x $(echo s3curity dump-keychain)'", "bash -c 'eval $(echo s3curity list-keychains)'",
    # a bare printf into a shell raised IndexError in stdin_pipelines (main too: an 'error' block); it prints nothing
    'printf | bash',
    # card c7234bed (48033 M1): the substitution in another command than the reader's, a $var no reader takes, a
    # heredoc body no shell reads, a substitution in a comment, a harmless or non-secret line at the new sites
    'bash -n x.sh && cat <(echo s3curity dump-keychain)', 'x=$(echo s3curity dump-keychain); bash -n x.sh; echo "$x"',
    "cat <<'E'\neval \"$(echo s3curity dump-keychain)\"\nE", "eval \"$(echo x # $(echo s3curity dump-keychain)\necho true)\"",
    'bash -o pipefail -c "$(echo echo hi)"', 'eval -- "$(echo s3curity list-keychains)"',
    "print 'x\\ns3curity dump-keychain' | cat", "command echo -e 'x\\ns3curity dump-keychain' | cat",
    # (mutation round) \U past U+10FFFF prints no letter (bash: as is, zsh: other bytes); a flag word before the
    # feeder with no wrapper is the command itself (`-v` runs nothing)
    "printf '\\U00110073ecurity dump-keychain' | bash", "-v printf 'x\\ns3curity dump-keychain' | bash",
    "printf '\\u0073ecurity list-keychains' | bash", "echo -e '\\0163ecurity list-keychains' | bash",
    'eval "$(command -v brew)"', "builtin printf 'hello\\n' | bash", 'eval "$(env | grep PATH)"',
    "printf '\\uD800 x\\n' | bash", "printf '\\U0011FFFF x\\n' | bash",
    # card 03a336e5: a literal first word, another word than the three, the word glued to more, a quoted string
    'echo $(echo s3curity) dump-keychain', 'echo "$(date)" dump-keychain', '$PY x.py export', '$S list-keychains',
    '$EDITOR notes/dump-keychain.md', '$X dump-keychain-notes', 'grep -n "$PAT" find-generic-password.txt',
    '"$SHELL" -n x.sh', '$S find-certificate -a', 'cd $D; grep -c dump-keychain notes.txt', '$X | grep dump-keychain',
    # (mutation round) the word glued to more on its left; a NUL of the command is a plain char, not a mark
    '$X my-dump-keychain', '$X a/dump-keychain', '\x00echo $S dump-keychain',
    # card d58d5c30: a literal subcommand with a made argument after it, the name not in command position, a
    # substitution whose call is literal
    's3curity find-certificate -c "$NAME"', 's3curity list-keychains -d user', 'echo s3curity $(echo dump-keychain)',
    's3curity find-identity -v -p "$P"', 'X=$(s3curity list-keychains)', 'grep s3curity "$F"',
    # (fleet replay 11-20) a closing backtick in prose, quoted data the quote removal would make a command, and the
    # help loops over literal non-secret subcommands (Viktor's and Kernel's)
    'echo "`s3curity add-trusted-cert` (x)"', 'echo "x (`s3curity ...`, y)"', 'echo "`s3curity definer`, z"',
    'grep -n "^a\\|s3curity" $F', 'for s in add-trusted-cert create-keypair; do s3curity $s -h; done',
    'for s in a b; do s3curity "$s" -h; done', 'for s in a b; do /usr/bin/s3curity ${s} -h 2>&1 | head -3; done',
    # (mutation round 1) `$s=` in an echo is no assignment of s
    'for s in add-trusted-cert create-keypair; do echo $s=1; s3curity $s -h; done',
    'for s in add-trusted-cert; do echo x$s=1; s3curity $s -h; done',
    # (Viktor 48765) the loop over literal words read only as $s / ${s}, a quoted brace, xargs with a literal
    # subcommand or into another program, a backtick in prose before a literal call
    'for s in list-keychains show-keychain-info; do s3curity $s; done', 's3curity find-certificate -c "{a,b}"',
    'for sub in add-trusted-cert create-keypair; do s3curity $sub -h; done',
    'for s in list-keychains; do s3curity "$s"; done; echo ${s}', 'grep -rn s3curity . | xargs -n1 echo',
    'ls | xargs s3curity list-keychains', 'echo it`s fine; s3curity list-keychains',
    'xargs -I{} cp {} /x; s3curity list-keychains', 'echo "`s3curity ...`, and `SECURITY NOTICE` here"',
    # (d58d5c30 r2 fleet replay, 14 rows: runs of prod-tree-write-gate_test.py, whose row is the first) the name as
    # another program's argument or glued to more is no call xargs makes
    'find agents -name agent-config.json | xargs grep s3curityProfile', 'git ls-files | xargs grep -l s3curity',
    'ls | xargs -0 grep -n s3curity', 'xargs echo s3curity < tmp/f', 'xargs -I{} grep s3curity {} < tmp/f',
    'xargs -n1 s3curity-notes < tmp/f', 'xargs -J % cp % s3curity/ < tmp/f', 'echo xargs; s3curity list-keychains',
    # (Viktor 48860 r3: R13, R14, X09, X10) an escaped or quoted backtick before a literal call, a wrapper xargs runs
    # with a literal subcommand or another program
    'echo \\`; s3curity list-keychains', "echo '`'; s3curity list-keychains",
    'printf list-keychains | xargs env s3curity list-keychains', 'ls | xargs env echo s3curity',
    "cat <<'E'\n`\nE\ns3curity list-keychains",  # (r3) a heredoc backtick before a literal call
    "cat <<'E'\n`\nE\ns3curity list-keychains\necho \"",  # the same in a text the lexer does not read
    # (r3 fleet replay, 20 rows: a doc or a heredoc the lexer reads apart from the line, e.g. the Marabel
    # architecture.md's `security definer`) no secret subcommand starts with the made word's literal start
    "cat <<'E'\n- `s3curity definer`, `search_path`\nE", "cat <<'E'\n`s3curity add-trusted-cert`, it's here\nE",
    "echo \"it's `s3curity definer`, z\n",
    # (replay row, Kernel's help loop) with a loop name that is not also a sed / grep letter
    "for sub in add-trusted-cert list-keychains; do echo \"### $sub\"; /usr/bin/s3curity $sub -h 2>&1"
    " | grep -E '^\\s+-' | sed 's/^ *//' | cut -c1-110; done > o.txt",
    # (mutation round 5, loop-name-lookbehind) the name glued to a digit names no variable
    'for s in add-trusted-cert list-keychains; do s3curity $s -h; sleep 1s; done',
    'for s in list-keychains; do s3curity $s; done; tail -n 20s.log',
    # (second replay run) the quoted name as a quoted argument: its opening quote is no command position
    'K=x; grep -n "s3curity" "$K" | head -30', "grep 's3curity' \"$F\"", 'grep -c "s3curity" $(ls *.py)',
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
    # card 3bf9a741: what an xargs runs with its fed words is no keychain call (a printed name, a search)
    'echo dump-keychain | xargs echo s3curity', 'echo s3curity dump-keychain | xargs grep -c x',
    'echo dump-keychain | xargs', 'echo the s3curity team | xargs -n1 echo',
    # card 39d885ef: printf's output, the name printed as text
    "printf 'echo %s\\n' s3curity | bash", "printf 'echo the\\ns3curity team\\n' | cat",
    # mutation m39 (strip-fd-any-word): a 2 not glued to its > is a printed word, so by security(1)'s syntax 2 is the
    # command it runs (not run here); in bash nothing reaches the pipe at all, only zsh's MULTIOS sends it
    'echo s3curity 2 >/dev/null dump-keychain | bash',
    # card c7234bed: a substitution's output that no shell runs, and a substitution of another program (H1: what
    # ssh-agent or brew prints is not read)
    'echo "$(echo s3curity dump-keychain)"', 'cat <(echo s3curity dump-keychain)',
    'grep x <<<"$(echo s3curity dump-keychain)"', 'eval "$(ssh-agent -s)"', 'eval $(ssh-agent)',
    'eval "$(/opt/homebrew/bin/brew shellenv)"', 'eval "$(echo echo hi)"',
    # mutation round c7234bed (ev-/so-any-opener, hs-lo-zero, hs-hi-end): an opener its reader does not take as code
    # (eval runs the path /dev/fd/N, . reads the file the printed words name: bash and zsh ran nothing,
    # work/c7234bed/truth7), and a here-string to a program that is no shell next to a shell of another command
    'eval <(echo s3curity dump-keychain)', '. "$(echo s3curity dump-keychain)"',
    'bash -n x.sh; grep x <<<"$(echo s3curity dump-keychain)"',
    'grep x <<<"$(echo s3curity dump-keychain)"; bash -n x.sh',
    'bash -n x.sh && grep x <<<"$(echo s3curity dump-keychain)"',
    'grep x <<<"$(echo s3curity dump-keychain)"\nbash -n x.sh',
    # mutation round c7234bed (var-cls-off, max-gen-1): eval "$x" as quoted data reads no feeder; 64 harmless sites
    # are all read, none blocks (work/c7234bed/truth9)
    'x=$(echo s3curity dump-keychain); echo \'eval "$x"\'',
    '; '.join('eval "$(echo echo a%d)"' % i for i in range(64)),
    # M1 mutation round (rd-cls-off, feeder-cls-off, var-cls-off): a reader word in quotes is data (echo prints it),
    # a feeder word in quotes in the body is data (grep's pattern), a $x in single quotes is not expanded by the outer
    # shell (and x is not exported): bash and zsh ran nothing (work/c7234bed/m1/truth-surv.txt)
    "echo 'eval' \"$(echo s3curity dump-keychain)\"", "eval \"$(grep -c 'echo s3curity dump-keychain' notes.txt)\"",
    "x=$(echo s3curity dump-keychain); bash -c 'echo $x'",
    # M1 mutation round (doc-quoted-all): in a quoted heredoc body only a site with its own reader counts; here echo
    # prints the line (bash and zsh ran nothing, work/c7234bed/m1/truth-skip.txt)
    "bash <<'E'\necho \"$(echo s3curity dump-keychain)\"\nE",
    # card c7234bed (Viktor 48205, 2nd round): his controls, nothing secret runs (work/c7234bed/r2/truth-r2.txt)
    'echo "$(echo hi)" | bash',
    'echo "$(date)" | bash',
    'echo "$(echo s3curity dump-keychain)" | tee x.txt',
    'echo "$(echo s3curity dump-keychain)" | grep bash',
    'echo "$(echo s3curity dump-keychain)" | wc -l',
    'cat <<E | bash\necho $(date)\nE',
    'cat <<\'E\' | python3\neval "$(echo s3curity dump-keychain)"\nE',
    'echo "$1" | bash',
    'f() { echo "$1"; }; f "$(echo s3curity dump-keychain)"',
    'f() { eval "$1"; }; f hi',
    # (2nd round mutation: site-pipe-search, doc-pipe-search, doc-lexed-never) the pipe into a shell of a later command,
    # a reader in a string of a quoted heredoc body a shell reads: nothing runs (work/c7234bed/r2/truth-r2b.txt)
    'echo "$(echo s3curity dump-keychain)"; echo hi | bash',
    'x="$(echo s3curity dump-keychain)"; echo hi | bash',
    'cat <<E\n$(echo s3curity dump-keychain)\nE\necho hi | bash',
    'cat <<\'E\' > x.txt\neval "$(echo s3curity dump-keychain)"\nE\necho hi | bash',
    'bash <<\'E\'\nx=\'eval "$(echo s3curity dump-keychain)"\'\nE',
    'cat <<\'E\' | bash\nx=\'eval "$(echo s3curity dump-keychain)"\'\nE',
    # mutation round 2 c7234bed (hs-any-opener, unclosed-read-all): a here-string of a process substitution gives the
    # shell a path as its line; a substitution that never closes is a syntax error: bash and zsh ran nothing
    # (work/c7234bed/truth10, truth11)
    'bash <<< <(echo s3curity dump-keychain)',
    'eval "$(echo s3curity dump-keychain', 'eval "$(echo s3curity dump-keychain"', '. <(echo s3curity dump-keychain',
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
    'l4unchctl list',
    'l4unchctl submit -l a -o /tmp/o -- /bin/echo hi',
    'l4unchctl load -w /tmp/x.plist',
    'login',
    'echo login root s3curity dump-keychain',
    'sandbox-exec -p "(version 1)" ls',
    # the & of `>&2` / `&>` is a redirection's, no command end: the word after it is an argument (bash runs `x`)
    'x >&2 s3curity dump-keychain',
    'x &>/dev/null s3curity dump-keychain',
]
# card 04df07c5: a glob that cannot make a secret subcommand, a quoted or escaped glob char (security gets the literal
# word, no such subcommand), a glob in an argument after a literal subcommand, a ~ path
ALLOW += ["s3curity 'dump-k*'", 's3curity dump-k\\*', 's3curity "dump-keychai?"', 's3curity list-k*',
          's3curity (list-keychains)', '(s3curity list-keychains)', 's3curity add-trusted-cert *.pem',
          's3curity find-certificate -c "*.pem"', 's3curity verify-cert -c x?', 's3curity f[aeiou]nd-cert*',
          's3curity ~/x', 'setopt extendedglob; s3curity list-k*~x', 'setopt extendedglob; s3curity list-keychainss#',
          's3curity cms -D -i x.p7', 'ls dump-k*', 'echo s3curity; ls dump-keychai?']
# card 04df07c5 round 2 (Viktor 49398): his benign oracle rows, and adjacent stars before a literal: round 1 made each
# star a run of its own and the fullmatch backtracked (14 stars + x: 6.2 s and the watchdog blocked; main 0.05 s)
ALLOW += ['s3curity list-k*', "s3curity 'dump-k*'", 's3curity find-certificate -c "x*"', 's3curity dump-k\\*',
          's3curity show-keychain-info ~/x*', 'git commit --dry-run -m "fix: s3curity dump-k* now blocks" 2>/dev/null; true',
          'grep -c "s3curity dump-k" /dev/null; true', 's3curity -h', 's3curity list-keychains -d user',
          's3curity ' + '*' * 8 + 'x', 's3curity ' + '*' * 14 + 'x', 's3curity ' + '*' * 200 + 'x',
          # Kernel r2: zsh # after # nested a quantifier per # ((?:(?:x)*)*: 14 # took over 2 s in process)
          'setopt extendedglob; s3curity ' + '#' * 14 + 'x', 'setopt extendedglob; s3curity ' + '#' * 200 + 'x',
          'setopt extendedglob; s3curity list-keychains###']
BLOCK += ['setopt extendedglob; s3curity dump-keychainn###', 'setopt extendedglob; s3curity dump-keychai(n)###']


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



def _eval_nest(cmd, k):
    """Card af12091a: cmd as the innermost of k eval payloads, each level quoted for the next (shlex)."""
    import shlex
    for _ in range(k):
        cmd = 'eval ' + shlex.quote(cmd)
    return cmd


def script_git_cases():
    """Card 8d8298c7 (Viktor 50515 MEDIUM, 50542): a script FILE's text is judged by git's helper rules too, and the
    one exemption, this tree's scripts/gh-pr.mjs named by an absolute literal path, opens nothing else. The scripts
    are written to a temp dir from fragments (the subcommand pair never stands whole in this file); nothing runs."""
    import shutil
    import tempfile
    CR, FL, OK = 'cred' + 'ential', 'fi' + 'll', 'osx' + 'keychain'
    repo = os.path.dirname(os.path.dirname(os.path.dirname(HOOK)))
    prod = os.path.realpath(os.path.join(repo, 'scripts', 'gh-pr.mjs'))
    fails, n = [], 0
    with tempfile.TemporaryDirectory() as d0:
        d = os.path.realpath(d0)

        def w(name, body, mode=0o644):
            path = os.path.join(d, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(body)
            os.chmod(path, mode)
            return path
        w('h.sh', f'#!/bin/sh\nprintf "protocol=https\\nhost=github.com\\n\\n" | git {CR} {FL}\n', 0o755)
        w('h2.sh', f'#!/bin/sh\ngit -C . {CR} approve < x\n', 0o755)
        w('h.py', f"import subprocess\nsubprocess.run(['git', '{CR}', '{FL}'], input=b'')\n")
        w('hs.py', f"import subprocess\nsubprocess.run('git {CR} {FL}', shell=True)\n")
        w('hk.py', f"import subprocess\nsubprocess.run(['git', '{CR}-{OK}', 'get'])\n")
        w('hc.sh', f'#!/bin/sh\ngit -c {CR}.helper={OK} fetch\n', 0o755)
        w('ok.sh', '#!/bin/sh\ngit fetch origin\nHOME=/tmp/x git status\n', 0o755)
        w('okword.py', f"print('the {CR} file is read elsewhere; {FL} the form')\n")
        w('helper.cjs', f"require('child_process').execFileSync('git', ['{CR}', '{FL}'])\n")
        w('helper.mjs', f"import {{ execFileSync }} from 'node:child_process'; execFileSync('git', ['{CR}', '{FL}'])\n")
        w('ok.js', "console.log(1)\n")
        w('HANDOFF.md', f'# handoff\n- the shapes that ran the helper:\n```\ngit -C . {CR} approve < x\n'
                        f'git -c {CR}.helper={OK} fetch\n```\n')
        w('x.txt', 'data\n')
        w('runner.sh', '#!/bin/sh\nbash "$1"\n', 0o755)
        w(os.path.join('scripts', 'gh-pr.mjs'), f"import {{ execFileSync }} from 'node:child_process'; "
                                                f"execFileSync('git', ['{CR}', '{FL}'])\n")
        with open(prod, encoding='utf-8') as f:
            real_body = f.read()
        w('gh-pr.mjs.bak', real_body)
        w(os.path.join('x', 'marveen', 'scripts', 'gh-pr.mjs'), real_body)
        os.symlink(prod, os.path.join(d, 'gh-link.mjs'))
        os.symlink(os.path.join(d, 'scripts', 'gh-pr.mjs'), os.path.join(d, 'other-link.mjs'))
        S = d + '/h.sh'
        H = d + '/hc.sh'
        rows = [
            # Viktor 50515: the shapes that ran git's keychain helper unseen (a script file's text)
            (f'bash {S}', 2), (f'bash {S} | tee {d}/o', 2), (f'bash {S} > {d}/o', 2), (f'bash {S} | cat', 2),
            (f'bash {S}; echo done', 2), (f'cd {d} && ./h.sh', 2), (f'sh {S} | tee {d}/o', 2),
            (f'bash {d}/h2.sh', 2), (f'python3 {d}/h.py', 2), (f'python3 {d}/hs.py', 2), (f'python3 {d}/hk.py', 2),
            (f'sh {d}/hc.sh', 2),
            # controls: a plain git run, a HOME change, the words in prose
            (f'bash {d}/ok.sh', 0), (f'python3 {d}/okword.py', 0),
            # the exemption: an absolute literal path to this tree's gh-pr.mjs, or a symlink to it
            (f'node {prod} pr view 1', 0), (f'node {d}/gh-link.mjs pr view 1', 0),
            (f'cd {d} && node {prod} pr view 1', 0),
            # Viktor 50542 1: a relative name stays under the rule (the gate's cwd reckoning is the weak spot)
            (f'cd {d} && node scripts/gh-pr.mjs pr view 1', 2), ('node scripts/gh-pr.mjs pr view 1', 2),
            (f'echo {prod}; node scripts/gh-pr.mjs pr view 1', 2),
            # Viktor 50542 3: an exact realpath, no prefix or suffix match, no copy
            (f'node {d}/gh-pr.mjs.bak pr view 1', 2), (f'node {d}/x/marveen/scripts/gh-pr.mjs pr view 1', 2),
            (f'node {prod} pr view 1; node {d}/other-link.mjs', 2),  # another scripts/gh-pr.mjs behind a symlink
            # Viktor 50542 2: the rest of the command is judged as before
            (f'node {prod} pr view 1 && bash {S}', 2), (f'bash {S}; node {prod} pr view 1', 2),
            (f'node {prod} pr view 1 && python3 {d}/h.py', 2),
            # Viktor 50542 2: node's preload options are read as files of their own, the exemption does not cover them
            (f'cd {d} && node -r ./helper.cjs {prod} pr view 1', 2), (f'cd {d} && node --import ./helper.mjs {prod} x', 2),
            (f'cd {d} && NODE_OPTIONS=--require ./helper.cjs node {prod} x', 2),
            (f'cd {d} && node --loader ./helper.mjs {prod} x', 2),
            # KNOWN-LIMIT node-options-quoted (main too, not opened by the exemption): a quoted or `=` NODE_OPTIONS
            # value's preload file is not read, with any script
            (f'cd {d} && NODE_OPTIONS="--import ./helper.mjs" node {prod} x', 0),
            (f'cd {d} && NODE_OPTIONS="--import ./helper.mjs" node ./ok.js', 0),
            # round 2 (Viktor 50625): git's rules for a file the command runs or feeds to code. hc.sh: only git's
            # rules see it (h.sh holds the literal pair main blocks anyway). Run: source, dot, stdin redirect,
            # process substitution
            (f'source {H}', 2), (f'. {H}', 2), (f'bash < {H}', 2), (f'bash <(cat {H})', 2), (f'source <(cat {H})', 2),
            # fed: piped straight into an interpreter, or read by eval / -c through a substitution
            (f'cat {H} | sh', 2), (f'cat {H} | bash -s', 2), (f'head -50 {H} | bash', 2),
            (f'cat {d}/hk.py | python3', 2), (f'cat {d}/hk.py | python3 -', 2),
            (f'eval "$(cat {H})"', 2), (f'eval "`cat {H}`"', 2), (f'bash -c "$(cat {H})"', 2),
            (f'sh -c "$(cat {H})"', 2), (f'zsh -c "$(cat {H})"', 2), (f'python3 -c "$(cat {d}/hk.py)"', 2),
            (f'C=$(cat {H}); bash -c "$C"', 2),
            # a data file read next to an interpreter elsewhere keeps the main rules (the fleet's HANDOFF.md read)
            (f'cat {d}/HANDOFF.md; bash {d}/ok.sh', 0), (f'head -40 {d}/HANDOFF.md && python3 {d}/okword.py', 0),
            (f'cat {d}/HANDOFF.md | grep -n x; echo a | python3 -c "import sys"', 0),
            (f'cat {d}/HANDOFF.md {d}/x.txt; node {d}/ok.js', 0),
            # ...but a run of the same text is judged by them
            (f'cat {d}/HANDOFF.md; bash {d}/HANDOFF.md', 2),
            # through a filter into a shell: the pipeline-into-a-shell reading (card 74586987) gives its words to the
            # git walk too (main allows it: no git rules on a file there)
            (f'cat {H} | grep -v x | bash', 2),
            # KNOWN-LIMIT cat-fed-indirect (Viktor 50625): a cat text run through a file the command writes first (it
            # does not exist when the gate reads the command) keeps the main rules (as on main)
            (f'cat {H} > {d}/g.sh; bash {d}/g.sh', 0),
            # round 3 (Viktor 50674): git's rules for a RUN position only. (1) the script is the first operand after
            # the interpreter's options; an option's argument is no operand; a file after it is the script's argument
            (f'bash {d}/ok.sh {d}/HANDOFF.md', 0), (f'bash {d}/ok.sh {H}', 0),
            (f'cd {d} && bash ok.sh "HANDOFF.md megirva; x" 1', 0), (f'cd {d} && bash ok.sh HANDOFF.md 2>&1 | tail -3', 0),
            (f'python3 {d}/okword.py {H}', 0), (f'python3 -W error {d}/okword.py {H}', 0),
            (f'python3 -W error {d}/hk.py', 2), (f'bash -o pipefail {H}', 2), (f'bash -o pipefail {d}/ok.sh {H}', 0),
            (f'bash -x {H}', 2), (f'bash -- {H}', 2), (f'cd {d} && node ./ok.js ./helper.cjs', 0),
            # inline code: no script file (node -e / --eval / -p)
            (f'node -e 1 {d}/helper.cjs', 0), (f'node --eval 1 {d}/helper.cjs', 0), (f'node -p 1 {d}/helper.cjs', 0),
            # an option the gate does not know: the next two operands are run (either may be the script)
            (f'node --stack-size 99 {d}/helper.cjs', 2), (f'node --frob {d}/helper.cjs', 2),
            (f'node --frob x {d}/helper.cjs', 2), (f'node --frob x y {d}/helper.cjs', 0),
            # a word that may vanish or split before the script: every word is run
            (f'cd {d} && bash $X ok.sh {H}', 2),
            # (2) a preload or rc file runs, separate and with `=`; a stdin redirect; source / dot
            (f'cd {d} && node --require=./helper.cjs ./ok.js', 2), (f'cd {d} && node --import=./helper.mjs ./ok.js', 2),
            (f'cd {d} && node --loader=./helper.mjs ./ok.js', 2), (f'cd {d} && node -r ./helper.cjs ./ok.js', 2),
            (f'cd {d} && node --experimental-loader ./helper.mjs ./ok.js', 2),
            (f'bash --rcfile {H} {d}/ok.sh', 2), (f'bash --init-file {H} {d}/ok.sh', 2),
            (f'bash {d}/ok.sh < {H}', 2), (f'source {H} x', 2),
            # KNOWN-LIMIT env-prefix-run-file: BASH_ENV / ENV in the prefix are not read (main too, any rules)
            (f'BASH_ENV={H} bash {d}/ok.sh', 0), (f'ENV={H} sh {d}/ok.sh', 0),
            # (3) KNOWN-LIMIT git-rules-on-argument-files: a script that runs its own argument file (runner.sh runs
            # "$1"); the argument gets the main rules only
            (f'bash {d}/runner.sh {H}', 0), (f'source {d}/runner.sh {H}', 0), (f'. {d}/runner.sh {H}', 0),
            # KNOWN-LIMIT dash-c-argument (an over-block, the safe side): after a -c payload the gate's payload view
            # reads the next word as a command word, so `bash -c '...' f` judges f by git's rules (main: its rules)
            (f"bash -c 'echo 1' {H}", 2),
            # KNOWN-LIMIT pipe-into-shell-with-script (an over-block, the safe side): the pipeline-into-a-shell reading
            # takes what a pipe prints as the shell's code even when the shell runs a script file
            (f"cd {d} && printf '%s\\n' 'HANDOFF.md x' | bash {d}/ok.sh", 2),
            # round 4 (Viktor 50741 A): a subcommand word in the first operand position is no script; the next
            # operand is (bun run / x / exec / test, deno run / test, tsx watch, node inspect)
            (f'bun run {d}/helper.cjs', 2), (f'bun run --silent {d}/helper.cjs', 2), (f'bun run --hot {d}/helper.cjs', 2),
            (f'bun x {d}/helper.cjs', 2), (f'bun test {d}/helper.cjs', 2), (f'bun exec {d}/helper.cjs', 2),
            (f'deno run {d}/helper.cjs', 2), (f'deno run -A {d}/helper.cjs', 2), (f'tsx watch {d}/helper.cjs', 2),
            (f'node inspect {d}/helper.cjs', 2), (f'cd {d} && bun run ./helper.cjs', 2),
            # controls: the file after the script is its argument; a second subcommand word is an operand
            (f'bun run {d}/ok.js {d}/helper.cjs', 0), (f'tsx watch {d}/ok.js {d}/helper.cjs', 0),
            (f'node inspect {d}/ok.js {d}/helper.cjs', 0),
            # after an option the gate does not know, a subcommand word may still be the first operand (--frob may take
            # x): the file after it is run (round-4 mutation: a first-operand-only skip passed it)
            (f'node --frob x inspect {d}/helper.cjs', 2), (f'bun --frob x run {d}/helper.cjs', 2),
            # round 4 (Viktor 50741 B): a shell's +option is an option (+o / +O take a value)
            (f'bash +x {H}', 2), (f'bash +e {H}', 2), (f'sh +e {H}', 2), (f'bash +o posix {H}', 2),
            (f'zsh +o nomatch {H}', 2), (f'bash +O extglob {H}', 2), (f'bash +o posix {d}/ok.sh {H}', 0),
            # round 4 (Viktor 50741, old): a shell's lone `-` is its `--` (bash(1)): the next word is the script
            (f'bash - {H}', 2), (f'sh - {H}', 2), (f'bash -x - {H}', 2), (f'bash - {d}/ok.sh {H}', 0),
            # KNOWN-LIMIT git-rules-on-argument-files: `python3 -m runpy f` (a module runs its argument file)
            (f'python3 -m runpy {H}', 0),
            # KNOWN-LIMIT find-exec-computed-name: find computes the name it runs; the file keeps the main rules
            (f'find {d} -name hc.sh -exec bash {{}} \\;', 0),
        ]
        for cmd, want in rows:
            n += 1
            cwd = repo if 'scripts/gh-pr.mjs' in cmd and 'cd ' not in cmd else d
            code, err = bash_in(cmd, cwd)
            if code != want:
                fails.append(f'script-git: want {want}, got {code}: {cmd.replace(d, "<tmp>")[:110]!r} {err[:80]}')
        shutil.rmtree(os.path.join(d, 'x'), ignore_errors=True)
    return fails, n


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
        w('feedhi.sh', 'echo "$(echo hi)" | bash\n')  # card 0196e1ee m6: a harmless fed substitution in a file
        w('ok.js', "console.log('ok');\n")
        w('a b.py', "import subprocess\nSEC = '/usr/bin/" + S + "'\n"  # card 946937b7: a script name with a blank
                    "subprocess.run([SEC, 'find-generic-password', '-a', 'acct', '-s', 'svc'])\n")
        os.makedirs(os.path.join(d, 'evilmod'), exist_ok=True)
        w(os.path.join('evilmod', '__main__.py'), "import subprocess\nsubprocess.run(['" + S + "', 'dump-keychain'])\n")
        w('runner.sh', 'python3 "$1"\n')  # runs its first argument: `source runner.sh m.py` runs m.py
        # card b138f11b: script names holding a quoted "$(" or paren (bash and zsh run them as written)
        for name in ('$(true)m.py', ')m.py', '(m.py'):
            w(name, "import subprocess\nsubprocess.run(['" + S + "', 'dump-keychain'])\n")
        w('$(true)runner.sh', 'python3 "$1"\n')
        w('(ok.py', 'print(1)\n')
        w('word.py', "print('the " + S + " team writes find-generic-password docs')\n")
        # card 31045f4d (Klodel 43233, Viktor 43235): a data file whose text names the blocked call (the error
        # register), and a script that only counts its lines
        w('regiszter.jsonl', '{"ts":"11-14","cmd":"' + S + ' find-generic-password -s x -w"}\n')
        w('stat.py', "import sys\nprint(sum(1 for _ in open(sys.argv[1])))\n")
        # card 3bf9a741 (fleet replay 2026-11-21): a script file read line by line for xargs. A harmless list of many
        # xargs rows (data commands, a quote that a Python string leaves open at the line's end, a one-line heredoc
        # written with \n escapes, an xargs no | stands right before below many pipelines) runs nothing; the same
        # rows above a real `| xargs <binary>` line still read it
        rows = (['    "echo a%d | xargs grep x",' % i for i in range(200)]
                + ['    "echo b | xargs sed s/a/b/ | wc -l",' for _ in range(70)]
                + ["    'echo x | xargs tmux kill-server',", "    \"xargs python3 <<'E'\\nstat.py\\nE\","]
                + ['    "a | b | c %d",' % i for i in range(600)] + ['    "then xargs echo done",'])
        w('xrows.py', 'ROWS = [\n' + '\n'.join(rows) + '\n]\nprint(len(ROWS))\n')
        w('xrun.sh', '#!/bin/sh\necho dump-keychain | xargs ' + S + '\n')
        w('xrun2.sh', '#!/bin/sh\n' + 'echo a | xargs sed s/a/b/\n' * 100 + 'echo dump-keychain | xargs ' + S + '\n')
        w('xrun3.sh', "#!/bin/sh\nxargs " + S + " <<'E'\ndump-keychain\nE\n")  # a closed heredoc: still read
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
        # card 8a73eab1 r3 (Viktor 49502 LELET 1): a keychain file whose name holds [1] (a name list's glob blocks it,
        # escaped), and one [1] as a character class would match (escaped: not matched)
        w('m[1]HOMEx.py', "import subprocess\nsubprocess.run(['" + S + "', 'dump-keychain'])\n")
        w('k1Zq.py', "import subprocess\nsubprocess.run(['" + S + "', 'dump-keychain'])\n")
        # card 00c714ea r2 (Viktor 49408 LOW 1): a glob's first match in the locale's order: under en_US.UTF-8 bash
        # and zsh put _a.py before -a.py, the byte and case-folded order put -a.py first
        os.makedirs(os.path.join(d, 'loc'))
        w(os.path.join('loc', '-a.py'), 'print(1)\n')
        w(os.path.join('loc', '_a.py'), "import subprocess\nsubprocess.run(['" + S + "', 'dump-keychain'])\n")
        # card 00c714ea r2: a hidden file a zsh group names (`(.hm|zz).py` ran .hm.py, zsh -f, measured 11-21)
        os.makedirs(os.path.join(d, 'hid'))
        w(os.path.join('hid', '.hm.py'), "import subprocess\nsubprocess.run(['" + S + "', 'dump-keychain'])\n")
        # ... and hu_HU.UTF-8's order: cz before cs in bash and zsh (byte, case-folded and en_* order: cs first)
        os.makedirs(os.path.join(d, 'loc2'))
        w(os.path.join('loc2', 'cs.py'), 'print(1)\n')
        w(os.path.join('loc2', 'cz.py'), "import subprocess\nsubprocess.run(['" + S + "', 'dump-keychain'])\n")
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
        # card deede5e4 (mutation round 2): a clean directory whose name the glob `on*` shares with sub2/only.py
        os.makedirs(os.path.join(d, 'onlypkg'))
        with open(os.path.join(d, 'onlypkg', '__main__.py'), 'w', encoding='utf-8') as f:
            f.write("print(1)\n")
        # card deede5e4 r2 (Viktor 49087 R1): lnk -> phys/inner; physically lnk/.. is phys, whose twin.py is the
        # keychain one (logically lnk/.. is d, whose twin.py prints 1)
        os.makedirs(os.path.join(d, 'phys', 'inner'))
        with open(os.path.join(d, 'phys', 'twin.py'), 'w', encoding='utf-8') as f:
            f.write("import subprocess\nsubprocess.run(['" + S + "', 'dump-keychain'])\n")
        os.symlink(os.path.join(d, 'phys', 'inner'), os.path.join(d, 'lnk'))
        # card c6c67dde r2 (Viktor 50201 R1): amlnk -> this repo's scripts/; logically amlnk/.. is d (whose
        # scripts/agent-msg.sh is the look-alike), physically it is this repo's root
        os.symlink(os.path.join(AM_ROOT, 'scripts'), os.path.join(d, 'amlnk'))
        sub = os.path.join(d, 'sub')
        os.makedirs(sub)
        with open(os.path.join(sub, 'deep.py'), 'w', encoding='utf-8') as f:
            f.write("SEC = '" + S + "'\nimport subprocess; subprocess.run([SEC, 'dump-keychain'])\n")
        # card 15896271: a run's output that quotes the blocked call (a negative test run's log)
        w('out.txt', "FAIL should block: '/usr/bin/env " + S + " dump-keychain'\n")
        # card 03a336e5 (fleet replay 2026-11-19: a kanban dump read by a python heredoc, a PR.md, a .diff blocked): a
        # made command name in a file counts only where a shell may run the file (_hn_shell_file)
        # the card's own JSON as /api/kanban gives it (the replay's kb.json: the title's backticks and the \" pieces
        # leave `$(printf %s S) find-generic-password` at a command position), and a Markdown list of the forms
        w('kb.json', '[{"id":"03a336e5","title":"x ($(echo S) dump-K, `echo S` ...) y","description":"S = name.\\n'
                     '- $(echo S) dump-K\\n- `echo S` dump-K\\n- \\"$(echo S)\\" dump-K\\n- $(echo se..)$(echo ..ty) dump-K\\n'
                     '- $(printf %s S) find-generic-password -s x -w\\n\\nmore"}]\n')
        w('pr.md', '- $(printf %s S) find-generic-password -s x -w\n- `$S dump-keychain`\n')
        w('made.sh', '$(echo ' + S + ') dump-keychain\n')
        w('made', 'x=$(echo ' + S + '); $x dump-keychain\n')
        w('made.md', '$S dump-keychain\n')
        w('madebang.py', '#!/usr/bin/env bash\n$S find-generic-password -s x\n')
        # card 3bcd4514 (Viktor 48033 LOW L1): a data file a shell reads as code on its stdin or from a substitution,
        # and a shell file with the call in it for the stdin forms the gate did not collect (0<, a1<, eval)
        w('made.json', '$S dump-keychain\n')
        w('lit.sh', S + ' dump-keychain\n')
        cf_curl = ('curl -s -X POST localhost:3420/api/kanban/x/comments -H "Content-Type: application/json" '
                   '-H "Authorization: Bearer $(cat store/.dashboard-token)" --data-binary @- ')
        block = [
            ('python3 measure.py', d),
            # card 03a336e5: a made name in a file a shell runs (an .sh, no extension, a shell shebang, a shell word or
            # source before a data file's name)
            ('bash made.sh', d), ('sh ./made', d), ('bash made.md', d), ('/bin/zsh -e made.md', d), ('source made.md', d),
            ('. ./made.md', d), ('./madebang.py', d), ('./made', d),
            # card 3bcd4514 (Viktor 48033 LOW L1, bash and zsh ran each; gate-bash-truth 11-20): the file on a shell's
            # stdin (a pipe, a < redirect, -s, -), in a substitution a shell or eval runs, a <( a shell or source reads,
            # and a shell's option that takes a word (-o, +O, -eo, --rcfile) before its name
            ('cat made.json | bash', d), ('bash < made.json', d), ('bash -c "$(< made.json)"', d),
            ('bash -o errexit made.md', d), ('cat made.json | sh -s', d), ('< made.json bash', d), ('zsh 0<made.json', d),
            ('head -n 5 made.json | bash', d), ('eval "$(cat made.json)"', d), ('bash -c "$(cat made.json)"', d),
            ('source <(cat made.json)', d), ('. <(< made.json)', d), ('bash <(cat made.json)', d),
            ('bash -eo pipefail made.md', d), ('bash +O extglob made.md', d), ('bash --rcfile x made.md', d),
            ('cat made.json | source /dev/stdin', d), ('bash -s < made.json', d), ('bash - < made.json', d),
            ('bash -s a1<made.json', d), ('cat < made.json | bash', d),
            # ... and the stdin forms the gate did not collect at all (a literal call ran on main): fd 0, a digit glued
            # to a word (no fd: the < is stdin's), eval of a cat or < substitution
            ('bash 0<lit.sh', d), ('bash -s a1<lit.sh', d), ('eval "$(cat lit.sh)"', d), ('eval "$(< lit.sh)"', d),
            ('eval `cat lit.sh`', d),
            # (mutation-round rows, bash and zsh ran each) a shell word ending a line, a quoted shell word, a path to
            # the file, head / tail in a substitution, a pipe word of a filter that is no reader (sed), . /dev/fd/0, a
            # redirect before the reader (`< x cat f`, `2>/dev/null cat f`: cat is the command), and the literal file
            ('cat made.json | bash\necho x', d), ("cat made.json | 'bash'", d), ('eval "$(cat ./made.json)"', d),
            ('eval "$(head made.json)"', d), ('eval "$(tail made.json)"', d), ('sed -n p made.json | bash', d),
            ('cat made.json | . /dev/fd/0', d), ('< stat.py cat made.json | bash', d),
            ('eval "$(2>/dev/null cat made.json)"', d), ('eval "$(< stat.py cat made.json)"', d),
            ('eval "$(head -n 1 lit.sh)"', d), ('eval "$(tail -n 1 lit.sh)"', d),
            # head / tail piped straight into an interpreter that reads its stdin as code (-E is no -e)
            ('tail -n 1 lit.sh | python3', d), ('head lit.sh | node', d), ('tail -1 out.txt | python3 -E', d),
            ('head -n 1 lit.sh | bash -s', d), ('/usr/bin/head lit.sh | bash', d), ('eval `head lit.sh`', d),
            ('/usr/bin/tail -n 1 lit.sh | python3', d), ('eval "$(/usr/bin/head lit.sh)"', d),
            # --init-file, more options than the walk reads (fail-closed), -c not last in its cluster, a path to cat,
            # a backtick substitution, a quoted pipe word; eval quoted or escaped (the gate's interpreter forms)
            ('bash --init-file x made.md', d), ('bash' + ' -x' * 17 + ' made.md', d), ('bash -cx "$(cat made.json)"', d),
            # (mutation rd-over-off) past the walk's options a shell the file-name rule does not know ($SHELL,
            # bash5) reading its stdin: only the reader's own fail-closed branch sees it
            ('cat made.json | $SHELL' + ' -x' * 17, d), ('cat made.json | bash5' + ' -x' * 17, d),
            # (mutation rd-end-paren) the reader's command ends at a substitution's or a subshell's )
            ('x=$(cat made.json | bash)', d), ('(cat made.json | bash)', d), ('echo "$(cat made.json | sh)"', d),
            # (mutation rd-fd) a reader with an fd redirect after it (its output, not its stdin)
            ('cat made.json | bash 2>/dev/null', d), ('cat made.json | sh 2>&1', d),
            # (mutation rd-s) -s with the script's own arguments after it: stdin is still the script
            ('cat made.json | bash -s x', d), ('bash -s -- a b < made.json', d), ('cat made.json | sh -xs y', d),
            # (mutation fed-lstrip) fd 0 with a blank before the name (the file-name rule reads `0<f` glued only)
            ('bash 0< made.json', d), ('sh -s 0< made.json', d),
            # (found by it) a shell under a name INTERP does not list reads its stdin: the file was not collected
            # at all, a literal call ran on main and on the branch before this row
            ('$SHELL < made.json', d), ('$SHELL 0<made.json', d), ('bash5 -s < lit.sh', d), ('fish < lit.sh', d),
            ('$SHELL < lit.sh', d),
            ('eval "$(/bin/cat made.json)"', d), ('eval `cat made.json`', d), ("sed -n p 'made.json' | bash", d),
            ('eval "$(/bin/cat lit.sh)"', d), ('"eval" "$(cat lit.sh)"', d), ('\\eval "$(cat lit.sh)"', d),
            # (Viktor 48464 M1, L1: his matrix, bash and zsh ran them) head / tail after a wrapper or an assignment
            # in a substitution or a <(, a wrapper or NAME= before cat / head / tail, a comment after the reader,
            # /dev/stdin or /dev/fd/0 as the shell's operand
            ('eval "$(command cat made.json)"', d), ('eval "$(LC_ALL=C cat made.json)"', d),
            ('eval "$(env cat made.json)"', d), ('eval "$(nice cat made.json)"', d),
            ('eval "$(exec cat made.json)"', d), ('eval "$(time cat made.json)"', d),
            ('bash -c "$(command cat made.json)"', d), ('source <(command cat made.json)', d),
            ('bash <(LC_ALL=C cat made.json)', d), ('command cat made.json | bash', d),
            ('LC_ALL=C cat made.json | bash', d), ('eval "$(command head made.json)"', d),
            ('eval "$(sudo cat made.json)"', d), ('eval "$(nohup cat made.json)"', d),
            ('cat made.json | bash # x', d), ('bash < made.json # x', d), ('cat made.json | bash #', d),
            ('cat made.json|bash', d), ('cat made.json |& bash', d), ('cat made.json | bash\t# x', d),
            ('cat made.json | bash /dev/stdin', d), ('bash /dev/stdin < made.json', d),
            ('bash /dev/fd/0 < made.json', d), ('exec 3<made.json; bash <&3', d),
            # (mutation round 3, gate-bash-truth 11-20: bash and zsh ran them, main allowed) the operand quoted, a --
            # after nice; the number word before cat for a sudo flag with a value (not measured: sudo asks a password)
            ("cat made.json | bash '/dev/stdin'", d), ('bash "/dev/stdin" < made.json', d),
            ("bash '/dev/fd/0' < made.json", d), ('eval "$(nice -- cat made.json)"', d),
            ('eval "$(sudo -T 5 cat made.json)"', d),
            ('read -r x < made.json; eval "$x"', d), ('bash <<< "$(cat made.json)"', d),
            ('cat made.json | tee /dev/null | bash', d), ('cat made.json | /bin/bash', d),
            ('cat made.json | env bash', d), ('cat made.json | command bash', d),
            ('cat made.json | xargs -0 bash -c', d), ('cat made.json | bash -O extglob', d),
            ('cat made.json | bash --norc', d), ('cat made.json | bash -l', d), ('cat -- made.json | bash', d),
            ('cat -u made.json | bash', d), ('cat made.json - | bash', d), ('cat "made.json" | bash', d),
            ('cat ma"de".json | bash', d), ('cat made\\.json | bash', d), ('eval "$(cat <made.json)"', d),
            ('eval "$(<made.json cat)"', d), ('source /dev/fd/0 < made.json', d), ('zsh -s < made.json', d),
            ('cat made.json | dash', d), ('cat made.json | ksh', d), ('cat made.json | sh -c "$(cat)"', d),
            ('bash -c "$(cat made.json)" x', d), ('eval "$(command cat lit.sh)"', d),
            ('eval "$(LC_ALL=C cat lit.sh)"', d), ('command cat lit.sh | bash', d), ('cat lit.sh | bash # x', d),
            ('read -r x < lit.sh; eval "$x"', d), ('bash /dev/stdin < lit.sh', d), ('exec 3<lit.sh; bash <&3', d),
            ('eval "$(env cat lit.sh)"', d), ('eval "$(command head lit.sh)"', d),
            ('eval "$(LC_ALL=C head lit.sh)"', d), ('eval "$(nice tail lit.sh)"', d),
            ('eval "$(env head -n 9 lit.sh)"', d), ('bash -c "$(command tail lit.sh)"', d),
            ('eval "`command head lit.sh`"', d), ('eval "$(nice -n 5 head lit.sh)"', d),
            ('eval "$(nice -n 5 cat made.json)"', d), ('eval "$(env -u X cat made.json)"', d),
            ('A=1 B=2 cat made.json | bash', d), ('source <(tail -n 5 lit.sh)', d),
            ('source <(LC_ALL=C tail lit.sh)', d), ('. <(command head -n 3 lit.sh)', d),
            ('eval "$(timeout 5 head lit.sh)"', d),
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
            # card 8a73eab1 (Dave's audit 11-16): a variable glued to the name is empty when unset or set to ""
            # (main: allow); ${X:-w} gives w, ${X+w} gives w for a set-to-"" X; read with quotes and substitutions too
            ('python3 measure${X}.py', d),
            ('python3 measure$X.py', d),
            ('python3 "meas"ure${X}.py', d),
            ('X=; python3 measure$X.py', d),
            ("X=''; python3 measure$X.py", d),
            ('python3 measure${X:-}.py', d),
            ('python3 meas${X:-ure}.py', d),
            ('python3 meas${X-ure}.py', d),
            ('X=; python3 meas${X+ure}.py', d),
            ('python3 ${D}measure.py', d),
            ('python3 "$D"measure.py', d),
            ('python3 measure"${X}".py', d),
            ('python3 meas${X:-${Y:-${Z:-ure}}}.py', d),
            ('python3 measure${X#a}.py', d),
            ('python3 measure${X/a/b}.py', d),
            ('python3 measure${X:0:1}.py', d),
            ('python3 $(true)measure$X.py', d),
            ('python3 -I measure$X.py stat.py', d),
            ('python3 ' + '${A:-' * 8 + 'measure' + '}' * 8 + '.py', d),
            ('python3 ' + '${A:-' * 10 + 'stat' + '}' * 10 + '.py', d),  # nested past MAX_VAR_NEST: not read
            ('bash dump$X.sh', d),
            ('./dump$X.sh', d),
            ('source dump$X.sh', d),
            ('source $X dump.sh', d),
            # an expansion the shell may not make: `echo X=a` sets nothing, $X is empty (expand() read it as "a")
            ('echo X=a; python3 measure$X.py', d),
            ('X=a true; python3 measure$X.py', d),
            # Viktor r1 (49425): zsh's forms of a glued variable (the fleet's Bash tool is zsh): a subscript and a
            # modifier on a plain name, a flag in a brace (cut at its paren: blocks), $= $~ and an empty name
            ('python3 measure$X[1].py', d),
            ('python3 measure$X:r.py', d),
            ('python3 measure${(L)X}.py', d),
            ('python3 measure${=X}.py', d),
            ('python3 measure${~X}.py', d),
            ('python3 measure$=X.py', d),
            ('python3 measure$~X.py', d),
            ('python3 ${${X}:-meas}ure.py', d),
            ('python3 ${:-meas}ure.py', d),
            ('python3 meas${!HOM*}ure.py', d),  # the names of variables: any run, a glob (Kernel r2)
            ('./meas${!HOM*}ure.py', d),
            # Kernel r2 (measured in zsh 5.9): :h gives ".", :a :c :s give "", a pattern substitution's replacement,
            # ${X::=w}; :P (the cwd) is not read and blocks, whatever the name
            ('python3 measure$X:hpy', d),
            ('python3 measure$X:a.py', d),
            ('python3 measure$X:c.py', d),
            ('python3 measure$X:s/a/b/.py', d),
            ('python3 measure$X:gs/a/b/.py', d),
            ('python3 measure$X:s^a^b^.py', d),
            ('python3 meas${X/#/ure}.py', d),
            ('python3 meas${X/%/ure}.py', d),
            ('python3 meas${X//*/ure}.py', d),
            ('python3 meas${X::=ure}.py', d),
            ('python3 measure${X:h}py', d),
            ('python3 meas${X:-"ure"}.py', d),
            ('python3 notes$X:P.py', d),
            # Kernel r3 (Viktor 49502 LELET 1): a cut zsh flag group blocks: what follows its paren may name a dot
            # file or a path in a subdirectory, which a glob does not see (prop2 blocked all of these)
            ('python3 .m${(L)X}easure.py', d),  # cutgroup-dotfile
            ('python3 "n${(L)X}.otes.py"', d),  # cutgroup-dq-dotfile (a glob n* sees only notes.py)
            ('python3 su${(L)X}b/deep.py', d),  # cutgroup-prefix-subdir
            ('X=; python3 su${(L)X}b/deep.py', d),  # cutgroup-set-value-subdir
            ("python3 'm[1]'${(L)X}x.py", d),  # cutgroup-bracket-in-name
            ("python3 'm[1]'${!HOM*}x.py", d),  # namelist-bracket-in-name: the word's literal parts glob-escaped
            # (LELET 2) a subscript in a brace with a default word: empty, so the word
            ('python3 meas${X[1]:-ure}.py', d),  # brace-array-index-default
            ('python3 meas${X[@]:-ure}.py', d),  # brace-array-at-default
            # (LELET 3) zsh's modifier chain: :a / :A after :h (the cwd), :P after :s, a substitution after :h,
            # an escaped delimiter in :s, :&, and ${X:/p/r}
            ('python3 notes$X:h:a.py', d),  # zmod-h-then-a (not read: blocks, whatever the name)
            ('python3 notes$X:h:A:t.py', d),
            ('python3 notes${X:h:a}.py', d),  # zmod-brace-h-a
            ('python3 notes$X:s/a/b/:P.py', d),  # zmod-s-then-P
            ('python3 notes${X:s/a/b/:P}.py', d),
            ('python3 meas$X:h:s/./ure/.py', d),  # :h gives ".", the substitution its replacement
            ('python3 meas$X:h:s/\\/x/ure/.py', d),  # zmod-s-escaped-delim
            ('python3 "meas$X:&ure.py"', d),  # zmod-unlisted-amp-dq
            ('python3 meas${X:/*/ure}.py', d),  # zsubst-colon-slash
            # (LELET 4) a NUL in the word as written blocks (bash drops it reading a script file)
            ('python3 .meas\x00ure.py', d),  # nul-raw-dotfile
            ('python3 sub/\x00deep.py', d),  # nul-raw-subdir
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
            # card 10624d73: the expansion is trusted only for a plain top-level assignment the shell surely makes
            # before the use; each of these leaves $X empty or another value in bash (oracle-checked), and blocks
            ('false && X=stat.py; python3 $X ./measure.py', d),
            ('true || X=stat.py; python3 $X ./measure.py', d),
            ('X=stat.py | true; python3 $X ./measure.py', d),
            ('X=stat.py & python3 $X ./measure.py', d),
            ('(X=stat.py); python3 $X ./measure.py', d),
            ('$(X=stat.py); python3 $X ./measure.py', d),
            ('if false; then X=stat.py; fi; python3 $X ./measure.py', d),
            ('f() { X=stat.py; }; python3 $X ./measure.py', d),
            ('X=stat.py; X=; python3 $X ./measure.py', d),
            ('python3 $X ./measure.py; X=stat.py', d),
            ('X=stat.py; read X < /dev/null; python3 $X ./measure.py', d),
            ("X=stat.py; eval 'X='; python3 $X ./measure.py", d),
            ("X=stat.py; trap 'X=' DEBUG; python3 $X ./measure.py", d),
            ('X=stat.py; . ./nosuch.sh; python3 $X ./measure.py', d),
            ('X=stat.py; IFS=.; python3 $X ./measure.py', d),
            ("X=stat.py; bash -c 'python3 $X ./measure.py'", d),  # single-quoted: the inner bash has no X
            ('(true; X=stat.py); python3 $X ./measure.py', d),  # a subshell, not right after its "("
            ('$(true; X=stat.py); python3 $X ./measure.py', d),
            ('X=stat.py; eval "unset $(printf \'\\x58\')"; python3 $X ./measure.py', d),  # unset without the name
            # card 10624d73 round 2 (Viktor 49224 MEDIUM): a shell step between the assignment and the use that
            # changes the name without naming it, or an assignment the shell does not make as written; bash or zsh
            # ran the script in each (his oracle, own/out3.txt and indep-kcet-head.txt); round 1 allowed them
            ('\\X=stat.py; python3 $X ./measure.py', d),  # bs-name
            ('X\\Y=stat.py; python3 $XY ./measure.py', d),  # bs-mid-name
            ('X""Y=stat.py; python3 $XY ./measure.py', d),  # dq-empty-in-name
            ("X''Y=stat.py; python3 $XY ./measure.py", d),  # sq-empty-in-name
            ('false &&\nX=stat.py\npython3 $X ./measure.py', d),  # nl-after-and
            ('true ||\nX=stat.py\npython3 $X ./measure.py', d),  # nl-after-or
            ('if false\nthen\nX=stat.py\nfi\npython3 $X ./measure.py', d),  # if-nl
            ('f() {\nX=stat.py\n}\npython3 $X ./measure.py', d),  # func-def
            ('false && {\nX=stat.py\n}\npython3 $X ./measure.py', d),  # brace-and
            ('X=stat.py; unset "$(printf \'\\x58\')"; python3 $X ./measure.py', d),  # unset-hex
            ('X=stat.py; unset "$(printf \'\\130\')"; python3 $X ./measure.py', d),  # unset-oct
            ('X=stat.py; declare "$(printf \'\\x58\')=-I"; python3 $X ./measure.py', d),  # declare-hex
            ('REPLY=stat.py; read <<< -I; python3 $REPLY ./measure.py', d),  # read-REPLY
            ('_=stat.py; : -I; python3 $_ ./measure.py', d),  # underscore
            ('OPTARG=stat.py; getopts a: o -a -I; python3 $OPTARG ./measure.py', d),  # getopts-OPTARG
            ("X=stat.py; source'' ./s.sh; python3 $X ./measure.py", d),  # source-quoted
            ("X=stat.py; '.' ./s.sh; python3 $X ./measure.py", d),  # dot-quoted
            ('X=stat.py; python3 $X:h ./measure.py', d),  # zsh-modifier-h
            ("''X=stat.py; python3 $X ./measure.py", d),  # emptyquote-assign
            # card 00c714ea (Viktor 49241 follow-up; old, main and 10624d73 passed each, bash ran measure.py in his
            # oracle's twins): a value the shell reads otherwise than the gate (a glob, a blank or a brace at an
            # unquoted use, an escape, a name split by quotes), and a script word's own brace expansion and glob
            ('X=m*.py; python3 $X stat.py', d),  # value-glob-star
            ('X=[m]easure.py; python3 $X stat.py', d),  # value-glob-bracket
            ("X='measure.py stat.py'; python3 $X", d),  # value-sq-space-split
            ('X=measure.py\\ stat.py; python3 $X', d),  # value-esc-space-split
            ('X=\\ ; python3 $X measure.py', d),  # value-esc-space-empty
            ('X=measure\\.py; python3 $X stat.py', d),  # value-escape
            ('export "HO"ME=' + d + '/measure.py; python3 $HOME stat.py', d),  # home-export-split
            ('X=stat.py; python3 {measure.py,$X}', d),  # brace-expansion
            ('python3 {measure.py,stat.py}', d),
            # a lean, not an attack (Viktor 49408 LOW 3): the shells run leasure.py and give measure.py as its argv;
            # every word a brace makes is read as a script (KNOWN-KTP-OVER in the module header)
            ('python3 {l..n}easure.py stat.py', d),
            ('python3 m*.py stat.py', d),
            # card 00c714ea r2 (Viktor 49408 LOW 1; old, main passed each, bash 3.2 / zsh -f ran measure.py): a
            # negated bracket the shells read as [!x], a zsh group or qualifier (its words arrive cut at ) and |),
            # a ** that matches no directory
            ('python3 [^s]easure.py stat.py', d),
            ('python3 m[^x]asure.py stat.py', d),
            ('python3 (measure|zz).py stat.py', d),
            ('python3 (m|q)easure.py stat.py', d),
            ('python3 m*.py(.) stat.py', d),
            ('python3 m*(N) stat.py', d),
            ('python3 **/measure.py stat.py', d),
            # card 00c714ea r2: a group with no glob char before it (zsh -f with the fleet Bash tool's setopts ran
            # measure.py for `m(easure.py|x)`), a qualifier on a plain word (plain `zsh -c`), a hidden file
            ('python3 m(easure.py|x) stat.py', d),
            ('python3 measure.py(.) stat.py', d),
            ('cd hid && python3 (.hm|zz).py x', d),
            # ... a quoted or a nested member (zsh -f ran measure.py), and the call after a decoy of its cut word
            ('python3 (zz|"measure.py") x', d),
            # card 00c714ea r3 (Viktor 49709 L1): a blank, tab or newline in a group is a member char, not "zsh runs
            # nothing": zsh -f (and with extendedglob) ran measure.py for each (Dave zblank/drive.py, 11-21)
            ('python3 (measure.py|a b) x', d),
            ('python3 (measure.py|a\tb) x', d),
            ('python3 (measure.py|a\nb) x', d),
            ('python3 (zz|(measure.py|a b)) x', d),
            ('python3 (a b|measure.py) x', d),
            # ... a lean (KNOWN-KTP-OVER, r3): a whole-word group with no | and a substitution in it is a glob
            # qualifier for zsh, which stops ("unknown file attribute"): the gate reads the substitution as unread
            ('python3 (`echo zq`, zz) x', d),
            ('python3 (zz|(me|q)asure.py) x', d),
            ('echo "(zz)"; python3 (measure|zz).py x', d),
            # ... a quote the gate takes out, before the paren or inside the group
            ('python3 "m"(easure.py|x) stat.py', d),
            ('python3 ("measure.py"|zz) x', d),
            # ... a group nested past MAX_ZSH_GROUP_DEPTH (RecursionError before the cap: fail-closed by the catch, now
            # the prefix), and the call after 30 000 cut paren words that are no script (0.4 s / 0.8 s in the hook)
            ('python3 (a' + '|(a' * 30000 + ' x', d),
            ('python3 m(easure.py|x) stat.py; ' + 'echo (x; ' * 30000, d),
            # ... (mutation round, each measured with zsh -f and the fleet setopts, or plain `zsh -c` for (D)): a
            # qualifier that adds hidden names, a negated bracket, a brace and ** before the group, a substitution,
            # a value or an escape in a member
            ('python3 hid/*(D) x', d),
            ('python3 [^z](easure.py|x) stat.py', d),
            ('python3 m{e,e}(asure.py|x) stat.py', d),
            ('python3 **/m(easure.py|x) stat.py', d),
            ('python3 (zz|$(echo measure.py)) x', d),
            ('python3 (zz|`echo measure.py`) x', d),
            ('python3 (zz|$X) x', d),
            ('python3 (zz|"$X") x', d),
            ('python3 (zz|measure\\.py) x', d),
            # ... past MAX_ZSH_GROUP_GLOBS occurrences or forms: the prefix (`*` here), fail-closed
            ('python3 (zq|zz) x; ' + 'echo (zq; ' * 70, d),
            ('python3 (' + '|'.join('q%d' % k for k in range(70)) + ') x', d),
            ('python3 [m]easure.py stat.py', d),
            ("bash -c 'python3 [m]easure.py stat.py'", d),  # in a payload, read as its own text
            ('eval "python3 {measure.py,stat.py}"', d),
            ('DIRSTACK=stat.py; python3 $DIRSTACK ./measure.py', d),  # special-DIRSTACK
            ('X=stat.py\r; python3 $X ./measure.py', d),  # value-CR
            ('X=stat.py\x0b; python3 $X ./measure.py', d),  # value-VT
            ('X=stat.py\xa0; python3 $X ./measure.py', d),  # value-NBSP
            # the price of the positive shape (round 2): && between assignment and use, a chained value, and a
            # double-quoted bash -c payload fall back to the old walk; bash would run no keychain script here
            ('X=stat.py && python3 $X ./measure.py', d),
            ('X=stat.py; Y=$X; python3 $Y ./measure.py', d),
            ('X=stat.py; bash -c "python3 $X ./measure.py"', d),
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
            # card e3d2fd6e (main too): a backslash in the word or in its path start; bash and zsh took it off and ran
            # dump.sh (bin/shell-truth.py, 11-21); in a substitution, a backtick and a { } group too
            ('./dump\\.sh', d),
            ('./dump\\.sh x', d),
            ('\\./dump.sh', d),
            ('.\\/dump.sh', d),
            ('\\.\\/dump.sh', d),
            ('true; \\./dump.sh', d),
            ('echo $(./dump\\.sh)', d),
            ('echo "$(./dump\\.sh)"', d),
            ('echo `./dump\\.sh`', d),
            ('x=`./dump\\.sh`', d),
            ('{ ./dump\\.sh; }', d),
            ('\\' + os.path.join(d, 'dump.sh'), None),  # `\/abs/x.sh` and `sub\/y.sh` ran too (work/e3d2fd6e/truth2.py)
            ('sub\\/deep.py', d),
            ('echo $(sub\\/deep.py)', d),
            ('cd sub && \\../dump.sh', d),  # `\../` and `.\./` ran ../x.sh (truth2.py)
            ('cd sub && .\\./dump.sh', d),
            # card e3d2fd6e r3: the word in a shell's payload or in a heredoc a shell reads is code
            ("bash -c './dump\\.sh'", d),
            ("eval './dump\\.sh'", d),
            ('bash -c "echo $(./dump\\.sh)"', d),
            ("bash <<'EOF'\n./dump\\.sh\nEOF", d),
            ("bash <<'EOF'\nx=1; ./dump\\.sh\nEOF", d),
            ('bash <<EOF\n./dump\\.sh\nEOF', d),
            ('cat > /dev/null <<EOF\n$(./dump\\.sh)\nEOF', d),  # an unquoted body: the shell runs its $( )
            # r5 (Viktor 49996 R2): an unquoted-delimiter data body with a `$(` or a backtick anywhere keeps every
            # backslash word of it (fail-closed: the lexer does not tell the substitution's inside apart)
            ('cat > notes.md <<X\n./dump\\.sh\n$(date)\nX', d),
            ('cat > notes.md <<X\n`date`\n./dump\\.sh\nX', d),
            ('cat > notes.md <<X\n$(./dump\\.sh)\nX', d),
            # r6 (rebased onto 0196e1ee): a heredoc 0196e1ee's _shell_reads_heredoc gives to a shell keeps the word
            # (source and . /dev/stdin, a pipeline left open after the body; main does not read the word at all)
            ('source /dev/stdin <<X\n./dump\\.sh\nX', d),
            (". /dev/stdin <<'X'\n./dump\\.sh\nX", d),
            ("cat <<'X' |\n./dump\\.sh\nX\nbash", d),
            # a text the lexer does not fully read (a heredoc in a substitution) keeps the word (fail-closed)
            ("echo $(cat <<'E'\nx\nE\n); ./dump\\.sh", d),
            ("echo `cat <<'E'\nx\nE\n`; ./dump\\.sh", d),
            # a quote right after the word makes it one DIRECT_WORD_RX took before e3d2fd6e: read as on main
            ("git commit --dry-run -m 'x; ./dump\\.sh'", d),
            # past _ESC_MAX_COPIES copies the command is not searched: the word is kept (fail-closed)
            ("python3 -c 'print(1)'" + " 'a ))\\/(( )) b'" * 65, d),
            # a copy of the word at a code position of the command keeps it, the second copy too
            ("python3 -c 'print(1)' 'x; ./dump\\.sh ))\\/(( ))'; ./dump\\.sh", d),
            ("python3 -c 'print(1)' 'a ))\\/(( )) b'\n./dump\\.sh", d),
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
            # card deede5e4 (Viktor LOW L1): a directory change cd_bases does not follow, then a relative script
            # (main read no file and allowed); a loop variable in the cd target or the script path; pushd / env -C
            # into sub2, where twin.py is the keychain one (d's twin.py prints 1: main judged that one)
            ('for x in sub2; do cd $x && python3 only.py; done', d),
            ('for x in sub2; do (cd $x && python3 only.py); done', d),
            ('cd "$(echo sub2)" && python3 only.py', d),
            ('pushd sub2 && python3 only.py', d),
            ('pushd sub2 >/dev/null; python3 twin.py', d),
            ('env -C sub2 python3 twin.py', d),
            ('cd ' + d + '/$X && python3 twin.py', None),
            ('for f in sub2/only.py; do python3 $f; done', d),
            ('for f in twin.py sub2/only.py; do python3 "$f"; done', d),
            ('for f in twin.py; do :; done; for f in sub2/only.py; do python3 ${f}; done', d),
            ('for f in sub2/*.py; do python3 $f; done', d),  # a glob list: expanded in each base
            ('for f in $(ls sub2); do python3 sub2/$f; done', d),  # a substituted list: unread
            # card deede5e4, mutation round 1: a row for each survivor. Past MAX_LOOP_PATHS values; the values of
            # every list of a name, not only the last; a name once unknown stays unknown; no list (`for f; do`: "$@")
            ('for f in ' + ' '.join(f'n{i}.py' for i in range(64)) + ' sub2/only.py; do python3 $f; done', d),
            ('for f in sub2/only.py; do python3 $f; done; for f in twin.py; do :; done', d),
            ('for f in $(ls sub2); do python3 sub2/$f; done; for f in nothing; do :; done', d),
            ('for f; do python3 $f; done', d),
            # an empty cd word (bash 3.2, bash 5 and zsh stay, measured; not followed, fail-closed), a cd word a
            # substitution continues, a cd to a loop variable over a substitution, a glob cd, a relative cd from
            # every value of a loop cd, a cd in a heredoc a shell reads, a loop glob after pushd
            ('cd "" && python3 twin.py', d),
            ('cd sub$(echo 2) && python3 only.py', d),
            ('cd s"$(echo ub2)" && python3 only.py', d),
            ('for x in $(echo sub2); do cd $x && python3 only.py; done', d),
            ('cd sub? && python3 only.py', d),
            ('for x in sub*; do (cd $x && python3 only.py); done', d),
            ('for x in sub .; do (cd $x && cd sub2 && python3 only.py); done', d),
            ("bash <<'E'\ncd sub2\npython3 only.py\nE", d),
            ("bash -s <<'E'\ncd sub2 && python3 twin.py\nE", d),
            ('pushd sub2; for f in t*.py; do python3 $f; done', d),
            ('pushd sub2; for f in on*; do python3 $f; done', d),  # the cwd's onlypkg/__main__.py is clean: unread
            # a loop value naming a directory runs its __main__.py (found while killing the survivors: allowed before)
            ('for f in mainpkg; do python3 $f; done', d),
            ('for f in mainp*; do python3 "$f"; done', d),
            # card deede5e4: a chained value (`B=$A/..`), a quoted loop target, a plain loop value in an argument
            # after an innocent first file (Viktor 41756 LOW 2 still holds), env's own -C after its options
            ('A=sub2; B=$A; cd $B && python3 only.py', d),
            ('A=sub2; B=$A/only.py; python3 $B', d),
            ('for x in sub2; do cd "$x" && python3 only.py; done', d),
            ('for f in read.mjs; do node -r ./ok.js $f; done', d),
            ('env -i -u X -C sub2 python3 twin.py', d),
            ('cd "$T" && python3 twin.py', d),  # a variable set outside the command: unread
            # card deede5e4 r2 (Viktor 49087, his prop d20acc50). R1 (a regression of r1: main blocked it): a physical
            # directory change, bash steps above the link's target
            ('set -P; cd lnk/.. && python3 twin.py', d), ('cd -P lnk/.. && python3 twin.py', d),
            # P2: a plain assignment of the loop variable's name hid the loop values (main too)
            ('F=twin.py; for F in sub2/only.py; do python3 $F; done', d),
            ('F=twin.py; for F in sub2/only.py; do python3 ${F}; done', d),
            ('D=fdname; for D in sub2; do cd $D; python3 only.py; cd ..; done', d),
            ('F=twin.py; for F in sub2/only.py; do :; done; python3 $F', d),
            ('for F in sub2/only.py; do python3 $F; done; F=twin.py', d),
            ('F="twin.py"; for F in sub2/only.py; do python3 "$F"; done', d),
            # P3: a cd the gate took for followed but read wrong (main too): an option word, `--`, a redirection
            # before the target, a quoted cd / pushd name, a brace target, a ~+ target; $PWD / ~+ in the script path
            ('cd -P sub2 && python3 twin.py', d), ('cd -L sub2 && python3 twin.py', d),
            ('cd -- sub2 && python3 twin.py', d), ('builtin cd -P sub2 && python3 twin.py', d),
            ('cd 2>/dev/null sub2 && python3 twin.py', d), ("'c'd sub2 && python3 twin.py", d),
            ('c"d" sub2 && python3 twin.py', d), ("'push'd sub2 && python3 twin.py", d),
            ('cd {sub2,} ; python3 twin.py', d), ('cd ~+/sub2 && python3 twin.py', d),
            ('cd sub2 && python3 $PWD/twin.py', d), ('cd sub2 && python3 ${PWD}/twin.py', d),
            ('cd sub2 && python3 ~+/twin.py', d),
            # (mutation round 3, in process, work/deede5e4/m3.py) a plain value assigned after the loop is read too,
            # a made one blocks; a cd of option words only (bash: to HOME) is not followed; $PWD after an unknown cd
            ('for F in twin.py; do :; done; F=sub2/only.py; python3 $F', d),
            ('for F in twin.py; do :; done; F=$X; python3 $F', d),
            ('cd -P && python3 twin.py', d), ('cd $T && python3 $PWD/twin.py', d),
            # every word of a node call, not only those before the first file (Viktor 41756 LOW 2 under pushd)
            ('pushd sub2 && node -r ' + d + '/ok.js read.mjs', d),
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
            # card c6c67dde: a cd to this repo's root is followed, but a cd that may fail leaves the shell where it
            # was (d: a look-alike scripts/agent-msg.sh), after any join but &&; a relative target or `cd -` is not
            ("cd " + AM_ROOT + "; bash scripts/agent-msg.sh dave v - <<'M'\n" + d + "/measure.py\nM", d),
            ("cd " + AM_ROOT + " && true; bash scripts/agent-msg.sh dave v - <<'M'\n" + d + "/measure.py\nM", d),
            ("cd " + AM_ROOT + " || bash scripts/agent-msg.sh dave v - <<'M'\n" + d + "/measure.py\nM", d),
            ("cd " + AM_ROOT + " && cd /tmp && bash scripts/agent-msg.sh dave v - <<'M'\n" + d + "/measure.py\nM",
             AM_ROOT),
            ("cd - && bash scripts/agent-msg.sh dave v - <<'M'\n" + d + "/measure.py\nM", AM_ROOT),
            ("cd scripts/.. && bash scripts/agent-msg.sh dave v - <<'M'\n" + d + "/measure.py\nM", AM_ROOT),
            # card c6c67dde r2 (Viktor 50201 R1, bash and zsh ran d's agent-msg.sh): cd is logical, a .. past a symlink
            # steps back to where the link stands, not to its target's parent
            ("cd " + d + "/amlnk/.. && bash scripts/agent-msg.sh dave v - <<'M'\n" + d + "/measure.py\nM", AM_ROOT),
            ("cd " + d + "/amlnk/..; bash scripts/agent-msg.sh dave v - <<'M'\n" + d + "/measure.py\nM", AM_ROOT),
            ("cd " + d + "/amlnk/..\nbash scripts/agent-msg.sh dave v - <<'M'\n" + d + "/measure.py\nM", AM_ROOT),
            # card c6c67dde r3 (Viktor 50321 R2, fail-open since r1): after || the cd may not run, after | it runs in
            # a subshell (bash): bash ran d's look-alike in each but the && one (zsh: the || ones;
            # work/c6c67dde-r3/truth), the shell may be where it was
            ("true || cd " + AM_ROOT + " && bash scripts/agent-msg.sh dave v - <<'M'\n" + d + "/measure.py\nM", d),
            ("echo x || cd " + AM_ROOT + " && bash scripts/agent-msg.sh dave v - <<'M'\n" + d + "/measure.py\nM", d),
            ("true || cd " + AM_ROOT + "\nbash scripts/agent-msg.sh dave v - <<'M'\n" + d + "/measure.py\nM", d),
            ("true || cd " + AM_ROOT + "; bash scripts/agent-msg.sh dave v - <<'M'\n" + d + "/measure.py\nM", d),
            ("true | cd " + AM_ROOT + " && bash scripts/agent-msg.sh dave v - <<'M'\n" + d + "/measure.py\nM", d),
            ("echo x | cd " + AM_ROOT + " && bash scripts/agent-msg.sh dave v - <<'M'\n" + d + "/measure.py\nM", d),
            # where the shell was is not known (a relative cd), so neither is it after `|| cd <abs>`
            ("cd . || cd " + AM_ROOT + " && bash scripts/agent-msg.sh dave v - <<'M'\n" + d + "/measure.py\nM", d),
            # a lean (main too): the cd runs here (false && true fails), the gate does not weigh the conditions
            ("false && true || cd " + AM_ROOT + " && bash scripts/agent-msg.sh dave v - <<'M'\n" + d + "/measure.py\nM",
             d),
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
            # card 70a5fb2a (Viktor 43324 LELET 3): the terminator line of a quoted delimiter ending in a backslash
            # (`<<'J\'`, line `J\`) is no line continuation: bash ends the body there and runs the next line (the
            # lexer's bodyEnd was right, lexer_normalise joined the terminator's backslash-newline)
            ("curl -d @- <<'J\\'\nhello\nJ\\\n./measure.py", d),
            ("curl -s -X POST http://localhost:1/x --data-binary @- <<'J\\'\nhi\nJ\\\nbash measure.py", d),
            ("git commit -F - <<'J\\'\nmsg\nJ\\\npython3 measure.py", d),
            ("curl -d @- <<-'J\\'\n\thello\n\tJ\\\n./measure.py", d),
            ("cat <<'J\\' > /dev/null\nhello\nJ\\\n./measure.py", d),
            # card 70a5fb2a round 2 (Viktor 49212; bash 3.2 ran every row; c2da88a9's gate allowed each, measured,
            # except the $'J\x41' row, which it already blocked: its body never ended there):
            # O1: the old (lexer-free) path, sent there by an unterminated heredoc or quote later in the text, joined
            # every backslash-newline; the text with none joined is read too
            ("curl -d @- <<'J\\'\nhello\nJ\\\n./measure.py\ncat <<Z", d),
            ("cat <<'J\\' >/dev/null\nhello\nJ\\\n./measure.py\necho \"unterminated", d),
            (': x \\\\\n./measure.py\ncat <<Z', d),
            (': # note \\\n./measure.py\ncat <<Z', d),
            # O2: a $'..' / $".." delimiter: bash 3.2 ends the body at its value (J; $'J\x41' at JA, ANSI-C), not at $J
            ("git commit -F - <<$'J'\nhello\nJ\n./measure.py\n$J", d),
            ("git commit -F - <<$'J'\nhello\nJ\npython3 measure.py\n$J", d),
            ('git commit -F - <<$"J"\nhello\nJ\n./measure.py\n$J', d),
            ("curl -d @- http://127.0.0.1:9 <<$'J'\nhello\nJ\n./measure.py\n$J", d),
            ("git commit -F - <<$'J\\x41'\nhello\nJA\n./measure.py", d),
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
            # Viktor 49925 L1: the same fed glob in a heredoc a shell reads, or piped to one, is live
            ("bash <<'X'\necho ./meas*.py | bash\nX", d),
            ("cat <<'X' | bash\necho ./meas*.py | bash\nX", d),
            # ... and an interpreter's glob word on such a data line is read as on main (main blocks it: the 00c714ea
            # glob reading of a script word; only the command position is quoted, a lean kept, not added)
            ("cat > notes.md <<'X'\necho python3 ./meas*.py | bash\nX", d),
            # Viktor 49984 (card 0196e1ee): a heredoc `source` / `.` reads from /dev/stdin, a pipeline the heredoc's line
            # leaves open after a | (bash on a later line, or after a backslash-newline), an unquoted delimiter's body
            # $( ) or backtick (the shell runs it when it expands the body), a data command piped to a shell, and a
            # runner before the shell (bash ran each fed glob, work/0196e1ee-r8)
            ("source /dev/stdin <<X\necho ./meas*.py | bash\nX", d),
            (". /dev/stdin <<X\ncat ./meas?re.py | bash\nX", d),
            ("cat <<'X' |\necho ./meas*.py | bash\nX\nbash", d),
            ("cat <<'X' |\n./meas*.py\nX\nbash", d),
            ("cat <<'X' |\necho ./meas*.py | bash\nX\ntee /dev/null |\nbash", d),
            ("cat <<'X' \\\n| bash\necho ./meas*.py | bash\nX", d),
            ('cat > notes.md <<X\n$(echo ./meas*.py | bash)\nX', d),
            ('cat >> notes.md <<X\n`echo ./meas*.py | bash`\nX', d),
            ("grep -c sh <<'X' | bash\necho ./meas*.py | bash\nX", d),
            ("env bash <<'X'\necho ./meas*.py | bash\nX", d),
            ("sudo -u a sh <<'X'\necho ./meas*.py | bash\nX", d),
            ("{ bash; } <<'X'\necho ./meas*.py | bash\nX", d),  # a group on the line: the whole line is read
            # past _HD_MAX_NEXT open lines the body is read as a shell's (fail-closed, a lean)
            ("cat <<'X' |\necho ./meas*.py | bash\nX\n" + 'cat |\n' * 9 + 'grep x', d),
            # card 0196e1ee (Viktor 43793 LOW/INFO 2, each passed main 749bffd9 and bash ran the fed script,
            # work/0196e1ee): a glob or a brace in the fed text, a path run directly, a reader PIPE_SHELL_RX did not see,
            # a fed text that makes its words itself, and a loop / if / case / function feeding the pipe
            ('echo ./measur?.py | bash', d),
            ("echo './meas*.py' | bash", d),
            ('echo ./{measure,zz}.py | bash', d),
            ('echo ./m[e]asure.py | bash', d),
            ('./measur?.py', d),
            ('./meas*.py x', d),
            ('./{measure,zz}.py', d),
            ('echo ./measure.py | /usr/bin/env bash', d),
            ('echo ./measure.py | env -i FOO=1 bash', d),
            ('echo ./measure.py | b"as"h', d),
            ("echo ./measure.py | 'ba'sh", d),
            ('echo ./measure.py | { bash; }', d),
            ('echo ./measure.py | ( bash )', d),
            ('echo ./measure.py | (bash)', d),
            ('echo ./measure.py | if true; then bash; fi', d),
            ('echo ./measure.py | while read l; do bash $l; done', d),
            ('echo ./measure.py | while read l; do $l; done', d),
            ('echo ./measure.py | eval "$(cat)"', d),
            ('echo ./measure.py | { read c; $c; }', d),
            ('echo ./measure.py | { read c; eval $c; }', d),
            ('echo python3 $(echo measure.py) | bash', d),
            ('echo python3 ${F:-measure.py} | bash', d),
            # card 0196e1ee m6 (unread-param-off, -weak): a ${..} with an operator in the fed text is expanded by the
            # shell that reads it, from its exported environment (main ran these: no literal names the script)
            ("export F=measure.py; echo 'python3 ${F%x}' | bash", d),
            ("export F=measure.py; echo 'python3 ${F/zz/q}' | bash", d),
            ('export F=measure.py; echo python3 \\${F[0]%x} | bash', d),
            ("export G=F F=measure.py; echo 'python3 ${!G}' | bash", d),
            # m6 (unread-hits-off, echo-put-off, live-shell-body-off): the fed text inside eval and a shell's heredoc
            # body; main ran these (Dave survivor-cand on the test's own feed rows in 13 contexts, 11-21)
            ("eval 'echo python3 `echo measure.py` | bash'", d),
            ("eval 'echo python3 $(echo measure.py) | bash'", d),
            ("bash <<'EOF'\necho python3 `echo measure.py` | bash\nEOF", d),
            ('echo python3 `echo measure.py` | bash', d),
            ("echo '`./measure.py`' | bash", d),
            ('f() { echo ./measure.py; }; f | bash', d),
            ('function f { echo ./measure.py; }; f | bash', d),
            ('for f in ./measure.py; do echo $f; done | bash', d),
            ('while true; do echo ./measure.py; break; done | bash', d),
            ('if true; then echo ./measure.py; fi | bash', d),
            # m6 word-cut-off survived: the feeder's first word ends at the | too (no blank before it)
            ('f() { echo ./measure.py; }; f|bash', d),
            ('for x in ./measure.py; do echo $x; done|bash', d),
            ('case 1 in 1) echo ./measure.py;; esac | bash', d),
            # a heredoc body a shell reads is the shell's own code: its pipes, readers and direct words are live
            ("bash <<'EOF'\necho ./meas*.py | bash\nEOF", d),
            ("bash <<'EOF'\necho python3 ${F:-measure.py} | bash\nEOF", d),
            ("bash <<'EOF'\n./meas*.py\nEOF", d),
            ("bash <<'EOF'\necho ./measure.py | { bash; }\nEOF", d),
            # the live mark is per pipe: a quoted | from the same start must not hide the live one
            ("echo python3 ${F:-measure.py} | bash -c 'a | bash'", d),
            # fleet replay 2: a function call right after a heredoc's terminator line (bash ran the fed script), and
            # what the replay-2 fix must not take: a pattern at a code position next to a data body / a process
            # substitution, a pattern a $NAME makes that a data body also has
            ("f() { echo ./measure.py; }; cat <<'E'\nhi\nE\nf | bash", d),
            ("python3 - <<'PY'\n/**\nPY\npython3 -c ''; ./meas*.py", d),
            ("python3 - <<'PY'\n./meas*.py\nPY\npython3 -c ''; X=./meas; ${X}*.py", d),
            ("X=./meas; python3 - <<'PY'\n./meas*.py\nPY\npython3 -c ''; $X*.py", d),
            ('diff <(cat stat.py) x; ./meas*.py', d),
            ('case a in a) ./meas*.py;; esac', d),
            ('$(true) ./meas*.py', d),  # a $( ) closer is no <( ): the empty word leaves the pattern the command
            ("python3 - <<'PY'\n./meas*.py\nPY\npython3 -c ''; ./meas*.py", d),
            ("bash <<'EOF'\n./meas*.py\nEOF\npython3 -c ''", d),
            ("f() { echo ./measure.py; }; export -f f; bash <<'EOF'\nf | bash\nEOF", d),  # a shell body: no clamp
            # card 3bf9a741 (all passed main 915e2f70, bash ran each; work/3bf9a741/probe2.py): xargs puts the words it
            # reads on stdin into the argv of the interpreter it runs
            ('echo measure.py | xargs python3', d),
            ('echo ./measure.py | xargs -n1 python3', d),
            ('echo measure.py | xargs -n 1 -P2 -t python3', d),
            ('echo measure.py | xargs -L 1 -- python3 -u', d),
            ('echo measure.py | xargs -I{} python3 {}', d),
            ('echo measure.py | xargs -I % python3 -u %', d),
            ('echo measure.py | xargs -J% python3 %', d),
            ('echo read.mjs | xargs -I{} node {}', d),
            ('echo read.mjs | xargs node', d),
            ('echo dump.sh | xargs -n1 sh', d),
            ('echo measure.py | xargs env python3', d),
            ('echo measure.py | xargs nice python3', d),
            ('echo measure.py | /usr/bin/xargs python3', d),
            ('echo measure.py | command xargs python3', d),
            ('echo measure.py | \\xargs python3', d),
            ('echo measure.py | xargs "python3"', d),
            ("printf '%s\\n' measure.py | xargs python3", d),
            ('printf measure.py | xargs -0 python3', d),
            ("printf 'measure\\x2epy' | xargs python3", d),
            ('echo -n measure.py | xargs python3', d),
            ('echo -m measure | xargs python3', d),
            ('echo measure | xargs python3 -m', d),
            ('(echo measure.py) | xargs python3', d),
            ('{ echo measure.py; } | xargs python3', d),
            ('echo measure.py | tee /dev/null | xargs python3', d),
            ('echo x measure.py | xargs -n1 python3', d),
            ("echo 'a; b' measure.py | xargs -n1 python3", d),
            ('xargs python3 <<< measure.py', d),
            ("xargs python3 <<'E'\nmeasure.py\nE", d),
            ('xargs python3 <<-E\n\tmeasure.py\n\tE', d),
            ("cat <<'E' | xargs python3\nmeasure.py\nE", d),
            ('cat <<< measure.py | xargs python3', d),
            ('xargs python3 < <(echo measure.py)', d),
            ('xargs -a <(echo measure.py) python3', d),  # GNU -a reads the file (BSD has no -a)
            ('cd sub && echo ../measure.py | xargs python3', d),
            ('echo x; echo measure.py | xargs python3', d),
            ("echo measure.py | xargs -I{} sh -c 'python3 {}'", d),
            # round 2 (Viktor 49280; d74afad6 allowed each): the whole input line in place of -I's string (MEDIUM 1),
            # and a plain word after a shell's -c is the shell's code, read as such (LOW 2b, script-shc-I)
            ("echo python3 measure.py | xargs -I{} sh -c '{}'", d),
            ("echo ./measure.py | xargs -I{} sh -c '{}'", d),
            ('echo ./measure.py | xargs -I{} bash -ec {}', d),
            # round 3 (Viktor, r2 own probe; main and 59057d2c allowed each): a wrapper before the shell keeps it the
            # shell (env, nice -n, command, nohup, timeout, sudo -u, VAR=value), so its -c word is the shell's code
            ("echo ./measure.py | xargs -I{} env sh -c '{}'", d),
            ("echo ./measure.py | xargs -I{} nice -n 5 bash -c '{}'", d),
            ("echo ./measure.py | xargs -I{} command sh -c '{}'", d),
            ("echo ./measure.py | xargs -I{} nohup sh -c '{}'", d),
            ("echo ./measure.py | xargs -I{} timeout 5 sh -c '{}'", d),
            ("echo ./measure.py | xargs -I{} /usr/bin/env -i A=1 bash -c '{}'", d),
            ("echo ./measure.py | xargs -I{} sudo -u root sh -c '{}'", d),
            # an xargs no | stands right before still reads the pipe: a group, a loop, an if, a $( ), a >( )
            ('echo measure.py | (xargs python3)', d),
            ('echo measure.py | { xargs python3; }', d),
            ('echo measure.py | (cd . && xargs python3)', d),
            ('echo measure.py | while true; do xargs python3; break; done', d),
            ('echo measure.py | if true; then xargs python3; fi', d),
            ('echo measure.py | echo $(xargs python3)', d),
            ('echo measure.py | tee >(xargs python3) >/dev/null', d),
            # an unbalanced quote in a fed word is a char of the argument: it does not hide the next xargs's line
            ('echo "x\'" | xargs grep a; echo measure.py | xargs python3', d),
            # the xargs of plain data commands are not counted, and the one after them is still read
            ('echo a | xargs grep x; ' * 100 + 'echo measure.py | xargs python3', d),
            ('echo a | xargs wc -l; ' * 70 + 'echo measure.py | xargs -I{} python3 {}', d),
            # a script file read line by line: a real `| xargs <binary>` line, alone and below 100 counted xargs
            ('bash xrun.sh', d), ('sh ./xrun2.sh', d), ('bash xrun3.sh', d),
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
            # card b138f11b (measured 2026-11-16 on 3545748a: allow, the call ended at the quoted ")"; blocked since
            # 946937b7, unpinned until now): a quoted "$(" or paren is part of the script's name, not a substitution
            # or a call end (bash and zsh -f ran the named file, or runner.sh's measure.py, in each)
            ("python3 '$(true)'m.py", d),
            ("python3 '$(true)m.py'", d),
            ("source '$(true)'runner.sh measure.py", d),
            ("bash '$(true)'runner.sh measure.py", d),
            ("python3 ')'m.py", d),
            ('python3 ")"m.py', d),
            ('python3 \\)m.py', d),
            ("python3 '('m.py", d),
            ("(python3 ')'m.py)", d),
            ('python3 $(true \\()measure.py', d),
            ("python3 -W ')' measure.py", d),  # a quoted paren as an option's argument
            ("python3 -X ')' measure.py", d),
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
            # card af12091a (Viktor 45748 K1; bash ran the script in every row of his probe): a quoted operator in a
            # call the lexer reads as quoted text (a payload, a heredoc body) cut its words short of the script. The
            # call's own command ends at the first operator up to which its text lexes cleanly
            ("bash -c \"python3 -W 'a;b' measure.py\"", d),
            ('bash -c "python3 -W \\"a;b\\" measure.py"', d),
            ("eval 'python3 -W \"a;b\" measure.py'", d),
            ("eval 'python3 >\"x;y\" measure.py'", d),
            ("eval 'python3 -W \"a|b\" measure.py'", d),
            ("eval 'python3 -W \"a&b\" measure.py'", d),
            ("eval 'python3 -W \"a)b\" measure.py'", d),
            ("eval 'python3 2>x\\& measure.py'", d),
            ("eval 'python3 -W a\\;b measure.py'", d),
            ("sh -c 'eval \"$0\"' 'python3 -W \"a;b\" measure.py'", d),
            ('bash <<EOF\npython3 -W "a;b" measure.py\nEOF', d),
            ("eval 'source >\"a;b\" dump.sh'", d),
            ("eval 'bash >\"x;y\" dump.sh'", d),
            ("eval 'python3 -W \"a;b\" notes.py; python3 -W \"a;b\" measure.py'", d),
            # an escaped operator is no end (-W takes "x;"), a payload closed by a double quote, an opening backtick in
            # the words, an expanded text ($X is empty in bash: echo's X= is no assignment); bash ran measure.py in each
            ("eval 'python3 -W \"a;b\" -W x\\; measure.py'", d),
            ("eval \"python3 -W 'a;b' measure.py\"", d),
            ("x=$(eval \"python3 -W 'a;b' measure.py\")", d),
            ("eval 'python3 -W \"a;b\" `true` measure.py'", d),
            ("echo X=notes.py; eval 'python3 -W \"a;b\" $X measure.py'", d),
            # the same two in a heredoc body into a shell: no payload quote, only the own-command search reads them
            # (mutation round 2: with the decoded payloads the eval rows above no longer told these apart)
            ("bash <<'EOF'\npython3 -W \"a;b\" -W x\\; measure.py\nEOF", d),
            ("echo X=notes.py; bash <<'EOF'\npython3 -W \"a;b\" $X measure.py\nEOF", d),
            # a backtick in a heredoc body: one that opens a substitution in the words, one that closes the call's
            ("bash <<'EOF'\npython3 -W \"a;b\" `true` measure.py\nEOF", d),
            ("bash <<'EOF'\nx=`python3 -W \"a;b\" measure.py`\nEOF", d),
            # Viktor 47244 (1): the payload's outer quoting hid the operator; read as the shell reads it (bash ran it)
            ("eval 'python3 -W '\\''c;d'\\'' measure.py'", d),
            ("eval 'eval \"python3 -W \\\"c;d\\\" measure.py\"'", d),
            ("eval 'eval \"python3 -W '\\''c;d'\\'' measure.py\"'", d),
            ("eval 'python3 -W \"a;b\" $(eval \"python3 -W '\\''c;d'\\'' measure.py\")'", d),
            ("eval 'python3 notes.py; eval \"python3 -W '\\''c;d'\\'' measure.py\"'", d),
            # a payload past PAYLOAD_DEPTH levels is not read: blocks, whatever it runs
            (_eval_nest("python3 -W 'a' notes.py", 4), d),
            # no limit per call: 40 quoted operators before the script (a limit would leave the old reading)
            ("eval 'python3 -W \"a" + ';b' * 40 + "\" measure.py'", d),
            # card 2917e6b6 (2026-11-18, bash and zsh ran measure.py in each; main allowed every eval row): a
            # substitution in the payload's words, no quote before it, cut the call at its ")" or opening backtick
            ("eval 'python3 $(:) measure.py'", d),
            ("eval 'python3 $(echo) measure.py'", d),
            ("eval 'python3" + ' $(:)' * 70 + " measure.py'", d),
            ("eval 'python3 `:` measure.py'", d),
            ("eval 'python3 `:``:` measure.py'", d),
            ("eval 'python3" + ' `:`' * 70 + " measure.py'", d),
            ("eval 'python3 `:`$(:) measure.py'", d),
            ("sh -c 'eval \"$0\"' 'python3 `:` measure.py'", d),
            # the body of a heredoc into a shell (main allowed each; bash and zsh ran measure.py)
            ("bash <<'EOF'\npython3 `:` measure.py\nEOF", d),
            ("bash <<EOF\npython3 `:` measure.py\nEOF", d),
            ("sh <<'X'\necho hi\npython3 `:``:` measure.py\nX", d),
            ("bash <<'EOF'\npython3 $(:) measure.py\nEOF", d),
            # Viktor 2917e6b6 (11-18 18:55) asked negative rows (11-19, gate-bash-truth: bash ran measure.py in each;
            # main allowed 10 of them): eval in double quotes, builtin/command eval, nested eval, backtick and $( )
            # together. (source/. of a process substitution: open on main and here, another class, card c7234bed)
            ('eval "python3 $(:) measure.py"', d),
            ('eval "python3 \\$(:) measure.py"', d),
            ('eval "python3 \\`:\\` measure.py"', d),
            ('eval "python3 `:` measure.py"', d),
            ("builtin eval 'python3 $(:) measure.py'", d),
            ("command eval 'python3 $(:) measure.py'", d),
            ("builtin eval 'python3 `:` measure.py'", d),
            ("command eval 'python3 `:` measure.py'", d),
            ('eval \'eval \'"\'"\'python3 $(:) measure.py\'"\'"\'\'', d),
            ('eval "eval \'python3 \\$(:) measure.py\'"', d),
            ('eval \'eval "python3 \\`:\\` measure.py"\'', d),
            ("eval 'python3 `:`$(:)`:` measure.py'", d),
            ("eval 'python3 $(`:`) measure.py'", d),
            ("eval 'python3 `echo $(:)` measure.py'", d),
            # ... and the fail-closed side (measured): a harmless call with 70 of them past the lexer's bounds
            ("eval 'python3 notes.py" + ' $(:)' * 70 + "'", d),
            # mutation round m5 (bin/mut-diff.py, generated candidates; bash and zsh ran measure.py in each): an
            # operator after the payload's closing quote (the strip end's quote index), and a heredoc in the call's
            # text whose cut line is not its delimiter (unterminated: bash warns and runs the call), with <<- tabs
            ("eval 'python3 $(:) measure.py' && true", d),
            ("eval 'python3 -W \"a;b\" measure.py <<-X\n\tfoo;bar\n\tX; echo done'", d),
            ("eval 'python3 -W \"a;b\" measure.py <<X\nfoo;bar\nX\"'`:`", d),
            # ... an end more than four times past the filter's text (the filter is asked only within it), the whole
            # text unterminated (a heredoc with no body: bash warns and runs the call), so no later end reads
            ("eval 'python3 -W \"a;b;c\" -W " + 'x' * 200 + " measure.py; cat <<E'", d),
            # ... a backtick in a '"' glued to the script word, at the call text's own quote (the strip end wants the
            # 'c' class there, and a substitution's start is not inside it), and a substitution's end right at an end
            ("eval 'python3 -W \"a;b\" measure.py\"`:`\" <<E'", d),
            ("eval 'python3 -W \"a;b\" measure.py$(:); cat <<E'", d),
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
            # card 39d885ef (Viktor 43793 MEDIUM 1): printf and echo -e print a newline for \n (a command position);
            # normalise() made it a plain n, so the command ended glued to the last word and passed (main a8b4a4bf)
            ("printf './measure.py\\n' | bash", d),
            ("printf 'python3 measure.py\\n' | bash", d),
            ("printf 'true\\n./measure.py\\n' | bash", d),
            ("echo -e './measure.py\\n' | bash", d),
            ('echo -e "./measure.py\\n" | bash', d),
            ("printf './measure.py\\012' | bash", d),
            ("printf './measure.py\\x0a' | bash", d),
            # (Viktor 43793 LOW 1): a ; & ( { in a quote is printed text, and the & of a redirection ends no pipeline:
            # the start of the pipeline was read after it, and the words before it were never read
            ("echo './measure.py;' | bash", d),
            ('echo "./measure.py;" | bash', d),
            ("echo './measure.py;echo hi' | bash", d),
            ("echo './measure.py &' | bash", d),
            ('echo ./measure.py 2>&1 | bash', d),
            # the same in a heredoc body fed to a shell: the body's stops are its own lexing's (the fleet replay)
            ("bash <<'EOF'\necho './measure.py;' | bash\nEOF", d),
            ('(echo ./measure.py) 2>&1 | bash', d),
            ('{ echo ./measure.py; } 2>&1 | bash', d),
            ('(echo ./measure.py; echo "(") | bash', d),
            ("(echo ./measure.py; echo '(') | bash", d),
            ('{ echo ./measure.py; echo "{"; } | bash', d),
            ("{ echo ./measure.py; echo '{'; } | bash", d),
            # mutation m39 (survivors, by the differential, 11-19): the escape-kept reading alone does not see an escaped
            # shell name (union-second-only); a here-string's escapes kept too (herestring-first-only: bash and zsh run
            # $'..\n..' as two lines); a text the lexer does not read (a heredoc in a backtick) takes the old path with
            # the escapes kept (pipesrc-keep-old-off); %.1s converts (printf-s-only)
            ('echo ./measure.py | ba\\sh', d),
            ('echo ./measure.py | \\bash', d),
            ("bash <<<$'true\\n./measure.py'", d),
            ("echo x | true; bash <<<$'true\\n./measure.py'", d),
            ("x=`cat <<'E'\nE\n`\nprintf 'true\\n./measure.py' | bash", d),
            ("printf './meas%.1sre.py\\n' u | bash", d),
            ("printf '%s' ./meas ure.py | bash", d),
            ("printf -- './meas%s.py\\n' ure | bash", d),
            # card c7234bed (Viktor 47570): the stub ran in bash and zsh (zsh only: the `. <(..)` forms), the gate
            # allowed each on main 171f2e6a and on 39d885ef (work/c7234bed/truth1)
            (". <(printf '%s\\n' 'python3 measure.py')", d),
            ("source <(echo 'python3 measure.py')", d),
            ("bash <(printf '%s\\n' 'python3 measure.py')", d),
            ("sh <(echo 'python3 measure.py')", d),
            ('eval "$(printf \'%s\\n\' \'python3 measure.py\')"', d),
            ('eval $(echo python3 measure.py)', d),
            ('eval "`echo python3 measure.py`"', d),
            ('builtin eval "$(echo python3 measure.py)"', d),
            ('bash -c "`echo python3 measure.py`"', d),
            ('bash <<< $(echo python3 measure.py)', d),
            (". /dev/stdin <<<'python3 measure.py'", d),
            ('source /dev/stdin <<<"$(echo python3 measure.py)"', d),
            ('x=$(echo python3 measure.py); eval "$x"', d),
            ("eval \"$(printf 'true\\npython3 meas%s.py\\n' ure)\"", d),
            ("eval \"$(echo -e 'true\\npython3 measure.py')\"", d),
            # mutation round c7234bed (feeder-no-path): echo by its path; bash and zsh ran the stub, 39d885ef allowed
            # both (work/c7234bed/truth8; the `. <(..)` form in zsh only)
            ('eval "$(/bin/echo python3 measure.py)"', d),
            ('. <(/bin/echo python3 measure.py)', d),
            # mutation round c7234bed (var-no-brace, source-here-nosplit; work/c7234bed/truth9): 39d885ef allowed both
            ('x=$(echo python3 measure.py); eval "${x}"', d),
            ('source /dev/stdin <<<"$(printf \'true\\npython3 measure.py\\n\')"', d),
            # mutation round 2 c7234bed (bt-noesc, sq-off, dq-off): bash and zsh ran the stub, 9ddb6a43 allowed each
            # (work/c7234bed/truth10, truth11; the `. <(..)` form in zsh only)
            ('eval "`echo \\`true\\`; echo python3 measure.py`"', d),
            ('bash -c "`echo \\`echo hi\\`; echo python3 measure.py`"', d),
            ('eval "$(echo \'#)\'; echo python3 measure.py)"', d),
            ('eval "$(echo "#)"; echo python3 measure.py)"', d),
            (". <(echo '#)'; echo python3 measure.py)", d),
            # card c7234bed (Viktor 48033 M1): bash and zsh ran the stub, main f48a5d0f and 79e1a907 allowed each
            # (work/c7234bed/m1/truth-m1.txt)
            ('bash -o pipefail -c "$(echo python3 measure.py)"', d),
            ('eval -- "$(echo python3 measure.py)"', d),
            ('eval "$(true; echo python3 measure.py)"', d),
            ('sh < <(echo python3 measure.py)', d),
            ("bash <<'E'\neval \"$(echo python3 measure.py)\"\nE", d),
            ('x=$(echo python3 measure.py); bash -c "$x"', d),
            # M1 mutation round (recurse-off): bash and zsh ran the stub, f48a5d0f and 79e1a907 allowed it
            # (work/c7234bed/m1/truth-surv.txt)
            ("eval \"$(printf 'eval \\x24(echo python3 measure.py)')\"", d),
            # M1 mutation round (seg-frame-any; work/c7234bed/m1/truth-skip.txt, truth-skip2.txt)
            ('eval "${1:-$(echo python3 measure.py)}"', d),
            ('bash -c "${1:-$(echo python3 measure.py)}"', d),
            ('eval "${x:-$(echo python3 measure.py)}"', d),
            ('bash -c "${x:-$(echo python3 measure.py)}"', d),
            # card c7234bed (Viktor 48205, 2nd round: M1, M2, L1; work/c7234bed/r2/truth-r2.txt)
            ('f() { eval "$1"; }; f "$(echo python3 measure.py)"', d),
            ('set -- "$(echo python3 measure.py)"; eval "$1"', d),
            ('set -- "$(echo python3 measure.py)"; eval "${1}"', d),
            ('set -- "$(echo python3 measure.py)"; eval "$@"', d),
            ('set -- "$(echo python3 measure.py)"; eval "$*"', d),
            ('f() { bash -c "$1"; }; f "$(echo python3 measure.py)"', d),
            ('echo "$(echo python3 measure.py)" | bash', d),
            ('echo "$(echo python3 measure.py)" | sh -s', d),
            ('printf \'%s\\n\' "$(echo python3 measure.py)" | bash', d),
            ('echo "`echo python3 measure.py`" | bash', d),
            ('echo "$(echo python3 measure.py)" |& bash', d),
            ('echo "$(echo python3 measure.py)" | /bin/bash', d),
            ('cat <<E | bash\n$(echo python3 measure.py)\nE', d),
            ('cat <<\'E\' | bash\neval "$(echo python3 measure.py)"\nE', d),
            ('cat <<E | sh\n$(echo python3 measure.py)\nE', d),
            ('cat <<-E | bash\n\t$(echo python3 measure.py)\n\tE', d),
            ("bash <<E1\nbash <<'E2'\n$(echo python3 measure.py)\nE2\nE1", d),
            ('bash <<E1\nbash <<E2\nbash <<E3\n$(echo python3 measure.py)\nE3\nE2\nE1', d),
        ]
        prose ='mérve: 2 fájl változott (' + d + '/measure.py + _test.py), (./measure.py) is'
        allow = [
            ('python3 list.py', d),
            # card 00c714ea r2: a paren whose prefix matches no file runs nothing (zsh: no matches found; bash: a
            # syntax error); every paren read as unread blocked 311 fleet commands on the replay (code cut into words)
            ('python3 zq(x|y).py stat.py', d),
            # card 00c714ea r3: ; & < in a group: a zsh parse error, nothing runs (measured 11-21, Dave zblank/drive.py)
            ('python3 (measure.py|a;b) x', d),
            ('python3 (measure.py|a&b) x', d),
            ('python3 (measure.py|a<b) x', d),
            # card 00c714ea r3 m7 (blank-not-appended): the blank is part of the member, so these match no file and
            # zsh runs nothing (no matches found; bash: a syntax error), measured 11-21 (bin/shell-truth.py)
            ('python3 (meas ure.py|zq) x', d),
            ('python3 (measure.py |zq) x', d),
            ('python3 (zq| measure.py) x', d),
            ('python3 (15) x', d),  # a group whose member names no file (prose cut into words: `(15`, `(argv,`)
            # ... a quote or a substitution the gate took out of the word (found in the text all the same), a group
            # the text leaves open, a `=(..)` in a group: zsh -f ran nothing (bad pattern, no matches found), measured
            # 11-21 (a backtick left open blocks earlier: the lexer cannot read the text)
            ('python3 ("zq.py"|zz) x', d),
            ("python3 - <<'PY'\nnew=\"\"\"- the walk does not follow (`python3 -c`, `python3 -` + heredoc), the import\n\"\"\"\nPY", d),
            ('python3 (measure.py|zz', d),
            ('python3 (zz|=(echo measure.py)) x', d),
            ('python3 "m*.py"$(true) stat.py', d),  # a quoted glob before a substitution: no glob, no group
            # a PR text in a python heredoc (replay 11-20): the gate joins two backtick spans into the word
            # `/usr/bin/sqlite3(rows, ...`; its group holds blanks, and the prefix alone matched /usr/bin/sqlite3
            ('python3 - <<\'PY\'\ns="""Measured: `/usr/bin/sqlite3` 3.54.0 rolled it back; a database that cannot be copied'
             ' is named `(rows, journal rolled back, not read)`.\n"""\nPY', d),
            ("python3 -I - <<'PY'\nimport os\nprint(os.path.basename(x)[1])\nPY", d),
            # card 03a336e5: the made-name forms quoted in data a python heredoc reads (the replay's kanban dump, a PR
            # text); no shell runs them
            ("python3 -I - <<'PY'\nimport json\nprint(len(json.load(open('./kb.json'))))\nPY", d),
            ("python3 -I - <<'PY'\nprint(open('./pr.md').read()[:9])\nPY", d),
            ("python3 -I - <<'PY'\nprint(open('./made.md').read()[:9])\nPY", d),
            # ... and a shell word before ANOTHER name that only starts like it
            ("python3 -I - <<'PY'\nprint(open('./made.md').read()[:9])\nPY\nbash made.md.orig", d),
            # card 3bcd4514: a shell with a script operand reads its stdin as data (the fleet's `bash agent-msg.sh ... -
            # < f`), a non-shell reader of the file, and eval of a clean file
            ('bash runner.sh stat.py < made.json', d), ('cat made.json | bash runner.sh stat.py', d), ('cat made.json', d),
            ('python3 stat.py < made.json', d), ('cat made.json | python3 stat.py', d), ('cat < made.json', d),
            ('bash -o errexit runner.sh stat.py', d), ('eval "$(cat stat.py)"', d),
            # (Viktor 48464 N group) no reader of code after the wrapper forms, and a here-string's word is no file
            # (his mutant M12: << / <<< read as fed); his out.txt rows read stat.py here (this out.txt has a call)
            ('cat made.json | wc -l', d), ('command cat made.json', d), ('sudo cat made.json | python3 stat.py', d),
            ('grep x made.json | bash runner.sh stat.py', d), ('set -o pipefail; cat made.json | wc -l', d),
            ('cat made.json | python3 stat.py; echo done', d), ('eval "$(command cat stat.py)"', d),
            ('tail -n 3 made.json', d), ('bash -o pipefail -c "cat made.json | wc -l"', d),
            ('eval "$(command head -1 stat.py)"', d), ('nice -n 5 cat made.json | wc -l', d),
            ('bash -c "cat made.json | wc -l"', d), ('eval "$(LC_ALL=C tail -n 2 stat.py)"', d),
            ('echo cat made.json | bash runner.sh stat.py', d), ('env A=1 python3 stat.py made.json; bash', d),
            ('grep -c cat made.json', d), ('printf "%s" cat made.json > out2.txt', d),
            ('diff <(head -1 made.json) <(head -1 out.txt)', d), ('source <(head -n 2 stat.py)', d),
            ('bash <<< made.json', d),
            # (mutation round 3) another path that only starts like /dev/stdin is the shell's script, made.json its
            # stdin data; an earlier command's cat does not feed a later command's file (the separator ends it)
            ('bash /dev/stdin.bak < made.json', d), ('cat made.json | bash /dev/fd/0x', d),
            ('bash /dev/stdin/x < made.json', d), ('cat stat.py; python3 made.json; eval true', d),
            ('cat stat.py | bash; python3 made.json', d),
            # a reader of stdin, but the data file is a python script's, not fed to it
            ('python3 made.json; bash -s < stat.py', d),
            # a shell or eval word glued to another word is no reader (--bash, sh-, --eval, evaluate, `stat.` before a
            # <(), a quoted '<(' is a file name, not a substitution)
            ('cat made.json | python3 stat.py --bash', d), ('cat made.json | python3 stat.py sh-', d),
            ('cat made.json | python3 stat.py --eval', d), ('cat made.json | python3 stat.py evaluate', d),
            ('cat made.json; diff stat. <(cat stat.py)', d), ("source '<(cat made.json)'", d),
            # (mutation rd-procsub-lookbehind) the same with an interpreter in the command, so the file IS collected
            # (the row above never reaches the reader test: no interpreter, no cat collection)
            ('cat made.json | python3 stat.py; diff stat. <(cat stat.py)', d),
            ('cat made.json | python3 stat.py; resource <(cat stat.py)', d),
            ('echo bash; cat stat.py', d), ('$SHELL < stat.py', d),
            # head / tail of an output file outside a substitution or a pipe into an interpreter (the replay of 11-20:
            # 105 fleet commands, `head -1 HANDOFF.md && bash x.sh`, `tail -1 reg.jsonl | python3 -c ...`)
            ('head -1 out.txt && bash runner.sh stat.py', d), ('tail out.txt; python3 stat.py', d),
            ('head -3 out.txt | cut -c1-9; python3 stat.py', d), ("tail -1 out.txt | python3 -I -c 'print(1)'", d),
            ("tail -1 out.txt | python3 -c 'print(1)'", d), ("head out.txt | node -e '1'", d),
            # card af12091a: the K1 shapes before a harmless script, and as prose or data
            ("eval 'python3 -W \"a;b\" notes.py'", d),
            ('bash -c "python3 -W \\"a;b\\" notes.py"', d),
            ("bash -c \"python3 >'x;y' notes.py\"", d),
            ('git commit -m "fix: python3 -W \\"a;b\\" measure.py is prose"', d),
            ("echo 'python3 -W \"a;b\" measure.py'", d),
            ("eval 'python3 -W \"a;b\" notes.py `date`'", d),  # a backtick end: notes.py is the script either way
            ("eval 'python3 -W '\\''c;d'\\'' notes.py'", d),  # decoded payloads: a harmless script stays allowed
            ("eval 'eval \"python3 -W \\\"c;d\\\" notes.py\"'", d),
            (_eval_nest("python3 -W 'a' notes.py", 3), d),  # PAYLOAD_DEPTH levels are read
            # card 2917e6b6: a substitution in a harmless call's payload words, and a backtick that closes the call's
            ("eval 'python3 $(:) notes.py'", d),
            ("eval 'python3 notes.py $(:)'", d),
            ("eval 'python3 `:` notes.py'", d),
            ("eval 'python3 notes.py `date` measure.py'", d),
            ("eval 'x=`python3 notes.py`; echo measure.py'", d),
            # ... and a harmless script behind the same shapes stays allowed
            ("builtin eval 'python3 `:` notes.py'", d),
            ("eval 'echo `python3 notes.py` measure.py'", d),
            ("eval 'x=`python3 notes.py` measure.py'", d),
            # mutation round m5 (own-cut-end-off): a call with no cut inside its payload words does not search for its
            # own command, so 70 backticks after its script are no fail-closed block (bash runs notes.py)
            ("eval 'python3 notes.py" + ' `:`' * 70 + "'", d),
            # ... (heredoc-any-command, shrunk from a fleet command 11-16): a heredoc body with a backtick is read as
            # shell only when a shell reads it; cat writes this Python data file
            ("cat > t.py <<'PY'\n\"`''`\"\n\"python $() -m$('')\"]\nPY", d),
            # ... (own-depth-off, shrunk from a fleet data file 11-16): shell heredocs into shells, line after line; a
            # call's own text, read again, does not search for its own end again (without that: past OWN_LEX_BUDGET)
            ("<<'J'necho\nsh <<'J'necho\nsh <<'J'necho\nsh <<'J'necho\nsh <<'J'necho\nsource <<'J'necho\n"
             ". <<'J'necho J\nsh <<'J'necho b\nsudo sh <<'J'necho\nenv bash <<'J'necho o /|sh", d),
            ("bash <<'EOF'\necho `date`\npython3 notes.py\nEOF", d),
            ("cat <<'EOF' > /dev/null\nrun `python3 notes.py` then measure.py\nEOF", d),  # no shell reads it
            ("python3 - <<'PY'\ns = '`python3 x` measure.py'\nprint(s)\nPY", d),
            ("x=`eval 'python3 -W \"a;b\" notes.py'`; echo measure.py", d),
            # card 31045f4d (A, Klodel 43233): a data file after the script is its sys.argv, not run
            ('python3 stat.py regiszter.jsonl', d),
            ('python3 -I -B -u stat.py regiszter.jsonl', d),
            ('python3 -W ignore stat.py regiszter.jsonl', d),
            ('python3 -IW ignore stat.py regiszter.jsonl', d),
            ('python3 -Wignore stat.py regiszter.jsonl', d),
            ('python3 -Xdev stat.py measure.py', d),
            ('python3 -W measure.py stat.py', d),  # a warning filter, never run
            ('python3 stat.py measure.py', d),  # Viktor 43235 B/C: the same boundary as a path in the script
            # card 10624d73 (the price of Viktor 43324 LELET 1 won back): a plain top-level assignment before the use
            # is what bash does, so the words after the script are its argv again (the fleet's measuring forms)
            ('X=stat.py; python3 $X ./measure.py', d),
            ('X=stat.py\npython3 $X ./measure.py', d),
            # card 00c714ea: a blank in a quoted use, a glob or a brace after the plain script, a substitution's value
            ('Q="a b"; python3 stat.py "$Q"', d),
            ('Q="a b"; python3 stat.py $Q', d),
            ('python3 stat.py *.txt', d),
            ('python3 stat.py {a,b}.jsonl', d),
            ('S=$(mktemp -d); python3 stat.py $S', d),
            ('X="stat.py"; python3 "$X"', d),
            ("python3 '[m]easure.py' stat.py", d),  # a quoted glob is no glob
            ('python3 -c "x = \'bash \' * 3"', d),  # a call inside quoted code: no glob of its own
            ('P=' + d + '; python3 -I $P/stat.py ' + d + '/measure.py', d),
            ('/usr/bin/python3 stat.py regiszter.jsonl 2>/dev/null', d),
            # card b138f11b: the quoted paren name is read, not blocked on sight
            ("python3 '('ok.py", d),
            ('python3 \\(ok.py', d),
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
            # card e3d2fd6e: a backslash word that names no keychain-reading file, and one in prose
            ('./ok\\.js', d),
            ('\\./ok.js', d),
            ('grep -n "./dump\\.sh" /dev/null; true', d),
            # card e3d2fd6e r3: a backslash word in a quote or in a heredoc no shell reads is data (the fleet replay
            # on 99ee40e4: a JS regex a python heredoc writes, a sed script; a zsh-group reading took it for a script)
            ("python3 - <<'PY'\nif (a && /\\.(?:py|sh)$/.test(x)) return\nPY", d),
            ("python3 - <<'PY'\nconst rx = /expect\\(r\\)\\.(not\\.)?m\\((\\/(?:\\\\.|[^\\/\\n])+\\/[a-z]*)\\)/g\nPY", d),
            ("sed -n 's/^1\\. x/1. y (# a ${ }\\/$(( ))\\/ z/' /dev/null", d),
            ("echo 'a; ./dump\\.sh'", d),
            ('echo "a; ./dump\\.sh"', d),
            ("printf %s $'a; ./dump\\\\.sh'", d),
            ('git commit --dry-run -m "x; ./dump\\.sh y"', d),
            ("git commit --dry-run -m 'x; ./dump\\.sh y'", d),
            # the r3 replay: a quoted argument after a python -c payload; the lexer view of it does not lex, the
            # command does, and every copy of the word in it is in a quote
            ("python3 -I -c 'import sys; print(sys.argv[1])' 's/a ))\\/(( )) b/'", d),
            ("python3 -c 'print(1)' 'a (# ${ }\\/$(( ))\\/(( )) b), c'", d),
            ("python3 - <<'PY'\n./dump\\.sh\nPY", d),
            ("cat > /dev/null <<'EOF'\nx && ./dump\\.sh\nEOF", d),
            # r5 (Viktor 49996 R2): an unquoted-delimiter heredoc into another program is data too (the shell runs only
            # its $( ) and backticks; measured: bash does not run ./dump.sh), the second heredoc of a command as well
            ('cat > notes.md <<X\n./dump\\.sh a\nX', d),
            ('cat > notes.md <<X\nhello\n.\\/dump.sh\nX', d),
            ("cat > a.md <<'Y'\nz\nY\ncat > notes.md <<X\n./dump\\.sh\nX", d),
            ('cat >> notes.md <<X\n${HOME} \\./dump.sh\nX', d),
            ("cat > notes.md <<'X'\n$(date)\n./dump\\.sh\nX", d),  # a quoted body's $( ) is text
            # r6: a shell word elsewhere on the heredoc's line is not its reader (0196e1ee L1b): data, as on main
            ("grep -c sh <<'X'\n./dump\\.sh\nX", d),
            ("cat > n.md <<'X'; echo hi | bash\n./dump\\.sh\nX", d),
            ("echo hi | bash; cat > n.md <<'X'\n./dump\\.sh\nX", d),
            ("cat > n.md <<'A'; bash <<'B'\n./dump\\.sh\nA\nok\nB", d),
            ('grep -c sh <<X\n./dump\\.sh\nX', d),
            ('python3 "no"tes.py stat.py', d),
            ('python3 -m "notes"', d),
            ('python3 -Inotes', d),
            ('python3 -m json.tool regiszter.jsonl', d),
            ('python3 -W ignore -m notes', d),
            ('source "$(true)"runner.sh', d),
            ('. "$(dirname "$0")/notes.py"', d),
            ('./"no"tes.py', d),
            # card 8a73eab1: a variable's empty readings that name no keychain-reading file, a variable in a word after
            # the plain script (argv data), and a value the text sets for sure
            ('python3 notes$X.py', d),
            ('python3 no${X:-tes}.py', d),
            ('python3 stat.py measure$X.py', d),
            ('X=a; python3 stat.py $X', d),
            ('X=tes; python3 no$X.py', d),
            ('echo ${HOME}/x', d),
            ('python3 ' + '${A:-' * 8 + 'notes' + '}' * 8 + '.py', d),
            # Viktor r1 / Kernel r2: zsh's forms in argv data and in readings that name no keychain-reading file
            ('python3 notes$X:h.py', d),
            ('python3 no${X/#/tes}.py', d),
            ('python3 notes$X[1].py', d),
            ('python3 notes$+X.py', d),
            ('echo ${!HOM*}', d),
            ('python3 stat.py ${!HOM*} $X:P ${(L)X}', d),
            ('echo measure$X:P.py', d),
            # Kernel r2: a name list or a cut flag group is a glob: no matching file, no block (prop2 blocked a JS
            # template literal in a heredoc to cat: 3 of the replay's pairs)
            ('python3 no${!HOM*}tes.py', d),
            # Kernel r3: the cut flag group blocks, except in a heredoc body no shell reads (KNOWN-V9: a glob there)
            ("cat > out.mjs <<'EOF'\nconsole.log(`${(a + b)}`, full/lex=${(full / lex).toFixed(2)})\nEOF", d),
            # the name list's literal parts are glob-escaped: [1] is no character class, k1Zq.py is not matched
            ("python3 'k[1]'${!HOM*}q.py", d),
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
            # card deede5e4: a loop over plain words naming harmless files, a loop that names no script, an absolute
            # path after a directory change the gate does not follow, a known cd
            ('for f in twin.py fdname/ok.py; do python3 $f; done', d),
            ('for x in a b; do echo $x; done; python3 twin.py', d),
            # mutation round 1: -C of env's command is not env's; a value reassigned from outside the command is not
            # its old value (B is unknown, as any variable set outside: see "Not seen")
            ('env git -C sub2 log; python3 twin.py', d),
            ('env A=1 git -C sub2 status && python3 twin.py', d),
            ('A=sub2; A=$T; B=$A/only.py; python3 $B', d),
            ('pushd sub2 >/dev/null && python3 ' + d + '/twin.py', d),
            ('cd fdname && python3 ok.py', d),
            # card deede5e4 r2 (Viktor 49087 controls): the loop name assigned the same harmless value, an option cd
            # into a harmless directory, an absolute script after a cd -P, $PWD after a known cd, `--` before a
            # harmless directory
            ('F=twin.py; for F in twin.py; do python3 $F; done', d), ('cd -P fdname && python3 ok.py', d),
            ('cd -P sub2 && python3 ' + d + '/twin.py', d), ('cd fdname && python3 $PWD/ok.py', d),
            ('cd -- fdname && python3 ok.py', d),
            # card deede5e4, the replay's readings (675 fleet rows blocked by the first draft): a cd word in a heredoc
            # no shell reads, -C of another command next to env, a chained value naming a harmless file, a for loop
            # of python code next to a shell variable, a loop glob in python's argv after its script (data)
            ("python3 - <<'PY'\nx = 'cd|export'\nPY\npython3 fdname/ok.py", d),
            ('for m in sub2/*.py; do python3 fdname/ok.py $m; done', d),
            ('git -C sub2 status; env A=1 python3 fdname/ok.py', d),
            ('A=fdname; B=$A/ok.py; python3 $B', d),
            ("f=fdname/ok.py; python3 - <<'PY'\nfor f in os.listdir('.'): pass\nPY\npython3 $f", d),
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
            # card c6c67dde (Klodel 09:24: `cd /Users/klodel/marveen; bash scripts/agent-msg.sh ... <<'MSG'` blocked
            # on a path in the message): a relative agent-msg.sh after a cd to an absolute path is ours from there
            ("cd " + AM_ROOT + "; bash scripts/agent-msg.sh dave viktor - <<'M'\n" + d + "/measure.py\nM", AM_ROOT),
            ("cd " + AM_ROOT + " && bash scripts/agent-msg.sh dave viktor - <<'M'\n" + d + "/measure.py\nM", d),
            ("cd /tmp && cd " + AM_ROOT + " && bash scripts/agent-msg.sh dave viktor - <<'M'\n" + d + "/measure.py\nM",
             d),
            ("cd " + AM_ROOT + "\ntrue\nbash scripts/agent-msg.sh dave viktor - <<'M'\n" + d + "/measure.py\nM", AM_ROOT),
            # card c6c67dde r2: a .. with no symlink before it names the same directory either way
            ("cd " + AM_ROOT + "/scripts/.. && bash scripts/agent-msg.sh dave viktor - <<'M'\n" + d + "/measure.py\nM",
             d),
            # card c6c67dde r3: || or | before the cd, from this repo's root: ours wherever the shell is
            ("true || cd " + AM_ROOT + " && bash scripts/agent-msg.sh dave viktor - <<'M'\n" + d + "/measure.py\nM",
             AM_ROOT),
            ("true | cd " + AM_ROOT + " && bash scripts/agent-msg.sh dave viktor - <<'M'\n" + d + "/measure.py\nM",
             AM_ROOT),
            ("git commit -F - <<'MSG'   \n./measure.py\nMSG", d),  # trailing blanks after the operator
            ("cd " + d + " && bash " + AM + " dave viktor - <<'M'\n./measure.py\nM", d),  # absolute: any cd
            ("curl -s -X POST localhost:3420/api/messages --data-binary @- <<'J'\n./measure.py\nJ", d),
            # card 70a5fb2a: a body behind a quoted delimiter ending in a backslash is still data, its own
            # backslash-newline still joins, and a harmless command after the terminator passes
            ("curl -d @- <<'J\\'\n./measure.py\nJ\\\necho done", d),
            ("curl -d @- <<'J\\'\nx\\\nJ\\\necho done", d),
            # card 70a5fb2a round 2: a $'..' / $".." delimiter's body is still data up to its real terminator line,
            # and the old path's unjoined reading adds nothing where only harmless commands stand
            ("git commit -F - <<$'J'\n./measure.py\nJ\necho done", d),
            ('git commit -F - <<$"J"\n./measure.py\nJ\necho done', d),
            ("git commit -F - <<$'J\\x41'\n./measure.py\nJA\necho done", d),
            (': x \\\\\necho done\ncat <<Z', d),
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
            # Viktor 49925 L1 (main ALLOW, bash and zsh run nothing: data): a fed glob in a heredoc no shell reads is
            # read as written, its match not taken
            ("cat > notes.md <<'X'\necho ./meas*.py | bash\nX", d),
            ("cat > notes.md <<'X'\nx\necho ./meas?re.py | bash\nX", d),
            ('cat > notes.md <<X\necho ./meas*.py | bash\nX', d),
            ("cat > /dev/null <<'X'\necho ./{measure,zz}.py | bash\nX", d),
            # Viktor 49984 L1b (main ALLOW, bash and zsh run nothing: data): a printf brace in a data heredoc, a shell
            # word elsewhere on the heredoc's line (an argument of a data command, a command after a ;, another
            # heredoc), a fed line that only prints the glob, and an open pipeline into a non-shell
            ("cat > notes.md <<'X'\nprintf '%s\\n' ./{measure,zz}.py | sh\nX", d),
            ("cat >> notes.md <<X\nprintf '%s\\n' ./{measure,zz}.py | sh\nX", d),
            ("tee notes.md <<'X' >/dev/null\nprintf '%s\\n' ./{measure,zz}.py | sh\nX", d),
            ("cat > notes.md <<\\X\nprintf '%s\\n' ./{measure,zz}.py | sh\nX", d),
            ("grep -c sh <<'X'\necho ./meas*.py | bash\nX", d),
            ("cat > notes.md <<'X'; echo hi | bash\necho ./meas*.py | bash\nX", d),
            ("cat > notes.md <<'A'; bash <<'B'\necho ./meas*.py | bash\nA\necho hi\nB", d),
            ("echo 'echo ./meas*.py' | bash", d),
            ("echo 'cat ./meas?re.py' | bash", d),
            ("cat <<'X' |\necho ./meas*.py | bash\nX\ngrep x", d),
            ("echo hi | bash; cat > notes.md <<'X'\necho ./meas*.py | bash\nX", d),
            # card 0196e1ee: a reader of the pipe that runs no code from it, a glob into a non-shell, a quoted direct path
            # (the file named so does not exist), a function / loop that prints a harmless line, a substitution into a
            # non-shell, a benign script fed to a $var reader
            ('git ls-files | while read f; do wc -l "$f"; done', d),
            ('echo ./measure.py | while read l; do echo "$l"; done', d),
            ('echo hi | if true; then cat; fi', d),
            ("echo './meas*.py' | grep py", d),
            ("'./meas*.py'", d),
            ('f() { echo hi; }; f | bash', d),
            ('for f in a b; do echo $f; done | grep a', d),
            ('echo $(date) | grep x', d),
            ('echo ./stat.py | while read l; do $l; done', d),
            ('echo ./stat?.py | bash', d),
            # card 0196e1ee (fleet replay 11-21: 113 + 52 allow->block): a | or a direct word in a heredoc body or
            # a quote is data of whatever reads it; the unread rule and the globs are for the command's own code
            ("python3 - <<'PY'\ns = '''\n/**\n * doc\n */\n'''\nPY", d),
            ("python3 - <<'PY'\nx = 'echo \"$(cat)\" | bash'\nPY", d),
            ("python3 - <<'PY'\nx = 'echo ./meas*.py | bash'\nPY", d),
            ("echo 'a $(b) | bash'", d),
            # m6 readers-prose survived: a reader | (while read, read; eval) in a quote is prose, not a stop
            ("git commit -m 'note: echo ./measure.py | while read f; do bash; done'", d),
            ("printf '%s\\n' 'echo ./measure.py | read x; eval \"$x\"'", d),
            ("cat > n.md <<'EOF'\nrun: echo ${F:-x} | bash\nEOF", d),
            # fleet replay 2 (6 allow->block on c7f0c8c4): a payload mark that cuts the lexing of the text the
            # direct-pattern test reads (the command's own heredoc bodies decide), a body pipeline that walked to the
            # outer command's words, a word right after a process substitution (diff's argument)
            ("python3 - <<'PY'\ns = '''\n/**\n * doc\n */\n'''\nPY\npython3 -c ''", d),
            ("python3 - <<'PY'\n/**\nPY\npython3 -c 'print(1)'", d),
            ("cd scripts; python3 - <<'PY'\nx = '\\''')|sh'\nPY", d),
            ("cd scripts; python3 - <<'PY'\nrows = ['a\\'', ')|sh']\nPY", d),
            ('diff <(cat stat.py) ./meas*.py', d),
            ('cmp <(echo a) >(cat) ./meas*.py', d),
            # card 3bf9a741: a fed word is data where the line written out reads it as data, and no file of its own
            ('echo measure.py | xargs grep -c find', d),
            ('echo measure.py | xargs wc -l', d),
            ('echo measure.py | xargs cat', d),
            ('echo measure.py | xargs python3 stat.py', d),
            ('echo measure.py | xargs -I{} python3 stat.py {}', d),
            # round 2: the whole input line, and the quoted word after a shell's -c, harmless
            ("echo git status | xargs -I{} sh -c '{}'", d),
            ("echo python3 stat.py | xargs -I{} sh -c '{}'", d),
            ("echo measure.py | xargs -I{} sh -c 'wc -l {}'", d),
            # round 3: a wrapper before the shell, harmless code; and a shell word that is only an argument
            ("echo git status | xargs -I{} env sh -c '{}'", d),
            ("echo 1 | xargs -I{} timeout 5 sh -c 'sleep {}'", d),
            ('echo ./measure.py | xargs -I{} echo sh -c {}', d),
            ("echo ./measure.py | xargs -I{} env cat {}", d),
            ("printf 'ls -l\\n' | xargs -I@ sh -c @", d),
            ('echo stat.py | xargs python3', d),
            ('echo measure.py | xargs echo python3', d),
            ('echo measure.py | xargs', d),
            ('xargs -n1 echo <<< measure.py', d),
            ('echo measure.py || xargs python3', d),
            ('echo measure.py >| xargs python3', d),
            ("git commit -m 'echo measure.py | xargs python3'", d),
            ('echo measure.py | xargs -n1 basename | xargs ls', d),
            ('echo "x\'" | xargs grep a', d),
            ('python3 xrows.py', d), ('python3 -I xrows.py', d),  # a harmless list of many xargs rows
            ('echo ./measure.py >| bash', d),  # noclobber redirection, no pipe
            ('echo ./measure.py || bash', d),  # an or-list, no pipe
            ('echo ./measure.py | bashful', d),
            ('echo ./measure.py | source ./notes.py', d),  # source a file: no stdin reader
            ('echo ./measure.py | source /dev/stdin.bak', d),
            # card 39d885ef: the printed text stays allowed when it runs nothing that reads a secret
            ("printf 'echo hi\\n' | bash", d),
            # the fleet replay (dave 11-16): a pipeline in a Python string of a python3 heredoc. By the outer lexing
            # every stop of the body was gone, the pipeline started at the body's top and took measure.py in
            ("python3 - <<'PY'\np = 'measure.py'\nprint(f(\"echo x | tee /dev/stdout | bash\"))\nPY", d),
            # mutation m39 (body-none-nostop; the fleet differential, 6 commands of pulzus, kernel, viktor shrunk): a
            # body the lexer does not read (an odd quote) keeps every stop, as on main, so its pipeline starts on its
            # own line, not at the body's top
            ("python3 - <<'PY'\ns = 'it's ./measure.py'\nx = \"a | bash\"\nPY", d),
            ("cat > out.ts <<'TS'\n// it's ./measure.py\nconst lang = /(python|bash/\nTS", d),
            # card c7234bed: a harmless script printed for eval / a shell, and a printed name no shell runs
            ('eval "$(echo python3 notes.py)"', d),
            ('bash -c "$(echo python3 notes.py)"', d),
            ('echo "$(echo python3 measure.py)"', d),
            ('x=$(echo python3 measure.py); echo "$x"', d),
            ('diff <(echo python3 measure.py) <(echo b)', d),
            # card c7234bed (48033 M1): the substitution in another command than the reader's, a heredoc to cat
            ('bash -n x.sh && cat <(echo python3 measure.py)', d),
            ("cat <<'E'\neval \"$(echo python3 measure.py)\"\nE", d),
            ('bash -o pipefail -c "$(echo python3 notes.py)"', d),
            # M1 mutation round (rd-cls-off, feeder-cls-off, var-cls-off): bash and zsh ran nothing
            # (work/c7234bed/m1/truth-surv.txt)
            ("echo 'eval' \"$(echo python3 measure.py)\"", d),
            ("eval \"$(grep -c 'echo python3 measure.py' notes.txt)\"", d),
            ("x=$(echo python3 measure.py); bash -c 'echo $x'", d),
            # M1 mutation round (doc-quoted-all): echo prints it (work/c7234bed/m1/truth-skip.txt)
            ("bash <<'E'\necho \"$(echo python3 measure.py)\"\nE", d),
            # card c7234bed (Viktor 48205, 2nd round): the controls (work/c7234bed/r2/truth-r2.txt)
            ('echo "$(echo hi)" | bash', d),
            ('echo "$(date)" | bash', d),
            # card 0196e1ee m6 (unread-hits-script): a script file's body is not read for a fed substitution
            # (KNOWN-FEED-FILE); a harmless one passes. A data heredoc's pipe after a benign live one stays data
            ('bash feedhi.sh', d),
            ("echo ./stat.p? | bash; python3 - <<'PY'\nx = 'echo ./meas*.py | bash'\nPY", d),
            # m6 (live-words-reset-off): the live words of one reading are not carried into the next. hits() reads an
            # eval / bash -c text in data as a payload, where its | is live; script_hits reads the command, where the
            # same word is data (the row above does not kill it: survivor-cand, 14 of 20 shapes do, 11-21)
            ('git commit --dry-run -m "eval \'echo ./meas*.py | bash\'"; true', d),
            ("python3 - <<'PY'\nx = \"bash -c 'echo ./meas*.py | bash'\"\nPY", d),
            ('echo \'eval "echo ./meas*.py | bash"\'', d),
            ('echo "$(echo python3 measure.py)" | tee x.txt', d),
            ('echo "$(echo python3 measure.py)" | grep bash', d),
            ('echo "$(echo python3 measure.py)" | wc -l', d),
            ('cat <<E | bash\necho $(date)\nE', d),
            ('cat <<\'E\' | python3\neval "$(echo python3 measure.py)"\nE', d),
            ('echo "$1" | bash', d),
            ('f() { echo "$1"; }; f "$(echo python3 measure.py)"', d),
            ('f() { eval "$1"; }; f hi', d),
            # (2nd round mutation round; work/c7234bed/r2/truth-r2b.txt)
            ('echo "$(echo python3 measure.py)"; echo hi | bash', d),
            ('x="$(echo python3 measure.py)"; echo hi | bash', d),
            ('cat <<E\n$(echo python3 measure.py)\nE\necho hi | bash', d),
            ('cat <<\'E\' > x.txt\neval "$(echo python3 measure.py)"\nE\necho hi | bash', d),
            ('bash <<\'E\'\nx=\'eval "$(echo python3 measure.py)"\'\nE', d),
            ('cat <<\'E\' | bash\nx=\'eval "$(echo python3 measure.py)"\'\nE', d),
            # ... (the fleet replay, 5 commands of viktor 11-16): a reader and a substitution in a heredoc body's
            # strings are no code (the lexer's class), and an eval at a code position does not read a substitution
            # that stands in data
            ("python3 - <<'PY'\ns = 'eval \"$(echo python3 measure.py)\"'\nPY", d),
            ("eval x; python3 - <<'PY'\ns = \"$(echo python3 measure.py)\"\nPY", d),
            ("eval x; echo '$(echo python3 measure.py)'", d),
            ("cat <<'EOF'\n. /dev/stdin <<<'python3 measure.py'\nEOF", d),
            ("printf './measure.py\\n' | cat", d),
            ("echo 'x;' ./measure.py | cat", d),
            ("echo -e 'a\\tb' | bash", d),
            ("printf 'true\\nls\\n' | bash", d),
            ('echo hi 2>&1 | bash', d),
            ("printf 'x %s\\n' ./measure.py | cat", d),
            ("printf '%%s\\n' ./list.py | bash", d),
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
        # card 00c714ea r2 (Viktor 49408 LOW 1, locale-order): the shells' first match of ?a.py is _a.py where the
        # locale sorts it first; a runner without such a locale (en_US / hu_HU not installed) has no row to pin
        import locale
        old_coll = locale.setlocale(locale.LC_COLLATE)
        try:
            for loc in ('en_US.UTF-8', 'hu_HU.UTF-8'):
                try:
                    locale.setlocale(locale.LC_COLLATE, loc)
                except locale.Error:
                    continue
                if min(['-a.py', '_a.py'], key=locale.strxfrm) == '_a.py':
                    block += [('python3 loc/?a.py stat.py', d), ('python3 loc/*a.py stat.py', d)]
                    break
            try:  # hu_HU.UTF-8 alone puts cz.py first (the environment's and en_US's: cs.py)
                locale.setlocale(locale.LC_COLLATE, 'hu_HU.UTF-8')
                if min(['cs.py', 'cz.py'], key=locale.strxfrm) == 'cz.py':
                    block.append(('python3 loc2/c?.py stat.py', d))
            except locale.Error:
                pass
        finally:
            locale.setlocale(locale.LC_COLLATE, old_coll)
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
        # card 00c714ea r2: a ~ before a zsh group is the home's (expanduser): HOME is the fixture here (the hook in
        # run() has no HOME and would take the account's home)
        p = subprocess.run([sys.executable, '-I', HOOK], capture_output=True, text=True, timeout=20,
                           env={'PATH': '/usr/bin:/bin', 'HOME': d}, input=json.dumps(
                               {'tool_name': 'Bash', 'tool_input': {'command': 'python3 ~/m(easure.py|x) stat.py'},
                                'cwd': os.path.join(d, 'sub2')}))
        if p.returncode != 2 or 'KULCSKARIKA-KAPU' not in p.stderr:
            fails.append(f'script: should block (got {p.returncode}): a ~ before a zsh group, HOME = the fixture')
        # card 00c714ea r3 (Viktor 49709 L2): a ** walk is bounded by directories (MAX_STAR_DIRS 2000), not only by
        # matches: a no-match `**/x.py` in a large cwd walked to the 6 s watchdog. Past the bound it blocks at once
        # (a lean, KNOWN-KTP-OVER); under it a no-match passes. A tree of its own: d's ** rows stay as they are.
        import time as _t
        with tempfile.TemporaryDirectory() as big:
            for k in range(2100):
                os.makedirs(os.path.join(big, f'g{k // 100}', f'h{k}'))
                os.makedirs(os.path.join(big, 'hid', f'.g{k}', 'h'))
                os.makedirs(os.path.join(big, 'hid2', f'g{k // 100}', f'.h{k}'))
            # m7 (Dave survivor-cand 11-21): hidden directories are not counted (glob's ** does not enter them); a
            # ** that is not a whole component is a plain * (no walk); a ** member of a zsh group is bounded too
            for cmd, cwd, want in (('python3 **/zz_nomatch_q7.py x', big, 2), ('python3 ./**/zz_nomatch_q7.py x', big, 2),
                                   ('python3 **/zz_nomatch_q7.py x', d, 0),
                                   ('python3 hid/**/zz_nomatch_q7.py x', big, 0), ('python3 hid2/**/zz_nomatch_q7.py x', big, 0),
                                   ('python3 g**/zz_nomatch_q7.py x', big, 0), ('python3 **x/zz_nomatch_q7.py x', big, 0),
                                   ('python3 (**/zz_nomatch_q7.py|zq) x', big, 2),
                                   ('python3 (zq|**/zz_nomatch_q7.py) x', big, 2),
                                   # r5 (Viktor 49863 M1): a loop value's ** walk is bounded the same way
                                   ('for f in **/zz_nomatch_q7.py; do python3 "$f"; done', big, 2),
                                   ('for f in ***/zz_nomatch_q7.py; do python3 "$f"; done', big, 2),
                                   ('for f in **/zz_nomatch_q7.py; do python3 "$f"; done', d, 0)):
                t = _t.monotonic()
                code, err = bash_in(cmd, cwd)
                took = _t.monotonic() - t
                if code != want or took > 2:
                    fails.append(f'script: ** walk {cmd[:40]!r}: want rc {want} under 2 s, got {code} in {took:.1f} s')
        # card 00c714ea r4 (Viktor 49785 L1): zsh's `***/` walks like `**/` and follows links; Python's glob read it as one
        # `*` and the gate passed it. Measured 11-21 (bin/shell-truth.py): zsh -f and extendedglob ran a/b/c/x.py for
        # `***/x.py`, `a/***/x.py`, `***/c/x.py` and one behind a link for `sub/***/x.py`; `****/` and `a***/` matched
        # nothing. `sub/**/m2.py` is a lean (KNOWN-KTP-OVER): zsh's `**/` does not follow the link, Python's does.
        with tempfile.TemporaryDirectory() as deep:
            measure_src = open(os.path.join(d, 'measure.py'), encoding='utf-8').read()
            for rel in ('a/b/c/measure.py', 'real/d/m2.py'):
                os.makedirs(os.path.join(deep, os.path.dirname(rel)), exist_ok=True)
                with open(os.path.join(deep, rel), 'w', encoding='utf-8') as f:
                    f.write(measure_src)
            os.makedirs(os.path.join(deep, 'a', 'b', 'z'))  # r5: a benign file deep down (loop-benign-star2)
            with open(os.path.join(deep, 'a', 'b', 'z', 'zz.py'), 'w', encoding='utf-8') as f:
                f.write("print('ok')\n")
            os.makedirs(os.path.join(deep, 'sub'))
            os.symlink('../real', os.path.join(deep, 'sub', 'lnk'))
            for cmd, want in (('python3 ***/measure.py x', 2), ('python3 a/***/measure.py x', 2),
                              ('python3 ***/c/measure.py x', 2), ('python3 sub/***/m2.py x', 2),
                              ('python3 sub/**/m2.py x', 2),
                              ('python3 ****/measure.py x', 0), ('python3 a***/measure.py x', 0),
                              # r4 m8 (star3-no-lookahead): a trailing *** is one level in zsh (a/b/c/*** ran
                              # the script there, measured); read as ** its first match was the directory
                              ('python3 a/b/c/*** x', 2), ('python3 real/d/*** x', 2),
                              # r4 m8 (star3-nomatch-off): a ***/ member of a zsh group: zsh stops ("bad
                              # pattern", measured), the gate walks it as ** (the lean, as for **/)
                              ('python3 (zq|***/measure.py) x', 2),
                              # r5 (Viktor 49863 S09): two ***/ in one word, each read as **/ (a/b/c/measure.py)
                              ('python3 a/***/c/***/measure.py x', 2),
                              # r5 (Viktor 49863 M1, old, main too): a loop value with ** or ***/ is read recursively
                              # (zsh ran a/b/c/measure.py, Viktor loop_rows.py 11-21; a plain iglob read ** as *)
                              ('for f in **/measure.py; do python3 "$f"; done', 2),
                              ('for f in ***/measure.py; do python3 "$f"; done', 2),
                              ('for f in **/*.py; do python3 "$f"; done', 2),
                              ('for f in **/measure.py; do python3 $f; done', 2),
                              # Viktor 49878 INFO (X08): two ***/ in one loop value (zsh ran it, his x08.txt)
                              ('for f in a/***/c/***/measure.py; do python3 "$f"; done', 2),
                              ('for f in a/b/c/[^z]easure.py; do python3 "$f"; done', 2),  # [^z] is [!z] (r1)
                              ('for f in **/zz.py; do python3 "$f"; done', 0),  # loop-benign-star2
                              ('for f in a/**/zz.py; do python3 "$f"; done', 0)):
                code, err = bash_in(cmd, deep)
                if code != want:
                    fails.append(f'script: ***/ walk {cmd!r}: want rc {want}, got {code}')
        # card 3bcd4514: the stdin reading is linear. In the hook a long call blocks before it (MAX_ARGS, ARGS_WINDOW),
        # but the token pass (_hn_fed) and the reader regex read the WHOLE command (a short call after a long text), so
        # they are timed in process: runs of shell words with options (-o read with its word or alone, -eo, --rcfile),
        # dots, path pieces, file names and redirects, 120-560 KB, each ending where no walk matches (` y z`); want the
        # verdict and under 2 s each (measured 11-20: 0.5 s at most, under a parallel test run). Unbounded, the option
        # walk was quadratic (`bash -o bash -o ...` past 120 s); past _HN_MAX_OPTS (16) options it counts as a reader.
        hn_stdin = ('import importlib.util as u,sys,time; s=u.spec_from_file_location("g",sys.argv[1]); '
                    'm=u.module_from_spec(s); s.loader.exec_module(m); b="$S dump-"+"keychain"; c="cat made.json; "; R=['
                    '(c+"bash -o x "*30000+"y z",0),(c+"bash -o -o -o "*20000+"y z",0),(c+"bash -o "*40000+"y z",0),'
                    '(c+"sh -o "*40000+"y z",0),(c+"bash -x "*40000+"y z",0),(c+"bash --rcfile x "*20000+"y z",0),'
                    '(c+". x "*40000,0),(c+"bash -eo "*40000+"y z",0),("echo "+"made.json "*40000,0),'
                    '("< x "*40000+"bash z",0),(c+"bash"+" -x"*16+" y",0),(c+"bash"+" -x"*17+" y",1),'
                    '(c+"bash"+" -o x"*16+" y",0),(c+"bash"+" -x"*40000,1),(c+"/sh"*40000,1),'
                    '("cat made.json "*40000+"| bash",1),(c+"bash -c"+" \\"$(x)\\""*40000,1)]\n'
                    'for c,w in R:\n t=time.monotonic(); g=m._hn_shell_file("/d/made.json",b,c,()); '
                    'd=time.monotonic()-t\n if g!=bool(w) or d>2: print(repr(c[:40]),g,round(d,2))')
        p = subprocess.run([sys.executable, '-I', '-c', hn_stdin, HOOK], capture_output=True, text=True, timeout=120,
                           env={'PATH': '/usr/bin:/bin'})
        if p.returncode != 0 or p.stdout.strip():
            fails.append(f'script: stdin timing (in process): {p.stdout.strip()[:300]} {p.stderr.strip()[-300:]}')
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
        # card 39d885ef (the fleet replay): a script file's text is not lexed by the pipeline reading (the gate lexes
        # no script file's text). A node file of 82 KB with 30 `((` retries cost about 1 s per reading, four readings
        # per file: 133 -> 1 345 ms and 894 -> 3 945 ms on fleet commands, benign ones blocked on the budget. The
        # command's own text is lexed (its quoted stops: Viktor 43793 LOW 1)
        nolex = ('import importlib.util as u,sys; s=u.spec_from_file_location("g",sys.argv[1]); m=u.module_from_spec(s);'
                 ' s.loader.exec_module(m); n=[]; real=m.shell_lex.lex\n'
                 'def lex(t):\n    n.append(len(t)); return real(t)\n'
                 'm.shell_lex.lex = lex; t = "x = 1\\necho \'./a.sh;\' | bash\\n"\n'
                 'm.hits(t, True); a = len(n); getattr(m, "_LEX_CACHE", {}).clear(); n.clear()\n'
                 'm.hits(t + " ", False); print(a, len(n) > 0)')
        p = subprocess.run([sys.executable, '-I', '-c', nolex, HOOK], capture_output=True, text=True, timeout=20,
                           env={'PATH': '/usr/bin:/bin'})
        if p.stdout.strip() != '0 True':
            fails.append(f'script: pipeline reading lexes a script file / not the command -> {p.stdout.strip()!r} '
                         f'{p.stderr[-200:]!r}, want 0 True')
        # card c7234bed (48033 M1 rework, the replay): generated_lines() lexes no script file's text and no text past
        # GEN_LEX_MAX (a 1 MB text cost 1-4 s a reading, 6 fleet commands past the script budget), and the lexer-less
        # path keeps the nested form of a shell file (the whole body read first: the cut part first put a `$` line
        # between the name and its subcommand, and 79e1a907's block of `bash x.sh` was lost)
        genlex = ('import importlib.util as u,sys; s=u.spec_from_file_location("g",sys.argv[1]); m=u.module_from_spec(s);'
                  ' s.loader.exec_module(m); n=[]; real=m.shell_lex.lex\n'
                  'def lex(t):\n    n.append(len(t)); return real(t)\n'
                  'm.shell_lex.lex = lex\n'
                  'big = "eval \\"$(echo echo hi)\\"\\n" + "x\\n" * (m.GEN_LEX_MAX // 2)\n'
                  'm.generated_lines(big); a = len([k for k in n if k > m.GEN_LEX_MAX])\n'
                  'nest = "#!/bin/bash\\neval \\"$(echo $(echo s" + "ec" + "u\'\'rity) dump-key\'\'chain)\\"\\n"\n'
                  'print(a, m.hits(nest, True))')
        p = subprocess.run([sys.executable, '-I', '-c', genlex, HOOK], capture_output=True, text=True, timeout=60,
                           env={'PATH': '/usr/bin:/bin'})
        if p.stdout.strip() != "0 ['secret-read']":
            fails.append(f'script: generated_lines lexes a big text / loses the nested form -> {p.stdout.strip()!r} '
                         f'{p.stderr[-200:]!r}, want 0 [\'secret-read\']')
        # card c7234bed M1 mutation round (prefilter-reader-off, raw-part-off, raw-window-off, raw-comment-off; the
        # in-process probe work/c7234bed/m1/raw-probe.py): a text with no reader word is not lexed at all; a feeder
        # part of the lexer-less path is GEN_RAW_PART chars at most; in a script file's text a reader farther than
        # GEN_RAW_BEFORE before the opener is not its reader (bash and zsh ran nothing: an assignment), and a comment
        # with a quote in the substitution does not end the reading (zsh ran the stub; bash 3.2 reads the quote,
        # fail-closed there; the command form is truth-m1.txt row 17)
        rawpin = ('import importlib.util as u,sys; s=u.spec_from_file_location("g",sys.argv[1]); m=u.module_from_spec(s);'
                  ' s.loader.exec_module(m); n=[]; real=m.shell_lex.lex\n'
                  'def lex(t):\n    n.append(len(t)); return real(t)\n'
                  'm.shell_lex.lex = lex\n'
                  'm.generated_lines("x=$(echo hi)\\ny=`printf a`\\n"); a = len(n); m.shell_lex.lex = real\n'
                  'lens = []; sp = m.stdin_pipelines\n'
                  'def rec(t, *x, **k):\n    lens.append(len(t)); return sp(t, *x, **k)\n'
                  'm.stdin_pipelines = rec; m.generated_lines("eval \\"$(echo " + "a" * 5000 + ")\\"\\n", lexed=False)\n'
                  'm.stdin_pipelines = sp; b = bool(lens) and max(lens) <= m.GEN_RAW_PART + len(" | bash")\n'
                  'sec = "s" + "ec" + "urity dump-keychain"\n'
                  'far = m.hits("eval true\\n#" + "x" * 200 + "\\nx=$(echo " + sec + ")\\n", True)\n'
                  'cm = m.hits("eval \\"$(echo x # it\'s\\necho " + sec + ")\\"\\n", True)\n'
                  'print(a, b, far, cm)')
        p = subprocess.run([sys.executable, '-I', '-c', rawpin, HOOK], capture_output=True, text=True, timeout=60,
                           env={'PATH': '/usr/bin:/bin'})
        if p.stdout.strip() != "0 True [] ['secret-read']":
            fails.append(f'script: generated_lines raw path (no-reader lexing, part cap, reader window, comment) -> '
                         f'{p.stdout.strip()!r} {p.stderr[-200:]!r}, want 0 True [] [\'secret-read\']')
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
        # card af12091a: OWN_LEX_BUDGET is per decision (an in-process caller, the replay, judges many commands): after
        # a command that used it up, the next one gets the whole budget again
        own = ('import importlib.util as u,sys,time; s=u.spec_from_file_location("g",sys.argv[1]); m=u.module_from_spec(s);'
               ' s.loader.exec_module(m)\nfor c in sys.argv[2:]:\n    m.T0 = time.monotonic()\n'
               '    try:\n        print(",".join(m.script_hits(c, ' + repr(d) + ')) or "-")\n'
               '    except m.TooManyArgs:\n        print("too-many")')
        p = subprocess.run([sys.executable, '-I', '-c', own, HOOK, "bash -c '" + 'python3 $(a;b notes.py; ' * 1500 + "'",
                            "eval '" + 'python3 -W "a;b" notes.py; ' * 1000 + "'"], capture_output=True, text=True,
                           timeout=60, env={'PATH': '/usr/bin:/bin'})
        lines = p.stdout.splitlines()
        if len(lines) != 2 or not lines[0].startswith('script-too-many-args') or '2000000' not in lines[0] or lines[1] != '-':
            fails.append(f'script: OWN_LEX_BUDGET per decision -> {lines!r} {p.stderr[-200:]!r}, want too-many then -')
        # card af12091a (m3 own-budget-off survived): every pass of the lexer counts against OWN_LEX_BUDGET. 70 openers
        # that each need a retry, in a call quoted open: the end filter gives up (past MAX_SPLIT_RETRIES) and every end
        # is lexed up to 65 times. Counted once per lexing, 2 million characters took 6.4 s (only the watchdog stopped
        # it), and the 500-end line passed after 4.5 s. In process (no watchdog) the budget stops both, under 2 s.
        # _lex_no_segments runs lex()'s retry loop itself to charge each pass: its reading must be lex()'s.
        per_pass = ('import importlib.util as u,sys,time; s=u.spec_from_file_location("g",sys.argv[1]); m=u.module_from_spec(s);'
                    ' s.loader.exec_module(m); L=m.shell_lex\nfor c in sys.argv[2:4]:\n    m.T0 = t = time.monotonic()\n'
                    '    try:\n        r = ",".join(m.script_hits(c, ' + repr(d) + ')) or "-"\n'
                    '    except m.TooManyArgs as e:\n        r = "too-many " + str(e)\n'
                    '    print(r[:60], "%.2f" % (time.monotonic() - t))\nm.OWN_LEX_BUDGET = 10**12; bad = []\n'
                    'for k in (0, 1, 63, 64, 65, 70):\n'
                    '    for t in ("python3 -W \\"a;" + "$((y) );" * k + "\\" x.py", "python3 $((1 #x)) " + "((y) ) " * k + "m.py"):\n'
                    '        so = L.segments_of; L.segments_of = m._no_segments\n'
                    '        try:\n            ref = L.lex(t)\n        finally:\n            L.segments_of = so\n'
                    '        mine = m._lex_no_segments(t)\n'
                    '        if {a: b for a, b in mine.items() if a != "segments"} != {a: b for a, b in ref.items() if a != "segments"}:\n'
                    '            bad.append(k)\nprint("lex-same", bad)')
        retry_open = "eval 'python3 -W \"a;" + '$((y) );' * 70
        p = subprocess.run([sys.executable, '-I', '-c', per_pass, HOOK, retry_open + ';' * 500 + "'",
                            retry_open + ';' * 3000 + "\" notes.py'"], capture_output=True, text=True, timeout=60,
                           env={'PATH': '/usr/bin:/bin'})
        lines = p.stdout.splitlines()
        if (len(lines) != 3 or lines[2] != 'lex-same []'
                or any(not ln.startswith('script-too-many-args (a hívások') or float(ln.split()[-1]) >= 2
                       for ln in lines[:2])):
            fails.append(f'script: OWN_LEX_BUDGET per lexer pass -> {lines!r} {p.stderr[-200:]!r}, want 2x too-many under 2 s, lex-same []')
        # card af12091a (Viktor 47244 (1)): the decoded payloads only add. Every block row, judged with them and with
        # decoded_payloads() giving nothing: a row whose script rules block without them blocks with them too
        only_adds = ('import importlib.util as u,json,sys,time; s=u.spec_from_file_location("g",sys.argv[1]);'
                     ' m=u.module_from_spec(s); s.loader.exec_module(m); real=m.decoded_payloads; out=[]\n'
                     'for c, w in json.load(sys.stdin):\n    r=[]\n    for f in (real, lambda t: []):\n'
                     '        m.decoded_payloads=f; m.T0=time.monotonic(); r.append(bool(m.script_hits(c, w)))\n'
                     '    out.append(r)\nprint(json.dumps(out))')
        p = subprocess.run([sys.executable, '-I', '-c', only_adds, HOOK], input=json.dumps(block), capture_output=True,
                           text=True, timeout=600, env={'PATH': '/usr/bin:/bin'})
        try:
            pairs = json.loads(p.stdout)
        except ValueError:
            pairs = None
        if not pairs or len(pairs) != len(block):
            fails.append(f'script: decoded payloads only add -> no result {p.stderr[-200:]!r}')
        else:
            lost = [cmd[:60] for (cmd, _), (w, wo) in zip(block, pairs) if wo and not w]
            if lost:
                fails.append(f'script: decoded payloads took a block away: {lost!r}')
        # ... and the own-command search on its own: the decoded payloads read these rows too, so the rows above do not
        # tell a broken own-command search apart (mutation m3: the closing-quote variant removed, single or double
        # quote only, the escape guard, the expanded walk, all survived). With no decoded text, each still blocks
        own_only = [(c, d) for c in (
            "eval 'python3 -W \"a;b\" measure.py'", "eval \"python3 -W 'a;b' measure.py\"",
            "bash -c \"python3 -W 'a;b' measure.py\"", 'bash -c "python3 -W \\"a;b\\" measure.py"',
            "eval 'python3 >\"x;y\" measure.py'", "eval 'python3 -W \"a;b\" -W x\\; measure.py'",
            "eval 'python3 -W \"a;b\" `true` measure.py'", "echo X=notes.py; eval 'python3 -W \"a;b\" $X measure.py'",
            "eval 'python3 $(:) measure.py'", "eval 'python3 -W \"a;b\" notes.py; python3 -W \"a;b\" measure.py'")]
        own_alone = ('import importlib.util as u,json,sys,time; s=u.spec_from_file_location("g",sys.argv[1]);'
                     ' m=u.module_from_spec(s); s.loader.exec_module(m); m.decoded_payloads=lambda t: [];'
                     ' m.shell_heredoc_bodies=lambda c, lx: []; out=[]\n'
                     'for c, w in json.load(sys.stdin):\n    m.T0=time.monotonic(); out.append(bool(m.script_hits(c, w)))\n'
                     'print(json.dumps(out))')
        p = subprocess.run([sys.executable, '-I', '-c', own_alone, HOOK], input=json.dumps(own_only),
                           capture_output=True, text=True, timeout=120, env={'PATH': '/usr/bin:/bin'})
        try:
            alone = json.loads(p.stdout)
        except ValueError:
            alone = None
        if not alone or len(alone) != len(own_only):
            fails.append(f'script: own-command search alone -> no result {p.stderr[-200:]!r}')
        elif not all(alone):
            fails.append(f'script: own-command search alone let through: {[c[:60] for (c, _), b in zip(own_only, alone) if not b]!r}')
        # card af12091a (the replay: 39 benign fleet commands past OWN_LEX_BUDGET): the end filter of the own-command
        # search only skips ends that cannot read. Every block and allow row is judged the same with it and without it
        # (budget lifted: the unfiltered search is the slow one). A third pass builds the filter at the first failed
        # end (_OWN_FILTER_AFTER 0): on a short row the failed ends never cost enough to build it, so without this
        # pass every row compared the unfiltered reading with itself (mutation m3 on 9c1810bd: 12 filter mutants that
        # skip more ends survived, e.g. every substitution's end read as broken)
        same = ('import importlib.util as u,json,sys,time; s=u.spec_from_file_location("g",sys.argv[1]);'
                ' m=u.module_from_spec(s); s.loader.exec_module(m); m.OWN_LEX_BUDGET=10**13; out=[]; built=[0]\n'
                'real_f=m._own_end_filter\n'
                'def counted(*a):\n    f=real_f(*a)\n    built[0]+=bool(f)\n    return f\n'
                'm._own_end_filter=counted\n'
                'for c, w in json.load(sys.stdin):\n    r=[]\n    for on, after in ((True, 2), (True, 0), (False, 2)):\n'
                '        m._OWN_FILTER[0]=on; m._OWN_FILTER_AFTER[0]=after; m.T0=time.monotonic(); r.append(m.script_hits(c, w))\n'
                '    out.append(r[0]==r[1]==r[2])\nout.append(built[0])\nprint(json.dumps(out))')
        rows = block + allow
        p = subprocess.run([sys.executable, '-I', '-c', same, HOOK], input=json.dumps(rows), capture_output=True,
                           text=True, timeout=900, env={'PATH': '/usr/bin:/bin'})
        try:
            eq = json.loads(p.stdout)
            built = eq.pop()
        except (ValueError, AttributeError, IndexError):
            eq, built = None, 0
        # the comparison is empty unless the filter was built: on the rows it must be, 74 times on the final head (2026-11-18)
        if eq is not None and built < 40:
            fails.append(f'script: end filter built on only {built} row passes, the comparison proves nothing')
        if not eq or len(eq) != len(rows):
            fails.append(f'script: end filter only skips -> no result {p.stderr[-200:]!r}')
        elif not all(eq):
            fails.append(f'script: end filter changed a verdict: {[c[:60] for (c, _), e in zip(rows, eq) if not e]!r}')
        # card 39d885ef: pipes_union skips the escape-kept second reading when no backslash-letter was taken off (the
        # same text). Every row: hits() and script_hits() the same with the skip and without it; both branches must
        # run on the rows (a comparison where one side never ran proves nothing: af12091a m3)
        esc_same = ('import importlib.util as u,json,sys,time; s=u.spec_from_file_location("g",sys.argv[1]);'
                    ' m=u.module_from_spec(s); s.loader.exec_module(m); out=[]; n=[0, 0]\n'
                    'real_p=m.stdin_pipelines\n'
                    'def counted(*a, **k):\n    n[1 if m._KEEP_ESC[0] else 0]+=1\n    return real_p(*a, **k)\n'
                    'm.stdin_pipelines=counted\n'
                    'for c, w in json.load(sys.stdin):\n    r=[]\n    for skip in (True, False):\n'
                    '        m._ESC_SKIP[0]=skip; m.T0=time.monotonic(); r.append((m.hits(c), m.script_hits(c, w)))\n'
                    '    out.append(r[0]==r[1])\nout.append(n)\nprint(json.dumps(out))')
        p = subprocess.run([sys.executable, '-I', '-c', esc_same, HOOK], input=json.dumps(rows), capture_output=True,
                           text=True, timeout=900, env={'PATH': '/usr/bin:/bin'})
        try:
            eq = json.loads(p.stdout)
            first, second = eq.pop()
        except (ValueError, AttributeError, IndexError, TypeError):
            eq, first, second = None, 0, 0
        if not eq or len(eq) != len(rows):
            fails.append(f'script: escape-kept skip -> no result {p.stderr[-200:]!r}')
        elif not all(eq):
            fails.append(f'script: escape-kept skip changed a verdict: {[c[:60] for (c, _), e in zip(rows, eq) if not e]!r}')
        # each mode makes the same first readings (first / 2 each); the forced mode adds a second one to every first, so
        # second - first / 2 is the skip mode's second readings: some (the rows with a backslash-letter), not all
        elif not 0 < second - first // 2 < first // 2:
            fails.append(f'script: escape-kept skip: {first // 2} first readings per mode, {second - first // 2} '
                         f'second ones with the skip (want some, not all)')
        # ... and one shape per rule of the filter, in-process: the call's own-command reading is the same with and
        # without the filter, and the filter keeps the lexing small (each rule switched off, its shape lexes 97 000
        # to 700 000 characters: every end of the 300 is lexed from the call's start)
        shapes = {
            'whole-quote': ' -W "a;b" \'' + 'x;' * 300 + '\' m.py',
            'whole-subst': ' -W "a;b" $(' + 'x;' * 300 + ') m.py',
            'body-whole': ' -W "a;b" <<E m.py\n' + 'x;\n' * 300 + 'E\n',
            'body-strip': ' -W "a;b" <<E m.py\n' + "x' ;\n" * 300 + 'E\n',
            'pending': ' -W "a;b" <<E m.py' + ' |' * 300 + '\nE\n',
            'broken': ' -W "a;b" `(` m.py' + ' x;' * 300,
            'strip-quote': ' -W "a;b" \'' + 'x";' * 300 + '\' m.py',
            # the filter's lexing past MAX_SPLIT_RETRIES (70 '((y) )' after the end) splits every opener: the
            # arithmetic '$((1 #x))' turns into a comment there, and without the guard the clean end after it was
            # skipped (measured: work/af12091a/retrycap.py, readings differed at 150 and 1000). Reading only
            'retry-cap-150': ' -W "a' + ';' * 150 + '" $((1 #x)) notes.py; m.py' + ' ((y) )' * 70,
            'retry-cap-1000': ' -W "a' + ';' * 1000 + '" $((1 #x)) notes.py; m.py' + '\n((y) )' * 70,
        }
        cost = ('import importlib.util as u,json,sys; s=u.spec_from_file_location("g",sys.argv[1]);'
                ' m=u.module_from_spec(s); s.loader.exec_module(m); m.OWN_LEX_BUDGET=10**13; out={}\n'
                'def norm(x):\n    if isinstance(x, (list, tuple)):\n        return [norm(y) for y in x]\n'
                '    if hasattr(x, "__dict__"):\n        return sorted((k, repr(norm(v))) for k, v in vars(x).items())\n'
                '    return x\n'
                'for k, rest in json.load(sys.stdin).items():\n    r=[]\n    for on in (True, False):\n'
                '        m._OWN_FILTER[0]=on; m._OWN_LEXED[0]=0\n'
                '        g=norm(m._own_command_groups("python3", rest, rest.index(";"), False)); r.append((g, m._OWN_LEXED[0]))\n'
                '    out[k]=[r[0][0]==r[1][0], len(r[0][0]), r[0][1], r[1][1]]\nprint(json.dumps(out))')
        p = subprocess.run([sys.executable, '-I', '-c', cost, HOOK], input=json.dumps(shapes), capture_output=True,
                           text=True, timeout=120, env={'PATH': '/usr/bin:/bin'})
        try:
            got = json.loads(p.stdout)
        except ValueError:
            got = {}
        for k in shapes:
            same_r, n, on, off = got.get(k, [False, 0, -1, -1])
            if k.startswith('retry-cap'):
                on, off = 1, 10001  # the reading is what this shape pins
            if not same_r or n == 0 and k != 'broken' or not 0 < on <= 10000 or off <= 10000:
                fails.append(f'script: end filter shape {k}: same {same_r}, {n} groups, lexed {on} with the filter '
                             f'(want <= 10000), {off} without (want > 10000) {p.stderr[-120:]!r}')
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
            # card af12091a: every call of a long line looks for its own command end; Viktor's Q1 read up to the line
            # end per call (5-6 s, and a fail-closed block of the first two). The third has the script call at the
            # end; the fourth never lexes cleanly and blocks on OWN_LEX_BUDGET (6 s watchdog without it)
            ("eval '" + 'python3 -W "a;b" notes.py; ' * 1500 + "'", 0),
            ('bash -c "' + 'python3 -W \\"a;b\\" notes.py; ' * 800 + '"', 0),
            ("eval '" + 'python3 -W "a;b" notes.py; ' * 1500 + 'python3 -W "a;b" measure.py' + "'", 2),
            ("bash -c '" + 'python3 $(a;b notes.py; ' * 1500 + "'", 2),
            # past 64 substitutions: the call's own command reads cleanly (the lexer's problems, not its segments, which
            # LexTooBig bounds) but is past the lexer's bounds, which interp_groups would read the old way: blocks
            # (before the end filter it blocked on OWN_LEX_BUDGET, every end raising LexTooBig); bash ran measure.py
            ("eval 'python3 -W \"a;b\" " + '$(:)' * 900 + " measure.py'", 2),
            # the replay (39 benign fleet commands): calls quoted in Python code in a heredoc never read cleanly, and
            # every end of each was lexed from its start (a block on OWN_LEX_BUDGET at 60 lines); the end filter
            ("python3 - <<'PY'\nadd = \"\"\"\n" + "    ('python3 -W \"a;b\" notes.py', d),\n" * 120 + "\"\"\"\nPY", 0),
            # Viktor 47244 (1): MAX_PAYLOADS decoded payloads are read, one more blocks unread
            ('; '.join("eval 'python3 -W '\\''a;b'\\'' n%d.py'" % i for i in range(64)), 0),
            ('; '.join("eval 'python3 -W '\\''a;b'\\'' n%d.py'" % i for i in range(65)), 2),
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
            ("bash -c '" + 'python3 $(a;b notes.py; ' * 1500 + "'", d),  # card af12091a: past OWN_LEX_BUDGET
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
            # card 0196e1ee: a pipeline's first word and the functions the text defines are read once (one search
            # of the whole text per pipe and per name ran `echo 'x' | bash; ` x 20 000 into the 6 s watchdog)
            ('; '.join('a%d | bash' % i for i in range(20000)), 2), ('f() { echo a; }; ' + 'f | bash; ' * 20000, 0),
            # card 3bf9a741: past XARGS_MAX xargs that run no plain data command, XARGS_MAX_WORDS fed words of one,
            # XARGS_MAX_CHARS of lines, or XARGS_SCAN_MAX xargs of any kind it blocks (xargs-unread), fast; inside
            # them, many pipelines before one xargs stay fast; an xargs of a plain data command (XARGS_DATA) is not
            # counted (a script file listing 70 `xargs grep` rows blocked when every xargs counted)
            ('echo a | xargs sed s/a/b/; ' * 65, 2), ('echo ' + ' '.join('a%d' % i for i in range(600)) + ' | xargs python3', 2),
            ('echo a | xargs sed s/a/b/; ' * 64, 0), ('a | b; ' * 10000 + 'xargs grep x <<< y', 0),
            ('echo ' + ' '.join('a%d' % i for i in range(500)) + ' | xargs -n1 sed ' + 'x ' * 400, 2), ('(' * 5000 + 'xargs grep x' + ')' * 5000, 0),
            ('echo a | xargs grep x; ' * 200, 0), ('echo a | xargs /usr/bin/wc -l; ' * 100 + 'echo a | xargs sed s/a/b/; ' * 64, 0),
            ('echo a | xargs grep x; ' * 4097, 2),
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
        return fails, len(block) + len(allow) + 9 + 3 + len(timed) + 2 + 1 + len(too_many) + 2 + 2 + 3 + 2 + 2 + 1 + 1 + len(payload_redos) + 6 + corpus_n + 1 + 1 + 1


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


def prefilter_cases():
    """card 7ef651a9: a NeedRule (literal prefilter) answers like its plain pattern on every BLOCK and ALLOW command,
    their normalised, wrapper-bounded and quote-free texts, and case variants (re.I folds per character, the literal
    too)."""
    import importlib.util
    import re
    spec = importlib.util.spec_from_file_location('kc_gate_prefilter', HOOK)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    rules = [(n, r) for n, r in gate.RULES + gate.GIT_RULES if isinstance(r, gate.NeedRule)]
    fails, n = [], 0
    if len(rules) != 9:
        fails.append(f'prefilter: want 9 NeedRule rules, got {len(rules)}')
    # every regex rule of the lists is behind a literal (a new one without it is a slow rule again)
    plain_rx = [nm for nm, r in gate.RULES + gate.GIT_RULES if isinstance(r, re.Pattern)]
    if plain_rx:
        fails.append(f'prefilter: regex rules without a literal: {plain_rx}')
    sec = fix('s3curity')
    extra = [sec.upper() + ' dump-keychain', 'ſ' + sec[1:] + ' dump-keychain',
             sec.title() + ' -i', fix('git -c CR3DENTIAL.helper=OSXKEYCHAIN fetch'), 'git -c INCLUDE.PATH=/x fetch',
             'GIT_CONFIG_KEY_0=Include.Path git fetch', 'git --CONFIG-ENV=include.path=V fetch',
             fix('CR3DENTIAL FILL'), fix('git-cr3dential-OsxKeychain get'),
             # the literal far into a long text (a prefilter that read only a head of it passed these)
             'x' * 5000 + '; ' + sec + ' dump-keychain', 'a=b ' * 2000 + fix('git -c cr3dential.helper=osxkeychain x')]
    extra += [fix('GIT -C . CR3DENTIAL FILL'), fix('sudo -u a git -c x=y cr3dential Approve')]  # hits on the bounds only
    texts = []
    for cmd in list(map(fix, BLOCK + ALLOW)) + extra:
        t = gate.normalise(cmd)
        b = gate.wrapper_bounds(t, gate.WRAP_RX)  # the text hits_in() also judges, with the wrapped calls' bounds
        texts += [cmd, t, re.sub(r'[\'"\\]', '', t)] + ([b, re.sub(r'[\'"\\]', '', b)] if b and b != t else [])
    for name, r in rules:
        if not r.need.search(r.pattern):
            fails.append(f'prefilter {name}: the literal {r.need.pattern!r} is not in its own pattern')
        for t in texts:
            n += 1
            if bool(r.search(t)) != bool(r.rx.search(t)):
                fails.append(f'prefilter {name} ({r.need.pattern!r}) differs from its pattern on {t[:60]!r}')
    # the case variants are hits of a plain pattern (so the comparison above saw a prefilter on a hit)
    for cmd in extra:
        n += 1
        t = gate.normalise(cmd)
        if not any(r.rx.search(x) for _, r in rules for x in (t, gate.wrapper_bounds(t, gate.WRAP_RX) or t)):
            fails.append(f'prefilter: case variant is no hit of any rule: {cmd!r}')
    return fails, n


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
    # card 03a336e5: the hidden-name rule is linear. Its first form (one regex, a lazy scan to the word after every
    # head) took 2.3 s at 20 KB of `$($a ` and as long for glued backtick or quoted pieces, every start reading the same
    # long name again; 80 KB lines with the word behind a `;`, under 1 s each now
    # (on 9830a60b's gate the first three blocked on the watchdog at 6.2 s, the fourth took 2.1 s)
    hn_timed = [('$($a ' * 16000 + '; echo dump-keychain', 0), ('`$a` ' * 16000 + '; echo dump-keychain', 0),
                ('$a"x"' * 16000 + '; echo dump-keychain', 0), ('"$a dump-keychainx' * 4000 + '; echo dump-keychain', 0),
                ('`$a` ' * 16000 + '$a dump-keychain', 2),
                # (mutation round) a line is read once, not once per word in it: 4000 words, no name, 0.1 s; read per
                # word it took 93 s in process
                ('x $a; ' + 'echo dump-keychain; ' * 4000, 0)]
    import time as _t
    for cmd, want in hn_timed:
        try:
            t = _t.monotonic()
            p = subprocess.run([sys.executable, '-I', HOOK], capture_output=True, text=True, timeout=5,
                               input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}}),
                               env={'PATH': '/usr/bin:/bin'})
            took = _t.monotonic() - t
            if p.returncode != want or took > 2:
                fails.append(f'hidden-name timing case: want {want} under 2 s, got {p.returncode} in {took:.1f} s: '
                             f'{cmd[:40]!r}...')
        except subprocess.TimeoutExpired:
            fails.append(f'hidden-name timing case timed out (5 s): {cmd[:40]!r}...')
    # card e3d2fd6e r5 (Viktor 49996 R1): a backslash word in a data heredoc is judged against one reading of the
    # text, not a new one per word: 3 000 line-start `\\./dirN/x.sh` lines (~300 KB) ran into the 6 s watchdog on
    # 425f2206 (main 0.59 s); under 2 s each, allowed
    pad = ' ' + 'p' * 90
    esc_timed = ["cat <<'X'\n" + ''.join('\\./dir%d/x.sh%s\n' % (i, pad) for i in range(3000)) + 'X',
                 "python3 - <<'PY'\n" + ''.join('\\./dir%d/x.sh%s\n' % (i, pad) for i in range(3000)) + 'PY',
                 'cat > n.md <<X\n' + ''.join('./d%d\\.sh%s\n' % (i, pad) for i in range(3000)) + 'X']
    for cmd in esc_timed:
        try:
            t = _t.monotonic()
            p = subprocess.run([sys.executable, '-I', HOOK], capture_output=True, text=True, timeout=5,
                               input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}}),
                               env={'PATH': '/usr/bin:/bin'})
            took = _t.monotonic() - t
            if len(cmd) < 290000 or p.returncode != 0 or took > 2:
                fails.append(f'backslash-heredoc timing case: want 0 under 2 s at 290 KB+, got {p.returncode} in '
                             f'{took:.1f} s at {len(cmd)} chars: {cmd[:40]!r}...')
        except subprocess.TimeoutExpired:
            fails.append(f'backslash-heredoc timing case timed out (5 s): {cmd[:40]!r}...')
    # card d58d5c30: the made-subcommand rule is linear: the loop table is one pass (a call per match read the text
    # again each time), in process (the hook blocks such texts early on MAX_ARGS): 200-740 KB, 2 s cap each
    # (measured 11-20: 0.07 s at most)
    ms_timed = ('import importlib.util as u,sys,time; s=u.spec_from_file_location("g",sys.argv[1]); '
                'm=u.module_from_spec(s); s.loader.exec_module(m); N="secu"+"rity"; R=['
                '("for s in a b; do "+(N+" $s -h; ")*40000,0),((N+" $a; ")*40000,1),'
                '("".join("for v%d in x; do %s $v%d; "%(i,N,i) for i in range(20000)),0),'
                '((N+" x ")*60000+"; "+N+" $(y)",1),("`"*200000+N+" $x",1),((N+" ")*80000,0),'
                '("for s in a b; do "+("read q; "*30000)+N+" $s",0),'
                # r3: every call's backtick closes a span (a count from the start per call: 7.1 s at 1.15 MB; past
                # the lexer's bounds no backtick is real, so it blocks at the first), and an odd plain count before
                # the real opener over 1.1 MB of quoted backticks (the lexer reads it)
                '(("echo `"+N+" ` x ; ")*50000,1),("echo \\x27`\\x27; "*100001+N+" ` printf x`",1)]\n'
                'for c,w in R:\n t=time.monotonic(); g=m.made_subcommand(c); d=time.monotonic()-t\n'
                ' if bool(g)!=bool(w) or d>2: print(repr(c[:40]),bool(g),round(d,2))')
    p = subprocess.run([sys.executable, '-I', '-c', ms_timed, HOOK], capture_output=True, text=True, timeout=120,
                       env={'PATH': '/usr/bin:/bin'})
    if p.returncode != 0 or p.stdout.strip():
        fails.append(f'made-subcommand timing (in process): {p.stdout.strip()[:300]} {p.stderr.strip()[-300:]}')
    # card 04df07c5: the glob-subcommand rule is linear: each word is read up to its first blank (an unclosed group,
    # bracket or quote is not scanned to the text's end per call), and a group nested past 8 levels reads as any run
    # (no recursion depth): 0.3-2 MB, 2 s cap each, in process
    gs_timed = ('import importlib.util as u,sys,time; s=u.spec_from_file_location("g",sys.argv[1]); '
                'm=u.module_from_spec(s); s.loader.exec_module(m); N="secu"+"rity"; R=['
                '((N+" (a ")*60000,0),((N+" [a ")*60000,0),((N+" \x27a ")*60000,0),((N+" (#a ")*60000,0),'
                '(N+" x"+"("*1000000,1),(N+" "+"("*5000+"d"+")"*5000,1),(N+" "+"@("*3000+"a"+")"*3000,1),'
                '((N+" list-k* ")*80000,0),((N+" list-k*|")*80000,0),(N+" "+"?"*1000000,0),'
                '((N+" "+"*"*14+"x; ")*40000,0),((N+" "+"*?"*4+"x; ")*10000,0),((N+" "+"*?"*5+"x; ")*40000,1),'
                '((N+" x"+"#"*3000+"y; ")*100,0)]\n'
                'for c,w in R:\n t=time.monotonic(); g=m.glob_subcommand(c); d=time.monotonic()-t\n'
                ' if bool(g)!=bool(w) or d>2: print(repr(c[:40]),bool(g),round(d,2))')
    p = subprocess.run([sys.executable, '-I', '-c', gs_timed, HOOK], capture_output=True, text=True, timeout=120,
                       env={'PATH': '/usr/bin:/bin'})
    if p.returncode != 0 or p.stdout.strip():
        fails.append(f'glob-subcommand timing (in process): {p.stdout.strip()[:300]} {p.stderr.strip()[-300:]}')
    # card 8a73eab1: var_readings is a linear walk per nesting level, at most MAX_VAR_NEST + 1 levels (deeper:
    # TooManyArgs); 1-2 MB words, 2 s cap each. w: 1 = TooManyArgs expected, 0 = readings returned
    vr_timed = ('import importlib.util as u,sys,time; s=u.spec_from_file_location("g",sys.argv[1]); '
                'm=u.module_from_spec(s); s.loader.exec_module(m); R=['
                '("${A:-"*300000,0),("${A:-"*20+"x"+"}"*20,1),("${A}"*300000,0),("$A"*500000,0),'
                '("${A"+"x"*1000000,0),("${A:-"+"x"*1000000+"}",0),("${"*1000000,0),("${#A}"*200000,0),'
                '("${A:-${B}"*150000+"}"*150000,1),("${A"+"}x"*500000,0),("${A/"+"x"*1000000,0),'
                '("${A:-\\""*300000,0),("${A:-\\\\}"*300000,0),("$A:s/"*200000,0),("$A:h"*200000,0),'
                '("${A/#/"*200000,0),("${A:-\'"+"x"*1000000,0)]\n'
                'for c,w in R:\n t=time.monotonic()\n try:\n  m.var_readings(c); g=0\n except m.TooManyArgs:\n  g=1\n'
                ' d=time.monotonic()-t\n if g!=w or d>2: print(repr(c[:30]),g,round(d,2))')
    p = subprocess.run([sys.executable, '-I', '-c', vr_timed, HOOK], capture_output=True, text=True, timeout=120,
                       env={'PATH': '/usr/bin:/bin'})
    if p.returncode != 0 or p.stdout.strip():
        fails.append(f'var-readings timing (in process): {p.stdout.strip()[:300]} {p.stderr.strip()[-300:]}')
    # Kernel r2 (Viktor 49425): zsh's values of an empty or unset variable, measured in zsh 5.9 -f and with the
    # fleet's setopt; each must be one of var_readings' readings (after the quote removal), or TooManyArgs (None)
    vr_vals = ('import importlib.util as u,sys; s=u.spec_from_file_location("g",sys.argv[1]); '
               'm=u.module_from_spec(s); s.loader.exec_module(m); R=['
               '("ev$+X.py","ev0.py"),("ev$+X.py","ev1.py"),("ev$#X.py","ev0.py"),("ev${+X}il.py","ev1il.py"),'
               '("ev${+X}il.py","ev0il.py"),("ev${#X}il.py","ev0il.py"),("ev$X:h.py","ev..py"),'
               '("ev$X:h:t.py","ev..py"),("ev$X:s:a:b:.py","ev.py"),("ev$X:s/a/b.py","ev"),'
               '("ev${X:h}il.py","ev.il.py"),("ev${X/*/il}.py","evil.py"),'
               '("ev${X/a/il}.py","ev.py"),("ev${X:-i\\\\}l}.py","evi}l.py"),("ev${X:-i\'}\'l}.py","evi}l.py"),'
               '("ev${X:-i\\"}\\"l}.py","evi}l.py"),("ev$X:x.py","ev:x.py"),("ev$X[1].py","ev.py"),'
               '("ev$^X.py","ev.py"),("ev${^X}il.py","evil.py"),("ev$X:P.py",None),("ev${X:P}il.py",None),'
               '("ev${!HOM@}il.py","ev"+chr(0)+"il.py"),("evil${(L",None),'
               # Kernel r3 (Viktor 49502): the cut group and a NUL block; a subscript in a brace; the modifier chain
               '("ev"+chr(0)+"$X.py",None),("ev${X[1]:-il}.py","evil.py"),("ev${X[@]:-il}.py","evil.py"),'
               '("ev$X:h:a.py",None),("ev${X:h:A}il.py",None),("ev$X:s/a/b/:P.py",None),("ev$X:h:s/./il/.py","evil.py"),'
               '("ev$X:h:s/\\\\/x/il/.py","evil.py"),("ev$X:&il.py","evil.py"),("ev$X:h:&il.py",None),'
               '("ev${X:/*/il}.py","evil.py"),("ev$X:h:s/./i/:t.py",None)]\n'
               'for c,want in R:\n try:\n  got=[m.shell_unquote(r) for r in m.var_readings(c)]\n'
               ' except m.TooManyArgs:\n  got=None\n'
               ' if (want is None) != (got is None) or (want is not None and want not in got): print(c,want,got)')
    p = subprocess.run([sys.executable, '-I', '-c', vr_vals, HOOK], capture_output=True, text=True, timeout=60,
                       env={'PATH': '/usr/bin:/bin'})
    if p.returncode != 0 or p.stdout.strip():
        fails.append(f'var-readings zsh values (in process): {p.stdout.strip()[:300]} {p.stderr.strip()[-300:]}')
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
    # card 04d67b39: the fleet's GitHub path, which runs git's helper fill with the helper list reset (and names it in a
    # comment and a string), passes. Card 8d8298c7 (Viktor 50542 1, 5): named by its absolute path; the relative form
    # is judged by the script rules (script_git_cases)
    repo = os.path.dirname(os.path.dirname(os.path.dirname(HOOK)))
    if not os.path.isfile(os.path.join(repo, 'scripts', 'gh-pr.mjs')):
        fails.append('gh-pr.mjs not found next to the gate: the regression case did not run')
    else:
        code, err = bash_in('node ' + os.path.join(repo, 'scripts', 'gh-pr.mjs') + ' pr view 1', repo)
        if code != 0:
            fails.append(f'gh-pr.mjs should pass (got {code}): {err[:160]}')
    sg_fails, sg_n = script_git_cases()
    fails += sg_fails
    script_fails, script_n = script_cases()
    fails += script_fails
    pre_fails, pre_n = prefilter_cases()
    fails += pre_fails
    # Viktor 49925 M1 (card 0196e1ee): an invalid escape in the gate's text (`\\*` in its docstring) is a SyntaxWarning
    # on python 3.12+ and a SyntaxError under -W error / PYTHONWARNINGS=error; the hook then exits 1, which Claude Code
    # takes as a non-blocking error: the call goes through. The gate must compile with every warning an error.
    # The file is read and closed first: an unclosed one is a ResourceWarning on stderr AFTER the "N/N passed" line.
    import warnings
    with open(HOOK, encoding='utf-8') as f:
        hook_src = f.read()
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        try:
            compile(hook_src, HOOK, 'exec')
        except SyntaxError as e:
            fails.append(f'the gate does not compile with warnings as errors: line {e.lineno}: {e.msg}')
    total = len(BLOCK) + len(ALLOW) + 1 + 6 + 11 + len(hn_timed) + len(wrap_timed) + 1 + script_n + pre_n + 1 + sg_n
    for f in fails:
        print('FAIL', f)
    print(f'{total - len(fails)}/{total} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
