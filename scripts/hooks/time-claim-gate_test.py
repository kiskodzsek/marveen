#!/usr/bin/env python3
"""Tests for time-claim-gate.py (Klodel 38401).

Runs the hook as Claude Code does (PreToolUse JSON on stdin; exit 0 allow, 2 block) with a fixed
TIME_CLAIM_GATE_NOW. Most cases run a COPY of the hook in a throw-away root, so <root>/shared/ is a temp
directory and no file is created in the checkout; one case runs the real file to pin the root resolution.
Fixture dates are built from today's date, so the "same day" / "other day" cases hold on any day.
Run: python3 -I scripts/hooks/time-claim-gate_test.py
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REAL_HOOK = os.path.join(HERE, 'time-claim-gate.py')
TODAY = datetime.date.today()
TOMORROW = TODAY + datetime.timedelta(days=1)
KANBAN = 'curl -s -X POST http://localhost:3420/api/kanban/abc/comments -H "Content-Type: application/json"'


def make_root(tmp):
    hooks = os.path.join(tmp, 'scripts', 'hooks')
    os.makedirs(hooks)
    shutil.copy(REAL_HOOK, hooks)
    shutil.copy(os.path.join(HERE, 'hook_errlog.py'), hooks)
    os.makedirs(os.path.join(tmp, 'shared', 'x'))
    return os.path.join(hooks, 'time-claim-gate.py')


def run(hook, tool, tool_input=None, now='18:14', raw=None, cwd=None, errlog=None):
    env = {'PATH': '/usr/bin:/bin', 'TIME_CLAIM_GATE_NOW': now, 'HOOK_ERRLOG_PATH': errlog or os.devnull}
    body = {'tool_name': tool, 'tool_input': tool_input}
    if cwd:
        body['cwd'] = cwd
    payload = raw if raw is not None else json.dumps(body)
    p = subprocess.run([sys.executable, '-I', hook], input=payload, capture_output=True, text=True, env=env, timeout=20)
    return p.returncode, p.stdout, p.stderr


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def write(root, text, name='x/report.md', **kw):
    return run(root['hook'], 'Write', {'file_path': os.path.join(root['dir'], 'shared', name), 'content': text}, **kw)


# ---- BLOCK ----

@case
def block_future_range_dated_today(root):
    code, out, err = write(root, f'Kernel, {TODAY:%Y-%m-%d} (mérve 18:15-18:30, `date`)')
    return code == 2 and '18:30' in err and 'line 1' in err and out == ''


@case
def block_placeholder_in_shared_md(root):
    code, _, err = write(root, 'fejléc\naz Ads-hívás 19:3x és 18:00 között')
    return code == 2 and '19:3x' in err and 'line 2' in err


@case
def block_placeholder_upper_x(root):
    return write(root, 'kész 09:3X-kor')[0] == 2 and write(root, 'kész 10:XX-re')[0] == 2


@case
def block_edit_future_measured(root):
    ti = {'file_path': os.path.join(root['dir'], 'shared', 'x', 'r.md'), 'old_string': 'TODO', 'new_string': 'mérve 23:58'}
    code, _, err = run(root['hook'], 'Edit', ti)
    return code == 2 and '23:58' in err


@case
def block_multiedit_second_edit(root):
    ti = {'file_path': os.path.join(root['dir'], 'shared', 'x', 'r.md'),
          'edits': [{'old_string': 'a', 'new_string': 'rendben'}, {'old_string': 'b', 'new_string': 'measured 20:00'}]}
    return run(root['hook'], 'MultiEdit', ti)[0] == 2


@case
def block_kanban_heredoc_placeholder(root):
    cmd = KANBAN + " --data-binary @- <<'JSON'\n{\"author\":\"kernel\",\"content\":\"Kernel 10:xx: kész\"}\nJSON"
    code, _, err = run(root['hook'], 'Bash', {'command': cmd})
    return code == 2 and '10:xx' in err and 'command line 2' in err


@case
def block_kanban_data_file(root):
    path = os.path.join(root['dir'], 'payload.json')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('{"author":"kernel","content":"riport, mérve 23:50"}\n')
    code, _, err = run(root['hook'], 'Bash', {'command': KANBAN + f' --data-binary @{path}'})
    return code == 2 and '@file line 1' in err and '23:50' in err


@case
def block_kanban_relative_data_file_d_flag(root):
    with open(os.path.join(root['dir'], 'p.json'), 'w', encoding='utf-8') as fh:
        fh.write('{"content":"lezárva 19:00"}')
    return run(root['hook'], 'Bash', {'command': KANBAN + ' -d @p.json'}, cwd=root['dir'])[0] == 2


@case
def block_range_not_misread_as_date(root):
    # "10:05-11:30" contains "05-11"; it must not count as the date May 11 and hide the line.
    return write(root, 'mérve 10:05-11:30', now='09:00')[0] == 2


@case
def block_marker_case_insensitive(root):
    return write(root, 'MÉRVE 20:00')[0] == 2 and write(root, 'date szerint 20:00')[0] == 2


@case
def block_same_line_with_today_mmdd(root):
    return write(root, f'{TODAY:%m-%d} mérve 23:00')[0] == 2


@case
def block_real_hook_resolves_repo_shared(root):
    # The real file: <repo-root>/shared/ is two levels above scripts/hooks/. The path need not exist.
    repo = os.path.realpath(os.path.join(HERE, '..', '..'))
    ti = {'file_path': os.path.join(repo, 'shared', 'no-such-dir-tcg', 'r.md'), 'content': 'mérve 23:59'}
    return run(REAL_HOOK, 'Write', ti)[0] == 2


# ---- PASS ----

@case
def pass_future_deadline_without_marker(root):
    return all(write(root, t)[0] == 0 for t in ('határidő 21:00-ig kész', 'holnap 10:00', 'kész lesz 23:30-ra'))


@case
def pass_deadline_on_a_marker_line(root):
    # A measured line may name a deadline; the deadline is not a measured time.
    texts = ('mérve 18:10, kész 22:00-ig', 'mérve 18:10; határidő 22:00', 'measured 18:10, due by 22:00',
             'mért 18:10, 21:30-ra kész', 'lefutott 18:12, 22:00 óráig')
    return all(write(root, t)[0] == 0 for t in texts)


@case
def block_measured_future_next_to_deadline(root):
    # The deadline exemption is per time token: the guessed measured time on the same line still blocks.
    code, _, err = write(root, 'mérve 20:15, kész 22:00-ig')
    return code == 2 and '20:15' in err and '22:00' not in err


@case
def long_line_is_bounded(root):
    # Viktor 38419 LOW: 20000 times on one line took 13.6 s (quadratic prefix scan). Now bounded.
    import time
    t0 = time.monotonic()
    code = write(root, 'mérve ' + '10:00 ' * 20000, now='11:00')[0]
    return code == 0 and time.monotonic() - t0 < 3


@case
def pass_past_and_slack(root):
    return write(root, 'mérve 18:08-18:14')[0] == 0 and write(root, 'mérve 18:16')[0] == 0


@case
def pass_not_clock_times(root):
    return all(write(root, t)[0] == 0 for t in ('cron 0 9 * * *', 'arány 3:2', 'hex 0x1f', 'mérve 2026-11-11T23:30:00'))


@case
def pass_other_day_line(root):
    return (write(root, f'{TOMORROW:%Y-%m-%d} mérve 23:00')[0] == 0
            and write(root, f'{TOMORROW:%m-%d} lefutott 23:00')[0] == 0)


@case
def pass_out_of_scope_paths_and_tools(root):
    shared_txt = os.path.join(root['dir'], 'shared', 'x', 'notes.txt')
    outside_md = os.path.join(root['dir'], 'docs', 'r.md')
    h = root['hook']
    return (run(h, 'Write', {'file_path': shared_txt, 'content': 'mérve 23:59 19:3x'})[0] == 0
            and run(h, 'Write', {'file_path': outside_md, 'content': 'mérve 23:59 19:3x'})[0] == 0
            and run(h, 'Read', {'file_path': os.path.join(root['dir'], 'shared', 'x', 'r.md')})[0] == 0
            and run(h, 'Bash', {'command': 'echo "mérve 23:59 19:3x" > /dev/null'})[0] == 0
            and run(h, 'Bash', {'command': 'curl http://localhost:3420/api/kanban/abc -d "19:3x"'})[0] == 0)


@case
def pass_symlink_out_of_shared_is_judged_by_realpath(root):
    # A link under shared/ that points outside: the realpath is not in shared/, so it is out of scope.
    target = os.path.join(root['dir'], 'outside.md')
    open(target, 'w').close()
    link = os.path.join(root['dir'], 'shared', 'x', 'link.md')
    os.symlink(target, link)
    return run(root['hook'], 'Write', {'file_path': link, 'content': 'mérve 23:59'})[0] == 0


@case
def pass_write_keeps_existing_lines(root):
    # Rewriting a report whose old, undated lines hold a later time: only the NEW lines are judged.
    path = os.path.join(root['dir'], 'shared', 'x', 'log.md')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('tegnap: mérve 22:10\n')
    ok_keep = run(root['hook'], 'Write', {'file_path': path, 'content': 'tegnap: mérve 22:10\nma: mérve 18:00\n'})[0] == 0
    bad_new = run(root['hook'], 'Write', {'file_path': path, 'content': 'tegnap: mérve 22:10\nma: mérve 22:11\n'})[0] == 2
    return ok_keep and bad_new


@case
def pass_edit_context_lines_from_old_string(root):
    ti = {'file_path': os.path.join(root['dir'], 'shared', 'x', 'r.md'),
          'old_string': 'tegnap: mérve 22:10', 'new_string': 'tegnap: mérve 22:10\nma: mérve 18:00'}
    return run(root['hook'], 'Edit', ti)[0] == 0


@case
def pass_kanban_data_file_too_big_or_missing(root):
    big = os.path.join(root['dir'], 'big.json')
    with open(big, 'w', encoding='utf-8') as fh:
        fh.write('mérve 23:50\n' + 'x' * (64 * 1024 + 1))
    return (run(root['hook'], 'Bash', {'command': KANBAN + f' --data-binary @{big}'})[0] == 0
            and run(root['hook'], 'Bash', {'command': KANBAN + ' --data-binary @/no/such/file.json'})[0] == 0)


@case
def pass_fail_open_on_garbage(root):
    h = root['hook']
    return (run(h, 'Write', raw='this is not json')[0] == 0
            and run(h, 'Write', raw='[1, 2]')[0] == 0
            and run(h, 'Write', ['not-a-dict'])[0] == 0
            and run(h, 'Write', {'file_path': 7, 'content': None})[0] == 0
            and run(h, 'MultiEdit', {'file_path': os.path.join(root['dir'], 'shared', 'a.md'), 'edits': 'x'})[0] == 0
            and run(h, 'Write', raw='')[0] == 0)


@case
def bad_now_override_is_ignored_not_crashing(root):
    code, _, err = write(root, 'rendben', now='25:99')
    return code == 0 and err == ''


@case
def block_text_names_only_the_token(root):
    secretish = 'SZINTETIKUS-titok-szoveg-ne-jelenjen-meg'
    code, _, err = write(root, f'{secretish} mérve 23:40')
    return code == 2 and secretish not in err and '23:40' in err


def main():
    failed = []
    for fn in CASES:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = os.path.realpath(tmp)
            root = {'dir': tmp, 'hook': make_root(tmp)}
            try:
                ok = fn(root)
            except Exception as ex:  # a crashing case is a failing case
                ok = False
                print(f'  {fn.__name__}: {ex!r}')
        print(('PASS ' if ok else 'FAIL ') + fn.__name__)
        if not ok:
            failed.append(fn.__name__)
    print(f'{len(CASES) - len(failed)}/{len(CASES)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
