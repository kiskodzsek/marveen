// SCHEDTRUST1112 (card 6544de50; Viktor 38943 #4 and 38996; Klodel 39006):
// which scheduled tasks reach their agent with the OWNER framing.
//
// The problem: every agent holds the one shared dashboard token, and the
// runner handed EVERY task to its agent under SCHEDULED_TASK_PREAMBLE
// ("authored by the operator ... EXPECTED TO CARRY OUT"). So a prompt-injected
// agent could schedule an owner-grade instruction for any agent, the main one
// included, through POST/PUT /api/schedules -- or by editing a SKILL.md.
//
// The rule:
//   - A task runs with the owner framing ONLY while it has a trust row
//     (db.ts schedule_trust) whose hash equals the hash of its CURRENT stored
//     definition. Everything else -- no row, an unreadable row, a mismatch, a
//     lookup error -- runs with AGENT_SCHEDULED_TASK_PREAMBLE (fail-closed).
//   - Rows are written by the server only: the owner's browser session
//     (create/edit/approve in the dashboard), the install's own code (seeded
//     defaults, the rotation heartbeat), and the one-time legacy baseline. No
//     request body field reaches this table, and X-Agent-Id is a label only.
//   - A token-authenticated create or edit drops the row (expected path, no
//     alarm). A row whose hash no longer matches means the definition changed
//     behind the API (a file edit): agent framing PLUS an alert to the main
//     agent, once per changed definition.
//   - The runner executes no bash for an untrusted task: a command task is not
//     run, a preCheck is not run (its stdout would land in the task body).
//
// The legacy baseline runs once (db.ts schedule_trust_baseline). Deleting a
// trust ROW only lowers trust; deleting the BASELINE row and restarting would
// re-baseline every task at its current hash -- the same capability as writing
// the table directly, i.e. the residual below, not a new door (Viktor 39032 #5).
//
// Residual, stated (Klodel 39006: "ismert maradék kockázat, zárja: bubek 2e"):
// an agent runs under the same Unix user as the dashboard, so it can rewrite a
// task AND its trust row together (the hash is not a secret; an HMAC key would
// be just as readable). The hash stops the realistic case -- an agent that
// edits the task files without knowing about this table -- not a determined
// one. Only a separate OS user for the dashboard closes that.
//
// PRECHECKTRUST1114 (Viktor 42462 MEDIUM, Klodel 42464/42469): the preCheck
// path in the definition is not enough. Most preCheck scripts live in ops/,
// which is GITIGNORED (.gitignore "/ops/"): no PR path, no history, and any
// agent can rewrite one without touching the task definition -- a silent,
// lasting channel into an owner-framed prompt. So the CONTENT of the preCheck
// and of the files it directly calls is pinned at approval, in its own column
// (preCheckContentHash; the definition hash is unchanged), and a changed file
// is a mismatch like a changed definition (Viktor 42472).
// - The walk follows literal references: a .py / .sh word, a shell
//   interpreter's operand (after the dirname idiom and a literal cd), every
//   python import name (stdlib included: X.py and X/__init__.py beside the
//   script and on a literal sys.path dir; a missing candidate is ABSENT, so a
//   shadowing json.py planted later moves the hash), literal importlib /
//   spec_from_file_location / run_path paths, subprocess list literals.
// - What it cannot follow is BLOCKING, never silently skipped: a computed
//   import / exec / eval / sys.path / subprocess command / interpreter operand
//   / cd is UNRESOLVED; a missing or unreadable file, a non-UTF-8 script, a
//   file over 2 MB or more than 32 files is MISSING / UNREADABLE /
//   UNPARSEABLE / TOOBIG / LIMIT. Such a task is never trusted and cannot be
//   approved until the script is fixed.
// - NOT covered, by design: what is not a file the walk can name (tmux, git,
//   binaries on PATH, store/ data files, the network), and a path the script
//   already computed at approval in a way this walk does not recognise as
//   computed. The hash -> exec window (ms) is an accepted residual (same Unix
//   user, above). .pyc: an importer can load a planted __pycache__ .pyc instead
//   of the hashed source; the wrappers run python3 -I -X pycache_prefix=...
//   (Viktor 42472 RES1/RES2) so no cached bytecode and no user site is read.

import { createHash } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { lstatSync, readFileSync, realpathSync, statSync } from 'node:fs'
import { dirname, isAbsolute, join, normalize, relative, sep } from 'node:path'
import {
  getScheduleTrust, setScheduleTrust, deleteScheduleTrust, baselineScheduleTrust, createSystemMessage,
  pinScheduleTrustPreChecks, repinScheduleTrustPreCheck, type ScheduleTrustRow,
} from '../db.js'
import { MAIN_AGENT_ID, PROJECT_ROOT } from '../config.js'
import { resolvePreCheckPath } from './precheck-path.js'
import { PRECHECK_PIN_EXPECTED } from './schedule-trust-precheck-pins.js'
import { logger } from '../logger.js'
import type { ScheduledTask } from './scheduled-tasks-io.js'

/** approved/legacy run with the owner framing; agent/mismatch do not. */
export type ScheduleTrustStatus = 'approved' | 'legacy' | 'agent' | 'mismatch'

/**
 * The hash is DENY-LIST based (Viktor 39032 #1): EVERY field of the stored
 * definition counts -- prompt (the SKILL.md body), type, command, preCheck,
 * agent, targetSession, telegramChatId, channelProvider, injectMetrics,
 * sendDigestDirect, requires, ... and any field added later -- EXCEPT the ones
 * below, which only say WHEN or WHETHER a task runs, or how it is labelled.
 * They are exactly what a token PUT may change while keeping the approval
 * (schedule-api-fields.ts), plus the store's own bookkeeping.
 */
export const SCHEDULE_TRUST_UNHASHED_FIELDS: ReadonlySet<string> = new Set([
  'name', 'description', 'schedule', 'enabled', 'createdAt', 'skipIfBusy', 'forceSend',
  'catchUpMaxAgeMinutes', 'stuckAfterMinutes', 'runAt',
])

