#!/usr/bin/env python3
"""prod-tree-write-gate: PreToolUse hook (matcher `Write|Edit|MultiEdit|NotebookEdit|Bash`) that keeps sub-agents
out of the production checkout's code and config (card 11c4a5fe; Klodel 42803/42808/42812; Viktor 42806, 42810 K1-K4,
42816 1a-c/2/E1-E3; plan: agents/kernel/reports/plan-prod-tree-write-gate-1115.md v4).

WHAT IT IS: an ACCIDENT guard, not a security boundary. It stops the frequent, lazy damage (an agent editing
/Users/klodel/marveen/scripts/... by hand instead of in a worktree). It does NOT stop a script or an interpreter that
writes (python -c, node -e, a .sh file), a path assembled at run time beyond what is resolved below, or an agent that
rewrites its own config with the same uid. The durable boundary is a separate uid / root-owned tree (owner decision).

WHO: identity comes from the hook payload's `transcript_path` (set by Claude Code from the session's config dir; the
agent does not choose it per call). A path under <prod>/agents/<name>/.claude-config/ is the sub-agent <name>; every
other session (the main agent, the owner) is NOT gated: the gate still computes the decision and logs a would-deny
line for it, but always lets the call through. No transcript_path = unknown = allow (+ log if the text names a
protected path). No environment variable is read (an agent can set env in its own settings).

PROTECTED (case-insensitive: APFS is, realpath does not fold case; K1): <prod>/scripts, <prod>/src, <prod>/.claude
(the directories and everything under them), and the files <prod>/CLAUDE.md, .mcp.json, package.json,
package-lock.json, store/autonomy-config.json (Klodel 42812). The firmlinked /System/Volumes/Data<prod> form counts.
A path is checked both normalised and realpath-resolved (symlinks, `..`); either form protected = protected.

WHAT IS DENIED for a sub-agent:
  - Write/Edit/MultiEdit/NotebookEdit on a protected path; a missing, non-string or unresolvable path = deny.
  - Bash: a write whose target resolves to a protected path: redirections (>, >>, >|, &>, <>), tee, cp/mv/ln/install/
    rsync/ditto/scp destination (and destination/basename(source)), mv sources, rm/rmdir/unlink/touch/mkdir/chmod/
    chown/chgrp/chflags/truncate/shred/mkfifo, sed -i/perl -i files, dd of=, curl -o/wget -O, find -delete/-exec;
    for the destructive ones (rm, rmdir, mv, chmod, chown, chgrp, chflags, find) an ANCESTOR of the protected tree
    (the prod root itself) counts too. A glob or a partly unknown target is checked by its literal directory prefix.
  - Bash: git commands that write the production work tree (K3): checkout, switch, restore, reset, stash (not list/
    show), apply (not --check/--stat), am, cherry-pick, revert, merge, pull, rebase, clean (not -n), mv, rm,
    read-tree -u, checkout-index, submodule update/deinit, worktree remove/move of the prod tree; the target repo is
    found from -C, --git-dir, --work-tree, GIT_DIR, GIT_WORK_TREE and the nearest .git above the git cwd.
    `git fetch`, `git worktree add` (outside the protected tree) and all reading commands stay free.
  - Bash: npm/pnpm/yarn/bun install-type commands, patch, tar -x, unzip whose working directory is the prod root or
    inside a protected directory (they rewrite files below their cwd).
  - Bash fallback (K2, 1a): a write target that cannot be resolved (`$VAR`, `$(...)`), a lexer error or a path
    resolution error = deny when the RAW command text (casefolded) names a protected path in any form (absolute,
    ~/, $HOME/, the firmlink form, relative to a prod cwd, ../ from inside the tree, the root followed by a closer of
    a substitution or quote, and -- when the cwd's repository is the prod checkout -- a `... rev-parse
    --show-toplevel` substitution directly in front of a protected part); otherwise allow + an `unresolved-allow`
    log line. A variable or a substitution of another form in front of a protected part is NOT a raw match (the E1
    replay: every agent home is inside the prod repo, so it gave false denies).
  `cd`, `pushd`, `git -C`, `bash -c`, `sh -c`, `eval`, `$(...)`, backticks, process substitution and a heredoc fed to
  a shell are followed; `sudo`, `env`, `nice`, `nohup`, `time`, `command`, `exec`, `timeout`, `xargs` are unwrapped.
  A brace group `{ ...; }` is a command list like `( ... )` (its first command too; Viktor 42855 M1); a brace
  expansion is one word across a quoted or escaped space (`../{CLAUDE.md,"x y"}`); the bash keyword `time` takes
  inline assignments like `env` (`time GIT_DIR=... git reset --hard`; L1), and `time !`, `time { ...; }`,
  `function NAME { ...; }` are followed (Viktor v2 delta).
  NOT MODELLED (Viktor 42855 INFO 1, a documented limit of an accident guard): writers outside the list above, e.g.
  sort -o, ex/vi -c, sed 'w file', split, git archive -o, git bundle create, git diff/log --output,
  git format-patch -o, git merge-file; xargs fed from a variable or a pipe; while-read loops; a command piped to a
  shell (`echo cmd | bash`) and `source <(...)`; interpreters (-c/-e) and script files run by a shell. Only the
  raw-text rule can catch these, when the target is not resolved by the gate.
  Values the gate tracks inside one command: literal and prefix-known assignments (X=lit, B=dir/m-$(date)),
  $(mktemp), $(pwd), $(dirname X), ${X%pat}, $(git [-C d] rev-parse --show-toplevel [2>/dev/null]) = the
  repository root of that directory, $(echo LIT), $(printf %s LIT), for-loop word lists, repos created by
  worktree add / clone / init.

RAW-TEXT RULE AFTER A SUCCESSFUL ANALYSIS (narrowed by the E1 replay, Viktor 42816 E1): the executed command and the
script path given to an interpreter (`python3 -I <prod>/scripts/x.py > "$OUT"`) are removed from the text first, and
the bare prod root counts only through the tracked cwd (payload cwd, cd/pushd, git -C landing on the prod root or in
a protected directory), not as a text mention. On a lexer error the full text and the bare root count (1a strict).

FAIL BEHAVIOUR (Viktor 42810 1., 42816 1a-b): Write-type tools fail CLOSED for a sub-agent. Bash fails open only when
the raw text names no protected path. Any unexpected exception or the internal deadline: the same rule (deny if
sub-agent and the raw text names a protected path or the tool is Write-type; else allow), and a log line.

WHERE IT IS WIRED (Klodel 42872, Viktor 42810 "managed-settings ... most nem ... elfogadható"): every sub-agent's
own .claude/settings.json, PreToolUse, by src/web/agent-scaffold.ts (injectProdTreeWriteGate at spawn,
ensureProdTreeWriteGate on dashboard start: a removed or stale entry is written back). The main agent does not carry
it. An agent can still take the entry out of its own settings until the next start/spawn (accident guard, see above);
the root-owned managed-settings form is parked under H1 until the owner asks for it.

LOG (1b): <root>/store/prod-tree-write-gate/gate.jsonl, created on the first write (agent-writable, NOT append-only:
evidence for the review, not tamper-proof), one JSON line per: deny, error-allow, unresolved-allow (a sub-agent's allowed write whose target was not resolved),
would-deny of a non-gated session, and one `seen` line per session (marker files in
seen/), with time, agent (name | main | unknown), tool, decision, reason, and the first 200 characters of the input
with secrets masked. A failing log write never changes the decision. The gate imports nothing from the agent-writable
tree (python3 -I, stdlib only): the masking patterns are a copy of scripts/hooks/tool-log-capture.py _SECRET_PATTERNS.

Output: deny = one PreToolUse JSON line (permissionDecision deny + reason), exit 0. Allow = no output, exit 0 (the
normal permission flow continues; the gate never grants a permission). Python 3.9 compatible (/usr/bin/python3).
"""
import sys
try:
    import hashlib, json, os, pwd, re, signal, time
except BaseException:  # nothing to log with: let the call through, say why on stderr
    sys.stderr.write('prod-tree-write-gate: python stdlib unavailable, allowing\n')
    sys.exit(0)

