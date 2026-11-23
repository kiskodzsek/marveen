#!/usr/bin/env node
// PreToolUse hard-gate: blocks outbound email-send for sub-agents.
//
// Governance control (Szabi 2026-06-25, after the Boni incident: a sub-agent
// autonomously emailed a fabricated address asking for money in Szabi's name).
// Sub-agents may NOT send outbound email; any email must be routed through the
// main agent (Marveen) for approval -- only Marveen retains email-send.
//
// STATED LIMIT (msg 14298): this gate catches the ACCIDENTAL send, not a
// determined evader. Static analysis of arbitrary interpreter code is
// undecidable, so a sub-agent CAN send through interpreter code the patterns
// do not model -- the premise "a sub-agent cannot send outbound" does NOT
// hold against intent, only against accident. The exec-heuristic below covers
// the naive shapes (process-spawn plus a known mailer name in one code
// string) and claims no more. Our sub-agents are not adversaries; if that
// assumption ever changes, this gate is the wrong tool.
//
// Why a hook and not a permissions deny-list: the hook is version- and
// mode-independent, and it can analyze command CONTENT (the Bash send-shape
// heuristics below), which a name/prefix deny rule cannot express.
// CORRECTION (SKIPDENY910, measured 2026-09-10): this comment used to claim
// that --dangerously-skip-permissions BYPASSES the settings.json deny list.
// That is false on every CLI version we measured (2.1.63, 2.1.110, 2.1.267;
// marker-file ground truth, deny arm vs no-deny control, -p AND interactive
// TUI): the deny list IS enforced under the flag, and a tool-name deny is
// enforced by removing the tool from the session entirely. The hook remains
// the primary gate anyway -- future CLI behavior is not a contract, and the
// deny list stays a second, independent layer, not the load-bearing one.
//
// This file is wired into every sub-agent's .claude/settings.json by
// writeAgentSettingsFromProfile() (agent-scaffold.ts), guarded by
// name !== MAIN_AGENT_ID, and re-applied on every spawn (respawn-safe).

