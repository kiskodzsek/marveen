"""shell-lex-oracle-gen.py -- a bash oracle for the shared shell lexer (card fae0712e, Viktor 42697 condition 2).

Generates shell commands from pieces that contain MARKER commands (m1, m2, ...), runs each with a real bash in which
every marker is a function that appends its own name to a file, and stores which markers RAN. The lexer tests
(scripts/lib/shell_lex_test.py and src/__tests__/shell-lex.test.ts) then check that the lexer predicts exactly that
set: a marker runs iff it is the command word of a segment in a frame that runs commands. Two lexers agreeing (the
golden file) cannot catch a wrong shared assumption; this can.

    python3 -I scripts/lib/shell-lex-oracle-gen.py            # rewrite scripts/lib/shell-lex-oracle.json (seed 1115)
    python3 -I scripts/lib/shell-lex-oracle-gen.py --check    # regenerate in memory, exit 1 if bash now differs

Only the stub markers, true, echo and cat run; no network, no file outside a temp dir. A case bash rejects with a
syntax error (bash -n) is not stored. The bash version is stored with the cases: CI does not run bash, it checks
the lexers against the stored answers.
"""
import json
import os
import random
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'shell-lex-oracle.json')
SEED = 1115
WANT = 400
BASH = '/bin/bash'


def pieces(rnd, k):
    """One command-ish piece; k() gives the next marker name. Each returns text."""
    m = k
    choices = [
        lambda: m(),                                        # runs
        lambda: 'echo ' + m(),                              # an argument: does not run
        lambda: "echo '" + m() + " ; " + m() + "'",         # single quotes
        lambda: 'echo "x ; ' + m() + '"',                   # double quotes
        lambda: 'echo "x $(' + m() + ')"',                  # runs inside "$( )"
        lambda: 'echo $(' + m() + ')',
        lambda: 'echo `' + m() + '`',
        lambda: '(' + m() + ')',
        lambda: '{ ' + m() + '; }',
        lambda: 'echo a\\; ' + m(),                         # escaped ; : an argument
        lambda: 'true # ' + m() + ' ; ' + m(),              # a comment
        lambda: 'echo a#b ; ' + m(),                        # # inside a word: no comment
        lambda: "echo $'a\\' ; " + m() + "'",               # $'..' with an escaped quote
        lambda: 'X=1 ' + m(),                               # an assignment prefix: runs
        lambda: 'X=$(' + m() + ') ' + m(),                  # both run
        lambda: 'true \\\n ' + m(),                         # continuation: an argument
        lambda: "cat >/dev/null <<'E'\n" + m() + "\nE\n" + m(),        # quoted body: inert; after it: runs
        lambda: "cat >/dev/null <<'E' ; " + m() + "\nx ; " + m() + "\nE",  # the rest of the operator line runs
        lambda: "cat >/dev/null <<-'E'\n\t" + m() + "\n\tE\n" + m(),
        lambda: 'cat >/dev/null <<"E"\n$(' + m() + ')\nE',             # double-quoted delimiter: inert
        lambda: "true <<<'" + m() + "' ; " + m(),           # here-string
        lambda: 'echo ${X:-' + m() + '}',                   # a default word: does not run
        lambda: 'echo ${X:-$(' + m() + ')}',                # runs
        lambda: 'echo $(( 1 << 2 )) ; ' + m(),
        lambda: 'echo "a\\"b ; ' + m() + '"',               # escaped quote inside double quotes
        lambda: "echo 'a'\"b\"" + m(),                      # glued word: an argument
        lambda: 'true && ' + m(),                           # every piece succeeds, so && always goes on
        # Viktor 42794 HIGH 1: a '#' inside ${ } / (( )) is no comment; the 400 cases had no such piece
        lambda: 'echo ${X:- #} ; ' + m(),                   # runs: the } closes, the ; separates
        lambda: 'echo ${X:- a #b} ; ' + m(),
        lambda: '(( 1 #)) ; ' + m(),                        # an arithmetic error, the next command still runs
        lambda: 'echo ${#X} # ' + m(),                      # ${#X} is a length; the # after it is a comment
        lambda: "echo $'a\\'#' ; " + m(),                   # $'..': the escaped quote does not close, # is text
        # Viktor 42834 HIGH 2: a comment inside a backtick ends at the closing backtick
        lambda: 'echo `true # ' + m() + '` ; ' + m(),       # the first marker is comment text, the second runs
        lambda: 'X=`true #`; ' + m(),
        lambda: 'echo "`true # ' + m() + '`" ; ' + m(),
        lambda: "echo `true # it's` ; " + m(),              # an apostrophe in the comment opens no quote
        # Viktor 42852 HIGH 3: a '#' right after a closed $( ), <( ), $(( )) or backtick is word text; after a plain
        # ( ) subshell or the (( )) command it is a comment
        lambda: 'echo $(true)#; ' + m(),                    # runs
        lambda: 'echo `true`#x; ' + m(),                    # runs
        lambda: 'cat <(true)# >/dev/null 2>&1; ' + m(),     # runs (cat fails on the /dev/fd name, the ; goes on)
        lambda: 'echo $((1))#; ' + m(),                     # runs
        lambda: 'X=$(true)#; ' + m(),                       # runs
        lambda: '(true)#; ' + m(),                          # comment text: does not run
        lambda: '((1))#; ' + m(),                           # comment text: does not run
    ]
    return rnd.choice(choices)()


