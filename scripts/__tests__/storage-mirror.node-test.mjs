// Tests for scripts/storage-mirror/ (restore.mjs, negative-test.mjs, lib.mjs).
// Dependency-free: `node --test scripts/__tests__/storage-mirror.node-test.mjs`.
// Not *.test.mjs on purpose: vitest's default include would collect it and fail on node:test.
// Synthetic data only: mocked S3 and Supabase, a fake age CLI
// (fixtures/storage-mirror/fake-age.mjs), no real key, no real customer file.

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdtempSync, writeFileSync, rmSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  signV4, pathProblem, parseManifest, mirrorKey, integrityProblem, redact, restoreContentType, s3Client, sha256hex, MirrorError,
  RESTORE_CONTENT_TYPES,
} from '../storage-mirror/lib.mjs'
import { runRestore, makeAgeDecrypt, makeSupabaseUpload, parseTarget, parseArgs } from '../storage-mirror/restore.mjs'
import { runNegativeTest } from '../storage-mirror/negative-test.mjs'

const FAKE_AGE = join(dirname(fileURLToPath(import.meta.url)), 'fixtures', 'storage-mirror', 'fake-age.mjs')
const ID1 = '11111111-1111-4111-8111-111111111111'
const ID2 = '22222222-2222-4222-8222-222222222222'
const ID3 = '33333333-3333-4333-8333-333333333333'
const md5 = (b) => createHash('md5').update(b).digest('hex')
const fakeEnc = (buf) => Buffer.concat([Buffer.from('FAKEAGE\n'), Buffer.from(Buffer.from(buf).toString('base64'))])
const fakeDec = async (buf) => {
  const s = buf.toString('utf8')
  if (!s.startsWith('FAKEAGE\n')) throw new MirrorError('decrypt_failed')
  return Buffer.from(s.slice(8), 'base64')
}
const rejectsCode = (p, code) => assert.rejects(p, (e) => e instanceof MirrorError && e.code === code)

// --- SigV4 ---------------------------------------------------------------

test('signV4 matches the AWS SigV4 test suite vector get-vanilla', () => {
  // https://docs.aws.amazon.com/general/latest/gr/signature-v4-test-suite.html (get-vanilla).
  // AKIDEXAMPLE and its secret are AWS's published example credentials.
  const r = signV4({
    method: 'GET', endpoint: 'https://example.amazonaws.com', path: '/', region: 'us-east-1', service: 'service',
    accessKeyId: 'AKIDEXAMPLE', secretAccessKey: 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY', now: new Date('2015-08-30T12:36:00Z'),
  })
  assert.equal(r.headers.authorization,
    'AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, SignedHeaders=host;x-amz-date, Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31')
})

test('signV4 for s3 signs the payload hash and a sorted sub-resource query', () => {
  const r = signV4({ method: 'PUT', endpoint: 'https://s3.fr-par.scw.cloud', path: '/b/k', query: { versionId: 'v1', retention: '' }, body: 'x', region: 'fr-par', accessKeyId: 'id', secretAccessKey: 's' })
  assert.equal(r.headers['x-amz-content-sha256'], createHash('sha256').update('x').digest('hex'))
  assert.equal(r.url, 'https://s3.fr-par.scw.cloud/b/k?retention=&versionId=v1')
  assert.match(r.headers.authorization, /SignedHeaders=host;x-amz-content-sha256;x-amz-date,/)
})

// --- untrusted manifest (Viktor 15290/1) ----------------------------------

test('pathProblem rejects traversal, absolute, control and oversized paths', () => {
  for (const p of ['', '../x', 'a/../b', 'a/./b', '/abs', 'a//b', 'a/', 'a\\b', 'a\u0000b', 'a\nb', 'a\u0085b', 'x'.repeat(1025), 'é.jpg']) {
    assert.notEqual(pathProblem(p), '', JSON.stringify(p))
  }
  for (const p of ['p1/photo 1.jpg', 'p1/ékezetes fotó.jpg', 'p1/a.b..c/d.webm', 'x'.repeat(1024)]) {
    assert.equal(pathProblem(p), '', JSON.stringify(p))
  }
})

