#!/usr/bin/env python3
"""zsh-trap-gate.py -- PreToolUse (Bash) gate: the zsh traps the fleet keeps falling into, and rm -r on a bare variable.

WHY (retro 2026-11-13 R6, card cf287c2c; hibanapló 2026-11-12/13): the Bash tool runs zsh, and zsh differs from bash
exactly where an agent writes bash out of habit. A memory note never stopped the repeat; Dave's two private gates
(agents/dave/bin/zsh-wordsplit-gate.py, zsh-modifier-gate.py) did, but only for Dave. This hook carries both to the
whole fleet and adds the two traps of 11-13:
  - `git show "$T:src/..."` ran the :s history modifier, not ref:path (Dave, 3rd time; hibanapló 11-12 07:18).
  - `for spec in ...; do set -- $spec` gave one word, not two: a worktree with a space in its path and a local
    refs/heads/origin/main branch (Dave, 6th time; 11-12 16:43).
  - `HJ="bash heavy-job.sh ..."; $HJ ...` -> "no such file or directory", the checks did not run (Dave, 11-13 17:39;
    Pulzus: `G="..."; $G ...` 11-13 18:12).
  - `echo ===X` -> "==X not found", the greps after it never ran (Viktor, 3x in one session; 11-13 18:03).
  - `rm -rf $S...` on a variable path (Viktor, 2nd time that day; 11-13 18:38).

BLOCKS (exit 2, short Hungarian reason with the fix on stderr). Checks 1-4 run only when the Bash tool's shell is
zsh (CLAUDE_CODE_SHELL, else SHELL; unknown = zsh, the fleet's shell); check 5 runs for every shell.
  1. word splitting: `for x in $V` / `set -- $V` with a bare unquoted $V or ${V} that is NOT an array. A variable
     is an array when this command assigns it as one (V=(...), typeset/local/declare -a, read -A) or it is $@ $*
     $argv. Everything else blocks: a scalar holding whitespace or an expansion (V=$(ls) is ONE word in zsh) and a
     variable this command does not set (it comes from the environment, a string). A literal one-word scalar passes.
  2. variable as command: a word that is only $V / ${V} / "$V" in command position, when this command assigns V a
     scalar with a literal space ("bash x.sh --a"). An array, a one-word value, a $(...) value, or a variable this
     command does not set passes.
  3. history modifier: an unbraced $NAME (or $0-$9) followed by ':' and a letter zsh reads as a modifier (measured
     on zsh 5.9: a A c e h l P q Q r s t u, and gs / g&), unquoted or in double quotes, also in an unquoted heredoc
     body. "${V}:path" passes, and so does ${V:h} (braces = intent); "$B:docs" passes (:d is no modifier, zsh
     leaves it as written).
  4. EQUALS expansion: an argument that starts with an unquoted '=' and has more after it (`echo ===`, `echo =foo`,
     `[ a == b ]`, `test a == b`; also an assignment value `x==y`). A lone `=`, `=(...)` (process substitution),
     a quoted or escaped '=' ("===", '===', \\=), `a=b`, `--opt=val` and anything inside [[ ]] pass.
  5. rm -r on a variable: an rm (also /bin/rm, after sudo/command/env/nohup/.../xargs) with -r/-R/--recursive whose
     operand STARTS with a variable expansion ($S, "$S", ${S}, "$S"/*, $S/x). Empty or misspelt, that removes the
     cwd or /. The ${S:?} / ${S?} guard passes (zsh stops on an empty S), and so does any operand that starts with
     a literal (an absolute /path/$X, ./x). $HOME is not exempt: write the path out.

NOT JUDGED: single-quoted text (so bash -c '...', python -c '...'), quoted-heredoc bodies (<<'EOF'), the body of
any heredoc for checks 1, 2, 4, 5 (it is data, or another interpreter's code), comments. $(...), backticks and
process substitutions are parsed like the main command. A text that merely QUOTES a trap inside double quotes is
not a word, so it passes checks 1, 2, 4, 5 (check 3 still sees it: zsh expands it inside double quotes too).
Scope: an accidental habit, not a deliberate bypass (a trap built by eval, a variable holding the command, or a
script file is not seen).

CONTRACT (hook-exit-code-invariant): exit 2 = block, exit 0 = allow, never exit 1. Malformed stdin, a non-Bash
tool, or an internal error allows (fail OPEN) and the error is recorded in store/hook-errors.log via hook_errlog.
Nesting (card 3b05ae69, the gate-timing probe): $( ), backticks, <( ), =( ) and NAME=( ) nest through parse_seq,
and a double quote nests through read_dq ("$(( "$(( ... : match_paren and read_dq call each other); both count one
shared depth. A command nested deeper than MAX_DEPTH (64; Kernel's 26069 real Bash commands reach 6 at most)
blocks with MSG_DEEP instead of running into Python's recursion limit (about 330 levels, 1 KB of `$(`), which was an
internal error = a silent allow.
Known limits (Viktor 50179, independent probe indep12, all as on main, LOW; each pinned by a KNOWN-LIMIT test
row): read but not as code: bt-escaped-inner-rm, dq-bt-escaped-inner-rm, bt-escaped-inner-for (an escaped inner
backtick), arith-cmdsub-rm, dq-arith-cmdsub-rm, dparen-cmd-arith-cmdsub-rm (a substitution inside arithmetic),
brace-default-cmdsub-rm, dq-brace-default-bt-rm, brace-default-cmdsub-setsplit, dq-brace-default-cmdsub-eq (a
substitution in a ${V:-...} default), dollar-dparen-fallback-rm, dparen-start-subshell-rm (zsh's (( )) command
fallback), dq-case-subst-rm (a case pattern paren in a quoted substitution); not read: bt-heredoc-tail-rm (a
heredoc end inside backticks), dollar-bracket-shift-tail-rm ($[ ... << ] read as a heredoc), and past the
256 KB cut (MAX_COMMAND) the tail is not judged: time-data-heredoc-300k-tail-rm, time-1mb-tail-rm.
Inside a backtick sequence a backtick closes the word it is glued to (`a`b`: before, a glued closing backtick opened
a new nested sequence).
Prefix words (card e6a0f476, Viktor 50227 round 2 LOW/INFO, all as on main): exec -a NAME takes a value; the one word
of env -S / --split-string is read as the command line env runs (inside "..." the shell's backslash escapes are
dropped first), nested up to MAX_SPLIT_DEPTH (3) levels, deeper blocks; sudo -h is --help or -h HOST (the man page
lists both), so the head is looked for both ways and a finding in either counts; a -v / -V among command's options,
also in a cluster (-pv, -vp), only looks the name up and runs nothing.
Round 2 (Viktor 50424 L1-L6, all old): env appends the words after the -S value to it, so the text judged is
`env <value> <rest>` (and the value cut at a word-start #, which ends only the value); a short option cluster whose
last letter takes a value takes the next word (exec -cla x, env -vu FOO, sudo -iu root; a glued -aNAME does not);
env -P altpath takes a value; a quoted option or VAR=x word ("-a", "-S", "FOO=a b") is still one; zsh's `- cmd`
is a prefix word; `set --` after prefix words (noglob, builtin) is check 1 too. Only the first split option of a
command recurses (its text holds the words after it): a 150 KB env -S chain is a few parses, not one per env word.
Round 3 (Viktor 50471 R1, L1-L4, I1): the split value is judged a second time as env reads its escapes (a backslash-c
ends it, backslash-underscore / -t / -n, a tab and a newline separate words; the words after it are still appended);
a prefix word written with a path, quotes or a backslash (/usr/bin/env, "/usr/bin/env", \\env, 'nohup', '-',
/usr/bin/xargs) is the same prefix word (keywords stay unquoted-only); sudo -R / --chroot take a directory; the
ambiguous -h is found anywhere after its prefix word (no window) and also as the last letter of a cluster (-Eh).
Round 4 (Viktor 50541 R1b, L-a..L-d): the split value is also read after zsh's $'..' decoding (ansi_decode: a doubled
backslash, x5c, 134, u005c is the backslash env reads, so backslash-c cuts and backslash-underscore separates); a
real CR, FF and VT separate like a tab; an unquoted =name (zsh EQUALS) and a glob in the last path segment
(/usr/bin/[e]nv, /usr/bin/en?) name the prefix word; macOS arch is a prefix word (-arch, -d, -e take a value).
Overblocks (the safe side): ansi_decode runs on every value, so a single-quoted doubled backslash + c is cut too;
env's own backslash-t puts a tab INTO the word, but the model separates on it.
Tests: python3 -I scripts/hooks/zsh-trap-gate_test.py
"""
import fnmatch
import json
import os
import re
import sys

