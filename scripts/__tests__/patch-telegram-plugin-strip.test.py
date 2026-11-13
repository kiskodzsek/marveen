#!/usr/bin/env python3
"""patch-telegram-plugin.py "strip" and "who" patches: gate markers leave the sent Telegram text (Klodel 38054,
Balázs TG 5404), and the sender of each inbound message is recorded for the Creatorz gate (Klodel 38073).

1. The patch lands once per handler (reply, edit_message) on a fixture, is idempotent, and is all-or-nothing.
2. The inserted code, run under node with the handler's own names (args, req, STATE_DIR, fs, path), cuts the
   markers, keeps everything else, logs what it cut (0600), refuses a text that is only markers, and leaves a
   text without markers byte for byte.
3. End to end with the real gate: without the marker product-image-gate still blocks; with it the gate lets the
   text through, and the text the plugin sends carries no marker.
4. If the installed plugin is on this machine: both anchors are found exactly once and the patched copy transpiles
   (bun build --no-bundle). Skipped, not failed, where the plugin or bun is missing.
Run: python3 -I scripts/__tests__/patch-telegram-plugin-strip.test.py
"""
import glob
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "patch-telegram-plugin.py")
GATE = os.path.join(HERE, "..", "hooks", "product-image-gate.py")
spec = importlib.util.spec_from_file_location("ptp", SCRIPT)
ptp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ptp)
STRIP = next(p for p in ptp.PATCHES if p["name"] == "strip")
FAILS = []

FIXTURE = """mcp.setRequestHandler(CallToolRequestSchema, async req => {
  const args = (req.params.arguments ?? {}) as Record<string, unknown>
  try {
    switch (req.params.name) {
      case 'reply': {
        const text = args.text as string
      }
      case 'edit_message': {
        const t2 = args.text as string
      }
    }
  } catch (err) {}
})
"""


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def strip(text, chat="-100", tool="reply", state=None, ages=None):
    """Runs the inserted JS once under node. state: an existing dir for STATE_DIR (default: a fresh one); ages:
    {file name: days} fakes the creation time statSync reports. Returns (sent text or None, error or None, log
    lines, log mode, state dir listing)."""
    snippet = STRIP["insert"].format(indent="")
    with tempfile.TemporaryDirectory() as d:
        sd = state if state is not None else d
        js = ("const fs = require('fs'); const { writeFileSync, renameSync, rmSync } = fs; const { join, basename } = require('path');\n"
              f"const AGES = {json.dumps(ages or {})};\n"
              "const statSync = p => { const s = fs.statSync(p); const a = AGES[basename(p)];\n"
              "  return { size: s.size, mtimeMs: s.mtimeMs, birthtimeMs: a != null ? Date.now() - a * 864e5 : s.birthtimeMs } };\n"
              f"const STATE_DIR = {json.dumps(sd)}; const req = {{ params: {{ name: {json.dumps(tool)} }} }};\n"
              f"const args = {{ chat_id: {json.dumps(chat)}, text: {json.dumps(text)} }};\n"
              "try {\n" + snippet + "process.stdout.write(JSON.stringify({ text: args.text }))\n"
              "} catch (e) { process.stdout.write(JSON.stringify({ error: String(e.message) })) }\n")
        p = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=20)
        if p.returncode != 0:
            return None, "node: " + p.stderr[-300:], [], None, []
        out = json.loads(p.stdout)
        logf = os.path.join(sd, "outbound-markers.jsonl")
        lines, mode = [], None
        if os.path.exists(logf):
            lines = [json.loads(x) for x in open(logf, encoding="utf-8").read().splitlines() if x]
            mode = stat.S_IMODE(os.stat(logf).st_mode)
        listing = sorted(os.listdir(sd)) if os.path.isdir(sd) else []
        return out.get("text"), out.get("error"), lines, mode, listing


def gate(text, chat="-1000000000001"):
    env = {"PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": tempfile.mkdtemp(), "MARVEEN_OWNER_PRIVATE_CHAT": "5040302010"}
    # Majsztro's budget at 100 % (synthetic), so "MAJSZTRO: helyettes-klodel" is accepted: a subprocess run cannot
    # reach the queue for a "MAJSZTRO: MEHET <id>" (same setup as run_idea in product-image-gate_test.py).
    ms = os.path.join(env["CLAUDE_PROJECT_DIR"], "store", "mod-state")
    os.makedirs(ms)
    with open(os.path.join(ms, "majsztro.json"), "w") as f:
        json.dump({"usage": {"rateLimits": [{"kind": "five_hour", "percentUsed": 0},
                                            {"kind": "seven_day", "percentUsed": 100}]}}, f)
    p = subprocess.run([sys.executable, "-I", GATE], input=json.dumps({"tool_input": {"chat_id": chat, "text": text}}),
                       capture_output=True, text=True, env=env, timeout=20)
    shutil.rmtree(env["CLAUDE_PROJECT_DIR"], ignore_errors=True)
    return p.returncode


