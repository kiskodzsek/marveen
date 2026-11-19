import { describe, it, expect, beforeAll, afterAll } from 'vitest'
// @ts-expect-error -- plain .mjs hook script, no types
import { gateDecision, scheduleDirBashSegmentAllowed, fileToolTargetsScheduleDir, scheduleDirOf } from '../../scripts/self-pace-gate.mjs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { mkdtempSync, mkdirSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'

// SCHEDDIR1118 (card a74793b8, Klodel 47370; system 47365, first case 42457): a sub-agent
// may not write the per-task store ~/.claude/scheduled-tasks/<name>/ by any route; it
// may read it. On the gate before this change every write case below was allowed.

let root: string
let home: string
let store: string
let opts: Record<string, string>

beforeAll(() => {
  root = mkdtempSync(join(tmpdir(), 'sched-dir-'))
  home = join(root, 'home')
  store = join(home, '.claude', 'scheduled-tasks')
  mkdirSync(join(store, 'kernel-flotta-keret'), { recursive: true })
  writeFileSync(join(store, 'kernel-flotta-keret', 'SKILL.md'), 'x\n')
  // every agent's .claude-config/scheduled-tasks is a symlink to the store
  mkdirSync(join(root, 'agent', 'cfg'), { recursive: true })
  symlinkSync(store, join(root, 'agent', 'cfg', 'tasks-link'))
  opts = { home, cwd: join(root, 'agent') }
})
afterAll(() => { rmSync(root, { recursive: true, force: true }) })

const bash = (command: string, o: Record<string, string> = {}) => gateDecision('Bash', { command }, { ...opts, ...o })

describe('self-pace-gate: the per-task schedule store, native file tools', () => {
  it('denies Write / Edit / MultiEdit / NotebookEdit into the store by its path text', () => {
    expect(gateDecision('Write', { file_path: '/Users/x/.claude/scheduled-tasks/a/SKILL.md', content: 'y' }, opts)).toEqual({ deny: true, reason: 'schedule-dir' })
    expect(gateDecision('Edit', { file_path: '~/.claude/scheduled-tasks/a/task-config.json' }, opts).deny).toBe(true)
    expect(gateDecision('MultiEdit', { file_path: '/Users/x/agents/dave/.claude-config/scheduled-tasks/a/SKILL.md' }, opts).deny).toBe(true)
    expect(gateDecision('NotebookEdit', { notebook_path: '/Users/x/.claude/Scheduled-Tasks/a/n.ipynb' }, opts).deny).toBe(true)
  })
  it('denies by the real path: a symlink, a relative path, a new task directory', () => {
    expect(gateDecision('Write', { file_path: join(root, 'agent', 'cfg', 'tasks-link', 'kernel-flotta-keret', 'SKILL.md') }, opts).deny).toBe(true)
    expect(gateDecision('Write', { file_path: 'cfg/tasks-link/uj-feladat/SKILL.md' }, opts).deny).toBe(true)
    expect(gateDecision('Write', { file_path: join(store, 'uj', 'melyebb', 'task-config.json') }, opts).deny).toBe(true)
    expect(fileToolTargetsScheduleDir({ file_path: store }, store, root)).toBe(true)
  })
  it('allows a sibling with the same prefix, the repo templates and other files', () => {
    expect(gateDecision('Write', { file_path: join(home, '.claude', 'scheduled-tasks-old', 'x.md') }, opts).deny).toBe(false)
    expect(gateDecision('Write', { file_path: '/Users/x/marveen/scheduled-tasks/a/task-config.json' }, opts).deny).toBe(false)
    expect(gateDecision('Edit', { file_path: join(root, 'agent', 'notes.md') }, opts).deny).toBe(false)
  })
  it('the default store is <home>/.claude/scheduled-tasks', () => {
    expect(scheduleDirOf({ home: '/h' })).toBe('/h/.claude/scheduled-tasks')
    expect(scheduleDirOf({ scheduleDir: '/s' })).toBe('/s')
  })
})

