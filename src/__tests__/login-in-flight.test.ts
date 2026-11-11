import { describe, it, expect, beforeEach } from 'vitest'
import { markLoginInFlight, isLoginInFlight, clearLoginInFlight, LOGIN_IN_FLIGHT_MS } from '../web/login-in-flight.js'

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

  it('a new mark restarts the window', () => {
    markLoginInFlight('dave', 1_000)
    markLoginInFlight('dave', 1_000 + LOGIN_IN_FLIGHT_MS - 10)
    expect(isLoginInFlight('dave', 1_000 + LOGIN_IN_FLIGHT_MS + 5)).toBe(true)
  })
})
