# Post-deploy live gate

Patrik TG 5607 (2026-11-12): "azért az hogy vmi betolt-e mobilon meg asztalin nem elégséges.. egy prodra történő deploy után ennél komolyabban kéne vizsgálni az oldalt és pl nem esne meg h az internal nevek maradnak kint mint a Receptes proba formon.."

A release is NOT done until this gate is green and every screenshot has been looked at (Read).

## What it checks, per step, mobile 390x844 and desktop 1440x900
- fullPage screenshot (listed in `gate-result.json`);
- the visible text (DOM `innerText`) and the customer-facing attributes (`placeholder`, `aria-label`, `alt`, `title`) for internal names: `{{ }}` / `{% %}` / `${}` templates, snake_case, SCREAMING_CASE, camelCase, dotted i18n keys, kebab keys, English developer words (TODO, debug, placeholder, lorem, undefined, null, NaN), and the names in `internal-names.txt`;
- HTTP status >= 400 and error text with HTTP 200 (Application error, This page could not be found, ...);
- a step that cannot be performed is a finding too (the gate does not pass over a form it could not walk).
Any finding: exit code 1, "GATE PIROS - a KIADÁS NEM KÉSZ".

## Use
```
node scripts/live-gate/selftest.mjs                                  # the gate itself: fixture with the old bug must be RED
node scripts/live-gate/run.mjs --plan scripts/live-gate/plan-marabel-pages.json --out <dir>
```
Then Read every image in `<dir>`. The plan lists pages and pre-login entry steps (read-only).

## Per-page allow (`allow_by_path`)
A page that legitimately LISTS identifier-shaped names (the /adatkezeles cookie and storage notice names `marabel_sid`, `multiFbc`, ...) would be RED for ever. The plan may carry an `allow_by_path` object:
```json
"allow_by_path": { "/adatkezeles": ["marabel_sid", "multiFbc"] }
```
- Key: a path starting with `/`, matched against `new URL(page.url()).pathname` at the checkpoint. Any other key: exit 2 (REFUSED).
- Value: an array of EXACT names (`^[A-Za-z0-9_.-]+$`). No wildcard, no space, no non-array: exit 2.
- Never global: the same name on another page stays RED; a NEW name on the allowed page stays RED.
- Only the identifier-shaped rules can be allowed (snake_case, SCREAMING_CASE, camelCase, i18n key, kebab key, known internal name). Templates, English developer words, error text and HTTP status can NEVER be allowed.
- What was let through is listed in `gate-result.json` (`steps[].allowed`, `findings.suppressed`): allowing is visible, not silent.
- Adding a name is weakening the gate: it needs a reviewer (Viktor) and the name must be on the page's own notice.

## Flows behind login, or that submit
`run.mjs` refuses any step marked `"submits": true` without `--allow-submit` (Patrik's explicit "mehet": no real registration, payment or form submission on production otherwise). For trial / order forms, a flow script imports the same filter:
```js
import { Gate, VIEWS, verdict } from './gate.mjs';
const gate = new Gate({ outDir, view: 'mobil', flow: 'receptkonyv-proba' });
await gate.checkpoint(page, 'indito-urlap');   // after EVERY step the script takes
```
Run it once per view (VIEWS.mobil, VIEWS.asztali) and finish with `verdict(gates, outFile)`.

## Known limits
- The filter finds identifier-shaped and listed names. A plain-word internal name (a project code that looks like a Hungarian word) is only caught once it is in `internal-names.txt`: add every name that ever shipped.
- "test" is not a dev word on purpose: it is a Hungarian word (body).
- The gate cannot see that a human looked at the images.