# the install root: this file is <root>/scripts/hooks/prod-tree-write-gate.py (the hook command names the production
# checkout's copy; a worktree copy run by hand would only guard that worktree)
PROD = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(os.path.abspath(__file__)))))
LOG_DIR = os.path.join(PROD, 'store', 'prod-tree-write-gate')
PROTECTED_DIRS = ('scripts', 'src', '.claude')
PROTECTED_FILES = ('CLAUDE.md', '.mcp.json', 'package.json', 'package-lock.json', 'store/autonomy-config.json')
FIRMLINK = '/system/volumes/data'
WRITE_TOOLS = {'Write': 'file_path', 'Edit': 'file_path', 'MultiEdit': 'file_path', 'NotebookEdit': 'notebook_path'}
DEADLINE_S = 5            # managed-settings entry has "timeout": 15; a timed-out hook does not block
MAX_STDIN = 4 * 1024 * 1024
MAX_CMD = 200000          # longer Bash text: only the raw-text rule runs
MAX_DEPTH = 5             # nested bash -c / $(...) / eval levels
MAX_PATH = 4096
LOG_INPUT = 200
# What to do instead (Klodel 42825 (1)): every deny says it, so a night-time deploy does not stop without a word.
DENY_HINT = ('a prod-fába (%s: scripts/, src/, .claude/ és a gyökér CLAUDE.md, .mcp.json, package*.json, '
             'store/autonomy-config.json) sub-ágens nem ír. TEENDŐ: worktree + PR (scripts/worktree-add.sh); '
             'ha a prod-fán tényleg kell, üzenj Klodelnek a pontos paranccsal')
DENY_HINT_PULZUS = (' ÁTVEZETÉSNÉL (Pulzus): az origin/main változatát a bash '
                    '/Users/klodel/marveen/agents/pulzus/scripts/restore-from-main.sh [--apply] veszi át; ha nem '
                    'fedi, üzenj Klodelnek a pontos paranccsal')


class LexError(Exception):
    pass


class ResolveError(Exception):
    pass


class Deadline(BaseException):
    pass


# ---------------------------------------------------------------- paths

def home_dir():
    try:
        return pwd.getpwuid(os.getuid()).pw_dir
    except Exception:
        return None


def fold(p):
    """normpath + casefold + firmlink prefix removed; raises ResolveError on NUL / huge / non-str."""
    if not isinstance(p, str) or '\x00' in p or len(p) > MAX_PATH:
        raise ResolveError('path')
    try:
        p.encode('utf-8')
    except UnicodeEncodeError:
        raise ResolveError('path encoding')
    f = os.path.normpath(p).casefold()
    if f == FIRMLINK or f.startswith(FIRMLINK + '/'):
        f = f[len(FIRMLINK):] or '/'
    if f.startswith('//'):
        f = '/' + f.lstrip('/')
    return f


class Prod(object):
    def __init__(self, root):
        self.root = root
        self.cf = fold(root)
        self.dirs = tuple(self.cf + '/' + d for d in PROTECTED_DIRS)
        self.files = tuple(self.cf + '/' + f.casefold() for f in PROTECTED_FILES)

    def kind_of(self, f):
        """f: folded absolute path -> 'protected' | 'ancestor' | 'inside' (prod tree, not protected) | None."""
        for d in self.dirs:
            if f == d or f.startswith(d + '/'):
                return 'protected'
        if f in self.files:
            return 'protected'
        if f == '/' or (self.cf + '/').startswith(f.rstrip('/') + '/'):
            return 'ancestor'
        if f.startswith(self.cf + '/'):
            return 'inside'
        return None

    def classify(self, path):
        """absolute path -> the strictest kind of its normalised and its realpath form."""
        forms = [fold(path)]
        try:
            forms.append(fold(os.path.realpath(path)))
        except ResolveError:
            raise
        except Exception as e:   # realpath loop / OSError / ValueError
            raise ResolveError('realpath: %s' % type(e).__name__)
        kinds = [self.kind_of(f) for f in forms]
        for k in ('protected', 'ancestor', 'inside'):
            if k in kinds:
                return k
        return None


def find_repo(path):
    """Nearest directory at or above `path` (or its nearest existing parent) that holds a .git entry."""
    p = os.path.realpath(path)
    for _ in range(256):
        if os.path.isdir(p) and os.path.lexists(os.path.join(p, '.git')):
            return p
        q = os.path.dirname(p)
        if q == p:
            return None
        p = q
    return None


# ---------------------------------------------------------------- lexer

META = frozenset(' \t\n;&|<>()')
IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
ASSIGN = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\+?=')


class Word(object):
    __slots__ = ('parts', 'raw')

    def __init__(self, parts, raw):
        self.parts = parts   # [(kind, text)]: lit, tilde, var, sub, glob, unk
        self.raw = raw

    def literal(self):
        """the word when it is plain literal text (quotes removed), else None"""
        if all(k == 'lit' for k, _ in self.parts):
            return ''.join(t for _, t in self.parts)
        return None


def match_close(s, i, close):
    """index of the `close` paren/brace matching an opener just before s[i]; quote and nesting aware."""
    depth, n = 1, len(s)
    opener = '(' if close == ')' else '{'
    while i < n:
        c = s[i]
        if c == '\\':
            i += 2
            continue
        if c == "'":
            j = s.find("'", i + 1)
            if j < 0:
                raise LexError('quote')
            i = j + 1
            continue
        if c == '"':
            i = skip_dq(s, i + 1)
            continue
        if c == '`':
            i = skip_bt(s, i + 1)
            continue
        if c == opener:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise LexError('unclosed %s' % close)


def skip_dq(s, i):
    n = len(s)
    while i < n:
        c = s[i]
        if c == '\\':
            i += 2
            continue
        if c == '"':
            return i + 1
        if c == '$' and s.startswith('$(', i):
            i = match_close(s, i + 2, ')') + 1
            continue
        if c == '`':
            i = skip_bt(s, i + 1)
            continue
        i += 1
    raise LexError('unclosed "')


def skip_bt(s, i):
    n = len(s)
    while i < n:
        if s[i] == '\\':
            i += 2
            continue
        if s[i] == '`':
            return i + 1
        i += 1
    raise LexError('unclosed `')


def read_dollar(s, i, parts, subs):
    """s[i] == '$'; appends one part, returns the next index."""
    n = len(s)
    if s.startswith('$((', i):
        j = match_close(s, i + 2, ')')
        parts.append(('unk', s[i:j + 1]))
        return j + 1
    if s.startswith('$(', i):
        j = match_close(s, i + 2, ')')
        subs.append(s[i + 2:j])
        parts.append(('sub', s[i + 2:j]))
        return j + 1
    if s.startswith('${', i):
        j = match_close(s, i + 2, '}')
        inner = s[i + 2:j]
        mm = re.match(r'([A-Za-z_][A-Za-z0-9_]*)(:?[-?=+].*)?$', inner, re.S)
        cut = re.match(r'([A-Za-z_][A-Za-z0-9_]*)%%?[^/]*$', inner, re.S)
        if cut:
            parts.append(('varcut', cut.group(1)))
        elif IDENT.fullmatch(inner):
            parts.append(('var', inner))
        elif mm and mm.group(2) and mm.group(2).lstrip(':')[:1] in '?':
            parts.append(('var', mm.group(1)))
        else:
            subs.extend(re.findall(r'\$\(([^()]*)\)', inner))
            parts.append(('unk', inner))
        return j + 1
    if s.startswith("$'", i):
        j = i + 2
        while j < n and s[j] != "'":
            j += 2 if s[j] == '\\' else 1
        if j >= n:
            raise LexError("unclosed $'")
        parts.append(('unk', s[i:j + 1]))
        return j + 1
    m = IDENT.match(s, i + 1)
    if m:
        parts.append(('var', m.group(0)))
        return m.end()
    if i + 1 < n and s[i + 1] in '0123456789@*#?-$!':
        parts.append(('unk', s[i:i + 2]))
        return i + 2
    parts.append(('lit', '$'))
    return i + 1


def add_lit(parts, t):
    if parts and parts[-1][0] == 'lit':
        parts[-1] = ('lit', parts[-1][1] + t)
    else:
        parts.append(('lit', t))


def read_dq(s, i, parts, subs):
    n = len(s)
    while i < n:
        c = s[i]
        if c == '\\' and i + 1 < n and s[i + 1] in '$`"\\\n':
            if s[i + 1] != '\n':
                add_lit(parts, s[i + 1])
            i += 2
            continue
        if c == '"':
            return i + 1
        if c == '$':
            i = read_dollar(s, i, parts, subs)
            continue
        if c == '`':
            j = skip_bt(s, i + 1)
            subs.append(s[i + 1:j - 1])
            parts.append(('sub', s[i + 1:j - 1]))
            i = j
            continue
        add_lit(parts, c)
        i += 1
    raise LexError('unclosed "')


