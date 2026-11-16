/**
 * The TTS directive goes into the agent's PROMPT, so it must not carry the
 * dashboard token's value: the prompt lands in the transcript and with the
 * model provider. The curl reads the token file itself, by absolute path.
 * And the agent's answer goes in on stdin through a quoted heredoc, so a
 * backtick or $(...) in it is text, not a command (Kernel 43594, Viktor 43599).
 *
 * The run tests execute the directive's bash block for real against a local
 * HTTP server and check what arrives.
 */
import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createServer, type Server } from 'node:http'
import { execFile } from 'node:child_process'
import type { AddressInfo } from 'node:net'

const ROOT = mkdtempSync(join(tmpdir(), 'voice-token-ref-'))
const STORE = join(ROOT, 'store')
const TOKEN_FILE = join(STORE, '.dashboard-token')
// A fake value, only ever used inside this temp store.
const FAKE_TOKEN = 'faketoken-0123456789abcdef-not-a-real-dashboard-token'

vi.mock('../config.js', async () => {
  const actual = await vi.importActual<typeof import('../config.js')>('../config.js')
  return { ...actual, PROJECT_ROOT: ROOT, STORE_DIR: STORE }
})

const { buildTtsDirective, TTS_HEREDOC_PREFIX } = await import('../web/voice-directive.js')

const OPTS = { chatId: '-100123', stateDir: '/tmp/st', voiceModel: 'eleven_v3' }

function bashBlock(directive: string): string {
  const m = /```bash\n([\s\S]*?)```/.exec(directive)
  if (!m) throw new Error('no bash block in the directive')
  return m[1]
}

// The heredoc terminator the block opens with (<<'...').
function heredocEnd(block: string): string {
  const m = /<<'([^']+)'/.exec(block)
  if (!m) throw new Error('no quoted heredoc in the block')
  return m[1]
}

interface Got { auth: string | undefined; body: string }

let server: Server
let port = 0
let last: Got | null = null

beforeAll(async () => {
  mkdirSync(STORE, { recursive: true })
  server = createServer((req, res) => {
    let body = ''
    req.on('data', (c) => { body += c })
    req.on('end', () => {
      last = { auth: req.headers.authorization, body }
      res.writeHead(200, { 'Content-Type': 'application/json' })
      res.end('{"ok":true}')
    })
  })
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', () => r()))
  port = (server.address() as AddressInfo).port
})

afterAll(async () => {
  await new Promise<void>((r) => server.close(() => r()))
  rmSync(ROOT, { recursive: true, force: true })
})

function run(shell: string, script: string, cwd: string): Promise<{ code: number; stderr: string }> {
  return new Promise((resolve) => {
    execFile(shell, ['-c', script], { cwd, timeout: 20_000 }, (err, _out, stderr) => {
      resolve({ code: err ? (typeof err.code === 'number' ? err.code : 1) : 0, stderr: String(stderr) })
    })
  })
}

describe('buildTtsDirective: no token value in the prompt', () => {
  it('names the token file by absolute path and does not contain its content', () => {
    writeFileSync(TOKEN_FILE, FAKE_TOKEN + '\n', { mode: 0o600 })
    const d = buildTtsDirective(OPTS)
    expect(d).not.toBeNull()
    expect(d).not.toContain(FAKE_TOKEN)
    expect(d).toContain(`Bearer $(cat '${TOKEN_FILE}')`)
    expect(TOKEN_FILE.startsWith('/')).toBe(true)
  })

  it('gives no directive when there is no token file', () => {
    rmSync(TOKEN_FILE, { force: true })
    expect(buildTtsDirective(OPTS)).toBeNull()
  })
})

const SHELLS = ['/bin/bash', '/bin/zsh'].filter((s) => existsSync(s))

