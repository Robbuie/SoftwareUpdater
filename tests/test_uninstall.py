"""Uninstall commands and the leftover guard (core/uninstall.py)."""

from __future__ import annotations

import pytest

from app.core import uninstall as u

ROOTS = {
    "ProgramFiles": r"C:\Program Files",
    "ProgramFiles(x86)": r"C:\Program Files (x86)",
    "ProgramData": r"C:\ProgramData",
    "APPDATA": r"C:\Users\me\AppData\Roaming",
    "LOCALAPPDATA": r"C:\Users\me\AppData\Local",
}


@pytest.mark.parametrize("line, exe, params", [
    ('"C:\\Program Files\\App\\uninst.exe" /S', r"C:\Program Files\App\uninst.exe", "/S"),
    (r"C:\Program Files\App\unins000.exe /SILENT", r"C:\Program Files\App\unins000.exe",
     "/SILENT"),
    (r"C:\Program Files\App\uninstall.exe", r"C:\Program Files\App\uninstall.exe", ""),
    ("MsiExec.exe /X{11111111-2222-3333-4444-555555555555}", "MsiExec.exe",
     "/X{11111111-2222-3333-4444-555555555555}"),
    ("", "", ""),
])
def test_split_command(line, exe, params):
    assert u.split_command(line) == (exe, params)


def test_msi_repair_becomes_remove():
    command = u.command_for(uninstall="MsiExec.exe /I{11111111-2222-3333-4444-555555555555}")
    assert command.executable == "msiexec.exe"
    assert command.parameters.startswith("/X{11111111-2222-3333-4444-555555555555}")
    assert "/passive" in command.parameters


def test_winget_preferred_and_quiet_string_used():
    w = u.command_for(winget_id="Git.Git", source="winget", uninstall="x.exe")
    assert w.winget_id == "Git.Git" and w.args[:3] == ["uninstall", "--id", "Git.Git"]
    assert "--silent" in w.args and "--source" in w.args
    q = u.command_for(quiet='"C:\\A\\u.exe" /S', uninstall='"C:\\A\\u.exe"')
    assert q.parameters == "/S"
    loud = u.command_for(quiet='"C:\\A\\u.exe" /S', uninstall='"C:\\A\\u.exe"', silent=False)
    assert loud.parameters == ""
    assert u.command_for() is None


@pytest.mark.parametrize("path, ok", [
    (r"C:\Program Files\Notepad++", True),
    (r"C:\Program Files\Rockwell Automation\Studio 5000", True),
    (r"C:\Users\me\AppData\Roaming\Notepad++", True),
    # Never a root, never above one, never outside, never a share.
    (r"C:\Program Files", False),
    (r"C:\Users\me\AppData\Roaming", False),
    (r"C:\Users\me", False),
    (r"C:\Windows\System32", False),
    (r"D:\Notepad++", False),
    (r"\\server\share\Notepad++", False),
    (r"C:\Program Files\..\Windows", False),
    # Shared folders and publisher folders on their own.
    (r"C:\Program Files\Common Files", False),
    (r"C:\Program Files\Microsoft", False),
    (r"C:\Program Files\Rockwell Automation", False),
    # A folder sharing no word with the program.
    (r"C:\Program Files\SomethingElse", False),
])
def test_safe_leftover(path, ok):
    names = {r"C:\Program Files\Rockwell Automation\Studio 5000":
             "Rockwell Automation Studio 5000 Logix Designer"}
    name = names.get(path, "Notepad++ (64-bit x64)")
    if "Rockwell Automation" == path.rsplit("\\", 1)[-1]:
        name = "Studio 5000 Logix Designer"
    assert u.safe_leftover(path, name=name, publisher="", roots=ROOTS) is ok


def test_candidates_skip_folders_holding_other_programs():
    found = u.candidates(name="Microsoft Office Visio", publisher="Microsoft Corporation",
                         location=r"C:\Program Files\Microsoft Office", roots=ROOTS,
                         others=[r"C:\Program Files\Microsoft Office\root\Office16"])
    assert all(not p.lower().endswith("microsoft office") for p, _why in found)


def test_candidates_include_appdata_and_install_folder():
    found = dict(u.candidates(name="Notepad++ (64-bit x64)", publisher="Notepad++ Team",
                              location=r"C:\Program Files\Notepad++", roots=ROOTS))
    assert r"C:\Program Files\Notepad++" in found
    assert r"C:\Users\me\AppData\Roaming\Notepad++" in found


def test_registry_keys_only_the_users_own_and_named():
    keys = u.registry_candidates(name="7-Zip 23.01 (x64)", publisher="Igor Pavlov")
    assert keys[0] == r"Software\7-Zip"
    assert u.safe_key(r"Software\7-Zip", name="7-Zip 23.01 (x64)")
    assert not u.safe_key(r"Software\Microsoft\7-Zip", name="7-Zip")
    assert not u.safe_key(r"Software", name="7-Zip")
    assert not u.safe_key(r"System\7-Zip", name="7-Zip")


def test_only_full_paths_or_windows_tools_run():
    assert u.runnable(r"C:\Program Files\App\unins000.exe")
    assert u.runnable("MsiExec.exe")
    assert not u.runnable("uninstall.exe")          # would be searched for
    assert not u.runnable(r"\\server\share\u.exe")
