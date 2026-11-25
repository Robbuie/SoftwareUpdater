"""Installing chosen Windows Update offers, as administrator.

One elevated run (`io/elevated.py`) for every chosen offer, so one UAC
prompt. The ids are written into the script itself, which `elevated.run`
hashes before the administrator's PowerShell will run it -- see that module
for why a separate request file was not safe.
"""

from __future__ import annotations

import threading

from app.core import winupdate
from app.io import elevated, scripts


def install(ids: list[str], *, server: str, timeout: float,
            cancel: threading.Event | None = None) -> winupdate.InstallResult:
    script = scripts.embed(scripts.WU_INSTALL, request={"ids": list(ids), "server": server})
    outcome = elevated.run(script, timeout=timeout, cancel=cancel)
    if not outcome.ok:
        return winupdate.InstallResult([], error=outcome.error)
    return winupdate.install_result(outcome.data)
