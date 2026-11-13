import { describe, it, expect } from 'vitest'
import { identitySlashCommands } from '../web/agent-process.js'

// Locks the identity slash commands sent on every Claude Code session
// (re)start -- both the normal startup and the channel-monitor recovery
// respawns route through scheduleIdentitySetup, which uses these. Only `/rename`
// is sent now; `/remote-control` was dropped (the operator no longer uses it).
//
// The `/name` case below is not a style assertion. `/name` is not a Claude Code
// command -- the CLI answers "Unknown command: /name. Did you mean /rename?" and
// leaves the rejected line PARKED in the input box, where it lands only when the
// current turn ends. A parked input line makes the router read the session as
// busy, so inter-agent messages stop being delivered and the channel goes quiet
// with no error. The previous version of this test asserted `/name`, which is
// why CI stayed green while no session was ever renamed.
describe('identitySlashCommands', () => {
  it('returns just /rename with the display name', () => {
    expect(identitySlashCommands('Zoé')).toEqual(['/rename Zoé'])
  })

  it('never sends /name -- there is no such Claude Code command', () => {
    expect(identitySlashCommands('Zoé').some((c) => c.startsWith('/name'))).toBe(false)
  })

  it('does not send /remote-control', () => {
    expect(identitySlashCommands('Mr. Wolf').some((c) => c.includes('/remote-control'))).toBe(false)
  })
})

// RENAMEPARK1113 (2026-11-13, store/dashboard.log): the identity "/rename" was
// left parked in the input box of klodel, pulzus, viktor, juro and lex; at
// 11:12 the juro/lex ones fired the overdue-guard alert to the owner. The setup
// now re-reads the box after sending. identityRenameParked is the decision: it
// must fire ONLY on this session's own parked identity command.
import { identityRenameParked } from '../web/agent-process.js'

const SEP = '─'.repeat(80)
const FOOTER = '  ⏵⏵ bypass permissions on (shift+tab to cycle) · ↓ to manage'
const box = (text: string) => [SEP, `❯ ${text}`, SEP, FOOTER].join('\n')
const EMPTY = [SEP, '❯ ', SEP, FOOTER].join('\n')

describe('identityRenameParked', () => {
  it('NEGATIVE: the parked /rename of this session is detected (juro, lex shape)', () => {
    expect(identityRenameParked(box('/rename Juró'), 'Juró')).toBe(true)
    expect(identityRenameParked(box('/rename Lex'), 'Lex')).toBe(true)
  })
  it('an empty box (submitted) is not parked', () => {
    expect(identityRenameParked(EMPTY, 'Juró')).toBe(false)
  })
  it('no pane (capture failed) is not parked -- nothing is touched', () => {
    expect(identityRenameParked(null, 'Juró')).toBe(false)
  })
  it("another session's name or a different text is NOT ours to submit or clear", () => {
    expect(identityRenameParked(box('/rename Lex'), 'Juró')).toBe(false)
    expect(identityRenameParked(box('Finish the migration before lunch'), 'Juró')).toBe(false)
    expect(identityRenameParked(box('/rename Juró and also do this'), 'Juró')).toBe(false)
  })
})
