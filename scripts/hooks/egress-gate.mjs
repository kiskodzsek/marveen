#!/usr/bin/env node
// PreToolUse hook: WebFetch egress allowlist enforcement.
//
// Any WebFetch call from the main agent must target a known, legitimate API
// endpoint. Arbitrary web content (RSS feeds, docs, news pages, public APIs
// not in the allowlist) MUST go through the quarantine-reader sub-agent
// instead, so the fetched content is quarantined, wrapped, and never executed
// as instructions in the main agent's context.
//
// Two-tier allowlist:
//   1. Built-in (ALLOWED_PREFIXES): hard-coded, always enforced.
//   2. Runtime (store/egress-allowlist.json): operator-managed, loaded on each
//      invocation. Shape: { "domains": ["example.com"], "prefixes": ["https://host/path/"],
//      "quarantine_domains": ["feeds.example.org"], "quarantine_reader_posture": "allowlist"|"denylist" }
//      All keys are optional. Missing file or malformed JSON -> treated as empty
//      lists (FAIL-OPEN on the file, FAIL-SAFE on the decision: the built-in list
//      still guards; no extra URLs are allowed merely because the file is missing).
//
// When a URL is not on either allowlist:
//   - The tool call is HARD-BLOCKED (decision: deny).
//   - The blocked call is appended to EGRESS_BLOCK_LOG for operator review.
//   - The operator can approve the URL/domain: add it to store/egress-allowlist.json,
//     then re-run the WebFetch. No restart required for THIS hook (it re-reads
//     the JSON on every invocation).
//   - GRANT LATENCY for the quarantine-reader (EGRESSRENDER824): the reader's
//     own prompt-level list is a RENDERED copy of this JSON, refreshed by a
//     file-watcher within ~5s of a JSON change and read at the reader's next
//     SPAWN. A denial from the reader's prompt copy produces NO line in the
//     block log below (it rejects without a network call) -- if a freshly
//     granted domain is still refused, wait a few seconds and spawn a new
//     reader; a session restart is NOT needed.
//
// The log is separate from the main Marveen log so operators can grep it
// independently: `tail -f store/egress-blocked.log`
//
// Scope: this guard covers the Claude Code WebFetch tool only -- it is wired
// with matcher "WebFetch" and sees no other tool. It does NOT intercept
// WebSearch or MCP-server outbound requests.
//
// The SHELL half is a separate control: BASH_EGRESS_DENY in
// src/web/agent-scaffold.ts puts a small permissions.deny list on every agent
// (curl to https://, plus wget/nc/ncat/telnet outright), because a fetched page
// telling an agent to run a curl would otherwise walk straight past this file.
// That list is a deny list, not a sandbox, and its limits are written down in
// docs/security-hardening.md. The two halves are deliberately separate: this
// one decides on a URL, that one on a command string.

