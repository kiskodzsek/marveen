# Billingo invoice approval, signed for the egress gate (BILLINGOISSUE1104)

Card 05980d05, Patrik TG 767/770/776, Viktor 26223 (anchor A: signed approval, A1-A5, K1).
The Billingo connector (kiskodzsek/mcp-connectors, `issue_own_draft`) can issue one of our own
drafts as an invoice only with Patrik's approval of exactly that invoice; the connectors' egress
gate (`ops/gate/mcp-gate.mjs` there) verifies it. This side asks, renders, and signs.

## Flow
1. The agent calls the connector's `issue_preview` and POSTs its `approval_request` to
   `/api/approvals`: `category: "billingo_issue"`, `action_payload` = the approval_request as a JSON
   string (`{category, company, draft_id, content_hash, body}`), `content_hash` = its content_hash,
   `action_description` = a short note (shown labelled as the agent's, never as the amount).
2. The server checks the body and recomputes `sha256(canonicalJson({company, draft_id, body}))`;
   a mismatch is a 400 and nothing is stored. The owner's message is rendered from the body by
   `src/web/billingo-issue-approval.ts`: company, draft id, partner id, items, net/VAT/gross,
   dates, check code (K1).
3. Only a press on the approval bot's button (`resolution_channel = 'approval_bot'`,
   `resolved_by = 'telegram_button'`) signs, at the press (A1):
   `billingo_issue_v1:<kid>:<approval_id>:<company>:<draft_id>:<content_hash>:<resolved_at>`, Ed25519.
   The value is stored once in `approvals.issue_signature` (`setApprovalIssueSignature` repeats
   every condition in its WHERE). A text reply or the dashboard resolves the row but never signs,
   so the gate refuses the issue. A failed signature alerts the owner.
4. The agent reads `GET /api/approvals/<id>/signature` (`{approval}`; 409 until signed) and
   passes it to `issue_own_draft`. The gate checks the kid, the signature, the company, the
   draft, the hash of the body it forwards, the age (24 h), reads the draft back from Billingo,
   and spends the approval once.

## The key
`npx tsx scripts/billingo-issue-key.ts generate` (once, on the dashboard host): an Ed25519 key
straight into the Vault (`billingo-issue-signing-key`, never printed); it prints only
`{"kid","key"}` for `ops/gate/billingo-issue.json` in mcp-connectors. `show` prints it again.
The Vault id is server-only (`isServerOnlyVaultId`, routes/connectors.ts): never served, never
bound. Replacing the key needs the gate's pin changed too.

## Limit (stated, not hidden)
As with the approval bot itself: whoever can write the dashboard code or the Vault on this UID
can sign. The TOTP-backed approval of 9a2925a7 step 2 closes it. An issued invoice cannot be
withdrawn on this path (storno is not a path); the button text says so.

Tests: `src/__tests__/billingo-issue-approval.test.ts` (shared hash vector with the connector and
the gate, rendering, A1 refusals, the press, the route).
