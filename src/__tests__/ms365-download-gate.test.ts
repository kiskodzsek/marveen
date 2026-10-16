import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdirSync, mkdtempSync, realpathSync, rmSync, symlinkSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
// @ts-expect-error -- plain .mjs hook script, no types
import { gateDecision } from '../../scripts/hooks/ms365-download-gate.mjs'

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
