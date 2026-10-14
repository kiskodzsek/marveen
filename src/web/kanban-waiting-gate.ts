import { getDb } from '../db.js'

// Card bf868101: a card in "waiting" must say WHO it waits for and on WHAT, in a
// line of the form "VÁR: <ki> - <mire>" (e.g. "VÁR: Patrik - mehet a K6a-ra").
// A bare waiting card is a dead end on the board: nobody can tell whose move it
// is, so nobody moves.
//
// The rule applies to an API move INTO waiting (POST /move, PUT status). A move
// within the column (reorder, a whole-card PUT echoing status back) is not a
// transition and is not checked -- otherwise every drag inside the waiting
// column and every assignee edit on a waiting card would start failing.
//
// The line may come with the move itself (`comment` in the body, stored as a
// comment on success) or already sit in the card's LATEST comment, which is the
// order the dispatch instructions prescribe (comment, then move).

// Accent-insensitive on purpose for the leading word only: "VÁR:", "Vár:", and
// the accentless "VAR:" a phone keyboard produces all count; the colon and some
// text after it are required. NFC first, so a decomposed "A + combining acute"
// matches like the precomposed letter.
const VAR_LINE_RE = /^\s*(?:[-*>]\s*)?v[aá]r\s*:\s*\S/iu
// The fleet also ends a one-line status comment with the marker after a full
// stop ("... átadva Pulzusnak. VÁR: Pulzus - merge"). Mid-line it only counts
// in capitals and right after a sentence end, so prose like "Patrikra vár:"
// still does not pass.
const VAR_INLINE_RE = /[.!?;]\s+V[AÁ]R\s*:\s*\S/u

export function hasVarLine(text: string | null | undefined): boolean {
  if (!text) return false
  return text.normalize('NFC').split(/\r?\n/).some((line) => VAR_LINE_RE.test(line) || VAR_INLINE_RE.test(line))
}

export const WAITING_GATE_ERROR =
  'A kártya csak akkor mehet "waiting"-be, ha kiderül belőle, KIRE és MIRE vár. ' +
  'Küldj a mozgatással együtt egy "comment" mezőt, vagy írd a kártya legutóbbi kommentjébe, ' +
  'egy ilyen sorral: "VÁR: <ki> - <mire>" (pl. "VÁR: Patrik - mehet a K6a-ra"). A kártya NEM mozdult.'

// The latest comment a PERSON or AGENT wrote: machine rows (automated=1, or the
// board's own 'system' notices such as the undelivered-dispatch warning) are
// skipped, so a system note landing between "comment" and "move" cannot void
// the VÁR line the mover just wrote.
export function latestKanbanCommentContent(cardId: string): string | null {
  const row = getDb().prepare(
    "SELECT content FROM kanban_comments WHERE card_id = ? AND COALESCE(automated, 0) = 0 AND author <> 'system' " +
    'ORDER BY created_at DESC, id DESC LIMIT 1',
  ).get(cardId) as { content: string } | undefined
  return row?.content ?? null
}

/**
 * null = the move may proceed; a string = the 400 message.
 * `currentStatus` undefined (card not found) passes: the caller's own 404 path answers that.
 */
export function waitingGateVerdict(
  cardId: string,
  currentStatus: string | undefined,
  targetStatus: unknown,
  comment: unknown,
): string | null {
  if (targetStatus !== 'waiting') return null
  if (currentStatus === undefined || currentStatus === 'waiting') return null
  if (typeof comment === 'string' && hasVarLine(comment)) return null
  if (hasVarLine(latestKanbanCommentContent(cardId))) return null
  return WAITING_GATE_ERROR
}