MAX_COMMAND = 256 * 1024
MAX_DEPTH = 64


class TooDeep(Exception):
    pass
# Measured on zsh 5.9 (`B=main; print "$B:<letter>x/y"` for every letter): these change the value or fail
# ("bad substitution" for :s); every other letter leaves "main:<letter>x/y" as written. :g only with s/& after it.
MODIFIER_RX = re.compile(r'(?<![\\$])\$([A-Za-z_][A-Za-z0-9_]*|[0-9])(:(?:[aAcehlPqQrstuW]|g[s&]))')
NAME_RX = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
ASSIGN_RX = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)(\[[^\]]*\])?\+?=')
ARRAY_ASSIGN_RX = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*\+?=$')
BARE_VAR_RX = re.compile(r'^\$(?:([A-Za-z_][A-Za-z0-9_]*)|\{([A-Za-z_][A-Za-z0-9_]*)\})$')
GUARD_RX = re.compile(r'^\$\{[A-Za-z_][A-Za-z0-9_]*:?\?')
ARRAY_SPECIAL = {'@', '*', 'argv', 'path', 'fpath', 'cdpath', 'manpath', 'mailpath', 'pipestatus', 'match',
                 'reply', 'funcstack', 'commands'}
KEYWORDS = {'if', 'then', 'else', 'elif', 'fi', 'do', 'done', 'while', 'until', '!', '{', '}', 'time', 'coproc',
            'esac', 'case'}
XARGS_VALUE_OPTS = {'-I', '-n', '-P', '-L', '-s', '-E', '-d', '-J', '-R', '-a'}
# Viktor 41322 INFO 5: GNU long options whose required value may stand in the next word ("--max-args 1")
XARGS_VALUE_OPTS |= {'--max-args', '--max-procs', '--max-lines', '--max-chars', '--delimiter', '--arg-file',
                     '--process-slot-var'}
# Viktor 41371 INFO 2: BSD xargs -S replsize takes its value in the next word
XARGS_VALUE_OPTS.add('-S')
# The prefix words' options that take the next word as their value (indep12: sudo -u root rm ..., nice -n 10 rm ...)
PRECMD_VALUE_OPTS = {'sudo': {'-u', '-g', '-h', '-p', '-C', '-D', '-U', '-T', '-r', '-t', '--user', '--group', '--host',
                              '--prompt', '--close-from', '--chdir', '--other-user', '--command-timeout', '--role',
                              '--type',
                              # e6a0f476 round 3 (Viktor 50471 L3): -R / --chroot directory (man sudo)
                              '-R', '--chroot'},
                     'nice': {'-n', '--adjustment'},
                     # e6a0f476 round 2 (Viktor 50424 L3): BSD env -P altpath
                     'env': {'-u', '--unset', '-C', '--chdir', '-S', '--split-string', '-P'},
                     'caffeinate': {'-t', '-w'},
                     # e6a0f476 (Viktor 50227 LOW 1): exec -a NAME runs the command under another argv[0]
                     'exec': {'-a'},
                     # e6a0f476 round 4 (Viktor 50541 L-d): man arch; -arch is one single-dash option word
                     'arch': {'-arch', '-d', '-e'}}
# e6a0f476 (Viktor 50227 INFO 2): sudo's -h is --help and -h HOST (the man page lists both and does not say whether a
# separate next word is the host). Not modeled: the head is looked for both ways, and a finding in either counts.
AMBIG_VALUE_OPTS = {'sudo': {'-h'}}
# e6a0f476 (Viktor 50227 LOW 2): env -S / --split-string takes ONE word and splits it into the command line it runs
ENV_SPLIT_OPTS = ('-S', '--split-string')
MAX_SPLIT_DEPTH = 3
# e6a0f476 round 2 (Viktor 50424 L5): zsh's `- cmd` runs cmd with a dash before argv[0] (a precommand modifier)
# e6a0f476 round 4 (Viktor 50541 L-d): macOS arch runs its program (arch -arm64 rm ... runs rm)
PRECMD = {'sudo', 'command', 'builtin', 'exec', 'nocorrect', 'noglob', 'nohup', 'env', 'nice', 'caffeinate', '-',
          'arch'}
