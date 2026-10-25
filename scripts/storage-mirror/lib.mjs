// Shared, dependency-free pieces of the Marabel Storage mirror tools
// (restore.mjs, negative-test.mjs). Card 4e790bdd; plan:
// agents/kernel/reports/2026-10-23-marabel-storage-tukor-terv.md; security
// review: agents/viktor/reports/2026-10-23-marabel-storage-tukor-review.md
// (+ Viktor 15290 for the restore/negative-test requirements).
//
// The mirror itself is a Supabase Edge Function in the Marabel repo (Dave). It
// writes, per source object, one age-encrypted object at
// <bucket_id>/<storage.objects.id>.age into an S3 bucket with versioning and a
// COMPLIANCE Object Lock, and an encrypted manifest at manifest/latest.json.age
// (plus manifest/<UTC timestamp>.json.age). A source deletion becomes a 0-byte
// tombstone object (x-amz-meta-tombstone: 1), never a DELETE.
//
// Trust model (Viktor 15290/1): the manifest is NOT an authenticated input.
// age encrypts, it does not authenticate the sender, so anyone holding the
// leaked uploader key can write a forged manifest. Every field is validated
// here before it touches a URL or a write.

import { createHash, createHmac } from 'node:crypto'

export const ALLOWED_BUCKETS = Object.freeze(['project-photos', 'storyteller-audio', 'project-print-assets'])

// The Marabel production Supabase project (agents/pulzus/reports: "gvipgmezmglireuizxpn
// marabel, eu-central-1"). A project ref is public (it is in every client URL), not a
// secret. Writing to it needs --i-know-this-is-prod on top of --apply (Viktor 15290/4).
export const PROD_SUPABASE_REFS = Object.freeze(['gvipgmezmglireuizxpn'])

export const MANIFEST_VERSION = 1
export const LIMITS = Object.freeze({
  pathLength: 1024,
  etagLength: 128,
  manifestObjects: 200_000,
  manifestCipherBytes: 64 * 1024 * 1024,
  objectBytes: 200 * 1024 * 1024,
})

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const CONTROL_RE = /[\u0000-\u001f\u007f-\u009f]/
const VERSION_ID_RE = /^[A-Za-z0-9._-]{1,128}$/
const MD5_ETAG_RE = /^"?([0-9a-f]{32})"?$/

// What each bucket may be restored as (Viktor 15290 L3), from what Marabel
// itself uploads (agents/dave/repos/marabel origin/main):
//   project-photos      src/app/api/projects/[projectId]/photos/route.ts:45 (MIME_TYPES)
//   storyteller-audio   src/lib/audio-recording.ts:19-26 (SUPPORTED_BASE_TYPES, "what the private
//                       storyteller-audio bucket accepts")
//   project-print-assets  print-renderer: PRINT_ASSET_MEDIA_TYPE "application/pdf",
//                       package-store.ts:209 "application/json", print-photos.ts:130 image derivatives
// Anything else (text/html, image/svg+xml, a script...) is restored as
// application/octet-stream, so a forged manifest cannot plant a page that a
// browser would render from the project's storage origin.
export const RESTORE_CONTENT_TYPES = Object.freeze({
  'project-photos': ['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif'],
  'storyteller-audio': ['audio/webm', 'audio/mp4', 'audio/ogg', 'audio/mpeg', 'audio/aac', 'audio/x-m4a'],
  'project-print-assets': ['application/pdf', 'application/json', 'image/jpeg', 'image/png', 'image/webp'],
})

// The Content-Type an entry is restored with: the base type (parameters such
// as ";codecs=opus" dropped) when the bucket allows it, octet-stream otherwise.
export function restoreContentType(entry) {
  const base = String(entry.content_type ?? '').split(';')[0].trim().toLowerCase()
  return (RESTORE_CONTENT_TYPES[entry.bucket] ?? []).includes(base) ? base : 'application/octet-stream'
}

export class MirrorError extends Error {
  // code is the only thing the CLI prints: a fixed token, never a path or a body.
  constructor(code, detail = '') {
    super(detail ? `${code}: ${detail}` : code)
    this.code = code
  }
}

// --- path and manifest validation -----------------------------------------

// A storage path as Supabase stores it: relative, '/'-separated, no traversal.
// Returns the reason it is rejected, or '' when it is fine.
export function pathProblem(p) {
  if (typeof p !== 'string' || p.length === 0) return 'empty'
  if (p.length > LIMITS.pathLength) return 'too-long'
  if (CONTROL_RE.test(p)) return 'control-char'
  if (p.includes('\\')) return 'backslash'
  if (p.startsWith('/')) return 'leading-slash'
  if (p !== p.normalize('NFC')) return 'not-nfc'
  for (const seg of p.split('/')) {
    if (seg === '') return 'empty-segment'
    if (seg === '.' || seg === '..') return 'dot-segment'
  }
  return ''
}

