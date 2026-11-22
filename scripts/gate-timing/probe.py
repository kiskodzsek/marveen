#!/usr/bin/env python3
"""probe.py -- the run time of every hook gate (scripts/hooks/*gate.py) on generated 60-120 KB repeated shapes.

Why (card 3b05ae69, DREAM 11-22): of the 38 gates only 7 have a test that measures time, and the time-claim-gate's
quadratic regex came back four times on one card (81a70e99), each found only by Viktor's review. A hook gate has a
10 s limit and runs on every tool call; this probe gives every gate the same repeated shapes and records the wall
time of the real hook process (python start included, what the session waits for), against a 1 s budget per run.

  probe.py all <repo> <rev> <workdir> [--workers N] [--size BYTES] [--only NAME[,NAME]] [--python PY]
      prepare + run (in the sandbox) + table; the table goes to stdout and <workdir>/table-<sha8>.md.
  probe.py prepare <repo> <rev> <root>     git archive <rev> scripts/ into the empty <root>
  probe.py run <root> [...]                inside sandbox-exec -f gatetime.sb -D ROOT=<root> only (self-check)
  probe.py table <root>/results.jsonl      the per-gate table (markdown)

How a gate is fed: the generated text goes into the field its matcher reads (Bash command, Telegram reply text,
Write content, a UserPromptSubmit prompt, ...; GATES below, from the wiring in .claude/settings.json, the agents'
settings and agent-scaffold.ts), wrapped in a few contexts that reach the gates' expensive branches (an
inter-agent message, a card comment, a shared/*.md heredoc, a commit message, python -c, ...). A unit is repeated
to --size bytes (default 120 000). Every case over CONFIRM_S is rerun alone at the full size and at half of it
(the ratio of the two shows growth: about 2 is linear, about 4 quadratic).

Safety: the gates run from the copy (their repo root is <root>, so their logs and state go there), under
gatetime.sb (writes only under <root>, no network, no signal out, no launchctl/osascript/open, no dashboard
token). `run` refuses to start when a write outside <root>, a localhost connect or the token read succeeds.
Nothing a payload names is executed: a gate only reads it.

Known limits: the copy has no store/, .env or transcript, so a gate that needs one takes its no-data path (often
an early allow); the time is that path's. One payload field per case (Edit / MultiEdit old_string, chat history
and a real transcript are not generated). Parallel runs share the CPU; only the confirm rerun is alone.
Exit: 0 table written (whatever it shows), 2 usage / prepare error, 3 not sandboxed.
"""
import concurrent.futures
import json
import os
import re
import shutil
import socket
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(HERE, 'gatetime.sb')
TOKEN = '/Users/klodel/marveen/store/.dashboard-token'
BUDGET_S = 1.0
CONFIRM_S = 0.5
TIMEOUT_S = 12.0
OWNER = '111111'

TG = 'mcp__plugin_telegram_telegram__reply'
# name -> [(hook event, tool)]; the payload field follows from the tool (FIELD).
B, W, R, TGR = ('PreToolUse', 'Bash'), ('PreToolUse', 'Write'), ('PreToolUse', 'Read'), ('PreToolUse', TG)
GATES = {
    'balazs-task-reply-gate.py': [TGR], 'big-read-gate.py': [R], 'claim-source-reply-gate.py': [TGR],
    'count-claim-gate.py': [B], 'credentials-write-gate.py': [B], 'destructive-gate.py': [B, W],
    'email-approval-gate.py': [B], 'este-blokk-write-gate.py': [B, W], 'hex-id-source-gate.py': [B],
    'keychain-read-gate.py': [B], 'keychain-write-gate.py': [B], 'link-request-reply-gate.py': [TGR],
    'mea-culpa-reply-gate.py': [TGR], 'memory-frontmatter-bash-gate.py': [B], 'memory-frontmatter-gate.py': [W],
    'mute-video-reply-gate.py': [TGR], 'outgoing-copy-gate.py': [B, TGR], 'patrik-capacity-reply-gate.py': [TGR],
    'patrik-decision-reply-gate.py': [TGR], 'patrik-mood-reply-gate.py': [TGR],
    'patrik-reply-volume-gate.py': [TGR], 'patrik-step-reply-gate.py': [TGR], 'pr-kerdes-gate.py': [TGR],
    'private-topic-group-gate.py': [TGR], 'prod-tree-write-gate.py': [B, W], 'product-image-gate.py': [TGR],
    'provenance-gate.py': [('UserPromptSubmit', None)],
    'react-emoji-gate.py': [('PreToolUse', 'mcp__plugin_telegram_telegram__react')],
    'render-claim-reply-gate.py': [TGR], 'repo-create-gate.py': [B], 'service-memory-reply-gate.py': [TGR],
    'session-meta-reply-gate.py': [TGR], 'summary-form-reply-gate.py': [TGR], 'time-claim-gate.py': [B, W, TGR],
    'tmux-kill-gate.py': [B], 'update-apply-gate.py': [B], 'zsh-trap-gate.py': [B],
}
EXCLUDED = {'channel-process-gate.py': 'not a hook: a scheduled process check (reads ps/tmux), no stdin payload'}

