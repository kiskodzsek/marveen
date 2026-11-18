#!/usr/bin/env python3
"""Számla-PDF letöltése szolgáltatói letöltő linkről (Patrik engedélye, TG 13722, 2026-11-02).

Szűk kapu a .channels-config 'curl https' tiltása mellé: CSAK az alábbi számlázó-hostokról,
CSAK GET, CSAK ~/Konyveles alá, és CSAK akkor ment, ha a válasz PDF (%PDF fejléc).
Billingo document-access oldalnál a HTML-ből kikeresi a PDF-letöltő linket (ugyanazon a hoston).

Használat: python3 -I scripts/szamla-letolto.py <url> <cél-fájl.pdf>
"""
import os, re, sys, urllib.parse, urllib.request

ALLOWED = {"app.billingo.hu", "api.billingo.hu", "www.innvoice.hu", "innvoice.hu",
           "www.szamlazz.hu", "szamlazz.hu", "www.szamlazoprogram.hu", "szamlazoprogram.hu"}
ROOT = os.path.realpath(os.path.expanduser("~/Konyveles"))
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) szamla-letolto/1.0"}


def host_ok(u):
    p = urllib.parse.urlparse(u)
    return p.scheme == "https" and p.hostname in ALLOWED


def get(u):
    if not host_ok(u):
        sys.exit(f"TILTOTT host: {urllib.parse.urlparse(u).hostname}")
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r:
        if not host_ok(r.geturl()):
            sys.exit(f"TILTOTT átirányítás: {urllib.parse.urlparse(r.geturl()).hostname}")
        return r.read(), r.headers.get("Content-Type", ""), r.geturl()


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    url, out = sys.argv[1], os.path.realpath(os.path.expanduser(sys.argv[2]))
    if not out.startswith(ROOT + os.sep) or not out.lower().endswith(".pdf"):
        sys.exit("A cél csak ~/Konyveles alatti .pdf lehet")
    body, ctype, final = get(url)
    if not body.startswith(b"%PDF"):
        html = body.decode("utf-8", "replace")
        cands = re.findall(r'href=["\']([^"\']+)["\']', html) + re.findall(r'"(https?://[^"\s]+)"', html)
        cands = [urllib.parse.urljoin(final, c.replace("&amp;", "&")) for c in cands]
        cands = [c for c in cands if host_ok(c) and re.search(r"download|pdf|letolt", c, re.I)]
        for c in dict.fromkeys(cands):
            b2, _, _ = get(c)
            if b2.startswith(b"%PDF"):
                body = b2
                break
        else:
            sys.exit(f"Nem PDF a válasz ({ctype}); jelölt linkek: {len(cands)}")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(body)
    print(f"OK {len(body)} bájt -> {out}")


if __name__ == "__main__":
    main()
