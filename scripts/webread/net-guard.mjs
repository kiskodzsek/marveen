// net-guard.mjs -- the address gate of webread (Viktor 2026-11-10-getfile-renderelo-olvaso-itelet.md, C).
//
// One rule for every byte webread fetches: only https on port 443, and only to a PUBLIC unicast address.
// The address is checked where the connection is made, never by a separate lookup beforehand (DNS
// rebinding: a second lookup may answer differently). Both paths use the same `safeLookup`:
//   - the `file` mode's Node https request (`lookup:` option of https.request), and
//   - the local forward proxy the browser is forced through (`--proxy-server`, loopback not bypassed):
//     every CONNECT is resolved here, checked, and connected to the checked address.
// A name that resolves to ANY blocked address is refused as a whole (no "pick the public one").

import dns from 'node:dns'
import crypto from 'node:crypto'
import http from 'node:http'
import net from 'node:net'
import os from 'node:os'

// IPv4 ranges that are not public unicast (RFC 6890 and friends).
const V4_BLOCKED = [
  ['0.0.0.0', 8, 'this-network'],
  ['10.0.0.0', 8, 'private'],
  ['100.64.0.0', 10, 'cgnat'],
  ['127.0.0.0', 8, 'loopback'],
  ['169.254.0.0', 16, 'link-local'],
  ['172.16.0.0', 12, 'private'],
  ['192.0.0.0', 24, 'ietf'],
  ['192.0.2.0', 24, 'doc'],
  ['192.88.99.0', 24, '6to4-relay'],
  ['192.168.0.0', 16, 'private'],
  ['198.18.0.0', 15, 'benchmark'],
  ['198.51.100.0', 24, 'doc'],
  ['203.0.113.0', 24, 'doc'],
  ['224.0.0.0', 4, 'multicast'],
  ['240.0.0.0', 4, 'reserved'],
]
// IPv6 ranges that are not public unicast. IPv4-mapped (::ffff:0:0/96) is unwrapped and checked as IPv4.
const V6_BLOCKED = [
  ['::', 128, 'unspecified'],
  ['::1', 128, 'loopback'],
  ['::', 96, 'v4-compatible'],
  ['64:ff9b::', 96, 'nat64'],
  ['64:ff9b:1::', 48, 'nat64'],
  ['100::', 64, 'discard'],
  ['2001::', 32, 'teredo'],
  ['2001:db8::', 32, 'doc'],
  ['2002::', 16, '6to4'],
  ['fc00::', 7, 'unique-local'],
  ['fe80::', 10, 'link-local'],
  ['fec0::', 10, 'site-local'],
  ['::ffff:0:0:0', 96, 'v4-translated'],
  ['ff00::', 8, 'multicast'],
]

const v4List = new net.BlockList()
const v6List = new net.BlockList()
for (const [a, p] of V4_BLOCKED) v4List.addSubnet(a, p, 'ipv4')
for (const [a, p] of V6_BLOCKED) v6List.addSubnet(a, p, 'ipv6')

function v4ToInt(ip) {
  return ip.split('.').reduce((n, o) => n * 256 + Number(o), 0)
}
function inV4(ip, base, prefix) {
  const mask = prefix === 0 ? 0 : 2 ** 32 - 2 ** (32 - prefix)
  return (v4ToInt(ip) & mask) >>> 0 === (v4ToInt(base) & mask) >>> 0
}

// The 16 bytes of an IPv6 address (any textual form net.isIPv6 accepts, including a dotted tail).
function v6Bytes(ip) {
  let s = ip.toLowerCase()
  const zone = s.indexOf('%')
  if (zone >= 0) s = s.slice(0, zone)
  let tail = []
  const dotted = /(\d+\.\d+\.\d+\.\d+)$/.exec(s)
  if (dotted) {
    tail = dotted[1].split('.').map(Number)
    s = s.slice(0, -dotted[1].length) + '0:0'
  }
  const [head, rest] = s.includes('::') ? s.split('::') : [s, null]
  const h = head ? head.split(':') : []
  const r = rest === null ? [] : rest ? rest.split(':') : []
  const fill = rest === null ? 0 : 8 - h.length - r.length
  const groups = [...h, ...Array(fill).fill('0'), ...r].map((g) => parseInt(g || '0', 16))
  const bytes = groups.flatMap((g) => [g >> 8, g & 0xff])
  if (tail.length) bytes.splice(12, 4, ...tail)
  return bytes
}

