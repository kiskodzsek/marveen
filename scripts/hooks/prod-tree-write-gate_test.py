#!/usr/bin/env python3
"""Tests for prod-tree-write-gate.py (card 11c4a5fe).
Run: /usr/bin/python3 -I scripts/hooks/prod-tree-write-gate_test.py (and under a second python3).
A synthetic prod tree in a temp dir; decide() and run() are called directly (no env seam)."""
import atexit, importlib.util, json, os, random, shutil, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location('gate', os.path.join(HERE, 'prod-tree-write-gate.py'))
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

def _base():
    # The cases use /tmp as an OUTSIDE cwd; a synthetic prod tree under /tmp would make /tmp its ancestor, where the
    # gate is (rightly) strict. ubuntu CI and a TMPDIR under /tmp put tempfile there, so the tree goes elsewhere.
    b = os.path.realpath(tempfile.gettempdir())
    t = os.path.realpath('/tmp')
    if b == t or b.startswith(t + '/'):
        b = os.path.join(os.path.realpath(os.path.expanduser('~')), '.cache')
        os.makedirs(b, exist_ok=True)
    return b


T = tempfile.mkdtemp(prefix='ptwg-', dir=_base())
atexit.register(shutil.rmtree, T, True)
HOME = os.path.realpath(T)
P = os.path.join(HOME, 'marveen')           # the prod root; HOME/marveen = the ~/marveen form
BASE = 'marveen'
WT = P + '/agents/dave/repos/wt'
LOG = os.path.join(HOME, 'log')


def setup_tree():
    for d in ('.git', 'scripts/hooks', 'src', '.claude', 'store', 'agents/kernel/.claude-config/projects/x',
              'agents/pulzus/.claude-config/projects/x', 'agents/pulzus/scripts', 'agents/dave/repos/wt/scripts',
              'agents/x/.claude', 'other/.git'):
        os.makedirs(os.path.join(P, d), exist_ok=True)
    for f in ('CLAUDE.md', '.mcp.json', 'package.json', 'package-lock.json', 'store/autonomy-config.json',
              'store/verified-recipients.json', 'scripts/x.py', 'README.md'):
        open(os.path.join(P, f), 'w').close()
    open(WT + '/.git', 'w').write('gitdir: ' + P + '/.git/worktrees/wt\n')
    os.symlink(P + '/scripts', P + '/agents/kernel/lnk')
    os.symlink(P + '/agents/kernel/loop2', P + '/agents/kernel/loop1')
    os.symlink(P + '/agents/kernel/loop1', P + '/agents/kernel/loop2')
    os.makedirs(os.path.join(LOG, 'seen'), exist_ok=True)
    open(os.path.join(LOG, 'gate.jsonl'), 'w').close()


setup_tree()
SUB_TP = P + '/agents/kernel/.claude-config/projects/x/s.jsonl'
MAIN_TP = HOME + '/.claude/projects/-x/s.jsonl'


def bash(cmd, cwd=P):
    return {'tool_name': 'Bash', 'tool_input': {'command': cmd}, 'cwd': cwd, 'transcript_path': SUB_TP}


def write(path, tool='Write', cwd=P):
    key = 'notebook_path' if tool == 'NotebookEdit' else 'file_path'
    return {'tool_name': tool, 'tool_input': {key: path}, 'cwd': cwd, 'transcript_path': SUB_TP}


def d(payload):
    return gate.decide(payload, P, HOME)[0]


def subst(s):
    return s.replace('P/', P + '/').replace(' P ', ' ' + P + ' ').replace('=P', '=' + P).replace('BASE', BASE)


