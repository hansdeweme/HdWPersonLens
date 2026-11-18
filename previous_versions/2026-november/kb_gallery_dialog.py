#kb_gallery_dialog.py
# Dialog to apply proposal-first KB gallery optimization for the Person Recognition project.
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
from __future__ import annotations
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
# PyQt6 imports
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, 
                             QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
# local imports
from .kb_gallery_optimizer import (ACTION_ADD, ACTION_REMOVE, GalleryApplyResult, GalleryChangeSet, GalleryOptimizationReport, KBGalleryOptimizer, PersonGalleryProposal,
                                  apply_gallery_changes)

ROLE_LABELS = {
    "face_anchor": "Face Anchor", "face_variation": "Face Variation", "body_anchor": "Body Anchor",
    "body_variation": "Body Variation", "general_reference": "General Reference", "manual_review": "Manual Review",
    "duplicate": "Duplicate", "redundant": "Redundant", "reserve": "Reserve",
}

class KBGalleryOptimizerDialog(QDialog):
    optimization_applied = pyqtSignal(object)

    def __init__(self, *, person_db, person_service, knowledge_manager, settings: Mapping[str, Any], parent=None):
        super().__init__(parent)
        self.person_db = person_db
        self.person_service = person_service
        self.knowledge_manager = knowledge_manager
        self.settings = dict(settings or {})
        self.report: GalleryOptimizationReport | None = None
        self.proposals: dict[str, PersonGalleryProposal] = {}
        self.approved: dict[tuple[str, str], bool] = {}
        self.analysis_worker: GalleryAnalysisWorker | None = None
        self.apply_worker: GalleryApplyWorker | None = None
        self.busy = False
        self.analysis_stale = False
        self.current_person = ""
        self.setWindowTitle("Analyse and Optimize KB Gallery")
        self.resize(1260, 820)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Target gallery size:"))
        self.target_size = QSpinBox(); self.target_size.setRange(2, 50)
        self.target_size.setValue(max(2, int(self.settings.get("kb_gallery_target_size", 12))))
        controls.addWidget(self.target_size)
        self.recursive = QCheckBox("Scan Persons DB folders recursively")
        self.recursive.setChecked(bool(self.settings.get("kb_gallery_recursive", False)))
        controls.addWidget(self.recursive)
        controls.addStretch(1)
        self.analyze_btn = QPushButton("Analyse Galleries")
        self.analyze_btn.clicked.connect(self._start_analysis)
        controls.addWidget(self.analyze_btn)
        root.addLayout(controls)
        self.summary_label = QLabel("Run analysis to compare current KB images with each person's files_path collection.")
        self.summary_label.setWordWrap(True); root.addWidget(self.summary_label)
        splitter = QSplitter(Qt.Orientation.Horizontal); root.addWidget(splitter, 1)
        left = QWidget(); left_layout = QVBoxLayout(left); left_layout.addWidget(QLabel("Persons"))
        self.person_list = QListWidget(); self.person_list.currentItemChanged.connect(self._on_person_changed)
        left_layout.addWidget(self.person_list, 1); splitter.addWidget(left)
        right = QWidget(); right_layout = QVBoxLayout(right)
        preview_row = QHBoxLayout()
        self.preview = QLabel("Select a proposal row")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.preview.setFixedSize(300, 240)
        self.preview.setStyleSheet("QLabel { background: #202020; color: #d0d0d0; border: 1px solid #555; }")
        self.preview_info = QLabel(); self.preview_info.setWordWrap(True)
        self.preview_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        preview_row.addWidget(self.preview); preview_row.addWidget(self.preview_info, 1)
        right_layout.addLayout(preview_row)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Apply", "Action", "Role", "Origin", "Score", "File", "Reason"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._show_selected_row)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.horizontalHeader().setStretchLastSection(True)
        right_layout.addWidget(self.table, 1)
        splitter.addWidget(right); splitter.setSizes([260, 980])
        proposal_controls = QHBoxLayout()
        self.approve_adds_btn = QPushButton("Approve All Additions")
        self.clear_removes_btn = QPushButton("Clear All Removals")
        self.approve_adds_btn.clicked.connect(self._approve_all_additions)
        self.clear_removes_btn.clicked.connect(self._clear_all_removals)
        proposal_controls.addWidget(self.approve_adds_btn); proposal_controls.addWidget(self.clear_removes_btn)
        proposal_controls.addStretch(1)
        self.apply_btn = QPushButton("Apply Approved Changes")
        self.apply_btn.clicked.connect(self._request_apply); proposal_controls.addWidget(self.apply_btn)
        self.close_btn = QPushButton("Close"); self.close_btn.clicked.connect(self.reject); proposal_controls.addWidget(self.close_btn)
        root.addLayout(proposal_controls)
        progress_group = QGroupBox("Gallery Optimization Progress")
        progress_layout = QVBoxLayout(progress_group)
        self.operation_label = QLabel("No operation running."); self.operation_label.setWordWrap(True)
        self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(1000); self.log.setMinimumHeight(130)
        progress_layout.addWidget(self.operation_label); progress_layout.addWidget(self.progress); progress_layout.addWidget(self.log)
        root.addWidget(progress_group)
        self._set_busy(False)

    def _analysis_settings(self) -> dict[str, Any]:
        settings = dict(self.settings)
        settings["kb_gallery_target_size"] = self.target_size.value()
        settings["kb_gallery_recursive"] = self.recursive.isChecked()
        return settings

    def _start_analysis(self) -> None:
        if self.busy:
            return
        self.report = None; self.proposals.clear(); self.approved.clear(); self.analysis_stale = False
        self.person_list.clear(); self.table.setRowCount(0); self.progress.setValue(0); self.log.clear()
        self.operation_label.setText("Preparing gallery analysis…"); self._set_busy(True)
        self.analysis_worker = GalleryAnalysisWorker(person_db=self.person_db, person_service=self.person_service,
                                                     knowledge_manager=self.knowledge_manager,
                                                     settings=self._analysis_settings(), parent=self)
        self.analysis_worker.progress.connect(self.progress.setValue)
        self.analysis_worker.log_message.connect(self._append_log)
        self.analysis_worker.result_ready.connect(self._on_analysis_ready)
        self.analysis_worker.failed.connect(self._on_analysis_failed)
        self.analysis_worker.finished.connect(self._on_analysis_finished)
        self.analysis_worker.finished.connect(self.analysis_worker.deleteLater)
        self.analysis_worker.start()

    def _on_analysis_ready(self, report: GalleryOptimizationReport) -> None:
        self.report = report; self.proposals = {proposal.person_name: proposal for proposal in report.proposals}
        self.approved = {(proposal.person_name, item.path): bool(item.default_apply) for proposal in report.proposals
                         for item in proposal.items if item.action in {ACTION_ADD, ACTION_REMOVE}}
        self._populate_persons()
        additions = sum(len(proposal.additions) for proposal in report.proposals)
        removals = sum(len(proposal.removals) for proposal in report.proposals)
        reviews = sum(len(proposal.review_items) for proposal in report.proposals)
        self.summary_label.setText(
            f"Analysed {report.analyzed_images} image(s) for {len(report.proposals)} person(s): "
            f"{additions} proposed addition(s), {removals} optional removal(s), {reviews} manual-review item(s). "
            f"Cache hits/misses: {report.cache_hits}/{report.cache_misses}. "
            "Additions are approved by default; removals remain opt-in."
        )
        self._append_log(f"[Gallery] JSON report: {report.json_path}")
        self._append_log(f"[Gallery] CSV report: {report.csv_path}")
        self.operation_label.setText("Analysis completed. Review and approve the proposed changes.")
        self.progress.setValue(100)

    def _on_analysis_failed(self, message: str) -> None:
        self._append_log(f"[Gallery][ERROR] {message}")
        self.operation_label.setText("Gallery analysis failed.")
        QMessageBox.critical(self, "Gallery Analysis Failed", message)

    def _on_analysis_finished(self) -> None:
        self.analysis_worker = None; self._set_busy(False)

    def _populate_persons(self) -> None:
        self.person_list.blockSignals(True); self.person_list.clear()
        for proposal in sorted(self.proposals.values(), key=lambda item: item.person_name.casefold()):
            label = (f"{proposal.person_name}  (+{len(proposal.additions)} / -{len(proposal.removals)} / "
                     f"review {len(proposal.review_items)})")
            item = QListWidgetItem(label); item.setData(Qt.ItemDataRole.UserRole, proposal.person_name)
            self.person_list.addItem(item)
        self.person_list.blockSignals(False)
        if self.person_list.count():
            self.person_list.setCurrentRow(0)
        else:
            self.table.setRowCount(0)

    def _on_person_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        self.current_person = str(current.data(Qt.ItemDataRole.UserRole)) if current else ""
        self._populate_table()

    def _populate_table(self) -> None:
        proposal = self.proposals.get(self.current_person)
        self.table.blockSignals(True); self.table.setRowCount(0)
        if proposal is None:
            self.table.blockSignals(False); return
        self.table.setRowCount(len(proposal.items))
        for row, proposal_item in enumerate(proposal.items):
            apply_item = QTableWidgetItem()
            apply_item.setData(Qt.ItemDataRole.UserRole, proposal_item.path)
            if proposal_item.action in {ACTION_ADD, ACTION_REMOVE}:
                apply_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
                checked = self.approved.get((proposal.person_name, proposal_item.path), proposal_item.default_apply)
                apply_item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            else:
                apply_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 0, apply_item)
            values = [proposal_item.action.upper(), ROLE_LABELS.get(proposal_item.role, proposal_item.role.replace("_", " ").title()),
                      proposal_item.origin.upper(), f"{proposal_item.score:.3f}", Path(proposal_item.path).name, proposal_item.reason]
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(value); item.setData(Qt.ItemDataRole.UserRole, proposal_item.path)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents(); self.table.setColumnWidth(6, max(340, self.table.columnWidth(6)))
        self.table.blockSignals(False)
        if self.table.rowCount():
            self.table.selectRow(0)
        warning_text = "\n".join(f"• {warning}" for warning in proposal.warnings)
        self.preview_info.setText(
            f"<b>{proposal.person_name}</b><br>Current KB: {proposal.current_count}<br>Collection candidates: "
            f"{proposal.collection_count}<br>Proposed gallery: {proposal.proposed_count}/{proposal.target_size}"
            + (f"<br><br><b>Warnings</b><br>{warning_text}" if warning_text else "")
        )

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0 or not self.current_person:
            return
        path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if path:
            self.approved[(self.current_person, path)] = item.checkState() == Qt.CheckState.Checked
        self._update_apply_summary()

    def _show_selected_row(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row(); path = str(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) or "")
        proposal = self.proposals.get(self.current_person)
        proposal_item = next((item for item in proposal.items if item.path == path), None) if proposal else None
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.preview.setPixmap(QPixmap()); self.preview.setText("Image missing or unreadable")
        else:
            self.preview.setText(""); self.preview.setPixmap(pixmap.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                                           Qt.TransformationMode.SmoothTransformation))
        if proposal_item:
            face_support = "—" if proposal_item.face_support_distance is None else f"{proposal_item.face_support_distance:.4f}"
            body_support = "—" if proposal_item.body_support_similarity is None else f"{proposal_item.body_support_similarity:.4f}"
            self.preview_info.setText(
                f"<b>{Path(path).name}</b><br>Action: {proposal_item.action}<br>Role: "
                f"{ROLE_LABELS.get(proposal_item.role, proposal_item.role)}<br>Origin: {proposal_item.origin}<br>"
                f"Identity: {proposal_item.identity_status}<br>Face quality: {proposal_item.face_quality:.3f}<br>"
                f"Body quality: {proposal_item.body_quality:.3f}<br>Face support distance: {face_support}<br>"
                f"Body support similarity: {body_support}<br><br>{proposal_item.reason}<br><br>{path}"
            )

    def _approve_all_additions(self) -> None:
        for proposal in self.proposals.values():
            for item in proposal.additions:
                self.approved[(proposal.person_name, item.path)] = True
        self._populate_table(); self._update_apply_summary()

    def _clear_all_removals(self) -> None:
        for proposal in self.proposals.values():
            for item in proposal.removals:
                self.approved[(proposal.person_name, item.path)] = False
        self._populate_table(); self._update_apply_summary()

    def _approved_change_sets(self) -> list[GalleryChangeSet]:
        changes: list[GalleryChangeSet] = []
        for proposal in self.proposals.values():
            additions = tuple(item.path for item in proposal.additions if self.approved.get((proposal.person_name, item.path), False))
            removals = tuple(item.path for item in proposal.removals if self.approved.get((proposal.person_name, item.path), False))
            if additions or removals:
                changes.append(GalleryChangeSet(person_name=proposal.person_name, add_images=additions, remove_images=removals))
        return changes

    def _update_apply_summary(self) -> None:
        changes = self._approved_change_sets()
        additions = sum(len(change.add_images) for change in changes); removals = sum(len(change.remove_images) for change in changes)
        self.apply_btn.setText(f"Apply Approved Changes (+{additions} / -{removals})")
        self.apply_btn.setEnabled(not self.busy and not self.analysis_stale and bool(changes))

    def _request_apply(self) -> None:
        if self.busy or self.analysis_stale:
            return
        changes = self._approved_change_sets()
        if not changes:
            QMessageBox.information(self, "No Approved Changes", "Approve at least one addition or removal first."); return
        additions = sum(len(change.add_images) for change in changes); removals = sum(len(change.remove_images) for change in changes)
        message = (f"Persons to update: {len(changes)}\nImages to add: {additions}\nImages to remove: {removals}\n\n"
                   "Each person will be updated transactionally and re-encoded once. Continue?")
        reply = QMessageBox.question(self, "Apply Gallery Optimization", message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.progress.setValue(0); self.operation_label.setText("Applying approved gallery changes…"); self._set_busy(True)
        self.apply_worker = GalleryApplyWorker(change_sets=changes, person_service=self.person_service, parent=self)
        self.apply_worker.progress.connect(self.progress.setValue)
        self.apply_worker.log_message.connect(self._append_log)
        self.apply_worker.result_ready.connect(self._on_apply_ready)
        self.apply_worker.failed.connect(self._on_apply_failed)
        self.apply_worker.finished.connect(self._on_apply_finished)
        self.apply_worker.finished.connect(self.apply_worker.deleteLater)
        self.apply_worker.start()

    def _on_apply_ready(self, result: GalleryApplyResult) -> None:
        self.analysis_stale = True; self.progress.setValue(100)
        self.operation_label.setText("Gallery changes applied. Run analysis again before applying further changes.")
        self.optimization_applied.emit(result)
        summary = (f"Persons updated: {len(result.completed_persons)}\nImages added: {result.images_added}\n"
                   f"Images removed: {result.images_removed}\nFailures: {len(result.failures)}")
        if result.failures or result.warnings:
            details = [f"{name}: {message}" for name, message in result.failures] + list(result.warnings)
            QMessageBox.warning(self, "Gallery Optimization Completed with Issues", summary + "\n\n" + "\n".join(f"• {item}" for item in details))
        else:
            QMessageBox.information(self, "Gallery Optimization Completed", summary)

    def _on_apply_failed(self, message: str) -> None:
        self._append_log(f"[Gallery][ERROR] {message}"); self.operation_label.setText("Gallery update failed.")
        QMessageBox.critical(self, "Gallery Update Failed", message)

    def _on_apply_finished(self) -> None:
        self.apply_worker = None; self._set_busy(False); self._update_apply_summary()

    def _append_log(self, message: str) -> None:
        text = str(message or "").strip()
        if not text:
            return
        self.log.appendPlainText(text); self.operation_label.setText(text)
        scrollbar = self.log.verticalScrollBar(); scrollbar.setValue(scrollbar.maximum())
        parent = self.parent(); handler = getattr(parent, "display_message", None)
        if callable(handler):
            handler(text)

    def _set_busy(self, busy: bool) -> None:
        self.busy = bool(busy)
        for widget in (self.target_size, self.recursive, self.analyze_btn, self.person_list, self.table,
                       self.approve_adds_btn, self.clear_removes_btn, self.close_btn):
            widget.setEnabled(not self.busy)
        self._update_apply_summary()

    def reject(self) -> None:
        if self.busy:
            QMessageBox.information(self, "Operation Running", "Wait until the current gallery operation has finished."); return
        super().reject()

class GalleryAnalysisWorker(QThread):
    progress = pyqtSignal(int); log_message = pyqtSignal(str); result_ready = pyqtSignal(object); failed = pyqtSignal(str)

    def __init__(self, *, person_db, person_service, knowledge_manager, settings: Mapping[str, Any], parent=None):
        super().__init__(parent); self.person_db = person_db; self.person_service = person_service
        self.knowledge_manager = knowledge_manager; self.settings = dict(settings); self._stop = False

    def run(self) -> None:
        connected = False
        try:
            signal = getattr(self.knowledge_manager, "progress_signal", None)
            if signal is not None:
                signal.connect(self.log_message.emit); connected = True
            optimizer = KBGalleryOptimizer(person_db=self.person_db, person_service=self.person_service,
                                           knowledge_manager=self.knowledge_manager, settings=self.settings)
            report = optimizer.analyze_all(on_log=self.log_message.emit, on_progress=self.progress.emit,
                                           stop_flag=lambda: self._stop)
            self.result_ready.emit(report)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            if connected:
                try:
                    self.knowledge_manager.progress_signal.disconnect(self.log_message.emit)
                except TypeError:
                    pass

    def cancel(self) -> None:
        self._stop = True

class GalleryApplyWorker(QThread):
    progress = pyqtSignal(int); log_message = pyqtSignal(str); result_ready = pyqtSignal(object); failed = pyqtSignal(str)

    def __init__(self, *, change_sets: Sequence[GalleryChangeSet], person_service, parent=None):
        super().__init__(parent); self.change_sets = list(change_sets); self.person_service = person_service

    def run(self) -> None:
        try:
            result = apply_gallery_changes(self.change_sets, person_service=self.person_service, on_log=self.log_message.emit, on_progress=self.progress.emit)
            self.result_ready.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