# Klodel 42854 (three HIGHs of one class: a '#' misread in or after a frame): every frame x the characters a gate
# splits on (# ; | & newline) x {inside the frame, right after its closer}. Deterministic, every cell has a case;
# a cell bash rejects as a syntax error is kept with 'syntax': true (the gate-level test still uses what ran).
# Viktor 42888 HIGH 4 (an unterminated quote inside a backtick body): the two quotes are matrix characters too
MATRIX_CHARS = ['#', ';', '|', '&', '\n', "'", '"']
CODE_FRAMES = {  # frame -> (open, close): the inside runs commands
    'top': ('', ''), '$(': ('echo $(', ')'), '`': ('echo `', '`'), '<(': ('cat <(', ')'), '>(': ('echo >(', ')'),
    '(': ('( ', ' )'), '{': ('{ ', '\n}'), '"$(': ('echo "$(', ')"'), '"`': ('echo "`', '`"'),
    # bash 3.2: a $(( / (( whose ')' at depth 0 is not followed by ')' is a subshell inside (found by this matrix)
    '$((sub': ('echo $((', ') )'), '((sub': ('((', ') )'),
}
INERT_FRAMES = {  # frame -> a function of the inner text: the inside is text, or arithmetic
    "'": lambda t: "echo '" + t + "'", '"': lambda t: 'echo "' + t + '"', "$'": lambda t: "echo $'" + t + "'",
    '${': lambda t: 'echo ${X:-' + t + '}',
    'heredoc-q': lambda t: "cat >/dev/null <<'E'\n" + t + '\nE', 'heredoc-u': lambda t: 'cat >/dev/null <<E\n' + t + '\nE',
    'comment': lambda t: 'true # ' + t,
}
CLOSED = {  # frame -> the closed frame as a whole command, for "right after the closer"
    '$(': 'echo $(m1)', '`': 'echo `m1`', '<(': 'cat <(m1)', '>(': 'echo >(m1)', '(': '( m1 )', '{': '{ m1\n}',
    '"$(': 'echo "$(m1)"', '"`': 'echo "`m1`"', "'": "echo 'x'", '"': 'echo "x"', "$'": "echo $'x'",
    '${': 'echo ${X:-x}', '$((': 'echo $(( 1 ))', '((': '(( 1 ))', '$((sub': 'echo $((m1) )', '((sub': '((m1) )',
}


