// preCheck over the schedules API (card 248e8f7c, Klodel 47998, 2026-11-19).
//
// The PUT /api/schedules/<name> body may carry a `preCheck`, but ONLY in the form
// {{PROJECT_ROOT}}/scripts/prechecks/<name>.sh, naming an existing regular file
// (not a symlink) whose directory resolves to <root>/scripts/prechecks. Every
// other value is a 400. The route-level half (the write ends the approval, an
// owner save does not approve it) is in schedule-trust.test.ts.

import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, rmSync, readFileSync, realpathSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  validateScheduleUpdate,
  preCheckApiRefusal,
  SCHEDULE_API_PRECHECK_REFUSAL,
} from '../web/schedule-api-fields.js'

const agents = new Set(['marveen', 'kernel'])
const P = (rest: string) => `{{PROJECT_ROOT}}/scripts/prechecks/${rest}`

let root = ''
let outside = ''
beforeAll(() => {
  root = mkdtempSync(join(tmpdir(), 'apiprecheck-root-'))
  outside = mkdtempSync(join(tmpdir(), 'apiprecheck-out-'))
  const pc = join(root, 'scripts', 'prechecks')
  mkdirSync(join(pc, 'sub'), { recursive: true })
  mkdirSync(join(root, 'scripts', 'hooks'), { recursive: true })
  writeFileSync(join(pc, 'ok.sh'), '#!/bin/sh\nexit 0\n')
  writeFileSync(join(pc, 'kernel-quota_precheck2.sh'), '#!/bin/sh\nexit 0\n')
  writeFileSync(join(pc, 'sub', 'deep.sh'), '#!/bin/sh\nexit 0\n')
  writeFileSync(join(pc, 'x.py'), 'print(1)\n')
  // Real files a looser pattern would let through (an unanchored end, a '.' or '/' in the name).
  writeFileSync(join(pc, 'ok.sh.bak'), '#!/bin/sh\nexit 0\n')
  writeFileSync(join(pc, 'ok.shx'), '#!/bin/sh\nexit 0\n')
  writeFileSync(join(pc, 'a.b.sh'), '#!/bin/sh\nexit 0\n')
  writeFileSync(join(root, 'scripts', 'hooks', 'h.sh'), '#!/bin/sh\nexit 0\n')
  mkdirSync(join(pc, 'adir.sh'))
  writeFileSync(join(outside, 'evil.sh'), '#!/bin/sh\nexit 0\n')
  symlinkSync(join(outside, 'evil.sh'), join(pc, 'link.sh'))
  symlinkSync(join(pc, 'ok.sh'), join(pc, 'innerlink.sh'))
})
afterAll(() => {
  rmSync(root, { recursive: true, force: true })
  rmSync(outside, { recursive: true, force: true })
})

