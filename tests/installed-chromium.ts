// PWREV1110 (Dave 35824, card 3f36ae31): this checkout's @playwright/test wants one exact
// chromium-headless-shell revision (node_modules/playwright-core/browsers.json). On the owner's
// machine the shared cache holds other revisions only, so every default launch stopped with
// "Executable doesn't exist ... chromium_headless_shell-<rev>" and both suites were red before
// a single test ran. The fix picks, in this order:
//   1. CHROMIUM_BIN, when set (an explicit choice always wins);
//   2. nothing (Playwright's own default), when the wanted revision IS installed -- CI and a
//      fresh `npx playwright install` land here, so nothing changes for them;
//   3. the newest chromium-headless-shell already in the cache, rather than downloading another
//      ~100 MB copy onto the owner's machine.
// Measured 2026-11-10 (heavy-job run 20261110-114145-pw-bv): browser-verify with the default
// launch 3 failed; with the installed 1248 headless shell 3 passed.
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { createRequire } from 'node:module'

function cacheDir(): string {
  if (process.env.PLAYWRIGHT_BROWSERS_PATH) return process.env.PLAYWRIGHT_BROWSERS_PATH
  return process.platform === 'darwin'
    ? join(homedir(), 'Library', 'Caches', 'ms-playwright')
    : join(homedir(), '.cache', 'ms-playwright')
}

function wantedRevision(): string | undefined {
  try {
    const req = createRequire(join(process.cwd(), 'package.json'))
    // browsers.json is not in playwright-core's exports map; package.json is
    const file = join(dirname(req.resolve('playwright-core/package.json')), 'browsers.json')
    const browsers = JSON.parse(readFileSync(file, 'utf-8')).browsers as { name: string; revision: string }[]
    return browsers.find((b) => b.name === 'chromium-headless-shell')?.revision
  } catch {
    return undefined
  }
}

export function installedChromium(): string | undefined {
  if (process.env.CHROMIUM_BIN) return process.env.CHROMIUM_BIN
  const dir = cacheDir()
  const wanted = wantedRevision()
  if (!wanted || existsSync(join(dir, `chromium_headless_shell-${wanted}`))) return undefined
  let names: string[]
  try {
    names = readdirSync(dir)
  } catch {
    return undefined
  }
  const revs = names
    .map((n) => /^chromium_headless_shell-(\d+)$/.exec(n))
    .filter((m): m is RegExpExecArray => m !== null)
    .map((m) => Number(m[1]))
    .sort((a, b) => b - a)
  for (const rev of revs) {
    const root = join(dir, `chromium_headless_shell-${rev}`)
    if (!existsSync(join(root, 'INSTALLATION_COMPLETE'))) continue
    const sub = readdirSync(root).find((n) => n.startsWith('chrome-headless-shell-'))
    const exe = sub && join(root, sub, process.platform === 'win32' ? 'chrome-headless-shell.exe' : 'chrome-headless-shell')
    if (exe && existsSync(exe)) return exe
  }
  return undefined
}
