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

Memory footprint (2026-11-04 20:56-21:08, Klodel 26838/26851): the free disk fell to 1.3 GiB with
swap at 23 GB while neither a VM nor a dev server ran, so the name list above found nothing. The
memory was held by VTDecoderXPCService (macOS video decoder), 44 GB footprint in `top`, and its
client was WallpaperAerialsExtension (the animated Aerial wallpaper): stopping the extension made
the decoder exit and stay gone. So the footprint (`top -l 1 -stats pid,mem`, or --top FILE) adds:
  "video decoder <N> GB"  VTDecoderXPCService at or over --decoder-gb (4) GB; mem-relief stops it;
  "Aerial wallpaper"      WallpaperAerialsExtension, any size (the decoder's client); mem-relief stops it;
  "large <name> <N> GB"   any other process at or over --large-gb (6) GB: named for the alert, never
                          stopped by mem-relief (it may be someone's work).
With --ps and no --top (a test fixture) no footprint is read: a fixture never mixes with the live host.
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


def footprints(path, fixture):
    """pid -> footprint in MB, from `top -l 1 -stats pid,mem` (e.g. "40542  44G", "432  339M+")."""
    if path:
        text = open(path).read()
    elif fixture:
        return {}
    else:
        # Viktor 26868 INFO-2: an absolute path and a timeout, so a stuck top cannot hold the launchd job.
        try:
            text = subprocess.run(["/usr/bin/top", "-l", "1", "-stats", "pid,mem"], capture_output=True, text=True, timeout=30).stdout
        except (subprocess.TimeoutExpired, OSError):
            return {}
    unit = {"B": 1 / 1048576, "K": 1 / 1024, "M": 1, "G": 1024, "T": 1048576}
    out = {}
    for line in text.splitlines():
        m = re.match(r"^\s*(\d+)\s+([\d.]+)([BKMGT])[+-]?\s*$", line)
        if m:
            out[int(m.group(1))] = float(m.group(2)) * unit[m.group(3)]
    return out


def gb(mb):
    return f"{mb / 1024:.1f}"


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


# The heavy-process gate (Klodel 34315/34318, 2026-11-09): the Mac took its second kernel panic at 15:19 ("watchdog
# timeout", 908 free pages, ~15 GiB wired) with two Blender renders resident at 11.2 + 6.4 GB on a 16 GiB machine
# (/Library/Logs/DiagnosticReports/panic-full-2026-11-09-151916.0002.panic); Patrik restarted it by hand (TG 17017).
# Neither render ran under heavy-job.sh, so nothing held the second one back and nothing stopped them when memory
# ran out. Heavy = Blender, ffmpeg, mflux (Klodel 34318). A heavy process is "gated" when a process in its parent
# chain RUNS heavy-job.sh (argv0 or argv1 ends with /heavy-job.sh), not when some ancestor's text merely mentions it.
def heavy_kind(cmd):
    words = cmd.split()
    if not words:
        return None
    base = words[0].rsplit("/", 1)[-1]
    if base == "Blender":
        return "Blender"
    if base == "ffmpeg":
        return "ffmpeg"
    # mflux runs as its console script (argv0) or under python (argv1 / `python -m mflux...`)
    if any(w.rsplit("/", 1)[-1].startswith("mflux") for w in words[:3]):
        return "mflux"
    return None


def gated(procs, pid):
    for p in chain(procs, pid)[1:]:
        words = procs[p][1].split()
        if any(w.rsplit("/", 1)[-1] == "heavy-job.sh" for w in words[:2]):
            return True
    return False


def heavy_roots(procs):
    """(pid, kind) for every heavy process whose parent is not a heavy process of the same kind (counted once)."""
    out = []
    for pid, (ppid, cmd) in sorted(procs.items()):
        kind = heavy_kind(cmd)
        if kind and not (ppid in procs and heavy_kind(procs[ppid][1]) == kind):
            out.append((pid, kind))
    return out


def ungated_heavy(procs):
    """(owner, pid, "ungated <kind>") for every heavy process with no heavy-job.sh in its parent chain."""
    return [(owner(procs, pid), pid, f"ungated {kind}") for pid, kind in heavy_roots(procs) if not gated(procs, pid)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ps", default="")
    parser.add_argument("--top", default="")
    parser.add_argument("--decoder-gb", type=float, default=4)
    parser.add_argument("--large-gb", type=float, default=6)
    parser.add_argument("--ungated-heavy", action="store_true",
                        help="print only the heavy processes (Blender, ffmpeg, mflux) not running under heavy-job.sh")
    parser.add_argument("--heavy", action="store_true",
                        help="print every heavy process with its footprint, the largest first (gated or not)")
    args = parser.parse_args()
    procs = snapshot(args.ps)
    if args.ungated_heavy:
        for who, pid, what in ungated_heavy(procs):
            print(f"{who}\t{pid}\t{what}")
        return 0
    if args.heavy:
        mem = footprints(args.top, bool(args.ps) and not args.top)
        rows = sorted(heavy_roots(procs), key=lambda r: -mem.get(r[0], 0))
        for pid, kind in rows:
            print(f"{owner(procs, pid)}\t{pid}\theavy {kind} {gb(mem.get(pid, 0))} GB")
        return 0
    mem = footprints(args.top, bool(args.ps))
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
        elif cmd.split(" ", 1)[0].endswith("/WallpaperAerialsExtension"):  # argv0, as measured 2026-11-04 21:03
            out.append(("-", pid, "Aerial wallpaper"))
        elif cmd.split(" ", 1)[0].endswith("/VTDecoderXPCService") and mem.get(pid, 0) >= args.decoder_gb * 1024:
            out.append(("-", pid, f"video decoder {gb(mem[pid])} GB"))
    listed = {pid for _, pid, _ in out}
    for pid, mb in sorted(mem.items(), key=lambda kv: -kv[1]):
        if mb >= args.large_gb * 1024 and pid not in listed and pid in procs and pid != 0:
            # Viktor 26868 LOW-3: the name goes into a message sent as the main agent; any same-user
            # process can choose it, so only a short, plain form passes.
            name = re.sub(r"[^A-Za-z0-9._-]", "_", procs[pid][1].split(" ", 1)[0].rsplit("/", 1)[-1])[:40]
            out.append((owner(procs, pid), pid, f"large {name} {gb(mb)} GB"))
    for who, pid, what in out:
        print(f"{who}\t{pid}\t{what}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