def read_word(s, i, subs):
    parts, start, n = [], i, len(s)
    if s[i] == '~':
        j = i + 1
        while j < n and s[j] not in META and s[j] not in '/\'"$`\\':
            j += 1
        parts.append(('tilde', s[i + 1:j]))
        i = j
    while i < n:
        c = s[i]
        if c in META:
            break
        if c == '\\':
            if i + 1 < n and s[i + 1] != '\n':
                add_lit(parts, s[i + 1])
            i += 2
            continue
        if c == "'":
            j = s.find("'", i + 1)
            if j < 0:
                raise LexError("unclosed '")
            add_lit(parts, s[i + 1:j])
            i = j + 1
            continue
        if c == '"':
            if not parts:
                parts.append(('lit', ''))
            i = read_dq(s, i + 1, parts, subs)
            continue
        if c == '$':
            if s.startswith('$"', i):
                i = read_dq(s, i + 2, parts, subs)
                continue
            i = read_dollar(s, i, parts, subs)
            continue
        if c == '`':
            j = skip_bt(s, i + 1)
            subs.append(s[i + 1:j - 1])
            parts.append(('sub', s[i + 1:j - 1]))
            i = j
            continue
        if c in '*?[':
            parts.append(('glob', c))
            i += 1
            continue
        if c == '{':
            # brace expansion only when the closing brace is in the SAME word (no metacharacter before it); a
            # search to the next '}' anywhere took a group opener `{ rm ../x; }` for an expansion (Viktor 42855 M1)
            j = i + 1
            while j < n and s[j] not in META and s[j] != '}':
                if s[j] == '\\':
                    j += 2
                elif s[j] in '\'"':      # a quoted piece may hold a metacharacter: the brace word goes on after it
                    k = s.find(s[j], j + 1)
                    j = n if k < 0 else k + 1
                else:
                    j += 1
            if j < n and s[j] == '}' and (',' in s[i:j] or '..' in s[i:j]):
                parts.append(('glob', '{'))
        add_lit(parts, c)
        i += 1
    return Word(parts, s[start:i]), i


REDIR = re.compile(r'(\d*)(>>|>\||>&|&>>|&>|>|<<<|<<-|<<|<>|<&|<)')
OPS = ('&&', '||', ';;&', ';;', ';&', ';', '|&', '|', '&', '(', ')', '\n')


def lex(s):
    """-> tokens: ('w', Word) | ('op', str) | ('r', op, target Word or None, heredoc dict or None); subs list."""
    toks, subs, pending, i, n = [], [], [], 0, len(s)
    while i < n:
        c = s[i]
        if c == '\n':
            toks.append(('op', '\n'))
            i += 1
            for hd in pending:
                i = read_heredoc(s, i, hd)
            pending = []
            continue
        if c in ' \t':
            i += 1
            continue
        if c == '\\' and s.startswith('\\\n', i):
            i += 2
            continue
        if c == '#':
            j = s.find('\n', i)
            i = n if j < 0 else j
            continue
        if s.startswith('<(', i) or s.startswith('>(', i):
            j = match_close(s, i + 2, ')')
            subs.append(s[i + 2:j])
            toks.append(('w', Word([('sub', s[i + 2:j])], s[i:j + 1])))
            i = j + 1
            continue
        m = REDIR.match(s, i) if (c in '<>&' or c.isdigit()) else None
        if m and (c in '<>' or c.isdigit() or m.group(2).startswith('&')):
            op = m.group(2)
            i = m.end()
            while i < n and s[i] in ' \t':
                i += 1
            if s.startswith('<(', i) or s.startswith('>(', i):
                j = match_close(s, i + 2, ')')
                subs.append(s[i + 2:j])
                w, i = Word([('sub', s[i + 2:j])], s[i:j + 1]), j + 1
            elif i >= n or s[i] in META:
                raise LexError('redirect without target')
            else:
                w, i = read_word(s, i, subs)
            hd = None
            if op in ('<<', '<<-'):
                hd = {'delim': w.literal() if w.literal() is not None else ''.join(t for _, t in w.parts),
                      'tabs': op == '<<-', 'body': ''}
                pending.append(hd)
            toks.append(('r', op, w, hd))
            continue
        for op in OPS:
            if s.startswith(op, i):
                toks.append(('op', op))
                i += len(op)
                break
        else:
            w, i = read_word(s, i, subs)
            toks.append(('w', w))
    return toks, subs


def read_heredoc(s, i, hd):
    lines, n = [], len(s)
    while i < n:
        j = s.find('\n', i)
        line = s[i:] if j < 0 else s[i:j]
        i = n if j < 0 else j + 1
        if (line.lstrip('\t') if hd['tabs'] else line) == hd['delim']:
            break
        lines.append(line)
    hd['body'] = '\n'.join(lines)
    return i


def commands(toks):
    """-> list of simple commands {'words': [Word], 'redirs': [(op, Word, hd)], 'pipe_prev': cmd or None}"""
    out, cur, prev_pipe = [], None, None
    for t in toks:
        if t[0] == 'op':
            if cur is not None:
                out.append(cur)
            prev_pipe = cur if t[1] in ('|', '|&') else None
            cur = None
            continue
        if cur is None:
            cur = {'words': [], 'redirs': [], 'pipe_prev': prev_pipe}
        if t[0] == 'w':
            cur['words'].append(t[1])
        else:
            cur['redirs'].append((t[1], t[2], t[3]))
    if cur is not None:
        out.append(cur)
    return out


# ---------------------------------------------------------------- Bash analysis

RESERVED = frozenset(['if', 'then', 'else', 'elif', 'fi', 'do', 'done', 'while', 'until', 'for', 'in', 'case', 'esac',
                      'function', '{', '}', '!', 'select', 'coproc', '[[', ']]'])
SHELLS = frozenset(['bash', 'sh', 'zsh', 'dash', 'ksh'])
INTERPRETERS = frozenset(['python', 'python3', 'node', 'perl', 'ruby', 'tsx', 'deno', 'bun', 'source', '.',
                          'osascript', 'php'])
WRAPPERS = frozenset(['sudo', 'env', 'nice', 'nohup', 'time', 'command', 'builtin', 'exec', 'timeout', 'gtimeout',
                      'caffeinate', 'stdbuf', 'noglob', 'doas'])
WRAP_ARG_OPTS = {'sudo': ('-u', '-g', '-C', '-h', '-p', '-U', '-r', '-t', '-D'), 'nice': ('-n',),
                 'env': ('-u', '-C', '-S'), 'timeout': ('-s', '-k', '--signal', '--kill-after'),
                 'stdbuf': ('-i', '-o', '-e'), 'doas': ('-u', '-C')}
ALL_ARGS = frozenset(['rm', 'rmdir', 'unlink', 'touch', 'mkdir', 'chmod', 'chown', 'chgrp', 'chflags', 'truncate',
                      'shred', 'srm', 'mkfifo', 'tee', 'sponge', 'mv', 'gmv', 'grm', 'gtouch', 'gmkdir'])
DESTRUCTIVE = frozenset(['rm', 'rmdir', 'unlink', 'mv', 'gmv', 'grm', 'chmod', 'chown', 'chgrp', 'chflags', 'shred',
                         'srm', 'find', 'truncate'])
LAST_ARG = frozenset(['cp', 'gcp', 'ln', 'gln', 'install', 'ginstall', 'rsync', 'ditto', 'scp'])
OPT_WITH_ARG = {'cp': 'St', 'gcp': 'St', 'ln': 'St', 'gln': 'St', 'install': 'mogSt', 'ginstall': 'mogSt',
                'mkdir': 'm', 'gmkdir': 'm', 'truncate': 'sr', 'touch': 'rtdA', 'gtouch': 'rtdA', 'rsync': 'eTf',
                'scp': 'cFiJloPS', 'mv': 'St', 'gmv': 'St', 'patch': 'iodrDBFVYzg'}
PKG = frozenset(['npm', 'pnpm', 'yarn', 'bun', 'npx'])
PKG_WRITE = frozenset(['install', 'i', 'ci', 'uninstall', 'un', 'remove', 'rm', 'update', 'up', 'upgrade', 'add',
                       'dedupe', 'prune', 'link', 'audit', 'rebuild', 'init', 'version'])