import { readFileSync, appendFileSync, mkdirSync } from 'node:fs'
import { realpathSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Derive repo root from this script's location (scripts/hooks/egress-gate.mjs).
const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const EGRESS_BLOCK_LOG = join(REPO_ROOT, 'store', 'egress-blocked.log')
const RUNTIME_ALLOWLIST_PATH = join(REPO_ROOT, 'store', 'egress-allowlist.json')

// Dashboard port: env WEB_PORT, else the install .env, else the 3420 default.
// A fixed 3420 in the allowlist below blocked the agent's own dashboard as soon
// as the install moved to another port.
// SECURITY: the value is interpolated into an allowlist PREFIX (`http://localhost:${PORT}/`), so it
// must be digits ONLY. An unvalidated value containing `@` turns the whole `localhost:<value>` part
// into a URL userinfo section -- `http://localhost:3420@evil.com/` resolves to host evil.com, which
// would put an attacker-chosen host on the built-in allowlist and defeat the egress gate entirely.
// Anything that is not 1-5 digits is rejected and falls back to the default port.
const isValidPort = (v) => /^\d{1,5}$/.test(v)
const DASHBOARD_PORT = (() => {
  const fromEnv = process.env['WEB_PORT']
  if (fromEnv && isValidPort(fromEnv)) return fromEnv
  try {
    const m = readFileSync(join(REPO_ROOT, '.env'), 'utf-8').match(/^WEB_PORT=(.*)$/m)
    const v = m?.[1]?.trim().replace(/^["']|["']$/g, '')
    if (v && isValidPort(v)) return v
  } catch { /* no .env: fall through to the default */ }
  return '3420'
})()

// Built-in allowlist: URL prefixes the main agent may call directly via WebFetch.
// Anything not on this list (or the runtime allowlist) must go through the
// quarantine-reader sub-agent. Keep sorted and documented so additions are
// intentional, not accidental.
const ALLOWED_PREFIXES = [
  // GitHub REST API
  'https://api.github.com/',
  // Google OAuth token endpoint
  'https://oauth2.googleapis.com/',
  // Google APIs (Calendar, Gmail, Drive, etc.)
  'https://www.googleapis.com/',
  'https://gmail.googleapis.com/',
  'https://calendar.googleapis.com/',
  // Telegram Bot API
  'https://api.telegram.org/',
  // Slack Web API
  'https://slack.com/api/',
  // Discord REST API
  'https://discord.com/api/',
  // Ollama (local LLM server) -- localhost and loopback
  'http://localhost:11434/',
  'http://127.0.0.1:11434/',
  // Marveen dashboard API (local). The port follows WEB_PORT: a fixed 3420 here
  // blocked the agent's own dashboard once the install moved to another port.
  `http://localhost:${DASHBOARD_PORT}/`,
  `http://127.0.0.1:${DASHBOARD_PORT}/`,
]

// The quarantine tier.
//
// The block message tells the caller to fetch through the quarantine-reader
// sub-agent -- and until now this same hook blocked that sub-agent too, so the
// escape hatch the gate prescribed was one the gate closed (kanban #224).
//
// A sub-agent's PreToolUse payload carries two fields a main agent's does not:
// `agent_id` and `agent_type` (measured 2026-08-03, both key sets recorded in
// store/egress-blocked.log). `agent_type` is what separates the tiers.
//
// FAIL-CLOSED: only an exact `agent_type` match opens this tier. A missing,
// empty, unknown or misspelled value is treated as a main agent, i.e. blocked.
// A mistake here can only deny a fetch, never grant one.
//
// The domain list mirrors the one in the sub-agent's own definition
// (templates/sub-agents/quarantine-reader.md). That copy is a promise the
// sub-agent makes to itself in its prompt; this one is enforcement. Keep them
// in step -- and when they disagree, this file is the one that decides.
const QUARANTINE_AGENT_TYPE = 'quarantine-reader'

// `path` (optional) narrows a domain to the URLs the sub-agent's definition
// actually promises. Reddit is the reason it exists: the definition allows RSS
// feeds only, and hostname matching alone would hand over the entire site.
const QUARANTINE_DOMAINS = [
  { domain: 'status.anthropic.com' },
  { domain: 'status.claude.com' },
  { domain: 'feeds.feedburner.com' },
  { domain: 'rss.arxiv.org' },
  { domain: 'export.arxiv.org' },
  { domain: 'hnrss.org' },
  { domain: 'feeds.arstechnica.com' },
  { domain: 'techcrunch.com' },
  { domain: 'feeds.reuters.com' },
  { domain: 'feeds.bbci.co.uk' },
  { domain: 'www.reddit.com', path: (p) => p.endsWith('.rss') },
]

// The reader's posture is an OPERATOR SWITCH, not a code-level decision.
//
// First proposed as an unconditional inversion (allowlist -> denylist); the
// upstream owner asked for both behaviours to coexist behind one setting, with
// the allowlist as the default, and his reasoning is recorded here because it
// is the contract this code keeps: the two failure directions are not
// symmetric. An allowlist that errs refuses a legitimate read, and a human
// hears about it. A denylist that errs lets something in, and nobody hears
// anything. A default that silently flips on update pushes every install
// toward the quieter failure without anyone having decided that -- so the
// flip must be an explicit, per-install operator act:
//
//   store/egress-allowlist.json: { "quarantine_reader_posture": "denylist" }
//
// Anything other than the literal string "denylist" (missing key, missing
// file, typo, wrong type) means "allowlist" -- the stricter, louder default.
// An untouched install behaves byte-identically to before this change.
//
// Why the open posture is defensible for THIS tier and no other: the posture
// applies only to the quarantine-reader, a sub-agent whose definition grants
// it `tools: WebFetch` and nothing else. No shell, no filesystem, no store
// access -- it holds nothing to leak, and what it returns is data the caller
// must wrap before use. The main agent's own WebFetch path is unaffected by
// the switch in either position.
//
// What the deny rules below must stop in the open posture is therefore NOT
// exfiltration but SSRF: a poisoned page talking the caller into aiming the
// reader at our own network. Hence literal internal hosts, internal-only name
// suffixes, and private/link-local/loopback address literals.
const QUARANTINE_DENY_HOSTS = new Set([
  'localhost',
  'localhost.localdomain',
  'broadcasthost',
  '0.0.0.0',
  '::',
  '::1',
  '[::]',
  '[::1]',
  'metadata.google.internal',
  'instance-data',
])

const QUARANTINE_DENY_SUFFIXES = ['.localhost', '.local', '.internal', '.home.arpa', '.lan']

// Private / link-local / loopback IPv4 literals, plus the cloud metadata
// address (169.254.169.254 is inside the link-local range and thus covered).
function isPrivateIPv4(host) {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host)
  if (!m) return false
  const [a, b] = [Number(m[1]), Number(m[2])]
  if (m.slice(1).some((x) => Number(x) > 255)) return true // malformed -> deny
  if (a === 10 || a === 127 || a === 0) return true
  if (a === 172 && b >= 16 && b <= 31) return true
  if (a === 192 && b === 168) return true
  if (a === 169 && b === 254) return true
  if (a === 100 && b >= 64 && b <= 127) return true // CGNAT
  return false
}

// IPv6 loopback / unique-local / link-local, with or without brackets.
function isPrivateIPv6(host) {
  const h = host.replace(/^\[|\]$/g, '').toLowerCase()
  if (!h.includes(':')) return false
  if (h === '::1' || h === '::') return true
  if (h.startsWith('fc') || h.startsWith('fd')) return true // unique-local
  if (h.startsWith('fe80')) return true // link-local
  // IPv4-mapped (::ffff:10.0.0.1) -- reuse the v4 rules on the tail.
  const tail = h.split(':').pop() ?? ''
  if (tail.includes('.')) return isPrivateIPv4(tail)
  return false
}

// KNOWN LIMIT, stated rather than papered over: this checks the hostname as
// written. A public name that RESOLVES to a private address (DNS rebinding)
// still passes, because the hook sees the URL, not the socket. Closing that
// needs resolution at fetch time, which is not this layer's job.
export function isQuarantineDenied(url) {
  let parsed
  try {
    parsed = new URL(url)
  } catch {
    return true // unparseable -> deny
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return true
  const host = parsed.hostname.toLowerCase()
  if (!host) return true
  if (QUARANTINE_DENY_HOSTS.has(host)) return true
  if (QUARANTINE_DENY_SUFFIXES.some((s) => host.endsWith(s))) return true
  if (isPrivateIPv4(host)) return true
  if (isPrivateIPv6(host)) return true
  return false
}

// Multi-tenant hosting suffixes (Viktor 13106). Under these, each subdomain is
// a different customer's site, so the "exact host or any subdomain" rule turns
// one operator entry such as `vercel.app` into every app hosted there --
// attacker-written content included. An operator entry that equals one of
// these, or is a parent of one (`amazonaws.com` covers `s3.amazonaws.com`), is
// ignored by both runtime tiers. A single tenant (`myapp.vercel.app`) is still
// accepted: its subdomains belong to the same owner. The scaffold drops the
// same entries from the reader's rendered prompt; keep the two lists equal
// (src/web/agent-scaffold.ts MULTI_TENANT_SUFFIXES, parity test).
// The open (denylist) reader posture is not narrowed by this list: it is an
// operator opt-in to read any public host.
export const MULTI_TENANT_SUFFIXES = [
  'appspot.com',
  'azurewebsites.net',
  'blogspot.com',
  'cloudfront.net',
  'firebaseapp.com',
  'fly.dev',
  'github.io',
  'gitlab.io',
  'glitch.me',
  'herokuapp.com',
  'netlify.app',
  'ngrok-free.app',
  'ngrok.io',
  'notion.site',
  'onrender.com',
  'pages.dev',
  's3.amazonaws.com',
  'substack.com',
  'supabase.co',
  'trycloudflare.com',
  'vercel.app',
  'web.app',
  'webflow.io',
  'wixsite.com',
  'workers.dev',
]

export function opensMultiTenantSuffix(entry) {
  const d = String(entry ?? '').trim().toLowerCase()
  if (!d) return false
  return MULTI_TENANT_SUFFIXES.some((s) => s === d || s.endsWith('.' + d))
}

// The shape a runtime entry needs before it may match anything (Viktor 13122
// L1): at least two labels, no empty label, no leading or trailing dot. A
// trailing dot (`vercel.app.`) slipped past the suffix check and then matched
// `https://evil.vercel.app./`; a single label (`org`) opened a whole TLD. The
// scaffold's isPublicFetchHost already refuses both, so without this the
// prompt and the gate disagreed again. Shape only: a LAN name or an address
// literal in `domains` is still the operator's call for the main agent.
export function isUsableRuntimeDomain(entry) {
  const d = String(entry ?? '')
  const labels = d.split('.')
  if (labels.length < 2 || labels.some((l) => l === '')) return false
  return !opensMultiTenantSuffix(d)
}

// The reader-side host filter, a mirror of isPublicFetchHost in
// src/web/agent-scaffold.ts (Viktor 13125 LOW). The scaffold already drops an
// internal or address-literal entry from the reader's rendered prompt, but in
// the allowlist posture the gate took every quarantine_domains entry as is, so
// `10.0.85.98` or `localhost.localdomain` there let the reader fetch inward:
// the same prompt/gate disagreement L1 closed, one tier over. The quarantine
// tier now applies this to the operator's entries AND to the requested host
// before granting `quarantine`; the open posture applies it to every host
// (isDeniedToOpenReader). `domains` (the main agent's) stays the operator's
// call.
// Keep the two copies equal (parity test in quarantine-allowlist-render).
export function isPublicFetchHost(value) {
  const host = value.trim().toLowerCase()
  if (!host || host.length > 253) return false
  if (/[^a-z0-9.-]/.test(host)) return false          // scheme, port, path, wildcard, space
  if (host.startsWith('.') || host.endsWith('.')) return false
  if (host.startsWith('-') || host.endsWith('-')) return false
  if (/^\d+(\.\d+)*$/.test(host)) return false        // IPv4 literal or a bare number
  const labels = host.split('.')
  if (labels.length < 2) return false                 // single label: localhost and friends
  if (labels.some((l) => !l || l.length > 63 || l.startsWith('-') || l.endsWith('-'))) return false
  // `example` is reserved (RFC 2606, RFC 6761) and never public; before it was
  // listed, `nas.home.example` (Viktor 13125) passed this filter.
  const INTERNAL_SUFFIX = ['local', 'internal', 'localdomain', 'lan', 'intranet', 'home', 'arpa', 'test', 'invalid', 'localhost', 'svc', 'cluster', 'example']
  if (INTERNAL_SUFFIX.includes(labels[labels.length - 1])) return false
  // A public NAME can still resolve inward. Wildcard-DNS services (nip.io,
  // sslip.io and friends) encode the address in the name itself, so
  // 127.0.0.1.nip.io and 192-168-1-50.sslip.io pass every check above and then
  // resolve to loopback/RFC1918. Reaching them needs an allowlist entry, so
  // this is defence-in-depth rather than an open door -- but it is the same
  // class of bypass the literal check already rejects, and it costs one pass.
  if (labels.some((l) => isInwardDashQuad(l))) return false
  if (labels.some((l) => isInwardPackedLabel(l))) return false
  if (labels.some((l) => isInwardIPv6Label(l))) return false
  for (let i = 0; i + 3 < labels.length; i++) {
    if (isInwardQuad(labels[i], labels[i + 1], labels[i + 2], labels[i + 3])) return false
  }
  return true
}

// True for an IPv4 that points back at us or into a private network. Kept
// narrow on purpose: a PUBLIC address embedded in a name is not a bypass of
// the loopback/RFC1918 guard, and rejecting every numeric label would break
// legitimate hosts.
function isInwardIPv4(o) {
  if (o.length !== 4 || o.some((n) => !Number.isInteger(n) || n < 0 || n > 255)) return false
  const [a, b] = o
  if (a === 0 || a === 127) return true                      // this-host, loopback
  if (a === 10) return true                                  // RFC1918
  if (a === 172 && b >= 16 && b <= 31) return true           // RFC1918
  if (a === 192 && b === 168) return true                    // RFC1918
  if (a === 169 && b === 254) return true                    // link-local, cloud metadata
  if (a === 100 && b >= 64 && b <= 127) return true          // CGNAT
  return false
}

/* One part of a dotted address, the way inet_aton reads it: 0x-prefixed is
   hex, a leading zero is OCTAL, everything else decimal. This is not pedantry:
   the resolvers behind the wildcard-DNS services use the same rules, so
   0177.0.0.1.nip.io answers with 127.0.0.1 while a decimal-only parser sees
   four harmless-looking labels. */
function inetAtonPart(part) {
  if (/^0[xX][0-9a-fA-F]{1,8}$/.test(part)) return parseInt(part.slice(2), 16)
  if (/^0[0-7]{1,11}$/.test(part)) return parseInt(part, 8)
  if (/^(0|[1-9]\d{0,9})$/.test(part)) return parseInt(part, 10)
  return null
}

function isInwardQuad(a, b, c, d) {
  const parts = [a, b, c, d].map(inetAtonPart)
  if (parts.some((n) => n == null)) return false
  return isInwardIPv4(parts)
}

/* A single label that IS the whole address, packed into one number:
   2130706433.nip.io and 7f000001.nip.io both resolve to 127.0.0.1.

   The lower bound is deliberate. Anything under 2^24 does not encode all four
   octets, and treating it as an address would reject 123.example.com, which is
   an ordinary public name and exactly what the guard promises not to touch.
   Nothing is lost by the bound: those values decode into 0.0.0.0/8, which is
   not routable anyway. */
const PACKED_MIN = 0x01000000
function isInwardPackedLabel(label) {
  let n = null
  if (/^0[xX][0-9a-fA-F]{1,8}$/.test(label)) n = parseInt(label.slice(2), 16)
  else if (/^0[0-7]{9,12}$/.test(label)) n = parseInt(label, 8)
  else if (/^\d{8,10}$/.test(label)) n = Number(label)
  else if (/^[0-9a-fA-F]{8}$/.test(label) && /[a-fA-F]/.test(label)) n = parseInt(label, 16)
  if (n == null || !Number.isInteger(n) || n < PACKED_MIN || n > 0xffffffff) return false
  return isInwardIPv4([(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255])
}

/* sslip.io writes IPv6 with dashes instead of colons, so 0--1.sslip.io is ::1.
   The dotted-quad and dash-quad checks above never see it, because it is
   neither. */
function isInwardIPv6Label(label) {
  if (!/^[0-9a-fA-F-]+$/.test(label) || !label.includes('-')) return false
  const addr = label.replace(/-/g, ':')
  if ((addr.match(/::/g) ?? []).length > 1) return false
  const groups = addr.split(':')
  if (groups.length < 3 || groups.length > 8) return false
  if (groups.some((g) => g !== '' && !/^[0-9a-fA-F]{1,4}$/.test(g))) return false
  const filled = expandIPv6(groups)
  if (filled == null) return false
  const [h0] = filled
  if (filled.every((g, i) => g === (i === 7 ? 1 : 0))) return true // ::1 loopback
  if (filled.every((g) => g === 0)) return true // :: unspecified
  if ((h0 & 0xffc0) === 0xfe80) return true // fe80::/10 link-local
  if ((h0 & 0xfe00) === 0xfc00) return true // fc00::/7 unique local
  // ::ffff:a.b.c.d and ::a.b.c.d carry an IPv4 inside
  if (filled.slice(0, 5).every((g) => g === 0) && (filled[5] === 0xffff || filled[5] === 0)) {
    const v4 = [(filled[6] >>> 8) & 255, filled[6] & 255, (filled[7] >>> 8) & 255, filled[7] & 255]
    if (isInwardIPv4(v4)) return true
  }
  return false
}

/** '::' filled out to eight 16-bit groups, or null when it does not fit. */
function expandIPv6(groups) {
  const gapAt = groups.indexOf('')
  let parts
  if (gapAt === -1) {
    if (groups.length !== 8) return null
    parts = groups
  } else {
    const head = groups.slice(0, gapAt).filter((g) => g !== '')
    const tail = groups.slice(gapAt + 1).filter((g) => g !== '')
    const missing = 8 - head.length - tail.length
    if (missing < 1) return null
    parts = [...head, ...Array(missing).fill('0'), ...tail]
  }
  return parts.map((g) => parseInt(g || '0', 16))
}

function isInwardDashQuad(label) {
  const m = label.match(/^(\d{1,3})-(\d{1,3})-(\d{1,3})-(\d{1,3})$/)
  if (!m) return false
  return isInwardIPv4(m.slice(1).map((p) => parseInt(p, 10)))
}

// What the open reader posture refuses: the literal deny rules, plus any host
// the reader-side filter would not list (Viktor 13166). isQuarantineDenied
// reads the hostname as written, so wildcard-DNS names that encode an inward
// address (`127.0.0.1.nip.io`, `192-168-1-50.sslip.io`) and reserved names
// (`nas.home.example`) passed it. Accepted side effect: a public IP literal is
// refused too, which a reader source has no reason to be. This is the
// condition for switching an install to the denylist posture.
function isDeniedToOpenReader(url) {
  if (isQuarantineDenied(url)) return true // also the unparseable case
  return !isPublicFetchHost(new URL(url).hostname)
}

function matchesQuarantineDomain(url, extraDomains = []) {
  let parsed
  try {
    parsed = new URL(url)
  } catch {
    return false
  }
  const hostMatches = (d) => parsed.hostname === d || parsed.hostname.endsWith('.' + d)
  for (const entry of QUARANTINE_DOMAINS) {
    if (!hostMatches(entry.domain)) continue
    if (entry.path && !entry.path(parsed.pathname)) return false
    return true
  }
  // Operator additions carry no path rule: an entry someone typed into the
  // store file is a deliberate act, and second-guessing its shape here would
  // only make the file's behaviour harder to predict.
  return extraDomains.some(hostMatches)
}

// Load the runtime allowlist from store/egress-allowlist.json.
// FAIL-OPEN on the file: missing or malformed -> empty lists, NOT an error.
// The caller must still apply the built-in ALLOWED_PREFIXES.
export function loadRuntimeAllowlist() {
  try {
    const raw = readFileSync(RUNTIME_ALLOWLIST_PATH, 'utf-8')
    const parsed = JSON.parse(raw)
    return {
      domains: Array.isArray(parsed.domains) ? parsed.domains.filter((d) => typeof d === 'string') : [],
      prefixes: Array.isArray(parsed.prefixes) ? parsed.prefixes.filter((p) => typeof p === 'string') : [],
      // Operator-managed extension of the QUARANTINE tier. Reachable ONLY by
      // the quarantine-reader sub-agent -- putting a domain here does not open
      // it to the main agent, which is the whole point of the split.
      quarantineDomains: Array.isArray(parsed.quarantine_domains)
        ? parsed.quarantine_domains.filter((d) => typeof d === 'string')
        : [],
      // The reader-posture switch. ONLY the literal string "denylist" opens
      // the reader; any other value -- absent key, typo, wrong type -- is the
      // allowlist default. Fail-closed to the louder failure direction.
      quarantinePosture: parsed.quarantine_reader_posture === 'denylist' ? 'denylist' : 'allowlist',
    }
  } catch {
    // Missing file or JSON parse error: treat as empty, never propagate.
    return { domains: [], prefixes: [], quarantineDomains: [], quarantinePosture: 'allowlist' }
  }
}

// Pure decision, with the tier that decided it.
//
// `runtimeList` is the decoded store/egress-allowlist.json (or any equivalent
// object) and `agentType` is the payload's `agent_type` -- empty for a main
// agent. Keeping file I/O out of this function makes it fully unit-testable
// without touching the filesystem.
//
// The tier is returned because the quarantine tier is the security-relevant
// exception and its grants are audited: a fetch nobody can see is a hole
// nobody can find.
//
// Domain matching uses URL-parsed hostname ONLY, not string-contains, to prevent
// bypasses like `https://evil.com/?x=docs.anthropic.com` matching the domain
// "docs.anthropic.com" via a simple includes() check.
export function egressDecision(
  toolName,
  toolInput,
  runtimeList = { domains: [], prefixes: [], quarantineDomains: [] },
  agentType = '',
) {
  if (toolName !== 'WebFetch') return { blocked: false, tier: 'not-webfetch' }
  const url = String(toolInput?.url ?? '')
  if (!url) return { blocked: false, tier: 'no-url' }

  const openReader = String(agentType ?? '') === QUARANTINE_AGENT_TYPE
    && (runtimeList.quarantinePosture ?? 'allowlist') === 'denylist'

  // 0. Reader deny rules, BEFORE every allow path -- in the denylist posture
  //    only, so the default posture stays byte-identical to the pre-switch
  //    gate. Order matters and was found by a test, not by reading: the
  //    built-in prefixes include this install's own dashboard
  //    (http://localhost:PORT/), so with the deny rules consulted only in
  //    step 4 an open reader would have reached localhost through step 1 --
  //    the one address the deny rules exist to refuse. An allowlist that
  //    predates the switch must not be able to re-open what the open posture
  //    walls off.
  if (openReader && isDeniedToOpenReader(url)) {
    return { blocked: true, tier: 'quarantine-denied' }
  }

  // 1. Built-in prefix check (startsWith is correct here: the prefix already
  //    includes the trailing slash so a prefix-extension attack is impossible,
  //    e.g. 'https://api.github.com.evil.com/' does not start with
  //    'https://api.github.com/').
  if (ALLOWED_PREFIXES.some((prefix) => url.startsWith(prefix))) return { blocked: false, tier: 'builtin' }

  // 2. Runtime prefix check.
  const rtPrefixes = runtimeList.prefixes ?? []
  if (rtPrefixes.some((p) => url.startsWith(p))) return { blocked: false, tier: 'runtime-prefix' }

  // 3. Runtime domain check: parse the URL to extract a verified hostname.
  //    URL parsing fails on non-URLs -> block (fail-safe).
  const rtDomains = (runtimeList.domains ?? []).filter(isUsableRuntimeDomain)
  if (rtDomains.length > 0) {
    let hostname
    try {
      hostname = new URL(url).hostname
    } catch {
      // Unparseable URL: block, don't throw.
      return { blocked: true, tier: 'unparseable' }
    }
    // Match exact hostname OR any subdomain (host.endsWith('.' + domain)).
    if (rtDomains.some((d) => hostname === d || hostname.endsWith('.' + d))) return { blocked: false, tier: 'runtime-domain' }
  }

  // 4. Quarantine tier -- the ONLY tier a main agent cannot reach. Exact
  //    agent_type match required (fail-closed: anything else falls through to
  //    the block below).
  //
  //    In the allowlist posture (the default) the named domains are the whole
  //    grant, exactly as before the switch existed. In the denylist posture
  //    two sub-cases, in this order:
  //    (a) the shipped feeds and operator additions -- allowed as before, so
  //        flipping the posture can never break a long-standing source;
  //    (b) anything else -- allowed UNLESS the deny rules catch it. The
  //        re-check is defence in depth: step 0 already refused denied URLs,
  //        and this keeps that true even if someone later reorders the steps.
  if (String(agentType ?? '') === QUARANTINE_AGENT_TYPE) {
    const qDomains = (runtimeList.quarantineDomains ?? [])
      .filter((d) => isUsableRuntimeDomain(d) && isPublicFetchHost(d))
    if (matchesQuarantineDomain(url, qDomains) && isPublicFetchHost(new URL(url).hostname)) {
      return { blocked: false, tier: 'quarantine' }
    }
    if (openReader) {
      if (!isDeniedToOpenReader(url)) return { blocked: false, tier: 'quarantine-open' }
      return { blocked: true, tier: 'quarantine-denied' }
    }
  }

  return { blocked: true, tier: 'none' }
}

// Back-compatible boolean form.
export function isEgressBlocked(toolName, toolInput, runtimeList, agentType) {
  return egressDecision(toolName, toolInput, runtimeList, agentType).blocked
}

// The payload's top-level FIELD NAMES, sorted -- never a value.
//
// This exists to answer one open question with data instead of a guess: does
// the PreToolUse payload carry anything that identifies the CALLER? The gate
// decides on the URL alone, so a main agent and a quarantine-reader sub-agent
// are indistinguishable to it, and the sub-agent is the escape hatch the block
// message itself prescribes -- which is why the RSS path is currently dead
// (kanban #224). A caller-aware tier can only be built on a field that is
// verified to exist; building it on an assumed one would produce a guard that
// looks like it protects and does not.
//
// Keys only, by construction: a value could carry a url, a prompt, or a
// secret, and this log is read casually. Nested objects contribute nothing but
// their own key.
export function payloadKeySignature(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return ''
  return Object.keys(payload).sort().join(',')
}

// `agentType` IS logged by value, unlike everything else in the payload. It is
// an agent-type name from a fixed set -- not content, not a url, not a secret
// -- and without it a denied sub-agent call cannot be told apart from a denied
// main-agent one, which is exactly the distinction this log now exists to make.
// Verifying this gate by hand -- piping a payload into it after an allowlist
// change -- writes an ALLOWED_QUARANTINE line for a request that never left the
// machine. fetch-budget.py then counts it against the source's daily allowance,
// and its own comment says the opposite: "Only fetches that actually left the
// machine count against a source." Measured 2026-08-28: seven such phantom
// lines, one on every domain approved that morning, and the caller read them
// back as real traffic before starting a sweep.
//
// EGRESS_GATE_SELFTEST=1 prefixes the log kind with SELFTEST_ so those lines
// are visibly not traffic. It NEVER touches the decision -- allow and deny come
// out exactly the same with it set or unset -- because a gate with a switch
// that changes what it permits is not a gate.
//
// If the variable is ever left set in a live session, real fetches log as
// SELFTEST_ and go uncounted. That fails quiet, so fetch-budget.py should say
// out loud when it skips SELFTEST_ lines rather than silently reporting less.
const SELFTEST = process.env.EGRESS_GATE_SELFTEST === '1'

function logLine(kind, url, detail, keys = '', agentType = '') {
  try {
    mkdirSync(join(REPO_ROOT, 'store'), { recursive: true })
    const ts = new Date().toISOString()
    if (SELFTEST) kind = `SELFTEST_${kind}`
    const keyPart = keys ? ` payload_keys="${keys}"` : ''
    const agentPart = agentType ? ` agent_type="${agentType}"` : ''
    appendFileSync(EGRESS_BLOCK_LOG, `${ts} ${kind} url="${url}" ${detail}${agentPart}${keyPart}\n`, 'utf-8')
  } catch {
    // Never let log failure cascade into blocking the agent process itself.
  }
}

const BLOCK_MESSAGE =
  'Egress TILTOTT (egress-gate hook). Ez az URL nem szerepel a fő ágens WebFetch ' +
  'engedélylistáján. Külső web-tartalom (RSS, dokumentáció, cikkek, ismeretlen API-k) ' +
  'KIZÁRÓLAG a quarantine-reader sub-ágensen keresztül kérhető le: ' +
  'Agent({ subagent_type: "quarantine-reader", prompt: `FETCH {"url":"...","nonce":"..."}` }). ' +
  'A letiltott hívás rögzítve lett a store/egress-blocked.log fájlban. ' +
  'Ha ez a hívás jogos, az operátor jóváhagyhatja: adja hozzá az URL-t vagy domain-t a ' +
  'store/egress-allowlist.json fájlhoz ({ "domains": ["example.com"] } vagy ' +
  '{ "prefixes": ["https://example.com/api/"] }), majd futtassa újra a WebFetch hívást.'

function allow() { process.exit(0) }

function deny(reason) {
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'deny',
      permissionDecisionReason: reason,
    },
  }))
  process.exit(0)
}

