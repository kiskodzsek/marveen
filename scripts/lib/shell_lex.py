"""shell_lex.py -- the Python twin of scripts/lib/shell-lex.mjs (card fae0712e, DREAM 11-15).

ONE shell lexer for the command gates: the JS module serves bash-egress-parser.mjs and schedule-trust.ts, this one
serves keychain-read-gate.py (a Python hook: starting node on every Bash call would cost too much). Both must give the
SAME answer on scripts/lib/shell-lex-golden.json; each side's test checks it, so the two cannot drift apart. The
contract (classes, problems, heredocs, substs, segments, words) is documented once, in shell-lex.mjs; this file keeps
the same names and the same order of decisions, so a change is made in both, side by side.

Indices are code points (a Python str index), as in the JS module (Array.from).
"""

SEP = set(';&|\n')
META = set(' \t\n;&|()<>')
WORD_START_BEFORE = set(' \t\n;&|()<>')
# Viktor 42852 HIGH 3: the closer of $( ), <( ), >( ), $(( )) and a backtick is word text, so a '#' right after it is
# word text too. A plain ( ) subshell and the (( )) command end a word: (true)# is a comment.
WORD_SUBST_KINDS = ('$(', '<(', '>(', '$((', '`')
CLOSE_PAREN_KINDS = ('$(', '(', '<(', '>(')
NO_HEREDOC_KINDS = ('${', '$((', '((')
NO_COMMENT_KINDS = ('${', '$((', '((')


# Viktor 42888 LOW: one retry per such opener re-lexes the whole text, so many of them were quadratic. Past
# MAX_SPLIT_RETRIES every $(( and (( is read as two parentheses at once (its body as commands: a gate sees more).
MAX_SPLIT_RETRIES = 64
# card 09283e90: the $( ) frames that may own a heredoc, per text; past it the text is read the old way (each one costs one more lexing of the text from the frame's start: the bash 3.2 reading, see lex)
MAX_HEREDOC_FRAMES = 8
HEREDOC_FRAME_KINDS = ('$(',)


class _All:
    def __contains__(self, _):
        return True


_ALL = _All()


def lex(text, charge=None, retries_only=False):
    """bash 3.2 reads $(( and (( as arithmetic only while the parentheses inside pair up and the frame ends in )):
    a ')' at depth 0 not followed by ')' makes it a subshell inside ($((a) ) runs a, measured). That opener is then
    read again as two parentheses ('split'); each retry splits one more opener, so it ends.

    Card 09283e90: a heredoc inside $( ) gets its body (bash 5 and zsh read it before the frame's closer). bash 3.2
    finds the closer FIRST, reading the body's lines as code (measured: a body line 'a)' ends the frame there). So the
    outermost $( ) around such a heredoc is lexed once more the bash 3.2 way (bash32: a heredoc in a frame takes no
    body); when the two put a closer at different places, or a frame is not understood, the whole text is read the
    bash 3.2 way and gets the problem 'heredoc-in-subst' (the reading before this card).

    Python only (the keychain gate's budget, card af12091a): charge(n) is called before every pass over n characters,
    the bash 3.2 check's passes too; retries_only: None when a lexing needs more than MAX_SPLIT_RETRIES retries."""
    r = _lex_split(text, False, charge=charge, retries_only=retries_only)
    if r is not None and 'hsub' in r:
        r = _lex_split(text, True, charge=charge, retries_only=retries_only)
    return r


def _lex_split(text, bash32, stop=False, charge=None, retries_only=False):
    split = set()
    cache = {}
    for _ in range(MAX_SPLIT_RETRIES):
        if charge:
            charge(len(text))
        r = _lex_once(text, split, bash32, cache, stop, charge)
        if 'retry' not in r:
            return r
        split.add(r['retry'])
    if retries_only:
        return None
    if charge:
        charge(len(text))
    return _lex_once(text, _ALL, bash32, cache, stop, charge)