BASH_DENY = [  # (command, cwd)
    ('echo x > scripts/hooks/a.py', P), ('echo x >> P/src/a.ts', '/tmp'), ('cat <<EOF > .claude/x\nhi\nEOF', P),
    ('tee scripts/a < /dev/null', P), ('cp /tmp/a P/scripts/', '/tmp'), ('cp /tmp/package.json P/', '/tmp'),
    ('mv scripts/a /tmp/', P), ('rm -rf scripts', P), ('rm -rf ' + P, '/tmp'),
    ('find ' + P + ' -name "*.bak" -delete', '/tmp'), ('find . -name x -delete', P),
    ("sed -i '' s/a/b/ scripts/x.py", P), ('perl -pi -e s/a/b/ src/x', P), ('dd if=/dev/zero of=scripts/x', P),
    ('touch .claude/x', P), ('mkdir -p src/new', P), ('chmod +x scripts/x.py', P), ('ln -s /tmp/x scripts/y', P),
    ('install -m 644 /tmp/a scripts/a', P), ('rsync -a /tmp/a/ scripts/', P), ('curl -s -o scripts/x https://e', P),
    ('truncate -s 0 package.json', P), ('cp -t scripts /tmp/a', P), ('rm scripts/*.bak', P),
    # K1 case
    ('echo x > SCRIPTS/hooks/x', P), ('echo x > .Claude/x', P), ('echo x > Src/x', P), ('echo x > claude.MD', P),
    ('echo x > P/SCRIPTS/hooks/x', '/tmp'), ('touch P/.CLAUDE/settings.json', '/tmp'),
    # root files (Klodel 42812)
    ('echo {} > P/.mcp.json', '/tmp'), ('echo > CLAUDE.md', P), ('echo > store/autonomy-config.json', P),
    ('echo > package-lock.json', P),
    # K2 forms
    ('cd scripts && echo x > hooks/a.py', P), ('git --work-tree=P checkout .', '/tmp'),
    ('GIT_DIR=P/.git git stash', '/tmp'), ('cd P/agents/kernel && cd ../../scripts && rm a', '/tmp'),
    ('cd ~/BASE && echo > scripts/x', '/tmp'), ('echo x > "$HOME/BASE/scripts/x"', '/tmp'),
    ('X=P/scripts; echo > $X/a', '/tmp'), ('echo x > "$(echo P/scripts/x)"', '/tmp'),
    ('bash -c "echo x > P/scripts/a"', '/tmp'), ("sh -c 'rm P/src/a'", '/tmp'), ('eval "rm P/src/a"', '/tmp'),
    ('sudo rm P/scripts/a', '/tmp'), ('env FOO=1 rm P/scripts/a', '/tmp'), ('timeout 10 rm P/scripts/a', '/tmp'),
    ('find scripts -name x | xargs rm', P), ("bash <<'EOF'\nrm P/scripts/a\nEOF", '/tmp'),
    ('x=$(rm P/scripts/a)', '/tmp'), ('echo "x > P/scripts/a', '/tmp'), ('echo x > `echo P/scripts/a`', '/tmp'),
    ('echo x > P/agents/../scripts/a', '/tmp'), ('echo x > P/agents/kernel/lnk/a', '/tmp'),
    ('echo x > /System/Volumes/DataP/scripts/a', '/tmp'), ('cd P/agents/kernel; echo > ../../src/a', '/tmp'),
    ('export GIT_DIR=P/.git; git reset --hard', '/tmp'), ('for f in a b; do rm "scripts/$f"; done', P),
    ('cd "$X" && rm a # P/scripts/', '/tmp'), ("echo $'x' > scripts/a", P),
    # K3 git on the prod tree
    ('git checkout -- scripts/x.py', P), ('git switch main', P), ('git restore scripts/x.py', P),
    ('git reset --hard', P), ('git stash', P), ('git stash pop', P), ('git apply x.diff', P), ('git am x.mbox', P),
    ('git cherry-pick abc', P), ('git revert abc', P), ('git merge origin/main', P), ('git pull', P),
    ('git rebase origin/main', P), ('git clean -fd', P), ('git mv a b', P), ('git rm scripts/x.py', P),
    ('git read-tree -u HEAD', P), ('git submodule update', P), ('git checkout-index -a', P),
    ('git -C P stash', '/tmp'), ('git stash', P + '/agents/kernel'), ('git -c x=y -C P checkout .', '/tmp'),
    ('git --git-dir=P/.git --work-tree=P reset --hard', '/tmp'), ('git worktree add scripts/wt', P),
    # Pulzus: no exception (Viktor 42810 2.)
    ('git show origin/main:scripts/x.py > scripts/x.py', P),
    # cwd writers
    ('npm install', P), ('npm --prefix P install', '/tmp'), ('patch -p1 < x.diff', P), ('tar -xf a.tar', P),
    ('tar -xf a.tar -C P/scripts', '/tmp'), ('unzip a.zip -d P/src', '/tmp'), ('npm ci', P + '/scripts'),
    # replay-derived (E1): loops, find -exec writers
    ('for f in P/scripts/a P/src/b; do rm $f; done', '/tmp'), ('for f in a b; do echo > scripts/$f; done', P),
    ('find P/scripts -name "*.bak" -exec rm {} +', '/tmp'), ("find . -exec sed -i '' s/a/b/ {} +", P),
    ('find P -type f -exec chmod 644 {} \\;', '/tmp'), ('mkdir P/newdir && cd P/newdir && git checkout .', '/tmp'),
    ('cd P/scripts/nope && git checkout .', '/tmp'),
    ('for d in ~/m*; do rm -rf "$d/scripts"; done', '/tmp'), ('mkdir -p $(dirname P/scripts/x/y)', '/tmp'),
    ('Q=P/scripts/a.txt; echo > ${Q%.txt}.json', '/tmp'), ('python3 P/scripts/x.py > "$OUT"; ls P/src', '/tmp'),
    ('B=scripts/m-$(date +%s); mkdir -p $B', P), ('B=scr$(date); cd $B && echo > x', P),
    ('cd $(echo scripts) && echo > x', P), ('X=P/src; bash -c "rm -rf $X/a"', '/tmp'),
    ('X=P/src; eval "rm $X/a"', '/tmp'), ('GIT_DIR=$(mktemp) git stash; Y=P/scripts/$(date); echo > $Y', '/tmp'), ('while read f; do echo > $f; done < <(ls P/src)', '/tmp'),
]