/**
 * The hashed fields the dashboard EDITOR shows and lets the owner set
 * (openEditSchedule in web/app.js: prompt, agent, type task/heartbeat,
 * targetSession). An owner save from the editor approves the task as stored
 * ONLY when no other hashed field is set (Viktor 39055 A): the editor does not
 * show a command, a preCheck, a telegramChatId, ..., so saving must not approve
 * one the owner never saw. Kept next to SCHEDULE_TRUST_UNHASHED_FIELDS so the
 * two lists cannot drift: "hidden" is everything hashed that is not listed
 * here, so a field added later is hidden until the editor shows it.
 */
export const SCHEDULE_EDITOR_SHOWN_FIELDS: ReadonlySet<string> = new Set(['prompt', 'agent', 'type', 'targetSession'])
const SCHEDULE_EDITOR_TYPES: ReadonlySet<string> = new Set(['task', 'heartbeat'])

/**
 * The hashed fields of a stored task the editor does not show, that are set
 * (anything but undefined / null / false -- readScheduledTask turns an absent
 * flag into false), plus "type" when it is not one the editor offers. Empty =
 * an owner editor save may approve the task. Sorted, for the log line.
 */
export function scheduleEditorHiddenFields(task: ScheduleTrustFields): string[] {
  const hidden: string[] = []
  for (const [k, v] of Object.entries(task)) {
    if (SCHEDULE_TRUST_UNHASHED_FIELDS.has(k) || SCHEDULE_EDITOR_SHOWN_FIELDS.has(k)) continue
    if (v === undefined || v === null || v === false) continue
    hidden.push(k)
  }
  if (!SCHEDULE_EDITOR_TYPES.has(String(task.type ?? 'task'))) hidden.push('type')
  return hidden.sort()
}

export type ScheduleTrustFields = Pick<ScheduledTask, 'prompt' | 'agent'> & Partial<Omit<ScheduledTask, 'prompt' | 'agent'>>

const HASH_RX = /^[0-9a-f]{64}$/

// Key-sorted, undefined-free JSON, so the hash does not depend on the order
// the fields were written in, nor on an absent-vs-undefined difference.
function canonical(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(canonical)
  if (v && typeof v === 'object') {
    const out: Record<string, unknown> = {}
    for (const k of Object.keys(v as Record<string, unknown>).sort()) {
      const x = (v as Record<string, unknown>)[k]
      if (x !== undefined) out[k] = canonical(x)
    }
    return out
  }
  return v
}

export function scheduleTrustHash(task: ScheduleTrustFields): string {
  const kept: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(task)) {
    if (!SCHEDULE_TRUST_UNHASHED_FIELDS.has(k)) kept[k] = v
  }
  // The defaults readScheduledTask applies, so a task built in code and the
  // same task read back from disk hash alike.
  kept.prompt = String(task.prompt ?? '')
  kept.agent = String(task.agent ?? '')
  kept.type = task.type ?? 'task'
  return createHash('sha256').update(JSON.stringify(['v2', canonical(kept)]), 'utf8').digest('hex')
}

/** Walk limits (Viktor 42472 b1): reaching either is a BLOCKING marker, never a silent cut. */
export const PRECHECK_WALK_MAX_FILES = 32
export const PRECHECK_WALK_MAX_BYTES = 2 * 1024 * 1024

/**
 * Digest markers (Viktor 42472 b1). A blocking marker makes the task
 * untrusted whatever its row says: the preCheck does not run, and the owner
 * cannot approve the task until the script is fixed. Two markers only record:
 * ABSENT (a file python would load, or a relative path the script names, that
 * does not exist: it appearing later moves the hash) and LINK (a symlink hop).
 */
export const PRECHECK_BLOCKING_MARKERS: ReadonlySet<string> = new Set(['LIMIT', 'TOOBIG', 'UNPARSEABLE', 'UNREADABLE', 'MISSING', 'NOTFILE', 'UNRESOLVED'])