describe('self-pace-gate: the per-task schedule store, Bash', () => {
  it('denies the write routes measured open on the old gate', () => {
    for (const c of [
      'cp /tmp/a ~/.claude/scheduled-tasks/x/SKILL.md',
      'mv a.md ~/.claude/scheduled-tasks/x/SKILL.md',
      'echo hi > ~/.claude/scheduled-tasks/x/SKILL.md',
      'echo hi >> "$HOME/.claude/scheduled-tasks/x/SKILL.md"',
      'printf x | tee ~/.claude/scheduled-tasks/x/SKILL.md',
      "python3 -c 'open(\"/Users/k/.claude/scheduled-tasks/x/SKILL.md\",\"w\").write(\"y\")'",
      'sed -i "" s/a/b/ ~/.claude/scheduled-tasks/x/SKILL.md',
      'mkdir -p ~/.claude/scheduled-tasks/new',
      'touch ~/.claude/scheduled-tasks/new/SKILL.md',
      'rm -rf ~/.claude/scheduled-tasks/x',
      'ln -s /tmp/evil ~/.claude/scheduled-tasks/x',
      'cp a "$CLAUDE_CONFIG_DIR/scheduled-tasks/x/SKILL.md"',
      'cp a ${CLAUDE_CONFIG_DIR}/scheduled-tasks/x/SKILL.md',
      'cp a agents/kernel/.claude-config/scheduled-tasks/x/SKILL.md',
      'find ~/.claude/scheduled-tasks -name "*.bak*" -delete',
      'find ~/.claude/scheduled-tasks -name SKILL.md -exec sed -i "" s/a/b/ {} +',
      'cat a > ~/.claude/scheduled-tasks/x/SKILL.md',
      'cat ~/.claude/scheduled-tasks/x/SKILL.md > $OUT',
      'git diff --output=/Users/k/.claude/scheduled-tasks/x/SKILL.md',
      'sh -c "cp a ~/.claude/scheduled-tasks/x/SKILL.md"',
    ]) {
      expect({ c, d: bash(c) }).toEqual({ c, d: { deny: true, reason: 'schedule-dir' } })
    }
  })
  it('a cd into the store makes the later segments count as inside it', () => {
    expect(bash('cd ~/.claude/scheduled-tasks/x && cp /tmp/a SKILL.md').deny).toBe(true)
    expect(bash('cd ~/.claude/scheduled-tasks/x; cat SKILL.md > SKILL.md.bak-1118').deny).toBe(true)
    expect(bash('pushd ~/.claude/scheduled-tasks && python3 w.py').deny).toBe(true)
    expect(bash('cd ~/.claude/scheduled-tasks/x && ls -la && cat SKILL.md').deny).toBe(false)
  })
  it('a for over the store or a variable set from it carries the store too', () => {
    expect(bash('for d in ~/.claude/scheduled-tasks/*elo*; do cp /tmp/a "$d/SKILL.md"; done').deny).toBe(true)
    expect(bash('f=$(ls -d ~/.claude/scheduled-tasks/*keret* | head -1); cp /tmp/a "$f/SKILL.md"').deny).toBe(true)
    expect(bash('for d in ~/.claude/scheduled-tasks/*elo*; do echo "== $d"; ls "$d"; cat "$d/SKILL.md"; done').deny).toBe(false)
    expect(bash('f=$(ls -d ~/.claude/scheduled-tasks/*keret* 2>/dev/null | head -1); [ -d "$f" ] && cat "$f/SKILL.md"').deny).toBe(false)
  })
  it('allows reading the store', () => {
    for (const c of [
      'cat ~/.claude/scheduled-tasks/x/SKILL.md',
      'grep -rn klodel2 ~/.claude/scheduled-tasks/',
      'ls -la ~/.claude/scheduled-tasks | head',
      'head -5 ~/.claude/scheduled-tasks/x/task-config.json 2>/dev/null',
      'shasum -a 256 ~/.claude/scheduled-tasks/x/SKILL.md',
      'find ~/.claude/scheduled-tasks -name SKILL.md -newer /tmp/t',
      'diff ~/.claude/scheduled-tasks/x/SKILL.md /tmp/b',
      'cat ~/.claude/scheduled-tasks/x/SKILL.md > /tmp/copy.md',
      'readlink agents/kernel/.claude-config/scheduled-tasks',
    ]) {
      expect({ c, d: bash(c).deny }).toEqual({ c, d: false })
    }
  })
  it('allows the path as text: a message, read-only git over source, a heredoc body', () => {
    expect(bash('bash scripts/agent-msg.sh kernel klodel "ird at a ~/.claude/scheduled-tasks/x/SKILL.md-t"').deny).toBe(false)
    expect(bash("git grep -n '.claude/scheduled-tasks' -- src").deny).toBe(false)
    expect(bash("git log --oneline -S'.claude/scheduled-tasks'").deny).toBe(false)
    expect(bash("cat > /tmp/note.txt <<'EOF'\nhelyes ut: ~/.claude/scheduled-tasks/x\nEOF").deny).toBe(false)
  })
  it('quoted separators do not cut fake segments (replay false denies)', () => {
    expect(bash("grep -n -E 'codex|--write' ~/.claude/scheduled-tasks/*/task-config.json 2>/dev/null | head -15").deny).toBe(false)
    expect(bash('grep -rl "07:30\\|30 7 " ~/.claude/scheduled-tasks/*kernel*/SKILL.md 2>/dev/null').deny).toBe(false)
    expect(bash('bash tools/msg-close.sh "kesz; a ~/.claude/scheduled-tasks/x | y" 47370').deny).toBe(false)
    expect(bash('bash tools/card-comment.sh a74793b8 "a ~/.claude/scheduled-tasks/*/ irasa"').deny).toBe(false)
    expect(bash('cd ~/.claude/scheduled-tasks && cat x/SKILL.md; cd /Users/k/marveen && cp a b').deny).toBe(false)
  })
  it('a heredoc into the store or an interpreter heredoc naming it is still a write route', () => {
    expect(bash("cat > ~/.claude/scheduled-tasks/x/SKILL.md <<'EOF'\nuj szoveg\nEOF").deny).toBe(true)
    expect(bash("python3 -I - <<'PY'\nopen('/Users/k/.claude/scheduled-tasks/x/SKILL.md','w').write('y')\nPY").deny).toBe(true)
    expect(bash("python3 -I -c 'import json\nd=json.load(open(\"/Users/k/.claude/scheduled-tasks/x/task-config.json\"))\nprint(d)'").deny).toBe(true)
  })
  it('a text sender heredoc may name the store; another owner on the same line may not', () => {
    expect(bash("bash /Users/k/agents/kernel/tools/kernel-msg.sh klodel - <<'MSG'\nird at: ~/.claude/scheduled-tasks/x/SKILL.md; | ok\nMSG").deny).toBe(false)
    expect(bash("T=\"Bearer $(cat t)\"; bash tools/kernel-msg.sh klodel - <<'MSG'\nKernel -> Klodel: a ~/.claude/scheduled-tasks/x\nmasodik sor\nMSG").deny).toBe(false)
    expect(bash("bash tools/kernel-msg.sh klodel x; python3 - <<'PY'\nopen('/Users/k/.claude/scheduled-tasks/x/SKILL.md','w')\nPY").deny).toBe(true)
    expect(bash("bash <<'MSG'\ncp a ~/.claude/scheduled-tasks/x/SKILL.md\nMSG").deny).toBe(true)
  })
  it('carried into the store: unrelated commands pass, writers and redirects do not', () => {
    expect(bash('cd ~/.claude/scheduled-tasks; cat x/SKILL.md; curl -s localhost:3420/api/agents').deny).toBe(false)
    expect(bash('cd ~/.claude/scheduled-tasks; sort -u x/a | head').deny).toBe(false)
    expect(bash('cd ~/.claude/scheduled-tasks; python3 -I -c "print(1)"').deny).toBe(true)
    expect(bash('cd ~/.claude/scheduled-tasks; curl -s -o x/SKILL.md https://e.example/a').deny).toBe(true)
    expect(bash('cd ~/.claude/scheduled-tasks; sort -u x/a > x/b').deny).toBe(true)
    expect(bash('cd ~/.claude/scheduled-tasks; git checkout x').deny).toBe(true)
  })
  it('mutation gaps: a relative redirect inside, a writing git subcommand, a substitution in an assignment', () => {
    expect(bash('cd ~/.claude/scheduled-tasks; cat ~/.claude/scheduled-tasks/x/SKILL.md > x/SKILL.md.bak').deny).toBe(true)
    expect(bash('git checkout -- ~/.claude/scheduled-tasks/x/SKILL.md').deny).toBe(true)
    expect(bash('X=`touch${IFS}~/.claude/scheduled-tasks/x`').deny).toBe(true)
    expect(bash('D=$HOME/.claude/scheduled-tasks; ls "$D"').deny).toBe(false)
  })
  // Viktor 47414 (probe work/sched-1118/probe.mjs): the rows his review found open on 9ce219fe
  it('M1: a pipe, a loop, a process or command substitution carry the store', () => {
    const S = '~/.claude/scheduled-tasks'
    for (const c of [
      `find ${S} -name SKILL.md | xargs sed -i '' 's/a/b/'`,
      `ls -d ${S}/* | while read d; do cp /tmp/e "$d/SKILL.md"; done`,
      `while read d; do cp /tmp/e "$d/SKILL.md"; done < <(ls -d ${S}/*)`,
      `echo $(cp /tmp/e ${S}/x/SKILL.md)`,
      'echo `cp /tmp/e ' + S + '/x/SKILL.md`',
      `ls "$(cp /tmp/e ${S}/x/SKILL.md)"`,
      `cd ${S} && cd x && cp /tmp/e SKILL.md`,
    ]) expect({ c, d: bash(c).deny }).toEqual({ c, d: true })
  })
  it('M2: inside the store an allowlist, not a writer list', () => {
    const S = '~/.claude/scheduled-tasks'
    for (const w of ['command cp /tmp/e', 'nohup cp /tmp/e', 'time cp /tmp/e', '"cp" /tmp/e', '\\cp /tmp/e',
      'ditto /tmp/e', 'wget https://e.example/', 'curl --remote-name https://e.example/']) {
      const c = `cd ${S}/x && ${w} SKILL.md`
      expect({ c, d: bash(c).deny }).toEqual({ c, d: true })
    }
  })
  it('L1: path spellings bash resolves', () => {
    for (const c of [
      'cp /tmp/e ~/.claude//scheduled-tasks/x/SKILL.md',
      'cp /tmp/e ~/.claude/./scheduled-tasks/x/SKILL.md',
      'cp /tmp/e "$HOME/.claude"/scheduled-tasks/x/SKILL.md',
      'cp /tmp/e "$CLAUDE_CONFIG_DIR"/scheduled-tasks/x/SKILL.md',
      'cp /tmp/e ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/scheduled-tasks/x/SKILL.md',
      'cp /tmp/e ~/.claude/schedule"d-tasks"/x/SKILL.md',
    ]) expect({ c, d: bash(c).deny }).toEqual({ c, d: true })
  })
  // mutation gaps on f5b61d73 (work/sched-store-1118/mutants2.json, 1-based M1 M5 M6 M7 M8)
  it('mutation gaps: a backslash in the path, text filters that write, git -C on a tainted line', () => {
    const S = '~/.claude/scheduled-tasks'
    expect(bash('cp /tmp/e ~/.claude/sched\\uled-tasks/x/SKILL.md').deny).toBe(true) // M1
    expect(bash(`ls ${S} | sort -o /tmp/f`).deny).toBe(true) // M6: sort -o writes a file
    expect(bash(`ls ${S} | sort --output=/tmp/f`).deny).toBe(true)
    expect(bash(`ls ${S} | uniq - /tmp/out`).deny).toBe(true) // M7: a second uniq operand writes
    expect(bash(`ls ${S} | sort | uniq -c`).deny).toBe(false) // M5: pure filters on a tainted line pass
    expect(bash(`cat ${S}/x/SKILL.md | sort -u | head`).deny).toBe(false)
    expect(bash(`cat ${S}/x/SKILL.md; git -C /Users/k/marveen log -1`).deny).toBe(false) // M8
    expect(bash(`cat ${S}/x/SKILL.md; git -C /Users/k/marveen checkout -- a`).deny).toBe(true)
  })
  it('after a read of the store, an absolute cd and later work elsewhere stay free', () => {
    expect(bash('cd ~/.claude/scheduled-tasks && cat x/SKILL.md; cd /Users/k/marveen && cp a b').deny).toBe(false)
    expect(bash('cd ~/.claude/scheduled-tasks; sort -u x/a | head').deny).toBe(false)
  })
  it('an absolute cd does not clear the taint when a later segment names the store again (mutation gap M13)', () => {
    const S = '~/.claude/scheduled-tasks'
    expect(bash(`cat ${S}/x/SKILL.md; cd /tmp; ls -d ${S}/* | while read d; do cp /tmp/e "$d/SKILL.md"; done`).deny).toBe(true)
    expect(bash(`cat ${S}/x/SKILL.md; cd /tmp && while read d; do cp /tmp/e "$d"; done < <(ls -d ${S}/*)`).deny).toBe(true)
  })
  it('leaves the repo templates (no .claude in the path) and other commands alone', () => {
    expect(bash('cp a scheduled-tasks/x/task-config.json').deny).toBe(false)
    expect(bash('cp a.md ~/.claude/skills-notes/x.md').deny).toBe(false)
    expect(scheduleDirBashSegmentAllowed('npm test')).toBe(true)
    expect(scheduleDirBashSegmentAllowed('cp a b', true)).toBe(false)
  })
})

