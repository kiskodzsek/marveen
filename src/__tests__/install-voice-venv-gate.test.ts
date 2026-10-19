import { describe, it, expect, beforeAll } from 'vitest'
import { execFileSync } from 'node:child_process'
import { readFileSync, mkdtempSync, mkdirSync, writeFileSync, existsSync, symlinkSync, chmodSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

// Step 2 is re-run on every install attempt, so its idempotency gate decides
// whether a broken install can ever recover. The gate used to be
// `[[ ! -d "$DEST/venv" ]]`, which asks whether the DIRECTORY exists rather than
// whether the venv WORKS. An interrupted or partial earlier run can leave a
// few-kilobyte venv stub behind -- a bin/ holding the python symlinks and no pip
// at all -- and `-d` is true for it. Step 2 is then skipped on every single run,
// and step 3 dies on
//
//     .../venv/bin/pip: No such file or directory
//
// Retrying cannot help: each attempt takes the same SKIP.
//
// These tests execute the REAL step 2 out of the shipped script (with a stubbed
// DEST) rather than re-describing it, because the fault is invisible at the
// level of reading the condition.

const ROOT = join(__dirname, '..', '..')
const SCRIPT = join(ROOT, 'scripts', 'install-voice.sh')
const SRC = readFileSync(SCRIPT, 'utf-8')

/** Slice one `# --- Step N: ... ---` block out of the installer. */
function sliceStep(src: string, header: string, nextHeader: string): string {
  const start = src.indexOf(header)
  if (start < 0) throw new Error(`step header not found: ${header}`)
  const end = src.indexOf(nextHeader, start)
  if (end < 0) throw new Error(`next step header not found: ${nextHeader}`)
  return src.slice(start, end)
}

const STEP2 = sliceStep(SRC, '# --- Step 2: Python venv ---', '# --- Step 3:')

/**
 * Run the REAL step 2 against a scratch DEST. Only the four echo helpers and
 * DEST are stubbed; the gate and the venv creation are the shipped lines.
 */
function runStep2(dest: string, env: Record<string, string> = {}): { code: number; out: string } {
  return runStep(STEP2, dest, env)
}

function runStep(step: string, dest: string, env: Record<string, string> = {}): { code: number; out: string } {
  const script = [
    'set -euo pipefail',
    `DEST=${JSON.stringify(dest)}`,
    '_pass() { echo "    [PASS] $*"; }',
    '_skip() { echo "    [SKIP] $*"; }',
    '_fail() { echo "    [FAIL] $*" >&2; exit 1; }',
    '_step() { echo ""; echo "==> $*"; }',
    step,
  ].join('\n')
  try {
    const out = execFileSync('bash', ['-c', script], {
      encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, ...env },
    })
    return { code: 0, out }
  } catch (err) {
    const e = err as { status?: number; stdout?: string; stderr?: string }
    return { code: e.status ?? -1, out: (e.stdout ?? '') + (e.stderr ?? '') }
  }
}

/** Reproduce the stub a partial install leaves: bin/ has python, but no pip. */
function makeBrokenVenv(dest: string): void {
  const bin = join(dest, 'venv', 'bin')
  mkdirSync(bin, { recursive: true })
  const python3 = execFileSync('bash', ['-c', 'command -v python3'], { encoding: 'utf-8' }).trim()
  symlinkSync(python3, join(bin, 'python'))
  symlinkSync(python3, join(bin, 'python3'))
  writeFileSync(join(dest, 'venv', 'pyvenv.cfg'), 'home = /usr/bin\n')
}

/** A healthy-looking venv that must NOT be rebuilt: bin/pip is executable and bin/python runs. */
function makeWorkingVenv(dest: string): void {
  const bin = join(dest, 'venv', 'bin')
  mkdirSync(bin, { recursive: true })
  for (const name of ['pip', 'python']) {
    writeFileSync(join(bin, name), '#!/bin/sh\nexit 0\n')
    chmodSync(join(bin, name), 0o755)
  }
  writeFileSync(join(dest, 'venv', 'SENTINEL'), 'do not rebuild me\n')
}

