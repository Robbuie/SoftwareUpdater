"""Software Updater -- what on this Windows machine is out of date, and the
way to bring each thing up to date.

Split three ways, like File Manager and File Compare, and the boundaries are
the design: `ui` renders and takes input and never runs a program or touches a
file, `core` holds the inventory and every decision about it, `io` runs
winget, PowerShell and the registry reads. See CLAUDE.md before adding to any
of them.
"""

__version__ = "0.2.0"
