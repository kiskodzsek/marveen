#!/usr/bin/env python3
"""
Stop hook — two jobs, in one place so there is a single owner of the per-session
progress state at turn end (no racing Stop hooks):

  1) CLEAR: remove the "✍️ Dolgozom rajta…" placeholder(s) that the
     UserPromptSubmit hook (telegram_progress.py) posted for this session. Under
     normal operation the PostToolUse reply hook already cleared them the moment
     the agent replied, so usually there is nothing left to do.

  2) ENFORCE DELIVERY: if the turn was triggered by an inbound Telegram message
     but the agent ended the turn WITHOUT ever sending a reply to that chat
     (i.e. a placeholder is still pending), the answer only exists in the CLI /
     transcript — which the Telegram user never sees ("the agent looks frozen").
     This hook then:
       - on the first Stop: BLOCKS the stop and instructs the agent to send its
         answer via the Telegram `reply` tool (the agent re-enters and replies
         properly, with its own formatting);
       - if it STILL did not reply after that one nudge: delivers the agent's
         final answer (last assistant message from the transcript) to the chat
         as a guaranteed fallback, then removes the placeholder.
     So a Telegram turn always ends with the user getting the answer here.

Loop safety: a per-session `enforce-<sid>.marker` guarantees we block at most
once; `stop_hook_active` is also honored. Silent on stdout EXCEPT the single
decision JSON when blocking. Token/state dir resolution mirrors the plugin
(TELEGRAM_STATE_DIR else default).
"""
import sys, os, json, glob, re, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import ledger_lib
except Exception:  # the ledger is optional here: without it nothing counts as acknowledged (old behaviour)
    ledger_lib = None


def acknowledged(ev, p):
    """Klodel 37860: the inbound behind this placeholder (src_mid) was closed as "not for me" (ledger-close.py) or
    reacted to after it arrived. Then no reply is owed: the placeholder is deleted, and NOTHING is sent -- the
    fallback below would otherwise post the transcript's last text into a conversation that was not ours."""
    if ledger_lib is None or not p.get("src_mid"):
        return False
    try:
        agent_id = ledger_lib.agent_id_from_payload(ev)
        cid, mid = p.get("chat_id"), p.get("src_mid")
        return ledger_lib.acknowledged(agent_id, cid, mid, ledger_lib.inbound_created_at(agent_id, cid, mid))
    except Exception:
        return False

INSTRUCTION = (
    "KÖTELEZŐ: erre a Telegram-üzenetre még NEM küldtél választ a Telegram "
    "`reply` tool-lal (chat_id=%s). A CLI/transzkript szöveget a felhasználó a "
    "Telegramon NEM látja — onnan nézve csak befagytál. Küldd el a válaszodat "
    "MOST a `reply` tool-lal a megfelelő chat_id-vel. Ha tényleg nincs érdemi "
    "válasz, akkor is küldj egy rövid visszaigazolást."
)


def state_dir():
    # #915: env override, then the install-scoped dir once it holds the .env,
    # then the legacy shared path (unmigrated installs only).
    d = os.environ.get("TELEGRAM_STATE_DIR")
    if d:
        return d
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _inst = os.path.join(_root, ".claude", "channels", "telegram")
    if os.path.isfile(os.path.join(_inst, ".env")):
        return _inst
    return os.path.expanduser("~/.claude/channels/telegram")