GIT_GLOBAL_ARG = frozenset(['-C', '-c', '--git-dir', '--work-tree', '--namespace', '--exec-path', '--super-prefix',
                            '--config-env'])
GIT_ALWAYS_WRITE = frozenset(['checkout', 'switch', 'restore', 'reset', 'am', 'cherry-pick', 'revert', 'merge', 'pull',
                              'rebase', 'mv', 'rm', 'checkout-index'])
TREE_WRITERS_MSG = 'a prod-fa munkakönyvtárát írja'
UNRESOLVED_ALLOW = 'nem feloldható írási cél, a szöveg nem nevez védett utat'   # logged as unresolved-allow (L2)


class State(object):
    def __init__(self, prod, cwd, home):
        self.prod = prod
        self.cwd = cwd            # absolute str, or None = unknown
        self.home = home
        self.vars = {'TMPDIR': '/private/tmp/prod-tree-write-gate-tmpdir'}   # a placeholder, not prod
        self.loops = {}           # for-loop variable -> the listed words
        self.new_repos = []       # paths a `git worktree add` / `git clone` / `git init` in this command creates
        self.deny = []            # reasons
        self.unknown = []         # raw text of write targets we could not resolve
        self.errors = []          # resolve / lex errors (1a)
        self.partial = ''
        self.prod_cwd = False     # a cd / pushd / git -C in this command went to the prod root or a protected dir
        self.exec_raw = []        # executed command / script words: not a write mention for the raw-text rule


def word_path(w, st, cwd=None):
    """-> ('path', abs) | ('dir', abs dir that contains every expansion) | ('unknown', None)"""
    cwd = st.cwd if cwd is None else cwd
    acc, rest = '', None
    for idx, (k, t) in enumerate(w.parts):
        if k == 'lit':
            acc += t
        elif k == 'tilde':
            if t == '':
                h = st.home
            else:
                try:
                    h = pwd.getpwnam(t).pw_dir
                except Exception:
                    h = None
            if h is None:
                rest = w.parts[idx:]
                break
            acc += h
        elif k == 'var' and t == 'HOME' and st.home:
            acc += st.home
        elif k == 'var' and t == 'PWD' and cwd:
            acc += cwd
        elif k == 'var' and isinstance(st.vars.get(t), str):
            acc += st.vars[t]
        elif k == 'var' and isinstance(st.vars.get(t), tuple):
            acc += st.vars[t][1]
            rest = [('glob', '$')] + w.parts[idx + 1:]
            break
        elif k == 'varcut' and isinstance(st.vars.get(t), str) and '/' in st.vars[t]:
            v = st.vars[t]
            acc += v[:v.rfind('/') + 1]
            rest = [('glob', '%')] + w.parts[idx + 1:]
            break
        elif k == 'sub' and sub_value(t, st, cwd) is not None:
            acc += sub_value(t, st, cwd)
        else:
            rest = w.parts[idx:]
            break
    st.partial = ''
    if rest is None:
        if acc == '':
            return ('unknown', None)
        if not acc.startswith('/'):
            if cwd is None:
                return ('unknown', None)
            acc = os.path.join(cwd, acc)
        return ('path', acc)
    if any(k == 'lit' and '..' in t for k, t in rest):
        return ('unknown', None)
    if acc == '' and rest[0][0] != 'glob':
        return ('unknown', None)
    if '/' in acc:
        d = acc[:acc.rfind('/')] or '/'
        st.partial = acc[acc.rfind('/') + 1:]
    else:
        d = '.'
        st.partial = acc
    if not d.startswith('/'):
        if cwd is None:
            return ('unknown', None)
        d = os.path.normpath(os.path.join(cwd, d))
    return ('dir', d)


def sub_value(text, st, cwd):
    """the value of a few side-effect-free command substitutions: $(pwd), $(dirname X), $(mktemp ...)"""
    t = text.strip()
    if t == 'pwd':
        return cwd
    if t.startswith('mktemp'):
        return '/private/tmp/prod-tree-write-gate-mktemp'
    if (t.startswith('git ') or t.startswith('echo ') or t.startswith('printf ')) and len(t) < 1000:
        try:
            toks, subs = lex(t)
        except LexError:
            return None
        if subs:
            return None
        ws, ok = [], True
        for x in toks:
            if x[0] == 'w':
                ws.append(x[1])
            elif x[0] == 'r' and x[1] in ('>', '2>', '>&') and x[2] is not None and x[2].literal() in ('/dev/null', '1', '2'):
                continue
            else:
                ok = False
        lits = [w.literal() for w in ws]
        if ok and None not in lits:
            if lits[0] == 'echo' and len(lits) == 2:
                return lits[1]
            if lits[0] == 'printf' and len(lits) == 3 and lits[1] == '%s':
                return lits[2]
            if lits[:1] == ['git']:
                g = lits[1:]
                gcwd = cwd
                if len(g) >= 2 and g[0] == '-C':
                    kind, gp = word_path(ws[2], st, cwd)
                    gcwd = gp if kind == 'path' else None
                    g = g[2:]
                if g == ['rev-parse', '--show-toplevel'] and gcwd:
                    return find_repo(gcwd)
        return None
    if t.startswith('dirname ') and len(t) < 1000:
        try:
            toks, _ = lex(t)
        except LexError:
            return None
        ws = [x[1] for x in toks if x[0] == 'w']
        if len(ws) == 2 and len(toks) == 2:
            kind, p = word_path(ws[1], st, cwd)
            if kind == 'path':
                return os.path.dirname(p.rstrip('/')) or '/'
    return None


def expand_loops(w, st, depth=0):
    """a word with a for-loop variable -> one word per listed value (bounded)"""
    if depth < 2:
        for idx, (k, t) in enumerate(w.parts):
            if k == 'var' and t in st.loops and st.vars.get(t) is None:
                out = []
                for v in st.loops[t]:
                    out.extend(expand_loops(Word(w.parts[:idx] + v.parts + w.parts[idx + 1:], w.raw), st, depth + 1))
                return out[:200]
    return [w]


def check_target(w, st, destructive=False, what='írás'):
    alts = expand_loops(w, st)
    if len(alts) != 1 or alts[0] is not w:
        for a in alts:
            check_target_one(a, st, destructive, what)
        return
    check_target_one(w, st, destructive, what)


def check_target_one(w, st, destructive=False, what='írás'):
    kind, p = word_path(w, st)
    if kind == 'unknown':
        st.unknown.append(w.raw[:120])
        return
    try:
        k = st.prod.classify(p)
    except ResolveError as e:
        st.errors.append('útfeloldás (%s): %s' % (e, w.raw[:80]))
        return
    if kind == 'dir':
        if k == 'ancestor' and st.partial:
            # the expansion starts with the literal `partial`: it reaches the prod tree only if the next prod path
            # component can start with it
            try:
                fd = fold(p).rstrip('/')
                nxt = st.prod.cf[len(fd) + 1:].split('/')[0] if fd != st.prod.cf else ''
            except ResolveError:
                nxt = ''
            if nxt and not nxt.startswith(st.partial.casefold()):
                return
        if k in ('protected', 'ancestor'):
            st.deny.append('%s nem feloldható célja (%s) a védett fába vagy fölé mutat' % (what, w.raw[:80]))
        return
    if k == 'protected' or (destructive and k == 'ancestor'):
        st.deny.append('%s a védett útra: %s' % (what, w.raw[:80]))


def lits(words):
    return [w.literal() for w in words]


def split_opts(name, args):
    """-> (option words, positional words); `--` ends options; a short option in OPT_WITH_ARG takes the next word."""
    opts, pos, i = [], [], 0
    takes = OPT_WITH_ARG.get(name, '')
    while i < len(args):
        w = args[i]
        t = w.literal()
        if t == '--':
            pos.extend(args[i + 1:])
            break
        if t is not None and len(t) > 1 and t.startswith('-'):
            opts.append(w)
            if not t.startswith('--') and len(t) == 2 and t[1] in takes and i + 1 < len(args):
                opts.append(args[i + 1])
                i += 1
            i += 1
            continue
        pos.append(w)
        i += 1
    return opts, pos


