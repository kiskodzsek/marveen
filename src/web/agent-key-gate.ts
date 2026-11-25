// The server-side fence around a narrow per-agent key (card 45dea12e; security review 53307).
//
// Decided BEFORE any route handler runs, on the very `path` (URL.pathname) and `method` the router matches: an agent
// key reaches the rules below and nothing else. Deny by default: a route added later, a trailing slash, a doubled
// slash, an upper-case /API/, a HEAD or an SSE request matches no rule and is refused. The agent is the key's
// (src/web/auth-agent-keys.ts); X-Agent-Id is not read. Where a rule names a field of the body, the gate reads the
// body once (web.ts pre-reads it for readBody, so the handler parses the very same bytes) and refuses when the field
// names anyone but the key's agent. An unreadable body (not a JSON object) is refused, not passed on.
//
// Every other principal (token, device, session, federation) never reaches this file.

export type AgentGateVerdict = { ok: true } | { ok: false; status: 403 | 404; reason: string }

export interface AgentGateDeps {
  message(id: number): { from_agent: string; to_agent: string } | undefined
  memory(id: number): { agent_id: string; category: string } | undefined
  card(id: string): { assignee: string | null } | undefined
  /** The owner's names, any case (an owner's card is not an agent's to move; an agent opens one only as a JELZÉS card). */
  ownerNames: readonly string[]
}

type Body = Record<string, unknown>
interface Rule {
  method: string
  path: RegExp
  /** Whether the check reads the body (web.ts pre-reads it only then). */
  body: boolean
  check(agent: string, m: RegExpMatchArray, url: URL, body: Body | null, deps: AgentGateDeps): AgentGateVerdict
}

const OK: AgentGateVerdict = { ok: true }
const deny = (reason: string): AgentGateVerdict => ({ ok: false, status: 403, reason })
const notFound = (reason: string): AgentGateVerdict => ({ ok: false, status: 404, reason })

/** Every query key is one of `known`. */
function onlyKeys(url: URL, known: readonly string[]): boolean {
  return [...url.searchParams.keys()].every((k) => known.includes(k))
}

/** The values the request gives for the agent filter (every repeat of every alias), exactly [agent]. */
function filterIsSelf(url: URL, agent: string, aliases: readonly string[]): boolean {
  const values = aliases.flatMap((k) => url.searchParams.getAll(k))
  return values.length === 1 && values[0] === agent
}

const isSelf = (v: unknown, agent: string): boolean => typeof v === 'string' && v.trim() === agent
const absentOrSelf = (v: unknown, agent: string): boolean => v === undefined || v === null || isSelf(v, agent)
/** A signal card for the owner: "JELZÉS (<name>): ..." (the fleet rule's title shape). */
const isJelzesTitle = (v: unknown): boolean => typeof v === 'string' && v.trimStart().startsWith('JELZÉS (')
const isOwner = (v: unknown, deps: AgentGateDeps): boolean =>
  typeof v === 'string' && deps.ownerNames.some((o) => o.trim().toLowerCase() === v.trim().toLowerCase() && o.trim() !== '')

function decodeId(raw: string): string | null {
  try {
    return decodeURIComponent(raw)
  } catch {
    return null
  }
}

