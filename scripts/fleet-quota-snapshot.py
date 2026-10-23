#!/usr/bin/env python3
"""One pass of the fleet quota snapshot (launchd: every 15 min).

    fleet-quota-snapshot.py            read, append to the history, alert on a band crossing
    fleet-quota-snapshot.py --status   read and print (with the count of due, unsent alerts), no write
    fleet-quota-snapshot.py --test-alert   send one real probe message to the main agent

Why (2026-10-23, Klodel 14644, Patrik TG 6032): the fleet's Claude seat had no
readable quota at 07:22. store/.claude-rate-limits.json is written by the
statusLine, and the statusLine's rate_limits block never arrives on a
setup-token login (src/web/quota.ts, QUOTAMOD1005) -- the whole fleet runs on
the setup-token, so that file is never created. limit-monitor.sh reads only
that file and is not scheduled on macOS; usage-collect is disabled. So there
was no history and no threshold alert. The dashboard does compute the quota,
from the agent-state-observer mod (store/mod-state), but only on request.

This pass asks the dashboard for exactly that computation (GET /api/overview:
`quota` = the fleet seat, `quotaSeats` = every agent on its own seat), so the
window rules stay in one place (quota.ts) and are not copied here.

Effects:
  - store/fleet-quota.jsonl: one line per run, every seat with its 5h / 7d
    percentage, reset time, status and age. Lines older than KEEP_DAYS are
    dropped when the oldest line is a day past that, not on every run.
  - an upward band crossing inside the same window (default 7d: 80/90/95,
    5h: 90) sends one inter-agent message to the main agent. The band is
    remembered per seat, window kind and reset time in
    store/.fleet-quota-alert.json, so a new window starts from zero and the
    same band is never sent twice. A failed send is not remembered, so the
    next run retries it.
  - the fleet seat going stale or missing (no fresh reading, see quota.ts
    maxAgeSec) sends one message per episode; it re-arms once a fresh
    reading is back.
  - The sender id is `fleet-quota`. POST /api/messages accepts it only when it
    is listed in SYSTEM_SENDER_IDS (.env); without that every alert is a 403.
    A send that fails is logged, counted into the history row (`unsent`) and
    shown by --status, so a rejected sender is visible, not a silent green.
  - It never restarts, pauses or switches anything.

Test hooks: FLEETQ_OVERVIEW_FILE (read the overview JSON from a file instead
of HTTP), FLEETQ_NOW (epoch), MARVEEN_STORE (state dir), FLEETQ_AGENT_MSG
(the agent-msg.sh to call), FLEETQ_MAIN_AGENT.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
INSTALL_DIR = os.path.dirname(HERE)
STORE = os.environ.get('MARVEEN_STORE') or os.path.join(INSTALL_DIR, 'store')
HISTORY = os.path.join(STORE, 'fleet-quota.jsonl')
ALERT_STATE = os.path.join(STORE, '.fleet-quota-alert.json')
LOG = os.path.join(STORE, 'fleet-quota.log')
URL = os.environ.get('FLEETQ_URL', 'http://localhost:3420/api/overview')
AGENT_MSG = os.environ.get('FLEETQ_AGENT_MSG') or os.path.join(HERE, 'agent-msg.sh')
MAIN_AGENT = os.environ.get('FLEETQ_MAIN_AGENT', 'klodel')
KEEP_DAYS = 35
BANDS = {
    'sevenDay': [80, 90, 95],
    'fiveHour': [90],
}
LABEL = {'sevenDay': '7 napos', 'fiveHour': '5 órás'}


def now_sec():
    raw = os.environ.get('FLEETQ_NOW')
    return int(raw) if raw else int(time.time())


def log(line):
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S') + ' ' + line + '\n')
    except OSError:
        pass


def read_overview():
    path = os.environ.get('FLEETQ_OVERVIEW_FILE')
    if path:
        with open(path) as f:
            return json.load(f)
    with open(os.path.join(STORE, '.dashboard-token')) as f:
        token = f.read().strip()
    req = urllib.request.Request(URL, headers={'Authorization': 'Bearer ' + token})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def window(w):
    if not isinstance(w, dict) or not isinstance(w.get('usedPercentage'), (int, float)):
        return None
    return {'pct': w['usedPercentage'], 'resetsAt': w.get('resetsAt'), 'expired': bool(w.get('expired'))}


def seats_of(overview):
    """{seat key: {status, ageSec, fiveHour, sevenDay, sources}}; 'fleet' is the shared seat."""
    out = {}
    pairs = [('fleet', overview.get('quota'))]
    pairs += [(s.get('key'), s.get('quota')) for s in overview.get('quotaSeats') or [] if isinstance(s, dict)]
    for key, q in pairs:
        if not key or not isinstance(q, dict):
            continue
        out[key] = {
            'status': q.get('status'),
            'ageSec': q.get('ageSec'),
            'fiveHour': window(q.get('fiveHour')),
            'sevenDay': window(q.get('sevenDay')),
            'sources': q.get('sourceAgents') or [],
        }
    return out


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_atomic(path, text):
    tmp = '%s.tmp.%d' % (path, os.getpid())
    with open(tmp, 'w') as f:
        f.write(text)
    os.replace(tmp, path)


def append_history(now, seats, unsent):
    row = {'ts': now, 'seats': seats}
    if unsent:
        row['unsent'] = unsent
    with open(HISTORY, 'a') as f:
        f.write(json.dumps(row, sort_keys=True) + '\n')
    try:
        with open(HISTORY) as f:
            first = json.loads(f.readline() or '{}').get('ts') or now
    except OSError:
        return
    except ValueError:
        first = 0  # a torn first line must not switch the trim off for good (Viktor 14713 INFO 6)
    cutoff = now - KEEP_DAYS * 86400
    if first >= cutoff - 86400:
        return
    keep = []
    with open(HISTORY) as f:
        for line in f:
            try:
                if (json.loads(line).get('ts') or 0) >= cutoff:
                    keep.append(line)
            except ValueError:
                pass  # a torn line from a crashed run is history nobody can read
    write_atomic(HISTORY, ''.join(keep))


def fmt_reset(epoch):
    if not isinstance(epoch, (int, float)):
        return 'ismeretlen'
    return time.strftime('%m-%d %H:%M', time.localtime(epoch))


def due_alerts(seats, state):
    """(messages, new state entries) for the band crossings and stale episodes not yet sent."""
    alerts = []
    for key, s in seats.items():
        if s['status'] != 'ok':
            continue
        for kind, bands in BANDS.items():
            w = s[kind]
            if not w or w['expired']:
                continue
            band = max([b for b in bands if w['pct'] >= b], default=0)
            sid = '%s|%s' % (key, kind)
            prev = state.get(sid) or {}
            sent = prev.get('band', 0) if prev.get('resetsAt') == w['resetsAt'] else 0
            if band > sent:
                seat = 'flotta seat' if key == 'fleet' else 'seat ' + key
                alerts.append((sid, {'resetsAt': w['resetsAt'], 'band': band},
                               '[FLOTTA-KERET] %s: a %s ablak %s%% (sáv %s%%), reset %s (Budapest). Forrás: /api/overview, %s.'
                               % (seat, LABEL[kind], w['pct'], band, fmt_reset(w['resetsAt']), ', '.join(s['sources']) or '-')))
    fleet = seats.get('fleet')
    stale = fleet is None or fleet['status'] != 'ok'
    if stale and not state.get('fleet|stale'):
        why = 'nincs adat' if fleet is None else '%s, kor %ss' % (fleet['status'], fleet['ageSec'])
        alerts.append(('fleet|stale', True,
                       '[FLOTTA-KERET] a flotta seat kvótája nem mérhető (%s): egyik stateObserver-es ügynök sem adott friss adatot. Forrás: /api/overview.' % why))
    return alerts, stale


def send(text):
    try:
        r = subprocess.run(['bash', AGENT_MSG, 'fleet-quota', MAIN_AGENT, '-'], input=text,
                           capture_output=True, text=True, timeout=180)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def main():
    args = sys.argv[1:]
    if '--test-alert' in args:
        # Go-live probe (Viktor 14713 M1): one REAL message through the same path
        # an alert takes. --status cannot prove delivery, and the sender id must
        # be accepted by POST /api/messages (SYSTEM_SENDER_IDS), see the installer.
        ok = send('[FLOTTA-KERET] próbaüzenet a telepítés ellenőrzéséhez, teendő nincs.')
        print('fleet-quota: test alert %s' % ('delivered' if ok else 'FAILED (is fleet-quota in SYSTEM_SENDER_IDS?)'))
        return 0 if ok else 1
    status_only = '--status' in args
    now = now_sec()
    try:
        seats = seats_of(read_overview())
    except Exception as e:  # dashboard down, token missing, bad JSON: one log line, no history row
        log('overview read FAILED: %s' % type(e).__name__)
        print('fleet-quota: overview read failed (%s)' % type(e).__name__, file=sys.stderr)
        return 1
    for key, s in sorted(seats.items()):
        p5 = s['fiveHour']['pct'] if s['fiveHour'] else '-'
        p7 = s['sevenDay']['pct'] if s['sevenDay'] else '-'
        print('%s %s 5h=%s%% 7d=%s%%' % (key, s['status'], p5, p7))
    state = load_json(ALERT_STATE, {})
    alerts, stale = due_alerts(seats, state)
    if status_only:
        # An alert that stays due run after run is one that never got through:
        # say so here, so a rejected sender is not a silent green.
        print('unsent alerts: %d%s' % (len(alerts), (' (last send failure %s)' % fmt_reset(state['lastSendFailure']))
                                        if state.get('lastSendFailure') else ''))
        return 0
    if not stale:
        state.pop('fleet|stale', None)
    unsent = []
    for sid, entry, text in alerts:
        if send(text):
            state[sid] = entry
            log('alert sent: ' + sid)
        else:
            unsent.append(sid)
            state['lastSendFailure'] = now
            log('alert send FAILED (retried next run): ' + sid)
    append_history(now, seats, unsent)
    write_atomic(ALERT_STATE, json.dumps(state, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
