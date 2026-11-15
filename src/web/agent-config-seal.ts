// Card 17901b47 (Viktor 43048 INFO 4, 43132): agent-config.json integrity, the DETECTIVE half.
//
// Measured 2026-11-15: every fleet agent runs as the same uid, agents/<name>/agent-config.json is 0644 owned by that
// uid, and no deny rule or hook stopped a sub-agent from rewriting its own or another agent's file (Write, Edit, sed -i,
// cp, mv, a redirect, python -c, node -e). The launcher reads the security-bearing fields from it at EVERY spawn, so a
// rewrite took effect at the next restart without a trace.
//
// This module does not stop a write (a separate uid is the boundary: an owner decision). It makes a change VISIBLE: the
// last accepted values of the SEALED_FIELDS live in store/agent-config-seal.json; at every spawn the launcher compares
// the file with the seal, and a difference is a logger.error plus one kanban card per distinct changed state (not one
// per spawn). The spawn goes on: a false alarm must never keep an agent down.
//
// Who moves the seal:
//   - the dashboard's own writer of a sealed field (writeAgentSecurityProfile, writeAgentTeam) moves THAT field only,
//     so a hand edit of another sealed field made before it is still reported (a whole-file re-seal would launder it);
//   - acceptAgentConfigSeal (POST /api/agents/<name>/config-seal/accept): after a deliberate hand edit (toolDeny,
//     runAsUser and excludeRootClaudeMd have no dashboard writer); the caller's X-Agent-Id is recorded;
//   - the first spawn of an agent with no seal entry (trust on first use, logged as a warning).
// Limits, said plainly: the seal file is writable by the same uid, the API token is shared by the fleet, and the
// X-Agent-Id is self-declared. A coordinated rewrite of the config AND the seal is not detected; an accidental or
// lazy rewrite of the config is.
// Imports only the base helpers: agent-config.ts and agent-team.ts call into this module, and the kanban/db side is
// handed in by the caller (SealDeps), so no import cycle and no database in a plain config read.
import { createHash } from 'node:crypto'
import { join } from 'node:path'
import { PROJECT_ROOT, STORE_DIR } from '../config.js'
import { logger } from '../logger.js'
import { atomicWriteFileSync } from './atomic-write.js'
import { readRegularFileSync } from './safe-read.js'
import { safeJoin } from './sanitize.js'

// The fields the launcher turns into permissions or trust: the profile template (securityProfile; team.role 'leader'
// resolves to 'applier'), the extra deny list, the uid, the root CLAUDE.md opt-out, and team.trustFrom (whose messages
// count as a trusted peer).
export const SEALED_FIELDS = ['securityProfile', 'toolDeny', 'runAsUser', 'excludeRootClaudeMd', 'team'] as const
export type SealedField = typeof SEALED_FIELDS[number]
export type SealedView = Record<SealedField, unknown>

export interface SealEntry {
  hash: string
  fields: SealedView
  sealedAt: number
  by: string
  // the hash of the changed state a card was already filed for (one card per distinct state)
  alertedHash?: string
  alertCardId?: string
}
interface SealFile { version: 1; agents: Record<string, SealEntry> }

export interface SealPaths { configPath: (name: string) => string; sealPath: string }
// Read lazily (a getter, not at module load): tests that mock ../config.js without STORE_DIR still import this module
// through agent-config.ts / agent-team.ts.
export const DEFAULT_SEAL_PATHS: SealPaths = {
  configPath: name => join(safeJoin(join(PROJECT_ROOT, 'agents'), name), 'agent-config.json'),
  get sealPath() { return join(STORE_DIR, 'agent-config-seal.json') },
}

// JSON with sorted object keys, so key order in the file never reads as a change
export function canonicalJson(v: unknown): string {
  if (Array.isArray(v)) return '[' + v.map(canonicalJson).join(',') + ']'
  if (v && typeof v === 'object') {
    return '{' + Object.keys(v as Record<string, unknown>).sort()
      .map(k => JSON.stringify(k) + ':' + canonicalJson((v as Record<string, unknown>)[k])).join(',') + '}'
  }
  return JSON.stringify(v === undefined ? null : v)
}

