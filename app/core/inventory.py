"""One list of everything installed, each with a verdict and a way forward.

The scan gathers four answers from four programs (`core/scan.py`); this is
where they become rows. Pure -- every input is plain data -- so the merging
rules, which are the part most likely to be wrong in an interesting way, are
proved by `tests/test_inventory.py` rather than by squinting at a window.

**Applications.** The registry's Uninstall entries are what is installed.
winget's `list` says which of those it can match to a package (and adds
Store and MSIX apps the registry does not list); its `upgrade` says which
of those have something newer. A registry entry is tied to winget's row by
name -- exactly, or by prefix when winget cut the name with an ellipsis --
preferring a row whose version also agrees, because two entries for one
product ("Python 3.11", "Python 3.12") are common.

**Drivers.** Grouped by package (`core/drivers.py`). A Windows Update driver
offer is tied to the installed package that serves the hardware id it names.
An offer that matches nothing installed is still listed: Windows thinks it
applies, and that is worth seeing.

**Windows.** Everything else Windows Update offers.

**Verdicts** (`Status`): update available, up to date, old (a third-party
driver past the configured age with nothing offered), not tracked (nothing
here knows the latest version), and unknown (the source that would know did
not answer this time). A row also carries how it would be updated (`Action`),
which is what the window's Update button acts on.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field

from app.core import versions
from app.core.drivers import DriverGroup, is_old
from app.core.winget import ELLIPSIS, Row
from app.core.winupdate import Offer


class Kind:
    APP = "app"
    DRIVER = "driver"
    WINDOWS = "windows"


KIND_LABELS = {Kind.APP: "Application", Kind.DRIVER: "Driver", Kind.WINDOWS: "Windows"}


class Status:
    UPDATE = "update"
    CURRENT = "current"
    OLD = "old"
    UNTRACKED = "untracked"
    UNKNOWN = "unknown"
    DONE = "done"          # updated during this session
    FAILED = "failed"      # an update was tried this session and did not go in


STATUS_LABELS = {
    Status.UPDATE: "Update available",
    Status.CURRENT: "Up to date",
    Status.OLD: "Old: check manufacturer",
    Status.UNTRACKED: "Not tracked",
    Status.UNKNOWN: "Unknown",
    Status.DONE: "Updated",
    Status.FAILED: "Update failed",
}

#: Sort order of the Status column: what needs doing first.
STATUS_ORDER = {Status.FAILED: 0, Status.UPDATE: 1, Status.OLD: 2, Status.DONE: 3,
                Status.UNKNOWN: 4, Status.UNTRACKED: 5, Status.CURRENT: 6}


class Action:
    NONE = ""
    WINGET = "winget"
    WU = "wu"
    VENDOR = "vendor"      # the manufacturer's tool or site


@dataclass
class Installed:
    """One Uninstall entry from the registry (`io/registry.py`)."""

    name: str
    version: str = ""
    publisher: str = ""
    install_date: str = ""
    location: str = ""
    scope: str = ""
    arch: str = ""
    key: str = ""
    uninstall: str = ""


@dataclass
class Item:
    key: str
    kind: str
    name: str
    installed: str = ""
    available: str = ""
    status: str = Status.UNKNOWN
    source: str = ""
    publisher: str = ""
    action: str = Action.NONE
    winget_id: str = ""
    winget_source: str = ""
    #: winget's second table: an upgrade `winget upgrade --all` leaves out.
    explicit: bool = False
    #: Windows Update ids this row's update installs.
    wu_ids: tuple[str, ...] = ()
    #: Lines for the details panel, (label, value).
    facts: list[tuple[str, str]] = field(default_factory=list)
    #: The outcome of an update tried this session.
    note: str = ""

    @property
    def updatable(self) -> bool:
        return self.status in (Status.UPDATE, Status.FAILED) and self.action in (
            Action.WINGET, Action.WU)


def normalise(name: str) -> str:
    text = name.lower().replace(ELLIPSIS, "")
    text = re.sub(r"\(.*?\)", " ", text) if text.count("(") == text.count(")") else text
    return re.sub(r"[^a-z0-9]+", "", text)


def _match(entry: Installed, rows: list[Row], used: set[int]) -> int | None:
    """The winget row that is this registry entry, or None."""
    want = normalise(entry.name)
    if not want:
        return None
    best: int | None = None
    best_score = 0
    for index, row in enumerate(rows):
        if index in used:
            continue
        have = normalise(row.name)
        if not have:
            continue
        if have == want:
            score = 3
        elif row.name.endswith(ELLIPSIS) and want.startswith(have) and len(have) >= 6:
            score = 2
        else:
            continue
        if row.version and entry.version and (
                row.version == entry.version or versions.compare(row.version, entry.version) == 0):
            score += 2
        if score > best_score:
            best, best_score = index, score
    return best


@dataclass
class Sources:
    """Everything one scan found. A source that did not answer is None, which
    is different from an empty list: "winget is not here" is not "nothing is
    tracked"."""

    installed: list[Installed] | None = None
    winget_list: list[Row] | None = None
    winget_upgrades: list[Row] | None = None
    drivers: list[DriverGroup] | None = None
    offers: list[Offer] | None = None


