import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

// Registration-completeness lint for scripts/hooks/.
//
// The recurring defect class this pins: a hook ships fully unit-tested but is
// registered NOWHERE, so it never fires in production while its suite stays
// green -- the reply-guard before #1028 registered its decision logic but not
// the Stop wiring, skill-usage-capture (#607) captured nothing for six weeks,
// and the ledger-live-drain never ran while its docs promised a schedule.
// Each was found by hand. This test finds the next one mechanically: every
// shipped hook script must be referenced by at least one REGISTRATION surface,
// or carry an explicit, reasoned exemption below.
//
// Two directions are enforced:
//   - UNWIRED: a hook that is neither registered nor exempted fails the build,
//     so a new hook cannot ship dead.
//   - STALE EXEMPTION: an exempted hook that IS now registered fails the
//     build, so the exemption list cannot rot into a blind spot -- when an
//     in-flight wiring PR lands, its entry must be deleted here.

const ROOT = join(__dirname, '..', '..')
const HOOKS_DIR = join(ROOT, 'scripts', 'hooks')

// Everywhere a hook can legitimately be wired into production, split by WHO
// the surface configures (TGSABLONHOOK921, 2026-09-21):
//
//   SEEDING surfaces configure every agent this install creates from now on:
//   the settings template each agent is seeded from, the code-side
//   registrations (agent-scaffold), and the two installer scripts.
//
//   CHECKOUT surfaces configure exactly ONE agent -- the one whose session cwd
//   is this checkout, i.e. the main agent -- through the repo's own project
//   settings.
//
// The two are not interchangeable, and the single concatenated corpus this
// lint used to build treated them as if they were: telegram-reply-directive.py
// was registered in .claude/settings.json (one agent) and absent from the
// template (every seeded agent), and the lint stayed green because "somewhere"
// was satisfied by the main agent's own file. Every newly seeded Telegram
// agent started without the hook: it composed its reply, wrote it into its
// tmux pane, never called the reply tool, and the owner saw nothing. An
// external install measured this on two agents (2026-09-11/12 and again after
// a 2026-09-14 image swap wiped a hand wiring the template had never carried).
const SEEDING_SURFACES = [
  'templates/settings.json.template',
  'src/web/agent-scaffold.ts',
  'scripts/install-telegram-progress-hook.sh',
  'scripts/install-slack-progress-hook.sh',
  'scripts/install-channel-image-hook.sh',
]
const CHECKOUT_SURFACES = ['.claude/settings.json']
const REGISTRATION_SURFACES = [...SEEDING_SURFACES, ...CHECKOUT_SURFACES]

