#!/usr/bin/env python3
"""Shared email-payload extraction (EMAILKAPU901 PR1).

Single source of truth for recovering the OUTGOING LETTER (recipients, subject,
body) from a send invocation, used by BOTH gates:
  - scripts/hooks/outgoing-copy-gate.py (copy audit: accents, names, em dash)
  - the level-2 email approval gate (PR2): content-hash anchor over
    to + cc + subject + body -- the approval record pins the EXACT letter, and
    a send is allowed only on an exact match.

The extraction boundary (Marveen, msg 17900) is deterministic-or-deny:
  - readable literal (--body "...", < /abs/path, heredoc, MCP fields) -> text
  - anything shell-expanded at run time ($(cat), `...`, $VAR, unresolvable
    path, pipe) -> unreadable_reason, and the CALLER must fail closed.
The SAME boundary applies to recipients (msg 17936): a --to that comes from a
variable is not "approximately right", it is unreadable -> deny. A body+subject
hash alone would let an approved letter be re-sent to a DIFFERENT recipient.

collect_bash_body / collect_mcp_body moved here VERBATIM from
outgoing-copy-gate.py (behavior-neutral; parity proven byte-for-byte against a
golden captured from the pre-move code -- scripts/__tests__/email-extract-parity.test.py).
"""
import json
import os
import re
import unicodedata

def collect_bash_body(cmd: str):
    """Return (text, unreadable_reason). text is '' when nothing was recovered."""
    parts = []
    for m in re.finditer(r"--(?:body|subject)[= ]+(\"([^\"]*)\"|'([^']*)'|(\S+))", cmd):
        val = m.group(2) or m.group(3) or m.group(4) or ""
        # A shell-expanded --body ($(cat f), `cat f`, $VAR) reaches this hook
        # UNEXPANDED: what we would audit is the literal command text, not the
        # letter. That is worse than useless -- it fires on words that happen to
        # sit in the PATH while the real copy goes uninspected. Measured
        # 2026-08-11 on a live customer letter: `--body "$(cat .../hidli_zaro_
        # level.txt)"` blocked on "level" from the FILENAME, and the letter
        # itself was never read. Same fail-closed rule as the `<` branch below.
        if re.search(r"\$\(|`|\$\{?\w", val):
            return ("\n".join(parts),
                    "a --body shell-behelyettesitest tartalmaz, amit a hook nem old fel "
                    f"({val[:60]}...) -- igy a parancs szoveget vizsgalnam, nem a levelet")
        parts.append(val)
    # heredoc payloads sit inline in the command string
    for m in re.finditer(r"<<-?\s*'?(\w+)'?\n(.*?)\n\1", cmd, re.S):
        parts.append(m.group(2))
    # A single `<` only. Without the lookarounds a heredoc (`<<'EOF'`) matches
    # here and the quoted delimiter is taken for a filename -- caught by the
    # first live probe of this gate, which blocked with "'EOF': No such file".
    # `(?<![<=])`: a `=<` is curl's `-F "name=<file"` (read by the file-body
    # forms below), not a shell redirect; the quoted form would otherwise be
    # taken as a redirect to a path ending in the closing quote.
    redirect = re.search(r"(?<![<=])<(?!<)\s*([^\s|;&<>]+)", cmd)
    if redirect:
        raw = redirect.group(1)
        path = os.path.expandvars(os.path.expanduser(raw))
        if "$" in path:
            return ("\n".join(parts), f"a torzs egy fel nem oldhato utvonalrol jon ({raw})")
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                parts.append(fh.read())
        except OSError as exc:
            return ("\n".join(parts), f"a torzs-fajl nem olvashato ({path}: {exc})")
    # GATEBINVAK916: curl's `@file` payload (-d/--data/--data-binary/--json/
    # --data-urlencode @path). Before this branch the body of such a call was
    # never read: on the Resend path that made every @file letter -- clean ones
    # too -- fail closed with the generic "no inspectable text" reason, and the
    # real content was never audited. --data-raw is deliberately NOT here: it
    # sends a literal "@path", it reads no file.
    # Every curl/wget shape that sends a FILE as the body, each with its own
    # label: an unreadable one then says WHICH shape failed, instead of the
    # generic "no inspectable text" that this change exists to retire
    # (Marveen's #1507 review: `--data-urlencode name@file` LOOKED handled --
    # the flag was in the @ regex -- but the name@ form never matched).
    for label, rx in _FILE_BODY_FORMS:
        for m in rx.finditer(cmd):
            ref = m.group(1)
            if ref in ("-", "."):
                # stdin: a heredoc is already in `parts`; a pipe is not readable.
                if not parts:
                    return ("", f"a torzs stdin-rol jon ({label} {ref}), heredoc nelkul -- a hook nem latja")
                continue
            text, reason = _read_body_file(ref, label)
            if reason:
                return ("\n".join(parts), reason)
            parts.append(text)
    if not parts and re.search(r"\|\s*(python3?|node|tsx)?[^|]*send", cmd):
        return ("", "a torzs egy pipe-bol jon, a hook nem latja")
    return ("\n".join(parts), None)


