#!/usr/bin/env node
// PreToolUse hook for the ms365 MCP tool download-bytes-to-file.
//
// The tool (@softeria/ms-365-mcp-server, stdio mode) streams Graph bytes to
// an absolute outputPath with open(path, 'wx', 0600): it never overwrites and
// does not follow a symlink at the target name. What it does NOT limit is the
// directory, and the bytes are third-party data (a mail attachment). Without
// this gate one injected call could drop a new file anywhere the user can
// write -- ~/Library/LaunchAgents, ~/.claude/skills, a hooks dir -- and have
// it picked up later as code or instructions.
//
// So this gate allows exactly one shape:
//   - target: a mail FILE attachment's bytes,
//       /me|/users/<id>[/mailFolders/<id>]/messages/<id>/attachments/<id>/$value
//     (no query string, no other Graph resource);
//   - outputPath: an absolute path whose parent directory, after realpath,
//     IS the drop directory (not a subdirectory, not a sibling), and whose
//     file name is plain (no leading dot, no control characters) and ends in
//     an allowed data extension.
// The drop directory is MS365_DOWNLOAD_DIR, default <repo>/store/mail-downloads,
// and must already exist. Moving the file somewhere else afterwards is a
// separate, deliberate act.
//
// One more shape, closed by default (Klodel 11031, Viktor 10933: a message
// body must not enter the model context): a whole message as MIME,
//   /me/messages/<id>/$value
// into MS365_MIME_DIR (default <repo>/agents/pulzus/secure) as [A-Za-z0-9._-]+.eml,
// and only while the one-shot marker MS365_MIME_ONCE (default
// <repo>/store/ms365-mime-once) exists and is younger than MIME_ONCE_MAX_AGE_MS.
// Allowing consumes the marker (one marker = one download, Viktor 11075) and
// appends a timestamp-only line to MS365_MIME_LOG (default
// <repo>/store/ms365-mime-gate.log); if either fails, the call is denied.
// The marker bounds the window, not the authority: whoever may call the tool
// may create it. The sender and the link are checked afterwards by
// the extractor (agents/pulzus/scripts/marabel-admin/mimelink.py), which reads
// the file, deletes it, and prints nothing secret from the mail.
//
// Fail-closed: unreadable input or an internal error denies (exit 2).

import { appendFileSync, readFileSync, realpathSync, statSync, unlinkSync } from 'node:fs'
import { basename, dirname, isAbsolute, join, normalize } from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
export const DEFAULT_DROP_DIR = join(REPO_ROOT, 'store', 'mail-downloads')
export const DEFAULT_MIME_DIR = join(REPO_ROOT, 'agents', 'pulzus', 'secure')
export const DEFAULT_MIME_ONCE = join(REPO_ROOT, 'store', 'ms365-mime-once')
export const DEFAULT_MIME_LOG = join(REPO_ROOT, 'store', 'ms365-mime-gate.log')
export const MIME_ONCE_MAX_AGE_MS = 60 * 60 * 1000
const MIME_NAME = /^[A-Za-z0-9._-]+\.eml$/

// A segment is anything but a separator, query/fragment or whitespace, and
// never `.` or `..`: a dot segment would let the target climb out of the
// attachment shape once the URL is resolved.
const SEG = '(?!\\.{1,2}(?:/|$))[^/?#\\s]+'
const ATTACHMENT_TARGET = new RegExp(
  `^/(?:me|users/${SEG})(?:/mailFolders/${SEG})?/messages/${SEG}/attachments/${SEG}/\\$value$`,
)
// Own mailbox only: no /users/<id>, no mailFolders, no query string.
const MIME_TARGET = new RegExp(`^/me/messages/${SEG}/\\$value$`)

/**
 * Decide on one download-bytes-to-file call. Returns { deny, reason }.
 * Pure apart from realpath/stat on the drop directory and the parent dir.
 */
// The bytes are third-party data, so they only land as inert data files. An
// allowlist rather than a list of risky types: archives, macro formats and any
// executable type macOS adds later stay out without anyone updating a list.
// Not here on purpose (Viktor 6359): xls (old BIFF can carry VBA macros),
// docm/xlsm (macros), html/svg (script). xml stays for NAV e-invoices.
export const ALLOWED_EXTENSIONS = ['pdf', 'xml', 'csv', 'xlsx', 'docx', 'png', 'jpg', 'jpeg', 'heic', 'txt']
// Anchored on the LAST extension, any case. A name with no extension, or one
// ending in a dot or a space ("x.pdf.", "x.pdf "), does not match.
const ALLOWED_EXTENSION = new RegExp(`\\.(?:${ALLOWED_EXTENSIONS.join('|')})$`, 'i')

