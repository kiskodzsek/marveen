#!/usr/bin/env python3
"""Generate store/pr-kerdes/<n>.ok: the full file list of a PR, from the GitHub API, for pr-kerdes-gate.py.

    GITHUB_PERSONAL_ACCESS_TOKEN=vault:github-github_personal_access_token ./scripts/vault-env-wrapper.sh \
        python3 -I scripts/pr-kerdes.py init kiskodzsek/<repo> <n> [--force]

Read-only: three kinds of GET (the PR, its files, paginated). The host is fixed (api.github.com) and the repo must
be kiskodzsek/<name>, so the token goes nowhere else; it is read from the environment, never printed, and an API
error is reported by status code and GitHub's "message" field only. Redirects are not followed (a 3xx is an error):
urllib's default redirect handler would carry the Authorization header to the redirect target (Viktor 37340).

The written file lists every changed path as "FILE: <path> | KEPEN: ?"; fill in each KEPEN by hand
(igen <absolute image path> | nem-vevoi <reason>). Each file's blob sha is kept in a "# SHA: <blob> <path>" comment
line; re-running after a new push keeps an answer only for a file whose blob is unchanged, and reopens (and names) every
file that changed again (Viktor 37340: a carried-over "nem-vevoi" must not look fresh). A fresh file of ANOTHER repo with the same number is not
overwritten without --force.
"""
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.environ.get('CLAUDE_PROJECT_DIR') or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, 'store', 'pr-kerdes')
API = 'https://api.github.com'
REPO_RX = re.compile(r'^kiskodzsek/[A-Za-z0-9._-]+$')
MAX_PAGES = 30  # GitHub lists at most 3000 files of a PR (100 per page)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # a 3xx surfaces as HTTPError; the token never follows a redirect


_OPENER = urllib.request.build_opener(_NoRedirect)


def _get(path, token):
    req = urllib.request.Request(API + path, headers={
        'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'marveen-pr-kerdes'})
    try:
        with _OPENER.open(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = str(json.load(e).get('message', ''))[:200]
        except Exception:
            msg = ''
        raise SystemExit(f'GitHub API {e.code} on {path.split("?")[0]}: {msg}')


def list_hash(paths):
    return hashlib.sha256('\n'.join(sorted(paths)).encode('utf-8')).hexdigest()


def fetch(repo, n, token, get=_get):
    """(head sha, {path: blob sha}) of PR n, every path, or SystemExit."""
    pr = get(f'/repos/{repo}/pulls/{n}', token)
    head = str((pr.get('head') or {}).get('sha') or '')
    want = int(pr.get('changed_files') or 0)
    paths, blobs = [], {}
    for page in range(1, MAX_PAGES + 1):
        batch = get(f'/repos/{repo}/pulls/{n}/files?per_page=100&page={page}', token)
        for f in batch:
            paths.append(str(f['filename']))
            blobs[str(f['filename'])] = str(f.get('sha') or '-')
        if len(batch) < 100:
            break
    if len(paths) != want or len(set(paths)) != len(paths):
        raise SystemExit(f'PR #{n}: the API listed {len(paths)} files, the PR says {want}; not writing a partial list.')
    if not re.fullmatch(r'[0-9a-f]{40}', head):
        raise SystemExit(f'PR #{n}: no head sha in the API answer.')
    return head, blobs


def previous(path):
    """(repo, {file: kepen}, {file: blob sha}) of an existing .ok, or ('', {}, {})."""
    repo, ans, blobs = '', {}, {}
    try:
        for line in open(path, encoding='utf-8'):
            line = line.strip()
            if line.startswith('REPO:'):
                repo = line[5:].strip()
            elif line.startswith('# SHA:'):
                parts = line[len('# SHA:'):].strip().split(' ', 1)
                if len(parts) == 2:
                    blobs[parts[1]] = parts[0]
            elif line.startswith('FILE:') and '| KEPEN:' in line:
                p, k = line[5:].split('| KEPEN:', 1)
                if k.strip() and k.strip() != '?':
                    ans[p.strip()] = k.strip()
    except FileNotFoundError:
        pass
    return repo, ans, blobs


def render(repo, n, head, blobs, answers, now=None):
    paths = sorted(blobs)
    now = now or datetime.now(timezone.utc)
    out = [
        f'# PR-kerdes lap (scripts/pr-kerdes.py). Minden FILE sorba: KEPEN: igen <abszolut kep> | nem-vevoi <indok>.',
        f'# Az "igen" kepet a kerdo uzenethez csatold (files). A FILE sorokat ne torold, ne add hozza: a LISTA hash ellenorzi.',
        f'REPO: {repo}',
        f'PR: {n}',
        f'HEAD: {head}',
        f'GENERALT: {now.strftime("%Y-%m-%dT%H:%M:%SZ")}',
        f'LISTA: {len(paths)} {list_hash(paths)}',
    ]
    out += [f'# SHA: {blobs[p]} {p}' for p in paths]
    out += [f'FILE: {p} | KEPEN: {answers.get(p, "?")}' for p in paths]
    return '\n'.join(out) + '\n'


def init(repo, n, force, token, get=_get):
    if not REPO_RX.match(repo):
        raise SystemExit(f'repo must be kiskodzsek/<name>, got {repo!r}')
    path = os.path.join(DIR, f'{n}.ok')
    old_repo, answers, old_blobs = previous(path)
    if old_repo and old_repo != repo:
        if not force:
            raise SystemExit(f'{path} belongs to {old_repo}; --force to replace it with {repo} #{n}.')
        answers = {}
    head, blobs = fetch(repo, n, token, get)
    paths = sorted(blobs)
    changed = sorted(p for p in answers if p in blobs and (old_blobs.get(p) != blobs[p] or blobs[p] == '-'))
    answers = {p: k for p, k in answers.items() if p in blobs and p not in changed}
    os.makedirs(DIR, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(render(repo, n, head, blobs, answers))
    os.replace(tmp, path)
    todo = sum(1 for p in paths if p not in answers)
    print(f'{path}: {repo} #{n} head {head[:12]}, {len(paths)} files, {todo} KEPEN to fill, '
          f'{len(paths) - todo} kept (blob unchanged).')
    if changed:
        print('reopened, changed since the previous sheet: ' + ', '.join(changed))
    return 0


def main(argv):
    if len(argv) < 3 or argv[0] != 'init' or not argv[2].isdigit():
        sys.stderr.write(__doc__)
        return 2
    token = os.environ.get('GITHUB_PERSONAL_ACCESS_TOKEN', '')
    if not token or token.startswith('vault:'):
        sys.stderr.write('GITHUB_PERSONAL_ACCESS_TOKEN is not set: run through ./scripts/vault-env-wrapper.sh '
                         '(see the usage above).\n')
        return 2
    return init(argv[1], int(argv[2]), '--force' in argv[3:], token)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
