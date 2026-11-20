#!/usr/bin/env python3
"""Tests for patrik-reply-volume-gate.py: the check() core, and the hook end to end against a temporary
conversation_log ledger (synthetic chat ids, no real data)."""
import importlib.util
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
spec = importlib.util.spec_from_file_location('gate', GATE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

PRIV, GROUP, OTHER = '111', '-222', '333'
PATRIK = PRIV  # Patrik's user id = his private chat id (the mood test's owner_user_id)
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

    def test_release_problem_core(self):
        self.assertIn('nincs benne', gate.release_problem('köteg', 'main', '/nonexistent.db'))
        self.assertIn('nem olvasható', gate.release_problem('47210', 'main', '/nonexistent.db'))

    def test_escape_does_not_lift_size(self):
        self.assertIsNotNone(gate.check('\n'.join(['sor'] * 7), 0, escaped=True))


class Hook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, 'ledger.db')
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE conversation_log (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT, '
                    'chat_id TEXT, direction TEXT, text TEXT, created_at INTEGER)')
        con.execute('CREATE TABLE agent_messages (id INTEGER PRIMARY KEY, from_agent TEXT, to_agent TEXT, '
                    'content TEXT, created_at INTEGER)')
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

    def mark(self, chat, agent='main', kind='KESZ-EREDMENY', value='a kért képek'):
        os.environ['REPLY_MARKS_PATH'] = self.marks_path()
        reply_marks.add(kind, chat, agent, value)

    def queue_msg(self, msg_id, frm='pulzus', to='main', age=60):
        con = sqlite3.connect(self.db)
        con.execute('INSERT INTO agent_messages (id, from_agent, to_agent, content, created_at) VALUES (?, ?, ?, ?, ?)',
                    (msg_id, frm, to, 'kiadás', int(time.time()) - age))
        con.commit()
        con.close()

    def answered(self, chat=GROUP):
        self.log(chat, 'in')
        self.log(chat, 'out')

    def run_gate(self, chat, text, agent='main', tool=TOOL, db=None, env_extra=None):
        # rule 3's mood test reads the plugin state and Patrik's user id: a synthetic, empty state unless upset() wrote
        env = dict(os.environ, LEDGER_DB_PATH=db or self.db, MAIN_AGENT_ID='main', MARVEEN_AGENT_ID=agent,
                   MARVEEN_OWNER_CHATS=f'{PRIV},{GROUP}', REPLY_MARKS_PATH=self.marks_path(),
                   TELEGRAM_STATE_DIR=self.state_dir(), MARVEEN_OWNER_PRIVATE_CHAT=PATRIK,
                   CLAUDE_PROJECT_DIR=self.tmp)
        env.update(env_extra or {})
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

    # --- card 36731203: the release "before" line (KIADAS-ELOTTE, Pulzus's release message msg_id) ---
    def test_release_mark_with_pulzus_message_passes(self):
        self.answered()
        self.queue_msg(47210)
        self.mark(GROUP, kind='KIADAS-ELOTTE', value='pulzus 47210: éjjeli köteg')
        self.assertEqual(self.run_gate(GROUP, 'Ma éjjel kiadás: 3 PR, Pulzus viszi.')[0], 0)

    def test_without_any_mark_the_hint_names_the_release_mark(self):
        self.answered()
        rc, err = self.run_gate(GROUP, 'Ma éjjel kiadás.')
        self.assertEqual(rc, 2)
        self.assertIn('KIADAS-ELOTTE', err)

    def test_release_mark_without_msg_id_blocks(self):
        self.answered()
        self.mark(GROUP, kind='KIADAS-ELOTTE', value='éjjeli köteg')
        rc, err = self.run_gate(GROUP, 'Ma éjjel kiadás.')
        self.assertEqual(rc, 2)
        self.assertIn('nincs benne', err)

    def test_release_mark_naming_another_sender_blocks(self):
        self.answered()
        self.queue_msg(47211, frm='dave')
        self.mark(GROUP, kind='KIADAS-ELOTTE', value='47211')
        self.assertEqual(self.run_gate(GROUP, 'Ma éjjel kiadás.')[0], 2)

    def test_release_mark_naming_pulzus_to_another_agent_blocks(self):
        self.answered()
        self.queue_msg(47212, to='dave')
        self.mark(GROUP, kind='KIADAS-ELOTTE', value='47212')
        self.assertEqual(self.run_gate(GROUP, 'Ma éjjel kiadás.')[0], 2)

    def test_release_mark_naming_an_old_message_blocks(self):
        self.answered()
        self.queue_msg(47213, age=gate.RELEASE_MSG_MAX_AGE_S + 60)
        self.mark(GROUP, kind='KIADAS-ELOTTE', value='47213')
        self.assertEqual(self.run_gate(GROUP, 'Ma éjjel kiadás.')[0], 2)

    def test_release_mark_naming_a_missing_message_blocks_and_is_not_spent(self):
        self.answered()
        self.mark(GROUP, kind='KIADAS-ELOTTE', value='47214')
        self.assertEqual(self.run_gate(GROUP, 'Ma éjjel kiadás.')[0], 2)
        self.queue_msg(47214)  # the same mark passes once the message is there: the block did not spend it
        self.assertEqual(self.run_gate(GROUP, 'Ma éjjel kiadás.')[0], 0)

    def test_release_mark_lets_one_message_through(self):
        self.answered()
        self.queue_msg(47215)
        self.mark(GROUP, kind='KIADAS-ELOTTE', value='47215')
        self.assertEqual(self.run_gate(GROUP, 'Ma éjjel kiadás.')[0], 0)
        self.log(GROUP, 'out')
        self.assertEqual(self.run_gate(GROUP, 'És még ez.')[0], 2)

    def test_release_mark_does_not_lift_size(self):
        self.answered()
        self.queue_msg(47216)
        self.mark(GROUP, kind='KIADAS-ELOTTE', value='47216')
        self.assertEqual(self.run_gate(GROUP, '\n'.join(['sor'] * 7))[0], 2)

    def test_release_mark_of_another_chat_is_no_escape(self):
        self.answered()
        self.queue_msg(47217)
        self.mark(PRIV, kind='KIADAS-ELOTTE', value='47217')
        self.assertEqual(self.run_gate(GROUP, 'Ma éjjel kiadás.')[0], 2)

    def test_release_mark_without_a_queue_table_blocks(self):
        con = sqlite3.connect(self.db)
        con.execute('DROP TABLE agent_messages')
        con.commit()
        con.close()
        self.answered()
        self.mark(GROUP, kind='KIADAS-ELOTTE', value='47218')
        rc, err = self.run_gate(GROUP, 'Ma éjjel kiadás.')
        self.assertEqual(rc, 2)
        self.assertIn('nem olvasható', err)

    def test_finished_result_mark_is_taken_first_the_release_mark_stays(self):
        self.answered()
        self.queue_msg(47219)
        self.mark(GROUP)
        self.mark(GROUP, kind='KIADAS-ELOTTE', value='47219')
        self.assertEqual(self.run_gate(GROUP, 'Itt vannak.')[0], 0)
        self.log(GROUP, 'out')
        self.assertEqual(self.run_gate(GROUP, 'Ma éjjel kiadás.')[0], 0)
        self.log(GROUP, 'out')
        self.assertEqual(self.run_gate(GROUP, 'És még ez.')[0], 2)

    # Viktor 47309: his probe rows that killed mutants these cases missed (V01, V02, V06, V09, V14-V16), and the
    # 6-hour window as a literal (a constant-derived age survived a 6 -> 60 hour mutant).
    def queue_raw(self, msg_id, frm, to, created_at):
        con = sqlite3.connect(self.db)
        con.execute('INSERT INTO agent_messages (id, from_agent, to_agent, content, created_at) VALUES (?, ?, ?, ?, ?)',
                    (msg_id, frm, to, 'kiadás', created_at))
        con.commit()
        con.close()

    def release(self, value):
        self.answered()
        self.mark(GROUP, kind='KIADAS-ELOTTE', value=value)
        return self.run_gate(GROUP, 'Ma éjjel kiadás.')[0]

    def test_v01_future_dated_message_blocks(self):
        self.queue_raw(47230, 'pulzus', 'main', int(time.time()) + 3600)
        self.assertEqual(self.release('47230'), 2)

    def test_v02_real_created_at_blocks(self):
        self.queue_raw(47231, 'pulzus', 'main', time.time() - 60.5)
        self.assertEqual(self.release('47231'), 2)

    def test_v06_three_digit_id_blocks(self):
        self.queue_raw(472, 'pulzus', 'main', int(time.time()) - 60)
        self.assertEqual(self.release('472'), 2)

    def test_v09_sender_case_or_space_variant_blocks(self):
        self.queue_raw(47232, 'Pulzus', 'main', int(time.time()) - 60)
        self.queue_raw(47233, ' pulzus', 'main', int(time.time()) - 60)
        self.queue_raw(47234, 'pulzus', 'Main', int(time.time()) - 60)
        self.assertEqual(self.release('47232 47233 47234'), 2)

    def test_v14_id_after_a_digit_blocks(self):
        # 8 digits: without the lookbehind "1047235" would match from the second digit.
        self.queue_msg(1047235)
        self.assertEqual(self.release('91047235'), 2)

    def test_v15_id_before_a_digit_blocks(self):
        # 8 digits: without the lookahead "1047236" would match from the first digit.
        self.queue_msg(1047236)
        self.assertEqual(self.release('10472369'), 2)

    def test_v16_second_of_two_ids_is_enough(self):
        self.queue_msg(47237, frm='dave')
        self.queue_msg(47238)
        self.assertEqual(self.release('47237 47238'), 0)

    def test_window_is_six_hours_literally(self):
        self.queue_msg(47239, age=7 * 3600)
        self.assertEqual(self.release('47239'), 2)
        self.queue_msg(47240, age=5 * 3600 + 3000)
        self.assertEqual(self.release('47240'), 0)

    def test_spent_message_names_the_release_mark(self):
        self.assertIn("f'VÁLASZ-KAPU: a {mark_kind} jel közben elfogyott", open(GATE, encoding='utf-8').read())

    def test_reply_mark_cli_accepts_the_accented_alias(self):
        env = dict(os.environ, REPLY_MARKS_PATH=self.marks_path(), MARVEEN_AGENT_ID='main', MAIN_AGENT_ID='main')
        env.pop('CLAUDE_CONFIG_DIR', None)
        cli = os.path.join(os.path.dirname(HERE), 'reply-mark.py')
        p = subprocess.run([sys.executable, '-I', cli, 'KIADÁS-ELŐTTE', '--chat', GROUP, 'pulzus 47220'], env=env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = [json.loads(l) for l in open(self.marks_path(), encoding='utf-8') if l.strip()]
        self.assertEqual(rows[-1]['kind'], 'KIADAS-ELOTTE')

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

    # --- rule 3, the 20-minute count while Patrik is upset (Klodel 48564, 48590; 13 group replies 09:40-09:58 UTC) ---
    def state_dir(self):
        d = os.path.join(self.tmp, 'tg')
        os.makedirs(d, exist_ok=True)
        return d

    def upset(self, user=None, text='ettől behányt az agyam', minutes_ago=3, msg_id='6617', chat=None):
        """A line of Patrik's (synthetic ids) in the plugin's inbound logs, as patrik-mood-reply-gate.py reads them."""
        at = int((time.time() - minutes_ago * 60) * 1000)
        chat = chat or GROUP
        with open(os.path.join(self.state_dir(), 'inbound-evidence.jsonl'), 'a') as f:
            f.write(json.dumps({'at': at, 'chat_id': chat, 'message_id': msg_id, 'text': text}) + '\n')
        with open(os.path.join(self.state_dir(), 'inbound-senders.jsonl'), 'a') as f:
            f.write(json.dumps({'at': at, 'chat_id': chat, 'message_id': msg_id, 'user_id': user or PATRIK}) + '\n')

    def log_at(self, chat, direction, at, agent='main'):
        con = sqlite3.connect(self.db)
        con.execute('INSERT INTO conversation_log (agent_id, chat_id, direction, text, created_at) '
                    'VALUES (?, ?, ?, ?, ?)', (agent, chat, direction, 'x', int(at)))
        con.commit()
        con.close()

    def todays_series(self, upto):
        """Replay of 2026-11-20: the group messages and the replies, minutes before now (reply 1 = 17 min ago)."""
        now = time.time()
        offsets = [17, 16, 14, 10, 8, 7, 6, 5, 4, 4, 2, 0.5, 0.2]  # 09:40 ... 09:58 UTC
        for k, m in enumerate(offsets[:upto]):
            self.log_at(GROUP, 'in', now - m * 60 - 5)
            self.log_at(GROUP, 'out', now - m * 60)

    def test_count_four_in_window_then_the_fifth_blocks(self):
        self.upset()
        self.todays_series(4)
        self.log_at(GROUP, 'in', time.time())
        rc, err = self.run_gate(GROUP, 'Megnéztem.')
        self.assertEqual(rc, 2)
        self.assertIn('20 percben már 4', err)
        self.assertIn('TG 6617', err)

    def test_count_three_in_window_passes(self):
        self.upset()
        self.todays_series(3)
        self.log_at(GROUP, 'in', time.time())
        self.assertEqual(self.run_gate(GROUP, 'Megnéztem.')[0], 0)

    def test_count_todays_thirteen_blocks(self):
        # the negative test of Klodel 48590: today's series, with Patrik's frustrated lines (TG 6615, 6617) in it
        self.upset(text='ez szánalmas', minutes_ago=12, msg_id='6615')
        self.upset(minutes_ago=6)
        self.todays_series(13)
        self.log_at(GROUP, 'in', time.time())
        self.assertEqual(self.run_gate(GROUP, 'Még egy poén.')[0], 2)

    def test_count_calm_day_has_no_limit(self):  # Klodel 48590: no general cap
        self.todays_series(13)
        self.log_at(GROUP, 'in', time.time())
        self.assertEqual(self.run_gate(GROUP, 'Megnéztem.')[0], 0)

    def test_count_frustration_older_than_an_hour_passes(self):
        self.upset(minutes_ago=61)
        self.todays_series(5)
        self.log_at(GROUP, 'in', time.time())
        self.assertEqual(self.run_gate(GROUP, 'Megnéztem.')[0], 0)

    def test_count_someone_elses_frustration_does_not_count(self):
        self.upset(user='999')
        self.todays_series(5)
        self.log_at(GROUP, 'in', time.time())
        self.assertEqual(self.run_gate(GROUP, 'Megnéztem.')[0], 0)

    def test_count_private_frustration_counts_for_the_group(self):
        self.upset(chat=PRIV)
        self.todays_series(5)
        self.log_at(GROUP, 'in', time.time())
        self.assertEqual(self.run_gate(GROUP, 'Megnéztem.')[0], 2)

    def test_count_no_owner_id_passes(self):  # Patrik's id unknown (no env, no projektek.json): rule 3 cannot decide
        self.upset()
        self.todays_series(5)
        self.log_at(GROUP, 'in', time.time())
        self.assertEqual(self.run_gate(GROUP, 'Megnéztem.', env_extra={'MARVEEN_OWNER_PRIVATE_CHAT': ''})[0], 0)

    def test_count_mood_file_missing_passes(self):  # the mood gate's file cannot be loaded: rules 1-2 still hold
        self.upset()
        self.todays_series(5)
        self.log_at(GROUP, 'in', time.time())
        d = tempfile.mkdtemp()
        try:
            for name in os.listdir(HERE):
                if name != 'patrik-mood-reply-gate.py' and not os.path.isdir(os.path.join(HERE, name)):
                    shutil.copy(os.path.join(HERE, name), d)
            env = dict(os.environ, LEDGER_DB_PATH=self.db, MAIN_AGENT_ID='main', MARVEEN_AGENT_ID='main',
                       MARVEEN_OWNER_CHATS=f'{PRIV},{GROUP}', REPLY_MARKS_PATH=self.marks_path(),
                       TELEGRAM_STATE_DIR=self.state_dir(), MARVEEN_OWNER_PRIVATE_CHAT=PATRIK, CLAUDE_PROJECT_DIR=self.tmp)
            payload = {'tool_name': TOOL, 'tool_input': {'chat_id': GROUP, 'text': 'Megnéztem.'}}
            p = subprocess.run([sys.executable, '-I', os.path.join(d, os.path.basename(GATE))],
                               input=json.dumps(payload), env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, 0, p.stderr)
        finally:
            shutil.rmtree(d, True)

    def test_count_core_needs_upset(self):
        self.assertIsNone(gate.check('Rendben.', 0, recent=9))
        self.assertIsNotNone(gate.check('Rendben.', 0, recent=4, upset='6617'))
        self.assertIsNone(gate.check('Rendben.', 0, recent=3, upset='6617'))
        self.assertIsNone(gate.check('Rendben.', 0, escaped=True, recent=9, upset='6617'))

    def test_count_old_replies_fall_out_of_the_window(self):
        self.upset()
        now = time.time()
        for m in (25, 24, 23, 22, 21):
            self.log_at(GROUP, 'out', now - m * 60)
        self.log_at(GROUP, 'in', now)
        self.assertEqual(self.run_gate(GROUP, 'Rendben.')[0], 0)

    def test_count_is_per_chat(self):
        self.upset()
        self.todays_series(5)
        self.log_at(PRIV, 'in', time.time())
        self.assertEqual(self.run_gate(PRIV, 'Rendben.')[0], 0)

    def test_count_finished_result_mark_passes_once(self):
        self.upset()
        self.todays_series(5)
        self.log_at(GROUP, 'in', time.time())
        self.mark(GROUP)
        self.assertEqual(self.run_gate(GROUP, 'Itt a kész lista.')[0], 0)

    def test_count_outage_mark_passes(self):
        self.upset()
        self.todays_series(5)
        self.log_at(GROUP, 'in', time.time())
        self.mark(GROUP, kind='KIESES', value='a marabel.hu nem válaszol')
        self.assertEqual(self.run_gate(GROUP, 'Kiesés: a marabel.hu áll, Pulzus dolgozik rajta.')[0], 0)

    def test_count_outage_mark_of_another_chat_is_no_escape(self):
        self.upset()
        self.todays_series(5)
        self.log_at(GROUP, 'in', time.time())
        self.mark(PRIV, kind='KIESES', value='a marabel.hu nem válaszol')
        self.assertEqual(self.run_gate(GROUP, 'Kiesés.')[0], 2)

    def test_bad_payload_passes(self):
        p = subprocess.run([sys.executable, '-I', GATE], input='nem json', capture_output=True, text=True,
                           timeout=30)
        self.assertEqual(p.returncode, 0)


if __name__ == '__main__':
    unittest.main()
