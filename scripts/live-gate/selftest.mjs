// Self-test of the live gate: a browser opens FIXTURES (never the live site).
//  - trial-form-internal-names.html (the old bug: internal names on a trial form) MUST be RED,
//  - trial-form-clean.html (normal Hungarian text, host, brand, price) MUST be GREEN,
//  - page-404.html (error text with HTTP 200) MUST be RED,
//  - a status 500 on a clean page MUST be RED,
//  - per-page allow (plan "allow_by_path", Klodel 40328): the privacy notice with its cookie names is GREEN with
//    the exact names allowed on ITS path, RED without, RED on any other path, RED for a new name on the same path,
//    and a rule that is not identifier-shaped (dev word, template) can never be allowed.
// Usage: node selftest.mjs [--pw <playwright index.mjs>]   exit 0 = the gate works, 1 = the gate is broken.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { Gate, VIEWS, normalizeAllow } from './gate.mjs';

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
expect('name hidden in a closed <details>', red.some((f) => f.token === 'faq_trial_note'), true);
expect('name in a <select> option', red.some((f) => f.where === 'attr:option' && f.token === 'GIFT_BOOK_V2'), true);
expect('both views are checked', new Set(red.map((f) => f.view)).size === 2, true);
expect('clean Hungarian page (host, brand, price, "Test")', (await run('trial-form-clean.html')).length > 0, false);
expect('404 text with HTTP 200', (await run('page-404.html')).some((f) => f.rule === 'error_marker'), true);
expect('HTTP 500 on a clean page', (await run('trial-form-clean.html', 500)).some((f) => f.rule === 'http_status'), true);
// the known-name list
{
  const g = new Gate({ outDir: out, view: 'mobil', flow: 'k', known: ['Marabello-projekt'] });
  expect('known internal name', g.evaluate('s', { text: 'Itt a Marabello-projekt kód.' }).some((f) => f.rule === 'known_internal'), true);
}

// ---- per-page allow: pure part ----
{
  const NAMES = ['marabel_sid', 'lastExternalReferrer'];
  const g = new Gate({ outDir: out, view: 'mobil', flow: 'allow-unit', known: [] });
  const text = 'Sütik: marabel_sid és lastExternalReferrer.';
  expect('allow unit: without allow the names are RED', g.evaluate('s', { text }).length > 0, true);
  expect('allow unit: exact names allowed -> GREEN', g.evaluate('s', { text, allow: NAMES }).length > 0, false);
  expect('allow unit: suppressed names are reported', g.evaluate('s', { text, allow: NAMES }).suppressed.length === 2, true);
  expect('allow unit: a NEW name next to allowed ones is RED', g.evaluate('s', { text: text + ' marabel_new_cookie', allow: NAMES }).some((f) => f.token === 'marabel_new_cookie'), true);
  expect('allow unit: a dev word can never be allowed', g.evaluate('s', { text: 'undefined', allow: ['undefined'] }).some((f) => f.rule === 'dev_word'), true);
  expect('allow unit: a template can never be allowed', g.evaluate('s', { text: '{{ nev }}', allow: ['nev'] }).some((f) => f.rule === 'template'), true);
  expect('allow unit: HTTP status can never be allowed', g.evaluate('s', { text: 'ok', status: 500, allow: ['500'] }).some((f) => f.rule === 'http_status'), true);
  let threw = 0;
  for (const bad of [['marabel_*'], ['a b'], ['/x'], [1], 'marabel_sid']) { try { normalizeAllow(bad); } catch { threw++; } }
  expect('allow unit: wildcard / non-name / non-array entries are refused', threw === 5, true);
}

// ---- per-page allow: through run.mjs and a local server (never the live site) ----
{
  const notice = fs.readFileSync(path.join(HERE, 'fixtures', 'cookie-notice.html'), 'utf8');
  const NAMES = [...notice.matchAll(/<td>([A-Za-z0-9_]+)<\/td><td>/g)].map((m) => m[1]);
  expect('allow e2e: the fixture lists 12 names', NAMES.length === 12, true);
  const pages = { '/adatkezeles': notice, '/masik': notice, '/uj-adatkezeles': notice.replace('</table>', '<tr><td>marabel_new_cookie</td><td>uj</td></tr></table>') };
  const server = http.createServer((req, res) => { const b = pages[req.url.split('?')[0]]; res.writeHead(b ? 200 : 404, { 'content-type': 'text/html; charset=utf-8' }); res.end(b || 'nincs'); });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const flow = (name, p) => ({ name, steps: [{ goto: p }, { check: 'loaded' }] });
  // async spawn: the local server lives in THIS process, a blocking spawnSync would freeze it
  const runPlan = async (name, plan) => {
    const dir = path.join(out, 'e2e-' + name); fs.mkdirSync(dir, { recursive: true });
    const pf = path.join(dir, 'plan.json'); fs.writeFileSync(pf, JSON.stringify(plan));
    const code = await new Promise((resolve) => {
      const child = spawn(process.execPath, [path.join(HERE, 'run.mjs'), '--plan', pf, '--base', base, '--out', dir, '--pw', PW], { env: process.env, stdio: 'ignore' });
      const timer = setTimeout(() => child.kill('SIGKILL'), 180000);
      child.on('close', (c) => { clearTimeout(timer); resolve(c); });
    });
    let res = null; try { res = JSON.parse(fs.readFileSync(path.join(dir, 'gate-result.json'), 'utf8')); } catch {}
    return { code, res };
  };
  const a = await runPlan('allowed', { flows: [flow('page-adatkezeles', '/adatkezeles')], allow_by_path: { '/adatkezeles': NAMES } });
  expect('allow e2e: notice page with its names allowed on its path', a.code !== 0, false);
  expect('allow e2e: the verdict lists what was let through', a.res?.gates?.some((g) => g.steps.some((s) => s.allowed.length === 12)), true);
  const b = await runPlan('no-allow', { flows: [flow('page-adatkezeles', '/adatkezeles')] });
  expect('allow e2e: same page without allow_by_path', b.code !== 0, true);
  const c = await runPlan('other-path', { flows: [flow('page-adatkezeles', '/adatkezeles'), flow('page-masik', '/masik')], allow_by_path: { '/adatkezeles': NAMES } });
  expect('allow e2e: the same names on ANOTHER path', c.code !== 0 && c.res.findings.length > 0 && c.res.findings.every((f) => f.flow === 'page-masik'), true);
  const d = await runPlan('new-name', { flows: [flow('page-uj', '/uj-adatkezeles')], allow_by_path: { '/uj-adatkezeles': NAMES } });
  expect('allow e2e: a NEW name on the allowed path', d.code !== 0 && d.res.findings.length > 0 && d.res.findings.every((f) => f.token === 'marabel_new_cookie'), true);
  const e = await runPlan('wildcard', { flows: [flow('page-adatkezeles', '/adatkezeles')], allow_by_path: { '/adatkezeles': ['marabel_*'] } });
  expect('allow e2e: a wildcard entry is refused (exit 2)', e.code === 2, true);
  const f = await runPlan('badkey', { flows: [flow('page-adatkezeles', '/adatkezeles')], allow_by_path: { 'adatkezeles': NAMES } });
  expect('allow e2e: a key that is not a path is refused (exit 2)', f.code === 2, true);
  server.close();
}

await browser.close();
console.log(bad ?  `SELFTEST HIBA: ${bad} elvárás nem teljesült` : 'SELFTEST OK');
process.exit(bad ? 1 : 0);
