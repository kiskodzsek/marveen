#!/usr/bin/env python3
"""
telegram_progress_watchdog.py -- the "őrszem" (sentry) for the Telegram progress
indicator. Runs independently of the agent sessions (via launchd/systemd), so it
can speak even when an agent is wedged or down.

Problem it solves: the UserPromptSubmit hook posts a "✍️ Dolgozom rajta…"
placeholder; the Stop hook deletes it when the turn ends. If a turn never ends
(agent crashed, session killed, or WEDGED on a dropped MCP reply-tool call that
never returns), the placeholder would sit there forever and the user is left
wondering "is it working or broken?".

Two delivery modes, best-effort per pending placeholder:
  - REAL ANSWER (preferred): if the agent's final answer is recoverable from the
    transcript, deliver it for real (sendMessage) and remove the placeholder --
    the same answer the Stop hook's guaranteed fallback would have sent, but
    without waiting for a turn end that may never come. This is the fix for the
    "reply tool dropped mid-turn -> round hangs -> Stop hook never fires ->
    the owner has to restart" freeze: the user gets the actual answer, restart-free.
  - GENERIC ERROR (fallback): if no answer is recoverable, rewrite the
    placeholder into a clear error (editMessageText), as before.

Detection (per pending placeholder, keyed by its session state file):
  - agent DOWN (its tmux `agent-<name>` session is gone) and the placeholder is
    older than DOWN_GRACE_SEC -> fire (crash / unreachable), or
  - agent UP but the transcript shows a HUNG reply -- the most recent tool call
    is the Telegram `reply` and it has no result yet -- and the placeholder is
    older than WEDGED_UP_SEC -> fire FAST. This precisely targets the dropped-
    MCP freeze and does NOT misfire on a legitimately long task (which has no
    dangling reply call), so the threshold can be far below the blunt backstop.
  - agent UP with no hung-reply signal but the placeholder is older than
    WEDGED_SEC -> fire (blunt backstop for genuinely stuck turns; generous so
    long legit tasks aren't cut short).
  - placeholder older than STALE_SEC (default 24h) -> DEAD round: deliver
    nothing, drop the marker (and the placeholder message while Telegram still
    allows deletion). TGORPHAN908: without this bound a post-outage scan walked
    28-day orphans into the backstop and sent internal work logs to the owner.

The recovered answer is scoped to the round that posted the placeholder (see
read_transcript): the transcript keeps growing after that round, so its last
text may be a later internal turn's monologue -- never deliverable here.

Standalone: scans every agent's per-agent telegram state dir. No marveen src
dependency; only Python stdlib + the `tmux` binary. Bot API base is overridable
via TELEGRAM_API_BASE (tests point it at a local stub).
"""
import datetime, hashlib, os, glob, json, re, time, subprocess, urllib.request

# State dirs to scan: per-agent dirs under the fleet, plus the default dir.
#
# TGWDOGVAK913: this daemon is launched by launchd/systemd, and launchd does NOT
# pass the operator's shell environment to a job -- the plist EnvironmentVariables
# holds only what the installer writes. So MARVEEN_ROOT is NOT set in the
# daemon's environment unless the installer put it there, and the old
# `~/marveen` default pointed at a directory that does not exist on the real
# install (root: /Users/<user>/ClaudeClaw). The watchdog then scanned two
# non-existent globs and its log stayed 0 bytes -- a sentry that guards nothing.
#
# The durable fix is self-location: when the daemon runs the repo copy at
# <root>/scripts/hooks/telegram_progress_watchdog.py (where the installer points
# the plist), the root is two directories up, needing no environment at all.
# MARVEEN_ROOT still wins as an explicit override; ~/marveen stays as the
# last-resort legacy fallback.
def _derive_fleet_root():
    env = os.environ.get("MARVEEN_ROOT")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    # <root>/scripts/hooks/telegram_progress_watchdog.py -> <root>
    if os.path.basename(here) == "hooks" and os.path.basename(os.path.dirname(here)) == "scripts":
        cand = os.path.dirname(os.path.dirname(here))
        # Confirm it looks like an install root, so a stray copy in some other
        # scripts/hooks/ tree does not silently capture the scan.
        if os.path.isdir(os.path.join(cand, ".claude")) or os.path.isdir(os.path.join(cand, "agents")):
            return cand
    return os.path.expanduser("~/marveen")


