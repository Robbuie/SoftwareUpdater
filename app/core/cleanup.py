"""What can be cleaned, where it is, and what to say about it. Pure.

Each `Target` is a kind of disposable data with fixed locations. Nothing a
person typed and nothing read from the registry becomes a cleanup location:
every path here is a template over a known environment variable, expanded by
`expand`, and the deletion code refuses anything outside the expanded set
(`io/cleaner.py`), elevated script included.

Three groups, as the user asked for them:

- **Temporary files and caches** -- temp folders, the thumbnail cache, crash
  dumps and error reports, the Recycle Bin, and the Delivery Optimization
  cache. Temp files younger than a day are left: an installer that is
  running right now may be using them.
- **Windows Update leftovers** -- downloaded update files once installed,
  and the component store cleanup DISM performs (superseded versions of
  system files). Both need administrator rights; they run in one elevated
  batch with one prompt.
- **Developer caches** -- pip, npm, NuGet, Gradle and Maven. The first three
  are pure download caches. The NuGet package folder, Gradle caches and the
  Maven repository are also caches, but a build reads them, so clearing them
  costs a re-download and an offline build would fail -- those are off by
  default and say so.

The big-folder finder is in `core/space.py`.
"""

from __future__ import annotations

import ntpath
import re
from dataclasses import dataclass

TEMP = "Temporary files and caches"
WINDOWS_UPDATE = "Windows Update leftovers"
DEV = "Developer caches"
GROUPS = (TEMP, WINDOWS_UPDATE, DEV)


class Method:
    FILES = "files"                   # delete files under the paths
    RECYCLE_BIN = "recycle-bin"       # empty the Recycle Bin
    DELIVERY = "delivery"             # Delete-DeliveryOptimizationCache
    DISM = "dism"                     # DISM /StartComponentCleanup


@dataclass(frozen=True)
class Target:
    id: str
    label: str
    group: str
    paths: tuple[str, ...] = ()
    #: Only files older than this many days.
    days: float = 0
    #: Only files whose name matches (fnmatch, lower case); "" for all.
    pattern: str = ""
    admin: bool = False
    method: str = Method.FILES
    note: str = ""
    default: bool = True


TARGETS: tuple[Target, ...] = (
    Target("user-temp", "Your temporary files", TEMP, (r"%TEMP%",), days=1,
           note="Files programs left in your temp folder, older than a day."),
    Target("windows-temp", "Windows temporary files", TEMP, (r"%SystemRoot%\Temp",), days=1,
           admin=True, note="The system temp folder, older than a day."),
    Target("thumbnails", "Thumbnail cache", TEMP,
           (r"%LOCALAPPDATA%\Microsoft\Windows\Explorer",), pattern="thumbcache_*.db",
           note="Explorer rebuilds the previews as folders are opened. Files in use are left."),
    Target("crash-user", "Crash dumps and error reports", TEMP,
           (r"%LOCALAPPDATA%\CrashDumps", r"%LOCALAPPDATA%\Microsoft\Windows\WER\ReportArchive",
            r"%LOCALAPPDATA%\Microsoft\Windows\WER\ReportQueue"),
           note="Saved when a program crashed. Useful only to whoever is debugging it."),
    Target("crash-system", "System crash dumps and error reports", TEMP,
           (r"%SystemRoot%\Minidump", r"%ProgramData%\Microsoft\Windows\WER\ReportArchive",
            r"%ProgramData%\Microsoft\Windows\WER\ReportQueue"), admin=True,
           note="Saved after a blue screen or a service crash."),
    Target("recycle-bin", "Recycle Bin", TEMP, method=Method.RECYCLE_BIN, default=False,
           note="Everything in the Recycle Bin on every drive. This cannot be undone."),
    Target("delivery", "Delivery Optimization cache", TEMP, admin=True, method=Method.DELIVERY,
           note="Update pieces Windows keeps to share with other PCs. Re-downloaded if needed."),
    Target("wu-download", "Downloaded Windows updates", WINDOWS_UPDATE,
           (r"%SystemRoot%\SoftwareDistribution\Download",), days=10, admin=True,
           note="Update files already installed, older than ten days."),
    Target("component-store", "Superseded system files (DISM)", WINDOWS_UPDATE, admin=True,
           method=Method.DISM, default=False,
           note="Old versions of Windows components replaced by updates. Takes several "
                "minutes; afterwards installed updates can no longer be uninstalled."),
    Target("pip", "pip download cache", DEV, (r"%LOCALAPPDATA%\pip\cache",),
           note="Packages pip downloaded. Installed packages are not touched."),
    Target("npm", "npm cache", DEV, (r"%LOCALAPPDATA%\npm-cache\_cacache",),
           note="Packages npm downloaded. Installed packages are not touched."),
    Target("nuget-http", "NuGet download cache", DEV, (r"%LOCALAPPDATA%\NuGet\v3-cache",),
           note="NuGet's HTTP cache."),
    Target("nuget-packages", "NuGet package folder", DEV, (r"%USERPROFILE%\.nuget\packages",),
           default=False,
           note="Every package your .NET builds have used. They are downloaded again by the "
                "next build; an offline build would fail until then."),
    Target("gradle", "Gradle caches", DEV, (r"%USERPROFILE%\.gradle\caches",), default=False,
           note="Re-downloaded by the next Gradle build."),
    Target("maven", "Maven repository", DEV, (r"%USERPROFILE%\.m2\repository",), default=False,
           note="Re-downloaded by the next Maven build."),
)

