import { describe, it, expect, afterEach, vi } from 'vitest'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import setup, {
  diskProblem, leftoverProblem, minFreeGib, freeGib, MIN_FREE_GIB_DEFAULT,
} from './setup/disk-and-tmp-root.js'

// Card 8ae42dd0 (retro 2026-11-13): the run stops below the disk floor, and every run's temp files live under one
// root that is removed afterwards; a leftover is reported, and red under MARVEEN_TEST_TMP_STRICT=1.

const saved = { ...process.env }
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
    expect(() => teardown()).toThrow(/TMP-MARADEK/)
    expect(existsSync(root)).toBe(false)
  })

  it('the leftover text lists at most ten names and the count', () => {
    const names = Array.from({ length: 12 }, (_, i) => `n${i}`)
    const msg = leftoverProblem('/r', names) as string
    expect(msg).toContain('12 bejegyzés')
    expect(msg).toContain('n9')
    expect(msg).not.toContain('n10')
    expect(leftoverProblem('/r', [])).toBeNull()
  })
})
