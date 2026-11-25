"""Entry point: hand over to a running window, or become the window.

The command line is parsed before Qt is asked for anything, and a running
instance is looked for before a window is built: a second start from the
Start menu should bring the open window forward, not start a second scan.
"""

from __future__ import annotations

import multiprocessing
import os
import sys


def main() -> int:
    multiprocessing.freeze_support()
    argv = sys.argv[1:]

    from app import cli

    request = cli.parse(argv)
    if request.report:
        from app import batch
        from app.core.config import Config

        return batch.main(request, Config.load())

    from PySide6.QtWidgets import QApplication

    from app import __version__
    from app.core import appearance, instance
    from app.core.config import Config
    from app.ui.window import MainWindow

    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("Software Updater")
    app.setApplicationVersion(__version__)

    if instance.hand_over(argv, os.getcwd()):
        return 0

    config = Config.load()
    on_launch = config.get("scan.on_launch")
    if request.no_scan:
        # This start only: the setting is put back before anything saves it.
        config.set("scan.on_launch", False)
    look, source = appearance.resolve(config)
    window = MainWindow(config, look=look, look_source=source)
    config.set("scan.on_launch", on_launch)

    listener = instance.Listener()
    listener.received.connect(lambda _args, _where: window.bring_forward())
    listener.listen()

    if config.get("window.maximized"):
        window.showMaximized()
    else:
        window.show()
    code = app.exec()
    listener.close()
    # A downloaded, verified update of this application runs once the window
    # is gone, so the installer is not waiting on files this process holds.
    window.updates.install_staged()
    return code


if __name__ == "__main__":
    sys.exit(main())
