"""The window: title bar with the menus, the command row, the list of what is
installed, and under it the details of the selected row beside the activity
log.

Its shape is File Compare's -- the same custom title bar with Windows' own
snapping and shadow kept (`winframe.py`), the same labelled command row, the
same status line -- with one page instead of tabs, because there is one
machine to look at.

Nothing here runs a program or reads a file. A scan and an update run are
handed to the loader (`core/work.py`) and their progress arrives as events;
opening a page or a tool goes through `io/system.py` on the loader too.
"""

from __future__ import annotations

import datetime as _dt
import time

from PySide6.QtCore import QEvent, QItemSelectionModel, QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.core import appearance, inventory, oem, plan as _plan, report, updates, work
from app.core.config import Config, scan_options
from app.core.inventory import Action, Item, Status
from app.core.loader import Loader
from app.core.scan import STAGE_LABELS, Scan, stages
from app.theme import sheet
from app.theme.tokens import ACCENT_LABELS, ACCENTS, DENSITIES, DENSITY_LABELS, THEME_LABELS, THEMES
from app.ui import winframe
from app.ui.chrome import MenuBar, ToolBar
from app.ui.commands import (COMMANDS, DISABLED, HIDDEN, SHOW_COMMANDS, TOGGLES, State)
from app.ui.model import (AVAILABLE, INSTALLED, KIND, NAME, SOURCE, STATUS, FilterProxy,
                          ItemModel, ItemRole)
from app.ui.titlebar import TitleBar

KEYS = """\
F5                        scan again
Esc                       stop the scan or the updates
Ctrl+U                    update the selected rows
Ctrl+Shift+U              update everything that can be updated here
Ctrl+A                    select every row with an update
Delete / Insert           ignore the selected rows, show them again
Ctrl+C                    copy the winget command for the selected rows
Ctrl+1 .. Ctrl+6          Updates, All, Apps, Drivers, Windows, Ignored
Ctrl+F                    filter by name, id or version
Ctrl+D                    the details panel
Ctrl+Shift+H              export a report
F1                        this list"""

OLD_YEARS = (0.0, 1.0, 2.0, 3.0, 5.0)
ROW_SELECT = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows


