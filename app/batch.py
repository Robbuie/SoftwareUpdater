"""`--report`: one scan with no window, written to a file, and an exit code.

Exit 0: nothing to update. 1: something has an update available, or a
driver is old. 2: the scan could not run, or the report could not be written.
"""

from __future__ import annotations

import datetime as _dt
import sys

from app.cli import Request
from app.core import inventory, oem, report
from app.core.config import Config, scan_options
from app.core.scan import STAGE_LABELS, run


def main(request: Request, config: Config) -> int:
    from app.io.probe import Probe

    options = scan_options(config)
    if "winget" in request.skip:
        options.winget = False
    if "drivers" in request.skip:
        options.drivers = False
    if "windows-update" in request.skip:
        options.windows_update = False

    def say(stage, scan) -> None:
        error = scan.errors.get(stage)
        print(f"{STAGE_LABELS.get(stage, stage)}: {error or 'done'}", file=sys.stderr)

    try:
        scan = run(Probe(), options, report=say)
    except Exception as exc:  # noqa: BLE001 - an exit code, not a traceback
        print(f"scan failed: {exc}", file=sys.stderr)
        return 2
    manufacturer = str(scan.system.get("manufacturer") or "")
    items = inventory.build(scan.sources, today=_dt.date.today(),
                            old_years=float(config.get("drivers.old_years")),
                            include_inbox=bool(config.get("drivers.include_inbox")),
                            vendor_url=oem.support_url(manufacturer))
    ignored = set(config.get("ignore.items"))
    items = [i for i in items if i.key not in ignored]
    if request.report.lower().endswith(".csv"):
        text = report.to_csv(items)
    else:
        machine = " ".join(str(scan.system.get(k) or "") for k in ("manufacturer", "model"))
        text = report.to_html(items, machine=machine.strip(), errors=scan.errors)
    try:
        with open(request.report, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
    except OSError as exc:
        print(f"could not write {request.report}: {exc}", file=sys.stderr)
        return 2
    todo = sum(1 for i in items if i.status in (inventory.Status.UPDATE, inventory.Status.OLD))
    print(f"{len(items)} items, {todo} to look at: {request.report}", file=sys.stderr)
    return 1 if todo else 0
