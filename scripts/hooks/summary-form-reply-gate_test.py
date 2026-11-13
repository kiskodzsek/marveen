#!/usr/bin/env python3
"""Tests for summary-form-reply-gate.py (retro 2026-11-13 R9, card dddca664): the check() core, and the hook end to
end (main agent, owner chats from MARVEEN_OWNER_CHATS, synthetic chat ids, no real data).

Run: python3 -I scripts/hooks/summary-form-reply-gate_test.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, 'summary-form-reply-gate.py')
spec = importlib.util.spec_from_file_location('gate', GATE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

PRIV, GROUP, OTHER = '111', '-222', '333'
TOOL = 'mcp__plugin_telegram_telegram__reply'

# The shape of the 11-10 incident (L185, D20261110-1800), shortened, invented wording.
INCIDENT = ('Esti döntés-összesítő (D20261110-1800), 1/3: a csapat jelzései, változtatás nélkül.\n\n'
            '[1] JELZÉS (Kernel): a kapu néma\n'
            '┆ scripts/hooks/x.py: exit 0 hibánál\n'
            '┆ javaslat: fail-closed\n'
            'Válasz: 1 mehet, 2 nem')
# A good evening summary (11-13 19:29 shape): passes.
GOOD = ('Mai eredmény, mérve:\n'
        '- Első éved film kész, kint a Facebookon (TG 6033), a hirdetése 19:22 óta fut (Mira 41233).\n'
        '- A posztod kiemelése nálunk nem ment, ezért külön hirdetésként fut.\n'
        '- Éjjel 00:05: Dave lapozós záróklipje az Első évedhez.\n'
        'Döntés ma nincs.')
GOOD_DECISIONS = ('Esti döntések, 2 pont:\n'
                  '1. A kóstoló-törlés éjjel élesedhet, javaslatom: mehet.\n'
                  '2. A heti hirdetési keret marad 20 000 Ft, javaslatom: igen.\n'
                  'Válasz pl.: 1 mehet, 2 igen')


class Check(unittest.TestCase):
    def test_incident_blocks(self):
        self.assertIn('részletsor', gate.check(INCIDENT))

    def test_detail_line_blocks_in_any_reply(self):
        self.assertIsNotNone(gate.check('Rendben.\n┆ belső sor'))
        self.assertIsNotNone(gate.check('Rendben.\n  ¦ belső sor'))

    def test_good_summaries_pass(self):
        self.assertIsNone(gate.check(GOOD))
        self.assertIsNone(gate.check(GOOD_DECISIONS))

    def test_ordinary_reply_with_path_passes(self):
        # not a summary: a path in an ordinary answer is not this gate's business
        self.assertIsNone(gate.check('A retró itt van: shared/retro/retro-2026-11-13.md'))

    def test_summary_detection(self):
        for head in ('Mai eredmény:', 'Napi eredmény', 'Esti döntések, három pont:', 'Esti összesítő',
                     'Esti összefoglaló.', '📋 Mai nap, röviden', 'DÖNTÉSEK (reggel)', 'Esti döntés-összesítő',
                     '🔴 NAPI DÖNTÉS-ÖSSZESÍTŐ (x), 1/2'):
            self.assertTrue(gate.is_summary(head + '\n- egy'), head)
        self.assertTrue(gate.is_summary('Két dolog vár:\n1. egy\n2. kettő\nVálasz: 1 mehet, 2 nem'))
        for text in ('Rendben, mehet.', '1. egy\n2. kettő', 'A 4 nem jó, a 2 igen.\nok',
                     'Heti retró, mérve:\n- 243 hiba'):
            self.assertFalse(gate.is_summary(text), text)

    def test_path_in_summary_blocks(self):
        for p in ('store/projektek.json', 'shared/hibanaplo.md', '/Users/klodel/x', 'dontes_motor.py', '`kód`'):
            self.assertIsNotNone(gate.check(f'Mai eredmény:\n- kész: {p}'), p)

    def test_internal_ids_block(self):
        for c in ('129d53c9', 'D20261110-1800', 'EGYSORJELZES1110'):
            self.assertIsNotNone(gate.check(f'Esti döntések:\n1. a {c} kártya, mehet?'), c)

    def test_sources_and_numbers_pass(self):
        self.assertIsNone(gate.check('Mai eredmény:\n- #1298 bent (Pulzus 41084, TG 6033), 20 000 Ft, 12345678 Ft'))

    def test_points_limit(self):
        five = 'Esti döntések:\n' + '\n'.join(f'{i}. pont' for i in range(1, 6))
        self.assertIsNone(gate.check(five))
        self.assertIn('legfeljebb 5', gate.check(five + '\n6. pont'))

    def test_point_length(self):
        self.assertIsNone(gate.check('Mai eredmény:\n- ' + 'a' * 218))
        self.assertIn('karakter', gate.check('Mai eredmény:\n- ' + 'a' * 219))

    def test_indented_continuation_blocks(self):
        self.assertIn('részletsorral', gate.check('Esti döntések:\n1. A kapu néma.\n   részlet: exit 0'))
        # an unindented closing line after the list is fine
        self.assertIsNone(gate.check('Esti döntések:\n1. A kapu néma, javaslatom: mehet.\nVálasz: 1 mehet'))


class Hook(unittest.TestCase):
    def run_gate(self, chat, text, agent='main', tool=TOOL, extra=None):
        env = dict(os.environ, MAIN_AGENT_ID='main', MARVEEN_AGENT_ID=agent, MARVEEN_OWNER_CHATS=f'{PRIV},{GROUP}',
                   LEDGER_DB_PATH=os.path.join(tempfile.mkdtemp(), 'ledger.db'),
                   HOOK_ERRLOG_PATH=os.path.join(tempfile.mkdtemp(), 'hook-errors.log'))
        env.update(extra or {})
        payload = {'tool_name': tool, 'tool_input': {'chat_id': chat, 'text': text}}
        p = subprocess.run([sys.executable, '-I', GATE], input=json.dumps(payload), env=env,
                           capture_output=True, text=True, timeout=30)
        return p.returncode, p.stderr

    def test_incident_blocked_in_group_and_private(self):
        for chat in (GROUP, PRIV):
            rc, err = self.run_gate(chat, INCIDENT)
            self.assertEqual(rc, 2)
            self.assertIn('ÖSSZESÍTŐ-KAPU', err)

    def test_good_summary_passes(self):
        self.assertEqual(self.run_gate(GROUP, GOOD)[0], 0)

    def test_other_chat_sub_agent_and_other_tool_pass(self):
        self.assertEqual(self.run_gate(OTHER, INCIDENT)[0], 0)
        self.assertEqual(self.run_gate(GROUP, INCIDENT, agent='dave')[0], 0)
        self.assertEqual(self.run_gate(GROUP, INCIDENT, tool='mcp__plugin_telegram_telegram__edit_message')[0], 0)

    def test_malformed_payloads_pass(self):
        env = dict(os.environ, MAIN_AGENT_ID='main', MARVEEN_AGENT_ID='main', MARVEEN_OWNER_CHATS=GROUP)
        for raw in ('', 'not json', '[]', '{"tool_input": 5}', json.dumps({'tool_input': {'chat_id': GROUP}})):
            p = subprocess.run([sys.executable, '-I', GATE], input=raw, env=env, capture_output=True, text=True,
                               timeout=30)
            self.assertEqual(p.returncode, 0, raw)

    def test_internal_error_fails_open_and_logs(self):
        log = os.path.join(tempfile.mkdtemp(), 'hook-errors.log')
        env = dict(os.environ, MAIN_AGENT_ID='main', MARVEEN_AGENT_ID='main', MARVEEN_OWNER_CHATS=GROUP,
                   HOOK_ERRLOG_PATH=log)
        code = ('import runpy, sys; sys.path.insert(0, %r); import unicodedata; '
                'unicodedata.normalize = lambda *a: 1 / 0; runpy.run_path(%r, run_name="__main__")' % (HERE, GATE))
        payload = json.dumps({'tool_name': TOOL, 'tool_input': {'chat_id': GROUP, 'text': GOOD}})
        p = subprocess.run([sys.executable, '-I', '-c', code], input=payload, env=env, capture_output=True,
                           text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(log, encoding='utf-8') as f:
            self.assertIn('summary-form-reply-gate', f.read())


if __name__ == '__main__':
    unittest.main(verbosity=1)
