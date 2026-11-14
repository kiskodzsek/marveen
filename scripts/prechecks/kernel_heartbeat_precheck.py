#!/usr/bin/env python3
"""preCheck for Kernel's three silent-by-default heartbeats (Klodel 42455/42460).

  kernel_heartbeat_precheck.py quota      kernel-flotta-keret (cron */15): the fleet seat's 7-day pct >= 100
  kernel_heartbeat_precheck.py disk       kernel-lemez-10gib  (cron */30): free space < 10 GiB
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
DISK_PATH = ROOT
DISK_MIN_GIB = 10               # the task's own threshold ("< 10 GiB"); GiB = 2**30 bytes, as df -k / host-monitor
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
    if not (pct < QUOTA_LIMIT_PCT):
        return f'PRECHECK: fleet 7d pct {pct:g} (>= {QUOTA_LIMIT_PCT}), status {status}.'
    return 'SKIP'


def disk():
    st = os.statvfs(DISK_PATH)
    free_gib = st.f_bavail * st.f_frsize / 2**30
    if not (free_gib >= DISK_MIN_GIB):
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
