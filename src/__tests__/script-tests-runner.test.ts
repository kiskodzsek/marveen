// Every scripts/__tests__ suite runs in CI, discovered, not enumerated.
//
// Measured 2026-09-05: scripts/__tests__ held 29 executable suites and only 4
// were reachable from the vitest run -- the other 25 had never been executed by
// anything but a human typing their path. Among the dead ones were the gate's
// own fail-closed exit-code contract (outgoing-copy-gate-failclosed), the shell
// portability suite written the night before, and the hook double-run audit.
// Two of the 25 were in fact FAILING: seed-skills asserted a template sentence
// that 827491c rewrote away, and stop-start-system-unit asserted the systemd
// branch on a machine that has no systemd. Nobody could know, because nothing
// ran them.
//
// Enumerating them here would rot the same way, so the list is discovered from
// disk: a new scripts/__tests__/*.test.sh is in CI the moment it is written.
// The four suites with their own dedicated wrapper run twice; that is the cheap
// direction of the trade, because deleting a wrapper must not silently retire a
// suite.
import { describe, it, expect } from 'vitest'
import { spawnSync } from 'node:child_process'
import { readdirSync } from 'node:fs'
import { join } from 'node:path'

const ROOT = join(__dirname, '..', '..')
const DIR = join(ROOT, 'scripts', '__tests__')

// `*-test.py` is the older naming; both spellings are real suites in this tree.
const SUITES = readdirSync(DIR)
  .filter((f) => /\.test\.(sh|py)$/.test(f) || /-test\.py$/.test(f))
  .sort()

// Suites that measure macOS-only code as a whole, so they run on Darwin only (CI is ubuntu-latest).
// Measured 2026-11-11 (card ac602965) in an ubuntu:24.04 container as a non-root user, the same failures
// as CI run 42805724668: each fails there because the code under test is macOS-only, not because it broke;
// all pass on the Mac mini. A suite with only a FEW macOS-only cases guards those cases itself
// (daily-cleanup.test.sh, clone-dedupe.test.py) and stays here in full. Keep every reason concrete.
const MACOS_ONLY: Record<string, string> = {
  'mem-relief.test.sh':
    'stops the Colima VM (colima/limactl) and installs a launchd plist; install-mem-relief.sh refuses non-Darwin by design',
  'memgate-macos-heavy-job.test.sh':
    'the macOS memory gate of heavy-job.sh: sysctl vm.swapusage, the Colima VM check and BSD stat; Linux reads /proc/meminfo, covered by its own suites',
  'ssh-unlock-setup.test.sh':
    'stages the macOS Remote Login sshd drop-in and mirrors the LIVE /etc/ssh/sshd_config.d (100-macos.conf); on the GitHub runner that directory holds a root-only 50-cloud-init.conf',
}
const IS_DARWIN = process.platform === 'darwin'

describe('scripts/__tests__ suites', () => {
  it('finds the suites on disk (a rename must not silently empty this run)', () => {
    expect(SUITES.length).toBeGreaterThan(20)
  })

  it('every MACOS_ONLY entry names a suite that exists (no ghost exemption)', () => {
    expect(Object.keys(MACOS_ONLY).filter((name) => !SUITES.includes(name))).toEqual([])
  })

  it.each(SUITES.filter((name) => IS_DARWIN || !(name in MACOS_ONLY)))('%s passes', (name) => {
    const runner = name.endsWith('.py') ? 'python3' : 'bash'
    const res = spawnSync(runner, [join(DIR, name)], {
      encoding: 'utf-8',
      timeout: 300_000,
      cwd: ROOT,
    })
    if (res.status !== 0) {
      console.error(`--- ${name} stdout ---\n${res.stdout ?? ''}`)
      console.error(`--- ${name} stderr ---\n${res.stderr ?? ''}`)
    }
    expect(res.status).toBe(0)
  }, 310_000)

  // Off macOS the macOS-only suites show up as skipped, by name, rather than disappearing.
  it.skipIf(IS_DARWIN).each(Object.keys(MACOS_ONLY))('%s: macOS-only, skipped on this platform', () => {})
})
