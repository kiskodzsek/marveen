// Card e6e294a7 (Viktor 43021, the follow-up of b9daaaf5): the rest of the 42983 MEDIUM 2 class.
// MEDIUM 1: a FIFO in place of agents/<name>/agent-config.json blocked readAgentClaudeConfigDir (the launcher's call)
// through readFileOr; the agent-process.ts readers of the agent's .env, .mcp.json, settings and .claude.json are the
// same class. LOW 2: an ensure*Section that refuses an over-cap CLAUDE.md says so in the log. INFO: the source pin
// covers every read in the scaffold, not only four variable names.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { execFileSync, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const { warn } = vi.hoisted(() => ({ warn: vi.fn() }))
vi.mock('../logger.js', () => ({
  logger: { warn, info: vi.fn(), error: vi.fn(), debug: vi.fn(), child: () => ({ warn, info: vi.fn(), error: vi.fn(), debug: vi.fn() }) },
  PRETTY_OPTIONS: {},
}))

import { AGENTS_BASE_DIR, readFileOr } from '../web/agent-config.js'
import { ensureEvidenceSection } from '../web/agent-scaffold.js'

const here = dirname(fileURLToPath(import.meta.url))
const web = join(here, '..', 'web')
const unix = process.platform !== 'win32'

// Run `body` (an ES module snippet; the args are process.argv.slice(2)) in a child with a timeout: a regression blocks the
// synchronous read, and with it whatever process runs it. The snippet writes "start <step>" to stderr before each step.
function inChild(body: string, args: string[], timeoutMs = 30000): { out: unknown; blockedAt?: string; signal: string | null } {
  // A module FILE, not -e: agent-process.ts spawns helpers with the parent's execArgv, and an inherited
  // --input-type=module makes those fail (ERR_INPUT_TYPE_NOT_ALLOWED, measured).
  const tmp = mkdtempSync(join(tmpdir(), 'rfo-child-'))
  const file = join(tmp, 'child.mjs')
  writeFileSync(file, body)
  const r = spawnSync(process.execPath, ['--import', 'tsx', file, ...args], { encoding: 'utf-8', timeout: timeoutMs })
  rmSync(tmp, { recursive: true, force: true })
  const blockedAt = (r.stderr.match(/^start \S+$/gm) ?? []).pop()
  let out: unknown = null
  // The logger also writes to stdout: the result is the line after the RESULT marker.
  const line = r.stdout.split('\n').find((l) => l.startsWith('RESULT ')) ?? 'RESULT null'
  try { out = JSON.parse(line.slice(7)) } catch { /* keep null */ }
  return { out, blockedAt, signal: r.signal }
}

describe('readFileOr / readJsonObjectForWrite / agent-process readers: a FIFO or a device is not read', () => {
  let dir = ''
  beforeEach(() => { dir = mkdtempSync(join(tmpdir(), 'rfo-')) })
  afterEach(() => { rmSync(dir, { recursive: true, force: true }) })

  it('readFileOr keeps reading a regular file and falls back on a missing one', () => {
    writeFileSync(join(dir, 'a.json'), '{"x":1}')
    expect(readFileOr(join(dir, 'a.json'), '{}')).toBe('{"x":1}')
    expect(readFileOr(join(dir, 'none'), 'FB')).toBe('FB')
  })

  it('readFileOr falls back on a file over 1 MB (refused, not read)', () => {
    writeFileSync(join(dir, 'big'), 'x'.repeat(1_000_001))
    expect(readFileOr(join(dir, 'big'), 'FB')).toBe('FB')
  })

  it.skipIf(!unix)('each reader returns at once on a FIFO / a /dev/zero symlink', () => {
    const fifo = join(dir, 'fifo')
    execFileSync('mkfifo', [fifo])
    symlinkSync('/dev/zero', join(dir, 'zero'))
    const body = `
      const cfg = await import(${JSON.stringify(join(web, 'agent-config.ts'))})
      const proc = await import(${JSON.stringify(join(web, 'agent-process.ts'))})
      const [fifo, zero, projectDir] = process.argv.slice(2)
      const out = {}
      const step = (k, f) => { process.stderr.write('start ' + k + '\\n'); try { out[k] = f() } catch (e) { const m = String(e && e.message); out[k] = 'threw:' + (m.includes('cannot be read; refusing to overwrite') ? 'refused' : m) } }
      step('readFileOr-fifo', () => cfg.readFileOr(fifo, 'FB'))
      step('readFileOr-zero', () => cfg.readFileOr(zero, 'FB'))
      step('readJsonObjectForWrite-fifo', () => cfg.readJsonObjectForWrite(fifo))
      step('syncTeamsDisplayName-fifo', () => proc.syncTeamsDisplayName(fifo, 'Bot'))
      step('stampProjectTrustForDir-fifo', () => proc.stampProjectTrustForDir(fifo, projectDir))
      step('stampFableOverageConsent-fifo', () => proc.stampFableOverageConsent(fifo))
      step('ensureSharedClaudeOnboarded-fifo', () => proc.ensureSharedClaudeOnboarded(fifo))
      process.stdout.write('\\nRESULT ' + JSON.stringify(out) + '\\n'); process.exit(0)
    `
    const r = inChild(body, [fifo, join(dir, 'zero'), dir])
    expect(r.signal, `blocked at: ${r.blockedAt}`).toBeNull()
    expect(r.out).toEqual({
      'readFileOr-fifo': 'FB',
      'readFileOr-zero': 'FB',
      // refused loudly, never overwritten (JSONCLOBBER926 rule), and without blocking
      'readJsonObjectForWrite-fifo': 'threw:refused',
      'syncTeamsDisplayName-fifo': false,
      'stampProjectTrustForDir-fifo': false,
      'stampFableOverageConsent-fifo': false,
      'ensureSharedClaudeOnboarded-fifo': false,
    })
  })
})

