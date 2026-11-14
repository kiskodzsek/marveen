import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { chmodSync, existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import setup, {
  diskProblem, leftoverProblem, minFreeGib, freeGib, removeRoot, MIN_FREE_GIB_DEFAULT,
} from './setup/disk-and-tmp-root.js'

// Card 8ae42dd0 (retro 2026-11-13): the run stops below the disk floor, and every run's temp files live under one
// root that is removed afterwards; a leftover is reported, and red under MARVEEN_TEST_TMP_STRICT=1.

const saved = { ...process.env }
// CI runs the suite with MARVEEN_TEST_TMP_STRICT=1 (card 400faadf); every test here starts without it and sets it
// itself where it is the subject
beforeEach(() => { delete process.env.MARVEEN_TEST_TMP_STRICT })
afterEach(() => {
  for (const k of ['TMPDIR', 'MARVEEN_TEST_MIN_FREE_GIB', 'MARVEEN_TEST_TMP_STRICT']) {
    if (saved[k] === undefined) delete process.env[k]
    else process.env[k] = saved[k]
  }
  vi.restoreAllMocks()
})

describe('disk floor', () => {
  it('blocks below the floor and names the free space, the floor and the volume', () => {
    const msg = diskProblem('/vol', 5, () => 0.5)
    expect(msg).toContain('LEMEZ-KAPU')
    expect(msg).toContain('0.5 GiB')
    expect(msg).toContain('5 GiB')
    expect(msg).toContain('/vol')
  })

  it('passes at and above the floor', () => {
    expect(diskProblem('/vol', 5, () => 5)).toBeNull()
    expect(diskProblem('/vol', 5, () => 18.1)).toBeNull()
  })

  it('the floor is 5 GiB unless MARVEEN_TEST_MIN_FREE_GIB sets a non-negative number', () => {
    expect(MIN_FREE_GIB_DEFAULT).toBe(5)
    expect(minFreeGib({})).toBe(5)
    expect(minFreeGib({ MARVEEN_TEST_MIN_FREE_GIB: '0' })).toBe(0)
    expect(minFreeGib({ MARVEEN_TEST_MIN_FREE_GIB: '12.5' })).toBe(12.5)
    for (const bad of ['', 'x', '-1']) expect(minFreeGib({ MARVEEN_TEST_MIN_FREE_GIB: bad })).toBe(5)
  })

  it('freeGib reads the real volume', () => {
    expect(freeGib(process.cwd())).toBeGreaterThan(0)
  })

  it('setup throws before creating anything when the floor is above the free space', () => {
    process.env.MARVEEN_TEST_MIN_FREE_GIB = '1000000'
    const before = process.env.TMPDIR
    expect(() => setup()).toThrow(/LEMEZ-KAPU/)
    expect(process.env.TMPDIR).toBe(before)
  })
})

describe('per-run temp root', () => {
  it('points TMPDIR to a fresh short root and removes it with its content; TMPDIR is restored', () => {
    process.env.MARVEEN_TEST_MIN_FREE_GIB = '0'
    const before = process.env.TMPDIR
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const teardown = setup()
    const root = process.env.TMPDIR as string
    expect(root).not.toBe(before)
    expect(root.split('/').pop()).toMatch(/^mvt-/)
    mkdirSync(join(root, 'left-dir'))
    writeFileSync(join(root, 'left-dir', 'f'), 'x')
    teardown()
    expect(existsSync(root)).toBe(false)
    expect(process.env.TMPDIR).toBe(before)
    expect(warn).toHaveBeenCalledTimes(1)
    expect(String(warn.mock.calls[0][0])).toContain('left-dir')
  })

  it('a clean run says nothing', () => {
    process.env.MARVEEN_TEST_MIN_FREE_GIB = '0'
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    setup()()
    expect(warn).not.toHaveBeenCalled()
  })

  it('MARVEEN_TEST_TMP_STRICT=1 turns a leftover red, after removing it', () => {
    process.env.MARVEEN_TEST_MIN_FREE_GIB = '0'
    process.env.MARVEEN_TEST_TMP_STRICT = '1'
    const teardown = setup()
    const root = process.env.TMPDIR as string
    writeFileSync(join(root, 'left'), 'x')
    const code = process.exitCode
    try {
      expect(() => teardown()).toThrow(/TMP-MARADEK/)
      // card 400faadf: vitest 4.1 exits 0 after an error thrown in a globalSetup teardown; the exit code makes it red
      expect(process.exitCode).toBe(1)
    } finally {
      process.exitCode = code
    }
    expect(existsSync(root)).toBe(false)
  })

  it('an unreadable (chmod 000) leftover folder is still removed, not red without STRICT, TMPDIR restored (Viktor 41392)', () => {
    process.env.MARVEEN_TEST_MIN_FREE_GIB = '0'
    const before = process.env.TMPDIR
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const teardown = setup()
    const root = process.env.TMPDIR as string
    mkdirSync(join(root, 'locked', 'inner'), { recursive: true })
    writeFileSync(join(root, 'locked', 'inner', 'f'), 'x')
    chmodSync(join(root, 'locked'), 0o000)
    expect(() => teardown()).not.toThrow()
    expect(existsSync(root)).toBe(false)
    expect(process.env.TMPDIR).toBe(before)
    expect(warn).toHaveBeenCalledTimes(1)
    expect(String(warn.mock.calls[0][0])).toContain('locked')
  })

  it('a root that cannot be removed is reported by name, and TMPDIR is restored before', () => {
    const parent = mkdtempSync(join(tmpdir(), 'mvt-rm-'))
    const r = join(parent, 'root')
    mkdirSync(r)
    chmodSync(parent, 0o500)
    try {
      const msg = removeRoot(r)
      expect(msg).toContain('TMP-GYOKER')
      expect(msg).toContain(r)
    } finally {
      chmodSync(parent, 0o700)
      rmSync(parent, { recursive: true, force: true })
    }
    expect(removeRoot(join(parent, 'gone'))).toBeNull()
  })

  it('the leftover text lists at most ten names and the count', () => {
    const names = Array.from({ length: 12 }, (_, i) => `n${i}`)
    const msg = leftoverProblem('/r', names) as string
    expect(msg).toContain('12 bejegyzés')
    expect(msg).toContain('n9')
    expect(msg).not.toContain('n10')
    expect(leftoverProblem('/r', [])).toBeNull()
    // the ssh seam is a bounded, reused directory, not a leftover; anything next to it still is
    expect(leftoverProblem('/r', ['marveen-ssh-seam'])).toBeNull()
    expect(leftoverProblem('/r', ['marveen-ssh-seam', 'x'])).toContain('1 bejegyzés')
    // Viktor 41495 INFO 1: the exemption is the exact name, not a prefix.
    expect(leftoverProblem('/r', ['marveen-ssh-seam-extra'])).toContain('1 bejegyzés')
    expect(leftoverProblem('/r', ['marveen-ssh-seam2', 'marveen-ssh'])).toContain('2 bejegyzés')
  })
})
