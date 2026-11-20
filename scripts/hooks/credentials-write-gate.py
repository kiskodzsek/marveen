#!/usr/bin/env python3
"""PreToolUse gate (Bash): an agent shell does not write a Claude Code `.credentials.json` by accident.

Why (card a467f621, Viktor 48495, Radar's weekly review 2026-11-20 point 2; CLAUDE.md fleet AUTH rule 1): a hand-placed
or symlinked `.credentials.json` brought the 401 cascade back every time: an expired file wins over a valid env token.
Claude Code 2.1.326's own block is path-based on its file tools (Write, Edit); the Bash route was open, and before
this gate no hook looked at it (scripts/hooks grep: 0 hits, Viktor 48495).

An ACCIDENT guard, not a boundary: every agent runs as the same macOS user. NOT MODELLED (passes unseen):
- a write from an interpreter: python/node/perl `open(..., 'w')`, `json.dump`, `fs.writeFileSync`, also in a
  here-document a python3/node reads (`python3 - <<EOF`), and a script file's content;
- a directory copy that carries the file inside it (`cp -R ~/.claude/ X/`, `rsync -a A/ B/`, `ditto A B`, `tar x`,
  `unzip`): the file name is not in the text (Viktor 48557 Q2: a follow-up, not this gate);
- a read redirected into a file (`cat ~/.claude/.credentials.json > x`): a copy out, but a read in form;
- a name built beyond the text: a variable set outside the command, `$(...)` output, a glob or brace that does not
  contain "cred", `xargs`/`find -exec`/`parallel` running the writer, a path from a file;
- writers not in the list below (scp, curl -O/--output-dir, wget without -O, a remote rsync target), wrappers and
  options the parser does not know (sudo --user, zsh noglob, GNU abbreviated long options), names set by declare,
  local, typeset, a for loop or ${X:-...}, ANSI-C quoting (Viktor 48557 L2-L4: rare or deliberate forms);
- a quoted `">"` word reads as a redirection (a rare false deny), and a shell reading stdin (`bash -s < f`) makes
  every echo/printf/cat text of the line a command text.

What blocks (exit 2), for every simple command of the text (and, read again, the text a shell runs: `bash|sh|zsh|dash|
ksh -c STRING`, `eval WORDS`, a `$( )` or backtick inside double quotes, a here-document on a line where such a shell
runs, the echo/printf/cat text of a text a shell reads on stdin -- the parser of keychain-write-gate.py, so a
here-document body or quoted text that no shell runs is data and passes), when a WRITE TARGET is named
`.credentials.json` (any letter case: APFS is case-insensitive; a glob or brace that can match it counts):
- a redirection target: `>`, `>>`, `>|`, `&>`, `N>`, `<>`;
- cp, mv, ln, link, install, ditto, rsync (and the g-prefixed GNU names): the destination (the last operand, or
  `-t DIR` / `--target-directory=DIR`), and ANY `.credentials.json` source, whatever the destination (AUTH rule 2
  forbids the copy too, Viktor 48557 Q1): `cp`, `mv`, `ln -s` of the file anywhere, a backup `cp X{,.bak}`, a
  restore `cp X{.bak,}` (a one-level brace is read both ways, as the shell expands it and as one word; M1);
- tee, touch, truncate, sponge (and gtee, gtouch, gtruncate): every operand; dd/gdd `of=`; sed/gsed/perl with an
  in-place `-i` (a cluster such as -pi or -ni; perl -M... is no in-place): every operand; curl `-o`/`--output`,
  wget `-O`/`--output-document`, sort/base64 `-o`;
- a text that cannot be split (an open quote) while it names `.credentials.json` (fail-closed).
Passes: every read (ls, stat, test -f, `[ -e ]`, cat/grep/head without a redirection to it, shasum, find -name),
rm (a delete is not a placement; it is also the way to take a stale file out), chmod, a mention in a here-document
body or a message text.
No allow list: a deliberate placement is exactly what AUTH rule 1 forbids; the fix is the token source.
Denies go to store/credentials-write-gate/deny.log as sha256 + reason, never the command text (it may hold a token).
"""
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
STATE = os.path.join(ROOT, 'store', 'credentials-write-gate')
DENY_LOG = os.path.join(STATE, 'deny.log')
PARSER_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'keychain-write-gate.py')
NAME = '.credentials.json'

COPY_LIKE = {'cp', 'gcp', 'mv', 'gmv', 'ln', 'gln', 'link', 'install', 'ginstall', 'ditto', 'rsync'}
# Option letters that take a separate argument (BSD and GNU; `t` = GNU target directory, read as the destination).
COPY_ARG = {'cp': set('St'), 'gcp': set('St'), 'mv': set('St'), 'gmv': set('St'), 'ln': set('St'), 'gln': set('St'),
            'link': set(), 'install': set('BfgmoSt'), 'ginstall': set('gmoSt'), 'ditto': set(), 'rsync': set('eBfTM')}
