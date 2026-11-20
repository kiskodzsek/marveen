#!/usr/bin/env python3
"""preCheck for Kernel's three silent-by-default heartbeats (Klodel 42455/42460).

  kernel_heartbeat_precheck.py quota      kernel-flotta-keret (cron */15): the fleet seat's 7-day pct >= 100,
                                          its 5-hour pct >= 100, or >= 80 not yet reported for that window,
                                          or the prompt's review time passed and not yet reported,
                                          or an own seat's (OWN_SEATS) while the sampler reads it
  kernel_heartbeat_precheck.py disk       kernel-lemez-10gib  (cron */30): free space < 10 GiB, and that low-disk
                                          stretch not yet reported
  kernel_heartbeat_precheck.py gitconfig  kernel-gitconfig-or (cron 17 * * * *): ~/.gitconfig vs the guard baseline

Why: the three tasks woke the model 96 + 48 + 24 = 168 times a day, and every wake from 19:30 to 21:30 on
2026-11-14 ended in "stay quiet". Each task's decision is a threshold on a file or on the free space, which this
script computes without the model; the model is woken only when the task has something to do.

Contract (schedule-runner.ts runPreCheck): stdout "SKIP" skips the LLM round; anything else runs it, other stdout
being prepended to the prompt as context. This script FAILS OPEN: the wrappers force exit 0 and print nothing when
it errors, so the round runs. It prints SKIP only when it positively measured "nothing to do".

Read-only. The gitconfig mode does NOT call the guard (agents/kernel/tools/gitconfig-guard/guard.py): the guard
records a new deviation as "reported" when it exits 1, so running it here would leave the woken round an exit 3
("already reported, stay quiet") and the alert would be lost. Nor does it import the guard: that file is outside
the reviewed tree. It repeats the guard's two reads (sha256 of the file, the global helper list ending with an
empty entry) and reads the guard's state file as data.

Install root = this file's grandparent (scripts/prechecks/ -> root). No environment variable changes a path or
a threshold (Viktor 42470: an env override could silence the check without a trust-hash change); the tests import
this module and set the constants in-process.

What reaches the prompt is built from numbers and fixed words only, never a raw data field (Viktor 42470 LOW 1:
the quota file is writable by any agent, and preCheck stdout lands in an owner-framed task body).
"""
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

QUOTA_FILE = os.path.join(ROOT, 'store', 'fleet-quota.jsonl')
QUOTA_MAX_AGE_S = 3600          # an older last line means the sampler stopped: wake the round to say so
QUOTA_MAX_FUTURE_S = 300        # a ts further ahead (ms instead of s, a wrong clock) also wakes the round
QUOTA_LIMIT_PCT = 100           # the task's own threshold ("ha >=100")
# The task's 5-hour rule (Klodel 47788, 2026-11-19): ">= 80 -> one line to Klodel, once per fiveHour.resetsAt;
# >= 100 -> one line". The round records what it sent in SENT_STATE, keyed by the window's resetsAt (a decimal
# string); this script only READS it. A key that is there means "already said", so 80-99 % skips; >= 100 % always
# wakes (the round itself stays quiet when that line was sent). An unreadable state file reads as empty: wake.
FIVE_HOUR_WARN_PCT = 80
FIVE_HOUR_LIMIT_PCT = 100
SENT_STATE = os.path.join(ROOT, 'agents', 'kernel', 'state', 'flotta-keret-jelzes.json')
# The prompt says it is out of date after 2026-11-21 03:00 Europe/Budapest (the fleet leaves the Dave seat):
# one line to Klodel. 1795226400 = 2026-11-21 03:00 CET (TZ=Europe/Budapest date -r). Recorded as PROMPT_KEY.
PROMPT_REVIEW_AT = 1795226400
PROMPT_KEY = 'prompt-review'
OWN_SEATS = ('own:dave',)       # own-seat agents the task watches too (card 6db4cc15, Klodel 43760)
DISK_PATH = ROOT
DISK_MIN_GIB = 10               # the task's own threshold ("< 10 GiB"); GiB = 2**30 bytes, as df -k / host-monitor
# The disk task's own rule is "under 10 GiB AND not yet reported since the last report": while one low-disk stretch
# lasts, every round after the first one stays quiet (2026-11-20: free 9 GiB from 02:50 on, reported once at 03:00,
# then a silent model wake every 30 minutes). The round records its report in DISK_SENT_STATE
# (last_sent_host_state_ts, epoch s); the host monitor writes one HOST_LOG line per band change. This script only
# READS both, and skips under the limit only when the last band line moves INTO a non-ok band and the report is at
# or after that line: a new stretch (or a warn -> crit move) has a later line and wakes. Any read or parse problem,
# a report from the future, or a last line back to ok wakes (fail-open). Only a band the disk opened counts
# (Viktor 48469 L1): the band is shared with load, swap and memory, and a band one of those holds may span a disk
# recovery and a new low stretch with no new line. Left over, not visible in the log: a band the disk opened that
# another reason keeps up through a full disk recovery and a new low stretch; that stretch is not re-reported.
DISK_SENT_STATE = os.path.join(ROOT, 'agents', 'kernel', 'state', 'lemez-10gib-jelzes.json')
HOST_LOG = os.path.join(ROOT, 'store', 'host-monitor.log')
BAND_LINE_RX = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) [a-z]{1,8} -> band=([a-z]{1,8})(?: |$)')
GUARD_STATE = os.path.join(ROOT, 'agents', 'kernel', 'state', 'gitconfig-guard.json')
GITCONFIG = os.path.expanduser('~/.gitconfig')
STATUS_RX = re.compile(r'[a-z_]{1,16}')


