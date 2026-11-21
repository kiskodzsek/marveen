#!/usr/bin/env python3
"""Tests for patrik-capacity-reply-gate.py (card 13909285, retro 2026-11-20 R6, hibanapló 2026-11-16 11:15): the
capacity_offer() core, the BELSO-UT-MERVE value check, and the hook end to end against a temporary reply-mark ledger,
agents directory and inter-agent queue (synthetic chat and message ids)."""
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
GATE = os.path.join(HERE, 'patrik-capacity-reply-gate.py')
SPEND = os.path.join(HERE, 'reply-marks-spend.py')
spec = importlib.util.spec_from_file_location('gate', GATE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'lib'))
import reply_marks  # noqa: E402

PRIV, GROUP, OTHER = '111', '-222', '333'
TOOL = 'mcp__plugin_telegram_telegram__reply'
GOOD = 'kernel 41500: Dave helye 7d 10 %, a flotta 71 %, áttehető 3 ágens'
# The TG 6198 sentence (2026-11-16 11:12), the third occurrence (hibanapló 11:15).
TG6198 = ('✅ A motor adattár-sémája is fent van (PR 81, Dave): 377 tesztből 377 zöld.\n⚠️ Egy döntés vár rád: a csapat '
          'heti kerete a mért ütem mellett a héten elfogy (becslés: legkorábban holnap hajnalban). Három lehetőség árral '
          'a jelzés-kártyán és az esti blokkban; a javaslatom is ott van.')


class CapacityOffer(unittest.TestCase):
    def test_capacity_offers_are_caught(self):
        for text in (TG6198,
                     'Javaslom, hogy vegyünk egy harmadik Claude-fiókot (180 EUR/hó).',
                     'A Codex-keret elfogyott, vegyünk kreditet?',
                     'A heti keret holnap betelik; két lehetőség árral az esti blokkban.',
                     'Javaslat: Claude Max előfizetés a csapatnak, 200 USD/hó.',
                     'A flotta kerete kifut, a javaslatom egy további seat.',
                     'Codex-kredit vásárlás kell, 40 USD.',
                     'A csapat keretét bővítsük egy plusz Claude-előfizetéssel?'):
            self.assertIsNotNone(gate.capacity_offer(text), text)

    def test_measured_misses_pass(self):
        # The false hits of the first, paragraph-wide draft on 21 days of real messages (shapes kept, data synthetic).
        for text in ('Most mértem az adatbázisban: 01:00 óta egyetlen új fiók és egyetlen próbaindítás sincs.',
                     'Májsztró heti kerete 100%-on áll, csütörtökön nullázódik. A szlogenre adok 2 változatot.',
                     'Forgalom-céllal, a napi keretet és a szöveg két változatát előbb megkapod.',
                     'A Mixkit száma szól alatta, kredit a leírásban, a kép változatlan.',
                     'Májsztró a te ChatGPT-előfizetéseddel fut, API-kulcs és külön költség nélkül.',
                     'Dave átállt a második előfizetés keretére, mérve: 0 %.',
                     'Akkor a javaslatom: a fizetős GitHub Team csomag a fő ág védelméhez.',
                     'Hány új helyen jártak, hány km-t tettek meg.'):
            self.assertIsNone(gate.capacity_offer(text), text)

    def test_negated_quoted_and_report_pass(self):
        for text in ('Nem csinálom: új Claude-fiókot nem indítok, amíg nem mondod.',
                     'Nem kell új Claude-előfizetés, Dave kerete elbírja.',
                     'Patrik írta: „vegyünk egy harmadik Claude-fiókot”, ezt nem tesszük.',
                     'Keret most, mérve: a heti 14 %, a flotta előfizetésén.',
                     'Balázs, a csapat heti kerete elfogy, a javaslatom az esti blokkban.'):
            self.assertIsNone(gate.capacity_offer(text), text)

    def test_hidden_characters_do_not_hide_an_offer(self):
        self.assertIsNotNone(gate.capacity_offer('Java​slom: harmadik Claude-fiók, 180 EUR/hó.'))
        self.assertIsNotNone(gate.capacity_offer('ＪＡＶＡＳＬＯＭ a harmadik Claude-fiókot.'))

    def test_semicolon_clause_keeps_its_own_negation(self):
        # The ';' joins the offer to its sentence, but a negation before the ';' must not cover the next clause.
        self.assertIsNotNone(gate.capacity_offer('Új Claude-fiók nem kell; a heti keret betelik, javaslom a bővítést.'))

    def test_word_cut_by_the_negation_window_is_not_a_negation(self):
        # "ynem" cut by the scan window right before "nem" must not read as a negation of the offer.
        text = 'Javaslom ' + 'y' * 20 + 'nem ' + ' '.join(['z' * 64, 'z' * 64, 'z' * 65]) + ' harmadik Claude-fiókot.'
        start = text.index('harmadik')
        self.assertEqual(text[start - gate.NEG_SCAN_CHARS:start - gate.NEG_SCAN_CHARS + 4], 'nem ')
        self.assertIsNotNone(gate.capacity_offer(text))
        self.assertIsNone(gate.capacity_offer(text.replace('y' * 20 + 'nem', 'y' * 19 + ' nem')))

    def test_offer_needs_its_own_sentence(self):
        self.assertIsNone(gate.capacity_offer('A heti keret 70 %. Külön téma: a javaslatom a poszthoz kész.'))

    def test_row_is_measurement(self):
        self.assertTrue(gate.row_is_measurement('Dave helye 7d 10 %, a flotta 71 %.'))
        self.assertTrue(gate.row_is_measurement('own:dave seven_day 95 %, nullázás 11-23.'))
        self.assertFalse(gate.row_is_measurement('A flotta tokenje nem másolható, külön fiók kell.'))
        self.assertFalse(gate.row_is_measurement('A keret elfogy. Holnap 40 % lesz a terhelés.'))


