"""Installed programs as Windows records them: the Uninstall keys.

This is what "Apps > Installed apps" reads, and it is the inventory used when
winget is not there or cannot match a program to a package. Three places,
because a 64-bit machine keeps per-machine 32-bit programs apart and per-user
installs in the user's own hive.

Entries Windows itself hides from that list are hidden here too: system
components, updates parented to another entry, and anything with no name.

Read on a worker thread. Off Windows it answers an empty list, so the tests
and the preview tool run anywhere.
"""

from __future__ import annotations

import sys

from app.core.inventory import Installed

KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
KEY_32 = r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"


def _value(handle, name: str) -> str:
    import winreg

    try:
        value, _kind = winreg.QueryValueEx(handle, name)
    except OSError:
        return ""
    return str(value).strip() if value is not None else ""


def _dword(handle, name: str) -> int:
    import winreg

    try:
        value, _kind = winreg.QueryValueEx(handle, name)
        return int(value)
    except (OSError, TypeError, ValueError):
        return 0


def entries() -> list[Installed]:
    if sys.platform != "win32":
        return []
    import winreg

    places = (
        (winreg.HKEY_LOCAL_MACHINE, KEY, "machine", "x64", winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, KEY, "machine", "x86", winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, KEY, "user", "", 0),
    )
    out: list[Installed] = []
    seen: set[tuple[str, str]] = set()
    for root, path, scope, arch, view in places:
        try:
            parent = winreg.OpenKey(root, path, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with parent:
            index = 0
            while True:
                try:
                    sub = winreg.EnumKey(parent, index)
                except OSError:
                    break
                index += 1
                try:
                    handle = winreg.OpenKey(parent, sub, 0, winreg.KEY_READ | view)
                except OSError:
                    continue
                with handle:
                    name = _value(handle, "DisplayName")
                    if not name or _dword(handle, "SystemComponent") == 1:
                        continue
                    if _value(handle, "ParentKeyName") or _value(handle, "ReleaseType") in (
                            "Update", "Hotfix", "Security Update"):
                        continue
                    entry = Installed(
                        name=name,
                        version=_value(handle, "DisplayVersion"),
                        publisher=_value(handle, "Publisher"),
                        install_date=_value(handle, "InstallDate"),
                        location=_value(handle, "InstallLocation"),
                        scope=scope,
                        arch=arch,
                        key=sub,
                        uninstall=_value(handle, "UninstallString"),
                    )
                # The 64- and 32-bit views are the same key on a 32-bit
                # machine; an entry is kept once.
                marker = (entry.name.lower(), entry.version)
                if marker in seen:
                    continue
                seen.add(marker)
                out.append(entry)
    return out