def analyze_git(words, env, st):
    i, gcwd, unknown = 1, st.cwd, False
    gitdir = worktree = None
    for key in ('GIT_DIR', 'GIT_WORK_TREE'):
        src = env if key in env else (st.vars if key in st.vars else None)
        if src is not None:
            if not isinstance(src[key], str):
                unknown = True
            elif key == 'GIT_DIR':
                gitdir = src[key] if src[key].startswith('/') or st.cwd is None else os.path.join(st.cwd, src[key])
            else:
                worktree = src[key] if src[key].startswith('/') or st.cwd is None else os.path.join(st.cwd, src[key])
    while i < len(words):
        t = words[i].literal()
        if t is None:
            unknown = True
            i += 1
            continue
        if not t.startswith('-'):
            break
        key, eq, val = t.partition('=')
        if key in GIT_GLOBAL_ARG:
            if not eq:
                i += 1
                vw = words[i] if i < len(words) else None
            else:
                vw = Word([('lit', val)], val)
            if vw is not None and key in ('-C', '--git-dir', '--work-tree'):
                kind, p = word_path(vw, st, gcwd)
                if kind != 'path':
                    unknown = True
                elif key == '-C':
                    gcwd = p
                    mark_prod_cwd(st, p)
                elif key == '--git-dir':
                    gitdir = p
                else:
                    worktree = p
        i += 1
    if i >= len(words):
        return
    sub = words[i].literal()
    args = lits(words[i + 1:])
    if sub is None:
        return
    writes = False
    if sub in GIT_ALWAYS_WRITE:
        writes = True
    elif sub == 'stash':
        writes = not (args and args[0] in ('list', 'show'))
    elif sub == 'apply':
        writes = not any(a in ('--check', '--stat', '--numstat', '--summary') for a in args if a) or '--apply' in args
    elif sub == 'clean':
        writes = not any(a and (a in ('-n', '--dry-run') or (a.startswith('-') and not a.startswith('--')
                                                                  and 'n' in a)) for a in args)
    elif sub == 'read-tree':
        writes = any(a and (a == '-u' or a == '--reset' or (a.startswith('-') and not a.startswith('--')
                                                                and 'u' in a)) for a in args)
    elif sub == 'submodule':
        writes = any(a in ('update', 'deinit', 'add', 'absorbgitdirs') for a in args)
    elif sub == 'worktree':
        if args and args[0] in ('remove', 'move', 'add'):
            for w in words[i + 2:]:
                t = w.literal()
                if t is not None and t.startswith('-'):
                    continue
                check_target(w, st, destructive=args[0] != 'add', what='git worktree ' + args[0])
                if args[0] == 'add':
                    note_new_repo(w, st)
                    break
        return
    elif sub in ('clone', 'init'):
        pos = [w for w in words[i + 1:] if not (w.literal() or '').startswith('-')]
        if pos:
            check_target(pos[-1], st, what='git ' + sub)
            note_new_repo(pos[-1], st)
        return
    if not writes:
        return
    if unknown or (gcwd is None and gitdir is None and worktree is None):
        st.unknown.append('git ' + sub)
        return
    try:
        target = None
        if worktree is not None:
            target = worktree
        elif gitdir is not None:
            g = os.path.normpath(gitdir)
            target = os.path.dirname(g) if os.path.basename(g).casefold() == '.git' else g
        else:
            if not os.path.isdir(gcwd):
                # created by this same command (worktree add, clone, scripts/worktree-add.sh, mkdir): a new repo
                # unless it sits directly in the prod root or in a protected directory (then it is the prod repo)
                g = fold(gcwd)
                if any(g == r or g.startswith(r + '/') for r in st.new_repos):
                    return
                anc = gcwd
                for _ in range(256):
                    if os.path.isdir(anc) or os.path.dirname(anc) == anc:
                        break
                    anc = os.path.dirname(anc)
                if fold(anc) == st.prod.cf or st.prod.classify(anc) == 'protected':
                    st.deny.append('git %s a prod-fában létrehozott mappában (%s)' % (sub, TREE_WRITERS_MSG))
                return
            target = find_repo(gcwd)
        if target is None:
            return
        tf = st.prod.cf
        forms = (fold(target), fold(os.path.realpath(target)))
        if any(f == tf or st.prod.kind_of(f) == 'protected' for f in forms):
            st.deny.append('git %s a prod-fa munkafáján (%s)' % (sub, TREE_WRITERS_MSG))
    except ResolveError as e:
        st.errors.append('git útfeloldás (%s)' % e)
    except Exception as e:
        st.errors.append('git útfeloldás (%s)' % type(e).__name__)


def mark_prod_cwd(st, p):
    if p is None:
        return
    try:
        if fold(p) == st.prod.cf or st.prod.classify(p) == 'protected':
            st.prod_cwd = True
    except ResolveError:
        st.prod_cwd = True


def note_new_repo(w, st):
    kind, p = word_path(w, st)
    if kind == 'path':
        try:
            st.new_repos.append(fold(p))
        except ResolveError:
            pass


def cwd_writer(st, what):
    if st.cwd is None:
        st.unknown.append(what)
        return
    try:
        k = st.prod.classify(st.cwd)
    except ResolveError as e:
        st.errors.append('útfeloldás (%s)' % e)
        return
    if k == 'protected' or fold(st.cwd) == st.prod.cf:
        st.deny.append('%s a prod-fában fut (cwd), %s' % (what, TREE_WRITERS_MSG))


