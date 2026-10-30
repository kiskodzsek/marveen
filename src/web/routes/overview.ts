import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { homedir } from 'node:os'
import { PROJECT_ROOT, MAIN_AGENT_ID, currentBotName } from '../../config.js'
import { getDb, countTaskRunsBetween } from '../../db.js'
import {
  agentDir, listAgentNames, readAgentDisplayName,
  readAgentAuthMode, readAgentClaudePlan, readAgentClaudeConfigDir,
} from '../agent-config.js'
import { readAgentTeam } from '../agent-team.js'
import { isAgentRunning } from '../agent-process.js'
import { json, jsonMaybeGzip } from '../http-helpers.js'
import { readQuotaSnapshot, DEFAULT_MAX_AGE_SEC, readFableSnapshot, DEFAULT_FABLE_MAX_AGE_SEC, readModQuotaSnapshot, chooseQuotaSnapshot, quotaPlanKey, type QuotaSnapshot } from '../quota.js'
import { STATE_OBSERVER_STATE_DIR } from '../state-observer.js'
import { resolveOauthTokenFileSetting } from '../agent-oauth-token-file.js'
import type { RouteContext } from './types.js'

// Count "real" user turns (operator prompts, Telegram messages) in every
// Claude Code session JSONL under ~/.claude/projects/. Filters out
// tool_result, local-command, and synthetic system events so a task-heavy
// hour doesn't inflate the counter.
function countUserTurns(fromMs: number, toMs: number = Number.POSITIVE_INFINITY): number {
  const root = join(homedir(), '.claude', 'projects')
  if (!existsSync(root)) return 0
  let total = 0
  try {
    for (const projectDir of readdirSync(root)) {
      const absDir = join(root, projectDir)
      let stat: ReturnType<typeof statSync>
      try { stat = statSync(absDir) } catch { continue }
      if (!stat.isDirectory()) continue
      for (const fname of readdirSync(absDir)) {
        if (!fname.endsWith('.jsonl')) continue
        const absFile = join(absDir, fname)
        let fstat: ReturnType<typeof statSync>
        try { fstat = statSync(absFile) } catch { continue }
        if (fstat.mtimeMs < fromMs) continue
        try {
          const data = readFileSync(absFile, 'utf-8')
          for (const line of data.split('\n')) {
            if (!line) continue
            let e: any
            try { e = JSON.parse(line) } catch { continue }
            if (e.type !== 'user' || e.isMeta) continue
            const ts = e.timestamp ? Date.parse(e.timestamp) : 0
            if (!ts || ts < fromMs || ts >= toMs) continue
            const content = e.message?.content
            if (typeof content === 'string') {
              if (content.startsWith('<local-command') || content.startsWith('<command-name>')) continue
              total++
            } else if (Array.isArray(content)) {
              const hasToolResult = content.some((b: any) => b && b.type === 'tool_result')
              if (hasToolResult) continue
              total++
            }
          }
        } catch { /* skip unreadable file */ }
      }
    }
  } catch { /* ignore */ }
  return total
}

// The fleet's remaining quota, as the overview strip shows it. Same file and
// the same staleness threshold the quota monitor uses, so the strip and the
// alert can never disagree about what the fleet has left. QUOTAMOD1005: on a
// setup-token install the statusLine block never comes; the
// agent-state-observer mod's readings do. The fresher of the two wins, and the
// snapshot says which one it is. Shared with the operator status
// (DASHOPERATOR1005), so the two surfaces cannot disagree either.
//
// QUOTAPLAN1014: only the agents on the fleet subscription feed this number.
// An agent on its own seat (authMode own_team, a named plan, its own config
// dir) reports that seat's windows, and its 95% must not read as the fleet's
// -- nor brake the fleet. Those seats come back separately, from
// readSeatQuotas. The statusLine file stays fleet-only: it is written by the
// host session's statusLine, which runs on the shared login.
export function readFleetQuota(nowSec: number): QuotaSnapshot {
  const maxAgeSec = Number(process.env.QUOTA_MAX_AGE_SEC) || DEFAULT_MAX_AGE_SEC
  const keys = agentQuotaKeys()
  return chooseQuotaSnapshot(
    readQuotaSnapshot(join(PROJECT_ROOT, 'store', '.claude-rate-limits.json'), nowSec, maxAgeSec),
    readModQuotaSnapshot(STATE_OBSERVER_STATE_DIR, nowSec, maxAgeSec, (a) => (keys.get(a) ?? 'fleet') === 'fleet'),
  )
}

