import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { EMAIL_GATE_MATCHER, MS365_OUTBOUND_OPS } from '../web/agent-scaffold.js'
// @ts-expect-error -- plain .mjs hook script, no types
import { gateDecision, ms365ToolClass, loadMs365Policy } from '../../scripts/email-send-gate.mjs'
// @ts-expect-error -- plain .mjs hook script, no types
import { endpointsDrift, mcpConfigDrift, loadPolicy } from '../../scripts/hooks/ms365-policy-check.mjs'

// MS365GATE1015 (Viktor G1/G3, card d85d38c3): the ms365 gates are an
// allowlist driven by ONE policy file. These tests pin the three copies of it
// (policy JSON, the TS matcher list, the reviewed server version) to each other
// and to the server's own tool list.
const ROOT = join(__dirname, '..', '..')
type Policy = { reviewed_version: string; read_draft: string[]; anchored_send: string[]; outbound: string[] }
const POLICY = loadPolicy() as Policy
const FIXTURE = JSON.parse(readFileSync(join(__dirname, 'fixtures', 'ms365-endpoints-0.162.0.json'), 'utf-8')) as {
  version: string
  endpoints: { tool: string; scopes: string[] }[]
}

const LIVE_SHAPE = {
  mcpServers: {
    ms365: {
      command: 'npx',
      args: ['-y', '@softeria/ms-365-mcp-server@0.162.0', '--enabled-tools',
        '^(list-mail-messages|list-mail-folders|list-mail-child-folders|list-mail-folder-messages|get-mail-message|list-mail-attachments|get-mail-message-mime|list-mail-folder-messages-delta|create-draft-email|create-reply-draft|create-reply-all-draft|create-forward-draft)$'],
    },
    other: { command: 'node', args: ['x.js'] },
  },
}

function withServer(name: string, args: string[]) {
  return { mcpServers: { [name]: { command: 'npx', args } } }
}

describe('ms365 tool policy (MS365GATE1015)', () => {
  it('the TS matcher list is the policy outbound list', () => {
    expect([...MS365_OUTBOUND_OPS]).toEqual(POLICY.outbound)
  })

  it('the policy matches the server tool list of the reviewed version', () => {
    expect(FIXTURE.version).toBe(POLICY.reviewed_version)
    expect(endpointsDrift(FIXTURE, POLICY)).toEqual([])
  })

  it('endpointsDrift catches a send-scoped tool missing from outbound, and a send on the read list', () => {
    const dropped = { ...POLICY, outbound: POLICY.outbound.filter((op) => op !== 'reply-shared-mailbox-mail') }
    expect(endpointsDrift(FIXTURE, dropped).join('\n')).toMatch(/reply-shared-mailbox-mail has a send scope/)
    const widened = { ...POLICY, read_draft: [...POLICY.read_draft, 'send-mail'] }
    expect(endpointsDrift(FIXTURE, widened).join('\n')).toMatch(/send-mail is also outbound/)
    const typo = { ...POLICY, outbound: [...POLICY.outbound, 'send-mial'] }
    expect(endpointsDrift(FIXTURE, typo).join('\n')).toMatch(/send-mial is not a tool/)
  })

  it('mcpConfigDrift: the live shape passes', () => {
    expect(mcpConfigDrift(LIVE_SHAPE, POLICY)).toEqual([])
  })

  it('mcpConfigDrift: a renamed server, a version bump, a wider allowlist and no allowlist all fail', () => {
    const args = LIVE_SHAPE.mcpServers.ms365.args
    expect(mcpConfigDrift(withServer('outlook', args), POLICY).join('\n')).toMatch(/whole-server gate does not reach it/)
    expect(mcpConfigDrift(withServer('ms365', ['-y', '@softeria/ms-365-mcp-server@0.163.0', ...args.slice(2)]), POLICY)
      .join('\n')).toMatch(/not the reviewed 0\.162\.0/)
    expect(mcpConfigDrift(withServer('ms365', ['-y', '@softeria/ms-365-mcp-server', ...args.slice(2)]), POLICY)
      .join('\n')).toMatch(/unpinned/)
    expect(mcpConfigDrift(withServer('ms365', [args[0], args[1], '--enabled-tools', '^(list-mail-messages|create-mail-rule)$']), POLICY)
      .join('\n')).toMatch(/exposes create-mail-rule/)
    expect(mcpConfigDrift(withServer('ms365', [args[0], args[1], '--enabled-tools', '^(list-mail-messages|send-mail)$']), POLICY))
      .toEqual([])
    expect(mcpConfigDrift(withServer('ms365', [args[0], args[1]]), POLICY).join('\n')).toMatch(/no --enabled-tools/)
    expect(mcpConfigDrift(withServer('ms365', [args[0], args[1], '--enabled-tools', 'mail.*']), POLICY).join('\n'))
      .toMatch(/cannot be checked/)
  })

  it.skipIf(!existsSync(join(ROOT, '.mcp.json')))('the install .mcp.json has no ms365 drift', () => {
    const live = JSON.parse(readFileSync(join(ROOT, '.mcp.json'), 'utf-8'))
    expect(mcpConfigDrift(live, POLICY)).toEqual([])
  })

  it('the matcher reaches every ms365 tool and every outbound operation on any server', () => {
    const full = new RegExp(`^(${EMAIL_GATE_MATCHER})$`)
    expect(full.test('mcp__ms365__get-me')).toBe(true)
    expect(full.test('mcp__ms-365__list-mail-messages')).toBe(true)
    for (const op of POLICY.outbound) {
      expect(full.test(`mcp__outlook__${op}`), op).toBe(true)
    }
    expect(full.test('mcp__outlook__list-mail-messages')).toBe(false)
    expect(full.test('mcp__plugin_telegram_telegram__reply')).toBe(false)
  })

  it('sub-agent gate: outbound and unlisted ms365 tools are denied, the read/draft list passes', () => {
    for (const op of POLICY.outbound) {
      expect(gateDecision(`mcp__ms365__${op}`, {}).deny, op).toBe(true)
      expect(gateDecision(`mcp__m365__${op}`, {}).deny, `renamed ${op}`).toBe(true)
    }
    for (const op of ['get-me', 'list-calendar-events', 'delete-mail-message', 'some-future-tool']) {
      expect(gateDecision(`mcp__ms365__${op}`, {}).deny, op).toBe(true)
    }
    for (const op of POLICY.read_draft) {
      expect(gateDecision(`mcp__ms365__${op}`, {}).deny, op).toBe(false)
    }
    expect(gateDecision('mcp__outlook__list-mail-messages', {}).deny).toBe(false)
  })

  it('sub-agent gate: an unreadable policy denies every ms365 tool and the six first-version sends', () => {
    const broken = loadMs365Policy('/nonexistent/ms365-tool-policy.json')
    expect(broken.error).toBeTruthy()
    expect(ms365ToolClass('mcp__ms365__list-mail-messages', broken)).toBe('unlisted')
    expect(ms365ToolClass('mcp__outlook__forward-mail-message', broken)).toBe('outbound')
    expect(ms365ToolClass('mcp__outlook__list-mail-messages', broken)).toBe(null)
  })
})
