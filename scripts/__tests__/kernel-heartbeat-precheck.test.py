#!/usr/bin/env python3
"""Tests for Kernel's heartbeat preCheck (scripts/prechecks/kernel_heartbeat_precheck.py).

Each test runs the REAL wrapper (`bash kernel-<mode>-precheck.sh`, as runPreCheck does) with the KHP_* paths
pointed at throwaway files, and reads stdout and the exit code. Nothing touches the live store, the guard state or
~/.gitconfig. The contract under test: "SKIP" only when nothing is to be done; every alert case and every error
case prints something else (or nothing), so the round runs.
"""
import hashlib
import json
import os
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PRECHECKS = os.path.join(os.path.dirname(HERE), 'prechecks')


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.now = int(time.time())
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('KHP_')}
        self.env.update({
            'KHP_ROOT': self.d,
            'KHP_NOW': str(self.now),
            'KHP_QUOTA_FILE': os.path.join(self.d, 'q.jsonl'),
            'KHP_DISK_PATH': self.d,
            'KHP_GUARD_STATE': os.path.join(self.d, 'guard.json'),
            'KHP_GITCONFIG': os.path.join(self.d, 'gitconfig'),
        })

    def tearDown(self):
        self.tmp.cleanup()

    def run_mode(self, mode, **extra):
        env = dict(self.env, **extra)
        r = subprocess.run(['bash', os.path.join(PRECHECKS, f'kernel-{mode}-precheck.sh')],
                           env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, 'the wrapper always exits 0')
        return r.stdout.strip()


class Quota(Base):
    def q(self, pct, age_s, raw=None):
        with open(self.env['KHP_QUOTA_FILE'], 'w') as f:
            f.write('{"old": 1}\n')
            f.write(raw if raw is not None else json.dumps(
                {'seats': {'fleet': {'sevenDay': {'pct': pct}, 'status': 'ok'}}, 'ts': self.now - age_s}) + '\n')

    def test_low_fresh_skips(self):
        self.q(9, 60)
        self.assertEqual(self.run_mode('quota'), 'SKIP')

    def test_99_skips(self):
        self.q(99, 60)
        self.assertEqual(self.run_mode('quota'), 'SKIP')

    def test_100_wakes(self):
        self.q(100, 60)
        self.assertIn('pct 100', self.run_mode('quota'))

    def test_over_wakes(self):
        self.q(130, 60)
        self.assertIn('>= 100', self.run_mode('quota'))

    def test_stale_line_wakes(self):
        self.q(9, 7200)
        self.assertIn('min old', self.run_mode('quota'))

    def test_errors_never_skip(self):
        cases = {'missing file': None, 'empty file': '', 'broken json': '{broken\n',
                 'pct null': json.dumps({'seats': {'fleet': {'sevenDay': {'pct': None}}}, 'ts': self.now}) + '\n',
                 'pct bool': json.dumps({'seats': {'fleet': {'sevenDay': {'pct': True}}}, 'ts': self.now}) + '\n',
                 'no fleet seat': json.dumps({'seats': {}, 'ts': self.now}) + '\n',
                 'ts string': json.dumps({'seats': {'fleet': {'sevenDay': {'pct': 9}}}, 'ts': 'x'}) + '\n'}
        for name, raw in cases.items():
            with self.subTest(name):
                p = self.env['KHP_QUOTA_FILE']
                if raw is None:
                    if os.path.exists(p):
                        os.unlink(p)
                else:
                    with open(p, 'w') as f:
                        f.write(raw)
                self.assertEqual(self.run_mode('quota'), '')


class Disk(Base):
    def test_enough_space_skips(self):
        self.assertEqual(self.run_mode('disk', KHP_DISK_MIN_GIB='0.001'), 'SKIP')

    def test_low_space_wakes(self):
        self.assertIn('< 1e+06 GiB', self.run_mode('disk', KHP_DISK_MIN_GIB='1000000'))

    def test_default_threshold_is_10(self):
        out = self.run_mode('disk', KHP_DISK_MIN_GIB='')
        st = os.statvfs(self.d)
        free = st.f_bavail * st.f_frsize / 2**30
        self.assertEqual(out, 'SKIP' if free >= 10 else out)
        if free < 10:
            self.assertIn('< 10 GiB', out)

    def test_missing_path_never_skips(self):
        self.assertEqual(self.run_mode('disk', KHP_DISK_PATH=os.path.join(self.d, 'nope')), '')


class Gitconfig(Base):
    def write_cfg(self, text):
        with open(self.env['KHP_GITCONFIG'], 'w') as f:
            f.write(text)
        return sha(self.env['KHP_GITCONFIG'])

    def state(self, baseline, reported=None):
        with open(self.env['KHP_GUARD_STATE'], 'w') as f:
            json.dump({'baseline': baseline, 'reported': reported}, f)

    RESET = '[credential]\n\thelper = osxkeychain\n\thelper =\n'

    def test_baseline_match_skips(self):
        self.state(self.write_cfg(self.RESET))
        self.assertEqual(self.run_mode('gitconfig'), 'SKIP')

    def test_no_state_runs(self):
        self.write_cfg(self.RESET)
        self.assertEqual(self.run_mode('gitconfig'), '')

    def test_state_without_baseline_runs(self):
        self.write_cfg(self.RESET)
        self.state(None)
        self.assertEqual(self.run_mode('gitconfig'), '')

    def test_match_with_leftover_mark_runs_once(self):
        self.state(self.write_cfg(self.RESET), reported='old|True')
        self.assertEqual(self.run_mode('gitconfig'), '')

    def test_new_change_runs(self):
        base = self.write_cfg(self.RESET)
        self.state(base)
        self.write_cfg(self.RESET + '\n')
        self.assertEqual(self.run_mode('gitconfig'), '')

    def test_already_reported_change_skips(self):
        base = self.write_cfg(self.RESET)
        cur = self.write_cfg(self.RESET + '\n')
        self.state(base, reported=f'{cur}|True')
        self.assertEqual(self.run_mode('gitconfig'), 'SKIP')

    def test_second_change_after_a_reported_one_runs(self):
        base = self.write_cfg(self.RESET)
        first = self.write_cfg(self.RESET + '\n')
        self.state(base, reported=f'{first}|True')
        self.write_cfg(self.RESET + '\n\n')
        self.assertEqual(self.run_mode('gitconfig'), '')

    def test_reset_removed_same_sha_runs(self):
        base = self.write_cfg('[credential]\n\thelper = osxkeychain\n')
        self.state(base)
        self.assertEqual(self.run_mode('gitconfig'), '')

    def test_missing_gitconfig_runs(self):
        self.state('abc')
        self.assertEqual(self.run_mode('gitconfig'), '')

    def test_guard_state_is_not_written(self):
        base = self.write_cfg(self.RESET)
        self.state(base)
        self.write_cfg(self.RESET + '\n')
        before = open(self.env['KHP_GUARD_STATE']).read()
        self.run_mode('gitconfig')
        self.assertEqual(open(self.env['KHP_GUARD_STATE']).read(), before)


class Wrapper(Base):
    def test_unknown_mode_never_skips(self):
        r = subprocess.run(['python3', '-I', os.path.join(PRECHECKS, 'kernel_heartbeat_precheck.py'), 'bogus'],
                           env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(r.stdout, '')
        self.assertNotEqual(r.returncode, 0)


if __name__ == '__main__':
    unittest.main()
