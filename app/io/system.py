"""Opening things for the user: a web page, a manufacturer's tool, a Windows
settings page. And finding which manufacturer tools are installed.

Opening is ShellExecute through `os.startfile`, so a page opens in the
user's own browser and a tool starts as it would from the Start menu. These
are user actions, one per click; nothing here runs on its own.
"""

from __future__ import annotations

import os
import sys

from app.core.oem import Tool

#: Windows' own pages, by what they are for.
SETTINGS = {
    "windows-update": "ms-settings:windowsupdate",
    "optional-updates": "ms-settings:windowsupdate-optionalupdates",
    "apps": "ms-settings:appsfeatures",
}


def open_target(target: str) -> str:
    """Open a URL, a settings page or a program. "" on success, else why not."""
    if sys.platform != "win32":
        return "Opening things is only available on Windows."
    try:
        os.startfile(target)  # noqa: S606 - a user's click, a known target
        return ""
    except OSError as exc:
        return str(exc)


def device_manager() -> str:
    if sys.platform != "win32":
        return "Device Manager is only available on Windows."
    try:
        os.startfile("devmgmt.msc")  # noqa: S606
        return ""
    except OSError as exc:
        return str(exc)


def tool_path(tool: Tool) -> str:
    """The tool's executable if it is installed, else ""."""
    for candidate in tool.paths:
        path = os.path.expandvars(candidate)
        if "%" not in path and os.path.isfile(path):
            return path
    return ""


def found_tools(tools: list[Tool]) -> dict[str, str]:
    return {tool.name: tool_path(tool) for tool in tools}
