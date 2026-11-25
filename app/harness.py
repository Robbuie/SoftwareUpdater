"""Each source on its own, from a terminal, without the window.

This is the test loop for the parts Claude cannot run: winget, PowerShell and
the Windows Update Agent exist only on the real machine. When the window
shows something odd, the source behind it can be run alone here and its raw
output and its parse compared.

    python -m app.harness winget-list            run `winget list`, show the parse
    python -m app.harness winget-upgrade         run `winget upgrade`
    python -m app.harness parse saved.txt        parse winget output saved to a file
    python -m app.harness drivers                installed drivers, grouped
    python -m app.harness windows-update         what Windows Update offers
    python -m app.harness system                 manufacturer, model, BIOS
    python -m app.harness registry               the Uninstall entries
    python -m app.harness inventory              every source, merged, as the window shows it

Add `--raw` to print what the program wrote before the parse.

Capturing winget output for a test: `winget upgrade --include-unknown >
upgrade.txt` and `python -m app.harness parse upgrade.txt`. A file that
parses wrongly belongs in `tests/data/winget/` with a test beside it.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
import threading


def _rows(text: str) -> None:
    from app.core import winget

    for table in winget.parse(text):
        print(f"-- table, {len(table.rows)} rows{' (explicit)' if table.explicit else ''}")
        for row in table.rows:
            print(f"{row.name[:40]:<40} {row.id[:36]:<36} {row.version:<16} "
                  f"{row.available:<16} {row.source}")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 0
    raw = "--raw" in argv
    argv = [a for a in argv if a != "--raw"]
    command = argv[0]
    cancel = threading.Event()

    if command == "parse":
        with open(argv[1], "r", encoding="utf-8", errors="replace") as handle:
            _rows(handle.read())
        return 0

    from app.io import powershell, registry, scripts, wingetcli

    if command in ("winget-list", "winget-upgrade"):
        exe = wingetcli.find()
        if not exe:
            print("winget not found")
            return 2
        print(f"winget {wingetcli.version(exe)} at {exe}")
        result = (wingetcli.list_installed(exe, timeout=180, cancel=cancel)
                  if command == "winget-list"
                  else wingetcli.list_upgrades(exe, timeout=180, cancel=cancel))
        print(f"exit 0x{result.code & 0xFFFFFFFF:08X} in {result.seconds:.1f} s")
        if raw:
            print(result.out)
            print(result.err, file=sys.stderr)
        _rows(result.out)
        return 0

    if command in ("drivers", "windows-update", "system"):
        script = {"drivers": scripts.DRIVERS, "system": scripts.SYSTEM,
                  "windows-update": scripts.fill(scripts.WU_SEARCH, server="windows-update")}[
            command]
        answer = powershell.call(script, timeout=900, cancel=cancel)
        print(f"ok={answer.ok} in {answer.seconds:.1f} s {answer.error}")
        if raw or command == "system":
            print(json.dumps(answer.data, indent=2)[:20000])
        if command == "drivers" and answer.ok:
            from app.core import drivers

            for group in drivers.group(drivers.devices(answer.data.get("drivers"))):
                print(f"{group.name[:50]:<50} {group.version:<20} {group.date:<11} "
                      f"{group.provider}{'  (inbox)' if group.inbox else ''}")
        if command == "windows-update" and answer.ok:
            from app.core import winupdate

            for offer in winupdate.offers(answer.data.get("updates")):
                print(f"{'driver ' if offer.is_driver else 'software'} {offer.title}")
        return 0 if answer.ok else 1

    if command == "registry":
        for entry in sorted(registry.entries(), key=lambda e: e.name.lower()):
            print(f"{entry.name[:50]:<50} {entry.version:<20} {entry.scope:<8} {entry.publisher}")
        return 0

    if command == "inventory":
        from app.core import inventory, oem
        from app.core.config import Config, scan_options
        from app.core.scan import STAGE_LABELS, run
        from app.io.probe import Probe

        config = Config.load()
        scan = run(Probe(), scan_options(config),
                   report=lambda stage, s: print(f"{STAGE_LABELS[stage]}: "
                                                 f"{s.errors.get(stage) or 'done'}"))
        items = inventory.build(scan.sources, today=_dt.date.today(),
                                vendor_url=oem.support_url(str(scan.system.get("manufacturer"))))
        for item in sorted(items, key=lambda i: (inventory.STATUS_ORDER.get(i.status, 9),
                                                 i.name.lower())):
            print(f"{inventory.STATUS_LABELS[item.status]:<24} {item.kind:<8} "
                  f"{item.name[:48]:<48} {item.installed:<18} {item.available}")
        return 0

    print(f"unknown command {command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
