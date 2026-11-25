"""winget's tables, parsed (core/winget.py)."""

from __future__ import annotations

from app.core import winget
from tests import sample


def test_upgrade_table_and_the_explicit_one():
    tables = winget.parse(sample.text("winget", "upgrade.txt"))
    assert len(tables) == 2
    assert [r.id for r in tables[0].rows] == [
        "Git.Git", "Microsoft.Edge", "Notepad++.Notepad++", "Microsoft.VCRedist.2015+.x64",
        "7zip.7zip", "Contoso.Memo"]
    assert not tables[0].explicit
    assert tables[1].explicit and tables[1].rows[0].id == "Zoom.Zoom"
    assert tables[1].rows[0].explicit


def test_spinner_before_the_header_is_ignored():
    git = winget.rows(sample.text("winget", "upgrade.txt"))[0]
    assert (git.name, git.version, git.available, git.source) == (
        "Git", "2.43.0", "2.47.1", "winget")


def test_names_with_spaces_and_brackets_stay_whole():
    rows = {r.id: r for r in winget.rows(sample.text("winget", "upgrade.txt"))}
    assert rows["Notepad++.Notepad++"].name == "Notepad++ (64-bit x64)"


def test_wide_characters_do_not_shift_columns():
    rows = {r.id: r for r in winget.rows(sample.text("winget", "upgrade.txt"))}
    memo = rows["Contoso.Memo"]
    assert memo.name == "メモ帳ツール"
    assert (memo.version, memo.available, memo.source) == ("1.0.0", "1.2.0", "winget")


def test_truncated_values_are_marked():
    rows = {r.id: r for r in winget.rows(sample.text("winget", "upgrade.txt"))}
    assert rows["Microsoft.Edge"].truncated
    assert rows["Microsoft.VCRedist.2015+.x64"].name.endswith(winget.ELLIPSIS)
    assert not rows["Git.Git"].truncated


def test_list_rows_without_a_source_are_not_tracked():
    rows = {r.id: r for r in winget.rows(sample.text("winget", "list.txt"))}
    assert rows["Python.Python.3.12"].tracked
    arp = next(r for r in rows.values() if r.id.startswith("ARP\\"))
    assert not arp.tracked and arp.version == "36.00.00"


def test_no_table_is_no_rows():
    assert winget.rows(sample.text("winget", "empty-upgrade.txt")) == []
    assert winget.rows("") == []


def test_non_english_headings_fall_back_to_position():
    text = ("Nom      ID       Version  Disponible Source\n"
            "---------------------------------------------\n"
            "Git      Git.Git  2.43.0   2.47.1     winget\n")
    row = winget.rows(text)[0]
    assert (row.id, row.available, row.source) == ("Git.Git", "2.47.1", "winget")


def test_upgrade_command():
    args = winget.upgrade_args("Git.Git", silent=True, unknown_version=True, source="winget")
    assert args[:4] == ["upgrade", "--id", "Git.Git", "--exact"]
    assert "--accept-package-agreements" in args and "--accept-source-agreements" in args
    assert "--silent" in args and "--include-unknown" in args
    assert args[args.index("--source") + 1] == "winget"
    assert "--silent" not in winget.upgrade_args("X", silent=False)


def test_result_codes():
    assert winget.succeeded(0)
    assert winget.succeeded(0x8A150109)
    assert not winget.succeeded(0x8A15002B)
    assert "no applicable upgrade" in winget.explain(0x8A15002B)
    assert winget.explain(0x80070005) == "winget returned 0x80070005."
    # A signed exit code reads the same as the unsigned one.
    assert winget.explain(0x8A15002B - (1 << 32)) == winget.explain(0x8A15002B)