BASH_ALLOW = [
    ('cat P/scripts/x.py', '/tmp'), ('grep -r foo P/scripts', '/tmp'), ('git -C P log --oneline -3', '/tmp'),
    ('git -C P status', '/tmp'), ('git -C P diff', '/tmp'), ('git -C P fetch -q origin', '/tmp'),
    ('git -C P show origin/main:scripts/x.py', '/tmp'),
    ('git -C P worktree add P/agents/kernel/repos/wt-new -b x', '/tmp'), ('git stash list', P),
    ('git clean -n', P), ('git status --porcelain', P), ('git merge-base HEAD origin/main', P),
    ('python3 -I P/scripts/foo.py > /tmp/out', '/tmp'), ('python3 -I P/scripts/foo.py 2>&1 | tail -5', '/tmp'),
    ('D=$(mktemp -d); python3 P/scripts/x.py > "$D/out"', '/tmp'),
    ('cd P/agents/dave/repos/wt && echo x > scripts/a', '/tmp'), ('git checkout -b x', WT), ('git stash', WT),
    ('cd P/agents/dave/repos/wt && git reset --hard', '/tmp'), ('echo > /tmp/x', P),
    ('cp P/scripts/x.py /tmp/', '/tmp'), ('cp P/scripts/x.py P/agents/dave/repos/wt/scripts/x.py', '/tmp'),
    ('bash agents/pulzus/scripts/restore-from-main.sh --apply', P), ('echo "scripts/x" > /tmp/notes', P),
    ("cat > /tmp/x <<'EOF'\nrm P/scripts/a\necho > P/src/b\nEOF", '/tmp'), ('npm install', WT),
    ('rm -rf /tmp/x', P), ('find /tmp/x -delete', P), ('echo hi 2>/dev/null', P), ('ls 2>&1', P),
    ('python3 -c "open(\'P/scripts/x\',\'w\')"', '/tmp'), ('touch *.txt', '/tmp'), ('rm $X', '/tmp'),
    ('echo x > P/README.md', '/tmp'), ('echo x > P/store/verified-recipients.json', '/tmp'),
    ('mkdir -p P/agents/kernel/work/new', '/tmp'), ('touch P/agents/x/.claude/settings.json', '/tmp'),
    ('curl -s https://e > /tmp/x', P), ('git -C P/other checkout .', '/tmp'),
    ('node P/scripts/agent-msg.mjs < /tmp/in', '/tmp'), ('sed -n 1,5p scripts/x.py', P),
    ('python3 - <<"PY"\nopen("P/scripts/x","w")\nPY', '/tmp'), ('tar -tf a.tar', P), ('unzip -l a.zip', P),
    ('find P/agents/kernel -name "*.pyc" -delete', '/tmp'), ('cd /tmp && rm -f a', P), ('cp /tmp/a P', '/tmp'),
    # replay-derived (E1)
    ('git patch-id --stable < <(git diff a b)', P), ('find P -xdev -type f -exec stat -f %z {} + | sort', '/tmp'),
    ('find P/scripts/hooks -name "*.py" -exec ls -l {} +', '/tmp'), ('find P/scripts -exec cat {} +', '/tmp'),
    ("K=P/store/kep-kapu; for f in $K/a.ok $K/b.ok; do sed -i '' s/a/b/ $f; done; cd P/scripts/hooks && ls", '/tmp'),
    ('for a in dave kernel; do d=$a/x; [ -d $d ] || continue; done; grep x P/scripts/y', P + '/agents'),
    ('git -C P worktree add P/agents/kernel/repos/wt-q -b q && cd P/agents/kernel/repos/wt-q && git checkout -b y',
     '/tmp'), ('git -C P/agents/kernel/repos/wt-nope rebase origin/main', '/tmp'),
    ('bash P/scripts/worktree-add.sh P P/agents/kernel/repos/wt-z x && cd P/agents/kernel/repos/wt-z && git apply a',
     '/tmp'),
    ('cat P/scripts/x.py > $TMPDIR/x', '/tmp'),
    ('L=/tmp/a/b.log && mkdir -p $(dirname $L) && cat P/scripts/x.py > $L', '/tmp'),
    ('Q=/tmp/v1.txt; python3 x.py > ${Q%.txt}.json # P/scripts', '/tmp'),
    ('for d in ~/.gh-pr-outside-*; do rm "$d/b.md"; done # P/scripts', '/tmp'),
    ('bash P/scripts/worktree-add.sh P P/agents/k/repos/wt && echo x >> "$(git rev-parse --git-dir)/info/exclude"',
     '/tmp'), ('python3 -I P/scripts/x.py > "$OUT"', '/tmp'), ('echo hi > "$(pwd)/a"', '/tmp'),
    ('B=agents/pulzus/backups/m-$(date +%H%M%S); mkdir -p $B; cp .claude/settings.json $B/', P),
    ('for w in a b; do p=agents/kernel/repos/$w; echo > $p/x; done', P),
    ('B=agents/pulzus/backups/m-$(date +%s); mkdir -p $B; cd $B && shasum * > SHA256SUMS', P),
    ('X=/tmp/q; nohup bash -c "echo hi > $X/out; cat P/scripts/x.py" &', '/tmp'),
]