describe.each(SHELLS)('buildTtsDirective: the block run by %s', (shell) => {
  it('sends the answer as text, the token from the file, the fields exactly', async () => {
    writeFileSync(TOKEN_FILE, FAKE_TOKEN + '\n', { mode: 0o600 })
    const canary = join(ROOT, `canary-${shell.replace(/\W/g, '')}`)
    const answer =
      `Szia! Itt egy \`touch ${canary}\` és $(touch ${canary}) meg "idézet" és 'aposztróf', ` +
      `egy \\ visszaper, $HOME és ${'$'}{PATH}.\nMásodik sor.`
    const odd = {
      chatId: `-100'7"`,
      stateDir: `/tmp/o'dd "dir" $HOME \\x`,
      voiceModel: `m'1 "$(touch ${canary})" \`touch ${canary}\``,
    }
    const d = buildTtsDirective(odd)!
    const script = bashBlock(d)
      .replace(`http://localhost:`, `http://127.0.0.1:`)
      .replace(/127\.0\.0\.1:\d+/, `127.0.0.1:${port}`)
      .replace('A_VÁLASZOD_SZÖVEGE', () => answer) // a function: no $-patterns in the replacement
    // A sub-agent's cwd is not the install root: run from elsewhere.
    const cwd = mkdtempSync(join(tmpdir(), 'voice-cwd-'))
    last = null
    const r = await run(shell, script, cwd)
    rmSync(cwd, { recursive: true, force: true })
    expect(r.code, r.stderr).toBe(0)
    expect(existsSync(canary)).toBe(false)
    expect(last).not.toBeNull()
    expect(last!.auth).toBe(`Bearer ${FAKE_TOKEN}`)
    expect(JSON.parse(last!.body)).toEqual({
      text: answer,
      chat_id: odd.chatId,
      state_dir: odd.stateDir,
      voice_model: odd.voiceModel,
    })
  })
})

it('the heredoc terminator is a line of its own after the answer placeholder', () => {
  writeFileSync(TOKEN_FILE, FAKE_TOKEN + '\n', { mode: 0o600 })
  const block = bashBlock(buildTtsDirective(OPTS)!)
  const end = heredocEnd(block)
  const lines = block.split('\n')
  expect(lines).toContain('A_VÁLASZOD_SZÖVEGE')
  expect(lines.indexOf(end)).toBe(lines.indexOf('A_VÁLASZOD_SZÖVEGE') + 1)
})

it('the terminator is the prefix plus a fresh random suffix on every call (Viktor 43605 INFO 1)', () => {
  writeFileSync(TOKEN_FILE, FAKE_TOKEN + '\n', { mode: 0o600 })
  const ends = Array.from({ length: 5 }, () => heredocEnd(bashBlock(buildTtsDirective(OPTS)!)))
  for (const e of ends) expect(e).toMatch(new RegExp(`^${TTS_HEREDOC_PREFIX}[0-9a-f]{24}$`))
  expect(new Set(ends).size).toBe(ends.length)
})

describe.each(SHELLS)('buildTtsDirective: an answer that carries a terminator line, run by %s', (shell) => {
  it('the bare prefix and another call\'s terminator stay text, nothing after them runs', async () => {
    writeFileSync(TOKEN_FILE, FAKE_TOKEN + '\n', { mode: 0o600 })
    const canary = join(ROOT, `canary-end-${shell.replace(/\W/g, '')}`)
    const otherEnd = heredocEnd(bashBlock(buildTtsDirective(OPTS)!))
    const answer = [
      'elso sor',
      TTS_HEREDOC_PREFIX,
      TTS_HEREDOC_PREFIX.replace(/_$/, ''),
      otherEnd,
      `touch ${canary}`,
      'harmadik',
    ].join('\n')
    const script = bashBlock(buildTtsDirective(OPTS)!)
      .replace(`http://localhost:`, `http://127.0.0.1:`)
      .replace(/127\.0\.0\.1:\d+/, `127.0.0.1:${port}`)
      .replace('A_VÁLASZOD_SZÖVEGE', () => answer)
    const cwd = mkdtempSync(join(tmpdir(), 'voice-cwd-'))
    last = null
    const r = await run(shell, script, cwd)
    rmSync(cwd, { recursive: true, force: true })
    expect(r.code, r.stderr).toBe(0)
    expect(existsSync(canary)).toBe(false)
    expect(JSON.parse(last!.body).text).toBe(answer)
  })
})