PREFIX_NAMES = PRECMD | {'xargs'}
GLOB_CHAR_RX = re.compile(r'[*?\[]')
DECLARERS = {'typeset', 'local', 'declare', 'export', 'readonly', 'integer', 'float'}
OPERATORS = [';;', ';&', ';|', '&&', '||', '|&', '&!', '&|', ';', '|', '&']
REDIRECTS = ['&>>', '&>', '>>', '>|', '>!', '>&', '<&', '<>', '>', '<']


class Word:
    __slots__ = ('parts', 'start', 'end')

    def __init__(self, start):
        self.parts = []   # (kind, text): lit, esc, sq, dq, var, sub, arith, array, procsub
        self.start = start
        self.end = start

    def add(self, kind, text):
        if kind == 'lit' and self.parts and self.parts[-1][0] == 'lit':
            self.parts[-1] = ('lit', self.parts[-1][1] + text)
        else:
            self.parts.append((kind, text))

    def text(self):
        """The word with its quoting removed (expansions kept as written)."""
        return ''.join(t for _, t in self.parts)

    def plain(self):
        """The word if it is one unquoted literal, else None."""
        if len(self.parts) == 1 and self.parts[0][0] == 'lit':
            return self.parts[0][1]
        return None


class Parser:
    def __init__(self, s):
        self.s = s
        self.n = len(s)
        self.blank = []      # (start, end) ranges zsh does not expand (masked for the modifier check)
        self.commands = []   # each: (words, in_double_bracket_flag_list)
        self.depth = 0

    # -- helpers ---------------------------------------------------------------------------------------------
    def match_paren(self, i):
        """s[i] == '('; index after the matching ')' (quote-aware, naive)."""
        s, n, depth = self.s, self.n, 0
        while i < n:
            c = s[i]
            if c == '\\':
                i += 2
                continue
            if c == "'":
                j = s.find("'", i + 1)
                i = n if j < 0 else j + 1
                continue
            if c == '"':
                i = self.read_dq(i, None)
                continue
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        return n

    def match_brace(self, i):
        """s[i] == '{'; index after the matching '}'."""
        s, n, depth = self.s, self.n, 0
        while i < n:
            c = s[i]
            if c == '\\':
                i += 2
                continue
            if c == "'":
                j = s.find("'", i + 1)
                i = n if j < 0 else j + 1
                continue
            if c == '"':
                i = self.read_dq(i, None)
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        return n

    def read_dq(self, i, word):
        """s[i] == '"'; returns index after the closing quote. Parses $(...) and backticks inside.
        Counts as a nesting level: match_paren / match_brace and read_dq call each other ("$(( "$(( ...)."""
        self.depth += 1
        try:
            if self.depth > MAX_DEPTH:
                raise TooDeep()
            return self._read_dq(i, word)
        finally:
            self.depth -= 1

    def _read_dq(self, i, word):
        s, n = self.s, self.n
        j = i + 1
        while j < n and s[j] != '"':
            c = s[j]
            if c == '\\':
                if j + 1 < n and s[j + 1] in '$`"\\\n':
                    self.blank.append((j, j + 2))
                j += 2
                continue
            if s.startswith('$((', j):
                j = self.match_paren(j + 1)
                continue
            if s.startswith('$(', j):
                j = self.parse_seq(j + 2, ')')
                continue
            if s.startswith('${', j):
                j = self.match_brace(j + 1)
                continue
            if c == '`':
                j = self.parse_seq(j + 1, '`')
                continue
            j += 1
        if word is not None:
            word.add('dq', s[i + 1:min(j, n)])
        return min(j + 1, n)

    # -- words -----------------------------------------------------------------------------------------------
    def read_word(self, i, dbl=False, bt=False):
        s, n = self.s, self.n
        w = Word(i)
        if dbl and s.startswith(']]', i):
            w.add('lit', ']]')
            w.end = i + 2
            return w, i + 2
        stop = ' \t\n' if dbl else ' \t\n;&|<>)'
        if bt:
            stop += '`'   # inside a backtick sequence a backtick closes it, it does not open a new one
        while i < n:
            c = s[i]
            if c in stop:
                break
            if c == '(':
                if not w.parts and not dbl:
                    break
                if w.plain() is not None and ARRAY_ASSIGN_RX.match(w.plain()):
                    i = self.parse_seq(i + 1, ')')
                    w.add('array', '(...)')
                    continue
                j = self.match_paren(i)
                w.add('lit', s[i:j])
                i = j
                continue
            if c == '\\':
                if i + 1 < n and s[i + 1] == '\n':
                    i += 2
                    continue
                w.add('esc', s[i + 1:i + 2])
                self.blank.append((i, i + 2))
                i += 2
                continue
            if c == "'":
                j = s.find("'", i + 1)
                j = n if j < 0 else j
                w.add('sq', s[i + 1:j])
                self.blank.append((i + 1, j))
                i = j + 1
                continue
            if c == '$':
                nx = s[i + 1] if i + 1 < n else ''
                if nx == "'":
                    j = i + 2
                    while j < n and s[j] != "'":
                        j += 2 if s[j] == '\\' else 1
                    w.add('sq', s[i + 2:j])
                    self.blank.append((i, min(j + 1, n)))
                    i = j + 1
                    continue
                if nx == '"':
                    i += 1
                    continue
                if s.startswith('$((', i):
                    j = self.match_paren(i + 1)
                    w.add('arith', s[i:j])
                    i = j
                    continue
                if nx == '(':
                    j = self.parse_seq(i + 2, ')')
                    w.add('sub', s[i:j])
                    i = j
                    continue
                if nx == '{':
                    j = self.match_brace(i + 1)
                    w.add('var', s[i:j])
                    i = j
                    continue
                m = NAME_RX.match(s, i + 1)
                if m:
                    w.add('var', '$' + m.group(0))
                    i = m.end()
                    continue
                if nx and nx in '0123456789@*#?$!-':
                    w.add('var', s[i:i + 2])
                    i += 2
                    continue
                w.add('lit', '$')
                i += 1
                continue
            if c == '`':
                j = self.parse_seq(i + 1, '`')
                w.add('sub', s[i:j])
                i = j
                continue
            if c == '"':
                i = self.read_dq(i, w)
                continue
            if c == '=' and not w.parts and s.startswith('=(', i):
                j = self.parse_seq(i + 2, ')')
                w.add('procsub', s[i:j])
                i = j
                continue
            w.add('lit', c)
            i += 1
        w.end = i
        return w, i

    # -- sequences -------------------------------------------------------------------------------------------
    def parse_seq(self, i, term=None):
        """Tokenise from i until the terminator (')' or '`') or the end; returns the index after it.
        Raises TooDeep past MAX_DEPTH nested sequences."""
        self.depth += 1
        try:
            if self.depth > MAX_DEPTH:
                raise TooDeep()
            return self._parse_seq(i, term)
        finally:
            self.depth -= 1

    def _parse_seq(self, i, term=None):
        s, n = self.s, self.n
        bt = term == '`'
        cur, flags = [], []
        pending = []      # heredocs waiting for the next newline: (delimiter, quoted, strip_tabs)
        depth = 0
        dbl = False
        redirect_next = False

        def end_cmd():
            nonlocal cur, flags
            if cur:
                self.commands.append((cur, flags))
            cur, flags = [], []

        while i < n:
            c = s[i]
            if term == '`' and c == '`':
                end_cmd()
                return i + 1
            if term == ')' and c == ')' and depth == 0 and not dbl:
                end_cmd()
                return i + 1
            if c in ' \t':
                i += 1
                continue
            if c == '\\' and i + 1 < n and s[i + 1] == '\n':
                i += 2
                continue
            if c == '\n':
                if not dbl:
                    end_cmd()
                i += 1
                if pending:
                    i = self.read_heredocs(i, pending)
                    pending = []
                continue
            if c == '#':
                j = s.find('\n', i)
                j = n if j < 0 else j
                self.blank.append((i, j))
                i = j
                continue
            if dbl:
                w, i = self.read_word(i, dbl=True, bt=bt)
                if w.text() == ']]':
                    dbl = False
                cur.append(w)
                flags.append(True)
                continue
            if s.startswith('((', i) and not cur:
                i = self.match_paren(i)
                continue
            if c == '(':
                depth += 1
                end_cmd()
                i += 1
                continue
            if c == ')':
                depth = max(0, depth - 1)
                end_cmd()
                i += 1
                continue
            if s.startswith('<(', i) or s.startswith('>(', i):
                j = self.parse_seq(i + 2, ')')
                i = j
                # a process substitution after a redirect IS its target (cat < <(ls)); left pending, the redirect
                # took the next command's first word (indep12 procsub-redirect-then-rm: `; rm -rf $S` lost its rm)
                redirect_next = False
                continue
            if s.startswith('<<<', i):
                redirect_next = True
                i += 3
                continue
            if s.startswith('<<', i):
                strip = s.startswith('<<-', i)
                i += 3 if strip else 2
                while i < n and s[i] in ' \t':
                    i += 1
                w, i = self.read_word(i, bt=bt)
                quoted = any(k in ('sq', 'dq', 'esc') for k, _ in w.parts)
                pending.append((w.text(), quoted, strip))
                continue
            op = next((o for o in REDIRECTS if s.startswith(o, i)), None)
            if op:
                if cur and cur[-1].end == i and (cur[-1].plain() or '').isdigit():
                    cur.pop()
                    flags.pop()
                redirect_next = True
                i += len(op)
                continue
            op = next((o for o in OPERATORS if s.startswith(o, i)), None)
            if op:
                end_cmd()
                i += len(op)
                continue
            w, i = self.read_word(i, bt=bt)
            if redirect_next:
                redirect_next = False
                continue
            if w.end == w.start:      # nothing consumed: never loop forever
                i += 1
                continue
            cur.append(w)
            flags.append(False)
            if w.plain() == '[[' and all(x.plain() in KEYWORDS or ASSIGN_RX.match(x.text())
                                         for x in cur[:-1]):
                dbl = True
        end_cmd()
        return n

    def read_heredocs(self, i, pending):
        s, n = self.s, self.n
        for delim, quoted, strip in pending:
            start = i
            while i < n:
                j = s.find('\n', i)
                j = n if j < 0 else j
                line = s[i:j]
                if (line.lstrip('\t') if strip else line) == delim:
                    if quoted:
                        self.blank.append((start, i))
                    else:
                        self.body_ranges.append((start, i))
                    i = min(j + 1, n)
                    break
                i = j + 1
            else:
                if quoted:
                    self.blank.append((start, n))
                else:
                    self.body_ranges.append((start, n))
        return i

    def run(self):
        self.body_ranges = []
        self.parse_seq(0)
        return self


