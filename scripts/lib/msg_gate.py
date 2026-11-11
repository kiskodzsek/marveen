#!/usr/bin/env python3
"""msg_gate.py -- the pre-send gate of scripts/agent-msg.sh (card aba42256, DREAM 11-11).

    printf '%s' "$TEXT" | python3 -I scripts/lib/msg_gate.py --from <a> --to <b>

Exit 0: send. Exit 3: refused, the reasons are on stderr (names and counts only, never the matched
text). Any other exit: the gate itself failed, which is not a verdict on the text.

Two rules:

1. Secret shapes, every sender and recipient. The patterns are NOT copied here: they are read at
   run time from SECRET_PATTERNS in src/security/secret-gate.ts, the list the commit gate and the
   transcript masking already use, so a pattern added there covers messages too. If that file is
   missing or yields fewer than MIN_PATTERNS, the gate fails (exit 4): a gate that silently runs
   with no patterns would answer "clean" for everything.
   Measured 2026-11-11 on 30 days of agent_messages (32 137 rows): 4 hits, all 2026-10-12, a
   deliberately fake low-entropy Stripe placeholder; nothing else.

2. Majsztro's traffic (--from or --to in STRICT, default "majsztro"): Klodel filters Majsztro's
   text before Patrik sees it, and Majsztro is a marketing agent with a budget that hit 100 %.
   - Longer than MAX_CHARS characters (default 12 000): refused, put the material in a file under
     agents/majsztro/kontext/ and send the path. Measured over 7 days: 5 messages above 12 000 in
     the whole fleet, 4 of them to majsztro (longest 22 789).
   - An e-mail address outside our own domains (default marabel.hu, myshp.hu, subdomains too):
     refused. Measured over 30 days of Majsztro traffic: 11 addresses, 10 were our own marabel.hu
     address quoted in copy text (allowed), 1 a third party's press address.
   Other pairs are not length- or e-mail-gated: 94 fleet messages a week carry an address,
   mostly our own, in mail and order work where the address is the subject.

Env (the suite uses them): MARVEEN_MSG_GATE_SECRET_SRC, MARVEEN_MSG_GATE_STRICT (comma list),
MARVEEN_MSG_GATE_MAX_CHARS, MARVEEN_MSG_GATE_OWN_DOMAINS (comma list).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SRC = os.path.join(HERE, '..', '..', 'src', 'security', 'secret-gate.ts')
MIN_PATTERNS = 10

EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})')
# One entry per line in secret-gate.ts:  { name: '...', pattern: /.../flags },
ENTRY = re.compile(r"\{\s*name:\s*'([^']+)',\s*pattern:\s*/((?:\\.|[^/\\\n])+)/([a-z]*)\s*\}")


def die(msg):
    print('msg_gate: ' + msg, file=sys.stderr)
    sys.exit(4)


def load_secret_patterns(path):
    try:
        with open(path, encoding='utf-8') as f:
            src = f.read()
    except OSError as e:
        die('cannot read the secret patterns at %s (%s)' % (path, e.strerror))
    start = src.find('export const SECRET_PATTERNS')
    if start < 0:
        die('SECRET_PATTERNS not found in %s' % path)
    end = src.find('\n];', start)
    if end < 0:
        die('SECRET_PATTERNS has no end in %s' % path)
    out = []
    for name, body, flags in ENTRY.findall(src[start:end]):
        if set(flags) - {'i'}:
            die('pattern %r has flags %r this gate does not translate' % (name, flags))
        try:
            out.append((name, re.compile(body, re.I if 'i' in flags else 0)))
        except re.error as e:
            die('pattern %r does not compile in Python: %s' % (name, e))
    if len(out) < MIN_PATTERNS:
        die('only %d secret patterns read from %s (expected at least %d)' % (len(out), path, MIN_PATTERNS))
    return out


def csv_env(name, default):
    return [x.strip().lower() for x in os.environ.get(name, default).split(',') if x.strip()]


def main(argv):
    frm = to = None
    i = 0
    while i < len(argv):
        if argv[i] == '--from' and i + 1 < len(argv):
            frm = argv[i + 1]; i += 2
        elif argv[i] == '--to' and i + 1 < len(argv):
            to = argv[i + 1]; i += 2
        else:
            die('usage: msg_gate.py --from <a> --to <b>  (text on stdin)')
    if frm is None or to is None:
        die('usage: msg_gate.py --from <a> --to <b>  (text on stdin)')
    try:
        max_chars = int(os.environ.get('MARVEEN_MSG_GATE_MAX_CHARS', '12000'))
    except ValueError:
        die('MARVEEN_MSG_GATE_MAX_CHARS is not a number')

    text = sys.stdin.buffer.read().decode('utf-8', errors='replace')
    patterns = load_secret_patterns(os.environ.get('MARVEEN_MSG_GATE_SECRET_SRC', DEFAULT_SRC))

    reasons = []
    hits = [name for name, rx in patterns if rx.search(text)]
    if hits:
        reasons.append('titok-minta: %s. Titokra csak névvel és hellyel hivatkozz '
                       '(pl. "STRIPE_SECRET_KEY a Vaultban"); helykitöltő így: <helykitöltő>.'
                       % ', '.join(hits))

    strict = csv_env('MARVEEN_MSG_GATE_STRICT', 'majsztro')
    pair = {frm.lower(), to.lower()}
    if pair & set(strict):
        who = ', '.join(sorted(pair & set(strict)))
        if len(text) > max_chars:
            reasons.append('%d karakter, a határ %d (%s forgalma). Az anyagot tedd fájlba '
                           '(agents/majsztro/kontext/), és az útvonalat küldd.'
                           % (len(text), max_chars, who))
        own = csv_env('MARVEEN_MSG_GATE_OWN_DOMAINS', 'marabel.hu,myshp.hu')
        foreign = 0
        for m in EMAIL.finditer(text):
            d = m.group(1).lower()
            if not any(d == o or d.endswith('.' + o) for o in own):
                foreign += 1
        if foreign:
            reasons.append('%d e-mail-cím nem a saját domainjeinkről (%s; %s forgalma). '
                           'Ne a címet küldd, hanem hogy kié és hol található.'
                           % (foreign, ', '.join(own), who))

    if reasons:
        for r in reasons:
            print('  - ' + r, file=sys.stderr)
        return 3
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
