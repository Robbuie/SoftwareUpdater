"""Starting one program as administrator, and waiting for it.

Only Windows Update installs need this: the agent refuses to install for a
standard token, and unlike winget it does not ask for elevation itself. So
the install script is started through ShellExecuteEx with the `runas` verb,
which is what shows the UAC prompt, and this waits on the process handle.

The application itself never runs elevated. It is installed per user so that
its own updates need no prompt (see CLAUDE.md, Packaging), and a whole window
running as administrator to make one call would be a large thing to ask for a
small one.

A UAC prompt answered "No" is ERROR_CANCELLED (1223), returned as a normal
result rather than raised.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass

ERROR_CANCELLED = 1223
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_NO_CONSOLE = 0x00008000
SW_HIDE = 0
SW_SHOWNORMAL = 1
WAIT_TIMEOUT = 0x102


@dataclass
class Elevated:
    started: bool
    code: int = -1
    declined: bool = False
    timed_out: bool = False
    cancelled: bool = False
    error: str = ""


def run(executable: str, parameters: str, *, timeout: float,
        cancel: threading.Event | None = None, verb: str = "runas",
        show: bool = False) -> Elevated:
    """Start `executable` through ShellExecuteEx and wait for it.

    `verb="runas"` asks for administrator rights. `verb="open"` starts it as
    the user and lets its own manifest decide -- which is how an uninstaller
    that needs rights gets a UAC prompt instead of failing."""
    if sys.platform != "win32":
        return Elevated(False, error="Elevation is only available on Windows.")
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
            ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
        ]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32 = ctypes.windll.kernel32
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NO_CONSOLE
    info.lpVerb = verb
    info.lpFile = executable
    info.lpParameters = parameters
    info.nShow = SW_SHOWNORMAL if show else SW_HIDE
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == ERROR_CANCELLED:
            return Elevated(False, declined=True, error="The Windows prompt was declined.")
        return Elevated(False, error=f"Could not start as administrator (error {error}).")
    handle = info.hProcess
    if not handle:
        return Elevated(True, code=0)
    started = time.monotonic()
    try:
        while True:
            state = kernel32.WaitForSingleObject(handle, 250)
            if state != WAIT_TIMEOUT:
                break
            if cancel is not None and cancel.is_set():
                # An elevated process can be ended from here only because we
                # hold its handle; Windows granted it with the launch.
                kernel32.TerminateProcess(handle, 1)
                return Elevated(True, cancelled=True, error="Cancelled.")
            if time.monotonic() - started > timeout:
                kernel32.TerminateProcess(handle, 1)
                return Elevated(True, timed_out=True,
                                error=f"No result after {timeout / 60:.0f} minutes.")
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return Elevated(True, code=int(code.value))
    finally:
        kernel32.CloseHandle(handle)
