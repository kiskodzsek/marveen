#!/usr/bin/env python3
"""PostToolUse hook (Bash): a revocation that may touch Patrik goes into his evening block on its own.

Why (retro 2026-11-13, Kernel c; card 7702bb13): on 11-12 08:01:28 an agent ran
`CLAUDE_CONFIG_DIR=agents/dave/.claude-config claude mcp logout higgsfield` (Viktor 38879, Klodel 38881 MEHET).
The login was Patrik's; nobody told him, and on 11-13 he had to log in again without knowing why (TG 18290,
hibanapló 11-13 15:16). Now every such command that ran writes one item to store/patrik-este-blokk.json
(scripts/lib/este_blokk.py), and the 18:05 evening message (napi-eredmeny-este skill) puts it in front of him.
Klodel decides there whether it was Patrik's; an agent's own test login shows up too, on purpose (a missed one
cost Patrik a login, a needless one costs a line).

What counts (in command position: line start, ; & | ( ` $( , a shell -c payload, after VAR=... / env / sudo / npx
/ exec / command / nohup / timeout N):
  claude mcp logout|remove <server>, claude [auth] logout, <cli> [auth] logout|signout for gh vercel supabase
  netlify firebase heroku stripe npm docker wrangler fly flyctl railway doctl az tailscale codex gemini, op signout,
  gcloud auth revoke, aws sso logout, security delete-generic-password|delete-internet-password [-s <service>],
  git credential[-osxkeychain] reject|erase, curl ... https://<host>/.../revoke|logout|signout.
  A CLAUDE_CONFIG_DIR=.../agents/<name>/... in the command names whose config it was.
Not counted: the words inside a quoted argument (`git commit -m "gh auth logout"`), a heredoc body fed to anything
but a shell (`cat <<'E'` notes), a revocation inside a script file the command runs (that script calls
scripts/este-blokk-add.py itself), and a command that failed (PostToolUseFailure is not wired).
Only the matched phrase is written, never the command (it may carry a secret). Never blocks: always exit 0.
Wiring: .claude/settings.json PostToolUse, matcher "Bash" (every agent). Tests: revocation-evening-note_test.py.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib'))

# Command position, then up to six words that may stand before the command. Bounded, so a long run of them stays
# linear (the keychain gate's ReDoS lessons, card bc009036).
POS = (r'(?:^|[;&|(\n`]|\$\(|[ \t]-[A-Za-z]*c[ \t]+[\'"])[ \t]*'
       r'(?:(?:\w+=[^\s;&|]*|env|sudo|npx|exec|command|nohup|timeout[ \t]+[\d.]+[smh]?)[ \t]+){0,6}')
NAME = r'["\']?([\w.@-]{1,64})["\']?'
CLIS = r'(gh|vercel|supabase|netlify|firebase|heroku|stripe|npm|docker|wrangler|flyctl|fly|railway|doctl|az|tailscale|codex|gemini)'
RULES = [
    ('claude-mcp', re.compile(POS + r'claude[ \t]+mcp[ \t]+(logout|remove)((?:[ \t]+-{1,2}[\w-]+(?:[ =][\w.-]+)?){0,4})'
                              r'[ \t]+' + NAME)),
    ('claude-logout', re.compile(POS + r'claude[ \t]+(?:auth[ \t]+)?(logout)\b')),
    ('cli-logout', re.compile(POS + CLIS + r'[ \t]+(?:auth[ \t]+)?(logout|signout)\b')),
    ('op-signout', re.compile(POS + r'(op)[ \t]+(signout)\b')),
    ('gcloud-revoke', re.compile(POS + r'(gcloud)[ \t]+auth[ \t]+(revoke)\b')),
    ('aws-sso-logout', re.compile(POS + r'(aws)[ \t]+sso[ \t]+(logout)\b')),
    ('keychain-delete', re.compile(POS + r'(?:/usr/bin/)?security[ \t]+(delete-(?:generic|internet)-password)\b'
                                   r'(?:[^;&|\n]{0,300}?[ \t]-s[ \t]+(?:["\']([^"\'\n]{1,64})["\']|([^\s;&|"\']{1,64})))?')),
    ('git-credential', re.compile(POS + r'git[ \t]+credential(?:-osxkeychain)?[ \t]+(reject|erase)\b')),
    ('http-revoke', re.compile(POS + r'curl\b[^;&|\n]{0,2000}?https?://([\w.-]{1,100})[^\s;&|\'"]{0,500}?/(revoke|logout|signout)\b')),
]
CONFIG_RX = re.compile(r'CLAUDE_CONFIG_DIR=["\']?[^\s"\']*?/?agents/([a-z0-9_-]{1,40})/')
HEREDOC_RX = re.compile(r'<<-?[ \t]*([\'"]?)(\w{1,40})\1[^\n]*\n(.*?)\n[ \t]*\2(?=\n|$)', re.S)
SHELL_FEED_RX = re.compile(r'\b(?:bash|sh|zsh|dash|ksh|source)\b[^\n]*$')
AGENT_RX = re.compile(r'/agents/([a-z0-9_-]{1,40})(?:/|$)')


def strip_heredocs(cmd):
    """Drop heredoc bodies, except one fed to a shell (`bash <<'E' ... E` runs its lines)."""
    def keep_or_drop(m):
        head = cmd[cmd.rfind('\n', 0, m.start()) + 1:m.start()]
        return m.group(0) if SHELL_FEED_RX.search(head) else '<<' + m.group(2) + '\n'
    return HEREDOC_RX.sub(keep_or_drop, cmd)


def phrases(cmd):
    """The revocations in a command, as short phrases (no command text beyond the match)."""
    text = strip_heredocs(cmd.replace('\\\n', ' '))
    out = []
    for kind, rx in RULES:
        for m in rx.finditer(text):
            g = [x for x in m.groups() if x]
            if kind == 'claude-mcp':
                p = f'claude mcp {m.group(1)} {m.group(3)}'
            elif kind == 'claude-logout':
                p = 'claude logout'
            elif kind == 'keychain-delete':
                svc = m.group(2) or m.group(3)
                p = f'security {m.group(1)}' + (f' -s {svc}' if svc else '')
            elif kind == 'http-revoke':
                p = f'HTTP {m.group(2)} ({m.group(1)})'
            elif kind == 'git-credential':
                p = f'git credential {m.group(1)}'
            else:
                p = ' '.join(g[:2])
            if p not in out:
                out.append(p)
    return out


def agent_of(payload):
    for src in (payload.get('cwd') if isinstance(payload.get('cwd'), str) else '', os.environ.get('CLAUDE_CONFIG_DIR', '')):
        m = AGENT_RX.search(src or '')
        if m:
            return m.group(1)
    return 'fő ágens'


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or payload.get('tool_name') != 'Bash':
            return 0
        ti = payload.get('tool_input') or {}
        cmd = ti.get('command') if isinstance(ti, dict) else None
        if not isinstance(cmd, str) or not cmd:
            return 0
        found = phrases(cmd)
        if not found:
            return 0
        import este_blokk
        cfg = CONFIG_RX.search(cmd)
        cfg_note = f' ({cfg.group(1)} configjában)' if cfg else ''
        agent = agent_of(payload)
        for p in found:
            este_blokk.add_item(
                'visszavonas',
                f'{agent} visszavonást futtatott: {p}{cfg_note}. Ha ez Patrik belépése vagy kulcsa volt, '
                'újra be kell lépnie, vagy új kulcs kell.',
                'revocation-evening-note hook (Bash)', agens=agent,
                javaslat='Este mondd ki Patriknak; ha a belépés kell, egyeztesd az újra-belépés idejét.')
    except Exception as e:  # never block, never lose the tool call; a note on stderr only
        sys.stderr.write(f'revocation-evening-note: {e.__class__.__name__}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
