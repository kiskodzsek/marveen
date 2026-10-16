#!/usr/bin/env node
// MS365GATE1015 (Viktor G1/G3, card d85d38c3): drift check between the ms365
// tool policy the email gates enforce and what is actually installed.
//
//   node scripts/hooks/ms365-policy-check.mjs [--mcp <.mcp.json>] [--endpoints <dist/endpoints.json>]
//
// Exit 0 = no drift, 1 = drift (each problem on stderr), 2 = the check itself
// could not run. Run it before turning send-mail on (F1) and after any change
// to the ms365 entry of .mcp.json. The vitest suite runs the same functions
// against a fixture and, when present, the live .mcp.json.
import { readFileSync, existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
export const POLICY_PATH = join(HERE, 'ms365-tool-policy.json')
const PACKAGE = '@softeria/ms-365-mcp-server'
const SERVER_NAME_RE = /ms-?365/i

export function loadPolicy(path = POLICY_PATH) {
  return JSON.parse(readFileSync(path, 'utf-8'))
}

// The policy against the server's own tool list (dist/endpoints.json, or the
// fixture copy of it): every name the policy uses exists, every tool with a
// *.Send scope is outbound, and nothing outbound sits on the read/draft list.
// The policy's local_tools (graph-tools.js tool:<name> entries, not in
// endpoints.json) also count as tool names of the server.
export function endpointsDrift(endpoints, policy) {
  const problems = []
  const list = Array.isArray(endpoints) ? endpoints : endpoints.endpoints
  const norm = list.map((e) => ({
    tool: e.tool ?? e.toolName,
    scopes: [e.scopes, e.workScopes].flat(2).filter((x) => typeof x === 'string'),
  }))
  const names = new Set([...norm.map((e) => e.tool), ...(policy.local_tools ?? [])])
  const outbound = new Set(policy.outbound)
  for (const key of ['read_draft', 'anchored_send', 'outbound']) {
    for (const op of policy[key]) {
      if (!names.has(op)) problems.push(`${key}: ${op} is not a tool of the server`)
    }
  }
  for (const op of policy.read_draft) {
    if (outbound.has(op)) problems.push(`read_draft: ${op} is also outbound`)
  }
  for (const op of policy.anchored_send) {
    if (!outbound.has(op)) problems.push(`anchored_send: ${op} is not in outbound (a renamed server would not be gated)`)
  }
  for (const e of norm) {
    if (e.scopes.some((s) => /\.Send(\.|$)/.test(s)) && !outbound.has(e.tool)) {
      problems.push(`outbound: ${e.tool} has a send scope (${e.scopes.join(', ')}) but is not on the list`)
    }
  }
  return problems
}

// The live .mcp.json: every server running the softeria package carries ms365
// in its name (the whole-server matcher, G3), is pinned to the reviewed version
// (a new version means new tools and a new review), and exposes only
// read/draft tools plus the anchored send.
export function mcpConfigDrift(mcpJson, policy) {
  const problems = []
  const servers = mcpJson?.mcpServers ?? {}
  const allowed = new Set([...policy.read_draft, ...policy.anchored_send])
  for (const [name, cfg] of Object.entries(servers)) {
    const args = Array.isArray(cfg?.args) ? cfg.args.map(String) : []
    const pkg = [String(cfg?.command ?? ''), ...args].find((a) => a.includes(PACKAGE))
    if (!pkg) continue
    if (!SERVER_NAME_RE.test(name)) {
      problems.push(`${name}: runs ${PACKAGE} but its name has no ms365/ms-365, so the whole-server gate does not reach it`)
    }
    const version = pkg.split(`${PACKAGE}@`)[1]
    if (version !== policy.reviewed_version) {
      problems.push(`${name}: ${PACKAGE}@${version ?? '(unpinned)'} is not the reviewed ${policy.reviewed_version}`)
    }
    const i = args.indexOf('--enabled-tools')
    const re = i >= 0 ? args[i + 1] : undefined
    if (!re) {
      problems.push(`${name}: no --enabled-tools, every tool of the server is exposed`)
      continue
    }
    const m = /^\^\(([a-z0-9|-]+)\)\$$/.exec(re)
    if (!m) {
      problems.push(`${name}: --enabled-tools is not a plain ^(a|b|...)$ list, so it cannot be checked: ${re}`)
      continue
    }
    for (const op of m[1].split('|')) {
      if (!allowed.has(op)) problems.push(`${name}: --enabled-tools exposes ${op}, which is not read_draft or anchored_send`)
    }
  }
  return problems
}

function main(argv) {
  const opt = (flag) => {
    const i = argv.indexOf(flag)
    return i >= 0 ? argv[i + 1] : undefined
  }
  const mcpPath = resolve(opt('--mcp') ?? join(HERE, '..', '..', '.mcp.json'))
  const endpointsPath = opt('--endpoints')
  let problems = []
  try {
    const policy = loadPolicy()
    if (!existsSync(mcpPath)) throw new Error(`no .mcp.json at ${mcpPath}`)
    problems = problems.concat(mcpConfigDrift(JSON.parse(readFileSync(mcpPath, 'utf-8')), policy))
    if (endpointsPath) {
      problems = problems.concat(endpointsDrift(JSON.parse(readFileSync(endpointsPath, 'utf-8')), policy))
    }
  } catch (e) {
    process.stderr.write(`ms365-policy-check: could not run: ${e}\n`)
    return 2
  }
  for (const p of problems) process.stderr.write(`ms365-policy-check: ${p}\n`)
  if (!problems.length) process.stdout.write('ms365-policy-check: OK\n')
  return problems.length ? 1 : 0
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main(process.argv.slice(2))
}
