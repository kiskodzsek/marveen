#!/usr/bin/env python3
"""PreToolUse gate (telegram reply): when the owner asked for a link, the reply carries one.

Why: twice on 2026-11-12. TG 17974: "mondjuk egy kurva linket ilyenkor adjál már" (the trademark filing place was
described without its URL). TG 18018 -> 18022/18024/18025: "add a linket ..." was answered with a CSV file and
"a linket még ellenőrzöm", then "a linket kértem" / "url" / "mit nem értesz?". The skill pitfall written after the
first one did not stop the second: this gate does.

What blocks (exit 2): a reply to chat C when the latest inbound message in chat C (store/claudeclaw.db
conversation_log, direction 'in', this agent) asks for a link -- the accent-folded text has the word link / linket /
linkjet / linkje / linkek / url / urlt / urljet -- and the reply text has no http:// or https:// URL and no www. host.
Escape (the link really does not exist yet): a line "LINK-NINCS: <why>" with at least 10 characters of reason.
Anything unreadable (bad payload, no ledger, other tool) passes: the gate must never block an unrelated reply.
Wiring: .claude/settings.json PreToolUse, matcher "mcp__plugin_telegram_telegram__reply".
Tests: link-request-reply-gate_test.py next to this file.
"""
import json
import os
import re
import sqlite3
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ASK = re.compile(r'\b(link|linket|linkjet|linkje|linkek|linkeket|linkjeit|url|urlt|urljet|urlje)\b')
HAS_URL = re.compile(r'https?://\S+|\bwww\.[a-z0-9-]+\.[a-z]{2,}', re.I)
ESCAPE = re.compile(r'(?m)^\s*LINK-NINCS:\s*\S.{9,}$')


def norm(text):
    text = unicodedata.normalize('NFKC', str(text))
    text = ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))
    return text.casefold()


def asks_for_link(text):
    return bool(text) and bool(ASK.search(norm(text)))


def check(inbound_text, reply_text):
    if not asks_for_link(inbound_text):
        return None
    if HAS_URL.search(reply_text or '') or ESCAPE.search(reply_text or ''):
        return None
    return ('LINK-KAPU (Patrik TG 17974, TG 18022 "a linket kértem"): Patrik linket kért, a válaszban nincs URL. '
            'Az első sor a pontos link legyen (forrásból). Ha tényleg nincs még link: egy sor '
            '"LINK-NINCS: <miért, és mikor jön>".')


def latest_inbound(agent_id, chat_id):
    import ledger_lib
    con = sqlite3.connect(ledger_lib.db_path(), timeout=5)
    try:
        row = con.execute(
            "SELECT text FROM conversation_log WHERE agent_id=? AND chat_id=? AND direction='in'"
            " ORDER BY created_at DESC, id DESC LIMIT 1",
            (str(agent_id), str(chat_id)),
        ).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    tool = str(payload.get('tool_name') or '')
    if tool and not tool.endswith('__reply'):
        return 0
    ti = payload.get('tool_input')
    if not isinstance(ti, dict) or not ti.get('chat_id'):
        return 0
    try:
        import ledger_lib
        agent_id = ledger_lib.agent_id_from_payload(payload) or ledger_lib.main_agent_id()
        inbound = latest_inbound(agent_id, ti['chat_id'])
    except Exception:
        return 0
    msg = check(inbound, ti.get('text', ''))
    if msg:
        print(msg, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
