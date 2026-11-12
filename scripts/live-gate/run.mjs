// Walk a plan of live pages / click-through flows and gate every step.
// Usage: node run.mjs --plan plan.json [--base https://marabel.hu] [--out <dir>] [--allow-submit] [--pw <playwright index.mjs>]
//
// Plan (JSON): { "flows": [ { "name": "...", "steps": [ <step>, ... ] } ] }
// Step actions (one key each):
//   { "goto": "/path" }                       navigate, status recorded
//   { "click": "<selector or text=...>" }     Playwright click
//   { "fill": ["<selector>", "<value>"] }     fill a field (use obviously fake values; never a real customer's)
//   { "wait": 800 }                           ms
//   { "check": "label" }                      checkpoint: screenshot + internal-name filter
// Any step with "submits": true (it creates an account, order, payment, sends a form) is REFUSED unless
// --allow-submit is given; that flag is Patrik's explicit "mehet", never a default (CLAUDE.md: no real
// registration/payment/form submission on production without it). A goto/click that is only a wizard "next"
// button is not a submission.
// Exit code 0 = green, 1 = findings or a missing view, 2 = plan/usage error.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Gate, VIEWS, verdict, safe } from './gate.mjs';

const args = process.argv.slice(2);
const arg = (k, d) => (args.includes(k) ? args[args.indexOf(k) + 1] : d);
const BASE = arg('--base', 'https://marabel.hu');
const PLAN = arg('--plan');
const PW = arg('--pw', '/Users/klodel/marveen/node_modules/playwright/index.mjs');
const ALLOW_SUBMIT = args.includes('--allow-submit');
if (!PLAN) { console.error('usage: node run.mjs --plan plan.json [--base URL] [--out DIR] [--allow-submit]'); process.exit(2); }
const plan = JSON.parse(fs.readFileSync(PLAN, 'utf8'));
const stamp = new Date().toISOString().replace(/[:T]/g, '-').slice(0, 19);
const OUT = arg('--out', path.join(path.dirname(fileURLToPath(import.meta.url)), 'out', stamp));

for (const fl of plan.flows || []) for (const st of fl.steps || []) {
  if (st.submits && !ALLOW_SUBMIT) { console.error(`REFUSED: flow "${fl.name}" has a submitting step (${JSON.stringify(st)}); needs --allow-submit (Patrik's mehet)`); process.exit(2); }
}

const { chromium } = await import(PW);
const exe = process.env.HOME + '/Library/Caches/ms-playwright/chromium_headless_shell-' + (process.env.CHROMIUM_REV || '1248') + '/chrome-headless-shell-mac-arm64/chrome-headless-shell';
const browser = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
const gates = [];
for (const fl of plan.flows || []) {
  for (const [view, opts] of Object.entries(VIEWS)) {
    const gate = new Gate({ outDir: OUT, view, flow: fl.name });
    const ctx = await browser.newContext(opts);
    await ctx.addCookies([{ name: 'marabel_internal', value: '1', domain: new URL(BASE).hostname, path: '/', secure: BASE.startsWith('https'), sameSite: 'Lax' }]);
    const page = await ctx.newPage();
    let status = 200;
    for (const st of fl.steps) {
      try {
        if (st.goto) { const r = await page.goto(BASE + st.goto, { waitUntil: 'load' }).catch(() => null); status = r ? r.status() : 0; await page.waitForTimeout(600); }
        else if (st.click) { await page.click(st.click, { timeout: 8000 }); await page.waitForTimeout(600); status = 200; }
        else if (st.fill) { await page.fill(st.fill[0], st.fill[1], { timeout: 8000 }); }
        else if (st.wait) { await page.waitForTimeout(st.wait); }
        else if (st.check) { await gate.checkpoint(page, st.check, { status }); }
      } catch (e) {
        // a step that cannot be performed is a finding: the gate must not pass over a form it could not walk
        gate.findings.push({ flow: fl.name, view, step: JSON.stringify(st).slice(0, 80), rule: 'step_failed', why: 'step could not be performed', token: String(e.message).split('\n')[0].slice(0, 120), where: 'runner', context: '' });
      }
    }
    await ctx.close();
    gates.push(gate);
  }
}
await browser.close();
process.exit(verdict(gates, path.join(OUT, 'gate-result.json')));
