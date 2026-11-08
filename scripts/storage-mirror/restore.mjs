#!/usr/bin/env node
// restore.mjs -- puts Marabel Storage objects back from the encrypted mirror.
//
//   restore.mjs --mirror-bucket NAME --target-url https://<ref>.supabase.co --identity FILE
//               [--manifest manifest/latest.json.age] [--bucket B] [--prefix P]
//               [--manifest-sha256 HEX] [--verify]
//               [--apply [--overwrite] [--i-know-this-is-prod] --target-key-stdin]
//
// Without --apply nothing is written anywhere (Viktor 15290/4): the default run
// reads and checks the manifest and prints the plan; --verify also downloads,
// decrypts and checks every selected object, still without writing.
//
// Where each secret comes from, and where it never goes (Viktor 15290/2-3):
//   - mirror READ key: env MIRROR_S3_READ_ACCESS_KEY_ID / MIRROR_S3_READ_SECRET_ACCESS_KEY
//     (Patrik creates it for the restore and revokes it after, plan 3.2);
//   - age identity: a passphrase-protected file (age -p). Its PATH is an argument,
//     its passphrase is typed on the tty when age asks, never argv or env. The
//     decrypted identity lives in this process's memory only and reaches each age
//     child on a pipe (fd 3), never on disk;
//   - target service-role key: stdin (--target-key-stdin), piped by Pulzus.
// Decrypted file contents are never written to disk: age's stdout goes straight
// into the upload body. Output is counts, bytes and error codes; file names and
// paths are customer data and are never printed (entries are named by index).
//
// The manifest's authenticity (Viktor 15290 M2): age does not authenticate, so
// a leaked uploader key can write a manifest AND matching objects, and the
// size/MD5 check would pass on forged data. The Edge Function therefore stores
// the sha256 of each manifest ciphertext in a DB row that the S3 key cannot
// reach; --manifest-sha256 pins the run to it. It is REQUIRED for --apply on the
// production project and for every --overwrite. Prefer the timestamped manifest
// from before an incident over manifest/latest.json.age.

import { spawn } from 'node:child_process'
import { openSync, closeSync, createReadStream } from 'node:fs'
import { createInterface } from 'node:readline'
import { fileURLToPath } from 'node:url'
import {
  ALLOWED_BUCKETS, PROD_SUPABASE_REFS, LIMITS, MirrorError,
  parseManifest, mirrorKey, integrityProblem, prefixProblem, redact, readCapped, restoreContentType, s3Client, sha256hex, uriEncode,
} from './lib.mjs'

const MANIFEST_KEY_RE = /^manifest\/(latest|\d{8}T\d{6}Z)\.json\.age$/
const SHA256_RE = /^[0-9a-f]{64}$/
const MAX_ERRORS = 50

// https://<20 lowercase alnum>.supabase.co, or a local stack on 127.0.0.1/localhost.
export function parseTarget(url) {
  let u
  try { u = new URL(url) } catch { throw new MirrorError('target_url') }
  if (u.pathname !== '/' || u.search || u.hash || u.username || u.password) throw new MirrorError('target_url')
  const m = /^([a-z0-9]{20})\.supabase\.co$/.exec(u.hostname)
  if (u.protocol === 'https:' && m && !u.port) return { base: u.origin, ref: m[1] }
  if (u.protocol === 'http:' && (u.hostname === '127.0.0.1' || u.hostname === 'localhost')) return { base: u.origin, ref: 'local' }
  throw new MirrorError('target_url')
}

// age ciphertext is the plaintext plus a header (~200 bytes per recipient) and
// 16 bytes per 64 KiB chunk; the slack keeps a forged size from opening the cap.
function cipherCap(size) {
  return size + Math.ceil(size / 65536) * 16 + 4096
}