COPY_LONG_ARG = {'ditto': {'--arch', '--bom'},
                 'rsync': {'--exclude', '--include', '--filter', '--rsh', '--temp-dir', '--exclude-from',
                           '--include-from', '--files-from', '--compare-dest', '--link-dest', '--copy-dest',
                           '--backup-dir', '--suffix', '--chmod', '--chown', '--log-file', '--password-file',
                           '--partial-dir', '--rsync-path', '--out-format', '--log-file-format', '--max-size',
                           '--min-size', '--block-size', '--timeout', '--contimeout', '--port', '--bwlimit',
                           '--usermap', '--groupmap', '--iconv', '--sockopts', '--write-batch', '--read-batch',
                           '--only-write-batch', '--protocol', '--modify-window', '--checksum-choice',
                           '--compress-choice', '--compress-level', '--skip-compress', '--remote-option'},
                 'install': {'--mode', '--owner', '--group', '--suffix'}}
EVERY_OPERAND_ARG = {'tee': set(), 'gtee': set(), 'touch': set('tdr'), 'gtouch': set('tdr'), 'truncate': set('sr'),
                     'gtruncate': set('sr'), 'sponge': set()}
OUTPUT_OPT = {'curl': ({'-o'}, {'--output'}), 'wget': ({'-O'}, {'--output-document'}), 'sort': ({'-o'}, {'--output'}),
              'gsort': ({'-o'}, {'--output'}), 'base64': ({'-o'}, {'--output'})}
# an in-place option: sed -i / -Ei / --in-place, perl -i / -pi / -ni (not -M..., whose module name may hold an i)
IN_PLACE = {'sed': re.compile(r'^-[nEr]*i|^--in-place'), 'gsed': re.compile(r'^-[nEr]*i|^--in-place'),
            'perl': re.compile(r'^-[pnlaw0-9]*i')}

_P = None


