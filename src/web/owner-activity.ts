// Owner-activity deferral (Klodel 39538, Patrik TG 18102 "nagyon lassú vagy, lassan reaglsz az üzenetimre?").
//
// Measured by Klodel on 2026-11-12: between Patrik's messages of 13:34-13:39 the main channels session ran
// heartbeats (export-or, lemez-or-ideiglenes, tetlen-agens-figyelo, elo-allapot-frissites), and every one of them
// pushed his replies back. A scheduled prompt for the MAIN agent is therefore not typed into the channels session
// while a human wrote to it in the last OWNER_ACTIVE_WINDOW_MS: the runner answers 'busy', the normal retry path
// delivers it after the quiet window (skipIfBusy heartbeats drop the tick, as they do for any busy session).
//
// Not routed to another session instead: the "klodel-worker" tmux pane runs a plain bash (measured 2026-11-12,
// pane_current_command=bash), so a prompt typed there would be executed as shell input.
//
// "A human" = any inbound row of conversation_log for the main agent (Patrik's private chat and the team group:
// both are people waiting for an answer). The table carries no sender id, so the group is not narrowed to Patrik.
import { lastInboundAt } from '../db.js'

export const OWNER_ACTIVE_WINDOW_MS = 15 * 60_000

/** Pure decision: true when the latest inbound (unix seconds) is within the window before nowMs. A future
 *  timestamp (clock skew) counts as active; no inbound at all does not. */
export function ownerActiveDefers(lastInboundSec: number | null, nowMs: number, windowMs = OWNER_ACTIVE_WINDOW_MS): boolean {
  if (lastInboundSec == null || !Number.isFinite(lastInboundSec)) return false
  return nowMs - lastInboundSec * 1000 < windowMs
}

/** Reads the ledger. Fails OPEN (false = deliver as before) when the read fails: a broken ledger must not stop
 *  every scheduled task of the main agent. */
export function ownerRecentlyActive(agentId: string, nowMs: number = Date.now()): boolean {
  try {
    return ownerActiveDefers(lastInboundAt(agentId), nowMs)
  } catch {
    return false
  }
}