export async function runRestore(opts, deps) {
  const { s3, decrypt, upload, confirm, log } = deps
  const manifestKey = opts.manifest || 'manifest/latest.json.age'
  if (!MANIFEST_KEY_RE.test(manifestKey)) throw new MirrorError('manifest_key')
  if (opts.bucket !== undefined && !ALLOWED_BUCKETS.includes(opts.bucket)) throw new MirrorError('bucket_not_allowed')
  if (opts.prefix !== undefined && prefixProblem(opts.prefix)) throw new MirrorError('prefix_invalid')
  const maxBytes = Math.min(opts.maxObjectBytes ?? LIMITS.objectBytes, LIMITS.objectBytes)
  const target = parseTarget(opts.targetUrl)
  const isProd = PROD_SUPABASE_REFS.includes(target.ref)
  if (opts.apply && isProd && !opts.prodOk) throw new MirrorError('target_is_prod', 'add --i-know-this-is-prod')
  if (opts.manifestSha256 !== undefined && !SHA256_RE.test(opts.manifestSha256)) throw new MirrorError('manifest_sha256_invalid')
  if (opts.apply && (isProd || opts.overwrite) && !opts.manifestSha256) {
    throw new MirrorError('manifest_sha256_required', 'production or --overwrite: pin the manifest with --manifest-sha256')
  }

  const mres = await s3.request('GET', manifestKey)
  if (mres.status !== 200) throw new MirrorError(`manifest_s3_${mres.status}`)
  const cipher = await readCapped(mres, LIMITS.manifestCipherBytes)
  const manifestSha256 = sha256hex(cipher)
  // Checked on the ciphertext, before anything of it is decrypted or parsed.
  if (opts.manifestSha256 && manifestSha256 !== opts.manifestSha256) throw new MirrorError('manifest_sha256_mismatch')
  const manifest = parseManifest((await decrypt(cipher, LIMITS.manifestCipherBytes)).toString('utf8'))

  const selected = []
  let tombstones = 0
  manifest.objects.forEach((e, index) => {
    if (opts.bucket !== undefined && e.bucket !== opts.bucket) return
    if (opts.prefix !== undefined && !e.path.startsWith(opts.prefix)) return
    if (e.tombstone) { tombstones++; return }
    selected.push({ e, index })
  })
  const plan = {}
  for (const { e } of selected) {
    plan[e.bucket] ??= { objects: 0, bytes: 0 }
    plan[e.bucket].objects++
    plan[e.bucket].bytes += e.size
  }
  const summary = {
    mode: opts.apply ? 'apply' : opts.verify ? 'verify' : 'plan',
    target_ref: target.ref, target_is_prod: isProd, manifest_sha256: manifestSha256, manifest_pinned: !!opts.manifestSha256,
    manifest_objects: manifest.objects.length, selected: selected.length, tombstones_skipped: tombstones, plan,
    verified: 0, uploaded: 0, exists_skipped: 0, etag_unchecked: 0, errors: [],
  }
  log(`plan: ${JSON.stringify({ target_ref: target.ref, target_is_prod: isProd, manifest_sha256: manifestSha256, manifest_pinned: !!opts.manifestSha256, selected: selected.length, tombstones_skipped: tombstones, plan })}`)
  if (!opts.apply && !opts.verify) return summary

  if (opts.apply && !(await confirm(target.ref, isProd))) throw new MirrorError('not_confirmed')

  for (const { e, index } of selected) {
    if (summary.errors.length >= MAX_ERRORS) { summary.aborted = 'too_many_errors'; break }
    const fail = (code) => summary.errors.push({ index, code })
    try {
      const query = e.version_id ? { versionId: e.version_id } : {}
      const res = await s3.request('GET', mirrorKey(e), { query })
      if (res.status !== 200) { fail(`s3_${res.status}`); continue }
      if (res.headers.get('x-amz-meta-tombstone') === '1') { fail('unexpected_tombstone'); continue }
      const plain = await decrypt(await readCapped(res, cipherCap(e.size)), maxBytes)
      const why = integrityProblem(e, plain)
      if (why === 'etag_unchecked') summary.etag_unchecked++
      else if (why) { fail(why); continue }
      summary.verified++
      if (!opts.apply) continue
      const outcome = await upload(e, plain, { overwrite: !!opts.overwrite })
      if (outcome === 'uploaded') summary.uploaded++
      else if (outcome === 'exists') summary.exists_skipped++
      else fail(outcome)
    } catch (err) {
      fail(err instanceof MirrorError ? err.code : 'internal')
    }
  }
  return summary
}

