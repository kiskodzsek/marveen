#!/usr/bin/env python3
"""PreToolUse gate (Bash): an agent shell does not write or delete in the LOGIN keychain by accident with `security`.

Why (card 759161e3, Viktor 48285; hibanapló 2026-11-13 21:36 Kernel and 2026-11-20 01:00 Viktor, the same class twice):
`security add-generic-password ... t.keychain-db` got a RELATIVE keychain name, security(1) did not find it and
wrote the item into the default (login) keychain: rc 0, no message. A missing keychain argument does the same. The
exit code and the silence are no proof of where an item went.

An ACCIDENT guard, not a boundary: every agent runs as the same macOS user. NOT MODELLED (passes unseen): a keychain
write through an API (Swift, Python, a Node execFile such as the dashboard's own src/web/keychain.ts), a script
file's content, a command name or a keychain path hidden in a variable or built by the shell beyond `~`, and
the tool's interactive mode, which reads subcommands from stdin (keychain-read-gate.py blocks it), and a command a
program other than a shell runs (`script -q /dev/null security ...`, `find -exec security ...`, `env -S "..."`).

What blocks (exit 2), for a `security` call in command position (the start of a simple command, after ; & | ( ) a
newline, `$(`, a backtick, after the wrapper words env, sudo, exec, command, nohup, time, nice, timeout, xargs ...,
and in text a shell runs: `bash|sh|zsh|dash|ksh -c STRING`, `eval WORDS`, a `$( )` or backtick inside double
quotes, a here-document or here-string on a line where such a shell runs, and the echo/printf/cat text of a text
where a shell reads stdin (`echo '...' | bash`); any other here-document body or quoted text is data, so
`grep "security add-..."` or a doc written with `cat > f <<EOF` passes; measured in the 14-day replay, card
759161e3). `unset NAME` forgets a variable the text set (a later "$NAME" cannot be resolved and blocks):
- the keychain-at-the-end subcommands (POSITIONAL): after the options, parsed per subcommand with the option table
  of its own `security <sub> -h` (measured 2026-11-20, macOS 27.0.1), at least one keychain argument, and every one
  an absolute path to an existing regular file that is not under ~/Library/Keychains or /Library/Keychains, by
  path after realpath or by device and inode of the file's directories (another name of the same directory:
  /System/Volumes/Data/Users/..., another letter case; Viktor 48329 P); `add-*-password -w` as the last option
  (the password prompt) takes no argument. The last word alone is no keychain: `-T /usr/bin/true` at the end is
  an option's argument (Viktor's own gate passed it, Kernel 48296).
- create-keychain, create-filevaultmaster-keychain: every keychain an absolute path outside those directories (it
  does not exist yet).
- import, add-certificates, create-keypair: `-k <keychain>` required, with the POSITIONAL condition.
- always: add-trusted-cert, remove-trusted-cert, trust-settings-import, user-trust-settings-enable (user trust
  settings, no keychain argument makes them local), and default-keychain / login-keychain / list-keychains with
  -s (they move later writes to another keychain).
- a command that cannot be split (an open quote) while a write subcommand word is in it (fail-closed).
A subcommand's usage text passes: a `-h` the subcommand's own option table reads as an option (`-Uh` too), not as
another option's value (`-a -h` writes; Viktor 48329 H).
Passes: every other subcommand (find-*, list-keychains without -s, show-keychain-info, unlock-keychain ...), and a
command whose exact text's sha256 is a line of store/keychain-write-gate/allow.txt (a deliberate login-keychain
write, with Klodel's OK). Denies go to store/keychain-write-gate/deny.log as sha256 + subcommand + reason, never the
command text (it may hold a -w password).
"""
import hashlib
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
STATE = os.path.join(ROOT, 'store', 'keychain-write-gate')
ALLOW = os.path.join(STATE, 'allow.txt')
DENY_LOG = os.path.join(STATE, 'deny.log')
KEYCHAIN_DIRS = tuple(os.path.realpath(p) for p in (os.path.expanduser('~/Library/Keychains'), '/Library/Keychains'))