// name -> why it is allowed to be unregistered. Keep every reason concrete;
// "misc" entries defeat the lint.
const EXEMPT: Record<string, string> = {
  'ledger_lib.py':
    'shared library imported by the ledger hooks; not itself a hook',
  'ledger-close.py':
    'agent-run CLI that closes one group inbound as "not for me" (python3 scripts/hooks/ledger-close.py <chat_id> <message_id> "nem nekem: <kinek>"); the reply guard names it by this path in its block text, so it lives next to ledger_lib.py; not itself a hook (Klodel 37860)',
  'keychain-read-gate_test.py':
    'the unit test of keychain-read-gate.py (run: python3 -I scripts/hooks/keychain-read-gate_test.py); not itself a hook (c1921b55)',
  'command_prompt.py':
    'shared library: the one "is this prompt an owner slash command" check, imported by marveen-commands.py, inbox-drain.py and channel-inbox-drain.py; not itself a hook',
  'hook_errlog.py':
    'shared library imported by hooks to record a swallowed failure in store/hook-errors.log (SILENTOLLAMA926); not itself a hook',
  'clearstate_lib.py':
    'shared library imported by clear-capture.py / clear-replay.py; not itself a hook',
  'memory_frontmatter_lib.py':
    'shared library: the one memory-frontmatter check, imported by memory-frontmatter-gate.py (Write/Edit) and memory-frontmatter-bash-gate.py (Bash, KAPUEGYUT918); not itself a hook',
  'private-topic-group-gate_test.py':
    'the unit test of private-topic-group-gate.py (run: python3 -I scripts/hooks/private-topic-group-gate_test.py); not itself a hook (6dbeadad)',
  'email_extract.py':
    'shared library imported by outgoing-copy-gate.py (and the level-2 email approval gate, EMAILKAPU901 PR2); not itself a hook',
  'ms365-policy-check.mjs':
    'operator CLI (MS365GATE1015): checks the live .mcp.json ms365 entry and the server tool list against ms365-tool-policy.json before send-mail is enabled; the same functions run in src/__tests__/ms365-tool-policy.test.ts; not a settings hook',
  'memory-save.sh':
    'legacy: referenced only by a historical rebuild prompt, wired nowhere; kept pending a maintainer decision to remove it',
  'telegram-ack.py':
    'unreferenced anywhere in the repo; dead code kept pending a maintainer decision to remove it',
  'telegram_fallback_send.py':
    'agent-invoked CLI (manual Bot API fallback sender, see scripts/lib/send-telegram.sh), not a settings hook; since #1305 the progress installer no longer copies or names it',
  'channel-process-gate.py':
    'scheduled/CLI gate (--only / --notify / --json), not a settings hook: it compares the channels a session DECLARES against the plugin processes actually alive under it, which is a periodic check rather than a per-tool-call one',
  'browser-content-notice.py':
    'OPT-IN by construction (BROWSERNOTICE920): it envelopes browser-MCP / WebSearch payloads as untrusted content, and an install without a browser MCP server gains nothing from it. Wiring it here would fire it on every fleet member, most of which have no browser. Operators add it to their own PostToolUse hooks -- the procedure is in docs/security-hardening.md.',
  'claim-source-reply-gate_test.py':
    'the unit test of claim-source-reply-gate.py (run: python3 -I scripts/hooks/claim-source-reply-gate_test.py); not itself a hook',
  'mea-culpa-reply-gate_test.py':
    'the unit test of mea-culpa-reply-gate.py (run: python3 -I scripts/hooks/mea-culpa-reply-gate_test.py); not itself a hook',
  'mute-video-reply-gate_test.py':
    'the unit test of mute-video-reply-gate.py (run: python3 -I scripts/hooks/mute-video-reply-gate_test.py); not itself a hook',
  'service-memory-reply-gate_test.py':
    'the unit test of service-memory-reply-gate.py (run: python3 -I scripts/hooks/service-memory-reply-gate_test.py); not itself a hook',
  'render-claim-reply-gate_test.py':
    'the unit test of render-claim-reply-gate.py (run: python3 -I scripts/hooks/render-claim-reply-gate_test.py); not itself a hook',
  'product-image-gate_test.py':
    'the unit test of product-image-gate.py (run: python3 -I scripts/hooks/product-image-gate_test.py); not itself a hook',
  'react-emoji-gate_test.py':
    'the unit test of react-emoji-gate.py (run: python3 -I scripts/hooks/react-emoji-gate_test.py); not itself a hook (#185)',
  'balazs-task-reply-gate_test.py':
    'the unit test of balazs-task-reply-gate.py (run: python3 -I scripts/hooks/balazs-task-reply-gate_test.py); not itself a hook (#185)',
  'time-claim-gate_test.py':
    'the unit test of time-claim-gate.py (run: python3 -I scripts/hooks/time-claim-gate_test.py); not itself a hook (Klodel 38401)',
  'link-request-reply-gate_test.py':
    'the unit test of link-request-reply-gate.py (run: python3 -I scripts/hooks/link-request-reply-gate_test.py); not itself a hook (#219, card 18b2002b)',
  'patrik-reply-volume-gate_test.py':
    'the unit test of patrik-reply-volume-gate.py (run: python3 -I scripts/hooks/patrik-reply-volume-gate_test.py); not itself a hook (card 9df14a4c)',
  'pr-kerdes-gate_test.py':
    'the unit test of pr-kerdes-gate.py and scripts/pr-kerdes.py (run: python3 -I scripts/hooks/pr-kerdes-gate_test.py); not itself a hook',
  'count-claim-gate_test.py':
    'the unit test of count-claim-gate.py (run: python3 -I scripts/hooks/count-claim-gate_test.py); not itself a hook (Klodel 39869)',
  'repo-create-gate_test.py':
    'the unit test of repo-create-gate.py (run: python3 -I scripts/hooks/repo-create-gate_test.py); not itself a hook (Klodel 40048)',
  'zsh-trap-gate_test.py':
    'the unit test of zsh-trap-gate.py (run: python3 -I scripts/hooks/zsh-trap-gate_test.py); not itself a hook (retro 2026-11-13 R6, card cf287c2c)',
  'update-apply-gate_test.py':
    'the unit test of update-apply-gate.py (run: python3 -I scripts/hooks/update-apply-gate_test.py); not itself a hook (Klodel 39791)',
  'render_claim_lib.py':
    'shared library imported by render-claim-reply-gate.py (the store/video-export-status.json reader); not itself a hook',
  'mio-orszem-precheck.sh':
    'scheduler preCheck for the HOST-LOCAL marveen-io-kozosseg-orszem task (ORSICTX912): the mio community sentinel is this install\'s own and deliberately NOT seeded (a repo seed would ship it to every customer install), so its registration lives in the host ~/.claude/scheduled-tasks task-config -- outside this corpus by design. Wiring is gated on the ORSICTX912 activation order (host restart -> verify -> merge -> build+restart); the hermetic fail-direction tests are scripts/__tests__/mio-orszem-precheck.test.py.',
}