# -- analysis ----------------------------------------------------------------------------------------------------

def masked_text(p):
    chars = list(p.s)
    for a, b in p.blank:
        for k in range(max(a, 0), min(b, len(chars))):
            if chars[k] != '\n':
                chars[k] = ' '
    return ''.join(chars)


def literal_value(parts):
    """(has_literal_whitespace, is_dynamic) for an assignment value's parts."""
    ws, dyn = False, False
    for kind, text in parts:
        if kind in ('lit', 'esc', 'sq'):
            ws = ws or bool(re.search(r'\s', text))
        elif kind == 'dq':
            ws = ws or bool(re.search(r'\s', re.sub(r'\$\{[^}]*\}|\$\w+|\$\([^)]*\)|`[^`]*`', '', text)))
            dyn = dyn or ('$' in text or '`' in text)
        elif kind in ('var', 'sub', 'arith'):
            dyn = True
    return ws, dyn


def value_parts(word):
    """The parts after NAME= in an assignment word."""
    out, seen = [], False
    for kind, text in word.parts:
        if seen:
            out.append((kind, text))
            continue
        if kind == 'lit' and '=' in text:
            seen = True
            rest = text.split('=', 1)[1]
            if rest:
                out.append(('lit', rest))
        elif kind != 'lit':
            return out
    return out


