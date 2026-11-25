"""Comparing version strings the way the people who write them mean them.

Installed programs report versions in every shape there is: "1.2.3",
"24.08", "2.43.0.windows.1", "10.0.22621.3155", "v5", "< 1.4", "Unknown".
winget already decides "is there an upgrade" for what it tracks, so this is
not used to second-guess it. It is used where nothing else decides: matching
a registry entry to winget's row by version, ordering a column, and saying
which of two driver versions is newer.

Pure, and covered by `tests/test_versions.py`.
"""

from __future__ import annotations

import re

_PART = re.compile(r"\d+|[A-Za-z]+")

#: What winget and the registry write when they do not know.
UNKNOWN = frozenset({"", "unknown", "n/a", "-", "?"})


def is_known(value: str | None) -> bool:
    if value is None:
        return False
    text = value.strip().lower()
    return text not in UNKNOWN and not text.startswith("<")


def parts(value: str) -> list[tuple[int, int | str]]:
    """Split into comparable pieces. Numbers compare as numbers, words as
    lower-case text, and a number always sorts after a word in the same
    place, so "1.0.beta" < "1.0.0"."""
    text = value.strip().lstrip("vV")
    out: list[tuple[int, int | str]] = []
    for match in _PART.finditer(text):
        token = match.group(0)
        if token.isdigit():
            out.append((1, int(token)))
        else:
            out.append((0, token.lower()))
    return out


def compare(left: str | None, right: str | None) -> int | None:
    """-1, 0 or 1; None when either side is not a version at all.

    Trailing zeros do not count: "1.2" and "1.2.0.0" are the same release.
    """
    if not is_known(left) or not is_known(right):
        return None
    a, b = parts(left or ""), parts(right or "")
    if not a or not b:
        return None
    # The shorter is padded with zeros, so trailing zeros do not count
    # ("1.2" == "1.2.0.0") and a word where the other has a number is a
    # pre-release ("1.2rc1" < "1.2", "1.0.beta" < "1.0.0").
    size = max(len(a), len(b))
    a += [(1, 0)] * (size - len(a))
    b += [(1, 0)] * (size - len(b))
    for x, y in zip(a, b):
        if x != y:
            return -1 if x < y else 1
    return 0


def newer(candidate: str | None, current: str | None) -> bool:
    return compare(candidate, current) == 1


def sort_key(value: str | None) -> tuple:
    """A key for sorting a column of versions, unknowns last."""
    if not is_known(value):
        return (1, ())
    return (0, tuple(parts(value or "")))
