#!/usr/bin/env python3
"""probe.py -- the run time of every hook gate (scripts/hooks/*gate.py) on generated 60-120 KB repeated shapes.

Why (card 3b05ae69, DREAM 11-22): of the 38 gates only 7 have a test that measures time, and the time-claim-gate's
quadratic regex came back four times on one card (81a70e99), each found only by Viktor's review. A hook gate has a
10 s limit and runs on every tool call; this probe gives every gate the same repeated shapes and records the wall
time of the real hook process (python start included, what the session waits for), against a 1 s budget per run.

  probe.py all <repo> <rev> <workdir> [--workers N] [--size BYTES] [--only NAME[,NAME]] [--python PY]
      prepare + run (in the sandbox) + table; the table goes to stdout and <workdir>/table.md.
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


def self_check(root):
    """None when sandboxed, else the reason."""
    outside = os.path.join(os.path.dirname(os.path.abspath(root)), '.gate-timing-escape-test')
    try:
        with open(outside, 'w') as fh:
            fh.write('x')
        os.unlink(outside)
        return 'a write outside ROOT succeeded'
    except OSError:
        pass
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
                                 'rc_half': half[1]}, ensure_ascii=False) + '\n')
    print(f'probe: {len(jobs)} cases, {len(slow)} confirmed alone, {time.time() - t_start:.0f} s -> {out}')
    return 0


def cmd_table(path):
    rows, conf, meta, info = [], {}, {}, {}
    for line in open(path, encoding='utf-8'):
        r = json.loads(line)
        if r.get('meta'):
            info = r
        elif r.get('confirm'):
            conf[(r['gate'], r['tool'], r['ctx'], r['unit'])] = r
        elif 'excluded' in r or 'unmapped' in r:
            meta[r['gate']] = r
        else:
            rows.append(r)
    by = {}
    for r in rows:
        by.setdefault(r['gate'], []).append(r)
    out = [f"Gate run time, {info.get('cases')} cases, {info.get('size')} bytes per case, "
           f"{info.get('workers')} parallel, {info.get('version')} ({info.get('python')}); budget {BUDGET_S:g} s; "
           'worst = alone rerun when confirmed (ratio = full / half size).', '',
           '| gate | tools | cases | baseline ms | median ms | worst s | worst case (tool/ctx/unit) | ratio | '
           '> 1 s | rc not 0/2 | crash / fail-open | timeout |', '|---|---|---|---|---|---|---|---|---|---|---|---|']
    order = []
    for g, rs in by.items():
        base = [r['t'] for r in rs if r['unit'] == 'BASELINE']
        real = [r for r in rs if r['unit'] != 'BASELINE']
        worst = max(real, key=lambda r: r['t'])
        c = conf.get((g, worst['tool'], worst['ctx'], worst['unit']))
        wt = c['t_full'] if c else worst['t']
        ratio = f"{c['t_full'] / c['t_half']:.1f}" if c and c['t_half'] > 0 else ''
        over = sum(1 for r in real if (conf.get((g, r['tool'], r['ctx'], r['unit'])) or {}).get('t_full', r['t'])
                   > BUDGET_S)
        odd = sum(1 for r in real if r['rc'] not in (0, 2, 'timeout'))
        tools = ','.join(sorted({str(r['tool']).replace('mcp__plugin_telegram_telegram__', 'tg:') for r in rs}))
        label = (str(worst['tool']).replace('mcp__plugin_telegram_telegram__', 'tg:') + '/' + worst['ctx'] + '/'
                 + json.dumps(worst['unit'], ensure_ascii=False))
        order.append((wt, f"| {g} | {tools} | {len(real)} | {1000 * statistics.median(base):.0f} | "
                          f"{1000 * statistics.median(r['t'] for r in real):.0f} | {wt:.2f} | {label} | {ratio} | "
                          f"{over} | {odd} | {sum(r['crash'] for r in real)} | "
                          f"{sum(1 for r in real if r['rc'] == 'timeout')} |"))
    out += [line for _, line in sorted(order, reverse=True)]
    for g, m in sorted(meta.items()):
        out.append(f"| {g} | - | - | - | - | - | {'EXCLUDED: ' + m['excluded'] if 'excluded' in m else 'UNMAPPED: fed as Bash'} | | | | | |")
    fails = {}
    for r in rows:
        if r.get('err'):
            fails.setdefault((r['gate'], r['err']), []).append(r)
    if fails:
        out += ['', 'Crash / fail-open details (gate: detail -- cases, example tool/ctx/unit):']
        for (g, d), rs in sorted(fails.items()):
            ex = rs[0]
            out.append(f"- {g}: {d} -- {len(rs)}, e.g. {ex['tool']}/{ex['ctx']}/{json.dumps(ex['unit'], ensure_ascii=False)}"
                       f" ({ex['bytes']} bytes), units: {', '.join(sorted({json.dumps(r['unit'], ensure_ascii=False) for r in rs}))}")
    return '\n'.join(out)


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
    cmd = args[0] if args else ''
    if cmd == 'prepare' and len(args) == 4:
        repo, rev, root = args[1:]
        if os.path.exists(root) and os.listdir(root):
            print('probe: root not empty: ' + root, file=sys.stderr)
            return 2
        os.makedirs(root, exist_ok=True)
        a = subprocess.run(['git', '-C', repo, 'archive', rev, 'scripts'], capture_output=True)
        if a.returncode:
            print('probe: git archive failed: ' + a.stderr.decode()[:200], file=sys.stderr)
            return 2
        subprocess.run(['tar', '-x', '-C', root], input=a.stdout, check=True)
        return 0
    if cmd == 'run' and len(args) == 2:
        return cmd_run(os.path.abspath(args[1]), int(opts['--workers']), int(opts['--size']), only, opts['--python'])
    if cmd == 'table' and len(args) == 2:
        print(cmd_table(args[1]))
        return 0
    if cmd == 'all' and len(args) == 4:
        repo, rev, work = args[1:]
        sha = subprocess.run(['git', '-C', repo, 'rev-parse', rev], capture_output=True, text=True).stdout.strip()
        if not sha:
            print('probe: unknown rev ' + rev, file=sys.stderr)
            return 2
        root = os.path.join(os.path.abspath(work), 'root-' + sha[:8] + '-' + time.strftime('%Y%m%d%H%M%S'))
        rc = main([argv[0], 'prepare', repo, sha, root])
        if rc:
            return rc
        extra = sum(([k, v] for k, v in opts.items() if v), [])
        rc = subprocess.run(['/usr/bin/sandbox-exec', '-D', 'ROOT=' + root, '-f', PROFILE, opts['--python'], '-I',
                             os.path.abspath(__file__), 'run', root] + extra).returncode
        if rc:
            return rc
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
