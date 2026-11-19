"""No-write shortlist panel combining existing quality and identity reports."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .kb_reference_recommendations import build_recommendations, source_snapshot


class PersonKBRecommendationPanel(QWidget):
    """Displays provisional suggestions; does not write files or selection decisions."""
    def __init__(self, settings=None, parent=None, *, source_getter=None):
        super().__init__(parent)
        self.target_size = max(1, int((settings or {}).get("kb_gallery_target_size", 12)))
        self._paths = []
        self._person = ""
        self._source_getter = source_getter
        self._collection = None
        self._identity = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        self.button = QPushButton("Build Reference Shortlist")
        self.button.setEnabled(False)
        self.button.clicked.connect(self.build)
        header.addWidget(self.button)
        self.summary = QLabel("Run collection and identity analyses first · no KB changes")
        self.summary.setWordWrap(True)
        header.addWidget(self.summary, 1)
        layout.addLayout(header)
        self.results = QTreeWidget()
        self.results.setHeaderLabels(["Image", "Tech score", "Proposal", "Why"])
        self.results.setMinimumHeight(170)
        self.results.setMaximumHeight(310)
        layout.addWidget(self.results)

    def set_person(self, name, paths):
        self._person = name
        self._paths = list(paths)
        self._collection = self._identity = None
        self.results.clear()
        self._update_ready()

    def invalidate_collection(self):
        self._collection = None
        self.results.clear()
        self._update_ready()

    def invalidate_identity(self):
        self._identity = None
        self.results.clear()
        self._update_ready()

    def set_collection(self, result):
        self._collection = result
        self.results.clear()
        self._update_ready()

    def set_identity(self, result):
        self._identity = result
        self.results.clear()
        self._update_ready()

    def _reports_current(self):
        try:
            paths = self._source_getter(self._person) if self._source_getter and self._person else self._paths
            current = source_snapshot(paths)
        except (OSError, ValueError):
            return False
        if current != source_snapshot(self._paths) or any(size is None for _, size, _ in current):
            return False
        return all(report is not None and report.get("source_snapshot") == current
                   for report in (self._collection, self._identity))

    def _update_ready(self):
        reports_ready = bool(self._collection is not None and self._identity is not None and self._paths)
        ready = reports_ready and self._reports_current()
        self.button.setEnabled(ready)
        self.summary.setText("Both analyses ready - suggestions remain provisional" if ready else
                             "Run collection and identity analyses first - no KB changes")
        if reports_ready and not ready:
            self.summary.setText("KB sources changed or reports are stale; refresh or rerun both analyses")

    def build(self):
        if self._collection is None or self._identity is None: return
        if not self._reports_current():
            self._collection = self._identity = None
            self.results.clear()
            self._update_ready()
            self.summary.setText("KB images changed since analysis; refresh or rerun both analyses")
            return
        result = build_recommendations(self._collection, self._identity, target_size=self.target_size)
        self.summary.setText(f"{result['shortlisted']} proposed / {self.target_size} target · {result['reason']}")
        self.results.clear()
        for row in result["rows"]:
            item = QTreeWidgetItem([Path(row["path"]).name, f"{row['score']:.3f}",
                                    row["recommendation"].title(), row["reason"]])
            item.setToolTip(0, row["path"])
            self.results.addTopLevelItem(item)
