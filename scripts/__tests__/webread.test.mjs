// webread (scripts/webread/): the controls of Viktor's review (2026-11-10-getfile-renderelo-olvaso-itelet.md, A-E),
// tested without the network: the address gate, the guard proxy's refusals, the output-path guard, the limits,
// the scheduler and the sanitised output. The live measurements (sandbox in ps, real hosts) are in the PR.
import { describe, it, expect, afterEach } from 'vitest'
import fs from 'node:fs'
import http from 'node:http'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'
import { PassThrough } from 'node:stream'
import { fileURLToPath } from 'node:url'
import { allowedUrl, blockedReason, makeSafeLookup, startGuardProxy, urlFingerprint } from '../webread/net-guard.mjs'
import { cleanHeader, cleanHost, extFor, nameHost, fetchFile, flagFor, makeRunDir, makeScheduler, parseArgs, writeNew, BANNER } from '../webread/webread.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const tmps = []
function tmp() {
  const d = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'webread-')))
  tmps.push(d)
  return d
}
afterEach(() => {
  while (tmps.length) fs.rmSync(tmps.pop(), { recursive: true, force: true })
})

describe('blockedReason (C: only public unicast)', () => {
  it.each([
    ['127.0.0.1', 'loopback'],
    ['127.255.0.9', 'loopback'],
    ['0.0.0.0', 'this-network'],
    ['10.1.2.3', 'private'],
    ['172.31.255.255', 'private'],
    ['192.168.1.1', 'private'],
    ['169.254.169.254', 'link-local'],
    ['100.64.0.1', 'cgnat'],
    ['224.0.0.1', 'multicast'],
    ['255.255.255.255', 'reserved'],
    ['::1', 'loopback'],
    ['::', 'unspecified'],
    ['::ffff:127.0.0.1', 'v4-mapped-loopback'],
    ['::ffff:7f00:1', 'v4-mapped-loopback'],
    ['[::ffff:10.0.0.1]', 'v4-mapped-private'],
    ['fd12:3456::1', 'unique-local'],
    ['fe80::1%lo0', 'link-local'],
    ['64:ff9b::7f00:1', 'nat64'],
    ['2002:7f00:1::1', '6to4'],
    ['ff02::1', 'multicast'],
    ['0:0:0:0:ffff:0:a00:1', 'v4-translated'],
  ])('%s is blocked (%s)', (ip, why) => {
    expect(blockedReason(ip)).toBe(why)
  })
  it.each(['93.184.215.14', '1.1.1.1', '172.32.0.1', '2606:4700:4700::1111', '::ffff:1.1.1.1'])('%s is allowed', (ip) => {
    expect(blockedReason(ip)).toBeNull()
  })
  it('a name is not an address', () => expect(blockedReason('localhost')).toBe('not-ip'))
  it("the host's own non-loopback interface addresses are blocked", () => {
    const own = Object.values(os.networkInterfaces()).flat().filter((i) => i && !i.internal).map((i) => i.address.split('%')[0])
    for (const a of own) expect(blockedReason(a)).not.toBeNull()
  })
})

describe('makeSafeLookup (C: checked where the connection is made)', () => {
  const fake = (answers) => (host, opts, cb) => cb(null, answers[host] ?? [])
  const run = (lookup, host, opts) => new Promise((r) => lookup(host, opts, (err, a, f) => r({ err, a, f })))
  it('refuses a name with ANY private answer, never picks the public one', async () => {
    const blocked = []
    const lookup = makeSafeLookup({ resolve: fake({ 'mixed.test': [{ address: '1.1.1.1', family: 4 }, { address: '127.0.0.1', family: 4 }] }), onBlock: (h, w) => blocked.push([h, w]) })
    const { err } = await run(lookup, 'mixed.test', { all: true })
    expect(err?.code).toBe('EWEBREAD_BLOCKED')
    expect(blocked).toEqual([['mixed.test', 'loopback']])
  })
  it('hands over exactly the checked public answers', async () => {
    const lookup = makeSafeLookup({ resolve: fake({ 'ok.test': [{ address: '1.1.1.1', family: 4 }] }) })
    expect((await run(lookup, 'ok.test', { all: true })).a).toEqual([{ address: '1.1.1.1', family: 4 }])
    expect(await run(lookup, 'ok.test', {})).toMatchObject({ a: '1.1.1.1', f: 4 })
  })
  it('checks a literal without resolving it', async () => {
    const lookup = makeSafeLookup({ resolve: () => { throw new Error('must not resolve') } })
    expect((await run(lookup, '[::1]', {})).err?.code).toBe('EWEBREAD_BLOCKED')
  })
})

