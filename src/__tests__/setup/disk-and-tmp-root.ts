// vitest globalSetup: stop before the run when the disk is nearly full, and give every run its own temp root that
// is removed afterwards (retro 2026-11-13, Kernel's input (a), card 8ae42dd0).
//
// WHY: on 2026-11-13 the test runs of Kernel's installer branches copied a 344 MB binary into $TMPDIR per run and
// never removed it; the mini's disk fell to 534 MiB free (Klodel 40964, near an outage). A test that does not clean
// up is invisible while the disk has room, and the suite that fills the disk is not the one that fails.
//
//   1. Before the run: free space on the temp volume below MIN_FREE_GIB (5 GiB, the fleet's floor; override
//      MARVEEN_TEST_MIN_FREE_GIB) stops the run with a reason, before any test writes.
//   2. TMPDIR points to a fresh per-run root (mkdtemp under the original temp dir); os.tmpdir() in the workers
//      reads it, so every mkdtemp(tmpdir()) of the suite lands under it.
//   3. After the run the root is removed whatever it holds. Leftovers are reported with the first names; with
//      MARVEEN_TEST_TMP_STRICT=1 (set in CI once the suite is clean) a leftover turns the run red.
import { mkdtempSync, readdirSync, rmSync, statfsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export const MIN_FREE_GIB_DEFAULT = 5
const GIB = 1024 ** 3

export function freeGib(dir: string): number {
  const s = statfsSync(dir)
  return (Number(s.bavail) * Number(s.bsize)) / GIB
}

export function minFreeGib(env: NodeJS.ProcessEnv = process.env): number {
  const v = Number(env.MARVEEN_TEST_MIN_FREE_GIB)
  return Number.isFinite(v) && v >= 0 && env.MARVEEN_TEST_MIN_FREE_GIB !== '' && env.MARVEEN_TEST_MIN_FREE_GIB !== undefined
    ? v : MIN_FREE_GIB_DEFAULT
}

export function diskProblem(dir: string, min: number, free: (d: string) => number = freeGib): string | null {
  const have = free(dir)
  if (have >= min) return null
  return `LEMEZ-KAPU: ${have.toFixed(1)} GiB szabad a ${dir} kötetén, a padló ${min} GiB; a tesztfutás nem indul. ` +
    'Szabadíts fel helyet (régi worktree, build-cache, tmp), vagy szólj Kernelnek. ' +
    `/ DISK GATE: ${have.toFixed(1)} GiB free on the temp volume, floor ${min} GiB; the run does not start.`
}

export function leftoverProblem(root: string, names: string[]): string | null {
  if (names.length === 0) return null
  return `TMP-MARADEK: a tesztfutás után ${names.length} bejegyzés maradt a ${root} alatt (törölve): ` +
    names.slice(0, 10).join(', ') + (names.length > 10 ? ', ...' : '') +
    '. A teszt takarítson maga után (afterEach/afterAll rmSync). / Tests left entries in the per-run temp root.'
}

let root: string | null = null
let originalTmp: string | undefined

export default function setup(): () => void {
  originalTmp = process.env.TMPDIR
  const base = tmpdir()
  const problem = diskProblem(base, minFreeGib())
  if (problem) throw new Error(problem)
  // A short prefix: a tmux or other Unix socket under the root must stay under the 104-byte path limit of macOS
  // (measured: 'marveen-vitest-XXXXXX' made tmux-exact-target's socket path "File name too long").
  root = mkdtempSync(join(base, 'mvt-'))
  process.env.TMPDIR = root
  return function teardown(): void {
    if (!root) return
    const r = root
    let names: string[] = []
    try { names = readdirSync(r) } catch { names = [] }
    rmSync(r, { recursive: true, force: true })
    root = null
    if (originalTmp === undefined) delete process.env.TMPDIR
    else process.env.TMPDIR = originalTmp
    const msg = leftoverProblem(r, names)
    if (!msg) return
    if (process.env.MARVEEN_TEST_TMP_STRICT === '1') throw new Error(msg)
    console.warn(msg)
  }
}
