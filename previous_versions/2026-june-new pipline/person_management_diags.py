#person_management.py
# Workers for person recognition management 
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#

import os
# PyQt6 imports
from PyQt6           import QtGui
from PyQt6.QtCore    import QThread, QSize, Qt, pyqtSignal, pyqtSlot, QObject
from PyQt6.QtGui     import QIcon, QPixmap
from PyQt6.QtWidgets import (QDialog, QMessageBox, QComboBox,  QDialogButtonBox, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,  
                             QFileDialog, QFormLayout, QCheckBox, QListWidget, QListWidgetItem, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem)
# local imports
from image_drop_list   import DropWidget
from person_service    import PersonConflictError, PersonNotFoundError, PersonServiceError


class SelectPersonDialog(QDialog):
    def __init__(self, person_names, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Person")
        self.selected_name = None
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Choose a person to search for:"))
        self.combo = QComboBox()
        self.combo.addItems(sorted(set(person_names)))
        layout.addWidget(self.combo)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def get_selected_name(self):
        return self.combo.currentText()

class AddPersonWorker(QObject):
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    completed = pyqtSignal()

    def __init__(self, person_service, name: str, images: list[str]):
        super().__init__()
        self.person_service = person_service
        self.name = name
        self.images = images

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = self.person_service.add_to_knowledge_base(
                name=self.name,
                images=self.images,
                on_log=self.log_message.emit,
                on_progress=self.progress.emit,
            )
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.completed.emit()

class AddPersonDialog(QDialog):
    person_added = pyqtSignal(object)
    create_db_record_requested = pyqtSignal(str, str)

    def __init__(self, person_service, parent=None):
        super().__init__(parent)
        self.person_service = person_service
        self.selected_images: list[str] = []
        self._image_keys: set[str] = set()
        self._name_has_conflict = False
        self.thread: QThread | None = None
        self.worker: AddPersonWorker | None = None
        self._worker_result = None
        self._worker_error = ""
        self.busy = False
        self.valid_extensions = self._normalized_extensions(
            self.person_service.settings.get("valid_extensions", [".jpg", ".jpeg", ".png", ".webp"],))
        self.setWindowTitle("Add Person")
        self.resize(720, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Person name:"))
        self.person_combo = QComboBox()
        self.person_combo.setEditable(True)
        self.person_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.person_combo.addItems(self.person_service.list_add_candidates())
        self.person_combo.lineEdit().setPlaceholderText("Select a Persons DB record or enter a new name")
        self.person_combo.currentTextChanged.connect(self._update_person_info)
        layout.addWidget(self.person_combo)
        self.record_info_label = QLabel()
        self.record_info_label.setWordWrap(True)
        self.record_info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.record_info_label)
        layout.addWidget(QLabel("Training images:"))
        self.drop_widget = DropWidget()
        self.drop_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.drop_widget.images_dropped.connect(self._add_image_paths)
        self.drop_widget.itemSelectionChanged.connect(self._sync_controls)
        layout.addWidget(self.drop_widget, 1)
        image_buttons = QHBoxLayout()
        self.select_button = QPushButton("Select Images…")
        self.remove_button = QPushButton("Remove Selected")
        self.clear_button = QPushButton("Clear")
        self.select_button.clicked.connect(self._select_images)
        self.remove_button.clicked.connect(self._remove_selected_images)
        self.clear_button.clicked.connect(self._clear_images)
        image_buttons.addWidget(self.select_button)
        image_buttons.addWidget(self.remove_button)
        image_buttons.addWidget(self.clear_button)
        image_buttons.addStretch()
        layout.addLayout(image_buttons)
        self.image_status_label = QLabel()
        self.image_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.image_status_label)
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.add_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        self.cancel_button = self.button_box.button(QDialogButtonBox.StandardButton.Cancel)
        self.add_button.setText("Add and Encode")
        self.button_box.accepted.connect(self._start_add)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)
        self._update_person_info(self.person_combo.currentText())
        self._sync_controls()

    @staticmethod
    def _path_key(path: str) -> str:
        return os.path.normcase(os.path.abspath(path))

    @staticmethod
    def _normalized_extensions(values) -> set[str]:
        extensions = set()
        for value in values or []:
            extension = str(value or "").strip().lower()
            if not extension:
                continue
            extensions.add(extension if extension.startswith(".") else f".{extension}" )
        return extensions

    def select_person(self, name: str) -> None:
        """Preselect a DB person when opened from the Persons DB form."""
        name = str(name or "").strip()
        if name:
            self.person_combo.setCurrentText(name)

    def _current_name(self) -> str:
        return " ".join(self.person_combo.currentText().split()).strip()

    def _update_person_info(self, raw_name: str) -> None:
        name = " ".join(str(raw_name or "").split()).strip()
        self._name_has_conflict = False
        if not name:
            self.record_info_label.setText("Enter a name or select a metadata-only person.")
            self._sync_controls()
            return
        recognition_name = self.person_service.find_recognition_name(name)
        if recognition_name is not None:
            state = self.person_service.get_person_state(recognition_name)
            self._name_has_conflict = True
            self.record_info_label.setText(
                f"A recognition profile already exists as "
                f"'{recognition_name}'.\n"
                f"Images: {state.image_count} | "
                f"Face encodings: {state.face_encodings} | "
                f"Body encodings: {state.body_encodings}\n\n"
                "Use Edit Person Images or Re-Encode Person instead."
            )
            self._sync_controls()
            return
        record = self.person_service.get_person_record(name)
        if record is None:
            self.record_info_label.setText("No Persons DB record exists. The recognition profile can still be created; metadata can be added afterward.")
        else:
            person_id = str(record.get("#person_id", "")).strip() or "—"
            files_path = str(record.get("files_path", "")).strip() or "—"
            self.record_info_label.setText(
                "Existing Persons DB record found.\n"
                f"Person ID: {person_id}\n"
                f"Photo collection: {files_path}"
            )
        self._sync_controls()

    def _select_images(self) -> None:
        patterns = " ".join(
            f"*{extension}"
            for extension in sorted(self.valid_extensions)
        )
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Training Images",
            "",
            f"Images ({patterns});;All Files (*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if files:
            self._add_image_paths(files)

    def _add_image_paths(self, paths) -> None:
        added_paths: list[str] = []
        rejected: list[str] = []
        for raw_path in paths:
            path = os.path.abspath(os.path.expanduser(str(raw_path or "").strip()))
            if (not path or not os.path.isfile(path) or os.path.splitext(path)[1].lower() not in self.valid_extensions):
                rejected.append(path or str(raw_path))
                continue
            key = self._path_key(path)
            if key in self._image_keys:
                continue
            self._image_keys.add(key)
            self.selected_images.append(path)
            added_paths.append(path)

        if added_paths:
            self.drop_widget.add_images(added_paths)
        if rejected:
            self.status_label.setText(f"Ignored {len(rejected)} unsupported or missing file(s).")
        elif added_paths:
            self.status_label.clear()
        self._sync_controls()

    def _remove_selected_images(self) -> None:
        selected_items = self.drop_widget.selectedItems()
        if not selected_items:
            return

        remove_keys = {
            self._path_key(str(item.data(Qt.ItemDataRole.UserRole) or ""))
            for item in selected_items
            if item.data(Qt.ItemDataRole.UserRole)
        }
        self.selected_images = [path for path in self.selected_images if self._path_key(path) not in remove_keys]
        self._image_keys.difference_update(remove_keys)

        for item in selected_items:
            row = self.drop_widget.row(item)
            self.drop_widget.takeItem(row)
        self._sync_controls()

    def _clear_images(self) -> None:
        self.selected_images.clear()
        self._image_keys.clear()
        self.drop_widget.clear()
        self.status_label.clear()
        self._sync_controls()

    def _start_add(self) -> None:
        name = self._current_name()

        if not name:
            QMessageBox.warning(self, "No Person Name", "Enter a valid person name.",)
            return

        if self._name_has_conflict:
            QMessageBox.warning(self, "Recognition Profile Exists", (f"A recognition profile already exists for '{name}'.\n\n" "Use Edit Person Images to add more images."),)
            return

        if not self.selected_images:
            QMessageBox.warning(self, "No Images Selected", "Select at least one training image.",)
            return

        reply = QMessageBox.question(self, "Create Recognition Profile", (
                f"Create a recognition profile for '{name}' using "
                f"{len(self.selected_images)} image(s)?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes,)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._worker_result = None
        self._worker_error = ""
        self._set_busy(True)
        parent = self.parent()
        reset_progress = getattr(parent, "reset_progress_bar", None)
        if callable(reset_progress):
            reset_progress()

        self.thread = QThread(self)
        self.worker = AddPersonWorker(person_service=self.person_service, name=name,images=list(self.selected_images),)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._forward_progress)
        self.worker.log_message.connect(self._forward_log)
        self.worker.finished.connect(self._store_result)
        self.worker.error.connect(self._store_error)
        self.worker.completed.connect(self.thread.quit)
        self.worker.completed.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._on_thread_finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _forward_progress(self, value: int) -> None:
        handler = getattr(self.parent(), "store_progress_value", None, )
        if callable(handler):
            handler(value)

    def _forward_log(self, message: str) -> None:
        handler = getattr(self.parent(), "display_message",  None,)
        if callable(handler):
            handler(message)

    def _store_result(self, result) -> None:
        self._worker_result = result

    def _store_error(self, message: str) -> None:
        self._worker_error = message

    def _on_thread_finished(self) -> None:
        result = self._worker_result
        error = self._worker_error
        self.thread = None
        self.worker = None
        self._set_busy(False)

        if error:
            self.status_label.setText("The recognition profile was not created.")
            QMessageBox.critical(self, "Add Person Failed",  error, )
            return

        if result is None:
            QMessageBox.critical(self, "Add Person Failed", "The worker completed without returning a result.", )
            return
        self._finish_success(result)

    def _finish_success(self, result) -> None:
        self.person_added.emit(result)
        summary = (
            f"Recognition profile created for '{result.name}'.\n\n"
            f"Training images supplied: {len(self.selected_images)}\n"
            f"Face encodings added: {result.face_encodings}\n"
            f"Body encodings added: {result.body_encodings}"
        )
        create_metadata = False
        if result.database_record_exists:
            QMessageBox.information(self, "Person Added", summary + "\n\nThe existing Persons DB record was linked.",)
        else:
            reply = QMessageBox.question(self, "Person Added", (summary + "\n\nNo Persons DB record exists yet. " "Create a metadata record now?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes, )
            create_metadata = (reply == QMessageBox.StandardButton.Yes)
        if create_metadata:
            self.create_db_record_requested.emit(result.name, self._suggest_files_path(),)
        self.accept()

    def _suggest_files_path(self) -> str:
        parents = {os.path.dirname(os.path.abspath(path)) for path in self.selected_images}
        return parents.pop() if len(parents) == 1 else ""

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        if busy:
            self.status_label.setText("Creating recognition profile and encodings…")
        self._sync_controls()

    def _sync_controls(self) -> None:
        has_name = bool(self._current_name())
        has_images = bool(self.selected_images)
        has_selection = bool(self.drop_widget.selectedItems())
        self.person_combo.setEnabled(not self.busy)
        self.drop_widget.setEnabled(not self.busy)
        self.select_button.setEnabled(not self.busy)
        self.remove_button.setEnabled(not self.busy and has_selection)
        self.clear_button.setEnabled(not self.busy and has_images)
        self.add_button.setEnabled(not self.busy and has_name and has_images and not self._name_has_conflict)
        self.cancel_button.setEnabled(not self.busy)
        self.image_status_label.setText(f"{len(self.selected_images)} image(s) selected")

    def reject(self) -> None:
        if self.busy:
            QMessageBox.information(self, "Operation Running", "Wait until the recognition profile has been created.",)
            return
        super().reject()

class RemovePersonDialog(QDialog):
    person_removed = pyqtSignal(str)
    def __init__(self, person_service, parent=None,):
        super().__init__(parent)
        self.person_service = person_service
        self.setWindowTitle("Remove Person")
        self.setMinimumWidth(520)
        layout = QFormLayout(self)
        # ---------- Person selection ----------
        self.person_combo = QComboBox()
        self.person_combo.addItems(self.person_service.list_person_names())
        layout.addRow("Select person to remove:", self.person_combo,)
        # ---------- Optional photo deletion ----------
        self.delete_photos_chk = QCheckBox("Also permanently delete the photo collection folder")
        layout.addRow(self.delete_photos_chk)
        self.files_path_label = QLabel("—")
        self.files_path_label.setWordWrap(True)
        self.files_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addRow("Photo folder:", self.files_path_label,)
        # ---------- Explanation ----------
        self.scope_label = QLabel(
            "The person will be removed from:\n"
            "• face and body encodings\n"
            "• the knowledge-base folder\n"
            "• the Persons DB record, when present"
        )
        self.scope_label.setWordWrap(True)
        layout.addRow(self.scope_label)
        # ---------- Buttons ----------
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.remove_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        self.remove_button.setText("Remove")
        self.button_box.accepted.connect(self.confirm_and_remove)
        self.button_box.rejected.connect(self.reject)
        layout.addRow(self.button_box)
        # ---------- Signals ----------
        self.person_combo.currentTextChanged.connect(self._update_files_path)
        self._update_files_path(self.person_combo.currentText())
        if self.person_combo.count() == 0:
            self.remove_button.setEnabled(False)
            self.files_path_label.setText("No persons available.")

    def select_person(self, name: str) -> None:
        index = self.person_combo.findText(name)
        if index >= 0:
            self.person_combo.setCurrentIndex(index)

    def _update_files_path(self, name: str, ) -> None:
        name = str(name or "").strip()
        record = (self.person_service.get_person_record(name) if name  else None)
        files_path = str((record or {}).get("files_path", "",)).strip()
        self.files_path_label.setText(files_path or "—")
        folder_available = bool(files_path and os.path.isdir(files_path))
        self.delete_photos_chk.setEnabled(folder_available)
        if not folder_available:
            self.delete_photos_chk.setChecked(False)
        if files_path and not folder_available:
            self.files_path_label.setText(f"{files_path}\n" "(folder not found; nothing will be deleted)")            

    def confirm_and_remove(self) -> None:
        name = (
            self.person_combo.currentText().strip()
        )
        if not name:
            QMessageBox.warning(self, "No Person Selected", "Select the person to remove.", )
            return
        delete_photo_folder = (self.delete_photos_chk.isChecked())
        confirmation_lines = [
            f"Permanently remove '{name}'?",
            "",
            "This will remove:",
            "• face and body encoding entries",
            "• the knowledge-base folder",
            "• the Persons DB record, when present",
        ]
        if delete_photo_folder:
            photo_path = (
                self.files_path_label.text()
                .splitlines()[0]
                .strip()
            )
            confirmation_lines.extend(
                [
                    "",
                    "The following photo collection folder "
                    "will also be permanently deleted:",
                    photo_path or "Unknown folder",
                ]
            )
        else:
            confirmation_lines.extend(
                [
                    "",
                    "The external photo collection folder "
                    "will be preserved.",
                ]
            )
        reply = QMessageBox.warning(self, "Confirm Permanent Removal",
            "\n".join(confirmation_lines),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.remove_button.setEnabled(False)
        self.person_combo.setEnabled(False)
        self.delete_photos_chk.setEnabled(False)
        try:
            result = self.person_service.remove_person(name=name, remove_database_record=True, delete_photo_folder=delete_photo_folder,)
        except PersonNotFoundError as exc:
            QMessageBox.warning(self, "Person Not Found", str(exc),)
            return
        except PersonConflictError as exc:
            QMessageBox.warning(self, "Removal Conflict", str(exc),)
            return
        except (PersonServiceError, ValueError) as exc:
            QMessageBox.critical(self, "Removal Failed", str(exc), )
            return
        except Exception as exc:
            QMessageBox.critical(self, "Unexpected Removal Error", str(exc),)
            return
        finally:
            self.remove_button.setEnabled(True)
            self.person_combo.setEnabled(True)
            # Recalculated in case the dialog remains open after an error.
            self._update_files_path(self.person_combo.currentText())
        removed_items = []
        if result.knowledge_base_changed:
            removed_items.append("knowledge-base folder and encodings")
        if result.database_changed:
            removed_items.append("Persons DB record")
        if result.photo_folder_changed:
            removed_items.append("photo collection folder")
        removed_text = (
            "\n".join(
                f"• {item}"
                for item in removed_items
            )
            if removed_items
            else "• No persisted resources were changed"
        )
        warning_text = ""
        if result.warnings:
            warning_text = (
                "\n\nWarnings:\n"
                + "\n".join(
                    f"• {warning}"
                    for warning in result.warnings
                )
            )
        QMessageBox.information(self, "Person Removed", (
                f"'{name}' was removed successfully.\n\n"
                f"Removed:\n{removed_text}\n\n"
                f"Face encodings removed: "
                f"{result.face_encodings}\n"
                f"Body encodings removed: "
                f"{result.body_encodings}"
                f"{warning_text}"
            ),
        )
        self.person_removed.emit(name)
        self.accept()

class AlterPersonDialog(QDialog):
    person_renamed = pyqtSignal(str, str)
    def __init__(self, person_service, parent=None, ):
        super().__init__(parent)
        self.person_service = person_service
        self.setWindowTitle("Rename Person")
        self.setMinimumWidth(540)
        layout = QFormLayout(self)

        # ---------- Existing person ----------
        self.person_combo = QComboBox()
        self.person_combo.addItems(self.person_service.list_person_names())
        # ---------- New name ----------
        self.new_name_edit = QLineEdit()
        self.new_name_edit.setPlaceholderText("Enter the new person name")

        # ---------- Photo collection ----------
        self.rename_photos_chk = QCheckBox("Also rename the photo collection folder")
        self.current_path_label = QLabel("—")
        self.current_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.current_path_label.setWordWrap(True)
        self.new_path_edit = QLineEdit()
        self.new_path_edit.setEnabled(False)
        self.new_path_edit.setPlaceholderText("Leave blank to use the suggested path")
        # ---------- Buttons ----------
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.rename_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        self.rename_button.setText("Rename")
        button_box.accepted.connect(self._do_rename)
        button_box.rejected.connect(self.reject)
        # ---------- Signals ----------
        self.person_combo.currentTextChanged.connect(self._refresh_paths)
        self.new_name_edit.textChanged.connect(self._refresh_paths)
        self.rename_photos_chk.toggled.connect(self._toggle_new_path_edit)
        # ---------- Layout ----------
        layout.addRow("Existing person:", self.person_combo,) 
        layout.addRow("New name:", self.new_name_edit,)
        layout.addRow(self.rename_photos_chk,)
        layout.addRow("Current photo folder:", self.current_path_label,)
        layout.addRow("New photo folder:", self.new_path_edit,)
        layout.addRow(button_box)
        self._refresh_paths()

    def select_person(self, name: str) -> None:
        index = self.person_combo.findText(name)
        if index >= 0:
            self.person_combo.setCurrentIndex(index)
      
    def _toggle_new_path_edit(self, enabled: bool,) -> None:
        self.new_path_edit.setEnabled(enabled)
        if not enabled:
            self.new_path_edit.clear()
        self._refresh_paths()

    def _refresh_paths(self,_value=None,) -> None:
        old_name = (self.person_combo.currentText().strip())
        record = (self.person_service.get_person_record(old_name))
        current_path = str((record or {}).get("files_path", "",)).strip()
        self.current_path_label.setText(current_path or "—")
        new_name = self.new_name_edit.text().strip()
        suggested_path = (self.person_service.suggest_photo_folder(old_name, new_name,))
        if (self.rename_photos_chk.isChecked() and suggested_path):
            # Use a placeholder instead of setText().
            # This prevents overwriting a custom path entered by the user.
            self.new_path_edit.setPlaceholderText(suggested_path)
        else:
            self.new_path_edit.setPlaceholderText("Leave blank to use the suggested path")        

    def _do_rename(self) -> None:
        old_name = (self.person_combo.currentText().strip() )
        new_name = (self.new_name_edit.text().strip())
        if not old_name:
            QMessageBox.warning(self, "No Person Selected", "Select the person to rename.",)
            return
        if not new_name:
            QMessageBox.warning(self, "Invalid Name", "The new name cannot be empty.",)
            self.new_name_edit.setFocus()
            return
        if old_name == new_name:
            QMessageBox.information(self, "No Change", "The old and new names are the same.",)
            return

        rename_photo_folder = (self.rename_photos_chk.isChecked())
        custom_photo_path = (self.new_path_edit.text().strip() if rename_photo_folder else "")

        # A blank value tells PersonService to use its automatic
        # sibling-folder suggestion.
        new_photo_path = (custom_photo_path or None)
        details = [
            f"Rename '{old_name}' to '{new_name}'?",
            "",
            "This will update:",
            "• the knowledge-base folder",
            "• face and body encoding labels",
            "• the Persons DB record, when present",
        ]

        if rename_photo_folder:
            suggested = (
                custom_photo_path
                or self.person_service.suggest_photo_folder(
                    old_name,
                    new_name,
                )
                or "automatic target path"
            )
            details.append(f"• photo collection folder → {suggested}")

        answer = QMessageBox.question(self, "Confirm Rename",
            "\n".join(details),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.rename_button.setEnabled(False)
        try:
            result = self.person_service.rename_person(
                old_name=old_name,
                new_name=new_name,
                rename_photo_folder=rename_photo_folder,
                new_photo_path=new_photo_path,
            )

        except PersonConflictError as exc:
            QMessageBox.warning(self, "Rename Conflict", str(exc),)
            return
        except PersonNotFoundError as exc:
            QMessageBox.warning(self, "Person Not Found", str(exc), )
            return
        except (PersonServiceError, ValueError) as exc:
            QMessageBox.critical(
                self,
                "Rename Failed",
                str(exc),
            )
            return
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Unexpected Rename Error",
                str(exc),
            )
            return
        finally:
            self.rename_button.setEnabled(True)
        changed = []
        if result.database_changed:
            changed.append("Persons DB record")

        if result.knowledge_base_changed:
            changed.append("knowledge-base folder and encodings")

        if result.photo_folder_changed:
            changed.append("photo collection folder")

        changed_text = (
            "\n".join(
                f"• {item}"
                for item in changed
            )
            if changed
            else "• No persisted resources changed"
        )
        QMessageBox.information(self, "Rename Completed",  (
                f"'{old_name}' was renamed to "
                f"'{new_name}'.\n\n"
                f"Updated:\n{changed_text}\n\n"
                f"Face labels renamed: "
                f"{result.face_encodings}\n"
                f"Body labels renamed: "
                f"{result.body_encodings}"
            ), )
        self.person_renamed.emit(old_name, new_name)
        self.accept()

class EditPersonImagesWorker(QObject):
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    completed = pyqtSignal()

    def __init__(self, person_service, name: str,  add_images: list[str],  remove_images: list[str],):
        super().__init__()
        self.person_service = person_service
        self.name = name
        self.add_images = add_images
        self.remove_images = remove_images

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = self.person_service.update_person_images(
                name=self.name,
                add_images=self.add_images,
                remove_images=self.remove_images,
                on_log=self.log_message.emit,
                on_progress=self.progress.emit,
            )
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.completed.emit()

class EditPersonImagesDialog(QDialog):
    person_images_updated = pyqtSignal(str, int, int)
    PATH_ROLE = int(Qt.ItemDataRole.UserRole)
    STATE_ROLE = PATH_ROLE + 1
    def __init__(self, person_service, parent=None):
        super().__init__(parent)
        self.person_service = person_service
        self.existing_images: list[str] = []
        self.pending_additions: dict[str, str] = {}
        self.pending_removals: dict[str, str] = {}
        self.thread: QThread | None = None
        self.worker: EditPersonImagesWorker | None = None
        self.busy = False
        self.setWindowTitle("Edit Person Images")
        self.resize(720, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select person:"))
        self.person_combo = QComboBox()
        self.person_combo.addItems(self.person_service.list_recognition_names())
        self.person_combo.currentTextChanged.connect(self._load_person)
        layout.addWidget(self.person_combo)
        self.image_list = QListWidget()
        self.image_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.image_list.setIconSize(QSize(110, 110))
        self.image_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.image_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.image_list.itemDoubleClicked.connect(self._preview_image)
        self.image_list.itemSelectionChanged.connect(self._sync_controls)
        layout.addWidget(self.image_list, 1)
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        buttons = QHBoxLayout()
        self.btn_add = QPushButton("Add Images…")
        self.btn_toggle_remove = QPushButton("Remove / Restore Selected")
        self.btn_discard = QPushButton("Discard Changes")
        self.btn_apply = QPushButton("Apply and Re-Encode")
        self.btn_close = QPushButton("Close")
        self.btn_add.clicked.connect(self._add_images)
        self.btn_toggle_remove.clicked.connect(self._toggle_selected_removal)
        self.btn_discard.clicked.connect(self._discard_changes)
        self.btn_apply.clicked.connect(self._apply_changes)
        self.btn_close.clicked.connect(self.reject)
        for button in (
            self.btn_add,
            self.btn_toggle_remove,
            self.btn_discard,
            self.btn_apply,
            self.btn_close,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self._load_person(self.person_combo.currentText())
        if not self.person_combo.count():
            self.status_label.setText("No recognition profiles are available.")

    @staticmethod
    def _path_key(path: str) -> str:
        return os.path.normcase(os.path.abspath(path))

    def _has_changes(self) -> bool:
        return bool(self.pending_additions or self.pending_removals)

    def _current_name(self) -> str:
        return self.person_combo.currentText().strip()

    def _load_person(self, name: str) -> None:
        if self.busy:
            return
        self.pending_additions.clear()
        self.pending_removals.clear()
        self.existing_images = (self.person_service.get_person_image_paths(name) if name else [])
        self._refresh_image_list()

    def _refresh_image_list(self) -> None:
        self.image_list.clear()
        for path in self.existing_images:
            key = self._path_key(path)
            removed = key in self.pending_removals
            filename = os.path.basename(path)
            label = f"[REMOVE] {filename}" if removed else filename
            item = QListWidgetItem(QIcon(path), label)
            item.setData(self.PATH_ROLE, path)
            item.setData(self.STATE_ROLE, "remove" if removed else "existing")
            item.setToolTip(path)
            self.image_list.addItem(item)

        for path in self.pending_additions.values():
            item = QListWidgetItem(QIcon(path), f"[ADD] {os.path.basename(path)}")
            item.setData(self.PATH_ROLE, path)
            item.setData(self.STATE_ROLE, "add")
            item.setToolTip(path)
            self.image_list.addItem(item)
        added = len(self.pending_additions)
        removed = len(self.pending_removals)
        self.status_label.setText(f"{len(self.existing_images)} existing image(s) | " f"+{added} pending | -{removed} pending" )
        self._sync_controls()

    def _preview_image(self, item: QListWidgetItem) -> None:
        path = str(item.data(self.PATH_ROLE) or "")
        if path and os.path.isfile(path):
            ImagePreviewDialog(path, self).exec()

    def _add_images(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Select Images", "", "Images (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff)",)
        if not files:
            return
        existing = {
            self._path_key(path): path
            for path in self.existing_images
        }
        for path in files:
            absolute_path = os.path.abspath(path)
            key = self._path_key(absolute_path)
            if key in existing:
                # Selecting an existing image cancels a pending removal.
                self.pending_removals.pop(key, None)
            else:
                self.pending_additions[key] = absolute_path
        self._refresh_image_list()

    def _toggle_selected_removal(self) -> None:
        selected_items = self.image_list.selectedItems()
        if not selected_items:
            return
        for item in selected_items:
            path = str(item.data(self.PATH_ROLE) or "")
            state = str(item.data(self.STATE_ROLE) or "")
            key = self._path_key(path)
            if state == "add":
                # A newly queued image can simply be removed from the queue.
                self.pending_additions.pop(key, None)
            elif key in self.pending_removals:
                self.pending_removals.pop(key, None)
            else:
                self.pending_removals[key] = path
        self._refresh_image_list()

    def _discard_changes(self) -> None:
        if not self._has_changes():
            return
        reply = QMessageBox.question(self, "Discard Changes", "Discard all pending image additions and removals?", 
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,)
        if reply == QMessageBox.StandardButton.Yes:
            self._load_person(self._current_name())

    def _apply_changes(self) -> None:
        name = self._current_name()
        if not name or not self._has_changes():
            return
        added = len(self.pending_additions)
        removed = len(self.pending_removals)
        reply = QMessageBox.question(self, "Apply Image Changes",  (
                f"Update '{name}'?\n\n"
                f"Add: {added}\n"
                f"Remove: {removed}\n\n"
                "The person will be re-encoded after the file changes."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._set_busy(True)
        self.thread = QThread(self)
        self.worker = EditPersonImagesWorker(self.person_service, name, list(self.pending_additions.values()), list(self.pending_removals.values()), )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._forward_progress)
        self.worker.log_message.connect(self._forward_log)
        self.worker.finished.connect(self._on_update_finished)
        self.worker.error.connect(self._on_update_error)
        self.worker.completed.connect(self.thread.quit)
        self.worker.completed.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._on_thread_finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _forward_progress(self, value: int) -> None:
        handler = getattr(self.parent(), "store_progress_value", None)
        if callable(handler):
            handler(value)

    def _forward_log(self, message: str) -> None:
        handler = getattr(self.parent(), "display_message", None)
        if callable(handler):
            handler(message)

    def _on_update_finished(self, result) -> None:
        name = result.name
        self.pending_additions.clear()
        self.pending_removals.clear()
        self.existing_images = self.person_service.get_person_image_paths(name)
        self._refresh_image_list()
        self.person_images_updated.emit(name, result.images_added, result.images_removed,)
        QMessageBox.information(self, "Images Updated", (
                f"'{name}' was updated successfully.\n\n"
                f"Added: {result.images_added}\n"
                f"Removed: {result.images_removed}\n"
                f"Face encodings: {result.face_encodings}\n"
                f"Body encodings: {result.body_encodings}"
            ),
        )

    def _on_update_error(self, message: str) -> None:
        self.status_label.setText("Update failed; pending changes were retained.")
        QMessageBox.critical(self, "Image Update Failed", message)

    def _on_thread_finished(self) -> None:
        self.thread = None
        self.worker = None
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        if busy:
            self.status_label.setText("Updating images and re-encoding…")
        self._sync_controls()

    def _sync_controls(self) -> None:
        has_person = bool(self._current_name())
        has_selection = bool(self.image_list.selectedItems())
        dirty = self._has_changes()
        # Lock the selected person while changes are pending. This avoids
        # accidentally discarding one person's pending changes by switching.
        self.person_combo.setEnabled(not self.busy and not dirty)
        self.image_list.setEnabled(not self.busy)
        self.btn_add.setEnabled(not self.busy and has_person)
        self.btn_toggle_remove.setEnabled(not self.busy and has_selection)
        self.btn_discard.setEnabled(not self.busy and dirty)
        self.btn_apply.setEnabled(not self.busy and dirty)
        self.btn_close.setEnabled(not self.busy)

    def reject(self) -> None:
        if self.busy:
            QMessageBox.information(
                self,
                "Operation Running",
                "Wait for the image update to finish.",
            )
            return
        if self._has_changes():
            reply = QMessageBox.question(
                self,
                "Discard Changes",
                "Close and discard all pending image changes?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        super().reject()

class ImagePreviewDialog(QDialog):
    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Image Preview with Zoom")
        self.setMinimumSize(800, 600)
        layout = QVBoxLayout(self)
        self.view = QGraphicsView()
        self.scene = QGraphicsScene()
        self.pixmap = QPixmap(image_path)
        self.pixmap_item = QGraphicsPixmapItem(self.pixmap)
        self.scene.addItem(self.pixmap_item)
        self.view.setScene(self.scene)
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.view.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)       
        self.view.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(self.view)
        self.view.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)      
        btn_layout = QHBoxLayout()
        self.btn_zoom_in = QPushButton("Zoom In")
        self.btn_zoom_out = QPushButton("Zoom Out")
        self.btn_reset = QPushButton("Reset")
        self.btn_close = QPushButton("Close")
        self.btn_zoom_in.clicked.connect(self.zoom_in)
        self.btn_zoom_out.clicked.connect(self.zoom_out)
        self.btn_reset.clicked.connect(self.reset_zoom)
        self.btn_close.clicked.connect(self.reject)
        for btn in [self.btn_zoom_in, self.btn_zoom_out, self.btn_reset, self.btn_close]:
            btn_layout.addWidget(btn)
        layout.addLayout(btn_layout)
        self.scale_factor = 1
        
    def zoom_in(self):
        self.scale_factor *= 1.25
        self.view.resetTransform()
        self.view.scale(self.scale_factor, self.scale_factor)

    def zoom_out(self):
        self.scale_factor /= 1.25
        self.view.resetTransform()
        self.view.scale(self.scale_factor, self.scale_factor)

    def reset_zoom(self):
        self.scale_factor = 1.0
        self.view.resetTransform()
        self.view.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
