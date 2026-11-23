"""Workbench-owned guided recognition-profile creation, retaining the established service worker."""

import os
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from .config import DEFAULT_RECOGNITION_EXTENSIONS
from .image_drop_list import DropWidget
from .person_management_diags import AddPersonWorker


class WorkbenchAddPerson(QWidget):
    person_added = pyqtSignal(object)
    create_db_record_requested = pyqtSignal(str, str)
    close_requested = pyqtSignal()

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.images = {}
        self.busy = self._stopping = False
        self.thread = self.worker = None
        self._result, self._error, self._token = None, "", None
        self.extensions = {ext if ext.startswith(".") else f".{ext}" for ext in DEFAULT_RECOGNITION_EXTENSIONS}
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Create a recognition profile using selected training images."))
        self.name = QComboBox()
        self.name.setEditable(True)
        self.name.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.name.setAccessibleName("New recognition person name")
        self.name.lineEdit().setPlaceholderText("Select an existing metadata-only person or enter a new name")
        self.info = QLabel()
        self.info.setWordWrap(True)
        layout.addWidget(self.name)
        layout.addWidget(self.info)
        layout.addWidget(QLabel("Training images (source files are never moved):"))
        self.drop_list = DropWidget()
        self.drop_list.setAccessibleName("New person's training images")
        self.drop_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.drop_list.images_dropped.connect(self._add_paths)
        self.drop_list.itemSelectionChanged.connect(self._sync_controls)
        layout.addWidget(self.drop_list, 1)
        actions = QHBoxLayout()
        self.choose = QPushButton("Select Images…")
        self.remove = QPushButton("Remove Selected")
        self.clear = QPushButton("Clear List")
        for button in (self.choose, self.remove, self.clear): actions.addWidget(button)
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.apply = QPushButton("Add and Encode")
        self.apply.setProperty("themeRole", "primary")
        self.cancel = QPushButton("Cancel")
        buttons.addWidget(self.apply)
        buttons.addWidget(self.cancel)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.name.currentTextChanged.connect(self._update_name)
        self.choose.clicked.connect(self._choose_images)
        self.remove.clicked.connect(self._remove_selected)
        self.clear.clicked.connect(self._clear_images)
        self.apply.clicked.connect(self._start)
        self.cancel.clicked.connect(self._cancel)
        self.reset()

    def reset(self):
        if self.busy: return
        self.images.clear()
        self.drop_list.clear()
        self.name.clear()
        self.name.addItems(self.service.list_add_candidates())
        self.name.setCurrentIndex(-1)
        self.status.setText("Choose at least one training image, then review the creation request.")
        self._update_name()

    def _name(self):
        return " ".join(self.name.currentText().split()).strip()

    def _update_name(self, *_args):
        name = self._name()
        if not name: message = "Select a metadata-only DB person or enter a new name."
        elif self.service.find_recognition_name(name) is not None:
            message = f"A recognition profile already exists for '{name}'. Use Edit Images or Re-encode instead."
        else:
            record = self.service.get_person_record(name)
            message = "Existing Persons DB metadata will be linked." if record else "Recognition-only profile; DB metadata can be created afterward."
        self.info.setText(message)
        self._sync_controls()

    def _choose_images(self):
        patterns = " ".join(f"*{ext}" for ext in sorted(self.extensions))
        files, _ = QFileDialog.getOpenFileNames(self, "Select Training Images", "", f"Images ({patterns});;All Files (*)")
        self._add_paths(files)

    def _add_paths(self, paths):
        added, rejected = [], 0
        for raw in paths:
            path = os.path.abspath(os.path.expanduser(str(raw or "").strip()))
            if not os.path.isfile(path) or Path(path).suffix.lower() not in self.extensions:
                rejected += 1
                continue
            key = os.path.normcase(path)
            if key not in self.images:
                self.images[key] = path
                added.append(path)
        if added: self.drop_list.add_images(added)
        if rejected: self.status.setText(f"Ignored {rejected} unsupported or missing file(s).")
        self._sync_controls()

    def _remove_selected(self):
        for item in list(self.drop_list.selectedItems()):
            path = item.data(Qt.ItemDataRole.UserRole)
            if path: self.images.pop(os.path.normcase(os.path.abspath(path)), None)
            self.drop_list.takeItem(self.drop_list.row(item))
        self._sync_controls()

    def _clear_images(self):
        self.images.clear()
        self.drop_list.clear()
        self._sync_controls()

    def _sync_controls(self):
        valid = bool(self._name()) and self.service.find_recognition_name(self._name()) is None
        self.name.setEnabled(not self.busy)
        self.drop_list.setEnabled(not self.busy)
        self.choose.setEnabled(not self.busy)
        self.remove.setEnabled(not self.busy and bool(self.drop_list.selectedItems()))
        self.clear.setEnabled(not self.busy and bool(self.images))
        self.apply.setEnabled(not self.busy and valid and bool(self.images))
        self.cancel.setEnabled(not self.busy)

    def confirm_leave(self):
        if self.busy:
            QMessageBox.information(self, "Creation Running", "Wait until recognition-profile creation finishes.")
            return False
        if self.images or self._name():
            reply = QMessageBox.question(self, "Discard New Person", "Discard this pending recognition-profile creation?",
                                         QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                         QMessageBox.StandardButton.Cancel)
            if reply != QMessageBox.StandardButton.Discard: return False
        self.reset()
        return True

    def _cancel(self):
        if self.confirm_leave(): self.close_requested.emit()

    def _start(self):
        name, images = self._name(), list(self.images.values())
        if self.busy or not name or not images: return
        if self.service.find_recognition_name(name) is not None:
            QMessageBox.warning(self, "Recognition Profile Exists", f"'{name}' already has a recognition profile.")
            return
        if any(not os.path.isfile(path) for path in images):
            QMessageBox.warning(self, "Image Missing", "One or more training images changed or disappeared. Recheck the list.")
            return
        reply = QMessageBox.question(self, "Create Recognition Profile", f"Create '{name}' from {len(images)} image(s)?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return
        if self.service.find_recognition_name(name) is not None or any(not os.path.isfile(path) for path in images):
            QMessageBox.warning(self, "Sources Changed", "The profile or source images changed during confirmation. Review again.")
            return
        self.busy, self._result, self._error = True, None, ""
        begin = getattr(self.window(), "begin_person_operation", None)
        self._token = begin(f"Add Person: {name}") if callable(begin) else None
        self._sync_controls()
        self.status.setText(f"Creating '{name}' and generating recognition encodings…")
        self.thread = QThread(self)
        self.worker = AddPersonWorker(self.service, name, images)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._forward_progress)
        self.worker.log_message.connect(self._forward_log)
        self.worker.finished.connect(self._store_result)
        self.worker.error.connect(self._store_error)
        self.worker.completed.connect(self.thread.quit)
        self.worker.completed.connect(self.worker.deleteLater)
        self.thread.finished.connect(lambda: QTimer.singleShot(0, self._complete))
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _forward_progress(self, value):
        callback = getattr(self.window(), "progress_person_operation", None)
        if callable(callback) and self._token is not None: callback(self._token, value)

    def _forward_log(self, message):
        callback = getattr(self.window(), "display_message", None)
        if callable(callback): callback(message)

    def _store_result(self, result):
        self._result = result

    def _store_error(self, message):
        self._error = str(message or "Creation failed without an error message")

    def _complete(self):
        if not self.busy: return
        result = self._result
        error = self._error or ("Creation worker returned no result" if result is None else "")
        finish = getattr(self.window(), "finish_person_operation", None)
        if callable(finish) and self._token is not None: finish(self._token, error)
        self._token = None
        self.busy = False
        self.thread = self.worker = None
        if self._stopping: return
        self._sync_controls()
        if error:
            self.status.setText(f"Creation failed; source selection retained: {error}")
            QMessageBox.critical(self, "Add Person Failed", error)
            return
        parents = {str(Path(path).parent) for path in self.images.values()}
        message = (f"Recognition profile created for '{result.name}'.\n\nTraining images: {len(self.images)}\n"
                   f"Face encodings: {result.face_encodings}\nBody encodings: {result.body_encodings}")
        create_metadata = False
        if result.database_record_exists:
            QMessageBox.information(self, "Person Added", message + "\n\nExisting Persons DB record linked.")
        else:
            answer = QMessageBox.question(self, "Person Added", message + "\n\nCreate a Persons DB metadata record now?",
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
            create_metadata = answer == QMessageBox.StandardButton.Yes
        self.reset()
        self.close_requested.emit()
        self.person_added.emit(result)
        if create_metadata: self.create_db_record_requested.emit(result.name, parents.pop() if len(parents) == 1 else "")

    def shutdown(self):
        if self._stopping: return
        self._stopping = True
        if self.thread is not None:
            try:
                if self.thread.isRunning():
                    self.thread.quit()
                    self.thread.wait()
            except RuntimeError: pass
        if self.busy:
            self._error = self._error or "Creation result unavailable during shutdown"
            self._complete()
