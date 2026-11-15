import { describe, it, expect } from 'vitest'
import { join } from 'node:path'
import { mkdtempSync, mkdirSync, writeFileSync, utimesSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { projectsDirFor, readLiveSessionModel, resetTranscriptScansForTests } from '../web/active-model.js'

// Card e6b7df37: the model hold looks for a NEW session by the live transcript's id.
describe('readLiveSessionModel', () => {
  const line = (type: string, ts: string, model?: string) =>
    JSON.stringify({ type, timestamp: ts, message: model ? { role: 'assistant', model } : { role: 'user', content: 'x' } }) + '\n'

  it('names the live session and its newest assistant model; an old file with a newer mtime does not win', () => {
    resetTranscriptScansForTests()
    const cfg = mkdtempSync(join(tmpdir(), 'live-session-'))
    try {
      const dir = projectsDirFor('/w', cfg)
      mkdirSync(dir, { recursive: true })
      writeFileSync(join(dir, 'old.jsonl'), line('assistant', '2026-11-15T21:58:24Z', 'claude-fable-5-2'))
      writeFileSync(join(dir, 'new.jsonl'), line('user', '2026-11-15T21:59:20Z') + line('assistant', '2026-11-15T21:59:22Z', 'claude-opus-5-5'))
      // the old transcript's FILE was touched later (card 3bbf80ca), its last turn stays older
      const later = new Date('2026-11-15T22:30:00Z')
      utimesSync(join(dir, 'old.jsonl'), later, later)
      expect(readLiveSessionModel('/w', cfg)).toEqual({ id: 'new', model: 'claude-opus-5-5' })
    } finally { rmSync(cfg, { recursive: true, force: true }) }
  })

  it('a fresh session before its first assistant line: its id, model null; no project dir: null', () => {
    resetTranscriptScansForTests()
    const cfg = mkdtempSync(join(tmpdir(), 'live-session-'))
    try {
      expect(readLiveSessionModel('/w', cfg)).toBeNull()
      const dir = projectsDirFor('/w', cfg)
      mkdirSync(dir, { recursive: true })
      writeFileSync(join(dir, 'prev.jsonl'), line('assistant', '2026-11-15T21:58:24Z', 'claude-fable-5-2'))
      writeFileSync(join(dir, 'fresh.jsonl'), line('user', '2026-11-15T21:59:20Z'))
      expect(readLiveSessionModel('/w', cfg)).toEqual({ id: 'fresh', model: null })
    } finally { rmSync(cfg, { recursive: true, force: true }) }
  })

  it('a placeholder model (<synthetic>) is skipped: the real model before it counts (Viktor 43389 V7)', () => {
    resetTranscriptScansForTests()
    const cfg = mkdtempSync(join(tmpdir(), 'live-session-'))
    try {
      const dir = projectsDirFor('/w', cfg)
      mkdirSync(dir, { recursive: true })
      writeFileSync(join(dir, 's.jsonl'), line('assistant', '2026-11-15T21:59:22Z', 'claude-opus-5-5') + line('assistant', '2026-11-15T21:59:30Z', '<synthetic>'))
      expect(readLiveSessionModel('/w', cfg)).toEqual({ id: 's', model: 'claude-opus-5-5' })
    } finally { rmSync(cfg, { recursive: true, force: true }) }
  })
})

describe('projectsDirFor', () => {
  it('uses <home>/.claude/projects when no config dir is given', () => {
    const result = projectsDirFor('/home/u/work', undefined, '/home/u')
    expect(result).toBe(join('/home/u', '.claude', 'projects', '-home-u-work'))
  })

  it('uses the supplied config dir instead of the default home location', () => {
    const result = projectsDirFor('/home/u/work', '/home/u/.claude-coding', '/home/u')
    expect(result).toBe(join('/home/u/.claude-coding', 'projects', '-home-u-work'))
  })

  it('does not fall back to the home dir when a config dir is supplied', () => {
    const result = projectsDirFor('/home/u/work', '/var/lib/claude-coding', '/home/u')
    expect(result.startsWith('/var/lib/claude-coding')).toBe(true)
    expect(result).not.toContain('/home/u/.claude')
  })

  it('encodes slashes and dots in the working dir to dashes', () => {
    const result = projectsDirFor('/home/u/some.dir/app', '/cfg', '/home/u')
    expect(result).toBe(join('/cfg', 'projects', '-home-u-some-dir-app'))
  })

  it('produces distinct project dirs for the same working dir on different config roots', () => {
    const a = projectsDirFor('/w', '/home/u/.claude', '/home/u')
    const b = projectsDirFor('/w', '/home/u/.claude-coding', '/home/u')
    expect(a).not.toBe(b)
  })
})
