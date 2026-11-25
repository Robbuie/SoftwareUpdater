"""Developer packages: what pip and npm say is outdated. Pure.

**pip** is asked once per Python found. The Python launcher (`py -0p`) lists
every registered interpreter; a `python` on PATH that the launcher does not
know (a conda base, a Store Python) is added. Each is asked `python -m pip
list --outdated --format=json`, which covers that interpreter's
site-packages -- global and per-user -- but not virtual environments, which
belong to their projects and are updated there.

**npm** is asked `npm outdated -g --json`: globally installed packages only.

Every row is `opt_in`: never taken by Update all, only updated when ticked
by hand. A global package upgraded under a project that pinned an older one
is the classic way to break a working setup, so it is a deliberate choice
each time.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

PIP = "pip"
NPM = "npm"

_LAUNCHER = re.compile(r"^\s*-(?:V:)?(?P<tag>[^\s*]+)\s*(?:\*)?\s+(?P<path>\S.*?\.exe)\s*$", re.I)


@dataclass
class Interpreter:
    tag: str          # "3.12", "3.12-64", or "PATH"
    path: str


@dataclass
class Package:
    manager: str      # PIP or NPM
    name: str
    current: str
    latest: str
    tool: str         # interpreter path, or the npm command
    tool_label: str   # "Python 3.12", "npm"

    @property
    def key(self) -> str:
        return f"{self.manager}:{self.tool_label.lower()}:{self.name.lower()}"


def interpreters(launcher_output: str, on_path: str = "") -> list[Interpreter]:
    found: list[Interpreter] = []
    seen: set[str] = set()
    for line in (launcher_output or "").splitlines():
        match = _LAUNCHER.match(line)
        if not match:
            continue
        path = match.group("path").strip()
        tag = match.group("tag").lstrip("V:").strip()
        if path.lower() not in seen:
            seen.add(path.lower())
            found.append(Interpreter(tag, path))
    if on_path and on_path.lower() not in seen and on_path.lower().endswith(".exe") \
            and "windowsapps" not in on_path.lower():
        # The WindowsApps "python.exe" is the Store's install prompt, not a Python.
        found.append(Interpreter("PATH", on_path))
    return found


def label(interpreter: Interpreter) -> str:
    if interpreter.tag == "PATH":
        return "Python (PATH)"
    return f"Python {interpreter.tag.split('-')[0]}"


def pip_outdated(text: str, interpreter: Interpreter) -> list[Package]:
    try:
        data = json.loads(_json_part(text))
    except ValueError:
        return []
    out = []
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        out.append(Package(PIP, str(entry["name"]), str(entry.get("version") or ""),
                           str(entry.get("latest_version") or ""), interpreter.path,
                           label(interpreter)))
    return out


def npm_outdated(text: str, npm: str) -> list[Package]:
    try:
        data = json.loads(_json_part(text) or "{}")
    except ValueError:
        return []
    out = []
    if not isinstance(data, dict):
        return out
    for name, entry in data.items():
        if not isinstance(entry, dict) or name == "error":
            continue
        current, latest = str(entry.get("current") or ""), str(entry.get("latest") or "")
        if latest and current != latest:
            out.append(Package(NPM, name, current, latest, npm, "npm"))
    return sorted(out, key=lambda p: p.name.lower())


def _json_part(text: str) -> str:
    """pip and npm sometimes print a notice before the JSON ("A new release of
    pip is available"); the JSON is from the first bracket on."""
    text = (text or "").strip()
    starts = [i for i in (text.find("["), text.find("{")) if i >= 0]
    return text[min(starts):] if starts else ""


def list_args() -> list[str]:
    return ["-m", "pip", "list", "--outdated", "--format=json", "--disable-pip-version-check"]


def upgrade_command(package: Package) -> list[str]:
    if package.manager == PIP:
        return [package.tool, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check",
                package.name]
    return [package.tool, "install", "-g", f"{package.name}@latest"]