# Option letters that take an argument, per subcommand (`security <sub> -h`, macOS 27.0.1, 2026-11-20).
ITEM_ADD = set('acCDGjlswpXT')            # add-generic-password (-A -U take none)
INET_ADD = set('acCdDjlpPrstwXT')         # add-internet-password
GEN_MATCH = set('acCDGjls')               # delete-generic-password
INET_MATCH = set('acCdDjlpPrst')          # delete-internet-password
POSITIONAL = {
    'add-generic-password': ITEM_ADD,
    'add-internet-password': INET_ADD,
    'delete-generic-password': GEN_MATCH,
    'delete-internet-password': INET_MATCH,
    'delete-certificate': set('cZ'),
    'delete-identity': set('cZ'),
    'delete-keychain': set(),
    'set-generic-password-partition-list': GEN_MATCH | set('Sk'),
    'set-internet-password-partition-list': INET_MATCH | set('Sk'),
    'set-key-partition-list': set('acDjltSk'),
    'set-identity-preference': set('csuZ'),
    'set-keychain-password': set('op'),
    'set-keychain-settings': set('t'),
}
PROMPT_W = {'add-generic-password', 'add-internet-password'}
CREATE = {'create-keychain': set('p'), 'create-filevaultmaster-keychain': set('ps')}
K_OPTION = {'import': set('ktfPaT'), 'add-certificates': set('k'), 'create-keypair': set('asftdkT')}
ALWAYS = {'add-trusted-cert': set('rpaseukio'), 'remove-trusted-cert': set(), 'trust-settings-import': set(),
          'user-trust-settings-enable': set()}
SEARCH_SET = {'default-keychain', 'login-keychain', 'list-keychains'}
WRITE_WORDS = set(POSITIONAL) | set(CREATE) | set(K_OPTION) | set(ALWAYS) | SEARCH_SET
SECURITY_GLOBAL_ARG = set('p')            # the tool's own options before the subcommand: only its prompt option takes a word
WRAPPERS = {'env', 'sudo', 'doas', 'exec', 'command', 'builtin', 'nohup', 'time', 'nice', 'caffeinate', 'xargs',
            'timeout', 'stdbuf', 'setsid', 'arch', '!', 'if', 'then', 'else', 'elif', 'do', 'while', 'until', '{'}
WRAPPER_ARG = {'sudo': set('ugCDhpRrTU'), 'env': set('uSPC'), 'nice': set('n'), 'timeout': set('sk'),
               'arch': set(), 'exec': set('a'), 'xargs': set('IJLnPRsSE'), 'caffeinate': set('tw'),
               'stdbuf': set('ioe')}


def _dir_ids(paths):
    ids = set()
    for p in paths:
        try:
            st = os.stat(p)
        except OSError:
            continue
        ids.add((st.st_dev, st.st_ino))
    return ids


KEYCHAIN_DIR_IDS = _dir_ids(KEYCHAIN_DIRS)


def under_keychain_dir(real):
    """True if real or an existing ancestor of it IS a keychain directory by device and inode: the realpath of
    /System/Volumes/Data/Users/... or of another letter case is not the string in KEYCHAIN_DIRS."""
    p = real
    while True:
        try:
            st = os.stat(p)
            if (st.st_dev, st.st_ino) in KEYCHAIN_DIR_IDS:
                return True
        except OSError:
            pass
        parent = os.path.dirname(p)
        if parent == p:
            return False
        p = parent


BOUNDARY = (';', '&', '|', '(', ')', '`')
SHELLS = {'bash', 'sh', 'zsh', 'dash', 'ksh'}
ASSIGN_RX = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')
ASSIGN_WORDS = set('export readonly'.split())


class Unsplittable(Exception):
    pass


