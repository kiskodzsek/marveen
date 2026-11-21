#!/usr/bin/env python3
"""PreToolUse gate (Write|Edit|MultiEdit|NotebookEdit|Bash): Patrik's evening block is written only by its scripts.

Why (Klodel 49761, card 0260694d, hibanapló 2026-11-21 18:06): store/patrik-este-blokk.json is a JSON list written
under a lock by scripts/lib/este_blokk.py (scripts/este-blokk-add.py puts an item in, scripts/este-blokk-drain.py
takes them out at 18:05); a hand write that reads the list and writes it back minutes later, unlocked, can drop an
item written in between (Viktor 41840 LOW 2, #278). The napi-eredmeny-este skill has said "do not read or write it by
hand" since 2026-11-14, yet the main agent's transcripts of the 14 days before 2026-11-21 hold 80 distinct commands
that wrote it directly (python json.dump/open, redirections, sed -i), 45 of them dated after that day (18 carry no
date); the sub-agents' none. This gate, replayed on those 321 main-agent and 66 sub-agent calls naming the file,
blocks exactly those 80 (card 0260694d). prod-tree-write-gate.py only logs for the main agent, and does not model an
interpreter.

An ACCIDENT guard, not a boundary: every agent runs as the same macOS user, and este_blokk.py itself writes the file
from inside a hook process, which no PreToolUse gate sees (and must not stop).

PROTECTED: store/patrik-este-blokk.json of the install, and its two sidecars este_blokk.py owns: .hiba.jsonl (the
parked items drain() hands back) and .lock. The install is CLAUDE_PROJECT_DIR, else two levels above this file. Names
are compared case-insensitively (APFS). Reading passes everywhere; so do the .utolso-drain.json copy and backups.

What blocks (exit 2):
- Write/Edit/MultiEdit/NotebookEdit whose path resolves to a protected file.
- Bash, for every simple command of the text (and the text a shell runs: `bash -c`, `eval`, `$( )` in double
  quotes, a here-document a shell reads; the parser of keychain-write-gate.py, as credentials-write-gate.py):
  - a redirection target (`>`, `>>`, `>|`, `&>`, `N>`, `<>`) that is a protected file;
  - the writers credentials-write-gate.py models, with this file as the name: cp/mv/ln/install/ditto/rsync/scp to OR
    from it (a copy by hand is a read by hand: drain's JSON is the read), tee/touch/truncate/sponge, dd of=, sed/perl
    -i, curl -o, wget -O, sort/base64 -o;
  - rm, unlink, shred, srm, trash of it;
  - an INTERPRETER (python*, node, perl, ruby, deno, bun, php, osascript) whose code (a `-c`/`-e`/`-E`/`--eval`/
    `-p` argument, a here-document or `<<<` text it reads) holds a string literal naming a protected file ('...',
    "...", and `...` outside Python; an absolute literal outside the install's store/ does not count) AND a write
    call: open(..) with a
    w/a/x/+ mode, json.dump(, .write(, write_text/write_bytes, os.replace/rename/remove/unlink/truncate, shutil
    copy/move, .unlink(, fs.*write*/append*/rename*/unlink*/copy*, File.write / IO.write, and a method call on any
    receiver named write*/appendFile*/rename*/unlink*/copyFile*/cp/rm/truncate*/createWriteStream (so
    `require('fs').writeFileSync(` and `fs.promises.writeFile(` count; a bare `.copy(`/`.append(` does not: a
    read-only Python script calls them on a dict or a list); Path.replace with ONE argument, os.open with a write
    flag, ruby FileUtils.mv/cp/rm/touch/... and File.delete/rename, perl's bare unlink( / rename( (Viktor 49783);
  - an interpreter whose NON-code argument or env prefix names the file (`python3 -c CODE store/...`, `P=store/...
    python3 -c CODE`, `python3 - store/... <<PY`) while its code holds a write call (Viktor 49773 L1);
  - a text that cannot be split (an open quote) while it names the file (fail-closed).
  - a copy or move INTO the store directory of a source whose name is protected (`cp /backup/patrik-este-blokk.json
    store/`, `cp -t store ...`; Viktor 49776 L2).
  Code options: -c/-e/-E/--eval/-p/--print, --eval=CODE, a python cluster ending in c (-Ic, -IBc, -IPc), a perl
  cluster ending in e (-pe, -ne); code is also read with the text's variables put in (`F=...; python3 -c
  "open(\"$F\", 'w')"`); perl open modes '>', '>>', '+<', '+>' count as a write. A target is resolved with the
  variables set earlier in the text (`X=...`, `for X in ...`, also a bare name in the for list), a `cd`/`pushd`
  earlier in the text and the payload's cwd; a cd the gate cannot resolve (an unknown variable, bare cd, `cd -`,
  popd) makes the cwd unknown. A nested text (bash -c, eval, a here-document a shell reads, `...` and $( ) in an
  UNQUOTED here-document's body) inherits them and the `X=... bash -c` prefix, up to 16 levels; deeper, a nested
  text naming the file blocks. A target that names the file but cannot be resolved (an unknown variable, no cwd)
  counts as the protected one.
Passes: every read (cat, jq, head, ls, stat, json.load without a write call), the two scripts
(`python3 -I scripts/este-blokk-add.py ...`, `... este-blokk-drain.py`: a script file's content is not read), a
here-document or quoted text no shell or interpreter runs (a HANDOFF.md, a skill or a card comment naming the file).
NOT MODELLED (passes unseen; Known limits, Viktor 49773): a script FILE that writes it; a name built at run time
('patrik-este' + '-blokk.json', a path read from a file); a value from command substitution (`X=$(...)`); code an
interpreter reads from a pipe (`echo CODE | python3`); os.system / subprocess / child_process calls inside
interpreter code (`os.system('echo > store/...')`, `subprocess.run(['cp', a, name])`); a glob that does not spell
the name (`rm store/*blokk.json`, `> store/patrik-*-blokk.json`); awk; find -delete; xargs (the name on stdin);
perl open without parentheses; deno eval, php -r; a nested for (`do for ...`); declare / local; a command held in a
variable and run with eval; a positional argument of bash -c (`bash -c 'echo > $1' _ name`); an interpreter the list
above does not name; writers credentials-write-gate.py does not model (tar x, unzip, an rsync or tar directory
restore that carries it). Over-blocks (the safe side): a write call on another file in code that also names the
block (the code reads the block by hand, which the skill forbids too), and sys.stdout.write in such code; after a
for loop its variable keeps the matching item, not the last; a cd inside a subshell acts outside too; after popd,
`cd -`, a bare cd or a cd to an unknown value a relative protected name counts; in another install a python
literal's relative name still counts (Viktor 49776 INFO); the mode regex reads a '+' concatenation as a '+' mode, so
json.load(open('store/'+'patrik-este-blokk.json')) blocks (Viktor 49783 INFO). On an error in a sibling module every
Bash text naming the block exits 2, the two scripts too.
Wiring: .claude/settings.json PreToolUse (the main agent; the sub-agents wrote it 0 times in 14 days, seeding them is
a separate decision). Deny log: store/este-blokk-write-gate/deny.log (sha256 of the text, never the text).
Tests: este-blokk-write-gate_test.py next to this file.
"""
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.environ.get('CLAUDE_PROJECT_DIR') or os.path.dirname(os.path.dirname(HERE))
STATE = os.path.join(ROOT, 'store', 'este-blokk-write-gate')
DENY_LOG = os.path.join(STATE, 'deny.log')
BLOCK = 'patrik-este-blokk.json'
NAMES = {BLOCK, BLOCK + '.hiba.jsonl', BLOCK + '.lock'}
HINT = 'este-blokk.json'
INTERP = re.compile(r'^(?:python[\d.]*|pypy[\d.]*|node|nodejs|perl[\d.]*|ruby|deno|bun|php|osascript)$')
CODE_OPTS = {'-c', '-e', '-E', '--eval', '-p', '--print'}
REMOVERS = {'rm', 'grm', 'unlink', 'gunlink', 'shred', 'gshred', 'srm', 'trash'}
LITERAL = re.compile(r"""(['"`])([^'"`\s]*?)(patrik-este-blokk\.json(?:\.hiba\.jsonl|\.lock)?)\1""", re.I)
PY_LITERAL = re.compile(r"""(['"])([^'"`\s]*?)(patrik-este-blokk\.json(?:\.hiba\.jsonl|\.lock)?)\1""", re.I)
PYTHON = re.compile(r'^(?:python[\d.]*|pypy[\d.]*)$')
# open(..) with a write mode within 300 characters; the classes before and at the pivot are disjoint and bounded
# (redos-probe, 2026-11-21: an unbounded `[^)]*?` was quadratic on many `open(` without a `)`: 2 s at 300 KB)
WRITE_CALL = re.compile(r"""open\s*\([^)]{0,300}?['"][rbt]{0,3}[wax+][rwaxbt+]{0,3}['"]|open\s*\([^)]{0,300}?['"](?:\+[<>]|>)|\bjson\.dump\s*\(|\.write\s*\(|"""
                        r"""\bwrite_(?:text|bytes)\s*\(|\bos\.(?:replace|rename|remove|unlink|truncate)\s*\(|"""
                        # Viktor 49783 L1: Path.replace with ONE argument (str.replace always takes two; a keyword such
                        # as datetime.replace(hour=0) is not it), os.open with a write flag, ruby FileUtils / File.delete,
                        # perl's bare unlink( / rename(
                        r"""\.replace\s*\(\s*[^,()=]{1,300}\)|\bos\.open\s*\([^)]{0,300}?\bO_(?:WRONLY|RDWR|TRUNC|CREAT|APPEND)\b|"""
                        r"""\bFileUtils\.(?:mv|move|cp|copy\w*|rm\w*|remove\w*|touch|install|ln\w*)\b|"""
                        r"""\bFile\.(?:delete|rename|unlink)\b|(?<![\w.$])(?:unlink|rename)\s*\(|"""
                        r"""\bshutil\.(?:copy\w*|move)\s*\(|\.unlink\s*\(|\bfs\w{0,32}\.\w{0,64}?(?:[wW]rite|[aA]ppend|[rR]ename|"""
                        r"""[uU]nlink|[cC]opy|[rR]m)\w{0,64}\s*\(|\b(?:File|IO)\.write\s*\(|"""
                        r"""\.\s*(?:write\w*|appendFile\w*|rename\w*|unlink\w*|copyFile\w*|cp(?:Sync)?|rm(?:Sync)?|"""
                        r"""truncate\w*|createWriteStream)\s*\(""")
