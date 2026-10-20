// IMAGESAFETY1020 (card 1a4fe725, Viktor 9018 F3): no agent opens an unscreened or
// quarantined image -- by a file tool, an MCP tool or a Bash reader. Listing names
// stays allowed, and so does writing new images INTO _unscreened/.
import { describe, it, expect } from 'vitest'
// @ts-expect-error -- plain .mjs hook script, no types
import { gateDecision } from '../../scripts/self-pace-gate.mjs'

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
  ])('%s on a screening dir is denied', (tool, input) => {
    expect(decide(tool, input)).toEqual(DENY)
  })

  it.each([
    ['Read', { file_path: `${ROOT}/out/panna/a_seed7.png` }],
    ['Read', { file_path: `${ROOT}/scripts/check_quarantine.py` }],
    ['Read', { file_path: '/repo/scripts/image-safety/check.py' }],
    ['Edit', { file_path: '/repo/scripts/image-safety/check.py', old_string: 'QUARANTINE = "_quarantine"', new_string: 'x' }],
  ])('%s outside the screening dirs passes', (tool, input) => {
    expect(decide(tool, input)).toEqual({ deny: false })
  })
})

describe('MCP tools', () => {
  it.each([
    ['mcp__playwright__browser_navigate', { url: `file://${ROOT}/_quarantine/a.png` }],
    ['mcp__plugin_telegram_telegram__reply', { chat_id: '1', text: 'x', files: [`${ROOT}/_unscreened/a.png`] }],
  ])('%s with a screening path is denied', (tool, input) => {
    expect(decide(tool, input)).toEqual(DENY)
  })

  it('an MCP tool without one passes', () => {
    expect(decide('mcp__playwright__browser_navigate', { url: 'https://example.com/_quarantine-docs' })).toEqual({ deny: false })
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
  ])('denies: %s', (command) => {
    expect(decide('Bash', { command })).toEqual(DENY)
  })

  it.each([
    'ls -la _quarantine/',
    `ls ${ROOT}/out/panna-elvetett`,
    'du -sh _quarantine/',
    'grep -n _quarantine scripts/image-safety/check.py',
    'git commit -m "screen into out/_quarantine/ first"',
    'mkdir -p _unscreened/panna',
    'venv/bin/mflux-generate-z-image-turbo --prompt-file p.txt --output _unscreened/panna/a_seed{seed}.png',
    'python3 scripts/image-safety/check.py --root . inbox --dest out/panna',
  ])('allows: %s', (command) => {
    expect(decide('Bash', { command })).toEqual({ deny: false })
  })
})