// --- real dependencies -------------------------------------------------------

function runAge(ageBin, args, { input, extraFd, cap }) {
  return new Promise((resolve, reject) => {
    const stdio = ['pipe', 'pipe', 'pipe']
    if (extraFd) stdio.push('pipe')
    const child = spawn(ageBin, args, { stdio })
    const out = []
    let total = 0
    let over = false
    child.stdout.on('data', (c) => {
      total += c.length
      if (total > cap) { over = true; child.kill('SIGKILL'); return }
      out.push(c)
    })
    child.stderr.resume() // age's own message; not printed, it may name the input
    child.on('error', () => reject(new MirrorError('age_not_runnable')))
    child.on('close', (code) => {
      if (over) return reject(new MirrorError('too_large'))
      if (code !== 0) return reject(new MirrorError('decrypt_failed'))
      resolve(Buffer.concat(out))
    })
    // An age that exits early (bad input) closes these pipes: EPIPE is then
    // expected, and the exit code above reports the failure.
    if (extraFd) { child.stdio[3].on('error', () => {}); child.stdio[3].end(extraFd) }
    child.stdin.on('error', () => {})
    child.stdin.end(input)
  })
}

// Unlocks the passphrase-protected identity ONCE (age prompts on the tty), so
// the passphrase is not asked per object, and returns a decrypt function.
export async function makeAgeDecrypt({ ageBin = 'age', identityFile }) {
  const identity = await new Promise((resolve, reject) => {
    const child = spawn(ageBin, ['-d', identityFile], { stdio: ['ignore', 'pipe', 'inherit'] })
    const out = []
    child.stdout.on('data', (c) => out.push(c))
    child.on('error', () => reject(new MirrorError('age_not_runnable')))
    child.on('close', (code) => {
      const identity = Buffer.concat(out)
      for (const c of out) c.fill(0) // the chunks too, not only the joined copy (Viktor 15290 I2)
      if (code === 0) resolve(identity)
      else { identity.fill(0); reject(new MirrorError('identity_unlock_failed')) }
    })
  })
  const decrypt = (cipher, cap) => runAge(ageBin, ['-d', '-i', '/dev/fd/3'], { input: cipher, extraFd: identity, cap })
  decrypt.wipe = () => identity.fill(0)
  return decrypt
}

export function makeSupabaseUpload({ base, key, fetchImpl = fetch }) {
  return async (entry, bytes, { overwrite }) => {
    const url = `${base}/storage/v1/object/${uriEncode(entry.bucket, false)}/${uriEncode(entry.path, true)}`
    let res
    try {
      res = await fetchImpl(url, {
        method: 'POST',
        headers: {
          authorization: `Bearer ${key}`,
          apikey: key,
          'content-type': restoreContentType(entry),
          'x-upsert': overwrite ? 'true' : 'false',
        },
        body: bytes,
        redirect: 'error',
      })
    } catch {
      return 'upload_network'
    }
    if (res.status === 200) return 'uploaded'
    // An existing object: 409 per the error-code reference, 400 "already exists"
    // per the standard-uploads guide (both: supabase.com/docs/guides/storage).
    if (res.status === 409) return 'exists'
    if (res.status === 400) {
      const text = (await readCapped(res, 8192).catch(() => Buffer.alloc(0))).toString('utf8')
      if (/already exists|duplicate/i.test(text)) return 'exists'
    }
    return `upload_${res.status}`
  }
}