function isInvokedDirectly() {
  try {
    const self = realpathSync(fileURLToPath(import.meta.url))
    const entry = process.argv[1] ? realpathSync(process.argv[1]) : ''
    return self === entry
  } catch {
    return false
  }
}

if (isInvokedDirectly()) {
  let payload
  try {
    payload = JSON.parse(readFileSync(0, 'utf-8'))
  } catch {
    allow() // malformed/empty input must never block the agent
  }
  const url = String(payload?.tool_input?.url ?? '')
  const agentType = String(payload?.agent_type ?? '')
  const runtimeList = loadRuntimeAllowlist()
  const decision = egressDecision(payload?.tool_name, payload?.tool_input, runtimeList, agentType)
  if (decision.blocked) {
    logLine('BLOCKED', url, 'reason="not on egress allowlist"', payloadKeySignature(payload), agentType)
    deny(BLOCK_MESSAGE)
  }
  // Audited, not silent: the quarantine tier is the one grant a main agent
  // cannot obtain, so every use of it leaves a line next to the denials. The
  // other tiers are the ordinary allowlist and stay quiet.
  if (decision.tier === 'quarantine') {
    logLine('ALLOWED_QUARANTINE', url, 'reason="quarantine-reader tier"', '', agentType)
  }
  allow()
}
