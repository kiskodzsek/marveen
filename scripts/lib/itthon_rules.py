#!/usr/bin/env python3
"""itthon_rules.py -- the "missing at home" rules shared by three gates (card 9a4b245c, Viktor 41524 L2, 41550).

Users: the Telegram reply gate (scripts/hooks/product-image-gate.py, the ITTHON-KAPU), the shared idea lint
(scripts/uzleti-otlet-kapu-lint.py, the site probe) and the file lint (scripts/lib/hiany_lint.py, which the send
gate runs). They lived in the first two files, and hiany_lint.py loaded both whole files by path; the mem-relief
pin (scripts/launchd-pins/com.marveen.mem-relief.sha256) did not cover them, so a change there reached a pinned
job unseen. Now this small file is the one source, and it is pinned. Moved verbatim: no rule changed.
Standard library only, no side effect at import.
"""
import re

ITTHON_VERB = r'(talál|kaph|árul|forgalmaz|létezik|érhető el|csinál|kínál|gyárt)'
ITTHON_CLAIM = [
    re.compile(r'(?i)\bitthon(\s+(még|viszont|pedig|is|sem|már))?\s+(nincs|sincs|hiányzik)\b'),
    re.compile(r'(?i)\bitthon\s+nem\s*[:.,;)]'),
    re.compile(r'(?i)\bitthon\b(\s+[\wáéíóöőúüű-]+){0,4}?\s+(nem|sem)\s+' + ITTHON_VERB),
    re.compile(r'(?i)\bitthon\s+senki\s+(sem|nem)\b'),
    re.compile(r'(?i)\bitthon\s+egyik\w*(\s+[\w-]+){0,2}\s+sem\b'),
    re.compile(r'(?i)\b(magyar|hazai)\s+(bolt|webshop|piac|platform|szolgáltat|stúdió|ügynökség|alapítású|megfelel|'
               r'változat|versenytárs|cég|app|termék)\w*[^.\n]{0,60}?(nem talál|nincs|sincs|nem kaph|nem árul)'),
    re.compile(r'(?i)nincs\s+(magyar|hazai)\s+(megfelel|változat|bolt|versenytárs|kínál|termék|app|platform)'),
]
ITTHON_SHOPS = {'meska': r'meska', 'pepita': r'pepita', 'emag': r'e-?mag'}
ITTHON_RESULT = re.compile(r'(?i)\d|nincs találat|nem hozott találatot|nem talált')
ITTHON_NOT_MEASURED = re.compile(r'(?i)nem mérhető|nem mért|(?<!\d)(403|404|410)(?!\d)|captcha')
ITTHON_NO_DATA = re.compile(r'(?i)NINCS ADAT\W+\w[^\n]{9,}')
ITTHON_SITE = re.compile(r'(?i)(?<!\w)site(:|-szűrt|-próba| szűrt)')


def itthon_blocks(t):
    out, lines = [], t.splitlines()
    for i, ln in enumerate(lines):
        if re.match(r'^\s*[-*]?\s*ITTHON:', ln):
            blk = [ln]
            for k in lines[i + 1:]:
                if k.startswith('  ') and k.strip():
                    blk.append(k)
                else:
                    break
            out.append(blk)
    return out


def itthon_shop_gaps(blk):
    """The shops of ITTHON_SHOPS that this ITTHON block does not answer (measured result or NINCS ADAT + reason)."""
    gaps = []
    for name, rx in ITTHON_SHOPS.items():
        ok = False
        for ln in blk:
            # On a site-probe line the domains (emag.hu, ...) are absence evidence, not a shop search (Klodel 39550):
            # they are cut out, the line's own shop name ("eMAG: NINCS ADAT ..., a site-próba pótolja") still counts.
            if ITTHON_SITE.search(ln):
                ln = re.sub(r'(?i)(?<![\w.])[\w-]+\.hu(?!\w)', ' ', ln)
            if not re.search(r'(?i)(?<!\w)' + rx + r'(?!\w)', ln):
                continue
            if ITTHON_NO_DATA.search(ln) or (ITTHON_RESULT.search(ln) and not ITTHON_NOT_MEASURED.search(ln)):
                ok = True
                break
        if not ok:
            gaps.append(name)
    return gaps


SITE_DOMAINEK = ["emag.hu", "alza.hu", "notino.hu", "douglas.hu"]
SITE_SOR = re.compile(r"(?i)(?<!\w)site(:|-szűrt|-próba| szűrt)")
def site_hibak(b):
    talalt = {}
    for s in b.splitlines():
        if not SITE_SOR.search(s): continue
        low = s.lower()
        for d in SITE_DOMAINEK:
            if d not in low: continue
            utana = low.split(d, 1)[1]
            kov = [utana.find(x) for x in SITE_DOMAINEK if x != d and x in utana]
            sajat = utana[:min(kov)] if kov else utana
            # a list ("emag.hu, alza.hu): 0") shares the result after it; a domain with its own text keeps its own
            for resz in [sajat] + ([utana] if kov and re.fullmatch(r"[\s,/()]*", sajat) else []):
                m = re.search(r"(?<![\w.])(\d+)(?!\w|[.,]\d)", resz)
                if m: talalt[d] = int(m.group(1)); break
                if re.search(r"(?i)nincs találat|nem hozott találatot|nem talált", resz): talalt[d] = 0; break
    hibak = [f"ITTHON: site-próba talált ({d}: {n}), itthon kapható (Klodel 39454)" for d, n in talalt.items() if n > 0]
    hianyzik = [d for d in SITE_DOMAINEK if d not in talalt]
    if hianyzik:
        hibak.append("ITTHON: site-próba eredménnyel hiányzik: " + ", ".join(hianyzik) + " (Klodel 39454)")
    return hibak
