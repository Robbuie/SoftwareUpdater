# Security review -- Software Updater 0.2.0

Reviewed 2026-11-25, alongside the 0.2.0 build. This covers what the
application itself could be made to do wrong. The Security *page*, which
checks the computer, is described in `app/core/security.py`.

## What it is trusted with

Software Updater runs as the signed-in user and is installed per user. It
can, when asked:

- run installers and uninstallers (winget, MSI, programs' own);
- run PowerShell **as administrator**, after a UAC prompt, for Windows
  Update installs, system-folder cleanup, DISM and Defender updates;
- delete files in temp and cache folders, send folders to the Recycle Bin,
  and delete a program's own registry key under HKCU;
- download and run a new version of itself.

So the questions are: can someone else make it run their code as
administrator, can it be made to delete the wrong thing, and can its own
update be replaced?

## Findings and what was done

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| 1 | **Elevated script could be swapped (0.1.0).** The Windows Update installer wrote its script and request to `%ProgramData%\SoftwareUpdater\jobs`, then ran them as administrator. Any local user can create that folder first and own it, then replace the script between the write and the run, getting their code run as administrator. | High | **Fixed.** `io/elevated.py`: the bootstrap carries the script's SHA-256 inside its `-EncodedCommand`, reads the file once, checks those bytes and runs those bytes. All data is written into the script before hashing; there is no separate request file. A changed script stops with nothing done. |
| 2 | **Elevated result file could be redirected.** Swapping the jobs folder for a junction could make the administrator's PowerShell write its result JSON into another folder. | Low | **Fixed.** The app refuses a jobs folder that is a link, and the elevated script will not write through a link or over an existing file. |
| 3 | **A misdirected `TEMP` would delete your files.** "Your temporary files" deletes files older than a day under `%TEMP%`. If `TEMP` pointed at your profile, Documents or a drive root, that would mean your own files. | High (data loss) | **Fixed.** `core/cleanup.dangerous_root` drops any cleanup location that resolves to a drive root, a key Windows folder, the profile or a folder directly in it. Tested with each case. |
| 4 | **The space finder could recycle system folders.** Selecting `Windows` or a `Program Files` folder in the tree and pressing Recycle would have tried, and partly succeeded. | Medium (data loss) | **Fixed.** `core/cleanup.may_recycle`, checked in the worker rather than the window: no drive roots, nothing in Windows, Program Files or ProgramData, no profile or known folders themselves. |
| 5 | **Uninstall strings are not trusted input.** Uninstall entries under HKCU can be written by any program running as you. | Medium | **Mitigated.** Uninstallers run as you through ShellExecute; this app never elevates them (their own UAC prompt shows if they need rights). A command with no full path is refused, since it would be searched for in the current folder; `msiexec`/`rundll32` are run from System32 by full path. MSI "repair" (`/I`) is rewritten to remove (`/X`). |
| 6 | **Leftover removal could reach shared folders.** "Microsoft Office" left by Visio holds Word. | Medium (data loss) | **Fixed by design.** A leftover must be strictly inside Program Files, ProgramData or AppData, at least one level down, share a real word with the program's name, not be a shared folder (`Common Files`, `Microsoft`...), not be a link, and not contain another installed program's folder. It is re-checked in the worker, shown to you with a box per row, and goes to the Recycle Bin. Registry keys: HKCU `Software\<program>` only, exported to a `.reg` backup first. |
| 7 | **System programs found by search order.** `reg.exe`, `taskkill`, `explorer.exe` were run by bare name. | Low | **Fixed.** Run from `%SystemRoot%` by full path. PowerShell already was. |
| 8 | **Command and script injection.** Package ids, names and paths reach winget, pip, npm and PowerShell. | -- | **No issue found.** Programs get argument lists, not shell strings. winget ids with spaces are rejected by the parser. Every value put into PowerShell goes through `scripts.quote` (single-quoted, quote doubled) or `scripts.embed` (JSON in a quoted string), with tests. |
| 9 | **Following links while deleting.** A junction inside a temp folder could point at your documents. | -- | **No issue found.** `io/files` never descends into or deletes a reparse point (`follow_symlinks=False` and the reparse attribute both checked), in Python and in the elevated PowerShell. Tested with a link. |
| 10 | **Network locations.** Company policy forbids writing to network servers. | -- | **No issue found.** UNC paths and remote drive letters are refused by every measure, delete, recycle and scan. |
| 11 | **Secrets.** The Security page checks automatic sign-in. | -- | **No issue found.** It asks only whether a stored password *exists*; the value is never read. A test pins this. |
| 12 | **Self-update authenticity.** Updates come from this repo's GitHub releases; size and SHA-256 are checked against `latest.json`, and only URLs inside the repo's releases are accepted. | Medium | **Accepted, documented.** This proves the download is intact, not who built it: someone who could publish a release on the repo could ship anything. The installer is unsigned. Code signing is the fix if this is used on machines other than yours. |

## What remains true by design

- **Administrator actions always show a UAC prompt.** Nothing runs elevated
  without one, and the prompt is for Windows PowerShell, launched by this
  app, for the action you just confirmed.
- **Security settings are never changed by the app.** The Security page's
  Fix opens the Windows page for the setting; the only action it runs is
  Defender's definition update.
- **pip and npm packages are never in Update all.** Each is ticked by hand.
- **Deletes that cannot be undone are off by default** (Recycle Bin, DISM,
  build caches) and the confirmation lists every kind with its size.

## How to check it again

`pytest` runs the guards in `tests/test_cleanup.py`, `tests/test_uninstall.py`,
`tests/test_scan.py` (elevated bootstrap and script data) and
`tests/test_app.py` (no filesystem or process calls in `app/ui/`, no colour
literals). Any change to `io/elevated.py`, `io/files.py`,
`core/uninstall.py` or `core/cleanup.py` should be read against this file.
