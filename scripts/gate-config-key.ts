#!/usr/bin/env tsx
// GATECONFIG1113 (Klodel 40642, Viktor 40668 C6): the Ed25519 key the approval bot signs gate-config changes
// with. A separate key and kid from the Billingo issue key.
//
//   npx tsx scripts/gate-config-key.ts generate   # once: a new key into the Vault
//   npx tsx scripts/gate-config-key.ts show       # the public half, again
//
// generate refuses when a key is already stored (a new key needs the root-owned pubkey.json changed too, which
// is a sudo step). The private key goes straight into the Vault (GATE_CONFIG_KEY_VAULT_ID, server-only, never
// served by any route) and is never printed. Both commands print only the public half, as the entry for
// /usr/local/libexec/gate-config/pubkey.json "keys":
//   {"kid":"k-1a2b3c4d","public_key":"<raw Ed25519 public key, base64url>","purpose":"gate_config_v1"}

import { generateKeyPairSync } from 'node:crypto'
import { publicKeyInfo } from '../src/web/billingo-issue-approval.js'
import { GATE_CONFIG_KEY_VAULT_ID, GATE_CONFIG_PURPOSE, readGateConfigSigningKey } from '../src/web/gate-config-approval.js'
import { getSecret, setSecret } from '../src/web/vault.js'

const entry = (k: { kid: string; publicKey: string }) => `${JSON.stringify({ kid: k.kid, public_key: k.publicKey, purpose: GATE_CONFIG_PURPOSE })}\n`

const command = process.argv[2]
if (command === 'generate') {
  if (getSecret(GATE_CONFIG_KEY_VAULT_ID)) {
    process.stderr.write(`A key is already stored under ${GATE_CONFIG_KEY_VAULT_ID}; not replaced. Use "show" for its public half.\n`)
    process.exit(1)
  }
  const { privateKey } = generateKeyPairSync('ed25519')
  setSecret(GATE_CONFIG_KEY_VAULT_ID, 'Gate config approval signing key (GATECONFIG1113)', privateKey.export({ format: 'pem', type: 'pkcs8' }).toString())
  const stored = readGateConfigSigningKey()
  if (!stored || stored.publicKey !== publicKeyInfo(privateKey).publicKey) {
    process.stderr.write('The key was not read back from the Vault as written. Stop and report it.\n')
    process.exit(1)
  }
  process.stdout.write(entry(stored))
} else if (command === 'show') {
  const stored = readGateConfigSigningKey()
  if (!stored) {
    process.stderr.write(`No Ed25519 key under ${GATE_CONFIG_KEY_VAULT_ID}.\n`)
    process.exit(1)
  }
  process.stdout.write(entry(stored))
} else {
  process.stderr.write('usage: gate-config-key.ts generate | show\n')
  process.exit(2)
}