# GATEBINVAK916: the file-body shapes. Each flag must stand alone (leading
# space or start), so an address like x@y.hu or an @ inside a quoted payload is
# never taken for a file. Measured list (Marveen's #1507 review, against the
# gate's own _CURL_BODY_OPTS): the six @-flags, plus the five shapes that also
# send a FILE but were not read: --data-urlencode name@file, -F/--form
# name=@file or name=<file, wget --post-file / --body-file, curl -T.
# NOT here, deliberately: --data-raw (sends a literal "@path", reads nothing)
# and --form-string (literal). The inline literal flags (-d '...',
# --post-data '...') stay outside this branch as before.
_REF = r"['\"]?([^\s'\"|;&<>]+)"
_FILE_BODY_FORMS = (
    ("@", re.compile(
        r"(?:^|\s)(?:-d|--data|--data-binary|--data-ascii|--json|--data-urlencode)"
        r"(?:=|\s+|(?<=-d))['\"]?@([^\s'\"|;&<>]+)")),
    ("--data-urlencode name@", re.compile(
        r"(?:^|\s)--data-urlencode(?:=|\s+)['\"]?[A-Za-z0-9_.-]+@([^\s'\"|;&<>]+)")),
    ("-F/--form name=@|<", re.compile(
        r"(?:^|\s)(?:-F|--form)(?:=|\s+)['\"]?[^\s'\"=]+=[@<]([^\s'\";|&<>]+)")),
    ("wget --post-file/--body-file", re.compile(
        r"(?:^|\s)--(?:post|body)-file(?:=|\s+)" + _REF)),
    ("curl -T/--upload-file", re.compile(
        r"(?:^|\s)(?:-T|--upload-file)(?:=|\s+)" + _REF)),
)


def _read_body_file(ref: str, label: str):
    """(text, unreadable_reason) for a file named as a request body."""
    shown = f"@{ref}" if label == "@" else f"{label} {ref}"  # as the user typed it
    path = os.path.expandvars(os.path.expanduser(ref))
    if "$" in path:
        return ("", f"a torzs egy fel nem oldhato utvonalrol jon ({shown})")
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            data = fh.read()
    except OSError as exc:
        return ("", f"a torzs-fajl ({shown}) nem olvashato ({path}: {exc})")
    return _payload_text(data, ref)


# The prose fields of a JSON payload. A JSON body is audited through these,
# DECODED: the raw file would show "\u00e1" for "a" with an accent, and the
# accent audit would read escape sequences instead of the letter.
_PAYLOAD_TEXT_FIELDS = ("subject", "text", "html", "body", "content", "message")


def _payload_text(data: str, raw: str):
    """(text, unreadable_reason) for a payload read from an @file."""
    try:
        obj = json.loads(data)
    except ValueError:
        return (data, None)  # not JSON: the file IS the text
    if not isinstance(obj, dict):
        return ("", f"a torzs-fajl (@{raw}) JSON, de nem objektum -- a hook nem tudja, mi benne a szoveg")
    got = [str(obj[f]) for f in _PAYLOAD_TEXT_FIELDS if obj.get(f)]
    if not got:
        return ("", f"a torzs-fajl (@{raw}) JSON-jaban nincs ismert szoveg-mezo "
                    f"({', '.join(_PAYLOAD_TEXT_FIELDS)})")
    return ("\n".join(got), None)


