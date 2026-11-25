// Issuing the narrow per-agent dashboard key at agent start, revoking it at stop (card 45dea12e, slice 2; security
// review 53307 point 5).
//
// The key file is <agent dir>/.claude-config/agent-api-key: the agent's own config folder, a name no other credential
// rule matches. The sandbox profile (card 6aa0a853) refuses every agent-api-key path and then allows the agent's own
// literal path only, so an agent reads its own key and no other.
//
// The folder is checked before the write: it must be a real directory, not a link (it is a direct child of the agent
// folder, so a non-link entry cannot resolve anywhere else). Otherwise an agent that swapped its own .claude-config for
// a link to another agent's folder would have the dashboard replace THAT agent's key file with its own key. A missing
// folder is made (0700). Known limit: a swap between this check and the write is not caught here; the sandbox profile
// (card 6aa0a853, v4) refuses renaming or removing an agent's .claude-config folder. The file itself is written by issueAgentKey (O_CREAT|O_EXCL|O_NOFOLLOW, 0600; the agent's earlier key
// revoked in the same transaction; a failed write revokes the new key).
//
// Which agents: local ones that run as the dashboard's own user. The main agent starts through scripts/channels.sh and
// keeps the full token (plan v1, 6.); a remote agent's files are on another host; an agent with runAsUser could not
// read a 0600 file of this user. For those no key is issued, and any earlier live key is revoked.
//
// Never throws, never blocks a start: in this slice no client reads the key yet (the agents still use the full
// token), so a failed issue only means the agent has no live key -- the key path answers 401, fail closed.

import { lstatSync, mkdirSync, unlinkSync } from 'node:fs'
import { join } from 'node:path'
import { issueAgentKey, revokeAgentKeys } from './auth-agent-keys.js'

export const AGENT_KEY_DIRNAME = '.claude-config'
export const AGENT_KEY_FILENAME = 'agent-api-key'

export interface AgentKeyTarget {
  readonly isMainAgent: boolean
  readonly isRemote: boolean
  readonly runAsUser: string | null | undefined
}

export type AgentKeyProvision =
  | { readonly state: 'issued'; readonly id: number; readonly path: string }
  | { readonly state: 'skipped'; readonly reason: 'main-agent' | 'remote-agent' | 'run-as-user'; readonly revoked: number }
  | { readonly state: 'failed'; readonly reason: string; readonly revoked: number }

export function agentKeyPath(agentDirPath: string): string {
  return join(agentDirPath, AGENT_KEY_DIRNAME, AGENT_KEY_FILENAME)
}

/** The checked folder for the key file, or a refusal reason. Makes a missing folder (0700, not recursive). */
function keyFolder(agentDirPath: string): { ok: true; dir: string } | { ok: false; reason: string } {
  const dir = join(agentDirPath, AGENT_KEY_DIRNAME)
  let st = lstatSync(dir, { throwIfNoEntry: false })
  if (st === undefined) {
    mkdirSync(dir, { mode: 0o700 })
    st = lstatSync(dir)
  }
  if (st.isSymbolicLink()) return { ok: false, reason: 'config-dir-is-a-link' }
  if (!st.isDirectory()) return { ok: false, reason: 'config-dir-not-a-directory' }
  return { ok: true, dir }
}

export function provisionAgentKey(name: string, agentDirPath: string, target: AgentKeyTarget, now: number = Date.now()): AgentKeyProvision {
  const skip = (reason: 'main-agent' | 'remote-agent' | 'run-as-user'): AgentKeyProvision => ({ state: 'skipped', reason, revoked: safeRevoke(name, now) })
  if (target.isMainAgent) return skip('main-agent')
  if (target.isRemote) return skip('remote-agent')
  if (target.runAsUser) return skip('run-as-user')
  try {
    const folder = keyFolder(agentDirPath)
    if (!folder.ok) return { state: 'failed', reason: folder.reason, revoked: safeRevoke(name, now) }
    const path = join(folder.dir, AGENT_KEY_FILENAME)
    const { id } = issueAgentKey(name, path, now)
    return { state: 'issued', id, path }
  } catch (e) {
    // issueAgentKey already revoked what it inserted; revoke again in case the throw came before the transaction
    return { state: 'failed', reason: errorCode(e), revoked: safeRevoke(name, now) }
  }
}

/** At stop: every live key of the agent revoked, the key file removed (a link there is removed, not followed). */
export function retireAgentKey(name: string, agentDirPath: string, now: number = Date.now()): { revoked: number; fileRemoved: boolean } {
  const revoked = safeRevoke(name, now)
  let fileRemoved = false
  try {
    const path = agentKeyPath(agentDirPath)
    if (lstatSync(path, { throwIfNoEntry: false }) !== undefined) {
      unlinkSync(path)
      fileRemoved = true
    }
  } catch { /* a leftover file holds a revoked key only */ }
  return { revoked, fileRemoved }
}

function safeRevoke(name: string, now: number): number {
  try {
    return revokeAgentKeys(name, now)
  } catch {
    return 0
  }
}

// Only a code or a type name leaves this module: a path or a message could carry more than the log needs.
function errorCode(e: unknown): string {
  if (e && typeof e === 'object' && 'code' in e && typeof (e as { code: unknown }).code === 'string') return (e as { code: string }).code
  return e instanceof Error ? e.name : 'unknown'
}