class Hook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.marks = os.path.join(self.tmp, 'reply-marks.jsonl')
        self.agents = os.path.join(self.tmp, 'agents')
        for n in ('kernel', 'dave', 'pulzus', 'szigma'):
            os.makedirs(os.path.join(self.agents, n))
        os.environ['REPLY_MARKS_PATH'] = self.marks
        self.db = os.path.join(self.tmp, 'claudeclaw.db')
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE agent_messages (id INTEGER PRIMARY KEY, from_agent TEXT NOT NULL, to_agent TEXT NOT NULL,'
                    ' content TEXT NOT NULL, status TEXT NOT NULL, created_at INTEGER NOT NULL)')
        now = int(time.time())
        for row in ((41500, 'kernel', 'main', 'Mérve: Dave helye 7d 10 %, a flotta 71 %; 3 ágens áttehető.', now - 600),
                    (41501, 'dave', 'main', 'A flotta tokenje nem másolható, külön fiók kell.', now - 600),
                    (41502, 'kernel', 'main', 'Mérve: Dave helye 7d 10 %.', now - 8 * 86400),
                    (41503, 'main', 'main', 'A heti keret 71 %.', now - 60),
                    (41504, 'szigma', 'pulzus', 'A flotta 7d 80 %.', now - 60)):
            con.execute("INSERT INTO agent_messages VALUES (?, ?, ?, ?, 'done', ?)", row)
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

    def mark(self, chat=GROUP, value=GOOD, agent='main', kind='BELSO-UT-MERVE'):
        reply_marks.add(kind, chat, agent, value)

    def run_gate(self, chat, text, agent='main', tool=TOOL, call=None, raw=None, owner_env=True):
        env = dict(os.environ, MAIN_AGENT_ID='main', MARVEEN_AGENT_ID=agent, MARVEEN_OWNER_CHATS=f'{PRIV},{GROUP}',
                   REPLY_MARKS_PATH=self.marks, MARVEEN_AGENTS_DIR=self.agents, LEDGER_DB_PATH=self.db,
                   CLAUDE_PROJECT_DIR=self.tmp)
        if not owner_env:
            env.pop('MARVEEN_OWNER_CHATS')
        payload = {'tool_name': tool, 'tool_input': {'chat_id': chat, 'text': text}}
        if call:
            payload['tool_use_id'] = call
        p = subprocess.run([sys.executable, '-I', GATE], input=raw if raw is not None else json.dumps(payload),
                           env=env, capture_output=True, text=True, timeout=30)
        return p.returncode, p.stderr

    def test_neg_tg6198_without_mark_blocks(self):
        rc, err = self.run_gate(GROUP, TG6198)
        self.assertEqual(rc, 2)
        self.assertIn('KERET-KAPU', err)
        self.assertIn('BELSO-UT-MERVE', err)
        self.assertEqual(self.run_gate(PRIV, 'Javaslom a harmadik Claude-fiókot, 180 EUR/hó.')[0], 2)

    def test_measured_mark_passes(self):
        self.mark()
        self.assertEqual(self.run_gate(GROUP, TG6198)[0], 0)

    def test_neg_team_claim_without_number_blocks(self):
        # The 364/370 shape: a teammate's claim referenced, no quota measured.
        self.mark(value='dave 41501: külön fiók kell')
        rc, err = self.run_gate(GROUP, TG6198)
        self.assertEqual(rc, 2)
        self.assertIn('nem keret-mérés', err)

    def test_neg_mark_without_id_own_name_stale_or_foreign_row_blocks(self):
        for value, why in (('mértük, van belső út', 'msg_id'), ('main 41503: heti keret 71 %', 'MÁSIK'),
                           ('kernel 41502: Dave helye 7d 10 %', '7 napon belüli'),
                           ('kernel 41504: flotta 80 %', '7 napon belüli'), ('valaki 41500: mértük', 'MÁSIK')):
            self.mark(value=value)
            rc, err = self.run_gate(GROUP, TG6198)
            self.assertEqual(rc, 2, value)
            self.assertIn(why, err, value)

    def test_mark_of_another_agent_or_chat_does_not_count(self):
        self.mark(agent='dave')
        self.assertEqual(self.run_gate(GROUP, TG6198)[0], 2)
        self.mark(chat=PRIV)
        self.assertEqual(self.run_gate(GROUP, TG6198)[0], 2)

    def test_other_kind_does_not_count(self):
        self.mark(kind='PATRIK-LEPES')
        self.assertEqual(self.run_gate(GROUP, TG6198)[0], 2)

    def test_one_mark_one_message(self):
        self.mark()
        self.assertEqual(self.run_gate(GROUP, TG6198)[0], 0)
        self.assertEqual(self.run_gate(GROUP, 'Javaslom a harmadik Claude-fiókot.')[0], 2)

    def test_one_mark_one_sent_message_in_hold_mode(self):
        self.mark()
        self.assertEqual(self.run_gate(GROUP, TG6198, call='toolu_A')[0], 0)
        subprocess.run([sys.executable, '-I', SPEND], input=json.dumps({'tool_use_id': 'toolu_A'}),
                       env=dict(os.environ, REPLY_MARKS_PATH=self.marks), capture_output=True, text=True, timeout=30)
        self.assertEqual(self.run_gate(GROUP, 'Javaslom a harmadik Claude-fiókot.', call='toolu_B')[0], 2)

    def test_other_chat_edit_bad_input_and_report_pass(self):
        self.assertEqual(self.run_gate(OTHER, TG6198)[0], 0)
        self.assertEqual(self.run_gate(GROUP, TG6198, tool='mcp__plugin_telegram_telegram__edit_message')[0], 0)
        self.assertEqual(self.run_gate(GROUP, '', raw='not json')[0], 0)
        self.assertEqual(self.run_gate(GROUP, '', raw='[]')[0], 0)
        self.assertEqual(self.run_gate(GROUP, 'Keret most, mérve: a heti 14 %.')[0], 0)
        self.assertFalse(os.path.exists(self.marks))

    def test_unknown_owner_chats_pass_and_say_so(self):
        rc, err = self.run_gate(GROUP, TG6198, owner_env=False)
        self.assertEqual(rc, 0)
        self.assertIn('gate is off', err)


if __name__ == '__main__':
    unittest.main()
