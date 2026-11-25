# Changelog

## 0.2.0 -- 2026-11-25

Three sections now: Software, Cleanup and Security (Alt+1, Alt+2, Alt+3).

- **Uninstall** (Ctrl+Delete): winget's uninstall when winget knows the
  program, otherwise the program's own uninstaller (its quiet one where it
  has one; MSI entries removed rather than repaired). Afterwards, what it
  left behind -- install folder, AppData and ProgramData folders, its HKCU
  key -- is listed with a box each. Folders go to the Recycle Bin; keys are
  backed up to a .reg file first.
- **Cleanup**: temp files, the thumbnail cache, crash dumps, the Recycle
  Bin, the Delivery Optimization cache, downloaded Windows updates, DISM's
  component cleanup, and pip, npm, NuGet, Gradle and Maven caches, each
  measured, with a box. What needs administrator rights runs in one
  elevated batch. Emptying the Recycle Bin, DISM and the build caches are
  off unless ticked.
- **Find space**: a folder's tree by size, and large or forgotten files in
  Downloads; picked items go to the Recycle Bin.
- **Security**: Windows support status, antivirus, firewall, BitLocker,
  Secure Boot, UAC, SMBv1, Remote Desktop, WDigest, automatic sign-in, LSA
  protection, Guest and administrator accounts, last update, pending
  restart, out-of-date browsers and missing Windows security updates. Fix
  opens the Windows page for each; Defender's definitions can be updated
  from here.
- **pip and npm**: outdated packages for every Python found and for global
  npm, under Dev. Never part of Update all.
- **Security review** of the application itself (SECURITY.md). The elevated
  Windows Update install in 0.1.0 could have had its script swapped by
  another local user before it ran as administrator; elevated scripts are
  now hash-checked and carry their data inside them. Cleanup and the space
  finder refuse system, profile and network folders, and a misdirected TEMP.
- Lists' checkboxes are drawn by the theme, so an unticked box is visible.

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
