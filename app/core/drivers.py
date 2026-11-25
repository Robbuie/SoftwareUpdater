"""Installed drivers, and what Windows Update offers for them. Pure.

Two inputs, both JSON from PowerShell (`io/scripts.py`):

- **Installed drivers** from `Win32_PnPSignedDriver`: one entry per device,
  so a chipset driver appears twenty times, once for each bridge and bus it
  binds. They are grouped here by provider, INF and version into one row,
  because the thing a person updates is the driver package, not each device
  it happens to serve.
- **Offered updates** from the Windows Update Agent (`core/winupdate.py`
  parses those). A driver update names the hardware id it is for, which is
  how it is tied back to the installed row it replaces.

What Windows Update does not offer is not proof a driver is current. Most
vendors publish newer drivers on their own sites first, or only there. So a
driver from a third-party provider that is older than a configurable age is
marked "old" -- a prompt to look, with the manufacturer's tool or site, not a
claim that something newer exists.

Drivers whose provider is Microsoft are Windows' own inbox drivers. They are
updated with Windows itself, so they are left out unless asked for.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from typing import Any

#: Providers whose drivers ship with Windows and update with it.
INBOX_PROVIDERS = frozenset({"microsoft", "microsoft corporation", "microsoft windows"})


@dataclass
class Device:
    name: str
    device_class: str = ""
    manufacturer: str = ""
    provider: str = ""
    version: str = ""
    date: str = ""          # yyyy-mm-dd, or ""
    inf: str = ""
    device_id: str = ""
    hardware_id: str = ""


@dataclass
class DriverGroup:
    """One driver package and the devices it serves."""

    provider: str
    inf: str
    version: str
    date: str
    device_class: str
    devices: list[Device] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"driver:{self.provider.lower()}|{self.inf.lower()}|{self.version}"

    @property
    def name(self) -> str:
        first = self.devices[0].name if self.devices else self.inf
        more = len(self.devices) - 1
        return f"{first} (+{more} more)" if more > 0 else first

    @property
    def inbox(self) -> bool:
        return self.provider.strip().lower() in INBOX_PROVIDERS

    @property
    def manufacturer(self) -> str:
        for device in self.devices:
            if device.manufacturer:
                return device.manufacturer
        return ""

    def hardware_ids(self) -> set[str]:
        return {d.hardware_id.lower() for d in self.devices if d.hardware_id}

    def age_days(self, today: _dt.date) -> int | None:
        day = parse_date(self.date)
        return (today - day).days if day else None


def parse_date(value: str) -> _dt.date | None:
    if not value:
        return None
    text = value.strip()
    # PowerShell's own date form when ConvertTo-Json writes a DateTime.
    if text.startswith("/Date(") and text.endswith(")/"):
        try:
            ms = int(text[6:-2].split("+")[0].split("-")[0])
            return _dt.datetime.fromtimestamp(ms / 1000, _dt.timezone.utc).date()
        except ValueError:
            return None
    attempts = ((text[:10], "%Y-%m-%d"), (text[:8], "%Y%m%d"),
                (text.split(" ")[0], "%m/%d/%Y"))
    for piece, fmt in attempts:
        try:
            return _dt.datetime.strptime(piece, fmt).date()
        except ValueError:
            continue
    return None


def as_list(payload: Any) -> list[dict]:
    """PowerShell 5.1 writes one object as an object and many as an array,
    and nothing as nothing."""
    if payload is None:
        return []
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    return []


def load(text: str) -> Any:
    text = (text or "").strip().lstrip("﻿")
    if not text:
        return None
    return json.loads(text)


def _s(entry: dict, key: str) -> str:
    value = entry.get(key)
    if value is None:
        return ""
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value).strip()


def _iso(value: str) -> str:
    day = parse_date(value)
    return day.isoformat() if day else ""


def devices(payload: Any) -> list[Device]:
    out = []
    for entry in as_list(payload):
        name = _s(entry, "DeviceName")
        version = _s(entry, "DriverVersion")
        if not name or not version:
            continue
        out.append(Device(
            name=name,
            device_class=_s(entry, "DeviceClass"),
            manufacturer=_s(entry, "Manufacturer"),
            provider=_s(entry, "DriverProviderName"),
            version=version,
            date=_iso(_s(entry, "DriverDate")),
            inf=_s(entry, "InfName"),
            device_id=_s(entry, "DeviceID"),
            hardware_id=_s(entry, "HardWareID"),
        ))
    return out


def group(found: list[Device]) -> list[DriverGroup]:
    groups: dict[tuple[str, str, str], DriverGroup] = {}
    for device in found:
        key = (device.provider.lower(), device.inf.lower(), device.version)
        entry = groups.get(key)
        if entry is None:
            entry = DriverGroup(provider=device.provider, inf=device.inf,
                                version=device.version, date=device.date,
                                device_class=device.device_class)
            groups[key] = entry
        entry.devices.append(device)
    for entry in groups.values():
        entry.devices.sort(key=lambda d: d.name.lower())
    return sorted(groups.values(), key=lambda g: g.name.lower())


def is_old(entry: DriverGroup, today: _dt.date, years: float) -> bool:
    if entry.inbox or years <= 0:
        return False
    age = entry.age_days(today)
    return age is not None and age > years * 365.25
