// BILLINGOISSUE1104 (card 05980d05, Patrik TG 767/770/776, Viktor 26223 A1, A2, K1):
// Patrik's approval of ONE Billingo invoice, signed for the egress gate of
// kiskodzsek/mcp-connectors (ops/gate/mcp-gate.mjs), which issues the invoice
// only with this signature.
//
// The request (POST /api/approvals, category billingo_issue) carries, as
// action_payload, the connector's issue_preview approval_request:
//   { category, company, draft_id, content_hash, body }
// The server checks the body's shape, recomputes content_hash from company,
// draft_id and body, and renders the owner's button text from the body with
// its OWN code (items, net/VAT/gross, dates, currency, draft id): the agent's
// free text is shown only as a labelled note, never as the amount (K1).
//
// After the owner's button press (resolution_channel 'approval_bot',
// resolved_by 'telegram_button', and nothing else) the server signs, with the
// Ed25519 key in the Vault (BILLINGO_ISSUE_KEY_VAULT_ID, never served):
//   billingo_issue_v1:<kid>:<approval_id>:<company>:<draft_id>:<content_hash>:<resolved_at>
// and stores the gate's header value on the row (A1, A2). A text reply, the
// dashboard PATCH or any other route never signs. The gate pins the public
// key by kid, checks the company, the draft, the hash it computes of the body
// it forwards, the age, and spends the approval once.
//
// What this does NOT stop, as in approval-bot.ts: whoever can write the
// dashboard code or the Vault on this UID can sign (Viktor 26223 A5; the
// TOTP-backed approval of 9a2925a7 step 2 closes it). An issued invoice cannot
// be withdrawn here (storno is not a path), so the owner sees this on the button.

import { createHash, createPrivateKey, createPublicKey, sign, type KeyObject } from 'node:crypto'
import { getSecret } from './vault.js'

export const BILLINGO_ISSUE_CATEGORY = 'billingo_issue'
/** Server-only Vault id (routes/connectors.ts refuses to serve or bind it). */
export const BILLINGO_ISSUE_KEY_VAULT_ID = 'billingo-issue-signing-key'
/** The signed message's prefix; the gate's APPROVAL_PURPOSE. */
export const BILLINGO_ISSUE_PURPOSE = 'billingo_issue_v1'
const COMPANY_NAMES: Record<string, string> = { myshp: 'mySHP Solutions Bt.', notramit: 'NotramIT Kft.' }
const DATE_RE = /^20\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/
const MAX_ITEMS = 50

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const posInt = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v > 0
const text = (v: unknown, max: number): v is string => typeof v === 'string' && v.trim().length > 0 && v.length <= max

/** JSON with object keys sorted at every level: the connector's and the gate's canonicalJson. */
export function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  if (isObj(value)) return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${canonicalJson(value[k])}`).join(',')}}`
  return JSON.stringify(value)
}

export function issueContentHash(company: string, draftId: number, body: unknown): string {
  return createHash('sha256').update(canonicalJson({ company, draft_id: draftId, body }), 'utf8').digest('hex')
}

export interface IssueItem { name: string; unit_price: number; unit_price_type: 'net' | 'gross'; quantity: number; unit: string; vat: string }
export interface IssueRequest {
  company: string
  draftId: number
  hash: string
  partnerId: number
  currency: string
  fulfillmentDate: string
  dueDate: string
  items: IssueItem[]
  body: Record<string, unknown>
}

/**
 * The action_payload of a billingo_issue request, checked, with the hash
 * recomputed here. `contentHash` is the row's content_hash: it must be the
 * same value, so the row the gate's approval names is this body's.
 */