/** The reason an address is not allowed, or null when it is a public unicast address. Not an IP: 'not-ip'. */
export function blockedReason(address) {
  const ip = String(address ?? '').replace(/^\[|\]$/g, '')
  const kind = net.isIP(ip)
  if (kind === 4) {
    for (const [a, p, why] of V4_BLOCKED) if (inV4(ip, a, p)) return why
    if (v4List.check(ip, 'ipv4')) return 'blocked'
    return ownAddresses().has(ip) ? 'own-interface' : null
  }
  if (kind === 6) {
    const b = v6Bytes(ip)
    const mapped = b.slice(0, 10).every((x) => x === 0) && b[10] === 0xff && b[11] === 0xff
    if (mapped) {
      const v4 = b.slice(12).join('.')
      const why = blockedReason(v4)
      return why ? `v4-mapped-${why}` : null
    }
    for (const [a, p, why] of V6_BLOCKED) {
      const base = v6Bytes(a)
      let ok = true
      for (let bit = 0; bit < p && ok; bit++) {
        const i = bit >> 3
        const m = 0x80 >> (bit & 7)
        ok = (b[i] & m) === (base[i] & m)
      }
      if (ok) return why
    }
    if (v6List.check(ip, 'ipv6')) return 'blocked'
    return ownAddresses().has(v6Bytes(ip).join(':')) ? 'own-interface' : null
  }
  return 'not-ip'
}

// The host's own interface addresses (a public IPv4 or a global IPv6 included): a name pointing back at this
// machine would reach a local service on 443 (Viktor webread-delta INFO 2). Read once per process.
let own = null
function ownAddresses() {
  if (own) return own
  own = new Set()
  for (const list of Object.values(os.networkInterfaces())) {
    for (const { address, family } of list ?? []) {
      if (family === 'IPv4' || family === 4) own.add(address)
      else if (net.isIPv6(address)) own.add(v6Bytes(address).join(':'))
    }
  }
  return own
}

export class BlockedAddressError extends Error {
  constructor(host, reason) {
    super(`blocked address: ${reason}`)
    this.code = 'EWEBREAD_BLOCKED'
    this.host = host
    this.reason = reason
  }
}

/**
 * A `lookup` for net.connect / https.request that resolves the name ONCE, refuses it if any answer is a
 * blocked address, and hands the connection exactly the addresses it checked. `resolve` is injectable for
 * tests (same signature as dns.lookup with { all: true }).
 */
export function makeSafeLookup({ resolve = dns.lookup, onBlock } = {}) {
  return function safeLookup(hostname, options, callback) {
    if (typeof options === 'function') {
      callback = options
      options = {}
    }
    const opts = typeof options === 'number' ? { family: options } : { ...(options || {}) }
    const literal = net.isIP(String(hostname).replace(/^\[|\]$/g, ''))
    const finish = (list) => {
      for (const { address } of list) {
        const why = blockedReason(address)
        if (why) {
          onBlock?.(hostname, why)
          return callback(new BlockedAddressError(hostname, why))
        }
      }
      if (!list.length) return callback(Object.assign(new Error('no address'), { code: 'ENOTFOUND' }))
      if (opts.all) return callback(null, list)
      return callback(null, list[0].address, list[0].family)
    }
    if (literal) return finish([{ address: String(hostname).replace(/^\[|\]$/g, ''), family: literal }])
    resolve(hostname, { all: true, family: opts.family || 0 }, (err, list) => {
      if (err) return callback(err)
      finish(Array.isArray(list) ? list : [{ address: list, family: net.isIP(list) }])
    })
  }
}

export const MAX_URL_CHARS = 2048

