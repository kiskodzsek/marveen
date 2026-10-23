# Marabel Storage mirror: restore and negative test

Card 4e790bdd. The mirror is a Supabase Edge Function in the Marabel repo (Dave). It copies
`project-photos`, `storyteller-audio` and `project-print-assets` daily, age-encrypted, into a
Scaleway bucket with versioning and a COMPLIANCE Object Lock. These two tools are the fleet side:

| Tool | Key it uses | Writes to |
|---|---|---|
| `restore.mjs` | mirror READ key (env), age identity (file + passphrase on the tty), target service-role key (stdin) | the target Supabase Storage, only with `--apply` |
| `negative-test.mjs` | mirror UPLOADER key (env) | one canary object of its own |

Plan: `agents/kernel/reports/2026-10-23-marabel-storage-tukor-terv.md`. Security review:
`agents/viktor/reports/2026-10-23-marabel-storage-tukor-review.md` and Viktor 15290 (the
requirements these tools implement). Privacy: `agents/lex/jelentesek/2026-10-23-storage-tukor-adatvedelmi-iselet-4e790bdd.md`.

## Manifest (the contract with the Edge Function)

`manifest/latest.json.age` and `manifest/<YYYYMMDDTHHMMSSZ>.json.age`, age-encrypted UTF-8 JSON:

```json
{
  "version": 1,
  "generated_at": "2026-10-23T03:00:00Z",
  "objects": [
    {
      "id": "<storage.objects.id, UUID>",
      "bucket": "project-photos",
      "path": "<storage.objects.name>",
      "etag": "<metadata.eTag as Supabase reports it>",
      "size": 123456,
      "content_type": "image/jpeg",
      "updated_at": "2026-10-22T18:00:00Z",
      "version_id": "<x-amz-version-id from the mirror PUT response>",
      "tombstone": false
    }
  ]
}
```

- Required: `id`, `bucket`, `path`, `etag`, `size`, `tombstone`. Optional: `content_type`,
  `updated_at`, `version_id`.
- `version_id` is what makes an OLD manifest restorable: without it the restore reads the
  current version of each object, which may be newer than the manifest (or a tombstone).
- A tombstone entry has `size: 0` and is skipped by the restore.
- The mirror object of an entry is `<bucket>/<id>.age`; the restore builds it from `bucket` and
  `id` only, never from `path`.
- Manifest pin (Viktor 15290 M2): for every manifest it writes, the Edge Function also stores the
  sha256 of the manifest CIPHERTEXT (the exact bytes of the `.json.age` object) in a DB row that
  only the service role reaches, e.g. `storage_mirror_runs.manifest_sha256`. The S3 key cannot
  touch that row, so a forged manifest cannot forge its pin.
- `content_type` is restored only if the bucket allows it (parameters such as `;codecs=opus`
  dropped); anything else, e.g. `text/html` or `image/svg+xml`, becomes
  `application/octet-stream` (`RESTORE_CONTENT_TYPES` in `lib.mjs`, taken from what Marabel uploads).

The manifest is NOT trusted (age encrypts, it does not authenticate the writer; anyone with the
leaked uploader key can write one, together with matching forged objects, so the size/MD5 check
alone proves nothing about a forged manifest; only the pin does). The restore refuses the WHOLE manifest if any entry fails:
bucket outside the three above, non-UUID id, a path with `..`/`.`/empty segment, a leading `/`,
a backslash, a control character, non-NFC text or over 1024 characters, a size over 200 MB,
duplicate id or path. Per object, a size or MD5-eTag mismatch with the decrypted bytes is an
error and that object is not uploaded (a multipart eTag `<md5>-<n>` cannot be recomputed: only
the size is checked, counted as `etag_unchecked`).

## restore.mjs

```
read -s AK; read -s SK     # typed, not exported, not in the shell history
MIRROR_S3_READ_ACCESS_KEY_ID="$AK" MIRROR_S3_READ_SECRET_ACCESS_KEY="$SK" \
node scripts/storage-mirror/restore.mjs --mirror-bucket <bucket> --identity <identity.age> \
  --target-url https://<ref>.supabase.co --manifest manifest/<YYYYMMDDTHHMMSSZ>.json.age \
  --manifest-sha256 <hex from storage_mirror_runs> [--bucket B] [--prefix P] [--verify]
unset AK SK
```

After an incident, use the timestamped manifest from BEFORE it, not `manifest/latest.json.age`.

1. Default (no `--verify`, no `--apply`): reads and validates the manifest, prints the plan
   (objects and bytes per bucket). Nothing else is read, nothing is written.
