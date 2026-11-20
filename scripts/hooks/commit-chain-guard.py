#!/usr/bin/env python3
"""commit-chain-guard.py -- PreToolUse (Bash) hook of every sub-agent: a `git commit` that would run even when a test
or gate EARLIER IN THE SAME COMMAND fails stops BEFORE the command runs.

FLEET (card b3ae9523, retro 2026-11-20, Klodel 48876; logic Viktor 48985 HASH-OK): first Kernel's own hook
(agents/kernel/tools/hooks), now wired onto every sub-agent by src/web/agent-scaffold.ts (ensureCommitChainGuard).
The 14-day fleet replay (158769 Bash commands): 145 blocks, Dave 22 and Pulzus 1 among them, each a commit or a
swap behind ';' or a piped check. The Codex and live-swap actions below are Kernel's tools; on other agents they
simply never match.

WHY (hibanapló 2026-11-16, twice the same day, two agents): Kernel 04:12 amended with a red test because the commit
followed the test with ';' instead of '&&' (a mutation run then reported "23/23 killed" on the red base); Dave 11:07
committed past a red clean gate the same way. The second shape of the same loss is a pipe: `npm test | tail && git
commit` commits on tail's status, not the test's.

Blocked (exit 2), for every check that precedes a `git commit` in the command:
  - a joiner between the check and the commit is not '&&' (';', newline, '||', '&'), `set -e` or not;
  - the check is piped into something else and `set -o pipefail` is not on (its status is lost).
Not blocked: the check and the commit in separate Bash calls (the way to commit on purpose after reading a red run),
'&&' all the way (+ `set -o pipefail` for pipes).

`set -e` does NOT count (2026-11-16 18:58, measured in this Bash tool: `set -e; false; echo after` printed "after",
the shell runs the command through zsh eval, where errexit does not stop it). The same day a commit went through
past a clean gate with 1 finding behind `set -e` + newlines, and this guard let it pass. `set -o pipefail` was
measured to work (`set -o pipefail; false | cat && echo x` printed nothing).

A check = a command that RUNS a test or gate: vitest / pytest / jest / eslint / tsc (directly or through npx),
`npm test`, `npm run test|lint|check|typecheck`, `node --test`, `python3 -m unittest|pytest`, or an interpreter whose
SCRIPT is named *_test.* / *.test.* / *.spec.* / test_*.py / *lint*, or has clean-gate / release-check / run-tests in
its path (also behind a wrapper script: `sh enter.sh node --test`). A test file that is only an argument is not a run
(`git add a.test.ts`, `python3 - a.test.ts <<EOF`): the 14-day replay showed these as the false hits.

CHAIN GUARD (2026-11-20, retro 3(b), Klodel 48854): the same rule holds for two more ACTIONS besides `git commit`:
  - a REAL Codex review run: tools/codex-review/run_review.py or launch_detached.py without --dry (hibanapló
    2026-11-17 10:24: `run_review.py --dry ...; launch_detached.py ...` started the real run after the dry stopped
    with exit 7; codex-dry-first-guard.py lets such a chain through when an older passing dry report is still fresh);
  - `live-swap.sh ... --apply` (a live file is replaced).
And two more CHECKS: run_review.py / launch_detached.py WITH --dry, and live-swap.sh WITHOUT --apply (its check mode).
So `live-swap.sh <args>; live-swap.sh <args> --apply` and `npm test; live-swap.sh ... --apply` stop like a commit does.

FOLLOW-UP 1-2 (Viktor 48870 KÖVETŐ, card b3ae9523): a commit behind a wrapper (`env VAR=x git commit`, `command git
commit`, `time git commit`, `nice -n 10 git commit`, `timeout 60 git commit`, `nohup`, `stdbuf -oL`, `exec -a x`,
`caffeinate -t 5`, `env -S 'git commit'`) is a commit, and a package-manager option with a separate value
(`npm --prefix web test`, `npm -C web test`, `npm -w web test`, `pnpm --filter web test`, `pnpm -C web test`,
`yarn --cwd web test`, `yarn workspace web test`) no longer hides the test run. Also (indep probe, 2nd round):
`env -P dir`, zsh `noglob`, `eval git commit`, `npm --loglevel x test`, `bun --cwd web test`, `bunx`/`pnpx` like
npx, `deno test|lint|check`, and the pnpm / yarn bare-name script or bin (`pnpm lint`, `yarn lint`, `pnpm vitest`);
`command -v vitest` only looks the name up and is not a check.

Known limits (allowed, fail open): control flow (if/for/while/case, { }), anything inside ( ) or $( ), unbalanced
quotes, any error; wrappers not modelled: sudo, xargs (`... | xargs git commit -m`), nested shells (`bash -c '...'`,
`sh -c`); a package-manager option with a separate value that is not listed in PKG_OPTS_WITH_ARG (a deny list).
This is a hygiene guard, not a security gate.
Test: python3 -I scripts/hooks/commit-chain-guard_test.py
"""
import json
import os
import re
import shlex
import sys