export function sealedView(config: Record<string, unknown>): SealedView {
  const out = {} as SealedView
  for (const f of SEALED_FIELDS) out[f] = f in config ? config[f] : null
  return out
}

export function viewHash(view: SealedView): string {
  return createHash('sha256').update(canonicalJson(view)).digest('hex')
}

// readRegularFileSync: a FIFO, a device or an over-cap file throws (never blocks) -> treated as unreadable
function readText(path: string): string {
  try { return readRegularFileSync(path) } catch { return '' }
}

function readSealFile(p: SealPaths): SealFile {
  try {
    const raw = JSON.parse(readText(p.sealPath))
    if (raw && raw.version === 1 && raw.agents && typeof raw.agents === 'object') return raw as SealFile
  } catch { /* missing or unreadable: a fresh file */ }
  return { version: 1, agents: {} }
}

function writeSealFile(p: SealPaths, f: SealFile): void {
  atomicWriteFileSync(p.sealPath, JSON.stringify(f, null, 2) + '\n')
}

// null: the config is missing, unsafe (a FIFO, a device, over the cap) or not a JSON object -- nothing to compare
function readConfigObject(name: string, p: SealPaths): Record<string, unknown> | null {
  try {
    const v = JSON.parse(readText(p.configPath(name)))
    return v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : null
  } catch {
    return null
  }
}

export function changedFields(sealed: SealedView, current: SealedView): SealedField[] {
  return SEALED_FIELDS.filter(f => canonicalJson(sealed[f]) !== canonicalJson(current[f]))
}

export type SealCheck =
  | { status: 'ok' }
  | { status: 'no-config' }
  | { status: 'first-seal' }
  | { status: 'changed'; fields: SealedField[]; cardId: string | null }

export interface SealDeps {
  // files the kanban card (the launcher passes db.createKanbanCard); returns the card id
  fileCard: (title: string, description: string) => string | null
  // a comment on the alert card when the change is accepted (the route passes db.addKanbanComment)
  comment: (cardId: string, author: string, text: string) => void
  now: () => number
}
export const DEFAULT_SEAL_DEPS: SealDeps = {
  fileCard: () => null,
  comment: () => {},
  now: () => Math.floor(Date.now() / 1000),
}

function describeChange(name: string, fields: SealedField[], sealed: SealEntry, current: SealedView): string {
  const lines = fields.map(f => `- ${f}: elfogadott ${canonicalJson(sealed.fields[f])} -> most ${canonicalJson(current[f])}`)
  return [
    `A launcher a(z) ${name} indításakor eltérést mért az agent-config.json biztonsági mezőiben az utolsó elfogadott`,
    `állapothoz képest (store/agent-config-seal.json, elfogadva: ${new Date(sealed.sealedAt * 1000).toISOString()}, ${sealed.by}).`,
    '',
    ...lines,
    '',
    'Az ágens a megváltozott értékkel indult (ez jelzés, nem tiltás). Ha a változás szándékos (Patrik, Klodel, a',
    'dashboard), fogadd el: POST /api/agents/' + name + '/config-seal/accept (X-Agent-Id fejléccel). Ha nem az, állítsd',
    'vissza a fájlt, és jelezd Viktornak: az ágensek ugyanazzal a uid-del írhatják egymás configját (kártya 17901b47).',
  ].join('\n')
}

