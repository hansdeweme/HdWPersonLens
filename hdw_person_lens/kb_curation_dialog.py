# kb_curation_dialog.py 
# GUI for reviewing possible KB curation images
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project.
#
from __future__ import annotations
import html
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
# PyQt6 imports
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, 
                             QSplitter, QTextEdit, QVBoxLayout, QWidget, QProgressBar, QPlainTextEdit)
# local imports
from .kb_curation import KBCandidateStore, KBCurationResult, KBPromotionCandidate, apply_kb_curation_decisions

class KBCurationDialog(QDialog):
    # Review pending KB candidates and apply staged decisions explicitly
    curation_completed = pyqtSignal(object)
    def __init__(self, *, person_service, settings: Mapping[str, Any], parent=None, on_done=None):
        super().__init__(parent)
        self.person_service = person_service
        self.settings = dict(settings or {})
        self.on_done = on_done
        self.output_dir = Path(self.settings.get("output_folder", "")).expanduser()
        self.store = KBCandidateStore.for_output_folder(self.output_dir)
        self.candidates: list[KBPromotionCandidate] = []
        self.by_id: dict[str, KBPromotionCandidate] = {}
        self.decisions: dict[str, dict[str, str]] = {}
        self.current_person = ""
        self.current_candidate_id = ""
        self.busy = False
        self.worker: KBCurationWorker | None = None
        self._worker_result: KBCurationResult | None = None
        self._worker_error = ""
        self.setWindowTitle("Curate Knowledge Base Candidates")
        self.resize(1180, 760)
        self._build_ui()
        self._reload_candidates()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Persons with candidates"))
        self.person_list = QListWidget()
        self.person_list.currentItemChanged.connect(self._on_person_changed)
        left_layout.addWidget(self.person_list, 1)
        left_layout.addWidget(QLabel("Candidates"))
        self.candidate_list = QListWidget()
        self.candidate_list.currentItemChanged.connect(self._on_candidate_changed)
        left_layout.addWidget(self.candidate_list, 2)
        splitter.addWidget(left)
        centre = QWidget()
        centre_layout = QVBoxLayout(centre)
        candidate_group = QGroupBox("Candidate")
        candidate_layout = QVBoxLayout(candidate_group)
        self.candidate_image = QLabel("No candidate selected")
        self.candidate_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.candidate_image.setMinimumSize(420, 360)
        self.candidate_image.setStyleSheet("QLabel { background: #202020; color: #d0d0d0; border: 1px solid #555; }")
        candidate_layout.addWidget(self.candidate_image, 1)
        self.candidate_path = QLabel()
        self.candidate_path.setWordWrap(True)
        self.candidate_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        candidate_layout.addWidget(self.candidate_path)
        centre_layout.addWidget(candidate_group, 3)
        evidence_group = QGroupBox("Recognition evidence")
        evidence_layout = QVBoxLayout(evidence_group)
        self.evidence_label = QLabel()
        self.evidence_label.setWordWrap(True)
        self.evidence_label.setTextFormat(Qt.TextFormat.RichText)
        self.evidence_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        evidence_layout.addWidget(self.evidence_label)
        centre_layout.addWidget(evidence_group, 1)
        splitter.addWidget(centre)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.references_title = QLabel("Existing KB references")
        right_layout.addWidget(self.references_title)
        self.references_scroll = QScrollArea()
        self.references_scroll.setWidgetResizable(True)
        self.references_widget = QWidget()
        self.references_grid = QGridLayout(self.references_widget)
        self.references_scroll.setWidget(self.references_widget)
        right_layout.addWidget(self.references_scroll, 1)
        splitter.addWidget(right)
        splitter.setSizes([260, 500, 360])
        note_row = QHBoxLayout()
        note_row.addWidget(QLabel("Decision note:"))
        self.note_edit = QTextEdit()
        self.note_edit.setFixedHeight(58)
        note_row.addWidget(self.note_edit, 1)
        root.addLayout(note_row)
        action_row = QHBoxLayout()
        self.promote_btn = QPushButton("Promote to KB")
        self.reject_btn = QPushButton("Reject Candidate")
        self.defer_btn = QPushButton("Defer")
        self.clear_btn = QPushButton("Clear Staged Decision")
        self.promote_btn.clicked.connect(lambda: self._stage("promote"))
        self.reject_btn.clicked.connect(lambda: self._stage("reject"))
        self.defer_btn.clicked.connect(lambda: self._stage("defer"))
        self.clear_btn.clicked.connect(self._clear_current_decision)
        action_row.addWidget(self.promote_btn)
        action_row.addWidget(self.reject_btn)
        action_row.addWidget(self.defer_btn)
        action_row.addWidget(self.clear_btn)
        action_row.addStretch(1)
        root.addLayout(action_row)
        footer = QHBoxLayout()
        self.queue_label = QLabel()
        footer.addWidget(self.queue_label, 1)
        self.apply_btn = QPushButton("Apply KB Changes")
        self.close_btn = QPushButton("Close")
        self.apply_btn.clicked.connect(self._request_apply)
        self.close_btn.clicked.connect(self.reject)
        footer.addWidget(self.apply_btn)
        footer.addWidget(self.close_btn)
        root.addLayout(footer)
        progress_group = QGroupBox("Curation Progress")
        progress_layout = QVBoxLayout(progress_group)
        self.operation_label = QLabel("No operation running.")
        self.operation_label.setWordWrap(True)
        self.curation_progress = QProgressBar()
        self.curation_progress.setRange(0, 100)
        self.curation_progress.setValue(0)
        self.activity_log = QPlainTextEdit()
        self.activity_log.setReadOnly(True)
        self.activity_log.setMaximumBlockCount(500)
        self.activity_log.setMinimumHeight(130)
        progress_layout.addWidget(self.operation_label)
        progress_layout.addWidget(self.curation_progress)
        progress_layout.addWidget(self.activity_log)
        root.addWidget(progress_group)        

    def _update_curation_progress(self, value: int) -> None:
        self.curation_progress.setValue(max(0, min(100, int(value))))

    def _append_curation_log(self, message: str) -> None:
        text = str(message or "").strip()
        if not text:
            return
        self.activity_log.appendPlainText(text)
        self.operation_label.setText(text)
        scrollbar = self.activity_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


    def _reload_candidates(self, *, preferred_person: str = "", preferred_candidate_id: str = "") -> None:
        try:
            all_candidates = self.store.load_candidates(status=None)
        except Exception as exc:
            QMessageBox.critical(self, "KB Candidate Store Error", str(exc))
            all_candidates = []
        self.candidates = [candidate for candidate in all_candidates if candidate.status in {"pending", "deferred", "failed"}]
        self.by_id = {candidate.candidate_id: candidate for candidate in self.candidates}
        valid_ids = set(self.by_id)
        self.decisions = {candidate_id: decision for candidate_id, decision in self.decisions.items() if candidate_id in valid_ids}
        counts = Counter(candidate.person_name for candidate in self.candidates)
        self.person_list.blockSignals(True)
        self.person_list.clear()
        for person_name in sorted(counts, key=str.casefold):
            item = QListWidgetItem(f"{person_name}  ({counts[person_name]})")
            item.setData(Qt.ItemDataRole.UserRole, person_name)
            self.person_list.addItem(item)
        self.person_list.blockSignals(False)
        self.summary_label.setText(
            f"Active KB candidates: {len(self.candidates)} across {len(counts)} person(s). "
            "Promotions copy selected output images into the KB and re-encode each affected person once."
        )
        target_row = 0
        target_person = preferred_person or self.current_person
        for row in range(self.person_list.count()):
            item = self.person_list.item(row)
            if str(item.data(Qt.ItemDataRole.UserRole)).casefold() == target_person.casefold():
                target_row = row
                break
        if self.person_list.count():
            self.person_list.setCurrentRow(target_row)
            if preferred_candidate_id:
                self._select_candidate(preferred_candidate_id)
        else:
            self.current_person = ""
            self.current_candidate_id = ""
            self.candidate_list.clear()
            self._show_empty_state()
        self._refresh_queue_label()
        self._set_busy(self.busy)

    def _on_person_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        self.current_person = str(current.data(Qt.ItemDataRole.UserRole)) if current else ""
        self._populate_candidate_list()
        self._load_reference_images()

    def _populate_candidate_list(self) -> None:
        current_id = self.current_candidate_id
        self.candidate_list.blockSignals(True)
        self.candidate_list.clear()
        rows = [candidate for candidate in self.candidates if candidate.person_name == self.current_person]
        rows.sort(key=lambda candidate: (candidate.status != "pending", candidate.created_at_utc, candidate.candidate_id))
        for candidate in rows:
            decision = self.decisions.get(candidate.candidate_id, {})
            staged = str(decision.get("action", "") or "")
            suffix = f"  → {staged.upper()}" if staged else ""
            item = QListWidgetItem(f"{Path(candidate.source_path).name}  [{candidate.status}]{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, candidate.candidate_id)
            self.candidate_list.addItem(item)
        self.candidate_list.blockSignals(False)
        target_row = 0
        for row in range(self.candidate_list.count()):
            if self.candidate_list.item(row).data(Qt.ItemDataRole.UserRole) == current_id:
                target_row = row
                break
        if self.candidate_list.count():
            self.candidate_list.setCurrentRow(target_row)
        else:
            self.current_candidate_id = ""
            self._show_empty_state()

    def _on_candidate_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        self.current_candidate_id = str(current.data(Qt.ItemDataRole.UserRole)) if current else ""
        candidate = self.by_id.get(self.current_candidate_id)
        if candidate is None:
            self._show_empty_state()
            return
        self._show_candidate(candidate)

    def _show_candidate(self, candidate: KBPromotionCandidate) -> None:
        path = Path(candidate.source_path)
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.candidate_image.setPixmap(QPixmap())
            self.candidate_image.setText("Image missing or unreadable")
        else:
            self.candidate_image.setText("")
            self.candidate_image.setPixmap(
                pixmap.scaled(self.candidate_image.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.candidate_path.setText(str(path))
        self.note_edit.setPlainText(self.decisions.get(candidate.candidate_id, {}).get("note", candidate.note or ""))
        contender = candidate.selected_contender or {}
        machine = candidate.machine_record or {}
        face_distance = self._format_number(contender.get("face_distance"))
        body_similarity = self._format_number(contender.get("body_similarity"))
        face_rank = contender.get("face_rank", "—")
        body_rank = contender.get("body_rank", "—")
        reason = machine.get("decision_reason") or machine.get("reason") or "—"
        session = candidate.review_session_id or "—"
        dimensions = "—" if pixmap.isNull() else f"{pixmap.width()} × {pixmap.height()}"
        self.evidence_label.setText(
            f"<b>Person:</b> {html.escape(candidate.person_name)}<br>"
            f"<b>Candidate status:</b> {html.escape(candidate.status)}<br>"
            f"<b>Image:</b> {dimensions}<br>"
            f"<b>Face distance:</b> {face_distance} &nbsp; <b>rank:</b> {html.escape(str(face_rank))}<br>"
            f"<b>Body similarity:</b> {body_similarity} &nbsp; <b>rank:</b> {html.escape(str(body_rank))}<br>"
            f"<b>Decision reason:</b> {html.escape(str(reason))}<br>"
            f"<b>Review session:</b> {html.escape(session)}<br>"
            f"<b>SHA-256:</b> <span style='font-family:monospace'>{html.escape(candidate.source_sha256)}</span>"
        )
        self._set_busy(self.busy)

    def _load_reference_images(self) -> None:
        while self.references_grid.count():
            item = self.references_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self.current_person:
            self.references_title.setText("Existing KB references")
            return
        try:
            paths = [Path(path) for path in self.person_service.get_person_image_paths(self.current_person)]
        except Exception as exc:
            paths = []
            label = QLabel(f"Could not load KB references:\n{exc}")
            label.setWordWrap(True)
            self.references_grid.addWidget(label, 0, 0)
        self.references_title.setText(f"Existing KB references for {self.current_person} ({len(paths)})")
        max_refs = int(self.settings.get("kb_curation_reference_limit", 18) or 18)
        for index, path in enumerate(paths[:max_refs]):
            card = QWidget()
            layout = QVBoxLayout(card)
            layout.setContentsMargins(2, 2, 2, 2)
            image = QLabel()
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image.setFixedSize(102, 102)
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                image.setPixmap(pixmap.scaled(image.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            else:
                image.setText("Unreadable")
            name = QLabel(path.name)
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name.setWordWrap(True)
            layout.addWidget(image)
            layout.addWidget(name)
            self.references_grid.addWidget(card, index // 3, index % 3)
        if len(paths) > max_refs:
            note = QLabel(f"{len(paths) - max_refs} more reference image(s) not shown.")
            note.setWordWrap(True)
            self.references_grid.addWidget(note, (max_refs + 2) // 3, 0, 1, 3)

    def _stage(self, action: str) -> None:
        candidate = self.by_id.get(self.current_candidate_id)
        if candidate is None:
            return
        self.decisions[candidate.candidate_id] = {"action": action, "note": self.note_edit.toPlainText().strip()}
        self._populate_candidate_list()
        self._select_candidate(candidate.candidate_id)
        self._refresh_queue_label()

    def _clear_current_decision(self) -> None:
        candidate_id = self.current_candidate_id
        if not candidate_id:
            return
        self.decisions.pop(candidate_id, None)
        self._populate_candidate_list()
        self._select_candidate(candidate_id)
        self._refresh_queue_label()

    def _select_candidate(self, candidate_id: str) -> None:
        for row in range(self.candidate_list.count()):
            item = self.candidate_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == candidate_id:
                self.candidate_list.setCurrentRow(row)
                return

    def _refresh_queue_label(self) -> None:
        counts = Counter(decision.get("action", "") for decision in self.decisions.values())
        self.queue_label.setText(
            f"{counts['promote']} promotion(s), {counts['reject']} rejection(s), "
            f"{counts['defer']} deferred, {len(self.candidates) - len(self.decisions)} undecided"
        )
        self.apply_btn.setEnabled(not self.busy and bool(self.decisions))

    def _worker_decisions(self) -> list[dict[str, str]]:
        return [{"candidate_id": candidate_id, "action": decision.get("action", ""), "note": decision.get("note", "")} for candidate_id, decision in self.decisions.items()]

    def _request_apply(self) -> None:
        if self.busy or not self.decisions:
            return
        self.activity_log.clear()
        self.curation_progress.setValue(0)
        self.operation_label.setText("Preparing KB curation...")        
        counts = Counter(decision.get("action", "") for decision in self.decisions.values())
        promoted_people = sorted({
            self.by_id[candidate_id].person_name for candidate_id, decision in self.decisions.items()
            if decision.get("action") == "promote" and candidate_id in self.by_id
        }, key=str.casefold)
        message = f"Promote to KB: {counts['promote']}\nReject: {counts['reject']}\nDefer: {counts['defer']}\n\n"
        if promoted_people:
            message += (
                "The following person(s) will be re-encoded once after all selected images are copied:\n"
                + "\n".join(f"• {name}" for name in promoted_people) + "\n\n"
            )
        message += "Processed-output images remain in place. Apply these decisions?"
        reply = QMessageBox.question(self, "Apply KB Curation Decisions", message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._worker_result = None
        self._worker_error = ""
        self._set_busy(True)
        self.worker = KBCurationWorker(decisions=self._worker_decisions(), store=self.store, person_service=self.person_service, parent=self,)
        parent = self.parent()
        progress_handler = getattr(parent, "store_progress_value", None)
        log_handler = getattr(parent, "display_message", None)
        if callable(progress_handler):
            self.worker.progress.connect(progress_handler)
            self.worker.progress.connect(self._update_curation_progress)
        if callable(log_handler):
            self.worker.log_message.connect(log_handler)
            self.worker.log_message.connect(self._append_curation_log)
        self.worker.result_ready.connect(self._store_worker_result)
        self.worker.failed.connect(self._store_worker_error)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def _store_worker_result(self, result: KBCurationResult) -> None:
        self._worker_result = result

    def _store_worker_error(self, message: str) -> None:
        self._worker_error = str(message)

    def _on_worker_finished(self) -> None:
        self.worker = None
        self._set_busy(False)
        if self._worker_error:
            QMessageBox.critical(self, "KB Curation Failed", self._worker_error)
            return
        result = self._worker_result
        if result is None:
            QMessageBox.critical(self, "KB Curation Failed", "The curation worker returned no result.")
            return
        successful = set(result.successful_candidate_ids)
        self.decisions = {candidate_id: decision for candidate_id, decision in self.decisions.items() if candidate_id not in successful}
        previous_person = self.current_person
        self._reload_candidates(preferred_person=previous_person)
        self.curation_completed.emit(result)
        if callable(self.on_done):
            self.on_done()
        summary = (
            f"Promoted: {result.promoted_images}\nAlready present in KB: {result.already_present}\n"
            f"Rejected: {result.rejected_images}\nDeferred: {result.deferred_images}\n"
            f"Persons re-encoded: {len(result.updated_persons)}"
        )
        if result.failed_items or result.warnings:
            issues = [f"{candidate_id}: {message}" for candidate_id, message in result.failed_items]
            issues.extend(result.warnings)
            QMessageBox.warning(self, "KB Curation Completed with Issues", summary + "\n\n" + "\n".join(f"• {item}" for item in issues),)
            self.operation_label.setText("KB curation completed with issues.")
            for candidate_id, message in result.failed_items:
                self._append_curation_log(f"[FAILED] {candidate_id}: {message}")
            for warning in result.warnings:
                self._append_curation_log(f"[WARNING] {warning}")                          
        else:
            QMessageBox.information(self, "KB Curation Completed", summary)
            self.curation_progress.setValue(100)
            self.operation_label.setText(
                f"Completed: {result.promoted_images} promoted, "
                f"{result.rejected_images} rejected, "
                f"{result.deferred_images} deferred."
            )            

    def _set_busy(self, busy: bool) -> None:
        self.busy = bool(busy)
        has_candidate = self.current_candidate_id in self.by_id
        for widget in (
            self.person_list, self.candidate_list, self.note_edit, self.promote_btn,
            self.reject_btn, self.defer_btn, self.clear_btn, self.close_btn,
        ):
            widget.setEnabled(not self.busy)
        self.promote_btn.setEnabled(not self.busy and has_candidate)
        self.reject_btn.setEnabled(not self.busy and has_candidate)
        self.defer_btn.setEnabled(not self.busy and has_candidate)
        self.clear_btn.setEnabled(not self.busy and has_candidate)
        self.apply_btn.setEnabled(not self.busy and bool(self.decisions))

    def _show_empty_state(self) -> None:
        self.candidate_image.setPixmap(QPixmap())
        self.candidate_image.setText("No active KB candidates")
        self.candidate_path.clear()
        self.evidence_label.setText("Images appear here only after a reviewed assignment is explicitly marked for later KB consideration.")
        self.note_edit.clear()
        self._set_busy(self.busy)

    @staticmethod
    def _format_number(value: Any) -> str:
        try:
            return f"{float(value):.4f}"
        except (TypeError, ValueError):
            return "—"

    def reject(self) -> None:
        if self.busy:
            QMessageBox.information(self, "Operation Running", "Wait until KB curation has finished.")
            return
        if not self.decisions:
            super().reject()
            return
        reply = QMessageBox.question(self, "Discard Staged Decisions", f"Discard {len(self.decisions)} staged KB-curation decision(s)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,)
        if reply == QMessageBox.StandardButton.Yes:
            super().reject()

class KBCurationWorker(QThread):
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)
    def __init__(self, *, decisions: Sequence[Mapping[str, Any]], store: KBCandidateStore, person_service, parent=None):
        super().__init__(parent)
        self.decisions = [dict(item) for item in decisions]
        self.store = store
        self.person_service = person_service

    def run(self) -> None:
        try:
            result = apply_kb_curation_decisions(
                self.decisions, store=self.store, person_service=self.person_service,
                on_log=self.log_message.emit, on_progress=self.progress.emit,
            )
            self.result_ready.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
