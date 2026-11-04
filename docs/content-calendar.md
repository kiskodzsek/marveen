# Content calendar (`/api/content`)

CONTENTCAL1104, marketing infra I3 (card b84e1760; plan `shared/marketing/upgrade-1103/terv.md` 3., 7., 12.(2)).

One row = one social post, keyed by its **campaign code**. The calendar is a table in the dashboard SQLite behind
field-level `PATCH`, so Mágnes and Mira can write the same post without overwriting each other. Nothing here
publishes anything or talks to Metricool.

Code: `src/content-calendar.ts` (rules), `src/web/routes/content.ts` (HTTP), test `src/__tests__/content-calendar.test.ts`.

## Endpoints (Bearer, like every `/api/*`)

| Method | Path | What |
|---|---|---|
| GET | `/api/content?status=a,b&brand=marabel&from=…&to=…` | list, ordered by `scheduled_at` (unscheduled last); `from`/`to` compare instants |
| POST | `/api/content` | new post; `id`, `brand`, `title` required; starts as `brief` (or `piszkozat`) |
| GET | `/api/content/<code>` | one post + `events` (who changed what, when, from/to status) |
| PATCH | `/api/content/<code>` | any writable fields and/or `status` |

No DELETE: a dropped post goes to `elvetve`. Every write needs an **actor** (`"actor":"mira"` in the body or the
`X-Agent-Id` header); it is self-asserted (one shared token), so it attributes, it does not authorize.
Send `"if_updated_at": <updated_at you read>` to refuse the write if someone changed the post in between (409).

## Fields

- `id`: campaign code - lowercase letters, digits, `-`, `_`, at most 40, no run of 7+ digits (`p-w45-reel1` yes, `20261106` no).
- `brand` (`marabel`, `myshp`), `title`, `brief` (goal + CTA, audience, hook idea, product/image, Reel need), `notes`.
- Approved content (hashed): `final_text` (verbatim: hashtags, line breaks, UTM link), `hook`, `link` (https),
  `channels` = `[{"network":"ig","format":"4:5"}, …]` (formats `4:5`, `9:16`, `1:1`, `16:9`, `1.91:1`),
  `scheduled_at` (ISO 8601 with offset, e.g. `2026-11-12T18:00:00+01:00`), `media` = `[{"path":"/Users/klodel/marveen/agents/mira/drafts/x.png","sha256":"<64 hex>"}]`,
  `ai_status` (`nincs` | `mi-segitett` | `mi-generalt`).
- `source_render` (Dave export / real product), `license` (music, font, image; CC BY attribution text),
  `lex_gate_required` (true/false), `lex_gate_ref` (Lex's message or file).
- After scheduling (Mira, only in `utemezve`/`kint`/`merve`): `metricool_date`, `metricool_networks`,
  `metricool_readback` (the text read back from Metricool), `readback_matches` (true/false), `live_url`.
- Server-managed (read only): `content_hash`, `approved_at`, `created_*`, `updated_*`. `approval_id` is set by the caller while asking.

## Status machine (plan 7.)

```
brief -> piszkozat -> [jogi-ok] -> jovahagyas-kerve -> jovahagyva -> utemezve -> kint -> merve
                                         |-> elutasitva -> piszkozat
any open status -> elvetve (final); jovahagyva/jogi-ok/jovahagyas-kerve/elutasitva -> piszkozat (edit again)
utemezve -> jovahagyva (pulled back from Metricool)
```

- **`jovahagyas-kerve`** needs `final_text`, `channels`, `scheduled_at`, `ai_status`, `lex_gate_required`; if
  `lex_gate_required` is true, the post must come from `jogi-ok` (which needs `lex_gate_ref`). On entering, the server
  computes `content_hash` (sha256 over text, hook, link, channels, time, media + sha256, AI status) and **freezes**
  those fields. To change anything: `status: piszkozat` (drops the hash and the approval), edit, ask again.
- **`jovahagyva`** needs `approval_id` of an `approvals` row that is `approved`, category `social_post`, with the
  **same** `content_hash`, resolved by the approval bot's button (`resolution_channel = 'approval_bot'`, which no API
  route can set; a route-side `PATCH /api/approvals` approval does not count, Viktor 25867). The `social_post` category and the Telegram button are I4 (not built yet), so today no
  post can be approved - intended, nothing is published (Patrik TG 14215, 14348).
- **`kint`** needs `live_url`.

The media files are not read by the server: the path and sha256 are what the caller says. The path must be under
the install tree (`/Users/klodel/marveen/…` in production), not in `store/` and not in a dot-directory. The check before
scheduling is Mira's `shasum -a 256` against the post's media (plan 7.2(a)).

## Examples

```bash
T="Authorization: Bearer $(cat /Users/klodel/marveen/store/.dashboard-token)"
# Mágnes: a brief
curl -s -X POST http://localhost:3420/api/content -H "$T" -H 'Content-Type: application/json' --data-binary @- <<'JSON'
{"id":"p-w46-feed1","brand":"marabel","title":"Meséld el! - nagymama hangja","brief":"cél: ...; CTA: ...","actor":"magnes"}
JSON
# Mira: the draft
curl -s -X PATCH http://localhost:3420/api/content/p-w46-feed1 -H "$T" -H 'Content-Type: application/json' --data-binary @- <<'JSON'
{"status":"piszkozat","final_text":"...","channels":[{"network":"ig","format":"4:5"}],"scheduled_at":"2026-11-12T18:00:00+01:00",
 "media":[{"path":"/Users/klodel/marveen/agents/mira/drafts/x.png","sha256":"..."}],"ai_status":"nincs","lex_gate_required":false,"actor":"mira"}
JSON
# Mira's pre-scheduling check reads id, status, content_hash, media:
curl -s -H "$T" http://localhost:3420/api/content/p-w46-feed1
```