# 1. patch mechanics
new, st = ptp.apply_patch(FIXTURE, STRIP)
check("patch lands", st == "patched" and new.count(ptp.STRIP_MARKER) == 2)
check("insert sits inside each case, before the text is read",
      new.index("case 'reply': {") < new.index(ptp.STRIP_MARKER) < new.index("const text = args.text")
      and new.index("case 'edit_message': {") < new.rindex(ptp.STRIP_MARKER) < new.index("const t2 = args.text"))
check("idempotent", ptp.apply_patch(new, STRIP) == (new, "already"))
# v1 -> v2 (Klodel 39799): a server.ts that carries the v1 line gets exactly what a fresh patch gives, once.
V1_JS = ptp.STRIP_JS.replace(ptp.STRIP_MARKER, ptp.STRIP_MARKER_V1)
v1, st1 = ptp.apply_patch(FIXTURE, dict(STRIP, marker=ptp.STRIP_MARKER_V1, insert=V1_JS, supersedes=[]))
up, st2 = ptp.apply_patch(v1, STRIP)
check("upgrade: a v1-patched file becomes the fresh v2 file",
      st1 == "patched" and v1.count(ptp.STRIP_MARKER_V1) == 2 and ptp.STRIP_MARKER not in v1
      and st2 == "patched" and up == new and ptp.apply_patch(up, STRIP) == (up, "already"), st2)
v1_half = v1.replace("case 'edit_message': {", "case 'edit': {")
check("upgrade: anchor missing leaves the v1 file untouched (all-or-nothing)",
      ptp.apply_patch(v1_half, STRIP) == (v1_half, "anchor-missing:edit_message case"))
check("the v2 marker keeps the v1 text as prefix (system-status.ts substring)",
      ptp.STRIP_MARKER.startswith(ptp.STRIP_MARKER_V1) and "MARVEEN-PATCH(kapu-jelolo-38054)" in ptp.STRIP_MARKER)
half = FIXTURE.replace("case 'edit_message': {", "case 'edit': {")
check("all-or-nothing", ptp.apply_patch(half, STRIP) == (half, "anchor-missing:edit_message case"))

# 2. behaviour of the inserted code
cases = [
    ("ÖTLET-KAPU line", "Új ötlet: kalkulátor.\nÖTLET-KAPU: nem Marabel/könyv, termékpaletta ellenőrizve (6)\nVége.",
     "Új ötlet: kalkulátor.\nVége."),
    ("BALAZS-OK line, any case and form", "Balázs, nézd meg.\nBALAZS-OK: TG 5400\nbalázs ok: TG 1\nKöszi.",
     "Balázs, nézd meg.\nKöszi."),
    ("PATRIK-KERTE line", "PR #183 mehet?\nPATRIK-KÉRTE: TG 17000", "PR #183 mehet?"),
    ("ELVETETT-DE-KERT line", "ELVETETT-DE-KERT: TG 17454\nÚj irány: szalon.", "Új irány: szalon."),
    ("PRIVÁT-OK line", "Kész.\nPRIVÁT-OK: Patrik privátban kérdezte\nRészletek lent.", "Kész.\nRészletek lent."),
    ("indented marker line", "Szöveg.\n  ÖTLET-KAPU: nem Marabel/könyv, termékpaletta ellenőrizve x\nVége.", "Szöveg.\nVége."),
    # Klodel 39799: the reviewer lines the idea gate wants are internal too
    ("ATNEZO: MEHET line", "Új ötlet: kalkulátor.\nATNEZO: MEHET a1b2c3d4e5\nVége.", "Új ötlet: kalkulátor.\nVége."),
    ("ATNÉZŐ: nincs-ötlet line", "Állapot.\nATNÉZŐ: nincs-ötlet csak állapot, nincs új irány", "Állapot."),
    ("MAJSZTRO: MEHET line", "Ötlet.\nMAJSZTRO: MEHET 39550\nVége.", "Ötlet.\nVége."),
    ("MAJSZTRÓ: helyettes-klodel line, any case", "Ötlet.\nmajsztró: Helyettes-Klodel keret 100 %", "Ötlet."),
    ("MarkdownV2-escaped hyphen", "Ötlet.\nMAJSZTRO: helyettes\\-klodel keret\nATNEZO: nincs\\-otlet csak állapot", "Ötlet."),
    ("MAJSZTRO: nem-marketing / kivetel-1881", "Kép.\nMAJSZTRO: nem-marketing belső ábra\nMAJSZTRO: kivetel-1881 39001", "Kép."),
]
for name, text, want in cases:
    got, err, log, mode, _ = strip(text)
    check("cut: " + name, got == want and err is None and len(log) == 1 and log[0]["removed"], f"got={got!r} err={err}")

