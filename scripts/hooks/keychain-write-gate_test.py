#!/usr/bin/env python3
"""Tests for keychain-write-gate.py (card 759161e3, Viktor 48285).

Runs the hook as Claude Code does (JSON on stdin; exit 0 allow, 2 block), plus the deny log and the allow list through
the module with its state paths pointed at a temp directory. Hermetic: no keychain call, no network; the commands are
only text. KC is a real temp file (a throwaway keychain stands there in real use); NOKC a path that does not exist.
Run: python3 -I scripts/hooks/keychain-write-gate_test.py
"""
import atexit
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'keychain-write-gate.py')
TMP = tempfile.mkdtemp(prefix='kc-write-gate-test-')
atexit.register(shutil.rmtree, TMP, True)
KC = os.path.join(TMP, 'throwaway.keychain-db')
with open(KC, 'w') as f:
    f.write('x')
KC2 = os.path.join(TMP, 'second.keychain-db')
with open(KC2, 'w') as f:
    f.write('x')
NOKC = os.path.join(TMP, 'missing.keychain-db')
NEWKC = os.path.join(TMP, 'new.keychain-db')
LOGIN = os.path.expanduser('~/Library/Keychains/login.keychain-db')


# The fixtures spell the binary "s3curity"; fix() restores it at run time, so this file carries no runnable keychain
# call (the keychain-read-gate convention, card bc009036).
def fix(cmd):
    return (cmd.replace('s3c', 'sec').replace('S3C', 'SEC').replace('{KC}', KC).replace('{KC2}', KC2)
            .replace('{NOKC}', NOKC).replace('{NEWKC}', NEWKC).replace('{LOGIN}', LOGIN).replace('{DIR}', TMP))


