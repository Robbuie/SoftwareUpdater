"""Render the window to a PNG without a screen.

File Manager's and File Compare's tool, for the same reason: Claude cannot
see this application run, but Qt's offscreen platform draws the real window
with the real stylesheet into an image. The rows are the fixture machine in
`tests/data/` (see `tests/sample.py`), so nothing is scanned and nothing is
run. It says nothing about whether the window *behaves*.

    python tools/preview.py --out preview.png
    python tools/preview.py --show all --select "Intel(R) Wi-Fi 6E AX211 160MHz" --out p.png
    python tools/preview.py --all-themes --out-dir previews
    python tools/preview.py --section cleanup --out cleanup.png
    python tools/preview.py --section security --select "Firewall" --out security.png
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _fake_pages(window, sample) -> None:
    """Fill Cleanup and Security from the fixtures instead of the machine."""
    from app.core import cleanup, security
    from app.core.cleanup import Measured
    import datetime as _dt

    page = window.cleanup
    page._started = True
    sizes = {"user-temp": 2_400_000_000, "windows-temp": 310_000_000, "thumbnails": 95_000_000,
             "crash-user": 1_200_000_000, "crash-system": None, "recycle-bin": 4_700_000_000,
             "delivery": None, "wu-download": None, "component-store": None,
             "pip": 880_000_000, "npm": 1_900_000_000, "nuget-http": 420_000_000,
             "nuget-packages": 6_300_000_000, "gradle": 0, "maven": 0}
    for ident, size in sizes.items():
        target = cleanup.BY_ID[ident]
        note = "" if size is not None else (
            "Measured when it runs" if target.method != cleanup.Method.FILES
            else "Needs administrator rights to measure")
        page._measured(Measured(ident, size, 1234 if size else 0, note))
    page.status.setText("About 12.1 GB could be freed")
    page.free.setText("C:  38.2 GB free of 475.9 GB")
    sec = window.security
    sec._started = True
    sec._show(sample.security())
    _ = (security, _dt)


def render(theme: str, accent: str, density: str, width: int, height: int, show: str,
           select: str, out: str, scale: float, section: str = "software") -> None:
    from PySide6.QtWidgets import QApplication

    from app.core.config import Config
    from app.ui.window import ROW_SELECT, MainWindow
    from app.ui.model import ItemRole
    from tests import sample

    app = QApplication.instance() or QApplication([])
    config = Config({"scan.on_launch": False, "updates.check_on_launch": False,
                     "view.show": show},
                    path=os.path.join(tempfile.mkdtemp(), "config.json"))
    window = MainWindow(config, look={"theme": theme, "accent": accent, "density": density},
                        look_source="own")
    window.resize(width, height)
    window._scan_finished(sample.scan())
    window.say("winget: updating Git")
    window.say("Git: Updated.")
    _fake_pages(window, sample)
    window.show_section(section)
    if section == "security" and select:
        for index in range(window.security.list.topLevelItemCount()):
            item = window.security.list.topLevelItem(index)
            if item.text(1) == select:
                item.setSelected(True)
        select = ""
    if select:
        for row in range(window.proxy.rowCount()):
            index = window.proxy.index(row, 0)
            if window.proxy.data(index, ItemRole).name == select:
                window.view.selectionModel().select(index, ROW_SELECT)
    window.show()
    for _ in range(20):
        app.processEvents()
    image = window.grab().toImage()
    if scale != 1.0:
        from PySide6.QtCore import Qt

        image = image.scaledToWidth(int(image.width() * scale), Qt.SmoothTransformation)
    image.save(out)
    window._loader.shutdown()
    window.close()
    print(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", default="slate")
    parser.add_argument("--accent", default="sky")
    parser.add_argument("--density", default="normal")
    parser.add_argument("--width", type=int, default=1360)
    parser.add_argument("--height", type=int, default=820)
    parser.add_argument("--show", default="updates")
    parser.add_argument("--select", default="Git")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--section", default="software", choices=("software", "cleanup", "security"))
    parser.add_argument("--out", default="preview.png")
    parser.add_argument("--all-themes", action="store_true")
    parser.add_argument("--out-dir", default="previews")
    args = parser.parse_args()
    if args.all_themes:
        from app.theme.tokens import THEMES

        os.makedirs(args.out_dir, exist_ok=True)
        for theme in THEMES:
            render(theme, args.accent, args.density, args.width, args.height, args.show,
                   args.select, os.path.join(args.out_dir, f"{theme}.png"), args.scale,
                   args.section)
        return
    render(args.theme, args.accent, args.density, args.width, args.height, args.show,
           args.select, args.out, args.scale, args.section)


if __name__ == "__main__":
    main()
