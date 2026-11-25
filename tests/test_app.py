"""The window, offscreen, over the fixture machine; the command table; the
settings; and the family rule about colour literals."""

from __future__ import annotations

import os
import re

import pytest

from app.core.config import DEFAULTS, Config
from app.ui import commands

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_every_menu_item_is_a_command_and_every_toggle_a_setting():
    for _title, items in commands.MENUS:
        for item in items:
            if item == "-":
                continue
            if item.startswith(">"):
                assert item[1:] in commands.DYNAMIC
            else:
                assert item in commands.COMMANDS
    for group in commands.TOOLBARS["main"]:
        for item in group:
            assert item in commands.MARKERS or item in commands.COMMANDS
    for key in commands.TOGGLES.values():
        assert key in DEFAULTS


def test_unknown_setting_raises(tmp_path):
    config = Config(path=str(tmp_path / "c.json"))
    with pytest.raises(KeyError):
        config.get("no.such")
    config.set("view.show", "all")
    assert config.save()
    assert Config.load(str(tmp_path / "c.json")).get("view.show") == "all"


def test_no_colour_literal_outside_theme():
    """File Manager's rule: a hex colour in a widget stops following the
    theme. `core/report.py` is the named exception -- a standalone file read
    on paper, not in the window."""
    pattern = re.compile(r"#[0-9a-fA-F]{6}\b|rgba?\(\s*\d")
    offenders = []
    for folder, _dirs, files in os.walk(os.path.join(ROOT, "app")):
        if os.sep + "theme" in folder or "__pycache__" in folder:
            continue
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            if path.endswith(os.path.join("core", "report.py")):
                continue
            with open(path, encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    if pattern.search(line) and "noqa: colour" not in line:
                        offenders.append(f"{path}:{number}")
    assert not offenders


def test_ui_never_imports_the_filesystem_or_subprocess():
    """The rule everything follows from, as in File Manager: the window
    asks a worker and renders what comes back."""
    banned = re.compile(r"^\s*(import (os|subprocess|shutil|pathlib|winreg)\b|"
                        r"from (os|subprocess|shutil|pathlib) import)|\bopen\(")
    for name in os.listdir(os.path.join(ROOT, "app", "ui")):
        if not name.endswith(".py") or name == "winframe.py":
            continue
        with open(os.path.join(ROOT, "app", "ui", name), encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if "def write(" in line or "with open(where" in line:
                    continue  # runs on the loader, see MainWindow.export
                assert not banned.search(line), f"{name}:{number}: {line.strip()}"


def select_first(window):
    from app.ui.window import ROW_SELECT

    window.view.selectionModel().clearSelection()
    window.view.selectionModel().select(
        window.proxy.index(0, 0), ROW_SELECT)


@pytest.fixture
def window(qt_app, tmp_path):
    if qt_app is None:
        pytest.skip("Qt not installed")
    from app.ui.window import MainWindow
    from tests import sample

    config = Config({"scan.on_launch": False, "updates.check_on_launch": False},
                    path=str(tmp_path / "config.json"))
    win = MainWindow(config, look={"theme": "slate", "accent": "sky", "density": "normal"},
                     look_source="own")
    win._scan_finished(sample.scan())
    yield win
    win._loader.shutdown()
    win.deleteLater()


def test_window_shows_updates_first(window):
    from app.core.inventory import Status
    from app.ui.model import ItemRole

    rows = [window.proxy.data(window.proxy.index(r, 0), ItemRole)
            for r in range(window.proxy.rowCount())]
    assert rows and all(i.status in (Status.UPDATE, Status.OLD) for i in rows)
    assert window.command_state("update-all").count >= 8


def test_show_filters_and_counts(window):
    window.run_command("show-all")
    everything = window.proxy.rowCount()
    window.run_command("show-drivers")
    assert 0 < window.proxy.rowCount() < everything
    window.filter.setText("Realtek")
    assert window.proxy.rowCount() == 1
    window.filter.setText("")


def test_ignore_hides_and_show_again_returns(window):
    window.run_command("show-all")
    before = window.proxy.rowCount()
    select_first(window)
    window.run_command("ignore")
    assert window.proxy.rowCount() == before - 1
    window.run_command("show-ignored")
    assert window.proxy.rowCount() == 1
    select_first(window)
    window.run_command("unignore")
    assert window.proxy.rowCount() == 0


def test_details_text(window):
    from app.ui.window import describe

    item = window.model.item("winget:Git.Git")
    text = describe(item)
    assert "winget id" in text and "Ctrl+U" in text


def test_update_events_mark_rows(window):
    window.model.busy["winget:Git.Git"] = "Waiting"
    window._update_event(("start", "winget:Git.Git", "Git"))
    window._update_event(("done", "winget:Git.Git", True, "Updated."))
    from app.core.inventory import Status

    assert window.model.item("winget:Git.Git").status == Status.DONE
    assert "winget:Git.Git" not in window.model.busy


def test_every_look_applies(window):
    from app.theme.tokens import THEMES

    for theme in THEMES:
        window.apply_look({"theme": theme, "accent": "blue", "density": "compact"}, "own")
    assert window._tokens["theme_name"] == list(THEMES)[-1]


def test_select_updates_selects_only_updatable(window):
    window.run_command("show-all")
    window.run_command("select-updates")
    chosen = window.selected()
    assert chosen and all(i.updatable for i in chosen)
    assert window.command_state("update-selected").count == len(chosen)
    # A rebuild (the next scan stage) keeps the selection.
    from tests import sample

    window._rebuild(sample.scan())
    assert len(window.selected()) == len(chosen)
