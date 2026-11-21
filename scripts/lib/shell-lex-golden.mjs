// shell-lex-golden.mjs -- writes or checks scripts/lib/shell-lex-golden.json (card fae0712e).
//
//   node scripts/lib/shell-lex-golden.mjs --write   # after a deliberate change: rewrite every case's `want`
//   node scripts/lib/shell-lex-golden.mjs --check   # exit 1 if shell-lex.mjs no longer gives the stored answer
//
// The cases are the INPUTS below; `want` is what shell-lex.mjs answered when they were written. The JS test
// (src/__tests__/shell-lex.test.ts) and the Python test (scripts/lib/shell_lex_test.py) both check every case, so
// the two lexers give the same answer on all of them. A `--write` is a review item: read the diff of the json.
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { lex, words } from './shell-lex.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const OUT = join(HERE, 'shell-lex-golden.json')

// [id, input, why]
const CASES = [
  ['plain', 'ls -la /tmp', 'one command, three words'],
  ['seps', 'a; b && c || d | e |& f & g\nh', 'every separator; |& and a lone & split too'],
  ['redir-amp', 'curl x 2>&1 >/dev/null &>/tmp/o | tee y', '>& 2>&1 &> are redirections, not separators'],
  ['squote', "echo 'a;b|c $(d)'", 'nothing is live inside single quotes'],
  ['dquote-subst', 'echo "c $(d "e") f"', 'a $( ) inside double quotes is code again, and nests'],
  ['dquote-escape', 'echo "a\\"b\\$c\\x"', 'in double quotes \\ escapes only $ ` " \\ newline'],
  // Three cases a mutation round showed missing (work/fae0712e/lexmut, mutants p06/j06, p09/j09, p13/j13):
  ['dquote-backtick', 'echo "a `id; ls` b"', 'a backtick inside double quotes is code again (mutant dq-backtick)'],
  ['hash-after-escaped-blank', "echo a\\ #b; ls 'c'", 'an escaped blank is word text: the # after it is no comment (mutant comment-after-escape)'],
  ['herestring-then-lt', 'cat <<<<EOF\nwhoami\nEOF', '<<< then <: no heredoc, the next lines stay code (bash: a syntax error, no body either way; mutant herestring-as-heredoc)'],
  // Viktor 42794 HIGH 1: a '#' inside ${ }, $(( )), (( )) is no comment (bash and zsh, measured in
  // work/fae0712e/hash-probe.sh); the comment reading left the frame open and the egress gate allowed the curl after it
  ['hash-in-param-default', 'echo ${x:- #}; ls', 'a # after a blank inside ${ } is parameter text, the } closes the frame'],
  ['hash-in-param-word', 'echo ${x:- a #b}; ls', 'the same with a word before the #'],
  ['hash-in-param-escaped-brace', 'echo ${x:- \\} #}; ls', 'an escaped } does not close, the # after it is still no comment'],
  ['hash-in-arith', 'echo $(( 1 #)); ls', 'a # inside $(( )) is arithmetic text (an arithmetic error, not a comment)'],
  ['hash-in-arith-cmd', '(( 1 #)); ls', 'the same in (( )): bash runs the ls after the arithmetic error'],
  ['hash-param-length', 'echo ${#HOME} # c', '${#x} is the length; a # after the frame and a blank is a comment again'],
  ['hash-in-backtick', 'echo `echo a #` ; ls', 'a comment inside a backtick ends at the closing backtick: ls is a command (main denied the curl form; Viktor probe_c shape)'],
  // Viktor 42852 HIGH 3: the closer of $( ), <( ), $(( )) and a backtick is word text, so a '#' right after it is too;
  // a plain ( ) subshell and the (( )) command end a word, the '#' after them is a comment (bash 3.2, measured)
  ['hash-after-cmdsubst', 'echo $(true)#; ls', "a '#' right after a closed $( ) is word text: ls is a command"],
  ['hash-after-backtick', 'echo `true`#; ls', "a '#' right after a closed backtick is word text: ls is a command"],
  ['hash-after-procsubst', 'cat <(true)#; ls', "a '#' right after a closed <( ) is word text: ls is a command"],
  ['hash-after-arith', 'echo $((1))#; ls', "a '#' right after a closed $(( )) is word text: ls is a command"],
  ['hash-after-subshell', '(true)#; ls', "a plain ( ) subshell ends a word: the '#' after it is a comment"],
  ['hash-after-arith-cmd', '((1))#; ls', "the (( )) command ends a word: the '#' after it is a comment"],
  // the frame matrix (Klodel 42854) found it: in bash 3.2 a $(( / (( whose ')' at depth 0 is not followed by ')' is a
  // subshell inside ($((a) ) runs a; measured); the lexer reads that opener again as two parentheses
  ['arith-split-cmdsubst', 'echo $((ls) ) ; id', '$((ls) ) is $( (ls) ): ls runs, then id'],
  ['arith-split-cmd', '((ls); id )', '((ls); id ) is ( (ls); id ): both run'],
  ['arith-split-dquote', 'echo "$((ls) )"', 'the same inside double quotes'],
  ['arith-paired', 'echo $(( (1) + 2 )) ; id', 'paired parentheses inside: still arithmetic'],
  // Viktor 42888 HIGH 4: bash 3.2 cuts a backtick body at its first unescaped backtick, whatever quote, comment or
  // $( ) is open inside it; what is open there is a problem, and the text after the backtick is code again
  ['backtick-open-quote', "echo `echo '` ; ls", 'an unterminated quote inside a backtick ends at the closing backtick: ls is a command'],
  ['backtick-open-subst-comment', 'echo `echo $(echo a #)` ; ls', 'a comment inside a $( ) inside a backtick ends at the closing backtick too'],
  // Viktor 42933 INFO 1 (b), bash 3.2 measured (work/fae0712e/h7-esc-bt.sh): an escaped backtick does not end the body,
  // an escaped backslash before one does
  ['backtick-escaped-backtick', "echo `echo a \\` b '` ; ls", 'an escaped backtick does not end a backtick body: the quote closes at the last backtick, ls is a command'],
  ['backtick-escaped-backslash', 'echo `echo a \\\\` ; ls', 'an escaped backslash before a backtick: that backtick ends the body, ls is a command'],
  ['ansi-c-escaped-quote-hash', "echo $'a\\'#'; ls", "in $'..' an escaped quote does not close: the # is string text (mutant dollarq-escape)"],
  ['backtick-nested', 'echo `a \\`b\\` c` d', 'inside a backtick an escaped backtick nests: b is a command (card f7d4ead8, oracle matrix)'],
  ['ansi-c', "echo $'a\\'b;c'", "$'..' with an escaped quote"],
  ['ansi-c-escapes', "echo $'\\x2e/m\\056py\\u00e9\\cA\\q\\x'", 'hex, octal, \\u, \\c and unknown escapes are decoded'],
  ['dquote-dollar-end', 'echo "a$" b', 'a $ before the closing quote is a literal $'],
  ['continuation-mid', 'ab\\\ncd', 'a backslash-newline inside a word joins it'],
  ['locale', 'echo $"a;b"', '$"..." is a double-quoted string'],
  ['escape', 'echo a\\;b \\#c', 'a backslash pair is literal: no separator, no comment'],
  ['continuation', 'git commit \\\n  -m x', 'backslash-newline joins the line'],
  ['comment', 'ls # x; rm -rf /\nwhoami', 'a comment runs to the end of its line only'],
  ['hash-in-word', 'echo a#b c#d', '# inside a word is no comment'],
  ['hash-after-sep', 'true;# x\n(# y\n)', '# after ; or ( starts a comment'],
  ['backtick', 'echo `date` x', 'a backtick substitution'],
  ['subst-nested', 'a $(b $(c) d) e', 'nested $( )'],
  ['arith', 'x=$((1<<2)); y=$(( (3) ))', '<< inside $(( )) is a shift, parens nest'],
  ['arith-cmd', '((i<<=1)); echo', '(( )) at command start is arithmetic'],
  ['param', 'echo ${x:-a;b} ${#y}', '${ } holds a ; and a # without splitting the top command; its inside still gets segments (over-reporting is the safe side: bash 5.3 runs ${ cmd; })'],
  ['procsubst', 'diff <(ls a) >(cat)', '<( ) and >( )'],
  ['subshell', '(cd x && make); ls', 'a ( ) subshell'],
  ['group', '{ a; b; } > o', '{ } is plain code'],
  ['herestring', "cat <<<'x' ; ls", '<<< is an operator with no body'],
  ['heredoc-quoted', "git commit -F - <<'MSG'\n./x.py\nMSG\nls", 'quoted delimiter: inert body, ls runs after'],
  ['heredoc-dquoted', 'cat <<"E"\n$(x)\nE', 'a double-quoted delimiter is quoted too'],
  ['heredoc-escaped', 'cat <<\\E\n$(x)\nE', '<<\\E is quoted'],
  ['heredoc-partquoted', "cat <<E'N'D\nx\nEND", 'any quote in the word makes it quoted; delimiter END'],
  ['heredoc-dquoted-escape', 'cat <<"a\\b\\$"\nx\na\\b$', 'in a "..." delimiter \\ escapes only $ ` " \\ newline: delimiter a\\b$'],
  ['heredoc-dollar-squote', "cat <<$'J'\nx\nJ\nls", "card 70a5fb2a (Viktor 49212 O2): $'J' delimits at J, the $ is not part of it (bash 3.2)"],
  ['heredoc-dollar-squote-ansi', "cat <<$'J\\x41'\nx\nJA\nls", "a $'...' delimiter is ANSI-C decoded: J\\x41 delimits at JA (bash 3.2)"],
  ['heredoc-dollar-dquote', 'cat <<$"J"\nx\nJ\nls', '$"J" delimits at J, quoted (bash 3.2)'],
  ['heredoc-unquoted', 'cat <<E\n$(id)\nE', 'unquoted: the body is live (class u)'],
  ['heredoc-dash', "cat <<-'E'\n\tx\n\tE\nls", '<<- strips leading tabs from the terminator'],
  ['heredoc-no-dash-tab', "cat <<'E'\n\tE\nE", 'without - a tabbed line is no terminator'],
  ['heredoc-two', "cat <<A <<'B'\n1\nA\n2\nB\nls", 'two heredocs on one line: bodies in order'],
  ['heredoc-after-sep', "true && git commit -F - <<'M'\nx\nM", 'a heredoc of a later command on the line'],
  ['heredoc-unterminated', "cat <<'E'\nx", 'the body runs to the end: a problem'],
  ['heredoc-term-spaces', "cat <<'E'\nE \nE", 'a terminator with a trailing blank is no terminator'],
  ['heredoc-in-backtick', "git commit -F - `true <<'M'\n` ; ./m.sh\nM", 'inside a substitution: no body, lines stay code, problem (bash runs ./m.sh)'],
  ['heredoc-in-subst', "git commit -F - $(true <<'M'\n) ; ./m.sh\nM", 'same for $( ) (bash 3.2 runs ./m.sh)'],
  ['heredoc-in-quote', 'git commit -F - -m "x <<\'MSG\'\n" ; ./m.py\nMSG', 'an operator inside a quote is no operator'],
  ['heredoc-after-comment', "true # a; git commit -F - <<'true'\npython3 ./m.py\ntrue", 'an operator in a comment is no operator'],
  ['heredoc-escaped-op', "git commit -F - \\<<'true'\npython3 ./m.py\ntrue", '\\< is a word: no heredoc'],
  ['heredoc-open-quote-after', 'git commit -F - <<\'MSG\' -m "x\n" ; ./m.py #\nMSG', 'a quote opened after the operator: the body starts after it closes'],
  ['unterminated-squote', "echo 'abc", 'a problem'],
  ['unterminated-subst', 'echo $(ls', 'a problem'],
  ['unicode', "echo 'é😀' é😀 # 😀", 'indices are code points'],
  ['words-glue', 'a"b"\'c\'$\'d\'\\ e f', 'one word from four quoting styles, then f'],
  ['words-expand', 'echo $HOME "${x}" \'$y\' `z`', 'expands: unquoted or double-quoted $ or `'],
  ['env-prefix', 'A=1 B="x y" cmd arg', 'assignments are words of the segment'],
  ['empty', '', 'nothing'],
  ['only-sep', ' ; ;; & ', 'no segment'],
  // card 09283e90: a heredoc inside $( ) (bash 3.2 and zsh measured, scripts/lib/shell-lex-oracle.json hsub cases)
  ['hsub-payload', "R=$(curl -s -X POST u --data-binary @- <<'JSON'\n{\"a\": \"(x) y; ./m.sh\"}\nJSON\n)\necho \"$R\"", 'the body is inert, the frame closes after it'],
  ['hsub-close-on-op-line', "echo $(cat <<E) ; ./a.sh\n./m.sh\nE", 'the frame closed on the operator line: no body, the lines after it are code'],
  ['hsub-subshell', "( cat <<'J' )\nx ; ./m.sh\nJ\nls", 'a ( ) subshell is read at its parent level: the body after the ) line'],
  ['hsub-nested', "R=$(cat <<'J' $(cat <<'K'\nk\nK\n./a.sh)\nj\nJ\n)", 'each frame reads its own heredoc at its own newline'],
  ['hsub-two-frames', "A=$(cat <<'J'\n1\nJ\n); B=$(cat <<'K'\n2\nK\n)", 'two frames, a heredoc each'],
  ['hsub-bash32-paren', "R=$(cat <<'J'\na) ./m.sh\nJ\n)", 'bash 3.2 closes the frame at the body line: the old reading, a problem'],
  ['hsub-bash32-squote', "R=$(cat <<'J'\nPatrik's\nJ\n)", 'bash 3.2 opens a quote in the body: the old reading, a problem'],
  ['hsub-procsubst', "cat <(cat <<'J'\nx\nJ\n)", 'in <( ) the old reading (bash 3.2 reads # there differently), a problem'],
  ['top-pending-subst-nl', "cat <<T $(echo\n./m.sh\nT\n)\nbody\nT", 'a newline in $( ) does not read the top heredoc: ./m.sh and T run in it'],
  ['top-pending-subshell-nl', "cat <<T ; ( echo\nbody\nT\n)", 'a newline in a ( ) subshell reads it'],
]