// A prefix filter: the same rules as a path, and it may end with '/'.
export function prefixProblem(p) {
  return pathProblem(p.endsWith('/') ? p.slice(0, -1) : p)
}

function entryProblem(e) {
  if (!e || typeof e !== 'object' || Array.isArray(e)) return 'not-object'
  if (typeof e.id !== 'string' || !UUID_RE.test(e.id)) return 'id'
  if (!ALLOWED_BUCKETS.includes(e.bucket)) return 'bucket'
  const pp = pathProblem(e.path)
  if (pp) return `path-${pp}`
  if (typeof e.tombstone !== 'boolean') return 'tombstone'
  if (!Number.isSafeInteger(e.size) || e.size < 0 || e.size > LIMITS.objectBytes) return 'size'
  if (e.tombstone && e.size !== 0) return 'tombstone-size'
  if (typeof e.etag !== 'string' || e.etag.length > LIMITS.etagLength || CONTROL_RE.test(e.etag)) return 'etag'
  if (e.version_id !== undefined && (typeof e.version_id !== 'string' || !VERSION_ID_RE.test(e.version_id))) return 'version_id'
  // Shape only; what it may become is restoreContentType's decision.
  if (e.content_type !== undefined && (typeof e.content_type !== 'string' || e.content_type.length > 200 || CONTROL_RE.test(e.content_type))) return 'content_type'
  if (e.updated_at !== undefined && (typeof e.updated_at !== 'string' || Number.isNaN(Date.parse(e.updated_at)))) return 'updated_at'
  return ''
}

// Parses and validates a decrypted manifest. Any bad entry fails the WHOLE
// manifest: a forged manifest is a reason to stop, not to restore the rest.
// The error names the entry by index only, never by path.
export function parseManifest(text) {
  let doc
  try { doc = JSON.parse(text) } catch { throw new MirrorError('manifest_not_json') }
  if (!doc || typeof doc !== 'object' || Array.isArray(doc)) throw new MirrorError('manifest_shape')
  if (doc.version !== MANIFEST_VERSION) throw new MirrorError('manifest_version')
  if (!Array.isArray(doc.objects)) throw new MirrorError('manifest_shape')
  if (doc.objects.length > LIMITS.manifestObjects) throw new MirrorError('manifest_too_many')
  const seenId = new Set()
  const seenPath = new Set()
  doc.objects.forEach((e, i) => {
    const why = entryProblem(e)
    if (why) throw new MirrorError('manifest_entry_invalid', `objects[${i}] ${why}`)
    if (seenId.has(e.id)) throw new MirrorError('manifest_entry_invalid', `objects[${i}] duplicate-id`)
    const key = `${e.bucket}/${e.path}`
    if (seenPath.has(key)) throw new MirrorError('manifest_entry_invalid', `objects[${i}] duplicate-path`)
    seenId.add(e.id)
    seenPath.add(key)
  })
  return doc
}

// The mirror key of an entry. Built only from the validated bucket and UUID,
// never from the path, so a forged path cannot steer the S3 request.
export function mirrorKey(entry) {
  return `${entry.bucket}/${entry.id}.age`
}

// --- integrity -------------------------------------------------------------

// Size must match. The eTag is checked when it is a plain MD5 (a single-part
// upload); a multipart eTag ("<md5>-<n>") cannot be recomputed from the bytes,
// so only the size is checked and the caller counts it as etag_unchecked.
export function integrityProblem(entry, bytes) {
  if (bytes.length !== entry.size) return 'size_mismatch'
  const m = MD5_ETAG_RE.exec(entry.etag)
  if (!m) return 'etag_unchecked'
  const md5 = createHash('md5').update(bytes).digest('hex')
  return md5 === m[1] ? '' : 'etag_mismatch'
}

// --- secrets out of every message -------------------------------------------

// Replaces every given secret, and anything shaped like an auth header, in a
// string. Used on every error before it reaches stdout/stderr (Viktor 15290/3).
export function redact(text, secrets = []) {
  let s = String(text)
  for (const v of secrets) {
    if (typeof v === 'string' && v.length >= 4) s = s.split(v).join('[REDACTED]')
  }
  s = s.replace(/(authorization|apikey|x-amz-security-token)(["'\s:=]+)[^\s"',;]+(\s+[^\s"',;]+)?/gi, '$1$2[REDACTED]')
  s = s.replace(/\bBearer\s+\S+/g, 'Bearer [REDACTED]')
  s = s.replace(/(Signature|Credential)=[^\s,&]+/g, '$1=[REDACTED]')
  return s
}

// --- AWS Signature Version 4 (S3 path-style) --------------------------------
// https://docs.aws.amazon.com/IAM/latest/UserGuide/create-signed-request.html

