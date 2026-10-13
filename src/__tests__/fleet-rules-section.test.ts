// FLEETRULES1013: a sub-agent that opts in (agent-config.json
// "excludeRootClaudeMd": true) carries the fleet rules as a generated block
// rendered from the install-local store/fleet-rules.md, and only then stops
// loading the root CLAUDE.md (claudeMdExcludes in its project settings).
//
// The safety property pinned here: NO BLOCK, NO EXCLUSION. Every path that
// cannot render the block (opted out, rules file missing/empty, rules stamped
// against an older root, glob-shaped root) leaves or puts back the root load;
// the failure mode is "too many rules", never "rules silently gone".
//
// Viktor's review of the first version (2026-10-13) added three things pinned
// here too: the rules text never ships in a versioned file (F1), a root edit
// after the last sync puts the root load back (F2), and taking the exclusion
// out removes the exclusion before the block (L1). L2: the glob guard and the
// symlinked-root spelling have their own tests.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  mkdtempSync, writeFileSync, readFileSync, mkdirSync, rmSync, existsSync, realpathSync, symlinkSync,
} from 'node:fs'
import { join, dirname } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'
import { execFileSync, spawnSync } from 'node:child_process'

const tmpRoot = realpathSync(mkdtempSync(join(tmpdir(), 'marveen-fleetrules-test-')))
const optIn = new Map<string, boolean>()
const failWrites = new Set<string>()

vi.mock('../config.js', () => ({
  STORE_DIR: join(tmpRoot, 'store'),
  PROJECT_ROOT: tmpRoot,
  OWNER_NAME: 'TestOwner',
  MAIN_AGENT_ID: 'agent-a',
  BOT_NAME: 'agent-a',
  CHANNEL_PROVIDER: 'telegram',
  WEB_PORT: 3420,
  OWNER_DRIVE_FOLDER: '',
  DASHBOARD_PUBLIC_URL: '',
  AGENT_API_ORIGIN: '',
  APP_TZ: 'Europe/Budapest',
}))

vi.mock('../web/agent-config.js', () => ({
  agentDir: (name: string) => join(tmpRoot, 'agents', name),
  agentConfigRoot: () => join(tmpRoot, 'agents'),
  listAgentNames: () => ['agent-a', 'agent-b'],
  readAgentCapabilities: () => [],
  readAgentToolDeny: () => [],
  readAgentExcludeRootClaudeMd: (name: string) => optIn.get(name) === true,
}))

vi.mock('../web/atomic-write.js', () => ({
  atomicWriteFileSync: (path: string, content: string) => {
    if (failWrites.has(path)) throw new Error(`simulated write failure: ${path}`)
    writeFileSync(path, content, 'utf-8')
  },
}))

const {
  ensureFleetRulesSection, buildFleetRulesBody, rootClaudeMdExcludePaths, fleetRulesStamp, rootClaudeMdSha256,
} = await import('../web/agent-scaffold.js')

const BEGIN = '<!-- BEGIN GENERATED: fleet-rules (auto-generated from store/fleet-rules.md, do not edit by hand) -->'
const LEGACY_BEGIN = '<!-- BEGIN GENERATED: fleet-rules (auto-generated from templates/fleet-rules.md, do not edit by hand) -->'
const END = '<!-- END GENERATED: fleet-rules -->'
const SRC = join(tmpRoot, 'store', 'fleet-rules.md')
const ROOT_MD = join(tmpRoot, 'CLAUDE.md')

const agentMd = (a: string) => join(tmpRoot, 'agents', a, 'CLAUDE.md')
const settingsPath = (a: string) => join(tmpRoot, 'agents', a, '.claude', 'settings.json')
const readMd = (a: string) => readFileSync(agentMd(a), 'utf-8')
const readSettings = (a: string) => JSON.parse(readFileSync(settingsPath(a), 'utf-8')) as Record<string, unknown>
const sha = (path: string) => createHash('sha256').update(readFileSync(path)).digest('hex')

