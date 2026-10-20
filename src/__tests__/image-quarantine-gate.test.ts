// IMAGESAFETY1020 (card 1a4fe725, Viktor 9018 F3): no agent opens an unscreened or
// quarantined image -- by a file tool, an MCP tool or a Bash reader. Listing names
// stays allowed, and so does writing new images INTO _unscreened/.
import { describe, it, expect, afterEach } from 'vitest'
// @ts-expect-error -- plain .mjs hook script, no types
import { gateDecision } from '../../scripts/self-pace-gate.mjs'
import { spawnSync } from 'node:child_process'
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  IMAGE_QUARANTINE_GATE_MATCHER,
  ensureImageQuarantineGate,
  injectImageQuarantineGate,
  injectSelfPaceGate,
} from '../web/agent-scaffold.js'
import { MAIN_AGENT_ID, PROJECT_ROOT } from '../config.js'

const decide = (tool: string, input: Record<string, unknown>) => gateDecision(tool, input, {})
const DENY = { deny: true, reason: 'image-quarantine' }
const ROOT = '/Users/klodel/marveen/agents/mira/tools/mflux'

describe('file tools', () => {
  it.each([
    ['Read', { file_path: `${ROOT}/_quarantine/a_seed7.png` }],
    ['Read', { file_path: `${ROOT}/_unscreened/panna/a_seed7.png` }],
    ['Read', { file_path: `${ROOT}/out/panna-elvetett/husvet_seed7.png` }],
    ['Read', { file_path: `${ROOT}/final/visszavonva/husvet.jpg` }],
    ['Grep', { pattern: 'x', path: `${ROOT}/_quarantine` }],
    ['Write', { file_path: `${ROOT}/_quarantine/a.png`, content: '' }],
    ['Glob', { pattern: '**/*.png', path: `${ROOT}/_quarantine` }],
    ['Glob', { pattern: '**/_unscreened/**' }],
    // review B2: APFS is case-insensitive
    ['Read', { file_path: `${ROOT}/_Quarantine/a.png` }],
    ['Read', { file_path: `${ROOT.toUpperCase()}/_QUARANTINE/A.PNG` }],
    ['Read', { file_path: `${ROOT}/out/Panna-Elvetett/x.png` }],
    // review I1: percent-encoded
    ['Read', { file_path: `${ROOT}/%5Fquarantine/a.png` }],
  ])('%s on a screening dir is denied', (tool, input) => {
    expect(decide(tool, input)).toEqual(DENY)
  })

  it.each([
    ['Read', { file_path: `${ROOT}/out/panna/a_seed7.png` }],
    ['Read', { file_path: `${ROOT}/scripts/check_quarantine.py` }],
    ['Read', { file_path: '/repo/scripts/image-safety/check.py' }],
    ['Edit', { file_path: '/repo/scripts/image-safety/check.py', old_string: 'QUARANTINE = "_quarantine"', new_string: "QUARANTINE = '_quarantine'" }],
    ['Grep', { pattern: '_quarantine', path: '/repo/scripts' }],
  ])('%s outside the screening dirs passes', (tool, input) => {
    expect(decide(tool, input)).toEqual({ deny: false })
  })
})

describe('MCP tools', () => {
  it.each([
    ['mcp__playwright__browser_navigate', { url: `file://${ROOT}/_quarantine/a.png` }],
    ['mcp__plugin_telegram_telegram__reply', { chat_id: '1', text: 'x', files: [`${ROOT}/_unscreened/a.png`] }],
    ['mcp__playwright__browser_navigate', { url: `file://${ROOT}/%5Fquarantine/a.png` }],
    ['mcp__playwright__browser_navigate', { url: `file://${ROOT}/_QUARANTINE/a.png` }],
  ])('%s with a screening path is denied', (tool, input) => {
    expect(decide(tool, input)).toEqual(DENY)
  })

  it('an MCP tool without one passes', () => {
    expect(decide('mcp__playwright__browser_navigate', { url: 'https://example.com/_quarantine-docs' })).toEqual({ deny: false })
  })

  it('a channel message that only names the directory passes', () => {
    expect(decide('mcp__plugin_telegram_telegram__reply', { chat_id: '1', text: 'a _quarantine mappa mode 000' })).toEqual({ deny: false })
  })
})

