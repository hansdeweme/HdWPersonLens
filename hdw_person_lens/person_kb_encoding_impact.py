"""Read-only encoding impact panel for a reviewed KB shortlist."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .kb_encoding_impact import build_encoding_impact
from .kb_reference_recommendations import source_snapshot


class PersonKBEncodingImpactPanel(QWidget):
    image_requested = pyqtSignal(str)

    def __init__(self, person_service, parent=None):
        super().__init__(parent)
        self.service = person_service
        self.person, self.paths = "", []
        self.recommendations = None
        self._result = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel("Build a shortlist to preview proposed encoding inputs (read-only)")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.notice = QLabel("Existing face/body embeddings have no per-source provenance. Counts are not predicted outcomes.")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.results = QTreeWidget()
        self.results.setHeaderLabels(["KB image", "Proposal", "Why"])
        self.results.setMinimumHeight(140)
        self.results.itemDoubleClicked.connect(lambda item, _: self.image_requested.emit(item.data(0, Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.results)

    def set_person(self, name, paths):
        self.person, self.paths = name, list(paths)
        self.invalidate()

    def invalidate(self):
        self._result = None
        self.results.clear()
        self.summary.setText("Build a fresh shortlist to preview encoding inputs (read-only)")

    def set_shortlist(self, result):
        self.invalidate()
        if not self.person: return
        try:
            current_paths = self.service.get_person_image_paths(self.person)
            current = source_snapshot(current_paths)
            reports_current = (current == source_snapshot(self.paths) and
                               all(size is not None for _, size, _ in current) and
                               self.recommendations is not None and self.recommendations._person == self.person and
                               self.recommendations._paths == self.paths and self.recommendations._reports_current())
            state = self.service.get_person_state(self.person)
            if not state.database_record_exists: reports_current = False
            preview = build_encoding_impact(self.paths, result, face_encodings=state.face_encodings,
                                            body_encodings=state.body_encodings, evidence_current=reports_current)
        except (OSError, ValueError, TypeError) as exc:
            self.summary.setText(f"Encoding impact unavailable: {exc}")
            return
        self._result = preview if preview["status"] == "preview_ready" else None
        if self._result is None:
            self.summary.setText(f"Encoding impact unavailable: {preview['reason']}")
            return
        self.summary.setText(f"Current KB inputs: {preview['current_images']} · Proposed: {preview['proposed_images']} · "
                             f"Omitted: {preview['omitted_images']} · Existing embeddings: "
                             f"{preview['existing_face_encodings']} face / {preview['existing_body_encodings']} body")
        for row in preview["rows"]:
            item = QTreeWidgetItem([Path(row["path"]).name, row["action"], row["reason"]])
            item.setData(0, Qt.ItemDataRole.UserRole, row["path"])
            item.setToolTip(0, row["path"])
            self.results.addTopLevelItem(item)