INTERPRETERS = {'python3', 'python', 'bash', 'sh', 'zsh', 'node', 'deno', 'bun', 'tsx', 'ts-node'}
PKG = {'npm', 'pnpm', 'yarn', 'bun'}
WRAPPERS = {'env', 'time', 'command', 'exec', 'nice', 'caffeinate', 'timeout', 'gtimeout', 'nohup', 'stdbuf', 'noglob',
            'eval'}
TOOL_WORDS = {'vitest', 'pytest', 'jest', 'eslint', 'tsc', 'unittest'}
RUN_TARGETS = {'test', 'lint', 'check', 'typecheck', 't'}
# a script counts by its file name (a test file, a linter) or by a gate name anywhere in its path
NAME_RX = re.compile(r'(^test_.+\.py$)|((_test|\.test|\.spec)\.(py|sh|ts|tsx|mts|mjs|cjs|js)$)|lint')
PATH_RX = re.compile(r'clean-gate|release-check|run-tests')
KEYWORDS = {'if', 'then', 'else', 'elif', 'fi', 'for', 'while', 'until', 'do', 'done', 'case', 'esac', 'function',
            '{', '}', '!', 'select'}
ASSIGN_RX = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')
HEREDOC_RX = re.compile(r'<<(-?)\s*(?:\'([^\']+)\'|"([^"]+)"|\\?([A-Za-z_][A-Za-z0-9_]*))')


