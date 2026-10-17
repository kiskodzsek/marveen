import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildMainSessionRespawnCmd } from '../web/channel-monitor.js'
import { mainConfigDecisionForTest } from '../web/main-config-decision.js'
import { buildRemoteLaunchCommand } from '../web/ssh-tmux.js'

// 0d7dd18d (Viktor, review of cc6ba6e0 / 0b660471, 2026-10-17): the key-sending
// detectors (pane-state) type into whatever the pane runs. Today no launch path
// can leave a shell there: every tmux command string ends with the claude
// invocation, so when claude exits the pane closes or goes dead (channels.sh
// remain-on-exit), and a dead pane takes no keys. A launch string with anything
// after claude (`; exec bash`, `|| bash`, `; read`) would leave a live shell
// that the detectors could type a dialog answer into. Every launch path is
// pinned here; a new tmux launcher fails the enumeration below first. A launch
// that really needs a shell after claude brings its own tpgid check (ps -g)
// before any send-keys, in its own PR.

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const read = (rel: string) => readFileSync(join(ROOT, rel), 'utf-8')

// What a shell would run after (or instead of) claude in the tail of a launch
// string: an unquoted ; & | or newline, or a command or process substitution
// anywhere outside single quotes. The tail starts at the FIRST claude word, so a
// later claude cannot hide a shell in between. ${VAR} expansions are opaque
// here: the shell-side ones come from .env and tmux's sh -c parses them again,
// so keeping operators out of those values is the quoting test's job
// (launch-scripts-quoting.test.sh), not this one's.
function shellControlAfterClaude(cmd: string, claudeWord: string): string[] {
  const at = cmd.indexOf(claudeWord)
  if (at < 0) return [`claude word not found: ${claudeWord}`]
  const tail = cmd.slice(at + claudeWord.length)
  const found: string[] = []
  let quote: string | null = null
  for (let i = 0; i < tail.length; i++) {
    const c = tail[i]
    if (quote === "'") { if (c === "'") quote = null; continue }
    if (c === '\\') { i++; continue }
    const subst = c === '`' || ('$<>'.includes(c) && tail[i + 1] === '(')
    if (quote === '"') { if (c === '"') quote = null; else if (subst) found.push(c); continue }
    if (c === "'" || c === '"') { quote = c; continue }
    if (subst || ';&|\n'.includes(c)) found.push(JSON.stringify(c))
  }
  if (quote) found.push('unterminated quote')
  return found
}

describe('the checker itself', () => {
  it('accepts plain claude arguments, quoted values and ${VAR} flags', () => {
    expect(shellControlAfterClaude(`a && b; claude --model 'x;y' --settings "a|b" \${FLAGS}`, 'claude')).toEqual([])
  })
  it.each([
    ['claude --x; exec bash'],
    ['claude --x || bash'],
    ['claude --x | tee log'],
    ['claude --x &'],
    ['claude --x\nbash'],
    ['claude --x "$(bash)"'],
    ['claude --x `bash`'],
    ['claude --x <(bash)'],
    ['claude --x; bash; claude --y'],
    ['claude --continue; read -r _; claude'],
  ])('rejects a shell after claude: %j', (cmd) => {
    expect(shellControlAfterClaude(cmd, 'claude')).not.toEqual([])
  })
})

