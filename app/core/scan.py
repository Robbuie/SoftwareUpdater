"""One scan of the machine: every source asked at once, each answer reported
as it arrives.

The sources take very different times. The registry answers in a fraction of
a second, winget in five to thirty, the Windows Update Agent anywhere from ten
seconds to several minutes. So they run side by side, and each one is handed
to `report` the moment it is in -- the window shows installed programs while
Windows Update is still searching, rather than a spinner for three minutes.

A source that fails reports its failure and the others carry on. What failed
is kept (`Scan.errors`) and shown, because "no driver updates" and "the
driver search did not run" must never look the same.

The programs are run through a `Probe` (`io/probe.py`), passed in, so the
tests drive this with a fake one and nothing here touches the machine.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from app.core import drivers as _drivers
from app.core import winget as _winget
from app.core import winupdate
from app.core.inventory import Installed, Sources


class Stage:
    SYSTEM = "system"
    REGISTRY = "registry"
    WINGET = "winget"
    DRIVERS = "drivers"
    WINDOWS_UPDATE = "windows-update"
    DEV = "dev"


STAGE_LABELS = {
    Stage.SYSTEM: "This computer",
    Stage.REGISTRY: "Installed programs",
    Stage.WINGET: "winget",
    Stage.DRIVERS: "Drivers",
    Stage.WINDOWS_UPDATE: "Windows Update",
    Stage.DEV: "pip and npm",
}


@dataclass
class Options:
    winget: bool = True
    drivers: bool = True
    windows_update: bool = True
    dev: bool = True
    include_unknown: bool = True
    wu_server: str = "windows-update"
    winget_timeout: float = 180.0
    drivers_timeout: float = 120.0
    wu_timeout: float = 600.0


@dataclass
class Answer:
    """What one stage produced. `value` is the parsed result, `error` what
    went wrong if anything did, in words."""

    ok: bool
    value: Any = None
    error: str = ""
    seconds: float = 0.0


class Probe(Protocol):
    def system(self, timeout: float, cancel: threading.Event) -> Answer: ...  # noqa: E704
    def installed(self) -> list[Installed]: ...  # noqa: E704
    def winget(self) -> str | None: ...  # noqa: E704
    def winget_list(self, exe: str, timeout: float, cancel: threading.Event) -> Answer: ...  # noqa: E704,E501
    def winget_upgrades(self, exe: str, timeout: float, include_unknown: bool,  # noqa: E704
                        cancel: threading.Event) -> Answer: ...
    def drivers(self, timeout: float, cancel: threading.Event) -> Answer: ...  # noqa: E704
    def windows_update(self, server: str, timeout: float,  # noqa: E704
                       cancel: threading.Event) -> Answer: ...
    def dev(self, timeout: float, cancel: threading.Event) -> Answer: ...  # noqa: E704


@dataclass
class Scan:
    sources: Sources = field(default_factory=Sources)
    system: dict = field(default_factory=dict)
    winget_path: str = ""
    errors: dict[str, str] = field(default_factory=dict)
    seconds: dict[str, float] = field(default_factory=dict)
    finished_at: float = 0.0


Report = Callable[[str, Scan], None]


def run(probe: Probe, options: Options, *, cancel: threading.Event | None = None,
        report: Report | None = None) -> Scan:
    cancel = cancel or threading.Event()
    scan = Scan()
    lock = threading.Lock()

    def done(stage: str, seconds: float, error: str = "") -> None:
        with lock:
            scan.seconds[stage] = seconds
            if error:
                scan.errors[stage] = error
            if report is not None:
                report(stage, scan)

    def system() -> None:
        answer = probe.system(60.0, cancel)
        if answer.ok and isinstance(answer.value, dict):
            scan.system = answer.value
        done(Stage.SYSTEM, answer.seconds, "" if answer.ok else answer.error)

    def registry() -> None:
        started = time.monotonic()
        try:
            scan.sources.installed = probe.installed()
            done(Stage.REGISTRY, time.monotonic() - started)
        except Exception as exc:  # noqa: BLE001 - a broken key must not end the scan
            done(Stage.REGISTRY, time.monotonic() - started, f"Could not read: {exc}")

    def winget() -> None:
        started = time.monotonic()
        exe = probe.winget()
        if not exe:
            done(Stage.WINGET, 0.0, "winget is not installed. It comes with Microsoft's "
                                    "App Installer, from the Microsoft Store.")
            return
        scan.winget_path = exe
        listed = probe.winget_list(exe, options.winget_timeout, cancel)
        if listed.ok:
            scan.sources.winget_list = _winget.rows(listed.value)
        upgrades = probe.winget_upgrades(exe, options.winget_timeout, options.include_unknown,
                                         cancel)
        if upgrades.ok:
            scan.sources.winget_upgrades = _winget.rows(upgrades.value)
        errors = [a.error for a in (listed, upgrades) if not a.ok and a.error]
        done(Stage.WINGET, time.monotonic() - started, " ".join(dict.fromkeys(errors)))

    def drivers() -> None:
        answer = probe.drivers(options.drivers_timeout, cancel)
        if answer.ok:
            payload = answer.value.get("drivers") if isinstance(answer.value, dict) else answer.value
            scan.sources.drivers = _drivers.group(_drivers.devices(payload))
        done(Stage.DRIVERS, answer.seconds, "" if answer.ok else answer.error)

    def windows_update() -> None:
        answer = probe.windows_update(options.wu_server, options.wu_timeout, cancel)
        if answer.ok:
            payload = answer.value.get("updates") if isinstance(answer.value, dict) else answer.value
            scan.sources.offers = winupdate.offers(payload)
        done(Stage.WINDOWS_UPDATE, answer.seconds, "" if answer.ok else answer.error)

    def dev() -> None:
        answer = probe.dev(options.winget_timeout, cancel)
        if answer.ok:
            scan.sources.dev = list(answer.value or [])
        # A partial answer (one Python's pip failed) is still an answer, and
        # what failed is still worth saying.
        done(Stage.DEV, answer.seconds, answer.error)

    jobs: list[Callable[[], None]] = [system, registry]
    if options.winget:
        jobs.append(winget)
    if options.drivers:
        jobs.append(drivers)
    if options.windows_update:
        jobs.append(windows_update)
    if options.dev:
        jobs.append(dev)
    with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="scan") as pool:
        for future in [pool.submit(job) for job in jobs]:
            future.result()
    scan.finished_at = time.time()
    return scan


def stages(options: Options) -> list[str]:
    out = [Stage.SYSTEM, Stage.REGISTRY]
    if options.winget:
        out.append(Stage.WINGET)
    if options.drivers:
        out.append(Stage.DRIVERS)
    if options.windows_update:
        out.append(Stage.WINDOWS_UPDATE)
    if options.dev:
        out.append(Stage.DEV)
    return out
