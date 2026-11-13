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
Tests: python3 -I scripts/hooks/zsh-trap-gate_test.py
"""
import json
import os
import re
import sys

MAX_COMMAND = 256 * 1024
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
PRECMD = {'sudo', 'command', 'builtin', 'exec', 'nocorrect', 'noglob', 'nohup', 'env', 'nice', 'caffeinate'}
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
        """s[i] == '"'; returns index after the closing quote. Parses $(...) and backticks inside."""
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
    def read_word(self, i, dbl=False):
        s, n = self.s, self.n
        w = Word(i)
        if dbl and s.startswith(']]', i):
            w.add('lit', ']]')
            w.end = i + 2
            return w, i + 2
        stop = ' \t\n' if dbl else ' \t\n;&|<>)'
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
        """Tokenise from i until the terminator (')' or '`') or the end; returns the index after it."""
        s, n = self.s, self.n
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
                w, i = self.read_word(i, dbl=True)
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
                w, i = self.read_word(i)
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
            w, i = self.read_word(i)
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
MSG_RM = ('RM-VALTOZO-KAPU: {f!r} -- rm -r változóval kezdődő úton: üres vagy elírt változónál a cwd vagy a / törlődik. '
          'Írd: rm -rf -- "${{S:?}}/alut" (a :? megáll, ha S üres), vagy kiírt abszolút úttal.')


def shell_is_zsh(env):
    sh = env.get('CLAUDE_CODE_SHELL') or env.get('SHELL') or ''
    base = os.path.basename(sh.strip())
    return base == '' or 'zsh' in base


def findings(command, env=None):
    env = os.environ if env is None else env
    if not isinstance(command, str) or not command.strip():
        return []
    s = command[:MAX_COMMAND]
    p = Parser(s).run()
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
            # 1. for x in $V / set -- $V
            items = []
            if head == 'for' and k + 1 < len(words):
                rest = words[k + 1:]
                for idx, x in enumerate(rest):
                    if x.plain() == 'in':
                        items = [y for y in rest[idx + 1:] if y.plain() not in ('do',)]
                        break
            elif head == 'set':
                rest = words[k + 1:]
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

        # 5. rm -r on a variable (every shell)
        j = k
        while j < len(words):
            pw = words[j].plain()
            if pw == 'xargs':
                # Kernel 41291: "... | xargs rm -rf $S" runs rm too; skip xargs' options (and the value of the ones
                # that take one as a separate word: -I {} -n 1 -P 4 -L 1 -s N -E eof -d c -J x -R n)
                j += 1
                while j < len(words) and (words[j].plain() or '').startswith('-'):
                    o = words[j].plain()
                    j += 2 if o in XARGS_VALUE_OPTS else 1
                continue
            if pw in PRECMD or pw in KEYWORDS:
                j += 1
                while j < len(words) and ((words[j].plain() or '').startswith('-')
                                          or (words[j].parts and words[j].parts[0][0] == 'lit'
                                              and ASSIGN_RX.match(words[j].text()))):
                    j += 1
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
