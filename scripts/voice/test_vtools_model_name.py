#!/usr/bin/env python3
"""Behaviour test for 2e4806e1: the whisper model can be chosen by a file.

WHY A FILE: the STT hook runs inside the dashboard process and inherits its
launchd environment, so MARVEEN_WHISPER_MODEL cannot be changed there without
restarting the dashboard. A one-line ``whisper-model`` file next to
``_vtools.py`` (the installed copy) can be changed at any time; the next
transcription reads it.

These tests drive ``_whisper_model_name`` with a temp file and read the model
name that comes out: env wins, the file is used only for known sizes, and
anything else (missing, unknown, a path, a repo id, not UTF-8) falls back to
'small'. No model, no network.

Run: python3 scripts/voice/test_vtools_model_name.py
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("_vtools_under_test", os.path.join(HERE, "_vtools.py"))
vt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vt)

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print("ok   - %s" % name)
    else:
        print("FAIL - %s %s" % (name, detail))
        FAILS.append(name)


def resolve(content: bytes | None, env: str | None = None) -> tuple[str, str]:
    """Model name and stderr for a given file content (None = no file) and env."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "whisper-model")
        if content is not None:
            with open(path, "wb") as f:
                f.write(content)
        old = os.environ.pop("MARVEEN_WHISPER_MODEL", None)
        if env is not None:
            os.environ["MARVEEN_WHISPER_MODEL"] = env
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                return vt._whisper_model_name(path), err.getvalue()
        finally:
            os.environ.pop("MARVEEN_WHISPER_MODEL", None)
            if old is not None:
                os.environ["MARVEEN_WHISPER_MODEL"] = old


def run() -> None:
    check("[1] no file, no env: small", resolve(None)[0] == "small")
    check("[2] file 'medium': medium", resolve(b"medium\n")[0] == "medium")
    check("[3] surrounding whitespace is ignored", resolve(b"  medium  \n")[0] == "medium")
    check("[4] env wins over the file", resolve(b"medium\n", env="base")[0] == "base")
    check("[5] empty env falls through to the file", resolve(b"medium\n", env="  ")[0] == "medium")

    name, err = resolve(b"Systran/faster-whisper-large-v3\n")
    check("[6] a repo id in the file is refused", name == "small", name)
    check("[6] ... and said so on stderr", "ignoring" in err, repr(err))
    check("[7] a path in the file is refused", resolve(b"/tmp/evil-model\n")[0] == "small")
    check("[8] an empty file: small", resolve(b"")[0] == "small")
    check("[9] not UTF-8: small, no crash", resolve(b"\xff\xfe\x00m")[0] == "small")
    check("[10] only the first line counts", resolve(b"medium\nlarge-v3\n")[0] == "medium")

    # [11] The default location is the file next to the LOADED _vtools.py (the
    # installed copy), not the source tree: load a copy from a temp dir.
    # TemporaryDirectory, not mkdtemp + rmdir: importing the copy may leave a
    # __pycache__ next to it (Viktor 8182: exit 1 without -B).
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(HERE, "_vtools.py"), "rb") as src, open(os.path.join(d, "_vtools.py"), "wb") as dst:
            dst.write(src.read())
        with open(os.path.join(d, "whisper-model"), "w") as f:
            f.write("medium\n")
        s2 = importlib.util.spec_from_file_location("_vtools_copy", os.path.join(d, "_vtools.py"))
        vt2 = importlib.util.module_from_spec(s2)
        s2.loader.exec_module(vt2)
        old = os.environ.pop("MARVEEN_WHISPER_MODEL", None)
        try:
            got = vt2._whisper_model_name()
        finally:
            if old is not None:
                os.environ["MARVEEN_WHISPER_MODEL"] = old
        check("[11] default: the file next to the loaded script", got == "medium", got)

    # [12] The refusal line must not leak the file's content (it may be a symlink
    # to another file), and only the first 64 characters are read.
    name, err = resolve(b"SECRET-LOOKING-CONTENT-xyz\n")
    check("[12] the refused value is not echoed to stderr", "SECRET-LOOKING" not in err, repr(err))
    check("[13] a 10 MB single line: small (bounded read)", resolve(b"m" * 10_000_000)[0] == "small")

    if FAILS:
        print("FAILED: %s" % ", ".join(FAILS))
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    run()