function readSurfaces(rels: readonly string[]): string {
  let corpus = ''
  for (const rel of rels) {
    const p = join(ROOT, rel)
    if (existsSync(p)) corpus += readFileSync(p, 'utf-8')
  }
  return corpus
}

// The seeded scheduled tasks count as a registration too (a script may be
// driven by a schedule instead of a hook event), and they reach every install,
// so they sit in the general corpus -- but they are not a settings surface, so
// they play no part in the checkout-vs-seeding comparison below.
function scheduledTasksCorpus(): string {
  let corpus = ''
  const tasksDir = join(ROOT, 'scheduled-tasks')
  if (existsSync(tasksDir)) {
    for (const task of readdirSync(tasksDir)) {
      const skill = join(tasksDir, task, 'SKILL.md')
      if (existsSync(skill)) corpus += readFileSync(skill, 'utf-8')
      // A task's preCheck script is a schedule registration too: the scheduler
      // runs it on every tick (ledger-live-drain-precheck.sh).
      const config = join(tasksDir, task, 'task-config.json')
      if (existsSync(config)) corpus += readFileSync(config, 'utf-8')
    }
  }
  return corpus
}

function registrationCorpus(): string {
  return readSurfaces(REGISTRATION_SURFACES) + scheduledTasksCorpus()
}