SHELL_UNITS = ['a ', 'a=b ', '(a=', '`a=', 'a=(', ';', ';a ', '; curl ', '|', '| a ', '&', '&& ', '\\\n', '\\',
               '"a" ', '"', "'a' ", "'", '$(a)', '$(', '${a}', '\\"', "$'a'", '<<E\n', '> f ', '>> /a/b.md ',
               '/a', '-d @f ', '# c\n', '{', '}', 'aaaa', ' ', '\n', '=a', '*', '[a]', '!', 'cat <<E; ',
               'fs.Write', 'x.y(', '=', '-X PUT ', 'curl ', 'rm ', 'python3 -c ', 'git ', 'tmux ', 'kill ',
               'sudo ', '~/', '..', '$HOME/', 'T=1 ']
TEXT_UNITS = ['19:30 ', 'mérve 19:30 ', '19:3x ', '2026-11-22 ', '11-22 ', 'abcdef12 ', '42 db ', '42 % ',
              'https://x.hu/a ', '**b** ', '- a\n', 'Patrik ', '`a` ', 'ő ', '#1234 ', 'TG 6535 ', '(a) ',
              'kész. ', ' ', '\U0001F600']
UNITS = SHELL_UNITS + TEXT_UNITS

BASH_CTX = {
    'bare': lambda b: b,
    'agent-msg': lambda b: "bash scripts/agent-msg.sh kernel klodel - <<'M'\n" + b + '\nM',
    'api-msg': lambda b: ("curl -s -X POST http://localhost:3420/api/messages -H 'Content-Type: application/json'"
                          " --data-binary @- <<'J'\n{\"from\":\"kernel\",\"content\":\"" + b + '"}\nJ'),
    'card-put': lambda b: "curl -s -X PUT http://localhost:3420/api/kanban/abc -d '{\"comment\":\"" + b + "\"}'",
    'shared-md': lambda b: "cat > /Users/klodel/marveen/shared/x.md <<'E'\n" + b + '\nE',
    'commit': lambda b: 'git commit -m "' + b + '"',
    'python-c': lambda b: "python3 -c '" + b + "'",
    'chain': lambda b: 'cd /tmp && ' + b + ' && echo ok',
    'then-rm': lambda b: b + ' ; rm -rf /tmp/x',
}
TEXT_CTX = {'bare': lambda b: b, 'reply': lambda b: 'Patrik, ' + b + ' Kész.'}
WRITE_PATHS = {'shared-md': '/Users/klodel/marveen/shared/x.md', 'prod-py': '/Users/klodel/marveen/scripts/x.py',
               'memory': '/Users/klodel/.claude/projects/x/memory/x.md'}