def split_commands(text, subs=None):
    """(cmds, heredocs): cmds the simple commands of a shell text as word lists, quotes removed; heredocs a list of
    (body, first, last), a here-document body and the index range in cmds of the commands on the line that opened
    it. A body is data, never split as shell here (judge reads it again only when a shell runs it). Raises
    Unsplittable on an open quote outside a body."""
    cmds, words, heredocs = [], [], []
    cur, in_word = [], False
    line_start = 0
    i, n = 0, len(text)

    def end_word():
        nonlocal cur, in_word
        if in_word:
            words.append(''.join(cur))
        cur, in_word = [], False

    def end_cmd():
        nonlocal words
        end_word()
        if words:
            cmds.append(words)
        words = []

    def read_bodies(i):
        """At the start of the line after one that opened here-documents: consume their bodies in order."""
        nonlocal line_start
        for words_ in cmds[line_start:]:
            for k, w in enumerate(words_[:-1]):
                if w != '<<':
                    continue
                delim = words_[k + 1]
                strip = delim.startswith('-')
                if strip:
                    delim = delim[1:]
                body = []
                while i < n:
                    e = text.find('\n', i)
                    e = n if e == -1 else e
                    line = text[i:e]
                    i = e + 1
                    if (line.lstrip('\t') if strip else line) == delim:
                        break
                    body.append(line)
                heredocs.append(('\n'.join(body), line_start, len(cmds)))
        line_start = len(cmds)
        return i

    while i < n:
        c = text[i]
        if c == '\\' and i + 1 < n:
            if text[i + 1] == '\n':
                i += 2
                continue
            cur.append(text[i + 1])
            in_word = True
            i += 2
            continue
        if c == "'":
            j = text.find(c, i + 1)
            if j == -1:
                raise Unsplittable()
            cur.append(text[i + 1:j])
            in_word = True
            i = j + 1
            continue
        if c == '"':
            # Bash's rule: inside double quotes a backslash escapes only " \ $ ` and a newline. The old scan took
            # every quote after a backslash for an escaped one, so `"dir\\"` (an escaped backslash, then the closing
            # quote) ran on to the next quote; inside `bash -c '...'` the text was then Unsplittable, which passes at
            # depth > 0, and the command after it went unjudged (card c6b9ff2f, Viktor 48557 INFO 3).
            j, buf = i + 1, []
            while j < n and text[j] != '"':
                if text[j] == '\\' and j + 1 < n:
                    nxt = text[j + 1]
                    if nxt in '"\\$`':
                        buf.append(nxt)
                    elif nxt != '\n':
                        buf.append('\\' + nxt)
                    j += 2
                    continue
                buf.append(text[j])
                j += 1
            if j >= n:
                raise Unsplittable()
            part = ''.join(buf)
            if subs is not None:
                subs.extend(dquote_substitutions(text[i + 1:j].replace('\\"', '"')))
            cur.append(part)
            in_word = True
            i = j + 1
            continue
        if c == '$' and i + 1 < n and text[i + 1] == '(':
            end_cmd()
            i += 2
            continue
        if c == '#' and not in_word:
            j = text.find('\n', i)
            i = n if j == -1 else j
            continue
        if c == '\n':
            end_cmd()
            i = read_bodies(i + 1)
            continue
        if c in BOUNDARY:
            end_cmd()
            i += 1
            continue
        if c in (' ', '\t'):
            end_word()
            i += 1
            continue
        if c in '<>':
            # A redirection: a file-descriptor number right before it belongs to it (`2>&1`), not to the command;
            # the operator stays a word, and strip_redirections drops it with its target.
            if in_word and ''.join(cur).isdigit():
                cur, in_word = [], False
            end_word()
            j = i
            while j < n and text[j] in '<>&':
                j += 1
            words.append(text[i:j])
            i = j
            continue
        cur.append(c)
        in_word = True
        i += 1
    end_cmd()
    read_bodies(n)
    return cmds, heredocs


def dquote_substitutions(part):
    """The command texts of $( ) and backtick substitutions inside a double-quoted part: the shell runs them."""
    out, k = [], 0
    while k < len(part):
        if part.startswith('$(', k):
            depth, m = 1, k + 2
            while m < len(part) and depth:
                depth += {'(': 1, ')': -1}.get(part[m], 0)
                m += 1
            out.append(part[k + 2:m - 1] if not depth else part[k + 2:])
            k = m
        elif part[k] == '`':
            m = part.find('`', k + 1)
            out.append(part[k + 1:] if m == -1 else part[k + 1:m])
            k = len(part) if m == -1 else m + 1
        else:
            k += 1
    return out


def strip_redirections(words):
    """The words without redirection operators and their targets (`> /dev/null`, `>&2`, `<<'EOF'`)."""
    out, i = [], 0
    while i < len(words):
        if words[i] and words[i][0] in '<>':
            i += 2
            continue
        out.append(words[i])
        i += 1
    return out


def _skip_opts(words, i, argset):
    """Skip a wrapper's options from words[i]; returns the index of its first operand."""
    while i < len(words) and words[i].startswith('-') and words[i] != '-':
        w = words[i]
        i += 1
        if w == '--':
            break
        if len(w) == 2 and w[1] in argset:
            i += 1
    return i


def command_start(words):
    """Index of the program word after assignments, redirections and wrapper words, or None."""
    i = 0
    while i < len(words):
        w = words[i]
        if w and w[0] in '<>':
            i += 2
            continue
        if '=' in w and w.split('=', 1)[0].replace('_', 'a').isalnum() and not w.startswith('='):
            i += 1
            continue
        base = os.path.basename(w).lower()
        if base in WRAPPERS:
            i = _skip_opts(words, i + 1, WRAPPER_ARG.get(base, set()))
            if base in ('nice', 'timeout') and i < len(words) and words[i].replace('.', '').isdigit():
                i += 1
            continue
        return i
    return None


