#!/usr/bin/env python3
"""Pin / unpin a message with the main agent's Telegram bot (Patrik TG 14285, Klodel 24795).

Patrik: "if you are waiting for something from someone, pin it, and take the pin off once it is
done". The telegram channel plugin has reply/react/edit/download but no pin, so this is the
gated path for it:

  telegram-pin.py check [--chat ID]            can the bot pin in this chat? (getMe, getChat, getChatMember)
  telegram-pin.py pin <message_id> [--chat ID] [--notify]
  telegram-pin.py unpin <message_id> [--chat ID]
  telegram-pin.py open [--chat ID]             pins made here and not yet taken off (from the log)

Gates:
  - Only the MAIN agent's bot: the token is read from the main channel dir's .env (the same
    resolution as telegram-live-progress.py). It is never printed, logged or put in an error
    message, and the API base is a constant, not an environment knob, so no caller can point the
    token at another host.
  - Only a chat the channel already trusts: a key of access.json "groups" or an "allowFrom" id.
    Without --chat, DEFAULT_GROUP (the owner's supergroup) is used if allowed, else the one
    configured group; with several and no default, --chat is required.
  - Pins are silent by default (disable_notification); --notify makes a pin notify the members.
  - Every pin / unpin is appended to store/telegram-pin.log (time, action, chat, message id,
    result, the caller's MARVEEN_AGENT_ID if set). `open` reads it back.

Limit: the Bot API has no "read message" call, so the script cannot prove that <message_id> is a
message we sent; it pins what it is told to in an allowed chat, and the log keeps the trace.

Exit: 0 ok; 1 the API refused (the reason is printed); 2 usage / config error.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_BASE = "https://api.telegram.org"
LOG_NAME = "telegram-pin.log"
# The owner's group (Klodel 24935: it became a supergroup on 2026-11-03, the old
# basic-group id -5194177964 is dead). Used when --chat is absent and this id is
# among the channel's allowed groups; access.json may still list the old id.
DEFAULT_GROUP = "-1004488869449"


def channel_dir(root=ROOT):
    """The main agent's telegram channel dir (#915 order: env, install-scoped, legacy shared)."""
    d = os.environ.get("TELEGRAM_STATE_DIR")
    if d:
        return d
    inst = os.path.join(root, ".claude", "channels", "telegram")
    if os.path.isfile(os.path.join(inst, ".env")):
        return inst
    return os.path.expanduser("~/.claude/channels/telegram")


