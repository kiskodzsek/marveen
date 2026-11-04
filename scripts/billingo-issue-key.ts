#!/usr/bin/env tsx
// BILLINGOISSUE1104 (card 05980d05, Viktor 26223 A2/A5): the Ed25519 key the
// approval bot signs Billingo invoice approvals with.
//
//   npx tsx scripts/billingo-issue-key.ts generate   # once: a new key into the Vault
//   npx tsx scripts/billingo-issue-key.ts show       # the public half, again
//
// generate refuses when a key is already stored (a new key needs the gate's pin
// changed too: delete the Vault entry on purpose first). The private key goes
// straight into the Vault (BILLINGO_ISSUE_KEY_VAULT_ID, never served by any
// route) and is never printed. Both commands print only the public half, as
// the entry for ops/gate/billingo-issue.json "keys" in kiskodzsek/mcp-connectors:
//   {"kid":"k-1a2b3c4d","key":"<raw Ed25519 public key, base64url>"}

import { generateKeyPairSync } from 'node:crypto'
import { BILLINGO_ISSUE_KEY_VAULT_ID, publicKeyInfo, readIssueSigningKey } from '../src/web/billingo-issue-approval.js'
import { getSecret, setSecret } from '../src/web/vault.js'

const command = process.argv[2]
if (command === 'generate') {
  if (getSecret(BILLINGO_ISSUE_KEY_VAULT_ID)) {
    process.stderr.write(`A key is already stored under ${BILLINGO_ISSUE_KEY_VAULT_ID}; not replaced. Use "show" for its public half.\n`)
    process.exit(1)
  }
  const { privateKey } = generateKeyPairSync('ed25519')
  setSecret(BILLINGO_ISSUE_KEY_VAULT_ID, 'Billingo issue approval signing key (BILLINGOISSUE1104)', privateKey.export({ format: 'pem', type: 'pkcs8' }).toString())
  const stored = readIssueSigningKey()
  if (!stored || stored.publicKey !== publicKeyInfo(privateKey).publicKey) {
    process.stderr.write('The key was not read back from the Vault as written. Stop and report it.\n')
    process.exit(1)
  }
  process.stdout.write(`${JSON.stringify({ kid: stored.kid, key: stored.publicKey })}\n`)
} else if (command === 'show') {
  const stored = readIssueSigningKey()
  if (!stored) {
    process.stderr.write(`No Ed25519 key under ${BILLINGO_ISSUE_KEY_VAULT_ID}.\n`)
    process.exit(1)
  }
  process.stdout.write(`${JSON.stringify({ kid: stored.kid, key: stored.publicKey })}\n`)
} else {
  process.stderr.write('usage: npx tsx scripts/billingo-issue-key.ts generate | show\n')
  process.exit(2)
}
