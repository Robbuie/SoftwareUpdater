"""The two long jobs -- a scan and an update run -- as functions the loader
runs on a worker thread. Each reports progress as plain tuples, which the
window turns into rows, a log line, a status message.

Progress events:

    ("stage", stage, Scan)                 a scan source finished; a snapshot
    ("start", key, name)                   a winget upgrade began
    ("line", key, text)                    a line of winget's output
    ("done", key, ok, note)                a winget upgrade ended
    ("wu-start", count)                    the elevated Windows Update run began
    ("wu-done", InstallResult)             and ended
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from app.core import plan as _plan
from app.core import scan as _scan
from app.core import winget


def scan(job, options: _scan.Options) -> _scan.Scan:
    from app.io.probe import Probe

    def report(stage: str, state: _scan.Scan) -> None:
        snapshot = _scan.Scan(sources=copy.copy(state.sources), system=dict(state.system),
                              winget_path=state.winget_path, errors=dict(state.errors),
                              seconds=dict(state.seconds))
        job.progress(("stage", stage, snapshot))

    return _scan.run(Probe(), options, cancel=job.cancel, report=report)


@dataclass
class Settings:
    winget_exe: str
    silent: bool = True
    upgrade_timeout: float = 1800.0
    wu_server: str = "windows-update"
    wu_timeout: float = 3600.0


@dataclass
class Outcome:
    done: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    reboot: bool = False
    cancelled: bool = False


def update(job, plan: _plan.Plan, settings: Settings) -> Outcome:
    from app.io import wingetcli, wuinstall

    outcome = Outcome()
    for step in plan.winget:
        if job.cancel.is_set():
            outcome.cancelled = True
            return outcome
        job.progress(("start", step.key, step.name))
        result = wingetcli.upgrade(
            settings.winget_exe, step.winget_id, timeout=settings.upgrade_timeout,
            silent=settings.silent, unknown_version=step.unknown_version,
            source=step.winget_source, cancel=job.cancel,
            on_line=lambda text, k=step.key: job.progress(("line", k, text)))
        if result.cancelled:
            outcome.cancelled = True
            job.progress(("done", step.key, False, "Cancelled."))
            return outcome
        if result.timed_out:
            note = f"Stopped after {settings.upgrade_timeout / 60:.0f} minutes without finishing."
            ok = False
        elif result.missing:
            note, ok = f"winget could not be started: {result.err}", False
        else:
            ok = winget.succeeded(result.code)
            note = winget.explain(result.code)
            if not ok:
                tail = [line for line in result.out.splitlines() if line.strip()][-1:]
                if tail and not note.startswith(tail[0]):
                    note += " " + tail[0].strip()
            if (result.code & 0xFFFFFFFF) == 0x8A150109:
                outcome.reboot = True
        if ok:
            outcome.done.append(step.key)
        else:
            outcome.failed[step.key] = note
        job.progress(("done", step.key, ok, note))

    from app.core import devtools
    from app.io import run as _run

    for item in plan.dev:
        if job.cancel.is_set():
            outcome.cancelled = True
            return outcome
        name = dict(item.facts).get("Package", item.name)
        package = devtools.Package(item.source, name, item.installed, item.available,
                                   item.tool, "")
        job.progress(("start", item.key, item.name))
        result = _run.run(devtools.upgrade_command(package), timeout=settings.upgrade_timeout,
                          cancel=job.cancel,
                          on_line=lambda text, k=item.key: job.progress(("line", k, text)))
        ok = result.ok
        if ok:
            note = "Updated."
        elif result.timed_out or result.cancelled:
            note = "Stopped."
        else:
            tail = [l for l in (result.err or result.out).splitlines() if l.strip()][-1:]
            note = tail[0].strip() if tail else f"Exited with {result.code}."
            if "permission" in note.lower() or "access is denied" in note.lower():
                note += " This Python is installed for everyone; run the command as administrator."
        if ok:
            outcome.done.append(item.key)
        else:
            outcome.failed[item.key] = note
        job.progress(("done", item.key, ok, note))

    if plan.wu and not job.cancel.is_set():
        job.progress(("wu-start", len(plan.wu)))
        result = wuinstall.install(plan.wu_ids, server=settings.wu_server,
                                   timeout=settings.wu_timeout, cancel=job.cancel)
        job.progress(("wu-done", result))
        by_id = {o.id: o for o in result.outcomes}
        for item in plan.wu:
            results = [by_id[i] for i in item.wu_ids if i in by_id]
            if results and all(r.ok for r in results):
                outcome.done.append(item.key)
            else:
                text = "; ".join(r.text for r in results) or result.error or "Not installed."
                outcome.failed[item.key] = text
        outcome.reboot = outcome.reboot or result.reboot
    return outcome


# --------------------------------------------------------------------------
# Uninstalling (0.2).
#
#   ("u-start", key, name, command text)   an uninstaller started
#   ("line", key, text)                    winget's output
#   ("u-done", key, ok, note)              and ended
# --------------------------------------------------------------------------

@dataclass
class Removal:
    key: str
    name: str
    publisher: str
    location: str
    winget_id: str = ""
    winget_source: str = ""
    uninstall: str = ""
    quiet_uninstall: str = ""


@dataclass
class RemovalOutcome:
    done: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    #: What each removed program left, by key, for the user to choose from.
    leftovers: dict = field(default_factory=dict)
    cancelled: bool = False


def uninstall(job, removals: list[Removal], others: list[str], *, winget_exe: str,
              silent: bool, timeout: float) -> RemovalOutcome:
    from app.core import uninstall as rules
    from app.io import uninstaller

    outcome = RemovalOutcome()
    for removal in removals:
        if job.cancel.is_set():
            outcome.cancelled = True
            break
        command = rules.command_for(
            winget_id=removal.winget_id if winget_exe else "", source=removal.winget_source,
            quiet=removal.quiet_uninstall, uninstall=removal.uninstall, silent=silent)
        if command is None:
            outcome.failed[removal.key] = "Windows has no uninstall command recorded for it."
            job.progress(("u-done", removal.key, False, outcome.failed[removal.key]))
            continue
        job.progress(("u-start", removal.key, removal.name, command.text()))
        ran = uninstaller.run(command, winget_exe=winget_exe, timeout=timeout, cancel=job.cancel,
                              on_line=lambda text, k=removal.key: job.progress(("line", k, text)))
        if ran.ok:
            outcome.done.append(removal.key)
            found = uninstaller.leftovers(name=removal.name, publisher=removal.publisher,
                                          location=removal.location, others=others,
                                          cancel=job.cancel)
            if found.folders or found.keys:
                outcome.leftovers[removal.key] = found
        else:
            outcome.failed[removal.key] = ran.note
        job.progress(("u-done", removal.key, ran.ok, ran.note))
    return outcome


def remove_leftovers(job, chosen: list, name: str):
    from app.io import uninstaller

    return uninstaller.remove(chosen, name=name)


# --------------------------------------------------------------------------
# Cleanup and space (0.2).
#
#   ("measured", Measured)       one target measured
#   ("cleaned", Cleaned)         one target cleaned
#   ("space", files, bytes)      the space finder's running count
# --------------------------------------------------------------------------

def measure(job, ids: list[str]) -> list:
    from app.core import cleanup
    from app.io import cleaner

    out = []
    for ident in ids:
        if job.cancel.is_set():
            break
        result = cleaner.measure(cleanup.BY_ID[ident], cancel=job.cancel)
        job.progress(("measured", result))
        out.append(result)
    return out


def clean(job, ids: list[str]) -> list:
    """Targets needing no rights first, one by one; then every target that
    needs rights in a single elevated run, so there is one prompt."""
    from app.core import cleanup
    from app.io import cleaner

    targets = [cleanup.BY_ID[i] for i in ids if i in cleanup.BY_ID]
    out = []
    for target in [t for t in targets if not t.admin]:
        if job.cancel.is_set():
            return out
        result = cleaner.clean(target, cancel=job.cancel)
        job.progress(("cleaned", result))
        out.append(result)
    elevated = [t for t in targets if t.admin]
    if elevated and not job.cancel.is_set():
        job.progress(("elevating", len(elevated)))
        for result in cleaner.clean_elevated(elevated, cancel=job.cancel):
            job.progress(("cleaned", result))
            out.append(result)
    return out


def scan_space(job, root: str):
    from app.io import cleaner

    tree = cleaner.scan_space(root, cancel=job.cancel,
                              progress=lambda n, b: job.progress(("space", n, b)))
    return tree


def forgotten(job):
    from app.io import cleaner

    return cleaner.forgotten_downloads(cancel=job.cancel)


def recycle(job, paths: list[str]):
    """Checked here, off the window, against the rules in core/cleanup.py: a
    path the window was handed can never widen what is recycled."""
    import os

    from app.core import cleanup
    from app.io import files

    env = dict(os.environ)
    refused = {p: why for p in paths if (why := cleanup.may_recycle(p, env))}
    done, failed = files.recycle([p for p in paths if p not in refused])
    failed.update(refused)
    return done, failed


def free_space(job, drive: str = ""):
    """(drive, free, total) for the system drive, or the one given."""
    import os

    from app.io import files

    drive = drive or os.environ.get("SystemDrive", "C:")
    free, total = files.disk_usage(drive + "\\")
    return drive, free, total


def home_folder(job) -> str:
    import os

    return os.environ.get("USERPROFILE") or os.path.expanduser("~")


# --------------------------------------------------------------------------
# Security (0.2).
# --------------------------------------------------------------------------

def security_facts(job) -> dict:
    from app.io import powershell, scripts

    answer = powershell.call(scripts.SECURITY, timeout=120, cancel=job.cancel)
    if not answer.ok and not isinstance(answer.data, dict):
        raise RuntimeError(answer.error or "The checks did not answer.")
    return answer.data if isinstance(answer.data, dict) else {}


def defender_update(job) -> str:
    from app.io import elevated, scripts

    outcome = elevated.run(scripts.DEFENDER_UPDATE, timeout=600, cancel=job.cancel)
    if not outcome.ok:
        return outcome.error
    data = outcome.data or {}
    if not data.get("ok"):
        return str(data.get("error") or "Not updated.")
    return ""


def open_target(job, target: str, arguments: str = "") -> str:
    from app.io import system

    return system.open_target(target, arguments)
