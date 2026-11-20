#!/usr/bin/env python3
"""Tests for patrik-mood-reply-gate.py (Klodel 48551): the laugh detector, the frustration window, and the hook end to
end against a synthetic plugin state (inbound-evidence.jsonl + inbound-senders.jsonl) and a synthetic store
(projektek.json, the extension word file). Synthetic ids and texts only. Run:
python3 -I scripts/hooks/patrik-mood-reply-gate_test.py"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, 'patrik-mood-reply-gate.py')
spec = importlib.util.spec_from_file_location('mood', GATE)
mood = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mood)

PATRIK, BALAZS = '111', '999'
PRIV, GROUP, OTHER = '111', '-222', '333'
REPLY = 'mcp__plugin_telegram_telegram__reply'
EDIT = 'mcp__plugin_telegram_telegram__edit_message'


class Laugh(unittest.TestCase):
    def test_todays_grin_is_a_signal(self):
        self.assertEqual(mood.laugh_signals('Ez jó volt 😄'), ['😄'])

    def test_the_listed_faces_all_signal(self):
        for e in '😄😁😂🤣😆😅😉😜🐷🥳🤪🫠😸🙃':
            self.assertEqual(mood.laugh_signals('x ' + e), [e], e)

    def test_range_edges(self):  # Klodel 48590: the five face ranges, inclusive, and nothing just outside them
        for lo, hi in mood.FACES:
            for o in (lo, hi):
                self.assertEqual(mood.laugh_signals(chr(o)), [chr(o)], hex(o))
        for o in (0x1F5FF, 0x1F650, 0x1F90F, 0x1F930, 0x1F96F, 0x1F97B, 0x1FADF, 0x1FAE9, 0x1F436, 0x1F438):
            self.assertEqual(mood.laugh_signals(chr(o)), [], hex(o))

    def test_content_emoji_pass(self):  # Klodel 48590: the post-draft emoji of the replay are not laughs
        self.assertEqual(mood.laugh_signals('🎙 📖 🎁 ✨ 🤍 🌙 🎄 ✅ ❌ ⚠️ 👍 👀 ❤️'), [])

    def test_status_marks_pass(self):
        self.assertEqual(mood.laugh_signals('✅ kész, ❌ hiba, ⚠️ figyelem, 👍, 👀, ❤️'), [])

    def test_variation_selector_and_skin_tone_do_not_hide(self):
        self.assertEqual(mood.laugh_signals('😁️'), ['😁'])
        self.assertEqual(mood.laugh_signals('👍🏽'), [])

    def test_laughing_words(self):
        for t, w in (('lol', 'lol'), ('Hahaha, ez az', 'hahaha'), ('hehe', 'hehe'), ('XD', 'xd'), ('jó :D', ':d'),
                     ('na ;)', ';)')):
            self.assertEqual(mood.laugh_signals(t), [w], t)

    def test_words_inside_words_do_not_signal(self):
        self.assertEqual(mood.laugh_signals('a Lolka mappa, a haharfa, x:d=1'), [])

    def test_plain_text_and_arrows_pass(self):
        self.assertEqual(mood.laugh_signals('Kész: PR #172 → main, 3 fájl. :)'), [])

    def test_gestures_are_not_laughs(self):  # Viktor 48627 INFO 2: "köszi 🙏" from a frustrated Patrik's chat
        for o in (0x1F645, 0x1F646, 0x1F647, 0x1F64B, 0x1F64C, 0x1F64D, 0x1F64E, 0x1F64F):
            self.assertEqual(mood.laugh_signals('köszi ' + chr(o)), [], hex(o))

    def test_monkeys_and_eye_roll_still_laugh(self):
        for e in '🙈🙉🙊🙄':
            self.assertEqual(mood.laugh_signals(e), [e], e)

    def test_laugh_word_needs_its_own_start(self):  # Viktor 48627 A16: no word boundary would catch these
        self.assertEqual(mood.laugh_signals('xlol, ahaha'), [])


class Stems(unittest.TestCase):
    def setUp(self):
        self.rx = mood.frustration_rx()

    def hit(self, text):
        return bool(self.rx.search(mood.fold(text)))

    def test_baszt_takes_the_imperative(self):  # Viktor 48627 LOW 1 (prop1.diff) and A30
        for t in ('ne basztass', 'ne basztatsz', 'basztatod'):
            self.assertTrue(self.hit(t), t)

    def test_baszt_leaves_bastya(self):
        for t in ('a bástya áll', 'bastion', 'Bazsi írta'):
            self.assertFalse(self.hit(t), t)

    def test_stem_only_from_the_start_of_a_word(self):  # Viktor 48627 A28
        self.assertFalse(self.hit('a kepfasz nem jo'))
        self.assertTrue(self.hit('ez faszság'))


class Hook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = os.path.join(self.tmp, 'tg')
        self.root = os.path.join(self.tmp, 'root')
        os.makedirs(self.state)
        os.makedirs(os.path.join(self.root, 'store'))
        with open(os.path.join(self.root, 'store', 'projektek.json'), 'w') as f:
            json.dump({'elo_uzenet': {'privat': {'chat_id': PRIV}, 'csoport': {'chat_id': GROUP}}}, f)
        self.mid = 6600

    def tearDown(self):
        shutil.rmtree(self.tmp, True)

    def said(self, user, text, minutes_ago=1, chat=GROUP):
        self.mid += 1
        at = int((time.time() - minutes_ago * 60) * 1000)
        with open(os.path.join(self.state, 'inbound-evidence.jsonl'), 'a') as f:
            f.write(json.dumps({'at': at, 'chat_id': chat, 'message_id': str(self.mid), 'text': text}) + '\n')
        with open(os.path.join(self.state, 'inbound-senders.jsonl'), 'a') as f:
            f.write(json.dumps({'at': at, 'chat_id': chat, 'message_id': str(self.mid), 'user_id': user}) + '\n')
        return str(self.mid)

    def run_gate(self, text, chat=GROUP, tool=REPLY, env_extra=None):
        env = {k: v for k, v in os.environ.items() if k not in ('MARVEEN_OWNER_CHATS', 'MARVEEN_OWNER_PRIVATE_CHAT')}
        env.update(CLAUDE_PROJECT_DIR=self.root, TELEGRAM_STATE_DIR=self.state)
        env.update(env_extra or {})
        payload = {'tool_name': tool, 'tool_input': {'chat_id': chat, 'text': text}}
        p = subprocess.run([sys.executable, '-I', GATE], input=json.dumps(payload), env=env, capture_output=True,
                           text=True, timeout=30)
        return p.returncode, p.stderr

    def test_todays_case_blocks(self):
        # 2026-11-20: Patrik's "behányt az agyam" (TG 6617), then a grinning joke reply into the group
        tg = self.said(PATRIK, 'ettől behányt az agyam', minutes_ago=3)
        rc, err = self.run_gate('Na, legalább a kávé jó 😄')
        self.assertEqual(rc, 2)
        self.assertIn('HUMOR-KAPU', err)
        self.assertIn(f'TG {tg}', err)
        self.assertNotIn('behányt', err)  # Patrik's text is not echoed

    def test_frustration_in_the_private_chat_counts_for_the_group(self):
        self.said(PATRIK, 'még sosem voltál szánalmasabb ennél', chat=PRIV)
        self.assertEqual(self.run_gate('haha')[0], 2)

    def test_edit_message_is_gated_too(self):
        self.said(PATRIK, 'ez hulladék')
        self.assertEqual(self.run_gate('frissítve 😂', tool=EDIT)[0], 2)

    def test_calm_day_jokes_pass(self):
        self.said(PATRIK, 'köszi, jó lett')
        self.assertEqual(self.run_gate('Szívesen 😄')[0], 0)

    def test_frustration_older_than_an_hour_passes(self):
        self.said(PATRIK, 'idióta vagy', minutes_ago=61)
        self.assertEqual(self.run_gate('😄')[0], 0)

    def test_balazs_frustration_does_not_count(self):
        self.said(BALAZS, 'ez szar')
        self.assertEqual(self.run_gate('😄')[0], 0)

    def test_matter_of_fact_reply_passes_while_upset(self):
        self.said(PATRIK, 'miért spammelsz?')
        self.assertEqual(self.run_gate('✅ Leállítottam, a többi a kártyára megy.')[0], 0)

    def test_other_chat_passes(self):
        self.said(PATRIK, 'idióta')
        self.assertEqual(self.run_gate('😄', chat=OTHER)[0], 0)

    def test_szar_stem_leaves_out_szarmazik(self):
        self.said(PATRIK, 'ez a szám a Stripe-ból származik, száraz adat')
        self.assertEqual(self.run_gate('😄')[0], 0)

    def test_extension_file_adds_a_stem(self):
        self.said(PATRIK, 'ez katasztrófa')
        self.assertEqual(self.run_gate('😄')[0], 0)
        with open(os.path.join(self.root, 'store', 'frusztracio-szavak.txt'), 'w') as f:
            f.write('# Klodel bővítése\nkatasztrófa\n')
        self.assertEqual(self.run_gate('😄')[0], 2)

    def test_extension_lines_are_plain_text_not_regex(self):
        with open(os.path.join(self.root, 'store', 'frusztracio-szavak.txt'), 'w') as f:
            f.write('.*\n')
        self.said(PATRIK, 'köszi')
        self.assertEqual(self.run_gate('😄')[0], 0)

    def write_ext(self, data):
        with open(os.path.join(self.root, 'store', 'frusztracio-szavak.txt'), 'wb') as f:
            f.write(data)

    def test_extension_comment_is_cut(self):  # Viktor 48627 A22: the "# ..." tail is not part of the stem
        self.write_ext('pocsék # Patrik 11-20\n'.encode('utf-8'))
        self.said(PATRIK, 'ez pocsék lett')
        self.assertEqual(self.run_gate('😄')[0], 2)

    def test_empty_extension_lines_add_nothing(self):  # Viktor 48627 A31: an empty stem would match every line
        self.write_ext('\n   \n# csak komment\n\n'.encode('utf-8'))
        self.said(PATRIK, 'köszi, jó lett')
        self.assertEqual(self.run_gate('😄')[0], 0)

    def test_non_utf8_extension_keeps_the_builtin_stems(self):  # Viktor 48627 A25
        self.write_ext(b'katasztr\xf3fa\n')
        self.said(PATRIK, 'idióta vagy')
        self.assertEqual(self.run_gate('😄')[0], 2)

    def test_frustration_only_in_the_rotated_log_counts(self):  # Viktor 48627 A23: the .1 files are read too
        self.said(PATRIK, 'ez hulladék')
        for n in ('inbound-evidence.jsonl', 'inbound-senders.jsonl'):
            os.rename(os.path.join(self.state, n), os.path.join(self.state, n + '.1'))
        self.assertEqual(self.run_gate('😄')[0], 2)

    def test_future_timestamp_does_not_count(self):  # Viktor 48627 A02
        self.said(PATRIK, 'idióta', minutes_ago=-10)
        self.assertEqual(self.run_gate('😄')[0], 0)

    def test_no_owner_id_passes(self):
        os.remove(os.path.join(self.root, 'store', 'projektek.json'))
        self.said(PATRIK, 'idióta')
        self.assertEqual(self.run_gate('😄', env_extra={'MARVEEN_OWNER_CHATS': f'{PRIV},{GROUP}'})[0], 0)

    def test_owner_env_overrides(self):
        self.said('555', 'idióta')
        env = {'MARVEEN_OWNER_CHATS': f'{PRIV},{GROUP}', 'MARVEEN_OWNER_PRIVATE_CHAT': '555'}
        self.assertEqual(self.run_gate('😄', env_extra=env)[0], 2)

    def test_no_logs_pass(self):
        self.assertEqual(self.run_gate('😄')[0], 0)

    def test_bad_payload_passes(self):
        p = subprocess.run([sys.executable, '-I', GATE], input='nem json', capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0)

    def test_other_tool_passes(self):
        self.said(PATRIK, 'idióta')
        self.assertEqual(self.run_gate('😄', tool='mcp__plugin_telegram_telegram__react')[0], 0)


if __name__ == '__main__':
    unittest.main()