describe('every tmux launch string ends with the claude invocation', () => {
  it('channels.sh: both new-session launches (primary and /tmp fallback)', () => {
    const m = [...read('scripts/channels.sh').matchAll(/new-session -d -s "\$SESSION" -c "[^"]+" \\\n\s*"(.*)"$/gm)]
    expect(m).toHaveLength(2)
    for (const [, cmd] of m) expect(shellControlAfterClaude(cmd, '$CLAUDE ')).toEqual([])
  })

  it('channel-watchdog.sh respawn command, passed to respawn-pane as is', () => {
    const s = read('scripts/channel-watchdog.sh')
    const cmd = s.match(/^RESPAWN_CMD="(.*)"$/m)?.[1] ?? ''
    expect(shellControlAfterClaude(cmd, '$CLAUDE ')).toEqual([])
    expect(s).toMatch(/respawn-pane -k -t "=\$SESSION:" "\$RESPAWN_CMD" 2>/)
  })

  it('stuck-modal-guard.sh respawn command, passed to respawn-pane as is', () => {
    const s = read('scripts/stuck-modal-guard.sh')
    const cmd = s.match(/local RESPAWN_CMD="(.*)"$/m)?.[1] ?? ''
    expect(shellControlAfterClaude(cmd, '$CLAUDE_Q ')).toEqual([])
    expect(s).toMatch(/respawn-pane -k -t "=\$SESSION:" "\$RESPAWN_CMD" 2>/)
  })

  it('watchdog.sh sub-agent relaunch, passed to new-session as is', () => {
    const s = read('scripts/watchdog.sh')
    const cmd = s.match(/^\s*CMD="(\$\{ISO_ENV\}.*)"$/m)?.[1] ?? ''
    expect(shellControlAfterClaude(cmd, '${CLAUDE_BIN} ')).toEqual([])
    expect(s).toMatch(/tmux new-session -d -s "\$SESSION_NAME" "\$CMD" 2>/)
  })

  it('agent-process.ts buildLaunchCmd, the only command of both new-session calls', () => {
    const s = read('src/web/agent-process.ts')
    const cmd = s.match(/const buildLaunchCmd = \(launchCwd: string\) => `(.*)`\.trimEnd\(\)$/m)?.[1] ?? ''
    expect(shellControlAfterClaude(cmd, '${claudeBin()} ')).toEqual([])
    expect([...s.matchAll(/\['new-session', '-d', '-s', session, buildLaunchCmd\(\w+\)\]/g)]).toHaveLength(2)
  })

  it('agent-process.ts remote launch runs buildRemoteLaunchCommand as is', () => {
    expect(read('src/web/agent-process.ts')).toMatch(/const cmd = buildRemoteLaunchCommand\([^\n]*\n\n\s*try \{\n\s*runTmux\(host, \['new-session', '-d', '-s', session, cmd\]/)
  })

  it('agent-worker.ts: the claude word is the last piece of the bash -lc string', () => {
    const m = read('src/web/agent-worker.ts').match(/`\$\{shArg\(claudeLaunchBin\)\}([^`]*)`\n\s*execFileSync\(TMUX, \['new-session', '-d', '-s', ctx\.session, '-c', ctx\.home, 'bash', '-lc', launch\]/)
    expect(m).not.toBeNull()
    expect(shellControlAfterClaude(`claude${m![1]}`, 'claude')).toEqual([])
  })

  it('channel-monitor main respawn command, every config shape (behaviour)', () => {
    const base = {
      claudePath: '/usr/local/bin/claude',
      pluginId: 'telegram@claude-plugins-official',
      model: 'claude-opus-4-8[1m]',
      channelStateEnv: { name: 'TELEGRAM_STATE_DIR', dir: '/opt/marveen/.claude/channels/telegram' },
    }
    const configs = [
      mainConfigDecisionForTest(),
      mainConfigDecisionForTest({ fleetToken: true }),
      mainConfigDecisionForTest({ isolatedConfigDir: '/opt/cfg', ownCredentials: true }),
      mainConfigDecisionForTest({ isolatedConfigDir: '/opt/cfg', tokenSecretId: 'plan-a' }),
      mainConfigDecisionForTest({ isolatedConfigDir: '/opt/cfg' }),
    ]
    for (const config of configs) {
      for (const continueSession of [false, true]) {
        const cmd = buildMainSessionRespawnCmd({
          ...base, config, continueSession,
          extraPluginIds: ['slack-channel@marveen'],
          extraSettingsPath: '/opt/marveen/store/main-extra.json',
        })
        expect(shellControlAfterClaude(cmd, '/usr/local/bin/claude ')).toEqual([])
      }
    }
  })

  it('channel-monitor: all three respawn-pane calls run that builder output as is', () => {
    const s = read('src/web/channel-monitor.ts')
    expect([...s.matchAll(/const claudeCmd = buildMainSessionRespawnCmd\(/g)]).toHaveLength(3)
    expect([...s.matchAll(/\['respawn-pane', '-k', '-t', exactTmuxTarget\(MAIN_CHANNELS_SESSION\), claudeCmd\]/g)]).toHaveLength(3)
  })

  it('ssh-tmux remote launch command (behaviour)', () => {
    for (const cont of [false, true]) {
      const cmd = buildRemoteLaunchCommand({ workdir: '/home/x/agents/a', model: 'claude-opus-4-8', continue: cont })
      expect(shellControlAfterClaude(cmd, ' claude ')).toEqual([])
    }
  })
})

// Every production file (not a test) whose code lines launch claude with
// --dangerously-skip-permissions through tmux new-session / respawn-pane is
// pinned above. A new tmux launcher has to be added here, with its own pin.
function* walk(dir: string): Generator<string> {
  for (const n of readdirSync(dir)) {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) { if (n !== '__tests__' && n !== 'node_modules') yield* walk(p) } else yield p
  }
}

describe('no tmux launch path is unpinned (enumeration)', () => {
  it('the tmux launcher files are exactly the pinned ones', () => {
    const files = [
      ...readdirSync(join(ROOT, 'scripts')).filter((f) => f.endsWith('.sh')).map((f) => join(ROOT, 'scripts', f)),
      ...[...walk(join(ROOT, 'src'))].filter((f) => f.endsWith('.ts')),
    ]
    const launchers: string[] = []
    for (const f of files) {
      const code = readFileSync(f, 'utf-8').split('\n')
        .filter((l) => { const t = l.trim(); return !t.startsWith('#') && !t.startsWith('//') && !t.startsWith('*') })
      if (code.some((l) => l.includes('--dangerously-skip-permissions')) && code.some((l) => /new-session|respawn-pane/.test(l))) {
        launchers.push(relative(ROOT, f))
      }
    }
    expect(launchers.sort()).toEqual([
      'scripts/channel-watchdog.sh',
      'scripts/channels.sh',
      'scripts/stuck-modal-guard.sh',
      'scripts/watchdog.sh',
      'src/web/agent-process.ts',
      'src/web/agent-worker.ts',
      'src/web/channel-monitor.ts',
    ])
  })
})