describe('Bash', () => {
  it.each([
    'cat out/_quarantine/a.png',
    `open ${ROOT}/_quarantine/a.png`,
    'qlmanage -p _unscreened/a.png',
    'sips -g all out/panna-elvetett/x.png',
    'cp final/visszavonva/husvet.jpg /tmp/',
    'base64 _quarantine/a.png',
    'chmod 644 _quarantine/a.png',
    'mv _quarantine/a.png out/',
    'ls _quarantine/ && cat _quarantine/a.png',
    'ls _quarantine > _quarantine/list.txt',
    'mkdir -p _quarantine/x',
    'mflux-generate --output _quarantine/x.png',
    "python3 - <<'EOF'\nopen('/m/_quarantine/a.png','rb').read()\nEOF",
    // review B2
    `cat ${ROOT}/_QUARANTINE/a.png`,
    'open out/Panna-Elvetett/x.png',
    // review B3: the bare directory name, no slash
    `cd ${ROOT} && cd _unscreened`,
    'cp -R _unscreened /tmp/x',
    'mv _unscreened /tmp/u',
    'tar cf /tmp/u.tar _unscreened',
    'zip -r /tmp/q.zip _quarantine',
    'rsync -a _unscreened /tmp/u',
    'chmod -R 755 _quarantine',
    'open _unscreened',
    'cp -R final/visszavonva /tmp/v',
    'grep -n _quarantine scripts/image-safety/check.py',
    'git add -f agents/mira/tools/mflux/_quarantine/a.png',
    'ls _quarantine > /tmp/x && cat /tmp/x _quarantine/a.png',
    // review L4: git reading raw bytes outside the repo
    'git diff --no-index --text _unscreened/a.png /dev/null',
    "git grep --no-index -a . -- _unscreened",
    'git diff --no-index _unscreened/a.png /dev/null',
    'git --no-pager diff --tex _unscreened/a.png /dev/null',
    'git diff --binary -- _unscreened',
    // review L5: git resolves the abbreviation --bi to --binary
    'git diff --bi _unscreened/x.png /dev/null',
    'git grep -Ia x -- _quarantine',
  ])('denies: %s', (command) => {
    expect(decide('Bash', { command })).toEqual(DENY)
  })

  it.each([
    'ls -la _quarantine/',
    `ls ${ROOT}/out/panna-elvetett`,
    'du -sh _quarantine/',
    'ls _quarantine',
    'du -sh _QUARANTINE',
    'git grep -n _quarantine',
    'git log --stat -- agents/mira/tools/mflux/_quarantine',
    'git diff -- scripts/image-safety/check.py',
    'git commit -m "screen into out/_quarantine/ first"',
    'mkdir -p _unscreened/panna',
    'venv/bin/mflux-generate-z-image-turbo --prompt-file p.txt --output _unscreened/panna/a_seed{seed}.png',
    'python3 scripts/image-safety/check.py --root . inbox --dest out/panna',
  ])('allows: %s', (command) => {
    expect(decide('Bash', { command })).toEqual({ deny: false })
  })
})