/** Stand in for the 2 x 63 MB downloaded models: expensive, must survive. */
function makeVoices(dest: string): string {
  const voices = join(dest, 'voices')
  mkdirSync(voices, { recursive: true })
  const model = join(voices, 'hu_HU-imre-medium.onnx')
  writeFileSync(model, 'expensive bytes\n')
  return model
}

describe('install-voice.sh step 2 venv gate', () => {
  beforeAll(() => {
    // python3 with a usable venv module is what step 2 calls; without it these
    // tests would measure the environment, not the gate.
    execFileSync('bash', ['-c', 'python3 -m venv --help'], { stdio: 'ignore' })
  })

  it('rebuilds a venv that exists but has no pip (the 09-21 regression)', () => {
    const dest = mkdtempSync(join(tmpdir(), 'voice-broken-'))
    makeBrokenVenv(dest)
    expect(existsSync(join(dest, 'venv', 'bin', 'python'))).toBe(true)
    expect(existsSync(join(dest, 'venv', 'bin', 'pip'))).toBe(false)

    const r = runStep2(dest)

    expect(r.code).toBe(0)
    // Step 3 calls venv/bin/pip directly; that is the only outcome that counts.
    expect(existsSync(join(dest, 'venv', 'bin', 'pip'))).toBe(true)
    expect(r.out).not.toContain('[SKIP] venv exists')
  })

  it('keeps the downloaded voice models when it rebuilds the venv', () => {
    const dest = mkdtempSync(join(tmpdir(), 'voice-scope-'))
    makeBrokenVenv(dest)
    const model = makeVoices(dest)

    const r = runStep2(dest)

    expect(r.code).toBe(0)
    // Both halves matter. The rebuild must happen (otherwise this assertion is
    // a tautological pass -- the old gate removed nothing, so the model also
    // survived), and it must not reach outside $DEST/venv while doing it.
    expect(existsSync(join(dest, 'venv', 'bin', 'pip'))).toBe(true)
    expect(existsSync(model)).toBe(true)
    expect(readFileSync(model, 'utf-8')).toBe('expensive bytes\n')
  })

  it('leaves a working venv untouched (idempotency is still the point)', () => {
    const dest = mkdtempSync(join(tmpdir(), 'voice-ok-'))
    makeWorkingVenv(dest)

    const r = runStep2(dest)

    expect(r.code).toBe(0)
    expect(r.out).toContain('[SKIP] venv exists')
    // A rebuild would have wiped the directory, sentinel and all.
    expect(existsSync(join(dest, 'venv', 'SENTINEL'))).toBe(true)
  })

  it('rebuilds a venv whose bin/python no longer runs (a python upgrade, 10-19)', () => {
    const dest = mkdtempSync(join(tmpdir(), 'voice-dangling-'))
    const bin = join(dest, 'venv', 'bin')
    mkdirSync(bin, { recursive: true })
    writeFileSync(join(bin, 'pip'), '#!/bin/sh\nexit 0\n')
    chmodSync(join(bin, 'pip'), 0o755)
    symlinkSync(join(dest, 'gone', 'python3.15'), join(bin, 'python'))

    const r = runStep2(dest)

    expect(r.code).toBe(0)
    expect(r.out).toContain('bin/python does not run')
    expect(() => execFileSync(join(bin, 'python'), ['-c', ''])).not.toThrow()
  })

  it('prefers a known-good minor version over the bare python3', () => {
    const dest = mkdtempSync(join(tmpdir(), 'voice-pick-'))
    const fake = mkdtempSync(join(tmpdir(), 'voice-path-'))
    const real = execFileSync('bash', ['-c', 'command -v python3'], { encoding: 'utf-8' }).trim()
    const marker = join(fake, 'used')
    writeFileSync(join(fake, 'python3.14'), `#!/bin/sh\necho "$*" >> ${JSON.stringify(marker)}\nexec ${JSON.stringify(real)} "$@"\n`)
    chmodSync(join(fake, 'python3.14'), 0o755)

    const r = runStep2(dest, { PATH: `${fake}:/usr/bin:/bin` })

    expect(r.code).toBe(0)
    expect(readFileSync(marker, 'utf-8')).toContain(`-m venv ${dest}/venv`)
  })

  it('fails loudly when VOICE_PYTHON is set but unusable', () => {
    const dest = mkdtempSync(join(tmpdir(), 'voice-override-'))

    const r = runStep2(dest, { VOICE_PYTHON: join(dest, 'no-such-python') })

    expect(r.code).not.toBe(0)
    expect(r.out).toContain('no usable python')
    expect(existsSync(join(dest, 'venv'))).toBe(false)
  })

  it('creates the venv when nothing is there yet', () => {
    const dest = mkdtempSync(join(tmpdir(), 'voice-empty-'))

    const r = runStep2(dest)

    expect(r.code).toBe(0)
    expect(existsSync(join(dest, 'venv', 'bin', 'pip'))).toBe(true)
  })
})