def collect_mcp_body(tool_input: dict):
    fields = ("body", "text", "html", "htmlBody", "message", "subject", "content", "forwardText")
    got = [str(tool_input[f]) for f in fields if tool_input.get(f)]
    return "\n".join(got)

# --- recipients (new in PR1; consumed by the PR2 approval gate) --------------
# Same unreadable boundary as the body branches above: shell substitution in a
# recipient value means the hook would hash the COMMAND TEXT while the real
# recipient is decided at run time -- deny, never approximate.
_SHELL_SUBST = re.compile(r"\$\(|`|\$\{?\w")


def collect_bash_recipients(cmd: str):
    """Return (to, cc, bcc, unreadable_reason); recipient lists hold literal
    values. bcc is part of the envelope since EMAILBCCHORGONY903: an anchor
    that ignores it lets an approved letter be re-sent WITH an added --bcc,
    delivering to a recipient nobody approved."""
    to, cc, bcc = [], [], []
    buckets = {"to": to, "cc": cc, "bcc": bcc}
    for m in re.finditer(r"--(to|cc|bcc)[= ]+(\"([^\"]*)\"|'([^']*)'|(\S+))", cmd):
        val = m.group(3) or m.group(4) or m.group(5) or ""
        if _SHELL_SUBST.search(val):
            return (to, cc, bcc,
                    f"a --{m.group(1)} shell-behelyettesitest tartalmaz, amit a hook "
                    f"nem old fel ({val[:60]}...) -- a cimzett futasidoben dol el")
        buckets[m.group(1)].append(val)
    return (to, cc, bcc, None)


def collect_mcp_recipients(tool_input: dict):
    """Return (to, cc, bcc, unreadable_reason). Values are kept RAW (no
    splitting, no lowercasing): the hash anchor needs exact bytes, not address
    semantics. bcc: see collect_bash_recipients (EMAILBCCHORGONY903)."""
    def norm(v):
        if v is None or v == "":
            return []
        if isinstance(v, (list, tuple)):
            return [str(x) for x in v]
        return [str(v)]
    return (norm(tool_input.get("to")), norm(tool_input.get("cc")),
            norm(tool_input.get("bcc")), None)


# The claude.ai Gmail connector's send-shaped tools (mcp__claude_ai_Gmail__*):
# no "send_email" in the name, so the name-based test above never saw them.
CONNECTOR_SEND_RE = re.compile(r"gmail__(reply|reply_all|send_message|forward)$", re.I)

# MS365SEND1014 + MS365GATE1015 (Viktor G1/G3, card d85d38c3): the
# @softeria/ms-365-mcp-server tools. The first version named six Mail.Send tools,
# a BLOCKLIST -- and the 0.162.0 server has many more ways out (shared-mailbox
# reply/forward/send, graph-batch, a forwarding mail rule, meeting requests, chat
# messages, shares, a webhook subscription). So the classification is inverted:
#   - send-mail is the one anchored send (the whole envelope is in its input);
#   - an OUTBOUND operation is unanchorable on ANY server name (a renamed server
#     stays gated, G3; a false positive is a deny, never an allow);
#   - on a server whose name carries ms365 / ms-365, everything that is not on the
#     read/draft allowlist is unanchorable too -- an unknown tool is a deny.
# The lists live in ms365-tool-policy.json, shared with email-send-gate.mjs and
# the hook matcher. An unreadable policy file is fail-closed: every ms365 tool and
# the floor of known send operations below are denied.
_MS365_POLICY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "ms365-tool-policy.json")
_MS365_SERVER_RE = re.compile(r"ms-?365", re.I)
# Used only when the policy file cannot be read: the six send tools the first
# version knew, so a broken file can never make the gate blinder than before.
_MS365_OUTBOUND_FLOOR = frozenset({
    "send-mail", "send-draft-message", "reply-mail-message", "reply-all-mail-message",
    "forward-mail-message", "send-shared-mailbox-mail"})


