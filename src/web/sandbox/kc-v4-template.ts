// Generated from the v4 profile template that security review 53372 approved (MEHET + HASH-OK; card 6aa0a853).
// Byte-exact: String.raw keeps every backslash; the template holds no backtick and no '${'.
// Do not edit by hand: a change is a new profile, a new name in SANDBOX_PROFILES and a new hash review.
export const KC_V4_TEMPLATE = String.raw`;; kc-deny-v4.sb.tmpl -- card 6aa0a853, plan round 4 (Viktor 53351, 53359). NOT live. Base: kc-deny-v3.sb (blocks 1-6 unchanged).
;; Goal: no process under this profile reads a keychain secret, whatever its command text; none can have a process
;; OUTSIDE the profile run a command for it; and it cannot pick up the fleet's full-power credentials (the shared
;; dashboard token, the fleet Claude token, the root .env) to ask the dashboard to run something outside it.
;; It is no full secret isolation: an agent's own files, its own MCP configuration and every other file stay readable.
(version 1)
(allow default)

;; (1) keychain database files: the user's, the system's, any *.keychain / *.keychain-db by name
(deny file-read* file-write*
  (subpath "/Users/klodel/Library/Keychains")
  (subpath "/Library/Keychains")
  (regex #"\.keychain(-db)?$"))

;; (2) the keychain servers (file keychains: securityd; data-protection keychain: secd)
(deny mach-lookup
  (global-name "com.apple.SecurityServer")
  (global-name "com.apple.securityd")
  (global-name "com.apple.securityd.xpc")
  (global-name "com.apple.secd"))

;; (3) the fleet's full-power credentials, every copy by name (Viktor 53265 HIGH 1; the copies in store/ and backups/
;;     are listed on card 0254ec0f): without them the dashboard's command-running endpoints are out of reach. Until the
;;     narrow per-agent token (card 45dea12e) exists, this also keeps a sandboxed agent off the dashboard API entirely.
(deny file-read* file-write*
  (regex #"/\.dashboard-token")
  (regex #"/\.claude-oauth-token")
  (literal "/Users/klodel/marveen/.env")
  (regex #"^/Users/klodel/marveen/(store|backups)/(.*/)?\.env"))

;; (4) escape through a local server (Viktor 53265 HIGH 2: a tmux server on a custom -S path was open in v2): every
;;     outbound unix-socket connect is refused; allowed only what the fleet's natural commands were measured to need
;;     (sock-measure-2.txt: name resolution).
(deny network-outbound (remote unix-socket))
(allow network-outbound (remote unix-socket (literal "/private/var/run/mDNSResponder")))
;; the tmux socket folders also by file (a server is found by its folder too)
(deny file-read* file-write* (regex #"/tmux-[0-9]+/"))

;; (5) Apple events, LaunchServices
(deny appleevent-send)
(deny mach-lookup
  (global-name "com.apple.coreservices.launchservicesd")
  (global-name "com.apple.coreservices.quarantine-resolver")
  (global-name-regex #"^com\.apple\.lsd\."))

;; (6) launchd, at, cron, ssh, osascript, open by binary (a first layer; the probe also measures the API paths
;;     without the binaries: SMJobSubmit, NSAppleScript, NSWorkspace)
(deny process-exec
  (literal "/bin/launchctl")
  (literal "/usr/bin/osascript")
  (literal "/usr/bin/open")
  (literal "/usr/bin/at") (literal "/usr/bin/batch") (literal "/usr/bin/atq") (literal "/usr/bin/atrm")
  (literal "/usr/bin/crontab")
  (literal "/usr/bin/ssh"))
(deny network-outbound (remote ip "localhost:22"))

;; ---- v4 (Viktor 53351, 53359; card 45dea12e slice 2). Rendered per agent: @ROOT@ = install root (regex-safe, the live
;; root has no metacharacter), @SELF@ = the agent id, @HOME@ = the user's home. The later rule wins (SBPL).

;; (7) narrow agent keys (45dea12e): no agent-api-key is read or written, wherever it lies; the folders on the way cannot
;;     be renamed or removed (no other agent's folder moved onto the own path); then the own key, read only.
(deny file-read* file-write* (regex #"/agent-api-key$"))
(deny file-write*
  (literal "@ROOT@")
  (literal "@ROOT@/agents")
  (regex #"^@ROOT@/agents/[^/]+$")
  (regex #"^@ROOT@/agents/[^/]+/\.claude-config$")
  (regex #"^@ROOT@/agents/[^/]+/\.claude$")
  (regex #"^@ROOT@/agents/[^/]+/\.claude/channels$")
  (literal "@ROOT@/.claude"))
(allow file-read* (literal "@ROOT@/agents/@SELF@/.claude-config/agent-api-key"))

;; (8) localhost TCP, deny by default (Viktor 53351 1.): only the dashboard (the narrow key decides there). Any other port
;;     only after its purpose and authentication were measured.
(deny network-outbound (remote ip "localhost:*"))
(allow network-outbound (remote ip "localhost:3420"))

;; (9) channel state (bot tokens), per agent (Viktor 53351 2.): the main agent's, every agent's and the user-level folder
;;     refused; then the agent's own folder (its plugin runs under this profile and reads it).
(deny file-read* file-write*
  (subpath "@ROOT@/.claude/channels")
  (subpath "@HOME@/.claude/channels")
  (regex #"^@ROOT@/agents/[^/]+/\.claude/channels(/|$)"))
(allow file-read* file-write* (subpath "@ROOT@/agents/@SELF@/.claude/channels"))
`
