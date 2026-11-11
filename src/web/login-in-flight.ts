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

const startedAt = new Map<string, number>()

/** Record that an operator started an interactive /login for `name`. */
export function markLoginInFlight(name: string, nowMs: number = Date.now()): void {
  startedAt.set(name, nowMs)
}

/** Drop the mark (e.g. tests, or a caller that knows the login ended). */
export function clearLoginInFlight(name: string): void {
  startedAt.delete(name)
}

/** True while an operator-started login for `name` is younger than LOGIN_IN_FLIGHT_MS. */
export function isLoginInFlight(name: string, nowMs: number = Date.now()): boolean {
  const t = startedAt.get(name)
  if (t == null) return false
  if (nowMs - t >= LOGIN_IN_FLIGHT_MS || nowMs < t) {
    startedAt.delete(name)
    return false
  }
  return true
}