function answer(input) {
  const lx = lex(input)
  return {
    cls: lx.cls,
    problems: lx.problems,
    heredocs: lx.heredocs,
    substs: lx.substs,
    segments: lx.segments.map((sg) => ({ ...sg, words: words(input, lx, sg).map((w) => [w.text, w.start, w.end, w.quoted, w.expands]) })),
  }
}

const mode = process.argv[2]
if (mode === '--write') {
  const cases = CASES.map(([id, input, why]) => ({ id, why, input, want: answer(input) }))
  writeFileSync(OUT, JSON.stringify({ about: 'generated by scripts/lib/shell-lex-golden.mjs --write; checked by src/__tests__/shell-lex.test.ts and scripts/lib/shell_lex_test.py', cases }, null, 1) + '\n')
  console.log(`wrote ${cases.length} cases -> ${OUT}`)
} else if (mode === '--check') {
  const stored = JSON.parse(readFileSync(OUT, 'utf8')).cases
  const bad = stored.filter((c) => JSON.stringify(answer(c.input)) !== JSON.stringify(c.want)).map((c) => c.id)
  const missing = CASES.filter(([id]) => !stored.some((c) => c.id === id)).map(([id]) => id)
  if (bad.length || missing.length) { console.error(`shell-lex-golden: changed ${bad.join(', ') || '-'}; not stored ${missing.join(', ') || '-'}`); process.exit(1) }
  console.log(`shell-lex-golden: ${stored.length} cases OK`)
} else {
  console.error('usage: shell-lex-golden.mjs --write | --check')
  process.exit(2)
}
