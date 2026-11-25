"""Running work off the UI thread and getting the answer back onto it.

The same contract as File Compare's `core/loader.py`, without its worker
processes for network shares -- this application reads no shares. The
window asks, gets a request id, and later receives `finished(id, envelope)`
on its own thread; a reply nobody is waiting for any more is dropped by the
receiver.

Always *later*, never inside `submit`: the worker side emits a private
signal connected with `QueuedConnection`, so even work that finishes at once
is delivered by the event loop after the caller has stored its id. File
Compare learned that the hard way and the reasoning is in its loader.

`progress(id, payload)` carries anything a running job wants the window to
see before it finishes -- a scan stage, a line of winget's output.
"""

from __future__ import annotations

import itertools
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal

WORKERS = 4


@dataclass
class Envelope:
    ok: bool
    value: Any = None
    error: str = ""


class Job:
    """What a running job is handed: a way to report, and a cancel flag."""

    def __init__(self, loader: "Loader", request: int) -> None:
        self._loader = loader
        self.request = request
        self.cancel = threading.Event()

    def progress(self, payload: Any) -> None:
        self._loader._progress.emit(self.request, payload)


class Loader(QObject):
    finished = Signal(int, object)
    progress = Signal(int, object)
    _ready = Signal(int, object)
    _progress = Signal(int, object)

    def __init__(self, parent: QObject | None = None, workers: int = WORKERS) -> None:
        super().__init__(parent)
        self._ready.connect(self.finished.emit, Qt.QueuedConnection)
        self._progress.connect(self.progress.emit, Qt.QueuedConnection)
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="softwareupdater")
        self._ids = itertools.count(1)
        self._jobs: dict[int, Job] = {}

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> int:
        """Run `fn(job, *args, **kwargs)` on a worker thread."""
        request = next(self._ids)
        job = Job(self, request)
        self._jobs[request] = job

        def work() -> None:
            envelope = _guard(fn, (job, *args), kwargs)
            self._jobs.pop(request, None)
            self._ready.emit(request, envelope)

        self._pool.submit(work)
        return request

    def cancel(self, request: int) -> bool:
        job = self._jobs.get(request)
        if job is None:
            return False
        job.cancel.set()
        return True

    def running(self, request: int) -> bool:
        return request in self._jobs

    def shutdown(self) -> None:
        for job in list(self._jobs.values()):
            job.cancel.set()
        self._pool.shutdown(wait=False, cancel_futures=True)


def _guard(fn: Callable[..., Any], args: tuple, kwargs: dict) -> Envelope:
    try:
        return Envelope(True, fn(*args, **kwargs))
    except Exception as exc:  # noqa: BLE001 - every failure becomes an envelope
        detail = traceback.format_exc(limit=4)
        return Envelope(False, None, f"{type(exc).__name__}: {exc}\n{detail}")