def matrix_cases():
    """[(cell, cmd)]: markers are m1..mN in the text. A marker after the frame shows where bash closed it."""
    out = []
    for ch in MATRIX_CHARS:
        name = 'NL' if ch == '\n' else ch
        for fr, (op, cl) in CODE_FRAMES.items():
            bt = fr in ('`', '"`')
            if ch == '#':
                inner = ['m1 #m2' + ('' if bt else '\n'), 'm1#m2', '#m1' + ('' if bt else '\n')]
            else:
                inner = ['m1 %s m2' % ch if ch != '\n' else 'm1\nm2']
                if ch in '\'"':  # unterminated, and a closed pair holding a separator
                    inner.append('m1 %sa;b%s m2' % (ch, ch))
            for k, x in enumerate(inner):
                out.append(('%s|%s|in%s' % (fr, name, k or ''), op + x + cl + ' ; m3' if fr != 'top' else x + '\nm3'))
        texts = ['a %s m1 b' % ch] + (['a#m1 b', '#m1 b'] if ch == '#' else [])
        for fr, wrap in INERT_FRAMES.items():
            for k, t in enumerate(texts):
                out.append(('%s|%s|in%s' % (fr, name, k or ''), wrap(t) + '\nm2'))
        out.append(('$((|%s|in' % name, '( echo $(( 1 %s 2 )) ) ; m1' % ch))
        out.append(('((|%s|in' % name, '( (( 1 %s 2 )) ) ; m1' % ch))
        tail = {'#': '#m8 ; m9\nm10', ';': '; m8', '|': '| m8', '&': '& m8', '\n': '\nm8', "'": "'#' ; m8", '"': '"#" ; m8'}[ch]
        for fr, closed in CLOSED.items():
            out.append(('%s|%s|after' % (fr, name), closed + tail))
        for q, d in (('heredoc-q', "'E'"), ('heredoc-u', 'E')):
            # right after the delimiter word: a glued '#' is part of the delimiter word (bash: E#m8)
            body = {'#': '#m8 ; m9\nx\nE#m8\nm10', '\n': '\nm8\nE\nm9'}.get(ch, tail + '\nx\nE')
            out.append(('%s|%s|after' % (q, name), 'cat >/dev/null <<' + d + body))
        out.append(('comment|%s|after' % name, 'true # x\n' + {'#': '#m8\nm9', '\n': '\nm8'}.get(ch, ch + ' m8')))
    return out


SPECIAL = ['#', ';', '&', '|', '<', '>', "'", '"', '`', '$', '\\', '(', ')', '{', '}', '\n', ' ']


def code_payload(ch, a, b):
    """Two markers around one special character, in a frame that runs commands (card f7d4ead8)."""
    return {
        '#': '%s # %s\n' % (a, b),            # a comment to the end of the line
        ';': '%s ; %s' % (a, b),
        '&': '%s & %s' % (a, b),
        '|': '%s | %s' % (a, b),
        '<': '%s </dev/null ; %s' % (a, b),
        '>': '%s >o ; %s' % (a, b),
        "'": "%s 'x' %s" % (a, b),             # b is an argument
        '"': '%s "x" %s' % (a, b),
        '`': '%s `%s`' % (a, b),               # b runs in a nested backtick
        '$': '%s $(%s)' % (a, b),
        '\\': '%s \\; %s' % (a, b),            # an escaped ; : b is an argument
        '(': '%s ; ( %s )' % (a, b),
        ')': '%s ; ( %s )' % (a, b),
        '{': '%s ; { %s ; }' % (a, b),
        '}': '%s ; { %s ; }' % (a, b),
        '\n': '%s\n%s' % (a, b),
        ' ': '%s %s' % (a, b),
    }[ch]


def char_matrix_cases():
    """(context x special char), next to the frame matrix above (card f7d4ead8): every frame and quote kind gets
    every special character once, and a marker after the frame shows the frame closed where bash closes it. Viktor 42794 HIGH 1 came from such an empty cell (a '#'
    inside ${ }); work/fae0712e/oracle-coverage.py measures the cells. Arithmetic runs in a subshell, so an
    arithmetic error ends only that subshell and the marker after it still runs."""
    out = []
    for ch in SPECIAL:
        code = {
            'top': lambda: code_payload(ch, 'm1', 'm2'),
            '$(': lambda: 'echo $(' + code_payload(ch, 'm1', 'm2') + ') ; m3',
            '`': lambda: 'echo `' + code_payload(ch, 'm1', 'm2').replace('`', '\\`') + '` ; m3',
            '<(': lambda: 'cat <(' + code_payload(ch, 'm1', 'm2') + ') >/dev/null ; m3',
            '(': lambda: '( ' + code_payload(ch, 'm1', 'm2') + ' ) ; m3',
        }
        text = 'a ' + ch + ' m1 b'
        inert = {
            '${': lambda: 'echo ${X:-' + text + '} ; m2',
            '$((': lambda: '( echo $(( 1 ' + ch + ' 2 )) ) ; m1',
            '((': lambda: '( (( 1 ' + ch + ' 2 )) ) ; m1',
            "'..'": lambda: "echo '" + text + "' ; m2",
            '".."': lambda: 'echo "' + text + '" ; m2',
            "$'..'": lambda: "echo $'" + text + "' ; m2",
            'comment': lambda: 'true # ' + text + '\nm2',
            'heredoc(u)': lambda: 'cat >/dev/null <<E\n' + text + '\nE\nm2',
            'heredoc(q)': lambda: "cat >/dev/null <<'E'\n" + text + '\nE\nm2',
        }
        for ctx, make in list(code.items()) + list(inert.items()):
            out.append((ctx, make()))
    return out


