#!/usr/bin/env node
// A stand-in for the age CLI in storage-mirror.node-test.mjs (the real age is not
// installed on CI). It models only the two calls restore.mjs makes:
//   fake-age -d <identity-file>     "unlocks" a passphrase identity: the file holds
//                                   FAKE-PASSPHRASE-IDENTITY:<identity>, stdout gets <identity>
//   fake-age -d -i /dev/fd/3        identity read from fd 3 (must equal FAKE_AGE_IDENTITY),
//                                   stdin is FAKEAGE\n<base64 plaintext>, stdout the plaintext
// Synthetic only: no real key, no real cipher.
import { readFileSync } from 'node:fs'

const args = process.argv.slice(2)
const fail = (msg) => { process.stderr.write(`fake-age: ${msg}\n`); process.exit(1) }

if (args.length === 2 && args[0] === '-d') {
  const text = readFileSync(args[1], 'utf8')
  const m = /^FAKE-PASSPHRASE-IDENTITY:(.+)$/.exec(text.trim())
  if (!m) fail('identity file is not passphrase-protected')
  process.stdout.write(m[1])
} else if (args.length === 3 && args[0] === '-d' && args[1] === '-i' && args[2] === '/dev/fd/3') {
  const identity = readFileSync('/dev/fd/3', 'utf8')
  if (identity !== process.env.FAKE_AGE_IDENTITY) fail('wrong identity')
  const input = readFileSync(0)
  const head = Buffer.from('FAKEAGE\n')
  if (!input.subarray(0, head.length).equals(head)) fail('not an age file')
  process.stdout.write(Buffer.from(input.subarray(head.length).toString('utf8'), 'base64'))
} else {
  fail('unsupported call')
}