HEREDOC_OP = re.compile(r"""(?<!<)<<(?!<)-?[ \t]*(['"]?)[^\s'";|&<>()]+\1""")
SUBST = re.compile(r"""`([^`]{0,4000})`|\$\(([^()]{0,4000})\)""")
MAX_DEPTH = 16  # quoting grows the text with every level: 11 levels of bash -c are 354 KB
CWD = None  # the payload's cwd
_CRED = None
_P = None


def store_dir():
    return os.path.realpath(os.path.join(ROOT, 'store')).casefold()


def parser():
    """The shell splitter of keychain-write-gate.py (shared by the write gates)."""
    global _P
    if _P is None:
        spec = importlib.util.spec_from_file_location('este_gate_parser', os.path.join(HERE, 'keychain-write-gate.py'))
        _P = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_P)
    return _P


def cred():
    """A private instance of credentials-write-gate.py whose name matcher is this gate's: its writer model (copy,
    tee, dd, sed -i, curl -o, ...) judges the block instead of .credentials.json. The real gate is untouched."""
    global _CRED
    if _CRED is None:
        spec = importlib.util.spec_from_file_location('este_gate_writers', os.path.join(HERE, 'credentials-write-gate.py'))
        _CRED = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_CRED)
        _CRED.is_cred = is_target
        _CRED.carries_cred = lambda word, env: False
        _CRED.NAME = BLOCK
    return _CRED


