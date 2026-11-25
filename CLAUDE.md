# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

**Software Updater** -- a Windows tool that lists what is installed on this
machine, applications and drivers, says which of them are out of date, and
updates the ones it can with one click. Since 0.2 it also uninstalls (with
leftovers), cleans temp files and caches, finds where disk space went, and
checks the machine's security settings: three sections, Software, Cleanup
and Security. Python + PySide6. Personal use,
single user. Repo: `Robbuie/SoftwareUpdater` (public, for the same reason as
the others -- see Packaging). Local path
`C:\Users\Rokray.ENCORE\Projects\SoftwareUpdater`.

It is the fifth app in a family: **Redline PDF** (Electron), **DWG Viewer**
(PyQt6), **File Manager** and **File Compare** (PySide6). They are meant to
read as one suite. "Look and feel" below is a spec, not a suggestion, and
File Compare is the newest member to copy from.

It does not replace the tools that already update things. It asks them and
puts their answers in one list:

- **winget** for applications -- the only source that can both say "newer
  exists" and install it, for most of what people install;
- **Windows Update**, through the Windows Update Agent's COM API, for drivers
  and Windows' own updates;
- **the registry's Uninstall keys** for everything installed, including what
  neither of those knows;
- **Win32_PnPSignedDriver** for installed drivers, so a driver Windows Update
  says nothing about can still be judged by its age;
- **the PC maker's own tool** (Dell Command Update, Lenovo System Update, HP
  Support Assistant, Intel DSA), opened rather than reimplemented, for BIOS,
  firmware and the drivers only the maker publishes.

## Working agreement

The family's, unchanged:

- **No emojis.** Not in the UI, code, comments, commit messages,
  `CHANGELOG.md`, or chat responses about this project.
- **No decorative output.** Comments explain *why*, in prose.
- **Claude cannot run this application's sources.** winget, PowerShell and
  the Windows Update Agent exist only on the real machine. What Claude *can*
  check before calling anything finished:
  - the **parsers and the merge** (`core/winget.py`, `core/drivers.py`,
    `core/winupdate.py`, `core/inventory.py`, `core/plan.py`), pure Python,
    covered by `pytest` against shaped fixtures in `tests/data/`;
  - the **scan's orchestration**, driven by a fake probe (`tests/test_scan.py`);
  - the **look**, through `tools/preview.py`, which renders the real window
    offscreen over the fixture machine.
  The user is the test loop for everything that touches Windows, and
  `python -m app.harness` is how a source is run alone to see its raw output
  next to its parse. Never report a source or an update path as working until
  the user has seen it work. A real capture that parses wrongly goes into
  `tests/data/` with a test.
- **Claude has direct read/write access to this folder in Cowork sessions.**
  Pushing is the user's job.
- **Ask before adding a dependency.** The list is PySide6 alone.
- Every user-visible change gets a `CHANGELOG.md` entry and a version bump.

## Commands

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install pytest

pytest                                   # parsers, merge, plan, scan, window
python tools/run_tests.py                # what CI runs
python -m app                            # the window; scans on opening
python -m app --no-scan                  # the window without the first scan
python -m app --report out.html          # no window; exit 0 none, 1 some, 2 failed
python -m app --report out.csv --skip windows-update

python -m app.harness winget-upgrade --raw    # one source alone, raw and parsed
python -m app.harness parse upgrade.txt       # parse saved winget output
python -m app.harness drivers
python -m app.harness windows-update
python -m app.harness inventory               # every source merged, as text

python tools/preview.py --out preview.png
python tools/preview.py --theme light --show drivers --select "Realtek Audio" --out p.png
python tools/preview.py --all-themes --out-dir previews