keep = ("A Forrás: KSH 2024 szerint 48 141 vállalkozás.\nforrás: Eurostat\nA BALAZS-OK szó a mondat közepén marad.\n"
        "FORRÁS: msg 38057, ads-1111.csv")
got, err, log, _, _ = strip(keep)
check("kept: FORRÁS: line (Klodel 38117), prose Forrás:, a marker word mid-sentence", got == keep and not log, repr(got))

keep2 = ("Majsztro: kész a heti szöveg, holnap nézi Patrik.\nMAJSZTRO: szerintem jó\nATNEZO szerint mehet.\n"
         "A MAJSZTRO: MEHET 1 sor a mondat közepén marad.\nMAJSZTRO: MEHETNÉK holnap?\nMAJSZTRO: MEHETÉS?\nATNEZO: MEHETNÉK holnap?")
got, err, log, _, _ = strip(keep2)
check("kept: prose Majsztro:/ATNEZO lines, a gate form mid-sentence or as a longer word", got == keep2 and not log, repr(got))

got, err, log, _, _ = strip("A szám 12 100.\nÖTLET-KAPU: nem Marabel/könyv, termékpaletta ellenőrizve (6)\nFORRÁS: msg 38057")
check("ÖTLET-KAPU cut, FORRÁS kept beside it", got == "A szám 12 100.\nFORRÁS: msg 38057" and len(log) == 1, repr(got))

nfd = "Café ma.\n"  # NFD, no marker: must go out byte for byte
got, err, log, _, _ = strip(nfd)
check("no marker: byte for byte, no log", got == nfd and not log, repr(got))

got, err, log, mode, _ = strip("PRIVÁT-OK: Patrik privátban kérdezte\nÖTLET-KAPU: nem Marabel/könyv, termékpaletta ellenőrizve x")
check("only markers: refused, not sent empty", got is None and err and "only gate markers" in err, f"{got!r} {err}")

got, err, log, mode, _ = strip("Szöveg.\nBALAZS-OK: TG 5400", chat="-42", tool="edit_message")
check("audit log: chat, tool, the cut line, mode 0600",
      log and log[0]["chat_id"] == "-42" and log[0]["tool"] == "edit_message" and log[0]["removed"] == ["BALAZS-OK: TG 5400"]
      and mode == 0o600, f"{log} {oct(mode or 0)}")

# Viktor 38092 L1: a marker mid-sentence stays (nothing after it is lost); L3: no audit line, no change;
# I2: the rest of the text is not normalised. Lex 38089: a logged line is at most 80 characters, references kept.
mid = "A számla 120 000 Ft. PRIVÁT-OK: igen. Erősítsd meg, mielőtt fizetsz."
got, err, log, _, _ = strip(mid)
check("PRIVÁT-OK mid-sentence stays, nothing lost", got == mid and not log, repr(got))
got, err, log, _, _ = strip("Kész.\nÖTLET-KAPU: nem Marabel/könyv, termékpaletta ellenőrizve x", state="/nonexistent/marveen-test")
check("audit write fails: text unchanged (marker visible, not gone)", got == "Kész.\nÖTLET-KAPU: nem Marabel/könyv, termékpaletta ellenőrizve x" and err is None, f"{got!r} {err}")
nf = "Cafe\u0301 ma.  \nÖTLET-KAPU: nem Marabel/könyv, termékpaletta ellenőrizve x\nMásodik sor  \nVége."
got, err, log, _, _ = strip(nf)
check("rest not normalised (NFD, two trailing spaces kept)", got == "Cafe\u0301 ma.  \nMásodik sor  \nVége.", repr(got))
longl = "PRIVÁT-OK: " + "hosszú indoklás " * 10 + "TG 17454 msg 38073"
got, err, log, _, _ = strip("Szöveg.\n" + longl)
r = log[0]["removed"][0] if log else ""
check("logged line cut to 80 chars, references kept", r.startswith(longl[:80]) and len(r) < len(longl) and "TG 17454" in r
      and "msg 38073" in r, r)

# Retention (Lex 38089): created > 45 days ago -> .1; a .1 created > 90 days ago is removed.
with tempfile.TemporaryDirectory() as sd:
    open(os.path.join(sd, "outbound-markers.jsonl"), "w").write('{"old": 1}\n')
    open(os.path.join(sd, "outbound-markers.jsonl.1"), "w").write('{"older": 1}\n')
    _, _, log, _, ls = strip("x\nBALAZS-OK: TG 1", state=sd, ages={"outbound-markers.jsonl": 46, "outbound-markers.jsonl.1": 10})
    rotated = open(os.path.join(sd, "outbound-markers.jsonl.1")).read()
    check("main file older than 45 days rotates to .1", '"old"' in rotated and len(log) == 1 and "old" not in log[0], f"{ls} {log}")
