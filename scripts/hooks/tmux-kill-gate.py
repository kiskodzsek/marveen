#!/usr/bin/env python3
"""tmux-kill-gate.py -- PreToolUse(Bash) gate: no agent shell kills the LIVE tmux server or an agent's session.

Why (card ad7edaec, Klodel 43120; Viktor 43117): on 2026-11-15 16:45:44 a measurement meant for an isolated tmux
server ran `tmux kill-server` against the LIVE one, and every agent session dropped at once. The isolation was
TMUX_TMPDIR, and it does not isolate: measured on tmux 3.8 (2026-11-15), with $TMUX set (every agent shell runs
inside tmux) tmux talks to the $TMUX socket whatever TMUX_TMPDIR says, and even with $TMUX unset a TMUX_TMPDIR
that does not exist falls back to the live /private/tmp/tmux-<uid>/default. Only -L <name> and -S <path> override
$TMUX (measured). So:

  BLOCK, on the live server (no -L/-S, -L default, or -S to the live socket / any .../tmux-<uid>/default):
    - kill-server (any alias or unique prefix: tmux accepts kill-ser, measured);
    - kill-session / kill-window / kill-pane, unlink-window -k, respawn-pane/-window -k, when the target is or may
      be an agent's session: no -t (the CALLER's own session, e.g. agent-kernel), -a (everything but the target),
      a target starting with agent- or klodel-channels, a PREFIX of those (tmux prefix-matches session names:
      kill-session -t agent killed agent-x, measured), a glob, an id ($n @n %n), or an expanded value;
    - pkill / killall with a tmux pattern, kill with $(pgrep ... tmux).
  ALLOW: everything with an explicit -L <name> (not default) or -S <path> that is not the live socket; every other
  tmux command (send-keys, capture-pane, list-*, new-session ...); kill-session -t <a plain non-agent name>.

Read through the shared lexer (scripts/lib/shell_lex.py, card fae0712e): quotes, $( ), backticks, ;, &&, |, and
heredoc bodies are separated the way bash does. Followed: VAR=value prefixes, env/command/exec/nohup/nice/time/
sudo/timeout/xargs/caffeinate wrappers, sh/bash/zsh -c payloads, eval, a heredoc fed to a shell, tmux -c, and the
arguments of every tmux subcommand (send-keys "tmux kill-server" Enter would run it in a pane).
A $NAME / ${NAME} socket or target resolves only to a LITERAL value assigned earlier in the same command
(L=probe; tmux -L $L ...); an unknown, reassigned or prefix-assigned one stays dynamic, i.e. live.
Interpreter code (the 16:45 incident itself: cat > probe.mts <<'EOF' ... execFileSync('tmux', ['kill-server'])
... EOF; node probe.mts): in a command that runs an interpreter (node, python3, tsx, ...), a heredoc body or an
-e/-c payload that names tmux AND a kill subcommand as literals AND no '-L'/'-S' literal -> BLOCK. A text match,
not a parser: a probe of the gate itself fed through `python3 - <<EOF` is blocked too (use a file).

NOT MODELLED (an ACCIDENT guard, not a boundary: same uid): a script file written in an EARLIER command and run
later, or one that builds the tmux arguments at run time; the tmux library of an interpreter; kill <pid> of the
server; a value built at run time and passed as the command word ($T kill-server is blocked only because the
subcommand is literal); tmux source-file; a tmux config or hook.

Exit 2 + the reason on stderr = block; exit 0 = allow. Internal error or watchdog: block only when the command text
mentions tmux or a kill command (fail closed where it matters, open elsewhere). Deny lines are logged to
store/tmux-kill-gate/gate.jsonl (lazily created, O_APPEND|O_NOFOLLOW; the command text is not stored, only its
sha256 prefix and the reasons).
"""
import hashlib
import importlib.util
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
LEX_PATH = os.path.join(ROOT, 'scripts', 'lib', 'shell_lex.py')
LOG_DIR = os.path.join(ROOT, 'store', 'tmux-kill-gate')
MAX_DEPTH = 6
MAX_TEXT = 200_000
WATCHDOG_S = 5.0