describe('allowedUrl', () => {
  it.each([
    ['http://example.com/', 'not-https'],
    ['file:///etc/hosts', 'not-https'],
    ['ftp://example.com/', 'not-https'],
    ['https://example.com:8443/', 'port'],
    ['https://u:p@example.com/', 'credentials'],
    ['not a url', 'bad-url'],
  ])('%s -> %s', (u, why) => expect(allowedUrl(u)).toMatchObject({ ok: false, reason: why }))
  it('https on 443 passes', () => expect(allowedUrl('https://example.com:443/a?b=1').ok).toBe(true))
  it('a URL over 2048 characters is refused', () => {
    expect(allowedUrl(`https://example.com/?d=${'a'.repeat(2048)}`)).toMatchObject({ ok: false, reason: 'too-long' })
  })
  it('the log keeps the length and a hash of path + query, never the text', () => {
    const fp = urlFingerprint(new URL('https://example.com/p?token=SECRET'))
    expect(fp).toMatch(/^15:[0-9a-f]{8}$/)
    expect(fp).not.toMatch(/SECRET|token/)
  })
})

describe('startGuardProxy (C: the browser\'s only way out)', () => {
  let proxy
  afterEach(async () => proxy && (await proxy.close()))
  const connect = (port, target) =>
    new Promise((resolve) => {
      const s = net.connect(port, '127.0.0.1', () => s.write(`CONNECT ${target} HTTP/1.1\r\nHost: ${target}\r\n\r\n`))
      let buf = ''
      s.on('data', (d) => (buf += d))
      s.on('close', () => resolve(buf.split('\r\n')[0]))
      setTimeout(() => s.destroy(), 3000)
    })
  it('refuses plain http, a non-443 port, a loopback literal and a name that resolves privately', async () => {
    const log = []
    const lookup = makeSafeLookup({ resolve: (h, o, cb) => cb(null, [{ address: '192.168.0.10', family: 4 }]) })
    proxy = await startGuardProxy({ lookup, marker: 'run-secret', log: (h, v) => log.push(`${h} ${v}`) })
    const res = await new Promise((r) => http.get({ host: '127.0.0.1', port: proxy.port, path: 'http://example.com/' }, r))
    expect(res.statusCode).toBe(403)
    expect(res.headers['x-webread-blocked']).toBe('run-secret')
    res.resume()
    expect(await connect(proxy.port, 'example.com:80')).toMatch(/403/)
    expect(await connect(proxy.port, '127.0.0.1:443')).toMatch(/403/)
    expect(await connect(proxy.port, '[::1]:443')).toMatch(/403/)
    expect(await connect(proxy.port, 'rebind.test:443')).toMatch(/403/)
    expect(log).toEqual(expect.arrayContaining(['example.com blocked:not-https', 'example.com blocked:port', '127.0.0.1 blocked:loopback', '::1 blocked:loopback', 'rebind.test blocked:private']))
  })
})

describe('startGuardProxy tunnels end with the run', () => {
  it('close() ends every tunnel, upstream included: a half-open keep-alive does not hold the process (2026-11-10 hang)', async () => {
    // Half-open, like a remote that does not answer our FIN: only a destroy frees our side of the socket.
    const peers = []
    const target = net.createServer({ allowHalfOpen: true }, (s) => peers.push(s))
    await new Promise((r) => target.listen(0, '127.0.0.1', r))
    // Test seam: the tunnel goes to a local server instead of the checked address (the check itself is tested above).
    const upstreams = []
    const connect = () => {
      const u = net.connect(target.address().port, '127.0.0.1')
      upstreams.push(u)
      return u
    }
    const proxy = await startGuardProxy({ lookup: () => {}, connect })
    const client = net.connect(proxy.port, '127.0.0.1')
    await new Promise((r) => client.on('connect', r))
    client.write('CONNECT site.test:443 HTTP/1.1\r\nHost: site.test:443\r\n\r\n')
    await new Promise((r) => client.once('data', r))
    // The browser side ends; the proxy's socket for it stays half-open (http.Server allows that), as in the hang.
    client.end()
    await new Promise((r) => setTimeout(r, 100))
    await proxy.close()
    expect(upstreams).toHaveLength(1)
    expect(upstreams[0].destroyed).toBe(true)
    for (const s of peers) s.destroy()
    await new Promise((r) => target.close(r))
  })
})