def split_top(cmd):
    """[(text, op_after)] split at top-level operators; None when the quoting does not balance.
    op_after is one of '&&', '||', ';', '|', '&', '' (last). Newline counts as ';'. Heredoc bodies are dropped."""
    segs, buf, stack, pending = [], [], [], []
    i, n = 0, len(cmd)

    def flush(op):
        segs.append((''.join(buf), op))
        del buf[:]

    while i < n:
        c = cmd[i]
        top = stack[-1] if stack else None
        if top == 'sq':
            buf.append(c)
            if c == "'":
                stack.pop()
            i += 1
            continue
        if c == '\\' and i + 1 < n:
            if cmd[i + 1] == '\n':
                buf.append(' ')
            else:
                buf.append(cmd[i:i + 2])
            i += 2
            continue
        if top == 'bt':
            buf.append(c)
            if c == '`':
                stack.pop()
            i += 1
            continue
        if top == 'dq':
            if c == '"':
                stack.pop()
            elif c == '`':
                stack.append('bt')
            elif c == '$' and cmd[i + 1:i + 2] == '(':
                stack.append('paren')
                buf.append('$(')
                i += 2
                continue
            buf.append(c)
            i += 1
            continue
        # unquoted: top level or inside ( ) / $( )
        if c == '<' and cmd.startswith('<<', i) and not cmd.startswith('<<<', i):
            m = HEREDOC_RX.match(cmd, i)
            if m:
                pending.append((m.group(1) == '-', m.group(2) or m.group(3) or m.group(4)))
                buf.append(m.group(0))
                i = m.end()
                continue
        if c == '\n' and pending:
            j = i + 1
            for strip_tabs, delim in pending:
                while j < n:
                    k = cmd.find('\n', j)
                    end = n if k < 0 else k
                    line = cmd[j:end]
                    j = end + 1
                    if (line.lstrip('\t') if strip_tabs else line) == delim:
                        break
            del pending[:]
            i = j - 1  # the newline that ends the terminator line, or past the end
            if i >= n:
                break
        if c == "'":
            stack.append('sq')
        elif c == '"':
            stack.append('dq')
        elif c == '`':
            stack.append('bt')
        elif c == '(':
            stack.append('paren')
        elif c == ')' and top == 'paren':
            stack.pop()
        elif c == '#' and not stack and (not buf or buf[-1] in ' \t'):
            k = cmd.find('\n', i)
            i = n if k < 0 else k
            continue
        elif not stack:
            two = cmd[i:i + 2]
            if two in ('&&', '||'):
                flush(two)
                i += 2
                continue
            if two == '|&':
                flush('|')
                i += 2
                continue
            if c == '|':
                flush('|')
                i += 1
                continue
            if c in ';\n':
                flush(';')
                i += 1
                continue
            if c == '&':
                prev = buf[-1] if buf else ''
                if prev not in '<>' and cmd[i + 1:i + 2] != '>':
                    flush('&')
                    i += 1
                    continue
        buf.append(c)
        i += 1
    if stack:
        return None
    flush('')
    return [(t, op) for t, op in segs if t.strip() or op == '|']


def words(seg):
    try:
        w = shlex.split(seg, comments=False)
    except ValueError:
        w = seg.split()
    while w and ASSIGN_RX.match(w[0]):
        w = w[1:]
    return w


# wrapper options that take a separate value, PER WRAPPER (env -u NAME, nice -n 10, exec -a NAME, caffeinate -t 5,
# timeout -s TERM, stdbuf -o L); the value is skipped with the option. env -S STRING is split into words instead
# (env -S 'git commit -m x' runs the commit). timeout then takes one positional DURATION (Viktor, chain-fleet 1st round).
WRAPPER_OPTS_WITH_ARG = {
    'env': {'-u', '--unset', '-C', '--chdir', '-P'},  # macOS env -P altpath (measured: env -P /usr/bin git runs git)
    'nice': {'-n', '--adjustment'},
    'exec': {'-a'},
    'caffeinate': {'-t', '-w'},
    'time': {'-o', '--output', '-f', '--format'},
    'timeout': {'-s', '--signal', '-k', '--kill-after'},
    'gtimeout': {'-s', '--signal', '-k', '--kill-after'},
    'stdbuf': {'-i', '-o', '-e', '--input', '--output', '--error'},
}
SPLIT_OPTS = {'-S', '--split-string'}
DURATION_RX = re.compile(r'^\d+(\.\d+)?[smhd]?$')