# `tmux list-commands` on tmux 3.8 (2026-11-15): full names and their aliases. A unique prefix of a full name is
# accepted by tmux too (kill-ser -> kill-server; kill-s is ambiguous and refused, measured).
COMMANDS = {
    'attach-session': 'attach', 'bind-key': 'bind', 'break-pane': 'breakp', 'capture-pane': 'capturep',
    'choose-buffer': None, 'choose-client': None, 'choose-tree': None, 'clear-history': 'clearhist',
    'clear-prompt-history': 'clearphist', 'clock-mode': None, 'command-prompt': None, 'confirm-before': 'confirm',
    'copy-mode': None, 'customize-mode': None, 'delete-buffer': 'deleteb', 'detach-client': 'detach',
    'display-menu': 'menu', 'display-message': 'display', 'display-popup': 'popup', 'display-panes': 'displayp',
    'find-window': 'findw', 'has-session': 'has', 'if-shell': 'if', 'join-pane': 'joinp', 'kill-pane': 'killp',
    'kill-server': None, 'kill-session': None, 'kill-window': 'killw', 'last-pane': 'lastp', 'last-window': 'last',
    'link-window': 'linkw', 'list-buffers': 'lsb', 'list-clients': 'lsc', 'list-commands': 'lscm',
    'list-keys': 'lsk', 'list-panes': 'lsp', 'list-sessions': 'ls', 'list-windows': 'lsw', 'load-buffer': 'loadb',
    'lock-client': 'lockc', 'lock-server': 'lock', 'lock-session': 'locks', 'move-pane': 'movep',
    'move-window': 'movew', 'new-pane': 'newp', 'new-session': 'new', 'new-window': 'neww', 'next-layout': 'nextl',
    'next-window': 'next', 'paste-buffer': 'pasteb', 'pipe-pane': 'pipep', 'previous-layout': 'prevl',
    'previous-window': 'prev', 'refresh-client': 'refresh', 'rename-session': 'rename', 'rename-window': 'renamew',
    'resize-pane': 'resizep', 'resize-window': 'resizew', 'respawn-pane': 'respawnp', 'respawn-window': 'respawnw',
    'rotate-window': 'rotatew', 'run-shell': 'run', 'save-buffer': 'saveb', 'select-layout': 'selectl',
    'select-pane': 'selectp', 'select-window': 'selectw', 'send-keys': 'send', 'send-prefix': None,
    'server-access': None, 'set-buffer': 'setb', 'set-environment': 'setenv', 'set-hook': None, 'set-option': 'set',
    'set-window-option': 'setw', 'show-buffer': 'showb', 'show-environment': 'showenv', 'show-hooks': None,
    'show-messages': 'showmsgs', 'show-options': 'show', 'show-prompt-history': 'showphist',
    'show-window-options': 'showw', 'source-file': 'source', 'split-window': 'splitw', 'start-server': 'start',
    'suspend-client': 'suspendc', 'swap-pane': 'swapp', 'swap-window': 'swapw', 'switch-client': 'switchc',
    'switch-mode': None, 'unbind-key': 'unbind', 'unlink-window': 'unlinkw', 'wait-for': 'wait',
}
ALIASES = {a: c for c, a in COMMANDS.items() if a}
# Options taking a value, per command we inspect (tmux getopt strings, man tmux 3.8); others: values not needed.
ARG_OPTS = {
    'kill-server': '', 'kill-session': 'ft', 'kill-window': 'ft', 'kill-pane': 'ft', 'unlink-window': 't',
    'respawn-pane': 'cet', 'respawn-window': 'cet',
}
NEEDS_K = {'unlink-window', 'respawn-pane', 'respawn-window'}
GLOBAL_ARG_OPTS = 'LScfT'
PROTECTED = ('agent-', 'klodel-channels')
SHELLS = {'sh', 'bash', 'zsh', 'dash', 'ksh'}
ASSIGN_RX = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')
INTERPRETERS = {'node', 'python', 'python3', 'bun', 'deno', 'ruby', 'perl', 'tsx', 'ts-node', 'osascript'} | {
    f'python3.{n}' for n in range(6, 15)}