def parser():
    """The shell splitter of keychain-write-gate.py (one parser for both write gates), loaded on first need."""
    global _P
    if _P is None:
        spec = importlib.util.spec_from_file_location('keychain_write_gate_parser', PARSER_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _P = mod
    return _P


def is_cred(word, env):
    """True when the word, as a path, names .credentials.json (letter case ignored; a glob or brace that can)."""
    w = parser().expand(word, env)
    if w is None:
        w = word
    base = w.rstrip('/').rsplit('/', 1)[-1].casefold()
    if base == NAME:
        return True
    if '{' in base and 'cred' in base:
        return True
    if any(ch in base for ch in '*?[') and base.startswith('.'):
        # the shell's glob matches a leading dot only literally (no dotglob): `dir/*` does not name the file
        return fnmatch.fnmatchcase(NAME, base)
    return False


def operands(args, argset, long_arg=()):
    """(operands, target_dir): the non-option words, and the GNU `-t DIR` / `--target-directory=DIR` value."""
    ops, tdir, i = [], None, 0
    while i < len(args):
        w = args[i]
        i += 1
        if w == '--':
            ops.extend(args[i:])
            break
        if w.startswith('--'):
            name, eq, val = w.partition('=')
            if name == '--target-directory':
                if not eq and i < len(args):
                    val = args[i]
                    i += 1
                tdir = val
            elif not eq and name in long_arg:
                i += 1
            continue
        if w.startswith('-') and w != '-':
            for k, ch in enumerate(w[1:]):
                if ch in argset:
                    val = w[k + 2:]
                    if not val and i < len(args):
                        val = args[i]
                        i += 1
                    if ch == 't':
                        tdir = val
                    break
            continue
        ops.append(w)
    return ops, tdir


BRACE_RX = re.compile(r'^([^{}]*)\{([^{}]*,[^{}]*)\}([^{}]*)$')


def brace_words(word):
    """A one-level unquoted brace `a{b,c}d` -> [abd, acd] (the shell expands it before cp sees it); else [word]."""
    m = BRACE_RX.match(word)
    if not m:
        return [word]
    return [m.group(1) + part + m.group(3) for part in m.group(2).split(',')]


def judge_copy(prog, ops, tdir, env):
    """The copy-like verdict on an operand list."""
    if tdir is not None:
        dest, sources = tdir, ops
    elif len(ops) >= 2:
        dest, sources = ops[-1], ops[:-1]
    elif len(ops) == 1 and prog in ('ln', 'gln'):
        dest, sources = '.', ops
    else:
        return None
    if is_cred(dest, env):
        return f'{prog} writes to {NAME}'
    if any(is_cred(s, env) for s in sources):
        return f'{prog} copies, moves or links a {NAME} (AUTH rule 2: no copy either)'
    return None


def judge_program(prog, rest, env):
    """The reason a simple command writes .credentials.json, or None."""
    if prog in COPY_LIKE:
        ops, tdir = operands(rest, COPY_ARG[prog], COPY_LONG_ARG.get(prog, ()))
        wide = [x for w in ops for x in brace_words(w)]  # `cp f{.bak,}` is two operands to cp (Viktor M1)
        if wide != ops:
            hit = judge_copy(prog, wide, tdir, env)
            if hit:
                return hit
        return judge_copy(prog, ops, tdir, env)
    if prog in EVERY_OPERAND_ARG:
        ops, _ = operands(rest, EVERY_OPERAND_ARG[prog])
        if any(is_cred(w, env) for w in ops):
            return f'{prog} writes to {NAME}'
        return None
    if prog in ('dd', 'gdd'):
        if any(w.startswith('of=') and is_cred(w[3:], env) for w in rest):
            return f'dd of= writes to {NAME}'
        return None
    if prog in OUTPUT_OPT:
        shorts, longs = OUTPUT_OPT[prog]
        for k, w in enumerate(rest):
            name, eq, val = w.partition('=')
            if w.startswith('--') and name in longs:
                target = val if eq else (rest[k + 1] if k + 1 < len(rest) else '')
            elif w.startswith('-') and not w.startswith('--') and any(s[1] in w[1:] for s in shorts):
                # a cluster such as -sSLo FILE: the letter's value is the rest of the word or the next word
                at = min(w.index(s[1], 1) for s in shorts if s[1] in w[1:])
                target = w[at + 1:] or (rest[k + 1] if k + 1 < len(rest) else '')
            else:
                continue
            if is_cred(target, env):
                return f'{prog} output writes to {NAME}'
        return None
    if prog in IN_PLACE:
        in_place = any(IN_PLACE[prog].match(w) for w in rest)
        if in_place and any(is_cred(w, env) for w in rest if not w.startswith('-')):
            return f'{prog} -i edits {NAME} in place'
    return None


def judge(cmd, depth=0):
    """The reason for the first write to a .credentials.json in cmd, or None."""
    flat = cmd.replace('\\\n', '').replace("'", '').replace('"', '').replace('\\', '').lower()
    if 'cred' not in flat:
        return None
    P = parser()
    try:
        subs = []
        cmds, heredocs = P.split_commands(cmd, subs)
    except P.Unsplittable:
        if depth or NAME not in flat:
            return None
        return f'the command cannot be split (an open quote) and names {NAME}'
    nested = list(subs)
    env = {}
    stdin_shell = False
    for idx, words in enumerate(cmds):
        for k, w in enumerate(words):
            if w and w[0] in '<>' and '>' in w:
                if k + 1 < len(words):
                    target = words[k + 1]
                elif idx + 1 < len(cmds) and cmds[idx + 1]:
                    target = cmds[idx + 1][0]  # `>| f`: the splitter cut at the `|`
                else:
                    continue
                if is_cred(target, env):
                    return f'a redirection writes to {NAME}'
        assigns = words[1:] if words and words[0] in P.ASSIGN_WORDS else words
        if assigns and all(P.ASSIGN_RX.match(w) for w in assigns):
            for w in assigns:
                name, value = w.split('=', 1)
                v = P.expand(value, env)
                if v is None:
                    env.pop(name, None)
                else:
                    env[name] = v
            continue
        if words and words[0] == 'unset':
            for w in words[1:]:
                env.pop(w, None)
            continue
        prog, rest = P.program(words)
        hit = judge_program(prog, rest, env)
        if hit:
            return hit
        if prog in P.SHELLS:
            text = P.shell_command_arg(rest)
            if text is not None:
                nested.append(text)
            elif P.shell_reads_stdin(rest):
                stdin_shell = True
                nested.extend(words[k + 1] for k, w in enumerate(words[:-1]) if w == '<<<')
        elif prog == 'eval':
            nested.append(' '.join(rest))
    if stdin_shell:
        for words in cmds:
            p, r = P.program(words)
            if p in ('echo', 'printf', 'cat'):
                nested.append(' '.join(r))
                nested.extend(r)
    for body, first, last in heredocs:
        if any(P.program(w)[0] in P.SHELLS for w in cmds[first:last]):
            nested.append(body)
    if depth < 3:
        for text in nested:
            hit = judge(text, depth + 1)
            if hit:
                return hit
    return None


def decide(cmd):
    """The replay entry point (E1): the deny reason or None."""
    return judge(cmd)


def log_deny(digest, why):
    try:
        os.makedirs(STATE, mode=0o700, exist_ok=True)
        fd = os.open(DENY_LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as f:
            f.write(json.dumps({'ts': int(time.time()), 'sha256': digest, 'why': why}) + '\n')
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
    why = judge(cmd)
    if not why:
        return 0
    digest = hashlib.sha256(cmd.encode()).hexdigest()
    log_deny(digest, why)
    print(f'CREDENTIALS-WRITE-GATE (card a467f621): {why}. A hand-placed or linked {NAME} brings the 401 cascade '
          f'back (CLAUDE.md fleet AUTH rule 1): an expired file wins over a valid env token. The fix is the token '
          f'source (store/.claude-oauth-token, the agent\'s own token), not a credentials file. Reading it (ls, '
          f'stat, test -f) passes.', file=sys.stderr)
    return 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:  # fail-closed; the cheap pre-check means only a text with "cred" in it can get here
        print(f'CREDENTIALS-WRITE-GATE error: {type(e).__name__}', file=sys.stderr)
        sys.exit(2)