def _strip_wrappers(w):
    """The simple command behind VAR=x, env/command/time/exec/nice/caffeinate and their options (Viktor 48870
    KÖVETŐ 1: `env VAR=x git commit`, `command git commit`, `time git commit` passed, is_commit read only w[0])."""
    while w:
        if ASSIGN_RX.match(w[0]):
            w = w[1:]
        elif os.path.basename(w[0]) in WRAPPERS:
            name = os.path.basename(w[0])
            takes = WRAPPER_OPTS_WITH_ARG.get(name, set())
            if name == 'command' and len(w) > 1 and w[1] in ('-v', '-V'):
                return []  # command -v vitest only looks the name up, it runs nothing (indep P11 over-block)
            if name == 'eval':
                joined = ' '.join(w[1:])  # eval git commit -m x: eval joins its words and runs them
                try:
                    w = shlex.split(joined)
                except ValueError:
                    w = joined.split()
                continue
            w = w[1:]
            while w and w[0].startswith('-') and w[0] != '--':
                if name == 'env' and w[0] in SPLIT_OPTS and len(w) > 1:
                    try:
                        w = shlex.split(w[1]) + w[2:]
                    except ValueError:
                        w = w[1].split() + w[2:]
                    break
                w = w[2:] if w[0] in takes else w[1:]
            if w and w[0] == '--':
                w = w[1:]
            if name in ('timeout', 'gtimeout') and w and DURATION_RX.match(w[0]):
                w = w[1:]
        else:
            break
    return w


def is_commit(w):
    w = _strip_wrappers(w)
    if not w or os.path.basename(w[0]) != 'git':
        return False
    i = 1
    while i < len(w):
        if w[i] in ('-C', '-c', '--git-dir', '--work-tree', '--namespace'):
            i += 2
        elif w[i].startswith('-'):
            i += 1
        else:
            return w[i] == 'commit'
    return False


CODEX_RUNNERS = {'run_review.py', 'launch_detached.py'}
SWAP = 'live-swap.sh'


DETACHED = 'launch_detached.py'


def _dry(b, args):
    """run_review.py's argparse takes an unambiguous prefix (--dr); launch_detached.py's first word is the LOG file,
    so `launch_detached.py --dry --input ...` is a REAL run with a log named --dry (Viktor 48859, stub-measured)."""
    if b == DETACHED:
        args = args[1:]
    return any(len(a) >= 4 and '--dry'.startswith(a) for a in args)


def _script_is_check(x, args=()):
    b = os.path.basename(x)
    if b in CODEX_RUNNERS:
        return _dry(b, args)
    if b == SWAP:
        return '--apply' not in args
    return bool(NAME_RX.search(b) or PATH_RX.search(x))


def _script_and_args(w):
    """(script path, its args) when the simple command runs a script directly or through an interpreter."""
    w = _strip_wrappers(w)  # timeout 600 python3 run_review.py: the duration is not the script (Viktor, chain-fleet)
    while w and (ASSIGN_RX.match(w[0]) or os.path.basename(w[0]) in WRAPPERS or w[0].startswith('-')):
        w = w[1:]  # VAR=x, env/time/nice ... and their options, in any order (env FOO=1 bash x.sh)
    if not w:
        return None, []
    if os.path.basename(w[0]) not in INTERPRETERS:
        return w[0], w[1:]
    rest = w[1:]
    i = 0
    while i < len(rest):
        x = rest[i]
        if x in ('-c', '-e', '-', '-p', '--eval', '--print', '-m', '--test'):
            return None, []
        if x in ('-W', '-X', '-r', '--require', '--import', '--loader', '-o'):
            i += 2
            continue
        if x.startswith('-'):
            i += 1
            continue
        return x, rest[i + 1:]
    return None, []


def action_of(w):
    """The label of a guarded ACTION run by this simple command, or None."""
    if is_commit(w):
        return 'git commit'
    script, args = _script_and_args(w)
    if not script:
        return None
    b = os.path.basename(script)
    if b in CODEX_RUNNERS and not _dry(b, args):
        return 'a valódi Codex-futás (' + b + ')'
    if b == SWAP and '--apply' in args:
        return 'a live-swap.sh --apply'
    return None