def _lex_once(text, split, bash32=False, cache=None, stop=False, charge=None):
    """stop (card 09283e90, the bash 3.2 check): the text starts with a frame; return {'substs': ...} as soon as it
    closes (a check that read to the end of the text made 8 frames 9x slower on a 20 000-char text)."""
    if cache is None:
        cache = {}
    s = text
    n = len(s)
    cls = ['c'] * n
    problems = []
    heredocs = []
    substs = []
    # card 09283e90: a frame's 'lvl' is the frame whose newline reads its heredocs: itself, or for a ( ) subshell its
    # parent's (bash and zsh, measured: cat <<T ; ( echo + newline reads T's body inside the subshell, cat <<T $(echo +
    # newline does not). The pending heredocs of a level are in its 'pend' list; hd_frames counts the frames with one.
    top = {'kind': 'top'}
    top['lvl'] = top
    stack = [top]
    hd_frames = [0]
    # the backtick frames on the stack as (index, frame), innermost last; trimmed when read (an entry whose index is
    # past the stack or holds another frame is gone, and every entry above it). Walking the whole stack per character
    # was quadratic (20 000 open '(' took 35 s; the keychain gate's timing paddings).
    bts = []

    def live_bts():
        while bts:
            k, g = bts[-1]
            if k < len(stack) and stack[k] is g:
                break
            bts.pop()
        return bts

    def at(k):
        return s[k] if 0 <= k < n else ''

    def open_subst(kind, start, inner_start, nested=False):
        sub = {'kind': kind, 'start': start, 'end': n, 'inner': [inner_start, n]}
        substs.append(sub)
        fr = {'kind': kind, 'sub': sub, 'depth': 0, 'nested': nested}
        fr['lvl'] = stack[-1]['lvl'] if kind == '(' else fr
        # an escaped-backtick frame (nested) has no body end of its own: the next escaped backtick closes it, and the
        # outer body's end (its first unescaped backtick) ends it too, as an unterminated frame (bash: echo `a \` b`
        # ; ls runs ls at the top)
        if kind == '`' and not nested:
            # bash 3.2 cuts a backtick body out FIRST: it ends at the first unescaped backtick, whatever quote or
            # $( ) is open inside it (Viktor 42888 HIGH 4: echo `echo '` ; curl runs curl)
            j = inner_start
            while j < n and s[j] != '`':
                j += 2 if s[j] == '\\' else 1
            fr['bodyEnd'] = j
            live_bts().append((len(stack), fr))
        stack.append(fr)

    word_closer = set()  # index of the last char of a closed word substitution (WORD_SUBST_KINDS)

    def close_subst(inner_end, end):
        f = stack.pop()
        f['sub']['inner'][1] = inner_end
        f['sub']['end'] = end
        if f['kind'] in WORD_SUBST_KINDS:
            word_closer.add(end - 1)
        # card 09283e90: a heredoc of this frame still pending gets no body (the frame closed on its operator's line:
        # bash and zsh read nothing, the lines after it are code, measured)
        for h in f.pop('pend', ()):
            h['bodyStart'] = h['bodyEnd'] = h['end'] = inner_end

    def bash32_closer(f):
        """The end of frame f (just closed) when the heredocs in frames take no body (the bash 3.2 reading); -1 if it
        does not close there. ONE such lexing per outermost $( ) (the anchor), from its start to its closer, answers
        for every frame in it (a lexing per frame made 8 nested frames 9x slower); cached per lex() call, the retries
        of the split loop ask again."""
        anchor = next((g for g in stack[1:] if g['kind'] == '$('), f)
        a = anchor['sub']['start']
        if a not in cache:
            r = _lex_split(s[a:], True, True, charge)
            cache[a] = {x['start']: x['end'] for x in r['substs'] if x['inner'][1] < x['end']}  # closed frames only
        rel = cache[a].get(f['sub']['start'] - a)
        return -1 if rel is None else a + rel

    def read_heredoc_bodies(start, todo):
        p = start
        for h in todo:
            h['bodyStart'] = p
            found = False
            while p < n:
                e = p
                while e < n and s[e] != '\n':
                    e += 1
                line = s[p:e]
                if h['stripTabs']:
                    line = line.lstrip('\t')
                if line == h['delim']:
                    h['bodyEnd'] = p
                    for k in range(p, e):
                        cls[k] = 't'
                    if e < n:
                        cls[e] = 't'
                    p = e + 1 if e < n else e
                    h['end'] = p
                    found = True
                    break
                for k in range(p, min(e + 1, n)):
                    cls[k] = 'h' if h['quoted'] else 'u'
                p = e + 1 if e < n else e
            if not found:
                h['bodyEnd'] = n
                h['end'] = n
                problems.append('unterminated-heredoc')
        return p

    def read_delimiter(p):
        delim = ''
        quoted = False
        while p < n and s[p] not in META:
            ch = s[p]
            if ch == '$' and p + 1 < n and s[p + 1] in '"\'':
                # card 70a5fb2a (Viktor): bash 3.2 ends the body at the delimiter's value, measured: $'J' at J,
                # $'J\x41' at JA (ANSI-C), $"J" at J; the $ is not part of it
                if s[p + 1] == '"':
                    p += 1
                    continue
                quoted = True
                e = p + 2
                while e < n and s[e] != "'":
                    e += 2 if s[e] == '\\' and e + 1 < n else 1
                delim += ansi_c(s[p + 2:min(e, n)])
                p = e + 1 if e < n else e
                continue
            if ch == "'":
                quoted = True
                e = p + 1
                while e < n and s[e] != "'":
                    e += 1
                delim += s[p + 1:e]
                p = e + 1 if e < n else e
            elif ch == '"':
                quoted = True
                e = p + 1
                while e < n and s[e] != '"':
                    if s[e] == '\\' and e + 1 < n:
                        e += 1
                    e += 1
                raw = s[p + 1:e]
                out, k = '', 0
                while k < len(raw):  # bash: in "..." a backslash escapes only $ ` " \\ newline
                    if raw[k] == '\\' and k + 1 < len(raw) and raw[k + 1] in '$`"\\\n':
                        out += '' if raw[k + 1] == '\n' else raw[k + 1]
                        k += 2
                    else:
                        out += raw[k]
                        k += 1
                delim += out
                p = e + 1 if e < n else e
            elif ch == '\\' and p + 1 < n:
                quoted = True
                delim += s[p + 1]
                p += 2
            else:
                delim += ch
                p += 1
        return delim, quoted, p

    i = 0
    while i < n:
        # the closing backtick of a backtick body ends every frame opened inside it (not understood: a problem)
        for k, g in reversed(live_bts()):
            if i == g['bodyEnd']:
                while len(stack) - 1 > k:
                    u = stack.pop()
                    problems.append(('unterminated-' if 'sub' in u else 'unterminated-quote-') + u['kind'])
                    if 'sub' in u:
                        u['sub']['inner'][1] = i
                        u['sub']['end'] = i
                break
        f = stack[-1]
        kind = f['kind']
        ch = s[i]
        nx = at(i + 1)

        if kind == "'":
            cls[i] = 'q'
            if ch == "'":
                stack.pop()
            i += 1
            continue
        if kind == "$'":
            cls[i] = 'a'
            if ch == '\\' and i + 1 < n:
                cls[i + 1] = 'a'
                i += 2
                continue
            if ch == "'":
                stack.pop()
            i += 1
            continue
        if kind == '"':
            if ch == '\\' and i + 1 < n and nx in '$`"\\\n':
                cls[i] = cls[i + 1] = 'l' if nx == '\n' else 'e'
                i += 2
                continue
            if ch == '"':
                cls[i] = 'd'
                stack.pop()
                i += 1
                continue
            if ch == '$' and nx == '(':
                if at(i + 2) == '(' and i not in split:
                    cls[i] = cls[i + 1] = cls[i + 2] = 'c'
                    open_subst('$((', i, i + 3)
                    i += 3
                    continue
                cls[i] = cls[i + 1] = 'c'
                open_subst('$(', i, i + 2)
                i += 2
                continue
            if ch == '$' and nx == '{':
                cls[i] = cls[i + 1] = 'c'
                open_subst('${', i, i + 2)
                i += 2
                continue
            if ch == '`':
                cls[i] = 'c'
                open_subst('`', i, i + 1)
                i += 1
                continue
            cls[i] = 'd'
            i += 1
            continue

        # a code frame: top, $(, (, <(, >(, `, $((, ((, ${
        if kind == '`' and ch == '`':
            cls[i] = 'c'
            close_subst(i, i + 1)
            i += 1
            continue
        if kind in ('$((', '(('):
            if ch == '(':
                f['depth'] += 1
                i += 1
                continue
            if ch == ')':
                if f['depth'] > 0:
                    f['depth'] -= 1
                    i += 1
                    continue
                if nx == ')':
                    close_subst(i, i + 2)
                    i += 2
                    continue
                return {'retry': f['sub']['start']}  # Klodel 42854 matrix: $((a) ) and ((a) ) run a
        if kind == '${' and ch == '}':
            close_subst(i, i + 1)
            i += 1
            continue
        if ch == ')' and kind in CLOSE_PAREN_KINDS:
            close_subst(i, i + 1)
            if stop and len(stack) == 1:
                return {'substs': substs}
            # card 09283e90: a frame with a heredoc: bash 3.2 must close it here too, else read the old way (see lex)
            if f.get('hd') and bash32_closer(f) != i + 1:
                return {'hsub': True}
            i += 1
            continue

        # card f7d4ead8 (oracle matrix): inside a backtick an escaped backtick opens a nested command substitution,
        # the next escaped backtick closes it; bash runs the command in it. A third level (\\\`) is not modelled.
        if ch == '\\' and nx == '`' and kind == '`':
            cls[i] = cls[i + 1] = 'c'
            if f.get('nested'):
                close_subst(i, i + 2)
            else:
                open_subst('`', i, i + 2, True)
            i += 2
            continue
        if ch == '\\':
            if i + 1 < n:
                cls[i] = cls[i + 1] = 'l' if nx == '\n' else 'e'
                i += 2
            else:
                cls[i] = 'e'
                i += 1
            continue
        if ch == "'":
            cls[i] = 'q'
            stack.append({'kind': "'"})
            i += 1
            continue
        if ch == '$' and nx == "'":
            cls[i] = cls[i + 1] = 'a'
            stack.append({'kind': "$'"})
            i += 2
            continue
        if ch == '"':
            cls[i] = 'd'
            stack.append({'kind': '"'})
            i += 1
            continue
        if ch == '$' and nx == '"':
            cls[i] = cls[i + 1] = 'd'
            stack.append({'kind': '"'})
            i += 2
            continue
        # Viktor 42794 HIGH 1: inside ${ }, $(( )) and (( )) a '#' is never a comment (bash and zsh, measured)
        if ch == '#' and kind not in NO_COMMENT_KINDS and (i == 0 or (s[i - 1] in WORD_START_BEFORE and cls[i - 1] != 'e' and (i - 1) not in word_closer)):
            # a comment inside a backtick ends at the closing backtick: bash cuts the body out first
            bt_end = min([g['bodyEnd'] for _, g in live_bts()] + [n])
            while i < n and s[i] != '\n' and i != bt_end and not (kind == '`' and s[i] == '`'):
                cls[i] = 'm'
                i += 1
            continue
        if ch == '$' and nx == '(':
            if at(i + 2) == '(' and i not in split:
                open_subst('$((', i, i + 3)
                i += 3
                continue
            open_subst('$(', i, i + 2)
            i += 2
            continue
        if ch == '$' and nx == '{':
            open_subst('${', i, i + 2)
            i += 2
            continue
        if ch == '`':
            open_subst('`', i, i + 1)
            i += 1
            continue
        if ch in '<>' and nx == '(':
            open_subst(ch + '(', i, i + 2)
            i += 2
            continue
        if ch == '(' and kind != '${':
            if nx == '(' and i not in split:
                open_subst('((', i, i + 2)
                i += 2
                continue
            open_subst('(', i, i + 1)
            i += 1
            continue
        if ch == '<' and nx == '<' and at(i + 2) != '<' and kind not in NO_HEREDOC_KINDS:
            p = i + 2
            strip_tabs = at(p) == '-'
            if strip_tabs:
                p += 1
            while p < n and s[p] in ' \t':
                p += 1
            delim, quoted, end = read_delimiter(p)
            if delim == '':
                i = p
                continue
            lvl = f['lvl']
            if lvl is not top:
                if bash32:
                    # the reading before card 09283e90: no body is taken, its lines stay code, a problem
                    problems.append('heredoc-in-subst')
                    i = end
                    continue
                # card 09283e90: a body only in $( ), <( ), >( ) (and a ( ) in them), not in a backtick body (cut
                # out first), at most MAX_HEREDOC_FRAMES frames; else the old reading
                if live_bts() or lvl['kind'] not in HEREDOC_FRAME_KINDS:
                    return {'hsub': True}
                if not lvl.get('hd'):
                    if hd_frames[0] >= MAX_HEREDOC_FRAMES:
                        return {'hsub': True}
                    lvl['hd'] = True
                    hd_frames[0] += 1
            h = {'op': i, 'opEnd': end, 'delim': delim, 'quoted': quoted, 'stripTabs': strip_tabs,
                 'bodyStart': n, 'bodyEnd': n, 'end': n}
            heredocs.append(h)
            lvl.setdefault('pend', []).append(h)
            i = end
            continue
        if ch == '<' and nx == '<' and at(i + 2) == '<':
            i += 3
            continue
        # card 09283e90: a newline reads the heredocs of its own level only (a newline inside $( ), a backtick, <( ),
        # >( ), $(( )), (( )) or ${ } does not read a heredoc pending outside it; bash and zsh, measured)
        if ch == '\n' and f['lvl'].get('pend'):
            i = read_heredoc_bodies(i + 1, f['lvl'].pop('pend'))
            continue
        i += 1
    for k in range(len(stack) - 1, 0, -1):
        f = stack[k]
        if f.get('hd'):
            return {'hsub': True}  # an unterminated frame with a heredoc: not understood, the old reading
        problems.append(('unterminated-' + f['kind']) if 'sub' in f else ('unterminated-quote-' + f['kind']))
    if top.get('pend'):
        read_heredoc_bodies(n, top.pop('pend'))
    c = ''.join(cls)
    return {'cls': c, 'problems': problems, 'heredocs': heredocs, 'substs': substs,
            'segments': segments_of(s, c, substs)}