const entry = (over = {}) => ({ id: ID1, bucket: 'project-photos', path: 'p1/a.jpg', etag: md5('aaa'), size: 3, tombstone: false, ...over })
const manifestOf = (objects, version = 1) => JSON.stringify({ version, generated_at: '2026-10-23T10:00:00Z', objects })

test('parseManifest fails the whole manifest on any bad entry, naming it by index only', () => {
  const bad = [
    [{ bucket: 'marketing-videos' }, 'bucket'],
    [{ bucket: 'other' }, 'bucket'],
    [{ id: 'not-a-uuid' }, 'id'],
    [{ path: '../../etc/passwd' }, 'path-dot-segment'],
    [{ size: -1 }, 'size'],
    [{ size: 300 * 1024 * 1024 }, 'size'],
    [{ tombstone: 'no' }, 'tombstone'],
    [{ tombstone: true, size: 5 }, 'tombstone-size'],
    [{ version_id: 'a b' }, 'version_id'],
    [{ content_type: 'image/jpeg\r\nx-evil: 1' }, 'content_type'],
    [{ content_type: 'x'.repeat(201) }, 'content_type'],
  ]
  for (const [over, why] of bad) {
    assert.throws(() => parseManifest(manifestOf([entry({ id: ID2, path: 'p1/ok.jpg' }), entry(over)])), (e) => {
      assert.equal(e.code, 'manifest_entry_invalid')
      assert.match(e.message, new RegExp(`objects\\[1\\] ${why}$`))
      assert.doesNotMatch(e.message, /etc|passwd|a\.jpg/)
      return true
    })
  }
  assert.throws(() => parseManifest(manifestOf([entry(), entry({ id: ID2 })])), /duplicate-path/)
  assert.throws(() => parseManifest(manifestOf([entry(), entry({ path: 'p1/b.jpg' })])), /duplicate-id/)
  assert.throws(() => parseManifest(manifestOf([entry()], 2)), (e) => e.code === 'manifest_version')
  assert.throws(() => parseManifest('{nope'), (e) => e.code === 'manifest_not_json')
})

test('mirrorKey is built from bucket and UUID, never from the path', () => {
  assert.equal(mirrorKey(entry({ path: 'evil/../../x' })), `project-photos/${ID1}.age`)
})

test('integrityProblem: size, md5 eTag, multipart eTag', () => {
  const b = Buffer.from('aaa')
  assert.equal(integrityProblem(entry(), b), '')
  assert.equal(integrityProblem(entry({ etag: `"${md5('aaa')}"` }), b), '')
  assert.equal(integrityProblem(entry({ size: 4 }), b), 'size_mismatch')
  assert.equal(integrityProblem(entry({ etag: md5('bbb') }), b), 'etag_mismatch')
  assert.equal(integrityProblem(entry({ etag: `${md5('aaa')}-2` }), b), 'etag_unchecked')
})

// --- secrets out of the output (Viktor 15290/3) ---------------------------

test('redact strips given secrets, auth headers, bearer values and signatures', () => {
  const key = 'synthetic-target-key-0001'
  const out = redact(`err ${key} Authorization: AWS4 abc Bearer zzz apikey=${key} Signature=deadbeef Credential=ID/x`, [key])
  assert.doesNotMatch(out, /synthetic-target-key|zzz|deadbeef|AWS4 abc|ID\/x/)
})

// --- mocks ------------------------------------------------------------------

function mockS3(objects, { status = {} } = {}) {
  const calls = []
  const fetchImpl = async (url, init) => {
    const u = new URL(url)
    calls.push({ method: init.method, path: u.pathname, search: u.search, redirect: init.redirect })
    const key = decodeURIComponent(u.pathname.split('/').slice(2).join('/'))
    if (status[key]) return new Response('', { status: status[key] })
    const o = objects[key]
    if (!o) return new Response('<Error><Code>NoSuchKey</Code></Error>', { status: 404 })
    return new Response(o.body, { status: 200, headers: o.headers ?? {} })
  }
  const client = s3Client({ endpoint: 'https://s3.fr-par.scw.cloud', region: 'fr-par', bucket: 'mirror', accessKeyId: 'kid', secretAccessKey: 'ksecret', fetchImpl })
  return { client, calls }
}