// Viktor's repro: a FIFO at agents/<name>/agent-config.json and the launcher's readAgentClaudeConfigDir.
const TEST_AGENT = 'readfileor-safe-read-probe'
const root = join(AGENTS_BASE_DIR, TEST_AGENT)
const MARKER = join(root, '.readfileor-safe-read-probe')
function cleanup(): void {
  if (!existsSync(root)) return
  if (!existsSync(MARKER)) throw new Error(`refusing: ${root} has no test marker, not a test checkout`)
  rmSync(root, { recursive: true, force: true })
}

describe('agent folder files', () => {
  beforeEach(() => { cleanup(); mkdirSync(root, { recursive: true }); writeFileSync(MARKER, ''); warn.mockClear() })
  afterEach(cleanup)

  it.skipIf(!unix)('a FIFO agent-config.json: readAgentClaudeConfigDir returns at once (null, as for a missing file)', () => {
    execFileSync('mkfifo', [join(root, 'agent-config.json')])
    const body = `
      const cfg = await import(${JSON.stringify(join(web, 'agent-config.ts'))})
      process.stderr.write('start readAgentClaudeConfigDir\\n')
      process.stdout.write('\\nRESULT ' + JSON.stringify({ dir: cfg.readAgentClaudeConfigDir(process.argv[2]) }) + '\\n'); process.exit(0)
    `
    const r = inChild(body, [TEST_AGENT])
    expect(r.signal, `blocked at: ${r.blockedAt}`).toBeNull()
    expect(r.out).toEqual({ dir: null })
  })

  it('LOW 2: a CLAUDE.md over the cap is left as is AND logged with the agent name', () => {
    const md = join(root, 'CLAUDE.md')
    const big = '# x\n' + 'y'.repeat(1_100_000)
    writeFileSync(md, big)
    ensureEvidenceSection(TEST_AGENT)
    expect(readFileSync(md, 'utf-8')).toBe(big)
    expect(warn).toHaveBeenCalledWith(
      expect.objectContaining({ agent: TEST_AGENT, path: md }),
      expect.stringContaining('agent file refused'),
    )
  })

  it('a missing-or-ordinary skip is not logged as a refusal (no noise)', () => {
    writeFileSync(join(root, 'CLAUDE.md'), '# ok\n')
    ensureEvidenceSection(TEST_AGENT)
    expect(warn.mock.calls.filter((c) => String(c[1]).includes('agent file refused'))).toEqual([])
  })
})

// INFO: every readFileSync left in the scaffold is listed here by its argument; a new reader (any variable name) of an
// agent-writable file fails this pin until it is either routed through readRegularFileSync or added here on purpose.
describe('source pins', () => {
  const src = (f: string) => readFileSync(join(web, f), 'utf-8')
  const readArgs = (s: string) => [...s.matchAll(/\breadFileSync\(([^,)]+)/g)].map((m) => m[1].trim()).sort()

  it('agent-scaffold.ts: only owner-side files (templates, store/, repo task seeds, the root) are read raw', () => {
    expect(readArgs(src('agent-scaffold.ts'))).toEqual([
      "join(root",            // rootClaudeMdSha256: the production tree's CLAUDE.md
      "join(storeDir",        // egress allowlist (store/)
      "join(storeDir",
      "join(storeDir",
      "path",                 // public suffix list (vendored)
      "sharedMcp",            // the root .mcp.json, only when seeding a NEW agent
      "sourcePath",           // fleet-rules source (repo)
      "sourcePath",
      "srcFile",              // scheduled-task seeds (repo)
      "srcPath",
      "tplPath",              // templates (repo)
      "tplPath",
      "tplPath",
    ].sort())
  })

  it('agent-process.ts: no raw read of the agent\'s .env, .mcp.json, settings or .claude.json', () => {
    expect(src('agent-process.ts')).not.toMatch(/\breadFileSync\((envPath|ownSettingsPath|dotClaude|dotClaudePath|mcpJsonPath|settingsPath|join\(cwd, '\.mcp\.json'\))\b/)
  })

  it('agent-config.ts and scheduled-tasks-io.ts: readFileOr and readJsonObjectForWrite go through readRegularFileSync', () => {
    for (const f of ['agent-config.ts', 'scheduled-tasks-io.ts']) {
      const body = src(f).match(/function readFileOr\([^)]*\): string \{\n([^\n]*)\n/)?.[1] ?? ''
      expect(body, f).toContain('readRegularFileSync(path)')
    }
    const rj = src('agent-config.ts').match(/export function readJsonObjectForWrite[\s\S]*?\n}\n/)?.[0] ?? ''
    expect(rj).toContain('raw = readRegularFileSync(path)')
    expect(rj).not.toMatch(/readFileSync\(path/)
  })
})
