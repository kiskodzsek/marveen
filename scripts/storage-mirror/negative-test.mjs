#!/usr/bin/env node
// negative-test.mjs -- proves the mirror UPLOADER key cannot destroy anything
// (plan 8/F1, Viktor 15269 + 15290/5).
//
//   negative-test.mjs --bucket NAME --other-bucket NAME [--prod-canary]
//                     [--endpoint URL] [--region R]
//   env: MIRROR_S3_ACCESS_KEY_ID / MIRROR_S3_SECRET_ACCESS_KEY (the uploader key)
//
// It uploads ONE synthetic canary object of its own (canary/negtest-<time>-<rand>.bin,
// random bytes, no customer data), which the bucket's default Object Lock then
// holds, and attempts every forbidden operation against that canary or the bucket.
// A probe passes only on HTTP 403 WITH the S3 error code AccessDenied (Viktor
// 15290 M1). A 403 SignatureDoesNotMatch / InvalidAccessKeyId means the request
// never reached the permission check (a signing bug would read as green), so it
// is a FAIL marked "signing"; anything else (2xx, 404, 405, 409, 501, another
// code) is a FAIL for a human to read.
//
// The probe bucket must be versioned with NO default retention, and the key's
// policy the same as the live one (Viktor 15290 I1): under a lock, the
// version/retention/legal-hold calls are refused by the lock as well, and the
// run would prove the WORM setting, not the key's rights. --prod-canary on the
// live bucket proves exactly that weaker thing, and leaves a 32-byte canary that
// cannot be deleted until its lock runs out.
//
// --prod-canary is for the live mirror bucket: then only the object-level probes
// run, on the canary alone, plus the other-bucket probe. The bucket-level probes
// (lifecycle, versioning, policy, lock config, ACL, DeleteBucket) cannot be pointed
// at one object, so they run only on the throwaway test bucket: if a denial were
// missing, a probe there must not be able to change the live configuration.
// Without --prod-canary the bucket name must carry "test" or "probe" as a
// separate token (marabel-mirror-test, probe.bucket; not "latest"). In both modes
// the bucket name is typed back on the tty before the first request.
//
// This is the ONE tool that sends DELETE to a mirror bucket, and only for the
// canary key or the bucket itself, each expected to be refused.

import { createHash, randomBytes } from 'node:crypto'
import { openSync, closeSync, createReadStream } from 'node:fs'
import { createInterface } from 'node:readline'
import { fileURLToPath } from 'node:url'
import { MirrorError, readCapped, redact, s3Client } from './lib.mjs'

export const TEST_BUCKET_RE = /(^|[-_.])(test|probe)([-_.]|$)/i
const SIGNING_CODES = new Set(['SignatureDoesNotMatch', 'InvalidAccessKeyId', 'AuthorizationHeaderMalformed', 'InvalidSecurity', 'RequestTimeTooSkewed', 'MissingSecurityHeader', 'ExpiredToken', 'InvalidToken'])

// The S3 error code of a response (<Error><Code>...</Code>), '' when none.
async function errorCode(res) {
  const text = (await readCapped(res, 8192).catch(() => Buffer.alloc(0))).toString('utf8')
  return /<Code>([A-Za-z0-9.]{1,64})<\/Code>/.exec(text)?.[1] ?? ''
}

function denied(probe, status, code) {
  const pass = status === 403 && code === 'AccessDenied'
  const r = { probe, expect: '403 AccessDenied', status, code, pass }
  if (!pass && status === 403 && SIGNING_CODES.has(code)) r.reason = 'signing'
  return r
}

const md5b64 = (s) => createHash('md5').update(s).digest('base64')
const xml = (s) => ({ body: s, headers: { 'content-type': 'application/xml', 'content-md5': md5b64(s) } })

// Each probe: [name, level, method, key-or-'' (bucket), query, extra].
// level 'object' targets the canary only; 'bucket' targets the bucket.
export function probes(canaryKey, versionId, now = new Date()) {
  const in1d = new Date(now.getTime() + 86_400_000).toISOString().replace(/\.\d{3}Z$/, 'Z')
  const retention = xml(`<Retention><Mode>GOVERNANCE</Mode><RetainUntilDate>${in1d}</RetainUntilDate></Retention>`)
  return [
    ['DeleteObjectVersion', 'object', 'DELETE', canaryKey, { versionId }, {}],
    ['DeleteObject', 'object', 'DELETE', canaryKey, {}, {}],
    ['PutObjectRetention', 'object', 'PUT', canaryKey, { retention: '', versionId }, retention],
    ['PutObjectRetention-bypass', 'object', 'PUT', canaryKey, { retention: '', versionId },
      { body: retention.body, headers: { ...retention.headers, 'x-amz-bypass-governance-retention': 'true' } }],
    ['PutObjectLegalHold', 'object', 'PUT', canaryKey, { 'legal-hold': '', versionId }, xml('<LegalHold><Status>OFF</Status></LegalHold>')],
    ['PutObjectAcl', 'object', 'PUT', canaryKey, { acl: '' }, { headers: { 'x-amz-acl': 'public-read' } }],
    ['PutBucketLifecycle', 'bucket', 'PUT', '', { lifecycle: '' },
      xml('<LifecycleConfiguration><Rule><ID>negtest</ID><Status>Enabled</Status><Filter><Prefix>canary/</Prefix></Filter><Expiration><Days>1</Days></Expiration></Rule></LifecycleConfiguration>')],
    ['PutBucketVersioning', 'bucket', 'PUT', '', { versioning: '' }, xml('<VersioningConfiguration><Status>Suspended</Status></VersioningConfiguration>')],
    ['PutBucketPolicy', 'bucket', 'PUT', '', { policy: '' },
      { body: '{"Version":"2023-04-17","Statement":[]}', headers: { 'content-type': 'application/json' } }],
    ['PutObjectLockConfiguration', 'bucket', 'PUT', '', { 'object-lock': '' },
      xml('<ObjectLockConfiguration><ObjectLockEnabled>Enabled</ObjectLockEnabled><Rule><DefaultRetention><Mode>GOVERNANCE</Mode><Days>1</Days></DefaultRetention></Rule></ObjectLockConfiguration>')],
    ['PutBucketAcl', 'bucket', 'PUT', '', { acl: '' }, { headers: { 'x-amz-acl': 'public-read' } }],
    ['DeleteBucketPolicy', 'bucket', 'DELETE', '', { policy: '' }, {}],
    ['DeleteBucketLifecycle', 'bucket', 'DELETE', '', { lifecycle: '' }, {}],
    ['DeleteBucket', 'bucket', 'DELETE', '', {}, {}],
  ]
}

