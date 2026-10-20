import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, statSync, symlinkSync, utimesSync, writeFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
// @ts-expect-error -- plain .mjs hook script, no types
import { consumeMarker, gateDecision } from '../../scripts/hooks/ms365-download-gate.mjs'

// download-bytes-to-file writes third-party bytes wherever outputPath says;
// the server only refuses overwrites. The gate is the directory boundary, so
// the deny cases below are the acceptance bar.
describe('ms365-download-gate', () => {
  let tmp: string
  let drop: string
  const att = '/me/messages/AAMkAD-x_y=/attachments/AAMkAD-a_b=/$value'
  beforeEach(() => {
    tmp = realpathSync(mkdtempSync(join(tmpdir(), 'dlgate-')))
    drop = join(tmp, 'mail-downloads')
    mkdirSync(join(drop, 'sub'), { recursive: true })
  })
  afterEach(() => rmSync(tmp, { recursive: true, force: true }))
  const decide = (target: string, outputPath: string, dir = drop) => gateDecision({ target, outputPath }, dir)

  it('allows a mail attachment into the drop directory', () => {
    expect(decide(att, join(drop, 'hibás_számlák.pdf')).deny).toBe(false)
  })
  it('allows the /users/<id> and mailFolders shapes', () => {
    expect(decide('/users/u1/messages/m/attachments/a/$value', join(drop, 'a.pdf')).deny).toBe(false)
    expect(decide('/me/mailFolders/inbox/messages/m/attachments/a/$value', join(drop, 'a.pdf')).deny).toBe(false)
  })

  it('denies any non-attachment target', () => {
    for (const t of [
      '/me/drive/root/content',
      '/me/photo/$value',
      '/me/messages/m/$value',
      '/me/messages/m/attachments/a/$value?x=1',
      '/me/messages/m/attachments/a/$value/extra',
      'https://graph.microsoft.com/v1.0/me/messages/m/attachments/a/$value',
    ]) expect(decide(t, join(drop, 'a.pdf')).deny, t).toBe(true)
  })

  it('denies paths outside the drop directory', () => {
    mkdirSync(join(tmp, 'mail-downloads-evil'))
    expect(decide(att, join(tmp, 'a.pdf')).deny).toBe(true)
    expect(decide(att, join(tmp, 'mail-downloads-evil', 'a.pdf')).deny).toBe(true)
    expect(decide(att, join(drop, 'sub', 'a.pdf')).deny).toBe(true)
    expect(decide(att, '/Users/klodel/Library/LaunchAgents/x.plist').deny).toBe(true)
  })
  it('denies traversal and non-normalised paths', () => {
    expect(decide(att, `${drop}/../a.pdf`).deny).toBe(true)
    expect(decide(att, `${drop}/sub/../a.pdf`).deny).toBe(true)
    expect(decide(att, `${drop}//a.pdf`).deny).toBe(true)
    expect(decide(att, 'a.pdf').deny).toBe(true)
  })
  it('denies a symlinked directory inside the drop dir that points out', () => {
    mkdirSync(join(tmp, 'outside'))
    symlinkSync(join(tmp, 'outside'), join(drop, 'link'))
    expect(decide(att, join(drop, 'link', 'a.pdf')).deny).toBe(true)
  })
  it('allows a drop directory reached through a symlink (realpath on both sides)', () => {
    symlinkSync(drop, join(tmp, 'alias'))
    expect(decide(att, join(tmp, 'alias', 'a.pdf'), join(tmp, 'alias')).deny).toBe(false)
  })
  it('denies hidden or control-character names', () => {
    expect(decide(att, join(drop, '.zshrc')).deny).toBe(true)
    expect(decide(att, join(drop, 'a\nb.pdf')).deny).toBe(true)
  })
  it('denies when the drop directory does not exist', () => {
    expect(decide(att, join(drop, 'a.pdf'), join(tmp, 'missing')).deny).toBe(true)
  })
  it('denies dot segments in the target', () => {
    expect(decide('/me/messages/../photo/attachments/a/$value', join(drop, 'a.pdf')).deny).toBe(true)
    expect(decide('/me/messages/m/attachments/./$value', join(drop, 'a.pdf')).deny).toBe(true)
    expect(decide('/me/messages/m..x/attachments/a.b/$value', join(drop, 'a.pdf')).deny).toBe(false)
  })
  it('denies executable or auto-opening file types, any case', () => {
    for (const n of ['x.command', 'x.PKG', 'x.terminal', 'x.webloc', 'x.scpt', 'x.sh', 'x.app', 'x.plist', 'x.pdf.command'])
      expect(decide(att, join(drop, n)).deny, n).toBe(true)
    expect(decide(att, join(drop, 'invoice.pdf')).deny).toBe(false)
  })
  it('allows only the data-extension allowlist, anchored on the last extension (Viktor 6359)', () => {
    for (const n of ['x.PDF', 'x.pdf', 'e-szamla.xml', 'a.csv', 'a.xlsx', 'a.docx', 'a.png', 'a.JPG', 'a.jpeg', 'a.heic', 'a.txt'])
      expect(decide(att, join(drop, n)).deny, n).toBe(false)
    for (const n of ['x.zip', 'x.bin', 'noextension', 'x.pdf.', 'x.pdf ', 'x.pdf.app', 'x.xlsm', 'x.docm', 'x.xls', 'x.html', 'x.svg', 'x.pdfx'])
      expect(decide(att, join(drop, n)).deny, n).toBe(true)
  })
  it('the deny reason names the allowed types and does not suggest renaming', () => {
    const { reason } = decide(att, join(drop, 'x.zip'))
    expect(reason).toContain('Allowed types: pdf, xml')
    expect(reason).not.toMatch(/\.bin|data extension|Save it under/)
  })
  it('denies bidi control characters in the name', () => {
    expect(decide(att, join(drop, 'invoice\u202Efdp.command')).deny).toBe(true)
    // RLO on an otherwise allowed extension: only the bidi rule can deny this one
    expect(decide(att, join(drop, 'invoice\u202Efdp.pdf')).deny).toBe(true)
    expect(decide(att, join(drop, 'a\u2066b.pdf')).deny).toBe(true)
  })
  it('denies missing or non-string fields', () => {
    expect(gateDecision({}, drop).deny).toBe(true)
    expect(gateDecision({ target: att }, drop).deny).toBe(true)
    expect(gateDecision(undefined, drop).deny).toBe(true)
  })

  it('as a hook process: exit 2 on deny, 0 on allow, 2 on garbage input', () => {
    const run = (input: string) =>
      spawnSync(process.execPath, ['scripts/hooks/ms365-download-gate.mjs'], {
        input,
        env: { ...process.env, MS365_DOWNLOAD_DIR: drop },
      }).status
    const payload = (outputPath: string) => JSON.stringify({ tool_name: 'mcp__ms365__download-bytes-to-file', tool_input: { target: att, outputPath } })
    expect(run(payload(join(drop, 'a.pdf')))).toBe(0)
    expect(run(payload(join(tmp, 'a.pdf')))).toBe(2)
    expect(run('not json')).toBe(2)
  })
})

