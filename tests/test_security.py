"""The security rules (core/security.py) and pip/npm parsing (core/devtools.py)."""

from __future__ import annotations

import copy
import datetime as _dt

from app.core import devtools, inventory, security
from tests import sample

TODAY = _dt.date(2026, 11, 25)


def by_id(findings):
    return {f.id: f for f in findings}


def test_fixture_machine():
    found = by_id(security.evaluate(sample.security(), today=TODAY))
    assert found["firewall"].level == security.BAD and "Public" in found["firewall"].summary
    assert found["antivirus"].level == security.WARN
    assert found["antivirus"].action == "defender-update"
    assert found["reboot"].level == security.WARN
    assert found["os"].level == security.GOOD and "2027-10-12" in found["os"].summary
    assert found["bitlocker"].level == security.GOOD
    assert found["rdp"].level == security.INFO


def test_worst_first():
    findings = security.evaluate(sample.security(), today=TODAY)
    order = [security.LEVEL_ORDER[f.level] for f in findings]
    assert order == sorted(order)


def test_os_support_by_edition_and_date():
    facts = {"os": {"build": 22631, "edition": "Professional", "caption": "Windows 11 Pro"}}
    assert security.os_support(facts, TODAY).level == security.BAD
    facts["os"]["edition"] = "Enterprise"
    assert security.os_support(facts, TODAY).level == security.BAD       # ended 2026-11-10
    assert security.os_support(facts, _dt.date(2026, 10, 1)).level == security.WARN
    facts = {"os": {"build": 26100, "edition": "Professional"}}
    assert security.os_support(facts, TODAY).level == security.BAD       # ended 2026-10-13
    facts = {"os": {"build": 19045, "edition": "Enterprise"}}
    assert security.os_support(facts, TODAY).level == security.BAD
    facts = {"os": {"build": 26300, "edition": "Professional"}}
    assert security.os_support(facts, TODAY).level == security.GOOD
    assert security.os_support({}, TODAY).level == security.UNKNOWN


def test_dangerous_settings():
    facts = copy.deepcopy(sample.security())
    facts.update({"wdigest": 1, "guest": True, "autologon": {"enabled": "1", "storedPassword": True},
                  "uac": {"enableLua": 0}, "smb1": {"server": 1}, "rdp": {"deny": 0, "nla": 0},
                  "updateService": "Disabled", "lastPatch": "2026-06-01"})
    found = by_id(security.evaluate(facts, today=TODAY))
    for key in ("wdigest", "guest", "autologon", "uac", "smb1", "rdp", "wuservice", "lastpatch"):
        assert found[key].level == security.BAD, key


def test_third_party_antivirus_counts():
    facts = {"defender": {"enabled": False, "realtime": False}, "antivirus": ["Sophos Endpoint"]}
    found = by_id(security.evaluate(facts, today=TODAY))
    assert found["antivirus"].level == security.GOOD


def test_missing_facts_are_unknown_not_good():
    found = by_id(security.evaluate({}, today=TODAY))
    for key in ("antivirus", "firewall", "bitlocker", "secureboot"):
        assert found[key].level == security.UNKNOWN, key


def test_inventory_feeds_browsers_and_security_updates():
    items = inventory.build(sample.sources(), today=TODAY)
    found = by_id(security.from_inventory(items))
    assert found["browsers"].level == security.BAD and "Edge" in found["browsers"].summary
    assert found["wu-security"].level == security.BAD


def test_never_reads_the_stored_password():
    from app.io import scripts

    assert "DefaultPassword" in scripts.SECURITY
    assert "-Name 'DefaultPassword'" not in scripts.SECURITY
    assert "Reg $w 'DefaultPassword'" not in scripts.SECURITY


def test_py_launcher_and_pip_and_npm():
    pythons = devtools.interpreters(sample.text("ps", "py-launcher.txt"),
                                    r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\python.exe")
    assert [p.tag for p in pythons] == ["3.12", "3.11"]          # Store stub left out
    assert devtools.label(pythons[0]) == "Python 3.12"
    pip = devtools.pip_outdated("A new release of pip is available\n"
                                + sample.text("ps", "pip-outdated.json"), pythons[0])
    assert [p.name for p in pip] == ["requests", "pip"]
    npm = devtools.npm_outdated(sample.text("ps", "npm-outdated.json"), "npm.cmd")
    assert [(p.name, p.latest) for p in npm] == [("npm", "11.6.2"), ("typescript", "5.9.3")]
    assert devtools.npm_outdated("", "npm.cmd") == []
    assert devtools.upgrade_command(npm[1])[-1] == "typescript@latest"
    assert devtools.upgrade_command(pip[0])[1:5] == ["-m", "pip", "install", "--upgrade"]


def test_dev_rows_are_opt_in():
    items = inventory.build(sample.sources(), today=TODAY)
    dev = [i for i in items if i.kind == inventory.Kind.DEV]
    assert len(dev) == 4 and all(i.opt_in and i.updatable for i in dev)
