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
