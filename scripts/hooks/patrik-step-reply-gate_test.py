#!/usr/bin/env python3
"""Tests for patrik-step-reply-gate.py (Klodel 41154): the step_phrase() core, the PATRIK-LEPES value check, and the
hook end to end against a temporary reply-mark ledger and agents directory (synthetic chat and message ids)."""
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
GATE = os.path.join(HERE, 'patrik-step-reply-gate.py')
SPEND = os.path.join(HERE, 'reply-marks-spend.py')
spec = importlib.util.spec_from_file_location('gate', GATE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'lib'))
import reply_marks  # noqa: E402

PRIV, GROUP, OTHER = '111', '-222', '333'
TOOL = 'mcp__plugin_telegram_telegram__reply'
GOOD = 'mira 41144: a Reel a profil posztja, API-n nem hirdethető'


class StepPhrase(unittest.TestCase):
    def test_steps_put_on_the_reader(self):
        # Klodel 41154's own examples, and the TG 6048 sentence shape.
        for text in ('Nyomd meg a Kiemelés gombot.', 'Ezt te nyomod, mi nem tudjuk.', 'Kattints a linkre.',
                     'Lépj be a Metába, és kész.', 'Töltsd fel a videót az Ads Managerbe.', 'Holnap te indítod.',
                     'Futtasd le ezt a parancsot.', 'Másold be a kódot.', 'Ehhez a gépnél kell lenned.',
                     'Kérlek, jelentkezz be.', 'Elindítod reggel?', 'Fel kell töltened a fájlt.',
                     'Állítsd be a keretet.', 'Kapcsold be a kétlépcsős azonosítást.'):
            self.assertIsNotNone(gate.step_phrase(text), text)

    def test_negated_or_past_or_ours_passes(self):
        for text in ('Nem kell nyomnod semmit, mi intézzük.', 'Ne töltsd fel, már fent van.',
                     'Nem te indítod, hanem Pulzus.', 'Megnyomtad, köszönöm, élesben van.',
                     'Feltöltöttük, a videó a fiókban van.', 'Mi elindítjuk ma éjjel.', 'Kész, kiment.',
                     'Patrik kérte: „nyomd meg”, ezt már megcsináltuk.', 'Balázs, töltsd fel a számlát.',
                     'A link: https://example.com/kattints', 'Beírtam a gépnél-teendőid közé.',
                     'Poszt-szöveg: „Idén karácsonyra indítsd el anyukádnak a Meséld el!-t.”'):
            self.assertIsNone(gate.step_phrase(text), text)

    def test_hidden_characters_do_not_hide_a_step(self):
        self.assertIsNotNone(gate.step_phrase('Nyomd​ meg a gombot.'))
        self.assertIsNotNone(gate.step_phrase('ＮＹＯＭＤ ＭＥＧ.'))

    def test_negation_applies_to_its_own_sentence_only(self):
        self.assertIsNotNone(gate.step_phrase('Ezt nem kell. Nyomd meg a gombot.'))