def _load_ms365_policy():
    """(read_draft, anchored_send, outbound, error). On any fault the sets are
    empty except the outbound floor, and error says why."""
    try:
        with open(_MS365_POLICY_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        lists = [data[k] for k in ("read_draft", "anchored_send", "outbound")]
        if not all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in lists):
            raise ValueError("a listak nem szoveg-listak")
        read_draft, anchored, outbound = (frozenset(v) for v in lists)
        return read_draft, anchored, outbound | _MS365_OUTBOUND_FLOOR, None
    except Exception as exc:  # noqa: BLE001 -- fail-closed below
        return frozenset(), frozenset(), _MS365_OUTBOUND_FLOOR, repr(exc)


_MS365_READ_DRAFT, _MS365_ANCHORED, _MS365_OUTBOUND, MS365_POLICY_ERROR = _load_ms365_policy()


def _split_mcp_name(tool_name):
    """(server, operation) of an mcp__<server>__<operation> name, else None."""
    name = str(tool_name or "")
    if not name.startswith("mcp__"):
        return None
    server, sep, op = name[5:].rpartition("__")
    return (server, op) if sep and server and op else None


def ms365_class(tool_name):
    """'send' (anchored send-mail), 'unanchorable' (deny below level 3),
    'read' (allowlisted read/draft) or None (not an ms365 tool)."""
    parts = _split_mcp_name(tool_name)
    if not parts:
        return None
    server, op = parts
    ms365_server = bool(_MS365_SERVER_RE.search(server))
    # On any server name (G3): a renamed server's send-mail is still anchored.
    # Without the policy file the anchored set is empty, and send-mail falls to
    # the outbound floor -- denied.
    if op in _MS365_ANCHORED:
        return "send"
    if op in _MS365_OUTBOUND:
        return "unanchorable"
    if ms365_server:
        return "read" if op in _MS365_READ_DRAFT else "unanchorable"
    return None


def is_ms365_send(tool_name):
    return ms365_class(tool_name) == "send"


def is_ms365_unanchorable(tool_name):
    return ms365_class(tool_name) == "unanchorable"


def ms365_unanchorable_reason(tool_name):
    if MS365_POLICY_ERROR:
        return ("ms365: a tool-szabalyzat (ms365-tool-policy.json) nem olvashato "
                f"({MS365_POLICY_ERROR}) -- fail-closed, minden ms365 hivas tiltott")
    parts = _split_mcp_name(tool_name)
    op = parts[1] if parts else str(tool_name)
    if op in _MS365_OUTBOUND:
        return (f"ms365: a(z) {op} kifele visz (level, meghivo, uzenet, megosztas, "
                "szabaly vagy webhook), a cimzettet uzenet-azonositoval vagy a szerver "
                "donti el, ezert levelre szolo jovahagyas nem kotheto hozza -- csak a "
                "send-mail hasznalhato")
    return (f"ms365: a(z) {op} nincs az olvaso/piszkozat engedelylistan "
            "(ms365-tool-policy.json read_draft) -- ismeretlen ms365 tool, tiltva")


# The server merges a top-level argument whose name is a body field into the
# request body, and its message schema is passthrough: any Graph property
# (replyTo, attachments, headers, extended properties, from) reaches the wire.
# So the readable shape is an ALLOWLIST, and anything outside it is unreadable.
_MS365_TOP_KEYS = {"body"}
_MS365_BODY_KEYS = {"Message", "SaveToSentItems"}
_MS365_MESSAGE_KEYS = {"subject", "body", "toRecipients", "ccRecipients",
                       "bccRecipients", "importance"}
_MS365_RECIPIENT_FIELDS = (("to", "toRecipients"), ("cc", "ccRecipients"),
                           ("bcc", "bccRecipients"))