export function gateDecision(
  toolInput,
  dropDir = process.env.MS365_DOWNLOAD_DIR || DEFAULT_DROP_DIR,
  { mimeDir = process.env.MS365_MIME_DIR || DEFAULT_MIME_DIR, mimeOnce = process.env.MS365_MIME_ONCE || DEFAULT_MIME_ONCE, now = Date.now() } = {},
) {
  const target = toolInput?.target
  const outputPath = toolInput?.outputPath
  if (typeof target === 'string' && MIME_TARGET.test(target)) return mimeDecision(outputPath, mimeDir, mimeOnce, now)
  if (typeof target !== 'string' || !ATTACHMENT_TARGET.test(target)) {
    return {
      deny: true,
      reason:
        'download-bytes-to-file: only a mail attachment target is allowed ' +
        '(/me/messages/<id>/attachments/<id>/$value, no query string).',
    }
  }
  const pathCheck = outputPathDecision(outputPath, dropDir)
  if (pathCheck.deny) return pathCheck
  if (!ALLOWED_EXTENSION.test(basename(outputPath))) {
    return {
      deny: true,
      reason:
        `download-bytes-to-file: file type not allowed: ${basename(outputPath)}. ` +
        `Allowed types: ${ALLOWED_EXTENSIONS.join(', ')}; if another type is needed, ask Kernel/Viktor.`,
    }
  }
  return { deny: false, reason: '' }
}

function mimeDecision(outputPath, mimeDir, mimeOnce, now) {
  let age
  try {
    const st = statSync(mimeOnce)
    if (!st.isFile()) throw new Error('not a file')
    age = now - st.mtimeMs
  } catch {
    return {
      deny: true,
      reason: 'download-bytes-to-file: a whole message ($value) is closed; it opens only for one confirmation-link extraction (marker missing).',
    }
  }
  // A few seconds of future mtime is filesystem timestamp precision, not a forged marker.
  if (age < -5000 || age > MIME_ONCE_MAX_AGE_MS) {
    return { deny: true, reason: 'download-bytes-to-file: the one-shot MIME marker is older than 60 minutes, recreate it deliberately.' }
  }
  const pathCheck = outputPathDecision(outputPath, mimeDir)
  if (pathCheck.deny) return pathCheck
  if (!MIME_NAME.test(basename(outputPath))) {
    return { deny: true, reason: 'download-bytes-to-file: a whole message may only be saved as [A-Za-z0-9._-]+.eml.' }
  }
  return { deny: false, reason: '', consumeMarker: mimeOnce }
}

/**
 * Use up the one-shot marker and log the allow. Returns a deny decision if
 * either step fails, so a marker can never serve two downloads.
 */
export function consumeMarker(mimeOnce, log = process.env.MS365_MIME_LOG || DEFAULT_MIME_LOG, now = new Date()) {
  try {
    unlinkSync(mimeOnce)
  } catch {
    return { deny: true, reason: 'download-bytes-to-file: the one-shot MIME marker could not be consumed, denying.' }
  }
  try {
    appendFileSync(log, `${now.toISOString()} ms365-mime-once consumed: one whole-message download allowed\n`, { mode: 0o600 })
  } catch {
    return { deny: true, reason: 'download-bytes-to-file: could not write the MIME gate log, denying (the marker is used up).' }
  }
  return { deny: false, reason: '' }
}

// outputPath must be absolute, normalised, plainly named, and sit directly in dir.
function outputPathDecision(outputPath, dir) {
  if (typeof outputPath !== 'string' || !isAbsolute(outputPath) || outputPath.includes('\0')) {
    return { deny: true, reason: 'download-bytes-to-file: outputPath must be an absolute path.' }
  }
  if (normalize(outputPath) !== outputPath || outputPath.endsWith('/')) {
    return { deny: true, reason: 'download-bytes-to-file: outputPath must be normalised (no "..", ".", "//" or trailing "/").' }
  }
  const name = basename(outputPath)
  // eslint-disable-next-line no-control-regex
  if (!name || name.startsWith('.') || /[\u0000-\u001f\u007f\u200e\u200f\u202a-\u202e\u2066-\u2069]/.test(name)) {
    return {
      deny: true,
      reason: 'download-bytes-to-file: the file name must be plain (no leading dot, no control or bidi characters).',
    }
  }
  let drop
  try {
    drop = realpathSync(dir)
    if (!statSync(drop).isDirectory()) throw new Error('not a directory')
  } catch {
    return { deny: true, reason: `download-bytes-to-file: the drop directory does not exist, create it first: ${dir}` }
  }
  let parent
  try {
    parent = realpathSync(dirname(outputPath))
  } catch {
    return { deny: true, reason: `download-bytes-to-file: the parent directory does not exist: ${dirname(outputPath)}` }
  }
  if (parent !== drop) {
    return {
      deny: true,
      reason:
        `download-bytes-to-file: refusing to write outside the drop directory.\n` +
        `  requested: ${join(parent, name)}\n  allowed:   ${drop}/<name>\n` +
        'Save into the drop directory, then move the file deliberately.',
    }
  }
  return { deny: false, reason: '' }
}

function main() {
  let decision
  try {
    const payload = JSON.parse(readFileSync(0, 'utf-8'))
    decision = gateDecision(payload?.tool_input)
    if (!decision.deny && decision.consumeMarker) decision = consumeMarker(decision.consumeMarker)
  } catch (e) {
    decision = { deny: true, reason: `ms365-download-gate: internal error, denying: ${e?.message ?? e}` }
  }
  if (decision.deny) {
    process.stderr.write(decision.reason + '\n')
    process.exit(2)
  }
  process.exit(0)
}

if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) main()
