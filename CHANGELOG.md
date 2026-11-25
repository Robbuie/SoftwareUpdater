# Changelog

## 0.1.0 -- 2026-11-25

First version.

- One list of everything installed: registry programs, winget packages
  (Store and MSIX included), and drivers grouped by package.
- Verdicts from winget (`list`, `upgrade --include-unknown`), the Windows
  Update Agent (drivers and software, asking Microsoft's service directly by
  default), and driver age for third-party drivers with nothing offered.
- Update selected or Update all: winget one package at a time as the user;
  Windows Update in one elevated batch. A confirmation lists what will run
  and what cannot be updated from here.
- View filter with counts: Updates, All, Apps, Drivers, Windows, Ignored.
  Filter box, details panel, activity log.
- Ignore and Show again, kept in the settings.
- The PC maker's driver tool or page (Dell, Lenovo, HP, Intel).
- Export to HTML or CSV; `--report` for a scan with no window and an exit
  code.
- `python -m app.harness` to run each source alone.
- The family's look, chrome, single-instance hand-over, and self-update from
  GitHub releases, ported from File Compare 1.26.0.