FLEET_ROOT = _derive_fleet_root()
SCAN_GLOBS = [
    os.path.join(FLEET_ROOT, "agents", "*", ".claude", "channels", "telegram", "progress"),
    # #915: the main agent's state dir is install-scoped once migrated; scan
    # both bases -- at most one holds live progress markers.
    os.path.join(FLEET_ROOT, ".claude", "channels", "telegram", "progress"),
    os.path.expanduser("~/.claude/channels/telegram/progress"),
]
DOWN_GRACE_SEC = 120        # agent down + placeholder older than this -> fire
WEDGED_SEC = 15 * 60        # agent up, no hung-reply signal, this old -> fire (backstop)
# UPPER age bound (TGORPHAN908): a marker older than this marks a DEAD round,
# not a stuck one -- there is no question behind it that needs an answer today.
# Deliver NOTHING; drop the marker. Without this bound, a fleet restart after a
# long outage walked 20-28 day old markers into the wedged-backstop branch and
# sent six internal work logs to the owner's channel (2026-09-08).
DEFAULT_STALE_SEC = 24 * 3600
# Telegram refuses deleteMessage on messages older than 48h; don't burn an API
# call (and an error log line) on a delete that cannot succeed.
TELEGRAM_DELETE_WINDOW_SEC = 47 * 3600
# A marker is written by the SAME submit hook that logs the user event into the
# transcript, so the round's opening user-prompt sits within seconds of the
# marker mtime. The slack absorbs clock/write-order jitter.
TURN_ANCHOR_SLACK_SEC = 120
# agent up + a HUNG reply detected + placeholder older than this -> fire FAST.
# Far below WEDGED_SEC because the hung-reply signal is precise. Env-tunable so
# a live install can adjust without a code change.
DEFAULT_WEDGED_UP_SEC = 180
ERROR_TEXT = ("⚠️ Valami elakadt, és erre nem érkezett válasz. "
              "Lehet, hogy újra kell indítani az ügynököt, vagy próbáld újra kicsit később.")

# TGAPIERR1113 (Klodel 40067, Patrik TG 18218, 2026-11-13): Claude Code writes its OWN error chrome into the
# transcript as an assistant row ("Please run /login · API Error: 403 Attention Required! | Cloudflare", flagged
# isApiErrorMessage:true). It is not the agent's answer, but the last-assistant-text scrape took it as one: at
# 11:34:25 the wedged-backstop delivered it six times (once per pending placeholder of the dead session
# b8999041), four of them into Patrik's private chat, and the second dead session's marker added a generic error.
# Two fixes: (1) an API-error row never becomes the answer -- it maps to ONE Hungarian sentence (API_ERROR_TEXT),
# and a later real assistant text in the same round still wins; (2) one delivery per chat: within a run, the first
# placeholder of a chat carries the text, the rest are only deleted; across runs the same text to the same chat
# is not repeated within DEDUP_SEC (progress/sent-dedup.state).
API_ERROR_TEXT = ("⚠️ Erre most nem tudtam válaszolni, mert a Claude-szolgáltatás hibát adott "
                  "(nem a gépen van a gond, újraindítás nem segít), kérlek, pár perc múlva írd újra.")
API_ERROR_RX = re.compile(r"(?:^|\s)API Error:\s*\d{3}\b|Please run /login", re.I)
DEDUP_SEC = 10 * 60
# TGAPIERR1113 b (Dave 40050, Patrik TG 658/660): on an API error Claude Code ends the turn WITHOUT the Stop hook
# (measured 2026-11-13 11:15-11:19: five 403 rows in b8999041, no "[enforce]" line in debug.log), so the
# placeholder sat until the 15-min backstop while Patrik saw only "Dolgozom rajta" and restarted the session twice,
# which cannot help an API-side error. A round whose LAST assistant row is an API error fires after this many
# seconds with the one-sentence line above. Env: TELEGRAM_WATCHDOG_API_ERROR_SEC.
DEFAULT_API_ERROR_SEC = 30
DEDUP_FILE = "sent-dedup.state"  # NOT *.json: the marker scan globs *.json


def is_api_error_event(ev, text=""):
    """True for Claude Code's own error row: the isApiErrorMessage flag, or (older format without the flag) an
    assistant text that is nothing but the API-error chrome. A real answer that merely MENTIONS an API error
    is longer than the chrome line and is not matched by the length guard."""
    if ev.get("isApiErrorMessage") is True:
        return True
    t = (text or "").strip()
    return bool(t) and len(t) <= 200 and "\n" not in t and bool(API_ERROR_RX.search(t))


