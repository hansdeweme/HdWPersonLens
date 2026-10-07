# unknown_review.py
# GUI for reviewing uncertain person-recognition results
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project.

from __future__     import annotations
import os
from pathlib         import Path
from collections.abc import Mapping, Sequence
from typing          import Any
# PyQt6 imports
from PyQt6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QCheckBox
from PyQt6.QtCore    import Qt, pyqtSignal, QThread
from PyQt6.QtGui     import QPixmap
#local imports
from review_session_reporting import RecognitionReviewResult, apply_recognition_review_decisions, new_session_id, utc_now_iso
from recognition_contenders   import ContenderSlateWidget
from config          import DEFAULT_RECOGNITION_EXTENSIONS  

def _path_key(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))

#---------------------------------------------
# Review Non assigned Images from Batch Recognition Dialog
# writes the classification before optionally registering a KB candidate
# Candidate-registration failure does not undo a valid human classification
#---------------------------------------------
class RecognitionReviewDialog(QDialog):
    """Review images routed to ``output/Review`` by batch recognition."""
    review_completed = pyqtSignal(object)
    def __init__(self, person_service, settings: dict, suggestions: dict, parent=None, on_done=None,):
        super().__init__(parent)
        self.person_service = person_service
        self.settings = settings
        self.suggestions = suggestions or {}
        self.on_done = on_done
        self.output_dir = Path(settings.get("output_folder", "")).expanduser()
        self.review_dir = self.output_dir / "Review"
        self.valid_exts = self._normalized_extensions(DEFAULT_RECOGNITION_EXTENSIONS)
        # source path -> {action: assign|unknown, person_name: str}
        self.decisions: dict[str, dict[str, str]] = {}
        self.image_files: list[str] = []
        self.current_index = 0
        self.busy = False
        self.worker: RecognitionReviewWorker | None = None
        self._worker_result: RecognitionReviewResult | None = None
        self._worker_error = ""
        self.deferred_paths: set[str] = set()
        self._begin_new_session()
        self.setWindowTitle("Recognition Review")
        self.resize(900, 720)
        self._build_ui()
        self._refresh_review_files()
        if self.image_files:
            self._load_current_image()
        else:
            self._set_empty_state()

    def _begin_new_session(self) -> None:
        self.session_id = new_session_id()
        self.session_started_at_utc = utc_now_iso()

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
        layout.addWidget(QLabel("Recognition contenders:"))
        self.contender_slate = ContenderSlateWidget(sample_getter=self._get_sample_image, max_cards=3, parent=self)
        self.contender_slate.person_selected.connect(self._select_person)
        layout.addWidget(self.contender_slate)
        self.person_dropdown = QComboBox()
        self.person_dropdown.addItem("— Select another person —", "")
        for name in self.person_service.list_recognition_names():
            clean_name = str(name).strip()
            if clean_name:
                self.person_dropdown.addItem(clean_name, clean_name)
        self.person_dropdown.currentIndexChanged.connect(self._sync_candidate_selection)
        layout.addWidget(self.person_dropdown)
        self.kb_candidate_checkbox = QCheckBox("Mark assigned image for later KB consideration")
        self.kb_candidate_checkbox.setChecked(False)
        self.kb_candidate_checkbox.setToolTip("Creates a pending curation candidate only. It does not copy the image into the KB or re-encode the person.")
        layout.addWidget(self.kb_candidate_checkbox)        
        navigation = QHBoxLayout()
        self.previous_btn = QPushButton("Previous")
        self.confirm_btn = QPushButton("Confirm Assignment")
        self.unknown_btn = QPushButton("None of These / Keep Unknown")
        self.defer_btn = QPushButton("Defer")
        self.finish_btn = QPushButton("Apply Decisions & Close")
        self.close_btn = QPushButton("Close")
        self.previous_btn.clicked.connect(self._previous_image)
        self.confirm_btn.clicked.connect(self._queue_current_assignment)
        self.unknown_btn.clicked.connect(self._queue_keep_unknown)
        self.defer_btn.clicked.connect(self._defer_current_image)
        self.finish_btn.clicked.connect(self._request_apply)
        self.close_btn.clicked.connect(self.reject)
        navigation.addWidget(self.previous_btn)
        navigation.addWidget(self.confirm_btn)
        navigation.addWidget(self.unknown_btn)
        navigation.addWidget(self.defer_btn)
        navigation.addStretch()
        navigation.addWidget(self.finish_btn)
        navigation.addWidget(self.close_btn)
        layout.addLayout(navigation)
        self.queue_label = QLabel()
        self.queue_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.queue_label.setToolTip(
            "Review decisions only move processed images. They do not add "
            "reference images or re-encode the knowledge base."
        )
        layout.addWidget(self.queue_label)
        self._refresh_queue_label()

    # ------------------------------------------------------------------
    # Paths and records
    # ------------------------------------------------------------------
    def _current_path(self) -> str:
        if 0 <= self.current_index < len(self.image_files):
            return self.image_files[self.current_index]
        return ""

    @staticmethod
    def _normalized_extensions(values) -> tuple[str, ...]:
        extensions: list[str] = []
        for value in values or []:
            extension = str(value).strip().lower()
            if extension:
                extensions.append(
                    extension if extension.startswith(".") else f".{extension}"
                )
        return tuple(extensions)

    def _refresh_review_files(self, exclude: Sequence[str] = ()) -> None:
        excluded = {_path_key(path) for path in exclude}
        if not self.review_dir.is_dir():
            self.image_files = []
            self.current_index = 0
            return

        self.image_files = sorted((str(path) for path in self.review_dir.iterdir() if (path.is_file() and path.suffix.lower() in self.valid_exts 
                                    and _path_key(path) not in excluded)), key=lambda path: (Path(path).name.casefold(), Path(path).name),)
        if self.image_files:
            self.current_index = min(self.current_index, len(self.image_files) - 1,)
        else:
            self.current_index = 0

    def _record_for(self, image_path: str) -> dict[str, Any]:
        image_name = Path(image_path).name
        record = (
            self.suggestions.get(image_path)
            or self.suggestions.get(_path_key(image_path))
            or self.suggestions.get(image_name)
            or {}
        )
        return dict(record) if isinstance(record, Mapping) else {}

    def _contenders_for(self, image_path: str) -> list[dict[str, Any]]:
        record = self._record_for(image_path)
        contenders = record.get("contenders", [])
        if isinstance(contenders, Sequence) and not isinstance(contenders, (str, bytes), ):
            clean = [dict(item) for item in contenders if isinstance(item, Mapping) and str(item.get("name", "")).strip()]
            if clean:
                return clean[:3]
        # Backward-compatible fallback for an older batch_report.csv.
        merged: dict[str, dict[str, Any]] = {}
        for rank, item in enumerate(record.get("face_matches", []) or [], start=1):
            try:
                name, score = item
                name = str(name).strip()
                if name:
                    merged[name.casefold()] = {
                        "name": name,
                        "face_distance": float(score),
                        "face_rank": rank,
                        "body_similarity": None,
                        "body_rank": None,
                        "face_plausible": None,
                        "body_plausible": None,
                        "evidence": "face",
                    }
            except (TypeError, ValueError):
                continue

        for rank, item in enumerate(record.get("body_matches", []) or [], start=1):
            try:
                name, score = item
                name = str(name).strip()
                if not name:
                    continue
                contender = merged.setdefault(
                    name.casefold(),
                    {
                        "name": name,
                        "face_distance": None,
                        "face_rank": None,
                        "body_similarity": None,
                        "body_rank": None,
                        "face_plausible": None,
                        "body_plausible": None,
                        "evidence": "body",
                    },
                )
                contender["body_similarity"] = float(score)
                contender["body_rank"] = rank
                if contender.get("face_distance") is not None:
                    contender["evidence"] = "face_and_body"
            except (TypeError, ValueError):
                continue
        return list(merged.values())[:3]

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _set_empty_state(self) -> None:
        self.filename_label.setText("No images are waiting in Review.")
        self.image_label.clear()
        self.status_label.setText(str(self.review_dir))
        self.contender_slate.clear()
        self._sync_controls()

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
            self.status_label.setText(self._status_text_for(path))
        self._render_suggestions(path)
        self._sync_controls()

    def _status_text_for(self, path: str) -> str:
        decision = self.decisions.get(path)
        if decision:
            if decision.get("action") == "assign":
                return f"Queued assignment: {decision.get('person_name', '')}."
            return "Queued decision: Keep Unknown."
        record = self._record_for(path)
        reason = str(record.get("decision_reason", "") or "").strip()
        if reason:
            return f"Machine decision: review required ({reason})."
        return "Review required. Select a contender, another person, or Keep Unknown."

    def _render_suggestions(self, image_path: str) -> None:
        # Never carry a selection or promotion flag from the previous image into this one.
        self.person_dropdown.setCurrentIndex(0)
        self.kb_candidate_checkbox.setChecked(False)
        contenders = self._contenders_for(image_path)
        self.contender_slate.set_contenders(contenders)
        decision = self.decisions.get(image_path)
        if decision and decision.get("action") == "assign":
            self._select_person(decision.get("person_name", ""))
            self.kb_candidate_checkbox.setChecked(bool(decision.get("mark_for_kb_consideration")))
        elif decision and decision.get("action") == "unknown":
            self.person_dropdown.setCurrentIndex(0)
            self._sync_candidate_selection()
        elif contenders:
            # Preselection is only a UI convenience. It never queues or applies
            # a decision until Confirm Assignment is pressed.
            self._select_person(str(contenders[0].get("name", "")))
        else:
            self.person_dropdown.setCurrentIndex(0)
            self._sync_candidate_selection()

    def _get_sample_image(self, person_name: str) -> str | None:
        images = self.person_service.get_person_image_paths(person_name)
        return images[0] if images else None

    def _select_person(self, name: str) -> None:
        clean_name = str(name or "").strip()
        index = self.person_dropdown.findData(clean_name)
        if index < 0:
            index = self.person_dropdown.findText(clean_name)
        if index >= 0:
            self.person_dropdown.setCurrentIndex(index)
        self._sync_candidate_selection()

    def _selected_person(self) -> str:
        value = self.person_dropdown.currentData()
        if value is None:
            value = self.person_dropdown.currentText()
        return str(value or "").strip()

    def _sync_candidate_selection(self, *_args) -> None:
        selected_key = self._selected_person().casefold()
        self.contender_slate.select_name(self._selected_person(), emit=False)
        if not selected_key:
            self.kb_candidate_checkbox.setChecked(False)
        self._sync_controls()

    # ------------------------------------------------------------------
    # Review decisions
    # ------------------------------------------------------------------
    def _queue_current_assignment(self) -> None:
        path = self._current_path()
        name = self._selected_person()
        if not path:
            return
        if not name:
           QMessageBox.warning(self,"No Person Selected","Select a contender or another person first.",)
           return
        if not os.path.isfile(path):
            QMessageBox.warning(self, "Image Not Found", f"The review image no longer exists:\n{path}",)
            return
        mark_for_kb = self.kb_candidate_checkbox.isChecked()
        self.decisions[path] = {"action": "assign","person_name": name, "mark_for_kb_consideration": mark_for_kb,}
        self.deferred_paths.discard(path)
        suffix = " Marked for later KB consideration." if mark_for_kb else ""
        self.status_label.setText(f"Queued assignment: {name}.{suffix}")        
        self._refresh_queue_label()
        self._advance()

    def _queue_keep_unknown(self) -> None:
        path = self._current_path()
        if not path:
            return
        if not os.path.isfile(path):
            QMessageBox.warning(self, "Image Not Found", f"The review image no longer exists:\n{path}",)
            return
        self.decisions[path] = {"action": "unknown", "person_name": "",}
        self.deferred_paths.discard(path)
        self.person_dropdown.setCurrentIndex(0)
        self.kb_candidate_checkbox.setChecked(False)
        self.status_label.setText("Queued decision: Keep Unknown.")
        self._refresh_queue_label()
        self._advance()

    def _defer_current_image(self) -> None:
        path = self._current_path()
        if path:
            self.decisions.pop(path, None)
            self.deferred_paths.add(path)
            self.kb_candidate_checkbox.setChecked(False)
            self.status_label.setText("Deferred for a later review session.")
        self._refresh_queue_label()
        self._advance()

    def _previous_image(self) -> None:
        if self.current_index > 0:
            self.current_index -= 1
            self._load_current_image()

    def _advance(self) -> None:
        if self.current_index + 1 < len(self.image_files):
            self.current_index += 1
            self._load_current_image()
            return

        self.status_label.setText(
            "Reached the final review image. Apply queued decisions or use "
            "Previous to revise them."
        )
        self._sync_controls()

    def _refresh_queue_label(self) -> None:
        assigned = sum(1 for decision in self.decisions.values() if decision.get("action") == "assign")
        unknown = sum( 1 for decision in self.decisions.values() if decision.get("action") == "unknown")
        current_keys = {_path_key(path) for path in self.image_files}
        deferred = sum(1 for path in self.deferred_paths if _path_key(path) in current_keys)
        reviewed_keys = ({_path_key(path) for path in self.decisions} | {_path_key(path) for path in self.deferred_paths})
        candidates = sum(1 for decision in self.decisions.values() if decision.get("action") == "assign" and decision.get("mark_for_kb_consideration"))        
        unreviewed = sum(1 for path in self.image_files if _path_key(path) not in reviewed_keys)
        self.queue_label.setText(f"{assigned} assignment(s), {unknown} Keep Unknown, {candidates} KB candidate(s), " f"{deferred} deferred, {unreviewed} unreviewed")

    def _worker_decisions(self) -> list[dict[str, Any]]:
        return [
            {
                "source_path": source_path,
                "action": decision.get("action", ""),
                "person_name": decision.get("person_name", ""),
                "mark_for_kb_consideration": bool(decision.get("mark_for_kb_consideration")),
                "machine_record": self._record_for(source_path),
            }
            for source_path, decision in self.decisions.items()
        ]

    def _worker_deferred_items(self) -> list[dict[str, Any]]:
        current_paths = {
            _path_key(path): path
            for path in self.image_files
        }
        return [ {"source_path": current_paths[key],  "machine_record": self._record_for(current_paths[key]), }
            for key in sorted((_path_key(path) for path in self.deferred_paths), key=str.casefold,) if key in current_paths]

    def _worker_unreviewed_items(self) -> list[dict[str, Any]]:
        reviewed_keys = ( {_path_key(path) for path in self.decisions} | {_path_key(path) for path in self.deferred_paths})
        return [ {"source_path": path, "machine_record": self._record_for(path),}
            for path in self.image_files if _path_key(path) not in reviewed_keys]

    def _request_apply(self) -> None:
        if self.busy:
            return
        if not self.decisions and not self.deferred_paths:
            QMessageBox.information(self, "No Review Activity", ("No classification decisions or explicit deferrals have been queued."),)
            return

        assigned = sum(1 for decision in self.decisions.values() if decision.get("action") == "assign")
        unknown = sum(1 for decision in self.decisions.values() if decision.get("action") == "unknown")
        candidates = sum(1 for decision in self.decisions.values() if decision.get("action") == "assign" and decision.get("mark_for_kb_consideration"))        
        deferred = len(self._worker_deferred_items())
        unreviewed = len(self._worker_unreviewed_items())
        reply = QMessageBox.question(self, "Complete Recognition Review Session", (
                f"Complete session {self.session_id}?\n\n"
                f"Assign to named processed folders: {assigned}\n"
                f"Keep Unknown: {unknown}\n"
                f"Mark for later KB consideration: {candidates}\n"
                f"Explicitly deferred: {deferred}\n"
                f"Not reviewed in this session: {unreviewed}\n\n"
                "A JSON and CSV session report will be written. "
                "No images will be added to the knowledge base and "
                "no person will be re-encoded."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes,)
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._worker_result = None
        self._worker_error = ""
        self._set_busy(True)
        self.worker = RecognitionReviewWorker(decisions=self._worker_decisions(), deferred_items=self._worker_deferred_items(), unreviewed_items=self._worker_unreviewed_items(),
                                        output_folder=self.output_dir, session_id=self.session_id, session_started_at_utc=self.session_started_at_utc, parent=self,)
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
            QMessageBox.critical(self, "Recognition Review Failed", self._worker_error, )
            return
        result = self._worker_result
        if result is None:
            QMessageBox.critical(self, "Recognition Review Failed", "The review worker returned no result.",)
            return
        successful_keys = { _path_key(path) for path in result.successful_sources}
        self.decisions = {path: decision for path, decision in self.decisions.items() if _path_key(path) not in successful_keys}
        self.deferred_paths.clear()
        self.review_completed.emit(result)
        if callable(self.on_done):
            self.on_done()
        self.current_index = 0
        self._refresh_review_files(exclude=result.successful_sources)
        self._begin_new_session()
        self._refresh_queue_label()
        summary_lines = [
            f"Session: {result.session_id}",
            f"Assigned to named folders: {result.assigned_images}",
            f"Kept Unknown: {result.kept_unknown}",
            f"Deferred: {result.deferred_images}",
            f"Unreviewed: {result.unreviewed_images}",
            f"New KB candidates: {result.kb_candidates_created}",
            f"Existing KB candidates reused: {result.kb_candidates_existing}",            
            f"Audit manifest: {result.manifest_path}",
        ]
        if result.session_report_path:
            summary_lines.append(f"Session JSON: {result.session_report_path}" )
        if result.session_csv_path:
            summary_lines.append(f"Session CSV: {result.session_csv_path}")    
        if result.candidate_store_path:
            summary_lines.append(f"KB candidate store: {result.candidate_store_path}")    
        summary = "\n".join(summary_lines)   
        if result.failed_items or result.warnings:
            issue_lines = [f"{Path(path).name or path}: {message}" for path, message in result.failed_items]
            issue_lines.extend(result.warnings)
            QMessageBox.warning(self, "Recognition Review Completed with Issues", summary  + "\n\n" + "\n".join(f"• {line}" for line in issue_lines), )
            if self.image_files:
                self._load_current_image()
            else:
                self._set_empty_state()
            return

        QMessageBox.information(self, "Recognition Review Completed", summary,)
        if self.image_files:
            self._load_current_image()
        else:
            super().accept()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        for widget in (
            self.person_dropdown,
            self.previous_btn,
            self.kb_candidate_checkbox,
            self.confirm_btn,
            self.unknown_btn,
            self.defer_btn,
            self.finish_btn,
            self.close_btn,
        ):
            widget.setEnabled(not busy)

        if busy:
            self.status_label.setText("Applying classification decisions without changing the knowledge base…")
        else:
            self._sync_controls()

    def _sync_controls(self) -> None:
        has_images = bool(self.image_files)
        has_person = bool(self._selected_person())
        self.previous_btn.setEnabled(not self.busy and has_images and self.current_index > 0)
        self.confirm_btn.setEnabled(not self.busy and has_images and has_person)
        self.confirm_btn.setEnabled(not self.busy and has_images and has_person)
        self.kb_candidate_checkbox.setEnabled(not self.busy and has_images and has_person)        
        self.unknown_btn.setEnabled(not self.busy and has_images)
        self.defer_btn.setEnabled(not self.busy and has_images)
        self.finish_btn.setEnabled(not self.busy and bool(self.decisions or self.deferred_paths))
        self.close_btn.setEnabled(not self.busy)

    def reject(self) -> None:
        if self.busy:
            QMessageBox.information(self, "Operation Running", "Wait until the queued decisions have been applied.",)
            return
        if not self.decisions and not self.deferred_paths:
            super().reject()
            return

        reply = QMessageBox.question(self, "Unreported Review Activity", (
                f"{len(self.decisions)} classification decision(s) and "
                f"{len(self.deferred_paths)} explicit deferral(s) have "
                "not yet been written as a completed session.\n\n"
                "Complete the session before closing?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes,)
        if reply == QMessageBox.StandardButton.Yes:
            self._request_apply()
        elif reply == QMessageBox.StandardButton.No:
            super().reject()

class RecognitionReviewWorker(QThread):
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, decisions: Sequence[Mapping[str, Any]], output_folder: str | Path, *, session_id: str = "", session_started_at_utc: str = "",
        deferred_items: Sequence[Mapping[str, Any]] = (), unreviewed_items: Sequence[Mapping[str, Any]] = (), parent=None,):
        super().__init__(parent)
        self.decisions = [dict(item) for item in decisions]
        self.deferred_items = [dict(item) for item in deferred_items]
        self.unreviewed_items = [dict(item) for item in unreviewed_items]
        self.output_folder = Path(output_folder)
        self.session_id = str(session_id or "")
        self.session_started_at_utc = str(session_started_at_utc or "")

    def run(self) -> None:
        try:
            result = apply_recognition_review_decisions(self.decisions, output_folder=self.output_folder, session_id=self.session_id, session_started_at_utc=self.session_started_at_utc,
                deferred_items=self.deferred_items, unreviewed_items=self.unreviewed_items, on_log=self.log_message.emit, on_progress=self.progress.emit, )
            self.result_ready.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))

# Temporary import compatibility for any external extension that still imports
# the old class name. New application code should use RecognitionReviewDialog.
UnknownReviewDialog = RecognitionReviewDialog
