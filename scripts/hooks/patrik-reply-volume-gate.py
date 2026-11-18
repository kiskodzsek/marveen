#!/usr/bin/env python3
"""PreToolUse gate (telegram reply): short replies, and one reply per owner message, in the owner's chats.

Why (card 9df14a4c, Klodel 40007): on 2026-11-13 between 10:39 and 11:00 the main agent sent 11 messages
to the team group, several of them 10+ lines. Patrik, private TG 18129: "miért spammels ezzel a sok
szarral te idiota?".

What blocks (exit 2), only for the MAIN agent's reply into one of the owner's chats (store/projektek.json
elo_uzenet "privat" / "csoport", or MARVEEN_OWNER_CHATS):
  1. size: more than MAX_LINES non-empty lines or more than MAX_CHARS characters of text;
  2. volume: the agent already replied in this chat since the latest inbound message there (store/claudeclaw.db
     conversation_log, by row id), unless the text has a line "KÉSZ-EREDMÉNY: <what>" -- a finished
     deliverable (e.g. the images Patrik asked for) may follow the answer it was promised in.
  The release line (card 36731203, 2026-11-16 23:16): CLAUDE.md asks for one line to Patrik BEFORE and one AFTER a
  release; the "before" line came after an answer to Patrik's last message and was blocked. A KIADAS-ELOTTE mark lets
  ONE such line through; its value must hold the msg_id of Pulzus's release message to the main agent in the
  inter-agent queue (store/claudeclaw.db agent_messages), at most RELEASE_MSG_MAX_AGE_S old. The "after" line is a
  finished result (KESZ-EREDMENY).
Edits (edit_message) are not gated: the live status message is edited in place and is long by design.
The inbound side counts every inbound row of the chat (the ledger has no sender column); in the owner's
chats those are the owner's (and the team's) human messages.
Anything unreadable (bad payload, no ledger, other agent, other tool) passes: the gate must never block an
unrelated reply.
Wiring: .claude/settings.json PreToolUse, matcher "mcp__plugin_telegram_telegram__reply" (main agent only).
Tests: patrik-reply-volume-gate_test.py next to this file.
"""
import json
import os
import re
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
STORE = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'store')

MAX_LINES = 6
MAX_CHARS = 600
RELEASER = 'pulzus'  # CLAUDE.md "Kiadás és éles üzem": Pulzus collects, merges and deploys the batch
RELEASE_MSG_MAX_AGE_S = 6 * 3600
MSG_ID = re.compile(r'(?<!\d)\d{4,7}(?!\d)')


def owner_chats():
    """The owner's chats (same rule as mea-culpa-reply-gate.py): MARVEEN_OWNER_CHATS, else projektek.json."""
    env = os.environ.get('MARVEEN_OWNER_CHATS')
    if env:
        return {c.strip() for c in env.split(',') if c.strip()}
    try:
        with open(os.path.join(STORE, 'projektek.json'), encoding='utf-8') as f:
            elo = json.load(f).get('elo_uzenet')
    except Exception:
        return set()
    out = set()
    for key in ('privat', 'csoport'):
        v = elo.get(key) if isinstance(elo, dict) else None
        if isinstance(v, dict):
            v = v.get('chat_id')
        if v is not None and str(v).strip():
            out.add(str(v).strip())
    return out


def check(text, replies_since_inbound, escaped=False):
    """Pure decision: the block message, or None. escaped: a KESZ-EREDMENY reply mark was taken for this message
    (scripts/reply-mark.py; one mark lets ONE more message through, Viktor 40894; it is spent only when the reply
    is sent, so a reply another gate blocks keeps it, Klodel 41147)."""
    text = str(text or '')
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) > MAX_LINES or len(text.strip()) > MAX_CHARS:
        return (f'VÁLASZ-KAPU (Patrik TG 18129: "miért spammels ezzel a sok szarral"): Patrik chatjébe legfeljebb '
                f'{MAX_LINES} sor és {MAX_CHARS} karakter mehet (most {len(lines)} sor, {len(text.strip())} karakter). '
                'Írd egy rövid sorba a lényeget; a részlet a kártyára megy.')
    if replies_since_inbound >= 1 and not escaped:
        return ('VÁLASZ-KAPU (Patrik TG 18129): Patrik utolsó üzenete óta már válaszoltál ebben a chatben. '
                'Egy Patrik-üzenetre egy válasz. Kész anyag (pl. a kért képek) mehet, ha előtte jelölöd (a szövegbe '
                'nem kerül): python3 -I scripts/reply-mark.py KESZ-EREDMENY --chat <chat_id> "<mi>"; kiadás ELŐTTI sor: '
                'python3 -I scripts/reply-mark.py KIADAS-ELOTTE --chat <chat_id> "<Pulzus kiadás-üzenetének msg_id-je>"; '
                'minden más a kártyára.')
    return None


