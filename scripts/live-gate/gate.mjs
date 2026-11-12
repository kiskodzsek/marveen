// Post-deploy live gate: a machine stops the release (Patrik TG 5607, 2026-11-12).
//
// Used two ways:
//   1. run.mjs walks a JSON plan (pages and click-through flows) and calls checkpoint() after every step.
//   2. an existing flow script (trial form, checkout ...) imports { Gate } and calls
//      gate.checkpoint(page, 'step-label') after each step it takes. Same filter, same verdict.
//
// A checkpoint = (a) fullPage screenshot in the page's current viewport (flows run twice: mobile 390x844 and
// desktop 1440x900), (b) internal-name filter on the visible text (innerText) and on customer-facing
// attributes, (c) error-page / HTTP status markers. ANY finding -> exit code 1 -> the release is NOT done.
// The screenshots are listed in gate-result.json; the gate cannot see whether a human looked at them, so the
// verdict says so and the releaser must Read every image before reporting "done".
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { scanText, scanAttrs, parseKnown } from './internal-names.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const VIEWS = {
  mobil: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
  asztali: { viewport: { width: 1440, height: 900 }, isMobile: false, hasTouch: false, deviceScaleFactor: 1 },
};

// Page-level error markers: a customer-visible failure that still returns HTTP 200.
const ERROR_MARKERS = [
  /Application error/i, /Internal Server Error/i, /This page could not be found/i, /Unhandled Runtime Error/i,
  /digest:\s*\d+/i, /ChunkLoadError/i, /Hydration failed/i, /Cannot read propert/i,
];

export function loadKnown(file = path.join(HERE, 'internal-names.txt')) {
  try { return parseKnown(fs.readFileSync(file, 'utf8')); } catch { return []; }
}

export function safe(s) { return String(s).replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'x'; }

export class Gate {
  // opts: { outDir, view: 'mobil'|'asztali', flow: 'name', known?: string[] }
  constructor({ outDir, view, flow, known }) {
    this.outDir = outDir; this.view = view; this.flow = flow;
    this.known = known ?? loadKnown();
    this.n = 0; this.findings = []; this.images = []; this.steps = [];
    fs.mkdirSync(outDir, { recursive: true });
  }

  // Pure part, testable without a browser: text + attrs -> findings.
  evaluate(label, { text, attrs = [], status = 200 }) {
    const f = [];
    if (status >= 400 || status === 0) f.push({ rule: 'http_status', why: 'page did not load', token: String(status), where: 'navigation', context: '' });
    for (const re of ERROR_MARKERS) {
      const m = re.exec(text || '');
      if (m) f.push({ rule: 'error_marker', why: 'error text visible to the customer', token: m[0], where: 'innerText', context: '' });
    }
    f.push(...scanText(text, 'innerText', this.known), ...scanAttrs(attrs, this.known));
    return f.map((x) => ({ flow: this.flow, view: this.view, step: label, ...x }));
  }

  async checkpoint(page, label, { status = 200 } = {}) {
    this.n += 1;
    const idx = String(this.n).padStart(2, '0');
    // Only what a customer can see: innerText skips display:none and <script>/<style>.
    const text = await page.evaluate(() => document.body ? document.body.innerText : '');
    const attrs = await page.evaluate(() => {
      const out = [];
      for (const el of document.querySelectorAll('[placeholder],[aria-label],[alt],[title]')) {
        const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
        if (st.display === 'none' || st.visibility === 'hidden') continue;
        for (const a of ['placeholder', 'aria-label', 'alt', 'title']) { const v = el.getAttribute(a); if (v) out.push({ attr: a, value: v }); }
      }
      return out;
    });
    const findings = this.evaluate(label, { text, attrs, status });
    const img = path.join(this.outDir, `${safe(this.flow)}-${idx}-${safe(label)}-${this.view}.png`);
    await page.screenshot({ path: img, fullPage: true });
    this.images.push(img); this.findings.push(...findings);
    this.steps.push({ n: this.n, label, url: page.url(), status, text_chars: (text || '').length, findings: findings.length, image: img });
    return findings;
  }

  result() { return { flow: this.flow, view: this.view, steps: this.steps, findings: this.findings, images: this.images }; }
}

// Combine gates into the verdict (printed + written). Returns the process exit code.
export function verdict(gates, outFile, { requireViews = ['mobil', 'asztali'] } = {}) {
  const findings = gates.flatMap((g) => g.findings);
  const images = gates.flatMap((g) => g.images);
  const missing = [];
  const flows = [...new Set(gates.map((g) => g.flow))];
  for (const fl of flows) for (const v of requireViews) if (!gates.some((g) => g.flow === fl && g.view === v && g.steps.length)) missing.push(`${fl}/${v}`);
  const ok = findings.length === 0 && missing.length === 0 && gates.length > 0;
  const body = { ok, findings, missing_views: missing, images, gates: gates.map((g) => g.result()) };
  fs.writeFileSync(outFile, JSON.stringify(body, null, 2));
  if (ok) {
    console.log(`GATE ZÖLD: ${gates.reduce((s, g) => s + g.steps.length, 0)} lépés, ${images.length} kép, 0 találat. A kiadás csak akkor kész, ha a képeket Read-del MEG IS NÉZTED (${path.dirname(outFile)}).`);
  } else {
    console.log(`GATE PIROS - a KIADÁS NEM KÉSZ, nem jelentheted késznek. ${findings.length} találat, hiányzó nézet: ${missing.join(', ') || 'nincs'}`);
    for (const f of findings.slice(0, 40)) console.log(`  [${f.view}] ${f.flow} / ${f.step}: ${f.rule} "${f.token}" (${f.where}) ...${f.context}...`);
    if (findings.length > 40) console.log(`  ... +${findings.length - 40} további, lásd ${outFile}`);
  }
  return ok ? 0 : 1;
}
