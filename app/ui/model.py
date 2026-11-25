"""The list of rows: a table model over `core.inventory.Item`, and the proxy
that filters and sorts it.

Colour comes from the theme's semantic tokens -- `warn` for something to do,
`good` for done or current, `txt_2` for what nothing here can judge -- and
never from the accent, for the reason File Manager gives: the accent is the
user's choice of chrome colour, and "needs an update" must not change meaning
when the picker moves.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QFont

from app.core import inventory, versions
from app.core.inventory import KIND_LABELS, STATUS_LABELS, STATUS_ORDER, Item, Status
from app.ui.colour import parse_colour

COLUMNS = ("Name", "Kind", "Installed", "Available", "Status", "Source")
NAME, KIND, INSTALLED, AVAILABLE, STATUS, SOURCE = range(len(COLUMNS))

#: The item behind a row, for the window.
ItemRole = Qt.UserRole + 1
SortRole = Qt.UserRole + 2


class ItemModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.items: list[Item] = []
        #: Rows being updated right now, by key, with what to show.
        self.busy: dict[str, str] = {}
        self._tokens: dict[str, str] = {}
        self._bold = QFont()
        self._bold.setBold(True)

    def set_items(self, items: list[Item]) -> None:
        self.beginResetModel()
        self.items = list(items)
        self.endResetModel()

    def set_tokens(self, tokens: dict[str, str]) -> None:
        self._tokens = tokens
        if self.items:
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(len(self.items) - 1, len(COLUMNS) - 1))

    def changed(self, key: str) -> None:
        for row, item in enumerate(self.items):
            if item.key == key:
                self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLUMNS) - 1))

    def item(self, key: str) -> Item | None:
        for item in self.items:
            if item.key == key:
                return item
        return None

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt naming
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def status_text(self, item: Item) -> str:
        if item.key in self.busy:
            return self.busy[item.key]
        text = STATUS_LABELS.get(item.status, item.status)
        if item.status == Status.UPDATE and item.explicit:
            text += " (pinned)"
        return text

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        column = index.column()
        if role == Qt.DisplayRole:
            return (item.name, KIND_LABELS.get(item.kind, item.kind), item.installed,
                    item.available, self.status_text(item), item.source)[column]
        if role == ItemRole:
            return item
        if role == SortRole:
            if column in (INSTALLED, AVAILABLE):
                return str(versions.sort_key(item.installed if column == INSTALLED
                                             else item.available))
            if column == STATUS:
                return f"{STATUS_ORDER.get(item.status, 9)}{item.name.lower()}"
            return (item.name, KIND_LABELS.get(item.kind, ""), "", "", "", item.source)[
                column].lower()
        if role == Qt.ToolTipRole:
            if column == STATUS and item.note:
                return item.note
            if column == NAME:
                return item.name
            return None
        if role == Qt.ForegroundRole and column == STATUS and self._tokens:
            if item.key in self.busy:
                return parse_colour(self._tokens["accent_text"])
            token = {Status.UPDATE: "warn", Status.FAILED: "warn", Status.DONE: "good",
                     Status.CURRENT: "good", Status.OLD: "txt_1"}.get(item.status, "txt_2")
            return parse_colour(self._tokens[token])
        if role == Qt.ForegroundRole and column in (KIND, SOURCE) and self._tokens:
            return parse_colour(self._tokens["txt_1"])
        if role == Qt.FontRole and column == STATUS and item.status in (Status.UPDATE,
                                                                         Status.FAILED):
            return self._bold
        return None


class FilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.show = "updates"
        self.text = ""
        self.ignored: set[str] = set()
        self.setSortRole(SortRole)

    def configure(self, *, show: str | None = None, text: str | None = None,
                  ignored: set[str] | None = None) -> None:
        begin = getattr(self, "beginFilterChange", None)
        if begin is not None:
            begin()
        if show is not None:
            self.show = show
        if text is not None:
            self.text = text
        if ignored is not None:
            self.ignored = set(ignored)
        if begin is not None:
            # Qt 6.10 and later: the pair replaces invalidateFilter.
            self.endFilterChange()
        else:
            self.invalidateFilter()

    def filterAcceptsRow(self, row, parent) -> bool:  # noqa: N802
        model = self.sourceModel()
        item = model.items[row]
        return (inventory.visible(item, self.show, self.ignored)
                and inventory.matches(item, self.text))
