"""Read-only per-person identity-consistency panel with isolated face analysis."""
from __future__ import annotations

from pathlib import Path
from threading import Event

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .kb_identity_assessment import IdentityAssessmentRunner
from .kb_reference_recommendations import source_snapshot


class _IdentitySignals(QObject):
    finished = pyqtSignal(int, object, str)


class _IdentityJob(QRunnable):
    def __init__(self, generation, paths, threshold, runner):
        super().__init__()
        self.setAutoDelete(False)
        self.generation, self.paths, self.threshold, self.runner = generation, paths, threshold, runner
        self.cancelled = Event()
        self.source_snapshot = source_snapshot(paths)
        self.signals = _IdentitySignals()

    def run(self):
        if self.cancelled.is_set():
            result, error = None, "Assessment cancelled"
        else:
            try: result, error = self.runner.assess(self.paths, self.threshold, self.cancelled)
            except Exception as exc: result, error = None, f"Unexpected assessment failure: {exc}"
        self.signals.finished.emit(self.generation, result, error)


class PersonKBIdentityPanel(QWidget):
    assessment_ready = pyqtSignal(object)
    assessment_invalidated = pyqtSignal()
    assessment_started = pyqtSignal()
    assessment_failed = pyqtSignal(str)
    assessment_stale = pyqtSignal(str)
    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.threshold = float((settings or {}).get("kb_gallery_face_identity_max",
                                                    (settings or {}).get("face_threshold_supportable", 0.425)))
        self._generation = 0
        self._paths = []
        self._jobs = {}
        self._stopping = False
        self._runner = IdentityAssessmentRunner()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        self.button = QPushButton("Check Identity Consistency")
        self.button.clicked.connect(self.analyze)
        header.addWidget(self.button)
        self.summary = QLabel("Read-only peer comparison; not identity verification")
        self.summary.setWordWrap(True)
        header.addWidget(self.summary, 1)
        layout.addLayout(header)
        self.results = QTreeWidget()
        self.results.setHeaderLabels(["KB image", "Faces", "Peer distance", "Finding"])
        self.results.setMinimumHeight(130)
        self.results.setMaximumHeight(190)
        layout.addWidget(self.results)

    def set_person(self, _name, paths):
        if self._stopping: return
        self.assessment_invalidated.emit()
        self._invalidate()
        self._paths = list(paths)
        self.results.clear()
        self.summary.setText(f"{len(self._paths)} KB images · Internal consistency only; identity unverified")
        self.button.setEnabled(bool(self._paths))

    def analyze(self):
        if self._stopping or not self._paths: return
        self.assessment_invalidated.emit()
        self._invalidate()
        job = _IdentityJob(self._generation, list(self._paths), self.threshold, self._runner)
        job.signals.finished.connect(self._finished)
        self._jobs[self._generation] = job
        self.button.setEnabled(False)
        self.assessment_started.emit()
        self.summary.setText("Comparing face embeddings in isolated native process…")
        self._pool.start(job)

    def _finished(self, generation, result, error):
        job = self._jobs.pop(generation, None)
        if self._stopping or generation != self._generation: return
        self.button.setEnabled(bool(self._paths))
        self.results.clear()
        if result is None:
            self.summary.setText(f"Identity assessment unavailable: {error or 'unknown failure'}")
            self.assessment_failed.emit(error or "Identity assessment unavailable")
            return
        if job is None or job.source_snapshot != source_snapshot(self._paths):
            self.summary.setText("KB images changed during analysis; rerun identity assessment")
            self.assessment_invalidated.emit()
            self.assessment_stale.emit("KB sources changed during identity analysis; rerun identity")
            return
        result = dict(result, source_snapshot=job.source_snapshot)
        self.assessment_ready.emit(result)
        status = result["status"].replace("_", " ")
        truncated = " · first 100 images" if result["truncated"] else ""
        self.summary.setText(f"{result['usable']} usable faces · {result['consensus']} consensus · "
                             f"{status} (Euclidean distance ≤ {result['threshold']:.3f}){truncated} · identity unverified")
        for record in result["records"]:
            distance = record.get("best_peer_distance")
            distance_text = f"{distance:.3f}" if distance is not None else "—"
            finding = record.get("identity_finding", "inconclusive").replace("_", " ")
            if record.get("error"): finding = f"Unreadable: {record['error']}"
            item = QTreeWidgetItem([Path(record["path"]).name, str(record.get("face_count") or 0), distance_text, finding])
            item.setToolTip(0, record["path"])
            self.results.addTopLevelItem(item)

    def _invalidate(self):
        self._generation += 1
        for key, job in list(self._jobs.items()):
            job.cancelled.set()
            if self._pool.tryTake(job): self._jobs.pop(key, None)
        self._runner.cancel_active()

    def shutdown(self):
        if self._stopping: return
        self._stopping = True
        self._invalidate()
        self._runner.close()
        self._pool.waitForDone()
        self._jobs.clear()
