// Viktor 26241 (BILLINGOISSUE1104): the server-only Vault ids (the approval bot token and the
// Billingo issue signing key) cannot be written, imported or deleted over HTTP either: a
// fleet-token caller could otherwise replace or remove the signing key (a denial of
// service; the gate pins the public half, so no forgery).
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { Readable } from 'node:stream'
import type http from 'node:http'
import type { RouteContext } from '../web/routes/types.js'

vi.mock('../logger.js', () => ({ logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() }, PRETTY_OPTIONS: {} }))
const setSecret = vi.fn()
const deleteSecret = vi.fn((..._a: unknown[]) => true)
vi.mock('../web/vault.js', () => ({
  listSecrets: () => [],
  setSecret: (...a: unknown[]) => setSecret(...a),
  deleteSecret: (...a: unknown[]) => deleteSecret(...a),
  getSecret: () => null,
  getSecretsForEnv: () => ({}),
}))

const { tryHandleConnectors } = await import('../web/routes/connectors.js')
const { isServerOnlyVaultId } = await import('../web/server-only-secrets.js')

function mkRes() {
  const r: { statusCode: number; body: string; headers: Record<string, unknown> } & Record<string, any> = { statusCode: 0, body: '', headers: {} }
  r.writeHead = (c: number) => { r.statusCode = c; return r }
  r.end = (b?: string) => { r.body = b ?? '' }
  r.setHeader = () => {}
  r.getHeader = () => undefined
  return r
}
async function call(method: string, path: string, body?: unknown) {
  const res = mkRes()
  const req = Object.assign(Readable.from(body === undefined ? [] : [Buffer.from(JSON.stringify(body))]), { headers: {}, method, url: path })
  const ctx = { req: req as unknown as http.IncomingMessage, res: res as unknown as http.ServerResponse, path, method, url: new URL(`http://127.0.0.1:3420${path}`), auth: { kind: 'token' } } as RouteContext
  await tryHandleConnectors(ctx)
  return res
}

beforeEach(() => { setSecret.mockClear(); deleteSecret.mockClear() })

describe('server-only Vault ids over HTTP', () => {
  it.each(['billingo-issue-signing-key', 'telegram-approval-bot'])('%s is server-only', (id) => {
    expect(isServerOnlyVaultId(id)).toBe(true)
    expect(isServerOnlyVaultId(` ${id} `)).toBe(true)
  })
  it.each(['billingo-issue-signing-key', 'telegram-approval-bot'])('POST /api/vault refuses %s and writes nothing', async (id) => {
    const res = await call('POST', '/api/vault', { id, label: 'x', value: 'attacker-key' })
    expect(res.statusCode).toBe(403)
    expect(setSecret).not.toHaveBeenCalled()
  })
  it.each(['billingo-issue-signing-key', 'telegram-approval-bot'])('DELETE /api/vault/%s is refused and deletes nothing', async (id) => {
    const res = await call('DELETE', `/api/vault/${id}`)
    expect(res.statusCode).toBe(403)
    expect(deleteSecret).not.toHaveBeenCalled()
  })
  it('an ordinary id still works', async () => {
    expect((await call('POST', '/api/vault', { id: 'some-key', label: 'x', value: 'v' })).statusCode).toBe(200)
    expect(setSecret).toHaveBeenCalledTimes(1)
  })
})