# G2 (Viktor, CWE-436): the address must be a bare addr-spec. The field is free
# text on the wire, and "balazs@myshp.hu (evil@x.com)" re-parses to the standing
# address through an RFC comment -- the gate would then judge a string other
# than the one Exchange receives. The name may not carry a control character or
# angle brackets: it is shown to the approver next to the address.
# G2b (Viktor, CWE-451/176): the approver must see what Exchange receives. The
# address is printable ASCII only (no zero-width, no homoglyph, no accented
# local part), and the name carries no format/control/separator character (bidi
# override, zero-width) and no , @ < > that could read as a second address.
_MS365_ADDR_RE = re.compile(r'^[^\s<>(),;:"\[\]\\]+@[^\s<>(),;:"\[\]\\]+$')
_MS365_ADDR_ASCII_RE = re.compile(r"^[\x21-\x7e]+$")
_MS365_NAME_BAD_CHARS = frozenset(",@<>")
_MS365_NAME_BAD_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})


# I9 (Viktor): a compatibility form reads as its ASCII twin (fullwidth U+FF20
# "＠", U+FF0C "，", U+FF1C "＜"), so the name is checked in its NFKC form too.
def _ms365_name_bad(name):
    return any(ch in _MS365_NAME_BAD_CHARS
               or unicodedata.category(ch) in _MS365_NAME_BAD_CATEGORIES
               for ch in name + unicodedata.normalize("NFKC", name))


def _ms365_recipients(raw, field):
    """(display, addresses, unreadable_reason) for one Graph recipient list.
    Each entry must be {"emailAddress": {"address": str, "name"?: str}} and
    nothing else. display keeps the name, because it is in the header the
    recipient sees (and in the hash anchor); addresses are the raw address
    fields, which the standing-recipient check compares (never a re-parse)."""
    if raw is None:
        return [], [], None
    if not isinstance(raw, list):
        return [], [], f"a {field} nem lista"
    out, addrs = [], []
    for item in raw:
        ea = item.get("emailAddress") if isinstance(item, dict) else None
        if not isinstance(ea, dict) or set(item) != {"emailAddress"} \
                or not set(ea) <= {"address", "name"}:
            return [], [], f"a {field} egy eleme nem {{emailAddress: {{address, name}}}} alaku"
        addr, name = ea.get("address"), ea.get("name")
        if not isinstance(addr, str) or not addr.strip() \
                or (name is not None and not isinstance(name, str)):
            return [], [], f"a {field} egy elemeben nincs olvashato cim"
        if not _MS365_ADDR_RE.match(addr) or not _MS365_ADDR_ASCII_RE.match(addr):
            return [], [], (f"a {field} egy cime nem csupasz, ASCII e-mail-cim ({addr[:60]!r}); "
                            "komment, nev, tobb cim, szokoz, ekezet vagy lathatatlan "
                            "karakter nem lehet benne")
        if name is not None and _ms365_name_bad(name):
            return [], [], (f"a {field} egy neveben vezerlo-, formazo- vagy lathatatlan "
                            "karakter, vagy , @ < > van")
        out.append(f"{name} <{addr}>" if name else addr)
        addrs.append(addr)
    return out, addrs, None


