// The open reader posture's second risk (Viktor 24670): the reader holds
// nothing, but its caller writes the URL, so the URL itself can carry context
// out. The open branch limits the URL's shape, refuses collector hosts,
// resolves the host once, and logs every decision without the query.
import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  egressDecision, openReaderShapeViolation, openReaderLogFields, openReaderResolvesInward,
  OPEN_READER_MAX_URL, OPEN_READER_MAX_QUERY,
// @ts-expect-error -- plain .mjs hook script, no types
} from '../../scripts/hooks/egress-gate.mjs'

const QUARANTINE = 'quarantine-reader'
const EMPTY = { domains: [], prefixes: [], quarantineDomains: [] }
const OPEN = { ...EMPTY, quarantinePosture: 'denylist' }
const tier = (url: string, list: Record<string, unknown> = OPEN, agent = QUARANTINE) => egressDecision('WebFetch', { url }, list, agent)

describe('open branch: URL shape', () => {
  it('still lets an ordinary public page through', () => {
    expect(tier('https://www.reddit.com/r/devops/about/rules.json').tier).toBe('quarantine-open')
    expect(tier('https://shop.example-store.hu/termek/konyv?id=123&lang=hu').tier).toBe('quarantine-open')
  })
  it('refuses an over-long URL or query', () => {
    const longPath = 'https://evil-feeds.com/' + 'a'.repeat(OPEN_READER_MAX_URL)
    expect(tier(longPath)).toEqual({ blocked: true, tier: 'quarantine-denied', reason: 'url-too-long' })
    const longQuery = 'https://evil-feeds.com/?d=' + 'x'.repeat(OPEN_READER_MAX_QUERY)
    expect(tier(longQuery)).toEqual({ blocked: true, tier: 'quarantine-denied', reason: 'query-too-long' })
  })
  it('refuses userinfo and non-web ports, accepts explicit 80/443', () => {
    expect(openReaderShapeViolation('https://user:pw@evil-feeds.com/')).toBe('userinfo')
    expect(openReaderShapeViolation('https://evil-feeds.com:8443/')).toBe('port')
    expect(openReaderShapeViolation('https://evil-feeds.com:443/')).toBeNull()
    expect(openReaderShapeViolation('http://evil-feeds.com:80/')).toBeNull()
    expect(openReaderShapeViolation('http://evil-feeds.com:443/')).toBeNull()
  })
  it('refuses request catchers, OAST collectors, tunnels and paste sites, subdomains included', () => {
    for (const u of ['https://webhook.site/abc', 'https://x1.pipedream.net/', 'https://abc.oast.fun/', 'https://q.oastify.com/',
      'https://a.ngrok-free.app/', 'https://pastebin.com/raw/x', 'https://hooks.slack.com/services/T/B/X', 'https://x.trycloudflare.com/']) {
      expect([u, openReaderShapeViolation(u)]).toEqual([u, 'collector-host'])
    }
  })
  it('refuses message-delivering paths but not the rest of the host', () => {
    expect(openReaderShapeViolation('https://api.telegram.org/bot123:abc/sendMessage')).toBe('collector-path')
    expect(openReaderShapeViolation('https://discord.com/api/webhooks/1/x')).toBe('collector-path')
    expect(openReaderShapeViolation('https://discord.com/api/v10/webhooks/1/x')).toBe('collector-path')
    expect(openReaderShapeViolation('https://discord.com/blog')).toBeNull()
  })
  it('does not touch the allowlist posture or the main agent', () => {
    // Allowlist posture: an unnamed host is blocked as before, with no shape reason.
    expect(tier('https://webhook.site/abc', EMPTY)).toEqual({ blocked: true, tier: 'none' })
    // Main agent: blocked as before, whatever the posture says.
    expect(tier('https://evil-feeds.com/', OPEN, '').blocked).toBe(true)
  })
})

describe('open branch: log fields carry no query', () => {
  it('keeps host, cut path, query length and a short hash only', () => {
    const f = openReaderLogFields('https://evil-feeds.com/' + 'p'.repeat(100) + '?d=c2VjcmV0LWNvbnRleHQtZnJvbS10aGUtY2FsbGVy')
    expect(f.host).toBe('evil-feeds.com')
    expect(f.path.length).toBe(60)
    expect(f.pathLen).toBe(101)
    expect(f.queryLen).toBe(42)
    expect(f.queryHash).toMatch(/^[0-9a-f]{8}$/)
    expect(f.b64like).toBe(true)
    expect(JSON.stringify(f)).not.toContain('c2VjcmV0')
  })
  it('a plain query is not flagged', () => {
    expect(openReaderLogFields('https://evil-feeds.com/?id=123&lang=hu').b64like).toBe(false)
  })
})

describe('open branch: DNS resolution', () => {
  const fake = (addrs: string[]) => async () => addrs.map((address) => ({ address, family: address.includes(':') ? 6 : 4 }))
  it('refuses a public name that resolves inward', async () => {
    expect(await openReaderResolvesInward('rebind.evil-feeds.com', fake(['127.0.0.1']))).toBe('resolves-private')
    expect(await openReaderResolvesInward('x.evil-feeds.com', fake(['93.184.216.34', '10.0.0.5']))).toBe('resolves-private')
    expect(await openReaderResolvesInward('x.evil-feeds.com', fake(['::1']))).toBe('resolves-private')
    expect(await openReaderResolvesInward('x.evil-feeds.com', fake(['::ffff:192.168.1.10']))).toBe('resolves-private')
  })
  it('passes a name with public addresses only', async () => {
    expect(await openReaderResolvesInward('ok.evil-feeds.com', fake(['93.184.216.34', '2606:2800:220:1::248']))).toBeNull()
  })
  it('fails closed on lookup error, empty answer and timeout', async () => {
    expect(await openReaderResolvesInward('x', async () => { throw new Error('ENOTFOUND') })).toBe('dns-failed')
    expect(await openReaderResolvesInward('x', fake([]))).toBe('dns-empty')
    expect(await openReaderResolvesInward('x', () => new Promise(() => {}), 20)).toBe('dns-timeout')
  })
})

