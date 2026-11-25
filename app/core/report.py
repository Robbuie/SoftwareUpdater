"""The scan as a file: CSV for a spreadsheet, HTML to read or send. Pure.

Written by the window's Export command and by `--report` on the command line.
The HTML is self-contained -- no script, no external stylesheet -- and its
colours are its own, chosen for paper, not the window's theme: a report is
read in a browser or printed, where the theme means nothing.
"""

from __future__ import annotations

import csv
import html
import io
import time

from app.core.inventory import KIND_LABELS, STATUS_LABELS, STATUS_ORDER, Item

COLUMNS = ("Name", "Kind", "Installed", "Available", "Status", "Source", "Publisher",
           "winget id")


def _row(item: Item) -> list[str]:
    return [item.name, KIND_LABELS.get(item.kind, item.kind), item.installed, item.available,
            STATUS_LABELS.get(item.status, item.status), item.source, item.publisher,
            item.winget_id]


def ordered(items: list[Item]) -> list[Item]:
    return sorted(items, key=lambda i: (STATUS_ORDER.get(i.status, 9), i.kind, i.name.lower()))


def to_csv(items: list[Item]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    for item in ordered(items):
        writer.writerow(_row(item))
    return buffer.getvalue()


# Report colours: print-friendly constants for a standalone file, not theme
# tokens. Kept here, named, so the "no literal colour outside app/theme" test
# can name this file as the one exception.
_STYLE = """
body { font: 13px "Segoe UI", sans-serif; color: #1d2128; margin: 24px; }
h1 { font-size: 18px; margin: 0 0 4px 0; }
p.meta { color: #5c6470; margin: 0 0 16px 0; }
table { border-collapse: collapse; width: 100%; }
th { text-align: left; color: #5c6470; font-weight: 600; border-bottom: 1px solid #d7dbe2;
     padding: 4px 8px; }
td { padding: 4px 8px; border-bottom: 1px solid #eceef2; vertical-align: top; }
tr.update td.status, tr.failed td.status { color: #b26a00; font-weight: 600; }
tr.old td.status { color: #8a5a00; }
tr.current td.status, tr.done td.status { color: #1e7f4f; }
td.v { font-family: Consolas, monospace; }
"""


def to_html(items: list[Item], *, machine: str = "", errors: dict[str, str] | None = None,
            when: float | None = None) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(when or time.time()))
    counts: dict[str, int] = {}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    summary = ", ".join(f"{n} {STATUS_LABELS.get(s, s).lower()}"
                        for s, n in sorted(counts.items(), key=lambda kv: STATUS_ORDER.get(kv[0], 9)))
    parts = ["<!DOCTYPE html><html><head><meta charset='utf-8'>",
             "<title>Software Updater report</title><style>", _STYLE, "</style></head><body>",
             "<h1>Software Updater report</h1>",
             f"<p class='meta'>{html.escape(machine)}{' &middot; ' if machine else ''}"
             f"{html.escape(stamp)} &middot; {html.escape(summary)}</p>"]
    for stage, error in (errors or {}).items():
        parts.append(f"<p class='meta'>{html.escape(stage)}: {html.escape(error)}</p>")
    parts.append("<table><tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in COLUMNS) + "</tr>")
    for item in ordered(items):
        cells = _row(item)
        tds = []
        for index, value in enumerate(cells):
            cls = " class='status'" if index == 4 else (" class='v'" if index in (2, 3, 7) else "")
            tds.append(f"<td{cls}>{html.escape(value)}</td>")
        parts.append(f"<tr class='{html.escape(item.status)}'>" + "".join(tds) + "</tr>")
    parts.append("</table></body></html>")
    return "".join(parts)
