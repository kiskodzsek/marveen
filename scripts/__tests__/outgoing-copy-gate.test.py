#!/usr/bin/env python3
"""Test the outbound-copy QA gate (scripts/hooks/outgoing-copy-gate.py).

Focus: the name-rule-file state distinction. Two owner decisions meet here,
and the 2026-09-04 upstream merge combined them (see the RULES_* block in the
hook for the full reasoning):
  - GATEPERSIST816/3 (PDB, 2026-08-19): a file that explicitly declares
    no_name_rule=true is a SANCTIONED state, silent everywhere -- and an
    ordinary empty list that merely forgot to say so must never be mistaken
    for it.
  - CLCOPYGATEHIANY902 (upstream, 2026-09-02): a MISSING or empty file is not
    the same as a BROKEN one. Missing/empty now fail-OPEN with a loud,
    user-visible warning, because the file is deliberately not shipped and the
    old fail-closed path left a fresh install unable to send mail at all.
    A file that EXISTS but is unusable (invalid) still fails CLOSED.
So the states are: ok / sanctioned (silent) / missing / empty (open + loud) /
invalid (closed). What this file guards above all is the pair that looks alike
and must not behave alike: sanctioned passes SILENTLY, empty-without-flag
passes LOUDLY.

Also carries a regression pass over the checks this task must NOT touch:
accents, em dash, double-hyphen, mixed-script (homoglyph). Drives the hook as
a subprocess against an isolated OUTGOING_COPY_GATE_RULES file so the real
store/outgoing-copy-gate-rules.json is never touched. Run:
  python3 scripts/__tests__/outgoing-copy-gate.test.py
Exit 0 = all pass; non-zero = a failure (message on stderr).
"""
import json
import os
import sys
import tempfile
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(os.path.dirname(HERE), "hooks", "outgoing-copy-gate.py")

CLEAN_HU = "Szia! Koszonom szepen, holnap kuldom at a szamlat es a reszleteket."
# proper accents, no dash, no homoglyph, no bad name -- a payload that should
# sail through every check except whatever the test deliberately breaks.
CLEAN_HU_OK = "Szia! Köszönöm szépen, holnap küldöm át a számlát és a részleteket."


def rules_path(tmpdir, name="rules.json"):
    return os.path.join(tmpdir, name)


