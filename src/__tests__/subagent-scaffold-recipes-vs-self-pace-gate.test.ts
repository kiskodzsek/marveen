import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { gateDecision as selfPaceDecision } from '../../scripts/self-pace-gate.mjs'

// The sub-agent CLAUDE.md that generateClaudeMd() asks the model to copy verbatim
// must not hand the agent a recipe its own self-pace-gate denies (card aedf84be).
//
// Measured 2026-11-11: the "## Ütemezett feladatok" section told every new
// sub-agent to create its schedules with `curl -X POST .../api/schedules`, while
// scripts/self-pace-gate.mjs -- wired into every sub-agent's settings since #463
// (cd0acfe6, 2026-06-27: "a sub-agent must be INPUT-DRIVEN") -- denies exactly that
// call. The agent followed its instructions and hit a hard deny, and the deny took
// the other steps of the same Bash call down with it. The gate is the intended
// rule (governance, two audits); the instructions were stale.
//
// The check is mechanical, so the next stale recipe fails here too: every curl
// line in the generateClaudeMd prompt body is run through the gate's own
// decision function.

const __dirname = dirname(fileURLToPath(import.meta.url))
const SCAFFOLD_SRC = join(__dirname, '..', 'web', 'agent-scaffold.ts')

const src = readFileSync(SCAFFOLD_SRC, 'utf-8')
const fnStart = src.indexOf('export async function generateClaudeMd')
const fnEnd = src.indexOf('export async function generateSoulMd')
const fnBody = src.slice(fnStart, fnEnd)

// The template-literal placeholders, filled the way a generated CLAUDE.md has them.
function render(line: string): string {
  return line
    .replaceAll('${tokenPath}', '/srv/marveen/store/.dashboard-token')
    .replaceAll('${dashboardOrigin}', 'http://localhost:3420')
    .replaceAll('${MAIN_AGENT_ID}', 'marveen')
    .replaceAll('${name}', 'agent-x')
    .replaceAll('\\"', '"')
}

const curlRecipes = fnBody
  .split('\n')
  .map((l) => l.trim())
  .filter((l) => l.startsWith('curl '))
  .map(render)

const scheduleSection = (() => {
  const a = fnBody.indexOf('## Ütemezett feladatok')
  const b = fnBody.indexOf('\n## ', a + 1)
  return a >= 0 && b > a ? fnBody.slice(a, b) : ''
})()

describe('sub-agent CLAUDE.md recipes vs the sub-agent self-pace gate (card aedf84be)', () => {
  it('finds the recipes it checks (the slice must not silently empty)', () => {
    expect(fnStart).toBeGreaterThan(0)
    expect(fnEnd).toBeGreaterThan(fnStart)
    expect(curlRecipes.length).toBeGreaterThanOrEqual(5)
    expect(curlRecipes.some((c) => c.includes('/api/schedules'))).toBe(true)
    expect(scheduleSection).not.toBe('')
  })

  it('every curl recipe handed to a sub-agent passes that sub-agent\'s self-pace gate', () => {
    const denied = curlRecipes.filter((c) => selfPaceDecision('Bash', { command: c }).deny)
    expect(denied, `recipes the gate denies:\n${denied.join('\n')}`).toEqual([])
  })

  it('the instrument is live: the old schedule-create recipe IS denied by the gate', () => {
    // If this ever passes the gate, the check above proves nothing about schedules.
    const old = render(`curl -s -X POST \${dashboardOrigin}/api/schedules -H "Content-Type: application/json" -H "Authorization: Bearer $(cat \${tokenPath})" -d '{"name": "x", "schedule": "0 8 * * *", "agent": "AGENT_NAME", "type": "task"}'`)
    expect(selfPaceDecision('Bash', { command: old }).deny).toBe(true)
  })

  it('the schedules section names the gate and the way a sub-agent gets a timed task', () => {
    expect(scheduleSection).toContain('self-pace-gate')
    expect(scheduleSection).toContain('${MAIN_AGENT_ID}')
    expect(scheduleSection).not.toMatch(/-X\s*POST[^\n]*\/api\/schedules/)
  })
})
