"""Guided, non-destructive image curation panel for the Persons Workbench."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QStandardPaths, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .kb_curation_review import ReviewDecisionStore, evidence_rows
from .kb_reference_recommendations import source_snapshot


class PersonKBCurationPanel(QWidget):
    image_requested = pyqtSignal(str)

    def __init__(self, parent=None, *, store_path=None):
        super().__init__(parent)
        base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        self.store = ReviewDecisionStore(store_path or str(Path(base) / "kb_curation_reviews.json"))
        self.person, self.paths = "", []
        self.collection = self.identity = self.shortlist = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel("Select a person to review KB images · advisory decisions only")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.list = QTreeWidget()
        self.list.setHeaderLabels(["KB image", "Assessment findings", "Decision"])
        self.list.setMinimumHeight(180)
        self.list.itemSelectionChanged.connect(self._update_buttons)
        self.list.itemDoubleClicked.connect(lambda item, _: self.image_requested.emit(item.data(0, Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        self.inspect_button = QPushButton("Inspect in Gallery")
        self.inspect_button.clicked.connect(self._inspect)
        buttons.addWidget(self.inspect_button)
        self.buttons = {}
        for decision, label in (("keep", "Keep"), ("later", "Review Later"), ("exclude", "Mark Exclude (Advisory)")):
            button = QPushButton(label)
            button.clicked.connect(lambda _, d=decision: self._decide(d))
            buttons.addWidget(button)
            self.buttons[decision] = button
        layout.addLayout(buttons)
        self._render()

    def set_person(self, name, paths):
        self.person, self.paths = name, list(paths)
        self.collection = self.identity = self.shortlist = None
        self._render()

    def invalidate_collection(self):
        self.collection = self.shortlist = None
        self._render()

    def invalidate_identity(self):
        self.identity = self.shortlist = None
        self._render()

    def invalidate_shortlist(self):
        self.shortlist = None
        self._render()

    def set_collection(self, report):
        self.collection = report
        self._render()

    def set_identity(self, report):
        self.identity = report
        self._render()

    def set_shortlist(self, report):
        self.shortlist = report
        self._render()

    def _selected(self):
        items = self.list.selectedItems()
        return items[0].data(0, Qt.ItemDataRole.UserRole) if items else None

    def _inspect(self):
        if self._selected(): self.image_requested.emit(self._selected())

    def _decide(self, decision):
        path = self._selected()
        if not self.person or not path: return
        signature = next((r["signature"] for r in evidence_rows([path]) if r["path"] == path), None)
        if signature is None or path not in self.paths:
            QMessageBox.warning(self, "Source changed", "This image is missing or unavailable. Refresh the person before reviewing.")
            return
        displayed = self.list.selectedItems()[0].data(0, int(Qt.ItemDataRole.UserRole) + 1)
        if signature != displayed:
            self._render(select=path)
            QMessageBox.warning(self, "Source changed", "This image changed since the queue was displayed. Inspect it again before recording a decision.")
            return
        try: self.store.set(self.person, path, signature, decision)
        except OSError as exc:
            QMessageBox.warning(self, "Review not saved", str(exc))
            return
        self._render(select=path)

    def _update_buttons(self):
        selected = bool(self._selected())
        self.inspect_button.setEnabled(selected)
        for button in self.buttons.values(): button.setEnabled(selected)

    def _render(self, select=None):
        select = select or self._selected()
        current = source_snapshot(self.paths)
        reports = [report if report is not None and report.get("source_snapshot") == current else None
                   for report in (self.collection, self.identity)]
        shortlist = self.shortlist if all(reports) else None
        rows = evidence_rows(self.paths, reports[0], reports[1], shortlist)
        self.list.clear()
        reviewed, stale = 0, 0
        for row in rows:
            decision, current = self.store.get(self.person, row["path"], row["signature"])
            if decision and current: reviewed += 1
            if decision and not current: stale += 1
            label = (decision.replace("exclude", "excluded").title() if current else "Needs re-review") if decision else "Unreviewed"
            item = QTreeWidgetItem([Path(row["path"]).name, ", ".join(row["findings"]) or "No finding yet", label])
            item.setData(0, Qt.ItemDataRole.UserRole, row["path"])
            item.setData(0, int(Qt.ItemDataRole.UserRole) + 1, row["signature"])
            item.setToolTip(0, row["path"])
            self.list.addTopLevelItem(item)
            if row["path"] == select: self.list.setCurrentItem(item)
        ready = sum(r is not None for r in (*reports, shortlist))
        self.summary.setText(f"{reviewed}/{len(rows)} reviewed · {stale} require re-review · {ready}/3 evidence stages ready · "
                             "decisions are advisory; images, preferences and recognition caches are unchanged")
        self._update_buttons()