export function parseIssueRequest(payload: string | null | undefined, contentHash: string | null | undefined): { request: IssueRequest } | { error: string } {
  let p: unknown
  try { p = JSON.parse(payload ?? '') } catch { return { error: 'action_payload must be the issue_preview approval_request (JSON)' } }
  if (!isObj(p)) return { error: 'action_payload is not a JSON object' }
  const keys = Object.keys(p).sort().join(',')
  if (keys !== 'body,category,company,content_hash,draft_id') return { error: 'action_payload must have exactly category, company, draft_id, content_hash, body' }
  if (p.category !== BILLINGO_ISSUE_CATEGORY) return { error: 'action_payload.category must be billingo_issue' }
  if (typeof p.company !== 'string' || !Object.hasOwn(COMPANY_NAMES, p.company)) return { error: 'company must be myshp or notramit' }
  if (!posInt(p.draft_id)) return { error: 'draft_id must be a positive integer' }
  const b = p.body
  if (!isObj(b)) return { error: 'body must be an object' }
  if (b.type !== 'invoice') return { error: 'body.type must be invoice' }
  if (!posInt(b.partner_id)) return { error: 'body.partner_id must be a positive integer' }
  if (typeof b.currency !== 'string' || !/^[A-Z]{3}$/.test(b.currency)) return { error: 'body.currency must be an ISO code' }
  if (typeof b.fulfillment_date !== 'string' || !DATE_RE.test(b.fulfillment_date) || typeof b.due_date !== 'string' || !DATE_RE.test(b.due_date)) {
    return { error: 'body dates must be YYYY-MM-DD' }
  }
  if (!Array.isArray(b.items) || b.items.length < 1 || b.items.length > MAX_ITEMS) return { error: 'body.items must be 1-50 items' }
  const items: IssueItem[] = []
  for (const i of b.items) {
    if (!isObj(i) || !text(i.name, 200) || !text(i.unit, 30) || !text(i.vat, 16)) return { error: 'an item has no name, unit or VAT' }
    if (typeof i.unit_price !== 'number' || !Number.isFinite(i.unit_price) || i.unit_price < 0) return { error: 'an item has no unit price' }
    if (i.unit_price_type !== 'net' && i.unit_price_type !== 'gross') return { error: 'an item has no unit price type' }
    if (typeof i.quantity !== 'number' || !Number.isFinite(i.quantity) || !(i.quantity > 0)) return { error: 'an item has no quantity' }
    items.push({ name: i.name, unit_price: i.unit_price, unit_price_type: i.unit_price_type, quantity: i.quantity, unit: i.unit, vat: i.vat })
  }
  const hash = issueContentHash(p.company, p.draft_id, b)
  if (p.content_hash !== hash) return { error: 'content_hash is not the hash of company, draft_id and body' }
  if (contentHash !== hash) return { error: 'content_hash must be given, and be the hash of the payload' }
  return {
    request: {
      company: p.company, draftId: p.draft_id, hash, partnerId: b.partner_id, currency: b.currency,
      fulfillmentDate: b.fulfillment_date, dueDate: b.due_date, items, body: b,
    },
  }
}

/** "27%" is 0.27; the exempt and reverse-charge codes (AAM, TAM, EUK, ...) add nothing. */
function vatRate(vat: string): number {
  const m = /^(\d{1,2}(?:\.\d+)?)%$/.exec(vat)
  return m ? Number(m[1]) / 100 : 0
}

/** Net, VAT and gross by line, rounded per line (to the forint for HUF, to the cent otherwise). */
export function issueTotals(r: IssueRequest): { net: number; vat: number; gross: number } {
  const round = (n: number) => (r.currency === 'HUF' ? Math.round(n) : Math.round(n * 100) / 100)
  let net = 0
  let gross = 0
  for (const i of r.items) {
    const rate = vatRate(i.vat)
    const amount = i.unit_price * i.quantity
    const lineNet = round(i.unit_price_type === 'net' ? amount : amount / (1 + rate))
    const lineGross = round(i.unit_price_type === 'net' ? amount * (1 + rate) : amount)
    net += lineNet
    gross += lineGross
  }
  return { net: round(net), vat: round(gross - net), gross: round(gross) }
}

function money(n: number, currency: string): string {
  return `${n.toLocaleString('hu-HU', { maximumFractionDigits: 2 })} ${currency}`
}

/** One line of agent-originated text, made harmless for the button message. */
function plain(s: string, max: number): string {
  // eslint-disable-next-line no-control-regex
  const one = s.replace(/[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁠-⁩﻿]/g, ' ').replace(/\s+/g, ' ').trim()
  return one.length > max ? `${one.slice(0, max - 1)}…` : one
}

