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
//     file name is plain (no leading dot, no control characters).
// The drop directory is MS365_DOWNLOAD_DIR, default <repo>/store/mail-downloads,
// and must already exist. Moving the file somewhere else afterwards is a
// separate, deliberate act.
//
// Fail-closed: unreadable input or an internal error denies (exit 2).

import { readFileSync, realpathSync, statSync } from 'node:fs'
import { basename, dirname, isAbsolute, join, normalize } from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
export const DEFAULT_DROP_DIR = join(REPO_ROOT, 'store', 'mail-downloads')

// A segment is anything but a separator, query/fragment or whitespace, and
// never `.` or `..`: a dot segment would let the target climb out of the
// attachment shape once the URL is resolved.
const SEG = '(?!\\.{1,2}(?:/|$))[^/?#\\s]+'
const ATTACHMENT_TARGET = new RegExp(
  `^/(?:me|users/${SEG})(?:/mailFolders/${SEG})?/messages/${SEG}/attachments/${SEG}/\\$value$`,
)

/**
 * Decide on one download-bytes-to-file call. Returns { deny, reason }.
 * Pure apart from realpath/stat on the drop directory and the parent dir.
 */
// File types macOS (or a shell) would run or open as an action on a double
// click. The bytes are third-party data, so they only land as inert files.
const RISKY_EXTENSION =
  /\.(?:app|command|tool|terminal|sh|bash|zsh|csh|ksh|fish|py|pl|rb|js|mjs|cjs|jxa|scpt|scptd|applescript|workflow|action|pkg|mpkg|dmg|webloc|inetloc|fileloc|url|plist|mobileconfig|jar|dylib|so|kext|bundle|prefpane|saver)$/i

export function gateDecision(toolInput, dropDir = process.env.MS365_DOWNLOAD_DIR || DEFAULT_DROP_DIR) {
  const target = toolInput?.target
  const outputPath = toolInput?.outputPath
  if (typeof target !== 'string' || !ATTACHMENT_TARGET.test(target)) {
    return {
      deny: true,
      reason:
        'download-bytes-to-file: only a mail attachment target is allowed ' +
        '(/me/messages/<id>/attachments/<id>/$value, no query string).',
    }
  }
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
    drop = realpathSync(dropDir)
    if (!statSync(drop).isDirectory()) throw new Error('not a directory')
  } catch {
    return { deny: true, reason: `download-bytes-to-file: the drop directory does not exist, create it first: ${dropDir}` }
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
  if (RISKY_EXTENSION.test(name)) {
    return {
      deny: true,
      reason: `download-bytes-to-file: refusing an executable or auto-opening file type: ${name}. Save it under a data extension (e.g. .pdf, .bin).`,
    }
  }
  return { deny: false, reason: '' }
}

function main() {
  let decision
  try {
    const payload = JSON.parse(readFileSync(0, 'utf-8'))
    decision = gateDecision(payload?.tool_input)
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
