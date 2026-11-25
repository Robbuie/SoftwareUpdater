"""Running a program and getting its output, with a deadline and a cancel.

Everything this application learns comes from another program -- winget,
PowerShell -- and every one of them can hang: winget waiting on a source
that is not answering, the Windows Update Agent searching a WSUS server that
is not there, an installer showing a dialog on a desktop nobody is looking
at. So nothing is ever run without a timeout, a run can be cancelled from the
window, and either way the whole process tree is ended, because winget
starting an installer that starts another installer is the normal case.

Output is read on a thread of its own as it arrives, so `on_line` can show an
upgrade's progress while it runs and a full pipe can never stall the child.
No console window flashes up: the child is started with CREATE_NO_WINDOW.

Called from worker threads only. Never from `app/ui/`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

CREATE_NO_WINDOW = 0x08000000


@dataclass
class Result:
    code: int
    out: str
    err: str = ""
    timed_out: bool = False
    cancelled: bool = False
    missing: bool = False
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.code == 0 and not (self.timed_out or self.cancelled or self.missing)


def _kill_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=CREATE_NO_WINDOW, check=False)
    try:
        process.kill()
    except OSError:
        pass


def run(command: list[str], *, timeout: float, cancel: threading.Event | None = None,
        on_line: Callable[[str], None] | None = None, env: dict | None = None) -> Result:
    started = time.monotonic()
    flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
    environment = dict(os.environ)
    environment.update(env or {})
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, creationflags=flags, env=environment)
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return Result(code=-1, out="", err=str(exc), missing=True)

    out_chunks: list[bytes] = []
    err_chunks: list[bytes] = []

    def pump_out() -> None:
        assert process.stdout is not None
        pending = b""
        for chunk in iter(lambda: process.stdout.read1(4096), b""):
            out_chunks.append(chunk)
            if on_line is None:
                continue
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                text = decode(line).rsplit("\r", 1)[-1].rstrip()
                if text.strip():
                    on_line(text)
        if on_line is not None and pending.strip():
            on_line(decode(pending).rsplit("\r", 1)[-1].rstrip())

    def pump_err() -> None:
        assert process.stderr is not None
        for chunk in iter(lambda: process.stderr.read1(4096), b""):
            err_chunks.append(chunk)

    readers = [threading.Thread(target=pump_out, daemon=True),
               threading.Thread(target=pump_err, daemon=True)]
    for reader in readers:
        reader.start()

    timed_out = cancelled = False
    while process.poll() is None:
        if cancel is not None and cancel.is_set():
            cancelled = True
            _kill_tree(process)
            break
        if time.monotonic() - started > timeout:
            timed_out = True
            _kill_tree(process)
            break
        time.sleep(0.1)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _kill_tree(process)
    for reader in readers:
        reader.join(timeout=2)
    code = process.returncode if process.returncode is not None else -1
    return Result(code=code & 0xFFFFFFFF if code >= 0 or sys.platform == "win32" else code,
                  out=decode(b"".join(out_chunks)), err=decode(b"".join(err_chunks)),
                  timed_out=timed_out, cancelled=cancelled,
                  seconds=time.monotonic() - started)


def decode(data: bytes) -> str:
    """UTF-8 first, which is what winget and the scripts here write; the
    console's code page only if that fails, so an older tool's accented text
    is still readable."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        import locale

        return data.decode(locale.getpreferredencoding(False) or "cp1252", errors="replace")
