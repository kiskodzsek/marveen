#!/usr/bin/env node
// fleet-rules-stamp (FLEETRULES1013, Viktor F2): records which root CLAUDE.md
// the install-local fleet rules (store/fleet-rules.md) were synced from.
//
// ensureFleetRulesSection() excludes the root CLAUDE.md from an opted-in agent
// ONLY while the root's sha256 equals the stamp in the rules file's leading
// comment. Any edit of the root therefore puts the root load back for every
// opted-in agent, until someone carries the new rule into store/fleet-rules.md
// (or decides it is main-agent-only) and re-stamps. That is the point: a rule
// added to the root can never silently miss the agents that stopped loading it.
//
// Stamping also keeps a copy of the root as it was (store/fleet-rules.root-at-stamp.md),
// so the next re-sync can see exactly what changed:
//   diff store/fleet-rules.root-at-stamp.md CLAUDE.md
//
// Usage (from the install root, or pass --root):
//   node scripts/fleet-rules-stamp.mjs            stamp the current root
//   node scripts/fleet-rules-stamp.mjs --check    exit 0 if the stamp is current, 1 if not
// Options: --root <dir> (default: the repo this script lives in), --rules <file>
// (default: <root>/store/fleet-rules.md).
//
// Stamping is a statement that the rules file has been reviewed against the
// current root. It does not check that by itself.
import { readFileSync, writeFileSync, renameSync, statSync, chmodSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const STAMP_RE = /synced-from-root-sha256=[0-9a-f]{64}/
const LEAD_RE = /^\s*<!--[\s\S]*?-->/

function arg(name) {
  const i = process.argv.indexOf(name)
  return i > -1 ? process.argv[i + 1] : undefined
}

const root = resolve(arg('--root') ?? join(dirname(fileURLToPath(import.meta.url)), '..'))
const rulesPath = resolve(arg('--rules') ?? join(root, 'store', 'fleet-rules.md'))
const snapshotPath = join(dirname(rulesPath), 'fleet-rules.root-at-stamp.md')
const rootPath = join(root, 'CLAUDE.md')

let rootBytes, rules
try { rootBytes = readFileSync(rootPath) } catch { console.error(`fleet-rules-stamp: cannot read ${rootPath}`); process.exit(2) }
try { rules = readFileSync(rulesPath, 'utf-8') } catch { console.error(`fleet-rules-stamp: cannot read ${rulesPath}`); process.exit(2) }

const sha = createHash('sha256').update(rootBytes).digest('hex')
const lead = rules.match(LEAD_RE)
const current = lead?.[0].match(STAMP_RE)?.[0].split('=')[1] ?? null

if (process.argv.includes('--check')) {
  if (current === sha) {
    console.log(`OK: ${rulesPath} is stamped with the current root (${sha.slice(0, 12)})`)
    process.exit(0)
  }
  console.log(current === null
    ? `STALE: ${rulesPath} has no stamp -- the root CLAUDE.md stays loaded for opted-in agents`
    : `STALE: root CLAUDE.md changed since the stamp (${current.slice(0, 12)} -> ${sha.slice(0, 12)}); see: diff ${snapshotPath} ${rootPath}`)
  process.exit(1)
}

const line = `synced-from-root-sha256=${sha}`
let next
if (lead && STAMP_RE.test(lead[0])) next = rules.replace(LEAD_RE, (c) => c.replace(STAMP_RE, line))
else if (lead) next = rules.replace(LEAD_RE, (c) => c.replace(/-->$/, `  ${line}\n-->`))
else next = `<!-- ${line} -->\n\n${rules}`

function writeAtomic(path, content, mode) {
  const tmp = `${path}.tmp-${process.pid}`
  writeFileSync(tmp, content)
  if (mode !== undefined) chmodSync(tmp, mode)
  renameSync(tmp, path)
}
writeAtomic(rulesPath, next, statSync(rulesPath).mode & 0o777)
writeAtomic(snapshotPath, rootBytes, 0o600)
console.log(`stamped ${rulesPath} with root ${sha.slice(0, 12)}; snapshot: ${snapshotPath}`)