def build(sources: Sources, *, today: _dt.date, old_years: float = 3.0,
          include_inbox: bool = False, vendor_url: str = "") -> list[Item]:
    items: list[Item] = []
    items.extend(_apps(sources))
    items.extend(_drivers(sources, today=today, old_years=old_years,
                          include_inbox=include_inbox, vendor_url=vendor_url))
    items.extend(_windows(sources))
    return items


def _apps(sources: Sources) -> list[Item]:
    upgrades: dict[str, Row] = {}
    for row in sources.winget_upgrades or []:
        upgrades.setdefault(row.id.lower(), row)
    listed = list(sources.winget_list or [])
    used: set[int] = set()
    out: list[Item] = []
    winget_answered = sources.winget_list is not None

    for entry in sources.installed or []:
        index = _match(entry, listed, used) if winget_answered else None
        row = listed[index] if index is not None else None
        if index is not None:
            used.add(index)
        out.append(_app_item(entry, row, upgrades, winget_answered,
                             sources.winget_upgrades is not None))

    # What winget lists that the registry does not: Store and MSIX apps, and
    # per-user installs under another hive.
    for index, row in enumerate(listed):
        if index in used:
            continue
        out.append(_app_item(None, row, upgrades, True, sources.winget_upgrades is not None))

    # An upgrade winget offers for something neither list produced -- it
    # happens when `list` cut a name we could not match. Never drop an offer.
    shown = {item.winget_id.lower() for item in out if item.winget_id}
    for key, row in upgrades.items():
        if key not in shown:
            out.append(_app_item(None, row, upgrades, True, True))
    return out


def _app_item(entry: Installed | None, row: Row | None, upgrades: dict[str, Row],
              winget_answered: bool, upgrades_answered: bool) -> Item:
    name = entry.name if entry else (row.name if row else "")
    installed = (entry.version if entry and entry.version else (row.version if row else ""))
    tracked = row is not None and row.tracked
    upgrade = upgrades.get(row.id.lower()) if row is not None else None
    if row is not None and upgrade is None and row.available and tracked:
        # `list` shows an Available column too; `upgrade` is preferred because
        # it honours pins, but if only `list` answered, use what it says.
        upgrade = row if not upgrades_answered else None

    item = Item(
        key=f"winget:{row.id}" if tracked else f"arp:{normalise(name)}",
        kind=Kind.APP,
        name=name,
        installed=installed,
        publisher=entry.publisher if entry else "",
        winget_id=row.id if tracked else "",
        winget_source=row.source if row is not None else "",
    )
    if upgrade is not None:
        item.status = Status.UPDATE
        item.available = upgrade.available
        item.action = Action.WINGET
        item.explicit = upgrade.explicit
        item.source = upgrade.source or "winget"
    elif tracked:
        item.status = Status.CURRENT if upgrades_answered else Status.UNKNOWN
        item.source = row.source
    elif winget_answered:
        item.status = Status.UNTRACKED
        item.source = "Registry"
    else:
        item.status = Status.UNKNOWN
        item.source = "Registry"

    facts = [("Installed version", installed or "not recorded")]
    if item.available:
        facts.append(("Available", item.available))
    if entry is not None:
        if entry.publisher:
            facts.append(("Publisher", entry.publisher))
        if entry.install_date:
            facts.append(("Installed on", _yyyymmdd(entry.install_date)))
        if entry.scope:
            facts.append(("Installed for", "everyone" if entry.scope == "machine"
                          else "this user"))
        if entry.location:
            facts.append(("Location", entry.location))
    if row is not None:
        facts.append(("winget id", row.id))
        if row.source:
            facts.append(("winget source", row.source))
    if item.explicit:
        facts.append(("Note", "winget only upgrades this when asked by name "
                              "(it is pinned, or its installer type changes)."))
    if item.status == Status.UNTRACKED:
        facts.append(("Note", "winget has no package for this program, so the latest "
                              "version is not known here. Its own updater or the "
                              "publisher's site is the way to check."))
    item.facts = facts
    return item