// End to end: the hook as Claude Code runs it, in a temporary repo root, so the
// log line it writes can be read back. No network: the denied cases never
// reach the DNS step, and the allowed case uses a name that cannot resolve.
describe('hook entry point: what the log gets', () => {
  let root: string
  const listName = ['egress', 'allowlist.json'].join('-')
  beforeAll(() => {
    root = mkdtempSync(join(tmpdir(), 'qopen-'))
    mkdirSync(join(root, 'scripts', 'hooks'), { recursive: true })
    mkdirSync(join(root, 'store'))
    for (const f of ['egress-gate.mjs', 'public-suffix-list.json']) {
      copyFileSync(join(__dirname, '..', '..', 'scripts', 'hooks', f), join(root, 'scripts', 'hooks', f))
    }
    writeFileSync(join(root, 'store', listName), JSON.stringify({ quarantine_reader_posture: 'denylist' }))
  })
  afterAll(() => { rmSync(root, { recursive: true, force: true }) })
  const run = (url: string) => spawnSync('node', [join(root, 'scripts', 'hooks', 'egress-gate.mjs')], {
    input: JSON.stringify({ tool_name: 'WebFetch', tool_input: { url }, agent_type: QUARANTINE }),
    encoding: 'utf-8', timeout: 15000,
  })
  const log = () => (existsSync(join(root, 'store', 'egress-blocked.log')) ? readFileSync(join(root, 'store', 'egress-blocked.log'), 'utf-8') : '')

  it('a refused exfiltration-shaped URL is denied and logged without its query', () => {
    const secret = 'Q0xJRU5ULUFHR1JFR0FURS1ET05PVC1MRUFL'
    const r = run(`https://webhook.site/x?d=${secret}`)
    expect(r.stdout).toContain('"permissionDecision":"deny"')
    const l = log()
    expect(l).toMatch(/BLOCKED_QUARANTINE_OPEN host="webhook.site" path="\/x" path_len=2 query_len=\d+ query_sha8=[0-9a-f]{8} query_b64like=1 reason="collector-host"/)
    expect(l).not.toContain(secret)
  })
  it('a name that does not resolve is denied (fail closed) and logged', () => {
    const r = run('https://does-not-exist.invalid-tld-qopen-test.com/feed?x=1')
    expect(r.stdout).toContain('"permissionDecision":"deny"')
    expect(log()).toMatch(/BLOCKED_QUARANTINE_OPEN host="does-not-exist.invalid-tld-qopen-test.com" .*reason="dns-(failed|timeout|empty)"/)
  })
})

describe('daily summary', () => {
  it('counts hosts, new hosts, max query length, reasons and raises the alerts', async () => {
    // @ts-expect-error -- plain .mjs script, no types
    const { summarize, render, HOURLY_ALERT } = await import('../../scripts/egress-quarantine-daily.mjs')
    const line = (ts: string, kind: string, host: string, q: number, reason: string, b64 = false) =>
      `${ts} ${kind} host="${host}" path="/" path_len=1 query_len=${q}${q ? ' query_sha8=abcd1234' : ''}${b64 ? ' query_b64like=1' : ''} reason="${reason}" agent_type="quarantine-reader"`
    const lines = [
      line('2026-11-02T10:00:00.000Z', 'ALLOWED_QUARANTINE_OPEN', 'old.hu', 0, 'open-posture'),
      line('2026-11-03T09:00:00.000Z', 'ALLOWED_QUARANTINE_OPEN', 'old.hu', 5, 'open-posture'),
      line('2026-11-03T09:01:00.000Z', 'ALLOWED_QUARANTINE_OPEN', 'fresh.hu', 40, 'open-posture', true),
      line('2026-11-03T09:02:00.000Z', 'BLOCKED_QUARANTINE_OPEN', 'webhook.site', 60, 'collector-host'),
      'noise line that is not ours',
    ]
    for (let i = 0; i < HOURLY_ALERT + 1; i++) lines.push(line('2026-11-03T11:10:00.000Z', 'ALLOWED_QUARANTINE_OPEN', 'busy.hu', 0, 'open-posture'))
    const s = summarize(lines.join('\n'), '2026-11-03')
    expect(s.allowed).toBe(2 + HOURLY_ALERT + 1)
    expect(s.blocked).toBe(1)
    expect(s.newHosts).toEqual(['fresh.hu', 'busy.hu'])
    expect(s.maxQueryLen).toBe(60)
    expect(s.reasons).toEqual({ 'collector-host': 1 })
    const text = render(s)
    expect(text).toContain('RIASZTÁS: busy.hu')
    expect(text).toContain('RIASZTÁS: kiszivárogtatás-alakú URL elutasítva: collector-host 1')
    expect(text).toContain('RIASZTÁS: base64-szerű lekérdezés: 1 db')
  })
})
