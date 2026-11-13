// GATECONFIG1113 (Klodel 40642/40646, Patrik TG 18364: "mi a faszomért kell állandoan ez a sudozgatás";
// plan agents/kernel/work/higgsfield-gate/sudo-nelkul-terv.md, Viktor 40668 C1-C7):
// a gate config change (Higgsfield gate first) approved with the owner's button, without sudo.
//
// The request (POST /api/approvals, category gate_config) carries, as action_payload:
//   { gate, prev_sha, config }
// prev_sha is the sha256 of the INSTALLED config file; content_hash = sha256(canonicalJson(payload)).
// The server reads the installed config itself, checks prev_sha against it, and renders the owner's button text
// from the FULL structural diff between the two (every changed leaf, C6). A diff it cannot render completely,
// or an empty one, is refused: no approval row, so no button next to a partial text.
//
// After the owner's button press (resolution_channel 'approval_bot', resolved_by 'telegram_button', nothing
// else) the server signs, with the Ed25519 key in the Vault (GATE_CONFIG_KEY_VAULT_ID, server-only):
//   gate_config_v1:<kid>:<approval_id>:<gate>:<prev_sha>:<config_sha>:<resolved_at>
// and writes the canonical envelope into the gate's inbox, where the _gatecfg daemon (gate-config-apply.mjs)
// verifies it against the pinned public key and the root-owned ceiling, and installs it.
//
// What this does NOT stop (Viktor 40668, as for the Billingo issue key): whoever can write the dashboard code or
// the Vault on this UID can sign. The ceiling bounds what a signature can reach: tools, parameter keys, limits,
// upload roots and the ledger outside it still need sudo.

import { createHash, createPrivateKey, sign, type KeyObject } from 'node:crypto'
import { closeSync, constants, openSync, readFileSync, renameSync, writeSync, fsyncSync, unlinkSync } from 'node:fs'
import { join } from 'node:path'
import { canonicalJson, publicKeyInfo } from './billingo-issue-approval.js'
import { getSecret } from './vault.js'

export const GATE_CONFIG_CATEGORY = 'gate_config'
export const GATE_CONFIG_PURPOSE = 'gate_config_v1'
export const GATE_CONFIG_KEY_VAULT_ID = 'gate-config-signing-key'
/** The owner's button message must fit with room to spare (Telegram: 4096 characters). */
export const MAX_DIFF_CHARS = 3000
const MAX_PAYLOAD_BYTES = 256 * 1024