def _redir_amp(s, cls, p):
    if s[p] != '&':
        return False
    if p > 0 and s[p - 1] in '<>' and cls[p - 1] == 'c':
        return True
    return p + 1 < len(s) and s[p + 1] == '>' and (p == 0 or s[p - 1] != '&')


def segments_of(s, cls, substs):
    """ONE pass with a stack of open frames -- same rules as segmentsOf in shell-lex.mjs (linear in the text plus
    the substitutions)."""
    n = len(s)
    out = []

    def mk(fr, depth):
        return {'fr': fr, 'depth': depth, 'frame': 'top' if fr < 0 else substs[fr]['kind'], 'start': -1, 'last': -1}

    def flush(f):
        if f['start'] >= 0:
            out.append({'start': f['start'], 'end': f['last'] + 1, 'depth': f['depth'], 'frame': f['frame'],
                        'frameAt': f['fr']})
        f['start'] = f['last'] = -1

    stack = [mk(-1, 0)]
    k = 0
    for p in range(n):
        while len(stack) > 1 and p >= substs[stack[-1]['fr']]['end']:
            flush(stack.pop())
        while k < len(substs) and substs[k]['start'] == p:
            y = substs[k]
            parent = stack[-1]
            if y['kind'] not in ('(', '(('):
                if parent['start'] < 0:
                    parent['start'] = y['start']
                parent['last'] = max(parent['last'], y['end'] - 1)
            stack.append(mk(k, len(stack)))
            k += 1
        f = stack[-1]
        if f['fr'] >= 0 and (p < substs[f['fr']]['inner'][0] or p >= substs[f['fr']]['inner'][1]):
            continue
        c = cls[p]
        if c in 'hutm':
            if c != 'm':
                flush(f)
            continue
        if c == 'c' and s[p] in SEP and not _redir_amp(s, cls, p):
            flush(f)
            continue
        if c == 'c' and s[p] in ' \t':
            continue
        if f['start'] < 0:
            f['start'] = p
        f['last'] = max(f['last'], p)
    while stack:
        flush(stack.pop())
    return sorted(out, key=lambda x: (x['start'], x['depth']))


