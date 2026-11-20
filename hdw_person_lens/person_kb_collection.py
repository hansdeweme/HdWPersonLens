"""Explicit, read-only KB collection assessment panel for the Persons Workbench."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .kb_collection_assessment import CollectionAssessmentRunner
from .kb_reference_recommendations import source_snapshot


class _AssessmentSignals(QObject):
    finished = pyqtSignal(int, object, str)


class _AssessmentJob(QRunnable):
    def __init__(self, generation, paths, runner):
        super().__init__()
        self.setAutoDelete(False)
        self.generation, self.paths, self.runner = generation, paths, runner
        self.token = runner.request_token()
        self.source_snapshot = source_snapshot(paths)
        self.signals = _AssessmentSignals()

    def run(self):
        try: result, error = self.runner.assess(self.paths, token=self.token)
        except Exception as exc: result, error = None, f"Unexpected assessment failure: {exc}"
        self.signals.finished.emit(self.generation, result, error)


class PersonKBCollectionPanel(QWidget):
    """Display quality and duplicate evidence; never suggest or perform deletion."""
    assessment_ready = pyqtSignal(object)
    assessment_invalidated = pyqtSignal()
    assessment_started = pyqtSignal()
    assessment_failed = pyqtSignal(str)
    assessment_stale = pyqtSignal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self._generation = 0
        self._stopping = False
        self._paths = []
        self._jobs = {}
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._runner = CollectionAssessmentRunner()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        self.analyze_button = QPushButton("Analyze KB Collection")
        self.analyze_button.clicked.connect(self.analyze)
        header.addWidget(self.analyze_button)
        self.summary = QLabel("Read-only collection assessment; identity not verified")
        self.summary.setWordWrap(True)
        header.addWidget(self.summary, 1)
        layout.addLayout(header)
        self.results = QTreeWidget()
        self.results.setHeaderLabels(["KB image", "Dimensions", "Sharpness", "Finding"])
        self.results.setMinimumHeight(130)
        self.results.setMaximumHeight(190)
        layout.addWidget(self.results)

    def set_person(self, _name, paths):
        if self._stopping: return
        self.assessment_invalidated.emit()
        self._generation += 1
        self._cancel_queued()
        self._runner.cancel_active()
        self._paths = list(paths)
        self.results.clear()
        self.summary.setText(f"{len(self._paths)} KB images · Select Analyze to compare (read-only)")
        self.analyze_button.setEnabled(bool(self._paths))

    def analyze(self):
        if self._stopping or not self._paths: return
        self.assessment_invalidated.emit()
        self._generation += 1
        self._cancel_queued()
        self._runner.cancel_active()
        job = _AssessmentJob(self._generation, list(self._paths), self._runner)
        job.signals.finished.connect(self._finished)
        self._jobs[self._generation] = job
        self.analyze_button.setEnabled(False)
        self.assessment_started.emit()
        self.summary.setText("Analyzing collection in isolated process…")
        self._pool.start(job)

    def _finished(self, generation, result, error):
        job = self._jobs.pop(generation, None)
        if self._stopping or generation != self._generation: return
        self.analyze_button.setEnabled(bool(self._paths))
        self.results.clear()
        if not result:
            self.summary.setText(f"Collection assessment unavailable: {error or 'unknown failure'}")
            self.assessment_failed.emit(error or "Collection assessment unavailable")
            return
        if job is None or job.source_snapshot != source_snapshot(self._paths):
            self.summary.setText("KB images changed during analysis; rerun collection assessment")
            self.assessment_invalidated.emit()
            self.assessment_stale.emit("KB sources changed during collection analysis; rerun collection")
            return
        result = dict(result, source_snapshot=job.source_snapshot)
        self.assessment_ready.emit(result)
        errors = len(result["errors"])
        suffix = " · first 250 only" if result["truncated"] else ""
        self.summary.setText(f"{result['analyzed']}/{result['total']} analyzed · "
                             f"{result['duplicates']} possible duplicates · {errors} unreadable{suffix}")
        for record in result["records"]:
            finding = f"Possible duplicate of {Path(record['duplicate_of']).name}" if record["duplicate_of"] else "No duplicate found"
            item = QTreeWidgetItem([Path(record["path"]).name, f"{record['width']}×{record['height']}",
                                    f"{record['sharpness']:.1f}", finding])
            item.setToolTip(0, record["path"])
            self.results.addTopLevelItem(item)
        for failure in result["errors"]:
            item = QTreeWidgetItem([Path(failure["path"]).name, "—", "—", f"Unreadable: {failure['error']}"])
            item.setToolTip(0, failure["path"])
            self.results.addTopLevelItem(item)

    def _cancel_queued(self):
        for key, job in list(self._jobs.items()):
            if self._pool.tryTake(job): self._jobs.pop(key, None)

    def shutdown(self):
        if self._stopping: return
        self._stopping = True
        self._generation += 1
        self._cancel_queued()
        self._runner.close()
        self._pool.waitForDone()
        self._jobs.clear()