export interface GateSpec { label: string; installed: string; inbox: string }
/** The gates this route knows. A gate not listed here cannot be requested. */
export const GATES: Record<string, GateSpec> = {
  higgsfield: {
    label: 'Higgsfield-kapu',
    installed: '/usr/local/etc/higgsfield-gate/config.json',
    inbox: '/usr/local/var/gate-config/inbox',
  },
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const sha256 = (b: string | Buffer) => createHash('sha256').update(b).digest('hex')

export interface GateConfigRequest { gate: string; prevSha: string; config: Record<string, unknown>; contentHash: string }

export function gateConfigContentHash(gate: string, prevSha: string, config: unknown): string {
  return sha256(canonicalJson({ config, gate, prev_sha: prevSha }))
}

export function parseGateConfigRequest(payload: string | null | undefined, contentHash: string | null | undefined, gates: Record<string, GateSpec> = GATES): { request: GateConfigRequest } | { error: string } {
  if (typeof payload !== 'string' || payload.length === 0) return { error: 'action_payload is required' }
  if (Buffer.byteLength(payload, 'utf8') > MAX_PAYLOAD_BYTES) return { error: 'action_payload too large' }
  let p: unknown
  try { p = JSON.parse(payload) } catch { return { error: 'action_payload is not JSON' } }
  if (!isObj(p)) return { error: 'action_payload must be an object' }
  const keys = Object.keys(p).sort().join(',')
  if (keys !== 'config,gate,prev_sha') return { error: 'action_payload keys must be exactly gate, prev_sha, config' }
  const { gate, prev_sha: prevSha, config } = p as { gate: unknown; prev_sha: unknown; config: unknown }
  if (typeof gate !== 'string' || !Object.hasOwn(gates, gate)) return { error: 'unknown gate' }
  if (typeof prevSha !== 'string' || !/^[0-9a-f]{64}$/.test(prevSha)) return { error: 'prev_sha must be a sha256 hex' }
  if (!isObj(config)) return { error: 'config must be an object' }
  const hash = gateConfigContentHash(gate, prevSha, config)
  if (contentHash !== hash) return { error: 'content_hash does not match the payload' }
  return { request: { gate, prevSha, config, contentHash: hash } }
}

// ---------------------------------------------------------------- diff (C6)

function leaves(v: unknown, path: string, out: Map<string, string>): void {
  if (isObj(v) && Object.keys(v).length > 0) {
    for (const k of Object.keys(v).sort()) leaves(v[k], path ? `${path}.${k}` : k, out)
    return
  }
  out.set(path, canonicalJson(v))
}

/** Every changed leaf (arrays compared whole), sorted by path. */
export function configDiff(before: unknown, after: unknown): string[] {
  const a = new Map<string, string>(); const b = new Map<string, string>()
  leaves(before, '', a); leaves(after, '', b)
  const paths = [...new Set([...a.keys(), ...b.keys()])].sort()
  const lines: string[] = []
  for (const p of paths) {
    const x = a.get(p); const y = b.get(p)
    if (x === y) continue
    if (x === undefined) lines.push(`+ ${p} = ${y}`)
    else if (y === undefined) lines.push(`- ${p} (volt: ${x})`)
    else lines.push(`~ ${p}: ${x} -> ${y}`)
  }
  return lines
}

/** The owner's button text, or an error: never a partial text (C6). */
export function renderGateConfigText(r: GateConfigRequest, readInstalled: (path: string) => Buffer = (p) => readFileSync(p), gates: Record<string, GateSpec> = GATES): { text: string } | { error: string } {
  const spec = gates[r.gate]
  let installed: Buffer
  try { installed = readInstalled(spec.installed) } catch { return { error: 'the installed config cannot be read' } }
  if (sha256(installed) !== r.prevSha) return { error: 'prev_sha is not the installed config (it changed meanwhile)' }
  let before: unknown
  try { before = JSON.parse(installed.toString('utf8')) } catch { return { error: 'the installed config is not JSON' } }
  const diff = configDiff(before, r.config)
  if (diff.length === 0) return { error: 'the new config is the same as the installed one' }
  const text = [`${spec.label}: beállítás-váltás (${diff.length} változás)`, ...diff].join('\n')
  if (text.length > MAX_DIFF_CHARS) return { error: `the diff is too long for the button message (${text.length} > ${MAX_DIFF_CHARS} characters); split the change` }
  return { text }
}

// ---------------------------------------------------------------- signing

export interface GateConfigSigningKey { key: KeyObject; kid: string; publicKey: string }

export function readGateConfigSigningKey(secret: (id: string) => string | null = getSecret): GateConfigSigningKey | null {
  let pem: string | null = null
  try { pem = secret(GATE_CONFIG_KEY_VAULT_ID) } catch { pem = null }
  if (!pem) return null
  try {
    const key = createPrivateKey(pem.trim())
    if (key.asymmetricKeyType !== 'ed25519') return null
    return { key, ...publicKeyInfo(key) }
  } catch {
    return null
  }
}

export interface SignableGateApproval {
  id: string
  category: string
  status: string
  resolved_at: number | null
  resolved_by: string | null
  resolution_channel?: string | null
  action_payload: string | null
  content_hash: string | null
}

/** The canonical envelope for the gate's inbox, or the reason it is not signed. Only the owner's button signs. */
export function signGateConfigApproval(a: SignableGateApproval, signingKey: GateConfigSigningKey | null, gates: Record<string, GateSpec> = GATES): { envelope: string; gate: string } | { error: string } {
  if (a.category !== GATE_CONFIG_CATEGORY) return { error: 'not a gate_config approval' }
  if (a.status !== 'approved' || a.resolution_channel !== 'approval_bot' || a.resolved_by !== 'telegram_button' || !Number.isSafeInteger(a.resolved_at)) {
    return { error: 'only an approval resolved by the owner\'s button is signed' }
  }
  if (!/^[A-Za-z0-9-]{8,64}$/.test(a.id)) return { error: 'approval id outside the signed character set' }
  const parsed = parseGateConfigRequest(a.action_payload, a.content_hash, gates)
  if ('error' in parsed) return { error: parsed.error }
  if (!signingKey) return { error: 'no signing key in the Vault' }
  const r = parsed.request
  const configSha = sha256(canonicalJson(r.config))
  const message = [GATE_CONFIG_PURPOSE, signingKey.kid, a.id, r.gate, r.prevSha, configSha, a.resolved_at].join(':')
  const sig = sign(null, Buffer.from(message, 'utf8'), signingKey.key).toString('base64url')
  const envelope = canonicalJson({ approval_id: a.id, config: r.config, gate: r.gate, kid: signingKey.kid, prev_sha: r.prevSha, resolved_at: a.resolved_at, sig, v: 1 })
  return { envelope, gate: r.gate }
}

/** Writes the envelope into the gate's inbox as <approval id>.json (tmp + fsync + rename; never overwrites). */
export function writeGateConfigEnvelope(gate: string, approvalId: string, envelope: string, gates: Record<string, GateSpec> = GATES): void {
  const dir = gates[gate]!.inbox
  const tmp = join(dir, `.${approvalId}.tmp`)
  const fd = openSync(tmp, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o644)
  try {
    writeSync(fd, envelope)
    fsyncSync(fd)
  } catch (err) {
    closeSync(fd)
    try { unlinkSync(tmp) } catch { /* best effort */ }
    throw err
  }
  closeSync(fd)
  const final = join(dir, `${approvalId}.json`)
  try {
    readFileSync(final)
    unlinkSync(tmp)
    throw new Error('an envelope for this approval is already in the inbox')
  } catch (err) {
    if ((err as NodeJS.ErrnoException)?.code !== 'ENOENT') throw err
  }
  renameSync(tmp, final)
}
