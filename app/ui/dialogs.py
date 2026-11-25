"""Dialogs that ask before something is removed.

Both show exactly what will happen, row by row, with a box to untick. A
removal this application performs is never a single "Are you sure?": the
person sees the list.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from app.core.cleanup import size_text


class ChecklistDialog(QDialog):
    """A list of rows with boxes, a heading, a note, and two buttons."""

    def __init__(self, parent, *, title: str, heading: str, note: str, columns: list[str],
                 rows: list[tuple[object, list[str], bool]], accept: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 420)
        layout = QVBoxLayout(self)
        top = QLabel(heading)
        top.setWordWrap(True)
        layout.addWidget(top)
        self.tree = QTreeWidget()
        self.tree.setProperty("role", "foldertree")
        self.tree.setRootIsDecorated(False)
        self.tree.setHeaderLabels(columns)
        self.tree.setColumnWidth(0, 420)
        for data, values, checked in rows:
            item = QTreeWidgetItem(values)
            item.setData(0, Qt.UserRole, data)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
            item.setToolTip(0, values[0])
            self.tree.addTopLevelItem(item)
        layout.addWidget(self.tree, 1)
        if note:
            bottom = QLabel(note)
            bottom.setProperty("role", "note")
            bottom.setWordWrap(True)
            layout.addWidget(bottom)
        buttons = QDialogButtonBox()
        go = buttons.addButton(accept, QDialogButtonBox.AcceptRole)
        go.setProperty("role", "primary")
        buttons.addButton("Cancel", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def chosen(self) -> list:
        out = []
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.checkState(0) == Qt.Checked:
                out.append(item.data(0, Qt.UserRole))
        return out


def leftovers(parent, name: str, found) -> list:
    """Ask which of a removed program's leftovers go. Returns the chosen
    `Leftover`s, or [] when cancelled."""
    rows = []
    for leftover in found.folders:
        rows.append((leftover, [leftover.path, size_text(leftover.size), leftover.why], True))
    for leftover in found.keys:
        rows.append((leftover, [leftover.path, "", leftover.why], True))
    dialog = ChecklistDialog(
        parent, title="Leftovers",
        heading=f"{name} is uninstalled. It left these behind:",
        note="Folders go to the Recycle Bin, so they can be restored. Registry keys are "
             "saved to a .reg file in %LOCALAPPDATA%\\SoftwareUpdater\\backups before they "
             "are deleted; double-click that file to put a key back.",
        columns=["Where", "Size", "Why it is listed"], rows=rows, accept="Remove ticked")
    return dialog.chosen() if dialog.exec() == QDialog.Accepted else []
