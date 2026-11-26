import { createHash } from 'node:crypto'
import { realpathSync, writeFileSync, renameSync } from 'node:fs'
import { join } from 'node:path'
import { STORE_DIR } from '../config.js'
import { readRegularFileSync } from './safe-read.js'
import { KC_V4_TEMPLATE } from './sandbox/kc-v4-template.js'

// Card 6aa0a853 (keychain read refused at the OS level), canary step (security review 54105, 54110): an agent can be
// started under a macOS sandbox profile (sandbox-exec), opted in one by one.
//
// - The opt-in lives in the dashboard's store (store/agent-sandbox.json: {"version":1,"agents":{"<agent>":"kc-v4"}}),
//   never in the agent's own agent-config.json, which the agent writes itself (review 54105 B2). Klodel or the owner
//   writes it; the narrow agent key has no endpoint for it (deny by default, #456).
// - There is no rendered profile file: the template is a constant in the code (kc-v4-template.ts), its sha256 is pinned
//   here, and the rendered text goes to `sandbox-exec -p` as one argument, so no file can be swapped (review 54110
//   V5-1). The inputs (install root, home, agent id) are canonical real paths with a strict character allowlist,
//   because they are written into the profile's SBPL strings and regexes (rule injection).
// - Fail closed (review 54110 M1): an opted-in agent whose profile cannot be rendered does not start; an agent that ran
//   sandboxed at its last start does not start when the opt-in file is gone or unreadable. An agent that ran sandboxed
//   last time and is no longer opted in starts without it, and that is reported (logger.error + a kanban card).
// - The last start's mode per agent is kept in store/agent-sandbox-state.json (written by the dashboard).

export const SANDBOX_PROFILES: Readonly<Record<string, { template: string; sha256: string }>> = Object.freeze({
  'kc-v4': { template: KC_V4_TEMPLATE, sha256: '057b2693f5eafc1ae3aa539d8850264ffea9a9d41f23f2ede72128b89c246817' },
})

export const SANDBOX_EXEC = '/usr/bin/sandbox-exec'
export const SANDBOX_OPTIN_MAX_BYTES = 64 * 1024

export interface SandboxPaths {
  optinPath: string
  statePath: string
}
// Getters, read lazily: tests that mock ../config.js without STORE_DIR still import this module.
export const DEFAULT_SANDBOX_PATHS: SandboxPaths = {
  get optinPath() { return join(STORE_DIR, 'agent-sandbox.json') },
  get statePath() { return join(STORE_DIR, 'agent-sandbox-state.json') },
}

export type SandboxDecision =
  | { kind: 'off'; downgradedFrom: string | null; warning: string | null }
  | { kind: 'on'; profile: string; text: string }
  | { kind: 'refused'; reason: string }

const AGENT_ID_RX = /^[a-z0-9][a-z0-9_-]{0,63}$/
// No regex metacharacter (the template inlines the root and the home into regexes), no quote, backslash, parenthesis,
// white space or newline (SBPL strings), no '.' (a regex metacharacter, and it keeps '..' out).
const PATH_RX = /^\/[A-Za-z0-9_/-]+$/

export class SandboxRenderError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'SandboxRenderError'
  }
}

function sha256(text: string): string {
  return createHash('sha256').update(text, 'utf8').digest('hex')
}

// The profile of one agent. `root` and `home` must already be canonical (see canonicalPath); the error messages never
// carry the template or the rendered text.
export function renderSandboxProfile(profile: string, v: { root: string; home: string; self: string }): string {
  const p = Object.hasOwn(SANDBOX_PROFILES, profile) ? SANDBOX_PROFILES[profile] : undefined
  if (p === undefined) throw new SandboxRenderError('unknown profile')
  if (sha256(p.template) !== p.sha256) throw new SandboxRenderError('template hash mismatch')
  for (const [k, x] of [['root', v.root], ['home', v.home]] as const) {
    if (typeof x !== 'string' || !PATH_RX.test(x) || x.endsWith('/') || x.includes('//')) throw new SandboxRenderError(`unsafe ${k} path`)
  }
  if (typeof v.self !== 'string' || !AGENT_ID_RX.test(v.self)) throw new SandboxRenderError('not an agent id')
  const out = p.template.split('@ROOT@').join(v.root).split('@SELF@').join(v.self).split('@HOME@').join(v.home)
  if (out.replace(/;;[^\n]*/g, '').includes('@')) throw new SandboxRenderError('placeholder left')
  return out
}

// The real path, and only when it is already the canonical form (a /var vs /private/var difference would silently
// leave the profile's rules unmatched: fail open). Throws SandboxRenderError otherwise.
export function canonicalPath(path: string): string {
  let real: string
  try {
    real = realpathSync(path)
  } catch {
    throw new SandboxRenderError('path cannot be resolved')
  }
  if (real !== path) throw new SandboxRenderError('path is not canonical')
  return real
}