const pin = (objects) => sha256hex(objects['manifest/latest.json.age'].body)

function mirrorWith(entries, payloads) {
  const objects = { 'manifest/latest.json.age': { body: fakeEnc(manifestOf(entries)) } }
  for (const e of entries) if (payloads[e.id] !== undefined) objects[mirrorKey(e)] = { body: fakeEnc(payloads[e.id]) }
  return objects
}

const TARGET = 'https://abcdefghijklmnopqrst.supabase.co'
const PROD = 'https://gvipgmezmglireuizxpn.supabase.co'
const three = [
  entry(),
  entry({ id: ID2, bucket: 'storyteller-audio', path: 'p2/r.webm', etag: md5('bbbb'), size: 4 }),
  entry({ id: ID3, path: 'p1/gone.jpg', etag: '', size: 0, tombstone: true }),
]
const payloads = { [ID1]: 'aaa', [ID2]: 'bbbb' }

function deps(s3, { confirm = true, uploadResult = 'uploaded' } = {}) {
  const uploads = []
  const logs = []
  return {
    uploads, logs,
    d: {
      s3, decrypt: fakeDec, log: (l) => logs.push(l), confirm: async () => confirm,
      upload: async (e, bytes, o) => { uploads.push({ bucket: e.bucket, path: e.path, bytes: bytes.toString(), ...o }); return uploadResult },
    },
  }
}

// --- runRestore ----------------------------------------------------------------

test('plan mode (default) reads only the manifest and writes nothing', async () => {
  const { client, calls } = mockS3(mirrorWith(three, payloads))
  const { d, uploads } = deps(client)
  const s = await runRestore({ targetUrl: TARGET }, d)
  assert.equal(s.mode, 'plan')
  assert.equal(s.selected, 2)
  assert.equal(s.tombstones_skipped, 1)
  assert.deepEqual(s.plan, { 'project-photos': { objects: 1, bytes: 3 }, 'storyteller-audio': { objects: 1, bytes: 4 } })
  assert.deepEqual(calls.map((c) => c.path), ['/mirror/manifest/latest.json.age'])
  assert.equal(uploads.length, 0)
})

test('verify mode downloads, decrypts and checks, still without writing', async () => {
  const { client, calls } = mockS3(mirrorWith(three, payloads))
  const { d, uploads } = deps(client)
  const s = await runRestore({ targetUrl: TARGET, verify: true }, d)
  assert.equal(s.verified, 2)
  assert.equal(s.errors.length, 0)
  assert.equal(uploads.length, 0)
  assert.ok(calls.some((c) => c.path === `/mirror/project-photos/${ID1}.age`))
})

test('apply restores to the original bucket and path, no overwrite unless asked', async () => {
  const { client } = mockS3(mirrorWith(three, payloads))
  const { d, uploads } = deps(client)
  const s = await runRestore({ targetUrl: TARGET, apply: true }, d)
  assert.equal(s.uploaded, 2)
  assert.deepEqual(uploads, [
    { bucket: 'project-photos', path: 'p1/a.jpg', bytes: 'aaa', overwrite: false },
    { bucket: 'storyteller-audio', path: 'p2/r.webm', bytes: 'bbbb', overwrite: false },
  ])
  const o2 = mirrorWith(three, payloads)
  const { client: c2 } = mockS3(o2)
  const r2 = deps(c2)
  await runRestore({ targetUrl: TARGET, apply: true, overwrite: true, manifestSha256: pin(o2) }, r2.d)
  assert.ok(r2.uploads.every((u) => u.overwrite === true))
})

test('apply: an existing object is counted, not overwritten', async () => {
  const { client } = mockS3(mirrorWith(three, payloads))
  const { d } = deps(client, { uploadResult: 'exists' })
  const s = await runRestore({ targetUrl: TARGET, apply: true }, d)
  assert.equal(s.exists_skipped, 2)
  assert.equal(s.uploaded, 0)
})