def collect_assignments(commands):
    info = {}   # name -> set of {'array', 'ws', 'dyn', 'plain'}

    def mark(name, tag):
        info.setdefault(name, set()).add(tag)

    for words, _ in commands:
        k = 0
        while k < len(words) and words[k].plain() in KEYWORDS:
            k += 1
        head = words[k].plain() if k < len(words) else None
        if head in DECLARERS:
            is_array = any((x.plain() or '').startswith('-') and ('a' in x.plain() or 'A' in x.plain())
                           for x in words[k + 1:])
            for x in words[k + 1:]:
                m = ASSIGN_RX.match(x.text())
                if m:
                    vp = value_parts(x)
                    if any(kind == 'array' for kind, _ in x.parts) or is_array:
                        mark(m.group(1), 'array')
                    else:
                        ws, dyn = literal_value(vp)
                        mark(m.group(1), 'ws' if ws else 'dyn' if dyn else 'plain')
                elif is_array and x.plain() and NAME_RX.fullmatch(x.plain()):
                    mark(x.plain(), 'array')
            continue
        if head == 'read':
            arr = any((x.plain() or '').startswith('-') and 'A' in x.plain() for x in words[k + 1:])
            for x in words[k + 1:]:
                if x.plain() and NAME_RX.fullmatch(x.plain()):
                    mark(x.plain(), 'array' if arr else 'dyn')
            continue
        if head in ('for', 'select') and k + 1 < len(words):
            # the loop variable holds one item per round: a scalar, dynamic
            nm = words[k + 1].plain()
            if nm and NAME_RX.fullmatch(nm):
                mark(nm, 'dyn')
        while k < len(words):
            m = ASSIGN_RX.match(words[k].text()) if words[k].parts and words[k].parts[0][0] == 'lit' else None
            if not m:
                break
            x = words[k]
            if any(kind == 'array' for kind, _ in x.parts):
                mark(m.group(1), 'array')
            else:
                ws, dyn = literal_value(value_parts(x))
                mark(m.group(1), 'ws' if ws else 'dyn' if dyn else 'plain')
            k += 1
    return info


def bare_var(word, allow_dq):
    """NAME if the word is only $NAME / ${NAME} (unquoted, or "$NAME" when allow_dq), else None."""
    if len(word.parts) != 1:
        return None
    kind, text = word.parts[0]
    if kind == 'var' or (allow_dq and kind == 'dq'):
        m = BARE_VAR_RX.match(text)
        if m:
            return m.group(1) or m.group(2)
    return None


def starts_with_var(word):
    """The leading variable expansion text of a word ($S, ${S}, from "$S/x" too), else None."""
    if not word.parts:
        return None
    kind, text = word.parts[0]
    if kind == 'var':
        return text
    if kind == 'lit':
        # zsh's unbraced flag forms ($=V split, $~V glob, $^V rc-expand) are parsed as a literal (indep12
        # rm-eqsplit-unbraced: rm -rf $=D/cache)
        m = re.match(r'\$[=~^]+[A-Za-z_][A-Za-z0-9_]*', text)
        if m:
            return m.group(0)
    if kind == 'dq':
        m = re.match(r'\$(?:\{[^}]*\}|[A-Za-z_][A-Za-z0-9_]*|[0-9@*])', text)
        if m:
            return m.group(0)
    return None


def frag(word, s):
    return s[word.start:word.end][:120]


MSG_SPLIT = ('ZSH-CSAPDA (szóbontás): {f!r} -- a zsh egy sima változót NEM bont szavakra, a ciklus/set -- egyetlen '
             'elemet kap. Írd tömbbel (L=(a b c); for x in $L), ${{=L}}-lel, kiírt szavakkal, vagy bash -c \'...\'-ben.')
MSG_CMDVAR = ('ZSH-CSAPDA (változó mint parancs): {f!r} -- a zsh a szóközös értéket EGY parancsnévnek veszi '
              '("no such file or directory"). Írd tömbbel (X=(bash heavy-job.sh --a); $X ...), függvénnyel, '
              'vagy írd ki a parancsot.')
MSG_MOD = ('ZSH-CSAPDA (modifier): {f!r} -- zsh-ban a $VAR: utáni betű history modifier (:s :a :h :t ...), nem '
           'ref:út ("bad substitution" vagy elrontott út). Írd "${{VAR}}:út" alakban.')
MSG_EQ = ('ZSH-CSAPDA (=-kibontás): {f!r} -- a zsh az =-jellel kezdődő szót parancsnévként oldja fel ("{nf} not '
          'found"), a parancs és ami utána jön NEM fut le. Elválasztónak idézve: echo "=== X ===" vagy echo \'--- X\'; '
          'összehasonlításra [ a = b ] vagy [[ a == b ]].')
MSG_DEEP = ('ZSH-CSAPDA (mélység): a parancs {d}-nél több elemzési szinten ágyaz egymásba $( ), backtick, <( ), =( ) '
            'vagy idézőjeles részt (egy idézőjelen belüli $( ) két szintnek számít); a kapu ennyit nem elemez végig (a valódi parancsok néhány szintet használnak). Bontsd '
            'lépésekre vagy írd szkriptfájlba.')
MSG_SPLIT_DEEP = ('ZSH-CSAPDA (mélység): az env -S / --split-string {d}-nél több szinten ágyaz egymásba (az értéke maga '
                  'is env -S); a kapu ennyit nem elemez végig. Bontsd lépésekre vagy írd szkriptfájlba.')
MSG_RM = ('RM-VALTOZO-KAPU: {f!r} -- rm -r változóval kezdődő úton: üres vagy elírt változónál a cwd vagy a / törlődik. '
          'Írd: rm -rf -- "${{S:?}}/alut" (a :? megáll, ha S üres), vagy kiírt abszolút úttal.')


def shell_is_zsh(env):
    sh = env.get('CLAUDE_CODE_SHELL') or env.get('SHELL') or ''
    base = os.path.basename(sh.strip())
    return base == '' or 'zsh' in base


