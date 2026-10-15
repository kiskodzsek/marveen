import { describe, it, expect } from 'vitest'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
// @ts-expect-error -- plain .mjs script, no types
import { build, HEADER } from '../../scripts/fleet-rules-sync.mjs'

// FLEETRULESSYNC1015 (card 834a0364): the sync copies the root's fleet sections
// verbatim, and refuses to write while any root section is unclassified.
const ROOT = [
  '# Owner bot',
  '## Persona',
  'I am the main agent.',
  '## Hard rules (owner)',
  '- never send mail',
  '```bash',
  '## not a heading inside a fence',
  'curl -s http://localhost:3420/api/x -H "Authorization: Bearer $(cat store/.dashboard-token)"',
  '```',
  '## Inter-agent messages',
  'send with from "klodel"',
  '### Unknown sender pings',
  'main-agent-only procedure',
  '## Skills',
  '### Progressive disclosure',
  '- keep SKILL.md short',
  '### Reflection',
  'main only',
  '## Time handling',
  'use Europe/Budapest',
  '',
].join('\n')

const MAP = {
  fleet: [
    'Hard rules',
    { heading: 'Inter-agent messages', stop_at: 'Unknown sender' },
    { h3: 'Progressive disclosure', title: 'Skill writing' },
  ],
  agent_file: ['Skills', 'Time handling'],
  main_only: ['Persona'],
  substitutions: [['http://localhost:3420', '{{DASHBOARD_ORIGIN}}'], ['$(cat store/', '$(cat {{PROJECT_ROOT}}/store/']],
}

describe('fleet-rules-sync build()', () => {
  it('copies the fleet sections verbatim, in map order, with the placeholders', () => {
    const { text, problems } = build(ROOT, MAP)
    expect(problems).toEqual([])
    expect(text.startsWith(HEADER)).toBe(true)
    const body = text.slice(HEADER.length)
    expect(body).toBe([
      '',
      '## Hard rules (owner)',
      '- never send mail',
      '```bash',
      '## not a heading inside a fence',
      'curl -s {{DASHBOARD_ORIGIN}}/api/x -H "Authorization: Bearer $(cat {{PROJECT_ROOT}}/store/.dashboard-token)"',
      '```',
      '',
      '## Inter-agent messages',
      'send with from "klodel"',
      '',
      '## Skill writing',
      '',
      '- keep SKILL.md short',
      '',
    ].join('\n'))
    expect(body).not.toContain('main-agent-only procedure')
    expect(body).not.toContain('I am the main agent')
  })

  it('stops on an unclassified root section', () => {
    const { problems } = build(`${ROOT}## New rule (owner, today)\n- something\n`, MAP)
    expect(problems).toEqual(['unclassified root section: "## New rule (owner, today)"'])
  })

  it('stops when a fleet section disappeared from the root, or a prefix became ambiguous', () => {
    expect(build(ROOT.replace('## Hard rules (owner)', '## Rules'), { ...MAP, agent_file: [...MAP.agent_file, 'Rules'] }).problems)
      .toEqual(['fleet entry not in the root: "## Hard rules"'])
    expect(build(`${ROOT}## Hard rules, part 2\nx\n`, MAP).problems.join('\n')).toMatch(/matches 2 root sections/)
    expect(build(ROOT.replace('### Progressive disclosure', '### Disclosure'), MAP).problems)
      .toEqual(['fleet entry not in the root: "### Progressive disclosure"'])
  })
})

describe('scripts/fleet-rules-sync.mjs', () => {
  const script = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'scripts', 'fleet-rules-sync.mjs')
  const run = (inst: string, ...args: string[]) =>
    spawnSync(process.execPath, [script, '--root', inst, ...args], { encoding: 'utf-8' })

  it('writes and stamps; a root edit goes stale until re-synced; a new section blocks the write', () => {
    const inst = mkdtempSync(join(tmpdir(), 'frsync-'))
    mkdirSync(join(inst, 'store'))
    writeFileSync(join(inst, 'CLAUDE.md'), ROOT)
    writeFileSync(join(inst, 'store', 'fleet-rules-map.json'), JSON.stringify(MAP))
    const rules = join(inst, 'store', 'fleet-rules.md')

    expect(run(inst, '--check').status).toBe(1)
    expect(run(inst).status).toBe(0)
    expect(run(inst, '--check').status).toBe(0)
    expect(readFileSync(rules, 'utf-8')).toMatch(/synced-from-root-sha256=[0-9a-f]{64}/)

    writeFileSync(join(inst, 'CLAUDE.md'), ROOT.replace('- never send mail', '- never send mail, ever'))
    expect(run(inst, '--check').status).toBe(1)
    expect(run(inst).status).toBe(0)
    expect(readFileSync(rules, 'utf-8')).toContain('- never send mail, ever')
    expect(run(inst, '--check').status).toBe(0)

    const before = readFileSync(rules, 'utf-8')
    writeFileSync(join(inst, 'CLAUDE.md'), `${ROOT}## New rule (owner)\n- x\n`)
    const blocked = run(inst)
    expect(blocked.status).toBe(1)
    expect(blocked.stderr).toContain('unclassified root section: "## New rule (owner)"')
    expect(readFileSync(rules, 'utf-8')).toBe(before)
    expect(run(inst, '--check').status).toBe(1)
  })

  it('cannot run without the map (exit 2), and writes nothing', () => {
    const inst = mkdtempSync(join(tmpdir(), 'frsync-'))
    mkdirSync(join(inst, 'store'))
    writeFileSync(join(inst, 'CLAUDE.md'), ROOT)
    expect(run(inst).status).toBe(2)
    expect(existsSync(join(inst, 'store', 'fleet-rules.md'))).toBe(false)
  })
})
