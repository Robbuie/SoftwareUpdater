"""Merging the sources into rows (core/inventory.py), the update plan
(core/plan.py), drivers and Windows Update parsing, and the report."""

from __future__ import annotations

import datetime as _dt

from app.core import drivers, inventory, plan, report, winupdate
from app.core.inventory import Action, Kind, Status
from tests import sample

TODAY = _dt.date(2026, 11, 25)


def build(**kwargs):
    source = kwargs.pop("sources", None) or sample.sources()
    return {i.key: i for i in inventory.build(source, today=TODAY, vendor_url="https://x", **kwargs)}


def by_name(items, name):
    return next(i for i in items.values() if i.name == name)


def test_registry_entry_takes_winget_upgrade():
    items = build()
    git = items["winget:Git.Git"]
    assert git.status == Status.UPDATE and git.action == Action.WINGET
    assert (git.installed, git.available) == ("2.43.0", "2.47.1")
    assert git.publisher == "The Git Development Community"


def test_truncated_winget_name_matches_registry_by_prefix():
    items = build()
    vc = items["winget:Microsoft.VCRedist.2015+.x64"]
    assert vc.name.startswith("Microsoft Visual C++ 2015-2022 Redistributable (x64)")
    assert vc.status == Status.UPDATE


def test_two_pythons_each_get_their_own_row():
    items = build()
    py312 = items["winget:Python.Python.3.12"]
    assert py312.installed == "3.12.4" and py312.status == Status.CURRENT
    py311 = by_name(items, "Python 3.11.9 (64-bit)")
    assert py311.status == Status.UNTRACKED


def test_program_winget_cannot_match_is_untracked():
    items = build()
    logix = by_name(items, "Rockwell Automation Studio 5000 Logix Designer x86")
    assert logix.status == Status.UNTRACKED and logix.action == Action.NONE


def test_store_app_only_winget_lists_is_kept():
    items = build()
    photos = by_name(items, "Microsoft Photos")
    assert photos.status == Status.UNTRACKED


def test_explicit_upgrade_is_marked():
    items = build()
    zoom = items["winget:Zoom.Zoom"]
    assert zoom.status == Status.UPDATE and zoom.explicit


def test_unknown_installed_version_still_updates():
    items = build()
    seven = items["winget:7zip.7zip"]
    assert seven.status == Status.UPDATE
    steps = plan.build([seven]).winget
    assert steps[0].unknown_version


def test_without_winget_everything_is_unknown_not_current():
    source = sample.sources()
    source.winget_list = None
    source.winget_upgrades = None
    apps = [i for i in build(sources=source).values() if i.kind == Kind.APP]
    assert apps and all(i.status == Status.UNKNOWN for i in apps)


def test_driver_offer_attaches_to_installed_driver_by_hardware_id():
    items = build()
    wifi = by_name(items, "Intel(R) Wi-Fi 6E AX211 160MHz")
    assert wifi.status == Status.UPDATE and wifi.action == Action.WU
    assert wifi.wu_ids == ("0b1c2d3e-0000-4000-8000-000000000001",)
    assert wifi.available == "2024-06-14"


def test_unmatched_driver_offer_is_its_own_row():
    items = build()
    firmware = items["wu:0b1c2d3e-0000-4000-8000-000000000002"]
    assert firmware.kind == Kind.DRIVER and firmware.status == Status.UPDATE


def test_devices_of_one_package_are_one_row():
    items = build()
    serial = [i for i in items.values() if i.name.startswith("Intel(R) Serial IO")]
    assert len(serial) == 1 and serial[0].name.endswith("(+1 more)")


def test_old_third_party_driver_is_old_and_recent_one_is_current():
    items = build()
    assert by_name(items, "Realtek Audio").status == Status.OLD
    assert by_name(items, "NVIDIA RTX A1000 Laptop GPU").status == Status.CURRENT
    assert by_name(items, "Realtek Audio").action == Action.VENDOR


def test_old_years_zero_turns_old_off():
    items = build(old_years=0)
    assert by_name(items, "Realtek Audio").status == Status.CURRENT


def test_inbox_drivers_hidden_unless_asked():
    assert not any(i.name == "HID-compliant mouse" for i in build().values())
    shown = build(include_inbox=True)
    assert by_name(shown, "HID-compliant mouse").status == Status.CURRENT


def test_windows_updates():
    items = build()
    cu = items["wu:0b1c2d3e-0000-4000-8000-000000000003"]
    assert cu.kind == Kind.WINDOWS and cu.available == "KB5046633"


def test_drivers_without_windows_update_are_unknown():
    source = sample.sources()
    source.offers = None
    items = build(sources=source)
    assert by_name(items, "NVIDIA RTX A1000 Laptop GPU").status == Status.UNKNOWN


def test_visible_and_counts():
    items = list(build().values())
    ignored = {"winget:Git.Git"}
    counts = inventory.counts(items, ignored)
    assert counts["ignored"] == 1
    assert counts["updates"] == sum(1 for i in items if i.key not in ignored and i.status in (
        Status.UPDATE, Status.OLD))
    assert inventory.matches(items[0], "") and not inventory.matches(items[0], "zzzz")


def test_plan_separates_winget_windows_update_and_manual():
    items = build()
    chosen = [items["winget:Git.Git"], by_name(items, "Intel(R) Wi-Fi 6E AX211 160MHz"),
              items["wu:0b1c2d3e-0000-4000-8000-000000000003"], by_name(items, "Realtek Audio")]
    result = plan.build(chosen)
    assert [s.winget_id for s in result.winget] == ["Git.Git"]
    assert len(result.wu) == 2 and len(result.wu_ids) == 2
    assert [i.name for i in result.manual] == ["Realtek Audio"]
    assert any("administrator prompt" in line for line in result.describe())


def test_powershell_one_object_is_a_list_of_one():
    assert len(drivers.devices(sample.payload("ps", "drivers.json")["drivers"][0])) == 1
    assert drivers.devices(None) == []


def test_install_result():
    result = winupdate.install_result({"results": {"id": "a", "title": "T", "code": 4,
                                                   "hresult": 0x80070005}, "reboot": True})
    assert result.reboot and not result.outcomes[0].ok
    assert "administrator" in result.outcomes[0].text
    assert winupdate.install_result(None).error


def test_reports():
    items = list(build().values())
    csv_text = report.to_csv(items)
    assert csv_text.splitlines()[0].startswith("Name,Kind,Installed")
    page = report.to_html(items, machine="Dell Inc. Precision 5680", errors={"winget": "x<y"})
    assert "<table>" in page and "x&lt;y" in page and "Precision 5680" in page
