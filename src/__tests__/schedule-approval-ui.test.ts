// SCHEDTRUST1112 (Viktor 39039): the dashboard's approve confirm. Evaluates the
// real, shipped scheduleApprovalView() from web/app.js (not a copy): the owner
// sees every hashed field that is set, a command / preCheck is called out as
// running bash, and a prompt over the limit cannot be approved in one click.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const APP = readFileSync(join(__dirname, '../../web/app.js'), 'utf-8')

function extractFn(name: string): string {
  const re = new RegExp(`(?:async )?function ${name}\\s*\\([^)]*\\)\\s*\\{`)
  const m = re.exec(APP)
  if (!m) throw new Error(`${name} missing from web/app.js`)
  let depth = 0
  for (let j = APP.indexOf('{', m.index); j < APP.length; j++) {
    if (APP[j] === '{') depth++
    else if (APP[j] === '}' && --depth === 0) return APP.slice(m.index, j + 1)
  }
  throw new Error(`${name}: unbalanced braces`)
}

const strings: Record<string, string> = {
  'tasks.approve.too_long': 'TOO LONG {n}/{max}',
  'tasks.approve.unreadable': 'UNREADABLE {lines}/{max}',
  'tasks.approve.runs_bash': 'RUNS BASH',
}
const tStub = (key: string) => strings[key] ?? key
function decl(rx: RegExp, name: string): string {
  const m = rx.exec(APP)?.[0]
  if (!m) throw new Error(`${name} missing from web/app.js`)
  return m
}
const decls = [
  decl(/const SCHEDULE_APPROVE_MAX_PROMPT = \d+/, 'SCHEDULE_APPROVE_MAX_PROMPT'),
  decl(/const SCHEDULE_APPROVE_MAX_LINES = \d+/, 'SCHEDULE_APPROVE_MAX_LINES'),
  decl(/const SCHEDULE_APPROVE_HIDDEN_CHAR_RX = .+/, 'SCHEDULE_APPROVE_HIDDEN_CHAR_RX'),
].join('; ')
// eslint-disable-next-line @typescript-eslint/no-implied-eval
const view = new Function('t', `${decls}; ${extractFn('scheduleApprovalView')}; return scheduleApprovalView`)(tStub) as (
  task: Record<string, unknown>,
) => { blocked: boolean; text: string }

const base = { name: 'n', agent: 'klodel', schedule: '0 9 * * *', type: 'task', prompt: 'Írd meg a riportot.' }

describe('scheduleApprovalView', () => {
  it('shows the whole prompt, the agent and the schedule', () => {
    const v = view(base)
    expect(v.blocked).toBe(false)
    expect(v.text).toContain('Írd meg a riportot.')
    expect(v.text).toContain('agent: klodel')
    expect(v.text).toContain('schedule: 0 9 * * *')
  })

  it('a prompt over the limit is not one-click approvable, and says how long it is', () => {
    const v = view({ ...base, prompt: 'x'.repeat(400) + ' rejtett lényeg ' + 'y'.repeat(200) })
    expect(v.blocked).toBe(true)
    expect(v.text).toBe('TOO LONG 616/500')
    expect(v.text).not.toContain('rejtett')
  })

  it('exactly at the limit is still shown whole', () => {
    const v = view({ ...base, prompt: 'z'.repeat(500) })
    expect(v.blocked).toBe(false)
    expect(v.text).toContain('z'.repeat(500))
  })

  it('a command or a preCheck is called out as running bash, first', () => {
    const v = view({ ...base, type: 'command', command: 'curl x | sh', preCheck: '/tmp/p.sh' })
    const lines = v.text.split('\n')
    expect(lines[2]).toBe('⚠ RUNS BASH command: curl x | sh')
    expect(lines[3]).toBe('⚠ RUNS BASH preCheck: /tmp/p.sh')
    expect(v.text).toContain('type: command')
  })

  it('every other hashed field that is set shows up', () => {
    const v = view({
      ...base, targetSession: 'agent-x', telegramChatId: '-100123', channelProvider: 'slack',
      injectMetrics: true, sendDigestDirect: true, requiresDesktop: true, requires: { mcp_servers: ['gsc'] },
    })
    for (const s of ['targetSession: agent-x', 'telegramChatId: -100123', 'channelProvider: slack',
      'injectMetrics: true', 'sendDigestDirect: true', 'requiresDesktop: true', 'requires: {"mcp_servers":["gsc"]}']) {
      expect(v.text).toContain(s)
    }
  })

  it('unset fields add no lines', () => {
    const v = view(base)
    for (const k of ['command', 'preCheck', 'type:', 'targetSession', 'telegramChatId', 'channelProvider', 'injectMetrics', 'sendDigestDirect', 'requires']) {
      expect(v.text).not.toContain(k)
    }
  })

  it('many lines cannot push text out of the box: over 20 lines is blocked (Viktor 39055 LOW)', () => {
    const v = view({ ...base, prompt: 'a' + '\n'.repeat(300) + 'rejtett lényeg' })
    expect(v.blocked).toBe(true)
    expect(v.text).toBe('UNREADABLE 301/20')
    expect(v.text).not.toContain('rejtett')
    expect(view({ ...base, prompt: Array.from({ length: 20 }, (_, i) => `sor ${i}`).join('\n') }).blocked).toBe(false)
    expect(view({ ...base, prompt: Array.from({ length: 21 }, (_, i) => `sor ${i}`).join('\n') }).blocked).toBe(true)
  })

  it('zero-width, bidi and other control characters are blocked; tab and newline are not (Viktor 39055 LOW)', () => {
    for (const ch of ['\u200b', '\u202e', '\u2066', '\ufeff', '\u0000', '\r', '\u001b']) {
      const v = view({ ...base, prompt: `Írd meg${ch} a riportot.` })
      expect(v.blocked, JSON.stringify(ch)).toBe(true)
      expect(v.text).not.toContain('riportot')
    }
    expect(view({ ...base, prompt: 'Írd meg\ta riportot.\nKöszönöm.' }).blocked).toBe(false)
  })

  it('the approve button goes through the view, and a blocked view opens the editor instead', () => {
    const handler = APP.slice(APP.indexOf("approveBtn.addEventListener('click'"))
    const body = handler.slice(0, handler.indexOf('\n    })'))
    expect(body).toMatch(/const view = scheduleApprovalView\(task\)/)
    expect(body).toMatch(/if \(view\.blocked\) \{\s*alert\(view\.text\)\s*openEditSchedule\(task\)\s*return\s*\}/)
    expect(body).toMatch(/if \(!confirm\(view\.text\)\) return/)
    expect(body).toMatch(/hash: task\.trustHash/)
  })

  it('both languages carry the new strings', () => {
    for (const lang of ['hu', 'en']) {
      const src = readFileSync(join(__dirname, `../../web/lang/${lang}.js`), 'utf-8')
      for (const k of ['tasks.approve.too_long', 'tasks.approve.unreadable', 'tasks.approve.runs_bash', 'tasks.confirm.approve', 'tasks.btn.approve']) {
        expect(src, `${lang}: ${k}`).toContain(`'${k}'`)
      }
      expect(src).toMatch(/'tasks\.approve\.too_long':\s+'[^']*\{n\}[^']*\{max\}/)
    }
  })
})