def write_rules(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def run_hook(payload, rules_file=None, cwd=None):
    env = dict(os.environ)
    if rules_file is not None:
        env["OUTGOING_COPY_GATE_RULES"] = rules_file
    else:
        env.pop("OUTGOING_COPY_GATE_RULES", None)
    p = subprocess.run(
        [sys.executable, HOOK],
        input=json.dumps(payload),
        capture_output=True, text=True, env=env, timeout=20, cwd=cwd,
    )
    return p.returncode, p.stdout, p.stderr


def email_payload(body):
    return {"tool_name": "send_email", "tool_input": {"body": body}}


def telegram_payload(text):
    return {"tool_name": "mcp__plugin_telegram_telegram__reply", "tool_input": {"text": text}}


FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got={got!r} want={want!r}")
    if not ok:
        FAILS.append(name)


def check_true(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" ({detail})" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def main():
    with tempfile.TemporaryDirectory(prefix="copygate-") as tmp:

        # --- 1. MISSING file -----------------------------------------------
        missing = rules_path(tmp, "does-not-exist.json")
        # CLCOPYGATEHIANY902: the email goes OUT, but never silently -- the
        # sender has to see that the name check did not protect this letter.
        code, out, err = run_hook(email_payload(CLEAN_HU_OK), rules_file=missing)
        check("missing file: email fail-OPEN (exit 0)", code, 0)
        check_true("missing file: the pass is LOUD (systemMessage names the absent check)",
                   "systemMessage" in out and "HIANYZIK" in out, out)

        code, out, err = run_hook(telegram_payload(CLEAN_HU_OK), rules_file=missing)
        check("missing file: telegram fail-open (exit 0)", code, 0)
        check_true("missing file: telegram warns via systemMessage", "NEV-SZABALY" in out, out)

        # --- 2. CORRUPT file (unparseable JSON) -----------------------------
        corrupt = rules_path(tmp, "corrupt.json")
        with open(corrupt, "w", encoding="utf-8") as fh:
            fh.write("{ not valid json ]")
        code, out, err = run_hook(email_payload(CLEAN_HU_OK), rules_file=corrupt)
        check("corrupt file: email fail-closed (exit 2)", code, 2)
        check_true("corrupt file: email stderr names the rules file", "NEV-SZABALY" in err, err)

        code, out, err = run_hook(telegram_payload(CLEAN_HU_OK), rules_file=corrupt)
        check("corrupt file: telegram fail-open (exit 0)", code, 0)
        check_true("corrupt file: telegram warns via systemMessage", "NEV-SZABALY" in out, out)

        # --- 3. EXPLICIT no-rule (sanctioned, silent) -----------------------
        explicit_none = rules_path(tmp, "explicit-none.json")
        write_rules(explicit_none, {
            "no_name_rule": True,
            "no_name_rule_reason": "teszt: a regi szabaly-fajl elveszett, tudatosan nincs pótolva",
        })
        code, out, err = run_hook(email_payload(CLEAN_HU_OK), rules_file=explicit_none)
        check("explicit no-rule: email proceeds (exit 0)", code, 0)
        check_true("explicit no-rule: email stderr silent on name-rule", "NEV-SZABALY" not in err, err)

        code, out, err = run_hook(telegram_payload(CLEAN_HU_OK), rules_file=explicit_none)
        check("explicit no-rule: telegram proceeds (exit 0)", code, 0)
        check_true("explicit no-rule: telegram stays silent (no systemMessage)", out.strip() == "", out)

        # THE PAIR THAT MUST NOT BE CONFUSED. Since CLCOPYGATEHIANY902 both of
        # these let the letter out, so the exit code alone no longer separates
        # them -- the difference is now the NOISE, and that is what is asserted
        # here. A sanctioned file passes in silence; an ordinary empty list
        # that merely forgot the flag passes with a loud warning. If a future
        # change makes the empty list silent, the sanctioned state would have
        # become reachable by accident, which is what GATEPERSIST816/3 exists
        # to prevent.
        empty_no_flag = rules_path(tmp, "empty-no-flag.json")
        write_rules(empty_no_flag, {"bad_name_patterns": []})
        code, out, err = run_hook(email_payload(CLEAN_HU_OK), rules_file=empty_no_flag)
        check("empty patterns, no explicit flag: email fail-OPEN (exit 0)", code, 0)
        check_true("empty patterns, no explicit flag: the pass is LOUD",
                   "systemMessage" in out and "URES" in out, out)

        code, out, err = run_hook(telegram_payload(CLEAN_HU_OK), rules_file=empty_no_flag)
        check_true("empty patterns, no explicit flag: telegram also warns",
                   "systemMessage" in out, out)

        # --- 4. ACTIVE rule (unchanged matching behaviour) ------------------
        active = rules_path(tmp, "active.json")
        write_rules(active, {
            "bad_name_patterns": [r"\bTeszt[- ]?Elek\b"],
            "correction": "a helyes alak: Teszt Elemer",
        })
        code, out, err = run_hook(email_payload(CLEAN_HU_OK), rules_file=active)
        check("active rule, clean body: email proceeds (exit 0)", code, 0)

        bad_body = CLEAN_HU_OK + " Udvozlettel, Teszt Elek"
        code, out, err = run_hook(email_payload(bad_body), rules_file=active)
        check("active rule, bad name present: email blocks (exit 2)", code, 2)
        check_true("active rule, bad name present: stderr names the bad name", "HELYTELEN NEV" in err, err)
        check_true("active rule, bad name present: stderr carries the correction", "Teszt Elemer" in err, err)

        code, out, err = run_hook(telegram_payload(bad_body), rules_file=active)
        check("active rule, bad name present: telegram blocks (exit 2)", code, 2)

        # --- 5. Regression: checks this task must not touch -----------------
        # 5a. em dash
        code, out, err = run_hook(email_payload(CLEAN_HU_OK + " — mégis."), rules_file=active)
        check("em dash still blocks (exit 2)", code, 2)
        check_true("em dash: stderr names it", "GONDOLATJEL" in err, err)

        # 5b. missing accents (accent-insensitive Hungarian detector)
        code, out, err = run_hook(email_payload(CLEAN_HU), rules_file=active)
        check("missing accents still blocks (exit 2)", code, 2)
        check_true("missing accents: stderr names it", "HIANYZO EKEZETEK" in err, err)

        # 5b'. ac3cf99f (2026-10-20): the markers match whole words only. As
        # substrings "ami"/"amit" (in NotramIT) and "van" (in advance) made this
        # English reminder "Hungarian", and the accent ratio blocked it.
        english = (
            "Hello, this is a friendly reminder from NotramIT about the KOMPaaS subscription. "
            "The next invoice will be issued on the first business day of the month, and we would "
            "like to settle it in advance. Please let us know if the billing contact or the amount "
            "has changed since the last period. Thank you, NotramIT"
        )
        code, out, err = run_hook(email_payload(english), rules_file=active)
        check("English text with NotramIT / advance proceeds (exit 0)", code, 0)
        # ...and a long accentless Hungarian text still trips the ratio check.
        accentless_long = (
            "Szia, csak jelezni szeretnem, hogy a holnapi talalkozot at kell tennunk, mert nem "
            "tudok ott lenni idoben. Ha neked jo, akkor csutortokon delelott tiz orakor "
            "megbeszelhetjuk ugyanott, vagy irj egy masik idopontot, ami jobban megfelel."
        )
        code, out, err = run_hook(email_payload(accentless_long), rules_file=active)
        check("long accentless Hungarian still blocks (exit 2)", code, 2)

        # 5c. double-hyphen em-dash substitute
        code, out, err = run_hook(
            email_payload(CLEAN_HU_OK + " ez most -- szerintem -- jo lesz."), rules_file=active,
        )
        check("double-hyphen still blocks (exit 2)", code, 2)
        check_true("double-hyphen: stderr names it", "DUPLA KOTOJEL" in err, err)

        # 5d. mixed-script (Cyrillic homoglyph 'о' U+043E inside a Latin word)
        homoglyph_word = "kоszonom"  # koszonom with a Cyrillic 'o'
        code, out, err = run_hook(
            email_payload(f"Szia! {homoglyph_word} szepen a segitseget majd irok reszletesen is."),
            rules_file=active,
        )
        check("mixed-script homoglyph still blocks (exit 2)", code, 2)
        check_true("homoglyph: stderr names it", "VEGYES IRASRENDSZERU" in err, err)

        # 5d2. HOMOGLYPHMICRO924: unit and formula notation is not a mixed-script
        # word (MICRO SIGN, superscript and subscript digits disguise no Latin letter).
        units = " A mért késés 40 \u00b5s, a ház 100 m\u00b2, a doboz 5 cm\u00b3, a víz H\u2082O."
        code, out, err = run_hook(email_payload(CLEAN_HU_OK + units), rules_file=active)
        check("unit notation (micro sign, super/subscript digits) passes (exit 0)", code, 0)

        # 5e. clean, correctly-accented text with an active (matching-nothing)
        # rule and no em dash/double-hyphen/homoglyph -> passes clean.
        code, out, err = run_hook(email_payload(CLEAN_HU_OK), rules_file=active)
        check("fully clean body passes (exit 0)", code, 0)

        # --- 6. #1184: manage_email dispatch + telegram codeblock gate ------
        # COPYGATEMATCHER904: the multiplexed manage_email must be classified
        # by OPERATION. Before the fix every letter fell through to exit 0.
        def manage_payload(op, **kw):
            return {"tool_name": "mcp__google-workspace__manage_email",
                    "tool_input": {"operation": op, **kw}}

        code, out, err = run_hook(manage_payload("send", body=CLEAN_HU_OK + " — mégis."),
                                  rules_file=active)
        check("manage_email send with em dash blocks (exit 2)", code, 2)
        code, out, err = run_hook(manage_payload("send", body=CLEAN_HU_OK), rules_file=active)
        check("manage_email send clean passes (exit 0)", code, 0)
        code, out, err = run_hook(manage_payload("search", query="— rossz — szoveg"),
                                  rules_file=active)
        check("manage_email search is not audited (exit 0)", code, 0)
        code, out, err = run_hook(manage_payload("forward", message_id="x"), rules_file=active)
        check("manage_email bare forward passes (exit 0)", code, 0)

        # GATECOPY827: a code block without format=markdownv2 has no copy
        # button on the phone -- machine gate, not memory.
        fenced = "Íme:\n```\nls -la\n```\nfuttasd le kérlek."
        code, out, err = run_hook(telegram_payload(fenced), rules_file=active)
        check("telegram codeblock without markdownv2 blocks (exit 2)", code, 2)
        payload = telegram_payload(fenced)
        payload["tool_input"]["format"] = "markdownv2"
        code, out, err = run_hook(payload, rules_file=active)
        check("telegram codeblock WITH markdownv2 passes (exit 0)", code, 0)

        # edit_message goes through the same telegram gate as reply: the
        # scaffold matcher (#1184) wires both, so both must actually audit.
        edit_bad = {"tool_name": "mcp__plugin_telegram_telegram__edit_message",
                    "tool_input": {"message_id": "1", "text": CLEAN_HU_OK + " — mégis."}}
        code, out, err = run_hook(edit_bad, rules_file=active)
        check("edit_message with em dash blocks (exit 2)", code, 2)
        edit_fence = {"tool_name": "mcp__plugin_telegram_telegram__edit_message",
                      "tool_input": {"message_id": "1", "text": "```\nls\n``` légy szíves."}}
        code, out, err = run_hook(edit_fence, rules_file=active)
        check("edit_message codeblock without markdownv2 blocks (exit 2)", code, 2)
        edit_ok = {"tool_name": "mcp__plugin_telegram_telegram__edit_message",
                   "tool_input": {"message_id": "1", "text": CLEAN_HU_OK}}
        code, out, err = run_hook(edit_ok, rules_file=active)
        check("edit_message clean passes (exit 0)", code, 0)

        # --- GATEDISCORD905: the Discord reply path is audited too ----------
        # Same audit as Telegram, with two deliberate differences: no MarkdownV2
        # unescaping (a backslash on Discord is a literal the author typed), and
        # the Telegram-only code-block rule must NOT fire there.
        discord_bad = {"tool_name": "mcp__plugin_discord_discord__reply",
                       "tool_input": {"text": CLEAN_HU_OK + " — mégis."}}
        code, out, err = run_hook(discord_bad, rules_file=active)
        check("discord reply with em dash blocks (exit 2)", code, 2)
        check_true("discord block names the DISCORD channel, not Telegram",
                   "(Discord)" in err and "(Telegram)" not in err, err)

        discord_ok = {"tool_name": "mcp__plugin_discord_discord__reply",
                      "tool_input": {"text": CLEAN_HU_OK}}
        code, out, err = run_hook(discord_ok, rules_file=active)
        check("discord reply clean passes (exit 0)", code, 0)

        discord_edit = {"tool_name": "mcp__plugin_discord_discord__edit_message",
                        "tool_input": {"message_id": "1", "text": CLEAN_HU_OK + " — mégis."}}
        code, out, err = run_hook(discord_edit, rules_file=active)
        check("discord edit_message with em dash blocks (exit 2)", code, 2)

        # The code-block rule is Telegram-only. Discord renders a fenced block
        # natively and its reply tool has no markdownv2 format value, so firing
        # here would block a problem that does not exist. Paired with the
        # telegram case above, which must stay red for the same input.
        discord_fence = {"tool_name": "mcp__plugin_discord_discord__reply",
                         "tool_input": {"text": fenced}}
        code, out, err = run_hook(discord_fence, rules_file=active)
        check("discord codeblock without markdownv2 passes (exit 0)", code, 0)

        # A name hit still blocks on Discord: the channel branch is a new door,
        # not a bypass.
        discord_name = {"tool_name": "mcp__plugin_discord_discord__reply",
                        "tool_input": {"text": CLEAN_HU_OK + " Üdvözlettel, Teszt Elek"}}
        code, out, err = run_hook(discord_name, rules_file=active)
        check("discord reply with a bad name blocks (exit 2)", code, 2)

        # --- COPYGATEENT914: HTML-ENTITAS NEM KERULHETI MEG A GONDOLATJEL-TILTAST ---
        # Marveen merese 2026-09-14, egy VALODI vevo-levelen: a hook a TAGEKET
        # szedte ki, de az entitast sehol nem dekodolta, igy a `&mdash;` atment
        # es a cimzettnel gondolatjelkent renderelt. A kapu zoldet mondott arra,
        # amit tilt. Merve MIND A HAROM alakon, nem csak a bejelentettre.
        #
        # A SZOVEG SZANDEKOSAN TELJESEN EKEZETES. Az elso valtozatom ekezet
        # nelkuli volt, ezert a HIANYZO-EKEZET szabaly is tuzelt, es az exit 2
        # AKKOR IS teljesult, amikor a dekodolast visszavettem -- a teszt jonak
        # latszott, kozben nem az entitas-utat merte. A mutans-kontroll fogta meg.
        for nev, alak in (("nevesitett &mdash;", "&mdash;"),
                          ("szamos &#8212;", "&#8212;"),
                          ("hex &#x2014;", "&#x2014;")):
            ent = {"tool_name": "mcp__plugin_telegram_telegram__reply",
                   "tool_input": {"text": f"Szia! A határidő {alak} péntek, köszönöm."}}
            code, out, err = run_hook(ent, rules_file=active)
            check(f"HTML-entitas gondolatjel blokkol ({nev})", code, 2)
            check_true(f"...es a GONDOLATJEL indokkal, nem masert ({nev})",
                       "GONDOLATJEL" in (err or ""), detail=(err or "")[:120])

        # NEGATIV KONTROLL: a dekodolas nem tehet minden `&`-t gyanussa.
        amp = {"tool_name": "mcp__plugin_telegram_telegram__reply",
               "tool_input": {"text": "Szia! Kovács &amp; Társa Kft. ajánlata megérkezett."}}
        code, out, err = run_hook(amp, rules_file=active)
        check("&amp; onmagaban NEM blokkol", code, 0)

        # A SORREND KONTROLLJA: tag-kiszedes ELOSZOR, dekodolas AZUTAN. Forditva
        # egy szovegkent mutatott, escape-elt jelolo valodi tagge dekodolodna, es
        # a TAG.sub kitorolne a szoveg egy darabjat -- a kapu nem hibat jelezne,
        # hanem CSENDBEN mast vizsgalna, mint amit kuldunk.
        esc = {"tool_name": "mcp__plugin_telegram_telegram__reply",
               "tool_input": {"text": "Szia! Írd ki: &lt;b&gt;vastag&lt;/b&gt; szöveggel, köszönöm."}}
        code, out, err = run_hook(esc, rules_file=active)
        check("escape-elt jelolo NEM blokkol es nem tunik el", code, 0)

        # A FENTI SOR ONMAGABAN NEM ELEG, ES EZT SAMU MERTE MEG (#1320 review):
        # csak exit 0-t asszertal, ezert MINDKET sorrenddel zold -- vagyis nem
        # bizonyitja azt, amit a kommentje allit. Ez a fog viszont diszkriminal
        # (fuggetlenul visszamerve, True/False):
        #   HELYES sorrend  -> a dekodolt spanban OTT a tiltott jel      -> exit 2
        #   CSERELT sorrend -> a span TAGGE dekodolodik, a TAG.sub a jellel
        #                      EGYUTT torli                             -> exit 0, CSENDES atengedes
        # Vagyis pontosan az a veszely, amit a hook kommentje leir: a kapu nem
        # hibat jelez, hanem mast vizsgal, mint amit kuldunk.
        span = {"tool_name": "mcp__plugin_telegram_telegram__reply",
                "tool_input": {"text": "Szia! A jelölés: &lt;határidő — péntek&gt; formában áll, köszönöm."}}
        code, out, err = run_hook(span, rules_file=active)
        check("escape-elt SPAN-ben rejtett gondolatjel blokkol (sorrend-fog)", code, 2)
        check("...es a GONDOLATJEL indokkal", "GONDOLATJEL" in (err or ""), True)

        # --- GMAILCONNECTOR914: the claude.ai Gmail connector ----------------
        # mcp__claude_ai_Gmail__send_message carries ONE underscore before Gmail,
        # so the old (^|__)gmail__ alternative never matched and the send fell
        # through to exit 0 with no audit (measured 2026-08-30, 2026-09-08).
        for tool in ("send_message", "reply", "forward"):
            bad = {"tool_name": f"mcp__claude_ai_Gmail__{tool}",
                   "tool_input": {"to": ["a@b.hu"], "messageId": "m1", "subject": "Teszt",
                                  "body": CLEAN_HU_OK + " — mégis."}}
            code, out, err = run_hook(bad, rules_file=active)
            check(f"connector {tool} with em dash blocks (exit 2)", code, 2)
            ok = {"tool_name": f"mcp__claude_ai_Gmail__{tool}",
                  "tool_input": {"to": ["a@b.hu"], "messageId": "m1", "subject": "Teszt", "body": CLEAN_HU_OK}}
            code, out, err = run_hook(ok, rules_file=active)
            check(f"connector {tool} clean passes (exit 0)", code, 0)
        fwd = {"tool_name": "mcp__claude_ai_Gmail__forward",
               "tool_input": {"to": ["a@b.hu"], "messageId": "m1", "forwardText": "Nézd meg — fontos."}}
        code, out, err = run_hook(fwd, rules_file=active)
        check("connector forward: forwardText is audited too (exit 2)", code, 2)
        draft_only = {"tool_name": "mcp__claude_ai_Gmail__send_message", "tool_input": {"draftId": "d1"}}
        code, out, err = run_hook(draft_only, rules_file=active)
        check("connector send of a draftId: body unreadable, fail-closed (exit 2)", code, 2)
        for tool in ("search_threads", "get_thread", "label_message"):
            code, out, err = run_hook({"tool_name": f"mcp__claude_ai_Gmail__{tool}", "tool_input": {"q": "x — y"}},
                                      rules_file=active)
            check(f"connector {tool} is a read: passes untouched (exit 0)", code, 0)

        # MS365SEND1014: the ms365 send-mail body (body.Message) is audited
        # like any letter, and an unreadable one blocks.
        def ms365_payload(content, tool="mcp__ms365__send-mail", **msg_extra):
            msg = {"subject": "Teszt", "body": {"contentType": "text", "content": content},
                   "toRecipients": [{"emailAddress": {"address": "a@b.hu"}}], **msg_extra}
            return {"tool_name": tool,
                    "tool_input": {"body": {"Message": msg, "SaveToSentItems": True}}}
        code, out, err = run_hook(ms365_payload(CLEAN_HU_OK), rules_file=active)
        check("ms365 send-mail with clean copy passes (exit 0)", code, 0)
        code, out, err = run_hook(ms365_payload(CLEAN_HU_OK + " — mégis."), rules_file=active)
        check("ms365 send-mail with em dash blocks (exit 2)", code, 2)
        code, out, err = run_hook(ms365_payload(CLEAN_HU_OK, attachments=[{"name": "x"}]),
                                  rules_file=active)
        check("ms365 send-mail with an unreadable shape blocks (exit 2)", code, 2)
        code, out, err = run_hook({"tool_name": "mcp__ms365__forward-mail-message",
                                   "tool_input": {"message-id": "1",
                                                  "body": {"Comment": CLEAN_HU_OK + " — mégis."}}},
                                  rules_file=active)
        check("ms365 forward comment with em dash blocks (exit 2)", code, 2)
        # MS365GATE1015: the matcher now routes the WHOLE ms365 server here. A
        # read, and an outbound tool with no text of ours, must pass untouched:
        # the approval gate is the one that decides the send.
        for tool in ("mcp__ms365__list-mail-messages", "mcp__ms365__get-mail-message",
                     "mcp__ms365__graph-batch", "mcp__ms365__create-mail-rule",
                     "mcp__ms365__get-me"):
            code, out, err = run_hook({"tool_name": tool, "tool_input": {"message-id": "1"}},
                                      rules_file=active)
            check(f"ms365 {tool.split('__')[-1]} without our text passes the copy gate (exit 0)",
                  code, 0)
        # G3: a renamed server's send-mail is audited the same way.
        code, out, err = run_hook(ms365_payload(CLEAN_HU_OK + " — mégis.",
                                                tool="mcp__outlook__send-mail"), rules_file=active)
        check("renamed server send-mail with em dash blocks (exit 2)", code, 2)

        # --- bbc6bad4 round 3 (Viktor 50311 I1): rows his surviving mutants asked for --------------------------
        def bash(cmd):
            return {"tool_name": "Bash", "tool_input": {"command": cmd}}
        snd = "send" + "mail"
        # E15: every heredoc body of a send is audited, not only the first one (a mutant that kept the first body
        # alone let the em dash of the second through).
        two = (f"{snd} -t a@b.hu <<'A'\n{CLEAN_HU_OK}\nA\n"
               f"{snd} -t c@d.hu <<'B'\n{CLEAN_HU_OK} — mégis.\nB")
        code, out, err = run_hook(bash(two), rules_file=active)
        check("E15: the em dash only in the SECOND heredoc body of a send blocks (exit 2)", code, 2)
        code, out, err = run_hook(bash(two.replace(" — mégis.", "")), rules_file=active)
        check("E15: both bodies clean passes (exit 0)", code, 0)
        ia = "curl -s -X POST http://localhost:3420/api/messages -H 'Content-Type: application/json' --data-binary @- "
        # C07: an UNQUOTED heredoc body with a shell substitution is not read as the message (the shell rewrites it
        # first): a loud pass naming the reason, not a silent homoglyph check of the raw text.
        code, out, err = run_hook(bash(ia + '<<JSON\n{"from":"kernel","to":"klodel","content":"$(date) ok"}\nJSON'),
                                  rules_file=active)
        check("C07: unquoted heredoc + substitution on /api/messages passes (exit 0)", code, 0)
        check_true("C07: ... and says why (NEM idezett)", "NEM idezett" in out, out)
        code, out, err = run_hook(bash(ia + "<<'JSON'\n{\"from\":\"kernel\",\"to\":\"klodel\",\"content\":\"$(date) ok\"}\nJSON"),
                                  rules_file=active)
        check_true("C07: the QUOTED heredoc with the same text is read (no warning)", "NEM idezett" not in out, out)
        # C04: an empty heredoc body is a body (invalid JSON), not "no heredoc".
        code, out, err = run_hook(bash(ia + "<<'JSON'\n\nJSON"), rules_file=active)
        check_true("C04: an empty heredoc body is reported as invalid JSON, not as a missing heredoc",
                   "nem ervenyes JSON" in out and "heredoc nelkul" not in out, out)

        # --- LONGTOK1122 (Viktor 50311 B1): a token run past 32 KiB, the whole hook process -------------------
        # The approval gate's hook timeout is 10 s and a timed-out hook lets the command through; on the previous
        # head 'sendmail a@b.hu ' + 1 MB of 'w' took 9.1 s in is_send_invocation alone, and the echo shape 12.7 s
        # through the HTTP and inter-agent arms. 10 s of wall time per process is the acceptance bound (measured
        # 0.03-0.27 s on the fixed head); 3 s of the hook's own CPU (RUSAGE_CHILDREN, load-proof) is the regression
        # guard: one arm left unbounded burns 6-9 s of CPU on the 1 MB shapes.
        import resource as _resource
        import time as _time
        w1m = "w" * 1_000_000
        long_rows = [
            ("send + 1 MB word blocks (unreadable body)", f"{snd} a@b.hu {w1m}", 2, None),
            ("echo + 1 MB word passes", "echo " + w1m, 0, None),
            ("echo + 1 MB quoted string with spaces passes", "echo '" + "w " * 500_000 + "'", 0, None),
            ("Telegram API + 40 KB token fails closed", "curl -s https://api.telegram.org/botX/sendMessage -d 'text="
             + "w" * 40_000 + "'", 2, "api.telegram.org"),
            ("/api/messages + 40 KB token + lookalike blocks", ia.replace("--data-binary @- ", "-d '")
             + '{"content":"' + "w " * 40_000 + " kаrtya\"}'", 2, "homoglifa"),
            ("/api/messages + 40 KB clean token passes", ia.replace("--data-binary @- ", "-d '")
             + '{"content":"' + "w " * 40_000 + "\"}'", 0, None),
        ]
        for name, cmd, want, needle in long_rows:
            ru0 = _resource.getrusage(_resource.RUSAGE_CHILDREN)
            t0 = _time.perf_counter()
            code, out, err = run_hook(bash(cmd), rules_file=active)
            wall = _time.perf_counter() - t0
            ru1 = _resource.getrusage(_resource.RUSAGE_CHILDREN)
            cpu = (ru1.ru_utime - ru0.ru_utime) + (ru1.ru_stime - ru0.ru_stime)
            check(f"LONGTOK1122: {name}", code, want)
            check_true(f"LONGTOK1122: {name} -- under 10 s", wall < 10, f"{wall:.2f} s")
            check_true(f"LONGTOK1122: {name} -- under 3 s of hook CPU", cpu < 3, f"{cpu:.2f} s")
            if needle:
                check_true(f"LONGTOK1122: {name} -- names {needle}", needle in err, err[:200])

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {FAILS}", file=sys.stderr)
        sys.exit(1)
    print("\nAll outgoing-copy-gate tests passed.")


if __name__ == "__main__":
    main()
