#!/usr/bin/env node
// PreToolUse hook: no agent opens an unscreened or quarantined image (IMAGESAFETY1020).
//
// scripts/image-safety/check.py screens every generated image before an agent may
// see it; a flagged one lands in _quarantine/ with mode 000. Sub-agents get the
// rule inside scripts/self-pace-gate.mjs. The MAIN agent does not run that gate
// (it is wired only for sub-agents), yet it is the one that receives the
// quarantine notices -- so this file runs the same decision for it (Viktor review
// P2 on card 1a4fe725, Klodel 9186). Wired in the repo-shipped
// .claude/settings.json. One decision function, screeningDecision(), lives in
// self-pace-gate.mjs; this file only adapts it to a hook.
//
// Not a security boundary: every agent runs as the same uid. It stops an agent
// from opening such a file by accident, which would send it to the model provider.

import { readFileSync, realpathSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { screeningDecision, QUARANTINE_GATE_MSG } from '../self-pace-gate.mjs'

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
  if (screeningDecision(payload?.tool_name, payload?.tool_input).deny) deny(QUARANTINE_GATE_MSG)
  allow()
}
