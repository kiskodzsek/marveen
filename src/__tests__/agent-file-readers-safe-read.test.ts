// Card e32fdc02 (Viktor 43048, the follow-up of e6e294a7 / #318):
// LELET 2: the remaining raw readers of agent-writable files -- schedule-runner resolveBoundChannel (access.json; a FIFO
// there blocked the scheduler, measured by Viktor), routes/overview readAgentOauthTokenFilePath (agent-config.json),
// context-restart-gate-runner getMcpJsonPatterns (.mcp.json), plus routes/onboarding paired() (the main agent's
// access.json) -- read through readRegularFileSync.
// LOW 3: readFileOr logs a refusal (once per path), and startAgentProcess does not start an agent whose
// agent-config.json is a FIFO, a device or over the cap (fail closed), and the scheduler does not retry that every tick.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { execFileSync, spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const { warn } = vi.hoisted(() => ({ warn: vi.fn() }))
vi.mock('../logger.js', () => ({
  logger: { warn, info: vi.fn(), error: vi.fn(), debug: vi.fn(), child: () => ({ warn, info: vi.fn(), error: vi.fn(), debug: vi.fn() }) },
  PRETTY_OPTIONS: {},
}))

import { AGENTS_BASE_DIR, readFileOr } from '../web/agent-config.js'
import { isConfigStartRefusal } from '../web/schedule-runner.js'

const here = dirname(fileURLToPath(import.meta.url))
const src = join(here, '..')
const web = join(src, 'web')
const unix = process.platform !== 'win32'

// The same child-process harness as readfileor-safe-read.test.ts: a regression blocks the synchronous read and the
// process with it, so the read runs in a child with a timeout, and "start <step>" on stderr names the step that hung.
function inChild(body: string, args: string[], env: Record<string, string> = {}, timeoutMs = 30000) {
  const tmp = mkdtempSync(join(tmpdir(), 'afr-child-'))
  const file = join(tmp, 'child.mjs')
  writeFileSync(file, body)
  const r = spawnSync(process.execPath, ['--import', 'tsx', file, ...args], {
    encoding: 'utf-8', timeout: timeoutMs, env: { ...process.env, ...env },
  })
  rmSync(tmp, { recursive: true, force: true })
  const blockedAt = (r.stderr.match(/^start \S+$/gm) ?? []).pop()
  const line = r.stdout.split('\n').find((l) => l.startsWith('RESULT ')) ?? 'RESULT null'
  let out: Record<string, unknown> | null = null
  try { out = JSON.parse(line.slice(7)) } catch { /* keep null */ }
  return { out, blockedAt, signal: r.signal, stderr: r.stderr }
}

