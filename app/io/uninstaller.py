"""Running an uninstaller, then looking for what it left. See `core/uninstall.py`
for the rules; this is only the part that touches the machine."""

from __future__ import annotations

import datetime as _dt
import os
import sys
import threading
from dataclasses import dataclass
from typing import Callable

from app.core import uninstall as rules
from app.io import elevate, files, run as _run, wingetcli


@dataclass
class Ran:
    ok: bool
    note: str


def run(command: rules.Command, *, winget_exe: str, timeout: float,
        cancel: threading.Event | None = None,
        on_line: Callable[[str], None] | None = None) -> Ran:
    if command.winget_id:
        if not winget_exe:
            return Ran(False, "winget was not found.")
        result = wingetcli.uninstall(winget_exe, command.args, timeout=timeout, cancel=cancel,
                                     on_line=on_line)
        if result.cancelled:
            return Ran(False, "Cancelled.")
        if result.timed_out:
            return Ran(False, f"Stopped after {timeout / 60:.0f} minutes without finishing.")
        code = result.code & 0xFFFFFFFF
        if code == 0:
            return Ran(True, "Uninstalled.")
        tail = [line for line in result.out.splitlines() if line.strip()][-1:]
        return Ran(False, f"winget returned 0x{code:08X}. {tail[0].strip() if tail else ''}".strip())
    if not rules.runnable(command.executable):
        return Ran(False, "Refused: the recorded uninstall command has no full path "
                          f"({command.executable}). Use Settings > Apps for this one.")
    executable = command.executable
    if executable.lower() in rules.SYSTEM_TOOLS:
        name = executable.lower()
        executable = _run.system32(name if name.endswith(".exe") else name + ".exe")
    # The uninstaller's own window is shown: many ask questions, and an
    # invisible dialog waiting for an answer is a hang nobody can see.
    started = elevate.run(executable, command.parameters, timeout=timeout,
                          cancel=cancel, verb="open", show=True)
    if not started.started:
        return Ran(False, started.error or "The uninstaller could not be started.")
    if started.cancelled or started.timed_out:
        return Ran(False, started.error)
    # 0 is done; 3010 and 1641 are MSI's "done, restart needed".
    if started.code in (0, 3010, 1641):
        return Ran(True, "Uninstalled." + (" Restart to finish." if started.code != 0 else ""))
    if started.code == 1602:
        return Ran(False, "Cancelled in the uninstaller.")
    return Ran(False, f"The uninstaller exited with {started.code}.")


def roots() -> dict[str, str]:
    return {var: os.environ.get(var, "") for var in rules.ROOT_VARS}


def leftovers(*, name: str, publisher: str, location: str,
              others: list[str], cancel: threading.Event | None = None) -> rules.Leftovers:
    found = rules.Leftovers()
    for path, why in rules.candidates(name=name, publisher=publisher, location=location,
                                      roots=roots(), others=others):
        if not os.path.isdir(path) or files.is_link(path) or files.is_network(path):
            continue
        found.folders.append(rules.Leftover(path, "folder",
                                            files.folder_size(path, cancel=cancel), why))
    if sys.platform == "win32":
        import winreg

        for subkey in rules.registry_candidates(name=name, publisher=publisher):
            if not rules.safe_key(subkey, name=name):
                continue
            try:
                winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey))
            except OSError:
                continue
            found.keys.append(rules.Leftover("HKCU\\" + subkey, "key", 0,
                                             "Settings the program kept for you"))
    return found


def backups_folder() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "SoftwareUpdater", "backups")


def remove(chosen: list[rules.Leftover], *, name: str) -> tuple[list[str], dict[str, str]]:
    """Folders to the Recycle Bin; keys exported to a .reg backup, then
    deleted. Every path is checked against the rules again here, so nothing
    the window was handed can widen what is removed."""
    folders = [c.path for c in chosen if c.kind == "folder"
               and rules.safe_leftover(c.path, name=name, publisher="", roots=roots())]
    done, failed = files.recycle(folders)
    for item in chosen:
        if item.kind == "folder" and item.path not in folders:
            failed[item.path] = "Refused: not a folder this program owns."
    for item in chosen:
        if item.kind != "key":
            continue
        subkey = item.path.split("\\", 1)[1] if "\\" in item.path else ""
        if not item.path.upper().startswith("HKCU\\") or not rules.safe_key(subkey, name=name):
            failed[item.path] = "Refused: not a key this program owns."
            continue
        why = _delete_key(subkey)
        if why:
            failed[item.path] = why
        else:
            done.append(item.path)
    return done, failed


def _delete_key(subkey: str) -> str:
    if sys.platform != "win32":
        return "Only available on Windows."
    os.makedirs(backups_folder(), exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = "".join(ch if ch.isalnum() else "_" for ch in subkey)[-60:]
    backup = os.path.join(backups_folder(), f"{stamp}-{safe}.reg")
    exported = _run.run([_run.system32("reg.exe"), "export", "HKCU\\" + subkey, backup, "/y"], timeout=30)
    if not exported.ok:
        return "Not deleted: the backup could not be written."
    import ctypes
    import winreg
    from ctypes import wintypes

    advapi = ctypes.windll.advapi32
    advapi.RegDeleteTreeW.argtypes = [wintypes.HKEY, wintypes.LPCWSTR]
    advapi.RegDeleteTreeW.restype = wintypes.LONG
    # With a subkey named, RegDeleteTree removes that key and all beneath it.
    code = advapi.RegDeleteTreeW(winreg.HKEY_CURRENT_USER, subkey)
    if code != 0:
        return f"Not deleted (error {code})."
    return ""