BLOCK = [
    # the 2026-11-13 / 2026-11-20 class: a relative or missing keychain name falls back to the login keychain
    's3curity add-generic-password -U -s "Claude Code-credentials-1a2b3c4d" -a a@example.test -w x t.keychain-db',
    's3curity add-generic-password -a x -s y -w z',
    's3curity add-generic-password -a x -s y -w z {NOKC}',
    's3curity add-generic-password -a x -s y -w z ./t.keychain-db',
    's3curity add-generic-password -a x -s y -w z "$KC"',
    's3curity add-generic-password -a x -s y -w z {LOGIN}',
    's3curity add-generic-password -a x -s y -w z ~/Library/Keychains/login.keychain-db',
    's3curity add-generic-password -a x -s y -w z /Library/Keychains/System.keychain',
    # the last word is an option's argument, not a keychain (Viktor's own gate passed these, Kernel 48296)
    's3curity add-generic-password -a x -s y -w z -T /usr/bin/true',
    's3curity add-generic-password -a x -s y -w z -j {KC}',
    's3curity add-generic-password -a x -s y -l {KC}',
    's3curity add-generic-password -a x -s y -w{KC}',
    's3curity add-generic-password -a x -s y -w {KC}',
    's3curity add-generic-password -a x -s y -w',
    's3curity add-internet-password -a x -s example.test -w z -P 443',
    's3curity add-internet-password -a x -s example.test -w z -p {KC}',
    # every keychain operand must be fine, not only the last one
    's3curity delete-generic-password -s y t.keychain-db {KC}',
    's3curity delete-generic-password -s y',
    's3curity delete-generic-password -a x -s "Claude Code-credentials"',
    's3curity delete-internet-password -s example.test',
    's3curity delete-certificate -c name',
    's3curity delete-identity -Z abcd',
    's3curity delete-keychain login.keychain-db',
    's3curity delete-keychain {LOGIN}',
    's3curity delete-keychain',
    's3curity set-generic-password-partition-list -S apple-tool: -s y -k pw',
    's3curity set-key-partition-list -S apple: -k pw',
    's3curity set-identity-preference -c name -s example.test',
    's3curity set-keychain-password -o a -p b',
    's3curity set-keychain-settings -t 3600',
    's3curity create-keychain -p pw t.keychain-db',
    's3curity create-keychain -p pw ~/Library/Keychains/x.keychain-db',
    's3curity create-keychain',
    's3curity import /tmp/x.p12',
    's3curity import /tmp/x.p12 -k login.keychain-db',
    's3curity import /tmp/x.p12 -P pw -T /usr/bin/true',
    's3curity add-certificates /tmp/x.pem',
    's3curity add-certificates -k t.keychain-db /tmp/x.pem',
    's3curity add-trusted-cert -d -r trustRoot -k {KC} /tmp/x.pem',
    's3curity remove-trusted-cert /tmp/x.pem',
    's3curity default-keychain -s {KC}',
    's3curity login-keychain -s {KC}',
    's3curity list-keychains -d user -s {KC}',
    # command position: wrappers, paths, case, separators, substitutions, nested shells
    '/usr/bin/s3curity add-generic-password -a x -s y -w z t.kc',
    'S3CURITY add-generic-password -a x -s y -w z t.kc',
    's3curity -q add-generic-password -a x -s y -w z t.kc',
    'env -u HOME FOO=1 s3curity add-generic-password -a x -s y -w z t.kc',
    'sudo -u root s3curity delete-generic-password -s y',
    'timeout 5 s3curity delete-generic-password -s y',
    'nice -n 5 s3curity delete-generic-password -s y',
    'FOO=1 s3curity delete-generic-password -s y',
    'cd {KC2}; s3curity delete-generic-password -s y',
    'true && s3curity delete-generic-password -s y',
    'false || s3curity delete-generic-password -s y',
    'echo x | s3curity delete-generic-password -s y',
    'x=$(s3curity delete-generic-password -s y)',
    'x=`s3curity delete-generic-password -s y`',
    '( s3curity delete-generic-password -s y )',
    'if true; then s3curity delete-generic-password -s y; fi',
    'bash -c "s3curity delete-generic-password -s y"',
    "zsh -c 's3curity add-generic-password -a x -s y -w z t.kc'",
    'ls\ns3curity delete-generic-password -s y',
    's3cur\\\nity delete-generic-password -s y',
    "s'ec'urity delete-generic-password -s y",
    's3curity "delete-generic-password" -s y',
    's3curity delete-generic-p\\assword -s y',
    's3curity delete-generic-password -s y 2>/dev/null',
    's3curity add-generic-password -a x -s y -w z t.kc >/dev/null 2>&1',
    # variables: only what the same text set literally (and HOME, ~) is resolved
    'for d in /tmp/a; do s3curity delete-keychain "$d/x.keychain-db"; done',
    'KC=t.keychain-db; s3curity add-generic-password -a x -s y -w z "$KC"',
    'KC={KC}; unset KC; s3curity add-generic-password -a x -s y -w z "$OTHER"',
    's3curity add-generic-password -a x -s y -w z $(echo {KC})',
    's3curity add-generic-password -a x -s y -w z $HOME/Library/Keychains/login.keychain-db',
    's3curity add-generic-password -a x -s y -w z ${HOME}/Library/Keychains/login.keychain-db',
    # text a shell runs is read again
    'bash -lc "s3curity delete-generic-password -s y"',
    'sudo sh -c "s3curity delete-generic-password -s y"',
    'bash -o pipefail -c "s3curity delete-generic-password -s y"',
    'eval s3curity delete-generic-password -s y',
    "bash <<'EOF'\ns3curity delete-generic-password -s y\nEOF",
    "cat <<'EOF' | sh\necho hi\ns3curity delete-generic-password -s y\nEOF",
    "zsh <<-EOF\n\ts3curity delete-generic-password -s y\n\tEOF\necho after",
    # fail-closed: an open quote with a write subcommand word in the text
    's3curity add-generic-password -a "x -s y t.kc',
    # Viktor 48329 H: a -h that is another option's value is no usage request; security(1) writes
    's3curity add-generic-password -a -h -s y -w z t.kc',
    's3curity add-generic-password -a x -s y -w -h',
    's3curity add-generic-password -a x -s y -j -h -w z',
    's3curity delete-generic-password -s -h',
    's3curity add-trusted-cert -k -h /tmp/c.pem',
    # Q: a substitution inside double quotes runs
    'out="$(s3curity delete-generic-password -s y)"',
    'echo "`s3curity delete-generic-password -s y`"',
    'echo "a $(true; s3curity delete-generic-password -s y) b"',
    # S: a shell that reads its commands from stdin runs the echo / printf / cat text and a here-string
    "echo 's3curity delete-generic-password -s y' | bash",
    "printf 's3curity delete-generic-password -s y' | sh",
    "bash <<< 's3curity delete-generic-password -s y'",
    "echo 's3curity delete-generic-password -s y' | bash -s",
    "echo 's3curity delete-generic-password -s y' | sudo zsh",
    # SUB: the subcommands the first head missed
    's3curity create-keypair -a rsa -s 2048 name',
    's3curity create-keypair -k t.keychain-db name',
    's3curity trust-settings-import /tmp/t.plist',
    's3curity user-trust-settings-enable -d',
    's3curity create-filevaultmaster-keychain -p pw t.keychain-db',
    's3curity create-filevaultmaster-keychain -p pw ~/Library/Keychains/fv.keychain',
    # V: unset forgets the value; "$KC" is then unknown
    'KC={KC}; unset KC; s3curity delete-generic-password -s y "$KC"',
    'KC={KC}; unset -v KC; s3curity delete-generic-password -s y "$KC"',
    # the mutation round (Viktor 48329): each a form the head decides right, pinned
    's3curity set-internet-password-partition-list -S x: -s example.test -k pw',  # T1
    's3curity -p xx delete-generic-password -s y',  # T6: the tool's -p takes a word
    's3curity create-keychain -p pw {NEWKC} t.keychain-db',  # T8: the second operand too
    's3curity delete-generic-password -s y {DIR}',  # K4: a directory is no keychain file
    'KC={KC}; KC=$OTHER; s3curity delete-generic-password -s y "$KC"',  # K6: unresolvable reassignment
    'xargs -n 1 s3curity delete-generic-password -s y',  # W1
    'exec s3curity delete-generic-password -s y',  # W2
    '2>/dev/null s3curity delete-generic-password -s y',  # W3: a leading redirection and its target
    '> /tmp/o s3curity delete-generic-password -s y',
    'x#; s3curity delete-generic-password -s y',  # S1: a # inside a word is no comment
    "cat <<-EOF\n\tdata\n\tEOF\ns3curity delete-generic-password -s y",  # S2: the <<- body ends at the tab line
    'bash -c "sh -c \'s3curity delete-generic-password -s y\'"',  # S3: two levels
    'bash -c "sh -c \'eval s3curity delete-generic-password -s y\'"',
    "ksh -c 's3curity delete-generic-password -s y'",  # S5
    # card c6b9ff2f (Viktor 48557 INFO 3): an escaped backslash before a closing double quote ends the string; the
    # old scan ran on to the next quote, and inside bash -c the text was Unsplittable (a pass at depth > 0)
    "bash -c 'echo \"a\\\\\" ; s3curity add-generic-password -a x -s y -w z ; echo \"b\"'",
    "sh -c 'printf \"%s\\\\\" x && s3curity delete-generic-password -s y && echo \"b\"'",
    'echo "a\\\\" ; s3curity delete-generic-password -s y ; echo "b"',
    'echo "q\\"\\\\" ; s3curity delete-generic-password -s y',  # an escaped quote, then an escaped backslash
]

