// Card 7b2f784f follow-up (measured 2026-11-20, the e2e of #406): the deployed
// hex-id-source-gate.py printed `SyntaxWarning: "\s" is an invalid escape
// sequence` on every run (a non-raw piece of a concatenated regex). Today it is a
// warning; with warnings as errors it is a SyntaxError at compile time, which no
// try/except in the hook can catch, so a future Python would turn the gate into a
// silent exit 1. Every Python hook must compile with SyntaxWarning as an error.
// Before Python 3.12 the same invalid escape is a DeprecationWarning (Viktor 48990, measured on 3.9.6), so that is
// an error here too: on an older python3 the test would otherwise pass without checking anything.
import { describe, it, expect } from 'vitest'
import { spawnSync } from 'node:child_process'
import { readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const hooksDir = join(here, '..', '..', 'scripts', 'hooks')

const COMPILE_ALL = [
  'import sys, warnings',
  "warnings.simplefilter('error', SyntaxWarning)",
  "warnings.simplefilter('error', DeprecationWarning)",
  'bad = []',
  'for p in sys.argv[1:]:',
  '    try:',
  "        compile(open(p, encoding='utf-8').read(), p, 'exec')",
  '    except SyntaxError as e:',
  "        bad.append(p.rsplit('/', 1)[-1] + ': ' + str(e.msg))",
  "print('\\n'.join(bad))",
].join('\n')

describe('every Python hook compiles with SyntaxWarning as an error', () => {
  it('no invalid escape sequence (or other SyntaxWarning) in scripts/hooks/*.py', () => {
    const files = readdirSync(hooksDir).filter((f) => f.endsWith('.py')).map((f) => join(hooksDir, f))
    expect(files.length).toBeGreaterThan(50)
    const r = spawnSync('python3', ['-I', '-c', COMPILE_ALL, ...files], { encoding: 'utf-8' })
    expect(r.status, r.stderr).toBe(0)
    expect(r.stdout.trim()).toBe('')
  })
})
