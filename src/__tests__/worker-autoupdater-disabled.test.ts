// Card 8fbd8b7b (Klodel 39979): on 2026-11-13 the shared Claude Code install moved
// 2.1.322 -> 2.1.323 at 10:40:28 with no fleet decision. Every running claude
// process had DISABLE_AUTOUPDATER=1 except the two agent-worker sessions
// (klodel-worker, klodel-worker-fast, started 10:08:11): their launch line never
// set it, and the tmux global env that would have carried it is set by
// channels.sh only after its network wait. The worker launch must carry the
// flag itself, before the claude binary, like agent-process.ts does.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const src = readFileSync(join(ROOT, 'src/web/agent-worker.ts'), 'utf-8')

describe('agent-worker launch disables the in-place auto-updater', () => {
  it('exports DISABLE_AUTOUPDATER=1 in the launch line', () => {
    expect(src).toMatch(/`export DISABLE_AUTOUPDATER=1; ` \+/)
  })

  it('NEGATIVE: the export comes BEFORE the claude launch (an export after it would not reach the process)', () => {
    const exp = src.indexOf('`export DISABLE_AUTOUPDATER=1; `')
    const launch = src.indexOf('--dangerously-skip-permissions --model ${shArg(workerModel)}')
    expect(exp).toBeGreaterThan(-1)
    expect(launch).toBeGreaterThan(-1)
    expect(exp).toBeLessThan(launch)
  })

  it('agent-process.ts keeps its own sub-agent flag (the reference this mirrors)', () => {
    expect(readFileSync(join(ROOT, 'src/web/agent-process.ts'), 'utf-8')).toContain("const autoUpdaterEnv = 'export DISABLE_AUTOUPDATER=1 && '")
  })
})
