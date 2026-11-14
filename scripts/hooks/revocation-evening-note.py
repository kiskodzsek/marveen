#!/usr/bin/env python3
"""PostToolUse hook (Bash): a revocation that may touch Patrik goes into his evening block on its own.

Why (retro 2026-11-13, Kernel c; card 7702bb13): on 11-12 08:01:28 an agent ran
`CLAUDE_CONFIG_DIR=agents/dave/.claude-config claude mcp logout higgsfield` (Viktor 38879, Klodel 38881 MEHET).
The login was Patrik's; nobody told him, and on 11-13 he had to log in again without knowing why (TG 18290,
hibanapló 11-13 15:16). Now every such command that ran writes one item to store/patrik-este-blokk.json
(scripts/lib/este_blokk.py), and the 18:05 evening message (napi-eredmeny-este skill) puts it in front of him.
Klodel decides there whether it was Patrik's; an agent's own test login shows up too, on purpose (a missed one
cost Patrik a login, a needless one costs a line).

What counts (in command position: line start, ; & | ( ` $( , a shell -c payload, a string handed to a call in inline
code (os.system('...'), execSync(`...`)), after VAR=... / env / sudo / npx / exec / command / nohup / timeout N, and
after a wrapper with its flags and words (WRAP_ARGS: sudo -u X, env -i A=b, timeout -s X N, time, eval '...', xargs,
npx -y, nice -n N ...; card 1a2eb541); a CLI by path (/usr/local/bin/claude, ~/.local/bin/claude) and flags between
the CLI and its subcommand (gh --hostname h auth logout) too):
  claude mcp logout|remove <server>, claude [auth] logout, <cli> [auth] logout|signout for gh vercel supabase
  netlify firebase heroku stripe npm docker wrangler fly flyctl railway doctl az tailscale codex gemini, op signout,
  gcloud auth revoke, aws sso logout, security delete-generic-password|delete-internet-password [-s <service>],
  git credential[-osxkeychain] reject|erase, curl ... https://<host>/.../revoke|logout|signout.
  A CLAUDE_CONFIG_DIR=.../agents/<name>/... in the command names whose config it was.
Not counted: the words inside a quoted argument (`git commit -m "gh auth logout"`), the later lines of a multi-line
quoted value or argument (`CMDS="probe<newline>claude mcp logout x"`, `echo '...<newline>gh auth logout'`: a newline
inside a closed quote is no command boundary, and an assignment's quoted value is one word; Viktor 42360, the 11-14
probe that put three false items in Patrik's block) unless a shell runs that quote (`bash -c '...'`, `eval "..."`,
`su -c`, `bash -c -- $'...'`, `bash <<< '...'`, `'...' | bash`, a $(...) or `...` inside "..."; Viktor 42401 LOW 1),
a heredoc body fed to anything
but a shell (`cat <<'E'` notes), a revocation inside a script file the command runs (that script calls
scripts/este-blokk-add.py itself), and a command that failed (PostToolUseFailure is not wired).
Only the matched phrase is written, never the command (it may carry a secret). Never blocks: always exit 0.
No secret in the phrase either (Viktor 41840 LOW 1; the item reaches Patrik's chat):
  - curl: the host only when it has a dot and does not look like a key, and no host at all when the URL carries
    userinfo (https://KEY:@host/...);
  - security -s <service>: a known service name, or [A-Za-z0-9._-] up to 32 that does not look like a key, else
    '-s <megadva>';
  - claude mcp <name>: a server name found in the MCP configs (.mcp.json of the install and the agents,
    ~/.claude.json, $CLAUDE_CONFIG_DIR/.claude.json), or [a-z][a-z0-9-] up to 24 that does not look like a key, else
    '<név nem ismert>' (after `claude mcp remove` the name is gone from the config, so the shape rule is the fallback).
  Looks like a key: a run of 4+ digits, upper+lower+digit mixed, or a known token prefix (sk_, ghp_, xox, AKIA, eyJ...).
  The shape rule is a fallback, not a proof: an all-lowercase key of up to 24 (mcp) / 32 (service) letters passes it
  (Viktor 41865 D); the names the configs know are the exact protection.
The agent: $CLAUDE_CONFIG_DIR's agents/<name> first (a sub-agent's own folder), the cwd only as a fallback (Viktor
41840 LOW 5: a sub-agent working in another agent's folder was named after the folder). A failure of the hook and a
parked item (a broken block) go to store/hook-errors.log (hook_errlog), not only to stderr nobody reads (LOW 3).
Only the first MAX_CMD characters are read (an unterminated-heredoc flood was quadratic: 20 000 took 7.6 s).
Known misses (after card 1a2eb541): the list form in inline code (subprocess.run(['gh', 'auth', 'logout'])), a
string a wrapper splits itself (env -S 'gh auth logout', npx -c '...'), a wrapper not in WRAP_ARGS whose flag takes a
word (su, runuser, ionice, taskset ...), a wrapper followed by more than MAX_ARGS words, a CLI named through a
variable, alias or $(which gh), a flag argument that starts with a quote (`gh --hostname "h" auth logout`), and the
later lines of a multi-line quoted string a shell other than `sh -c`/`eval` runs (`ssh host '...'`; it runs on
another machine), and an assignment before the command past ASSIGN_VALUE's bounds (a bare run over 256, a quoted
part over 2000, more than 8 quoted parts: no natural command; the bounds keep the regex linear; Viktor 42401 INFO 1).
Known extra items (a needless line): a call position inside quoted text is still read as one
(`echo 'os.system("gh auth logout")'`, a `$(gh auth logout)` inside '...'), as before.
Wiring: .claude/settings.json PostToolUse, matcher "Bash" (every agent). Tests: revocation-evening-note_test.py.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib'))

# Command position, then up to six words that may stand before the command. Bounded, so a long run of them stays
# linear (the keychain gate's ReDoS lessons, card bc009036). A string handed to a call in inline code
# (`python3 -c "import os; os.system('gh auth logout')"`, execSync(`...`)) is a command position too (Viktor 41840
# LOW 4); a wrapper with flags (`sudo -u root`, `env -i`, `timeout -s KILL 5`) is read by wrap_marks() below.
# An assignment's value is one word, a quoted part with its blanks included (`CMDS="probe claude mcp logout x"` is
# no logout; Viktor 42360): bare characters and closed quotes, each bounded, a quote not closed on its line no value.
# Bare runs never meet, so there is no backtracking between them (`a=b=c=d ` x 12 000 stays linear).
ASSIGN_VALUE = r'[^\s;&|\'"]{0,256}(?:(?:"[^"\n]{0,2000}"|\'[^\'\n]{0,2000}\')[^\s;&|\'"]{0,256}){0,8}'
POS = (r'(?:^|[;&|(\n`]|\$\(|[ \t]-[A-Za-z]*c[ \t]+[\'"]'
       r'|\b(?:system|popen|getoutput|getstatusoutput|check_output|check_call|call|run|Popen|execSync|spawnSync|exec)'
       r'\([ \t]*\[?[ \t]*[fbr]?[\'"`])[ \t]*'
       r'(?:(?:\w+=' + ASSIGN_VALUE + r'|env|sudo|npx|exec|command|nohup|timeout[ \t]+[\d.]+[smh]?)[ \t]+){0,6}')
PFX = r'(?:[\w.~/-]{0,256}/)?'  # a CLI by path: /usr/local/bin/claude, ~/.local/bin/claude (Viktor 41840 LOW 4)
# flags between the CLI and its subcommand (`gh --hostname github.com auth logout`); an argument never starts with a
# quote or a dash, so `claude -p "please logout"` is no logout
FLAGS = r'(?:[ \t]+-{1,2}[\w-]+(?:=[^\s;&|]*|[ \t]+[^\s;&|\'"-][^\s;&|]*)?){0,4}'
NAME = r'["\']?([\w.@-]{1,64})["\']?'
CLIS = r'(gh|vercel|supabase|netlify|firebase|heroku|stripe|npm|docker|wrangler|flyctl|fly|railway|doctl|az|tailscale|codex|gemini)'
RULES = [
    ('claude-mcp', re.compile(POS + PFX + r'claude' + FLAGS + r'[ \t]+mcp[ \t]+(logout|remove)'
                              r'((?:[ \t]+-{1,2}[\w-]+(?:[ =][\w.-]+)?){0,4})[ \t]+' + NAME)),
    # no name: it comes from stdin or a placeholder (`xargs claude mcp logout`, `xargs -I {} ... remove {}`), so it
    # is not known; only flags without a value and at most one word that is no name before the end, so
    # `claude mcp remove --verbose higgsfield` is the rule above's alone
    ('claude-mcp-noname', re.compile(POS + PFX + r'claude' + FLAGS + r'[ \t]+mcp[ \t]+(logout|remove)'
                              r'((?:[ \t]+-{1,2}[\w-]+){0,4})()(?:[ \t]+[^\s;&|)\'"`]{0,32}[^\w.@\s;&|)\'"`-][^\s;&|)\'"`]{0,32})?'
                              r'[ \t]*(?=$|[;&|\n)`\'"])')),
    # a claude flag takes no separate word here: `claude --debug mcp logout x` is the mcp rule's, not a logout
    ('claude-logout', re.compile(POS + PFX + r'claude(?:[ \t]+-{1,2}[\w-]+(?:=[^\s;&|]*)?){0,4}'
                                 r'[ \t]+(?:auth[ \t]+)?(logout)\b')),
    ('cli-logout', re.compile(POS + PFX + CLIS + FLAGS + r'[ \t]+(?:auth[ \t]+)?(logout|signout)\b')),
    ('op-signout', re.compile(POS + PFX + r'(op)' + FLAGS + r'[ \t]+(signout)\b')),
    ('gcloud-revoke', re.compile(POS + PFX + r'(gcloud)' + FLAGS + r'[ \t]+auth[ \t]+(revoke)\b')),
    ('aws-sso-logout', re.compile(POS + PFX + r'(aws)' + FLAGS + r'[ \t]+sso[ \t]+(logout)\b')),
    ('keychain-delete', re.compile(POS + PFX + r'security[ \t]+(delete-(?:generic|internet)-password)\b'
                                   r'(?:[^;&|\n]{0,300}?[ \t]-s[ \t]+(?:["\']([^"\'\n]{1,64})["\']|([^\s;&|"\']{1,64})))?')),
    ('git-credential', re.compile(POS + PFX + r'git' + FLAGS + r'[ \t]+credential(?:-osxkeychain)?[ \t]+(reject|erase)\b')),
    ('http-revoke', re.compile(POS + PFX + r'curl\b[^;&|\n]{0,2000}?https?://(?:([^/@\s;&|\'"]{0,200})@)?([\w.-]{1,100})'
                               r'[^\s;&|\'"]{0,500}?/(revoke|logout|signout)\b')),
]

# Wrappers whose flags take a word, or that take positional words, before the command they run (Viktor 41840 LOW 4,
# card 1a2eb541): wrapper -> (short flags taking the next word, long flags taking the next word, positional words).
# The keychain gate's table (card 3085a683), plus time, eval, xargs and npx.
WRAP_ARGS = {
    'sudo': ('CDghprRtTuU', {'--user', '--group', '--close-from', '--chdir', '--host', '--prompt', '--role', '--type',
                             '--command-timeout', '--other-user', '--chroot'}, 0),
    'doas': ('Cu', set(), 0),
    'env': ('uCP', {'--unset', '--chdir'}, 0),
    'timeout': ('sk', {'--signal', '--kill-after'}, 1),
    'time': ('of', {'--output', '--format'}, 0),
    'nice': ('n', {'--adjustment'}, 0),
    'nohup': ('', set(), 0),
    'exec': ('a', set(), 0),
    'command': ('', set(), 0),
    'eval': ('', set(), 0),
    'xargs': ('IJLnPEdsaRS', {'--max-args', '--max-procs', '--delimiter', '--arg-file', '--max-lines', '--replace',
                              '--eof', '--max-chars'}, 0),
    'npx': ('p', {'--package'}, 0),
    'stdbuf': ('ioe', {'--input', '--output', '--error'}, 0),
    'caffeinate': ('tw', set(), 0),
}
WRAP_RX = re.compile(POS + PFX + r'(' + '|'.join(sorted(WRAP_ARGS, key=len, reverse=True)) + r')(?=[ \t])')
NEXT_WRAP_RX = re.compile(PFX + r'(' + '|'.join(sorted(WRAP_ARGS, key=len, reverse=True)) + r')(?=[ \t])')
WRAP_END = ';&|\n)`'
MAX_ARGS = 64
WRAP_PASSES = 4


def paren_close(text):
    """Where each `(` closes ({index of '(': index of ')'}), in one pass; an unclosed one is missing."""
    close, stack = {}, []
    for i, ch in enumerate(text):
        if ch == '(':
            stack.append(i)
        elif ch == ')' and stack:
            close[stack.pop()] = i
    return close


def wrap_command_start(text, i, name, close):
    """Index of the first word of the command `name` runs, its words starting at i; None if there is none in this
    command (a ; & | newline ) ` or the end comes first, an unclosed quote or $(, or more than MAX_ARGS words: the hook
    never blocks, so a flood past the cap is only not read). One pass over the words, no regex over them (linear). A
    quoted word, a $(...) (`close`, from paren_close), and a backslash with the next character stay in one word:
    `sudo -u $(timeout -s KILL 5 vercel logout) ls` runs ls, and the $(...) is walked on its own (its `$(` is a
    command position)."""
    short, whole, positional = WRAP_ARGS[name]
    n = len(text)
    need_arg = flags_done = False
    for _ in range(MAX_ARGS + 1):
        while i < n and text[i] in ' \t':
            i += 1
        if i >= n or text[i] in WRAP_END:
            return None
        start = i
        while i < n and text[i] not in ' \t' and text[i] not in WRAP_END:
            if text[i] in '"\'':
                j = text.find(text[i], i + 1)
                if j < 0:
                    return None
                i = j + 1
            elif text[i] == '$' and i + 1 < n and text[i + 1] == '(':
                j = close.get(i + 1)
                if j is None:
                    return None
                i = j + 1
            elif text[i] == '\\':
                i += 2
            else:
                i += 1
        word = text[start:i]
        if need_arg:
            need_arg = False
            continue
        if not flags_done and len(word) > 1 and word[0] == '-':
            if word == '--':
                flags_done = True
            elif word.startswith('--'):
                need_arg = '=' not in word and word in whole
            else:
                for k, c in enumerate(word[1:]):
                    if c in short:
                        need_arg = k == len(word) - 2  # `-uroot` carries its own word
                        break
            continue
        if re.match(r'\w+=', word):  # env A=b, sudo A=b
            continue
        if positional:
            positional -= 1
            continue
        return start
    return None


def wrap_marks(text):
    """text with the start of each command a wrapper runs made a command position: the blank before it becomes a
    `;`, a quote opening it (`eval 'claude mcp logout x'`) becomes a `;`. A wrapper right at that command is walked in
    the same pass; a later pass finds what a mark exposed elsewhere. The plain text is judged too (a mark only adds).
    Every wrapper in command position is walked, a later one of a chain too: unlike the keychain gate (its `reach`,
    Viktor 41970 LOW 3), a quote is no command position here, so finditer does not find a chain's later wrappers, and
    a wrapper inside a flag's $(...) must be walked (`sudo -u $(timeout -s KILL 5 vercel logout) ls`)."""
    for _ in range(WRAP_PASSES):
        chars = None
        close = paren_close(text)
        for m in WRAP_RX.finditer(text):
            i, name = m.end(), m.group(1)
            while True:
                k = wrap_command_start(text, i, name, close)
                if k is None:
                    break
                at = k if text[k] in '"\'' else k - 1
                if text[at] != ';':
                    chars = chars or list(text)
                    chars[at] = ';'
                nxt = NEXT_WRAP_RX.match(text, k + 1 if text[k] in '"\'' else k)
                if not nxt:
                    break
                i, name = nxt.end(), nxt.group(1)
        if chars is None:
            return text
        text = ''.join(chars)
    return text
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
    """Drop heredoc bodies, except one fed to a shell (`bash <<'E' ... E` runs its lines). A `<<` with no terminator
    line after it is kept as text: it is often no heredoc at all (`$((1<<4))`, `echo "see <<EOF doc"`,
    `python3 -c "print(1<<2)"`), and dropping the rest hid a revocation after it (Viktor 41865 A; a needless item
    costs a line, a missed one cost Patrik a login). Line by line, the next terminator looked up in an index: a lazy regex
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
        if e >= len(ends):  # no terminator: not read as a heredoc, the line stays
            out.append(ln)
            i += 1
            continue
        j = ends[e]
        if SHELL_FEED_RX.search(ln[:m.start()]):
            out.extend(lines[i:j + 1])
        else:
            out.append(ln)
        i = j + 1
    return '\n'.join(out)


SHELLS = {'bash', 'sh', 'zsh', 'dash', 'ksh', 'fish'}
C_RUNNERS = SHELLS | {'su', 'runuser', 'script'}
CMD_SEP = ';&|\n(`'
PIPE_TO_SHELL = re.compile(r'[ \t]*\|[ \t]*(?:(?:sudo|env|exec|command|nohup)[ \t]+)*(?:\S*/)?(?:bash|sh|zsh|dash|ksh|fish)(?![\w-])')


def runs_as_shell(text, q, end):
    """True when the quote opening at q (closing at end) is a string a shell runs line by line: `bash -c '...'`,
    `sh -lc "..."`, `eval '...'`, `bash -c $'...'`, `bash -c -- '...'`, `su -c '...'`, `bash <<< '...'`, `... | bash`.
    Only the current simple command is looked at (back to the last ; & | newline ( `, at most 300 characters), and
    only for a quote that spans a newline, so the cost stays small."""
    if PIPE_TO_SHELL.match(text, end + 1):
        return True
    seg = text[max(0, q - 300):q]
    if seg.endswith('$'):
        seg = seg[:-1]
    words = seg[max(seg.rfind(c) for c in CMD_SEP) + 1:].split()
    if words and words[-1] == '--':
        words.pop()
    if not words:
        return False
    if words[-1] == 'eval':
        return True
    if words[-1] == '<<<':
        return any(w.rsplit('/', 1)[-1] in SHELLS for w in words[:-1])
    if not re.fullmatch(r'-[A-Za-z]*c', words[-1]):
        return False
    return any(w.rsplit('/', 1)[-1] in C_RUNNERS for w in words[:-1])


def blank_quoted_newlines(text):
    """text with every newline inside a closed '...', $'...' or "..." made a blank (same length, so positions still
    compare): a quoted value is one word, its later lines are no command position (Viktor 42360 LOW: a multi-line
    quoted value or `echo "..."` naming `claude mcp logout x` on a line of its own put a false item in Patrik's
    evening block). Kept: a quote a shell runs (`bash -c '...'`, `eval "..."`: its lines are commands), a $(...) or
    `...` inside "..." (it runs), and an unclosed quote (a missed revocation cost Patrik a login, a needless line
    costs a line). One pass, a backslash escapes outside '...', a # at a word start is a comment to the line end."""
    stack = []  # [kind, start, newline positions]; kind: sq ansi dq sub bt
    blank = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        top = stack[-1][0] if stack else None
        if top == 'sq':
            if ch == "'":
                kind, q, nl = stack.pop()
                if nl and not runs_as_shell(text, q, i):
                    blank.extend(nl)
            elif ch == '\n':
                stack[-1][2].append(i)
            i += 1
            continue
        if ch == '\\':
            i += 2
            continue
        if top in ('dq', 'ansi'):
            closing = '"' if top == 'dq' else "'"
            if ch == closing:
                kind, q, nl = stack.pop()
                if nl and not runs_as_shell(text, q, i):
                    blank.extend(nl)
            elif ch == '\n':
                stack[-1][2].append(i)
            elif top == 'dq' and ch == '$' and text.startswith('$(', i):
                stack.append(['sub', i, []])
                i += 2
                continue
            elif top == 'dq' and ch == '`':
                stack.append(['bt', i, []])
            i += 1
            continue
        # unquoted, or inside a $(...) / `...`: shell text
        if ch == "'":
            stack.append(['ansi' if i > 0 and text[i - 1] == '$' else 'sq', i, []])
        elif ch == '"':
            stack.append(['dq', i, []])
        elif ch == '$' and text.startswith('$(', i):
            stack.append(['sub', i, []])
            i += 2
            continue
        elif ch == ')' and top == 'sub':
            stack.pop()
        elif ch == '`':
            if top == 'bt':
                stack.pop()
            else:
                stack.append(['bt', i, []])
        elif ch == '#' and (i == 0 or text[i - 1] in ' \t\n;&|('):
            j = text.find('\n', i)
            i = n if j < 0 else j
            continue
        i += 1
    if not blank:
        return text
    chars = list(text)
    for k in blank:
        chars[k] = ' '
    return ''.join(chars)


def phrases(cmd):
    """The revocations in a command, as short phrases (no command text beyond the match)."""
    text = blank_quoted_newlines(strip_heredocs(cmd[:MAX_CMD].replace('\\\n', ' ')))
    marked = wrap_marks(text)
    out = []
    known = None
    named = set()  # where the named claude-mcp rule matched (a mark keeps the length: positions compare)
    for kind, rx in RULES:
        for m in [m for t in ([text] if marked == text else [text, marked]) for m in rx.finditer(t)]:
            g = [x for x in m.groups() if x]
            if kind == 'claude-mcp':
                named.add(m.start(1))
            if kind == 'claude-mcp-noname' and m.start(1) in named:
                continue
            if kind in ('claude-mcp', 'claude-mcp-noname'):
                if known is None:
                    known = known_mcp_names()
                name = m.group(3)
                p = f'claude mcp {m.group(1)} {safe_mcp_name(name, known) if name else "<név nem ismert>"}'
            elif kind == 'claude-logout':
                p = 'claude logout'
            elif kind == 'keychain-delete':
                svc = m.group(2) or m.group(3)
                p = f'security {m.group(1)}' + (f' -s {safe_service(svc)}' if svc else '')
            elif kind == 'http-revoke':
                # userinfo in the URL (https://KEY:@host): no host either, the key may sit right before it. A host
                # is written only with a dot and not key-like: a userinfo with a "/" (https://KEY/x:@host) read its
                # first part as the host, and a host label can be a key (Viktor 41865 B)
                host = m.group(2)
                if m.group(1) is not None:
                    p = f'HTTP {m.group(3)} (host rejtve: belépési adat az URL-ben)'
                elif '.' not in host or secretish(host):
                    p = f'HTTP {m.group(3)} (host rejtve)'
                else:
                    p = f'HTTP {m.group(3)} ({host})'
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