describe('agent-writable file readers outside the scaffold refuse a FIFO (LELET 2)', () => {
  let dir = ''
  beforeEach(() => { dir = mkdtempSync(join(tmpdir(), 'afr-')) })
  afterEach(() => { rmSync(dir, { recursive: true, force: true }) })

  it.skipIf(!unix)('resolveBoundChannel returns at once (no chat id) when access.json is a FIFO, and reads a regular one', () => {
    // A throwaway agent folder under AGENTS_BASE_DIR (PROJECT_ROOT is file-relative: the checkout running the test,
    // never another install), removed in the finally. The access.json path is built the way the function builds it.
    const body = `
      const sr = await import(${JSON.stringify(join(web, 'schedule-runner.ts'))})
      const cfg = await import(${JSON.stringify(join(web, 'agent-config.ts'))})
      const cp = await import(${JSON.stringify(join(src, 'channel-provider.ts'))})
      const fs = await import('node:fs')
      const path = await import('node:path')
      const cpx = await import('node:child_process')
      const [name] = process.argv.slice(2)
      const stateDir = cp.channelStateDir('telegram', cfg.agentDir(name))
      fs.mkdirSync(stateDir, { recursive: true })
      const access = path.join(stateDir, 'access.json')
      const out = {}
      try {
        fs.writeFileSync(access, JSON.stringify({ allowFrom: ['12345'] }))
        process.stderr.write('start regular\\n'); out.regular = sr.resolveBoundChannel(name, 'telegram').chatId
        fs.rmSync(access); cpx.execFileSync('mkfifo', [access])
        process.stderr.write('start fifo\\n'); out.fifo = sr.resolveBoundChannel(name, 'telegram').chatId
      } finally { fs.rmSync(cfg.agentDir(name), { recursive: true, force: true }) }
      process.stdout.write('\\nRESULT ' + JSON.stringify(out) + '\\n'); process.exit(0)
    `
    const name = `zz-afr-${process.pid}-${Date.now()}`
    const r = inChild(body, [name])
    // A child killed by the timeout never reaches its finally: clean up from here too.
    rmSync(join(AGENTS_BASE_DIR, name), { recursive: true, force: true })
    expect(r.signal, `blocked at: ${r.blockedAt}`).toBeNull()
    expect(r.out).toEqual({ regular: '12345', fifo: null })
  })

  it.skipIf(!unix)('agentConfigRefusal names a FIFO / over-cap agent-config.json and is null for a regular or missing one (LOW 3)', () => {
    const body = `
      const cfg = await import(${JSON.stringify(join(web, 'agent-config.ts'))})
      const fs = await import('node:fs')
      const path = await import('node:path')
      const cpx = await import('node:child_process')
      const [name] = process.argv.slice(2)
      const d = cfg.agentDir(name)
      fs.mkdirSync(d, { recursive: true })
      const out = {}
      try {
        cpx.execFileSync('mkfifo', [path.join(d, 'agent-config.json')])
        process.stderr.write('start refusal\\n'); out.refusal = cfg.agentConfigRefusal(name)
        fs.rmSync(path.join(d, 'agent-config.json'))
        fs.writeFileSync(path.join(d, 'agent-config.json'), '{}')
        out.regular = cfg.agentConfigRefusal(name)
        fs.rmSync(path.join(d, 'agent-config.json'))
        out.missing = cfg.agentConfigRefusal(name)
        fs.writeFileSync(path.join(d, 'agent-config.json'), '{"x":"' + 'y'.repeat(1_100_000) + '"}')
        out.overCap = typeof cfg.agentConfigRefusal(name)
      } finally { fs.rmSync(d, { recursive: true, force: true }) }
      process.stdout.write('\\nRESULT ' + JSON.stringify(out) + '\\n'); process.exit(0)
    `
    const name = `zz-afr-${process.pid}-${Date.now()}`
    const r = inChild(body, [name])
    // A child killed by the timeout never reaches its finally: clean up from here too.
    rmSync(join(AGENTS_BASE_DIR, name), { recursive: true, force: true })
    expect(r.signal, `blocked at: ${r.blockedAt}`).toBeNull()
    expect(String(r.out?.refusal)).toMatch(/^not a regular file: /)
    expect(r.out?.regular).toBeNull()
    expect(r.out?.missing).toBeNull()
    expect(r.out?.overCap).toBe('string')
  })

  it.skipIf(!unix)('readFileOr warns on a refused file once per path, and stays quiet on a missing one (LOW 3)', () => {
    const fifo = join(dir, 'fifo')
    execFileSync('mkfifo', [fifo])
    warn.mockClear()
    expect(readFileOr(fifo, 'FB')).toBe('FB')
    expect(readFileOr(fifo, 'FB')).toBe('FB')
    expect(readFileOr(join(dir, 'missing'), 'FB')).toBe('FB')
    const refusals = warn.mock.calls.filter((c) => String(c[1]).startsWith('readFileOr: refused'))
    expect(refusals).toHaveLength(1)
    expect(refusals[0][0]).toMatchObject({ path: fifo })
  })
})

