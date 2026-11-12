#!/usr/bin/env python3
"""Tests for link-request-reply-gate.py (the check() core; the ledger read is a plain SELECT)."""
import importlib.util
import os
import unittest

spec = importlib.util.spec_from_file_location(
    'gate', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'link-request-reply-gate.py'))
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class LinkGate(unittest.TestCase):
    def test_incident_18018_blocks(self):
        self.assertIsNotNone(gate.check('add a linket ahol meg tudom nézni a google kereséseket',
                                        'Csatolom az összes mért számot egy táblázatban.'))

    def test_url_word_blocks(self):
        self.assertIsNotNone(gate.check('url', 'Pár perc múlva küldöm.'))

    def test_accents_and_case(self):
        self.assertIsNotNone(gate.check('A LINKJÉT küldd', 'Megnézem.'))

    def test_reply_with_url_passes(self):
        self.assertIsNone(gate.check('a linket kértem', 'https://ads.google.com/aw/keywordplanner/home\n\nLépj be.'))

    def test_www_host_passes(self):
        self.assertIsNone(gate.check('link?', 'www.alza.hu a termék oldala'))

    def test_escape_line_passes(self):
        self.assertIsNone(gate.check('add a linket', 'LINK-NINCS: a preview még épül, 14:30-ra lesz link'))

    def test_short_escape_blocks(self):
        self.assertIsNotNone(gate.check('add a linket', 'LINK-NINCS: nincs'))

    def test_no_link_ask_passes(self):
        self.assertIsNone(gate.check('mehet a marabellos szarod', 'Rendben, éjjel élesítjük.'))

    def test_word_inside_other_word_passes(self):
        self.assertIsNone(gate.check('linkedin profil kell', 'Rendben.'))

    def test_no_inbound_passes(self):
        self.assertIsNone(gate.check(None, 'bármi'))


if __name__ == '__main__':
    unittest.main()