describe('output path (B: no caller-chosen path, no overwrite, no link)', () => {
  function root() {
    const r = tmp()
    fs.mkdirSync(path.join(r, 'agents', 'radar', 'work'), { recursive: true })
    fs.mkdirSync(path.join(r, 'store'))
    return r
  }
  it('creates a fresh run dir under agents/<agent>/work/untrusted/webread', () => {
    const r = root()
    const { base, run } = makeRunDir(r, 'radar')
    expect(base).toBe(path.join(r, 'agents', 'radar', 'work', 'untrusted', 'webread'))
    expect(path.dirname(run)).toBe(base)
  })
  it.each(['../radar', 'radar/../../x', 'Radar', '', 'a b'])('refuses the agent name %j', (a) => {
    expect(() => makeRunDir(root(), a)).toThrow()
  })
  it('refuses an agent whose work dir is missing or a link', () => {
    const r = root()
    expect(() => makeRunDir(r, 'nobody')).toThrow()
    fs.mkdirSync(path.join(r, 'agents', 'evil'))
    fs.symlinkSync(path.join(r, 'store'), path.join(r, 'agents', 'evil', 'work'))
    expect(() => makeRunDir(r, 'evil')).toThrow()
  })
  it('refuses a planted link in the untrusted/ path', () => {
    const r = root()
    fs.symlinkSync(path.join(r, 'store'), path.join(r, 'agents', 'radar', 'work', 'untrusted'))
    expect(() => makeRunDir(r, 'radar')).toThrow()
  })
  it('writeNew never overwrites and never follows a link', () => {
    const d = tmp()
    writeNew(d, '01-example.com.txt', 'a')
    expect(() => writeNew(d, '01-example.com.txt', 'b')).toThrow(/EEXIST/)
    fs.writeFileSync(path.join(d, 'target'), 'keep')
    fs.symlinkSync(path.join(d, 'target'), path.join(d, '02-x.txt'))
    expect(() => writeNew(d, '02-x.txt', 'evil')).toThrow(/EEXIST/)
    expect(fs.readFileSync(path.join(d, 'target'), 'utf8')).toBe('keep')
    expect(() => writeNew(d, '../escape.txt', 'x')).toThrow(/bad file name/)
  })
  it('parseArgs has no output-path option at all', () => {
    expect(() => parseArgs(['page', '--agent', 'radar', '--out', '/tmp/x', 'https://a.example/'])).toThrow(/unknown option/)
    expect(() => parseArgs(['page', 'https://a.example/'])).toThrow(/--agent/)
    expect(() => parseArgs(['page', '--agent', 'radar', '--concurrency', '50', 'https://a.example/'])).toThrow(/range/)
    expect(() => parseArgs(['file', '--agent', 'radar', '--max-bytes', String(300 * 1024 * 1024), 'https://a.example/'])).toThrow(/range/)
    expect(parseArgs(['page', '--agent', 'radar', 'https://a.example/'])).toMatchObject({ concurrency: 8, perHost: 2, waitMs: 3000 })
  })
})

describe('fetchFile (C + D: plain https, redirects re-checked, byte limit)', () => {
  // A fake https.get: the same callback shape, a stream as the response.
  function fakeGet(routes) {
    return (u, _opts, cb) => {
      const req = new PassThrough()
      req.destroy = () => {}
      const route = routes[u.toString()]
      setImmediate(() => {
        const res = new PassThrough()
        res.statusCode = route.status
        res.headers = route.headers ?? {}
        cb(res)
        for (const c of route.chunks ?? []) res.write(c)
        res.end()
      })
      return req
    }
  }
  const lookup = makeSafeLookup({ resolve: (h, o, cb) => cb(null, [{ address: '1.1.1.1', family: 4 }]) })
  it('stops a stream without content-length at the byte limit and leaves no file', async () => {
    const d = tmp()
    const big = Buffer.alloc(64 * 1024, 1)
    const get = fakeGet({ 'https://a.example/big': { status: 200, headers: { 'content-type': 'application/pdf' }, chunks: [big, big, big] } })
    const r = await fetchFile(new URL('https://a.example/big'), { lookup, maxBytes: 100 * 1024, dir: d, name: '01-a.example', get })
    expect(r.error).toBe('too_large')
    expect(fs.readdirSync(d)).toEqual([])
  })
  it('a dripping server ends at the total deadline, and the partial file is removed', async () => {
    const d = tmp()
    const get = (u, _o, cb) => {
      const req = new PassThrough()
      setImmediate(() => {
        const res = new PassThrough()
        res.statusCode = 200
        res.headers = { 'content-type': 'text/plain' }
        cb(res)
        res.write('a') // and never ends
      })
      return req
    }
    const r = await fetchFile(new URL('https://a.example/drip'), { lookup, maxBytes: 1024, dir: d, name: '01-a', get, deadlineMs: 50 })
    expect(r.error).toBe('timeout')
    expect(fs.readdirSync(d)).toEqual([])
  })
  it('refuses a declared length over the limit before reading', async () => {
    const d = tmp()
    const get = fakeGet({ 'https://a.example/huge': { status: 200, headers: { 'content-length': String(2 * 1024 ** 3) } } })
    expect((await fetchFile(new URL('https://a.example/huge'), { lookup, maxBytes: 1024, dir: d, name: '01-a', get })).error).toBe('too_large')
  })
  it('re-checks every redirect: plain http and a private literal are refused', async () => {
    const d = tmp()
    const get = fakeGet({
      'https://a.example/r1': { status: 302, headers: { location: 'http://a.example/x' } },
      'https://a.example/r2': { status: 301, headers: { location: 'https://127.0.0.1/admin' } },
    })
    expect((await fetchFile(new URL('https://a.example/r1'), { lookup, maxBytes: 1024, dir: d, name: '01-a', get })).error).toBe('not_https')
    expect((await fetchFile(new URL('https://a.example/r2'), { lookup, maxBytes: 1024, dir: d, name: '02-a', get })).error).toBe('blocked')
  })
  it('writes a new file named by the tool, with the type-based extension and the sha256', async () => {
    const d = tmp()
    const get = fakeGet({ 'https://a.example/p': { status: 200, headers: { 'content-type': 'application/pdf\r\nX-Evil: 1' }, chunks: ['%PDF-1.7'] } })
    const r = await fetchFile(new URL('https://a.example/p'), { lookup, maxBytes: 1024, dir: d, name: '01-a.example', get })
    expect(r).toMatchObject({ status: 200, size: 8, file: '01-a.example.pdf', type: 'application/pdfX-Evil 1' })
    expect(r.sha).toMatch(/^[0-9a-f]{64}$/)
  })
})