def run_case(cmd, markers, tmp, syntax_ok=False):
    script = os.path.join(tmp, 's.sh')
    log = os.path.join(tmp, 'ran')
    pre = ''.join('%s() { echo %s >> "$OUT"; }\n' % (x, x) for x in markers)
    with open(script, 'w') as f:
        f.write(pre + cmd + '\nwait\n')
    syntax = subprocess.run([BASH, '-n', script], capture_output=True).returncode != 0
    if syntax and not syntax_ok:
        return None
    if os.path.exists(log):
        os.remove(log)
    env = {'PATH': '/usr/bin:/bin', 'OUT': log, 'HOME': tmp, 'LC_ALL': 'C'}
    subprocess.run([BASH, script], cwd=tmp, env=env, capture_output=True, timeout=10)
    ran = []
    if os.path.exists(log):
        with open(log) as f:
            ran = sorted(set(f.read().split()), key=lambda x: int(x[1:]))
    return (ran, syntax) if syntax_ok else ran


def generate():
    rnd = random.Random(SEED)
    cases = []
    with tempfile.TemporaryDirectory() as tmp:
        while len(cases) < WANT:
            n = [0]

            def k():
                n[0] += 1
                return 'm%d' % n[0]

            parts = [pieces(rnd, k) for _ in range(rnd.randint(1, 3))]
            seps = [rnd.choice(['; ', ' && ', '\n', ' | ']) for _ in parts[1:]]
            cmd = parts[0] + ''.join(s + p for s, p in zip(seps, parts[1:]))
            # no || and no failing command: every piece succeeds (the markers, true, echo, cat), so the run set
            # never depends on an exit status the lexer cannot know
            markers = ['m%d' % i for i in range(1, n[0] + 1)]
            ran = run_case(cmd, markers, tmp)
            if ran is None:
                continue
            cases.append({'cmd': cmd, 'markers': markers, 'ran': ran})
        for cell, cmd in matrix_cases():
            markers = sorted(set(re.findall(r'\bm[0-9]+\b', cmd)), key=lambda x: int(x[1:]))
            ran, syntax = run_case(cmd, markers, tmp, syntax_ok=True)
            c = {'cmd': cmd, 'markers': markers, 'ran': ran, 'cell': cell}
            if syntax:
                c['syntax'] = True
            cases.append(c)
        # the (context x char) matrix after the frame matrix, so the earlier cases stay byte-identical; a cell bash
        # rejects as a syntax error is left out here
        for ctx, cmd in char_matrix_cases():
            markers = sorted(set(re.findall(r'\bm[0-9]+\b', cmd)), key=lambda x: int(x[1:]))
            ran = run_case(cmd, markers, tmp)
            if ran is None:
                continue
            cases.append({'cmd': cmd, 'markers': markers, 'ran': ran, 'matrix': ctx})
    ver = subprocess.run([BASH, '--version'], capture_output=True, text=True).stdout.splitlines()[0]
    return {'about': 'generated by scripts/lib/shell-lex-oracle-gen.py (seed %d); the ran set was measured with a '
                     'real bash' % SEED, 'bash': ver, 'cases': cases}


def main():
    data = generate()
    if '--check' in sys.argv:
        with open(OUT, encoding='utf-8') as f:
            old = json.load(f)
        bad = [c['cmd'] for c, o in zip(data['cases'], old['cases']) if c != o]
        if bad or len(data['cases']) != len(old['cases']):
            print('shell-lex-oracle: bash now differs on %d case(s), first: %r' % (len(bad), bad[:1]))
            return 1
        print('shell-lex-oracle: %d cases, bash agrees' % len(data['cases']))
        return 0
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write('\n')
    print('wrote %d cases -> %s (%s)' % (len(data['cases']), OUT, data['bash']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