def prefix_name(word):
    """The name of a prefix word (PRECMD or xargs) also when it is written with a path or quoted (e6a0f476 round 3,
    Viktor 50471 L2: /usr/bin/env, /usr/bin/nice, \\env, 'nohup' ran the rm unseen), else word.plain(). Only words of
    literal / quoted / escaped parts (no expansion); zsh reads a quoted or escaped `-` as the modifier too (measured:
    zsh -f -c "'-' echo hi" prints hi). Keywords are not resolved here: a quoted `if` is no keyword (the callers keep
    plain() for KEYWORDS)."""
    p = word.plain()
    if p is not None and '/' not in p:
        # e6a0f476 round 4 (Viktor 50541 L-c): zsh EQUALS expands an unquoted =name to the command's path
        return p[1:] if p.startswith('=') and p[1:] in PREFIX_NAMES else p
    if not word.parts or not all(k in ('lit', 'sq', 'dq', 'esc') for k, _ in word.parts):
        return p
    b = shell_text(word).rsplit('/', 1)[-1]
    if b in PREFIX_NAMES:
        return b
    # e6a0f476 round 4 (Viktor 50541 L-c): an unquoted glob in the last path segment matches the file it names
    # (/usr/bin/[e]nv, /usr/bin/en? run /usr/bin/env); a prefix name it matches counts (at worst an overblock)
    if p is not None and len(b) <= 64 and GLOB_CHAR_RX.search(b):
        for n in sorted(PREFIX_NAMES):
            if fnmatch.fnmatchcase(n, b):
                return n
    return p


def skip_prefix_args(words, j, ambig_value=True):
    """Past a prefix word at j (sudo, nice, env, ..., or a keyword): its options, the value of the ones that take one
    (PRECMD_VALUE_OPTS), and VAR=x words. Returns the index of the next word. ambig_value: whether an option of
    AMBIG_VALUE_OPTS takes the next word too (the caller tries both)."""
    name = prefix_name(words[j])
    vo = PRECMD_VALUE_OPTS.get(name, ())
    amb = AMBIG_VALUE_OPTS.get(name, ())
    j += 1
    while j < len(words):
        t = opt_text(words[j])
        if t is None or not (t.startswith('-') or ASSIGN_RX.match(t)):
            break
        if name == 'env' and env_split_at(t) is not None:
            return len(words)  # env -S: the command is the split value plus the words after it (env_split_texts)
        o = cluster_value_opt(t, vo)
        j += 2 if o and (ambig_value or o not in amb) else 1
    return j


def opt_text(word):
    """An option or VAR=x word as the program sees it (e6a0f476 round 2, Viktor 50424 L4: a quoted "-a" or
    "FOO=a b" is still one; plain() saw only an unquoted literal). None for a word with an expansion that does not
    start with a literal."""
    if not word.parts:
        return None
    if all(k in ('lit', 'sq', 'dq', 'esc') for k, _ in word.parts) or word.parts[0][0] == 'lit':
        return shell_text(word)
    return None


def cluster_value_opt(t, vo):
    """The option of vo that takes the NEXT word as its value in the option word t, else None. A long option counts
    as a whole; a short cluster (-cla, -vu, -iu) is read as getopt reads it (e6a0f476 round 2, Viktor 50424 L2): the
    first letter that takes a value ends the cluster, and it takes the next word only when it is the last letter
    (-aNAME, -uFOO carry it glued)."""
    if t.startswith('--') or t in vo:  # a whole option word first (arch's single-dash -arch)
        return t if t in vo else None
    for k in range(1, len(t)):
        o = '-' + t[k]
        if o in vo:
            return o if k == len(t) - 1 else None
    return None


def env_split_at(t):
    """In env's option word t, the split value glued to it ('' when it is in the next word), else None: -S, a -S
    ending a cluster (-vS) or carrying its value (-Secho, -vSecho), --split-string[=...]. A value letter before the
    S (-uS: S is -u's value) ends the cluster first."""
    if t == '--split-string':
        return ''
    if t.startswith('--split-string='):
        return t[len('--split-string='):]
    if t.startswith('--') or not t.startswith('-'):
        return None
    for k in range(1, len(t)):
        if t[k] == 'S':
            return t[k + 1:]
        if '-' + t[k] in PRECMD_VALUE_OPTS['env']:
            return None
    return None


def set_index(words, flags, k):
    """The index of `set` when it is the command at k, also after prefix words (e6a0f476 round 2, Viktor 50424 L6:
    noglob set -- $V, builtin set -- $V split like a bare set), else None."""
    while k < len(words) and not flags[k] and prefix_name(words[k]) in PRECMD:
        if command_lookup_only(words, k):
            return None
        k = skip_prefix_args(words, k)
    return k if k < len(words) and not flags[k] and words[k].plain() == 'set' else None


def has_ambig_opt(words):
    """Does some prefix word in this command carry an option of AMBIG_VALUE_OPTS after it (then the head is looked for
    both ways)? e6a0f476 round 3 (Viktor 50471 L4, I1): no 40-word window (sudo + 40 x -E + -h hid the -h), and an
    option that ends a cluster counts like a bare one (sudo -Eh: both readings, as for sudo -E -h). One backward walk:
    linear in the number of words."""
    seen = set()   # the prefix names whose ambiguous option stands somewhere to the right
    for w in reversed(words):
        n = prefix_name(w)
        if n in seen:
            return True
        t = opt_text(w)
        if t is not None and t.startswith('-'):
            for name, amb in AMBIG_VALUE_OPTS.items():
                if cluster_value_opt(t, PRECMD_VALUE_OPTS.get(name, ())) in amb:
                    seen.add(name)
    return False


def command_lookup_only(words, j):
    """`command` at j with a -v / -V among its options (also in a cluster: -pv, -vp) only looks the name up and runs
    nothing (e6a0f476, Viktor 50227 INFO 1: only a separate -v / -V counted, command -pv $X overblocked)."""
    if prefix_name(words[j]) != 'command':
        return False
    # an index walk, not words[j + 1:]: the slice copies the whole rest of the command for every `command` word,
    # so a long "command -p command -p ..." chain took quadratic time (e6a0f476 ReDoS round)
    for i in range(j + 1, len(words)):
        o = words[i].plain() or ''
        if o == '--' or not o.startswith('-') or o.startswith('--') or len(o) < 2:
            return False
        if 'v' in o or 'V' in o:
            return True
    return False


