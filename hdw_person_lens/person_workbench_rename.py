"""Workbench-owned rename interaction; the main window performs the service transaction."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout
from .person_management_evidence import person_revision


class WorkbenchRenamePanel(QGroupBox):
    rename_requested = pyqtSignal(str, str, bool, object, str, object)

    def __init__(self, person_service, parent=None):
        super().__init__("Rename selected person", parent)
        self.person_service = person_service
        self.person_name = ""
        self.original_photo_path = ""
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.current_name = QLabel("—")
        self.new_name = QLineEdit()
        self.new_name.setAccessibleName("New person name")
        self.new_name.setPlaceholderText("Enter the new name")
        self.rename_photos = QCheckBox("Also rename the external photo collection folder")
        self.original_path = QLabel("—")
        self.original_path.setWordWrap(True)
        self.custom_path = QLineEdit()
        self.custom_path.setAccessibleName("New photo collection folder")
        self.custom_path.setPlaceholderText("Use suggested destination")
        form.addRow("Current person:", self.current_name)
        form.addRow("New name:", self.new_name)
        form.addRow(self.rename_photos)
        form.addRow("Current photo folder:", self.original_path)
        form.addRow("New photo folder:", self.custom_path)
        layout.addLayout(form)
        self.scope = QLabel("Renames KB folder, face/body encoding labels, and the DB record when present.")
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        buttons = QHBoxLayout()
        self.apply_button = QPushButton("Review Rename")
        self.apply_button.setProperty("themeRole", "primary")
        self.cancel_button = QPushButton("Cancel")
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.new_name.textChanged.connect(self._update_suggestion)
        self.rename_photos.toggled.connect(self._update_suggestion)
        self.rename_photos.toggled.connect(self.custom_path.setEnabled)
        self.apply_button.clicked.connect(self._review)
        self.cancel_button.clicked.connect(self.hide)
        self.setVisible(False)

    def open_for(self, name: str) -> bool:
        record = self.person_service.get_person_record(name)
        state = self.person_service.get_person_state(name) if name else None
        if not state or not (state.database_record_exists or state.has_recognition_state): return False
        self.person_name = name
        self.original_photo_path = str((record or {}).get("files_path") or "").strip()
        self.current_name.setText(name)
        self.original_path.setText(self.original_photo_path or "—")
        self.new_name.clear()
        self.rename_photos.setChecked(False)
        self.rename_photos.setEnabled(record is not None and bool(self.original_photo_path))
        self.custom_path.clear()
        self.custom_path.setEnabled(False)
        self._update_suggestion()
        self.setVisible(True)
        self.new_name.setFocus()
        return True

    def has_pending_changes(self) -> bool:
        return bool(self.new_name.text().strip() or self.rename_photos.isChecked() or self.custom_path.text().strip())

    def confirm_discard(self) -> bool:
        if self.isHidden(): return True
        if self.has_pending_changes():
            answer = QMessageBox.question(self, "Discard Rename", "Discard the pending rename?",
                                          QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                          QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Discard: return False
        self.hide()
        return True

    def _update_suggestion(self, *_args):
        if not self.rename_photos.isChecked():
            self.custom_path.setPlaceholderText("External photo folder will be preserved")
            return
        suggestion = self.person_service.suggest_photo_folder(self.person_name, self.new_name.text().strip())
        self.custom_path.setPlaceholderText(suggestion or "Use suggested destination")

    def _review(self):
        old_name, new_name = self.person_name, self.new_name.text().strip()
        original_state = self.person_service.get_person_state(old_name)
        try: original_evidence = person_revision(self.person_service, old_name)
        except (OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "Rename Source Unavailable", str(exc))
            return
        if not new_name:
            QMessageBox.warning(self, "Invalid Name", "The new name cannot be empty.")
            self.new_name.setFocus()
            return
        if old_name == new_name:
            QMessageBox.information(self, "No Change", "The old and new names are the same.")
            return
        record = self.person_service.get_person_record(old_name)
        if not (original_state.database_record_exists or original_state.has_recognition_state) or str((record or {}).get("files_path") or "").strip() != self.original_photo_path:
            QMessageBox.warning(self, "Rename Source Changed", "The selected record changed. Refresh and review the rename again.")
            return
        rename_photos = self.rename_photos.isChecked()
        if rename_photos and not original_state.database_record_exists:
            QMessageBox.warning(self, "Rename Photos Unavailable", "KB-only profiles have no DB photo-folder reference.")
            return
        custom_path = self.custom_path.text().strip() if rename_photos else ""
        target = (custom_path or self.person_service.suggest_photo_folder(old_name, new_name) or "automatic target path") if rename_photos else ""
        description = (f"Rename '{old_name}' to '{new_name}'?\n\nThis will update:\n"
                       "• Knowledge-base folder\n• Face and body encoding labels\n• Persons DB record, when present")
        description += f"\n• Photo collection folder → {target}" if rename_photos else "\n\nExternal photo collection folder will be preserved."
        answer = QMessageBox.question(self, "Confirm Rename", description, QMessageBox.StandardButton.Yes |
                                      QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes: return
        try: current_evidence = person_revision(self.person_service, old_name)
        except (OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "Rename Source Unavailable", str(exc))
            return
        if (self.person_name != old_name or self.original_photo_path != str((self.person_service.get_person_record(old_name) or {}).get("files_path") or "").strip() or
                self.new_name.text().strip() != new_name or self.rename_photos.isChecked() != rename_photos or
                (self.custom_path.text().strip() if rename_photos else "") != custom_path or
                current_evidence != original_evidence):
            QMessageBox.warning(self, "Rename Source Changed", "The person or rename options changed during confirmation. Review again.")
            return
        self.rename_requested.emit(old_name, new_name, rename_photos, custom_path or None, self.original_photo_path, original_evidence)