export interface SeatQuota {
  /** quotaPlanKey: own:<agent>, plan:<id>, dir:<hash> or tok:<hash>. */
  key: string
  /** Display names of the agents on this seat, for the strip's label. */
  label: string
  agents: string[]
  quota: QuotaSnapshot
}

/** Every sub-agent's quota key; an agent missing from the map (the main agent, a stray state file) is fleet. */
function agentQuotaKeys(): Map<string, string> {
  const keys = new Map<string, string>()
  for (const a of listAgentNames()) {
    keys.set(a, quotaPlanKey(a, {
      authMode: readAgentAuthMode(a),
      claudePlan: readAgentClaudePlan(a),
      claudeConfigDir: readAgentClaudeConfigDir(a),
      oauthTokenFile: readAgentOauthTokenFilePath(a),
    }))
  }
  return keys
}

/**
 * The agent's own setup-token path, when the setting is valid. An invalid one
 * refuses the launch (agent-oauth-token-file.ts), so it never runs on any seat.
 */
function readAgentOauthTokenFilePath(agent: string): string | null {
  let raw = '{}'
  try { raw = readFileSync(join(agentDir(agent), 'agent-config.json'), 'utf-8') } catch { /* no config: unset */ }
  const setting = resolveOauthTokenFileSetting(raw)
  return setting.state === 'set' ? setting.path : null
}

/**
 * One snapshot per non-fleet seat, from the observer mod's readings of the
 * agents on it. A seat is listed even with no reading ('missing'): the strip
 * then says the number is unknown instead of hiding that the seat exists.
 */
export function readSeatQuotas(nowSec: number): SeatQuota[] {
  const maxAgeSec = Number(process.env.QUOTA_MAX_AGE_SEC) || DEFAULT_MAX_AGE_SEC
  const seats = new Map<string, string[]>()
  for (const [agent, key] of agentQuotaKeys()) {
    if (key === 'fleet') continue
    seats.set(key, [...(seats.get(key) ?? []), agent])
  }
  return [...seats].sort(([a], [b]) => a.localeCompare(b)).map(([key, agents]) => ({
    key,
    label: agents.map(readAgentDisplayName).join(', '),
    agents,
    quota: readModQuotaSnapshot(STATE_OBSERVER_STATE_DIR, nowSec, maxAgeSec, (a) => agents.includes(a)),
  }))
}

