#!/usr/bin/env python3
"""Test the Telegram-reply Stop hook (scripts/hooks/telegram-reply-guard.py).

Drives the hook as a subprocess against an isolated ledger DB (LEDGER_DB_PATH),
asserting the block/allow decision for each scenario. Run:  python3 <thisfile>
Exit 0 = all pass; non-zero = a failure (message on stderr).
"""
import os
import sys
import json
import time
import tempfile
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.join(os.path.dirname(HERE), "hooks")
HOOK = os.path.join(HOOKS, "telegram-reply-guard.py")
sys.path.insert(0, HOOKS)


import contextlib
import importlib.util


def load_guard():
    """Import the hook as a module, so its helpers can be called directly."""
    spec = importlib.util.spec_from_file_location("guard_mod", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@contextlib.contextmanager
def env_patch(vars, install_dir=None):
    """Set/clear env vars (and optionally the install dir) for one block."""
    import ledger_lib
    regi = {k: os.environ.get(k) for k in vars}
    regi_dir = getattr(ledger_lib, "_install_dir", None)
    for k, v in vars.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    if install_dir is not None:
        ledger_lib._install_dir = lambda *_a, **_k: install_dir
    try:
        yield
    finally:
        for k, v in regi.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if install_dir is not None and regi_dir is not None:
            ledger_lib._install_dir = regi_dir


# The identity the rows are ledgered under AND the identity the hook resolves.
# They used to be two different things: the rows said "marveen", while the hook
# took its id from the install -- MAIN_AGENT_ID in <install>/.env, "marveen" only
# as the fallback. On any install whose main agent has another name the hook
# looked under that name, found no open question, and every case returned
# got=None: the allow cases went green for the wrong reason and the suite could
# not tell a working guard from a dead one. MARVEEN_AGENT_ID is the explicit
# override agent_id_from_payload honours before the cwd, so pinning it here
# makes the result independent of the host.
AGENT = "tgguard-test"


def run_hook(db_path, cwd=None, extra_env=None):
    env = dict(os.environ)
    env["LEDGER_DB_PATH"] = db_path
    env["MARVEEN_AGENT_ID"] = AGENT
    if extra_env:
        env.update(extra_env)
    p = subprocess.run(
        [sys.executable, HOOK],
        input=json.dumps({"cwd": cwd or os.path.dirname(db_path), "stop_hook_active": False}),
        capture_output=True, text=True, env=env, timeout=20,
    )
    out = p.stdout.strip()
    decision, reason = None, ""
    if out:
        try:
            parsed = json.loads(out)
            decision = parsed.get("decision")
            reason = parsed.get("reason") or ""
        except Exception:
            decision = "PARSE_ERROR:" + out
    # An allow is "exit 0, no output". A hook that crashes before deciding
    # looks the same on stdout, so the run must also be clean.
    if p.returncode != 0 or p.stderr.strip():
        decision = f"UNCLEAN(rc={p.returncode}):{p.stderr.strip()[-200:]}"
    return decision, reason, p.returncode


# Kept alive for the whole run; TemporaryDirectory removes each one when the
# interpreter finalises it.
_TMPDIRS = []


def fresh_db():
    # Each DB gets its own directory. The hook keeps its per-agent statefile
    # NEXT TO the DB (_statefile: dirname(db_path())/.tg-reply-guard-<agent>),
    # and AGENT is a constant, so a DB made straight in the shared tmpdir put
    # every concurrent run of this suite on the same statefile -- and the old
    # "clear stale statefiles" sweep here deleted the other runs' state
    # mid-case. A private directory makes the statefile private too, starts
    # every case clean without touching anyone else's files, and needs no
    # sweep at all.
    d = tempfile.TemporaryDirectory(prefix="tgguard-")
    _TMPDIRS.append(d)
    return os.path.join(d.name, "ledger.db")


def load_lib(db_path):
    os.environ["LEDGER_DB_PATH"] = db_path
    import importlib
    import ledger_lib
    importlib.reload(ledger_lib)
    return ledger_lib


FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got={got!r} want={want!r}")
    if not ok:
        FAILS.append(name)


def main():
    # 1. Unanswered real question -> BLOCK
    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound(AGENT, "8695313113", "1001", "mennyi 2+2?", "2026-08-02T22:00:00.000Z")
    d, _r, _ = run_hook(db)
    check("unanswered question blocks", d, "block")

    # 2. Same question, but answered via reply-tool (outbound logged) -> ALLOW
    lib.log_outbound(AGENT, "8695313113", "4")
    d, _r, _ = run_hook(db)
    check("answered question allows", d, None)

    # 3. Pure acknowledgement -> ALLOW (no reply owed)
    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound(AGENT, "8695313113", "1002", "köszi 👍", "2026-08-02T22:05:00.000Z")
    d, _r, _ = run_hook(db)
    check("ack allows", d, None)
    # Liveness control: the same DB with a real question after the ack must
    # block. Without it "ack allows" is also what a hook that never finds
    # anything would return.
    lib.log_inbound(AGENT, "8695313113", "1012", "és mikor?", "2026-08-02T22:06:00.000Z")
    d, _r, _ = run_hook(db)
    check("ack control: a later question on the same DB blocks", d, "block")

    # 4. Stale (older than STALE_SECONDS) unanswered question -> ALLOW
    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound(AGENT, "8695313113", "1003", "regi kerdes", "2026-08-01T00:00:00.000Z")
    # backdate created_at directly
    con = lib.connect()
    con.execute("UPDATE conversation_log SET created_at=? WHERE message_id='1003'",
                (int(time.time()) - 4000,))
    con.commit(); con.close()
    d, _r, _ = run_hook(db)
    check("stale question allows", d, None)
    # Control: the same row with a staleness window wider than its age must
    # block, so it is the age that allowed it, not a hook that saw nothing.
    d, _r, _ = run_hook(db, extra_env={"TG_GUARD_STALE_SECONDS": "86400"})
    check("stale control: same row inside the window blocks", d, "block")

    # 5. Max-block backstop: after MAX_BLOCKS blocks on the same id -> ALLOW
    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound(AGENT, "8695313113", "1004", "makacs kerdes", "2026-08-02T22:10:00.000Z")
    env = {"TG_GUARD_MAX_BLOCKS": "2"}
    d1, _r, _ = run_hook(db, extra_env=env)   # block 1
    d2, _r, _ = run_hook(db, extra_env=env)   # block 2
    d3, _r, _ = run_hook(db, extra_env=env)   # now over the cap -> allow
    check("maxblock #1 blocks", d1, "block")
    check("maxblock #2 blocks", d2, "block")
    check("maxblock #3 allows (backstop)", d3, None)

    # 6. No inbound at all (e.g. a heartbeat-only turn) -> ALLOW
    db = fresh_db()
    lib = load_lib(db)
    d, _r, _ = run_hook(db)
    check("no inbound allows", d, None)
    lib.log_inbound(AGENT, "8695313113", "1006", "most mar van kerdes?", "2026-08-02T22:20:00.000Z")
    d, _r, _ = run_hook(db)
    check("no-inbound control: once a question arrives it blocks", d, "block")

    # 6b. Rows ledgered under ANOTHER agent must not make this one block. This
    #     is the other half of the identity pin: the hook reads its own rows.
    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound("some-other-agent", "8695313113", "1007", "kinek szol ez?", "2026-08-02T22:25:00.000Z")
    d, _r, _ = run_hook(db)
    check("another agent's open question does not block this one", d, None)
    d, _r, _ = run_hook(db, extra_env={"MARVEEN_AGENT_ID": "some-other-agent"})
    check("... but blocks the agent it belongs to", d, "block")

    # 7. Provider resolution and the reply-tool name it produces.
    #    A table test, because the two halves of the tool name differ per
    #    provider: mcp__plugin_<plugin directory>_<MCP server>__reply. Slack is
    #    the case that motivated it -- the plugin directory is `slack-channel`
    #    while the MCP server is `slack`, so deriving the name from the provider
    #    alone produced a tool that does not exist in any session.
    guard = load_guard()

    # 7a. CHANNEL_PROVIDER in the environment wins over everything.
    for provider, vart_tool in [
        ("telegram", "mcp__plugin_telegram_telegram__reply"),
        ("discord", "mcp__plugin_discord_discord__reply"),
        ("slack", "mcp__plugin_slack-channel_slack__reply"),
        ("SLACK", "mcp__plugin_slack-channel_slack__reply"),  # case-folded
    ]:
        with env_patch({"CHANNEL_PROVIDER": provider}):
            tool, nev = guard._reply_tool_name()
        check(f"env {provider} -> tool", tool, vart_tool)
        check(f"env {provider} -> name", nev, provider.lower())

    # 7b. A provider we know of but whose real tool name is unverified must NOT
    #     get an invented name. A wrong name is worse than none: the model cannot
    #     comply with a directive naming a tool absent from its session, which is
    #     the exact failure this guard exists to remove.
    #     (An EMPTY CHANNEL_PROVIDER is not this case: it is falsy, so resolution
    #     correctly falls through to .env and the project settings. 7d covers it.)
    for provider in ("teams", "googlechat", "whatsapp"):
        with env_patch({"CHANNEL_PROVIDER": provider}):
            tool, _ = guard._reply_tool_name()
        check(f"unverified {provider} -> generic wording",
              tool, "a csatorna reply tool")

    # 7c. With no environment value, the install .env is consulted, then the
    #     project settings. Both are exercised through a temporary install dir.
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, ".env"), "w") as f:
            f.write("CHANNEL_PROVIDER=discord\n")
        with env_patch({"CHANNEL_PROVIDER": None}, install_dir=d):
            tool, _ = guard._reply_tool_name()
        check(".env discord -> tool", tool, "mcp__plugin_discord_discord__reply")

    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, ".claude"))
        with open(os.path.join(d, ".claude", "settings.json"), "w") as f:
            json.dump({"enabledPlugins": {"slack-channel@marveen-marketplace": True}}, f)
        with env_patch({"CHANNEL_PROVIDER": None, "CLAUDE_PROJECT_DIR": d}, install_dir=d):
            tool, _ = guard._reply_tool_name()
        check("settings slack-channel -> slack tool", tool,
              "mcp__plugin_slack-channel_slack__reply")

    # 7d. Nothing configured anywhere: no tool is named, and the guard still
    #     fires. The PR text once claimed telegram was the fallback; it is not.
    with tempfile.TemporaryDirectory() as d:
        with env_patch({"CHANNEL_PROVIDER": None, "CLAUDE_PROJECT_DIR": d}, install_dir=d):
            tool, nev = guard._reply_tool_name()
        check("nothing configured -> generic wording", tool, "a csatorna reply tool")
        check("nothing configured -> generic name", nev, "csatorna")

    # 8. Fixture isolation: the hook's statefile sits beside the DB, so every
    #    DB must live in a directory of its own, and making a new one must not
    #    touch the statefile of another DB (a concurrent run of this suite).
    a, b = fresh_db(), fresh_db()
    check("fresh_db: private dir, not the shared tmpdir",
          os.path.dirname(a) != tempfile.gettempdir(), True)
    check("fresh_db: each DB its own dir",
          os.path.dirname(a) != os.path.dirname(b), True)
    other = os.path.join(os.path.dirname(a), f".tg-reply-guard-{AGENT}")
    with open(other, "w") as f:
        f.write("{}")
    fresh_db()
    check("fresh_db: leaves another DB's statefile alone", os.path.exists(other), True)

    # ---- PROVIDERVAK908: the directive must name the RIGHT channel's reply tool.
    # Measured 2026-09-07: a DISCORD inbound (the owner's DM) was answered with a demand for a TELEGRAM reply. The
    # decision was right, the instruction was undeliverable -- so asserting only
    # decision=="block" (as this file did) passes straight through the bug.
    TG_TOOL = "mcp__plugin_telegram_telegram__reply"
    DC_TOOL = "mcp__plugin_discord_discord__reply"

    # 9. Discord inbound -> names the Discord tool, and NOT the Telegram one.
    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound(AGENT, "900000000000000001", "2001", "ez mi is?",
                    "2026-09-07T07:02:03.110Z", source="plugin:discord:discord")
    d, r, _ = run_hook(db)
    check("discord inbound blocks", d, "block")
    check("discord names discord tool", DC_TOOL in r, True)
    check("discord does NOT name telegram tool", TG_TOOL in r, False)

    # 10. Telegram inbound -> unchanged behaviour, names the Telegram tool.
    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound(AGENT, "8695313113", "2002", "mi ujsag?",
                    "2026-09-07T07:02:03.110Z", source="plugin:telegram:telegram")
    d, r, _ = run_hook(db)
    check("telegram inbound blocks", d, "block")
    check("telegram names telegram tool", TG_TOOL in r, True)
    check("telegram does NOT name discord tool", DC_TOOL in r, False)

    # 11. Legacy row (source NULL, written before the column existed) -> still
    # blocks, and names the CONFIGURED channel's verified tool (Marveen 32905:
    # the #1606 provider, NOT the generic wording); with a provider whose tool is
    # unverified it names no tool at all. CHANNEL_PROVIDER is set explicitly in
    # every case, so the result does not depend on the host's own .env.
    SL_TOOL = "mcp__plugin_slack-channel_slack__reply"
    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound(AGENT, "8695313113", "2003", "regi sor, nincs source",
                    "2026-09-07T07:02:03.110Z")
    d, r, _ = run_hook(db, extra_env={"CHANNEL_PROVIDER": "discord"})
    check("legacy row blocks", d, "block")
    check("legacy row + configured discord -> names the discord tool", DC_TOOL in r, True)
    check("legacy row + configured discord -> not the generic wording",
          "ANNAK a csatornának" in r, False)
    check("legacy row still carries chat_id", "8695313113" in r, True)
    d, r, _ = run_hook(db, extra_env={"CHANNEL_PROVIDER": "telegram"})
    check("legacy row + configured telegram -> names the telegram tool", TG_TOOL in r, True)
    d, r, _ = run_hook(db, extra_env={"CHANNEL_PROVIDER": "teams"})
    check("legacy row + unverified provider -> names no tool",
          (TG_TOOL in r or DC_TOOL in r or SL_TOOL in r), False)
    check("legacy row + unverified provider -> generic wording",
          "ANNAK a csatornának" in r, True)

    # 11b. The message's own source WINS over the configured channel: a Discord
    # inbound on a Telegram-configured install names the Discord tool.
    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound(AGENT, "900000000000000002", "2004", "es ez?",
                    "2026-09-07T07:02:03.110Z", source="plugin:discord:discord")
    d, r, _ = run_hook(db, extra_env={"CHANNEL_PROVIDER": "telegram"})
    check("source discord beats configured telegram", (DC_TOOL in r, TG_TOOL in r), (True, False))

    # 11c. A source that names no tool (a dash: Slack's plugin:slack-channel:slack)
    # borrows the configured tool only for the SAME provider, never another one.
    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound(AGENT, "C0SLACK", "2005", "slack kerdes",
                    "2026-09-07T07:02:03.110Z", source="plugin:slack-channel:slack")
    d, r, _ = run_hook(db, extra_env={"CHANNEL_PROVIDER": "slack"})
    check("slack-channel source + configured slack -> the verified slack tool", SL_TOOL in r, True)
    d, r, _ = run_hook(db, extra_env={"CHANNEL_PROVIDER": "telegram"})
    check("slack-channel source + configured telegram -> NOT the telegram tool", TG_TOOL in r, False)
    check("slack-channel source + configured telegram -> generic wording", "ANNAK a csatornának" in r, True)

    # 12. END-TO-END: the capture hook must actually RECORD the source. Without
    # this the three cases above test a column nothing ever populates.
    db = fresh_db()
    lib = load_lib(db)
    capture = os.path.join(HOOKS, "ledger-capture.py")
    envelope = (
        '<channel source="plugin:discord:discord" chat_id="900000000000000001" '
        'message_id="3001" user="stylnet" ts="2026-09-07T07:02:03.110Z">'
        "ez mi is?</channel>"
    )
    env = dict(os.environ)
    env["LEDGER_DB_PATH"] = db
    env["MARVEEN_AGENT_ID"] = AGENT
    subprocess.run([sys.executable, capture],
                   input=json.dumps({"cwd": os.path.dirname(db), "prompt": envelope}),
                   capture_output=True, text=True, env=env, timeout=20)
    con = lib.connect()
    row = con.execute("SELECT source, text FROM conversation_log"
                      " WHERE message_id='3001'").fetchone()
    con.close()
    check("capture records source", row[0] if row else None, "plugin:discord:discord")
    check("capture still records text", row[1] if row else None, "ez mi is?")
    check("capture -> guard names discord tool",
          DC_TOOL in run_hook(db)[1], True)

    # 7. Klodel 34050 (Balázs csoport TG 3631): an emoji reaction acknowledges a group message, no new message.
    outbound = os.path.join(HOOKS, "telegram-react-ack.py")

    def react(db, chat, response="reacted", tool="mcp__plugin_telegram_telegram__react"):
        env = dict(os.environ)
        env["LEDGER_DB_PATH"] = db
        env["MARVEEN_AGENT_ID"] = AGENT
        payload = {"cwd": os.path.dirname(db), "tool_name": tool,
                   "tool_input": {"chat_id": chat, "message_id": "5001", "emoji": "👍"},
                   "tool_response": [{"type": "text", "text": response}] if isinstance(response, str) else response}
        p = subprocess.run([sys.executable, outbound], input=json.dumps(payload),
                           capture_output=True, text=True, env=env, timeout=20)
        return p.returncode

    GRP = "-1009990001"
    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound(AGENT, GRP, "5001", "szerintem a B jobb, Patrik?", "2026-11-09T12:00:00.000Z")
    check("react: unanswered group message blocks", run_hook(db)[0], "block")
    check("react: hook exits clean", react(db, GRP), 0)
    check("react: a reaction in the chat allows", run_hook(db)[0], None)
    check("react: no ledger 'out' row written", lib.connect().execute(
        "SELECT COUNT(*) FROM conversation_log WHERE direction='out'").fetchone()[0], 0)
    # a later inbound after the reaction blocks again (the reaction answered the earlier one only)
    con = lib.connect()
    lib.log_inbound(AGENT, GRP, "5002", "és a C?", "2026-11-09T12:01:00.000Z")
    con.execute("UPDATE conversation_log SET created_at=? WHERE message_id='5002'", (int(time.time()) + 5,))
    con.commit(); con.close()
    check("react: a newer inbound after the reaction blocks", run_hook(db)[0], "block")

    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound(AGENT, GRP, "5003", "mi legyen?", "2026-11-09T12:02:00.000Z")
    react(db, "-1000000000999")
    check("react: a reaction in ANOTHER chat still blocks", run_hook(db)[0], "block")

    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound(AGENT, GRP, "5004", "mi legyen?", "2026-11-09T12:03:00.000Z")
    react(db, GRP, response={"isError": True, "content": [{"type": "text", "text": "reaction failed: REACTION_INVALID"}]})
    check("react: a failed reaction (isError) still blocks", run_hook(db)[0], "block")
    react(db, GRP, tool="mcp__plugin_telegram_telegram__edit_message")
    check("react: another tool (edit_message) does not count", run_hook(db)[0], "block")

    db = fresh_db()
    lib = load_lib(db)
    react(db, GRP)
    rf = lib._reaction_file(AGENT)
    json.dump({GRP: int(time.time()) - 600}, open(rf, "w"))  # the reaction is OLDER than the inbound
    lib.log_inbound(AGENT, GRP, "5005", "új kérdés", "2026-11-09T12:04:00.000Z")
    check("react: a reaction older than the inbound still blocks", run_hook(db)[0], "block")

    # the "Dolgozom rajta" placeholder goes on a react too (no token -> no API call, only the state file)
    clear = os.path.join(HOOKS, "telegram_progress_reply_clear.py")
    sd = tempfile.TemporaryDirectory(prefix="tgprog-")
    _TMPDIRS.append(sd)
    os.makedirs(os.path.join(sd.name, "progress"))
    pend = os.path.join(sd.name, "progress", "sid1.json")
    json.dump([{"chat_id": GRP, "message_id": 77}], open(pend, "w"))
    env = dict(os.environ)
    env["TELEGRAM_STATE_DIR"] = sd.name
    subprocess.run([sys.executable, clear], input=json.dumps({"session_id": "sid1",
                   "tool_name": "mcp__plugin_telegram_telegram__react",
                   "tool_input": {"chat_id": GRP, "message_id": "5001", "emoji": "👍"}}),
                   capture_output=True, text=True, env=env, timeout=20)
    check("react: placeholder cleared", os.path.exists(pend), False)
    json.dump([{"chat_id": GRP, "message_id": 78}], open(pend, "w"))
    subprocess.run([sys.executable, clear], input=json.dumps({"session_id": "sid1",
                   "tool_name": "mcp__plugin_telegram_telegram__download_attachment",
                   "tool_input": {"chat_id": GRP}}), capture_output=True, text=True, env=env, timeout=20)
    check("react: another telegram tool keeps the placeholder", os.path.exists(pend), True)

    # 8. Klodel 37860 (Balázs TG 5277): "not for me" close -- guard, live drain and progress Stop hook accept it.
    close_cli = os.path.join(HOOKS, "ledger-close.py")
    drain = os.path.join(HOOKS, "ledger-live-drain.py")

    def run_close(db, *args):
        env = dict(os.environ)
        env["LEDGER_DB_PATH"] = db
        env["MARVEEN_AGENT_ID"] = AGENT
        p = subprocess.run([sys.executable, close_cli, *args], capture_output=True, text=True, env=env,
                           cwd=os.path.dirname(db), timeout=20)
        return p.returncode

    def run_drain(db):
        env = dict(os.environ)
        env["LEDGER_DB_PATH"] = db
        env["MARVEEN_AGENT_ID"] = AGENT
        p = subprocess.run([sys.executable, drain], capture_output=True, text=True, env=env,
                           cwd=os.path.dirname(db), timeout=20)
        return p.stdout.startswith("OPEN_QUESTION")

    def aged(lib, mid, secs=300):
        con = lib.connect()
        con.execute("UPDATE conversation_log SET created_at=? WHERE message_id=?", (int(time.time()) - secs, mid))
        con.commit(); con.close()

    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound(AGENT, GRP, "5260", "regeljek be ? Patrik", "2026-11-11T13:00:00.000Z")
    aged(lib, "5260")
    check("close: without a close the guard blocks", run_hook(db)[0], "block")
    check("close: without a close the drain surfaces it", run_drain(db), True)
    check("close: a note without 'nem nekem:' is refused", run_close(db, GRP, "5260", "Balázsnak szólt"), 2)
    check("close: an empty addressee is refused", run_close(db, GRP, "5260", "nem nekem:   "), 2)
    check("close: an unknown message is refused", run_close(db, GRP, "9999", "nem nekem: Balázsnak"), 2)
    check("close: a 1-letter addressee is refused (L1)", run_close(db, GRP, "5260", "nem nekem: x"), 2)
    check("close: a non-integer message id is refused (I2)", run_close(db, GRP, "5260;x", "nem nekem: Balázsnak"), 2)
    check("close: refused attempts wrote nothing", os.path.exists(lib._closed_file(AGENT)), False)
    check("close: a valid close exits 0", run_close(db, GRP, "5260", "nem nekem: Patrik Balázsnak"), 0)
    check("close: the guard allows the closed message", run_hook(db)[0], None)
    check("close: audit log line written",
          "nem nekem: Patrik Balázsnak" in open(lib._closed_file(AGENT)[:-5] + ".log", encoding="utf-8").read(), True)
    check("close: no ledger 'out' row written", lib.connect().execute(
        "SELECT COUNT(*) FROM conversation_log WHERE direction='out'").fetchone()[0], 0)
    lib.log_inbound(AGENT, GRP, "5261", "és mikor?", "2026-11-11T13:01:00.000Z")
    con = lib.connect()
    con.execute("UPDATE conversation_log SET created_at=? WHERE message_id='5261'", (int(time.time()) - 200,))
    con.commit(); con.close()
    check("close: a newer, unclosed inbound blocks again", run_hook(db)[0], "block")
    check("close: ... and the drain surfaces it", run_drain(db), True)

    # 9. Retro R9 (card dddca664, hibanapló L218): a group message addressed to someone else by name leads with the
    # "not for me" close; the agent's own name, a private chat and a third-person mention keep the reply directive.
    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound(AGENT, GRP, "5300", "regeljek be ? Patrik", "2026-11-11T13:10:00.000Z")
    aged(lib, "5300")
    d, r, _ = run_hook(db)
    check("R9: addressed to Patrik in the group blocks", d, "block")
    check("R9: ... the directive leads with NEM-NEKEM and names Patrik", r.startswith("⚠️ NEM-NEKEM?") and "neki: Patrik" in r, True)
    check("R9: ... it gives the exact close command", f'ledger-close.py {GRP} 5300 "nem nekem: Patrik"' in r, True)
    check("R9: ... and does not say 'send the reply NOW'", "MOST" in r, False)
    check("R9: the suggested close is accepted", run_close(db, GRP, "5300", "nem nekem: Patrik"), 0)
    check("R9: ... and the guard then allows", run_hook(db)[0], None)
    for mid, text in (("5301", "Balázs, ezt nézd meg"), ("5302", "jó így, Balázs?"), ("5303", "@patrik mehet?")):
        db = fresh_db()
        lib = load_lib(db)
        lib.log_inbound(AGENT, GRP, mid, text, "2026-11-11T13:11:00.000Z")
        aged(lib, mid)
        d, r, _ = run_hook(db)
        check(f"R9: vocative {text!r} -> NEM-NEKEM", (d, r.startswith("⚠️ NEM-NEKEM?")), ("block", True))
    for mid, text in (("5310", "Patrik szerint jó ez?"), ("5311", "Ezt mondta Patrik"), ("5312", "szerintetek?"),
                      ("5313", "kernel, pulzus miért állnak?"), ("5314", "ki vette észre a hibát? majsztro?")):
        db = fresh_db()
        lib = load_lib(db)
        lib.log_inbound(AGENT, GRP, mid, text, "2026-11-11T13:12:00.000Z")
        aged(lib, mid)
        d, r, _ = run_hook(db)
        check(f"R9: no vocative {text!r} -> reply directive", (d, r.startswith("⚠️ VÁLASZOLATLAN")), ("block", True))
    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound(AGENT, "4242002", "6100", "Patrik, mehet?", "2026-11-11T13:13:00.000Z")
    aged(lib, "6100")
    d, r, _ = run_hook(db)
    check("R9: a private chat keeps the reply directive (no close there)", (d, r.startswith("⚠️ VÁLASZOLATLAN")), ("block", True))
    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound("klodel", GRP, "5320", "Klodel, Patrik szerint mehet?", "2026-11-11T13:14:00.000Z")
    aged(lib, "5320")
    d, r, _ = run_hook(db, extra_env={"MARVEEN_AGENT_ID": "klodel"})
    check("R9: addressed to this agent by name -> reply directive", (d, r.startswith("⚠️ VÁLASZOLATLAN")), ("block", True))

    # the drain dedups a surfaced id, so the close is checked on a DB the drain has not seen yet
    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound(AGENT, GRP, "5262", "Patrik, mehet?", "2026-11-11T13:02:00.000Z")
    aged(lib, "5262")
    run_close(db, GRP, "5262", "nem nekem: Balázs Patriknak")
    check("close: the drain does not surface a closed message", run_drain(db), False)
    lib.log_inbound(AGENT, GRP, "5263", "Patrik, és ez?", "2026-11-11T13:03:00.000Z")
    aged(lib, "5263", 250)
    check("close: control -- the drain does surface the next, unclosed one", run_drain(db), True)

    # the drain honours a reaction too (measured 13:58: OPEN_QUESTION after a 👍)
    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound(AGENT, GRP, "5270", "szerintetek?", "2026-11-11T13:50:00.000Z")
    aged(lib, "5270", 200)
    react(db, GRP)
    check("drain: a reaction after the inbound silences it", run_drain(db), False)

    # progress Stop hook: a closed inbound's placeholder goes, the stop is NOT blocked, nothing is sent
    pclear = os.path.join(HOOKS, "telegram_progress_clear.py")
    db = fresh_db()
    lib = load_lib(db)
    lib.log_inbound(AGENT, GRP, "5280", "Balázs, ránézel?", "2026-11-11T13:55:00.000Z")
    sd2 = tempfile.TemporaryDirectory(prefix="tgprog-")
    _TMPDIRS.append(sd2)
    os.makedirs(os.path.join(sd2.name, "progress"))
    pend2 = os.path.join(sd2.name, "progress", "sid2.json")

    def run_pclear(db):
        env = dict(os.environ)
        env["LEDGER_DB_PATH"] = db
        env["MARVEEN_AGENT_ID"] = AGENT
        env["TELEGRAM_STATE_DIR"] = sd2.name
        p = subprocess.run([sys.executable, pclear], input=json.dumps({"session_id": "sid2", "cwd": os.path.dirname(db),
                           "stop_hook_active": False}), capture_output=True, text=True, env=env, timeout=20)
        return (json.loads(p.stdout).get("decision") if p.stdout.strip() else None), p.returncode

    json.dump([{"chat_id": GRP, "message_id": 91, "src_mid": "5280"}], open(pend2, "w"))
    check("progress: an unclosed inbound's placeholder blocks the stop", run_pclear(db), ("block", 0))
    os.remove(os.path.join(sd2.name, "progress", "enforce-sid2.marker"))
    check("progress: close exits 0", run_close(db, GRP, "5280", "nem nekem: Patrik Balázsnak"), 0)
    check("progress: a closed inbound does not block", run_pclear(db), (None, 0))
    check("progress: its placeholder state is cleared", os.path.exists(pend2), False)

    # 9. Viktor 37867 M1: the owner's private message and a reply to our own message cannot be closed.
    db = fresh_db()
    lib = load_lib(db)
    PRIV = "4242001"
    lib.log_inbound(AGENT, PRIV, "6001", "Kernel, ránézel?", "2026-11-11T14:00:00.000Z")
    check("M1a: a private-chat inbound is refused", run_close(db, PRIV, "6001", "nem nekem: Balázsnak"), 2)
    lib.log_outbound(AGENT, GRP, "itt a link", message_id="7001")
    lib.log_inbound(AGENT, GRP, "5290", "és ezt hova?", "2026-11-11T14:01:00.000Z", reply_to_message_id="7001")
    check("M1b: a reply to our own message is refused", run_close(db, GRP, "5290", "nem nekem: Balázsnak"), 2)
    check("M1: refused attempts wrote nothing", os.path.exists(lib._closed_file(AGENT)), False)
    check("M1b: ... and the guard still blocks it", run_hook(db)[0], "block")
    lib.log_inbound(AGENT, GRP, "5291", "Balázs, ezt nézd", "2026-11-11T14:02:00.000Z", reply_to_message_id="99")
    check("M1b control: a reply to someone else's message can be closed",
          run_close(db, GRP, "5291", "nem nekem: Patrik Balázsnak"), 0)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {FAILS}", file=sys.stderr)
        sys.exit(1)
    print("\nAll telegram-reply-guard tests passed.")


if __name__ == "__main__":
    main()