def contexts(tool):
    """[(ctx name, body -> tool_input)] for one tool."""
    if tool == 'Bash':
        return [(n, (lambda f: lambda b: {'command': f(b)})(f)) for n, f in BASH_CTX.items()]
    if tool == 'Write':
        return [(n, (lambda p: lambda b: {'file_path': p, 'content': b})(p)) for n, p in WRITE_PATHS.items()]
    if tool == 'Read':
        return [('path', lambda b: {'file_path': '/tmp/' + b[:4000]})]
    if tool and tool.endswith('__react'):
        return [('emoji', lambda b: {'chat_id': OWNER, 'message_id': '1', 'emoji': b})]
    if tool is None:
        return [('prompt', lambda b: b)]
    return [(n, (lambda f: lambda b: {'chat_id': OWNER, 'text': f(b)})(f)) for n, f in TEXT_CTX.items()]


def payload(root, event, tool, ti):
    p = {'session_id': 'gate-timing', 'transcript_path': os.path.join(root, 'transcript.jsonl'), 'cwd': root,
         'hook_event_name': event}
    if tool is None:
        p['prompt'] = ti
    else:
        p['tool_name'], p['tool_input'] = tool, ti
    return json.dumps(p, ensure_ascii=False)


def env_for(root, path_env):
    e = {'PATH': path_env, 'HOME': os.environ.get('HOME', '/tmp'), 'LANG': 'en_US.UTF-8',
         'TMPDIR': os.path.join(root, 'tmp'), 'CLAUDE_PROJECT_DIR': root,
         'HOOK_ERRLOG_PATH': os.path.join(root, 'hook-errors.log'),
         'MARVEEN_OWNER_CHATS': OWNER, 'MARVEEN_OWNER_PRIVATE_CHAT': OWNER, 'MARVEEN_OWNER_GROUP_CHAT': '-100222',
         'TELEGRAM_STATE_DIR': os.path.join(root, 'tg'), 'MEMFM_BASH_STATE_DIR': os.path.join(root, 'memfm'),
         'CLAUDE_CONFIG_DIR': os.path.join(root, 'claude-config'), 'MARVEEN_AGENTS_DIR': os.path.join(root, 'agents'),
         'EMAIL_APPROVAL_GATE_STORE': os.path.join(root, 'email-approvals'),
         'PROVENANCE_GATE_DB': os.path.join(root, 'provenance.db'),
         'HEX_GATE_FAILOPEN_LOG': os.path.join(root, 'hex-failopen.log'),
         'CHANNEL_GATE_NOTIFY_CMD': '/usr/bin/true'}
    return e


def run_one(py, gate, data, env, root, key):
    """(seconds, rc, crash, detail). crash: a traceback on stderr, or a line in the run's own hook_errlog file (a
    gate that catches its own exception and allows: 'internal error, allowed' is a fail-open, not a verdict)."""
    errlog = os.path.join(root, 'errlog', key + '.log')
    env = dict(env, HOOK_ERRLOG_PATH=errlog)
    t0 = time.perf_counter()
    try:
        p = subprocess.run([py, gate], input=data, capture_output=True, text=True, env=env, cwd=root,
                           timeout=TIMEOUT_S)
        rc, err = p.returncode, p.stderr
    except subprocess.TimeoutExpired:
        rc, err = 'timeout', ''
    dt = time.perf_counter() - t0
    detail = ''
    if 'Traceback (most recent call last)' in err:
        detail = 'traceback: ' + err.strip().splitlines()[-1][:100]
    try:
        with open(errlog, encoding='utf-8', errors='replace') as fh:
            logged = fh.read().strip().splitlines()
        os.unlink(errlog)
        if logged:
            detail = detail or ('errlog: ' + logged[-1].split('] ', 1)[-1][:100])
    except OSError:
        pass
    return dt, rc, bool(detail), detail


def write_probe_places(root):
    """Where the self-check tries to write: the ROOT's parent and the caller's HOME (both outside a root-* copy)."""
    places = [os.path.dirname(os.path.abspath(root))]
    home = os.environ.get('HOME', '')
    if os.path.isabs(home):
        places.append(home)
    return places