def _is_pair_start(cls, p):
    k = p
    while k - 1 >= 0 and cls[k - 1] == 'e':
        k -= 1
    return (p - k) % 2 == 0


def words(text, lx, seg):
    s = text
    cls = lx['cls']
    out = []
    st = {'cur': None, 'dq': False, 'a': 0, 'esc': False, 'buf': ''}

    def end_a():
        if st['a'] == 2:
            st['cur']['text'] += ansi_c(st['buf'])
        st['a'], st['esc'], st['buf'] = 0, False, ''

    def push():
        if st['cur']:
            end_a()
            out.append(st['cur'])
            st['cur'] = None
        st['dq'] = False

    # the substitutions inside this segment (a char in one is verbatim word text): a sweep, not a scan per char
    subs = lx['substs']
    lo, hi = 0, len(subs)
    while lo < hi:  # substs are in start order
        mid = (lo + hi) // 2
        if subs[mid]['start'] < seg['start']:
            lo = mid + 1
        else:
            hi = mid
    inner = []
    for j in range(lo, len(subs)):
        x = subs[j]
        if x['start'] >= seg['end']:
            break
        if x['end'] <= seg['end'] and not (x['start'] == seg['start'] and x['end'] == seg['end']):
            inner.append(x)
    ix, cover_end = 0, -1
    for p in range(seg['start'], seg['end']):
        c = cls[p]
        ch = s[p]
        while ix < len(inner) and inner[ix]['start'] <= p:
            cover_end = max(cover_end, inner[ix]['end'])
            ix += 1
        in_nested = p < cover_end
        if c == 'c' and not in_nested and ch in ' \t':
            push()
            continue
        if c == 'l':
            continue
        if st['cur'] is None:
            st['cur'] = {'text': '', 'start': p, 'end': p + 1, 'quoted': False, 'expands': False}
        cur = st['cur']
        cur['end'] = p + 1
        if in_nested:
            cur['text'] += ch
            cur['expands'] = True
            continue
        if c == 'a':
            cur['quoted'] = True
            if st['a'] == 0:
                st['a'] = 1
            elif st['a'] == 1:
                st['a'] = 2
            elif st['esc']:
                st['buf'] += ch
                st['esc'] = False
            elif ch == '\\':
                st['buf'] += ch
                st['esc'] = True
            elif ch == "'":
                end_a()
            else:
                st['buf'] += ch
            continue
        if c == 'q':
            cur['quoted'] = True
            if ch != "'":
                cur['text'] += ch
            continue
        if c == 'd':
            cur['quoted'] = True
            if not st['dq']:
                if ch == '"':
                    st['dq'] = True
                continue
            if ch == '"':
                st['dq'] = False
                continue
            cur['text'] += ch
            continue
        if c == 'e':
            cur['quoted'] = True
            if not _is_pair_start(cls, p):
                cur['text'] += ch
            continue
        if ch in '$`' and c == 'c':
            cur['expands'] = True
        cur['text'] += ch
    push()
    return out