def analyze_simple(cmd, st, depth):
    words = list(cmd['words'])
    env = {}
    # redirections first (they apply to the shell cwd)
    for op, w, hd in cmd['redirs']:
        if op in ('>', '>>', '>|', '&>', '&>>', '<>'):
            t = w.literal()
            if t in ('/dev/null', '/dev/stdout', '/dev/stderr', '/dev/tty'):
                continue
            check_target(w, st, what='átirányítás')
        elif op == '>&':
            t = w.literal()
            if t is not None and (t.isdigit() or t == '-'):
                continue
            check_target(w, st, what='átirányítás')
    if len(words) >= 2 and words[0].literal() in ('for', 'select') and IDENT.fullmatch(words[1].literal() or ''):
        if len(words) >= 3 and words[2].literal() == 'in':
            st.loops[words[1].literal()] = words[3:53]
        st.vars[words[1].literal()] = None
        return
    while words and words[0].literal() in RESERVED:
        if words[0].literal() == 'function' and len(words) > 1:     # `function NAME [()] { cmd; }`
            words.pop(0)
            words.pop(0)
            continue
        words.pop(0)
    # leading assignments
    while words:
        t = words[0].literal()
        raw = words[0].raw
        m = ASSIGN.match(raw)
        if not m:
            break
        name = m.group(1)
        val = Word(strip_assign(words[0], name), raw[m.end():])
        if len(words) == 1:
            st.vars[name] = assign_value(val, st)
        else:
            v = assign_value(val, st)
            env[name] = v if v is not None else None
        words.pop(0)
    if not words:
        return
    xargs = False
    # wrappers
    for _ in range(8):
        name = base(words[0])
        if name == 'xargs':
            xargs = True
            words = drop_opts(words[1:], ('-I', '-J', '-L', '-n', '-P', '-s', '-E', '-d', '-a'))
        elif name in WRAPPERS:
            rest = words[1:]
            argopts = WRAP_ARG_OPTS.get(name, ())
            while rest:
                t = rest[0].literal()
                if t is None:
                    break
                # `env A=x cmd`, and the bash keyword form `time A=x cmd` (Viktor 42855 L1)
                if name == 'time' and t in ('!', '{'):     # `time ! cmd`, `time { cmd; }`
                    rest = rest[1:]
                    continue
                if name in ('env', 'time') and ASSIGN.match(rest[0].raw):
                    m = ASSIGN.match(rest[0].raw)
                    env[m.group(1)] = assign_value(Word(strip_assign(rest[0], m.group(1)), ''), st)
                    rest = rest[1:]
                    continue
                if name == 'timeout' and re.match(r'^\d', t):
                    rest = rest[1:]
                    break
                if t.startswith('-'):
                    rest = rest[2:] if t in argopts else rest[1:]
                    continue
                break
            words = rest
        else:
            break
        if not words:
            return
    name = base(words[0])
    args = words[1:]
    st.exec_raw.append(words[0].raw)
    if name in INTERPRETERS or name in SHELLS:
        for w in args:
            t = w.literal()
            if t is None or not t.startswith('-'):
                if t is not None:
                    st.exec_raw.append(w.raw)
                break
            if t in ('-c', '-e', '-m') or (name in SHELLS and t.startswith('-') and 'c' in t):
                break
    if name is None:
        if xargs:
            st.unknown.append('xargs ?')
        return
    if name in ('export', 'local', 'declare', 'typeset', 'readonly'):
        for w in args:
            m = ASSIGN.match(w.raw)
            if m:
                st.vars[m.group(1)] = assign_value(Word(strip_assign(w, m.group(1)), ''), st)
        return
    if name in ('cd', 'pushd'):
        a = [w for w in args if not (w.literal() or '').startswith('-')]
        if not a:
            st.cwd = st.home
            return
        kind, p = word_path(a[0], st)
        st.cwd = os.path.normpath(p) if kind == 'path' else None
        if kind == 'dir':
            # only the start is known: a placeholder child of the known directory when that directory is neither
            # protected nor an ancestor of the prod tree (so the unknown part cannot reach a protected path)
            try:
                if st.prod.classify(p) not in ('protected', 'ancestor') and fold(p) != st.prod.cf:
                    st.cwd = os.path.join(p, '.prod-tree-write-gate-unknown')
            except ResolveError:
                st.cwd = None
        mark_prod_cwd(st, st.cwd)
        return
    if name in SHELLS:
        i = 0
        while i < len(args):
            t = args[i].literal()
            if t is None:
                break
            if t == '-c' or (t.startswith('-') and not t.startswith('--') and 'c' in t):
                if i + 1 < len(args):
                    inner = args[i + 1].literal()
                    analyze_text(inner if inner is not None else render(args[i + 1]), st, depth + 1)
                return
            if t.startswith('-'):
                i += 1
                continue
            return    # a script file: the stated boundary
        for op, w, hd in cmd['redirs']:
            if hd is not None:
                analyze_text(hd['body'], st, depth + 1)
        return
    if name == 'eval':
        analyze_text(' '.join(w.literal() if w.literal() is not None else render(w) for w in args), st, depth + 1)
        return
    if name == 'git':
        analyze_git(words, env, st)
        return
    if xargs and (name in ALL_ARGS or name in LAST_ARG or name in ('sed', 'gsed', 'perl', 'dd', 'git')):
        st.unknown.append('xargs ' + name)
    if name in ALL_ARGS:
        opts, pos = split_opts(name, args)
        for w in pos:
            check_target(w, st, destructive=name in DESTRUCTIVE, what=name)
        for k in range(len(opts) - 1):
            if opts[k].literal() in ('-t', '--target-directory') and name in ('mv', 'gmv'):
                check_target(opts[k + 1], st, destructive=True, what=name)
        return
    if name in LAST_ARG:
        opts, pos = split_opts(name, args)
        dest = None
        for k in range(len(opts) - 1):
            if opts[k].literal() in ('-t', '--target-directory'):
                dest = opts[k + 1]
        for o in opts:
            t = o.literal() or ''
            if t.startswith('--target-directory='):
                dest = Word([('lit', t.split('=', 1)[1])], t)
        srcs = pos
        if dest is None and pos:
            dest, srcs = pos[-1], pos[:-1]
        if dest is None:
            return
        if name in ('scp', 'rsync') and ':' in (dest.literal() or '').split('/')[0]:
            return
        if name in ('install', 'ginstall') and any(o.literal() == '-d' for o in opts):
            for w in pos:
                check_target(w, st, what=name + ' -d')
            return
        check_target(dest, st, destructive=name in ('rsync',) and any(
            (o.literal() or '').startswith('--delete') for o in opts), what=name)
        dk, dp = word_path(dest, st)
        if dk == 'path':
            for s_ in srcs:
                sl = s_.literal()
                if sl:
                    bn = os.path.basename(sl.rstrip('/'))
                    if bn:
                        check_target(Word([('lit', os.path.join(dp, bn))], dest.raw + '/' + bn), st, what=name)
        return
    if name in ('sed', 'gsed', 'perl'):
        lt = lits(args)
        inplace = any(t is not None and (t.startswith('--in-place') or (t.startswith('-') and not t.startswith('--')
                                                                           and 'i' in t)) for t in lt)
        if not inplace:
            return
        script_given = any(t in ('-e', '-E', '-f', '--expression', '--file') or
                           (t is not None and t.startswith('-') and not t.startswith('--') and t[-1:] in 'eEf'
                            and len(t) > 2) for t in lt)
        pos, skip = [], False
        for k, w in enumerate(args):
            t = w.literal()
            if skip:
                skip = False
                continue
            if t == '':
                continue
            if t is not None and t.startswith('-') and t != '-':
                if t in ('-e', '-E', '-f', '--expression', '--file') or (
                        not t.startswith('--') and len(t) > 2 and t[-1] in 'eEf'):
                    skip = True
                continue
            pos.append(w)
        if not script_given and pos and name != 'perl':
            pos = pos[1:]
        for w in pos:
            check_target(w, st, what=name + ' -i')
        return
    if name == 'dd':
        for w in args:
            t = w.raw
            if t.startswith('of='):
                check_target(Word(strip_prefix(w, 3), t[3:]), st, what='dd of=')
        return
    if name in ('curl', 'wget'):
        for k, w in enumerate(args):
            t = w.literal() or ''
            if t in ('-o', '--output', '-O', '--output-document', '-P', '--directory-prefix', '--output-dir') \
                    and k + 1 < len(args) and not (name == 'curl' and t == '-O'):
                check_target(args[k + 1], st, what=name)
            elif t.startswith('--output=') or t.startswith('--output-document='):
                check_target(Word([('lit', t.split('=', 1)[1])], t), st, what=name)
        return
    if name == 'find':
        lt = lits(args)
        writes = any(t in ('-delete', '-fprint', '-fprintf', '-fls') for t in lt)
        for k, t in enumerate(lt):
            if t in ('-exec', '-execdir', '-ok', '-okdir') and k + 1 < len(lt):
                ex = os.path.basename(lt[k + 1]) if lt[k + 1] else None
                rest = lt[k + 2:]
                if ex is None or ex in ALL_ARGS or ex in LAST_ARG or ex in SHELLS or ex in (
                        'dd', 'git', 'patch', 'xargs', 'install') or (
                        ex in ('sed', 'gsed', 'perl') and any(x and x.startswith('-') and 'i' in x for x in rest)):
                    writes = True
        if writes:
            starts = []
            for w in args:
                t = w.literal()
                if t is not None and (t.startswith('-') or t in ('(', '!', ')')):
                    break
                starts.append(w)
            if not starts:
                starts = [Word([('lit', '.')], '.')]
            for w in starts:
                check_target(w, st, destructive=True, what='find -delete/-exec')
        return
    if name in PKG:
        lt, skip = [], False
        for t in lits(args):
            if skip:
                skip = False
            elif t in ('--prefix', '-C', '--cwd', '--dir', '-w', '--workspace', '--filter'):
                skip = True
            elif t is not None and not t.startswith('-'):
                lt.append(t)
        if lt and lt[0] in PKG_WRITE:
            pfx = None
            for k, w in enumerate(args):
                if w.literal() in ('--prefix', '-C', '--cwd', '--dir') and k + 1 < len(args):
                    pfx = args[k + 1]
            if pfx is not None:
                kind, p = word_path(pfx, st)
                saved = st.cwd
                st.cwd = p if kind == 'path' else None
                cwd_writer(st, name + ' ' + lt[0])
                st.cwd = saved
            else:
                cwd_writer(st, name + ' ' + lt[0])
        return
    if name == 'patch':
        opts, pos = split_opts(name, args)
        for w in pos:
            check_target(w, st, what='patch')
        ddir = None
        for k in range(len(opts) - 1):
            if opts[k].literal() == '-d':
                ddir = opts[k + 1]
        if ddir is not None:
            kind, p = word_path(ddir, st)
            saved = st.cwd
            st.cwd = p if kind == 'path' else None
            cwd_writer(st, 'patch -d')
            st.cwd = saved
        else:
            cwd_writer(st, 'patch')
        return
    if name in ('tar', 'gtar', 'bsdtar'):
        lt = [t or '' for t in lits(args)]
        if lt and (re.match(r'^-?[A-Za-z]*x', lt[0]) or '--extract' in lt or '-x' in lt):
            cdir = None
            for k, t in enumerate(lt):
                if t in ('-C', '--directory') and k + 1 < len(args):
                    cdir = args[k + 1]
            if cdir is not None:
                check_target(cdir, st, what='tar -x -C')
            else:
                cwd_writer(st, 'tar -x')
        return
    if name == 'unzip':
        lt = lits(args)
        for k, t in enumerate(lt):
            if t == '-d' and k + 1 < len(args):
                check_target(args[k + 1], st, what='unzip -d')
                return
        if not any(t in ('-l', '-t', '-v', '-p', '-Z') for t in lt):
            cwd_writer(st, 'unzip')
        return