function setup(agent: string, md: string, settings?: Record<string, unknown>) {
  mkdirSync(join(tmpRoot, 'agents', agent, '.claude'), { recursive: true })
  writeFileSync(agentMd(agent), md, 'utf-8')
  if (settings) writeFileSync(settingsPath(agent), JSON.stringify(settings, null, 2), 'utf-8')
  else rmSync(settingsPath(agent), { force: true })
}

const SAMPLE_RULES = [
  '## Kemény szabályok',
  'Rule one for {{AGENT_ID}}.',
  '```bash',
  'curl -s {{DASHBOARD_ORIGIN}}/api/kanban -H "Authorization: Bearer $(cat {{PROJECT_ROOT}}/store/.dashboard-token)"',
  "echo '$&' \"$'\"",
  '```',
  '',
].join('\n')

/** Write the rules file. `stamp`: the root it claims to be synced from ('current' = the root as it is now). */
function rules(text: string | null, stamp: 'current' | 'none' | string = 'current', root = tmpRoot, path = SRC) {
  mkdirSync(dirname(path), { recursive: true })
  if (text === null) { rmSync(path, { force: true }); return }
  const hex = stamp === 'current' ? sha(join(root, 'CLAUDE.md')) : stamp
  const lead = stamp === 'none'
    ? '<!-- maintainer notes: not a rule -->'
    : `<!-- maintainer notes: not a rule\n  synced-from-root-sha256=${hex}\n-->`
  writeFileSync(path, `${lead}\n\n${text}`, 'utf-8')
}

beforeEach(() => {
  optIn.clear()
  failWrites.clear()
  writeFileSync(ROOT_MD, '# Main agent root\n\nroot rule\n', 'utf-8')
  rules(SAMPLE_RULES)
})

describe('fleet-rules: rendering', () => {
  it('substitutes every placeholder and drops the maintainer comment with the stamp', () => {
    const body = buildFleetRulesBody('agent-b', SRC)!
    expect(body).toContain('Rule one for agent-b.')
    expect(body).toContain(`$(cat ${tmpRoot}/store/.dashboard-token)`)
    expect(body).toContain('http://localhost:3420/api/kanban')
    expect(body).not.toMatch(/\{\{[A-Z_]+\}\}/)
    expect(body).not.toContain('maintainer notes')
    expect(body).not.toContain('synced-from-root-sha256')
  })

  it('missing or empty rules file renders nothing', () => {
    rules(null)
    expect(buildFleetRulesBody('agent-b', SRC)).toBeNull()
    writeFileSync(SRC, '<!-- only a comment -->\n\n', 'utf-8')
    expect(buildFleetRulesBody('agent-b', SRC)).toBeNull()
  })

  it('a body carrying a GENERATED marker renders nothing (Viktor I3)', () => {
    for (const marker of [
      '<!-- BEGIN GENERATED: autonomy-wiring -->',
      '<!-- END GENERATED: fleet-auth -->',
    ]) {
      rules(`${SAMPLE_RULES}\n\n${marker}\n`)
      expect(buildFleetRulesBody('agent-b', SRC), marker).toBeNull()
    }
    // NEGATIVE CONTROL: an ordinary HTML comment in the rules text is fine.
    rules(`${SAMPLE_RULES}\n\n<!-- a note inside the rules -->\n`)
    expect(buildFleetRulesBody('agent-b', SRC)).not.toBeNull()
  })

  it('reads the stamp from the leading comment only', () => {
    expect(fleetRulesStamp(SRC)).toBe(rootClaudeMdSha256(tmpRoot))
    rules(SAMPLE_RULES, 'none')
    expect(fleetRulesStamp(SRC)).toBeNull()
    // A stamp-shaped line in the rules TEXT is not a stamp.
    writeFileSync(SRC, `<!-- notes -->\n\nsynced-from-root-sha256=${'a'.repeat(64)}\n`, 'utf-8')
    expect(fleetRulesStamp(SRC)).toBeNull()
  })
})

