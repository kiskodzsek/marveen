// Card 0069544d (Viktor 43450 LELET 2): the skills routes that write or remove a SKILL.md answered any token caller.
// A SKILL.md is instructions the agent loads, so one sub-agent could change another agent's instructions with the
// shared dashboard token: the class of cards a8944247 and 4cd20267.
//
// Two routers, one rule:
// - routes/agents-skills.ts: POST /api/agents/<n>/skills (a generated SKILL.md), POST .../skills/import (a zip
//   unpacked into the skills dir), DELETE .../skills/<s>. For the MAIN agent the skills dir is the global
//   ~/.claude/skills, which every agent of the fleet loads, so these also wrote and removed fleet-wide skills.
// - routes/skills.ts: POST /api/skills, POST /api/skills/import, POST /api/skills/<s>/assign (copies a global skill
//   into agents, removes it from others) and PUT /api/skills/<s> (replaces a global SKILL.md with the body).
//
// Measured before the card (work/0069544d/callers.py): no sub-agent and no script or skill calls any of them; the
// dashboard UI (web/app.js) does, as a session. Agents make their own skills by writing files, not through this API.
// The caller rule is sealedWriteRefusal's, agentFileWriteRefusal's and connectorWriteRefusal's: a token caller that
// names a sub-agent in X-Agent-Id. X-Agent-Id is self-declared, so this is an accident-level gate, not a boundary.
//
// Not covered: the reads (GET / HEAD: the lists, a skill's detail, /api/skills/export).

export type SkillCallerAuth = { kind: string; agent?: string }

const AGENT_SKILLS_RX = /^\/api\/agents\/[^/]+\/skills(?:\/|$)/

/** The writing skills routes: any method but GET / HEAD on /api/skills or below it, or on /api/agents/<n>/skills or
 *  below it. A new writing route under these prefixes is covered without a change here. */
export function isSkillWrite(path: string, method: string): boolean {
  if (method === 'GET' || method === 'HEAD') return false
  return path === '/api/skills' || path.startsWith('/api/skills/') || AGENT_SKILLS_RX.test(path)
}

export function skillWriteRefusal(
  auth: SkillCallerAuth | undefined | null,
  mainAgentId: string,
  path: string,
  method: string,
): string | null {
  if (!isSkillWrite(path, method)) return null
  if (auth?.kind === 'token' && auth.agent && auth.agent !== mainAgentId) {
    return `${method} ${path.slice(0, 120)} (an agent's or the fleet's SKILL.md) is changed by the dashboard or the ` +
      `main agent, not by ${auth.agent.slice(0, 64)}; ask the main agent (card 0069544d).`
  }
  return null
}
