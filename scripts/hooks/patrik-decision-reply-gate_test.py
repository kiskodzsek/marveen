#!/usr/bin/env python3
"""Tests for patrik-decision-reply-gate.py (card dd706ced): the decision_phrase() core, the PATRIK-DONTES value check,
and the hook end to end against a temporary reply-mark ledger and database (synthetic chat and message ids)."""
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
GATE = os.path.join(HERE, 'patrik-decision-reply-gate.py')
spec = importlib.util.spec_from_file_location('gate', GATE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'lib'))
import reply_marks  # noqa: E402

PRIV, GROUP, OTHER = '111', '-222', '333'
TOOL = 'mcp__plugin_telegram_telegram__reply'
GOOD = 'penz: a Higgsfield-csomag havidíjas, TG 6533'


class DecisionPhrase(unittest.TestCase):
    def test_decisions_asked_of_the_reader(self):
        # TG 6275's shape and the measured 14-day shapes (replay_gate.py, card dd706ced)
        for text in ('Indulhat a Codex-kör? 🙂', 'Mehet?', 'Így mehet ki?', 'Mehet élesbe?', 'Csak igen vagy nem.',
                     'Igen / nem?', 'Egy döntés kell tőled: a próba új csatornán megy.', 'Döntsd el, melyik.',
                     'Ez a te döntésed.', 'A kártyák a döntésedre várnak.', 'Jóváhagyod?', 'Rábólintasz?',
                     'Ha igent mondasz, indul.', 'Melyik legyen?', 'Az A vagy a B tetszik? A vagy B?',
                     '🔴 Pénz: 12 000 Ft havonta.', 'Indulhatnak-e a lépések ma éjjel',
                     # Viktor 48130 M1, L1, L2 (work/dg-1119/test-rows.txt)
                     'Nem találtam hibát, mehet?', 'Ha nincs ellenvetésed, mehet?', 'Ne haragudj, mehet?',
                     'Mehet élesbe a PR #385?', 'Mehet a deploy 23:00-kor?', 'Mehet a merge (Pulzus)?',
                     'Mehet a Marabel kiadás ma éjjel is?', 'Mehet a v2.1 kiadás?',
                     'Döntés tőled, nem sürgős: indulhat-e a próba?', 'Balázs is átnézte, mehet?',
                     'Mehet így, vagy mit változtassunk?',
                     'Tőled egyetlen szó kell, mert pénzbe kerül: mehet a Metricool fizetős csomagja?',
                     'Patrik, Balázs: mehet?', 'Balázs, Patrik: mehet?'):   # addressed to both: it asks Patrik too
            self.assertIsNotNone(gate.decision_phrase(text), text)

    def test_negated_reported_quoted_or_not_his_passes(self):
        for text in ('Nem kell döntened, a kérésed lefedi.', 'Nincs teendőd, nem kell jóváhagynod.',
                     'Jóváhagytad, élesben van.', 'A te döntésed szerint a lap alján marad.',
                     'Patrik döntése szerint megy.', 'Mehet. Elindítottuk.', 'Indul a kör, eredmény este.',
                     'Balázs, mehet?', 'A poszt szövege: „Mehet a nyár?”', 'https://example.com/mehet?x=1',
                     'Ez a döntés megvan, holnap kész.', 'A Codex-kör fut, a kimenetet küldöm.',
                     'Pénz csak a jóváhagyásod után megy ki.', 'Nem kell döntés tőled, megcsináljuk.',
                     'Balázs, mehet a merge?', 'Pulzus szerint nem kell döntened, a szabály lefedi.',
                     'Ezt most tényleg nem kell jóváhagynod.',
                     'Kérdezted, mehet-e: igen, a TG 6533 szerint már élesben van.',
                     'https://example.com/mehet? ott a leírás.',
                     # Viktor 48130 I2: a report, not a request
                     'A jóváhagyásodat megkaptuk, indul.', 'A jóváhagyásod szerint ment ki.'):
            self.assertIsNone(gate.decision_phrase(text), text)

    def test_report_words_viktor_48157(self):
        # Viktor 48157 F1: the report exception needs a word boundary and no question in the clause (his i2probe ROWS);
        # I1: "megvan" as a report; I2: "jóváhagyásodat / jóváhagyásodra" as a request.
        reports = ('A jóváhagyásod szerint mentem tovább.', 'A jóváhagyásodat megkaptuk, indul.',
                   'A jóváhagyásod megvan, indítom.', 'A jóváhagyásod után élesítettem.',
                   'A jóváhagyásod nélkül nem nyúltam hozzá.', 'A jóváhagyásod szerint, ahogy kérted, kész.')
        requests = ('Ehhez a jóváhagyásod szerintem kell.', 'A jóváhagyásod szerintem holnapig kellene.',
                    'A jóváhagyásodat utána kérem a deployhoz.', 'A jóváhagyásod utána kellene, a merge előtt.',
                    'A jóváhagyásod nélkülözhetetlen ehhez.', 'A jóváhagyásod megvan erre?', 'Kell a jóváhagyásod.',
                    'A jóváhagyásodra várok.', 'A jóváhagyásod\nszerintem kell.', 'Kérem a jóváhagyásodat.',
                    'A jóváhagyásod megvan a holnapi kiadáshoz is?')
        for text in reports:
            self.assertIsNone(gate.decision_phrase(text), text)
        for text in requests:
            self.assertIsNotNone(gate.decision_phrase(text), text)

    def test_hidden_characters_do_not_hide_a_decision(self):
        self.assertIsNotNone(gate.decision_phrase('Me​het?'))
        self.assertIsNotNone(gate.decision_phrase('ＭＥＨＥＴ?'))

    def test_negation_applies_to_its_own_sentence_only(self):
        self.assertIsNotNone(gate.decision_phrase('Ezt nem kell. Mehet a másik?'))
        # the same words without the negation ask (the negation check is what lets the sentences above pass)
        for text in ('Kell döntened.', 'Kell döntés tőled.', 'Kell jóváhagynod.'):
            self.assertIsNotNone(gate.decision_phrase(text), text)


