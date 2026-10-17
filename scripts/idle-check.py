#!/usr/bin/env python3
"""Tétlen ágens + nyitott in_progress kártya felderítése (Patrik, 2026-10-13 19:17).

Kimenet soronként: <ágens> <in_progress+planned kártyák száma>. Csak azok az ágensek, akiknek a
tmux-paneje üres promptnál áll (nem dolgozik) ÉS van in_progress, vagy urgent/high planned kártyájuk. A normal/low planned kártyát Klodel adja ki, mérlegelve a plan-tartalékot (Patrik 19:28: "nem kell automatikusan daráljunk mindent, te koordinálsz"). Üres kimenet =
nincs teendő. Csak olvas, semmit nem küld.

IDLEDEFER1017 (Bella jelzése, D20261017-1800 [1], Klodel 7526): a fókusz miatt halasztott
tervezett kártya nem számít nyitottnak, amíg a jelölt dátum el nem jön. Jelölés a kártya
címében vagy az UTOLSÓ kommentjében: "fókusz" vagy "halasztva" szó, utána legfeljebb 40
karakteren belül egy dátum (ÉÉÉÉ-HH-NN vagy HH-NN), opcionális utótaggal:
  "fókusz, 10-16 után" / "(fókusz 10-16)" / "fókusz ... 10-19-ig"  -> halasztva a dátum NAPJÁIG,
  "fókusz ... 10-19-től"                                           -> halasztva a dátum ELŐTTI napig.
Csak a planned kártyára vonatkozik; az in_progress mindig számít (azon valaki aktívan dolgozik).
Hiba (komment nem olvasható, rossz dátum) esetén a kártya számít: a hiba iránya a régi viselkedés,
nem a csend. A halasztás legfeljebb MAX_DEFER_DAYS napra szól: távolabbi dátumnál a kártya számít
(Viktor L1, df41a35c), így egy elírt vagy szándékos "fókusz 2099-12-31" nem némít el végleg egy kártyát.
Az assignee csak ágensnév-alakú lehet (Viktor L2): a kimeneti sor a Klodel-promptba és az
agent-msg hívásba kerül, ezért a más alakú assignee kártyái kimaradnak (stderr-re egy darabszám). Ennek a fájlnak az élő példánya az ops/idle-check.py (symlink ide).
"""
import collections
import datetime
import json
import re
import subprocess
import sys
import urllib.request

API = 'http://localhost:3420'
TOKEN_PATH = '/Users/klodel/marveen/store/.dashboard-token'

# Dave a saját seatjén fut, és nem állhat (Patrik TG 2307, 2026-10-14 15:18): ha üres a panelje,
# akkor is jelezzük ("dave-szabad"), ha nincs nyitott kártyája -- Klodel ilyenkor munkát ad neki
# a többi fejlesztőtől (Pixel, Kernel).
ALWAYS_BUSY = ('dave',)
SKIP_AGENTS = ('klodel', 'patrik')
MAX_DEFER_DAYS = 14
_AGENT_RE = re.compile(r'[a-z][a-z0-9_-]{0,31}')

_DEFER_RE = re.compile(
    r'(?:fókusz|fokusz|halasztva)[^\n]{0,40}?(?<!\d)(?:(\d{4})-)?(\d{1,2})-(\d{1,2})(?!\d)'
    r'(\s*után|-?\s*ig\b|-?\s*t[óő]l\b)?',
    re.IGNORECASE)


def defer_until(text, today):
    """The last day the text defers a card to (inclusive), or None. Several markers: the latest wins."""
    best = None
    for m in _DEFER_RE.finditer(text or ''):
        year, month, day, suffix = m.group(1), int(m.group(2)), int(m.group(3)), (m.group(4) or '').strip().lower()
        try:
            d = datetime.date(int(year) if year else today.year, month, day)
        except ValueError:
            continue
        # A bare HH-NN written in December for January means next year.
        if not year and (today - d).days > 183:
            d = d.replace(year=d.year + 1)
        if suffix.endswith(('tól', 'től')):
            d -= datetime.timedelta(days=1)
        if best is None or d > best:
            best = d
    return best


def is_deferred(card, last_comment, today):
    if card.get('status') != 'planned':
        return False
    until = [u for u in (defer_until(card.get('title', ''), today), defer_until(last_comment, today)) if u]
    # Each source's latest marker; one beyond the cap is ignored, so the card counts again.
    until = [u for u in until if (u - today).days <= MAX_DEFER_DAYS]
    return bool(until) and today <= max(until)


def counted(card):
    return not card.get('archived_at') and (
        card.get('status') == 'in_progress'
        or (card.get('status') == 'planned' and card.get('priority') in ('urgent', 'high')))


def idle_report(cards, pane_idle, last_comment, today):
    """The output lines. `last_comment(card_id)` may raise: then the card counts (fail toward the old behaviour)."""
    by_agent = collections.defaultdict(list)
    for c in cards:
        if counted(c):
            by_agent[c.get('assignee')].append(c)
    lines = []
    open_agents = set()
    invalid = [a for a in by_agent if a and not _AGENT_RE.fullmatch(a)]
    if invalid:
        # Count only: the raw value is exactly what must not reach a prompt or a command line.
        print(f'idle-check: skipped {len(invalid)} assignee(s) not shaped like an agent name', file=sys.stderr)
    for agent in sorted(a for a in by_agent if a and a not in invalid):
        if agent in SKIP_AGENTS:
            continue
        if not pane_idle(agent):
            # A busy agent is never reported; it still "has open cards" for the ALWAYS_BUSY check.
            open_agents.add(agent)
            continue
        n = 0
        for c in by_agent[agent]:
            try:
                deferred = c.get('status') == 'planned' and is_deferred(c, last_comment(c['id']), today)
            except Exception:
                deferred = False
            if not deferred:
                n += 1
        if n:
            open_agents.add(agent)
            lines.append(f'{agent} {n}')
    for agent in ALWAYS_BUSY:
        if agent not in open_agents and pane_idle(agent):
            lines.append(f'{agent}-szabad 0')
    return lines


def pane_idle(agent):
    try:
        pane = subprocess.run(['tmux', 'capture-pane', '-p', '-t', f'agent-{agent}'],
                              capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return False
    if not pane:
        return False
    busy = 'esc to interrupt' in pane or 'to interrupt)' in pane
    lines = [l for l in pane.splitlines() if l.strip()]
    return any(l.strip() == '❯' for l in lines[-4:]) and not busy


def _get(path, token, timeout):
    req = urllib.request.Request(API + path, headers={'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def main():
    with open(TOKEN_PATH) as fh:
        token = fh.read().strip()
    cards = _get('/api/kanban', token, 10)

    def last_comment(card_id):
        rows = _get(f'/api/kanban/{card_id}/comments', token, 3)
        rows = rows.get('comments', rows) if isinstance(rows, dict) else rows
        return max(rows, key=lambda r: r.get('id', 0)).get('content', '') if rows else ''

    for line in idle_report(cards, pane_idle, last_comment, datetime.date.today()):
        print(line)


if __name__ == '__main__':
    main()