def collect_ms365_envelope(tool_input):
    """Envelope of an ms365 send-mail call, or an unreadable_reason (the caller
    denies). Same dict as collect_email_envelope; text is subject + body content,
    the same subject/body pair the copy gate audits."""
    empty = {"to": [], "cc": [], "bcc": [], "text": ""}

    def bad(reason):
        return {**empty, "unreadable_reason": "ms365 send-mail: " + reason}

    ti = tool_input if isinstance(tool_input, dict) else {}
    extra = set(ti) - _MS365_TOP_KEYS
    if extra:
        return bad(f"ismeretlen felso szintu mezo ({', '.join(sorted(extra))}); "
                   "csak a body.Message alak olvashato")
    body = ti.get("body")
    if not isinstance(body, dict) or not isinstance(body.get("Message"), dict):
        return bad("nincs body.Message objektum")
    extra = set(body) - _MS365_BODY_KEYS
    if extra:
        return bad(f"ismeretlen body-mezo ({', '.join(sorted(extra))})")
    # The server's schema defaults SaveToSentItems to FALSE: a letter sent that
    # way leaves no copy in Sent Items, i.e. no trace in the mailbox the owner
    # reads. The flag has to be an explicit true.
    if body.get("SaveToSentItems") is not True:
        return bad("a SaveToSentItems nem explicit true (enelkul a level nem "
                   "kerul az Elkuldott elemek koze)")
    msg = body["Message"]
    extra = set(msg) - _MS365_MESSAGE_KEYS
    if extra:
        return bad(f"a Message nem engedett mezot tartalmaz ({', '.join(sorted(extra))}); "
                   "csatolmany, valaszcim, fejlec es felado nem horgonyozhato")
    env = dict(empty)
    env["addrs"] = {}
    for key, field in _MS365_RECIPIENT_FIELDS:
        display, addrs, reason = _ms365_recipients(msg.get(field), field)
        if reason:
            return bad(reason)
        env[key] = display
        env["addrs"][key] = addrs
    subject = msg.get("subject")
    if subject is not None and not isinstance(subject, str):
        return bad("a subject nem szoveg")
    mbody = msg.get("body")
    content = ""
    if mbody is not None:
        if not isinstance(mbody, dict) or not set(mbody) <= {"contentType", "content"}:
            return bad("a Message.body nem {contentType, content} alaku")
        ctype = mbody.get("contentType", "text")
        if not isinstance(ctype, str) or ctype.lower() not in ("text", "html"):
            return bad("a contentType csak text vagy html lehet")
        content = mbody.get("content") or ""
        if not isinstance(content, str):
            return bad("a body.content nem szoveg")
    importance = msg.get("importance")
    if importance is not None and importance not in ("low", "normal", "high"):
        return bad("az importance csak low, normal vagy high lehet")
    # Body first, subject last: the order collect_mcp_body uses.
    env["text"] = "\n".join(p for p in (content, subject or "") if p)
    env["unreadable_reason"] = None
    return env


def collect_email_envelope(tool_name: str, tool_input: dict):
    """PR2 entry point: one dict for the recipient+content hash anchor (to/cc/bcc/text), built from the
    SAME collectors the copy gate runs (no second extraction implementation).
    Returns {"to", "cc", "bcc", "text", "unreadable_reason"}; text is the combined
    subject+body exactly as the copy gate audits it. The CALLER decides policy
    (e.g. an empty recipient list on a send is itself grounds to deny)."""
    if re.search(r"send_email", tool_name or "", re.I) or CONNECTOR_SEND_RE.search(tool_name or ""):
        ti = tool_input if isinstance(tool_input, dict) else {}
        text = collect_mcp_body(ti)
        to, cc, bcc, reason = collect_mcp_recipients(ti)
        # A connector reply/forward addresses the ORIGINAL message: its
        # recipient is fixed by messageId, not by a `to` field, so the id is
        # the recipient anchor (GMAILCONNECTOR914). Same bytes-exact rule as
        # the addresses: an approval for one message cannot answer another.
        if not to and ti.get("messageId"):
            to = [f"messageId:{ti['messageId']}"]
    elif is_ms365_send(tool_name):
        return collect_ms365_envelope(tool_input)
    elif is_ms365_unanchorable(tool_name):
        return {"to": [], "cc": [], "bcc": [], "text": "",
                "unreadable_reason": ms365_unanchorable_reason(tool_name)}
    elif tool_name == "Bash":
        cmd = str((tool_input or {}).get("command") or "") if isinstance(tool_input, dict) else ""
        text, reason = collect_bash_body(cmd)
        if not reason:
            to, cc, bcc, reason = collect_bash_recipients(cmd)
        else:
            to, cc, bcc = [], [], []
    else:
        return {"to": [], "cc": [], "bcc": [], "text": "",
                "unreadable_reason": f"nem email-kuldo tool ({tool_name!r})"}
    return {"to": to, "cc": cc, "bcc": bcc, "text": text, "unreadable_reason": reason}