def _env_int(name, default):
    v = os.environ.get(name)
    if v:
        try:
            n = int(v)
            if n > 0:
                return n
        except ValueError:
            pass
    return default


def wedged_up_sec():
    return _env_int("TELEGRAM_WATCHDOG_WEDGED_UP_SEC", DEFAULT_WEDGED_UP_SEC)


def stale_sec():
    return _env_int("TELEGRAM_WATCHDOG_STALE_SEC", DEFAULT_STALE_SEC)


def token(state_dir):
    try:
        for line in open(os.path.join(state_dir, ".env"), encoding="utf-8"):
            line = line.strip()
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    except Exception:
        return None
    return None


def api(tok, method, payload):
    base = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
    url = f"{base}/bot{tok}/{method}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode())


def agent_name_from(progress_dir):
    # .../agents/<name>/.claude/channels/telegram/progress  -> <name>
    parts = progress_dir.split(os.sep)
    if "agents" in parts:
        i = parts.index("agents")
        if i + 1 < len(parts):
            return parts[i + 1]
    return None


def tmux_session_alive(session):
    # Test/override seam: force the agent-up verdict without a real tmux probe.
    forced = os.environ.get("TELEGRAM_WATCHDOG_FORCE_AGENT_UP")
    if forced in ("0", "1"):
        return forced == "1"
    try:
        return subprocess.run(["tmux", "has-session", "-t", session],
                              capture_output=True, timeout=5).returncode == 0
    except Exception:
        return True  # if tmux probe fails, assume alive (don't false-alarm)


def _iter_events(transcript_path):
    if not transcript_path:
        return
    try:
        f = open(transcript_path, encoding="utf-8")
    except Exception:
        return
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def _is_reply_tool(name):
    n = (name or "").lower()
    return "telegram" in n and "reply" in n


def _ev_epoch(ev):
    ts = ev.get("timestamp")
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _is_user_prompt(ev):
    """A real inbound prompt (starts a turn) -- NOT a tool_result carrier."""
    msg = ev.get("message") or {}
    role = msg.get("role") or ev.get("role")
    if not (ev.get("type") == "user" or role == "user"):
        return False
    content = msg.get("content", ev.get("content"))
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") != "tool_result"
                   for b in content)
    return False


