"""Settings, with a default for every key and no raw key reads anywhere.

The same shape as File Manager's and File Compare's `core/config.py`, and the
same deliberate exception to the rule about the UI thread: `%APPDATA%` is
local by definition, the read happens once before the window exists and the
write on close.

`get` raises on an unknown key rather than returning None: a typo that reads
as "off" is found months later by somebody wondering why a preference never
applied.
"""

from __future__ import annotations

import json
import os
from typing import Any

APP_FOLDER = "SoftwareUpdater"
FILE_NAME = "config.json"


def _home() -> str:
    return os.environ.get("USERPROFILE") or os.path.expanduser("~")


DEFAULTS: dict[str, Any] = {
    # The family's newest look (File Compare 1.25) by default.
    "theme": "slate",
    "accent": "sky",
    "density": "normal",
    # Take theme, accent and density from File Manager's settings, read once
    # at startup and never written.
    "look.follow_file_manager": False,

    "window.width": 1280,
    "window.height": 820,
    "window.maximized": False,
    "window.split": [620, 220],

    # Scan once a few seconds after the window opens.
    "scan.on_launch": True,
    # Which sources a scan asks. Each can be turned off on its own, because
    # on some machines one of them is slow or blocked by policy.
    "scan.winget": True,
    "scan.drivers": True,
    "scan.windows_update": True,

    # List packages whose installed version winget cannot read, and upgrade
    # them when asked. winget leaves them out unless told.
    "winget.include_unknown": True,
    # Run installers without their own windows where the package allows it.
    "winget.silent": True,
    # Seconds for `winget list` and `winget upgrade` to answer, and for one
    # package's upgrade to finish.
    "winget.timeout": 180.0,
    "winget.upgrade_timeout": 1800.0,

    # "windows-update": ask Microsoft's Windows Update service directly, so a
    # WSUS or Intune policy that approves no drivers does not hide them.
    # "default": ask whatever server policy names, as Settings does.
    "wu.server": "windows-update",
    "wu.timeout": 600.0,
    "wu.install_timeout": 3600.0,

    # A third-party driver older than this, with nothing newer offered, is
    # marked "old" as a prompt to check the manufacturer. 0 turns it off.
    "drivers.old_years": 3.0,
    # Windows' own inbox drivers (provider Microsoft) are hidden unless an
    # update is offered for one.
    "drivers.include_inbox": False,
    "drivers.timeout": 120.0,

    # Which rows the list shows: updates, all, apps, drivers, windows, ignored.
    "view.show": "updates",
    "view.details": True,

    # Rows the user said to stop showing, by item key.
    "ignore.items": [],

    # Look for a new version of this application, once, a few seconds after
    # the window opens (CLAUDE.md, Scope).
    "updates.check_on_launch": True,
    "updates.skip_version": "",
}


class Config:
    """A flat dotted-key store over `DEFAULTS`."""

    def __init__(self, values: dict[str, Any] | None = None, path: str | None = None):
        self._values = dict(values or {})
        self._path = path or self.default_path()

    @property
    def path(self) -> str:
        return self._path

    @staticmethod
    def default_path() -> str:
        base = os.environ.get("APPDATA") or os.path.join(_home(), ".config")
        return os.path.join(base, APP_FOLDER, FILE_NAME)

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        """Read the settings file, falling back to defaults on any problem.
        A corrupt settings file must not stop the application starting."""
        target = path or cls.default_path()
        try:
            with open(target, "r", encoding="utf-8") as handle:
                values = json.load(handle)
            if not isinstance(values, dict):
                values = {}
        except (OSError, ValueError):
            values = {}
        return cls({k: v for k, v in values.items() if k in DEFAULTS}, target)

    def get(self, key: str) -> Any:
        if key not in DEFAULTS:
            raise KeyError(f"unknown setting {key!r}; add it to config.DEFAULTS")
        return self._values.get(key, DEFAULTS[key])

    def set(self, key: str, value: Any) -> None:
        if key not in DEFAULTS:
            raise KeyError(f"unknown setting {key!r}; add it to config.DEFAULTS")
        self._values[key] = value

    def save(self) -> bool:
        """Write the settings out. False rather than raising: failing to save
        a preference is not worth an error dialog on the way out."""
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as handle:
                json.dump(self._values, handle, indent=2, sort_keys=True)
            return True
        except OSError:
            return False


def scan_options(config: Config):
    from app.core.scan import Options

    return Options(
        winget=bool(config.get("scan.winget")),
        drivers=bool(config.get("scan.drivers")),
        windows_update=bool(config.get("scan.windows_update")),
        include_unknown=bool(config.get("winget.include_unknown")),
        wu_server=str(config.get("wu.server")),
        winget_timeout=float(config.get("winget.timeout")),
        drivers_timeout=float(config.get("drivers.timeout")),
        wu_timeout=float(config.get("wu.timeout")),
    )
