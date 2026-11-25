// Where the agent-key gate meets the request (card 45dea12e; security review 53307). web.ts calls enforceAgentKey with
// the very `path` (URL.pathname), `method` and `url` its route handlers match, after the auth and operator gates and
// before any handler. The live lookups live here too, so agent-key-gate.ts is tested without a database.

import type http from 'node:http'
import { getAgentMessage, getDb, getKanbanCard } from '../db.js'
import { OWNER_NAME, currentOwnerName } from '../config.js'
import { logger } from '../logger.js'
import { agentKeyGateDecision, agentKeyRule, type AgentGateDeps, type AgentGateVerdict } from './agent-key-gate.js'
import { preReadBody } from './http-helpers.js'

/** Each lookup reads exactly the row the handler of the same request reads. */
export function agentGateDeps(): AgentGateDeps {
  return {
    message: (id) => {
      const m = getAgentMessage(id)
      return m ? { from_agent: m.from_agent, to_agent: m.to_agent } : undefined
    },
    memory: (id) =>
      getDb().prepare('SELECT agent_id, category FROM memories WHERE id = ?').get(id) as { agent_id: string; category: string } | undefined,
    card: (id) => {
      const c = getKanbanCard(id)
      return c ? { assignee: c.assignee ?? null } : undefined
    },
    ownerNames: [OWNER_NAME, currentOwnerName()],
  }
}

/**
 * true = the request was refused and answered (403, or 404 for a row that is not the agent's); false = it may go on to
 * the handlers. When a rule reads the body it is read here once, and the handler's readBody gets the same bytes.
 */
export async function enforceAgentKey(
  agent: string,
  keyId: number,
  req: http.IncomingMessage,
  res: http.ServerResponse,
  method: string,
  path: string,
  url: URL,
  deps: () => AgentGateDeps = agentGateDeps,
): Promise<boolean> {
  const rule = agentKeyRule(method, path)
  let verdict: AgentGateVerdict
  if (rule === null) {
    verdict = { ok: false, status: 403, reason: 'agent key: endpoint not allowed' }
  } else {
    try {
      const body = rule.needsBody ? await preReadBody(req) : null
      verdict = agentKeyGateDecision(agent, method, path, url, body, deps())
    } catch {
      verdict = { ok: false, status: 403, reason: 'agent key: the request could not be judged' }
    }
  }
  if (verdict.ok) return false
  logger.warn({ path, method, agent, keyId, reason: verdict.reason }, 'agent key gate: denied')
  res.writeHead(verdict.status, { 'Content-Type': 'application/json' })
  res.end(JSON.stringify(verdict.status === 404 ? { error: verdict.reason } : { error: 'Forbidden for this credential', reason: verdict.reason }))
  return true
}
