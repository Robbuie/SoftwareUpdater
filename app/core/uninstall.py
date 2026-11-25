"""Removing a program, and what it left behind. Pure.

**The uninstaller.** A program winget can match is removed with `winget
uninstall --id`, which knows each installer's quiet switches. Anything else
is removed with the command Windows recorded for it in the Uninstall key:
`QuietUninstallString` when the publisher wrote one, else `UninstallString`.
An MSI entry's string is usually `MsiExec.exe /I{GUID}` -- which opens the
*repair* dialog -- so it is rewritten to `/X{GUID}`, remove.

The command is started through ShellExecute (`io/uninstaller.py`), not
CreateProcess, so an uninstaller whose manifest asks for administrator rights
gets its UAC prompt instead of failing with "elevation required". This
application never elevates an uninstaller itself.

**Leftovers.** After the uninstaller finishes, the places programs commonly
leave behind are listed: the install folder if it survived, and folders
named after the program (or publisher\\program) in Program Files, ProgramData
and the user's AppData. The user ticks what goes; folders go to the Recycle
Bin, never straight to deletion.

**The guard.** `safe_leftover` is the most important function in this file.
A leftover is only ever offered if it is strictly inside one of the known
roots, at least one level down, not a reparse point (checked by the caller),
and its own name shares a real word with the program's name. "C:\\Program
Files", "C:\\Users\\me", "AppData\\Roaming" and anything outside those roots can
never appear, whatever the registry says -- the Uninstall key is writable by
any program running as the user, so its InstallLocation is not trusted.
"""

from __future__ import annotations

import ntpath
import re
from dataclasses import dataclass, field

#: Environment variables naming the roots a leftover may be inside.
ROOT_VARS = ("ProgramFiles", "ProgramFiles(x86)", "ProgramData", "APPDATA", "LOCALAPPDATA")

#: Words too common to tie a folder to a program.
STOP_WORDS = frozenset({
    "the", "and", "for", "inc", "llc", "ltd", "corp", "corporation", "company", "software",
    "microsoft", "windows", "update", "updates", "x64", "x86", "bit", "64", "32", "version",
    "setup", "installer", "app", "apps", "tool", "tools", "driver", "drivers", "common",
    "files", "program", "programs", "data", "local", "roaming", "temp", "user", "users",
    "packages", "edition", "pro", "free", "community", "runtime", "redistributable",
    "plus", "lite", "beta", "en", "us", "intel", "nvidia", "amd", "dell", "hp", "lenovo",
})

#: Folders never offered however well they match: shared by many programs.
NEVER = frozenset({
    "common files", "microsoft", "microsoft shared", "windows", "windowsapps", "packages",
    "temp", "programs", "microsoft.net", "dotnet", "installer", "package cache",
    "windows defender", "windows nt", "internet explorer", "modifiablewindowsapps",
})


@dataclass
class Command:
    """What to start: an executable and its parameter string, for ShellExecute."""

    executable: str
    parameters: str = ""
    winget_id: str = ""
    #: For winget: the arguments as a list, run directly rather than parsed.
    args: list[str] = field(default_factory=list)

    def text(self) -> str:
        if self.winget_id:
            return "winget " + self.parameters
        exe = f'"{self.executable}"' if " " in self.executable else self.executable
        return f"{exe} {self.parameters}".strip()


_MSI = re.compile(r"^\s*\"?msiexec(\.exe)?\"?\s+.*?/[IX]\s*(\{[0-9A-Fa-f-]{36}\})", re.I)


def split_command(line: str) -> tuple[str, str]:
    """An Uninstall string as (executable, parameters).

    Recorded strings come in three shapes: quoted path then arguments, an
    unquoted path with spaces ending in `.exe` then arguments, and a bare
    program name. CreateProcess would guess at the second; ShellExecute wants
    them apart, so they are split here, deterministically.
    """
    text = (line or "").strip()
    if not text:
        return "", ""
    if text.startswith('"'):
        end = text.find('"', 1)
        if end > 0:
            return text[1:end], text[end + 1:].strip()
        return text.strip('"'), ""
    lower = text.lower()
    for ext in (".exe", ".cmd", ".bat", ".msc"):
        at = lower.find(ext)
        if at > 0:
            stop = at + len(ext)
            if stop == len(text) or text[stop] in " \t/":
                return text[:stop], text[stop:].strip()
    first, _, rest = text.partition(" ")
    return first, rest.strip()


def msi_remove(line: str) -> str | None:
    """`/X{GUID}` for an MSI entry, whatever it recorded."""
    match = _MSI.match(line or "")
    return match.group(2) if match else None


#: Windows' own programs an Uninstall string may name without a path. They
#: are run from System32 by full path, never found by searching.
SYSTEM_TOOLS = frozenset({"msiexec.exe", "msiexec", "rundll32.exe", "rundll32"})


def runnable(executable: str) -> bool:
    """A full local path, or one of Windows' own tools. A bare name like
    "uninstall.exe" would be looked for in the current folder first -- where
    something else could be waiting -- so it is refused."""
    if executable.lower() in SYSTEM_TOOLS:
        return True
    return ntpath.isabs(executable) and not executable.startswith("\\\\")


