// LAUNCHDPIN1111 (Klodel 37298, Pulzus 37294): the launchd jobs the self-pace gate lets Pulzus bootstrap run
// repo scripts, and Viktor approves those scripts by sha256 at bootstrap (Viktor 25470/25476: the mem-relief
// scripts are "pinned at bootstrap"). That pin lived OUTSIDE the repo (agents/kernel/out/mem-relief-pins-*.txt),
// so nothing noticed when #150, #170 and #173 changed scripts/agent-msg.sh: on 2026-11-11 the pre-bootstrap
// check found the stale hash and com.marveen.mem-relief stayed down from 07:17 -- the outage found the drift.
//
// The pins now live in scripts/launchd-pins/<label>.sha256 (shasum format, repo-relative paths), and this test
// recomputes them: a PR that changes a pinned script without updating the pin goes red in CI, so the pin bump
// (and Viktor's HASH-OK on it) happens in the same PR. Pulzus checks before a bootstrap, from the repo root:
//   shasum -a 256 -c scripts/launchd-pins/com.marveen.mem-relief.sha256
// The plist itself is host-specific and stays pinned in scripts/self-pace-gate.mjs
// (LAUNCHD_APPROVED_PLIST_SHA256).
import { describe, it, expect } from 'vitest'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const PIN_DIR = join(ROOT, 'scripts', 'launchd-pins')
const LINE_RX = /^([0-9a-f]{64}) {2}(\S+)$/

function readPins(file: string): { sha: string, path: string }[] {
  return readFileSync(join(PIN_DIR, file), 'utf8')
    .split('\n')
    .filter((l) => l.trim() !== '')
    .map((l) => {
      const m = LINE_RX.exec(l)
      if (!m) throw new Error(`${file}: not a "<sha256>  <path>" line: ${JSON.stringify(l)}`)
      return { sha: m[1], path: m[2] }
    })
}

const sha256 = (rel: string) => createHash('sha256').update(readFileSync(join(ROOT, rel))).digest('hex')

// The repo files a pinned file runs or imports, as the shapes the pinned scripts use:
//   shell: "$HERE/<file>" (HERE = the script's dir) and "$BASE/scripts/<path>" (BASE = the repo root);
//   python: a top-level `import x` / `from x import ...` that names a sibling x.py.
function depsOf(rel: string): string[] {
  const src = readFileSync(join(ROOT, rel), 'utf8')
  const dir = dirname(rel)
  const out = new Set<string>()
  if (rel.endsWith('.sh')) {
    for (const m of src.matchAll(/\$\{?HERE\}?\/([A-Za-z0-9_.\/-]+\.(?:sh|py|mjs))/g)) out.add(join(dir, m[1]))
    for (const m of src.matchAll(/\$\{?BASE\}?\/(scripts\/[A-Za-z0-9_.\/-]+\.(?:sh|py|mjs))/g)) out.add(m[1])
  } else if (rel.endsWith('.py')) {
    for (const m of src.matchAll(/^(?:from\s+([A-Za-z_][A-Za-z0-9_]*)\s+import|import\s+([A-Za-z_][A-Za-z0-9_]*))/gm)) {
      const sib = join(dir, `${m[1] ?? m[2]}.py`)
      if (existsSync(join(ROOT, sib))) out.add(sib)
    }
  }
  return [...out].filter((p) => existsSync(join(ROOT, p))).sort()
}

const pinFiles = existsSync(PIN_DIR) ? readdirSync(PIN_DIR).filter((f) => f.endsWith('.sha256')).sort() : []

describe('launchd script pins (LAUNCHDPIN1111)', () => {
  it('finds the pin files (a rename must not silently empty this check)', () => {
    expect(pinFiles).toContain('com.marveen.mem-relief.sha256')
  })

  for (const file of pinFiles) {
    describe(file, () => {
      const pins = readPins(file)

      it('pins repo-relative files that exist (no absolute or host path, no ..)', () => {
        expect(pins.length).toBeGreaterThan(0)
        for (const { path } of pins) {
          expect(path.startsWith('/') || path.includes('..'), `${file}: ${path}`).toBe(false)
          expect(existsSync(join(ROOT, path)), `${file}: ${path} does not exist`).toBe(true)
        }
      })

      it('every pinned file still has its pinned sha256', () => {
        const stale = pins
          .map(({ sha, path }) => ({ path, pinned: sha, now: sha256(path) }))
          .filter((p) => p.pinned !== p.now)
        expect(
          stale,
          `pinned launchd scripts changed: ${stale.map((s) => `${s.path} ${s.pinned.slice(0, 12)} -> ${s.now.slice(0, 12)}`).join(', ')} -- ` +
            `update scripts/launchd-pins/${file} in this PR and get Viktor's HASH-OK on the new line: ` +
            'the job is bootstrapped only against this pin',
        ).toEqual([])
      })
    })
  }

  // A pin is only as good as its closure: a pinned script that runs or imports an unpinned repo file can be
  // changed through that file while every pinned hash still matches (Viktor 37300/37303: agent-msg.sh runs
  // scripts/lib/msg_gate.py and homoglyph.py, and homoglyph.py imports mixed_script.py).
  it('every pin is closed: what a pinned file runs or imports from the repo is pinned too', () => {
    expect(depsOf('scripts/agent-msg.sh')).toEqual(
      expect.arrayContaining(['scripts/lib/msg_gate.py', 'scripts/lib/homoglyph.py']),
    )
    expect(depsOf('scripts/lib/homoglyph.py')).toContain('scripts/lib/mixed_script.py')
    for (const file of pinFiles) {
      const pinned = new Set(readPins(file).map((p) => p.path))
      const missing = [...pinned].flatMap((p) => depsOf(p).filter((d) => !pinned.has(d)).map((d) => `${p} -> ${d}`))
      expect(missing, `${file}: pinned files depend on unpinned repo files: ${missing.join(', ')}`).toEqual([])
    }
  })

  it('the instrument is live: a changed byte in a pinned file changes its sha256', () => {
    const { path } = readPins('com.marveen.mem-relief.sha256')[0]
    const buf = readFileSync(join(ROOT, path))
    const flipped = Buffer.from(buf)
    flipped[0] ^= 1
    expect(createHash('sha256').update(flipped).digest('hex')).not.toBe(sha256(path))
  })
})