def protected_path(path, cwd):
    """True when path (absolute, or relative to cwd) is a protected file; a relative one without a cwd counts."""
    base = path.rstrip('/').rsplit('/', 1)[-1].casefold()
    if base not in NAMES:
        return False
    if not os.path.isabs(path):
        if not cwd:
            return True
        path = os.path.join(cwd, path)
    return os.path.realpath(os.path.dirname(path)).casefold() == store_dir()


def is_target(word, env, cwd=None):
    """True when a shell word, as a write target, is a protected file (a glob or brace that can match it counts)."""
    cwd = env.get('\0cwd', CWD) if cwd is None else cwd
    w = parser().expand(word, env)
    if w is None:
        return HINT in word.casefold()
    base = w.rstrip('/').rsplit('/', 1)[-1].casefold()
    if '{' in base and 'este' in base:
        return True
    if any(ch in base for ch in '*?['):
        return any(fnmatch.fnmatchcase(n, base) for n in NAMES)
    return protected_path(w, cwd)


def copies_into_store(rest, env):
    """True when a copy-like command puts a source whose name is protected into the store directory (the name kept):
    `cp /backup/patrik-este-blokk.json store/`, `mv x/patrik-este-blokk.json -t store` (Viktor round 2)."""
    ops = [w for w in rest if not w.startswith('-')]
    tdir = next((rest[k + 1] for k, w in enumerate(rest[:-1]) if w == '-t'), None)
    tdir = next((w.split('=', 1)[1] for w in rest if w.startswith('--target-directory=')), tdir)
    dest, srcs = (tdir, ops) if tdir is not None else ((ops[-1], ops[:-1]) if len(ops) >= 2 else (None, []))
    if dest is None:
        return False
    d = parser().expand(dest, env)
    cwd = env.get('\0cwd', CWD)
    if d is None or (not os.path.isabs(d) and not cwd):
        return False
    d = d if os.path.isabs(d) else os.path.join(cwd, d)
    if os.path.realpath(d).casefold() != store_dir():
        return False
    for w in srcs:
        v = parser().expand(w, env)
        base = (v if v is not None else w).rstrip('/').rsplit('/', 1)[-1].casefold()
        if base in NAMES or (v is None and HINT in w.casefold()):
            return True
    return False


