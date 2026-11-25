"""Measuring and cleaning the `core/cleanup.py` targets, and walking a folder
for the space finder. Worker threads only."""

from __future__ import annotations

import fnmatch
import os
import threading

from app.core import cleanup, space
from app.io import elevated, files, scripts


def env() -> dict[str, str]:
    return dict(os.environ)


def _keep(target: cleanup.Target):
    by_age = files.older_than(target.days) if target.days else None
    pattern = target.pattern.lower()

    def keep(entry: os.DirEntry) -> bool:
        if pattern and not fnmatch.fnmatch(entry.name.lower(), pattern):
            return False
        return by_age(entry) if by_age else True

    return keep


def measure(target: cleanup.Target, *, cancel: threading.Event | None = None) -> cleanup.Measured:
    if target.method == cleanup.Method.RECYCLE_BIN:
        size, count = files.recycle_bin_size()
        return cleanup.Measured(target.id, size, count)
    if target.method in (cleanup.Method.DELIVERY, cleanup.Method.DISM):
        return cleanup.Measured(target.id, None, 0, "Measured when it runs")
    total = cleanup.Measured(target.id, 0, 0)
    unreadable = False
    for root in cleanup.locations(target, env()):
        if not os.path.isdir(root) or files.is_link(root) or files.is_network(root):
            continue
        try:
            os.listdir(root)
        except OSError:
            unreadable = True
            continue
        for _entry, size in files.walk_files(root, cancel=cancel, keep=_keep(target)):
            total.bytes += size
            total.files += 1
    if unreadable and not total.bytes:
        return cleanup.Measured(target.id, None, 0, "Needs administrator rights to measure")
    return total


def clean(target: cleanup.Target, *, cancel: threading.Event | None = None) -> cleanup.Cleaned:
    """A target that needs no rights. Elevated ones go through `clean_elevated`."""
    if target.method == cleanup.Method.RECYCLE_BIN:
        size, count = files.recycle_bin_size()
        error = files.empty_recycle_bin()
        return cleanup.Cleaned(target.id, 0 if error else size, 0 if error else count, 0, error)
    result = cleanup.Cleaned(target.id)
    environment = env()
    for root in cleanup.locations(target, environment):
        # Checked again here, against the fixed list: nothing but a cleanup
        # location is ever handed to the deleting walk.
        if not cleanup.allowed(root, environment) or files.is_network(root):
            result.error = f"Refused: {root}"
            continue
        if not os.path.isdir(root) or files.is_link(root):
            continue
        for entry, size in list(files.walk_files(root, cancel=cancel, keep=_keep(target))):
            try:
                os.remove(entry.path)
                result.bytes += size
                result.files += 1
            except OSError:
                result.skipped += 1
    return result


def clean_elevated(targets: list[cleanup.Target], *, timeout: float = 3600.0,
                   cancel: threading.Event | None = None) -> list[cleanup.Cleaned]:
    environment = env()
    request = {"targets": [{"id": t.id, "method": t.method, "days": t.days,
                            "pattern": t.pattern, "paths": cleanup.locations(t, environment)}
                           for t in targets]}
    outcome = elevated.run(scripts.embed(scripts.CLEAN, request=request), timeout=timeout,
                           cancel=cancel)
    if not outcome.ok:
        return [cleanup.Cleaned(t.id, error=outcome.error) for t in targets]
    out = []
    for entry in (outcome.data or {}).get("results") or []:
        if isinstance(entry, dict):
            out.append(cleanup.Cleaned(str(entry.get("target") or ""),
                                       int(entry.get("bytes") or 0), int(entry.get("files") or 0),
                                       int(entry.get("skipped") or 0),
                                       str(entry.get("error") or "")))
    return out


# --------------------------------------------------------------------------
# The space finder.
# --------------------------------------------------------------------------

def scan_space(root: str, *, cancel: threading.Event | None = None,
               progress=None) -> space.Node:
    if files.is_network(root):
        raise ValueError("Network locations are not scanned.")
    root = os.path.abspath(root)
    tree = space.Node(os.path.basename(root.rstrip("\\/")) or root, root)
    prefix = len(root.rstrip("\\/")) + 1
    count = 0
    for entry, size in files.walk_files(root, cancel=cancel):
        folder = os.path.dirname(entry.path)
        relative = folder[prefix:] if len(folder) >= prefix else ""
        parts = [p for p in relative.replace("/", "\\").split("\\") if p]
        space.add(tree, parts, size)
        count += 1
        if progress is not None and count % 5000 == 0:
            progress(count, tree.size)
    return tree


def downloads_folder() -> str:
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            # FOLDERID_Downloads: the real location, even when moved to D:.
            class GUID(ctypes.Structure):
                _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD),
                            ("d", ctypes.c_ubyte * 8)]

            guid = GUID(0x374DE290, 0x123F, 0x4565,
                        (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None,
                                                         ctypes.byref(out)) == 0:
                path = out.value
                ctypes.windll.ole32.CoTaskMemFree(out)
                if path:
                    return path
        except (OSError, AttributeError):
            pass
    return os.path.join(os.path.expanduser("~"), "Downloads")


def forgotten_downloads(*, cancel: threading.Event | None = None) -> list[space.Forgotten]:
    folder = downloads_folder()
    if not os.path.isdir(folder) or files.is_network(folder):
        return []
    found = []
    for entry, size in files.walk_files(folder, cancel=cancel):
        try:
            found.append((entry.path, size, entry.stat(follow_symlinks=False).st_mtime))
        except OSError:
            continue
    return space.forgotten(found)
