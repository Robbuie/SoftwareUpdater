"""Version comparison (core/versions.py)."""

from __future__ import annotations

import pytest

from app.core import versions


@pytest.mark.parametrize("left, right, expected", [
    ("1.2.3", "1.2.3", 0),
    ("1.2", "1.2.0.0", 0),
    ("1.10", "1.9", 1),
    ("2.43.0", "2.47.1", -1),
    ("v5", "5.0", 0),
    ("1.2.1", "1.2", 1),
    ("1.2rc1", "1.2", -1),
    ("1.0.beta", "1.0.0", -1),
    ("10.0.22621.3155", "10.0.22621.2506", 1),
    ("2.43.0.windows.1", "2.43.0.windows.2", -1),
])
def test_compare(left, right, expected):
    assert versions.compare(left, right) == expected


@pytest.mark.parametrize("value", ["", "Unknown", "< 1.4", None, "-"])
def test_unknown(value):
    assert not versions.is_known(value)
    assert versions.compare(value, "1.0") is None


def test_sort_key_puts_unknowns_last():
    values = ["Unknown", "1.10", "1.9", ""]
    assert sorted(values, key=versions.sort_key)[:2] == ["1.9", "1.10"]
