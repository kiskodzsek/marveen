#!/usr/bin/env python3
"""EMAILKAPU901 PR2: the email_send level becomes a real switch on the main agent.

Branches proven (Marveen msgs 17900/17936):
  - level 1: the send is DENIED outright.
  - level 2: denied without approval; ALLOWED against an approved, matching,
    in-window approval; the SAME send a SECOND time is denied again (one-shot
    consumption -- the feature's built-in mutation control); an expired window
    denies; a pending approval denies with its id.
  - level 3: allowed.
  - four-field anchor: an approval for the SAME subject+body but a DIFFERENT
    recipient does NOT authorize the send.
  - FAIL-CLOSED, proven separately from the happy path: missing approvals DB,
    missing/corrupt autonomy-config, unreadable letter ($VAR body), and a
    recipient that cannot be extracted all DENY (exit 2, never 1).

Run: python3 <thisfile>   Exit 0 = all pass.
"""
import json
import os
import re
import hashlib
import importlib.util
import sqlite3
import subprocess
import sys
import tempfile
import threading
import tokenize
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.join(os.path.dirname(HERE), "hooks")
GATE = os.path.join(HOOKS, "email-approval-gate.py")
WINDOW = 1800
# Same portability constraint as the gate: this file drives the gate through
# the HOST's python3, so its own fixtures must not need SQLite 3.38 either.
NOW_S = "CAST(strftime('%s','now') AS INTEGER)"

failed = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if not ok and detail else ""))
    if not ok:
        failed.append(name)


def make_store(td, level=2, max_level=None, config="ok"):
    store = os.path.join(td, "store")
    os.makedirs(store, exist_ok=True)
    cfg_path = os.path.join(store, "autonomy-config.json")
    if config == "ok":
        cat = {"key": "email_send", "label": "Email", "level": level, "locked": False}
        if max_level is not None:
            cat["maxLevel"] = max_level
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "categories": [cat]}, fh)
    elif config == "corrupt":
        with open(cfg_path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
    # config == "missing": write nothing
    db_path = os.path.join(store, "claudeclaw.db")
    con = sqlite3.connect(db_path)
    con.execute("""
      CREATE TABLE approvals (
        id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, category TEXT NOT NULL,
        action_description TEXT NOT NULL, action_payload TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        timeout_at INTEGER, telegram_message_id INTEGER,
        requested_at INTEGER NOT NULL DEFAULT (CAST(strftime('%s','now') AS INTEGER)),
        resolved_at INTEGER, resolved_by TEXT,
        content_hash TEXT, consumed_at INTEGER)""")
    con.commit()
    con.close()
    return store


def write_standing(store, value):
    """value: a Python object dumped as JSON, or a raw string written verbatim
    (for the corrupt-file case)."""
    path = os.path.join(store, "email-standing-recipients.json")
    with open(path, "w", encoding="utf-8") as fh:
        if isinstance(value, str):
            fh.write(value)
        else:
            json.dump(value, fh)
    return path


def make_daily_log_stub(received):
    """A minimal /api/daily-log endpoint. Records (parsed body, Authorization)
    so the test can assert WHAT reached the owner's log, not merely that
    something did."""
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 -- BaseHTTPRequestHandler's contract
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n).decode("utf-8")
            try:
                body = json.loads(raw)
            except Exception:
                body = {"_unparseable": raw}
            received.append((body, self.headers.get("Authorization")))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, *a):  # keep the test output clean
            pass
    return Handler


def run_gate(store, payload, extra_env=None):
    env = dict(os.environ,
               EMAIL_APPROVAL_GATE_STORE=store,
               EMAIL_APPROVAL_WINDOW_S=str(WINDOW),
               OUTGOING_COPY_GATE_RULES=os.path.join(store, "no-rules.json"))
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run([sys.executable, GATE], input=json.dumps(payload).encode(),
                          capture_output=True, env=env)
    return proc.returncode, proc.stdout.decode(), proc.stderr.decode()


def mcp_send(to="a@b.hu", cc=None, subject="Teszt tárgy", body="Kedves Ügyfelünk! Törzs."):
    ti = {"to": [to], "subject": subject, "body": body}
    if cc:
        ti["cc"] = [cc]
    return {"tool_name": "mcp__server-gmail-autoauth-mcp__send_email", "tool_input": ti}


def approve(store, anchor, resolved_ago=0, status="approved", consumed=None):
    con = sqlite3.connect(os.path.join(store, "claudeclaw.db"))
    con.execute(
        "INSERT INTO approvals (id, agent_id, category, action_description, status,"
        " requested_at, resolved_at, resolved_by, content_hash, consumed_at)"
        " VALUES (hex(randomblob(6)), 'marveen', 'email_send', 'Email teszt', ?,"
        f" {NOW_S}-?-60, CASE WHEN ?='pending' THEN NULL ELSE {NOW_S}-? END,"
        " 'szabi', ?, ?)",
        (status, resolved_ago, status, resolved_ago, anchor, consumed))
    con.commit()
    con.close()


def activate_standing(store, addr, status="approved", resolved_ago=0):
    """Az elesites: egy MAR LEZART email_standing_recipient sor a cimre.
    A `resolved_ago` a sorrendhez kell (az utolso dontes nyer)."""
    anchor = hashlib.sha256(addr.strip().lower().encode("utf-8")).hexdigest()
    con = sqlite3.connect(os.path.join(store, "claudeclaw.db"))
    con.execute(
        "INSERT INTO approvals (id, agent_id, category, action_description, status,"
        " requested_at, resolved_at, resolved_by, content_hash, consumed_at)"
        " VALUES (hex(randomblob(6)), 'marveen', 'email_standing_recipient',"
        f" 'Allando cimzett elesitese', ?, {NOW_S}-?-60,"
        f" CASE WHEN ?='pending' THEN NULL ELSE {NOW_S}-? END, 'szabi', ?, NULL)",
        (status, resolved_ago, status, resolved_ago, anchor))
    con.commit()
    con.close()
    return anchor


def anchor_from_stderr(err):
    m = re.search(r"\b([0-9a-f]{64})\b", err)
    return m.group(1) if m else None


