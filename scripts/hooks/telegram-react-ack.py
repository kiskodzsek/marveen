#!/usr/bin/env python3
"""PostToolUse hook (matcher: mcp__plugin_telegram_telegram__react): a successful emoji reaction acknowledges the
inbound in that chat, so the Stop-hook reply guard (telegram-reply-guard.py) lets the turn end without a new message.

Why (Klodel 34050, Balázs csoport TG 3631, 2026-11-09: "ne újjazz már meg ennyiszer"): the guard demanded a reply on
every group message, so a discussion between Patrik and Balázs got six separate 👍 messages (TG 3594-3630). A
reaction is the quiet acknowledgement.

The reaction is NOT a conversation_log row (no reply text; an 'out' row would show up in the SessionStart replay as
an answer, and ledger-outbound.py stays the only writer of 'out' rows). ledger_lib.record_reaction keeps
{chat_id: unix ts} in a small JSON next to the DB; the guard reads it with reacted_since. Only a successful react
counts (the plugin answers "reacted"); an error answer records nothing, so the guard still blocks.
Any error -> exit 0 silently: a PostToolUse hook must never break the tool call.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ledger_lib  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import owner_chat  # noqa: E402

REACT_TOOL_RX = re.compile(r"^mcp__plugin_telegram_[A-Za-z0-9_-]+__react$")


def _owner_chat():
    # the same resolution as ledger-outbound.py (CHATID0): LEDGER_OWNER_CHAT, then the install's owner chat
    v = (os.environ.get("LEDGER_OWNER_CHAT") or "").strip()
    if v:
        return v
    try:
        return str(owner_chat.resolve_owner_chat_id(os.path.join(ledger_lib._install_dir(), ".env")) or "")
    except Exception:
        return ""


def reacted(payload):
    resp = payload.get("tool_response")
    if isinstance(resp, dict):
        if resp.get("isError") or resp.get("is_error"):
            return False
        resp = resp.get("content", resp)
    if isinstance(resp, list):
        resp = " ".join(str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in resp)
    return isinstance(resp, str) and resp.strip().lower() == "reacted"


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not REACT_TOOL_RX.match(payload.get("tool_name") or ""):
        return 0
    ti = payload.get("tool_input") or {}
    chat_id = "" if ti.get("chat_id") is None else str(ti.get("chat_id")).strip()
    if chat_id in ("", "0"):
        chat_id = _owner_chat()
    if not chat_id or not reacted(payload):
        return 0
    try:
        ledger_lib.record_reaction(ledger_lib.agent_id_from_payload(payload), chat_id)
    except Exception as exc:
        try:
            import hook_errlog  # noqa: E402
            hook_errlog.report("telegram-react-ack", "record_reaction failed, reaction not recorded", exc)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
