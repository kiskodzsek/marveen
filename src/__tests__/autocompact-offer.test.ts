// Card e9989124 (Radar 2026-11-16, session-stuck 44979): Claude Code's autocompact offer parked a sub-agent for
// 10+ minutes with 2 messages queued, and nothing recognised it: its hint row "esc not now" matched neither menu
// regex, so the pane read 'unknown', the monitor sent no Escape, and every message the router typed into the modal
// was swallowed as stray keys. These tests pin the detector, the blocking-menu and the emit-refusal consequences,
// the session-stuck sentence, and the monitor branch (Escape only, never Enter).
//
// The dialog shapes below are RECONSTRUCTED from the strings of the shipped CLI (bin/claude.exe, read 2026-11-18):
// title "We recommend compacting earlier", body "Want to autocompact at <N> tokens instead? ...", options
// "Autocompact at ‹ <N> › tokens" / "Keep <window>", hint "↑/↓ choose · ←/→ change size · enter confirm · esc not
// now", overflow warning "More text above: scroll up, or enlarge the terminal". No live capture exists yet; the
// variants (wrapped body, box borders, overflow line) cover the layouts the source allows.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { detectsAutocompactOffer, detectsBlockingMenu, detectsPermissionDialog, detectPaneState } from '../pane-state.js'
import { formatStuckSessionAlert, urgentEmitRefusal } from '../web/message-router.js'

const SEP = '─'.repeat(80)
const HINT = '↑/↓ choose · ←/→ change size · enter confirm · esc not now'

const OFFER = [
  '⏺ Done: the review is in shared/k-f/radar-meres.md.',
  '',
  '  We recommend compacting earlier',
  '',
  '   Each message re-sends the whole conversation, so long conversations use up your plan\'s usage limits faster.',
  '   With your current settings, Claude Code autocompacts (replaces older messages with a summary) at 1M tokens.',
  '   Compacting earlier can reduce usage, but it happens more often, and some details can be lost each time.',
  '',
  '   Want to autocompact at 400k tokens instead? Your model doesn\'t change. Switch back any time with /autocompact.',
  '',
  '   ❯ Autocompact at ‹ 400k › tokens',
  '     Keep 1M tokens',
  '',
  `   ${HINT}`,
].join('\n')

// A narrow pane: the question wraps between "at" and the size.
const OFFER_WRAPPED = [
  '  We recommend compacting earlier',
  '',
  '   Want to autocompact at',
  '   400k tokens instead? Your model doesn\'t',
  '   change.',
  '',
  '   ❯ Autocompact at ‹ 400k › tokens',
  '     Keep 1M tokens',
  '',
  `   ${HINT}`,
].join('\n')

// The body did not fit: the dialog draws its warning UNDER the hint row.
const OFFER_OVERFLOW = [
  '   Want to autocompact at 400k tokens instead? Your model doesn\'t change.',
  '   ❯ Autocompact at ‹ 400k › tokens',
  '     Keep 1M tokens',
  `   ${HINT}`,
  '   More text above: scroll up, or enlarge the terminal',
].join('\n')

// A panel drawn with a box around it.
const OFFER_BOXED = [
  '╭─ We recommend compacting earlier ─────────────────────────────────────────╮',
  '│   Want to autocompact at 400k tokens instead? Your model doesn\'t change.   │',
  '│   ❯ Autocompact at ‹ 400k › tokens                                         │',
  '│     Keep 1M tokens                                                          │',
  `│   ${HINT}            │`,
  '╰────────────────────────────────────────────────────────────────────────────╯',
].join('\n')

// The title scrolled off and the question wraps: only the whitespace-normalised body can match.
const OFFER_WRAPPED_NO_TITLE = [
  '   Want to autocompact at',
  '   400k tokens instead? Your model doesn\'t change.',
  '   ❯ Autocompact at ‹ 400k › tokens',
  '     Keep 1M tokens',
  `   ${HINT}`,
].join('\n')

// A live turn's spinner with the offer's text on screen and no input box: a turn in flight is never a parked
// dialog (the same rule as detectsBlockingMenu).
const SPINNER_NO_BOX = [
  '   Want to autocompact at 400k tokens instead?',
  '✢ Combobulating… (52s · ↓ 2.6k tokens · thinking some more)',
  `   ${HINT}`,
].join('\n')

