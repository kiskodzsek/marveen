import { readFileSync, lstatSync, realpathSync, statSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { join } from 'node:path'
import { atomicWriteFileSync } from './atomic-write.js'

// CLAUDEJSON1014: an agent's isolated .claude.json loses most of its keys on a
// router restart. Measured live on juro twice (2026-10-13 23:32 and
// 2026-10-14 00:17, kernel reports/2026-10-13-claude-json-isolated-repro.md):
// ~2.7 s after the restart POST the 54 KB file became 1208 B with 12 top-level
// keys, while the ONLY claude alive was the old one -- it outlives
// `tmux kill-session` by ~2.8 s, past stopAgentProcess's fixed 2 s wait. The
// new claude then backs the TRUNCATED file up into the shared backups dir, so
// Claude Code's own backup cannot recover it. Lost: user-scope mcpServers
// entries, other projects' entries, tipsHistory and friends.
//
// Why Claude Code's exit write drops the keys is NOT known (a small synthetic
// repro never showed it). This guard therefore does not depend on the cause:
// it takes an in-memory snapshot before the kill and, once the old PID has
// really exited, puts back whatever the exit write dropped.
//
// Security-gate conditions (viktor 3287), each enforced below:
//   1. The snapshot lives only in this process's memory. Never on disk, in a
//      log line or an error, never returned by the API. Logs carry structure
//      only: byte size, top-level key count, a 12-hex sha prefix.
//   2. The restore target is the agent's OWN fixed path derived from its
//      agentDir: <agentDir>/.claude-config/.claude.json, realpath-checked, no
//      symlink followed -- never the shared ~/.claude.json or ~/.claude.
//   3. Conditional swap: only after the old PID has exited, and only while the
//      live file's sha is still the damaged one that was evaluated. If anything
//      else wrote in between, nothing is overwritten. tmp + rename, mode kept
//      but capped at 0600.
//   4. The protected maps are `projects` and `mcpServers`. The restore never
//      adds an mcpServers entry the pre-stop file did not have (the snapshot
//      IS the pre-stop file; live-only entries stay as live has them).
//   5. Per-agent backups dirs are a separate item; this does not replace them.

export const PROTECTED_MAPS = ['projects', 'mcpServers'] as const

// A top-level key count below this share of the snapshot's counts as damage on
// its own (54 KB/25 keys -> 1208 B/12 keys measured is 48%). A healthy exit
// write ADDS keys (last* session metrics), it does not halve them.
export const MIN_KEPT_TOP_LEVEL_SHARE = 0.5

// The old claude was measured alive ~2.8 s after kill-session. 10 s leaves a
// wide margin; past it the guard gives up rather than race a live writer.
export const OLD_PID_EXIT_TIMEOUT_MS = 10_000
const OLD_PID_POLL_MS = 50

export interface ClaudeJsonSnapshot {
  readonly path: string
  readonly data: Record<string, unknown>
  readonly bytes: number
  readonly sha: string
}

export type RestoreDecision =
  | { action: 'keep'; reason: 'intact' | 'snapshot-not-object' }
  | { action: 'restore'; reason: 'unparseable' | 'lost-protected' | 'lost-top-level'; lost: string[]; merged: Record<string, unknown> }

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

export function shaHex(text: string | Buffer): string {
  return createHash('sha256').update(text).digest('hex')
}

// Structure-only description for log lines (condition 1): no key names, no values.
export function describeShape(bytes: number, data: unknown, sha: string): { bytes: number; keys: number | null; sha: string } {
  return { bytes, keys: isPlainObject(data) ? Object.keys(data).length : null, sha: sha.slice(0, 12) }
}

// Condition 2: the agent's own isolated .claude.json, or null. Refuses a
// symlinked .claude-config dir or .claude.json (either would let a restore land
// in the shared root or in another agent's file), and a config dir whose
// realpath is not directly under the agent dir's realpath.
export function resolveOwnClaudeJsonPath(agentDirPath: string): string | null {
  try {
    const cfg = join(agentDirPath, '.claude-config')
    const file = join(cfg, '.claude.json')
    const cfgStat = lstatSync(cfg)
    if (cfgStat.isSymbolicLink() || !cfgStat.isDirectory()) return null
    const fileStat = lstatSync(file)
    if (fileStat.isSymbolicLink() || !fileStat.isFile()) return null
    if (realpathSync(cfg) !== join(realpathSync(agentDirPath), '.claude-config')) return null
    return file
  } catch {
    return null
  }
}

export function takeClaudeJsonSnapshot(path: string): ClaudeJsonSnapshot | null {
  try {
    const raw = readFileSync(path)
    const data = JSON.parse(raw.toString('utf-8')) as unknown
    if (!isPlainObject(data)) return null
    return { path, data, bytes: raw.length, sha: shaHex(raw) }
  } catch {
    // Absent or already unparseable before the stop: nothing trustworthy to
    // restore from, so the guard stays out of the way.
    return null
  }
}

// Pure: compares the pre-stop snapshot with what the stop left on disk.
//
// The restore is snapshot-first: every key and every protected-map entry the
// pre-stop file had comes back with its pre-stop value, and only what the live
// file ADDED (a new top-level key, a new project or mcpServers entry) is kept on
// top. Overlaying the live values instead would write the truncated file's reset
// defaults over the real ones. The cost: the old session's last* exit metrics
// for a project that already existed are dropped -- cosmetic, and rewritten on
// the next exit.
export function decideClaudeJsonRestore(snapshot: Record<string, unknown>, liveText: string): RestoreDecision {
  if (!isPlainObject(snapshot)) return { action: 'keep', reason: 'snapshot-not-object' }
  let live: unknown
  try { live = JSON.parse(liveText) } catch { live = undefined }
  if (!isPlainObject(live)) {
    return { action: 'restore', reason: 'unparseable', lost: ['<file>'], merged: structuredClone(snapshot) }
  }

  const lostProtected: string[] = []
  for (const key of PROTECTED_MAPS) {
    const before = snapshot[key]
    if (!isPlainObject(before)) continue
    const after = live[key]
    if (!isPlainObject(after)) {
      if (Object.keys(before).length > 0) lostProtected.push(key)
      continue
    }
    if (Object.keys(before).some((entry) => !(entry in after))) lostProtected.push(key)
  }

  const beforeKeys = Object.keys(snapshot)
  const lostTop = beforeKeys.filter((k) => !(k in live))
  const keptShare = beforeKeys.length === 0 ? 1 : (beforeKeys.length - lostTop.length) / beforeKeys.length
  const damaged = lostProtected.length > 0 || keptShare < MIN_KEPT_TOP_LEVEL_SHARE
  if (!damaged) return { action: 'keep', reason: 'intact' }

  const merged: Record<string, unknown> = structuredClone(snapshot)
  for (const [k, v] of Object.entries(live)) {
    if (!(k in merged)) merged[k] = structuredClone(v)
  }
  for (const key of PROTECTED_MAPS) {
    const before = merged[key]
    const after = live[key]
    if (!isPlainObject(before) || !isPlainObject(after)) continue
    for (const [entry, v] of Object.entries(after)) {
      if (!(entry in before)) before[entry] = structuredClone(v)
    }
  }
  return {
    action: 'restore',
    reason: lostProtected.length > 0 ? 'lost-protected' : 'lost-top-level',
    lost: [...lostProtected, ...(lostProtected.length === 0 ? [`${lostTop.length} top-level keys`] : [])],
    merged,
  }
}

export function isPidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0)
    return true
  } catch (err) {
    // EPERM: the process exists under another user -> still alive.
    return (err as NodeJS.ErrnoException).code === 'EPERM'
  }
}

