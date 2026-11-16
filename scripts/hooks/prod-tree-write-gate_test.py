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
              'agents/x/.claude', 'other/.git', 'agents/kernel/.claude', 'agents/kernel/work',
              'agents/x/.claude-config'):
        os.makedirs(os.path.join(P, d), exist_ok=True)
    for f in ('CLAUDE.md', '.mcp.json', 'package.json', 'package-lock.json', 'store/autonomy-config.json',
              'store/verified-recipients.json', 'scripts/x.py', 'README.md', 'agents/kernel/agent-config.json',
              'agents/x/agent-config.json', 'agents/x/.claude/settings.local.json'):
        open(os.path.join(P, f), 'w').close()
    open(WT + '/.git', 'w').write('gitdir: ' + P + '/.git/worktrees/wt\n')
    os.symlink(P + '/scripts', P + '/agents/kernel/lnk')
    os.symlink(P + '/agents/x/.claude', P + '/agents/kernel/xclaude')
    os.symlink(P + '/agents/x', P + '/agents/kernel/xhome')          # Viktor 43196 mutant (b): a symlinked home
    os.symlink(P + '/agents', P + '/agents/kernel/xagents')
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
    ('mkdir -p P/agents/kernel/work/new', '/tmp'), ('touch P/agents/kernel/.claude/settings.local.json', '/tmp'),
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
        for p in (P + '/agents/kernel/x', WT + '/scripts/x', P + '/agents/kernel/.claude/settings.local.json',
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


# card 17901b47 (Viktor): agent config files. The caller is kernel (SUB_TP); x is another agent.
K = P + '/agents/kernel'
CFG_FILES = ('agent-config.json', '.claude/settings.json', '.claude-config/settings.json')
CFG_BASH = ('echo {{}} > {f}', 'printf x >> {f}', "sed -i '' s/a/b/ {f}", 'cp /tmp/a {f}', 'mv /tmp/a {f}',
            'tee {f} < /dev/null', 'rm {f}', 'rm -f {f}', 'mv {f} /tmp/bak', 'chmod 600 {f}', 'ln -sf /tmp/a {f}',
            'truncate -s 0 {f}', 'touch {f}', 'bash -c "echo x > {f}"')


def cfg_deny_rows():
    """(command, cwd): every Bash write form on own and other agent config files, absolute and home-relative"""
    rows = []
    for owner in ('kernel', 'x'):
        for f in CFG_FILES:
            for c in CFG_BASH:
                rows.append((c.format(f=P + '/agents/' + owner + '/' + f), '/tmp'))
                rows.append((c.format(f=f), P + '/agents/' + owner))
    for c in CFG_BASH:   # another agent's settings.local.json
        rows.append((c.format(f=P + '/agents/x/.claude/settings.local.json'), '/tmp'))
        rows.append((c.format(f='../x/.claude/settings.local.json'), K))
    return rows


CFG_DENY_MORE = [
    # case, firmlink, symlink, relative climbs
    ('echo > ' + P + '/AGENTS/X/Agent-Config.JSON', '/tmp'), ('echo > /System/Volumes/Data' + P + '/agents/x/agent-config.json', '/tmp'),
    ('echo > xclaude/settings.json', K), ('echo > xclaude/settings.local.json', K),
    ('echo > ../x/agent-config.json', K), ('echo > ../../agents/x/.claude/settings.json', K),
    ('cd ../x && echo > agent-config.json', K), ('cd .claude && echo {} > settings.json', K),
    # destructive ops on the agent home / its config directories (an ancestor of the files)
    ('rm -rf ' + P + '/agents/x', '/tmp'), ('rm -rf .claude', K), ('rm -rf .claude-config', K),
    ('mv ' + P + '/agents/x/.claude /tmp/y', '/tmp'), ('chmod -R 777 ' + P + '/agents/x', '/tmp'),
    ('rm -rf ' + P + '/agents/*', '/tmp'), ('rm *.json', K), ('rm -rf .c*', K), ('rm -rf *', K),
    ('rmdir ' + P + '/agents', '/tmp'),
    # into a directory: destination/basename(source)
    ('mv /tmp/agent-config.json ' + P + '/agents/x/', '/tmp'), ('cp /tmp/settings.json ' + P + '/agents/x/.claude/', '/tmp'),
    ('cp -t .claude /tmp/settings.json', K), ('mv -t ' + P + '/agents/x /tmp/agent-config.json', '/tmp'),
    # unresolved agent name: the raw-text rule
    ('echo x > ' + P + '/agents/$A/agent-config.json', '/tmp'), ('cd ' + P + '/agents/$A && echo > agent-config.json', '/tmp'),
    ('echo x > ~/BASE/agents/$A/.claude/settings.json'.replace('BASE', BASE), '/tmp'),
    ('echo x > "$HOME/BASE/agents/x/.claude-config/settings.json"'.replace('BASE', BASE), '/tmp'),
    ('for a in x kernel; do echo > ' + P + '/agents/$a/agent-config.json; done', '/tmp'),
    ('X=' + P + '/agents/x; echo > $X/agent-config.json', '/tmp'), ('echo "x ' + P + '/agents/x/agent-config.json', '/tmp'),
    # a variable inside the name next to a literal: matched against the config names
    ('echo > ' + K + '/$X-config.json', '/tmp'), ('echo > ' + P + '/agents/$A/.claude/settings.json', '/tmp'),
    ('cp /tmp/s ' + K + '/$D/settings.json', '/tmp'), ('rm -f ' + P + '/agents/x/{agent-config,y}.json', '/tmp'),
    ('rm -rf agents/x/$Y', P),
    # the raw-text rule from an agent home (cwd unknown after `cd $X`): ../<name>/<config file>
    ('cd $X; echo > ../x/agent-config.json', K), ('cd $X; echo > ./../../x/.claude/settings.json', K),
]

CFG_ALLOW = [
    # reads
    ('cat agent-config.json', K), ('cat ' + P + '/agents/x/agent-config.json', '/tmp'), ('jq . agent-config.json', K),
    ('grep -n hook .claude/settings.json ../x/.claude/settings.json', K), ('ls -la .claude .claude-config', K),
    ('python3 -c "import json; print(json.load(open(\'agent-config.json\')))"', K), ('cp agent-config.json /tmp/a.bak', K),
    ('cat ' + P + '/agents/x/agent-config.json > /tmp/out', '/tmp'), ('shasum -a 256 .claude/settings.json', K),
    ('diff .claude/settings.json ../x/.claude/settings.json', K), ('git -C ' + P + ' diff -- agents/x/agent-config.json', '/tmp'),
    ('cat agent-config.json > "$OUT"', K), ('echo agent-config.json > /tmp/x', K),
    ('grep -rl agent-config.json src > $LIST', K), ('cp .claude/settings.json "$B/"', K),
    # the caller's own settings.local.json (its self-imposed hook gates)
    ('echo {} > .claude/settings.local.json', K), ("sed -i '' s/a/b/ .claude/settings.local.json", K),
    ('cp /tmp/s .claude/settings.local.json', K), ('mv /tmp/s ' + K + '/.claude/settings.local.json', '/tmp'),
    ('tee .claude/settings.local.json < /tmp/s', K), ('cp .claude/settings.local.json .claude/settings.local.json.bak', K),
    # writes elsewhere in the own home
    ('echo > work/x', K), ('echo x > ' + K + '/work/x', '/tmp'), ('mkdir -p bin && cp /tmp/t bin/t', K),
    ('rm -rf work/old', K), ('mv /tmp/r.md ' + K + '/', '/tmp'), ('mv /tmp/r.md .', K), ('rm *.log', K),
    ('find . -name "*.pyc" -delete', K), ('mkdir -p .claude/skills/a && echo > .claude/skills/a/SKILL.md', K),
    ('echo > .claude-config/projects/x/m.md', K), ('cp agent-config.json agent-config.json.bak', K),
    ('mkdir -p ' + P + '/agents/newagent/work', '/tmp'), ('echo > work/$NAME', K), ('rm -rf work/*', K),
    ('echo > ' + WT + '/agents/x/agent-config.json', '/tmp'), ('echo > ' + WT + '/.claude/settings.json', '/tmp'),
    ('touch ' + K, '/tmp'), ('echo > ' + K + '/$F', '/tmp'),
    # replay 17901b47: a HANDOFF backup with a substitution in the name, from the prod root cwd (the raw rule sees
    # protected text there); a variable directory below the agents/ dir
    ('cd ' + P + '; echo > store/x; cp ' + K + '/HANDOFF.md ' + K + '/HANDOFF.prev-$(date +%H%M)-1110.md', P),
    ('cd ' + P + '; cat scripts/x.py > agents/kernel/HANDOFF.prev-$(date +%H%M).md', P),
    ('echo > ' + P + '/agents/$A/work/x', '/tmp'), ('echo > ' + K + '/$F.log', '/tmp'),
    ('cd $X; echo > ../x/work.txt', K), ('cd $X; echo > ../kernel/.claude/settings.local.json', K),
]


class AgentConfig(unittest.TestCase):
    """card 17901b47: a sub-agent does not write any agent's agent-config.json / .claude/settings.json /
    .claude-config/settings.json or another agent's .claude/settings.local.json; its own settings.local.json and the
    rest of its home stay writable; reads stay free; the main agent is never gated."""

    def test_write_tools_deny(self):
        for tool in ('Write', 'Edit', 'MultiEdit'):
            for owner in ('kernel', 'x', 'pulzus', 'nobody'):
                for f in CFG_FILES:
                    with self.subTest(tool=tool, path=owner + '/' + f):
                        self.assertEqual(d(write(P + '/agents/' + owner + '/' + f, tool)), 'deny')
            for p in (P + '/agents/x/.claude/settings.local.json', P + '/AGENTS/X/.Claude/Settings.json',
                      K + '/xclaude/settings.json', K + '/xclaude/settings.local.json'):
                with self.subTest(tool=tool, path=p):
                    self.assertEqual(d(write(p, tool)), 'deny')
            with self.subTest(tool=tool, path='relative'):
                self.assertEqual(d(write('agent-config.json', tool, cwd=K)), 'deny')

    def test_write_tools_allow(self):
        for p in (K + '/.claude/settings.local.json', K + '/.Claude/Settings.Local.json', K + '/work/x',
                  K + '/.claude/skills/a/SKILL.md', K + '/agent-config.json.bak', K + '/.claude',
                  WT + '/agents/x/agent-config.json', WT + '/.claude/settings.json'):
            with self.subTest(path=p):
                self.assertEqual(d(write(p)), 'allow')

    def test_bash_deny(self):
        for cmd, cwd in cfg_deny_rows() + CFG_DENY_MORE:
            with self.subTest(cmd=cmd, cwd=cwd):
                self.assertEqual(gate.decide(bash(cmd, cwd), P, HOME)[0], 'deny')

    def test_bash_allow(self):
        for cmd, cwd in CFG_ALLOW:
            with self.subTest(cmd=cmd, cwd=cwd):
                r = gate.decide(bash(cmd, cwd), P, HOME)
                self.assertEqual(r[0], 'allow', r)

    def test_main_agent_never_denied(self):
        for tp in (MAIN_TP, None):
            open(os.path.join(LOG, 'gate.jsonl'), 'w').close()
            for cmd, cwd in cfg_deny_rows() + CFG_DENY_MORE:
                p = bash(cmd, cwd)
                p['transcript_path'] = tp
                with self.subTest(tp=tp, cmd=cmd):
                    self.assertEqual(run(p), '')
            for f in CFG_FILES + ('.claude/settings.local.json',):
                p = write(P + '/agents/x/' + f)
                p['transcript_path'] = tp
                self.assertEqual(run(p), '')
            if tp == MAIN_TP:
                self.assertTrue(any(r['decision'] == 'would-deny' for r in log_rows()))

    def test_own_settings_local_follows_identity(self):
        """the same write is the caller's own for kernel (allow) and another's for pulzus (deny)"""
        p = write(K + '/.claude/settings.local.json')
        self.assertEqual(d(p), 'allow')
        p['transcript_path'] = P + '/agents/pulzus/.claude-config/projects/x/s.jsonl'
        self.assertEqual(d(p), 'deny')
        p = bash('echo > ' + K + '/.claude/settings.local.json', '/tmp')
        self.assertEqual(d(p), 'allow')
        p['transcript_path'] = P + '/agents/pulzus/.claude-config/projects/x/s.jsonl'
        self.assertEqual(d(p), 'deny')

    def test_sub_agent_deny_via_run(self):
        out = run(bash('echo {} > ' + P + '/agents/x/agent-config.json', '/tmp'))
        msg = json.loads(out)['hookSpecificOutput']['permissionDecisionReason']
        self.assertIn('agent-config.json', msg)
        self.assertIn('saját .claude/settings.local.json szabad', msg)


SEAL = P + '/store/agent-config-seal.json'
R2_DENY = [  # Viktor 43196 (card 17901b47 round 2)
    # MEDIUM 1: the seal of the agent configs
    ('echo {} > store/agent-config-seal.json', P), ('echo {} >> ' + SEAL, '/tmp'), ('rm store/agent-config-seal.json', P),
    ('rm -f ' + SEAL, '/tmp'), ('mv /tmp/s ' + SEAL, '/tmp'), ('mv ' + SEAL + ' /tmp/s', '/tmp'),
    ('cp /tmp/s store/agent-config-seal.json', P), ('truncate -s 0 STORE/Agent-Config-Seal.JSON', P),
    ('echo "x ' + SEAL, '/tmp'), ('echo x > $UNSET; ls ' + SEAL, '/tmp'),
    # LOW 2: a relative value in the middle of a path word
    ('N=x; echo x > agents/$N/agent-config.json', P), ("N=x; sed -i '' s/a/b/ agents/${N}/agent-config.json", P),
    ('N=x; echo x > "agents/$N/.claude/settings.json"', P), ('export N=x; rm agents/$N/.claude-config/settings.json', P),
    ('N=x; echo x > ' + P + '/agents/$N/agent-config.json', '/tmp'), ('N=kernel; tee agents/$N/agent-config.json < /dev/null', P),
    ('for N in x kernel; do echo x > agents/$N/agent-config.json; done', P),
    ('for N in x; do echo x > agents/${N}/agent-config.json; done', P),
    ('N=x$(date); echo x > agents/$N/agent-config.json', P), ('N=x; cd agents/$N && echo > agent-config.json', P),
    ('N=x/$(echo .claude); echo > $N/settings.json', P + '/agents'),
    # LOW 3: a writing find under agents/ or a home, its tests let a config file through
    ('find agents -name agent-config.json -exec sed -i s/applier/developer/ {} +', P),
    ('find ' + P + '/agents -name agent-config.json -execdir perl -pi -e s/a/b/ {} \\;', '/tmp'),
    ('find agents -iname AGENT-CONFIG.JSON -ok rm {} \\;', P), ('find agents -type f -exec truncate -s 0 {} +', P),
    ('find agents/x -name "*.json" -delete', P), ('find agents -path "*/.claude/settings.json" -exec rm {} +', P),
    ('find agents -wholename "*/.claude-config/settings.json" -exec rm {} +', P),
    ('find agents -ipath "*/AGENT-CONFIG.JSON" -exec cp /tmp/a {} \\;', P), ('find . -maxdepth 1 -type f -delete', K),
    ('find agents ! -name "*.md" -delete', P), ('find agents -not -name "*.md" -delete', P),
    ('find agents -name "*.md" -o -name "*.json" -delete', P), ('find agents -name "*.md" , -delete', P),
    ('find agents -name "$X" -delete', P), ('find . -name .claude -exec rm -rf {} +', K),
    ('find . -type d -name .claude -exec chmod 700 {} +', K), ('find . -type f,d -name "*-config.json" -delete', K),
    ('find agents -exec ls {} + -name "*.json" -delete', P), ('find agents -exec ls {} \\; -name "*.json" -delete', P),
    ("find xclaude -name 'settings*' -exec sed -i '' s/a/b/ {} +", K),
    ('find xagents -name agent-config.json -exec tee {} \\;', K),
    ('for d in x/work x; do find agents/$d -name "*.json" -delete; done', P),   # the 2nd loop value counts
    ('find agents/x/work agents/x -name "*.json" -delete', P), ('cd agents; find x -name "*.json" -delete', P),
    ('cd /tmp; find . -name "*.json" -delete; cd ' + P + '/agents/x; find . -name "*.json" -delete', P),  # same word
    ('find agents -path "agents/*/agent-config.json" -exec rm {} +', P),          # -path against the start as typed
    ("find ../x/.claude -name settings.local.json -exec sed -i '' s/a/b/ {} +", K),  # another agent's
    ('find .claude -type d -exec rm -rf {} +', K), ('find agents -name agents -exec rm -rf {} +', P),  # the start itself
    ('find agents ' + '-name "*.md" ' * 257 + '-delete', P),     # more than FIND_MAX_TESTS (256): no exclusion
    # LOW 4: directory writers into agents/, a home, its config dirs, the prod root
    ('rsync -a /tmp/evil/ agents/x/', P), ('cp -r /tmp/evil/. agents/x/', P), ('tar -xf /tmp/e.tar -C agents/x', P),
    ('unzip -o /tmp/e.zip -d agents/x', P), ('ditto /tmp/evil agents/x', P), ('cp -R /tmp/evil/ agents/x', P),
    ('gcp -a /tmp/evil/. agents/x/', P), ('scp -r /tmp/evil/. agents/x/', P),
    ('rsync -av --exclude=.git /tmp/evil/ ' + P + '/agents/x/', '/tmp'), ('cp -r /tmp/x ' + P + '/agents/', '/tmp'),
    ('cp -r /tmp/evil/. .claude/', K), ('ditto -x -k /tmp/e.zip agents/x', P), ('tar -C agents/x -xf /tmp/e.tar', P),
    ('tar --extract -f /tmp/e.tar -C agents/x', P), ('unzip -o /tmp/e.zip', K), ('tar -xf /tmp/e.tar', P + '/agents'),
    ('rsync -a "$S/" agents/x/', P), ('cp -r /tmp/evil ' + P + '/agents/newagent', '/tmp'),
    ('N=x; rsync -a /tmp/e/ agents/$N/', P), ('rsync -a /tmp/e/ ' + P + '/', '/tmp'), ('cp -a /tmp/e/. ' + P, '/tmp'),
    ('cp -r /tmp/e/. --target-directory=' + P + '/agents/x', '/tmp'),
    ('cp --recursive /tmp/evil/. agents/x/', P), ('gcp --archive /tmp/e/. agents/x/', P),
    ('rsync -a /tmp/e/ ' + P + '/agents/x$N/', '/tmp'), ('tar --get -f /tmp/e.tar -C agents/x', P),
    ('rsync -a "$S" agents/x/', P),
    ('N=kernel; for N in x; do cd agents/$N && echo > .claude/settings.local.json; done', P),   # the loop value
    ('find agents -name AGENT-CONFIG.JSON -exec sed -i s/a/b/ {} +', P),     # APFS: the same file
    ('rsync -a /tmp/e/ ' + P + '/agents/x*/', '/tmp'), ('rsync /tmp/e/* agents/x/', P),
    ('tar -xf /tmp/e.tar --exclude=Old -C agents/x', P), ('tar -xf- -C agents/x < /tmp/e.tar', P),
    ('tar -xf /tmp/e.tar Output', K), ('tar -C agents/x -xvf /tmp/e.tar', P), ('unzip -oq /tmp/e.zip', K),
    # option clusters with letters inside the [A-Za-z] ranges (not only at their ends), old-style tar
    ('cp -PpRLv /tmp/e/ agents/x/', P), ('tar Pmxf /tmp/e.tar -C agents/x', P),
    ('tar -C agents/x -PmxvU -f /tmp/e.tar', P), ('unzip -CMoq /tmp/e.zip', K),
    # Viktor 43196 mutant (b): a glob below a symlinked config directory / home (agent_reach's realpath form)
    ('rm -f xclaude/*.json', K), ('rm -f xhome/*-config.json', K), ('echo > xhome/agent-*.json', K),
    # Viktor 43257 A: the letters of a joined -dDIR are not listing letters; d / P take the rest of the word
    ('unzip -o /tmp/e.zip -dscripts', P), ('unzip -qodscripts /tmp/e.zip', P), ('unzip -Pl /tmp/e.zip', P),
    ('unzip -o /tmp/e.zip -d' + P + '/agents/x', '/tmp'), ('unzip -qod' + P + '/agents/x /tmp/e.zip', '/tmp'),
    ('unzip -qod ' + P + '/agents/x /tmp/e.zip', '/tmp'), ('unzip -l /tmp/e.zip -d agents/x', P),
    ('unzip --l /tmp/e.zip', P),
    # Viktor 43257 B: find's leading options are not the end of the starting points
    ('find -H ' + P + '/agents -path "*x*" -name agent-config.json -delete', K + '/work'),
    ('find -L ' + P + '/agents -name agent-config.json -delete', K), ('find -x -s ' + P + '/agents -name agent-config.json -delete', '/tmp'),
    ('find -Hx ' + P + '/agents -name agent-config.json -delete', '/tmp'), ('find -f ' + P + '/agents -name agent-config.json -delete', '/tmp'),
    ('find -f' + P + '/agents -name agent-config.json -delete', '/tmp'), ('find -D tree ' + P + '/agents -name agent-config.json -delete', '/tmp'),
    ('find -O3 ' + P + '/agents -name agent-config.json -delete', '/tmp'), ('find -P -E ' + P + '/agents -name agent-config.json -delete', '/tmp'),
    # Viktor 43257 C: tar's directory joined, as --directory=, in a cluster, old style
    ('tar -xf /tmp/e.tar --directory=' + P + '/agents/x', K + '/work'), ('tar -xf /tmp/e.tar -C' + P + '/agents/x', K + '/work'),
    ('tar -xC ' + P + '/agents/x -f /tmp/e.tar', K + '/work'), ('tar xCf ' + P + '/agents/x /tmp/e.tar', K + '/work'),
    ('tar -xzC' + P + '/agents/x -f /tmp/e.tgz', K + '/work'), ('tar xfC /tmp/e.tar ' + P + '/agents/x', K + '/work'),
    # Viktor 43257 D: an O after the first valued letter is that letter's value, not --to-stdout
    ('tar -xfO -C agents/x', P), ('tar -xf /tmp/e.tar -C agents/x -sOaObO', P),
    # Viktor 43257 E: a relative literal value joins the cwd where it is used
    ('F=agent-config.json; cd agents/x && echo x > $F', P), ('D=x; cd agents && echo x > $D/agent-config.json', P),
    ('F=settings.json; cd agents/x/.claude; echo x > $F', P),
    ('cd /tmp; F=agent-config.json; X=$F; cd ' + P + '/agents/x && echo x > $X', '/tmp'),   # X=$F keeps F's relative text
    # Viktor 43289 F: unzip reads "-" as "not"; with a listing letter it extracts (into the cwd)
    ('unzip -l --v /tmp/e.zip', P), ('unzip -l-l /tmp/e.zip', P), ('unzip -- -l /tmp/e.zip', P), ('unzip -t --t /tmp/e.zip', P),
    # Viktor 43289 INFO (mutant U11): -D is a timestamp flag, not an exdir
    ('unzip -D /tmp/e.zip', P),
    # card f72e8f27 (Viktor 43676 LELET 1): after the archive name a word is a member pattern, not an option
    # (measured, Info-ZIP 6.00: every one of these extracts evil.txt into the cwd); 7 HOLE-NEW (-h), 8 HOLE-OLD
    ('unzip /tmp/z.zip evil.txt -h', P), ('unzip /tmp/z.zip evil.txt -hh', P), ('unzip /tmp/z.zip evil.txt -qh', P),
    ('unzip /tmp/z.zip nomatch evil.txt -h', P), ("unzip /tmp/z.zip '*' -h", P), ('unzip /tmp/z.zip -h evil.txt', P),
    ('unzip /tmp/z.zip evil.txt -x -h', P),
    ('unzip /tmp/z.zip evil.txt -l', P), ('unzip /tmp/z.zip evil.txt -t', P), ('unzip /tmp/z.zip evil.txt -v', P),
    ('unzip /tmp/z.zip evil.txt -p', P), ('unzip /tmp/z.zip evil.txt -z', P), ('unzip /tmp/z.zip evil.txt -Z', P),
    ('unzip /tmp/z.zip -l evil.txt', P), ('unzip -o /tmp/z.zip evil.txt -l', P), ('unzip "$Z" evil.txt -l', P),
    ('unzip $A -l /tmp/e.zip', P),   # an unknown word may be the archive: the -l after it is then a member pattern
    ('unzip -Ppw /tmp/z.zip -l evil.txt', P),   # a joined -Ppw takes no next word: /tmp/z.zip is the archive
    # Viktor 43347 LOW 1: several -C are applied in order (bsdtar: -C o1 -C sub extracts to o1/sub); last-wins read
    # the attached one alone (agents/kernel/work/x) and allowed what the parent denied
    ('tar -xf /tmp/e.tar -C ../.. -Cx', K + '/work'), ('tar -xf /tmp/e.tar -C ../.. -C x', K + '/work'),
    ('tar -xf /tmp/e.tar -C /tmp/a -C ' + P + '/agents/x', '/tmp'),   # an absolute one starts the chain again
    # card f72e8f27 (Viktor 43370 C2): every element of the chain is checked, not only the first (out is a scratch
    # dir; out/../../../x is agents/x)
    ('tar -xf /tmp/e.tar -C out -C ../../../x', K + '/work'),
    # Viktor 43347 LOW 2: bsdtar's --cd and the unique prefixes of --directory
    ('tar -xf /tmp/e.tar --cd ' + P + '/agents/x', K + '/work'), ('tar -xf /tmp/e.tar --cd=' + P + '/agents/x', K + '/work'),
    ('tar -xf /tmp/e.tar --dir ' + P + '/agents/x', K + '/work'), ('tar -xf /tmp/e.tar --direc=' + P + '/agents/x', K + '/work'),
    ('tar --extract --file /tmp/e.tar --directory agents/x', P),
    # Viktor 43347 LOW 3: -P / --absolute-names: the archive's member names are the targets
    ('tar -xPf /tmp/abs.tar', K + '/work'), ('tar -x --absolute-names -f /tmp/abs.tar', '/tmp'), ('tar xPf /tmp/abs.tar', '/tmp'),
    ('tar -x --absolute-paths -f /tmp/abs.tar', '/tmp'),
    # card f72e8f27 (Viktor 43370 A1): --ab is already --absolute-paths in bsdtar (measured: the member went to its
    # absolute path); the old 5-character minimum let it through
    ('tar -x --ab -f /tmp/abs.tar', '/tmp'), ('tar -xf /tmp/abs.tar --abs', K + '/work'),
    # Viktor 43347 mutant B7: a -f start point as its own word, before a protected start point
    ('find -f /tmp/ok agents/x -name agent-config.json -delete', P),
    # mutant b7: -f takes the next word even when it starts with "-" (measured on macOS find: `find -f -x/../../t`
    # walks t); read as a plain start point the walk stops there and only the cwd was checked
    ('find -f -x/../../../x -delete', K + '/work'),
    # mutants t1 / t15: every -C of the chain is checked, not only the last (bsdtar extracts into the last one; GNU
    # tar's positional -C before members is not measured here: a deny on a rare form, Viktor 43347's reading kept)
    ('tar -xf /tmp/e.tar -C ' + P + '/agents/x -C sub', '/tmp'),
]
R2_ALLOW = [
    ('cat store/agent-config-seal.json', P), ('cp ' + SEAL + ' /tmp/s', '/tmp'),
    ('echo x > $UNSET; ls ' + P + '/store/verified-recipients.json', '/tmp'), ('echo "x ' + SEAL + '.bak', '/tmp'),
    ('N=x; echo x > agents/$N/notes.md', P), ('N=x; echo x > agents/${N}/work/a.txt', P),
    ('for N in x kernel; do echo x > agents/$N/notes.md; done', P), ('N=x$(date); echo x > agents/$N/notes.md', P),
    ('N=x; echo x > ' + P + '/agents/$N/work/a', '/tmp'), ('N=x/$(echo work); echo > $N/settings.json', P + '/agents'),
    ('find agents -name agent-config.json -print', P), ('find agents -name agent-config.json -exec cat {} +', P),
    ('find agents -name agent-config.json | xargs grep securityProfile', P),
    ('find agents -name agent-config.json -exec grep -l x {} +', P), ('find agents -name "*.log" -delete', P),
    ('find agents -path "*/work/*.tmp" -delete', P), ('find . -type d -name __pycache__ -exec rm -rf {} +', K),
    ("find . -type d -name .claude -exec sed -i '' s/a/b/ {} +", K), ("find xclaude -name '*.md' -exec sed -i '' s/a/b/ {} +", K),
    ('find agents -iname "*.LOG" -delete', P), ('find agents -ipath "*/WORK/*" -delete', P),
    ('find agents -name "*.md" -exec test ! -s {} \\; -delete', P), ('find agents -exec ls {} + -name "*.md" -delete', P),
    ('find agents -exec ls {} \\; -name "*.md" -delete', P), ('find agents/x/work -delete', P),
    ('find xagents -name "*.md" -exec rm {} +', K),
    ('find agents ' + '-name "*.md" ' * 256 + '-delete', P),     # FIND_MAX_TESTS (256) tests are still read
    ('cp -r /tmp/proj agents/x/', P), ('rsync -a /tmp/proj agents/x/', P), ('rsync -a /tmp/evil/ agents/x/work/', P),
    ('tar -xf /tmp/e.tar -C agents/x/work', P), ('unzip /tmp/e.zip -d agents/kernel/work/u', P),
    ('cp -r /tmp/skills/. .claude/skills/', K), ('cp /tmp/a agents/x/', P), ('tar -xf /tmp/e.tar', K + '/work'),
    ('unzip -l /tmp/e.zip', K), ('tar -tf /tmp/e.tar', K), ('rsync -a ' + P + '/agents/x/ /tmp/bak/', '/tmp'),
    ('cp -r ' + P + '/agents/x /tmp/bak', '/tmp'), ('ditto ' + P + '/agents/x /tmp/bak', '/tmp'),
    ('cp -r /tmp/evil/. /tmp/y/', P), ('tar -czf /tmp/a.tgz -C agents/x .', P), ('cp -r /tmp/e/. ' + HOME + '/', '/tmp'),
    ('rsync -a /tmp/e/ ' + HOME + '/other/', '/tmp'), ('cp -p /tmp/e/. agents/x/', P),
    ('rm -f xhome/*.md', K), ('rm -f xclaude/*.md', K),
    ('find agents -path "agents/*/work/*" -delete', P), ("find .claude -name settings.local.json -exec sed -i '' s/a/b/ {} +", K),
    ('rsync -a /tmp/kernel agents/newdir', P), ('patch -p1 < /tmp/x.diff', K),
    ('rsync -a /tmp/e/ ' + P + '/agents/x/work$N/', '/tmp'),
    # replay 17901b47 r2 (Kernel, 11-09/10-27): extract to stdout, zipinfo / listing modes write nothing
    ('tar -xOf /tmp/e.tar ./job.log | tail -5', K), ('tar xOf /tmp/e.tar a', K), ('tar -xzf /tmp/e.tgz --to-stdout x', K),
    ('tar -C agents/x -xOf /tmp/e.tar a', P), ('m=$(unzip -Z1 /tmp/e.whl | grep x)', K), ('unzip -qql /tmp/e.zip', K),
    ('unzip -p /tmp/e.zip a | grep x', K), ('unzip -t /tmp/e.zip', K), ('unzip -v /tmp/e.zip', K),
    ('unzip -z /tmp/e.zip', K), ('tar -PxOm -f /tmp/e.tar a', K), ('unzip -^:CMqql /tmp/e.zip', K),
    ('unzip -o /tmp/e.zip -d/tmp/out', P), ('unzip -qod /tmp/out /tmp/e.zip', P), ('unzip -Z1 /tmp/e.zip', P),
    ('unzip -qql /tmp/e.zip', P),
    # Viktor 43257 B-E: the same shapes where nothing protected is reached
    ('find -H ' + P + '/agents -name "*.log" -delete', '/tmp'), ('find -L /tmp/x -name agent-config.json -delete', P),
    ('find -f /tmp/x -name agent-config.json -delete', P),
    ('find -D agents /tmp/x -name agent-config.json -delete', P),   # -D takes its value word: no starting point
    ('tar -xf /tmp/e.tar --directory=/tmp/out', P), ('tar xCf /tmp/out /tmp/e.tar', P), ('tar -xC/tmp/out -f /tmp/e.tar', P),
    ('tar -xfC ' + P + '/agents/x', K + '/work'),     # f takes "C" (the archive), the cwd is a work dir
    ('tar xfO /tmp/e.tar a', P),                      # old style: every letter is a flag, O = stdout
    # Viktor 43347: a relative -C after an absolute one is inside it (the head denied this: last-wins read agents/x
    # against the cwd); --cd / --dir to a scratch dir; --di is ambiguous in bsdtar (not a directory option)
    ('tar -xf /tmp/e.tar -C /tmp/a -C agents/x', P), ('tar -xf /tmp/e.tar -C /tmp/o -C sub', K + '/work'),
    ('tar -xf /tmp/e.tar --cd /tmp/o', K + '/work'), ('tar -xf /tmp/e.tar --dir=/tmp/o', K + '/work'),
    # mutant t6: --di is ambiguous in bsdtar (--disable-copyfile, --directory; measured rc 1, nothing extracted)
    ('tar -xf /tmp/e.tar --di=' + P + '/agents/x', K + '/work'),
    # card f72e8f27 (Viktor 43370 L3, A1): --c and --a are ambiguous in bsdtar (measured rc 1, nothing extracted), so
    # the minimum prefixes are --cd (4) and --ab (4)
    ('tar -xf /tmp/e.tar --c=' + P + '/agents/x', K + '/work'), ('tar -xf /tmp/abs.tar --a', K + '/work'),
    # card f72e8f27 (Viktor 43370 C3): an absolute -C starts the chain again; bsdtar extracts into /tmp/a only
    ('tar -xf /tmp/e.tar -C agents/x -C /tmp/a', P),
    # card f72e8f27 (Viktor 43370 INFO): unzip -h / -hh is the help; measured, with an archive too it extracts nothing
    ('unzip -hh', P), ('unzip -h /tmp/e.zip', P), ('unzip -oh /tmp/e.zip', P),
    # card f72e8f27 (Viktor 43676 LELET 1): a lone -P takes the next word (the password), so it is not the archive
    # name and a listing letter after it still counts; listing before the archive, -d after it, stay as they were
    ('unzip -P pw -l /tmp/e.zip', P), ('unzip -qql /tmp/e.zip a -x b', P), ('unzip -l /tmp/e.zip -d /tmp/o', P),
    # mutant t12: in -xfP the f takes the rest of the word: P is the archive name, not -P (measured: "P: No such file")
    ('tar -xfP /tmp/e.tar', K + '/work'),
    ('F=notes.md; cd agents/x && echo x > $F', P), ('F=agent-config.json; cd /tmp && echo x > $F', P),
    ('B=agents/pulzus/backups/m-$(date +%H%M%S); cd /tmp; mkdir -p $B', P),
    ('find agents -wholename "*/work/*" -delete', P), ('find agents -iwholename "*/WORK/*" -delete', P),
    # mutation round 1 survivors: a stale relative value / joined flag, -type alone excluding
    ('N=x; M=$(mktemp); echo > agents/x/$M', P), ('D=$(dirname agents/x/f); echo > agents/$D/agent-config.json', P),
    ('N=x/work; echo > agents/$N/agent-config.json', P), ('N=kernel; echo > agents/$N/.claude/settings.local.json', P),
    ('N=x; N=$(mktemp); echo > agents/$N/agent-config.json', P), ("find . -type d -exec sed -i '' s/a/b/ {} +", K),
    ("find . -type f -name '.claude*' -exec rm -rf {} +", K), ('rsync -a /tmp/e/ ' + P + '/agents/x/wo*/', '/tmp'),
]


class ViktorR2(unittest.TestCase):
    """Viktor 43196 on card 17901b47: the seal file, a mid-word relative variable, a writing find under agents/,
    directory writers into a home, the symlinked glob directory."""

    def test_deny(self):
        bad = [(c, w, r) for c, w in R2_DENY for r in [gate.decide(bash(c, w), P, HOME)] if r[0] != 'deny']
        self.assertEqual(bad, [])

    def test_allow(self):
        bad = [(c, w, r) for c, w in R2_ALLOW for r in [gate.decide(bash(c, w), P, HOME)] if r[0] != 'allow']
        self.assertEqual(bad, [])

    def test_seal_write_tools(self):
        for tool in ('Write', 'Edit', 'MultiEdit'):
            for p in (SEAL, P + '/STORE/Agent-Config-Seal.JSON', '/System/Volumes/Data' + SEAL):
                self.assertEqual(d(write(p, tool)), 'deny', (tool, p))
            self.assertEqual(d(write('store/agent-config-seal.json', tool, cwd=P)), 'deny', tool)
            self.assertEqual(d(write(SEAL + '.bak', tool)), 'allow', tool)

    def test_main_agent_never_denied(self):
        for tp in (MAIN_TP, None):
            open(os.path.join(LOG, 'gate.jsonl'), 'w').close()
            for cmd, cwd in R2_DENY:
                p = bash(cmd, cwd)
                p['transcript_path'] = tp
                with self.subTest(tp=tp, cmd=cmd):
                    self.assertEqual(run(p), '')
            p = write(SEAL)
            p['transcript_path'] = tp
            self.assertEqual(run(p), '')
            if tp == MAIN_TP:
                self.assertIn('would-deny', [r['decision'] for r in log_rows()])

    def test_floods(self):
        """x20000 of each new token, with the write at the end (deny) and without it (allow), each under 4 s"""
        many_starts = ' '.join('./' * i + 'agents' for i in range(300))
        rows = [
            ('find agents ' + '-name a ' * 20000 + '-delete', 'find agents ' + '-name a ' * 20000 + '-print'),
            ('find ' + 'agents/x ' * 20000 + '-name "*.json" -delete', 'find ' + 'agents/x ' * 20000 + '-name "*.md" -delete'),
            ('find ' + many_starts + ' -name "*a*"' * 250 + ' -name "*.md" -delete',
             'find ' + many_starts + ' -name "*a*"' * 250 + ' -name "*.md" -print'),
            ('N=x; ' * 20000 + 'echo > agents/$N/agent-config.json', 'N=x; ' * 20000 + 'echo > agents/$N/notes.md'),
            ('rsync -a ' + '/tmp/e/ ' * 20000 + 'agents/x/', 'rsync -a ' + '/tmp/e/ ' * 20000 + 'agents/x/work/'),
            ('cp -r ' + ' '.join('/e%d' % i for i in range(20000)) + ' ' + P + '/agents/',
             'cp -r ' + ' '.join('/e%d' % i for i in range(20000)) + ' ' + P + '/agents/x/work/'),
        ]
        for want_deny, want_allow in rows:
            for cmd, want in ((want_deny, 'deny'), (want_allow, 'allow')):
                t0 = time.time()
                r = gate.decide(bash(cmd, P), P, HOME)
                self.assertEqual(r[0], want, (cmd[:60], cmd[-60:], r))
                self.assertLess(time.time() - t0, 4, cmd[:60])

    def test_find_budget_fails_closed(self):
        st = gate.State(gate.Prod(P, 'kernel'), P, HOME)
        st.find_budget = 3
        gate.analyze_text('find agents -name "*.md" -delete', st, 0)
        self.assertEqual(len(st.deny), 1)
        self.assertIn('fail-closed', st.deny[0])
        st = gate.State(gate.Prod(P, 'kernel'), P, HOME)
        gate.analyze_text('find agents -name "*.md" -delete', st, 0)
        self.assertEqual(st.deny, [])


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
