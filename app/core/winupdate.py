"""What the Windows Update Agent offers, and what it said after installing. Pure.

The agent is asked through its COM API from PowerShell (`io/scripts.py`),
which writes JSON. Two kinds of update come back from the same search:
drivers (type 2) and software (type 1) -- the cumulative updates, Defender
definitions and .NET patches that Settings > Windows Update also lists.

Which server is asked matters on a managed machine. By default the agent asks
whatever policy names, which on a company laptop is often WSUS or Intune, and
those commonly approve no drivers at all -- so a search there says "nothing to
do" about drivers Microsoft does have. `wu.server = "windows-update"` asks
Microsoft's public Windows Update service directly, the same thing "Check
online for updates from Microsoft Update" does. Policy can forbid that too;
when it does, the search fails with a code, and that code is shown.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.drivers import as_list

SOFTWARE = 1
DRIVER = 2


@dataclass
class Offer:
    id: str
    revision: int
    title: str
    kind: int
    kb: str = ""
    size: int = 0
    driver_model: str = ""
    driver_manufacturer: str = ""
    driver_class: str = ""
    driver_date: str = ""
    hardware_id: str = ""
    categories: str = ""
    severity: str = ""
    #: Optional: Windows lists it but does not install it automatically.
    optional: bool = False

    @property
    def key(self) -> str:
        return f"wu:{self.id}"

    @property
    def is_driver(self) -> bool:
        return self.kind == DRIVER


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def offers(payload) -> list[Offer]:
    out = []
    for entry in as_list(payload):
        ident = str(entry.get("id") or "").strip()
        title = str(entry.get("title") or "").strip()
        if not ident or not title:
            continue
        out.append(Offer(
            id=ident,
            revision=_int(entry.get("rev")),
            title=title,
            kind=_int(entry.get("type")) or SOFTWARE,
            kb=str(entry.get("kb") or ""),
            size=_int(entry.get("size")),
            driver_model=str(entry.get("driverModel") or ""),
            driver_manufacturer=str(entry.get("driverManufacturer") or ""),
            driver_class=str(entry.get("driverClass") or ""),
            driver_date=str(entry.get("driverDate") or "")[:10],
            hardware_id=str(entry.get("hardwareId") or ""),
            categories=str(entry.get("categories") or ""),
            severity=str(entry.get("severity") or ""),
            optional=bool(entry.get("browseOnly")),
        ))
    return out


#: OperationResultCode from the agent.
RESULT_CODES = {
    0: "Not started",
    1: "In progress",
    2: "Installed",
    3: "Installed with errors",
    4: "Failed",
    5: "Aborted",
}

#: HRESULTs the agent returns often enough to be worth words.
HRESULTS = {
    0x80240024: "There are no updates.",
    0x8024402C: "Windows Update could not be reached (proxy or network).",
    0x8024401C: "Windows Update timed out.",
    0x80244022: "Windows Update service is unavailable right now.",
    0x8024002E: "Policy blocks access to Windows Update from this machine.",
    0x80240438: "Windows Update could not be reached; policy may block it.",
    0x80070005: "Access denied: installing needs administrator rights.",
    0x800704C7: "Cancelled.",
    0x80240022: "Every update in the request failed.",
    0x8024001E: "The service or system was shutting down.",
}


def explain(hresult: int) -> str:
    code = hresult & 0xFFFFFFFF
    return HRESULTS.get(code, f"0x{code:08X}")


@dataclass
class Outcome:
    id: str
    title: str
    code: int
    hresult: int = 0

    @property
    def ok(self) -> bool:
        return self.code in (2, 3)

    @property
    def text(self) -> str:
        words = RESULT_CODES.get(self.code, f"Result {self.code}")
        if self.hresult and not self.ok:
            words += f" ({explain(self.hresult)})"
        return words


@dataclass
class InstallResult:
    outcomes: list[Outcome]
    reboot: bool = False
    error: str = ""


def install_result(payload) -> InstallResult:
    """What the elevated install script wrote to its result file."""
    if not isinstance(payload, dict):
        return InstallResult([], error="The installer wrote no result.")
    error = str(payload.get("error") or "")
    outcomes = [Outcome(id=str(e.get("id") or ""), title=str(e.get("title") or ""),
                        code=_int(e.get("code")), hresult=_int(e.get("hresult")))
                for e in as_list(payload.get("results"))]
    return InstallResult(outcomes, reboot=bool(payload.get("reboot")), error=error)
