import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { routeStuckInputAlert, stuckInputAlertTarget } from '../web/channel-monitor.js'

// SUBSTUCK1113 (Patrik, privát TG 18139, 2026-11-13 11:12, Klodel 40029): the
// stuck-input alert for the juro and lex sub-agents went to the owner's
// Telegram. A sub-agent's wedge is the main agent's job ([session-stuck] in its
// inbox), never the owner's; only the main agent's own wedge may reach the owner.

const MAIN = 'klodel'

function recorder() {
  const main: string[] = []
  const owner: string[] = []
  return {
    main, owner,
    deps: { toMainAgent: (t: string) => { main.push(t) }, toOwner: (t: string) => { owner.push(t) } },
  }
}

describe('stuckInputAlertTarget', () => {
  it('a sub-agent goes to the main agent', () => {
    expect(stuckInputAlertTarget('juro', MAIN)).toBe('main-agent')
    expect(stuckInputAlertTarget('lex', MAIN)).toBe('main-agent')
  })
  it('an unknown session (no agent name) goes to the main agent, not the owner', () => {
    expect(stuckInputAlertTarget(null, MAIN)).toBe('main-agent')
  })
  it('only the main agent itself goes to the owner', () => {
    expect(stuckInputAlertTarget(MAIN, MAIN)).toBe('owner')
  })
})

describe('routeStuckInputAlert', () => {
  it('NEGATIVE: a sub-agent alert never reaches the owner', () => {
    const r = recorder()
    routeStuckInputAlert('juro', 'A(z) juro ágens bemenete beragadt', r.deps, MAIN)
    routeStuckInputAlert('lex', 'A(z) lex ágens bemenete beragadt', r.deps, MAIN)
    expect(r.owner).toEqual([])
    expect(r.main).toHaveLength(2)
    expect(r.main.every((m) => m.startsWith('[session-stuck] '))).toBe(true)
  })

  it('NEGATIVE: a failed inbox write is dropped, not re-routed to the owner', () => {
    const owner: string[] = []
    const target = routeStuckInputAlert('juro', 'x', {
      toMainAgent: () => { throw new Error('db locked') },
      toOwner: (t) => { owner.push(t) },
    }, MAIN)
    expect(target).toBe('main-agent')
    expect(owner).toEqual([])
  })

  it("the main agent's own wedge still reaches the owner", () => {
    const r = recorder()
    routeStuckInputAlert(MAIN, 'main wedged', r.deps, MAIN)
    expect(r.owner).toEqual(['main wedged'])
    expect(r.main).toEqual([])
  })
})

// Wiring: both sub-agent stuck-input alert sites use the router, not sendAlert.
const ROOT = join(__dirname, '..', '..')
function fnBody(file: string, decl: string): string {
  const src = readFileSync(join(ROOT, 'src', 'web', file), 'utf-8')
  const start = src.indexOf(decl)
  expect(start).toBeGreaterThanOrEqual(0)
  return src.slice(start, src.indexOf('\n}', start))
}

describe('wiring', () => {
  it('channel-monitor maybeAlertStuckSubAgent routes, never sendAlert', () => {
    const body = fnBody('channel-monitor.ts', 'function maybeAlertStuckSubAgent')
    expect(body).toMatch(/routeStuckInputAlert\(agentName,/)
    expect(body).not.toMatch(/sendAlert\(/)
  })
  it('stuck-input-watcher checkLocalSession routes, never sendAlert', () => {
    const body = fnBody('stuck-input-watcher.ts', 'async function checkLocalSession')
    expect(body).toMatch(/routeStuckInputAlert\(label,/)
    expect(body).not.toMatch(/sendAlert\(/)
  })
})
