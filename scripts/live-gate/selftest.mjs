// Self-test of the live gate: a browser opens FIXTURES (never the live site).
//  - trial-form-internal-names.html (the old bug: internal names on a trial form) MUST be RED,
//  - trial-form-clean.html (normal Hungarian text, host, brand, price) MUST be GREEN,
//  - page-404.html (error text with HTTP 200) MUST be RED,
//  - a status 500 on a clean page MUST be RED.
// Usage: node selftest.mjs [--pw <playwright index.mjs>]   exit 0 = the gate works, 1 = the gate is broken.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Gate, VIEWS } from './gate.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const PW = args.includes('--pw') ? args[args.indexOf('--pw') + 1] : '/Users/klodel/marveen/node_modules/playwright/index.mjs';
const { chromium } = await import(PW);
const exe = process.env.HOME + '/Library/Caches/ms-playwright/chromium_headless_shell-' + (process.env.CHROMIUM_REV || '1248') + '/chrome-headless-shell-mac-arm64/chrome-headless-shell';
const browser = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
const out = fs.mkdtempSync(path.join(os.tmpdir(), 'live-gate-selftest-'));
let bad = 0;
const expect = (name, got, want) => { const ok = got === want; if (!ok) bad++; console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}: ${got ? 'RED' : 'GREEN'} (expected ${want ? 'RED' : 'GREEN'})`); };

async function run(fixture, status = 200) {
  const found = [];
  for (const [view, opts] of Object.entries(VIEWS)) {
    const g = new Gate({ outDir: out, view, flow: fixture, known: ['Marabello-projekt'] });
    const ctx = await browser.newContext(opts);
    const page = await ctx.newPage();
    await page.setContent(fs.readFileSync(path.join(HERE, 'fixtures', fixture), 'utf8'));
    found.push(...(await g.checkpoint(page, 'step', { status })));
    await ctx.close();
  }
  return found;
}

const red = await run('trial-form-internal-names.html');
expect('old bug: internal names on the trial form', red.length > 0, true);
const rules = new Set(red.map((f) => f.rule));
for (const r of ['template', 'snake_case', 'SCREAMING_CASE', 'camelCase', 'i18n_key', 'dev_word']) expect(`rule ${r} fires`, rules.has(r), true);
expect('both views are checked', new Set(red.map((f) => f.view)).size === 2, true);
expect('clean Hungarian page (host, brand, price, "Test")', (await run('trial-form-clean.html')).length > 0, false);
expect('404 text with HTTP 200', (await run('page-404.html')).some((f) => f.rule === 'error_marker'), true);
expect('HTTP 500 on a clean page', (await run('trial-form-clean.html', 500)).some((f) => f.rule === 'http_status'), true);
// the known-name list
{
  const g = new Gate({ outDir: out, view: 'mobil', flow: 'k', known: ['Marabello-projekt'] });
  expect('known internal name', g.evaluate('s', { text: 'Itt a Marabello-projekt kód.' }).some((f) => f.rule === 'known_internal'), true);
}
await browser.close();
console.log(bad ? `SELFTEST HIBA: ${bad} elvárás nem teljesült` : 'SELFTEST OK');
process.exit(bad ? 1 : 0);
