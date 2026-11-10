# Git force-push guard

Marveen agents run autonomously, often with shell access and the ability to push
to git, so a prompt-injected or simply mistaken agent can rewrite shared history.
This guard reduces that blast radius without changing how the fleet works.

## What it does

`scripts/install-git-guard-hook.sh` installs a `pre-push` hook that **refuses a
non-fast-forward (force / rebase / amend) push to `main` or `master`**. Normal
fast-forwards and merge commits pass untouched, and every other ref (`develop`,
feature branches, fork branches, including `--force-with-lease` to those) is
unaffected: only history rewrites of a protected branch are blocked.

It is named `install-*-hook.sh`, so `scripts/sync-hooks.sh` (and the dashboard
update flow) run it automatically. It composes with an existing `pre-push` hook
(e.g. a secret scanner) by moving it under `.git/hooks/pre-push.d/` and adding a
small dispatcher that feeds the ref list to every sub-hook.

```bash
scripts/install-git-guard-hook.sh   # runs automatically on update; manual run also works
```

Override an intentional rewrite of a protected branch:

```bash
ALLOW_FORCE_PUSH=1 git push ...
```

# Bash egress deny rules

`scripts/hooks/egress-gate.mjs` compares a URL against the allowlist, but it is
wired as a `PreToolUse` hook with matcher `WebFetch` **only**. Bash was never
ungated (`outgoing-copy-gate.py` and `email-approval-gate.py` on the main agent,
`email-send-gate.mjs` and `self-pace-gate.mjs` on sub-agents) but none of those
gates looks at the destination host, so a shell `curl` never met the allowlist.
The realistic threat is not a malicious agent: it is a fetched page telling an
agent to run a `curl`, which is why the quarantine-reader exists in the first
place.

## What it does

`BASH_EGRESS_DENY` in `src/web/agent-scaffold.ts` is the single source of truth
for the EGRESS part of `permissions.deny`, and it lands in **every** agent's
`settings.json` by three routes:

- on spawn, via `writeAgentSettingsFromProfile()`,
- on server startup, via `ensureBashEgressDeny()` (existing fleet, and the main
  agent -- see the scope note below),
- on scaffold, via `templates/settings.json.template` (so the next agent created
  starts gated -- a parity test keeps the template and the constant in step).

It is **not** the only list any more: since DENYARGS925 a second constant, the
fleet deny FLOOR, feeds the same block. The two are described together in the
next section, because the difference between them is not what they deny but how
they REACH an agent -- and that is the part that decides what happens when one
of them is edited.

Denied: `curl` to an `https://` URL, and `wget` / `nc` / `ncat` / `telnet`
outright. A `deny` rule is checked **before** the
`--dangerously-skip-permissions` bypass, so it binds on permissive profiles too.
Sanctioned tooling that speaks HTTPS on its own account (`git`, `gh`, `npm`) is
deliberately untouched: denying it would break the release path without closing
anything an agent could not do through it anyway.

The sanctioned route for external content is unchanged: the quarantine-reader
sub-agent, through `WebFetch`, where the domain check already runs. A host being
on the egress allowlist does not open it to the shell.

## Two lists, and why they are not one

Since DENYARGS925 (2026-09-25) `permissions.deny` is fed by TWO constants in
`src/web/agent-scaffold.ts`. Reading either one as "the" deny list is the
mistake this section exists to prevent.

| | `BASH_EGRESS_DENY` | `FLEET_BASELINE_DENY` |
|---|---|---|
| covers | shell URL-fetch verbs: `curl` to `https://`, `wget`, `nc`, `ncat`, `telnet` | the fleet FLOOR: key/credential dirs, `.env`, `sudo`, `rm -rf` of `$HOME` and `/`, force-push (friction only), the unsafe browser-code MCP tool |
| sub-agent gets it | spawn + server-startup migration + scaffold template | **spawn only** (`writeAgentSettingsFromProfile`) |
| main agent gets it | `ensureBashEgressDeny()` into its own config dir | the repo's tracked `.claude/settings.json` (the scaffold never writes the main agent, #1305) |
| parity guarded by | `bash-egress-deny.test.ts` (template vs constant) | `fleet-baseline-deny.test.ts` (shipped file vs constant, both directions) |