def code_writes_block(code, cwd, prog=''):
    """True when interpreter code names a protected file in a string literal and holds a write call. A backtick
    delimits a literal in node/ruby/perl, not in Python: there it is markdown inside a string (a HANDOFF.md or a
    SKILL.md the code writes names the file in backticks; 7 of the 321 replayed main-agent calls)."""
    if not WRITE_CALL.search(code):
        return False
    for m in (PY_LITERAL if PYTHON.match(prog or '') else LITERAL).finditer(code):
        prefix, name = m.group(2), m.group(3)
        if not prefix.startswith('/'):
            return True  # relative or bare: the agent's cwd is the install (or a cd the text holds)
        if protected_path(prefix + name, cwd):
            return True
    return False


def interpreter_code(prog, rest):
    """The code texts an interpreter's arguments carry: -c/-e/--eval/-p/... (judge() adds a `<<<` word)."""
    out = [w.split('=', 1)[1] for w in rest if w.startswith(('--eval=', '--print='))]  # node --eval=CODE (Viktor 49783)
    for k, w in enumerate(rest[:-1]):
        if w in CODE_OPTS or (prog.startswith('perl') and re.fullmatch(r'-[a-zA-Z]*[eE]', w)) or (
                PYTHON.match(prog) and re.fullmatch(r'-[bBdEhiIOPqRsSuvx]+c', w)):
            out.append(rest[k + 1])
    return out


