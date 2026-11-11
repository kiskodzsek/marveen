/**
 * In-flight registry for OPERATOR-STARTED interactive logins (/login), per agent.
 *
 * WHY THIS EXISTS. The reauth-healer treats the browser sign-in screen
 * ("Paste code here if prompted") as Claude Code's first-run gate and heals it
 * with a restart after DEAD_PROBE_THRESHOLD probes (~6-9 min). That is right
 * when nobody is logging in (a blind Enter advanced the picker), and wrong when
 * a human is: the restart kills the login process, and the authorize link the
 * owner was just sent becomes useless.
 *
 * Measured 2026-11-11 (dave, authMode own_team, store/dashboard.log): Kernel
 * started /login via POST /api/agents/dave/login at 22:07, the link went to the
 * owner, and at 22:11:36 "reauth-healer: first-run gate on live sub-agent --
 * restarting it" killed the session while the owner was authorizing; the new
 * session came up "Not logged in". Patrik had to be sent a second link.
 *
 * The dashboard's own login entry points (POST /api/agents/:name/auth/init and
 * POST /api/agents/:name/login phase=start) mark the agent here; while the mark
 * is fresh the healer neither restarts the agent, nor sends /login keys, nor
 * escalates. The mark expires on its own, so an abandoned login falls back to
 * the normal heal. IO-free so the invariants are unit-testable.
 */

/** How long an operator-started login is protected from the healer. */
export const LOGIN_IN_FLIGHT_MS = 15 * 60 * 1000
/**
 * Hard cap from the FIRST mark of a spell (Viktor 38639 L2): the fleet shares
 * one Bearer token, so any caller could re-mark an agent forever and keep a
 * dead-token agent from its restart and its alert. A re-mark extends the
 * window, but never past this.
 */
export const LOGIN_IN_FLIGHT_MAX_MS = 30 * 60 * 1000

const marks = new Map<string, { first: number; last: number }>()

/**
 * Record that an operator started an interactive /login for `name`. A mark less
 * than LOGIN_IN_FLIGHT_MS after the previous one continues the same spell (its
 * first-mark time is kept), so steady re-marking cannot outlive the hard cap;
 * only a quiet gap of LOGIN_IN_FLIGHT_MS starts a new spell.
 */
export function markLoginInFlight(name: string, nowMs: number = Date.now()): void {
  const m = marks.get(name)
  const sameSpell = m != null && nowMs >= m.first && nowMs - m.last < LOGIN_IN_FLIGHT_MS
  marks.set(name, { first: sameSpell ? (m as { first: number }).first : nowMs, last: nowMs })
}

/** Drop the mark (a failed login start, tests, or a caller that knows the login ended). */
export function clearLoginInFlight(name: string): void {
  marks.delete(name)
}

/**
 * True while an operator-started login for `name` is younger than
 * LOGIN_IN_FLIGHT_MS since its last mark and LOGIN_IN_FLIGHT_MAX_MS since its first.
 */
export function isLoginInFlight(name: string, nowMs: number = Date.now()): boolean {
  const m = marks.get(name)
  if (m == null) return false
  if (nowMs < m.first || nowMs - m.last >= LOGIN_IN_FLIGHT_MS) {
    marks.delete(name) // the spell is over: a later mark starts a new one
    return false
  }
  // Past the cap the entry stays (it remembers the spell's start), but it no longer holds the healer.
  return nowMs - m.first < LOGIN_IN_FLIGHT_MAX_MS
}

/** Whole minutes since the first mark of the live spell, or null when none. */
export function loginInFlightAgeMin(name: string, nowMs: number = Date.now()): number | null {
  if (!isLoginInFlight(name, nowMs)) return null
  return Math.floor((nowMs - (marks.get(name) as { first: number }).first) / 60_000)
}
