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
        # 0.03-0.27 s on the fixed head); 4 s of the hook's own CPU (RUSAGE_CHILDREN) is the regression guard: one arm
        # left unbounded burns 6-9 s of CPU on the 1 MB shapes (Viktor 50318 I1: CPU time grows under load 6-10 too).
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
            # round 6 (Viktor 50350, Klodel 50352): the inter-agent arm fails closed past the bound
            ("/api/messages + 40 KB clean token fails closed", ia.replace("--data-binary @- ", "-d '")
             + '{"content":"' + "w " * 40_000 + "\"}'", 2, "KiB-nal hosszabb"),
            # Viktor 50318 B2: the shell removes the quotes, so a split target is the target; the literals of the
            # long-token arms are searched on a dequoted copy
            ("split /api/messages + 40 KB token + lookalike blocks",
             "curl -s -X POST localhost:3420/api/mess''ages -d '{\"content\":\"p\u0430ss\"}' " + "x" * 40_000,
             2, "homoglifa"),
            ("split Telegram API + 40 KB token fails closed",
             "curl -s https://api.tele''gram.org/botX/sendMessage -d 'text=" + "w" * 40_000 + "'", 2, "api.telegram.org"),
            ("/api/messages + 40 KB token + a lookalike only the shell joins (p, a, ss split by quotes)",
             'curl -s -X POST localhost:3420/api/messages -H x p""\u0430""ss ' + "x" * 40_000, 2, "homoglifa"),
            ("split /api/messages + lookalike, no long token (control: the exact reading)",
             "curl -s -X POST localhost:3420/api/mess''ages -d '{\"content\":\"p\u0430ss\"}'", 2, "homoglifa"),
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
            check_true(f"LONGTOK1122: {name} -- under 4 s of hook CPU", cpu < 4, f"{cpu:.2f} s")
            if needle:
                check_true(f"LONGTOK1122: {name} -- names {needle}", needle in err, err[:200])

        # --- LONGTOK1122 round 6 (Viktor 50330 R1, 50350 R1a/R1b): what main reads and the long arm cannot -------
        # Next to a long token every /api/messages command fails closed, whatever shape the body has; without the token
        # (the control) the short arm reads it as main does. The way out the message names (a heredoc or an @file)
        # passes a clean 40 KB body and blocks a lookalike in it: the bound does not count a heredoc body.
        lk = os.path.join(tmp, "r6-lookalike.json")
        with open(lk, "w", encoding="utf-8") as fh:
            fh.write('{"to":"klodel","content":"p\u0430trik"}')
        os.makedirs(os.path.join(tmp, "r6 sp"), exist_ok=True)
        lk_sp = os.path.join(tmp, "r6 sp", "body.json")
        with open(lk_sp, "w", encoding="utf-8") as fh:
            fh.write('{"to":"klodel","content":"p\u0430trik"}')
        big_clean = os.path.join(tmp, "r6-big-clean.json")
        with open(big_clean, "w", encoding="utf-8") as fh:
            fh.write('{"to":"klodel","content":"' + "w" * 40_000 + '"}')
        h = "curl -s -X POST localhost:3420/api/messages -H 'Content-Type: application/json' "
        jesc = "\\u0430"  # a JSON escape in the command text: six ASCII characters
        r6_rows = [
            ("inline -d with a JSON-escaped lookalike", h + "-d '{\"content\":\"p" + jesc + "trik\"}'", 2),
            ("@file with a lookalike", h + "--data-binary @" + lk, 2),
            ("@- heredoc with a JSON-escaped lookalike", h + "--data-binary @- <<'JSON'\n{\"content\":\"p" + jesc
             + "trik\"}\nJSON", 2),
            ("inline lookalike next to a decoy unreadable @ref", h + "-d '{\"content\":\"p\u0430trik, lasd -d @/nope/m.json\"}'",
             2),
            ("double-quoted @path with a space", h + "--data-binary \"@" + lk_sp + "\"", 2),
            ("clean inline body", h + "-d '{\"content\":\"patrik\"}'", 0),
        ]
        for name, cmd, ctl in r6_rows:
            for pad_name, pad in (("40 000 character token", " -H 'X-Pad: " + "x" * 40_000 + "'"),
                                  ("32 769 character token", " -H X-Pad:" + "x" * (32_769 - 6)),
                                  ("no long token (control)", "")):
                full = cmd.replace(" -H 'Content-Type", pad + " -H 'Content-Type", 1) if pad else cmd
                code, out, err = run_hook(bash(full), rules_file=active)
                want = ctl if not pad else 2
                check(f"LONGTOK1122 r6: {name}, {pad_name}", code, want)
                if pad:
                    check_true(f"LONGTOK1122 r6: {name}, {pad_name} -- names the bound", "KiB-nal hosszabb" in err,
                               err[:200])
        # the bound itself: 32 768 characters is still read (the short arm), 32 769 fails closed
        code, out, err = run_hook(bash(h + "-d '{\"content\":\"patrik\"}' -H X-Pad:" + "x" * (32_768 - 6)),
                                  rules_file=active)
        check("LONGTOK1122 r6: a 32 768 character token is still read (clean passes)", code, 0)
        # the way out the message names
        code, out, err = run_hook(bash(h + "--data-binary @- <<'JSON'\n{\"content\":\"" + "w" * 40_000
                                       + "\"}\nJSON"), rules_file=active)
        check("LONGTOK1122 r6: a heredoc with a 40 KB clean word passes (the bound does not count it)", code, 0)
        code, out, err = run_hook(bash(h + "--data-binary @- <<'JSON'\n{\"content\":\"" + "w" * 40_000
                                       + " p\u0430trik\"}\nJSON"), rules_file=active)
        check("LONGTOK1122 r6: a heredoc with a 40 KB word and a lookalike blocks", code, 2)
        check_true("LONGTOK1122 r6: ... as a homoglyph, not as the bound", "VEGYES" in err, err[:200])
        code, out, err = run_hook(bash(h + "--data-binary @" + big_clean), rules_file=active)
        check("LONGTOK1122 r6: an @file with a 40 KB clean word passes", code, 0)

        # --- KNOWN-LIMIT rows (Viktor 50375, independent probe e0b9f9deb31c): each pins today's exit 0 of a documented
        # Known limit (the module docstring names the label and its word; main lets all 18 through too; follow-up card
        # 474437df). The inputs are the probe's builders, verbatim. A later fix turns its row red on purpose: then drop
        # the label here and in the docstring.
        kl_hom = "H\u0435llo"
        kl_u = "http://127.0.0.1:9/api/messages"
        kl_hdr = "-H 'Content-Type: application/json'"

        def kl_sq(x):
            return "'" + x.replace("'", "'\\''") + "'"

        def kl_body(content):
            return json.dumps({"from": "viktor", "to": "klodel", "content": content}, ensure_ascii=False)

        def kl_curl(rest, url=kl_u):
            return "curl -s -X POST %s %s %s" % (url, kl_hdr, rest)
        kl_mixed = kl_body(kl_hom + " vilag")
        kl_line = kl_curl("-d " + kl_sq(kl_mixed))
        kl_lp = ": %s; " % ("w" * 40000)
        kl_dir = os.path.join(tmp, "known-limit")
        os.makedirs(kl_dir, exist_ok=True)
        with open(os.path.join(kl_dir, "nl.json"), "w", encoding="utf-8") as fh:
            fh.write('{"from":"viktor","to":"klodel","content":"Hel\n\u043b\u043e vilag"}\n')
        known_limit_rows = [
            ("hd-unclosed-short-mixed", kl_curl("--data-binary @- <<'JSON'\n" + kl_mixed)),
            ("fakehd-quoted-short-mixed", "echo '<<E' >/dev/null\n" + kl_line + "\nE"),
            ("fakehd-quoted-long-mixed", "echo '<<E' >/dev/null\n"
             + kl_curl("-H 'X-Pad: %s' -d %s" % ("w" * 40000, kl_sq(kl_mixed))) + "\nE"),
            ("fakehd-comment-mixed", "# <<E\n" + kl_line + "\nE"),
            ("fakehd-arith-mixed", "echo $((1<<E)) >/dev/null\n" + kl_line + "\nE"),
            ("fakehd-herestring-mixed", "cat <<<E >/dev/null\n" + kl_line + "\nE"),
            ("tgt-dotseg-short-mixed", kl_curl("-d " + kl_sq(kl_mixed), "http://127.0.0.1:9/api/./messages")),
            ("tgt-dotseg-long-mixed", kl_lp + kl_curl("-d " + kl_sq(kl_mixed), "http://127.0.0.1:9/api/./messages")),
            ("KNOWN-K1-tgt-emptyvar-long-mixed",
             kl_lp + kl_curl("-d " + kl_sq(kl_mixed), "http://127.0.0.1:9/api/mess${E}ages")),
            ("KNOWN-K2-tgt-ansic-long-mixed",
             kl_lp + kl_curl("-d " + kl_sq(kl_mixed), "http://127.0.0.1:9/api/mess$'\\x61'ges")),
            ("KNOWN-K3-tgt-brace-long-mixed",
             kl_lp + kl_curl("-d " + kl_sq(kl_mixed), "http://127.0.0.1:9/api/mess{a,}ges")),
            ("tgt-curlglob-long-mixed",
             kl_lp + kl_curl("-d " + kl_sq(kl_mixed), "'http://127.0.0.1:9/api/{messages}'")),
            ("tgt-fragment-short-mixed", kl_curl("-d " + kl_sq(kl_mixed), "http://127.0.0.1:9/api/messages#x")),
            ("out-file-nlstrip-mixed", kl_curl("-d @nl.json")),
            ("short-cluster-sd-mixed", "curl -sd %s %s" % (kl_sq(kl_mixed), kl_u)),
            ("short-bash-c-mixed", "bash -c %s" % kl_sq(kl_curl("-d " + kl_sq(kl_mixed)))),
            ("short-json-concat-mixed", "curl -s %s --json %s --json %s" % (
                kl_u, kl_sq('{"from":"viktor","to":"klodel",'), kl_sq('"content":"' + kl_hom + '"}'))),
        ]
        kl_changed = []
        for label, cmd in known_limit_rows:
            code, out, err = run_hook(bash(cmd), rules_file=active, cwd=kl_dir)
            if code != 0:
                kl_changed.append(f"{label} (exit {code})")
        check("KNOWN-LIMIT (Known limits, card 474437df): the 17 documented inputs still pass (exit 0); a changed "
              "row means a limit was closed or moved", kl_changed, [])
        check("KNOWN-LIMIT: the list has the 17 documented labels", len(known_limit_rows), 17)
        # card 64d10325 (SENDCONT1122: the mask drops a backslash-newline) closed the probe's tgt-bsnl-short-mixed
        code, out, err = run_hook(bash(kl_curl("-d " + kl_sq(kl_mixed), "http://127.0.0.1:9/api/mess\\\nages")),
                                  rules_file=active, cwd=kl_dir)
        check("KNOWN-LIMIT closed: a backslash-newline inside the target URL, a lookalike body blocks", code, 2)
        # --- SENDMODES1122 (card 64d10325 round 4): what only the python twin reads ---------------------------------
        # The shared list (send-invocation-cases.json) binds both twins; these two python readings have no JS twin:
        # "legacy" is this twin's main (shlex reads the comment, so a mid-word # cuts an open quote, and the parse
        # error falls back to the literals: main said send), and past _MULTI_READING_MAX the extra readings give way
        # to the long-token literal search (the JS twin runs every reading at any length).
        import importlib.util as _ilu
        _sp = _ilu.spec_from_file_location("occ_gate_modes", HOOK)
        _g = _ilu.module_from_spec(_sp)
        _sp.loader.exec_module(_g)
        legacy_only = "echo a#'\nsendmail a@b.c'"
        check("SENDMODES1122: main's reading is kept (a mid-word # cuts the quote open: main audited it)",
              _g.is_send_invocation(legacy_only), True)
        check("SENDMODES1122: ... and only the legacy reading sees it (A, PP, blind, legacy)",
              [_g._is_send_in_reading(legacy_only, 0, m) for m in ("A", "PP", "blind", "legacy")],
              [False, False, False, True])
        pad = "echo " + "ab " * 90_000
        check_true("SENDMODES1122: the large command is past _MULTI_READING_MAX",
                   len(pad) > _g._MULTI_READING_MAX, str(len(pad)))
        check("SENDMODES1122: past _MULTI_READING_MAX a send only a comment reading names is still audited",
              _g.is_send_invocation("true # sendmail a@b.c\n" + pad), True)
        check("SENDMODES1122: ... which the A reading alone does not see",
              _g._is_send_in_reading("true # sendmail a@b.c\n" + pad, 0, "A"), False)
        check("SENDMODES1122: ... and a large command with a comment and no sender name stays clean",
              _g.is_send_invocation("true # a note\n" + pad), False)

        # --- SENDFANOUT1123 (round 5): the readings multiply with each -c / eval level; one call has a read budget --
        # On the round 4 head the two-level shape below took 12.2 s (eval) and 13.1 s (bash -c), main 0.14 s; the
        # hook timeout is 10 s and a timed-out hook lets the command through. 4 s of CPU is the guard (measured
        # ~1.1 s with the budget); past the budget the command is audited.
        import time as _t2
        for _w in ("eval", "bash -c"):
            _l1 = _w + " \\\": " + "x " * 40 + "# ((\\\"; "
            _seg = _w + " \"" + _l1 * 8 + "\"\n"
            _two = _seg * (250_000 // len(_seg))
            _c0 = _t2.process_time()
            _v = _g.is_send_invocation(_two)
            _cpu = _t2.process_time() - _c0
            check("SENDFANOUT1123: two-level %s fan-out (250 KB) is audited once the budget is spent" % _w, _v, True)
            check_true("SENDFANOUT1123: ... within 4 s of CPU (%s)" % _w, _cpu < 4.0, "%.2f s" % _cpu)
        _flat = (": " + "abcdefg " * 12 + "\n") * (4 * 1024 * 1024 // 98)
        check("SENDFANOUT1123: a flat 4 MiB command with no sender is not audited (one reading always fits)",
              _g.is_send_invocation(_flat), False)
        check("SENDFANOUT1123: ... with a heredoc too (its strict pass fits as well)",
              _g.is_send_invocation(_flat + "cat <<E\nx\nE\n"), False)
        check("SENDFANOUT1123: a one-level eval with a send still reads the send, not the budget",
              _g.is_send_invocation("eval 'true # ((x\nsendmail a@b.c'"), True)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {FAILS}", file=sys.stderr)
        sys.exit(1)
    print("\nAll outgoing-copy-gate tests passed.")


if __name__ == "__main__":
    main()
