"""The manufacturer's own driver tool, for the drivers Windows Update does not
carry. Pure: which tools to look for and where; `io/system.py` looks.

BIOS, firmware, docking-station and most chipset and audio drivers come
from the PC maker, and the maker's tool is the reliable way to get them --
it knows the exact model, which no generic scan can. So this does not try to
replace those tools; it finds the one that belongs to this machine and puts
it one click away, and when it is not installed, says where it comes from.

The paths are where each vendor's installer puts the program. A tool found
at none of them is treated as not installed, and its winget id, where it has
one, is offered instead.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tool:
    name: str
    vendor: str
    #: Candidate executables, `%VAR%` expanded by the caller.
    paths: tuple[str, ...]
    #: The vendor's driver page, for when the tool is not installed.
    url: str
    winget_id: str = ""


TOOLS: tuple[Tool, ...] = (
    Tool("Dell Command | Update", "dell",
         (r"%ProgramFiles%\Dell\CommandUpdate\DellCommandUpdate.exe",
          r"%ProgramFiles(x86)%\Dell\CommandUpdate\DellCommandUpdate.exe"),
         "https://www.dell.com/support/home/drivers", "Dell.CommandUpdate"),
    Tool("Lenovo System Update", "lenovo",
         (r"%ProgramFiles(x86)%\Lenovo\System Update\tvsu.exe",
          r"%ProgramFiles%\Lenovo\System Update\tvsu.exe"),
         "https://support.lenovo.com/solutions/ht003029", "Lenovo.SystemUpdate"),
    Tool("HP Support Assistant", "hp",
         (r"%ProgramFiles(x86)%\HP\HP Support Framework\HPSF.exe",
          r"%ProgramFiles%\HP\HP Support Framework\HPSF.exe"),
         "https://support.hp.com/drivers"),
    Tool("Intel Driver & Support Assistant", "intel",
         (r"%ProgramFiles(x86)%\Intel\Driver and Support Assistant\DSATray.exe",
          r"%ProgramFiles%\Intel\Driver and Support Assistant\DSATray.exe"),
         "https://www.intel.com/content/www/us/en/support/detect.html", "Intel.IntelDriverAndSupportAssistant"),
)

#: How manufacturers spell themselves in Win32_ComputerSystem.
_VENDORS = {
    "dell": "dell", "lenovo": "lenovo", "hp": "hp", "hewlett-packard": "hp",
    "hewlett packard": "hp",
}


def vendor(manufacturer: str) -> str:
    text = (manufacturer or "").strip().lower()
    for word, name in _VENDORS.items():
        if text.startswith(word):
            return name
    return ""


def relevant(manufacturer: str, driver_providers: set[str] | None = None) -> list[Tool]:
    """The tools worth offering on this machine, most useful first: the PC
    maker's own, then Intel's when Intel drivers are installed."""
    out: list[Tool] = []
    maker = vendor(manufacturer)
    for tool in TOOLS:
        if tool.vendor == maker:
            out.append(tool)
    providers = {p.lower() for p in (driver_providers or set())}
    if any(p.startswith("intel") for p in providers):
        out.extend(t for t in TOOLS if t.vendor == "intel")
    return out


def support_url(manufacturer: str) -> str:
    maker = vendor(manufacturer)
    for tool in TOOLS:
        if tool.vendor == maker:
            return tool.url
    return ""