def release_problem(value, main_agent, db, now=None):
    """Why a KIADAS-ELOTTE value does not name Pulzus's release message, or None: one of its msg_ids must be a row of
    the inter-agent queue from RELEASER to the main agent, at most RELEASE_MSG_MAX_AGE_S old."""
    ids = [int(x) for x in MSG_ID.findall(str(value or ''))]
    if not ids:
        return 'nincs benne Pulzus kiadás-üzenetének msg_id-je (4-7 jegyű szám)'
    now = time.time() if now is None else now
    try:
        con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=5)
        try:
            rows = con.execute('SELECT from_agent, to_agent, created_at FROM agent_messages WHERE id IN (%s)'
                               % ','.join('?' * len(ids)), ids).fetchall()
        finally:
            con.close()
    except Exception:
        return 'az üzenetsor nem olvasható, a msg_id nem ellenőrizhető'
    for frm, to, at in rows:
        if (str(frm) == RELEASER and str(to) == str(main_agent) and isinstance(at, int)
                and 0 <= now - at <= RELEASE_MSG_MAX_AGE_S):
            return None
    return (f'a msg_id ({", ".join(map(str, ids))}) nem {RELEASER} -> {main_agent} üzenet az utolsó '
            f'{RELEASE_MSG_MAX_AGE_S // 3600} órából')


def replies_since_inbound(agent_id, chat_id):
    import ledger_lib
    con = sqlite3.connect(f'file:{ledger_lib.db_path()}?mode=ro', uri=True, timeout=5)  # never create a ledger
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM conversation_log WHERE agent_id=? AND chat_id=? AND direction='out'"
            " AND id > COALESCE((SELECT MAX(id) FROM conversation_log"
            "                    WHERE agent_id=? AND chat_id=? AND direction='in'), 0)",
            (str(agent_id), str(chat_id), str(agent_id), str(chat_id)),
        ).fetchone()
        return int(row[0]) if row else 0
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
    chat = str(ti['chat_id']).strip()
    if chat not in owner_chats():
        return 0
    try:
        import ledger_lib
        agent_id = ledger_lib.agent_id_from_payload(payload) or ledger_lib.main_agent_id()
        if agent_id != ledger_lib.main_agent_id():
            return 0
    except Exception:
        return 0
    try:
        n = replies_since_inbound(agent_id, chat)
    except Exception:
        n = 0  # no readable ledger: the volume rule cannot decide, the size rule still holds
    escaped = False
    mark_kind = 'KESZ-EREDMENY'
    if n >= 1:
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'lib'))
            import reply_marks
            reply_marks.bind_call(payload)  # held for this call, spent by reply-marks-spend.py once sent (41147)
            escaped = reply_marks.take('KESZ-EREDMENY', chat, agent_id) is not None
            if not escaped:
                rel = reply_marks.take('KIADAS-ELOTTE', chat, agent_id)
                if rel is not None:
                    problem = release_problem(rel, agent_id, ledger_lib.db_path())
                    if problem:
                        print(f'VÁLASZ-KAPU: a KIADAS-ELOTTE jel {problem}; a jel nem fogyott el, javítsd és jelölj '
                              'újra.', file=sys.stderr)
                        return 2
                    escaped = True
                    mark_kind = 'KIADAS-ELOTTE'
        except Exception:
            escaped = False
    msg = check(ti.get('text', ''), n, escaped)
    if msg:
        print(msg, file=sys.stderr)
        return 2
    if escaped and not reply_marks.spend_pending():
        print(f'VÁLASZ-KAPU: a {mark_kind} jel közben elfogyott (egy jel = egy üzenet); jelölj újra.', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
