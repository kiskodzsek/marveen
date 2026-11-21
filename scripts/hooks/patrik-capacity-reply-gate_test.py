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

    def test_shortage_is_not_a_negation(self):
        # Viktor 49735 M1 (N1-N4): "nem lesz elég / nem bírja / nem fog kitartani" is the TG 6198 situation itself.
        for text in ('A csapat heti kerete nem lesz elég a hétre; két lehetőség árral az esti blokkban.',
                     'A heti keret nem elég, javaslom, hogy bővítsünk.',
                     'A Claude-keret nem fog kitartani, javaslom a bővítést.',
                     'Nem lesz elég a heti keret, javaslom a bővítést.'):
            self.assertIsNotNone(gate.capacity_offer(text), text)

    def test_price_shapes_and_vocabulary(self):
        # Viktor 49735 L1 (E1-E4) and L2 (W1-W3).
        for text in ('Harmadik Claude-fiók javaslat, 180 €/hó.', 'A heti keret elfogy; Claude Max havi 180 EUR.',
                     'A heti keret elfogy; Claude Max 180 euró havonta.', 'Javasolnék egy harmadik Claude-fiókot.',
                     'Javaslom a ChatGPT Plus előfizetést Májsztrónak.', 'Vegyünk OpenAI API kreditet?'):
            self.assertIsNotNone(gate.capacity_offer(text), text)
        # A provider-less "harmadik / további fiók" is not AI capacity (Marabel, Metricool accounts).
        for text in ('Javaslom, hogy a teszthez nyissunk egy harmadik fiókot a Marabelen.',
                     'Javaslom a további fiókot a Metricoolban.'):
            self.assertIsNone(gate.capacity_offer(text), text)

    def test_negated_offer_passes(self):
        # A negated OFFER next to a live capacity phrase (the negation windows before and after the offer).
        for text in ('Nem javaslom a harmadik Claude-fiókot.', 'A heti keret elfogy, de nem javaslom a bővítést.',
                     'A heti keret elfogy, bővítést nem javaslok.'):
            self.assertIsNone(gate.capacity_offer(text), text)

    def test_far_negation_does_not_negate(self):
        # Only the last 4 words before a phrase count: a "nem" further back in the clause is about something else.
        self.assertIsNotNone(gate.capacity_offer('Nem tudtam még megnézni a mai heti keret állását és javaslom a bővítést.'))

    def test_balazs_overlap_and_bare_price_word(self):
        # A sentence to Balázs that also names Patrik is checked; "harmadik seat" alone is not its own offer;
        # a bare "árral" is an offer.
        self.assertIsNotNone(gate.capacity_offer('Balázs és Patrik: a heti keret elfogy, javaslom a bővítést.'))
        self.assertIsNone(gate.capacity_offer('Most a harmadik seat fut a flottán.'))
        self.assertIsNotNone(gate.capacity_offer('A heti keret elfogy, a két út árral a kártyán.'))

    def test_long_digit_run_is_linear(self):
        # Viktor 49735 L4: an unbounded digit run before the currency was quadratic (64 000 "1 " = 64 s).
        t0 = time.monotonic()
        gate.capacity_offer('A heti keret elfogy ' + '1 ' * 64000)
        self.assertLess(time.monotonic() - t0, 2.0)

    def test_msg_id_length(self):
        for v in ('kernel 415: Dave helye 7d 10 %', 'kernel 41500000: Dave helye 7d 10 %'):
            self.assertIn('nincs benne a mérés msg_id-je', gate.value_problem(v, {'kernel', 'main'}, 'main'), v)

    def test_row_is_measurement(self):
        self.assertTrue(gate.row_is_measurement('Dave helye 7d 10 %, a flotta 71 %.'))
        self.assertTrue(gate.row_is_measurement('own:dave seven_day 95 %, nullázás 11-23.'))
        self.assertFalse(gate.row_is_measurement('A flotta tokenje nem másolható, külön fiók kell.'))
        self.assertFalse(gate.row_is_measurement('A keret elfogy. Holnap 40 % lesz a terhelés.'))
        # Viktor 49735 L3 (R1, R6): a disk or build limit is not a quota measurement.
        self.assertFalse(gate.row_is_measurement('Mérve: szabad hely 12 %.'))
        self.assertFalse(gate.row_is_measurement('A Vercel limit a hónapban 35 %-on áll.'))


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
                    (41504, 'szigma', 'pulzus', 'A flotta 7d 80 %.', now - 60),
                    (41505, 'main', 'dave', 'Dave, kérlek mérd meg újra: múlt héten a kereted 10 % volt.', now - 60)):
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

    def run_gate(self, chat, text, agent='main', tool=TOOL, call=None, raw=None, owner_env=True, db=None):
        env = dict(os.environ, MAIN_AGENT_ID='main', MARVEEN_AGENT_ID=agent, MARVEEN_OWNER_CHATS=f'{PRIV},{GROUP}',
                   REPLY_MARKS_PATH=self.marks, MARVEEN_AGENTS_DIR=self.agents, LEDGER_DB_PATH=db or self.db,
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

    def test_neg_own_message_to_the_teammate_is_not_its_measurement(self):
        # Viktor 49735 L3a (R2b): the writer's own row TO Dave carries a percentage, but Dave did not send it.
        self.mark(value='dave 41505: Dave kerete 10 %')
        rc, err = self.run_gate(GROUP, TG6198)
        self.assertEqual(rc, 2)
        self.assertIn('KÜLDÖTT', err)

    def test_neg_unreadable_queue_blocks(self):
        # Viktor 49735 L5 (M13): the msg_id cannot be checked = no measurement, not a pass.
        self.mark()
        rc, err = self.run_gate(GROUP, TG6198, db=os.path.join(self.tmp, 'missing', 'claudeclaw.db'))
        self.assertEqual(rc, 2)
        self.assertIn('nem olvasható', err)

    def test_neg_reply_marks_error_blocks(self):
        # Viktor 49735 L5 (M18): an error while reading the mark = no mark (blocks), in process with a failing take().
        import io
        from unittest import mock
        payload = json.dumps({'tool_name': TOOL, 'tool_input': {'chat_id': GROUP, 'text': TG6198}})
        def boom(*a, **k):
            raise RuntimeError('ledger broken')
        with mock.patch.dict(os.environ, {'MARVEEN_OWNER_CHATS': f'{PRIV},{GROUP}', 'MAIN_AGENT_ID': 'main'}), \
                mock.patch.object(reply_marks, 'take', boom), mock.patch('sys.stdin', io.StringIO(payload)), \
                mock.patch('sys.stderr', io.StringIO()):
            self.assertEqual(gate.main(), 2)

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