export function sha256hex(data) { return createHash('sha256').update(data).digest('hex') }
function hmac(key, data) { return createHmac('sha256', key).update(data).digest() }

// RFC 3986 unreserved characters stay, everything else is %XX (S3 rules).
export function uriEncode(s, keepSlash) {
  let out = ''
  for (const ch of Buffer.from(String(s), 'utf8')) {
    const c = String.fromCharCode(ch)
    if (/[A-Za-z0-9\-._~]/.test(c) || (keepSlash && c === '/')) out += c
    else out += '%' + ch.toString(16).toUpperCase().padStart(2, '0')
  }
  return out
}

function amzDates(now) {
  const iso = now.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '')
  return { amzDate: iso, dateStamp: iso.slice(0, 8) }
}

// Returns { url, headers } for one request. `query` is an object; a flag
// sub-resource (?retention) is { retention: '' }. `body` is a Buffer or string.
export function signV4({ method, endpoint, path, query = {}, headers = {}, body = '', region, service = 's3', accessKeyId, secretAccessKey, now = new Date() }) {
  const u = new URL(endpoint)
  const { amzDate, dateStamp } = amzDates(now)
  const payloadHash = sha256hex(body)
  const h = {}
  for (const [k, v] of Object.entries(headers)) h[k.toLowerCase()] = String(v).trim()
  h.host = u.host
  h['x-amz-date'] = amzDate
  if (service === 's3') h['x-amz-content-sha256'] = payloadHash
  const signedNames = Object.keys(h).sort()
  const canonicalHeaders = signedNames.map((k) => `${k}:${h[k]}\n`).join('')
  const signedHeaders = signedNames.join(';')
  const canonicalQuery = Object.keys(query).sort()
    .map((k) => `${uriEncode(k, false)}=${uriEncode(query[k], false)}`).join('&')
  const canonicalUri = uriEncode(path, true)
  const canonicalRequest = [method, canonicalUri, canonicalQuery, canonicalHeaders, signedHeaders, payloadHash].join('\n')
  const scope = `${dateStamp}/${region}/${service}/aws4_request`
  const stringToSign = ['AWS4-HMAC-SHA256', amzDate, scope, sha256hex(canonicalRequest)].join('\n')
  const kSigning = hmac(hmac(hmac(hmac(`AWS4${secretAccessKey}`, dateStamp), region), service), 'aws4_request')
  const signature = createHmac('sha256', kSigning).update(stringToSign).digest('hex')
  delete h.host // fetch sets it from the URL
  h.authorization = `AWS4-HMAC-SHA256 Credential=${accessKeyId}/${scope}, SignedHeaders=${signedHeaders}, Signature=${signature}`
  const url = `${u.origin}${canonicalUri}${canonicalQuery ? `?${canonicalQuery}` : ''}`
  return { url, headers: h, canonicalRequest }
}

// --- S3 client (read side for restore, probes for the negative test) --------

export function s3Client({ endpoint, region, bucket, accessKeyId, secretAccessKey, fetchImpl = fetch, allowedMethods = ['GET', 'HEAD'] }) {
  const secrets = [accessKeyId, secretAccessKey]
  async function request(method, key, { query = {}, headers = {}, body = '' } = {}) {
    // The method allowlist is the code-level guarantee that the restore tool
    // never sends DELETE to the mirror (Viktor 15290/6).
    if (!allowedMethods.includes(method)) throw new MirrorError('method_not_allowed', method)
    const path = key === '' ? `/${bucket}` : `/${bucket}/${key}`
    const signed = signV4({ method, endpoint, path, query, headers, body, region, accessKeyId, secretAccessKey })
    let res
    try {
      // redirect: 'error' -- a redirect must not carry the signed request (or,
      // on the Supabase side, the apikey header) to another origin (Viktor 15290 L1).
      res = await fetchImpl(signed.url, { method, headers: signed.headers, body: method === 'GET' || method === 'HEAD' ? undefined : body, redirect: 'error' })
    } catch (err) {
      throw new MirrorError('s3_network', redact(err?.cause?.code || err?.name || 'error', secrets))
    }
    return res
  }
  return { request, secrets, bucket }
}

// Reads a response body with a hard byte cap, so a forged size cannot make us
// buffer gigabytes.
export async function readCapped(res, cap) {
  const len = Number(res.headers.get('content-length'))
  if (Number.isFinite(len) && len > cap) throw new MirrorError('too_large')
  if (!res.body) return Buffer.alloc(0)
  const chunks = []
  let total = 0
  for await (const chunk of res.body) {
    total += chunk.length
    if (total > cap) throw new MirrorError('too_large')
    chunks.push(Buffer.from(chunk))
  }
  return Buffer.concat(chunks)
}