// Hooks wired ONLY in the checkout's own project settings, each with the
// verified reason it is main-agent-only by design and must NOT be seeded to
// every agent. Keep every reason concrete and sourced (docstring, docs, PR):
// a "misc" entry here would re-open exactly the blind spot this split closes.
const CHECKOUT_ONLY: Record<string, string> = {
  'link-request-reply-gate.py':
    'the owner asked the MAIN agent for a link (Patrik TG 17974, TG 18022; #219, card 18b2002b): the gate reads the latest inbound message of the chat from conversation_log through ledger_lib, and that ledger is written only for the main channels session (ledger-capture.py is CHECKOUT_ONLY below), so on a seeded sub-agent it would find no inbound row and pass every reply; seeding it needs a sub-agent ledger first (a separate decision)',
  'patrik-reply-volume-gate.py':
    'the MAIN agent spammed the owner\'s chats (Patrik TG 18129; card 9df14a4c): the gate counts the main agent\'s outbound rows since the latest inbound row of the chat in conversation_log through ledger_lib, and that ledger is written only for the main channels session (ledger-capture.py is CHECKOUT_ONLY below); the gate itself passes every other agent',
  'private-topic-group-gate.py':
    'the owner\'s private topics stay out of the team group (card 6dbeadad): it lets through only the owner\'s private chat with the MAIN agent (store/projektek.json elo_uzenet.privat) and gates every other chat, so on a sub-agent, whose chats are all "other", it would gate every message that names a private project',
  'email-approval-gate.py':
    'level-aware email gate for the MAIN agent (EMAILKAPU901 PR2, #1149): its docstring scopes it to sessions rooted at PROJECT_ROOT, and sub-agents keep their unconditional hard-deny (email-send-gate.mjs), behind which this gate would be a no-op',
  'inbox-drain.py':
    'main-agent inbox PULL (#506): sub-agents are fed by the message router\'s tmux-push path, and draining them here too would double-deliver (docstring: "Main-agent ONLY")',
  'ledger-capture.py':
    'conversation-continuity ledger: docs/conversation-continuity.md wires the ledger trio in the PROJECT settings for the main channels session ("NOT user scope"); the sub-agent path is the clear-capture/clear-replay pair, which IS in the template',
  'ledger-outbound.py':
    'conversation-continuity ledger: same design as ledger-capture.py (docs/conversation-continuity.md, project settings only)',
  'ledger-replay.py':
    'conversation-continuity ledger: same design as ledger-capture.py; the docs state it is "wired in the repo\'s project settings only (the main agent)"',
  'ms365-download-gate.mjs':
    'gates the ms365 MCP download-bytes-to-file tool, which only the MAIN agent has: the ms365 server is configured in the repo\'s own .mcp.json (the main session), no agents/*/.mcp.json carries it (measured 2026-10-16), and the tool is enabled only by that file\'s --enabled-tools. Its drop directory is ONE repo-wide store/mail-downloads; seeding the gate as-is would point every agent\'s downloads at that shared directory, so a sub-agent that ever gets ms365 needs its own drop-dir design first (a separate, reviewed decision, Viktor/Lex)',
  'persona-change-notify.py':
    'fleet-wide BY CONSTRUCTION, so one wiring already covers every agent: it resolves the repo root from its own file location, and watched() enumerates agents/*/CLAUDE.md and SOUL.md alongside the main pair. Seeding it per-agent would point every seeded session at the SAME store/.persona-hashes.json, and because the hook stamps the new digest BEFORE it sends, whichever session reaches it first silences the others -- the race can only LOSE an alert, so seeding would weaken the guard rather than extend it',
  'mea-culpa-reply-gate.py':
    'PreToolUse gate on the telegram reply/edit_message tool that guards replies to Patrik\'s own chats (store/projektek.json elo_uzenet privat/csoport; none known = every chat gated, fail-closed). Its docstring: "Wiring: .claude/settings.json PreToolUse ... (the main agent\'s settings; the sub-agents have their own)". Seeded, every sub-agent would be gated on Patrik\'s rule for the main agent (#141)',
  'service-memory-reply-gate.py':
    'PreToolUse gate on the MAIN agent\'s telegram reply (Klodel 40111, #241, Patrik TG 5750/5753): a known service named in a reply needs a dashboard-memory search in the same round, read from the session transcript. It passes every non-main agent itself (ledger_lib.agent_id_from_payload), so seeding it would only add a no-op; a fleet-wide rule is a separate decision',
  'render-claim-reply-gate.py':
    'PreToolUse gate on the telegram reply/edit_message tool that guards replies to Patrik\'s own chats: a render-state claim only on a fresh ops/video_export_status.py measurement of THIS machine (docstring: chats as mea-culpa-reply-gate.py). Main-agent rule from Klodel 35696 (#147); same seeding objection as mea-culpa-reply-gate.py',
  'claim-source-reply-gate.py':
    'PreToolUse gate on the telegram reply/edit_message tool that guards replies to Patrik\'s own chats: a state claim or number needs a source (Klodel 35761, Patrik TG 4477; chats as mea-culpa-reply-gate.py). Its docstring wires it in .claude/settings.json; until fix/ci-red-main-1111 it ran only from the prod checkout\'s uncommitted settings',
  'mute-video-reply-gate.py':
    'PreToolUse gate on the main agent\'s telegram reply: no .mp4/.mov without an audio track reaches Patrik (TG 4483, Klodel 35741). Docstring: "Wiring: .claude/settings.json PreToolUse"; until fix/ci-red-main-1111 it ran only from the prod checkout\'s uncommitted settings. Seeding it fleet-wide is a separate decision',
  'pr-kerdes-gate.py':
    'PreToolUse gate on the main agent\'s telegram reply/edit_message: a "PR #<n> mehet?" ask to Patrik only with a store/pr-kerdes/<n>.ok sheet (the PR\'s full file list, a picture or reason per file) in THIS checkout\'s store (hibanapló 2026-11-11, Klodel 37320). Asking Patrik to ship a PR is the main agent\'s role; seeding it fleet-wide is a separate decision',
  'product-image-gate.py':
    'TERMEKKEP-KAPU (Patrik TG 1690/1694): an image/video to the owner on Telegram only with a store/kep-kapu/<file>.ok attestation in THIS checkout\'s store. Until fix/ci-red-main-1111 it ran only from the prod checkout\'s uncommitted settings. Seeding it fleet-wide is a separate decision',
  'react-emoji-gate.py':
    'PreToolUse gate on the main agent\'s telegram react tool: in Patrik\'s own chats (store/projektek.json elo_uzenet privat/csoport; none known = every chat gated) only 👍 👀 ❤ (Klodel 38093, Patrik TG 5436). The rule was about the main agent\'s reactions; same seeding objection as mea-culpa-reply-gate.py (#185)',
  'balazs-task-reply-gate.py':
    'PreToolUse gate on the main agent\'s telegram reply/edit_message: no task put on Balázs without BALAZS-OK: TG <n>, and no PR go-ask to Patrik without PATRIK-KERTE (Patrik TG 4910/4917). A rule for the main agent, the one that talks to Balázs and Patrik; it ran only from the prod checkout\'s uncommitted settings until #185. Seeding it fleet-wide is a separate decision',
  'telegram-react-ack.py':
    'the PostToolUse half of the reaction acknowledgement (Klodel 34050): it records a successful react in ledger_lib.record_reaction, and the only reader is telegram-reply-guard.py (reacted_since), which is itself CHECKOUT_ONLY on the main-only ledger; seeded alone it would write a stamp nobody reads',
  'telegram-reply-guard.py':
    'the Stop-hook half of the Telegram reply enforcement (#856) decides from ledger_lib.open_question_with_age, i.e. the conversation_log the main-only ledger trio writes; seeded alone it would read an empty ledger and allow every stop, a silent no-op -- seeding it means seeding the ledger trio with it, a separate design decision',
}