with tempfile.TemporaryDirectory() as td:
    # --- scope: what the gate must NOT touch --------------------------------
    store = make_store(os.path.join(td, "s0"), level=1)
    code, _, _ = run_gate(store, {"tool_name": "Bash", "tool_input": {"command": "ls -la"}})
    check("non-send Bash passes untouched even at level 1", code == 0, f"exit={code}")
    code, _, _ = run_gate(store, {"tool_name": "Read", "tool_input": {"file_path": "/x"}})
    check("non-email tool passes untouched", code == 0, f"exit={code}")

    # --- level 1: hard deny --------------------------------------------------
    code, _, err = run_gate(store, mcp_send())
    check("level 1: MCP send DENIED", code == 2 and "szint 1" in err, f"exit={code}")
    code, _, err = run_gate(store, {"tool_name": "mcp__x__manage_email",
                                    "tool_input": {"action": "send", "to": ["a@b.hu"], "body": "x"}})
    check("level 1: manage_email DENIED too (2026-08-10 bypass class)", code == 2, f"exit={code}")

    # --- level 3: allow ------------------------------------------------------
    store = make_store(os.path.join(td, "s3"), level=3)
    code, _, _ = run_gate(store, mcp_send())
    check("level 3: MCP send allowed", code == 0, f"exit={code}")

    # --- level 2: the approval loop -----------------------------------------
    store = make_store(os.path.join(td, "s2"), level=2)
    payload = mcp_send()
    code, _, err = run_gate(store, payload)
    anchor = anchor_from_stderr(err)
    check("level 2 without approval: DENIED and the deny carries the sha256 anchor",
          code == 2 and "NINCS jovahagyas" in err and anchor is not None, f"exit={code} err={err[:150]!r}")
    check("deny message is actionable (POST /api/approvals + resend instructions)",
          "api/approvals" in err and "content_hash" in err and "a@b.hu" in err)

    approve(store, anchor)
    code, out, _ = run_gate(store, payload)
    check("level 2 with approved+matching+in-window approval: ALLOWED",
          code == 0 and "felhasznalva" in out, f"exit={code} out={out[:120]!r}")

    con = sqlite3.connect(os.path.join(store, "claudeclaw.db"))
    consumed = con.execute("SELECT consumed_at FROM approvals WHERE content_hash=?", (anchor,)).fetchone()[0]
    con.close()
    check("the allow CONSUMED the approval (consumed_at set in the DB)", consumed is not None)

    code, _, err = run_gate(store, payload)
    check("the SAME send a SECOND time: DENIED (one-shot)",
          code == 2 and "FEL LETT HASZNALVA" in err, f"exit={code}")

    # window expiry: a different letter, approved too long ago
    payload_b = mcp_send(subject="Masik tárgy")
    _, _, err = run_gate(store, payload_b)
    anchor_b = anchor_from_stderr(err)
    approve(store, anchor_b, resolved_ago=WINDOW + 60)
    code, _, err = run_gate(store, payload_b)
    check("approval outside the time window: DENIED as expired",
          code == 2 and "IDOABLAKA lejart" in err, f"exit={code} err={err[:150]!r}")

    # pending approval names itself
    payload_c = mcp_send(subject="Harmadik tárgy")
    _, _, err = run_gate(store, payload_c)
    anchor_c = anchor_from_stderr(err)
    approve(store, anchor_c, status="pending")
    code, _, err = run_gate(store, payload_c)
    check("pending approval: DENIED with 'meg fuggoben'",
          code == 2 and "FUGGOBEN" in err, f"exit={code}")

    # --- the four-field anchor: recipient is part of the identity ------------
    payload_d = mcp_send(subject="Negyedik tárgy", body="Ugyanaz a törzs.")
    _, _, err = run_gate(store, payload_d)
    approve(store, anchor_from_stderr(err))
    hijacked = mcp_send(to="evil@x.hu", subject="Negyedik tárgy", body="Ugyanaz a törzs.")
    code, _, err = run_gate(store, hijacked)
    check("approved subject+body to a DIFFERENT recipient: DENIED (anchor covers to)",
          code == 2 and "NINCS jovahagyas" in err, f"exit={code}")
    cc_flip = mcp_send(cc="cc@x.hu", subject="Negyedik tárgy", body="Ugyanaz a törzs.")
    code, _, _ = run_gate(store, cc_flip)
    check("same letter with an ADDED cc: DENIED (anchor covers cc)", code == 2)

    # --- maxLevel clamps -----------------------------------------------------
    store = make_store(os.path.join(td, "sclamp"), level=3, max_level=2)
    code, _, err = run_gate(store, mcp_send())
    check("level 3 clamped by maxLevel 2: behaves as level 2 (deny w/o approval)",
          code == 2 and "level 2" in err, f"exit={code}")

    # --- Bash path end-to-end at level 2 ------------------------------------
    store = make_store(os.path.join(td, "sbash"), level=2)
    bash_payload = {"tool_name": "Bash", "tool_input": {
        "command": 'sendmail --to a@b.hu --subject "Bash tárgy" --body "Bash törzs."'}}
    code, _, err = run_gate(store, bash_payload)
    b_anchor = anchor_from_stderr(err)
    check("level 2 Bash send without approval: DENIED with anchor",
          code == 2 and b_anchor is not None, f"exit={code} err={err[:150]!r}")
    approve(store, b_anchor)
    code, _, _ = run_gate(store, bash_payload)
    check("level 2 Bash send with approval: ALLOWED", code == 0, f"exit={code}")

    # --- FAIL-CLOSED, each branch separately --------------------------------
    store = make_store(os.path.join(td, "sf1"), level=2)
    os.remove(os.path.join(store, "claudeclaw.db"))
    code, _, err = run_gate(store, mcp_send())
    check("fail-closed: approvals DB missing -> DENIED (undecidable != allowed)",
          code == 2 and "nem-eldontheto" in err, f"exit={code}")

    store = make_store(os.path.join(td, "sf2"), config="missing")
    code, _, err = run_gate(store, mcp_send())
    check("fail-closed: autonomy-config missing -> level 2 path, DENIED w/o approval",
          code == 2 and "fail-closed" in err, f"exit={code}")

    store = make_store(os.path.join(td, "sf3"), config="corrupt")
    code, _, err = run_gate(store, mcp_send())
    check("fail-closed: autonomy-config corrupt -> level 2 path, DENIED",
          code == 2, f"exit={code}")

    store = make_store(os.path.join(td, "sf4"), level=2)
    code, _, err = run_gate(store, {"tool_name": "Bash", "tool_input": {
        "command": 'sendmail --to a@b.hu --body "$LETTER"'}})
    check("fail-closed: $VAR body at level 2 -> DENIED as unanchorable",
          code == 2 and "horgonyozhato" in err, f"exit={code}")

    code, _, err = run_gate(store, {"tool_name": "mcp__x__send_email",
                                    "tool_input": {"subject": "t", "body": "b"}})
    check("fail-closed: no extractable recipient -> DENIED",
          code == 2 and "cimzett" in err, f"exit={code}")

    code, _, err = run_gate(store, {"tool_name": "mcp__x__send_email", "tool_input": "not-a-dict"})
    check("fail-closed: non-dict tool_input -> DENIED (exit 2, never 1)",
          code == 2, f"exit={code}")

    # Marveen's #1149 review: this gate AUTHORIZES, so unlike the copy gate it
    # must fail closed on an unparseable payload too -- the docstring and the
    # code now state the same contract.
    env = dict(os.environ, EMAIL_APPROVAL_GATE_STORE=store,
               OUTGOING_COPY_GATE_RULES=os.path.join(store, "no-rules.json"))
    proc = subprocess.run([sys.executable, GATE], input=b"this is not json",
                          capture_output=True, env=env)
    check("fail-closed: unparseable stdin -> DENIED (exit 2, never 0/1)",
          proc.returncode == 2, f"exit={proc.returncode}")

    # --- EMAILBCCHORGONY903: bcc is part of the anchor -----------------------
    # The gap this pins closed: with a to+cc+text anchor, an approved letter
    # could be re-sent with an ADDED bcc -- identical hash, the approval was
    # consumed, and a recipient nobody approved got the letter. Both send
    # paths are covered, plus the backward-compat golden below.
    store = make_store(os.path.join(td, "bcc-mcp"))
    _, _, err = run_gate(store, mcp_send())          # harvest the letter's anchor
    bccless_anchor = anchor_from_stderr(err)
    approve(store, bccless_anchor)
    bcc_payload = mcp_send()
    bcc_payload["tool_input"]["bcc"] = ["rejtett@idegen.example"]
    code, _, _ = run_gate(store, bcc_payload)
    check("bcc/MCP: approved bcc-less letter re-sent WITH bcc -> DENIED",
          code == 2, f"exit={code}")
    code, _, _ = run_gate(store, mcp_send())
    check("bcc/MCP: the bcc-less letter itself still sends on that approval",
          code == 0, f"exit={code}")

    store = make_store(os.path.join(td, "bcc-bash"))
    bash_cmd = ('python3 scripts/send.py --to "a@b.hu" --subject "Teszt tárgy" '
                '--body "Kedves Ügyfelünk! Törzs."')
    _, _, err = run_gate(store, {"tool_name": "Bash", "tool_input": {"command": bash_cmd}})
    approve(store, anchor_from_stderr(err))
    code, _, _ = run_gate(store, {"tool_name": "Bash",
                                  "tool_input": {"command": bash_cmd + ' --bcc "rejtett@idegen.example"'}})
    check("bcc/Bash: approved bcc-less command re-sent WITH --bcc -> DENIED",
          code == 2, f"exit={code}")
    code, _, _ = run_gate(store, {"tool_name": "Bash", "tool_input": {"command": bash_cmd}})
    check("bcc/Bash: the bcc-less command itself still sends on that approval",
          code == 0, f"exit={code}")

    # Backward-compat golden: the bcc-less canon is BYTE-STABLE across the bcc
    # fix (bcc joins the hash ONLY when non-empty), so approvals recorded
    # before the change stay valid for the letters they approved. If this hash
    # ever changes, EVERY open approval silently invalidates -- that must be a
    # loud, deliberate decision failing here, never a side effect.
    check("bcc/golden: bcc-less anchor is byte-stable across the bcc fix",
          bccless_anchor == "de87bdb699dcab419b68811bb57b6fab44b34e2fe16bff11cf90b2a5848f82ec",
          f"got {bccless_anchor}")

    # MANAGEOP904: manage_email is a MULTIPLEXER, not a send tool. Scoping the
    # gate on the tool NAME alone denied `operation=search` and
    # `operation=draft` at level 1 -- measured on a live install 2026-09-04,
    # where the draft-only workflow needs exactly those two. The level exists to
    # stop the SEND, so reading and drafting must pass and sending must not.
    store1 = make_store(td, level=1)

    def manage(op=None, **extra):
        ti = {"to": ["a@b.hu"], "subject": "T", "body": "Torzs."}
        if op is not None:
            ti["operation"] = op
        ti.update(extra)
        return {"tool_name": "mcp__google-workspace__manage_email", "tool_input": ti}

    for op in ("search", "read", "draft", "label", "list", "archive"):
        code, _, _ = run_gate(store1, manage(op))
        check(f"manage_email operation={op} passes at level 1 (not a send)", code == 0,
              f"exit={code}")
    for op in ("send", "reply", "reply_all", "replyAll", "forward", "SEND"):
        code, _, _ = run_gate(store1, manage(op))
        check(f"manage_email operation={op} is DENIED at level 1 (it is a send)",
              code == 2, f"exit={code}")
    # Fail-closed on doubt: no operation, or one we cannot read, counts as send.
    code, _, _ = run_gate(store1, manage(None))
    check("manage_email without an operation is DENIED (fail-closed)", code == 2,
          f"exit={code}")
    code, _, _ = run_gate(store1, {"tool_name": "mcp__google-workspace__manage_email",
                                   "tool_input": {"operation": 42}})
    check("manage_email with a non-string operation is DENIED (fail-closed)", code == 2,
          f"exit={code}")
    # MANAGEDRAFT905: a send OPERATION carrying an explicit draft:true is a
    # DRAFT, not a send -- `{"operation":"reply","draft":true}` is the only way
    # to write a threaded draft with this tool, and the sibling gate
    # (email-send-gate.mjs) lets exactly that shape through. Without this the
    # draft-only workflow was blocked at level 1 by its own guard.
    for op in ("send", "reply", "reply_all", "replyAll", "forward"):
        for flag in (True, "true"):
            code, _, _ = run_gate(store1, manage(op, draft=flag))
            check(f"manage_email operation={op} draft={flag!r} passes at level 1 (a draft is not a send)",
                  code == 0, f"exit={code}")
    # Fail-closed stays: anything but an explicit true is still a send.
    for flag in (False, "false", "yes", 1, None, "", "True "):
        code, _, _ = run_gate(store1, manage("reply", draft=flag))
        check(f"manage_email operation=reply draft={flag!r} is DENIED (not an explicit draft)",
              code == 2, f"exit={code}")
    # Control: the draft exemption is scoped to the multiplexer, not to the
    # dedicated send tool -- a draft flag must not buy send_email a pass.
    code, _, _ = run_gate(store1, {"tool_name": "mcp__x__send_email",
                                   "tool_input": {"to": ["a@b.hu"], "subject": "T",
                                                  "body": "Torzs.", "draft": True}})
    check("control: send_email with draft:true is still DENIED at level 1", code == 2,
          f"exit={code}")

    # Control: send_email has no operations and must stay gated unconditionally,
    # otherwise the scoping above could quietly exempt the real send tool too.
    code, _, _ = run_gate(store1, mcp_send())
    check("control: send_email is still DENIED at level 1", code == 2, f"exit={code}")
    # Control: the scoping is about the OPERATION, not about level 1 letting
    # things through -- at level 3 the same send passes, which proves the deny
    # above came from the level and not from a broken payload.
    cfg1 = os.path.join(store1, "autonomy-config.json")
    with open(cfg1, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "categories": [
            {"key": "email_send", "label": "Email", "level": 3, "locked": False}]}, fh)
    code, _, _ = run_gate(store1, manage("send"))
    check("control: manage_email operation=send passes at level 3", code == 0,
          f"exit={code}")

    # --- GMAILCONNECTOR914: the claude.ai Gmail connector -------------------
    # No send_email, no manage_email in the name: the gate exited 0 on every
    # connector send, so an unapproved send_message was never denied.
    def connector(tool, **ti):
        return {"tool_name": f"mcp__claude_ai_Gmail__{tool}", "tool_input": ti}
    store_l1 = make_store(os.path.join(td, "sconn1"), level=1)  # store1 was raised to level 3 above
    code, _, err = run_gate(store_l1, connector("send_message", to=["a@b.hu"], subject="T", body="x"))
    check("connector send_message is DENIED at level 1", code == 2 and "szint 1" in err, f"exit={code}")
    code, _, _ = run_gate(store_l1, connector("search_threads", q="x"))
    check("connector search_threads is a read: passes at level 1", code == 0, f"exit={code}")
    code, _, _ = run_gate(store_l1, connector("create_draft", to=["a@b.hu"], body="x"))
    check("connector create_draft is not a send: passes at level 1", code == 0, f"exit={code}")
    store_c = make_store(os.path.join(td, "sconn"), level=2)
    payload = connector("reply", messageId="msg-42", body="Kedves Ügyfelünk! Válasz.")
    code, _, err = run_gate(store_c, payload)
    anchor = anchor_from_stderr(err)
    check("connector reply at level 2 without approval: DENIED, anchored on messageId (no `to` field)",
          code == 2 and anchor is not None and "messageId:msg-42" in err, f"exit={code} err={err[:200]!r}")
    approve(store_c, anchor)
    code, out, _ = run_gate(store_c, payload)
    check("connector reply with a matching approval: ALLOWED", code == 0 and "felhasznalva" in out,
          f"exit={code} out={out[:120]!r}")
    code, _, err = run_gate(store_c, connector("reply", messageId="msg-43", body="Kedves Ügyfelünk! Válasz."))
    check("the same approval does not cover a reply to ANOTHER message", code == 2, f"exit={code}")

    # --- EMAILALLANDOCIMZETT926: allando cimzett-lista, CSAK level 2-n --------
    # A funkcio egyetlen dolga, hogy EGY cimre jovahagyas nelkul lehessen kuldeni,
    # ugy, hogy minden mas cimzett a regi uton maradjon. Ezert minden teszt parban
    # all: ami atmegy a listas cimre, annak TILOS lennie egy masikra.
    store = make_store(os.path.join(td, "sl1"), level=2)
    write_standing(store, {"recipients": ["dani@pelda.hu"]})
    activate_standing(store, "dani@pelda.hu")
    code, out, err = run_gate(store, mcp_send(to="dani@pelda.hu"))
    check("standing: a listan levo cimre level 2-n jovahagyas NELKUL mehet",
          code == 0 and "allando cimzett" in out, f"exit={code} out={out[:120]!r}")
    code, _, err = run_gate(store, mcp_send(to="idegen@pelda.hu"))
    check("standing: a listan NEM szereplo cimre tovabbra is jovahagyas kell",
          code == 2 and "NINCS jovahagyas" in err, f"exit={code}")

    # A ketto egyutt a lenyeg: a lista NEM a level helyettesitoje.
    store1 = make_store(os.path.join(td, "sl2"), level=1)
    write_standing(store1, {"recipients": ["dani@pelda.hu"]})
    activate_standing(store1, "dani@pelda.hu")   # TELJESEN eles cim -- a level 1 igy is tilt
    code, _, err = run_gate(store1, mcp_send(to="dani@pelda.hu"))
    check("standing: level 1 HARD DENY marad, a lista nem nyit hatso ajtot",
          code == 2 and "szint 1" in err, f"exit={code} err={err[:120]!r}")

    # cc/bcc: a lista egy cimzettre szol, nem egy levelre
    code, _, err = run_gate(store, mcp_send(to="dani@pelda.hu", cc="idegen@pelda.hu"))
    check("standing: cc-vel NEM mehet at (a lista egy cimzettre szol)",
          code == 2, f"exit={code}")
    payload = mcp_send(to="dani@pelda.hu")
    payload["tool_input"]["bcc"] = ["idegen@pelda.hu"]
    code, _, err = run_gate(store, payload)
    check("standing: bcc-vel sem mehet at", code == 2, f"exit={code}")

    # A kritikus el: az extractor NEM bontja a cimzettet, egy string tobb cimet vihet.
    code, _, err = run_gate(store, mcp_send(to="dani@pelda.hu, idegen@pelda.hu"))
    check("standing: vesszovel osszefuzott ket cim EGY to-mezoben sem megy at",
          code == 2, f"exit={code}")
    code, out, _ = run_gate(store, mcp_send(to="Nemeth Daniel <dani@pelda.hu>"))
    check("standing: a 'Nev <cim>' alak felismerese (ugyanaz a cim)",
          code == 0 and "allando cimzett" in out, f"exit={code}")
    code, out, _ = run_gate(store, mcp_send(to="DANI@Pelda.HU"))
    check("standing: a cim-egyezes kis-nagybetu fuggetlen",
          code == 0, f"exit={code}")

    # fail-closed: romlott lista nem ad jogot, DE lathatova teszi magat
    store2 = make_store(os.path.join(td, "sl3"), level=2)
    write_standing(store2, "{not json")
    code, _, err = run_gate(store2, mcp_send(to="dani@pelda.hu"))
    check("standing: romlott lista -> nincs jog (fail-closed), es a deny MEGMONDJA",
          code == 2 and "nem olvashato" in err, f"exit={code} err={err[:160]!r}")
    write_standing(store2, {"recipients": "dani@pelda.hu"})
    code, _, err = run_gate(store2, mcp_send(to="dani@pelda.hu"))
    check("standing: rossz alaku lista (string lista helyett) -> nincs jog, es lathato",
          code == 2 and "alakja nem lista" in err, f"exit={code}")

    # hianyzo fajl = a normal allapot, nem hiba: csendben a regi ut. "Extra zaj"
    # = a lista HIBA-jegyzete (romlott/rossz alaku); annak nincs mit jeleznie,
    # ha a fajl egyszeruen nincs.
    store3 = make_store(os.path.join(td, "sl4"), level=2)
    code, _, err = run_gate(store3, mcp_send(to="dani@pelda.hu"))
    check("standing: lista-fajl nelkul minden marad a regiben, extra zaj nelkul",
          code == 2 and "NINCS jovahagyas" in err
          and "nem olvashato" not in err and "alakja nem lista" not in err,
          f"exit={code}")

    # --- BIRALOI KERES 1: a deny NE tanitsa meg a kiskaput -------------------
    # A tiltas korabban SZO SZERINT leirta, hogy a cim felvehetó a
    # email-standing-recipients.json fajlba, es onnantol jovahagyas nelkul mehet
    # ra level. Csakhogy azt a fajlt AZ AGENS IS irja: a store/ ala ir nap mint
    # nap. Vagyis a kapu sajat tiltasa volt a megkerules hasznalati utmutatoja.
    # A jogot tovabbra is a gazda adja, de az UTAT a tiltas nem mondja meg.
    code, _, err = run_gate(store3, mcp_send(to="dani@pelda.hu"))
    check("keres1: a deny NEM nevezi meg a lista-fajlt",
          "email-standing-recipients" not in err and ".json" not in err,
          f"err={err[-400:]!r}")
    check("keres1: a deny a GAZDAHOZ kuldi az agenst, nem a fajlhoz",
          "KERD TOLE" in err and "MAGAD NE vegezd el" in err,
          f"err={err[-400:]!r}")
    # Kontroll: a regi, tanito mondat tenylegesen eltunt -- kulonben a ket
    # fenti allitas akkor is zold lenne, ha csak a fajlnevet vettem volna ki.
    check("keres1 kontroll: a 'felveheti a cimet ... fajlba' mondat nincs tobbe",
          "felveheti a cimet" not in err, f"err={err[-400:]!r}")

    # --- BIRALOI KERES 2: a jovahagyas nelkuli kuldes hagyjon nyomot ---------
    # Ez az EGYETLEN ut, amin emberi dontes nelkul megy ki level, ezert a nyom
    # nem mellektermek, hanem a jog feltetele.
    store4 = make_store(os.path.join(td, "sl5"), level=2)
    write_standing(store4, {"recipients": ["dani@pelda.hu"]})
    activate_standing(store4, "dani@pelda.hu")
    log_path = os.path.join(store4, "email-standing-sends.log")
    code, out, _ = run_gate(store4, mcp_send(to="dani@pelda.hu", subject="Napi jelentes"))
    log_text = open(log_path, encoding="utf-8").read() if os.path.exists(log_path) else ""
    check("keres2: a listas kuldes sort ir a helyi naploba",
          code == 0 and "dani@pelda.hu" in log_text, f"exit={code} log={log_text!r}")
    check("keres2: a naplosor idobelyeges (offsettel, nem UTC)",
          re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4} ", log_text or "x") is not None,
          f"log={log_text[:80]!r}")
    check("keres2: a naplosor megmondja, hogy a gazdat NEM sikerult ertesiteni",
          "NEM MENT KI" in log_text, f"log={log_text!r}")
    check("keres2: a systemMessage sem allitja, hogy a gazda latta",
          "NEM sikerult ertesiteni" in out, f"out={out[:300]!r}")

    # A ket kuldes ket sor: a naplo append-only, nem felulir.
    run_gate(store4, mcp_send(to="dani@pelda.hu", subject="Masodik"))
    after = open(log_path, encoding="utf-8").read() if os.path.exists(log_path) else ""
    check("keres2: a naplo append-only (ket kuldes = ket sor)",
          len([l for l in after.splitlines() if l.strip()]) == 2, f"log={after!r}")

    # Es a kritikus el: ha a nyom NEM irhato, a jog sem all.
    store5 = make_store(os.path.join(td, "sl6"), level=2)
    write_standing(store5, {"recipients": ["dani@pelda.hu"]})
    activate_standing(store5, "dani@pelda.hu")
    blocked_log = os.path.join(store5, "email-standing-sends.log")
    os.mkdir(blocked_log)  # egy KONYVTAR ugyanazon a neven -> az append OSError
    code, _, err = run_gate(store5, mcp_send(to="dani@pelda.hu"))
    check("keres2: rogzithetetlen kuldes -> fail-closed TILTVA, nem csendes atengedes",
          code == 2 and "nem rogzitheto" in err, f"exit={code} err={err[:300]!r}")

    # A gazda-ertesites ELMEGY, ha a dashboard el: stub szerver a napi naplora.
    store6 = make_store(os.path.join(td, "sl7"), level=2)
    write_standing(store6, {"recipients": ["dani@pelda.hu"]})
    activate_standing(store6, "dani@pelda.hu")
    with open(os.path.join(store6, ".dashboard-token"), "w", encoding="utf-8") as fh:
        fh.write("teszt-token")
    received = []
    srv = HTTPServer(("127.0.0.1", 0), make_daily_log_stub(received))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        code, out, _ = run_gate(store6, mcp_send(to="dani@pelda.hu", subject="Elo dashboard"),
                                extra_env={"WEB_PORT": str(srv.server_port),
                                           "MAIN_AGENT_ID": "teszt-agens"})
    finally:
        srv.shutdown()
    check("keres2: elo dashboardnal a kuldes a GAZDA napi naplojaba kerul",
          code == 0 and len(received) == 1, f"exit={code} received={len(received)}")
    if received:
        body, auth = received[0]
        check("keres2: a napi naplo bejegyzes a fo agens neveben, Bearer tokennel megy",
              body.get("agent_id") == "teszt-agens" and auth == "Bearer teszt-token",
              f"body={body!r} auth={auth!r}")
        check("keres2: a bejegyzes megnevezi a cimzettet es hogy jovahagyas NELKUL ment",
              "dani@pelda.hu" in body.get("content", "")
              and "JOVAHAGYAS NELKUL" in body.get("content", ""),
              f"content={body.get('content')!r}")
    check("keres2: es ilyenkor a systemMessage sem beszel elmaradt ertesitesrol",
          "NEM sikerult" not in out, f"out={out[:300]!r}")

    # --- BIRALOI KERES 3: a felveteltol meg nem eles a cim -----------------
    # A lelke: a lista JAVASLAT, az elesites DONTES. Aki a fajlt irja, attol meg
    # nem adhatja meg maganak a jogot. Ezert minden eset PARBAN all: ami atmegy
    # az eles cimre, annak TILOS lennie ugyanarra a cimre elesites nelkul.
    store7 = make_store(os.path.join(td, "sl8"), level=2)
    write_standing(store7, {"recipients": ["dani@pelda.hu"]})
    code, _, err = run_gate(store7, mcp_send(to="dani@pelda.hu"))
    check("keres3: listan van, de NINCS elesitve -> nem megy at",
          code == 2 and "NINCS ELESITVE" in err, f"exit={code} err={err[:200]!r}")
    check("keres3: a deny kimondja, hogy a felvetel nem elesites",
          "A felvetel javaslat, az elesites dontes" in err, f"err={err[:400]!r}")
    check("keres3: a deny a GAZDA dontesehez kuldi, es tiltja az onjovahagyast",
          "A dontes a gazdae" in err and "NE hagyd jova" in err, f"err={err[:400]!r}")
    check("keres3: a deny megadja a cim-horgonyt, hogy az elesites KERHETO legyen",
          "email_standing_recipient" in err and anchor_from_stderr(err) is not None,
          f"err={err[:400]!r}")
    # ugyanaz a store, ugyanaz a cim, EGYETLEN kulonbseg: a gazda dontese
    activate_standing(store7, "dani@pelda.hu")
    code, out, _ = run_gate(store7, mcp_send(to="dani@pelda.hu"))
    check("keres3: elesites UTAN ugyanaz a level atmegy",
          code == 0 and "allando cimzett" in out, f"exit={code} out={out[:150]!r}")

    # A horgony a NORMALIZALT cimre szol: egy elesites fedi az alakvaltozatokat.
    code, out, _ = run_gate(store7, mcp_send(to="Nemeth Daniel <DANI@Pelda.HU>"))
    check("keres3: egy elesites fedi a 'Nev <CIM>' es a kis-nagybetus alakot is",
          code == 0, f"exit={code}")

    # Az elesites NEM egyszer-hasznalatos es NEM jar le -- kulonben csak egy
    # level-enkenti jovahagyas lenne mas neven.
    code2, _, _ = run_gate(store7, mcp_send(to="dani@pelda.hu", subject="Masodik level"))
    check("keres3: az elesites NEM fogy el (masodik kuldes is atmegy)",
          code2 == 0, f"exit={code2}")
    store8 = make_store(os.path.join(td, "sl9"), level=2)
    write_standing(store8, {"recipients": ["dani@pelda.hu"]})
    activate_standing(store8, "dani@pelda.hu", resolved_ago=100000)  # >> WINDOW
    code, _, _ = run_gate(store8, mcp_send(to="dani@pelda.hu"))
    check("keres3: az elesites NEM jar le a level-ablakkal",
          code == 0, f"exit={code}")

    # Fuggoben levo keres MEG NEM jog.
    store9 = make_store(os.path.join(td, "sl10"), level=2)
    write_standing(store9, {"recipients": ["dani@pelda.hu"]})
    activate_standing(store9, "dani@pelda.hu", status="pending")
    code, _, err = run_gate(store9, mcp_send(to="dani@pelda.hu"))
    check("keres3: FUGGOBEN levo elesites meg nem jog, es a deny ezt mondja",
          code == 2 and "FUGGOBEN" in err, f"exit={code} err={err[:200]!r}")

    # Visszavonas: a gazda UTOLSO dontese nyer, a fajl erintese nelkul.
    store10 = make_store(os.path.join(td, "sl11"), level=2)
    write_standing(store10, {"recipients": ["dani@pelda.hu"]})
    activate_standing(store10, "dani@pelda.hu", status="approved", resolved_ago=600)
    code, _, _ = run_gate(store10, mcp_send(to="dani@pelda.hu"))
    check("keres3 kontroll: a regebbi jovahagyas onmagaban meg jog",
          code == 0, f"exit={code}")
    activate_standing(store10, "dani@pelda.hu", status="rejected", resolved_ago=0)
    code, _, err = run_gate(store10, mcp_send(to="dani@pelda.hu"))
    check("keres3: kesobbi elutasitas VISSZAVONJA a jogot (a fajl valtozatlan)",
          code == 2 and "rejected" in err, f"exit={code} err={err[:200]!r}")

    # Es forditva, hogy ne csak a 'barmi rossz sor tilt' legyen igaz.
    store11 = make_store(os.path.join(td, "sl12"), level=2)
    write_standing(store11, {"recipients": ["dani@pelda.hu"]})
    activate_standing(store11, "dani@pelda.hu", status="rejected", resolved_ago=600)
    activate_standing(store11, "dani@pelda.hu", status="approved", resolved_ago=0)
    code, _, _ = run_gate(store11, mcp_send(to="dani@pelda.hu"))
    check("keres3: ujboli jovahagyas UTAN megint jog (az utolso dontes nyer)",
          code == 0, f"exit={code}")

    # Egy MASIK cim elesitese nem elesiti ezt.
    store12 = make_store(os.path.join(td, "sl13"), level=2)
    write_standing(store12, {"recipients": ["dani@pelda.hu", "masik@pelda.hu"]})
    activate_standing(store12, "masik@pelda.hu")
    code, _, err = run_gate(store12, mcp_send(to="dani@pelda.hu"))
    check("keres3: MAS cim elesitese nem elesiti ezt a cimet",
          code == 2 and "NINCS ELESITVE" in err, f"exit={code}")
    code, _, _ = run_gate(store12, mcp_send(to="masik@pelda.hu"))
    check("keres3 kontroll: az elesitett masik cim ugyanabban a store-ban atmegy",
          code == 0, f"exit={code}")

    # Fail-closed: ha az elesites nem ellenorizheto, a jog sem all.
    store13 = make_store(os.path.join(td, "sl14"), level=2)
    write_standing(store13, {"recipients": ["dani@pelda.hu"]})
    activate_standing(store13, "dani@pelda.hu")
    os.remove(os.path.join(store13, "claudeclaw.db"))
    code, _, err = run_gate(store13, mcp_send(to="dani@pelda.hu"))
    check("keres3: ellenorizhetetlen elesites -> fail-closed TILTVA",
          code == 2 and "elesitese nem ellenorizheto" in err, f"exit={code} err={err[:200]!r}")

    # kontroll: a matcher tud is talalni -- kulonben a fenti tiltasok
    # akkor is atmennenek, ha a funkcio egyaltalan nem letezne
    code, out, _ = run_gate(store, mcp_send(to="dani@pelda.hu"))
    check("kontroll: a pozitiv ag ugyanabban a store-ban tovabbra is atmegy",
          code == 0, f"exit={code}")

    # --- MS365SEND1014: the ms365 send-mail tool (Viktor F2-F4) -------------
    # The softeria server takes a Graph message under body.Message, and its
    # schema is passthrough: every case below that adds a field must DENY.
    NO_DASH = {"WEB_PORT": "1"}  # never reach a real dashboard from a test

    def ms365(to=("a@b.hu",), cc=(), bcc=(), subject="Teszt tárgy",
              body="Kedves Ügyfelünk! Törzs.", save=True, msg_extra=None,
              top_extra=None, tool="mcp__ms365__send-mail"):
        def rcp(xs):
            return [{"emailAddress": {"address": x}} for x in xs]
        msg = {"subject": subject, "body": {"contentType": "text", "content": body},
               "toRecipients": rcp(to)}
        if cc:
            msg["ccRecipients"] = rcp(cc)
        if bcc:
            msg["bccRecipients"] = rcp(bcc)
        msg.update(msg_extra or {})
        b = {"Message": msg}
        if save is not None:
            b["SaveToSentItems"] = save
        ti = {"body": b}
        ti.update(top_extra or {})
        return {"tool_name": tool, "tool_input": ti}

    store = make_store(os.path.join(td, "ms1"), level=2)
    code, _, err = run_gate(store, ms365())
    anchor = anchor_from_stderr(err)
    check("ms365: send-mail without approval is DENIED at level 2",
          code == 2 and "NINCS jovahagyas" in err and anchor, f"exit={code} err={err[:160]!r}")
    approve(store, anchor)
    code, out, _ = run_gate(store, ms365())
    check("ms365: the approved, byte-identical send-mail is ALLOWED",
          code == 0 and "felhasznalva" in out, f"exit={code}")
    code, _, err = run_gate(store, ms365())
    check("ms365: the same send a second time is DENIED (one-shot)",
          code == 2 and "MAR FEL LETT HASZNALVA" in err, f"exit={code}")
    for name, payload in (
            ("a different recipient", ms365(to=("masik@b.hu",))),
            ("an added bcc", ms365(bcc=("rejtett@b.hu",))),
            ("an added cc", ms365(cc=("masolat@b.hu",))),
            ("a changed subject", ms365(subject="Masik targy")),
            ("a changed body", ms365(body="Kedves Ügyfelünk! Másik törzs."))):
        approve(store, anchor)
        code, _, err = run_gate(store, payload)
        check(f"ms365: an approval does NOT authorize {name}",
              code == 2 and "NINCS jovahagyas" in err, f"exit={code} err={err[:160]!r}")
    for name, payload in (
            ("an attachment", ms365(msg_extra={"attachments": [{"name": "x.pdf"}]})),
            ("a replyTo", ms365(msg_extra={"replyTo": [{"emailAddress": {"address": "x@y.hu"}}]})),
            ("a from", ms365(msg_extra={"from": {"emailAddress": {"address": "x@y.hu"}}})),
            ("custom headers", ms365(msg_extra={"internetMessageHeaders": [{"name": "X-A", "value": "1"}]})),
            ("a top-level Message merged by the server", ms365(top_extra={"Message": {"bccRecipients": []}})),
            ("a top-level account switch", ms365(top_extra={"account": "masik@b.hu"})),
            ("SaveToSentItems missing", ms365(save=None)),
            ("SaveToSentItems false", ms365(save=False)),
            ("a recipient with an extra field", ms365(msg_extra={"toRecipients": [
                {"emailAddress": {"address": "a@b.hu", "x": 1}}]})),
            ("an unknown contentType", ms365(msg_extra={"body": {"contentType": "mime", "content": "x"}}))):
        code, _, err = run_gate(store, payload)
        check(f"ms365: {name} is unreadable -> DENIED",
              code == 2 and "nem horgonyozhato" in err, f"exit={code} err={err[:160]!r}")
    for tool in ("mcp__ms365__send-draft-message", "mcp__ms365__reply-mail-message",
                 "mcp__ms365__reply-all-mail-message", "mcp__ms365__forward-mail-message",
                 "mcp__ms365__send-shared-mailbox-mail"):
        code, _, err = run_gate(store, {"tool_name": tool,
                                        "tool_input": {"message-id": "AAMk1", "body": {"Comment": "ok"}}})
        check(f"ms365: {tool.split('__')[-1]} (id-addressed) is DENIED at level 2",
              code == 2 and "uzenet-azonositoval" in err, f"exit={code} err={err[:160]!r}")
    code, _, _ = run_gate(make_store(os.path.join(td, "ms3"), level=3),
                          {"tool_name": "mcp__ms365__forward-mail-message", "tool_input": {}})
    check("ms365: level 3 stays autonomous for the id-addressed tools too", code == 0, f"exit={code}")
    code, _, err = run_gate(make_store(os.path.join(td, "ms4"), level=1), ms365())
    check("ms365: level 1 is a hard deny", code == 2 and "szint 1" in err, f"exit={code}")
    store_l1 = make_store(os.path.join(td, "ms5"), level=1)
    for tool in ("mcp__ms365__create-reply-draft", "mcp__ms365__create-draft-email",
                 "mcp__ms365__list-mail-messages"):
        code, _, _ = run_gate(store_l1, {"tool_name": tool, "tool_input": {"message-id": "AAMk1"}})
        check(f"ms365: {tool.split('__')[-1]} (no send) passes even at level 1", code == 0, f"exit={code}")

    # --- MS365GATE1015 (Viktor G1): allowlist, not a blocklist --------------
    # Every outbound operation of the 0.162.0 server, and every ms365 tool off
    # the read/draft list, is denied below level 3 -- not only the six names the
    # first version knew.
    store = make_store(os.path.join(td, "g1"), level=2)
    for tool in ("reply-shared-mailbox-mail", "reply-all-shared-mailbox-mail",
                 "forward-shared-mailbox-mail", "send-shared-mailbox-draft", "graph-batch",
                 "create-mail-rule", "update-mail-rule", "update-mailbox-settings",
                 "create-calendar-event", "update-specific-calendar-event",
                 "forward-calendar-event", "send-chat-message", "share-drive-item",
                 "create-subscription"):
        code, _, err = run_gate(store, {"tool_name": f"mcp__ms365__{tool}", "tool_input": {}})
        check(f"G1: ms365 {tool} (outbound) is DENIED at level 2",
              code == 2 and "kifele visz" in err, f"exit={code} err={err[:160]!r}")
    for tool in ("get-me", "list-calendar-events", "delete-mail-message", "some-future-tool"):
        code, _, err = run_gate(store, {"tool_name": f"mcp__ms365__{tool}", "tool_input": {}})
        check(f"G1: ms365 {tool} (off the read/draft allowlist) is DENIED at level 2",
              code == 2 and "engedelylistan" in err, f"exit={code} err={err[:160]!r}")

    # --- MS365GATE1015 (Viktor G3): a renamed server is not a blind spot ------
    for server in ("outlook", "m365", "mail"):
        for tool in ("graph-batch", "create-mail-rule", "reply-shared-mailbox-mail",
                     "send-draft-message"):
            code, _, err = run_gate(store, {"tool_name": f"mcp__{server}__{tool}", "tool_input": {}})
            check(f"G3: {server}/{tool} is DENIED by operation, whatever the server name",
                  code == 2, f"exit={code} err={err[:160]!r}")
    store = make_store(os.path.join(td, "g3"), level=2)
    code, _, err = run_gate(store, ms365(tool="mcp__outlook__send-mail"))
    anchor = anchor_from_stderr(err)
    check("G3: a renamed server's send-mail still needs the per-letter approval",
          code == 2 and anchor is not None, f"exit={code} err={err[:160]!r}")
    approve(store, anchor)
    code, _, _ = run_gate(store, ms365(tool="mcp__outlook__send-mail"))
    check("G3: ... and goes with it", code == 0, f"exit={code}")
    code, _, _ = run_gate(make_store(os.path.join(td, "g3b"), level=1),
                          {"tool_name": "mcp__outlook__list-mail-messages", "tool_input": {}})
    check("G3: a read on a non-ms365 server name is not this gate's business", code == 0, f"exit={code}")

    # An unreadable policy file is fail-closed: every ms365 tool is denied, the
    # reads too, and the six send names of the first version stay denied on any
    # server name.
    nopol = os.path.join(td, "nopolicy-hooks")
    os.makedirs(nopol)
    for f in ("email-approval-gate.py", "email_extract.py"):
        with open(os.path.join(HOOKS, f), encoding="utf-8") as src, \
                open(os.path.join(nopol, f), "w", encoding="utf-8") as dst:
            dst.write(src.read())
    store = make_store(os.path.join(td, "g1np"), level=2)
    for tool in ("mcp__ms365__list-mail-messages", "mcp__ms365__send-mail",
                 "mcp__outlook__send-mail", "mcp__outlook__forward-mail-message"):
        proc = subprocess.run([sys.executable, os.path.join(nopol, "email-approval-gate.py")],
                              input=json.dumps(ms365(tool=tool)).encode(), capture_output=True,
                              env=dict(os.environ, EMAIL_APPROVAL_GATE_STORE=store))
        err = proc.stderr.decode()
        check(f"G1: without ms365-tool-policy.json, {tool} is DENIED (fail-closed)",
              proc.returncode == 2 and "nem olvashato" in err, f"exit={proc.returncode} err={err[:160]!r}")

    # --- MS365GATE1015 (Viktor G2): the address is a bare addr-spec -----------
    store = make_store(os.path.join(td, "g2"), level=2)

    def ms365_named(address, name=None, field="toRecipients", **kw):
        p = ms365(**kw)
        ea = {"address": address}
        if name is not None:
            ea["name"] = name
        p["tool_input"]["body"]["Message"][field] = [{"emailAddress": ea}]
        return p
    for label, payload in (
            ("an RFC comment after the address (the fuzz case)",
             ms365_named("balazs@myshp.hu (evil@x.com)")),
            ("two addresses in one field", ms365_named("a@b.hu, c@d.hu")),
            ("a display name inside the address", ms365_named("Balazs <balazs@myshp.hu>")),
            ("a space", ms365_named("a @b.hu")),
            ("a comment in the cc", ms365_named("gazda@pelda.hu (x@y.hu)", field="ccRecipients")),
            ("a newline in the name", ms365_named("a@b.hu", name="Kedves\nBcc: x@y.hu")),
            ("angle brackets in the name", ms365_named("evil@x.hu", name="Balazs <balazs@myshp.hu>")),
            # G2b (Viktor, CWE-451/176): what the approver reads must be what
            # Exchange receives.
            ("a zero-width character after the address", ms365_named("balazs@myshp.hu\u200b")),
            ("an accented address", ms365_named("bal\u00e1zs@myshp.hu")),
            ("a Cyrillic homoglyph in the domain", ms365_named("balazs@myshp.h\u0443")),
            ("a bidi override in the name", ms365_named("a@b.hu", name="Bal\u00e1zs\u202emoc.x")),
            ("a zero-width character in the name", ms365_named("a@b.hu", name="Bal\u200bazs")),
            ("a comma in the name", ms365_named("evil@x.hu", name="Balazs, Patrik")),
            ("an @ in the name", ms365_named("evil@x.hu", name="balazs@myshp.hu")),
            ("a line separator in the name", ms365_named("a@b.hu", name="Balazs\u2028Bcc"))):
        code, _, err = run_gate(store, payload)
        check(f"G2: {label} is unreadable -> DENIED",
              code == 2 and "nem horgonyozhato" in err, f"exit={code} err={err[:160]!r}")
    code, _, err = run_gate(store, ms365_named("a@b.hu", name="Kovács Éva"))
    check("G2: a plain name with accents is still readable (anchor offered)",
          code == 2 and anchor_from_stderr(err) is not None, f"exit={code} err={err[:160]!r}")

    # The standing check reads the raw address fields, not a re-parse of the
    # "name <addr>" display string.
    spec = importlib.util.spec_from_file_location("eag_g2", GATE)
    eag = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(eag)
    standing = {"kollega@pelda.hu": "gazda@pelda.hu"}
    env_ok = {"to": ["Kolléga <kollega@pelda.hu>"], "cc": ["gazda@pelda.hu"], "bcc": [],
              "addrs": {"to": ["kollega@pelda.hu"], "cc": ["gazda@pelda.hu"], "bcc": []}}
    check("G2: standing match on the raw addresses",
          eag.standing_match(env_ok, standing) == ("kollega@pelda.hu", "gazda@pelda.hu"))
    env_bad = dict(env_ok, addrs={"to": ["evil@x.hu"], "cc": ["gazda@pelda.hu"], "bcc": []})
    check("G2: a display string that re-parses to the standing address does NOT match "
          "when the raw address differs", eag.standing_match(env_bad, standing) is None)
    env_cc = dict(env_ok, addrs={"to": ["kollega@pelda.hu"], "cc": ["masik@x.hu"], "bcc": []})
    check("G2: the required cc is checked on the raw cc address too",
          eag.standing_match(env_cc, standing) is None)

    # F2: the hook only runs if settings.json routes the tool to it. Removing
    # the matcher must fail here, not silently on the live install.
    with open(os.path.join(os.path.dirname(os.path.dirname(HERE)), ".claude", "settings.json"),
              encoding="utf-8") as fh:
        pre = json.load(fh)["hooks"]["PreToolUse"]
    for hook in ("email-approval-gate.py", "outgoing-copy-gate.py"):
        for tool in ("mcp__ms365__send-mail", "mcp__ms365__forward-mail-message",
                     "mcp__ms365__send-draft-message", "mcp__ms365__graph-batch",
                     "mcp__ms365__create-mail-rule", "mcp__ms365__get-me",
                     "mcp__outlook__reply-shared-mailbox-mail", "mcp__m365__send-mail"):
            routed = any(re.fullmatch(e.get("matcher", ""), tool)
                         and any(hook in (h.get("command") or "") for h in e.get("hooks", []))
                         for e in pre)
            check(f"settings.json routes {tool.split('__')[-1]} to {hook}", routed)

    # --- MS365SEND1014: standing recipient with a REQUIRED cc (Patrik TG 1915) --
    def activate_anchor(store, anchor):
        con = sqlite3.connect(os.path.join(store, "claudeclaw.db"))
        con.execute(
            "INSERT INTO approvals (id, agent_id, category, action_description, status,"
            " requested_at, resolved_at, resolved_by, content_hash, consumed_at)"
            " VALUES (hex(randomblob(6)), 'marveen', 'email_standing_recipient',"
            f" 'Allando cimzett CC-vel', 'approved', {NOW_S}-60, {NOW_S}, 'szabi', ?, NULL)",
            (anchor,))
        con.commit()
        con.close()

    def sha(s):
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    store = make_store(os.path.join(td, "cc1"), level=2)
    write_standing(store, {"recipients": [
        {"address": "kolléga@pelda.hu".replace("é", "e"), "require_cc": "Gazda <gazda@pelda.hu>"}]})
    activate_anchor(store, sha("kollega@pelda.hu|cc:gazda@pelda.hu"))
    code, out, err = run_gate(store, mcp_send(to="kollega@pelda.hu", cc="gazda@pelda.hu"), NO_DASH)
    check("standing cc: to the colleague WITH the owner in cc goes without approval",
          code == 0 and "allando cimzett" in out, f"exit={code} err={err[:160]!r}")
    code, out, _ = run_gate(store, ms365(to=("kollega@pelda.hu",), cc=("gazda@pelda.hu",)), NO_DASH)
    check("standing cc: the same through ms365 send-mail", code == 0, f"exit={code}")
    for name, payload in (
            ("without the owner in cc", mcp_send(to="kollega@pelda.hu")),
            ("with another cc", mcp_send(to="kollega@pelda.hu", cc="idegen@pelda.hu")),
            ("with the owner AND another cc",
             mcp_send(to="kollega@pelda.hu", cc="gazda@pelda.hu, idegen@pelda.hu")),
            ("with a bcc", ms365(to=("kollega@pelda.hu",), cc=("gazda@pelda.hu",),
                                 bcc=("idegen@pelda.hu",))),
            ("to another address with the owner in cc",
             mcp_send(to="idegen@pelda.hu", cc="gazda@pelda.hu"))):
        code, _, err = run_gate(store, payload, NO_DASH)
        check(f"standing cc: {name} needs a per-letter approval",
              code == 2 and "NINCS jovahagyas" in err, f"exit={code} err={err[:160]!r}")
    # The condition is part of what the owner approved: dropping require_cc
    # from the file must not lift it.
    write_standing(store, {"recipients": ["kollega@pelda.hu"]})
    code, _, err = run_gate(store, mcp_send(to="kollega@pelda.hu"), NO_DASH)
    check("standing cc: deleting require_cc from the file does not make the cc-less send live",
          code == 2 and "NINCS ELESITVE" in err, f"exit={code} err={err[:160]!r}")
    # An unreadable condition grants nothing.
    write_standing(store, {"recipients": [
        {"address": "kollega@pelda.hu", "require_cc": "a@pelda.hu, b@pelda.hu"}]})
    code, _, err = run_gate(store, mcp_send(to="kollega@pelda.hu", cc="a@pelda.hu"), NO_DASH)
    check("standing cc: a require_cc with two addresses grants nothing", code == 2, f"exit={code}")
    # And the cc-less owner path is unchanged (anchor byte-identical to before).
    store = make_store(os.path.join(td, "cc2"), level=2)
    write_standing(store, {"recipients": ["gazda@pelda.hu"]})
    activate_anchor(store, sha("gazda@pelda.hu"))
    code, _, _ = run_gate(store, mcp_send(to="gazda@pelda.hu"), NO_DASH)
    check("standing: the cc-less entry keeps its old anchor", code == 0, f"exit={code}")

    # SQLite-version portability, kept as a STATIC check on purpose. The
    # behavioural cases above only catch the bad call on a host whose sqlite is
    # older than 3.38 -- on CI (newer) they stay green while the live install
    # denies every approved letter. So assert the function is absent from the
    # source, which fails on every host once it is reintroduced. Measured
    # 2026-09-02: host python sqlite3 3.37.2, gate raised OperationalError,
    # and the fail-closed deny read as "no approval" rather than a version
    # fault. The 'unixepoch' MODIFIER (date(x,'unixepoch')) is ancient and
    # fine -- only the bare function call is banned.
    #
    # COMMENTS ARE STRIPPED before matching, and the pattern is assembled from
    # fragments: otherwise this file's own prose (and the pattern itself) would
    # register as a violation and the check would fail for a reason that has
    # nothing to do with any SQL. Strings are KEPT -- that is where the SQL is.
    banned = re.compile(r"(?<!')\b" + "unix" + r"epoch\s*\(")

    def code_without_comments(path):
        with open(path, "rb") as fh:
            return "".join(t.string for t in tokenize.tokenize(fh.readline)
                           if t.type != tokenize.COMMENT)

    hook_srcs = [os.path.join(HOOKS, f) for f in sorted(os.listdir(HOOKS)) if f.endswith(".py")]
    offenders = [os.path.basename(p) for p in hook_srcs + [os.path.abspath(__file__)]
                 if banned.search(code_without_comments(p))]
    check("portability: no bare SQLite unixepoch function call (needs 3.38+) in the hooks",
          not offenders, f"offenders={offenders}")
    # Control: the check can actually fail. Without this, a broken matcher
    # would report a clean tree forever and read exactly like a passing gate.
    check("control: the same matcher DOES flag the old expression",
          bool(banned.search("SELECT unix" + "epoch()-60")))
    check("control: the host's own sqlite3 really executes the replacement expression",
          sqlite3.connect(":memory:").execute(f"SELECT {NOW_S}").fetchone()[0] > 1_700_000_000)

print()
if failed:
    print(f"{len(failed)} FAILED: {failed}", file=sys.stderr)
    sys.exit(1)
print("All email-approval-gate tests passed.")
