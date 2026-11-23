"""Read-only KB encoding provenance panel with asynchronous source verification."""
from __future__ import annotations

from pathlib import Path
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .kb_encoding_provenance import assess_provenance


class _ProvenanceSignals(QObject):
    ready = pyqtSignal(int, str, object, str)


class _ProvenanceJob(QRunnable):
    def __init__(self, generation, snapshot):
        super().__init__()
        self.setAutoDelete(False)
        self.generation, self.snapshot = generation, snapshot
        self.signals = _ProvenanceSignals()

    def run(self):
        try:
            result = assess_provenance(self.snapshot["folder"], self.snapshot["records"],
                face_count=self.snapshot["face_count"], body_count=self.snapshot["body_count"])
            error = ""
        except Exception as exc:
            result, error = None, str(exc) or exc.__class__.__name__
        self.signals.ready.emit(self.generation, self.snapshot["name"], result, error)


class PersonKBProvenancePanel(QWidget):
    image_requested = pyqtSignal(str)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.person = ""
        self._generation = 0
        self._jobs = {}
        self._stopping = False
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        self.summary = QLabel("Select a person to inspect saved recognition provenance")
        self.summary.setWordWrap(True)
        header.addWidget(self.summary, 1)
        self.refresh_button = QPushButton("Refresh provenance")
        self.refresh_button.clicked.connect(self.refresh)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)
        self.notice = QLabel("Historical face/body outcomes are not identity verification. Source freshness is checked against saved SHA-256 signatures.")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.results = QTreeWidget()
        self.results.setHeaderLabels(["KB image", "Source", "Face at encoding", "Body at encoding"])
        self.results.setMinimumHeight(140)
        self.results.itemDoubleClicked.connect(self._navigate_image)
        layout.addWidget(self.results)

    def _navigate_image(self, item, _column):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(path, str) and Path(path).is_file() and not Path(path).is_symlink():
            self.image_requested.emit(path)

    def set_person(self, person):
        self.person = person or ""
        self.invalidate()

    def invalidate(self):
        self._generation += 1
        self.results.clear()
        for generation, job in list(self._jobs.items()):
            if self._pool.tryTake(job): self._jobs.pop(generation, None)
        self.summary.setText("Select Refresh provenance to inspect saved encoding sources" if self.person else "Select a person")

    def refresh(self):
        if self._stopping or not self.person: return
        self.invalidate()
        try:
            snapshot = self.service.get_reference_provenance(self.person)
        except Exception as exc:
            self.summary.setText(f"Provenance temporarily unavailable: {exc}")
            return
        if snapshot["records"] is None:
            self.summary.setText(f"Legacy encodings · {snapshot['face_count']} face / {snapshot['body_count']} body · source provenance unavailable")
            return
        generation = self._generation
        job = _ProvenanceJob(generation, snapshot)
        job.signals.ready.connect(self._ready)
        self._jobs[generation] = job
        self.summary.setText("Checking saved image signatures…")
        self._pool.start(job)

    def _ready(self, generation, name, report, error):
        self._jobs.pop(generation, None)
        if self._stopping or generation != self._generation or name != self.person: return
        if error:
            self.summary.setText(f"Provenance unavailable: {error}")
            return
        self.summary.setText(report["summary"])
        tones = {"Current": "#5cbe9c", "Changed": "#e1ad63", "Missing": "#e17c85", "Unreadable": "#e17c85"}
        for row in report["rows"]:
            item = QTreeWidgetItem([row["image"], row["freshness"], row["face"], row["body"]])
            item.setData(0, Qt.ItemDataRole.UserRole, row["path"])
            item.setToolTip(0, row["path"])
            item.setForeground(1, QBrush(QColor(tones[row["freshness"]])))
            self.results.addTopLevelItem(item)

    def shutdown(self):
        if self._stopping: return
        self._stopping = True
        self.invalidate()
        self.refresh_button.setEnabled(False)
        self._pool.waitForDone()
        self._jobs.clear()
