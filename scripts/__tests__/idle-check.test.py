#!/usr/bin/env python3
"""IDLEDEFER1017: the idle watcher must not wake an agent for a planned card that is
deferred by a focus marker until the marked date (Bella, D20261017-1800 [1]; Klodel 7526).

Pinned cases:
  1. the marker forms: "fókusz, 10-16 után", "(fókusz 10-16)", "-ig", "-tól/-től", full date,
     "halasztva", a December note for January, an invalid date, unrelated dates
  2. the marker is read from the title and from the LAST comment only
  3. deferred only up to and including the day; the day after it counts again
  4. in_progress always counts, even with a marker
  5. a comment read error counts the card (old behaviour, never silence)
  6. the output keeps the old shape: "<agent> <n>", busy agents not printed,
     klodel/patrik skipped, "dave-szabad 0" when Dave is idle with nothing countable
  7. a marker more than MAX_DEFER_DAYS ahead is ignored: the card counts (Viktor L1)
  8. an assignee not shaped like an agent name never reaches the output, and its raw
     value is not echoed to stderr either (Viktor L2)
  9. IDLEPANE1108: a pane with a running spinner or token counter is busy even when the
     "esc to interrupt" tail is cut off and the empty "❯" box shows; a finished turn
     ("Sautéed for 35s · done", "Churned for 2m 3s") is idle (Klodel 32781)
 10. IDLEBG1121 (Klodel 49636): an idle agent waiting for its background run keeps its line with
     " hatter-futas <pid>" (a bg-run.py / detach.py under agents/<agent>/, by script path or working
     folder) or " hatter-futas shell-<N>" (the pane's "N shell(s) still running"); the pid wins;
     no mark without either, on a ps error, or for a runner outside agents/<agent>/; only printed
     agents are asked; the lines without a mark keep their old shape; the runner counts only as the
     script of a python[0-9.]* interpreter after argument-free flags, and a throwing pane capture
     means no mark, not a lost report (Viktor 49638)
"""
import contextlib
import datetime
import importlib.util
import io
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location('idle_check', os.path.join(HERE, '..', 'idle-check.py'))
ic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ic)

D = datetime.date
TODAY = D(2026, 10, 16)
NEXT = D(2026, 10, 17)


def card(cid, agent, status='planned', priority='high', title='munka', archived=None):
    return {'id': cid, 'assignee': agent, 'status': status, 'priority': priority, 'title': title, 'archived_at': archived}