ALLOW = [
    # card c6b9ff2f: a string ending in an escaped backslash is closed where bash closes it; text in it is data
    'echo "C:\\\\" ; echo "s3curity add-generic-password is the write subcommand"',
    "bash -c 'echo \"dir\\\\\" ; ls'",
    # the throwaway keychain, named by an absolute path to an existing file outside the keychain directories
    's3curity add-generic-password -U -a x -s y -w z {KC}',
    's3curity add-generic-password -a x -s y -w z -T /usr/bin/true {KC}',
    's3curity add-generic-password -a x -s y -X 616263 -A {KC}',
    's3curity add-internet-password -a x -s example.test -w z -P 443 {KC}',
    's3curity delete-generic-password -s y {KC} {KC2}',
    's3curity delete-generic-password -s y -- {KC}',
    's3curity delete-keychain {KC}',
    's3curity set-generic-password-partition-list -S apple-tool: -s y -k pw {KC}',
    's3curity set-keychain-settings -lu -t 3600 {KC}',
    's3curity create-keychain -p pw {NEWKC}',
    's3curity import /tmp/x.p12 -k {KC} -P pw -T /usr/bin/true',
    's3curity add-certificates -k {KC} /tmp/x.pem',
    's3curity add-generic-password -a x -s y -w z {KC} 2>&1 | tail -1',
    's3curity add-generic-password -a x -s y -w z {KC} >/dev/null',
    'env FOO=1 s3curity delete-generic-password -s y {KC}',
    'bash -c "s3curity delete-generic-password -s y {KC}"',
    'KC={KC}; s3curity add-generic-password -a x -s y -w z "$KC"',
    'export KCPATH={KC} && s3curity delete-generic-password -s y ${KCPATH}',
    'D={KC2}; KC=$D; s3curity delete-keychain "$KC"',
    # a subcommand's usage text writes nothing (the 14-day replay, Kernel 11-20 00:02)
    's3curity add-generic-password -h 2>&1 | head -40',
    's3curity delete-keychain -h',
    # reading, listing, locking: not writes
    's3curity list-keychains',
    's3curity list-keychains -d user',
    's3curity default-keychain',
    's3curity login-keychain -d user',
    's3curity show-keychain-info {KC}',
    's3curity unlock-keychain -p pw {KC}',
    's3curity lock-keychain -a',
    's3curity find-certificate -a -c name',
    's3curity verify-cert -c /tmp/x.pem',
    # the word in plain text, not in command position
    'grep add-generic-password notes.md',
    'echo s3curity delete-generic-password',
    'git log --oneline -1 # s3curity delete-generic-password -s y',
    # the 14-day replay's false denies (card 759161e3): quoted text and a here-document body are data
    'grep -rn -iE "vault (set|add|put)|s3curity add-generic-password" scripts/x.mjs scripts/y.sh 2>/dev/null | head -5',
    "python3 - <<'EOF'\ns = 'a fix in Mastra\\'s changelog'\nprint('s3curity add-generic-password')\nEOF",
    "cat > notes.md <<'EOF'\ns3curity delete-generic-password -s y\nEOF\necho done",
    'git commit -m "docs: s3curity add-generic-password needs an absolute keychain path"',
    "python3 - <<'PY'\nx = \"it's\ny = 's3curity delete-generic-password'\nPY",
    'bash -c "echo ok" && grep "s3curity delete-generic-password" f',
    'python3 -c "import json"',
    'ls -la',
    '',
    # Viktor 48329 H: a usage request in a cluster is one (it was a false deny on the first head)
    's3curity add-generic-password -Uh',
    's3curity delete-generic-password -h -s y',
    # Q, S: data stays data; a stdin shell with a throwaway keychain passes
    'echo "built $(date)" && git commit -m "s3curity delete-generic-password docs"',
    "echo 's3curity delete-generic-password -s y' | grep delete",
    "echo 's3curity delete-generic-password -s y {KC}' | bash",
    "bash <<< 's3curity delete-generic-password -s y {KC}'",
    "echo 's3curity delete-generic-password -s y' > notes.md; bash build.sh",
    # SUB with a throwaway keychain
    's3curity create-keypair -a rsa -k {KC} name',
    's3curity create-filevaultmaster-keychain -p pw {NEWKC}',
    # the mutation round (Viktor 48329): option values the tables must read as values
    's3curity delete-generic-password -G gen -s y {KC}',  # T3
    's3curity add-internet-password -a x -s example.test -r http -w z {KC}',  # T4
    's3curity delete-generic-password -sy {KC}',  # G1: a value glued to its letter
    's3curity add-generic-password -Uw z -a x -s y {KC}',  # G2: a valued letter late in a cluster
    'KC={KC}; unset OTHER; s3curity delete-generic-password -s y "$KC"',
]


