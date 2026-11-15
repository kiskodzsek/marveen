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
      a target starting with agent- or klodel- (klodel-channels, klodel-worker, klodel-worker-fast: every klodel-*
      session is the fleet's, Viktor 43205 INFO 2), a PREFIX of those (tmux prefix-matches session names:
      kill-session -t agent killed agent-x, measured), a glob, an id ($n @n %n), an expanded value, or an
      xargs/find placeholder ({}, the xargs -I/-J/-i string: filled at run time);
    - pkill / killall with a tmux pattern, kill with $(pgrep ... tmux).
  ALLOW: everything with an explicit -L <name> (not default) or -S <path> that is not the live socket; every other
  tmux command (send-keys, capture-pane, list-*, new-session ...); kill-session -t <a plain non-agent name>.

Read through the shared lexer (scripts/lib/shell_lex.py, card fae0712e): quotes, $( ), backticks, ;, &&, |, and
heredoc bodies are separated the way bash does. Followed: VAR=value prefixes, a redirection before the command word
(>/dev/null tmux ..., quoted >"/tmp/x" and {fd}>f too) and among tmux's arguments (tmux kill-session -t >x agent-dave,
... | xargs tmux kill-session -t 2>/dev/null: read once as written and once without the redirections), >| (clobber;
the shared lexer cuts at its '|', so it is read as > here), function definitions (function f { ...; f() { ...), coproc,
compound-command keywords (if/then/elif/else/while/until/do/{/!, case patterns), env (-S, -S'...', -iS clusters,
--split-string=, a value letter closing a cluster: -iu X, -iC dir)/command/exec/nohup/nice/time/sudo/timeout/xargs/
caffeinate/setsid/arch/sandbox-exec/stdbuf/screen/
script wrappers (getopt-style values: screen -dmS x, stdbuf -oL, script -qt 0), find -exec/-execdir/-ok/-okdir,
sh/bash/zsh -c payloads, eval, a heredoc, a here-string or a pipe fed to a shell (also cat <<EOF | sh: the producer's
heredoc), xargs tmux (the fed words appended or put in place of the -I/-J string; with no pipe in front, the input
is a redirection or the terminal and stands for a run-time word; an outer replace string stays visible inside a
nested sh -c / eval payload), tmux -c, the arguments of every tmux subcommand (send-keys "tmux kill-server" Enter would run it in a
pane), read as tmux commands too for if-shell/confirm-before/command-prompt/bind-key/set-hook, and a ';' glued to a
tmux argument (kill-server\\;) as tmux's separator. With both -S and -L, -S counts (tmux uses
it whatever the order, measured); an -L label with a path part (-L ../tmux-<uid>/default) is live. A window/pane
target without a session part (-t 1, -t .0, -t <window>) resolves in the caller's own session: blocked.
A $NAME / ${NAME} socket, target or subcommand resolves only to a LITERAL value assigned earlier in the same command
(L=probe; tmux -L $L ...); an unknown, reassigned or prefix-assigned one stays dynamic, i.e. live.
Interpreter code (the 16:45 incident itself: cat > probe.mts <<'EOF' ... execFileSync('tmux', ['kill-server'])
... EOF; node probe.mts): in a command that runs an interpreter (node, python3, tsx, ...), a heredoc body or an
-e/-c payload that names tmux AND a kill subcommand as literals, and no '-L'/'-S' literal between the kill word and
the nearest tmux literal before it (per call: one isolated call does not clear a live one, Viktor 43205 LOW 4) ->
BLOCK. A text match, not a parser: a probe of the gate itself fed through `python3 - <<EOF` is blocked too (use a
file). In the same bodies, the string literal right after a shell-running call (system( / popen( / run( / exec( /
execSync( / spawn(, perl/ruby system "...") is read as a command line, like an sh -c payload: os.system('>x tmux
kill-server'); a string anywhere else (an assignment, a JSON field, prose) is not.

NOT MODELLED (an ACCIDENT guard, not a boundary: same uid): a script file written in an EARLIER command and run
later, or one that builds the tmux arguments at run time; the tmux library of an interpreter; kill <pid> of the
server; a value built at run time and passed as the command word ($T kill-server is blocked only because the
subcommand is literal); awk system(), ssh, GNU parallel (not installed on the fleet machine, 2026-11-15), and other
programs that run a command string; xargs tmux whose subcommand itself comes from the input; a perl/ruby
command string in backticks, qx() or %x() (not after a call), a literal split across lines or longer than 4000
characters, a command string held in a variable before the call (cmd = '>x tmux kill-server'; os.system(cmd)), a
prefixed literal (r'...', f'...', b'...'), a triple-quoted one, a keyword argument (os.system(command='...'),
subprocess.run(args='...', shell=True)), an argv list handed to a shell (['sh', '-c', '>x tmux kill-server']),
os.execl and the like, two literals joined, an escaped character (\\x2d) or a literal in parentheses or str(...),
perl q()/qq() and ruby %q(). Perl q()/qq() and ruby %q() are not caught at all, plain or prefixed (system(q(tmux
kill-server)) passes, Viktor 43373); the other shapes only with a redirection or wrapper prefix: a plain
'tmux kill-server' literal is caught by the interpreter check above. None of these shapes occurred in Viktor's
14-day replay (43364);
tmux source-file; a tmux
config or hook set up outside the command; more than 64 nested wrappers raise (blocked through main() when tmux or
kill is named). Known false positive: a loop variable as a target (for s in klodel-worker ...; tmux respawn-pane -k
-t $s) is read as live (Viktor 43177 replay, 1 in 14 days); since klodel-* is protected, the literal names are
blocked too: restart an agent through POST /api/agents/<name>/restart.

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
TMUX_CMD_ARGS = {'if-shell', 'confirm-before', 'command-prompt', 'bind-key', 'set-hook'}
GLOBAL_ARG_OPTS = 'LScfT'
# Viktor 43205 INFO 2: klodel-worker and klodel-worker-fast run the schedules (tmux ls, 2026-11-15): every klodel-*
# session is the fleet's, like klodel-channels.
PROTECTED = ('agent-', 'klodel-')
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
    """A kill subcommand literal whose OWN call names no socket: the text from the nearest tmux literal before it (at
    most 200 characters back) to the kill word carries no '-L'/'-S' literal (Viktor 43205 LOW 4: one isolated call
    must not clear a second, live one in the same body). No tmux literal before it: the whole body decides."""
    if not CODE_TMUX_RX.search(body):
        return False
    for k in CODE_KILL_RX.finditer(body):
        lo = max(0, k.start() - 200)
        tm = list(CODE_TMUX_RX.finditer(body, lo, k.start() + 1))
        span = body[tm[-1].start():k.end()] if tm else body
        if not CODE_ISOLATED_RX.search(span):
            return True
    return False


# a single-, double- or backtick-quoted string literal in interpreter code (one line, at most 4000 characters; the
# alternation is unambiguous, so a failed attempt ends at the line end or the cap, no backtracking blow-up)
STR_LIT_RX = re.compile(r"""'((?:[^'\\\n]|\\.){1,4000})'|"((?:[^"\\\n]|\\.){1,4000})"|`((?:[^`\\\n]|\\.){1,4000})`""")
MAX_LITERALS = 2000
# a call that hands its string argument to a shell: os.system / os.popen / subprocess.run|call|check_output|Popen
# (with shell=True), subprocess.getoutput, child_process.exec|execSync|spawn, perl/ruby system|exec (with or without
# parentheses); the literal must follow it directly
SHELL_CALL_RX = re.compile(r'(?:\b(?:system|popen|getoutput|getstatusoutput|run|call|check_call|check_output|Popen|'
                           r'exec|execSync|spawn|spawnSync)\s*\(\s*|\b(?:system|exec)\s+)$')
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
_PLACEHOLDERS = [set()]  # xargs -I/-J/-i replace strings of the segment being read (innermost last)
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
        # Viktor 43177 LOW 2: tmux does not filter the label, -L ../tmux-<uid>/default and -L ./default reach the live
        # server (measured on an isolated server); a label with a path part is read as live.
        return val in ('default', '') or '/' in val or val.startswith('.')
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


def target_dangerous(word, name='kill-session'):
    word = resolved(word)
    if word is None:
        return 'no -t: the caller\'s own (current) session'
    t = word['text']
    if t[:1] in ('$', '@', '%'):
        return f'target {t!r} is an id or expanded'
    if dynamic(word):
        return 'the target is expanded at run time'
    if '{}' in t or any(ph and ph in t for ph in _PLACEHOLDERS[-1]):
        return f'target {t!r} is an xargs/find placeholder, filled at run time'  # Viktor 43205 LOW 1
    # Viktor 43177 MEDIUM 2: a window/pane target without a session part (-t 1, -t .0, -t <window name>) resolves in
    # the CALLER's own session (measured on an isolated server): an agent's window or pane dies.
    if name != 'kill-session' and ':' not in t:
        return f'target {t!r} has no session part: it resolves in the caller\'s own (agent) session'
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
    sock_l, sock_s = None, None
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
                    if ch == 'S':
                        sock_s = val
                    else:
                        sock_l = val
                elif ch == 'c' and val is not None:
                    reasons += decide_text(val['text'], depth + 1)
                break
            j += 1
        i += 2 if consumed else 1
    # Viktor 43177 LOW 1: with both, tmux uses -S whatever the order (measured); -L counts only without -S.
    live = socket_is_live('-S', sock_s) if sock_s is not None else socket_is_live('-L' if sock_l is not None else None, sock_l)
    rest = words[i:]
    # tmux command sequences: a ';' argument separates commands
    seqs, cur = [], []
    for w in rest:
        if w['text'] == ';':  # an escaped \; or a quoted ';' argument: tmux's own command separator
            seqs.append(cur)
            cur = []
        elif len(w['text']) > 1 and w['text'].endswith(';'):  # kill-server\; glued (Viktor 43205 INFO 1)
            cur.append(dict(w, text=w['text'][:-1]))
            seqs.append(cur)
            cur = []
        else:
            cur.append(w)
    seqs.append(cur)
    for seq in seqs:
        if not seq:
            continue
        # Viktor 43177 LOW 5: x=kill-server; tmux $x -- a literal assignment resolves the subcommand too
        seq = [resolved(seq[0])] + seq[1:]
        name = resolve(seq[0]['text']) if not dynamic(seq[0]) else None
        args = seq[1:]
        # anything handed to the server as shell text (send-keys, run-shell, new-session's command ...) is read too
        for a in args:
            if not a['text'].startswith('-'):
                reasons += decide_text(a['text'], depth + 1)
                # if-shell / confirm-before / command-prompt / bind-key / set-hook take TMUX commands as arguments
                # (tmux if-shell true kill-server; Viktor 43205 INFO 1): read them as a tmux command line too
                if live and name in TMUX_CMD_ARGS:
                    reasons += decide_text('tmux ' + a['text'], depth + 1)
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
            why = target_dangerous(opts.get('t') if isinstance(opts.get('t'), dict) else None, name)
            if why:
                reasons.append(f'tmux {name} on the LIVE server: {why}')
    return reasons


# Viktor 43177 MEDIUM 1: the lexer hands a compound command's keyword over as the segment's first word
# (then tmux kill-server; do tmux ...; { tmux ...; ! tmux ...).
RESERVED = {'if', 'then', 'elif', 'else', 'while', 'until', 'do', '{', '!'}
# a redirection word at the head of a command (>/dev/null, 2>&1, &>>, < in, <<EOF, <<< x, {fd}>f): skipped with its
# target word when the target is not glued to it (bash runs the command after it; <<EOF tmux kill-server kills)
REDIR_RX = re.compile(r'^(\{[A-Za-z_][A-Za-z0-9_]*\}|[0-9]*|&)(<<<|<<-|<<|>>|>\||>&|<&|<>|>|<)(.*)$')
# options taking a value, per wrapper
WRAPPER_ARGS = {
    'command': '', 'builtin': '', 'nohup': '', 'time': '', 'caffeinate': '-t -w', 'noglob': '', 'stdbuf': '-i -o -e',
    'exec': '-a', 'setsid': '', 'arch': '-e', 'sandbox-exec': '-f -p -n -D', 'screen': '-S -c -e -p -t -T -h',
    'nice': '-n', 'sudo': '-u -g -C -D -h -p -r -t -U', 'xargs': '-n -I -L -P -s -E -d -J -R', 'watch': '-n',
}


def strip_wrappers(words):
    """Drop VAR=value prefixes, compound-command keywords and the common command wrappers; returns the words from the
    real command word."""
    i = 0
    for _ in range(64):
        while i < len(words) and ASSIGN_RX.match(words[i]['text']) and not words[i]['quoted']:
            i += 1
        if i >= len(words):
            return []
        w = words[i]
        name = os.path.basename(w['text'])
        if not w['quoted'] and w['text'] in RESERVED:
            i += 1
            continue
        # quoted too: the lexer hands >"/tmp/x" over as one quoted word '>/tmp/x' (Viktor 43301 LOW 2)
        m = REDIR_RX.match(w['text'])
        if m:  # >/dev/null tmux ..., 2> err tmux ... (Viktor 43205 LOW 3)
            i += 1 if m.group(3) else 2
            continue
        if not w['quoted'] and w['text'] == 'coproc':
            # coproc tmux ... / coproc NAME { tmux ...; } (Viktor 43301 INFO)
            i += 2 if i + 2 < len(words) and words[i + 2]['text'] == '{' else 1
            continue
        if not w['quoted'] and w['text'] == 'function':
            i += 2  # function NAME { ... (Viktor 43205 INFO 1)
            continue
        if not w['quoted'] and w['text'].endswith('()') and len(w['text']) > 2:
            i += 1  # NAME() { ...
            continue
        if not w['quoted'] and i + 1 < len(words) and words[i + 1]['text'] == '()':
            i += 2  # NAME () { ...
            continue
        if name == 'script':  # script [-aq ...] FILE CMD ... (Viktor 43205 INFO 1)
            i += 1
            while i < len(words) and words[i]['text'].startswith('-'):
                t = words[i]['text']
                # -t (and the playback -T) take a value, also at the end of a cluster (script -qt 0; Viktor 43301
                # INFO). -F is a FLAG on macOS (man script: "Immediately flush output after each write"): with it read
                # as taking a value, script -F /tmp/p tmux kill-server passed (#326)
                i += 2 if not t.startswith('--') and len(t) > 1 and t[-1] in 'tT' else 1
            i += 1
            continue
        if not w['quoted'] and w['text'] == 'case':
            # case WORD in PATTERN) cmd ...
            k = next((k for k in range(i + 1, len(words)) if words[k]['text'] == 'in' and not words[k]['quoted']), None)
            if k is None:
                return []
            i = k + 1
            continue
        if not w['quoted'] and len(w['text']) > 1 and w['text'].endswith(')') and '(' not in w['text']:
            i += 1  # a case pattern (a) / *) / b|c)), also the one opening a later ;; branch
            continue
        if name == 'env':
            i += 1
            while i < len(words):
                t = words[i]['text']
                # -S inside a short-option cluster too (env -iS '...', -vS'...'; Viktor 43301 INFO)
                spos = t.find('S') if t.startswith('-') and not t.startswith('--') else -1
                glued = (spos > 0 and len(t) > spos + 1) or t.startswith('--split-string=')
                if glued or ((spos > 0 or t == '--split-string') and i + 1 < len(words)):
                    # env -S 'tmux kill-server' (or -S'...' / --split-string=... glued): the value is split into the
                    # command line (Viktor 43177 LOW 4, 43205 INFO 1)
                    L = lexer()
                    val = (t.split('=', 1)[1] if t.startswith('--') else t[spos + 1:]) if glued else words[i + 1]['text']
                    lx = L.lex(val)
                    head = L.words(val, lx, lx['segments'][0]) if lx['segments'] else []
                    words = head + words[i + (1 if glued else 2):]
                    i = 0
                    break
                if t in ('-u', '-P', '-C'):
                    i += 2
                elif t.startswith('-') and not t.startswith('--') and len(t) > 2 and any(ch in 'uPC' for ch in t[1:]):
                    # a cluster whose FIRST value letter is its last letter takes the next word (env -iu X tmux
                    # kill-server, -iC /tmp, -vu X, -0u X; Viktor 43329 LOW 2); -iuX and -ui X carry the value glued
                    first = next(j for j in range(1, len(t)) if t[j] in 'uPC')
                    i += 2 if first == len(t) - 1 else 1
                elif t.startswith('-') or ASSIGN_RX.match(t):
                    i += 1
                else:
                    break
            continue
        if name in WRAPPER_ARGS:
            i = skip_wrapper_opts(name, words, i + 1)
            continue
        if name in ('timeout', 'gtimeout'):
            i += 1
            while i < len(words) and words[i]['text'].startswith('-'):
                i += 2 if words[i]['text'] in ('-s', '-k') else 1
            i += 1  # the duration
            continue
        return words[i:]
    # more nested wrappers than the loop reads: fail closed through main() when tmux or kill is mentioned
    # (Viktor 43205 INFO 1: env env env ... past the limit used to allow)
    raise RuntimeError('wrapper nesting too deep to read')


def skip_wrapper_opts(name, words, i):
    """getopt-style: -dmS x (screen), -oL (stdbuf), -n 5: a value-taking letter consumes the rest of the word or, at
    its end, the next word. xargs -I/-J record the replace string, -i[R] too ({} by default; Viktor 43205 LOW 1)."""
    letters = {a[1] for a in WRAPPER_ARGS[name].split() if len(a) == 2}
    while i < len(words) and words[i]['text'].startswith('-') and len(words[i]['text']) > 1:
        t = words[i]['text']
        step = 1
        if not t.startswith('--'):
            for j in range(1, len(t)):
                ch = t[j]
                if name == 'xargs' and ch == 'i':
                    _PLACEHOLDERS[-1].add(t[j + 1:] or '{}')
                    break
                if ch in letters:
                    glued = t[j + 1:]
                    if not glued:
                        step = 2
                    if name == 'xargs' and ch in 'IJ':
                        val = glued or (words[i + 1]['text'] if i + 1 < len(words) else '')
                        if val:
                            _PLACEHOLDERS[-1].add(val)
                    break
        i += step
    return i


def segment_reasons(words, depth):
    # Viktor 43301 LOW 1: only the outermost level starts a segment afresh; a nested payload (xargs -I X sh -c 'tmux
    # kill-session -t X', eval ...) keeps the outer replace strings (stricter across its own segments)
    if depth == 0:
        _PLACEHOLDERS[-1].clear()
    words = strip_wrappers(words)
    if not words:
        return []
    head = words[0]
    name = os.path.basename(head['text'])
    rest = words[1:]
    if name == 'tmux' and not dynamic(head):
        # bash removes a redirection from the arguments wherever it stands (tmux kill-session -t >x agent-dave, and
        # ... | xargs tmux kill-session -t 2>/dev/null read 2>/dev/null as the target; Viktor 43329 LOW 1). The
        # arguments are read as written AND without the redirections: only stricter, and a quoted argument that
        # looks like one ('>x; tmux kill-server' for send-keys) is still read as shell text in the first pass
        out = tmux_reasons(rest, depth)
        bare = _drop_redirs(rest)
        if len(bare) != len(rest):
            out += tmux_reasons(bare, depth)
        return out
    if name in SHELLS:
        out = []
        for k, w in enumerate(rest):
            t = w['text']
            if re.fullmatch(r'-[A-Za-z]*c[A-Za-z]*', t) and k + 1 < len(rest):
                out += decide_text(rest[k + 1]['text'], depth + 1)
                break
        for k, w in enumerate(rest[:-1]):
            if w['text'] == '<<<' and not w['quoted']:  # bash <<< 'tmux kill-server' (Viktor 43177 LOW 3)
                out += decide_text(unescape(rest[k + 1]['text']), depth + 1)
        return out
    if name == 'find':
        # find ... -exec / -execdir / -ok CMD ... ; or +  (Viktor 43177 LOW 4)
        out = []
        for k, w in enumerate(rest):
            if w['text'] in ('-exec', '-execdir', '-ok', '-okdir'):
                end = next((m for m in range(k + 1, len(rest)) if rest[m]['text'] in (';', '+')), len(rest))
                out += segment_reasons(rest[k + 1:end], depth + 1)
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


def unescape(t):
    return t.replace('\\n', '\n').replace('\\t', '\t')


def shell_reads_stdin(ws):
    """sh/bash/zsh with no -c and no script argument (or with -s): it runs what comes on stdin."""
    if not ws or os.path.basename(ws[0]['text']) not in SHELLS:
        return False
    opts = [w['text'] for w in ws[1:] if w['text'].startswith('-') and not w['quoted']]
    if any(re.fullmatch(r'-[A-Za-z]*c[A-Za-z]*', o) for o in opts):
        return False
    if any(re.fullmatch(r'-[A-Za-z]*s[A-Za-z]*', o) for o in opts):
        return True
    return not any(not w['text'].startswith('-') for w in ws[1:])


def piped_into_runner(text, lx, segwords, idx):
    """Segment idx reads the previous segment's output through a pipe and runs it: a stdin-reading shell, or xargs
    handing it to a shell or tmux (echo 'tmux kill-server' | sh; ... | xargs -I{} sh -c {})."""
    if idx == 0:
        return False
    sep = text[lx['segments'][idx - 1]['end']:lx['segments'][idx]['start']].strip()
    if sep not in ('|', '|&'):
        return False
    ws = segwords[idx]
    sw = strip_wrappers(ws)
    if shell_reads_stdin(sw):
        return True
    raw = [w for w in ws if not (ASSIGN_RX.match(w['text']) and not w['quoted'])]
    return bool(raw and os.path.basename(raw[0]['text']) == 'xargs' and sw and
                os.path.basename(sw[0]['text']) in SHELLS | {'tmux'})


def _drop_redirs(ws):
    """ws without its redirection words (>x, 2>/dev/null, {fd}>f, > x with its target): a redirection is not an
    argument (Viktor 43329 LOW 1, his proposal)."""
    out, k = [], 0
    while k < len(ws):
        m = REDIR_RX.match(ws[k]['text'])
        if m:
            k += 1 if m.group(3) else 2
            continue
        out.append(ws[k])
        k += 1
    return out


def xargs_tmux(ws):
    """(the words from tmux on, the segment's own xargs replace strings) when the segment is `xargs ... tmux ...`
    (after VAR= prefixes), else ([], set()). The replace strings go to a fresh set: the caller's level is untouched.
    A redirection anywhere (>x xargs tmux kill-session -t < names, ... -t 2>/dev/null) is handled where the tmux
    words are read: segment_reasons reads them once more without the redirections (Viktor 43329 LOW 1)."""
    raw = [w for w in ws if not (ASSIGN_RX.match(w['text']) and not w['quoted'])]
    if not raw or os.path.basename(raw[0]['text']) != 'xargs':
        return [], set()
    _PLACEHOLDERS.append(set())
    try:
        sw = strip_wrappers(ws)
        own = set(_PLACEHOLDERS[-1])
    finally:
        _PLACEHOLDERS.pop()
    if sw and os.path.basename(sw[0]['text']) == 'tmux':
        return sw, own
    return [], set()


def decide_text(text, depth=0):
    if depth > MAX_DEPTH or not text or ('tmux' not in text and 'kill' not in text and 'eval' not in text):
        return [] if depth <= MAX_DEPTH else ['nesting too deep to read']
    if len(text) > MAX_TEXT:
        return ['command too long to read'] if 'tmux' in text else []
    L = lexer()
    lx = L.lex(text)
    # >| (clobber) is ONE redirection operator, but the shared lexer cuts a segment at its '|' (>|x tmux kill-server
    # passed; Viktor 43329 LOW 3). An unquoted '|' right after an unquoted '>' is replaced by a space (same length, so
    # every offset holds) and the text is lexed again: >|x reads as > x.
    clob = [p for p in range(1, len(text)) if text[p] == '|' and text[p - 1] == '>' and lx['cls'][p] == 'c'
            and lx['cls'][p - 1] == 'c']
    if clob:
        chars = list(text)
        for p in clob:
            chars[p] = ' '
        text = ''.join(chars)
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
        for idx, ws in enumerate(segwords):
            reasons += segment_reasons(ws, depth)
            if piped_into_runner(text, lx, segwords, idx):
                # what the producer prints is run: read its arguments as a command line (Viktor 43177 LOW 3)
                fed = ' '.join(unescape(w['text']) for w in segwords[idx - 1][1:])
                reasons += decide_text(fed, depth + 1)
                # a producer's heredoc (cat <<EOF | sh) is what it prints (Viktor 43205 LOW 2)
                prev = lx['segments'][idx - 1]
                for h in lx['heredocs']:
                    if prev['start'] <= h['op'] < prev['end']:
                        reasons += decide_text(text[h['bodyStart']:h['bodyEnd']], depth + 1)
                # xargs tmux ...: the fed words are appended, or replace the -I/-J string (Viktor 43205 LOW 1). This
                # segment's own replace strings are read into a fresh set, so a nested level keeps the outer ones.
                sw, own = xargs_tmux(ws)
                if sw:
                    line = ' '.join(w['text'] for w in sw)
                    phs = [ph for ph in own if ph and ph in line]
                    line = line.replace(phs[0], fed) if phs else line + ' ' + fed
                    _PLACEHOLDERS.append(set())
                    try:
                        reasons += decide_text(line, depth + 1)
                    finally:
                        _PLACEHOLDERS.pop()
            else:
                # xargs tmux with no pipe in front: its input is a redirection (< names.txt, <<< x, < <(tmux ls)) or
                # the terminal, and the fed words are not known before run time (Viktor 43301 LOW 3): the redirection
                # words are dropped, and a run-time word stands for what xargs appends
                sw, own = xargs_tmux(ws)
                if sw:
                    line = ' '.join(w['text'] for w in _drop_redirs(sw))
                    if not any(ph and ph in line for ph in own):
                        line += ' $__XARGS_INPUT'
                    _PLACEHOLDERS.append(set(own))
                    try:
                        reasons += decide_text(line, depth + 1)
                    finally:
                        _PLACEHOLDERS.pop()
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
        # the string a shell-running call gets (os.system('>x tmux kill-server'), execSync('script -F p tmux
        # kill-server'), system("coproc tmux kill-server")) is read as a command line, like an sh -c payload (Viktor
        # 43329 LOW 4). Only right after such a call: prose in an assignment or a JSON field (line = '... a parancs
        # (tmux kill-server) fut ...', a hibanapló line, 2026-11-15 20:52 in the replay) is not a command.
        for b in bodies:
            for k, m in enumerate(STR_LIT_RX.finditer(b)):
                if k >= MAX_LITERALS:
                    break
                lit = next(x for x in m.groups() if x is not None)
                if 'tmux' in lit and SHELL_CALL_RX.search(b[max(0, m.start() - 40):m.start()]):
                    reasons += decide_text(unescape(lit.replace('\\"', '"').replace("\\'", "'")), depth + 1)
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