def _plain_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join((b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


class _Acc:
    """Accumulator for one scan window of the transcript."""
    def __init__(self):
        self.text = ""
        self.results = set()      # tool_use_ids that have a tool_result
        self.reply_ids = set()    # tool_use_ids of Telegram reply calls
        self.last_tool_use = None  # (id, is_reply) of the most recent tool_use
        self.api_error_last = False  # the most recent assistant row is Claude Code's API-error chrome

    def feed(self, ev):
        msg = ev.get("message") or {}
        role = msg.get("role") or ev.get("role")
        content = msg.get("content", ev.get("content"))
        is_assistant = ev.get("type") == "assistant" or role == "assistant"
        if is_assistant and is_api_error_event(ev, _plain_text(content)):
            self.text = API_ERROR_TEXT  # TGAPIERR1113: never the raw chrome; a later real text overrides
            self.api_error_last = True
            return
        if is_assistant:
            self.api_error_last = False
        if isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "tool_use":
                    is_reply = _is_reply_tool(b.get("name"))
                    self.last_tool_use = (b.get("id"), is_reply)
                    if is_reply and b.get("id") is not None:
                        self.reply_ids.add(b.get("id"))
                elif bt == "tool_result":
                    tid = b.get("tool_use_id")
                    if tid is not None:
                        self.results.add(tid)
                elif bt == "text" and is_assistant:
                    t = (b.get("text") or "").strip()
                    if t:
                        self.text = t
        elif isinstance(content, str) and is_assistant:
            if content.strip():
                self.text = content.strip()

    def reply_hung(self):
        return bool(self.last_tool_use and self.last_tool_use[1]
                    and self.last_tool_use[0] not in self.results)

    def reply_delivered(self):
        return bool(self.reply_ids & self.results)


def read_transcript(transcript_path, turn_start=None):
    """Return (last_assistant_text, reply_is_hung, reply_delivered, api_error_last).

    api_error_last (TGAPIERR1113 b): the round's most recent assistant row is Claude Code's API-error chrome
    (the turn died on an API error; last_assistant_text is then API_ERROR_TEXT).

    last_assistant_text: the agent's final user-facing answer (last non-empty
    assistant text block) -- the same source the Stop hook's fallback uses.

    reply_is_hung: True iff the most recent tool call in scope is the Telegram
    `reply` tool with no matching tool_result yet (dropped MCP).

    reply_delivered: True iff a Telegram reply call in scope DID get a result
    -- the round's answer already reached the channel, so nothing may be resent.

    Scope (TGORPHAN908): a transcript outlives the round that posted the
    placeholder -- later scheduled/internal turns keep appending, so the LAST
    text of the whole file may be internal monologue that was never meant for
    the channel (six such leaked to the owner on 2026-09-08). When `turn_start`
    (the marker mtime) is given and the transcript carries timestamped user
    prompts, only the round active at turn_start is read: from the last user
    prompt at/before turn_start+slack to the next user prompt. A timestamped
    transcript with no prompt at/before the marker is unattributable -> no
    answer (generic-error path), never a foreign turn's text. Transcripts
    without timestamped prompts (older format) keep the whole-file behavior.
    """
    whole = _Acc()
    scoped = _Acc()
    have_ts_prompt = False
    anchor_seen = False
    in_window = False
    for ev in _iter_events(transcript_path):
        if _is_user_prompt(ev):
            e = _ev_epoch(ev)
            if e is not None:
                have_ts_prompt = True
                if turn_start is not None and e <= turn_start + TURN_ANCHOR_SLACK_SEC:
                    scoped = _Acc()  # a later prompt supersedes: window restarts
                    anchor_seen = True
                    in_window = True
                elif in_window:
                    in_window = False  # the marker's round ended here
        whole.feed(ev)
        if in_window:
            scoped.feed(ev)
    if turn_start is not None and have_ts_prompt:
        if not anchor_seen:
            return "", False, False, False
        return scoped.text, scoped.reply_hung(), scoped.reply_delivered(), scoped.api_error_last
    return whole.text, whole.reply_hung(), False, whole.api_error_last


def log(progress_dir, msg):
    try:
        with open(os.path.join(progress_dir, "debug.log"), "a", encoding="utf-8") as f:
            f.write(f"[watchdog {time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def _dedup_load(progress_dir, now):
    try:
        d = json.load(open(os.path.join(progress_dir, DEDUP_FILE)))
        return {k: v for k, v in d.items() if isinstance(v, (int, float)) and now - v < DEDUP_SEC}
    except Exception:
        return {}


def _dedup_save(progress_dir, d):
    try:
        with open(os.path.join(progress_dir, DEDUP_FILE), "w") as f:
            json.dump(d, f)
    except Exception:
        pass


def _dedup_key(chat_id, text):
    return f"{chat_id}:" + hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def drop_placeholder(tok, chat_id, message_id, progress_dir):
    """A duplicate of a delivery already made to this chat: only remove the placeholder."""
    try:
        api(tok, "deleteMessage", {"chat_id": chat_id, "message_id": message_id})
    except Exception as e:
        log(progress_dir, f"placeholder delete failed (mid={message_id}): {e}")
    return "dedup-deleted"


def deliver(tok, chat_id, message_id, answer, progress_dir):
    """Deliver the real answer if we have one (sendMessage + drop the
    placeholder), else rewrite the placeholder into a generic error. Returns a
    short label for logging."""
    if answer:
        try:
            api(tok, "sendMessage", {"chat_id": chat_id, "text": answer[:4000]})
        except Exception as e:
            log(progress_dir, f"real-answer send failed (mid={message_id}): {e}")
            return "send-failed"
        try:
            api(tok, "deleteMessage", {"chat_id": chat_id, "message_id": message_id})
        except Exception as e:
            log(progress_dir, f"placeholder delete failed (mid={message_id}): {e}")
        return "real-answer"
    # No recoverable answer -> generic error, keep the (edited) placeholder.
    try:
        api(tok, "editMessageText",
            {"chat_id": chat_id, "message_id": message_id, "text": ERROR_TEXT})
    except Exception as e:
        log(progress_dir, f"error edit failed (mid={message_id}): {e}")
    return "generic-error"


def handle_dir(progress_dir):
    state_dir = os.path.dirname(progress_dir)           # .../telegram
    name = agent_name_from(progress_dir)
    agent_up = tmux_session_alive(f"agent-{name}") if name else True
    now = time.time()
    # Sweep orphan dedup markers (normally removed by the Stop hook).
    for m in glob.glob(os.path.join(progress_dir, "seen-*.marker")):
        try:
            if now - os.path.getmtime(m) > 3600:
                os.remove(m)
        except Exception:
            pass
    tok = None
    up_sec = wedged_up_sec()
    api_err_sec = _env_int("TELEGRAM_WATCHDOG_API_ERROR_SEC", DEFAULT_API_ERROR_SEC)
    max_age = stale_sec()
    # TGAPIERR1113: one delivery per chat -- key = chat + the text that would go out (answer or the error line).
    dedup = _dedup_load(progress_dir, now)
    dedup_dirty = False
    for path in glob.glob(os.path.join(progress_dir, "*.json")):
        try:
            age = now - os.path.getmtime(path)
        except Exception:
            continue
        try:
            pend = json.load(open(path))
        except Exception:
            pend = []
        if not pend or not isinstance(pend, list):
            continue

        # UPPER age bound (TGORPHAN908): a marker this old marks a DEAD round.
        # Whatever answer might be scraped from its transcript, nobody is
        # waiting for it today -- deliver NOTHING, drop the marker. The
        # placeholder message is cleaned up only while Telegram still allows
        # deletion (<48h); past that the delete can only fail (HTTP 400).
        if age > max_age:
            if age < TELEGRAM_DELETE_WINDOW_SEC:
                if tok is None:
                    tok = token(state_dir)
                if tok:
                    for p in pend:
                        try:
                            api(tok, "deleteMessage",
                                {"chat_id": p.get("chat_id"),
                                 "message_id": p.get("message_id")})
                        except Exception as e:
                            log(progress_dir,
                                f"stale placeholder delete failed "
                                f"(mid={p.get('message_id')}): {e}")
            try:
                os.remove(path)
            except Exception:
                pass
            log(progress_dir, f"orphan dropped (stale): {os.path.basename(path)} "
                              f"age={int(age)}s delivered=none")
            continue

        # The transcript path is stamped onto the pending entries by the submit
        # hook (same for the whole turn); read the agent's answer + hung-reply
        # signal once, scoped to the round that posted this marker.
        transcript_path = ""
        for p in pend:
            if p.get("transcript_path"):
                transcript_path = p["transcript_path"]
                break
        answer, reply_hung, reply_delivered, api_error_last = read_transcript(
            transcript_path, turn_start=now - age)

        # Fire decision.
        if not agent_up:
            fire = age > DOWN_GRACE_SEC
            reason = "agent-down"
        elif reply_hung and age > up_sec:
            fire = True
            reason = "reply-hung"
        elif api_error_last and age > api_err_sec:
            fire = True
            reason = "api-error"
        elif age > WEDGED_SEC:
            fire = True
            reason = "wedged-backstop"
        else:
            fire = False
            reason = ""
        if not fire:
            continue

        if tok is None:
            tok = token(state_dir)
        if not tok:
            continue

        # The round's own reply already reached the channel (a reply call in
        # this round's window has a result): the marker is leftover bookkeeping
        # from a missed Stop hook. Resending would duplicate the answer -- and
        # the transcript's LAST text may belong to a later, internal turn.
        # Clear silently.
        if reply_delivered and not reply_hung:
            for p in pend:
                try:
                    api(tok, "deleteMessage",
                        {"chat_id": p.get("chat_id"),
                         "message_id": p.get("message_id")})
                except Exception as e:
                    log(progress_dir,
                        f"placeholder delete failed (mid={p.get('message_id')}): {e}")
            try:
                os.remove(path)
            except Exception:
                pass
            log(progress_dir, f"orphan cleared (reply-already-delivered): "
                              f"{os.path.basename(path)} agent_up={agent_up} "
                              f"age={int(age)}s delivered=none")
            continue

        modes = []
        for p in pend:
            cid = p.get("chat_id")
            key = _dedup_key(cid, answer or ERROR_TEXT)
            if key in dedup:
                modes.append(drop_placeholder(tok, cid, p.get("message_id"), progress_dir))
                continue
            mode = deliver(tok, cid, p.get("message_id"), answer, progress_dir)
            modes.append(mode)
            if mode in ("real-answer", "generic-error"):
                dedup[key] = now
                dedup_dirty = True
        try:
            os.remove(path)
        except Exception:
            pass
        log(progress_dir, f"orphan handled ({reason}): {os.path.basename(path)} "
                          f"agent_up={agent_up} age={int(age)}s "
                          f"delivered={','.join(modes)}")
    if dedup_dirty:
        _dedup_save(progress_dir, dedup)


def main():
    dirs = []
    for g in SCAN_GLOBS:
        dirs.extend(glob.glob(g))
    for d in dirs:
        if os.path.isdir(d):
            handle_dir(d)


if __name__ == "__main__":
    main()
