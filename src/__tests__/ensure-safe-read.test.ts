// Card b9daaaf5 (Viktor 42983 MEDIUM 2, follow-up of d4180ec8): the ensure* migrations read the sub-agent's own
// settings.json, CLAUDE.md and quarantine-reader copy synchronously on the dashboard's main thread. A FIFO in one of
// those places blocked the read (measured: ensureKeychainReadGate still blocked after 25 s), a symlink to /dev/zero
// would exhaust memory. readRegularFileSync refuses both on the open descriptor; every such reader goes through it.
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { execFileSync, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readRegularFileSync, UnsafeFileError, SAFE_READ_MAX_BYTES } from '../web/safe-read.js'
import { AGENTS_BASE_DIR } from '../web/agent-config.js'

const here = dirname(fileURLToPath(import.meta.url))
const scaffoldSrc = join(here, '..', 'web', 'agent-scaffold.ts')
const unix = process.platform !== 'win32'

describe('readRegularFileSync', () => {
  let dir = ''
  beforeEach(() => { dir = mkdtempSync(join(tmpdir(), 'safe-read-')) })
  afterEach(() => { rmSync(dir, { recursive: true, force: true }) })

  it('returns what readFileSync(path, "utf-8") returns: BOM kept, multi-byte text across the 64 KiB chunk edge', () => {
    const p = join(dir, 'a.json')
    const text = '﻿{"k": "' + 'á'.repeat(70_000) + 'ő€"}\n'
    writeFileSync(p, text)
    expect(readRegularFileSync(p)).toBe(readFileSync(p, 'utf-8'))
    writeFileSync(p, '')
    expect(readRegularFileSync(p)).toBe('')
  })

  it('a missing file throws ENOENT, as readFileSync does (callers keep their catch)', () => {
    expect(() => readRegularFileSync(join(dir, 'none'))).toThrow(expect.objectContaining({ code: 'ENOENT' }))
  })

  it('a directory is refused', () => {
    expect(() => readRegularFileSync(dir)).toThrow(UnsafeFileError)
  })

  it('over the limit is refused; exactly the limit is read', () => {
    const p = join(dir, 'big')
    writeFileSync(p, 'x'.repeat(101))
    expect(() => readRegularFileSync(p, 100)).toThrow(UnsafeFileError)
    writeFileSync(p, 'x'.repeat(100))
    expect(readRegularFileSync(p, 100)).toBe('x'.repeat(100))
    expect(SAFE_READ_MAX_BYTES).toBe(1_000_000)
  })

  it('a symlink to a regular file is followed (as readFileSync does)', () => {
    const p = join(dir, 'real.json')
    writeFileSync(p, '{}')
    symlinkSync(p, join(dir, 'link.json'))
    expect(readRegularFileSync(join(dir, 'link.json'))).toBe('{}')
  })

  // In a child process with a timeout: a regression would block the synchronous read, and with it the test worker.
  it.skipIf(!unix)('a FIFO and a symlink to /dev/zero are refused at once, without blocking', () => {
    execFileSync('mkfifo', [join(dir, 'fifo')])
    symlinkSync('/dev/zero', join(dir, 'zero'))
    const mod = join(here, '..', 'web', 'safe-read.ts')
    const t0 = Date.now()
    const r = spawnSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e',
      `import { readRegularFileSync } from ${JSON.stringify(mod)}; const out = {}; ` +
      `for (const p of process.argv.slice(1)) { try { readRegularFileSync(p); out[p] = 'read' } catch (e) { out[p] = e.name } } ` +
      `process.stdout.write(JSON.stringify(out))`, join(dir, 'fifo'), join(dir, 'zero')],
    { encoding: 'utf-8', timeout: 20000 })
    expect(r.signal).toBeNull()
    expect(JSON.parse(r.stdout.trim().split('\n').pop() ?? 'null')).toEqual({
      [join(dir, 'fifo')]: 'UnsafeFileError',
      [join(dir, 'zero')]: 'UnsafeFileError',
    })
    expect(Date.now() - t0).toBeLessThan(15000)
  })
})

// Every ensure* reader of a sub-agent's settings.json or CLAUDE.md, and the quarantine-reader check, with a FIFO in
// place of the file it reads. Each call gets a fresh FIFO (an "overwrite" reader replaces it with a regular file).
// The child prints "start <fn>" to stderr before each call, so a timeout names the reader that blocked.
const TEST_AGENT = 'ensure-safe-read-probe'
const root = join(AGENTS_BASE_DIR, TEST_AGENT)
const MARKER = join(root, '.ensure-safe-read-probe')

