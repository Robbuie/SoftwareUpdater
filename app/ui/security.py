"""The Security section: this computer's protections, each judged, with the
place to fix it one click away (`core/security.py` decides; this shows).

Runs its checks the first time it is opened and on Check again. Fix opens the
Windows page where that setting lives; it never changes a setting itself.
"""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core import security, work
from app.core.security import LEVEL_LABELS, Finding
from app.ui.colour import parse_colour
from app.ui.commands import State

#: Colours by level: the semantic tokens, never the accent. "bad" borrows the
#: family's fixed deletion red from the diff palette.
LEVEL_TOKENS = {security.GOOD: "good", security.INFO: "txt_1", security.WARN: "warn",
                security.BAD: "diff_del_bar", security.UNKNOWN: "txt_2"}


class SecurityPage(QWidget):
    kind = "security"

    def __init__(self, window) -> None:
        super().__init__()
        self.window = window
        self._tokens: dict[str, str] = {}
        self._request = 0
        self._defender_request = 0
        self.facts: dict = {}
        self.findings: list[Finding] = []
        self._started = False

        self.summary = QLabel("Not checked yet.")
        self.summary.setProperty("role", "note")
        head = QWidget()
        head.setProperty("role", "folderbar")
        head.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(head)
        row.setContentsMargins(10, 6, 10, 6)
        row.addWidget(self.summary, 1)

        self.list = QTreeWidget()
        self.list.setProperty("role", "foldertree")
        self.list.setRootIsDecorated(False)
        self.list.setHeaderLabels(["", "Check", "Finding"])
        self.list.setColumnWidth(0, 92)
        self.list.setColumnWidth(1, 220)
        self.list.itemSelectionChanged.connect(self._selected)
        self.list.itemDoubleClicked.connect(lambda *_: self.fix())

        self.details = QPlainTextEdit()
        self.details.setProperty("role", "passage")
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Select a check to see what it means and how to fix it.")

        card = QWidget()
        card.setProperty("role", "card")
        card.setAttribute(Qt.WA_StyledBackground, True)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)
        inner.addWidget(head)
        inner.addWidget(self.list, 1)

        split = QSplitter(Qt.Vertical)
        split.addWidget(card)
        split.addWidget(self.details)
        split.setSizes([560, 200])
        column = QVBoxLayout(self)
        column.setContentsMargins(10, 8, 10, 6)
        column.addWidget(split, 1)

    def activated(self) -> None:
        if not self._started:
            self._started = True
            self.check()

    def busy(self) -> bool:
        return bool(self._request or self._defender_request)

    def stop(self) -> None:
        if self._request:
            self.window.cancel(self._request)

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        self._tokens = tokens
        self._paint()

    # -------------------------------------------------------------- commands

    def current(self) -> Finding | None:
        items = self.list.selectedItems()
        return items[0].data(0, Qt.UserRole) if items else None

    def command_state(self, id_: str) -> State | None:
        if id_ == "sec-check":
            return State(enabled=not self.busy())
        if id_ == "sec-fix":
            finding = self.current()
            label = finding.fix_label if finding and finding.fix_label else None
            return State(enabled=bool(finding and (finding.fix_target or finding.action))
                         and not self.busy(), label=label)
        if id_ == "stop":
            return State(visible=self.busy())
        return None

    def run_command(self, id_: str) -> bool:
        if id_ == "sec-check":
            self.check()
        elif id_ == "sec-fix":
            self.fix()
        elif id_ == "stop":
            self.stop()
        else:
            return False
        return True

    def check(self) -> None:
        if self.busy():
            return
        self.summary.setText("Checking...")
        self._request = self.window.submit(work.security_facts)
        self.window.refresh_chrome()

    def refresh_from_inventory(self) -> None:
        """The Software page finished a scan: browsers and Windows updates
        feed two of the findings."""
        if self.facts:
            self._show(self.facts)

    def fix(self) -> None:
        finding = self.current()
        if finding is None:
            return
        if finding.action == "defender-update":
            self.window.say("Updating Defender's definitions as administrator. Answer the "
                            "Windows prompt to continue.")
            self._defender_request = self.window.submit(work.defender_update)
        elif finding.action == "show-software":
            self.window.show_section("software")
        elif finding.fix_target:
            self.window.submit(work.open_target, finding.fix_target, finding.fix_args)
        self.window.refresh_chrome()

    # --------------------------------------------------------------- display

    def _show(self, facts: dict) -> None:
        self.facts = facts
        self.findings = security.evaluate(facts, today=_dt.date.today(),
                                          items=self.window.software_items())
        keep = self.current().id if self.current() else ""
        self.list.clear()
        for finding in self.findings:
            item = QTreeWidgetItem([LEVEL_LABELS.get(finding.level, finding.level),
                                    finding.title, finding.summary])
            item.setData(0, Qt.UserRole, finding)
            item.setToolTip(2, finding.summary)
            self.list.addTopLevelItem(item)
            if finding.id == keep:
                item.setSelected(True)
        counts = {level: sum(1 for f in self.findings if f.level == level)
                  for level in LEVEL_LABELS}
        parts = []
        if counts[security.BAD]:
            parts.append(f"{counts[security.BAD]} risk(s)")
        if counts[security.WARN]:
            parts.append(f"{counts[security.WARN]} to look at")
        parts.append(f"{counts[security.GOOD]} OK")
        self.summary.setText("  ·  ".join(parts))
        self._paint()

    def _paint(self) -> None:
        if not self._tokens:
            return
        for index in range(self.list.topLevelItemCount()):
            item = self.list.topLevelItem(index)
            finding = item.data(0, Qt.UserRole)
            colour = parse_colour(self._tokens.get(LEVEL_TOKENS.get(finding.level, "txt_2"),
                                                   self._tokens["txt_1"]))
            item.setForeground(0, colour)
            font = item.font(0)
            font.setBold(finding.level in (security.BAD, security.WARN))
            item.setFont(0, font)

    def _selected(self) -> None:
        finding = self.current()
        if finding is None:
            self.details.setPlainText("")
        else:
            lines = [finding.title, "", finding.summary]
            if finding.detail:
                lines += ["", finding.detail]
            if finding.fix_label:
                lines += ["", f"Fix: {finding.fix_label} (double-click the row)."]
            self.details.setPlainText("\n".join(lines))
        self.window.refresh_chrome()

    # ---------------------------------------------------------------- loader

    def handle_progress(self, request: int, payload) -> bool:
        return request in (self._request, self._defender_request) and bool(request)

    def handle_finished(self, request: int, envelope) -> bool:
        if request == self._request and request:
            self._request = 0
            if envelope.ok:
                self._show(envelope.value or {})
            else:
                self.summary.setText("The checks could not run: "
                                     + (envelope.error.splitlines() or [""])[0])
        elif request == self._defender_request and request:
            self._defender_request = 0
            error = envelope.value if envelope.ok else envelope.error
            self.window.say(f"Defender definitions: {error or 'updated'}.")
            self.check()
        else:
            return False
        self.window.refresh_chrome()
        return True
