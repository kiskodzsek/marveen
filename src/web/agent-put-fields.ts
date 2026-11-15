// Which fields PUT /api/agents/:name will actually act on.
//
// Split out of the route handler so the decision is testable without standing
// up an HTTP context: the handler itself needs a request, a response, the
// filesystem and a live agent directory, which is enough friction that the rule
// would have gone untested — and this rule is exactly the kind that needs a test,
// because its failure mode is silence.
//
// Background: the handler used to destructure the fields it understood and drop
// everything else, then answer 200 {ok:true}. On 2026-07-27 a securityProfile
// was PUT here four times, acknowledged every time and never applied; the agent
// stayed in a mode where it stopped for approval on every tool call and was
// unusable for hours while the API kept reporting success.

export const AGENT_PUT_WRITABLE_FIELDS = [
  'claudeMd', 'soulMd', 'mcpJson', 'model',
  'authMode', 'apiKey', 'claudePlan', 'memoryIsolation',
  'modelProfile', 'customProvider',
] as const

// Fields that exist on the agent but belong to a different endpoint. Listed
// separately from "unknown" so the error can say where to go instead of just
// refusing — a caller who gets "unsupported" with no alternative tends to go
// looking for a way around the check.
const ELSEWHERE: Record<string, (name: string) => string> = {
  securityProfile: name =>
    `use PUT /api/agents/${encodeURIComponent(name)}/security with {"profile": "..."} instead`,
}

export type AgentPutFieldCheck =
  | { ok: true }
  | { ok: false; rejected: string[]; message: string }

// Rejects the UNKNOWN rather than allow-listing the known at the call site: a
// field someone adds to the client tomorrow surfaces as a loud 400 instead of
// disappearing quietly. Same inversion as the permission-mode chip — what we do
// not recognise is precisely what we must not hide.
export function checkAgentPutFields(name: string, body: unknown): AgentPutFieldCheck {
  if (body === null || typeof body !== 'object') {
    return { ok: false, rejected: [], message: 'Request body must be a JSON object.' }
  }
  const writable = new Set<string>(AGENT_PUT_WRITABLE_FIELDS)
  const rejected = Object.keys(body as Record<string, unknown>).filter(k => !writable.has(k))
  if (!rejected.length) return { ok: true }

  const hints = rejected.filter(k => k in ELSEWHERE).map(k => `${k}: ${ELSEWHERE[k](name)}`)
  const message =
    `Unsupported field(s) for this endpoint: ${rejected.join(', ')}.` +
    (hints.length ? ` ${hints.join('; ')}.` : '')
  return { ok: false, rejected, message }
}

// Same rule for the per-agent CONFIG endpoints (auto-restart, context-guard).
// Those hand the body to a normalize*Config() that rebuilds a fresh object from
// the keys it knows, so an unknown key is never rejected — it is never LOOKED
// AT. The endpoint then answers 200 {ok:true} with the saved config, which is
// indistinguishable from success:
//
//   PUT /api/agents/<name>/context-guard
//     {..., "idleFlushEnabled": true, "totalNonsenseField": 42}
//   -> 200 {"ok":true,"contextGuard":{ ...only the seven known fields... }}
//
// That is the securityProfile failure above, one endpoint over: an agent can
// be configured for a tier that does not exist while every call reports
// success, and nothing surfaces the gap until the behaviour fails to appear.
//
// Deliberately narrower than "validate the body". The route comments state that
// a partial/garbled payload is COERCED rather than rejected, and that stays
// true: this checks KEYS, not values. A bad number still falls back to its
// default; a misspelled key is now loud.
export function checkConfigPutFields(body: unknown, knownFields: readonly string[]): AgentPutFieldCheck {
  if (body === null || typeof body !== 'object') {
    return { ok: false, rejected: [], message: 'Request body must be a JSON object.' }
  }
  const known = new Set<string>(knownFields)
  const rejected = Object.keys(body as Record<string, unknown>).filter(k => !known.has(k))
  if (!rejected.length) return { ok: true }
  return {
    ok: false,
    rejected,
    message:
      `Unknown field(s) for this config endpoint: ${rejected.join(', ')}. ` +
      `Known fields: ${knownFields.join(', ')}.`,
  }
}

// Card a8944247: claudeMd, soulMd and mcpJson of PUT /api/agents/:name are an agent's instructions (CLAUDE.md, SOUL.md)
// and the MCP servers it starts (.mcp.json). The seal (card 17901b47) does not cover them, and every sub-agent holds
// the shared dashboard token, so one sub-agent could rewrite another's instructions or give it a new MCP server.
// The same caller rule as sealedWriteRefusal (card ec665017): a token caller that names a sub-agent in X-Agent-Id is
// refused, whichever agent it targets (its own files too); the dashboard UI (a session), a token caller without the
// header and the main agent are not. Caller survey 2026-11-16: no recorded token call wrote these fields; the UI's
// wizard and editor do, as a session. X-Agent-Id is self-declared, so this stops an honest sub-agent's mistake, not
// a sub-agent that leaves the header out: an accident-level gate, like the seal's.
export const AGENT_FILE_FIELDS = ['claudeMd', 'soulMd', 'mcpJson'] as const

export function agentFileWriteRefusal(
  auth: { kind: string; agent?: string } | undefined | null,
  mainAgentId: string,
  body: Record<string, unknown>,
): string | null {
  const fields = AGENT_FILE_FIELDS.filter(f => body[f] !== undefined)
  if (!fields.length) return null
  if (auth?.kind === 'token' && auth.agent && auth.agent !== mainAgentId) {
    return `${fields.join(', ')} (an agent's CLAUDE.md, SOUL.md, .mcp.json) is written by the dashboard or the main ` +
      `agent, not by ${auth.agent.slice(0, 64)}; ask the main agent (card a8944247).`
  }
  return null
}
