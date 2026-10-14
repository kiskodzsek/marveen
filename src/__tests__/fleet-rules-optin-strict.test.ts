// FLEETRULES1013, Viktor L4: the opt-in that drops the root CLAUDE.md is
// strictly `excludeRootClaudeMd: true`. fleet-rules-section.test.ts mocks the
// reader, so a refactor to a truthy check passed every test there -- and a
// `"false"` string would then silently exclude the whole root rule body. This
// file runs the REAL reader against a real agent-config.json.

import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { agentDir, readAgentExcludeRootClaudeMd } from '../web/agent-config.js'

const AGENT = 'fleetrules-optin-strict-test'

function setOptIn(value: unknown): void {
  writeFileSync(join(agentDir(AGENT), 'agent-config.json'), JSON.stringify({ excludeRootClaudeMd: value }), 'utf-8')
}

beforeAll(() => { mkdirSync(agentDir(AGENT), { recursive: true }) })
afterAll(() => { rmSync(agentDir(AGENT), { recursive: true, force: true }) })

describe('readAgentExcludeRootClaudeMd is strictly === true (Viktor L4)', () => {
  it('a string, a number or any other truthy value is not an opt-in', () => {
    for (const value of ['true', 1, 'false', 'yes', {}, [true]]) {
      setOptIn(value)
      expect(readAgentExcludeRootClaudeMd(AGENT), JSON.stringify(value)).toBe(false)
    }
  })

  it('missing, null, false and unreadable configs are not an opt-in', () => {
    for (const value of [null, false, 0, '']) {
      setOptIn(value)
      expect(readAgentExcludeRootClaudeMd(AGENT), JSON.stringify(value)).toBe(false)
    }
    writeFileSync(join(agentDir(AGENT), 'agent-config.json'), '{not json', 'utf-8')
    expect(readAgentExcludeRootClaudeMd(AGENT)).toBe(false)
  })

  it('NEGATIVE CONTROL: the boolean true is the opt-in', () => {
    setOptIn(true)
    expect(readAgentExcludeRootClaudeMd(AGENT)).toBe(true)
  })
})