// Pulzus 9266: a name in a report or message is text, not a file read.
// Viktor #5144: the probe2 cases (R*, E*) are below.
describe('Bash: names as text (false-deny fix)', () => {
  const Q = '/Users/klodel/marveen/out/_quarantine/a.png'
  const U = '/Users/klodel/marveen/out/_unscreened/a.png'
  const hd = (owner: string, body: string) => `${owner} <<'EOF'\n${body}\nEOF`
  it.each([
    `python3 -I cardc.py 1a4fe725 <<'EOF'\nmoved to x/_quarantine/a.png\nEOF`,
    `python3 -I -u cardc.py X <<'EOF'\nx/_quarantine/a.png\nEOF`,
    `bash -e run.sh <<'EOF'\nx/_quarantine/a.png\nEOF`,
    `node tool.mjs <<'EOF'\nx/_quarantine/a.png\nEOF`,
    // flags after the script operand are the script's own argv
    `python3 scripts/report.py -W ignore <<'EOF'\nx/_unscreened/a.png\nEOF`,
    'echo "x/_quarantine/y.png"',
    `echo ${Q}`,
    `printf '%s\\n' "x/_quarantine/y.png"`,
    'bash /Users/klodel/marveen/scripts/agent-msg.sh kernel viktor "see x/_quarantine/a.png"',
    `bash /Users/klodel/marveen/scripts/agent-msg.sh viktor kernel - <<'EOF'\nmoved to ${Q}\nEOF`,
    `cat <<'EOF' | bash agent-msg.sh a b -\nx/_quarantine/a\nEOF`,
    // Viktor #5144 B2: a name piped into a text filter
    'ls x/_quarantine | grep png | wc -l',
    'ls -la x/_quarantine/ 2>&1 | head -5',
    'ls x/_quarantine | sort | uniq -c',
  ])('allows: %s', (command) => {
    expect(decide('Bash', { command })).toEqual({ deny: false })
  })

  it.each([
    // the interpreter reads its code from stdin
    `python3 - <<'EOF'\nopen('x/_quarantine/a.png').read()\nEOF`,
    `python3 -I <<'EOF'\nopen('x/_quarantine/a.png').read()\nEOF`,
    `python3 -m code <<'EOF'\nopen('x/_quarantine/a.png')\nEOF`,
    `python3 -Ic 'import sys; exec(sys.stdin.read())' <<'EOF'\nopen('x/_quarantine/a.png')\nEOF`,
    `bash -s <<'EOF'\ncat x/_quarantine/a.png\nEOF`,
    `bash <<'EOF'\ncat x/_quarantine/a.png\nEOF`,
    `node <<'EOF'\nrequire('fs').readFileSync('x/_quarantine/a.png')\nEOF`,
    `ssh box cat <<'EOF'\nx/_quarantine/a.png\nEOF`,
    // content fed into a name printer
    'ls $(cat x/_quarantine/a.png)',
    'echo `cat x/_quarantine/a.png`',
    'echo "$(cat x/_quarantine/a.png)"',
    'echo <(cat x/_quarantine/a.png)',
    'ls x/_quarantine < x/_quarantine/a.png',
    'bash agent-msg.sh a b - < x/_quarantine/a.png',
    'echo hi > x/_quarantine/a.png',
    // a script argument is still a possible read
    'python3 script.py x/_quarantine/a.png',
    'bash other.sh "x/_unscreened/a.png"',
    // Viktor #5144 B1: a flag value is not a script operand, the body is code
    hd('bash -o pipefail', `cat ${Q}`),
    hd('sh -o errexit', `cat ${Q}`),
    hd('node -r ./x.js', `require("fs").readFileSync("${Q}")`),
    hd('node --require ./x.js', `require("fs").readFileSync("${Q}")`),
    hd('node --import ./x.mjs', `require("fs").readFileSync("${Q}")`),
    hd('perl -I lib', `open F,"${Q}"; print <F>`),
    hd('ruby -r json', `print File.read("${Q}")`),
    hd('bash -O extglob', `cat ${Q}`),
    hd('bash --rcfile /dev/null', `cat ${Q}`),
    hd('python3 -W ignore', `print(open("${Q}","rb").read())`),
    hd('php -d display_errors=1', `<?php echo file_get_contents("${Q}");`),
    hd('python3 /dev/stdin', `open("${Q}")`),
    hd('python3 notascript', `open("${Q}")`),
    `echo $(<${Q})`,
    `bash /Users/klodel/marveen/scripts/agent-msg.sh viktor kernel - < ${Q}`,
    // B2: a stage that names the dir pipes only into a text filter
    `echo ${Q} | xargs cat`,
    'echo "x/_quarantine/a.png" | xargs cat',
    `ls ${Q} | xargs cat`,
    `printf '%s\\n' ${U} | xargs base64`,
    `printf '%s\\n' '${Q}' | xargs -I{} cp {} /tmp/o`,
    `echo ${Q} | while read f; do base64 "$f"; done`,
    `echo ${Q} | sh`,
    `ls x/_quarantine | awk '{getline l < $0; print l}'`,
    'ls x/_quarantine |& xargs cat',
    'ls x/_quarantine 2>&1 | xargs cat',
    // L1: a heredoc of names for xargs / while read
    hd('xargs cat', Q),
    `while read f; do base64 "$f"; done <<'EOF'\n${Q}\nEOF`,
  ])('denies: %s', (command) => {
    expect(decide('Bash', { command })).toEqual(DENY)
  })
})

// Review P2 (Klodel 9186): the main agent does not run self-pace-gate.mjs, so the
// same decision runs from its own hook, wired in the repo-shipped settings.
describe('main-agent hook (scripts/hooks/image-quarantine-gate.mjs)', () => {
  const HOOK = join(__dirname, '..', '..', 'scripts', 'hooks', 'image-quarantine-gate.mjs')
  const run = (stdin: string) => spawnSync(process.execPath, [HOOK], { input: stdin, encoding: 'utf-8' })

  it('denies a quarantined path with the quarantine message, exit 0', () => {
    const r = run(JSON.stringify({ tool_name: 'Read', tool_input: { file_path: `${ROOT}/_quarantine/a.png` } }))
    expect(r.status).toBe(0)
    const out = JSON.parse(r.stdout)
    expect(out.hookSpecificOutput.permissionDecision).toBe('deny')
    expect(out.hookSpecificOutput.permissionDecisionReason).toContain('IMAGESAFETY1020')
  })

  it.each([
    JSON.stringify({ tool_name: 'Read', tool_input: { file_path: `${ROOT}/out/a.png` } }),
    JSON.stringify({ tool_name: 'Bash', tool_input: { command: 'ls _quarantine' } }),
    'not json',
    '',
  ])('allows silently: %s', (stdin) => {
    const r = run(stdin)
    expect(r.status).toBe(0)
    expect(r.stdout).toBe('')
  })

  it('denies a wrapped sh -c reader', () => {
    const r = run(JSON.stringify({ tool_name: 'Bash', tool_input: { command: "sh -c 'cat _unscreened/a.png'" } }))
    expect(JSON.parse(r.stdout).hookSpecificOutput.permissionDecision).toBe('deny')
  })

  it('is wired in the repo settings for every tool the decision covers', () => {
    const settings = JSON.parse(readFileSync(join(__dirname, '..', '..', '.claude', 'settings.json'), 'utf-8'))
    const entry = settings.hooks.PreToolUse.find((e: { hooks: { command: string }[] }) =>
      e.hooks.some((h) => h.command.includes('scripts/hooks/image-quarantine-gate.mjs')))
    expect(entry).toBeTruthy()
    const rx = new RegExp(`^(?:${entry.matcher})$`)
    for (const t of ['Bash', 'Read', 'Write', 'Edit', 'MultiEdit', 'NotebookEdit', 'Grep', 'Glob', 'mcp__playwright__browser_navigate', 'mcp__plugin_telegram_telegram__reply']) {
      expect(rx.test(t), t).toBe(true)
    }
    // fail-closed when node is missing, like the egress gate
    expect(entry.hooks[0].command).toContain('exit 2')
  })
})

