/**
 * Inbound-probe: active deafness watchdog for the main main channels session.
 *
 * Architecture note: the actual Telegram ping is sent by a Python script
 * (scripts/watchdog-inbound-prober.py) using the existing telethon session.
 * Rationale: telethon's asyncio event loop, StringSession handling, and
 * FloodWait back-off are already Python-shaped (see watchdog-userbot-login.py).
 * Re-implementing MTProto session handling in TS for a 30-line prober is
 * disproportionate. This TS module manages the Python prober's lifecycle and
 * implements the pure decision logic.
 *
 * MANUAL GATE: the prober account must be /telegram:access allowlisted
 * by the operator before the inbound probe can send messages. Until then the Python
 * prober detects the unauthorised state and exits 0 (no-op). No respawn is
 * triggered by the TS side when the session file is absent.
 */

import { closeSync, existsSync, openSync, readdirSync, readFileSync, readSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { homedir } from 'node:os'
import { spawn, type ChildProcess } from 'node:child_process'
import { logger } from '../logger.js'
import { PROJECT_ROOT } from '../config.js'
import { readEnvFile } from '../env.js'
import { getEffectiveSettingValue } from '../settings-store.js'
import { resolveOwnerChatId } from '../owner-chat.js'
import { projectsDirFor } from './active-model.js'

// Mirrors KEEPALIVE_RESPAWN_GRACE_MS from channel-monitor.ts (15 min).
// Not imported directly to avoid a circular module dependency: channel-monitor.ts
// lazy-imports inbound-probe.ts; inbound-probe.ts uses dynamic import() of
// channel-monitor.ts to call hardRestartMarveenChannels at respawn time.
const RESPAWN_GRACE_MS = 15 * 60 * 1000

const SESSION_FILE = join(PROJECT_ROOT, 'store', '.watchdog-userbot.session')
const PROBE_LAST_SENT_FILE = join(PROJECT_ROOT, 'store', '.watchdog-probe-last-sent')
const VENV_PYTHON = join(PROJECT_ROOT, '.watchdog-venv', 'bin', 'python3')
const PROBER_SCRIPT = join(PROJECT_ROOT, 'scripts', 'watchdog-inbound-prober.py')

// Transcript directory for the main channels session JSONL files. Claude Code
// encodes a project dir by replacing every character outside [a-zA-Z0-9-]
// with '-' (measured, src/claude-project-dir.ts) --
// see projectsDirFor in active-model.ts, the canonical encoder already relied
// on by schedule-runner and the context-guard/restart-gate watchdogs. A
// hand-rolled slash-only encoder here
// used to disagree with it on any PROJECT_ROOT containing another separator
// Claude Code also encodes (e.g. a dot in the username), which made this
// constant point at a directory Claude Code never creates -- see the
// 866da985 postmortem below mainTranscriptDirs().
//
// Kept as the SHARED-ROOT candidate only; every caller must go through
// mainTranscriptDirs() instead -- see the comment there.
export const TRANSCRIPT_DIR = projectsDirFor(PROJECT_ROOT, join(process.env.HOME ?? homedir(), '.claude'))

// CONFIG-DIR BLIND SPOT (2026-09-11, ~2h of false keepalive respawns): the
// constant above assumes the main channels agent writes its transcript under the
// SHARED ~/.claude. That stopped being true the moment main-agent config
// isolation shipped -- with MAIN_AGENT_ISOLATED_CONFIG=1 the session runs with
// CLAUDE_CONFIG_DIR=<PROJECT_ROOT>/.channels-config, so its JSONL lands in
// <PROJECT_ROOT>/.channels-config/projects/<encoded-cwd>/ and the watchdogs read
// an empty (or frozen) directory forever. Two things break at once:
//   - refreshKeepaliveFromInbound() never sees live traffic, so a BUSY
//     conversation ages the keepalive file out (the scheduled edit_message
//     keep-alive is busy-skipped exactly then) and the staleness watchdog
//     respawn-panes the running conversation away;
//   - the inbound probe reads lastIngestionTs as null/stale and can declare
//     deafness on a perfectly healthy channel.
// Rather than re-deriving the isolation gates here (settings + fleet token +
// dir existence -- three places to drift out of sync, and an import cycle into
// agent-process.ts), we probe EVERY candidate root and take the newest
// ingestion across them. A root that is not in use simply yields an older
// timestamp or none, and "newest wins" is exactly the question being asked.
// The CONFIG ROOTS (not the projects/ subdirs) the main agent may be writing
// its transcript under. Exported separately from mainTranscriptDirs() because
// not every caller wants the main agent's own cwd: the schedule runner asks the
// same question about a task it injected, and needs the roots so it can join
// them with ITS working dir. Keeping the isolation knowledge in one function is
// the whole point -- a second copy is what produced the schedule-runner blind
// spot this list was already supposed to prevent (2026-09-14).
export function mainConfigRoots(): string[] {
  const roots = [
    join(process.env.HOME ?? homedir(), '.claude'),
    join(PROJECT_ROOT, '.channels-config'),
  ]
  // An operator-set MAIN_AGENT_CONFIG_DIR (a separate Claude login for the bot)
  // wins over both defaults, so it must be a candidate too. Read defensively:
  // the settings store must never be able to break a watchdog tick.
  try {
    let raw = String(getEffectiveSettingValue('MAIN_AGENT_CONFIG_DIR') ?? '').trim()
    if (raw) {
      if (raw.startsWith('~')) raw = join(homedir(), raw.slice(1))
      roots.push(raw)
    }
  } catch {
    // keep the defaults
  }
  return [...new Set(roots)]
}

// POSTMORTEM (866da985, 2026-09-20): this used to encode PROJECT_ROOT with a
// local `PROJECT_ROOT.replace(/\//g, '-')` that only strips slashes, while
// Claude Code itself also replaces dots with '-' (the character class is
// `[/.]`, not `/` alone). On this host PROJECT_ROOT is
// /Users/a.kobza/marveen -- the dot in the username meant the computed directory
// (.../-Users-a.kobza-marveen) never existed on disk (the real one is
// .../-Users-a-kobza-marveen), so readLastIngestionTimestampAcross() always
// returned null. shouldRefreshKeepaliveFromInbound() is `lastInboundTs !=
// null && ...`, so it was permanently false: refreshKeepaliveFromInbound()
// never advanced store/.channel-keepalive's mtime, no matter how much real
// Telegram traffic or inter-agent processing occurred. The file aged out
// past KEEPALIVE_STALE_MS forever, and once past KEEPALIVE_RESPAWN_GRACE_MS
// (15 min) the very next non-busy poll tick force-respawned the session --
// measured live at 63 respawns in one day, each one wiping the running
// conversation (memory/kanban survive; the live turn does not). Fixed by
// reusing projectsDirFor(), the same encoder schedule-runner and the
// context-guard/restart-gate watchdogs already trust for this exact
// question -- see the 09-11 CONFIG-DIR BLIND SPOT comment above for why a
// second hand-rolled copy of this logic is exactly how this kind of bug
// hides for months on hosts whose username has no dot in it.
export function mainTranscriptDirs(): string[] {
  const dirs = mainConfigRoots().map(root => projectsDirFor(PROJECT_ROOT, root))
  return [...new Set(dirs)]
}

// Newest inbound-channel ingestion across every candidate transcript root.
// Returns null only when NO candidate has one.
export function readLastIngestionTimestampAcross(dirs: string[]): number | null {
  let newest: number | null = null
  for (const dir of dirs) {
    const ts = readLastIngestionTimestamp(dir)
    if (ts != null && (newest == null || ts > newest)) newest = ts
  }
  return newest
}

// N3: named constant for the probe timeout multiplier.
// probeTimeoutMs = probeIntervalMs * PROBE_TIMEOUT_MULTIPLIER (allow 2x interval before declaring deaf).
const PROBE_TIMEOUT_MULTIPLIER = 2

// W4: env-derived values cached once at startInboundProber() startup.
// Reading .env from disk every tick is unnecessary and wasteful.
let _cachedProbeIntervalMs: number | null = null
let _cachedAllowedChatId: string | null | undefined = undefined // undefined = not yet read

// W3: one-shot flags to avoid repeating "session missing" / "ALLOWED_CHAT_ID absent" warnings every tick.
let _warnedSessionMissing = false
let _warnedChatIdAbsent = false

// Module-level last-respawn tracker for the inbound-probe path.
// Separate from marveenLastKeepaliveRespawn in channel-monitor.ts so the two
// paths do not interfere with each other's grace windows.
let lastInboundRespawn = 0

let proberProcess: ChildProcess | null = null

// ---------------------------------------------------------------------------
// Pure exported functions
// ---------------------------------------------------------------------------

/**
 * Pure decision: should the watchdog trigger a deafness respawn?
 *
 * @param markerTs         When the __wd_ping was sent (ms since epoch).
 * @param lastIngestionTs  When the most recent <channel source= ingestion was
 *                         seen in the session transcript, or null if no
 *                         ingestion has been recorded yet.
 * @param probeTimeoutMs   Inactivity window after which we declare deaf.
 * @param nowMs            Current wall-clock time (ms since epoch).
 *
 * Returns true (trigger respawn) when:
 *   - nowMs - markerTs >= probeTimeoutMs (the timeout has elapsed), AND
 *   - lastIngestionTs is null OR lastIngestionTs < markerTs
 *     (no ingestion has been seen since the marker was sent).
 *
 * Returns false in all other cases.
 */
export function shouldTriggerDeafnessRespawn(opts: {
  markerTs: number
  lastIngestionTs: number | null
  probeTimeoutMs: number
  nowMs: number
}): boolean {
  const { markerTs, lastIngestionTs, probeTimeoutMs, nowMs } = opts
  if (nowMs - markerTs < probeTimeoutMs) return false
  return lastIngestionTs == null || lastIngestionTs < markerTs
}

/**
 * Find the most recent inbound-channel ingestion in a transcript directory.
 * Returns its timestamp (ms since epoch), or null if none is found within the
 * read budget.
 *
 * WHAT COUNTS (card 194e7ada, measured 2026-11-14 on the main agent's 337
 * transcripts): only a line that IS an inbound channel message --
 *   - type "user" whose message.content is a string starting with
 *     `<channel source=` (the delivered turn), or
 *   - type "queue-operation", operation "enqueue", whose content starts with
 *     `<channel source=` (the message arrived while the session was busy).
 * A bare substring match is NOT enough: every session file carries the marker
 * in non-inbound lines too -- the "attachment" line of type
 * mcp_instructions_delta (the channel plugin's own instructions, stamped with
 * the SESSION START time) and the system-prompt "api-request-blob". Before this
 * fix a fresh session file under 256 KB returned its start time as the "last
 * inbound", which could warm store/.channel-keepalive with no real traffic.
 *
 * WHERE IT LOOKS: the newest files by mtime (at most `maxFiles`), each read
 * BACKWARD in `chunkBytes` chunks, with one shared `maxBytes` budget per call.
 * The old reader looked only at the last 256 KB of the newest file; every
 * restart opens a new file, and the large inter-agent/tool traffic pushes the
 * last inbound out of a fixed tail window, so it returned null for every agent
 * (all 5 intake rows "unknown-inbound" on 2026-11-14). The budget keeps the
 * synchronous read bounded (B1: do not block the event loop on 100s of MB);
 * a null now means "no inbound within the budget", not "never".
 *
 * Files are visited newest-first; once a match is found, a file whose mtime is
 * older than that match cannot hold a later line, so the scan stops there.
 *
 * NOTE: Do NOT log line contents -- JSONL lines may contain full Telegram
 * message text (PII). Only the extracted timestamp is ever returned.
 */
// Sized on 2026-11-14 (measured): the main agent restarts several times a
// day (a new file each time); after a quiet night its last inbound sat in the
// 15th newest file, about 23 MB back. With these limits the live run found it,
// and a dir with NO inbound (the worst case, the whole budget read) took
// 7-14 ms per call. A longer silence than that reads as null ("unknown"). Called once a minute (keepalive)
// and once per agent every 5 minutes (intake monitor).
// maxFiles 16 -> 24 (card 116c95c8, Viktor 42177 INFO 2): at 16 the live main dir had one file of headroom;
// the 32 MB budget still bounds the read (the main agent's files are 1-3 MB, so the budget, not the file
// count, is now the usual limit).
export const INGESTION_READ_DEFAULTS = {
  maxFiles: 24,
  maxBytes: 32 * 1024 * 1024,
  chunkBytes: 256 * 1024,
}

const CHANNEL_MARKER = '<channel source='
const CHANNEL_MARKER_BYTES = Buffer.from(CHANNEL_MARKER, 'utf-8')

/** The timestamp (ms) of a transcript line that is an inbound channel message, else null. */
export function inboundChannelLineTs(line: string): number | null {
  let obj: unknown
  try { obj = JSON.parse(line) } catch { return null }
  if (!obj || typeof obj !== 'object') return null
  const o = obj as {
    type?: unknown
    operation?: unknown
    content?: unknown
    timestamp?: unknown
    message?: { role?: unknown; content?: unknown } | null
  }
  let inbound = false
  if (o.type === 'user') {
    const m = o.message
    inbound = !!m && typeof m === 'object' && typeof m.content === 'string' && m.content.startsWith(CHANNEL_MARKER)
  } else if (o.type === 'queue-operation') {
    inbound = o.operation === 'enqueue' && typeof o.content === 'string' && o.content.startsWith(CHANNEL_MARKER)
  }
  if (!inbound || typeof o.timestamp !== 'string') return null
  const ts = new Date(o.timestamp).getTime()
  return Number.isFinite(ts) ? ts : null
}

// The last inbound line in one file, read backward chunk by chunk. `budget.left`
// is shared across the files of one call and decremented by the bytes read.
// A line stamped more than this far in the future is not trusted (card 116c95c8, Viktor 42177 INFO 5): the
// timestamp comes from the Claude client's clock, and a future one would hold store/.channel-keepalive fresh
// until the wall clock caught up. It is skipped, not clamped: a clamp to "now" would re-warm the keepalive
// every minute for as long as the bad line stayed the newest. The scan goes on to the previous line.
export const INGESTION_FUTURE_SKEW_MS = 5 * 60 * 1000

function lastInboundInFile(path: string, size: number, chunkBytes: number, budget: { left: number }, latestOk: number): number | null {
  const fd = openSync(path, 'r')
  try {
    let pos = size
    let carry: Buffer = Buffer.alloc(0) // the (partial) first line of the later chunk
    while (pos > 0 && budget.left > 0) {
      const len = Math.min(chunkBytes, pos, budget.left)
      pos -= len
      budget.left -= len
      const buf = Buffer.allocUnsafe(len)
      // A short read (the file shrank under us) would splice two lines: give up on this file.
      if (readSync(fd, buf, 0, len, pos) !== len) break
      const data = carry.length ? Buffer.concat([buf, carry]) : buf
      let complete: Buffer
      if (pos > 0) {
        // The first line may start before this chunk: keep it for the next round.
        const nl = data.indexOf(0x0a)
        if (nl < 0) { carry = data; continue }
        carry = data.subarray(0, nl)
        complete = data.subarray(nl + 1)
      } else {
        carry = Buffer.alloc(0)
        complete = data
      }
      // Newest first: walk the marker occurrences backward.
      let from = complete.length
      while (from > 0) {
        const at = complete.lastIndexOf(CHANNEL_MARKER_BYTES, from - 1)
        if (at < 0) break
        const start = complete.lastIndexOf(0x0a, at) + 1
        let end = complete.indexOf(0x0a, at)
        if (end < 0) end = complete.length
        const ts = inboundChannelLineTs(complete.subarray(start, end).toString('utf-8'))
        if (ts != null && ts <= latestOk) return ts
        from = start - 1
      }
    }
    return null
  } finally {
    closeSync(fd)
  }
}

export function readLastIngestionTimestamp(
  transcriptDir: string,
  opts: Partial<typeof INGESTION_READ_DEFAULTS> & { nowMs?: number } = {},
): number | null {
  const { maxFiles, maxBytes, chunkBytes } = { ...INGESTION_READ_DEFAULTS, ...opts }
  const latestOk = (opts.nowMs ?? Date.now()) + INGESTION_FUTURE_SKEW_MS
  try {
    if (!existsSync(transcriptDir)) return null
    const files: { path: string; mtimeMs: number; size: number }[] = []
    for (const entry of readdirSync(transcriptDir)) {
      if (!entry.endsWith('.jsonl')) continue
      const path = join(transcriptDir, entry)
      try {
        const st = statSync(path)
        if (st.isFile()) files.push({ path, mtimeMs: st.mtimeMs, size: st.size })
      } catch {
        // file disappeared between readdir and stat -- skip
      }
    }
    files.sort((a, b) => b.mtimeMs - a.mtimeMs)
    const budget = { left: maxBytes }
    let best: number | null = null
    for (const f of files.slice(0, maxFiles)) {
      if (budget.left <= 0) break
      if (best != null && f.mtimeMs < best) break // nothing in it can be later
      let ts: number | null = null
      try { ts = lastInboundInFile(f.path, f.size, chunkBytes, budget, latestOk) } catch { /* unreadable -- skip */ }
      if (ts != null && (best == null || ts > best)) best = ts
    }
    return best
  } catch {
    return null
  }
}

// ---------------------------------------------------------------------------
// Prober lifecycle
// ---------------------------------------------------------------------------

function readProbeLastSentMs(): number | null {
  try {
    const raw = readFileSync(PROBE_LAST_SENT_FILE, 'utf-8').trim()
    const ts = new Date(raw).getTime()
    return Number.isFinite(ts) ? ts : null
  } catch {
    return null
  }
}

// W4: read once at startup; subsequent calls return the cached value.
// W1: enforce a minimum floor of 30 000 ms to prevent inadvertent DoS.
function readProbeIntervalMs(): number {
  if (_cachedProbeIntervalMs !== null) return _cachedProbeIntervalMs
  const env = readEnvFile(['PROBE_INTERVAL_MS'])
  const raw = env['PROBE_INTERVAL_MS']
  const DEFAULT_MS = 180_000 // 3 minutes
  let parsed = DEFAULT_MS
  if (raw) {
    const n = parseInt(raw, 10)
    if (Number.isFinite(n) && n > 0) parsed = n
  }
  // W1: minimum 30 s floor
  _cachedProbeIntervalMs = Math.max(parsed, 30_000)
  return _cachedProbeIntervalMs
}

// W4: read once at startup; subsequent calls return the cached value.
function readAllowedChatId(): string | null {
  if (_cachedAllowedChatId !== undefined) return _cachedAllowedChatId
  // Goes through the shared resolver so the installer placeholder "0" counts
  // as "not set" here too, and so a wizard install falls back to the paired
  // channel instead of probing a chat that cannot exist.
  const env = readEnvFile(['ALLOWED_CHAT_ID'])
  _cachedAllowedChatId = resolveOwnerChatId(undefined, env['ALLOWED_CHAT_ID'] ?? null)
  return _cachedAllowedChatId
}

function spawnProber(): void {
  if (!existsSync(SESSION_FILE)) {
    // W3: one-shot warning — log only on first occurrence, debug on subsequent ticks.
    if (!_warnedSessionMissing) {
      logger.warn('Inbound prober: store/.watchdog-userbot.session missing -- prober is a no-op until the session is created')
      _warnedSessionMissing = true
    } else {
      logger.debug('Inbound prober: session still missing -- skipping')
    }
    return
  }
  // Reset session-missing flag if the file now exists.
  _warnedSessionMissing = false

  const allowedChatId = readAllowedChatId()
  if (!allowedChatId) {
    // CW addendum D3: if ALLOWED_CHAT_ID is absent/empty, log warning and skip.
    // W3: one-shot via logger.warn; subsequent ticks use logger.debug.
    if (!_warnedChatIdAbsent) {
      logger.warn('inbound-prober: ALLOWED_CHAT_ID absent in .env -- prober skipped')
      _warnedChatIdAbsent = true
    } else {
      logger.debug('inbound-prober: ALLOWED_CHAT_ID still absent -- skipping')
    }
    return
  }
  // Reset chat-id-absent flag if the value is now present.
  _warnedChatIdAbsent = false

  if (!existsSync(VENV_PYTHON)) {
    logger.warn('Inbound prober: .watchdog-venv/bin/python3 not found -- prober skipped')
    return
  }

  if (!existsSync(PROBER_SCRIPT)) {
    logger.warn('Inbound prober: scripts/watchdog-inbound-prober.py not found -- prober skipped')
    return
  }

  if (proberProcess && proberProcess.exitCode === null) {
    // Still running — do not double-spawn.
    return
  }

  logger.info('Inbound prober: spawning watchdog-inbound-prober.py')
  try {
    proberProcess = spawn(VENV_PYTHON, [PROBER_SCRIPT], {
      detached: false,
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    proberProcess.stdout?.on('data', (data: Buffer) => {
      // Do not log stdout content as it may carry debug info with timing data.
      const text = data.toString('utf-8').trim()
      if (text) logger.debug({ prober: 'stdout' }, text)
    })
    proberProcess.stderr?.on('data', (data: Buffer) => {
      const text = data.toString('utf-8').trim()
      if (text) logger.warn({ prober: 'stderr' }, text)
    })
    proberProcess.on('exit', (code) => {
      logger.info({ code }, 'Inbound prober process exited')
      proberProcess = null
    })
    proberProcess.on('error', (err) => {
      logger.error({ err }, 'Inbound prober spawn error')
      proberProcess = null
    })
  } catch (err) {
    logger.error({ err }, 'Inbound prober: failed to spawn')
    proberProcess = null
  }
}

// N5: renamed doInboundProbeCheck → checkInboundProbeDeafness (match check* convention)
function checkInboundProbeDeafness(probeTimeoutMs: number): void {
  // Session file absent — safe no-op.
  if (!existsSync(SESSION_FILE)) return

  const markerTs = readProbeLastSentMs()
  if (markerTs === null) {
    // No probe has been sent yet — nothing to check.
    return
  }

  const nowMs = Date.now()
  const lastIngestionTs = readLastIngestionTimestampAcross(mainTranscriptDirs())

  const needsRespawn = shouldTriggerDeafnessRespawn({
    markerTs,
    lastIngestionTs,
    probeTimeoutMs,
    nowMs,
  })

  if (!needsRespawn) return

  // Lazy import to avoid circular dependency at module load time.
  // B2: also import lastMainRespawnAt to enforce cross-path grace (an inbound-probe
  // respawn must suppress the keepalive path and vice-versa).
  import('./channel-monitor.js').then(({ hardRestartMarveenChannels, lastMainRespawnAt }) => {
    const nowAfterImport = Date.now()

    // B2 fix: cross-path grace — skip if EITHER path has respawned recently.
    const msSinceCrossPathRespawn = nowAfterImport - lastMainRespawnAt()
    if (lastMainRespawnAt() > 0 && msSinceCrossPathRespawn < RESPAWN_GRACE_MS) {
      logger.info({ msSinceCrossPathRespawn }, 'Inbound deafness detected but within cross-path respawn grace -- skipping')
      return
    }

    // Inbound-path self-rate-cap (covers the period before marveenLastHardRestart
    // is set by the async call completing).
    if (lastInboundRespawn && nowAfterImport - lastInboundRespawn < RESPAWN_GRACE_MS) {
      logger.info({ msSinceLastRespawn: nowAfterImport - lastInboundRespawn }, 'Inbound deafness detected but within respawn grace -- skipping')
      return
    }

    logger.warn({ markerTs, lastIngestionTs, nowMs }, 'Inbound deafness detected -- triggering respawn')

    // hardRestartMarveenChannels sets marveenLastHardRestart on success, which
    // automatically suppresses the keepalive path for KEEPALIVE_RESPAWN_GRACE_MS.
    const result = hardRestartMarveenChannels()
    if (result.ok) {
      lastInboundRespawn = nowAfterImport
      logger.warn('Inbound deafness respawn triggered successfully')
    } else {
      logger.error({ error: result.error }, 'Inbound deafness respawn failed')
    }
  }).catch((err) => {
    logger.error({ err }, 'Inbound probe: failed to import channel-monitor for respawn')
  })
}

/**
 * Start the inbound-probe background loop.
 *
 * Called once during server startup (immediately after startChannelPluginMonitor).
 * A failure here must never crash the server — wrapped in try/catch at call site.
 *
 * The prober is a safe no-op when:
 *   - store/.watchdog-userbot.session is missing (account not set up)
 *   - ALLOWED_CHAT_ID is absent in .env
 *   - auth fails in the Python prober (exits 0 with warning)
 *
 * MANUAL GATE: the operator must run /telegram:access in the main channels session to
 * allowlist the prober account before messages will
 * be delivered. Until then the prober sends messages that are silently
 * dropped by the allowlist, and no respawn is triggered (the probe-last-sent
 * file won't be written).
 */
export function startInboundProber(): void {
  const probeIntervalMs = readProbeIntervalMs()

  // Spawn the Python prober immediately (it manages its own send loop).
  spawnProber()

  // TS-side check loop: runs at the same interval as the prober's send loop.
  // Each tick: re-spawn the prober if it died, then check the transcript.
  setInterval(() => {
    try {
      spawnProber()
      checkInboundProbeDeafness(probeIntervalMs * PROBE_TIMEOUT_MULTIPLIER)
    } catch (err) {
      logger.error({ err }, 'Inbound probe check tick failed')
    }
  }, probeIntervalMs)

  logger.info({ probeIntervalMs }, 'Inbound prober started')
}