class Decide(unittest.TestCase):
    def test_write_tools_deny(self):
        for tool in ('Write', 'Edit', 'MultiEdit', 'NotebookEdit'):
            for p in ('scripts/hooks/x.py', 'src/a.ts', '.claude/settings.json', 'CLAUDE.md', '.mcp.json',
                      'package.json', 'package-lock.json', 'store/autonomy-config.json', 'SCRIPTS/hooks/x',
                      '.Claude/x', 'Src/x', 'claude.MD', 'agents/kernel/lnk/x', 'agents/../scripts/x', 'scripts',
                      'STORE/Autonomy-Config.json'):
                self.assertEqual(d(write(P + '/' + p, tool)), 'deny', (tool, p))
            self.assertEqual(d(write('scripts/x', tool, cwd=P)), 'deny', tool)
            self.assertEqual(d(write('/System/Volumes/Data' + P + '/scripts/x', tool)), 'deny', tool)

    def test_write_tools_allow(self):
        for p in (P + '/agents/kernel/x', WT + '/scripts/x', P + '/agents/x/.claude/settings.json',
                  P + '/store/verified-recipients.json', P + '/README.md', '/tmp/x', P + '/agents/kernel/loop1/x'):
            self.assertEqual(d(write(p)), 'allow', p)

    def test_write_tools_fail_closed(self):
        for inp in ({}, {'file_path': 5}, {'file_path': ''}, {'file_path': P + '/a\x00b'}, {'file_path': 'x' * 9000}):
            self.assertEqual(gate.decide({'tool_name': 'Write', 'tool_input': inp, 'cwd': P}, P, HOME)[0], 'deny', inp)
        self.assertEqual(gate.decide({'tool_name': 'Edit', 'tool_input': 'x'}, P, HOME)[0], 'deny')
        self.assertEqual(d(write('rel/x', cwd=None)), 'deny')

    def test_bash_deny(self):
        bad = [(cmd, cwd, r) for cmd, cwd in BASH_DENY for r in [gate.decide(bash(subst(cmd), cwd), P, HOME)]
               if r[0] != 'deny']
        self.assertEqual(bad, [])

    def test_bash_allow(self):
        bad = [(cmd, cwd, r) for cmd, cwd in BASH_ALLOW for r in [gate.decide(bash(subst(cmd), cwd), P, HOME)]
               if r[0] != 'allow']
        self.assertEqual(bad, [])

    def test_lexer_error_fail_open_only_without_protected_text(self):
        r = gate.decide(bash('echo "unterminated', '/tmp'), P, HOME)
        self.assertEqual(r[0], 'allow')
        self.assertTrue(r[2])
        self.assertEqual(gate.decide(bash('echo "x ' + P + '/src/a', '/tmp'), P, HOME)[0], 'deny')

    def test_resolve_error_1a(self):
        self.assertEqual(gate.decide(bash('echo x > ' + P + '/scripts/\x00a', '/tmp'), P, HOME)[0], 'deny')
        r = gate.decide(bash('echo x > /tmp/\x00a', '/tmp'), P, HOME)
        self.assertEqual(r[0], 'allow')
        self.assertTrue(r[2])

    def test_viktor_42855(self):
        """Viktor 42855 repro (agents/viktor/reports/2026-11-15-prod-tree-write-gate-hash-repro.txt), no subst()."""
        A, AX = P + '/agents', P + '/agents/x'
        deny = [  # M1: the first command of a brace group
            ('{ rm ../../CLAUDE.md; }', AX), ('{ cp /dev/null ../../CLAUDE.md; }', AX),
            ('{ tee ../../CLAUDE.md <<< x; }', AX), ('{ cd ../..; echo x > CLAUDE.md; }', AX),
            ('{ chmod 600 ' + P + '/{scripts,zzz}/hooks/h.py; }', '/'), ('{ git -C .. checkout .; }', A),
            ('{ git -C .. rm -f scripts/x.py; }', A), ('{ git -C .. stash -k; }', A),
            ('{ git -C ../.. checkout .; }', AX), ('{ git -C ' + A + ' -C .. checkout .; }', '/'),
            ('{ git -C .. read-tree --reset -u HEAD~1; }', A), ('{ rm -rf ../../scripts; } && true', AX),
            ('if true; then { rm ../../.mcp.json; }; fi', AX),
            # L1: time + inline assignments
            ('time GIT_DIR=' + P + '/.git GIT_WORK_TREE=' + P + ' git reset --hard', A),
            ('time -p GIT_WORK_TREE=' + P + ' git checkout .', '/'),
            # L3: the root from a substitution
            ('echo x > "$(echo ' + P + ')/scripts/x.py"', '/'), ('echo x > $(printf %s ' + P + ')/.mcp.json', '/'),
            ('echo x > $(git rev-parse --show-toplevel)/CLAUDE.md', AX), ('echo x > "$R"/scripts/a', P),
            ('cp /tmp/a `git rev-parse --show-toplevel`/src/a', P + '/agents'),
            # L4: the raw-text alternatives on a lexer error, one per protected file/dir
            ('echo "x ' + P + '/CLAUDE.md', '/tmp'), ('echo "x ' + P + '/.mcp.json', '/tmp'),
            ('echo "x ' + P + '/package.json', '/tmp'), ('echo "x ' + P + '/package-lock.json', '/tmp'),
            ('echo "x ' + P + '/store/autonomy-config.json', '/tmp'), ('echo "x ' + P + '/.claude/settings.json', '/tmp'),
            ('echo "x ' + P + '/scripts/a', '/tmp'),
            # L4: git worktree remove/move of the prod root is destructive (the root is an ancestor)
            ('git worktree remove --force ' + P, '/tmp'), ('git worktree move ' + P + ' /tmp/x', '/tmp'),
        ]
        allow = [
            ('{ cd ..; echo x > CLAUDE.md; }', AX),            # lands in agents/: not protected (correct allow)
            ('{ echo x > /tmp/a; } 2>/dev/null', P), ('{ cat CLAUDE.md; }', P), ('echo {a,b}', P),
            ('echo x > $(git rev-parse --show-toplevel)/scripts/a', WT),   # a worktree, not the prod checkout
            ('cat $(git rev-parse --show-toplevel)/CLAUDE.md', P),          # a read
            ('git apply --check x.diff', P), ('git apply --stat x.diff', P),
            ('git worktree remove ' + P + '/agents/dave/repos/wt', '/tmp'),
            ('time git status', P),
            # E1-replay false positives of the first L3 draft (agent home inside the prod repo, unresolved variable)
            ('echo x > $N/scripts/hooks/old_test.py', AX), ('echo x > $N/scripts/hooks/old_test.py', WT),
            ("sed -i '' s/a/b/ ${j/a-/b-}/scripts/x", P + '/agents/dave'),
        ]
        bad = [(c, w, r) for c, w in deny for r in [gate.decide(bash(c, w), P, HOME)] if r[0] != 'deny']
        bad += [(c, w, r) for c, w in allow for r in [gate.decide(bash(c, w), P, HOME)] if r[0] != 'allow']
        self.assertEqual(bad, [])

    def test_other_tools_allow(self):
        self.assertEqual(gate.decide({'tool_name': 'Read', 'tool_input': {'file_path': P + '/scripts/x'}},
                                     P, HOME)[0], 'allow')


