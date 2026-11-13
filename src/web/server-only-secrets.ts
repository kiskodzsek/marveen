// Vault ids read in-process only, never served, bound, written or deleted over HTTP:
// the approval bot's token (APPROVALBOT1013, Viktor 2384 M2) and the Billingo issue
// signing key (BILLINGOISSUE1104, Viktor 26241), and the gate-config signing key (GATECONFIG1113,
// Viktor 40668 C6). Only the dashboard process and its own CLIs (scripts/billingo-issue-key.ts,
// scripts/gate-config-key.ts) touch them.
import { approvalBotVaultId } from './approval-bot.js'
import { BILLINGO_ISSUE_KEY_VAULT_ID } from './billingo-issue-approval.js'
import { GATE_CONFIG_KEY_VAULT_ID } from './gate-config-approval.js'

export function isServerOnlyVaultId(id: string): boolean {
  const t = id.trim()
  return t === approvalBotVaultId() || t === BILLINGO_ISSUE_KEY_VAULT_ID || t === GATE_CONFIG_KEY_VAULT_ID
}
