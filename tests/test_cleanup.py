"""Cleanup targets, the space finder and the file helpers that delete."""

from __future__ import annotations

import os
import time

from app.core import cleanup, space
from app.io import files

ENV = {"TEMP": r"C:\Users\me\AppData\Local\Temp", "SystemRoot": r"C:\Windows",
       "LOCALAPPDATA": r"C:\Users\me\AppData\Local", "USERPROFILE": r"C:\Users\me",
       "ProgramData": r"C:\ProgramData"}


def test_expand_refuses_missing_variables_and_relative_results():
    assert cleanup.expand(r"%TEMP%", ENV) == r"C:\Users\me\AppData\Local\Temp"
    assert cleanup.expand(r"%NOPE%\x", ENV) is None
    assert cleanup.expand(r"%TEMP%", {"TEMP": "relative"}) is None
    assert cleanup.expand(r"%TEMP%", {"TEMP": r"\\server\share"}) is None


def test_allowed_is_only_cleanup_locations():
    assert cleanup.allowed(r"C:\Users\me\AppData\Local\Temp\x\y.tmp", ENV)
    assert cleanup.allowed(r"C:\Windows\Temp", ENV)
    assert not cleanup.allowed(r"C:\Windows", ENV)
    assert not cleanup.allowed(r"C:\Users\me\Documents", ENV)
    assert not cleanup.allowed(r"C:\Users\me\AppData\Local\TempX", ENV)


def test_targets_are_sane():
    ids = [t.id for t in cleanup.TARGETS]
    assert len(ids) == len(set(ids))
    for target in cleanup.TARGETS:
        assert target.group in cleanup.GROUPS
        if target.method == cleanup.Method.FILES:
            assert target.paths
    # What cannot be undone or costs a rebuild is never ticked for you.
    for ident in ("recycle-bin", "component-store", "nuget-packages", "gradle", "maven"):
        assert not cleanup.BY_ID[ident].default


def test_size_text():
    assert cleanup.size_text(None) == "--"
    assert cleanup.size_text(512) == "512 B"
    assert cleanup.size_text(5 * 1024 ** 3) == "5.0 GB"


def test_space_tree_adds_up_and_caps_depth():
    root = space.Node("me", r"C:\Users\me")
    space.add(root, ["a", "b"], 100)
    space.add(root, ["a"], 50)
    space.add(root, list("cdefghijk"), 7)
    assert root.size == 157 and root.files == 3
    assert root.children["a"].size == 150 and root.children["a"].children["b"].size == 100
    depth, node = 0, root.children["c"]
    while node.children:
        node = next(iter(node.children.values()))
        depth += 1
    assert depth == space.DEPTH - 1
    assert [n.name for n in root.sorted_children()] == ["a", "c"]


def test_forgotten_downloads():
    now = 1_800_000_000.0
    day = 86400
    found = space.forgotten([("big.iso", 2_000_000_000, now), ("old.zip", 50_000_000, now - 200 * day),
                             ("new.zip", 50_000_000, now - day), ("tiny.txt", 10, now - 900 * day)],
                            now=now)
    assert [f.path for f in found] == ["big.iso", "old.zip"]


def test_walk_never_follows_links(tmp_path):
    inside = tmp_path / "temp"
    outside = tmp_path / "precious"
    inside.mkdir()
    outside.mkdir()
    (outside / "keep.txt").write_text("x")
    (inside / "junk.tmp").write_text("y")
    try:
        os.symlink(outside, inside / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        return
    tally = files.delete_files(str(inside))
    assert tally.files == 1
    assert (outside / "keep.txt").exists()


def test_delete_respects_age(tmp_path):
    old = tmp_path / "old.tmp"
    new = tmp_path / "new.tmp"
    old.write_text("a")
    new.write_text("b")
    past = time.time() - 5 * 86400
    os.utime(old, (past, past))
    assert files.measure(str(tmp_path), days=1).files == 1
    files.delete_files(str(tmp_path), days=1)
    assert not old.exists() and new.exists()


FULL = {**ENV, "ProgramFiles": r"C:\Program Files", "APPDATA": r"C:\Users\me\AppData\Roaming",
        "SystemDrive": "C:"}


def test_a_misdirected_temp_is_never_cleaned():
    for bad in (r"C:\Users\me", r"C:\Users\me\Documents", r"C:\Users\me\Desktop", "C:\\",
                r"C:\Windows", r"C:\Users"):
        env = {**FULL, "TEMP": bad}
        assert cleanup.locations(cleanup.BY_ID["user-temp"], env) == [], bad
    env = {**FULL, "TEMP": r"C:\Users\me\AppData\Local\Temp"}
    assert cleanup.locations(cleanup.BY_ID["user-temp"], env) == [env["TEMP"]]


def test_recycle_refuses_system_and_profile_folders():
    for path in (r"C:\Windows", r"C:\Windows\Temp", r"C:\Program Files\App", r"C:\Users\me",
                 r"C:\Users\me\Documents", "C:\\", r"\\server\share\x", "relative"):
        assert cleanup.may_recycle(path, FULL), path
    for path in (r"C:\Users\me\Documents\old project", r"C:\Users\me\Downloads\big.iso",
                 r"D:\Backups\2019"):
        assert cleanup.may_recycle(path, FULL) == "", path
