// Card 91d9911e (DREAM 11-19, measured 2026-11-18 20:12 - 11-19 00:42, Kernel 47551):
// the machine had no network for four and a half hours, and 60 messages reached the
// main agent, all symptoms of that one outage; 49 of them were scheduler notices
// ("pane N perce foglalt", "N perce várakozik"): no agent could reach the API, so
// every injected task kept its pane busy past the threshold.
//
// While the Marabel watchdog's net-down marker is fresh, the scheduler's notices
// and their owner escalations are held instead of sent (the one-shot stamps are
// still set, so nothing fires in a burst when the network returns), and on the
// first sweep after the marker is gone the main agent gets ONE summary: how long,
// which tasks, how many.
import { closeSync, constants, fstatSync, openSync, readSync, renameSync, unlinkSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { PROJECT_ROOT } from '../config.js'

/** Written by ops/marabel-watchdog.sh on every run that finds no network ("<since> <last>"),
 *  removed on the first run that does. */
export const NETDOWN_MARKER_PATH = join(PROJECT_ROOT, 'store', 'marabel-watchdog-netdown')

/**
 * How old the marker may be and still count. The watchdog runs every 300 s
 * (hu.myshp.marabel-watchdog.plist StartInterval) and rewrites the marker on each
 * net-down run, so three missed runs mean the watchdog itself stopped: a marker
 * left behind then must not silence the scheduler for good.
 */
export const NETDOWN_FRESH_MS = 3 * 300_000

/**
 * Pure: whether a marker with this content and mtime means "the network is down
 * now". Returns the outage start in ms (the marker's first field, epoch seconds),
 * or the mtime when that field is unreadable; null when the marker is stale or
 * from the future.
 */
export function netdownSinceFromMarker(text: string, mtimeMs: number, nowMs: number): number | null {
  if (!Number.isFinite(mtimeMs) || mtimeMs > nowMs + 60_000 || nowMs - mtimeMs > NETDOWN_FRESH_MS) return null
  const first = text.trim().split(/\s+/)[0] ?? ''
  if (/^\d{1,12}$/.test(first)) {
    const sinceMs = Number(first) * 1000
    if (sinceMs <= nowMs) return sinceMs
  }
  return mtimeMs
}

/** The outage start (ms) when the net-down marker is present and fresh, else null. Never throws. */
export function readNetdownSince(nowMs: number, path: string = NETDOWN_MARKER_PATH): number | null {
  // Viktor 91d9911e r1: open first, then fstat the same fd. A stat-then-read let a FIFO swapped in between block
  // the dashboard's event loop (measured); O_NONBLOCK keeps a FIFO open from waiting, O_NOFOLLOW refuses a link.
  let fd: number | null = null
  try {
    fd = openSync(path, constants.O_RDONLY | constants.O_NONBLOCK | constants.O_NOFOLLOW)
    const st = fstatSync(fd)
    if (!st.isFile() || st.size > 4096) return null
    const buf = Buffer.alloc(4096)
    const n = readSync(fd, buf, 0, buf.length, 0)
    return netdownSinceFromMarker(buf.toString('utf-8', 0, n), st.mtimeMs, nowMs)
  } catch {
    return null
  } finally {
    if (fd !== null) try { closeSync(fd) } catch { /* closed */ }
  }
}

export type HeldAlertKind = 'inflight' | 'inflight-owner' | 'retry' | 'retry-owner'

const KIND_LABEL: Record<HeldAlertKind, string> = {
  'inflight': 'pane-foglaltság',
  'inflight-owner': 'pane-foglaltság, üzemeltetői szint',
  'retry': 'várakozó újrapróba',
  'retry-owner': 'várakozó újrapróba, üzemeltetői szint',
}

/** Card 91d9911e r2 (Viktor 49109 LOW 2): the hold is persisted, so a dashboard restart inside an outage does
 *  not lose the alerts whose one-shot stamps the hold already claimed. Removed once the summary is delivered. */
export const NETDOWN_HOLD_PATH = join(PROJECT_ROOT, 'store', 'scheduler-netdown-hold.json')
const HOLD_MAX_BYTES = 256 * 1024
const HOLD_MAX_ROWS = 500
const HOLD_MAX_COUNT = 1_000_000
// A task or agent name read back from the file goes into a message to the main agent: names only.
const HOLD_NAME_RX = /^[\p{L}\p{N}_.@:-]{1,200}$/u
const HELD_KINDS: ReadonlyArray<HeldAlertKind> = ['inflight', 'inflight-owner', 'retry', 'retry-owner']

export interface PersistedHold {
  sinceMs: number
  rows: Array<{ task: string; agent: string; kinds: Partial<Record<HeldAlertKind, number>> }>
}

/** The alerts held back during one outage, folded into one summary at its end. */
export class NetdownAlertHold {
  private sinceMs: number | null = null
  private readonly counts = new Map<string, { task: string; agent: string; kinds: Map<HeldAlertKind, number> }>()

  /** Record one held alert. `sinceMs` is the outage start the marker gave. */
  hold(kind: HeldAlertKind, task: string, agent: string, sinceMs: number): void {
    if (this.sinceMs === null || sinceMs < this.sinceMs) this.sinceMs = sinceMs
    const key = `${task}@${agent}`
    const row = this.counts.get(key) ?? { task, agent, kinds: new Map<HeldAlertKind, number>() }
    row.kinds.set(kind, (row.kinds.get(kind) ?? 0) + 1)
    this.counts.set(key, row)
  }

  get size(): number {
    let n = 0
    for (const r of this.counts.values()) for (const c of r.kinds.values()) n += c
    return n
  }

  /**
   * The summary for the main agent; null when nothing was held. The hold is NOT
   * emptied: the caller clears it once the summary is delivered. `stillBusy`
   * (card 91d9911e r2, Viktor INFO 2) marks a task whose injection is still
   * tracked: its stamps were set by the hold, so no later alert of its own comes.
   */
  summary(nowMs: number, fmtClock: (ms: number) => string, stillBusy?: (task: string, agent: string) => boolean): string | null {
    if (this.counts.size === 0 || this.sinceMs === null) return null
    const minutes = Math.max(0, Math.round((nowMs - this.sinceMs) / 60_000))
    const rows = [...this.counts.values()].sort((a, b) => (a.agent + a.task).localeCompare(b.agent + b.task))
    const lines = rows.map((r) => {
      const kinds = [...r.kinds.entries()].map(([k, n]) => `${KIND_LABEL[k]} ${n}x`).join(', ')
      const busy = stillBusy?.(r.task, r.agent) ? ' -- MOST IS FOGLALT' : ''
      return `- "${r.task}" (${r.agent}): ${kinds}${busy}`
    })
    return [
      `[scheduler] Hálózat-kiesés alatt (${fmtClock(this.sinceMs)} - ${fmtClock(nowMs)}, ${minutes} perc, a Marabel-figyelő jelzője szerint) ${this.size} ütemező-riasztást tartottam vissza, ez az összesítőjük:`,
      ...lines,
      'Ezek a kiesés tünetei (az ágensek nem érték el az API-t). Egyenként utólag sem jönnek meg, az üzemeltetői szint sem; a "MOST IS FOGLALT" sort nézd meg.',
    ].join('\n')
  }

  clear(): void {
    this.counts.clear()
    this.sinceMs = null
  }

  /** The summary, and the hold emptied (summary + clear). */
  flush(nowMs: number, fmtClock: (ms: number) => string): string | null {
    const text = this.summary(nowMs, fmtClock)
    if (text !== null) this.clear()
    return text
  }

  toJSON(): PersistedHold {
    return {
      sinceMs: this.sinceMs ?? 0,
      rows: [...this.counts.values()].map((r) => ({ task: r.task, agent: r.agent, kinds: Object.fromEntries(r.kinds) })),
    }
  }

  /** A hold from the persisted shape; anything malformed is dropped (a garbage file gives an empty hold). */
  static fromJSON(v: unknown): NetdownAlertHold {
    const h = new NetdownAlertHold()
    if (!v || typeof v !== 'object' || Array.isArray(v)) return h
    const o = v as { sinceMs?: unknown; rows?: unknown }
    if (typeof o.sinceMs !== 'number' || !Number.isFinite(o.sinceMs) || o.sinceMs <= 0 || !Array.isArray(o.rows)) return h
    for (const row of o.rows.slice(0, HOLD_MAX_ROWS)) {
      if (!row || typeof row !== 'object' || Array.isArray(row)) continue
      const { task, agent, kinds } = row as { task?: unknown; agent?: unknown; kinds?: unknown }
      if (typeof task !== 'string' || typeof agent !== 'string' || !HOLD_NAME_RX.test(task) || !HOLD_NAME_RX.test(agent)) continue
      if (!kinds || typeof kinds !== 'object' || Array.isArray(kinds)) continue
      for (const k of HELD_KINDS) {
        if (!Object.prototype.hasOwnProperty.call(kinds, k)) continue
        const n = (kinds as Record<string, unknown>)[k]
        if (typeof n !== 'number' || !Number.isInteger(n) || n < 1 || n > HOLD_MAX_COUNT) continue
        // One hold() creates the row and the outage start; the stored count then replaces the 1.
        h.hold(k, task, agent, o.sinceMs)
        h.counts.get(`${task}@${agent}`)?.kinds.set(k, n)
      }
    }
    return h
  }
}

/** Card 91d9911e r2: the persisted hold (an empty hold when absent or malformed). Read like the marker: no link,
 *  no FIFO wait, a size cap. Never throws. */
export function loadNetdownHold(path: string = NETDOWN_HOLD_PATH): NetdownAlertHold {
  let fd: number | null = null
  try {
    fd = openSync(path, constants.O_RDONLY | constants.O_NONBLOCK | constants.O_NOFOLLOW)
    const st = fstatSync(fd)
    if (!st.isFile() || st.size > HOLD_MAX_BYTES) return new NetdownAlertHold()
    const buf = Buffer.alloc(st.size)
    const n = readSync(fd, buf, 0, buf.length, 0)
    return NetdownAlertHold.fromJSON(JSON.parse(buf.toString('utf-8', 0, n)))
  } catch {
    return new NetdownAlertHold()
  } finally {
    if (fd !== null) try { closeSync(fd) } catch { /* closed */ }
  }
}

/** Card 91d9911e r2: write the hold (an empty one removes the file). A fresh temp name created exclusively
 *  (a planted link is not followed), then rename. Returns false when the write failed. */
export function saveNetdownHold(hold: NetdownAlertHold, path: string = NETDOWN_HOLD_PATH): boolean {
  try {
    if (hold.size === 0) {
      try { unlinkSync(path) } catch (err) { if ((err as NodeJS.ErrnoException).code !== 'ENOENT') throw err }
      return true
    }
    const tmp = `${path}.${process.pid}.${Date.now()}.${Math.random().toString(36).slice(2)}.tmp`
    writeFileSync(tmp, JSON.stringify(hold.toJSON()), { flag: 'wx' })
    renameSync(tmp, path)
    return true
  } catch {
    return false
  }
}
