// APPROVALBOT1013 (Viktor 2384 M2): the approval bot's token is read in-process
// only. No route serves it, no binding takes it, no runtime resolver hands it
// out, and an MCP install cannot overwrite it with a generated id.
import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import { execFile } from 'node:child_process'
import { mkdtempSync, mkdirSync, copyFileSync, writeFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import type http from 'node:http'
import type { RouteContext } from '../web/routes/types.js'

const TOKEN_VALUE = '123456789:BOTTOKEN-fixture-do-not-serve-7d2e'
const OTHER_VALUE = 'other-secret-fixture'
const logSpy = { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() }
vi.mock('../logger.js', () => ({ logger: logSpy, PRETTY_OPTIONS: {} }))
const getSecretSpy = vi.fn((id: string) => (id === 'telegram-approval-bot' ? TOKEN_VALUE : id === 'other' ? OTHER_VALUE : null))
const setSecretSpy = vi.fn()
vi.mock('../web/vault.js', () => ({
  listSecrets: () => [{ id: 'telegram-approval-bot', label: 'bot', createdAt: '', updatedAt: '' }],
  setSecret: (...a: unknown[]) => setSecretSpy(...a),
  deleteSecret: () => false,
  getSecret: (id: string) => getSecretSpy(id),
  getSecretsForEnv: () => ({}),
}))
vi.mock('../env.js', () => ({ readEnvFile: () => ({}) }))

const { tryHandleConnectors, vaultAndBindEnvSecrets } = await import('../web/routes/connectors.js')

function mkRes() {
  const r = { statusCode: 200, body: '', headers: {} as Record<string, unknown>,
    writeHead(c: number, h?: Record<string, unknown>) { r.statusCode = c; Object.assign(r.headers, h ?? {}) },
    end(b?: string) { r.body = b ?? '' }, setHeader() {}, getHeader() { return undefined } }
  return r
}
async function call(method: string, path: string, body?: unknown) {
  const res = mkRes()
  const payload = body === undefined ? '' : JSON.stringify(body)
  const req: any = { headers: {}, method, url: path, on(ev: string, cb: (b?: Buffer) => void) { if (ev === 'data' && payload) cb(Buffer.from(payload)); if (ev === 'end') cb() } }
  const ctx = { req: req as http.IncomingMessage, res: res as unknown as http.ServerResponse, path, method, url: new URL(`http://127.0.0.1:3420${path}`), auth: { kind: 'token' } } as RouteContext
  await tryHandleConnectors(ctx)
  return res
}

describe('the vault routes never hand out the approval bot token', () => {
  it('GET /api/vault/telegram-approval-bot is 403, not decrypted, audited, value nowhere', async () => {
    getSecretSpy.mockClear()
    const res = await call('GET', '/api/vault/telegram-approval-bot')
    expect(res.statusCode).toBe(403)
    expect(res.body).not.toContain(TOKEN_VALUE)
    expect(getSecretSpy).not.toHaveBeenCalledWith('telegram-approval-bot')
    expect(JSON.stringify([...logSpy.info.mock.calls, ...logSpy.warn.mock.calls])).not.toContain(TOKEN_VALUE)
  })
  it('another secret is still served (the branch is exact)', async () => {
    const res = await call('GET', '/api/vault/other')
    expect(res.statusCode).toBe(200)
    expect(JSON.parse(res.body).value).toBe(OTHER_VALUE)
  })
  it('a binding to an env var or a header is refused', async () => {
    for (const b of [{ vaultSecretId: 'telegram-approval-bot', envVar: 'X', serverName: 's' }, { vaultSecretId: ' telegram-approval-bot ', headerName: 'Authorization', serverName: 's' }]) {
      const res = await call('POST', '/api/vault/bindings', b)
      expect(res.statusCode).toBe(400)
      expect(res.body).toContain('approval bot token')
    }
  })
  it('an MCP install cannot generate the reserved id and overwrite the token', () => {
    setSecretSpy.mockClear()
    expect(() => vaultAndBindEnvSecrets('telegram-approval', '/tmp/x.json', { BOT: 'v' })).toThrow(/foglalt/)
    expect(setSecretSpy).not.toHaveBeenCalled()
  })
})

describe('the runtime resolvers refuse it too', () => {
  const ROOT = mkdtempSync(join(tmpdir(), 'approval-bot-resolver-'))
  beforeAll(() => {
    mkdirSync(join(ROOT, 'scripts'), { recursive: true })
    mkdirSync(join(ROOT, 'dist', 'web'), { recursive: true })
    for (const f of ['vault-resolve.mjs', 'vault-headers-helper.mjs']) copyFileSync(join(process.cwd(), 'scripts', f), join(ROOT, 'scripts', f))
    writeFileSync(join(ROOT, 'dist', 'web', 'vault.js'),
      `export function getSecret(id) { return id === 'telegram-approval-bot' || id === 'custom-bot-id' ? '${TOKEN_VALUE}' : id === 'other' ? '${OTHER_VALUE}' : null }\n`)
  })
  afterAll(() => rmSync(ROOT, { recursive: true, force: true }))
  function run(script: string, args: string[], stdin = ''): Promise<{ stdout: string; stderr: string }> {
    return new Promise((resolve) => {
      const child = execFile(process.execPath, [join(ROOT, 'scripts', script), ...args], (_e, stdout, stderr) => resolve({ stdout, stderr }))
      child.stdin!.end(stdin)
    })
  }
  it('vault-resolve.mjs: the default id is refused, another still resolves', async () => {
    const r = await run('vault-resolve.mjs', [], 'TOK=telegram-approval-bot\nOK=other\n')
    expect(r.stdout).not.toContain(TOKEN_VALUE)
    expect(r.stdout).toContain(`OK=${OTHER_VALUE}`)
    expect(r.stderr).toContain('approval bot token')
  })
  it('vault-resolve.mjs: an APPROVAL_BOT_VAULT_ID set in .env is refused', async () => {
    writeFileSync(join(ROOT, '.env'), 'APPROVAL_BOT_VAULT_ID=custom-bot-id\n')
    const r = await run('vault-resolve.mjs', [], 'TOK=custom-bot-id\n')
    expect(r.stdout).not.toContain(TOKEN_VALUE)
    rmSync(join(ROOT, '.env'))
  })
  it('vault-headers-helper.mjs refuses it as a header', async () => {
    const r = await run('vault-headers-helper.mjs', ['Authorization=Bearer:::telegram-approval-bot'])
    expect(r.stdout).not.toContain(TOKEN_VALUE)
    expect(r.stderr).toContain('approval bot token')
  })
})