async function confirmOnTty(ref, isProd) {
  let fd
  try { fd = openSync('/dev/tty', 'r+') } catch { return false }
  const input = createReadStream(null, { fd, autoClose: false })
  const rl = createInterface({ input, output: process.stderr })
  const answer = await new Promise((resolve) => rl.question(
    `${isProd ? 'PRODUCTION project. ' : ''}Type the target project ref (${ref}) to write to it: `, resolve))
  rl.close()
  input.destroy()
  closeSync(fd)
  return answer.trim() === ref
}

async function readStdin() {
  const chunks = []
  for await (const c of process.stdin) chunks.push(c)
  return Buffer.concat(chunks).toString('utf8').trim()
}

export function parseArgs(argv) {
  const o = {}
  const flags = { '--apply': 'apply', '--verify': 'verify', '--overwrite': 'overwrite', '--i-know-this-is-prod': 'prodOk', '--target-key-stdin': 'keyStdin' }
  const values = { '--mirror-bucket': 'mirrorBucket', '--target-url': 'targetUrl', '--identity': 'identity', '--manifest': 'manifest', '--bucket': 'bucket', '--prefix': 'prefix', '--endpoint': 'endpoint', '--region': 'region', '--age-bin': 'ageBin', '--max-object-bytes': 'maxObjectBytes', '--manifest-sha256': 'manifestSha256' }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (flags[a]) o[flags[a]] = true
    else if (values[a] && i + 1 < argv.length) o[values[a]] = argv[++i]
    else throw new MirrorError('usage', `unknown or incomplete argument #${i + 1}`)
  }
  if (o.maxObjectBytes !== undefined) o.maxObjectBytes = Number(o.maxObjectBytes)
  if (!o.mirrorBucket || !o.targetUrl || !o.identity) throw new MirrorError('usage', '--mirror-bucket, --target-url and --identity are required')
  if (o.apply && !o.keyStdin) throw new MirrorError('usage', '--apply needs --target-key-stdin')
  if (o.overwrite && !o.apply) throw new MirrorError('usage', '--overwrite only with --apply')
  return o
}

async function main() {
  const secrets = []
  let decrypt
  try {
    const o = parseArgs(process.argv.slice(2))
    const accessKeyId = process.env.MIRROR_S3_READ_ACCESS_KEY_ID || ''
    const secretAccessKey = process.env.MIRROR_S3_READ_SECRET_ACCESS_KEY || ''
    if (!accessKeyId || !secretAccessKey) throw new MirrorError('read_key_missing')
    secrets.push(accessKeyId, secretAccessKey)
    const targetKey = o.keyStdin ? await readStdin() : ''
    if (o.keyStdin && !targetKey) throw new MirrorError('target_key_missing')
    if (targetKey) secrets.push(targetKey)
    const target = parseTarget(o.targetUrl)
    const s3 = s3Client({ endpoint: o.endpoint || 'https://s3.fr-par.scw.cloud', region: o.region || 'fr-par', bucket: o.mirrorBucket, accessKeyId, secretAccessKey })
    decrypt = await makeAgeDecrypt({ ageBin: o.ageBin, identityFile: o.identity })
    const summary = await runRestore(o, {
      s3, decrypt,
      upload: makeSupabaseUpload({ base: target.base, key: targetKey }),
      confirm: confirmOnTty,
      log: (line) => process.stderr.write(`restore: ${redact(line, secrets)}\n`),
    })
    process.stdout.write(`${redact(JSON.stringify(summary), secrets)}\n`)
    process.exitCode = summary.errors.length || summary.aborted ? 1 : 0
  } catch (err) {
    const code = err instanceof MirrorError ? err.message : 'internal'
    process.stderr.write(`restore: FAILED ${redact(code, secrets)}\n`)
    process.exitCode = 2
  } finally {
    decrypt?.wipe?.()
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) main()