# package-manager options whose value is a separate word (Viktor 48870 KÖVETŐ 2: in `npm --prefix web test` the
# value "web" became plain[0], so the test run was not seen); the --opt=value form is one word and needs nothing
# Per manager, because the same letter differs: npm -w takes a workspace name, pnpm -w is --workspace-root (no value).
PKG_OPTS_WITH_ARG = {
    'npm': {'--prefix', '-C', '-w', '--workspace', '--loglevel'},  # -C = --prefix (measured on npm 10.9.9)
    'pnpm': {'-C', '--dir', '--filter', '-F', '--loglevel'},
    'yarn': {'--cwd'},
    'bun': {'--cwd'},
}
# pnpm and yarn run a package script or a local bin by its bare name (pnpm lint, yarn lint, pnpm vitest run)
SHORTHAND_PKG = {'pnpm', 'yarn'}
NPX_LIKE = {'npx', 'bunx', 'pnpx'}
DENO_CHECKS = {'test', 'lint', 'check'}


def _pkg_plain(rest, manager):
    """The non-option words of a package-manager command, with the values of its PKG_OPTS_WITH_ARG skipped."""
    takes = PKG_OPTS_WITH_ARG.get(manager, set())
    out, i = [], 0
    while i < len(rest):
        x = rest[i]
        if x in takes:
            i += 2
            continue
        if not x.startswith('-'):
            out.append(x)
        i += 1
    if manager == 'yarn' and out[:1] == ['workspace'] and len(out) > 2:
        out = out[2:]  # yarn workspace NAME test
    return out


def is_check(w, depth=0):
    """True when the simple command RUNS a test or a gate. A test file that is only an argument (git add x.test.ts,
    python3 - x.test.ts <<EOF, an editor script) is not a run."""
    while w and ASSIGN_RX.match(w[0]):
        w = w[1:]
    if not w or depth > 3:
        return False
    first = os.path.basename(w[0])
    rest = w[1:]
    if first in TOOL_WORDS:
        return True
    if first in WRAPPERS:
        return is_check(_strip_wrappers(w), depth + 1)
    if first == 'make':
        return any(x in RUN_TARGETS for x in rest if not x.startswith('-'))
    if first in PKG and first != 'bun' or (first == 'bun' and _pkg_plain(rest, 'bun')[:1] in (['test'], ['run'], ['x'])):
        plain = _pkg_plain(rest, first)
        if not plain:
            return False
        if plain[0] in ('test', 't') or plain[0].startswith('test:'):
            return True
        if plain[0] in ('run', 'run-script') and len(plain) > 1:
            return plain[1] in RUN_TARGETS or plain[1].startswith(('test:', 'lint:'))
        if plain[0] in ('exec', 'dlx', 'x'):
            return is_check(plain[1:], depth + 1)
        if first in SHORTHAND_PKG:
            return plain[0] in RUN_TARGETS or plain[0] in TOOL_WORDS or plain[0].startswith('lint:')
        return False
    if first in NPX_LIKE:
        plain = [x for x in rest if not x.startswith('-')]
        return is_check(plain, depth + 1) if plain else False
    if first == 'deno' and [x for x in rest if not x.startswith('-')][:1] in [[c] for c in DENO_CHECKS]:
        return True  # deno test / lint / check; deno run x.ts goes on as an interpreter
    if first in INTERPRETERS:
        i = 0
        while i < len(rest):
            x = rest[i]
            if x == '--test':
                return True
            if x == '-m':
                return rest[i + 1:i + 2] != [] and rest[i + 1].split('.')[0] in TOOL_WORDS
            if x in ('-c', '-e', '-', '-p', '--eval', '--print'):
                return False
            if x in ('-W', '-X', '-r', '--require', '--import', '--loader', '-o'):
                i += 2
                continue
            if x.startswith('-'):
                i += 1
                continue
            if _script_is_check(x, rest[i + 1:]):
                return True
            return is_check(rest[i + 1:], depth + 1) if rest[i + 1:i + 2] and os.path.basename(
                rest[i + 1]) in INTERPRETERS | PKG | TOOL_WORDS | {'npx', 'make'} else False
        return False
    return _script_is_check(w[0], rest)