// The direction that was blind: a hook the checkout's own settings wire, which
// no seeding surface carries and no entry explains. Pure so the mechanism can
// be tested on synthetic corpora, independent of the repo's current state.
export function unseededCheckoutHooks(
  names: readonly string[],
  checkoutCorpus: string,
  seedingCorpus: string,
  checkoutOnly: Record<string, string>,
): string[] {
  return names.filter(
    (name) => isRegistered(checkoutCorpus, name) && !(name in checkoutOnly) && !isRegistered(seedingCorpus, name),
  )
}

// A reference is a PATH ("/name") or a quoted token ("'name'" / "\"name\"") --
// never a bare substring, so "channel-inbox-drain.py" cannot satisfy
// "inbox-drain.py".
function isRegistered(corpus: string, name: string): boolean {
  return corpus.includes(`/${name}`) || corpus.includes(`'${name}'`) || corpus.includes(`"${name}"`)
}

function hookScripts(): string[] {
  return readdirSync(HOOKS_DIR)
    .filter((f) => f.endsWith('.py') || f.endsWith('.mjs') || f.endsWith('.sh'))
    .sort()
}

describe('hook registration completeness (scripts/hooks/)', () => {
  const corpus = registrationCorpus()

  it('every shipped hook is registered on some production surface, or reasoned-exempt', () => {
    const unwired = hookScripts().filter(
      (name) => !(name in EXEMPT) && !isRegistered(corpus, name),
    )
    expect(unwired, `unregistered hooks with no exemption: ${unwired.join(', ')} -- wire them or add a reasoned EXEMPT entry`).toEqual([])
  })

  it('no exemption has gone stale (an exempted hook that is now registered must drop its entry)', () => {
    const stale = Object.keys(EXEMPT).filter((name) => isRegistered(corpus, name))
    expect(stale, `stale exemptions (now registered): ${stale.join(', ')} -- delete their EXEMPT entries`).toEqual([])
  })

  it('every exemption points at a file that still exists (no ghost entries)', () => {
    const ghosts = Object.keys(EXEMPT).filter((name) => !existsSync(join(HOOKS_DIR, name)))
    expect(ghosts).toEqual([])
  })

  it('the boundary rule rejects substring matches (the channel-inbox-drain trap)', () => {
    expect(isRegistered('scripts/hooks/channel-inbox-drain.py', 'inbox-drain.py')).toBe(false)
    expect(isRegistered('scripts/hooks/inbox-drain.py', 'inbox-drain.py')).toBe(true)
    expect(isRegistered("join(PROJECT_ROOT, 'scripts', 'hooks', 'egress-gate.mjs')", 'egress-gate.mjs')).toBe(true)
  })
})

