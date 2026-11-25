"""The command line, parsed before Qt is imported.

    SoftwareUpdater.exe                    the window, which scans on opening
    SoftwareUpdater.exe --no-scan          the window, without the first scan
    SoftwareUpdater.exe --report out.html  no window: scan, write, exit
    SoftwareUpdater.exe --report out.csv --skip windows-update

`--report` exits 0 when nothing needs updating, 1 when something does, and 2
when the scan could not run -- so a scheduled task can act on the answer.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

SKIPPABLE = ("winget", "drivers", "windows-update")


@dataclass
class Request:
    report: str = ""
    no_scan: bool = False
    skip: list[str] = field(default_factory=list)


def parse(argv: list[str]) -> Request:
    parser = argparse.ArgumentParser(prog="SoftwareUpdater", add_help=True)
    parser.add_argument("--report", default="", help="scan, write an .html or .csv, exit")
    parser.add_argument("--no-scan", action="store_true", help="open without scanning")
    parser.add_argument("--skip", action="append", default=[], choices=SKIPPABLE,
                        help="leave a source out of this scan")
    args, _unknown = parser.parse_known_args(argv)
    return Request(report=args.report, no_scan=args.no_scan, skip=list(args.skip))
