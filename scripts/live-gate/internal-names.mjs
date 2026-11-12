// Internal-name filter for the post-deploy live gate (Patrik TG 5607, 2026-11-12).
//
// A customer must never see a developer's word on a live page: a snake_case or camelCase identifier,
// an enum or template key, a {{ placeholder }}, an i18n key with dots, a project/engine code, or an
// English developer word (TODO, debug, undefined, null, NaN ...). The filter reads VISIBLE text (the
// DOM innerText) and, separately, the customer-facing attributes (placeholder, aria-label, alt, title).
// A finding means the release is NOT done. No finding carries personal data: only the matched token
// and a short window of text around it.
//
// Pure functions, no I/O, so the negative test (a fixture with an internal name) runs without a browser.

export const DEV_WORDS = ['TODO', 'FIXME', 'XXX', 'debug', 'placeholder', 'lorem', 'ipsum', 'undefined', 'null', 'NaN', '[object Object]', 'Object object'];

// Words that look like identifiers but are legitimate on a Marabel page (brand names, tech names a
// customer may read). Keep this list SHORT and add a line only with the reason.
export const ALLOW = new Set([
  'mySHP', 'YouTube', 'TikTok', 'WhatsApp', 'iPhone', 'iPad', 'iOS', 'macOS', 'PayPal', 'GitHub',
  'LinkedIn', 'WordPress', 'JavaScript', 'PDF', 'QR', 'Apple', 'ApplePay', 'GooglePay',
]);

// Known internal names, one per line in internal-names.txt next to this file (names only, no secrets).
// Matched as whole words, case-sensitive. Extend after every internal name that ever shipped.

const RULES = [
  { id: 'template', re: /\{\{[^}]*\}\}|\{%[^%]*%\}|\$\{[^}]*\}|<%[^%]*%>/g, why: 'unrendered template placeholder' },
  { id: 'snake_case', re: /(?<![\w./@-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w@-])/g, why: 'snake_case identifier' },
  { id: 'SCREAMING_CASE', re: /(?<![\w./@-])[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+(?![\w@-])/g, why: 'enum / constant name' },
  { id: 'camelCase', re: /(?<![\w./@-])[a-z]+(?:[A-Z][a-z0-9]+)+(?![\w@-])/g, why: 'camelCase identifier' },
  // i18n key with dots: at least three lower-case segments, not an e-mail/host (those have a TLD)
  { id: 'i18n_key', re: /(?<![\w./@-])[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_]*){2,}(?![\w@-])/g, why: 'dotted key (i18n / config path)' },
  { id: 'kebab_key', re: /(?<![\w./@-])(?:err|error|msg|label|btn|cta|step|form|field|tpl|template)(?:-[a-z0-9]+){2,}(?![\w@-])/g, why: 'kebab-case key' },
];

const TLDS = new Set(['hu', 'com', 'org', 'net', 'eu', 'io', 'app', 'dev', 'co', 'de', 'at', 'ro', 'sk']);

function windowAround(text, idx, len) {
  const a = Math.max(0, idx - 24), b = Math.min(text.length, idx + len + 24);
  return text.slice(a, b).replace(/\s+/g, ' ').trim();
}

export function parseKnown(txt) {
  return (txt || '').split('\n').map((l) => l.replace(/#.*$/, '').trim()).filter(Boolean);
}

// text: string; where: label of the place (e.g. "innerText", "attr:placeholder"); known: string[]
export function scanText(text, where = 'innerText', known = []) {
  const out = [];
  if (!text) return out;
  for (const rule of RULES) {
    rule.re.lastIndex = 0;
    let m;
    while ((m = rule.re.exec(text))) {
      const tok = m[0];
      if (ALLOW.has(tok)) continue;
      if (rule.id === 'i18n_key') {
        const last = tok.split('.').at(-1);
        if (TLDS.has(last)) continue; // www.marabel.hu
      }
      if (rule.id === 'camelCase' && /^[a-z]{1,2}[A-Z]/.test(tok) && ALLOW.has(tok)) continue;
      out.push({ rule: rule.id, why: rule.why, token: tok, where, context: windowAround(text, m.index, tok.length) });
    }
  }
  for (const w of DEV_WORDS) {
    const esc = w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    // whole word; TODO/FIXME/XXX/NaN case-sensitive, the rest case-insensitive
    const flags = /^[A-Z]+$|NaN/.test(w) ? 'g' : 'gi';
    const re = new RegExp(`(?<![\\p{L}\\p{N}_])${esc}(?![\\p{L}\\p{N}_])`, flags + 'u');
    const rg = new RegExp(re.source, re.flags);
    let m;
    while ((m = rg.exec(text))) {
      out.push({ rule: 'dev_word', why: 'English developer word', token: m[0], where, context: windowAround(text, m.index, m[0].length) });
    }
  }
  for (const k of known) {
    const esc = k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const rg = new RegExp(`(?<![\\p{L}\\p{N}_])${esc}(?![\\p{L}\\p{N}_])`, 'gu');
    let m;
    while ((m = rg.exec(text))) {
      out.push({ rule: 'known_internal', why: 'listed internal name', token: m[0], where, context: windowAround(text, m.index, m[0].length) });
    }
  }
  return out;
}

// attrs: [{ attr, value }]
export function scanAttrs(attrs, known = []) {
  const out = [];
  for (const a of attrs) out.push(...scanText(a.value, `attr:${a.attr}`, known));
  return out;
}