class Hook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.marks = os.path.join(self.tmp, 'reply-marks.jsonl')
        os.environ['REPLY_MARKS_PATH'] = self.marks
        self.db = os.path.join(self.tmp, 'claudeclaw.db')
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE agent_messages (id INTEGER PRIMARY KEY, from_agent TEXT NOT NULL, to_agent TEXT NOT NULL,'
                    ' content TEXT NOT NULL, status TEXT NOT NULL, created_at INTEGER NOT NULL)')
        con.execute('CREATE TABLE conversation_log (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL, chat_id '
                    "TEXT NOT NULL, direction TEXT NOT NULL CHECK(direction IN ('in','out')), message_id TEXT, text TEXT, "
                    'ts TEXT, created_at INTEGER NOT NULL)')
        now = int(time.time())
        for row in ((41144, 'mira', 'main', now - 3600), (40001, 'kernel', 'main', now - 8 * 86400)):
            con.execute("INSERT INTO agent_messages VALUES (?, ?, ?, 'x', 'done', ?)", row)
        for chat, direction, mid in ((GROUP, 'in', '6533'), (PRIV, 'in', '18717'), (GROUP, 'out', '6275'),
                                     (OTHER, 'in', '9001')):
            con.execute("INSERT INTO conversation_log (agent_id, chat_id, direction, message_id, text, created_at) "
                        "VALUES ('main', ?, ?, ?, 'x', ?)", (chat, direction, mid, now - 600))
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

    def mark(self, chat=GROUP, value=GOOD, agent='main', kind='PATRIK-DONTES'):
        reply_marks.add(kind, chat, agent, value)

    def run_gate(self, chat, text, agent='main', tool=TOOL, raw=None, owner_env=True):
        env = dict(os.environ, MAIN_AGENT_ID='main', MARVEEN_AGENT_ID=agent, MARVEEN_OWNER_CHATS=f'{PRIV},{GROUP}',
                   REPLY_MARKS_PATH=self.marks, LEDGER_DB_PATH=self.db, CLAUDE_PROJECT_DIR=self.tmp)
        if not owner_env:
            env.pop('MARVEEN_OWNER_CHATS')
        payload = {'tool_name': tool, 'tool_input': {'chat_id': chat, 'text': text}}
        p = subprocess.run([sys.executable, '-I', GATE], input=raw if raw is not None else json.dumps(payload),
                           env=env, capture_output=True, text=True, timeout=30)
        return p.returncode, p.stderr

    def test_neg_decision_without_mark_blocks(self):
        # TG 6275: a yes asked for a Codex round his request already covered
        rc, err = self.run_gate(GROUP, 'A PoC-kód Codex-köre kész az indulásra. Indulhat?')
        self.assertEqual(rc, 2)
        self.assertIn('DÖNTÉS-KAPU', err)
        self.assertIn('PATRIK-DONTES', err)
        self.assertIn('lefedi', err)
        self.assertEqual(self.run_gate(PRIV, 'Mehet?')[0], 2)

    def test_mark_is_held_for_the_call_not_spent(self):
        # Viktor 48130 I3 (k26): with a tool_use_id the mark gets a "hold" row; the spend stays with PostToolUse
        self.mark()
        env = dict(os.environ, MAIN_AGENT_ID='main', MARVEEN_AGENT_ID='main', MARVEEN_OWNER_CHATS=f'{PRIV},{GROUP}',
                   REPLY_MARKS_PATH=self.marks, LEDGER_DB_PATH=self.db, CLAUDE_PROJECT_DIR=self.tmp)
        payload = {'tool_name': TOOL, 'tool_use_id': 'toolu_hold_1', 'tool_input': {'chat_id': GROUP, 'text': 'Mehet?'}}
        p = subprocess.run([sys.executable, '-I', GATE], input=json.dumps(payload), env=env, capture_output=True,
                           text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = [json.loads(l) for l in open(self.marks, encoding='utf-8') if l.strip()]
        self.assertTrue(any(r.get('call') == 'toolu_hold_1' and r.get('hold') for r in rows), rows[-2:])
        self.assertFalse(any('used' in r for r in rows), rows[-2:])   # reply_marks.spend_pending: no "used" row

    def test_decision_with_mark_passes_once(self):
        self.mark()
        self.assertEqual(self.run_gate(GROUP, 'A csomag havidíjas. Mehet?')[0], 0)
        self.assertEqual(self.run_gate(GROUP, 'A csomag havidíjas. Mehet?')[0], 2)   # one mark = one message

    def test_mark_of_another_kind_or_chat_does_not_count(self):
        self.mark(kind='PATRIK-LEPES', value='mira 41144: x')
        self.assertEqual(self.run_gate(GROUP, 'Mehet?')[0], 2)
        self.mark(chat=PRIV)
        self.assertEqual(self.run_gate(GROUP, 'Mehet?')[0], 2)

    def test_passes_without_mark(self):
        self.assertEqual(self.run_gate(GROUP, 'Elindítottuk a Codex-kört, este jön az eredmény.')[0], 0)
        self.assertEqual(self.run_gate(GROUP, 'Nem kell döntened, a kérésed lefedi.')[0], 0)
        self.assertEqual(self.run_gate(OTHER, 'Mehet?')[0], 0)                                        # not his chat
        self.assertEqual(self.run_gate(GROUP, 'Mehet?', tool='mcp__plugin_telegram_telegram__edit_message')[0], 0)
        self.assertEqual(self.run_gate(GROUP, '', raw='not json')[0], 0)

    def test_owner_chats_unknown_passes_and_says_so(self):
        rc, err = self.run_gate(GROUP, 'Mehet?', owner_env=False)
        self.assertEqual(rc, 0)
        self.assertIn('the gate is off', err)

    def test_neg_mark_without_reason_or_fact_blocks(self):
        for value, word in (('review: a Codex-kör, TG 6533', 'miért csak Patrik'),
                            ('mérés kell, 41144', 'miért csak Patrik'),
                            ('penz: havidíjas', 'TG-szám'),
                            ('penz: havidíjas, TG 6275', 'nem Patrik chatjeibe bejött'),   # our own outgoing row
                            ('penz: havidíjas, TG 9001', 'nem Patrik chatjeibe bejött'),   # another chat
                            ('jog: 40001', 'nem 7 napon belüli')):                        # 8 days old
            self.mark(value=value)
            rc, err = self.run_gate(GROUP, 'Mehet?')
            self.assertEqual(rc, 2, value)
            self.assertIn(word, err, value)
            reply_marks._pending.clear()

    def test_value_check(self):
        chats = {PRIV, GROUP}
        for value in (GOOD, 'termek-ar: az új ár, TG 18717', 'jog: ÁSZF-szöveg, 41144', 'Pénz: TG#6533',
                      'adat-torles: 3 teszt-projekt, tg 6533', 'uj-epites: új felület, 41144'):
            self.assertIsNone(gate.value_problem(value, chats), value)
        # a TG number is never read as a msg_id (TG 41144 is no inbound row, though 41144 is a queue row); a PR number
        # (#41144) is no msg_id; a reason word inside another word (közpénz) is no reason
        for value in ('penzugy: TG 6533', 'jogos: TG 6533', 'sorrend: TG 6533', 'penz: TG 12', 'penz: 123',
                      'penz: TG 41144', 'penz: PR #41144', 'kozpenz: TG 6533'):
            self.assertIsNotNone(gate.value_problem(value, chats), value)

    def test_unreadable_db_blocks_with_reason(self):
        os.environ['LEDGER_DB_PATH'] = os.path.join(self.tmp, 'missing', 'x.db')
        self.assertIn('nem olvasható', gate.value_problem(GOOD, {PRIV, GROUP}))


if __name__ == '__main__':
    unittest.main()