DQ_ESC_RX = re.compile(r'\\([$`"\\\n])')


def shell_text(word):
    """The word as the shell hands it to the program: quotes removed, and inside "..." the backslash before $ ` " \\
    or a newline dropped (Word.text() keeps it). An unescaped \\$ reads as an expansion: at worst an overblock."""
    return ''.join(DQ_ESC_RX.sub(r'\1', t) if k == 'dq' else t for k, t in word.parts)


def env_split_texts(words, j, s):
    """The command line the env at j runs when an option splits a word (-S, --split-string, also in a cluster or a
    quoted option word), else []. e6a0f476 round 2 (Viktor 50424 L1): env splits the value into env ARGUMENTS and
    appends the words after it, so `env -S rm -rf $S` runs rm (measured: /usr/bin/env -S 'echo a' b c prints a b c);
    the text judged is `env <value> <the words after it as written>`. A word-start # in the value is a comment that ends
    the VALUE only (measured: /usr/bin/env -S 'echo #' echo hi prints echo hi), so the value cut before it is judged
    too; a # inside the value's quotes stays in the first text. Only the first split option counts: a later one is in
    the words after it, which the recursion reads (one parse per level, not one per env word)."""
    i = j + 1
    while i < len(words):
        t = opt_text(words[i])
        if t is None or not (t.startswith('-') or ASSIGN_RX.match(t)):
            return []
        v = env_split_at(t)
        if v is not None:
            if v == '':
                if i + 1 >= len(words):
                    return []
                v, nxt = shell_text(words[i + 1]), i + 2
            else:
                nxt = i + 1
            rest = s[words[nxt].start:words[-1].end] if nxt < len(words) else ''
            texts = []
            # e6a0f476 round 3 (Viktor 50471 R1, L1): the value as env itself splits it is judged TOO (only added,
            # never instead of the first text): a backslash-c ends the value (measured: /usr/bin/env -S 'echo A\c B'
            # x y prints A x y), and backslash-underscore, a tab or a newline (real, or the backslash-t / -n escape
            # that $'..' leaves raw here) separate words like a space (measured by Viktor: env -S 'echo\_U1').
            for val in dict.fromkeys((v, env_split_model(v), env_split_model(ansi_decode(v)))):
                for t in (val, cut_split_comment(val)):
                    t = 'env ' + t + ' ' + rest
                    if t not in texts:
                        texts.append(t)
            return texts
        i += 2 if cluster_value_opt(t, PRECMD_VALUE_OPTS['env']) else 1
    return []


SPLIT_COMMENT_RX = re.compile(r'(?:^|(?<=\s))#')
SPLIT_ESC_RX = re.compile(r'\\(.)|[\t\n\r\f\v]', re.S)
ANSI_RX = re.compile(r'\\(?:x([0-9A-Fa-f]{1,2})|u([0-9A-Fa-f]{1,4})|U([0-9A-Fa-f]{1,8})|([0-7]{1,3})|(.))', re.S)
ANSI_SIMPLE = {'a': '\a', 'b': '\b', 'e': '\x1b', 'E': '\x1b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t', 'v': '\v'}


def ansi_decode(v):
    """e6a0f476 round 4 (Viktor 50541 R1b, L-b; his prop2 copy): the value as zsh decodes a $'..' word (the lexer keeps
    its body raw as 'sq'), so a backslash written as a doubled backslash, x5c, 134 or u005c reaches the split model as
    the backslash env reads. Only the escapes that can make a backslash or a separator are decoded; a backslash-# and
    a backslash-$ stay for env to read. Applied to every value (an added text: at worst an overblock). Linear."""
    def rep(m):
        h = m.group(1) or m.group(2) or m.group(3)
        if h:
            try:
                return chr(int(h, 16))
            except (ValueError, OverflowError):
                return m.group(0)
        if m.group(4):
            return chr(int(m.group(4), 8))
        e = m.group(5)
        return '\\' if e == '\\' else ANSI_SIMPLE.get(e, m.group(0))
    return ANSI_RX.sub(rep, v)


def cut_split_comment(v):
    """The split value before a word-start # (env reads the rest as a comment), or v when it has none."""
    m = SPLIT_COMMENT_RX.search(v)
    return v[:m.start()] if m else v


def env_split_model(v):
    """The split value as env -S reads its escapes: cut at the first backslash-c, and backslash-underscore,
    backslash-t, backslash-n, a tab and a newline turned into a space. The escapes are read left to right in pairs,
    so a backslash-backslash before a c is a literal backslash, not the cut. Other pairs stay as written. Linear."""
    out, last = [], 0
    for m in SPLIT_ESC_RX.finditer(v):
        out.append(v[last:m.start()])
        last = m.end()
        e = m.group(1)
        if e == 'c':
            return ''.join(out)
        out.append(' ' if e is None or e in '_tn' else m.group(0))
    out.append(v[last:])
    return ''.join(out)