def log(sd, msg):
    try:
        os.makedirs(os.path.join(sd, "progress"), exist_ok=True)
        with open(os.path.join(sd, "progress", "debug.log"), "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def token(sd):
    try:
        for line in open(os.path.join(sd, ".env"), encoding="utf-8"):
            line = line.strip()
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    except Exception:
        return None
    return None


def api(tok, method, payload):
    # Base is overridable (TELEGRAM_API_BASE) so tests can point it at a local
    # stub; defaults to the real Bot API, so production is unchanged.
    base = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
    url = f"{base}/bot{tok}/{method}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode())


# TGAPIERR1113 (Klodel 40067, Patrik TG 18218): Claude Code's own error chrome ("Please run /login · API Error:
# 403 ...", isApiErrorMessage:true) is an assistant row in the transcript, not the agent's answer. It must never be
# delivered raw; it maps to one Hungarian sentence, and a later real text wins. Mirrors
# telegram_progress_watchdog.py (kept local: this hook may be installed without its siblings).
API_ERROR_TEXT = ("⚠️ Erre most nem tudtam válaszolni, mert a Claude-szolgáltatás hibát adott "
                  "(nem a gépen van a gond, újraindítás nem segít), kérlek, pár perc múlva írd újra.")
_API_ERROR_RX = re.compile(r"(?:^|\s)API Error:\s*\d{3}\b|Please run /login", re.I)


def _is_api_error(ev, text):
    if ev.get("isApiErrorMessage") is True:
        return True
    t = (text or "").strip()
    return bool(t) and len(t) <= 200 and "\n" not in t and bool(_API_ERROR_RX.search(t))


def last_assistant_text(transcript_path):
    """Return the last non-empty assistant text message from the JSONL transcript
    (the agent's final user-facing answer). Empty string if none / unreadable."""
    text = ""
    if not transcript_path:
        return text
    try:
        for line in open(transcript_path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            msg = ev.get("message") or {}
            role = msg.get("role") or ev.get("role")
            if ev.get("type") == "assistant" or role == "assistant":
                content = msg.get("content", ev.get("content"))
                parts = []
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            parts.append(c.get("text", ""))
                elif isinstance(content, str):
                    parts.append(content)
                t = "\n".join(p for p in parts if p).strip()
                if _is_api_error(ev, t):
                    text = API_ERROR_TEXT  # never the raw chrome
                elif t:
                    text = t  # keep the LAST non-empty one
    except Exception:
        pass
    return text


def main():
    raw = sys.stdin.read()
    try:
        ev = json.loads(raw)
    except Exception:
        ev = {}
    sid = ev.get("session_id") or "default"
    transcript = ev.get("transcript_path")
    stop_active = bool(ev.get("stop_hook_active"))
    sd = state_dir()
    pdir = os.path.join(sd, "progress")
    guard = os.path.join(pdir, f"enforce-{sid}.marker")

    # Clean up this session's dedup markers (created by telegram_progress.py).
    for m in glob.glob(os.path.join(pdir, f"seen-{sid}-*.marker")):
        try:
            os.remove(m)
        except Exception:
            pass

    path = os.path.join(pdir, f"{sid}.json")
    try:
        pend = json.load(open(path))
    except Exception:
        pend = None

    if pend:
        done = [p for p in pend if acknowledged(ev, p)]
        if done:
            tok = token(sd)
            for p in done:
                if tok:
                    try:
                        api(tok, "deleteMessage", {"chat_id": p.get("chat_id"), "message_id": p.get("message_id")})
                    except Exception as e:
                        log(sd, f"[ack] delete failed: {e}")
            pend = [p for p in pend if p not in done]
            try:
                if pend:
                    json.dump(pend, open(path, "w"))
                else:
                    os.remove(path)
            except Exception:
                pass
            log(sd, f"[ack] {len(done)} placeholder(s) of acknowledged/closed inbound(s) removed, no reply sid={sid}")

    if not pend:
        # Nothing pending: either not a Telegram turn, or the reply was already
        # sent (PostToolUse cleared it). Drop any stale enforce marker and exit.
        try:
            os.remove(guard)
        except Exception:
            pass
        return

    # A Telegram turn whose reply was NOT sent for the listed chat(s).
    blocked_before = os.path.exists(guard)
    if not stop_active and not blocked_before:
        # First Stop with an un-replied Telegram turn -> nudge the agent to reply
        # properly via its own tool. Keep the placeholder so the re-entry path
        # (PostToolUse) clears it when the reply finally goes out.
        try:
            open(guard, "w").close()
        except Exception:
            pass
        chats = ", ".join(sorted({str(p.get("chat_id")) for p in pend}))
        log(sd, f"[enforce] blocking stop, no reply sent sid={sid} chats={chats}")
        print(json.dumps({"decision": "block", "reason": INSTRUCTION % chats}))
        return

    # Already nudged once (or loop guard tripped) and STILL no reply -> guaranteed
    # fallback: deliver the agent's final answer to the chat, then clear.
    answer = last_assistant_text(transcript)
    tok = token(sd)
    if tok:
        sent_to = set()  # TGAPIERR1113: one delivery per chat, however many placeholders pend there
        for p in pend:
            cid, mid = p.get("chat_id"), p.get("message_id")
            if answer and str(cid) not in sent_to:
                sent_to.add(str(cid))
                try:
                    api(tok, "sendMessage", {"chat_id": cid, "text": answer[:4000]})
                except Exception as e:
                    log(sd, f"[enforce] fallback send failed: {e}")
            try:
                api(tok, "deleteMessage", {"chat_id": cid, "message_id": mid})
            except Exception as e:
                log(sd, f"[stop] delete failed: {e}")
    for f in (path, guard):
        try:
            os.remove(f)
        except Exception:
            pass
    log(sd, f"[enforce] fallback-delivered={bool(answer)} cleared {len(pend)} "
            f"placeholder(s) sid={sid}")


if __name__ == "__main__":
    main()