Two consequences follow from the row that differs, and both are deliberate:

**The floor has no startup migration.** An agent that is running right now and is
not respawned keeps whatever deny list it started with; the egress rules would be
merged into its file at the next server start, the floor would not. The floor
therefore takes effect at the next spawn, not at the next server restart. This is
the honest limit, not a claim of immediate fleet-wide cover.

**The floor is deliberately NOT in `templates/settings.json.template`.** Measured
2026-09-25: after `scaffoldAgentDir()` the template-derived file carries 10 deny
rules and **zero** of the floor's 13 -- but on the create path
(`routes/agents.ts`) `scaffoldAgentDir()`, `writeAgentModel()`,
`writeAgentSecurityProfile()` and `writeAgentSettingsFromProfile()` are four
SYNCHRONOUS calls with no await and no session launch between them, and on the
spawn path the profile write runs before the Claude Code process starts. So the
template-only state exists on disk but no session reads it, and
`loadProfileTemplate()` cannot throw its way around that: a missing or unparseable
profile falls back to `default` and finally to `HARDCODED_DEFAULT_PROFILE`. The
live fleet agrees: the leanest agent here carries 16 rules, none carries 10.

If a future change adds a route that scaffolds WITHOUT writing the profile
straight after, that reasoning expires and the floor belongs in the template too.
The parity test names this condition so the decision can be re-measured rather
than re-argued.

## Where the main agent's copy goes

The main agent's nominal settings path is the shared user root
(`~/.claude/settings.json`) -- and that same file is the operator's own
interactive Claude Code sessions. The owner's decision (2026-09-07) was that
their own shell stays unrestricted while the fleet stays gated, which makes the
shared file unusable in both directions: writing there restricts the operator,
removing it from there un-gates the main agent, which is the one agent that
reads untrusted web content on the owner's behalf.

Measured way out: when the install gives the main agent a config dir of its own
(`MAIN_AGENT_CONFIG_DIR`, or the provisioned isolated dir behind
`MAIN_AGENT_ISOLATED_CONFIG`), that dir's `settings.json` is the agent's user
scope and the operator's shell does not read it. `bashEgressDenyTargetPath()`
sends the rules there. The separation survives restarts: the provisioner
rebuilds that file from the shared one on every start but keeps keys the shared
file never mentions, and `permissions` is such a key.

When the main agent runs on the shared root there is no scope that covers it
without covering the operator, so **nothing is written** and the startup log
says so. Giving the main agent its own config dir is the fix; picking a side
quietly is not this code's call.

## The trap for whoever measures this next

The two scopes do not behave the same way, and the difference is invisible until
it misleads you (both measured 2026-09-07):

- The **project scope** (`<cwd>/.claude/settings.json` and `settings.local.json`)
  is re-read while a session runs. A rule written there fires immediately, which
  makes it a fine live test bench: drop a narrow, unique rule in, probe it, then
  delete the file.
