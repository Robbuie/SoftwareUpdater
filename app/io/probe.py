"""The real `core.scan.Probe`: each source asked of the machine.

Every method here runs a program or reads the registry, so every one is
called from a scan thread, never from the window.
"""

from __future__ import annotations

import threading

from app.core import winupdate
from app.core.inventory import Installed
from app.core.scan import Answer
from app.io import powershell, registry, scripts, wingetcli


def _from(answer: powershell.Answer, explain=None) -> Answer:
    error = answer.error
    if not answer.ok and answer.hresult and explain is not None:
        error = f"{explain(answer.hresult)} {answer.error}".strip()
    return Answer(answer.ok, answer.data, error, answer.seconds)


class Probe:
    def system(self, timeout: float, cancel: threading.Event) -> Answer:
        return _from(powershell.call(scripts.SYSTEM, timeout=timeout, cancel=cancel))

    def installed(self) -> list[Installed]:
        return registry.entries()

    def winget(self) -> str | None:
        return wingetcli.find()

    def _winget(self, result, what: str, timeout: float) -> Answer:
        if result.missing:
            return Answer(False, error=f"winget could not be started: {result.err}")
        if result.cancelled:
            return Answer(False, error="Cancelled.")
        if result.timed_out:
            return Answer(False, error=f"winget {what} gave no answer in {timeout:.0f} seconds.",
                          seconds=result.seconds)
        # `winget upgrade` exits non-zero when there is nothing to upgrade on
        # some versions; the table, or its absence, is the answer either way.
        if result.out.strip():
            return Answer(True, result.out, seconds=result.seconds)
        tail = (result.err or "").strip().splitlines()[-1:] or [f"exit 0x{result.code:08X}"]
        return Answer(False, error=f"winget {what}: {tail[0]}", seconds=result.seconds)

    def winget_list(self, exe: str, timeout: float, cancel: threading.Event) -> Answer:
        return self._winget(wingetcli.list_installed(exe, timeout=timeout, cancel=cancel),
                            "list", timeout)

    def winget_upgrades(self, exe: str, timeout: float, include_unknown: bool,
                        cancel: threading.Event) -> Answer:
        return self._winget(wingetcli.list_upgrades(exe, timeout=timeout,
                                                    include_unknown=include_unknown,
                                                    cancel=cancel), "upgrade", timeout)

    def drivers(self, timeout: float, cancel: threading.Event) -> Answer:
        return _from(powershell.call(scripts.DRIVERS, timeout=timeout, cancel=cancel))

    def dev(self, timeout: float, cancel: threading.Event) -> Answer:
        from app.io import devtools

        return devtools.outdated(timeout=timeout, cancel=cancel)

    def windows_update(self, server: str, timeout: float, cancel: threading.Event) -> Answer:
        script = scripts.fill(scripts.WU_SEARCH, server=server)
        return _from(powershell.call(script, timeout=timeout, cancel=cancel), winupdate.explain)
