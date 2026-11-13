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
import { chmodSync, mkdtempSync, readdirSync, rmSync, statfsSync, type Dirent } from 'node:fs'
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

// Bounded on purpose, not a leak: default-ssh-dir-seam.ts keeps one reused directory per worker slot under here
// (cleared on entry). It is removed with the root like everything else, but it is not reported as a leftover
// (Viktor 41424 INFO 3: under MARVEEN_TEST_TMP_STRICT=1 it would turn every run red).
export const KNOWN_SEAMS = ['marveen-ssh-seam']

export function leftoverProblem(root: string, all: string[]): string | null {
  const names = all.filter((n) => !KNOWN_SEAMS.includes(n))
  if (names.length === 0) return null
  return `TMP-MARADEK: a tesztfutás után ${names.length} bejegyzés maradt a ${root} alatt (törölve): ` +
    names.slice(0, 10).join(', ') + (names.length > 10 ? ', ...' : '') +
    '. A teszt takarítson maga után (afterEach/afterAll rmSync). / Tests left entries in the per-run temp root.'
}

// Make every directory under r readable and writable for us (a test may leave a chmod 000 folder), without
// following symlinks (a symlinked directory is a Dirent that is not a directory).
function unlockTree(r: string): void {
  try { chmodSync(r, 0o700) } catch { return }
  let entries: Dirent[] = []
  try { entries = readdirSync(r, { withFileTypes: true }) } catch { return }
  for (const e of entries) if (e.isDirectory()) unlockTree(join(r, e.name))
}

// Removes the run root. rmSync's force only swallows ENOENT: an unreadable folder throws EACCES (Viktor 41392 LOW),
// so on a failure the tree is unlocked and the removal tried once more. Returns null, or what could not be removed.
export function removeRoot(r: string): string | null {
  try { rmSync(r, { recursive: true, force: true }); return null } catch { /* unlock and retry below */ }
  unlockTree(r)
  try { rmSync(r, { recursive: true, force: true }); return null } catch (e) {
    return `TMP-GYOKER: a ${r} nem törölhető (${(e as NodeJS.ErrnoException).code ?? 'hiba'}); töröld kézzel. ` +
      '/ The per-run temp root could not be removed.'
  }
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
    // TMPDIR and the module state are restored first, so a failed removal cannot leave them pointing at the root.
    root = null
    if (originalTmp === undefined) delete process.env.TMPDIR
    else process.env.TMPDIR = originalTmp
    let names: string[] = []
    try { names = readdirSync(r) } catch { names = [] }
    const stuck = removeRoot(r)
    const msg = [leftoverProblem(r, names), stuck].filter(Boolean).join(' ')
    if (!msg) return
    if (process.env.MARVEEN_TEST_TMP_STRICT === '1') throw new Error(msg)
    console.warn(msg)
  }
}