ANSI_SIMPLE = {'a': '\x07', 'b': '\b', 'e': '\x1b', 'E': '\x1b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t',
               'v': '\v', '\\': '\\', "'": "'", '"': '"', '?': '?'}
_OCT = set('01234567')
_HEX = set('0123456789abcdefABCDEF')


def _cp(v):
    return '�' if v > 0x10ffff or 0xd800 <= v <= 0xdfff else chr(v)


def ansi_c(raw):
    """The value of the inside of a $'...' -- same rules as ansiC in shell-lex.mjs."""
    r = raw
    out = []
    i = 0
    while i < len(r):
        ch = r[i]
        if ch != '\\' or i + 1 >= len(r):
            out.append(ch)
            i += 1
            continue
        e = r[i + 1]
        if e in ANSI_SIMPLE:
            out.append(ANSI_SIMPLE[e])
            i += 2
            continue
        if e in _OCT:
            j, v = i + 1, ''
            while j < len(r) and len(v) < 3 and r[j] in _OCT:
                v += r[j]
                j += 1
            out.append(_cp(int(v, 8) & 0xff))
            i = j
            continue
        if e in 'xuU':
            mx = 2 if e == 'x' else 4 if e == 'u' else 8
            j, v = i + 2, ''
            while j < len(r) and len(v) < mx and r[j] in _HEX:
                v += r[j]
                j += 1
            if not v:
                out.append('\\' + e)
                i += 2
                continue
            out.append(_cp(int(v, 16)))
            i = j
            continue
        if e == 'c' and i + 2 < len(r):
            out.append(_cp(ord(r[i + 2]) & 0x1f))
            i += 3
            continue
        out.append('\\' + e)
        i += 2
    return ''.join(out)
