// Reserved message senders (RESERVEDSENDER1013).
//
// `system` is the from_agent of in-process supervisory directives (context-guard
// handoff/stop/resume, restart-gate wake-ups, channels-recovery). Agents
// authenticate such a directive by looking its row up: it exists, from_agent is
// "system", to_agent is them, and the content matches. That recipe only holds
// while NOTHING reachable from outside the process can write a from=system row.
//
// SYSRESERVED918 closed POST /api/messages, but the check lived in that one
// route. Two other routes still handed a caller-chosen string to
// createAgentMessage as the sender: POST /api/desktop-lock (`owner`, plus free
// text in `note`) and PUT /api/schedules/:name (`agent`, used as the sender of
// the heartbeat direct digest). Both reach the shared dashboard token, which
// every sub-agent can read. (Viktor, 2026-10-13, M1/M2.)
//
// So the reservation is enforced where the row is written: createAgentMessage
// refuses a reserved sender, and the one way to write a system row is
// createSystemMessage(), which takes no sender argument at all. A new route that
// passes request data as `from` is therefore safe by default; it fails loudly
// instead of minting a directive-shaped row.
import { sanitizeAgentIdent } from './prompt-safety.js'

export const SYSTEM_SENDER = 'system'

// Look-alikes that render as the Latin letters of "system" in a terminal or a
// JSON dump. The directive recipe compares from_agent by eye as much as by
// string, so "ѕуѕtеm" (Cyrillic) must count as reserved too. Not a full
// confusables table: it covers the letters of the one reserved word.
const CONFUSABLES: Record<string, string> = {
  'ѕ': 's', // Cyrillic small dze
  'Ѕ': 's', // Cyrillic capital dze
  'у': 'y', // Cyrillic small u
  'ү': 'y', // Cyrillic small straight u
  'У': 'y', // Cyrillic capital u
  'γ': 'y', // Greek small gamma
  'т': 't', // Cyrillic small te
  'Т': 't', // Cyrillic capital te
  'τ': 't', // Greek small tau
  'е': 'e', // Cyrillic small ie
  'Е': 'e', // Cyrillic capital ie
  'ε': 'e', // Greek small epsilon
  'м': 'm', // Cyrillic small em
  'М': 'm', // Cyrillic capital em
}

/** The comparison key of a sender id: NFKC (folds fullwidth forms), the
 *  look-alike letters above mapped to Latin, then the same character filter
 *  the router applies to agent ids, lowercased. */
function senderKey(raw: string): string {
  const folded = [...String(raw ?? '').normalize('NFKC')]
    .map(ch => CONFUSABLES[ch] ?? ch)
    .join('')
  return sanitizeAgentIdent(folded).toLowerCase()
}

/** True when `raw` would read as the reserved system sender. */
export function isReservedSender(raw: string): boolean {
  return senderKey(raw) === SYSTEM_SENDER
}

export class ReservedSenderError extends Error {
  constructor(from: string) {
    super(`sender '${String(from).trim()}' is reserved for in-process system messages -- use createSystemMessage()`)
    this.name = 'ReservedSenderError'
  }
}