// `$(dirname "$0")`, `"$(dirname "$0")"`, `$(dirname "${BASH_SOURCE[0]}")` -> the script's directory.
const SH_DIRNAME_RX = /"?\$\(\s*dirname\s+"?\$(?:0|\{0\}|BASH_SOURCE(?:\[0\])?|\{BASH_SOURCE(?:\[0\])?\})"?\s*\)"?/g
// A path-like word ending in .py or .sh (an interpreter target, a source, an importlib / subprocess literal).
const CODE_PATH_RX = /[A-Za-z0-9_.\/~-]*[A-Za-z0-9_-]\.(?:py|sh)(?![A-Za-z0-9_])/g
const PY_FROM_IMPORT_RX = /^[ \t]*from[ \t]+([A-Za-z_][\w.]*)[ \t]+import[ \t]+\(?([^#\n;)]*)/gm
const PY_IMPORT_RX = /^[ \t]*import[ \t]+([^#\n;]+)/gm
// sys.path growth: a literal absolute dir is followed; the script's own dir (the
// dirname(abspath(__file__)) idiom) is already a candidate dir; anything else is UNRESOLVED.
const PY_SYSPATH_RX = /sys\.path\s*(?:\.\s*(insert|append|extend)\s*\(|\[[^\]]*\]\s*=|\+=|=(?!=))/g
const PY_SCRIPT_DIR_EXPR_RX = /^\s*os\.path\.dirname\(\s*(?:os\.path\.(?:abspath|realpath)\(\s*__file__\s*\)|__file__)\s*\)\s*\)/
// A string literal argument (not an f-string): r'..', b"..", '..'.
const PY_LITERAL_ARG_RX = /^\s*(?:[rRbBuU]{0,2})(['"])([^'"\n]*)\1\s*[,)]/
const PY_DYNAMIC_RX = /(?<![\w.])(exec|eval|compile|__import__)\s*\(|\b(import_module|run_path|run_module)\s*\(|\bspec_from_file_location\s*\(|\bos\s*\.\s*(system|popen|exec\w*|spawn\w*|posix_spawn\w*)\s*\(|\bpty\s*\.\s*spawn\s*\(|\bshell\s*=\s*True\b|\bsubprocess\s*\.\s*(run|Popen|call|check_call|check_output|getoutput|getstatusoutput)\s*\(/g
const INTERP_WORD = String.raw`(?:[\w./-]*\/)?(?:python[\d.]*|bash|sh|zsh|dash|ksh|node|perl|ruby|osascript)`
const PY_INTERP_LITERAL_RX = new RegExp(String.raw`^[rRuU]?(['"])${INTERP_WORD}\1$`)
const SH_INTERP_RX = new RegExp(String.raw`^${INTERP_WORD}$`)
const SH_KEYWORDS: ReadonlySet<string> = new Set(['if', 'then', 'else', 'elif', 'do', 'while', 'until', '!', 'exec', 'command', 'nohup', 'time', 'env', '{', 'builtin'])

export interface PreCheckRefs {
  /** Files the script RUNS or IMPORTS: read, hashed and walked in turn (a missing one is MISSING, blocking). */
  refs: string[]
  /** Files the script only NAMES (a .py / .sh word): read and hashed, not walked (a missing one is ABSENT). */
  mentions: string[]
  /** Candidates that do not exist (ABSENT, recorded only). */
  absent: string[]
  /** Constructs the walk cannot follow (UNRESOLVED, blocking): `kind@line`. */
  unresolved: string[]
}

/** The text up to the parenthesis that closes the call opened just before `from` (strings not parsed; enough for argument lists). */
function callArgs(text: string, from: number): string {
  let depth = 1
  for (let i = from; i < text.length && i < from + 2000; i++) {
    const c = text[i]
    if (c === '(' || c === '[' || c === '{') depth++
    else if (c === ')' || c === ']' || c === '}') { depth--; if (depth === 0) return text.slice(from, i + 1) }
  }
  return text.slice(from, from + 2000)
}

/** The elements of a list literal at the start of `args` ('[a, b]'), or null when the first argument is not a list literal. */
function listLiteralElements(args: string): string[] | null {
  const m = /^\s*\[/.exec(args)
  if (!m) return null
  const inner = callArgs(args, m[0].length)
  return inner.slice(0, -1).split(',').map(s => s.trim()).filter(s => s.length > 0)
}

function lineOf(text: string, index: number): number {
  let n = 1
  for (let i = 0; i < index; i++) if (text.charCodeAt(i) === 10) n++
  return n
}

function pyModuleCandidates(dirs: Iterable<string>, dotted: string, fromNames: string[]): string[] {
  const parts = dotted.split('.').filter(Boolean)
  const out: string[] = []
  for (const d of dirs) {
    out.push(join(d, parts[0] + '.py'), join(d, parts[0], '__init__.py'))
    // Deeper names only under a package directory that exists (no candidate explosion for the stdlib).
    if (!dirExists(join(d, parts[0]))) continue
    for (let i = 2; i <= parts.length; i++) {
      const p = join(d, ...parts.slice(0, i))
      out.push(p + '.py', join(p, '__init__.py'))
    }
    const pkg = join(d, ...parts)
    if (dirExists(pkg)) for (const n of fromNames) out.push(join(pkg, n + '.py'), join(pkg, n, '__init__.py'))
  }
  return out
}

function pyReferences(file: string, text: string, out: PreCheckRefs, add: (p: string) => void, bases: string[]): void {
  const dir = dirname(file)
  const dirs = new Set<string>([dir])
  for (const m of text.matchAll(PY_SYSPATH_RX)) {
    // Only insert(<int>, X) and append(X) with X a literal absolute dir or the script-dir idiom are followed.
    let rest: string | null = null
    const at = (m.index ?? 0) + m[0].length
    if (m[1] === 'append') rest = text.slice(at)
    else if (m[1] === 'insert') {
      const idx = /^\s*-?\d+\s*,/.exec(text.slice(at))
      if (idx) rest = text.slice(at + idx[0].length)
    }
    const l = rest === null ? null : PY_LITERAL_ARG_RX.exec(rest)
    if (l && isAbsolute(l[2])) dirs.add(l[2])
    else if (rest !== null && PY_SCRIPT_DIR_EXPR_RX.test(rest)) { /* the script's own dir: already a candidate */ }
    else out.unresolved.push(`sys.path@${lineOf(text, m.index ?? 0)}`)
  }
  const mods: Array<[string, string[]]> = []
  for (const m of text.matchAll(PY_FROM_IMPORT_RX)) {
    if (m[1].startsWith('.')) continue
    mods.push([m[1], m[2].split(',').map(s => s.trim().split(/\s+/)[0]).filter(s => /^[A-Za-z_]\w*$/.test(s))])
  }
  for (const m of text.matchAll(PY_IMPORT_RX)) {
    for (const part of m[1].split(',')) {
      const name = part.trim().split(/\s+/)[0]
      if (/^[A-Za-z_][\w.]*$/.test(name)) mods.push([name, []])
    }
  }
  for (const m of text.matchAll(PY_DYNAMIC_RX)) {
    const at = (m.index ?? 0) + m[0].length
    const where = `@${lineOf(text, m.index ?? 0)}`
    const args = text.slice(at)
    if (m[1] || m[2]) {
      // exec / eval / compile / __import__ / import_module / run_path / run_module: only a string literal is followed.
      const kind = m[1] ?? m[2]
      const l = PY_LITERAL_ARG_RX.exec(args)
      if (!l) { out.unresolved.push(kind + where); continue }
      if (kind === '__import__' || kind === 'import_module' || kind === 'run_module') mods.push([l[2], []])
      else if (kind === 'run_path') add(isAbsolute(l[2]) ? l[2] : join(dir, l[2]))
      // exec('literal') / eval('literal'): the code is in this (hashed) file.
    } else if (m[0].includes('spec_from_file_location')) {
      const l = /^\s*(?:[rRuU]?(['"])[^'"\n]*\1|[\w.]+)\s*,\s*[rRuU]?(['"])([^'"\n]+)\2\s*[,)]/.exec(args)
      if (l && isAbsolute(l[3])) add(l[3])
      else out.unresolved.push('spec_from_file_location' + where)
    } else if (m[3] || /pty/.test(m[0])) {
      out.unresolved.push(`os.${m[3] ?? 'pty'}` + where)
    } else if (/shell/.test(m[0])) {
      out.unresolved.push('shell=True' + where)
    } else {
      // subprocess: a list literal of string literals is followed by CODE_PATH_RX; a computed
      // command, or an interpreter with a computed argument, is not.
      const els = listLiteralElements(args)
      if (els === null) { out.unresolved.push(`subprocess.${m[4]}` + where); continue }
      const interp = els.some(e => PY_INTERP_LITERAL_RX.test(e) || /\bsys\.executable\b/.test(e))
      if (interp && els.some(e => !/^[rRuU]?(['"])[^'"\n]*\1$/.test(e) && !/^sys\.executable$/.test(e))) { out.unresolved.push(`subprocess.${m[4]}` + where); continue }
      // A path-like literal in the command list is what runs (the command itself, or the interpreter's script).
      for (const e of els) {
        const lit = /^[rRuU]?(['"])([^'"\n]*)\1$/.exec(e)
        if (!lit || !(lit[2].includes('/') || /\.(?:py|sh)$/.test(lit[2])) || lit[2].startsWith('-')) continue
        if (isAbsolute(lit[2])) { add(lit[2]); continue }
        const hit = bases.map(b => join(b, lit[2])).find(fileExists)
        add(hit ?? join(bases[0], lit[2]))
      }
    }
  }
  // Every imported name, stdlib included (Viktor 42472 b2): a module planted on a
  // searched dir shadows the stdlib, so its candidate path is part of the hash.
  for (const [mod, names] of mods) for (const cand of pyModuleCandidates(dirs, mod, names)) {
    if (fileExists(cand)) out.refs.push(cand)
    else out.absent.push(cand)
  }
}

/** Shell: the words after the dirname idiom is replaced, split at command boundaries. */
function shReferences(file: string, body: string, out: PreCheckRefs, bases: string[], add: (p: string) => void): void {
  const lines = body.split('\n')
  lines.forEach((raw, i) => {
    if (/^\s*#/.test(raw)) return
    const where = `@${i + 1}`
    for (const seg of raw.split(/;|&&|\|\||\||\$\(|`|\(|\)/)) {
      const words = seg.trim().split(/\s+/).filter(Boolean)
      while (words.length > 0 && (SH_KEYWORDS.has(words[0]) || /^[A-Za-z_]\w*=/.test(words[0]))) words.shift()
      if (words.length === 0) continue
      const unq = (w: string) => w.replace(/^["']|["']$/g, '')
      const cmd = unq(words[0])
      if (/[$`]/.test(cmd)) { out.unresolved.push('command' + where); continue }
      if (cmd === 'eval') { out.unresolved.push('eval' + where); continue }
      if (cmd === 'cd') {
        const target = words[1] === undefined ? '' : unq(words[1])
        if (/[$`~]/.test(target) || target === '' || target === '-') { out.unresolved.push('cd' + where); continue }
        bases.unshift(isAbsolute(target) ? normalize(target) : normalize(join(dirname(file), target)))
        continue
      }
      const isSource = cmd === 'source' || cmd === '.'
      if (!isSource && !SH_INTERP_RX.test(cmd)) {
        // `./tool`, `/abs/tool.py`: a path as the command word runs that file.
        if (cmd.includes('/')) {
          if (isAbsolute(cmd)) add(cmd)
          else add(bases.map(b => join(b, cmd)).find(fileExists) ?? join(bases[0], cmd))
        }
        continue
      }
      // The interpreter's operand: flags skipped (-X / -W take a value), -c is inline code (in this file).
      let j = 1
      let operand: string | null = null
      while (j < words.length) {
        const w = unq(words[j])
        if (w === '-c') { operand = null; j = words.length; break }
        if (w === '-m') { out.unresolved.push('interpreter -m' + where); operand = null; j = words.length; break }
        if (/^-[XWO]$/.test(w) && !isSource) { j += 2; continue }
        if (w.startsWith('-') && w !== '-') { j++; continue }
        operand = w
        break
      }
      if (operand === null || operand === '-' || operand.startsWith('<') || /^\d*>/.test(operand)) continue
      if (/[$`~*?]/.test(operand)) { out.unresolved.push('interpreter argument' + where); continue }
      if (isAbsolute(operand)) { add(operand); continue }
      const hit = bases.map(b => join(b, operand as string)).find(fileExists)
      add(hit ?? join(bases[0], operand))
    }
  })
}

/** The files one script refers to: what to read next, what is absent, what cannot be followed. */
export function preCheckReferences(file: string, text: string, root: string = PROJECT_ROOT): PreCheckRefs {
  const dir = dirname(file)
  const out: PreCheckRefs = { refs: [], mentions: [], absent: [], unresolved: [] }
  const isPy = file.endsWith('.py') || (!file.endsWith('.sh') && /^#!.*python/.test(text))
  const body = (isPy ? text : text.replace(SH_DIRNAME_RX, dir)).replace(/\r\n?/g, '\n')
  // Relative words resolve beside the script and in the runner's cwd (the install
  // root); for a shell script also after a literal `cd`.
  const bases = [root, dir]
  const add = (p: string) => { out.refs.push(p) }
  if (!isPy) shReferences(file, body, out, bases, add)
  // A named .py / .sh is hashed (a docstring naming a script is not proof it runs,
  // so it is not walked); what runs is found by the interpreter / import / subprocess rules.
  for (const m of body.matchAll(CODE_PATH_RX)) {
    const t = m[0]
    if (t.startsWith('~')) continue
    if (isAbsolute(t)) { out.mentions.push(t); continue }
    const cands = [...new Set(bases.map(b => join(b, t)))]
    const hits = cands.filter(fileExists)
    if (hits.length > 0) out.mentions.push(...hits)
    else out.absent.push(...cands)
  }
  if (isPy) pyReferences(file, body, out, add, bases)
  return out
}

function fileExists(p: string): boolean {
  try { return statSync(p).isFile() } catch { return false }
}

function dirExists(p: string): boolean {
  try { return statSync(p).isDirectory() } catch { return false }
}

function sha256Hex(data: string | Buffer): string {
  return createHash('sha256').update(data).digest('hex')
}

/** One reading of a preCheck chain: the sorted [key, digest] pairs, and what the trust and the re-pin need. */
export interface PreCheckWalk {
  pairs: Array<[string, string]>
  /** Files read (or failed to read): the number the approval screen shows. */
  files: number
  /** `MARKER key` for every blocking marker; empty = followable. */
  blockers: string[]
  /** Real path -> bytes of every file read, for the upstream comparison (no second read). */
  contents: Map<string, Buffer>
  /** The walk crossed a symlink. */
  linked: boolean
}

/**
 * The preCheck script and every file it refers to, transitively. digest =
 * sha256, or a marker: a reference that cannot be read is recorded, never
 * thrown, so a file that appears or changes later changes the hash.
 */
export function preCheckWalk(entry: string, root: string = PROJECT_ROOT): PreCheckWalk {
  const seen = new Map<string, string>()
  const contents = new Map<string, Buffer>()
  const analyzed = new Set<string>()
  // [path, runs]: runs = the file is executed / imported (walked), else only named (hashed).
  const queue: Array<[string, boolean]> = [[entry, true]]
  let files = 0
  let linked = false
  const over = new Set<string>()
  const utf8 = new TextDecoder('utf-8', { fatal: true })
  while (queue.length > 0) {
    const [p, runs] = queue.shift() as [string, boolean]
    let real = p
    try { real = realpathSync(p) } catch { /* recorded below as MISSING / ABSENT */ }
    try {
      if (lstatSync(p).isSymbolicLink()) { linked = true; if (!seen.has(p)) seen.set(p, `LINK:${real}`) }
    } catch { /* missing: below */ }
    const prior = seen.get(real)
    if (prior === undefined || (prior === 'ABSENT' && runs)) {
      if (files >= PRECHECK_WALK_MAX_FILES) { over.add(real); continue }
      files++
      try {
        const st = statSync(real)
        if (!st.isFile()) { seen.set(real, 'NOTFILE'); continue }
        if (st.size > PRECHECK_WALK_MAX_BYTES) { seen.set(real, 'TOOBIG'); continue }
        const buf = readFileSync(real)
        seen.set(real, sha256Hex(buf))
        contents.set(real, buf)
      } catch (err) {
        const missing = (err as NodeJS.ErrnoException)?.code === 'ENOENT'
        if (missing && !runs) { files--; seen.set(real, 'ABSENT'); continue }
        seen.set(real, missing ? 'MISSING' : 'UNREADABLE')
        continue
      }
    }
    const buf = contents.get(real)
    if (!runs || buf === undefined || analyzed.has(real)) continue
    analyzed.add(real)
    if (!(real.endsWith('.py') || real.endsWith('.sh') || p === entry || /^#!/.test(buf.subarray(0, 2).toString('latin1')))) continue
    let text: string
    try { text = utf8.decode(buf) } catch { seen.set(`${real}#text`, 'UNPARSEABLE'); continue }
    const r = preCheckReferences(real, text, root)
    for (const u of r.unresolved) seen.set(`${real}#${u}`, 'UNRESOLVED')
    for (const a of r.absent) if (!seen.has(a)) seen.set(a, 'ABSENT')
    for (const ref of r.refs) queue.push([ref, true])
    for (const m of r.mentions) queue.push([m, false])
  }
  const pairs = [...seen.entries()].sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
  if (over.size > 0) pairs.push(['(walk limit)', `LIMIT:${over.size}`])
  const blockers = pairs
    .filter(([, v]) => PRECHECK_BLOCKING_MARKERS.has(v.split(':')[0]))
    .map(([k, v]) => `${v.split(':')[0]} ${k}`)
  return { pairs, files, blockers, contents, linked }
}

/** The [key, digest] pairs only (kept for the pin list and the tests). */
export function preCheckFileDigests(entry: string): Array<[string, string]> {
  return preCheckWalk(entry).pairs
}

/** What the trust needs from one reading of a task's preCheck chain. */
export interface PreCheckContent {
  hash: string
  files: number
  blockers: string[]
  walk: PreCheckWalk
}

function contentOfWalk(walk: PreCheckWalk): PreCheckContent {
  return { hash: sha256Hex(JSON.stringify(['pc2', walk.pairs])), files: walk.files, blockers: walk.blockers, walk }
}

/** One reading of a task's preCheck chain; null when the task has none. */
export function preCheckContent(task: ScheduleTrustFields): PreCheckContent | null {
  if (!task.preCheck) return null
  return contentOfWalk(preCheckWalk(resolvePreCheckPath(String(task.name ?? ''), String(task.preCheck))))
}

/** The pinned-content hash of a task's preCheck; null when the task has none. */
export function preCheckContentHash(task: ScheduleTrustFields): string | null {
  return preCheckContent(task)?.hash ?? null
}

/**
 * The first 16 hex of what the owner approves: the definition hash, and for a
 * task with a preCheck the definition AND the preCheck content together, so
 * the approve call (which echoes it) approves what is on disk at that moment.
 */
export function scheduleTrustShortHash(task: ScheduleTrustFields): string {
  return combinedTrustHash(scheduleTrustHash(task), preCheckContentHash(task)).slice(0, 16)
}

function combinedTrustHash(defHash: string, contentHash: string | null): string {
  return contentHash === null ? defHash : sha256Hex(`${defHash}:${contentHash}`)
}

/**
 * Pure verdict for one task against its stored row. A task with a preCheck is
 * trusted only while its pinned content hash equals the current one and the
 * chain has no blocking marker; an unpinned (null) row is a mismatch (Klodel 42469 b).
 */
export function evaluateScheduleTrust(
  task: ScheduleTrustFields,
  row: (Pick<ScheduleTrustRow, 'status' | 'hash'> & { precheck_hash?: string | null }) | null | undefined,
  content: PreCheckContent | null = preCheckContent(task),
): ScheduleTrustStatus {
  if (!row) return 'agent'
  if (row.status !== 'approved' && row.status !== 'legacy') return 'agent'
  if (typeof row.hash !== 'string' || !HASH_RX.test(row.hash)) return 'mismatch'
  if (row.hash !== scheduleTrustHash(task)) return 'mismatch'
  if (task.preCheck) {
    const pinned = row.precheck_hash
    if (content === null || content.blockers.length > 0) return 'mismatch'
    if (typeof pinned !== 'string' || !HASH_RX.test(pinned) || pinned !== content.hash) return 'mismatch'
  }
  return row.status
}

export function isOwnerTrusted(status: ScheduleTrustStatus): boolean {
  return status === 'approved' || status === 'legacy'
}

/** The verdict for a task as stored now. Any error is 'agent' (fail-closed). */
export function scheduleTrustOf(task: ScheduledTask): ScheduleTrustStatus {
  try {
    return evaluateScheduleTrust(task, getScheduleTrust(task.name))
  } catch (err) {
    logger.warn({ err, task: task.name }, 'schedule-trust: lookup failed, treating the task as agent-authored')
    return 'agent'
  }
}

/** What the approval screen shows beside the 16 hex (Viktor 42472 INFO ii); null without a preCheck. */
export function preCheckApprovalInfo(task: ScheduleTrustFields): { files: number; blockers: string[] } | null {
  try {
    const c = preCheckContent(task)
    return c === null ? null : { files: c.files, blockers: c.blockers }
  } catch {
    return { files: 0, blockers: ['UNREADABLE (walk failed)'] }
  }
}

/**
 * Owner (or install code) approval of the task AS STORED NOW, its preCheck
 * content included. With `expectShort` (the 16 hex the owner saw), nothing is
 * written and null comes back when the task, or a file its preCheck calls,
 * changed since: the check and the write use ONE reading of the files. A chain
 * with a blocking marker is never approved (null): the script has to be fixed.
 */
export function approveScheduledTask(task: ScheduledTask, setBy: string, now = Date.now(), expectShort?: string): string | null {
  const hash = scheduleTrustHash(task)
  const content = preCheckContent(task)
  if (content !== null && content.blockers.length > 0) {
    logger.warn({ task: task.name, blockers: content.blockers.slice(0, 10) }, 'schedule-trust: approval refused, the preCheck chain has a blocking marker')
    return null
  }
  if (expectShort !== undefined && combinedTrustHash(hash, content?.hash ?? null).slice(0, 16) !== expectShort) return null
  setScheduleTrust(task.name, 'approved', hash, setBy, Math.floor(now / 1000), content?.hash ?? null)
  return hash
}

/** A token-side create/edit/delete: the task is agent-authored from here on. */
export function clearScheduleTrust(taskName: string): void {
  try {
    deleteScheduleTrust(taskName)
  } catch (err) {
    // The row survives, but its hash no longer matches the edited task, so the
    // fire still gets the agent framing (and an alert) -- fail-closed anyway.
    logger.warn({ err, task: taskName }, 'schedule-trust: could not drop the trust row')
  }
}

/**
 * One-time legacy import of the tasks that existed when SCHEDTRUST1112
 * shipped (Klodel 39006: they keep today's framing). Does nothing once the
 * baseline row exists. Returns the number of rows written, or null.
 */
export function ensureScheduleTrustBaseline(listTasks: () => ScheduledTask[], now = Date.now()): number | null {
  try {
    const entries = listTasks().map(t => ({ name: t.name, agent: t.agent, hash: scheduleTrustHash(t) }))
    const n = baselineScheduleTrust(entries, Math.floor(now / 1000))
    // Viktor 39032 #7: the baselined set, once, so a later review can compare
    // what was trusted unreviewed. Names and agents are filtered like the alert.
    if (n !== null) {
      logger.warn({
        tasks: n,
        baseline: entries.map(e => ({ name: alertSafeId(e.name), agent: alertSafeId(e.agent), hash: e.hash.slice(0, 16) })),
      }, 'schedule-trust: legacy baseline written (one-time)')
    }
    return n
  } catch (err) {
    logger.error({ err }, 'schedule-trust: legacy baseline failed; every task runs agent-framed until it is approved')
    return null
  } finally {
    // PRECHECKTRUST1114: the one-time preCheck pin runs right after the legacy
    // baseline (same start-up call, so a fresh install pins its legacy rows too).
    ensurePreCheckTrustPin(listTasks, now)
    // Then the upstream re-pin, still before the first tick (Viktor 42476 (2) 4).
    repinPreChecksFromUpstream(listTasks, now)
  }
}

/**
 * PRECHECKTRUST1114 one-time pin of the preCheck content of the tasks trusted
 * when it shipped, as a PINNED TOFU (Viktor 42472 a, 42476 (1); Klodel 42469,
 * 42478): a row is pinned only when the task's content hash today EQUALS the
 * hash reviewed in the PR (`expected`, src/web/schedule-trust-precheck-pins.ts),
 * the row is trusted, still holds the task's current definition hash, has no
 * pin yet, and the chain has no blocking marker. Everything else stays a
 * mismatch until the owner approves (or the upstream re-pin below applies).
 * Does nothing once the pin row exists. Returns the rows pinned, or null.
 */
export function ensurePreCheckTrustPin(
  listTasks: () => ScheduledTask[],
  now = Date.now(),
  expected: Readonly<Record<string, string>> = PRECHECK_PIN_EXPECTED,
): number | null {
  try {
    const entries: Array<{ name: string; agent: string; hash: string; precheckHash: string; files: string[] }> = []
    const skipped: Array<{ name: string; precheck: string; why: string }> = []
    for (const t of listTasks()) {
      if (!t.preCheck) continue
      const row = getScheduleTrust(t.name)
      if (!row || (row.status !== 'approved' && row.status !== 'legacy')) continue
      const hash = scheduleTrustHash(t)
      if (row.hash !== hash) continue
      const c = preCheckContent(t)
      if (c === null) continue
      const want = Object.prototype.hasOwnProperty.call(expected, t.name) ? expected[t.name] : undefined
      const why = c.blockers.length > 0 ? 'blocking marker' : want === undefined ? 'not in the reviewed table' : want !== c.hash ? 'differs from the reviewed hash' : ''
      if (why) { skipped.push({ name: alertSafeId(t.name), precheck: c.hash.slice(0, 16), why }); continue }
      entries.push({
        name: t.name, agent: t.agent, hash, precheckHash: c.hash,
        files: c.walk.pairs.filter(([, d]) => d !== 'ABSENT').map(([f, d]) => `${f} ${d.slice(0, 16)}`),
      })
    }
    const n = pinScheduleTrustPreChecks(entries, Math.floor(now / 1000))
    // The pinned set, once, file by file, so the review (Viktor 42476 (1)) can
    // compare what was pinned with what was read; the skipped ones with the reason.
    if (n !== null) {
      logger.warn({
        tasks: n,
        pinned: entries.map(e => ({ name: alertSafeId(e.name), agent: alertSafeId(e.agent), precheck: e.precheckHash.slice(0, 16), files: e.files })),
        skipped,
      }, 'schedule-trust: preCheck content pinned (one-time)')
    }
    return n
  } catch (err) {
    logger.error({ err }, 'schedule-trust: preCheck pin failed; every task with a preCheck runs agent-framed, without it, until approved')
    return null
  }
}

/**
 * Tasks whose preCheck is NEVER re-pinned from upstream (Klodel 42478, Viktor
 * 42476 (2) 3): security and outage watchers, where a SKIP is an alarm kept
 * quiet. A change in their chain always waits for the owner's click.
 */
export const PRECHECK_REPIN_DENY: ReadonlySet<string> = new Set([
  'billingo-rawtool-figyelo',
  'marabel-watchdog-orfigyelo',
  'marabel-watchdog-napi',
  'kernel-gitconfig-or',
])

interface UpstreamState {
  root: string
  upstream: string
  format: 'sha1' | 'sha256'
  git: (args: string[]) => { status: number; stdout: string }
}

// Plumbing only (Viktor 42476 (2) 2): rev-parse, merge-base, ls-files, ls-tree.
// Never diff / status (an --assume-unchanged file hides from both), no
// fsmonitor, no hook; the local blob id is computed here from the bytes the
// walk read, so no git process ever reads the worktree file.
function upstreamState(root: string): UpstreamState | null {
  const git = (args: string[]) => {
    const r = spawnSync('git', ['-C', root, '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false', ...args], {
      encoding: 'utf8', timeout: 5000, maxBuffer: 1024 * 1024,
      env: { ...process.env, GIT_OPTIONAL_LOCKS: '0', GIT_TERMINAL_PROMPT: '0' },
    })
    return { status: r.status ?? -1, stdout: r.stdout ?? '' }
  }
  const top = git(['rev-parse', '--show-toplevel'])
  if (top.status !== 0 || realpathSync(top.stdout.trim()) !== root) return null
  const up = git(['rev-parse', '--verify', '--quiet', '@{upstream}^{commit}'])
  const upstream = up.stdout.trim()
  if (up.status !== 0 || !/^[0-9a-f]{40}([0-9a-f]{24})?$/.test(upstream)) return null
  // The checkout carries no commit of its own: HEAD is the upstream or behind it.
  if (git(['merge-base', '--is-ancestor', 'HEAD', upstream]).status !== 0) return null
  const fmt = git(['rev-parse', '--show-object-format']).stdout.trim()
  const format = fmt === 'sha256' ? 'sha256' : fmt === 'sha1' || fmt === '' ? 'sha1' : null
  if (format === null) return null
  return { root, upstream, format, git }
}

function gitBlobId(buf: Buffer, format: 'sha1' | 'sha256'): string {
  return createHash(format).update(`blob ${buf.length}\0`).update(buf).digest('hex')
}

/** Every file is tracked and byte-equal to the upstream tree's blob (regular file mode). */
function filesMatchUpstream(s: UpstreamState, files: Map<string, Buffer>): string[] | null {
  const rels: string[] = []
  for (const real of files.keys()) {
    if (!real.startsWith(s.root + sep)) return null
    rels.push(relative(s.root, real))
  }
  if (rels.length === 0) return null
  if (s.git(['ls-files', '-z', '--error-unmatch', '--', ...rels]).status !== 0) return null
  const tree = s.git(['ls-tree', '-z', '--full-tree', s.upstream, '--', ...rels])
  if (tree.status !== 0) return null
  const blobs = new Map<string, string>()
  for (const rec of tree.stdout.split('\0')) {
    const m = /^(100644|100755) blob ([0-9a-f]+)\t(.+)$/.exec(rec)
    if (m) blobs.set(m[3], m[2])
  }
  for (const rel of rels) {
    const want = blobs.get(rel)
    const buf = files.get(join(s.root, rel))
    if (want === undefined || buf === undefined || gitBlobId(buf, s.format) !== want) return null
  }
  return rels
}

/**
 * PRECHECKTRUST1114 re-pin from upstream (Klodel 42474/42478, Viktor 42476 (2)):
 * at start-up, before the first tick, a trusted task whose definition hash
 * still matches but whose preCheck content moved is re-pinned ONLY when every
 * file of its chain is git-tracked and byte-equal to the upstream tree, the
 * checkout's HEAD is an ancestor of the upstream, the chain has no blocking
 * marker and no symlink hop, and the task is not on PRECHECK_REPIN_DENY. Only
 * precheck_hash is written; a definition change never re-pins. Each re-pin is
 * a log line AND an alert to the main agent (task, upstream commit, files).
 *
 * Residual, said out loud: an upstream PR merged WITHOUT a security review
 * makes its chain trusted here (today's rules have no Viktor round), hence the
 * deny list and the alert; and the remote-tracking ref is writable by the same
 * Unix user (git update-ref), like the task files and this DB.
 */
export function repinPreChecksFromUpstream(listTasks: () => ScheduledTask[], now = Date.now(), root: string = PROJECT_ROOT): number {
  let n = 0
  let state: UpstreamState | null | undefined
  try {
    const realRoot = realpathSync(root)
    for (const t of listTasks()) {
      if (!t.preCheck || PRECHECK_REPIN_DENY.has(t.name)) continue
      const row = getScheduleTrust(t.name)
      if (!row || (row.status !== 'approved' && row.status !== 'legacy')) continue
      const defHash = scheduleTrustHash(t)
      if (row.hash !== defHash) continue
      const c = preCheckContent(t)
      if (c === null || c.hash === row.precheck_hash || c.blockers.length > 0 || c.walk.linked) continue
      // Cheap checks first: a chain with a file outside the repo never reaches git.
      if ([...c.walk.contents.keys()].some(f => !f.startsWith(realRoot + sep))) continue
      if (state === undefined) state = upstreamState(realRoot)
      if (state === null) return n
      const rels = filesMatchUpstream(state, c.walk.contents)
      if (rels === null) continue
      if (!repinScheduleTrustPreCheck(t.name, defHash, row.precheck_hash ?? null, c.hash)) continue
      n++
      const name = alertSafeId(t.name)
      const agent = alertSafeId(t.agent)
      const shown = rels.map(r => (/^[A-Za-z0-9._\/-]{1,200}$/.test(r) ? r : '(név)'))
      logger.warn({ task: name, agent, upstream: state.upstream, files: shown, precheck: c.hash.slice(0, 16), at: Math.floor(now / 1000) },
        'schedule-trust: preCheck re-pinned from upstream')
      try {
        createSystemMessage(
          MAIN_AGENT_ID,
          `[UTEMEZES-BIZALOM] A(z) "${name}" ütemezett feladat (agent: ${agent}) preCheck-láncát indításkor újrarögzítettem: ` +
          `minden fájlja git-követett és bájtra egyezik az upstream ${state.upstream.slice(0, 12)} commit tartalmával (${shown.join(', ')}). ` +
          `Ha ilyen merge nem volt, vagy a láncot nem nézte át senki, szólj Viktornak.`,
        )
      } catch (err) {
        logger.warn({ err, task: name }, 'schedule-trust: re-pin alert could not be queued')
      }
    }
  } catch (err) {
    logger.error({ err }, 'schedule-trust: preCheck re-pin from upstream failed; the changed chains stay a mismatch until approved')
  }
  return n
}

// One alert per task per stored definition and preCheck content (keyed by the
// CURRENT combined hash), so a task firing every 10 minutes does not repeat it;
// a further edit alerts again.
const mismatchAlerted = new Map<string, string>()

// Viktor 39032 #2: the alert goes out as a from=system message to the main
// agent, so nothing read from the task files may reach it raw -- the directory
// name and the agent field are free text on disk (newlines, a fake directive,
// kilobytes). Only an id-shaped value is shown; the rest is a fixed template.
const ALERT_ID_RX = /^[A-Za-z0-9._-]{1,64}$/
export function alertSafeId(v: unknown): string {
  return typeof v === 'string' && ALERT_ID_RX.test(v) ? v : '(érvénytelen név)'
}

export function alertScheduleTrust(task: ScheduledTask, status: ScheduleTrustStatus, where: string): void {
  if (isOwnerTrusted(status)) return
  const defHash = scheduleTrustHash(task)
  let content: PreCheckContent | null = null
  try { content = preCheckContent(task) } catch { /* keyed by the definition only */ }
  const key = combinedTrustHash(defHash, content?.hash ?? null)
  if (mismatchAlerted.get(task.name) === key) return
  mismatchAlerted.set(task.name, key)
  const name = alertSafeId(task.name)
  const agent = alertSafeId(task.agent)
  let contentOnly = false
  if (status === 'mismatch') {
    try { contentOnly = getScheduleTrust(task.name)?.hash === defHash } catch { /* the generic text below */ }
  }
  logger.warn({ task: name, agent, status, where, precheckContent: contentOnly }, 'schedule-trust: task is not approved as stored')
  const blocked = contentOnly && content !== null && content.blockers.length > 0
  const what = blocked
    ? `preCheck-lánca olyat tartalmaz, amit a rendszer nem tud követni vagy elolvasni (${content!.blockers.length} jelölő, pl. számolt útvonal vagy hiányzó fájl), ezért jóvá sem hagyható, amíg a szkriptet nem javítják`
    : contentOnly
    ? 'preCheck szkriptjének vagy egy általa hívott fájlnak a tartalma eltér a jóváhagyottól (vagy még nincs rögzítve): valaki átírta a szkriptet'
    : status === 'mismatch'
      ? 'tárolt definíciója eltér a jóváhagyottól (prompt / type / command / preCheck / agent / targetSession): valaki az API-n kívül, a fájlban írta át'
      : 'nincs jóváhagyva, mégis olyat kér, amit az API nem tud beállítani (command / preCheck): fájlból került a tárba'
  try {
    createSystemMessage(
      MAIN_AGENT_ID,
      `[UTEMEZES-BIZALOM] A(z) "${name}" ütemezett feladat (agent: ${agent}) ${what}. ` +
      `Ügynöki keretezéssel fut, bash (command, preCheck) nélkül (${where}). ` +
      `Nézd meg a ~/.claude/scheduled-tasks/${name}/ tartalmát; ha rendben van, a tulajdonos a dashboardon jóváhagyhatja. Ha nem a tulajdonos írta, szólj Viktornak.`,
    )
  } catch (err) {
    logger.warn({ err, task: name }, 'schedule-trust: alert could not be queued')
  }
}

/** Test seam. */
export function _resetScheduleTrustAlertsForTest(): void { mismatchAlerted.clear() }