export async function waitForPidExit(
  pid: number,
  timeoutMs: number = OLD_PID_EXIT_TIMEOUT_MS,
  alive: (pid: number) => boolean = isPidAlive,
  sleep: (ms: number) => Promise<void> = (ms) => new Promise((r) => setTimeout(r, ms)),
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (alive(pid)) {
    if (Date.now() >= deadline) return false
    await sleep(OLD_PID_POLL_MS)
  }
  return true
}

export type RestoreOutcome =
  | { outcome: 'intact' }
  | { outcome: 'restored'; reason: string; lost: string[]; before: ReturnType<typeof describeShape>; after: ReturnType<typeof describeShape> }
  | { outcome: 'skipped'; reason: 'old-pid-still-alive' | 'live-unreadable' | 'live-changed-before-swap' | 'target-moved' | 'write-failed' }

export interface RestoreDeps {
  waitForExit: () => Promise<boolean>
  // Re-resolves the target right before the write (condition 2 at swap time).
  resolveTarget: () => string | null
}

// Conditions 2 and 3. Runs after the kill; never throws.
export async function restoreClaudeJsonAfterStop(snapshot: ClaudeJsonSnapshot, deps: RestoreDeps): Promise<RestoreOutcome> {
  if (!(await deps.waitForExit())) return { outcome: 'skipped', reason: 'old-pid-still-alive' }

  let liveRaw: Buffer
  try { liveRaw = readFileSync(snapshot.path) } catch { return { outcome: 'skipped', reason: 'live-unreadable' } }
  const liveSha = shaHex(liveRaw)
  if (liveSha === snapshot.sha) return { outcome: 'intact' }

  const decision = decideClaudeJsonRestore(snapshot.data, liveRaw.toString('utf-8'))
  if (decision.action === 'keep') return { outcome: 'intact' }

  if (deps.resolveTarget() !== snapshot.path) return { outcome: 'skipped', reason: 'target-moved' }
  const body = JSON.stringify(decision.merged, null, 2) + '\n'
  try {
    // Compare-and-swap: the bytes must still be the damaged ones we judged.
    if (shaHex(readFileSync(snapshot.path)) !== liveSha) return { outcome: 'skipped', reason: 'live-changed-before-swap' }
    // Never wider than 0600, whatever the live file carries: mcpServers entries
    // can hold credentials in their env blocks (viktor L2).
    const mode = statSync(snapshot.path).mode & 0o600
    atomicWriteFileSync(snapshot.path, body, { mode })
  } catch {
    return { outcome: 'skipped', reason: 'write-failed' }
  }
  let liveParsed: unknown
  try { liveParsed = JSON.parse(liveRaw.toString('utf-8')) } catch { liveParsed = undefined }
  return {
    outcome: 'restored',
    reason: decision.reason,
    lost: decision.lost,
    before: describeShape(liveRaw.length, liveParsed, liveSha),
    after: describeShape(Buffer.byteLength(body), decision.merged, shaHex(body)),
  }
}