test('bucket and prefix filters', async () => {
  const { client } = mockS3(mirrorWith(three, payloads))
  const { d, uploads } = deps(client)
  await runRestore({ targetUrl: TARGET, apply: true, bucket: 'storyteller-audio' }, d)
  assert.deepEqual(uploads.map((u) => u.path), ['p2/r.webm'])
  const { client: c2 } = mockS3(mirrorWith(three, payloads))
  const r2 = deps(c2)
  await runRestore({ targetUrl: TARGET, apply: true, prefix: 'p1/' }, r2.d)
  assert.deepEqual(r2.uploads.map((u) => u.path), ['p1/a.jpg'])
  await rejectsCode(runRestore({ targetUrl: TARGET, bucket: 'marketing-videos' }, r2.d), 'bucket_not_allowed')
  await rejectsCode(runRestore({ targetUrl: TARGET, prefix: '../' }, r2.d), 'prefix_invalid')
})

test('production target: apply needs --i-know-this-is-prod, a pinned manifest and the typed confirmation', async () => {
  const objects = mirrorWith(three, payloads)
  const { client } = mockS3(objects)
  const { d, uploads } = deps(client)
  const sha = pin(objects)
  await rejectsCode(runRestore({ targetUrl: PROD, apply: true, manifestSha256: sha }, d), 'target_is_prod')
  await rejectsCode(runRestore({ targetUrl: PROD, apply: true, prodOk: true }, d), 'manifest_sha256_required')
  const plan = await runRestore({ targetUrl: PROD }, d)
  assert.equal(plan.target_is_prod, true)
  assert.equal(plan.manifest_sha256, sha)
  assert.equal(plan.manifest_pinned, false)
  const refused = deps(client, { confirm: false })
  await rejectsCode(runRestore({ targetUrl: PROD, apply: true, prodOk: true, manifestSha256: sha }, refused.d), 'not_confirmed')
  assert.equal(uploads.length + refused.uploads.length, 0)
  const ok = deps(client)
  const s = await runRestore({ targetUrl: PROD, apply: true, prodOk: true, manifestSha256: sha }, ok.d)
  assert.equal(s.uploaded, 2)
  assert.equal(s.manifest_pinned, true)
})

test('manifest pin (Viktor M2): --overwrite needs it anywhere, a wrong hash stops before decrypting', async () => {
  const objects = mirrorWith(three, payloads)
  const { client, calls } = mockS3(objects)
  let decrypted = 0
  const { d, uploads } = deps(client)
  d.decrypt = async (b) => { decrypted++; return fakeDec(b) }
  await rejectsCode(runRestore({ targetUrl: TARGET, apply: true, overwrite: true }, d), 'manifest_sha256_required')
  assert.equal(calls.length, 0)
  await rejectsCode(runRestore({ targetUrl: TARGET, apply: true, manifestSha256: 'f'.repeat(64) }, d), 'manifest_sha256_mismatch')
  await rejectsCode(runRestore({ targetUrl: TARGET, verify: true, manifestSha256: 'f'.repeat(64) }, d), 'manifest_sha256_mismatch')
  await rejectsCode(runRestore({ targetUrl: TARGET, manifestSha256: 'XYZ' }, d), 'manifest_sha256_invalid')
  assert.equal(decrypted, 0)
  assert.equal(uploads.length, 0)
  // A forged manifest with matching forged objects: only the pin catches it.
  const forged = mirrorWith([entry({ etag: md5('evil'), size: 4 })], { [ID1]: 'evil' })
  const f = mockS3(forged)
  await rejectsCode(runRestore({ targetUrl: TARGET, apply: true, overwrite: true, manifestSha256: pin(objects) }, deps(f.client).d), 'manifest_sha256_mismatch')
})

test('a non-production target also needs the typed confirmation', async () => {
  const { client } = mockS3(mirrorWith(three, payloads))
  const { d, uploads } = deps(client, { confirm: false })
  await rejectsCode(runRestore({ targetUrl: TARGET, apply: true }, d), 'not_confirmed')
  assert.equal(uploads.length, 0)
})

test('mismatch with the manifest is an error and nothing is uploaded for it', async () => {
  const forged = [entry({ size: 3, etag: md5('aaa') }), entry({ id: ID2, path: 'p1/b.jpg', size: 4, etag: md5('bbbb') })]
  const { client } = mockS3(mirrorWith(forged, { [ID1]: 'aaaa', [ID2]: 'cccc' }))
  const { d, uploads } = deps(client)
  const s = await runRestore({ targetUrl: TARGET, apply: true }, d)
  assert.deepEqual(s.errors, [{ index: 0, code: 'size_mismatch' }, { index: 1, code: 'etag_mismatch' }])
  assert.equal(uploads.length, 0)
})