const STEP3 = sliceStep(SRC, '# --- Step 3: Python packages ---', '# --- Step 4:')

/**
 * A venv whose python sees stand-in modules, and whose pip records its arguments
 * and "installs" by rewriting the av version: the gate and the pin are what is
 * under test, not PyPI.
 */
function makePackagesVenv(dest: string, avVersion: string): { pipLog: string } {
  const bin = join(dest, 'venv', 'bin')
  const site = join(dest, 'site')
  mkdirSync(bin, { recursive: true })
  mkdirSync(site, { recursive: true })
  writeFileSync(join(site, 'faster_whisper.py'), '')
  writeFileSync(join(site, 'piper.py'), '')
  writeFileSync(join(site, 'av.py'), `__version__ = ${JSON.stringify(avVersion)}\n`)
  const real = execFileSync('bash', ['-c', 'command -v python3'], { encoding: 'utf-8' }).trim()
  // No bytecode: "19.0.1" and "18.1.0" have the same length, so a .pyc written in the
  // same second would pass the mtime+size check and keep the stale version.
  writeFileSync(join(bin, 'python'), `#!/bin/sh\nPYTHONDONTWRITEBYTECODE=1 PYTHONPATH=${JSON.stringify(site)} exec ${JSON.stringify(real)} "$@"\n`)
  const pipLog = join(dest, 'pip.log')
  writeFileSync(join(bin, 'pip'), `#!/bin/sh\necho "$*" >> ${JSON.stringify(pipLog)}\necho '__version__ = "18.1.0"' > ${JSON.stringify(join(site, 'av.py'))}\n`)
  chmodSync(join(bin, 'python'), 0o755)
  chmodSync(join(bin, 'pip'), 0o755)
  return { pipLog }
}

describe('install-voice.sh step 3 av pin', () => {
  it('reinstalls with av<19 when av 19 is present (faster-whisper 1.2.1 TypeError, 10-19)', () => {
    const dest = mkdtempSync(join(tmpdir(), 'voice-av19-'))
    const { pipLog } = makePackagesVenv(dest, '19.0.1')

    const r = runStep(STEP3, dest)

    expect(r.code).toBe(0)
    expect(readFileSync(pipLog, 'utf-8')).toContain('av<19')
    expect(r.out).not.toContain('[SKIP]')
  })

  it('skips when the packages import and av is below 19', () => {
    const dest = mkdtempSync(join(tmpdir(), 'voice-av18-'))
    const { pipLog } = makePackagesVenv(dest, '18.1.0')

    const r = runStep(STEP3, dest)

    expect(r.code).toBe(0)
    expect(r.out).toContain('[SKIP] packages already installed')
    expect(existsSync(pipLog)).toBe(false)
  })
})
