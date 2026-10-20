#!/usr/bin/env python3
"""Local nudity screen for generated images (mflux output), fail-closed.

Why (card 1a4fe725, Klodel 8990, Patrik TG 3854): a baby-scene generation came
out nude (Mira 8972). Every generated image must be screened BEFORE any agent
opens it -- whatever lands in an agent's context also goes to the model provider
(Viktor 9018 F2). So the generator writes into <root>/_unscreened/, and only a
"pass" verdict moves an image out of it. Agents never read _unscreened/ or
_quarantine/ (governance gate in scripts/self-pace-gate.mjs).

Verdicts:
  pass        -> the image (and its .metadata.json) moves to the destination
  flag/error  -> the image moves to <root>/_quarantine/ and gets mode 000;
                 one log line, one seed-blocklist line, one message to mira+klodel

Fail-closed: a detector above its threshold, a detector error, a symlink, a path
outside the root -- all quarantine. If the detectors cannot even load, NOTHING is
touched: the images stay in _unscreened/ (still unreadable to agents) and the exit
code is 3.

What this is NOT (Viktor 9018, Lex 9016): a guarantee. Recall on child nudity is
not measured and must not be (no such test set is collected or generated). The
prompt (clothing always) and Mira's review stay the primary controls. mode 000 is
a "do not open by accident" guard, not a security boundary: every agent runs as
the same uid.

The log, the blocklist and the message carry only: time, file name, prompt-file
NAME (never its text), seed, detector, score. No image, preview, base64 or link.

Usage (inside Mira's venv, after the models are in place):
  check.py --root <mflux-root> inbox --dest out/panna
  check.py --root <mflux-root> sweep [--dirs out final drafts]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import socket
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
STORE = REPO / "store"
LOG_PATH = STORE / "image-safety.log"
BLOCKLIST_PATH = STORE / "image-safety-seed-blocklist.tsv"
AGENT_MSG = REPO / "scripts" / "agent-msg.sh"

UNSCREENED = "_unscreened"
QUARANTINE = "_quarantine"
QUARANTINE_META = "quarantine-meta"
PASSED_LEDGER = ".image-safety-passed.jsonl"
# The ONE list of directories the sweep never enters and the governance gate
# (scripts/self-pace-gate.mjs SCREENING_DIRS) bans; a test keeps the two equal.
# panna-elvetett/ and visszavonva/ are Mira's reject dirs from before the screen:
# untouched until Lex decides (Viktor 9018 F5, review B1).
SCREENING_DIRS = (QUARANTINE, UNSCREENED, "panna-elvetett", "visszavonva", QUARANTINE_META)
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".gif", ".tif", ".tiff", ".bmp", ".avif"}
SEED_RX = re.compile(r"^(?P<prompt>.+?)_seed(?P<seed>\d+)$")

EXIT_OK = 0
EXIT_QUARANTINED = 2
EXIT_DETECTORS_UNAVAILABLE = 3
EXIT_FILE_ERRORS = 4
EXIT_USAGE = 64


class DetectorError(Exception):
    """A detector could not produce a verdict for this image."""


@dataclass
class Detector:
    name: str
    threshold: float
    score: Callable[[Path], float]  # 0..1, higher = more likely nudity


@dataclass
class Verdict:
    flagged: bool
    detector: str
    score: float | None
    error: str | None = None


# --- network guard -----------------------------------------------------------

def block_network() -> None:
    """The screen runs offline (Viktor 9018 F1). Hub libraries get the offline
    switches, and any socket connect raises, so a model loader that tries to
    phone home fails loudly instead of fetching."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    def _refuse(*_a, **_k):
        raise OSError("image-safety: network access is disabled")

    socket.socket.connect = _refuse  # type: ignore[method-assign]
    socket.socket.connect_ex = _refuse  # type: ignore[method-assign]
    socket.create_connection = _refuse  # type: ignore[assignment]


# --- screening ---------------------------------------------------------------

def screen(path: Path, detectors: list[Detector]) -> Verdict:
    """Run every detector; the first flag or error decides. All must pass."""
    best: Verdict | None = None
    for det in detectors:
        try:
            s = float(det.score(path))
        except Exception as e:  # any failure is a verdict: quarantine
            return Verdict(True, det.name, None, error=type(e).__name__)
        if not (0.0 <= s <= 1.0):
            return Verdict(True, det.name, None, error="ScoreOutOfRange")
        if s >= det.threshold:
            return Verdict(True, det.name, s)
        if best is None or s > (best.score or 0.0):
            best = Verdict(False, det.name, s)
    if best is None:
        return Verdict(True, "none", None, error="NoDetectors")
    return best


# --- safe file handling ------------------------------------------------------

