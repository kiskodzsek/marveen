import { openSync, fstatSync, readSync, closeSync, constants } from 'node:fs'

// The ensure* migrations read files a sub-agent can write (its settings.json, its CLAUDE.md, its quarantine-reader
// copy), synchronously, on the dashboard's main thread, at every spawn and at every dashboard start. A plain
// readFileSync on such a path blocks the whole dashboard when the agent puts a FIFO there (mkfifo: the read waits for
// a writer that never comes), and exhausts memory when it puts a symlink to /dev/zero there (Viktor 42983 MEDIUM 2,
// measured: ensureKeychainReadGate on a FIFO settings.json still blocked after 25 s).
//
// readRegularFileSync is the drop-in replacement for readFileSync(path, 'utf-8') on those paths:
//   - the file is opened with O_NONBLOCK, so opening a FIFO returns at once instead of waiting for a writer;
//   - the OPEN descriptor is checked (fstat), not the path, so the file cannot be swapped between check and read;
//   - not a regular file (FIFO, character or block device, socket, directory) -> throws UnsafeFileError;
//   - more than maxBytes -> throws UnsafeFileError, and never more than maxBytes + 1 bytes are read, even when the
//     file grows after the fstat;
//   - a missing file throws ENOENT, exactly as readFileSync does, so every caller's existing catch keeps its meaning.
// The text is decoded as UTF-8 with a leading BOM kept, the same as readFileSync(path, 'utf-8').
export const SAFE_READ_MAX_BYTES = 1_000_000

export class UnsafeFileError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'UnsafeFileError'
  }
}

const CHUNK = 64 * 1024

// Claude Code's own state file (.claude.json) grows with every project it has seen (153 KB measured on
// 2026-11-15); refusing it would skip the onboarding / trust stamps, so its readers get a wider cap.
export const CLAUDE_JSON_MAX_BYTES = 16_000_000

export function readRegularFileSync(path: string, maxBytes: number = SAFE_READ_MAX_BYTES): string {
  const fd = openSync(path, constants.O_RDONLY | constants.O_NONBLOCK)
  try {
    const st = fstatSync(fd)
    if (!st.isFile()) throw new UnsafeFileError(`not a regular file: ${path}`)
    if (st.size > maxBytes) throw new UnsafeFileError(`over ${maxBytes} bytes: ${path}`)
    const chunks: Buffer[] = []
    let total = 0
    for (;;) {
      const want = Math.min(CHUNK, maxBytes + 1 - total)
      if (want <= 0) break
      const buf = Buffer.allocUnsafe(want)
      const n = readSync(fd, buf, 0, want, null)
      if (n === 0) break
      chunks.push(n === want ? buf : buf.subarray(0, n))
      total += n
    }
    if (total > maxBytes) throw new UnsafeFileError(`over ${maxBytes} bytes: ${path}`)
    return Buffer.concat(chunks, total).toString('utf-8')
  } finally {
    closeSync(fd)
  }
}
