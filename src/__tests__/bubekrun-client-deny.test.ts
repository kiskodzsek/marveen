import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { existsSync, readFileSync, rmSync } from 'node:fs'

// Card 05836cea (Klodel 53700, Viktor 53686 and 53693): the root-owned /usr/local/bubek/bin/bubekrun-client runs the
// BubekAI runner as _bubekrun, and every agent shares one uid. Every sub-agent not on the owner's .env key
// BUBEKRUN_CLIENT_AGENTS gets the deny rule Bash(*bubekrun-client*), rebuilt at every settings write; no key = every
// sub-agent denied; the main agent is never granted by the list. The .env read is mocked: the test sets the key.
const env: { BUBEKRUN_CLIENT_AGENTS?: string } = {}
vi.mock('../env.js', () => ({
  readEnvFile: (keys?: string[]) => {
    const out: Record<string, string> = {}
    for (const k of keys ?? []) if (k in env) out[k] = (env as Record<string, string>)[k]
    return out
  },
}))

const {
  writeAgentSettingsFromProfile, agentSettingsPath, BUBEKRUN_CLIENT_DENY_RULES,
  bubekrunClientGrantedAgents, agentMayRunBubekrunClient,
} = await import('../web/agent-scaffold.js')
const { agentDir } = await import('../web/agent-config.js')
const { loadProfileTemplate } = await import('../web/profiles.js')
const { MAIN_AGENT_ID } = await import('../config.js')

const NAME = 'bubekrun-deny-test-agent'
const OTHER = 'bubekrun-deny-test-other'
const RULE = 'Bash(*bubekrun-client*)'

function denyOf(name: string): string[] {
  return JSON.parse(readFileSync(agentSettingsPath(name), 'utf-8')).permissions.deny as string[]
}
function write(name: string): void {
  const profile = loadProfileTemplate('default')
  if (!profile) throw new Error('default profile missing')
  writeAgentSettingsFromProfile(name, profile)
}

beforeEach(() => {
  delete env.BUBEKRUN_CLIENT_AGENTS
  for (const n of [NAME, OTHER]) {
    if (existsSync(agentDir(n))) throw new Error(`refusing: ${agentDir(n)} already exists`)
  }
})
afterEach(() => {
  for (const n of [NAME, OTHER]) rmSync(agentDir(n), { recursive: true, force: true })
})

describe('bubekrun-client grant list', () => {
  it('the rule is the one text rule', () => {
    expect([...BUBEKRUN_CLIENT_DENY_RULES]).toEqual([RULE])
  })

  it('parses comma- and space-separated ids, drops empties', () => {
    expect(bubekrunClientGrantedAgents('dave')).toEqual(['dave'])
    expect(bubekrunClientGrantedAgents(' dave, pulzus  x ')).toEqual(['dave', 'pulzus', 'x'])
    expect(bubekrunClientGrantedAgents(',,')).toEqual([])
    expect(bubekrunClientGrantedAgents('')).toEqual([])
    expect(bubekrunClientGrantedAgents(undefined)).toEqual([])
  })

  it('Viktor 53724 B1: a trailing # comment grants nobody it names', () => {
    expect(bubekrunClientGrantedAgents('dave # not kernel yet')).toEqual(['dave'])
    expect(agentMayRunBubekrunClient('kernel', 'dave # not kernel yet')).toBe(false)
    expect(agentMayRunBubekrunClient('not', 'dave # not kernel yet')).toBe(false)
    expect(bubekrunClientGrantedAgents('dave#kernel')).toEqual(['dave'])
    // the .env reader leaves the quotes when a comment follows: a quoted word is not an id, so nobody is granted
    expect(bubekrunClientGrantedAgents('"dave" # kernel later')).toEqual([])
    expect(agentMayRunBubekrunClient('kernel', '"dave" # kernel later')).toBe(false)
  })

  it('one word that is not an agent id empties the whole list (fail closed)', () => {
    expect(bubekrunClientGrantedAgents('dave,Kernel')).toEqual([])
    expect(bubekrunClientGrantedAgents('dave ker​nel')).toEqual([])
    expect(bubekrunClientGrantedAgents('dave,-x')).toEqual([])
    expect(bubekrunClientGrantedAgents('dave,../x')).toEqual([])
    expect(bubekrunClientGrantedAgents(`dave,${'a'.repeat(42)}`)).toEqual([])
    expect(agentMayRunBubekrunClient('dave', 'dave,Kernel')).toBe(false)
  })

  it('an exact id only: no prefix, substring or case match', () => {
    expect(agentMayRunBubekrunClient('dave', 'dave')).toBe(true)
    expect(agentMayRunBubekrunClient('dave2', 'dave')).toBe(false)
    expect(agentMayRunBubekrunClient('dav', 'dave')).toBe(false)
    expect(agentMayRunBubekrunClient('Dave', 'dave')).toBe(false)
    expect(agentMayRunBubekrunClient('viktor', 'dave')).toBe(false)
  })

  it('no key or an empty key grants nobody', () => {
    expect(agentMayRunBubekrunClient('dave', '')).toBe(false)
    expect(agentMayRunBubekrunClient('dave')).toBe(false) // env mock: key absent
  })

  it('the main agent is never granted, even when listed', () => {
    expect(agentMayRunBubekrunClient(MAIN_AGENT_ID, MAIN_AGENT_ID)).toBe(false)
    expect(agentMayRunBubekrunClient(MAIN_AGENT_ID, `dave,${MAIN_AGENT_ID}`)).toBe(false)
  })
})

describe('writeAgentSettingsFromProfile', () => {
  it('no key: a sub-agent gets the rule, once, and keeps it at a respawn', () => {
    write(NAME)
    expect(denyOf(NAME).filter((r) => r === RULE)).toHaveLength(1)
    write(NAME)
    expect(denyOf(NAME).filter((r) => r === RULE)).toHaveLength(1)
  })

  it('a granted agent has no rule; an agent off the list on the same key has it', () => {
    env.BUBEKRUN_CLIENT_AGENTS = `${NAME}`
    write(NAME)
    write(OTHER)
    expect(denyOf(NAME)).not.toContain(RULE)
    expect(denyOf(OTHER)).toContain(RULE)
  })

  it('removing the grant brings the rule back at the next write', () => {
    env.BUBEKRUN_CLIENT_AGENTS = NAME
    write(NAME)
    expect(denyOf(NAME)).not.toContain(RULE)
    delete env.BUBEKRUN_CLIENT_AGENTS
    write(NAME)
    expect(denyOf(NAME)).toContain(RULE)
  })

  it('a profile that already carries the rule still yields it once', () => {
    const profile = loadProfileTemplate('default')
    if (!profile) throw new Error('default profile missing')
    const withRule = { ...profile, filesystem: { ...profile.filesystem, deny: [...profile.filesystem.deny, RULE] } }
    writeAgentSettingsFromProfile(NAME, withRule)
    expect(denyOf(NAME).filter((r) => r === RULE)).toHaveLength(1)
  })

  it('the sudo pair stays for a granted agent too (no new exception)', () => {
    env.BUBEKRUN_CLIENT_AGENTS = NAME
    write(NAME)
    expect(denyOf(NAME)).toEqual(expect.arrayContaining(['Bash(sudo:*)', 'Bash(*/sudo *)']))
  })
})