describe('preCheckApiRefusal: the one accepted form', () => {
  it('accepts an existing regular .sh file in <root>/scripts/prechecks', () => {
    expect(preCheckApiRefusal(P('ok.sh'), root)).toBeNull()
    expect(preCheckApiRefusal(P('kernel-quota_precheck2.sh'), root)).toBeNull()
  })

  it('accepts the shipped scripts of this repo (the three Kernel heartbeats)', () => {
    const repo = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
    for (const s of ['kernel-quota-precheck.sh', 'kernel-disk-precheck.sh', 'kernel-gitconfig-precheck.sh']) {
      expect(preCheckApiRefusal(P(s), repo), s).toBeNull()
    }
  })

  it('refuses every other path shape', () => {
    for (const v of [
      P('../ok.sh'), P('../../scripts/prechecks/ok.sh'), P('sub/deep.sh'), P('./ok.sh'),
      P('sub/../ok.sh'), P('x/../ok.sh'), P('a.b.sh'), P('ok.shx'),
      join(root, 'scripts', 'prechecks', 'ok.sh'),               // absolute
      'scripts/prechecks/ok.sh', 'ok.sh',                         // relative (beside the SKILL.md)
      '{{INSTALL_DIR}}/scripts/prechecks/ok.sh',
      '{{PROJECT_ROOT}}/scripts/hooks/h.sh',
      '{{PROJECT_ROOT}}/scripts/prechecks//ok.sh',
      P('x.py'), P('ok'), P('ok.sh.bak'), P('.sh'), P('-ok.sh'), P('Ok.sh'), P('OK.SH'),
      P('ok.sh\n'), `${P('ok.sh')} `, ` ${P('ok.sh')}`, P('ok .sh'), P('ok;id.sh'), P('ok$(id).sh'),
      P('ok.sh') + '\u0000', P(`${'a'.repeat(65)}.sh`), '',
    ]) {
      expect(preCheckApiRefusal(v, root), JSON.stringify(v)).toBe(SCHEDULE_API_PRECHECK_REFUSAL)
    }
  })

  it('refuses a value that is not a string', () => {
    for (const v of [5, null, true, {}, [P('ok.sh')], undefined]) {
      expect(preCheckApiRefusal(v, root), JSON.stringify(v)).toBe(SCHEDULE_API_PRECHECK_REFUSAL)
    }
  })

  it('refuses a missing file, a directory, and a symlink (also one pointing inside)', () => {
    expect(preCheckApiRefusal(P('missing.sh'), root)).toBe(SCHEDULE_API_PRECHECK_REFUSAL)
    expect(preCheckApiRefusal(P('adir.sh'), root)).toBe(SCHEDULE_API_PRECHECK_REFUSAL)
    expect(preCheckApiRefusal(P('link.sh'), root)).toBe(SCHEDULE_API_PRECHECK_REFUSAL)
    expect(preCheckApiRefusal(P('innerlink.sh'), root)).toBe(SCHEDULE_API_PRECHECK_REFUSAL)
  })

  it('refuses when scripts/prechecks itself is a symlink out of the root', () => {
    const r2 = mkdtempSync(join(tmpdir(), 'apiprecheck-r2-'))
    try {
      mkdirSync(join(r2, 'scripts'))
      mkdirSync(join(outside, 'pc'), { recursive: true })
      writeFileSync(join(outside, 'pc', 'ok.sh'), '#!/bin/sh\nexit 0\n')
      symlinkSync(join(outside, 'pc'), join(r2, 'scripts', 'prechecks'))
      expect(preCheckApiRefusal(P('ok.sh'), r2)).toBe(SCHEDULE_API_PRECHECK_REFUSAL)
    } finally {
      rmSync(r2, { recursive: true, force: true })
    }
  })

  it('accepts a root that is itself reached through a symlink (realpath on both sides)', () => {
    const viaLink = join(outside, 'rootlink')
    symlinkSync(root, viaLink)
    expect(preCheckApiRefusal(P('ok.sh'), viaLink)).toBeNull()
    expect(realpathSync(viaLink)).toBe(realpathSync(root))
  })

  it('refuses without a root', () => {
    expect(preCheckApiRefusal(P('ok.sh'), undefined)).toBe(SCHEDULE_API_PRECHECK_REFUSAL)
    expect(preCheckApiRefusal(P('ok.sh'), '')).toBe(SCHEDULE_API_PRECHECK_REFUSAL)
  })
})

describe('validateScheduleUpdate with preCheck', () => {
  it('stores the accepted preCheck as given (the runner resolves the placeholder)', () => {
    const v = validateScheduleUpdate({ preCheck: P('ok.sh') }, 'heartbeat', agents, root)
    expect(v).toEqual({ ok: true, update: { preCheck: P('ok.sh') } })
  })

  it('combines with the other editable fields', () => {
    const v = validateScheduleUpdate({ preCheck: P('ok.sh'), enabled: true, schedule: '0 9 * * *' }, 'task', agents, root)
    expect(v).toEqual({ ok: true, update: { preCheck: P('ok.sh'), enabled: true, schedule: '0 9 * * *' } })
  })

  it('a bad preCheck fails the whole update, nothing is partly written', () => {
    const v = validateScheduleUpdate({ preCheck: P('../ok.sh'), prompt: 'p' }, 'task', agents, root)
    expect(v).toEqual({ ok: false, error: SCHEDULE_API_PRECHECK_REFUSAL })
  })

  it('without a root the preCheck is refused (the older 3-argument call)', () => {
    expect(validateScheduleUpdate({ preCheck: P('ok.sh') }, 'task', agents).ok).toBe(false)
  })

  it('preCheck does not open the other installer-only fields', () => {
    for (const field of ['command', 'timeoutMs', 'injectMetrics', 'telegramChatId', 'sendDigestDirect']) {
      const v = validateScheduleUpdate({ preCheck: P('ok.sh'), [field]: 'x' }, 'task', agents, root)
      expect(v.ok, field).toBe(false)
      if (!v.ok) expect(v.error).toContain(field)
    }
  })

  it('a command task stays disable-only, preCheck included', () => {
    expect(validateScheduleUpdate({ preCheck: P('ok.sh') }, 'command', agents, root).ok).toBe(false)
    expect(validateScheduleUpdate({ preCheck: P('ok.sh'), enabled: false }, 'command', agents, root).ok).toBe(false)
  })

  it('the PUT route hands the install root to the validator', () => {
    const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'web', 'routes', 'schedules.ts'), 'utf8')
    const put = src.slice(src.indexOf("scheduleUpdateMatch && method === 'PUT'"))
    const call = put.slice(put.indexOf('validateScheduleUpdate('), put.indexOf('if (!verdict.ok)'))
    expect(call).toMatch(/scheduleAgentIds\(\),\s*PROJECT_ROOT,\s*\)/)
  })
})