function cleanup(): void {
  if (!existsSync(root)) return
  // Only the throwaway directory this test created (it carries the marker); never a live agent folder.
  if (!existsSync(MARKER)) throw new Error(`refusing: ${root} has no test marker, not a test checkout`)
  rmSync(root, { recursive: true, force: true })
}

const READERS = [
  'ensureAgentHooks', 'ensureAgentStalenessHook', 'ensureAgentProvenanceHook', 'ensureBashEgressDeny',
  'ensureTelegramCopyGate', 'ensureEgressGate', 'ensureBashEgressParser', 'ensureImageQuarantineGate',
  'ensureKeychainReadGate', 'ensureProdTreeWriteGate', 'ensureRevocationNote', 'ensureGovernanceGateCommands',
  'ensureEvidenceSection', 'ensureMcpListChannelSection', 'ensureMessageCloseSection', 'ensureAutonomySection',
  'ensureFleetRosterSection', 'ensureProjectRootInClaudeMd', 'ensureSkillsPathTrapSection',
  'ensureSystemDirectiveAuthSection', 'ensureAgentIdHeaderSection', 'ensureThinChiefHandoffSection',
  'ensureMemorySearchLabelSection', 'ensureFleetAuthSection', 'ensureFleetRulesSection', 'ensureQuarantineReader',
]

describe('the ensure* readers with a FIFO in place of the agent\'s file', () => {
  beforeEach(() => {
    cleanup()
    mkdirSync(join(root, '.claude', 'agents'), { recursive: true })
    writeFileSync(MARKER, '')
  })
  afterEach(cleanup)

  it.skipIf(!unix)('every reader returns at once; none blocks the (single-threaded) dashboard', () => {
    const settings = join(root, '.claude', 'settings.json')
    const claudeMd = join(root, 'CLAUDE.md')
    const qr = join(root, '.claude', 'agents', 'quarantine-reader.md')
    const child = `
      import * as s from ${JSON.stringify(scaffoldSrc)}
      import { execFileSync } from 'node:child_process'
      import { rmSync } from 'node:fs'
      const [agent, ...paths] = process.argv.slice(1)
      const out = {}
      for (const fn of ${JSON.stringify(READERS)}) {
        for (const p of paths) { rmSync(p, { force: true }); execFileSync('mkfifo', [p]) }
        process.stderr.write('start ' + fn + '\\n')
        const t0 = Date.now()
        try { s[fn](agent) } catch (e) { out[fn + ':threw'] = String(e && e.message) }
        out[fn] = Date.now() - t0
      }
      process.stdout.write(JSON.stringify(out))
    `
    const r = spawnSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', child,
      TEST_AGENT, settings, claudeMd, qr], { encoding: 'utf-8', timeout: 60000 })
    const started = (r.stderr.match(/^start \S+$/gm) ?? []).pop()
    expect(r.signal, `blocked at: ${started}`).toBeNull()
    const out = JSON.parse(r.stdout.trim().split('\n').pop() ?? 'null') as Record<string, number | string>
    for (const fn of READERS) {
      expect(typeof out[fn], fn).toBe('number')
      expect(out[fn] as number, fn).toBeLessThan(5000)
      expect(out[fn + ':threw'], fn).toBeUndefined()
    }
    // The quarantine-reader copy stood as a FIFO: it was replaced by the rendered file (atomic rename), not written
    // through, which would have blocked waiting for a reader.
    expect(readFileSync(qr, 'utf-8')).toMatch(/quarantine/i)
  })
})

// Pin: no ensure* reader of an agent-writable path goes back to a plain readFileSync. The four names are the ones the
// scaffold uses for the agent's settings.json (settingsPath, projectScope), its CLAUDE.md and the reader copy.
describe('source pin', () => {
  it('agent-scaffold.ts reads settingsPath / projectScope / claudeMdPath / destPath only through readRegularFileSync', () => {
    const src = readFileSync(scaffoldSrc, 'utf-8')
    expect(src.match(/readFileSync\((settingsPath|projectScope|claudeMdPath|destPath)\b/g) ?? []).toEqual([])
    expect((src.match(/readRegularFileSync\((settingsPath|projectScope|claudeMdPath|destPath)\)/g) ?? []).length).toBe(31)
    // A write to the reader copy goes through the atomic rename, never a plain write that a FIFO would block.
    expect(src).not.toMatch(/[^c]writeFileSync\(destPath\b/)
  })
})
