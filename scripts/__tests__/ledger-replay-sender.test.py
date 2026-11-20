#!/usr/bin/env python3
"""SENDERNAME1120 (Klodel 48611, hibanapló 2026-11-20): the SessionStart replay labels an inbound turn with its REAL
sender, from the Telegram plugin's sender log, not with the owner's name by default.

Measured: the replay gave a team-group message of another member (TG 6674) to the fresh session as "the owner's last
message", and the agent asked that member for the owner's decision. Synthetic ids and names only: owner 111 (OWNER),
member 999 (Member), stranger 555.

Run: python3 <thisfile>   Exit 0 = all pass.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.join(os.path.dirname(HERE), "hooks")
REPLAY = os.path.join(HOOKS, "ledger-replay.py")
OWNER_ID, MEMBER_ID, STRANGER_ID, GROUP = "111", "999", "555", "-222"

failed = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        failed.append(name)
        if detail:
            print("       " + detail[:600])


def run(turns, senders=(), rotated=(), names=None, state=True, owner_id=OWNER_ID):
    """Seed a ledger with `turns` [(direction, chat, message_id, text)], write the sender log rows
    [(chat, message_id, user_id)] (and the rotated .1 rows), run the hook as the harness does, return its context."""
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = os.path.join(tmp, "tg")
        if state:
            os.makedirs(state_dir)
            for fname, rows in (("inbound-senders.jsonl", senders), ("inbound-senders.jsonl.1", rotated)):
                if rows:
                    with open(os.path.join(state_dir, fname), "w") as f:
                        for chat, mid, uid in rows:
                            f.write(json.dumps({"at": 1, "chat_id": chat, "message_id": mid, "user_id": uid}) + "\n")
                        f.write("not json\n")
        env = dict(os.environ, LEDGER_DB_PATH=os.path.join(tmp, "ledger.db"), MARVEEN_AGENT_ID="snd",
                   MAIN_AGENT_ID="snd", OWNER_NAME="OWNER", TELEGRAM_STATE_DIR=state_dir,
                   LEDGER_OWNER_USER_ID=owner_id, LEDGER_SENDER_NAMES=json.dumps(names or {}))
        seed = ("import sys, json; sys.path.insert(0, sys.argv[1]); import ledger_lib\n"
                "for i, (d, chat, mid, text) in enumerate(json.loads(sys.argv[2])):\n"
                "    ts = '2026-11-20T09:%02d:00Z' % i\n"
                "    if d == 'in': ledger_lib.log_inbound('snd', chat, mid, text, ts)\n"
                "    else: ledger_lib.log_outbound('snd', chat, text)\n"
                "    import time; time.sleep(0.01)\n")
        subprocess.run([sys.executable, "-c", seed, HOOKS, json.dumps(turns)], env=env, check=True, cwd=tmp)
        p = subprocess.run([sys.executable, REPLAY], input=json.dumps({"session_id": "x", "cwd": tmp}), env=env,
                           capture_output=True, text=True, timeout=30, cwd=tmp)
        if not p.stdout.strip():
            return ""
        return json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"]


# The case of the day: the member's group message is the open question.
ctx = run([("in", GROUP, "6670", "owner kérdez"), ("out", GROUP, None, "válasz"),
           ("in", GROUP, "6674", "member kérdez")],
          senders=[(GROUP, "6670", OWNER_ID), (GROUP, "6674", MEMBER_ID)], names={MEMBER_ID: "Member"})
check("the member's group message is labelled with the member's name", 'Member: "member kérdez"' in ctx, ctx)
check("NEGATIVE: the member's message is never the owner's", 'OWNER: "member kérdez"' not in ctx, ctx)
check("the open question names the member, not the owner", "Member utolsó üzenete" in ctx, ctx)
check("the open question does not name the owner", "OWNER utolsó üzenete" not in ctx, ctx)
check("the owner's own group message keeps the owner's name", 'OWNER: "owner kérdez"' in ctx, ctx)

# An unlisted sender: its id, never the owner.
ctx = run([("in", GROUP, "7001", "idegen")], senders=[(GROUP, "7001", STRANGER_ID)])
check("an unlisted sender is 'ismeretlen [<user_id>]'", 'ismeretlen [555]: "idegen"' in ctx, ctx)
check("an unlisted sender's open question names the id", "ismeretlen [555] utolsó üzenete" in ctx, ctx)

# A known chat, a message the log does not have (older than the log): unknown, not the owner.
ctx = run([("in", GROUP, "100", "régi")], senders=[(GROUP, "7001", OWNER_ID)])
check("a group message missing from the log is 'ismeretlen feladó'", 'ismeretlen feladó: "régi"' in ctx, ctx)

# The owner's private chat: only he writes there, even without a log row.
ctx = run([("in", OWNER_ID, "50", "privát")], senders=[(GROUP, "7001", MEMBER_ID)])
check("the owner's private chat without a log row keeps the owner", 'OWNER: "privát"' in ctx, ctx)

# The rotated log is read too.
ctx = run([("in", GROUP, "6000", "forgatott")], senders=[(GROUP, "7001", OWNER_ID)],
          rotated=[(GROUP, "6000", MEMBER_ID)], names={MEMBER_ID: "Member"})
check("a sender found only in inbound-senders.jsonl.1 is used", 'Member: "forgatott"' in ctx, ctx)

# No sender log at all (another provider, or none yet): the old label, the replay still works.
ctx = run([("in", "4242", "1", "nincs napló")], state=False)
check("no sender log: the old owner label", 'OWNER: "nincs napló"' in ctx, ctx)

# No owner id: a logged sender is never the owner.
ctx = run([("in", GROUP, "8001", "x")], senders=[(GROUP, "8001", OWNER_ID)], owner_id="")
check("no owner id: a logged sender is not given the owner's name", 'ismeretlen [111]: "x"' in ctx, ctx)

if failed:
    print(f"\n{len(failed)} FAILED")
    sys.exit(1)
print("\nAll ledger-replay sender tests passed.")