# tmux as a string literal ('tmux', "tmux kill-server") or as a command after a shell separator inside a string
# ("cd x && tmux kill-server"); NOT bare prose ("... a tmux kill-server futott ..." in a log line, E1 2026-11-15).
CODE_TMUX_RX = re.compile(r"""['"`]tmux['"`]|['"`]tmux\s|[;&|(]\s*tmux\s""")
CODE_KILL_RX = re.compile(r"""['"`\s](kill-se(r(v(er?)?)?)?|kill-session|kill-window|kill-pane|killw|killp)['"`\s]""")
CODE_ISOLATED_RX = re.compile(r"""['"`]-[LS]['"`]|\btmux\s+-[LS]\s""")


def code_kills_live_tmux(body):
    return bool(CODE_TMUX_RX.search(body) and CODE_KILL_RX.search(body) and not CODE_ISOLATED_RX.search(body))


KILL_WORD_RX = re.compile(r'\b(kill-(se(r(v(er?)?)?)?|session|window|pane)|killp|killw)\b')


def _load_lex():
    spec = importlib.util.spec_from_file_location('tmux_kill_gate_shell_lex', LEX_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_LEX = None


def lexer():
    global _LEX
    if _LEX is None:
        _LEX = _load_lex()
    return _LEX


def live_socket_paths():
    uid = os.getuid()
    out = set()
    for base in ('/private/tmp', '/tmp', os.environ.get('TMUX_TMPDIR') or '/tmp'):
        p = os.path.join(base, f'tmux-{uid}', 'default')
        out.add(p)
        out.add(os.path.realpath(p))
    tm = os.environ.get('TMUX', '')
    if tm:
        sock = tm.split(',')[0]
        out.add(sock)
        out.add(os.path.realpath(sock))
    return out


def dynamic(word):
    """Expanded at run time. The lexer's 'expands' covers only an UNQUOTED $ or backtick; \"$X\" expands too, so any $ or
    backtick in the text counts (a single-quoted literal '$X' is read as dynamic as well: the safe side)."""
    return word['expands'] or '$' in word['text'] or '`' in word['text']


_ASSIGNS = [{}]  # literal NAME=value assignments of the command being read (innermost last)
VAR_REF_RX = re.compile(r'^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?$')


def resolved(word):
    """$NAME / ${NAME} whose value was assigned a LITERAL earlier in the same command (L=probe; tmux -L $L ...)."""
    if word is None:
        return None
    m = VAR_REF_RX.match(word['text'])
    if m and m.group(1) in _ASSIGNS[-1]:
        return dict(word, text=_ASSIGNS[-1][m.group(1)], expands=False)
    return word


def socket_is_live(opt, word):
    """opt: None (no -L/-S), '-L' or '-S'; word: the lexer word of the value (or None)."""
    if opt is None:
        return True
    word = resolved(word)
    if word is None or dynamic(word):
        return True
    val = word['text']
    if opt == '-L':
        return val == 'default' or val == ''
    p = os.path.expanduser(val)
    if p in live_socket_paths() or os.path.realpath(p) in live_socket_paths():
        return True
    return os.path.basename(p) == 'default' and re.fullmatch(r'tmux-\d+', os.path.basename(os.path.dirname(p))) is not None


def resolve(name):
    if name in COMMANDS:
        return name
    if name in ALIASES:
        return ALIASES[name]
    cands = [c for c in COMMANDS if c.startswith(name)] if name else []
    return cands[0] if len(cands) == 1 else None


def target_dangerous(word):
    word = resolved(word)
    if word is None:
        return 'no -t: the caller\'s own (current) session'
    t = word['text']
    if t[:1] in ('$', '@', '%'):
        return f'target {t!r} is an id or expanded'
    if dynamic(word):
        return 'the target is expanded at run time'
    session = t.split(':', 1)[0]
    exact = session.startswith('=')
    if exact:
        session = session[1:]
    if session == '':
        return f'target {t!r} names the current session'
    if any(ch in session for ch in '*?['):
        return f'target {t!r} is a pattern'
    if session.startswith(PROTECTED):
        return f'target {t!r} is an agent session'
    if not exact and any(p.startswith(session) for p in PROTECTED):
        return f'target {t!r} prefix-matches agent sessions (tmux matches session-name prefixes)'
    return None


def parse_opts(words, argopts):
    """getopt-style: returns ({letter: value-word or True}, positional words)."""
    opts = {}
    pos = []
    i = 0
    while i < len(words):
        w = words[i]
        t = w['text']
        if t == '--':
            pos.extend(words[i + 1:])
            break
        if len(t) > 1 and t.startswith('-') and not w['quoted']:
            j = 1
            while j < len(t):
                ch = t[j]
                if ch in argopts:
                    if j + 1 < len(t):
                        opts[ch] = dict(w, text=t[j + 1:])
                    else:
                        i += 1
                        opts[ch] = words[i] if i < len(words) else None
                    break
                opts[ch] = True
                j += 1
            i += 1
            continue
        pos.append(w)
        i += 1
    return opts, pos


def tmux_reasons(words, depth):
    """words: the tmux invocation's arguments (after the command word)."""
    reasons = []
    # global options, up to the first non-option word
    i = 0
    sock_opt, sock_word = None, None
    while i < len(words):
        t = words[i]['text']
        if t == '--':
            i += 1
            break
        if not (len(t) > 1 and t.startswith('-')) or words[i]['quoted']:
            break
        j = 1
        consumed = False
        while j < len(t):
            ch = t[j]
            if ch in GLOBAL_ARG_OPTS:
                val = dict(words[i], text=t[j + 1:]) if j + 1 < len(t) else (words[i + 1] if i + 1 < len(words) else None)
                if j + 1 >= len(t):
                    consumed = True
                if ch in 'LS':
                    sock_opt, sock_word = '-' + ch, val
                elif ch == 'c' and val is not None:
                    reasons += decide_text(val['text'], depth + 1)
                break
            j += 1
        i += 2 if consumed else 1
    live = socket_is_live(sock_opt, sock_word)
    rest = words[i:]
    # tmux command sequences: a ';' argument separates commands
    seqs, cur = [], []
    for w in rest:
        if w['text'] == ';':  # an escaped \; or a quoted ';' argument: tmux's own command separator
            seqs.append(cur)
            cur = []
        else:
            cur.append(w)
    seqs.append(cur)
    for seq in seqs:
        if not seq:
            continue
        name = resolve(seq[0]['text']) if not dynamic(seq[0]) else None
        args = seq[1:]
        # anything handed to the server as shell text (send-keys, run-shell, new-session's command ...) is read too
        for a in args:
            if not a['text'].startswith('-'):
                reasons += decide_text(a['text'], depth + 1)
        if dynamic(seq[0]):
            if any(KILL_WORD_RX.search(a['text']) for a in args) or KILL_WORD_RX.search(seq[0]['text']):
                reasons.append('a tmux subcommand built at run time')
            continue
        if not live or name is None:
            continue
        if name == 'kill-server':
            reasons.append('tmux kill-server on the LIVE server')
            continue
        if name in ARG_OPTS:
            opts, _ = parse_opts(args, ARG_OPTS[name])
            if name in NEEDS_K and 'k' not in opts:
                continue
            if 'a' in opts:
                reasons.append(f'tmux {name} -a on the LIVE server (kills everything but the target)')
                continue
            why = target_dangerous(opts.get('t') if isinstance(opts.get('t'), dict) else None)
            if why:
                reasons.append(f'tmux {name} on the LIVE server: {why}')
    return reasons


def strip_wrappers(words):
    """Drop VAR=value prefixes and the common command wrappers; returns the words from the real command word."""
    i = 0
    for _ in range(12):
        while i < len(words) and ASSIGN_RX.match(words[i]['text']) and not words[i]['quoted']:
            i += 1
        if i >= len(words):
            return []
        name = os.path.basename(words[i]['text'])
        if name == 'env':
            i += 1
            while i < len(words):
                t = words[i]['text']
                if t in ('-u', '-P', '-S', '-C'):
                    i += 2
                elif t.startswith('-') or ASSIGN_RX.match(t):
                    i += 1
                else:
                    break
            continue
        if name in ('command', 'exec', 'builtin', 'nohup', 'time', 'caffeinate', 'noglob', 'stdbuf'):
            i += 1
            while i < len(words) and words[i]['text'].startswith('-'):
                i += 1
            continue
        if name in ('nice', 'sudo', 'xargs', 'watch'):
            i += 1
            argful = {'nice': '-n', 'sudo': '-u -g -C -D -h -p -r -t -U', 'xargs': '-n -I -L -P -s -E -d -J -R',
                      'watch': '-n -d'}[name].split()
            while i < len(words) and words[i]['text'].startswith('-'):
                i += 2 if words[i]['text'] in argful else 1
            continue
        if name in ('timeout', 'gtimeout'):
            i += 1
            while i < len(words) and words[i]['text'].startswith('-'):
                i += 2 if words[i]['text'] in ('-s', '-k') else 1
            i += 1  # the duration
            continue
        return words[i:]
    return words[i:]


def segment_reasons(words, depth):
    words = strip_wrappers(words)
    if not words:
        return []
    head = words[0]
    name = os.path.basename(head['text'])
    rest = words[1:]
    if name == 'tmux' and not dynamic(head):
        return tmux_reasons(rest, depth)
    if name in SHELLS:
        out = []
        for k, w in enumerate(rest):
            t = w['text']
            if re.fullmatch(r'-[A-Za-z]*c[A-Za-z]*', t) and k + 1 < len(rest):
                out += decide_text(rest[k + 1]['text'], depth + 1)
                break
        return out
    if name == 'eval':
        return decide_text(' '.join(w['text'] for w in rest), depth + 1)
    if name in ('pkill', 'killall'):
        if any('tmux' in w['text'] for w in rest if not w['text'].startswith('-')):
            return [f'{name} on tmux (stops the LIVE server)']
        return []
    if name == 'kill':
        if any('pgrep' in w['text'] and 'tmux' in w['text'] for w in rest):
            return ['kill of the tmux server pid (pgrep tmux)']
        return []
    if dynamic(head) and any(KILL_WORD_RX.search(w['text']) for w in rest):
        # $T kill-server: the command word is not known before run time
        return ['a command word built at run time with a tmux kill subcommand']
    return []


def decide_text(text, depth=0):
    if depth > MAX_DEPTH or not text or ('tmux' not in text and 'kill' not in text and 'eval' not in text):
        return [] if depth <= MAX_DEPTH else ['nesting too deep to read']
    if len(text) > MAX_TEXT:
        return ['command too long to read'] if 'tmux' in text else []
    L = lexer()
    lx = L.lex(text)
    reasons = []
    segwords = [L.words(text, lx, seg) for seg in lx['segments']]
    assigns = dict(_ASSIGNS[-1])
    for ws in segwords:
        if ws and all(ASSIGN_RX.match(w['text']) for w in ws):
            for w in ws:
                k, v = w['text'].split('=', 1)
                if '$' in v or '`' in v:
                    assigns.pop(k, None)
                else:
                    assigns[k] = v
    _ASSIGNS.append(assigns)
    try:
        for ws in segwords:
            reasons += segment_reasons(ws, depth)
    finally:
        _ASSIGNS.pop()
    # Interpreter code (the 2026-11-15 16:45 case: cat > probe.mts <<'EOF' ... execFileSync('tmux', ['kill-server'])
    # ... EOF, then node probe.mts in the same command): a heredoc body or an interpreter -e/-c payload that calls
    # tmux with a kill subcommand and names no -L/-S socket, in a command that runs an interpreter.
    runs_interp = any(strip_wrappers(ws) and os.path.basename(strip_wrappers(ws)[0]['text']) in INTERPRETERS
                      for ws in segwords)
    if runs_interp:
        bodies = [text[h['bodyStart']:h['bodyEnd']] for h in lx['heredocs']]
        for ws in segwords:
            sw = strip_wrappers(ws)
            if sw and os.path.basename(sw[0]['text']) in INTERPRETERS:
                for k, w in enumerate(sw[1:-1], start=1):
                    if w['text'] in ('-e', '-c', '-p', '--eval', '--print'):
                        bodies.append(sw[k + 1]['text'])
        for b in bodies:
            if code_kills_live_tmux(b):
                reasons.append('interpreter code calls tmux with a kill subcommand and no -L/-S socket')
                break
    # a heredoc body fed to a shell runs as commands
    for h in lx['heredocs']:
        owner = next((sg for sg in lx['segments'] if sg['start'] <= h['op'] < sg['end']), None)
        if owner is None:
            continue
        ws = strip_wrappers(L.words(text, lx, owner))
        if ws and os.path.basename(ws[0]['text']) in SHELLS and not any(
                re.fullmatch(r'-[A-Za-z]*c[A-Za-z]*', w['text']) for w in ws[1:]):
            reasons += decide_text(text[h['bodyStart']:h['bodyEnd']], depth + 1)
    return reasons


def decide(command):
    seen = []
    for r in decide_text(command):
        if r not in seen:
            seen.append(r)
    return seen


def log_deny(command, reasons, data):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        rec = {'ts': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'cwd': data.get('cwd') if isinstance(data, dict) else None,
               'cmd_sha256': hashlib.sha256(command.encode('utf-8', 'replace')).hexdigest()[:16], 'reasons': reasons}
        fd = os.open(os.path.join(LOG_DIR, 'gate.jsonl'), os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, (json.dumps(rec, ensure_ascii=False) + '\n').encode('utf-8'))
        finally:
            os.close(fd)
    except Exception:
        pass


MESSAGE = ('TMUX-KAPU: a parancs az ÉLŐ tmux-szervert vagy egy ágens sessionjét állítaná le ({}). '
           'Egy ilyen hívás 2026-11-15 16:45-kor minden ágens-sessiont megszakított (Viktor 43117). '
           'Izolált próbához EXPLICIT socket kell: tmux -L <saját-név> ... vagy tmux -S <saját-út> ... '
           '(a TMUX_TMPDIR nem izolál: a $TMUX felülírja, mérve). Ágens-újraindítás: POST /api/agents/<név>/restart.\n')


def main():
    command_holder = {'cmd': ''}

    def on_watchdog(signum, frame):
        if re.search(r'tmux|kill', command_holder['cmd']):
            os.write(2, 'TMUX-KAPU: a kapu nem végzett időben, és a parancs tmuxot/killt említ: blokkol.\n'.encode('utf-8'))
            os._exit(2)
        os._exit(0)

    try:
        import signal
        signal.signal(signal.SIGALRM, on_watchdog)
        signal.setitimer(signal.ITIMER_REAL, WATCHDOG_S)
    except Exception:
        pass
    try:
        data = json.load(sys.stdin)
        ti = data.get('tool_input') or {}
    except Exception:
        return 0
    if not isinstance(ti, dict):
        return 0
    cmd = ti.get('command')
    if not isinstance(cmd, str) or not cmd:
        return 0
    command_holder['cmd'] = cmd
    try:
        reasons = decide(cmd)
    except Exception as e:
        if not re.search(r'tmux|kill', cmd):
            return 0
        reasons = [f'a kapu hibára futott ({e.__class__.__name__}), és a parancs tmuxot/killt említ']
    if reasons:
        log_deny(cmd, reasons, data)
        sys.stderr.write(MESSAGE.format('; '.join(reasons)))
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