class Hook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.marks = os.path.join(self.tmp, 'reply-marks.jsonl')
        self.agents = os.path.join(self.tmp, 'agents')
        for n in ('mira', 'kernel', 'dave'):
            os.makedirs(os.path.join(self.agents, n))
        os.environ['REPLY_MARKS_PATH'] = self.marks
        # The inter-agent queue (store/claudeclaw.db agent_messages), synthetic rows: the writer is "main".
        self.db = os.path.join(self.tmp, 'claudeclaw.db')
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE agent_messages (id INTEGER PRIMARY KEY, from_agent TEXT NOT NULL, to_agent TEXT NOT NULL,'
                    ' content TEXT NOT NULL, status TEXT NOT NULL, created_at INTEGER NOT NULL)')
        now = int(time.time())
        for row in ((41144, 'mira', 'main', now - 3600), (41154, 'main', 'kernel', now - 60),
                    (40001, 'kernel', 'main', now - 8 * 86400), (41200, 'main', 'main', now - 60)):
            con.execute("INSERT INTO agent_messages VALUES (?, ?, ?, 'x', 'done', ?)", row)
        con.commit()
        con.close()
        os.environ['LEDGER_DB_PATH'] = self.db
        reply_marks._pending.clear()
        reply_marks.bind_call(None)

    def tearDown(self):
        os.environ.pop('LEDGER_DB_PATH', None)
        shutil.rmtree(self.tmp, ignore_errors=True)
        reply_marks._pending.clear()
        reply_marks.bind_call(None)

    def mark(self, chat=GROUP, value=GOOD, agent='main', kind='PATRIK-LEPES'):
        reply_marks.add(kind, chat, agent, value)

    def run_gate(self, chat, text, agent='main', tool=TOOL, call=None, raw=None, owner_env=True, root=None):
        env = dict(os.environ, MAIN_AGENT_ID='main', MARVEEN_AGENT_ID=agent, MARVEEN_OWNER_CHATS=f'{PRIV},{GROUP}',
                   REPLY_MARKS_PATH=self.marks, MARVEEN_AGENTS_DIR=self.agents, LEDGER_DB_PATH=self.db,
                   CLAUDE_PROJECT_DIR=root or self.tmp)
        if not owner_env:
            env.pop('MARVEEN_OWNER_CHATS')
        payload = {'tool_name': tool, 'tool_input': {'chat_id': chat, 'text': text}}
        if call:
            payload['tool_use_id'] = call
        p = subprocess.run([sys.executable, '-I', GATE], input=raw if raw is not None else json.dumps(payload),
                           env=env, capture_output=True, text=True, timeout=30)
        return p.returncode, p.stderr

    def test_neg_step_without_mark_blocks(self):
        rc, err = self.run_gate(GROUP, 'Nyomd meg a Kiemelés gombot.')
        self.assertEqual(rc, 2)
        self.assertIn('LÉPÉS-KAPU', err)
        self.assertIn('PATRIK-LEPES', err)
        self.assertEqual(self.run_gate(PRIV, 'Te indítod holnap.')[0], 2)

    def test_step_with_mark_passes(self):
        self.mark()
        self.assertEqual(self.run_gate(GROUP, 'Nyomd meg a Kiemelés gombot.')[0], 0)

    def test_negated_step_passes_without_mark(self):
        self.assertEqual(self.run_gate(GROUP, 'Nem kell nyomnod semmit, mi intézzük.')[0], 0)
        self.assertEqual(self.run_gate(GROUP, 'Megnyomtad, köszönöm.')[0], 0)

    def test_neg_mark_without_msg_id_or_name_blocks(self):
        self.mark(value='nincs belső út, mértem')
        rc, err = self.run_gate(GROUP, 'Nyomd meg a gombot.')
        self.assertEqual(rc, 2)
        self.assertIn('msg_id', err)
        self.mark(value='valaki 41144: nincs belső út')
        rc, err = self.run_gate(GROUP, 'Nyomd meg a gombot.')
        self.assertEqual(rc, 2)
        self.assertIn('csapattag', err)

    def test_value_is_a_reference_to_the_queue(self):
        # Viktor 41257 LOW 2 (Klodel 41260): the msg_id is a queue row of the last 7 days with the named agent as
        # sender or recipient, and the named agent is not the writer.
        names = {'mira', 'kernel', 'dave', 'main'}
        self.assertIsNone(gate.value_problem(GOOD, names, 'main'))
        self.assertIsNone(gate.value_problem('Kernel 41154: a targeting search csak Patrik tokenjével', names, 'main'))
        # the missing msg_id is named as such, not as an unreadable queue (an empty IN () would also fail)
        self.assertIn('nincs benne a mérés msg_id', gate.value_problem('mira mérte, nincs belső út', names, 'main'))
        self.assertIn('nincs benne a mérés msg_id', gate.value_problem('mira 123: rövid id', names, 'main'))
        self.assertIn('csapattag', gate.value_problem('valaki 41144: nincs belső út', names, 'main'))
        self.assertIn('saját', gate.value_problem('main 41200: én mértem', names, 'main'))   # own name
        self.assertIn('üzenetsor', gate.value_problem('dave 41144: nincs út', names, 'main'))  # dave not a party
        self.assertIn('üzenetsor', gate.value_problem('kernel 40001: régi', names, 'main'))   # 8 days old
        self.assertIn('üzenetsor', gate.value_problem('kernel 2026: az év', names, 'main'))    # no such row
        self.assertIn('üzenetsor', gate.value_problem('mira 8080: port', names, 'main'))
        os.environ['LEDGER_DB_PATH'] = os.path.join(self.tmp, 'nincs.db')
        self.assertIn('nem olvasható', gate.value_problem(GOOD, names, 'main'))             # fail closed

    def test_neg_own_name_or_unknown_msg_id_blocks_end_to_end(self):
        self.mark(value='main 41154: én néztem meg')
        rc, err = self.run_gate(GROUP, 'Nyomd meg a gombot.')
        self.assertEqual(rc, 2)
        self.assertIn('saját', err)
        self.mark(value='kernel 2026: nincs belső út')
        self.assertEqual(self.run_gate(GROUP, 'Nyomd meg a gombot.')[0], 2)
        self.mark(value='kernel 41154: nincs belső út')
        self.assertEqual(self.run_gate(GROUP, 'Nyomd meg a gombot.')[0], 0)

    def projektek(self, data):
        root = os.path.join(self.tmp, 'root')
        os.makedirs(os.path.join(root, 'store'), exist_ok=True)
        with open(os.path.join(root, 'store', 'projektek.json'), 'w', encoding='utf-8') as f:
            f.write(data if isinstance(data, str) else json.dumps(data))
        return root

    def test_neg_owner_chats_from_projektek_json(self):
        # Viktor 41257 MEDIUM: production reads store/projektek.json (no MARVEEN_OWNER_CHATS); TG 6049 was the group.
        root = self.projektek({'elo_uzenet': {'privat': {'chat_id': int(PRIV), 'message_id': 1},
                                              'csoport': {'chat_id': int(GROUP), 'message_id': 2}}})
        self.assertEqual(self.run_gate(PRIV, 'Nyomd meg a gombot.', owner_env=False, root=root)[0], 2)
        self.assertEqual(self.run_gate(GROUP, 'Nyomd meg a gombot.', owner_env=False, root=root)[0], 2)
        self.assertEqual(self.run_gate(OTHER, 'Nyomd meg a gombot.', owner_env=False, root=root)[0], 0)
        root = self.projektek({'elo_uzenet': {'privat': PRIV, 'csoport': GROUP}})  # bare ids
        self.assertEqual(self.run_gate(GROUP, 'Nyomd meg a gombot.', owner_env=False, root=root)[0], 2)

    def test_unknown_owner_chats_pass_and_say_so(self):
        for data in (None, 'not json', {'elo_uzenet': None}, {'elo_uzenet': {'privat': {}}}):
            root = self.projektek(data) if data is not None else os.path.join(self.tmp, 'ures')
            rc, err = self.run_gate(GROUP, 'Nyomd meg a gombot.', owner_env=False, root=root)
            self.assertEqual(rc, 0, data)
            self.assertIn('the gate is off', err, data)

    def test_main_agent_id_counts_as_a_name_for_another_writer(self):
        reply_marks.add('PATRIK-LEPES', GROUP, 'kernel', 'main 41154: Patrik telefonján a 2FA')
        self.assertEqual(self.run_gate(GROUP, 'Lépj be a Metába.', agent='kernel')[0], 0)

    def test_neg_mark_of_another_chat_kind_or_agent_blocks(self):
        self.mark(chat=PRIV)
        self.mark(kind='KESZ-EREDMENY')
        self.mark(agent='dave')
        self.assertEqual(self.run_gate(GROUP, 'Nyomd meg a gombot.')[0], 2)

    def test_one_mark_one_message(self):
        self.mark()
        self.assertEqual(self.run_gate(GROUP, 'Nyomd meg a gombot.')[0], 0)
        self.assertEqual(self.run_gate(GROUP, 'És kattints a linkre.')[0], 2)

    def test_one_mark_one_sent_message_in_hold_mode(self):
        self.mark()
        self.assertEqual(self.run_gate(GROUP, 'Nyomd meg a gombot.', call='toolu_A')[0], 0)
        with open(self.marks, encoding='utf-8') as f:
            rows = [json.loads(line) for line in f if line.strip()]
        # Held for toolu_A, not spent: a reply another gate blocks keeps the mark (Klodel 41147).
        self.assertEqual([(r.get('call'), 'used' in r) for r in rows if 'nonce' not in r], [('toolu_A', False)])
        subprocess.run([sys.executable, '-I', SPEND], input=json.dumps({'tool_use_id': 'toolu_A'}),
                       env=dict(os.environ, REPLY_MARKS_PATH=self.marks), capture_output=True, text=True, timeout=30)
        self.assertEqual(self.run_gate(GROUP, 'És kattints a linkre.', call='toolu_B')[0], 2)

    def test_other_chat_edit_and_bad_input_pass(self):
        self.assertEqual(self.run_gate(OTHER, 'Nyomd meg a gombot.')[0], 0)
        self.assertEqual(self.run_gate(GROUP, 'Nyomd meg a gombot.',
                                       tool='mcp__plugin_telegram_telegram__edit_message')[0], 0)
        self.assertEqual(self.run_gate(GROUP, '', raw='not json')[0], 0)
        self.assertEqual(self.run_gate(GROUP, '', raw='[]')[0], 0)

    def test_plain_report_passes_and_writes_no_ledger(self):
        self.assertEqual(self.run_gate(GROUP, 'Kész: a videó a Meta-fiókban van.')[0], 0)
        self.assertFalse(os.path.exists(self.marks))


if __name__ == '__main__':
    unittest.main()
