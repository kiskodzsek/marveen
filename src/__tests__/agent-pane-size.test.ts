// Card 0db274d2: every agent tmux session starts at AGENT_PANE_SIZE_ARGS, not at tmux's 80-column default,
// where Claude Code cuts its footer and the router read the pane 'unknown' (session-stuck 45907).
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join } from 'node:path'
import { AGENT_PANE_COLS, AGENT_PANE_ROWS, AGENT_PANE_SIZE_ARGS } from '../web/agent-pane-size.js'

const ROOT = join(__dirname, '..', '..')
const read = (p: string) => readFileSync(join(ROOT, p), 'utf8')

describe('agent tmux sessions start wide enough for the whole footer', () => {
  it('the size is wider than the default where the footer was cut', () => {
    expect(AGENT_PANE_COLS).toBeGreaterThanOrEqual(120)
    expect(AGENT_PANE_ROWS).toBeGreaterThanOrEqual(24)
    expect(AGENT_PANE_SIZE_ARGS).toEqual(['-x', String(AGENT_PANE_COLS), '-y', String(AGENT_PANE_ROWS)])
  })

  it('every new-session call of the agent launchers carries the size', () => {
    for (const file of ['src/web/agent-process.ts', 'src/web/agent-worker.ts']) {
      const calls = [...read(file).matchAll(/\['new-session',[^\]]*\]/g)].map((m) => m[0])
      expect(calls.length, file).toBeGreaterThan(0)
      for (const c of calls) expect(c, `${file}: ${c}`).toContain("'-d', ...AGENT_PANE_SIZE_ARGS,")
    }
    // agent-process.ts: the remote start, the local start and the EPERM fallback.
    expect([...read('src/web/agent-process.ts').matchAll(/\['new-session',/g)]).toHaveLength(3)
  })

  it('the watchdog relaunch uses the same size', () => {
    const lines = read('scripts/watchdog.sh').split('\n').filter((l) => /^\s*tmux new-session/.test(l))
    expect(lines.length).toBeGreaterThan(0)
    for (const l of lines) expect(l).toContain(`-x ${AGENT_PANE_COLS} -y ${AGENT_PANE_ROWS}`)
  })

  it('live: a detached session started with the size has that window width (isolated tmux server)', () => {
    const sock = `pane-size-test-${process.pid}`
    const tmux = (...a: string[]) => execFileSync('tmux', ['-L', sock, ...a], { encoding: 'utf8', timeout: 10_000 })
    try {
      tmux('-f', '/dev/null', 'new-session', '-d', ...AGENT_PANE_SIZE_ARGS, '-s', 'probe', 'sleep 30')
      expect(tmux('display-message', '-p', '-t', 'probe', '#{window_width}x#{window_height}').trim()).toBe(`${AGENT_PANE_COLS}x${AGENT_PANE_ROWS}`)
      // The control: without the size the same server starts at its default, which is narrower.
      tmux('new-session', '-d', '-s', 'ctl', 'sleep 30')
      expect(Number(tmux('display-message', '-p', '-t', 'ctl', '#{window_width}').trim())).toBeLessThan(AGENT_PANE_COLS)
    } finally {
      try { tmux('kill-server') } catch { /* already gone */ }
    }
  })
})