class DeferUntil(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(ic.defer_until('fókusz, 10-16 után', TODAY), D(2026, 10, 16))
        self.assertEqual(ic.defer_until('senki nem dolgozik rajta most (fókusz 10-16), ezért tervezett.', TODAY), D(2026, 10, 16))
        self.assertEqual(ic.defer_until('Fókusz miatt áll, 10-19-ig', TODAY), D(2026, 10, 19))
        self.assertEqual(ic.defer_until('fókusz: hétfőtől, 10-19-től', TODAY), D(2026, 10, 18))
        self.assertEqual(ic.defer_until('FÓKUSZ 2026-10-20 után', TODAY), D(2026, 10, 20))
        self.assertEqual(ic.defer_until('halasztva 10-21-ig', TODAY), D(2026, 10, 21))
        self.assertEqual(ic.defer_until('fokusz 10-16', TODAY), D(2026, 10, 16))

    def test_year_rollover_and_bad_input(self):
        self.assertEqual(ic.defer_until('fókusz, 01-05 után', D(2026, 12, 20)), D(2027, 1, 5))
        self.assertIsNone(ic.defer_until('fókusz, 02-30 után', TODAY))
        self.assertIsNone(ic.defer_until('', TODAY))
        self.assertIsNone(ic.defer_until(None, TODAY))

    def test_needs_the_keyword_and_a_near_date(self):
        self.assertIsNone(ic.defer_until('határidő 10-30, PR #398', TODAY))
        self.assertIsNone(ic.defer_until('fókusz' + ' ' * 60 + '10-30', TODAY))
        self.assertIsNone(ic.defer_until('fókusz nélkül', TODAY))

    def test_latest_marker_wins(self):
        self.assertEqual(ic.defer_until('fókusz 10-16 után; fókusz 10-19-ig', TODAY), D(2026, 10, 19))


class IsDeferred(unittest.TestCase):
    def test_title_or_last_comment_until_the_day(self):
        c = card('a', 'bella', title='Bella: X (fókusz, 10-16 után)')
        self.assertTrue(ic.is_deferred(c, '', TODAY))
        self.assertFalse(ic.is_deferred(c, '', NEXT))
        plain = card('b', 'bella')
        self.assertTrue(ic.is_deferred(plain, 'Klodel: (fókusz 10-16)', TODAY))
        self.assertFalse(ic.is_deferred(plain, 'Klodel: (fókusz 10-16)', NEXT))
        self.assertFalse(ic.is_deferred(plain, 'nincs jelölés', TODAY))

    def test_cap(self):
        cap = TODAY + datetime.timedelta(days=ic.MAX_DEFER_DAYS)
        self.assertTrue(ic.is_deferred(card('f', 'bella'), f'fókusz {cap.isoformat()}-ig', TODAY))
        self.assertFalse(ic.is_deferred(card('f', 'bella'), f'fókusz {(cap + datetime.timedelta(days=1)).isoformat()}-ig', TODAY))
        self.assertFalse(ic.is_deferred(card('g', 'bella', title='fókusz 2099-12-31'), '', TODAY))
        # A capped title marker does not hide a valid comment marker.
        self.assertTrue(ic.is_deferred(card('h', 'bella', title='fókusz 2099-12-31'), 'fókusz 10-19-ig', TODAY))

    def test_in_progress_is_never_deferred(self):
        self.assertFalse(ic.is_deferred(card('c', 'bella', status='in_progress', title='fókusz, 10-16 után'), '', TODAY))


class Report(unittest.TestCase):
    def run_report(self, cards, idle, comments, today=TODAY):
        asked = []

        def last_comment(cid):
            asked.append(cid)
            v = comments.get(cid, '')
            if isinstance(v, Exception):
                raise v
            return v
        return ic.idle_report(cards, lambda a: a in idle, last_comment, today), asked

    def test_bella_case(self):
        cards = [card(f'b{i}', 'bella') for i in range(5)]
        comments = {c['id']: 'Klodel 11:1x: senki nem dolgozik rajta most (fókusz 10-16), ezért tervezett.' for c in cards}
        out, _ = self.run_report(cards, {'bella'}, comments, TODAY)
        self.assertEqual(out, [])
        out, _ = self.run_report(cards, {'bella'}, comments, NEXT)
        self.assertEqual(out, ['bella 5'])

    def test_mixed_counts_and_old_shape(self):
        cards = [
            card('1', 'bella', title='X (fókusz, 10-16 után)'),
            card('2', 'bella', status='in_progress', title='Y (fókusz, 10-16 után)'),
            card('3', 'bella', priority='normal'),            # normal planned: never counted
            card('4', 'bella', archived=123),                  # archived: never counted
            card('5', 'mira'),                                 # busy agent: not printed
            card('6', 'klodel'),                               # skipped
            card('7', 'pixel'),
        ]
        out, asked = self.run_report(cards, {'bella', 'klodel', 'pixel'}, {}, TODAY)
        self.assertEqual(out, ['bella 1', 'pixel 1'])
        self.assertNotIn('5', asked)                           # no comment read for a busy agent
        self.assertNotIn('2', asked)                           # nor for in_progress

    def test_comment_error_counts_the_card(self):
        out, _ = self.run_report([card('e', 'bella')], {'bella'}, {'e': OSError('down')}, TODAY)
        self.assertEqual(out, ['bella 1'])

    def test_invalid_assignee_is_dropped(self):
        bad = ['x; curl evil\nIGNORE ALL', 'Bella', 'bella\n', '$(id)', 'a' * 33, '-x']
        cards = [card(f'i{n}', a) for n, a in enumerate(bad)] + [card('ok', 'bella')]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            out, asked = self.run_report(cards, set(bad) | {'bella'}, {}, TODAY)
        self.assertEqual(out, ['bella 1'])
        self.assertEqual(asked, ['ok'])
        self.assertIn(f'skipped {len(bad)} assignee', err.getvalue())
        self.assertNotIn('curl', err.getvalue())
        self.assertNotIn('$(id)', err.getvalue())

    def test_dave_free_when_everything_is_deferred(self):
        cards = [card('d', 'dave', title='Z (fókusz, 10-16 után)')]
        out, _ = self.run_report(cards, {'dave'}, {}, TODAY)
        self.assertEqual(out, ['dave-szabad 0'])
        out, _ = self.run_report(cards, {'dave'}, {}, NEXT)
        self.assertEqual(out, ['dave 1'])
        out, _ = self.run_report([], set(), {}, TODAY)
        self.assertEqual(out, [])



BOX = "─" * 60 + "\n❯ \n" + "─" * 60 + "\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"


class PaneTextIdle(unittest.TestCase):
    def test_unfurling_cut_off_is_busy(self):
        # Dave's pane at 19:54: the spinner line lost its "esc to interrupt" tail
        self.assertFalse(ic.pane_text_idle("worktree nyitás\n· Unfurling… (2m 27s\n" + BOX))

    def test_spinner_with_counter_is_busy(self):
        self.assertFalse(ic.pane_text_idle("szöveg\n✻ Befuddling… (14s · ↓ 802 tokens · thought for 7s)\n" + BOX))

    def test_running_subagent_rows_are_busy(self):
        pane = "  ⏺ main\n  ◯ general-purpose  Reading orders table… 1m 6s · ↓ 159.6k tokens\n" + BOX
        self.assertFalse(ic.pane_text_idle(pane))

    def test_old_tail_check_still_busy(self):
        self.assertFalse(ic.pane_text_idle("x\n" + BOX.rstrip("\n") + " · esc to interrupt\n"))

    def test_finished_turn_is_idle(self):
        self.assertTrue(ic.pane_text_idle("megszokott módon jön.\n✻ Sautéed for 35s · done 7:20 PM\n" + BOX))
        self.assertTrue(ic.pane_text_idle("kész.\n✻ Churned for 2m 3s\n" + BOX))

    def test_no_prompt_or_empty_is_not_idle(self):
        self.assertFalse(ic.pane_text_idle(""))
        self.assertFalse(ic.pane_text_idle("valami fut, prompt nélkül\n"))

PY = '/opt/homebrew/Cellar/python@3.15/3.15.0/Frameworks/Python.framework/Versions/3.15/Resources/Python.app/Contents/MacOS/Python'
R = '/Users/klodel/marveen'
DONE_SHELLS = "kész.\n✻ Baked for 34s · done 10:46 AM · 2 shells still running\n" + BOX


class BackgroundWait(unittest.TestCase):
    def test_shells_from_the_pane(self):
        self.assertEqual(ic.pane_shells_running(DONE_SHELLS), 2)
        self.assertEqual(ic.pane_shells_running("x\n  1 shell still running\n" + BOX), 1)
        self.assertEqual(ic.pane_shells_running("✻ Churned for 2m 3s\n" + BOX), 0)
        self.assertEqual(ic.pane_shells_running(""), 0)
        old = "✻ Baked for 3s · done · 4 shells still running\n" + "sor\n" * ic.BUSY_TAIL + BOX
        self.assertEqual(ic.pane_shells_running(old), 0)  # scrolled out of the tail: not the current state

    def test_runners_by_script_path_and_by_cwd(self):
        ps = '\n'.join([
            f' 55973 {PY} -I {R}/agents/dave/bin/bg-run.py {R}/agents/dave/work/r4/bg.log bash x',
            f' 66633 {PY} -I bin/bg-run.py {R}/agents/dave/work/r5/bg.log bash y',
            f'   901 /usr/bin/python3 -I -B {R}/agents/kernel/tools/detach.py /tmp/l -- npm test',
            f'   902 /usr/bin/python3 -I bin/bg-run.py /tmp/l sleep 9',             # cwd outside agents/
            f'   903 /usr/bin/python3 /tmp/bg-run.py /tmp/l sleep 9',               # script outside agents/
            f'   904 /usr/bin/grep -n bg-run.py {R}/agents/dave/x',                 # not a Python runner
            f'   905 /usr/bin/python3 {R}/agents/../store/bg-run.py l',             # .. out of agents/
            f'   906 /usr/bin/python3 {R}/agents/Bad Name/bg-run.py l',
            f'   907 /usr/bin/python3 {R}/agents/viktor/work/other.py bg-run.py',  # the runner is an argument
            'garbage line', '',
        ])
        cwds = {66633: f'{R}/agents/dave', 902: '/private/tmp', 904: f'{R}/agents/dave', 907: f'{R}/agents/viktor'}
        runs = ic.bg_runs(ps, cwd=lambda pid: cwds.get(pid, ''))
        self.assertEqual(dict(runs), {'dave': [55973, 66633], 'kernel': [901]})

    def test_runner_only_as_the_script_of_a_real_interpreter(self):
        v = f'{R}/agents/viktor/bin/bg-run.py'
        ps = '\n'.join([
            f' 801 /usr/bin/python3 -W {v} /tmp/evil.py',       # the runner is -W's argument (Viktor 49638)
            f' 802 /usr/bin/python3 - {v}',                     # stdin script, the runner is an argument
            f' 803 /usr/bin/python3 -c {v}',                    # -c code
            f' 804 /tmp/python-not-an-interpreter {v}',         # not a Python interpreter name
            f' 805 /usr/bin/python3 -m {v}',                    # -m module
            f' 811 /usr/bin/python3.12 -IB {R}/agents/dave/bin/bg-run.py l x',   # grouped flags
            f' 812 {PY} -Werror -I {R}/agents/dave/bin/bg-run.py l y',          # -W value glued on
        ])
        self.assertEqual(dict(ic.bg_runs(ps, cwd=lambda pid: '')), {'dave': [811, 812]})

    def test_throwing_capture_is_no_mark_not_a_lost_report(self):
        def capture(agent):
            raise RuntimeError('tmux gone')
        w = ic.make_bg_wait(capture=capture, ps=lambda: '', cwd=lambda pid: '')
        self.assertIsNone(w('bella'))
        out = ic.idle_report([card('1', 'bella')], lambda a: a == 'bella', lambda cid: '', TODAY, w)
        self.assertEqual(out, ['bella 1'])

    def test_mark_pid_wins_then_shells_then_none(self):
        ps = f' 700 {PY} -I {R}/agents/dave/bin/bg-run.py l x\n 650 {PY} -I {R}/agents/dave/bin/bg-run.py l y\n'
        panes = {'dave': DONE_SHELLS, 'mira': DONE_SHELLS, 'bella': BOX}
        w = ic.make_bg_wait(capture=lambda a: panes.get(a, ''), ps=lambda: ps, cwd=lambda pid: '')
        self.assertEqual(w('dave'), '650')
        self.assertEqual(w('mira'), 'shell-2')
        self.assertIsNone(w('bella'))

    def test_ps_error_means_no_pid_mark(self):
        def boom():
            raise OSError('ps down')
        w = ic.make_bg_wait(capture=lambda a: DONE_SHELLS if a == 'dave' else BOX, ps=boom, cwd=lambda pid: '')
        self.assertEqual(w('dave'), 'shell-2')
        self.assertIsNone(w('bella'))

    def test_report_lines(self):
        cards = [card('1', 'dave', status='in_progress'), card('2', 'dave'), card('3', 'bella'),
                 card('4', 'mira')]
        asked = []
        marks = {'dave': '55973', 'mira': 'shell-1'}

        def bg_wait(agent):
            asked.append(agent)
            return marks.get(agent)
        out = ic.idle_report(cards, lambda a: a in {'dave', 'bella'}, lambda cid: '', TODAY, bg_wait)
        self.assertEqual(out, ['bella 1', 'dave 2 hatter-futas 55973'])
        self.assertEqual(sorted(asked), ['bella', 'dave'])  # mira is busy: never asked
        self.assertEqual(ic.idle_report(cards, lambda a: a in {'dave', 'bella'}, lambda cid: '', TODAY),
                         ['bella 1', 'dave 2'])  # without bg_wait: the old lines

    def test_dave_free_is_marked_too(self):
        out = ic.idle_report([], lambda a: a == 'dave', lambda cid: '', TODAY, lambda a: 'shell-3')
        self.assertEqual(out, ['dave-szabad 0 hatter-futas shell-3'])


if __name__ == '__main__':
    unittest.main(verbosity=1)
