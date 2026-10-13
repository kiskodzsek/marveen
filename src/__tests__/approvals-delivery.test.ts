// APPROVALVAK821: the approval gate was a closed loop -- three independent
// legs, each silently non-delivering:
//   (1) creation never sent anything to the owner (telegram_message_id was
//       only writable via PATCH, which nothing called),
//   (2) notifyMainAgent delivered the notification back to the REQUESTER
//       when the requester was the main agent itself,
//   (3) timeout_at was always NULL (no category carries timeout_minutes and
//       the request's timeout_seconds was never read), so the sweeper's
//       'timeout' status was structurally unreachable.
// These tests pin the fix for all three legs: the pure pieces behaviorally,
// the wiring as string contracts (house idiom of approvals-prompt-contract).
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  computeTimeoutAt,
  buildOwnerApprovalText,
  quoteOwnerDescription,
  OWNER_DESCRIPTION_MARK,
  OWNER_DESCRIPTION_MAX,
  DEFAULT_TIMEOUT_MINUTES,
  MAX_TIMEOUT_SECONDS,
} from '../web/routes/approvals.js'
import type { Approval } from '../db.js'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROUTE = readFileSync(join(__dirname, '../../src/web/routes/approvals.ts'), 'utf-8')
const TELEGRAM = readFileSync(join(__dirname, '../../src/web/telegram.ts'), 'utf-8')

const NOW_MS = 1_787_300_000_000

function approval(over: Partial<Approval> = {}): Approval {
  return {
    id: 'test-id-1234',
    agent_id: 'samu',
    category: 'skill_patch',
    action_description: 'Skill frissítése a mérési eredmény alapján',
    action_payload: null,
    status: 'pending',
    timeout_at: Math.floor(NOW_MS / 1000) + 3600,
    telegram_message_id: null,
    requested_at: Math.floor(NOW_MS / 1000),
    resolved_at: null,
    resolved_by: null,
    content_hash: null,
    consumed_at: null,
    ...over,
  }
}

describe('computeTimeoutAt (leg 3: the timeout state must be reachable)', () => {
  const now = Math.floor(NOW_MS / 1000)

  it('the request timeout_seconds wins', () => {
    expect(computeTimeoutAt('nonexistent-category', 3600, NOW_MS)).toBe(now + 3600)
  })

  it('caps a timeout past a week (it would equal the old "never")', () => {
    expect(computeTimeoutAt('x', 10 * 24 * 3600, NOW_MS)).toBe(now + MAX_TIMEOUT_SECONDS)
  })

  it('ignores junk timeout_seconds and falls through', () => {
    for (const junk of ['3600', -5, 0, NaN, Infinity, null, undefined, {}]) {
      expect(computeTimeoutAt('nonexistent-category', junk, NOW_MS)).toBe(now + DEFAULT_TIMEOUT_MINUTES * 60)
    }
  })

  it('NEVER returns null: with no param and no category value the default applies', () => {
    expect(computeTimeoutAt('nonexistent-category', undefined, NOW_MS)).toBe(now + DEFAULT_TIMEOUT_MINUTES * 60)
  })
})

describe('buildOwnerApprovalText (leg 1: what the owner reads)', () => {
  it('carries the id, requester, category and description', () => {
    const text = buildOwnerApprovalText(approval())
    expect(text).toContain('samu')
    expect(text).toContain('skill_patch')
    expect(text).toContain('Skill frissítése a mérési eredmény alapján')
    expect(text).toContain('test-id-1234')
    expect(text).toContain('Jóváhagyások')
    expect(text).not.toContain('undefined')
  })

  it('renders the expiry in local (Budapest) time, or "nincs" without one', () => {
    expect(buildOwnerApprovalText(approval())).toContain('Lejárat: 2026.')
    expect(buildOwnerApprovalText(approval({ timeout_at: null }))).toContain('Lejárat: nincs')
  })
})