import { readFileSync, realpathSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { homedir } from 'node:os'
import { loadLedger, isVerifiedIn, splitAddresses, SOURCE_HELP } from './recipient-ledger.mjs'

// Bash command patterns that send mail. SUBGATEPOZ822 (2026-08-22): these are
// no longer the primary trigger -- they matched CONTENT anywhere in the
// command string, and the header's old premise ("a sub-agent has no
// legitimate need to invoke these") broke measurably: the developer of the
// mail tooling IS a sub-agent, and the gate blocked the delivery of the
// mail-gate fix three times in one afternoon (commit message, PR body,
// card-comment sqlite write), plus five more content hits across the fleet
// the same day. The primary trigger is now isSendInvocation() below
// (command-position analysis); this list remains ONLY as the conservative
// fallback when a command cannot be tokenized (unbalanced quote) -- on
// unparseable input the gate behaves exactly as before, never weaker.
const SEND_PATTERNS = [
  /support-mail\/send\.py/i,
  /\bsend\.py\b/i,
  /api\.resend\.com/i,
  /\bresend\b[^\n]*\b(email|send|message)\b/i,
  /\bsendmail\b/i,
  /\bmsmtp\b/i,
  /\bswaks\b/i,
  /\bsmtplib\b|SMTP\s*\(/i,
  /\bmail\.send\b|\bsendEmail\b/i,
  // graph-mail.ts (PR #668, M365/Exchange Online client-credentials mailbox):
  // its CLI is `tsx scripts/graph-mail.ts send ...`, which none of the above
  // patterns catch (no "sendmail"/"mail.send" substring). Also gate any direct
  // call to the exported sendMail() (e.g. a one-off `node -e`/`tsx -e` that
  // imports the module without going through the CLI).
  /\bgraph-mail\b[^\n]*\bsend\b/i,
  /\bsendMail\s*\(/i,
]

// --- command-position analysis (SUBGATEPOZ822) ------------------------------
// Ported from scripts/hooks/outgoing-copy-gate.py (KAPUHATOKOR822, PR #1042,
// two adversarial rounds): quote-aware tokenization, then the INVOKED program
// of each pipeline/sequence segment decides. A quoted token keeps its
// POSITION, so a quoted provider URL in curl argument position still fires
// (the normal way curl is written), while the same domain inside a quoted -d
// payload stays content (the target pattern is anchored to the token start).
// Wrapper-shell -c strings recurse; interpreter code-string arguments
// (python -c / node -e) are scanned for code-level send calls -- code handed
// to an interpreter IS operation, not content.
// Order-independent heredoc stripping (round 3, msg 14286): the rest of
// the intro line (e.g. a redirect after the marker) is command text and
// is KEPT -- only the body is cut. Without this, marker-first spellings
// leaked the body into command position (FP), and dropping the intro
// would have lost a heredoc-fed real sender (FN).
export const HEREDOC_RE = /(<<-?\s*'?(\w+)'?[^\n]*)\n[\s\S]*?\n\2(?=\s|$)/g
// LOOSELIN1122 (card bbc6bad4): cmd.replace(HEREDOC_RE, '$1') is quadratic on unclosed openers (the lazy body scans
// from every opener to the end; main as well: 8000 "x <<Q<i>" lines 0.5 s, x4 per doubling, 120 000 past the hook
// timeout). looseHeredocCut returns the SAME text in linear time: delimiter lines indexed once, a bisect per opener,
// the \w+ group's backtracking to shorter words tried longest first. Rationale at _LOOSE_OPEN in
// outgoing-copy-gate.py; send-heredoc-strict.test.ts compares it with HEREDOC_RE on generated strings.
const LOOSE_OPEN_RE = /<<-?\s*'?(\w+)/g
const LOOSE_END_RE = /\n(\w+)(?=\s|$)/g
export function looseHeredocCut(cmd) {
  const ends = new Map()
  for (const m of cmd.matchAll(LOOSE_END_RE)) {
    const at = m.index + 1
    const list = ends.get(m[1])
    if (list) list.push(at)
    else ends.set(m[1], [at])
  }
  const lens = [...new Set([...ends.keys()].map((w) => w.length))].sort((a, b) => b - a)
  let out = ''
  let last = 0
  let nl = -1
  const open = new RegExp(LOOSE_OPEN_RE.source, 'g')
  for (;;) {
    const m = open.exec(cmd)
    if (m === null) break
    const wordEnd = m.index + m[0].length
    if (nl < wordEnd) {
      // reuse the newline found for an earlier opener on this line (many openers, one long line)
      nl = cmd.indexOf('\n', wordEnd)
      if (nl < 0) break // no newline left: no later opener can match either
    }
    let stop = -1
    const word = m[1]
    for (const n of lens) {
      if (n > word.length) continue
      const qs = ends.get(word.slice(0, n))
      if (!qs) continue
      let lo = 0
      let hi = qs.length
      while (lo < hi) {
        const mid = (lo + hi) >> 1
        if (qs[mid] < nl + 2) lo = mid + 1
        else hi = mid
      }
      if (lo < qs.length) { stop = qs[lo] + n; break }
    }
    if (stop < 0) { open.lastIndex = m.index + 1; continue }
    out += cmd.slice(last, nl)
    last = stop
    open.lastIndex = stop
  }
  return out + cmd.slice(last)
}
// HDSTRICT1122 (card bbc6bad4, Viktor 50205 / 50220): HEREDOC_RE can drop a command bash RUNS (an empty body, a
// here-string, an opener inside quotes, a <<- body with a tab-led end). isSendInvocation is (loose cut) OR (strict
// cut): the strict cut drops a body only where bash surely reads one, and in every doubtful case cuts nothing, so its
// error leans to a deny (kind 'heredoc-strict', whose message gives the way out: the text from a file). Full rationale
// and Known limits at _STRICT_OPEN in outgoing-copy-gate.py (the python twin); send-invocation-cases.json binds them.
// Known limits of THIS twin: none of its own since SENDCOMMENT1122 / SENDCONT1122 (card 64d10325): the opener-comment
// case is seen by both twins, and a backslash-newline is dropped by both masks before words are read.
const STRICT_OPEN_RE = /(?<![<\w])<<(-?)[ \t]*(['"]?)(\w+)\2(?=[ \t;&|)<>]|$)[^\n]*(?:\n|$)/gm

function strictPrefixOk(prefix) {
  let q = null
  let depth = 0
  let bt = false
  let prev = ' '
  for (let i = 0; i < prefix.length; i++) {
    const ch = prefix[i]
    if (q === "'") {
      if (ch === "'") q = null
    } else if (q === '"') {
      if (ch === '\\') i++
      else if (ch === '"') q = null
      else if (ch === '`') bt = !bt
      else if (ch === '$' && prefix[i + 1] === '(') { depth++; i++ }
    } else if (ch === '\\') i++
    else if (ch === "'" || ch === '"') q = ch
    else if (ch === '#' && ' \t;&|()'.includes(prev)) return false
    else if (ch === '`') bt = !bt
    else if (ch === '(') depth++
    else if (ch === ')') depth = Math.max(0, depth - 1)
    prev = ch
  }
  return q === null && depth === 0 && !bt
}

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

export function strictHeredocCut(cmd) {
  let out = ''
  let pos = 0
  for (;;) {
    STRICT_OPEN_RE.lastIndex = pos
    const m = STRICT_OPEN_RE.exec(cmd)
    if (!m) return out + cmd.slice(pos)
    const opener = m[0]
    const mEnd = m.index + opener.length
    const lineStart = cmd.lastIndexOf('\n', m.index - 1) + 1
    if (!opener.endsWith('\n') || opener.endsWith('\\\n') || !strictPrefixOk(cmd.slice(lineStart, m.index))) {
      out += cmd.slice(pos, mEnd)
      pos = mEnd
      continue
    }
    const endRe = new RegExp('^' + (m[1] ? '\\t*' : '') + escapeRe(m[3]) + '$', 'gm')
    endRe.lastIndex = mEnd
    const end = endRe.exec(cmd)
    if (!end) return out + cmd.slice(pos) // unclosed: bash reads the rest as this body; cut nothing, stop
    out += cmd.slice(pos, mEnd - 1)
    pos = end.index + end[0].length
  }
}
const ENV_ASSIGN = /^[A-Za-z_][A-Za-z_0-9]*=/
// KWSPLIT924: shell reserved words that put the NEXT word in command position.
// Stripped only at the head of a segment, never used as separators -- see the
// full rationale at _CMD_POSITION_KEYWORDS in outgoing-copy-gate.py (the python
// twin); the shared send-invocation-cases.json binds the two copies.
const CMD_POSITION_KEYWORDS = new Set(['if', 'then', 'else', 'elif', 'do', 'while', 'until', '{', '!'])
const SENDER_PROG = /^(sendmail|msmtp|swaks)$/i
const SENDPY = /^send\.py$/i
const PYTHON = /^python3?$/i
const NODEISH = /^(node|tsx|ts-node|deno|bun|npx)$/i
const GRAPHMAIL = /^graph-mail(\.ts|\.js)?$/i
const WRAPPER_SHELL = /^(sh|bash|zsh|dash)$/i
const CURLISH = /^(curl|wget|http)$/i
const RESEND_TARGET = /^(https?:\/\/)?([^/@\s]*\.)?api\.resend\.com(\/|$)/i
const CODE_SEND = /\bsmtplib\b|SMTP\s*\(|\bsendMail\s*\(|\bsendEmail\b|\bmail\.send\b/i
// Naive-shape exec heuristic (msg 14298): process-spawn AND a known mailer
// name together in one interpreter code string. Covers the accidental shapes;
// see the STATED LIMIT in the header for what it deliberately does not claim.
const CODE_EXECISH = /\bsubprocess\b|os\.system|\bpopen\b|child_process|\bexec[A-Za-z]*\s*\(|\bspawn[A-Za-z]*\s*\(/i
const CODE_SENDER_LIT = /sendmail|msmtp|swaks|send\.py/i
const codeStringSends = (code) => CODE_SEND.test(code) || (CODE_EXECISH.test(code) && CODE_SENDER_LIT.test(code))

// Unquoted newline / backtick / `$(` become segment separators; quoted text is
// untouched (it is content). Tracks quote state by hand -- no shell involved.
// SENDCOMMENT1122 (card 64d10325, Viktor 50274): an unquoted `#` at the start of a word is a comment up to the end
// of its line, dropped here (the newline stays a separator), as bash reads it; full rationale at
// _mask_subshell_markers in outgoing-copy-gate.py (the python twin). This twin had no comment handling: a comment
// line before a send was harmless here, but a send commented out (`# sendmail x`) counted as a send.
// SENDEXPR1122 / SENDCONT1122 (Viktor 50303 B1/B2): no comment inside `${...}` or an arithmetic command `((...))` (a
// stack of the open constructs decides), and a backslash-newline is dropped before words are read; see the python twin.
// main's mask (4c2ed11d), verbatim: the "legacy" reading of SENDMODES1122 (see isSendInvocation).
function maskLegacy(cmd) {
  let out = ''
  let q = null
  for (let i = 0; i < cmd.length; i++) {
    const ch = cmd[i]
    if (q) {
      if (ch === '\\' && q === '"' && i + 1 < cmd.length) { out += cmd[i] + cmd[i + 1]; i++; continue }
      if (ch === q) q = null
      out += ch
      continue
    }
    if (ch === "'" || ch === '"') { q = ch; out += ch; continue }
    if (ch === '\\' && i + 1 < cmd.length) { out += cmd[i] + cmd[i + 1]; i++; continue }
    if (ch === '\n' || ch === '`') { out += ';'; continue }
    if (ch === '$' && cmd[i + 1] === '(') { out += ';'; i++; continue }
    out += ch
  }
  return out
}

export function maskSubshellMarkers(cmd, mode = 'A') {
  if (mode === 'legacy') return maskLegacy(cmd)
  let out = ''
  let q = null
  let prev = '\n'
  let bt = false // inside an unquoted backtick substitution: a comment there ends at the closing backtick
  const nxt = { '\n': -1, '`': -1 } // cached next position of each comment end (length = none left): linear
  const ctx = [] // SENDEXPR1122: open ${ (B), (( (A), $( (C), ( (P)
  let nb = 0 // SENDBCLOSE1122: the B entries on ctx (see the python twin)
  for (let i = 0; i < cmd.length; i++) {
    const ch = cmd[i]
    if (q) {
      if (ch === '\\' && q === '"' && i + 1 < cmd.length) { out += cmd[i] + cmd[i + 1]; i++; continue }
      if (ch === q) { q = null; prev = ch }
      out += ch
      continue
    }
    if (ch === "'" || ch === '"') { q = ch; out += ch; continue }
    if (ch === '\\' && i + 1 < cmd.length) {
      if (cmd[i + 1] === '\n') { i++; continue } // SENDCONT1122: a line continuation is gone before bash reads words
      out += cmd[i] + cmd[i + 1]; i++; prev = 'a'; continue
    }
    const top = ctx.length ? ctx[ctx.length - 1] : ''
    if (ch === '#' && ' \t\n;&|()<>`'.includes(prev) && (top === '' || top === 'C' || top === 'P')) {
      for (const c of bt ? ['\n', '`'] : ['\n']) {
        if (nxt[c] < i) { const k = cmd.indexOf(c, i); nxt[c] = k < 0 ? cmd.length : k }
      }
      i = (bt ? Math.min(nxt['\n'], nxt['`']) : nxt['\n']) - 1
      continue
    }
    const wordStart = ' \t\n;&|()<>`'.includes(prev)
    prev = ch
    if (ch === '`') {
      if (bt) prev = 'a' // SENDBTCLOSE1122 (Viktor 50353 F6): after a CLOSING backtick a `#` is mid-word, not a comment
      bt = !bt
    }
    if ((ch === '<' || ch === '>') && cmd[i + 1] === '&') { out += ch; i++; continue } // SENDREDIR1122: `2>&1`
    if (ch === '\n' || ch === '`') { out += ';'; continue }
    if (ch === '$' && cmd[i + 1] === '(') { ctx.push('C'); out += ';'; i++; prev = '('; continue }
    if (ch === '$' && cmd[i + 1] === '{') { ctx.push('B'); nb++ }
    else if (ch === '}' && nb) { while (ctx.pop() !== 'B'); nb-- } // SENDBCLOSE1122: `}` closes everything above its B
    else if (ch === '(') {
      if (wordStart && cmd[i + 1] === '(') { // an arithmetic command, or two subshells in the PP reading
        if (mode === 'PP') ctx.push('P', 'P')
        else ctx.push('A')
        out += '(('; i++; continue
      }
      ctx.push('P')
    } else if (ch === ')' && top) {
      if (top === 'A' && cmd[i + 1] === ')') { ctx.pop(); out += '))'; i++; continue }
      if (top === 'A' && mode === 'A1') ctx[ctx.length - 1] = 'P' // SENDDPAREN1122, the A1 reading: ((true) ) = ( (true) )
      else if (top === 'C' || top === 'P') ctx.pop()
    }
    out += ch
  }
  return out
}

// Quote-aware tokenizer -> [[token, ...], ...] per segment. Throws on an
// unbalanced quote (the caller falls back to the legacy content patterns).
export function segmentsTokens(cmd, strict = false, mode = 'A') {
  const s = maskSubshellMarkers(strict ? strictHeredocCut(cmd) : looseHeredocCut(cmd), mode)
  const segments = []
  let cur = []
  let tok = ''
  let hasTok = false
  let q = null
  const pushTok = () => { if (hasTok) { cur.push(tok); tok = ''; hasTok = false } }
  const pushSeg = () => { pushTok(); if (cur.length) { segments.push(cur); cur = [] } }
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]
    if (q) {
      if (ch === '\\' && q === '"' && i + 1 < s.length) { tok += s[++i]; continue }
      if (ch === q) { q = null; continue }
      tok += ch
      continue
    }
    if (ch === "'" || ch === '"') { q = ch; hasTok = true; continue }
    if (ch === '\\' && i + 1 < s.length) { tok += s[++i]; hasTok = true; continue }
    if (ch === ' ' || ch === '\t') { pushTok(); continue }
    if ('|&;()'.includes(ch)) { pushSeg(); continue }
    tok += ch
    hasTok = true
  }
  if (q) throw new Error('unbalanced quote')
  pushSeg()
  return segments
}

const basename = (t) => t.split('/').pop()

// SENDWRAP924: a wrapper in front of the sender is stepped over WITH its own
// flags -- see the full rationale at _WRAPPERS in outgoing-copy-gate.py (the
// python twin). An unknown long flag without `=` is read both ways, so it errs
// toward auditing. send-invocation-cases.json binds the two copies.
const WRAPPERS = new Map([
  ['time', ['fo', ['format', 'output'], 0]],
  ['sudo', ['ughpCUrtDRT', ['user', 'group', 'host', 'prompt', 'close-from', 'other-user',
    'role', 'type', 'chdir', 'chroot', 'command-timeout'], 0]],
  ['env', ['uCS', ['unset', 'chdir', 'split-string'], 0]],
  ['nohup', ['', [], 0]],
  ['nice', ['n', ['adjustment'], 0]],
  ['exec', ['a', [], 0]],
  ['command', ['', [], 0]],
  ['xargs', ['ILnPsdEa', ['arg-file', 'delimiter', 'eof', 'replace', 'max-lines', 'max-args',
    'max-procs', 'max-chars', 'process-slot-var'], 0]],
  ['timeout', ['sk', ['signal', 'kill-after'], 1]],
  ['setsid', ['', [], 0]],
  // ZSHPREFIX1123 (Viktor 50388 M2): zsh precommand modifiers -- see the python twin
  ['repeat', ['', [], 1]],
  ['noglob', ['', [], 0]],
  ['-', ['', [], 0]],
])
const HEAD_DEPTH = 8
// SENDREDIR1122: a redirect before the command word is stepped over (an operator token alone takes its target);
// see _REDIR in outgoing-copy-gate.py (the python twin).
const REDIR = /^(?:\d+|\{\w+\})?(?:<<<|<<-?|<>|>>|>\||&>>|&>|<|>)(.*)$/s

function commandHeads(toksIn, d = 0) {
  let toks = toksIn
  let k = 0 // an index, not a slice per token (a long assignment chain was quadratic, see the python twin)
  while (k < toks.length) {
    if (ENV_ASSIGN.test(toks[k]) || CMD_POSITION_KEYWORDS.has(toks[k])) { k++; continue }
    const r = REDIR.exec(toks[k])
    if (!r) break
    k += r[1] ? 1 : 2
  }
  toks = toks.slice(k)
  if (!toks.length) return [toks]
  const w = basename(toks[0])
  // Still a wrapper at the depth bound: counts as a send (null), see the python twin.
  if (d >= HEAD_DEPTH) return (WRAPPERS.has(w) || w === 'function' || w === 'coproc') ? [null] : [toks]
  if (w === 'function') return commandHeads(toks.slice(2), d + 1)
  if (w === 'coproc') return [...commandHeads(toks.slice(1), d + 1), ...commandHeads(toks.slice(2), d + 1)]
  const spec = WRAPPERS.get(w)
  if (!spec) return [toks]
  const [shortVal, longVal, positionals] = spec
  let i = 1
  const starts = []
  while (i < toks.length) {
    const t = toks[i]
    if (t === '--') { i++; break }
    if (t.startsWith('--')) {
      if (!t.includes('=') && longVal.includes(t.slice(2))) { i += 2; continue }
      if (!t.includes('=')) starts.push(i + 2)
      i++
      continue
    }
    if (t.startsWith('-') && t.length > 1) {
      if (w === 'command' && (t.includes('v') || t.includes('V'))) return []
      let k = -1
      for (let j = 1; j < t.length; j++) if (shortVal.includes(t[j])) { k = j; break }
      i += k === t.length - 1 ? 2 : 1
      continue
    }
    break
  }
  starts.unshift(i)
  return starts.flatMap((s) => commandHeads(toks.slice(s + positionals), d + 1))
}

function segmentIsSend(toksIn, depth) {
  if (commandHeads(toksIn).some((h) => headIsSend(h, depth))) return true
  // ZSHALWAYS1123 (Viktor 50388 M2): each piece after a zsh `} always` is its own command -- see the python twin
  if (!toksIn.includes('always')) return false
  const cuts = []
  for (let j = 0; j + 1 < toksIn.length; j++) if (toksIn[j] === '}' && toksIn[j + 1] === 'always') cuts.push(j)
  return cuts.some((a, k) => commandHeads(toksIn.slice(a + 2, k + 1 < cuts.length ? cuts[k + 1] : toksIn.length))
    .some((h) => headIsSend(h, depth)))
}

function headIsSend(toks, depth) {
  if (toks === null) return true // the depth bound was hit on a wrapper: audit it
  if (!toks.length) return false
  const prog = basename(toks[0])
  const rest = toks.slice(1)
  if (SENDER_PROG.test(prog)) return true
  if (WRAPPER_SHELL.test(prog) && depth < 3) {
    for (let i = 0; i < rest.length; i++) {
      if (rest[i] === '-c' && rest[i + 1] && isSendInvocation(rest[i + 1], depth + 1)) return true
    }
  }
  // EVALREC1123 (Viktor 50388 M2): eval runs its joined arguments as a command line -- see the python twin
  if (prog === 'eval' && depth < 3) {
    const args = rest[0] === '--' ? rest.slice(1) : rest
    if (args.length && isSendInvocation(args.join(' '), depth + 1)) return true
  }
  if (PYTHON.test(prog) || NODEISH.test(prog)) {
    for (let i = 0; i < rest.length; i++) {
      if ((rest[i] === '-c' || rest[i] === '-e' || rest[i] === '--eval') &&
          rest[i + 1] && codeStringSends(rest[i + 1])) return true
    }
  }
  const candidates = [prog]
  if ((PYTHON.test(prog) || NODEISH.test(prog)) && rest.length) candidates.push(basename(rest[0]))
  if (candidates.some((c) => SENDPY.test(c)) &&
      rest.some((t) => t === '--to' || t.startsWith('--to='))) return true
  if (toks.some((t) => GRAPHMAIL.test(basename(t))) && rest.includes('send')) return true
  if (CURLISH.test(prog) && rest.some((t) => RESEND_TARGET.test(t))) return true
  return false
}

// True when some segment is still a wrapper at the depth bound (HEADDEPTH924),
// so the deny says WHY -- see wrapper_depth_hit in outgoing-copy-gate.py.
export function wrapperDepthHit(cmd) {
  let segments
  try {
    segments = segmentsTokens(cmd)
  } catch {
    return false
  }
  // Only when the bound is the WHOLE reason: a visible send in another segment wins.
  const heads = segments.flatMap((toks) => commandHeads(toks))
  return heads.some((h) => h === null) && !heads.some((h) => h !== null && headIsSend(h, 0))
}

export function buildWrapperDepthMsg() {
  return (
    'TILTVA (governance hard-gate): a parancs valodi fejet nem latom. ' +
    `A parancs a burkolo-korlatnal (${HEAD_DEPTH} egymasba agyazott burkolo: sudo, time, env, nohup, nice, timeout...) ` +
    'is meg burkolo, tehat nem tudom eldonteni, hogy levelkuldes-e, es a kapu ilyenkor fail-closed. ' +
    `Ha ez NEM levelkuldes: csokkentsd a burkolok szamat ${HEAD_DEPTH} vagy kevesebb ala. ` +
    'Ha levelkuldes: sub-agentkent Bash-bol amugy sem kuldhetsz, a kimeno emailt a fo-agens kuldi.'
  )
}

function looseSendInvocation(cmd, depth = 0, mode = 'A') {
  let segments
  try {
    segments = segmentsTokens(cmd, false, mode)
  } catch {
    // Unparseable command: fall back to the LEGACY content patterns, so on
    // this path the gate is exactly as strict as before -- never weaker.
    return SEND_PATTERNS.some((re) => re.test(cmd))
  }
  return segments.some((toks) => segmentIsSend(toks, depth))
}

// HDSTRICT1122: the strict heredoc cut alone (see STRICT_OPEN_RE). A parse error of the strict text falls back like
// the loose pass (the legacy patterns): a deny, never a miss.
export function sendOnlyByStrictHeredoc(cmd, depth = 0, mode = 'A') {
  if (!cmd.includes('<<')) return false
  let segments
  try {
    segments = segmentsTokens(cmd, true, mode)
  } catch {
    return SEND_PATTERNS.some((re) => re.test(cmd))
  }
  return segments.some((toks) => segmentIsSend(toks, depth))
}

// SENDMODES1122 (card 64d10325 round 4, Viktor 50353): the send detection runs on every reading that can differ,
// and a send in ANY of them is a send -- "A" (a word-start (( is arithmetic), "PP" (it is two subshells from its first
// character; only with a (( and a #), "A1" (round 5, Viktor 50388 R1: the round 3 mask, a lone ) with an A on top
// turns it into a P; only with a (( and a #), "legacy" (main's mask; only with a #, a backslash-newline or a >& / <&). The
// python twin (is_send_invocation in outgoing-copy-gate.py) has the reasons and the same readings.
export function sendModes(cmd) {
  const modes = ['A']
  if (cmd.includes('#') && cmd.includes('((')) modes.push('PP', 'A1')
  if (cmd.includes('#') || cmd.includes('\\\n') || cmd.includes('>&') || cmd.includes('<&')) modes.push('legacy')
  return modes
}

export function sendInReading(cmd, depth = 0, mode = 'A') {
  return looseSendInvocation(cmd, depth, mode) || sendOnlyByStrictHeredoc(cmd, depth, mode)
}

export function isSendInvocation(cmd, depth = 0) {
  return sendModes(cmd).some((m) => sendInReading(cmd, depth, m))
}

export function buildHeredocStrictMsg() {
  return (
    'TILTVA (governance hard-gate): a parancs egyik heredoc-torzseben egy sor levelkuldesnek latszik, es a kapu nem ' +
    'tudja biztosan, hogy a bash torzskent olvassa-e (ures torzs, here-string, idezojelben vagy $( )-ben allo nyito, ' +
    'backslash-es sorveg, lezaratlan torzs), ezert fail-closed. Ha ez szoveg, NEM kuldes: ird a szoveget fajlba ' +
    '(Write), es onnan add at, ne heredocbol. Ha levelkuldes: sub-agentkent Bash-bol amugy sem kuldhetsz, a kimeno ' +
    'emailt a fo-agens kuldi.'
  )
}

// Outbound-shaped operations of the multiplexed manage_email tool. Each of
// these sends for real unless the call explicitly asks for a draft.
const MANAGE_EMAIL_SEND_OPS = new Set(['send', 'reply', 'replyall', 'forward'])

// Draft-creating MCP tools. Drafting is allowed (that is the whole point of the
// draft-required rule), but the ADDRESS in a draft still has to be verified:
// the owner presses send on what we typed, so an invented address reaches the
// outside world through a draft just as surely as through a send.
const DRAFT_TOOL_RE = /(^|__)(create_draft|draft_email|update_draft)$/i

// RECOVERYPATH920: the recovery command in the deny message used to be the
// relative `node scripts/recipient-ledger.mjs`. Sub-agents run with cwd
// agents/<name>/, which has NO scripts/ directory, so from a gated agent the
// command died with "Cannot find module .../agents/<name>/scripts/
// recipient-ledger.mjs" -- the one path the gate offers was unreachable from
// the only place it is ever read. Resolve it from this file's own location:
// the gate script and the ledger CLI ship in the same directory, so this is
// correct from any cwd.
const LEDGER_CLI = join(dirname(fileURLToPath(import.meta.url)), 'recipient-ledger.mjs')

// Tool-input fields that carry recipient addresses across the mail tools we
// have. A reply that only names a messageId has none of these -- it is
// addressed by the thread, not by us, so there is nothing to invent.
const RECIPIENT_FIELDS = ['to', 'cc', 'bcc', 'recipients', 'recipient', 'recipient_email']

// Every address in this call that the ledger does not know. Pure: the lookup is
// injected so tests never touch the real ledger file.
export function unverifiedRecipients(toolInput, isVerified) {
  const out = []
  for (const field of RECIPIENT_FIELDS) {
    const value = toolInput?.[field]
    if (value === undefined || value === null || value === '') continue
    for (const addr of splitAddresses(value)) {
      if (!isVerified(addr) && !out.includes(addr)) out.push(addr)
    }
  }
  return out
}

// Default lookup for the live hook: read the ledger once per invocation. A
// missing or corrupt ledger means nothing is verified, so the gate blocks --
// an evidence store that cannot be read must never open the gate silently.
function ledgerLookup() {
  const ledger = loadLedger()
  return (addr) => isVerifiedIn(ledger, addr)
}

// Pure decision: does this tool call send (or attempt to send) email?
// Returns { deny, kind? }. `kind` selects the deny wording at the hook
// entrypoint: 'draft-required' is the manage_email case (drafting is fine,
// only the actual send is refused), 'send_email' is the direct MCP send tool
// (the only path the thread-reply capability below can narrow),
// 'unverified-recipient' is a draft/manage_email address with no recorded
// source, and everything else is the sub-agent governance block.
// MS365GATE1015 (Viktor G1/G3, card d85d38c3): the ms365 policy is an
// ALLOWLIST shared with the main agent's gates (scripts/hooks/ms365-tool-policy.json).
// For a sub-agent nothing on an ms365 server leaves the mailbox: every tool off
// the read/draft list is denied, send-mail included, and every outbound
// operation is denied on ANY server name, so renaming the server does not blind
// the gate. An unreadable policy denies every ms365 tool plus the six send
// operations the first version knew (never blinder than before).
export const MS365_POLICY_PATH = join(dirname(fileURLToPath(import.meta.url)), 'hooks', 'ms365-tool-policy.json')
const MS365_SERVER_RE = /ms-?365/i
const MS365_OUTBOUND_FLOOR = ['send-mail', 'send-draft-message', 'reply-mail-message',
  'reply-all-mail-message', 'forward-mail-message', 'send-shared-mailbox-mail']

export function loadMs365Policy(path = MS365_POLICY_PATH) {
  try {
    const data = JSON.parse(readFileSync(path, 'utf-8'))
    const lists = ['read_draft', 'anchored_send', 'outbound'].map((k) => data[k])
    if (!lists.every((v) => Array.isArray(v) && v.every((x) => typeof x === 'string'))) {
      throw new Error('policy lists are not string arrays')
    }
    const [readDraft, anchored, outbound] = lists
    return { readDraft: new Set(readDraft), anchored: new Set(anchored),
      outbound: new Set([...outbound, ...MS365_OUTBOUND_FLOOR]), error: null }
  } catch (e) {
    return { readDraft: new Set(), anchored: new Set(), outbound: new Set(MS365_OUTBOUND_FLOOR), error: String(e) }
  }
}

let ms365Policy = null

// 'outbound' | 'unlisted' | 'read' | null (not an ms365 tool).
export function ms365ToolClass(toolName, policy = (ms365Policy ??= loadMs365Policy())) {
  const name = String(toolName ?? '')
  if (!name.startsWith('mcp__')) return null
  const rest = name.slice(5)
  const cut = rest.lastIndexOf('__')
  if (cut <= 0 || cut + 2 >= rest.length) return null
  const server = rest.slice(0, cut)
  const op = rest.slice(cut + 2)
  if (policy.outbound.has(op)) return 'outbound'
  if (MS365_SERVER_RE.test(server)) return policy.readDraft.has(op) ? 'read' : 'unlisted'
  return null
}

export function gateDecision(toolName, toolInput, isVerified = null) {
  const name = String(toolName ?? '')
  // Lazy: only build the ledger lookup when a call actually carries addresses,
  // so a read-shaped tool call never pays a file read.
  const verify = isVerified ?? (() => {
    let cached = null
    return (addr) => (cached ??= ledgerLookup())(addr)
  })()
  // Any MCP send_email tool, name-agnostic (gmail or a differently-named
  // server in a customer install -> the matcher + this both key on send_email).
  // Deliberately NOT ledger-checked. This branch is either an unconditional
  // deny, or -- with --allow-thread-reply -- a narrowing that only passes
  // recipients read back from the live thread the reply belongs to. A
  // participant of a thread we can read IS a sourced address in the same sense
  // the ledger means it (the From header of a mail they sent us), so gating it
  // against the file would refuse a legitimately sourced reply. The ledger
  // guards the paths where an address can be typed from memory: drafting and
  // manage_email.
  if (/send_email/i.test(name)) return { deny: true, kind: 'send_email' }
  // The claude.ai Gmail connector (mcp__claude_ai_Gmail__*) has no send_email:
  // its sends are send_message / reply / forward. Drafts stay allowed and the
  // reads are not sends, only the three send-shaped tools are denied
  // (GMAILCONNECTOR914 -- before this line a sub-agent could send through the
  // connector with no gate at all).
  // Kind is NOT 'send_email' on purpose: the thread-reply narrowing at the
  // entrypoint reads send_email-shaped fields (threadId/to), which a connector
  // reply does not carry, so the connector stays fully gated for every agent.
  if (/gmail__(reply|reply_all|send_message|forward)$/i.test(name)) return { deny: true, kind: 'connector-send' }
  // MS365SEND1014 (Viktor F5) + MS365GATE1015 (G1/G3): sub-agents load the
  // root .mcp.json servers too, so a sub-agent session can see the ms365 tools;
  // only the main agent may send, through its approval gate.
  const ms365 = ms365ToolClass(name)
  if (ms365 === 'outbound' || ms365 === 'unlisted') return { deny: true, kind: 'connector-send' }
  // Drafting is allowed, but only to an address with a recorded source.
  if (DRAFT_TOOL_RE.test(name)) {
    const bad = unverifiedRecipients(toolInput, verify)
    if (bad.length) return { deny: true, kind: 'unverified-recipient', addresses: bad }
    return { deny: false }
  }
  // @aaronsb/google-workspace-mcp multiplexes read, draft and send behind one
  // manage_email tool, so the tool NAME cannot decide this one -- the operation
  // plus the draft flag can. This is what replaces the server's own
  // draft-only-email safety policy, which blocks drafting too: that policy keys
  // on ctx.operation alone and never looks at draft:true, so with it enabled the
  // mailbox is effectively read-only (verified live, 2026-08-10).
  if (/(^|__)manage_email$/i.test(name)) {
    const op = String(toolInput?.operation ?? '').toLowerCase()
    if (!MANAGE_EMAIL_SEND_OPS.has(op)) return { deny: false }
    // The address check runs before the draft rule, so it applies to the send
    // AND to the draft the deny message would send us back to write.
    const bad = unverifiedRecipients(toolInput, verify)
    if (bad.length) return { deny: true, kind: 'unverified-recipient', addresses: bad }
    // Fail safe: only an explicit draft request passes. A missing/ambiguous
    // flag is treated as a real send, even though the server would itself
    // force a draft when attachments are present.
    const draft = toolInput?.draft
    if (draft === true || draft === 'true') return { deny: false }
    return { deny: true, kind: 'draft-required' }
  }
  if (name === 'Bash') {
    const cmd = String(toolInput?.command ?? '')
    if (isSendInvocation(cmd)) {
      if (wrapperDepthHit(cmd)) return { deny: true, kind: 'wrapper-depth' }
      return looseSendInvocation(cmd) ? { deny: true } : { deny: true, kind: 'heredoc-strict' }
    }
  }
  return { deny: false }
}

// Deny wording for the manage_email case. Unlike the sub-agent governance
// block this is not about who the agent is: drafting stays open, so the fix is
// to re-issue the same call with draft: true and hand the draft to the owner.
export function buildDraftOnlyMsg(ownerName) {
  return (
    'Kimeno email kuldese tiltott (draft-kapu). ' +
    'Ird meg ugyanezt draft: true kapcsoloval, es jelezd a tulajdonosnak ' +
    `(${ownerName}), hogy a Gmail piszkozatok kozott varja a jovahagyasat. ` +
    'Csak VERIFIKALT cimre. A kuldes gombot ember nyomja meg.'
  )
}

// Deny wording for an address the ledger does not know. This is the one deny
// the agent can clear on its own -- by going and finding where the address
// actually comes from. It names the exact command, so the cheap path is the
// correct path and not "write it anyway".
export function buildUnverifiedRecipientMsg(addresses) {
  const list = addresses.join(', ')
  const first = addresses[0] ?? 'cim@pelda.hu'
  return (
    `Nem igazolt cimzett: ${list}. ` +
    'Ez a kapu azert van, mert egy kitalalt cimre meno level neman elveszik ' +
    '(support@connectors.hu, 2026-08-14, 550 User doesn\'t exist). ' +
    'Ne talalgass es ne a support@/info@ szokast hasznald: keresd meg a cimet ' +
    'egy valodi forrasban -- a toluk kapott level From fejleceben ' +
    '(manage_email search: from:<domain> in:anywhere), az elo oldalukon, ' +
    'a Woo rendelesben vagy a Notion lapon. Aztan vedd fel a ledgerbe:\n' +
    `  node ${LEDGER_CLI} add ${first} --source <forras> --note "<honnan>"\n` +
    `  --source: ${SOURCE_HELP}\n` +
    'Ha nem talalsz forrast, a cim NINCS meg: mondd meg a gazdanak, ne kuldj levelet.'
  )
}

// Pure builder for the deny message, so the brand/owner substitution is
// provable without spawning the hook. With the stock defaults (botName
// 'Marveen', ownerName 'Szabolcs') the wording is byte-identical to before.
export function buildGateMsg(botName, ownerName) {
  return (
    'Email-kuldes sub-agentkent tiltott (governance hard-gate). ' +
    `Kuldd a tervezett emailt (CIMZETT + TARGY + TELJES SZOVEG) ${botName}nek inter-agent uzenetben ` +
    `jovahagyasra; a kimeno emailt ${botName} kuldi. Csak VERIFIKALT cimre (soha nem nevbol talalt cim). ` +
    `Soha ne irj ala ${ownerName} nevevel, es soha ne kerj penzt senki neveben.`
  )
}

// Resolve the brand + owner display names for the deny message. The hook runs
// standalone (no config.ts), so read the install's .env directly, keyed off
// this file's own location (<root>/scripts/email-send-gate.mjs -> <root>/.env).
// Any failure falls back to the stock defaults, so the gate never breaks and a
// bare install keeps the original wording.
export function readBrandEnv(readFile = (p) => readFileSync(p, 'utf-8')) {
  const fallback = { botName: 'Marveen', ownerName: 'Szabolcs' }
  try {
    const envPath = join(dirname(fileURLToPath(import.meta.url)), '..', '.env')
    const raw = readFile(envPath)
    const pick = (key) => {
      const m = raw.match(new RegExp(`^\\s*${key}\\s*=\\s*(.*)$`, 'm'))
      if (!m) return ''
      return m[1].trim().replace(/^["']|["']$/g, '').trim()
    }
    return {
      botName: pick('BOT_NAME') || fallback.botName,
      ownerName: pick('OWNER_NAME') || fallback.ownerName,
    }
  } catch {
    return fallback
  }
}

// --- thread-scoped reply (BONIMAIL910) --------------------------------------
// Owner decision 2026-09-10: ONE named agent may send outbound email, but ONLY
// into an EXISTING Gmail thread and ONLY to addresses that already appear in
// that thread's headers. The capability is granted per agent in code
// (agent-scaffold.ts appends --allow-thread-reply to this hook's command when
// the agent's capability list contains EMAIL_THREAD_REPLY_CAPABILITY); every
// other agent keeps the unconditional deny above.
//
// Why THREAD-MEMBERSHIP and not a topic rule: the 2026-06-25 incident that
// created this gate was a sub-agent mailing a FABRICATED address in the
// owner's name. Membership in an existing thread is checkable in code; "is
// this financial" is not. The narrowing closes exactly the failure shape that
// created the rule: a new address can never be introduced.
//
// Every branch below fails CLOSED: missing threadId, unparseable recipient,
// empty participant list, credential/fetch/HTTP error, timeout -> deny.

// One address token. Deliberately simple: it must match what appears both in
// the tool input and in Gmail's From/To/Cc header values.
const ADDR_TOKEN = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi

// Parse one recipient entry ("addr" or "Name <addr>") to a bare lowercase
// address. Returns '' when the entry is not a single clean address -- the
// caller treats that as deny (an unparseable recipient must never slip past
// the membership check).
export function extractAddress(raw) {
  const s = String(raw ?? '').trim()
  const angle = s.match(/<([^<>]+)>$/)
  const cand = (angle ? angle[1] : s).trim()
  return /^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$/i.test(cand) ? cand.toLowerCase() : ''
}

// Validate the send_email tool input as a thread-reply request. Pure.
// Returns { ok: true, threadId, recipients } or { ok: false, reason }.
export function threadReplyRequest(toolInput) {
  const threadId = toolInput?.threadId
  if (typeof threadId !== 'string' || !threadId.trim()) {
    return { ok: false, reason: 'threadId hianyzik (uj szal nyitasa tiltott)' }
  }
  const raw = [toolInput?.to, toolInput?.cc, toolInput?.bcc]
    .flatMap((v) => (Array.isArray(v) ? v : v == null ? [] : [v]))
  if (!raw.length) return { ok: false, reason: 'nincs cimzett' }
  const recipients = []
  for (const r of raw) {
    const addr = extractAddress(r)
    if (!addr) return { ok: false, reason: `ertelmezhetetlen cimzett: ${String(r)}` }
    recipients.push(addr)
  }
  return { ok: true, threadId: threadId.trim(), recipients }
}

// The membership decision itself. Pure. Empty participant list denies: a
// thread we could not read participants from authorizes nothing.
export function threadMembershipDecision(recipients, participants) {
  const set = new Set((participants ?? []).map((p) => String(p).toLowerCase()).filter(Boolean))
  if (!set.size) return { allow: false, reason: 'a szal resztvevo-listaja ures (fail-closed)' }
  for (const r of recipients) {
    if (!set.has(r)) return { allow: false, reason: `cimzett nincs a szalban: ${r}` }
  }
  return { allow: true }
}

// Collect every address that appears in the thread's From/To/Cc/Reply-To
// headers. Pure over the Gmail API thread payload (format=metadata).
export function extractParticipants(threadData) {
  const out = new Set()
  for (const msg of threadData?.messages ?? []) {
    for (const h of msg?.payload?.headers ?? []) {
      const n = String(h?.name ?? '').toLowerCase()
      if (n === 'from' || n === 'to' || n === 'cc' || n === 'reply-to') {
        for (const m of String(h?.value ?? '').matchAll(ADDR_TOKEN)) out.add(m[0].toLowerCase())
      }
    }
  }
  return [...out]
}

// Fetch the thread's participant addresses with the same credentials the Gmail
// MCP server uses (same mailbox the send would go through, so the gate and the
// send see the same thread). Path resolution mirrors the MCP server's own:
// GMAIL_CREDENTIALS_PATH / GMAIL_OAUTH_PATH env overrides, else ~/.gmail-mcp.
// Throws on ANY failure; per-request timeouts keep the whole check well under
// the hook's 10s budget (a hook timeout would be a NON-blocking error, i.e.
// fail-open -- the script must always decide first).
export async function fetchThreadParticipants(threadId, opts = {}) {
  const fetchImpl = opts.fetchImpl ?? fetch
  const readFile = opts.readFile ?? ((p) => readFileSync(p, 'utf-8'))
  const now = opts.now ?? (() => Date.now())
  const home = process.env.HOME || homedir()
  const credPath = process.env.GMAIL_CREDENTIALS_PATH || join(home, '.gmail-mcp', 'credentials.json')
  const keysPath = process.env.GMAIL_OAUTH_PATH || join(home, '.gmail-mcp', 'gcp-oauth.keys.json')
  const creds = JSON.parse(readFile(credPath))
  let accessToken = creds.access_token
  const fresh = typeof creds.expiry_date === 'number' && creds.expiry_date > now() + 60_000
  if (!fresh) {
    const keys = JSON.parse(readFile(keysPath))
    const k = keys.installed ?? keys.web
    if (!k?.client_id || !k?.client_secret || !creds.refresh_token) {
      throw new Error('gmail credentials incomplete')
    }
    const res = await fetchImpl(k.token_uri || 'https://oauth2.googleapis.com/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        client_id: k.client_id,
        client_secret: k.client_secret,
        refresh_token: creds.refresh_token,
        grant_type: 'refresh_token',
      }).toString(),
      signal: AbortSignal.timeout(3500),
    })
    if (!res.ok) throw new Error(`token refresh failed: ${res.status}`)
    accessToken = (await res.json())?.access_token
  }
  if (!accessToken) throw new Error('no gmail access token')
  const url = 'https://gmail.googleapis.com/gmail/v1/users/me/threads/'
    + encodeURIComponent(threadId)
    + '?format=metadata&metadataHeaders=From&metadataHeaders=To&metadataHeaders=Cc&metadataHeaders=Reply-To'
  const res = await fetchImpl(url, {
    headers: { Authorization: `Bearer ${accessToken}` },
    signal: AbortSignal.timeout(3500),
  })
  if (!res.ok) throw new Error(`thread fetch failed: ${res.status}`)
  return extractParticipants(await res.json())
}

// Deny wording for the thread-reply case: the agent HAS a send right, the
// specific call fell outside it. Says what the right covers and the way out.
export function buildThreadDenyMsg(botName, detail) {
  return (
    'Kimeno email ezzel a jogosultsaggal CSAK meglevo szalba mehet, es csak a ' +
    `szalban mar szereplo cimzettnek (szal-kapu). Elutasitva: ${detail}. ` +
    `Uj cimzetthez vagy uj szalhoz kuldd a tervezett emailt ${botName}nek ` +
    'inter-agent uzenetben jovahagyasra.'
  )
}

function allow() { process.exit(0) }

function deny(reason) {
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'deny',
      permissionDecisionReason: reason,
    },
  }))
  process.exit(0)
}

// Run as the hook entrypoint only when invoked directly (not when imported by a
// test). Reads the PreToolUse payload from stdin and emits a deny decision for
// email-send tool calls. realpath both sides so a symlinked install path (the
// hook command is an absolute path that may traverse a symlink, e.g. /tmp ->
// /private/tmp on macOS, or a symlinked /home on Linux) still matches -- a raw
// url-vs-argv compare would silently no-op the gate (a security bypass).
function isInvokedDirectly() {
  try {
    const self = realpathSync(fileURLToPath(import.meta.url))
    const entry = process.argv[1] ? realpathSync(process.argv[1]) : ''
    return self === entry
  } catch {
    return false
  }
}
if (isInvokedDirectly()) {
  let payload
  try {
    payload = JSON.parse(readFileSync(0, 'utf-8'))
  } catch {
    allow() // malformed/empty input must never break the agent's tool calls
  }
  const { deny: shouldDeny, kind, addresses } = gateDecision(payload?.tool_name, payload?.tool_input)
  if (shouldDeny) {
    const { botName, ownerName } = readBrandEnv()
    // An address with no recorded source loses before every other branch,
    // including the thread-reply narrowing below: a verified thread cannot
    // vouch for an unsourced recipient.
    if (kind === 'unverified-recipient') deny(buildUnverifiedRecipientMsg(addresses ?? []))
    if (kind === 'draft-required') deny(buildDraftOnlyMsg(ownerName))
    if (kind === 'wrapper-depth') deny(buildWrapperDepthMsg())
    if (kind === 'heredoc-strict') deny(buildHeredocStrictMsg())
    // Thread-scoped narrowing: only when the scaffold wired this agent's hook
    // command with the flag (capability-driven, regenerated on every spawn),
    // and only for the direct send_email tool. Bash send routes and
    // manage_email stay fully gated even for the capable agent.
    if (kind === 'send_email' && process.argv.includes('--allow-thread-reply')) {
      const req = threadReplyRequest(payload?.tool_input)
      if (!req.ok) deny(buildThreadDenyMsg(botName, req.reason))
      let verdict
      try {
        const participants = await fetchThreadParticipants(req.threadId)
        verdict = threadMembershipDecision(req.recipients, participants)
      } catch {
        verdict = { allow: false, reason: 'a szal resztvevoi nem olvashatok (fail-closed)' }
      }
      if (verdict.allow) allow()
      deny(buildThreadDenyMsg(botName, verdict.reason))
    }
    deny(buildGateMsg(botName, ownerName))
  }
  allow()
}
