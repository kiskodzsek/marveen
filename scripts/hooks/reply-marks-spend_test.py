#!/usr/bin/env python3
"""Tests for reply-marks-spend.py and the hold/spend half of scripts/lib/reply_marks.py (Klodel 41147): a reply
mark is spent only when the reply is sent, so a reply that another PreToolUse gate blocks keeps it.

End to end: patrik-reply-volume-gate.py (PreToolUse) and reply-marks-spend.py (PostToolUse) run as subprocesses
against a temporary conversation_log ledger, mark ledger and session transcript (synthetic ids, no real data)."""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, 'patrik-reply-volume-gate.py')
SPEND = os.path.join(HERE, 'reply-marks-spend.py')
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'lib'))
import reply_marks  # noqa: E402

GROUP = '-222'
TOOL = 'mcp__plugin_telegram_telegram__reply'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, 'ledger.db')
        self.marks = os.path.join(self.tmp, 'reply-marks.jsonl')
        self.transcript = os.path.join(self.tmp, 'session.jsonl')
        open(self.transcript, 'w').close()
        os.environ['REPLY_MARKS_PATH'] = self.marks
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE conversation_log (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT, '
                    'chat_id TEXT, direction TEXT, text TEXT, created_at INTEGER)')
        con.commit()
        con.close()
        # The owner wrote, the agent already answered: the next reply needs a KESZ-EREDMENY mark.
        self.log('in')
        self.log('out')
        reply_marks._pending.clear()
        reply_marks.bind_call(None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        reply_marks._pending.clear()
        reply_marks.bind_call(None)

    def log(self, direction):
        con = sqlite3.connect(self.db)
        con.execute('INSERT INTO conversation_log (agent_id, chat_id, direction, text, created_at) '
                    "VALUES ('main', ?, ?, 'x', 0)", (GROUP, direction))
        con.commit()
        con.close()

    def mark(self, kind='KESZ-EREDMENY', age=0):
        return reply_marks.add(kind, GROUP, 'main', 'a kért képek', now=time.time() - age)

    def blocked(self, call):
        """The session transcript gets the is_error tool_result Claude Code writes for a call a gate blocked
        (format as measured in a live transcript, 2026-11-13)."""
        row = {'type': 'user', 'message': {'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': call, 'is_error': True, 'content': 'PreToolUse hook error'}]}}
        with open(self.transcript, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, separators=(',', ':')) + '\n')

    def env(self):
        return dict(os.environ, LEDGER_DB_PATH=self.db, MAIN_AGENT_ID='main', MARVEEN_AGENT_ID='main',
                    MARVEEN_OWNER_CHATS=GROUP, REPLY_MARKS_PATH=self.marks)

    def pre(self, call, text='Itt vannak a kért képek.', transcript=True):
        payload = {'tool_name': TOOL, 'tool_input': {'chat_id': GROUP, 'text': text}}
        if call is not None:
            payload['tool_use_id'] = call
        if transcript:
            payload['transcript_path'] = self.transcript
        p = subprocess.run([sys.executable, '-I', GATE], input=json.dumps(payload), env=self.env(),
                           capture_output=True, text=True, timeout=30)
        return p.returncode

    def post(self, payload):
        p = subprocess.run([sys.executable, '-I', SPEND], input=payload if isinstance(payload, str)
                           else json.dumps(payload), env=self.env(), capture_output=True, text=True, timeout=30)
        return p.returncode

    def sent(self, call):
        """The reply went out: PostToolUse ran, and the ledger got the outbound row."""
        rc = self.post({'tool_name': TOOL, 'tool_use_id': call})
        self.log('out')
        return rc

    def rows(self):
        with open(self.marks, encoding='utf-8') as f:
            return [json.loads(line) for line in f if line.strip()]