describe('seeding vs checkout surfaces (TGSABLONHOOK921: the main agent\'s own settings must not vouch for every other agent)', () => {
  const seeding = readSurfaces(SEEDING_SURFACES)
  const checkout = readSurfaces(CHECKOUT_SURFACES)

  it('every hook wired in the checkout\'s own settings is also on a SEEDING surface, or reasoned CHECKOUT_ONLY', () => {
    const unseeded = unseededCheckoutHooks(hookScripts(), checkout, seeding, CHECKOUT_ONLY)
    expect(
      unseeded,
      `hooks wired only for the checkout's own agent, so every newly seeded agent starts without them: ${unseeded.join(', ')} -- add them to templates/settings.json.template (or agent-scaffold), or add a reasoned CHECKOUT_ONLY entry`,
    ).toEqual([])
  })

  it('no CHECKOUT_ONLY entry has gone stale (a hook that is now seeded must drop its entry)', () => {
    const stale = Object.keys(CHECKOUT_ONLY).filter((name) => isRegistered(seeding, name))
    expect(stale, `stale CHECKOUT_ONLY entries (now seeded): ${stale.join(', ')}`).toEqual([])
  })

  it('every CHECKOUT_ONLY entry names a hook that exists AND is actually wired in the checkout settings', () => {
    const ghosts = Object.keys(CHECKOUT_ONLY).filter((name) => !existsSync(join(HOOKS_DIR, name)))
    expect(ghosts, `CHECKOUT_ONLY entries with no file: ${ghosts.join(', ')}`).toEqual([])
    const unwired = Object.keys(CHECKOUT_ONLY).filter((name) => !isRegistered(checkout, name))
    expect(unwired, `CHECKOUT_ONLY entries not wired in .claude/settings.json at all: ${unwired.join(', ')}`).toEqual([])
  })

  it('the mechanism flags a checkout-only hook on synthetic corpora, and stops flagging it once seeded', () => {
    // Independent of the repo's current state: this is what makes the
    // template revocation red (see the PR's gate), not the current file set.
    const names = ['a.py', 'b.py', 'c.py']
    const checkoutCorpus = 'python3 "$CLAUDE_PROJECT_DIR/scripts/hooks/a.py"\nscripts/hooks/b.py\n'
    const seededA = "bash -c '[ -f {{PROJECT_ROOT}}/scripts/hooks/a.py ] && exec python3 {{PROJECT_ROOT}}/scripts/hooks/a.py; exit 0'"
    expect(unseededCheckoutHooks(names, checkoutCorpus, '', {})).toEqual(['a.py', 'b.py'])
    expect(unseededCheckoutHooks(names, checkoutCorpus, seededA, {})).toEqual(['b.py'])
    expect(unseededCheckoutHooks(names, checkoutCorpus, seededA, { 'b.py': 'main-only by design' })).toEqual([])
    // A hook the checkout does not wire is nobody's problem here (c.py).
    expect(unseededCheckoutHooks(names, checkoutCorpus, '', { 'a.py': 'x', 'b.py': 'y' })).toEqual([])
  })
})
