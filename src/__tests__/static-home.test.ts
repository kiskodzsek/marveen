import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import type http from 'node:http'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { tryHandleStatic } from '../web/routes/static.js'
import type { RouteContext } from '../web/routes/types.js'

// The office view is the home page (Patrik TG 14169): / serves iroda.html, the
// classic dashboard moved to /dashboard and stays on /index.html for old
// bookmarks.

interface MockRes {
  statusCode: number
  headers: Record<string, string>
  body: Buffer
  writeHead(status: number, headers?: Record<string, string>): MockRes
  setHeader(name: string, value: string): void
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
    setHeader(name, value) { this.headers[name] = value },
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
  webDir = mkdtempSync(join(tmpdir(), 'mv-home-'))
  writeFileSync(join(webDir, 'iroda.html'), '<html>OFFICE-VIEW</html>')
  writeFileSync(join(webDir, 'index.html'), '<html><head><title>x</title></head><body>CLASSIC-DASHBOARD</body></html>')
  writeFileSync(join(webDir, 'app.js'), '')
  writeFileSync(join(webDir, 'style.css'), '')
})

afterAll(() => {
  rmSync(webDir, { recursive: true, force: true })
})

describe('home page routing', () => {
  it('serves the office view on /', async () => {
    const { handled, res } = await get('/')
    expect(handled).toBe(true)
    expect(res.statusCode).toBe(200)
    expect(res.body.toString()).toContain('OFFICE-VIEW')
  })
  it.each(['/dashboard', '/index.html'])('serves the classic dashboard on %s', async (path) => {
    const { handled, res } = await get(path)
    expect(handled).toBe(true)
    expect(res.statusCode).toBe(200)
    expect(res.body.toString()).toContain('CLASSIC-DASHBOARD')
  })
  it('keeps /iroda as an alias of the office view', async () => {
    const { res } = await get('/iroda')
    expect(res.body.toString()).toContain('OFFICE-VIEW')
  })
})
