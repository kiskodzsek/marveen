#!/usr/bin/env python3
"""hiany_lint.py -- absence-claim lint for a delivered research file (retro 2026-11-13 R10, card 1f943050).

    python3 -I scripts/lib/hiany_lint.py <file.md>     exit 0 = clean, 1 = findings, 2 = usage/read error

Written by Radar (agents/radar/.claude/skills/magyar-problema-meres/scripts/hiany_lint.py, 41254); moved into the repo
so the send gate (scripts/lib/msg_gate.py rule 6) can run it. The patterns are NOT copied: the absence-claim patterns,
the ITTHON block reader and the shop check come from the reply gate (scripts/hooks/product-image-gate.py), the 4-domain
site probe from the shared idea lint (scripts/uzleti-otlet-kapu-lint.py site_hibak), so a change there covers files too.

R10a ITTHON: a sentence claiming something is missing at home needs, in the same file, an "ITTHON-MERT: <file>" line
     ("ITTHON-MERT: ez a fájl" points to itself). The target file (inside the install) needs at least one "ITTHON:"
     block, and every block must name Meska, Pepita and eMAG with a measured result or "NINCS ADAT <reason>", plus the
     4-domain site probe with a result for each domain and no hit.
     Background: Patrik TG 18042 "Mindegyik van itthon is", Balázs TG 5579 "megkérdeztem mi a magyar piac".
R10b NINCS ADAT: every line saying "NINCS ADAT" needs a search log, either
     - inline: a source (URL, domain, shop or tool name) AND a result (HTTP 4xx/5xx, "0 találat", "nincs találat",
       "nem hozott", "captcha", "üres") on the same line, or
     - a reference token (K1, N2, [K3], a range N1-N4) defined in a "## Keresés-napló" / "## Források" section,
       whose entry names a source and a result, with a date in the entry or in the section heading.
     Background: hibanapló 11-11 L232 ("Nyitott felhívás: NINCS ADAT" while a call was active).
Fenced code blocks are examples, not claims.

Env: MARVEEN_HIANY_ROOT (the install root the ITTHON-MERT target must be inside; default: this repo).
"""
import importlib.util
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.realpath(os.path.join(HERE, '..', '..'))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_gate = _load('_pig_for_hiany', os.path.join(REPO, 'scripts', 'hooks', 'product-image-gate.py'))
_idea = _load('_uok_for_hiany', os.path.join(REPO, 'scripts', 'uzleti-otlet-kapu-lint.py'))
ITTHON_CLAIM = _gate.ITTHON_CLAIM
itthon_blocks = _gate.itthon_blocks
itthon_shop_gaps = _gate.itthon_shop_gaps
site_hibak = _idea.site_hibak

# The file form allows a list dash and a phrase ("ez a fájl"); the reply gate's ITTHON_MERT_RE takes one token.
ITTHON_MERT_RE = re.compile(r'(?mi)^\s*[-*]?\s*ITTHON-M[EÉ]RT:[ \t]*(.+?)\s*$')
SELF = ('ez a fájl', 'ez a fajl', 'itt', 'self')