def read_token(cdir):
    try:
        with open(os.path.join(cdir, ".env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    tok = line.split("=", 1)[1].strip().strip("'\"")
                    return tok or None
    except OSError:
        pass
    return None


def allowed_chats(cdir):
    """(groups, all_allowed) from access.json, as strings."""
    try:
        with open(os.path.join(cdir, "access.json"), encoding="utf-8") as f:
            access = json.load(f)
    except (OSError, ValueError):
        return [], set()
    groups = access.get("groups") or {}
    groups = [str(g) for g in (groups.keys() if isinstance(groups, dict) else groups)]
    allow = {str(a) for a in (access.get("allowFrom") or [])}
    return groups, set(groups) | allow


def redact(text, tok):
    s = str(text)
    return s.replace(tok, "<token>") if tok else s


def api(tok, method, payload, base=None):
    """Call the Bot API; returns the decoded answer, never raises, never leaks the token."""
    url = f"{base or API_BASE}/bot{tok}/{method}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        # Telegram answers refusals with 4xx and a JSON body that says why.
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False, "description": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "description": redact(f"{type(e).__name__}: {e}", tok)}


def log_line(root, action, chat, msg_id, res):
    try:
        os.makedirs(os.path.join(root, "store"), exist_ok=True)
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "action": action, "chat": str(chat), "message_id": msg_id,
            "ok": bool(res.get("ok")), "description": res.get("description", ""),
            "by": os.environ.get("MARVEEN_AGENT_ID", ""),
        }
        with open(os.path.join(root, "store", LOG_NAME), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def open_pins(root, chat=None):
    """Pins logged as successful and not followed by a successful unpin, oldest first."""
    state = {}
    try:
        with open(os.path.join(root, "store", LOG_NAME), encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if not r.get("ok") or (chat and r.get("chat") != str(chat)):
                    continue
                key = (r.get("chat"), r.get("message_id"))
                if r.get("action") == "pin":
                    state[key] = r
                elif r.get("action") == "unpin":
                    state.pop(key, None)
    except OSError:
        pass
    return list(state.values())


def resolve_chat(cdir, chat):
    groups, allowed = allowed_chats(cdir)
    if chat is None:
        if DEFAULT_GROUP in groups:
            return DEFAULT_GROUP, None
        if len(groups) == 1:
            return groups[0], None
        return None, "--chat is required (configured groups: %d)" % len(groups)
    chat = str(chat)
    if chat not in allowed:
        return None, f"chat {chat} is not in the channel's access.json (groups / allowFrom)"
    return chat, None


def check(tok, chat, base=None):
    """What the bot can do in the chat, and what the owner has to switch on if it cannot pin."""
    me = api(tok, "getMe", {}, base)
    if not me.get("ok"):
        return 1, {"ok": False, "step": "getMe", "description": me.get("description", "")}
    bot_id = me["result"]["id"]
    info = api(tok, "getChat", {"chat_id": chat}, base)
    ctype = (info.get("result") or {}).get("type", "?") if info.get("ok") else "?"
    mem = api(tok, "getChatMember", {"chat_id": chat, "user_id": bot_id}, base)
    if not mem.get("ok"):
        return 1, {"ok": False, "step": "getChatMember", "chat_type": ctype,
                   "description": mem.get("description", "")}
    m = mem["result"]
    status = m.get("status")
    if ctype == "private":
        can, need = True, ""
    elif status == "creator":
        can, need = True, ""
    elif status == "administrator":
        # A basic group's admin may come without the granular field; only an explicit False
        # there means no. In a supergroup the right must be granted.
        can = bool(m.get("can_pin_messages")) if ctype == "supergroup" else m.get("can_pin_messages") is not False
        need = "" if can else "give the bot the 'Pin messages' admin right"
    else:
        can, need = False, "make the bot an admin of the group with the 'Pin messages' right"
    out = {"ok": True, "chat_type": ctype, "bot_status": status, "can_pin": can}
    if need:
        out["owner_action"] = need
    if info.get("ok") and (info["result"].get("migrate_to_chat_id")):
        out["migrated_to"] = info["result"]["migrate_to_chat_id"]
    return 0, out


def main(argv=None, root=ROOT, base=None):
    p = argparse.ArgumentParser(description="Pin / unpin with the main agent's Telegram bot.")
    p.add_argument("action", choices=["check", "pin", "unpin", "open"])
    p.add_argument("message_id", nargs="?", type=int)
    p.add_argument("--chat")
    p.add_argument("--notify", action="store_true", help="pin with a notification (default: silent)")
    a = p.parse_args(argv)

    cdir = channel_dir(root)
    chat, err = resolve_chat(cdir, a.chat)
    if err:
        print(json.dumps({"ok": False, "error": err}))
        return 2
    if a.action == "open":
        print(json.dumps({"ok": True, "chat": chat, "open": open_pins(root, chat)}, ensure_ascii=False))
        return 0
    tok = read_token(cdir)
    if not tok:
        print(json.dumps({"ok": False, "error": "no TELEGRAM_BOT_TOKEN in the main channel dir"}))
        return 2
    if a.action == "check":
        rc, out = check(tok, chat, base)
        print(json.dumps(out, ensure_ascii=False))
        return rc
    if not a.message_id or a.message_id <= 0:
        print(json.dumps({"ok": False, "error": "a positive message_id is required"}))
        return 2
    if a.action == "pin":
        res = api(tok, "pinChatMessage", {"chat_id": chat, "message_id": a.message_id,
                                          "disable_notification": not a.notify}, base)
    else:
        res = api(tok, "unpinChatMessage", {"chat_id": chat, "message_id": a.message_id}, base)
    log_line(root, a.action, chat, a.message_id, res)
    out = {"ok": bool(res.get("ok")), "action": a.action, "chat": chat, "message_id": a.message_id}
    if not res.get("ok"):
        out["description"] = redact(res.get("description", ""), tok)
        # A basic group upgraded to a supergroup answers with its new id.
        migrated = (res.get("parameters") or {}).get("migrate_to_chat_id")
        if migrated:
            out["migrated_to"] = str(migrated)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
