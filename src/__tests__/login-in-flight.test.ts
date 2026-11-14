import { describe, it, expect, beforeEach } from 'vitest'
import { markLoginInFlight, isLoginInFlight, clearLoginInFlight, loginInFlightAgeMin, LOGIN_IN_FLIGHT_MS, LOGIN_IN_FLIGHT_MAX_MS } from '../web/login-in-flight.js'

describe('login-in-flight registry', () => {
  beforeEach(() => { clearLoginInFlight('dave'); clearLoginInFlight('szigma') })

  it('unmarked agent is not in flight', () => {
    expect(isLoginInFlight('dave', 1_000)).toBe(false)
  })

  it('marked agent is in flight until the window ends, then expires on its own', () => {
    markLoginInFlight('dave', 1_000)
    expect(isLoginInFlight('dave', 1_000)).toBe(true)
    expect(isLoginInFlight('dave', 1_000 + LOGIN_IN_FLIGHT_MS - 1)).toBe(true)
    expect(isLoginInFlight('dave', 1_000 + LOGIN_IN_FLIGHT_MS)).toBe(false)
    expect(isLoginInFlight('dave', 1_000)).toBe(false) // the expired mark was dropped
  })

  it('the mark is per agent', () => {
    markLoginInFlight('dave', 1_000)
    expect(isLoginInFlight('szigma', 1_000)).toBe(false)
  })

  it('a clock that went backwards does not keep the mark alive forever', () => {
    markLoginInFlight('dave', 10_000)
    expect(isLoginInFlight('dave', 5_000)).toBe(false)
  })

  it('a new mark extends the window', () => {
    markLoginInFlight('dave', 1_000)
    markLoginInFlight('dave', 1_000 + LOGIN_IN_FLIGHT_MS - 10)
    expect(isLoginInFlight('dave', 1_000 + LOGIN_IN_FLIGHT_MS + 5)).toBe(true)
  })

  it('steady re-marking cannot keep the hold past the hard cap from the first mark (Viktor 38639 L2)', () => {
    const t0 = 1_000
    // one re-mark a minute for 90 minutes: held only for the first LOGIN_IN_FLIGHT_MAX_MS
    for (let t = t0; t <= t0 + 90 * 60_000; t += 60_000) {
      markLoginInFlight('dave', t)
      expect(isLoginInFlight('dave', t)).toBe(t - t0 < LOGIN_IN_FLIGHT_MAX_MS)
    }
  })

  it('after a quiet gap of the window a new spell starts', () => {
    markLoginInFlight('dave', 0)
    expect(isLoginInFlight('dave', LOGIN_IN_FLIGHT_MS)).toBe(false)
    markLoginInFlight('dave', LOGIN_IN_FLIGHT_MAX_MS + LOGIN_IN_FLIGHT_MS)
    expect(isLoginInFlight('dave', LOGIN_IN_FLIGHT_MAX_MS + LOGIN_IN_FLIGHT_MS + 1)).toBe(true)
  })

  it('reports the minutes since the first mark of the live spell', () => {
    markLoginInFlight('dave', 0)
    markLoginInFlight('dave', 5 * 60_000)
    expect(loginInFlightAgeMin('dave', 7 * 60_000)).toBe(7)
    expect(loginInFlightAgeMin('szigma', 7 * 60_000)).toBe(null)
  })
})