# Viktor 41461 LOW 2 (CWE-1333): the domain label is bounded to 63 characters (the DNS limit), so a long hyphenated
# token no longer opens a scan to the line end at every hyphen (quadratic: 1 MB took minutes).
NINCS = re.compile(r'NINCS ADAT')
# Radar 41442: a brief line ("Kész, ha:") or a legend ("Jelölés(ek):") at the line start names NINCS ADAT as a term,
# not as a claim; a backticked `NINCS ADAT` in a table cell stays a claim (formatting alone must not pass).
DEFLINE = re.compile(r'^\s*(?:>\s*)?(?:[-*]\s+)?\**(?:Kész, ha|Jelölés(?:ek)?)\**\s*:')
# Viktor 41468 LOW 1: the prefix alone no longer exempts the whole line. Every NINCS ADAT on it must be a term use:
# an item of an enumeration or a definition ("; **NINCS ADAT** = nem tudom", "vagy NINCS ADAT indokkal",
# "`NINCS ADAT` a szokott jelentéssel"), not a value after a field ("Gyártási költség: NINCS ADAT").
TERM_RUN = re.compile(r'[\s*`_\[\]"„”“\']+')
# Viktor 41484 LOW: "a" and "és" before NINCS ADAT read as a field value in a sentence ("az ár a NINCS ADAT"),
# not as a list item, so they no longer exempt (measured: 6 of 187 real legend lines lose the exemption instead
# of 5). The comma stays: real legends list their marks with commas, and dropping it would cost 49 of 187.
TERM_PRE = re.compile(r'(?:[;,|/(.]|\bvagy)$')
TERM_POST = re.compile(r'(?:[;,./()]|$|=|indokkal\b|-|jelöl|a szokott jelentéssel)')
SRC = re.compile(r'(?i)https?://|(?<![\w@])[\w-]{1,63}\.(hu|com|org|io|eu|net|gov|de|co|app)\b|webread|websearch|'
                 r'quarantine|reader|\bGET\b|/search|\bapi\b|ads-|trends|ksh|meska|pepita|e-?mag|vatera|dm\b|'
                 r'google|meta|apify|curl|grep')
RES = re.compile(r'(?i)(?<!\d)[45]\d\d(?!\d)|\b0\s*(db|találat|sor|hit)|nincs találat|nem hozott|nem talál|nem ad|'
                 r'captcha|üres|nem szerepel|nincs (benne|rajta|ID|példa)|\b0\b|hiányzik|timeout|\bnincs\b')
DATE = re.compile(r'\b20\d\d-\d\d-\d\d\b|\b\d\d-\d\d\b|\b\d{1,2}:\d\d\b')
LOG_HEAD = re.compile(r'(?im)^#{2,4}\s+.*(keres[ée]s[- ]?napl[óo]|források)')
TOKEN = re.compile(r'(?<![\w-])\[?([A-Z]{1,2}\d{1,2})\]?(?![\w-])')
RANGE = re.compile(r'(?<![\w-])([A-Z]{1,2})(\d{1,2})\s*[-–]\s*\1?(\d{1,2})(?![\w-])')
MAX_BYTES = 2_000_000


def root():
    return os.path.realpath(os.environ.get('MARVEEN_HIANY_ROOT') or REPO)


def read_lines(path):
    """NFC lines with fenced code blanked (line numbers kept). OSError propagates."""
    with open(path, encoding='utf-8', errors='replace') as f:
        text = unicodedata.normalize('NFC', f.read(MAX_BYTES))
    out, fence = [], False
    for ln in text.splitlines():
        if ln.strip().startswith('```'):
            fence = not fence
            out.append('')
            continue
        out.append('' if fence else ln)
    return out


def check_itthon(path, lines):
    claims = [(i + 1, ln.strip()) for i, ln in enumerate(lines)
              if any(rx.search(ln) for rx in ITTHON_CLAIM) and not ITTHON_MERT_RE.match(ln)]
    if not claims:
        return []
    m = ITTHON_MERT_RE.search('\n'.join(lines))
    where = f"sor {claims[0][0]}: „{claims[0][1][:90]}”" + (f" (+{len(claims) - 1} további)" if len(claims) > 1 else "")
    if not m:
        return [f"R10a NEM MEGY  itthoni hiány-állítás ITTHON-MERT sor nélkül, {where}"]
    tok = m.group(1).strip().strip('`')
    if tok.lower() in SELF:
        tpath = os.path.realpath(path)
    else:
        tpath = os.path.realpath(tok if os.path.isabs(tok) else os.path.join(root(), tok))
        if not os.path.exists(tpath):
            tpath = os.path.realpath(os.path.join(os.path.dirname(path), tok))
    if not tpath.startswith(root() + os.sep):
        return [f"R10a NEM MEGY  az ITTHON-MERT fájl a telepítésen kívül van ({tok}), {where}"]
    try:
        tlines = read_lines(tpath)
    except OSError as e:
        return [f"R10a NEM MEGY  az ITTHON-MERT fájl nem olvasható ({tok}, {e.__class__.__name__}), {where}"]
    blocks = itthon_blocks('\n'.join(tlines))
    if not blocks:
        return [f"R10a NEM MEGY  az ITTHON-MERT fájlban nincs ITTHON: mező ({tok}), {where}"]
    out = []
    for blk in blocks:
        head = blk[0].strip()[:60]
        gaps = itthon_shop_gaps(blk)
        if gaps:
            out.append(f"R10a NEM MEGY  ITTHON-blokk „{head}”: hiányzik {', '.join(gaps)} "
                       f"(mért eredmény vagy „NINCS ADAT <indok>”)")
            continue
        for se in site_hibak('\n'.join(blk)):
            out.append(f"R10a NEM MEGY  ITTHON-blokk „{head}”: {se}")
    return out


