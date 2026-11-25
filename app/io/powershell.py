"""Running one of `io/scripts.py` and reading the JSON it writes."""

from __future__ import annotations

import base64
import json
import os
import threading
from dataclasses import dataclass
from typing import Any

from app.io import run as _run

ARGS = ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden"]


def executable() -> str:
    """Windows PowerShell by its full path, so a `powershell.exe` earlier on
    PATH -- a stray copy, a shim -- is never the one run."""
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    path = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return path if os.path.exists(path) else "powershell.exe"


def encode(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def command(script: str) -> list[str]:
    return [executable(), *ARGS, "-EncodedCommand", encode(script)]


@dataclass
class Answer:
    ok: bool
    data: Any = None
    error: str = ""
    hresult: int = 0
    seconds: float = 0.0


def call(script: str, *, timeout: float, cancel: threading.Event | None = None) -> Answer:
    result = _run.run(command(script), timeout=timeout, cancel=cancel)
    if result.missing:
        return Answer(False, error="PowerShell could not be started: " + result.err)
    if result.cancelled:
        return Answer(False, error="Cancelled.", seconds=result.seconds)
    if result.timed_out:
        return Answer(False, error=f"No answer after {timeout:.0f} seconds.",
                      seconds=result.seconds)
    text = result.out.strip()
    try:
        data = json.loads(text) if text else None
    except ValueError:
        tail = (result.err or text).strip().splitlines()[-3:]
        return Answer(False, error="Unreadable answer: " + " ".join(tail),
                      seconds=result.seconds)
    if isinstance(data, dict) and data.get("error"):
        return Answer(False, data=data, error=str(data["error"]),
                      hresult=int(data.get("hresult") or 0), seconds=result.seconds)
    return Answer(True, data=data, seconds=result.seconds)