def run(payload, raw=None):
    return gate.run(raw if raw is not None else json.dumps(payload), P, LOG, HOME, now=1794733055)


def log_rows():
    with open(os.path.join(LOG, 'gate.jsonl')) as f:
        return [json.loads(l) for l in f if l.strip()]


class Run(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(os.path.join(LOG, 'seen'))
        os.makedirs(os.path.join(LOG, 'seen'))
        open(os.path.join(LOG, 'gate.jsonl'), 'w').close()

    def test_sub_agent_denied_and_logged(self):
        out = run(bash('echo x > scripts/a'))
        o = json.loads(out)['hookSpecificOutput']
        self.assertEqual(o['permissionDecision'], 'deny')
        self.assertIn('worktree + PR', o['permissionDecisionReason'])
        self.assertIn('üzenj Klodelnek a pontos paranccsal', o['permissionDecisionReason'])
        rows = log_rows()
        self.assertEqual([r['decision'] for r in rows], ['seen', 'deny'])
        self.assertEqual(rows[1]['agent'], 'kernel')

    def test_viktor_delta_v2(self):
        """Viktor v2 delta (card 11c4a5fe): quoted brace expansion, time/function group forms, exact rev-parse root."""
        A, AX = P + '/agents', P + '/agents/x'
        deny = [  # brace expansion with a quoted / escaped space is still one expansion word
            ('rm ../../{CLAUDE.md,"x y"}', AX), ("rm ../../{CLAUDE.md,'x y'}", AX), ('rm ../../{CLAUDE.md,x\\ y}', AX),
            ('rm ../../{CLAUDE.md,x" "y}', AX), ('chmod 600 ' + P + '/{scripts,"a b"}/x.py', '/'),
            ('echo x > ../../{CLAUDE.md,"a b"}', AX),
            # time / function keyword forms of a command or a group
            ('time ! rm ../../CLAUDE.md', AX), ('time -p ! rm ../../CLAUDE.md', AX), ('time { rm ../../CLAUDE.md; }', AX),
            ('time ! GIT_WORK_TREE=' + P + ' git checkout .', '/'), ('function f { rm ../../CLAUDE.md; }; f', AX),
            ('function f() { rm ../../CLAUDE.md; }; f', AX), ('function f { { rm ../../CLAUDE.md; }; }; f', AX),
            # the repository root of the cwd, resolved exactly (not only as the direct prefix of a protected part)
            ('cd "$(git rev-parse --show-toplevel)" && echo x > CLAUDE.md', AX),
            ('cd $(git rev-parse --show-toplevel) && rm CLAUDE.md', AX),
            ('R=$(git rev-parse --show-toplevel); echo x > $R/CLAUDE.md', AX),
            ('R=$(git rev-parse --show-toplevel); echo x > "$R/.mcp.json"', AX),
            ('echo x > $(git rev-parse --show-toplevel 2>/dev/null)/CLAUDE.md', AX),
            ('echo x > $(git -C .. rev-parse --show-toplevel)/CLAUDE.md', AX),
            ('echo x > $(echo ' + P + ' )/CLAUDE.md', '/'),
            # Viktor v2 delta L4: the closers between the root and the protected part, with an UNRESOLVED
            # substitution (the raw rule, not the exact resolution, has to catch these)
            ('echo x > "$(cat /x; echo ' + P + ')"/scripts/a', '/'), ('echo x > `cat /x; echo ' + P + '`/scripts/a', '/'),
            ("echo x > \"$(cat /x; echo '" + P + "')\"/scripts/a", '/'), ('echo x > $(cat /x; echo ' + P + ')/.mcp.json', '/'),
        ]
        allow = [
            ('time ! git status', P), ('time { echo x; }', P), ('function f { echo x; }; f', P),
            ('echo x > $(git rev-parse --show-toplevel)/agents/x/a.txt', AX),
            ('R=$(git rev-parse --show-toplevel); echo x > $R/README.md', AX),
            ('cd "$(git rev-parse --show-toplevel)" && git status', AX),
            ('cd "$(git rev-parse --show-toplevel)" && echo x > agents/x/a.txt', AX),
            ('echo x > $(git rev-parse --show-toplevel)/scripts/a', WT),
            ('cat $(git rev-parse --show-toplevel)/CLAUDE.md', AX),
        ]
        bad = [(c, w, r) for c, w in deny for r in [gate.decide(bash(c, w), P, HOME)] if r[0] != 'deny']
        bad += [(c, w, r) for c, w in allow for r in [gate.decide(bash(c, w), P, HOME)] if r[0] != 'allow']
        self.assertEqual(bad, [])

    def test_unresolved_allow_logged(self):
        """Viktor 42855 L2: an allowed write with an unresolved target leaves an unresolved-allow row (sub-agent)."""
        self.assertEqual(run(bash('echo x > $UNSET/foo', '/tmp')), '')
        self.assertEqual(run(bash('echo x > ' + P + '/scripts/x.py', '/tmp')) != '', True)
        rows = log_rows()
        self.assertEqual([r['decision'] for r in rows], ['seen', 'unresolved-allow', 'deny'])
        self.assertIn('$UNSET/foo', rows[1]['input'])
        open(os.path.join(LOG, 'gate.jsonl'), 'w').close()
        p = bash('echo x > $UNSET/foo', '/tmp')
        p['transcript_path'] = MAIN_TP
        self.assertEqual(run(p), '')
        self.assertEqual([r['decision'] for r in log_rows()], ['seen'])

    def test_allow_writes_nothing_to_stdout(self):
        self.assertEqual(run(bash('ls')), '')
        self.assertEqual([r['decision'] for r in log_rows()], ['seen'])

    def test_main_and_unknown_never_denied(self):
        for tp, who in ((MAIN_TP, 'main'), (P + '/.channels-config/projects/x/s.jsonl', 'main'), (None, 'unknown'),
                        ('', 'unknown'), (5, 'unknown')):
            open(os.path.join(LOG, 'gate.jsonl'), 'w').close()
            for cmd, cwd in BASH_DENY:
                p = bash(subst(cmd), cwd)
                p['transcript_path'] = tp
                self.assertEqual(run(p), '', (who, cmd))
            p = write(P + '/scripts/x')
            p['transcript_path'] = tp
            self.assertEqual(run(p), '')
            rows = [r for r in log_rows() if r['decision'] == 'would-deny']
            self.assertTrue(rows and all(r['agent'] == who for r in rows), who)

    def test_identity(self):
        prod = gate.Prod(P)
        self.assertEqual(gate.identify(SUB_TP, prod), 'kernel')
        self.assertEqual(gate.identify(P + '/agents/kernel/.claude-config/projects/x/s/subagents/a-1.jsonl', prod),
                         'kernel')
        self.assertEqual(gate.identify(P + '/AGENTS/Pulzus/.claude-config/projects/x/s.jsonl', prod), 'pulzus')
        self.assertEqual(gate.identify(P + '/agents/kernel/other/s.jsonl', prod), 'main')
        self.assertEqual(gate.identify(MAIN_TP, prod), 'main')
        self.assertEqual(gate.identify('x\x00y', prod), 'unknown')

    def test_pulzus_has_no_exception(self):
        p = bash('git show origin/main:scripts/x.py > scripts/x.py')
        p['transcript_path'] = P + '/agents/pulzus/.claude-config/projects/x/s.jsonl'
        out = run(p)
        self.assertIn('"deny"', out)
        msg = json.loads(out)['hookSpecificOutput']['permissionDecisionReason']
        self.assertIn('restore-from-main.sh', msg)               # Klodel 42825 (1)
        self.assertIn('üzenj Klodelnek a pontos paranccsal', msg)
        self.assertNotIn('restore-from-main.sh', json.loads(run(bash('echo > scripts/a')))['hookSpecificOutput']
                         ['permissionDecisionReason'])          # only Pulzus gets the deploy hint
        p = bash('bash agents/pulzus/scripts/restore-from-main.sh --apply')
        p['transcript_path'] = P + '/agents/pulzus/.claude-config/projects/x/s.jsonl'
        self.assertEqual(run(p), '')

    def test_seen_once_per_session(self):
        run(bash('ls'))
        run(bash('pwd'))
        p = bash('ls')
        p['transcript_path'] = MAIN_TP
        run(p)
        self.assertEqual([(r['decision'], r['agent']) for r in log_rows()], [('seen', 'kernel'), ('seen', 'main')])

    def test_secret_masked_in_log(self):
        run(bash('curl -H "Authorization: Bearer abcdefghijklmnop1234" -o scripts/x https://e'))
        row = log_rows()[-1]
        self.assertEqual(row['decision'], 'deny')
        self.assertNotIn('abcdefghijklmnop1234', json.dumps(row))
        self.assertLessEqual(len(row['input']), gate.LOG_INPUT)

    def test_error_paths(self):
        orig = gate.decide
        try:
            def boom(*a, **k):
                raise RuntimeError('x')
            gate.decide = boom
            self.assertIn('"deny"', run(write(P + '/agents/kernel/x')))            # Write: fail closed
            self.assertIn('"deny"', run(bash('ls ' + P + '/scripts', '/tmp')))    # Bash + protected text
            self.assertEqual(run(bash('ls /tmp', '/tmp')), '')                    # Bash, nothing protected
            p = write(P + '/scripts/x')
            p['transcript_path'] = MAIN_TP
            self.assertEqual(run(p), '')                                          # main never
            def slow(*a, **k):
                raise gate.Deadline()
            gate.decide = slow
            self.assertIn('"deny"', run(bash('rm ' + P + '/src/a', '/tmp')))
        finally:
            gate.decide = orig
        self.assertIn('error-allow', [r['decision'] for r in log_rows()])

    def test_bad_stdin(self):
        for raw in ('', 'not json', '[]', '"x"', '{"tool_name": "Bash"}', 'x' * (gate.MAX_STDIN + 10)):
            self.assertEqual(run(None, raw), '')

    def test_log_dir_missing_does_not_change_decision(self):
        out = gate.run(json.dumps(bash('echo > scripts/a')), P, HOME + '/nope', HOME, now=0)
        self.assertIn('"deny"', out)

    def test_log_created_on_first_write(self):
        """No root installer: the gate creates <log>/gate.jsonl and seen/ itself (Klodel 42872)."""
        d = os.path.join(HOME, 'fresh-log')
        gate.run(json.dumps(bash('echo > scripts/a')), P, d, HOME, now=0)
        with open(os.path.join(d, 'gate.jsonl')) as f:
            self.assertEqual([json.loads(l)['decision'] for l in f], ['seen', 'deny'])
        self.assertEqual(len(os.listdir(os.path.join(d, 'seen'))), 1)

    def test_root_and_log_from_file_location(self):
        root = os.path.dirname(os.path.dirname(HERE))
        self.assertEqual(gate.PROD, os.path.realpath(root))
        self.assertEqual(gate.LOG_DIR, os.path.join(gate.PROD, 'store', 'prod-tree-write-gate'))

    def test_env_is_ignored(self):
        os.environ['MARVEEN_AGENT_ID'] = 'klodel'
        os.environ['HOME'] = '/nonexistent'
        try:
            self.assertIn('"deny"', run(bash('echo > scripts/a')))
        finally:
            del os.environ['MARVEEN_AGENT_ID']


ALPHA = list('ab /.\'"`$(){}[]*?~<>|&;\\\n\t=-#!') + ['scripts', 'src', '.claude', P, '\x00', '\ud800', '$(', '<<',
                                                      'EOF', 'git ', 'rm ', 'cd ', '>', '..', '$HOME', 'bash -c ']


class Fuzz(unittest.TestCase):
    def test_decide_never_raises(self):
        rnd = random.Random(1115)
        t0 = time.time()
        for _ in range(3000):
            s = ''.join(rnd.choice(ALPHA) for _ in range(rnd.randint(0, 80)))
            for p in (bash(s, rnd.choice([P, '/tmp', None, 5, P + '/scripts'])), write(s),
                      {'tool_name': rnd.choice(['Bash', 'Write', 'Edit']), 'tool_input': rnd.choice([None, s, [], {}])},
                      {'tool_name': 'Bash', 'tool_input': {'command': rnd.choice([None, 5, [s]])}}):
                r = gate.decide(p, P, HOME)
                self.assertIn(r[0], ('allow', 'deny'))
        self.assertLess(time.time() - t0, 60)

    def test_run_never_raises_and_is_bounded(self):
        rnd = random.Random(7)
        for _ in range(300):
            s = ''.join(rnd.choice(ALPHA) for _ in range(rnd.randint(0, 200)))
            out = run(None, rnd.choice([s, json.dumps(bash(s)), json.dumps(write(s)), '{"tool_input": ' + s + '}']))
            self.assertIn(out[:1], ('', '{'))
        for big in ('echo ' + 'a' * 300000, '$(' * 5000 + ')' * 5000, '"' * 100001, 'a | ' * 40000,
                    'echo ' + '$(echo ' * 50 + 'x' + ')' * 50 + ' > ' + P + '/scripts/a'):
            t0 = time.time()
            r = gate.decide(bash(big), P, HOME)
            self.assertIn(r[0], ('allow', 'deny'))
            self.assertLess(time.time() - t0, 4, big[:30])

    def test_symlink_loop(self):
        self.assertEqual(d(write(P + '/agents/kernel/loop1/x')), 'allow')
        r = gate.decide(bash('echo > ' + P + '/agents/kernel/loop1/x', '/tmp'), P, HOME)
        self.assertEqual(r[0], 'allow')


if __name__ == '__main__':
    try:
        unittest.main(verbosity=1)
    finally:
        shutil.rmtree(T, ignore_errors=True)