def getopt(args, argset, prompt_w=False):
    """BSD getopt over args with the argument-taking letters argset: (options, operands)."""
    opts, i = [], 0
    while i < len(args):
        a = args[i]
        if a == '--':
            return opts, args[i + 1:]
        if not a.startswith('-') or a == '-':
            break
        j = 1
        while j < len(a):
            ch = a[j]
            if ch in argset:
                if j + 1 < len(a):
                    opts.append((ch, a[j + 1:]))
                elif prompt_w and ch == 'w' and i + 1 == len(args):
                    opts.append((ch, None))
                else:
                    i += 1
                    opts.append((ch, args[i] if i < len(args) else None))
                break
            opts.append((ch, None))
            j += 1
        i += 1
    return opts, args[i:]


VAR_RX = re.compile(r'\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))')


def expand(word, env):
    """word with ~ and the variables of env (and HOME) put in; None when a $ is left that the gate cannot resolve."""
    if word.startswith('~/') or word == '~':
        word = os.path.expanduser('~') + word[1:]
    def one(m):
        name = m.group(1) or m.group(2)
        if name in env:
            return env[name]
        if name == 'HOME':
            return os.path.expanduser('~')
        return '\0'
    out = VAR_RX.sub(one, word)
    return None if '\0' in out or '$' in out else out


def keychain_problem(path, env, must_exist=True):
    if path is None or path == '':
        return 'no keychain named (security(1) writes the default, login keychain)'
    p = expand(path, env)
    if p is None:
        return f'keychain "{path}" uses a shell variable or substitution the gate cannot resolve; name it literally'
    if not os.path.isabs(p):
        return f'keychain "{path}" is not an absolute path (a name security(1) does not find goes to the login keychain)'
    real = os.path.realpath(p)
    for d in KEYCHAIN_DIRS:
        if real == d or real.startswith(d + os.sep):
            return f'keychain "{path}" is under {d}'
    if under_keychain_dir(real):
        return f'keychain "{path}" is under a keychain directory (another name for it)'
    if must_exist and not os.path.isfile(real):
        return f'keychain "{path}" is not an existing file'
    return None


def judge_security(args, env=None):
    """args: the words after `security`; env: the variables the same text set. Returns (subcommand, reason) or None."""
    env = env or {}
    _, rest = getopt(args, SECURITY_GLOBAL_ARG)
    if not rest:
        return None
    sub, sargs = rest[0], rest[1:]
    hargs = sargs[1:] if sub == 'import' else sargs
    argset = POSITIONAL.get(sub) or CREATE.get(sub) or K_OPTION.get(sub) or ALWAYS.get(sub) or (
        set('d') if sub in SEARCH_SET else set())
    if ('h', None) in getopt(hargs, argset, prompt_w=sub in PROMPT_W)[0]:
        return None  # the subcommand's usage text; it writes nothing (-a -h: -h is the value of -a)
    if sub in POSITIONAL:
        _, operands = getopt(sargs, POSITIONAL[sub], prompt_w=sub in PROMPT_W)
        if not operands:
            return sub, keychain_problem(None, env)
        for kc in operands:
            why = keychain_problem(kc, env)
            if why:
                return sub, why
        return None
    if sub in CREATE:
        _, operands = getopt(sargs, CREATE[sub])
        if not operands:
            return sub, 'no keychain named'
        for kc in operands:
            why = keychain_problem(kc, env, must_exist=False)
            if why:
                return sub, why
        return None
    if sub in K_OPTION:
        if sub == 'import':
            if not sargs:
                return None
            sargs = sargs[1:]
        opts, _ = getopt(sargs, K_OPTION[sub])
        ks = [v for k, v in opts if k == 'k']
        if not ks:
            return sub, 'no -k keychain (security(1) imports into the default, login keychain)'
        for kc in ks:
            why = keychain_problem(kc, env)
            if why:
                return sub, why
        return None
    if sub in ALWAYS:
        return sub, 'it changes the user trust settings, whatever keychain is named'
    if sub in SEARCH_SET:
        opts, _ = getopt(sargs, set('d'))
        if any(k == 's' for k, _ in opts):
            return sub, '-s moves the default keychain or the search list, and later writes with it'
        return None
    return None


def shell_command_arg(args):
    """The command string of `sh -c STRING` (option clusters such as -lc, -ec count), or None."""
    has_c, i = False, 0
    while i < len(args):
        w = args[i]
        if w in ('-o', '+o', '-O', '+O'):
            i += 2
            continue
        if w.startswith('--'):
            i += 1
            continue
        if len(w) > 1 and w[0] in '-+':
            has_c = has_c or 'c' in w[1:]
            i += 1
            continue
        return w if has_c else None
    return None


