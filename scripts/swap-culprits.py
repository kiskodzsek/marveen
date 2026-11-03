#!/usr/bin/env python3
"""Name the usual swap suspects and their owner agents, from a `ps` snapshot.

    swap-culprits.py [--ps FILE]     # FILE: `ps -axo pid=,ppid=,command=` output; default: run ps

Why (card 152400f3, 2026-11-03 16:09-16:42): the free disk fell from 13 GiB to 365 MiB while no
file grew: the swap grew from 8 to 14.8 GB on the shared APFS container. The memory was held by
a Colima VM (5.4 GB + 8.4 GB compressed) and five next dev servers (3-4 GB + 3 GB compressed
each). Cleaning files could not keep up; stopping the VM and the servers gave back 13 GiB in
minutes. So the disk guard names them and tells their owners.

Suspects: a Colima/Lima VM (limactl hostagent, the Virtualization.framework VM process, qemu) and
a next dev server: argv0 node, argv1 next's bin (node_modules/.bin/next or next/dist/bin/next),
argv2 `dev`. The owner is the first agents/<id>/ path in the
process's own or an ancestor's command line (a Claude Code shell snapshot or a worktree path);
a VM started by launchd has none and is reported with owner "-".

Output: one line per suspect, "<owner>\\t<pid>\\t<what>", the what being "Colima VM" or
"next dev :<port> <worktree>". A next dev server appears once (its next-server child is folded in).
"""
import argparse
import re
import subprocess
import sys

AGENT = re.compile(r"/agents/([a-z0-9_-]+)/")
PORT = re.compile(r"(?:-p|--port)\s+(\d+)")
# A next dev server is anchored on argv: node, then next's own bin, then `dev` (Viktor 25470 d):
# a long-lived process that only MENTIONS "next dev" in an argument (claude -p "...", a shell
# -c string, npm exec) is not a server, and mem-relief would signal it and its children.
NEXT_DEV = re.compile(r"^(?:\S*/)?node\s+\S*/(?:node_modules/\.bin/next|next/dist/bin/next)\s+dev(?:\s|$)")
TREE = re.compile(r"(/[^\s'\"]*/agents/[a-z0-9_-]+/repos/[^\s/'\"]+)")


def snapshot(path):
    text = open(path).read() if path else subprocess.run(["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True).stdout
    procs = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            procs[int(parts[0])] = (int(parts[1]), parts[2])
    return procs


def chain(procs, pid):
    seen = []
    while pid in procs and pid not in seen and len(seen) < 30:
        seen.append(pid)
        pid = procs[pid][0]
    return seen


def owner(procs, pid):
    for p in chain(procs, pid):
        match = AGENT.search(procs[p][1])
        if match:
            return match.group(1)
    return "-"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ps", default="")
    args = parser.parse_args()
    procs = snapshot(args.ps)
    out = []
    vm_done = False
    for pid, (_, cmd) in sorted(procs.items()):
        if ("limactl hostagent" in cmd or "Virtualization.VirtualMachine" in cmd or re.search(r"\bqemu-system", cmd)) and not vm_done:
            out.append((owner(procs, pid), pid, "Colima VM"))
            vm_done = True
        elif NEXT_DEV.match(cmd):
            port = PORT.search(cmd)
            tree = TREE.search(cmd) or next((TREE.search(procs[p][1]) for p in chain(procs, pid) if TREE.search(procs[p][1])), None)
            out.append((owner(procs, pid), pid, f"next dev :{port.group(1) if port else '?'} {tree.group(1) if tree else '?'}"))
    for who, pid, what in out:
        print(f"{who}\t{pid}\t{what}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
