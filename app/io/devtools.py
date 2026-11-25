"""Asking pip and npm what is outdated. `core/devtools.py` reads the answers."""

from __future__ import annotations

import shutil
import threading
import time

from app.core import devtools
from app.core.scan import Answer
from app.io import run as _run


def pythons(cancel: threading.Event | None = None) -> list[devtools.Interpreter]:
    listed = ""
    launcher = shutil.which("py")
    if launcher:
        result = _run.run([launcher, "-0p"], timeout=20, cancel=cancel)
        listed = result.out if result.ok else ""
    return devtools.interpreters(listed, shutil.which("python") or "")


def npm_command() -> str:
    # npm on Windows is npm.cmd; CreateProcess runs a .cmd only by its full name.
    return shutil.which("npm.cmd") or shutil.which("npm") or ""


def outdated(*, timeout: float, cancel: threading.Event | None = None) -> Answer:
    started = time.monotonic()
    found: list[devtools.Package] = []
    problems: list[str] = []
    tools = 0
    for interpreter in pythons(cancel):
        tools += 1
        result = _run.run([interpreter.path, *devtools.list_args()], timeout=timeout,
                          cancel=cancel)
        if result.ok or result.out.strip().startswith("["):
            found.extend(devtools.pip_outdated(result.out, interpreter))
        elif "No module named pip" not in result.err:
            problems.append(f"{devtools.label(interpreter)}: "
                            f"{(result.err.strip().splitlines() or ['no answer'])[-1]}")
    npm = npm_command()
    if npm:
        tools += 1
        # Exit code 1 means "something is outdated"; the JSON is the answer.
        result = _run.run([npm, "outdated", "-g", "--json"], timeout=timeout, cancel=cancel)
        if result.out.strip():
            found.extend(devtools.npm_outdated(result.out, npm))
        elif result.code not in (0, 1):
            problems.append(f"npm: {(result.err.strip().splitlines() or ['no answer'])[-1]}")
    seconds = time.monotonic() - started
    if not tools:
        return Answer(True, [], "", seconds)
    return Answer(True, found, "; ".join(problems), seconds)
