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
No secret in the phrase either (Viktor 41840 LOW 1; the item reaches Patrik's chat):
  - curl: the host only, and no host at all when the URL carries userinfo (https://KEY:@host/...);
  - security -s <service>: a known service name, or [A-Za-z0-9._-] up to 32 that does not look like a key, else
    '-s <megadva>';
  - claude mcp <name>: a server name found in the MCP configs (.mcp.json of the install and the agents,
    ~/.claude.json, $CLAUDE_CONFIG_DIR/.claude.json), or [a-z][a-z0-9-] up to 24 that does not look like a key, else
    '<név nem ismert>' (after `claude mcp remove` the name is gone from the config, so the shape rule is the fallback).
  Looks like a key: a run of 4+ digits, upper+lower+digit mixed, or a known token prefix (sk_, ghp_, xox, AKIA, eyJ...).
The agent: $CLAUDE_CONFIG_DIR's agents/<name> first (a sub-agent's own folder), the cwd only as a fallback (Viktor
41840 LOW 5: a sub-agent working in another agent's folder was named after the folder). A failure of the hook and a
parked item (a broken block) go to store/hook-errors.log (hook_errlog), not only to stderr nobody reads (LOW 3).
Only the first MAX_CMD characters are read (an unterminated-heredoc flood was quadratic: 20 000 took 7.6 s).
Known misses (Viktor 41840 LOW 4, follow-up card): claude by path (/usr/local/bin/claude, ~/.local/bin/claude),
wrapper flags (env -i, sudo -u X, timeout -s X N), time / eval / xargs before the CLI, npx -y, a flag between the CLI
and auth (gh --hostname h auth logout), and a revocation inside inline code (python3 -c "os.system(...)").
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
    ('http-revoke', re.compile(POS + r'curl\b[^;&|\n]{0,2000}?https?://(?:([^/@\s;&|\'"]{0,200})@)?([\w.-]{1,100})'
                               r'[^\s;&|\'"]{0,500}?/(revoke|logout|signout)\b')),
]
MAX_CMD = 100000
KNOWN_SERVICES = {'Claude Code-credentials', 'Claude Code', 'Claude Safe Storage'}
SECRETISH_RX = re.compile(r'\d{4}|^(?:sk|rk|pk)[_-]|^(?:gh[pousr]_|github_pat_|xox|AKIA|ASIA|eyJ|glpat-|AIza|ya29\.)')
SAFE_SVC_RX = re.compile(r'[A-Za-z0-9._-]{1,32}')
SAFE_MCP_RX = re.compile(r'[a-z][a-z0-9-]{0,23}')


def secretish(word):
    mixed = re.search(r'[a-z]', word) and re.search(r'[A-Z]', word) and re.search(r'\d', word)
    return bool(mixed or SECRETISH_RX.search(word))


def mcp_config_files():
    seam = os.environ.get('REVOCATION_MCP_CONFIGS')
    if seam is not None:
        return [x for x in seam.split(os.pathsep) if x]
    install = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    files = [os.path.join(install, '.mcp.json'), os.path.expanduser('~/.claude.json')]
    if os.environ.get('CLAUDE_CONFIG_DIR'):
        files.append(os.path.join(os.environ['CLAUDE_CONFIG_DIR'], '.claude.json'))
    try:
        files += [os.path.join(install, 'agents', a, '.mcp.json') for a in sorted(os.listdir(os.path.join(install, 'agents')))]
    except OSError:
        pass
    return files


def known_mcp_names():
    """Server names (keys only) from the MCP configs; a file that is missing, too big or not JSON is skipped."""
    names = set()
    for fp in mcp_config_files()[:64]:
        try:
            if os.path.getsize(fp) > 32 * 1024 * 1024:
                continue
            with open(fp, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        blocks = [data.get('mcpServers')]
        projects = data.get('projects')
        if isinstance(projects, dict):
            blocks += [v.get('mcpServers') for v in projects.values() if isinstance(v, dict)]
        for b in blocks:
            if isinstance(b, dict):
                names.update(k for k in b if isinstance(k, str))
    return names


def safe_mcp_name(name, known):
    if name in known or (SAFE_MCP_RX.fullmatch(name) and not secretish(name)):
        return name
    return '<név nem ismert>'


def safe_service(svc):
    if svc in KNOWN_SERVICES or (SAFE_SVC_RX.fullmatch(svc) and not secretish(svc)):
        return svc
    return '<megadva>'


CONFIG_RX = re.compile(r'CLAUDE_CONFIG_DIR=["\']?[^\s"\']*?/?agents/([a-z0-9_-]{1,40})/')
HEREDOC_OPEN_RX = re.compile(r'(?<!<)<<(?!<)-?[ \t]*([\'"]?)(\w{1,40})\1')
SHELL_FEED_RX = re.compile(r'\b(?:bash|sh|zsh|dash|ksh|source)\b[^\n]*$')
AGENT_RX = re.compile(r'/agents/([a-z0-9_-]{1,40})(?:/|$)')


def strip_heredocs(cmd):
    """Drop heredoc bodies, except one fed to a shell (`bash <<'E' ... E` runs its lines). An unterminated heredoc's
    body is the rest of the text (as in bash). Line by line, the next terminator looked up in an index: a lazy regex
    from every `<<` to its terminator was quadratic on unterminated ones (Viktor 41840 INFO 6: 20 000 took 7.6 s).
    One heredoc per line is read (`cat <<A <<B` drops A's body only)."""
    import bisect
    lines = cmd.split('\n')
    where = {}
    for k, ln in enumerate(lines):
        where.setdefault(ln.strip(' \t'), []).append(k)
    out = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = HEREDOC_OPEN_RX.search(ln)
        if not m:
            out.append(ln)
            i += 1
            continue
        ends = where.get(m.group(2), [])
        e = bisect.bisect_right(ends, i)
        j = ends[e] if e < len(ends) else len(lines)  # no terminator: the body runs to the end
        if SHELL_FEED_RX.search(ln[:m.start()]):
            out.extend(lines[i:j + 1])
        else:
            out.append(ln)
        i = j + 1
    return '\n'.join(out)


def phrases(cmd):
    """The revocations in a command, as short phrases (no command text beyond the match)."""
    text = strip_heredocs(cmd[:MAX_CMD].replace('\\\n', ' '))
    out = []
    known = None
    for kind, rx in RULES:
        for m in rx.finditer(text):
            g = [x for x in m.groups() if x]
            if kind == 'claude-mcp':
                if known is None:
                    known = known_mcp_names()
                p = f'claude mcp {m.group(1)} {safe_mcp_name(m.group(3), known)}'
            elif kind == 'claude-logout':
                p = 'claude logout'
            elif kind == 'keychain-delete':
                svc = m.group(2) or m.group(3)
                p = f'security {m.group(1)}' + (f' -s {safe_service(svc)}' if svc else '')
            elif kind == 'http-revoke':
                # userinfo in the URL (https://KEY:@host): no host either, the key may sit right before it
                p = f'HTTP {m.group(3)} (' + ('host rejtve: belépési adat az URL-ben' if m.group(1) is not None
                                              else m.group(2)) + ')'
            elif kind == 'git-credential':
                p = f'git credential {m.group(1)}'
            else:
                p = ' '.join(g[:2])
            if p not in out:
                out.append(p)
    return out


def agent_of(payload):
    for src in (os.environ.get('CLAUDE_CONFIG_DIR', ''), payload.get('cwd') if isinstance(payload.get('cwd'), str) else ''):
        m = AGENT_RX.search(src or '')
        if m:
            return m.group(1)
    return 'fő ágens'


def main():
    try:  # input that is not a Bash call is not a revocation: quiet, no error-log line
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or payload.get('tool_name') != 'Bash':
            return 0
        ti = payload.get('tool_input') or {}
        cmd = ti.get('command') if isinstance(ti, dict) else None
        if not isinstance(cmd, str) or not cmd:
            return 0
    except Exception:
        return 0
    try:
        found = phrases(cmd)
        if not found:
            return 0
        import este_blokk
        cfg = CONFIG_RX.search(cmd)
        cfg_note = f' ({cfg.group(1)} configjában)' if cfg else ''
        agent = agent_of(payload)
        for p in found:
            res = este_blokk.add_item(
                'visszavonas',
                f'{agent} visszavonást futtatott: {p}{cfg_note}. Ha ez Patrik belépése vagy kulcsa volt, '
                'újra be kell lépnie, vagy új kulcs kell.',
                'revocation-evening-note hook (Bash)', agens=agent,
                javaslat='Este mondd ki Patriknak; ha a belépés kell, egyeztesd az újra-belépés idejét.')
            if res == 'parked':
                errlog('a blokk-fájl nem JSON-lista: a tétel a .hiba.jsonl-be került (a drain visszaadja)')
    except Exception as e:  # never block, never lose the tool call; the error goes to the hook error log
        sys.stderr.write(f'revocation-evening-note: {e.__class__.__name__}\n')
        # an OSError names the file and the reason; other exceptions only their type (no command text)
        errlog('a tétel nem került a blokkba', e if isinstance(e, OSError) else None, e.__class__.__name__)
    return 0


def errlog(msg, exc=None, kind=None):
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import hook_errlog
        hook_errlog.report('revocation-evening-note', msg + (f' ({kind})' if kind and exc is None else ''), exc)
    except Exception:
        pass


if __name__ == '__main__':
    sys.exit(main())