def rm_check(words, k, s, out, amb_v, env, _depth):
    """Check 5 (rm -r on a variable, every shell) from the head search at k on; appends to out."""
    j = k
    while j < len(words):
        pw = words[j].plain()
        pn = prefix_name(words[j])
        if pn == 'xargs':
            # Kernel 41291: "... | xargs rm -rf $S" runs rm too; skip xargs' options (and the value of the ones
            # that take one as a separate word: -I {} -n 1 -P 4 -L 1 -s N -E eof -d c -J x -R n)
            j += 1
            while j < len(words) and (words[j].plain() or '').startswith('-'):
                o = words[j].plain()
                j += 2 if o in XARGS_VALUE_OPTS else 1
            continue
        if pn == 'env':
            texts = env_split_texts(words, j, s)
            if texts and _depth < MAX_SPLIT_DEPTH:
                for v in texts:
                    out.extend(findings(v, env, _depth + 1))
                return  # the split text holds every word after it
            if texts:
                out.append(MSG_SPLIT_DEEP.format(d=MAX_SPLIT_DEPTH))
                return
        if pn == 'command' and command_lookup_only(words, j):
            return
        if pn in PRECMD or pw in KEYWORDS:
            j = skip_prefix_args(words, j, amb_v)
            continue
        break
    # Viktor 41294 LOW 2: "\\rm" (the alias-bypass habit) is rm too: a name of only literal/escaped parts
    cmd = words[j].text() if j < len(words) and all(k in ('lit', 'esc') for k, _ in words[j].parts) else ''
    if j < len(words) and cmd.split('/')[-1] == 'rm':
        args = words[j + 1:]
        recursive, operands, opts_done = False, [], False
        for x in args:
            pw = x.plain()
            if not opts_done and pw == '--':
                opts_done = True
                continue
            if not opts_done and pw and pw.startswith('-') and len(pw) > 1:
                if pw == '--recursive' or (not pw.startswith('--') and re.search('[rR]', pw)):
                    recursive = True
                continue
            operands.append(x)
        if recursive:
            for x in operands:
                v = starts_with_var(x)
                if v and not GUARD_RX.match(v):
                    out.append(MSG_RM.format(f=s[words[j].start:x.end][:120]))
                    break


def findings(command, env=None, _depth=0):
    env = os.environ if env is None else env
    if not isinstance(command, str) or not command.strip():
        return []
    s = command[:MAX_COMMAND]
    try:
        p = Parser(s).run()
    except TooDeep:
        return [MSG_DEEP.format(d=MAX_DEPTH)]
    zsh = shell_is_zsh(env)
    out = []
    assigns = collect_assignments(p.commands)

    for words, flags in p.commands:
        k = 0
        while k < len(words) and not flags[k] and words[k].plain() in KEYWORDS:
            k += 1
        # leading assignments
        while k < len(words) and not flags[k] and words[k].parts and words[k].parts[0][0] == 'lit' \
                and ASSIGN_RX.match(words[k].text()):
            vp = value_parts(words[k])
            if zsh and vp and vp[0][0] == 'lit' and vp[0][1].startswith('=') and len(vp[0][1]) > 1 \
                    and not vp[0][1].startswith('=('):
                out.append(MSG_EQ.format(f=frag(words[k], s), nf=vp[0][1][1:]))
            k += 1
        if k >= len(words) or flags[k]:
            continue
        head_word = words[k]
        head = head_word.plain()

        if zsh:
            # 2. a variable as the command
            name = bare_var(head_word, allow_dq=True)
            if name and 'ws' in assigns.get(name, ()) and 'array' not in assigns.get(name, ()):
                out.append(MSG_CMDVAR.format(f=s[head_word.start:words[min(k + 1, len(words) - 1)].end][:120]))
            # ... also after prefix words (indep12 nohup-cmdvar, command-cmdvar: nohup $HJ, command $G); command -v /
            # -V only looks the name up, it runs nothing
            for amb_v in (True, False) if has_ambig_opt(words) else (True,):
                e2 = k
                while e2 < len(words) and not flags[e2] and prefix_name(words[e2]) in PRECMD:
                    if command_lookup_only(words, e2):
                        e2 = len(words)
                        break
                    e2 = skip_prefix_args(words, e2, amb_v)
                if e2 != k and e2 < len(words) and not flags[e2]:
                    name = bare_var(words[e2], allow_dq=True)
                    if name and 'ws' in assigns.get(name, ()) and 'array' not in assigns.get(name, ()):
                        out.append(MSG_CMDVAR.format(
                            f=s[head_word.start:words[min(e2 + 1, len(words) - 1)].end][:120]))
                        break
            # 1. for x in $V / set -- $V
            items = []
            if head == 'for' and k + 1 < len(words):
                rest = words[k + 1:]
                for idx, x in enumerate(rest):
                    if x.plain() == 'in':
                        items = [y for y in rest[idx + 1:] if y.plain() not in ('do',)]
                        break
            elif set_index(words, flags, k) is not None:
                rest = words[set_index(words, flags, k) + 1:]
                for idx, x in enumerate(rest):
                    if x.plain() == '--':
                        items = rest[idx + 1:]
                        break
            for x in items:
                name = bare_var(x, allow_dq=False)
                if not name or name in ARRAY_SPECIAL:
                    continue
                tags = assigns.get(name, set())
                if 'array' in tags:
                    continue
                if tags and tags <= {'plain'}:
                    continue
                out.append(MSG_SPLIT.format(f=s[head_word.start:x.end][:120]))
                break
            # 4. EQUALS expansion on an argument
            for x, in_dbl in zip(words[k + 1:], flags[k + 1:]):
                if in_dbl or head == '[[':
                    break
                if x.parts and x.parts[0][0] == 'lit':
                    t = x.parts[0][1]
                    if t.startswith('=') and (len(t) > 1 or len(x.parts) > 1) and not t.startswith('=('):
                        nf = (t[1:] + ''.join(tt for _, tt in x.parts[1:]))[:40]
                        out.append(MSG_EQ.format(f=frag(x, s), nf=nf))
                        break

        # 5. rm -r on a variable (every shell); with an ambiguous prefix option (sudo -h) the head is looked for both
        # ways (e6a0f476)
        for amb_v in (True, False) if has_ambig_opt(words) else (True,):
            n_out = len(out)
            rm_check(words, k, s, out, amb_v, env, _depth)
            if len(out) > n_out:
                break

    if zsh:
        masked = masked_text(p)
        m = MODIFIER_RX.search(masked)
        if m:
            a = max(0, m.start() - 10)
            out.append(MSG_MOD.format(f=s[a:m.end() + 20].strip()[:120]))
    # one message per kind, in order
    seen, uniq = set(), []
    for msg in out:
        key = msg.split(':', 1)[0]
        if key not in seen:
            seen.add(key)
            uniq.append(msg)
    return uniq


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
        msgs = findings(ti.get('command'))
    except Exception as ex:  # a crashing gate must not block a Bash call, nor become a silent exit 1
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import hook_errlog
            hook_errlog.report('zsh-trap-gate', 'internal error, allowed', ex)
        except Exception:
            pass
        return 0
    if msgs:
        sys.stderr.write('\n'.join(msgs) + '\n')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