def run(cmd, tool='Bash'):
    payload = json.dumps({'tool_name': tool, 'tool_input': {'command': cmd}})
    p = subprocess.run([sys.executable, '-I', HOOK], input=payload, capture_output=True, text=True, timeout=20)
    return p.returncode, p.stderr


def load():
    spec = importlib.util.spec_from_file_location('kc_write_gate', HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    fails = 0
    mod = load()
    for raw in BLOCK:
        cmd = fix(raw)
        hit = mod.judge(cmd)
        if not hit:
            print(f'FAIL: block expected: {raw!r}')
            fails += 1
    for raw in ALLOW:
        cmd = fix(raw)
        hit = mod.judge(cmd)
        if hit:
            print(f'FAIL: allow expected: {raw!r} -> {hit}')
            fails += 1
    # the reason names what is wrong: $HOME and ~ are resolved, so these are "under" the keychain directory
    for raw in ('s3curity add-generic-password -a x -s y -w z $HOME/Library/Keychains/login.keychain-db',
                's3curity add-generic-password -a x -s y -w z ~/Library/Keychains/login.keychain-db'):
        hit = mod.judge(fix(raw))
        if not hit or 'is under' not in hit[1]:
            print(f'FAIL: reason "is under" expected: {raw!r} -> {hit}')
            fails += 1
    extra = 0

    # Viktor 48329 P and K2, hermetic: a keychain directory of our own (FAKE) stands in for ~/Library/Keychains
    fake = os.path.join(TMP, 'FakeKeychains')
    os.makedirs(fake)
    inside = os.path.join(fake, 'a.keychain-db')
    with open(inside, 'w') as f:
        f.write('x')
    file_link = os.path.join(TMP, 'kc-link.keychain-db')  # a symlink to a file in it: realpath finds the directory
    os.symlink(inside, file_link)
    saved = mod.KEYCHAIN_DIRS, mod.KEYCHAIN_DIR_IDS
    cases = [
        # by inode only: the directory's path string is not in KEYCHAIN_DIRS (another name for it)
        (((), mod._dir_ids([fake])), inside, 'another name'),
        # by path after realpath only (no inode set): the symlinked file is under the directory
        (((os.path.realpath(fake),), set()), file_link, 'is under'),
        # neither: a file elsewhere passes
        (((os.path.realpath(fake),), mod._dir_ids([fake])), KC, None),
    ]
    try:
        for (dirs, ids), path, want in cases:
            mod.KEYCHAIN_DIRS, mod.KEYCHAIN_DIR_IDS = dirs, ids
            hit = mod.judge(fix('s3curity delete-generic-password -s y ') + path)
            extra += 1
            if (want is None and hit) or (want is not None and (not hit or want not in hit[1])):
                print(f'FAIL: keychain directory case {path!r} (dirs {dirs}, ids {len(ids)}): want {want!r}, got {hit}')
                fails += 1
    finally:
        mod.KEYCHAIN_DIRS, mod.KEYCHAIN_DIR_IDS = saved
    # the real other names, where this machine has them (macOS firmlink and a case-insensitive volume)
    real_kc = os.path.expanduser('~/Library/Keychains')
    if os.path.isdir(real_kc) and os.path.isdir('/System/Volumes/Data' + real_kc):
        for other in ('/System/Volumes/Data' + real_kc, real_kc.lower()):
            if not os.path.isdir(other):
                continue
            hit = mod.judge(fix('s3curity delete-generic-password -s y ') + other + '/login.keychain-db')
            extra += 1
            if not hit or 'keychain directory' not in hit[1] and 'is under' not in hit[1]:
                print(f'FAIL: another name of the keychain directory must block: {other!r} -> {hit}')
                fails += 1

    # through the hook process, as Claude Code runs it (state written under a temp root via the module below)
    rc, err = run(fix('s3curity list-keychains'))
    if rc != 0:
        print(f'FAIL: hook allow rc={rc} {err}')
        fails += 1
    rc, err = run(fix('s3curity add-generic-password -a x -s y -w SECRETPW t.kc'), tool='Write')
    if rc != 0:
        print(f'FAIL: non-Bash tool must pass, rc={rc}')
        fails += 1
    rc, _ = run('not json')
    if rc != 0:
        print(f'FAIL: unreadable stdin JSON must pass like the sibling gates, rc={rc}')
        fails += 1
    # fail-closed (Viktor 48329 F1): an error inside the gate blocks; a lone surrogate cannot be encoded for the hash
    payload = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': fix('s3curity delete-generic-password -s y ')
                                                                          + '\ud800'}})
    p = subprocess.run([sys.executable, '-I', HOOK], input=payload, capture_output=True, text=True, timeout=20)
    if p.returncode != 2 or 'KEYCHAIN-WRITE-GATE error' not in p.stderr:
        print(f'FAIL: an exception in the gate must block (exit 2), rc={p.returncode} {p.stderr[-120:]!r}')
        fails += 1

    # deny log and allow list through the module, with the state under TMP
    state = os.path.join(TMP, 'state')
    mod.STATE, mod.ALLOW, mod.DENY_LOG = state, os.path.join(state, 'allow.txt'), os.path.join(state, 'deny.log')
    cmd = fix('s3curity add-generic-password -a x -s y -w SECRETPW t.kc')
    digest = hashlib.sha256(cmd.encode()).hexdigest()

    def call(c):
        old_in, old_err = sys.stdin, sys.stderr
        sys.stdin, sys.stderr = io.StringIO(json.dumps({'tool_name': 'Bash', 'tool_input': {'command': c}})), io.StringIO()
        try:
            return mod.main(), sys.stderr.getvalue()
        finally:
            sys.stdin, sys.stderr = old_in, old_err

    rc, err = call(cmd)
    if rc != 2 or digest not in err or 'SECRETPW' in err:
        print(f'FAIL: deny message: rc={rc} {err!r}')
        fails += 1
    with open(mod.DENY_LOG) as f:
        log = f.read()
    if digest not in log or 'SECRETPW' in log or '"sub": "add-generic-password"' not in log:
        print(f'FAIL: deny log: {log!r}')
        fails += 1
    if os.stat(mod.DENY_LOG).st_mode & 0o077:
        print('FAIL: deny log not owner-only')
        fails += 1
    with open(mod.ALLOW, 'w') as f:
        f.write('# Klodel OK, test\n' + digest + '\n')
    rc, _ = call(cmd)
    if rc != 0:
        print(f'FAIL: allow-listed sha256 must pass, rc={rc}')
        fails += 1
    rc, _ = call(cmd + ' ')
    if rc != 2:
        print(f'FAIL: another text (one more blank) must not ride on the allow line, rc={rc}')
        fails += 1

    # the subprocess deny path end to end: exit 2 and the reason on stderr (the log goes to the repo's store/)
    rc, err = run(fix('s3curity delete-generic-password -s y'))
    if rc != 2 or 'KEYCHAIN-WRITE-GATE' not in err:
        print(f'FAIL: hook block rc={rc} {err}')
        fails += 1

    total = len(BLOCK) + len(ALLOW) + 12 + extra
    print(f'{total - fails}/{total} ok' if not fails else f'{fails} FAIL of {total}')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