test('a tombstone where the manifest expects data, a missing object and a 403 are errors', async () => {
  const entries = [entry(), entry({ id: ID2, path: 'p1/b.jpg' }), entry({ id: ID3, path: 'p1/c.jpg' })]
  const objects = mirrorWith(entries, { [ID1]: 'aaa' })
  objects[mirrorKey(entries[1])] = { body: '', headers: { 'x-amz-meta-tombstone': '1' } }
  const { client } = mockS3(objects, { status: { [mirrorKey(entries[2])]: 403 } })
  const { d, uploads } = deps(client)
  const s = await runRestore({ targetUrl: TARGET, apply: true }, d)
  assert.deepEqual(s.errors, [{ index: 1, code: 'unexpected_tombstone' }, { index: 2, code: 's3_403' }])
  assert.equal(uploads.length, 1)
})

test('a version_id in the manifest is fetched exactly', async () => {
  const entries = [entry({ version_id: 'v-123' })]
  const { client, calls } = mockS3(mirrorWith(entries, { [ID1]: 'aaa' }))
  await runRestore({ targetUrl: TARGET, verify: true }, deps(client).d)
  assert.ok(calls.some((c) => c.path === `/mirror/project-photos/${ID1}.age` && c.search === '?versionId=v-123'))
})

test('a forged oversized object is refused before it is buffered', async () => {
  const entries = [entry({ size: 3 })]
  const { client } = mockS3(mirrorWith(entries, { [ID1]: 'a'.repeat(20000) }))
  const s = await runRestore({ targetUrl: TARGET, verify: true }, deps(client).d)
  assert.deepEqual(s.errors, [{ index: 0, code: 'too_large' }])
})

test('the restore never sends DELETE (or any write) to the mirror, and follows no redirect', async () => {
  const objects = mirrorWith(three, payloads)
  const { client, calls } = mockS3(objects)
  await runRestore({ targetUrl: TARGET, apply: true, overwrite: true, manifestSha256: pin(objects) }, deps(client).d)
  assert.ok(calls.length > 1)
  assert.ok(calls.every((c) => c.method === 'GET'))
  assert.ok(calls.every((c) => c.redirect === 'error'))
  await rejectsCode(client.request('DELETE', 'x'), 'method_not_allowed')
  await rejectsCode(client.request('PUT', 'x'), 'method_not_allowed')
})

test('no path or file name reaches the summary or the log', async () => {
  const { client } = mockS3(mirrorWith(three, { [ID1]: 'aaa' }))
  const { d, logs } = deps(client)
  const s = await runRestore({ targetUrl: TARGET, apply: true }, d)
  const text = JSON.stringify(s) + logs.join('\n')
  for (const p of ['p1/', 'p2/', 'a.jpg', 'r.webm', 'gone.jpg', ID1, ID2]) assert.ok(!text.includes(p), p)
})

test('restoreContentType: the bucket allowlist, parameters dropped, everything else octet-stream', () => {
  assert.equal(restoreContentType(entry({ content_type: 'image/jpeg' })), 'image/jpeg')
  assert.equal(restoreContentType(entry({ content_type: 'IMAGE/PNG' })), 'image/png')
  assert.equal(restoreContentType(entry({ bucket: 'storyteller-audio', content_type: 'audio/webm;codecs=opus' })), 'audio/webm')
  assert.equal(restoreContentType(entry({ bucket: 'project-print-assets', content_type: 'application/pdf' })), 'application/pdf')
  for (const ct of ['text/html', 'image/svg+xml', 'application/javascript', 'text/html; charset=utf-8', 'audio/webm', undefined]) {
    assert.equal(restoreContentType(entry({ content_type: ct })), 'application/octet-stream', String(ct))
  }
})