def _inside(root: Path, p: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


def check_candidate(root: Path, p: Path) -> str | None:
    """Return a reason string if the path must not be screened as a normal file.
    lstat only: a symlink is never followed (Viktor 9018 F3)."""
    st = os.lstat(p)
    if stat.S_ISLNK(st.st_mode):
        return "Symlink"
    if not stat.S_ISREG(st.st_mode):
        return "NotRegularFile"
    if not _inside(root, Path(os.path.realpath(p.parent))):
        return "OutsideRoot"
    return None


def _free_name(d: Path, name: str) -> Path:
    target = d / name
    n = 1
    while os.path.lexists(target):
        target = d / f"{name}.{n}"
        n += 1
    return target


def ensure_private_dir(d: Path) -> None:
    d.mkdir(mode=0o700, exist_ok=True)
    if os.lstat(d).st_mode & 0o777 != 0o700:
        os.chmod(d, 0o700)  # this one directory only, never recursive


def quarantine(root: Path, p: Path) -> Path:
    """Same-volume rename into <root>/_quarantine, then mode 000. No copy, no delete."""
    qdir = root / QUARANTINE
    ensure_private_dir(qdir)
    target = _free_name(qdir, p.name)
    os.rename(p, target)
    if os.path.islink(target):
        if hasattr(os, "lchmod"):
            os.lchmod(target, 0)
    else:
        os.chmod(target, 0)
    return target


def sidecar(p: Path) -> Path:
    return p.with_name(p.stem + ".metadata.json")


def move_sidecar(p: Path, dest_dir: Path) -> None:
    sc = sidecar(p)
    if os.path.lexists(sc) and not os.path.islink(sc):
        dest_dir.mkdir(parents=True, exist_ok=True)
        os.rename(sc, _free_name(dest_dir, sc.name))


# --- records -----------------------------------------------------------------

def prompt_and_seed(p: Path) -> tuple[str, str]:
    m = SEED_RX.match(p.stem)
    if m:
        return m.group("prompt"), m.group("seed")
    return p.stem, "-"


def _append_private(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def record_line(p: Path, v: Verdict) -> str:
    prompt, seed = prompt_and_seed(p)
    ts = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    score = f"{v.score:.3f}" if v.score is not None else f"error:{v.error}"
    return f"{ts}\tfile={p.name}\tprompt={prompt}\tseed={seed}\tdetector={v.detector}\tscore={score}"


def notify(text: str, send: Callable[[str, str], None]) -> None:
    for to in ("mira", "klodel"):
        try:
            send(to, text)
        except Exception:
            pass  # the log line is the record; a failed message must not stop the batch


def send_agent_msg(to: str, text: str) -> None:
    subprocess.run(["bash", str(AGENT_MSG), "kernel", to, text], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)


@dataclass
class Sinks:
    log_path: Path = LOG_PATH
    blocklist_path: Path = BLOCKLIST_PATH
    send: Callable[[str, str], None] = send_agent_msg


def on_quarantine(p: Path, v: Verdict, sinks: Sinks) -> None:
    line = record_line(p, v)
    _append_private(sinks.log_path, line + "\tverdict=quarantine\n")
    prompt, seed = prompt_and_seed(p)
    _append_private(sinks.blocklist_path, f"{prompt}\t{seed}\n")
    notify("[image-safety] KARANTÉN (a képet senki ne nyissa meg): " + line, sinks.send)


# --- passed ledger (sweep skips what already passed, by content hash) -------

def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def detector_ident(detectors: list[Detector]) -> str:
    return ",".join(f"{d.name}@{d.threshold}" for d in detectors)


def load_passed(root: Path) -> set[tuple[str, str]]:
    """(sha256, detector ident) pairs: a model or threshold change re-screens."""
    led = root / PASSED_LEDGER
    if not led.exists():
        return set()
    out = set()
    for raw in led.read_text(encoding="utf-8").splitlines():
        try:
            j = json.loads(raw)
            out.add((j["sha256"], j["detectors"]))
        except Exception:
            continue
    return out


def add_passed(root: Path, digest: str, ident: str) -> None:
    _append_private(root / PASSED_LEDGER, json.dumps({"sha256": digest, "detectors": ident}) + "\n")


# --- modes -------------------------------------------------------------------

def iter_images(d: Path) -> Iterable[Path]:
    skip = {x.lower() for x in SCREENING_DIRS}  # APFS is case-insensitive (review B2)
    if not d.is_dir() or d.is_symlink() or skip & {x.lower() for x in d.parts}:
        return
    for dirpath, dirnames, filenames in os.walk(d, followlinks=False):
        dirnames[:] = [x for x in dirnames if x.lower() not in skip]
        for fn in sorted(filenames):
            if Path(fn).suffix.lower() in IMAGE_EXT:
                yield Path(dirpath) / fn


def process(root: Path, p: Path, detectors: list[Detector], sinks: Sinks,
            dest: Path | None, passed: set[tuple[str, str]] | None) -> bool:
    """Screen one file. Returns True if it was quarantined."""
    ident = detector_ident(detectors)
    reason = check_candidate(root, p)
    digest = ""
    if reason:
        v = Verdict(True, "path-check", None, error=reason)
    else:
        digest = sha256_of(p)
        if passed is not None and (digest, ident) in passed:
            return False
        v = screen(p, detectors)
    if v.flagged:
        quarantine(root, p)
        # The sidecar holds the prompt text: kept as documentation (Lex 9016),
        # outside the quarantine so it stays readable, never next to passed images.
        move_sidecar(p, root / QUARANTINE_META)
        on_quarantine(p, v, sinks)
        return True
    add_passed(root, digest, ident)
    if passed is not None:
        passed.add((digest, ident))
    if dest is not None:
        dest.mkdir(parents=True, exist_ok=True)
        move_sidecar(p, dest)
        os.rename(p, _free_name(dest, p.name))
    return False


def run_inbox(root: Path, dest_rel: str, detectors: list[Detector], sinks: Sinks) -> int:
    dest = (root / dest_rel)
    if not _inside(root, Path(os.path.realpath(dest))) or {x.lower() for x in SCREENING_DIRS} & {x.lower() for x in Path(dest_rel).parts}:
        print("image-safety: --dest must be inside the root and not a screening dir", file=sys.stderr)
        return EXIT_USAGE
    inbox = root / UNSCREENED
    if not os.path.lexists(inbox):
        return EXIT_OK
    bad = unsafe_dir(root, inbox) or (os.path.lexists(dest) and unsafe_dir(root, dest))
    if bad:
        print(f"image-safety: {bad}; nothing moved", file=sys.stderr)
        return EXIT_USAGE
    return run_batch(root, list(_inbox_entries(inbox)), detectors, sinks, dest, None)


def unsafe_dir(root: Path, d: Path) -> str | None:
    """A working dir must be a real directory on the root's volume (review L3):
    os.rename cannot cross volumes, and a symlinked dir would move files elsewhere."""
    st = os.lstat(d)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        return f"{d.name} is not a real directory"
    if st.st_dev != os.lstat(root).st_dev:
        return f"{d.name} is on another volume"
    return None


def run_batch(root: Path, paths: list[Path], detectors: list[Detector], sinks: Sinks,
              dest: Path | None, passed: set[tuple[str, str]] | None) -> int:
    """One file's failure never stops the batch (review B1): it is logged by file
    name and makes the exit code non-zero, and the next file is screened."""
    q = errors = 0
    for p in paths:
        try:
            q += process(root, p, detectors, sinks, dest, passed)
        except Exception as e:
            errors += 1
            ts = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
            try:
                _append_private(sinks.log_path, f"{ts}\tfile={p.name}\tverdict=error:{type(e).__name__}\n")
            except Exception:
                pass
            print(f"image-safety: {p.name}: {type(e).__name__}", file=sys.stderr)
    if errors:
        return EXIT_FILE_ERRORS
    return EXIT_QUARANTINED if q else EXIT_OK


def _inbox_entries(inbox: Path) -> Iterable[Path]:
    # Every entry, not only image suffixes: an unexpected file in the inbox is
    # not passed on unscreened. Sidecars travel with their image.
    for fn in sorted(os.listdir(inbox)):
        p = inbox / fn
        if fn.endswith(".metadata.json") and not os.path.islink(p):
            continue
        yield p


def run_sweep(root: Path, dirs: list[str], detectors: list[Detector], sinks: Sinks) -> int:
    passed = load_passed(root)
    paths: list[Path] = []
    for rel in dirs:
        paths.extend(iter_images(root / rel))
    return run_batch(root, paths, detectors, sinks, None, passed)


# --- real detectors (loaded only in the CLI path) ---------------------------

def load_detectors(models_dir: Path) -> list[Detector]:
    from detectors import load_nudenet_cv, load_vit  # local module, lazy heavy imports
    return [load_nudenet_cv(models_dir / "nudenet"), load_vit(models_dir / "vit")]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", required=True, help="mflux root (Mira: agents/mira/tools/mflux)")
    ap.add_argument("--models", help="model dir (default <root>/models/image-safety)")
    sub = ap.add_subparsers(dest="mode", required=True)
    pi = sub.add_parser("inbox")
    pi.add_argument("--dest", required=True, help="where passing images go, relative to the root")
    ps = sub.add_parser("sweep")
    ps.add_argument("--dirs", nargs="+", default=["out", "final", "drafts"])
    a = ap.parse_args(argv)

    block_network()
    root = Path(os.path.realpath(a.root))
    models = Path(a.models) if a.models else root / "models" / "image-safety"
    sys.path.insert(0, str(HERE))
    try:
        detectors = load_detectors(models)
    except Exception as e:
        print(f"image-safety: detectors unavailable ({type(e).__name__}); nothing moved", file=sys.stderr)
        return EXIT_DETECTORS_UNAVAILABLE
    sinks = Sinks()
    if a.mode == "inbox":
        return run_inbox(root, a.dest, detectors, sinks)
    return run_sweep(root, a.dirs, detectors, sinks)


if __name__ == "__main__":
    sys.exit(main())