const RULES: readonly Rule[] = [
  // Reads the fleet tools need: the roster (agent-msg.sh sends only to a running agent) and the schedule list.
  { method: 'GET', path: /^\/api\/agents$/, body: false, check: (_a, _m, url) => (onlyKeys(url, []) ? OK : deny('agent key: no query on this endpoint')) },
  { method: 'GET', path: /^\/api\/schedules$/, body: false, check: (_a, _m, url) => (onlyKeys(url, []) ? OK : deny('agent key: no query on this endpoint')) },

  // Messages: its own mailbox, its own rows, sent as itself.
  {
    method: 'GET', path: /^\/api\/messages$/, body: false,
    check: (a, _m, url) => (onlyKeys(url, ['agent', 'status', 'limit', 'before']) && filterIsSelf(url, a, ['agent']) ? OK : deny('agent key: the mailbox filter must be agent=<self>, once')),
  },
  { method: 'POST', path: /^\/api\/messages$/, body: true, check: (a, _m, _u, b) => (isSelf(b!.from, a) ? OK : deny('agent key: from must be the key\'s agent')) },
  {
    method: 'GET', path: /^\/api\/messages\/(\d+)$/, body: false,
    check: (a, m, _u, _b, d) => {
      const row = d.message(Number(m[1]))
      return row && (row.from_agent === a || row.to_agent === a) ? OK : notFound('Message not found')
    },
  },
  {
    method: 'PUT', path: /^\/api\/messages\/(\d+)$/, body: false,
    check: (a, m, _u, _b, d) => (d.message(Number(m[1]))?.to_agent === a ? OK : notFound('Message not found')),
  },

  // Kanban: read the board, open a card (not for the owner), move a card (not the owner's) as itself, comment as itself.
  { method: 'GET', path: /^\/api\/kanban$/, body: false, check: (_a, _m, url) => (onlyKeys(url, ['agent', 'assignee', 'includeArchived']) ? OK : deny('agent key: unknown query on the board')) },
  {
    method: 'POST', path: /^\/api\/kanban$/, body: true,
    check: (_a, _m, _u, b, d) => {
      // The id is the server's to choose (review 53362 MEDIUM): a caller-chosen id is written into the dispatch line
      // the main agent and the system send ("[Kanban feladat #<id>]"), so it would put the key holder's words there.
      if (b!.id !== undefined) return deny('agent key: the card id is the server\'s to choose')
      const assignee = b!.assignee === undefined ? b!.agent : b!.assignee
      // A JELZÉS card is any agent's to open for the owner (Patrik's rule, no approval needed; review 53362).
      if (isOwner(assignee, d) && !isJelzesTitle(b!.title)) return deny('agent key: a card for the owner is only a JELZÉS card')
      return OK
    },
  },
  {
    method: 'POST', path: /^\/api\/kanban\/([^/]+)\/move$/, body: true,
    check: (a, m, _u, b, d) => {
      const id = decodeId(m[1]!)
      if (id === null) return deny('agent key: the card id is not readable')
      const card = d.card(id)
      if (!card) return notFound('Kártya nem található')
      if (isOwner(card.assignee, d)) return deny('agent key: the owner\'s card is not an agent\'s to move')
      return isSelf(b!.actor, a) ? OK : deny('agent key: actor must be the key\'s agent')
    },
  },
  { method: 'GET', path: /^\/api\/kanban\/([^/]+)\/comments$/, body: false, check: () => OK },
  { method: 'POST', path: /^\/api\/kanban\/([^/]+)\/comments$/, body: true, check: (a, _m, _u, b) => (isSelf(b!.author, a) ? OK : deny('agent key: author must be the key\'s agent')) },

  // Memories: its own rows (and the shared tier by id), written as itself, never handed to another agent.
  {
    method: 'GET', path: /^\/api\/memories$/, body: false,
    check: (a, _m, url) =>
      onlyKeys(url, ['agent', 'agent_id', 'q', 'tier', 'category', 'limit', 'mode', 'strict', 'offset']) && filterIsSelf(url, a, ['agent', 'agent_id'])
        ? OK : deny('agent key: the memory filter must be agent=<self>, once'),
  },
  { method: 'POST', path: /^\/api\/memories$/, body: true, check: (a, _m, _u, b) => (isSelf(b!.agent_id, a) ? OK : deny('agent key: agent_id must be the key\'s agent')) },
  {
    method: 'GET', path: /^\/api\/memories\/(\d+)$/, body: false,
    check: (a, m, _u, _b, d) => {
      const row = d.memory(Number(m[1]))
      return row && (row.agent_id === a || row.category === 'shared') ? OK : notFound('Memory not found')
    },
  },
  {
    method: 'GET', path: /^\/api\/memories\/(\d+)\/versions$/, body: false,
    check: (a, m, _u, _b, d) => (d.memory(Number(m[1]))?.agent_id === a ? OK : notFound('Memory not found')),
  },
  ...(['PUT', 'PATCH'] as const).map((method): Rule => ({
    method, path: /^\/api\/memories\/(\d+)$/, body: true,
    check: (a, m, _u, b, d) => {
      if (d.memory(Number(m[1]))?.agent_id !== a) return notFound('Memory not found')
      if (!absentOrSelf(b!.agent_id, a)) return deny('agent key: agent_id would hand the row to another agent')
      return absentOrSelf(b!.updated_by, a) ? OK : deny('agent key: updated_by must be the key\'s agent')
    },
  })),

  // The daily log, as itself.
  { method: 'POST', path: /^\/api\/daily-log$/, body: true, check: (a, _m, _u, b) => (isSelf(b!.agent_id, a) ? OK : deny('agent key: agent_id must be the key\'s agent')) },
]

/** The rule a request falls under, or null (refused). Exported for web.ts: it pre-reads the body only for these. */
export function agentKeyRule(method: string, path: string): { needsBody: boolean } | null {
  const r = RULES.find((x) => x.method === method && x.path.test(path))
  return r ? { needsBody: r.body } : null
}

/**
 * null-free verdict for an agent key. `body` is the raw request body when agentKeyRule said it is needed (else
 * ignored); a needed body that is not a JSON object is refused.
 */
export function agentKeyGateDecision(agent: string, method: string, path: string, url: URL, body: Buffer | null, deps: AgentGateDeps): AgentGateVerdict {
  for (const r of RULES) {
    if (r.method !== method) continue
    const m = path.match(r.path)
    if (m === null) continue
    let parsed: Body | null = null
    if (r.body) {
      try {
        const v: unknown = JSON.parse((body ?? Buffer.alloc(0)).toString('utf8'))
        if (v === null || typeof v !== 'object' || Array.isArray(v)) return deny('agent key: the body is not a JSON object')
        parsed = v as Body
      } catch {
        return deny('agent key: the body is not a JSON object')
      }
    }
    return r.check(agent, m, url, parsed, deps)
  }
  return deny('agent key: endpoint not allowed')
}