// Viktor 47811 L1 (card 291bd837): a bare scheduled-tasks word is the store when the command runs in ~/.claude
// (its cwd, or a `cd ~/.claude` in the shell text). On the gate before, X01 X02 X09 X10 X11 X12 were allowed.
describe('self-pace-gate: the store named relatively from ~/.claude', () => {
  let cl: string
  let cfg: string
  beforeAll(() => {
    cl = join(home, '.claude')
    cfg = join(root, 'agent2', '.claude-config')   // an agent's config dir: its scheduled-tasks links to the store
    mkdirSync(cfg, { recursive: true })
    symlinkSync(store, join(cfg, 'scheduled-tasks'))
  })
  it('denies a write that names the store only by the bare word', () => {
    for (const [c, cwd] of [
      ["cd ~/.claude && find scheduled-tasks -name SKILL.md | xargs sed -i '' s/a/b/", undefined],
      ['ls -d scheduled-tasks/* | while read d; do cp /tmp/e "$d/SKILL.md"; done', 'CL'],
      ['find scheduled-tasks -name "*.pending" | xargs rm', 'CL'],
      ['cd ~/.claude && ls -d scheduled-tasks/* | while read d; do cp /tmp/e "$d/SKILL.md"; done', undefined],
      ['cd ~/.claude && cp /tmp/e scheduled-tasks/x/SKILL.md', undefined],
      ['cd ~/.claude && cp /tmp/e ./scheduled-tasks/x/SKILL.md', undefined],
      ['cp /tmp/e scheduled-tasks/x/SKILL.md', 'CFG'],
    ] as const) {
      const o: Record<string, string> = cwd === 'CL' ? { cwd: cl } : cwd === 'CFG' ? { cwd: cfg } : {}
      expect({ c, cwd, d: bash(c, o) }).toEqual({ c, cwd, d: { deny: true, reason: 'schedule-dir' } })
    }
  })
  it('leaves the bare word alone away from ~/.claude, a read in it, and a heredoc body that spells .claude', () => {
    expect(bash('grep -rn scheduled-tasks /tmp/notes.md').deny).toBe(false)
    expect(bash('cp a scheduled-tasks/x/SKILL.md').deny).toBe(false)               // the repo templates
    expect(bash('ls scheduled-tasks/x && cat scheduled-tasks/x/SKILL.md', { cwd: cl }).deny).toBe(false)
    expect(bash("cat > /tmp/rows.txt <<'EOF'\ncd ~/.claude && find scheduled-tasks\nEOF\nls scheduled-tasks | while read n; do cp /tmp/a \"/tmp/out/$n\"; done").deny).toBe(false)
    // where an anchored word WOULD deny: an interpreter heredoc (a text-tool heredoc such as cat's is blanked earlier)
    expect(bash("python3 - <<'PY'\nprint('cd ~/.claude')\nPY\nfind scheduled-tasks -name '*.pending' | xargs rm").deny).toBe(false)
    expect(bash("node - <<'JS'\nconsole.log('.claude')\nJS\ncp /tmp/e scheduled-tasks/x/SKILL.md").deny).toBe(false)
    expect(bash("cd ~/.claude\nfind scheduled-tasks -name '*.pending' | xargs rm").deny).toBe(true)
  })
})

describe('self-pace-gate: the hook end to end on a store write', () => {
  it('prints a deny with the schedule-store message and the main-agent route', () => {
    const r = spawnSync(process.execPath, [join(__dirname, '..', '..', 'scripts', 'self-pace-gate.mjs')], {
      input: JSON.stringify({ tool_name: 'Write', cwd: root, tool_input: { file_path: '/Users/x/.claude/scheduled-tasks/a/SKILL.md', content: 'y' } }),
      encoding: 'utf-8',
    })
    expect(r.status).toBe(0)
    const out = JSON.parse(r.stdout)
    expect(out.hookSpecificOutput.permissionDecision).toBe('deny')
    expect(out.hookSpecificOutput.permissionDecisionReason).toMatch(/Utemezes-tar TILTOTT/)
    expect(out.hookSpecificOutput.permissionDecisionReason).toMatch(/fo agenstol/)
  })
})
