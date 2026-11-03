#!/usr/bin/env python3
"""Klodel 24795: scripts/telegram-pin.py against a stub Bot API (no real Telegram call).

  - pin is silent by default, --notify turns the notification on; unpin sends the message id;
  - a chat outside access.json is refused locally and the API is never called;
  - without --chat the one configured group is used; with two groups --chat is required;
  - the token never appears in the output or the log, also when the API errors;
  - `open` lists pins not yet taken off; a failed pin is not listed;
  - `check`: a plain member -> owner_action, a supergroup admin without the right -> owner_action,
    an admin with the right -> can_pin.

Run: python3 <thisfile>   Exit 0 = all pass.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("tgpin", os.path.join(os.path.dirname(HERE), "telegram-pin.py"))
tgpin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tgpin)

TOKEN = "123456:synthetic-test-token-not-a-secret"
GROUP = "-5000000001"
calls = []
member = {"status": "member"}
chat_type = {"type": "group"}
fail_next = {"pin": None}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        method = self.path.rsplit("/", 1)[-1]
        calls.append((self.path, method, body))
        if method == "getMe":
            out = {"ok": True, "result": {"id": 42, "is_bot": True}}
        elif method == "getChat":
            out = {"ok": True, "result": {"id": int(body["chat_id"]), **chat_type}}
        elif method == "getChatMember":
            out = {"ok": True, "result": dict(member)}
        elif method == "pinChatMessage" and fail_next["pin"]:
            self.send_response(400)
            self.end_headers()
            err = {"ok": False, "description": fail_next["pin"]}
            if fail_next.get("migrate"):
                err["parameters"] = {"migrate_to_chat_id": int(fail_next.pop("migrate"))}
            self.wfile.write(json.dumps(err).encode())
            fail_next["pin"] = None
            return
        else:
            out = {"ok": True, "result": True}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)


srv = HTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_port}"

root = tempfile.mkdtemp(prefix="tgpin-")
cdir = os.path.join(root, ".claude", "channels", "telegram")
os.makedirs(cdir)
with open(os.path.join(cdir, ".env"), "w") as f:
    f.write(f"TELEGRAM_BOT_TOKEN={TOKEN}\n")


def access(groups):
    with open(os.path.join(cdir, "access.json"), "w") as f:
        json.dump({"allowFrom": ["111"], "groups": {g: {} for g in groups}}, f)


os.environ.pop("TELEGRAM_STATE_DIR", None)
failed = []


def run(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = tgpin.main(list(argv), root=root, base=BASE)
    return rc, json.loads(buf.getvalue())


def ok(cond, label):
    if not cond:
        failed.append(label)
    print(("PASS " if cond else "FAIL ") + label)


access([GROUP])

calls.clear()
rc, out = run("pin", "77")
ok(rc == 0 and out["ok"] and out["chat"] == GROUP, "pin in the one configured group")
ok(calls and calls[-1][1] == "pinChatMessage" and calls[-1][2] == {"chat_id": GROUP, "message_id": 77, "disable_notification": True},
   "pin is silent by default")
rc, out = run("pin", "78", "--notify")
ok(calls[-1][2]["disable_notification"] is False, "--notify turns the notification on")

rc, out = run("open")
ok([p["message_id"] for p in out["open"]] == [77, 78], "open lists both pins")
rc, out = run("unpin", "77")
ok(rc == 0 and calls[-1][1] == "unpinChatMessage" and calls[-1][2] == {"chat_id": GROUP, "message_id": 77}, "unpin sends chat + message id")
rc, out = run("open")
ok([p["message_id"] for p in out["open"]] == [78], "unpinned message leaves the open list")

fail_next["pin"] = "Bad Request: not enough rights to manage pinned messages in the chat"
rc, out = run("pin", "79")
ok(rc == 1 and "not enough rights" in out["description"], "API refusal: exit 1 with the reason")
rc, out = run("open")
ok(79 not in [p["message_id"] for p in out["open"]], "a failed pin is not open")

n = len(calls)
rc, out = run("pin", "80", "--chat", "-999")
ok(rc == 2 and len(calls) == n, "chat outside access.json refused, API not called")
rc, out = run("pin", "0")
ok(rc == 2 and len(calls) == n, "message id 0 refused, API not called")
rc, out = run("pin", "80", "--chat", "111")
ok(rc == 0, "an allowFrom chat (private) is allowed")

access([GROUP, "-5000000002"])
n = len(calls)
rc, out = run("pin", "81")
ok(rc == 2 and len(calls) == n and "--chat" in out["error"], "two groups: --chat required")

# Klodel 24935: the owner's supergroup is the default when listed, next to the dead old id.
access(["-5194177964", tgpin.DEFAULT_GROUP])
rc, out = run("pin", "83")
ok(rc == 0 and out["chat"] == tgpin.DEFAULT_GROUP and calls[-1][2]["chat_id"] == tgpin.DEFAULT_GROUP, "default supergroup chosen among two groups")
fail_next["pin"] = "Bad Request: group chat was upgraded to a supergroup chat"
fail_next["migrate"] = tgpin.DEFAULT_GROUP
rc, out = run("pin", "84", "--chat", "-5194177964")
ok(rc == 1 and out.get("migrated_to") == tgpin.DEFAULT_GROUP, "old group id: the migration target is reported")
access([GROUP])

# check
member.clear(); member.update({"status": "member"}); chat_type["type"] = "group"
rc, out = run("check")
ok(rc == 0 and out["can_pin"] is False and "admin" in out["owner_action"], "check: plain member -> owner action")
member.clear(); member.update({"status": "administrator", "can_pin_messages": False}); chat_type["type"] = "supergroup"
rc, out = run("check")
ok(out["can_pin"] is False and "Pin messages" in out["owner_action"], "check: supergroup admin without the right")
member.clear(); member.update({"status": "administrator", "can_pin_messages": True})
rc, out = run("check")
ok(out["can_pin"] is True and "owner_action" not in out, "check: admin with the right can pin")
member.clear(); member.update({"status": "administrator"}); chat_type["type"] = "group"
rc, out = run("check")
ok(out["can_pin"] is True, "check: basic-group admin without the granular field")

# token never leaks: output, log, and a transport error message
with open(os.path.join(root, "store", "telegram-pin.log")) as f:
    log = f.read()
ok(TOKEN not in log, "token not in the log")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    tgpin.main(["pin", "82"], root=root, base="http://127.0.0.1:1")  # nothing listens
ok(TOKEN not in buf.getvalue() and json.loads(buf.getvalue())["ok"] is False, "transport error: no token in the output")
ok(tgpin.redact(f"https://x/bot{TOKEN}/m failed", TOKEN) == "https://x/bot<token>/m failed", "redact replaces the token")
ok(tgpin.API_BASE == "https://api.telegram.org", "API base is the fixed Telegram host")

srv.shutdown()
shutil.rmtree(root, ignore_errors=True)
print(f"\n{'ALL PASS' if not failed else 'FAILED: ' + ', '.join(failed)}")
sys.exit(1 if failed else 0)
