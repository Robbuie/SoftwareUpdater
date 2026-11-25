"""Measuring and removing files: the only module that deletes anything.

Three rules hold for everything here, and `CLAUDE.md` explains why each one
exists:

- **Links are never followed.** A junction or symbolic link inside a temp
  folder can point anywhere -- at the user's documents, at another drive.
  `os.scandir` entries are checked with `follow_symlinks=False` and anything
  carrying the reparse-point attribute is neither descended into nor deleted.
- **Network locations are refused.** A UNC path, or a drive letter Windows
  reports as remote, is never measured or deleted (company policy, and a dead
  share would hang the walk).
- **What a person picked goes to the Recycle Bin.** Leftover folders and the
  big-folder finder's choices are recycled through the shell, so a mistake is
  one Restore away. Only the cleanup targets -- temp files and caches, which
  their owners recreate -- are deleted outright.
"""

from __future__ import annotations

import os
import stat
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

FILE_ATTRIBUTE_REPARSE_POINT = 0x400
DRIVE_REMOTE = 4


def is_link(entry_or_path) -> bool:
    try:
        if isinstance(entry_or_path, os.DirEntry):
            if entry_or_path.is_symlink():
                return True
            info = entry_or_path.stat(follow_symlinks=False)
        else:
            info = os.lstat(entry_or_path)
            if stat.S_ISLNK(info.st_mode):
                return True
    except OSError:
        return True  # unreadable: treat as untouchable
    attrs = getattr(info, "st_file_attributes", 0)
    return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)


def is_network(path: str) -> bool:
    if path.startswith("\\\\") or path.startswith("//"):
        return True
    if sys.platform != "win32" or len(path) < 2 or path[1] != ":":
        return False
    import ctypes

    return ctypes.windll.kernel32.GetDriveTypeW(path[:2] + "\\") == DRIVE_REMOTE


@dataclass
class Tally:
    files: int = 0
    bytes: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def walk_files(root: str, *, cancel: threading.Event | None = None,
               keep: Callable[[os.DirEntry], bool] | None = None):
    """Every file under `root` that `keep` accepts, links never followed.
    Yields (entry, size)."""
    stack = [root]
    while stack:
        if cancel is not None and cancel.is_set():
            return
        folder = stack.pop()
        try:
            with os.scandir(folder) as it:
                entries = list(it)
        except OSError:
            continue
        for entry in entries:
            if is_link(entry):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    if keep is None or keep(entry):
                        yield entry, entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue


def older_than(days: float) -> Callable[[os.DirEntry], bool]:
    limit = time.time() - days * 86400

    def keep(entry: os.DirEntry) -> bool:
        try:
            return entry.stat(follow_symlinks=False).st_mtime < limit
        except OSError:
            return False

    return keep


def measure(root: str, *, days: float = 0, cancel: threading.Event | None = None) -> Tally:
    tally = Tally()
    if not os.path.isdir(root) or is_network(root) or is_link(root):
        return tally
    for _entry, size in walk_files(root, cancel=cancel, keep=older_than(days) if days else None):
        tally.files += 1
        tally.bytes += size
    return tally


def delete_files(root: str, *, days: float = 0, cancel: threading.Event | None = None) -> Tally:
    """Delete the files `measure` counted, then any folders left empty.
    A file in use is skipped and counted, never forced."""
    tally = Tally()
    if not os.path.isdir(root) or is_network(root) or is_link(root):
        return tally
    for entry, size in list(walk_files(root, cancel=cancel,
                                       keep=older_than(days) if days else None)):
        try:
            os.remove(entry.path)
            tally.files += 1
            tally.bytes += size
        except OSError:
            tally.skipped += 1
    _prune_empty(root)
    return tally


def _prune_empty(root: str) -> None:
    """Remove folders the delete left empty, deepest first. The root stays."""
    for folder, _dirs, _files in os.walk(root, topdown=False, followlinks=False):
        if os.path.normcase(folder) == os.path.normcase(root) or is_link(folder):
            continue
        try:
            if not os.listdir(folder):
                os.rmdir(folder)
        except OSError:
            pass


def folder_size(path: str, *, cancel: threading.Event | None = None, limit: int = 200_000) -> int:
    total = 0
    for count, (_entry, size) in enumerate(walk_files(path, cancel=cancel)):
        total += size
        if count >= limit:
            break
    return total


def recycle(paths: list[str]) -> tuple[list[str], dict[str, str]]:
    """Send to the Recycle Bin. Returns (recycled, {path: why not})."""
    done: list[str] = []
    failed: dict[str, str] = {}
    if sys.platform != "win32":
        return done, {p: "The Recycle Bin is only available on Windows." for p in paths}
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE = 3
    FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400
    for path in paths:
        if is_network(path) or is_link(path) or not os.path.exists(path):
            failed[path] = "Not a local file or folder any more."
            continue
        op = SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        op.pFrom = os.path.abspath(path) + "\0"     # double-null terminated
        op.fFlags = FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI
        code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if code == 0 and not op.fAnyOperationsAborted and not os.path.exists(path):
            done.append(path)
        else:
            failed[path] = ("Needs administrator rights, or something has it open."
                            if code in (5, 0x78, 0x20) else f"Not recycled (code {code}).")
    return done, failed


def recycle_bin_size() -> tuple[int, int]:
    """(bytes, items) across every drive's Recycle Bin."""
    if sys.platform != "win32":
        return 0, 0
    import ctypes
    from ctypes import wintypes

    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong),
                    ("i64NumItems", ctypes.c_longlong)]

    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(info)
    if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) != 0:
        return 0, 0
    return int(info.i64Size), int(info.i64NumItems)


def empty_recycle_bin() -> str:
    if sys.platform != "win32":
        return "Only available on Windows."
    import ctypes

    SHERB = 0x1 | 0x2 | 0x4     # no confirmation, no progress, no sound
    code = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, SHERB)
    # S_OK, or E_UNEXPECTED when it was already empty.
    return "" if code in (0, -2147418113, 0x8000FFFF) else f"Not emptied (0x{code & 0xFFFFFFFF:08X})."


def disk_usage(path: str) -> tuple[int, int]:
    """(free, total) bytes on the drive holding `path`."""
    import shutil

    try:
        usage = shutil.disk_usage(path)
        return usage.free, usage.total
    except OSError:
        return 0, 0