/** The launcher's check, at every spawn. Never throws: a broken seal must not keep an agent down. */
export function checkAgentConfigSeal(name: string, p: SealPaths = DEFAULT_SEAL_PATHS, deps: SealDeps = DEFAULT_SEAL_DEPS): SealCheck {
  try {
    const config = readConfigObject(name, p)
    if (!config) return { status: 'no-config' }
    const current = sealedView(config)
    const hash = viewHash(current)
    const file = readSealFile(p)
    const entry = file.agents[name]
    if (!entry) {
      file.agents[name] = { hash, fields: current, sealedAt: deps.now(), by: 'first-spawn' }
      writeSealFile(p, file)
      logger.warn({ agent: name }, 'agent-config seal: no seal for this agent yet, the current security fields are sealed (trust on first use)')
      return { status: 'first-seal' }
    }
    if (entry.hash === hash) return { status: 'ok' }
    const fields = changedFields(entry.fields, current)
    logger.error({ agent: name, fields }, 'agent-config seal: the security fields differ from the last accepted state (not blocked; see the kanban card)')
    if (entry.alertedHash === hash) return { status: 'changed', fields, cardId: entry.alertCardId ?? null }
    let cardId: string | null = null
    try {
      cardId = deps.fileCard(`INTEGRITÁS: ${name} agent-config.json biztonsági mezője megváltozott (${fields.join(', ')})`,
        describeChange(name, fields, entry, current))
    } catch (err) {
      logger.error({ agent: name, err }, 'agent-config seal: filing the kanban card failed')
    }
    entry.alertedHash = hash
    if (cardId) entry.alertCardId = cardId
    writeSealFile(p, file)
    return { status: 'changed', fields, cardId }
  } catch (err) {
    logger.error({ agent: name, err }, 'agent-config seal: the check failed (the agent starts anyway)')
    return { status: 'no-config' }
  }
}

/** Accept the file's current security fields as the new seal (after a deliberate hand edit). */
export function acceptAgentConfigSeal(name: string, by: string, p: SealPaths = DEFAULT_SEAL_PATHS, deps: SealDeps = DEFAULT_SEAL_DEPS): SealEntry | null {
  const config = readConfigObject(name, p)
  if (!config) return null
  const current = sealedView(config)
  const file = readSealFile(p)
  const prev = file.agents[name]
  const entry: SealEntry = { hash: viewHash(current), fields: current, sealedAt: deps.now(), by }
  file.agents[name] = entry
  writeSealFile(p, file)
  logger.warn({ agent: name, by, fields: prev ? changedFields(prev.fields, current) : SEALED_FIELDS }, 'agent-config seal: accepted')
  if (prev?.alertCardId && prev.alertedHash === entry.hash) {
    try { deps.comment(prev.alertCardId, by, `Elfogadva (POST config-seal/accept, X-Agent-Id: ${by}).`) } catch { /* the seal is moved either way */ }
  }
  return entry
}

/** A dashboard writer of ONE sealed field moves that field only; the others keep their accepted value. */
export function sealDashboardWrite(name: string, field: SealedField, value: unknown, p: SealPaths = DEFAULT_SEAL_PATHS, now: () => number = DEFAULT_SEAL_DEPS.now): void {
  try {
    const file = readSealFile(p)
    const entry = file.agents[name]
    if (!entry) return // no seal yet: the next spawn seals the whole view (trust on first use)
    // as the file will read it back: JSON drops an undefined member, which would otherwise read as a change
    const stored = value === undefined ? null : JSON.parse(JSON.stringify(value))
    entry.fields = { ...entry.fields, [field]: stored }
    entry.hash = viewHash(entry.fields)
    entry.sealedAt = now()
    entry.by = `dashboard:${field}`
    writeSealFile(p, file)
  } catch (err) {
    logger.error({ agent: name, field, err }, 'agent-config seal: moving the seal after a dashboard write failed')
  }
}

/** For GET /api/agents/<name>/config-seal: the seal and whether the file matches it. */
export function agentConfigSealStatus(name: string, p: SealPaths = DEFAULT_SEAL_PATHS): { sealed: boolean; matches: boolean | null; changed: SealedField[]; sealedAt: number | null; by: string | null } {
  const entry = readSealFile(p).agents[name]
  const config = readConfigObject(name, p)
  if (!entry) return { sealed: false, matches: null, changed: [], sealedAt: null, by: null }
  if (!config) return { sealed: true, matches: null, changed: [], sealedAt: entry.sealedAt, by: entry.by }
  const changed = changedFields(entry.fields, sealedView(config))
  return { sealed: true, matches: changed.length === 0, changed, sealedAt: entry.sealedAt, by: entry.by }
}