def set_flags(w):
    """(errexit, pipefail) switched on by a `set ...` simple command."""
    if not w or w[0] != 'set':
        return False, False
    e = pf = False
    for i, x in enumerate(w[1:], 1):
        if x.startswith('-') and not x.startswith('--') and 'e' in x[1:]:
            e = True
        if x == 'pipefail' and w[i - 1].startswith('-') and w[i - 1].endswith('o'):
            pf = True
        if x == 'errexit' and w[i - 1].startswith('-') and w[i - 1].endswith('o'):
            e = True
    return e, pf


def verdict(payload):
    if payload.get('tool_name') != 'Bash':
        return None
    cmd = (payload.get('tool_input') or {}).get('command')
    if not isinstance(cmd, str) or not any(k in cmd for k in ('commit', 'run_review', 'launch_detached', 'live-swap')):
        return None
    segs = split_top(cmd)
    if not segs:
        return None
    # pipelines: [(members [words...], joiner_after)]
    pipes, cur = [], []
    for text, op in segs:
        cur.append(words(text))
        if op != '|':
            pipes.append((cur, op))
            cur = []
    if cur:
        pipes.append((cur, ''))
    if any(m and m[0] in KEYWORDS for members, _ in pipes for m in members):
        return None
    errexit = pipefail = False
    info = []  # per pipeline: (kind, errexit_at, label)  kind: None | 'kept' | 'lost'
    for members, _ in pipes:
        for m in members:
            e, pf = set_flags(m)
            errexit, pipefail = errexit or e, pipefail or pf
        checks = [k for k, m in enumerate(members) if is_check(m)]
        kind = None
        if checks:
            kind = 'kept' if (checks[-1] == len(members) - 1 or pipefail) else 'lost'
            if any(os.path.basename(_script_and_args(members[k])[0] or '') == DETACHED for k in checks):
                kind = 'detached'  # exit 0 once the child started: the dry's result is in the log, && cannot gate
        label = ' '.join(members[checks[0]])[:70] if checks else ''
        acts = [a for a in (action_of(m) for m in members) if a]
        info.append((kind, errexit, label, acts[0] if acts else None))
    for ci, (_, _, _, act) in enumerate(info):
        if not act:
            continue
        gated = True
        for k in range(ci - 1, -1, -1):
            joiner = pipes[k][1]
            kind, e_at, label, _ = info[k]
            if joiner != '&&':
                gated = False
            if kind == 'detached':
                return ('COMMIT-LANC-OR: a "' + label + '" a gyerek indítása után mindig 0-val lép ki, a dry eredménye '
                        'csak a logban van, ezért ' + act + ' a piros dry után is lefut (&& sem véd). A dry-t '
                        'run_review.py --dry-jal futtasd, vagy külön hívásban, a log elolvasása után. / '
                        'launch_detached.py exits 0 once started; its dry result is only in the log.')
            if kind == 'lost':
                return ('COMMIT-LANC-OR: a "' + label + '" eredménye csőben elvész (nincs set -o pipefail), ' + act +
                        ' piros futásnál is lefut. Futtasd a tesztet külön hívásban, vagy tedd elé: set -o pipefail. '
                        '/ The check is piped, its exit status is lost; the action would run on a red check.')
            if kind == 'kept' and not gated:
                return ('COMMIT-LANC-OR: a "' + label + '" és ' + act + ' között nem végig && áll (";", újsor, "||" '
                        'vagy "&"), így piros futásnál is lefut. A set -e itt NEM véd (mérve: a zsh eval alatt nem '
                        'állít meg). Kösd &&-del, vagy indítsd külön hívásban, a kimenet elolvasása után. / '
                        'The action is not &&-chained to the check before it; set -e does not stop it in this tool.')
    return None


def main():
    try:
        payload = json.loads(sys.stdin.read())
        reason = verdict(payload) if isinstance(payload, dict) else None
    except Exception:
        return 0
    if reason:
        sys.stderr.write(reason + '\n')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
