"""The scan's orchestration (core/scan.py) against a fake machine, and the
PowerShell quoting the real probe relies on."""

from __future__ import annotations

import json
import threading

from app.core import oem
from app.core.scan import Answer, Options, Stage, run
from app.io import powershell, scripts
from tests import sample


class Fake:
    def __init__(self, *, winget: bool = True, wu_error: str = "") -> None:
        self._winget = winget
        self._wu_error = wu_error

    def system(self, timeout, cancel):
        return Answer(True, sample.payload("ps", "system.json"))

    def installed(self):
        return sample.installed()

    def winget(self):
        return "winget.exe" if self._winget else None

    def winget_list(self, exe, timeout, cancel):
        return Answer(True, sample.text("winget", "list.txt"))

    def winget_upgrades(self, exe, timeout, include_unknown, cancel):
        return Answer(True, sample.text("winget", "upgrade.txt"))

    def drivers(self, timeout, cancel):
        return Answer(True, sample.payload("ps", "drivers.json"))

    def windows_update(self, server, timeout, cancel):
        if self._wu_error:
            return Answer(False, error=self._wu_error)
        return Answer(True, sample.payload("ps", "windows-update.json"))


def test_every_stage_reports_once():
    seen = []
    lock = threading.Lock()

    def report(stage, scan):
        with lock:
            seen.append(stage)

    scan = run(Fake(), Options(), report=report)
    assert sorted(seen) == sorted([Stage.SYSTEM, Stage.REGISTRY, Stage.WINGET, Stage.DRIVERS,
                                   Stage.WINDOWS_UPDATE])
    assert scan.sources.winget_upgrades and scan.sources.drivers and scan.sources.offers
    assert scan.system["manufacturer"] == "Dell Inc."
    assert not scan.errors


def test_a_failing_source_is_an_error_not_an_empty_list():
    scan = run(Fake(winget=False, wu_error="Policy blocks it."), Options())
    assert "App Installer" in scan.errors[Stage.WINGET]
    assert scan.errors[Stage.WINDOWS_UPDATE] == "Policy blocks it."
    assert scan.sources.winget_list is None and scan.sources.offers is None
    assert scan.sources.installed


def test_sources_can_be_turned_off():
    scan = run(Fake(), Options(winget=False, windows_update=False))
    assert Stage.WINGET not in scan.seconds and Stage.WINDOWS_UPDATE not in scan.seconds


def test_quote_and_fill():
    assert scripts.quote("C:\\it's") == "'C:\\it''s'"
    filled = scripts.fill(scripts.WU_SEARCH, server="windows-update")
    assert "__SERVER__" not in filled and "'windows-update' -eq 'windows-update'" in filled
    filled = scripts.fill(scripts.WU_INSTALL, request="a.json", result="b.json")
    assert "__REQUEST__" not in filled and "__RESULT__" not in filled


def test_encoded_command_round_trips():
    import base64

    encoded = powershell.encode("Write-Output 'é'")
    assert base64.b64decode(encoded).decode("utf-16-le") == "Write-Output 'é'"
    # Scripts that go on a command line stay well under its 32 767 characters.
    for script in (scripts.DRIVERS, scripts.SYSTEM, scripts.WU_SEARCH):
        assert len(powershell.encode(script)) < 16000


def test_scripts_write_an_object_at_the_top():
    for script in (scripts.DRIVERS, scripts.WU_SEARCH):
        assert "[pscustomobject]@{ error" in script


def test_oem_tools():
    assert oem.vendor("Dell Inc.") == "dell"
    assert oem.vendor("HP") == "hp" and oem.vendor("Hewlett-Packard") == "hp"
    assert oem.vendor("LENOVO") == "lenovo" and oem.vendor("ASUSTeK") == ""
    names = [t.name for t in oem.relevant("Dell Inc.", {"Intel"})]
    assert names[0].startswith("Dell") and any(n.startswith("Intel") for n in names)
    assert oem.support_url("Microsoft Corporation") == ""


def test_fixture_json_is_what_the_scripts_promise():
    data = sample.payload("ps", "windows-update.json")
    assert json.dumps(data) and set(data) == {"updates"}