test('manifest key, target URL and argument checks', async () => {
  const { client } = mockS3({})
  await rejectsCode(runRestore({ targetUrl: TARGET, manifest: '../x' }, deps(client).d), 'manifest_key')
  await rejectsCode(runRestore({ targetUrl: TARGET }, deps(client).d), 'manifest_s3_404')
  assert.deepEqual(parseTarget(TARGET), { base: TARGET, ref: 'abcdefghijklmnopqrst' })
  assert.deepEqual(parseTarget('http://127.0.0.1:54321'), { base: 'http://127.0.0.1:54321', ref: 'local' })
  for (const bad of ['http://abcdefghijklmnopqrst.supabase.co', 'https://evil.example', `${TARGET}/storage`, 'https://abcdefghijklmnopqrst.supabase.co.evil.example']) {
    assert.throws(() => parseTarget(bad), (e) => e.code === 'target_url', bad)
  }
  const base = ['--mirror-bucket', 'm', '--target-url', TARGET, '--identity', 'id.age']
  assert.equal(parseArgs(base).apply, undefined)
  assert.throws(() => parseArgs([...base, '--apply']), /target-key-stdin/)
  assert.throws(() => parseArgs([...base, '--overwrite']), /only with --apply/)
  assert.throws(() => parseArgs(['--target-url', TARGET]), /required/)
})

// --- the real age plumbing (with the fake binary) ----------------------------

test('makeAgeDecrypt unlocks the identity once and passes it on fd 3, not argv or env', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'smirror-'))
  try {
    const idFile = join(dir, 'identity.age')
    writeFileSync(idFile, 'FAKE-PASSPHRASE-IDENTITY:AGE-SECRET-KEY-FAKE-SYNTHETIC', { mode: 0o600 })
    process.env.FAKE_AGE_IDENTITY = 'AGE-SECRET-KEY-FAKE-SYNTHETIC'
    const decrypt = await makeAgeDecrypt({ ageBin: FAKE_AGE, identityFile: idFile })
    assert.equal((await decrypt(fakeEnc('hello'), 100)).toString(), 'hello')
    assert.equal((await decrypt(fakeEnc('again'), 100)).toString(), 'again')
    await rejectsCode(decrypt(Buffer.from('garbage'), 100), 'decrypt_failed')
    await rejectsCode(decrypt(fakeEnc('x'.repeat(500)), 100), 'too_large')
    decrypt.wipe()
    await rejectsCode(decrypt(fakeEnc('hello'), 100), 'decrypt_failed')
    writeFileSync(idFile, 'AGE-SECRET-KEY-PLAINTEXT-NOT-ALLOWED')
    await rejectsCode(makeAgeDecrypt({ ageBin: FAKE_AGE, identityFile: idFile }), 'identity_unlock_failed')
    await rejectsCode(makeAgeDecrypt({ ageBin: join(dir, 'missing-age'), identityFile: idFile }), 'age_not_runnable')
  } finally {
    delete process.env.FAKE_AGE_IDENTITY
    rmSync(dir, { recursive: true, force: true })
  }
})

// --- Supabase upload -------------------------------------------------------------

test('makeSupabaseUpload: URL, headers, and the exists/other outcomes', async () => {
  const seen = []
  const reply = { status: 200, body: '' }
  const upload = makeSupabaseUpload({
    base: TARGET, key: 'synthetic-key',
    fetchImpl: async (url, init) => { seen.push({ url, init }); return new Response(reply.body, { status: reply.status }) },
  })
  const e = entry({ path: 'p1/ékezet fotó.jpg', content_type: 'image/jpeg' })
  assert.equal(await upload(e, Buffer.from('aaa'), { overwrite: false }), 'uploaded')
  assert.equal(seen[0].url, `${TARGET}/storage/v1/object/project-photos/p1/%C3%A9kezet%20fot%C3%B3.jpg`)
  assert.equal(seen[0].init.method, 'POST')
  assert.equal(seen[0].init.headers['x-upsert'], 'false')
  assert.equal(seen[0].init.headers['content-type'], 'image/jpeg')
  assert.equal(seen[0].init.redirect, 'error')
  assert.equal(await upload(entry({ content_type: 'text/html' }), Buffer.from('aaa'), { overwrite: true }), 'uploaded')
  assert.equal(seen[1].init.headers['x-upsert'], 'true')
  assert.equal(seen[1].init.headers['content-type'], 'application/octet-stream')
  Object.assign(reply, { status: 409, body: '' })
  assert.equal(await upload(entry(), Buffer.from('aaa'), { overwrite: false }), 'exists')
  Object.assign(reply, { status: 400, body: '{"statusCode":"409","error":"Duplicate","message":"The resource already exists"}' })
  assert.equal(await upload(entry(), Buffer.from('aaa'), { overwrite: false }), 'exists')
  Object.assign(reply, { status: 400, body: '{"error":"InvalidKey"}' })
  assert.equal(await upload(entry(), Buffer.from('aaa'), { overwrite: false }), 'upload_400')
  Object.assign(reply, { status: 403, body: '' })
  assert.equal(await upload(entry(), Buffer.from('aaa'), { overwrite: false }), 'upload_403')
})

