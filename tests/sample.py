"""The fixture machine: what `tests/data/` says a scan found, as a `Scan`.

Used by the tests and by `tools/preview.py`, so the preview shows the same
rows the tests reason about. The fixtures are shaped like real output --
winget's padded tables with a spinner in front, PowerShell's JSON -- and a
real capture that parses wrongly belongs here beside them.
"""

from __future__ import annotations

import json
import os

from app.core import devtools, drivers, winget, winupdate
from app.core.inventory import Installed, Sources
from app.core.scan import Scan

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def text(*parts: str) -> str:
    with open(os.path.join(DATA, *parts), "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def payload(*parts: str):
    return json.loads(text(*parts))


def installed() -> list[Installed]:
    return [Installed(**entry) for entry in payload("registry.json")]


def sources() -> Sources:
    return Sources(
        installed=installed(),
        winget_list=winget.rows(text("winget", "list.txt")),
        winget_upgrades=winget.rows(text("winget", "upgrade.txt")),
        drivers=drivers.group(drivers.devices(payload("ps", "drivers.json")["drivers"])),
        offers=winupdate.offers(payload("ps", "windows-update.json")["updates"]),
        dev=dev(),
    )


def dev() -> list:
    pythons = devtools.interpreters(text("ps", "py-launcher.txt"))
    packages = devtools.pip_outdated(text("ps", "pip-outdated.json"), pythons[0])
    return packages + devtools.npm_outdated(text("ps", "npm-outdated.json"),
                                            r"C:\Program Files\nodejs\npm.cmd")


def security() -> dict:
    return payload("ps", "security.json")


def scan() -> Scan:
    result = Scan(sources=sources(), system=payload("ps", "system.json"),
                  winget_path=r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\winget.exe")
    result.finished_at = 1795000000.0
    return result