2. `--verify`: also downloads, decrypts and checks every selected object. Still no write.
3. `--apply --target-key-stdin`: uploads. Before the first write it prints the target ref and
   asks for it to be typed back on the tty. An existing object is skipped (`exists_skipped`)
   unless `--overwrite`. The production project (`gvipgmezmglireuizxpn`) also needs
   `--i-know-this-is-prod`.
4. `--manifest-sha256 <hex>` pins the run: a different manifest stops it before anything is
   decrypted. It is REQUIRED for `--apply` on production and for any `--overwrite`; until the Edge
   Function stores the hash, those two cannot run at all (a throwaway or staging drill can).
   Every plan prints the hash it computed (`manifest_sha256`) and whether it was pinned.

The target key comes on stdin, e.g. Pulzus' pipe from the Management API, never as an argument.
The age identity is a passphrase-protected file (`age -p`); age asks for the passphrase on the
tty once, the unlocked identity stays in memory and reaches each `age -d` child on fd 3.
Decrypted bytes go from age's stdout straight into the upload; nothing is written to disk.
The mirror client only allows GET/HEAD: the restore cannot send DELETE or any write to the mirror.
No request follows a redirect (`redirect: 'error'`), so no signed request or `apikey` header can be
carried to another origin. The unlocked identity is zeroed after the run (best effort: a garbage-
collected runtime can keep copies; the process is short-lived).

Output: one JSON summary on stdout (counts, bytes, `errors: [{index, code}]`), progress on
stderr. File names, paths and object ids are never printed. Exit 0 = clean, 1 = some objects
failed, 2 = the run failed.

Where it runs (plan F4): preferably on Patrik's machine; on the fleet host only with the
identity file 0600 in a place no agent reads, deleted after use. It needs the `age` CLI
(`brew install age`). The CI tests use a stand-in binary. Checked by hand on 2026-10-23 with
age 1.3.2 and a throwaway synthetic key pair: the passphrase identity is unlocked with one tty
prompt, two objects decrypt through fd 3, a corrupt input gives `decrypt_failed`, an over-cap
output `too_large`. The S3 and Supabase calls have run against mocks only; the first live run
is the restore drill on the throwaway bucket.

## negative-test.mjs

```
MIRROR_S3_ACCESS_KEY_ID="$AK" MIRROR_S3_SECRET_ACCESS_KEY="$SK" \
node scripts/storage-mirror/negative-test.mjs --bucket <test-bucket> --other-bucket <another bucket>
```

Uploads one random 32-byte canary (`canary/negtest-<time>-<rand>.bin`), then expects HTTP 403 for:
DeleteObjectVersion, DeleteObject, PutObjectRetention (also with the governance bypass header),
PutObjectLegalHold, PutObjectAcl, PutBucketLifecycle, PutBucketVersioning, PutBucketPolicy,
PutObjectLockConfiguration, PutBucketAcl, DeleteBucketPolicy, DeleteBucketLifecycle,
DeleteBucket, and a PUT and a LIST on the other bucket. A probe passes only on HTTP 403 with the
S3 error code `AccessDenied` (Viktor 15290 M1): a 403 `SignatureDoesNotMatch` or
`InvalidAccessKeyId` never reached the permission check, so it is a FAIL marked `signing`; any
other status or code is a FAIL to be read by a human. Each probe's result carries its code. At the
end the canary must still exist in the same version.

The probe bucket (Viktor 15290 I1): versioned, Object Lock with NO default retention, and the
uploader key's policy identical to the live one. Under a lock, the version/retention/legal-hold
calls are refused by the lock too, and a green run would prove the WORM setting, not the key.

Without `--prod-canary` the bucket name must carry `test` or `probe` as its own token
(`marabel-mirror-test`; not `marabel-latest`). In both modes the bucket name is typed back on the
tty before the first request. With `--prod-canary` (the live mirror bucket) only the object-level
probes run, on the canary alone: a bucket-level probe cannot be scoped to one object, so if a denial
were missing it could change the live configuration. On the locked live bucket this proves the
WORM behaviour, not the key's rights, and it leaves a 32-byte canary that cannot be deleted until
its lock runs out. First run: the probe bucket (plan 8).

Where it runs (Klodel 15296, Viktor 15290/5 (b)): the uploader key lives only in Supabase, so the
first live runs are a temporary selftest mode inside the Edge Function, ported from `probes()`
here. This script is the reference implementation and covers any later run with a key on hand.

## Tests

`node --test scripts/__tests__/storage-mirror.node-test.mjs`; in CI it runs inside `npm test`
through `src/__tests__/storage-mirror-suite.test.ts` (no workflow change). Synthetic data,
mocked S3 and Supabase, a fake `age` (`scripts/__tests__/fixtures/storage-mirror/fake-age.mjs`).
The SigV4 signer is checked against the AWS SigV4 test-suite vector `get-vanilla`.