def _now():
    return time.time()


def _last_json_line(path):
    with open(path, 'rb') as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 65536))
        lines = [ln for ln in f.read().split(b'\n') if ln.strip()]
    if not lines:
        raise ValueError('empty file')
    return json.loads(lines[-1])


def _finite(v):
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)


def _sent_keys():
    """The keys of the round's sent-state file; empty on any read or parse error (the wake direction)."""
    try:
        with open(SENT_STATE, encoding='utf-8') as f:
            d = json.load(f)
    except Exception:
        return set()
    return set(k for k in d if isinstance(k, str)) if isinstance(d, dict) else set()


def quota():
    d = _last_json_line(QUOTA_FILE)
    seat = d['seats']['fleet']
    pct = seat['sevenDay']['pct']
    ts = d['ts']
    if not _finite(pct) or not _finite(ts):
        raise ValueError('pct or ts is not a finite number')   # NaN / Infinity too (Viktor 42470 LOW 2): fail-open
    status = seat.get('status')
    status = status if isinstance(status, str) and STATUS_RX.fullmatch(status) else '?'
    age = _now() - ts
    if not (-QUOTA_MAX_FUTURE_S <= age <= QUOTA_MAX_AGE_S):
        when = 'in the future' if age < 0 else f'{int(age // 60)} min old'
        return f'PRECHECK: the last fleet-quota.jsonl line is {when} (pct {pct:g}); check the sampler.'
    out = []
    if not (pct < QUOTA_LIMIT_PCT):
        out.append(f'PRECHECK: fleet 7d pct {pct:g} (>= {QUOTA_LIMIT_PCT}), status {status}.')
    # An agent on its own Team seat (authMode own_team) stops at that seat's weekly limit since the Team org has no
    # usage credits left (card 6db4cc15, Klodel 43760): the round reports it so the agent is moved to the fleet seat.
    # Only a seat the sampler still reads ('ok') counts: after the switch it turns stale and then drops out of the
    # line. The seat name in the output is this file's constant, never the file's text.
    for name in OWN_SEATS:
        own = d['seats'].get(name)
        if not isinstance(own, dict) or own.get('status') != 'ok':
            continue
        own_pct = own['sevenDay']['pct']
        if not _finite(own_pct):
            raise ValueError(f'{name} pct is not a finite number')   # fail-open, as for the fleet seat
        if not (own_pct < QUOTA_LIMIT_PCT):
            out.append(f'PRECHECK: {name} 7d pct {own_pct:g} (>= {QUOTA_LIMIT_PCT}), status ok.')
    # The 5-hour window of the fleet seat (Klodel 47788). Only a seat read 'ok' counts, as in the task text. No
    # fiveHour object: nothing to compare (the sampler gives none). A present but unreadable one: fail-open.
    five = seat.get('fiveHour')
    if status == 'ok' and five is not None:
        fpct, freset = five['pct'], five['resetsAt']
        if not _finite(fpct) or not _finite(freset):
            raise ValueError('fiveHour pct or resetsAt is not a finite number')
        if not (fpct < FIVE_HOUR_LIMIT_PCT):
            out.append(f'PRECHECK: fleet 5h pct {fpct:g} (>= {FIVE_HOUR_LIMIT_PCT}), resetsAt {int(freset)}.')
        elif not (fpct < FIVE_HOUR_WARN_PCT) and str(int(freset)) not in _sent_keys():
            out.append(f'PRECHECK: fleet 5h pct {fpct:g} (>= {FIVE_HOUR_WARN_PCT}), resetsAt {int(freset)}, '
                       f'not yet reported.')
    if _now() >= PROMPT_REVIEW_AT and PROMPT_KEY not in _sent_keys():
        out.append(f'PRECHECK: the prompt review time 2026-11-21 03:00 has passed, not yet reported '
                   f'(record it as "{PROMPT_KEY}").')
    return ' '.join(out) if out else 'SKIP'


