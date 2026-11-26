"""Read-only, asynchronous image gallery for a selected person's KB references."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QSize, QThreadPool, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QImage, QImageReader, QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QBoxLayout, QLabel, QListWidget, QListWidgetItem, QSizePolicy, QVBoxLayout, QWidget)

from .face_crop_preview import FaceCropPreviewRunner


class _ImageSignals(QObject):
    loaded = pyqtSignal(int, str, int, object)


class _ImageJob(QRunnable):
    def __init__(self, generation: int, path: str, max_side: int):
        super().__init__()
        self.setAutoDelete(False)
        self.generation, self.path, self.max_side = generation, path, max_side
        self.signals = _ImageSignals()

    def run(self):
        try:
            reader = QImageReader(self.path)
            reader.setAutoTransform(True)
            source_size = reader.size()
            if source_size.isValid():
                source_size.scale(self.max_side, self.max_side, Qt.AspectRatioMode.KeepAspectRatio)
                reader.setScaledSize(source_size)
            image = reader.read()
        except Exception:
            image = QImage()
        self.signals.loaded.emit(self.generation, self.path, self.max_side, image)


class _CropSignals(QObject):
    loaded = pyqtSignal(int, str, object, str, object)


class _CropJob(QRunnable):
    def __init__(self, generation, path, runner):
        super().__init__()
        self.setAutoDelete(False)
        self.generation, self.path, self.runner = generation, path, runner
        self.signals = _CropSignals()

    def run(self):
        try: data, error, metadata = self.runner.assess(self.path)
        except Exception as exc: data, error, metadata = None, f"Unexpected preview failure: {exc}", {}
        self.signals.loaded.emit(self.generation, self.path, data, error, metadata)


class PersonKBImageGallery(QWidget):
    """Show KB originals and isolated face crops; never modifies source files."""
    image_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.person_name = ""
        self.paths = []
        self._generation = 0
        self._jobs = {}
        self._crop_jobs = {}
        self._quality = {}
        self._stopping = False
        self._original_image = QPixmap()
        self._crop_image = QPixmap()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._crop_pool = QThreadPool(self)
        self._crop_pool.setMaxThreadCount(1)
        self._crop_runner = FaceCropPreviewRunner()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.heading = QLabel("KB reference images")
        self.heading.setObjectName("galleryHeading")
        layout.addWidget(self.heading)
        self.images = QListWidget()
        self.images.setViewMode(QListWidget.ViewMode.IconMode)
        self.images.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.images.setMovement(QListWidget.Movement.Static)
        self.images.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.images.setIconSize(QSize(84, 84))
        self.images.setGridSize(QSize(120, 125))
        self.images.setMinimumHeight(150)
        self.images.setMaximumHeight(215)
        self.images.currentItemChanged.connect(self._on_selection)
        layout.addWidget(self.images)
        previews = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._previews_layout = previews
        previews.setSpacing(10)
        original_panel = QVBoxLayout()
        crop_panel = QVBoxLayout()
        self.preview = QLabel("Select a KB image to preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(190)
        self.preview.setMaximumHeight(260)
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        original_heading = QLabel("Original KB image")
        original_heading.setObjectName("gallerySectionHeading")
        original_panel.addWidget(original_heading)
        original_panel.addWidget(self.preview)
        self.crop_preview = QLabel("Select a KB image to inspect its face crop")
        self.crop_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.crop_preview.setMinimumHeight(190)
        self.crop_preview.setMaximumHeight(260)
        self.crop_preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.crop_preview.setWordWrap(True)
        crop_heading = QLabel("Face crop (preview only — not saved)")
        crop_heading.setObjectName("gallerySectionHeading")
        crop_panel.addWidget(crop_heading)
        crop_panel.addWidget(self.crop_preview)
        previews.addLayout(original_panel, 1)
        previews.addLayout(crop_panel, 1)
        layout.addLayout(previews)
        self.quality_label = QLabel("Quality metrics appear after face analysis; they do not verify identity")
        self.quality_label.setWordWrap(True)
        layout.addWidget(self.quality_label)
        self.filename = QLabel("")
        self.filename.setWordWrap(True)
        layout.addWidget(self.filename)
        self._update_preview_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview_layout()
        QTimer.singleShot(0, self._scale_previews)

    def _update_preview_layout(self):
        direction = QBoxLayout.Direction.TopToBottom if self.width() < 620 else QBoxLayout.Direction.LeftToRight
        if self._previews_layout.direction() != direction: self._previews_layout.setDirection(direction)

    def _scale_previews(self):
        if self._stopping: return
        for label, source in ((self.preview, self._original_image), (self.crop_preview, self._crop_image)):
            if source.isNull(): continue
            size = label.contentsRect().size()
            if size.width() > 0 and size.height() > 0:
                label.setPixmap(source.scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))

    def set_person(self, name: str, paths: list[str], preferred: str | None = None):
        if self._stopping: return
        self._generation += 1
        self._cancel_queued()
        self._cancel_queued_crops()
        self._quality.clear()
        self._original_image = QPixmap()
        self._crop_image = QPixmap()
        self.person_name, self.paths = name, list(paths)
        self.images.clear()
        self.preview.clear()
        self.preview.setText("Select a KB image to preview")
        self.crop_preview.clear()
        self.crop_preview.setText("Select a KB image to inspect its face crop")
        self.quality_label.setText("Quality metrics appear after face analysis; they do not verify identity")
        self.filename.clear()
        self.heading.setText(f"KB reference images ({len(self.paths)})")
        for path in self.paths:
            item = QListWidgetItem(Path(path).name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self.images.addItem(item)
        if not self.paths:
            self.preview.setText("No KB images available")
            self.crop_preview.setText("No KB images available")
            return
        for path in self.paths:
            self._enqueue(path, 96)
        if preferred:
            for index, path in enumerate(self.paths):
                if Path(path).resolve() == Path(preferred).resolve():
                    self.images.setCurrentRow(index)
                    break

    def selected_path(self):
        item = self.images.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def select_path(self, path: str) -> bool:
        """Select a loaded KB image without changing the source list or preferences."""
        for index in range(self.images.count()):
            if self.images.item(index).data(Qt.ItemDataRole.UserRole) == path:
                self.images.setCurrentRow(index)
                self.images.scrollToItem(self.images.item(index))
                return True
        return False

    def _on_selection(self, current, _previous):
        if self._stopping: return
        path = current.data(Qt.ItemDataRole.UserRole) if current else None
        self._cancel_queued_previews()
        self._cancel_queued_crops()
        self._original_image = QPixmap()
        self._crop_image = QPixmap()
        self.preview.clear()
        self.preview.setText("Loading preview…" if path else "Select a KB image to preview")
        self.crop_preview.clear()
        self.crop_preview.setText("Analyzing face in isolated process…" if path else "Select a KB image to inspect its face crop")
        self._show_quality(path)
        self.filename.setText(Path(path).name if path else "")
        if path:
            self._enqueue(path, 640, priority=1)
            self._enqueue_crop(path)
            self.image_selected.emit(path)

    def _enqueue_crop(self, path):
        if self._stopping: return
        key = (self._generation, path)
        if key in self._crop_jobs: return
        job = _CropJob(self._generation, path, self._crop_runner)
        job.signals.loaded.connect(self._crop_loaded)
        self._crop_jobs[key] = job
        self._crop_pool.start(job)

    def _crop_loaded(self, generation, path, data, error, metadata):
        self._crop_jobs.pop((generation, path), None)
        if self._stopping or generation != self._generation: return
        # None records a completed analysis with no metrics, rather than a
        # request that is still pending. It also replaces any stale result.
        self._quality[path] = metadata or None
        for i in range(self.images.count()):
            item = self.images.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                if metadata:
                    count = metadata.get("face_count", 0)
                    score = metadata.get("face_quality")
                    badge = f"Face {score:.2f}" if score is not None and count == 1 else f"Faces: {count}"
                else:
                    badge = "Quality unavailable"
                item.setText(f"{Path(path).name}\n{badge}")
                item.setToolTip(f"{path}\n{badge} (heuristic; identity unverified)")
                break
        if self.selected_path() != path: return
        self._show_quality(path)
        image = QImage.fromData(data) if data else QImage()
        if image.isNull():
            self.crop_preview.setText(f"Face crop unavailable: {error or 'invalid image'}")
            return
        self._crop_image = QPixmap.fromImage(image)
        self._scale_previews()

    def _show_quality(self, path):
        if path in self._quality and self._quality[path] is None:
            self.quality_label.setText("Quality unavailable")
            return
        quality = self._quality.get(path)
        if not quality:
            self.quality_label.setText("Analyzing quality…" if path else "Quality metrics appear after face analysis")
            return
        score = quality.get("face_quality")
        score_text = f"{score:.2f} / 1.00" if score is not None else "not available"
        face_size = quality.get("face_width_fraction")
        size_text = f"{face_size:.0%}" if face_size is not None else "not available"
        self.quality_label.setText(f"Faces: {quality['face_count']}  ·  Face width: {size_text}  ·  "
                                   f"Sharpness: {quality['sharpness']:.1f}  ·  "
                                   f"Face quality: {score_text} (heuristic; identity unverified)")

    def _enqueue(self, path, size, priority=0):
        if self._stopping: return
        key = (self._generation, path, size)
        if key in self._jobs: return
        job = _ImageJob(self._generation, path, size)
        job.signals.loaded.connect(self._loaded)
        self._jobs[key] = job
        self._pool.start(job, priority)

    def _loaded(self, generation, path, size, image):
        self._jobs.pop((generation, path, size), None)
        if self._stopping or generation != self._generation: return
        if image.isNull():
            if size == 640 and self.selected_path() == path: self.preview.setText("Image could not be decoded")
            return
        pixmap = QPixmap.fromImage(image)
        if size == 96:
            for i in range(self.images.count()):
                item = self.images.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == path:
                    item.setIcon(QIcon(pixmap))
                    break
        elif self.selected_path() == path:
            self._original_image = pixmap
            self._scale_previews()

    def _cancel_queued(self):
        for key, job in list(self._jobs.items()):
            if self._pool.tryTake(job): self._jobs.pop(key, None)

    def _cancel_queued_previews(self):
        for key, job in list(self._jobs.items()):
            if key[2] == 640 and self._pool.tryTake(job): self._jobs.pop(key, None)

    def _cancel_queued_crops(self):
        for key, job in list(self._crop_jobs.items()):
            if self._crop_pool.tryTake(job): self._crop_jobs.pop(key, None)

    def shutdown(self):
        """Cancel queued decodes and wait for the at-most-two active image readers."""
        if self._stopping: return
        self._stopping = True
        self._generation += 1
        self._cancel_queued()
        self._cancel_queued_crops()
        self._crop_runner.close()
        self._pool.waitForDone()
        self._crop_pool.waitForDone()
        self._jobs.clear()
        self._crop_jobs.clear()
