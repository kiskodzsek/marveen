#!/usr/bin/env python3
"""patch-telegram-plugin.py "strip" patch: gate markers leave the sent Telegram text (Klodel 38054, Balázs TG 5404).

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


def strip(text, chat="-100", tool="reply"):
    """Runs the inserted JS once under node. Returns (sent text or None, error or None, log lines, log mode)."""
    snippet = STRIP["insert"].format(indent="")
    with tempfile.TemporaryDirectory() as d:
        js = ("const { writeFileSync, statSync, renameSync } = require('fs'); const { join } = require('path');\n"
              f"const STATE_DIR = {json.dumps(d)}; const req = {{ params: {{ name: {json.dumps(tool)} }} }};\n"
              f"const args = {{ chat_id: {json.dumps(chat)}, text: {json.dumps(text)} }};\n"
              "try {\n" + snippet + "process.stdout.write(JSON.stringify({ text: args.text }))\n"
              "} catch (e) { process.stdout.write(JSON.stringify({ error: String(e.message) })) }\n")
        p = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=20)
        if p.returncode != 0:
            return None, "node: " + p.stderr[-300:], [], None
        out = json.loads(p.stdout)
        logf = os.path.join(d, "outbound-markers.jsonl")
        lines, mode = [], None
        if os.path.exists(logf):
            lines = [json.loads(x) for x in open(logf, encoding="utf-8").read().splitlines() if x]
            mode = stat.S_IMODE(os.stat(logf).st_mode)
        return out.get("text"), out.get("error"), lines, mode


def gate(text, chat="-1000000000001"):
    env = {"PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": tempfile.mkdtemp(), "MARVEEN_OWNER_PRIVATE_CHAT": "5040302010"}
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
    ("FORRÁS upper-case line", "A szám 12 100.\nFORRÁS: msg 38057, ads-1111.csv", "A szám 12 100."),
    ("PRIVÁT-OK mid-line, to the line end", "Kész. PRIVÁT-OK: Patrik privátban kérdezte\nRészletek lent.",
     "Kész.\nRészletek lent."),
    ("indented marker line", "Szöveg.\n  ÖTLET-KAPU: nem Marabel/könyv, termékpaletta ellenőrizve x\nVége.", "Szöveg.\nVége."),
]
for name, text, want in cases:
    got, err, log, mode = strip(text)
    check("cut: " + name, got == want and err is None and len(log) == 1 and log[0]["removed"], f"got={got!r} err={err}")

keep = "A Forrás: KSH 2024 szerint 48 141 vállalkozás.\nforrás: Eurostat\nA BALAZS-OK szó a mondat közepén marad."
got, err, log, _ = strip(keep)
check("prose kept (Forrás:, forrás:, a marker word mid-sentence)", got == keep and not log, repr(got))

nfd = "Café ma.\n"  # NFD, no marker: must go out byte for byte
got, err, log, _ = strip(nfd)
check("no marker: byte for byte, no log", got == nfd and not log, repr(got))

got, err, log, mode = strip("PRIVÁT-OK: Patrik privátban kérdezte\nÖTLET-KAPU: nem Marabel/könyv, termékpaletta ellenőrizve x")
check("only markers: refused, not sent empty", got is None and err and "only gate markers" in err, f"{got!r} {err}")

got, err, log, mode = strip("Szöveg.\nBALAZS-OK: TG 5400", chat="-42", tool="edit_message")
check("audit log: chat, tool, the cut line, mode 0600",
      log and log[0]["chat_id"] == "-42" and log[0]["tool"] == "edit_message" and log[0]["removed"] == ["BALAZS-OK: TG 5400"]
      and mode == 0o600, f"{log} {oct(mode or 0)}")

# 3. end to end with the real gate (ÖTLET-KAPU)
pitch = "Új ötlet: kalkulátor-portál."
line = "ÖTLET-KAPU: nem Marabel/könyv, termékpaletta ellenőrizve (6 termékkel)"
check("gate: no marker still blocks", gate(pitch) == 2)
both = pitch + "\n" + line
sent, err, _, _ = strip(both)
check("gate: with marker passes, and the sent text has no marker",
      gate(both) == 0 and sent == pitch and "ÖTLET-KAPU" not in (sent or ""), repr(sent))

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
    bun = shutil.which("bun") or os.path.expanduser("~/.bun/bin/bun")
    if st == "patched" and os.path.exists(bun):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "server.ts")
            open(f, "w", encoding="utf-8").write(out)
            p = subprocess.run([bun, "build", "--no-bundle", f], capture_output=True, text=True, timeout=60)
            check(f"installed {path.split('/')[-2]}: patched copy transpiles", p.returncode == 0, p.stderr[-300:])

print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'All patch-telegram-plugin strip tests passed.'}")
sys.exit(1 if FAILS else 0)