def _yyyymmdd(value: str) -> str:
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def _drivers(sources: Sources, *, today: _dt.date, old_years: float, include_inbox: bool,
             vendor_url: str) -> list[Item]:
    if sources.drivers is None and not sources.offers:
        return []
    driver_offers = [o for o in (sources.offers or []) if o.is_driver]
    by_hwid: dict[str, list[Offer]] = {}
    for offer in driver_offers:
        if offer.hardware_id:
            by_hwid.setdefault(offer.hardware_id.lower(), []).append(offer)
    claimed: set[str] = set()
    out: list[Item] = []

    for group in sources.drivers or []:
        matched: list[Offer] = []
        for hwid in group.hardware_ids():
            matched.extend(o for o in by_hwid.get(hwid, []) if o.id not in claimed)
        if not matched:
            names = {d.name.lower() for d in group.devices}
            matched = [o for o in driver_offers
                       if o.id not in claimed and o.driver_model.lower() in names]
        if group.inbox and not matched and not include_inbox:
            continue
        item = Item(key=group.key, kind=Kind.DRIVER, name=group.name,
                    installed=group.version, publisher=group.provider,
                    source="Windows Update" if matched else "Device")
        if matched:
            for offer in matched:
                claimed.add(offer.id)
            item.status = Status.UPDATE
            item.action = Action.WU
            item.wu_ids = tuple(o.id for o in matched)
            item.available = matched[0].driver_date or matched[0].title
        elif is_old(group, today, old_years):
            item.status = Status.OLD
            item.action = Action.VENDOR if vendor_url else Action.NONE
        elif sources.offers is None:
            item.status = Status.UNKNOWN
        else:
            item.status = Status.CURRENT
        facts = [("Driver version", group.version), ("Driver date", group.date or "not recorded"),
                 ("Provider", group.provider or "not recorded"),
                 ("Class", group.device_class or "not recorded"), ("INF", group.inf)]
        if group.manufacturer and group.manufacturer != group.provider:
            facts.append(("Device maker", group.manufacturer))
        for offer in matched:
            facts.append(("Offered", offer.title))
        facts.append(("Devices", "\n".join(d.name for d in group.devices)))
        if item.status == Status.OLD:
            age = group.age_days(today) or 0
            facts.append(("Note", f"This driver is {age / 365.25:.1f} years old and Windows "
                                  "Update offers nothing newer. The manufacturer's tool or "
                                  "site may have a newer one."))
        item.facts = facts
        out.append(item)

    for offer in driver_offers:
        if offer.id in claimed:
            continue
        out.append(Item(
            key=offer.key, kind=Kind.DRIVER, name=offer.driver_model or offer.title,
            available=offer.driver_date or "", status=Status.UPDATE, action=Action.WU,
            source="Windows Update", publisher=offer.driver_manufacturer, wu_ids=(offer.id,),
            facts=[("Offered", offer.title), ("Class", offer.driver_class or "not recorded"),
                   ("Hardware id", offer.hardware_id or "not recorded"),
                   ("Note", "Windows Update offers this driver for hardware in this "
                            "machine; no installed driver package was matched to it.")]))
    return out


def _windows(sources: Sources) -> list[Item]:
    out = []
    for offer in sources.offers or []:
        if offer.is_driver:
            continue
        facts = [("Title", offer.title)]
        if offer.kb:
            facts.append(("KB", ", ".join(f"KB{k}" for k in offer.kb.split(",") if k)))
        if offer.categories:
            facts.append(("Categories", offer.categories))
        if offer.severity:
            facts.append(("Severity", offer.severity))
        if offer.size:
            facts.append(("Download", f"{offer.size / 1e6:,.1f} MB"))
        if offer.optional:
            facts.append(("Note", "Optional: Windows lists this but does not install it on "
                                  "its own."))
        out.append(Item(key=offer.key, kind=Kind.WINDOWS, name=offer.title,
                        available=f"KB{offer.kb.split(',')[0]}" if offer.kb else "",
                        status=Status.UPDATE, action=Action.WU, source="Windows Update",
                        publisher="Microsoft", wu_ids=(offer.id,), facts=facts))
    return out


# --------------------------------------------------------------------------
# What the window shows.
# --------------------------------------------------------------------------

SHOWS = ("updates", "all", "apps", "drivers", "windows", "ignored")


def visible(item: Item, show: str, ignored: frozenset[str] | set[str]) -> bool:
    is_ignored = item.key in ignored
    if show == "ignored":
        return is_ignored
    if is_ignored:
        return False
    if show == "updates":
        return item.status in (Status.UPDATE, Status.OLD, Status.FAILED, Status.DONE)
    if show == "apps":
        return item.kind == Kind.APP
    if show == "drivers":
        return item.kind == Kind.DRIVER
    if show == "windows":
        return item.kind == Kind.WINDOWS
    return True


def matches(item: Item, text: str) -> bool:
    if not text:
        return True
    needle = text.lower()
    return any(needle in (value or "").lower()
               for value in (item.name, item.publisher, item.winget_id, item.installed,
                             item.available))


def counts(items: list[Item], ignored: frozenset[str] | set[str]) -> dict[str, int]:
    return {show: sum(1 for item in items if visible(item, show, ignored)) for show in SHOWS}