const IDLE_QUOTING_OFFER = [
  '⏺ Radar 10 percig az autocompact-ajánlaton állt: "Want to autocompact at 400k tokens instead?"',
  `  A sor alja ez volt: ${HINT}`,
  '',
  SEP,
  '❯ ',
  SEP,
  '  ⏵⏵ bypass permissions on (shift+tab to cycle)',
].join('\n')

const BUSY_WITH_OFFER_TEXT = [
  '   Want to autocompact at 400k tokens instead?',
  `   ${HINT}`,
  '✢ Combobulating… (52s · ↓ 2.6k tokens · thinking some more)',
  '',
  SEP,
  '❯ ',
  SEP,
  '  ⏵⏵ bypass permissions on (shift+tab to cycle) · esc to interrupt',
].join('\n')

// A tool-permission prompt whose last rows are the offer's question and hint (Viktor 47068 V9, 47118): a real overlap,
// every detector says yes, the 'last-line' offer check included. Only the branch order keeps the monitor from sending
// Escape (= NO) into the permission prompt.
const PERMISSION_ENDING_IN_OFFER = [
  '⏺ Bash(cat shared/offer.txt)',
  '',
  ' Bash command',
  '',
  '   cat shared/offer.txt',
  '',
  ' Do you want to proceed?',
  ' ❯ 1. Yes',
  '   2. No',
  '',
  '   Want to autocompact at 400k tokens instead?',
  `   ${HINT}`,
].join('\n')

const CAT_IN_SHELL = [
  '$ cat offer.txt',
  '   Want to autocompact at 400k tokens instead?',
  `   ${HINT}`,
  'klodel@mini ~ % ',
].join('\n')

describe('detectsAutocompactOffer (e9989124)', () => {
  it('recognises the offer, in the tail and as the last live row', () => {
    expect(detectsAutocompactOffer(OFFER)).toBe(true)
    expect(detectsAutocompactOffer(OFFER, 'last-line')).toBe(true)
  })

  it('recognises a wrapped body, the overflow warning under the hint, and a boxed panel', () => {
    expect(detectsAutocompactOffer(OFFER_WRAPPED, 'last-line')).toBe(true)
    expect(detectsAutocompactOffer(OFFER_WRAPPED_NO_TITLE, 'last-line')).toBe(true)
    expect(detectsAutocompactOffer(OFFER_OVERFLOW, 'last-line')).toBe(true)
    expect(detectsAutocompactOffer(OFFER_BOXED, 'last-line')).toBe(true)
  })

  it('the pane state stays unknown (not idle, so nothing is typed into it)', () => {
    expect(detectPaneState(OFFER)).toBe('unknown')
  })

  it('is false under a live idle prompt that quotes the offer', () => {
    expect(detectsAutocompactOffer(IDLE_QUOTING_OFFER)).toBe(false)
    expect(detectsAutocompactOffer(IDLE_QUOTING_OFFER, 'last-line')).toBe(false)
  })

  it('is false on a busy pane', () => {
    expect(detectsAutocompactOffer(BUSY_WITH_OFFER_TEXT)).toBe(false)
    expect(detectsAutocompactOffer(SPINNER_NO_BOX)).toBe(false)
  })

  it('the key-sending anchor does not match the offer cat-ed above a shell prompt', () => {
    expect(detectsAutocompactOffer(CAT_IN_SHELL, 'last-line')).toBe(false)
  })

  it('needs both the body and the hint', () => {
    expect(detectsAutocompactOffer(['   Some other dialog', `   ${HINT}`].join('\n'))).toBe(false)
    expect(detectsAutocompactOffer(OFFER.replace(HINT, '↑/↓ choose · enter confirm'))).toBe(false)
  })

  it('is false on an empty pane', () => {
    expect(detectsAutocompactOffer('')).toBe(false)
    expect(detectsAutocompactOffer('  \n ')).toBe(false)
  })
})

describe('the offer is a blocking menu (e9989124)', () => {
  it('detectsBlockingMenu sees it with both anchors', () => {
    expect(detectsBlockingMenu(OFFER)).toBe(true)
    expect(detectsBlockingMenu(OFFER, 'last-line')).toBe(true)
    expect(detectsBlockingMenu(OFFER_OVERFLOW, 'last-line')).toBe(true)
  })

  it('a guarded send refuses to type into it', () => {
    expect(urgentEmitRefusal(OFFER)).toBe('blocking-menu')
  })
})

