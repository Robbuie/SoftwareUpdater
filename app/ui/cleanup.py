"""The Cleanup section: disposable files by kind, and where the space went.

Two views, switched from the command row as File Compare switches layouts:

- **Clean up** -- every `core/cleanup.py` target under its group, with a
  box, its size once measured, and what it is. Clean removes the ticked
  ones: those that need no rights straight away, the rest in one elevated
  run after one prompt.
- **Find space** -- a folder's tree by size (the user's profile by default),
  and the forgotten files in Downloads. What is picked goes to the Recycle
  Bin.

Every measurement and every removal is a job on the window's loader.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core import cleanup, work
from app.core.cleanup import size_text
from app.ui.colour import parse_colour
from app.ui.commands import State

DataRole = Qt.UserRole
SizeRole = Qt.UserRole + 1


class SizeItem(QTreeWidgetItem):
    """Sorts the size column by bytes, not by its text."""

    def __lt__(self, other) -> bool:
        tree = self.treeWidget()
        column = tree.sortColumn() if tree else 0
        mine, theirs = self.data(column, SizeRole), other.data(column, SizeRole)
        if mine is not None and theirs is not None:
            return mine < theirs
        return super().__lt__(other)


class CleanupPage(QWidget):
    kind = "cleanup"

    def __init__(self, window) -> None:
        super().__init__()
        self.window = window
        self._tokens: dict[str, str] = {}
        self.view = "targets"
        self._measure_request = 0
        self._clean_request = 0
        self._space_request = 0
        self._forgotten_request = 0
        self._recycle_request = 0
        self._free_request = 0
        self.measured: dict[str, cleanup.Measured] = {}
        self._started = False
        self._space_tree = None

        self.free = QLabel()
        self.free.setProperty("role", "note")
        self.status = QLabel()
        self.status.setProperty("role", "note")
        head = QWidget()
        head.setProperty("role", "folderbar")
        head.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(head)
        row.setContentsMargins(10, 6, 10, 6)
        row.addWidget(self.free)
        row.addStretch(1)
        row.addWidget(self.status)

        # Clean up.
        self.targets = QTreeWidget()
        self.targets.setProperty("role", "foldertree")
        self.targets.setHeaderLabels(["What", "Size", "Files", "About it"])
        self.targets.setColumnWidth(0, 330)
        self.targets.setColumnWidth(1, 100)
        self.targets.setColumnWidth(2, 80)
        self.targets.itemChanged.connect(lambda *_: self.window.refresh_chrome())
        self._target_items: dict[str, QTreeWidgetItem] = {}
        self._group_items: dict[str, QTreeWidgetItem] = {}
        for group in cleanup.GROUPS:
            parent = QTreeWidgetItem([group])
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            parent.setFlags(Qt.ItemIsEnabled)
            self.targets.addTopLevelItem(parent)
            self._group_items[group] = parent
            for target in [t for t in cleanup.TARGETS if t.group == group]:
                about = target.note + ("  Needs administrator rights." if target.admin else "")
                item = SizeItem([target.label, "", "", about])
                item.setData(0, DataRole, target.id)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Checked if target.default else Qt.Unchecked)
                item.setToolTip(3, about)
                item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                item.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
                parent.addChild(item)
                self._target_items[target.id] = item
            parent.setExpanded(True)

        # Find space.
        self.path = QLineEdit()
        self.path.setProperty("role", "pathbox")
        self.path.setPlaceholderText("A folder on a local drive")
        self.path.returnPressed.connect(self.scan_space)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.setContentsMargins(10, 6, 10, 6)
        path_row.addWidget(QLabel("Folder"))
        path_row.addWidget(self.path, 1)
        path_row.addWidget(browse)
        self.folders = QTreeWidget()
        self.folders.setProperty("role", "foldertree")
        self.folders.setHeaderLabels(["Folder", "Size", "Files", "Share"])
        self.folders.setColumnWidth(0, 360)
        self.folders.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.folders.itemExpanded.connect(self._expand)
        self.folders.itemSelectionChanged.connect(self.window.refresh_chrome)
        self.downloads = QTreeWidget()
        self.downloads.setProperty("role", "foldertree")
        self.downloads.setHeaderLabels(["Forgotten in Downloads", "Size", "Modified", "Why"])
        self.downloads.setRootIsDecorated(False)
        self.downloads.setColumnWidth(0, 300)
        self.downloads.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.downloads.setSortingEnabled(True)
        self.downloads.itemSelectionChanged.connect(self.window.refresh_chrome)
        space_split = QSplitter(Qt.Horizontal)
        space_split.addWidget(self.folders)
        space_split.addWidget(self.downloads)
        space_split.setSizes([640, 520])
        space = QWidget()
        space_column = QVBoxLayout(space)
        space_column.setContentsMargins(0, 0, 0, 0)
        space_column.addLayout(path_row)
        space_column.addWidget(space_split, 1)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.targets)
        self.stack.addWidget(space)

        column = QVBoxLayout(self)
        column.setContentsMargins(10, 8, 10, 6)
        column.setSpacing(6)
        card = QWidget()
        card.setProperty("role", "card")
        card.setAttribute(Qt.WA_StyledBackground, True)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)
        inner.addWidget(head)
        inner.addWidget(self.stack, 1)
        column.addWidget(card, 1)

    # ----------------------------------------------------------------- state

    def activated(self) -> None:
        if not self._started:
            self._started = True
            self.measure()
            self._free_request = self.window.submit(work.free_space)
            self.path.setText(self.window.home_folder())

    def busy(self) -> bool:
        return bool(self._measure_request or self._clean_request or self._space_request
                    or self._recycle_request)

    def stop(self) -> None:
        for request in (self._measure_request, self._clean_request, self._space_request,
                        self._forgotten_request):
            if request:
                self.window.cancel(request)

    def checked(self) -> list[str]:
        return [ident for ident, item in self._target_items.items()
                if item.checkState(0) == Qt.Checked]

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        self._tokens = tokens
        self._paint_sizes()

    # -------------------------------------------------------------- commands

    def command_state(self, id_: str) -> State | None:
        if id_ == "clean-targets":
            return State(checked=self.view == "targets")
        if id_ == "clean-space":
            return State(checked=self.view == "space")
        if id_ == "clean-measure":
            return State(enabled=not self.busy(), visible=self.view == "targets")
        if id_ == "clean-run":
            n = len(self.checked())
            return State(enabled=n > 0 and not self.busy(), visible=self.view == "targets")
        if id_ == "space-scan":
            return State(enabled=not self.busy(), visible=self.view == "space")
        if id_ in ("space-recycle", "space-reveal"):
            n = len(self._picked())
            return State(enabled=n > 0 and not self.busy(), visible=self.view == "space",
                         count=(n or None) if id_ == "space-recycle" else None)
        if id_ == "stop":
            return State(visible=self.busy())
        return None

    def run_command(self, id_: str) -> bool:
        actions = {
            "clean-targets": lambda: self._switch("targets"),
            "clean-space": lambda: self._switch("space"),
            "clean-measure": self.measure,
            "clean-run": self.clean,
            "space-scan": self.scan_space,
            "space-recycle": self.recycle,
            "space-reveal": self.reveal,
            "stop": self.stop,
        }
        action = actions.get(id_)
        if action is None:
            return False
        action()
        return True

    def _switch(self, view: str) -> None:
        self.view = view
        self.stack.setCurrentIndex(0 if view == "targets" else 1)
        if view == "space" and self._space_tree is None and not self._space_request:
            self.scan_space()

    # --------------------------------------------------------------- targets

    def measure(self) -> None:
        if self.busy():
            return
        for item in self._target_items.values():
            item.setText(1, "...")
            item.setText(2, "")
        self.status.setText("Measuring...")
        self._measure_request = self.window.submit(work.measure, list(self._target_items))
        self.window.refresh_chrome()

    def _measured(self, result: cleanup.Measured) -> None:
        self.measured[result.target] = result
        item = self._target_items.get(result.target)
        if item is None:
            return
        item.setText(1, size_text(result.bytes))
        item.setData(1, SizeRole, result.bytes if result.bytes is not None else -1)
        item.setText(2, f"{result.files:,}" if result.files else "")
        if result.note:
            item.setToolTip(1, result.note)
        self._paint_sizes()

    def _paint_sizes(self) -> None:
        if not self._tokens:
            return
        big = 1024 ** 3
        for ident, item in self._target_items.items():
            got = self.measured.get(ident)
            token = "warn" if got and got.bytes and got.bytes >= big else "txt_1"
            item.setForeground(1, parse_colour(self._tokens[token]))

    def _total(self, ids: list[str]) -> int:
        return sum((self.measured.get(i).bytes or 0) for i in ids if self.measured.get(i))

    def clean(self) -> None:
        ids = self.checked()
        if not ids or self.busy():
            return
        lines = []
        for ident in ids:
            target = cleanup.BY_ID[ident]
            got = self.measured.get(ident)
            lines.append(f"{target.label}: {size_text(got.bytes) if got else 'not measured'}"
                         + ("  (administrator)" if target.admin else ""))
        admin = any(cleanup.BY_ID[i].admin for i in ids)
        box = QMessageBox(self)
        box.setWindowTitle("Clean up")
        box.setText(f"Remove {len(ids)} kind(s) of files, about {size_text(self._total(ids))}?")
        notes = ["These are deleted, not sent to the Recycle Bin: they are temporary files and "
                 "caches their programs recreate. Files in use are skipped."]
        if "recycle-bin" in ids:
            notes.append("Emptying the Recycle Bin cannot be undone.")
        if admin:
            notes.append("Some of these need administrator rights: Windows will ask once.")
        box.setInformativeText("\n\n".join(notes))
        box.setDetailedText("\n".join(lines))
        go = box.addButton("Clean", QMessageBox.AcceptRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not go:
            return
        self.status.setText("Cleaning...")
        self.window.say(f"Cleaning: {', '.join(cleanup.BY_ID[i].label for i in ids)}")
        self._cleaned_bytes = 0
        self._clean_request = self.window.submit(work.clean, ids)
        self.window.refresh_chrome()

    def _cleaned(self, result: cleanup.Cleaned) -> None:
        label = cleanup.BY_ID[result.target].label if result.target in cleanup.BY_ID else result.target
        self._cleaned_bytes = getattr(self, "_cleaned_bytes", 0) + result.bytes
        text = f"{label}: freed {size_text(result.bytes)}"
        if result.files:
            text += f" ({result.files:,} files"
            text += f", {result.skipped:,} in use and left)" if result.skipped else ")"
        if result.error:
            text += f". {result.error}"
        self.window.say(text)
        item = self._target_items.get(result.target)
        if item is not None:
            item.setText(1, "Cleaned" if not result.error else "See log")

    # ----------------------------------------------------------------- space

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Folder to look in", self.path.text())
        if folder:
            self.path.setText(folder.replace("/", "\\"))
            self.scan_space()

    def scan_space(self) -> None:
        root = self.path.text().strip()
        if not root or self.busy():
            return
        if root.startswith("\\\\"):
            self.window.flash("Network locations are not scanned; pick a folder on a local drive.")
            return
        self.folders.clear()
        self._space_tree = None
        self.status.setText(f"Looking in {root}...")
        self._space_started = time.monotonic()
        self._space_request = self.window.submit(work.scan_space, root)
        if not self._forgotten_request and not self.downloads.topLevelItemCount():
            self._forgotten_request = self.window.submit(work.forgotten)
        self.window.refresh_chrome()

    def _show_tree(self, tree) -> None:
        self._space_tree = tree
        self.folders.clear()
        root = self._node_item(tree, tree.size)
        self.folders.addTopLevelItem(root)
        root.setExpanded(True)
        took = time.monotonic() - getattr(self, "_space_started", time.monotonic())
        self.status.setText(f"{size_text(tree.size)} in {tree.files:,} files, {took:.0f} s")

    def _node_item(self, node, whole: int) -> QTreeWidgetItem:
        share = f"{node.size / whole * 100:.0f} %" if whole else ""
        item = SizeItem([node.name, size_text(node.size), f"{node.files:,}", share])
        item.setData(0, DataRole, node)
        item.setData(1, SizeRole, node.size)
        item.setToolTip(0, node.path)
        item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        if node.children:
            item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
        return item

    def _expand(self, item: QTreeWidgetItem) -> None:
        if item.childCount():
            return
        node = item.data(0, DataRole)
        whole = self._space_tree.size if self._space_tree else 0
        for child in node.sorted_children()[:200]:
            item.addChild(self._node_item(child, whole))

    def _show_forgotten(self, found) -> None:
        self.downloads.clear()
        for entry in found[:500]:
            name = entry.path.rsplit("\\", 1)[-1]
            item = SizeItem([name, size_text(entry.size),
                             time.strftime("%Y-%m-%d", time.localtime(entry.modified)), entry.why])
            item.setData(0, DataRole, entry.path)
            item.setData(1, SizeRole, entry.size)
            item.setToolTip(0, entry.path)
            self.downloads.addTopLevelItem(item)
        self.downloads.sortItems(1, Qt.DescendingOrder)

    def _picked(self) -> list[str]:
        paths = []
        for item in self.folders.selectedItems():
            node = item.data(0, DataRole)
            if node is not None and item.parent() is not None:   # never the scanned root
                paths.append(node.path)
        for item in self.downloads.selectedItems():
            paths.append(item.data(0, DataRole))
        return paths

    def recycle(self) -> None:
        paths = self._picked()
        if not paths:
            return
        answer = QMessageBox.question(
            self, "Recycle",
            f"Send {len(paths)} item(s) to the Recycle Bin?\n\n" + "\n".join(paths[:12])
            + ("\n..." if len(paths) > 12 else ""),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self._recycle_request = self.window.submit(work.recycle, paths)
        self.window.refresh_chrome()

    def reveal(self) -> None:
        paths = self._picked()
        if paths:
            def go(job, path):
                from app.io import system

                return system.reveal(path)

            self.window.submit(go, paths[0])

    # ---------------------------------------------------------------- loader

    def handle_progress(self, request: int, payload) -> bool:
        if request == self._measure_request and payload[0] == "measured":
            self._measured(payload[1])
            return True
        if request == self._clean_request:
            if payload[0] == "cleaned":
                self._cleaned(payload[1])
            elif payload[0] == "elevating":
                self.window.say(f"Cleaning {payload[1]} system location(s) as administrator. "
                                "Answer the Windows prompt to continue.")
            return True
        if request == self._space_request and payload[0] == "space":
            self.status.setText(f"Looking... {payload[1]:,} files, {size_text(payload[2])}")
            return True
        return False

    def handle_finished(self, request: int, envelope) -> bool:
        if request == self._measure_request:
            self._measure_request = 0
            total = sum((m.bytes or 0) for m in self.measured.values())
            self.status.setText(f"About {size_text(total)} could be freed" if envelope.ok
                                else "Measuring stopped.")
        elif request == self._clean_request:
            self._clean_request = 0
            self.window.say(f"Cleanup finished: {size_text(getattr(self, '_cleaned_bytes', 0))} "
                            "freed.")
            self.status.setText(f"Freed {size_text(getattr(self, '_cleaned_bytes', 0))}")
            self._free_request = self.window.submit(work.free_space)
            if not self.busy():
                self.measure()
        elif request == self._space_request:
            self._space_request = 0
            if envelope.ok:
                self._show_tree(envelope.value)
            else:
                self.status.setText(envelope.error.splitlines()[0] if envelope.error else "")
        elif request == self._forgotten_request:
            self._forgotten_request = 0
            if envelope.ok:
                self._show_forgotten(envelope.value or [])
        elif request == self._recycle_request:
            self._recycle_request = 0
            if envelope.ok:
                done, failed = envelope.value
                self.window.say(f"Recycled {len(done)} item(s).")
                for path, why in failed.items():
                    self.window.say(f"Not recycled: {path}: {why}")
                if done:
                    self.scan_space()
        elif request == self._free_request:
            self._free_request = 0
            if envelope.ok:
                drive, free, total = envelope.value
                if total:
                    self.free.setText(f"{drive}  {size_text(free)} free of {size_text(total)}")
        else:
            return False
        self.window.refresh_chrome()
        return True