class MainWindow(QMainWindow):

    def __init__(self, config: Config, *, look: dict[str, str], look_source: str,
                 custom_frame: bool = True) -> None:
        super().__init__()
        self._config = config
        self._look = dict(look)
        self._look_source = look_source
        self._tokens = sheet.tokens(**self._look)
        self._titlebar: TitleBar | None = None
        self._frame: winframe.NativeFrame | None = None

        self._loader = Loader(self)
        self._loader.finished.connect(self._finished)
        self._loader.progress.connect(self._progress)
        self._scan_request = 0
        self._update_request = 0
        self._scan: Scan | None = None
        self._scan_started = 0.0
        self._pending_stages: list[str] = []
        self._tools: dict[str, str] = {}
        self._tools_request = 0

        self.setWindowTitle("Software Updater")
        self.resize(int(config.get("window.width")), int(config.get("window.height")))

        # The list.
        self.model = ItemModel(self)
        self.proxy = FilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.configure(show=self._show(), ignored=set(config.get("ignore.items")))
        self.view = QTreeView()
        self.view.setProperty("role", "foldertree")
        self.view.setModel(self.proxy)
        self.view.setRootIsDecorated(False)
        self.view.setUniformRowHeights(True)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(STATUS, Qt.AscendingOrder)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.view.selectionModel().selectionChanged.connect(lambda *_: self._selection_changed())
        self.view.doubleClicked.connect(lambda _i: self._set_details(True))
        header = self.view.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(NAME, QHeaderView.Stretch)
        for column, size in ((KIND, 96), (INSTALLED, 150), (AVAILABLE, 150), (STATUS, 200),
                             (SOURCE, 120)):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
            header.resizeSection(column, size)

        self.filter = QLineEdit()
        self.filter.setProperty("role", "findfield")
        self.filter.setPlaceholderText("Filter by name, id or version  (Ctrl+F)")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(lambda text: (self.proxy.configure(text=text),
                                                      self._refresh_chrome()))
        self.filter.setFixedWidth(340)
        self.sources_label = QLabel()
        self.sources_label.setProperty("role", "note")
        self.notice = QLabel()
        self.notice.setProperty("role", "warn")
        self.notice.setWordWrap(True)
        self.notice.hide()
        bar = QWidget()
        bar.setProperty("role", "folderbar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar_row = QHBoxLayout(bar)
        bar_row.setContentsMargins(10, 6, 10, 6)
        bar_row.setSpacing(10)
        bar_row.addWidget(self.filter)
        bar_row.addWidget(self.sources_label, 1)

        card = QFrame()
        card.setProperty("role", "card")
        card_column = QVBoxLayout(card)
        card_column.setContentsMargins(0, 0, 0, 0)
        card_column.setSpacing(0)
        card_column.addWidget(bar)
        card_column.addWidget(self.view, 1)

        # Under the list: the selected row's details, and what has happened.
        self.details = QPlainTextEdit()
        self.details.setProperty("role", "passage")
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Select a row to see where it came from and how it "
                                        "would be updated.")
        self.log = QPlainTextEdit()
        self.log.setProperty("role", "passage")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.lower = QSplitter(Qt.Horizontal)
        self.lower.addWidget(self.details)
        self.lower.addWidget(self.log)
        self.lower.setSizes([600, 600])

        self.split = QSplitter(Qt.Vertical)
        self.split.addWidget(card)
        self.split.addWidget(self.lower)
        self.split.setChildrenCollapsible(False)
        sizes = config.get("window.split")
        if isinstance(sizes, list) and len(sizes) == 2:
            self.split.setSizes([int(s) for s in sizes])
        self.lower.setVisible(bool(config.get("view.details")))

        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(10, 8, 10, 6)
        column.setSpacing(6)
        column.addWidget(self.notice)
        column.addWidget(self.split, 1)

        self._status_left = QLabel()
        self._status_right = QLabel()
        self.statusBar().addWidget(self._status_left, 1)
        self.statusBar().addPermanentWidget(self._status_right)
        self.statusBar().setSizeGripEnabled(False)

        self.menubar = MenuBar(self)
        self.toolbar = ToolBar(self)
        self.toolbar.set_kind("main")

        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        if custom_frame:
            self._titlebar = TitleBar()
            self._titlebar.set_menubar(self.menubar)
            self._titlebar.menuRequested.connect(self._show_app_menu)
            self._titlebar.goRequested.connect(self.scan)
            self._titlebar.minimizeRequested.connect(self.showMinimized)
            self._titlebar.maximizeRequested.connect(self.toggle_maximized)
            self._titlebar.closeRequested.connect(self.close)
            outer.addWidget(self._titlebar)
            self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
            self._frame = winframe.NativeFrame(self, glass=False, dark=self._is_dark())
        else:
            outer.addWidget(self.menubar)
        outer.addWidget(self.toolbar)
        outer.addWidget(body, 1)
        self.setCentralWidget(root)

        self._shortcuts()
        self.apply_look(self._look, self._look_source)
        self._update_sources_label()
        self._status_left.setText("Not scanned yet. F5 scans.")

        self.updates = updates.Updates(config, __version__, self)
        self.updates.available.connect(self._update_available)
        self.updates.uptodate.connect(
            lambda current: self.flash(f"{current} is the latest version of Software Updater"))
        self.updates.problem.connect(self.flash)
        self.updates.progress.connect(self._update_progress)
        self.updates.ready.connect(self._update_ready)
        self.updates.start_if_wanted()

        if config.get("scan.on_launch"):
            QTimer.singleShot(400, self.scan)

    # ---------------------------------------------------------------- state

    def _show(self) -> str:
        value = self._config.get("view.show")
        return value if value in inventory.SHOWS else "updates"

    def _ignored(self) -> set[str]:
        return set(self._config.get("ignore.items"))

    def busy(self) -> bool:
        return bool(self._scan_request or self._update_request)

    def selected(self) -> list[Item]:
        rows = self.view.selectionModel().selectedRows() if self.view.selectionModel() else []
        return [self.proxy.data(index, ItemRole) for index in rows]

    def flash(self, text: str) -> None:
        self.statusBar().showMessage(text, 15000)

    def say(self, text: str) -> None:
        """A line in the activity log, with the time."""
        self.log.appendPlainText(f"{time.strftime('%H:%M:%S')}  {text}")

    # ----------------------------------------------------------------- scan

    def scan(self) -> None:
        if self.busy():
            self.flash("Wait for the current job to finish, or press Esc to stop it.")
            return
        options = scan_options(self._config)
        self._pending_stages = stages(options)
        self._scan_started = time.monotonic()
        self._scan_request = self._loader.submit(work.scan, options)
        self.say("Scanning: " + ", ".join(STAGE_LABELS[s] for s in self._pending_stages))
        self._update_sources_label()
        self._refresh_chrome()

    def _rebuild(self, scan: Scan) -> None:
        """New rows from what the scan has so far, keeping the selection and
        anything this session already updated."""
        keep = {item.key: item for item in self.model.items
                if item.status in (Status.DONE, Status.FAILED)}
        chosen = {item.key for item in self.selected()}
        manufacturer = str(scan.system.get("manufacturer") or "")
        items = inventory.build(
            scan.sources, today=_dt.date.today(),
            old_years=float(self._config.get("drivers.old_years")),
            include_inbox=bool(self._config.get("drivers.include_inbox")),
            vendor_url=oem.support_url(manufacturer))
        for index, item in enumerate(items):
            previous = keep.get(item.key)
            if previous is not None and item.status == Status.UPDATE:
                items[index] = previous
        self.model.set_items(items)
        if chosen:
            selection = self.view.selectionModel()
            for row in range(self.proxy.rowCount()):
                index = self.proxy.index(row, 0)
                if self.proxy.data(index, ItemRole).key in chosen:
                    selection.select(index, ROW_SELECT)
        self._refresh_chrome()

    def _scan_stage(self, stage: str, scan: Scan) -> None:
        self._scan = scan
        if stage in self._pending_stages:
            self._pending_stages.remove(stage)
        seconds = scan.seconds.get(stage, 0.0)
        error = scan.errors.get(stage)
        label = STAGE_LABELS.get(stage, stage)
        if error:
            self.say(f"{label}: {error}")
        else:
            self.say(f"{label}: done in {seconds:.0f} s")
        self._rebuild(scan)
        self._update_sources_label()
        self._show_notices(scan)

    def _scan_finished(self, scan: Scan | None, error: str = "") -> None:
        self._scan_request = 0
        self._pending_stages = []
        if scan is not None:
            self._scan = scan
            self._rebuild(scan)
            self._show_notices(scan)
            self._find_tools(scan)
        if error:
            self.say(f"The scan stopped: {error.splitlines()[0]}")
        if self._scan_started:
            self.say(f"Scan finished in {time.monotonic() - self._scan_started:.0f} s.")
            self._scan_started = 0.0
        self._update_sources_label()
        self._refresh_chrome()

    def _show_notices(self, scan: Scan) -> None:
        lines = [f"{STAGE_LABELS.get(stage, stage)}: {error}"
                 for stage, error in scan.errors.items() if error != "Cancelled."]
        self.notice.setText("\n".join(lines))
        self.notice.setVisible(bool(lines))

    def _update_sources_label(self) -> None:
        if self._pending_stages:
            text = "Waiting for " + ", ".join(STAGE_LABELS[s] for s in self._pending_stages)
        elif self._scan is not None:
            system = self._scan.system
            machine = " ".join(str(system.get(k) or "") for k in ("manufacturer", "model")).strip()
            text = (machine + "  ·  " if machine else "") + "Scanned " + time.strftime(
                "%H:%M", time.localtime(self._scan.finished_at or time.time()))
        else:
            text = ""
        self.sources_label.setText(text)

    def _find_tools(self, scan: Scan) -> None:
        manufacturer = str(scan.system.get("manufacturer") or "")
        providers = {g.provider for g in scan.sources.drivers or []}
        tools = oem.relevant(manufacturer, providers)

        def look(job, found):
            from app.io import system

            return system.found_tools(found)

        self._tools_request = self._loader.submit(look, tools)

    # -------------------------------------------------------------- updates

    def update_items(self, items: list[Item]) -> None:
        if self.busy():
            self.flash("Wait for the current job to finish, or press Esc to stop it.")
            return
        plan = _plan.build(items)
        if plan.empty:
            if items:
                self.flash("Nothing selected can be updated from here. The details panel "
                           "says what to do instead.")
            else:
                self.flash("Select the rows to update first.")
            return
        if plan.winget and not (self._scan and self._scan.winget_path):
            self.flash("winget was not found by the last scan.")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Update")
        box.setText(f"Update {len(plan.winget) + len(plan.wu)} "
                    f"item{'s' if len(plan.winget) + len(plan.wu) != 1 else ''}?")
        notes = ["Close the programs being updated first; an installer may refuse to "
                 "replace a running program."]
        if plan.wu:
            notes.append("Windows Update needs administrator rights: Windows will ask once.")
        if any(step for step in plan.winget):
            notes.append("A program installed for everyone may ask for administrator "
                         "rights itself.")
        box.setInformativeText("\n\n".join(notes))
        box.setDetailedText("\n".join(plan.describe()))
        go = box.addButton("Update", QMessageBox.AcceptRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not go:
            return
        settings = work.Settings(
            winget_exe=self._scan.winget_path if self._scan else "",
            silent=bool(self._config.get("winget.silent")),
            upgrade_timeout=float(self._config.get("winget.upgrade_timeout")),
            wu_server=str(self._config.get("wu.server")),
            wu_timeout=float(self._config.get("wu.install_timeout")))
        for step in plan.winget:
            self.model.busy[step.key] = "Waiting"
            self.model.changed(step.key)
        for item in plan.wu:
            self.model.busy[item.key] = "Waiting"
            self.model.changed(item.key)
        self._set_details(True)
        self.say(f"Updating {len(plan.winget)} with winget, {len(plan.wu)} from Windows Update.")
        self._update_request = self._loader.submit(work.update, plan, settings)
        self._refresh_chrome()

    def _update_event(self, event: tuple) -> None:
        kind = event[0]
        if kind == "start":
            _k, key, name = event
            self.model.busy[key] = "Updating..."
            self.model.changed(key)
            self.say(f"winget: updating {name}")
        elif kind == "line":
            _k, key, text = event
            if not _is_progress(text):
                self.log.appendPlainText(f"          {text}")
        elif kind == "done":
            _k, key, ok, note = event
            self._mark(key, ok, note)
            item = self.model.item(key)
            self.say(f"{item.name if item else key}: {note}")
        elif kind == "wu-start":
            for key, text in list(self.model.busy.items()):
                item = self.model.item(key)
                if item is not None and item.action == Action.WU:
                    self.model.busy[key] = "Installing..."
                    self.model.changed(key)
            self.say(f"Windows Update: installing {event[1]} as administrator. "
                     "Answer the Windows prompt to continue.")
        elif kind == "wu-done":
            result = event[1]
            if result.error:
                self.say(f"Windows Update: {result.error}")
            for outcome in result.outcomes:
                self.say(f"Windows Update: {outcome.title}: {outcome.text}")

    def _mark(self, key: str, ok: bool, note: str) -> None:
        self.model.busy.pop(key, None)
        item = self.model.item(key)
        if item is not None:
            item.status = Status.DONE if ok else Status.FAILED
            item.note = note
            self.model.changed(key)

    def _update_finished(self, outcome, error: str = "") -> None:
        self._update_request = 0
        if outcome is not None:
            for key in outcome.done:
                self._mark(key, True, "Updated this session.")
            for key, note in outcome.failed.items():
                self._mark(key, False, note)
        for key in list(self.model.busy):
            self.model.busy.pop(key, None)
            self.model.changed(key)
        if error:
            self.say(f"The update run stopped: {error.splitlines()[0]}")
        if outcome is not None:
            self.say(f"Finished: {len(outcome.done)} updated, {len(outcome.failed)} not"
                     + (", stopped early." if outcome.cancelled else "."))
            if outcome.reboot:
                QMessageBox.information(
                    self, "Restart needed",
                    "Windows needs a restart to finish installing. Save your work and "
                    "restart when it suits you; scan again afterwards to confirm.")
        self.flash("Updates finished. Scan again (F5) to confirm what is installed now.")
        self._refresh_selection_details()
        self._refresh_chrome()

    def stop(self) -> None:
        for request in (self._scan_request, self._update_request):
            if request:
                self._loader.cancel(request)
        if self.busy():
            self.say("Stopping...")

    # ---------------------------------------------------------------- loader

    def _progress(self, request: int, payload) -> None:
        if request == self._scan_request and payload and payload[0] == "stage":
            self._scan_stage(payload[1], payload[2])
        elif request == self._update_request:
            self._update_event(payload)

    def _finished(self, request: int, envelope) -> None:
        if request == self._scan_request:
            self._scan_finished(envelope.value if envelope.ok else None, envelope.error)
        elif request == self._update_request:
            self._update_finished(envelope.value if envelope.ok else None, envelope.error)
        elif request == self._tools_request and envelope.ok:
            self._tools = envelope.value or {}
            self._refresh_chrome()

    # --------------------------------------------------------------- details

    def _selection_changed(self) -> None:
        self._refresh_selection_details()
        self._refresh_chrome()

    def _refresh_selection_details(self) -> None:
        items = self.selected()
        if len(items) != 1:
            self.details.setPlainText(f"{len(items)} rows selected." if items else "")
            return
        self.details.setPlainText(describe(items[0], self._vendor_hint()))

    def _vendor_hint(self) -> str:
        installed = [name for name, path in self._tools.items() if path]
        if installed:
            return f"Update > Manufacturer's driver tool opens {installed[0]}."
        manufacturer = str((self._scan.system if self._scan else {}).get("manufacturer") or "")
        if oem.support_url(manufacturer):
            return "Update > Manufacturer's driver tool opens the maker's driver page."
        return "Check the device maker's support site, or Device Manager."

    def _set_details(self, on: bool) -> None:
        self._config.set("view.details", bool(on))
        self.lower.setVisible(bool(on))
        self._refresh_chrome()

    # ------------------------------------------------------------- commands

    def _refresh_chrome(self) -> None:
        self.toolbar.refresh()
        visible = self.proxy.rowCount()
        total = len(self.model.items)
        counts = inventory.counts(self.model.items, self._ignored())
        if total:
            self._status_left.setText(
                f"{visible:,} shown  ·  {counts['updates']:,} with something to do  ·  "
                f"{sum(1 for i in self.model.items if i.kind == inventory.Kind.APP):,} "
                f"applications, "
                f"{sum(1 for i in self.model.items if i.kind == inventory.Kind.DRIVER):,} "
                f"drivers")

    def command_state(self, id_: str) -> State:
        if id_ in SHOW_COMMANDS:
            show = SHOW_COMMANDS[id_]
            counts = inventory.counts(self.model.items, self._ignored())
            return State(checked=self._show() == show,
                         count=counts.get(show) if self.model.items else None)
        if id_ in TOGGLES:
            return State(checked=bool(self._config.get(TOGGLES[id_])))
        selected = self.selected()
        if id_ == "scan":
            return State(enabled=not self.busy(), visible=not self.busy())
        if id_ == "stop":
            return State(visible=self.busy())
        if id_ == "update-selected":
            n = sum(1 for i in selected if i.updatable)
            return State(enabled=n > 0 and not self.busy(), count=n or None)
        if id_ == "update-all":
            n = sum(1 for i in self.model.items if i.updatable
                    and i.key not in self._ignored())
            return State(enabled=n > 0 and not self.busy(), count=n or None)
        if id_ == "select-updates":
            return State(enabled=any(i.updatable for i in self.model.items))
        if id_ == "ignore":
            return State(enabled=bool(selected) and self._show() != "ignored")
        if id_ == "unignore":
            return State(enabled=any(i.key in self._ignored() for i in selected))
        if id_ == "copy-command":
            return State(enabled=any(i.winget_id for i in selected))
        if id_ == "export":
            return State(enabled=bool(self.model.items))
        if id_ == "vendor":
            installed = [n for n, p in self._tools.items() if p]
            manufacturer = str((self._scan.system if self._scan else {}).get("manufacturer")
                               or "")
            if installed:
                return State(tip=f"Open {installed[0]}")
            return State(enabled=bool(oem.support_url(manufacturer)))
        if id_ == "details":
            return State(checked=bool(self._config.get("view.details")))
        if id_ == "wu-direct":
            return State(checked=self._config.get("wu.server") == "windows-update")
        if id_ == "follow-look":
            return State(checked=bool(self._config.get("look.follow_file_manager")))
        if id_ == "check-updates":
            return State(enabled=not self.updates.busy())
        return State()

    def run_command(self, id_: str) -> None:
        if not self.command_state(id_).enabled and id_ not in SHOW_COMMANDS:
            return
        if id_ in SHOW_COMMANDS:
            self._config.set("view.show", SHOW_COMMANDS[id_])
            self.proxy.configure(show=SHOW_COMMANDS[id_])
        elif id_ in TOGGLES:
            key = TOGGLES[id_]
            self._config.set(key, not bool(self._config.get(key)))
            if key == "drivers.include_inbox" and self._scan is not None:
                self._rebuild(self._scan)
            elif key.startswith("scan.") and key != "scan.on_launch":
                self.flash("Takes effect at the next scan (F5).")
                self._update_sources_label()
        else:
            action = {
                "scan": self.scan,
                "stop": self.stop,
                "export": self.export,
                "exit": self.close,
                "update-selected": lambda: self.update_items(self.selected()),
                "update-all": lambda: self.update_items(
                    [i for i in self.model.items if i.updatable
                     and i.key not in self._ignored()]),
                "select-updates": self.select_updates,
                "ignore": lambda: self._ignore(True),
                "unignore": lambda: self._ignore(False),
                "copy-command": self.copy_command,
                "vendor": self.open_vendor,
                "device-manager": lambda: self._open("devmgmt.msc"),
                "wu-settings": lambda: self._open("ms-settings:windowsupdate"),
                "wu-optional": lambda: self._open("ms-settings:windowsupdate-optionalupdates"),
                "apps-settings": lambda: self._open("ms-settings:appsfeatures"),
                "details": lambda: self._set_details(not self._config.get("view.details")),
                "filter": lambda: (self.filter.setFocus(), self.filter.selectAll()),
                "follow-look": lambda: self._follow(
                    not self._config.get("look.follow_file_manager")),
                "wu-direct": self._toggle_wu_server,
                "keys": self.show_keys,
                "open-log": lambda: QApplication.clipboard().setText(self.log.toPlainText()),
                "check-updates": lambda: self.updates.check(manual=True),
                "about": self._about,
            }.get(id_)
            if action is not None:
                action()
        self._refresh_chrome()

    def fill_menu(self, name: str, menu: QMenu) -> None:
        if name in ("theme", "accent", "density"):
            names, labels = {"theme": (THEMES, THEME_LABELS), "accent": (ACCENTS, ACCENT_LABELS),
                             "density": (DENSITIES, DENSITY_LABELS)}[name]
            group = QActionGroup(menu)
            current = self._tokens[f"{name}_name"]
            for value in names:
                action = QAction(labels.get(value, value), menu)
                action.setCheckable(True)
                action.setChecked(value == current)
                action.triggered.connect(lambda _c=False, k=name, n=value: self._choose(k, n))
                group.addAction(action)
                menu.addAction(action)
        elif name == "old-years":
            group = QActionGroup(menu)
            current = float(self._config.get("drivers.old_years"))
            for years in OLD_YEARS:
                label = "Never" if years == 0 else f"{years:g} year{'s' if years != 1 else ''}"
                action = QAction(label, menu)
                action.setCheckable(True)
                action.setChecked(abs(years - current) < 0.01)
                action.triggered.connect(lambda _c=False, y=years: self._set_old_years(y))
                group.addAction(action)
                menu.addAction(action)

    def _set_old_years(self, years: float) -> None:
        self._config.set("drivers.old_years", years)
        if self._scan is not None:
            self._rebuild(self._scan)

    def _toggle_wu_server(self) -> None:
        direct = self._config.get("wu.server") == "windows-update"
        self._config.set("wu.server", "default" if direct else "windows-update")
        self.flash("Takes effect at the next scan (F5).")

    def select_updates(self) -> None:
        selection = self.view.selectionModel()
        selection.clearSelection()
        for row in range(self.proxy.rowCount()):
            index = self.proxy.index(row, 0)
            if self.proxy.data(index, ItemRole).updatable:
                selection.select(index, ROW_SELECT)

    def _ignore(self, on: bool) -> None:
        keys = {i.key for i in self.selected()}
        ignored = self._ignored()
        ignored = (ignored | keys) if on else (ignored - keys)
        self._config.set("ignore.items", sorted(ignored))
        self.proxy.configure(ignored=ignored)
        self.flash(f"{len(keys)} row{'s' if len(keys) != 1 else ''} "
                   + ("ignored. View > Ignored lists them." if on else "shown again."))

    def copy_command(self) -> None:
        lines = []
        for item in self.selected():
            if item.winget_id:
                from app.core import winget

                args = winget.upgrade_args(item.winget_id,
                                           silent=bool(self._config.get("winget.silent")))
                lines.append("winget " + " ".join(f'"{a}"' if " " in a else a for a in args))
        QApplication.clipboard().setText("\n".join(lines))
        self.flash(f"Copied {len(lines)} winget command{'s' if len(lines) != 1 else ''}.")

    def open_vendor(self) -> None:
        installed = [(n, p) for n, p in self._tools.items() if p]
        if installed:
            name, path = installed[0]
            self.say(f"Opening {name}")
            self._open(path)
            return
        manufacturer = str((self._scan.system if self._scan else {}).get("manufacturer") or "")
        url = oem.support_url(manufacturer)
        if url:
            self.say(f"Opening {url}")
            self._open(url)

    def _open(self, target: str) -> None:
        def go(job, what):
            from app.io import system

            return system.open_target(what)

        self._loader.submit(go, target)

    def export(self) -> None:
        path, chosen = QFileDialog.getSaveFileName(
            self, "Export report", f"software-{time.strftime('%Y-%m-%d')}.html",
            "HTML report (*.html);;CSV for a spreadsheet (*.csv)")
        if not path:
            return
        items = [self.proxy.data(self.proxy.index(r, 0), ItemRole)
                 for r in range(self.proxy.rowCount())]
        if path.lower().endswith(".csv"):
            text = report.to_csv(items)
        else:
            system = self._scan.system if self._scan else {}
            machine = " ".join(str(system.get(k) or "") for k in ("manufacturer", "model"))
            text = report.to_html(items, machine=machine.strip(),
                                  errors=self._scan.errors if self._scan else {})

        def write(job, where, body):
            with open(where, "w", encoding="utf-8", newline="") as handle:
                handle.write(body)
            return where

        self._loader.submit(write, path, text)
        self.say(f"Exported {len(items)} rows to {path}")

    def _context_menu(self, at: QPoint) -> None:
        menu = QMenu(self)
        for id_ in ("update-selected", "copy-command", "-", "ignore", "unignore", "-", "vendor"):
            if id_ == "-":
                menu.addSeparator()
                continue
            command = COMMANDS[id_]
            state = self.command_state(id_)
            action = menu.addAction(command.label + (f"\t{command.key}" if command.key else ""))
            action.setEnabled(state.enabled)
            action.triggered.connect(lambda _c=False, i=id_: self.run_command(i))
        menu.exec(self.view.viewport().mapToGlobal(at))

    def _shortcuts(self) -> None:
        for id_, command in COMMANDS.items():
            if not command.key or id_ in ("exit",):
                continue
            shortcut = QShortcut(QKeySequence(command.key), self)
            if id_ in ("copy-command", "select-updates", "ignore", "unignore"):
                # Keys the filter box also wants: only when the list has focus.
                shortcut.setContext(Qt.WidgetWithChildrenShortcut)
                shortcut.setParent(self.view)
            shortcut.activated.connect(lambda i=id_: self.run_command(i))

    # ----------------------------------------------------------------- look

    def _is_dark(self) -> bool:
        return sum(sheet.qss.unhex(self._tokens["bg_0"])) < 382

    def apply_look(self, look: dict[str, str], source: str) -> None:
        self._look = dict(look)
        self._look_source = source
        app = QApplication.instance()
        self._tokens = sheet.apply(app, **self._look) if app is not None else sheet.tokens(**look)
        if self._titlebar is not None:
            self._titlebar.apply_tokens(self._tokens)
        if self._frame is not None:
            self._frame.set_dark(self._is_dark())
        self.toolbar.apply_tokens(self._tokens)
        self.model.set_tokens(self._tokens)
        where = "File Manager's look" if source == "file manager" else "own look"
        self._status_right.setText(
            f"{THEME_LABELS.get(self._tokens['theme_name'], '')}  ·  "
            f"{ACCENT_LABELS.get(self._tokens['accent_name'], '')}  ·  {where}")

    def _choose(self, key: str, value: str) -> None:
        look = dict(self._look)
        look[key] = value
        for name in appearance.KEYS:
            self._config.set(name, look[name])
        following = self._config.get("look.follow_file_manager")
        self._config.set("look.follow_file_manager", False)
        self.apply_look(look, "own")
        if following:
            self.flash("Using this application's own look now; "
                       "the View menu can follow File Manager's again.")

    def _follow(self, on: bool) -> None:
        self._config.set("look.follow_file_manager", on)
        look, source = appearance.resolve(self._config)
        if on and source != "file manager":
            self.flash("File Manager's settings could not be read; keeping this look.")
        self.apply_look(look, source)

    # -------------------------------------------------------------- updates

    def _update_available(self, release) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Update")
        size = f" ({release.size / 1e6:.0f} MB)" if release.size else ""
        box.setText(f"Software Updater {release.version} is available{size}. "
                    f"This is {__version__}.")
        box.setInformativeText("It downloads in the background and installs when you quit.")
        download = box.addButton("Download", QMessageBox.AcceptRole)
        skip = box.addButton("Skip this version", QMessageBox.RejectRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is download:
            self.updates.accept(release)
        elif box.clickedButton() is skip:
            self.updates.skip(release)

    def _update_progress(self, done: int, total: int) -> None:
        share = (done / total * 100) if total else 0
        self.statusBar().showMessage(f"Downloading update  {share:.0f}%", 2000)

    def _update_ready(self, release) -> None:
        answer = QMessageBox.question(
            self, "Update ready",
            f"Software Updater {release.version} is downloaded. Quit and install it now?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self.close()

    def show_keys(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Keys")
        box.setTextFormat(Qt.PlainText)
        box.setText(KEYS)
        box.setStyleSheet("QLabel { font-family: " + self._tokens["mono"] + "; }")
        box.exec()

    def _about(self) -> None:
        QMessageBox.about(self, "Software Updater",
                          f"Software Updater {__version__}\n\nWhat on this computer is out "
                          "of date, and the way to update it. From the same family as File "
                          "Manager and File Compare.")

    # ---------------------------------------------------------------- frame

    def _show_app_menu(self, at: QPoint) -> None:
        menu = self.menubar.menus.get("Scan")
        if menu is not None:
            menu.popup(at)

    def hit_parts(self, pos) -> tuple[bool, bool]:
        """For `winframe`: is `pos` the maximise button, and is it caption."""
        bar = self._titlebar
        if bar is None:
            return False, False
        local = bar.mapFrom(self, pos)
        return bar.max_button.geometry().contains(local), bar.is_caption(local)

    def set_max_hover(self, hot: bool) -> None:
        if self._titlebar is not None:
            self._titlebar.set_max_hover(hot)

    def toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._frame is not None and not self._frame.active:
            self._frame.install()
            if self._frame.problem:
                self.flash(self._frame.problem)

    def nativeEvent(self, event_type, message):  # noqa: N802
        if self._frame is not None:
            answer = self._frame.handle(event_type, message)
            if answer is not None:
                return answer
        return super().nativeEvent(event_type, message)

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.WindowStateChange and self._titlebar is not None:
            self._titlebar.set_maximized(self.isMaximized())
        super().changeEvent(event)

    def bring_forward(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._update_request:
            answer = QMessageBox.question(
                self, "Updates running",
                "Updates are still running. Stop them and close?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        self._config.set("window.maximized", self.isMaximized())
        if not self.isMaximized():
            self._config.set("window.width", self.width())
            self._config.set("window.height", self.height())
        self._config.set("window.split", self.split.sizes())
        self._config.save()
        self.updates.shutdown()
        self._loader.shutdown()
        super().closeEvent(event)


def _is_progress(text: str) -> bool:
    """winget's download bar and spinner, which say nothing in a log."""
    stripped = text.strip()
    if len(stripped) <= 2:
        return True
    return stripped[0] in "█▒-\\|/" and ("KB" in stripped or "MB" in stripped
                                                   or "%" in stripped or len(set(stripped)) <= 3)


def describe(item: Item, vendor_hint: str = "") -> str:
    """The details panel for one row."""
    lines = [item.name, ""]
    status = inventory.STATUS_LABELS.get(item.status, item.status)
    lines.append(f"{'Status':<18}{status}")
    if item.note:
        lines.append(f"{'Last attempt':<18}{item.note}")
    for label, value in item.facts:
        first, *rest = (value or "").split("\n")
        lines.append(f"{label:<18}{first}")
        lines.extend(f"{'':<18}{more}" for more in rest)
    lines.append("")
    if item.action == Action.WINGET and item.updatable:
        lines.append("How: winget upgrades it (Ctrl+U). Its installer may show a prompt.")
    elif item.action == Action.WU and item.updatable:
        lines.append("How: Windows Update installs it, after an administrator prompt (Ctrl+U).")
    elif item.status == Status.OLD:
        lines.append("How: " + (vendor_hint or "check the device maker's site."))
    elif item.status == Status.UNTRACKED:
        lines.append("How: the program's own Check for updates, or its publisher's site.")
    elif item.status == Status.UNKNOWN:
        lines.append("The source that would know did not answer in the last scan.")
    return "\n".join(lines)


__all__ = ["MainWindow", "describe", "DISABLED", "HIDDEN"]
