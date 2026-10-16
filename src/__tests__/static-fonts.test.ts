import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import type http from 'node:http'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, readdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { tryHandleStatic } from '../web/routes/static.js'
import type { RouteContext } from '../web/routes/types.js'

// MYSHPTHEME1015 -- the self-hosted brand fonts behind /fonts/. Contract:
// a lowercase .woff2 name inside web/fonts is served as font/woff2 with a long
// cache; anything else under /fonts/ is a 404 that never touches the disk
// outside that one directory.

interface MockRes {
  statusCode: number
  headers: Record<string, string>
  body: Buffer
  writeHead(status: number, headers?: Record<string, string>): MockRes
  end(data?: string | Buffer): void
}

function mkRes(): MockRes {
  return {
    statusCode: 0,
    headers: {},
    body: Buffer.alloc(0),
    writeHead(status, headers) {
      this.statusCode = status
      if (headers) Object.assign(this.headers, headers)
      return this
    },
    end(data) {
      if (data !== undefined) this.body = Buffer.concat([this.body, Buffer.from(data)])
    },
  }
}

let webDir: string

async function get(path: string): Promise<{ handled: boolean; res: MockRes }> {
  const res = mkRes()
  const ctx: RouteContext = {
    req: { headers: {} } as http.IncomingMessage,
    res: res as unknown as http.ServerResponse,
    path,
    method: 'GET',
    url: new URL(`http://127.0.0.1:3420${path}`),
  }
  const handled = await tryHandleStatic(ctx, webDir)
  return { handled, res }
}

beforeAll(() => {
  webDir = mkdtempSync(join(tmpdir(), 'mv-fonts-'))
  mkdirSync(join(webDir, 'fonts'))
  writeFileSync(join(webDir, 'fonts', 'manrope-latin-wght-normal.woff2'), Buffer.from('wOF2-fake'))
  writeFileSync(join(webDir, 'secret.txt'), 'nope')
})

afterAll(() => {
  rmSync(webDir, { recursive: true, force: true })
})

describe('/fonts/ static route', () => {
  it('serves an allowlisted woff2 with its MIME type and a long cache', async () => {
    const { handled, res } = await get('/fonts/manrope-latin-wght-normal.woff2')
    expect(handled).toBe(true)
    expect(res.statusCode).toBe(200)
    expect(res.headers['Content-Type']).toBe('font/woff2')
    expect(res.headers['Cache-Control']).toBe('private, max-age=604800')
    expect(res.body.toString()).toBe('wOF2-fake')
  })

  it('404s a missing font', async () => {
    const { handled, res } = await get('/fonts/inter-latin-wght-normal.woff2')
    expect(handled).toBe(true)
    expect(res.statusCode).toBe(404)
  })

  it.each([
    '/fonts/../secret.txt',
    '/fonts/..%2fsecret.txt',
    '/fonts/sub/manrope-latin-wght-normal.woff2',
    '/fonts/Manrope-Latin.woff2',
    '/fonts/manrope-latin-wght-normal.ttf',
    '/fonts/',
  ])('refuses %s without reading outside web/fonts', async (path) => {
    const { handled, res } = await get(path)
    expect(handled).toBe(true)
    expect(res.statusCode).toBe(404)
    expect(res.body.toString()).not.toContain('nope')
  })
})

describe('shipped font files', () => {
  it('match the route allowlist, so none of them is unreachable', () => {
    const shipped = readdirSync(join(__dirname, '..', '..', 'web', 'fonts'))
    expect(shipped.length).toBeGreaterThan(0)
    for (const name of shipped) expect(name).toMatch(/^[a-z0-9-]+\.woff2$/)
  })
})