def judge(cmd, depth=0, cwd=None, env0=None):
    """The reason the text writes a protected file, or None."""
    cwd = CWD if cwd is None else cwd
    flat = (cmd + ' ' + ' '.join(str(v) for v in (env0 or {}).values())).replace('\\\n', '').replace("'", '').replace('"', '').replace('\\', '').casefold()
    if 'este-blokk' not in flat and 'patrik-este' not in flat and not ('{' in flat and 'este' in flat):
        return None
    P = parser()
    try:
        subs = []
        cmds, heredocs = P.split_commands(cmd, subs)
    except P.Unsplittable:
        return f'the command cannot be split (an open quote) and names {BLOCK}'
    nested = [(t, {}) for t in subs]
    env = dict(env0 or {})
    env['\0cwd'] = cwd
    interp_lines = set()
    argv_named = set()
    stdin_shell = False
    for idx, words in enumerate(cmds):
        for k, w in enumerate(words):
            if w and w[0] in '<>' and '>' in w or re.fullmatch(r'\d*>>?\|?|&>>?|\d*<>', w or ''):
                if k + 1 < len(words):
                    target = words[k + 1]
                elif idx + 1 < len(cmds) and cmds[idx + 1]:
                    target = cmds[idx + 1][0]
                else:
                    continue
                if is_target(target, env):
                    return f'a redirection writes to {BLOCK}'
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
        if len(words) >= 3 and words[0] == 'for' and words[2] == 'in':
            hit = next((w for w in words[3:] if is_target(w, env)), None) or next(
                (w for w in words[3:] if (P.expand(w, env) or '').rstrip('/').rsplit('/', 1)[-1].casefold() in NAMES),
                None)  # a bare name (`for f in patrik-este-blokk.json; do cp t store/$f`), Viktor 49783 L1
            v = None if hit is None else P.expand(hit, env)
            if v is None:
                env.pop(words[1], None)
            else:
                env[words[1]] = v
            continue
        if words and words[0] == 'unset':
            for w in words[1:]:
                env.pop(w, None)
            continue
        prog, rest = P.program(words)
        if prog in ('cd', 'pushd', 'popd'):
            # an unknown target (`cd $CLAUDE_PROJECT_DIR`, bare cd, `cd -`, popd) makes the cwd unknown, so a relative
            # protected name after it counts (fail-closed, Viktor 49783 L1)
            d = P.expand(rest[-1], env) if rest and prog != 'popd' and rest[-1] != '-' else None
            if d is None:
                env['\0cwd'] = None
            else:
                env['\0cwd'] = d if os.path.isabs(d) else (os.path.join(env['\0cwd'], d) if env['\0cwd'] else None)
            continue
        if prog in REMOVERS:
            if any(is_target(w, env) for w in rest if not w.startswith('-')):
                return f'{prog} removes {BLOCK}'
            continue
        if prog and INTERP.match(prog):
            interp_lines.add(idx)
            codes = interpreter_code(prog, rest) + [words[k + 1] for k, w in enumerate(words[:-1]) if w == '<<<']
            start = P.command_start(words) or 0
            if any(not w.startswith('-') and w not in codes and is_target(w, env) for w in rest) or any(
                    P.ASSIGN_RX.match(w) and is_target(w.split('=', 1)[1], env) for w in words[:start]):
                argv_named.add(idx)
                if any(WRITE_CALL.search(c) for c in codes):
                    return f'{prog} code writes to a path its arguments name ({BLOCK})'
            # program() drops redirections from rest, so the `<<<` text comes from the full word list
            for code in interpreter_code(prog, rest) + [words[k + 1] for k, w in enumerate(words[:-1]) if w == '<<<']:
                put = P.expand(code, env) if '$' in code else None
                if code_writes_block(code, env['\0cwd'], prog) or (put and code_writes_block(put, env['\0cwd'], prog)):
                    return f'{prog} code writes to {BLOCK} (a literal naming it and a write call)'
            # no continue: perl -i edits its operands in place, the writer model below judges it
        hit = cred().judge_program(prog, rest, env)
        if hit:
            return f'{prog} writes, copies or moves {BLOCK}'
        if prog in cred().COPY_LIKE and copies_into_store(rest, env):
            return f'{prog} copies or moves a {BLOCK} into store/'
        if prog in P.SHELLS:
            text = P.shell_command_arg(rest)
            pre = {}
            for w in words[:P.command_start(words) or 0]:
                if P.ASSIGN_RX.match(w):
                    name, value = w.split('=', 1)
                    v = P.expand(value, env)
                    if v is not None:
                        pre[name] = v
            if text is not None:
                nested.append((text, pre))
            elif P.shell_reads_stdin(rest):
                stdin_shell = True
                nested.extend((words[k + 1], pre) for k, w in enumerate(words[:-1]) if w == '<<<')
        elif prog == 'eval':
            nested.append((' '.join(rest), {}))
    if stdin_shell:
        for words in cmds:
            p, r = P.program(words)
            if p in ('echo', 'printf', 'cat'):
                nested.append((' '.join(r), {}))
                nested.extend((x, {}) for x in r)
    # Here-documents with an UNQUOTED delimiter expand `...` and $(...) in the body (Viktor 49783 L1). The parser drops
    # the quotes, so the delimiters are read again from the raw text in order; a count that does not match the parsed
    # here-documents treats every body as unquoted (fail-closed).
    ops = [m.group(1) for m in HEREDOC_OP.finditer(cmd)]
    quoted = ops if len(ops) == len(heredocs) else [''] * len(heredocs)
    for (body, _f, _l), q in zip(heredocs, quoted):
        if not q:
            nested.extend((t, {}) for pair in SUBST.findall(body) for t in pair if t)
    lines = {}  # (first, last) -> what the line runs, judged once per line (Viktor round 2: it was per here-document)
    for body, first, last in heredocs:
        if (first, last) not in lines:
            progs = [P.program(w) for w in cmds[first:last]]
            interp = [p for p, r in progs if p and INTERP.match(p)]
            lines[(first, last)] = (interp[0] if interp and any(i in interp_lines for i in range(first, last)) else None,
                                    any(i in argv_named for i in range(first, last)),
                                    any(p in P.SHELLS and P.shell_command_arg(r) is None and P.shell_reads_stdin(r)
                                        for p, r in progs))
        interp0, argv_line, shell_line = lines[(first, last)]
        if interp0 and code_writes_block(body, env['\0cwd'], interp0):
            return f'{interp0} code (a here-document) writes to {BLOCK}'
        if argv_line and WRITE_CALL.search(body):
            return f'a here-document code writes to a path its interpreter arguments name ({BLOCK})'
        if shell_line:
            nested.append((body, {}))  # a shell reading the here-document runs it; `bash script.sh - <<X` does not
    if depth >= MAX_DEPTH:
        if any('este-blokk' in t.casefold() or 'patrik-este' in t.casefold() for t, _ in nested):
            return f'a text nested deeper than {MAX_DEPTH} levels names {BLOCK} (fail-closed)'
        return None
    if True:
        for text, pre in nested:
            hit = judge(text, depth + 1, env['\0cwd'], dict(env, **pre))
            if hit:
                return hit
    return None