export async function tryHandleOverview(ctx: RouteContext): Promise<boolean> {
  const { req, res, path, method } = ctx

  if (path === '/api/overview' && method === 'GET') {
    const subAgents = listAgentNames()
    const running = subAgents.filter(n => isAgentRunning(n)).length + 1
    const total = subAgents.length + 1

    const db0 = getDb()
    const memStats = db0.prepare("SELECT COUNT(*) as c FROM memories").get() as { c: number }
    const memCats = db0.prepare("SELECT COUNT(DISTINCT category) as c FROM memories").get() as { c: number }

    const startOfDay = new Date()
    startOfDay.setHours(0, 0, 0, 0)
    const startTs = startOfDay.getTime()
    const yesterday = startTs - 24 * 60 * 60 * 1000
    const schedToday = countTaskRunsBetween(startTs)
    const schedYesterday = countTaskRunsBetween(yesterday, startTs)
    const userTurns = countUserTurns(startTs)
    const userTurnsPrev = countUserTurns(yesterday, startTs)
    const tasksToday = schedToday + userTurns
    const tasksYesterday = schedYesterday + userTurnsPrev

    let skillCount = 0
    let skillsToday = 0
    const skillsDir = join(homedir(), '.claude', 'skills')
    if (existsSync(skillsDir)) {
      for (const entry of readdirSync(skillsDir)) {
        const skillFile = join(skillsDir, entry, 'SKILL.md')
        if (existsSync(skillFile)) {
          skillCount++
          try {
            const mtime = statSync(skillFile).mtimeMs
            if (mtime >= startTs) skillsToday++
          } catch { /* ignore */ }
        }
      }
    }

    const activity: Array<{ icon: string; text: string; at: number }> = []
    try {
      const memRows = db0.prepare("SELECT content, created_at, agent_id FROM memories ORDER BY created_at DESC LIMIT 6").all() as { content: string; created_at: number; agent_id: string }[]
      for (const r of memRows) {
        activity.push({
          icon: 'memory',
          text: `${r.agent_id}: ${r.content.slice(0, 80)}${r.content.length > 80 ? '…' : ''}`,
          at: r.created_at * 1000,
        })
      }
    } catch { /* ignore */ }
    try {
      const msgRows = db0.prepare("SELECT from_agent, to_agent, content, created_at FROM agent_messages ORDER BY created_at DESC LIMIT 4").all() as { from_agent: string; to_agent: string; content: string; created_at: number }[]
      for (const r of msgRows) {
        activity.push({
          icon: 'delegate',
          text: `${r.from_agent} → ${r.to_agent}: ${r.content.slice(0, 60)}${r.content.length > 60 ? '…' : ''}`,
          at: r.created_at * 1000,
        })
      }
    } catch { /* ignore */ }
    activity.sort((a, b) => b.at - a.at)

    const agentsForTeam: Array<{ id: string; label: string; role: string; running: boolean; hasAvatar: boolean; avatarUrl: string }> = []
    const mainHasAvatar = [
      join(PROJECT_ROOT, 'store', 'marveen-avatar.png'),
      join(PROJECT_ROOT, 'store', 'marveen-avatar.jpg'),
    ].some(existsSync)
    agentsForTeam.push({
      id: MAIN_AGENT_ID,
      label: currentBotName(),
      role: 'main',
      running: true,
      hasAvatar: mainHasAvatar,
      avatarUrl: `/api/marveen/avatar`,
    })
    for (const a of subAgents) {
      const team = readAgentTeam(a)
      agentsForTeam.push({
        id: a,
        label: readAgentDisplayName(a),
        role: team.role,
        running: isAgentRunning(a),
        hasAvatar: existsSync(join(agentDir(a), 'avatar.png')),
        avatarUrl: `/api/agents/${encodeURIComponent(a)}/avatar`,
      })
    }
    const quota = readFleetQuota(Math.floor(Date.now() / 1000))
    const quotaSeats = readSeatQuotas(Math.floor(Date.now() / 1000))
    // Separate source (scripts/usage-collect.py), separate freshness rule --
    // see src/web/quota.ts for why this isn't folded into readQuotaSnapshot.
    const fableMaxAgeSec = Number(process.env.QUOTA_FABLE_MAX_AGE_SEC) || DEFAULT_FABLE_MAX_AGE_SEC
    const quotaFable = readFableSnapshot(
      join(PROJECT_ROOT, 'store', 'usage-latest.json'),
      Math.floor(Date.now() / 1000),
      fableMaxAgeSec,
    )

    jsonMaybeGzip(req, res, {
      agents: { total, running },
      tasksToday,
      tasksYesterday,
      memories: { count: memStats.c, categories: memCats.c },
      skills: { count: skillCount, today: skillsToday },
      team: agentsForTeam,
      activity: activity.slice(0, 8),
      quota,
      quotaSeats,
      quotaFable,
    })
    return true
  }

  return false
}
