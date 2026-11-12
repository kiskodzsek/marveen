#!/usr/bin/env python3
"""mcp-pin-run.py -- start an MCP server only if every pinned file still has its sha256 (Viktor 37600 L2).

Why (card 446b8283, Klodel 39314): the SEO MCP servers (GSC, funnel, Trends, GA4, Ads, DataForSEO) live in
agents/kernel/tools/, a folder every agent on this OS user can write. Viktor's condition for wiring them into
Radar's, Szigma's and Magnes's .mcp.json is a hash check before the command runs, so a changed server file does not
start silently with the agent's context and the shared Google key. The launcher itself lives HERE, in scripts/,
written only through the controlled PR path (Viktor 39318 HIGH: a launcher next to the files it guards can be
rewritten together with them).

Usage (the .mcp.json "command" is /usr/bin/python3, "args" are these):
    -I /Users/klodel/marveen/scripts/mcp-pin-run.py <sha256>=<abs path> [...] -- <command> [args ...]
Every pin is the FULL 64-hex sha256 of the file's realpath. Every argument after "--" that names an existing
.mjs/.js/.cjs/.py file must be pinned too, so the server script itself cannot be left out of the list. A pin need
not be an argument: a file the server runs or reads (scripts/vault-resolve.mjs, the node binary, sitemap.xml) is
pinned the same way (Viktor 39318 MEDIUM/LOW).
On a match the launcher exec()s the command with every pinned file replaced by the realpath that was hashed, the
command too when its resolved path is pinned (Viktor 39318 INFO 1: a symlink swapped after the check is not
followed). Same pid, stdio and env (the MCP env such as GA4_MODE comes from .mcp.json). On any mismatch, missing file, bad pin or unpinned script it writes ONE line to
stderr (the file name and the first 16 hex of both hashes, no file content) and exits 78 (EX_CONFIG): the server
does not start, and the agent sees the MCP server as failed.

Limits (stated, not solved): the file itself can still change between the hash and the exec (milliseconds);
only plain file arguments are forced to be pinned ("--require=/x.js" or NODE_OPTIONS are not; the wired configs
use fixed args); the root node_modules (@modelcontextprotocol/sdk, zod) is not pinned (accepted, Viktor 39318);
the pins in an agent's .mcp.json are only as safe as that file.
Tests: python3 -I scripts/__tests__/mcp-pin-run.test.py
"""
import hashlib
import os
import re
import shutil
import sys

EX_CONFIG = 78
PIN_RX = re.compile(r'^([0-9a-f]{64})=(/.+)$')
SCRIPT_EXT = ('.mjs', '.js', '.cjs', '.py')


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def fail(msg):
    sys.stderr.write('mcp-pin-run: REFUSED: ' + msg + '\n')
    return EX_CONFIG


def main(argv):
    if '--' not in argv:
        return fail('usage: <sha256>=<abs path> ... -- <command> [args]')
    cut = argv.index('--')
    pins, cmd = argv[:cut], argv[cut + 1:]
    if not pins or not cmd:
        return fail('at least one pin and a command are needed')
    pinned = set()
    for p in pins:
        m = PIN_RX.match(p)
        if not m:
            return fail('a pin is not <64 hex sha256>=<absolute path>: %r' % p[:80])
        want, path = m.group(1), m.group(2)
        real = os.path.realpath(path)
        try:
            got = sha256(real)
        except OSError as e:
            return fail('%s: unreadable (%s)' % (os.path.basename(path), e.__class__.__name__))
        if got != want:
            return fail('%s: sha256 %s..., pinned %s...' % (os.path.basename(path), got[:16], want[:16]))
        pinned.add(real)
    for a in cmd[1:]:
        if a.lower().endswith(SCRIPT_EXT) and os.path.isfile(a) and os.path.realpath(a) not in pinned:
            return fail('%s is run but not pinned' % os.path.basename(a))
    # Exec the hashed realpaths, not the names that pointed at them (Viktor 39318 INFO 1).
    run = [os.path.realpath(a) if os.path.isfile(a) and os.path.realpath(a) in pinned else a for a in cmd]
    exe = shutil.which(cmd[0])
    if exe and os.path.realpath(exe) in pinned:
        run[0] = os.path.realpath(exe)
    try:
        os.execvp(run[0], run)
    except OSError as e:
        return fail('%s: cannot start (%s)' % (cmd[0], e.__class__.__name__))


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