def decide(payload):
    """The deny reason for a PreToolUse payload, or None (the replay entry point)."""
    global CWD
    tool = payload.get('tool_name')
    ti = payload.get('tool_input') or {}
    cwd = payload.get('cwd')
    CWD = cwd if isinstance(cwd, str) and os.path.isabs(cwd) else None
    if tool in ('Write', 'Edit', 'MultiEdit', 'NotebookEdit'):
        p = ti.get('file_path') if tool != 'NotebookEdit' else ti.get('notebook_path')
        if isinstance(p, str) and protected_path(p, CWD):
            return f'{tool} writes to {BLOCK}'
        return None
    if tool == 'Bash':
        cmd = ti.get('command')
        return judge(cmd) if isinstance(cmd, str) else None
    return None


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
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    why = decide(payload)
    if not why:
        return 0
    ti = payload.get('tool_input') or {}
    log_deny(hashlib.sha256(json.dumps(ti, sort_keys=True, ensure_ascii=False).encode()).hexdigest(), why)
    print(f'ESTE-BLOKK-KAPU (Klodel 49761, kártya 0260694d): {why}. A store/patrik-este-blokk.json-t CSAK a két '
          f'szkript írja, zár alatt: tétel BE: python3 -I scripts/este-blokk-add.py --tipus <tipus> --agens <ki> '
          f'--forras <honnan> --mi "<mi>" [--javaslat "<mit>"]; tétel KI (18:05): python3 -I scripts/este-blokk-drain.py. '
          f'Küldés-hiba után a .utolso-drain.json tételeit ugyanígy, az add.py-jal tedd vissza. Kézi írás elveszítheti '
          f'a közben beírt tételt (#278). Olvasni szabad.', file=sys.stderr)
    return 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:  # fail-closed: the cheap pre-check lets only a text naming the block this far
        print(f'ESTE-BLOKK-KAPU error: {type(e).__name__}', file=sys.stderr)
        sys.exit(2)