def self_check(root):
    """None when sandboxed, else the reason. The write probe (Viktor 50112 R1): a fresh random name, created with
    O_CREAT | O_EXCL | O_NOFOLLOW (so an existing file, directory or symlink at a fixed name is never written through
    or removed), in each of write_probe_places(); any success = not sandboxed, and only that own new file is removed.
    A parent that is merely read-only no longer passes: HOME is tried too."""
    for place in write_probe_places(root):
        name = os.path.join(place, '.gate-timing-escape-' + os.urandom(8).hex())
        try:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except OSError:
            continue
        os.close(fd)
        try:
            os.unlink(name)
        except OSError:
            pass
        return 'a write outside ROOT succeeded'
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(('127.0.0.1', 3420))
        return 'a localhost connect succeeded'
    except OSError:
        pass
    finally:
        s.close()
    try:
        open(TOKEN).close()
        return 'the dashboard token is readable'
    except OSError:
        pass
    return None


def cmd_run(root, workers, size, only, py):
    why = self_check(root)
    if why:
        print('probe: NOT SANDBOXED (' + why + '); run it through: probe.py all', file=sys.stderr)
        return 3
    # the sandbox allows writes under ROOT: ROOT=/ or a directory that is not a fresh root-* copy would give the gates
    # a wide write right (Viktor 50112 R1; `all` always makes a new root-<sha8>-<time>)
    if root == '/' or not os.path.basename(root).startswith('root-') or not os.path.isdir(root):
        print('probe: ROOT must be a root-* directory made by probe.py all: ' + root, file=sys.stderr)
        return 2
    if workers < 1 or size < 1:
        print('probe: --workers and --size must be at least 1', file=sys.stderr)
        return 2
    for d in ('tmp', 'tg', 'memfm', 'claude-config', 'agents', 'email-approvals', 'errlog'):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    hooks = os.path.join(root, 'scripts', 'hooks')
    names = sorted(n for n in os.listdir(hooks) if n.endswith('gate.py'))
    if only:
        names = [n for n in names if n in only]
    env = env_for(root, os.environ.get('PATH', '/usr/bin:/bin'))
    jobs, meta = [], []
    for n in names:
        if n in EXCLUDED:
            meta.append({'gate': n, 'excluded': EXCLUDED[n]})
            continue
        wiring = GATES.get(n)
        if wiring is None:
            meta.append({'gate': n, 'unmapped': True})
            wiring = [B]
        for event, tool in wiring:
            for ctx, mk in contexts(tool):
                base = 'ls' if tool == 'Bash' else 'ok'
                jobs.append((n, event, tool, ctx, 'BASELINE', len(base), payload(root, event, tool, mk(base))))
                for u in UNITS:
                    body = u * max(1, size // len(u.encode()))
                    jobs.append((n, event, tool, ctx, u, len(body.encode()), payload(root, event, tool, mk(body))))
    out = os.path.join(root, 'results.jsonl')
    t_start = time.time()
    with open(out, 'w', encoding='utf-8', buffering=1) as fh:  # line-buffered: the progress is visible
        for m in meta:
            fh.write(json.dumps(m) + '\n')
        fh.write(json.dumps({'meta': True, 'python': py, 'version': subprocess.run(
            [py, '-V'], capture_output=True, text=True).stdout.strip(), 'size': size, 'cases': len(jobs),
            'workers': workers}) + '\n')
        slow = []
        with concurrent.futures.ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(run_one, py, os.path.join(hooks, j[0]), j[6], env, root, str(k)): j
                    for k, j in enumerate(jobs)}
            for f in concurrent.futures.as_completed(futs):
                j = futs[f]
                dt, rc, crash, last = f.result()
                row = {'gate': j[0], 'event': j[1], 'tool': j[2], 'ctx': j[3], 'unit': j[4], 'bytes': j[5],
                       't': round(dt, 4), 'rc': rc, 'crash': crash}
                if last:
                    row['err'] = last  # traceback or hook_errlog line (fail-open)
                fh.write(json.dumps(row, ensure_ascii=False) + '\n')
                if dt > CONFIRM_S and j[4] != 'BASELINE':
                    slow.append(j)
        for j in slow:  # alone, full size and half size
            gate = os.path.join(hooks, j[0])
            full = run_one(py, gate, j[6], env, root, 'cf')
            mk = dict(contexts(j[2]))[j[3]]
            half_body = j[4] * max(1, (size // 2) // len(j[4].encode()))
            half = run_one(py, gate, payload(root, j[1], j[2], mk(half_body)), env, root, 'ch')
            fh.write(json.dumps({'confirm': True, 'gate': j[0], 'tool': j[2], 'ctx': j[3], 'unit': j[4],
                                 't_full': round(full[0], 4), 'rc_full': full[1], 't_half': round(half[0], 4),
                                 'rc_half': half[1], 'crash_full': full[2], 'crash_half': half[2],
                                 'err': full[3] or half[3]}, ensure_ascii=False) + '\n')
    print(f'probe: {len(jobs)} cases, {len(slow)} confirmed alone, {time.time() - t_start:.0f} s -> {out}')
    return 0


def _cell(v):
    """One table cell or detail fragment: a | or a newline in a gate name, unit or error text must not shift a cell or
    start a forged row (Viktor 50112 R3). The | becomes a broken bar (a backslash escape is GFM only)."""
    return str(v).replace('\r', ' ').replace('\n', ' ').replace('|', '\u00a6')


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v  # v == v: not NaN


def _key(r):
    return tuple(str(r[k]) for k in ('gate', 'tool', 'ctx', 'unit'))


def _failed(rc):
    """'odd' for an rc that is no verdict (not 0, 2 or a timeout), 'timeout', or None."""
    if rc == 'timeout':
        return 'timeout'
    return None if rc in (0, 2) else 'odd'


def cmd_table(path):
    """The per-gate table. Every line is checked on its own (Viktor 50112 R3): one that is not JSON, not an object, or
    misses a key is skipped and counted on a visible SKIPPED line, never a traceback. A failure of the confirm rerun
    (rc not 0/2, timeout, crash) and of a BASELINE run counts in the row's rc / crash / timeout cells and has a
    detail line, so nothing that failed is hidden behind a fast first run."""
    rows, conf, meta, info, skipped = [], {}, {}, {}, 0
    with open(path, encoding='utf-8', errors='replace') as fh:
        lines = fh.readlines()
    for line in lines:
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            skipped += 1
            continue
        if not isinstance(r, dict):
            skipped += 1
        elif r.get('meta'):
            info = r
        elif r.get('confirm'):
            if all(k in r for k in ('gate', 'tool', 'ctx', 'unit')) and _num(r.get('t_full')) and _num(r.get('t_half')):
                conf[_key(r)] = r
            else:
                skipped += 1
        elif 'excluded' in r or 'unmapped' in r:
            if 'gate' in r:
                meta[str(r['gate'])] = r
            else:
                skipped += 1
        elif all(k in r for k in ('gate', 'tool', 'ctx', 'unit', 'rc')) and _num(r.get('t')):
            rows.append(r)
        else:
            skipped += 1
    by = {}
    for r in rows:
        by.setdefault(str(r['gate']), []).append(r)
    gconf = {}
    for k, c in conf.items():
        gconf.setdefault(k[0], []).append(c)
    out = [f"Gate run time, {_cell(info.get('cases'))} cases, {_cell(info.get('size'))} bytes per case, "
           f"{_cell(info.get('workers'))} parallel, {_cell(info.get('version'))} ({_cell(info.get('python'))}); "
           f"budget {BUDGET_S:g} s; worst = alone rerun when confirmed (ratio = full / half size).", '',
           '| gate | tools | cases | baseline ms | median ms | worst s | worst case (tool/ctx/unit) | ratio | '
           '> 1 s | rc not 0/2 | crash / fail-open | timeout |', '|---|---|---|---|---|---|---|---|---|---|---|---|']
    order, base_fail = [], []
    for g, rs in by.items():
        base = [r for r in rs if r['unit'] == 'BASELINE']
        real = [r for r in rs if r['unit'] != 'BASELINE']
        cs = gconf.get(g, [])
        tools = ','.join(sorted({str(r['tool']).replace('mcp__plugin_telegram_telegram__', 'tg:') for r in rs}))
        bad_base = [(r, _failed(r['rc'])) for r in base if _failed(r['rc']) or r.get('crash')]
        if bad_base:
            base_fail.append((g, bad_base))
        conf_rcs = [c.get(k) for c in cs for k in ('rc_full', 'rc_half') if k in c]
        odd = (sum(1 for r in real if _failed(r['rc']) == 'odd') + sum(1 for x in conf_rcs if _failed(x) == 'odd')
               + sum(1 for _, f in bad_base if f == 'odd'))
        tmo = (sum(1 for r in real if r['rc'] == 'timeout') + sum(1 for x in conf_rcs if x == 'timeout')
               + sum(1 for _, f in bad_base if f == 'timeout'))
        crash = (sum(1 for r in real if r.get('crash')) + sum(1 for c in cs if c.get('crash_full') or c.get('crash_half'))
                 + sum(1 for r, _ in bad_base if r.get('crash')))
        base_ms = f"{1000 * statistics.median(r['t'] for r in base):.0f}" if base else '-'
        if not real:
            order.append((0, f"| {_cell(g)} | {_cell(tools)} | 0 | {base_ms} | - | - | - | | 0 | {odd} | {crash} | "
                             f"{tmo} |"))
            continue

        def eff(r):
            c = conf.get(_key(r))
            return c['t_full'] if c else r['t']
        worst = max(real, key=eff)
        c = conf.get(_key(worst))
        wt = eff(worst)
        ratio = f"{c['t_full'] / c['t_half']:.1f}" if c and c['t_half'] > 0 else ''
        over = sum(1 for r in real if eff(r) > BUDGET_S)
        label = (str(worst['tool']).replace('mcp__plugin_telegram_telegram__', 'tg:') + '/' + str(worst['ctx']) + '/'
                 + json.dumps(worst['unit'], ensure_ascii=False))
        order.append((wt, f"| {_cell(g)} | {_cell(tools)} | {len(real)} | {base_ms} | "
                          f"{1000 * statistics.median(r['t'] for r in real):.0f} | {wt:.2f} | {_cell(label)} | {ratio} | "
                          f"{over} | {odd} | {crash} | {tmo} |"))
    out += [line for _, line in sorted(order, key=lambda x: x[0], reverse=True)]
    for g, m in sorted(meta.items()):
        why = 'EXCLUDED: ' + str(m['excluded']) if 'excluded' in m else 'UNMAPPED: fed as Bash'
        out.append(f"| {_cell(g)} | - | - | - | - | - | {_cell(why)} | | | | | |")
    if skipped:
        out += ['', f'SKIPPED {skipped} line(s) of {_cell(path)}: not JSON, not an object, or a missing key.']
    fails = {}
    for r in rows:
        if r.get('err'):
            fails.setdefault((str(r['gate']), str(r['err'])), []).append(r)
    conf_bad = [(k, c) for k, c in sorted(conf.items()) if c.get('err') or c.get('crash_full') or c.get('crash_half')
                or _failed(c.get('rc_full', 0)) or _failed(c.get('rc_half', 0))]
    if fails or base_fail or conf_bad:
        out += ['', 'Crash / fail-open details (gate: detail -- cases, example tool/ctx/unit):']
        for (g, d), rs in sorted(fails.items()):
            ex = rs[0]
            units = ', '.join(sorted({json.dumps(r['unit'], ensure_ascii=False) for r in rs}))
            out.append(_cell(f"- {g}: {d} -- {len(rs)}, e.g. {ex['tool']}/{ex['ctx']}/"
                             f"{json.dumps(ex['unit'], ensure_ascii=False)} ({ex.get('bytes')} bytes), units: {units}"))
        for k, c in conf_bad:
            out.append(_cell(f"- {k[0]}: confirm rerun of {k[1]}/{k[2]}/{json.dumps(c['unit'], ensure_ascii=False)}"
                             f": full rc {c.get('rc_full')}, half rc {c.get('rc_half')}"
                             + (f", {c['err']}" if c.get('err') else '')))
        for g, bad in base_fail:
            out.append(_cell(f"- {g}: BASELINE failed -- " + ', '.join(
                f"{r['tool']}/{r['ctx']} rc {r['rc']}" + (' crash' if r.get('crash') else '') for r, _ in bad)))
    return '\n'.join(out)


def resolve_rev(repo, rev):
    """The full sha of the commit <rev> names, or None. A rev starting with - would be read as an option by git
    archive (--output=<path>, --remote=<url>, --prefix=../; Viktor 50112 R2), so it is refused, and git only ever
    gets the verified sha after this."""
    if not rev or rev.startswith('-'):
        return None
    p = subprocess.run(['git', '-C', repo, 'rev-parse', '--verify', '--quiet', '--end-of-options', rev + '^{commit}'],
                       capture_output=True, text=True)
    sha = p.stdout.strip()
    return sha if p.returncode == 0 and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', sha) else None


def main(argv):
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    opts = {'--workers': '4', '--size': '120000', '--only': '', '--python': shutil.which('python3') or 'python3'}
    args = []
    i = 1
    while i < len(argv):
        if argv[i] in opts and i + 1 < len(argv):
            opts[argv[i]] = argv[i + 1]
            i += 2
        else:
            args.append(argv[i])
            i += 1
    only = set(filter(None, opts['--only'].split(',')))
    try:
        workers, size = int(opts['--workers']), int(opts['--size'])
    except ValueError:
        print('probe: --workers and --size take a whole number', file=sys.stderr)
        return 2
    cmd = args[0] if args else ''
    if cmd == 'prepare' and len(args) == 4:
        repo, rev, root = args[1:]
        sha = resolve_rev(repo, rev)
        if not sha:
            print('probe: not a commit (or starts with -): ' + rev, file=sys.stderr)
            return 2
        if os.path.lexists(root) and not os.path.isdir(root):
            print('probe: root is not a directory: ' + root, file=sys.stderr)
            return 2
        if os.path.isdir(root) and os.listdir(root):
            print('probe: root not empty: ' + root, file=sys.stderr)
            return 2
        os.makedirs(root, exist_ok=True)
        a = subprocess.run(['git', '-C', repo, 'archive', sha, 'scripts'], capture_output=True)
        if a.returncode:
            print('probe: git archive failed: ' + a.stderr.decode()[:200], file=sys.stderr)
            return 2
        subprocess.run(['tar', '-x', '-C', root], input=a.stdout, check=True)
        return 0
    if cmd == 'run' and len(args) == 2:
        return cmd_run(os.path.realpath(args[1]), workers, size, only, opts['--python'])
    if cmd == 'table' and len(args) == 2:
        try:
            print(cmd_table(args[1]))
        except OSError as ex:
            print('probe: cannot read ' + args[1] + ': ' + ex.__class__.__name__, file=sys.stderr)
            return 2
        return 0
    if cmd == 'all' and len(args) == 4:
        repo, rev, work = args[1:]
        sha = resolve_rev(repo, rev)
        if not sha:
            print('probe: not a commit (or starts with -): ' + rev, file=sys.stderr)
            return 2
        # realpath: the sandbox's (subpath ROOT) matches the resolved path, so a work dir behind a symlink (the
        # macOS temp dir /var/folders is /private/var/folders) would deny every write of the run.
        root = os.path.join(os.path.realpath(work), 'root-' + sha[:8] + '-' + time.strftime('%Y%m%d%H%M%S'))
        rc = main([argv[0], 'prepare', repo, sha, root])
        if rc:
            return rc
        extra = sum(([k, v] for k, v in opts.items() if v), [])
        rc = subprocess.run(['/usr/bin/sandbox-exec', '-D', 'ROOT=' + root, '-f', PROFILE, opts['--python'], '-I',
                             os.path.abspath(__file__), 'run', root] + extra).returncode
        if rc:
            return rc
        if not os.path.isfile(os.path.join(root, 'results.jsonl')):
            print('probe: the sandboxed run wrote no results.jsonl (is --python a Python?)', file=sys.stderr)
            return 2
        table = cmd_table(os.path.join(root, 'results.jsonl'))
        table = f'Tree: {sha} ({rev})\n\n' + table
        with open(os.path.join(os.path.abspath(work), 'table-' + sha[:8] + '.md'), 'w', encoding='utf-8') as fh:
            fh.write(table + '\n')
        print(table)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