describe('fleet-rules: opt-in writes the block, then the exclusion', () => {
  it('writes block + claudeMdExcludes, keeping other settings and other excludes', () => {
    optIn.set('agent-b', true)
    setup('agent-b', '# Agent B\n\nown text\n', { permissions: { deny: ['X'] }, claudeMdExcludes: ['/elsewhere/CLAUDE.md'] })
    ensureFleetRulesSection('agent-b', SRC)
    const md = readMd('agent-b')
    expect(md).toContain('own text')
    expect(md).toContain(BEGIN)
    expect(md).toContain(END)
    expect(md).toContain('Rule one for agent-b.')
    // `$&` / `$'` in the rules text must survive verbatim (no replace patterns).
    expect(md).toContain("echo '$&' \"$'\"")
    const s = readSettings('agent-b')
    expect(s.permissions).toEqual({ deny: ['X'] })
    expect(s.claudeMdExcludes).toEqual(['/elsewhere/CLAUDE.md', ...rootClaudeMdExcludePaths()])
    expect(rootClaudeMdExcludePaths()).toContain(ROOT_MD)
  })

  it('is idempotent: a second run changes neither file', () => {
    optIn.set('agent-b', true)
    setup('agent-b', '# Agent B\n', {})
    ensureFleetRulesSection('agent-b', SRC)
    const md1 = readMd('agent-b'); const s1 = readFileSync(settingsPath('agent-b'), 'utf-8')
    ensureFleetRulesSection('agent-b', SRC)
    expect(readMd('agent-b')).toBe(md1)
    expect(readFileSync(settingsPath('agent-b'), 'utf-8')).toBe(s1)
    expect(md1.split(BEGIN).length - 1).toBe(1)
  })

  it('a rules edit replaces the block in place, never appends a second one', () => {
    optIn.set('agent-b', true)
    setup('agent-b', '# Agent B\n\nbefore\n', {})
    ensureFleetRulesSection('agent-b', SRC)
    writeFileSync(agentMd('agent-b'), readMd('agent-b') + '\nafter\n', 'utf-8')
    rules('## Kemény szabályok\nRule TWO for {{AGENT_ID}}.\n')
    ensureFleetRulesSection('agent-b', SRC)
    const md = readMd('agent-b')
    expect(md.split(BEGIN).length - 1).toBe(1)
    expect(md).toContain('Rule TWO for agent-b.')
    expect(md).not.toContain('Rule one')
    expect(md).toContain('before')
    expect(md).toContain('after')
  })

  it('a block written with the earlier templates/ marker is replaced, not duplicated', () => {
    optIn.set('agent-b', true)
    setup('agent-b', `# Agent B\n\n${LEGACY_BEGIN}\nold pilot rules\n${END}\n`, {})
    ensureFleetRulesSection('agent-b', SRC)
    const md = readMd('agent-b')
    expect(md).not.toContain(LEGACY_BEGIN)
    expect(md).not.toContain('old pilot rules')
    expect(md.split(BEGIN).length - 1).toBe(1)
  })

  it('creates the settings file when the agent has none yet', () => {
    optIn.set('agent-b', true)
    setup('agent-b', '# Agent B\n')
    ensureFleetRulesSection('agent-b', SRC)
    expect(readSettings('agent-b').claudeMdExcludes).toEqual(rootClaudeMdExcludePaths())
  })
})