// --- negative test --------------------------------------------------------------

function mockProbeS3({ allow = () => false, code = () => 'AccessDenied' } = {}) {
  const calls = []
  const mk = (bucket) => s3Client({
    endpoint: 'https://s3.fr-par.scw.cloud', region: 'fr-par', bucket, accessKeyId: 'kid', secretAccessKey: 'ks', allowedMethods: ['GET', 'HEAD', 'PUT', 'DELETE'],
    fetchImpl: async (url, init) => {
      const u = new URL(url)
      const c = { bucket, method: init.method, path: u.pathname, search: u.search }
      calls.push(c)
      const sub = u.search.replace(/^\?/, '')
      const isCanary = bucket.includes('test') && u.pathname.includes('/canary/')
      if (isCanary && init.method === 'PUT' && sub === '') return new Response('', { status: 200, headers: { 'x-amz-version-id': 'v1' } })
      if (isCanary && (init.method === 'GET' || init.method === 'HEAD') && sub === 'versionId=v1') return new Response('', { status: 200 })
      if (allow(c)) return new Response(null, { status: 204 })
      return new Response(`<Error><Code>${code(c)}</Code></Error>`, { status: 403 })
    },
  })
  return { calls, s3: mk('marabel-mirror-test'), other: mk('other-bucket') }
}

test('negative test passes when every forbidden call is a 403 and the canary survives', async () => {
  const m = mockProbeS3()
  const out = await runNegativeTest({ bucket: 'marabel-mirror-test' }, { s3: m.s3, other: m.other, log: () => {}, confirm: async () => true, rand: () => 'r', now: new Date('2026-10-23T11:00:00Z') })
  assert.equal(out.pass, true, JSON.stringify(out.results))
  assert.equal(out.canary, 'canary/negtest-20261023T110000Z-r.bin')
  const names = out.results.map((r) => r.probe)
  for (const n of ['DeleteObjectVersion', 'DeleteObject', 'PutObjectRetention', 'PutObjectLegalHold', 'PutBucketLifecycle', 'PutBucketVersioning', 'PutBucketPolicy', 'PutObjectLockConfiguration', 'DeleteBucket', 'OtherBucketPut', 'OtherBucketList']) {
    assert.ok(names.includes(n), n)
  }
  // Every object-level DELETE/PUT targets the canary only.
  for (const c of m.calls.filter((c) => c.bucket === 'marabel-mirror-test' && c.path !== '/marabel-mirror-test')) {
    assert.equal(c.path, '/marabel-mirror-test/canary/negtest-20261023T110000Z-r.bin')
  }
})

test('negative test fails when one forbidden call is not refused', async () => {
  const m = mockProbeS3({ allow: (c) => c.method === 'PUT' && c.search === '?versioning=' })
  const out = await runNegativeTest({ bucket: 'marabel-mirror-test' }, { s3: m.s3, other: m.other, log: () => {}, confirm: async () => true })
  assert.equal(out.pass, false)
  assert.deepEqual(out.results.filter((r) => !r.pass).map((r) => [r.probe, r.status]), [['PutBucketVersioning', 204]])
})

