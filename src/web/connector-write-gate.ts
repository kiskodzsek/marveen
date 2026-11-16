// Card 4cd20267 (Viktor 43450 LELET 1): the connectors routes that write MCP configuration were open to every token
// caller. POST /api/connectors/<n>/assign wrote a connector (with its env) into any agent's .mcp.json and, through
// allAgents, removed it from others; DELETE /api/connectors/<n> removed it from every config (each agent's .mcp.json,
// the project .mcp.json, ~/.claude.json). The same class as card a8944247: one sub-agent changing the MCP servers
// (tools and the commands they start) of another agent, with the shared dashboard token.
//
// The other writing routes of the same router are the same class or worse, and are refused the same way:
// POST /api/connectors (`claude mcp add`: a stdio command into ~/.claude.json or the project .mcp.json, which the main
// agent starts), the external project paths (whose .mcp.json files assign and DELETE then reach), and the GitHub repos
// (git clone / pull and npm install, which runs the package's install scripts). Measured before the card (work/
// 4cd20267/callers.py): no sub-agent and no script or skill calls any of them; the dashboard UI (web/app.js) does, as
// a session. The caller rule is sealedWriteRefusal's and agentFileWriteRefusal's: a token caller that names a
// sub-agent in X-Agent-Id. X-Agent-Id is self-declared, so this stops an honest sub-agent's mistake, not one that
// leaves the header out (an accident-level gate, like the seal's).
//
// The MCP catalog routes of the same router (Viktor 43488 LELET 1): POST /api/mcp-catalog/<id>/install runs `claude mcp
// add --scope user` for a catalog item (with its env, the user's values vaulted and bound) and DELETE
// /api/mcp-catalog/<id>/uninstall runs `claude mcp remove`, so they change the same configuration and are refused the
// same way: any method but GET / HEAD below /api/mcp-catalog/. The only caller is the dashboard UI (web/app.js).
//
// Not covered here: the reads (GET, the catalog list included), POST /api/connectors/refresh (it re-reads `claude mcp list` into the cache and
// writes no configuration), the vault routes of the same router (their own model, vault-acl.ts) and
// /api/connectors-hu (another router).

export type ConnectorCallerAuth = { kind: string; agent?: string }

/** The writing connectors routes: any method but GET / HEAD on /api/connectors or below it, except the cache refresh,
 *  and below /api/mcp-catalog/ (install, uninstall). A new writing route under either prefix is covered without a
 *  change here. */
export function isConnectorWrite(path: string, method: string): boolean {
  if (method === 'GET' || method === 'HEAD') return false
  if (path.startsWith('/api/mcp-catalog/')) return true
  if (path !== '/api/connectors' && !path.startsWith('/api/connectors/')) return false
  return path !== '/api/connectors/refresh'
}

export function connectorWriteRefusal(
  auth: ConnectorCallerAuth | undefined | null,
  mainAgentId: string,
  path: string,
  method: string,
): string | null {
  if (!isConnectorWrite(path, method)) return null
  if (auth?.kind === 'token' && auth.agent && auth.agent !== mainAgentId) {
    return `${method} ${path.slice(0, 120)} (an MCP connector configuration) is changed by the dashboard or the main ` +
      `agent, not by ${auth.agent.slice(0, 64)}; ask the main agent (card 4cd20267).`
  }
  return null
}