describe('the scheduler treats the unsafe agent-config.json refusal as a config refusal (no retry loop)', () => {
  it('classifies it as refused; ordinary start failures stay missing', () => {
    expect(isConfigStartRefusal('agent-config.json: unsafe-file (not a regular file: /x/agent-config.json)')).toBe(true)
    expect(isConfigStartRefusal('agent-config.json: unsafe-file (over 1000000 bytes: /x/agent-config.json)')).toBe(true)
    expect(isConfigStartRefusal('Agent not found')).toBe(false)
    expect(isConfigStartRefusal('agent-config.json: something else')).toBe(false)
    expect(isConfigStartRefusal('oauthTokenFile: missing')).toBe(false)
    expect(isConfigStartRefusal('oauthTokenFile: non-claude-model')).toBe(true)
  })
})

describe('source pin: no raw readFileSync of an agent-derived path in src/ (LELET 2 pin)', () => {
  // A single-line pin: a readFileSync( whose argument text names agentDir(, channelStateDir(, AGENTS_BASE_DIR or
  // agentWorkingDir(. A path first stored in a variable is not seen here; those readers are pinned by name below.
  function tsFiles(d: string): string[] {
    const out: string[] = []
    for (const e of readdirSync(d)) {
      const p = join(d, e)
      if (e === '__tests__' || e === 'node_modules') continue
      if (statSync(p).isDirectory()) out.push(...tsFiles(p))
      else if (e.endsWith('.ts')) out.push(p)
    }
    return out
  }

  it('finds none', () => {
    const rx = /readFileSync\([^)]*(agentDir\(|channelStateDir\(|AGENTS_BASE_DIR|agentWorkingDir\()/
    const hits: string[] = []
    for (const f of tsFiles(src)) {
      readFileSync(f, 'utf-8').split('\n').forEach((l, i) => { if (rx.test(l)) hits.push(`${f.slice(src.length + 1)}:${i + 1}`) })
    }
    expect(hits).toEqual([])
  })

  it('the named readers go through readRegularFileSync', () => {
    const body = (file: string, fn: string): string => {
      const s = readFileSync(join(web, file), 'utf-8')
      const i = s.indexOf(`function ${fn}(`)
      expect(i, `${file}: ${fn} not found`).toBeGreaterThan(-1)
      return s.slice(i, s.indexOf('\n}\n', i))
    }
    for (const [file, fn] of [
      ['schedule-runner.ts', 'resolveBoundChannel'],
      ['routes/overview.ts', 'readAgentOauthTokenFilePath'],
      ['context-restart-gate-runner.ts', 'getMcpJsonPatterns'],
      ['routes/onboarding.ts', 'paired'],
      ['federation/capabilities.ts', 'readSummarySource'],
    ] as const) {
      const b = body(file, fn)
      expect(b, `${file} ${fn}`).toContain('readRegularFileSync(')
      expect(b, `${file} ${fn}`).not.toMatch(/\breadFileSync\(/)
    }
  })

  // startAgentProcess itself is not called here: if the guard regressed, the call would go on and launch a real
  // session. So the launcher is pinned by source: the refusal comes before the first config read, returns, and its
  // error string is exactly the one isConfigStartRefusal classifies (tested above).
  it('startAgentProcess refuses on agentConfigRefusal before the first config read, with the classified error', () => {
    const s = readFileSync(join(web, 'agent-process.ts'), 'utf-8')
    const start = s.indexOf('export async function startAgentProcess(')
    const refusal = s.indexOf('const cfgRefusal = agentConfigRefusal(name)', start)
    const firstRead = s.indexOf('readAgentRemoteConfig(name)', start)
    expect(refusal).toBeGreaterThan(start)
    expect(refusal).toBeLessThan(firstRead)
    const guard = s.slice(refusal, firstRead)
    expect(guard).toContain('if (cfgRefusal !== null) {')
    expect(guard).toContain("return { ok: false, error: `agent-config.json: unsafe-file (${cfgRefusal})` }")
    expect(isConfigStartRefusal('agent-config.json: unsafe-file (not a regular file: /a/agent-config.json)')).toBe(true)
  })
})
