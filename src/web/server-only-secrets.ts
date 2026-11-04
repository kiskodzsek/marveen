// Vault ids read in-process only, never served, bound, written or deleted over HTTP:
// the approval bot's token (APPROVALBOT1013, Viktor 2384 M2) and the Billingo issue
// signing key (BILLINGOISSUE1104, Viktor 26241). Only the dashboard process and its
// own CLI (scripts/billingo-issue-key.ts) touch them.
import { approvalBotVaultId } from './approval-bot.js'
import { BILLINGO_ISSUE_KEY_VAULT_ID } from './billingo-issue-approval.js'

export function isServerOnlyVaultId(id: string): boolean {
  const t = id.trim()
  return t === approvalBotVaultId() || t === BILLINGO_ISSUE_KEY_VAULT_ID
}