class SpendAfterSend(Base):
    def test_neg_mark_survives_a_block_by_another_gate(self):
        # Klodel 41147, the 18:30 run: the volume gate passed on the mark, claim-source-reply-gate blocked the
        # same reply, the corrected reply hit "már válaszoltál". Now the mark is still there.
        self.mark()
        self.assertEqual(self.pre('toolu_A'), 0)
        self.blocked('toolu_A')  # another gate blocked toolu_A: no PostToolUse
        self.assertEqual(self.pre('toolu_B', 'Itt vannak a kért képek, forrással.'), 0)

    def test_one_mark_one_sent_message(self):
        self.mark()
        self.assertEqual(self.pre('toolu_A'), 0)
        self.assertEqual(self.sent('toolu_A'), 0)
        self.assertEqual(self.pre('toolu_B', 'És még ez.'), 2)

    def test_block_then_send_then_third_blocks(self):
        self.mark()
        self.assertEqual(self.pre('toolu_A'), 0)
        self.blocked('toolu_A')
        self.assertEqual(self.pre('toolu_B'), 0)
        self.assertEqual(self.sent('toolu_B'), 0)
        self.assertEqual(self.pre('toolu_C', 'Még egy.'), 2)
        self.assertEqual([r.get('used') for r in self.rows() if 'used' in r], [self.rows()[0]['nonce']])

    def test_neg_hold_of_a_running_call_blocks_a_second_call(self):
        # Two calls at once on one mark (Viktor 40933 INFO 1): toolu_A has no tool_result yet, it may still send.
        self.mark()
        self.assertEqual(self.pre('toolu_A'), 0)
        self.assertEqual(self.pre('toolu_B'), 2)

    def test_neg_unreadable_transcript_keeps_the_hold_live(self):
        self.mark()
        self.assertEqual(self.pre('toolu_A'), 0)
        self.blocked('toolu_A')
        self.assertEqual(self.pre('toolu_B', transcript=False), 2)
        os.remove(self.transcript)
        self.assertEqual(self.pre('toolu_B'), 2)

    def test_a_fresh_mark_passes_while_an_old_hold_is_live(self):
        self.mark()
        self.assertEqual(self.pre('toolu_A'), 0)
        self.mark()
        self.assertEqual(self.pre('toolu_B'), 0)

    def test_hold_older_than_hold_max_is_void(self):
        nonce = self.mark(age=30)
        with open(self.marks, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'hold': nonce, 'call': 'toolu_OLD',
                                'ts': int(time.time()) - reply_marks.HOLD_MAX_S - 5}) + '\n')
        self.assertEqual(self.pre('toolu_B'), 0)

    def test_same_call_taking_again_passes(self):
        # Two gates of one tool call (or one gate run twice for it) share the hold.
        self.mark()
        self.assertEqual(self.pre('toolu_A'), 0)
        self.assertEqual(self.pre('toolu_A'), 0)
        self.assertEqual(self.sent('toolu_A'), 0)
        self.assertEqual(sum(1 for r in self.rows() if 'used' in r), 1)

    def test_no_tool_use_id_spends_at_once_as_before(self):
        self.mark()
        self.assertEqual(self.pre(None), 0)
        self.assertTrue(any('used' in r for r in self.rows()))
        self.log('out')
        self.assertEqual(self.pre(None, 'És még ez.'), 2)

    def test_malformed_tool_use_id_is_unbound(self):
        reply_marks.bind_call({'tool_use_id': 'toolu_"x', 'transcript_path': self.transcript})
        self.assertIsNone(reply_marks._call['id'])
        reply_marks.bind_call({'tool_use_id': 'x' * 129})
        self.assertIsNone(reply_marks._call['id'])


class SpendHook(Base):
    def test_spends_only_the_holds_of_its_call(self):
        self.mark()
        self.assertEqual(self.pre('toolu_A'), 0)
        self.assertEqual(self.post({'tool_use_id': 'toolu_OTHER'}), 0)
        self.assertFalse(any('used' in r for r in self.rows()))
        self.assertEqual(self.post({'tool_use_id': 'toolu_A'}), 0)
        self.assertEqual(sum(1 for r in self.rows() if 'used' in r), 1)
        self.assertEqual(self.post({'tool_use_id': 'toolu_A'}), 0)  # twice: still one spend
        self.assertEqual(sum(1 for r in self.rows() if 'used' in r), 1)

    def test_bad_input_exits_0_and_writes_nothing(self):
        self.mark()
        self.assertEqual(self.pre('toolu_A'), 0)
        before = self.rows()
        for payload in ('not json', '[]', {'tool_use_id': None}, {'tool_use_id': '../x'}, {}):
            self.assertEqual(self.post(payload), 0)
        self.assertEqual(self.rows(), before)

    def test_missing_ledger_exits_0_and_creates_nothing(self):
        self.assertEqual(self.post({'tool_use_id': 'toolu_A'}), 0)
        self.assertFalse(os.path.exists(self.marks))


class ReserveOnce(Base):
    def test_owner_permission_survives_a_blocked_call(self):
        # product-image-gate OWNER-ASKED-GROUP: the owner's one group reply is not burnt by a blocked attempt.
        token = 'OWNER-ASKED-GROUP:main:7'
        reply_marks.bind_call({'tool_use_id': 'toolu_A', 'transcript_path': self.transcript})
        self.assertTrue(reply_marks.reserve_once(token))
        self.assertTrue(reply_marks.spend_pending())
        self.blocked('toolu_A')
        reply_marks.bind_call({'tool_use_id': 'toolu_B', 'transcript_path': self.transcript})
        self.assertTrue(reply_marks.reserve_once(token))
        self.assertTrue(reply_marks.spend_pending())
        self.assertEqual(reply_marks.spend_held('toolu_B'), 1)
        reply_marks.bind_call({'tool_use_id': 'toolu_C', 'transcript_path': self.transcript})
        self.assertFalse(reply_marks.reserve_once(token))


if __name__ == '__main__':
    unittest.main()