def shell_reads_stdin(args):
    """A shell with no -c and no script operand (or with -s) reads its commands from stdin."""
    i = 0
    while i < len(args):
        w = args[i]
        if w in ('-o', '+o', '-O', '+O'):
            i += 2
            continue
        if w == '--':
            return i + 1 >= len(args)
        if len(w) > 1 and w[0] in '-+':
            if w[0] == '-' and 's' in w[1:] and not w.startswith('--'):
                return True
            i += 1
            continue
        return False
    return True


def program(words):
    i = command_start(words)
    return (None, []) if i is None else (os.path.basename(words[i]).lower(), strip_redirections(words[i + 1:]))


def judge(cmd, depth=0):
    """(subcommand, reason) for the first blocked call in cmd, or None. Text that a shell runs is read again:
    `bash|sh|zsh|dash|ksh -c STRING`, `eval WORDS`, and a here-document on a line where such a shell runs."""
    # The cheap pre-check reads the text as the shell joins words: no line continuations, quotes or backslashes.
    flat = cmd.replace('\\\n', '').replace("'", '').replace('"', '').replace('\\', '')
    if 'security' not in flat.lower() or not any(w in flat for w in WRITE_WORDS):
        return None
    try:
        subs = []
        cmds, heredocs = split_commands(cmd, subs)
    except Unsplittable:
        # at every depth (Viktor 48711 LOW 1): bash runs the first command of a text the splitter cannot split
        return '?', 'the command cannot be split (an open quote) and names a keychain write subcommand'
    nested = list(subs)
    env = {}
    stdin_shell = False
    for words in cmds:
        # NAME=value alone (or after export) sets a variable for the later commands of the same text.
        assigns = words[1:] if words and words[0] in ASSIGN_WORDS else words
        if assigns and all(ASSIGN_RX.match(w) for w in assigns):
            for w in assigns:
                name, value = w.split('=', 1)
                v = expand(value, env)
                if v is None:
                    env.pop(name, None)
                else:
                    env[name] = v
            continue
        if words and words[0] == 'unset':
            for w in words[1:]:
                env.pop(w, None)  # an unset name is unknown again: "$KC" then cannot be resolved
            continue
        prog, rest = program(words)
        if prog == 'security':
            hit = judge_security(rest, env)
            if hit:
                return hit
        elif prog in SHELLS:
            text = shell_command_arg(rest)
            if text is not None:
                nested.append(text)
            elif shell_reads_stdin(rest):
                stdin_shell = True
                nested.extend(words[k + 1] for k, w in enumerate(words[:-1]) if w == '<<<')
        elif prog == 'eval':
            nested.append(' '.join(rest))
    if stdin_shell:
        for words in cmds:
            p, r = program(words)
            if p in ('echo', 'printf', 'cat'):
                nested.append(' '.join(r))
                nested.extend(r)
    for body, first, last in heredocs:
        if any(program(w)[0] in SHELLS for w in cmds[first:last]):
            nested.append(body)
    if depth < 3:
        for text in nested:
            hit = judge(text, depth + 1)
            if hit:
                return hit
    return None


def allowed(cmd):
    try:
        with open(ALLOW) as f:
            ok = {ln.strip() for ln in f if ln.strip() and not ln.startswith('#')}
    except OSError:
        return False
    return hashlib.sha256(cmd.encode()).hexdigest() in ok


def log_deny(digest, sub, why):
    try:
        os.makedirs(STATE, mode=0o700, exist_ok=True)
        fd = os.open(DENY_LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as f:
            f.write(json.dumps({'ts': int(time.time()), 'sha256': digest, 'sub': sub, 'why': why}) + '\n')
    except OSError:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get('tool_name') != 'Bash':
        return 0
    cmd = (data.get('tool_input') or {}).get('command') or ''
    if not isinstance(cmd, str):
        return 0
    hit = judge(cmd)
    if not hit or allowed(cmd):
        return 0
    sub, why = hit
    digest = hashlib.sha256(cmd.encode()).hexdigest()
    log_deny(digest, sub, why)
    print(f'KEYCHAIN-WRITE-GATE (card 759161e3): security {sub}: {why}. Name the keychain as an absolute path to an '
          f'existing throwaway keychain outside ~/Library/Keychains (security create-keychain /abs/path first). A '
          f'deliberate login-keychain write: with Klodel\'s OK, the command\'s sha256 ({digest}) as a line of {ALLOW}.',
          file=sys.stderr)
    return 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:  # fail-closed
        print(f'KEYCHAIN-WRITE-GATE error: {type(e).__name__}', file=sys.stderr)
        sys.exit(2)