def log_entries(lines):
    """token -> (entry line, heading has a date), from the search-log / sources sections."""
    entries, in_log, head_date = {}, False, False
    for ln in lines:
        if re.match(r'^#{1,4}\s', ln):
            in_log = bool(LOG_HEAD.match(ln))
            head_date = bool(DATE.search(ln))
            continue
        if not in_log:
            continue
        m = re.match(r'^\s*[-*]\s*(\*\*)?\[?([A-Z]{1,2}\d{1,2})\]?\b', ln)
        if m:
            entries[m.group(2)] = (ln, head_date)
    return entries


def tokens(ln):
    """Log references on a line; a range such as N1-N4 or K2–5 expands to every member (at most 21)."""
    out = list(TOKEN.findall(ln))
    for p, a, b in RANGE.findall(ln):
        if int(a) <= int(b) <= int(a) + 20:
            out += [f"{p}{k}" for k in range(int(a), int(b) + 1)]
    return out


def term_line(ln):
    """A brief or legend line on which every NINCS ADAT is a term use (Viktor 41468 LOW 1)."""
    d = DEFLINE.match(ln)
    if not d:
        return False
    # Formatting and whitespace runs collapse to one space first, so a bounded window sees the nearest word or
    # separator (a long run of spaces must not hide "Gyártási költség:"), and no item costs a slice to the line end.
    body = TERM_RUN.sub(' ', ln[d.end():])
    for m in NINCS.finditer(body):
        pre = body[max(0, m.start() - 40):m.start()].strip()
        post = body[m.end():m.end() + 40].lstrip()
        if (pre and not TERM_PRE.search(pre)) or not TERM_POST.match(post):
            return False
    return True


def check_nincs(lines):
    entries = log_entries(lines)
    out = []
    for i, ln in enumerate(lines):
        if not NINCS.search(ln) or term_line(ln):
            continue
        if SRC.search(ln) and RES.search(ln):
            continue
        refs = tokens(ln)
        if any((e := entries.get(t)) and SRC.search(e[0]) and RES.search(e[0]) and (e[1] or DATE.search(e[0]))
               for t in refs):
            continue
        why = (f"a hivatkozott napló-tétel ({', '.join(refs)}) hiányzik, vagy nincs benne forrás + eredmény + dátum"
               if refs else "se soron belüli forrás + eredmény, se napló-hivatkozás (K1/N1)")
        out.append(f"R10b NEM MEGY  sor {i + 1}: NINCS ADAT keresés-napló nélkül: {why}: „{ln.strip()[:90]}”")
    return out


def lint(path):
    """The findings for one file (empty list = clean). OSError propagates."""
    lines = read_lines(path)
    return check_itthon(path, lines) + check_nincs(lines)


def main(argv):
    if len(argv) != 1:
        print('usage: hiany_lint.py <file.md>', file=sys.stderr)
        return 2
    try:
        findings = lint(argv[0])
    except OSError as e:
        print(f"HIBA: a fájl nem olvasható ({e.__class__.__name__})")
        return 2
    print('\n'.join(findings) if findings else "MEHET  R10a/R10b: nincs hiba")
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