// deps: { s3 (target bucket, write methods allowed), other (other bucket), log, now, rand }
export async function runNegativeTest({ prodCanary, bucket }, deps) {
  const { s3, other, log, confirm } = deps
  if (!prodCanary && !TEST_BUCKET_RE.test(bucket)) throw new MirrorError('not_a_test_bucket', 'use --prod-canary for the live bucket')
  if (!(await confirm(bucket, !!prodCanary))) throw new MirrorError('not_confirmed')
  const now = deps.now ?? new Date()
  const stamp = now.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z')
  const canaryKey = `canary/negtest-${stamp}-${(deps.rand ?? (() => randomBytes(6).toString('hex')))()}.bin`
  const results = []

  const put = await s3.request('PUT', canaryKey, { body: randomBytes(32), headers: { 'content-type': 'application/octet-stream' } })
  const versionId = put.headers.get('x-amz-version-id') || ''
  results.push({ probe: 'PutObject(canary)', expect: 200, status: put.status, pass: put.status === 200 && !!versionId })
  if (put.status !== 200 || !versionId) {
    log('canary upload failed or bucket not versioned: no further probe runs')
    return { pass: false, canary: canaryKey, results }
  }
  const get = await s3.request('GET', canaryKey, { query: { versionId } })
  results.push({ probe: 'GetObject(canary)', expect: 200, status: get.status, pass: get.status === 200 })

  for (const [name, level, method, key, query, extra] of probes(canaryKey, versionId, now)) {
    if (prodCanary && level === 'bucket') continue
    const res = await s3.request(method, key, { query, headers: extra.headers ?? {}, body: extra.body ?? '' })
    results.push(denied(name, res.status, await errorCode(res)))
  }
  for (const [name, method] of [['OtherBucketPut', 'PUT'], ['OtherBucketList', 'GET']]) {
    const res = await other.request(method, method === 'PUT' ? canaryKey : '', method === 'PUT' ? { body: 'x' } : {})
    results.push(denied(name, res.status, await errorCode(res)))
  }
  // The canary must still be there, same version, after all of it.
  const after = await s3.request('HEAD', canaryKey, { query: { versionId } })
  results.push({ probe: 'HeadObject(canary, after)', expect: 200, status: after.status, pass: after.status === 200 })
  return { pass: results.every((r) => r.pass), canary: canaryKey, results }
}

async function confirmOnTty(bucket, prodCanary) {
  let fd
  try { fd = openSync('/dev/tty', 'r+') } catch { return false }
  const input = createReadStream(null, { fd, autoClose: false })
  const rl = createInterface({ input, output: process.stderr })
  const answer = await new Promise((resolve) => rl.question(
    `${prodCanary ? 'LIVE mirror bucket, canary-only probes. ' : ''}Type the bucket name (${bucket}) to start: `, resolve))
  rl.close()
  input.destroy()
  closeSync(fd)
  return answer.trim() === bucket
}

function parseArgs(argv) {
  const o = {}
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--prod-canary') o.prodCanary = true
    else if (['--bucket', '--other-bucket', '--endpoint', '--region'].includes(a) && i + 1 < argv.length) o[a.slice(2).replace(/-(\w)/g, (_, c) => c.toUpperCase())] = argv[++i]
    else throw new MirrorError('usage', `unknown or incomplete argument #${i + 1}`)
  }
  if (!o.bucket || !o.otherBucket) throw new MirrorError('usage', '--bucket and --other-bucket are required')
  return o
}

async function main() {
  const accessKeyId = process.env.MIRROR_S3_ACCESS_KEY_ID || ''
  const secretAccessKey = process.env.MIRROR_S3_SECRET_ACCESS_KEY || ''
  const secrets = [accessKeyId, secretAccessKey]
  try {
    const o = parseArgs(process.argv.slice(2))
    if (!accessKeyId || !secretAccessKey) throw new MirrorError('uploader_key_missing')
    const common = { endpoint: o.endpoint || 'https://s3.fr-par.scw.cloud', region: o.region || 'fr-par', accessKeyId, secretAccessKey }
    const methods = ['GET', 'HEAD', 'PUT', 'DELETE']
    const out = await runNegativeTest(o, {
      s3: s3Client({ ...common, bucket: o.bucket, allowedMethods: methods }),
      other: s3Client({ ...common, bucket: o.otherBucket, allowedMethods: methods }),
      log: (l) => process.stderr.write(`negative-test: ${l}\n`),
      confirm: confirmOnTty,
    })
    process.stdout.write(`${redact(JSON.stringify(out, null, 1), secrets)}\n`)
    process.exitCode = out.pass ? 0 : 1
  } catch (err) {
    process.stderr.write(`negative-test: FAILED ${redact(err instanceof MirrorError ? err.message : 'internal', secrets)}\n`)
    process.exitCode = 2
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) main()