describe('fleet-rules: no block, no exclusion', () => {
  it('not opted in: nothing is written', () => {
    setup('agent-b', '# Agent B\n', { permissions: {} })
    ensureFleetRulesSection('agent-b', SRC)
    expect(readMd('agent-b')).toBe('# Agent B\n')
    expect(readSettings('agent-b').claudeMdExcludes).toBeUndefined()
  })

  it('opted in but the rules file is missing: the root stays loaded', () => {
    optIn.set('agent-b', true)
    rules(null)
    setup('agent-b', '# Agent B\n', {})
    ensureFleetRulesSection('agent-b', SRC)
    expect(readMd('agent-b')).not.toContain(BEGIN)
    expect(readSettings('agent-b').claudeMdExcludes).toBeUndefined()
  })

  it('opting out removes the block and our exclusion, keeps the rest', () => {
    optIn.set('agent-b', true)
    setup('agent-b', '# Agent B\n\nown text\n', { claudeMdExcludes: ['/elsewhere/CLAUDE.md'] })
    ensureFleetRulesSection('agent-b', SRC)
    optIn.set('agent-b', false)
    ensureFleetRulesSection('agent-b', SRC)
    const md = readMd('agent-b')
    expect(md).not.toContain(BEGIN)
    expect(md).not.toContain('Rule one')
    expect(md).toContain('own text')
    expect(readSettings('agent-b').claudeMdExcludes).toEqual(['/elsewhere/CLAUDE.md'])
  })

  it('opting out with no other excludes drops the key entirely', () => {
    optIn.set('agent-b', true)
    setup('agent-b', '# Agent B\n', { model: 'x' })
    ensureFleetRulesSection('agent-b', SRC)
    optIn.set('agent-b', false)
    ensureFleetRulesSection('agent-b', SRC)
    const s = readSettings('agent-b')
    expect('claudeMdExcludes' in s).toBe(false)
    expect(s.model).toBe('x')
  })

  it('the rules file disappearing later puts the root load back', () => {
    optIn.set('agent-b', true)
    setup('agent-b', '# Agent B\n', {})
    ensureFleetRulesSection('agent-b', SRC)
    rules(null)
    ensureFleetRulesSection('agent-b', SRC)
    expect(readMd('agent-b')).not.toContain(BEGIN)
    expect(readSettings('agent-b').claudeMdExcludes).toBeUndefined()
  })

  it('an unparseable settings file is left alone', () => {
    optIn.set('agent-b', true)
    setup('agent-b', '# Agent B\n')
    writeFileSync(settingsPath('agent-b'), '{ not json', 'utf-8')
    ensureFleetRulesSection('agent-b', SRC)
    expect(readFileSync(settingsPath('agent-b'), 'utf-8')).toBe('{ not json')
  })

  it('never touches the main agent', () => {
    optIn.set('agent-a', true)
    setup('agent-a', '# A\n', {})
    ensureFleetRulesSection('agent-a', SRC)
    expect(readFileSync(ROOT_MD, 'utf-8')).toBe('# Main agent root\n\nroot rule\n')
    expect(readMd('agent-a')).toBe('# A\n')
    expect(readSettings('agent-a').claudeMdExcludes).toBeUndefined()
  })
})

describe('fleet-rules: drift gate (Viktor F2)', () => {
  it('rules without a stamp: no block, no exclusion', () => {
    optIn.set('agent-b', true)
    rules(SAMPLE_RULES, 'none')
    setup('agent-b', '# Agent B\n', {})
    ensureFleetRulesSection('agent-b', SRC)
    expect(readMd('agent-b')).not.toContain(BEGIN)
    expect(readSettings('agent-b').claudeMdExcludes).toBeUndefined()
  })

  it('a root edit after the stamp puts the root load back until re-stamped', () => {
    optIn.set('agent-b', true)
    setup('agent-b', '# Agent B\n', {})
    ensureFleetRulesSection('agent-b', SRC)
    expect(readMd('agent-b')).toContain(BEGIN)

    writeFileSync(ROOT_MD, '# Main agent root\n\nroot rule\n\nA NEW RULE for everyone\n', 'utf-8')
    ensureFleetRulesSection('agent-b', SRC)
    expect(readMd('agent-b')).not.toContain(BEGIN)
    expect(readSettings('agent-b').claudeMdExcludes).toBeUndefined()

    rules(SAMPLE_RULES + '\nA NEW RULE for everyone\n')  // re-synced and re-stamped
    ensureFleetRulesSection('agent-b', SRC)
    expect(readMd('agent-b')).toContain('A NEW RULE for everyone')
    expect(readSettings('agent-b').claudeMdExcludes).toEqual(rootClaudeMdExcludePaths())
  })

  it('a missing root CLAUDE.md is not a match', () => {
    optIn.set('agent-b', true)
    setup('agent-b', '# Agent B\n', {})
    rmSync(ROOT_MD)
    ensureFleetRulesSection('agent-b', SRC)
    expect(readMd('agent-b')).not.toContain(BEGIN)
    expect(readSettings('agent-b').claudeMdExcludes).toBeUndefined()
  })
})

