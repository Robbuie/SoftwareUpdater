"""Installing chosen Windows Update offers, as administrator.

The window cannot hand an elevated process anything in memory, and cannot
read its standard output. So the exchange is two small files: a request
naming the update ids, written here, and a result the elevated script writes
back. They live under `%ProgramData%\\SoftwareUpdater\\jobs` rather than the
user's own profile, because the person who answers the UAC prompt may be a
different account -- an administrator typing their password over the user's
shoulder -- and that account can read and write ProgramData but not
necessarily this user's AppData. Both files are removed afterwards.
"""

from __future__ import annotations

import json
import os
import threading
import uuid

from app.core import winupdate
from app.io import elevate, powershell, scripts


def jobs_folder() -> str:
    base = os.environ.get("ProgramData") or r"C:\ProgramData"
    return os.path.join(base, "SoftwareUpdater", "jobs")


def install(ids: list[str], *, server: str, timeout: float,
            cancel: threading.Event | None = None) -> winupdate.InstallResult:
    folder = jobs_folder()
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        return winupdate.InstallResult([], error=f"Could not prepare {folder}: {exc}")
    name = uuid.uuid4().hex
    request = os.path.join(folder, f"{name}.request.json")
    result = os.path.join(folder, f"{name}.result.json")
    body = os.path.join(folder, f"{name}.ps1")
    try:
        with open(request, "w", encoding="utf-8") as handle:
            json.dump({"ids": list(ids), "server": server}, handle)
        # The script itself goes in a file and a two-line command runs it:
        # ShellExecute's parameter string is not the place for six kilobytes
        # of base64, and reading the file with Get-Content keeps execution
        # policy out of it, as -EncodedCommand does for the other scripts.
        with open(body, "w", encoding="utf-8-sig") as handle:
            handle.write(scripts.fill(scripts.WU_INSTALL, request=request, result=result))
        boot = scripts.fill(scripts.RUN_FILE, path=body)
        parameters = " ".join([*powershell.ARGS, "-EncodedCommand", powershell.encode(boot)])
        ran = elevate.run(powershell.executable(), parameters, timeout=timeout, cancel=cancel)
        if not ran.started or ran.declined or ran.cancelled or ran.timed_out:
            return winupdate.InstallResult([], error=ran.error or "Not started.")
        try:
            with open(result, "r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            return winupdate.InstallResult(
                [], error=f"The installer finished (exit {ran.code}) without writing a result.")
        return winupdate.install_result(payload)
    finally:
        for path in (request, result, body):
            try:
                os.remove(path)
            except OSError:
                pass
