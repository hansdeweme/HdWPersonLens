"""No-write shortlist panel combining existing quality and identity reports."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QSize, QThreadPool, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QImage, QImageReader, QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                             QPushButton, QSlider, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .kb_reference_recommendations import build_recommendations, source_snapshot


class _ThumbnailSignals(QObject):
    loaded = pyqtSignal(int, str, object)


class _ThumbnailJob(QRunnable):
    def __init__(self, generation, path):
        super().__init__()
        self.setAutoDelete(False)
        self.generation, self.path = generation, path
        self.signals = _ThumbnailSignals()

    def run(self):
        try:
            reader = QImageReader(self.path)
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():
                size.scale(112, 112, Qt.AspectRatioMode.KeepAspectRatio)
                reader.setScaledSize(size)
            image = reader.read()
        except Exception:
            image = QImage()
        self.signals.loaded.emit(self.generation, self.path, image)


class PersonKBRecommendationPanel(QWidget):
    """Displays provisional suggestions; does not write files or selection decisions."""
    shortlist_ready = pyqtSignal(object)
    shortlist_invalidated = pyqtSignal()
    shortlist_started = pyqtSignal()
    shortlist_failed = pyqtSignal(str)
    sources_stale = pyqtSignal(str)
    def __init__(self, settings=None, parent=None, *, source_getter=None):
        super().__init__(parent)
        self.target_size = max(1, int((settings or {}).get("kb_gallery_target_size", 12)))
        self.diversity_weight = float((settings or {}).get("kb_gallery_diversity_weight", 0.35))
        self._paths = []
        self._person = ""
        self._source_getter = source_getter
        self._collection = None
        self._identity = None
        self._built = False
        self._thumb_generation = 0
        self._thumb_jobs = {}
        self._thumb_icons = {}
        self._thumb_stopping = False
        self._thumb_pool = QThreadPool(self)
        self._thumb_pool.setMaxThreadCount(2)
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(120)
        self._rebuild_timer.timeout.connect(self.build)
        QApplication.instance().aboutToQuit.connect(self.shutdown)
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
        weights = QHBoxLayout()
        weights.addWidget(QLabel("Quality"))
        self.weight_slider = QSlider(Qt.Orientation.Horizontal)
        self.weight_slider.setRange(0, 70)
        self.weight_slider.setValue(round(max(0.0, min(0.7, self.diversity_weight)) * 100))
        self.weight_slider.setEnabled(False)
        self.weight_slider.valueChanged.connect(self._weight_changed)
        weights.addWidget(self.weight_slider, 1)
        self.weight_label = QLabel("")
        weights.addWidget(self.weight_label)
        layout.addLayout(weights)
        self._update_weight_label()
        compare = QHBoxLayout()
        quality_col, diversity_col = QVBoxLayout(), QVBoxLayout()
        quality_col.addWidget(QLabel("Quality-only baseline"))
        diversity_col.addWidget(QLabel("Diversity-aware shortlist"))
        self.quality_cards = self._make_cards()
        self.diversity_cards = self._make_cards()
        quality_col.addWidget(self.quality_cards)
        diversity_col.addWidget(self.diversity_cards)
        compare.addLayout(quality_col, 1)
        compare.addLayout(diversity_col, 1)
        layout.addLayout(compare)
        self.results = QTreeWidget()
        self.results.setHeaderLabels(["Image", "Tech score", "Novelty", "Proposal", "Why"])
        self.results.setMinimumHeight(140)
        self.results.setMaximumHeight(240)
        layout.addWidget(self.results)

    @staticmethod
    def _make_cards():
        cards = QListWidget()
        cards.setViewMode(QListWidget.ViewMode.IconMode)
        cards.setResizeMode(QListWidget.ResizeMode.Adjust)
        cards.setMovement(QListWidget.Movement.Static)
        cards.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        cards.setIconSize(QSize(100, 100))
        cards.setGridSize(QSize(132, 145))
        cards.setMinimumHeight(145)
        cards.setMaximumHeight(190)
        return cards

    def _update_weight_label(self):
        diversity = self.weight_slider.value()
        self.weight_label.setText(f"{100 - diversity}% / {diversity}% diversity")

    def _weight_changed(self, value):
        if self._thumb_stopping: return
        self.diversity_weight = value / 100.0
        self._update_weight_label()
        if self._built: self._rebuild_timer.start()

    def _clear_views(self):
        self._rebuild_timer.stop()
        self._built = False
        self.shortlist_invalidated.emit()
        self.results.clear()
        self.quality_cards.clear()
        self.diversity_cards.clear()
        self.weight_slider.setEnabled(False)

    def _reset_thumbnails(self):
        self._thumb_generation += 1
        for key, job in list(self._thumb_jobs.items()):
            if self._thumb_pool.tryTake(job): self._thumb_jobs.pop(key, None)
        self._thumb_icons.clear()

    def set_person(self, name, paths):
        self._person = name
        self._paths = list(paths)
        self._collection = self._identity = None
        self._reset_thumbnails()
        self._clear_views()
        self._update_ready()

    def invalidate_collection(self):
        self._collection = None
        self._reset_thumbnails()
        self._clear_views()
        self._update_ready()

    def invalidate_identity(self):
        self._identity = None
        self._reset_thumbnails()
        self._clear_views()
        self._update_ready()

    def set_collection(self, result):
        self._collection = result
        self._reset_thumbnails()
        self._clear_views()
        self._update_ready()

    def set_identity(self, result):
        self._identity = result
        self._reset_thumbnails()
        self._clear_views()
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
        self.weight_slider.setEnabled(ready and self._built)
        self.summary.setText("Both analyses ready - suggestions remain provisional" if ready else
                             "Run collection and identity analyses first - no KB changes")
        if reports_ready and not ready:
            self.summary.setText("KB sources changed or reports are stale; refresh or rerun both analyses")

    def build(self):
        if self._thumb_stopping: return
        if self._collection is None or self._identity is None:
            self.sources_stale.emit("Run collection and identity analyses before building a shortlist")
            return
        if not self._reports_current():
            self._collection = self._identity = None
            self._reset_thumbnails()
            self._clear_views()
            self._update_ready()
            self.summary.setText("KB images changed since analysis; refresh or rerun both analyses")
            self.sources_stale.emit("KB source evidence changed; rerun Collection and Identity")
            return
        self.shortlist_started.emit()
        try:
            result = build_recommendations(self._collection, self._identity, target_size=self.target_size,
                                           diversity_weight=self.diversity_weight)
            baseline = build_recommendations(self._collection, self._identity, target_size=self.target_size,
                                             diversity_weight=0)
        except Exception as exc:
            self._clear_views()
            message = f"Shortlist unavailable: {exc}"
            self.summary.setText(message)
            self.shortlist_failed.emit(message)
            return
        diverse_paths = {r["path"] for r in result["rows"] if r["recommendation"] == "shortlist"}
        baseline_paths = {r["path"] for r in baseline["rows"] if r["recommendation"] == "shortlist"}
        changed = len(diverse_paths - baseline_paths)
        self.summary.setText(f"{result['shortlisted']} proposed · {changed} differ from quality-only · {result['reason']}")
        self._built = True
        self.weight_slider.setEnabled(True)
        self._fill_cards(self.quality_cards, baseline["rows"], set())
        self._fill_cards(self.diversity_cards, result["rows"], diverse_paths - baseline_paths)
        self.results.clear()
        for row in result["rows"]:
            novelty = f"{row['novelty']:.2f}" if row["novelty"] is not None else "—"
            item = QTreeWidgetItem([Path(row["path"]).name, f"{row['score']:.3f}", novelty,
                                    row["recommendation"].title(), row["reason"]])
            item.setToolTip(0, row["path"])
            self.results.addTopLevelItem(item)
        self.shortlist_ready.emit(result)

    def _fill_cards(self, cards, rows, added):
        cards.clear()
        for row in rows:
            if row["recommendation"] != "shortlist": continue
            path = row["path"]
            marker = " + variation" if path in added else ""
            item = QListWidgetItem(f"#{row['rank']} {Path(path).name}{marker}")
            item.setToolTip(f"{path}\n{row['reason']}")
            item.setData(Qt.ItemDataRole.UserRole, path)
            if path in self._thumb_icons: item.setIcon(self._thumb_icons[path])
            cards.addItem(item)
            self._request_thumbnail(path)

    def _request_thumbnail(self, path):
        key = (self._thumb_generation, path)
        if self._thumb_stopping or path in self._thumb_icons or key in self._thumb_jobs: return
        job = _ThumbnailJob(self._thumb_generation, path)
        job.signals.loaded.connect(self._thumbnail_loaded)
        self._thumb_jobs[key] = job
        self._thumb_pool.start(job)

    def _thumbnail_loaded(self, generation, path, image):
        self._thumb_jobs.pop((generation, path), None)
        if self._thumb_stopping or generation != self._thumb_generation or image.isNull(): return
        icon = QIcon(QPixmap.fromImage(image))
        self._thumb_icons[path] = icon
        for cards in (self.quality_cards, self.diversity_cards):
            for index in range(cards.count()):
                item = cards.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == path: item.setIcon(icon)

    def shutdown(self):
        if self._thumb_stopping: return
        self._thumb_stopping = True
        self.button.setEnabled(False)
        self.weight_slider.setEnabled(False)
        self._rebuild_timer.stop()
        self._thumb_generation += 1
        for key, job in list(self._thumb_jobs.items()):
            if self._thumb_pool.tryTake(job): self._thumb_jobs.pop(key, None)
        self._thumb_pool.waitForDone()
        self._thumb_jobs.clear()