def command_for(*, winget_id: str = "", source: str = "", quiet: str = "", uninstall: str = "",
                silent: bool = True) -> Command | None:
    if winget_id:
        args = ["uninstall", "--id", winget_id, "--exact", "--accept-source-agreements",
                "--disable-interactivity"]
        if source in ("winget", "msstore"):
            args += ["--source", source]
        if silent:
            args.append("--silent")
        return Command("winget", " ".join(_q(a) for a in args), winget_id=winget_id, args=args)
    guid = msi_remove(quiet or uninstall)
    if guid:
        # /passive: a progress bar and no questions. Quiet enough, and the
        # user can see it is happening.
        return Command("msiexec.exe", f"/X{guid} /passive /norestart")
    line = (quiet if silent and quiet else "") or uninstall
    if not line:
        return None
    exe, params = split_command(line)
    return Command(exe, params) if exe else None


def _q(value: str) -> str:
    return f'"{value}"' if " " in value else value


# --------------------------------------------------------------------------
# Leftovers.
# --------------------------------------------------------------------------

def words(text: str) -> set[str]:
    found = {w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(w) >= 3}
    return {w for w in found if w not in STOP_WORDS and not w.isdigit()}


def _norm(path: str) -> str:
    return ntpath.normcase(ntpath.normpath(path)).rstrip("\\")


def inside(path: str, root: str) -> bool:
    """Strictly inside `root`, not equal to it."""
    p, r = _norm(path), _norm(root)
    return bool(r) and p.startswith(r + "\\") and len(p) > len(r) + 1


def safe_leftover(path: str, *, name: str, publisher: str, roots: dict[str, str]) -> bool:
    """True only for a folder this program plausibly owns. See the module
    docstring; every condition here is a reason something was refused."""
    if not path or not ntpath.isabs(path) or path.startswith("\\\\"):
        return False
    norm = _norm(path)
    if ".." in path.split("\\") or ".." in path.split("/"):
        return False
    root = next((r for r in roots.values() if r and inside(norm, r)), None)
    if root is None:
        return False
    tail = norm[len(_norm(root)) + 1:].split("\\")
    if not tail or not tail[0]:
        return False
    leaf = ntpath.basename(norm)
    if leaf in NEVER:
        return False
    # The folder's own name must share a word with the program's name. A
    # publisher folder alone (C:\Program Files\Contoso) is never enough:
    # other programs of that publisher may live in it.
    return bool(words(leaf) & words(name))


@dataclass
class Leftover:
    path: str
    kind: str = "folder"     # "folder" or "key"
    size: int = 0
    why: str = ""


@dataclass
class Leftovers:
    folders: list[Leftover] = field(default_factory=list)
    keys: list[Leftover] = field(default_factory=list)


def candidates(*, name: str, publisher: str, location: str, roots: dict[str, str],
               others: list[str] | tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """Folders worth checking, with why each is suspected. The caller keeps
    the ones that exist and are not reparse points.

    `others` are the install folders of every *other* program still
    installed. A candidate that is one of them, or holds one of them, is
    refused: "C:\\Program Files\\Microsoft Office" after removing Visio would
    take Word with it."""
    out: list[tuple[str, str]] = []
    if location:
        out.append((location.rstrip("\\/"), "Install folder"))
    short = _folder_name(name)
    names = {n for n in (name.strip(), short) if n}
    pub = _folder_name(publisher)
    for var in ROOT_VARS:
        root = roots.get(var)
        if not root:
            continue
        for candidate in names:
            out.append((ntpath.join(root, candidate), f"Named after the program in {var}"))
            if pub and pub.lower() != candidate.lower():
                out.append((ntpath.join(root, pub, candidate),
                            f"Publisher folder in {var}"))
    seen: set[str] = set()
    kept = []
    for path, why in out:
        key = _norm(path)
        if key in seen or not safe_leftover(path, name=name, publisher=publisher, roots=roots):
            continue
        if any(o and (_norm(o) == key or inside(o, key)) for o in others):
            continue
        seen.add(key)
        kept.append((path, why))
    return kept


def _folder_name(text: str) -> str:
    """"Notepad++ (64-bit x64)" -> "Notepad++"; "7-Zip 23.01 (x64)" -> "7-Zip";
    "Contoso, Inc." -> "Contoso"."""
    text = re.sub(r"\(.*?\)", " ", text or "")
    text = re.sub(r",?\s*(inc|llc|ltd|corp|corporation|gmbh)\.?$", "", text.strip(), flags=re.I)
    text = re.sub(r"\s+v?\d+(\.\d+)+.*$", "", text.strip())
    return re.sub(r'[<>:"/\\|?*]', "", text).strip(" .")


def registry_candidates(*, name: str, publisher: str) -> list[str]:
    """HKCU keys a program commonly leaves. Only the user's own hive: a
    machine-wide key is not something to delete from here."""
    short = _folder_name(name)
    pub = _folder_name(publisher)
    out = []
    if short and words(short):
        out.append(f"Software\\{short}")
        if pub and pub.lower() != short.lower():
            out.append(f"Software\\{pub}\\{short}")
    return out


def safe_key(subkey: str, *, name: str) -> bool:
    parts = subkey.split("\\")
    if len(parts) < 2 or parts[0].lower() != "software":
        return False
    if parts[1].lower() in ("microsoft", "classes", "policies", "wow6432node", "clients"):
        return False
    return bool(words(parts[-1]) & words(name))


__all__ = ["Command", "command_for", "split_command", "msi_remove", "candidates",
           "safe_leftover", "registry_candidates", "safe_key", "Leftover", "Leftovers"]