def _disk_stretch_reported():
    """True only when the low-disk stretch going on now was already reported (see DISK_SENT_STATE); else False."""
    try:
        with open(DISK_SENT_STATE, encoding='utf-8') as f:
            sent = json.load(f).get('last_sent_host_state_ts')
        if not _finite(sent) or sent > _now() + QUOTA_MAX_FUTURE_S:
            return False
        with open(HOST_LOG, 'rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 65536))
            lines = f.read().decode('utf-8', 'replace').split('\n')
        band = [m for m in (BAND_LINE_RX.match(ln) for ln in lines) if m]
        # only a band the disk opened: a load or swap band may span a disk recovery and a new low stretch (no line)
        if not band or band[-1].group(2) == 'ok' or ' reason=free disk ' not in band[-1].string:
            return False
        start = time.mktime(time.strptime(band[-1].group(1), '%Y-%m-%d %H:%M:%S'))   # local time, as the monitor
        return sent >= start
    except Exception:
        return False


def disk():
    st = os.statvfs(DISK_PATH)
    free_gib = st.f_bavail * st.f_frsize / 2**30
    if not (free_gib >= DISK_MIN_GIB):
        if _disk_stretch_reported():
            return 'SKIP'
        return f'PRECHECK: free {free_gib:.2f} GiB (< {DISK_MIN_GIB:g} GiB).'
    return 'SKIP'


def _sha(path):
    try:
        with open(path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except FileNotFoundError:
        return 'MISSING'


def _reset_in_effect(path):
    # Same read as the guard: the global helper list, with this file as the global config, ends with an empty entry.
    env = {k: v for k, v in os.environ.items() if k not in ('GIT_CONFIG_GLOBAL', 'GIT_CONFIG_NOSYSTEM')}
    env['GIT_CONFIG_GLOBAL'] = path
    r = subprocess.run(['git', 'config', '--global', '--get-all', 'credential.helper'],
                       env=env, capture_output=True, text=True, timeout=5)
    vals = r.stdout.split('\n')[:-1] if r.stdout else []
    return bool(vals) and vals[-1] == ''


def gitconfig():
    try:
        with open(GUARD_STATE, encoding='utf-8') as f:
            st = json.load(f)
    except FileNotFoundError:
        return ''        # no baseline: the guard exits 2, the round must report it
    if not isinstance(st, dict) or not st.get('baseline'):
        return ''
    cur = _sha(GITCONFIG)
    effect = _reset_in_effect(GITCONFIG)
    if cur == st['baseline'] and effect:
        # the guard prints OK; a leftover "reported" mark is cleared by the guard itself, so let that round run once
        return 'SKIP' if not st.get('reported') else ''
    if st.get('reported') == f'{cur}|{effect}':
        return 'SKIP'    # the guard exits 3: this exact deviation was already reported
    return ''            # a new deviation: the round runs the guard, which exits 1 and reports


MODES = {'quota': quota, 'disk': disk, 'gitconfig': gitconfig}


def main(argv):
    if len(argv) != 1 or argv[0] not in MODES:
        return 2
    out = MODES[argv[0]]()
    if out:
        print(out)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