describe('fleet-rules: order in both directions (Viktor L1)', () => {
  it('putting it in: a failed CLAUDE.md write leaves the exclusion out', () => {
    optIn.set('agent-b', true)
    setup('agent-b', '# Agent B\n', {})
    failWrites.add(agentMd('agent-b'))
    ensureFleetRulesSection('agent-b', SRC)
    expect(readSettings('agent-b').claudeMdExcludes).toBeUndefined()
  })

  it('taking it out: a failed settings write keeps the block', () => {
    optIn.set('agent-b', true)
    setup('agent-b', '# Agent B\n', {})
    ensureFleetRulesSection('agent-b', SRC)
    optIn.set('agent-b', false)
    failWrites.add(settingsPath('agent-b'))
    ensureFleetRulesSection('agent-b', SRC)
    // The exclusion is still in place, so the block must be too.
    expect(readSettings('agent-b').claudeMdExcludes).toEqual(rootClaudeMdExcludePaths())
    expect(readMd('agent-b')).toContain(BEGIN)
  })

  it('taking it out: an unparseable settings file keeps the block', () => {
    optIn.set('agent-b', true)
    setup('agent-b', '# Agent B\n', {})
    ensureFleetRulesSection('agent-b', SRC)
    optIn.set('agent-b', false)
    writeFileSync(settingsPath('agent-b'), '{ not json', 'utf-8')
    ensureFleetRulesSection('agent-b', SRC)
    expect(readMd('agent-b')).toContain(BEGIN)
  })
})

describe('fleet-rules: root spellings (Viktor L2)', () => {
  it('a glob-shaped root path: no block, no exclusion', () => {
    const globRoot = join(tmpRoot, 'inst[1]')
    mkdirSync(globRoot, { recursive: true })
    writeFileSync(join(globRoot, 'CLAUDE.md'), '# glob root\n', 'utf-8')
    rules(SAMPLE_RULES, 'current', globRoot)
    optIn.set('agent-b', true)
    setup('agent-b', '# Agent B\n', {})
    ensureFleetRulesSection('agent-b', SRC, globRoot)
    expect(readMd('agent-b')).not.toContain(BEGIN)
    expect(readSettings('agent-b').claudeMdExcludes).toBeUndefined()
  })

  it('a symlinked root: both the configured and the resolved path are excluded', () => {
    const realRoot = join(tmpRoot, 'real-install')
    const linkRoot = join(tmpRoot, 'link-install')
    mkdirSync(realRoot, { recursive: true })
    writeFileSync(join(realRoot, 'CLAUDE.md'), '# real root\n', 'utf-8')
    rmSync(linkRoot, { force: true })
    symlinkSync(realRoot, linkRoot)
    rules(SAMPLE_RULES, 'current', linkRoot)
    optIn.set('agent-b', true)
    setup('agent-b', '# Agent B\n', {})
    ensureFleetRulesSection('agent-b', SRC, linkRoot)
    expect(readSettings('agent-b').claudeMdExcludes).toEqual([
      join(linkRoot, 'CLAUDE.md'), join(realRoot, 'CLAUDE.md'),
    ])
    expect(readMd('agent-b')).toContain(BEGIN)
  })
})