python packaging/build.py                # dist/: folder, setup exe, latest.json
```

## The rules everything else follows from

**1. The UI thread never runs a program, reads the registry or touches a
file.** winget can sit for a minute on a source that is not answering, and a
Windows Update search can take several. All of it runs on the loader
(`core/loader.py`) with a timeout and a cancel; the window renders what comes
back. `tests/test_app.py` fails on `os`, `subprocess`, `shutil`, `pathlib`,
`winreg` or `open(` under `app/ui/` (the export writer, which runs on the
loader, is the one marked exception).

**2. Parsing and deciding are pure.** Everything in `core/` except
`loader.py`, `work.py`, `updates.py` and `instance.py` takes data and returns
data. That is the part Claude can prove.

**3. Nothing is deleted that is not provably disposable or picked by the
user, and nothing picked is deleted outright.** Cleanup locations come only
from `core/cleanup.TARGETS` and are dropped if they resolve somewhere
dangerous (`dangerous_root`); the space finder and leftover removal recycle,
and are re-checked in the worker (`may_recycle`, `safe_leftover`). Links are
never followed, network paths never touched. See SECURITY.md before changing
`io/files.py`, `io/elevated.py`, `core/cleanup.py` or `core/uninstall.py`.

**4. Everything that runs as administrator goes through `io/elevated.py`.**
The script is hash-checked by its bootstrap and carries its data inside it.
Never write a second elevated path.

**5. Nothing is installed without the user choosing it**, row by row or with
Update all, after a confirmation that lists exactly what will run and what
will not. There is no background updating.

**6. A source that did not answer is never shown as "up to date".**
`Sources` fields are None when a source failed; the rows it would have judged
are "Unknown", and the failure is in the notice bar and the log.

## Architecture

**`app/ui/`** -- the window. `window.py` (the frame, the Software section,
routing commands to the section that owns them), `cleanup.py` and
`security.py` (the other two sections; each answers `command_state`,
`run_command`, `handle_progress`, `handle_finished`), `dialogs.py`
(checklists before anything is removed), `model.py` (table
model and filter proxy), `commands.py` (every command, the menus, the
toolbar), and from File Compare verbatim or nearly: `chrome.py`,
`titlebar.py`, `winframe.py`, `glyphs.py` (Software Updater's glyphs added at
the end), `colour.py` (File Compare's `parse_colour` and `mono_font`).

**`app/core/`**

- `winget.py` -- parse winget's padded tables (display-cell columns, the
  ellipsis, the explicit-targeting second table, the spinner); build upgrade
  command lines; winget's result codes. Pure.
- `drivers.py` -- PnP devices from PowerShell's JSON, grouped by package
  (provider, INF, version); inbox detection; age. Pure.
- `winupdate.py` -- Windows Update offers and install results; HRESULTs in
  words. Pure.
- `versions.py` -- version comparison for matching and sorting. winget
  decides upgrades; this never second-guesses it. Pure.
- `inventory.py` -- the merge: registry entries tied to winget rows by name
  (prefix when winget truncated), upgrades by id, driver offers tied to
  installed packages by hardware id. Verdicts (`Status`) and update routes
  (`Action`). What the list shows (`visible`, `matches`, `counts`). Pure.
- `plan.py` -- chosen rows into winget steps, one Windows Update batch, and
  what is left out. Pure.
- `scan.py` -- every source at once on threads, each reported as it
  arrives, through a `Probe` passed in. Pure apart from the threads.
- `uninstall.py` (0.2) -- uninstall commands (winget, MSI `/X`, recorded
  strings split for ShellExecute), leftover candidates and the guards
  `safe_leftover`, `safe_key`, `runnable`. Pure.
- `cleanup.py` (0.2) -- the cleanup targets, `expand`, `allowed`,
  `dangerous_root`, `may_recycle`. Pure.
- `space.py` (0.2) -- the folder-size tree (depth-capped) and forgotten
  downloads. Pure.
- `security.py` (0.2) -- judges the security facts; Windows support dates
  (`SUPPORT`, from Microsoft's release health page, checked 2026-11-25 --
  add new versions as they ship). Pure.
- `devtools.py` (0.2) -- `py -0p`, `pip list --outdated`, `npm outdated -g`
  parsing and upgrade commands. Pure.
- `oem.py` -- which maker's tool belongs on this machine and where it
  installs. Pure.
- `report.py` -- CSV and a self-contained HTML report. Pure.
- `work.py` -- the scan and update jobs as loader functions, reporting
  progress as tuples (documented at the top of the file).
- `loader.py` -- File Compare's loader without the share processes, plus a
  `progress` signal and a cancel per job.
- `config.py`, `appearance.py`, `instance.py`, `updates.py` -- the family's.

**`app/io/`** -- every program run and registry read.

- `run.py` -- run a program with a deadline and a cancel, kill the whole tree,
  stream lines, no console window.
- `powershell.py` + `scripts.py` -- Windows PowerShell 5.1 by full path, the
  scripts sent with `-EncodedCommand` (execution policy does not apply), each
  writing one JSON object, failures as `{error, hresult}`.
- `wingetcli.py` -- find winget (PATH, then the WindowsApps alias), run it.
- `registry.py` -- the three Uninstall keys, filtered as Settings filters them.
- `probe.py` -- the real `Probe`.
- `elevate.py` -- ShellExecuteEx `runas` and wait, for Windows Update installs.
- `wuinstall.py` -- the elevated install's request and result files, in
  `%ProgramData%\SoftwareUpdater\jobs` so an over-the-shoulder administrator
  account can read and write them.
- `system.py` -- open a URL, a settings page or a tool; find maker tools;
  reveal in Explorer.
- `elevated.py` (0.2) -- the one way to run as administrator: hash-checked
  bootstrap, data inside the script, result file. `wuinstall.py` uses it.
- `files.py` (0.2) -- the only module that deletes: link-safe walks,
  age filters, Recycle Bin, network refusal.
- `cleaner.py` (0.2) -- measure and clean targets, the elevated cleanup
  batch, the space scan, Downloads.
- `uninstaller.py` (0.2) -- run an uninstaller, find and remove leftovers.
- `devtools.py` (0.2) -- find Pythons and npm, ask them what is outdated.

## How updating works, and why

- **winget, as the user, one package at a time.** `winget upgrade --id <id>
  --exact --accept-package-agreements --accept-source-agreements
  --disable-interactivity [--silent] [--include-unknown] [--source s]`. The
  application never elevates winget: a per-machine installer asks Windows for
  elevation itself, which shows the UAC prompt for that installer only.
  Packages in winget's "explicit targeting" table (pinned, or changing
  installer type) are marked "(pinned)" and are only updated when chosen,
  which `--id --exact` is.
- **Windows Update, elevated, in one batch.** The agent will not install for
  a standard token and does not prompt on its own, so the install script runs
  through `runas`: one prompt for every chosen driver and update. It searches
  again by update id (an update object cannot cross processes), accepts
  EULAs, downloads, installs, writes the result file.
- **`wu.server = "windows-update"` is the default.** On a managed machine the
  agent's default server is WSUS or Intune, which commonly approve no
  drivers; asking Microsoft's service directly is what Settings' "Check
  online" does. Policy can forbid it (`0x8024002E`), and that is shown.
- **Old drivers are a prompt, not a claim.** A third-party driver past
  `drivers.old_years` with nothing offered is "Old: check manufacturer", and
  its route is the maker's tool or page. Inbox (Microsoft) drivers are hidden
  unless something is offered for them.

## Look and feel

Copied from File Compare 1.26.0, which copied File Manager:

- `app/theme/` is **File Compare's, verbatim** -- tokens, the QSS template,
  the accent derivation, even the diff and syntax modules the sheet imports.
  A grey that changes there changes here. Add to it only what this
  application needs, at the bottom, under its own heading.
- **Three axes: theme, accent, density.** Default: Slate, Sky blue, normal --
  File Compare's 1.25 defaults. "Follow File Manager's look" reads File
  Manager's settings read-only.
- **The chrome is the family's**: custom title bar with the menu bar in it and
  the go box (here "Scan for updates F5"), the labelled one-row toolbar with a
  segmented control (here the View filter, with counts), the status line.
- **Status colours are semantic**: `warn` for update available or failed,
  `good` for up to date or updated, `txt_1` for old, `txt_2` for not tracked
  or unknown. Never the accent.
- **No literal colour outside `app/theme/`.** `tests/test_app.py` enforces it.
  `core/report.py` is the one named exception: a standalone HTML file meant
  for a browser or paper.

## Keys

```
Alt+1/2/3        Software, Cleanup, Security
Ctrl+Delete      uninstall selected
F5               scan again              Esc            stop
Ctrl+U           update selected         Ctrl+Shift+U   update everything available
Ctrl+A           select every update     Ctrl+C         copy winget command
Delete / Insert  ignore / show again     Ctrl+1..7      Updates, All, Apps, Drivers, Windows, Dev, Ignored
Ctrl+F           filter                  Ctrl+D         details panel
Ctrl+Shift+H     export report           F1             keys
```

## Conventions

The family's: Python 3.11+, type hints across module boundaries, a module
docstring saying why the file exists; envelopes from every worker call;
request ids on replies; new settings in `core/config.DEFAULTS` with a comment;
a setting somebody would change gets a menu item (Tools or View) and, if it
is a plain toggle, a row in `commands.TOGGLES`.

A ported file says at its top which version of which application it came
from, so a fix there can be carried here.

## Things that will bite you

- **winget's table is the only interface.** Column starts come from the
  header, counted in display cells. A localized winget falls back to column
  order. A new winget that changes the layout will show up as rows in the
  wrong columns; capture it (`winget upgrade --include-unknown > x.txt`) and
  add it to `tests/data/winget/`.
- **`winget upgrade` exit codes are HRESULTs**, unsigned on Windows.
  `0x8A15002B` (no applicable upgrade) is common for packages whose installed
  version winget reads differently from the source.
- **PowerShell 5.1 writes one object as an object.** Every script wraps its
  list in a top-level object (`{drivers: [...]}`) and `drivers.as_list`
  accepts either shape anyway.
- **`ShellExecuteEx` parameters are not a place for six kilobytes of base64.**
  The elevated install writes its script to a file and runs a two-line
  bootstrap that reads it into a scriptblock (`scripts.RUN_FILE`).
- **Constrained Language Mode** (AppLocker/WDAC) blocks `New-Object
  -ComObject`. The Windows Update stage then fails with a message, and the
  rest of the scan carries on.
- **`QSortFilterProxyModel.invalidateFilter` is deprecated in Qt 6.10+**;
  `FilterProxy.configure` uses `beginFilterChange`/`endFilterChange` when
  they exist.

## Packaging and releasing

The family's shape, ported from File Compare: PyInstaller folder build,
`packaging/entry.py` with `freeze_support()`, Inno Setup **per user** into
`%LOCALAPPDATA%\Programs\SoftwareUpdater` (no UAC for its own updates), App
Paths and PATH, `build.py` builds and the workflow publishes, never both;
output names without spaces; `core/updates.py` reads `latest.json` from this
repo's releases and verifies size and SHA-256. The AppId GUID in
`installer.iss` and `updates.APP_ID` is this application's own and must never
change. Bumping a version is three files: `app/__init__.py`, `pyproject.toml`,
`CHANGELOG.md`.

## Scope

Single user, local. No accounts, no telemetry, nothing about this machine is
sent anywhere by this application.

**Network use is the point here, so it is spelled out.** (0.2 adds pip and
npm, which talk to PyPI and the npm registry when asked what is outdated.) The application
itself makes one request: the update check for its own releases, as in the
other apps. Everything else goes through the tools it runs -- winget talks to
its sources, the Windows Update Agent to Microsoft or the managed server, and
installers download what they install. Those are the same requests those
tools make when run by hand. A new network call made by this application's
own code is a new decision, not an extension of these.

## Build order

0.1: scan, list, filter, ignore, update with winget and Windows Update,
maker's tool, export, `--report`, harness, preview.

0.2 (this): uninstall with leftovers, Cleanup, Find space, Security, pip and
npm, security review (SECURITY.md).

Candidates after the user has run 0.1 on the real machine:

- Dell Command Update's CLI (`dcu-cli /scan -report`) as a source, so Dell
  BIOS and firmware appear as rows rather than behind a button.
- A scheduled scan with a toast when something new needs updating.
- `winget pin` from the Ignore menu, so winget itself stops offering it.
- Store apps through `winget --source msstore` where the user's policy allows.