def strip_prefix(w, n):
    parts = list(w.parts)
    if parts and parts[0][0] == 'lit':
        parts[0] = ('lit', parts[0][1][n:])
    return parts


def strip_assign(w, name):
    parts = list(w.parts)
    if parts and parts[0][0] == 'lit':
        t = parts[0][1]
        k = t.find('=')
        parts[0] = ('lit', t[k + 1:])
        if parts[0][1] == '' and len(parts) > 1:
            parts.pop(0)
    return parts


def assign_value(w, st):
    """the literal value of an assignment, a safe placeholder for $(mktemp ...), else None (unknown)."""
    if len(w.parts) == 1 and w.parts[0][0] == 'sub' and w.parts[0][1].strip().startswith('mktemp'):
        return '/private/tmp/prod-tree-write-gate-mktemp'
    kind, p = word_path(w, st)
    if kind == 'path':
        return p
    if kind == 'dir':
        pre = p.rstrip('/') + '/' + st.partial
        return ('prefix', pre)
    t = w.literal()
    return t if t is not None and '/' not in t else None


def render(w):
    """source text equivalent of an expanded word, for a nested analysis (vars stay references)"""
    out = []
    for k, t in w.parts:
        if k == 'lit':
            out.append(t)
        elif k in ('var', 'varcut'):
            out.append('${%s}' % t)
        elif k == 'sub':
            out.append('$(%s)' % t)
        elif k == 'tilde':
            out.append('~' + t)
        elif k == 'glob':
            out.append(t if t in '*?[' else '*')
        else:
            out.append('${__prod_tree_write_gate_unknown}')
    return ''.join(out)


def base(w):
    t = w.literal()
    if t is None:
        return None
    return os.path.basename(t) or t


def drop_opts(words, argopts):
    i = 0
    while i < len(words):
        t = words[i].literal()
        if t is None or not t.startswith('-'):
            break
        i += 2 if t in argopts else 1
    return words[i:]


def analyze_text(text, st, depth):
    if depth > MAX_DEPTH:
        st.errors.append('túl mély beágyazás')
        return
    try:
        toks, subs = lex(text)
    except LexError as e:
        st.errors.append('lexer: %s' % e)
        return
    for sub in subs:
        saved = st.cwd
        analyze_text(sub, st, depth + 1)
        st.cwd = saved
    for cmd in commands(toks):
        analyze_simple(cmd, st, depth)


# ---------------------------------------------------------------- raw-text rule (K2, 1a)

def raw_protected(text, prod, home, cwd, bare_root=True):
    """True when the casefolded raw text names a protected path in any form (bare_root: the prod root alone counts
    too; after a successful analysis it does not, because a cd/-C into the prod root is tracked in State instead)."""
    low = text.casefold()
    roots = [re.escape(prod.cf), re.escape(FIRMLINK + prod.cf)]
    if home:
        hf = home.casefold().rstrip('/')
        if prod.cf.startswith(hf + '/'):
            rel = re.escape(prod.cf[len(hf) + 1:])
            roots += [r'~/' + rel, r'\$home/' + rel, r'\$\{home\}/' + rel, r'~' + re.escape(os.path.basename(hf))
                      + '/' + rel]
    end = r'(?=$|[\s\'"`;&|)<>/])'
    prot = r'(?:scripts|src|\.claude)' + end + r'|(?:claude\.md|\.mcp\.json|package\.json|package-lock\.json|' \
           r'store/autonomy-config\.json)(?=$|[\s\'"`;&|)<>])'
    root = r'(?:' + '|'.join(roots) + r')'
    # closers between the root and the protected part: the root yielded by a substitution or a quoted piece,
    # e.g. "$(echo P)"/scripts/x (Viktor 42855 L3)
    pat = root + r'(?:[)"\'`]*/+(?:\./)*(?:' + prot + r')|/[^\s\'"]*\.\.' + \
        (r'|/*(?=$|[\s\'"`;&|)<>])' if bare_root else '') + ')'
    if re.search(pat, low):
        return True
    if cwd:
        try:
            k = prod.classify(cwd)
        except ResolveError:
            return True
        if k == 'protected':
            return True
        if k in ('inside', 'ancestor') or fold(cwd) == prod.cf:
            if fold(cwd) == prod.cf and re.search(r'(?:^|[\s\'"`=:(;&|<>])(?:\./)*(?:' + prot + r')', low):
                return True
            if re.search(r'\.\./(?:\.\./)*(?:\./)*(?:' + prot + r')', low):
                return True
            # Viktor 42855 L3, narrowed by the E1 replay (any substitution/variable anywhere in the prod repo gave 4
            # false denies in 14 days: every agent home agents/<name> is inside the prod repo): with the cwd anywhere
            # in the prod repo (not a worktree) only `git rev-parse --show-toplevel`, which yields the prod root there
            # (the `git` word itself may already be blanked out of the text as an executed command word).
            # (cwd = the prod root itself is already strict: decide() counts st.prod_cwd as a raw match.)
            try:
                repo = find_repo(cwd)
            except Exception:
                repo = None
            if repo is not None and fold(repo) == prod.cf and re.search(
                    r'(?:\$\(|`)[^)`]*rev-parse\s+--show-toplevel\s*(?:\)|`)["\']?/+(?:\./)*(?:'
                    + prot + r')', low):
                return True
    return False


# ---------------------------------------------------------------- decision

def identify(tp, prod):
    """-> 'main' | 'unknown' | sub-agent name (from the transcript path)."""
    if not isinstance(tp, str) or not tp:
        return 'unknown'
    forms = []
    try:
        forms.append(fold(tp))
    except ResolveError:
        return 'unknown'
    try:
        forms.append(fold(os.path.realpath(tp)))
    except Exception:
        pass
    pre = prod.cf + '/agents/'
    for f in forms:
        if f.startswith(pre):
            name, _, tail = f[len(pre):].partition('/')
            if name and tail.startswith('.claude-config/') and re.fullmatch(r'[a-z0-9._-]{1,64}', name):
                return name
    return 'main'


def decide(payload, prod_root=PROD, home=None):
    """-> (decision 'deny'|'allow', reason, error_flag). Pure apart from realpath/lstat; never decides on identity."""
    prod = Prod(prod_root)
    home = home_dir() if home is None else home
    if not isinstance(payload, dict):
        return ('allow', 'a bemenet nem JSON-objektum', True)
    tool = payload.get('tool_name')
    inp = payload.get('tool_input')
    cwd = payload.get('cwd')
    if not (isinstance(cwd, str) and cwd.startswith('/') and '\x00' not in cwd and len(cwd) <= MAX_PATH):
        cwd = None
    if tool in WRITE_TOOLS:
        fp = inp.get(WRITE_TOOLS[tool]) if isinstance(inp, dict) else None
        if not isinstance(fp, str) or not fp:
            return ('deny', '%s: hiányzó vagy hibás útvonal (fail-closed)' % tool, True)
        if not fp.startswith('/'):
            if cwd is None:
                return ('deny', '%s: relatív út cwd nélkül (fail-closed)' % tool, True)
            fp = os.path.join(cwd, fp)
        try:
            k = prod.classify(fp)
        except ResolveError as e:
            return ('deny', '%s: az út nem oldható fel (%s), fail-closed' % (tool, e), True)
        if k == 'protected':
            return ('deny', '%s a védett útra: %s' % (tool, fp[:160]), False)
        return ('allow', '', False)
    if tool != 'Bash':
        return ('allow', '', False)
    cmd = inp.get('command') if isinstance(inp, dict) else None
    if not isinstance(cmd, str):
        return ('allow', 'Bash: hiányzó parancs', True)
    rawp = raw_protected(cmd[:MAX_CMD * 2], prod, home, cwd)
    if len(cmd) > MAX_CMD:
        if rawp:
            return ('deny', 'túl hosszú parancs, és a védett prod-utat említi', True)
        return ('allow', 'túl hosszú parancs, csak a nyers-szöveg szabály futott', True)
    st = State(prod, cwd, home)
    mark_prod_cwd(st, cwd)
    analyze_text(cmd, st, 0)
    if rawp and st.exec_raw and not any(e.startswith('lexer') for e in st.errors):
        text = cmd
        for e in sorted(set(st.exec_raw), key=len, reverse=True):
            if len(e) > 2:
                text = text.replace(e, ' ')
        rawp = raw_protected(text, prod, home, cwd, bare_root=False)
    rawp = rawp or st.prod_cwd
    if st.deny:
        return ('deny', st.deny[0], False)
    if st.errors:
        if rawp:
            return ('deny', '%s, és a parancs a védett prod-utat említi' % st.errors[0], True)
        return ('allow', st.errors[0], True)
    if st.unknown:
        if rawp:
            return ('deny', 'nem feloldható írási cél (%s), és a parancs a védett prod-utat említi'
                    % st.unknown[0][:80], False)
        return ('allow', UNRESOLVED_ALLOW + ' (%s)' % st.unknown[0][:80], False)
    return ('allow', '', False)


