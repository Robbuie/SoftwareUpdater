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