/** True for an https URL on the default port, without credentials, at most MAX_URL_CHARS long. */
export function allowedUrl(raw) {
  if (String(raw ?? '').length > MAX_URL_CHARS) return { ok: false, reason: 'too-long' }
  let u
  try {
    u = new URL(raw)
  } catch {
    return { ok: false, reason: 'bad-url' }
  }
  if (u.protocol !== 'https:') return { ok: false, reason: 'not-https' }
  if (u.port && u.port !== '443') return { ok: false, reason: 'port' }
  if (u.username || u.password) return { ok: false, reason: 'credentials' }
  if (!u.hostname) return { ok: false, reason: 'bad-url' }
  return { ok: true, url: u }
}

/**
 * What the request log keeps of a URL besides its host: the length of path + query and 8 hex of its sha256.
 * Enough to see a long or repeated query (data carried out in a GET, Viktor webread-delta LOW), never the text
 * (it may hold a token).
 */
export function urlFingerprint(u) {
  const tail = `${u.pathname}${u.search}`
  return `${tail.length}:${crypto.createHash('sha256').update(tail).digest('hex').slice(0, 8)}`
}

/**
 * The browser's only way out: an HTTP forward proxy on 127.0.0.1 that accepts CONNECT <host>:443 and
 * nothing else (plain http, ws, other ports: 403). Each tunnel goes through `lookup` (the safe one), so
 * the browser's own DNS answer is never trusted. `log(host, verdict)` records host and verdict only.
 */
export function startGuardProxy({ lookup, log = () => {}, marker = '1', connect = net.connect }) {
  const server = http.createServer((req, res) => {
    // Absolute-form requests are plain http (or ws): never.
    let host = 'unknown'
    try {
      host = new URL(req.url).hostname
    } catch {}
    log(host, 'blocked:not-https')
    res.writeHead(403, { 'content-type': 'text/plain', connection: 'close', 'x-webread-blocked': marker })
    res.end('webread: only https\n')
  })
  const sockets = new Set()
  server.on('connection', (s) => {
    sockets.add(s)
    s.on('close', () => sockets.delete(s))
  })
  server.on('connect', (req, client, head) => {
    const m = /^(\[[^\]]+\]|[^:]+):(\d+)$/.exec(req.url || '')
    const deny = (why, host = 'unknown') => {
      log(host, `blocked:${why}`)
      client.end('HTTP/1.1 403 Forbidden\r\nconnection: close\r\ncontent-length: 0\r\n\r\n')
    }
    if (!m) return deny('bad-connect')
    const host = m[1].replace(/^\[|\]$/g, '').toLowerCase()
    if (m[2] !== '443') return deny('port', host)
    // A literal IP never reaches `lookup` in net.connect: check it here, before any socket exists.
    if (net.isIP(host)) {
      const why = blockedReason(host)
      if (why) return deny(why, host)
    }
    const upstream = connect({ host, port: 443, lookup, autoSelectFamily: false })
    // Tracked, so close() ends it too: a site's keep-alive tunnel must not hold the process open after the run.
    sockets.add(upstream)
    upstream.on('close', () => sockets.delete(upstream))
    upstream.once('connect', () => {
      log(host, 'tunnel')
      client.write('HTTP/1.1 200 Connection Established\r\n\r\n')
      if (head?.length) upstream.write(head)
      upstream.pipe(client)
      client.pipe(upstream)
    })
    upstream.once('error', (err) => {
      if (err?.code === 'EWEBREAD_BLOCKED') return deny(err.reason, host)
      log(host, `error:${String(err?.code || 'connect').replace(/[^A-Za-z0-9_-]/g, '').slice(0, 24)}`)
      client.end('HTTP/1.1 502 Bad Gateway\r\nconnection: close\r\ncontent-length: 0\r\n\r\n')
    })
    client.on('error', () => upstream.destroy())
    client.on('close', () => upstream.destroy())
    upstream.on('close', () => client.destroy())
  })
  return new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      resolve({
        port: server.address().port,
        close: () =>
          new Promise((r) => {
            for (const s of sockets) s.destroy()
            server.close(() => r())
          }),
      })
    })
  })
}