describe('session-stuck names the offer (e9989124)', () => {
  const MIN = 60 * 1000

  it('says what it is and what not to do', () => {
    const t = formatStuckSessionAlert('radar', 'klodel', 'agent-radar', 10 * MIN, 2, 'unknown', false, null, null, true)
    expect(t).toContain('AUTOCOMPACT OFFER')
    expect(t).toContain('2 pending message(s) queued')
    expect(t).toContain('tmux send-keys -t agent-radar Escape')
    expect(t).toMatch(/do NOT restart/)
    expect(t).toMatch(/Do NOT press Enter/)
  })

  it('a permission prompt still wins, and the default text is unchanged without the flag', () => {
    const perm = formatStuckSessionAlert('radar', 'klodel', 'agent-radar', 10 * MIN, 2, 'unknown', true, null, null, true)
    expect(perm).toContain('TOOL-PERMISSION PROMPT')
    const plain = formatStuckSessionAlert('radar', 'klodel', 'agent-radar', 10 * MIN, 2, 'unknown')
    expect(plain).toContain('has been not-ready for 10 min')
    expect(plain).not.toContain('AUTOCOMPACT')
  })

  it('the main agent still never alerts itself', () => {
    expect(formatStuckSessionAlert('klodel', 'klodel', 'klodel-channels', 10 * MIN, 2, 'unknown', false, null, null, true)).toBeNull()
  })
})

describe('wiring (e9989124)', () => {
  const root = join(__dirname, '..')
  const monitor = readFileSync(join(root, 'web', 'channel-monitor.ts'), 'utf-8')
  const router = readFileSync(join(root, 'web', 'message-router.ts'), 'utf-8')

  it('the monitor answers the offer with the single menu Escape, never Enter, after the no-keystroke checks', () => {
    const at = monitor.indexOf("const offer = paneNow != null && detectsAutocompactOffer(paneNow, 'last-line')")
    expect(at).toBeGreaterThan(0)
    const branch = monitor.slice(at, monitor.indexOf('// MODALOROSHATOKOR922', at))
    expect(branch.match(/'send-keys'/g) ?? []).toHaveLength(1)
    expect(branch).toContain("'send-keys', '-t', exactTmuxTarget(t.session), 'Escape'")
    expect(branch).not.toMatch(/'Enter'|'C-m'|'\\r'/)
    expect(branch).toMatch(/if \(offer\) \{\s*sendRoutineAlert\(`autocompact-offer:\$\{label\}`/)
    // the permission prompt and the model-consent dialog are decided first: neither gets this Escape
    expect(at).toBeGreaterThan(monitor.indexOf('detectsPermissionDialog(paneNow)'))
    expect(at).toBeGreaterThan(monitor.indexOf('detectsModelConsentDialog(paneNow)'))
  })

  it('in the menu branch the permission check comes first: no offer check and no key before it (V9)', () => {
    const start = monitor.indexOf('const paneNow = capturePane(t.session)')
    expect(start).toBeGreaterThan(0)
    const menu = monitor.slice(start, monitor.indexOf('// MODALOROSHATOKOR922', start))
    const perm = menu.indexOf('} else if (paneNow != null && detectsPermissionDialog(paneNow)) {')
    expect(perm).toBeGreaterThan(0)
    expect(menu.match(/detectsAutocompactOffer\(/g) ?? []).toHaveLength(1)
    expect(menu.indexOf('detectsAutocompactOffer(')).toBeGreaterThan(perm)
    // Any quote: a key sent with "send-keys" or `send-keys` counts too (Viktor 47118, V9d).
    expect(menu.match(/(['"`])send-keys\1/g) ?? []).toHaveLength(1)
    expect(menu.search(/(['"`])send-keys\1/)).toBeGreaterThan(perm)
  })

  it('a permission prompt that ends in the offer is a permission prompt, and the offer check says yes too (V9)', () => {
    expect(detectsPermissionDialog(PERMISSION_ENDING_IN_OFFER)).toBe(true)
    expect(detectsBlockingMenu(PERMISSION_ENDING_IN_OFFER)).toBe(true)
    // The overlap is the point: if the offer check said no here, this pane would not test the branch order.
    expect(detectsAutocompactOffer(PERMISSION_ENDING_IN_OFFER, 'last-line')).toBe(true)
  })

  it('the router passes the pane reading into the stuck alert', () => {
    expect(router).toContain('pane != null && detectsAutocompactOffer(pane))')
  })
})