describe('fleet-rules: what the repo ships (Viktor F1) and the wiring', () => {
  const here = dirname(fileURLToPath(import.meta.url))
  const repo = join(here, '..', '..')
  const live = (rel: string) => readFileSync(join(here, '..', rel), 'utf-8')
    .split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')

  it('no rules file in a versioned path; the real one lives under the gitignored store/', () => {
    expect(existsSync(join(repo, 'templates', 'fleet-rules.md'))).toBe(false)
    expect(readFileSync(join(repo, '.gitignore'), 'utf-8')).toMatch(/^store\/$/m)
    expect(live('web/agent-scaffold.ts')).toMatch(/FLEETRULES_SOURCE = join\(STORE_DIR, 'fleet-rules\.md'\)/)
  })

  it('the shipped example renders and carries no install-specific content', () => {
    const example = join(repo, 'templates', 'fleet-rules.example.md')
    const text = readFileSync(example, 'utf-8')
    const body = buildFleetRulesBody('agent-b', example)!
    expect(body).toContain('agent-b')
    expect(body).not.toMatch(/\{\{[A-Z_]+\}\}/)
    // The example's stamp hint must never parse as a stamp.
    expect(fleetRulesStamp(example)).toBeNull()
    // Content-free by shape, not by a list of forbidden words: a word list here
    // would itself put the install's names into a versioned file.
    expect(body.split('\n').filter((l) => l.trim()).length).toBeLessThanOrEqual(3)
    expect(body.match(/^#+ /gm)).toEqual(['## '])
    expect(body).toContain('## Example section')
    expect(text).not.toMatch(/token|secret|password|api[_-]?key/i)
  })

  it('agent-process.ts ensures it on every agent start, after the profile settings write', () => {
    const src = live('web/agent-process.ts')
    const write = src.search(/^\s*writeAgentSettingsFromProfile\(name, profile\)/m)
    const ensure = src.search(/^\s*ensureFleetRulesSection\(name\)/m)
    expect(write).toBeGreaterThan(-1)
    expect(ensure).toBeGreaterThan(write)
  })
})

describe('scripts/fleet-rules-stamp.mjs', () => {
  const here = dirname(fileURLToPath(import.meta.url))
  const script = join(here, '..', '..', 'scripts', 'fleet-rules-stamp.mjs')

  it('stamps, checks, detects a root edit, and re-stamps in place', () => {
    const inst = mkdtempSync(join(tmpRoot, 'stamp-'))
    const file = join(inst, 'store', 'fleet-rules.md')
    mkdirSync(dirname(file), { recursive: true })
    writeFileSync(join(inst, 'CLAUDE.md'), '# root v1\n', 'utf-8')
    writeFileSync(file, '<!--\n  notes\n-->\n\n## Rules\nx\n', 'utf-8')
    const check = () => spawnSync(process.execPath, [script, '--check', '--root', inst], { encoding: 'utf-8' })

    expect(check().status).toBe(1)
    execFileSync(process.execPath, [script, '--root', inst])
    expect(check().status).toBe(0)
    expect(fleetRulesStamp(file)).toBe(sha(join(inst, 'CLAUDE.md')))
    expect(readFileSync(file, 'utf-8')).toContain('## Rules\nx')
    expect(readFileSync(join(inst, 'store', 'fleet-rules.root-at-stamp.md'), 'utf-8')).toBe('# root v1\n')

    writeFileSync(join(inst, 'CLAUDE.md'), '# root v2\n', 'utf-8')
    const stale = check()
    expect(stale.status).toBe(1)
    expect(stale.stdout).toContain('fleet-rules.root-at-stamp.md')

    execFileSync(process.execPath, [script, '--root', inst])
    expect(check().status).toBe(0)
    expect(readFileSync(file, 'utf-8').match(/synced-from-root-sha256=/g)?.length).toBe(1)
  })
})