type OptIn = { kind: 'missing' } | { kind: 'bad'; reason: string } | { kind: 'ok'; agents: Readonly<Record<string, string>> }

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

export function readSandboxOptIn(path: string): OptIn {
  let raw: string
  try {
    raw = readRegularFileSync(path, SANDBOX_OPTIN_MAX_BYTES)
  } catch (err) {
    if ((err as NodeJS.ErrnoException)?.code === 'ENOENT') return { kind: 'missing' }
    return { kind: 'bad', reason: 'unreadable' }
  }
  let v: unknown
  try {
    v = JSON.parse(raw)
  } catch {
    return { kind: 'bad', reason: 'not JSON' }
  }
  if (!isPlainObject(v) || v.version !== 1 || !isPlainObject(v.agents)) return { kind: 'bad', reason: 'bad shape' }
  if (Object.keys(v).some((k) => k !== 'version' && k !== 'agents')) return { kind: 'bad', reason: 'unknown key' }
  const agents: Record<string, string> = {}
  for (const [name, prof] of Object.entries(v.agents)) {
    if (!AGENT_ID_RX.test(name) || typeof prof !== 'string') return { kind: 'bad', reason: 'bad entry' }
    agents[name] = prof
  }
  return { kind: 'ok', agents: Object.freeze(agents) }
}

// The last start's profile per agent (null = not sandboxed). A missing or unreadable state is {}: nothing is known.
export function readSandboxState(path: string): Record<string, string | null> {
  try {
    const v: unknown = JSON.parse(readRegularFileSync(path, SANDBOX_OPTIN_MAX_BYTES))
    if (!isPlainObject(v) || !isPlainObject(v.agents)) return {}
    const out: Record<string, string | null> = {}
    for (const [name, e] of Object.entries(v.agents)) {
      if (isPlainObject(e) && (typeof e.profile === 'string' || e.profile === null)) out[name] = e.profile as string | null
    }
    return out
  } catch {
    return {}
  }
}

export function decideAgentSandbox(
  name: string,
  paths: SandboxPaths,
  env: { root: string; home: string; isMain: boolean; isRemote: boolean },
): SandboxDecision {
  const optin = readSandboxOptIn(paths.optinPath)
  const last = readSandboxState(paths.statePath)[name] ?? null
  if (optin.kind !== 'ok') {
    if (last !== null) return { kind: 'refused', reason: `opt-in file ${optin.kind === 'missing' ? 'missing' : optin.reason} after a sandboxed start` }
    return { kind: 'off', downgradedFrom: null, warning: optin.kind === 'bad' ? `opt-in file ${optin.reason}` : null }
  }
  const wanted = Object.hasOwn(optin.agents, name) ? optin.agents[name] : undefined
  if (wanted === undefined) return { kind: 'off', downgradedFrom: last, warning: null }
  if (env.isMain || env.isRemote) return { kind: 'refused', reason: 'only a local sub-agent can be sandboxed' }
  try {
    const text = renderSandboxProfile(wanted, { root: canonicalPath(env.root), home: canonicalPath(env.home), self: name })
    return { kind: 'on', profile: wanted, text }
  } catch (err) {
    return { kind: 'refused', reason: err instanceof SandboxRenderError ? err.message : 'render failed' }
  }
}

// The launch prefix: empty, or sandbox-exec with the profile as one single-quoted argument.
export function sandboxLaunchPrefix(d: SandboxDecision, quote: (s: string) => string): string {
  return d.kind === 'on' ? `${SANDBOX_EXEC} -p ${quote(d.text)} ` : ''
}

// Records the mode of this start (atomic: temp file + rename). A failure is reported to the caller, never thrown.
export function recordSandboxStart(name: string, profile: string | null, paths: SandboxPaths, now: number = Date.now()): boolean {
  try {
    let agents: Record<string, unknown> = {}
    try {
      const v: unknown = JSON.parse(readRegularFileSync(paths.statePath, SANDBOX_OPTIN_MAX_BYTES))
      if (isPlainObject(v) && isPlainObject(v.agents)) agents = { ...v.agents }
    } catch {
      // missing or unreadable: start over
    }
    agents[name] = { profile, at: Math.floor(now / 1000) }
    const tmp = `${paths.statePath}.tmp-${process.pid}`
    writeFileSync(tmp, JSON.stringify({ version: 1, agents }, null, 2) + '\n', { mode: 0o600 })
    renameSync(tmp, paths.statePath)
    return true
  } catch {
    return false
  }
}
