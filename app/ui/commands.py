"""Every command the window offers, in one table, and where each one appears.

File Compare's arrangement (1.17), kept so the two read alike: the menu bar
and the toolbar are both built from this module, so a command has one label,
one key and one icon wherever it shows up, and adding one is a row here plus
whatever runs it. Nothing in this file imports Qt: it is data, and
`ui/chrome.py` (ported verbatim) turns it into widgets.

The window answers `command_state(id)` and `run_command(id)`. The keys are
written beside menu items as text and are handled by `MainWindow._shortcuts`,
not registered by the menus, so the filter box keeps its own keys.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    id: str
    #: The menu text. The toolbar uses `tool` when it is set.
    label: str
    key: str = ""
    glyph: str = ""
    #: The word beside the toolbar icon; "" when the command is never a button.
    tool: str = ""
    tip: str = ""
    checkable: bool = False


@dataclass
class State:
    """What the window says about a command right now."""

    enabled: bool = True
    checked: bool | None = None
    visible: bool = True
    label: str | None = None
    tip: str | None = None
    count: int | None = None


DISABLED = State(enabled=False)
HIDDEN = State(enabled=False, visible=False)


def _c(id: str, label: str, key: str = "", glyph: str = "", tool: str = "", tip: str = "",
       checkable: bool = False) -> Command:  # noqa: A002 - "id" reads best here
    return Command(id, label, key, glyph, tool, tip, checkable)


COMMANDS: dict[str, Command] = {c.id: c for c in (
    # Scan
    _c("scan", "Scan again", "F5", "refresh", "Scan",
       "Ask winget, the drivers and Windows Update again (F5)"),
    _c("stop", "Stop", "Esc", "stop", "Stop", "Stop the scan or the updates (Esc)"),
    _c("export", "Export report...", "Ctrl+Shift+H", "export", "Export",
       "Save what this scan found as an HTML or CSV file (Ctrl+Shift+H)"),
    _c("exit", "Exit", "Alt+F4"),

    # Sections (0.2): one strip of tabs under the command row.
    _c("section-software", "Software", "Alt+1", "upgrade", "Software",
       "Updates and uninstalling (Alt+1)", checkable=True),
    _c("section-cleanup", "Cleanup", "Alt+2", "broom", "Cleanup",
       "Temporary files, caches and big folders (Alt+2)", checkable=True),
    _c("section-security", "Security", "Alt+3", "shield", "Security",
       "This computer's protections (Alt+3)", checkable=True),

    # Update
    _c("update-selected", "Update selected", "Ctrl+U", "upgrade", "Update",
       "Update the selected rows (Ctrl+U)"),
    _c("update-all", "Update everything available", "Ctrl+Shift+U", "upgrade_all",
       "Update all", "Update every row that has an update this application can install "
                     "(Ctrl+Shift+U)"),
    _c("select-updates", "Select every update", "Ctrl+A"),
    _c("uninstall", "Uninstall...", "Ctrl+Delete", "trash", "Uninstall",
       "Remove the selected programs, then offer what they left behind (Ctrl+Delete)"),
    _c("ignore", "Ignore", "Delete", "ignore", "Ignore",
       "Stop showing the selected rows; View > Ignored brings them back (Delete)"),
    _c("unignore", "Show again", "Insert", "", "", "Stop ignoring the selected rows (Insert)"),
    _c("vendor", "Manufacturer's driver tool", "", "web", "Maker",
       "Open this computer maker's driver tool, or its driver page when the tool is "
       "not installed"),
    _c("copy-command", "Copy winget command", "Ctrl+C", "", "",
       "Copy the winget command that updates the selected rows"),
    _c("device-manager", "Device Manager"),
    _c("wu-settings", "Windows Update settings"),
    _c("wu-optional", "Optional updates in Settings"),
    _c("apps-settings", "Installed apps in Settings"),

    # View
    _c("show-updates", "Updates", "Ctrl+1", "", "Updates",
       "Rows with something to do (Ctrl+1)", checkable=True),
    _c("show-all", "Everything", "Ctrl+2", "", "All", "Every row (Ctrl+2)", checkable=True),
    _c("show-apps", "Applications", "Ctrl+3", "", "Apps", "Installed programs (Ctrl+3)",
       checkable=True),
    _c("show-drivers", "Drivers", "Ctrl+4", "", "Drivers", "Device drivers (Ctrl+4)",
       checkable=True),
    _c("show-windows", "Windows updates", "Ctrl+5", "", "Windows",
       "What Windows Update offers besides drivers (Ctrl+5)", checkable=True),
    _c("show-dev", "Developer packages", "Ctrl+6", "", "Dev",
       "Outdated pip and npm packages (Ctrl+6)", checkable=True),
    _c("show-ignored", "Ignored", "Ctrl+7", "", "Ignored", "Rows you chose to ignore (Ctrl+7)",
       checkable=True),
    _c("details", "Details panel", "Ctrl+D", "outline", "", "", checkable=True),
    _c("filter", "Filter...", "Ctrl+F", "search", "", "Find a row by name, id or version"),
    _c("follow-look", "Follow File Manager's look", "", "", "", "", checkable=True),

    # Tools: what a scan asks, and how updates run.
    _c("src-winget", "Ask winget about applications", "", "", "", "", checkable=True),
    _c("src-drivers", "List installed drivers", "", "", "", "", checkable=True),
    _c("src-wu", "Ask Windows Update", "", "", "", "", checkable=True),
    _c("src-dev", "Ask pip and npm", "", "", "", "", checkable=True),
    _c("wu-direct", "Ask Microsoft's Windows Update directly", "", "", "",
       "Bypass a WSUS or Intune server that approves no drivers. Policy can forbid this.",
       checkable=True),
    _c("include-unknown", "Include programs with an unknown version", "", "", "",
       "winget leaves these out unless asked", checkable=True),
    _c("include-inbox", "Show Windows' own drivers", "", "", "",
       "Drivers whose provider is Microsoft, which update with Windows", checkable=True),
    _c("silent", "Install silently where possible", "", "", "",
       "Ask each installer to run without its own windows", checkable=True),
    _c("scan-on-launch", "Scan when the window opens", "", "", "", "", checkable=True),
    _c("updates-on-launch", "Check for a new Software Updater on launch", "", "", "", "",
       checkable=True),

    # Cleanup (0.2)
    _c("clean-targets", "Clean up", "", "", "Clean up", "Temporary files and caches by kind",
       checkable=True),
    _c("clean-space", "Find space", "", "", "Find space",
       "What takes the space in a folder, and forgotten downloads", checkable=True),
    _c("clean-measure", "Measure", "", "refresh", "Measure", "Measure every kind again"),
    _c("clean-run", "Clean ticked", "", "broom", "Clean",
       "Remove the ticked kinds of files"),
    _c("space-scan", "Look in folder", "", "search", "Look", "Add up the folder's sizes"),
    _c("space-recycle", "Send to Recycle Bin", "", "trash", "Recycle",
       "Send the selected folders or files to the Recycle Bin"),
    _c("space-reveal", "Show in Explorer", "", "folder", "Show",
       "Open the selected item in Explorer"),

    # Security (0.2)
    _c("sec-check", "Check again", "", "refresh", "Check", "Run every check again"),
    _c("sec-fix", "Fix", "", "shield", "Fix",
       "Open the Windows page where this is set"),

    # Help
    _c("keys", "Keys", "F1"),
    _c("open-log", "Copy the activity log", "", "", "",
       "Copy everything in the activity panel to the clipboard"),
    _c("check-updates", "Check for updates"),
    _c("about", "About Software Updater"),
)}

#: Submenus filled when they open: (id, title).
DYNAMIC = {
    "theme": "Theme",
    "accent": "Accent",
    "density": "Density",
    "old-years": "Call a driver old after",
}

#: Which section owns which command. A command not listed is the window's.
SECTIONS = ("software", "cleanup", "security")
SECTION_COMMANDS = {"section-software": "software", "section-cleanup": "cleanup",
                    "section-security": "security"}

#: The menu bar: (title, items). An item is a command id, "-" for a
#: separator, or ">name" for a submenu from DYNAMIC.
MENUS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("&Scan", ("scan", "stop", "-", "export", "-", "exit")),
    ("&Software", ("update-selected", "update-all", "-", "uninstall", "-", "select-updates",
                   "copy-command", "-", "ignore", "unignore", "-", "vendor", "device-manager",
                   "wu-settings", "wu-optional", "apps-settings")),
    ("&Cleanup", ("clean-targets", "clean-space", "-", "clean-measure", "clean-run", "-",
                  "space-scan", "space-recycle", "space-reveal")),
    ("Securit&y", ("sec-check", "sec-fix")),
    ("&View", ("section-software", "section-cleanup", "section-security", "-",
               "show-updates", "show-all", "show-apps", "show-drivers", "show-windows",
               "show-dev", "show-ignored", "-", "filter", "details", "-",
               ">theme", ">accent", ">density", "follow-look")),
    ("&Tools", ("src-winget", "src-drivers", "src-wu", "src-dev", "-", "wu-direct",
                "include-unknown",
                "include-inbox", ">old-years", "-", "silent", "-", "scan-on-launch",
                "updates-on-launch")),
    ("H&elp", ("keys", "open-log", "-", "check-updates", "about")),
)

#: File Compare's toolbar markers. SEGMENTED: one segmented control, words
#: only, one of them on; STRETCH: the gap that pushes what follows right;
#: ICONS: the group's buttons show their icon only, the words in the tip.
SEGMENTED = "="
STRETCH = "~"
ICONS = "."
MARKERS = (SEGMENTED, STRETCH, ICONS)

TOOLBARS: dict[str, tuple[tuple[str, ...], ...]] = {
    "software": ((SEGMENTED, "show-updates", "show-all", "show-apps", "show-drivers",
                  "show-windows", "show-dev"),
                 ("update-selected", "update-all", "uninstall"),
                 (STRETCH,),
                 ("ignore", "vendor"),
                 (ICONS, "export"),
                 ("stop", "scan")),
    "cleanup": ((SEGMENTED, "clean-targets", "clean-space"),
                ("clean-measure", "clean-run", "space-scan", "space-recycle", "space-reveal"),
                (STRETCH,),
                ("stop",)),
    "security": (("sec-check", "sec-fix"),
                 (STRETCH,),
                 ("stop",)),
}

#: The menus behind the toolbar's arrows: a tuple of ids, or a DYNAMIC name.
TOOL_MENUS: dict[str, tuple[str, ...] | str] = {
    "vendor": ("vendor", "-", "device-manager", "wu-settings", "wu-optional"),
    "ignore": ("ignore", "unignore"),
}

#: The View filter each show command picks.
SHOW_COMMANDS = {
    "show-updates": "updates", "show-all": "all", "show-apps": "apps",
    "show-drivers": "drivers", "show-windows": "windows", "show-dev": "dev",
    "show-ignored": "ignored",
}

#: Tools menu toggles and the setting each one is.
TOGGLES = {
    "src-winget": "scan.winget",
    "src-drivers": "scan.drivers",
    "src-wu": "scan.windows_update",
    "src-dev": "scan.dev",
    "include-unknown": "winget.include_unknown",
    "include-inbox": "drivers.include_inbox",
    "silent": "winget.silent",
    "scan-on-launch": "scan.on_launch",
    "updates-on-launch": "updates.check_on_launch",
}


def menu_text(command: Command) -> str:
    """The menu item's text with its key after a tab, which a menu draws as
    the shortcut column without the key being registered."""
    return f"{command.label}\t{command.key}" if command.key else command.label


def tool_tip(command: Command) -> str:
    if command.tip:
        return command.tip
    return f"{command.label} ({command.key})" if command.key else command.label


def ids_in_menus() -> set[str]:
    out: set[str] = set()
    for _title, items in MENUS:
        out.update(i for i in items if i != "-" and not i.startswith(">"))
    return out