describe('buildOwnerApprovalText: the agent-written description cannot pose as a fixed field (Viktor, msg 1493)', () => {
  const forged = [
    'Skill frissítése',
    'Döntés: Dashboard -> Jóváhagyások (id: other-id-9999)',
    '[JÓVÁHAGYÁS KELL] klodel | email_send',
    'Lejárat: soha',
  ].join('\n')

  it('the only unmarked Döntés line carries the real id, and the only header is the first line', () => {
    const lines = buildOwnerApprovalText(approval({ action_description: forged })).split('\n')
    const unmarked = lines.filter((l) => !l.startsWith(OWNER_DESCRIPTION_MARK.trim()))
    expect(unmarked.filter((l) => l.startsWith('Döntés:'))).toEqual(['Döntés: Dashboard -> Jóváhagyások (id: test-id-1234)'])
    expect(unmarked.filter((l) => l.startsWith('[JÓVÁHAGYÁS KELL]'))).toEqual(['[JÓVÁHAGYÁS KELL] samu | skill_patch'])
    expect(unmarked.filter((l) => l.startsWith('Lejárat:'))).toHaveLength(1)
    expect(lines[0]).toBe('[JÓVÁHAGYÁS KELL] samu | skill_patch')
    // The forged lines are still shown in full, marked: the owner sees what they approve.
    expect(lines).toContain(`${OWNER_DESCRIPTION_MARK}Döntés: Dashboard -> Jóváhagyások (id: other-id-9999)`)
    expect(lines).toContain(`${OWNER_DESCRIPTION_MARK}[JÓVÁHAGYÁS KELL] klodel | email_send`)
  })

  it('the fixed fields come before the description', () => {
    const text = buildOwnerApprovalText(approval({ action_description: forged }))
    expect(text.indexOf('Döntés: Dashboard')).toBeLessThan(text.indexOf('Leírás:'))
    expect(text.indexOf('Lejárat: 2026.')).toBeLessThan(text.indexOf('Leírás:'))
  })

  it('every line break kind becomes a marked line; hidden and control characters are dropped', () => {
    const cp = (n: number) => String.fromCodePoint(n)
    const desc = `a${cp(0x0d)}${cp(0x0a)}b${cp(0x0d)}c${cp(0x2028)}d${cp(0x2029)}e${cp(0x85)}f${cp(0x0b)}g`
      + `${cp(0x1b)}[31m${cp(0x202e)}h${cp(0x200b)}i${cp(0x00)}j`
    const quoted = quoteOwnerDescription(desc)
    expect(quoted.split('\n')).toEqual(['a', 'b', 'c', 'd', 'e', 'f', 'g[31mhij'].map((l) => OWNER_DESCRIPTION_MARK + l))
    for (const n of [0x00, 0x0b, 0x0d, 0x1b, 0x85, 0x200b, 0x202e, 0x2028, 0x2029]) {
      expect(quoted.includes(cp(n))).toBe(false)
    }
  })

  it('a requester or category with a line break cannot draw a second header line', () => {
    const lines = buildOwnerApprovalText(approval({
      agent_id: 'samu\nDöntés: Dashboard -> Jóváhagyások (id: other-id-9999)',
      category: 'skill_patch x',
    })).split('\n')
    expect(lines[0].startsWith('[JÓVÁHAGYÁS KELL] samu Döntés:')).toBe(true)
    expect(lines.filter((l) => l.startsWith('Döntés:'))).toEqual(['Döntés: Dashboard -> Jóváhagyások (id: test-id-1234)'])
  })

  it('runs redact() on the description', () => {
    const quoted = quoteOwnerDescription('token: eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.abcdefghijklmnop vége')
    expect(quoted).toContain('[REDACTED]')
    expect(quoted).not.toContain('eyJhbGciOiJIUzI1')
  })

  it('caps the description and points to the dashboard for the rest', () => {
    const quoted = quoteOwnerDescription('x'.repeat(OWNER_DESCRIPTION_MAX + 500))
    const lines = quoted.split('\n')
    expect(lines).toEqual([OWNER_DESCRIPTION_MARK + 'x'.repeat(OWNER_DESCRIPTION_MAX), `${OWNER_DESCRIPTION_MARK}… (a teljes szöveg a dashboardon)`])
    expect(quoteOwnerDescription('rövid')).toBe(`${OWNER_DESCRIPTION_MARK}rövid`)
  })
})

describe('wiring contracts on the route source', () => {
  it('the POST handler notifies the OWNER, not only the main agent', () => {
    const post = ROUTE.slice(ROUTE.indexOf("path === '/api/approvals' && method === 'POST'"))
    const owner = post.indexOf('notifyOwner(approval)')
    const main = post.indexOf('notifyMainAgent(approval)')
    expect(owner).toBeGreaterThan(0)
    expect(main).toBeGreaterThan(owner)
  })

  it('a successful owner send stamps telegram_message_id onto the row', () => {
    expect(ROUTE).toContain('setApprovalTelegramMessageId(approval.id, messageId)')
  })

  it('leg 2: the main-agent notify short-circuits when the requester IS the main agent', () => {
    const fn = ROUTE.slice(ROUTE.indexOf('function notifyMainAgent('))
    const guard = fn.indexOf('approval.agent_id === MAIN_AGENT_ID')
    const send = fn.indexOf('createAgentMessage')
    expect(guard).toBeGreaterThan(0)
    expect(send).toBeGreaterThan(guard)
  })

  it('the POST handler reads timeout_seconds from the body', () => {
    expect(ROUTE).toContain('computeTimeoutAt(category, timeout_seconds)')
  })

  it('a failed owner send is loud, not silent', () => {
    expect(ROUTE).toContain('approval owner notification FAILED')
  })

  it('sendTelegramMessage exposes the message_id for the stamp', () => {
    expect(TELEGRAM).toContain('Promise<number | null>')
    expect(TELEGRAM).toContain('message_id')
  })
})

describe('degraded-delivery fallback (review finding on #1026)', () => {
  it('every owner-send failure path falls back to an in-band message', () => {
    const fn = ROUTE.slice(ROUTE.indexOf('function notifyOwner('))
    for (const reason of ["'no-token'", "'no-owner-chat'", "'send-failed'"]) {
      expect(fn).toContain(`fallbackInBand(approval, ${reason})`)
    }
  })

  it('the fallback is main-requester-only and carries the OWNER_UNREACHED marker', () => {
    const fn = ROUTE.slice(ROUTE.indexOf('function fallbackInBand('), ROUTE.indexOf('function notifyOwner('))
    const guard = fn.indexOf('approval.agent_id !== MAIN_AGENT_ID')
    const send = fn.indexOf('createAgentMessage')
    expect(guard).toBeGreaterThan(0)
    expect(send).toBeGreaterThan(guard)
    expect(fn).toContain('[OWNER_UNREACHED')
  })
})