test('--prod-canary runs no bucket-level probe; a live bucket without it is refused', async () => {
  const m = mockProbeS3()
  // the mock's canary rule keys off "test" in the name; the live run is modelled by prodCanary
  const out = await runNegativeTest({ bucket: 'marabel-mirror-test', prodCanary: true }, { s3: m.s3, other: m.other, log: () => {}, confirm: async () => true })
  assert.equal(out.pass, true)
  assert.ok(m.calls.filter((c) => c.bucket === 'marabel-mirror-test').every((c) => c.path.includes('/canary/')))
  assert.ok(!out.results.some((r) => r.probe.startsWith('PutBucket') || r.probe === 'DeleteBucket'))
  await rejectsCode(runNegativeTest({ bucket: 'marabel-mirror' }, { s3: m.s3, other: m.other, log: () => {}, confirm: async () => true }), 'not_a_test_bucket')
})

test('negative test stops when the canary cannot be written or the bucket is not versioned', async () => {
  const calls = []
  const s3 = { request: async (method, key) => { calls.push(method); return new Response('', { status: 200 }) } }
  const out = await runNegativeTest({ bucket: 'x-test' }, { s3, other: s3, log: () => {}, confirm: async () => true })
  assert.equal(out.pass, false)
  assert.deepEqual(calls, ['PUT'])
})

test('a 403 that is not AccessDenied is a FAIL: a signing error must not read as green (Viktor M1)', async () => {
  const m = mockProbeS3({ code: (c) => (c.search === '?retention=&versionId=v1' ? 'SignatureDoesNotMatch' : c.search === '?legal-hold=&versionId=v1' ? 'InvalidRequest' : 'AccessDenied') })
  const out = await runNegativeTest({ bucket: 'marabel-mirror-test' }, { s3: m.s3, other: m.other, log: () => {}, confirm: async () => true })
  assert.equal(out.pass, false)
  const failed = out.results.filter((r) => !r.pass).map((r) => [r.probe, r.status, r.code, r.reason])
  assert.deepEqual(failed, [
    ['PutObjectRetention', 403, 'SignatureDoesNotMatch', 'signing'],
    ['PutObjectRetention-bypass', 403, 'SignatureDoesNotMatch', 'signing'],
    ['PutObjectLegalHold', 403, 'InvalidRequest', undefined],
  ])
  assert.ok(out.results.filter((r) => r.pass && r.expect !== 200).every((r) => r.code === 'AccessDenied'))
})

test('the test-bucket guard is token-bounded and the bucket name is typed back (Viktor L2)', async () => {
  const m = mockProbeS3()
  for (const b of ['marabel-latest', 'contest', 'marabel-mirror', 'probes-live']) {
    await rejectsCode(runNegativeTest({ bucket: b }, { s3: m.s3, other: m.other, log: () => {}, confirm: async () => true }), 'not_a_test_bucket')
  }
  let asked = ''
  await rejectsCode(runNegativeTest({ bucket: 'marabel-mirror-test' }, { s3: m.s3, other: m.other, log: () => {}, confirm: async (b) => { asked = b; return false } }), 'not_confirmed')
  assert.equal(asked, 'marabel-mirror-test')
  assert.equal(m.calls.length, 0)
})

// Viktor 15352 L3: the storyteller-audio allowlist must equal what Marabel's
// bucket accepts. The Marabel source is not in this repo, so the comparison runs
// when MARABEL_AUDIO_RECORDING_TS points at src/lib/audio-recording.ts (e.g.
// `git show origin/main:src/lib/audio-recording.ts > /tmp/x.ts`); the pinned
// list below runs always, so a change on either side is a deliberate edit.
test('storyteller-audio allowlist equals Marabel SUPPORTED_BASE_TYPES', (t) => {
  assert.deepEqual([...RESTORE_CONTENT_TYPES['storyteller-audio']].sort(),
    ['audio/aac', 'audio/mp4', 'audio/mpeg', 'audio/ogg', 'audio/webm', 'audio/x-m4a'])
  const src = process.env.MARABEL_AUDIO_RECORDING_TS
  if (!src) { t.skip('MARABEL_AUDIO_RECORDING_TS not set'); return }
  const body = /SUPPORTED_BASE_TYPES\s*=\s*new Set\(\[([^\]]*)\]/.exec(readFileSync(src, 'utf8'))
  assert.ok(body, 'SUPPORTED_BASE_TYPES not found')
  const marabel = [...body[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]).sort()
  assert.deepEqual([...RESTORE_CONTENT_TYPES['storyteller-audio']].sort(), marabel)
})
