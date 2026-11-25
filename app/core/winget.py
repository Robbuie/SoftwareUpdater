"""Reading what winget prints, and writing what winget is asked to do.

winget has no machine-readable output for `list` or `upgrade`. It prints a
table padded to fixed columns, and that table is what every tool built on it
parses -- so this does too, carefully, and the rules it follows are written
down here because each one was a way the obvious parse goes wrong:

- **Columns come from the header.** Each heading starts a column; a value is
  the text between one column's start and the next. Values are never split
  on spaces, because names have spaces ("Microsoft Visual C++ 2015-2022
  Redistributable") and so, sometimes, do versions.
- **Columns are counted in display cells, not characters.** winget pads by
  how wide a string looks in a console. A Japanese or Chinese name takes two
  cells per character, so slicing by characters shifts every column after it
  on that row.
- **Long values are cut with an ellipsis.** "131.0.2903.…" is not a version
  to compare; it is kept as written, marked `truncated`, and the upgrade is
  still winget's to decide.
- **There can be more than one table.** `upgrade` prints a second table of
  packages that "require explicit targeting" (pinned, or with a different
  installer technology). Those are real upgrades that `upgrade --all` skips,
  and they are marked `explicit`.
- **The progress spinner is in the same stream.** A line can carry
  `\\r - \\r \\\\ \\r` before the real text; only what follows the last `\\r` counts.

Headings are English. winget translates them in other display languages;
when the known names are not found, the order Name, Id, Version, [Available],
Source is assumed, which is the order every language uses.

Pure, and covered by `tests/test_winget.py` against captured output.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

ELLIPSIS = "…"


@dataclass
class Row:
    name: str
    id: str
    version: str
    available: str = ""
    source: str = ""
    #: In the second table of `winget upgrade`: an upgrade `--all` leaves out.
    explicit: bool = False

    @property
    def truncated(self) -> bool:
        return any(v.endswith(ELLIPSIS) for v in (self.name, self.id, self.version,
                                                    self.available))

    @property
    def tracked(self) -> bool:
        """Known to a winget source, so winget can upgrade it. A row with no
        source is something winget found installed but cannot match to a
        package (its id is then `ARP\\...` or `MSIX\\...`)."""
        return bool(self.source)


@dataclass
class Table:
    rows: list[Row] = field(default_factory=list)
    explicit: bool = False


def width(text: str) -> int:
    """Display cells taken by `text` in a console."""
    total = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def cut(text: str, start: int, stop: int | None) -> str:
    """The characters of `text` occupying display cells [start, stop)."""
    out: list[str] = []
    cell = 0
    for ch in text:
        w = 0 if unicodedata.combining(ch) else (
            2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1)
        if cell >= start and (stop is None or cell < stop):
            out.append(ch)
        cell += w
        if stop is not None and cell >= stop:
            break
    return "".join(out).strip()


def clean_lines(text: str) -> list[str]:
    """Lines as a console would have left them: the spinner and progress bar
    overwritten by whatever followed the last carriage return."""
    lines = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if "\r" in raw:
            raw = raw.rsplit("\r", 1)[-1]
        lines.append(raw.rstrip())
    return lines


def _is_rule(line: str) -> bool:
    stripped = line.strip()
    return len(stripped) >= 10 and set(stripped) <= {"-", "─"}


_NAMES = {
    "name": "name", "id": "id", "version": "version", "available": "available",
    "source": "source", "match": "match",
}


def _columns(header: str) -> list[tuple[str, int]]:
    """(field, start cell) for each heading."""
    starts: list[tuple[str, int]] = []
    cell = 0
    previous_space = True
    word = ""
    word_start = 0
    for ch in header + " ":
        if ch == " ":
            if word:
                starts.append((word, word_start))
                word = ""
            previous_space = True
        else:
            if previous_space:
                word_start = cell
            word += ch
            previous_space = False
        cell += width(ch) if ch != " " else 1
    known = [(_NAMES.get(w.lower(), ""), s) for w, s in starts]
    if all(name for name, _ in known):
        return known
    # Not English: assume the order every translation keeps.
    order = {3: ("name", "id", "version"),
             4: ("name", "id", "version", "source"),
             5: ("name", "id", "version", "available", "source")}.get(len(starts))
    if order is None:
        return []
    return [(name, s) for name, (_, s) in zip(order, starts)]


def parse(text: str) -> list[Table]:
    """Every table in one run of `winget list` or `winget upgrade`."""
    lines = clean_lines(text)
    tables: list[Table] = []
    i = 0
    explicit_next = False
    while i < len(lines):
        line = lines[i]
        lowered = line.lower()
        if "explicit targeting" in lowered or "require explicit" in lowered:
            explicit_next = True
        if i + 1 < len(lines) and _is_rule(lines[i + 1]) and line.strip():
            columns = _columns(line)
            i += 2
            if not columns:
                continue
            table = Table(explicit=explicit_next)
            explicit_next = False
            while i < len(lines) and lines[i].strip():
                row = _row(lines[i], columns)
                if row is None:
                    break
                row.explicit = table.explicit
                table.rows.append(row)
                i += 1
            tables.append(table)
            continue
        i += 1
    return tables


def _row(line: str, columns: list[tuple[str, int]]) -> Row | None:
    values: dict[str, str] = {}
    for index, (name, start) in enumerate(columns):
        stop = columns[index + 1][1] if index + 1 < len(columns) else None
        values[name] = cut(line, start, stop)
    ident = values.get("id", "")
    # The summary line under a table ("3 upgrades available.") fills the name
    # column and nothing else.
    if not ident or " " in ident or not values.get("name"):
        return None
    return Row(name=values.get("name", ""), id=ident, version=values.get("version", ""),
               available=values.get("available", ""), source=values.get("source", ""))


def rows(text: str) -> list[Row]:
    return [row for table in parse(text) for row in table.rows]


# --------------------------------------------------------------------------
# Commands. Built here so the tests can see exactly what will be run.
# --------------------------------------------------------------------------

COMMON = ["--accept-source-agreements", "--disable-interactivity"]


def list_args() -> list[str]:
    return ["list", *COMMON]


def upgrade_list_args(include_unknown: bool = True) -> list[str]:
    args = ["upgrade", *COMMON]
    if include_unknown:
        args.append("--include-unknown")
    return args


def upgrade_args(package_id: str, *, silent: bool = True, unknown_version: bool = False,
                 source: str = "") -> list[str]:
    """One package, by exact id, agreeing to its licence so the run does not
    stop at a prompt nobody can see."""
    args = ["upgrade", "--id", package_id, "--exact",
            "--accept-package-agreements", *COMMON]
    if source:
        args += ["--source", source]
    if silent:
        args.append("--silent")
    if unknown_version:
        # Without this winget says there is nothing to upgrade for a package
        # whose installed version it cannot read.
        args.append("--include-unknown")
    return args


#: winget's own result codes that read better in words. The rest are shown as
#: hex with the last thing winget printed, which is usually the explanation.
RESULTS: dict[int, str] = {
    0x8A150014: "No installed package matched that id.",
    0x8A15002B: "winget found no applicable upgrade for this package.",
    0x8A150101: "The program is running. Close it and try again.",
    0x8A150102: "Another installation is in progress. Try again when it finishes.",
    0x8A150109: "Installed; restart Windows to finish.",
}

#: Codes that mean the upgrade went in.
SUCCESS = frozenset({0, 0x8A150109})


def explain(code: int) -> str:
    code &= 0xFFFFFFFF
    if code == 0:
        return "Updated."
    return RESULTS.get(code, f"winget returned 0x{code:08X}.")


def succeeded(code: int) -> bool:
    return (code & 0xFFFFFFFF) in SUCCESS
