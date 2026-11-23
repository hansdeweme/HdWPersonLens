"""Workbench-owned full-person removal review; DB-record-only deletion remains separate."""

import os

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout


class WorkbenchRemovePanel(QGroupBox):
    remove_requested = pyqtSignal(str, bool, str)

    def __init__(self, service, parent=None):
        super().__init__("Remove selected person", parent)
        self.service = service
        self.person_name = ""
        self.original_photo_path = ""
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_label = QLabel("—")
        self.photo_path = QLabel("—")
        self.photo_path.setWordWrap(True)
        form.addRow("Selected person:", self.name_label)
        form.addRow("External photo folder:", self.photo_path)
        layout.addLayout(form)
        self.scope = QLabel("Full removal deletes the KB folder, face/body encoding entries, and Persons DB record when present.")
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        self.delete_photos = QCheckBox("Also permanently delete the external photo collection folder")
        layout.addWidget(self.delete_photos)
        self.preservation = QLabel("External photo collection is preserved by default. DB-record-only deletion remains available in Persons DB.")
        self.preservation.setWordWrap(True)
        layout.addWidget(self.preservation)
        controls = QHBoxLayout()
        self.review_button = QPushButton("Review Permanent Removal")
        self.review_button.setProperty("themeRole", "danger")
        self.cancel_button = QPushButton("Cancel")
        controls.addWidget(self.review_button)
        controls.addWidget(self.cancel_button)
        controls.addStretch()
        layout.addLayout(controls)
        self.review_button.clicked.connect(self._review)
        self.cancel_button.clicked.connect(self.hide)
        self.setVisible(False)

    def open_for(self, name: str) -> bool:
        record = self.service.get_person_record(name)
        if not name or record is None: return False
        self.person_name = name
        self.original_photo_path = str(record.get("files_path") or "").strip()
        exists = bool(self.original_photo_path and os.path.isdir(self.original_photo_path))
        self.name_label.setText(name)
        self.photo_path.setText(self.original_photo_path or "—")
        if self.original_photo_path and not exists:
            self.photo_path.setText(f"{self.original_photo_path}\n(folder does not exist; no external files will be deleted)")
        self.delete_photos.setChecked(False)
        self.delete_photos.setEnabled(exists)
        self.setVisible(True)
        self.review_button.setFocus()
        return True

    def confirm_discard(self) -> bool:
        if self.isHidden(): return True
        if self.delete_photos.isChecked():
            answer = QMessageBox.question(self, "Discard Removal Review", "Discard the pending removal options?",
                                          QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                          QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Discard: return False
        self.hide()
        return True

    def _review(self):
        name, delete_photos = self.person_name, self.delete_photos.isChecked()
        confirmed_path = self.original_photo_path
        record = self.service.get_person_record(name)
        if record is None or str(record.get("files_path") or "").strip() != confirmed_path:
            QMessageBox.warning(self, "Removal Source Changed", "The record changed. Refresh and review removal again.")
            return
        if delete_photos and not os.path.isdir(confirmed_path):
            QMessageBox.warning(self, "External Photo Folder Changed", "The external photo folder is unavailable. Review the removal scope again.")
            return
        message = (f"Permanently remove '{name}'?\n\nThis removes:\n• Face and body encodings\n"
                   "• Knowledge-base folder and its images\n• Persons DB record, when present")
        message += (f"\n\nALSO PERMANENTLY DELETE EXTERNAL PHOTO FOLDER:\n{confirmed_path}" if delete_photos
                    else "\n\nThe external photo collection folder will be preserved.")
        answer = QMessageBox.warning(self, "Confirm Permanent Removal", message,
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes: return
        record = self.service.get_person_record(name)
        if (record is None or str(record.get("files_path") or "").strip() != confirmed_path or
                self.person_name != name or self.original_photo_path != confirmed_path or self.delete_photos.isChecked() != delete_photos):
            QMessageBox.warning(self, "Removal Source Changed", "The selected record changed during confirmation. Refresh and review again.")
            return
        if delete_photos and not os.path.isdir(confirmed_path):
            QMessageBox.warning(self, "Photo Folder Changed", "External photo folder changed during confirmation.")
            return
        self.remove_requested.emit(name, delete_photos, confirmed_path)