// The sub-agents run the same decision inside self-pace-gate.mjs, but that hook's
// matcher never fires on Read, Grep, Glob, MultiEdit or an MCP tool (measured on
// all ten live sub-agent settings, 2026-10-20), so the hook is seeded for them too.
describe('sub-agent wiring (agent-scaffold)', () => {
  const TEST_AGENT = 'imgquarantine-test-agent'
  const testAgentDir = join(PROJECT_ROOT, 'agents', TEST_AGENT)
  const settingsPath = join(testAgentDir, '.claude', 'settings.json')
  type Entry = { matcher: string; hooks: { command: string }[] }
  const ptu = (settings: { hooks: { PreToolUse: Entry[] } }) => settings.hooks.PreToolUse
  const firesFor = (entries: Entry[], tool: string) => entries.some((e) =>
    e.hooks.some((h) => h.command.includes('image-quarantine-gate.mjs')) && new RegExp(`^(?:${e.matcher})$`).test(tool))

  afterEach(() => {
    rmSync(testAgentDir, { recursive: true, force: true })
  })

  it('uses the same matcher as the main agent hook in the repo settings', () => {
    const settings = JSON.parse(readFileSync(join(__dirname, '..', '..', '.claude', 'settings.json'), 'utf-8'))
    const entry = ptu(settings).find((e) => e.hooks.some((h) => h.command.includes('image-quarantine-gate.mjs')))
    expect(entry?.matcher).toBe(IMAGE_QUARANTINE_GATE_MATCHER)
  })

  it('the self-pace gate alone misses Read; with the seeded hook every file tool is covered', () => {
    const settings = {} as { hooks: { PreToolUse: Entry[] } }
    injectSelfPaceGate(settings as unknown as Record<string, unknown>, TEST_AGENT)
    const pace = ptu(settings).find((e) => e.hooks.some((h) => h.command.includes('self-pace-gate.mjs')))!
    expect(new RegExp(`^(?:${pace.matcher})$`).test('Read')).toBe(false)
    injectImageQuarantineGate(settings as unknown as Record<string, unknown>)
    for (const t of ['Bash', 'Read', 'Write', 'Edit', 'MultiEdit', 'NotebookEdit', 'Grep', 'Glob', 'mcp__playwright__browser_navigate']) {
      expect(firesFor(ptu(settings), t), t).toBe(true)
    }
  })

  it('ensureImageQuarantineGate replaces a narrower entry in place, then settles', () => {
    mkdirSync(join(testAgentDir, '.claude'), { recursive: true })
    const narrow = { matcher: 'Bash', hooks: [{ type: 'command', command: `node ${join(PROJECT_ROOT, 'scripts', 'hooks', 'image-quarantine-gate.mjs')}`, timeout: 10 }] }
    writeFileSync(settingsPath, JSON.stringify({ hooks: { PreToolUse: [narrow] } }, null, 2))
    expect(ensureImageQuarantineGate(TEST_AGENT)).toBe(true)
    expect(ensureImageQuarantineGate(TEST_AGENT)).toBe(false)
    const entries = ptu(JSON.parse(readFileSync(settingsPath, 'utf-8')))
    expect(entries.filter((e) => JSON.stringify(e).includes('image-quarantine-gate.mjs'))).toHaveLength(1)
    expect(firesFor(entries, 'Read')).toBe(true)
  })

  it('leaves the main agent and a never-spawned agent alone', () => {
    expect(ensureImageQuarantineGate(MAIN_AGENT_ID)).toBe(false)
    expect(ensureImageQuarantineGate(TEST_AGENT)).toBe(false)
  })
})
