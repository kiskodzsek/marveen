// Narrow per-agent dashboard keys (card 45dea12e; security review 53307).
//
// The fleet shares one full-power Bearer token. A sandboxed agent (card 6aa0a853) must not read it, so it gets a key
// of its own: `mvag_<random>`. Only sha256(key) is stored (table agent_keys, src/db.ts). A key authenticates as its
// agent and reaches only the endpoints src/web/agent-key-gate.ts allows, with the agent taken from the key, never from
// the request (X-Agent-Id, `from`, `agent_id` cannot widen it).
//
// Issuing a key revokes every earlier key of the same agent in the SAME transaction, so an agent never holds two live
// keys. The raw key is written once, to a file created with O_CREAT|O_EXCL|O_NOFOLLOW and mode 0600; when that write
// fails the new key is revoked too (fail closed: the agent gets 401, not a key nobody holds). Nothing caches a key, so a
// revocation takes effect on the next request.

import { createHash, randomBytes } from 'node:crypto'
import { closeSync, constants as fsc, lstatSync, openSync, unlinkSync, writeSync } from 'node:fs'
import { getDb } from '../db.js'

export const AGENT_KEY_PREFIX = 'mvag_'
/** An agent id as the roster spells one; anything else is refused before a row is written. */
const AGENT_ID = /^[a-z0-9][a-z0-9_-]{0,63}$/

function sha256hex(value: string): string {
  return createHash('sha256').update(value).digest('hex')
}

export interface AgentKeyPrincipal {
  readonly id: number
  readonly agent: string
}

/** The agent of a live key, or null (not an agent key, unknown, revoked). Records the use. */
export function resolveAgentKey(raw: string, now: number = Date.now()): AgentKeyPrincipal | null {
  if (typeof raw !== 'string' || !raw.startsWith(AGENT_KEY_PREFIX) || raw.length > 256) return null
  const keyHash = sha256hex(raw)
  const row = getDb()
    .prepare('SELECT id, agent_id, revoked_at FROM agent_keys WHERE key_hash = ?')
    .get(keyHash) as { id: number; agent_id: string; revoked_at: number | null } | undefined
  if (!row || row.revoked_at !== null || !AGENT_ID.test(row.agent_id)) return null
  getDb().prepare('UPDATE agent_keys SET last_used_at = ? WHERE id = ?').run(now, row.id)
  return { id: row.id, agent: row.agent_id }
}

/**
 * A new key for `agent`, written to `keyPath` (0600, created exclusively; a link or file already there is removed
 * first, never followed). Every earlier key of the agent is revoked in the same transaction as the insert.
 */
export function issueAgentKey(agent: string, keyPath: string, now: number = Date.now()): { id: number } {
  if (!AGENT_ID.test(agent)) throw new TypeError('not an agent id')
  const raw = AGENT_KEY_PREFIX + randomBytes(32).toString('base64url')
  const db = getDb()
  const id = db.transaction(() => {
    db.prepare('UPDATE agent_keys SET revoked_at = ? WHERE agent_id = ? AND revoked_at IS NULL').run(now, agent)
    return Number(db.prepare('INSERT INTO agent_keys (key_hash, agent_id, created_at) VALUES (?, ?, ?)').run(sha256hex(raw), agent, now).lastInsertRowid)
  })()
  try {
    writeKeyFile(keyPath, raw)
  } catch (e) {
    db.prepare('UPDATE agent_keys SET revoked_at = ? WHERE id = ?').run(now, id)
    throw e
  }
  return { id }
}

function writeKeyFile(keyPath: string, raw: string): void {
  // unlink, not open-over: the old entry may be a link the run planted, and O_NOFOLLOW below refuses one anyway
  if (lstatSync(keyPath, { throwIfNoEntry: false }) !== undefined) unlinkSync(keyPath)
  const fd = openSync(keyPath, fsc.O_WRONLY | fsc.O_CREAT | fsc.O_EXCL | fsc.O_NOFOLLOW, 0o600)
  try {
    const buf = Buffer.from(raw, 'utf8')
    for (let off = 0; off < buf.length; ) off += writeSync(fd, buf, off, buf.length - off)
  } finally {
    closeSync(fd)
  }
}

/** Revokes every live key of `agent`; returns how many. */
export function revokeAgentKeys(agent: string, now: number = Date.now()): number {
  return getDb().prepare('UPDATE agent_keys SET revoked_at = ? WHERE agent_id = ? AND revoked_at IS NULL').run(now, agent).changes
}
