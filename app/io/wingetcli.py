"""Running winget. What its output means is `core/winget.py`'s business.

winget is the App Installer package's command, an execution alias under
`%LOCALAPPDATA%\\Microsoft\\WindowsApps`. It is looked for there by name
rather than through PATH alone, because a process started from a shortcut
can have a PATH that predates the alias.

winget is run as the signed-in user, never elevated by this application. An
upgrade of a per-machine program asks Windows for elevation itself, which
puts the UAC prompt in front of the user for that one installer -- the right
place for it.
"""

from __future__ import annotations

import os
import shutil
import threading
from typing import Callable

from app.core import winget
from app.io import run as _run


def find() -> str | None:
    found = shutil.which("winget")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA")
    if local:
        alias = os.path.join(local, "Microsoft", "WindowsApps", "winget.exe")
        if os.path.exists(alias):
            return alias
    return None


#: Output in UTF-8 and never in colour, whatever the console says.
ENV = {"NO_COLOR": "1"}


def version(exe: str, *, timeout: float = 30.0) -> str:
    result = _run.run([exe, "--version"], timeout=timeout, env=ENV)
    return result.out.strip() if result.ok else ""


def list_installed(exe: str, *, timeout: float, cancel: threading.Event | None = None
                   ) -> _run.Result:
    return _run.run([exe, *winget.list_args()], timeout=timeout, cancel=cancel, env=ENV)


def list_upgrades(exe: str, *, timeout: float, include_unknown: bool = True,
                  cancel: threading.Event | None = None) -> _run.Result:
    return _run.run([exe, *winget.upgrade_list_args(include_unknown)], timeout=timeout,
                    cancel=cancel, env=ENV)


def upgrade(exe: str, package_id: str, *, timeout: float, silent: bool,
            unknown_version: bool, source: str = "", cancel: threading.Event | None = None,
            on_line: Callable[[str], None] | None = None) -> _run.Result:
    args = winget.upgrade_args(package_id, silent=silent, unknown_version=unknown_version,
                               source=source)
    return _run.run([exe, *args], timeout=timeout, cancel=cancel, on_line=on_line, env=ENV)
