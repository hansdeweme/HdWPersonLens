"""Reviewed reference-input comparison and explicitly confirmed selected encoding."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .kb_encoding_impact import build_encoding_impact
from .kb_controlled_encoding import confirmation_details
from .kb_reference_encoding import verify_reference_sources
from .kb_reference_recommendations import source_snapshot
from .person_kb_encoding_worker import SelectedEncodingWorker


class PersonKBEncodingImpactPanel(QWidget):
    image_requested = pyqtSignal(str)
    activity_message = pyqtSignal(str)
    encoding_completed = pyqtSignal(str, object)

    def __init__(self, person_service, parent=None):
        super().__init__(parent)
        self.service = person_service
        self.person, self.paths = "", []
        self.recommendations = None
        self._result = None
        self._snapshot = None
        self._running = False
        self._stopping = False
        self._thread = None
        self._worker = None
        self._operation_name = ""
        self._result_received = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel("Build a shortlist to review inputs before controlled reference encoding")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.notice = QLabel("Existing legacy embeddings have no per-source provenance. Preview counts are not predicted outcomes.")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.results = QTreeWidget()
        self.results.setHeaderLabels(["KB image", "Proposal", "Why"])
        self.results.setMinimumHeight(140)
        self.results.itemDoubleClicked.connect(lambda item, _: self.image_requested.emit(item.data(0, Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.results)
        self.apply_button = QPushButton("Encode Selected References…")
        self.apply_button.setProperty("themeRole", "primary")
        self.apply_button.setToolTip("Replace this person's recognition embeddings using only the reviewed shortlist.")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_selected)
        layout.addWidget(self.apply_button)
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def set_person(self, name, paths):
        self.person, self.paths = name, list(paths)
        self.invalidate()

    def invalidate(self):
        self._result = None
        self._snapshot = None
        self.results.clear()
        self.summary.setText("Build a fresh shortlist before applying controlled reference encoding")
        self.apply_button.setEnabled(False)

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
        try:
            selected = [row["path"] for row in preview["rows"] if row["action"] == "Proposed input"]
            self._snapshot = self.service.capture_selected_reference_sources(name=self.person, paths=selected)
            confirmation_details(self.person, self._result, self._snapshot)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self.invalidate()
            self.summary.setText(f"Encoding impact unavailable: {exc}")
            return
        self.summary.setText(f"Current KB inputs: {preview['current_images']} · Proposed: {preview['proposed_images']} · "
                             f"Omitted: {preview['omitted_images']} · Existing embeddings: "
                             f"{preview['existing_face_encodings']} face / {preview['existing_body_encodings']} body")
        for row in preview["rows"]:
            item = QTreeWidgetItem([Path(row["path"]).name, row["action"], row["reason"]])
            item.setData(0, Qt.ItemDataRole.UserRole, row["path"])
            item.setToolTip(0, row["path"])
            self.results.addTopLevelItem(item)
        self.apply_button.setEnabled(not self._running and not self._stopping)

    def apply_selected(self):
        if self._running or self._stopping or self._result is None or self._snapshot is None: return
        person, snapshot, preview = self.person, self._snapshot, self._result
        try:
            details = confirmation_details(self.person, self._result, self._snapshot)
            verify_reference_sources(self._snapshot, tuple(self.service._valid_extensions()))
            paths = self.service.get_person_image_paths(self.person)
            if (source_snapshot(paths) != source_snapshot(self.paths) or self.recommendations._person != self.person
                    or not self.recommendations._reports_current() or not self.service.get_person_state(self.person).database_record_exists):
                raise ValueError("The shortlist evidence or selected person is no longer current.")
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            self.invalidate()
            QMessageBox.warning(self, "References Changed", f"Review the KB assessment again before encoding.\n\n{exc}")
            return
        selected = "\n".join(f"  • {Path(path).name}" for path in details["selected"])
        omitted = "\n".join(f"  • {Path(path).name}" for path in details["omitted"]) or "  (none)"
        message = (f"Replace the recognition embeddings for {self.person}?\n\n"
            f"Selected reference images ({len(details['selected'])}):\n{selected}\n\n"
            f"Excluded from encoding ({len(details['omitted'])}):\n{omitted}\n\n"
            f"Existing embeddings to replace: {details['old_faces']} face / {details['old_bodies']} body\n\n"
            "Existing embeddings for this person will be replaced. Original KB images remain unchanged. "
            "The saved encoding bank retains its validated backup.")
        decision = QMessageBox.question(self, "Confirm Controlled Encoding", message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if decision != QMessageBox.StandardButton.Yes: return
        try:
            if (self._running or self._stopping or self.person != person or self._snapshot != snapshot
                    or self._result is not preview or confirmation_details(person, preview, snapshot) != details):
                raise ValueError("The proposal changed during confirmation. Confirm the updated selection before encoding.")
            verify_reference_sources(snapshot, tuple(self.service._valid_extensions()))
            if (self.recommendations._person != person or not self.recommendations._reports_current()
                    or not self.service.get_person_state(person).database_record_exists):
                raise ValueError("The person or assessment changed during confirmation.")
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            if self.person == person and self._snapshot == snapshot and self._result is preview:
                self.invalidate()
            QMessageBox.warning(self, "References Changed", str(exc))
            return
        self._running = True
        self._result_received = False
        self._operation_name = person
        self.apply_button.setEnabled(False)
        self.summary.setText(f"Encoding selected references for {self.person}…")
        self.activity_message.emit(f"[Controlled Encoding] Started {self.person}: {len(details['selected'])} selected image(s).")
        self._thread = QThread(self)
        self._worker = SelectedEncodingWorker(self.service, person, snapshot)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.activity.connect(self.activity_message)
        self._worker.progress.connect(self._on_progress)
        self._worker.completed.connect(self._on_completed)
        self._worker.completed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _on_progress(self, value):
        if self._running and not self._stopping and self._operation_name == self.person:
            self.summary.setText(f"Controlled encoding {self._operation_name}: {value}%")

    def _on_completed(self, result, error):
        self._result_received = True
        name = self._operation_name
        if not error and any(type(getattr(result, field, None)) is not int or getattr(result, field) < 0
                             for field in ("face_encodings", "body_encodings")):
            error = "Selected reference encoding returned an invalid completion result."
        if error:
            self.activity_message.emit(f"[Controlled Encoding][Error] {name}: {error}")
        else:
            self.activity_message.emit(f"[Controlled Encoding] Finished {name}: "
                f"{result.face_encodings} face / {result.body_encodings} body embeddings.")
            self.encoding_completed.emit(name, result)
        if not self._stopping and name == self.person:
            self.summary.setText(f"Controlled encoding failed: {error}" if error else
                f"Controlled encoding finished: {result.face_encodings} face / {result.body_encodings} body embeddings. Rebuild the shortlist to review again.")
            self._result = None
            self._snapshot = None
            self.results.clear()
            self.apply_button.setEnabled(False)

    def _on_thread_finished(self):
        QTimer.singleShot(0, self._finalize_thread)

    def _finalize_thread(self):
        if self._thread is None or self._thread.isRunning(): return
        if not self._result_received and not self._stopping:
            self.activity_message.emit(f"[Controlled Encoding][Error] {self._operation_name}: Worker stopped without a result.")
            if self.person == self._operation_name: self.summary.setText("Controlled encoding stopped without a result.")
        self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self._running = False
        self.apply_button.setEnabled(not self._stopping and self._result is not None and self._snapshot is not None)

    def shutdown(self):
        if self._stopping: return
        self._stopping = True
        self.apply_button.setEnabled(False)
        thread, worker = self._thread, self._worker
        if thread is not None:
            if worker is not None: worker.cancel_before_start()
            thread.quit()
            thread.wait()  # An active transaction must finish before the service is destroyed.