BY_ID = {t.id: t for t in TARGETS}

_VAR = re.compile(r"%([^%]+)%")


def expand(template: str, env: dict[str, str]) -> str | None:
    """`%VAR%` from `env` only; None when a variable is missing or empty, so
    a missing variable can never turn into a path relative to somewhere else."""
    missing = False

    def sub(match: re.Match) -> str:
        nonlocal missing
        value = env.get(match.group(1)) or env.get(match.group(1).upper()) or ""
        if not value:
            missing = True
        return value

    path = _VAR.sub(sub, template)
    if missing or not ntpath.isabs(path) or path.startswith("\\\\"):
        return None
    return ntpath.normpath(path)


def locations(target: Target, env: dict[str, str]) -> list[str]:
    """The target's folders, minus any that resolve somewhere dangerous."""
    return [p for p in (expand(t, env) for t in target.paths)
            if p and not dangerous_root(p, env)]


def _n(path: str) -> str:
    return ntpath.normcase(ntpath.normpath(path)).rstrip("\\")


def _within(path: str, root: str) -> bool:
    p, r = _n(path), _n(root)
    return bool(r) and (p == r or p.startswith(r + "\\"))


def _key_folders(env: dict[str, str]) -> list[str]:
    names = ("USERPROFILE", "SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData",
             "APPDATA", "LOCALAPPDATA", "PUBLIC", "SystemDrive")
    return [env[n] + ("\\" if n == "SystemDrive" else "") for n in names if env.get(n)]


def dangerous_root(path: str, env: dict[str, str]) -> bool:
    """True when a cleanup location resolved to somewhere whose files are not
    disposable: a drive root, a key Windows folder itself, the profile, or a
    folder directly in the profile (Documents, Desktop, Downloads...).

    The case this exists for: `%TEMP%` set by hand, or by a broken installer,
    to the profile or to Documents. "Files older than a day in your temp
    folder" would then mean most of the user's own files."""
    norm = _n(path)
    if len(norm) <= 3:                       # "c:" or "c:\\"
        return True
    profile = env.get("USERPROFILE")
    if profile and _n(ntpath.dirname(norm)) == _n(profile):
        return ntpath.basename(norm).lower() not in ("appdata", ".gradle", ".m2", ".nuget")
    return any(_n(folder) == norm or _within(folder, norm) for folder in _key_folders(env))


def may_recycle(path: str, env: dict[str, str]) -> str:
    """"" when the space finder may send `path` to the Recycle Bin, else why
    not. Windows and installed programs are never recycled from here --
    programs are removed with Uninstall, which knows what else to undo."""
    if not path or path.startswith("\\\\") or not ntpath.isabs(path):
        return "Only local folders and files."
    if dangerous_root(path, env):
        return "A system or profile folder; it is never removed from here."
    for name in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        root = env.get(name)
        if root and _within(path, root):
            return ("Inside Windows or Program Files: use Uninstall for programs."
                    if name != "SystemRoot" else "Inside Windows.")
    return ""


def allowed(path: str, env: dict[str, str]) -> bool:
    """True when `path` is one of the cleanup locations or inside one."""
    norm = ntpath.normcase(ntpath.normpath(path))
    for target in TARGETS:
        for root in locations(target, env):
            r = ntpath.normcase(root)
            if norm == r or norm.startswith(r + "\\"):
                return True
    return False


def size_text(value: int | None) -> str:
    if value is None:
        return "--"
    if value < 1024:
        return f"{value} B"
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024
        if value < 1024 or unit == "TB":
            return f"{value:,.1f} {unit}" if value < 100 else f"{value:,.0f} {unit}"
    return ""


@dataclass
class Measured:
    target: str
    bytes: int | None = None     # None: not readable without administrator rights
    files: int = 0
    note: str = ""


@dataclass
class Cleaned:
    target: str
    bytes: int = 0
    files: int = 0
    skipped: int = 0
    error: str = ""
