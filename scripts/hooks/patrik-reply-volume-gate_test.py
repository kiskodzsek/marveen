#!/usr/bin/env python3
"""Tests for patrik-reply-volume-gate.py: the check() core, and the hook end to end against a temporary
conversation_log ledger (synthetic chat ids, no real data)."""
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, 'patrik-reply-volume-gate.py')
spec = importlib.util.spec_from_file_location('gate', GATE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

PRIV, GROUP, OTHER = '111', '-222', '333'
TOOL = 'mcp__plugin_telegram_telegram__reply'


sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib'))
import reply_marks  # noqa: E402

class Check(unittest.TestCase):
    def test_six_lines_pass(self):
        self.assertIsNone(gate.check('\n'.join(['sor'] * 6), 0))

    def test_seven_lines_block(self):
        self.assertIsNotNone(gate.check('\n'.join(['sor'] * 7), 0))

    def test_blank_lines_do_not_count(self):
        self.assertIsNone(gate.check('\n\n'.join(['sor'] * 6), 0))

    def test_600_chars_pass(self):
        self.assertIsNone(gate.check('x' * 600, 0))

    def test_601_chars_block(self):
        self.assertIsNotNone(gate.check('x' * 601, 0))

    def test_second_reply_blocks(self):
        self.assertIsNotNone(gate.check('Még egy dolog.', 1))

    def test_second_reply_with_escape_passes(self):
        # The escape is a KESZ-EREDMENY reply mark now (Klodel 40845), not a line of the text.
        self.assertIsNone(gate.check('Itt vannak.', 1, escaped=True))

    def test_text_marker_is_no_escape(self):
        self.assertIsNotNone(gate.check('KÉSZ-EREDMÉNY: a két kért kép\nItt vannak.', 1))

    def test_escape_does_not_lift_size(self):
        self.assertIsNotNone(gate.check('\n'.join(['sor'] * 7), 0, escaped=True))


class Hook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, 'ledger.db')
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE conversation_log (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT, '
                    'chat_id TEXT, direction TEXT, text TEXT, created_at INTEGER)')
        con.commit()
        con.close()

    def log(self, chat, direction, agent='main'):
        con = sqlite3.connect(self.db)
        con.execute('INSERT INTO conversation_log (agent_id, chat_id, direction, text, created_at) '
                    'VALUES (?, ?, ?, ?, 0)', (agent, chat, direction, 'x'))
        con.commit()
        con.close()

    def marks_path(self):
        return os.path.join(os.path.dirname(self.db), 'reply-marks.jsonl')

    def mark(self, chat, agent='main'):
        os.environ['REPLY_MARKS_PATH'] = self.marks_path()
        reply_marks.add('KESZ-EREDMENY', chat, agent, 'a kért képek')

    def run_gate(self, chat, text, agent='main', tool=TOOL, db=None):
        env = dict(os.environ, LEDGER_DB_PATH=db or self.db, MAIN_AGENT_ID='main', MARVEEN_AGENT_ID=agent,
                   MARVEEN_OWNER_CHATS=f'{PRIV},{GROUP}', REPLY_MARKS_PATH=self.marks_path())
        payload = {'tool_name': tool, 'tool_input': {'chat_id': chat, 'text': text}}
        p = subprocess.run([sys.executable, '-I', GATE], input=json.dumps(payload), env=env,
                           capture_output=True, text=True, timeout=30)
        return p.returncode, p.stderr

    def test_first_reply_passes(self):
        self.log(PRIV, 'in')
        self.assertEqual(self.run_gate(PRIV, 'Rendben.')[0], 0)

    def test_second_reply_without_inbound_blocks(self):
        self.log(PRIV, 'in')
        self.log(PRIV, 'out')
        rc, err = self.run_gate(PRIV, 'Még egy dolog.')
        self.assertEqual(rc, 2)
        self.assertIn('VÁLASZ-KAPU', err)

    def test_new_inbound_resets(self):
        self.log(GROUP, 'in')
        self.log(GROUP, 'out')
        self.log(GROUP, 'in')
        self.assertEqual(self.run_gate(GROUP, 'Rendben.')[0], 0)

    def test_reply_in_other_chat_does_not_count(self):
        self.log(PRIV, 'in')
        self.log(GROUP, 'out')
        self.assertEqual(self.run_gate(PRIV, 'Rendben.')[0], 0)

    def test_second_reply_with_escape_passes(self):
        self.log(GROUP, 'in')
        self.log(GROUP, 'out')
        self.mark(GROUP)
        self.assertEqual(self.run_gate(GROUP, 'Itt vannak a kért képek.')[0], 0)

    def test_one_mark_lets_one_message_through(self):
        # Viktor 40894 (a): a mark is not a 3-minute pass; the next message needs a new one.
        self.log(GROUP, 'in')
        self.log(GROUP, 'out')
        self.mark(GROUP)
        self.assertEqual(self.run_gate(GROUP, 'Itt vannak.')[0], 0)
        self.log(GROUP, 'out')
        self.assertEqual(self.run_gate(GROUP, 'És még ez.')[0], 2)

    def test_mark_of_another_agent_or_chat_is_no_escape(self):
        self.log(GROUP, 'in')
        self.log(GROUP, 'out')
        self.mark(GROUP, agent='dave')
        self.mark(PRIV)
        self.assertEqual(self.run_gate(GROUP, 'Itt vannak.')[0], 2)

    def test_seven_lines_block(self):
        self.log(PRIV, 'in')
        self.assertEqual(self.run_gate(PRIV, '\n'.join(['sor'] * 7))[0], 2)

    def test_601_chars_block(self):
        self.log(PRIV, 'in')
        self.assertEqual(self.run_gate(PRIV, 'x' * 601)[0], 2)

    def test_not_owner_chat_passes(self):
        self.log(OTHER, 'in')
        self.log(OTHER, 'out')
        self.assertEqual(self.run_gate(OTHER, '\n'.join(['sor'] * 9))[0], 0)

    def test_other_agent_passes(self):
        self.log(PRIV, 'in', agent='dave')
        self.log(PRIV, 'out', agent='dave')
        self.assertEqual(self.run_gate(PRIV, '\n'.join(['sor'] * 9), agent='dave')[0], 0)

    def test_edit_message_passes(self):
        self.assertEqual(self.run_gate(GROUP, '\n'.join(['sor'] * 20),
                                       tool='mcp__plugin_telegram_telegram__edit_message')[0], 0)

    def test_missing_ledger_passes_and_creates_nothing(self):
        missing = os.path.join(self.tmp, 'nincs.db')
        self.assertEqual(self.run_gate(PRIV, 'Rendben.', db=missing)[0], 0)
        self.assertFalse(os.path.exists(missing))

    def test_bad_payload_passes(self):
        p = subprocess.run([sys.executable, '-I', GATE], input='nem json', capture_output=True, text=True,
                           timeout=30)
        self.assertEqual(p.returncode, 0)


if __name__ == '__main__':
    unittest.main()