with tempfile.TemporaryDirectory() as sd:
    open(os.path.join(sd, "outbound-markers.jsonl.1"), "w").write('{"older": 1}\n')
    _, _, _, _, ls = strip("x\nBALAZS-OK: TG 1", state=sd, ages={"outbound-markers.jsonl.1": 91})
    check(".1 older than 90 days is removed", ls == ["outbound-markers.jsonl"], str(ls))
with tempfile.TemporaryDirectory() as sd:
    open(os.path.join(sd, "outbound-markers.jsonl.1"), "w").write('{"older": 1}\n')
    _, _, _, _, ls = strip("x\nBALAZS-OK: TG 1", state=sd, ages={"outbound-markers.jsonl.1": 30})
    check(".1 younger than 90 days stays", ls == ["outbound-markers.jsonl", "outbound-markers.jsonl.1"], str(ls))

# The "who" patch: one line per inbound message, sender id and ids only, no text, 0600.
WHO = next(p for p in ptp.PATCHES if p["name"] == "who")
with tempfile.TemporaryDirectory() as sd:
    js = ("const fs = require('fs'); const { writeFileSync, statSync, renameSync, rmSync } = fs; const { join } = require('path');\n"
          f"const STATE_DIR = {json.dumps(sd)}; const chat_id = '-100'; const msgId = 901; const from = {{ id: 8366648365, username: 'b' }};\n"
          + WHO["insert"].format(indent=""))
    p = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=20)
    f = os.path.join(sd, "inbound-senders.jsonl")
    rec = json.loads(open(f).read().strip()) if os.path.exists(f) else {}
    check("who: chat_id, message_id, user_id, at; no text, no name; 0600",
          p.returncode == 0 and sorted(rec) == ["at", "chat_id", "message_id", "user_id"] and rec["user_id"] == "8366648365"
          and rec["message_id"] == "901" and stat.S_IMODE(os.stat(f).st_mode) == 0o600, f"{p.stderr[-200:]} {rec}")

# 3. end to end with the real gate (ÖTLET-KAPU)
pitch = "Új ötlet: hűtőmágnes-bolt."
line = "ÖTLET-KAPU: nem Marabel/könyv, termékpaletta ellenőrizve (6 termékkel)"
# Since Klodel 39520 / 39550 the idea gate also wants the blind reviewer's and Majsztro's lines; since 39799 the
# strip cuts them too, so only the pitch reaches the chat.
reviewed = "ATNEZO: MEHET a1b2c3d4e5\nMAJSZTRO: helyettes-klodel teszt, Májsztró kerete 100 %-on"
check("gate: no marker still blocks", gate(pitch) == 2)
check("gate: ÖTLET-KAPU without the reviewer lines still blocks", gate(pitch + "\n" + line) == 2)
both = pitch + "\n" + line + "\n" + reviewed
sent, err, _, _, _ = strip(both)
check("gate: with all marker lines passes, and the sent text has no gate line",
      gate(both) == 0 and sent == pitch, repr(sent))

# 4. the installed plugin, if any
plugins = sorted(glob.glob(os.path.expanduser("~/.claude/plugins/cache/claude-plugins-official/telegram/*/server.ts")))
if not plugins:
    print("SKIP installed plugin: not on this machine")
for path in plugins:
    src = open(path, encoding="utf-8").read()
    if ptp.STRIP_MARKER in src:
        check(f"installed {path.split('/')[-2]}: already patched", src.count(ptp.STRIP_MARKER) == 2)
        continue
    out, st = ptp.apply_patch(src, STRIP)
    check(f"installed {path.split('/')[-2]}: anchors found once", st == "patched", st)
    if ptp.WHO_MARKER not in out:
        out, st2 = ptp.apply_patch(out, WHO)
        check(f"installed {path.split('/')[-2]}: who anchor found once", st2 == "patched", st2)
    bun = shutil.which("bun") or os.path.expanduser("~/.bun/bin/bun")
    if st == "patched" and os.path.exists(bun):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "server.ts")
            open(f, "w", encoding="utf-8").write(out)
            p = subprocess.run([bun, "build", "--no-bundle", f], capture_output=True, text=True, timeout=60)
            check(f"installed {path.split('/')[-2]}: patched copy transpiles", p.returncode == 0, p.stderr[-300:])

print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'All patch-telegram-plugin strip tests passed.'}")
sys.exit(1 if FAILS else 0)
