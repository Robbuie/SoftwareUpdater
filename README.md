# Software Updater

![icon](assets/icon.png)

What on this Windows machine is out of date -- applications and drivers --
and the way to update each one. Part of the same family as File Manager and
File Compare: the same look, the same keys where the ideas match, and the
same refusal to freeze while something slow is being asked.

## What it does

- **Lists everything installed**: programs from the registry, Store and MSIX
  apps through winget, and device drivers grouped by driver package.
- **Says what is out of date**, from the sources that know:
  - **winget** for applications;
  - **Windows Update** for drivers and Windows' own updates (asking
    Microsoft directly by default, so a company WSUS server that approves no
    drivers does not hide them);
  - **driver age** for third-party drivers nothing offers an update for,
    marked "Old: check manufacturer".
- **Updates with one click**: select rows and press Update (Ctrl+U), or
  Update all. Applications go through winget one at a time; drivers and
  Windows updates go through Windows Update together, after one
  administrator prompt. A confirmation lists exactly what will run first.
- **Opens the PC maker's tool** -- Dell Command Update, Lenovo System Update,
  HP Support Assistant, Intel Driver & Support Assistant -- or the maker's
  driver page when the tool is not installed, for BIOS and firmware.
- **Ignore** rows you do not want to hear about; **filter** by name, id or
  version; **export** an HTML or CSV report.
- `SoftwareUpdater --report out.html` scans without a window and exits 0
  (nothing to do), 1 (something to do) or 2 (the scan failed).

Every source runs off the window's thread with a timeout; Esc stops a scan
or an update run.

## Running

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m app
```

Needs Windows 10 or 11 with winget (Microsoft's App Installer) for the
application half. Without winget the list still shows installed programs and
drivers, marked "Unknown".

F1 in the window lists the keys.

## When something looks wrong

Each source can be run alone, printing what the program said and what was
made of it:

```
python -m app.harness winget-upgrade --raw
python -m app.harness drivers
python -m app.harness windows-update
python -m app.harness inventory
```