- The **user scope** (the `settings.json` in the session's `CLAUDE_CONFIG_DIR`)
  is read when the session STARTS and is not re-read afterwards. A rule written
  there while the session runs does nothing at all.

So a probe that works perfectly on the project scope reports a confident
"allowed" on the user scope, and the honest-looking conclusion -- "the rule does
not work" -- is wrong. What it means is "this session has not read it yet".
Measure a user-scope rule from a session that started AFTER the write, or after
the next restart.

The same asymmetry is why a newly written rule binds the main agent from its
next restart rather than immediately.

## Limits, stated out loud

This is a deny list, not a sandbox.

- **The localhost exception is why only `https://` is denied for `curl`.** The
  rule language has no negation and `deny` always beats `allow`, so "any
  `http://` host except localhost" cannot be expressed. A `*http://*` rule would
  also match `http://localhost:3420/...` and mute the whole fleet (memory,
  kanban, message queue, approvals all ride that URL).
- Still open, by construction: plain-http external fetches, an interpreter
  one-liner (`python3 -c`, `node -e`), and a URL hidden in a shell variable.
  Closing those needs a Bash `PreToolUse` hook that parses the command.
- Known collateral: an internal POST whose **double-quoted** payload quotes an
  `https://` URL matches the `curl` rule. Single-quoted payloads do not (the
  permission engine excludes single-quoted content). Use single quotes or
  `-d @file` for such a call.

# The GitHub API path: one pinned script (GHPRPIN)

`store/egress-vendor-hosts.json` let every Bash call reach `api.github.com`.
The vendor list filters on the host, never on the path, so that one entry also
opened, with a token, gists, issues, comments and repository contents (a write
channel), and without one, foreign issue and comment text straight into the
context (Viktor 28582 (b); card 54bd5c28). In 14 days of fleet transcripts,
131 distinct Bash commands named that host (an upper bound: some only quote it).

`scripts/gh-pr.mjs` replaces it with a closed list:

- two repositories (`kiskodzsek/marabel`, `kiskodzsek/marveen`), the host a
  constant, the request built only from fixed templates and shaped arguments;
- `pr list|get|files|create|edit` and `ci checks|runs|jobs|log`;
- the release writes Pulzus's chain needs (card 54bd5c28, 2026-11-08):
  `pr review-approve`, `pr merge --method squash|merge`, `pr close`, `pr reopen`
  and `branch get`. Each write takes the PR's full 40-hex head (`--sha`); the
  script reads the PR first and writes nothing if the head moved or the state
  is not the expected one (`refused-head` in the audit); the merge also sends
  the sha, so GitHub refuses a moved head itself. No free text rides along: no
  review body, no merge commit title or message. The writes run only as
  `pulzus` or `klodel` (`refused-agent` otherwise, Viktor 31739): a drift
  control, not authentication, since the agent id is self-declared; the token's
  scope and the branch protection stay the real limit. The main session's id
  resolves to `unknown` today, so Klodel's marveen merges stay on their own
  path until its launcher names it. Still out: auto-merge, rebase
  merge, other review kinds, comments, issues, gists, contents, branch create,
  delete or protection, workflow re-run, cancel or dispatch;
- the token from the caller's own repository-local git credential helper, with
  the system and global git config off, so the keychain helper (other agents'
  credentials) is never asked; in memory only;
- `-C <clone>` only at or below the working directory, never in another
  agent's tree or the install's `store/` (another agent's helper would hand out
  that agent's token);
- a PR body from a regular file under the clone or `/tmp` (not in the store or
  another agent's tree), or stdin, at most 64 KiB, refused if it carries a
  secret shape; a job log printed inside an UNTRUSTED frame whose BEGIN and END
  lines carry a fresh random nonce (a CI step cannot print a fake end),
  tail-capped, secret shapes masked;
- one metadata line per call in `store/gh-pr-audit.jsonl`, refusals included
  (`refused`, `refused-clone`, `refused-body`, `refused-agent`, `refused-head`,
  `no-token`); a write's line also names the examined head sha; never a body,
  a header or the token.

The egress parser lets the script run only as the whole command
`node <install>/scripts/gh-pr.mjs ...` (output redirects and a body heredoc
allowed), with the file's sha256 equal to `store/egress-script-pins.json`
(`{"scripts/gh-pr.mjs": "<64 hex>"}`). A missing or wrong pin denies: this path
fails closed while the gate as a whole fails open.

**This is drift control, not enforcement.** The hook does not see network calls
inside a script file, so a renamed, edited copy runs unchecked; a write between
the hash check and node's read is not closed (TOCTOU). The limit that holds is
the token's scope: a fine-grained token on the two repositories (an owner step).

Rollout, in this order (Viktor 30388 K4): the script and parser change merged at
a reviewed sha; the pin written to the store (owner step, the sha from the
review); skills and memories switched to the script, 1-2 days of the block log;
then `api.github.com` removed from the vendor list (owner step). A new version of
the script needs a new review and a new pin.

# What the URL gate does not cover

Both web controls are wired to **one tool**. `scripts/hooks/egress-gate.mjs`
runs as a `PreToolUse` hook with matcher `WebFetch`, and `wrapUntrustedFetch()`
(`src/prompt-safety.ts`) frames what that tool returns. Everything else that
brings the outside world into an agent's context is outside both:

- **`WebSearch`** -- result snippets are external text; no allowlist decided
  which sites they came from, and nothing wraps them on the way in.
- **Any MCP server that fetches** -- a browser server (playwright, chrome), a
  docs server, an API connector. The agent's own `curl` is denied by
  `BASH_EGRESS_DENY`, but an MCP server makes the request in its own process,
  where neither control can see it.

This is stated in a comment inside `egress-gate.mjs`. It was not stated here,
which is the wrong place for it to be missing: the comment is read by whoever
edits the gate, this file is read by whoever decides what to install. An
operator adding a browser MCP server was therefore adding an ungated,
unlabelled content path while reading that egress was covered.

The fleet ships no browser by default, so a stock install is unaffected. But
the fleet's own scaffolding expects browsers to appear (the largest profile is
described as "filesystem + playwright + chrome"), so this is a normal
deployment, not an exotic one.

## Why a browser payload is the sharper case

A fetched page cannot run code in the agent; it can only try to talk to it. A
browser payload arrives the same way -- except the browser it arrives through
holds live logged-in sessions, and the agent reading it has a shell, a
filesystem and outbound channels. The realistic attack is not an exploit, it is
a sentence: text on the page addressed to the agent rather than to the reader.

The defence against that is framing, not filtering: content the agent knows is
content cannot impersonate an instruction. `WebFetch` gets that framing from
the wrapper. A browser payload gets none.

## The opt-in envelope hook

`scripts/hooks/browser-content-notice.py` is a `PostToolUse` hook that wraps
browser / search results in an `<untrusted source="..." fetch-nonce="...">`
envelope before the model sees them -- the same framing `wrapUntrustedFetch()`
gives the `WebFetch` path -- scrubs forged security tags out of the payload,
names any injection patterns it matched (forged `<untrusted>` /
`<system-reminder>` envelopes, a pre-injected scrub sentinel, instruction
overrides, credential targets, exfil shapes) and appends the full payload to
`store/browser-content.log` for reading outside the model's context.

It is **not registered by default** -- an install with no browser gains nothing
from it. Operators who run a browser MCP server wire it themselves, in the
project `settings.json` or `settings.local.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "mcp__playwright__browser_.*|mcp__chrome.*|WebSearch",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/scripts/hooks/browser-content-notice.py\"",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

### The shape rule, and the silent fallback behind it

`hookSpecificOutput.updatedToolOutput` replaces a tool result before it reaches
the model. It is not unconditional, and the condition is the important part
(measured 2026-09-20, Claude Code 2.1.278):

- **MCP tool**: a plain string replaced the result outright. The original never
  reached the model.
- **Built-in tool** (`WebSearch`): the replacement must match THAT TOOL'S
  OUTPUT SHAPE. A string was rejected -- `expected: object` -- the harness
  logged `... does not match WebSearch's output shape; using original output`,
  and the raw payload reached the model unchanged.

The rejection is an execution-error record, not part of the tool result, so
**from the model's side a broken envelope is indistinguishable from a working
one**: the content simply arrives unwrapped, as it always did.

That is why the hook writes two layers on every call and never treats the
first as sufficient:

1. `updatedToolOutput` -- the envelope. Shape-preserving: a string stays a
   string, MCP content blocks stay blocks with their original keys, a record
   keeps every key and only its free-text leaves are wrapped. A shape it
   cannot mirror confidently is left alone, because a rejected replacement
   leaves the RAW payload in context -- declining is the safer failure.
2. `additionalContext` -- the label, which cannot be shape-rejected. It states
   that a payload arriving WITHOUT an envelope means the envelope was rejected,
   so the absence is readable rather than invisible.

The label quotes nothing back. Its own text is trusted framing, so echoing a
matched line there would reopen the channel the hook exists to close. Pattern
names and counts only; the payload itself goes to the log.

`envelope_attempted` in the log records which shape the hook tried. It says
"attempted", never "succeeded": the hook cannot observe the harness's decision,
and a field that claimed success would be the most misleading line in the file.

# Email approvals consumed on the send path

At `email_send` level 2 an approval authorizes ONE letter: `content_hash` pins
it to the exact envelope and `consumed_at` makes it one-shot. The gate
(`scripts/hooks/email-approval-gate.py`) flips `consumed_at` itself, but only
for a send it can read in the command text (an MCP mail tool, `send.py --to`,
an inline mailer call). A tool that mails through a script on another host,
for example `ssh <host> 'tsx send-letter.mjs'`, is invisible to it, so its
approval stayed unconsumed and could authorize a second send.

Such a tool consumes on its own path, right BEFORE the letter goes out, and
sends only on a yes:

```bash
python3 scripts/approval-consume.py --id <approval id> --content-hash <anchor> \
  --consumer <tool name> --message-id '<id@your.domain>' || exit 1   # 0 = send now
```

`POST /api/approvals/<id>/consume` is one conditional write (approved,
`email_send`, unconsumed, the same anchor, inside `EMAIL_APPROVAL_WINDOW_S`,
1800 s like the gate). Of two attempts exactly one gets 200; the other gets
409 with a reason (`already_consumed`, `not_approved`, `hash_mismatch`,
`expired`, `wrong_category`). The row records the consumer and the Message-Id
the tool generated up front (`consumed_by`, `consumed_ref`), and every call,
refused ones included, leaves a row in `approval_events`. The gate and the
endpoint read the same `consumed_at IS NULL`, so a letter consumed by one path
is refused by the other.

A 409 means: do not send, and check the sent mailbox before deciding anything,
because the earlier attempt may already have gone out.

# The research reader: one local tool (webread)

Research (K+F, Radar) reads public pages with its own headless browser, because
the quarantine reader returns a model summary, not the page's bytes, and an
empty shell on JavaScript pages (`shared/kf/webgyujtes-1110.md`). That path ran
outside every egress control: `agents/radar/tools/getfile.mjs` launched Chromium
with `--no-sandbox`, wrote wherever the caller said, and reached `file://`,
localhost and the LAN. `scripts/webread/webread.mjs` replaces it with the
controls of Viktor's review (`agents/viktor/reports/2026-11-10-getfile-renderelo-olvaso-itelet.md`):

- **Sandbox (A).** `chromiumSandbox: true` and an environment of `PATH` and
  `TMPDIR` only, so no agent token reaches the browser. If the sandbox does not
  start, the run fails; there is no fallback to `--no-sandbox`.
- **Output (B).** Only `agents/<agent>/work/untrusted/webread/<run>/`, every
  directory on the way checked with `realpath`, every file created with `wx`
  (no overwrite, no planted link followed), every name made by the tool. There
  is no output-path argument.
- **Addresses (C).** `https` on port 443 only. The browser is forced through a
  local forward proxy (`--proxy-bypass-list=<-loopback>`, QUIC off, WebRTC
  proxied only) that resolves each `CONNECT` itself, refuses the name if any
  answer is loopback, private, link-local, CGNAT, multicast, reserved,
  documentation, NAT64, 6to4, Teredo or IPv4-mapped private, and connects to the
  address it checked (no DNS-rebinding gap). `file` mode uses no browser: plain
  Node `https` with the same lookup, a literal-IP check on every hop and at most
  5 redirects, each re-checked.
- **Limits (D).** A byte limit (`file`: 25 MB default, 200 MB max, also on a
  stream without a length; `page`: 2 000 000 characters), 50 s per page, a hard
  wall clock for the run (Chromium exits with the process), downloads and
  service workers blocked, at most 12 pages at once and 4 per host.
- **Output to the model (E).** stdout is fixed fields only (status, size,
  sha256, tool-made file name, flag), sanitised; the page text lands in files
  that open with an `UNTRUSTED WEB CONTENT` banner. Read them in slices. The
  request log (`requests.log` next to the runs) keeps host, time, status, size
  and flag, and the path + query only as `length:sha256-8`, never their text.
- **No host allowlist.** Any public https host is reachable, so the tool is an
  outbound channel too: an agent misled by a page could carry data out in a
  query. URLs are capped at 2048 characters, and the log's length:hash column is
  what shows a long or repeated query (Viktor, webread delta LOW).

Still open: the browser engine itself (a renderer exploit chained with a
sandbox escape), which only a separate, unprivileged OS user closes; that is the next step if the
tool is opened to arbitrary hosts. Bot walls (403, captcha) are reported as
`http_403` / `captcha` and never worked around.