describe('output and flags (E)', () => {
  it('stdout fields carry only the safe alphabet', () => {
    expect(cleanHost('EVIL.com\n<ignore previous>')).toBe('evil.comignoreprevious')
    expect(cleanHeader('text/html; charset=utf-8\r\n`$(rm -rf ~)`')).toBe('text/html; charset=utf-8rm -rf ')
    expect(cleanHeader('x'.repeat(100))).toHaveLength(60)
    expect(nameHost('[2606:4700::1111]')).toBe('2606-4700--1111-')
    expect(nameHost('.evil')).toBe('evil')
  })
  it('extension from the type, never from the URL', () => {
    expect(extFor('application/pdf')).toBe('pdf')
    expect(extFor('application/x-sh')).toBe('bin')
    expect(extFor(undefined)).toBe('bin')
  })
  it.each([
    [{ status: 200, text: 'x'.repeat(500) }, 'ok'],
    [{ status: 200, text: 'short' }, 'empty'],
    [{ status: 403, text: 'Just a moment... checking your browser' }, 'captcha'],
    [{ status: 200, text: 'Please complete the CAPTCHA to continue' }, 'captcha'],
    [{ status: 404, text: 'not found' }, 'http_404'],
    [{ status: 200, size: 0 }, 'empty'],
    [{ error: 'blocked', status: 0 }, 'blocked'],
  ])('%j -> %s', (input, flag) => expect(flagFor(input)).toBe(flag))
  it('the page files start with the untrusted banner', () => expect(BANNER).toMatch(/^### UNTRUSTED WEB CONTENT/))
})

describe('makeScheduler (D: global and per-host limits)', () => {
  it('never runs more than the limits', async () => {
    const schedule = makeScheduler(3, 1)
    let now = 0
    let peak = 0
    const perHost = new Map()
    let hostPeak = 0
    const job = (h) => async () => {
      now++
      perHost.set(h, (perHost.get(h) ?? 0) + 1)
      peak = Math.max(peak, now)
      hostPeak = Math.max(hostPeak, perHost.get(h))
      await new Promise((r) => setTimeout(r, 5))
      now--
      perHost.set(h, perHost.get(h) - 1)
    }
    await Promise.all(['a', 'a', 'a', 'b', 'b', 'c', 'd', 'd'].map((h) => schedule(h, job(h))))
    expect(peak).toBe(3)
    expect(hostPeak).toBe(1)
  })
})

describe('browser launch (A) and context (D), read from the source', () => {
  // Code only: the header comment names the flags it avoids.
  const src = fs.readFileSync(path.join(here, '..', 'webread', 'webread.mjs'), 'utf8').split('\n').filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join('\n')
  it('Chromium\'s own sandbox, a PATH-only environment, the guard proxy with loopback not bypassed', () => {
    expect(src).toMatch(/chromiumSandbox: true/)
    expect(src).toMatch(/env: \{ PATH: '\/usr\/bin:\/bin', TMPDIR: os\.tmpdir\(\) \}/)
    expect(src).toMatch(/--proxy-bypass-list=<-loopback>/)
    expect(src).toMatch(/--disable-quic/)
    expect(src).toMatch(/--force-webrtc-ip-handling-policy=disable_non_proxied_udp/)
    expect(src).not.toMatch(/--no-sandbox/)
    expect(src).not.toMatch(/process\.env\.WEBREAD/)
  })
  it('downloads and service workers are blocked', () => {
    expect(src).toMatch(/acceptDownloads: false, serviceWorkers: 'block'/)
  })
})
