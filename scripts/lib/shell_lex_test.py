"""shell_lex_test.py -- the Python twin of src/__tests__/shell-lex.test.ts (card fae0712e).

Checks scripts/lib/shell_lex.py against the SAME golden file as the JS lexer (scripts/lib/shell-lex-golden.json),
so the two lexers give the same answer on every case, plus the semantic asserts a gate relies on.

    python3 -I scripts/lib/shell_lex_test.py
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shell_lex  # noqa: E402

FAILS = []


def check(name, got, want):
    if got != want:
        FAILS.append(name)
        print('FAIL %s\n  got:  %r\n  want: %r' % (name, got, want))


def answer(text):
    lx = shell_lex.lex(text)
    return {
        'cls': lx['cls'],
        'problems': lx['problems'],
        'heredocs': lx['heredocs'],
        'substs': lx['substs'],
        'segments': [dict(sg, words=[[w['text'], w['start'], w['end'], w['quoted'], w['expands']]
                                     for w in shell_lex.words(text, lx, sg)]) for sg in lx['segments']],
    }


def seg_texts(text, depth=None):
    lx = shell_lex.lex(text)
    return [text[sg['start']:sg['end']] for sg in lx['segments'] if depth is None or sg['depth'] == depth]


def argv(text, k=0):
    lx = shell_lex.lex(text)
    top = [sg for sg in lx['segments'] if sg['depth'] == 0]
    return [w['text'] for w in shell_lex.words(text, lx, top[k])]


ASSIGN = re.compile(r'^[A-Za-z_]\w*=')


MATRIX_PROBLEM_CELLS = ["`|'|in", "\"`|'|in", '`|"|in', '"`|"|in', "heredoc-q|'|after", "heredoc-u|'|after",
                        'heredoc-q|"|after', 'heredoc-u|"|after']


def ran_by_lexer(cmd):
    """The command words the lexer says run: the first word of each segment in a frame that runs commands
    (not $(( )), (( )) or a plain ${ }), after { ! and unquoted VAR= prefixes. None = the lexer has problems."""
    lx = shell_lex.lex(cmd)
    if lx['problems']:
        return None
    out = set()
    for sg in lx['segments']:
        if sg['frame'] in ('$((', '(('):
            continue
        if sg['frame'] == '${':
            at = lx['substs'][sg['frameAt']]['inner'][0]
            if not (at < len(cmd) and cmd[at] in ' \t\n|'):
                continue
        ws = shell_lex.words(cmd, lx, sg)
        i = 0
        while i < len(ws) and (ws[i]['text'] in ('{', '!') or (ASSIGN.match(ws[i]['text']) and not ws[i]['quoted'])):
            i += 1
        if i < len(ws):
            out.add(ws[i]['text'])
    return out


def main():
    with open(os.path.join(HERE, 'shell-lex-golden.json'), encoding='utf-8') as f:
        cases = json.load(f)['cases']
    check('golden count', len(cases) >= 50, True)
    for c in cases:
        # json round trip: the stored want went through JSON too (tuples vs lists, key order do not matter)
        check('golden ' + c['id'], json.loads(json.dumps(answer(c['input']))), c['want'])

    check('separator in quote/escape/comment', seg_texts("echo 'a;b' \"c|d\" e\\;f # g; h"),
          ["echo 'a;b' \"c|d\" e\\;f"])
    t = "git commit -F - <<'MSG'\npython3 ./x.py\nMSG\nls"
    check('quoted heredoc segments', seg_texts(t), ["git commit -F - <<'MSG'", 'ls'])
    check('quoted heredoc count', len(shell_lex.lex(t)['heredocs']), 1)
    for t in ['x -m "a <<\'E\'\n" ; ./m.py\nE', "true # <<'E'\n./m.py\nE", "x \\<<'E'\n./m.py\nE"]:
        check('no operator: ' + repr(t), (shell_lex.lex(t)['heredocs'], './m.py' in seg_texts(t)), ([], True))
    t = "x $(true <<'M'\n) ; ./m.sh\nM"
    check('heredoc in subst', ('heredoc-in-subst' in shell_lex.lex(t)['problems'], './m.sh' in seg_texts(t)),
          (True, True))
    check('unterminated quote', bool(shell_lex.lex("echo 'a")['problems']), True)
    check('unterminated subst', bool(shell_lex.lex('echo $(a')['problems']), True)
    check('unterminated heredoc', 'unterminated-heredoc' in shell_lex.lex("cat <<'E'\nx")['problems'], True)
    check('clean', shell_lex.lex('echo ok')['problems'], [])
    check('subst in word', seg_texts('echo $(id) `who` <(ls)', 0), ['echo $(id) `who` <(ls)'])
    check('subst nested', seg_texts('echo $(id) `who` <(ls)', 1), ['id', 'who', 'ls'])
    check('subst in dquote word', argv('echo "a $(b) c"'), ['echo', 'a $(b) c'])
    check('words glue', argv("a\"b\"'c'$'d'\\ e f"), ['abcd e', 'f'])
    check('words continuation', argv('git commit \\\n  -m x'), ['git', 'commit', '-m', 'x'])
    check('words ansi-c', argv("python3 $'\\x2e/m\\056py'"), ['python3', './m.py'])
    check('words dquote $', argv('echo "a$" b'), ['echo', 'a$', 'b'])
    check('ansi_c bash', shell_lex.ansi_c('\\x2e/m\\056py\\cA\\q'), './m.py\x01\\q')
    check('ansi_c quote', shell_lex.ansi_c("a\\'b\\\\"), "a'b\\")
    check('ansi_c surrogate', shell_lex.ansi_c('\\ud800'), '\ufffd')
    check('code points', len(shell_lex.lex("echo 'é😀' x")['cls']), len("echo 'é😀' x"))

    # card fae0712e: linear on hostile input (1000 x f( took 255 s before the one-pass segments_of)
    import time
    # 20 000 open '(' (a per-character walk of the frame stack: 35 s) and 4 000 split retries (Viktor 42888 LOW: 32.6 s)
    for t in ['f(' * 4000, '$(a ' * 1000, 'echo ${a:-$(b)} ' * 2000, '(a);' * 3000, '(config ' * 20000,
              '`' + '(\n#x\n' * 20000, 'echo $((a) ) ' * 4000]:
        t0 = time.time()
        lx = shell_lex.lex(t)
        for sg in lx['segments']:
            shell_lex.words(t, lx, sg)
        check('linear ' + t[:12], time.time() - t0 < 3.0, True)

    # Viktor 42697 condition 2: the lexer against a real bash (scripts/lib/shell-lex-oracle.json, generated by
    # shell-lex-oracle-gen.py): a marker ran iff the lexer says it is a command word
    with open(os.path.join(HERE, 'shell-lex-oracle.json'), encoding='utf-8') as f:
        oracle = json.load(f)['cases']
    skipped = 0
    for c in oracle:
        if c.get('syntax'):  # bash rejects the text (a matrix cell, Klodel 42854): the gate-level test covers it
            continue
        got = ran_by_lexer(c['cmd'])
        if got is None:  # the lexer says it does not understand the text: a gate fails closed there
            skipped += 1
            continue
        check('oracle ' + repr(c['cmd']), sorted((x for x in got if x in c['markers']), key=lambda x: int(x[1:])), c['ran'])
    check('oracle cases', len(oracle) >= 300, True)
    check('oracle skipped <= 10%', skipped * 10 <= len(oracle), True)

    if FAILS:
        print('shell_lex_test: %d FAIL' % len(FAILS))
        return 1
    matrix = [c for c in oracle if 'cell' in c]
    cells = {c['cell'].rsplit('|', 1)[0] + '|' + ('after' if c['cell'].endswith('after') else 'in') for c in matrix}
    check('matrix: every frame x {# ; | & NL quotes} x {in, after} has a case', len(cells), 20 * 7 * 2 - 7)
    # the only valid cells the lexer reports problems on: a quote left open in a backtick body (bash: an error in the
    # small shell, the outer line goes on) and a heredoc whose quoted delimiter word never ends its body; the gate
    # level (bash-egress-parser.test.ts) and the unparseable-external reserve judge them
    check('matrix: the valid cells the lexer does not understand', sorted(c['cell'] for c in matrix if not c.get('syntax') and ran_by_lexer(c['cmd']) is None),
          sorted(MATRIX_PROBLEM_CELLS))
    # card 09283e90: a heredoc in a frame, run with bash 3.2 AND zsh (the oracle's hsub cases). Where the two shells
    # run different markers the lexer must not understand the text (a gate fails closed); where they agree it must
    # understand it, except in the frames whose heredoc it reads the old way (<( ) >( ) and a backtick)
    hs = [c for c in oracle if 'hsub' in c]

    def agree(c):
        return c['ran'] == c['zsh'] and bool(c.get('syntax')) == bool(c.get('zsh_syntax'))

    check('hsub cases', len(hs), 128)
    check('hsub: bash 3.2 and zsh differ -> not understood', [c['hsub'] for c in hs if not agree(c) and ran_by_lexer(c['cmd']) is not None], [])
    check('hsub: they agree -> understood, except the old-reading frames',
          sorted(c['hsub'] for c in hs if agree(c) and not c.get('syntax') and ran_by_lexer(c['cmd']) is None),
          sorted(c['hsub'] for c in hs if agree(c) and not c.get('syntax') and c['hsub'].split('|')[0] in ('<(', '`')))
    if FAILS:
        print('shell_lex_test: %d FAIL' % len(FAILS))
        return 1
    print('shell_lex_test: OK (%d golden cases, %d bash-oracle cases (%d with lexer problems; %d matrix cases, %d cells; '
          '%d heredoc-in-frame cases, bash 3.2 + zsh), semantic asserts)'
          % (len(cases), len(oracle), skipped, len(matrix), len(cells), len(hs)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