/** The owner's text: everything that decides the invoice comes from the body, through this code. */
export function renderIssueText(r: IssueRequest): string {
  const t = issueTotals(r)
  const lines = [
    'Billingo-SZÁMLA KIÁLLÍTÁSA. Kiállítás után nem vonható vissza (sztornó itt nem lehetséges).',
    `Cég: ${COMPANY_NAMES[r.company]} | piszkozat: ${r.draftId} | partner-azonosító: ${r.partnerId}`,
    'Tételek:',
    ...r.items.map((i) => `- ${plain(i.name, 120)}: ${i.quantity} ${plain(i.unit, 20)} x ${money(i.unit_price, r.currency)} (${i.unit_price_type === 'net' ? 'nettó' : 'bruttó'}), ÁFA ${plain(i.vat, 16)}`),
    `Nettó: ${money(t.net, r.currency)} | ÁFA: ${money(t.vat, r.currency)} | BRUTTÓ: ${money(t.gross, r.currency)}`,
    `Teljesítés: ${r.fulfillmentDate} | Fizetési határidő: ${r.dueDate}`,
    `Ellenőrző kód: ${r.hash.slice(0, 12)}`,
    'Az összegeket a szerver számolta a kérés törzséből; a kapu kiállítás előtt összeveti a Billingóban lévő piszkozattal.',
  ]
  return lines.join('\n')
}

// ---------------------------------------------------------------- signing

export interface IssueSigningKey { key: KeyObject; kid: string; publicKey: string }

/** The raw 32-byte public key, base64url, and its kid ("k-" + 8 hex of its SHA-256). */
export function publicKeyInfo(key: KeyObject): { kid: string; publicKey: string } {
  const raw = createPublicKey(key).export({ format: 'der', type: 'spki' }).subarray(12)
  return { kid: `k-${createHash('sha256').update(raw).digest('hex').slice(0, 8)}`, publicKey: raw.toString('base64url') }
}

/** null when no key is set or it is not an Ed25519 private key (never logged). */
export function readIssueSigningKey(secret: (id: string) => string | null = getSecret): IssueSigningKey | null {
  let pem: string | null = null
  try { pem = secret(BILLINGO_ISSUE_KEY_VAULT_ID) } catch { pem = null }
  if (!pem) return null
  try {
    const key = createPrivateKey(pem.trim())
    if (key.asymmetricKeyType !== 'ed25519') return null
    return { key, ...publicKeyInfo(key) }
  } catch {
    return null
  }
}

export interface SignableApproval {
  id: string
  category: string
  status: string
  resolved_at: number | null
  resolved_by: string | null
  resolution_channel?: string | null
  action_payload: string | null
  content_hash: string | null
}

/**
 * The gate's X-Marveen-Approval value for one approval, or null with the reason.
 * Only an approved billingo_issue row resolved by the owner's button (A1).
 */
export function signIssueApproval(a: SignableApproval, signingKey: IssueSigningKey | null): { value: string } | { error: string } {
  if (a.category !== BILLINGO_ISSUE_CATEGORY) return { error: 'not a billingo_issue approval' }
  if (a.status !== 'approved' || a.resolution_channel !== 'approval_bot' || a.resolved_by !== 'telegram_button' || !Number.isSafeInteger(a.resolved_at)) {
    return { error: 'only an approval resolved by the owner\'s button is signed' }
  }
  const parsed = parseIssueRequest(a.action_payload, a.content_hash)
  if ('error' in parsed) return { error: parsed.error }
  if (!signingKey) return { error: 'no signing key in the Vault' }
  const fields = {
    kid: signingKey.kid,
    approval_id: a.id,
    company: parsed.request.company,
    draft_id: parsed.request.draftId,
    content_hash: parsed.request.hash,
    resolved_at: a.resolved_at as number,
  }
  const message = [BILLINGO_ISSUE_PURPOSE, fields.kid, fields.approval_id, fields.company, fields.draft_id, fields.content_hash, fields.resolved_at].join(':')
  const sig = sign(null, Buffer.from(message, 'utf8'), signingKey.key).toString('base64url')
  return { value: Buffer.from(JSON.stringify({ ...fields, sig }), 'utf8').toString('base64url') }
}
