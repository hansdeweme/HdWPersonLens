#unknown_review.py
# GUI for person recognition management 
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#

import os
from pathlib           import Path
from collections.abc   import Sequence
# PyQt6 imports
from PyQt6.QtWidgets   import QDialog, QLabel, QComboBox, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QComboBox,  QScrollArea, QWidget, QPushButton, QMessageBox
from PyQt6.QtCore      import Qt, pyqtSignal, QThread
from PyQt6.QtGui       import QPixmap, QCursor

class UnknownReviewDialog(QDialog):
    review_completed = pyqtSignal(object)
    def __init__(self, person_service, settings: dict, suggestions: dict, parent=None, on_done=None,):
        super().__init__(parent)
        self.person_service = person_service
        self.settings = settings
        self.suggestions = suggestions or {}
        self.on_done = on_done
        self.unknown_dir = Path(settings.get("output_folder", "")).expanduser() / "Unknown"
        self.valid_exts = self._normalized_extensions(settings.get("valid_extensions", [".jpg", ".jpeg", ".png", ".webp"], ))
        # source path -> selected person
        self.assignments: dict[str, str] = {}
        self.image_files: list[str] = []
        self.current_index = 0
        self.busy = False
        self.worker: UnknownReviewWorker | None = None
        self._worker_result = None
        self._worker_error = ""
        self.setWindowTitle("Review Unknown Images")
        self.resize(820, 650)
        self._build_ui()
        self._refresh_unknown_files()
        if self.image_files:
            self._load_current_image()
        else:
            self._set_empty_state()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.filename_label = QLabel()
        self.filename_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.filename_label)
        self.image_label = QLabel("Image Preview")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumHeight(300)
        layout.addWidget(self.image_label, 1)
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addWidget(QLabel("Suggested matches:"))
        self.suggestion_area = QScrollArea()
        self.suggestion_area.setWidgetResizable(True)
        self.suggestion_area.setFixedHeight(185)
        self.suggestion_widget = QWidget()
        self.suggestion_grid = QGridLayout(self.suggestion_widget)
        self.suggestion_area.setWidget(self.suggestion_widget)
        layout.addWidget(self.suggestion_area)
        self.person_dropdown = QComboBox()
        self.person_dropdown.addItems(self.person_service.list_recognition_names())
        layout.addWidget(self.person_dropdown)
        navigation = QHBoxLayout()
        self.previous_btn = QPushButton("Previous")
        self.confirm_btn = QPushButton("Confirm & Queue")
        self.skip_btn = QPushButton("Skip")
        self.finish_btn = QPushButton("Apply & Close")
        self.close_btn = QPushButton("Close")
        self.previous_btn.clicked.connect(self._previous_image)
        self.confirm_btn.clicked.connect(self._queue_current_assignment)
        self.skip_btn.clicked.connect(self._skip_current_image)
        self.finish_btn.clicked.connect(self._request_apply)
        self.close_btn.clicked.connect(self.reject)
        navigation.addWidget(self.previous_btn)
        navigation.addWidget(self.confirm_btn)
        navigation.addWidget(self.skip_btn)
        navigation.addStretch()
        navigation.addWidget(self.finish_btn)
        navigation.addWidget(self.close_btn)
        layout.addLayout(navigation)
        self.queue_label = QLabel()
        self.queue_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.queue_label.setToolTip("Queued images are copied and each affected person is re-encoded once.")
        layout.addWidget(self.queue_label)
        self._refresh_queue_label()

    def _current_path(self) -> str:
        if 0 <= self.current_index < len(self.image_files):
            return self.image_files[self.current_index]
        return ""

    def _group_assignments(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for path, name in self.assignments.items():
            grouped.setdefault(name, []).append(path)
        return grouped

    #---------------- Helpers ----------------------------
    @staticmethod
    def _normalized_extensions(values) -> tuple[str, ...]:
        extensions = []
        for value in values or []:
            extension = str(value).strip().lower()
            if extension:
                extensions.append(
                    extension if extension.startswith(".") else f".{extension}"
                )

        return tuple(extensions)

    @staticmethod
    def _path_key(path: str | Path) -> str:
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    def _refresh_unknown_files(self, exclude: Sequence[str] = ()) -> None:
        excluded = {self._path_key(path) for path in exclude}

        if not self.unknown_dir.is_dir():
            self.image_files = []
            return
        self.image_files = sorted((str(path) for path in self.unknown_dir.iterdir() if path.is_file() and path.suffix.lower() in self.valid_exts and self._path_key(path) not in excluded),
            key=lambda path: (Path(path).name.casefold(), Path(path).name),
        )
        if self.image_files:
            self.current_index = min(self.current_index, len(self.image_files) - 1)
        else:
            self.current_index = 0

    def _set_empty_state(self) -> None:
        self.filename_label.setText("No unknown images found.")
        self.image_label.clear()
        self.status_label.setText(str(self.unknown_dir))
        self.previous_btn.setEnabled(False)
        self.confirm_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self.finish_btn.setEnabled(bool(self.assignments))

    def _load_current_image(self) -> None:
        path = self._current_path()
        if not path:
            self._set_empty_state()
            return
        image_path = Path(path)
        self.filename_label.setText(
            f"Reviewing {self.current_index + 1} of "
            f"{len(self.image_files)}: {image_path.name}"
        )
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.image_label.clear()
            self.status_label.setText("The image could not be displayed.")
        else:
            scaled = pixmap.scaled(
                max(1, self.image_label.width() - 20),
                300,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.image_label.setPixmap(scaled)
            assigned_name = self.assignments.get(path)
            if assigned_name:
                self.status_label.setText(f"Queued for {assigned_name}.")
                index = self.person_dropdown.findText(assigned_name)

                if index >= 0:
                    self.person_dropdown.setCurrentIndex(index)
            else:
                self.status_label.clear()
        self._render_suggestions(path)
        self.previous_btn.setEnabled(self.current_index > 0)
        self._sync_controls()
    
    def _suggestions_for(self, image_path: str) -> dict:
        image_name = Path(image_path).name
        return (
            self.suggestions.get(image_name)
            or self.suggestions.get(image_path)
            or self.suggestions.get(self._path_key(image_path))
            or {}
        )

    def _clear_suggestions(self) -> None:
        while self.suggestion_grid.count():
            item = self.suggestion_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


    def _render_suggestions(self, image_path: str) -> None:
        self._clear_suggestions()
        suggestions = self._suggestions_for(image_path)
        candidates: dict[str, tuple[float, str, str]] = {}
        for source, key in (("Face", "face_matches"), ("Body", "body_matches")):
            for name, raw_score in suggestions.get(key, []):
                name = str(name).strip()
                if not name or name in candidates:
                    continue
                sample = self._get_sample_image(name)
                if sample:
                    candidates[name] = (float(raw_score), source, sample)

        for column, (name, (score, source, sample)) in enumerate(list(candidates.items())[:3]):
            container = QWidget()
            candidate_layout = QVBoxLayout(container)
            thumbnail = QLabel()
            thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumbnail.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            thumbnail.setPixmap(QPixmap(sample).scaled(130, 125, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,))
            thumbnail.mousePressEvent = (lambda _event, selected=name: self._select_person(selected))
            metric = "distance" if source == "Face" else "similarity"
            caption = QLabel(f"{name}\n{source} {metric}: {score:.3f}")
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setWordWrap(True)
            candidate_layout.addWidget(thumbnail)
            candidate_layout.addWidget(caption)
            self.suggestion_grid.addWidget(container, 0, column)

    def _get_sample_image(self, person_name: str) -> str | None:
        images = self.person_service.get_person_image_paths(person_name)
        return images[0] if images else None

    def _select_person(self, name: str) -> None:
        index = self.person_dropdown.findText(name)
        if index >= 0:
            self.person_dropdown.setCurrentIndex(index)

    def _queue_current_assignment(self) -> None:
        path = self._current_path()
        name = self.person_dropdown.currentText().strip()
        if not path:
            return
        if not name:
            QMessageBox.warning(self, "No Person Selected", "Select a person first.")
            return
        if not os.path.isfile(path):
            QMessageBox.warning(self, "Image Not Found", f"The unknown image no longer exists:\n{path}", )
            return
        self.assignments[path] = name
        self.status_label.setText(f"Queued {Path(path).name} for {name}.")
        self._refresh_queue_label()
        self._advance()

    def _skip_current_image(self) -> None:
        self._advance()

    def _previous_image(self) -> None:
        if self.current_index > 0:
            self.current_index -= 1
            self._load_current_image()

    def _advance(self) -> None:
        if self.current_index + 1 < len(self.image_files):
            self.current_index += 1
            self._load_current_image()
        else:
            self._request_apply()

    def _refresh_queue_label(self) -> None:
        person_count = len(set(self.assignments.values()))
        self.queue_label.setText(
            f"{len(self.assignments)} image(s) queued for "
            f"{person_count} person(s)"
        )

    def _request_apply(self) -> None:
        if self.busy:
            return
        if not self.assignments:
            QMessageBox.information(self, "Review Complete", "No image assignments were queued.", )
            super().accept()
            return
        grouped = self._group_assignments()
        reply = QMessageBox.question(self, "Apply Reviewed Images",  (
                f"Apply {len(self.assignments)} reviewed image assignment(s) "
                f"to {len(grouped)} person(s)?\n\n"
                "Each affected person will be re-encoded once. "
                "Successful images will be removed from the Unknown folder."
            ),  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes,)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._worker_result = None
        self._worker_error = ""
        self._set_busy(True)
        self.worker = UnknownReviewWorker(
            person_service=self.person_service,
            assignments=grouped,
            parent=self,
        )
        parent = self.parent()
        progress_handler = getattr(parent, "store_progress_value", None)
        log_handler = getattr(parent, "display_message", None)
        if callable(progress_handler):
            self.worker.progress.connect(progress_handler)
        if callable(log_handler):
            self.worker.log_message.connect(log_handler)
        self.worker.result_ready.connect(self._store_worker_result)
        self.worker.failed.connect(self._store_worker_error)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def _store_worker_result(self, result) -> None:
        self._worker_result = result

    def _store_worker_error(self, message: str) -> None:
        self._worker_error = message

    def _on_worker_finished(self) -> None:
        self.worker = None
        self._set_busy(False)
        if self._worker_error:
            QMessageBox.critical(self, "Unknown Review Failed", self._worker_error,)
            return
        result = self._worker_result
        if result is None:
            QMessageBox.critical(self, "Unknown Review Failed", "The review worker returned no result.",)
            return

        self.review_completed.emit(result)
        if callable(self.on_done):
            self.on_done()
        warning_lines = list(result.warnings)
        if result.failed_persons:
            warning_lines.extend(f"{name}: {message}" for name, message in result.failed_persons)
        summary = (f"Images assigned: {result.assigned_images}\n" f"Persons updated: {len(result.updated_persons)}")
        if warning_lines:
            QMessageBox.warning(self, "Review Completed with Issues", summary + "\n\n" + "\n".join(f"• {line}" for line in warning_lines), )
            # Successful assignments are excluded even if their source could
            # not be deleted. Failed source images remain available for retry.
            self.assignments.clear()
            self.current_index = 0
            self._refresh_unknown_files(exclude=result.successful_sources)
            self._refresh_queue_label()
            if self.image_files:
                self._load_current_image()
            else:
                self._set_empty_state()
            return
        QMessageBox.information(self, "Review Completed", summary)
        super().accept()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        for widget in (
            self.person_dropdown,
            self.previous_btn,
            self.confirm_btn,
            self.skip_btn,
            self.finish_btn,
            self.close_btn,
        ):
            widget.setEnabled(not busy)
        if busy:
            self.status_label.setText("Applying assignments and re-encoding…")
        else:
            self._sync_controls()

    def _sync_controls(self) -> None:
        has_images = bool(self.image_files)
        has_person = bool(self.person_dropdown.currentText().strip())
        self.previous_btn.setEnabled(not self.busy and has_images and self.current_index > 0)
        self.confirm_btn.setEnabled(not self.busy and has_images and has_person)
        self.skip_btn.setEnabled(not self.busy and has_images)
        self.finish_btn.setEnabled(not self.busy and bool(self.assignments))
        self.close_btn.setEnabled(not self.busy)

    def reject(self) -> None:
        if self.busy:
            QMessageBox.information(self, "Operation Running", "Wait until the queued assignments have been applied.",)
            return
        if not self.assignments:
            super().reject()
            return
        reply = QMessageBox.question(self, "Queued Assignments", (
                f"{len(self.assignments)} image assignment(s) have not yet been applied.\n\n" "Apply them before closing?"),
            QMessageBox.StandardButton.Yes  | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes,)
        if reply == QMessageBox.StandardButton.Yes:
            self._request_apply()
        elif reply == QMessageBox.StandardButton.No:
            super().reject()

#------------------------------------------
# Worker
#------------------------------------------
class UnknownReviewWorker(QThread):
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, person_service, assignments: dict[str, list[str]], parent=None):
        super().__init__(parent)
        self.person_service = person_service
        self.assignments = assignments

    def run(self) -> None:
        try:
            result = self.person_service.apply_unknown_review_assignments(
                assignments=self.assignments,
                remove_sources=True,
                on_log=self.log_message.emit,
                on_progress=self.progress.emit,
            )
            self.result_ready.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))