// The whole-message ($value) shape: closed unless the one-shot marker is fresh,
// and then only into the MIME directory as .eml (Klodel 11031).
describe('ms365-download-gate, one-shot MIME shape', () => {
  let tmp: string
  let drop: string
  let mime: string
  let once: string
  const msg = '/me/messages/AAMkAD-x_y=/$value'
  beforeEach(() => {
    tmp = realpathSync(mkdtempSync(join(tmpdir(), 'dlgate-mime-')))
    drop = join(tmp, 'mail-downloads')
    mime = join(tmp, 'secure')
    once = join(tmp, 'ms365-mime-once')
    mkdirSync(drop)
    mkdirSync(join(mime, 'sub'), { recursive: true })
  })
  afterEach(() => rmSync(tmp, { recursive: true, force: true }))
  const decide = (target: string, outputPath: string, now = Date.now()) =>
    gateDecision({ target, outputPath }, drop, { mimeDir: mime, mimeOnce: once, now })

  it('denies a whole message while the marker is missing', () => {
    expect(decide(msg, join(mime, 'confirm.eml')).deny).toBe(true)
  })
  it('allows it into the MIME directory as .eml while the marker is fresh', () => {
    writeFileSync(once, '')
    expect(decide(msg, join(mime, 'confirm.eml')).deny).toBe(false)
  })
  it('denies once the marker is older than 60 minutes, or is a directory', () => {
    writeFileSync(once, '')
    const old = (Date.now() - 61 * 60 * 1000) / 1000
    utimesSync(once, old, old)
    expect(decide(msg, join(mime, 'confirm.eml')).deny).toBe(true)
    rmSync(once)
    mkdirSync(once)
    expect(decide(msg, join(mime, 'confirm.eml')).deny).toBe(true)
  })
  it('with a fresh marker still denies other places, names and types', () => {
    writeFileSync(once, '')
    expect(decide(msg, join(drop, 'confirm.eml')).deny).toBe(true)
    expect(decide(msg, join(mime, 'sub', 'confirm.eml')).deny).toBe(true)
    expect(decide(msg, `${mime}/../confirm.eml`).deny).toBe(true)
    expect(decide(msg, join(mime, '.confirm.eml')).deny).toBe(true)
    for (const n of ['confirm.pdf', 'confirm.eml.command', 'confirm', 'confirm.EML.sh', 'confirm.EML', 'számla.eml', 'a b.eml', 'a\u202Eb.eml'])
      expect(decide(msg, join(mime, n)).deny, n).toBe(true)
    expect(decide(msg, join(mime, 'confirm-1_a.b.eml')).deny).toBe(false)
  })
  it('denies a symlinked parent that points out of the MIME directory', () => {
    writeFileSync(once, '')
    mkdirSync(join(tmp, 'outside'))
    symlinkSync(join(tmp, 'outside'), join(mime, 'link'))
    expect(decide(msg, join(mime, 'link', 'confirm.eml')).deny).toBe(true)
  })
  it('an allow names the marker to consume; the attachment shape never does', () => {
    writeFileSync(once, '')
    expect(decide(msg, join(mime, 'confirm.eml')).consumeMarker).toBe(once)
    expect(decide('/me/messages/m/attachments/a/$value', join(drop, 'a.pdf')).consumeMarker).toBeUndefined()
  })
  it('consumeMarker deletes the marker, logs a timestamp only, and denies if either fails', () => {
    writeFileSync(once, '')
    const log = join(tmp, 'gate.log')
    expect(consumeMarker(once, log, new Date('2026-10-20T15:30:00Z')).deny).toBe(false)
    expect(existsSync(once)).toBe(false)
    expect(readFileSync(log, 'utf-8')).toBe('2026-10-20T15:30:00.000Z ms365-mime-once consumed: one whole-message download allowed\n')
    expect(statSync(log).mode & 0o777).toBe(0o600)
    expect(consumeMarker(once, log).deny).toBe(true)
    writeFileSync(once, '')
    expect(consumeMarker(once, join(tmp, 'missing', 'gate.log')).deny).toBe(true)
  })
  it('as a hook process: one marker serves exactly one download', () => {
    writeFileSync(once, '')
    const log = join(tmp, 'gate.log')
    const run = () =>
      spawnSync(process.execPath, ['scripts/hooks/ms365-download-gate.mjs'], {
        input: JSON.stringify({ tool_name: 'mcp__ms365__download-bytes-to-file', tool_input: { target: msg, outputPath: join(mime, 'confirm.eml') } }),
        env: { ...process.env, MS365_DOWNLOAD_DIR: drop, MS365_MIME_DIR: mime, MS365_MIME_ONCE: once, MS365_MIME_LOG: log },
      }).status
    expect(run()).toBe(0)
    expect(existsSync(once)).toBe(false)
    expect(run()).toBe(2)
    expect(readFileSync(log, 'utf-8').trim().split('\n')).toHaveLength(1)
    expect(readFileSync(log, 'utf-8')).not.toContain('AAMkAD')
  })
  it('with a fresh marker still denies other mailboxes, folders and query strings', () => {
    writeFileSync(once, '')
    for (const t of [
      '/users/u1/messages/m/$value',
      '/me/mailFolders/inbox/messages/m/$value',
      '/me/messages/m/$value?x=1',
      '/me/messages/../photo/$value',
      '/me/photo/$value',
      'https://graph.microsoft.com/v1.0/me/messages/m/$value',
    ]) expect(decide(t, join(mime, 'confirm.eml')).deny, t).toBe(true)
  })
  it('does not let .eml into the attachment drop directory', () => {
    writeFileSync(once, '')
    expect(decide('/me/messages/m/attachments/a/$value', join(drop, 'x.eml')).deny).toBe(true)
    expect(decide('/me/messages/m/attachments/a/$value', join(mime, 'x.pdf')).deny).toBe(true)
  })
})