# ---------------------------------------------------------------- log, output, entry

_SECRET_PATTERNS = [
    re.compile(r'(?i)(\b(?:bearer|basic)\s+)[A-Za-z0-9+/=_\-\.]{8,}'),
    re.compile(r'(?i)(\b[a-z][a-z0-9+.\-]*://)(?!\$)[^/\s:@]*:(?!\$)[^/\s]+(?=@[^/\s@]*(?:[/\s?#]|$))'),
    re.compile(r'(?i)(\b[a-z][a-z0-9+.\-]*://)[A-Za-z0-9_\-]{20,}(?=@)'),
    re.compile(r'(?i)(--(?:token|password|passwd|api-key|apikey|access-token|auth-token|secret)(?:\s+|=)[\'"]?)'
               r'(?!\$)[^\s\'"]{6,}'),
    re.compile(r'(?i)(\b\w*(?:token|secret|passw(?:or)?d|api[_\-]?key|apikey|auth|credential|_key)[\'"]?\s*[=:]\s*'
               r'[\'"]?)(?!\$)[^\s,\'";&|]{6,}'),
    re.compile(r'\b(ghp_|gho_|ghs_|ghu_|ghr_|github_pat_|sbp_|sk-ant-|sk-|xoxb-|xoxp-|xapp-|sk_live_|sk_test_|'
               r'rk_live_|rk_test_|whsec_)[A-Za-z0-9_\-]{10,}'),
    re.compile(r'(\b(?:bot)?\d{6,12}:)[A-Za-z0-9_\-]{30,}'),
    re.compile(r'\b(AKIA|ASIA)[A-Z0-9]{16}\b'),
    re.compile(r'(\bsshpass\s+-p\s*)(?:\'[^\']*\'|"(?!\$)[^"]*"|(?!\$)[^\s\'"]+)'),
    re.compile(r'(\b(?:mysql|mysqldump|mariadb)\b[^|;&\n]*?\s-p[\'"]?)(?!\$)[^\s\'"]{4,}'),
    re.compile(r'\beyJ[\w\-]{8,}\.eyJ[\w\-]{8,}\.[\w\-]{8,}'),
    re.compile(r'\b[0-9a-fA-F]{32,}\b'),
]


def redact(text):
    text = text[:LOG_INPUT * 2]
    for pat in _SECRET_PATTERNS:
        if pat.groups:
            text = pat.sub(lambda m: (m.group(1) if m.lastindex and m.lastindex >= 1 else '') + '[REDACTED]', text)
        else:
            text = pat.sub('[REDACTED]', text)
    return text[:LOG_INPUT]


def log_line(log_dir, row):
    try:
        data = (json.dumps(row, ensure_ascii=False) + '\n').encode('utf-8', 'replace')
        if len(data) > 1500:
            row['input'] = row.get('input', '')[:60]
            row['reason'] = row.get('reason', '')[:200]
            data = (json.dumps(row, ensure_ascii=False) + '\n').encode('utf-8', 'replace')
        os.makedirs(log_dir, exist_ok=True)
        fd = os.open(os.path.join(log_dir, 'gate.jsonl'), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    except Exception:
        pass


def mark_seen(log_dir, tp, agent, now):
    try:
        key = hashlib.sha256((tp if isinstance(tp, str) else '').encode('utf-8', 'replace')).hexdigest()[:32]
        os.makedirs(os.path.join(log_dir, 'seen'), exist_ok=True)
        fd = os.open(os.path.join(log_dir, 'seen', key), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        os.close(fd)
    except Exception:
        return
    log_line(log_dir, {'ts': stamp(now), 'agent': agent, 'decision': 'seen'})


def stamp(now):
    try:
        return time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(now))
    except BaseException:
        return str(now)


def input_text(payload):
    try:
        inp = payload.get('tool_input')
        if payload.get('tool_name') == 'Bash':
            return str(inp.get('command', ''))
        if payload.get('tool_name') in WRITE_TOOLS:
            return str(inp.get(WRITE_TOOLS[payload['tool_name']], ''))
    except BaseException:
        pass
    return ''


def deny_json(reason, agent=None):
    hint = DENY_HINT % PROD + ('.' + DENY_HINT_PULZUS if agent == 'pulzus' else '')
    return json.dumps({'hookSpecificOutput': {
        'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
        'permissionDecisionReason': 'prod-tree-write-gate: ' + reason + ' -- ' + hint}},
        ensure_ascii=False) + '\n'


def on_alarm(_sig, _frame):
    raise Deadline()


def run(raw, prod_root=PROD, log_dir=LOG_DIR, home=None, now=None):
    """raw stdin text -> stdout text ('' = allow). Never raises."""
    now = time.time() if now is None else now
    payload, agent, tool, text = None, 'unknown', None, ''
    try:
        prod = Prod(prod_root)
        if len(raw) > MAX_STDIN:
            raise ValueError('stdin too large')
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError('payload not an object')
        tool = payload.get('tool_name')
        text = input_text(payload)
        agent = identify(payload.get('transcript_path'), prod)
        mark_seen(log_dir, payload.get('transcript_path'), agent, now)
        decision, reason, err = decide(payload, prod_root, home)
        try:
            signal.alarm(0)
        except Exception:
            pass
    except BaseException as e:  # Deadline, unexpected error: the fallback rule (1a)
        reason = 'váratlan hiba a kapuban (%s)' % type(e).__name__
        err = True
        decision = 'allow'
        try:
            sub = agent not in ('main', 'unknown')
            if sub and tool in WRITE_TOOLS:
                decision = 'deny'
            elif sub and raw_protected(text[:MAX_CMD], Prod(prod_root), home_dir() if home is None else home,
                                       payload.get('cwd') if isinstance(payload, dict) and
                                       isinstance(payload.get('cwd'), str) else None):
                decision = 'deny'
        except BaseException:
            decision = 'deny' if agent not in ('main', 'unknown') and text and \
                PROD.casefold() in text.casefold() else 'allow'
    gated = agent not in ('main', 'unknown')
    row = {'ts': stamp(now), 'agent': agent, 'tool': tool if isinstance(tool, str) else None,
           'reason': reason, 'input': redact(text)}
    if gated and decision == 'deny':
        row['decision'] = 'deny'
        log_line(log_dir, row)
        return deny_json(reason, agent)
    if decision == 'deny':
        row['decision'] = 'would-deny'
        log_line(log_dir, row)
    elif err and agent != 'main':
        row['decision'] = 'error-allow'
        log_line(log_dir, row)
    elif gated and reason.startswith(UNRESOLVED_ALLOW):
        row['decision'] = 'unresolved-allow'   # Viktor 42855 L2: the allow of an unresolved target leaves a trace
        log_line(log_dir, row)
    return ''


def entry():
    try:
        signal.signal(signal.SIGALRM, on_alarm)
        signal.alarm(DEADLINE_S)
    except BaseException:
        pass
    try:
        raw = sys.stdin.buffer.read(MAX_STDIN + 1).decode('utf-8', 'replace')
    except BaseException:
        raw = ''
    out = run(raw)
    try:
        signal.alarm(0)
    except BaseException:
        pass
    if out:
        try:
            sys.stdout.write(out)
            sys.stdout.flush()
        except BaseException:
            os._exit(2)   # the deny could not be written: exit 2 blocks in Claude Code
    os._exit(0)


if __name__ == '__main__':
    entry()
